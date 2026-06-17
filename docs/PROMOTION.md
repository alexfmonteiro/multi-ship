# Promotion & launch kit

Ready-to-use copy and a checklist for getting multi-ship discovered. Work the
list top-to-bottom; the highest-leverage moves are first.

---

## 0. Pre-launch repo hygiene (do this first)

These make the repo *look* like a real project the moment someone lands on it.

- [ ] **Record the demo GIF** ([docs/demo.md](demo.md)) and embed it at the top of
      the README. Nothing else moves the needle as much.
- [ ] **Set the repo description** (GitHub → About):
      `Ship a backlog of specs autonomously on Claude Code — one fresh context per item, cold-judge merge gate, on-disk handoff memory. MIT.`
- [ ] **Add topics** (GitHub → About → ⚙):
      `claude-code` `ai-agents` `autonomous-agents` `llm-orchestration`
      `agent-orchestration` `code-generation` `developer-tools` `cli` `python`
- [ ] **Upload a social preview image** (Settings → Social preview, 1280×640) so
      links unfurl with a card, not a blank box.
- [ ] **Pin the repo** on your GitHub profile.
- [ ] **Create 3–5 starter issues** labeled `good first issue` (see §4) — an empty
      issue tracker reads as abandoned; a few scoped issues read as alive.

---

## 1. Get listed on the awesome-lists (highest ROI, lowest effort)

These curated lists are where Claude Code users actually browse for tools. Open a
PR adding multi-ship under the orchestration/agents category of each:

- [ ] [`hesreallyhim/awesome-claude-code`](https://github.com/hesreallyhim/awesome-claude-code) — agent orchestrators
- [ ] [`VoltAgent/awesome-agent-skills`](https://github.com/VoltAgent/awesome-agent-skills)
- [ ] [`ComposioHQ/awesome-claude-skills`](https://github.com/ComposioHQ/awesome-claude-skills)
- [ ] [`travisvn/awesome-claude-skills`](https://github.com/travisvn/awesome-claude-skills)

**Suggested list entry:**

> **[multi-ship](https://github.com/alexfmonteiro/multi-ship)** — Ship a backlog
> of specs autonomously: a thin driver gives every work item its own `claude -p`
> (fresh context, no session rot), with an independent cold-judge gate before each
> squash-merge and on-disk handoff memory between items.

Follow each list's CONTRIBUTING format exactly (alphabetical order, link style,
etc.) so the PR merges without friction.

---

## 2. Show HN / Hacker News

Title (lead with the insight, not the product name):

> **Show HN: Claude Code can't clear its own context, so I inverted the loop**

Body:

> Long autonomous Claude Code sessions rot — after a handful of items the context
> is bloated, stale reasoning bleeds between tasks, and a crash wipes progress.
> And a Claude Code session can't `/clear` or `/compact` itself; the only
> guaranteed reset is a fresh `claude -p`.
>
> multi-ship moves the loop out of the session into a ~400-line Python driver and
> gives every work item its own `claude -p` — a clean slate per item. Cross-item
> memory lives on disk in a fixed-schema handoff doc. Before each merge an
> independent cold judge (a separate model call that sees only the spec's
> Definition of Done and the PR diff) decides whether the work actually shipped;
> the driver merges only on approval and never merges red.
>
> The driver is deliberately dumb — it routes only on status/verdict files and
> never reasons about code, so every judgment is a fresh, cold model call. MIT,
> macOS + Linux. Honest caveat: it runs on Claude Code today; the patterns port
> across vendors but this implementation doesn't (yet).
>
> Repo: https://github.com/alexfmonteiro/multi-ship

Post Tue–Thu, ~9–11am ET. Reply to every comment in the first two hours.

---

## 3. Reddit / X / Discord

**r/ClaudeAI** (and r/ChatGPTCoding) — same insight-first angle:

> **Title:** I got tired of long Claude Code runs rotting, so each task now gets
> its own fresh context
>
> Short body explaining the context-rot problem, the fresh-`claude -p`-per-item
> fix, and the cold-judge merge gate. Link the repo and the demo GIF. Lead with
> the GIF if the sub allows images.

**X/Twitter thread** (1 hook + 3–4 beats + repo link):

> 1/ Claude Code can't clear its own context. So on a long autonomous run, task #9
> is dragging task #1's stale reasoning around — and one crash wipes everything.
> 2/ Fix: stop fighting the session. Move the loop into a tiny driver and give
> every task its own `claude -p`. Fresh context per item. Like an automatic
> /clear between tasks.
> 3/ Memory that *should* cross tasks lives on disk in a fixed-schema handoff doc
> — not in a bloated context window.
> 4/ Before every merge, an independent COLD judge sees only the spec's DoD + the
> PR diff and votes ok/not-ok. Nothing merges red. Nothing merges unjudged.
> 5/ MIT, macOS + Linux: [repo link] + demo GIF.

**Anthropic Discord** (#share-your-work or similar) — drop the GIF + one-liner +
repo link. Don't spam multiple channels.

---

## 4. Starter issues to file (signals an active project + invites contributors)

- `good first issue`: Add a GitHub Actions usage recipe to the README (run a
  backlog in CI).
- `good first issue`: `multi-ship status` — pretty-print the current run-log.
- `good first issue`: Windows sleep-inhibitor support (`SetThreadExecutionState`).
- `help wanted`: Within-run parallelism for independent specs.
- `help wanted` / discussion: Cross-vendor provider layer at the `resolveModel`
  seam (GPT/Gemini/local).

---

## 5. After launch

- [ ] Add a `## Star history` chart (star-history.com) once you have traction.
- [ ] Publish to **PyPI** so `pipx install multi-ship` works without a clone
      (bundle skills as package data first, then update the Quickstart).
- [ ] Package as a **Claude Code plugin** for marketplace install.
- [ ] Turn the best HN/Reddit comments into a short FAQ in the README.
