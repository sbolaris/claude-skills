---
name: nextflow-testing
description: Testing Nextflow pipelines — smoke tests, local tests, process debugging, and CI checklist
tags: [nextflow, testing, ci, bioinformatics]
---

# Skill: Testing Nextflow Pipelines

**When to use:** After writing or modifying Nextflow pipeline code. Extends nextflow-dsl2 with dedicated testing patterns.

---

## Test levels

| Level | Command | When |
|-------|---------|------|
| Smoke test | `-profile smoketest,docker` | After every change — fast, minimal data |
| Local test | `-profile localtest,docker` | Before committing — full data, all steps |
| Process test | Test single module in isolation | When debugging a specific step |
| Lint/syntax | `nextflow run main.nf --help` | Check param parsing and imports resolve |

---

## Test profile setup

`conf/testprofiles/smoketest.config`:
```groovy
params {
    reads        = "$baseDir/tests/data/*_{R1,R2}.fastq.gz"
    genome       = "hg38"
    genomes_base = "$baseDir/tests/refs"
    outDir       = "$baseDir/tests/results/smoketest"
    skipUmi      = false
    max_cpus     = 2
    max_memory   = '4.GB'
}
```

`conf/testprofiles/localtest.conf`:
```groovy
params {
    reads        = "$baseDir/tests/data/*_{R1,R2}.fastq.gz"
    genome       = "hg38"
    genomes_base = "~/genome-annotations"   // full reference
    outDir       = "$baseDir/tests/results/local"
    max_cpus     = 8
    max_memory   = '32.GB'
}
```

---

## Running tests

```bash
# Syntax check (no execution)
nextflow run main.nf --help

# Smoke test — fast validation
nextflow run main.nf -profile smoketest,docker

# Full local test
nextflow run main.nf -profile localtest,docker

# Resume after failure (re-uses cached work)
nextflow run main.nf -resume -profile localtest,docker

# Test single pipeline mode
nextflow run main.nf -profile localtest,docker --pipeline express
nextflow run main.nf -profile localtest,docker --pipeline complete

# Dry run — print workflow without executing
nextflow run main.nf -preview -profile localtest,docker
```

---

## Verifying process outputs

After a run, check:
```bash
ls results/Sample_Files/*/
ls results/report/

# Nextflow execution trace
cat results/pipeline_info/execution_trace.txt

# Work directory for debugging
ls work/xx/yyyyyy*/
cat work/xx/yyyyyy*/.command.log
cat work/xx/yyyyyy*/.command.err
cat work/xx/yyyyyy*/.command.sh   # exact script that ran
```

---

## Testing individual processes

```bash
# Run just one sample to validate a process change
nextflow run main.nf -profile localtest,docker \
  --reads './tests/data/SAMPLE1_{R1,R2}.fastq.gz'

# Test with SE mode
nextflow run main.nf -profile localtest,docker \
  --seqType SE \
  --reads './tests/data/SAMPLE1_'

# Test with ERCC spike
nextflow run main.nf -profile localtest,docker \
  --spikeType ercc \
  --genome hg38
```

---

## Checking report output

```bash
# HTML report opens in browser
open results/report/SAMPLE1_htmlReport.html

# Validate report has expected sections
grep -l "Alignment Summary" results/report/*.html
grep -l "Gene Counts" results/report/*.html

# CSV report check
head results/report/SAMPLE1_csvReport.csv
wc -l results/report/SAMPLE1_csvReport.csv  # should have header + data rows
```

---

## CI checklist before merging

- [ ] `nextflow run main.nf --help` exits 0
- [ ] Smoke test passes with docker profile
- [ ] HTML report generated and non-empty
- [ ] All expected output directories created
- [ ] `nextflow.config` version bumped
- [ ] Dockerfile version ARGs updated if tools changed
- [ ] Lock file regenerated if conda env changed

---

## Common failure patterns and fixes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Cannot find any reads` | Glob pattern wrong | Quote the pattern; add `*` wildcard |
| Process hangs at 0% | Insufficient memory | Increase `max_memory` in test profile |
| `No such file or directory` in process | stageAs path mismatch | Check `stageAs` names match script expectations |
| Report script fails | Missing output from upstream step | Check optional channels use `.ifEmpty([])` |
| Container pull error | Image not on registry | Run `docker build` locally first |
| Resume doesn't skip completed tasks | Work dir deleted or params changed | Check `-resume` is used, params unchanged |
