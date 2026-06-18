# tests/test_fresh_run.py
import json
from pathlib import Path

from multi_ship import cli, driver


# --- minimal valid config -------------------------------------------------

_CONFIG = {
    "build_workflow": "mmb", "spec_glob": "docs/specs/*.md", "verify": "true",
    "notify": "none", "pr_body_convention": "Closes #{issue}",
    "complete_cmd": "/complete-spec {slug}", "test_cmd": "true",
    "build_invariants": "x", "smoke_instructions": "y",
    "roles": {"scout": "haiku", "reader": "haiku", "planner": "opus",
              "judges": ["opus"], "coder": {"hard": "opus", "routine": "sonnet"},
              "verifier": "opus"},
}


def _write_config(repo: Path):
    cd = repo / ".claude"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "multi-ship.json").write_text(json.dumps(_CONFIG))


def _completed_runlog(state_dir: Path, order, statuses=None):
    statuses = statuses or {s: "shipped" for s in order}
    state_dir.mkdir(parents=True, exist_ok=True)
    log = {
        "stop_on_failure": True, "notification_surface": "none",
        "order": list(order),
        "items": [{"id": s, "status": statuses[s]} for s in order],
    }
    (state_dir / "run-log.json").write_text(json.dumps(log))


# --- Case 4a / 4b: _archive_completed_run helper --------------------------

def test_archive_moves_all_state_files(tmp_path):
    sd = tmp_path / ".multi-ship"
    sd.mkdir(parents=True)
    (sd / "run-log.json").write_text("{}")
    (sd / "item-a.md.json").write_text("{}")
    (sd / "verdict-a.md.json").write_text("{}")
    dest = cli._archive_completed_run(sd, ts="fixed")
    assert dest == sd / "archive" / "fixed"
    for name in ("run-log.json", "item-a.md.json", "verdict-a.md.json"):
        assert (dest / name).exists()
        assert not (sd / name).exists()
    assert (sd / "archive").exists()


def test_archive_dest_under_state_dir(tmp_path):
    sd = tmp_path / ".multi-ship"
    sd.mkdir(parents=True)
    (sd / "run-log.json").write_text("{}")
    dest = cli._archive_completed_run(sd, ts="fixed")
    assert str(dest).startswith(str(sd))
    assert "archive" in dest.parts


def test_archive_idempotent_separate_subdirs(tmp_path):
    sd = tmp_path / ".multi-ship"
    sd.mkdir(parents=True)
    (sd / "run-log.json").write_text("{}")
    d1 = cli._archive_completed_run(sd, ts="fixed")
    (sd / "run-log.json").write_text("{}")
    d2 = cli._archive_completed_run(sd, ts="fixed2")
    assert d1 != d2
    assert d1.exists() and d2.exists()
    assert (d1 / "run-log.json").exists()
    assert (d2 / "run-log.json").exists()


# --- main() auto-archive matrix -------------------------------------------

def _stub_run_loop(monkeypatch, repo):
    """Replace driver.run_loop with a stub that asserts run-log absence at call
    time and records that it was invoked."""
    calls = {}
    rlp = repo / ".multi-ship" / "run-log.json"
    def stub(**kw):
        assert not rlp.exists(), "run-log.json must not exist when run_loop is called"
        calls["kw"] = kw
        return {"shipped": [], "stopped_at": None}
    monkeypatch.setattr(driver, "run_loop", stub)
    return calls


def _spec(repo: Path, name: str):
    d = repo / "docs" / "specs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("# spec\n")
    return f"docs/specs/{name}"


def test_main_all_terminal_different_specs_auto_archives(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    _write_config(repo)
    _spec(repo, "new.md")
    _completed_runlog(repo / ".multi-ship", order=["docs/specs/old.md"])
    calls = _stub_run_loop(monkeypatch, repo)
    rc = cli.main(["docs/specs/new.md", "--repo", str(repo)])
    assert calls.get("kw") is not None
    assert (repo / ".multi-ship" / "archive").exists()
    archived = list((repo / ".multi-ship" / "archive").iterdir())
    assert len(archived) == 1
    assert rc == 0


def test_main_all_terminal_same_specs_refuses(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    _write_config(repo)
    _spec(repo, "old.md")
    _completed_runlog(repo / ".multi-ship", order=["docs/specs/old.md"])
    monkeypatch.setattr(driver, "run_loop",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    rc = cli.main(["docs/specs/old.md", "--repo", str(repo)])
    assert rc == 2
    assert not (repo / ".multi-ship" / "archive").exists()


def test_main_non_terminal_refuses_no_archive(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    _write_config(repo)
    _spec(repo, "new.md")
    _completed_runlog(repo / ".multi-ship", order=["docs/specs/old.md"],
                      statuses={"docs/specs/old.md": "awaiting_judge"})
    monkeypatch.setattr(driver, "run_loop",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    rc = cli.main(["docs/specs/new.md", "--repo", str(repo)])
    assert rc == 2
    assert not (repo / ".multi-ship" / "archive").exists()


def test_main_fresh_always_archives_and_proceeds(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    _write_config(repo)
    _spec(repo, "old.md")
    # same specs as order + non-terminal: --fresh still archives & proceeds
    _completed_runlog(repo / ".multi-ship", order=["docs/specs/old.md"],
                      statuses={"docs/specs/old.md": "awaiting_judge"})
    calls = _stub_run_loop(monkeypatch, repo)
    rc = cli.main(["docs/specs/old.md", "--repo", str(repo), "--fresh"])
    assert calls.get("kw") is not None
    assert (repo / ".multi-ship" / "archive").exists()
    assert rc == 0


def test_main_resume_never_archives(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    _write_config(repo)
    _spec(repo, "old.md")
    _completed_runlog(repo / ".multi-ship", order=["docs/specs/old.md"])
    calls = {}
    def stub(**kw):
        calls["kw"] = kw
        return {"shipped": [], "stopped_at": None}
    monkeypatch.setattr(driver, "run_loop", stub)
    rc = cli.main(["docs/specs/old.md", "--repo", str(repo), "--resume"])
    assert calls.get("kw") is not None
    assert not (repo / ".multi-ship" / "archive").exists()
    assert rc == 0
