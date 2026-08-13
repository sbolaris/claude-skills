#!/usr/bin/env python3
"""
jira_playwright_login.py — One-time OKTA session capture helper

Opens a visible (non-headless) browser so you can log in manually via OKTA.
Once you're fully inside the app, press Enter and the session is saved to a
JSON file. Pass that file to jira_playwright_server.py via --storage-state
so headless regression runs are authenticated from the start.

Usage:
    python3 ~/.claude/skills/jira_playwright_login.py \
        --url https://your-app.cloudfront.net/ \
        [--output ~/.config/pw_sessions/myapp.json]

Then run the server with:
    python3 ~/.claude/skills/jira_playwright_server.py \
        --url https://your-app.cloudfront.net/ \
        --storage-state ~/.config/pw_sessions/myapp.json \
        --headless
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_OUTPUT = Path.home() / ".config" / "pw_sessions" / "session.json"


def main():
    ap = argparse.ArgumentParser(
        description="Capture an OKTA-authenticated browser session for Playwright"
    )
    ap.add_argument("--url",    required=True,              help="App URL to open")
    ap.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT),
                    help=f"Where to save the session JSON (default: {DEFAULT_OUTPUT})")
    args = ap.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print("  OKTA Session Capture")
    print(f"  App URL : {args.url}")
    print(f"  Save to : {out}")
    print(f"{'=' * 60}")
    print()
    print("  A browser window will open. Complete the OKTA login flow.")
    print("  When you can see the app and are fully authenticated,")
    print("  come back here and press Enter.")
    print()

    signal_file = out.parent / ".login_ready"
    signal_file.unlink(missing_ok=True)

    print(f"  Waiting for signal file: {signal_file}")
    print(f"  When logged in, run:  touch {signal_file}")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--password-store=basic", "--no-first-run", "--no-default-browser-check"],
        )
        ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(args.url, timeout=30_000)

        import time
        while not signal_file.exists():
            time.sleep(0.5)

        signal_file.unlink(missing_ok=True)
        ctx.storage_state(path=str(out))
        browser.close()

    print()
    print(f"  Session saved to: {out}")
    print()
    print("  Use it for headless regression runs:")
    print(f"    python3 ~/.claude/skills/jira_playwright_server.py \\")
    print(f"        --url {args.url} \\")
    print(f"        --storage-state {out} \\")
    print(f"        --headless")
    print()


if __name__ == "__main__":
    main()
