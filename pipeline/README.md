# Graph Pipeline — Specification

A graph-based execution pipeline: plan → research → adversarial review → human gate → TDD implementation → SQA → docs → PR → PR review → human gate → reviewer tagging.

Invoked with `/pipeline "<goal>"`. This file is the source of truth for the graph; `~/.claude/commands/pipeline.md` is the executable version the orchestrator follows.

## Design decisions

| Decision | Choice |
|---|---|
| Substrate | Hybrid — main thread is the graph executor; `Workflow` used only inside fan-out nodes |
| Visualization source | `run.json` → `render_viz.py` → `viz.html`; the orchestrator never authors HTML |
| Context | `run.json` is the run's memory; gates double as compaction boundaries via `--resume` |
| Agent memory | per-agent under `~/.claude/agent-memory/<agent>/`, cross-role lessons in `_shared/` |
| Human gates | `PushNotification` (desktop + phone) then `AskUserQuestion` in the CLI |
| Push / PR | Pipeline runs `gh` itself: pushes the branch and opens a real (non-draft) PR |
| Visualization | Artifact republished to the same URL at every node transition |
| Evals | Human-readable criteria **plus** a runnable harness; gates re-run it |
| Run state | `~/.claude/pipeline-runs/<run-id>/` — outside the repo, zero footprint in the PR |
| Change guard | PM estimates blast radius; guard trips at 3× and halts to an unscheduled gate |
| Task fan-out | One task at a time — one branch, one PR per task |

## Why the main thread is the executor

A `Workflow` script cannot call `AskUserQuestion` — it runs in the background with no path to the human. Since this graph has three human gates, the graph state must live where the human is. `Workflow` is still used for the two nodes that genuinely fan out (research consensus, SQA lenses), invoked via `scriptPath`.

## Graph

```
  /pipeline "<goal>"
        │
   ┌────▼────┐
   │ N0 INIT │  create run dir, run id, first artifact publish
   └────┬────┘
   ┌────▼─────────────────┐
   │ N1 PLAN              │  project-manager (opus)
   │  A: returns questions│◄──┐ up to 2 rounds
   │  → AskUserQuestion   │───┘
   │  B: writes plan+evals│
   └────┬─────────────────┘
   ┌────▼──────────────────┐
   │ N2 RESEARCH (fan-out) │  Workflow: scout ×1 reads the repo
   │                       │  → researcher ×3 → consensus → link-check
   └────┬──────────────────┘
   ┌────▼──────────────────┐
   │ N3 SKEPTIC            │  3 lenses, adversarial, scout brief supplied
   └────┬──────────────────┘
        │ REFUTED ──► back to N2  (max 2 rounds, then gate)
        │ UPHELD
   ┌────▼──────────────────┐
   │ ★ GATE 1  approve findings + plan  ── push notify + CLI
   └────┬──────────────────┘
   ┌────▼──────────────────┐
   │ N4 BRANCH             │  git checkout -b
   ├───────────────────────┤
   │ N5 TESTS (red)        │  coding agent — one named test per AC
   ├───────────────────────┤
   │ N6 IMPLEMENT (green)  │  coding agent
   ├───────────────────────┤
   │ N7 VERIFY             │  lint + eval harness + change guard + structure
   └────┬──────────────────┘
        │ guard trips ──► ★ UNSCHEDULED GATE (diffstat shown)
   ┌────▼──────────────────┐
   │ N8 SQA (fan-out)      │  scout (sonnet) ─► 4 lenses (opus, isolated
   │                       │  worktrees) ─► dedupe in code ─► verify (sonnet)
   └────┬──────────────────┘
        │ BUGS ──► back to N6 with bug ledger  (max 3, then gate)
        │ CONTESTED ──► ★ UNSCHEDULED GATE (3+ lenses vs 1 verifier)
   ┌────▼──────────────────┐
   │ N9 DOCS               │  technical-writer
   ├───────────────────────┤
   │ N10 PUSH + PR         │  gh push, gh pr create
   ├───────────────────────┤
   │ N11 PR REVIEW         │  pr-reviewer (opus), fresh context
   └────┬──────────────────┘
        │ GAPS ──► back to N6  (max 2, then gate)
   ┌────▼──────────────────┐
   │ ★ GATE 2  approve reviewer tagging  ── push notify + CLI
   └────┬──────────────────┘
   ┌────▼──────────────────┐
   │ N12 TAG REVIEWERS     │  gh pr edit --add-reviewer
   └───────────────────────┘
```

## Loop caps

Every back-edge is capped. On exhaustion the pipeline **stops and raises a human gate** — it never silently gives up or keeps burning turns.

