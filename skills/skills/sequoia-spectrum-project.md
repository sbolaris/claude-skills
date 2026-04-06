# Skill: Sequoia Spectrum — Project Context & Pipeline Engineer Agent

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
- gencore was evaluated and skipped

---

## Completed module files

All 16 modules written in `modules/`:

| File | Process(es) | Container |
|------|-------------|-----------|
| `validate_inputs.nf` | `validateInputs` | python |
| `fastqc.nf` | `fastQc` | fastqc |
| `debarcode.nf` | `debarcode` | python |
| `rename_tuple.nf` | `rename_tuple` | python |
| `cutadapt.nf` | `cutAdapt` | python |
| `star.nf` | `starAlign` | star |
| `picard.nf` | `picardAlignSummary` | picard |
| `umi_tagging.nf` | `umiTagging` | python |
| `deduplication.nf` | `deduplication` (rumi) | dedup |
| `deduplication_umitools.nf` | `deduplication_umitools` | dedup |
| `split_bam.nf` | `splitBamMi`, `splitBamLong` | samtools |
| `count_rna.nf` | `countLongRNA`, `countMicroRNA` | subread |
| `rpkm.nf` | `calcRPKMTPM` | python |
| `threshold.nf` | `thresholdResults` | python |
| `combined_xls.nf` | `combinedXLS` | python |
| `report.nf` | `assembleReport`, `batchReport` | python |

**Critical module output convention:** All report-type outputs emit `tuple val(name), path(...)` so they can be joined by sample name for `assembleReport`. This applies to: `report_fastqc`, `report`, `report_trim`, `report_star`, `report_picard`, `report_dedup`, `report_counts`, `report_mirna_counts`.

---

## main.nf workflow logic

```
SE mode:   fromPath → map (strip _R1) → fastQc → cutAdapt → starAlign → picard
                                                            → countLongRNA → rpkm → threshold → combinedXLS

PE/doUmi:  fromFilePairs → fastQc → debarcode → cutAdapt → starAlign → picard
                                               → umiTagging → dedup (rumi|umitools)
                                               → [complete: splitBam] → countLongRNA → [complete: countMicroRNA]
                                               → rpkm → [express: threshold → combinedXLS]
                                               → assembleReport (per-sample, via join+multiMap)
                                               → batchReport (collect all samples)
```

**Report assembly pattern** — joining per-sample channels for `assembleReport`:
```groovy
fastQc.out.report_fastqc
    .join(deb_report_ch)          // [name, []] when skipUmi
    .join(cutAdapt.out.report_trim)
    .join(starAlign.out.report_star)
    .join(picardAlignSummary.out.report_picard)
    .join(dedup_report_ch)        // [name, []] when skipUmi
    .join(countLongRNA.out.report_counts)
    .multiMap { name, fastqc, deb, trim, star, picard, dedup, counts ->
        names: name; fastqc: fastqc; debarcode: deb; trim: trim
        star: star; picard: picard; dedup: dedup; counts: counts
    }
    .set { report_inputs }
assembleReport(report_inputs.names, report_inputs.fastqc, ...)
```

**Optional channel placeholder:** When a step is skipped (e.g., no UMI), create a same-length dummy channel for joining:
```groovy
deb_report_ch = doUmi ? debarcode.out.report : raw_reads_ch.map { name, r -> tuple(name, []) }
```

---

## Container architecture

8 containers, one per software ecosystem. Container assignments are in `nextflow.config` `withName` selectors — **not** in module files. R was fully removed — all scripts are now Python.

```
containers/
├── build.sh          # bash containers/build.sh [--push] [--version X]
├── python/           # python + cutadapt + pandas/pysam/openpyxl + samtools + parallel + src/ scripts
├── fastqc/           # FastQC + JDK
├── star/             # STAR + samtools + sambamba
├── picard/           # Picard + JDK + samtools
├── dedup/            # rumi binary + umi-tools + samtools + sambamba
├── samtools/         # samtools + bedtools + sambamba
├── subread/          # featureCounts
└── genome_build/     # gffread + gtfToGenePred + STAR + src/genome_build/ Python scripts
```

Each subdirectory contains `Dockerfile` + `env.yaml`. Build from project root so `COPY src/...` paths work:
```bash
docker build -f containers/python/Dockerfile -t bioraddbg/sequoia-spectrum-python:1.0.0 .
```

Override registry/version at runtime:
```bash
nextflow run main.nf --container_registry 123456.dkr.ecr.us-west-2.amazonaws.com --container_version 1.0.0
```

---

## src/ scripts

| Script | Container | Used by |
|--------|-----------|---------|
| `debarcode.py` | python | `debarcode` |
| `fastq_to_tsv.sh` | python | `debarcode` |
| `tsv_to_fastq.sh` | python | `debarcode` |
| `tagBamFile.py` | python | `umiTagging` |
| `validate.py` | python | `validateInputs` |
| `calc_rpkm_tpm.py` | python | `calcRPKMTPM` |
| `converge_xls.py` | python | `combinedXLS` |
| `generate_report.py` | python | `assembleReport` |
| `generate_batch_report.py` | python | `batchReport` |
| `threshold_results.py` | python | `thresholdResults` |
| `rumi` (binary) | dedup | `deduplication` |

