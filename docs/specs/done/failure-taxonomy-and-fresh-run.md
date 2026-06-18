---
Issue: 14
Difficulty: hard
title: "Failure taxonomy + parent_notes surfacing + auto-archive a completed run"
---

# Spec: make run-stops legible and handle a finished backlog cleanly

## Goal

Three related driver/CLI improvements distilled from a real run that hit **four
plan-gate REWORKs** before shipping. The pattern exposed that the run-log can only
say `status: "failed"` — it cannot express *why* a run stopped, even though the
`ship-one` skill's own prose distinguishes a *foldable* plan-gate REWORK (correct
the spec, `--resume`) from a *blocked* judge-rejection (investigate). And a finished
run blocks the next, different backlog behind a manual `mv`.

All three are small, additive, **stdlib-only**, fail-soft, and TDD'd against the
existing test modules. No new config keys, no new dependencies (`pyproject.toml`
dependencies stay `[]`).

The three changes:

1. **`failure_kind`** — a single classification field on the item / run-log so a
   stop is legible at a glance.
2. **Surface `parent_notes`** — the REWORK reason + foldable corrections already
   written to `item-<id>.json` are shown in the end-of-run notification and the
   `status` table instead of requiring a `cat` of the JSON.
3. **Auto-archive a completed run** — when a *different* backlog is launched over a
   *finished* run, archive the prior state into `.multi-ship/archive/<ts>/` (which
   stays gitignored) and start fresh; plus an explicit `--fresh` flag.

---

## Design

### Part 1 — `failure_kind`

A closed vocabulary, recorded on the run-log item (and on `item-<id>.json` for the
stops `ship-one` owns). Default `"unknown"` so an unclassified stop is visibly a
contract gap rather than silently mislabeled.

| `failure_kind` | Meaning | Foldable? | Written by |
|---|---|---|---|
| `plan_gate_rework` | Build panel returned REWORK, or the build planned the wrong spec — no code/PR produced | **Yes** — verify the panel's claims, correct the spec, `--resume` | `ship-one` (§3) |
| `config_error` | `.claude/multi-ship.json` missing or malformed | Yes — fix config, `--resume` | `ship-one` (§1) |
| `ci_failed` | Build shipped a PR but CI could not reach cold-green / an unresolved blocker reviewer | Maybe — fix on branch, `--resume` | `ship-one` (§4) |
| `needs_redesign` | A `--fix` retry could not address the judge's rejection without a larger redesign | No — operator redesign | `ship-one` (§5) |
| `judge_rejected` | The cold judge rejected twice (initial + one `--fix` retry exhausted) | No — investigate | `driver` (judge loop) |
| `error` | Any other unexpected exception in `_process_item`, including a genuine un-mergeable PR (`_merge_pr` raised) | No — read `error` string | `driver` (broad except) |

`unknown` is the render-time fallback only; no code path writes it deliberately.

**Schema addition (`skills/ship-one/SKILL.md` §6).** Add `failure_kind` to the
documented `item-<id>.json` shape, and instruct `ship-one` to set the matching kind
**at every point where it writes `status: "failed"`** (the four `ship-one`-owned
rows above — §1 config, §3 plan-gate/wrong-spec, §4 CI, §5 needs-redesign). On a
successful `awaiting_judge` write, `failure_kind` is omitted.

```json
{
  "status": "failed",
  "failure_kind": "plan_gate_rework",
  "pr": "",
  "parent_notes": "<verified blockers + recommended fold>",
  "...": "..."
}
```

**Driver propagation (`src/multi_ship/driver.py`).** Three sites:

1. `_process_item`, the `item.get("status") == "failed"` branch (currently copies
   only `pr`): also copy `failure_kind` and `parent_notes` from the item file onto
   the run-log item; if the item file omitted `failure_kind`, default it to
   `"unknown"`.
2. `_process_item`, the judge-loop-exhausted stop (after the `for attempt in
   range(2)` loop): set `failure_kind="judge_rejected"` alongside the existing
   `judge_reason`, and also carry `parent_notes` from the last re-read `item`
   (the `--fix` attempt writes its `parent_notes`).
