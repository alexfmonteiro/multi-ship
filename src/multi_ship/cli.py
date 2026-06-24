"""multi-ship CLI: run a backlog, `init` a repo, `install-skills`, or `status`."""
from __future__ import annotations
import argparse
import glob
import os
import re
import shutil
import sys
from pathlib import Path

from . import driver
from .config import load_config
from .resolve import ResolveError, resolve_specs

# Repo/package root: src/multi_ship/cli.py -> parents[2]. Works from a source
# checkout and from an editable install (both point back at the project tree).
PKG_ROOT = Path(__file__).resolve().parents[2]

def bundled_dir(name: str) -> Path:
    """Locate a bundled resource dir (skills / templates / workflows).

    Works from a source or editable checkout (top-level dir at the repo root)
    AND from an installed wheel, where the dirs are force-included under
    `multi_ship/_bundle/` (see pyproject.toml). Returns the first that exists,
    falling back to the source-layout path so callers can report a clean error."""
    candidates = [
        Path(__file__).resolve().parent / "_bundle" / name,  # installed wheel
        PKG_ROOT / name,                                       # source / editable
    ]
    return next((c for c in candidates if c.exists()), candidates[-1])

def cmd_install_skills(copy: bool = False) -> int:
    """Link (or copy) the bundled skills into ~/.claude/skills. Mirrors
    install.sh so a pip/pipx install needs no second clone. Idempotent; refuses
    to clobber a real (non-symlink) file."""
    src = bundled_dir("skills")
    if not src.is_dir():
        print(f"bundled skills not found at {src}", file=sys.stderr)
        return 1
    dst_root = Path(os.path.expanduser("~/.claude/skills"))
    dst_root.mkdir(parents=True, exist_ok=True)
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        dst = dst_root / d.name
        if dst.exists() and not dst.is_symlink():
            print(f"SKIP {d.name}: a non-symlink skill already exists at {dst}")
            continue
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        if copy:
            shutil.copytree(d, dst)
        else:
            dst.symlink_to(d, target_is_directory=True)
        print(f"{'copied' if copy else 'linked'} skill: {d.name}")
    print("done. Per-repo setup: cd <repo> && multi-ship init")
    return 0

def cmd_init(repo: str, template_path: Path) -> None:
    repo = Path(repo)
    claude_dir = repo / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    dest = claude_dir / "multi-ship.json"
    if not dest.exists():
        shutil.copy(template_path, dest)
    gi = repo / ".gitignore"
    line = ".multi-ship/"
    existing = gi.read_text() if gi.exists() else ""
    if line not in existing:
        gi.write_text(existing + ("\n" if existing and not existing.endswith("\n") else "") + line + "\n")

_STATUS_LABEL = {
    "pending": "pending",
    "awaiting_judge": "awaiting",
    "needs_fix": "needs-fix",
    "shipped": "shipped",
    "failed": "failed",
}
_STATUS_COLOR = {  # ANSI; only applied when writing to a TTY
    "pending": "90", "awaiting_judge": "36", "needs_fix": "33",
    "shipped": "32", "failed": "31",
}

def _pr_label(pr) -> str:
    """Compact PR reference for the table: '#41' from a number or a /pull/41 URL."""
    if not pr:
        return ""
    s = str(pr)
    if s.isdigit():
        return f"#{s}"
    m = re.search(r"/pull/(\d+)", s)
    return f"#{m.group(1)}" if m else s

