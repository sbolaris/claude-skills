---
name: lambda-container-audit
description: Pull a deployed Lambda container image, extract source files, and diff against the repo to validate changes before deploying a new version
tags: [lambda, docker, ecr, deployment]
---

# Lambda Container Audit & Deploy

## When to use
Before deploying a new Lambda container image, pull the currently-deployed image and diff it against
the repo to confirm what's actually changing and catch any unexpected regressions.

## 1. Find the current image URI

```bash
AWS_PROFILE=<profile> aws lambda get-function \
  --function-name <function-name> \
  --region <region> \
  --query 'Code.ImageUri' --output text
```

Returns: `<account>.dkr.ecr.<region>.amazonaws.com/<repo>@sha256:<digest>`

## 2. ECR login (sudo required if Docker runs as root)

```bash
AWS_PROFILE=<profile> aws ecr get-login-password --region <region> \
  | sudo docker login --username AWS --password-stdin \
    <account>.dkr.ecr.<region>.amazonaws.com
```

Note: `docker login` without sudo stores creds in `~/.docker/config.json`; with sudo stores in
`/root/.docker/config.json`. If you get "no basic auth credentials" on pull, re-login with sudo.

## 3. Pull and extract source files

```bash
# Pull by digest (exact deployed version)
sudo docker pull <image-uri-with-digest>

# Create a container without starting it
sudo docker create --name audit_container <image-uri-with-digest>

# Extract files (Lambda Python files land in /var/task/)
sudo docker cp audit_container:/var/task/lambda_main.py /tmp/deployed_lambda_main.py
sudo docker cp audit_container:/var/task/ion_tail.py    /tmp/deployed_ion_tail.py

# Cleanup
sudo docker rm audit_container
```

## 4. Diff against repo

```bash
diff /tmp/deployed_lambda_main.py /path/to/repo/ion_tail/lambda_main.py
diff /tmp/deployed_ion_tail.py    /path/to/repo/ion_tail/ion_tail.py
```

Empty output = identical. Review any differences before proceeding.

## 5. Build and push new image

```bash
cd /path/to/repo/ion_tail

# Build for Lambda's architecture (always amd64 regardless of host)
sudo docker build --platform linux/amd64 \
  -t <account>.dkr.ecr.<region>.amazonaws.com/<repo>:latest .

sudo docker push <account>.dkr.ecr.<region>.amazonaws.com/<repo>:latest
```

## 6. Capture the new SHA digest

```bash
NEW_SHA=$(sudo docker inspect \
  --format='{{index .RepoDigests 0}}' \
  <account>.dkr.ecr.<region>.amazonaws.com/<repo>:latest \
  | cut -d'@' -f2)
echo "New digest: $NEW_SHA"
```

## 7. Update Lambda — pin to digest, not tag

Always deploy by digest (not `:latest` tag) so the deployed version is immutable and auditable:

```bash
AWS_PROFILE=<profile> aws lambda update-function-code \
  --function-name <function-name> \
  --image-uri <account>.dkr.ecr.<region>.amazonaws.com/<repo>@${NEW_SHA} \
  --region <region>
```

## 8. Verify

```bash
# Wait for update to complete
AWS_PROFILE=<profile> aws lambda wait function-updated \
  --function-name <function-name> --region <region>

# Confirm new digest is live
AWS_PROFILE=<profile> aws lambda get-function \
  --function-name <function-name> --region <region> \
  --query 'Code.ImageUri' --output text
```

## Gotchas

- **`--platform linux/amd64`** is required when building on Apple Silicon — Lambda runs amd64
- The `docker login` context used for pull must match the one used by `docker pull` (root vs user)
- `:latest` tag is mutable — always record and deploy the `sha256:` digest for auditability
- `aws lambda wait function-updated` blocks until the update propagates (usually < 30s)
