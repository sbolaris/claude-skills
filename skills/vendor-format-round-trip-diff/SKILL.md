---
name: vendor-format-round-trip-diff
description: "Reverse-engineer an undocumented vendor file format by diffing a vendor-native artifact against your converter's output field by field. Use when writing a converter whose output a closed-source tool must accept."
tags: [file-formats, reverse-engineering, converter, methodology, testing]
---

# Vendor Format Round-Trip Diff

When you're writing a converter that has to produce output a closed-source vendor tool will accept (or reading vendor output that has no published spec), the only reliable way to know what structure is expected is to compare a vendor-native artifact against your converter's output, field by field. This skill captures that methodology.

## When to use

- You have a converter producing format X but the consuming tool rejects, misreads, or silently mishandles it.
- The vendor format has no public schema (or the schema is partial/wrong).
- A reference file produced by the vendor itself is available — either provided by the user or downloadable.
- Test data round-trips through your converter and an authoritative reference.

If you have docs and they're current, read them first. This skill is for the no-docs case.

## What you need from the user

1. A native vendor file (the "reference") — produced entirely by the vendor's tool, no third-party touching.
2. Optionally: the same logical content run through your converter, so you can diff. If they don't have it, generate it yourself once you can run the converter.
3. Any unlock material (passwords, license keys, account profiles) needed to open the container.

Ask for these explicitly. Don't try to fabricate a reference — guessing the format defeats the point.

## Process

### 1. Open both containers

Vendor formats often ship as encrypted/compressed archives (7z, zip, custom wrappers). Standard libs may not handle them — you may need vendor-specific or password-aware libs (e.g. `py7zr` for encrypted 7z).

Look for the password in:
- AWS Secrets Manager (project-specific secret name)
- A README or onboarding doc the user can share
- The vendor's installer or registry keys (last resort, ask user)

If multiple passwords exist (legacy + current), try them in order on the reference file and remember which worked.

### 2. Inventory what's inside

Both archives may contain many files. List them, find the analogues, and build a mapping table:

```
reference/well_A01.json  ↔  converter_output/well_A01.json
reference/plate_meta.xml  ↔  (missing in converter output)
reference/charts/*.json   ↔  (missing — likely UI-only, defer)
```

Anything in the reference but not in your output is a candidate gap. Anything in your output but not in the reference is suspect (may break the consumer).

### 3. Field-by-field diff per record

For structured formats (JSON, XML), iterate every record/well/row and diff key-by-key. Build a divergence table per scenario:

| Scenario | Field | Reference | Converter | Notes |
|----------|-------|-----------|-----------|-------|
| No threshold | `TV` | `[]` | `[[t0],[t1]]` | Causes downstream PK collision |
| Single channel manual | `TK` | `[FAM,HEX]` | `[FAM,HEX]` | Order varies in reference based on which channel is set |
| Both channels auto | `IsManuallySet` | `false` | `true` | Hardcoded in converter |

Don't generalize from one well — sample multiple wells per scenario. A reference often has clusters of similar records and one outlier that reveals the real rule.

### 4. Identify shape rules vs value rules

- **Shape rules**: array length, key presence, null vs empty, ordering. These are usually load-bearing — wrong shape breaks the consumer.
- **Value rules**: hardcoded constants, computed defaults. Vendor often varies these by scenario; converters often hardcode. Look at what *changes* across reference records to learn the rule.

If the converter currently writes `[[t0],[t1]]` always but the reference writes `[[],[t]]` or `[[t],[]]` depending on which channel is thresholded — that's a shape rule and the consumer probably depends on it.

### 5. Watch for "matches by luck"

Two values may agree in your test sample because the test sample is uniform (e.g. all wells are fully manual, so TV and ATV happen to be identical). Don't conclude the fields are interchangeable — find a record where they should differ and check the reference. If you can't find one, flag it as an open question to resolve with a richer test file.

### 6. Capture container-level differences too

If the vendor uses encrypted 7z and you write plain zip, the consumer may reject the file before parsing. Verify the consumer opens your output before declaring success. Container differences are often the easiest fix and the easiest thing to overlook.

### 7. Phase the fix

Don't dump every fix into one PR. Phase it:

- **Phase 0**: surgical, behavior-correct fix that unblocks users (the immediate bug).
- **Phase A–G**: structural changes per divergence category (shape, hardcoded metadata, container format, ingestion-side fixes).
- **Phase final**: round-trip validation — convert through your fixed lambda, diff against reference, assert zero divergence on the documented scenarios.

This lets you ship Phase 0 fast and review structural changes carefully.

