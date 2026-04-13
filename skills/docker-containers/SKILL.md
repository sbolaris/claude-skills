---
name: docker-containers
description: Building Docker containers for Nextflow and bioinformatics pipelines with conda pinning and multi-container patterns
tags: [docker, containers, nextflow, conda, bioinformatics]
---

# Skill: Docker Containers for Pipelines

**When to use:** Building Docker containers for Nextflow or other pipeline tools.

---

## Standard Dockerfile pattern

```dockerfile
FROM continuumio/miniconda3:latest

LABEL maintainer="team"
LABEL version="1.0.0"

# Pin ALL versions via build args
ARG FASTQC_VERSION=0.11.9
ARG STAR_VERSION=2.7.10b
ARG SUBREAD_VERSION=2.0.3

# Single RUN layer — minimizes image size
RUN conda install -y -c bioconda -c conda-forge \
    fastqc=${FASTQC_VERSION} \
    star=${STAR_VERSION} \
    subread=${SUBREAD_VERSION} \
    samtools \
    && conda clean -afy

RUN pip install --no-cache-dir boto3

COPY src/ /opt/pipeline/src/
RUN chmod +x /opt/pipeline/src/entrypoint.sh

ENTRYPOINT ["/opt/pipeline/src/entrypoint.sh"]
```

---

## Version locking

```bash
# Export lock file from a working conda env
conda env export --no-builds > environment_lock.yaml
```

Set tool versions as ENV vars so downstream scripts (reports) can read them:
```dockerfile
ENV FASTQC_VERSION=${FASTQC_VERSION} STAR_VERSION=${STAR_VERSION}
```

---

## Multi-stage builds (for compiled tools)

```dockerfile
# Build stage — compile tools
FROM ubuntu:22.04 AS builder
RUN apt-get install -y build-essential
COPY src/mytool/ /build/
RUN cd /build && cargo build --release

# Runtime stage — only what's needed to run
FROM continuumio/miniconda3:latest
COPY --from=builder /build/target/release/mytool /usr/local/bin/mytool
```

Use this when you have Rust/Go/C++ tools to compile but don't want build toolchains in the runtime image.

---

## Multi-container pattern (one container per tool ecosystem)

For large pipelines, use one container per software ecosystem to minimize image size, improve cache reuse, and make upgrades surgical.

```
containers/
├── build.sh          # Build/push all images
├── python/           # Python tools + scripts
├── fastqc/           # FastQC + JDK
├── star/             # STAR + samtools
├── subread/          # featureCounts
└── r/                # R scripts
```

**Always build from the project root** so `COPY src/...` paths resolve:
```bash
docker build -f containers/python/Dockerfile -t myrepo/pipeline-python:1.0.0 .
```

### build.sh pattern

```bash
#!/usr/bin/env bash
set -euo pipefail
REGISTRY="${REGISTRY:-myrepo}"; VERSION="${VERSION:-1.0.0}"; PUSH=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --push)     PUSH=1 ;;
    --version)  VERSION="$2"; shift ;;
    --registry) REGISTRY="$2"; shift ;;
  esac; shift
done

CONTAINERS=(python fastqc star subread r)
for NAME in "${CONTAINERS[@]}"; do
  IMAGE="${REGISTRY}/pipeline-${NAME}:${VERSION}"
  docker build -f "containers/${NAME}/Dockerfile" -t "${IMAGE}" .
  [[ $PUSH -eq 1 ]] && docker push "${IMAGE}"
done
```

---

## Nextflow integration

In `nextflow.config` — assign containers centrally, never in module files:
```groovy
def reg = params.container_registry
def ver = params.container_version
process {
    withName: 'stepA|stepB' { container = "${reg}/pipeline-python:${ver}" }
    withName: 'starAlign'    { container = "${reg}/pipeline-star:${ver}" }
}
```

Profiles:
```groovy
profiles {
    docker {
        docker.enabled    = true
        docker.runOptions = '-u $(id -u):$(id -g)'
    }
    awsbatch {
        process.executor = 'awsbatch'
        process.queue    = params.awsqueue
        aws.region       = params.awsregion
    }
}
```

---

## Local build and test workflow

```bash
docker build -t pipeline:dev .
docker run -it --rm -v $(pwd):/workspace -w /workspace pipeline:dev bash
docker images pipeline:dev   # check size
docker tag pipeline:dev myrepo/pipeline:1.0.0 && docker push myrepo/pipeline:1.0.0
```

---

## Common gotchas

- Pin ALL tool versions — `conda install fastqc` without a version picks whatever is latest at build time
- `conda clean -afy` after installs saves ~500MB by removing cache
- Scripts copied into the container must be `chmod +x` or called explicitly with interpreter
- Nextflow mounts the work directory into the container at runtime — process scripts run inside the container but access host paths via mounts
- Don't install R packages via both `conda` and `install.packages()` in the same image — pick one; conda is more reproducible
- Containers installing both samtools and sambamba may need a libcrypto symlink workaround if sambamba was compiled against a different OpenSSL version
