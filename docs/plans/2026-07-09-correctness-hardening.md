# 2026-07-09 — Correctness & hardening pass

Written for an engineer with zero context. Execute tasks **in order**; each task is
one commit. Repo root is the cwd for every command.

**Context.** multi-ship is a Python driver (`src/multi_ship/`, stdlib-only, tests in
`tests/`, run with `PYTHONPATH=src python3 -m pytest -q`) that ships a spec backlog by
spawning fresh `claude -p` sessions per item and gating merges behind a cold judge.
A correctness review found: an uncaught `subprocess.TimeoutExpired` that can crash the
whole run (skipping notification), a documented-but-unimplemented judge fail-open, stale
state-file reads on the fix/judge paths, run-log fields that persist across transitions,
non-atomic run-log writes, silently-dropped zero-match globs, `claude -p` error payloads
with exit 0 treated as success, and `multi-ship init` not installing the build workflow
that DESIGN.md says it installs.

**Non-negotiable gate.** Every task must end with the smoke harness green:

```bash
bash scripts/smoke.sh
```

Builders MUST NOT weaken, delete, or skip existing tests to get green. If a task cannot
pass the gate within its own scope, STOP and report — do not continue to the next task.

**Repo invariants that apply to every task** (from `.claude/multi-ship.json`):
stdlib-only (no new runtime deps; `pyproject.toml dependencies` stays `[]`); tests are
written failing-first where possible; config keys must not be added to
`_REQUIRED_KEYS`; fail-soft on external surfaces; match surrounding code style.

There are pre-existing **uncommitted changes** to `README.md`, `docs/PROMOTION.md`, and
`skills/ship-one/SKILL.md`. Do NOT revert, commit, or stash them. Commit only the files
each task names (`git add <paths>` explicitly; never `git add -A` / `git commit -a`).

---

## Task 1 — Work branch + smoke harness

**Files:** new `scripts/smoke.sh`.

1. Create the branch (from current `main`, keeping the dirty docs files as-is):

```bash
git checkout -b fix/correctness-hardening
```

2. Create `scripts/smoke.sh` with exactly this content:

```bash
#!/usr/bin/env bash
# Fast, dependency-free verification gate for multi-ship: the full unit suite.
# No network, no `claude`/`gh` calls — every external surface is monkeypatched.
# Every task in a plan-driven change must keep this green.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m pytest -q "$@"
```

3. `chmod +x scripts/smoke.sh`

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected output ends with: `164 passed` (time may vary).

**Commit:**

```bash
git add scripts/smoke.sh
git commit -m "chore: add dependency-free smoke harness script"
```

---

## Task 2 — `claude_cli`: convert `TimeoutExpired` to `ClaudeError` (probe stays fail-open)

**Files:** `src/multi_ship/claude_cli.py`, `tests/test_claude_cli.py`.

**Bug:** `subprocess.run(..., timeout=...)` in `_raw_run` raises
`subprocess.TimeoutExpired`, which is neither `ClaudeError` nor `QuotaExhausted`.
`probe_quota` is called in `driver.run_loop` outside any `except`, so a hung probe
crashes the entire run with a traceback and no end-of-run notification.

1. **Failing-first tests.** Append to `tests/test_claude_cli.py` (note: the file
   already imports `json`, `pytest`, and `claude_cli`; add `import subprocess` to the
   top of the file below the existing imports):

```python
# --- timeout handling --------------------------------------------------------

def test_run_timeout_raises_claude_error(monkeypatch):
    def fake_raw(cmd, cwd, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
    monkeypatch.setattr(claude_cli, "_raw_run", fake_raw)
    with pytest.raises(claude_cli.ClaudeError, match="timed out"):
        claude_cli.run("/ship-one x", repo="/repo")

def test_probe_quota_failopen_on_timeout(monkeypatch):
    """A hung probe must fail-open (True), never crash the driver."""
    def fake_raw(cmd, cwd, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
    monkeypatch.setattr(claude_cli, "_raw_run", fake_raw)
    assert claude_cli.probe_quota("/repo") == (True, None)
```

Run `bash scripts/smoke.sh` — the two new tests must FAIL with
`subprocess.TimeoutExpired` leaking out.

2. **Fix.** In `src/multi_ship/claude_cli.py`, replace the whole `run` function with:

