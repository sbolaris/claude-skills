---
name: bioinformatics-reference-vendoring
description: "Vendor small, slow-changing reference annotations (miRBase GFF3, ERCC SDF, blacklist BED, primer sequences, gene panels) into a Nextflow repo with a regenerator workflow. Use when adding reference data that should be version-pinned with the code rather than living in --genomes_base storage."
tags: [nextflow, bioinformatics, reference-data, vendoring]
---

# Skill: Bioinformatics Reference Vendoring in Nextflow Repos

**When to use:** Adding small, slow-changing reference annotations (miRBase GFF3, ERCC SDF, blacklist BED, primer sequences, gene panels) to a Nextflow pipeline. The big stuff (genome FASTA, STAR index) should still live in `--genomes_base` storage (S3 or local mount); this skill is about the *small* annotations that benefit from being version-pinned with the repo.

**Pattern:** Vendor the processed files in `resources/<kind>/`, configure paths via `${baseDir}/resources/...`, and ship a regenerator workflow so the vendored files aren't a black box.

---

## Layout

```
pipeline-root/
├── resources/
│   └── mirna/
│       ├── hg38_miRNA_annotation.gff3       # processed, drop-in ready
│       ├── hg38_miRNA_annotation.gtf
│       ├── mm10_miRNA_annotation.gff3
│       └── ...
├── src/genome_build/
│   ├── mirbase_normalize_gff3.py            # per-species chr-rename rules
│   └── mirbase_gff3_to_gtf.py               # featureCounts-friendly converter
├── modules/genome_build/
│   └── mirna_annotations.nf                 # downloadMirbaseGff3 + normalize + buildGtf
├── workflows/
│   └── mirna_build.nf                       # MIRNA_BUILD sub-workflow
├── conf/
│   ├── mirna_sources.config                 # genome → upstream source code mapping
│   └── genomes.config                       # paths point at ${baseDir}/resources/mirna/...
└── tests/test_genome_build/
    ├── test_mirbase_normalize_gff3.py
    ├── test_mirbase_gff3_to_gtf.py
    └── test_vendored_mirna.py               # sanity checks on shipped files
```

---

## Steps

### 1. Verify upstream state before processing

Open every raw input and look at:
- Chromosome naming: UCSC `chr*`, Ensembl `1`, TAIR `Chr1`, WormBase `I`?
- Genome build / assembly identifier in the file header
- Feature types present (`miRNA`, `miRNA_primary_transcript`, etc.)
- Whether expected transformations (liftOver, chr-rename) are still needed

**Don't trust outdated plans.** miRBase v22 (2018) already ships `dme.gff3` on Release_6 coordinates (= dm6), so the dm3→dm6 liftOver step described in older nf-core templates is wrong for current inputs. Always inspect first.

Quick audit script:

```bash
for f in ~/*.gff3; do
  echo "=== $(basename $f) ==="
  head -8 "$f" | grep -E '^#'      # header metadata (build, date, source version)
  grep -v '^#' "$f" | awk '{print $1}' | sort -u | head -8   # chromosomes
  grep -v '^#' "$f" | awk '{print $3}' | sort | uniq -c     # feature types
done
```

### 2. Write idempotent processors

Two scripts is usually clean: one normalizes chromosome naming, one converts to whatever downstream format you need. Keep the normalization rules even if they're no-ops for current inputs — they document intent and protect against future upstream changes.

```python
# src/genome_build/mirbase_normalize_gff3.py
ROMAN = {"I", "II", ..., "XX"}

def rename_ath(chrom):  # TAIR: Chr1 -> chr1, ChrC -> chrc
    if chrom.startswith("Chr"):
        return "chr" + chrom[3:].lower()
    return chrom

def rename_cel(chrom):  # WormBase: I -> chrI
    if chrom in ROMAN:
        return "chr" + chrom
    return chrom

def rename_ensembl_to_ucsc(chrom):  # 1 -> chr1, MT -> chrM
    if chrom == "MT": return "chrM"
    if re.fullmatch(r"[0-9]+|[XY]", chrom): return "chr" + chrom
    return chrom

RULES = {"ath": rename_ath, "cel": rename_cel,
         "dme": lambda c: c,  # already chr2L/2R/...
         "dre": rename_ensembl_to_ucsc, "hsa": ..., "mmu": ..., "rno": ...}
```

Idempotency matters — running the same script on output should produce identical output. The chr-rename rules above are idempotent because `chr1` already starts with `chr` so `rename_ensembl_to_ucsc` is a no-op on it.

### 3. Configure paths via `${baseDir}`