3. `run_loop`, the broad `except` that fails an item on an unexpected error: set
   `failure_kind="error"` alongside the existing `error=str(e)[:300]`.

`runlog.set_item_status` already persists arbitrary `**fields` via `it.update(...)`,
so **no `runlog.py` change is required** — `failure_kind` rides through as a field.

### Part 2 — surface `parent_notes`

The reason + foldable corrections are the single most valuable artifact on a stop
and are currently invisible (only `followups` are surfaced). Show them in both
operator-facing render sites. Truncate defensively; newlines → spaces.

**End-of-run notification (`src/multi_ship/endrun.py::format_notification`).**
Extend the signature (backward-compatible, new params default `None`):

```python
def format_notification(shipped, stopped_at, followups, run_log_path,
                        followups_path, stop_kind=None, stop_notes=None) -> str:
```

When `stopped_at` is set, render the kind inline and the notes on a `why:` line:

```
multi-ship: ⚠️ stopped at failure-taxonomy-and-fresh-run.md  [plan_gate_rework]
why: panel REWORK (2/3 lenses) — the G3 "symmetric pair" premise is false; …
shipped (0): none
stopped at: failure-taxonomy-and-fresh-run.md
run-log: /…/run-log.json
```

- The `[kind]` token is appended to the status line only when `stop_kind` is truthy.
- The `why:` line is emitted only when `stop_notes` is truthy, truncated to ~300
  chars (`stop_notes[:300]`, newlines collapsed to spaces, trailing `…` if cut).
- All existing lines and the "✅ all shipped" path are unchanged.

**Caller (`driver.py::_end_of_run`).** It already reads `log`. When `stopped_at` is
set, find that item (`next((it for it in log["items"] if it["id"] == stopped_at),
None)`) and pass its `failure_kind` and `parent_notes` as `stop_kind` / `stop_notes`.

**Status table (`src/multi_ship/cli.py::format_status`).** The note column today is
`judge_reason or error`. Make it `[failure_kind] <detail>` where `<detail>` falls
back through `judge_reason → parent_notes → error`:

```python
kind = it.get("failure_kind")
detail = (it.get("judge_reason") or it.get("parent_notes")
          or it.get("error") or "").replace("\n", " ").strip()
note = f"[{kind}] {detail}".strip() if kind else detail
# then the existing 60-char truncation
```

### Part 3 — auto-archive a completed run + `--fresh`

**The friction:** launching a *new* backlog over a *finished* run is refused
(`a previous run-log exists … pass --resume or remove`), forcing a manual `mv` — and
a hand-made sibling archive (e.g. `.multi-ship.done.20260618/`) is **not** covered
by the `.multi-ship/` gitignore line, so it shows up as untracked clutter.

**Detection (`src/multi_ship/cli.py::main`, the run-log-exists guard).** Replace the
binary refuse with:

```python
state_dir = repo / ".multi-ship"
run_log_path = state_dir / "run-log.json"
if run_log_path.exists() and not args.resume:
    log = json.loads(run_log_path.read_text())
    all_terminal = bool(log.get("items")) and all(
        it.get("status") in ("shipped", "failed") for it in log["items"])
    different_backlog = list(specs) != list(log.get("order", []))
    if args.fresh or (all_terminal and different_backlog):
        dest = _archive_completed_run(state_dir)
        print(f"archived prior run → {dest}")
        # run-log.json has been moved; fall through to a fresh run
    else:
        print("a previous run-log exists at .multi-ship/run-log.json — pass "
              "--resume to continue it, --fresh to archive it and start over, "
              "or remove .multi-ship/", file=sys.stderr)
        return 2
```

Behavior matrix:

| Prior run | New spec set | `--fresh`? | Result |
|---|---|---|---|
| all terminal | different | no | **auto-archive + fresh** |
| all terminal | same | no | refuse (suggest `--resume` / `--fresh`) |
| not terminal (crashed) | any | no | refuse (must `--resume`) |
| any | any | **yes** | archive + fresh |
| any | any | `--resume` | resume (unchanged; never archives) |

**Archive helper (`src/multi_ship/cli.py`).** A testable seam — the timestamp is
injectable so unit tests are deterministic:

