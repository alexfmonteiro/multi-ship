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
