---
name: packer-ecs-batch-ami
description: "Build custom ECS-optimized AMIs for AWS Batch with Docker storage moved off the root volume and a large scratch disk for pipeline workloads such as Nextflow."
tags: [packer, ami, aws-batch, ecs, nextflow]
---

# Packer ECS-Optimized AMI for AWS Batch

Build custom AMIs for AWS Batch that use the ECS-optimized AL2 base, move Docker storage off the root volume, and add a large scratch disk for pipeline workloads (e.g. Nextflow).

## When to use

- AWS Batch jobs need more Docker or scratch disk than the default ECS-optimized AMI provides
- Nextflow pipelines write large intermediate files that overflow the root or Docker volume
- Replacing plain AL2 + devicemapper (deprecated) with ECS-optimized AL2 + ext4

## Template Structure

```
packer/ecs-batch-ami/
├── aws.pkr.hcl
└── scripts/
    ├── 01_configure_swap.sh
    ├── 02_install_packages.sh
    ├── 03_install_awscli_v2.sh
    ├── 04_install_miniconda.sh
    ├── 05_configure_docker_volume.sh
    └── 06_configure_scratch_disk.sh
```

## `aws.pkr.hcl`

```hcl
packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

variable "root_volume_size_gb"   { type = number; default = 50 }
variable "docker_volume_size_gb" { type = number; default = 50 }   # 50 GB is enough when pipeline code redirects reads to scratch
variable "scratch_volume_size_gb" { type = number; default = 1250 }
variable "aws_region"            { type = string; default = "us-west-2" }
variable "ami_regions"           { type = list(string); default = ["us-west-2", "eu-west-1"] }
variable "vpc_id"                { type = string; default = "" }
variable "subnet_id"             { type = string; default = "" }

locals {
  ami_name = "ecs-batch-ami-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"
}

data "amazon-ami" "ecs_optimized" {
  filters     = { name = "amzn2-ami-ecs-hvm-*-x86_64-ebs" }
  owners      = ["amazon"]
  most_recent = true
  region      = var.aws_region
}

source "amazon-ebs" "ecs-batch" {
  ami_name      = local.ami_name
  instance_type = "m5.xlarge"
  region        = var.aws_region
  ami_regions   = var.ami_regions   # copies AMI to all listed regions after build
  source_ami    = data.amazon-ami.ecs_optimized.id
  ssh_username  = "ec2-user"

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  shutdown_behavior = "terminate"

  aws_polling { delay_seconds = 30; max_attempts = 120 }

  # Root volume
  launch_block_device_mappings {
    device_name = "/dev/xvda"; volume_size = var.root_volume_size_gb
    encrypted = true; volume_type = "gp3"; delete_on_termination = true
  }
  # Docker storage — keeps Docker layer cache off root
  launch_block_device_mappings {
    device_name = "/dev/xvdb"; volume_size = var.docker_volume_size_gb
    volume_type = "gp3"; delete_on_termination = true
  }
  # Scratch disk for pipeline work dirs
  launch_block_device_mappings {
    device_name = "/dev/xvdc"; volume_size = var.scratch_volume_size_gb
    volume_type = "gp3"; delete_on_termination = true
  }
}

build {
  sources = ["source.amazon-ebs.ecs-batch"]

  # Wait for cloud-init — ALWAYS include this as the first provisioner
  provisioner "shell" {
    inline_shebang = "/bin/sh -ex"
    inline         = ["while [ ! -f /var/lib/cloud/instance/boot-finished ]; do echo 'Waiting for cloud-init...'; sleep 1; done"]
  }

  provisioner "shell" { script = "scripts/01_configure_swap.sh" }
  provisioner "shell" { script = "scripts/02_install_packages.sh" }
  provisioner "shell" { script = "scripts/03_install_awscli_v2.sh" }
  provisioner "shell" { script = "scripts/04_install_miniconda.sh" }
  provisioner "shell" { script = "scripts/05_configure_docker_volume.sh" }
  provisioner "shell" { script = "scripts/06_configure_scratch_disk.sh" }
}
```

## Key Scripts

