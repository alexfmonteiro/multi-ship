# tests/test_claude_cli.py
import json
from multi_ship import claude_cli

def test_build_command_invokes_skill_and_json_output():
    cmd = claude_cli.build_command("/ship-one docs/specs/a.md", repo="/repo")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "/ship-one docs/specs/a.md" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--permission-mode" in cmd

def test_run_parses_json_result(monkeypatch):
    fake = json.dumps({"result": "done", "session_id": "abc"})
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (0, fake, ""))
    out = claude_cli.run("/x", repo="/repo")
    assert out["result"] == "done"

def test_run_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (1, "", "boom"))
    import pytest
    with pytest.raises(claude_cli.ClaudeError, match="boom"):
        claude_cli.run("/x", repo="/repo")
