# tests/test_driver_loop.py
import json
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

def test_fix_prompt_neutralizes_quotes_and_newlines():
    from multi_ship.driver import _fix_prompt
    p = _fix_prompt("a.md", 'missing "foo" test\nand bar')
    assert p == "/ship-one a.md --fix \"missing 'foo' test and bar\""
    assert p.count('"') == 2  # only the wrapping quotes remain


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
