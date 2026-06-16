"""multi-ship CLI: run a backlog, or `init` a repo."""
from __future__ import annotations
import argparse
import glob
import shutil
import sys
from pathlib import Path

from . import driver
from .config import load_config

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

def _resolve_specs(args, cfg) -> list[str]:
    if args.specs:
        out = []
        for s in args.specs:
            out.extend(sorted(glob.glob(s)) if any(c in s for c in "*?[") else [s])
        return out
    return sorted(glob.glob(cfg.spec_glob))

def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="multi-ship")
    sub = p.add_subparsers(dest="command")
    pi = sub.add_parser("init"); pi.add_argument("repo", nargs="?", default=".")
    p.add_argument("specs", nargs="*")
    p.add_argument("--repo", default=".")
    p.add_argument("--continue-on-failure", action="store_true")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    pkg_root = Path(__file__).resolve().parent.parent.parent
    if args.command == "init":
        cmd_init(args.repo, template_path=pkg_root / "templates" / "multi-ship.json")
        print(f"initialized {args.repo}/.claude/multi-ship.json")
        return 0

    repo = Path(args.repo).resolve()
    cfg = load_config(repo / ".claude" / "multi-ship.json")
    specs = _resolve_specs(args, cfg)
    if not specs:
        print("no specs to ship", file=sys.stderr); return 1
    state_dir = repo / ".multi-ship"
    if (state_dir / "run-log.json").exists() and not args.resume:
        print("a previous run-log exists at .multi-ship/run-log.json — pass --resume "
              "to continue it, or remove .multi-ship/ to start fresh", file=sys.stderr)
        return 2
    result = driver.run_loop(repo=str(repo), specs=specs, cfg=cfg,
                             stop_on_failure=not args.continue_on_failure,
                             state_dir=state_dir, resume=args.resume)
    print(f"shipped: {result['shipped']}  stopped_at: {result['stopped_at']}")
    return 0 if result["stopped_at"] is None else 2

if __name__ == "__main__":
    raise SystemExit(main())
