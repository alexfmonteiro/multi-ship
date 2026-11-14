# tests/test_endrun.py
import subprocess
from multi_ship import endrun
from multi_ship.endrun import (collect_followups, compare_git_state, format_notification,
                               git_snapshot, is_ancestor)

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

def test_compare_git_state_fast_forward_same_branch_is_expected():
    before = {"head": "aaa", "branch": "main", "porcelain": []}
    after = {"head": "bbb", "branch": "main", "porcelain": []}
    assert compare_git_state(before, after, fast_forward=True) == []

def test_compare_git_state_non_ancestor_head_warns():
    before = {"head": "aaa", "branch": "main", "porcelain": []}
    after = {"head": "bbb", "branch": "main", "porcelain": []}
    assert any("HEAD moved" in p for p in compare_git_state(before, after, fast_forward=False))

def test_compare_git_state_branch_switch_warns():
    before = {"head": "aaa", "branch": "main", "porcelain": []}
    after = {"head": "bbb", "branch": "feature", "porcelain": []}
    problems = compare_git_state(before, after, fast_forward=True)
    assert any("branch switched: main -> feature" in p for p in problems)

def test_compare_git_state_detached_head_move_warns():
    before = {"head": "aaa", "branch": "HEAD", "porcelain": []}
    after = {"head": "bbb", "branch": "HEAD", "porcelain": []}
    assert any("HEAD moved" in p for p in compare_git_state(before, after, fast_forward=True))

def test_compare_git_state_fast_forward_still_reports_new_dirty():
    before = {"head": "aaa", "branch": "main", "porcelain": []}
    after = {"head": "bbb", "branch": "main", "porcelain": ["?? new.py"]}
    problems = compare_git_state(before, after, fast_forward=True)
    assert len(problems) == 1 and "new.py" in problems[0]

def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()

def _commit(repo, msg):
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit",
         "--allow-empty", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")

def test_snapshot_and_is_ancestor_on_real_repo(tmp_path):
    repo = str(tmp_path)
    _git(repo, "init", "-q", "-b", "main")
    old = _commit(repo, "one")
    snap = git_snapshot(repo)
    assert snap["head"] == old and snap["branch"] == "main"
    new = _commit(repo, "two")
    assert is_ancestor(repo, old, new)
    assert not is_ancestor(repo, new, old)
    assert not is_ancestor(repo, old, "not-a-sha")

def test_is_ancestor_fails_soft_without_git(monkeypatch):
    def boom(*a, **k):
        raise OSError("git not found")
    monkeypatch.setattr(endrun.subprocess, "run", boom)
    assert is_ancestor(".", "aaa", "bbb") is False
    before = {"head": "aaa", "branch": "main", "porcelain": []}
    after = {"head": "bbb", "branch": "main", "porcelain": []}
    ff = is_ancestor(".", "aaa", "bbb")
    assert any("HEAD moved" in p for p in compare_git_state(before, after, fast_forward=ff))

def test_format_notification_all_shipped():
    msg = format_notification(["a.md", "b.md"], None, [], "/s/run-log.json", None)
    assert "all shipped" in msg
    assert "a.md" in msg and "b.md" in msg

def test_format_notification_stopped_with_followups():
    msg = format_notification(["a.md"], "b.md", ["do X", "do Y"], "/s/run-log.json", "/s/followups.md")
    assert "stopped at: b.md" in msg
    assert "do X" in msg and "/s/followups.md" in msg


def _why_line(msg):
    for ln in msg.splitlines():
        if ln.startswith("why: "):
            return ln
    return None


def test_format_notification_stop_kind_and_notes():
    msg = format_notification(
        ["a.md"], "b.md", [], "/s/run-log.json", None,
        stop_kind="plan_gate_rework", stop_notes="panel REWORK: G3 premise false")
    # the kind token must appear on the stopped-at status line
    status_line = next(ln for ln in msg.splitlines() if "stopped at: b.md" in ln)
    assert "[plan_gate_rework]" in status_line
    why = _why_line(msg)
    assert why is not None
    assert "panel REWORK: G3 premise false" in why


def test_format_notification_truncates_long_notes():
    msg = format_notification(
        ["a.md"], "b.md", [], "/s/run-log.json", None,
        stop_kind="x", stop_notes="x" * 400)
    why = _why_line(msg)
    assert why is not None
    body = why[len("why: "):]
    assert len(body) <= 303
    assert body.endswith("…")


def test_format_notification_notes_collapse_newlines():
    msg = format_notification(
        ["a.md"], "b.md", [], "/s/run-log.json", None,
        stop_kind="x", stop_notes="line1\nline2")
    why = _why_line(msg)
    assert why is not None
    assert "line1 line2" in why
    assert "\n" not in why[len("why: "):]


def test_format_notification_stopped_without_kind_or_notes():
    msg = format_notification(
        ["a.md"], "b.md", [], "/s/run-log.json", None,
        stop_kind=None, stop_notes=None)
    status_line = next(ln for ln in msg.splitlines() if "stopped at: b.md" in ln)
    assert "[" not in status_line
    assert _why_line(msg) is None


def test_format_notification_lists_bookkeeping_errors():
    msg = format_notification(["a.md", "b.md"], None, [], "/s/run-log.json", None,
                              bookkeeping=[("a.md", "claude -p timed out after 7200s")])
    assert "all shipped" in msg
    assert "bookkeeping failed (1)" in msg
    assert "  - a.md: claude -p timed out after 7200s" in msg


def test_format_notification_no_bookkeeping_section_when_clean():
    msg = format_notification(["a.md"], None, [], "/s/run-log.json", None)
    assert "bookkeeping" not in msg
