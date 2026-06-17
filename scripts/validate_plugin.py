#!/usr/bin/env python3
"""Static validation for the Claude Code plugin + marketplace manifests and the
PyPI metadata. Runs in CI with no external dependencies and no auth, so it can be
a blocking guard. For the official check, run `claude plugin validate . --strict`
locally (see docs/PUBLISHING.md) — that needs the authenticated Claude CLI, which
CI does not have.

Checks:
  - .claude-plugin/plugin.json and marketplace.json parse and carry required keys
  - the marketplace's single plugin source resolves to the repo root
  - every skills/<name>/ has a SKILL.md
  - version is identical across pyproject.toml, plugin.json, marketplace.json
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        err(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as e:
        err(f"invalid JSON in {path.relative_to(ROOT)}: {e}")
    return {}


def pyproject_version() -> str | None:
    text = (ROOT / "pyproject.toml").read_text()
    # [project] version = "x.y.z" — regex avoids a tomllib dep (3.9 has none).
    m = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def main() -> int:
    plugin = load_json(ROOT / ".claude-plugin" / "plugin.json")
    market = load_json(ROOT / ".claude-plugin" / "marketplace.json")

    if plugin and "name" not in plugin:
        err("plugin.json: missing required key 'name'")

    for key in ("name", "owner", "plugins"):
        if market and key not in market:
            err(f"marketplace.json: missing required key '{key}'")
    plugins = market.get("plugins", [])
    if market and not isinstance(plugins, list) or not plugins:
        err("marketplace.json: 'plugins' must be a non-empty list")
    else:
        for p in plugins:
            if "name" not in p or "source" not in p:
                err(f"marketplace.json: plugin entry needs 'name' and 'source': {p}")
            src = p.get("source")
            if isinstance(src, str) and not (ROOT / src).is_dir():
                err(f"marketplace.json: source path does not resolve: {src!r}")

    skills_dir = ROOT / "skills"
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        if not (d / "SKILL.md").exists():
            err(f"skills/{d.name}/ has no SKILL.md")

    versions = {
        "pyproject.toml": pyproject_version(),
        "plugin.json": plugin.get("version"),
        "marketplace.json": (plugins[0].get("version") if plugins else None),
    }
    distinct = {v for v in versions.values() if v is not None}
    if len(distinct) > 1:
        err(f"version mismatch across manifests: {versions}")

    if errors:
        print("PLUGIN VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"plugin manifests OK (version {distinct.pop() if distinct else '?'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
