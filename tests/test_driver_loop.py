# tests/test_driver_loop.py
import json
import subprocess
import pytest
from pathlib import Path
from multi_ship import driver, claude_cli, config as cfgmod

def _cfg():
    return cfgmod.Config(
        build_workflow="mmb", spec_glob="docs/specs/*.md", verify="true",
        notify="true", pr_body_convention="Closes #{issue}",
        complete_cmd="/complete-spec {slug}", test_cmd="true",
        build_invariants="x", smoke_instructions="y",
        roles={"scout": "haiku", "reader": "haiku", "planner": "opus",
               "judges": ["opus"], "coder": {"hard": "opus", "routine": "sonnet"},
               "verifier": "opus"},
    )

def test_single_item_ships(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            (state / f"verdict-{sid}.json").write_text(json.dumps({"ok": True, "reason": "meets DoD"}))
            return {"result": "judged"}
        return {"result": "ok"}  # complete_cmd / dream
    monkeypatch.setattr(claude_cli, "run", fake_run)
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)

    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]
    assert merges == ["http://pr/1"]

def test_judge_reject_then_fix_then_ship(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    calls = {"judge": 0}
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            calls["judge"] += 1
            ok = calls["judge"] >= 2  # reject first, pass on the post-fix re-judge
            (state / f"verdict-{sid}.json").write_text(json.dumps(
                {"ok": ok, "reason": "missing test" if not ok else "ok now"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]
    assert calls["judge"] == 2  # one reject + one post-fix pass

def test_judge_reject_twice_stops(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            (state / f"verdict-{sid}.json").write_text(json.dumps({"ok": False, "reason": "still broken"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: (_ for _ in ()).throw(AssertionError("must not merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md", "b.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert result["stopped_at"] == "a.md"

def test_continue_on_failure_advances_past_failed(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one a.md"):
            (state / "item-a.md.json").write_text(json.dumps({"status": "failed"}))
            return {"result": "x"}
        if prompt.startswith("/ship-one b.md"):
            (state / "item-b.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/2"}))
            return {"result": "x"}
        if prompt.startswith("/judge-shipped b.md"):
            (state / "verdict-b.md.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md", "b.md"], cfg=_cfg(),
                             stop_on_failure=False, state_dir=state)
    assert result["shipped"] == ["b.md"]
    assert result["stopped_at"] is None

def test_resume_completes_after_crash(tmp_path, monkeypatch):
    from multi_ship import runlog
    state = tmp_path / ".multi-ship"; state.mkdir(parents=True)
    rl = state / "run-log.json"
    runlog.init_run_log(rl, order=["a.md", "b.md"], stop_on_failure=True, notification_surface="none")
    runlog.set_item_status(rl, "a.md", "awaiting_judge"); runlog.set_item_status(rl, "a.md", "shipped")
    runlog.set_item_status(rl, "b.md", "awaiting_judge")   # crash state
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one b.md"):
            (state / "item-b.md.json").write_text(json.dumps({"status": "awaiting_judge", "pr": "http://pr/9"}))
            return {"result": "x"}
        if prompt.startswith("/judge-shipped b.md"):
            (state / "verdict-b.md.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md", "b.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state, resume=True)
    assert result["shipped"] == ["b.md"]   # a.md already shipped (skipped); b.md retried cleanly

# ---------------------------------------------------------------------------
# _merge_pr fail-soft: a failed branch deletion (e.g. a leftover worktree still
# holds the branch) must NOT crash the run once the PR is actually merged.
# Regression: a real run crashed in post-merge `--delete-branch` after the
# squash merge had already succeeded on GitHub.
# ---------------------------------------------------------------------------

def _fake_subprocess(responses):
    """Return a subprocess.run stand-in. `responses` maps a cmd-prefix tuple to
    (returncode, stdout, stderr). Honors check=True like the real thing so tests
    exercise real failure semantics; records every command in `calls`."""
    calls = []
    def run(cmd, **kw):
        calls.append(list(cmd))
        rc, out, err = 0, "", ""
        for prefix, resp in responses.items():
            if tuple(cmd[:len(prefix)]) == prefix:
                rc, out, err = resp
                break
        cp = subprocess.CompletedProcess(cmd, rc, out, err)
        if kw.get("check") and rc != 0:
            raise subprocess.CalledProcessError(rc, cmd, out, err)
        return cp
    run.calls = calls
    return run


def test_merge_pr_clean_success_does_not_query_state(monkeypatch):
    """A clean merge (rc 0) returns without raising and without a state query."""
    fake = _fake_subprocess({("gh", "pr", "merge"): (0, "", "")})
    monkeypatch.setattr(driver.subprocess, "run", fake)
    driver._merge_pr("http://pr/1", "/repo")  # must not raise
    assert not any(c[:3] == ["gh", "pr", "view"] for c in fake.calls)


def test_merge_pr_failsoft_when_branch_delete_fails_but_pr_merged(monkeypatch):
    """Merge command exits non-zero (branch held by a worktree) but the PR is
    actually MERGED -> swallow, do not crash the run."""
    fake = _fake_subprocess({
        ("gh", "pr", "merge"): (1, "", "cannot delete branch 'x' used by worktree"),
        ("gh", "pr", "view"): (0, "MERGED\n", ""),
    })
    monkeypatch.setattr(driver.subprocess, "run", fake)
    driver._merge_pr("http://pr/1", "/repo")  # must NOT raise
    assert any(c[:3] == ["gh", "pr", "view"] for c in fake.calls)


def test_merge_pr_raises_when_merge_truly_failed(monkeypatch):
    """Merge command exits non-zero AND the PR is not merged -> re-raise so the
    item fails (we must never record a ship that didn't merge)."""
    fake = _fake_subprocess({
        ("gh", "pr", "merge"): (1, "", "not mergeable: required checks failing"),
        ("gh", "pr", "view"): (0, "OPEN\n", ""),
    })
    monkeypatch.setattr(driver.subprocess, "run", fake)
    with pytest.raises(subprocess.CalledProcessError):
        driver._merge_pr("http://pr/1", "/repo")


def test_fix_prompt_neutralizes_quotes_and_newlines():
    from multi_ship.driver import _fix_prompt
    p = _fix_prompt("a.md", 'missing "foo" test\nand bar')
    assert p == "/ship-one a.md --fix \"missing 'foo' test and bar\""
    assert p.count('"') == 2  # only the wrapping quotes remain


# ---------------------------------------------------------------------------
# STEP 11 / STEP 12: dispatch routing — telegram vs shell vs none
# ---------------------------------------------------------------------------

def _cfg_notify(notify_value):
    """Helper: build a Config with a custom notify value."""
    return cfgmod.Config(
        build_workflow="mmb", spec_glob="docs/specs/*.md", verify="true",
        notify=notify_value, pr_body_convention="Closes #{issue}",
        complete_cmd="/complete-spec {slug}", test_cmd="true",
        build_invariants="x", smoke_instructions="y",
        roles={"scout": "haiku", "reader": "haiku", "planner": "opus",
               "judges": ["opus"], "coder": {"hard": "opus", "routine": "sonnet"},
               "verifier": "opus"},
        notify_telegram={},
    )


def _setup_end_of_run_state(tmp_path):
    """Create minimal state for _end_of_run: state dir, HANDOFF.md, run-log.json."""
    from multi_ship import runlog
    state = tmp_path / ".multi-ship"
    state.mkdir(parents=True, exist_ok=True)
    (state / "HANDOFF.md").write_text("# HANDOFF\n")
    rl = state / "run-log.json"
    runlog.init_run_log(rl, order=[], stop_on_failure=True, notification_surface="none")
    return state


def test_dispatch_telegram_calls_send_not_run_notify(tmp_path, monkeypatch):
    """With cfg.notify=='telegram', notify_telegram.send is called; run_notify is NOT."""
    from multi_ship import endrun, notify_telegram

    send_calls = []
    run_notify_calls = []
    monkeypatch.setattr(notify_telegram, "send", lambda cfg, repo, msg: send_calls.append(msg))
    monkeypatch.setattr(endrun, "run_notify", lambda cmd, msg: run_notify_calls.append(msg))

    state = _setup_end_of_run_state(tmp_path)
    cfg = _cfg_notify("telegram")
    driver._end_of_run(str(tmp_path), cfg, state, state / "run-log.json", [], None, {})

    assert len(send_calls) == 1
    assert len(run_notify_calls) == 0


def test_dispatch_other_string_calls_run_notify_not_send(tmp_path, monkeypatch):
    """With cfg.notify=='true' (any non-telegram string), run_notify IS called; send NOT."""
    from multi_ship import endrun, notify_telegram

    send_calls = []
    run_notify_calls = []
    monkeypatch.setattr(notify_telegram, "send", lambda cfg, repo, msg: send_calls.append(msg))
    monkeypatch.setattr(endrun, "run_notify", lambda cmd, msg: run_notify_calls.append(msg))

    state = _setup_end_of_run_state(tmp_path)
    cfg = _cfg_notify("true")
    driver._end_of_run(str(tmp_path), cfg, state, state / "run-log.json", [], None, {})

    assert len(send_calls) == 0
    assert len(run_notify_calls) == 1


def test_dispatch_none_no_telegram(tmp_path, monkeypatch):
    """With cfg.notify=='none', send NOT called (shell path handles no-op)."""
    from multi_ship import endrun, notify_telegram

    send_calls = []
    monkeypatch.setattr(notify_telegram, "send", lambda cfg, repo, msg: send_calls.append(msg))
    # Let run_notify run normally (it's a no-op for 'none')

    state = _setup_end_of_run_state(tmp_path)
    cfg = _cfg_notify("none")
    driver._end_of_run(str(tmp_path), cfg, state, state / "run-log.json", [], None, {})

    assert len(send_calls) == 0


def test_item_id_uses_filename_not_full_path(tmp_path, monkeypatch):
    # Regression: a spec under docs/specs/ must key state files by FILENAME
    # (item-x.md.json), not the full path (item-docs/specs/x.md.json → nested,
    # FileNotFoundError). Caught by the first live smoke.
    state = tmp_path / ".multi-ship"; state.mkdir(parents=True)
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-x.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/3"}))
            return {"result": "x"}
        if prompt.startswith("/judge-shipped"):
            (state / "verdict-x.md.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["docs/specs/x.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["docs/specs/x.md"]
