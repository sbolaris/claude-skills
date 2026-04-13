---
name: claude-code-project-setup
description: Writing CLAUDE.md and setting up slash command workflows for Claude Code projects
tags: [claude-code, claudemd, project-setup, slash-commands]
---

# Skill: Claude Code Project Setup

**When to use:** Setting up Claude Code on a new or existing project — writing a CLAUDE.md and optionally adding slash command workflows.

---

## What belongs in CLAUDE.md

CLAUDE.md is loaded into every Claude Code session. Keep it concise — every instance reads it.

### Always include

1. **Project summary** — one paragraph: what it does, who uses it, key technology
2. **Setup** — exact commands to get a working dev environment, including prerequisites that must exist *before* running setup (secrets, credentials, external services)
3. **Common commands** — build, test (single + full suite), lint, deploy
4. **Architecture** — structure that requires reading multiple files to understand; data flow between components; naming conventions that aren't obvious
5. **Code standards** — language-specific conventions, naming rules, patterns enforced in this project
6. **Key constraints** — things that will cause hard-to-diagnose failures if violated (e.g. "never use raw terraform", "agent code must live in its own subfolder")

### Do NOT include

- Generic best practices ("write unit tests", "handle errors gracefully")
- Things discoverable by reading one file
- File listings that `ls` can provide

---

## Format that works well

```markdown
## Section

Short intro sentence if needed.

### Subsection (only if complex)

- Bullet for short facts
- **Bold** the rule, plain text for the explanation

\`\`\`bash
# Commands in code blocks with inline comments
\`\`\`

| Tables | for | structured data |
```

---

## Checklist before finishing CLAUDE.md

- [ ] Can a new developer set up the project using only the Setup section?
- [ ] Are all "gotcha" constraints explicitly stated?
- [ ] Is the architecture section sufficient to understand data flow without reading every file?
- [ ] Are commands copy-pasteable and accurate?
- [ ] Is it under ~120 lines? (trim if longer)

---

## Slash command workflows (optional but recommended)

Add a `.claude/commands/` directory with files that Claude Code invokes as `/command-name`. Each command is a focused sub-agent with a single job.

### File structure

```
.claude/
└── commands/
    ├── plan.md       # Plan before writing code
    ├── research.md   # Explore codebase/topic
    ├── test.md       # Run tests, report failures
    ├── rework.md     # Fix errors and re-verify
    └── document.md   # Write high-level + technical docs
```

### The five commands

| Command | Job | Rule |
|---------|-----|------|
| `/plan <task>` | Read code, output a numbered implementation plan with file paths and test cases | Does NOT write code — waits for approval |
| `/research <topic>` | Deep-dive into one area; return relevant files, patterns, gotchas, reusable code | No side effects |
| `/test [scope]` | Run appropriate test suite; report pass/fail with root cause per failure | Does NOT fix — keeps concerns separated |
| `/rework <error>` | Trace root cause, apply minimal fix, re-run tests | Checks project-specific gotchas |
| `/document <feature>` | Write high-level + technical docs; update index | See documentation-patterns skill |

### Recommended workflow

```
/plan <task>    → review plan → approve
implement
/test           → if failures:
/rework <error> → until green
/document <feature>
```

### Template: minimal command file

```markdown
You are a <role> sub-agent. <One sentence job description>.

Input: $ARGUMENTS

## Step 1 — <first action>
...

## Output
<What to produce and where to save it>
```

### Rules for good commands
- Each command does one thing only — no fixing in `/test`, no implementing in `/plan`
- Always read code before producing output
- Reference project-specific constraints (CLAUDE.md rules) in `/rework`
- End with a clear output: what is produced, where it is saved

### Add to CLAUDE.md when slash commands are present

```markdown
## Sub-Agent Workflows

| Command | When to use |
|---------|-------------|
| `/plan <task>`      | Before writing code |
| `/research <topic>` | When unfamiliar with an area |
| `/test [scope]`     | After writing code |
| `/rework <error>`   | When tests fail |
| `/document <feat>`  | After code works |

Recommended flow: `/plan` → implement → `/test` → `/rework` → `/document`
```
