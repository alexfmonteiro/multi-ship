# Run multi-ship in GitHub Actions

Because the driver is now cross-platform (it uses `systemd-inhibit` on Linux, or
no-ops cleanly), you can run a whole backlog **unattended in CI** instead of
tying up your laptop. [`ship-backlog.yml`](./ship-backlog.yml) is a ready-to-copy
workflow.

## Setup

1. In the **target repo** (the one you want PRs shipped into), run
   `multi-ship init` and fill in `.claude/multi-ship.json`. For CI:
   - `verify`: a command that blocks until checks finish, e.g.
     `gh pr checks $PR --watch`.
   - `notify`: `echo` (or a webhook `curl` if you want a ping).
   - `test_cmd`: your project's test command (runs inside the build).
2. Add an `ANTHROPIC_API_KEY` secret (repo or org) for the Claude CLI.
3. Copy `ship-backlog.yml` into the target repo's `.github/workflows/`.
4. Trigger it from the **Actions** tab → *ship-backlog* → *Run workflow*, choosing
   the spec glob.

## How it works

The job installs the Claude CLI + the `multi-ship` CLI (via `pipx`, no clone),
links the skills with `install-skills --copy`, authenticates `gh` with the
built-in `GITHUB_TOKEN`, and runs `multi-ship <specs>`. Each spec gets its own
fresh `claude -p`, the cold judge gates every merge, and `multi-ship status`
prints the per-item table at the end.

## Safety

This runs Claude with `bypassPermissions` and **merges PRs autonomously**. Treat
it like any powerful automation:

- Start with **one trivial spec** (see [`../specs/add-greeting.md`](../specs/add-greeting.md)).
- Keep the default branch **protected** with required checks so nothing merges red.
- The `permissions:` block is scoped to `contents` + `pull-requests`; don't widen
  it. Prefer a dedicated environment with required reviewers for first runs.
- Use `workflow_dispatch` (manual) rather than a schedule until you trust it.
