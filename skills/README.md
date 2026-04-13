# Skills Library

Reusable patterns and workflows captured from working sessions.
Each skill lives in its own folder (`<skill-name>/SKILL.md`) with YAML frontmatter.

## Claude Code & Workflow

| Skill | Folder | Summary |
|-------|--------|---------|
| Claude Code project setup | `claude-code-project-setup/` | Writing CLAUDE.md + setting up slash command workflows |
| Documentation patterns | `documentation-patterns/` | Two-tier docs (high-level + technical reference) after completing a feature |
| Agent workflows | `agent-workflows/` | Agent team structure, parallel launch, SQA workflow, PR handoff |
| Sub-agent commands | `sub-agent-commands/` | Creating /plan /research /test /rework /document slash commands |
| GitHub CI / PR review | `github-ci-pr-review/` | Diagnosing CI failures, ruff lint fixes, rebase conflict resolution |

## AWS & Cloud

| Skill | Folder | Summary |
|-------|--------|---------|
| Terragrunt project setup | `terragrunt-project-setup/` | Multi-module structure, remote state bootstrap, dependency wiring, multi-account pattern |
| Amplify S3 Storage Browser | `amplify-storage-browser/` | React + Amplify Storage Browser v3 + Cognito + Terragrunt IaC recipe |

## Bioinformatics Pipelines

| Skill | Folder | Summary |
|-------|--------|---------|
| Nextflow DSL2 | `nextflow-dsl2/` | Module patterns, channels, PE/SE handling, genomes config, container assignment |
| Nextflow testing | `nextflow-testing/` | Smoke tests, local tests, process debugging, CI checklist |
| Docker containers | `docker-containers/` | Dockerfile patterns, conda pinning, multi-container builds, Nextflow integration |
| RNAseq reference | `rnaseq-reference/` | QC metrics (FastQC, STAR, Picard, dedup, counts), thresholds, biotypes, RPKM/TPM |
| UMI tools | `umi-tools/` | Comparison of fgbio, fgumi, umi-tools, rumi, UMICollapse |
| R-to-Python | `r-to-python/` | Checklist and function mapping for replacing R scripts in Nextflow pipelines |
| Legacy Python + conda | `legacy-python-conda/` | Python 2.7 conda env setup, pymongo/GridFS extraction, py2/3 compat patterns |

## Project Context

| Skill | Folder | Summary |
|-------|--------|---------|
| Sequoia Spectrum | `sequoia-spectrum/` | Full project context, pipeline modes, module map, container registry, open work items |
