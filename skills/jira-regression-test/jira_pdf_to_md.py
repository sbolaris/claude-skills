#!/usr/bin/env python3
"""
jira_pdf_to_md.py — Convert a Jira Test Execution PDF to Markdown

Usage:
    python3 ~/.claude/skills/jira_pdf_to_md.py <path_to_pdf>

Output:
    <pdf_name>.md written in the same directory as the PDF

Requires: pdftotext (poppler-utils) — `sudo apt-get install poppler-utils`
"""

import re
import sys
import subprocess
from pathlib import Path

STATUS_EMOJI = {
    "PASSED":    "✅ PASS",
    "PASS":      "✅ PASS",
    "FAILED":    "❌ FAIL",
    "FAIL":      "❌ FAIL",
    "TODO":      "🔲 TODO",
    "EXECUTING": "⏳ EXECUTING",
    "ABORTED":   "⛔ ABORTED",
    "PASSX":     "✅ PASSX",
}

PAGE_FOOTER_RE = re.compile(r'TEST EXECUTION[^\n]*AUTOMATICALLY GENERATED[^\n]*')

# SECTION_RE and the requirement key pattern are compiled dynamically per PDF
# once the project prefix is detected.  See detect_prefix() and build_regexes().
_DEFAULT_PREFIX = '[A-Z]+'   # fallback if detection fails


def detect_prefix(raw_text):
    """Detect the Jira project key prefix from the PDF cover page.

    Looks for the canonical 'Issue: PREFIX-NNN' line, then falls back to
    scanning the Test Execution path in section headers.
    Returns a string like 'DCA', 'PROJ', etc.
    """
    # Primary: "Issue: DCA-825"
    m = re.search(r'\bIssue:\s+([A-Z][A-Z0-9_]+)-\d+', raw_text)
    if m:
        return m.group(1)
    # Fallback: "/ Test: DCA-NNN -"
    m = re.search(r'/ Test:\s+([A-Z][A-Z0-9_]+)-\d+', raw_text)
    if m:
        return m.group(1)
    return None   # caller will use generic pattern


def build_regexes(prefix):
    """Return (section_re, req_key_re) compiled for the given prefix."""
    pfx = re.escape(prefix) if prefix else '[A-Z][A-Z0-9_]+'
    key_pat = rf'{pfx}-\d+'
    section_re = re.compile(
        rf'^[\d\.]+\s+.+/ Test: ({key_pat}) - (.+?)$'
    )
    req_key_re = re.compile(rf'^({key_pat})\s*(.*)', re.IGNORECASE)
    return section_re, req_key_re
META_ROW_RE = re.compile(
    r'(PASSED|FAILED|TODO|EXECUTING|ABORTED|PASSX)\s+'
    r'([A-Za-z][A-Za-z\s]+?)\s{2,}'
    r'([A-Za-z][A-Za-z\s]+?)\s{2,}'
    r'(\d{2}-\d{2}-\d{4}(?:\s+\d{2}:\d{2}:\d{2})?)\s+'
    r'(\d{2}-\d{2}-\d{4}(?:\s+\d{2}:\d{2}:\d{2})?)'
)


def normalize_status(raw):
    return STATUS_EMOJI.get(raw.strip().upper(), raw.strip())


def extract_text(pdf_path):
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True
    )
    return result.stdout


def strip_footers(text):
    text = text.replace('\x0c', '')          # remove form-feed (page break) chars
    return PAGE_FOOTER_RE.sub('', text)


def find_body_sections(lines, section_re):
    """Return list of (line_index, key, title) for real body sections (after TOC).

    Strategy: the document body always starts after the page that contains
    "2. Test Run Details" heading (well past line 100).  We skip any match
    before line 150 to exclude TOC entries.
    """
    sections = []
    for i, line in enumerate(lines):
        if i < 150:          # everything before this is preamble / TOC
            continue
        stripped = line.strip()
        m = section_re.match(stripped)
        if m and '.....' not in line:
            sections.append((i, m.group(1), m.group(2).strip()))
    return sections


