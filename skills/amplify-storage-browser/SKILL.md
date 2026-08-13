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
        primaryData: {                                              // arbitrary alias key
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
  expose_headers = [
    "ETag",
    "x-amz-server-side-encryption",
    "x-amz-request-id",
    "x-amz-id-2",
    "x-amz-storage-class",
  ]
  max_age_seconds = 3000
}
```
`ETag` in `expose_headers` is MANDATORY — without it multipart uploads silently fail.

**`x-amz-storage-class` MUST be in `expose_headers`** or `HeadObjectCommand.StorageClass` is always
`undefined` in browser JS. The browser's CORS filter strips response headers not listed here before
the AWS SDK sees them. Symptom: every file shows "Standard" even when the bucket uses Glacier or
Intelligent-Tiering. Fix: add `x-amz-storage-class` to `expose_headers` and `terragrunt apply` the
CORS change — no code change needed, purely Terraform.

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

**Omitting `delete` from `actions.default` is NOT enough.** Amplify's bundle internally merges
`defaultActionConfigs` first and then overlays `actions.default`. If the `delete` key is absent
from your overlay, the built-in default survives the merge and the Delete button reappears.

**Correct fix — override `delete` with `hide: () => true`:**
```tsx
import {
  createStorageBrowser,
  createAmplifyAuthAdapter,
  defaultActionConfigs,
} from '@aws-amplify/ui-react-storage/browser';

const {
  copy, createFolder, download, upload, listLocationItems,
  delete: deleteConfig,  // must destructure to reference it
} = defaultActionConfigs;

const { StorageBrowser } = createStorageBrowser({
  config: createAmplifyAuthAdapter(),
  actions: {
    default: {
      copy, createFolder, download, upload, listLocationItems,
      delete: { ...deleteConfig, actionListItem: { ...deleteConfig.actionListItem, hide: () => true } },
    },
  },
});
```

This keeps the key in the registry (preventing the default from taking over) while hiding it from
the action list entirely. The amplify-config.ts `paths` permissions should also omit `'delete'`:
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
VITE_AWS_ACCOUNT_NAME=<your-account-alias>   # get via: aws iam list-account-aliases --query 'AccountAliases[0]' --output text
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
#
#    *** REQUIREMENT: index.html MUST be at the ROOT of the zip ***
#    Amplify serves index.html from the archive root. If it is nested inside
#    a dist/ subdirectory the app returns 404 on every route.
#
#    Wrong: zip -r deploy.zip dist/   ← produces dist/index.html → 404
#    Wrong: zip -r deploy.zip .       ← if old deploy.zip exists, stale assets carry over
#    Correct: cd INTO dist first, then zip
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

## Custom Actions (createStorageBrowser)

### ActionViewConfig shape
```tsx
export const myActionConfig = {
  handler: (_input: unknown) => ({ result: Promise.resolve({ status: 'COMPLETE' as const }) }),
  viewName: 'MyActionView' as const,   // must end in "View"
  actionListItem: {
    icon: 'copy-file' as any,          // Amplify icon name or any string
    label: 'My Action',
    disable: (selectedValues: Array<{ type?: string }> | undefined) => {
      if (!selectedValues?.length) return true;
      return selectedValues.some(v => v.type === 'FOLDER');  // example: files only
    },
  },
} as const;
```

### View factory pattern (REQUIRED)
Views must be **factory functions** that close over the `useView` hook returned from
`createStorageBrowser`. Construct them after `createStorageBrowser` returns:

```tsx
const { StorageBrowser, useView } = createStorageBrowser({ config, actions });

// factories receive useView — construct AFTER createStorageBrowser
const MyView = createMyView(useView);

// pass views by name — key must match viewName in config (drop "View" suffix)
<StorageBrowser views={{ MyView }} />
```

### CRITICAL: How to read selection state
**Never use module-scope state to pass data from handler to view.** The handler runs
when the user clicks the action-list item, AFTER the view has already mounted. Any module-scope
variable written in the handler is empty when `useState(() => _var)` initializes.

**Correct pattern — read from `useView('LocationDetail').dataItems`:**
```tsx
export function createMyView(
  useView: <K extends 'LocationDetail'>(type: K) => {
    dataItems?: LocationItemData[];
    onActionExit: () => void;
  },
) {
  return function MyView() {
    const { dataItems, onActionExit } = useView('LocationDetail');
    const selectedFile = (dataItems ?? []).find(item => item.type === 'FILE');
    // ... use selectedFile, call onActionExit() to return to browser
  };
}
```

### No-op handler (standard for view-driven actions)
```tsx
export const myHandler = (_input: unknown) => ({
  result: Promise.resolve({ status: 'COMPLETE' as const }),
});
```

### Registering custom actions (and removing built-ins)
```tsx
const { copy, createFolder, download, upload, listLocationItems } = defaultActionConfigs;

const { StorageBrowser, useView } = createStorageBrowser({
  config: createAmplifyAuthAdapter(),
  actions: {
    default: { createFolder, download, upload, listLocationItems }, // omit `copy` to replace it
    custom: {
      copyS3Uri: copyS3UriActionConfig,
      copyFile: copyFileActionConfig,       // custom copy with FolderPicker
      downloadFolder: downloadFolderActionConfig,
      moveFile: moveFileActionConfig,
      renameFile: renameFileActionConfig,
    },
  },
});
```

### Reading bucket name in a view
`useView('LocationDetail')` does NOT expose `config.bucket`. Use the Vite env var:
```tsx
const bucket = import.meta.env.VITE_S3_BUCKET as string ?? '';
const uri = selectedFile ? `s3://${bucket}/${selectedFile.key}` : '';
```

### IAM for Move and Rename
Move (copy + delete source) and Rename require `s3:DeleteObject` in the Cognito Identity
Pool IAM role. The built-in `download` action does not need it.
```hcl
actions = [
  "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
  "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts",
]
```

---

## FolderPicker Component

Reusable navigable S3 folder picker; extract to `src/actions/FolderPicker.tsx` so both
Move and Copy views can import it.

**Key design decisions:**
- `list({ path: browsePath, options: { listAll: false, pageSize: 1000 } })` — one level only
- Extract unique immediate subfolder prefixes by finding the first `/` in each relative path
- `disabledPaths` prop greys out source dirs (so user can't move a file to where it already is)
- `navigateTo(path)` updates `browsePath` AND calls `onSelect(path)` — so navigating into a
  folder also selects it as the current destination
- `selectFolder(path)` selects without navigating (single-click on row)
- "Select current location" footer button picks the level currently being browsed

```tsx
export interface FolderPickerProps {
  onSelect: (path: string) => void;
  disabledPaths?: string[];
}

