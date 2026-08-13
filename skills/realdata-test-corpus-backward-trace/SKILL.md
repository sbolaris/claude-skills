---
name: realdata-test-corpus-backward-trace
description: "Assemble a real-data test corpus by tracing backwards from the data warehouse to the source files in S3. Use when a bug only reproduces on production-shaped data and synthetic mocks cannot trigger it."
tags: [testing, test-data, redshift, s3, methodology]
---

# Real-data test corpus — backward-trace from warehouse to S3

When a bug fix is hard to exercise with synthetic mocks (multi-channel data, vendor format edge cases, accumulated production-only quirks), assemble a real-data corpus by tracing backwards from the data warehouse to the source files. This pattern beats hand-crafting mocks for any pipeline where bugs hide in the *long tail* of inputs.

## When to reach for this

- The unit tests use clean mocks, but the bug only triggers on production-shaped data.
- Production files are too varied to enumerate by hand; you want a representative sample.
- The downstream warehouse has columns that flag the property you care about, even if the upstream files themselves are scattered across S3.
- You're shipping a schema change or PK fix and need a regression guard that survives next quarter's ingest format drift.

## Steps

### 1. Identify the property column in the warehouse

Find a column whose value isolates the bug case. For a multi-channel primary-key fix, that was `analytics.run_info.configured_channel_count >= 4`. For an encoding fix it might be `file_size > 100MB` or `software_version LIKE 'v1.7%'`. The column is rarely "exactly the bug" — usually a strong proxy.

### 2. Join downstream tables to filter for files that *actually* exercise the bug

The configuration column often lies for legacy data. Runs marked 4-channel in `run_info` can still emit 2-channel threshold arrays if exported by an older version of the vendor tool. Join with the table that holds the parsed downstream data:

```sql
SELECT ri.plate_uuid, ri.data_filename, ri.configured_channel_count AS nch,
       COALESCE(pm.well_count, 0) AS wells,
       COALESCE(th.threshold_rows, 0) AS thresh_rows
FROM   ddpcr_schema.run_info ri
LEFT JOIN (SELECT plate_uuid, COUNT(*) AS well_count
           FROM ddpcr_schema.peak_metadata GROUP BY plate_uuid) pm
  ON pm.plate_uuid = ri.plate_uuid
LEFT JOIN (SELECT plate_uuid, COUNT(*) AS threshold_rows
           FROM ddpcr_schema.threshold GROUP BY plate_uuid) th
  ON th.plate_uuid = ri.plate_uuid
WHERE  ri.configured_channel_count >= 4
  AND  ri.data_filename NOT LIKE '%dyecal%'      -- exclude calibration noise
  AND  ri.data_filename NOT LIKE '%converted%'   -- exclude synthetic test data
ORDER BY th.threshold_rows DESC NULLS LAST
LIMIT 20;
```

The `ORDER BY threshold_rows DESC` is the key trick — it ranks plates by how *much* they exercise the buggy code path, not just by file age.

### 3. Use Redshift Data API to avoid VPC tunnels

If the cluster is in a private VPC (`tcp/5439` blocked from your workstation), use the AWS control plane:

```bash
SID=$(aws redshift-data execute-statement \
  --cluster-identifier <cluster> --database <db> --db-user <user> \
  --sql "$QUERY" --region us-west-2 --query 'Id' --output text)

# poll
for i in {1..10}; do
  STATUS=$(aws redshift-data describe-statement --id "$SID" --region us-west-2 \
    --query 'Status' --output text)
  [ "$STATUS" = "FINISHED" ] && break
  [ "$STATUS" = "FAILED" ] && { aws redshift-data describe-statement --id "$SID" --region us-west-2 --query 'Error' --output text; exit 1; }
  sleep 3
done

aws redshift-data get-statement-result --id "$SID" --region us-west-2 > /tmp/q.json
```

Results come back as a JSON `Records` array of typed cells (`{"stringValue": "..."}`, `{"longValue": 4}`, `{"isNull": true}`). Use Python rather than `--output text` to parse — `text` collapses NULL/typed cells incorrectly.

`describe-table` (also Data API) gives the column list when you can't recall the schema.

### 4. Map DB filenames to S3 keys

Warehouse `data_filename` is often normalized (lowercase, kebab-case, no extension). The S3 key is the original (mixed case, spaces, with `.ddpcr`/`.ddpcrone`/etc.). Bridge with substring matching on a distinctive token:

```bash
for token in "david-dobnik-1" "xm2023-12-11" "pik282"; do
  aws s3api list-objects-v2 --bucket <bucket> --prefix "processed/" \
    --query "Contents[?contains(to_string(Key), '${token}')].[Size,Key]" \
    --output text
done
```

`contains(to_string(Key), ...)` is the JMESPath bit that does substring matching. Try both dash and underscore variants if your normalization is unclear.

### 5. Download a small sample and verify each fixture exercises the bug

5 files spanning the range usually beats 50 files of the same type. For each file, run the actual parser and verify the property at the leaf level — not just at the DB summary:

```python
for src in fixtures:
    extract(src, tmp_dir)
    for meta in glob.glob(f"{tmp_dir}/**/*.metajson", recursive=True):
        d = json.load(open(meta))
        outer_len = len(d.get('threshold_values') or [])
        # compare against what the DB said about this plate
```

This step **always** surfaces interesting findings: legacy files where the DB's channel count doesn't match the actual parsed threshold-array length; files where the property is present in the column but the downstream JSON is empty; files where the format changed mid-history. Save those findings to project memory.

