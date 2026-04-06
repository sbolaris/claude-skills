# Skill: Sub-Agent Slash Commands

**When to use:** Any project where you want structured, repeatable workflows for planning, researching, testing, fixing, and documenting code.

**Captured from:** BRAD project setup session.

---

## What this skill does

Creates a set of slash commands in `.claude/commands/` that Claude Code can invoke with `/command-name`. Each command acts as a focused sub-agent with a specific job, keeping work separated and reviewable.

---

## File structure to create

```
.claude/
├── commands/
│   ├── plan.md       # Plan before writing code
│   ├── research.md   # Explore codebase/topic
│   ├── test.md       # Run tests, report failures
│   ├── rework.md     # Fix errors and re-verify
│   └── document.md   # Write high-level + technical docs
└── skills/
    └── ...           # This library
```

---

## The five commands and their jobs

### `/plan <task>`
- Reads existing code to understand conventions
- Checks project constraints (CLAUDE.md, folder rules, IAM limits)
- Outputs a numbered implementation plan with file paths, signatures, and test cases
- **Does NOT write code** — waits for approval first

### `/research <topic>`
- Deep-dives into one area of the codebase
- Returns: relevant files, key patterns to follow, gotchas, reusable code to avoid reimplementing

### `/test [scope]`
- Runs the appropriate test suite (unit, integration, E2E, linting)
- Reports pass/fail with root cause per failure
- **Does NOT fix** — keeps concerns separated

### `/rework <error>`
- Traces root cause of a failure
- Applies the minimal targeted fix
- Re-runs tests to verify
- Checks project-specific gotchas

### `/document <feature>`
- Writes `docs/high-level/<feature>.md` — plain English for non-technical readers
- Writes `docs/technical/<feature>.md` — full reference for developers and Claude agents
- Updates `docs/README.md` index

---

## Recommended workflow

```
/plan <task>        → review plan → approve
implement
/test               → if failures:
/rework <error>     → until green
/document <feature>
```

---

## Template: minimal command file

```markdown
You are a <role> sub-agent. <One sentence job description>.

Input: $ARGUMENTS

## Step 1 — <first action>
...

## Step 2 — <second action>
...

## Output
<What to produce and where to save it>
```

---

## Key rules for good commands
- Each command does one thing only — no fixing in `/test`, no implementing in `/plan`
- Always read code before producing output
- Reference project-specific constraints (e.g. CLAUDE.md rules) in `/rework`
- End with a clear output: what is produced, where it is saved
