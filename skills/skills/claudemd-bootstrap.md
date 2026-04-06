# Skill: CLAUDE.md Bootstrap

**When to use:** Setting up Claude Code on a new or existing project.

**Captured from:** BRAD CLAUDE.md creation session.

---

## What belongs in CLAUDE.md

CLAUDE.md is loaded into every Claude Code session. Keep it concise — future instances read it every time.

### Always include

1. **Project summary** — one paragraph: what it does, who uses it, key technology
2. **Setup** — exact commands to get a working dev environment, including any prerequisites that must exist *before* running setup (e.g. secrets, credentials, external services)
3. **Common commands** — build, test (single test + full suite), lint, deploy
4. **Architecture** — high-level structure that requires reading multiple files to understand; data flow between components; naming conventions that aren't obvious
5. **Code standards** — language-specific conventions, naming rules, patterns enforced in this project
6. **Key constraints** — things that will cause hard-to-diagnose failures if violated (e.g. "never use raw terraform", "always use async handlers", "agent code must live in its own subfolder")

### Do NOT include

- Generic best practices ("write unit tests", "handle errors gracefully")
- Things discoverable by reading one file
- Obvious instructions
- File listings that `ls` can provide

---

## Format that works well

```markdown
## Section

Short intro sentence if needed.

### Subsection (only if the section is complex)

- Bullet for short facts
- **Bold** the constraint or rule, plain text for explanation

\`\`\`bash
# Commands in code blocks with inline comments
\`\`\`

| Tables | for | structured data |
```

---

## Sub-agent commands section

If the project has `.claude/commands/`, add a table near the top:

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

---

## Checklist before finishing CLAUDE.md

- [ ] Can a new developer set up the project using only the Setup section?
- [ ] Are all "gotcha" constraints explicitly stated?
- [ ] Is the architecture section sufficient to understand data flow without reading every file?
- [ ] Are commands copy-pasteable and accurate?
- [ ] Is it under ~120 lines? (trim if longer)
