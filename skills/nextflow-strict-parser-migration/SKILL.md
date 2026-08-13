---
name: nextflow-strict-parser-migration
description: "Fix Nextflow pipelines that start failing CI lint after a version bump enables the strict config and workflow parsers. Use for errors like 'Unexpected input', 'Variable declarations cannot be mixed with config statements', 'Unrecognized config option', or 'No such variable'."
tags: [nextflow, migration, parser, ci, lint]
---

# Skill: Nextflow Strict Parser Migration

**When to use:** A previously-working Nextflow pipeline starts failing CI lint with parser errors after a Nextflow version bump — typically when `nf-core/setup-nextflow@v2` (or any pin past 24.04) installs a newer Nextflow that enables the strict config and workflow language parsers by default. Symptoms include `Unexpected input: '('`, `Variable declarations cannot be mixed with config statements`, `Statements cannot be mixed with script declarations`, `Unrecognized config option`, `No such variable: <input_name>`. Also useful when authoring new Nextflow code targeting current versions to skip the legacy idioms entirely.

**Bottom line:** the new parsers reject most imperative Groovy idioms that legacy `.config` and `.nf` scripts relied on. Fixes are mechanical and behavior-preserving.

---

## Symptom → fix lookup

Use this table to triage an error message in one pass.

| Error | Location | Idiom that breaks | Fix |
|---|---|---|---|
| `Unexpected input: '('` at `def fn(args) {` | `.config` | Top-level method declaration | Convert to closure: `fn = { args -> body }` |
| `Variable declarations cannot be mixed with config statements` | `.config` | `def name = value` at top level | Drop `def`: `name = value` |
| `If statements cannot be mixed with config statements` | `.config` | Top-level `if (...)` wrapping config blocks | Flatten — inline the condition as a property (`enabled = !params.notrace`) or drop the wrapper entirely |
| `Unrecognized config option 'foo.bar'` | `.config` | Custom/deprecated top-level scope | Remove; usually dead code (e.g. `params_description { path = ... }`) |
| `Statements cannot be mixed with script declarations` at `def NAME = value` | `.nf` | Top-level binding in a workflow script | Wrap in a function: `def name() { return value }` |
| `Unexpected input: 'x'` at `(double) x` | `.nf` | C-style cast | Use `x as double` (preserve precedence with parens: `((double) a.b()) / c` → `(a.b() as double) / c`) |
| `No such variable: <input_name>` from `tag`/`publishDir` line | `.nf` | Directive string with eager interpolation of a process input | Wrap in closure: `tag { "${input}" }`, `publishDir { "${params.x}/${input}" }, mode: 'copy'` |
| Reference to a top-level binding (e.g. `${reg}`) "not defined" inside a nested `process {}` or `withName: {}` closure | `.config` | Script-level binding doesn't propagate | Inline the value (`${params.container_registry}`) everywhere; only `params.*` and `task.*` are reliably propagated |

---

## What's still allowed at top level

After cleanup, every top-level line in `nextflow.config` and `conf/*.config` should be one of:

- Block opener with no expression: `manifest {`, `params {`, `process {`, `profiles {`, `timeline {`, `report {`, `trace {`, `dag {`, custom-named blocks
- `includeConfig 'path'` — unconditional
- Scoped property assignment: `process.executor = 'awsbatch'`, `aws.region = 'us-west-2'`
- Plain assignment without `def`: `name = value` (note: doesn't propagate into nested closures)
- Closure assignment: `name = { args -> ... }` (same propagation caveat)

In `.nf` files, top level allows only:
- `nextflow.enable.dsl = 2`
- `include { ... } from '...'`
- `def fn(args) { body }` — function declarations are explicitly allowed
- `process foo { ... }` and `workflow foo { ... }` blocks (named or unnamed)

**Anything else needs to live inside a function, process, or workflow.**

---

## Inlining the `check_max` pattern

Many legacy Nextflow pipelines (nf-core templates pre-2024) use:

```groovy
// nextflow.config
def check_max(obj, type) { ... }

// conf/base.config
process {
    cpus   = { check_max(2 * task.attempt, 'cpus') }
    memory = { check_max(8.GB * task.attempt, 'memory') }
    time   = { check_max(4.h * task.attempt, 'time') }
}
```

Both halves break under the strict parser (method declaration + non-propagating binding). Inline the cap-min logic at each call site — closure bodies still allow `def`, `?:`, etc.:

```groovy
process {
    cpus   = { Math.min(2 as int, params.max_cpus as int) }
    memory = { def req = 8.GB * task.attempt
               def cap = params.max_memory as nextflow.util.MemoryUnit
               req > cap ? cap : req }
    time   = { def req = 4.h * task.attempt
               def cap = params.max_time as nextflow.util.Duration
               req > cap ? cap : req }
}
```

`params.max_*` propagates into the closure correctly. The try/catch fallbacks in the original `check_max` only guarded against unset `params.max_*` — which is never the case in practice if defaults are set in `conf/base.config`.

---

## The directive-closure rule

Process directives like `tag` and `publishDir` are evaluated **eagerly** when the script loads, before input variables exist:

```groovy
// FAILS — input var resolved at parse time, not process-execute time
process foo {
    tag "${name}"
    publishDir "${params.outDir}/Sample_Files/${name}/foo", mode: 'copy'
    input: tuple val(name), path(reads)
    ...
}
```

Wrap each in a closure to defer evaluation:

```groovy
// WORKS
process foo {
    tag { "${name}" }
    publishDir { "${params.outDir}/Sample_Files/${name}/foo" }, mode: 'copy'
    ...
}
```

Pure-params directives (`publishDir "${params.outDir}/static"`) work without a closure because `params.*` is in scope at load time — but wrap them anyway for consistency and to future-proof against any new params-evaluation changes.

---

## Local repro of the CI lint job

CI typically runs four checks. Replicate locally before pushing:

```bash
# Install Nextflow (Java 17 prerequisite)
sudo apt-get install -y openjdk-17-jre-headless
curl -s https://get.nextflow.io | bash    # or wget into /tmp/nextflow

# 1. Help message parses + exits 0
./nextflow run main.nf --help

# 2. Config parses for each profile
./nextflow config main.nf -profile docker > /dev/null
./nextflow config main.nf -profile singularity > /dev/null

# 3. Any guard tests (e.g. genome-allowlist enforcement)
./nextflow run main.nf --pipeline complete --genome <bad> \
    --reads 'NO_READS' --genomesIgnore true --outDir ./test_out \
    2>&1 | grep -q "<expected-error-fragment>" && echo PASS || echo FAIL
```

Iterate locally — each failing message points at one line, follow the symptom→fix table above. Don't dispatch SQA for the first error; only when the audit needs to be exhaustive across dozens of files (e.g. the directive-closure wrap across every module).

---

## Audit commands

```bash
# Top-level statements in .config (should be empty)
grep -nE "^(def |if |for |while |try )" nextflow.config conf/*.config

# Top-level statements (not function decls) in .nf (should be empty)
find . -name '*.nf' -not -path './.git/*' | while read f; do
  awk '/^def [a-zA-Z_][a-zA-Z0-9_]* = / {print FILENAME":"NR": "$0}' "$f"
done

# C-style casts anywhere in .nf
grep -rn '(\(double\|int\|long\|float\|String\|Integer\|MemoryUnit\|Duration\)) ' --include='*.nf' .

# Directive lines that reference non-params/task vars
find . -name '*.nf' -not -path './.git/*' | while read f; do
  awk '/^[[:space:]]+(tag|publishDir) "/ {
    if ($0 ~ /\$\{[^}]*\}/ &&
        !($0 ~ /^[^$]*\$\{params\.[^}]*\}[^$]*$/) &&
        !($0 ~ /^[^$]*\$\{task\.[^}]*\}[^$]*$/))
      print FILENAME":"NR": "$0
  }' "$f"
done
```

The third audit returns lines that mix `${params.X}` with input vars (`$name`, `${genome_name}`, etc.) — those need closure wrapping. Pure-params lines are matched too because they have `${params.X}` interpolation; filter those out by hand or wrap anyway.

---

## When delegating to an agent

Dispatching SQA for the directive-closure sweep is worthwhile because there are 20+ files with 60+ lines to change mechanically and a clear pattern. For the single-line fixes (one cast, one top-level `def`), fix inline — dispatching has more overhead than the fix.

Always include in the agent brief:
- The exact error message format (so they can search for the failing class)
- The verified working transform (with before/after example)
- The exhaustive line list from the audit grep (don't make them re-discover)
- The verification commands to run after (`nextflow run main.nf --help`, `pytest tests/`)
- The "stop conditions" — if a NEW error class appears, stop and report; don't fix speculatively
