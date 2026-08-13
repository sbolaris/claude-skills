export const meta = {
  name: 'sqa-lenses',
  description: 'Scout, then four parallel SQA lenses over a change, deduped and adversarially verified',
  phases: [
    { title: 'Scout', detail: 'read the diff, tests, runners and ledger ONCE' },
    { title: 'SQA', detail: '4 lenses in parallel', model: 'opus' },
    { title: 'Verify', detail: 'refute each DISTINCT finding before it bounces the coding agent' },
  ],
}

// args: { runDir, repo, branch, base, ledgerPath, planPath }
// Tolerate args arriving as a JSON string — a stringified object destructures to all-undefined
// and the lenses then review nothing while reporting cleanly.
const _a = typeof args === 'string' ? JSON.parse(args) : (args || {})
const { runDir, repo = '', branch = '', base = 'HEAD~1', ledgerPath, planPath } = _a

const _missing = ['runDir', 'ledgerPath', 'planPath'].filter((k) => !_a[k] || String(_a[k]).trim() === '')
if (_missing.length) {
  throw new Error(
    `sqa-lenses: missing required args [${_missing.join(', ')}]. ` +
    `Received keys: [${Object.keys(_a).join(', ')}]. ` +
    `Pass args as a JSON OBJECT, not a JSON-encoded string.`
  )
}

const FINDINGS = {
  type: 'object',
  required: ['findings', 'summary'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'file', 'severity', 'observed', 'expected', 'selfReproduced'],
        properties: {
          title: { type: 'string' },
          file: { type: 'string' },
          line: { type: 'number' },
          severity: { type: 'string', enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] },
          observed: { type: 'string', description: 'What actually happens' },
          expected: { type: 'string', description: 'What should happen' },
          repro: { type: 'string', description: 'Concrete inputs/state that trigger it' },
          regressionTest: { type: 'string', description: 'Name of the test that must pin this' },
          outOfScope: { type: 'string', description: 'What the fix must NOT touch' },
          // P3 — hearsay ban. On run 20260806 a lens filed a finding it had NOT run, inherited
          // from another lens via the clobbered ledger. Findings must be first-hand.
          selfReproduced: {
            type: 'boolean',
            description:
              'TRUE only if YOU ran the repro yourself in this session and observed the failure. ' +
              'FALSE if you inferred it, read it in the ledger, or took it from another lens. Never guess TRUE.',
          },
        },
      },
    },
    summary: { type: 'string' },
  },
}

const SCOUT_BRIEF = {
  type: 'object',
  required: ['diffSummary', 'runnerWiring', 'testInventory'],
  properties: {
    diffSummary: { type: 'string', description: 'What the change actually does, file by file' },
    // The single highest-value scout field. On run 20260806 FOUR lenses each independently
    // rediscovered that the new suite ran in no gate, because none of them was told how tests
    // are actually invoked. Establishing it once turns 4 findings into 1.
    runnerWiring: {
      type: 'string',
      description:
        'How tests are ACTUALLY invoked in this repo: every runner script and CI job, whether each ' +
        'passes explicit paths or relies on config discovery, and — explicitly — which suites touched ' +
        'by this diff are reachable from a blocking gate and which are not.',
    },
    testInventory: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          test: { type: 'string' },
          asserts: { type: 'string', description: 'What it actually asserts — not what its name implies' },
          couldFail: { type: 'string', description: 'A concrete mutation that would turn it red, or "NONE — tautological"' },
        },
      },
    },
    evalACs: { type: 'array', items: { type: 'string' }, description: 'Each [auto] AC and what it literally checks' },
    ledgerStatus: {
      type: 'array',
      items: { type: 'string' },
      description: 'Each previously closed ledger bug: does its pinning test still exist, and does it still pass?',
    },
    pinnedVersions: { type: 'array', items: { type: 'string' } },
    excerpts: {
      type: 'array',
      items: {
        type: 'object',
        properties: { file: { type: 'string' }, lines: { type: 'string' }, shows: { type: 'string' }, excerpt: { type: 'string' } },
      },
    },
  },
}

const VERDICT = {
  type: 'object',
  required: ['real', 'reasoning'],
  properties: {
    real: { type: 'boolean', description: 'False if you could not reproduce or the finding is mistaken' },
    reasoning: { type: 'string' },
    severityCorrection: { type: 'string', enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'none'] },
  },
}

