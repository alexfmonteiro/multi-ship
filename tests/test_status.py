# tests/test_status.py
import json
from multi_ship import cli
from multi_ship.cli import format_status, _pr_label, cmd_status

def _log():
    return {
        "stop_on_failure": True,
        "items": [
            {"id": "P15.md", "status": "shipped", "pr": "https://github.com/o/r/pull/41"},
            {"id": "P16.md", "status": "shipped", "pr": "42"},
            {"id": "P17.md", "status": "needs_fix", "pr": "43", "judge_reason": "missing test"},
            {"id": "P18.md", "status": "pending"},
            {"id": "P19.md", "status": "failed", "failure_kind": "plan_gate_rework",
             "parent_notes": "verified blockers; fold G3"},
            {"id": "P20.md", "status": "failed", "parent_notes": "bare note no kind"},
        ],
    }

def test_pr_label_from_number_and_url():
    assert _pr_label("42") == "#42"
    assert _pr_label("https://github.com/o/r/pull/41") == "#41"
    assert _pr_label("") == ""
    assert _pr_label(None) == ""

def test_format_status_summary_and_rows():
    out = format_status(_log(), "/repo", color=False)
    assert "shipped 2/6" in out
    assert "stop on first failure" in out
    # every item id appears, statuses are humanized, judge reason shown
    for sid in ("P15.md", "P16.md", "P17.md", "P18.md"):
        assert sid in out
    assert "needs-fix" in out
    assert "missing test" in out
    # no ANSI when color=False
    assert "\033[" not in out

def test_format_status_shows_failure_kind_and_parent_notes():
    out = format_status(_log(), "/repo", color=False)
    assert "[plan_gate_rework]" in out
    assert "verified blockers; fold G3" in out
    # judge_reason still wins the fallback for the needs_fix row
    assert "missing test" in out


def test_format_status_backcompat_no_kind():
    out = format_status(_log(), "/repo", color=False)
    # the failed item with parent_notes but no failure_kind renders a bare note
    bare = next(ln for ln in out.splitlines() if "bare note no kind" in ln)
    assert "[" not in bare


def test_format_status_colors_when_requested():
    out = format_status(_log(), "/repo", color=True)
    assert "\033[" in out

def test_format_status_empty_items():
    out = format_status({"stop_on_failure": False, "items": []}, "/repo")
    assert "shipped 0/0" in out
    assert "no items" in out

def test_cmd_status_missing_runlog(tmp_path, capsys):
    rc = cmd_status(str(tmp_path))
    assert rc == 1
    assert "no run-log" in capsys.readouterr().err

def test_cmd_status_reads_runlog(tmp_path, capsys):
    sd = tmp_path / ".multi-ship"
    sd.mkdir()
    (sd / "run-log.json").write_text(json.dumps(_log()))
    rc = cmd_status(str(tmp_path))
    assert rc == 0
    assert "shipped 2/6" in capsys.readouterr().out

def test_main_status_routes(tmp_path, capsys):
    sd = tmp_path / ".multi-ship"
    sd.mkdir()
    (sd / "run-log.json").write_text(json.dumps(_log()))
    rc = cli.main(["status", str(tmp_path)])
    assert rc == 0
    assert "shipped 2/6" in capsys.readouterr().out
