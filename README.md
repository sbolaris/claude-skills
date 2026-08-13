# claude-skills

Portable Claude Code configuration — skills, a custom agent team, the `/pipeline` graph, and
global instructions — built from production engineering work. Clone it on a new machine and run
[`./install.sh`](#installation).

```
CLAUDE.md            global instructions → ~/.claude/CLAUDE.md
settings.json        shared settings (model, theme); machine-specific ones stay local
agents/<name>.md     the specialist agent team
commands/<name>.md   slash commands
skills/<name>/SKILL.md
pipeline/            the /pipeline graph: coding protocol + workflow scripts
install.sh           symlinks the above into ~/.claude
```

---

## Custom Agent Team — `agents/`

Drop agent files into `.claude/agents/` in any project. Claude routes tasks to the right
specialist automatically, or you can invoke them explicitly in your prompt.

Each file's `name:` frontmatter matches its filename, and each declares `memory:` frontmatter
rather than carrying an inline memory block — the harness supplies the memory instructions.

| Agent | File | When to Use |
|-------|------|-------------|
| Cloud Engineer | `cloud-engineer.md` | AWS infrastructure — Terraform/Terragrunt modules, deployments, troubleshooting |
| Cloud Security Auditor | `aws-cloud-security-auditor.md` | Security audit of AWS infra code (IAM, S3, Lambda, VPC) against NIST/CIS |
| Exec Admin Assistant | `exec-admin-assistant.md` | Project status summaries, pending-decision nudges, Slack briefings |
| Frontend UI Engineer | `frontend-ui-engineer.md` | React/JavaScript frontend — components, styling, state, animations |
| Nextflow Pipeline Engineer | `nextflow-pipeline-engineer.md` | Nextflow DSL2 pipelines, Docker/Singularity containers, AWS Batch |
| PR Reviewer | `pr-reviewer.md` | Fresh-context review of an open PR against the plan and evals; posts a GitHub review (pipeline N11) |
| Presenter | `presenter.md` | Slides and stakeholder-ready summaries for non-technical audiences |
| Project Coordinator | `project-coordinator.md` | Orchestrate research → implement → QA across multiple agents |
| Project Manager | `project-manager.md` | Turn a goal into a scoped plan, acceptance criteria, runnable evals, blast-radius estimate (pipeline N1) |
| Python Backend Engineer | `python-backend-engineer.md` | Python application code — Lambda handlers, Flask APIs, boto3, pandas/numpy, Redshift, and their tests |
| Researcher | `researcher.md` | Docs lookup, best-practice verification, error diagnosis |
| Skeptic | `skeptic.md` | Adversarially refute a research finding before it drives implementation (pipeline N3) |
| Software Quality Engineer | `software-quality-engineer.md` | Code quality review, unit/integration tests, standards compliance |
| SQA Regression Tester | `sqa-regression-tester.md` | Run regression tests from Jira PDF test sets via Playwright |
| Technical Writer | `technical-writer.md` | README, CLAUDE.md, API docs, runbooks after a feature is approved |
| WPF Desktop Engineer | `wpf-desktop-engineer.md` | WPF desktop apps — MVVM, data binding, custom controls, performance |

**Typical workflow with the full team:**
```
Researcher (verify approach) → Cloud Engineer / Nextflow Pipeline Engineer /
  Python Backend Engineer (implement) → Software Quality Engineer (validate)
  → Technical Writer (document)
```

For complex multi-phase work, `project-coordinator` orchestrates the above automatically.

---

## Graph Pipeline — `pipeline/` + `commands/`

A graph-based execution pipeline invoked with `/pipeline "<goal>"`:

```
plan → research → skeptic → human gate → TDD implementation → SQA →
  docs → PR → PR review → human gate → reviewer tagging
```

The main thread is the graph executor (a `Workflow` script cannot reach the human for gate
approval); `Workflow` is used only inside the two fan-out nodes. Run state lives in
`~/.claude/pipeline-runs/<run-id>/` — outside the repo, so a run leaves no footprint in the PR.

| File | Purpose |
|------|---------|
| `commands/pipeline.md` | The executable slash command — the graph executor the orchestrator follows |
| `pipeline/README.md` | Specification and source of truth for the graph, nodes, gates and loop caps |
| `pipeline/CODING_PROTOCOL.md` | Protocol handed to the coding agent at the TDD node |
| `pipeline/render_viz.py` | `run.json` → `viz.html`; the orchestrator never hand-authors the artifact |
| `pipeline/workflows/research-consensus.js` | Fan-out: scout → 3 independent researchers → 3 skeptic lenses |
| `pipeline/workflows/sqa-lenses.js` | Fan-out: scout → 4 parallel SQA lenses → adversarial verification |

Requires these agents: `project-manager`, `researcher`, `skeptic`, `python-backend-engineer`
(or another coding agent), `software-quality-engineer`, `technical-writer`, `pr-reviewer`.

**Two entry modes.** Cold (default) runs every node. `--from-prototype <GRADUATION.md>` warm-starts
from a `/prototype` run that already answered the question empirically: N2/N3 are **substituted**
(recorded `fanOutRan: false`, `loops.skeptic` untouched), Gate 1 shortens to a harness-and-scope
approval carrying the packet's *still unknown* list as open risk, and N0/N1/N4–N12 are unchanged —
N1 is not skippable because the eval harness and the N7 change-guard budget originate there. See
`pipeline/README.md` → **Entry modes**. Since N2/N3 was ~16.4M tokens on the 20260806 run, this is
the largest saving in the graph, which is why the substitution is recorded on disk and disclosed at
the gate rather than done quietly.

**Install:**
```bash
git clone <this-repo> /tmp/claude-skills && \
  mkdir -p ~/.claude/commands ~/.claude/pipeline/workflows ~/.claude/agents && \
  cp /tmp/claude-skills/commands/pipeline.md ~/.claude/commands/ && \
  cp /tmp/claude-skills/pipeline/*.md /tmp/claude-skills/pipeline/*.py ~/.claude/pipeline/ && \
  cp /tmp/claude-skills/pipeline/workflows/*.js ~/.claude/pipeline/workflows/ && \
  cp /tmp/claude-skills/agents/* ~/.claude/agents/ && \
  rm -rf /tmp/claude-skills
```

---

## Skills Library — `skills/`

### Claude Code & Workflow

| Skill | Folder | Summary |
|-------|--------|---------|
| **Conversational prototyping** (`/prototype`) | `prototype/` | **Invocable skill.** The non-spec-driven path: one capped round of questions (max 4; never asks about tests/auth/scale), then the thinnest thing that runs, in `~/prototypes/<date>-<slug>/` outside any production repo. `--omega_protocol` skips the interview entirely and front-loads assumptions instead — skips questions, **not** guardrails. `PROTOTYPE.md` tracks question / real-vs-faked / assumptions / what-I-learned. Graduates via a `GRADUATION.md` packet into `/pipeline --from-prototype`. Guardrails: no apply/push/PR, never point at prod, never let prototype numbers read as validated |
| **Context handoff** (`/handoff`) | `handoff/` | **Invocable skill.** Compacts a session into a pointers-only digest at `~/.claude/handoffs/<ts>-<slug>/DIGEST.md` — paths, `file:line`, decisions, dead ends, and what is *not* in any file; never file bodies, hard 400-line/20 KB ceiling. Hands it plus one question to a fresh agent, which writes `FINDINGS.md` and returns ≤250 words. `SendMessage` for follow-ups instead of a second cold handoff |
| Claude Code project setup | `claude-code-project-setup/` | CLAUDE.md writing, slash command workflows, agent-team wiring |
| Documentation patterns | `documentation-patterns/` | Two-tier docs (high-level + technical reference) after a feature ships |
| Agent workflows | `agent-workflows/` | Agent team structure, parallel launch, SQA handoff, PR workflow |
| Sub-agent commands | `sub-agent-commands/` | Creating `/plan` `/research` `/test` `/rework` `/document` slash commands |
| GitHub CI / PR review | `github-ci-pr-review/` | CI failure diagnosis, ruff lint fixes, rebase conflict resolution |
| Git workflow | `git-workflow/` | Use plain `git` over `gh` (not authed in enterprise); git-native PR/CI equivalents; user pushes manually; default branch may be `master` |
| Dependabot PR evaluation | `dependabot-pr-evaluation/` | Discover PRs via git (no token), categorise by risk, test against current codebase, phased branching |
| User-driven debugging | `user-driven-debugging/` | When user finds a fix manually (page refresh, restart) — find the in-app equivalent and wire it automatically |
| Upstream library workaround | `upstream-library-workaround/` | Buggy 3rd-party property: write a domain-named helper using the underlying flag, replace call sites, pin with unit tests |
| VS Code Remote SSH port forwarding | `vscode-remote-ssh-port-forwarding/` | Dev server not showing via VS Code SSH tunnel; stale PORTS panel fix; Vite host binding under SSH |

### AWS & Cloud

| Skill | Folder | Summary |
|-------|--------|---------|
| Amplify S3 Storage Browser | `amplify-storage-browser/` | React + Amplify v3 + Cognito + Terragrunt; custom actions; `onSelect` trap; infinite-loop fix; selection persistence; multi-account migration |
| Terragrunt project setup | `terragrunt-project-setup/` | Multi-module structure, remote state bootstrap, dependency wiring, multi-account pattern |
| Terragrunt security hardening | `terragrunt-security-hardening/` | ECR IMMUTABLE, KMS module (default_tags gotcha), S3 SSE-KMS rollout, IAM least-privilege for Lambda/Batch, secrets hygiene, VPC public IP disable |
| GitHub Actions + Terragrunt CI | `github-actions-terragrunt-ci/` | OIDC trust setup, path-filtered plan workflows, per-leaf plan strategy, TF state version mismatch, per-leaf PR comment (avoids 60K cap), Node 24 |
| S3 pre-compute cache | `s3-precompute-cache/` | Lambda containers pre-compute DB query results to S3; Flask serves presigned URLs; cache invalidation on re-ingest |
| Step Functions non-blocking post-process | `stepfunctions-nonblocking-postprocess/` | Optional per-item Map + nested Parallel after ingestion with Catch; ResultPath preservation; state name uniqueness |
| Lambda container audit | `lambda-container-audit/` | Pull deployed Lambda image by digest, diff against repo, build + push new image, update Lambda to SHA digest (not :latest) |
| Packer ECS Batch AMI | `packer-ecs-batch-ami/` | ECS-optimized AL2 AMI: 3-volume layout, AWS CLI v2 + Nextflow cliPath symlink, multi-region `ami_regions`, multi-account build, per-env tfvars |
| AWS account teardown | `aws-account-teardown/` | Full teardown of Amplify + Cognito + WAF + S3: destroy order, Cognito deletion-protection, out-of-state WAF IP set (lock token pattern), state bucket removal |
| React/Vite quality toolchain | `react-vite-quality-toolchain/` | ESLint 10 flat config (.mjs), Prettier, Vitest (v8 coverage), typed vite-env.d.ts, ErrorBoundary, amplify.yml security headers, GitHub Actions CI |
| LaunchDarkly + React (Okta) | `launchdarkly-react-integration/` | Flag targeting keyed off Okta group/role; `useEffect` firing before auth completes; identify-after-login; common failure modes |
| MySQL admin Lambda | `mysql-admin-lambda/` | VPC-connected, CLI-invokable Lambda to manage app-level MySQL users without a bastion or direct DB access |

### Bioinformatics Pipelines

| Skill | Folder | Summary |
|-------|--------|---------|
| Nextflow DSL2 | `nextflow-dsl2/` | Module patterns, channels, PE/SE handling, genomes config, container assignment |
| Nextflow testing | `nextflow-testing/` | Smoke tests, local tests, process debugging, CI checklist |
| Nextflow strict parser migration | `nextflow-strict-parser-migration/` | Fix lookup for Nextflow 24.04+/26.x strict parser: `def fn()`/`def x=v` in .config, top-level `if`, eager directive interpolation, `check_max` inlining |
| Bioinformatics reference vendoring | `bioinformatics-reference-vendoring/` | Vendor small annotations (miRBase, ERCC, blacklist) in `resources/` with `${baseDir}` paths; regenerator sub-workflow; size limit (~10 MB) |
| Docker containers | `docker-containers/` | Dockerfile patterns, conda pinning, multi-container builds, Nextflow integration |
| RNAseq reference | `rnaseq-reference/` | QC metrics (FastQC, STAR, Picard, dedup, counts), thresholds, biotypes, RPKM/TPM |
| UMI tools | `umi-tools/` | Comparison of fgbio, fgumi, umi-tools, rumi, UMICollapse |
| R-to-Python | `r-to-python/` | Checklist and function mapping for replacing R scripts in Nextflow pipelines |
| Legacy Python + conda | `legacy-python-conda/` | Python 2.7 conda env setup, pymongo/GridFS extraction, py2/3 compat patterns |

### QA & Testing

| Skill | Folder | Summary |
|-------|--------|---------|
| Jira regression test | `jira-regression-test/` | Convert Xray/Jira Test Execution PDF → structured Markdown; `jira_pdf_to_md.py` for deterministic pdftotext+layout parsing; multi-line headers, split PASSED tokens |
| Jira Playwright runner | `jira-playwright-runner/` | Agent-native regression runner; thin browser server via cmd/result JSON protocol; OKTA auth via one-time `--storage-state` session capture; same-screen Okta field gotcha |
| Playwright E2E (TypeScript) | `playwright-e2e/` | TS Playwright suite with Okta SSO, Xray/Jira test steps, MUI selectors, and demo-video output |
| Real-data test corpus (backward-trace) | `realdata-test-corpus-backward-trace/` | Assemble production-shaped test fixtures by querying the warehouse, joining downstream tables, mapping DB filenames to S3 keys; bite-proving assertions; encrypted fixture pattern |

### Data & Databases

| Skill | Folder | Summary |
|-------|--------|---------|
| Redshift optimization | `redshift-optimization/` | Query-level fixes (explicit cols, parameterized, dedup), DISTKEY/SORTKEY CTAS migration, Data API benchmarking — 44.5% end-to-end improvement |

### Vendor / Format Engineering

| Skill | Folder | Summary |
|-------|--------|---------|
| Vendor format round-trip diff | `vendor-format-round-trip-diff/` | Reverse-engineer closed-source vendor file formats by diffing native reference vs converter output; encrypted containers; phased fix plan; downstream-consumer regression audit |

### Not in this repo — `skills-local/`

Skills that name an employer's products, internal repositories, or reverse-engineered vendor
formats are kept in a gitignored `skills-local/` directory. `install.sh` layers them into
`~/.claude/skills` alongside the public ones, so a machine gets the full set while the repo
publishes only what is reusable by someone else. If a skill's specifics *are* its content,
genericizing it produces something both still-identifiable and less useful — put it here instead.

---

## Installation

### Whole config, new machine

```bash
git clone https://github.com/sbolaris/claude-skills.git ~/claude-skills
cd ~/claude-skills
./install.sh --dry-run   # see what it would do
./install.sh             # symlink into ~/.claude
```

`install.sh` links `agents/`, `commands/`, `skills/`, `pipeline/`, and `CLAUDE.md` into
`~/.claude/`, and **copies** `settings.json`. Anything it replaces is moved to
`~/.claude/backups/install-<timestamp>/` first. Runtime state — `projects/`, `sessions/`,
`history.jsonl`, `.credentials.json` — is never touched.

Symlinks are the default deliberately: a skill you refine mid-session is edited in the repo,
so `git status` shows the change and there is no copy-back step to forget. Use `--copy` if you
would rather the two be independent.

`settings.json` is copied rather than linked because Claude Code rewrites it when you change
model or theme via `/config` — through a symlink that would silently edit the repo.

### What is intentionally *not* in this repo

| Not committed | Why |
|---|---|
| `settings.local.json` | Machine-specific permission allow-rules with absolute paths. Let each machine accumulate its own. |
| `.credentials.json` | Auth token. |
| `memory/` | Project state and in-flight work — machine-local by choice. |
| `projects/`, `sessions/`, `history.jsonl`, `plugins/` | Runtime state; re-created on each machine. |

### Portability rules for contributors

- **Every skill needs YAML frontmatter, or Claude Code will not load it.** `name:` must be
  kebab-case and match the directory name exactly; `description:` is what the model matches
  against to decide the skill is relevant, so write it as *what this does and when to reach for
  it*, including the terms someone would actually say. A `SKILL.md` with no frontmatter is an
  inert document — it sits on disk and never fires.
  ```yaml
  ---
  name: my-skill
  description: "What it does, and when to use it — include trigger words."
  tags: [topic, tool]
  ---
  ```
- **No absolute home paths.** Write `$HOME/foo`, never `/home/<user>/foo`. One exception: a
  shebang is not shell-expanded, so `#!$HOME/...` silently fails — spell out the interpreter
  path there and say so.
- **No account IDs, bucket names, secret names, KMS aliases, or internal hostnames.** Use
  `<account_id>`, `<project>`, `<account-alias>` placeholders. This repo is public.
- **No single-repo assumptions in `agents/`.** An agent that hardcodes one project's layout is
  useless in the next one — tell it to read the repo's own `CLAUDE.md` instead.

### Before you push

This repo is public, so run a sweep over the whole tree — not just your diff — before pushing:

```bash
grep -rniE '\b[0-9]{12}\b|/home/[a-z]+|AKIA[0-9A-Z]{16}|-----BEGIN|\.okta\.com' . \
  --exclude-dir=.git
```

Twelve-digit account numbers, absolute home paths, access keys, private key headers, and
internal hostnames all mean stop. Sanitize the tip **and** check history — a value scrubbed
from the current files is still published if an earlier commit carries it
(`git log --all -S'<value>'` finds it).

Getting a value out of published history means rewriting with
[`git filter-repo`](https://github.com/newren/git-filter-repo) and force-pushing — and note
that a force-push does not delete the old commits from GitHub. They become unreachable but stay
fetchable by direct SHA until GitHub Support garbage-collects them on request. Recreating the
repo from a fresh initial commit avoids that entirely, which is why this history starts where it
does.

Neither approach recalls what was already public: search indexes, crawler caches, scraper
datasets, and existing clones keep their copies. Rewrite to stop further spread, and treat
anything that was published as burned.

### Single skill only

```bash
git clone --depth 1 https://github.com/sbolaris/claude-skills.git /tmp/claude-skills && \
  cp -R /tmp/claude-skills/skills/amplify-storage-browser ~/.claude/skills/ && \
  rm -rf /tmp/claude-skills
```

Copy the whole skill **directory**, not just `SKILL.md` — several skills ship helper scripts
alongside it (`jira-playwright-runner`, `jira-regression-test`).

### Agents into a single project

```bash
git clone --depth 1 https://github.com/sbolaris/claude-skills.git /tmp/claude-skills && \
  mkdir -p .claude/agents && \
  cp /tmp/claude-skills/agents/* .claude/agents/ && \
  rm -rf /tmp/claude-skills
```
