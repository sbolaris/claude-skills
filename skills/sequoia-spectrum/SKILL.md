---
name: sequoia-spectrum
description: Full project context for the Bio-Rad Sequoia Spectrum unified RNAseq Nextflow pipeline
tags: [sequoia-spectrum, nextflow, bioinformatics, bio-rad, rnaseq]
---

# Skill: Sequoia Spectrum — Project Context & Pipeline Agent

**When to use:** Working on `/home/ubuntu/sequoia-spectrum` — the unified Bio-Rad RNAseq Nextflow pipeline.

**Role:** Act as a Nextflow pipeline engineer with deep knowledge of the Sequoia pipelines. Make architecture decisions consistent with the patterns below. Do not re-ask questions already answered here.

---

## Project identity

- **Repo:** local at `/home/ubuntu/sequoia-spectrum`
- **Source pipelines:** `/home/ubuntu/SEQuoia-Complete` and `/home/ubuntu/Sequoia_express_toolkit`
- **Purpose:** Unified replacement for both source pipelines
- **Stack:** Nextflow DSL2, Docker (8 containers), Bash, Python 3.7, JavaScript (Chart.js reports), Conda/Mamba

---

## Pipeline modes

| Flag | Mode | Reads | UMI | miRNA |
|------|------|-------|-----|-------|
| `--pipeline none` (default) | auto-detect | PE | auto | auto |
| `--pipeline express` | Express | SE or PE | optional | no |
| `--pipeline complete` | Complete | PE only | required | yes |

**Auto-detect logic** (`main.nf:resolvePipelineMode`):
```groovy
def resolvePipelineMode(String pipelineParam, String readsPattern) {
    if (pipelineParam in ['express', 'complete']) return pipelineParam
    def r1 = file(readsPattern).find { f -> f.name =~ /[._]R1[._]/ }
    def r2 = r1.resolveSibling(r1.name.replaceAll(/([._])R1([._])/, '$1R2$2'))
    def ratio = (double) r1.size() / r2.size()
    return ratio > 1.5 ? 'complete' : 'express'   // R2 is ~16bp UMI barcode in complete
}
```

---

## UMI deduplication

- **Default:** `rumi` (Bio-Rad fork of umi-tools — pre-compiled binary in `src/rumi`)
- **Legacy:** `umi_tools` via `--dedupTool umitools`
- Both produce identical output BAM format — all downstream steps are unaffected

---

## Completed modules (`modules/`)

| File | Process(es) | Container |
|------|-------------|-----------|
| `validate_inputs.nf` | `validateInputs` | python |
| `fastqc.nf` | `fastQc` | fastqc |
| `debarcode.nf` | `debarcode` | python |
| `rename_tuple.nf` | `rename_tuple` | python |
| `cutadapt.nf` | `cutAdapt` | python |
| `star.nf` | `starAlign` | star |
| `picard.nf` | `picardAlignSummary` | picard |
| `deduplication.nf` | `deduplication`, `deduplication_umitools` | dedup |
| `splitbam.nf` | `splitBamMi`, `splitBamLong` | samtools |
| `genecount.nf` | `countLongRNA`, `countMicroRNA` | subread |
| `rpkm.nf` | `calcRPKMTPM` | python |
| `threshold.nf` | `thresholdResults` | python |
| `report.nf` | `assembleReport`, `batchReport`, `metaReport`, `combinedXLS` | python |

---

## Container registry pattern

```groovy
// nextflow.config
def reg = params.container_registry   // e.g. 'bioraddbg' or ECR URL
def ver = params.container_version    // e.g. '1.0.0'

process {
    withName: 'validateInputs|debarcode|cutAdapt|umiTagging|calcRPKMTPM|combinedXLS|assembleReport|batchReport|metaReport|thresholdResults|rename_tuple' {
        container = "${reg}/sequoia-spectrum-python:${ver}"
    }
    withName: 'fastQc'                               { container = "${reg}/sequoia-spectrum-fastqc:${ver}" }
    withName: 'starAlign'                            { container = "${reg}/sequoia-spectrum-star:${ver}" }
    withName: 'picardAlignSummary'                   { container = "${reg}/sequoia-spectrum-picard:${ver}" }
    withName: 'deduplication|deduplication_umitools' { container = "${reg}/sequoia-spectrum-dedup:${ver}" }
    withName: 'splitBamMi|splitBamLong'              { container = "${reg}/sequoia-spectrum-samtools:${ver}" }
    withName: 'countLongRNA|countMicroRNA'           { container = "${reg}/sequoia-spectrum-subread:${ver}" }
}
```

---

## Express vs Complete key differences

| Feature | Complete (2D) | Express |
|---------|--------------|---------|
| Read mode | PE + UMI only | PE or SE |
| miRNA counting | Yes (splitBam → countMicroRNA) | No |
| Spike support | ercc, miltenyi | ercc only |
| Supported genomes | hg38, mm10, rnor6, dm6, danRer11, ce11, tair10 | + sacCer3 |
| Gene thresholding | No | Yes |
| Excel output | No | Yes |
| Batch/meta report | No | Yes |

---

## EXPRESS_ONLY_GENOMES

```groovy
EXPRESS_ONLY_GENOMES = ['sacCer3']   // all others now support Complete mode
```

dm6, danRer11, ce11, tair10 were unlocked in `feature/mirna-gff3` by switching from BED to GFF3 (miRBase). sacCer3 remains express-only (no miRNA annotations available).

## miRNA annotations

Pipeline uses **GFF3** directly via `bedtools intersect -b file.gff3` — no BED conversion needed. Key: `miRNAGff3File` (not `miRNABedFile`).

Files are user-provided at runtime. Expected path pattern:
```
{genomes_base}/{genome}/anno_ncbi/{genome}_miRNA_annotation.gff3
{genomes_base}/{genome}/anno_ncbi/{genome}_miRNA_annotation.gtf
```

miRBase organism codes: dm6=`dme`, danRer11=`dre`, ce11=`cel`, tair10=`ath`. Note: dme.gff3 uses dm3 coords — liftOver needed for dm6.

---

## Key constraints

- Never put `container` directives in module files — assign in `nextflow.config` via `withName`
- `val(name)` must be emitted by every report-type output (needed for `.join()` in report assembly)
- Optional channels must use `.ifEmpty([])` before `.collect()` to avoid blocking
- New genomes require entries in both `acceptableGenomes` list AND `conf/genomes.config`
- The `stageAs` paths in report process inputs must match exactly what the report script expects

---

## Open work items

- genomes branch: genome build workflow — ready to push (branch: `genomes`)
- miRNA GFF3 switch complete — branch `feature/mirna-gff3` ready to push/PR