```python
def run(prompt: str, repo: str, timeout: int = 7200) -> dict:
    cmd = build_command(prompt, repo)
    try:
        code, out, err = _raw_run(cmd, cwd=repo, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # A hung `claude -p` (slow MCP init, network stall) must surface as a
        # normal ClaudeError so callers' fail-open / per-item handling applies —
        # never as a raw TimeoutExpired that crashes the driver loop.
        raise ClaudeError(f"claude -p timed out after {timeout}s") from e
    if code != 0:
        is_quota, resets_at = detect_quota(out, err)
        if is_quota:
            suffix = f" (resets {resets_at})" if resets_at else ""
            raise QuotaExhausted(
                f"claude -p session quota exhausted{suffix}", resets_at=resets_at)
        raise ClaudeError(f"claude -p exited {code}: {err.strip()[:500]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"claude -p returned non-JSON: {out[:500]}") from e
```

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `166 passed`.

**Commit:**

```bash
git add src/multi_ship/claude_cli.py tests/test_claude_cli.py
git commit -m "fix: convert claude -p TimeoutExpired to ClaudeError so a hung probe can't crash the run"
```

---

## Task 3 — `claude_cli`: surface `is_error` JSON payloads (incl. quota) on exit 0

**Files:** `src/multi_ship/claude_cli.py`, `tests/test_claude_cli.py`.

**Bug:** `claude -p --output-format json` can exit 0 while the payload carries
`"is_error": true` (including a mid-session quota hit). `run()` returns that payload as
success; the failure then surfaces later as a misleading "stale item report" error.

1. **Failing-first tests.** Append to `tests/test_claude_cli.py`:

```python
# --- is_error payloads on exit 0 ---------------------------------------------

def test_run_exit0_is_error_raises_claude_error(monkeypatch):
    fake = json.dumps({"is_error": True, "result": "something broke mid-session"})
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (0, fake, ""))
    with pytest.raises(claude_cli.ClaudeError, match="something broke"):
        claude_cli.run("/x", repo="/repo")

def test_run_exit0_is_error_quota_raises_quota_exhausted(monkeypatch):
    fake = json.dumps({"is_error": True,
                       "result": "You've hit your session limit · resets 5:20pm (America/Sao_Paulo)"})
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (0, fake, ""))
    with pytest.raises(claude_cli.QuotaExhausted) as exc:
        claude_cli.run("/x", repo="/repo")
    assert exc.value.resets_at == "5:20pm (America/Sao_Paulo)"

def test_run_exit0_without_is_error_still_returns_payload(monkeypatch):
    fake = json.dumps({"is_error": False, "result": "done"})
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (0, fake, ""))
    assert claude_cli.run("/x", repo="/repo")["result"] == "done"
```

Run `bash scripts/smoke.sh` — the first two new tests must FAIL (no exception raised).

2. **Fix.** In `run()` (as rewritten in Task 2), replace the final `try/except`
   JSON block with:

```python
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"claude -p returned non-JSON: {out[:500]}") from e
    # `claude -p --output-format json` can exit 0 while the payload itself says
    # the session errored (is_error) — including a mid-session quota hit. Treat
    # that as the failure it is instead of returning it as success.
    if isinstance(data, dict) and data.get("is_error"):
        result_text = str(data.get("result", ""))
        is_quota, resets_at = detect_quota(result_text, err)
        if is_quota:
            suffix = f" (resets {resets_at})" if resets_at else ""
            raise QuotaExhausted(
                f"claude -p session quota exhausted{suffix}", resets_at=resets_at)
        raise ClaudeError(f"claude -p reported an error result: {result_text[:500]}")
    return data
```

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `169 passed`.

**Commit:**

```bash
git add src/multi_ship/claude_cli.py tests/test_claude_cli.py
git commit -m "fix: treat exit-0 is_error claude -p payloads as failures (incl. mid-session quota)"
```

---

## Task 4 — driver: implement judge fail-open + fresh-verdict guard

**Files:** `src/multi_ship/driver.py`, `tests/test_driver_loop.py`.

**Bug:** README documents "judge error → fail-open: log, proceed", but a judge
`claude -p` failure or a missing/stale `verdict-<id>.json` currently raises, marking
the item `failed` and stopping the run. Also, a stale verdict from a prior round can be
read as if fresh (worst case: a stale `ok: true` merges an unjudged PR on `--resume`).

1. **Failing-first tests.** Append to `tests/test_driver_loop.py`:

```python
# ---------------------------------------------------------------------------
# Judge fail-open: a judge crash or a judge that writes no fresh verdict must
# NOT fail the item — README contract: "judge error → fail-open: log, proceed".
# Quota during the judge still pauses (it is not a judge failure).
# ---------------------------------------------------------------------------

def test_judge_crash_fails_open_and_merges(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            raise claude_cli.ClaudeError("judge session crashed")
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]
    assert merges == ["http://pr/1"]

def test_judge_writes_no_fresh_verdict_fails_open(tmp_path, monkeypatch):
    """Judge session returns fine but never (re)writes verdict-<id>.json: a STALE
    verdict from a prior round must not be trusted — fail-open instead."""
    state = tmp_path / ".multi-ship"; state.mkdir(parents=True)
    # Stale verdict from a previous round, saying REJECT. It must be ignored.
    (state / "verdict-a.md.json").write_text(json.dumps({"ok": False, "reason": "old"}))
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            return {"result": "judged but wrote nothing"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]  # fail-open, not judge_rejected via stale file
    assert merges == ["http://pr/1"]

def test_quota_during_judge_still_pauses(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            raise claude_cli.QuotaExhausted("quota", resets_at="5pm")
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(claude_cli, "probe_quota", lambda repo: (True, None))
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert result["paused"]["item"] == "a.md"
    log = json.loads((state / "run-log.json").read_text())
    assert log["items"][0]["status"] == "pending"
```

Run `bash scripts/smoke.sh` — the first two new tests must FAIL (item marked failed /
stale verdict honored).

2. **Fix.** In `src/multi_ship/driver.py`:

   a. Add this helper directly ABOVE `def _process_item(...)`:

```python
def _judge_verdict(sid: str, iid: str, pr: str, repo: str, state_dir: Path) -> dict:
    """Run the cold judge and return a FRESH verdict dict.

    Fail-open per the documented contract (README: a flaky judge can't trap a
    good run): a judge crash, an unreadable verdict, or a judge session that
    returns without rewriting verdict-<id>.json all yield {ok: true} with a
    fail-open reason. Freshness is checked by mtime so a stale verdict from a
    prior round is never trusted. Quota exhaustion is NOT a judge failure — it
    propagates so the driver pauses cleanly."""
    vpath = state_dir / f"verdict-{iid}.json"
    before = vpath.stat().st_mtime_ns if vpath.exists() else 0
    try:
        claude_cli.run(f"/judge-shipped {sid} {pr}", repo=repo)
    except claude_cli.QuotaExhausted:
        raise
    except claude_cli.ClaudeError as e:
        sys.stderr.write(f"multi-ship: judge run for {iid} failed — fail-open: {e}\n")
        return {"ok": True, "reason": f"judge could not run — fail-open: {str(e)[:200]}"}
    if not vpath.exists() or vpath.stat().st_mtime_ns <= before:
        sys.stderr.write(
            f"multi-ship: judge wrote no fresh verdict for {iid} — fail-open\n")
        return {"ok": True, "reason": "judge produced no fresh verdict — fail-open"}
    try:
        return _read_json(vpath)
    except (json.JSONDecodeError, OSError) as e:
        sys.stderr.write(f"multi-ship: unreadable verdict for {iid} — fail-open: {e}\n")
        return {"ok": True, "reason": f"unreadable verdict — fail-open: {str(e)[:200]}"}
```

   b. In `_process_item`, replace the two lines

```python
    for attempt in range(2):
        claude_cli.run(f"/judge-shipped {sid} {item.get('pr','')}", repo=repo)
        verdict = _read_json(state_dir / f"verdict-{iid}.json")
```

with

```python
    for attempt in range(2):
        verdict = _judge_verdict(sid, iid, item.get("pr", ""), repo, state_dir)
```

   c. Also in `_process_item`, upgrade the existing build-freshness stamp to
      nanosecond precision (two lines):
      `before = item_path.stat().st_mtime if item_path.exists() else 0.0` →
      `before = item_path.stat().st_mtime_ns if item_path.exists() else 0`
      and `item_path.stat().st_mtime <= before` → `item_path.stat().st_mtime_ns <= before`.

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `172 passed`.

**Commit:**

```bash
git add src/multi_ship/driver.py tests/test_driver_loop.py
git commit -m "fix: implement documented judge fail-open + fresh-verdict guard (stale verdicts never trusted)"
```

---

## Task 5 — driver: fresh-report + failed-status handling on the `--fix` path

**Files:** `src/multi_ship/driver.py`, `tests/test_driver_loop.py`.

**Bug:** after the `--fix` re-dispatch, `item-<id>.json` is re-read with no freshness
check and no `status: failed` check — a crashed fix re-judges the stale pre-fix report,
and an honest `needs_redesign` failure from the fix is sent to the judge anyway.

1. **Failing-first tests.** Append to `tests/test_driver_loop.py`:

