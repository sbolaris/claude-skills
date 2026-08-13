export const meta = {
  name: 'research-consensus',
  description: 'Scout the repo once, then three independent researchers answer the question, then three skeptic lenses attack the consensus',
  phases: [
    { title: 'Scout', detail: 'one agent reads the code so six do not', model: 'sonnet' },
    { title: 'Research', detail: '3 independent researchers, same prompt, ground truth pre-supplied' },
    { title: 'Citations', detail: 'cheap agent resolves every cited URL before opus reads it', model: 'haiku' },
    { title: 'Skeptic', detail: 'evidence lens on sonnet, correctness + consequence on opus' },
  ],
}

// args: { runDir, question, context, repo, repoRoot, files, round, priorRefutations }
// Tolerate args arriving as a JSON string (a real and silent failure mode — a stringified
// object destructures to all-undefined and every agent then researches the word "undefined").
const _a = typeof args === 'string' ? JSON.parse(args) : (args || {})
const {
  runDir, question, context = '', repo = '', repoRoot = '', files = [],
  round = 1, priorRefutations = [],
} = _a

// Fail loudly rather than fanning out agents against an empty prompt.
const _missing = ['runDir', 'question'].filter((k) => !_a[k] || String(_a[k]).trim() === '')
if (_missing.length) {
  throw new Error(
    `research-consensus: missing required args [${_missing.join(', ')}]. ` +
    `Received keys: [${Object.keys(_a).join(', ')}]. ` +
    `Pass args as a JSON OBJECT, not a JSON-encoded string.`
  )
}

if (!repoRoot) {
  log('WARNING: no repoRoot supplied — scout phase skipped and researchers cannot check code. ' +
      'A question about this repo\'s behaviour answered from docs alone is exactly how the Q3 inversion happened.')
}

const BRIEF = {
  type: 'object',
  required: ['consumerBehaviour', 'evidence', 'answersInCode', 'pinnedVersions'],
  properties: {
    consumerBehaviour: {
      type: 'string',
      description: 'What the code that consumes this data ACTUALLY does, in mechanical terms. Not what it is supposed to do — what the lines say.',
    },
    evidence: {
      type: 'array',
      description: 'The specific code that settles the question. Quote it; do not paraphrase.',
      items: {
        type: 'object',
        required: ['file', 'lines', 'excerpt', 'shows'],
        properties: {
          file: { type: 'string' },
          lines: { type: 'string', description: 'e.g. "68-77"' },
          excerpt: { type: 'string' },
          shows: { type: 'string', description: 'The specific thing this excerpt establishes' },
        },
      },
    },
    answersInCode: {
      type: 'array',
      description: 'Sub-questions the code settles OUTRIGHT, so no web research is needed. Be strict: only where the code is dispositive.',
      items: {
        type: 'object',
        required: ['question', 'answer', 'why'],
        properties: {
          question: { type: 'string' },
          answer: { type: 'string' },
          why: { type: 'string', description: 'Which excerpt proves it' },
        },
      },
    },
    pinnedVersions: {
      type: 'array',
      description: 'Versions actually pinned in requirements.txt / pyproject.toml / Dockerfile / lockfiles — researchers must answer against THESE, not against latest/master.',
      items: { type: 'string' },
    },
    schemaFacts: {
      type: 'array',
      description: 'Real DDL / column types / cardinality found in the repo that bear on the question',
      items: { type: 'string' },
    },
    stillNeedsDocs: {
      type: 'array',
      description: 'Sub-questions the code CANNOT settle — these are the ones worth spending web budget on',
      items: { type: 'string' },
    },
  },
}

