---
name: amplify-storage-browser
description: React web app with AWS Amplify Storage Browser + Cognito + Terragrunt IaC
tags: [react, amplify, s3, cognito, terraform, terragrunt]
---

# AWS Amplify Storage Browser Web App

## Architecture
- React + Vite frontend with `@aws-amplify/ui-react-storage` Storage Browser (v3+, GA Dec 2024)
- Cognito User Pool + Identity Pool for auth (configured manually, NOT Amplify Gen 2)
- AWS Amplify Hosting for CI/CD from GitHub (managed via `aws_amplify_app` Terraform resource)
- Terraform modules + Terragrunt orchestration (multi-account portable)
- S3 bucket with CORS + Lambda event notification

## Key Package Versions
```json
"aws-amplify": "^6.16.0",
"@aws-amplify/ui-react": "^6.0.0",
"@aws-amplify/ui-react-storage": "^3.0.0"
```

## Critical Import Paths (v3.17.2 verified)
The subpath `./storage-browser` does NOT exist in the package exports map — using it throws `TS2307`.

```typescript
// StorageBrowser — root export (pre-built, configured via Amplify.configure())
import { StorageBrowser } from '@aws-amplify/ui-react-storage';

// createStorageBrowser + createAmplifyAuthAdapter — use ./browser subpath
import { createStorageBrowser, createAmplifyAuthAdapter } from '@aws-amplify/ui-react-storage/browser';
```

Package exports map only has three entries: `.`, `./browser`, `./styles.css`.

## Amplify Config (Manual, No Gen 2)

**CRITICAL: StorageBrowser v3 requires BOTH `bucket` (singular) AND `buckets` (plural)**

Two separate internal systems each need a different key — omitting either causes a silent blank screen:

| Key | Used by | Symptom if missing |
|---|---|---|
| `bucket` + `region` (singular) | `createAmplifyAuthAdapter()` guard | throws `MISSING_BUCKET_OR_REGION_ERROR` inside `useRef` → blank screen, no console error surfaced |
| `buckets` (plural) | `listPaths()` location discovery | returns `{ locations: [] }` immediately → browser renders empty, no locations shown |

```typescript
import type { ResourcesConfig } from 'aws-amplify';
export const amplifyConfig: ResourcesConfig = {
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_USER_POOL_ID as string,
      userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID as string,
      identityPoolId: import.meta.env.VITE_IDENTITY_POOL_ID as string,
      loginWith: { email: true },   // Required — without this Authenticator renders wrong field
    },
  },
  Storage: {
    S3: {
      // singular — required by createAmplifyAuthAdapter() guard check
      bucket: import.meta.env.VITE_S3_BUCKET as string,
      region: import.meta.env.VITE_AWS_REGION as string,
      // plural — required by listPaths() for location discovery
      buckets: {
        cometData: {                                              // arbitrary alias key
          bucketName: import.meta.env.VITE_S3_BUCKET as string,
          region: import.meta.env.VITE_AWS_REGION as string,
          paths: {
            '*': {
              // permission values: 'get' | 'list' | 'write' | 'delete' | 'read' (alias for get+list)
              authenticated: ['get', 'list', 'write', 'delete'],
            },
          },
        },
      },
    },
  },
};
```

`paths` keys are glob patterns (`'*'`, `'uploads/*'`, `'{identity_id}/*'`).
Access rule keys: `guest`, `authenticated`, `entityidentity`, or a Cognito group name.
`listPaths()` resolves which paths apply to the current session and returns them as locations.

Call `Amplify.configure(amplifyConfig)` in `main.tsx` BEFORE `ReactDOM.createRoot`.

## App Component Pattern
The pre-built `StorageBrowser` from the root export is configured implicitly via `Amplify.configure()`.
It does NOT accept a `config` prop — passing one throws `TS2322`.

```tsx
import { StorageBrowser } from '@aws-amplify/ui-react-storage';
import { Authenticator } from '@aws-amplify/ui-react';

export default function App() {
  return (
    <Authenticator>
      {() => <StorageBrowser />}
    </Authenticator>
  );
}
```

