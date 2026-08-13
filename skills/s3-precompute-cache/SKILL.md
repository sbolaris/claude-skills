---
name: s3-precompute-cache
description: "Pre-compute expensive query results to S3 during an ingestion pipeline and serve them as presigned URLs from a Flask/Zappa API, replacing live per-request database queries."
tags: [s3, caching, redshift, flask, presigned-urls]
---

# S3 Pre-compute Cache Pattern

Pre-compute expensive query results to S3 during an ingestion pipeline; serve them as presigned URLs from a Flask/Zappa API. Eliminates live Redshift/DB queries on every UI request.

## When to use

- Endpoints that run the same expensive query per-item (e.g. per well, per run) and return large result sets
- Data is stable after ingestion — recompute on re-ingest via cache invalidation
- Acceptable to fail gracefully (return error to UI) on cold miss rather than fall back to live query

## Architecture

```
Ingestion pipeline (Step Functions)
  → [existing ingestion states]
  → Pre-compute Cache State (new, non-blocking)   ← Lambdas write JSON to S3
  → [rest of pipeline]

API (Flask/Zappa)
  GET /graph/twod/<uuid>/<well>
    → s3.head_object  (raises ClientError if miss)
    → generate_presigned_url
    → return {"signedUrl": "..."}
    except → 503 with user-facing error message
```

## Lambda Container Structure

Each compute type gets its own container under `analysis/docker/graph_cache_{type}/`:

```
Dockerfile
lambda.py           # handler: read DB → transform → s3.put_object
transforms.py       # pure data transform functions (no I/O)
redshift_connect.py # DB connection via Secrets Manager
requirements.txt    # pandas, redshift-connector, boto3
builder.sh
```

**Dockerfile** — use latest Lambda Python base:
```dockerfile
FROM public.ecr.aws/lambda/python:3.12

COPY lambda.py .
COPY transforms.py .
COPY redshift_connect.py .
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

CMD [ "lambda.handler" ]
```

**lambda.py** pattern:
```python
import json, boto3
import transforms, redshift_connect

def handler(event, context):
    plate_uuid = event["plate_uuid"]
    well       = event["well"]
    bucket     = event["bucket"]
    env        = bucket.split("-")[2]   # derive env from bucket name convention

    data = redshift_connect.get_data(plate_uuid, well, env)
    json_data = transforms.compute(data)

    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=f"graph-cache/{plate_uuid}/{well}/{TYPE}.json",
        Body=json_data,
        ContentType="application/json",
    )
    return {"success": True}
```

**redshift_connect.py** — Secrets Manager pattern:
```python
import json, boto3, redshift_connector

SECRET_NAMES = {
    "prod": "<project>-<region>-datalake-prod-redshift-db-creds",
    "test": "<project>-<region>-datalake-test-redshift-db-creds",
    "dev":  "<project>-<region>-datalake-dev-redshift-db-creds",
}

def _get_conn(env):
    client = boto3.client("secretsmanager")
    creds = json.loads(client.get_secret_value(SecretId=SECRET_NAMES[env])["SecretString"])
    redshift_connector.paramstyle = "format"
    return redshift_connector.connect(
        host=creds["host"], database=creds["db_name"],
        user=creds["username"], password=creds["password"],
    )

def get_data(uid, well, env):
    conn = _get_conn(env)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schema.table WHERE uuid = %s AND well = %s", [uid, well])
    df = cursor.fetch_dataframe()
    conn.close()
    return df
```

**containers.tsv** — add one row per Lambda:
```
docker/graph_cache_twod    myorg/graph_cache_twod       lambda
```

## S3 Key Schema

```
s3://{BUCKET}/graph-cache/{uuid}/{well}/{graph_type}.json
```

Derive env from bucket name: `bucket.split("-")[2]` → `dev` / `test` / `prod`

## Flask/Zappa Endpoint Pattern

```python
GRAPH_CACHE_PRESIGN_TTL = int(os.environ.get("GRAPH_CACHE_PRESIGN_TTL", 3600))

def _graph_cache_key(uuid, well, graph_type):
    return f"graph-cache/{uuid}/{well}/{graph_type}.json"

def _try_graph_cache(uuid, well, graph_type):
    s3     = boto3.client("s3")
    bucket = app.config["S3_BUCKET_DATA"]
    key    = _graph_cache_key(uuid, well, graph_type)
    s3.head_object(Bucket=bucket, Key=key)   # raises ClientError if object missing
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=GRAPH_CACHE_PRESIGN_TTL,
    )

@app.route("/graph/twod/<string:uuid>/<string:well>")
def plot2d(uuid, well):
    try:
        return json.dumps({"signedUrl": _try_graph_cache(uuid, well, "twod")})
    except Exception as e:
        app.logger.exception(e)
        return apiOutput({}, "Graph data not yet available. Please retry after ingestion completes.", 503)
```

`head_object` raises `botocore.exceptions.ClientError` on 404 — no explicit `if url is None` check needed.

## Step Functions Integration

See `stepfunctions-nonblocking-postprocess.md` for the ASL pattern to add this as a non-blocking step in an existing ingestion state machine.

## Cache Invalidation

Add S3 delete to the re-ingest path:
```python
def _delete_graph_cache(plate_uuid, bucket):
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"graph-cache/{plate_uuid}/"):
        for obj in page.get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
```

Call at the end of `drop_if_exists()` in the ingestion Lambda.

**Note:** If the ingestion container uses a Conda base image (`condaforge/mambaforge`), add `boto3` to the conda env YAML, not `requirements.txt`.

## IAM Additions

| Role | Permissions | Resource |
|------|-------------|----------|
| Graph cache Lambdas | `s3:PutObject`, `secretsmanager:GetSecretValue` | `graph-cache/*` prefix |
| Flask API role | `s3:HeadObject`, `s3:GetObject`, `s3:GeneratePresignedUrl` | `graph-cache/*` prefix |
| Ingest Lambdas | `s3:ListBucket`, `s3:DeleteObject` | `graph-cache/*` prefix |

## Key Gotchas

- **`Unnamed: 0` column**: only present in CSV-sourced DataFrames, not Redshift results. Use `errors='ignore'` on any `drop()` that references it.
- **`eval(x)` in cluster results**: Redshift stores Python list literals as strings. Safe for internal data but note it is brittle.
- **Lambda config**: timeout 300s, memory 1024 MB, reserved concurrency ~20 per function (prevents stampede on 96-well plate load).
- **Env from bucket name**: `bucket.split("-")[2]` assumes naming convention `{org}-{service}-{env}`. Document this assumption.
