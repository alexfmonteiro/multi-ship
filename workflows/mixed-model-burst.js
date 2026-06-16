export const meta = {
  name: 'mixed-model-burst',
  description:
    'Mixed-model fan-out for a task: Haiku scouts + readers ground the work, Opus plans, a diverse panel stress-tests the plan, then (opt-in) a coder implements in an isolated worktree and a reviewer adversarially verifies the diff. Fully parametrized — pass args.roles to override any model slot, args.repo for repo path, args.invariants + args.test_cmd + args.smoke_instructions for project conventions.',
  phases: [
    { title: 'Scout', detail: 'Haiku maps the spec + affected subsystems' },
    { title: 'Read', detail: 'one Haiku reader per affected area (parallel)' },
    { title: 'Plan', detail: 'Opus synthesizes the implementation plan' },
    { title: 'Judge', detail: 'diverse panel grades the plan on disjoint lenses' },
    { title: 'Build', detail: 'coder implements the plan (TDD) in an isolated worktree — opt-in via args.build' },
    { title: 'Verify', detail: 'adversarial review of the diff + trifecta/smoke output' },
  ],
}

const SCOUT = {
  type: 'object',
  additionalProperties: false,
  required: ['spec_summary', 'areas'],
  properties: {
    spec_summary: { type: 'string' },
    areas: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'paths', 'why'],
        properties: {
          name: { type: 'string' },
          paths: { type: 'array', items: { type: 'string' } },
          why: { type: 'string' },
        },
      },
    },
  },
}

const READING = {
  type: 'object',
  additionalProperties: false,
  required: ['area', 'facts', 'risks'],
  properties: {
    area: { type: 'string' },
    facts: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
  },
}

const PLAN = {
  type: 'object',
  additionalProperties: false,
  required: ['steps', 'files_to_touch', 'test_plan', 'open_questions'],
  properties: {
    steps: { type: 'array', items: { type: 'string' } },
    files_to_touch: { type: 'array', items: { type: 'string' } },
    test_plan: { type: 'array', items: { type: 'string' } },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
}

const VERDICT = {
  type: 'object',
  additionalProperties: false,
  required: ['lens', 'sound', 'blocking_concerns', 'confidence'],
  properties: {
    lens: { type: 'string' },
    sound: { type: 'boolean' },
    blocking_concerns: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'number' },
  },
}

const BUILD = {
  type: 'object',
  additionalProperties: false,
  required: ['branch', 'files_changed', 'trifecta_output', 'smoke_output', 'self_assessment'],
  properties: {
    branch: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    trifecta_output: { type: 'string' }, // last ~20 lines, raw
    smoke_output: { type: 'string' }, // raw, or "n/a — pure refactor/doc" with reason
    self_assessment: { type: 'string' },
  },
}

const REVIEW = {
  type: 'object',
  additionalProperties: false,
  required: ['ships', 'blocking_findings', 'plan_coverage', 'confidence'],
  properties: {
    ships: { type: 'boolean' },
    blocking_findings: { type: 'array', items: { type: 'string' } },
    plan_coverage: { type: 'string' }, // did the diff implement the plan's steps + test_plan?
    confidence: { type: 'number' },
  },
}

// Robustly resolve args. The harness may deliver `args` as a parsed object OR as
// a JSON string — observed 2026-06-11: a stringified `args` left `args.spec`
// undefined, so `(args && args.spec)` fell through to the no-spec branch and the
// scout silently planned an ARBITRARY backlog spec (asked for T22, got T23 then
// T17). Parse-if-string + coerce non-objects to {} so spec/build/difficulty
// resolve reliably however the harness passes them. Worst case (args truly
// absent) → {} → no-spec branch, which now FAILS LOUD below instead of guessing.
let a = args
if (typeof a === 'string') {
  try { a = JSON.parse(a) } catch { a = {} }
}
if (!a || typeof a !== 'object') a = {}

