# Examples — ship your first spec in ~2 minutes

The fastest way to trust multi-ship is to watch it ship one trivial, real PR.
`specs/add-greeting.md` is built for exactly that: a single pure function with a
crisp Definition of Done the cold judge can verify.

## Run it

From a repo you own and have already set up (`multi-ship init`, then fill in
`verify` / `test_cmd` / `notify` in `.claude/multi-ship.json`):

```bash
# copy the example spec into your repo's spec folder, then:
multi-ship path/to/add-greeting.md
```

What you should see:

1. A fresh `claude -p` session builds the function + tests in an isolated worktree.
2. A PR opens; the driver watches CI to cold-green.
3. A **separate cold** `claude -p` judge reads only the spec's DoD + the PR diff
   and returns a verdict.
4. On `ok: true`, the driver squash-merges. On `ok: false`, it gets exactly one
   fix-retry, then stops without merging.

If that PR lands green, your config is correct and you can point multi-ship at a
real backlog with confidence.

## A worked config

See [`multi-ship.json`](./multi-ship.json) for a filled-in config for a typical
Python project (pytest + `gh`). Copy it to `.claude/multi-ship.json` and adapt
`test_cmd`, `verify`, and `notify` to your project.
