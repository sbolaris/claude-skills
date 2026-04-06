# Skill: Two-Tier Documentation

**When to use:** After completing any feature or significant code change. Produces docs that serve both non-technical stakeholders and developers/agents being onboarded.

**Captured from:** BRAD `/document` command design session.

---

## The two tiers

### Tier 1 — High-Level (plain English)
**Audience:** Product owners, new team members, non-technical stakeholders
**Goal:** Understand *what* it does and *why* without reading code

Required sections:
- **What it does** — one paragraph, no jargon
- **Why it exists** — the problem it solves
- **How it fits in** — where it sits in the overall system/pipeline
- **Example** — concrete inputs, what happens, outputs
- **Limitations** — anything non-technical readers should know

Save to: `docs/high-level/<feature_name>.md`

---

### Tier 2 — Technical Reference
**Audience:** Human developers and Claude agents being onboarded
**Goal:** Everything needed to understand, modify, or integrate with this feature

Required sections:
- **Overview** — two sentences: what + where the code lives
- **File map** — table of files and their purpose
- **Data flow** — inputs → processing → outputs with exact types/shapes
- **Key classes and functions** — signature, purpose, args, return type, side effects
- **AWS resources touched** — service, operation, IAM permission required
- **Environment variables** — name, required/optional, description
- **Integration points** — upstream/downstream contracts (field names, status values)
- **Error handling** — how errors surface (return objects, HTTP codes, short-circuits)
- **How to test locally** — exact commands
- **Gotchas** — common mistakes when modifying this feature

Save to: `docs/technical/<feature_name>.md`

---

## Docs index

Maintain a `docs/README.md` with a table:

```markdown
| Doc | Type | Summary |
|-----|------|---------|
| [Feature](path) | High-level | One sentence |
| [Feature](path) | Technical  | One sentence |
```

---

## Why two tiers matter

- High-level docs get read by people deciding *whether* to use or change a feature
- Technical docs get read by people actually *doing* the work
- Mixing them makes both audiences skim past what they need
- Claude agents onboarding to a codebase benefit most from the technical tier — explicit contracts, gotchas, and exact test commands reduce errors