### 8. Open questions go in the plan, not the code

When the diff reveals something you can't answer (e.g. "does the vendor preserve original auto value alongside manual override?"), don't guess in the code. Add it to the plan as an open question and resolve it with a richer reference file — usually one with the specific scenario you're missing.

### 9. Cross-file compatibility sweep before declaring done

A single reference file teaches you one convention. The vendor may emit different conventions across machine generations, instrument modes, or software versions — and your "fix" may regress files you didn't see.

Before shipping, gather a corpus that spans every distinct lineage:

- Raw instrument output (each machine generation: QX100/QX200/QX600/QXOne)
- Older converter output (your previous version's artifacts still in S3)
- Vendor-tool-produced conversion (the target you're trying to match)
- Edge configurations (single-channel, multi-channel, EvaGreen vs FAM/HEX, empty wells)

Write a sweep script that for each file:

1. Detects format (try every known extraction method — encrypted 7z with each password, then zip)
2. Inventories per-record shape distribution (count occurrences of each `TV` shape, `TK` order, etc.)
3. Runs your new helper across every record and asserts the invariant you're protecting (e.g. PK uniqueness, key presence)
4. Reports counts: total records, shape distribution, helper failures

One real example from a ddpcr migration:

| File lineage | Distinct shapes seen | PK collisions |
|---|---|---|
| Raw QX200 (encrypted 7z) | `[0,1]×18, [1,0]×14, []×64` | 0 |
| Desktop conversion (encrypted 7z) | `[1,1]×96` | 0 |
| Older converter zip | `[1,1]×1` | 0 |
| Older instrument variant | `[0,1]×12, []×64, [0,0]×20` | 0 |

Discovering the `[0,0]` shape (both-channels-empty-list) only on one older instrument file would have justified a fallback case in your helper — and the sweep is what surfaces it. **One reference file is never enough.**

### 10. Downstream-consumer regression audit when removing fields

When making your converter output more vendor-faithful, you'll often *remove* fields the old output had but the vendor doesn't. Each removal is a potential hidden regression for downstream consumers (Redshift loaders, stats lambdas, dashboards, internal tools) that read your output and expected the field to be there.

Before shipping the trim, grep the entire downstream codebase for every removed/renamed key:

```bash
for key in <field-a> <field-b> <field-c> <field-d>; do
  grep -rn "['\"]${key}['\"]" downstream/ --include="*.py"
done
```

For each hit, **read the surrounding code** and classify:

- **Safe**: `.get(key, None)` with no further use, or wrapped in `if value is not None:` guard. The reader silently no-ops on absence.
- **Risky**: `str(vendor_info.get(key, None))` followed by `ast.literal_eval(...)` — the str-of-None becomes the string `"None"`, then `literal_eval` returns Python `None`, then iteration/indexing crashes.
- **Broken**: `vendor_info[key]` (direct subscript) — `KeyError` on absence.

Only "safe" reads can stay removed. For risky/broken consumers, either:
- Restore the field in your output (cheapest if the vendor tolerates unrecognized keys — usually true for permissive formats like JSON)
- Fix the consumer to handle absence (correct long-term, but expands PR scope)

One real example: a per-well histogram field was trimmed from the converter's output because the vendor's own desktop conversion doesn't emit it. But four downstream stats lambdas did `ast.literal_eval(peak_data["<that field>"].iloc[0])` and crashed on `None`. Restoring the field as an extra key (vendor tolerates extras) was a 1-line fix that kept both directions working.

**Anti-pattern:** trusting that `.get(key, None)` everywhere means absence is universally safe. The `.get` only protects the FIRST level; subsequent unwrap operations (`.iloc[0]`, `ast.literal_eval`, indexing) are where None becomes a crash.

## Output artifacts

A good round-trip diff session produces:

1. A divergence report (the table above) committed to the repo or memory.
2. A minimal reference file checked in as test data (with secrets stripped if applicable).
3. A round-trip integration test that opens both, diffs them, and fails on regression.
4. A list of open questions parked for the next reference file.

## Anti-patterns

- **Reading the vendor's source** when it's available but proprietary — legal/compliance risk. Stick to observable I/O.
- **Hardcoding "what works for my test file"** — you'll regress as soon as a different scenario shows up.
- **Skipping the diff and patching the symptom** — you'll fix one well type and break another.
- **Assuming the consumer is strict** when it might be lenient (or vice versa). Test by feeding your output back to the vendor's tool.

## Cross-references

- `lambda-container-audit.md` — for verifying deployed converter matches repo source.
- `s3-precompute-cache.md` — when converter output is consumed by downstream cache pipelines.
