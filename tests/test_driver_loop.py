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
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["failure_kind"] == "judge_rejected"

def test_ship_one_failed_propagates_kind_and_notes(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "failed", "failure_kind": "plan_gate_rework",
                 "parent_notes": "fold the G3 premise"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                    stop_on_failure=True, state_dir=state)
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["failure_kind"] == "plan_gate_rework"
    assert a["parent_notes"] == "fold the G3 premise"

def test_ship_one_failed_without_kind_defaults_unknown(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps({"status": "failed"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                    stop_on_failure=True, state_dir=state)
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["failure_kind"] == "unknown"

def test_unexpected_error_sets_failure_kind_error(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "x"}
        if prompt.startswith("/judge-shipped"):
            (state / f"verdict-{sid}.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    def boom(pr, repo):
        raise subprocess.CalledProcessError(1, ["gh", "pr", "merge"])
    monkeypatch.setattr(driver, "_merge_pr", boom)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                    stop_on_failure=True, state_dir=state)
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["failure_kind"] == "error"

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


# ---------------------------------------------------------------------------
# Crash-proof loop: an unexpected error in _process_item (e.g. a genuine merge
# CalledProcessError) must fail the ITEM and still reach end-of-run/notify —
# never crash the whole driver. Regression: the first real run died via an
# uncaught CalledProcessError before the notify could fire.
# ---------------------------------------------------------------------------

def test_unexpected_error_fails_item_and_reaches_end_of_run(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "x"}
        if prompt.startswith("/judge-shipped"):
            (state / f"verdict-{sid}.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "x"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    def boom(pr, repo):
        raise subprocess.CalledProcessError(1, ["gh", "pr", "merge"])
    monkeypatch.setattr(driver, "_merge_pr", boom)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    reached = {}
    real_eor = driver._end_of_run
    monkeypatch.setattr(driver, "_end_of_run",
                        lambda *a, **k: reached.setdefault("ran", True))
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert reached.get("ran"), "end-of-run/notify must run even after an unexpected error"
    assert result["shipped"] == []
    assert result["stopped_at"] == "a.md"


# ---------------------------------------------------------------------------
# Idempotent recovery: if a prior attempt already merged the item's PR, --resume
# must NOT rebuild/re-judge/re-merge — just finish the tail (archive + shipped).
# ---------------------------------------------------------------------------

def test_resume_skips_rebuild_when_pr_already_merged(tmp_path, monkeypatch):
    from multi_ship import runlog
    state = tmp_path / ".multi-ship"; state.mkdir(parents=True)
    rl = state / "run-log.json"
    runlog.init_run_log(rl, order=["a.md"], stop_on_failure=True, notification_surface="none")
    # Prior run got as far as a merged PR but crashed before recording shipped.
    (state / "item-a.md.json").write_text(json.dumps(
        {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
    calls = []
    def fake_run(prompt, repo, timeout=7200):
        calls.append(prompt.split()[0])
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_pr_state", lambda pr, repo: "MERGED")
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state, resume=True)
    assert result["shipped"] == ["a.md"]
    assert "/ship-one" not in calls, "must not rebuild an already-merged item"
    assert "/judge-shipped" not in calls, "must not re-judge"
    assert merges == [], "must not re-merge"
    assert "/complete-spec" in calls, "must still archive (complete_cmd)"


# ---------------------------------------------------------------------------
# Worktree cleanup: the item's build worktree is removed (post-build) so it
# stops leaking and can't block branch deletion.
# ---------------------------------------------------------------------------

def test_cleanup_worktree_removes_the_branch_worktree(monkeypatch):
    porcelain = ("worktree /repo\nHEAD aaa\nbranch refs/heads/main\n\n"
                 "worktree /repo/.claude/worktrees/wf_1\nHEAD bbb\nbranch refs/heads/spec/a\n")
    fake = _fake_subprocess({
        ("git", "worktree", "list"): (0, porcelain, ""),
        ("git", "worktree", "remove"): (0, "", ""),
    })
    monkeypatch.setattr(driver.subprocess, "run", fake)
    driver._cleanup_worktree("spec/a", "/repo")
    removes = [c for c in fake.calls if c[:3] == ["git", "worktree", "remove"]]
    assert removes and removes[0][-1] == "/repo/.claude/worktrees/wf_1"


def test_cleanup_worktree_noop_when_branch_not_in_a_worktree(monkeypatch):
    fake = _fake_subprocess({
        ("git", "worktree", "list"): (0, "worktree /repo\nbranch refs/heads/main\n", ""),
    })
    monkeypatch.setattr(driver.subprocess, "run", fake)
    driver._cleanup_worktree("spec/a", "/repo")
    assert not any(c[:3] == ["git", "worktree", "remove"] for c in fake.calls)


def test_cleanup_worktree_empty_branch_is_noop(monkeypatch):
    fake = _fake_subprocess({})
    monkeypatch.setattr(driver.subprocess, "run", fake)
    driver._cleanup_worktree("", "/repo")
    assert fake.calls == []


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


def test_end_of_run_notification_includes_failure_kind_token(tmp_path, monkeypatch):
    """_end_of_run looks up the stopped item and surfaces its failure_kind +
    parent_notes in the notification text."""
    from multi_ship import endrun, runlog
    state = tmp_path / ".multi-ship"
    state.mkdir(parents=True, exist_ok=True)
    (state / "HANDOFF.md").write_text("# HANDOFF\n")
    rl = state / "run-log.json"
    runlog.init_run_log(rl, order=["a.md"], stop_on_failure=True, notification_surface="none")
    runlog.set_item_status(rl, "a.md", "failed",
                           failure_kind="plan_gate_rework", parent_notes="fold G3")
    captured = []
    monkeypatch.setattr(endrun, "run_notify", lambda cmd, msg: captured.append(msg))
    driver._end_of_run(str(tmp_path), _cfg_notify("true"), state, rl, [], "a.md", {})
    assert captured
    assert "[plan_gate_rework]" in captured[0]
    assert "fold G3" in captured[0]


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


# --- session-quota guardrails ----------------------------------------------

def test_quota_preflight_pauses_clean_without_building(tmp_path, monkeypatch):
    """Pre-flight probe says the quota is out -> pause cleanly, never call
    ship-one, leave the item PENDING (not failed) for a clean --resume."""
    state = tmp_path / ".multi-ship"
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    monkeypatch.setattr(claude_cli, "probe_quota",
                        lambda repo: (False, "5:20pm (America/Sao_Paulo)"))
    def no_build(prompt, repo, timeout=7200):
        raise AssertionError(f"no claude call expected on a quota pause: {prompt}")
    monkeypatch.setattr(claude_cli, "run", no_build)

    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert result["stopped_at"] is None
    assert result["paused"]["item"] == "a.md"
    assert result["paused"]["resets_at"] == "5:20pm (America/Sao_Paulo)"
    log = json.loads((state / "run-log.json").read_text())
    assert log["items"][0]["status"] == "pending"  # NOT failed/plan_gate_rework

def test_dream_run_failure_is_non_fatal(tmp_path, monkeypatch):
    """A /dream-run that hits the quota (or any error) must NOT crash the run."""
    state = tmp_path / ".multi-ship"
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(claude_cli, "probe_quota", lambda repo: (True, None))
    monkeypatch.setattr(driver.runlog, "worth_dreaming", lambda log, txt: True)
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "b"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            (state / "verdict-a.md.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "judged"}
        if prompt == "/dream-run":
            raise claude_cli.QuotaExhausted("quota", resets_at="5pm")
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)

    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]  # the dream-run crash did NOT kill the run

def test_wait_for_quota_retries_then_ships(tmp_path, monkeypatch):
    """--wait-for-quota: first probe is out, _wait_for_quota returns True, the
    re-probe succeeds, and the item ships in the same invocation."""
    state = tmp_path / ".multi-ship"
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_wait_for_quota", lambda resets, repo: True)
    probes = {"n": 0}
    def fake_probe(repo):
        probes["n"] += 1
        return (False, "5pm") if probes["n"] == 1 else (True, None)
    monkeypatch.setattr(claude_cli, "probe_quota", fake_probe)
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "b"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            (state / "verdict-a.md.json").write_text(json.dumps({"ok": True, "reason": "ok"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)

    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state, wait_for_quota=True)
    assert result["shipped"] == ["a.md"]
    assert result["paused"] is None
    assert probes["n"] == 2  # paused once, retried after the (faked) wait

def test_seconds_until_reset_parses_tz_phrase():
    secs = driver._seconds_until_reset("5:20pm (America/Sao_Paulo)")
    assert secs is not None and 0 < secs <= 24 * 3600
    assert driver._seconds_until_reset("not a time") is None
    assert driver._seconds_until_reset(None) is None

# ---------------------------------------------------------------------------
# Judge fail-open: a judge crash or a judge that writes no fresh verdict must
# NOT fail the item — README contract: "judge error → fail-open: log, proceed".
# Quota during the judge still pauses (it is not a judge failure).
# ---------------------------------------------------------------------------

def test_judge_crash_fails_open_and_merges(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            raise claude_cli.ClaudeError("judge session crashed")
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]
    assert merges == ["http://pr/1"]

def test_judge_writes_no_fresh_verdict_fails_open(tmp_path, monkeypatch):
    """Judge session returns fine but never (re)writes verdict-<id>.json: a STALE
    verdict from a prior round must not be trusted — fail-open instead."""
    state = tmp_path / ".multi-ship"; state.mkdir(parents=True)
    # Stale verdict from a previous round, saying REJECT. It must be ignored.
    (state / "verdict-a.md.json").write_text(json.dumps({"ok": False, "reason": "old"}))
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            return {"result": "judged but wrote nothing"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]  # fail-open, not judge_rejected via stale file
    assert merges == ["http://pr/1"]

def test_quota_during_judge_still_pauses(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            raise claude_cli.QuotaExhausted("quota", resets_at="5pm")
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(claude_cli, "probe_quota", lambda repo: (True, None))
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert result["paused"]["item"] == "a.md"
    log = json.loads((state / "run-log.json").read_text())
    assert log["items"][0]["status"] == "pending"

# ---------------------------------------------------------------------------
# --fix path: same freshness + failed-status discipline as the first build.
# ---------------------------------------------------------------------------

def test_fix_reporting_failed_stops_with_builder_kind(tmp_path, monkeypatch):
    """ship-one --fix writes status=failed (needs_redesign): the item must fail
    with the BUILDER's kind, not proceed to a second judge round."""
    state = tmp_path / ".multi-ship"
    judges = {"n": 0}
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one a.md --fix"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "failed", "failure_kind": "needs_redesign",
                 "parent_notes": "cannot fix without redesign"}))
            return {"result": "fix failed"}
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            judges["n"] += 1
            (state / "verdict-a.md.json").write_text(
                json.dumps({"ok": False, "reason": "missing test"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert judges["n"] == 1, "a failed fix must not be re-judged"
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["status"] == "failed"
    assert a["failure_kind"] == "needs_redesign"

def test_fix_writing_no_fresh_report_fails_item(tmp_path, monkeypatch):
    """ship-one --fix returns without rewriting item-<id>.json: honest error,
    not a re-judge of the stale pre-fix report."""
    state = tmp_path / ".multi-ship"
    judges = {"n": 0}
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one a.md --fix"):
            return {"result": "crashed without writing"}
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            judges["n"] += 1
            (state / "verdict-a.md.json").write_text(
                json.dumps({"ok": False, "reason": "missing test"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert judges["n"] == 1
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["status"] == "failed"
    assert a["failure_kind"] == "error"

def test_item_report_without_pr_fails_with_clear_error(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "branch": "spec/a"}))  # no "pr"
            return {"result": "built"}
        raise AssertionError(f"no judge call expected without a pr: {prompt}")
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(claude_cli, "probe_quota", lambda repo: (True, None))
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                    stop_on_failure=True, state_dir=state)
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["status"] == "failed"
    assert "no 'pr'" in a["error"]
