# multi-ship Implementation Plan (ARCHIVED — 2026-06-16 bootstrap)

> **Historical artifact.** This is the original pre-release bootstrap plan,
> retained for project history. All tasks were completed in June 2026 (the
> checkboxes were never ticked). The code listings below reflect the pre-release
> state and contain bugs fixed since (see CHANGELOG.md, e.g. PR #16) — do NOT
> use them as a reference for current behavior; the source tree and README are
> authoritative.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `multi-ship` — an installable, MIT-licensed CLI that ships N independent specs end-to-end autonomously, giving each item a fresh `claude -p` context, with on-disk handoff memory, a cold pre-merge judge gate, and end-of-run consolidation.

**Architecture:** A dumb Python driver (stdlib-only) runs the loop *outside* any Claude session and routes only on `{status}`/`{ok}` JSON files. Each item is a fresh `claude -p "/ship-one <spec>"`; a cold `claude -p "/judge-shipped"` gates the merge; the driver merges deterministically via `gh`. Cross-item memory lives in `.multi-ship/HANDOFF.md`. Build is delegated to a bundled, model-parametrized `mixed-model-burst.js` workflow.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `subprocess`, `json`, `pathlib`, `dataclasses`); pytest (dev); Claude Code (`claude -p`, Workflow/Agent engine); `gh` CLI; `caffeinate` (macOS). Bundled workflow is JavaScript run by Claude Code's Workflow engine.

**Reference:** `DESIGN.md` (same dir during bootstrap; moves into the repo in Task 1).

**Phasing:** Phase 1 (Tasks 2–5) produces a fully unit-tested pure-logic core. Phase 2 (6–8) wires the loop + CLI. Phase 3 (9–12) writes the skills. Phase 4 (13) genericizes the workflow. Phase 5 (14–17) packages for release. Phase 6 (18) is the live smoke. Each phase leaves the repo in a committable, test-green state.

---

## Task 1: Repo scaffold + license + gitignore

**Files:**
- Create: `~/Projects/multi-ship/` (git repo)
- Create: `~/Projects/multi-ship/LICENSE`, `.gitignore`, `src/multi_ship/__init__.py`, `tests/__init__.py`
- Move: `~/.claude/scripts/multi-ship/{DESIGN.md,PLAN.md}` → `~/Projects/multi-ship/`

- [ ] **Step 1: Create the repo and directory tree**

```bash
mkdir -p ~/Projects/multi-ship/{bin,src/multi_ship,skills,workflows,templates,tests,.github/workflows}
cd ~/Projects/multi-ship && git init -b main
mv ~/.claude/scripts/multi-ship/DESIGN.md ~/Projects/multi-ship/DESIGN.md
mv ~/.claude/scripts/multi-ship/PLAN.md   ~/Projects/multi-ship/PLAN.md
rmdir ~/.claude/scripts/multi-ship 2>/dev/null || true
touch src/multi_ship/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `LICENSE` (MIT)**

Standard MIT text, copyright `2026 Alex Monteiro`. (Use the canonical MIT template verbatim with that holder/year.)

- [ ] **Step 3: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.multi-ship/
.venv/
*.egg-info/
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: scaffold multi-ship repo (MIT, design + plan)"
```

---

## Task 2: `config.py` — load + validate `.claude/multi-ship.json`

**Files:**
- Create: `src/multi_ship/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import json
import pytest
from multi_ship.config import load_config, ConfigError

REQUIRED = {
    "build_workflow": "mixed-model-burst",
    "spec_glob": "docs/specs/*.md",
    "verify": "gh pr checks $PR --watch",
    "notify": "echo",
    "pr_body_convention": "Closes #{issue}",
    "complete_cmd": "/complete-spec {slug}",
    "test_cmd": "pytest -x",
    "build_invariants": "TDD test-first",
    "smoke_instructions": "load config; exercise path",
    "roles": {
        "scout": "haiku", "reader": "haiku", "planner": "opus",
        "judges": ["opus", "sonnet", "haiku"],
        "coder": {"hard": "opus", "routine": "sonnet"}, "verifier": "opus",
    },
}

def _write(tmp_path, data):
    p = tmp_path / "multi-ship.json"
    p.write_text(json.dumps(data))
    return p

def test_load_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, REQUIRED))
    assert cfg.build_workflow == "mixed-model-burst"
    assert cfg.roles["judges"] == ["opus", "sonnet", "haiku"]
    assert cfg.roles["coder"]["hard"] == "opus"

def test_missing_key_raises(tmp_path):
    bad = {k: v for k, v in REQUIRED.items() if k != "verify"}
    with pytest.raises(ConfigError, match="verify"):
        load_config(_write(tmp_path, bad))

def test_missing_role_subkey_raises(tmp_path):
    bad = json.loads(json.dumps(REQUIRED))
    del bad["roles"]["planner"]
    with pytest.raises(ConfigError, match="roles.planner"):
        load_config(_write(tmp_path, bad))

def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")

def test_bad_json_raises(tmp_path):
    p = tmp_path / "multi-ship.json"
    p.write_text("{not json")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Projects/multi-ship && PYTHONPATH=src pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multi_ship.config'`

- [ ] **Step 3: Write `src/multi_ship/config.py`**

