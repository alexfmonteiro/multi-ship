---
name: dream-run
description: >
  End-of-run consolidation: mine the run's HANDOFF.md + item reports for durable,
  reusable knowledge and draft PROPOSED additions to the project's CLAUDE.md gotchas +
  memory — written to .multi-ship/dream-proposals.md for operator review. Never edits
  CLAUDE.md or memory directly.
---

# dream-run

Offline consolidation skill. You run after all items in a multi-ship run are complete
(shipped or failed). Your output is a proposals doc — not a commit, not an edit. The
operator reviews and decides what to promote. Never touch `CLAUDE.md`, `~/.claude/`, or
any memory file directly.

---

## Inputs

Invoked as: `/dream-run` (no arguments; all input is on disk in `.multi-ship/`).

The driver invokes this automatically when the run ends, gated on: non-empty
*Errors and fixes* or *Discovered knowledge* sections in `HANDOFF.md`, OR two or more
items with `status: shipped`. If neither condition holds, the driver skips you and logs
"nothing durable to promote, dream-run skipped." You can also be invoked directly by the
operator at any time.

---

## 1. Read the run artifacts

Read all of these:

- `.multi-ship/HANDOFF.md` — all five sections.
- `.multi-ship/item-*.json` — every item report present (glob; read all).

Do not read verdicts, spec files, or repo source code. The proposals come from what
actually happened this run, not from what the specs intended.

---

## 2. Extract durable signals

Look for:

**From *Errors and fixes*:**
- Recurring patterns (same mistake across two or more items, or a mistake that cost
  significant recovery time on even a single item).
- Non-obvious gotchas: things that look fine until they aren't (env var ordering, CI
  warm/cold confusion, naming collisions, config keys that must co-appear, etc.).
- Anything a fresh session would hit again if it weren't warned.

**From *Discovered knowledge*:**
- Facts about the project's conventions, config file locations, tool behaviors, or
  external service quirks that are not already documented in the project's `CLAUDE.md`
  or memory files.
- Verified assumptions that future sessions can rely on (e.g., "branch naming convention
  is `burst/<id>-<slug>`, confirmed on three items").

**From item reports (`followups` field):**
- Follow-up items that surfaced during build but weren't in the original spec. These are
  not gotchas — note them separately only if they recur across items (suggesting a
  systemic gap) or represent a significant pattern.

**Filter aggressively.** One-off flukes, noise, items already documented, and things that
only make sense in the context of this specific run are not durable. If you're unsure
whether something is worth promoting, don't promote it — the operator can add it manually
if it recurs.

---

## 3. Write `.multi-ship/dream-proposals.md`

Write the proposals doc. The first line must be:

```
These are proposals — the operator reviews and applies.
```

Then two clearly-labelled sections:

### Section A: Proposed CLAUDE.md "Active gotchas" additions

One entry per proposed gotcha. Format each as it would appear verbatim in the `CLAUDE.md`
"Active gotchas" table — a bold lead phrase followed by a concise explanation. Include a
one-line rationale in a `> Rationale:` blockquote below each entry so the operator knows
why it was surfaced.

Example format (do not include this example in the output):

```
- **`verify` cold-green discipline.** A CI run that passes only because artifacts were
  cached from a prior run does not count as cold-green. Always push a new commit or
  empty commit to force a fresh run before declaring green.
  > Rationale: Hit on items P15 and P17; cost ~40 min of rework each time.
```

If nothing from this run is durable enough to promote, write:

```
### Proposed CLAUDE.md "Active gotchas" additions

Nothing durable to promote from this run.
```

### Section B: Proposed ~/.claude memory additions

One entry per proposed memory item. Format each as a short key-value pair suitable for a
memory file entry: a bolded topic line followed by one or two sentences of content.
Include a `> Rationale:` blockquote.

Example format (do not include this example in the output):

```
- **Branch base hygiene (multi-ship).** After a build workflow completes, always
  fast-forward local main and rebase the build branch before pushing — the workflow
  runs in a worktree and may be based on a stale tip.
  > Rationale: Surfaced on P15; manifested as a stale-base CI failure that took two
    re-runs to diagnose.
```

If nothing warrants a memory addition, write:

```
### Proposed ~/.claude memory additions

Nothing durable to promote from this run.
```

---

## 4. Nothing-durable case

If after reading all artifacts you find nothing that meets the filter in §2, write a
minimal proposals doc:

```markdown
These are proposals — the operator reviews and applies.

## Proposed CLAUDE.md "Active gotchas" additions

Nothing durable to promote from this run.

## Proposed ~/.claude memory additions

Nothing durable to promote from this run.
```

Do not manufacture proposals to appear thorough. An empty proposals doc is the correct
output when the run was clean.

---

## Hard rules

**Never auto-edit.** Do not write to `CLAUDE.md`, any file under `~/.claude/`, any
project memory file, or any file outside `.multi-ship/`. The proposals doc is your entire
output. All edits happen when the operator decides to apply them.

**Proposals doc only.** Do not create PRs, open issues, or commit changes as part of this
skill. Write `.multi-ship/dream-proposals.md` and stop.

**No invention.** Every proposed entry must trace back to a specific entry in HANDOFF or
a specific item report. If you cannot cite the source, do not include it.
