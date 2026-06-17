# Contributing to multi-ship

Thanks for your interest! multi-ship is a small, sharp tool — contributions that
keep it sharp are very welcome.

## Development setup

```bash
git clone https://github.com/alexfmonteiro/multi-ship.git
cd multi-ship
pip install -e .
pip install pytest
PYTHONPATH=src pytest -v
```

The driver's pure logic (config parsing, run-log state machine, resume/stop
routing, end-of-run consolidation) is unit-tested and runs without any Claude
calls. **New driver logic should come with a test.** The skills are prompt
contracts — validate changes to them with a live dry-run on a throwaway repo.

## Ground rules

- **The driver stays dumb.** It routes only on `{status}` / `{ok}` files and never
  reasons about code. Anything that needs judgment is a fresh `claude -p`. Keep it
  that way — don't move model reasoning into Python.
- **Fail-closed on build/CI, fail-open on the judge.** Preserve these invariants.
- **No hardcoded model IDs in the workflow.** Everything resolves through
  `resolveModel(role, difficulty)` against the config's `roles` map.
- **Cross-platform.** Don't reintroduce macOS-only assumptions; the sleep
  inhibitor auto-detects the OS (`caffeinate` / `systemd-inhibit` / no-op).

## Good places to help

- Linux/CI polish and a GitHub Actions usage recipe.
- The cross-vendor `resolveModel` provider layer (the deferred big one).
- Within-run parallelism for independent specs.
- A live demo cast / screen recording (see [docs/demo.md](docs/demo.md)).

## Pull requests

1. Branch from `main`.
2. Keep the change focused; update `README.md` / `DESIGN.md` if behavior changes.
3. Make sure `pytest` is green and add tests for new logic.
4. Use clear, conventional-style commit messages.

By contributing you agree your contributions are licensed under the project's
[MIT License](LICENSE).