def get_section_lines(all_lines, sections, idx):
    start = sections[idx][0]
    end = sections[idx + 1][0] if idx + 1 < len(sections) else len(all_lines)
    return all_lines[start:end]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def parse_metadata(section_lines):
    meta = dict(status="", assignee="", executed_by="",
                started_on="", finished_on="", comment="None")

    for i, line in enumerate(section_lines):
        m = META_ROW_RE.search(line)
        if m:
            meta['status']      = m.group(1)
            meta['assignee']    = m.group(2).strip()
            meta['executed_by'] = m.group(3).strip()
            meta['started_on']  = m.group(4).strip()
            meta['finished_on'] = m.group(5).strip()

        if re.match(r'\s*Comment\s*$', line, re.IGNORECASE):
            for j in range(i + 1, min(i + 5, len(section_lines))):
                c = section_lines[j].strip()
                if c:
                    meta['comment'] = c
                    break

    return meta


# ---------------------------------------------------------------------------
# Step table
# ---------------------------------------------------------------------------

def find_column_positions(header_line):
    """Return {col_name: start_char_position} from the table header line."""
    col_names = ['Step', 'Action', 'Data', 'Expected Result',
                 'Attachments', 'Comment', 'Defects', 'Status']
    positions = {}
    for col in col_names:
        pos = header_line.find(col)
        if pos >= 0:
            positions[col] = pos
    return positions


