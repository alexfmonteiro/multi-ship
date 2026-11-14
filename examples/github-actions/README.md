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
   - `notify`: `cat` — the end-of-run summary is piped to the command's
     **stdin**, so `echo` would silently discard it. For a ping, use a webhook
     script that reads stdin.
   - `test_cmd`: your project's test command (runs inside the build).
2. Add an `ANTHROPIC_API_KEY` secret (repo or org) for the Claude CLI.
3. Add a `MULTI_SHIP_GH_TOKEN` secret: a fine-grained personal access token or a
   GitHub App installation token scoped to the target repo, with:
   - Contents: read and write (push branches, merge)
   - Pull requests: read and write (open and merge PRs)
   - Checks: read, Commit statuses: read, Actions: read (`gh pr checks`)
   - Workflows: read and write, only if specs may edit `.github/workflows/`

   See [Why not `GITHUB_TOKEN`?](#why-not-github_token).
4. Copy `ship-backlog.yml` into the target repo's `.github/workflows/`.
5. Trigger it from the **Actions** tab → *ship-backlog* → *Run workflow*, choosing
   the spec glob.

## How it works

The job installs the Claude CLI + the `multi-ship` CLI (via `pipx`, no clone),
links the skills with `install-skills --copy`, authenticates `actions/checkout`
and `gh` with `MULTI_SHIP_GH_TOKEN`, and runs `multi-ship <specs>`. The workflow
inputs reach the script through `env:`, not `${{ inputs.* }}` inside `run:`, so a
crafted spec glob can't inject shell code. Each spec gets its own
fresh `claude -p`, the cold judge gates every merge, and `multi-ship status`
prints the per-item table at the end.

## Why not `GITHUB_TOKEN`?

GitHub doesn't start workflow runs for events caused by the built-in
`GITHUB_TOKEN` (except `workflow_dispatch` and `repository_dispatch`). With it,
the branches multi-ship pushes and the PRs it opens get no CI. `verify` then sees
no checks, the judge rejects the PR, and required status checks block the merge.
A PAT or App token doesn't have this limit, so the target repo's CI runs as usual.

## Safety

This runs Claude with `bypassPermissions` and **merges PRs autonomously**. Treat
it like any powerful automation:

- Start with **one trivial spec** (see [`../specs/add-greeting.md`](../specs/add-greeting.md)).
- Keep the default branch **protected** with required checks so nothing merges red.
- The `permissions:` block is scoped to `contents` + `pull-requests`; don't widen
  it. Give `MULTI_SHIP_GH_TOKEN` only the permissions listed above, on this repo
  only. Prefer a dedicated environment with required reviewers for first runs.
- Use `workflow_dispatch` (manual) rather than a schedule until you trust it.
