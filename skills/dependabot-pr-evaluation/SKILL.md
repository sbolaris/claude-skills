---
name: dependabot-pr-evaluation
description: "Evaluate stale Dependabot PRs, test them against the current codebase, and merge in phases without breaking the build. Use for dependency bumps, vulnerability remediation, or a backlog of open Dependabot PRs."
tags: [dependabot, dependencies, security, ci]
---

# Dependabot PR Evaluation & Safe Merge

Workflow for evaluating stale Dependabot PRs, testing them against the current codebase, and merging in phases without breaking the build.

---

## The Core Problem: Stale Branches

Dependabot PRs are created against the base branch at a point in time. If the base branch gets new commits (features, new deps) between when the Dependabot PR was opened and when you try to merge it, the branch becomes stale — it won't have the new files and packages, so it will fail to build even if the deps change itself is harmless.

**Never test Dependabot branches directly.** Always test the deps change against the current codebase.

---

## Step 1 — Discover open PRs with git (no gh token needed)

```bash
git fetch --all
git branch -r | grep dependabot
```

For each branch, check what's unique vs the base:
```bash
git log origin/master..origin/dependabot/<branch> --oneline
```

Check what actually changed in package.json and lockfile:
```bash
git diff origin/master..origin/dependabot/<branch> -- web/package.json
git diff origin/master..origin/dependabot/<branch> -- web/package-lock.json \
  | grep '"name"\|"version"\|"resolved"' | grep '^[+-]' | grep -v '^---\|^+++'
```

---

## Step 2 — Categorise by risk

| Type | Example | Risk | Action |
|------|---------|------|--------|
| Patch transitive dep | postcss 8.5.9 → 8.5.12 | Low | Group into one safe-bumps branch |
| Minor transitive dep | fast-xml-parser 5.5 → 5.7 | Low | Same safe-bumps branch |
| Major build tool | vite 5 → 6 | Medium | Own branch, check breaking changes |
| Multi-major jump | vite 5 → 8 | High | Skip / close manually |

Check if transitive deps are already satisfied by existing lockfile before doing anything:
```bash
npm ls <package-name>
```
Often a newer top-level dep already pulled in the version Dependabot wants.

---

## Step 3 — Test deps against current codebase (not Dependabot branch)

The right test is: do the new dep versions work with the **current** source code?

```bash
# Copy current source, swap in Dependabot's lockfile, build
cp -r web /tmp/test-branch
cp /tmp/pr-branch/web/package-lock.json /tmp/test-branch/
rm -rf /tmp/test-branch/node_modules
cd /tmp/test-branch && npm ci && npm run build
```

Or for transitive-only changes, just run `npm update <pkg>` on the current branch and check if it resolves and builds.

---

## Step 4 — Phased branching strategy

Branch off the **working base branch** (not master if something else is about to merge):

```
base-branch (e.g. feature/alternative-auth)
  └── deps/safe-bumps   ← patch/minor transitive deps, all grouped
        └── deps/vite-6 ← major build tool upgrade, isolated
```

### Safe bumps branch

For transitive deps (lockfile only, no package.json edit):
```bash
git checkout -b deps/safe-bumps
cd web
npm update postcss fast-xml-parser @aws-sdk/xml-builder   # etc.
npm run build   # must pass
git add web/package-lock.json
git commit
```

### Major version upgrade branch

For direct devDeps (package.json + lockfile):
```bash
git checkout -b deps/vite-6
cd web
npm install vite@6.4.2
npm run build   # must pass
# Also smoke-test: npm run dev, confirm server starts
git add web/package.json web/package-lock.json
git commit
```

Before upgrading a major build tool, check:
1. Does the plugin still support the new version? (`peerDependencies` in plugin's package.json)
2. Are there deprecated config options in `vite.config.ts`? (check migration guide)
3. Node.js version requirement met?

---

## Step 5 — Verify deps already satisfied

Before writing an update command, check resolved versions:
```bash
npm ls <package>
```
If already at the target version, the Dependabot PR is already satisfied — no action needed, it will auto-close when the base branch is updated.

---

## Step 6 — Dependabot auto-close behaviour

After your changes land on the target base branch, Dependabot runs its next scheduled check (usually within 24h of a push) and auto-closes PRs where the dep is now at or above its target version.

**Will auto-close:** patch/minor bumps where you're now at ≥ target version  
**Will NOT auto-close:** PRs targeting a version higher than what you merged (e.g. you merged vite 6, Dependabot PR targets vite 8 — still open)

Close the skip-worthy PRs manually with a comment explaining why (e.g. "skipping vite 8 until ecosystem matures"). To prevent Dependabot from reopening, add an ignore rule to `.github/dependabot.yml`:

```yaml
updates:
  - package-ecosystem: npm
    directory: /web
    ignore:
      - dependency-name: vite
        versions: [">=8.0.0"]
```

---

## Live server testing (VS Code Remote)

```bash
# Start dev server accessible from VS Code port forwarding
npm run dev -- --host 0.0.0.0 --port 5173
```

In VS Code: **PORTS** tab → Forward Port 5173 → click globe icon.

If browser shows "pending": remove the port forward, kill the server, restart it in foreground (not `&`), VS Code will auto-detect and re-add the port.

Auth notes: MSAL `redirectUri` is `window.location.origin` — Azure App Registration must have `http://localhost:5173` added as an allowed redirect URI for local dev to work.

Kill server when done:
```bash
kill $(lsof -ti :5173)
```
