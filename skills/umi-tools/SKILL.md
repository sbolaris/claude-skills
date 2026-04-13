---
name: umi-tools
description: UMI deduplication tool comparison — fgbio, fgumi, umi-tools, rumi, UMICollapse for RNA-seq pipelines
tags: [umi, deduplication, rnaseq, bioinformatics, fgbio, umi-tools]
---

# Skill: UMI Deduplication Tools

**When to use:** Evaluating or selecting UMI (Unique Molecular Identifier) processing tools for sequencing pipelines.

---

## Tool comparison

| Tool | Language | Maintainer | Key Strength | Status (Apr 2026) |
|------|----------|-----------|--------------|-------------------|
| **fgbio** | Scala/JVM | Fulcrum Genomics | Full UMI pipeline, mature, widely used | Stable, production |
| **fgumi** | Rust | Fulcrum Genomics | Next-gen replacement for fgbio, no JVM | ALPHA (v0.1.2), target June 2026 |
| **umi-tools** | Python | CGaT/Edinburgh | Flexible grouping algorithms, well-cited | Stable, production |
| **rumi** | Rust | Bio-Rad (fork of umi-tools) | Optimized for paired-end RNA-seq | Internal binary, production |
| **UMICollapse** | Java | Daniel Liu | N-gram/BK-tree indexing for fast grouping | Stable |
| **gencore** | C++ | OpenGene | Fast, low memory | Stable but limited features |

---

## fgumi (watch list)

- **Repo:** github.com/fulcrumgenomics/fgumi
- **Install:** `conda install -c bioconda fgumi` or pre-built GitHub releases
- **Commands:** extract, correct, group, dedup, simplex, duplex, filter, clip
- **Key advantage:** Single binary replaces fgbio + samtools + picard for UMI work. No JVM = smaller containers.
- **Gotcha:** `--queue-memory` scales per-thread by default — can cause unexpected RAM in multi-threaded Nextflow tasks
- **Evaluation target:** ~June 2026 when Fulcrum recommends it for production

---

## Standard UMI workflow

```
debarcode (extract UMI from R2, tag R1 read name)
  → align (STAR)
  → tag BAM (add XU tag)
  → dedup (rumi or umi-tools)
  → count (featureCounts)
```

UMI is optional in Express-mode pipelines (`--skipUmi`), required in Complete/2D-mode pipelines.
