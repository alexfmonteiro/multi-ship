---
name: autonomous-session
description: >
  Use when the operator asks for a fully autonomous, end-to-end ship of ONE burst/spec
  with no further confirmation prompts ("go ahead autonomously", "ship it and ping me
  when done"). Single-item autonomous ship = the multi-ship driver with N=1. Do NOT
  trigger for normal interactive work.
---

# autonomous-session

Single-item autonomous ship. This is the N=1 case of the same driver that
`autonomous-multi-ship` uses — one code path, both modes.

---

## When this triggers

Explicit operator opt-in to skipping confirmation pauses:

- "go ahead autonomously"
- "ship it and ping me when done"
- "do the whole thing unattended"
- "caffeinate and run it"

If the operator is interacting in real time and expects confirmation pauses, use the
normal interactive workflow instead.

---

## How to run it

1. Ensure the repo is initialized: `multi-ship init` (once per repo, scaffolds
   `.claude/multi-ship.json`).
2. Run: `multi-ship <abs-spec-path>`

The driver (`bin/multi-ship`) owns the full lifecycle:
- caffeinates the session
- builds via the configured `build_workflow` (the `mixed-model-burst` workflow)
- gates with the cold `judge-shipped` skill before the irreversible merge
- merges deterministically on judge `ok: true`
- runs end-of-run `dream-run` consolidation
- sends the structured notify and exits

Do NOT re-implement the lifecycle here. `bin/multi-ship` is the single source of truth.

---

## What the driver commits to

These are enforced by the driver and `ship-one` — not re-litigated here:

- TDD/trifecta honored via the build workflow
- Cold-verify gating (CI must be fresh-green, not warm-cached)
- No destructive git operations
- Judge gate runs before the irreversible merge
- No silent failures — any off-script condition notifies the operator and stops

---

## When NOT to use

- Interactive sessions where the operator wants to confirm each step
- Multi-item backlogs → use `autonomous-multi-ship`
- Ambiguous or underspecified specs → clarify with the operator first

---

## Related

- `autonomous-multi-ship` — the N-item version of the same driver
- `ship-one` — per-item build + ship-tail skill the driver invokes
- `judge-shipped` — cold independent verdict before merge
- `dream-run` — end-of-run consolidation and knowledge promotion