const FINDINGS = {
  type: 'object',
  required: ['answer', 'confidence', 'sources', 'caveats', 'repoEvidence'],
  properties: {
    answer: { type: 'string', description: 'The single most defensible answer. Do not hedge across alternatives.' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    sources: {
      type: 'array',
      items: {
        type: 'object',
        required: ['url', 'supports'],
        properties: {
          url: { type: 'string' },
          supports: { type: 'string', description: 'The specific claim this source backs' },
          fetched: { type: 'boolean', description: 'True only if you actually retrieved this URL this session' },
        },
      },
    },
    repoEvidence: {
      type: 'array',
      description: 'Code you read IN THIS REPO that bears on the answer. Any claim about how this system behaves must cite code here, not only documentation. An empty array is only acceptable when the question is purely about external behaviour with no consumer in this repo.',
      items: {
        type: 'object',
        required: ['file', 'lines', 'shows'],
        properties: {
          file: { type: 'string' },
          lines: { type: 'string' },
          shows: { type: 'string' },
        },
      },
    },
    caveats: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' }, description: 'Claims you could not confirm' },
  },
}

const LINKCHECK = {
  type: 'object',
  required: ['results'],
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object',
        required: ['url', 'status', 'verdict'],
        properties: {
          url: { type: 'string' },
          status: { type: 'string', description: 'HTTP status, or the curl error' },
          finalUrl: { type: 'string', description: 'After redirects, if different' },
          bytes: { type: 'number', description: 'Body size of the fetched page' },
          verdict: {
            type: 'string',
            enum: ['OK', 'DEAD', 'REDIRECTED_TO_LANDING', 'STUB', 'UNREACHABLE'],
            description: 'STUB = 200 but a near-empty meta-refresh shell. Under ~3KB of body on a docs host is a stub.',
          },
        },
      },
    },
  },
}

const VERDICT = {
  type: 'object',
  required: ['verdict', 'refutations', 'badCitations', 'summary'],
  properties: {
    verdict: { type: 'string', enum: ['UPHELD', 'UPHELD_WITH_CAVEATS', 'REFUTED'] },
    refutations: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim', 'why', 'severity'],
        properties: {
          claim: { type: 'string' },
          why: { type: 'string' },
          breaks: { type: 'string' },
          severity: { type: 'string', enum: ['FATAL', 'MATERIAL', 'MINOR'] },
        },
      },
    },
    badCitations: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: 'One line the human reads at the gate' },
  },
}

// On a REFUTED loop the orchestrator re-opens only the refuted claims. Re-running the whole
// question wastes a round re-deriving what already survived, and invites the researchers to
// restate the refuted answer with fresh citations rather than engage with the refutation.
const priorBlock = priorRefutations.length
  ? `\n\n=== THIS IS RESEARCH ROUND ${round}. A PRIOR ROUND WAS REFUTED — READ BEFORE ANSWERING ===\n` +
    priorRefutations.map((r, i) =>
      `[${i + 1}] (${r.severity || 'UNSPECIFIED'}, ${r.lens || 'unknown lens'} lens)\n` +
      `    Claim refuted: ${r.claim}\n` +
      `    Why it was wrong: ${r.why}\n` +
      (r.breaks ? `    What it would have broken: ${r.breaks}\n` : '')
    ).join('\n') +
    `\nOnly the claims above are re-opened. Everything else the prior round established stands — do not ` +
    `re-derive it and do not spend web budget on it.\n\n` +
    `The skeptic has already read this material and found the previous answer wrong. Restating that answer ` +
    `with better citations is not a response to the refutation. Either show specifically why the refutation ` +
    `does not hold, or accept it and answer differently.\n` +
    `=== END PRIOR REFUTATIONS ===\n`
  : ''

const base = `Repo: ${repo}\nRepo root (real path — read files here): ${repoRoot || '(none supplied)'}\nRun dir: ${runDir}\nResearch round: ${round}\n\nQuestion:\n${question}\n\nContext:\n${context}${priorBlock}`

// ---- Phase 0: ONE scout reads the repo, so six downstream agents do not each re-derive it ----
// In the 20260806 run, three opus skeptics independently walked the same worktree — 17-21 Bash
// calls each — because nothing upstream had put the code in the payload. That was ~8M tokens.
phase('Scout')
let brief = null
if (repoRoot) {
  brief = await agent(
    `${base}\n\n` +
    (files.length ? `The plan named these files as in scope:\n${files.map((f) => `- ${f}`).join('\n')}\n\n` : '') +
    `You are the SCOUT. You run once, before any web research, and your output is injected into the ` +
    `prompt of three researchers and three skeptics — so read carefully now and none of them has to.\n\n` +
    `Do NOT search the web. Do NOT reason from documentation or from memory of how these libraries behave. ` +
    `Your entire job is to report what the code in ${repoRoot} literally says.\n\n` +
    `Read the code that PRODUCES the data and the code that CONSUMES it, and answer: what does the consumer ` +
    `actually do with these values? Very often a question posed abstractly ("is X guaranteed?") is settled ` +
    `outright by the consumer never depending on X. Say so plainly in answersInCode when that is the case — ` +
    `that finding is the single most valuable thing you can return.\n\n` +
    `Also pull: the real DDL or schema definition if it lives in this repo, the versions actually pinned in ` +
    `requirements.txt / pyproject.toml / Dockerfile (researchers must answer against the PINNED version, ` +
    `not against master), and column cardinality where it bears on the question.\n\n` +
    `Quote real excerpts with real line numbers. Never paraphrase code you did not open.`,
    { label: 'scout', phase: 'Scout', agentType: 'general-purpose', model: 'sonnet', schema: BRIEF },
  )
}

