# Skill: Docker for Bioinformatics Pipelines

**When to use:** Building Docker containers for Nextflow/bioinformatics pipelines.

**Captured from:** SEQuoia-Complete and Sequoia_express_toolkit Dockerfile review.

---

## Standard Dockerfile pattern for Nextflow pipelines

```dockerfile
FROM continuumio/miniconda3:latest

# Metadata
LABEL maintainer="Bio-Rad"
LABEL version="1.0.0"
LABEL description="Sequoia Spectrum RNAseq pipeline"

# Build args for versions (pin everything)
ARG FASTQC_VERSION=0.11.9
ARG STAR_VERSION=2.7.10b
ARG PICARD_VERSION=2.27.5
ARG SUBREAD_VERSION=2.0.3
ARG SAMBAMBA_VERSION=0.8.2

# Single RUN layer for all conda installs (minimizes image size)
RUN conda install -y -c bioconda -c conda-forge \
    fastqc=${FASTQC_VERSION} \
    star=${STAR_VERSION} \
    picard=${PICARD_VERSION} \
    subread=${SUBREAD_VERSION} \
    sambamba=${SAMBAMBA_VERSION} \
    cutadapt \
    samtools \
    && conda clean -afy

# Python dependencies (use pip inside conda env)
RUN pip install --no-cache-dir boto3

# Copy pipeline scripts
COPY src/ /opt/biorad/src/
RUN chmod +x /opt/biorad/src/entrypoint.sh

# Write version info for report
RUN echo "Image: sequoia-spectrum" > /opt/biorad/imageInfo.txt \
    && echo "Version: ${VERSION}" >> /opt/biorad/imageInfo.txt \
    && echo "Build: $(date +%Y%m%d)" >> /opt/biorad/imageInfo.txt

ENTRYPOINT ["/opt/biorad/src/entrypoint.sh"]
```

---

## Version locking with lock file

Generate a lock file from a conda environment:
```bash
conda env export --no-builds > environment_lock.yaml
```

The lock file (`*_lock.yaml`) is used inside the container for version reporting in the report.

---

## Environment variables for tool versions

Set in Dockerfile so the report can read them:
```dockerfile
ENV FASTQC_VERSION=${FASTQC_VERSION} \
    STAR_VERSION=${STAR_VERSION} \
    PICARD_VERSION=${PICARD_VERSION} \
    SUBREAD_VERSION=${SUBREAD_VERSION} \
    SAMBAMBA_VERSION=${SAMBAMBA_VERSION} \
    Software\ Name="Sequoia Spectrum"
```

Read in the report script:
```javascript
// or in R: Sys.getenv("STAR_VERSION")
const versions = {
    star: process.env.STAR_VERSION,
    fastqc: process.env.FASTQC_VERSION,
};
```

---

## Multi-stage builds (optional, for smaller images)

```dockerfile
# Build stage — compile tools
FROM ubuntu:22.04 AS builder
RUN apt-get install -y build-essential
COPY src/rumi/ /build/rumi/
RUN cd /build/rumi && cargo build --release

# Runtime stage — only what's needed to run
FROM continuumio/miniconda3:latest
COPY --from=builder /build/rumi/target/release/rumi /usr/local/bin/rumi
```

Use this when you have Rust/Go/C++ tools to compile but don't want build toolchains in the runtime image.

---

## Multi-container-per-ecosystem pattern (Sequoia Spectrum)

Instead of one monolithic container, use one container per software ecosystem. This minimizes image size, improves cache reuse, and makes upgrades surgical.

### Directory layout
```
containers/
├── build.sh          # Build/push all images from project root
├── python/           # Python 3.7 + cutadapt + pandas/pysam/openpyxl + samtools + sambamba + src/ scripts
├── fastqc/           # FastQC + JDK only
├── star/             # STAR + samtools + sambamba
├── picard/           # Picard + JDK + samtools
├── dedup/            # rumi binary + umi-tools + samtools + sambamba
├── samtools/         # samtools + bedtools + sambamba (BAM splitting)
├── subread/          # featureCounts only
└── r/                # R base + threshold_results.R
```

Each subdir has `Dockerfile` + `env.yaml`. **Always build from the project root** so `COPY src/...` paths work:
```bash
docker build -f containers/python/Dockerfile -t bioraddbg/sequoia-spectrum-python:1.0.0 .
```

