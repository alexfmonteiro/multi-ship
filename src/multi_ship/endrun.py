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
    """HEAD, branch + porcelain status. Fail-soft: returns {} if repo isn't a git checkout."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo,
                                capture_output=True, text=True).stdout.strip()
        porc = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                              capture_output=True, text=True).stdout.splitlines()
        if not head:
            return {}
        return {"head": head, "branch": branch, "porcelain": porc}
    except (OSError, subprocess.SubprocessError):
        return {}

def is_ancestor(repo: str, old: str, new: str) -> bool:
    """True iff `old` is an ancestor of `new`. Fail-soft: False on any git error."""
    if not old or not new:
        return False
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", old, new], cwd=repo,
                              capture_output=True, text=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def compare_git_state(before: dict, after: dict, fast_forward: bool = False) -> list[str]:
    """Human-readable descriptions of UNEXPECTED parent-checkout changes.

    `fast_forward` says the old HEAD is an ancestor of the new one. A fast-forward
    on the same named branch is expected (ship-one syncs the default branch,
    complete_cmd may commit to it), so it isn't reported.
    """
    if not before or not after:
        return []
    problems = []
    b_branch, a_branch = before.get("branch"), after.get("branch")
    if b_branch and a_branch and b_branch != a_branch:
        problems.append(f"branch switched: {b_branch} -> {a_branch}")
    elif before.get("head") != after.get("head"):
        expected = (fast_forward and b_branch and b_branch == a_branch
                    and b_branch != "HEAD")
        if not expected:
            problems.append(f"HEAD moved: {before.get('head')} -> {after.get('head')}")
    new_dirty = set(after.get("porcelain", [])) - set(before.get("porcelain", []))
    if new_dirty:
        problems.append("new uncommitted changes: " + ", ".join(sorted(new_dirty)))
    return problems

def format_notification(shipped: list[str], stopped_at, followups: list[str],
                        run_log_path: str, followups_path,
                        stop_kind=None, stop_notes=None, bookkeeping=None) -> str:
    lines = []
    status = "✅ all shipped" if stopped_at is None else f"⚠️ stopped at {stopped_at}"
    lines.append(f"multi-ship: {status}")
    lines.append(f"shipped ({len(shipped)}): {', '.join(shipped) if shipped else 'none'}")
    if stopped_at:
        line = f"stopped at: {stopped_at}"
        if stop_kind:
            line += f" [{stop_kind}]"
        lines.append(line)
        if stop_notes:
            why = str(stop_notes).replace("\n", " ").strip()
            if len(why) > 300:
                why = why[:300] + "…"
            lines.append(f"why: {why}")
    if bookkeeping:
        lines.append(f"bookkeeping failed ({len(bookkeeping)}) — merged, but complete_cmd "
                     "did not finish; run it by hand:")
        lines.extend(f"  - {sid}: {err}" for sid, err in bookkeeping)
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
