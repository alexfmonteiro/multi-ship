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

def next_item(log: dict, skip: set | None = None) -> str | None:
    """First non-shipped item id not in `skip` (failed items are retried on resume,
    when skip is empty; within a single run the loop passes the attempted set)."""
    skip = skip or set()
    for it in log["items"]:
        if it["status"] != "shipped" and it["id"] not in skip:
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