// One verdict per finding, in the order given — used by the batched lower-severity verifier.
const BATCH_VERDICT = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      description: 'Exactly one entry per finding supplied, in the same order. Never omit or reorder.',
      items: VERDICT,
    },
  },
}

const ctx =
  `Repo: ${repo}\nBranch: ${branch}\nDiff base: ${base}\nRun dir: ${runDir}\n` +
  `Plan: ${planPath}\nBug ledger: ${ledgerPath}\n\n` +
  `Read the plan, the evals in ${runDir}/evals/, and the ledger before you start. ` +
  `Inspect the change with: git diff ${base}...HEAD`

// ---- Phase 0: ONE scout, so four opus lenses do not each re-derive the same ground truth ----
// Ported from research-consensus.js, which cut the same waste at N2/N3. See
// ~/pipeline-optimization-plan.md RC1.
phase('Scout')
const brief = await agent(
  `${ctx}\n\n` +
  `You are the SCOUT for a code review. You run once, and your output is injected into the prompt of ` +
  `four reviewing agents — so read carefully now and none of them has to re-walk this repo.\n\n` +
  `Report only what the code literally says. Do not review, do not judge, do not file bugs. Ground truth only.\n\n` +
  `Priorities, in order:\n` +
  `1. **runnerWiring** — the most valuable thing you can return. Open EVERY test runner: pre-push hooks, ` +
  `CI workflow files, Makefiles, package scripts. For each, record whether it invokes the test tool with ` +
  `EXPLICIT paths or relies on config discovery (pytest testpaths, jest roots, etc.). Then state plainly, ` +
  `for each suite this diff touches, whether it is reachable from a gate that can BLOCK a push or a merge. ` +
  `A config entry naming a suite is NOT evidence the suite runs.\n` +
  `2. **testInventory** — for each test the diff adds or changes, what does it ACTUALLY assert, and name a ` +
  `concrete mutation that would turn it red. If you cannot name one, say "NONE — tautological". Ignore what ` +
  `the test's name implies.\n` +
  `3. **evalACs** — for each [auto] AC in ${runDir}/evals/, what does it literally check? Flag any AC that ` +
  `asserts on a config string or constant rather than on executed behaviour.\n` +
  `4. **ledgerStatus** — for each previously closed bug in ${ledgerPath}, does its pinning test still exist ` +
  `and still pass?\n\n` +
  `Quote real excerpts with real line numbers. Never paraphrase code you did not open. ` +
  `Do not modify the worktree.`,
  { label: 'scout', phase: 'Scout', agentType: 'general-purpose', model: 'sonnet', schema: SCOUT_BRIEF },
)

const briefBlock = brief
  ? `\n\n=== GROUND TRUTH (scout has already read this — do not re-derive) ===\n` +
    `What the change does:\n${brief.diffSummary}\n\n` +
    `HOW TESTS ARE ACTUALLY INVOKED:\n${brief.runnerWiring}\n\n` +
    (brief.testInventory?.length
      ? `Test inventory (what each test really asserts):\n${brief.testInventory.map((t) => `- ${t.test}\n  asserts: ${t.asserts}\n  turns red on: ${t.couldFail}`).join('\n')}\n\n`
      : '') +
    (brief.evalACs?.length ? `Eval ACs:\n${brief.evalACs.map((a) => `- ${a}`).join('\n')}\n\n` : '') +
    (brief.ledgerStatus?.length ? `Ledger pins:\n${brief.ledgerStatus.map((l) => `- ${l}`).join('\n')}\n\n` : '') +
    (brief.pinnedVersions?.length ? `Pinned versions:\n${brief.pinnedVersions.join('\n')}\n\n` : '') +
    (brief.excerpts?.length
      ? `Excerpts:\n${brief.excerpts.map((e) => `--- ${e.file}:${e.lines} — ${e.shows}\n${e.excerpt}`).join('\n\n')}\n`
      : '') +
    `=== END GROUND TRUTH ===\n` +
    `The scout established the above. Do NOT spend calls rediscovering it. DO open code the scout did not ` +
    `cover, and DO run real mutations to prove your findings.\n`
  : ''