To use the factory pattern instead (custom actions, fine-grained control):
```tsx
import { createStorageBrowser, createAmplifyAuthAdapter } from '@aws-amplify/ui-react-storage/browser';

const { StorageBrowser } = createStorageBrowser({ config: createAmplifyAuthAdapter() });
```

## amplify.yml (multi-app syntax required when appRoot is set)
```yaml
version: 1
applications:
  - appRoot: web
    frontend:
      phases:
        preBuild:
          commands: [npm ci]
        build:
          commands: [npm run build]
      artifacts:
        baseDirectory: dist
        files: ['**/*']
      cache:
        paths: [node_modules/**/*]
```

## S3 CORS Config (Terraform)
```hcl
cors_rule {
  allowed_headers = ["*"]
  allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
  allowed_origins = ["http://localhost:5173", "https://*.amplifyapp.com"]
  expose_headers  = ["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]
  max_age_seconds = 3000
}
```
`ETag` in `expose_headers` is MANDATORY — without it multipart uploads silently fail.

**Keep `DELETE` in `allowed_methods` even when delete is disabled.** `AbortMultipartUpload`
uses the HTTP DELETE verb for CORS preflight. Removing `DELETE` from CORS breaks browser-initiated
multipart upload cancellation for files >5 MB. CORS is NOT a security boundary — IAM controls
actual delete permission.

## Cognito App Client (Terraform)
- `generate_secret = false` — SPA clients cannot keep secrets
- `explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]` — NO `ALLOW_USER_PASSWORD_AUTH`
- `allowed_oauth_flows_user_pool_client = false` for plain SRP (no hosted UI needed)
- `refresh_token_validity = 7` (days) — 30 days is too long for browser SPAs; 7 is the right balance
- `prevent_user_existence_errors = "ENABLED"` — blocks account enumeration via error messages

## Cognito User Pool Security Hardening (AWS provider v5)
```hcl
resource "aws_cognito_user_pool" "main" {
  deletion_protection = "ACTIVE"   # prevents accidental destroy; set INACTIVE to tear down

  password_policy {
    minimum_length    = 12         # NIST SP 800-63B minimum
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  user_pool_add_ons {
    advanced_security_mode = var.advanced_security_mode  # "AUDIT" | "ENFORCED" | "OFF"
    # AUDIT/ENFORCED require Cognito Advanced Security paid add-on on the account
    # Use "OFF" to avoid plan errors if add-on is not enabled
  }
}
```

## Cognito Identity Pool — provider version notes
`cognito_identity_providers` (plural block) is the **correct form through at least AWS provider v6.39**.
The singular `cognito_identity_provider` is NOT valid — Terraform will error with "Did you mean cognito_identity_providers?".

```hcl
# CORRECT (v5 and v6)
cognito_identity_providers {
  client_id               = aws_cognito_user_pool_client.web.id
  provider_name           = "cognito-idp.${data.aws_region.current.id}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  server_side_token_check = true
}
```

**AWS provider v6 deprecation:** `data.aws_region.current.name` → use `.id` instead (same value, `.name` emits a deprecation warning in v6+).

`server_side_token_check = true` is a HIGH security finding if left false — re-validates tokens
against the User Pool on every STS exchange, closing the revocation bypass window.

## IAM for Identity Pool Authenticated Role

**Upload + download only (no delete):**
```hcl
actions = [
  "s3:GetObject",
  "s3:PutObject",
  "s3:AbortMultipartUpload",
  "s3:ListMultipartUploadParts",
]
```
Omit `s3:DeleteObject` to block deletion at the IAM layer — this is the definitive control.

**Full access (including delete):**
```hcl
# s3:ListBucket on bucket ARN (not /*)
# s3:GetObject, PutObject, DeleteObject, AbortMultipartUpload, ListMultipartUploadParts on bucket_arn/*
```

