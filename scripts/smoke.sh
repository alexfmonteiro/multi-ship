#!/usr/bin/env bash
# Fast, dependency-free verification gate for multi-ship: the full unit suite.
# No network, no `claude`/`gh` calls — every external surface is monkeypatched.
# Every task in a plan-driven change must keep this green.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m pytest -q "$@"