---

## Report design (JavaScript, replacing R Markdown)

**Per-sample** (`${name}_report.html`) — self-contained HTML, no external deps:
- Sections: debarcode stats, trimming, STAR alignment, Picard RNA distribution, dedup, featureCounts, read fate funnel
- Chart.js: doughnut (alignment), bar (Picard distribution, counts assignment, read fate horizontal bar)
- Badge stats with color coding (blue=normal, amber=warn)
- CSV export button (data embedded as JSON in script tag)

**Batch** (`batch_summary.html` + `batch_summary.csv`):
- Multi-sample stacked bar charts (uniquely mapped %, Picard coding/intronic/intergenic %, dedup rate %)
- Sortable tables (click column header)
- Per-table CSV export

Both generated by Python scripts (`generate_report.py`, `generate_batch_report.py`) that parse QC log files from staged directories.

---

## Genome support

| Genome | Express | Complete | miRNA refs |
|--------|---------|----------|-----------|
| hg38 | ✓ | ✓ | bed + gtf |
| mm10 | ✓ | ✓ | bed + gtf |
| rnor6 | ✓ | ✓ | bed + gtf |
| tair10 | ✓ | ✗ | none |
| sacCer3 | ✓ | ✗ | none |
| dm6 | ✓ | ✗ | none |
| danRer11 | ✓ | ✗ | none |
| ce11 | ✓ | ✗ | none |

Express-only genomes are guarded in `main.nf`:
```groovy
def EXPRESS_ONLY_GENOMES = ['tair10', 'sacCer3', 'dm6', 'danRer11', 'ce11']
if (pipelineMode == 'complete' && EXPRESS_ONLY_GENOMES.contains(params.genome)) {
    exit 1, "ERROR: Genome '${params.genome}' has no miRNA annotations..."
}
```

Spike types: `NONE` (default), `ercc` (hg38/mm10/rnor6), `miltenyi` (hg38 only).

---

## Tool versions (pinned)

| Tool | Version |
|------|---------|
| Python | 3.7.12 |
| FastQC | 0.11.9 |
| cutadapt | 2.7 |
| STAR | 2.7.0f |
| samtools | 1.6 |
| sambamba | 0.6.9 |
| bedtools | 2.31.0 |
| picard | 2.27.4 |
| umi_tools | 1.1.4 |
| subread | 1.6.4 |
| parallel | 20230522 |

---

## Key params

```
--reads             '/data/*_R{1,2}_*.fastq.gz'  (required)
--genome            hg38 (default)
--pipeline          none | express | complete  (default: none → auto-detect)
--seqType           PE | SE  (default: PE)
--skipUmi           flag, express PE only
--dedupTool         rumi | umitools  (default: rumi)
--spikeType         NONE | ercc | miltenyi  (default: NONE)
--outDir            ./results
--container_registry  bioraddbg (default)
--container_version   1.0.0 (default)
```

---

## Running locally

```bash
# Smoke test
nextflow run main.nf -profile smoketest --reads 'test_data/*_R{1,2}*.fastq.gz'

# Express SE
nextflow run main.nf -profile docker \
    --reads '/data/*_R1*.fastq.gz' --genome mm10 \
    --pipeline express --seqType SE

# Complete + ERCC
nextflow run main.nf -profile docker \
    --reads '/data/*_R{1,2}_*.fastq.gz' --genome hg38 \
    --pipeline complete --spikeType ercc

# AWS Batch
nextflow run main.nf -profile awsbatch \
    --reads 's3://bucket/*_R{1,2}*.fastq.gz' \
    --genome hg38 --genomes_base 's3://bucket/genomes' \
    --container_registry 123456.dkr.ecr.us-west-2.amazonaws.com \
    --outDir 's3://bucket/results' --notrace
```

---

## Genome build workflow

**Activated by:** `--build_genome` flag on `main.nf`. When set, the RNA analysis workflow is skipped entirely — only the genome build sub-workflow runs.

**Sub-workflow:** `workflows/genome_build.nf` → `GENOME_BUILD` workflow. Orchestrates 9 sequential steps producing both standard and ERCC spike-in reference sets in parallel where possible.

**Module files** (`modules/genome_build/`):

| Module | Process(es) | Purpose |
|--------|-------------|---------|
| `convert_annotation.nf` | `convertAnnotation` | GFF → GTF via gffread, or copy if already GTF. Cleans `?` strand markers. |
| `rename_chromosomes.nf` | `renameChromosomes` | Aligns FASTA chromosome names to GTF using NCBI assembly report |
| `star_index.nf` | `buildStarIndex` | Runs STAR `genomeGenerate`. Called twice: standard + ERCC via aliased import |
| `add_ercc.nf` | `addErccFasta`, `addErccGtf`, `addErccLongRnaGtf`, `addErccBiotypes` | Appends ERCC spike-in sequences/annotations from `ercc_files/` |
| `annotation_files.nf` | `makeRefflat`, `makeRibosomalIntervals`, `extractBiotypes`, `makeLongRnaGtf`, `extractSizes`, `extractVersion`, `copyVersionErcc` | Generates all Picard/featureCounts support files |

