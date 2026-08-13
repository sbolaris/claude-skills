#!/usr/bin/env python3
"""
jira_playwright_runner.py — AI-driven Playwright regression runner

Reads a Jira test execution markdown (produced by jira_pdf_to_md.py),
interprets each step with Claude API, executes the action via Playwright,
verifies the result with Claude vision, and writes a results report.

Usage:
    python3 ~/.claude/skills/jira_playwright_runner.py \
        --markdown DCA-825.md \
        --url https://your-app.example.com \
        [--output DCA-825_results.md] \
        [--headless] \
        [--tests DCA-673,DCA-668]

Requires:
    pip install anthropic playwright
    playwright install chromium
    export ANTHROPIC_API_KEY=sk-...
"""

import argparse
import base64
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_markdown_tests(md_path):
    """Parse markdown from jira_pdf_to_md.py into a list of test dicts."""
    text = Path(md_path).read_text(encoding='utf-8')
    tests = []

    # Split on test section headers (## KEY — Title)
    raw_sections = re.split(r'\n(?=## [A-Z])', text)

    for section in raw_sections:
        m = re.match(r'^## ([A-Z][A-Z0-9_]+-\d+)\s+[—\-]+\s+(.+)', section)
        if not m:
            continue
        key   = m.group(1)
        title = m.group(2).strip()

        steps = []
        in_steps = False
        for line in section.split('\n'):
            if line.startswith('### Steps'):
                in_steps = True
                continue
            if line.startswith('### ') and in_steps:
                break
            if not in_steps:
                continue
            # | N | action | data | expected | status |
            m2 = re.match(
                r'^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$',
                line
            )
            if m2:
                steps.append({
                    'num':             int(m2.group(1)),
                    'action':          m2.group(2).strip(),
                    'data':            m2.group(3).strip(),
                    'expected':        m2.group(4).strip(),
                    'original_status': m2.group(5).strip(),
                })

        if steps:
            tests.append({'key': key, 'title': title, 'steps': steps})

    return tests


# ---------------------------------------------------------------------------
# Claude API prompts
# ---------------------------------------------------------------------------

_SYS_PLAYWRIGHT = """\
You are a Playwright automation engineer for a web application.

Given a natural-language test step, write ONLY the Python Playwright code that uses
an already-open `page` object to perform the action described.

Rules:
- No imports, no try/except, no assertions, no comments.
- Prefer readable locators: get_by_text(), get_by_role(), get_by_label(),
  get_by_placeholder(). Avoid brittle CSS selectors when text-based ones exist.
- If the Data field contains a URL, use page.goto(url).
- If Data contains a field value to enter, use page.fill() / page.type().
- Limit to 1–8 lines of code.
- Output ONLY the raw code — no markdown fences, no explanation.
"""

_SYS_VERIFIER = """\
You are a QA engineer verifying whether a UI screenshot satisfies a test step's
expected result.

Respond with EXACTLY one of these two formats (nothing else):
  PASS - <one concise sentence explaining why it passes>
  FAIL - <one concise sentence explaining what is wrong>
"""


def _strip_fences(text):
    text = re.sub(r'^```(?:python)?\s*\n?', '', text.strip())
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def generate_playwright_code(client, test_title, step, context_summary, base_url):
    """Call Claude to produce Playwright Python code for one step."""
    data_line = ''
    d = step['data']
    if d and d not in ('—', '-', ''):
        data_line = f"\n  Data / input value: {d}"

    user_msg = (
        f"App base URL: {base_url}\n"
        f"Test case: {test_title}\n"
        + (f"Steps completed so far: {context_summary}\n" if context_summary else "")
        + f"\nStep {step['num']}:\n"
        f"  Action: {step['action']}{data_line}\n\n"
        "Write Playwright Python code to perform this action."
    )

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[{"type": "text", "text": _SYS_PLAYWRIGHT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    return _strip_fences(resp.content[0].text)


def verify_step_result(client, screenshot_path, expected):
    """Call Claude vision to determine PASS/FAIL for a step's expected result."""
    with open(screenshot_path, 'rb') as f:
        img_b64 = base64.standard_b64encode(f.read()).decode()

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=[{"type": "text", "text": _SYS_VERIFIER,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64,
                    },
                },
                {
                    "type": "text",
                    "text": f"Expected result: {expected}\n\nDoes the screenshot satisfy this?",
                },
            ],
        }],
    )

    raw = resp.content[0].text.strip()
    upper = raw.upper()
    if upper.startswith('PASS'):
        return 'PASS', raw[4:].lstrip(' -').strip()
    if upper.startswith('FAIL'):
        return 'FAIL', raw[4:].lstrip(' -').strip()
    return 'WARN', raw   # unexpected format — keep the full response


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