```python
# ---------------------------------------------------------------------------
# --fix path: same freshness + failed-status discipline as the first build.
# ---------------------------------------------------------------------------

def test_fix_reporting_failed_stops_with_builder_kind(tmp_path, monkeypatch):
    """ship-one --fix writes status=failed (needs_redesign): the item must fail
    with the BUILDER's kind, not proceed to a second judge round."""
    state = tmp_path / ".multi-ship"
    judges = {"n": 0}
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one a.md --fix"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "failed", "failure_kind": "needs_redesign",
                 "parent_notes": "cannot fix without redesign"}))
            return {"result": "fix failed"}
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            judges["n"] += 1
            (state / "verdict-a.md.json").write_text(
                json.dumps({"ok": False, "reason": "missing test"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert judges["n"] == 1, "a failed fix must not be re-judged"
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["status"] == "failed"
    assert a["failure_kind"] == "needs_redesign"

def test_fix_writing_no_fresh_report_fails_item(tmp_path, monkeypatch):
    """ship-one --fix returns without rewriting item-<id>.json: honest error,
    not a re-judge of the stale pre-fix report."""
    state = tmp_path / ".multi-ship"
    judges = {"n": 0}
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one a.md --fix"):
            return {"result": "crashed without writing"}
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            judges["n"] += 1
            (state / "verdict-a.md.json").write_text(
                json.dumps({"ok": False, "reason": "missing test"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert judges["n"] == 1
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["status"] == "failed"
    assert a["failure_kind"] == "error"
```

Run `bash scripts/smoke.sh` — both new tests must FAIL (currently `judges["n"] == 2`).

2. **Fix.** In `_process_item`, replace the `if attempt == 0:` block:

```python
        if attempt == 0:
            # re-dispatch ship-one to FIX using the judge's reason, then re-judge.
            # Same freshness + failed-status discipline as the first build: a fix
            # that crashed without rewriting the report must not be re-judged
            # from stale data, and an honest failed fix keeps the builder's kind.
            runlog.set_item_status(run_log, sid, "needs_fix")
            fix_before = item_path.stat().st_mtime_ns if item_path.exists() else 0
            claude_cli.run(_fix_prompt(sid, verdict.get("reason", "")), repo=repo)
            if not item_path.exists() or item_path.stat().st_mtime_ns <= fix_before:
                raise claude_cli.ClaudeError(
                    f"ship-one --fix produced no fresh item report for {iid} "
                    "(stale/unchanged item-<id>.json — likely quota or crash mid-fix)")
            item = _read_json(item_path)
            if item.get("status") == "failed":
                fields = {k: item.get(k) for k in ("pr", "parent_notes") if item.get(k)}
                fields["failure_kind"] = item.get("failure_kind") or "unknown"
                runlog.set_item_status(run_log, sid, "failed", **fields)
                return False
            runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"))
```

(Note: `needs_fix → failed` is a legal transition in `runlog._TRANSITIONS`.)

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `174 passed`.

**Commit:**

```bash
git add src/multi_ship/driver.py tests/test_driver_loop.py
git commit -m "fix: apply fresh-report + failed-status checks to the ship-one --fix path"
```

---

## Task 6 — runlog: clear transient fields on transition + atomic writes

**Files:** `src/multi_ship/runlog.py`, `tests/test_runlog.py`.

**Bugs:** (a) `force_pending`'s docstring says `paused_reason`/`resets_at` are cleared
on the next successful transition, but `set_item_status` only `update()`s — stale
`judge_reason`/`parent_notes`/`error` also survive into `shipped` and are then shown by
`multi-ship status`. (b) `_write` is non-atomic; a crash mid-write corrupts the run-log
that resume depends on.

1. **Failing-first tests.** Append to `tests/test_runlog.py`:

```python
# --- transient fields are cleared on every transition ------------------------

def test_transition_clears_stale_transient_fields(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    set_item_status(p, "a.md", "needs_fix", judge_reason="missing test")
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    set_item_status(p, "a.md", "shipped")
    it = read_run_log(p)["items"][0]
    assert it["status"] == "shipped"
    assert "judge_reason" not in it, "stale rejection text must not survive a ship"

def test_force_pending_fields_cleared_on_next_transition(tmp_path):
    from multi_ship.runlog import force_pending
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    force_pending(p, "a.md", paused_reason="quota_exhausted", resets_at="5pm")
    it = read_run_log(p)["items"][0]
    assert it["paused_reason"] == "quota_exhausted" and it["resets_at"] == "5pm"
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    it = read_run_log(p)["items"][0]
    assert "paused_reason" not in it and "resets_at" not in it

def test_write_leaves_no_tmp_files(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge")
    leftovers = [f for f in p.parent.iterdir() if f.name != "run-log.json"]
    assert leftovers == []
```

Run `bash scripts/smoke.sh` — the first two new tests must FAIL.

2. **Fix.** In `src/multi_ship/runlog.py`:

   a. Change the imports at the top to:

