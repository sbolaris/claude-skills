---
name: handoff
description: Compact the current session into a pointers-only markdown digest on disk, hand it plus a question to a fresh agent instance, and relay that agent's findings back here. Use when you want a second pair of eyes, a deep dive, or a long investigation done without spending this session's context — "hand this off", "ask a fresh instance", "/handoff <question>".
argument-hint: "<question>" [--agent <type>] [--model <sonnet|opus|haiku>] [--dir <path>] [--reuse]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, SendMessage, AskUserQuestion
---

# handoff

Hand the current session's working state to a **fresh model instance** along with one question, and bring back only its answer.

The whole value of this skill is **context economy in both directions**:

- The digest you write is **authored, not copied** — paths and one-line facts, never file bodies. The fresh instance reads the files it needs itself, in *its* context, not yours.
- What comes back is a **short summary plus a path**, not a report pasted into this window.

If you find yourself pasting anything you already have in context into the digest, you have defeated the point. Stop and write a pointer instead.

Question / arguments: **$ARGUMENTS**

---

## Step 0 — Parse arguments

| Flag | Default | Meaning |
|---|---|---|
| (bare text) | *required* | The question for the fresh instance |
| `--agent <type>` | `general-purpose` | Subagent type (e.g. `researcher`, `python-backend-engineer`, `cloud-engineer`, `skeptic`, `Explore`) |
| `--model <tier>` | inherit | Model override for the subagent |
| `--dir <path>` | auto | Where to write the handoff packet |
| `--reuse` | off | Reuse the most recent digest in `~/.claude/handoffs/` instead of writing a new one |

If no question was given, ask for one with `AskUserQuestion` — do **not** invent one. A handoff without a question produces a report nobody asked for.

Pick the agent type from the question's shape, and say which you picked and why in one line. If the question is a **factual lookup where a wrong answer breaks something** (version numbers, release tags, API params, URLs, deprecation status), the user's standing consensus rule in `~/.claude/CLAUDE.md` applies: spawn **3 `researcher` agents in parallel** on the same digest and require 2-of-3 agreement. Mention that you are doing so.

## Step 1 — Create the packet directory

```bash
HANDOFF_DIR="$HOME/.claude/handoffs/$(TZ=America/Los_Angeles date +%Y%m%d-%H%M%S)-<slug>"
mkdir -p "$HANDOFF_DIR" && echo "$HANDOFF_DIR"
```

`<slug>` is 2–4 kebab-case words from the question. Use `--dir` verbatim if given. The path lives under the user's home, so they can open, edit, and re-use it — and it survives this session.

With `--reuse`, resolve the latest instead and skip Step 2:

```bash
ls -1dt "$HOME/.claude/handoffs"/*/ | head -1
```

## Step 2 — Write `DIGEST.md`

One `Write` call. Fill only the sections you actually have — delete the rest rather than writing "N/A" filler.

```markdown
# Handoff digest

- **Written:** <YYYY-MM-DD HH:MM PST>
- **From session cwd:** <absolute path>
- **Repo / branch / dirty:** <repo or "not a git repo"> / <branch> / <clean|N files modified>
- **Packet dir:** <HANDOFF_DIR>

## Objective
<1–3 sentences: what this session is trying to accomplish overall.>

## State of play
<5–15 bullets. What is done, what is in flight, what is broken. Each bullet one line.
State facts, not narration: "ingestion Lambda times out at 600s on 6-channel plates",
not "we spent a while looking at the Lambda".>

## Key paths
<The map the fresh instance navigates by. Path — what it is — why it matters. Line
refs where they pin something specific. NEVER the contents.>

- `path/to/file.py:412` — `run_stats()` entry point — the timeout originates here
- `path/to/dir/` — 4 Terragrunt stacks — only `foo/` is in scope
- `~/some-plan.md` — the agreed plan — authoritative over anything I say here

## Commands and outcomes
<What was run and the one-line result. Command + verdict, never the output.>

- `pytest tests/test_stats.py` — 47 pass, 2 fail (`test_rain_guard`, `test_cvp`)
- `terragrunt plan` in `live/dev/ingestion` — clean, 3 changes, not applied

## Decisions and constraints
<Choices already made and not up for re-litigation, plus hard limits: no apply,
no push, must stay backward compatible, human-only steps.>

## Dead ends
<What was already tried and did not work, so the fresh instance does not repeat it.>

## Open questions
<What is genuinely unresolved — including anything I am unsure of. Flag inference as
inference; do not launder a guess into a fact for the next instance to build on.>

## Environment and access
<AWS profile / account, cluster names, endpoints, tool versions — only what is needed
to act. No secrets, no tokens, no credentials.>

## The question
<The question, verbatim and self-contained. If it has sub-parts, number them.
State explicitly what a good answer looks like: a diagnosis, a patch, a
recommendation, a yes/no with evidence.>
```

