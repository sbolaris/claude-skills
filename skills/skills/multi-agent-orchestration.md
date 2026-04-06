# Skill: Multi-Agent Orchestration Patterns

**When to use:** Setting up or coordinating specialized agents that work together on a codebase — research, engineering, QA, documentation, and presentation agents.

---

## Agent team structure

| Agent | Role | When to invoke |
|-------|------|---------------|
| `researcher` | Investigate tools, APIs, best practices | Before implementation — gather context |
| `nextflow-pipeline-engineer` | Build/modify Nextflow pipelines, containers | Implementation of pipeline changes |
| `software-quality-engineer` | Review code, write tests, leave PR comments | After ANY code change — mandatory |
| `technical-writer` | Document features, update READMEs, CLAUDE.md | After SQA approval |
| `presenter` | Create diagrams, slides, visuals | When work needs to be communicated |
| `project-coordinator` | Orchestrate multi-phase tasks | Complex work spanning research → impl → QA |

## Parallel launch pattern

Launch independent agents simultaneously to maximize throughput:
- Research + documentation + engineering audit can all run in parallel
- SQA must wait until engineering is done (sequential dependency)
- Presenter can run in parallel with SQA

## Mandatory workflow: Engineering → SQA → Merge

1. Engineering agent creates a **feature branch** and **commits** changes
2. Engineering agent **pushes** the branch and creates a **PR** via `gh pr create`
3. SQA agent reviews the PR via `gh pr diff` and `gh pr review`
4. SQA leaves comments directly on the PR (approve / request changes)
5. If changes requested → engineering fixes on same branch, pushes, SQA re-reviews
6. Only after SQA approval → user merges

## PR handoff pattern

The project-coordinator must capture the PR URL from the engineering agent's output and pass it to the SQA agent:

```
Engineering output: "Created PR https://github.com/org/repo/pull/42"
                          ↓
SQA prompt: "Review PR #42 at https://github.com/org/repo/pull/42. 
             Use `gh pr diff 42` to see changes..."
```

## Agent memory locations

Each agent has persistent memory at `~/.claude/agent-memory/<agent-name>/` with a `MEMORY.md` index. Agents learn project-specific patterns over time.

## Shared skills

Skills at `~/.claude/skills/` are available to all agents. After completing significant work, capture reusable patterns as skills.

## Anti-patterns to avoid

- Don't launch SQA in parallel with engineering — it needs the finished code
- Don't skip SQA for "small" changes — all code changes get reviewed
- Don't have the engineering agent merge its own PR — user reviews first
- Don't duplicate work across agents — if researcher is investigating, don't also search for the same thing yourself
