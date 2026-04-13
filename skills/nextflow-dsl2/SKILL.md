---
name: nextflow-dsl2
description: Nextflow DSL2 module patterns, channels, PE/SE handling, genomes config, container assignment, and testing
tags: [nextflow, dsl2, bioinformatics, pipeline, rnaseq]
---

# Skill: Nextflow DSL2 Pipeline Patterns

**When to use:** Building, modifying, or testing Nextflow DSL2 pipelines.

---

## Project structure

```
pipeline-name/
├── main.nf                    # Workflow entrypoint — params validation, channels, orchestration
├── nextflow.config            # Manifest, default params, profiles, resource limits
├── parameters.settings.json   # JSON schema for --help and param validation
├── Dockerfile                 # Single container or see docker-containers skill for multi-container
├── conf/
│   ├── base.config            # Resource labels (low_memory, high_memory, etc.)
│   ├── genomes.config         # Genome reference paths keyed by genome+spikeType
│   ├── awsbatch.config        # AWS Batch execution profile
│   └── testprofiles/
│       ├── smoketest.config   # Fast smoke test with small inputs
│       └── localtest.conf     # Full local test
├── modules/                   # One .nf file per process
└── src/                       # Scripts called inside processes
```

---

## DSL2 module pattern

Each module file contains one process. Import in `main.nf`:

```groovy
include { starAlign }                      from './modules/star'
include { countLongRNA; countMicroRNA }    from './modules/count_rna'  // multiple from one file
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
- Always use `emit:` names for outputs used downstream
- `tag` sets the label in execution logs — use sample name
- `label` maps to resource configs in `base.config`
- `publishDir mode: 'copy'` — outputs are available to downstream only via `output:` channels, not via publishDir

---

## Channel patterns

```groovy
// Read pairs from glob — size:-1 for SE (unknown count)
raw_reads = Channel
    .fromFilePairs(params.reads, size: params.skipUmi ? 1 : 2)
    .ifEmpty { exit 1, "Cannot find reads: ${params.reads}" }

// Optional channel — empty when feature is skipped
report_dedup = Channel.empty().ifEmpty([])

// Join two channels on sample name (first tuple element)
joined = channel_a.join(channel_b)

// Collect all per-sample files for batch processing
assembleReport(starAlign.out.report_star.collect())

// Combine for paired processing
thresholdResults(rpkm_ch.combine(counts_ch, by: 0), annoDirPath)
```

---

## Conditional steps (PE vs SE, optional features)

```groovy
if (params.seqType == "SE") {
    reads = params.reads + "*_R1*"
    params.skipUmi = true
} else {
    reads = params.reads + "*{R1,R2}*"
}

if (!params.skipUmi && params.seqType == "PE") {
    debarcode(raw_reads)
} else {
    debarcoded_ch = raw_reads
    report_debarcode = Channel.empty().ifEmpty([])
}
```

---

## join() + multiMap pattern (report assembly)

When a downstream process needs outputs from many upstream steps for the same sample:

```groovy
fastQc.out.report_fastqc
    .join(deb_report_ch)
    .join(cutAdapt.out.report_trim)
    .join(starAlign.out.report_star)
    .multiMap { name, fastqc, deb, trim, star ->
        names:  name
        fastqc: fastqc
        deb:    deb
        trim:   trim
        star:   star
    }
    .set { report_inputs }

assembleReport(report_inputs.names, report_inputs.fastqc, ...)
```

**Critical:** Every process contributing to a `.join()` chain MUST emit `tuple val(name), path(...)`. A `path(...)` only output cannot be joined.

---

## Optional channel placeholder for skipped steps

```groovy
// Same cardinality as the real channel so .join() still lines up
deb_report_ch = doUmi
    ? debarcode.out.report
    : raw_reads_ch.map { name, r -> tuple(name, []) }   // [name, empty list]
