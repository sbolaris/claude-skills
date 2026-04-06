# Skill: Nextflow DSL2 RNAseq Pipeline Patterns

**When to use:** Building or modifying Nextflow DSL2 pipelines for RNAseq analysis (Bio-Rad Sequoia pattern).

**Captured from:** SEQuoia-Complete and Sequoia_express_toolkit analysis session.

---

## Project structure

```
pipeline-name/
├── main.nf                    # Workflow entrypoint — params validation, channel creation, process orchestration
├── nextflow.config            # Manifest, default params, profiles, resource limits
├── parameters.settings.json   # JSON schema for --help output and param validation
├── Dockerfile                 # Single container with all tools
├── conf/
│   ├── base.config            # Resource labels (low_memory, high_memory, etc.)
│   ├── genomes.config         # Genome reference paths keyed by genome+spikeType
│   ├── awsbatch.config        # AWS Batch execution profile
│   ├── indocker.conf          # Run inside Docker (for local dev)
│   └── testprofiles/
│       ├── smoketest.config   # Fast smoke test with small inputs
│       └── localtest.conf     # Full local test
├── modules/                   # One .nf file per process
│   ├── validate_inputs.nf
│   ├── fastqc.nf
│   ├── debarcode.nf           # UMI extraction (PE mode only)
│   ├── cutadapt.nf
│   ├── star.nf
│   ├── picard.nf
│   ├── deduplication.nf       # UMI dedup (PE mode only)
│   ├── genecount.nf           # featureCounts / subread
│   ├── rpkm.nf
│   └── report.nf
└── src/                       # Scripts called inside processes
    ├── entrypoint.sh
    ├── debarcode.py
    ├── tagBamFile.py
    ├── calc_rpkm_tpm.py
    └── report.*               # Report generation scripts
```

---

## DSL2 module pattern

Each module file contains one process. Import it in `main.nf`:

```groovy
include { starAlign }         from './modules/star'
include { countLongRNA; countMicroRNA } from './modules/count_rna'  // multiple from one file
```

Process structure:
```groovy
process starAlign {
    label 'high_memory'
    tag "$name"
    publishDir "${params.outDir}/Sample_Files/$name/star", mode: 'copy'

    input:
    tuple val(name), path(reads)
    path genomeDir
    path sjdbGTFFile

    output:
    tuple val(name), path("${name}_Aligned.sortedByCoord.out.bam"), emit: starBam_ch
    tuple val(name), path("${name}_Log.final.out"),                  emit: report_star

    script:
    """
    STAR --runThreadN ${task.cpus} \
         --genomeDir $genomeDir \
         --readFilesIn $reads \
         --outSAMtype BAM SortedByCoordinate \
         --outFileNamePrefix ${name}_
    """
}
```

Key rules:
- Always use `emit:` names for outputs that are used downstream
- `tag` sets the label shown in execution logs (use sample name)
- `label` maps to resource configs in `base.config`
- `publishDir` with `mode: 'copy'` copies outputs to results dir

---

## Channel patterns

```groovy
// Read pairs from glob — use size:-1 for SE (unknown count)
raw_reads = Channel
    .fromFilePairs(params.reads, size: params.skipUmi ? 1 : 2)
    .ifEmpty { exit 1, "Cannot find reads: ${params.reads}" }

// Optional channel — empty if feature not used
report_dedup = Channel.empty().ifEmpty([])

// Join two channels on sample name (first tuple element)
calcRPKMTPM(count_rna.out.counts_ch.join(calcRPKMTPM.out.rpkm_tpm_ch))

// Collect all files from per-sample channel for batch processing
assembleReport(starAlign.out.report_star.collect())

// Combine for paired processing
thresholdResults(rpkm_ch.combine(counts_ch, by: 0), annoDirPath)
```

---

## PE vs SE mode handling

