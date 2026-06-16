"""Thin wrapper over `claude -p` so the loop is subprocess-testable."""
from __future__ import annotations
import json
import subprocess

class ClaudeError(Exception):
    pass

def build_command(prompt: str, repo: str, permission_mode: str = "bypassPermissions") -> list[str]:
    return [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--permission-mode", permission_mode,
    ]

def _raw_run(cmd: list[str], cwd: str, timeout: int):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr

def run(prompt: str, repo: str, timeout: int = 7200) -> dict:
    cmd = build_command(prompt, repo)
    code, out, err = _raw_run(cmd, cwd=repo, timeout=timeout)
    if code != 0:
        raise ClaudeError(f"claude -p exited {code}: {err.strip()[:500]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"claude -p returned non-JSON: {out[:500]}") from e
