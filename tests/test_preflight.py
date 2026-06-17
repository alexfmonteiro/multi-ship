# tests/test_preflight.py
import shutil
from pathlib import Path
from multi_ship import preflight, cli

TEMPLATE = Path(__file__).parent.parent / "templates" / "multi-ship.json"


def _repo_with_spec(tmp_path, body):
    (tmp_path / ".claude").mkdir(parents=True)
    shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")
    spec = tmp_path / "docs" / "specs" / "x.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(body)
    return "docs/specs/x.md"


def test_main_preflight_flags_unready_spec(tmp_path, capsys):
    rel = _repo_with_spec(tmp_path, "---\nIssue: 0\n---\n# x\n")  # placeholder, no DoD
    rc = cli.main(["preflight", rel, "--repo", str(tmp_path)])
    assert rc == 2
    out = capsys.readouterr()
    assert "placeholder issue" in (out.out + out.err).lower()


def test_main_preflight_ok_for_ready_spec(tmp_path):
    rel = _repo_with_spec(
        tmp_path, "---\nIssue: 11\n---\n# x\n## Definition of Done\n- [ ] y\n")
    rc = cli.main(["preflight", rel, "--repo", str(tmp_path)])
    assert rc == 0


def _spec(issue="11", dod=True, extra=""):
    body = f"---\nIssue: {issue}\ntitle: \"x\"\n---\n\n# Spec\n\n## Goal\nstuff\n"
    if dod:
        body += "\n## Definition of Done\n- [ ] thing\n"
    return body + extra


def test_ready_spec_has_no_problems():
    assert preflight.lint_spec(_spec()) == []


def test_placeholder_issue_zero_flagged():
    probs = preflight.lint_spec(_spec(issue="0"))
    assert any("placeholder issue" in p.lower() for p in probs)


def test_missing_issue_frontmatter_flagged():
    text = "---\ntitle: \"x\"\n---\n\n## Definition of Done\n- [ ] thing\n"
    probs = preflight.lint_spec(text)
    assert any("issue" in p.lower() for p in probs)


def test_missing_definition_of_done_flagged():
    probs = preflight.lint_spec(_spec(dod=False))
    assert any("definition of done" in p.lower() for p in probs)


def test_tbd_marker_flagged():
    probs = preflight.lint_spec(_spec(extra="\nThe retry count is TBD.\n"))
    assert any("TBD" in p for p in probs)


def test_lint_specs_skips_clean_and_reports_dirty(tmp_path):
    good = tmp_path / "good.md"; good.write_text(_spec())
    bad = tmp_path / "bad.md"; bad.write_text(_spec(issue="0"))
    out = preflight.lint_specs([good, bad])
    assert str(good) not in out
    assert str(bad) in out


def test_lint_specs_reports_missing_file(tmp_path):
    missing = tmp_path / "nope.md"
    out = preflight.lint_specs([missing])
    assert out[str(missing)] == ["file not found"]
