---
name: aws-account-teardown
description: "Fully destroy a dev or prototype AWS deployment involving Amplify Hosting, Cognito, WAF, and S3, including resources that have drifted out of Terraform state. Use for teardown, account cleanup, or when 'terragrunt destroy' is blocked."
tags: [aws, terragrunt, teardown, amplify, cognito, s3]
---

# AWS Account Teardown (Amplify + Cognito + WAF + S3)

Patterns for fully destroying a dev/prototype AWS deployment that includes Amplify Hosting, Cognito, WAF, and S3 — covering both Terraform-managed and out-of-state resources.

---

## Common blockers before `terragrunt destroy`

### Cognito deletion protection
Terraform will fail with `InvalidParameterException: The user pool cannot be deleted because deletion protection is activated`.

Disable it first:
```bash
AWS_PROFILE=<profile> aws cognito-idp update-user-pool \
  --user-pool-id <pool-id> \
  --deletion-protection INACTIVE \
  --region <region>
```

### Cognito domain must be deleted before user pool
Terraform will fail with `User pool cannot be deleted. It has a domain configured that should be deleted first`.

Find the domain:
```bash
AWS_PROFILE=<profile> aws cognito-idp describe-user-pool \
  --user-pool-id <pool-id> \
  --region <region> \
  --query 'UserPool.Domain' --output text
```

Delete it:
```bash
AWS_PROFILE=<profile> aws cognito-idp delete-user-pool-domain \
  --domain <domain-name> \
  --user-pool-id <pool-id> \
  --region <region>
```

---

## Destroy order for Amplify + Cognito + S3 stacks

Order matters due to IAM role dependencies:

1. **amplify_app** — destroys Amplify app/branch + WAF WebACL (us-east-1 for CloudFront scope)
2. **s3_data** — destroys data bucket (requires `force_destroy = true` in Terraform if bucket has content)
3. **cognito** — destroys user pool, identity pool, IAM roles, OIDC provider

```bash
# Step 1
cd terraform/live/<env>/amplify_app
export PRIMARY_S3_BUCKET=<bucket-name>
AWS_PROFILE=<profile> terragrunt destroy

# Step 2
cd ../s3_data
AWS_PROFILE=<profile> terragrunt destroy

# Step 3
cd ../cognito
export PRIMARY_S3_BUCKET=<bucket-name>
AWS_PROFILE=<profile> terragrunt destroy
```

---

## Deleting out-of-state WAF IP sets (CloudFront scope)

Amplify sometimes creates WAF IP sets that are never imported into Terraform state. Find them in AWS Console → WAF → us-east-1, or from a prior audit. Deletion requires a lock token:

```bash
for ID_NAME in \
  "<uuid1>:<name1>" \
  "<uuid2>:<name2>"; do
  ID="${ID_NAME%%:*}"; NAME="${ID_NAME##*:}"
  TOKEN=$(AWS_PROFILE=<profile> aws wafv2 get-ip-set \
    --scope CLOUDFRONT --region us-east-1 \
    --id $ID --name $NAME \
    --query 'LockToken' --output text)
  AWS_PROFILE=<profile> aws wafv2 delete-ip-set \
    --scope CLOUDFRONT --region us-east-1 \
    --id $ID --name $NAME --lock-token $TOKEN
done
```

---

## Delete the Terraform state bucket (last step)

Always do this last — after all modules are destroyed and state is no longer needed:

```bash
AWS_PROFILE=<profile> aws s3 rb s3://<state-bucket-name> --force
```

`--force` removes all objects and versions before deleting the bucket.

---

## Terragrunt root.hcl gotchas for teardown branches

If the root.hcl was originally misconfigured (wrong project_name or region), fix it before running destroy or Terragrunt will target the wrong state bucket:

```diff
- project_name = "old-name"   # may not match actual state bucket
+ project_name = "correct-name"

- aws_region = "us-east-2"    # resources may actually be in us-west-2
+ aws_region = "us-west-2"
```

Commit fixes on a `chore/dev-account-cleanup` branch — do NOT merge to main (destroy-only branch).
