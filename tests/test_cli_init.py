# tests/test_cli_init.py
import shutil
from pathlib import Path
from multi_ship import cli, driver
from multi_ship.cli import cmd_init

TEMPLATE = Path(__file__).parent.parent / "templates" / "multi-ship.json"

def test_init_scaffolds_config_and_gitignore(tmp_path):
    repo = tmp_path
    (repo / ".git").mkdir()
    cmd_init(str(repo), template_path=TEMPLATE)
    assert (repo / ".claude" / "multi-ship.json").exists()
    gi = (repo / ".gitignore").read_text()
    assert ".multi-ship/" in gi

def test_main_init_routes(tmp_path):
    (tmp_path / ".git").mkdir()
    rc = cli.main(["init", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / ".claude" / "multi-ship.json").exists()

def test_main_specs_route_to_run_loop(tmp_path, monkeypatch):
    # A bare spec arg must NOT be mis-parsed as a subcommand (regression: the
    # old add_subparsers captured the first positional and rejected spec paths).
    (tmp_path / ".claude").mkdir(parents=True)
    shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")
    captured = {}
    def fake_run_loop(**kw):
        captured.update(kw)
        return {"shipped": ["x.md"], "stopped_at": None}
    monkeypatch.setattr(driver, "run_loop", fake_run_loop)
    rc = cli.main(["docs/specs/x.md", "--repo", str(tmp_path)])
    assert rc == 0
    assert captured["specs"] == ["docs/specs/x.md"]
