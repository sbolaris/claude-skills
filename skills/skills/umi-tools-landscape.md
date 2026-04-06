# Skill: UMI Tools Landscape for RNA-seq Pipelines

**When to use:** Evaluating or selecting UMI (Unique Molecular Identifier) processing tools for sequencing pipelines.

---

## Tool comparison

| Tool | Language | Maintainer | Key Strength | Status (as of Apr 2026) |
|------|----------|-----------|--------------|------------------------|
| **fgbio** | Scala/JVM | Fulcrum Genomics | Full UMI pipeline, mature, widely used | Stable, production |
| **fgumi** | Rust | Fulcrum Genomics | Next-gen replacement for fgbio UMI tools, no JVM | ALPHA (v0.1.2), target June 2026 |
| **umi-tools** | Python | CGaT/Edinburgh | Flexible grouping algorithms, well-cited | Stable, production |
| **rumi** | Rust | Bio-Rad (fork of umi-tools) | Optimized for paired-end RNA-seq | Internal binary, production |
| **UMICollapse** | Java | Daniel Liu | N-gram/BK-tree indexing for fast grouping | Stable |
| **gencore** | C++ | OpenGene | Fast, low memory | Stable but limited features |

## fgumi details (watch list)

- **Repo:** github.com/fulcrumgenomics/fgumi
- **Install:** `conda install -c bioconda fgumi` or pre-built binaries from GitHub releases
- **Commands:** extract, correct, zipper, fastq, sort, group, dedup, simplex, duplex, codec, filter, clip, duplex-metrics, downsample
- **Key advantage:** Single binary replaces fgbio + samtools + picard for UMI work. No JVM = smaller containers.
- **Gotcha:** `--queue-memory` scales per-thread by default — can cause unexpected RAM in multi-threaded Nextflow tasks
- **Evaluation plan:** Test in dev Nextflow config against current rumi/fgbio outputs. Target evaluation sprint around June 2026 when Fulcrum recommends it for production.

## Sequoia Spectrum current setup

- Default dedup tool: `rumi` (Bio-Rad Rust binary at `src/rumi`)
- Alternative: `umi-tools` via `--dedupTool umitools`
- UMI workflow: debarcode (extract from R2) → tag BAM (XU tag) → dedup
- UMI is optional in Express mode (`--skipUmi`), required in Complete mode
