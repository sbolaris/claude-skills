---
name: mysql-admin-lambda
description: "Create a VPC-connected, CLI-invokable Lambda to manage application-level MySQL user records without a bastion host or direct database access."
tags: [lambda, mysql, rds, vpc, aws]
---

# MySQL Admin Lambda (VPC-connected, CLI-invokable)

Pattern for creating a standalone Lambda to manage application-level MySQL user records without a bastion host or direct DB access.

## When to use
- App's MySQL DB is in a VPC (standard RDS, not Aurora Serverless)
- Need to add/update/check users outside the normal registration flow
- Want an IAM-controlled, auditable alternative to direct DB access

## Key design decisions

**Standalone Lambda, not an API endpoint** — invoke via `aws lambda invoke` from the CLI. No API Gateway, no auth token needed beyond IAM `lambda:InvokeFunction`. Keeps it off the public surface.

**Goes through the same DB credentials as the app** — pull from Secrets Manager (same secret the app uses), not hardcoded. VPC config matches the app's fe Lambda (same subnet + security group).

**Account mapping** — the Lambda must be in the same AWS account as the RDS instance and VPC. The secret can be in a different account if you set up a cross-account resource policy on the secret.

## Payload schema
```json
{
  "users": [
    {"email": "user@example.com", "group": "QC"}
  ]
}
```

## Logic
- **Not found** → INSERT with given group
- **Exists, group matches** → skip ("already correct")
- **Exists, group differs** → UPDATE to requested group

Note: skip check should match on `current_group.upper() == requested_group` (case-insensitive), not on "is it a valid group" — otherwise you can't change someone from QC to MFG.

## Deploy pattern
Pull MySQL creds + VPC config from Secrets Manager in CircleCI/deploy script (same pattern as app). Pass as Lambda env vars + VPC config at create/update time. Do not hard-code.

```bash
# Create in correct account (account that owns the VPC + RDS)
aws lambda create-function \
    --function-name admin-user-mgmt-dev \
    --runtime python3.11 \
    --role "arn:aws:iam::ACCOUNT:role/CICD" \
    --handler admin_user_mgmt.lambda_handler \
    --zip-file fileb://function.zip \
    --timeout 30 \
    --environment "Variables={MYSQL_DATABASE_HOST=...,MYSQL_DATABASE_USER=...,MYSQL_DATABASE_PASSWORD=...,MYSQL_DATABASE_DB=...}" \
    --vpc-config "SubnetIds=subnet-...,SecurityGroupIds=sg-..." \
    --region us-west-2
```

## Invoke
```bash
aws lambda invoke \
  --function-name admin-user-mgmt-dev \
  --cli-binary-format raw-in-base64-out \
  --payload '{"users":[{"email":"user@example.com","group":"QC"}]}' \
  --region us-west-2 \
  out.json && cat out.json | jq '.body'
```

## Cross-account secrets
If the secret lives in account A but the Lambda is in account B:
1. Add a resource policy to the secret in A allowing account B's Lambda role
2. Reference the secret by full ARN in the Lambda code (not by name)
3. Update the Lambda's IAM permission to allow `secretsmanager:GetSecretValue` on the ARN

Better long-term: pull the secret in CI at deploy time and inject as an env var — avoids runtime cross-account calls entirely. Same pattern CircleCI uses for MYSQL_DB, Okta, etc.

## Requirements
- `pymysql==1.1.1` (no Flask dependency — standalone Lambda)
- Python 3.11 runtime
