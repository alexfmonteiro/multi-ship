# tests/test_runlog.py
import json
import pytest
from multi_ship.runlog import (
    init_run_log, read_run_log, set_item_status, StatusError,
)

def test_init_creates_log_with_pending_items(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md", "b.md"], stop_on_failure=True, notification_surface="none")
    log = read_run_log(p)
    assert [i["id"] for i in log["items"]] == ["a.md", "b.md"]
    assert all(i["status"] == "pending" for i in log["items"])
    assert log["stop_on_failure"] is True

def test_init_is_fail_closed_idempotent_guard(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    with pytest.raises(StatusError, match="already exists"):
        init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")

def test_valid_transition_pending_to_awaiting_to_shipped(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    set_item_status(p, "a.md", "shipped")
    log = read_run_log(p)
    assert log["items"][0]["status"] == "shipped"
    assert log["items"][0]["pr"] == "http://pr/1"

def test_invalid_transition_pending_to_shipped_raises(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    with pytest.raises(StatusError, match="pending -> shipped"):
        set_item_status(p, "a.md", "shipped")

def test_needs_fix_cycle(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge")
    set_item_status(p, "a.md", "needs_fix")
    set_item_status(p, "a.md", "awaiting_judge")
    set_item_status(p, "a.md", "shipped")
    assert read_run_log(p)["items"][0]["status"] == "shipped"

def test_unknown_item_raises(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    with pytest.raises(StatusError, match="unknown item"):
        set_item_status(p, "z.md", "awaiting_judge")

def test_reset_for_resume_nonterminal_and_failed_to_pending(tmp_path):
    from multi_ship.runlog import reset_for_resume
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md", "b.md", "c.md", "d.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge"); set_item_status(p, "a.md", "shipped")
    set_item_status(p, "b.md", "awaiting_judge")          # crashed mid-judge
    set_item_status(p, "c.md", "awaiting_judge"); set_item_status(p, "c.md", "failed")  # failed last run
    # d.md stays pending
    reset_for_resume(p)
    st = {i["id"]: i["status"] for i in read_run_log(p)["items"]}
    assert st == {"a.md": "shipped", "b.md": "pending", "c.md": "pending", "d.md": "pending"}

# --- transient fields are cleared on every transition ------------------------

def test_transition_clears_stale_transient_fields(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    set_item_status(p, "a.md", "needs_fix", judge_reason="missing test")
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    set_item_status(p, "a.md", "shipped")
    it = read_run_log(p)["items"][0]
    assert it["status"] == "shipped"
    assert "judge_reason" not in it, "stale rejection text must not survive a ship"

def test_force_pending_fields_cleared_on_next_transition(tmp_path):
    from multi_ship.runlog import force_pending
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    force_pending(p, "a.md", paused_reason="quota_exhausted", resets_at="5pm")
    it = read_run_log(p)["items"][0]
    assert it["paused_reason"] == "quota_exhausted" and it["resets_at"] == "5pm"
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    it = read_run_log(p)["items"][0]
    assert "paused_reason" not in it and "resets_at" not in it

def test_write_leaves_no_tmp_files(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge")
    leftovers = [f for f in p.parent.iterdir() if f.name != "run-log.json"]
    assert leftovers == []