export function FolderPicker({ onSelect, disabledPaths = [] }: FolderPickerProps) {
  const [browsePath, setBrowsePath] = useState('');
  const [folders, setFolders] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setLoadError(''); setFolders([]);
    list({ path: browsePath, options: { listAll: false, pageSize: 1000 } })
      .then(result => {
        if (cancelled) return;
        const folderSet = new Set<string>();
        for (const item of result.items) {
          const relative = item.path.slice(browsePath.length);
          const slashIdx = relative.indexOf('/');
          if (slashIdx !== -1) folderSet.add(browsePath + relative.slice(0, slashIdx + 1));
        }
        setFolders(Array.from(folderSet).sort());
      })
      .catch(err => { if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Failed.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [browsePath]);

  const navigateTo = (path: string) => { setBrowsePath(path); setSelected(null); onSelect(path); };
  const selectFolder = (path: string) => { setSelected(path); onSelect(path); };

  const segments = browsePath ? browsePath.slice(0, -1).split('/').filter(Boolean) : [];
  const breadcrumbPath = (i: number) => segments.slice(0, i + 1).join('/') + '/';
  // render: breadcrumb, folder list (with Open button + disabled dimming), Select current location footer
}
```

---

## Copy File Custom Action (replacing built-in copy)

The built-in `copy` action does not have a FolderPicker or a named "Remove from list" column.
Replace it with a custom `copyFile` action that adds these UX features.

```tsx
// App.tsx — omit `copy` from default, add copyFile to custom
const { createFolder, download, upload, listLocationItems } = defaultActionConfigs;
const { StorageBrowser, useView } = createStorageBrowser({
  actions: {
    default: { createFolder, download, upload, listLocationItems },
    custom: { copyFile: copyFileActionConfig },
  },
});
```

View pattern:
- Maintain local `fileList` state (`useState(() => allFiles)`) so users can remove items
- Show table with **"Remove from list"** column header (the built-in has a headerless red X)
- Show `FolderPicker` for destination; same-source-dir guard before copying
- Cancel button (`onActionExit`) is always active — never disabled

---

## Amplify `dataItems` Duplicate Key Problem

**Symptom:** Move or any action that snapshots `dataItems` on mount shows duplicate file rows, even
when the user only selected each file once.

**Root cause:** Amplify calls `crypto.randomUUID()` in `parseItems` on every listing parse. The same
S3 object gets a **different `id`** each time the listing is refreshed or `selectedIds` changes.
When a listing refreshes after selection, the old `id` is no longer in `selectedIds`, so the file
appears unchecked. If the user then re-selects it, Amplify adds a second entry with the same `key`
but a new `id`. The `dataItems` array now contains two entries for the same S3 file.

**Fix: key-based dedup in the `useState` snapshot initializer:**
```tsx
const [selectedFiles] = useState<Extract<LocationItemData, { type: 'FILE' }>[]>(() => {
  const seen = new Set<string>();
  return (dataItems ?? []).filter(
    (item): item is Extract<LocationItemData, { type: 'FILE' }> => {
      if (item.type !== 'FILE') return false;
      if (seen.has(item.key)) return false;
      seen.add(item.key);
      return true;
    },
  );
});
```

Always use key-based dedup (not id-based) for any snapshot that captures selected files from
`dataItems` — ids are not stable across renders.

---

## Move File Custom Action

Same pattern as Copy + delete the source key after copy succeeds.

**Distinguish copy-then-delete errors with separate try-catch blocks:**
```tsx
let copySucceeded = false;
try {
  await copy({ source: { path: sourceKey }, destination: { path: destKey } });
  copySucceeded = true;
  await remove({ path: sourceKey });
  newResults.push({ key: sourceKey, ok: true });
} catch (err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  newResults.push({
    key: sourceKey, ok: false,
    error: copySucceeded ? `Copied but source delete failed: ${message}` : message,
  });
}
```

**Gotcha — `remove()` fails in non-Amplify-auth apps (e.g. Azure AD):** Amplify's `remove()` resolves the bucket through its own auth layer. If the app authenticates via Azure AD (Cognito federated identity) rather than a native Amplify `signIn()` flow, `remove()` throws `"bucket resolution error"` because Amplify has no credentials. Fix: use `DeleteObjectCommand` directly with the Cognito credentials from `fetchAuthSession`:

```tsx
import { DeleteObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { fetchAuthSession } from 'aws-amplify/auth';

const session = await fetchAuthSession();
const creds = session.credentials!;
const s3 = new S3Client({ region: REGION, credentials: creds });
await s3.send(new DeleteObjectCommand({ Bucket: BUCKET, Key: sourceKey }));
```

This applies to Move and Rename (both require deleting the source key).

---

## Download Folder as Zip Custom Action

- Requires exactly one FOLDER selected: `disable: sv => sv?.length !== 1 || sv[0].type !== 'FOLDER'`
- Read `selectedFolder` from `dataItems` (NOT from module-scope state)
- `list({ path: folderKey, options: { listAll: true } })` — recursive
- Filter out folder-placeholder objects: `items.filter(item => !item.path.endsWith('/'))`
- `getUrl({ path, options: { expiresIn: 300 } })` → `.url.toString()` before `fetch()`
- JSZip v3: `zip.folder(folderName)!.file(relPath, buffer)` → `zip.generateAsync({ type: 'blob' })`
- Trigger download via temporary anchor: `a.href = objectUrl; a.download = 'name.zip'; a.click()`
- Zip named after the S3 folder: `rawKey.split('/').filter(Boolean).pop() ?? 'folder'`

---

## File Details Pane Scrolling

### Root cause (multi-layer)

The StorageBrowser CSS structure is a flex column:

```
<main> (flex:1; overflow:hidden)
  .amplify-storage-browser (flex-direction:column; height:100%; padding:small; gap:small)
    [toolbar / breadcrumbs]
    .amplify-storage-browser__content-with-preview (display:flex; height:100%)
      [file table]
      .amplify-storage-browser__file-preview (flex:1; width:50%; position:sticky; height:fit-content)
        .amplify-storage-browser__file-preview-section (flex:1; min-height:400px)
          .amplify-storage-browser__file-metadata (key-value rows)
```

**Problem 1 — overshooting container:** `content-with-preview` uses `height:100%` of
`.amplify-storage-browser`, but the parent also has a toolbar + padding/gap consuming space.
`height:100%` means 100% of the parent's height (not remaining space), so the row overflows
`.amplify-storage-browser`, overflows `<main>`'s `overflow:hidden`, and the bottom of the
preview (including any scrollbar) is clipped invisibly. Symptom: making the window taller
reveals more rows — they were there all along, just clipped.

**Problem 2 — `flex:1` width ignored:** The pane has `flex:1` from Amplify. Setting only
`width:28%` doesn't work in a flex context — `flex:1` expands the item regardless.
Must use `flex:0 0 28%` to truly pin the width.

**Problem 3 — `min-height:400px` on inner section:** pushes the metadata table far down
before any content appears.

**Problem 4 — `position:sticky` inside `overflow:hidden`:** sticky becomes position:relative
(browser spec). Harmless but confusing — set `position:relative` explicitly.

### Complete working fix (`src/index.css`)

```css
/* Fix 1: use flex:1 + min-height:0 so the row takes remaining space after
   the toolbar instead of overshooting the parent with height:100%. */
.amplify-storage-browser__content-with-preview {
  flex: 1 !important;
  height: auto !important;
  min-height: 0 !important;
}

/* Fix 2: pin width with flex shorthand; fill bounded row height; scroll inside. */
.amplify-storage-browser__file-preview {
  flex: 0 0 28% !important;
  width: 28% !important;
  max-width: 28% !important;
  height: 100% !important;
  min-height: 0 !important;
  overflow-y: auto !important;
  position: relative !important;
  font-size: 0.78rem !important;   /* more rows visible without scrolling */
}

/* Fix 3: remove 400px min-height that buries metadata below the fold. */
.amplify-storage-browser__file-preview-section {
  min-height: unset !important;
}

/* Stack metadata key/value pairs vertically — long paths/timestamps wrap cleanly. */
.amplify-storage-browser__file-metadata-item {
  flex-direction: column !important;
  align-items: flex-start !important;
  gap: 0.15rem !important;
}
.amplify-storage-browser__file-metadata-value {
  max-width: 100% !important;
  text-align: start !important;
}
```

### Diagnosis checklist
- Content visible when window is taller → clipped by parent `overflow:hidden`, not a scroll issue
- `width` override has no effect → need `flex:0 0 N%` not just `width`
- Scrollbar appears but can't reach bottom → pane overflows parent, bottom is clipped
- `overflow-y:auto` on pane but no scroll → content isn't overflowing the pane (inner flex children stretch instead of overflow); add `min-height:0` on the scroll container and its flex ancestors

---

---

## S3 Key Name Validation

Create `src/utils/s3Validation.ts` for a shared validation utility used by Rename, Copy, and Move.

**Hard errors (block submit):**
- Contains `/` or `\`
- Contains control characters `\x00–\x1F` or `\x7F`
- Contains `%` — causes double-encoding in presigned URLs
- Exceeds 255 bytes (UTF-8 encoded)

**Soft warnings (show in amber, allow submit):**
- Leading or trailing spaces (AWS Console strips them on display)
- Starts with `.` (treated as hidden by Unix tools)
- Contains emoji or non-ASCII characters (stored correctly in S3 but some CLI tools have display issues)

```typescript
export function validateS3Name(name: string): { errors: string[]; warnings: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];
  const trimmed = name.trim();
  if (!trimmed) { errors.push('File name cannot be empty.'); return { errors, warnings }; }
  if (trimmed.includes('/')) errors.push('Must not contain "/".');
  if (trimmed.includes('\\')) errors.push('Must not contain "\\".');
  if (/[\x00-\x1F\x7F]/.test(trimmed)) errors.push('Must not contain control characters.');
  if (trimmed.includes('%')) errors.push('Must not contain "%" — breaks presigned URL encoding.');
  const bytes = new TextEncoder().encode(trimmed).length;
  if (bytes > 255) errors.push(`Too long (${bytes} bytes, max 255).`);
  if (name !== trimmed) warnings.push('Has leading/trailing spaces.');
  if (trimmed.startsWith('.')) warnings.push('Starts with "." — hidden file.');
  if (/[^\x00-\x7E]/.test(trimmed)) warnings.push('Contains emoji/non-ASCII.');
  return { errors, warnings };
}
```

Show errors in red, warnings in amber. Border of input turns red/amber. Submit disabled while `errors.length > 0`.

---

## Large File Guard (>5 GB) for Copy/Move

S3 `CopyObject` API (which Amplify `copy()` maps to) has a hard 5 GB limit. Files above it fail with a cryptic AWS error. Pre-flight before executing:

```typescript
export const S3_COPY_MAX_BYTES = 5 * 1024 ** 3;

// In FileItem type — size is present on Amplify's real FileData but often excluded from local aliases
type FileItem = { key: string; id: string; type: 'FILE'; size?: number };

// Before calling copy():
const oversized = filesToCopy.filter(f => (f.size ?? 0) >= S3_COPY_MAX_BYTES);
if (oversized.length > 0) {
  setOversizedFiles(oversized.map(f => ({ key: f.key, size: f.size ?? 0 })));
  setStatus('sizeWarning');
  return;
}
```

Warning panel shows oversized files with human-readable sizes + CLI hint:
```
aws s3 cp s3://SOURCE_BUCKET/path s3://DEST_BUCKET/path
```
If batch has mixed sizes, show "Copy N other files" button to proceed with just the small ones.

---

## Cancel Button for Long Async Operations (AbortController pattern)

For operations with loops + fetch calls (e.g. Download Folder):

```typescript
const cancelledRef = useRef(false);
const controllerRef = useRef<AbortController | null>(null);

const handleCancel = () => {
  cancelledRef.current = true;
  controllerRef.current?.abort();
  setPhase('confirm');  // return to the start screen — don't show error
  setProgress('');
};

const handleDownload = async () => {
  cancelledRef.current = false;
  const controller = new AbortController();
  controllerRef.current = controller;

  for (const file of files) {
    if (cancelledRef.current) return;   // check before each item
    let response: Response;
    try {
      response = await fetch(url, { signal: controller.signal });
    } catch (fetchErr) {
      if (fetchErr instanceof Error && fetchErr.name === 'AbortError') return;  // silent cancel
      throw fetchErr;
    }
    if (cancelledRef.current) return;   // check after each fetch
    // ... process response
  }
};
```

Show Cancel button alongside progress text during all working phases (`listing`, `downloading`, `zipping`).
On `AbortError`, return silently — don't surface an error panel.

---

## Multi-Bucket Support (Cross-Bucket Copy/Move)

### amplify-config.ts

Parse `VITE_S3_EXTRA_BUCKETS` (JSON array) and merge into the Amplify `buckets` config:

```
VITE_S3_EXTRA_BUCKETS=[{"alias":"secondaryData","bucketName":"my-bucket","region":"us-west-2","label":"Secondary Data"}]
```

```typescript
const extraBuckets = parseExtraBuckets();  // validate and parse JSON

const bucketsMap = {
  primaryData: { bucketName: VITE_S3_BUCKET, region: VITE_AWS_REGION, paths: { '*': { authenticated: [...] } } },
  ...Object.fromEntries(extraBuckets.map(b => [b.alias, { bucketName: b.bucketName, region: b.region, paths: {...} }]))
};

// Export for use in UI components:
export const availableBuckets: Array<{ alias: string; label: string }> = [
  { alias: 'primaryData', label: 'Primary Bucket' },
  ...extraBuckets.map(b => ({ alias: b.alias, label: b.label })),
];
```

### FolderPicker bucket selector

Add optional props to `FolderPicker`:
```typescript
interface FolderPickerProps {
  onSelect: (path: string, bucketAlias?: string) => void;
  disabledPaths?: string[];
  availableBuckets?: Array<{ alias: string; label: string }>;
  initialBucket?: string;
}
```

When `availableBuckets.length > 1`, render a `<select>` dropdown above the breadcrumb. Switching buckets resets `browsePath` to `''` and reloads folders.

Pass bucket to `list()`:
```typescript
list({ path: browsePath, options: { listAll: false, pageSize: 1000, ...(selectedBucket ? { bucket: selectedBucket } : {}) } as any })
// Note: Amplify's list() options type is a union — cast as any to pass bucket dynamically
```

### Cross-bucket copy

```typescript
const destOptions = destBucket ? { bucket: destBucket as any } : undefined;
await copy({
  source: { path: sourceKey },
  destination: destOptions ? { path: destKey, ...destOptions } : { path: destKey },
});
```

---

## Lifecycle / Storage Info Action

Uses `@aws-sdk/client-s3` directly (install separately — NOT bundled with `@aws-amplify/ui-react-storage`):
```bash
npm install @aws-sdk/client-s3
```

Get Cognito credentials for S3 client:
```typescript
import { fetchAuthSession } from 'aws-amplify/auth';
import { S3Client, HeadObjectCommand, GetBucketLifecycleConfigurationCommand } from '@aws-sdk/client-s3';

const session = await fetchAuthSession();
const creds = session.credentials!;
const s3 = new S3Client({
  region,
  credentials: {
    accessKeyId: creds.accessKeyId,
    secretAccessKey: creds.secretAccessKey,
    sessionToken: creds.sessionToken,
  },
});
```

**HeadObject** → `StorageClass` (`STANDARD`, `INTELLIGENT_TIERING`, `GLACIER`, etc.)

**GetBucketLifecycleConfiguration** → match rules to object key, compute transition countdowns:
```typescript
function ruleMatchesKey(rule: LifecycleRule, key: string): boolean {
  const prefix = rule.Filter?.Prefix ?? rule.Filter?.And?.Prefix ?? '';
  return key.startsWith(prefix);
}

// For Transition rules with Days:
const transitionDate = new Date(lastModified.getTime() + rule.Days * 86400_000);
const daysRemaining = Math.ceil((transitionDate.getTime() - Date.now()) / 86400_000);
```

Handle `NoSuchLifecycleConfiguration` gracefully (bucket has no rules — not an error):
```typescript
try {
  const resp = await s3.send(new GetBucketLifecycleConfigurationCommand({ Bucket: bucket }));
  rules = resp.Rules ?? [];
} catch (err) {
  if ((err as { name?: string }).name !== 'NoSuchLifecycleConfiguration') throw err;
}
```

**S3 Intelligent-Tiering note:** transitions are access-pattern based — no fixed date. Show a dedicated info box explaining the tiers (30-day Infrequent Access, 90-day Archive, 180-day Deep Archive) rather than a countdown.

**IAM change required** (bucket-level, not object-level):
```hcl
statement {
  sid       = "BucketMetadata"
  effect    = "Allow"
  actions   = ["s3:GetLifecycleConfiguration"]   # IAM name for GetBucketLifecycleConfiguration
  resources = [var.bucket_arn]                    # bucket ARN, NOT bucket_arn/*
}
```

**Bucket vs. object ARN scope:** `s3:ListBucket` and `s3:GetLifecycleConfiguration` apply to the bucket ARN. `s3:GetObject`, `s3:PutObject`, etc. apply to `${bucket_arn}/*`. Mixing these up causes AccessDenied.

---

## Custom LocationDetailView — Row Selection + File Preview

### `onSelect` argument trap (critical gotcha)

Amplify's state machine toggles selection **internally**. `onSelect` expects the **current** `isSelected`
state — NOT the toggled value. Passing `!isSelected` makes every click a no-op:

```
Not selected (isSelected=false) + onSelect(!false=true) → machine sees "currently selected" → deselects → no change
Selected (isSelected=true) + onSelect(!true=false)       → machine sees "currently not selected" → selects → no change
```

**Correct pattern (matches Amplify's own table implementation):**
```tsx
// WRONG — looks right but is inverted:
onChange={() => onSelect(!isSelected, item)}

// CORRECT:
onChange={() => onSelect(isSelected, item)}
```

This applies to both checkbox `onChange` AND row `onClick` handlers.

### File row click: selection vs. preview are separate callbacks

Amplify's native table uses **two different functions** for file click vs. checkbox:

| Interaction | Amplify internal call | Effect |
|---|---|---|
| Checkbox toggle | `onSelect(isSelected, item)` | Toggles selection; updates `dataItems`; enables ActionsList |
| File name click | `onSelectActiveFile(item)` | Activates file preview panel |

A custom table row's `onClick` must call **both** to restore full native behavior:

```tsx
// In LocationDetailState interface:
onSelectActiveFile: (item: LocationItemData) => void;

// Destructure from state:
const { onSelect, onSelectActiveFile, ... } = state;

// Row onClick:
onClick={isFile ? () => { onSelect(isSelected, item); onSelectActiveFile(item); } : undefined}

// Checkbox onChange:
onChange={() => onSelect(isSelected, item)}

// Checkbox td — stopPropagation prevents double-toggle on row click:
<td onClick={e => e.stopPropagation()}>
```

### Inline lifecycle transition hints in custom table

Fetch lifecycle rules once per bucket at module scope, then show transition countdown inline:

```tsx
// Module-level caches (survive re-renders and folder navigation)
const storageClassCache = new Map<string, string>();
const lifecycleRulesCache = new Map<string, LifecycleRule[]>();

// In useEffect — piggyback on the existing HeadObject fetch loop:
if (!lifecycleRulesCache.has(bucket)) {
  let rules: LifecycleRule[] = [];
  try {
    const resp = await s3.send(new GetBucketLifecycleConfigurationCommand({ Bucket: bucket }));
    rules = resp.Rules ?? [];
  } catch (err) {
    if ((err as { name?: string }).name !== 'NoSuchLifecycleConfiguration') { /* ignore */ }
  }
  lifecycleRulesCache.set(bucket, rules);
  // Compute next transition for all visible file items
  if (rules.length > 0) {
    for (const item of fileItems) {
      const { transitions } = computeTransitions(rules, item.key, item.lastModified);
      nextTransitions[item.key] = transitions[0] ?? null;  // soonest first
    }
  }
}
```

Show inline next to the badge — small gray text, two lines:
```tsx
<>
  <StorageClassBadge sc={sc} />
  {nextTx && (
    <span style={{ display: 'block', fontSize: '0.7rem', color: '#888', marginTop: '0.1rem' }}>
      {nextTx.daysRemaining > 0
        ? `→ ${storageClassLabel(nextTx.storageClass)} in ${nextTx.daysRemaining}d`
        : `→ ${storageClassLabel(nextTx.storageClass)} (${Math.abs(nextTx.daysRemaining)}d ago)`}
    </span>
  )}
