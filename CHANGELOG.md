# Changelog

All notable changes to multi-ship will be documented in this file.

## Unreleased

### Fixed
- A hung `claude -p` (subprocess timeout) is now a per-item `ClaudeError` instead of an
  uncaught `TimeoutExpired` that crashed the whole run before notification.
- The documented judge fail-open is now implemented: a judge crash or a judge session
  that writes no fresh `verdict-<id>.json` logs and proceeds to merge instead of
  failing the item; stale verdicts from prior rounds are never trusted (mtime guard).
- The `--fix` path now applies the same fresh-report + failed-status discipline as the
  first build (a failed fix keeps the builder's `failure_kind`; a crashed fix is an
  honest error, not a re-judge of stale data).
- `claude -p` payloads with exit 0 but `is_error: true` (including mid-session quota
  hits) are treated as failures.
- Run-log writes are atomic (tmp + rename); per-round fields (`judge_reason`,
  `paused_reason`, `error`, …) are cleared on every status transition so
  `multi-ship status` never shows a stale note.
- A glob token that matches no files raises `ResolveError` instead of silently
  dropping specs.
- `multi-ship init` installs the bundled build workflow into `.claude/workflows/`
  (per DESIGN.md); previously a fresh install could never build.
- Clean errors for `--repo` without a value, a corrupt `run-log.json` (no longer
  suggests `--resume`, which would crash), and item reports missing `pr`.
- **The driver loop is now crash-proof.** Any unexpected error while processing an
  item (including a genuine `gh pr merge` `CalledProcessError`) is caught, fails just
  that item, and still reaches the end-of-run notify — a single item can no longer
  kill the whole run via an unhandled exception.
- **`_merge_pr` is fail-soft on post-merge branch cleanup.** A failed
  `--delete-branch` (e.g. a leftover build worktree still holds the branch) no longer
  crashes the run once the PR is confirmed `MERGED`; the merge itself still hard-fails
  the item if it truly fails.
- **Idempotent recovery on `--resume`.** If a prior attempt already merged an item's
  PR, the driver short-circuits to the archive + `shipped` tail instead of rebuilding,
  re-judging, and re-merging an already-merged PR.
- **Build worktrees are cleaned up after merge.** The driver removes the item's build
  worktree (fail-soft) before deleting its branch, so worktrees stop accumulating and
  can't block branch deletion.

### Added

- **Session-quota guardrails.** Long runs (many REWORK rounds × a multi-agent build
  each) repeatedly hit the Claude Max/Pro session quota; the driver now handles it
  gracefully instead of crashing or recording misleading state:
  - `claude_cli` detects the quota signature in stdout/stderr and raises a distinct
    `QuotaExhausted(ClaudeError)` carrying the parsed `resets_at`.
  - A **pre-flight `probe_quota`** (one tiny `claude -p`, fail-open) runs before each
    item, so an already-shut window pauses *before* a full build is wasted.
  - Quota exhaustion **pauses cleanly**: the item is left `pending` (never `failed`/a
    misleading stale kind), the run-log records `paused_reason`/`resets_at`, the
    notification says so, and `multi-ship` exits **3** (vs 2 for a real failure).
  - `--wait-for-quota` (opt-in): sleep until the reset (parsed; clamped ≤6h, +60s
    buffer; ≤8 cycles) and auto-continue — a hands-off multi-window run.
  - **Fail-soft end-of-run**: `/dream-run` (and any end-of-run `claude -p`) can no
    longer crash the driver with a traceback (regression: an unwrapped `/dream-run`
    that hit the quota killed the run on exit 1).
  - **Stale-item guard**: if `ship-one` returns without rewriting `item-<id>.json`
    (quota/crash mid-build), the driver raises an honest error instead of recording
    the prior round's stale status.
- **Failure taxonomy (`failure_kind`).** A failed item now carries a closed-vocabulary
  `failure_kind` so operators can triage at a glance. `ship-one` sets `config_error`,
  `plan_gate_rework`, `ci_failed`, or `needs_redesign` at its stop sites; the driver
  owns `judge_rejected` (a cold-judge rejection it can't fix) and `error` (an unexpected
  exception). A failed item with no kind from the skill defaults to `unknown`. The kind
  is stdlib-only metadata on the run-log item — no config change, existing run-logs load
  unchanged.
- **`parent_notes` surfacing.** The skill's `parent_notes` (and the chosen `failure_kind`)
  now propagate onto the run-log item, into the end-of-run notification, and into the
  `multi-ship status` table. The notification's stopped-at line gains a `[<kind>]` token
  and a `why:` line (newlines collapsed to spaces, truncated to ~300 chars). The status
  table prefixes the note column with `[<kind>]` and falls back judge_reason →
  parent_notes → error. `parent_notes` must stay secret-free (skill §8 hygiene).
- **Auto-archive of a completed prior run + `--fresh`.** When a prior `run-log.json`
  exists, is fully terminal (every item `shipped`/`failed`), and the new backlog differs
  from the prior `order`, multi-ship now archives the prior run to
  `.multi-ship/archive/<timestamp>/` and proceeds — instead of refusing. The new
  `--fresh` flag forces this archive-and-proceed over any prior run-log (terminal or
  not). `--resume` is still checked first and never archives. A non-terminal run-log
  without `--fresh` still refuses, now with an improved three-option message
  (`--resume` / `--fresh` / remove `.multi-ship/`). The archive dir lives under the
  gitignored `.multi-ship/`.

- **`multi-ship preflight <specs…>`** — a spec-readiness gate to run before an
  unattended burst. Flags placeholder issue numbers (`Issue: 0`), a missing
  Definition of Done, and `TBD`/`???`/`FIXME` markers, resolving the same spec
  tokens/globs as a run. Exits 0 when all clear, 2 when any spec needs attention.
  Catches mechanical gaps up front instead of stopping at the plan gate mid-run.

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

- README reframed to lead with the verification bottleneck and the cold-judge
  merge gate (with the context-rot inversion as the second act), plus
  "Is this for me?" and "Safety & blast radius" sections.

## v0.1.0 - 2026-06-16

### Added

- Initial release of multi-ship, the autonomous multi-spec shipping CLI for Claude Code.
- Dispatches multiple independent specs/plans as sequential subagent rounds, keeping the parent context clean between items (equivalent to `/clear` between rounds).
- Conventional-commit messages, PR creation, CI monitoring, auto-merge, and Telegram operator notifications are all handled end-to-end without human intervention.
- Ships with a `multi-ship` entry-point (`bin/multi-ship`), `--resume` to skip already-completed items, and `--continue-on-failure` to keep going past a failed item.
- JSON config (`.claude/multi-ship.json`) plus a per-run log and cross-item handoff (`run-log.json`, `HANDOFF.md`) stored under `.multi-ship/` in the project root.
