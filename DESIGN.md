# multi-ship — Design

**Date:** 2026-06-16
**Status:** Approved design, pre-implementation
**License:** MIT (open source)
**Home:** `~/Projects/multi-ship` (own git repo, to be published on GitHub)
**Scope:** Global, cross-project autonomous multi-item shipping with true
fresh-context-per-item, built on Claude Code, distributed as an installable CLI + skills.

> NOTE: this design doc currently lives at `~/.claude/scripts/multi-ship/DESIGN.md`
> from the earlier draft. On implementation it moves into the new repo at
> `~/Projects/multi-ship/DESIGN.md` (or `docs/DESIGN.md`) and the `~/.claude` copy is removed.

## Problem

The existing `autonomous-multi-ship` skill keeps the *build* out of the parent
session (via `mixed-model-burst` subagents) but runs the ship-tail (CI watching,
reviewer triage, bookkeeping) and the orchestration loop *inside* one long-lived
parent session. After N items that parent context bloats, can't survive a crash,
and carries 14 incident-stamped hard rules as prose.

A Claude Code session **cannot clear or compact its own context** (`/clear`,
`/compact` are user-only; hooks can't spawn sessions; `--resume`/`--continue`
reuse old context). The only mechanism that guarantees a context reset without
forking the harness is a fresh `claude -p` invocation per item. So the fix is to
**invert the architecture**: move the loop out of the session into a thin driver,
make each item its own `claude -p` session, and keep all cross-item memory on disk.

## Relationship to Xiaomi MiMo Code

MiMo Code (forked from OpenCode) solves the same long-horizon problem by keeping
ONE long-lived session and managing it well: checkpoint-reconstruct, prune stale
tool outputs, cold-judge stop-gates, a relational task tree, and `/dream` offline
consolidation. They can do that because they *own the harness*.

We sit on top of Claude Code and own nothing inside the session — so
fresh-context-per-item is our only guaranteed reset, not an inferior patch. MiMo's
cleverest ideas live *above* the harness (files + extra model calls) and port
cleanly. We steal three:

- **① Fixed-schema handoff doc** (their 11-section `checkpoint.md`) → our `HANDOFF.md`.
- **② Cold-judge stop-gate** (their `/goal` + independent judge) → our `judge-shipped`.
- **③ Offline consolidation** (their `/dream`) → our `dream-run`.

We deliberately do NOT copy their intra-context pruning (we can't — no harness
control); our mitigation is that the heavy build already runs in isolated worktree
subagents, so each item's `claude -p` session only carries the ship-tail.

**The MiMo lesson that frames the OSS story:** *the harness ideas are model-agnostic
and portable; a given implementation is not.* So the README documents the patterns
as portable, while being honest that this implementation runs on Claude Code.

## Architecture

A **dumb Python driver** runs the loop outside any Claude session. Each work item
is its own `claude -p` invocation (fresh context). Three skills supply the per-item
brains; a bundled generic workflow does the build; a per-project config file supplies
the specifics. Everything is shipped from one repo and placed by an installer.

```
~/Projects/multi-ship/              # the OSS repo (source of truth)
  bin/multi-ship                    # CLI entrypoint (on PATH after install)
  src/multi_ship/
    driver.py                       # loop, run-log, resume, stop-on-failure, merge, notify
    config.py                       # load + validate .claude/multi-ship.json
    runlog.py                       # run-log read/write + item-status state machine
    __init__.py
  skills/
    ship-one/SKILL.md               # per-item: build → PR → CI cold-green → reviewer → PAUSE
    judge-shipped/SKILL.md          # cold pre-merge DoD gate
    dream-run/SKILL.md              # consolidation → proposals
    autonomous-session/SKILL.md     # thin → "run the driver, N=1"
    autonomous-multi-ship/SKILL.md  # thin → "run the driver, N items"
  workflows/
    mixed-model-burst.js            # GENERIC, parametrized model map + config-driven invariants
  templates/
    multi-ship.json                 # per-project config template (multi-ship init drops this)
  tests/                            # pytest over driver pure logic
  install.sh                        # symlink skills→~/.claude/skills, bin→PATH; idempotent
  README.md  LICENSE(MIT)  DESIGN.md  .gitignore

# installer places (symlinks) into:
~/.claude/skills/{ship-one,judge-shipped,dream-run,autonomous-session,autonomous-multi-ship}
PATH/multi-ship → ~/Projects/multi-ship/bin/multi-ship

# per-project (multi-ship init <repo>):
<target-repo>/.claude/multi-ship.json   # config (committed)
<target-repo>/.claude/workflows/mixed-model-burst.js  # symlink/copy of the generic workflow
<target-repo>/.multi-ship/               # run-scoped state (gitignored)
    run-log.json  HANDOFF.md  item-<id>.json  verdict-<id>.json  dream-proposals.md
```

