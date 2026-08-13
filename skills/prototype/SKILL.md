---
name: prototype
description: Build a quick, throwaway-friendly prototype through conversation instead of a spec. Ask a few sharp questions, then get something running fast and iterate on it with the user. Use for "let's prototype X", "mock something up", "can you spike this", "I want to see it working before we design it" — the opposite path from /pipeline's spec-driven build.
argument-hint: "<what you want to prototype>" [--omega_protocol] [--here] [--dir <path>] [--lang <python|js|...>]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion, Skill, Agent, WebFetch, WebSearch
---

# prototype

Get something **running** in front of the user fast, then iterate with them. Conversation
is the design process — the code is the deliverable, not a document about the code.

What you want to prototype: **$ARGUMENTS**

## The bargain this skill makes

A prototype buys **information** — whether an idea works, how it feels, whether the data
supports it — and pays for it with **rigor deliberately skipped**. That trade is only
honest if the skipped rigor is visible. So: move fast, hardcode freely, fake the hard
parts — and label every shortcut you take, every time.

The failure mode is not an ugly prototype. It is a prototype that gets **mistaken for
finished work**, or whose numbers get quoted as validated results. Guard that, and
everything else here is licence to go fast.

---

## Step 1 — Interview, briefly

Ask **one round** of `AskUserQuestion` — up to 4 questions, ideally 2–3. A second round is
allowed only if the first genuinely blocked you. If you find yourself on a third, you have
turned this into spec-driven design; stop asking and go build something they can react to.

Ask only what changes what you build. The highest-value questions are usually:

1. **What question is this prototype answering?** ("Do these metrics separate the
   populations?" is a different build from "Does this UI flow feel right?")
2. **What must be real, and what can be faked?** Real data with a fake UI, or real UI with
   synthetic data — this single answer shapes the whole build.
3. **Who sees it, and how?** A number in the terminal, a chart, a local web page, a
   published artifact.
4. **Is there existing code to build against, or is this greenfield?**

Do **not** ask about: error handling, tests, edge cases, auth, deployment, scale, naming
conventions, or file layout. Those are spec-driven concerns. In a prototype you pick a
default, note it, and move on.

Use `preview` on options when the choice is visual — a layout, an output shape, a chart
form. Seeing two mockups side by side resolves in one question what three rounds of prose
would not.

Then **state your assumptions in two or three lines and start building.** Do not seek
approval for the plan. If an assumption is wrong, the running prototype is the cheapest
possible way to find out.

### `--omega_protocol` — skip the interview

With `--omega_protocol`, **ask nothing.** Make every call yourself and start building
immediately. The user is telling you they would rather correct a wrong prototype than
answer questions about a hypothetical one.

- Decide the question, the real/faked split, the output form, and the stack yourself. Pick
  the boring option every time — the one already installed, the one that runs in one
  command.
- Bias hard toward **smaller**. An omega prototype that runs in three minutes and is 60%
  right beats a fifteen-minute one that guessed more ambitiously and missed.
- **Front-load the assumptions in your first message**, as a short list, before the code.
  This is the trade: the user gave up the questions, so they get the answers you assumed on
  their behalf in a form they can shoot down in one line. Skipping this makes the flag
  actively harmful.
- Then build, run, show. Same iteration loop from Step 4.

`--omega_protocol` skips **questions, not guardrails.** Everything under **Guardrails**
below still holds without exception — no prod, no apply, no push, no unlabelled fakes, no
writing to a production repo without `--here`. If an assumption you would have to make
involves touching production or spending real money, that is the one case where you stop
and ask anyway; say that the flag does not cover it.

## Step 2 — Pick the workspace

Default: **outside any production repo**, so prototype code can never quietly become
production code.

```bash
PROTO_DIR="$HOME/prototypes/$(TZ=America/Los_Angeles date +%Y%m%d)-<slug>"
mkdir -p "$PROTO_DIR" && echo "$PROTO_DIR"
```

- `--dir <path>` — use that path instead.
- `--here` — build in the current repo. Only with this flag, and if the repo is git-backed,
  work on a **throwaway branch or worktree** (`EnterWorktree`, or `git switch -c
  proto/<slug>`) and say so. Never leave prototype code sitting on a branch that ships.
- Reuse an existing `~/prototypes/*` dir when the user is clearly continuing one — check
  with `ls -1dt "$HOME/prototypes"/*/ | head -5` before creating a near-duplicate.

## Step 3 — Build the thinnest thing that runs

Optimise for **time-to-first-look**, not for structure. Rules of thumb:

- **One command to run it.** Put that command in `PROTOTYPE.md` and print it in chat.
- **One file until one file hurts.** Split only when it actually gets in the way.
- **Hardcode before you configure.** Constants at the top of the file beat a config system.
- **Synthetic data before real data**, unless the question *is* about the real data. When
  faking, make the shape realistic and the values obviously fake.
- **Fewest dependencies that work.** Prefer the stdlib and what is already installed;
  check before adding (`pip show` / `npm ls`). A prototype blocked on a dependency
  resolution is a prototype that taught you nothing.
- **Stub the expensive edges** — network calls, cloud services, warehouses, auth. A
  function returning a canned response is a legitimate prototype component.
- **Skip:** tests, error handling, logging frameworks, type rigor, docstrings on
  everything, abstractions with one implementation, and premature generality. If the user
  asks for tests, they are telling you this is no longer a prototype — see Step 6.

Write a short `PROTOTYPE.md` next to the code. This is the one piece of documentation the
skill insists on, because it is what stops a prototype being misread later:

```markdown
# Prototype: <name>

**Question it answers:** <the one thing this exists to find out>
**Run it:** `<exact command>`
**Status:** prototype — not tested, not reviewed, not production

## Real vs faked
- REAL: <what is genuine — data source, algorithm, integration>
- FAKED: <what is stubbed, hardcoded, or synthetic>

## Assumptions
- <the calls you made without asking>

## What I learned
<append as you iterate — this is the actual output of the exercise>
```

Then **run it** and show the user real output. A prototype you have not executed is a
guess. If it takes more than a couple of minutes to get to first-run, say what is taking
the time rather than going quiet.

## Step 4 — Iterate in the conversation

The loop is: **show → react → change → show**. Keep each turn small enough that the user
can hold the whole change in their head.

- Lead with what the user can see: the output, the number, the screenshot, the URL. Not a
  narration of what you edited.
- After each iteration, name the **one thing** you would change next and let them redirect.
  Do not present a five-item menu.
- When output is visual or comparative, publish an `Artifact` and hand over the link —
  faster to judge than terminal text. (Load `artifact-design` first, per that tool's
  contract.)
- When it is an app that needs launching, use the `run` skill rather than reinventing the
  launch dance.
- Update `PROTOTYPE.md`'s **What I learned** as findings land. That section, not the code,
  is usually what survives.
- **Throwing code away is a valid iteration.** If the second approach is clearly better,
  delete the first — do not carry it along out of sunk cost. Say that you are doing it.

### Honesty under speed

Speed is not licence to overstate. Never say a prototype "works" when you mean it ran once
on synthetic input. Report what you actually observed, and keep the real/faked split
current — a stub you added three iterations ago and forgot is how a prototype starts lying.

If the prototype produces **numbers in a scientific or diagnostic context**, they are
exploratory and must be labelled that way every time you report them. An unvalidated
metric from a prototype must never be handed onward as a result.

## Step 5 — Know when it has answered its question

A prototype is done when it has produced the information it was built for — not when it
feels finished. Say so plainly:

> This answers the question: <answer>. The prototype is at `<path>`. Next fork:
> throw it away, keep it as a scratch tool, or build it properly.

Then let the user choose. Do not start hardening on your own initiative.

## Step 6 — Graduation ramp to `/pipeline`

When the user wants the real thing, hand over rather than gradually upgrading the
prototype in place. Incremental hardening is how unreviewed prototype code ends up in
production with no tests and no plan.

**A prototype that answered its question has already done N2/N3's job — empirically.**
Research and the skeptic pass exist to establish whether an approach holds up; running code
that demonstrably works is stronger evidence than three agents agreeing about it. So
graduate into a **warm start** that skips the research fan-out, rather than paying for it
twice.

### Write the graduation packet first

Before invoking anything, write `GRADUATION.md` next to the prototype. This is the artifact
that replaces the research node, so it has to carry that weight:

```markdown
# Graduation packet: <name>

## Established by the prototype
<What now counts as known, and what demonstrated it. "Vectorised path holds 6-channel
plates in 84s — ran on 5 real plates from the corpus" — evidence, not assertion.>

## Approaches tried and rejected
<Each with the reason it lost. This is the most valuable thing here: it is precisely
what a fresh research pass would spend a fan-out rediscovering.>

## Still unknown
<What the prototype did NOT establish. Be honest and complete — everything omitted here
becomes an unexamined assumption in the real build.>

## Faked in the prototype — now in scope
<Every stub, hardcoded constant, and synthetic input. Each one is real work.>

## Reference implementation
`<path>` — reference only. NOT a starting diff, not reviewed, not tested.
```

### Then warm-start the pipeline

Invoke it as:

```
/pipeline "<goal>" --from-prototype <path-to-GRADUATION.md>
```

Which nodes actually change, and which do not:

- **N0 (init) still runs.** Clean tree check, run dir, `run.json`.
- **N1 (plan) still runs — do not try to skip it.** It produces `plan.md` *and the eval
  harness*, and its `expected_files`/`expected_lines` are what the N7 change guard is
  computed against. Without N1 there are no acceptance criteria to build toward, nothing for
  N7 to route on, and nothing for N8 to test. The prototype seeds N1's answers; it does not
  replace the node. Expect fewer PM questions, not zero.
- **N2/N3 (research + skeptic) are substituted, not skipped.** The packet is copied into
  the run's `research/` and `skeptic/` and the nodes are recorded as substituted, naming
  the packet path. They must never be recorded as though a fan-out ran — the run's own rule
  is that a silently-skipped node reading as green is the worst failure it can produce.
- **GATE 1 still fires, but it is a short gate.** Not a research review — an approval of the
  *eval harness* and the scope, with the packet's "still unknown" list shown as open risk.
  This gate is where the human confirms the criteria are measurable, which the prototype
  established nothing about.
- **N4 onward is unchanged.** Tests, implement, guard, SQA fan-out, docs, PR, fresh-context
  review. The prototype earns you no relief from any of it — its code is unreviewed by
  construction.

The one thing to watch: if the PM's questions at N1 reveal that the prototype's "still
unknown" list is large, that is the signal the prototype graduated too early. Say so and
offer another prototype round instead of pushing a thinly-evidenced plan through the gate.

If the situation reverses — the user starts a spec-driven build and hits a question no
amount of planning resolves — the reverse move is legitimate: prototype the unknown, then
resume the run.

---

## Guardrails

These hold no matter how fast you are moving:

- **Never `terragrunt apply` or `destroy`, never push, never open a PR** from a prototype.
  Infra prototyping ends at a plan you show the user. These are human-only steps.
- **Never point a prototype at production.** No prod credentials, no writes to prod
  buckets, tables, or warehouses. Dev/test read-only or local fixtures. If the question
  truly requires prod data, stop and ask.
- **Never modify a production repo without `--here`** and an explicit throwaway branch.
- **Never let prototype output masquerade as validated work** — no removing the prototype
  label to make a demo look better, and no reporting synthetic-data results as findings.
- **Watch for scope creep in disguise.** "Can you also handle…" three times in a row means
  this is a build, not a prototype. Name it and offer the graduation ramp.

## Relationship to the other skills

| | `/prototype` | `/pipeline` |
|---|---|---|
| Question | What should we build? | How do we build this safely? |
| Input | A hunch, in conversation | A decided goal |
| Design | The chat itself | PM plan, research, skeptic, gates |
| Output | Running code + what you learned | Tested, reviewed, documented PR |
| Tests | Skipped on purpose | TDD, SQA fan-out, regression ledger |
| Code fate | Often thrown away | Ships |

`/handoff` is orthogonal to both — it moves context to a fresh instance and brings back an
answer. Use it *from* a prototype session when a side question needs deep investigation you
do not want to spend this session's context on.

## When not to use this

- The change is understood and just needs doing — do it, or use `/pipeline` if it is large.
- The user asked for production code, tests, or a PR — that is `/pipeline`.
- The answer is a fact, not an artifact — look it up.
- Someone is depending on the result being correct. A prototype cannot carry that weight.