### Container assignment in nextflow.config (withName selectors)
Assign containers centrally in `nextflow.config` — never in module files. This keeps modules clean and allows deployment-time override:
```groovy
def reg = params.container_registry   // e.g. 'bioraddbg' or ECR URL
def ver = params.container_version    // e.g. '1.0.0'

process {
    withName: 'validateInputs|debarcode|cutAdapt|umiTagging|calcRPKMTPM|combinedXLS|assembleReport|batchReport' {
        container = "${reg}/sequoia-spectrum-python:${ver}"
    }
    withName: 'fastQc'                              { container = "${reg}/sequoia-spectrum-fastqc:${ver}" }
    withName: 'starAlign'                           { container = "${reg}/sequoia-spectrum-star:${ver}" }
    withName: 'picardAlignSummary'                  { container = "${reg}/sequoia-spectrum-picard:${ver}" }
    withName: 'deduplication|deduplication_umitools' { container = "${reg}/sequoia-spectrum-dedup:${ver}" }
    withName: 'splitBamMi|splitBamLong'             { container = "${reg}/sequoia-spectrum-samtools:${ver}" }
    withName: 'countLongRNA|countMicroRNA'          { container = "${reg}/sequoia-spectrum-subread:${ver}" }
    withName: 'thresholdResults'                    { container = "${reg}/sequoia-spectrum-r:${ver}" }
}
```

Switch all 8 images to ECR at runtime:
```bash
nextflow run main.nf --container_registry 123456.dkr.ecr.us-west-2.amazonaws.com --container_version 1.0.0
```

### build.sh pattern
```bash
#!/usr/bin/env bash
# Run from project root: bash containers/build.sh [--push] [--version 1.0.0] [--registry bioraddbg]
set -euo pipefail
REGISTRY="${REGISTRY:-bioraddbg}"; VERSION="${VERSION:-1.0.0}"; PUSH=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --push)     PUSH=1 ;;
    --version)  VERSION="$2"; shift ;;
    --registry) REGISTRY="$2"; shift ;;
  esac; shift
done

CONTAINERS=(python fastqc star picard dedup samtools subread r)
BUILD_ARGS=(
  --build-arg "SOURCE_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo local)"
  --build-arg "SOURCE_COMMIT=$(git rev-parse --short HEAD   2>/dev/null || echo local)"
)

for NAME in "${CONTAINERS[@]}"; do
  IMAGE="${REGISTRY}/sequoia-spectrum-${NAME}:${VERSION}"
  docker build -f "containers/${NAME}/Dockerfile" --build-arg "IMAGE_NAME=${IMAGE}" \
    "${BUILD_ARGS[@]}" -t "${IMAGE}" .
  [[ $PUSH -eq 1 ]] && docker push "${IMAGE}"
done
```

### libcrypto fix (samtools + sambamba conflict)
Containers that install both samtools and sambamba need this workaround — sambamba was compiled against libcrypto 1.0.0 but conda ships 1.1.x:
```dockerfile
RUN cp /opt/conda/envs/sequoia-dedup/lib/libcrypto.so.1.1 \
       /opt/conda/envs/sequoia-dedup/lib/libcrypto.so.1.0.0
```

### Nextflow + Docker integration

In `nextflow.config`:
```groovy
// Profiles
profiles {
    docker {
        docker.enabled = true
        docker.runOptions = '-u $(id -u):$(id -g)'  // run as current user
    }
    awsbatch {
        process.executor = 'awsbatch'
        process.queue = params.awsqueue
        aws.region = params.awsregion
    }
}
```

---

## Local build and test workflow

```bash
# Build image
docker build -t sequoia-spectrum:dev .

# Test locally with Nextflow
nextflow run main.nf -profile docker,localtest \
  --reads './tests/*_{R1,R2}.fastq.gz' \
  --genome hg38

# Run interactively to debug a process
docker run -it --rm \
  -v $(pwd):/workspace \
  -w /workspace \
  sequoia-spectrum:dev bash

# Check image size
docker images sequoia-spectrum:dev

# Push to registry
docker tag sequoia-spectrum:dev bioraddbg/sequoia-spectrum:1.0.0
docker push bioraddbg/sequoia-spectrum:1.0.0
```

---

## Hooks/build script pattern

Bio-Rad uses a `hooks/build` script for automated Docker Hub builds:
```bash
#!/bin/bash
docker build \
  --build-arg FASTQC_VERSION=0.11.9 \
  --build-arg STAR_VERSION=2.7.10b \
  -t $IMAGE_NAME .
```

---

## Common gotchas

- Pin ALL tool versions in the Dockerfile — `conda install fastqc` without a version will pick whatever is latest at build time
- `conda clean -afy` after installs saves ~500MB by removing cache
- Scripts copied into the container must be `chmod +x` or called explicitly with interpreter (`bash script.sh`, `python script.py`)
- Nextflow mounts the work directory into the container at runtime — process scripts run inside the container but access host paths via mounts
- Don't install R packages via `conda` and `install.packages()` in the same image — pick one; conda is more reproducible
