# Launch post (ready to publish)

A complete announcement post for a blog / dev.to / the body of a Show HN. Lead
with the demo GIF once you've recorded it. Title options are at the bottom.

---

## Claude Code can't clear its own context. So I inverted the loop.

If you've run Claude Code on a long autonomous task, you've felt this: somewhere
around the eighth or ninth work item, it starts getting worse. Earlier reasoning
bleeds into unrelated tasks. The context window is bloated with stale tool
output. And if the process dies, every bit of progress dies with it.

The obvious fix would be to clear the context between tasks. But here's the catch
that sent me down this rabbit hole: **a Claude Code session cannot clear or
compact its own context.** `/clear` and `/compact` are user-only gestures. Hooks
can't spawn fresh sessions. `--resume` and `--continue` deliberately *reuse* the
old history. From inside the session, there is no reset button.

The only thing that gives you a guaranteed clean slate is a brand-new `claude -p`
invocation.

So instead of fighting the session, I stopped putting the loop *inside* it.

### Invert the loop

[multi-ship](https://github.com/alexfmonteiro/multi-ship) moves orchestration out
of the Claude session into a thin (~400-line) Python driver. The driver owns the
backlog, and it gives **every work item its own `claude -p`** — a fresh context,
like an automatic `/clear` between tasks. Item nine starts exactly as clean as
item one.

The memory that genuinely *should* carry across items doesn't live in a context
window at all — it lives on disk, in a fixed-schema handoff doc the driver feeds
into each new session. Durable facts, errors-and-fixes, design decisions. The
stuff you want to remember, kept; the conversational sludge, dropped.

### The driver is deliberately dumb

The driver never reasons about code. It routes purely on small status files that
each session writes. Build succeeded or failed? Read a JSON file. Did the work
actually satisfy the spec? That's not the driver's call either — it shells out to
a **separate, cold `claude -p` judge** that sees *only* the spec's Definition of
Done and the PR diff. Never the builder's transcript. So the model that wrote the
code can't talk the judge into approving it.

The driver merges only when the judge says yes, and it never merges red. A
rejected item gets exactly one fix-retry, then the run stops and pings you.
Nothing half-shipped gets left merged.

Every decision that needs judgment is a fresh, cold model call. Everything
deterministic is boring Python. That split is the whole design.

### What it looks like

```bash
pipx install git+https://github.com/alexfmonteiro/multi-ship.git
multi-ship install-skills

cd your-repo
multi-ship init                 # one-time config
multi-ship docs/specs/*.md      # ship the backlog, hands-free
```

Each spec: fresh context → build in an isolated worktree → open a PR → drive CI
to green → cold judge → squash-merge → next item, clean slate. At the end you get
a status table and a notification. It runs on macOS and Linux, and there's a
GitHub Actions recipe if you'd rather ship a backlog in CI than tie up your
laptop.

### The honest caveat

This runs on Claude Code today. The orchestration *patterns* — fresh context per
item, on-disk handoff memory, a cold-judge stop-gate — are model-agnostic and
were shaped by Xiaomi's MiMo Code. But this *implementation* shells `claude -p`
and uses Claude Code's skills and workflow engine. There's a seam where a
cross-vendor provider layer would slot in; it isn't built yet. If you need
vendor-agnostic orchestration this week, take the patterns, not the code.

It's MIT. If the context-rot problem is one you've hit, I'd love a star and your
sharpest feedback: **https://github.com/alexfmonteiro/multi-ship**

---

### Title options

- *Claude Code can't clear its own context, so I inverted the loop*
- *I got tired of long Claude runs rotting — now every task gets a fresh context*
- *Shipping a backlog hands-free with fresh-context-per-item + a cold judge gate*

### Where to post

dev.to / personal blog (canonical) → then link it from Show HN, r/ClaudeAI, and
the X thread in [PROMOTION.md](PROMOTION.md). Reply to every comment in the first
two hours.