The driver never reasons about code. It routes only on `{status}` / `{ok}` files.
Any judgment needed is a fresh `claude -p`, keeping every decision cold.

## Distribution & installation

- **`install.sh`** (idempotent): symlinks each `skills/*` dir into `~/.claude/skills/`,
  puts `bin/multi-ship` on PATH (symlink into `~/.local/bin` or print the export line),
  checks deps (python3, `gh`, `claude`, `caffeinate` on macOS). Symlink (not copy) so
  `git pull` updates everything. Refuses to clobber a pre-existing non-symlink skill of
  the same name — warns instead.
- **`multi-ship init [repo]`**: scaffolds `<repo>/.claude/multi-ship.json` from the
  template, drops/symlinks the generic workflow into `<repo>/.claude/workflows/`, and
  adds `.multi-ship/` to the repo's `.gitignore`. One-time per repo.
- **Uninstall** path documented in README (remove symlinks).
- Future option (noted, not v1): package skills+workflow as a Claude Code **plugin** for
  marketplace install; the driver stays a standalone CLI either way.

## The loop (data flow)

```
multi-ship <specs...>  →  driver:
  caffeinate; load .claude/multi-ship.json; snapshot dirty parent state;
  init run-log (FAIL-CLOSED, before item 1) + empty HANDOFF.md; ensure .gitignore
  for spec in order:
    1. claude -p "/ship-one <spec>"          # fresh context; reads HANDOFF.md first
          → builds via {config.build_workflow}, opens PR, waits CI cold-green,
            triages reviewer, then STOPS before merge
          → writes item-<id>.json {status: awaiting_judge|failed, pr, branch, dod, ...}
          → appends Discovered-knowledge / Errors-and-fixes to HANDOFF.md
    2. driver reads item-<id>.json;  status=failed → stop loop + notify
    3. claude -p "/judge-shipped <spec> <pr>"  # fresh COLD context
          → reads spec DoD + PR diff + CI status ONLY → verdict-<id>.json {ok, reason}
          ok=false → driver re-dispatches ship-one with the reason to FIX → re-judge;
                     still ok=false after that 1 retry → stop loop + notify (NOTHING merged)
          judge error → FAIL-OPEN: log, proceed (a flaky judge can't trap the run)
    4. driver merges (deterministic, shell): gh pr merge --squash --delete-branch;
          bookkeeping via fresh `claude -p "{config.complete_cmd}"` (a skill,
          can't run in-process); ff main; assert parent tree clean → mark shipped
  end:
    if HANDOFF worth consolidating (non-empty Errors/Knowledge, or ≥2 shipped):
      claude -p "/dream-run"  → reads HANDOFF.md + item reports → dream-proposals.md
    else: log "nothing durable to promote", skip
    consolidate FOLLOWUPS → new follow-up spec (number allocated LAST, re-scan index)
    notify via {config.notify} (items shipped, follow-up spec, run-log + proposals paths,
      per-item operator checklist); kill caffeinate; exit
```

## Components & contracts

### bin/multi-ship + src/multi_ship/driver.py
- **CLI:** `multi-ship <specs...>` | `multi-ship init [repo]` | `multi-ship --resume`.
  Flags: `--repo` (default cwd), `--stop-on-failure/--continue-on-failure` (default stop).
