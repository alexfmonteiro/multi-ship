# multi-ship

**Ship a backlog of specs autonomously on Claude Code — one fresh context per item.**

[![CI](https://github.com/alexfmonteiro/multi-ship/actions/workflows/test.yml/badge.svg)](https://github.com/alexfmonteiro/multi-ship/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

Long autonomous Claude Code sessions rot. After a handful of work items the
session is bloated, drags stale reasoning from earlier items into new ones, and
a single crash wipes all progress. And here's the catch: **a Claude Code session
cannot clear or compact its own context.** `/clear` and `/compact` are user-only
gestures; hooks can't spawn sessions; `--resume` and `--continue` reuse the old
history. The only guaranteed reset is a fresh `claude -p` invocation.

**multi-ship inverts the loop.** It moves orchestration out of the Claude session
into a thin Python driver and gives **every work item its own `claude -p` — a
clean slate, like an automatic `/clear` between items.** Cross-item memory lives
on disk in a fixed-schema handoff doc. Before each merge, an independent **cold
judge** (a separate `claude -p` that sees only the spec's Definition of Done and
the PR diff) decides whether the work actually shipped. The driver is dumb — it
routes only on status/verdict files and never reasons about code. Every decision
that needs judgment is a fresh, cold model call.

```text
multi-ship docs/specs/*.md
  └─ for each spec, in order:
       fresh claude -p  →  build in a worktree  →  open PR  →  drive CI to green
       fresh COLD claude -p judge  →  reads only spec DoD + PR diff  →  {ok, reason}
       driver merges (squash) only when the judge says ok  →  next item, clean context
```

> **Demo:** _(asciinema cast coming — see [docs/demo.md](docs/demo.md) to record one)._

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

Flags:

| Flag | Meaning |
|---|---|
| `--continue-on-failure` | Keep processing remaining specs when an item fails (default: stop at the first failure) |
| `--resume` | Skip specs already `shipped` in the run-log; restart at the first non-shipped item |
| `--repo <path>` | Repo root (default: current working directory) |

Subcommands:

| Subcommand | Meaning |
|---|---|
| `multi-ship init [repo]` | Scaffold `.claude/multi-ship.json` and add `.multi-ship/` to `.gitignore`. `repo` defaults to `.` |
| `multi-ship install-skills [--copy]` | Link (or copy) the bundled skills into `~/.claude/skills` |

Specs run in the order you give them (or in glob sort order). The driver does not
reorder them.

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
| `roles` | Role-to-model map (see below). | — |

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
| `run-log.json` | Ordered item list, per-item status, stop-on-failure setting, notification surface. Written fail-closed before item 1. |
| `HANDOFF.md` | Fixed-schema append-only doc shared across all items: *Discovered knowledge*, *Errors and fixes*, *Live resources*, *Design decisions*, *Open notes*. |
| `item-<id>.json` | Per-item report written by `ship-one`: status, PR URL, branch, DoD array, files touched, follow-ups, CI tail, parent notes. |
| `verdict-<id>.json` | Per-item judge verdict written by `judge-shipped`: `{ok, reason}`. |
| `dream-proposals.md` | Proposed CLAUDE.md and memory additions from `dream-run`. Operator-reviewed; never auto-applied. |
| `followups.md` | Follow-up items collected from all item reports at end-of-run. |

`--resume` reads `run-log.json`, skips items with `status: shipped`, and restarts
at the first item that is not yet shipped. It does not clear or rewrite existing
artifacts.

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
