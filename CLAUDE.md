# Global Claude Code Instructions

Installed to `~/.claude/CLAUDE.md`. These apply to every project on the machine.
Repo-specific conventions belong in that repo's own `CLAUDE.md`, which is authoritative
and overrides anything here.

## Researcher / Web Fetching Behavior

When doing web research (using the `researcher` skill or making direct WebFetch/WebSearch calls):

- **Burst limit:** Do at most **10 WebFetch calls** and **5 WebSearch calls** per research session.
- When you hit the limit, **stop fetching and summarize** what you have so far. Clearly flag any gaps or unverified claims.
- Do not loop indefinitely trying to find a perfect answer. Partial findings + a clear summary of what's still unknown is the right output.
- If the question genuinely needs more depth after the summary, ask the user whether to continue rather than running on autonomously.

## Researcher Consensus Rule (Factual Lookups)

For any factual lookup where an incorrect answer would break something — version numbers, release tags, API parameters, URLs, deprecation status — **always spawn 3 researcher agents in parallel** with the same prompt and require consensus before using the result:

1. Run all 3 agents simultaneously via parallel Agent tool calls.
2. If **2 or more agree** on the same answer, use that answer and note the consensus.
3. If **all 3 disagree**, do NOT use any of the answers — instead make a direct `WebFetch` to the authoritative source (e.g. the GitHub releases page, official docs) and use that result.
4. Always report what the agents returned and which answer was selected, so the user can see the verification trail.

This rule applies whenever spawning a `researcher` subagent for version/tag/API lookups. It does not apply to exploratory or open-ended research questions where there is no single correct answer to verify.