```groovy
// In main.nf
if (params.seqType == "SE") {
    reads = params.reads + "*_R1*"
    params.skipUmi = true
} else {
    reads = params.reads + "*{R1,R2}*"
}

// UMI-aware steps are gated:
if (!params.skipUmi && params.seqType == "PE") {
    debarcode(raw_reads)
    // ...
} else {
    debarcoded_ch = raw_reads
    report_debarcode = Channel.empty().ifEmpty([])
}
```

---

## Pipeline selection pattern (sequoia-spectrum)

Two modes: `express` and `complete`. Default is `none` (auto-detect from file sizes).

```groovy
// nextflow.config
params {
    pipeline = "none"   // "express" | "complete" | "none" (auto-detect)
}

// main.nf — resolve mode at startup
def pipelineMode = params.pipeline == "none"
    ? autoDetectPipeline(params.reads)
    : params.pipeline

if (pipelineMode == "complete") {
    // miRNA-specific steps
    splitBamMi(...)
    countMicroRNA(...)
}
if (pipelineMode == "express") {
    // Express-only steps
    thresholdResults(...)
    combinedXLS(...)
    metaReport(...)
}
```

Auto-detection logic: R1 >> R2 in file size → complete (R2 is short UMI barcode). R1 ≈ R2 → express. Only R1 → exit with error asking user to specify. See `sequoia-spectrum-project.md` for full implementation.

---

## Genome configuration pattern

`conf/genomes.config` maps `genome + spikeType` to reference file paths:

```groovy
params {
    genomes {
        'hg38' {
            'NONE' {
                genomeDir             = "${params.genomes_base}/hg38/NONE/star"
                annoDir               = "${params.genomes_base}/hg38/NONE/annotation"
                sjdbGTFFile           = "${params.genomes_base}/hg38/NONE/annotation/genes.gtf"
                refFlatFile           = "${params.genomes_base}/hg38/NONE/annotation/refFlat.txt"
                ribosomalIntervalFile = "${params.genomes_base}/hg38/NONE/annotation/rRNA.interval_list"
                longRNAgtfFile        = "${params.genomes_base}/hg38/NONE/annotation/longRNA.gtf"
                miRNABedFile          = "${params.genomes_base}/hg38/NONE/annotation/miRNA.bed"  // complete only
                miRNAgtfFile          = "${params.genomes_base}/hg38/NONE/annotation/miRNA.gtf"  // complete only
                sizesFile             = "${params.genomes_base}/hg38/NONE/annotation/chrom.sizes"
                geneId                = "gene_id"
            }
        }
    }
}
```

In `main.nf`, resolve to file objects at startup:
```groovy
genomeDirPath = file(params.genomes[params.genome][params.spikeType].genomeDir)
```

---

## Resource labels (base.config)

```groovy
process {
    withLabel: low_memory  { memory = { check_max(4.GB  * task.attempt, 'memory') }; cpus = 1 }
    withLabel: high_memory { memory = { check_max(32.GB * task.attempt, 'memory') }; cpus = 8 }
    withLabel: micro_cpu   { cpus = 1 }
}
```

Always use `check_max()` with retry multiplier so jobs scale on retry.

---

## Complete vs Express key differences

| Feature | Complete (2D) | Express |
|---------|--------------|---------|
| Read mode | PE + UMI only | PE or SE |
| miRNA counting | Yes (splitBam → countMicroRNA) | No |
| Spike support | ercc, miltenyi | ercc only |
| Supported genomes | rnor6, hg38, mm10 | + tair10, sacCer3, dm6, danRer11, ce11 |
| Gene thresholding | No | Yes (thresholdResults) |
| Excel output | No | Yes (combinedXLS) |
| Batch/meta report | No | Yes (metaReport) |
| Report format | HTML + PDF | HTML + PDF + CSV |
| RPKM module | Separate (rpkm.nf) | Inside genecount.nf |

---

## Testing locally

```bash
# Smoke test (fast, uses bundled test data)
nextflow run main.nf -profile smoketest,docker

# Local test with real data
nextflow run main.nf -profile localtest,docker \
  --reads './tests/*_{R1,R2}.fastq.gz' \
  --genome hg38 \
  --genomes_base ~/genome-annotations \
  --outDir ./results

# Resume after failure (uses cached task results)
nextflow run main.nf -resume -profile localtest,docker ...

# Validate without running
nextflow run main.nf --help
```