if (brief) {
  log(`scout: ${(brief.excerpts || []).length} excerpts, ${(brief.testInventory || []).length} tests inventoried`)
} else {
  log('WARNING: scout failed — lenses will each re-walk the repo, expect materially higher cost')
}

const LENSES = [
  ['regression', `THE LEDGER LENS — the highest-priority one. Open ${ledgerPath} and re-verify EVERY previously closed bug: does its pinning regression test still exist, and does it still pass? Search the diff and the test suite for deleted tests, @pytest.mark.skip, .skip(, xfail, and commented-out assertions. A disabled or removed regression test is CRITICAL on its own, even if the current change looks unrelated.`],
  ['correctness', 'Does the code do what the plan and the acceptance criteria say? Walk the error paths, boundary values (empty, single, very large, malformed), idempotency, and concurrency. Check that failures actually fail rather than returning a partial result that reads as success.'],
  ['tests', 'Are the tests real? Every [auto] AC needs a named passing test. Look for tests that cannot fail: mocks that always succeed, assertions on the mock rather than the behaviour, tests with no assertion, and tests changed to match the implementation instead of the spec.'],
  ['security-standards', 'Hardcoded secrets, ARNs, account IDs; over-broad IAM; injection; unvalidated input; leaked credentials in logs. Plus repo standards: layout, naming, type hints, structured logging, no bare except-and-continue.'],
]

// ---- P0: claim registry — dedupe BEFORE verification, not after ----
// Verification fans out per finding, so duplicates are paid twice: once by the lens that found it
// and again by a verifier refuting the same defect. On run 20260806, 23 confirmed findings were 12
// distinct bugs; the wiring gap alone was filed by four lenses and verified four times.
//
// Registration is fully SYNCHRONOUS (no await between match and insert) so interleaved lens
// callbacks cannot race. Plain code only — no agent, no tokens.
const STOP = new Set(['the', 'a', 'an', 'is', 'are', 'in', 'on', 'of', 'to', 'and', 'or', 'it', 'its',
  'that', 'this', 'for', 'with', 'no', 'not', 'has', 'have', 'was', 'were', 'be', 'been', 'by', 'at',
  'from', 'but', 'so', 'than', 'then', 'when', 'which', 'because', 'entry', 'new', 'does', 'do'])

const _norm = (w) => (w.endsWith('s') && w.length > 4 ? w.slice(0, -1) : w)  // crude singularisation

// Titles keep `_` as a word char so code identifiers (`sort_values`, `_sliding_freq`) stay whole.
const tokens = (s) =>
  new Set(
    String(s || '')
      .toLowerCase()
      .replace(/bug-\d+/g, ' ')           // strip ledger IDs — same bug, different lens numbering
      .replace(/[^a-z0-9_]+/g, ' ')
      .split(' ')
      .filter((w) => w.length > 2 && !STOP.has(w))
      .map(_norm),
  )

// Pin names MUST split on `_` — they are snake_case, so keeping the underscore collapses the whole
// name to one token and the similarity is 0 unless two lenses guessed a byte-identical test name.
// That defect made the pin signal silently useless when it was first added.
const pinTokens = (s) =>
  new Set(
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .split(' ')
      .filter((w) => w.length > 2 && !STOP.has(w) && w !== 'test')
      .map(_norm),
  )

const jaccard = (a, b) => {
  if (!a.size || !b.size) return 0
  let hit = 0
  for (const t of a) if (b.has(t)) hit++
  return hit / (a.size + b.size - hit)
}

const basename = (f) => String(f || '').split('/').pop()

const claims = []
let filedCount = 0   // every finding any lens filed, before dedupe — the denominator for the win

// Returns the existing claim this finding duplicates, or null. Thresholds are deliberately
// asymmetric: same-file duplicates are common and cheap to merge, cross-file merges need stronger
// agreement. A missed merge costs one redundant verify; a WRONG merge could drop a real bug — so
// every merged title and repro is retained on the claim, and nothing is discarded.
// Thresholds tuned against run 20260806's real 23 findings: cross=0.40 / same-file=0.25 reproduces
// the hand-audited 12 distinct bugs exactly, with 11 merges and ZERO false merges. Lowest true
// merge scored 0.25 (the two AC6 findings), highest false-merge candidate stayed below it.
// That is ONE run of evidence — if a future run shows a wrong merge, raise same-file first, and
// check the `mergedTitles` on the offending claim to see what collapsed.
const CROSS_FILE_MATCH = 0.4
const SAME_FILE_MATCH = 0.3

