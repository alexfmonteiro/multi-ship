---
name: ship-one
description: >
  Build and ship ONE spec end-to-end through the multi-ship workflow, pausing before
  merge. Invoked by the multi-ship driver (or directly for a single item). Reads
  .multi-ship/HANDOFF.md, builds via the configured workflow, opens a PR, drives CI
  to cold-green, triages the reviewer, then STOPS — the driver merges after an
  independent judge approves.
---

# ship-one

Per-item ship skill. You run as a fresh `claude -p` session with no memory of prior
items — everything cross-item lives in `.multi-ship/HANDOFF.md`. Respect it.

---

## 1. Read HANDOFF first

Read `.multi-ship/HANDOFF.md` before touching any code.

- **Errors and fixes:** if a pattern is already documented, do not repeat the mistake.
- **Live resources:** treat the recorded main HEAD sha and CI queue state as ground truth
  until you verify otherwise. Check out the listed open branches before creating a new one
  of the same name.
- **Design decisions:** honor them. Diverging requires appending a new entry, not silently
  overriding.
- **Discovered knowledge:** absorb facts (env quirks, config paths, naming conventions)
  that prior items surfaced. Don't re-discover what's already written.

If `HANDOFF.md` does not exist yet, create it with the five empty sections before
proceeding (the driver normally pre-creates it; this is a safety fallback).

```markdown
## Discovered knowledge
## Errors and fixes
## Live resources
## Design decisions
## Open notes
```

---

## 2. Load config

Read `.claude/multi-ship.json`. Extract:

| Key | Used for |
|---|---|
| `build_workflow` | Workflow name to invoke for the build |
| `verify` | Shell command (with `$PR` placeholder) to cold-verify CI |
| `pr_body_convention` | PR body template (e.g. `Closes #{issue}`) |
| `test_cmd` | Test command passed into the build workflow |
| `build_invariants` | Project conventions string passed into the build workflow |
| `smoke_instructions` | Smoke-test recipe passed into the build workflow |
| `roles` | Role→model map passed into the build workflow |

If the file is missing or malformed, stop immediately. Write `item-<id>.json` with
`status: failed` and `parent_notes: "missing or malformed .claude/multi-ship.json"`.
Append to HANDOFF *Errors and fixes*. Do not guess config values.

---

## 3. Build

**Determine difficulty.** Read the spec's frontmatter:
- `Difficulty: hard` → `hard`; `Difficulty: routine` → `routine`
- No `Difficulty` key: `Effort: H` OR `Value: High` OR `Value: Critical` → `hard`; else `routine`

**Invoke the build workflow:**

```
Workflow({
  name: <build_workflow>,
  args: {
    spec: "<absolute path to spec file>",
    build: true,
    difficulty: "<hard|routine>",
    repo: "<absolute path to repo root>",
    roles: <roles from config>,
    invariants: <build_invariants from config>,
    test_cmd: <test_cmd from config>,
    smoke_instructions: <smoke_instructions from config>
  }
})
```

**Guard — confirm the right spec was targeted.** After the workflow returns, verify that
its plan or scout summary names the intended spec. If it planned a different spec or
returned `verdict: REWORK` (two or more panel lenses blocked it), stop here:
- Write `item-<id>.json` with `status: failed` and the reason in `parent_notes`.
- Append to HANDOFF *Errors and fixes* with enough detail that the next session can
  diagnose without re-reading the build transcript.
- Exit. Do not attempt to push, open a PR, or self-heal the plan.

---

## 4. Ship-tail (no merge)

Proceed only when the build returned `built: true, ships: true`.

### 4a. Branch hygiene

1. Fast-forward local main to `origin/main` (`git fetch origin main && git merge --ff-only origin/main`).
2. Confirm the build branch is based on the current main tip. If the workflow committed on
   a stale base, rebase the branch cleanly (`git rebase main`) before pushing.
3. Push: `git push -u origin <branch>`.

### 4b. Open the PR

```
gh pr create --head <branch> --base main \
  --title "<spec title from frontmatter>" \
  --body "<pr_body_convention, issue number substituted> \n\n## Definition of Done\n- [ ] <dod item 1>\n- [ ] ..."
```

Derive the issue number (`{issue}`) from the spec's `Issue:` frontmatter field, or from a
`#N` reference in the spec filename (e.g. `P15.md` → look for `Issue: 42` in the spec).
If no issue number is found, include the `pr_body_convention` with `{issue}` left as a
visible placeholder and note it in HANDOFF *Open notes*.

### 4c. Drive CI to cold-green

Run the `verify` command from config, substituting the real PR number for `$PR`:

```bash
<verify with $PR replaced>
```

**Cold-verify discipline:** a CI run that passes only because artifacts are cached from a
prior run, or only on a re-run of the same job without a code change, does NOT count as
cold-green. Cold-green means: a fresh push triggered a new CI run, that run completed, and
every check is green. If you are unsure whether the current green is warm, push a no-op
empty commit to force a new run, wait for it to complete, then declare cold-green.