// Model role map — Claude defaults; overridable via args.roles. This is the single
// seam a future non-Claude vendor layer slots into without touching call sites.
const DEFAULT_ROLES = {
  scout: 'haiku', reader: 'haiku', planner: 'opus',
  judges: ['opus', 'sonnet', 'haiku'],
  coder: { hard: 'opus', routine: 'sonnet' }, verifier: 'opus',
}
const ROLES = (a.roles && typeof a.roles === 'object') ? { ...DEFAULT_ROLES, ...a.roles } : DEFAULT_ROLES
function resolveModel(role, difficulty) {
  if (role === 'coder') return ROLES.coder[difficulty] || ROLES.coder.routine
  return ROLES[role]
}

const REPO = a.repo || '.'

// args.spec = path to a task spec (optional). With no spec, scout infers the
// in-flight work from the current branch's diff — and ONLY from the diff.
const spec = a.spec || null
const specClause = spec
  ? `Read the task spec at ${spec} end-to-end. The task you must plan is defined by THIS file ONLY — its H1 title is the authoritative scope. The spec may cross-reference sibling tasks (e.g. in "Prerequisites"/"Soft" coordination notes); those are context, NOT your scope. Do NOT plan a different task than the one this file's title names. If the title says "Drop"/"Remove"/"Delete", this is a DELETION task — plan removals, not additions.`
  : `No spec path was given. Run \`git -C ${REPO} diff main...HEAD --stat\` and \`git -C ${REPO} log --oneline -10\` to infer the IN-FLIGHT work. CRITICAL: if that diff is EMPTY (nothing uncommitted, nothing ahead of main), there is NO work to plan — do NOT browse docs/specs/ and do NOT pick a backlog/Todo spec to invent a task. In that case set spec_summary to exactly "NO_WORK" and return an empty areas array.`

phase('Scout')
const scout = await agent(
  `${specClause}
Map the work for an implementation task in the repo at ${REPO}.
Honor the project's documented invariants (${a.invariants || 'see the project conventions doc'}).
First state the task's identifying title verbatim (the spec H1 if a spec was given; otherwise a one-line label for the in-flight diff), then a one-paragraph summary of THAT task, then the 2-5 distinct subsystem AREAS this task touches — each with the concrete file paths an implementer must read, and why.`,
  { model: resolveModel('scout'), phase: 'Scout', label: 'scout', schema: SCOUT },
)

// Fail loud, never guess. Empty areas OR the NO_WORK sentinel (no spec + empty
// diff) both abort here rather than letting a mis-scoped plan reach the panel.
if (!scout || !scout.areas || scout.areas.length === 0 || scout.spec_summary === 'NO_WORK') {
  return {
    error: spec
      ? `scout produced no areas for ${spec} — the spec may be empty or unreadable`
      : 'no spec path given AND no in-flight diff — refusing to plan an arbitrary backlog spec. Pass {spec: "docs/specs/<id>.md"}.',
    scout,
  }
}
log(`scout mapped ${scout.areas.length} area(s)`)

phase('Read')
const readings = (
  await parallel(
    scout.areas.map((a) => () =>
      agent(
        `Task: ${scout.spec_summary}
Read these files under ${REPO} and report what an implementer must know about the "${a.name}" area: ${a.paths.join(', ')}.
Report load-bearing FACTS (function contracts, invariants, gotchas) and concrete RISKS. Do NOT propose a plan — just ground truth.`,
        { model: resolveModel('reader'), phase: 'Read', label: `read:${a.name}`, schema: READING },
      ),
    ),
  )
).filter(Boolean)

phase('Plan')
const plan = await agent(
  `You are the planner for this task. Synthesize ONE concrete implementation plan.
Spec: ${scout.spec_summary}
Grounded readings (facts + risks per area):
${JSON.stringify(readings, null, 2)}
Produce ordered steps, the exact files to touch, a TDD test plan (tests written before implementation, per the project's conventions doc), and open questions. Assume the trifecta + ephemeral smoke gate the ship.`,
  { model: resolveModel('planner'), phase: 'Plan', label: 'plan', schema: PLAN },
)