---

## Per-sample report assembly (join + multiMap pattern)

When `assembleReport` needs QC files from multiple upstream processes for the same sample, chain `.join()` by sample name then fan out with `.multiMap`:

```groovy
// All upstream report outputs emit:  tuple val(name), path(...)
fastQc.out.report_fastqc
    .join(deb_report_ch)               // [name, []] when step is skipped
    .join(cutAdapt.out.report_trim)
    .join(starAlign.out.report_star)
    .join(picardAlignSummary.out.report_picard)
    .join(dedup_report_ch)             // [name, []] when step is skipped
    .join(countLongRNA.out.report_counts)
    .multiMap { name, fastqc, deb, trim, star, picard, dedup, counts ->
        names:    name
        fastqc:   fastqc
        debarcode: deb
        trim:     trim
        star:     star
        picard:   picard
        dedup:    dedup
        counts:   counts
    }
    .set { report_inputs }

assembleReport(
    report_inputs.names,
    report_inputs.fastqc,
    report_inputs.debarcode,
    report_inputs.trim,
    report_inputs.star,
    report_inputs.picard,
    report_inputs.dedup,
    report_inputs.counts
)
```

**Critical:** Every process that contributes to `assembleReport` MUST emit `tuple val(name), path(...)` — the `val(name)` is what makes `.join()` work. A `path(...)` only output cannot be joined.

---

## Optional channel placeholder for skipped steps

When a step is conditionally skipped (e.g., no UMI → skip debarcode + dedup), create a same-cardinality dummy channel so `.join()` still lines up:

```groovy
// doUmi = params.seqType == 'PE' && !params.skipUmi
deb_report_ch = doUmi
    ? debarcode.out.report
    : raw_reads_ch.map { name, r -> tuple(name, []) }   // [name, empty list]

dedup_report_ch = doUmi
    ? dedup_report_emit                                  // from rumi or umitools branch
    : raw_reads_ch.map { name, r -> tuple(name, []) }
```

The downstream process receives `path([])` for the skipped slot — use `params.skipUmi` inside the script to decide whether to render that section.

---

## val(name) in all report outputs — convention

**Every** report-type process output must include `val(name)`:
```groovy
output:
tuple val(name), path("${name}_Log.final.out"), emit: report_star     // ✓
path("${name}_Log.final.out"),                  emit: report_star     // ✗ cannot join
```

This applies to: `report_fastqc`, `report` (debarcode), `report_trim`, `report_star`, `report_picard`, `report_dedup`, `report_counts`, `report_mirna_counts`.

---

## Per-process container assignment (withName in nextflow.config)

Never put `container` directives in module files. Assign centrally in `nextflow.config`:
```groovy
def reg = params.container_registry
def ver = params.container_version
process {
    withName: 'validateInputs|debarcode|cutAdapt|umiTagging|calcRPKMTPM|combinedXLS|assembleReport|batchReport' {
        container = "${reg}/sequoia-spectrum-python:${ver}"
    }
    withName: 'fastQc'      { container = "${reg}/sequoia-spectrum-fastqc:${ver}" }
    withName: 'starAlign'   { container = "${reg}/sequoia-spectrum-star:${ver}" }
    // etc.
}
```

---

## Common gotchas

- `stageAs` in process inputs renames/organizes files into subdirs for the report R script — preserve these exact paths when porting to JS report
- Optional channels must use `.ifEmpty([])` before `.collect()` to avoid blocking the pipeline
- `publishDir` copies happen after process completes; don't rely on them being available to downstream processes (use `output:` channels instead)
- Genome/spike validation happens at startup — add new genomes to `acceptableGenomes` list AND `conf/genomes.config`
- The `size: -1` option in `fromFilePairs` is needed for SE mode where file count is unknown