```python
"""Run-log: durable per-run state with an enforced item-status state machine."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
```

   b. Add below `TERMINAL = {"shipped", "failed"}`:

```python
# Per-round annotations that describe ONE attempt/pause, not the item itself.
# Cleared on every status transition so a stale judge_reason / paused_reason /
# error never survives into (and gets displayed for) a later status. Callers
# re-supply the relevant ones via **fields on each transition.
_TRANSIENT_FIELDS = ("paused_reason", "resets_at", "judge_reason",
                     "error", "failure_kind", "parent_notes")
```

   c. Replace `_write` with an atomic version:

```python
def _write(path: Path, log: dict) -> None:
    """Atomic write (tmp file + os.replace) — a crash mid-write must never
    corrupt the run-log that --resume depends on."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(log, indent=2))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

   d. In `set_item_status`, after `it["status"] = new_status` and before
      `it.update(fields)`, insert:

```python
    for k in _TRANSIENT_FIELDS:
        it.pop(k, None)
```

   e. Update `force_pending`'s docstring final sentence to stay truthful (it now IS
      true) — no code change needed there.

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `177 passed`. (If `test_end_of_run_notification_includes_failure_kind_token`
or status tests fail, you broke field re-supply — fields passed via `**fields` must
still land. Do not "fix" by weakening tests.)

**Commit:**

```bash
git add src/multi_ship/runlog.py tests/test_runlog.py
git commit -m "fix: clear stale per-round run-log fields on transition; make run-log writes atomic"
```

---

## Task 7 — resolve: a zero-match glob is an error, not a silent no-op

**Files:** `src/multi_ship/resolve.py`, `tests/test_resolve.py`.

**Bug:** a glob token that matches nothing extends results with `[]` silently — a
typo'd glob among several tokens silently drops those specs, violating the module
contract ("raises ResolveError on any unresolvable reference before starting a run").

1. **Failing-first test.** Append to `tests/test_resolve.py` (module level, matching
   the file's existing style — it defines `_cfg()` at module level):

```python
def test_glob_with_zero_matches_raises(tmp_path):
    from multi_ship.resolve import resolve_specs, ResolveError
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "P14.md").write_text("# P14")
    with pytest.raises(ResolveError, match="matched no files"):
        resolve_specs(tokens=["docs/spces/P1*.md"], issue_numbers=[],
                      cfg=_cfg(), repo=tmp_path)
```

(If `pytest` is not already imported at the top of `tests/test_resolve.py`, add
`import pytest`.)

Run `bash scripts/smoke.sh` — the new test must FAIL (no error raised).

2. **Fix.** In `_resolve_token`, replace the GLOB branch body's tail:

```python
        # Python 3.9-safe: Path(repo).glob(token) + .relative_to(repo)
        matches = sorted(
            str(p.relative_to(repo))
            for p in Path(repo).glob(token)
        )
        if not matches:
            raise ResolveError(
                f"glob '{token}' matched no files in repo '{repo}'"
            )
        results.extend(matches)
        return
```

(The no-arg `spec_glob` fallback in `cli._resolve_specs` is intentionally NOT changed —
an empty backlog there already exits with "no specs to ship".)

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `178 passed`.

**Commit:**

```bash
git add src/multi_ship/resolve.py tests/test_resolve.py
git commit -m "fix: raise ResolveError on a zero-match glob token instead of silently dropping specs"
```

---

## Task 8 — cli: `multi-ship init` installs the build workflow

**Files:** `src/multi_ship/cli.py`, `tests/test_cli_init.py`.

**Bug:** DESIGN.md says `init` "drops/symlinks the generic workflow into
`<repo>/.claude/workflows/`" and the README config table requires `build_workflow` to
be present there — but `cmd_init` only copies the JSON template. A fresh install can
never build.

1. **Failing-first test.** Append to `tests/test_cli_init.py`:

```python
def test_init_installs_build_workflow(tmp_path):
    from multi_ship.cli import cmd_init, bundled_dir
    cmd_init(str(tmp_path), template_path=bundled_dir("templates") / "multi-ship.json")
    wf = tmp_path / ".claude" / "workflows" / "mixed-model-burst.js"
    assert wf.exists(), "init must install the build workflow the config names"
    assert "mixed-model-burst" in wf.read_text()

def test_init_does_not_clobber_existing_workflow(tmp_path):
    from multi_ship.cli import cmd_init, bundled_dir
    wf = tmp_path / ".claude" / "workflows" / "mixed-model-burst.js"
    wf.parent.mkdir(parents=True)
    wf.write_text("// locally customized")
    cmd_init(str(tmp_path), template_path=bundled_dir("templates") / "multi-ship.json")
    assert wf.read_text() == "// locally customized"