- **Owns:** caffeinate (own PID), the ordered list (re-read from args, never held in a
  model's memory), run-log lifecycle, deterministic `gh pr merge` (shell), the
  re-dispatch-to-fix loop, end-of-run notification, resume (skip `status=shipped`,
  restart at failure). Judge, bookkeeping, dream all run as fresh `claude -p` it shells.
- **Pure-logic units (unit-tested):** `config.load/validate`, `runlog` state machine,
  resume selection, stop-on-failure routing, "dream worth running?" gate.
- **Cannot:** reason about code, triage a novel failure (by design — stops + notifies).

### ship-one (skill) — the single per-item unit
Replaces the per-item body of both old autonomous skills.
- Reads `HANDOFF.md` first. Builds via `Workflow({name: config.build_workflow,
  args:{spec, build:true, difficulty, repo, invariants}})`.
- Ship-tail: push → PR (`config.pr_body_convention`) → CI cold-green (`config.verify`)
  → reviewer triage. **STOPS before merge.**
- Writes `item-<id>.json {status, pr, branch, dod, files_touched, followups,
  verify_output_tail, parent_notes}`; appends to `HANDOFF.md`.
- Carries the prose hard rules that can't be code: cold-verify discipline, no
  destructive ops, secrets hygiene.

### judge-shipped (skill) — Steal ②
- Independent `claude -p`, fed ONLY spec DoD + PR diff + CI status (never the builder's
  transcript → cold read). Returns `verdict-<id>.json {ok, reason}`.
- Driver re-dispatches the fix at most once, then stops. **Fail-open** on judge error.

### dream-run (skill) — Steal ③
- Reads `HANDOFF.md` + item reports; writes `dream-proposals.md` (proposed CLAUDE.md
  "gotchas" + memory-file additions). **Proposes, never auto-edits.**
- **Triggers:** explicit `/dream-run`, always available; AND automatic at end of every
  driver run, **gated** (non-empty Errors/Knowledge or ≥2 shipped; else skip + log).
- **Not v1:** MiMo's periodic ~weekly cadence (needs cross-run trace accumulation).

## Steal ① — HANDOFF.md schema

Fixed schema, append-only, run-scoped, injected into every `ship-one`/`judge-shipped`
prompt. Trimmed from MiMo's 11-section checkpoint to the cross-item sections only:

```markdown
## Discovered knowledge      # durable facts the next item needs
## Errors and fixes          # what broke + the resolution
## Live resources            # main HEAD sha, CI queue state, open branches
## Design decisions          # choices later items must stay consistent with
## Open notes                # anything unclassified
```

## Bundled workflow — generic, parametrized mixed-model-burst.js

The current `mixed-model-burst.js` is project-hardcoded (`const REPO = '<path>'`,
hardcoded model IDs, project-specific invariants, the literal test command,
"burst"/CLAUDE.md language). For OSS it becomes generic:

1. **Parametrized model map (role→model), config-driven, Claude defaults + abstraction seam.**
   A `resolveModel(role, difficulty)` indirection so every `agent({model})` reads from the
   map, never a literal. Default map:
   ```
   scout: haiku, reader: haiku, planner: opus,
   judges: [opus, sonnet, haiku], coder: {hard: opus, routine: sonnet}, verifier: opus
   ```
   The map is overridable via `args.roles` (driver passes it from config). The seam means
   a future non-Claude vendor layer slots in at `resolveModel` without touching call sites.
2. **Repo from `args.repo`** (driver passes it; falls back to session cwd — `claude -p`
   runs in the repo), dropping the hardcoded `const REPO` and `git -C ${REPO}`.
3. **Project conventions injected, not hardcoded.** Any project-specific invariants
   (e.g. test-first, typed models, no hardcoded secrets, migration-only schema changes)
   come from `config.build_invariants` / `config.test_cmd` / `config.smoke_instructions`,
   passed via `args.invariants`. Generic language ("the task spec", "the project's test
   command", "the project's conventions doc") replaces "burst"/"CLAUDE.md"/"trifecta".
4. Keep everything else verbatim: scout→read→plan→diverse-panel(REWORK ≥2)→coder-in-worktree
   →adversarial-verify, the fail-loud no-spec guard, plan-only-unless-build.

## Hard rules that become code (not prose)

| Old prose rule | New form |
|---|---|
| Run-log fail-closed before item 1 | Driver init step; refuses to dispatch item 1 without it |
| Stop on first failure (default) | Driver routing on `{status}`/`{ok}` |
| Re-read the order list each iteration | Gone — list lives in the driver, can't drift |
| Parent-checkout containment (rules 11/12) | Gone — no long-lived parent session exists |
| Per-item bookkeeping | Driver step 4 (merge + complete_cmd + ff + assert clean) |
| Cold-verify discipline, no destructive ops, secrets hygiene | Move into `ship-one` skill prose |
| Follow-up spec number allocated last | Driver end step, re-scan index |
| Snapshot/respect operator's dirty state | Driver init snapshot; stop+ask if it changes |

## Per-project config

`.claude/multi-ship.json` (committed per repo; `multi-ship init` scaffolds it):

```json
{
  "build_workflow": "mixed-model-burst",
  "spec_glob": "docs/specs/*.md",
  "verify": "gh pr checks $PR --watch",
  "notify": "<your notify command, e.g. a Telegram/Slack webhook script>",
  "pr_body_convention": "Closes #{issue}",
  "complete_cmd": "/complete-spec {slug}",
  "test_cmd": "<your project's test command, e.g. ruff check . && mypy . && pytest -x>",
  "build_invariants": "<one paragraph of your project's must-honor invariants, e.g. test-first, typed models, no hardcoded secrets>",
  "smoke_instructions": "<how to exercise a new code path end-to-end, e.g. load your app config and call the new function with real inputs>",
  "roles": { "scout": "haiku", "reader": "haiku", "planner": "opus",
             "judges": ["opus","sonnet","haiku"],
             "coder": {"hard":"opus","routine":"sonnet"}, "verifier": "opus" }
}
```

The template ships with neutral placeholders; a worked example for a real project appears in the README.

## Error handling

- **No silent failures.** Off-script → notify + stop (never best-effort continue).
- **Judge fail-open**, build/CI fail-closed.
- **Crash resumability:** run-log written after every item; `--resume` skips shipped.
- **Operator dirty state:** snapshot at start; if it changes unexpectedly, stop and ask
  — never revert/rename/delete.

## Testing

- **Unit (pytest, `tests/`):** config parse + validation, run-log state machine,
  resume-skips-shipped, stop-on-failure routing, dream-gate predicate. Pure logic, no
  Claude calls. CI via GitHub Actions on the public repo.
- **Live smoke:** `multi-ship init` + one real trivial spec on a real repo end-to-end
  before trusting a backlog. The skills are prompt contracts — validated by the live dry-run.

## Open-source deliverables

- **README.md:** what/why, the MiMo relationship + "patterns portable, impl runs on
  Claude Code" honesty, install, `multi-ship init`, config reference, the role→model map,
  a worked example for a real project, limitations (Claude-Code-bound; cross-vendor is future).
- **LICENSE:** MIT.
- **install.sh** + `multi-ship init`.
- **.gitignore** (`.multi-ship/`, `__pycache__`, etc.).
- CI workflow running the pytest suite.

## Open follow-ups (out of v1 scope)

- True cross-vendor orchestration (GPT/Gemini/local) — the abstraction seam is built in
  v1 at `resolveModel`, but the provider layer that shells non-Claude CLIs is deferred.
- Steal ④ (relational task tree `Tn.m`) — flat order-list + run-log suffices at N≈8–20.
- Periodic `dream-run` cadence (MiMo's weekly cross-run consolidation).
- Claude Code plugin packaging for marketplace install.
