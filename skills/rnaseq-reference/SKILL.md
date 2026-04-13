---
name: rnaseq-reference
description: RNAseq QC metrics, quality thresholds, gene biotypes, RPKM/TPM normalization reference
tags: [rnaseq, qc, metrics, bioinformatics, fastqc, star, picard]
---

# Skill: RNAseq Analysis Reference

**When to use:** Understanding, implementing, or reporting on RNAseq analysis steps and quality metrics.

---

## Pipeline steps and tools

| Step | Tool | Purpose |
|------|------|---------|
| Quality check | FastQC | Per-base quality, adapter content, duplication |
| UMI extraction | Custom debarcode.py | Extract UMI from R2, tag R1 read name |
| Adapter trimming | Cutadapt | Remove sequencing adapters, low-quality bases |
| Alignment | STAR | Splice-aware alignment to reference genome |
| Alignment QC | Picard CollectRnaSeqMetrics | Coverage bias, base distribution, rRNA |
| UMI deduplication | rumi / umi-tools | Remove PCR duplicates using UMI sequences |
| BAM splitting | samtools/bedtools | Separate miRNA from longRNA reads |
| Gene counting | featureCounts (subread) | Count reads per gene from GTF annotations |
| Normalization | Custom Python | Calculate RPKM and TPM from raw counts |
| Thresholding | Custom R/Python | Filter genes below expression cutoff |

---

## Key metrics by step

### Debarcoding (UMI extraction)
- **Input Reads** — total reads in FASTQ
- **Reads with Valid UMI** — R1 reads with a valid UMI barcode on R2
- **% Reads with Valid UMI** — barcode capture efficiency; low values indicate library prep issues

### Alignment (STAR)
- **Uniquely Mapped Reads** — mapped to exactly one locus (high quality)
- **Multi-mapped Reads** — mapped to 2–10 loci
- **Unmapped Reads** — failed alignment

### Alignment QC (Picard CollectRnaSeqMetrics)
- **Coding/UTR/Intronic/Intergenic Bases** — distribution of aligned bases
- **Ribosomal Bases** — bases mapping to rRNA loci
- **Median CV Coverage** — coefficient of variation across 1000 highest-expressed transcripts; ideal = 0 (uniform)
- **Median 5'/3' Bias** — coverage uniformity across transcript length; high 3' bias typical of polyA-selected libraries
- **% Stranded** — ~100% expected for stranded libraries

### Deduplication
- **% PCR Duplicates** — `(1 - Unique Output / Unique Input) * 100`; typical range 10–50%

### Gene Counting (featureCounts)
- **Assigned** — counted to a gene
- **Unassigned_NoFeatures** — no overlapping annotation
- **Unassigned_Ambiguous** — overlaps multiple genes
- **Genes with >0 Counts** — number of expressed genes

### Normalization
- **RPKM** — `(raw_count × 10⁹) / (gene_length_bp × total_mapped_reads)`
- **TPM** — `(raw_count / gene_length_kb) / sum(raw_count / gene_length_kb) × 10⁶` — preferred; values sum to 1M per sample

---

## Quality thresholds

| Metric | Acceptable | Concern |
|--------|------------|---------|
| % Valid UMI | >70% | <50% = library prep issue |
| Unique mapping rate | >70% | <60% = alignment or sample quality issue |
| % rRNA bases | <10% | >20% = poor rRNA depletion |
| % PCR duplicates | 10–50% | >70% = over-amplified library |
| Genes with >0 counts | >5000 (human) | <1000 = failed library |
| Median CV Coverage | <0.8 | >1.0 = severe coverage non-uniformity |

---

## Gene biotypes (Ensembl)

- `protein_coding` — standard mRNA-producing genes
- `lncRNA` — long non-coding RNA
- `miRNA` — microRNA precursors
- `rRNA` — ribosomal RNA (high = contamination)
- `pseudogene` — non-functional gene copies
- `snoRNA`, `snRNA` — small nuclear/nucleolar RNAs

---

## ERCC spike-in controls

Synthetic RNA sequences spiked into samples for assessing dynamic range, detecting systematic bias, and normalizing between samples. Present as optional `--spikeType ercc`.

---

## miRNA vs longRNA splitting

Complete/2D pipelines split the BAM before counting:
- **miRNA BAM** — reads overlapping miRNA BED regions → counted against miRNA GTF
- **longRNA BAM** — all other reads → counted against longRNA GTF

This prevents miRNA reads from being assigned to overlapping long RNA genes.

---

## Report data sources (file patterns)

| Data | File pattern | Tool |
|------|-------------|------|
| FastQC | `*_fastqc.zip` | FastQC |
| Debarcoding | `*_barcode_stats.tsv` | debarcode.py |
| Trimming | `trimlog.log.<sample>` | Cutadapt |
| STAR alignment | `Log.final.out.<sample>` | STAR |
| Picard metrics | `rna_metrics.txt.<sample>` | Picard |
| Deduplication | `dedup.log.<sample>` | rumi/umi-tools |
| Gene counts | `gene_counts_longRNA.<sample>` | featureCounts |