RESULT_EMOJI = {
    'PASS':  '✅',
    'FAIL':  '❌',
    'ERROR': '🔴',
    'WARN':  '⚠️',
}


def run_test(client, page, test, base_url, screenshot_dir):
    """Execute all steps for one test case. Returns a result dict."""
    step_results = []
    context_parts = []    # rolling summary of completed steps for LLM context

    print(f"\n  {'─' * 52}")
    print(f"  {test['key']} — {test['title'][:55]}")
    print(f"  {'─' * 52}")

    for step in test['steps']:
        print(f"    Step {step['num']:>2}: ", end='', flush=True)
        code = ''
        error = None
        screenshot_name = None
        result = 'ERROR'
        notes  = ''

        # 1 — Generate Playwright code
        try:
            code = generate_playwright_code(
                client, test['title'], step,
                '; '.join(context_parts[-4:]),
                base_url,
            )
        except Exception as e:
            notes = f"Code generation failed: {e}"
            print(f"CODE-GEN ERROR — {notes[:55]}")
            step_results.append({**step, 'result': result, 'notes': notes,
                                  'code': '', 'screenshot': None})
            continue

        # 2 — Execute generated code
        try:
            exec(code, {'page': page})                         # noqa: S102
            page.wait_for_load_state('networkidle', timeout=15_000)
        except PWTimeout:
            # networkidle timeout is often benign (SPAs never fully idle)
            pass
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        # 3 — Screenshot
        screenshot_name = f"{test['key']}_step_{step['num']}.png"
        sc_path = str(screenshot_dir / screenshot_name)
        try:
            page.screenshot(path=sc_path, full_page=False)
        except Exception as e:
            screenshot_name = None
            if not error:
                error = f"Screenshot failed: {e}"

        # 4 — Verify
        if error:
            result = 'ERROR'
            notes  = error
            print(f"ERROR — {notes[:55]}")
        elif screenshot_name:
            try:
                result, notes = verify_step_result(client, sc_path, step['expected'])
                print(f"{result} — {notes[:55]}")
            except Exception as e:
                result, notes = 'WARN', f"Verification error: {e}"
                print(f"WARN — {notes[:55]}")
        else:
            result, notes = 'WARN', 'Screenshot capture failed'
            print('WARN')

        context_parts.append(
            f"Step {step['num']} ({result}): {step['action'][:70]}"
        )
        step_results.append({
            **step,
            'result':     result,
            'notes':      notes,
            'code':       code,
            'screenshot': screenshot_name,
        })

    passed  = sum(1 for s in step_results if s['result'] == 'PASS')
    overall = 'PASS' if passed == len(step_results) else 'FAIL'
    emoji   = RESULT_EMOJI[overall]
    print(f"  → {emoji} {overall}  ({passed}/{len(step_results)} steps)")

    return {
        'key':    test['key'],
        'title':  test['title'],
        'result': overall,
        'passed': passed,
        'total':  len(step_results),
        'steps':  step_results,
    }


# ---------------------------------------------------------------------------
# Results writer
# ---------------------------------------------------------------------------

def _cell(text, maxlen=70):
    return str(text or '').replace('|', '\\|')[:maxlen]