// Two independent signals, whichever is stronger. Lenses word titles very differently for the same
// defect but tend to converge on the regression test they want, so the pin name often matches when
// the prose does not — on run wf_0c3f5d46-b7a two lenses filed the same AUTO_FIX bug with titles
// scoring below threshold and pin names scoring 0.44.
const similarity = (f, c) =>
  Math.max(jaccard(tokens(f.title), c.titleTokens), jaccard(pinTokens(f.regressionTest), c.pinTokens))

const findDuplicate = (f) => {
  const fb = basename(f.file)
  for (const c of claims) {
    const score = similarity(f, c)
    if (score >= CROSS_FILE_MATCH || (fb === basename(c.file) && score >= SAME_FILE_MATCH)) return { claim: c, score }
  }
  return null
}

const SEV_RANK = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

phase('SQA')

// Pipeline, not barrier: each lens's findings dedupe and go to verification as soon as that lens
// returns. The registry makes later lenses cheaper without making earlier ones wait.
const perLens = await pipeline(
  LENSES,
  ([lens, instruction]) =>
    agent(
      `${ctx}${briefBlock}\n\nYour lens is **${lens}**.\n${instruction}\n\n` +
      `Report only defects you can point at in the code. Every finding needs a concrete repro and a named ` +
      `regression test that must pin it.\n\n` +
      `Set selfReproduced=true ONLY for findings whose repro you ran yourself and watched fail. If you did ` +
      `not run it, set false — a false-but-honest flag costs nothing, an unearned true poisons the bounce.\n\n` +
      `MUTATION DISCIPLINE — check this before you change a single file. You may have been given your ` +
      `own isolated worktree. Verify it: run \`git rev-parse --show-toplevel\` and compare against ` +
      `${repo}. If it differs, you are isolated — mutate freely to prove findings and do not clean up. ` +
      `If it is the SAME path, you are in the SHARED worktree that three other lenses are reading right ` +
      `now: copy what you need to a scratch dir (\`git show HEAD:<path>\`) and mutate only there. ` +
      `Never leave the shared tree dirty — on run 20260806 lens agents left mutants and assert-False ` +
      `canaries behind and corrupted another lens's investigation mid-flight.\n\n` +
      `Do not write to the shared bug ledger — concurrent lens writes clobbered it on that same run. ` +
      `Write your findings to ${runDir}/sqa/ledger-fragment-${lens}.md instead; the executor merges them.`,
      {
        label: `sqa-${lens}`,
        phase: 'SQA',
        agentType: 'software-quality-engineer',
        schema: FINDINGS,
        // NO isolation: 'worktree' here. It was tried on run wf_0c3f5d46-b7a and hard-errored all
        // four lenses: "Cannot create agent worktree: not in a git repository". The session cwd is
        // the harness's own directory, not the repo under review, so the runtime has no repo to
        // fork. Isolation would have to be arranged around `repo`, not the agent's cwd.
        // The shared-tree contamination risk (RC3) is handled by the MUTATION DISCIPLINE block in
        // the prompt instead — each lens checks where it actually is and copies out if it must.
      },
    ),

  (result, [lens]) => {
    if (!result || !result.findings?.length) return []

    // --- P0 dedupe + P3 hearsay downgrade, synchronous, before any verification spawns ---
    const fresh = []
    let merged = 0
    let hearsay = 0

    for (const f of result.findings) {
      filedCount++
      const dup = findDuplicate(f)
      if (dup) {
        merged++
        const c = dup.claim
        c.corroboratedBy.push(lens)
        c.mergedTitles.push(f.title)
        if (f.repro && !c.repros.includes(f.repro)) c.repros.push(f.repro)
        // Corroboration should not soften severity: keep the worst any lens assigned.
        if (SEV_RANK[f.severity] < SEV_RANK[c.severity]) c.severity = f.severity
        if (f.selfReproduced) c.selfReproduced = true
        continue
      }

      // P3 — a finding nobody actually reproduced cannot bounce the coding agent at full severity.
      let severity = f.severity
      if (f.selfReproduced === false) {
        hearsay++
        severity = 'LOW'
      }

      const claim = {
        ...f,
        severity,
        lens,
        hearsay: f.selfReproduced === false,
        corroboratedBy: [lens],
        mergedTitles: [f.title],
        repros: f.repro ? [f.repro] : [],
        titleTokens: tokens(f.title),
        pinTokens: pinTokens(f.regressionTest),
      }
      claims.push(claim)
      fresh.push(claim)
    }

    log(`${lens}: ${result.findings.length} filed → ${fresh.length} distinct` +
        `${merged ? `, ${merged} merged into earlier claims` : ''}` +
        `${hearsay ? `, ${hearsay} downgraded as unreproduced` : ''}`)

    if (!fresh.length) return []

    // --- Verification: only DISTINCT claims, severity-triaged, on sonnet ---
    // Refuting one concrete claim with the repro already written is bounded work; the lenses keep
    // opus, which is where the judgement is.
    const brief_ = (f) =>
      `Finding: ${f.title}\nFile: ${f.file}${f.line ? ':' + f.line : ''}\n` +
      `Observed: ${f.observed}\nExpected: ${f.expected}\n` +
      `Repro: ${f.repros.length ? f.repros.join('\n  OR: ') : '(none given)'}` +
      (f.corroboratedBy.length > 1 ? `\nAlso filed independently by: ${f.corroboratedBy.join(', ')}` : '') +
      (f.hearsay ? `\nNOTE: the filing lens did NOT reproduce this itself.` : '')

    const REFUTE =
      `Try to REFUTE this. You are not looking for reasons it might be right — you are looking for reasons it ` +
      `is wrong. Read the actual code and attempt the repro. Set real=false if it does not reproduce, if the ` +
      `"expected" behaviour is not what the plan or evals require, or if the finding misreads the code. ` +
      `A false finding costs a wasted bounce round out of only 3 — but do not refute a real defect just to ` +
      `keep the count down.\n\n` +
      `Work from git show HEAD:<path> blobs in a scratch dir, or in your own worktree if you have one. ` +
      `Leave the shared worktree untouched.`

    const heavy = fresh.filter((f) => f.severity === 'CRITICAL' || f.severity === 'HIGH')
    const light = fresh.filter((f) => f.severity !== 'CRITICAL' && f.severity !== 'HIGH')

    const jobs = heavy.map((f) => () =>
      agent(`${REFUTE}\n\n${ctx}${briefBlock}\n\n${brief_(f)}`,
        { label: `verify:${f.severity}:${basename(f.file)}`, phase: 'Verify', model: 'sonnet', schema: VERDICT },
      ).then((v) => [{ ...f, verdict: v }])
    )

    if (light.length) {
      jobs.push(() =>
        agent(
          `${REFUTE}\n\nYou are given ${light.length} lower-severity findings from the **${lens}** lens. ` +
          `Judge EACH one separately and return one verdict per finding, in the same order, keyed by index.\n\n` +
          `${ctx}${briefBlock}\n\n` +
          light.map((f, i) => `--- [${i}] ---\n${brief_(f)}`).join('\n\n'),
          { label: `verify:batch:${lens} (${light.length})`, phase: 'Verify', model: 'sonnet', schema: BATCH_VERDICT },
        ).then((b) => light.map((f, i) => ({ ...f, verdict: b?.verdicts?.[i] || null })))
      )
    }

    log(`${lens}: ${heavy.length} individual + ${light.length} batched verification(s)`)
    return parallel(jobs).then((r) => r.filter(Boolean).flat())
  },
)