def format_status(log: dict, repo: str, color: bool = False) -> str:
    items = log.get("items", [])
    shipped = sum(1 for it in items if it.get("status") == "shipped")
    policy = "stop on first failure" if log.get("stop_on_failure", True) else "continue on failure"
    out = [f"multi-ship — {repo}",
           f"policy: {policy}   |   shipped {shipped}/{len(items)}", ""]
    if not items:
        out.append("  (run-log has no items)")
        return "\n".join(out)

    prs = [_pr_label(it.get("pr")) for it in items]
    idx_w = max(len(str(len(items))), 1)
    st_w = max(len(v) for v in _STATUS_LABEL.values())
    id_w = max((len(it["id"]) for it in items), default=4)
    pr_w = max([len("pr")] + [len(p) for p in prs])

    out.append(f"  {'#':>{idx_w}}  {'status':<{st_w}}  {'item':<{id_w}}  {'pr':<{pr_w}}  note")
    for i, (it, pr) in enumerate(zip(items, prs), 1):
        st = it.get("status", "pending")
        label = _STATUS_LABEL.get(st, st).ljust(st_w)
        if color:
            label = f"\033[{_STATUS_COLOR.get(st, '0')}m{label}\033[0m"
        kind = it.get("failure_kind")
        detail = (it.get("judge_reason") or it.get("parent_notes")
                  or it.get("error") or "").replace("\n", " ").strip()
        note = f"[{kind}] {detail}".strip() if kind else detail
        if len(note) > 60:
            note = note[:57] + "..."
        out.append(f"  {i:>{idx_w}}  {label}  {it['id']:<{id_w}}  {pr:<{pr_w}}  {note}".rstrip())
    return "\n".join(out)

def _archive_completed_run(state_dir: Path, ts: str | None = None) -> Path:
    """Move every top-level entry of `state_dir` (except the archive root itself)
    into state_dir/archive/<ts>/, returning the destination dir. `ts` defaults to
    a microsecond-precise timestamp so repeated archives never collide."""
    from datetime import datetime
    ts = ts or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive_root = state_dir / "archive"
    dest = archive_root / ts
    dest.mkdir(parents=True, exist_ok=True)
    for entry in state_dir.iterdir():
        if entry == archive_root:
            continue
        shutil.move(str(entry), str(dest / entry.name))
    return dest

def cmd_status(repo: str) -> int:
    run_log = Path(repo) / ".multi-ship" / "run-log.json"
    if not run_log.exists():
        print(f"no run-log at {run_log} — nothing has shipped here yet", file=sys.stderr)
        return 1
    import json
    log = json.loads(run_log.read_text())
    print(format_status(log, str(Path(repo).resolve()), color=sys.stdout.isatty()))
    return 0

def cmd_preflight(repo: str, tokens: list[str]) -> int:
    """Lint resolved specs for readiness gaps before an unattended run. Exit 0 if
    all clear, 2 if any spec needs attention, 1 on a resolution error."""
    from . import preflight as pf
    repo_p = Path(repo).resolve()
    cfg = load_config(repo_p / ".claude" / "multi-ship.json")
    args = argparse.Namespace(specs=tokens, issue=None)
    try:
        specs = _resolve_specs(args, cfg, repo_p)
    except ResolveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not specs:
        print("no specs to check", file=sys.stderr)
        return 1
    problems = pf.lint_specs([repo_p / s for s in specs])
    if not problems:
        print(f"preflight OK — {len(specs)} spec(s) ready")
        return 0
    for path, probs in problems.items():
        rel = Path(path).relative_to(repo_p) if str(path).startswith(str(repo_p)) else path
        print(f"⚠ {rel}")
        for pr in probs:
            print(f"    - {pr}")
    print(f"\n{len(problems)} of {len(specs)} spec(s) need attention before an "
          "unattended run.", file=sys.stderr)
    return 2

def _resolve_specs(args, cfg, repo: Path) -> list[str]:
    """Resolve spec tokens and --issue integers to repo-relative paths.

    Falls back to globbing cfg.spec_glob (rebased on repo) when no positional
    specs and no --issue flags are given — preserving backward compatibility.
    """
    if not args.specs and not (args.issue or []):
        # No-arg fallback: glob cfg.spec_glob rebased on repo (3.9-safe).
        # Still validate for recursive globs before attempting to glob.
        from .resolve import _spec_dir_from_glob  # validates ** and derives spec_dir
        _spec_dir_from_glob(cfg.spec_glob)  # raises ResolveError if ** found
        return sorted(
            str(p.relative_to(repo))
            for p in Path(repo).glob(cfg.spec_glob)
        )
    return resolve_specs(
        tokens=args.specs or [],
        issue_numbers=args.issue or [],
        cfg=cfg,
        repo=repo,
    )