</>
```

### Shared lifecycle utility (`src/utils/lifecycleUtils.ts`)

Extract `computeTransitions`, `TransitionInfo`, `ExpirationInfo`, `storageClassLabel`, and
`STORAGE_CLASS_LABELS` to a shared util so both the inline table column and the full
`LifecycleInfoView` action panel can import from one place. Avoids duplication and keeps
the action view's `createLifecycleInfoView` type signature compatible with `useView`.

**`createLifecycleInfoView` type signature — use `LocationState` not `{ bucket, region }`:**
```typescript
// WRONG — `location.bucket` doesn't exist on the real LocationState:
useView: <K extends 'LocationDetail'>(type: K) => {
  location?: { bucket?: string; region?: string };
};

// CORRECT — matches Amplify's actual LocationDetailViewState shape:
interface LocationState {
  current: LocationData | undefined;  // LocationData has .bucket
  path: string;
  key: string;
}
useView: <K extends 'LocationDetail'>(type: K) => {
  location: LocationState;
};
// Then access: location.current?.bucket
```

---

## useEffect Infinite Loop — Amplify `useView` Array Reference Trap

**Symptom:** `ERR_INSUFFICIENT_RESOURCES` in the browser console; storage class column never loads;
the browser's network tab shows hundreds of identical HeadObject / Cognito token requests per second.

**Root cause:** Amplify's `useView('LocationDetail')` returns a **new `pageItems` array reference
on every render** — including when `dataItems` changes (file selected/deselected) or `activeFile`
changes (file preview activated). If `pageItems` is listed directly as a `useEffect` dependency,
the effect re-fires after every selection click:

```
click file → onSelect → dataItems updates → re-render → new pageItems ref
→ useEffect fires → setStorageClasses → re-render → new pageItems ref → loop
```

Each iteration calls `fetchAuthSession()` + HeadObject × N. A folder with 20 files generates
~20 requests per click, exhausting the browser connection pool in seconds.

**`ERR_INSUFFICIENT_RESOURCES` is a request flood, not a credentials error.** If you also see
`fetchAuthSession returned no credentials`, the flood is causing Cognito token requests to fail,
which is a downstream symptom — not the root cause.

**Fix:** Replace the `pageItems` dependency with a stable string of file keys. The effect then
only re-fires when the folder contents actually change (navigation or refresh), not on selection.

```tsx
// Compute once per render — cheap string join
const fileKeySignature = pageItems
  .filter(i => i.type === 'FILE')
  .map(i => i.key)
  .join('\n');

