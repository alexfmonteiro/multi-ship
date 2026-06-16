# tests/test_cli_init.py
from pathlib import Path
from multi_ship.cli import cmd_init

def test_init_scaffolds_config_and_gitignore(tmp_path):
    repo = tmp_path
    (repo / ".git").mkdir()
    template = Path(__file__).parent.parent / "templates" / "multi-ship.json"
    cmd_init(str(repo), template_path=template)
    assert (repo / ".claude" / "multi-ship.json").exists()
    gi = (repo / ".gitignore").read_text()
    assert ".multi-ship/" in gi
