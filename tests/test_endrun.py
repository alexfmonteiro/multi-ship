# tests/test_endrun.py
from multi_ship.endrun import collect_followups, compare_git_state, format_notification

def test_collect_followups_dedups_preserving_order():
    reports = [{"followups": ["a", "b"]}, {"followups": ["b", "c"]}, {}]
    assert collect_followups(reports) == ["a", "b", "c"]

def test_collect_followups_handles_missing_and_none():
    reports = [{"followups": None}, {"id": "x"}]
    assert collect_followups(reports) == []

def test_compare_git_state_detects_head_move():
    before = {"head": "aaa", "porcelain": []}
    after = {"head": "bbb", "porcelain": []}
    assert any("HEAD moved" in p for p in compare_git_state(before, after))

def test_compare_git_state_detects_new_dirty():
    before = {"head": "aaa", "porcelain": [" M x.py"]}
    after = {"head": "aaa", "porcelain": [" M x.py", "?? new.py"]}
    assert any("new.py" in p for p in compare_git_state(before, after))

def test_compare_git_state_clean():
    snap = {"head": "aaa", "porcelain": [" M x.py"]}
    assert compare_git_state(snap, snap) == []

def test_format_notification_all_shipped():
    msg = format_notification(["a.md", "b.md"], None, [], "/s/run-log.json", None)
    assert "all shipped" in msg
    assert "a.md" in msg and "b.md" in msg

def test_format_notification_stopped_with_followups():
    msg = format_notification(["a.md"], "b.md", ["do X", "do Y"], "/s/run-log.json", "/s/followups.md")
    assert "stopped at: b.md" in msg
    assert "do X" in msg and "/s/followups.md" in msg
