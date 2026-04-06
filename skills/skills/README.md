# Skills Library

Reusable patterns and workflows captured from working sessions.
Each file is a self-contained guide — copy the relevant sections into a new project or reference them when setting up similar patterns.

| Skill | File | Summary |
|-------|------|---------|
| Sub-agent slash commands | `sub-agent-commands.md` | Set up a project with `/plan`, `/research`, `/test`, `/rework`, `/document` commands |
| Two-tier documentation | `two-tier-docs.md` | Write high-level + technical docs after completing a feature |
| CLAUDE.md bootstrap | `claudemd-bootstrap.md` | What to include when writing a CLAUDE.md for a new project |
| Nextflow DSL2 RNAseq pipeline | `nextflow-rnaseq-pipeline.md` | Module structure, channel patterns, PE/SE handling, pipeline selection, genomes config, Complete vs Express differences |
| RNAseq analysis concepts | `rnaseq-concepts.md` | All QC metrics (FastQC, STAR, Picard, dedup, counts), biotypes, RPKM/TPM, ERCC spikes, quality thresholds |
| Docker for bioinformatics | `docker-bioinformatics.md` | Dockerfile patterns, conda pinning, version locking, Nextflow+Docker integration |
| Nextflow pipeline testing | `nextflow-testing.md` | Smoke/local test profiles, debugging work dirs, CI checklist, common failures |
| Sequoia Spectrum project | `sequoia-spectrum-project.md` | Full project context, pipeline modes, auto-detection logic, report design, module plan, open questions — acts as local agent for this project |
| R-to-Python migration | `r-to-python-migration.md` | Checklist and R→pandas function mapping for replacing R scripts in Nextflow pipelines |
| Multi-agent orchestration | `multi-agent-orchestration.md` | Agent team structure, parallel launch patterns, mandatory SQA workflow, PR handoff |
| UMI tools landscape | `umi-tools-landscape.md` | Comparison of fgbio, fgumi, umi-tools, rumi, UMICollapse — evaluation criteria and current status |