phase('Judge')
// Diverse panel on disjoint lenses — research: a diverse small-model jury beats
// one strong judge, and disjoint lenses catch failure modes redundancy can't.
const LENSES = [
  'correctness & architectural invariants',
  'cost & model-slot fit',
  'test coverage & TDD ordering',
]
const verdicts = (
  await parallel(
    LENSES.map((lens, i) => () =>
      agent(
        `Stress-test this implementation plan through the "${lens}" lens ONLY. Try to find a blocking flaw; default to skeptical.
Spec: ${scout.spec_summary}
Plan: ${JSON.stringify(plan, null, 2)}
Return whether the plan is sound on your lens, any blocking concerns, and your confidence 0-1.`,
        { model: ROLES.judges[i % ROLES.judges.length], phase: 'Judge', label: `judge:${ROLES.judges[i % ROLES.judges.length]}`, schema: VERDICT },
      ),
    ),
  )
).filter(Boolean)

const blocking = verdicts.filter((v) => v && v.sound === false)
const verdict = blocking.length >= 2 ? 'REWORK' : 'PROCEED'
log(`panel verdict: ${verdict} (${blocking.length}/${verdicts.length} lenses blocking)`)

const baseResult = {
  verdict,
  blocking_lenses: blocking.map((v) => v.lens),
  plan,
  verdicts,
  areas_scouted: scout.areas.length,
  areas_read: readings.length,
  built: false,
}

// Plan-only by default. The coder runs ONLY when the panel says PROCEED and the
// caller opted in with build:true — implementation mutates the repo, so it's
// never a silent side effect of "scout the work."
if (verdict === 'REWORK') {
  log('panel says REWORK — stopping before any code is written')
  return baseResult
}
if (!a.build) {
  log('plan-only run (pass {build: true} to implement the approved plan)')
  return baseResult
}

// Model-by-difficulty: hard work gets Opus, routine work gets Sonnet.
// Readers were Haiku; the planner/judge were diverse; the CODER is the
// one slot where "strength to generate" pays — never Haiku here.
const difficulty = a.difficulty || 'routine'

phase('Build')
const build = await agent(
  `You are the implementer for this task in the repo at ${REPO}.
Implement EXACTLY this approved plan — do not re-plan, do not expand scope:
${JSON.stringify(plan, null, 2)}

Honor the project's documented invariants: ${a.invariants || "the project's documented invariants"}.
Work entirely inside your own worktree — never touch the parent checkout.
Create a branch. Write tests first, then implement, then run the trifecta:
  ${a.test_cmd || "the project's test command"}
Then run the ephemeral smoke (${a.smoke_instructions || "exercise the new code path end-to-end with realistic inputs"}) — or, if the change has no live external surface, say so and why.
Do NOT open a PR or merge — leave the branch ready for operator review.
Return the branch name, files changed, the raw last ~20 lines of trifecta output, the raw smoke output (or "n/a" + reason), and a one-paragraph self-assessment.`,
  { model: resolveModel('coder', difficulty), isolation: 'worktree', phase: 'Build', label: `build:${difficulty}`, schema: BUILD },
)

if (!build) {
  log('coder produced no result — returning plan + judge only')
  return { ...baseResult, built: false, build_error: 'coder returned null' }
}

phase('Verify')
// Adversarial review by a DIFFERENT, stronger model than the coder — does the
// diff actually implement the plan, and does the trifecta/smoke output prove it?
const review = await agent(
  `Adversarially review this implementation against its plan. Default to skeptical — try to find a reason it should NOT ship.
Plan: ${JSON.stringify(plan, null, 2)}
Coder's report: ${JSON.stringify(build, null, 2)}
Inspect the branch "${build.branch}" in ${REPO} (\`git -C ${REPO} diff main...${build.branch}\`).
Check: (1) does the diff implement EVERY step + test in the plan, (2) is the trifecta output real and green (not paraphrased), (3) does the smoke genuinely exercise the new path or is it hand-waved, (4) any documented invariant violated (see the project's conventions doc).
Return whether it ships, blocking findings, an assessment of plan coverage, and confidence 0-1.`,
  { model: resolveModel('verifier'), phase: 'Verify', label: 'verify', schema: REVIEW },
)

log(`review: ${review && review.ships ? 'SHIPS' : 'HOLD'}`)

return {
  ...baseResult,
  built: true,
  build,
  review,
  ships: !!(review && review.ships),
}
