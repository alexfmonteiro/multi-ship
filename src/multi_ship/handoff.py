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
