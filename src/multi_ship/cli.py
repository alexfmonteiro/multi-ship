"""multi-ship CLI: run a backlog, `init` a repo, or `install-skills`."""
from __future__ import annotations
import argparse
import glob
import os
import shutil
import sys
from pathlib import Path

from . import driver
from .config import load_config

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

def _resolve_specs(args, cfg) -> list[str]:
    if args.specs:
        out = []
        for s in args.specs:
            out.extend(sorted(glob.glob(s)) if any(c in s for c in "*?[") else [s])
        return out
    return sorted(glob.glob(cfg.spec_glob))

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

    p = argparse.ArgumentParser(prog="multi-ship")
    p.add_argument("specs", nargs="*")
    p.add_argument("--repo", default=".")
    p.add_argument("--continue-on-failure", action="store_true")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

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
