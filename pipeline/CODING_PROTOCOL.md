# Coding Protocol (pipeline nodes N4–N7)

Read this in full before writing code. It is the same for every coding agent — Python, infra, front-end, Nextflow, WPF. Your own agent definition governs *how* you write code in your domain; this governs *the process* you follow inside the pipeline.

The orchestrator gives you `RUN_DIR` (the run-state directory) and `PLAN` (`$RUN_DIR/plan.md`). Read the plan and the evals before touching anything.

## N4 — Branch

```bash
git checkout -b <type>/<slug>      # feat/ fix/ refactor/ docs/ chore/
```

Branch off the repo's current default working branch, not necessarily `main` — check what the repo uses. Never commit to `main`/`master`. If the working tree is dirty when you start, **stop and report** rather than sweeping someone else's changes into your branch.

## N5 — Tests first (red)

One named test per `[auto]` acceptance criterion in `$RUN_DIR/evals/EVAL-*.md`. The mapping must be mechanical and obvious:

```
AC1 valid event writes exactly one row  →  test_valid_event_writes_one_row
AC2 malformed event routes to DLQ       →  test_malformed_event_routes_to_dlq
```

Run them. **They must fail**, and fail for the right reason — a test that errors on an import typo is not a red test, it is a broken test. Write the mapping and the failing output to `$RUN_DIR/code/tests-red.md`.

If an AC cannot be expressed as an automated test, say so explicitly in `tests-red.md` and propose the manual check instead of quietly skipping it.

Commit the tests on their own: `test: add failing tests for <task>`.

## N6 — Implement (green)

Make the tests pass. Constraints:

- **Only what the plan calls for.** No opportunistic refactors, no drive-by renames, no reformatting untouched files. If you spot something worth fixing that is out of scope, write it to `$RUN_DIR/code/followups.md` and leave the code alone.
- **Do not edit the tests to make them pass.** If a test is genuinely wrong, stop and say so in your report — changing the assertion to match your implementation defeats the entire exercise.
- **No new dependencies** without recording the reason in `$RUN_DIR/code/followups.md`.
- Match the surrounding code's conventions, comment density, and idiom.

Commit: `<type>: <what changed and why>`, ending with
`Co-Authored-By: Claude <noreply@anthropic.com>`

## N7 — Verify

Run all four checks and write results to `$RUN_DIR/code/verify.md`. Report failures honestly — a verify step that hides a red result poisons every gate downstream.

**1. Lint / format** — the repo's own toolchain (ruff, eslint, prettier, `terragrunt fmt`, `dotnet format`). Never introduce a new linter. If none is configured, say so.

**2. Eval harness** — run `$RUN_DIR/evals/eval_*.py`. Exit 0 means every `[auto]` AC passed. Paste the per-AC result table. **A red `[auto]` AC blocks the node** — you may not proceed to SQA.

**3. Change guard** — compare the actual diff against the PM's blast-radius estimate in `plan.md`:

```bash
git diff --stat <base>...HEAD
```

The guard **trips** if any of these is true:
- files touched > 3× `expected_files`
- net lines changed > 3× `expected_lines`
- any file deleted that the plan did not name
- any file renamed or moved that the plan did not name

On a trip: **stop immediately**, write the full diffstat to `$RUN_DIR/guard/diffstat.md`, and report `GUARD_TRIPPED` with the numbers. Do not continue and do not attempt to shrink the diff on your own — the orchestrator raises a human gate.

**4. Structure readability** — confirm the change left the tree navigable by a human:
- new files sit in the directory their siblings would predict
- no file grew past ~600 lines without a stated reason
- no generated, vendored, or `.env`-style file was committed
- the repo's documented layout still holds (e.g. each function in its own subfolder under `packages/functions/`)

## Bounce-backs from SQA (N8 → N6)

When SQA returns bugs you get the bug ledger and its report. Then:

1. Fix **only** the listed bugs. A bounce-back is not an invitation to revisit the design.
2. Every bug needs a **regression test that fails before your fix and passes after**. This is how the bug stays dead — record the test name against the bug ID.
3. Re-run all four N7 checks before handing back.
4. If you believe a reported bug is not a bug, do not silently ignore it — state your reasoning in your report and let SQA adjudicate.

The bounce cap is 3. On the third return the pipeline halts to a human gate, so if you are stuck, say clearly what is blocking you rather than trying another speculative fix.

## Context discipline

You have your own context window and the orchestrator does not see inside it — so what you spend is yours, but **what you return lands in the orchestrator's window and stays there for the rest of the run.**

- **Write artifacts to `$RUN_DIR`, return paths.** `tests-red.md`, `verify.md`, `diffstat.md`, `followups.md` all live on disk. Your final message references them; it does not reproduce them.
- **Never paste a diff, a file, or a full test log into your return.** Counts and the path are enough. The orchestrator re-reads only what it needs, and the next agent reads the file itself.
- **Read files at the paths you are given.** If a prompt hands you `$RUN_DIR/plan.md`, open it — do not ask for its contents to be repeated back to you.
- Everything the next node must know goes in `NOTES`, in a sentence or two. If it needs more than that, it belongs in a file under `$RUN_DIR`.

The same holds on a bounce-back: return what changed and the regression-test names, not the diff.

## Reporting

Your final message is consumed by the orchestrator, not read as prose. Return:

```
STATUS: GREEN | GUARD_TRIPPED | BLOCKED
BRANCH: <name>
COMMITS: <shas>
TESTS: <passed>/<total>   EVAL: <passed>/<total> [auto] ACs
GUARD: files <n>/<expected>  lines <n>/<expected>  verdict
FILES: <paths touched>
NOTES: <anything the next node must know>
```