| Edge | Cap | On exhaustion |
|---|---|---|
| N3 → N2 (skeptic refutes) | 2 | Gate: "research cannot satisfy the skeptic" + both positions |
| N8 → N6 (SQA finds bugs) | 3 | Gate: "coding agent cannot clear SQA" + bug ledger |
| N11 → N6 (PR review gaps) | 2 | Gate: "PR review gaps unresolved" |
| any node → itself (harness defect) | 2 | Gate: "node cannot execute" + the incident record |

**A loop credit is charged only for disagreement on the merits** — an agent did its job and the result was rejected. A node that failed to execute, returned nothing, or fell over on a defect in this harness is an **incident**: it lands in `run.json → incidents[]`, the node is retried, and the substantive counter is untouched. Harness retries have their own counter (`loops.infraRetry`) so a node that cannot run twice still halts.

This is not bookkeeping pedantry. On the 20260806 run an args-as-string bug produced three researchers prompted with the word `undefined`, and the resulting empty round charged `loops.skeptic = 1` — half the human's review budget spent on a JSON defect. `loops.skeptic` exists to tell a human *"three agents cannot satisfy the skeptic on this, come look."* Anything else recorded there is a false signal.

When the skeptic does refute, the next round is **narrowed**: the orchestrator passes `round` and `priorRefutations` and re-asks only the refuted claims. Re-running the full question re-derives what already survived and invites the researchers to restate the refuted answer with fresh citations instead of engaging with the refutation.

## Entry modes

**Cold (default).** N0 → N1 → N2/N3 → Gate 1 → N4…N12. Every node runs.

**Warm start — `--from-prototype <path-to-GRADUATION.md>`.** A `/prototype` run that answered
its question has already established empirically what N2/N3 establish by argument, so the
fan-out is **substituted** rather than re-paid for. This is the graph's only sanctioned
bypass, and it is deliberately narrow:

| Node | Cold | Warm start |
|---|---|---|
| N0 init | runs | runs |
| N1 plan + evals | runs | runs — **not skippable**; `plan.md`, the eval harness, and the `expected_files`/`expected_lines` the N7 guard is computed from all originate here. A prototype proves an approach works; it establishes nothing about whether the criteria are measurable. The packet seeds the PM's questions, it does not replace the node. |
| N2 research | Workflow fan-out | **substituted** — packet copied to `research/from-prototype.md`, node recorded `{"status":"substituted","fanOutRan":false}` |
| N3 skeptic | 3 lenses | **substituted** — same record; `loops.skeptic` stays 0, because no round was attacked and none was lost |
| Gate 1 | research + harness review | **shortened** — harness proof, scope, the packet's *Established* list with its evidence, its *Still unknown* list as open risk, and its *faked → now in scope* list. Gate text must state that no independent refutation was attempted. Options gain **Run research anyway**. |
| N4–N12 | runs | unchanged — prototype code is unreviewed by construction and buys no relief from tests, guard, SQA, docs, or PR review |

Refuse to warm-start if the packet is missing or lacks its *Established* and *Still unknown*
sections; run cold instead. A missing packet is not a licence to skip research.

The cost case is the section below: N2/N3 was **~16.4M tokens** on run
`<run-id>`, the most expensive part of the graph. Substituting
it on evidence a prototype already produced is the largest single saving available — which is
exactly why it must be recorded honestly rather than quietly.

If N1's questions reveal the *Still unknown* list is large, the prototype graduated too early:
stop and send it back for another prototype round rather than pushing a thinly-evidenced plan
through Gate 1.

## Run state

```
~/.claude/pipeline-runs/<run-id>/
  run.json              graph state — nodes, status, timestamps, loop counters
  plan.md               PM output: scope, tasks, blast-radius estimate
  evals/
    EVAL-001.md         acceptance criteria, [auto] / [manual] tagged
    eval_001.py         runnable harness, exit 0 = all [auto] ACs pass
  research/
    findings-{1,2,3}.md three independent researcher outputs
    consensus.md        agreed answer + divergences
  skeptic/report.md     per-lens verdicts, refutations, residual risk
  gates/gate-N.md       what was shown, the decision, timestamp
  code/
    tests-red.md        test names ↔ AC mapping, initial failing output
    verify.md           lint, eval, guard, structure results
  sqa/report.md         findings, severity, bug IDs raised
  docs/summary.md       what was documented and where
  pr/{url,review.md}
  viz.html              artifact source, republished each transition
```

Run id: `<repo-slug>-<YYYYMMDD-HHMMSS>`.

**Bug ledger is separate and persistent**, keyed per repo, surviving across runs:

```
~/.claude/pipeline-runs/ledgers/<repo-slug>.md
```