IAM trust policy must have BOTH conditions to prevent confused-deputy attacks:
- `cognito-identity.amazonaws.com:aud = <identity_pool_id>`
- `cognito-identity.amazonaws.com:amr = "authenticated"`

## Restricting StorageBrowser Actions (No Delete UI)

Use `createStorageBrowser` with a filtered action registry — omitting the `delete` key means
the action is never registered and no delete button is mounted anywhere in the component tree.
This is stronger than CSS hiding.

```tsx
import {
  createStorageBrowser,
  createAmplifyAuthAdapter,
  defaultActionConfigs,
} from '@aws-amplify/ui-react-storage/browser';

const { copy, createFolder, download, upload, listLocationItems } = defaultActionConfigs;

const { StorageBrowser } = createStorageBrowser({
  config: createAmplifyAuthAdapter(),
  actions: {
    default: { copy, createFolder, download, upload, listLocationItems },
    // delete key intentionally omitted
  },
});
```

The amplify-config.ts `paths` permissions should also omit `'delete'` to be consistent:
```typescript
authenticated: ['get', 'list', 'write'],  // no 'delete'
```

## Blocking Self-Signup (Admin-Only User Creation)

Two layers — both required for complete lockdown:

**Cognito (API layer):**
```hcl
resource "aws_cognito_user_pool" "main" {
  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}
```

**React UI layer:**
```tsx
<Authenticator hideSignUp>
  {() => <YourApp />}
</Authenticator>
```

Without `hideSignUp`, the "Create Account" tab still appears even though the API will reject attempts.

## Dynamic Account Name via Terragrunt run_cmd

Hardcoding `VITE_AWS_ACCOUNT_NAME = "Dev"` breaks when deploying to staging/prod.
Use `run_cmd` to resolve the AWS account alias at plan/apply time:

```hcl
# amplify_app/terragrunt.hcl
locals {
  aws_account_name = run_cmd("aws", "iam", "list-account-aliases", "--query", "AccountAliases[0]", "--output", "text")
}

inputs = {
  environment_variables = {
    VITE_AWS_ACCOUNT_NAME = local.aws_account_name
    # ... other vars
  }
}
```

**`VITE_*` vars are compile-time, not runtime.** Amplify environment variables are only injected
during Amplify-managed (CI/CD) builds. For `manual_deploy = true` (local build + upload),
you must also add the value to `web/.env` before running `npm run build`:

```bash
VITE_AWS_ACCOUNT_NAME=dbg-thunderhead-dev   # get via: aws iam list-account-aliases --query 'AccountAliases[0]' --output text
```

Update `.env.example` to document this requirement:
```bash
# Set to the AWS account alias (run: aws iam list-account-aliases --query 'AccountAliases[0]' --output text)
VITE_AWS_ACCOUNT_NAME=
```

## Terragrunt Multi-Module Wiring

**Default order (greenfield):** `s3_data` → `cognito` → `amplify_app`

`cognito` depends on `s3_data` for `bucket_arn`; `amplify_app` depends on both for env vars.
All `dependency` blocks need `mock_outputs` + `mock_outputs_allowed_terraform_commands = ["validate", "plan"]`.

**When the S3 bucket already exists in the account:** Remove `dependency "s3_data"` from
`cognito` and `amplify_app` and supply the bucket ARN/name as literal inputs. This eliminates
the risk of Terraform touching a pre-existing bucket when applying other modules.

```hcl
# cognito/terragrunt.hcl
inputs = {
  bucket_arn = "arn:aws:s3:::my-existing-bucket"
}

# amplify_app/terragrunt.hcl — no dependency "s3_data" block
environment_variables = {
  VITE_S3_BUCKET = "my-existing-bucket"
}
```

Env vars injected into Amplify build via `environment_variables` map on `aws_amplify_app`:
`VITE_USER_POOL_ID`, `VITE_USER_POOL_CLIENT_ID`, `VITE_IDENTITY_POOL_ID`, `VITE_S3_BUCKET`, `VITE_AWS_REGION`