def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    # Subcommands are handled before argparse: a subparser would capture the
    # first positional, breaking the primary `multi-ship <specs...>` form.
    if argv and argv[0] == "init":
        repo = argv[1] if len(argv) > 1 and not argv[1].startswith("-") else "."
        cmd_init(repo, template_path=bundled_dir("templates") / "multi-ship.json")
        print(f"initialized {repo}/.claude/multi-ship.json")
        return 0
    if argv and argv[0] == "install-skills":
        return cmd_install_skills(copy="--copy" in argv[1:])
    if argv and argv[0] == "status":
        rest = argv[1:]
        repo = "."
        if "--repo" in rest:
            repo = rest[rest.index("--repo") + 1]
        elif rest and not rest[0].startswith("-"):
            repo = rest[0]
        return cmd_status(repo)
    if argv and argv[0] == "preflight":
        rest = argv[1:]
        repo = "."
        if "--repo" in rest:
            i = rest.index("--repo")
            repo = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        return cmd_preflight(repo, rest)

    p = argparse.ArgumentParser(prog="multi-ship")
    p.add_argument("specs", nargs="*")
    p.add_argument("--repo", default=".")
    p.add_argument("--continue-on-failure", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--issue", action="append", type=int, default=None)
    p.add_argument("--wait-for-quota", action="store_true",
                   help="when the Claude session quota is exhausted, sleep until "
                        "it resets and continue automatically (hands-off "
                        "multi-window run) instead of pausing for a manual --resume")
    args = p.parse_args(argv)

    repo = Path(args.repo).resolve()
    cfg = load_config(repo / ".claude" / "multi-ship.json")
    try:
        specs = _resolve_specs(args, cfg, repo)
    except ResolveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not specs:
        print("no specs to ship", file=sys.stderr); return 1
    state_dir = repo / ".multi-ship"
    run_log_path = state_dir / "run-log.json"
    # --resume is checked FIRST so a resume never archives. Otherwise, when a
    # prior run-log exists, auto-archive it iff the prior run is fully terminal
    # AND the backlog differs (or the operator forced --fresh); else refuse with
    # the three-option message.
    if run_log_path.exists() and not args.resume:
        import json
        try:
            log = json.loads(run_log_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            log = {}
        all_terminal = bool(log.get("items")) and all(
            it.get("status") in ("shipped", "failed") for it in log["items"])
        different_backlog = list(specs) != list(log.get("order", []))
        if args.fresh or (all_terminal and different_backlog):
            dest = _archive_completed_run(state_dir)
            print(f"archived prior run → {dest}")
        else:
            print("a previous run-log exists at .multi-ship/run-log.json — pass "
                  "--resume to continue it, --fresh to archive it and start over, "
                  "or remove .multi-ship/ to start fresh", file=sys.stderr)
            return 2
    result = driver.run_loop(repo=str(repo), specs=specs, cfg=cfg,
                             stop_on_failure=not args.continue_on_failure,
                             state_dir=state_dir, resume=args.resume,
                             wait_for_quota=args.wait_for_quota)
    print(f"shipped: {result['shipped']}  stopped_at: {result['stopped_at']}")
    # Exit-code contract: 0 = clean finish, 2 = stopped on a real item failure,
    # 3 = paused on session-quota exhaustion (transient — re-run with --resume).
    paused = result.get("paused")
    if paused:
        resets = paused.get("resets_at")
        print(f"paused: session quota exhausted"
              + (f" (resets {resets})" if resets else "")
              + f" — item '{paused.get('item')}' left pending; re-run with --resume",
              file=sys.stderr)
        return 3
    return 0 if result["stopped_at"] is None else 2

if __name__ == "__main__":
    raise SystemExit(main())