Every bug gets `BUG-NNN`, the regression test that pins it, and a status. At N8 the SQA agent **first** re-verifies that every previously-closed bug's regression test still exists and passes — that is the "don't let bugs come back" mechanism.

## Agents

| Node | Agent | Model |
|---|---|---|
| N1 | `project-manager` | opus |
| N2 | `scout` ×1, then `researcher` ×3 | sonnet |
| N2.5 | `link-check` ×1 | haiku |
| N3 | `skeptic` — evidence lens | sonnet |
| N3 | `skeptic` — correctness, consequence | opus |
| N5, N6 | routed coding agent (below) | sonnet |
| N8 | `software-quality-engineer` | opus |
| N9 | `technical-writer` | sonnet |
| N11 | `pr-reviewer` | opus |

### Coding agent routing

Routed by what the task actually touches. The PM records the route in `plan.md`; the orchestrator does not re-decide it.

| Work | Agent |
|---|---|
| Python app code — Lambda handlers, Flask/API, data processing, boto3, pandas | `python-backend-engineer` |
| Terraform / Terragrunt / AWS infra | `cloud-engineer` |
| JavaScript, React, CSS, front-end | `frontend-ui-engineer` |
| Nextflow pipelines, containers | `nextflow-pipeline-engineer` |
| C# / XAML / WPF desktop | `wpf-desktop-engineer` |

A task spanning two domains is **split by the PM into two tasks**, run one at a time. Coding agents are never asked to work outside their domain.

## Cost discipline at N2/N3

Measured on run `<run-id>`: N2+N3 alone consumed **~16.4M tokens across 12 subagents**, of which the skeptic lenses were **89%**. The researchers were cheap (~1.7M/round) — they were not the cost, they were the *cause* of it.

Two failure modes drove the overrun, and the design above is aimed at both:

1. **Six agents each re-derived the same repo context.** Three opus skeptics independently walked the same worktree, 17–21 `Bash` calls apiece, writing their own test scripts, because nothing upstream had put the code in the payload. The **scout** now reads it once and its brief is injected into all six downstream prompts.
2. **The researchers answered a documentation question that the code had already settled.** Two of three made zero repo reads. They correctly reported that Redshift's tie ordering is nondeterministic; the consumer sorts whole rows and never re-pairs fields, so it could not matter — and the recommended remedy would have passed the eval harness while fixing nothing. `repoEvidence` is now a required schema field, and the harness **downgrades confidence to `low` in plain code** when a researcher cites no repo code. Compliance is not left to the model.

Related: the evidence lens is a link-reading job and runs on **sonnet**, with a **haiku** link-resolver having already resolved every cited URL. Previously it ran on opus and spent its turns on repo archaeology instead — 17 `Bash` calls, 1 `WebFetch`.

What deliberately survives: the skeptic writing and running its own experiments. The 300-trial permutation test is what produced the correct answer. That is not overhead — it is the node working.

## Cost discipline at N8

The same two diseases reappeared at N8 on the same run, and are fixed the same way. Full retrospective: `~/pipeline-optimization-plan.md`.

**1. The lenses each re-walked the repo.** The N2/N3 scout fix was never ported. It is now: one **sonnet scout** reads the diff, the test inventory, the eval ACs, the ledger — and above all the **runner wiring** — and its brief is injected into all four lens prompts. The runner-wiring field exists because four lenses independently rediscovered that a new test suite ran in no gate. Establishing that once turns four findings into one.

**2. Duplicate findings were paid for twice — once to find, once to verify.** Verification fans out per finding, so it is the cost centre of the node (22 of 26 agents on the first run). Findings are now **deduped in plain code before verification**, streaming, with no barrier: a claim registry clusters on title-token Jaccard plus filename, and later lenses attach as `corroboratedBy` rather than filing again.

Measured on the same run's real findings: **23 filed → 12 distinct, and 13 verify agents → 6 (54%).** Thresholds (0.40 cross-file, 0.25 same-file) were tuned against that data and reproduce the hand-audited dedupe exactly, with zero false merges. Nothing is discarded on a merge — `mergedTitles` and the union of repro steps ride along on the claim.

Two further changes came out of the same run:

- **Corroboration is now evidence, not noise.** A claim 3+ lenses filed independently that a single verifier then refutes is routed to `CONTESTED` and gated, not buried in `refuted`. On that run the security lens re-confirmed two findings the verify stage refuted, and the contradiction vanished silently.
- **`selfReproduced` is a required schema field.** A lens filed a finding it had explicitly not run, inherited from another lens through a clobbered ledger. Unreproduced findings are now downgraded to LOW and flagged `hearsay` in plain code.