const briefBlock = brief
  ? `\n\n=== GROUND TRUTH FROM THE REPO (scout, already read the code — do not re-derive) ===\n` +
    `What the consumer actually does:\n${brief.consumerBehaviour}\n\n` +
    `Code excerpts:\n${(brief.evidence || []).map((e) => `--- ${e.file}:${e.lines} — ${e.shows}\n${e.excerpt}`).join('\n\n')}\n\n` +
    (brief.answersInCode?.length
      ? `SETTLED BY CODE — do not spend web budget re-deriving these:\n${brief.answersInCode.map((a) => `- ${a.question}\n  → ${a.answer}\n  (${a.why})`).join('\n')}\n\n`
      : '') +
    `Pinned versions — answer against these, NOT against latest or master:\n${(brief.pinnedVersions || []).join('\n') || '(none found)'}\n` +
    (brief.schemaFacts?.length ? `\nSchema facts:\n${brief.schemaFacts.join('\n')}\n` : '') +
    (brief.stillNeedsDocs?.length ? `\nSTILL NEEDS DOCUMENTATION — spend your web budget here:\n${brief.stillNeedsDocs.join('\n')}\n` : '') +
    `=== END GROUND TRUTH ===\n`
  : ''

if (brief) log(`scout: ${(brief.evidence || []).length} excerpts, ${(brief.answersInCode || []).length} sub-question(s) settled by code`)

// ---- Phase 1: three independent researchers, same prompt (consensus rule) ----
phase('Research')
const findings = (await parallel([1, 2, 3].map((i) => () =>
  agent(
    `${base}${briefBlock}\n\nYou are researcher ${i} of 3 working INDEPENDENTLY on the same question. ` +
    `Others are answering it in parallel; your answer is compared against theirs to detect divergence. ` +
    `Give the single most defensible answer with real, fetched sources — do NOT hedge across alternatives to seem safe, ` +
    `because hedging destroys the divergence signal. Respect the search budget: max 10 WebFetch, 5 WebSearch. ` +
    `If you cannot verify something, list it under "unverified" rather than inferring.\n\n` +
    (repoRoot
      ? `**Check the code before you conclude.** The repo is at ${repoRoot} and you have Read, Grep, Glob and Bash. ` +
        `A documented general truth ("the database does not guarantee X") does not become an operative risk until ` +
        `you have confirmed the consumer in THIS repo actually depends on X. Trace it and report what you found in ` +
        `repoEvidence. An answer that asserts a risk to this system while citing zero repo code is not a finding, ` +
        `it is a guess — and it will be refuted downstream at far greater cost than the two minutes it takes to read the file.\n\n`
      : '') +
    `Answer against the PINNED versions above where they exist. Citing master/latest for a pinned dependency is a defect.`,
    { label: `researcher-${i}`, phase: 'Research', agentType: 'researcher', schema: FINDINGS },
  )
))).filter(Boolean)

if (findings.length === 0) {
  // Nothing was researched, so nothing was refuted. This is an infrastructure failure and the
  // orchestrator must NOT charge it against the skeptic loop cap.
  return {
    outcome: 'INFRASTRUCTURE_FAILURE',
    reason: 'all 3 researchers failed to return — no research was produced',
    brief, findings: [], skeptic: null,
  }
}

log(`${findings.length}/3 researchers returned`)

// Deterministic enforcement, not a request the model may decline: a repo-behaviour claim
// backed by no repo reads is capped at low confidence in plain code.
const noRepoReads = []
for (const f of findings) {
  if (repoRoot && !(f.repoEvidence || []).length) {
    noRepoReads.push(f)
    if (f.confidence !== 'low') {
      f.confidenceClaimed = f.confidence
      f.confidence = 'low'
      f.caveats = [...(f.caveats || []), 'CONFIDENCE DOWNGRADED BY HARNESS: answered with zero repo reads.']
    }
  }
}
if (noRepoReads.length) {
  log(`WARNING: ${noRepoReads.length}/${findings.length} researchers cited no repo code — confidence downgraded to low`)
}