def write_results(results, output_path, base_url, run_date):
    """Write the Markdown results report."""
    total_tests  = len(results)
    passed_tests = sum(1 for r in results if r['result'] == 'PASS')
    total_steps  = sum(r['total']  for r in results)
    passed_steps = sum(r['passed'] for r in results)

    lines = []
    stem = Path(output_path).stem.replace('_results', '')
    lines += [
        f"# Regression Results — {stem}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Run date | {run_date} |",
        f"| App URL | {base_url} |",
        f"| Tests | {passed_tests}/{total_tests} PASS |",
        f"| Steps | {passed_steps}/{total_steps} PASS |",
        "",
        "## Summary",
        "",
        "| Test | Title | Result | Steps |",
        "|------|-------|--------|-------|",
    ]
    for r in results:
        e = RESULT_EMOJI.get(r['result'], r['result'])
        lines.append(
            f"| {r['key']} | {_cell(r['title'], 55)} | {e} {r['result']} "
            f"| {r['passed']}/{r['total']} |"
        )
    lines += ["", "---", ""]

    for r in results:
        e = RESULT_EMOJI.get(r['result'], r['result'])
        lines += [
            f"## {r['key']} — {r['title']}",
            "",
            f"**Result:** {e} {r['result']}  ({r['passed']}/{r['total']} steps passed)",
            "",
            "| # | Action | Expected | Result | Notes |",
            "|---|--------|----------|--------|-------|",
        ]
        for s in r['steps']:
            se = RESULT_EMOJI.get(s['result'], s['result'])
            lines.append(
                f"| {s['num']} | {_cell(s['action'])} | {_cell(s['expected'])} "
                f"| {se} {s['result']} | {_cell(s['notes'], 80)} |"
            )
        lines.append("")

        # Screenshot references
        shots = [s['screenshot'] for s in r['steps'] if s['screenshot']]
        if shots:
            lines += ["**Screenshots:**", ""]
            for sc in shots:
                n = sc.split('_step_')[-1].replace('.png', '')
                lines.append(f"- Step {n}: `screenshots/{sc}`")
            lines.append("")

        # Generated code (collapsed so the report stays readable)
        lines += ["<details><summary>Generated Playwright code</summary>", ""]
        for s in r['steps']:
            if s['code']:
                lines += [
                    f"**Step {s['num']}:**",
                    "```python",
                    s['code'],
                    "```",
                    "",
                ]
        lines += ["</details>", "", "---", ""]

    Path(output_path).write_text('\n'.join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='AI-driven Playwright regression runner for Jira test markdowns'
    )
    ap.add_argument('--markdown', '-m', required=True,
                    help='Path to the .md file from jira_pdf_to_md.py')
    ap.add_argument('--url', '-u', required=True,
                    help='Base URL of the application under test')
    ap.add_argument('--output', '-o',
                    help='Results markdown path (default: <stem>_results.md)')
    ap.add_argument('--headless', action='store_true', default=False,
                    help='Run browser in headless mode')
    ap.add_argument('--tests', '-t',
                    help='Comma-separated test keys to run (e.g. DCA-673,DCA-668)')
    args = ap.parse_args()

    md_path = Path(args.markdown).expanduser().resolve()
    if not md_path.exists():
        print(f"ERROR: Markdown not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    out_path       = args.output or str(md_path.with_name(md_path.stem + '_results.md'))
    screenshot_dir = Path(out_path).parent / 'screenshots'
    screenshot_dir.mkdir(exist_ok=True)

    tests = parse_markdown_tests(str(md_path))
    if not tests:
        print("ERROR: No test cases found in markdown", file=sys.stderr)
        sys.exit(1)

    if args.tests:
        want = {k.strip().upper() for k in args.tests.split(',')}
        tests = [t for t in tests if t['key'].upper() in want]
        if not tests:
            print(f"ERROR: None of the requested tests found: {args.tests}", file=sys.stderr)
            sys.exit(1)

    run_date = datetime.now().strftime('%Y-%m-%d %H:%M PST')
    client   = anthropic.Anthropic()

    print(f"\n{'=' * 60}")
    print(f"  Jira Playwright Runner")
    print(f"  Markdown : {md_path.name}")
    print(f"  App URL  : {args.url}")
    print(f"  Tests    : {len(tests)}")
    print(f"  Headless : {args.headless}")
    print(f"{'=' * 60}")

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        ctx     = browser.new_context(viewport={'width': 1440, 'height': 900})
        page    = ctx.new_page()

        print(f"\n  Navigating to {args.url} …")
        page.goto(args.url, timeout=30_000)
        page.wait_for_load_state('networkidle', timeout=30_000)

        for test in tests:
            result = run_test(client, page, test, args.url, screenshot_dir)
            results.append(result)

        browser.close()

    write_results(results, out_path, args.url, run_date)

    passed = sum(1 for r in results if r['result'] == 'PASS')
    print(f"\n{'=' * 60}")
    print(f"  FINAL : {passed}/{len(results)} tests PASSED")
    print(f"  Report: {out_path}")
    print(f"  Shots : {screenshot_dir}/")
    print(f"{'=' * 60}\n")


if __name__ == '__main__':
    main()