```

Run `bash scripts/smoke.sh` — the first new test must FAIL.

2. **Fix.** Replace `cmd_init` in `src/multi_ship/cli.py` with:

```python
def cmd_init(repo: str, template_path: Path) -> None:
    repo = Path(repo)
    claude_dir = repo / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    dest = claude_dir / "multi-ship.json"
    if not dest.exists():
        shutil.copy(template_path, dest)
    # The config's build_workflow must resolve from <repo>/.claude/workflows/
    # (see DESIGN.md + README config table), so init installs the bundled
    # workflow(s) there. Idempotent: never clobbers a locally customized copy.
    wf_src = bundled_dir("workflows")
    if wf_src.is_dir():
        wf_dst = claude_dir / "workflows"
        wf_dst.mkdir(parents=True, exist_ok=True)
        for wf in sorted(wf_src.glob("*.js")):
            target = wf_dst / wf.name
            if not target.exists():
                shutil.copy(wf, target)
    gi = repo / ".gitignore"
    line = ".multi-ship/"
    existing = gi.read_text() if gi.exists() else ""
    if line not in existing:
        gi.write_text(existing + ("\n" if existing and not existing.endswith("\n") else "") + line + "\n")
```

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `180 passed`.

**Commit:**

```bash
git add src/multi_ship/cli.py tests/test_cli_init.py
git commit -m "fix: multi-ship init installs the bundled build workflow into .claude/workflows/"
```

---

## Task 9 — CLI/driver robustness: `--repo` without value, corrupt run-log message, missing `pr`

**Files:** `src/multi_ship/cli.py`, `src/multi_ship/driver.py`,
`tests/test_cli_init.py`, `tests/test_driver_loop.py`.

Three small hardening fixes:

1. **Failing-first tests.**

   Append to `tests/test_cli_init.py`:

```python
def test_status_repo_flag_without_value_errors_cleanly(capsys):
    from multi_ship import cli
    rc = cli.main(["status", "--repo"])
    assert rc == 1
    assert "--repo requires a value" in capsys.readouterr().err

