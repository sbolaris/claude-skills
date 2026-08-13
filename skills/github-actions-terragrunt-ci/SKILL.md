---
name: github-actions-terragrunt-ci
description: "Wire GitHub Actions to run terragrunt plan on PRs with AWS OIDC auth, topological init, per-leaf plan output, and PR comment posting. Use when setting up or debugging Terragrunt CI."
tags: [github-actions, terragrunt, ci, oidc, aws]
---

# GitHub Actions CI for Terragrunt (OIDC + Plan + PR Comment)

Reusable pattern for wiring GitHub Actions to run `terragrunt plan` on PRs with OIDC auth, topological init, per-leaf plan output, and PR comment posting. Battle-tested through ~10 iterations of failure modes (May 2026).

---

## AWS OIDC Setup (one-time per account)

### 1. Create GitHub Actions OIDC provider
```bash
# Check first
aws iam list-open-id-connect-providers | grep token.actions

# Create if missing
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 2. Add GitHub Actions trust statement to CICD role
Keep existing trust principals (CircleCI etc.) during transition. Add alongside:
```json
{
  "Effect": "Allow",
  "Principal": {
    "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
  },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
    },
    "StringLike": {
      "token.actions.githubusercontent.com:sub": "repo:<ORG>/<REPO>:*"
    }
  }
}
```
```bash
aws iam update-assume-role-policy --role-name CICD --policy-document file://trust-policy.json
```

For multi-account setups (non-prod + prod), repeat both steps in each account before merging the workflow PR.

---

## Workflow Strategy: run-all init + per-leaf plan

After trying several approaches, the working pattern is:

1. **Single `terragrunt run-all init` upfront** — walks the dep graph in topological order, populating every leaf's provider cache before any plan runs
2. **Per-leaf plan loop** — iterates each `terragrunt.hcl`, runs `terragrunt plan` standalone for per-stack error reporting
3. **Pre-init step for cross-env deps** (only needed when leaves reference paths outside `PLAN_DIR`)

### Why not run-all plan?
- Bulk error message that's hard to map back to which leaf failed
- A single broken leaf taints the entire output

### Why not per-leaf init?
- Iterates alphabetically, which is **not** dep order
- Example: `batch/jobs/foo` (sorts 2nd) depends on `ecr/` (sorts 5th) → init `batch/jobs` first, it walks into uninit'd ecr/ cache, fails

---

## Workflow Template

```yaml
name: Terragrunt Plan — dev

on:
  pull_request:
    paths:
      - 'infra/terraform/live/non-prod/myproject/dev/**'
      - 'infra/terraform/modules/**'
      - 'infra/terraform/terragrunt.hcl'
      - 'infra/terraform/global.hcl'
      - '.github/workflows/plan-dev.yml'

concurrency:
  group: plan-dev-${{ github.head_ref }}
  cancel-in-progress: true

permissions:
  id-token: write       # required for OIDC
  contents: read
  pull-requests: write  # required to post plan comments

env:
  TF_VERSION: "1.14.6"   # MUST match (or exceed) the version that last applied — see "TF state version" gotcha
  TG_VERSION: "0.50.17"
  AWS_REGION: us-west-2
  TF_INPUT: "false"
  TF_IN_AUTOMATION: "true"
  TERRAGRUNT_NON_INTERACTIVE: "true"
  PLAN_DIR: infra/terraform/live/non-prod/myproject/dev/us-west-2

