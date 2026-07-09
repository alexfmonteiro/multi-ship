# multi-ship

**Ship a spec backlog autonomously on Claude Code — with an independent cold judge gating every merge.**

[![CI](https://github.com/alexfmonteiro/multi-ship/actions/workflows/test.yml/badge.svg)](https://github.com/alexfmonteiro/multi-ship/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

In the orchestration era, the bottleneck stopped being code generation and became
**verification**. Autonomous agents open PRs faster than any human can decide
whether to trust them — review time balloons, unread merges become normal, and
"agent slop" (code that compiles but carries no recoverable intent) piles up. The
hard part of unattended shipping isn't writing the diff; it's deciding, for each
one, whether the work *actually shipped*.

**multi-ship puts a gate in front of every merge.** Before anything lands, an
independent **cold judge** — a separate `claude -p` that sees *only* the spec's
Definition of Done, the PR diff, and CI status, never the builder's transcript —
votes ok / not-ok. The driver merges on approval and **never merges red**. The
model that wrote the code can't talk the judge into accepting it.

The other half of the design is keeping each build clean in the first place. Long
autonomous Claude Code sessions **rot**: after a handful of items the context is
bloated, stale reasoning bleeds between tasks, and a single crash wipes all
progress. And a session **cannot clear or compact its own context** — `/clear` and
`/compact` are user-only gestures; hooks can't spawn sessions; `--resume` and
`--continue` reuse the old history. The only guaranteed reset is a fresh
`claude -p`. So multi-ship **inverts the loop**: orchestration moves out of the
session into a thin Python driver, and **every work item gets its own `claude -p` —
a clean slate, like an automatic `/clear` between items.** Cross-item memory lives
on disk in a fixed-schema handoff doc, not in a bloated context window.

The driver is deliberately dumb — it routes only on status/verdict files and never
reasons about code. **Every decision that needs judgment is a fresh, cold model
call; everything deterministic is boring Python.** That split is the whole design.

```text
multi-ship docs/specs/*.md
  └─ for each spec, in order:
       fresh claude -p  →  build in a worktree  →  open PR  →  drive CI to green
       fresh COLD claude -p judge  →  reads only spec DoD + PR diff  →  {ok, reason}
       driver merges (squash) only when the judge says ok  →  next item, clean context
```

> **Demo:** _(asciinema cast coming — see [docs/demo.md](docs/demo.md) to record one)._

> **Spec-driven by design — the specs must already exist.** Spec-driven
> development (SDD) is the credible-engineering answer to vibe-coded slop: the spec
> is the source of truth and its Definition of Done becomes an executable merge
> gate. multi-ship is the *executor* end of that workflow, not an ideation tool: it
> builds, ships, and merges work
> that is already written down as decision-complete spec files on disk (one file
> per item, each with a Definition of Done and an `Issue:` reference). It never
> invents work. Before a run you write the specs (or generate them however you
> like), point multi-ship at those files, and `multi-ship preflight <specs…>`
> gates that each one is ready. No spec file ⇒ nothing for multi-ship to do.

---

## Is this for me?

multi-ship is a sharp tool for a specific workflow. It's a strong fit if:

- ✅ You break work into **independent specs / plans** and have a backlog of them.
- ✅ You run Claude Code **unattended** and want it to ship PRs end-to-end (build →
  PR → green CI → merge) without babysitting each one.
- ✅ You're on **macOS or Linux**, with `claude` and the GitHub CLI (`gh`)
  authenticated.
- ✅ You want a **safety gate**: nothing merges red, and an independent cold judge
  must approve each PR before merge.

It's probably **not** for you if you work interactively item-by-item, don't write
specs, or need vendor-agnostic orchestration today (this runs on Claude Code — see
[Prior art & honesty](#prior-art--honesty)).

---

## Quickstart

```bash
# 1. install the CLI + skills (macOS or Linux) — no clone needed
pipx install git+https://github.com/alexfmonteiro/multi-ship.git
multi-ship install-skills   # links the skills into ~/.claude/skills

# 2. set up a repo you own
cd /path/to/your-repo
multi-ship init             # scaffolds .claude/multi-ship.json + gitignores .multi-ship/
# …edit .claude/multi-ship.json: set verify, test_cmd, notify…

# 3. prove it on one trivial spec, then ship the backlog
mkdir -p docs/specs && curl -fsSL \
  https://raw.githubusercontent.com/alexfmonteiro/multi-ship/main/examples/specs/add-greeting.md \
  -o docs/specs/add-greeting.md
multi-ship docs/specs/add-greeting.md       # watch it open + merge one real PR
multi-ship docs/specs/*.md                  # then the whole backlog
```

New here? [`examples/`](examples/) ships a 2-minute "first PR" walkthrough.

### Install options

| Path | Command | When |
|---|---|---|
| **pipx** (recommended) | `pipx install git+https://github.com/alexfmonteiro/multi-ship.git` | Isolated CLI on PATH, no clone. Skills travel in the wheel — `multi-ship install-skills` wires them up. |
| **pip from a clone** | `git clone … && cd multi-ship && pip install -e . && multi-ship install-skills` | Dev / hacking on multi-ship. `install-skills` symlinks so `git pull` keeps skills current. |
| **install.sh** | `git clone … && ./install.sh` | The original symlink-everything dev path. Still supported. |
| **Claude Code plugin** | see [below](#claude-code-plugin) | Browse/install the skills from a marketplace; great for trying the skills interactively. |

> PyPI publish (`pipx install multi-ship`, no `git+`) is queued — the wheel is
> already PyPI-ready; see [docs/PUBLISHING.md](docs/PUBLISHING.md).

### Claude Code plugin

multi-ship ships as a Claude Code plugin with its own self-hosted marketplace, so
you can install the skills without touching Python:

```text
/plugin marketplace add alexfmonteiro/multi-ship
/plugin install multi-ship@multi-ship
```

That makes the skills available as `/multi-ship:ship-one`,
`/multi-ship:autonomous-multi-ship`, etc. **Note:** the autonomous *driver* (the
`multi-ship` CLI) invokes the skills un-namespaced, so for hands-free backlog runs
install the CLI (pipx) and run `multi-ship install-skills`. The plugin is the
discovery + interactive-use path; the CLI is the engine.

### Requirements

| Tool | Notes |
|---|---|
| [`claude`](https://claude.ai/code) | Claude Code on PATH; must be authenticated |
| [`gh`](https://cli.github.com/) | GitHub CLI, authenticated (`gh auth login`) |
| `python3` | 3.9 or newer |
| sleep inhibitor | Optional. macOS uses `caffeinate`; Linux uses `systemd-inhibit` automatically. Neither present → the run just isn't sleep-protected. |

### Uninstall

```bash
pip uninstall multi-ship
rm -rf ~/.claude/skills/ship-one ~/.claude/skills/judge-shipped \
       ~/.claude/skills/dream-run ~/.claude/skills/autonomous-session \
       ~/.claude/skills/autonomous-multi-ship
```

---

## Safety & blast radius

multi-ship runs Claude **unattended with elevated permissions** — be deliberate
about where you point it.

- **`bypassPermissions`.** The inner `claude -p` sessions run with
  `--permission-mode bypassPermissions`: they read, modify, and commit code with
  no confirmation prompts. **Only point multi-ship at repos you own and trust.**
- **The cold judge is the guardrail.** Nothing merges that the independent judge
  rejected, and nothing merges red — `verify` must block until all checks
  complete. The judge sees only the spec DoD + PR diff + CI status, never the
  builder's transcript, so it can't be talked into approving by the same context
  that wrote the code.
- **One fix-retry, then stop.** A rejected item gets exactly one fix attempt and
  re-judge. A second rejection stops the run (or skips the item with
  `--continue-on-failure`). Nothing half-shipped is left merged.
- **Fail-closed on build/CI, fail-open on the judge.** A flaky judge can't trap a
  good run; a red build can't sneak through.
- **Your working tree is respected.** The driver snapshots dirty parent state at
  start and stops + notifies if it changes unexpectedly — it never reverts,
  renames, or deletes your uncommitted work.

---

## Usage

Ship specific specs (run in the order given):

```bash
multi-ship docs/specs/P15.md docs/specs/P16.md
```

Ship everything matching the config glob:

```bash
multi-ship
```

multi-ship accepts work references the way you think about them — not just full paths:

```bash
# Bare spec id (no path, no .md): resolved to <spec_dir>/<id>.md from cfg.spec_glob
multi-ship P14

# Issue reference (positional #N token): resolved via gh issue view
multi-ship "#42"

# Issue flag (repeatable; same resolution path as #N):
multi-ship --issue 42
multi-ship --issue 42 --issue 43

# Existing path or glob: unchanged behavior
multi-ship docs/specs/P14.md
multi-ship "docs/specs/P1*.md"
```

The `<spec_dir>` is derived from the configured `spec_glob` (e.g. `docs/specs/*.md` →
`docs/specs`). All forms are resolved relative to `--repo` and return repo-relative paths.
Argument order is preserved in the final spec list.

**Disambiguation note:** a bare digit without `#` (e.g. `42`) is treated as a spec id
(`<spec_dir>/42.md`), **not** an issue. Use `#42` or `--issue 42` for GitHub issue
resolution.

Flags:

| Flag | Meaning |
|---|---|
| `--continue-on-failure` | Keep processing remaining specs when an item fails (default: stop at the first failure) |
| `--resume` | Skip specs already `shipped` in the run-log; restart at the first non-shipped item |
| `--fresh` | Archive any existing `run-log.json` to `.multi-ship/archive/<timestamp>/` and start a brand-new run. Forces the archive even when the prior run is non-terminal or the backlog is unchanged. Never combined with `--resume` (resume wins and never archives) |
| `--repo <path>` | Repo root (default: current working directory) |
| `--issue N` | Resolve GitHub issue N to its spec file and add it to the run list (repeatable) |
| `--wait-for-quota` | When the Claude session quota is exhausted, sleep until it resets (parsed from Claude's message, clamped to ≤6h, +60s buffer) and continue automatically — a hands-off multi-window run. Default off: pause cleanly and exit 3 for a manual `--resume`. |

### Session-quota handling & exit codes

A long run (many REWORK rounds × a multi-agent build each) can exhaust the Claude
Max/Pro session quota. The driver handles this gracefully:

- A **pre-flight probe** (one tiny `claude -p`) runs before each item; if the quota
  window is already shut it **pauses before** spending a full multi-agent build that
  would only half-finish.
- Quota exhaustion **never marks an item failed** and **never crashes** the driver
  (including at the end-of-run `/dream-run`, which is now fail-soft). The paused item
  is left `pending` for a clean `--resume`.

Exit codes: **0** clean finish · **2** stopped on a real item failure · **3** paused on
session-quota exhaustion (transient — re-run with `--resume`, or use `--wait-for-quota`).

Subcommands:

| Subcommand | Meaning |
|---|---|
| `multi-ship init [repo]` | Scaffold `.claude/multi-ship.json` and add `.multi-ship/` to `.gitignore`. `repo` defaults to `.` |
| `multi-ship install-skills [--copy]` | Link (or copy) the bundled skills into `~/.claude/skills` |
| `multi-ship status [repo]` | Print the current run's per-item status table (shipped / awaiting / needs-fix / failed / pending) from `.multi-ship/run-log.json` |
| `multi-ship preflight <specs…>` | Spec-readiness gate to run before a burst: flags placeholder `Issue: 0`, missing Definition of Done, and `TBD`/`???`/`FIXME` markers. Exit 0 = ready, 2 = needs attention |

Specs run in the order you give them (or in glob sort order). The driver does not
reorder them.

### Run it in CI

The driver is cross-platform, so you can ship a backlog unattended in GitHub
Actions instead of tying up your laptop — see
[`examples/github-actions/`](examples/github-actions/) for a ready-to-copy
`workflow_dispatch` workflow (and its safety notes).

---

## Config reference

`.claude/multi-ship.json` — committed, one per repo.

| Key | Purpose | Substitution |
|---|---|---|
| `build_workflow` | Name of the Claude Code workflow that does the build (default: `"mixed-model-burst"`). Must be present in `.claude/workflows/` — `multi-ship init` installs the bundled copy there. | — |
| `spec_glob` | Glob used when `multi-ship` is invoked without explicit spec paths (e.g. `"docs/specs/*.md"`). | — |
| `verify` | Shell command to cold-verify CI for a PR. Run after every push; must block until all checks complete. | `$PR` → PR number (bare integer) |
| `notify` | How to deliver the end-of-run summary. Three routings: `"telegram"` — built-in stdlib Telegram bot (reads credentials from env / `.env`, no extra packages); `"none"` or `""` — no-op; any other string — treated as a shell command with the message passed on stdin (e.g. `"cat"`, `"jq -r '.'"`, a custom webhook script). | For the shell path, message text is piped to stdin. |
| `notify_telegram` | _(optional)_ Config block used only when `notify == "telegram"`. See table below. | — |
| `pr_body_convention` | Template for the PR body's closing keyword line (e.g. `"Closes #{issue}"`). | `{issue}` → issue number extracted from the spec's `Issue:` frontmatter |
| `complete_cmd` | Claude Code skill invocation run after each successful merge for bookkeeping (e.g. `"/complete-spec {slug}"`). Runs as a fresh `claude -p`. | `{slug}` → spec filename stem (e.g. `P15` from `P15.md`) |
| `test_cmd` | Project test command passed into the build workflow (e.g. `"pytest -x"`). | — |
| `build_invariants` | One paragraph of project conventions (TDD rules, architecture constraints, etc.) injected into the build workflow prompt. | — |
| `smoke_instructions` | Recipe for the post-build smoke test injected into the build workflow. | — |
| `roles` | Role-to-model map (see below). | — |

### The `notify_telegram` block

Only consulted when `notify == "telegram"`. All keys are optional (shown with defaults):

| Key | Default | Purpose |
|---|---|---|
| `bot_token_env` | `"TELEGRAM_BOT_TOKEN"` | Name of the env var (or `.env` key) holding the bot token |
| `chat_id_env` | `"TELEGRAM_CHAT_ID"` | Name of the env var (or `.env` key) holding the chat / group id |
| `env_file` | `".env"` | Path relative to the repo root for the fallback dotenv file |

Credential lookup order per variable: `os.environ` first, then the dotenv file. If either credential is still missing, the notification is skipped with one line to stderr (never crashes the run). The bot token is never logged.

```json
"notify": "telegram",
"notify_telegram": {
  "bot_token_env": "TELEGRAM_BOT_TOKEN",
  "chat_id_env": "TELEGRAM_CHAT_ID",
  "env_file": ".env"
}
```

> **Stdlib-only.** The Telegram backend uses only `urllib` and `pathlib` — no `python-telegram-bot`, `requests`, or any extra package. `pyproject.toml dependencies` stays `[]`.

### The role→model map

The `roles` object controls which Claude tier fills each role in the
`mixed-model-burst` build workflow. Defaults match the template:

```json
"roles": {
  "scout":   "haiku",
  "reader":  "haiku",
  "planner": "opus",
  "judges":  ["opus", "sonnet", "haiku"],
  "coder":   { "hard": "opus", "routine": "sonnet" },
  "verifier": "opus"
}
```

| Role | Default | What it does |
|---|---|---|
| `scout` | haiku | Rapid codebase scan to locate relevant files |
| `reader` | haiku | Deep read of the spec and located files |
| `planner` | opus | Produces the implementation plan; reviewed by the panel |
| `judges` | [opus, sonnet, haiku] | Diverse panel that votes APPROVE/REWORK on the plan; build proceeds only when fewer than 2 lenses block it |
| `coder.hard` | opus | Used when the spec difficulty is `hard` |
| `coder.routine` | sonnet | Used when the spec difficulty is `routine` |
| `verifier` | opus | Adversarial post-build verification before the ship-tail |

Override any role in your repo's config. The `resolveModel(role, difficulty)`
seam in the workflow reads from this map exclusively — no model IDs are hardcoded
in the workflow logic.

---

## How it works

```text
multi-ship <specs...>  →  driver:
  stay-awake (caffeinate / systemd-inhibit); load .claude/multi-ship.json
  init run-log (fail-closed, before item 1) + empty HANDOFF.md

  for spec in order:
    0. pre-flight quota probe (one tiny claude -p)
          ↳ session quota already exhausted? → pause cleanly (item stays
            pending, exit 3) — or, with --wait-for-quota, sleep to reset
            and continue. Never burns a doomed multi-agent build.

    1. claude -p "/ship-one <spec>"
          ↳ reads HANDOFF.md first
          ↳ builds via {build_workflow}
          ↳ opens PR, drives CI to cold-green, triages reviewer
          ↳ STOPS before merge
          ↳ writes .multi-ship/item-<id>.json
          ↳ appends to HANDOFF.md

    2. driver reads item-<id>.json
          status=failed → stop (or continue) + notify

    3. claude -p "/judge-shipped <spec> <pr>"   ← COLD, fresh session
          ↳ reads ONLY spec DoD + PR diff + CI status
          ↳ writes .multi-ship/verdict-<id>.json {ok, reason}
          ok=false → driver re-dispatches /ship-one --fix "<reason>" → re-judge
          still ok=false after 1 retry → stop + notify (nothing merged)
          judge error / no fresh verdict → fail-open: log, proceed to merge

    4. driver merges (deterministic shell):
          gh pr merge --squash --delete-branch
          claude -p "{complete_cmd}" (bookkeeping skill)
          mark shipped in run-log

  end of run:
    if HANDOFF has errors/knowledge OR ≥2 items shipped:
      claude -p "/dream-run"  → writes dream-proposals.md
    consolidate follow-up items → .multi-ship/followups.md
    notify operator (items shipped, follow-up paths, per-item checklist)
    release stay-awake; exit
```

### The four skills

| Skill | Invoked by | What it does |
|---|---|---|
| `ship-one` | Driver (fresh `claude -p`) | Reads HANDOFF, builds via the configured workflow, opens PR, drives CI to cold-green, triages the reviewer, stops before merge. Writes `item-<id>.json`. |
| `judge-shipped` | Driver (fresh cold `claude -p`) | Cold-reads only spec DoD + PR diff + CI status. Returns `verdict-<id>.json {ok, reason}`. Fail-open on any hard blocker. |
| `dream-run` | Driver at end-of-run (gated) | Mines HANDOFF + item reports for durable knowledge; drafts proposed CLAUDE.md gotchas and memory additions into `dream-proposals.md`. Never edits any file directly — the operator decides what to promote. |
| `mixed-model-burst` | `ship-one` (as a Workflow) | Scout → read → plan → diverse panel (REWORK blocks if ≥2 lenses reject) → coder in worktree → adversarial verify. Parametrized: all model IDs come from the `roles` config map. |

---

## State and resumability

All per-run state lives in `.multi-ship/` at the repo root (gitignored):

| File | Contents |
|---|---|
| `run-log.json` | Ordered item list, per-item status, stop-on-failure setting, notification surface. Written fail-closed before item 1. A quota pause records `paused_reason`/`resets_at` on the item (kept `pending`). |
| `HANDOFF.md` | Fixed-schema append-only doc shared across all items: *Discovered knowledge*, *Errors and fixes*, *Live resources*, *Design decisions*, *Open notes*. |
| `item-<id>.json` | Per-item report written by `ship-one`: status, PR URL, branch, DoD array, files touched, follow-ups, CI tail, parent notes, and (on failure) a `failure_kind`. |
| `verdict-<id>.json` | Per-item judge verdict written by `judge-shipped`: `{ok, reason}`. |
| `dream-proposals.md` | Proposed CLAUDE.md and memory additions from `dream-run`. Operator-reviewed; never auto-applied. |
| `followups.md` | Follow-up items collected from all item reports at end-of-run. |

`--resume` reads `run-log.json`, skips items with `status: shipped`, and restarts
at the first item that is not yet shipped. It does not clear or rewrite existing
artifacts.

**Auto-archive of a completed prior run.** When a `run-log.json` already exists and you
are *not* resuming, multi-ship checks whether the prior run is fully terminal (every item
`shipped` or `failed`) and whether the backlog you passed differs from the prior run's
`order` (an exact, order-sensitive list comparison). If both hold, it moves the whole
prior `.multi-ship/` contents into `.multi-ship/archive/<timestamp>/` and starts a clean
run — so the common "previous backlog finished, here's the next batch" case just works.
A non-terminal prior run (something still in flight) is *not* auto-archived; pass
`--fresh` to force the archive, `--resume` to continue it, or remove `.multi-ship/`
yourself. `--fresh` always archives and proceeds regardless of terminal/backlog state.
The `archive/<timestamp>/` dir lives under the already-gitignored `.multi-ship/`.

---

## Prior art & honesty

The orchestration ideas behind multi-ship were shaped by Xiaomi's
[MiMo Code](https://github.com/XiaomiMiMo/MiMo) (a fork of OpenCode), which solves
the same long-horizon problem by keeping one long-lived session and managing it
carefully: checkpoint-reconstruct, cold-judge stop-gates, and `/dream` offline
consolidation. We can't replicate the *intra-session* management because we don't
own the harness — but three of their ideas live *above* the harness and port
cleanly:

- **Fixed-schema handoff doc** (their 11-section `checkpoint.md`) → our `HANDOFF.md`.
- **Cold-judge stop-gate** (their `/goal` + independent judge) → our `judge-shipped`.
- **Offline consolidation** (their `/dream`) → our `dream-run`.

**The honest part:** *the patterns are portable; this implementation is not.* The
driver shells `claude -p` and uses Claude Code's skill and workflow engine. The
role→model map is parametrized and the `resolveModel` seam is where a future
cross-vendor provider layer would slot in — but **true cross-vendor support
(GPT, Gemini, local models) is not implemented today.** It's a documented future
direction. If you need vendor-agnostic orchestration now, the patterns here are
the portable part; the implementation is Claude-Code-specific.

See [DESIGN.md](DESIGN.md) for the full rationale.

---

## Limitations

- **Claude Code only.** The driver shells `claude -p`; the skills are Claude Code
  skill files; the build workflow uses Claude Code's `Workflow()`/`agent()` APIs.
  Running against GPT, Gemini, or local models is not supported today.
- **`gh` required.** PR creation, CI watching, and merging are all `gh` CLI calls.
  No GitHub API fallback.
- **Sequential, not parallel.** Specs run one at a time, in order. Within-run
  parallelism is not implemented (specs are independent by design, but serialized).
- **One fix-retry per item.** A judge rejection gets one fix attempt, then stops
  (or skips with `--continue-on-failure`).

---

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues
are labeled [`good first issue`](https://github.com/alexfmonteiro/multi-ship/labels/good%20first%20issue).

## License

[MIT](LICENSE) — Copyright (c) 2026 Alex Monteiro.