```python
def _archive_completed_run(state_dir: Path, ts: str | None = None) -> Path:
    """Move all top-level run state into .multi-ship/archive/<ts>/ and return it.
    The archive lives UNDER state_dir, so the existing `.multi-ship/` gitignore
    line covers it. Idempotent across runs (each call gets its own <ts> subdir)."""
    from datetime import datetime
    ts = ts or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive_root = state_dir / "archive"
    dest = archive_root / ts
    dest.mkdir(parents=True, exist_ok=True)
    for entry in state_dir.iterdir():
        if entry == archive_root:
            continue  # never move the archive dir into itself
        shutil.move(str(entry), str(dest / entry.name))
    return dest
```

After archiving, `run-log.json` no longer exists at the top level, so
`driver.run_loop` inits a fresh one — no further special-casing.

**CLI flag.** Add `--fresh` (`action="store_true"`) to the main argparse parser.
`--fresh` and `--resume` are mutually exclusive in intent; if both are passed,
`--resume` wins (resume never archives) — document this, no hard error needed.

---

## Resolved decisions (operator — treat as settled)

1. **`failure_kind` is a closed set with an `"unknown"` render fallback.** Code never
   writes `"unknown"`; it only appears if `ship-one` failed to classify a stop,
   which the DoD forbids — so seeing it in the wild is a signal, not normal.
2. **Merge failures fold under `error`, not a separate `merge_failed` kind.** The
   `_merge_pr` raise is caught by the existing broad `except` in `run_loop`; the
   `error` string already carries the `gh pr merge` stderr. Avoid fragile
   exception-type classification inside the catch.
3. **Auto-archive triggers ONLY on `all_terminal AND different_backlog`** (or explicit
   `--fresh`). A re-run of the *same* finished backlog still refuses and points at
   `--resume` / `--fresh`, because "re-run the same thing" is ambiguous enough to
   warrant an explicit operator choice.
4. **The archive lives under `.multi-ship/archive/<ts>/`** — inside the already-ignored
   state dir — so no `.gitignore` change is needed and no untracked clutter appears.
5. **The timestamp is an injectable parameter** (`ts=None`) so tests pin it; production
   uses microsecond precision to avoid same-second collisions.
6. **`runlog.py` is not modified.** `failure_kind` flows through the existing
   `**fields` mechanism; adding it to the transition table or schema would be
   over-engineering.

## Backward compatibility

- `format_notification`'s new params default `None` → every existing caller and test
  keeps working; the "all shipped" path is byte-identical.
- A run-log without `failure_kind` on its items renders exactly as today (the
  `[kind]` prefix and `why:` line are conditional).
- `--resume` semantics are untouched and never archive.
- No config-schema change; existing `.claude/multi-ship.json` files load unchanged.

## Out of scope

