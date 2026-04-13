---
name: terragrunt-project-setup
description: Multi-module Terraform + Terragrunt project structure, remote state bootstrap, dependency wiring, and multi-account patterns
tags: [terragrunt, terraform, aws, infrastructure, iac]
---

# Skill: Terragrunt Multi-Module Project Setup

**When to use:** Setting up a new Terraform + Terragrunt project with multiple modules that need to share outputs, support multiple AWS accounts, and bootstrap remote state.

---

## Directory structure

```
terraform/
  modules/
    module_a/          # Reusable, account-agnostic
      main.tf
      variables.tf
      outputs.tf
    module_b/
      main.tf
      variables.tf
      outputs.tf
  live/
    dev/               # One folder per environment/account
      root.hcl         # Root config: remote state + provider generation (NOT terragrunt.hcl)
      module_a/
        terragrunt.hcl # include root + inputs + dependency refs
      module_b/
        terragrunt.hcl
    staging/           # Second account: copy live/dev, change inputs
      root.hcl
      ...
```

---

## Root `live/{env}/root.hcl`

```hcl
locals {
  aws_region   = "us-east-1"
  environment  = "dev"
  project_name = "my-project"
}

remote_state {
  backend = "s3"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }
  config = {
    bucket         = "my-tf-state-${get_aws_account_id()}"
    key            = "${path_relative_to_include()}/terraform.tfstate"
    region         = local.aws_region
    encrypt        = true
    dynamodb_table = "my-tf-locks"
  }
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "${local.aws_region}"
}
EOF
}
```

Key rules:
- Never add `provider {}` or `backend {}` blocks inside module `.tf` files — Terragrunt generates these
- Use `get_aws_account_id()` in the state bucket name for automatic account isolation
- `path_relative_to_include()` gives each module a unique state key

---

## Module `live/{env}/module_b/terragrunt.hcl`

```hcl
include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../modules/module_b"
}

dependency "module_a" {
  config_path = "../module_a"

  # mock_outputs prevent errors when module_a hasn't been applied yet
  mock_outputs = {
    output_value = "mock-value"
  }
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
}

inputs = {
  some_input  = dependency.module_a.outputs.output_value
  environment = "dev"
}
```

---

## Module files — what goes where

| File | Contains |
|------|----------|
| `modules/x/variables.tf` | All `variable` blocks with type + description |
| `modules/x/main.tf` | All `resource` and `data` blocks |
| `modules/x/outputs.tf` | All `output` blocks |
| `live/dev/root.hcl` | Remote state config, provider generation, shared locals |
| `live/dev/x/terragrunt.hcl` | `include`, `terraform.source`, `dependency` blocks, `inputs` |

---

## State bootstrap (one-time per account)

**Name the state bucket after the project**, not just the account — multiple projects may share an account and generic names collide:

```hcl
bucket = "${local.project_name}-tf-state-${get_aws_account_id()}"
```

Create it before the first `terragrunt init` (no DynamoDB needed with Terraform >= 1.10 S3 native locking):

```bash
aws s3 mb s3://myproject-tf-state-$(aws sts get-caller-identity --query Account --output text) \
  --region us-west-2
```

For older Terraform (< 1.10), add DynamoDB for locking:
```bash
aws dynamodb create-table \
  --table-name myproject-tf-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-west-2
```

These are NOT managed by this Terraform code — they're a prerequisite.

---

## Apply order

```bash
# Always plan first — review output before applying
cd terraform/live/dev/module_a && terragrunt plan && terragrunt apply
cd terraform/live/dev/module_b && terragrunt plan && terragrunt apply

# Or plan all at once, then apply
cd terraform/live/dev
terragrunt run-all plan
terragrunt run-all apply
```

**Never skip the plan step.** Applying without reviewing the plan can destroy or replace live infrastructure without warning.

---

## Multi-account deployment

Add `terraform/live/staging/` with its own root `terragrunt.hcl`:
- Change `aws_region`, `environment` locals
- Update `inputs` blocks with account-specific values (ARNs, bucket names, etc.)
- Modules themselves need zero changes — they're account-agnostic by design

---

## Secrets in Terraform

Never hardcode tokens or credentials. Reference from AWS Secrets Manager:

```hcl
data "aws_secretsmanager_secret_version" "token" {
  secret_id = var.secret_name
}

# Use: jsondecode(data.aws_secretsmanager_secret_version.token.secret_string)["key"]
```

Pass `var.secret_name` from the Terragrunt `inputs` block.

---

## Optional resources pattern (feature flags)

Use a boolean variable + `count` to make resource groups optional without separate modules:

```hcl
# variables.tf
variable "create_lambda_trigger" {
  type    = bool
  default = false
}

# main.tf
resource "aws_lambda_permission" "allow_s3" {
  count         = var.create_lambda_trigger ? 1 : 0
  function_name = var.lambda_function_name
  ...
}
```

Key rules:
- References to counted resources from *other* resources need `[0]`: `aws_lambda_permission.allow_s3[0].arn`
- `depends_on` accepts the list form without index
- Add `validation` blocks gated on the feature flag so missing required vars fail at **plan** time, not apply

---

## Provider version pinning

```hcl
required_providers {
  aws = {
    source  = "hashicorp/aws"
    version = "~> 6.0"   # explicit — allows 6.x, blocks 7.x
  }
}
```

---

## Root config naming convention (Terragrunt >= v0.67)

**Do not name the root config `terragrunt.hcl`.** Use `root.hcl` instead — `terragrunt.hcl` as root is an anti-pattern and will become a hard error in a future version.

When using a non-default filename, child modules must explicitly name it:

```hcl
include "root" {
  path = find_in_parent_folders("root.hcl")   # explicit filename required
}
```

### Migration from `terragrunt.hcl` to `root.hcl`

```bash
cp terraform/live/dev/terragrunt.hcl terraform/live/dev/root.hcl
# Update every child module's include block:
#   path = find_in_parent_folders()  →  path = find_in_parent_folders("root.hcl")
git rm terraform/live/dev/terragrunt.hcl
cd terraform/live/dev/module_a && terragrunt plan   # verify zero warnings
```

---

## Common gotchas

- `mock_outputs` must match the real output types — a mock string for an ARN output, not `null`
- `mock_outputs_allowed_terraform_commands = ["validate", "plan"]` — do NOT include `"apply"`
- `find_in_parent_folders()` with no argument looks for `terragrunt.hcl` — if root config is named `root.hcl`, pass the filename explicitly
- Circular dependency (e.g., Amplify needs Cognito callback URL, Cognito needs Amplify domain): resolve with two-pass apply
- `force_destroy = true` on S3 buckets should be gated: `force_destroy = var.environment == "dev"`
