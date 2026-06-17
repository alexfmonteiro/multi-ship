# Changelog

All notable changes to multi-ship will be documented in this file.

## Unreleased

### Added

- **Spec/issue resolver (`src/multi_ship/resolve.py`).** `multi-ship` now accepts
  work references in four forms, resolved in order: (1) **glob** — any token
  containing `*?[` is expanded via `Path(repo).glob()` in sorted order; (2)
  **existing path** — token exists on disk relative to `--repo`; (3) **issue
  reference** — `#N` token or `--issue N` flag resolves via `gh issue view`: title
  prefix `[id]` maps to `<spec_dir>/<id>.md`, falling back to the first `.md` path
  found in the issue body; (4) **bare spec id** — any token with no `/` and not
  ending in `.md` maps to `<spec_dir>/<token>.md`. The `<spec_dir>` is derived from
  `cfg.spec_glob` (e.g. `docs/specs/*.md` → `docs/specs`). All resolution is
  rebased on the `--repo` path and returns repo-relative strings; argument order is
  preserved (input order wins; a single glob token expands sorted, but the list is
  not globally re-sorted). A resolved path that does not exist raises a clear error
  and exits non-zero without starting a run. Recursive `**` globs in `cfg.spec_glob`
  or in positional tokens are rejected with a clear error. The `gh` call is behind a
  mockable seam (`_gh_issue_title` / `_gh_issue_body`); `gh` failures produce a
  clear non-crashing error message. **Disambiguation:** a bare digit without `#`
  (e.g. `42`) is a spec id (`<spec_dir>/42.md`), not an issue; use `#42` or
  `--issue 42` for issue resolution.
- **`--issue N` flag** (repeatable via `action="append"`, type-checked as int by
  argparse) added to the main `multi-ship` parser. Each `--issue` value is resolved
  through the issue path and appended to the spec list after positional tokens.

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