```

The downstream process receives `path([])` for skipped slots — check `params.skipUmi` inside the script to decide whether to render that section.

---

## Genome configuration pattern

```groovy
// conf/genomes.config
params {
    genomes {
        'hg38' {
            'NONE' {
                genomeDir    = "${params.genomes_base}/hg38/NONE/star"
                sjdbGTFFile  = "${params.genomes_base}/hg38/NONE/annotation/genes.gtf"
                miRNABedFile = "${params.genomes_base}/hg38/NONE/annotation/miRNA.bed"
            }
        }
    }
}

// main.nf — resolve to file objects at startup
genomeDirPath = file(params.genomes[params.genome][params.spikeType].genomeDir)
```

---

## Resource labels

```groovy
process {
    withLabel: low_memory  { memory = { check_max(4.GB  * task.attempt, 'memory') }; cpus = 1 }
    withLabel: high_memory { memory = { check_max(32.GB * task.attempt, 'memory') }; cpus = 8 }
}
```

Always use `check_max()` with retry multiplier so jobs scale on retry.

---

## Container assignment (centralized in nextflow.config)

Never put `container` directives in module files:

```groovy
def reg = params.container_registry
def ver = params.container_version
process {
    withName: 'validateInputs|cutAdapt|assembleReport' { container = "${reg}/pipeline-python:${ver}" }
    withName: 'starAlign'                               { container = "${reg}/pipeline-star:${ver}" }
}
```

Switch registry at runtime: `nextflow run main.nf --container_registry 123456.dkr.ecr.us-west-2.amazonaws.com`

---

## Testing

### Test levels

| Level | Command | When |
|-------|---------|------|
| Syntax check | `nextflow run main.nf --help` | Every change |
| Smoke test | `-profile smoketest,docker` | After every change — fast, minimal data |
| Local test | `-profile localtest,docker` | Before committing — full data, all steps |

### Test profile setup

```groovy
// conf/testprofiles/smoketest.config
params {
    reads        = "$baseDir/tests/data/*_{R1,R2}.fastq.gz"
    genome       = "hg38"
    genomes_base = "$baseDir/tests/refs"
    outDir       = "$baseDir/tests/results/smoketest"
    max_cpus     = 2
    max_memory   = '4.GB'
}
```

### Running tests

```bash
nextflow run main.nf --help                                  # syntax + param check
nextflow run main.nf -profile smoketest,docker               # fast validation
nextflow run main.nf -profile localtest,docker               # full run
nextflow run main.nf -resume -profile localtest,docker       # re-use cached work
nextflow run main.nf -profile localtest,docker --pipeline express  # specific mode
```

### Debugging a failed process

```bash
# Find failed task work dir
ls work/xx/yyyyyy*/
cat work/xx/yyyyyy*/.command.log    # stdout
cat work/xx/yyyyyy*/.command.err    # stderr
cat work/xx/yyyyyy*/.command.sh     # exact script that ran
```

### CI checklist

- [ ] `nextflow run main.nf --help` exits 0
- [ ] Smoke test passes with docker profile
- [ ] HTML report generated and non-empty
- [ ] All expected output directories created
- [ ] `nextflow.config` version bumped if applicable
- [ ] Lock file regenerated if conda env changed

---

## Common gotchas

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Cannot find any reads` | Glob pattern wrong | Quote the pattern; add `*` wildcard |
| Process hangs at 0% | Insufficient memory | Increase `max_memory` in test profile |
| `No such file or directory` in process | stageAs path mismatch | Check `stageAs` names match script expectations |
| Report fails | Missing output from upstream | Check optional channels use `.ifEmpty([])` |
| Resume doesn't skip | Params changed or work dir deleted | Check `-resume` is used, params unchanged |
| Container pull error | Image not on registry | `docker build` locally first |

- Optional channels must use `.ifEmpty([])` before `.collect()` to avoid blocking the pipeline
- Genome/spike validation at startup — add new genomes to both `acceptableGenomes` list AND `conf/genomes.config`
- `size: -1` in `fromFilePairs` needed for SE mode where file count is unknown