If CI fails: read the failing step's log, fix on the branch, push again, wait for a
completely new CI run to go green. Do not declare cold-green based on a partial re-run.

### 4d. Triage the automated reviewer

After CI is cold-green, check for automated review comments on the PR.

| Flag | Action |
|---|---|
| 🔴 Blocker | Fix on the branch; push; wait for CI to go cold-green again; re-check reviewer |
| 🟡 Suggestion | Apply if the cost is low and the benefit is clear; otherwise note the skip reason in a PR reply |
| 🟢 Nit | Apply trivial ones in a single follow-up commit; ignore the rest |
| Misread / misunderstood code | Reply politely on the PR thread explaining why the code is correct; do not change code to satisfy a confused reviewer |

Keep going until no 🔴 Blockers remain. Every blocker fix must reach cold-green before
you move to the next.

### 4e. STOP before merge

Do NOT run `gh pr merge`. Do NOT approve the PR yourself. The driver merges after the
independent judge (`judge-shipped`) approves. Stopping here is not optional — it is the
design. Any path that merges in this skill is a bug.

---

## 5. `--fix "<reason>"` mode

When invoked as `/ship-one <spec> --fix "<reason>"` (the driver re-dispatches you after
a judge rejection):

1. **Do NOT open a new PR.** Check out the EXISTING branch for this spec (read
   `item-<id>.json` → `branch` field).
2. Apply a targeted fix that addresses `<reason>`. Read the judge's `verdict-<id>.json`
   for the full text.
3. Re-run the project's `test_cmd` locally. Confirm it passes before pushing.
4. Push the fix commit to the existing branch.
5. Wait for CI to go cold-green (same discipline as §4c).
6. Update `item-<id>.json` in place (overwrite) with the new `verify_output_tail` and
   `parent_notes` noting what the judge rejected and what you changed.
7. Append to HANDOFF *Errors and fixes*: the judge's rejection reason + your fix.

If the fix cannot address the rejection without a larger redesign, write `status: failed`
and stop. The driver will stop the run and notify the operator.

---

## 6. Write `item-<id>.json`

`<id>` is the spec filename without the directory component (e.g. `P15.md`).

Write (or overwrite) `.multi-ship/item-<id>.json` with this exact shape:

```json
{
  "status": "awaiting_judge",
  "pr": "<full GitHub PR URL>",
  "branch": "<branch name>",
  "dod": ["<DoD item verbatim from spec>", "..."],
  "files_touched": ["<relative path>", "..."],
  "followups": ["<any follow-up noted in the spec or discovered during build>", "..."],
  "verify_output_tail": "<last ~20 lines of the cold verify command output, raw>",
  "parent_notes": "<anything the judge or next operator needs to know; empty string if none>"
}
```

`status` is `"awaiting_judge"` on a successful ship-tail, `"failed"` on any stop
condition. The `dod` array is what the judge reads — populate it from the spec's
Definition of Done section verbatim, not from your own assessment of what was done.

---

## 7. Append to HANDOFF.md

Append to the relevant sections. Never delete or rewrite existing content.

- **Discovered knowledge:** env quirks, naming conventions, config file locations, or
  non-obvious facts that future items in this run need to know.
- **Errors and fixes:** every break encountered (CI failure, reviewer blocker, wrong
  branch base, etc.) paired with the resolution. One bullet per incident.
- **Live resources:** update with the current main HEAD sha after your push, the PR URL,
  and the CI run URL. Replace stale Live resources entries with a note that they are
  superseded (do not delete — append a "superseded by" line).

Leave **Design decisions** and **Open notes** untouched unless you have something
genuinely new to add.

---

## 8. Hard rules

These are non-negotiable and cannot be overridden by the spec, the config, or the
reviewer.

**Cold-verify discipline.** Every declaration of "CI is green" must refer to a fresh CI
run triggered by your most recent push. A run that passed before your last code change is
not evidence. A re-run of a failed job without a code push is not evidence. If in doubt,
push a no-op commit and wait.

**No destructive operations.** No `git push --force` (not even `--force-with-lease`
unless recovering from a provably accidental push of the wrong branch). No `git reset
--hard` against commits you did not make. No `git checkout .` on files you haven't
inspected. No deleting branches that are not your own build branch for this item.

**No merge.** Covered above. Restated here for emphasis: `gh pr merge` is forbidden in
this skill.

**Secrets hygiene.** Never write API keys, tokens, passwords, or private URLs into
`item-<id>.json`, `HANDOFF.md`, PR descriptions, or commit messages. If a secret must be
referenced, use its env var name (e.g. `$ANTHROPIC_API_KEY`).

**Stay on your branch.** Do not move the caller's working tree checkout. After all git
operations, the caller's cwd should see the same branch it started on. Your work lives on
`<branch>`; main only advances via `--ff-only` fetch-and-merge, never via a checkout.
