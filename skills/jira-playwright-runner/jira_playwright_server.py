#!/usr/bin/env python3
"""
jira_playwright_server.py — Persistent Playwright browser server

Started by the sqa-regression-tester agent as a background process.
Communicates via JSON files in /tmp/pw_session/.

Commands (write to /tmp/pw_session/cmd.json):
  {"action": "execute",    "code": "...",  "screenshot": "/path/shot.png"}
  {"action": "goto",       "url":  "...",  "screenshot": "/path/shot.png"}
  {"action": "screenshot", "path": "/path/shot.png"}
  {"action": "quit"}

Results (appears at /tmp/pw_session/result.json):
  {"status": "ok",    "screenshot": "/path/shot.png"}
  {"status": "error", "message":   "...", "screenshot": "/path/shot.png"}

Ready signal: /tmp/pw_session/ready  (created once browser is open)
"""

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

WORK_DIR = Path("/tmp/pw_session")
IDLE_TIMEOUT = 300  # auto-shutdown after 5 min with no commands


def main():
    ap = argparse.ArgumentParser(description="Persistent Playwright browser server")
    ap.add_argument("--url",           required=True,         help="Initial URL to open")
    ap.add_argument("--headless",      action="store_true",   help="Run headless")
    ap.add_argument("--work-dir",      default=str(WORK_DIR), help="Temp file directory")
    ap.add_argument("--storage-state", default=None,
                    help="Path to saved session JSON from jira_playwright_login.py")
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    for name in ("cmd.json", "result.json", "ready", "error"):
        (work / name).unlink(missing_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        ctx_kwargs = {"viewport": {"width": 1440, "height": 900}}
        if args.storage_state:
            ctx_kwargs["storage_state"] = args.storage_state
        ctx = browser.new_context(**ctx_kwargs)
        page    = ctx.new_page()

        try:
            page.goto(args.url, timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                pass
        except Exception as e:
            (work / "error").write_text(str(e))
            browser.close()
            sys.exit(1)

        (work / "ready").write_text("ready")
        print(f"[pw-server] ready — {args.url}", flush=True)

        last_activity = time.time()

        while True:
            cmd_file = work / "cmd.json"

            if not cmd_file.exists():
                if time.time() - last_activity > IDLE_TIMEOUT:
                    print("[pw-server] idle timeout — shutting down", flush=True)
                    break
                time.sleep(0.2)
                continue

            last_activity = time.time()

            try:
                cmd = json.loads(cmd_file.read_text())
                cmd_file.unlink()
            except Exception as e:
                _write_result(work, None, error=f"Bad command JSON: {e}")
                continue

            action = cmd.get("action", "")

            if action == "quit":
                print("[pw-server] quit received — shutting down", flush=True)
                break

            sc_path = cmd.get("screenshot") or str(work / "screenshot.png")
            error_msg = None

            try:
                if action == "goto":
                    page.goto(cmd["url"], timeout=30_000)
                elif action == "execute":
                    exec(cmd["code"], {"page": page})  # noqa: S102
                elif action == "screenshot":
                    pass
                else:
                    error_msg = f"Unknown action: {action!r}"

                if not error_msg:
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except PWTimeout:
                        pass
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"

            try:
                page.screenshot(path=sc_path, full_page=False)
            except Exception as sc_err:
                if not error_msg:
                    error_msg = f"Screenshot failed: {sc_err}"
                sc_path = None

            _write_result(work, sc_path, error=error_msg)
            print(f"[pw-server] {action} → {'error' if error_msg else 'ok'}", flush=True)

        browser.close()
        print("[pw-server] shutdown complete", flush=True)


def _write_result(work, screenshot, error=None):
    if error:
        payload = {"status": "error", "message": error}
        if screenshot:
            payload["screenshot"] = screenshot
    else:
        payload = {"status": "ok", "screenshot": screenshot}
    (work / "result.json").write_text(json.dumps(payload))


if __name__ == "__main__":
    main()