// Consensus is computed here, in plain code — not delegated to a model.
const norm = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const groups = []
for (const f of findings) {
  const g = groups.find((x) => {
    const a = new Set(norm(x.answer).split(' '))
    const b = norm(f.answer).split(' ')
    const overlap = b.filter((w) => a.has(w)).length / Math.max(b.length, 1)
    return overlap > 0.6
  })
  if (g) g.count++
  else groups.push({ answer: f.answer, count: 1, source: f })
}
groups.sort((a, b) => b.count - a.count)

const agreement = groups[0].count
const consensus = {
  agreement,
  total: findings.length,
  reached: agreement >= 2,
  answer: groups[0].answer,
  divergences: groups.slice(1).map((g) => g.answer),
  allSources: findings.flatMap((f) => f.sources || []),
  allRepoEvidence: findings.flatMap((f) => f.repoEvidence || []),
  allUnverified: findings.flatMap((f) => f.unverified || []),
  researchersWithNoRepoReads: noRepoReads.length,
}

log(consensus.reached
  ? `consensus ${agreement}/${findings.length}`
  : `NO CONSENSUS — ${findings.length} distinct answers, skeptic will attack all of them`)

// ---- Phase 1.5: resolve every cited URL once, cheaply, before opus reads any of them ----
// Dedup in plain code; one haiku agent does the curl-ing. Previously the evidence lens burned
// opus turns discovering that a cited page was a 1.1KB meta-refresh stub.
phase('Citations')
const uniqueUrls = [...new Set(consensus.allSources.map((s) => s.url).filter(Boolean))]
let linkReport = '(no URLs cited)'
if (uniqueUrls.length) {
  const check = await agent(
    `Resolve each URL below and report what is actually there. Use curl only — do not use WebFetch, ` +
    `do not read or summarise the content, do not evaluate whether it supports any claim. ` +
    `You are a link resolver, nothing more.\n\n` +
    `For each: \`curl -sSL -o /tmp/p.html -w '%{http_code} %{url_effective} %{size_download}' <url>\`\n\n` +
    `Verdicts: DEAD (4xx/5xx) · UNREACHABLE (curl failed) · REDIRECTED_TO_LANDING (final URL is a generic ` +
    `index/landing page, not the specific document requested) · STUB (200 but under ~3KB of body — typically ` +
    `a meta-refresh shell with no real content) · OK.\n\n` +
    `URLs:\n${uniqueUrls.join('\n')}`,
    { label: 'link-check', phase: 'Citations', agentType: 'general-purpose', model: 'haiku', schema: LINKCHECK },
  )
  const rows = check?.results || []
  const bad = rows.filter((r) => r.verdict !== 'OK')
  linkReport = rows.map((r) => `${r.verdict.padEnd(22)} ${r.status} ${r.bytes ?? '?'}B  ${r.url}${r.finalUrl && r.finalUrl !== r.url ? `  →  ${r.finalUrl}` : ''}`).join('\n')
  log(`citations: ${uniqueUrls.length} unique URL(s) from ${consensus.allSources.length} listed, ${bad.length} not OK`)
}

// ---- Phase 2: three adversarial lenses attack the consensus ----
// Evidence is a link-reading job and runs on sonnet with the resolution table already in hand.
// Correctness and consequence are the judgement calls and keep opus.
phase('Skeptic')
const LENSES = [
  ['correctness', 'opus', 'Is the claim true? Verify every load-bearing fact against a primary source AND against the code in the repo. Check version applicability and over-generalisation. A documented general truth is not an operative risk until the consumer is shown to depend on it — that inference is where research most often inverts an answer.'],
  ['evidence', 'sonnet', 'Does each source actually contain the claim attributed to it? The URL resolution table below is already done for you — do NOT re-curl the links. Spend your effort on: claims attributed to a source that does not contain them, window-function docs cited for statement-level behaviour and similar category slips, blogs cited as official docs, archived or stale mirrors presented as primary, source read at master when the repo pins an older version, and inflated source counts (same page cited twice under different URLs).'],
  ['consequence', 'opus', 'Assume the claim is true. Does the conclusion follow at this repo\'s scale, account, permissions, and concurrency? What breaks if it is true but incomplete? Where does the recommended remedy fail to deliver what it was added to provide, or pass the eval harness while fixing nothing?'],
]