### 6. Write the test with three-layer assertions

A real-data test that just runs the parser on fixtures will pass forever even if you delete every relevant file. Three assertions layer in regression-proof behavior:

```python
def test_at_least_one_plate_has_more_than_two_channels(self):
    """Fixture-rot guard — fail loud if the corpus stops covering the case."""
    self.assertTrue(any(
        max((len(tv) for _, tv in wells), default=0) >= 3
        for wells in self.plate_data.values()))

def test_new_pk_unique_across_every_well(self):
    """The fix's central guarantee on real data."""
    for plate, wells in self.plate_data.items():
        for well, tv in wells:
            rows = list(build_threshold_rows(tv, plate, well))
            pks = [(r["threshold_id"], r["channel_id"],
                    r["Plate_UUID"], r["Peak_Metadata_Name"]) for r in rows]
            self.assertEqual(len(pks), len(set(pks)))

def test_old_pk_would_have_collided_on_multi_channel_wells(self):
    """Prove the fixture has BITE — pre-fix logic must collide somewhere."""
    witnesses = 0
    for _, wells in self.plate_data.items():
        for well, tv in wells:
            if sum(1 for ch in tv if ch) < 2:
                continue
            old_pks = [(r["threshold_id"], r["Plate_UUID"], r["Peak_Metadata_Name"])
                       for r in build_threshold_rows(tv, "p", well)]
            if len(old_pks) != len(set(old_pks)):
                witnesses += 1
    self.assertGreater(witnesses, 0)
```

The third assertion is the easy one to skip and the most important one. Without it, the central-guarantee test is meaningless — *of course* mocked PKs don't collide; the question is whether the corpus actually contains data that would have collided pre-fix.

Plus two sanity assertions (contiguous IDs from zero) — cheap, catch off-by-one regressions.

### 7. Skip-unless guards for CI without data access

CI without AWS context should not fail this test — it should skip. Use `unittest.skipUnless` at the class level with two probes:

```python
@unittest.skipUnless(FIXTURES, f"no fixtures in {CORPUS_DIR}")
@unittest.skipUnless(PASSWORDS, "no unlock passwords available")
class MultiChannelThresholdCorpusTests(unittest.TestCase):
    ...
```

Where:
- `FIXTURES = sorted(glob.glob(...))` over an env-overridable `ONE_TOOL_FIXTURES_DIR`
- `PASSWORDS = _load_passwords()` — try env var first (`DDPCR_PASSWORDS` as JSON list), fall back to Secrets Manager, swallow boto3 import errors, return `[]` on any failure.

Verify the skip path works locally before committing:
```bash
ONE_TOOL_FIXTURES_DIR=/nonexistent python -m unittest test_threshold_real_data
# → "OK (skipped=5)"
```

### 8. Save findings to memory

The DB-vs-reality discrepancies discovered in step 5 are the most valuable artifact of this exercise. Future-you (or another agent) will not re-derive them. Save with `Why:` and `How to apply:` so the lesson outlives the codebase:

> `run_info.configured_channel_count` is the setup-time channel count, but the parser walks the threshold array out of each well's per-well metadata file. Older exports stored only a subset of the lanes regardless of configured channels. **How to apply:** when picking fixtures for multi-channel tests, filter by *extracting and inspecting* the parsed threshold array, not the configured count.

## Encrypted fixture pattern

Many vendor formats are password-encrypted 7z archives. Pull the unlock secret at test time rather than committing it:

```python
def _load_passwords():
    raw = os.environ.get("DDPCR_PASSWORDS")
    if raw:
        return json.loads(raw) if raw.startswith("[") else \
               [p.strip().strip("'\"") for p in raw.strip("[]").split(",")]
    try:
        import boto3
        client = boto3.session.Session().client(
            "secretsmanager", region_name=SECRET_REGION)
        secret = json.loads(client.get_secret_value(SecretId=SECRET_NAME)["SecretString"])
        cred = secret.get("ddpcr_cred_string", "")
        return json.loads(cred.replace("'", '"')) if cred.startswith("[") else []
    except Exception:
        return []  # caller's skipUnless handles the empty case
```

The env-var fallback lets the test run in environments without AWS creds (developer laptops with a temp local secret, GitHub Actions with a context-injected secret, etc.).

## Anti-patterns to avoid

- **"I'll just write a richer mock."** Real production data has weird shapes you won't guess. Mocks pass the test and miss the bug.
- **Committing the fixtures to the repo.** 142 MB of `.ddpcr` files bloats clones forever. Keep them outside the tree, point the test at an env-overridable path.
- **Skipping the "old code would have collided" assertion.** Without it, the test passes on any non-empty fixture — even a corpus that doesn't contain the bug.
- **Ordering by date instead of by bug-exercising density.** The most recent plates are often the ones with the cleanest data — the *oldest* plates with the most threshold rows are the ones most likely to surface format drift.
- **Trusting the warehouse summary column.** Always verify at the leaf-file level.

## Cross-references

- `vendor-format-round-trip-diff.md` — companion methodology for reverse-engineering the vendor formats whose quirks you're testing.
- `redshift-optimization.md` — Data API benchmarking and query patterns.

## Trigger keywords

"real-data test corpus", "backward trace from warehouse", "fixture-rot guard", "old code would have collided", "Redshift Data API select", "encrypted fixture", "skipUnless corpus", "find files that exercise this bug".
