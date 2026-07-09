# Promotion & launch kit

Ready-to-use copy and a checklist for getting multi-ship discovered. Work the
list top-to-bottom; the highest-leverage moves are first.

---

## The positioning (read this first)

multi-ship sits at the intersection of three live 2026 narratives. Lead with
whichever one fits the channel — don't force a single pitch everywhere.

| # | Narrative (the buzzword) | The pain it names | multi-ship's answer | Best channels |
|---|---|---|---|---|
| **1** | **Verification is the bottleneck** / "agent slop" | Agents open PRs faster than humans can decide whether to trust them. Review time balloons; unread merges become normal; code carries no recoverable intent. | A **cold judge** gates every merge — sees only the spec's DoD + PR diff + CI, never the builder's transcript. Nothing merges red; nothing merges unjudged. | LinkedIn, X, awesome-lists, blog/dev.to, eng-leadership audiences |
| **2** | **The orchestration era** / "delegation gap" | Devs use AI for ~60% of work but can fully delegate only 0–20% (Anthropic's 2026 report). The gap is trust + oversight at the merge boundary. | A thin driver that owns the loop, gives each item its own context, and only delegates the *merge decision* to an independent gate. | HN, Reddit, anywhere citing the Anthropic report |
| **3** | **Context rot** / "an agent can't `/clear` itself" | Long autonomous Claude Code runs bloat, bleed stale reasoning between tasks, and lose everything on a crash. | Invert the loop: every work item gets a fresh `claude -p`; cross-item memory lives on disk, not in a bloated window. | HN (contrarian hook), Anthropic Discord, r/ClaudeCode power users |

**Rule of thumb:** narrative #1 (the merge gate) is the broadest-resonating and
should lead the README, the repo description, and LinkedIn/X. Narrative #3 (the
context-rot inversion) is the most *contrarian* and makes the best Show HN hook.
Narrative #2 is the bridge — it lets you newsjack the Anthropic report (see §5).

**Buzzwords to use deliberately** (they are what people search and nod along to):
verification bottleneck · agent slop · missing intent · cold judge · merge gate ·
spec-driven development (SDD) · delegation gap · orchestration era · multi-agent
orchestration · agentic coding · fresh context per item · context engineering.

---

## 0. Pre-launch repo hygiene (do this first)

These make the repo *look* like a real project the moment someone lands on it.

- [ ] **Record the demo GIF** ([docs/demo.md](demo.md)) and embed it at the top of
      the README. Nothing else moves the needle as much. Capture the money shot: a
      **judge rejecting a PR**, then the fix-retry, then the merge — that's the
      whole pitch in 15 seconds.
- [ ] **Set the repo description** (GitHub → About):
      `Ship a spec backlog autonomously on Claude Code — an independent cold judge gates every merge (sees only the spec DoD + PR diff). Fresh context per item, on-disk handoff memory. MIT.`
- [ ] **Add topics** (GitHub → About → ⚙):
      `claude-code` `ai-agents` `autonomous-agents` `agentic-coding`
      `spec-driven-development` `ai-code-review` `llm-orchestration`
      `agent-orchestration` `multi-agent` `code-generation` `developer-tools`
      `cli` `python`
      *(new vs the old list: `agentic-coding`, `spec-driven-development`,
      `ai-code-review`, `multi-agent` — all high-traffic 2026 search terms.)*
- [ ] **Upload a social preview image** (Settings → Social preview, 1280×640) so
      links unfurl with a card, not a blank box. Put the merge-gate line on it.
- [ ] **Pin the repo** on your GitHub profile.
- [ ] **Create 3–5 starter issues** labeled `good first issue` (see §6) — an empty
      issue tracker reads as abandoned; a few scoped issues read as alive.

---

## 1. Get listed on the awesome-lists (highest ROI, lowest effort)

These curated lists are where Claude Code and agentic-coding users actually browse
for tools. Open a PR adding multi-ship under the orchestration/agents category:

- [ ] [`hesreallyhim/awesome-claude-code`](https://github.com/hesreallyhim/awesome-claude-code) — agent orchestrators
- [ ] [`VoltAgent/awesome-agent-skills`](https://github.com/VoltAgent/awesome-agent-skills)
- [ ] [`ComposioHQ/awesome-claude-skills`](https://github.com/ComposioHQ/awesome-claude-skills)
- [ ] [`travisvn/awesome-claude-skills`](https://github.com/travisvn/awesome-claude-skills)
- [ ] **Spec-driven-development lists** — SDD is now its own category with curated
      maps (Spec Kit, OpenSpec, GSD, Tessl, …). Find the active "awesome-spec-driven"
      / "awesome-agentic-coding" lists and PR multi-ship in as the *autonomous
      executor + merge-gate* entry — a niche none of the spec-authoring tools fill.

**Suggested list entry:**

> **[multi-ship](https://github.com/alexfmonteiro/multi-ship)** — Ship a backlog
> of specs autonomously: a thin driver gives every work item its own `claude -p`
> (fresh context, no session rot), with an independent **cold-judge merge gate**
> (reads only the spec's Definition of Done + PR diff) before each squash-merge,
> and on-disk handoff memory between items.

Follow each list's CONTRIBUTING format exactly (alphabetical order, link style,
etc.) so the PR merges without friction.

---

> A full, publish-ready announcement post (blog / dev.to / Show HN body) lives in
> [docs/launch-post.md](launch-post.md) — post it as the canonical write-up and
> link it from the channels below.

## 2. Show HN / Hacker News

HN rewards a contrarian, insight-first hook. Lead with the context-rot inversion
(narrative #3); the merge gate is the payoff in the body.

Title options (A/B — pick the one that feels least like an ad):

> **Show HN: Claude Code can't clear its own context, so I inverted the loop**

> **Show HN: An independent cold judge gates every autonomous merge (so nothing ships unjudged)**

Body:

> Long autonomous Claude Code sessions rot — after a handful of items the context
> is bloated, stale reasoning bleeds between tasks, and a crash wipes progress.
> And a Claude Code session can't `/clear` or `/compact` itself; the only
> guaranteed reset is a fresh `claude -p`.
>
> multi-ship moves the loop out of the session into a ~400-line Python driver and
> gives every work item its own `claude -p` — a clean slate per item. Cross-item
> memory lives on disk in a fixed-schema handoff doc. But the part I think
> actually matters in 2026 is the merge gate: code generation isn't the
> bottleneck anymore, verification is. So before each merge an independent **cold
> judge** (a separate model call that sees only the spec's Definition of Done and
> the PR diff — never the builder's transcript) decides whether the work shipped.
> The driver merges only on approval and never merges red. The model that wrote
> the code can't talk the judge into accepting it.
>
> The driver is deliberately dumb — it routes only on status/verdict files and
> never reasons about code, so every judgment is a fresh, cold model call. MIT,
> macOS + Linux. Honest caveat: it runs on Claude Code today; the patterns port
> across vendors but this implementation doesn't (yet).
>
> Repo: https://github.com/alexfmonteiro/multi-ship

Post Tue–Thu, ~9–11am ET. Reply to every comment in the first two hours. Expect
the top comment to be about the verification angle — have the "agent slop /
missing intent" framing ready.

---

## 3. Reddit / X / LinkedIn / Discord

**r/ClaudeCode** (~292k) and **r/ClaudeWorkflows** are the bullseye — the exact
"orchestrating sub-agents with isolated environments and automated gates" audience
multi-ship serves. Also **r/ClaudeAI** (~960k) and **r/ChatGPTCoding**.

> **Title:** I got tired of autonomous runs merging slop, so an independent cold
> judge now gates every merge
>
> Short body: the verification-bottleneck framing (generation is cheap, deciding
> whether to trust the PR isn't), the cold-judge gate (sees only DoD + diff), and
> the fresh-`claude -p`-per-item fix for context rot. Link the repo + demo GIF.
> Lead with the GIF if the sub allows images. In r/ClaudeWorkflows, frame it as a
> *workflow* and lead with the worktree-isolation + automated-gate mechanics.

**X/Twitter thread** (1 hook + beats + repo link):

> 1/ Code generation stopped being the bottleneck. Verification is. Autonomous
> agents open PRs faster than anyone can decide whether to trust them — so "agent
> slop" merges unread.
> 2/ multi-ship puts a gate in front of every merge: an independent COLD judge
> that sees only the spec's Definition of Done + the PR diff. Never the builder's
> transcript. It votes ok/not-ok. Nothing merges red. Nothing merges unjudged.
> 3/ The builds stay clean because each task gets its own `claude -p` — a fresh
> context, like an automatic /clear between tasks. (A Claude Code session can't
> clear itself; the only reset is a new process.)
> 4/ Memory that *should* cross tasks lives on disk in a fixed-schema handoff doc,
> not a bloated window.
> 5/ Deterministic Python routes; every judgment is a fresh, cold model call. MIT,
> macOS + Linux: [repo link] + demo GIF.

**LinkedIn** (eng-leadership audience — lead with the report, see §5). The
delegation-gap framing lands hardest with managers weighing oversight vs speed.

**Anthropic Discord** (#share-your-work or similar) — drop the GIF + one-liner +
repo link. Don't spam multiple channels.

---

## 4. Comparison / "where it fits" content (own a search lane)

People evaluating SDD tools search for comparisons. Publish one short, honest
positioning post and link it everywhere:

- [ ] **"Spec-authoring vs spec-executing"** — most SDD tools (Spec Kit, OpenSpec,
      GSD) help you *write* specs. multi-ship *executes* a backlog of finished
      specs and gates the merge. Frame it as complementary, not competitive: write
      specs however you like → multi-ship ships them. This captures the "X vs
      multi-ship" and "multi-ship alternative" long-tail with zero contention.
- [ ] Turn it into a one-paragraph FAQ entry in the README too (see §7).

---

## 5. Newsjack the Anthropic 2026 Agentic Coding Trends Report

The report is *the* canonical reference everyone is citing — its "delegation gap"
(60% AI use, 0–20% full delegation) and "orchestration era" framing are doing the
narrative work for you. Ride it:

- [ ] **Blog / LinkedIn post:** "Anthropic says we're in the orchestration era and
      the delegation gap is the story. The gap is *trust at the merge boundary* —
      here's a ~400-line driver that closes it with a cold-judge gate." Quote the
      report's stat, then show the gate. This is the single highest-leverage
      LinkedIn move because the report gives you instant credibility and context.
- [ ] Drop the same framing as a comment on threads discussing the report.

---

## 6. Starter issues to file (signals an active project + invites contributors)

- `good first issue`: Add a GitHub Actions usage recipe to the README (run a
  backlog in CI).
- `good first issue`: `multi-ship status` — pretty-print the current run-log.
- `good first issue`: Windows sleep-inhibitor support (`SetThreadExecutionState`).
- `help wanted`: Within-run parallelism for independent specs.
- `help wanted` / discussion: Cross-vendor provider layer at the `resolveModel`
  seam (GPT/Gemini/local).

---

## 7. After launch

- [ ] Add a `## Star history` chart (star-history.com) once you have traction.
- [x] ~~Bundle skills so a wheel install works without a clone~~ — done; the wheel
      force-includes skills/templates/workflows. `pipx install git+…` works today.
- [ ] **Publish to PyPI** so `pipx install multi-ship` works without the `git+`
      prefix. The wheel is ready — follow [docs/PUBLISHING.md](PUBLISHING.md).
- [x] ~~Package as a Claude Code plugin~~ — done; `.claude-plugin/` ships a plugin
      manifest + self-hosted marketplace (`claude plugin validate . --strict`
      passes). Promote the marketplace install line (below).
- [ ] **Submit to a third-party plugin marketplace** for extra discovery (PR an
      entry pointing at `{ "source": "github", "repo": "alexfmonteiro/multi-ship" }`).
- [ ] Turn the best HN/Reddit comments — and the "spec-authoring vs executing"
      question — into a short FAQ in the README.

**Plugin install line to include in posts:**

```text
/plugin marketplace add alexfmonteiro/multi-ship
/plugin install multi-ship@multi-ship
```