In `conf/genomes.config`, defaults resolve to repo-relative paths:

```groovy
'hg38' {
    'NONE' {
        miRNAGff3File = "${baseDir}/resources/mirna/hg38_miRNA_annotation.gff3"
        miRNAgtfFile  = "${baseDir}/resources/mirna/hg38_miRNA_annotation.gtf"
        // ...big files still under genomes_base...
        genomeDir     = "${params.genomes_base}/hg38/star_ncbi/"
    }
}
```

`${baseDir}` is the project root where `main.nf` lives. Works for local, Docker, and AWS Batch — Nextflow stages the project files into the work directory.

For ERCC/spike-in variants of the same genome, point `miRNA*File` at the same vendored file (miRNA annotation doesn't depend on spike-ins).

### 4. Ship a regenerator sub-workflow

Vendored files become stale when the upstream source updates. The pipeline should be able to refresh itself:

```groovy
// workflows/mirna_build.nf
include { downloadMirbaseGff3; normalizeMirnaGff3; buildMirnaGtf
        } from '../modules/genome_build/mirna_annotations'

workflow MIRNA_BUILD {
    take:
    genome_name
    mirbase_code

    main:
    downloadMirbaseGff3(genome_name, mirbase_code)
    normalizeMirnaGff3(downloadMirbaseGff3.out.gff3, mirbase_code)
    buildMirnaGtf(normalizeMirnaGff3.out.gff3)

    emit:
    gff3 = normalizeMirnaGff3.out.gff3
    gtf  = buildMirnaGtf.out.gtf
}
```

Gate it in `main.nf` parallel to `--build_genome`:

```groovy
if (params.build_mirna) {
    def gname = params.genome_name ?: 'custom'
    def src   = params.mirna_sources?.get(gname)
    if (!src?.mirbase_code) {
        exit 1, "ERROR: --build_mirna requires --genome_name to be one of: ${params.mirna_sources?.keySet()?.sort()?.join(', ')}"
    }
    MIRNA_BUILD(Channel.value(gname), Channel.value(src.mirbase_code))
    return
}
```

`--genome_outDir` is path-configurable (local mount or `s3://`), so the same workflow scaffolds the folder structure for any environment.

### 5. Source mapping in its own config

```groovy
// conf/mirna_sources.config
params {
    mirbase_ftp_base = 'https://mirbase.org/download'

    mirna_sources {
        'hg38'     { mirbase_code = 'hsa' }
        'mm10'     { mirbase_code = 'mmu' }
        // ...
    }
}
```

Include from `nextflow.config` unconditionally — the params block is inert until `--build_mirna` is set. Strict parser doesn't allow conditional `includeConfig`, so always-include is the only pattern that works.

### 6. Sanity tests on the vendored files

Three test files cover the trio:

```python
# tests/test_genome_build/test_vendored_<kind>.py
SUPPORTED = {"hg38", "mm10", "rnor6", "tair10", "ce11", "dm6", "danRer11"}

class TestVendoredFilesPresent:
    def test_all_genomes_have_both_files(self):
        for g in SUPPORTED:
            assert (REPO/f"resources/mirna/{g}_miRNA_annotation.gff3").exists()
            assert (REPO/f"resources/mirna/{g}_miRNA_annotation.gtf").exists()

class TestSanity:
    def test_chromosomes_are_ucsc_or_allowed_scaffold(self):
        # `chr*` or known unplaced-contig prefixes (KN/KZ/CP/DS for some genomes)
        ...

    def test_feature_count_matches(self):
        # Mature miRNA count in GFF3 == row count in derived GTF
        ...
```

Plus unit tests for the processor scripts (rename rules, GTF format).

---

## Source-of-truth tradeoff

When you flip a config to point at vendored files for genomes that previously consumed operator-supplied files (`genomes_base/<genome>/anno_ncbi/...`), call it out in the PR: prod runs will start consuming the new vendored content, which may differ in record count if upstream has added/dropped entries since the operator's snapshot.

Mitigations:
- Stamp the upstream version in the vendored file headers (most GFF3s already do) so divergence is auditable
- Keep the regenerator workflow runnable so operators can validate against current upstream
- Allow operator override via custom config that points the path back at `genomes_base`

---

## What NOT to vendor

Don't vendor large files (>10 MB) in the repo. That includes:
- Genome FASTA
- STAR / HISAT2 / Salmon indexes
- Chain files
- BAM/VCF test data
- Anything binary or that grows with each upstream release

Keep the repo lean — those belong in S3/object storage referenced via `--genomes_base`. The vendoring pattern in this skill is specifically for small text annotations under a few MB total.
