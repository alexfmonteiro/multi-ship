"""Thin wrapper over `claude -p` so the loop is subprocess-testable."""
from __future__ import annotations
import json
import re
import subprocess

class ClaudeError(Exception):
    pass

class QuotaExhausted(ClaudeError):
    """Raised when `claude -p` fails because the Claude (Max/Pro) session quota
    is exhausted. Distinct from a code/spec failure: it is operational and
    transient, so the driver pauses cleanly (and can wait for reset) rather than
    marking the item failed or crashing. `resets_at` is the best-effort reset
    phrase parsed from Claude's output (e.g. "5:20pm (America/Sao_Paulo)"), or
    None if the message had no parseable reset time."""
    def __init__(self, message: str, resets_at: str | None = None):
        super().__init__(message)
        self.resets_at = resets_at

# Best-effort signatures for the quota message. Claude phrases it as e.g.
# "You've hit your session limit · resets 5:20pm (America/Sao_Paulo)". We scan
# BOTH stdout and stderr (the outer `claude -p` has been observed to surface it
# on either) case-insensitively. This is intentionally lenient — a false
# positive only causes a (recoverable) pause, and the fail-soft end-of-run guard
# is the backstop if detection ever misses.
_QUOTA_SIGNATURE = re.compile(
    r"(session limit|usage limit|hit your (?:usage |session )?limit|rate limit exceeded)",
    re.I,
)
_RESETS_RE = re.compile(r"resets?\s+(?:at\s+)?([^\n.]+?)(?:\.|\n|$)", re.I)

def detect_quota(*streams: str) -> tuple[bool, str | None]:
    """Return (is_quota, resets_at) by scanning the given text streams for the
    session-quota signature. resets_at is the phrase after "resets", or None."""
    blob = "\n".join(s for s in streams if s)
    if not blob or not _QUOTA_SIGNATURE.search(blob):
        return False, None
    m = _RESETS_RE.search(blob)
    return True, (m.group(1).strip() if m else None)

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
    try:
        code, out, err = _raw_run(cmd, cwd=repo, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # A hung `claude -p` (slow MCP init, network stall) must surface as a
        # normal ClaudeError so callers' fail-open / per-item handling applies —
        # never as a raw TimeoutExpired that crashes the driver loop.
        raise ClaudeError(f"claude -p timed out after {timeout}s") from e
    if code != 0:
        is_quota, resets_at = detect_quota(out, err)
        if is_quota:
            suffix = f" (resets {resets_at})" if resets_at else ""
            raise QuotaExhausted(
                f"claude -p session quota exhausted{suffix}", resets_at=resets_at)
        raise ClaudeError(f"claude -p exited {code}: {err.strip()[:500]}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"claude -p returned non-JSON: {out[:500]}") from e
    # `claude -p --output-format json` can exit 0 while the payload itself says
    # the session errored (is_error) — including a mid-session quota hit. Treat
    # that as the failure it is instead of returning it as success.
    if isinstance(data, dict) and data.get("is_error"):
        result_text = str(data.get("result", ""))
        is_quota, resets_at = detect_quota(result_text, err)
        if is_quota:
            suffix = f" (resets {resets_at})" if resets_at else ""
            raise QuotaExhausted(
                f"claude -p session quota exhausted{suffix}", resets_at=resets_at)
        raise ClaudeError(f"claude -p reported an error result: {result_text[:500]}")
    return data

def probe_quota(repo: str, timeout: int = 120) -> tuple[bool, str | None]:
    """Cheap pre-flight check: is the Claude session quota available right now?

    Returns (available, resets_at). A tiny `claude -p` call surfaces quota
    exhaustion cleanly BEFORE the driver spends a full multi-agent build that
    would otherwise be wasted (the inner workflow swallows the limit and returns
    a partial/ambiguous result). Fail-open: only a *detected* QuotaExhausted
    returns False — any other error returns True so a flaky probe never blocks a
    run that could actually proceed."""
    try:
        run("Respond with the single word: OK", repo=repo, timeout=timeout)
        return True, None
    except QuotaExhausted as q:
        return False, q.resets_at
    except ClaudeError:
        return True, None