const all = perLens.flat().filter(Boolean)

// ---- P4: contested bucket ----
// A claim several lenses found independently, then a single verifier refuted, is not settled — it
// is contested. On run 20260806 the security lens re-confirmed two findings that the verify stage
// then refuted, and the contradiction vanished silently into `refuted`. Corroboration by 3+
// independent lenses outranks one refutation: surface it for human adjudication instead.
const isRefuted = (f) => f.verdict?.real === false
const contested = all.filter((f) => isRefuted(f) && f.corroboratedBy.length >= 3)
const refuted = all.filter((f) => isRefuted(f) && f.corroboratedBy.length < 3)

// A finding whose verifier died is NOT confirmed. It previously rode along in `confirmed` with
// verdict:null, so a bounce work order would present it to the coding agent as an established bug —
// exactly what the verify stage exists to prevent. On run wf_0c3f5d46-b7a two HIGH findings were in
// that state because their verify agents hit the org spend limit.
const unverified = all.filter((f) => !f.verdict)

const confirmed = all
  .filter((f) => f.verdict?.real === true)
  .map((f) => ({
    ...f,
    severity:
      f.verdict?.severityCorrection && f.verdict.severityCorrection !== 'none'
        ? f.verdict.severityCorrection
        : f.severity,
  }))

