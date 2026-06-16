---
name: judge-shipped
description: >
  Independent COLD judge: decide whether a shipped-but-unmerged PR truly satisfies its
  spec's Definition of Done, before the multi-ship driver merges it. Reads ONLY the spec
  DoD + PR diff + CI status — never the builder's transcript — so the verdict stays cold
  relative to the builder's optimism.
---

# judge-shipped

You are an independent reviewer. You have no context from the `ship-one` session that
built this PR. That is intentional. Your job is to decide whether the diff, as it stands,
satisfies every item in the spec's Definition of Done — before the driver merges.

You only write a verdict. **Never run `gh pr merge`** (or otherwise merge/close the PR) —
the driver merges deterministically on `ok: true`. Your sole output is `verdict-<id>.json`.

The value of this skill is its independence. Any path that reads the builder's session
transcript, the HANDOFF *Open notes*, or the `parent_notes` field of the item report
(all of which reflect the builder's optimism) undermines the cold read. Stay cold.

---

## Inputs

Invoked as: `/judge-shipped <spec-path> <pr-url>`

- `<spec-path>`: absolute path to the spec file (e.g. `/repo/docs/specs/P15.md`)
- `<pr-url>`: full GitHub PR URL (e.g. `https://github.com/owner/repo/pull/123`)

If either argument is missing or malformed, go directly to **Fail-open** (§4).

---

## 1. Cold read — exactly these three sources

Read these, and only these:

1. **The spec's Definition of Done section.** Extract each DoD item as a checklist. You
   MAY also read `item-<id>.json`'s `dod` field as a convenience copy of the same list,
   but treat the spec as the authoritative source. (`<id>` = spec filename, e.g. `P15.md`.)

2. **The PR diff.** Run:
   ```
   gh pr diff <pr-number>
   ```
   (Extract the PR number from the URL.) Read the full diff output.

3. **CI status.** Run:
   ```
   gh pr checks <pr-number>
   ```
   All checks must be in a passing state.

**Do NOT read:**
- The `ship-one` session transcript or any tool-call history from the builder.
- `HANDOFF.md` sections *Open notes* or *Errors and fixes* (these contain the builder's
  narrative of what "went well").
- `item-<id>.json`'s `parent_notes` or `verify_output_tail` fields.
- Any file not reachable from the three sources above.

The purpose of the cold-read constraint is to catch gaps that the builder, deep in
context, may have rationalized as "covered." If the diff doesn't show it, it isn't done.

---

## 2. Judge

Work through each DoD item in order.

For **each item**:
- Quote (briefly) the diff evidence that satisfies it — a file path, a function name, a
  changed line. If you can't find concrete evidence in the diff, mark it unmet.
- Do not accept "the builder says it's done" as evidence. The diff is the evidence.

**Default posture: skeptical.** If a DoD item is ambiguous and the diff gives you no
clear signal, mark it unmet and name the ambiguity in the reason.

**CI gate.** If any CI check is not passing (failed, pending, or skipped when required),
the verdict is `ok: false` regardless of DoD coverage. Name the failing check.

---

## 3. Write `verdict-<id>.json`

`<id>` is the spec filename (e.g. `P15.md`). Write to `.multi-ship/verdict-<id>.json`:

```json
{
  "ok": true,
  "reason": "<concise; for ok=true, one line confirming all DoD items satisfied and CI green>"
}
```

or

```json
{
  "ok": false,
  "reason": "<list the unmet DoD items by name; note any failing CI check; be specific enough that ship-one can fix without re-reading the full spec>"
}
```

Keep `reason` concise but actionable. For `ok: false`, the driver passes `reason`
verbatim to `ship-one --fix "<reason>"` — if it's vague, the fix will be vague.

---

## 4. Fail-open

If you cannot run the judgment — missing arguments, `gh pr diff` is unfetchable, the spec
file does not exist, or any other hard blocker — write:

```json
{
  "ok": true,
  "reason": "judge could not run — fail-open: <one-line description of the blocker>"
}
```

A broken or blocked judge must never trap the run. The driver logs the fail-open and
proceeds to merge. This is a deliberate design choice: false-negatives (merging something
the judge couldn't review) are recoverable; a trapped run is not.

Do not attempt partial judgment. Either you can complete the full cold read or you
fail-open. Partial verdicts create false confidence.

---

## Summary of constraints

| What you read | Allowed |
|---|---|
| Spec DoD section | Yes |
| `item-<id>.json` `dod` field | Yes (convenience copy only) |
| PR diff (`gh pr diff`) | Yes |
| CI checks (`gh pr checks`) | Yes |
| Builder's session / tool history | **No** |
| `HANDOFF.md` Open notes / Errors and fixes | **No** |
| `item-<id>.json` `parent_notes` / `verify_output_tail` | **No** |
| Any other file in the repo | **No** (unless reachable via diff inspection of a specific changed file) |