**Python scripts** (`src/genome_build/` — installed to `/opt/biorad/src/` in container):

| Script | Purpose |
|--------|---------|
| `extract_biotypes.py` | Parses GTF → `gene_biotypes.tsv` (gene_id → biotype mapping) |
| `longRNA_counts_fix.py` | Filters GTF to longRNA features only → `*_longRNA_annotation.gtf` |
| `refflat_fix.py` | Post-processes `gtfToGenePred` output for Picard compatibility |
| `rename_chr.py` | Chromosome renaming logic used by `renameChromosomes` |
| `ribosomal_int.py` | Builds Picard-format ribosomal interval list from GTF + chrNameLength |
| `txt2fasta.py` | Utility: converts tab-delimited spike-in definitions to FASTA |
| `gffread` (binary) | GFF to GTF conversion |
| `gtfToGenePred` (binary) | GTF to RefFlat conversion |

**How output maps to `conf/genomes.config` entries:**

```
<genome_outDir>/<genome_name>/
├── anno_ncbi/                         → annoDir / sjdbGTFFile / refFlatFile /
│   ├── <name>_contigs_in_ref.gtf          ribosomalIntervalFile / longRNAgtfFile
│   ├── <name>_annotations.refflat
│   ├── <name>_ribosomal_intervals.txt
│   ├── <name>_longRNA_annotation.gtf
│   ├── gene_biotypes.tsv
│   └── annotation_version.txt
├── anno_ncbi_ercc/                    → same keys, ercc spike type
├── star_ncbi/                         → genomeDir (NONE spike type)
├── star_ncbi_ercc/                    → genomeDir (ercc spike type)
└── sizes/
    ├── <name>.chrom.sizes             → sizesFile (NONE)
    └── <name>_ercc.chrom.sizes        → sizesFile (ercc)
```

Note: `miRNABedFile` and `miRNAgtfFile` are not produced by the build workflow — add them manually if the genome has miRNA annotations.

**Container:** `sequoia-spectrum-genome-build` — built from `containers/genome_build/Dockerfile` + `env.yaml`. Contains gffread, gtfToGenePred, STAR, and all `src/genome_build/` Python scripts at `/opt/biorad/src/`.

---

## Open items / next steps

- [x] Tertiary analysis Dash app added (`tertiary/`) — DGE, pathway analysis, interactive plots
- [x] Genome build workflow added (`--build_genome`) — produces complete reference packages from NCBI/Ensembl sources
- [ ] Add test data fixtures for smoke test profile
- [ ] `.claude/commands/` sub-agent slash commands (/plan /research /test /rework /document)
- [ ] Singularity `.sif` build workflow (for HPC clusters without Docker)
- [ ] miRNA annotation generation for newly built genomes

---

## Tertiary analysis app

**Location:** `tertiary/` — standalone Python package, not part of the Nextflow pipeline.

**Stack:** Python 3.10+, Plotly Dash, dash-bootstrap-components, PyDESeq2, GSEApy, gprofiler-official, scikit-learn.

**Input:** Sequoia Spectrum pipeline output directories. The loader reads `<sample_path>/RNACounts/gene_counts_longRNA.<sample_name>` (featureCounts output). Sample-to-condition mapping comes from a CSV or YAML sample sheet.

**Architecture:**

```
tertiary/
├── pyproject.toml          # Dependencies, entry point: sequoia-tertiary
├── Dockerfile              # python:3.11-slim, gunicorn 2 workers, port 8050
├── docker-compose.yml      # Mounts $DATA_DIR/results → /data/results:ro
└── app/
    ├── app.py              # Dash app + gunicorn server object
    ├── layout.py           # Tab-based UI
    ├── figures.py          # All Plotly figure builders
    ├── analysis/
    │   ├── loader.py       # load_sample_sheet() (CSV/YAML), load_count_matrix()
    │   ├── dge_engine.py   # run_dge(), classify_genes(), get_top_genes() — PyDESeq2 wrapper
    │   └── pathway.py      # run_gsea_prerank(), run_enrichr_ora(), run_gprofiler_ora()
    └── callbacks/          # data, dge, viz, pathway, export — one file per tab
```

**UI workflow:** Load data → Run DGE → Explore plots (volcano, MA, PCA, heatmaps) → Pathway analysis → Export CSV/Excel.

**Key conventions:**
- Genes with zero counts across all samples are dropped before DGE.
- GSEA uses log2FoldChange as rank metric, `seed=42` for reproducibility.
- Enrichr and g:Profiler require outbound internet at analysis time.
- gunicorn timeout is 300 s — do not lower without profiling DGE + GSEA wall times.
- Dev server: `python -m app.app` or `sequoia-tertiary` (entry point in pyproject.toml).
- Full docs: `tertiary/README.md`.
