---
name: playwright-e2e
description: "TypeScript Playwright patterns for suites that use Okta SSO, Xray/Jira test steps, and MUI components, including polished demo video output."
tags: [playwright, typescript, e2e, okta, mui]
---

# Playwright E2E — TypeScript Suite with Okta + Xray Fallback

Reusable patterns for TypeScript Playwright projects that use Okta SSO, Xray/Jira test
steps, MUI components, and need polished demo video output.

Originally built against an internal React single-page app.

---

## Okta Auth Setup

Run auth as a Playwright `setup` project that saves `storageState` to `.auth/user.json`.
All test projects declare `dependencies: ['setup']` and receive `storageState: authFile`.

```typescript
// playwright.config.ts
const authFile = path.join(__dirname, '.auth/user.json');

projects: [
  { name: 'setup', testMatch: /auth\.setup\.ts/ },
  {
    name: 'chromium',
    use: { ...devices['Desktop Chrome'], storageState: authFile },
    dependencies: ['setup'],
  },
]
```

Credentials in `.env` (`OKTA_USERNAME`, `OKTA_PASSWORD`). Never commit `.env`.

### Key fix — same-screen username + password

Some Okta tenants show both fields on one screen. The naive two-step approach
(fill username → submit → fill password → submit) fires the first submit with an
empty password field and triggers "We found some errors."

**Fix:** check if the password field is already visible before the first submit:

```typescript
const passwordLocator = page.locator(
  '#okta-signin-password, input[name="credentials.passcode"], input[type="password"]'
);

await page.fill('#okta-signin-username', username);

const passwordAlreadyVisible = await passwordLocator.isVisible({ timeout: 2_000 }).catch(() => false);
if (passwordAlreadyVisible) {
  await passwordLocator.fill(password);
  await page.click('#okta-signin-submit, input[type="submit"]');
} else {
  await page.click('#okta-signin-submit');
  if (await passwordLocator.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await passwordLocator.fill(password);
    await page.click('#okta-signin-submit, input[type="submit"]');
  }
}
```

---

## Local Xray/Jira Step Fallback

When `XRAY_CLIENT_ID` is not set, fall back to a locally parsed DCA markdown export
so tests show real step names in the HTML report without needing API credentials.

The markdown comes from `jira_pdf_to_md.py` (see `jira-regression-test.md`).

### Parser — `utils/local-steps.ts`

```typescript
import * as fs from 'fs';
import * as path from 'path';
import { TestStep } from './xray-client';

const SEARCH_PATHS = [
  process.env.LOCAL_STEPS_PATH,
  path.join(__dirname, '../../DCA-825.md'),
  path.join(process.env.HOME || '', 'DCA-825.md'),
].filter(Boolean) as string[];

function parseMarkdown(content: string): Map<string, TestStep[]> {
  const result = new Map<string, TestStep[]>();
  const parts = content.split(/\n(?=## DCA-\d+)/);
  for (const section of parts) {
    const keyMatch = section.match(/^## (DCA-\d+)/);
    if (!keyMatch) continue;
    const stepsMatch = section.match(/### Steps\n([\s\S]*?)(?=\n###|\n---|\n## |$)/);
    if (!stepsMatch) continue;
    const steps: TestStep[] = [];
    for (const line of stepsMatch[1].split('\n')) {
      if (!line.startsWith('|')) continue;
      const cells = line.split('|').map(c => c.trim()).filter(Boolean);
      if (cells.length < 4 || cells[0] === '#' || cells[0].includes('---')) continue;
      const id = parseInt(cells[0]);
      if (isNaN(id)) continue;
      steps.push({ id: String(id), action: cells[1], data: cells[2] !== '—' ? cells[2] : null, result: cells[3] });
    }
    if (steps.length > 0) result.set(keyMatch[1], steps);
  }
  return result;
}

let cache: Map<string, TestStep[]> | null = null;

export function getLocalSteps(issueKey: string): TestStep[] {
  if (!cache) {
    for (const p of SEARCH_PATHS) {
      try { cache = parseMarkdown(fs.readFileSync(p, 'utf-8')); break; }
      catch { /* try next */ }
    }
    cache = cache ?? new Map();
  }
  return cache.get(issueKey) ?? [];
}
```

### Wire into `xray-client.ts`

