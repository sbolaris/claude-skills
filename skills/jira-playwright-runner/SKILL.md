---
name: jira-playwright-runner
description: "Run AI-native Playwright regression tests from a Markdown test spec using a persistent browser server and vision-based verification, with no external API key. Pairs with the sqa-regression-tester agent."
tags: [playwright, testing, jira, xray, regression]
---

# Skill: jira-playwright-runner

AI-native Playwright regression runner. The `sqa-regression-tester` agent reads test steps from the Markdown file produced by `jira-regression-test`, generates Playwright code using its own reasoning, executes it via a persistent browser server, and verifies results with its own vision — no external API key required.

---

## Architecture

```
sqa-regression-tester agent (IS Claude — no API key needed)
  │
  │  generates Playwright code per step
  │  assesses screenshots with built-in vision
  │
  ▼
jira_playwright_server.py   ← long-running background process
  │
  │  /tmp/pw_session/cmd.json    (agent writes commands)
  │  /tmp/pw_session/result.json (server writes results)
  │  /tmp/pw_session/ready       (server signals ready)
  │
  ▼
Chromium browser (persistent session across all steps)
```

The key insight: Claude Code **is** Claude. There is no reason to call the Anthropic API from a subprocess when the agent can generate code and interpret screenshots natively. This eliminates the `ANTHROPIC_API_KEY` shell export requirement entirely.

---

## Components

### `jira_playwright_server.py`

A long-running Python process that:
- Opens a Chromium browser and navigates to the starting URL
- Writes `/tmp/pw_session/ready` when the browser is open
- Polls for `/tmp/pw_session/cmd.json`, executes the command, writes `/tmp/pw_session/result.json`
- Keeps browser state (cookies, local storage, page position) between steps
- Auto-shuts down after 5 minutes of no commands

**Start (background):**
```bash
python3 ~/.claude/skills/jira_playwright_server.py --url https://app.example.com --headless
```

**Command protocol** (write to `/tmp/pw_session/cmd.json`):
```json
{ "action": "execute",    "code": "page.goto('...')", "screenshot": "/tmp/pw_session/step.png" }
{ "action": "goto",       "url":  "https://...",       "screenshot": "/tmp/pw_session/step.png" }
{ "action": "screenshot", "path": "/tmp/pw_session/step.png" }
{ "action": "quit" }
```

**Result** (read from `/tmp/pw_session/result.json`, then delete it):
```json
{ "status": "ok",    "screenshot": "/tmp/pw_session/step.png" }
{ "status": "error", "message": "TimeoutError: ...", "screenshot": "/tmp/pw_session/step.png" }
```

### `sqa-regression-tester` agent

The agent owns all intelligence:
- Reads the Markdown test file to extract steps
- Generates Playwright code per step (via its own reasoning)
- Sends commands to the server via Write tool
- Reads screenshots via Read tool (built-in vision)
- Assesses PASS/FAIL/ERROR/WARN itself
- Writes the final results report

---

## OKTA Auth — Same-Screen Field Gotcha

Some Okta tenants show **both** username and password on one page. The naive two-step
approach (fill username → submit → fill password → submit) fires the first submit with an
empty password and triggers "We found some errors." Fix: check if the password field is
already visible *before* the first submit and fill it first if so. See
`playwright-e2e.md` for the full TypeScript pattern.

---

## OKTA / Auth Setup (one-time per app)

Apps protected by OKTA require a saved session before headless tests can run. This is a one-time step per environment.

### Step 1 — Capture your session

```bash
python3 ~/.claude/skills/jira_playwright_login.py \
    --url https://your-app.cloudfront.net/ \
    --output ~/.config/pw_sessions/myapp.json
```

A visible browser opens. Log in with your OKTA credentials. When you can see the app, press Enter. The session (cookies + local storage) is saved to the JSON file.

### Step 2 — The agent uses it automatically

When the `sqa-regression-tester` agent detects an auth wall, it will ask you to run the login helper and tell it the output path. It then restarts the browser server with:

```bash
python3 ~/.claude/skills/jira_playwright_server.py \
    --url https://your-app.cloudfront.net/ \
    --storage-state ~/.config/pw_sessions/myapp.json \
    --headless
```

### Session expiry

OKTA sessions typically last 8–24 hours. If tests start redirecting to login on a subsequent day, re-run the login helper to refresh the file.

---

## Prerequisites

```bash
pip install playwright
playwright install chromium
which pdftotext || sudo apt-get install -y poppler-utils
```

No `ANTHROPIC_API_KEY` required.

---

## Typical workflow

The `sqa-regression-tester` agent handles this end-to-end. You do not invoke the server or the converter manually — the agent does it all. Just give the agent:

1. The path to your Jira PDF
2. The URL of the app to test

```
Run the regression tests for $HOME/DCA-825.pdf against https://staging.example.com
```

---

## Output

The agent writes `<stem>_results.md` next to the markdown file with:
- Summary table (tests passed/failed, steps passed/failed)
- Per-test detail table (step-by-step PASS/FAIL with notes)
- Screenshot paths (stored in `/tmp/pw_session/`)
- Generated Playwright code per step (in `<details>` blocks)

---

## Result codes

| Code | Meaning |
|------|---------|
| `✅ PASS` | Agent's vision confirms the screenshot satisfies the expected result |
| `❌ FAIL` | Screenshot shows the wrong state |
| `🔴 ERROR` | Playwright threw an exception during step execution |
| `⚠️ WARN` | Screenshot missing or expected result text too ambiguous to judge |

---

## Known limitations

1. **`exec()` safety:** Playwright code is generated by the agent and run via `exec()` in the server. The agent is instructed to avoid destructive operations, but review the generated code in `<details>` blocks if a step behaves unexpectedly.

2. **SPA networkidle:** Single-page apps may never reach a true `networkidle` state. The server silently swallows that timeout and continues.

3. **Auth flows:** The browser starts at `--url` with no session. Tests that assume a logged-in user should include a login test case that runs first.

4. **Browser state is shared:** All tests run in one browser session. A test that leaves the page in a broken state will affect subsequent tests.

5. **Screenshot storage:** Screenshots go to `/tmp/pw_session/` which is cleared on server restart. Copy them out if you need to keep them beyond the session.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/tmp/pw_session/error` appears | Read the file — usually a network error reaching `--url`; confirm the app is up |
| `ready` file never appears | Server likely crashed on startup; check the background process output |
| All steps ERROR with `TimeoutError` | App may be slow — the server waits 10s for networkidle; check app health |
| Steps consistently FAIL despite correct UI | Make the Expected Result text in the markdown more concrete |
| `playwright` not found | `pip install playwright && playwright install chromium` |
| `pdftotext` not found | `sudo apt-get install -y poppler-utils` |
