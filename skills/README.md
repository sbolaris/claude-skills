# Skills Library

Reusable patterns and workflows captured from working sessions.
Each skill lives in its own folder (`<skill-name>/SKILL.md`).

This index mirrors the skills table in the [repository README](../README.md), which also
covers the agent team and the `/pipeline` graph.

## Claude Code & Workflow

| Skill | Folder | Summary |
|-------|--------|---------|
| **Conversational prototyping** (`/prototype`) | `prototype/` | **Invocable skill.** Non-spec-driven path: one capped round of questions, then the thinnest thing that runs, outside any production repo. `--omega_protocol` skips the interview (questions, not guardrails). Graduates into `/pipeline --from-prototype` via a `GRADUATION.md` packet |
| **Context handoff** (`/handoff`) | `handoff/` | **Invocable skill.** Session → pointers-only digest (paths + `file:line` + decisions + dead ends, never file bodies, 400-line cap) → fresh agent + one question → `FINDINGS.md` plus a ≤250-word summary back |
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

## AWS & Cloud

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

## Bioinformatics Pipelines

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

## QA & Testing

| Skill | Folder | Summary |
|-------|--------|---------|
| Jira regression test | `jira-regression-test/` | Convert Xray/Jira Test Execution PDF → structured Markdown; `jira_pdf_to_md.py` for deterministic pdftotext+layout parsing; multi-line headers, split PASSED tokens |
| Jira Playwright runner | `jira-playwright-runner/` | Agent-native regression runner; thin browser server via cmd/result JSON protocol; OKTA auth via one-time `--storage-state` session capture; same-screen Okta field gotcha |
| Playwright E2E (TypeScript) | `playwright-e2e/` | TS Playwright suite with Okta SSO, Xray/Jira test steps, MUI selectors, and demo-video output |
| Real-data test corpus (backward-trace) | `realdata-test-corpus-backward-trace/` | Assemble production-shaped test fixtures by querying the warehouse, joining downstream tables, mapping DB filenames to S3 keys; bite-proving assertions; encrypted fixture pattern |

## Data & Databases

| Skill | Folder | Summary |
|-------|--------|---------|
| Redshift optimization | `redshift-optimization/` | Query-level fixes (explicit cols, parameterized, dedup), DISTKEY/SORTKEY CTAS migration, Data API benchmarking — 44.5% end-to-end improvement |

## Vendor / Format Engineering

| Skill | Folder | Summary |
|-------|--------|---------|
| Vendor format round-trip diff | `vendor-format-round-trip-diff/` | Reverse-engineer closed-source vendor file formats by diffing native reference vs converter output; encrypted containers; phased fix plan; downstream-consumer regression audit |

## Not in this repo — `skills-local/`

Project-specific skills that name an employer's products, internal repositories, or
reverse-engineered vendor formats live in a gitignored `skills-local/` directory and install
alongside these via `install.sh`.