```typescript
import { getLocalSteps } from './local-steps';   // static import — CommonJS module target

export async function getTestSteps(issueKey: string): Promise<TestStep[]> {
  if (!process.env.XRAY_CLIENT_ID) {
    const steps = getLocalSteps(issueKey);
    if (steps.length > 0) console.log(`[xray] Using local markdown steps for ${issueKey}`);
    else console.warn(`[xray] No steps found for ${issueKey} — using inline labels`);
    return steps;
  }
  // ... existing Xray API call
}
```

**Important:** use a static `import`, not dynamic `import()`. Projects that compile
to CommonJS (`"module": "commonjs"` in tsconfig) will throw `Cannot use import
statement outside a module` at runtime with dynamic imports.

---

## Common Locator Fixes

### MUI DataGrid (not a native `<table>`)

```typescript
// ❌ fails — MUI DataGrid renders divs, not <table>/<tbody>
this.page.locator('table tbody')

// ✅ correct
this.page.locator('.MuiDataGrid-root')    // grid container — always present when rendered
this.page.locator('.MuiDataGrid-row')     // individual rows — use for row counting
```

### Hidden file inputs (drag-drop upload zones)

```typescript
// ❌ fails — input[type="file"] is intentionally hidden behind the drop zone div
await expect(fileInput).toBeVisible()

// ✅ use toBeAttached — confirms it's in the DOM even though hidden
await expect(fileInput).toBeAttached()
await fileInput.setInputFiles(filePath)   // setInputFiles works on hidden inputs

// ✅ assert the visible drop zone text instead
await expect(page.locator('text=Drag & drop some files here')).toBeVisible()
```

---

## Manual / Skipped Tests

Non-automatable tests (document checks, data-dependent multi-step workflows) still
appear in the HTML report under "Skipped" with a plain-English reason — useful for
release checklists and demos.

```typescript
// tests/manual/manual-checks.spec.ts
test('DCA-814: Project architecture document is created', async ({ page, xraySteps }) => {
  test.info().annotations.push({ type: 'jira', description: 'DCA-814' });
  test.info().annotations.push({
    type: 'manual',
    description: 'Release-time document check — not automatable via browser.',
  });
  const steps = await xraySteps('DCA-814');
  test.skip(true, `Manual — ${steps[0]?.action ?? 'Verify architecture document exists'}`);
});
```

Group all manual tests in a single `tests/manual/` directory so they're easy to
explain during a demo as "these are the release checklist items we verify by hand."

---

## Demo Video Config

### `playwright.config.ts`

```typescript
use: {
  trace: 'on',
  screenshot: 'on',
  video: 'on',
},
projects: [{
  name: 'chromium',
  use: {
    ...devices['Desktop Chrome'],
    storageState: authFile,
    slowMo: process.env.SLOW_MO ? parseInt(process.env.SLOW_MO) : 1200,
    viewport: { width: 1440, height: 900 },
  },
}]
```

### Page object patterns

Add `waitUntil: 'networkidle'` on every `page.goto()` so the page fully renders
before the step ends:

```typescript
async gotoList() {
  await this.page.goto('/my/route', { waitUntil: 'networkidle' });
}
```

Add a hold at the end of content-check methods so the video lingers on the loaded state:

```typescript
async waitForContentOrEmpty() {
  await expect(this.page.locator('.MuiDataGrid-root, ...')).toBeVisible({ timeout: 15_000 });
  await this.page.waitForTimeout(2500);  // hold — gives video a clear frame of the loaded page
}
```

### Running headed on a headless server (Xvfb)

```bash
Xvfb :99 -screen 0 1280x800x24 &
DISPLAY=:99 npx playwright test --headed
```

### Serving the HTML report

```bash
npx playwright show-report --host 0.0.0.0 --port 9323
```

The report embeds per-test videos, screenshots, and traces — open it at
`http://localhost:9323` for demos.

### Override slowMo without editing the config

```bash
SLOW_MO=500 npx playwright test    # faster for CI
SLOW_MO=2000 npx playwright test   # slower for a live demo walkthrough
```

---

## Test Structure Pattern

```
tests/
  analysis/       # one spec file per feature area
  qc/
  upload/
  general/        # navigation, auth, version checks
  manual/         # skipped tests for non-automatable checks
pages/            # page object classes, one per app section
fixtures/
  base.fixture.ts # extends base test with xraySteps fixture
utils/
  xray-client.ts  # Xray Cloud API + local markdown fallback
  local-steps.ts  # markdown parser
```

Each test uses a real Jira ticket key (not a placeholder like `DCA-XXX`) so steps
load from the local markdown and appear as named steps in the HTML report.
