# [SMOKE] Add a CHANGELOG

Difficulty: routine

## Goal

Add a top-level `CHANGELOG.md` documenting the v0.1.0 initial release. This is a
doc-only change used to exercise the multi-ship pipeline end-to-end.

## Definition of Done

- A new file `CHANGELOG.md` exists at the repo root.
- It contains a `## v0.1.0` heading with at least one bullet describing the initial
  release (autonomous multi-spec shipping CLI for Claude Code).
- No source files or tests are modified.
- `PYTHONPATH=src pytest -q` still passes unchanged.
