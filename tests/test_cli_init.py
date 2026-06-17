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

def test_bundled_dir_resolves_source_layout():
    # From the source checkout, bundled_dir falls back to the top-level dirs.
    skills = cli.bundled_dir("skills")
    templates = cli.bundled_dir("templates")
    assert skills.is_dir() and (skills / "ship-one" / "SKILL.md").exists()
    assert (templates / "multi-ship.json").exists()

def test_install_skills_links_into_fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    rc = cli.cmd_install_skills()
    assert rc == 0
    linked = home / ".claude" / "skills"
    assert (linked / "ship-one").exists()
    assert (linked / "judge-shipped").exists()

def test_install_skills_skips_non_symlink(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    existing = home / ".claude" / "skills" / "ship-one"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("user's own skill")
    cli.cmd_install_skills()
    # a real (non-symlink) skill of the same name is left untouched
    assert not (existing).is_symlink()
    assert (existing / "SKILL.md").read_text() == "user's own skill"

def test_main_specs_route_to_run_loop(tmp_path, monkeypatch):
    # A bare spec arg must NOT be mis-parsed as a subcommand (regression: the
    # old add_subparsers captured the first positional and rejected spec paths).
    (tmp_path / ".claude").mkdir(parents=True)
    shutil.copy(TEMPLATE, tmp_path / ".claude" / "multi-ship.json")
    # Create the spec file so the new existence gate passes (STEP 7 fix).
    spec_file = tmp_path / "docs" / "specs" / "x.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text("# x")
    captured = {}
    def fake_run_loop(**kw):
        captured.update(kw)
        return {"shipped": ["x.md"], "stopped_at": None}
    monkeypatch.setattr(driver, "run_loop", fake_run_loop)
    rc = cli.main(["docs/specs/x.md", "--repo", str(tmp_path)])
    assert rc == 0
    assert captured["specs"] == ["docs/specs/x.md"]