jobs:
  plan-dev:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - uses: hashicorp/setup-terraform@v4
        with:
          terraform_version: ${{ env.TF_VERSION }}
          terraform_wrapper: false

      - name: Install Terragrunt
        run: |
          curl -sLo /tmp/terragrunt \
            "https://github.com/gruntwork-io/terragrunt/releases/download/v${{ env.TG_VERSION }}/terragrunt_linux_amd64"
          chmod +x /tmp/terragrunt && sudo mv /tmp/terragrunt /usr/local/bin/terragrunt

      - uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::<ACCOUNT_ID>:role/CICD
          aws-region: ${{ env.AWS_REGION }}
          role-session-name: gha-plan-dev-${{ github.run_id }}

      # OPTIONAL: only needed for envs that reference cross-env deps via
      # `config_path` outside PLAN_DIR. Pre-init each cross-env dep so its
      # provider cache is populated before the per-leaf evaluation in plan
      # walks into it.
      - name: Pre-init cross-env dependencies
        run: |
          set -e
          for dep in \
            infra/terraform/live/non-prod/myproject/test/us-west-2/ecr \
            infra/terraform/live/non-prod/myproject/test/us-west-2/security/iam_roles_policies; do
            pushd "$dep" > /dev/null
            terragrunt init -upgrade=false -no-color
            popd > /dev/null
          done

      # Init every leaf in topological order. Walks the dep graph so each
      # leaf's deps are init'd (provider cache populated) before the leaf
      # itself. Required for `dependency.X.outputs.Y` evaluation to work
      # in the per-leaf plan loop below.
      - name: Terragrunt run-all init (topological)
        run: |
          cd "${{ env.PLAN_DIR }}"
          terragrunt run-all init \
            --terragrunt-ignore-external-dependencies \
            --terragrunt-non-interactive \
            -upgrade=false -no-color

      - name: Plan each leaf stack
        id: plan
        run: |
          set +e
          cd "${{ env.PLAN_DIR }}"
          : > /tmp/summary.txt   # one-line-per-stack status
          : > /tmp/plan.txt      # full output for FAILED stacks only
          failed=0

          mapfile -t leaves < <(
            find . -mindepth 2 -name terragrunt.hcl \
              -not -path '*/.terragrunt-cache/*' \
              -printf '%h\n' | sort
          )

          echo "Discovered ${#leaves[@]} leaf stacks under ${{ env.PLAN_DIR }}"

          for leaf in "${leaves[@]}"; do
            pushd "$leaf" > /dev/null
            terragrunt plan -lock=false -no-color > /tmp/leaf.log 2>&1
            plan_rc=$?
            popd > /dev/null

            if [ $plan_rc -ne 0 ]; then
              echo "❌ FAILED ($plan_rc): $leaf" | tee -a /tmp/summary.txt
              failed=1
              printf '\n============================================================\n' >> /tmp/plan.txt
              printf 'Stack: %s (FAILED rc=%s)\n' "$leaf" "$plan_rc" >> /tmp/plan.txt
              printf '============================================================\n' >> /tmp/plan.txt
              cat /tmp/leaf.log >> /tmp/plan.txt
            else
              echo "✅ $leaf" | tee -a /tmp/summary.txt
            fi
          done

          echo "status=$failed" >> "$GITHUB_OUTPUT"
          exit 0
        continue-on-error: true

      - name: Post plan output to PR
        uses: actions/github-script@v9
        env:
          PLAN_STATUS: ${{ steps.plan.outputs.status }}
        with:
          script: |
            const fs = require('fs');
            const summary = fs.readFileSync('/tmp/summary.txt', 'utf8').trim();
            const details = fs.existsSync('/tmp/plan.txt')
              ? fs.readFileSync('/tmp/plan.txt', 'utf8')
              : '';
            const MAX = 50000;
            const detailsTrunc = details.length > MAX
              ? details.slice(0, MAX) + '\n\n... output truncated (see workflow logs)'
              : details;

            const status = process.env.PLAN_STATUS === '0' ? '✅ success' : '❌ failed';
            const parts = [
              `## Terragrunt Plan — \`dev\` ${status}`,
              '',
              '### Stacks',
              '```',
              summary,
              '```',
            ];

            if (process.env.PLAN_STATUS !== '0' && detailsTrunc.trim()) {
              parts.push('');
              parts.push('### Failed plan output');
              parts.push('<details><summary>Expand</summary>');
              parts.push('');
              parts.push('```');
              parts.push(detailsTrunc);
              parts.push('```');
              parts.push('</details>');
            }

            parts.push('');
            parts.push(`*Workflow: \`${{ github.workflow }}\` | Commit: \`${{ github.sha }}\` | [Logs](${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }})*`);
            const body = parts.join('\n');

            const { data: comments } = await github.rest.issues.listComments({
              owner: context.repo.owner, repo: context.repo.repo,
              issue_number: context.issue.number,
            });
            const marker = 'Terragrunt Plan — `dev`';
            const existing = comments.find(c => c.user.login === 'github-actions[bot]' && c.body.includes(marker));
            if (existing) {
              await github.rest.issues.updateComment({
                owner: context.repo.owner, repo: context.repo.repo,
                comment_id: existing.id, body,
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner, repo: context.repo.repo,
                issue_number: context.issue.number, body,
              });
            }

      - name: Fail if plan errored
        if: steps.plan.outputs.status != '0'
        run: exit 1
```

---

## Gotchas (the ones that cost real time)

### 1. `Required plugins are not installed` in a dep dir's cache

```
Error: Required plugins are not installed
  - registry.terraform.io/hashicorp/aws: there is no package for hashicorp/aws 5.9.0 cached in .terraform/providers
time=... msg=[/.../test/us-west-2/ecr/.terragrunt-cache/350412247] exit status 1
```

**Cause:** When leaf A evaluates `dependency.B.outputs.X`, Terragrunt walks into B's dir, creates a fresh `.terragrunt-cache/<hash>/`, and tries to run `terraform output` — but the providers aren't installed in that fresh cache.

**Fix:** Use `run-all init` upfront (as in the template above). It iterates topologically, so B is fully init'd (provider cache populated) before A evaluates its `dependency.B`. Per-leaf or alphabetical init does NOT solve this.

For cross-env deps that live outside `PLAN_DIR`, add the explicit pre-init step.

### 2. mock_outputs whitelist must include `"init"`

If a dep block has `mock_outputs` for fresh/unapplied state, the whitelist of allowed commands needs `init`:

```hcl
dependency "step" {
  config_path = "../../../services/step//lambda-ingestion"
  mock_outputs = {
    arn = "arn:aws:states:us-west-2:000000000000:stateMachine:placeholder"
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "plan", "providers"]
}
```

Why `init` matters: in older Terragrunt versions, init evaluates dep blocks. If the dep's real state isn't readable and `init` isn't whitelisted for mocks, init fails. Older docs only mentioned `validate`/`plan`; that's incomplete.

### 3. TF state version mismatch — `unsupported checkable object kind "var"`

```
Error refreshing state: 8 problems:
  - unsupported checkable object kind "var"