useEffect(() => {
  const fileItems = pageItems.filter((i): i is FileData => i.type === 'FILE');
  // ... fetch storage class / lifecycle rules
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [fileKeySignature, bucket, region]);  // NOT [pageItems, bucket, region]
```

**Why `eslint-disable`:** The exhaustive-deps lint rule will warn that `pageItems` is used inside
the effect but not listed as a dependency. The disable is intentional — `fileKeySignature` is the
stable proxy for the data we actually care about.

---

## Isolating Errors in Multi-Step `fetchAll` Functions

When one async operation must not block another (e.g., lifecycle rules fetch must not kill
HeadObject calls), wrap each independently in its own `try/catch`. A single outer catch
silently swallows ALL errors:

```typescript
const fetchAll = async () => {
  try {
    const session = await fetchAuthSession();
    const creds = session.credentials;
    if (!creds) {
      console.error('[StorageBrowser] no credentials — try signing out and back in');
      return;
    }
    const s3 = new S3Client({ ... });

    // Step 1: lifecycle rules (non-critical — must not kill Step 2)
    try {
      const resp = await s3.send(new GetBucketLifecycleConfigurationCommand({ Bucket: bucket }));
      rules = resp.Rules ?? [];
    } catch (err) {
      if ((err as { name?: string }).name !== 'NoSuchLifecycleConfiguration') { /* ignore */ }
    }

    // Step 2: compute transitions from rules (non-critical — must not kill Step 3)
    try {
      if (rules.length > 0) {
        for (const item of fileItems) {
          if (!item.lastModified) continue;  // guard against undefined lastModified
          const { transitions } = computeTransitions(rules, item.key, item.lastModified);
          ...
        }
      }
    } catch { /* lifecycle hints stay blank */ }

    // Step 3: HeadObject — this is what we actually need
    const results = await Promise.allSettled(
      batch.map(item => s3.send(new HeadObjectCommand({ ... })))
    );
    // Promise.allSettled never throws — each result has .status === 'fulfilled' | 'rejected'

  } catch (err) {
    console.error('[StorageBrowser] fetchAll failed:', err);  // log don't swallow
  }
};
```

**Key pattern:** `Promise.allSettled` for the HeadObject batch — it never throws, so individual
object failures don't abort the loop. Each result has `.status` and either `.value` or `.reason`.

**Never cache a HeadObject failure as a default value.** Only write to the storage class cache
on `r.status === 'fulfilled'`. If you cache the failure as `'STANDARD'` (via `?? 'STANDARD'`),
the badge is permanently wrong for that file until the user force-refreshes — and the bug is
invisible because Standard is the default. Leave the badge blank on failure so the user sees
something is missing and can retry via Refresh:
```typescript
if (r.status === 'fulfilled') {
  const sc = r.value.StorageClass ?? 'STANDARD';
  scCacheSet(key, sc);
  newClasses[key] = sc;
} else {
  console.warn('[StorageBrowser] HeadObject failed for', key, (r as PromiseRejectedResult).reason);
  // Do not cache — badge stays blank; user can retry on Refresh
}
```

**Transition hint selection — prefer next future, fall back to latest past:**
`computeTransitions` returns transitions sorted ascending by `daysRemaining`. When showing a
single inline hint, pick the soonest upcoming transition, not the oldest past one:
```typescript
// WRONG — picks oldest past transition when all transitions are already done:
computed[item.key] = transitions[0] ?? null;

// CORRECT — picks the next future, or most recent past if all done:
computed[item.key] =
  transitions.find(t => t.daysRemaining > 0) ??
  transitions[transitions.length - 1] ??
  null;
```
This matters in buckets that have multi-step lifecycle rules (e.g. Standard → IA after 30d →
Glacier after 90d). Without this fix, a file that is already in IA shows "→ Standard 30d ago"
instead of "→ Glacier in 60d".

**Storage class missing after lifecycle rules start working:** If `GetBucketLifecycleConfiguration`
previously returned `AccessDenied` (empty rules, skip block), adding the IAM permission makes it
return real rules. If `computeTransitions` then throws (e.g., unexpected rule shape, undefined
`lastModified`), the outer catch kills the HeadObject loop. Always isolate each step.

---

## Stale Session After `terragrunt apply` on Cognito Resources

After applying changes to `aws_cognito_identity_pool_roles_attachment` or `aws_iam_role_policy`,
the user's existing browser session may hold STS tokens tied to the old configuration.
Symptoms: `fetchAuthSession` returns `undefined` credentials; all S3 operations fail silently;
`ERR_INSUFFICIENT_RESOURCES` from Cognito token refresh floods.

**Fix:** Sign out and sign back in. This discards the cached STS tokens and forces a fresh
`GetId` + `GetCredentialsForIdentity` exchange against the updated identity pool role.

This is expected behavior — not a code bug. Document it in runbooks for any Cognito Terraform apply.

---

## Selection Persistence Across Action Mount/Unmount Cycles

### The problem
Amplify **unmounts** `CustomLocationDetailView` while an action view is shown (rename, copy, etc.)
and **remounts** it when the user exits the action (`onActionExit`). On remount:
- `dataItems` resets to `[]` (Amplify clears selection state)
- `useRef` resets to its initial value (component is brand new)
→ Selection is lost. Users must re-select their file to try a different action.

### The fix — two module-level maps
```typescript
// Survives mount/unmount — stores intentionally-selected items
const selectionMemory = new Map<string, LocationItemData>();
// Tracks items auto-restored on action exit — cleared on next user interaction
const restoredFromMemory = new Map<string, LocationItemData>();
```

### Wrapped select handlers (keep selectionMemory in sync)
```tsx
const handleSelect = (isSelected: boolean, item: LocationItemData) => {
  // Deselect any auto-restored items (except the one being clicked) to prevent
  // phantom multi-selection that greys out single-item actions (Rename, Storage Info).
  if (restoredFromMemory.size > 0) {
    for (const [id, restored] of restoredFromMemory) {
      if (id !== item.id) onSelect(true, restored); // currently selected → toggle off
    }
    restoredFromMemory.clear();
  }
  onSelect(isSelected, item);
  if (isSelected) selectionMemory.delete(item.id);
  else selectionMemory.set(item.id, item);
};

const handleToggleSelectAll = () => {
  restoredFromMemory.clear();
  onToggleSelectAll();
  if (allSelected) {
    selectionMemory.clear();
  } else {
    for (const item of selectableItems) selectionMemory.set(item.id, item);
  }
};
```

### Restore effect (runs once on mount = once on each remount after action exit)
```tsx
useEffect(() => {
  if ((dataItems ?? []).length > 0 || selectionMemory.size === 0) return;
  restoredFromMemory.clear();
  const pageItemMap = new Map(pageItems.map(i => [i.id, i]));
  for (const [id] of selectionMemory) {
    const live = pageItemMap.get(id);
    if (live) {
      onSelect(false, live); // currently unselected → Amplify toggles to selected
      restoredFromMemory.set(id, live);
    } else {
      selectionMemory.delete(id); // item was renamed/deleted
    }
  }
  selectionMemory.clear(); // hand off tracking to restoredFromMemory
// eslint-disable-next-line react-hooks/exhaustive-deps
}, []); // intentionally empty — runs once per mount (= once per action exit remount)

// Clear both maps on folder navigation
useEffect(() => {
  selectionMemory.clear();
  restoredFromMemory.clear();
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [location.key]);
```

### Critical bug to avoid: phantom multi-selection
**Symptom:** After returning from an action (e.g. Rename), user selects a new item. Rename and
Storage Info (or any action with `disable: sv => sv.length !== 1`) are greyed out.

**Root cause:** The restore effect re-selects the original item (A) into Amplify's state. When the
user clicks a new item (B), Amplify adds B alongside A → `dataItems = [A, B]` → `length !== 1` → disabled.

**Fix:** The `restoredFromMemory` map + the cleanup in `handleSelect` handle this: on the first
user selection after a restore, all restored items except the one being clicked are deselected first.

---

## Cancel Button for Action Views

Every action view that modifies files should have a Cancel button that calls `onActionExit()`.
Add it in two places: the "no file selected" fallback state and the main action form.

```tsx
export function createRenameFileView(
  useView: <K extends 'LocationDetail'>(type: K) => { dataItems?: LocationItemData[]; onActionExit: () => void },
) {
  return function RenameFileView() {
    const { dataItems, onActionExit } = useView('LocationDetail');
    // ...

    // No-file fallback — always show Cancel
    if (!selectedFile) {
      return (
        <div style={containerStyle}>
          <h2 style={headingStyle}>Rename File</h2>
          <p style={{ margin: 0, color: '#555' }}>No file selected.</p>
          <button onClick={onActionExit} style={cancelButtonStyle}>Cancel</button>
        </div>
      );
    }

    // Main form — Cancel beside the primary action button
    return (
      <div>
        {/* ... inputs, validation ... */}
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button onClick={() => void handleAction()} disabled={hasErrors} style={primaryButtonStyle}>
            Rename
          </button>
          <button onClick={onActionExit} style={cancelButtonStyle}>Cancel</button>
        </div>
      </div>
    );
  };
}

const cancelButtonStyle: React.CSSProperties = {
  padding: '0.5rem 1.25rem',
  background: 'transparent',
  color: '#555',
  border: '1px solid #ccc',
  borderRadius: '4px',
  cursor: 'pointer',
  fontSize: '0.9rem',
  fontWeight: 500,
};
```

Cancel is never `disabled` — even if validation is failing, the user should always be able to leave.

---

## Auto-Refresh After Custom Action Exit (fixes "can't reuse action after first use")

**Symptom:** After using a custom action from the dropdown (e.g., Rename, Storage Info), the action cannot be triggered again without a full page refresh.

**Root cause (unconfirmed):** Amplify's internal action state machine appears to get stuck after a custom action's no-op handler resolves immediately to `COMPLETE`. A full page refresh resets it.

**Fix:** Call `onRefresh()` before `onActionExit()` at every exit point in the custom action view. This triggers an Amplify file-list refresh which also resets whatever internal state is blocking re-invocation.

```typescript
export function createMyCustomView(
  useView: <K extends 'LocationDetail'>(type: K) => {
    dataItems?: LocationItemData[];
    onActionExit: () => void;
    onRefresh?: () => void;   // ← add this
    location: LocationState;
  },
) {
  return function MyCustomView() {
    const { dataItems, onActionExit, onRefresh } = useView('LocationDetail');
    const exit = () => { onRefresh?.(); onActionExit(); };  // ← wrap every exit
    // ... use exit() instead of onActionExit() on ALL buttons (Done, Cancel, Back, Close)
  };
}
```

Apply `exit` to **every** button that calls `onActionExit` — Done, Cancel, Back, Close. Skipping any one of them leaves the bug partially present on that path.

`onRefresh` is optional (`?`) because older type signatures from `useView` may not expose it; the optional call `onRefresh?.()` is safe either way.

---

## Custom Download View (fixing greyed-out Cancel)

The built-in Amplify Download action has a Cancel button that is always greyed out — it is wired
to an internal cancel handler that never becomes active for the simple file download flow.

**Fix: replace with a custom download view factory.** The custom view gets full control over
Cancel and the file list.

Key implementation decisions:
- Pre-start phase: show table of selected files + "Download N file(s)" button. Cancel → `onActionExit()`.
- Processing phase: "Opening download links…" message. Cancel → `onActionCancel()` (Amplify-provided).
- Complete phase: success/failure counts. Done → `onActionExit()`.
- Trigger each file's download by opening a signed URL in a new tab (`window.open(url, '_blank')`).

```tsx
export function createCustomDownloadView(
  useView: (type: 'Download') => {
    tasks?: Array<{ key: string; status: string; cancel?: () => void }>;
    onActionCancel: () => void;
    onActionExit: () => void;
    onActionStart: () => void;
  },
) {
  return function CustomDownloadView() {
    const { tasks, onActionCancel, onActionExit, onActionStart } = useView('Download');
    const [phase, setPhase] = useState<'idle' | 'running' | 'done'>('idle');

    const handleDownload = () => {
      setPhase('running');
      onActionStart();
      for (const task of tasks ?? []) {
        if (task.key) window.open(`/api/download?key=${encodeURIComponent(task.key)}`, '_blank');
      }
      setPhase('done');
    };

    if (phase === 'running') return (
      <div>
        <p>Opening download links…</p>
        <button onClick={() => { onActionCancel(); setPhase('idle'); }}>Cancel</button>
      </div>
    );

    if (phase === 'done') return (
      <div>
        <p>{tasks?.length ?? 0} file(s) queued for download.</p>
        <button onClick={onActionExit}>Done</button>
      </div>
    );

    return (
      <div>
        <table>{/* file list with 🗑 remove button */}</table>
        <button onClick={handleDownload}>Download {tasks?.length ?? 0} file(s)</button>
        <button onClick={onActionExit}>Cancel</button>
      </div>
    );
  };
}
```

Register in App.tsx:
```tsx
// Inside the factory setup (after createStorageBrowser returns useView)
const CustomDownloadView = createCustomDownloadView(useView as any);
<StorageBrowser views={{ DownloadView: CustomDownloadView }} />
```

---

## Remove-from-List Button UX (Trash Icon)

For "remove from list" buttons in Copy, Move, and Download action views, use the trash icon
(`&#x1F5D1;` — 🗑) instead of the close symbol (`&#x2715;` — ✕). The trash icon immediately
communicates "remove from list" whereas ✕ reads as "cancel the whole action".

```tsx
<button
  onClick={() => removeFile(item.key)}
  style={removeButtonStyle}
  title={`Remove ${item.key.split('/').pop()} from list`}
  aria-label="Remove from list"
>
  &#x1F5D1;
</button>
```

```typescript
const removeButtonStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: '#c0392b',
  cursor: 'pointer',
  fontSize: '1.1rem',  // slightly larger than 1rem so the emoji renders clearly
  lineHeight: 1,
  padding: '0.1rem 0.3rem',
};
```

Column header for the remove column: `"Remove from list"` (not just "Remove" — users need to
know it removes from the pending list, not from S3).

---

## Lambda Infinite-Loop Guard (when S3 triggers Lambda)
Check path component [2] specifically, not substring of whole key:
```python
key_parts = key.split("/")
if len(key_parts) > 2 and key_parts[2] == "flowjo_processed":
    return {'Success': True, 'Skipped': True, 'Key': key}
```

---

## Deploying to an Account Where S3 Already Exists

When the target account already has S3 buckets configured (CORS, lifecycle, Lambda trigger in
place), skip the `s3_data` Terraform module entirely. Decouple the other modules from it using
a `local` variable as the single point of change.

### IaC decoupling pattern

In both `cognito/terragrunt.hcl` and `amplify_app/terragrunt.hcl`, add a local instead of
referencing `dependency.s3_data.outputs.*`:

```hcl
locals {
  account_id = get_env("AWS_ACCOUNT_ID", get_aws_account_id())

  # ---- SET FOR TARGET ENVIRONMENT ------------------------------------------
  # Must match in both cognito/terragrunt.hcl and amplify_app/terragrunt.hcl.
  primary_bucket_name = "my-existing-bucket-name"
  # --------------------------------------------------------------------------
}

inputs = {
  bucket_arn = "arn:aws:s3:::${local.primary_bucket_name}"
  # ...
}
```

In `amplify_app/terragrunt.hcl`:

```hcl
environment_variables = {
  VITE_S3_BUCKET = local.primary_bucket_name
  # ...
}
```

### Deployment order (existing bucket)

```
1. Set local.primary_bucket_name in cognito/ and amplify_app/ to existing bucket name
2. terragrunt apply cognito          # creates User Pool + Identity Pool + IAM
3. terragrunt apply amplify_app      # creates Amplify app + WAF
4. (build + deploy web/dist/)
5. Re-apply cognito with Amplify branch URL added to callback_urls
```

### Cross-account read access for extra buckets

The cognito module grants `s3:GetObject` on extra bucket ARNs via IAM. This is necessary but
not sufficient for cross-account — the bucket owner must also add a bucket policy on their side:

```json
{
  "Effect": "Allow",
  "Principal": { "AWS": "<cognito-authenticated-role-arn>" },
  "Action": "s3:GetObject",
  "Resource": "arn:aws:s3:::their-bucket/*"
}
```

Retrieve the role ARN after applying cognito:

```bash
cd terraform/live/dev/cognito && terragrunt output -raw authenticated_role_arn
```

Add `authenticated_role_arn` to `cognito/outputs.tf` if not already present:

```hcl
output "authenticated_role_arn" {
  description = "ARN of the IAM role assumed by authenticated Cognito identities."
  value       = aws_iam_role.cognito_authenticated.arn
}
```

### Existing bucket checklist (verify before applying Cognito)

- [ ] CORS allows `GET PUT POST DELETE HEAD` from Amplify app origin + `http://localhost:5173`
- [ ] `ETag` in CORS `expose_headers` (required for multipart upload verification)
- [ ] `DELETE` in CORS `allowed_methods` (needed for AbortMultipartUpload — not a security gap, IAM governs actual delete permission)
- [ ] S3 event notification pointing to ion_tail Lambda (if Lambda processing is in scope)
- [ ] `create_lambda_trigger = false` in `s3_data/terragrunt.hcl` — do not let Terraform manage the existing notification

---

## Manual Amplify Deployment (No GitHub CI)

When `manual_deploy = true` in the Amplify app Terraform config, there is no GitHub connection. Build locally and deploy via the CLI. The `--source-url file://` flag does NOT work for zip uploads — Amplify returns a presigned S3 URL instead.

### Full deploy sequence

```bash
# 1. Build (VITE_ vars must be set in .env or shell before this)
cd web/
npm run build

# 2. Package
rm -f dist.zip
cd dist && zip -r ../dist.zip . && cd ..

# 3. Create deployment — returns jobId + presigned zipUploadUrl
DEPLOY=$(AWS_PROFILE=<profile> aws amplify create-deployment \
    --app-id <app-id> --branch-name master \
    --region <region> --output json)

JOB=$(echo $DEPLOY | python3 -c "import sys,json; print(json.load(sys.stdin)['jobId'])")
UPLOAD_URL=$(echo $DEPLOY | python3 -c "import sys,json; print(json.load(sys.stdin)['zipUploadUrl'])")

# 4. Upload zip via presigned URL (curl PUT, no auth header needed)
curl -T dist.zip "$UPLOAD_URL"

# 5. Start the deployment
AWS_PROFILE=<profile> aws amplify start-deployment \
    --app-id <app-id> --branch-name master --job-id $JOB \
    --region <region>
```

**Gotchas:**
- If a previous job is stuck in `PENDING`, cancel it first: `aws amplify stop-job --job-id <id>`
- App ID is in the Amplify URL: `https://master.<app-id>.amplifyapp.com`
- `--region` must be specified — Amplify apps are regional and the CLI may default to the wrong region
- `fileb://` and `file://` prefixes don't work with `--source-url` — only presigned URL approach works

---

## Multi-Account / Multi-Region Migration

When redeploying the stack to a new AWS account or region, update these locations:

### `terraform/live/dev/root.hcl`
```hcl
locals {
  aws_region   = "us-east-2"          # new region
  project_name = "myproject"          # new name prefix → state bucket = myproject-tf-state-<account_id>
}
```

### `terraform/live/dev/cognito/terragrunt.hcl`
- `pool_name` — update to match new project name
- `extra_bucket_names` — update to the buckets that exist in the new account
- `callback_urls` / `logout_urls` — placeholder until Amplify app is deployed; update in pass 2

### `terraform/live/dev/amplify_app/terragrunt.hcl`
- `VITE_AWS_REGION` — update to new region
- `extra_buckets` list — update bucket names and regions
- Mock outputs (`us-west-2_MOCK`, `us-west-2:mock-identity-pool`) — update region prefix
- `VITE_S3_PRIMARY_BUCKET_LABEL` — label shown in bucket switcher for primary bucket

### Primary bucket label env var
The primary bucket label is not derivable from the bucket name — add `VITE_S3_PRIMARY_BUCKET_LABEL` env var:

`amplify_app/terragrunt.hcl`:
```hcl
VITE_S3_PRIMARY_BUCKET_LABEL = "Saber"
```

`amplify-config.ts`:
```typescript
const primaryBucket = {
  alias: 'primaryData',
  label: import.meta.env.VITE_S3_PRIMARY_BUCKET_LABEL || 'Primary Bucket',
};
```

`vite-env.d.ts`:
```typescript
readonly VITE_S3_PRIMARY_BUCKET_LABEL: string;
```

### State bucket bootstrap (new account)
Must exist before first `terragrunt plan`. Create with versioning + encryption:
```bash
aws s3api create-bucket --bucket <project>-tf-state-<account_id> \
  --region <region> --create-bucket-configuration LocationConstraint=<region>
aws s3api put-bucket-versioning --bucket <project>-tf-state-<account_id> \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket <project>-tf-state-<account_id> \
  --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws s3api put-bucket-encryption --bucket <project>-tf-state-<account_id> \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

### Two-pass Cognito apply
1. Apply `cognito` with `localhost` placeholder in `callback_urls`
2. Apply `amplify_app` → get `amplify_app_url` output
3. Add Amplify URL to `callback_urls` + `logout_urls` in `cognito/terragrunt.hcl`
4. Re-apply `cognito`

### CORS on pre-existing buckets (console)
`put-bucket-cors` **overwrites** — it does not append. If a bucket already has CORS rules:
1. Read existing rules first (S3 console → Permissions → Cross-origin resource sharing)
2. Add the new rule to the existing array
3. Save the merged result

Minimum rule for Storage Browser:
```json
{
  "AllowedHeaders": ["*"],
  "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
  "AllowedOrigins": ["http://localhost:5173", "https://master.<app-id>.amplifyapp.com"],
  "ExposeHeaders": ["ETag"],
  "MaxAgeSeconds": 3000
}
```