**`force_destroy = true` risk:** The `s3_data` module sets this for dev. Gate it on
`var.environment != "prod"` before any production apply or the bucket can be silently destroyed.

## Two-Pass Apply Required
Amplify domain unknown until after first apply. Apply cognito with localhost callback first, then update with `https://master.<app_id>.amplifyapp.com` after Amplify app is created.

## GitHub Token (CI/CD path)
Store in AWS Secrets Manager. Reference in Terraform:
```hcl
data "aws_secretsmanager_secret_version" "github_token" {
  count     = var.manual_deploy ? 0 : 1
  secret_id = var.github_token_secret_name
}
# use: jsondecode(data.aws_secretsmanager_secret_version.github_token[0].secret_string)["token"]
```
Required PAT scopes: `repo`, `admin:repo_hook`. Amplify needs its own credentials because
builds run in AWS infrastructure, not locally — even when deploying from a local machine.

## Manual Deploy (no GitHub token needed)
For dev/demo environments without a GitHub connection, set `manual_deploy = true` on the
module. The `aws_amplify_app` resource omits `repository`/`oauth_token` and sets
`enable_auto_build = false`.

### TypeScript build prerequisites (missing any causes blank page or 404)

1. **`src/vite-env.d.ts`** — must exist with:
   ```typescript
   /// <reference types="vite/client" />
   ```
   Without this, `import.meta.env` is untyped and all `VITE_*` vars are `undefined` at compile time.

2. **`tsconfig.node.json`** — must have `"composite": true` and must NOT have `"noEmit": true`.
   Without this, `tsc` fails with `TS6306`/`TS6310` and the build never produces `dist/`.

3. **`.env` must be present before `npm run build`** — `VITE_*` vars are baked in at compile time,
   not read at runtime. A build without `.env` produces a bundle with empty config strings.

4. **`VITE_S3_BUCKET` placeholder trap** — `.env.example` uses a fake account ID (`123456789012`).
   Always replace with the real account ID before building.

### Build + zip procedure

```bash
# 1. Fill in .env from Terragrunt outputs (do this first — vars are compile-time)
cp web/.env.example web/.env
# edit web/.env: replace placeholder values with real Cognito/S3/region values

# 2. Clean build (always rm -rf dist first to avoid stale asset hashes in the zip)
cd web && rm -rf dist && npm run build

# 3. Zip from INSIDE dist — NOT from outside
#    Wrong: zip -r dist.zip dist/   ← produces dist/index.html inside zip → Amplify 404
#    Wrong: zip -r deploy.zip .     ← if old deploy.zip exists, stale assets carry over
#    Correct:
rm -f deploy.zip          # delete old zip first — zip updates existing files, never purges
cd dist && zip -r ../deploy.zip index.html assets/

# 4. Verify before uploading
unzip -l ../deploy.zip
# Must see: index.html (non-zero), assets/*.js (non-zero), assets/*.css (non-zero)
# Red flag: assets/ entry with 0 bytes means assets were not captured
```

### Upload via CLI
**`create-deployment` returns BOTH a `jobId` AND a presigned `zipUploadUrl`. You MUST upload
the zip to the presigned URL before calling `start-deployment` — skipping this step results
in a 404 on the deployed app.**

```bash
APP_ID=<amplify_app_id>

# Step 1: create deployment — capture both jobId and presigned upload URL
RESULT=$(aws amplify create-deployment \
         --app-id $APP_ID --branch-name master)
JOB=$(echo $RESULT | jq -r '.jobId')
UPLOAD_URL=$(echo $RESULT | jq -r '.zipUploadUrl')

# Step 2: upload the zip to the presigned URL
curl -T web/deploy.zip "$UPLOAD_URL"

# Step 3: start the deployment
aws amplify start-deployment \
      --app-id $APP_ID --branch-name master --job-id $JOB
```

Use `manual_deploy = false` (default) in prod to restore GitHub-connected CI/CD.

## WAF IP Allowlist for Amplify Hosting

