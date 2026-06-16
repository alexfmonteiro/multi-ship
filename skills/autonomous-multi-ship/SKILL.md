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

---

## How to run it

```bash
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