def slice_columns(line, positions, col_names):
    """Assign text chunks to columns by proximity to column centers.

    Finds runs of non-whitespace (separated by 3+ spaces) and assigns each
    chunk to whichever column center it is closest to.  This handles layout
    text that starts a few characters to the left of the column header label.
    """
    sorted_cols = sorted(col_names, key=lambda c: positions.get(c, 9999))
    # Column center = header start + half the header label length
    centers = {c: positions[c] + len(c) // 2 for c in sorted_cols}

    # Find text chunks: runs separated by 3+ spaces
    chunks = []  # list of (chunk_center, text)
    for m in re.finditer(r'\S[\s\S]*?(?=\s{3}|$)', line):
        text = m.group(0).strip()
        if text:
            chunk_center = m.start() + len(m.group(0)) // 2
            chunks.append((chunk_center, text))

    result = {c: '' for c in col_names}
    for chunk_center, text in chunks:
        nearest = min(sorted_cols, key=lambda c: abs(centers[c] - chunk_center))
        result[nearest] = (result[nearest] + ' ' + text).strip()

    return result


def parse_steps(section_lines):
    """Parse step table.

    In layout-preserved PDFs the step number appears on the *middle* row of the
    multi-line cell — not the first row.  Strategy:
      1. Collect all body lines between the table header and the requirements.
      2. Find every row that contains a step number in the Step column.
      3. Build the block for step N from the row after step N-1's number row
         up to and including step N's number row.  This captures the "pre-rows"
         that appear above the step number in the PDF.
    """
    steps = []

    if not any(re.search(r'This Manual Test has \d+ Steps?', l) for l in section_lines):
        return steps

    header_idx = None
    col_positions = {}
    for i, line in enumerate(section_lines):
        # Single-line header (most tests)
        if 'Step' in line and 'Action' in line and 'Expected Result' in line and 'Status' in line:
            header_idx = i
            col_positions = find_column_positions(line)
            break
        # Multi-line header: column names split across 2-3 rows.
        # Anchor on the row that contains 'Action'; look at a 5-line window
        # around it to collect all column positions.
        if 'Action' in line and 'Status' in line:
            window_lines = section_lines[max(0, i - 1): i + 4]
            window_text = ' '.join(window_lines)
            # Must look like a step table header (Step/Ste/St nearby)
            if re.search(r'\bSt(?:ep|e|p)?\b', window_text):
                header_idx = i
                col_positions = find_column_positions(line)
                # Patch missing positions from adjacent lines
                col_patches = {
                    'Step':            [r'\bStep\b', r'\bSte\b', r'\bSt\b'],
                    'Data':            [r'\bData\b', r'\bDat\b'],
                    'Expected Result': [r'Expected Result', r'Expecte'],
                    'Attachments':     [r'Attachments', r'Attachme'],
                    'Comment':         [r'\bComment\b', r'\bComme\b'],
                    'Defects':         [r'\bDefects\b', r'\bDefe\b'],
                }
                for col, patterns in col_patches.items():
                    if col in col_positions:
                        continue
                    for adj in window_lines:
                        found = False
                        for pat in patterns:
                            m = re.search(pat, adj)
                            if m:
                                col_positions[col] = m.start()
                                found = True
                                break
                        if found:
                            break
                break

    if header_idx is None or not col_positions:
        return steps

    col_names = list(col_positions.keys())
    step_col = col_positions.get('Step', 0)

    # Collect body lines
    body_lines = []
    for line in section_lines[header_idx + 1:]:
        if re.search(r'Requirements linked with this test', line, re.IGNORECASE):
            break
        if PAGE_FOOTER_RE.search(line):
            continue
        body_lines.append(line)

    # Find step-number row indices
    step_rows = []  # (body_index, step_num_str)
    for i, line in enumerate(body_lines):
        step_area = line[max(0, step_col - 1): step_col + 6] if len(line) > step_col else ''
        m = re.match(r'\s*(\d+)\s', step_area)
        if m:
            step_rows.append((i, m.group(1)))

    if not step_rows:
        return steps

    # Build block for step N: body_lines[prev_end : this_row_idx + 1]
    prev_end = 0
    for row_idx, step_num in step_rows:
        block = body_lines[prev_end: row_idx + 1]
        prev_end = row_idx + 1

        fields = {c: [] for c in col_names}
        step_status = ''

        for line in block:
            step_area = line[max(0, step_col - 1): step_col + 6] if len(line) > step_col else ''
            is_num_row = bool(re.match(r'\s*\d+\s', step_area))
            parts = slice_columns(line, col_positions, col_names)

            for col, val in parts.items():
                if not val:
                    continue
                if col == 'Status' and val.upper().rstrip('X') in ('PASSED', 'FAILED', 'PASS', 'FAIL', 'TODO', 'ABORTED', 'EXECUTING', 'PASSX'):
                    step_status = val
                elif col == 'Step' and is_num_row:
                    pass  # skip digit token
                else:
                    fields[col].append(val)

        # Fallback: if column-based parsing missed the status, search the
        # block AND a lookahead window of up to 5 post-rows (status tokens
        # sometimes appear after the step-number row due to PDF vertical
        # centering).  PDFs also split tokens across lines ("PASSE"/"D" or
        # "PASS"/"ED"), so we join adjacent line pairs before searching.
        if not step_status:
            status_re = re.compile(r'\b(PASSED|FAILED|PASSX|ABORTED|EXECUTING|TODO)\b')
            post = body_lines[row_idx + 1: row_idx + 6]
            search_lines = list(block) + post
            pairs = [search_lines[i].rstrip() + search_lines[i + 1].lstrip()
                     for i in range(len(search_lines) - 1)]
            # Pass 1: complete token on one line or in a joined pair
            for text in search_lines + pairs:
                m = status_re.search(text)
                if m:
                    step_status = m.group(1)
                    break
        if not step_status:
            # Pass 2: PDF split the token mid-word across lines with the step-
            # number row in between (e.g. "…PASS\n 1 …\n…ED").  Any line that
            # ends with "PASS" or "PASSE" is treated as a split "PASSED".
            for text in search_lines:
                if re.search(r'PASSE?\s*$', text):
                    step_status = 'PASSED'
                    break
                if re.search(r'FAILE?\s*$', text):
                    step_status = 'FAILED'
                    break

        steps.append({
            'step':     step_num,
            'action':   ' '.join(fields.get('Action', [])),
            'data':     ' '.join(fields.get('Data', [])),
            'expected': ' '.join(fields.get('Expected Result', [])),
            'status':   step_status,
            'comment':  ' '.join(fields.get('Comment', [])),
            'defects':  ' '.join(fields.get('Defects', [])),
        })

    return steps


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

def parse_requirements(section_lines, req_key_re):
    """Parse the requirements table.

    In layout-preserved PDFs the first line of a requirement's Summary text can
    appear on the row ABOVE the project key (because the PDF vertically centers
    the key).  We buffer "pending" summary lines until we see the key, then
    prepend them to that requirement's summary.
    """
    reqs = []
    in_reqs = False
    current_key = None
    current_lines = []
    pending_lines = []   # lines seen before the key for the next requirement

    for line in section_lines:
        if re.search(r'Requirements linked with this test', line, re.IGNORECASE):
            in_reqs = True
            continue
        if not in_reqs:
            continue
        if re.match(r'\s*Requirement Key\s+Requirement Summary', line):
            continue

        stripped = line.strip()
        if not stripped:
            continue

        m = req_key_re.match(stripped)
        if m:
            if current_key:
                reqs.append({'key': current_key, 'summary': ' '.join(current_lines)})
            current_key = m.group(1)
            # Prepend any lines buffered before this key row
            first_val = m.group(2).strip()
            current_lines = pending_lines + ([first_val] if first_val else [])
            pending_lines = []
        elif current_key:
            current_lines.append(stripped)
        else:
            # No key seen yet — buffer as pre-rows for the next key
            pending_lines.append(stripped)

    if current_key:
        reqs.append({'key': current_key, 'summary': ' '.join(current_lines)})

    return reqs


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _cell(text):
    return (text or '—').replace('|', '\\|').replace('\n', ' ').strip()


def render_test(key, title, meta, steps, reqs):
    out = []
    out.append(f"## {key} — {title}")
    out.append("")

    # Metadata table
    out.append("| Field | Value |")
    out.append("|-------|-------|")
    out.append(f"| Status | {normalize_status(meta['status'])} |")
    out.append(f"| Assignee | {_cell(meta['assignee'])} |")
    out.append(f"| Executed By | {_cell(meta['executed_by'])} |")
    out.append(f"| Started | {_cell(meta['started_on'])} |")
    out.append(f"| Finished | {_cell(meta['finished_on'])} |")
    if meta['comment'] and meta['comment'].lower() != 'none':
        out.append(f"| Comment | {_cell(meta['comment'])} |")
    out.append("")

    # Steps
    if steps:
        out.append("### Steps")
        out.append("")
        out.append("| # | Action | Data | Expected Result | Status |")
        out.append("|---|--------|------|-----------------|--------|")
        for s in steps:
            out.append(
                f"| {s['step']} | {_cell(s['action'])} | {_cell(s['data'])} "
                f"| {_cell(s['expected'])} | {normalize_status(s['status'])} |"
            )
        out.append("")
    else:
        out.append("_No steps parsed._")
        out.append("")

    # Requirements
    if reqs:
        out.append("### Linked Requirements")
        out.append("")
        out.append("| Key | Summary |")
        out.append("|-----|---------|")
        for r in reqs:
            out.append(f"| {r['key']} | {_cell(r['summary'])} |")
        out.append("")

    out.append("---")
    out.append("")
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def convert(pdf_path_str):
    pdf_path = Path(pdf_path_str).expanduser().resolve()
    if not pdf_path.exists():
        print(f"ERROR: File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    out_path = pdf_path.with_suffix('.md')

    raw = extract_text(pdf_path)
    clean = strip_footers(raw)
    all_lines = clean.split('\n')

    # Auto-detect project prefix (e.g. "DCA", "PROJ") so the script works
    # across Jira projects without hardcoding.
    prefix = detect_prefix(raw)
    if prefix:
        print(f"Detected project prefix: {prefix}")
    else:
        print("Warning: could not detect project prefix — using generic pattern")
    section_re, req_key_re = build_regexes(prefix)

    sections = find_body_sections(all_lines, section_re)

    if not sections:
        print("ERROR: No test sections found in PDF.", file=sys.stderr)
        sys.exit(1)

    blocks = [f"# Test Execution — {pdf_path.stem}\n\n"]

    for idx, (_, key, title) in enumerate(sections):
        sec_lines = get_section_lines(all_lines, sections, idx)
        meta  = parse_metadata(sec_lines)
        steps = parse_steps(sec_lines)
        reqs  = parse_requirements(sec_lines, req_key_re)
        blocks.append(render_test(key, title, meta, steps, reqs))

    out_path.write_text('\n'.join(blocks), encoding='utf-8')
    print(f"✅ Written: {out_path}  ({len(sections)} tests)")
    return out_path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <path_to_pdf>")
        sys.exit(1)
    convert(sys.argv[1])
