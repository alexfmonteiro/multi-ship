# Changelog

All notable changes to multi-ship will be documented in this file.

## Unreleased

### Added

- **Cross-platform sleep handling.** The driver now auto-detects the OS: macOS
  uses `caffeinate`, Linux uses `systemd-inhibit`, and other platforms no-op
  gracefully. multi-ship is no longer macOS-only.
- **Standard packaging.** `pyproject.toml` exposes a `multi-ship` console script,
  so `pip install -e .` (or `pipx`) puts the command on PATH — no manual symlink
  or PATH export needed.
- **`multi-ship install-skills [--copy]`** subcommand to link (or copy) the
  bundled skills into `~/.claude/skills`, replacing the need to run `install.sh`
  after a pip install.
- **`examples/`** — a 2-minute "ship your first spec" walkthrough with a trivial
  example spec and a worked config.
- **Docs:** `CONTRIBUTING.md`, `docs/demo.md` (how to record the demo), and
  `docs/PROMOTION.md` (launch kit).

### Changed

- README reframed to lead with the context-rot problem and the fresh-context-per-
  item fix, with new "Is this for me?" and "Safety & blast radius" sections.

## v0.1.0 - 2026-06-16

### Added

- Initial release of multi-ship, the autonomous multi-spec shipping CLI for Claude Code.
- Dispatches multiple independent specs/plans as sequential subagent rounds, keeping the parent context clean between items (equivalent to `/clear` between rounds).
- Conventional-commit messages, PR creation, CI monitoring, auto-merge, and Telegram operator notifications are all handled end-to-end without human intervention.
- Ships with a `multi-ship` entry-point (`bin/multi-ship`), `--resume` to skip already-completed items, and `--continue-on-failure` to keep going past a failed item.
- JSON config (`.claude/multi-ship.json`) plus a per-run log and cross-item handoff (`run-log.json`, `HANDOFF.md`) stored under `.multi-ship/` in the project root.