- Auto-folding or auto-retrying a plan-gate REWORK (folding requires verifying the
  planner's claims against the live tree — human judgment, deliberately manual).
- Making `preflight` detect design ambiguity (the plan gate is that check).
- `status --json` (tracked separately in issue #4).
- Any change to `ship-one`'s build/merge flow beyond writing `failure_kind`.

## Definition of Done

- [ ] `skills/ship-one/SKILL.md` §6 documents `failure_kind` in the `item-<id>.json` shape, and §1/§3/§4/§5 instruct `ship-one` to set the matching kind (`config_error` / `plan_gate_rework` / `ci_failed` / `needs_redesign`) at each `status: "failed"` write.
- [ ] `driver._process_item` propagates `failure_kind` + `parent_notes` from the item file onto the run-log item on the `ship-one`-failed branch (defaulting `failure_kind` to `"unknown"` if absent).
- [ ] `driver._process_item` sets `failure_kind="judge_rejected"` + carries `parent_notes` on the judge-loop-exhausted stop; `driver.run_loop`'s broad `except` sets `failure_kind="error"`.
- [ ] `endrun.format_notification` gains `stop_kind` / `stop_notes` (default `None`), renders `[kind]` inline on the stop line and a truncated `why:` line; the all-shipped path and every existing call site are unchanged.
- [ ] `driver._end_of_run` passes the stopped item's `failure_kind` / `parent_notes` into `format_notification`.
- [ ] `cli.format_status` shows `[failure_kind] <detail>` with the `judge_reason → parent_notes → error` fallback, keeping the 60-char truncation.
- [ ] `cli._archive_completed_run(state_dir, ts=None)` moves all top-level state (except the `archive/` dir) into `.multi-ship/archive/<ts>/` and returns the path; the timestamp is injectable.
- [ ] `cli.main` auto-archives + starts fresh when `all_terminal AND different_backlog` (or `--fresh`); refuses with the improved 3-option message otherwise; `--fresh` is a parser flag; `--resume` still never archives.
- [ ] The archive path is under `.multi-ship/` (covered by the existing gitignore line) — asserted by a test.
- [ ] `pyproject.toml` dependencies remain `[]` (stdlib-only); `PYTHONPATH=src python -m pytest -x` passes.
- [ ] `CHANGELOG.md` "Unreleased" entry; `README.md` documents `--fresh` and the auto-archive behavior.
- [ ] PR body includes `Closes #14`.

## Test plan (TDD order — write each test red first, against the named module)

1. **`tests/test_endrun.py`** — `format_notification` with `stop_kind="plan_gate_rework"`,
   `stop_notes="panel REWORK …"` renders `[plan_gate_rework]` and a `why:` line;
   a long `stop_notes` is truncated to ~300 chars; omitting both is byte-identical
   to today (extend `test_format_notification_stopped_with_followups` or add a sibling).
2. **`tests/test_status.py`** — extend `_log()` with a `failed` item carrying
   `failure_kind="plan_gate_rework"` + `parent_notes="…"`; assert `format_status`
   shows `[plan_gate_rework]` and the notes; assert an item *without* `failure_kind`
   still renders its bare note (back-compat).
3. **`tests/test_driver_loop.py`** —
   a. extend `test_judge_reject_twice_stops` to assert the run-log item ends with
      `failure_kind == "judge_rejected"`;
   b. new: a `ship-one` REWORK (fake writes `{status:"failed",
      failure_kind:"plan_gate_rework", parent_notes:"…"}`) propagates both onto the
      run-log item;
   c. new: ship-one writes `status:"failed"` with **no** `failure_kind` → run-log
      item gets `failure_kind == "unknown"`;
   d. new: an unexpected error (reuse the `boom` `_merge_pr` pattern) yields
      `failure_kind == "error"` on the run-log item.
4. **`tests/test_fresh_run.py`** (new module) —
   a. `_archive_completed_run(state_dir, ts="fixed")` moves `run-log.json` +
      `item-*.json` into `.multi-ship/archive/fixed/`, leaves `archive/` itself in
      place, and the moved files are gone from the top level;
   b. the returned/dest path is under `state_dir` (gitignore-covered) — assert
      `str(dest).startswith(str(state_dir))` and `"archive" in dest.parts`;
   c. `cli.main` over a completed run-log (`all_terminal`) with a **different** spec
      list auto-archives and proceeds to a fresh run (monkeypatch `driver.run_loop`
      to a stub that records it was called and asserts `run-log.json` was absent at
      call time);
   d. same completed run-log with the **same** spec list → `main` returns `2` and
      does **not** archive;
   e. a **non-terminal** run-log + no `--fresh` → returns `2`, no archive;
   f. `--fresh` over any run-log archives and proceeds.
5. Full suite green: `PYTHONPATH=src python -m pytest -x`.

## Notes

- `gh`/network are not touched by this change; all new tests are pure (tmp trees +
  monkeypatched `driver.run_loop` / fake `claude_cli.run`), so CI needs nothing new.
- Keep the render strings terse — the notification goes to Telegram/stdout where
  width is tight; the `why:` line is a pointer to the full `parent_notes` in
  `item-<id>.json`, not a replacement for reading it.
- Ephemeral smoke (per `smoke_instructions`): a throwaway `PYTHONPATH=src python -c`
  that (a) builds a tmp `.multi-ship/` with a completed run-log + an `item-*.json`,
  calls `_archive_completed_run`, and asserts the files moved under `archive/`; and
  (b) calls `format_notification(..., stop_kind="plan_gate_rework",
  stop_notes="x"*400)` and asserts `[plan_gate_rework]` and a truncated `why:` line.
  Print OK or the first failure. Never check it in.
