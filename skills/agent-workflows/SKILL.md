---
name: agent-workflows
description: Agent team structure, parallel launch patterns, SQA workflow, and PR handoff for multi-agent Claude Code projects
tags: [agents, orchestration, sqa, workflow, claude-code]
---

# Skill: Agent Workflows

**When to use:** Coordinating specialized agents that work together — research, engineering, QA, documentation, and presentation.

---

## Agent team

| Agent | Role | When to invoke |
|-------|------|---------------|
| `researcher` | Investigate tools, APIs, best practices | Before implementation — gather context |
| `cloud-engineer` | AWS infrastructure (Terraform/Terragrunt) | Infrastructure changes |
| `frontend-ui-engineer` | React/JS frontend work | UI implementation |
| `nextflow-pipeline-engineer` | Nextflow pipelines, containers | Pipeline changes |
| `software-quality-engineer` | Review code, write tests | After ANY code change — mandatory |
| `technical-writer` | Document features, update READMEs | After SQA approval |
| `presenter` | Diagrams, slides, visuals | Communicating work to stakeholders |
| `exec-admin-assistant` | Status summaries, Slack notifications | Project status updates |

---

## Parallel launch pattern

Launch independent agents simultaneously in a single message with multiple tool calls:
- Research + documentation audit + codebase exploration → all in parallel
- Implementation agents (cloud-engineer + frontend-ui-engineer) → parallel when independent
- SQA → must wait until all implementation is done (sequential dependency)
- Technical writer → can run in parallel with SQA

**Do NOT use project-coordinator for build tasks** — engineer directly and fan out SQA/docs.

---

## Standard engineering workflow

```
1. Research (if needed) — researcher agent
2. Implement — engineer agents in parallel where possible
3. SQA review — software-quality-engineer (mandatory before PR)
4. Fix blocking issues from SQA
5. Docs — technical-writer in background while fixing
6. Commit on feature branch — user pushes and reviews PR
```

---

## Feature branch + PR pattern

- Always create a feature branch (`git checkout -b feature/<name>`)
- Commit all changes with a descriptive message
- User pushes the branch manually and creates the PR
- Do NOT push or create PRs via gh CLI unless explicitly asked

---

## Handoff between agents

When passing work between agents, include in the prompt:
- Exact file paths of code that was written/modified
- What was decided and why (not just what was done)
- Any open questions or known issues

---

## Anti-patterns

- Don't launch SQA in parallel with engineering — it needs the finished code
- Don't skip SQA for "small" changes — all code changes get reviewed
- Don't have the engineering agent merge its own PR — user reviews first
- Don't duplicate work — if researcher is investigating, don't also search for the same thing yourself
- Don't use project-coordinator as a middleman for straightforward build tasks
- **Don't commit while SQA is still running** — SQA actively edits files mid-run; committing before it finishes captures a partial state. Check the output file or wait for the task notification before staging.

---

## SQA + docs parallel launch timing

```
Implementation complete
       ↓
Launch SQA + technical-writer IN PARALLEL (both in background)
       ↓
Wait for BOTH task notifications
       ↓
Stage + commit all changes in one shot
```

Technical writer can run fully in parallel with SQA — they touch different files (docs vs code).
SQA may edit source files — do not git-add until its notification arrives.

---

## Memory and skills

- Skills at `~/.claude/skills/` are available to all agents
- After completing significant work, save a new skill file and update the README
- Agent memory at `~/.claude/projects/<path>/memory/` persists across conversations