Lenses run in **isolated worktrees** and write **per-lens ledger fragments**; the executor merges them. Both are RC3 fixes: concurrent lens writes clobbered the shared ledger (destroying entries and re-using IDs), and lens mutation of the shared worktree contaminated another lens mid-investigation.

**Not done, deliberately:** model tiering of the lenses. The obvious cut — drop the cheap-looking lenses to sonnet — is not supported by the data. The `security-standards` lens found the only genuine production-code defect in the entire diff. What the dedupe run *did* show is that `tests` and `correctness` contributed **zero** distinct bugs; everything they filed duplicated another lens. That is one run and lens ordering affects attribution, but the overlap itself is order-independent and worth re-measuring before anyone pays opus for four lenses again.

## The orchestrator's own context

Subagents are cheap to the executor: each has its own window and returns only a final message, so twelve agents spent ~16.4M without any of it landing in the main thread. The **executor's** context is the unbounded one — on the same run it peaked at 292k over 284 turns, **45.2M cumulative**, ~2.75× the entire N2/N3 subagent spend and the largest single line item in the run.

Three rules address it, and they apply at every node — the downstream half (diffs, lens reports, PR reviews) is heavier than research:

- **`run.json` is the memory.** Every node is recorded as it completes. On the 20260806 run, N2 and N3 executed fully and were never written to `nodes{}` — the graph could not be reconstructed from disk, which defeats resuming *and* the artifact.
- **Paths, not contents.** Agents write reports to `$RUN_DIR` and return a path and a summary. Pasting a diff or a report into a prompt copies it into two windows.
- **Gates are compaction boundaries.** The executor is already blocked on a human, so resuming costs nothing. `--resume` reloads state from `run.json` into a clean window, turning one 292k context into a series of short ones. This only works if `run.json` is complete, which is why the first rule comes first.

`viz.html` was its own tax: ~21KB authored and edited in-context at every transition to render values `run.json` already held. It is now generated by `render_viz.py`.

## The harness is part of the claim surface

Evals exist so "done" is measured rather than asserted. That only holds if the instrument itself is checked, and on the 20260806 run it was not:

- `eval_001.py` used `@contextlib.contextmanager` without importing `contextlib`. It died before a single AC executed. Exit 1 from a `NameError` is indistinguishable from exit 1 from honest red criteria, so **Gate 1 approved the plan on a per-AC table that had never existed** — and `run.json` recorded it as "validated by PM; executor independently re-confirmed red".
- AC2 claimed to test whether Redshift's ordering matched pandas', and computed its reference with `scrambled.sort_values("timestamps")` — the same call under test. Its fixture drew uniform floats, producing 30,000 rows with 30,000 distinct timestamps: **zero ties, in the criterion whose entire purpose was tie behaviour.** It passed a deliberately tie-order-sensitive implementation when tested.
- AC5 was meant to pin the query text. Its check, `re.search(r"ORDER\s+BY\s+timestamps", sql)`, matches `ORDER BY timestamps, gatingflags` as a prefix — so the one thing the human explicitly forbade at the gate would have passed the harness green.

Three rules follow, split across the agent that builds the harness and the executor that trusts it:

1. **The PM proves the harness before shipping it** — it loads (a per-AC table, not a traceback); every `[auto]` AC is red *on its assertion body*, not merely because the feature is absent; and every `[auto]` AC is mutation-proved in a scratch tree (passes a correct implementation, fails a plausible defect). The mutant used is recorded in `EVAL-NNN.md`.
2. **The executor runs the harness itself at N1** and records what it observed, in those words. "Verified by executor" is never written for a check that was not performed.
3. **Gate 1 states how the harness was proven**, not only what it scored. The human is approving the instrument as much as the plan.

## Cross-agent memory

Per-agent memory (`~/.claude/agent-memory/<agent>/`) is private and persists across runs. Lessons that would change how a *different* agent works go in **`_shared/`**, which every pipeline agent reads at task start.

The directory exists because of a specific loss: during the 20260806 run the skeptic wrote `pattern_read_the_repo_before_the_docs.md` into its own memory — precisely the lesson the researchers needed — and the researchers could not read it. The insight was learned, filed, and stranded in the same run.

## Shared coding protocol

Coding agents are not given a copy of the TDD / branch / change-guard rules in their own definition — that duplication is what rots. Instead the orchestrator passes `~/.claude/pipeline/CODING_PROTOCOL.md` in the task prompt and the agent reads it. One file, one place to change.

## Infrastructure safety

`terragrunt apply` and `terragrunt destroy` are **human-only** and are not nodes in this graph. For infrastructure tasks the pipeline ends at a reviewed `plan` attached to the PR; applying is yours.