def test_corrupt_run_log_message_does_not_suggest_resume(tmp_path, monkeypatch, capsys):
    import shutil as _sh
    from multi_ship import cli
    (tmp_path / ".claude").mkdir(parents=True)
    _sh.copy(cli.bundled_dir("templates") / "multi-ship.json",
             tmp_path / ".claude" / "multi-ship.json")
    spec_dir = tmp_path / "docs" / "specs"; spec_dir.mkdir(parents=True)
    (spec_dir / "a.md").write_text("# a")
    state = tmp_path / ".multi-ship"; state.mkdir()
    (state / "run-log.json").write_text("{not json")
    rc = cli.main(["docs/specs/a.md", "--repo", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "corrupt" in err
    assert "--resume" not in err, "resume would crash on a corrupt log — don't suggest it"
```

   Append to `tests/test_driver_loop.py`:

```python
def test_item_report_without_pr_fails_with_clear_error(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        if prompt.startswith("/ship-one"):
            (state / "item-a.md.json").write_text(json.dumps(
                {"status": "awaiting_judge", "branch": "spec/a"}))  # no "pr"
            return {"result": "built"}
        raise AssertionError(f"no judge call expected without a pr: {prompt}")
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr",
                        lambda pr, repo: (_ for _ in ()).throw(AssertionError("no merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                    stop_on_failure=True, state_dir=state)
    log = json.loads((state / "run-log.json").read_text())
    a = next(it for it in log["items"] if it["id"] == "a.md")
    assert a["status"] == "failed"
    assert "no 'pr'" in a["error"]
```

Run `bash scripts/smoke.sh` — all three new tests must FAIL (IndexError, "--resume" in
message, KeyError-flavored failure respectively).

2. **Fixes.**

   a. In `cli.main`, replace the `status` subcommand block with:

```python
    if argv and argv[0] == "status":
        rest = argv[1:]
        repo = "."
        if "--repo" in rest:
            i = rest.index("--repo")
            if i + 1 >= len(rest):
                print("error: --repo requires a value", file=sys.stderr)
                return 1
            repo = rest[i + 1]
        elif rest and not rest[0].startswith("-"):
            repo = rest[0]
        return cmd_status(repo)
```

      and the `preflight` block's `--repo` handling with:

```python
    if argv and argv[0] == "preflight":
        rest = argv[1:]
        repo = "."
        if "--repo" in rest:
            i = rest.index("--repo")
            if i + 1 >= len(rest):
                print("error: --repo requires a value", file=sys.stderr)
                return 1
            repo = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        return cmd_preflight(repo, rest)
```

   b. In `cli.main`, replace the archive-check block body (inside
      `if run_log_path.exists() and not args.resume:`) with:

```python
        import json
        corrupt = False
        try:
            log = json.loads(run_log_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            log, corrupt = {}, True
        all_terminal = bool(log.get("items")) and all(
            it.get("status") in ("shipped", "failed") for it in log["items"])
        different_backlog = list(specs) != list(log.get("order", []))
        if args.fresh or (all_terminal and different_backlog):
            dest = _archive_completed_run(state_dir)
            print(f"archived prior run → {dest}")
        elif corrupt:
            print("the previous run-log at .multi-ship/run-log.json is corrupt — "
                  "pass --fresh to archive it and start over, or remove "
                  ".multi-ship/ to start fresh", file=sys.stderr)
            return 2
        else:
            print("a previous run-log exists at .multi-ship/run-log.json — pass "
                  "--resume to continue it, --fresh to archive it and start over, "
                  "or remove .multi-ship/ to start fresh", file=sys.stderr)
            return 2
```

   c. In `driver._process_item`, find the block that begins
      `if item.get("status") == "failed":` (the one right after
      `item = _read_json(item_path)` following the FIRST build — NOT the recovery
      block at the top of the function and NOT the `--fix` block). Directly after
      that block's `return False`, insert:

```python
    if not item.get("pr"):
        raise claude_cli.ClaudeError(
            f"ship-one report for {iid} has status '{item.get('status')}' but no 'pr' "
            "— cannot judge or merge")
```

**Verify:**

```bash
bash scripts/smoke.sh
```

Expected: `183 passed`.

**Commit:**

```bash
git add src/multi_ship/cli.py src/multi_ship/driver.py tests/test_cli_init.py tests/test_driver_loop.py
git commit -m "fix: clean errors for --repo without value, corrupt run-log, and item reports missing pr"
```

---

## Task 10 — claude_cli: remove the dead `repo` parameter from `build_command`

**Files:** `src/multi_ship/claude_cli.py`, `tests/test_claude_cli.py`.

**Bug (nit):** `build_command(prompt, repo, permission_mode=...)` never uses `repo`
(the cwd is set in `_raw_run`), misleading readers into thinking the command embeds the
repo path.

1. Replace `build_command` with:

```python
def build_command(prompt: str, permission_mode: str = "bypassPermissions") -> list[str]:
    # The repo is NOT part of the command line — `run` sets it as the subprocess
    # cwd, which is what scopes the claude session to the target checkout.
    return [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--permission-mode", permission_mode,
    ]
```

2. In `run()`, change `cmd = build_command(prompt, repo)` → `cmd = build_command(prompt)`.

3. In `tests/test_claude_cli.py`, change the first line of
   `test_build_command_invokes_skill_and_json_output` to:

```python
    cmd = claude_cli.build_command("/ship-one docs/specs/a.md")
```

**Verify:**

```bash
bash scripts/smoke.sh
grep -rn "build_command(" src/ tests/ | grep -v pycache
```

Expected: `183 passed`; grep shows only the definition, the single call in `run()`, and
the updated test — none passing a repo argument.

**Commit:**

```bash
git add src/multi_ship/claude_cli.py tests/test_claude_cli.py
git commit -m "refactor: drop dead repo parameter from claude_cli.build_command"
```

---

## Task 11 — Docs: CHANGELOG reflects the new behavior

**Files:** `CHANGELOG.md` ONLY.

⚠️ `README.md` has uncommitted operator edits — do NOT touch or commit `README.md`
at all in this task (committing it would sweep the operator's WIP into this branch).
The README statements about the judge fail-open and `.claude/workflows/` are accurate
after Tasks 4 and 8; a fuller README polish is a follow-up, not this task.

1. In `CHANGELOG.md`, add under the top heading (create an `## Unreleased` section at
   the top if one doesn't exist):

```markdown
## Unreleased

### Fixed
- A hung `claude -p` (subprocess timeout) is now a per-item `ClaudeError` instead of an
  uncaught `TimeoutExpired` that crashed the whole run before notification.
- The documented judge fail-open is now implemented: a judge crash or a judge session
  that writes no fresh `verdict-<id>.json` logs and proceeds to merge instead of
  failing the item; stale verdicts from prior rounds are never trusted (mtime guard).
- The `--fix` path now applies the same fresh-report + failed-status discipline as the
  first build (a failed fix keeps the builder's `failure_kind`; a crashed fix is an
  honest error, not a re-judge of stale data).
- `claude -p` payloads with exit 0 but `is_error: true` (including mid-session quota
  hits) are treated as failures.
- Run-log writes are atomic (tmp + rename); per-round fields (`judge_reason`,
  `paused_reason`, `error`, …) are cleared on every status transition so
  `multi-ship status` never shows a stale note.
- A glob token that matches no files raises `ResolveError` instead of silently
  dropping specs.
- `multi-ship init` installs the bundled build workflow into `.claude/workflows/`
  (per DESIGN.md); previously a fresh install could never build.
- Clean errors for `--repo` without a value, a corrupt `run-log.json` (no longer
  suggests `--resume`, which would crash), and item reports missing `pr`.
```

**Verify:**

```bash
bash scripts/smoke.sh
git status --porcelain -- CHANGELOG.md
```

Expected: `183 passed`; `CHANGELOG.md` modified (and README.md NOT staged).

**Commit:**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for judge fail-open, init workflow install, and hardening fixes"
```

---

## Acceptance summary (the complete definition of done)

Run from the repo root on branch `fix/correctness-hardening`:

```bash
bash scripts/smoke.sh                                   # → 183 passed
PYTHONPATH=src python3 -m pytest -q tests/              # → 183 passed (same gate, explicit)
git log --oneline main..HEAD | wc -l                    # → 11 commits
test -x scripts/smoke.sh && echo OK                     # → OK
PYTHONPATH=src python3 - <<'EOF'                        # → all behavioral spot-checks print OK
import json, subprocess, tempfile
from pathlib import Path
from multi_ship import claude_cli, runlog
from multi_ship.cli import cmd_init, bundled_dir
from multi_ship.resolve import resolve_specs, ResolveError

# C1: hung probe fails open
import multi_ship.claude_cli as cc
orig = cc._raw_run
cc._raw_run = lambda cmd, cwd, timeout: (_ for _ in ()).throw(
    subprocess.TimeoutExpired(cmd=cmd, timeout=timeout))
assert cc.probe_quota("/tmp") == (True, None); cc._raw_run = orig
print("OK C1 probe fail-open on timeout")

# C2: init installs the workflow
with tempfile.TemporaryDirectory() as d:
    cmd_init(d, template_path=bundled_dir("templates") / "multi-ship.json")
    assert (Path(d) / ".claude/workflows/mixed-model-burst.js").exists()
print("OK C2 init installs workflow")

# M3+M4: transient clearing + atomic write
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "run-log.json"
    runlog.init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    runlog.force_pending(p, "a.md", paused_reason="quota_exhausted")
    runlog.set_item_status(p, "a.md", "awaiting_judge")
    it = runlog.read_run_log(p)["items"][0]
    assert "paused_reason" not in it
    assert [f.name for f in Path(d).iterdir()] == ["run-log.json"]
print("OK M3/M4 transient clearing + no tmp leftovers")

# M5: zero-match glob raises
from multi_ship.config import load_config
with tempfile.TemporaryDirectory() as d:
    cfg = load_config(bundled_dir("templates") / "multi-ship.json")
    try:
        resolve_specs(tokens=["nope/*.md"], issue_numbers=[], cfg=cfg, repo=Path(d))
        raise AssertionError("should have raised")
    except ResolveError:
        pass
print("OK M5 zero-match glob raises")
EOF
```

Every command above must succeed with the expected output. The judge fail-open (C3/M1)
and fix-path (M2) behaviors are covered by the pytest gate
(`test_judge_crash_fails_open_and_merges`, `test_judge_writes_no_fresh_verdict_fails_open`,
`test_fix_reporting_failed_stops_with_builder_kind`, `test_fix_writing_no_fresh_report_fails_item`).

## Out of scope (deliberately deferred)

- **Parallel item execution** — documented as sequential by design.
- **PyPI publishing, demo GIF, PROMOTION.md work** — operator-owned, in flight as
  uncommitted edits; not touched.
- **Skill-file (`SKILL.md`) content changes** — prompt engineering, not code
  correctness; the judge/ship-one contracts already match the fixed driver.
- **`_seconds_until_reset` ambiguity for phrases without am/pm** — best-effort by
  design, clamped; a wrong guess costs at most one bounded re-probe cycle.
- **Corrupt-run-log auto-archive** (we only fix the misleading message) — archiving a
  corrupt log automatically could hide real state; the operator decides.
- **`detect_quota` false positives on "rate limit exceeded"** — intentionally lenient
  per the in-code rationale; a false positive is a recoverable pause.
- **`install-skills` also linking workflows into `~/.claude/workflows/`** — Claude Code
  resolves workflows per-repo; the per-repo `init` fix is the correct seam. Follow-up
  candidate if a global path proves useful.