**Scope must be CLOUDFRONT, region must be us-east-1.** This is a hard AWS requirement —
Amplify Hosting uses CloudFront and only accepts CloudFront-scoped WAF ACLs.

### What does NOT work
- `aws_wafv2_web_acl_association` with Amplify app ARN → `WAFInvalidParameterException: The resource is not supported in current region`
- `waf_configuration` block inside `aws_amplify_app` → `Unsupported block type` (not in provider 6.39)

### Terraform pattern — provider alias required

**`terraform/modules/amplify_app/main.tf`** — declare alias, set scope + provider on WAF resources:
```hcl
terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      configuration_aliases = [aws.us_east_1]
    }
  }
}

resource "aws_wafv2_ip_set" "allowed" {
  count    = length(var.allowed_cidr_blocks) > 0 ? 1 : 0
  provider = aws.us_east_1
  scope    = "CLOUDFRONT"
  ...
}

resource "aws_wafv2_web_acl" "amplify" {
  count    = length(var.allowed_cidr_blocks) > 0 ? 1 : 0
  provider = aws.us_east_1
  scope    = "CLOUDFRONT"
  default_action { block {} }
  ...
}
```

**`terraform/live/<env>/amplify_app/terragrunt.hcl`** — generate the alias provider:
```hcl
generate "provider_us_east_1" {
  path      = "provider_us_east_1.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
EOF
}
```

### Association — manual via Amplify console (one-time per account)
Terraform creates the WAF resources but cannot associate them programmatically (provider gap).
After apply:
```bash
cd terraform/live/dev/amplify_app && terragrunt output waf_web_acl_arn
```
Then: **Amplify console → app → Firewall → Associate Web ACL → paste ARN**

CIDR updates only need `terragrunt apply` — no re-association needed.

### Preserve existing AWS managed rules on import
When importing an existing Amplify-console-created WAF ACL, the console automatically adds
three AWS managed rule groups. Terraform will plan to DELETE them unless they are explicitly
defined in the module. Always add these rules before applying after an import:

```hcl
rule {
  name     = "AWS-AWSManagedRulesAmazonIpReputationList"
  priority = 0
  override_action {
    none {}
  }
  statement {
    managed_rule_group_statement {
      name        = "AWSManagedRulesAmazonIpReputationList"
      vendor_name = "AWS"
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "AWS-AWSManagedRulesAmazonIpReputationList"
    sampled_requests_enabled   = true
  }
}
# Repeat pattern for AWSManagedRulesCommonRuleSet (priority 1)
# and AWSManagedRulesKnownBadInputsRuleSet (priority 2)
```

Put `AllowListedIPs` at priority 3 (after managed rules).

**HCL syntax note:** `override_action { none {} }` must be multi-line — single-line nested
empty blocks cause `Argument definition required` parse errors.

### WAFDuplicateItemException on apply
If a WAF ACL with the same name already exists in us-east-1 (from a prior apply or manual
creation), import it rather than recreating:
```bash
# 1. Find the existing ACL ID
aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 \
  --query 'WebACLs[?Name==`<name>`]'

# 2. Import into Terraform state
terragrunt import 'aws_wafv2_web_acl.amplify[0]' '<Id>/<name>/CLOUDFRONT'
```

### S3 bucket IP restriction — do NOT use when Lambda trigger is active
An S3 bucket policy with `NotIpAddress + aws:SourceIp` will also block Lambda (AWS service
calls have no source IP). If an IP restriction is needed on S3, add a second Allow statement
exempting the Lambda execution role ARN.

## SPA Rewrite Rule
```hcl
custom_rule {
  source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json)$)([^.]+$)/>"
  target = "/index.html"
  status = "200"
}
```

## Lambda Infinite-Loop Guard (when S3 triggers Lambda)
Check path component [2] specifically, not substring of whole key:
```python
key_parts = key.split("/")
if len(key_parts) > 2 and key_parts[2] == "flowjo_processed":
    return {'Success': True, 'Skipped': True, 'Key': key}
```
