---
name: git-workflow
description: "Git conventions for external or customer repos, preferring plain git over the gh CLI when no GitHub token is available. Use for branching, PRs, and remote operations in enterprise environments."
tags: [git, github, workflow]
---

# Git Workflow — External Repos

Default conventions for working in external/customer repos. Reach for plain `git` over `gh` whenever possible — the user works in a VS Code enterprise environment with built-in HTTPS auth, and `gh` is usually not installed or not authed.

## Use git, not gh

For nearly everything you'd reach for `gh` to do, there's a git-native equivalent that works without a GitHub token:

| Goal | Don't | Do |
|------|-------|-----|
| See PRs on a branch | `gh pr list --head <branch>` | `git ls-remote origin 'refs/pull/*/head'` + `git log origin/<branch>` |
| Check what a PR contains | `gh pr view <num>` | `git fetch origin pull/<num>/head:pr-<num>` then `git log pr-<num>` and `git diff master..pr-<num>` |
| See commits ahead of base | `gh pr view --json commits` | `git log <base>..HEAD` (use the actual default branch — could be `master` or `main`) |
| Check CI status | `gh run list` / `gh pr checks` | Ask the user to paste the run URL or status; or open the PR page in the browser |
| Find the default branch | `gh repo view --json defaultBranchRef` | `git remote show origin \| grep 'HEAD branch'` or look at `origin/HEAD` |
| Open the PR creation page | `gh pr create` | Push the branch, then tell the user the `https://github.com/<org>/<repo>/compare/<base>...<branch>` URL |

## Don't push or create PRs for the user

The user pushes branches manually and creates PRs through the GitHub UI. After committing:

1. State the branch name and how many commits ahead of base
2. Give the push command (`git push -u origin <branch>` for first push, `git push` for updates)
3. Give the PR compare URL if a new PR is needed
4. Stop there — do not run `git push` yourself unless explicitly told to

## Don't auth with extracted credentials

Never extract VS Code's stored git credential helper output and feed it to `curl`/`gh`/API calls. That was tried once and rejected. The HTTPS credential helper is for git operations only.

## Default branch is not always `main`

Several of these repos use `master`. Always check `origin/HEAD` or `git remote show origin` before assuming. Commands like `git log main..HEAD` will fatal out with "unknown revision" — that's usually the signal that the default is `master`.

## Finding work on a branch without gh

```bash
# What's ahead of the default branch?
git fetch origin
DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')
git log --oneline origin/$DEFAULT..HEAD

# Which remote branches exist for related work?
git branch -r | grep -i <keyword>

# What's in a remote branch you don't have locally?
git fetch origin <branch>:<branch>
git log --oneline <base>..<branch>
```

## Fetching a specific PR by number

```bash
git fetch origin pull/123/head:pr-123
git checkout pr-123      # to inspect
git diff master..pr-123  # what it changes
```

## Triggering CI re-runs

You can't trigger a re-run without `gh` or the GitHub UI. If CI needs to re-run after a fix:
- Commit the fix and tell the user to push it
- Or, if the fix isn't a code change, tell the user to click "Re-run jobs" in the GitHub UI

Don't push an empty commit (`git commit --allow-empty`) just to nudge CI — it pollutes history. Make the fix real or wait for a UI trigger.

## When the user explicitly asks for gh

If the user says "use gh to ..." treat that as a one-time override for that request. Don't generalize it back to defaulting to gh in the next step.

## Related skills

- `github-ci-pr-review.md` — diagnosing failing CI runs and fixing them on the branch
- `github-actions-terragrunt-ci.md` — terragrunt-specific CI patterns
- `dependabot-pr-evaluation.md` — assessing Dependabot PRs using git-only commands