```python
"""Load + validate a project's .claude/multi-ship.json."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

class ConfigError(Exception):
    pass

_REQUIRED_KEYS = [
    "build_workflow", "spec_glob", "verify", "notify", "pr_body_convention",
    "complete_cmd", "test_cmd", "build_invariants", "smoke_instructions", "roles",
]
_REQUIRED_ROLES = ["scout", "reader", "planner", "judges", "coder", "verifier"]

@dataclass(frozen=True)
class Config:
    build_workflow: str
    spec_glob: str
    verify: str
    notify: str
    pr_body_convention: str
    complete_cmd: str
    test_cmd: str
    build_invariants: str
    smoke_instructions: str
    roles: dict

def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}") from e
    for k in _REQUIRED_KEYS:
        if k not in data:
            raise ConfigError(f"missing required key: {k}")
    roles = data["roles"]
    if not isinstance(roles, dict):
        raise ConfigError("roles must be an object")
    for r in _REQUIRED_ROLES:
        if r not in roles:
            raise ConfigError(f"missing required key: roles.{r}")
    if not isinstance(roles["judges"], list) or not roles["judges"]:
        raise ConfigError("roles.judges must be a non-empty list")
    if not isinstance(roles["coder"], dict) or "hard" not in roles["coder"] or "routine" not in roles["coder"]:
        raise ConfigError("roles.coder must have 'hard' and 'routine'")
    return Config(**{k: data[k] for k in _REQUIRED_KEYS})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/multi_ship/config.py tests/test_config.py
git commit -m "feat: config loader + validation for .claude/multi-ship.json"
```

---

## Task 3: `runlog.py` — run-log init, read/write, item-status state machine

**Files:**
- Create: `src/multi_ship/runlog.py`
- Test: `tests/test_runlog.py`

Item statuses: `pending → awaiting_judge → shipped`; `awaiting_judge → needs_fix → awaiting_judge`; any non-terminal → `failed`. Terminal: `shipped`, `failed`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_runlog.py
import json
import pytest
from multi_ship.runlog import (
    init_run_log, read_run_log, set_item_status, StatusError,
)

