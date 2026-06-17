---
Issue: 0
Difficulty: routine
---

# Spec: add a `greeting()` helper

A deliberately tiny spec to prove your multi-ship setup end-to-end on a real
PR before you point it at a real backlog.

## Goal

Add a single pure function the project can import and test.

## Definition of Done

- [ ] A function `greeting(name: str) -> str` exists in the project's source tree.
- [ ] `greeting("world")` returns the exact string `"Hello, world!"`.
- [ ] A unit test covers both a normal name and an empty string.
- [ ] The project's test command passes.

## Notes

- Keep it dependency-free and pure (no I/O, no globals).
- Put it wherever the project's other small helpers live; match the surrounding
  style.
