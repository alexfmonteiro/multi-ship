# Changelog

All notable changes to multi-ship will be documented in this file.

## Unreleased

### Added

- **Built-in Telegram notification backend.** Set `"notify": "telegram"` in
  `.claude/multi-ship.json` to receive end-of-run summaries via a Telegram bot
  with no extra packages — the backend is stdlib-only (`urllib`, `pathlib`).
  Credentials are read from `os.environ` first, then a repo-local `.env` fallback
  (per-variable, so you can mix). Missing credentials or network errors are caught
  fail-soft (one stderr line, run exits 0). Long messages are truncated to
  Telegram's 4096-char limit with an ellipsis marker. Configure via an optional
  `notify_telegram` block (`bot_token_env`, `chat_id_env`, `env_file`; all
  default to conventional names so zero config is needed for the common case).
  The previous shell-command path (`any other string` → stdin pipe) and the
  no-op (`"none"` / `""`) are unchanged.

- **`multi-ship status`** — print the current run's per-item table (shipped /
  awaiting / needs-fix / failed / pending) with PR refs and the judge's reason,
  read from `.multi-ship/run-log.json`. Colorized on a TTY.
- **GitHub Actions recipe.** `examples/github-actions/` ships a ready-to-copy
  `workflow_dispatch` workflow (+ safety notes) to run a backlog unattended in CI.
- **Launch post.** `docs/launch-post.md` — a publish-ready announcement.
- **Cross-platform sleep handling.** The driver now auto-detects the OS: macOS
  uses `caffeinate`, Linux uses `systemd-inhibit`, and other platforms no-op
  gracefully. multi-ship is no longer macOS-only.
- **PyPI-ready packaging (hatchling).** `pyproject.toml` exposes a `multi-ship`
  console script and the wheel force-includes the skills/templates/workflow, so
  `pipx install git+…` works with **no clone** — `multi-ship install-skills`
  wires the skills up afterward. `cli.bundled_dir()` resolves resources from
  either a source checkout or an installed wheel. See `docs/PUBLISHING.md`.
- **Claude Code plugin + self-hosted marketplace.** `.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json` let users
  `/plugin marketplace add alexfmonteiro/multi-ship` and
  `/plugin install multi-ship@multi-ship`. Passes `claude plugin validate .
  --strict`.
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
