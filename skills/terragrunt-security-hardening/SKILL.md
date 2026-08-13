---
name: terragrunt-security-hardening
description: "Incrementally add security controls — KMS encryption, IAM least-privilege, logging — to an existing multi-environment Terragrunt repo without breaking running workloads."
tags: [terragrunt, security, kms, iam, aws]
---

# Terragrunt Security Hardening

Patterns for incrementally adding security controls to an existing Terragrunt multi-env repo without breaking running workloads.

---

## General Principles

- **Plan before every apply** — security changes are additive but some (KMS encryption, IAM policy changes) cascade to other resources.
- **Branch per sub-task** — branch off master independently for each security sub-task (ECR, KMS, S3, IAM). Keeps PRs small and reviewable.
- **Dev/test before prod** — always apply non-prod account first, verify workloads, then promote to prod.
- **Check existing state before creating new resources** — run `terragrunt state list` on any path you plan to use. Pre-existing state at the same path causes unexpected destroys.

---

## ECR Hardening

### Expose hardcoded module values as variables first

Before adding new inputs to live configs, check if the module has the value hardcoded:

```hcl
# bad — hardcoded in module/ecr/main.tf:
image_tag_mutability = "MUTABLE"

# fix — expose as variable with safe default:
variable "image_tag_mutability" {
  type    = string
  default = "MUTABLE"
  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.image_tag_mutability)
    error_message = "Must be MUTABLE or IMMUTABLE."
  }
}
```

### MUTABLE vs IMMUTABLE decision

| ECR | Setting | Reason |
|-----|---------|--------|
| test | `MUTABLE` | CI/CD pushes `latest` tag frequently for dev iteration |
| prod | `IMMUTABLE` | Prevent accidental overwrites; enforce pinned deploys |

**IMMUTABLE on prod requires CI/CD changes first:**
1. Stop pushing `latest` and env tags (e.g. `dev`, `prod`) to prod ECR
2. Only push unique tags (`v1.0.2`, git SHA) to prod ECR
3. Update `update-function-code` / deployment step to reference version tag, not `latest`

If CI/CD still pushes `latest` to prod ECR, setting `IMMUTABLE` will break every build.

### scan_images_on_push

Safe to enable at any time — scans run async and don't block pushes or deployments. Results appear in ECR console and CloudWatch.

```hcl
# live/non-prod/.../ecr/terragrunt.hcl
inputs = {
  scan_images_on_push  = true
  image_tag_mutability = "MUTABLE"
}
```

---

## KMS Key Module

### Terragrunt default_tags gotcha

The root `terragrunt.hcl` generates `provider.tf` containing `variable "default_tags"`. **Do not declare `default_tags` in your module's `variables.tf`** — Terraform will error with "Duplicate variable declaration".

Remove it from module variables; it arrives automatically via the root `inputs` merge.

### Path naming — avoid state collisions

Before creating a new `security/kms/` live config, check for existing state:

```bash
cd live/<env>/security/kms
terragrunt state list 2>&1
```

If state exists with different resource names, the plan will show unexpected destroys. **Do not overwrite** — use a different path name instead (e.g. `security/kms_s3`).

```
# non-prod account had existing state at security/kms/ for an AMI-sharing key
# new S3 encryption keys live at security/kms_s3/ to avoid collision
```

### Key policy — delegate to IAM

The simplest safe policy grants root `kms:*` and lets IAM policies on roles control access. This avoids having to enumerate Lambda ARNs in the key policy (which creates circular dependencies):

```hcl
policy = jsonencode({
  Version = "2012-10-17"
  Statement = [{
    Sid       = "EnableIAMUserPermissions"
    Effect    = "Allow"
    Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
    Action    = "kms:*"
    Resource  = "*"
  }]
})
```

Lambda/Redshift roles then get `kms:GenerateDataKey` and `kms:Decrypt` via their IAM policies (done in the IAM hardening phase).

### One key per env (not per account)