### `03_install_awscli_v2.sh`
```bash
#!/usr/bin/env bash
set -euxo pipefail
cd /tmp
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf awscliv2.zip aws/

# Nextflow awsbatch executor sets cliPath = '/home/ec2-user/miniconda/bin/aws'
# and mounts that host path into the container — symlink required
mkdir -p /home/ec2-user/miniconda/bin
ln -s /usr/local/bin/aws /home/ec2-user/miniconda/bin/aws
```

### `05_configure_docker_volume.sh`
```bash
#!/usr/bin/env bash
set -euxo pipefail
sudo systemctl stop docker ecs
sudo mkfs -t ext4 /dev/xvdb
sudo mkdir -p /var/lib/docker
sudo mount /dev/xvdb /var/lib/docker
echo '/dev/xvdb /var/lib/docker ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo systemctl start docker ecs
```

### `06_configure_scratch_disk.sh`
```bash
#!/usr/bin/env bash
set -euxo pipefail
sudo mkfs -t ext4 /dev/xvdc
sudo mkdir -p /docker_scratch
sudo mount /dev/xvdc /docker_scratch
echo '/dev/xvdc /docker_scratch ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo chmod 777 /docker_scratch
```

## Build & Deploy

```bash
# Build (run from packer/ecs-batch-ami/)
packer init .
packer validate aws.pkr.hcl
packer build aws.pkr.hcl
# outputs 2 AMI IDs (one per region in ami_regions list)

# If no default VPC in the account:
packer build -var vpc_id=vpc-XXXX -var subnet_id=subnet-XXXX aws.pkr.hcl
```

### Multi-account builds

AMIs are account-specific. For a dev/test/prod account setup, run packer once per account with that account's creds active. With `ami_regions = ["us-west-2", "eu-west-1"]`, each run produces 2 AMIs — 6 total for 3 accounts.

```bash
# Activate dev creds → packer build  → note ami IDs for dev
# Activate test creds → packer build → note ami IDs for test
# Activate prod creds → packer build → note ami IDs for prod
```

### AMI IDs in Terraform

A shared `ecs_ami` default map in `variables.tf` won't work across accounts (each account has different IDs for the same region). Put the override in each env's `terraform.tfvars` instead:

```hcl
# live/non-prod/<account-alias>/us-west-2/dev/batch/terraform.tfvars
ecs_ami = {
  us-west-2 = "ami-XXXXXXXXX"  # built with dev creds
  eu-west-1 = "ami-YYYYYYYYY"
}
```

## Volume Layout

| Device | Mount | Purpose | Default size |
|--------|-------|---------|-------------|
| `/dev/xvda` | `/` | OS + ECS agent | 50 GB |
| `/dev/xvdb` | `/var/lib/docker` | Docker layers/images | 50 GB |
| `/dev/xvdc` | `/docker_scratch` | Pipeline work/scratch | 1.25 TB |

Docker volume only needs ~50 GB when pipeline code correctly redirects reads to the scratch disk. Size it at 200 GB+ only if container writable layers accumulate large data.

## Nextflow / Pipeline Notes

- Nextflow's `awsbatch` executor config sets `cliPath = '/home/ec2-user/miniconda/bin/aws'` — the symlink in `03_install_awscli_v2.sh` makes AWS CLI v2 visible at that path.
- Job definitions should bind-mount `/docker_scratch` into containers as the Nextflow work dir.
- Fix relative paths in pipeline scripts before deploying: `./reads/` → `/data/reads/`, add `-w /data/work` and `-log /data/nextflow.log` to `nextflow run` calls so work artifacts land on the scratch disk, not inside the Docker writable layer.

## Gotchas

- **cloud-init wait**: without the `while [ ! -f /var/lib/cloud/instance/boot-finished ]` loop, provisioner scripts can start before the OS is fully ready and fail intermittently.
- **Stop docker before moving its root**: `05_configure_docker_volume.sh` stops Docker and ECS agent before remounting — if Docker is running when you mount over `/var/lib/docker`, the mount point is hidden and Docker is now writing to the root volume.
- **`nofail` in fstab**: without `nofail`, a missing EBS volume at boot will drop the instance into emergency mode.