const payload = consensus.reached
  ? `CONSENSUS ANSWER (${agreement}/${findings.length} agreed):\n${consensus.answer}\n\n` +
    (consensus.divergences.length ? `DIVERGENT ANSWERS (attack these too — divergence marks soft ground):\n${consensus.divergences.join('\n---\n')}\n\n` : '')
  : `NO CONSENSUS WAS REACHED. All ${findings.length} answers differ — treat this as a strong prior that the question is not settled:\n` +
    findings.map((f, i) => `[${i + 1}] ${f.answer}`).join('\n---\n') + '\n\n'

const skeptic = (await parallel(LENSES.map(([lens, model, instruction]) => () =>
  agent(
    `${base}${briefBlock}\n\n${payload}SOURCES CITED:\n${JSON.stringify(consensus.allSources, null, 2)}\n\n` +
    `URL RESOLUTION (already done — do not re-fetch these):\n${linkReport}\n\n` +
    `REPO CODE THE RESEARCHERS CITED:\n${JSON.stringify(consensus.allRepoEvidence, null, 2) || '(none — treat every claim about this system as unverified)'}\n\n` +
    (consensus.researchersWithNoRepoReads
      ? `NOTE: ${consensus.researchersWithNoRepoReads} of ${findings.length} researchers read no repo code at all. Their confidence was downgraded by the harness.\n\n`
      : '') +
    `RESEARCHERS COULD NOT VERIFY:\n${consensus.allUnverified.join('\n') || '(nothing declared)'}\n\n` +
    `Your lens is **${lens}**: ${instruction}\n\n` +
    `The scout has already read the repo and its findings are above. Do not re-walk the worktree to rediscover ` +
    `what is already in your prompt. DO open code the scout did not cover, and DO run a real experiment when a ` +
    `claim is cheaply testable — a permutation trial or a small script that settles a disputed property is worth ` +
    `more than any amount of documentation, and is explicitly in budget.\n\n` +
    `Budget: about 25 tool calls. If you are past that and still exploring, you have lost the thread — write up ` +
    `what you have and declare the rest unverified.\n\n` +
    `Default to REFUTED when uncertain — one more research round is cheap, a human approving a wrong plan is not.`,
    { label: `skeptic-${lens}`, phase: 'Skeptic', agentType: 'skeptic', model, schema: VERDICT },
  ).then((v) => (v ? { lens, ...v } : null))
))).filter(Boolean)

// A lens that failed to run is not an implicit pass — and if NONE ran, there is no verdict at all.
// Falling through here with the initial 'UPHELD' would report a clean pass from zero adversarial
// coverage, which is the worst output this node can produce.
if (skeptic.length === 0) {
  return {
    outcome: 'INFRASTRUCTURE_FAILURE',
    reason: 'all 3 skeptic lenses failed to return — the consensus was never attacked',
    brief, consensus, findings, skeptic: null,
  }
}

// Worst verdict wins.
const rank = { REFUTED: 2, UPHELD_WITH_CAVEATS: 1, UPHELD: 0 }
let worst = 'UPHELD'
for (const s of skeptic) if (rank[s.verdict] > rank[worst]) worst = s.verdict

const allRefutations = skeptic.flatMap((s) => (s.refutations || []).map((r) => ({ lens: s.lens, ...r })))
const fatal = allRefutations.filter((r) => r.severity === 'FATAL')
const material = allRefutations.filter((r) => r.severity === 'MATERIAL')

// A FATAL refutation forces REFUTED regardless of how the lens labelled its own verdict.
const verdict = fatal.length ? 'REFUTED' : worst
const lensesLost = LENSES.length - skeptic.length
if (lensesLost) log(`WARNING: ${lensesLost} skeptic lens(es) failed to return — treat coverage as incomplete`)

return {
  outcome: 'RESEARCH_COMPLETE',
  round,
  brief,
  consensus,
  findings,
  citations: { unique: uniqueUrls.length, listed: consensus.allSources.length, report: linkReport },
  skeptic: {
    verdict,
    lensesRun: skeptic.length,
    lensesExpected: LENSES.length,
    fatal: fatal.length,
    material: material.length,
    minor: allRefutations.filter((r) => r.severity === 'MINOR').length,
    refutations: allRefutations,
    badCitations: skeptic.flatMap((s) => s.badCitations || []),
    unverified: skeptic.flatMap((s) => s.unverified || []),
    summaries: skeptic.map((s) => `[${s.lens}] ${s.summary}`),
  },
}