def test_init_creates_log_with_pending_items(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md", "b.md"], stop_on_failure=True, notification_surface="none")
    log = read_run_log(p)
    assert [i["id"] for i in log["items"]] == ["a.md", "b.md"]
    assert all(i["status"] == "pending" for i in log["items"])
    assert log["stop_on_failure"] is True

def test_init_is_fail_closed_idempotent_guard(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    # re-init must not silently wipe an in-progress log
    with pytest.raises(StatusError, match="already exists"):
        init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")

def test_valid_transition_pending_to_awaiting_to_shipped(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge", pr="http://pr/1")
    set_item_status(p, "a.md", "shipped")
    log = read_run_log(p)
    assert log["items"][0]["status"] == "shipped"
    assert log["items"][0]["pr"] == "http://pr/1"

def test_invalid_transition_pending_to_shipped_raises(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    with pytest.raises(StatusError, match="pending -> shipped"):
        set_item_status(p, "a.md", "shipped")

def test_needs_fix_cycle(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    set_item_status(p, "a.md", "awaiting_judge")
    set_item_status(p, "a.md", "needs_fix")
    set_item_status(p, "a.md", "awaiting_judge")
    set_item_status(p, "a.md", "shipped")
    assert read_run_log(p)["items"][0]["status"] == "shipped"

def test_unknown_item_raises(tmp_path):
    p = tmp_path / "run-log.json"
    init_run_log(p, order=["a.md"], stop_on_failure=True, notification_surface="none")
    with pytest.raises(StatusError, match="unknown item"):
        set_item_status(p, "z.md", "awaiting_judge")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_runlog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multi_ship.runlog'`

- [ ] **Step 3: Write `src/multi_ship/runlog.py`**

```python
"""Run-log: durable per-run state with an enforced item-status state machine."""
from __future__ import annotations
import json
from pathlib import Path

class StatusError(Exception):
    pass

_TRANSITIONS = {
    "pending": {"awaiting_judge", "failed"},
    "awaiting_judge": {"shipped", "needs_fix", "failed"},
    "needs_fix": {"awaiting_judge", "failed"},
    "shipped": set(),
    "failed": set(),
}
TERMINAL = {"shipped", "failed"}

def init_run_log(path: Path, order: list[str], stop_on_failure: bool, notification_surface: str) -> None:
    path = Path(path)
    if path.exists():
        raise StatusError(f"run-log already exists at {path} — use --resume, do not re-init")
    path.parent.mkdir(parents=True, exist_ok=True)
    log = {
        "stop_on_failure": stop_on_failure,
        "notification_surface": notification_surface,
        "order": list(order),
        "items": [{"id": s, "status": "pending"} for s in order],
    }
    _write(path, log)

def read_run_log(path: Path) -> dict:
    return json.loads(Path(path).read_text())

def _write(path: Path, log: dict) -> None:
    Path(path).write_text(json.dumps(log, indent=2))

def _find(log: dict, item_id: str) -> dict:
    for it in log["items"]:
        if it["id"] == item_id:
            return it
    raise StatusError(f"unknown item: {item_id}")

def set_item_status(path: Path, item_id: str, new_status: str, **fields) -> None:
    log = read_run_log(path)
    it = _find(log, item_id)
    cur = it["status"]
    if new_status not in _TRANSITIONS.get(cur, set()):
        raise StatusError(f"illegal transition {cur} -> {new_status} for {item_id}")
    it["status"] = new_status
    it.update(fields)
    _write(path, log)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_runlog.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/multi_ship/runlog.py tests/test_runlog.py
git commit -m "feat: run-log with enforced item-status state machine + fail-closed init"
```

---

## Task 4: Resume selection + stop-on-failure routing + dream gate

**Files:**
- Modify: `src/multi_ship/runlog.py` (append pure predicates)
- Test: `tests/test_policy.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy.py
from multi_ship.runlog import next_item, should_stop, worth_dreaming

def _log(items, stop=True):
    return {"stop_on_failure": stop, "items": items}

def test_next_item_skips_shipped(tmp_path):
    log = _log([{"id": "a.md", "status": "shipped"}, {"id": "b.md", "status": "pending"}])
    assert next_item(log) == "b.md"

def test_next_item_returns_failed_for_retry(tmp_path):
    log = _log([{"id": "a.md", "status": "shipped"}, {"id": "b.md", "status": "failed"}])
    assert next_item(log) == "b.md"

def test_next_item_none_when_all_shipped():
    log = _log([{"id": "a.md", "status": "shipped"}])
    assert next_item(log) is None

def test_should_stop_on_failure_when_policy_stop():
    assert should_stop(_log([], stop=True), item_failed=True) is True

def test_should_continue_on_failure_when_policy_continue():
    assert should_stop(_log([], stop=False), item_failed=True) is False

def test_should_not_stop_on_success():
    assert should_stop(_log([], stop=True), item_failed=False) is False

def test_worth_dreaming_two_shipped():
    log = _log([{"id": "a", "status": "shipped"}, {"id": "b", "status": "shipped"}])
    assert worth_dreaming(log, handoff_text="") is True

def test_worth_dreaming_nonempty_handoff_section():
    log = _log([{"id": "a", "status": "shipped"}])
    text = "## Errors and fixes\n- broke X, fixed by Y\n## Open notes\n"
    assert worth_dreaming(log, handoff_text=text) is True

def test_not_worth_dreaming_trivial():
    log = _log([{"id": "a", "status": "shipped"}])
    text = "## Errors and fixes\n## Discovered knowledge\n## Open notes\n"
    assert worth_dreaming(log, handoff_text=text) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_policy.py -v`
Expected: FAIL with `ImportError: cannot import name 'next_item'`

- [ ] **Step 3: Append to `src/multi_ship/runlog.py`**

```python
def next_item(log: dict) -> str | None:
    """First non-shipped item id (failed items are retried on resume)."""
    for it in log["items"]:
        if it["status"] != "shipped":
            return it["id"]
    return None

def should_stop(log: dict, item_failed: bool) -> bool:
    return bool(item_failed and log.get("stop_on_failure", True))

def worth_dreaming(log: dict, handoff_text: str) -> bool:
    shipped = sum(1 for it in log["items"] if it["status"] == "shipped")
    if shipped >= 2:
        return True
    # any content under Errors/Knowledge beyond the bare headings?
    for heading in ("## Errors and fixes", "## Discovered knowledge"):
        body = _section_body(handoff_text, heading)
        if body.strip():
            return True
    return False

def _section_body(text: str, heading: str) -> str:
    lines = text.splitlines()
    out, capture = [], False
    for ln in lines:
        if ln.strip() == heading:
            capture = True
            continue
        if capture and ln.startswith("## "):
            break
        if capture:
            out.append(ln)
    return "\n".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_policy.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/multi_ship/runlog.py tests/test_policy.py
git commit -m "feat: resume selection, stop-on-failure routing, dream gate predicate"
```

---

## Task 5: `handoff.py` — HANDOFF.md schema scaffold

**Files:**
- Create: `src/multi_ship/handoff.py`
- Test: `tests/test_handoff.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_handoff.py
from multi_ship.handoff import init_handoff, HANDOFF_SECTIONS

def test_init_writes_all_sections(tmp_path):
    p = tmp_path / "HANDOFF.md"
    init_handoff(p)
    text = p.read_text()
    for sec in HANDOFF_SECTIONS:
        assert f"## {sec}" in text

def test_init_does_not_clobber_existing(tmp_path):
    p = tmp_path / "HANDOFF.md"
    p.write_text("## Open notes\n- existing\n")
    init_handoff(p)  # must be a no-op if present
    assert "existing" in p.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_handoff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multi_ship.handoff'`

- [ ] **Step 3: Write `src/multi_ship/handoff.py`**

```python
"""HANDOFF.md — fixed-schema cross-item memory (trimmed from MiMo's checkpoint)."""
from __future__ import annotations
from pathlib import Path

HANDOFF_SECTIONS = [
    "Discovered knowledge",
    "Errors and fixes",
    "Live resources",
    "Design decisions",
    "Open notes",
]

def init_handoff(path: Path) -> None:
    path = Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"## {s}\n" for s in HANDOFF_SECTIONS)
    path.write_text(f"# multi-ship HANDOFF\n\n{body}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_handoff.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/multi_ship/handoff.py tests/test_handoff.py
git commit -m "feat: HANDOFF.md fixed-schema scaffold"
```

---

## Task 6: `claude_cli.py` — thin, testable wrapper over `claude -p`

**Files:**
- Create: `src/multi_ship/claude_cli.py`
- Test: `tests/test_claude_cli.py`

Isolates the subprocess so the loop is testable by monkeypatching one function.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_claude_cli.py
import json
from multi_ship import claude_cli

def test_build_command_invokes_skill_and_json_output():
    cmd = claude_cli.build_command("/ship-one docs/specs/a.md", repo="/repo")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "/ship-one docs/specs/a.md" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--permission-mode" in cmd

def test_run_parses_json_result(monkeypatch):
    fake = json.dumps({"result": "done", "session_id": "abc"})
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (0, fake, ""))
    out = claude_cli.run("/x", repo="/repo")
    assert out["result"] == "done"

def test_run_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(claude_cli, "_raw_run", lambda cmd, cwd, timeout: (1, "", "boom"))
    import pytest
    with pytest.raises(claude_cli.ClaudeError, match="boom"):
        claude_cli.run("/x", repo="/repo")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_claude_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `src/multi_ship/claude_cli.py`**

```python
"""Thin wrapper over `claude -p` so the loop is subprocess-testable."""
from __future__ import annotations
import json
import subprocess

class ClaudeError(Exception):
    pass

def build_command(prompt: str, repo: str, permission_mode: str = "bypassPermissions") -> list[str]:
    return [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--permission-mode", permission_mode,
    ]

def _raw_run(cmd: list[str], cwd: str, timeout: int):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr

def run(prompt: str, repo: str, timeout: int = 7200) -> dict:
    cmd = build_command(prompt, repo)
    code, out, err = _raw_run(cmd, cwd=repo, timeout=timeout)
    if code != 0:
        raise ClaudeError(f"claude -p exited {code}: {err.strip()[:500]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"claude -p returned non-JSON: {out[:500]}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_claude_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/multi_ship/claude_cli.py tests/test_claude_cli.py
git commit -m "feat: testable claude -p wrapper"
```

---

## Task 7: `driver.py` — the orchestration loop (with subprocess mocked in tests)

**Files:**
- Create: `src/multi_ship/driver.py`
- Test: `tests/test_driver_loop.py`

The driver reads item-`<id>`.json / verdict-`<id>`.json written by the (mocked) Claude calls and routes. Tests drive it by monkeypatching `claude_cli.run` to write those files and return.

- [ ] **Step 1: Write the failing test (happy path: one item ships)**

```python
# tests/test_driver_loop.py
import json
from pathlib import Path
from multi_ship import driver, claude_cli, config as cfgmod

def _cfg():
    return cfgmod.Config(
        build_workflow="mmb", spec_glob="docs/specs/*.md", verify="true",
        notify="true", pr_body_convention="Closes #{issue}",
        complete_cmd="/complete-spec {slug}", test_cmd="true",
        build_invariants="x", smoke_instructions="y",
        roles={"scout": "haiku", "reader": "haiku", "planner": "opus",
               "judges": ["opus"], "coder": {"hard": "opus", "routine": "sonnet"},
               "verifier": "opus"},
    )

def test_single_item_ships(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            (state / f"verdict-{sid}.json").write_text(json.dumps({"ok": True, "reason": "meets DoD"}))
            return {"result": "judged"}
        return {"result": "ok"}  # complete_cmd / dream
    monkeypatch.setattr(claude_cli, "run", fake_run)
    merges = []
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: merges.append(pr))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)

    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]
    assert merges == ["http://pr/1"]

def test_judge_reject_then_fix_then_ship(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    calls = {"judge": 0}
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1", "branch": "spec/a"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            calls["judge"] += 1
            ok = calls["judge"] >= 2  # reject first, pass on the post-fix re-judge
            (state / f"verdict-{sid}.json").write_text(json.dumps(
                {"ok": ok, "reason": "missing test" if not ok else "ok now"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: None)
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == ["a.md"]
    assert calls["judge"] == 2  # one reject + one post-fix pass

def test_judge_reject_twice_stops(tmp_path, monkeypatch):
    state = tmp_path / ".multi-ship"
    def fake_run(prompt, repo, timeout=7200):
        sid = "a.md"
        if prompt.startswith("/ship-one"):
            (state / f"item-{sid}.json").write_text(json.dumps(
                {"status": "awaiting_judge", "pr": "http://pr/1"}))
            return {"result": "built"}
        if prompt.startswith("/judge-shipped"):
            (state / f"verdict-{sid}.json").write_text(json.dumps({"ok": False, "reason": "still broken"}))
            return {"result": "judged"}
        return {"result": "ok"}
    monkeypatch.setattr(claude_cli, "run", fake_run)
    monkeypatch.setattr(driver, "_merge_pr", lambda pr, repo: (_ for _ in ()).throw(AssertionError("must not merge")))
    monkeypatch.setattr(driver, "_caffeinate", lambda: None)
    monkeypatch.setattr(driver, "_kill_caffeinate", lambda *a: None)
    result = driver.run_loop(repo=str(tmp_path), specs=["a.md", "b.md"], cfg=_cfg(),
                             stop_on_failure=True, state_dir=state)
    assert result["shipped"] == []
    assert result["stopped_at"] == "a.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_driver_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multi_ship.driver'`

- [ ] **Step 3: Write `src/multi_ship/driver.py`**

```python
"""The orchestration loop. Dumb: routes only on item/verdict JSON files."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from . import claude_cli, runlog, handoff
from .config import Config

def _caffeinate():
    return subprocess.Popen(["caffeinate", "-dimsu"])

def _kill_caffeinate(proc):
    if proc:
        proc.terminate()

def _merge_pr(pr: str, repo: str):
    subprocess.run(["gh", "pr", "merge", pr, "--squash", "--delete-branch"],
                   cwd=repo, check=True)

def _read_json(p: Path) -> dict:
    return json.loads(Path(p).read_text())

def run_loop(repo: str, specs: list[str], cfg: Config, stop_on_failure: bool,
             state_dir: Path) -> dict:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    run_log = state_dir / "run-log.json"
    if not run_log.exists():
        runlog.init_run_log(run_log, order=specs, stop_on_failure=stop_on_failure,
                            notification_surface=cfg.notify)
    init_h = state_dir / "HANDOFF.md"
    handoff.init_handoff(init_h)

    caf = _caffeinate()
    shipped, stopped_at = [], None
    try:
        log = runlog.read_run_log(run_log)
        while True:
            sid = runlog.next_item(log)
            if sid is None:
                break
            ok = _process_item(sid, repo, cfg, state_dir, run_log)
            log = runlog.read_run_log(run_log)
            if ok:
                shipped.append(sid)
            else:
                if runlog.should_stop(log, item_failed=True):
                    stopped_at = sid
                    break
        _end_of_run(repo, cfg, state_dir, run_log)
    finally:
        _kill_caffeinate(caf)
    return {"shipped": shipped, "stopped_at": stopped_at}

def _process_item(sid: str, repo: str, cfg: Config, state_dir: Path, run_log: Path) -> bool:
    # Build + ship-tail → ship-one writes item-<id>.json, pauses before merge
    claude_cli.run(f"/ship-one {sid}", repo=repo)
    item = _read_json(state_dir / f"item-{sid}.json")
    if item.get("status") == "failed":
        runlog.set_item_status(run_log, sid, "failed", **{k: item.get(k) for k in ("pr",) if item.get(k)})
        return False
    runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"), branch=item.get("branch"))

    # Cold judge, with one fix retry
    for attempt in range(2):
        claude_cli.run(f"/judge-shipped {sid} {item.get('pr','')}", repo=repo)
        verdict = _read_json(state_dir / f"verdict-{sid}.json")
        if verdict.get("ok"):
            _merge_pr(item["pr"], repo)
            slug = Path(sid).stem
            claude_cli.run(cfg.complete_cmd.format(slug=slug), repo=repo)
            runlog.set_item_status(run_log, sid, "shipped")
            return True
        if attempt == 0:
            # re-dispatch ship-one to FIX using the judge's reason, then re-judge
            runlog.set_item_status(run_log, sid, "needs_fix")
            claude_cli.run(f"/ship-one {sid} --fix \"{verdict.get('reason','')}\"", repo=repo)
            item = _read_json(state_dir / f"item-{sid}.json")
            runlog.set_item_status(run_log, sid, "awaiting_judge", pr=item.get("pr"))
    runlog.set_item_status(run_log, sid, "failed", judge_reason=verdict.get("reason"))
    return False

def _end_of_run(repo: str, cfg: Config, state_dir: Path, run_log: Path):
    log = runlog.read_run_log(run_log)
    handoff_text = (state_dir / "HANDOFF.md").read_text()
    if runlog.worth_dreaming(log, handoff_text):
        claude_cli.run("/dream-run", repo=repo)
    # follow-up spec consolidation + notify are layered in Task 8/CLI wiring.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_driver_loop.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full suite + commit**

Run: `PYTHONPATH=src pytest -v`
Expected: PASS (all tasks 2–7 green)

```bash
git add src/multi_ship/driver.py tests/test_driver_loop.py
git commit -m "feat: orchestration loop with cold-judge gate + 1 fix retry"
```

---

## Task 8: CLI entrypoint + `multi-ship init` + `bin/multi-ship` shim

**Files:**
- Create: `src/multi_ship/cli.py`, `bin/multi-ship`
- Test: `tests/test_cli_init.py`

- [ ] **Step 1: Write the failing test for `init`**

```python
# tests/test_cli_init.py
from pathlib import Path
from multi_ship.cli import cmd_init

def test_init_scaffolds_config_and_gitignore(tmp_path):
    repo = tmp_path
    (repo / ".git").mkdir()
    template = Path(__file__).parent.parent / "templates" / "multi-ship.json"
    cmd_init(str(repo), template_path=template)
    assert (repo / ".claude" / "multi-ship.json").exists()
    gi = (repo / ".gitignore").read_text()
    assert ".multi-ship/" in gi
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_cli_init.py -v`
Expected: FAIL (`ModuleNotFoundError` or missing template — create the template in Task 15; for now this test fails on import)

- [ ] **Step 3: Write `src/multi_ship/cli.py`**

```python
"""multi-ship CLI: run a backlog, or `init` a repo."""
from __future__ import annotations
import argparse
import glob
import shutil
import sys
from pathlib import Path

from . import driver
from .config import load_config

def cmd_init(repo: str, template_path: Path) -> None:
    repo = Path(repo)
    claude_dir = repo / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    dest = claude_dir / "multi-ship.json"
    if not dest.exists():
        shutil.copy(template_path, dest)
    gi = repo / ".gitignore"
    line = ".multi-ship/"
    existing = gi.read_text() if gi.exists() else ""
    if line not in existing:
        gi.write_text(existing + ("\n" if existing and not existing.endswith("\n") else "") + line + "\n")

def _resolve_specs(args, cfg) -> list[str]:
    if args.specs:
        out = []
        for s in args.specs:
            out.extend(sorted(glob.glob(s)) if any(c in s for c in "*?[") else [s])
        return out
    return sorted(glob.glob(cfg.spec_glob))

def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="multi-ship")
    sub = p.add_subparsers(dest="command")
    pi = sub.add_parser("init"); pi.add_argument("repo", nargs="?", default=".")
    p.add_argument("specs", nargs="*")
    p.add_argument("--repo", default=".")
    p.add_argument("--continue-on-failure", action="store_true")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args(argv)

    pkg_root = Path(__file__).resolve().parent.parent.parent
    if args.command == "init":
        cmd_init(args.repo, template_path=pkg_root / "templates" / "multi-ship.json")
        print(f"initialized {args.repo}/.claude/multi-ship.json")
        return 0

    repo = Path(args.repo).resolve()
    cfg = load_config(repo / ".claude" / "multi-ship.json")
    specs = _resolve_specs(args, cfg)
    if not specs:
        print("no specs to ship", file=sys.stderr); return 1
    result = driver.run_loop(repo=str(repo), specs=specs, cfg=cfg,
                             stop_on_failure=not args.continue_on_failure,
                             state_dir=repo / ".multi-ship")
    print(f"shipped: {result['shipped']}  stopped_at: {result['stopped_at']}")
    return 0 if result["stopped_at"] is None else 2

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write `bin/multi-ship` (stdlib-only shim, no pip needed)**

```bash
#!/usr/bin/env bash
# Resolve the repo root from this script's location (handles symlinks).
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"; SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd -P "$(dirname "$SOURCE")/.." && pwd)"
exec python3 -c "import sys; sys.path.insert(0, '$ROOT/src'); from multi_ship.cli import main; raise SystemExit(main())" "$@"
```

```bash
chmod +x bin/multi-ship
```

- [ ] **Step 5: Run to verify it passes (after Task 15 template exists, re-run)**

Run: `PYTHONPATH=src pytest tests/test_cli_init.py -v`
Expected: PASS once `templates/multi-ship.json` exists (Task 15). If running in order, create a minimal template now to unblock, finalized in Task 15.

- [ ] **Step 6: Commit**

```bash
git add src/multi_ship/cli.py bin/multi-ship tests/test_cli_init.py
git commit -m "feat: CLI entrypoint + init subcommand + bin shim"
```

---

## Task 9: `skills/ship-one/SKILL.md`

**Files:**
- Create: `skills/ship-one/SKILL.md`

Port the per-item lifecycle from the existing `autonomous-session` Steps 1–3 + `autonomous-multi-ship` ship-tail, with two changes: (a) it STOPS before merge (driver merges), (b) it reads/writes `.multi-ship/HANDOFF.md` and `.multi-ship/item-<id>.json`.

- [ ] **Step 1: Write the skill**

Frontmatter `name: ship-one`, `description:` (triggers only when invoked by the driver or operator for a single item). Body sections:
1. **Read HANDOFF first** — `.multi-ship/HANDOFF.md`, honor its Errors-and-fixes / Live-resources.
2. **Build** — `Workflow({name: <build_workflow from config>, args:{spec, build:true, difficulty, repo, roles, invariants}})`; the guard to confirm it targeted the right spec (port from autonomous-multi-ship).
3. **Ship-tail** — push → PR with `pr_body_convention` → CI cold-green via `verify` → reviewer triage (port the 🔴/🟡/🟢 table). **STOP before merge.**
4. **`--fix "<reason>"` mode** — when re-dispatched by the driver after a judge reject: apply the fix on the existing branch, re-verify, re-push; do NOT open a new PR.
5. **Write `item-<id>.json`** `{status: awaiting_judge|failed, pr, branch, dod, files_touched, followups, verify_output_tail, parent_notes}`.
6. **Append to HANDOFF.md** — Discovered-knowledge / Errors-and-fixes / Live-resources.
7. **Hard rules (prose):** cold-verify discipline, no destructive ops, secrets hygiene, stay in worktree.

- [ ] **Step 2: Commit**

```bash
git add skills/ship-one/SKILL.md
git commit -m "feat: ship-one skill (per-item build+ship-tail, pause before merge)"
```

---

## Task 10: `skills/judge-shipped/SKILL.md`

**Files:**
- Create: `skills/judge-shipped/SKILL.md`

- [ ] **Step 1: Write the skill**

Frontmatter `name: judge-shipped`. Body:
- **Inputs:** spec path + PR url (from args).
- **Cold read ONLY:** the spec's Definition of Done, `gh pr diff <pr>`, and `gh pr checks <pr>` status. Explicitly forbid reading the builder's transcript or HANDOFF prose that could bias toward "done."
- **Judge:** does the diff satisfy EVERY DoD item? Default skeptical. Quote DoD evidence.
- **Write `verdict-<id>.json`** `{ok: bool, reason: str}` to `.multi-ship/`.
- **Fail-open note:** if the judge itself cannot run (missing inputs), write `{ok: true, reason: "judge could not run — fail-open"}` so a broken judge never traps the run (the driver also guards this).

- [ ] **Step 2: Commit**

```bash
git add skills/judge-shipped/SKILL.md
git commit -m "feat: judge-shipped cold pre-merge DoD gate"
```

---

## Task 11: `skills/dream-run/SKILL.md`

**Files:**
- Create: `skills/dream-run/SKILL.md`

- [ ] **Step 1: Write the skill**

Frontmatter `name: dream-run`. Body:
- Reads `.multi-ship/HANDOFF.md` + all `item-<id>.json` reports.
- Extracts durable, reusable knowledge (recurring errors+fixes, conventions discovered) and drafts **proposed** additions to the project's CLAUDE.md "Active gotchas" + `~/.claude` memory files.
- Writes `.multi-ship/dream-proposals.md` (a review doc). **Never edits CLAUDE.md or memory directly.**
- States explicitly: operator reviews and applies.

- [ ] **Step 2: Commit**

```bash
git add skills/dream-run/SKILL.md
git commit -m "feat: dream-run consolidation (proposals, never auto-apply)"
```

---

## Task 12: Rewrite `autonomous-session` + `autonomous-multi-ship` as thin wrappers

**Files:**
- Create: `skills/autonomous-session/SKILL.md`, `skills/autonomous-multi-ship/SKILL.md`

- [ ] **Step 1: Write `autonomous-session/SKILL.md`**

Thin: "Autonomous single-item ship = `multi-ship <one-spec>` (N=1). Ensure the repo is `multi-ship init`'d, then run the driver with one spec. The driver caffeinates, builds via the workflow, gates with the cold judge, merges, and notifies." Point at the driver; do not duplicate the lifecycle.

- [ ] **Step 2: Write `autonomous-multi-ship/SKILL.md`**

Thin: "Autonomous N-item ship = `multi-ship <specs...>`. The driver owns the loop, run-log, resume, stop-on-failure, and end-of-run dream + follow-up consolidation. Per-item brains live in `ship-one`/`judge-shipped`/`dream-run`." Keep the 'When this triggers' / 'prerequisites' guidance; delete the now-obsolete in-context loop, the 14 prose hard rules that became code (point to the driver), and the ship-tail duplication.

- [ ] **Step 3: Commit**

```bash
git add skills/autonomous-session/SKILL.md skills/autonomous-multi-ship/SKILL.md
git commit -m "refactor: autonomous skills become thin wrappers over the driver"
```

---

## Task 13: Genericize `workflows/mixed-model-burst.js`

**Files:**
- Create: `workflows/mixed-model-burst.js` (written fresh as the generic, parametrized version)

- [ ] **Step 1: Author `workflows/mixed-model-burst.js` from scratch as the generic workflow**

Create the file at `~/Projects/multi-ship/workflows/mixed-model-burst.js`. It should implement the scout→read→plan→diverse-panel(REWORK ≥2)→coder-in-worktree→adversarial-verify shape with the `resolveModel` seam (see Step 2) and the config-driven invariants injection (see Steps 3–4). Do not copy project-specific constants, model IDs, paths, or invariants from any existing project's workflow.

- [ ] **Step 2: Add the `resolveModel` seam + role map**

Replace the hardcoded `model: 'haiku'|'sonnet'|'opus'` at every `agent()` call with `resolveModel(role, difficulty)`. Insert near the top, after the args-parse block:

```javascript
// Model role map — Claude defaults; overridable via args.roles. This is the
// single seam a future non-Claude vendor layer slots into without touching call sites.
const DEFAULT_ROLES = {
  scout: 'haiku', reader: 'haiku', planner: 'opus',
  judges: ['opus', 'sonnet', 'haiku'],
  coder: { hard: 'opus', routine: 'sonnet' }, verifier: 'opus',
}
const ROLES = (a.roles && typeof a.roles === 'object') ? { ...DEFAULT_ROLES, ...a.roles } : DEFAULT_ROLES
function resolveModel(role, difficulty) {
  if (role === 'coder') return ROLES.coder[difficulty] || ROLES.coder.routine
  return ROLES[role]
}
```

Then: scout `model: resolveModel('scout')`; readers `resolveModel('reader')`; planner `resolveModel('planner')`; judges iterate `ROLES.judges` (lens list pairs with models by index, cycling if lengths differ); coder `resolveModel('coder', difficulty)`; verifier `resolveModel('verifier')`.

- [ ] **Step 3: Parametrize the repo + drop any hardcoded path**

Replace any hardcoded `const REPO = '<some-path>'` with `const REPO = a.repo || '.'` and change `git -C ${REPO}` to run in the session cwd when `a.repo` is absent (keep `-C ${REPO}` only when `a.repo` is set). `claude -p` runs in the repo dir, so cwd is correct by default.

- [ ] **Step 4: Inject project conventions from args, not hardcoded**

All project-specific invariants in the Plan/Build/Verify prompts come from `a.invariants` / `a.test_cmd` / `a.smoke_instructions` interpolations. Replace any hard-coded language with generic "task spec" / "the project's conventions doc" / "the project's test command (`${a.test_cmd}`)". Keep the scout→read→plan→panel(REWORK≥2)→coder-worktree→verify shape and the fail-loud no-spec guard verbatim.

- [ ] **Step 5: Sanity-check the JS parses**

Run: `node --check ~/Projects/multi-ship/workflows/mixed-model-burst.js`
Expected: no output (exit 0).

- [ ] **Step 6: Commit**

```bash
git add workflows/mixed-model-burst.js
git commit -m "feat: generic, model-parametrized mixed-model-burst workflow"
```

---

## Task 14: `install.sh`

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Write `install.sh` (idempotent symlink installer)**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DST="${HOME}/.claude/skills"
BIN_DST="${HOME}/.local/bin"
mkdir -p "$SKILLS_DST" "$BIN_DST"

for dep in python3 claude gh; do
  command -v "$dep" >/dev/null 2>&1 || { echo "WARN: '$dep' not found on PATH"; }
done

for d in "$ROOT"/skills/*/; do
  name="$(basename "$d")"; dst="$SKILLS_DST/$name"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "SKIP $name: a non-symlink skill already exists at $dst — remove it first"; continue
  fi
  ln -sfn "$d" "$dst"; echo "linked skill: $name"
done

ln -sfn "$ROOT/bin/multi-ship" "$BIN_DST/multi-ship"; echo "linked bin: $BIN_DST/multi-ship"
case ":$PATH:" in *":$BIN_DST:"*) ;; *) echo "ADD TO PATH: export PATH=\"$BIN_DST:\$PATH\"";; esac
echo "done. Per-repo setup: cd <repo> && multi-ship init"
```

```bash
chmod +x install.sh
```

- [ ] **Step 2: Dry-run verify (linking is idempotent)**

Run: `~/Projects/multi-ship/install.sh && ~/Projects/multi-ship/install.sh`
Expected: second run re-links without error; prints `linked skill:` lines + bin link.

- [ ] **Step 3: Commit**

```bash
git add install.sh && git commit -m "feat: idempotent symlink installer"
```

---

## Task 15: `templates/multi-ship.json`

**Files:**
- Create: `templates/multi-ship.json`

- [ ] **Step 1: Write the neutral-placeholder template**

```json
{
  "build_workflow": "mixed-model-burst",
  "spec_glob": "docs/specs/*.md",
  "verify": "gh pr checks $PR --watch",
  "notify": "echo NOTIFY:",
  "pr_body_convention": "Closes #{issue}",
  "complete_cmd": "/complete-spec {slug}",
  "test_cmd": "<your project's test command, e.g. pytest -x>",
  "build_invariants": "<one paragraph of your project's must-honor invariants>",
  "smoke_instructions": "<how to exercise a new code path end-to-end>",
  "roles": {
    "scout": "haiku", "reader": "haiku", "planner": "opus",
    "judges": ["opus", "sonnet", "haiku"],
    "coder": {"hard": "opus", "routine": "sonnet"}, "verifier": "opus"
  }
}
```

- [ ] **Step 2: Re-run the init test (now unblocked)**

Run: `PYTHONPATH=src pytest tests/test_cli_init.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add templates/multi-ship.json
git commit -m "feat: per-project config template"
```

---

## Task 16: `README.md`

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

Sections: (1) What it is + the one-line pitch; (2) Why — the context-bloat problem + the fresh-`claude -p`-per-item inversion; (3) **The MiMo relationship & honesty box** — patterns are model-agnostic and portable, this implementation runs on Claude Code, true cross-vendor is a documented future seam; (4) Install (`git clone` + `./install.sh`); (5) Per-repo `multi-ship init` + the config reference table (every key); (6) The role→model map + how to override; (7) Usage (`multi-ship docs/specs/*.md`, `--resume`, `--continue-on-failure`); (8) How it works (the loop diagram from DESIGN.md); (9) A worked example config for a real Python project; (10) Limitations (Claude-Code-bound; macOS `caffeinate`; needs `gh`); (11) License (MIT).

- [ ] **Step 2: Commit**

```bash
git add README.md && git commit -m "docs: README with honest portability framing"
```

---

## Task 17: CI workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Write the CI workflow**

```yaml
name: test
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pytest
      - run: PYTHONPATH=src pytest -v
```

- [ ] **Step 2: Verify locally**

Run: `cd ~/Projects/multi-ship && PYTHONPATH=src pytest -v`
Expected: PASS (all suites)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml && git commit -m "ci: pytest on push/PR"
```

---

## Task 18: Live smoke on a real repo

**Files:** none (operational verification)

- [ ] **Step 1: Install + init the target repo**

```bash
~/Projects/multi-ship/install.sh
cd ~/Projects/your-repo && multi-ship init
```

- [ ] **Step 2: Fill the config for the target repo**

Edit `.claude/multi-ship.json` in the target repo: set `notify` to your notify command (e.g. a Telegram/Slack webhook script), `test_cmd` to your project's test command (e.g. `ruff check . && mypy . && pytest -x`), `build_invariants` and `smoke_instructions` from your project's CLAUDE.md or equivalent conventions doc.

- [ ] **Step 3: Dry-run on ONE trivial real spec**

Pick the smallest open spec (or a throwaway doc-only spec). Run `multi-ship docs/specs/<trivial>.md`. Observe: caffeinate starts, `ship-one` builds + opens a PR + pauses, `judge-shipped` writes a verdict, the driver merges on ok, run-log shows `shipped`, `dream-run` either runs or logs "nothing durable."

- [ ] **Step 4: Confirm the artifacts**

Check `.multi-ship/run-log.json` (item shipped), `HANDOFF.md` (populated), and that the PR merged with `Closes #N`. If the judge rejected, confirm the one-fix-retry fired.

- [ ] **Step 5: Record the smoke result in the README's "tested against" note + commit**

```bash
git -C ~/Projects/multi-ship add README.md
git -C ~/Projects/multi-ship commit -m "docs: record first live smoke"
```

---

## Self-Review

**Spec coverage:**
- Driver pure logic (config/runlog/resume/stop/dream-gate) → Tasks 2–5. ✓
- Fresh-`claude -p`-per-item loop + cold-judge + 1 fix retry + deterministic merge → Tasks 6–7. ✓
- CLI + `init` + bin shim → Task 8. ✓
- Steal ① HANDOFF schema → Task 5 (scaffold) + Task 9 (ship-one writes it). ✓
- Steal ② judge-shipped → Task 10 + driver gate (Task 7). ✓
- Steal ③ dream-run (explicit + gated-auto, proposals only) → Task 11 + gate (Tasks 4,7). ✓
- Unify (thin autonomous-session/multi-ship) → Task 12. ✓
- Generic model-parametrized workflow (resolveModel seam, args.repo, config invariants) → Task 13. ✓
- OSS packaging: MIT, installer, init, template, README, CI → Tasks 1,14,15,16,17. ✓
- Live smoke → Task 18. ✓
- Hard-rules-become-code (run-log fail-closed, stop-on-failure, follow-up number last, dirty-state snapshot) → run-log fail-closed (Task 3) + stop routing (Tasks 4,7). NOTE: follow-up-spec consolidation + dirty-state snapshot + per-item operator checklist + notify are referenced in `_end_of_run` (Task 7) but their full implementation is light — see gap below.

**Gap found (fix in execution):** Task 7's `_end_of_run` stubs follow-up-spec consolidation, the dirty-state snapshot/assert, and the structured notify. Add a **Task 7b** during execution: TDD `_followups_from_items()` (collect FOLLOWUPS across item reports, allocate spec number last by re-scanning the index), `_assert_parent_clean()` (snapshot HEAD + porcelain at start, assert unchanged after each merge), and `_notify()` (format the end-of-run report incl. per-item operator checklist, shell `cfg.notify`). These are pure-logic-testable like Tasks 4–5.

**Placeholder scan:** template `multi-ship.json` uses `<...>` placeholders *by design* (it's a template the operator fills). No placeholders in code/tests.

**Type consistency:** `Config` fields match between `config.py` (Task 2), the driver `_cfg()` test fixture (Task 7), and the template keys (Task 15). `set_item_status`/`next_item`/`should_stop`/`worth_dreaming` signatures consistent between Tasks 3–4 and their callers in Task 7. `claude_cli.run(prompt, repo, timeout)` consistent between Task 6 and Task 7.
