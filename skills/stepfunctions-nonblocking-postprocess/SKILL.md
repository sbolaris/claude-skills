---
name: stepfunctions-nonblocking-postprocess
description: "Add best-effort post-processing such as cache warming or stats computation to a Step Functions ingestion pipeline without letting its failures block the main flow."
tags: [step-functions, aws, pipelines, error-handling]
---

# Step Functions: Non-Blocking Post-Processing State

Add optional post-processing work (e.g. cache warming, stats computation) to an existing Step Functions ingestion pipeline without risking the main flow if the post-processing fails.

## When to use

- You need to run per-item work (e.g. per well) after the main ingestion writes to the DB
- The post-processing is best-effort — a failure should not block file movement or mark the run as failed
- You have item groups already split in the state machine (e.g. row groups A/B, C/D, E/F, G/H)

## Placement Rule

**Must run after** the state that writes the data the Lambdas will read from (e.g. after peak/metapeak ingestion).  
**Must run before** any state whose output replaces `$` — after that point, per-item path arrays (`ab_path`, `cd_path`, etc.) are gone.

```
[Data Ingestion Parallel]     ← writes DB rows
       ↓
[Post-Process Build]          ← NEW: reads DB, writes S3/cache (non-blocking via Catch)
       ↓
[Move / Cleanup]              ← output replaces $; per-item paths no longer available
       ↓
[Final Parallel: stats etc.]
```

## ASL Pattern

```json
"Post-Process Build": {
  "Type": "Parallel",
  "ResultPath": "$.postProcess",
  "Next": "Move File Ingested",
  "Catch": [
    {
      "ErrorEquals": ["States.ALL"],
      "Next": "Move File Ingested",
      "ResultPath": "$.postProcessError"
    }
  ],
  "Branches": [
    <one branch per item group — see below>
  ]
}
```

**Key fields:**
- `ResultPath: "$.postProcess"` — appends output without overwriting existing state data. Downstream states still see `$.output.UUID`, `$.output.ab_path`, etc.
- `Catch` with `ResultPath: "$.postProcessError"` — any branch failure is captured and the machine continues to the next state. The main pipeline is never blocked.

## Per-Item-Group Branch Pattern

Each branch: Check if group has items → Map over items → nested Parallel for concurrent task types.

```json
{
  "StartAt": "Check Post-Process AB",
  "States": {
    "Check Post-Process AB": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.output.ab_wells",
          "BooleanEquals": false,
          "Next": "Post-Process AB Pass"
        }
      ],
      "Default": "Run Post-Process AB"
    },
    "Post-Process AB Pass": { "Type": "Pass", "End": true },
    "Run Post-Process AB": {
      "Type": "Map",
      "ItemsPath": "$.output.ab_path",
      "Parameters": {
        "uuid.$":   "$.output.UUID",
        "well.$":   "$$.Map.Item.Value",
        "bucket.$": "$.output.Bucket"
      },
      "Iterator": {
        "StartAt": "All Task Types AB",
        "States": {
          "All Task Types AB": {
            "Type": "Parallel",
            "End": true,
            "Branches": [
              <one branch per Lambda type — see below>
            ]
          }
        }
      },
      "End": true
    }
  }
}
```

**`$$.Map.Item.Value`** — references the current item in the Map iteration (the well name string).  
**`Parameters` in Map** — remaps nested state paths into a flat shape for the Iterator to consume.

## Per-Lambda-Type Branch Pattern (inside the nested Parallel)

```json
{
  "StartAt": "Graph Cache twod AB",
  "States": {
    "Graph Cache twod AB": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:{region}:{account}:function:graph_cache_twod-dev",
      "Parameters": {
        "Payload": {
          "plate_uuid.$": "$.uuid",
          "well.$":       "$.well",
          "bucket.$":     "$.bucket"
        }
      },
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 30,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "End": true
    }
  }
}
```

**State name uniqueness**: Step Functions requires all state names to be unique within a branch scope. When repeating the same structure for multiple item groups (AB, CD, EF, GH), suffix state names with the group: `"Graph Cache twod AB"`, `"Graph Cache twod CD"`, etc.

## Validating the JSON

The ASL definition is a `.json.tmpl` file rendered by Terraform's `templatefile()`. Validate before applying:

```bash
python3 -c "
import json
f = open('lambda_definition_dev.json.tmpl')
content = f.read().replace('\${account}','123456789').replace('\${region}','us-west-2')
json.loads(content)
print('JSON valid')
"
```

## Data Flow: What's Available Where

| After state | Available in `$` |
|-------------|-----------------|
| Main Ingestion | `$.output.UUID`, `$.output.Bucket`, `$.output.ab_path`, `$.output.ab_wells`, … |
| Peaks Ingestion (`ResultPath: "$.completion"`) | All of above + `$.completion` |
| **Post-Process Build** (`ResultPath: "$.postProcess"`) | All of above + `$.postProcess` |
| Move/Cleanup (no ResultPath → replaces `$`) | Only what the cleanup Lambda returns: `$.uuid`, `$.detail`, `$.qc_stats` |
| Final Parallel | Only `$.uuid`, `$.detail`, `$.qc_stats` |

`ResultPath` preserves existing state; omitting it (or using `"ResultPath": "$"`) replaces it. Check the cleanup Lambda's return value before assuming what's available in the final states.
