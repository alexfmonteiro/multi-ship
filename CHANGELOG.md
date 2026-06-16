# Changelog

All notable changes to multi-ship will be documented in this file.

## v0.1.0 - 2026-06-16

### Added

- Initial release of multi-ship, the autonomous multi-spec shipping CLI for Claude Code.
- Dispatches multiple independent specs/plans as sequential subagent rounds, keeping the parent context clean between items (equivalent to `/clear` between rounds).
- Conventional-commit messages, PR creation, CI monitoring, auto-merge, and Telegram operator notifications are all handled end-to-end without human intervention.
- Ships with a `multi-ship` entry-point (`bin/multi-ship`), `--resume` to skip already-completed items, and `--continue-on-failure` to keep going past a failed item.
- JSON config (`.claude/multi-ship.json`) plus a per-run log and cross-item handoff (`run-log.json`, `HANDOFF.md`) stored under `.multi-ship/` in the project root.
