"""Load + validate a project's .claude/multi-ship.json."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
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
    notify_telegram: dict = field(default_factory=dict)

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
    kwargs = {k: data[k] for k in _REQUIRED_KEYS}
    if "notify_telegram" in data:
        kwargs["notify_telegram"] = data["notify_telegram"]
    return Config(**kwargs)