Even when dev and test share an account, create separate keys per environment:
- `alias/<project>-datalake-dev-s3`
- `alias/<project>-datalake-test-s3`

Provides env-level isolation — a compromised dev key doesn't expose test data.

---

## S3 SSE-KMS Encryption — Impact Analysis

Enabling SSE-KMS on S3 buckets is **not self-contained**. Every service that reads or writes those buckets needs KMS grants or it gets `AccessDenied`.

### Required rollout order

1. **Apply KMS keys** (no impact on running services)
2. **Update IAM roles** — add `kms:GenerateDataKey` + `kms:Decrypt` to:
   - All Lambda execution roles that read/write the bucket
   - Redshift role (if using COPY from S3)
   - CloudFront OAC role (if applicable — see below)
3. **Enable SSE-KMS on S3 buckets** (safe only after step 2)

Skipping step 2 and going to step 3 directly will break Lambda and Redshift access immediately.

### CloudFront + SSE-KMS — critical check

| CloudFront access method | SSE-KMS support |
|--------------------------|-----------------|
| OAI (Origin Access Identity) | **Not supported** — will return 403s |
| OAC (Origin Access Control) | Supported — OAC service principal needs `kms:Decrypt` in key policy |

**Before encrypting any S3 bucket that CloudFront serves from:**
1. Check CloudFront distribution → Origins → confirm OAI or OAC
2. If OAI: must migrate to OAC first (separate task), or exclude that bucket from KMS encryption
3. If OAC: add `kms:Decrypt` grant to the KMS key policy for the CloudFront service principal

Check: AWS Console → CloudFront → your distribution → Origins tab.

### Separate data buckets from frontend buckets

CloudFront-served buckets (static frontend assets) and data pipeline buckets (e.g. raw instrument output, converted results) should be treated separately:
- Data buckets: encrypt with SSE-KMS, no CloudFront concern
- Frontend buckets: encryption decision depends on OAI/OAC setup

Confirm which buckets are which before applying encryption broadly.

---

## IAM Least Privilege — Lambda and Batch

### Replace FullAccess managed policies

Standard replacements for Lambda execution roles:

| Remove | Replace with |
|--------|-------------|
| `AmazonVPCFullAccess` | `AWSLambdaVPCAccessExecutionRole` (includes EC2 ENI lifecycle + CloudWatch logs) |
| `SecretsManagerReadWrite` | `AWSSecretsManagerClientReadOnlyAccess` |
| `AmazonRedshiftFullAccess` | Custom inline policy with `redshift:GetClusterCredentials`, `redshift:DescribeClusters` |
| `AmazonS3FullAccess` | Custom inline policy with `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` |
| `CloudWatchLogsFullAccess` | Already covered by `AWSLambdaVPCAccessExecutionRole`; drop this attachment |

### Batch role pattern

For `aws_batch_ecs_instance_role`: only needs `AmazonEC2ContainerServiceforEC2Role` (already a service role) plus a scoped CloudWatch logs policy.

For `aws_batch_ecs_task_role`: replace all FullAccess attachments with a single custom policy covering `batch:SubmitJob/DescribeJobs/TerminateJob`, minimal ECR pull, scoped S3, and scoped CloudWatch logs.

```hcl
# Batch instance role — minimal additional policy
resource "aws_iam_policy" "batch_instance_minimal" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/batch/*"
    }]
  })
}

# Batch task role — minimal combined policy
resource "aws_iam_policy" "batch_task_minimal" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["batch:SubmitJob", "batch:DescribeJobs", "batch:TerminateJob"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"], Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:*" },
    ]
  })
}
```

### Bulk-update identical Lambda modules via script

When many Lambda modules share the exact same IAM boilerplate, use a Python script rather than editing each file manually:

