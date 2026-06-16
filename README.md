# multi-ship

Ship a backlog of specs autonomously, one fresh context per item.

---

## Why

Long autonomous sessions accumulate context. After N work items the session is
bloated, carries stale reasoning from earlier items, and a crash wipes all
progress. Claude Code makes this worse in one specific way: **a session cannot
clear or compact its own context** — `/clear` and `/compact` are user-only
gestures; hooks can't spawn sessions; `--resume` and `--continue` reuse the old
history. The only guaranteed reset without forking the harness is a fresh
`claude -p` invocation.

The fix is to invert the architecture: move the loop out of the Claude session
into a thin Python driver, give each work item its own `claude -p` (fresh
context, clean slate), and keep all cross-item memory on disk in a fixed-schema
handoff doc. The driver is dumb — it routes only on status/verdict files, never
reasons about code. Every decision that requires judgment is a fresh cold
`claude -p`.

---

## Portability notice — "the patterns are portable; this implementation is not"

The orchestration ideas that make multi-ship work were shaped by Xiaomi's
[MiMo Code](https://github.com/XiaomiMiMo/MiMo) (a fork of OpenCode). MiMo
solves the same long-horizon problem by keeping one long-lived session and
managing it carefully: checkpoint-reconstruct, cold-judge stop-gates, and
`/dream` offline consolidation. We can't replicate the intra-session management
because we don't own the harness — but three of their ideas live *above* the
harness and port cleanly:

- **Fixed-schema handoff doc** (their 11-section `checkpoint.md`) → our
  `HANDOFF.md`, trimmed to cross-item sections only.
- **Cold-judge stop-gate** (their `/goal` + independent judge) → our
  `judge-shipped` skill.
- **Offline consolidation** (their `/dream`) → our `dream-run` skill.

**This implementation runs on Claude Code.** The driver shells `claude -p` and
uses Claude Code's skill and workflow engine. The model-role map is
parametrized (you can override which Claude tier fills each role) and the
`resolveModel` seam in the bundled workflow is the slot where a future
cross-vendor provider layer would live — but **true cross-vendor support
(GPT-4o, Gemini, local models) is not implemented today**. It is a documented
future direction. If you need vendor-agnostic orchestration now, the patterns
here are the portable part; the implementation is Claude-Code-specific.

---

## Requirements

| Tool | Notes |
|---|---|
| [`claude`](https://claude.ai/code) | Claude Code on PATH; must be authenticated |
| [`gh`](https://cli.github.com/) | GitHub CLI, authenticated (`gh auth login`) |
| `python3` | 3.9 or newer |
| `caffeinate` | macOS built-in; the driver uses it to prevent sleep during a run. Non-macOS users need to adapt `driver.py` (`_caffeinate` / `_kill_caffeinate`). |

---

## Install

```bash
git clone https://github.com/alexfmonteiro/multi-ship.git ~/Projects/multi-ship
cd ~/Projects/multi-ship && ./install.sh
```

`install.sh` does the following (idempotent, safe to re-run):

- Symlinks each directory under `skills/` into `~/.claude/skills/`. Because
  these are symlinks, a `git pull` in the repo updates the skills automatically.
- Creates a symlink `~/.local/bin/multi-ship → bin/multi-ship`.
- If `~/.local/bin` is not on your `PATH`, the installer prints the `export`
  line you need to add to your shell profile.
- Checks that `python3`, `claude`, and `gh` are on PATH; warns (does not abort)
  if any are missing.
- **Refuses to clobber** a pre-existing non-symlink skill of the same name —
  it prints `SKIP <name>: a non-symlink skill already exists` and leaves your
  file untouched. Remove it manually first if you want the multi-ship version.

### Uninstall

Remove the symlinks:

```bash
rm ~/.local/bin/multi-ship
rm -rf ~/.claude/skills/ship-one ~/.claude/skills/judge-shipped \
       ~/.claude/skills/dream-run ~/.claude/skills/autonomous-session \
       ~/.claude/skills/autonomous-multi-ship
```

---

## Per-repo setup

Run once in each repository you want to use multi-ship with:

```bash
cd <your-repo>
multi-ship init
```

This scaffolds `.claude/multi-ship.json` from the template and appends
`.multi-ship/` to `.gitignore`. The config file is committed; the state
directory is not.

---

## Config reference

`.claude/multi-ship.json` — committed, one per repo.

| Key | Purpose | Substitution |
|---|---|---|
| `build_workflow` | Name of the Claude Code workflow that does the build (default: `"mixed-model-burst"`). Must be present in `.claude/workflows/`. | — |
| `spec_glob` | Glob used when `multi-ship` is invoked without explicit spec paths (e.g. `"docs/specs/*.md"`). | — |
| `verify` | Shell command to cold-verify CI for a PR. Run after every push; must block until all checks complete. | `$PR` → PR number (bare integer) |
| `notify` | Shell command to send the end-of-run summary to the operator. Default template uses `echo`; replace with a Telegram/Slack notifier. | Message text is passed as the first argument. |
| `pr_body_convention` | Template for the PR body's closing keyword line (e.g. `"Closes #{issue}"`). | `{issue}` → issue number extracted from the spec's `Issue:` frontmatter |
| `complete_cmd` | Claude Code skill invocation run after each successful merge for bookkeeping (e.g. `"/complete-spec {slug}"`). Runs as a fresh `claude -p`. | `{slug}` → spec filename stem (e.g. `P15` from `P15.md`) |
| `test_cmd` | Project test command passed into the build workflow (e.g. `"pytest -x"`). | — |
| `build_invariants` | One paragraph of project conventions (TDD rules, architecture constraints, etc.) injected into the build workflow prompt. | — |
| `smoke_instructions` | Recipe for the post-build smoke test injected into the build workflow. | — |
| `roles` | Role-to-model map (see section below). | — |

---

## The role→model map

The `roles` object in the config controls which Claude tier fills each role in
the `mixed-model-burst` build workflow. The defaults match the template:

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

Override any role by changing its value in your repo's config. The
`resolveModel(role, difficulty)` seam in the workflow reads from this map
exclusively — no model IDs are hardcoded in the workflow logic.

---

## Usage

Ship specific specs (run in order as given):

```bash
multi-ship docs/specs/P15.md docs/specs/P16.md
```

Ship everything matching the config glob:

```bash
multi-ship
```

Flags:

| Flag | Meaning |
|---|---|
| `--continue-on-failure` | Keep processing remaining specs when an item fails (default: stop at the first failure) |
| `--resume` | Skip specs whose status is already `shipped` in the run-log; restart at the first non-shipped item |
| `--repo <path>` | Repo root (default: current working directory) |

Subcommands:

| Subcommand | Meaning |
|---|---|
| `multi-ship init [repo]` | Scaffold `.claude/multi-ship.json` and add `.multi-ship/` to `.gitignore`. `repo` defaults to `.` |

Specs run in the order you give them (or in glob sort order). The driver does
not reorder them.

---

## How it works

```
multi-ship <specs...>  →  driver:
  caffeinate; load .claude/multi-ship.json
  init run-log (fail-closed, before item 1) + empty HANDOFF.md

  for spec in order:
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
          judge error → fail-open: log, proceed

    4. driver merges (deterministic shell):
          gh pr merge --squash --delete-branch
          claude -p "{complete_cmd}" (bookkeeping skill)
          mark shipped in run-log

  end of run:
    if HANDOFF has errors/knowledge OR ≥2 items shipped:
      claude -p "/dream-run"  → writes dream-proposals.md
    consolidate follow-up items → .multi-ship/followups.md
    notify operator (items shipped, follow-up paths, per-item checklist)
    kill caffeinate; exit
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
| `run-log.json` | Ordered item list, per-item status, stop-on-failure setting, notification surface. Written fail-closed before item 1. |
| `HANDOFF.md` | Fixed-schema append-only doc shared across all items: *Discovered knowledge*, *Errors and fixes*, *Live resources*, *Design decisions*, *Open notes*. |
| `item-<id>.json` | Per-item report written by `ship-one`: status, PR URL, branch, DoD array, files touched, follow-ups, CI tail, parent notes. |
| `verdict-<id>.json` | Per-item judge verdict written by `judge-shipped`: `{ok, reason}`. |
| `dream-proposals.md` | Proposed CLAUDE.md and memory additions from `dream-run`. Operator-reviewed; never auto-applied. |
| `followups.md` | Follow-up items collected from all item reports at end-of-run. |

`--resume` reads `run-log.json`, skips items with `status: shipped`, and
restarts at the first item that is not yet shipped. It does not clear or
rewrite existing artifacts.

---

## Worked example config

A filled-in `.claude/multi-ship.json` for a typical Python project using
pytest, `gh`, and a Telegram notifier:

```json
{
  "build_workflow": "mixed-model-burst",
  "spec_glob": "docs/specs/*.md",
  "verify": "gh pr checks $PR --watch",
  "notify": "python3 scripts/notify.py",
  "pr_body_convention": "Closes #{issue}",
  "complete_cmd": "/complete-spec {slug}",
  "test_cmd": "uv run ruff check . && uv run mypy . && uv run pytest -x",
  "build_invariants": "TDD: write the test first. All Pydantic models in api/models.py. No hardcoded credentials. Migrations in migrations/ only — no runtime CREATE TABLE.",
  "smoke_instructions": "After tests pass, run: python -c \"from myapp.config import load_config; cfg = load_config(); print('OK')\"",
  "roles": {
    "scout":   "haiku",
    "reader":  "haiku",
    "planner": "opus",
    "judges":  ["opus", "sonnet", "haiku"],
    "coder":   { "hard": "opus", "routine": "sonnet" },
    "verifier": "opus"
  }
}
```

`notify` receives the run summary as its first positional argument; adapt it to
call your notifier script, `curl` a webhook, or `pbcopy` to clipboard.

---

## Limitations

- **Claude Code only.** The driver shells `claude -p`; the skills are Claude
  Code skill files; the build workflow uses Claude Code's `Workflow()` and
  `agent()` APIs. Running against GPT-4o, Gemini, or local models is not
  supported today. The `resolveModel` seam in the workflow is where that layer
  would slot in, but the provider implementation is deferred.

- **macOS `caffeinate`.** The driver calls `caffeinate -dimsu` to prevent sleep
  during long runs. On Linux or Windows you need to adapt `driver.py`'s
  `_caffeinate` / `_kill_caffeinate` functions (a no-op stub is safe if you
  keep the machine awake yourself).

- **`gh` required.** PR creation, CI watching, and merging are all `gh` CLI
  calls. The driver has no GitHub API fallback.

- **Sequential, not parallel.** Specs run one at a time in order. Parallelism
  within a run is not implemented; specs are independent by design, but the
  driver serializes them.

- **Elevated permissions.** The inner `claude -p` sessions run unattended with
  `--permission-mode bypassPermissions`. Only point multi-ship at repos you
  own and trust — it will read, modify, and commit code without confirmation
  prompts.

- **One fix-retry per item.** If the judge rejects, `ship-one` gets one chance
  to fix and re-pass the judge. A second rejection stops the run (or skips the
  item with `--continue-on-failure`).

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Alex Monteiro.
