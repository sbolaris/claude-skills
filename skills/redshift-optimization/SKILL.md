---
name: redshift-optimization
description: "Audit, benchmark, and migrate Redshift tables with DISTKEY and SORTKEY, including COPY JOB handling around schema migrations."
tags: [redshift, sql, performance, distkey, migration]
---

# Redshift Optimization — Query + Schema

Patterns for auditing, benchmarking, and migrating Redshift tables with DISTKEY/SORTKEY.
Written against an analytics schema of per-run and per-well assay tables.

---

## Workflow Overview

1. Capture schema baseline (rollback safety)
2. Apply query-level code fixes
3. Benchmark before/after (Redshift Data API — no VPC needed)
4. Apply DISTKEY/SORTKEY migration via CTAS
5. Re-benchmark to show combined improvement

---

## Schema Capture (`capture_schema.py`)

Use `information_schema.columns` — NOT `pg_table_def`.  
`pg_table_def` is session-schema-aware and returns 0 rows when the Data API runs with the default search_path (which doesn't include application schemas).

```python
# Works via Data API:
SELECT table_name, column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_schema = 'ddpcr_schema'
ORDER BY table_name, ordinal_position

# Also works:
SELECT * FROM svv_table_info WHERE schema = 'ddpcr_schema'

# Does NOT work via Data API (returns 0 rows):
SELECT * FROM pg_table_def WHERE schemaname = 'ddpcr_schema'
```

---

## Query-Level Optimizations

### 1. Parameterized queries (SQL injection prevention + plan caching)
```python
# Before (f-string — insecure, no plan caching):
sql = f"SELECT * FROM ddpcr_schema.peak_info WHERE plate_uuid = '{uid}'"
cursor.execute(sql)

# After:
cursor.execute(
    "SELECT plate_uuid, peak_data_name, id, widths, timestamps FROM ddpcr_schema.peak_info WHERE plate_uuid = %s",
    [uid]
)
```

### 2. Explicit column lists
- `peak_data` has 90+ columns; SELECT * returned 69KB per plate, explicit columns returns 3KB — **94% data reduction**, 543ms → 29ms
- `peak_info` and `droplets` only have 11/4 columns — SELECT * vs explicit makes little difference; data volume is the bottleneck

### 3. Remove duplicate queries
- Multiple callers were running the same `run_info` query twice per request (different dict keys, same SQL)
- Fix: deduplicate in the query dict; one key, one execution

### 4. Query dict pattern for selective loading
```python
QUERY_DICT = {
    'wellSamples':    "SELECT well_index, sampleids FROM ddpcr_schema.wellsamples WHERE plate_uuid = %s",
    'peakInfo':       "SELECT plate_uuid, peak_data_name, id, widths, ... FROM ddpcr_schema.peak_info WHERE plate_uuid = %s",
    'droplets':       "SELECT cluster_id, plate_uuid, peak_metadata_name, droplet FROM ddpcr_schema.droplets WHERE plate_uuid = %s",
    # ...
}

def get_table(uid, env, tables=None):
    tables = tables or list(QUERY_DICT.keys())
    results = {}
    for table in tables:
        cursor.execute(QUERY_DICT[table], [uid])
        results[table] = cursor.fetch_dataframe()
    return results
```
Lambda only runs the queries it actually needs — don't fetch all tables on every call.

---

## DISTKEY / SORTKEY Migration

### When to use DISTKEY
- Tables with `DISTSTYLE ALL` are replicated to every node — fine for small lookup tables (<100MB), wasteful for large fact tables
- Apply `DISTKEY(plate_uuid)` to high-volume tables where queries always filter by `plate_uuid`
- The join key and the filter key should be the same as the distkey

### CTAS migration pattern (safe, zero-downtime rename)
```python
# 1. Count source
source_count = get_row_count(table)

# 2. CTAS with new dist/sort
CREATE TABLE {schema}.{table}_new
    DISTKEY(plate_uuid)
    SORTKEY(plate_uuid, peak_data_name)
AS SELECT * FROM {schema}.{table}

# 3. Verify
new_count = get_row_count(f"{table}_new")
assert new_count == source_count

# 4. Atomic rename
ALTER TABLE {schema}.{table}     RENAME TO {table}_backup
ALTER TABLE {schema}.{table}_new RENAME TO {table}
```

CTAS automatically applies Redshift compression encodings — no need to write explicit DDL per column.

### Rollback
```python
ALTER TABLE {schema}.{table}        RENAME TO {table}_new   # move migrated aside
ALTER TABLE {schema}.{table}_backup RENAME TO {table}       # restore original
DROP TABLE  {schema}.{table}_new                            # discard migrated
```

### Migration targets for ddpcr_schema
```python
MIGRATION_TARGETS = [
    ("peak_info",                       "plate_uuid", "plate_uuid, peak_data_name"),
    ("droplets",                        "plate_uuid", "plate_uuid, peak_metadata_name"),
    ("peak_data",                       "plate_uuid", "plate_uuid, peak_data_name"),
    ("run_info",                        "plate_uuid", "ingest_date, plate_uuid"),
    ("clusters",                        "plate_uuid", "plate_uuid, peak_metadata_name"),
    ("peak_metadata",                   "plate_uuid", "plate_uuid, peak_metadata_name"),
    ("allavailablecolorcompensations",  "plate_uuid", "plate_uuid, peak_data_name"),
    ("autothreshold",                   "plate_uuid", "plate_uuid, peak_metadata_name"),
    ("threshold",                       "plate_uuid", "plate_uuid, peak_metadata_name"),
]
# Small lookup tables (ddplt, wellsamples, qc_plates, serial_number, etc.) keep DISTSTYLE ALL
```

---

## Benchmarking via Redshift Data API

```python
import boto3, time

def run_query_timed(client, cluster, database, db_user, sql, args=None):
    # Replace %s placeholders with quoted values for Data API (no native parameterization)
    if args:
        for arg in args:
            sql = sql.replace("%s", f"'{arg}'", 1)
    stmt_id = client.execute_statement(
        ClusterIdentifier=cluster, Database=database, DbUser=db_user, Sql=sql
    )["Id"]
    # poll until FINISHED
    while True:
        desc = client.describe_statement(Id=stmt_id)
        if desc["Status"] == "FINISHED":
            duration_ms = desc["Duration"] / 1_000_000  # nanoseconds → ms
            rows = desc["ResultRows"]
            size = desc["ResultSize"]
            return duration_ms, rows, size
        time.sleep(1)
```

`Duration` in describe_statement is nanoseconds. `ResultRows` and `ResultSize` (bytes) also available.

---

## Results Observed (dev, 16.8M rows peak_info)

| Optimization | Total time | vs baseline |
|---|---|---|
| Baseline (old code + DISTSTYLE ALL) | 40,798ms | — |
| Code changes only (explicit cols, parameterized, dedup) | 24,533ms | **−39.9%** |
| DISTKEY only (old code + new schema) | 26,613ms | **−34.8%** |
| Both combined | 22,655ms | **−44.5%** |

Key wins:
- `peak_data`: 543ms → 158ms (71%) — explicit columns cut payload 23×
- `droplets`: 16,478ms → 7,906ms (52%) — DISTKEY co-location
- `peak_info`: 22,728ms → 14,221ms (37%) — DISTKEY co-location
- All small tables: ~90ms → ~29ms (67%) — parameterized plan caching

Note: dev has 16.8M rows. Test has 869M rows (peak_info) + 1.29B rows (droplets).
DISTKEY benefit scales with data volume — expect larger % gains on test.

---

## Secret key inconsistency
Some Secrets Manager secrets use `host`, others `db_host`. Normalize:
```python
host = creds["db_host"] if "db_host" in creds else creds["host"]
```
