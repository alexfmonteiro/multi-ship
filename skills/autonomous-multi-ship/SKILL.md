---
name: autonomous-multi-ship
description: >
  Use when the operator asks to ship N independent specs end-to-end autonomously in one
  shot ("ship these N specs", "burst the backlog autonomously", "do the whole backlog in
  one shot"). The multi-ship driver loops a fresh claude -p session per item so the
  parent context never bloats. Do NOT trigger for a single item (use autonomous-session)
  or interactive work.
---

# autonomous-multi-ship

N-item autonomous ship. The driver (`bin/multi-ship`) is a Python process OUTSIDE any
Claude session — it owns the loop, the durable run-log, `--resume`, stop-on-failure,
deterministic merge, and end-of-run consolidation. Each item runs in its OWN fresh
`claude -p` session. That fresh-context-per-item is the whole point: no parent-context
bloat, crash-resumable on disk.

---

## When this triggers

Explicit operator request to ship MULTIPLE items autonomously:

- "ship these N specs"
- "burst the backlog autonomously"
- "do the whole backlog in one shot"
- "run all of these unattended"

Single item → use `autonomous-session`. Interactive ship-by-ship → normal workflow.

---

## Prerequisites the operator provides

- **Ordered spec list.** Order matters — the driver runs sequentially. Provide paths or a
  glob. Specs that depend on earlier ones must come after them.
- **Initialized repo.** Run `multi-ship init` once; fill in `verify`, `notify`,
  `test_cmd`, and `build_invariants` in `.claude/multi-ship.json`.
- **Failure policy.** Default: stop on first failure (later items often depend on earlier
  ones). Pass `--continue-on-failure` to override.
- **Decision-complete specs.** Run `multi-ship preflight <specs…>` BEFORE launching and
  resolve everything it flags with the operator up front. A spec with a placeholder
  `Issue: 0`, no Definition of Done, or `TBD`/`???`/`FIXME` markers will otherwise burn a
  full build cycle only to stop at the plan gate mid-run. Preflight catches mechanical
  gaps; latent design ambiguity still surfaces at the plan gate, so also skim each spec
  for unanswered design questions and batch them to the operator in one pass.

---

## How to run it

```bash
# readiness gate first — resolve anything it flags before launching:
multi-ship preflight docs/specs/P15.md docs/specs/P16.md docs/specs/P17.md
multi-ship docs/specs/P15.md docs/specs/P16.md docs/specs/P17.md
# or a glob:
multi-ship docs/specs/P1*.md
# resume a crashed or stopped run:
multi-ship docs/specs/P15.md docs/specs/P16.md docs/specs/P17.md --resume
```

The driver invokes `ship-one` (build + ship-tail) and `judge-shipped` (cold verdict) for
each item, then merges deterministically on judge `ok: true`. At the end it runs
`dream-run` (if the run produced durable signals) and sends the structured notify.

Per-item state lives in `.multi-ship/item-<id>.json`; cross-item knowledge in
`.multi-ship/HANDOFF.md`. `--resume` skips items whose `item-<id>.json` already shows
`status: shipped` and restarts at the first non-shipped item.

---

## When the run stops — failure taxonomy

The driver never exits via an unhandled traceback: any item error is caught, the item is
marked `failed`, and the end-of-run notify still fires (exit 2 when stopped). When you (the
supervising agent) are relaying a stop, distinguish two kinds:

- **Genuine failure** — a spec/build/judge problem: plan-gate REWORK, CI red the builder
  couldn't fix, judge rejected twice, a real merge conflict. The work is wrong or
  blocked. STOP and ping the operator with the reason; do not paper over it. This is what
  "stop on first failure" protects against (later items often build on earlier ones).
- **Spurious/infra hiccup** — the item's deliverable is actually fine but a mechanical
  step failed (e.g. a flaky post-merge cleanup; a PR that merged on GitHub while the
  run-log still says otherwise). Verify the real state (`gh pr view`, `git`), finish the
  interrupted tail, and `--resume`. The driver now self-heals the common cases
  (`_merge_pr` is fail-soft on branch cleanup; `_process_item` short-circuits an
  already-merged PR on resume instead of rebuilding), so a clean `--resume` usually
  suffices — but confirm before continuing.

## Permissions (parent-session recovery)

The driver's `claude -p` children run with `--permission-mode bypassPermissions`, so the
driver pushes, merges, and deletes branches on its own. A **parent interactive session**
doing manual recovery does NOT have that — the auto-mode classifier blocks `git push
origin main` and remote-branch deletes. Before a run that may need hands-on recovery,
either add `Bash(git push origin main:*)` to `.claude/settings.local.json`, or expect to
hand those pushes to the operator (`! git push origin main`). Commit recovery work
locally regardless — the next `--resume` build worktree branches from local HEAD and will
see it.

## What the driver does NOT do

- Decide ordering — the operator provides it.
- Merge red PRs or PRs the judge rejected.
- Run from a long-lived parent session — the driver is the orchestrator; there is no
  parent Claude session holding state.

---

## Note on the old design

The previous version ran the full loop plus a long list of prose hard-rules inside one
Claude session. Those rules are now CODE in the driver (run-log fail-closed,
stop-on-failure routing, no parent-checkout pollution) or live in `ship-one`. They are
not re-listed here.

---

## Related

- `autonomous-session` — the N=1 case of the same driver
- `ship-one` — per-item build + ship-tail skill (invoked fresh per item)
- `judge-shipped` — cold independent verdict before each merge
- `dream-run` — end-of-run consolidation and knowledge promotion
- `mixed-model-burst` workflow — the build workflow each `ship-one` session invokes
