# tests/test_claude_cli.py
import json
import pytest
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
    with pytest.raises(claude_cli.ClaudeError, match="boom"):
        claude_cli.run("/x", repo="/repo")

# --- quota detection -------------------------------------------------------

def test_detect_quota_signature_and_resets():
    is_q, resets = claude_cli.detect_quota(
        "You've hit your session limit · resets 5:20pm (America/Sao_Paulo)")
    assert is_q is True
    assert resets == "5:20pm (America/Sao_Paulo)"

def test_detect_quota_negative():
    assert claude_cli.detect_quota("normal build output, all good") == (False, None)

def test_run_raises_quota_exhausted_from_stderr(monkeypatch):
    msg = "You've hit your session limit · resets 11:20am"
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (1, "", msg))
    with pytest.raises(claude_cli.QuotaExhausted) as ei:
        claude_cli.run("/x", repo="/repo")
    assert ei.value.resets_at == "11:20am"
    assert isinstance(ei.value, claude_cli.ClaudeError)  # still a ClaudeError subclass

def test_run_detects_quota_in_stdout(monkeypatch):
    # the outer `claude -p` has been observed to surface the limit on stdout
    # with an empty stderr — detection must scan both streams.
    monkeypatch.setattr(claude_cli, "_raw_run",
                        lambda cmd, cwd, timeout: (1, "usage limit reached; resets 9am", ""))
    with pytest.raises(claude_cli.QuotaExhausted):
        claude_cli.run("/x", repo="/repo")

def test_probe_quota_available(monkeypatch):
    monkeypatch.setattr(claude_cli, "_raw_run",
                        lambda cmd, cwd, timeout: (0, json.dumps({"result": "OK"}), ""))
    assert claude_cli.probe_quota("/repo") == (True, None)

def test_probe_quota_exhausted(monkeypatch):
    monkeypatch.setattr(claude_cli, "_raw_run",
                        lambda cmd, cwd, timeout: (1, "session limit; resets 5pm", ""))
    available, resets = claude_cli.probe_quota("/repo")
    assert available is False and resets == "5pm"

def test_probe_quota_failopen_on_other_error(monkeypatch):
    # a flaky/non-quota error must NOT falsely pause a run that could proceed
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (1, "", "network boom"))
    assert claude_cli.probe_quota("/repo") == (True, None)
