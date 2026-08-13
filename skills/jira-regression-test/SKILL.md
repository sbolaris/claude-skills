---
name: jira-regression-test
description: "Convert a Jira/Xray Test Execution PDF into structured Markdown suitable for review, archiving, or agent-driven regression verification."
tags: [jira, xray, pdf, testing, regression]
---

# Skill: jira-regression-test

Convert a Jira Test Execution PDF (exported from Xray) into a structured Markdown document suitable for review, archiving, or agent-driven regression verification.

---

## When to use this skill

Invoke this skill when the user provides a Jira/Xray PDF test execution report (file typically named `DCA-NNN.pdf` or similar) and asks you to:
- Convert it to markdown
- Extract test cases for review
- Produce a readable regression test summary

---

## How it works

The conversion is handled by a Python script that deterministically parses the PDF layout:

```
~/.claude/skills/jira_pdf_to_md.py
```

**Requires:** `poppler-utils` — install with `sudo apt-get install poppler-utils` if not present.

---

## Steps to execute

### 1. Verify the tool is available

```bash
which pdftotext || sudo apt-get install -y poppler-utils
```

### 2. Run the converter

```bash
python3 ~/.claude/skills/jira_pdf_to_md.py /path/to/DCA-NNN.pdf
```

Output is written to the **same directory** as the PDF with a `.md` extension (e.g. `DCA-825.pdf` → `DCA-825.md`).

The script prints: `✅ Written: /path/to/DCA-825.md  (N tests)`

### 3. Verify the output

After the script completes, do a quick sanity check:

```bash
# Count tests found
grep -c "^## DCA-" /path/to/DCA-825.md

# Count steps with missing status
grep -E "^\| [0-9]" /path/to/DCA-825.md | grep -v "✅\|❌\|🔲\|⏳\|⛔" | wc -l
```

- Test count should match the PDF's "Number of Test Runs" from the cover page.
- Missing status count should be 0 (or close to it for unusual layouts).

### 4. Show the user the output path and summary

Report:
- Path to the `.md` file
- Number of tests extracted
- Any steps with missing statuses (so the user knows to review those manually)

---

## Output format

Each test section contains:

```markdown
## DCA-NNN — Test title

| Field | Value |
|-------|-------|
| Status | ✅ PASS |
| Assignee | Name |
| Executed By | Name |
| Started | MM-DD-YYYY HH:MM:SS |
| Finished | MM-DD-YYYY HH:MM:SS |

### Steps

| # | Action | Data | Expected Result | Status |
|---|--------|------|-----------------|--------|
| 1 | Navigate to... | — | User sees... | ✅ PASS |

### Linked Requirements

| Key | Summary |
|-----|---------|
| DCA-NNN | As a developer I need to... |
```

**Status emoji mapping:**
- `✅ PASS` = PASSED
- `❌ FAIL` = FAILED
- `🔲 TODO` = TODO
- `⏳ EXECUTING` = EXECUTING
- `⛔ ABORTED` = ABORTED

---

## Known limitations

The PDF uses a multi-column layout that `pdftotext -layout` linearizes. These edge cases may require manual review:

1. **Step text boundary bleed**: Multi-line step cells can have a line or two of content from an adjacent step at the start or end of the Action/Expected Result text. The step numbers and statuses are always correct.

2. **Multi-line headers**: Some tables have column headers split across 2–3 rows (PDF layout artifact). The parser handles the most common variants, but unusual splits may cause "No steps parsed" for a test — check that test manually.

3. **Requirement summary truncation**: When a requirement's Summary text starts on the row above its DCA key, the pre-row text is captured. Occasionally the first sentence of a multi-DCA block gets merged into the previous requirement's summary.

4. **URLs in action text**: Long Jira/Confluence URLs are preserved as-is (they appear in the Action column). Markdown pipe characters inside URLs are escaped with `\|`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ERROR: File not found` | Check path; use absolute path |
| `ERROR: No test sections found` | PDF may not follow the standard DBG Cloud Analysis / Test Execution format |
| `✅ Written: … (0 tests)` | The TOC/body section detection failed — check if the PDF has the standard 2-column section numbering |
| `No steps parsed` for a test | That test's step table header may use an unusual multi-line layout; review the PDF manually |
| `pdftotext: command not found` | Run: `sudo apt-get install poppler-utils` |
