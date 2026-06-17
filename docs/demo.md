# Recording the demo

A 30–60s terminal cast is the single highest-leverage asset for this repo —
autonomous agents are show-don't-tell. Here's how to record one and wire it into
the README.

## What to capture

The "wow" is the loop doing real work hands-free. Record a run over **2–3 tiny
specs** so viewers see context reset *between* items:

1. `multi-ship docs/specs/add-greeting.md docs/specs/add-farewell.md`
2. Item 1: fresh `claude -p` builds → PR opens → CI goes green → cold judge says
   `ok` → squash-merge.
3. Item 2 starts with a **clean context** and repeats.
4. End-of-run notify summary prints.

Keep it tight. Trim dead air. The story is "I typed one command and walked away."

## Record with asciinema (recommended)

```bash
brew install asciinema   # or: pipx install asciinema
asciinema rec docs/demo.cast --title "multi-ship: ship a backlog hands-free"
# …run the demo…
# Ctrl-D to stop
```

Embed in the README by uploading (`asciinema upload docs/demo.cast`) and replacing
the demo placeholder with the resulting badge/link, or render to GIF with
[`agg`](https://github.com/asciinema/agg):

```bash
agg docs/demo.cast docs/demo.gif
```

Then in `README.md`, swap the `> **Demo:**` placeholder for:

```markdown
![multi-ship demo](docs/demo.gif)
```

## GIF tips

- Target < 5 MB so it loads inline on GitHub.
- Big, readable font; dark theme; ~80×24.
- Lead with the command, end with the green merge — that's the payoff frame.