```

**Cause:** Terraform 1.9+ records variable validation results in state as `"checkable object kind 'var'"` entries. Older Terraform reads the state file, doesn't recognize the JSON shape, errors out.

**Fix:** Bump `TF_VERSION` in the workflow to match (or exceed) the version that most recently applied. Check by looking at local `terraform --version` or by inspecting the state file's `terraform_version` field.

**License caveat:** Terraform 1.5.6+ is BUSL-licensed (not MPL). Confirm org policy permits BUSL before bumping past 1.5.5; otherwise switch to OpenTofu (MPL fork of 1.5.7+).

### 4. Provider lock file platform mismatch

Lock files generated on macOS only have `h1:` hashes for darwin platforms. Linux CI runners fail with the same "no package cached" error as gotcha #1, but the fix is different:

```bash
# Run locally on macOS, commit the updated locks:
terragrunt run-all providers lock \
  -platform=linux_amd64 \
  -platform=darwin_arm64 \
  -platform=darwin_amd64
```

Distinguish from gotcha #1 by reading the error carefully: platform-mismatch errors say "checksum list has no matching hash"; cache-not-populated errors say "no package ... cached in .terraform/providers".

### 5. PR comment 60K character cap

GitHub issue comment limit is 65,536 chars. A `run-all plan` output for 20+ leaves can easily exceed this. If a failure happens near the end, the error is in the truncated tail.

**Fix:** Use the per-leaf plan loop with summary-only-on-success / details-on-failure pattern (see template). On a green run, the comment is a short checklist; on a failure, only the failing leaves' full plan output appears.

### 6. `--terragrunt-ignore-external-dependencies` scope

`run-all init` defaults to following the *entire* dep graph including out-of-tree paths. For multi-env repos where dev leaves reference test ECR (etc.), this causes run-all to try to init resources in the wrong env (often with wrong role perms).

**Fix:** Always pass `--terragrunt-ignore-external-dependencies` to scope init to the current `PLAN_DIR`. Handle cross-env deps via the explicit pre-init step before run-all init.

### 7. Latent bugs surface when CI stops suppressing failures

If the previous CI suppressed plan output with `|| true` (common pattern for tfsec/checkov in noisy repos), real plan errors have been hidden for months/years. The new strict workflow will surface them all at once. Expect:

- Orphaned outputs (output references a resource that was removed)
- Orphaned inputs (leaf passes args the module no longer accepts)
- Missing required inputs (module added a variable, leaf wasn't updated)
- Stale state from manual deletions in AWS console

These are normal latent debt, not workflow bugs. Triage one at a time.

### 8. Cache dir hash isn't stable across invocation contexts

In older Terragrunt versions, the `.terragrunt-cache/<hash>/` dir created when leaf A walks into B's dep is **different** from the one created by running terragrunt directly in B. Pre-initing B with one invocation doesn't always populate the hash that A sees.

This is why the workflow does `run-all init` (which walks the graph in the same invocation context that the dependents will use) rather than initing each leaf in isolation.

If hashes still don't align, the cleanest fix is bumping Terragrunt to 0.59+ which fetches dep state from S3 directly (no terraform init in the dep dir needed).

### 9. Node.js action versions (as of April 2026)

Node 20 deprecated June 2026. Node 24 native versions:

| Action | Node 24 version |
|--------|----------------|
| `actions/checkout` | `@v5` |
| `actions/github-script` | `@v9` |
| `aws-actions/configure-aws-credentials` | `@v6` (v4 and v5 are still Node 20) |
| `hashicorp/setup-terraform` | `@v4` |

---

## Multi-env workflow rollout

Create one workflow file per env (`plan-dev.yml`, `plan-test.yml`, `plan-prod.yml`):

| File | Path triggers | AWS account |
|------|---|---|
| `plan-dev.yml` | `live/non-prod/.../dev/**` | non-prod |
| `plan-test.yml` | `live/non-prod/.../test/**` | non-prod |
| `plan-prod.yml` | `live/prod/**` | prod |

All three also trigger on `modules/**`, root configs, and their own workflow file changes.

Each workflow needs OIDC setup in its AWS account. Non-prod and prod usually need separate trust policy updates.

---

## Migration from CircleCI

1. Build GHA workflows on a feature branch, keep CircleCI active in parallel
2. Update OIDC trust on CICD roles to include BOTH CircleCI and GHA principals
3. Merge GHA workflows; verify several PRs run cleanly through GHA
4. Remove CircleCI principals from trust policies (one account at a time)
5. Delete `.circleci/` directory in a follow-up PR
6. Delete CircleCI OIDC providers from AWS accounts

Don't delete CircleCI in the same PR that adds GHA — keep rollback path open.