```python
BASE = "infra/terraform/modules/services/lambda"
OLD_BLOCK = '''data "aws_iam_policy" "redshift_full_access" { ... }'''
NEW_BLOCK = '''data "aws_iam_policy" "lambda_vpc_access_execution" { ... }'''

for module in MODULES:
    path = f"{BASE}/{module}/main.tf"
    content = open(path).read()
    content = content.replace(OLD_BLOCK, NEW_BLOCK)
    content = content.replace('"SecretsManagerReadWrite"', '"AWSSecretsManagerClientReadOnlyAccess"')
    open(path, "w").write(content)
```

Run `git diff --stat` after to verify all expected modules were touched.

### Name scoped custom policies off function_name

When adding new inline policies to Lambda modules without adding new variables to all live configs, use `var.function_name` (always required, no default) for the policy name:

```hcl
resource "aws_iam_policy" "lambda_redshift_policy" {
  name = "${var.function_name}-redshift-policy"
  path = var.path
  ...
}
```

### Trust policy version

Old roles may have `"Version": "2008-10-17"` in the assume_role_policy. Update to `"2012-10-17"` — the 2008 version has restricted condition key support.

---

## Secrets Hygiene — Removing Sensitive Outputs from State

Terraform stores the plaintext value of `sensitive = true` outputs in the state file. If a module decodes and outputs a secret, it lands in the state file unprotected.

### Fix

Remove the output entirely. Services should fetch secrets at runtime via SDK, not receive them as Terraform outputs.

```hcl
# REMOVE from modules/security/secrets_manager/outputs.tf:
output "db_password" {
  value     = jsondecode(data.aws_secretsmanager_secret_version.secret-version.secret_string)["password"]
  sensitive = true   # sensitive = true doesn't protect state; it only masks CLI output
}
```

### Find all callers before removing

```bash
grep -r "secrets_manager.outputs.db_password" infra/terraform/live/ --include="*.hcl" -l
```

Update each caller to remove the dependency block and the input before applying. If a caller is in a prod config and you're doing dev/test first, leave the prod caller in place — it'll continue to work until you apply the module change to prod (at which point both files need updating together).

### After apply — clear cached output from state

```bash
terraform state rm module.secrets_manager.output.db_password
# or re-init if the above doesn't work cleanly
```

---

## VPC Network Security — map_public_ip_on_launch

### Pre-apply check: which VPC handles connectivity?

Before disabling public IPs on any VPC, determine which VPC actually hosts the services you care about. In a multi-VPC setup (comp + db + ingest), Lambdas are typically in the db VPC, not the comp VPC — so missing endpoints in comp only affect Batch EC2 instances, not Lambda.

```bash
# Check all VPCs and their tags to find the right one
aws ec2 describe-vpcs --region us-west-2 \
  --query 'Vpcs[*].{ID:VpcId,CIDR:CidrBlock,Name:Tags[?Key==`Name`].Value|[0]}' \
  --output table

# Then check endpoints per VPC
aws ec2 describe-vpc-endpoints --region us-west-2 \
  --filters "Name=vpc-id,Values=<vpc-id>" \
  --query 'VpcEndpoints[*].{Service:ServiceName,State:State}' \
  --output table
```

### Endpoint requirements by workload

| Workload | VPC | Required endpoints |
|----------|-----|--------------------|
| Lambda (VPC-attached) | db VPC | secretsmanager, s3, redshift |
| Batch EC2 (pulls images, writes logs) | comp VPC | ecr.api, ecr.dkr, logs, s3 |

If a VPC has **no endpoints at all**, do not flip `map_public_ip_on_launch = false` until endpoints are added — all internet-bound traffic will silently fail for new instances (which won't get public IPs).

### Safe if NAT gateway is present

A NAT gateway in the comp VPC provides internet egress — safe to disable public IPs regardless of endpoint coverage, since instances route outbound through NAT. Verify NAT GW presence first:

```bash
aws ec2 describe-nat-gateways --region us-west-2 \
  --filter "Name=vpc-id,Values=<vpc-id>" "Name=state,Values=available" \
  --query 'NatGateways[*].{ID:NatGatewayId,State:State}' --output table
```