### Hard rules for the digest

**Never include:**

- File contents, or excerpts longer than 3 lines. Give `path:line` instead.
- Diffs, `git log` output, full test output, log dumps, stack traces beyond the top frame.
- Long JSON/YAML/HCL blobs, base64, or anything machine-generated.
- Secrets, tokens, keys, credentials, or full connection strings.
- Restatements of what the files already say. If the fresh instance can learn it by reading `foo.py`, the digest says "read `foo.py`".

**Always include:** what is *not* in any file — why the current approach was chosen, what was ruled out, what the human said, and what you are uncertain about. That is the only information a fresh instance genuinely cannot recover on its own, and it is what makes a handoff worth more than "go read the repo".

### Verify the budget before launching

```bash
wc -lc "$HANDOFF_DIR/DIGEST.md"
```

Ceiling: **400 lines / 20 KB**. Over it means you pasted something — find it, replace it with a pointer, rewrite. Do not launch an over-budget digest; a bloated digest costs the fresh instance the same context you were trying to save.

## Step 3 — Launch the fresh instance

One `Agent` call (or three in one message for the consensus case). The prompt is **short by design** — it carries the path, not the content:

```
Read `<HANDOFF_DIR>/DIGEST.md` first. It is a pointers-only briefing from another
Claude Code session: paths, decisions, dead ends, and one question.

Answer the question at the end of that digest.

How to work:
- Read only the files the digest points you to, and only what you need of them. You
  have your own full context — use it on the real files rather than on guessing.
- Verify before asserting. If you claim a test fails, run it. If you claim a line is
  wrong, read it. Report what you actually ran.
- The digest may be wrong or stale. If a path is gone or a stated fact does not hold,
  say so explicitly — that is a finding, not an obstacle.
- Do not make changes outside the scope of the question. <If read-only: "Do not modify
  any files; investigate and report only.">

Deliverable, both parts required:
1. Write the full answer to `<HANDOFF_DIR>/FINDINGS.md` — evidence, file:line refs,
   commands run and their real results, and anything you could not verify.
2. Return, as your final text, at most 250 words: the verdict, the 3–6 findings that
   matter, and any blocking question. Your caller's context is nearly full — the file
   is the report, your return value is the summary. Do not restate FINDINGS.md.
```

Set `run_in_background: true` (the default) so the user can keep working; the notification brings you back. Set it to `false` only if the user's very next step depends on the answer and nothing else can proceed.

Add `isolation: "worktree"` if the question invites edits to a git repo the user is also working in.

## Step 4 — Relay to this session

When the agent returns:

1. **Relay its summary** — the agent's final text is never shown to the user, so a handoff you do not relay is a handoff that did not happen. Report it faithfully, including anything it could not verify or flagged as uncertain. Do not upgrade its hedges into certainty.
2. **Give the paths** — `FINDINGS.md` for the detail, `DIGEST.md` for what was sent. Let the user pull the detail in if they want it.
3. **Do not `Read` `FINDINGS.md`** unless you need a specific fact to take the next action. Reading it is exactly the context spend this skill exists to avoid.
4. **Flag disagreement** — if a finding contradicts something established in this session, say so plainly rather than silently adopting it. Subagents are wrong sometimes.
5. For the 3-agent consensus case, report what each returned and which answer was selected. If all three disagree, escalate per the consensus rule (direct fetch of the authoritative source) rather than picking a favourite.

## Step 5 — Follow-ups

To ask the same instance more, use `SendMessage` with the agent's name — its context is intact, and it has already read the files. That is far cheaper than a second handoff. Append new context to `DIGEST.md` first if the situation moved; mention that you did.

A new `Agent` call starts cold and re-reads everything. Only do that for a genuinely different question.

---

## Guardrails

- **Never fabricate findings.** If the agent dies, returns nothing, or is skipped, say that and stop. A confident-sounding invented answer is the worst thing this skill could produce.
- **Never claim a background agent's result before its notification arrives.** If the user asks in the meantime, the honest answer is "still running".
- **The digest is a summary, not a decision.** It does not authorise the fresh instance to apply Terraform, push, or open PRs — those stay human-only per the user's standing preferences. State that constraint in the digest when infra or git is in scope.
- **Packets accumulate.** `~/.claude/handoffs/` is never auto-pruned. If the user wants it cleaned, show them what would go first.

## When not to use this

- The question is answerable from what is already in context — just answer it.
- A single file needs reading — read it.
- The work is a broad code search — `Explore` or `Agent` directly; no digest needed.

Use it when the *background* is the expensive part to reconstruct: a long session, a
subtle bug, a plan with history, several dead ends already burned.
