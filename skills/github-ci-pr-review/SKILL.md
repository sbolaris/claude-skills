---
name: github-ci-pr-review
description: Diagnosing CI failures, fixing ruff lint, resolving merge conflicts, and managing PRs on GitHub
tags: [github, ci, pr, lint, ruff, git]
---

# GitHub CI / PR Review Workflow

Patterns for diagnosing CI failures, fixing lint, resolving merge conflicts, and cleaning up branches for PR merge.

---

## 1. Diagnosing a failing CI job

When a PR's Python unit tests fail in CI:

1. **Run tests locally first** — don't guess. Create a venv matching the CI Python version:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install <ci-deps>
   .venv/bin/pytest tests/ -v --tb=short
   ```

2. **Common mismatch: missing dependency in CI workflow.** If `conftest.py` fails to import at collection time, the error is `ImportError` / `ModuleNotFoundError` before any test runs. Grep all imports across `src/` and `tests/` to find what's needed:
   ```bash
   grep -r "^import\|^from" src/ tests/ --include="*.py" | sort -u
   ```
   Then compare against what the CI workflow installs. Fix the `pip install` line in `.github/workflows/ci.yml`.

3. **Example fix:** `src/genome_build/txt2fasta.py` imported `Bio.SeqIO` (biopython), but CI only installed `pytest pandas`. Added `biopython` to the install step.

---

## 2. Running ruff lint to match CI

Match the exact ruff invocation in the CI workflow:
```bash
pip install ruff
ruff check src/ tests/ --select E,F,W --ignore E501
```

Common issues and fixes:

| Code | Issue | Fix |
|------|-------|-----|
| F401 | Unused import | Remove the import line |
| F841 | Local variable assigned but never used | Remove assignment or use the variable |
| E731 | Lambda assigned to variable | Rewrite as `def` |
| W191 | Tabs in indentation | Convert to spaces (rewrite the function) |

**Note:** Pre-existing issues in `src/` will fail CI even if you didn't touch those files. Fix them in the same lint-fix commit.

**Also watch for real bugs hiding as lint issues** — e.g. `F841` on `read2 = sys.argv[2]` revealed that the next line called `validate_records(read1)` instead of `validate_records(read2)`. Fix the bug, not just the lint.

---

## 3. Resolving merge conflicts after rebase

When a feature branch has conflicts with updated master (e.g., another PR fixed the same lint issues):

```bash
git fetch origin
git rebase origin/master
# resolve conflicts in each file
git add <conflicted-files>
git rebase --continue
```

**Conflict resolution strategy for lint fixes:**
- If both sides fixed the same issue differently (e.g., one-liner vs two-line `def`), keep the cleaner version (master's, since it was reviewed).
- If master has a bug and your branch fixes it, keep your fix regardless of conflict direction.

After rebase, verify nothing broke:
```bash
ruff check src/ tests/ --select E,F,W --ignore E501
pytest tests/ -q
```

Then force-push to update the PR:
```bash
git push --force-with-lease origin <branch>
```

Use `--force-with-lease` (not `--force`) — it fails if the remote has commits you haven't seen, preventing accidental overwrites.

---

## 4. Workflow checklist before pushing a branch for PR

- [ ] All tests pass locally with the same Python version as CI
- [ ] `ruff check src/ tests/` is clean (match CI flags exactly)
- [ ] No untracked files that should be committed (`.gitignore` the rest)
- [ ] `git log --oneline <branch> --not master` shows only intended commits
- [ ] If rebasing: use `git push --force-with-lease` to update PR

---

## 5. CI workflow structure (GitHub Actions)

Typical 3-job layout:

```yaml
jobs:
  python-tests:      # pytest with all required deps
  nextflow-lint:     # nextflow --help + config parse + guard tests
  python-lint:       # ruff check
```

Key gotchas:
- `cache: 'pip'` in `setup-python` caches by `requirements.txt` hash — if you add a dep without a requirements file, the cache won't invalidate. Explicit `pip install` in the step is fine for small dep lists.
- The Nextflow "express-only genome guard" test pipes stdout through `grep -q` — if the guard message changes, this test silently breaks.
