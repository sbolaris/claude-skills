# Skill: RNAseq Analysis Concepts & Metrics

**When to use:** Understanding, implementing, or reporting on RNAseq analysis steps and quality metrics.

**Captured from:** SEQuoia-Complete and Sequoia_express_toolkit report analysis.

---

## Pipeline steps and tools

| Step | Tool | Purpose |
|------|------|---------|
| Quality check | FastQC | Per-base quality, adapter content, duplication |
| UMI extraction | Custom debarcode.py | Extract UMI from R2, tag R1 read name |
| Adapter trimming | Cutadapt | Remove sequencing adapters, low-quality bases |
| Alignment | STAR | Splice-aware alignment to reference genome |
| Alignment QC | Picard CollectRnaSeqMetrics | Coverage bias, base distribution, rRNA |
| UMI deduplication | rumi (UMI-tools fork) | Remove PCR duplicates using UMI sequences |
| BAM splitting | samtools/bedtools | Separate miRNA from longRNA reads |
| Gene counting | featureCounts (subread) | Count reads per gene from GTF annotations |
| Normalization | Custom Python | Calculate RPKM and TPM from raw counts |
| Thresholding | Custom R | Filter genes below expression cutoff |

---

## Key metrics by step

### Debarcoding (UMI extraction)
- **Input Reads** — total reads in FASTQ
- **Reads with Valid UMI** — R1 reads with a valid UMI barcode on R2
- **% Reads with Valid UMI** — barcode capture efficiency; low values indicate library prep issues

### Trimming (Cutadapt)
- Total reads processed, reads written (passing filter)
- Basepairs processed, quality-trimmed, adapter-trimmed
- Reads too short (filtered out)

### Alignment (STAR)
- **Input Reads** — reads entering alignment
- **Uniquely Mapped Reads** — mapped to exactly one locus (high quality)
- **Multi-mapped Reads** — mapped to 2–10 loci
- **Reads mapped to too many loci** — >10 loci, typically discarded
- **Unmapped Reads** — failed alignment (= Input - Unique - Multi)

### Alignment QC (Picard CollectRnaSeqMetrics)
- **PF Bases** — total passing-filter bases (including unaligned)
- **PF Aligned Bases** — aligned PF bases
- **Coding Bases** — bases in coding exons (not UTR)
- **UTR Bases** — bases in untranslated regions
- **Intronic Bases** — bases in introns
- **Intergenic Bases** — bases not in any annotated gene
- **Ribosomal Bases** — bases mapping to rRNA loci
- **Median CV Coverage** — coefficient of variation across 1000 highest-expressed transcripts; ideal = 0 (uniform coverage)
- **Median 5' Bias** — mean coverage of 5'-most 100 bases / mean whole-transcript coverage
- **Median 3' Bias** — same for 3' end; high 3' bias is typical of polyA-selected libraries
- **Median 5' to 3' Bias** — ratio of 5' to 3' bias; near 1 = good
- **% Stranded** — % reads on correct strand; ~100% expected for stranded libraries
- **% rRNA Bases** — percent of aligned bases mapping to rRNA; high = poor depletion

### Deduplication (UMI-tools/rumi)
- **Total input alignments** — alignments entering dedup
- **Total output alignments** — alignments after removing PCR duplicates
- **Unique UMIs observed** — number of distinct UMI sequences seen
- **Reads with unpaired mate** — alignments with no paired read (can indicate alignment issues)
- **Unique Input Reads** — distinct read positions before dedup
- **Unique Output Reads** — distinct read positions after dedup
- **% PCR Duplicates** — `(1 - Unique Output / Unique Input) * 100`; typical range 10–50%

### Gene Counting (featureCounts)
- **Total Alignments** — all alignments submitted
- **Assigned** — counted to a gene
- **Unassigned_NoFeatures** — no overlapping gene annotation
- **Unassigned_Ambiguous** — overlaps multiple genes
- **Unassigned_MultiMapping** — excluded multi-mappers
- **Genes with >0 Counts** — number of expressed genes

### Normalization
- **RPKM** (Reads Per Kilobase per Million) — `(raw_count * 10^9) / (gene_length_bp * total_mapped_reads)`
- **TPM** (Transcripts Per Million) — `(raw_count / gene_length_kb) / sum(raw_count / gene_length_kb) * 10^6`
- TPM is preferred; values sum to 1M per sample making cross-sample comparison valid

---

## Gene biotypes

Genes are annotated with Ensembl biotypes. Key ones to report:
- `protein_coding` — standard mRNA-producing genes
- `lncRNA` — long non-coding RNA
- `miRNA` — microRNA precursors
- `rRNA` — ribosomal RNA (high = contamination)
- `pseudogene` — non-functional gene copies
- `snoRNA`, `snRNA` — small nuclear/nucleolar RNAs
- `mitochondrial_rRNA`, `Mt_tRNA` — mitochondrial

---

## ERCC spike-in controls

ERCC (External RNA Controls Consortium) are synthetic RNA sequences spiked into samples for:
- Assessing dynamic range
- Detecting systematic bias across samples
- Normalizing between samples when endogenous RNA is variable

Present in both Express and Complete pipelines as optional (`--spikeType ercc`). Miltenyi spike is Complete-only.

---

## miRNA vs longRNA (Complete pipeline only)

The Complete pipeline splits the BAM before counting:
- **miRNA BAM** — reads overlapping miRNA BED file regions → counted against miRNA GTF
- **longRNA BAM** — all other reads → counted against longRNA GTF

This separation prevents miRNA reads from being assigned to overlapping long RNA genes.

---

## Report data sources (file patterns)

| Data | File pattern | Tool |
|------|-------------|------|
| FastQC | `*_fastqc.html`, `*_fastqc.zip` | FastQC |
| Debarcoding | `*_barcode_stats.tsv` | debarcode.py |
| Trimming | `trimlog.log.<sample>` | Cutadapt |
| STAR alignment | `Log.final.out.<sample>` | STAR |
| Picard metrics | `rna_metrics.txt.<sample>` | Picard |
| Deduplication | `dedup.log.<sample>` | rumi |
| Gene counts | `gene_counts_longRNA.<sample>` | featureCounts |
| Count summary | `gene_counts_longRNA.summary.<sample>` | featureCounts |
| Biotype annotation | `<annoDir>/gene_biotypes.tsv` | Ensembl annotation |
| Annotation version | `<annoDir>/annotation_version.txt` | Ensembl annotation |

---

## Quality thresholds (typical expectations)

| Metric | Acceptable range | Concern |
|--------|-----------------|---------|
| % Valid UMI | >70% | <50% = library prep issue |
| Unique mapping rate | >70% | <60% = alignment or sample quality issue |
| % rRNA bases | <10% | >20% = poor rRNA depletion |
| % PCR duplicates | 10–50% | >70% = over-amplified library |
| Genes with >0 counts | >5000 (human) | <1000 = failed library |
| Median CV Coverage | <0.8 | >1.0 = severe coverage non-uniformity |
