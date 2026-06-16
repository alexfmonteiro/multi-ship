"""End-of-run helpers: follow-up consolidation, git-state safety, notification text."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

def read_item_reports(state_dir: Path) -> list[dict]:
    reports = []
    for p in sorted(Path(state_dir).glob("item-*.json")):
        try:
            reports.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return reports

def collect_followups(item_reports: list[dict]) -> list[str]:
    """Flatten + de-dup (order-preserving) the 'followups' lists across item reports."""
    seen, out = set(), []
    for rep in item_reports:
        for f in (rep.get("followups") or []):
            if f not in seen:
                seen.add(f)
                out.append(f)
    return out

def git_snapshot(repo: str) -> dict:
    """HEAD + porcelain status. Fail-soft: returns {} if repo isn't a git checkout."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        porc = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                              capture_output=True, text=True).stdout.splitlines()
        if not head:
            return {}
        return {"head": head, "porcelain": porc}
    except (OSError, subprocess.SubprocessError):
        return {}

def compare_git_state(before: dict, after: dict) -> list[str]:
    """Human-readable descriptions of UNEXPECTED parent-checkout changes."""
    if not before or not after:
        return []
    problems = []
    if before.get("head") != after.get("head"):
        problems.append(f"HEAD moved: {before.get('head')} -> {after.get('head')}")
    new_dirty = set(after.get("porcelain", [])) - set(before.get("porcelain", []))
    if new_dirty:
        problems.append("new uncommitted changes: " + ", ".join(sorted(new_dirty)))
    return problems

def format_notification(shipped: list[str], stopped_at, followups: list[str],
                        run_log_path: str, followups_path) -> str:
    lines = []
    status = "✅ all shipped" if stopped_at is None else f"⚠️ stopped at {stopped_at}"
    lines.append(f"multi-ship: {status}")
    lines.append(f"shipped ({len(shipped)}): {', '.join(shipped) if shipped else 'none'}")
    if stopped_at:
        lines.append(f"stopped at: {stopped_at}")
    if followups:
        lines.append(f"follow-ups ({len(followups)}) — see {followups_path}:")
        lines.extend(f"  - {f}" for f in followups)
    lines.append(f"run-log: {run_log_path}")
    return "\n".join(lines)

def run_notify(notify_cmd: str, message: str) -> None:
    """Shell the project's notify command, piping the message on stdin. No-op if unset."""
    if not notify_cmd or notify_cmd == "none":
        return
    try:
        subprocess.run(notify_cmd, shell=True, input=message, text=True)
    except (OSError, subprocess.SubprocessError) as e:
        import sys
        print(f"multi-ship: notify command failed: {e}", file=sys.stderr)
