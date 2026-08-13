---
name: react-vite-quality-toolchain
description: "Add ESLint, Prettier, Vitest, an ErrorBoundary, typed env vars, security headers, and GitHub Actions CI to an existing React, TypeScript, and Vite project."
tags: [react, vite, typescript, eslint, vitest, ci]
---

# React / Vite Quality Toolchain

Reusable setup for adding ESLint 10, Prettier, Vitest, ErrorBoundary, typed env vars, security headers, and GitHub Actions CI to an existing React + TypeScript + Vite project.

## Packages to install (devDependencies)

```bash
npm install --save-dev \
  eslint \
  @eslint/js \
  @typescript-eslint/eslint-plugin \
  @typescript-eslint/parser \
  eslint-plugin-react-hooks \
  eslint-plugin-react-refresh \
  eslint-config-prettier \
  eslint-formatter-compact \
  globals \
  prettier \
  vitest \
  @vitest/coverage-v8
```

## ESLint flat config (`eslint.config.mjs`)

Must be `.mjs`, not `.js`, when `package.json` does not declare `"type": "module"`.

```js
import js from '@eslint/js';
import globals from 'globals';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import prettier from 'eslint-config-prettier';

export default [
  js.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { project: './tsconfig.json' },
      globals: { ...globals.browser },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'react-hooks/set-state-in-effect': 'warn',
      'no-control-regex': 'off',   // remove if not needed
    },
  },
  // Vitest globals for test files (eslint-plugin-vitest doesn't support ESLint 10 yet)
  {
    files: ['src/**/*.test.{ts,tsx}'],
    languageOptions: {
      globals: {
        describe: 'readonly', it: 'readonly', test: 'readonly',
        expect: 'readonly', beforeAll: 'readonly', afterAll: 'readonly',
        beforeEach: 'readonly', afterEach: 'readonly', vi: 'readonly',
      },
    },
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
  prettier,
];
```

**Gotchas:**
- ESLint 10 removed `util.styleText` compatibility with Node 18 — use `--format compact` or `eslint-formatter-compact` on Node 18; upgrade CI to Node 20 for the default formatter
- `eslint-plugin-vitest` does not yet support ESLint 10 — declare Vitest globals manually as shown above
- Browser globals (`document`, `window`, `navigator`, `localStorage`, `fetch`, etc.) require `globals.browser` in `languageOptions` — `js.configs.recommended` does not include them

## `.prettierrc`

```json
{
  "semi": true,
  "singleQuote": true,
  "tabWidth": 2,
  "trailingComma": "all",
  "printWidth": 100
}
```

## `package.json` scripts

```json
"scripts": {
  "lint": "eslint src --format compact",
  "lint:fix": "eslint src --fix --format compact",
  "format": "prettier --write src",
  "format:check": "prettier --check src",
  "test": "vitest run",
  "test:watch": "vitest",
  "test:coverage": "vitest run --coverage"
}
```

## Vitest config in `vite.config.ts`

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'node',   // or 'jsdom' if testing DOM-dependent code
    coverage: {
      provider: 'v8',
      include: ['src/utils/**'],
    },
  },
});
```

Add Vitest types to `tsconfig.json`:

```json
"types": ["vitest/globals"]
```

## Typed `vite-env.d.ts`

Extend the default file to type all `VITE_*` env vars — prevents silent `undefined` at build time:

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MY_VAR: string;
  // add all VITE_ vars used in src/
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

## React ErrorBoundary

```tsx
import { Component, type ReactNode } from 'react';

interface Props { children: ReactNode; }
interface State { error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ height: '100vh', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 12 }}>
          <h2>Something went wrong</h2>
          <p>{this.state.error.message}</p>
          <button onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

Wrap in `main.tsx`:

```tsx
<React.StrictMode>
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
</React.StrictMode>
```

## `amplify.yml` — Node pin + security headers

```yaml
version: 1
applications:
  - appRoot: web
    frontend:
      phases:
        preBuild:
          commands:
            - nvm use 20
            - npm ci
        build:
          commands:
            - npm run build
      artifacts:
        baseDirectory: dist
        files:
          - '**/*'
      cache:
        paths:
          - node_modules/**/*
      customHeaders:
        - pattern: '**'
          headers:
            - key: X-Frame-Options
              value: DENY
            - key: X-Content-Type-Options
              value: nosniff
            - key: Strict-Transport-Security
              value: 'max-age=31536000; includeSubDomains'
            - key: Referrer-Policy
              value: strict-origin-when-cross-origin
            - key: Permissions-Policy
              value: 'camera=(), microphone=(), geolocation=()'
            - key: Content-Security-Policy
              value: >-
                default-src 'self';
                script-src 'self' 'unsafe-inline';
                style-src 'self' 'unsafe-inline';
                img-src 'self' data: blob:;
                connect-src 'self'
                  https://*.amazonaws.com
                  https://login.microsoftonline.com;
                frame-ancestors 'none';
                object-src 'none';
                base-uri 'self'
```

Adjust `connect-src` for the services your app actually calls.

## GitHub Actions CI (`ci.yml`)

```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  python-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: pip
      - run: pip install pytest moto[s3] -r requirements.txt
      - run: python -m pytest tests/ -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'          # 20+ required for util.styleText (ESLint formatter)
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npm run lint
      - run: npm test
```

## What's worth testing with Vitest

Focus on pure utility functions — no mocking needed, fast to run:
- Input validation functions (string rules, byte-length checks, warning vs error tiers)
- Date/time calculation functions (`daysFromNow`, countdown logic)
- Data transformation functions (label maps, formatters)
- Rule-matching logic (lifecycle rules, filter conditions)

Skip React component rendering tests unless a component has complex logic that can't be extracted — Vitest without `@testing-library/react` is much lighter.