if (refuted.length) log(`${refuted.length} finding(s) refuted on verification — not bouncing those`)
if (contested.length) log(`${contested.length} CONTESTED: refuted by verify but filed independently by 3+ lenses — human adjudicates`)
if (unverified.length) log(`WARNING: ${unverified.length} finding(s) could not be verified — kept, treat as unconfirmed`)

const lensesLost = LENSES.length - perLens.filter((r) => r !== null).length
if (lensesLost) log(`WARNING: ${lensesLost} SQA lens(es) failed — coverage is incomplete, do not read a clean result as clean`)

confirmed.sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity])

const strip = (f) => {
  const { titleTokens, pinTokens: _pt, ...rest } = f   // Sets are not JSON-serialisable
  return rest
}

// A node that found nothing because it never ran must NEVER report PASS. Run wf_0c3f5d46-b7a
// returned status:'PASS' with lensesRun:0 after all four lenses died on a worktree error — a clean
// bill of health from zero adversarial coverage, which is the one failure mode the graph's rule 3
// forbids outright. The identical bug was fixed once at N2/N3 (`worst` left at its UPHELD
// initialiser) and this rewrite reintroduced it. PASS is now reachable only from full coverage.
const status =
  lensesLost === LENSES.length ? 'INFRASTRUCTURE_FAILURE'
    : confirmed.length ? 'BUGS_FOUND'
      : contested.length ? 'CONTESTED'
        // No confirmed bugs, but coverage was incomplete OR findings exist that nobody could
        // verify. Either way this is not a clean bill of health.
        : (lensesLost || unverified.length) ? 'INCOMPLETE'
          : 'PASS'

if (status === 'INFRASTRUCTURE_FAILURE') {
  log('INFRASTRUCTURE_FAILURE: every lens failed to run. This is NOT a pass — nothing was reviewed.')
} else if (status === 'INCOMPLETE') {
  log(`INCOMPLETE: ${lensesLost}/${LENSES.length} lens(es) never ran and the rest found nothing. ` +
      `Absence of findings from partial coverage is not evidence of correctness.`)
}

return {
  status,
  lensesRun: LENSES.length - lensesLost,
  lensesExpected: LENSES.length,
  scoutRan: !!brief,
  dedupe: {
    filed: filedCount,
    distinct: claims.length,
    verifyAgentsSaved: filedCount - claims.length,
    note: 'Verification fans out per DISTINCT claim. corroboratedBy shows which lenses agreed.',
  },
  counts: {
    critical: confirmed.filter((f) => f.severity === 'CRITICAL').length,
    high: confirmed.filter((f) => f.severity === 'HIGH').length,
    medium: confirmed.filter((f) => f.severity === 'MEDIUM').length,
    low: confirmed.filter((f) => f.severity === 'LOW').length,
  },
  confirmed: confirmed.map(strip),
  contested: contested.map((f) => ({ title: f.title, corroboratedBy: f.corroboratedBy, refutedBecause: f.verdict.reasoning })),
  refuted: refuted.map((f) => ({ title: f.title, why: f.verdict.reasoning })),
  // Full detail, not just titles: these need re-verification on the next attempt, and the executor
  // must be able to tell the coding agent exactly what is unproven rather than dropping them.
  unverified: unverified.map(strip),
  ledgerFragments: LENSES.map(([l]) => `${runDir}/sqa/ledger-fragment-${l}.md`),
}
