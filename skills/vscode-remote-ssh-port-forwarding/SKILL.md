---
name: vscode-remote-ssh-port-forwarding
description: "Debug dev servers (Vite, webpack, Flask) that do not appear in the browser when running on a remote EC2 host via VS Code Remote SSH. Use for port-forwarding failures, localhost binding, and tunnel troubleshooting."
tags: [vscode, ssh, port-forwarding, ec2, dev-server]
---

## How VS Code Remote SSH port forwarding works

VS Code auto-detects listening ports on the remote host and forwards them to `localhost:<port>` on your local machine. You access the app via `localhost:5173` on your laptop — **not** the EC2 public IP. Port does not need to be open in the EC2 security group.

Forwarded ports appear in the **PORTS** panel (bottom panel, tab next to TERMINAL/OUTPUT/PROBLEMS). Open it with `Ctrl+Shift+P` → "Focus on Ports View".

## Vite host binding

`--host localhost` (binds to 127.0.0.1) is fine under VS Code tunneling. VS Code will still forward it. Only use `--host 0.0.0.0` if you need direct access via the EC2 public IP (requires the port open in the security group).

## Common failure: stale port entry

If the dev server was killed and restarted, VS Code can hold a stale PORTS entry that blocks re-forwarding.

**Symptoms:** server is running, port is listening, but browser shows nothing or connection refused on local machine.

**Fix:**
1. Kill the dev server: `kill <pid>` or `pkill -f vite`
2. In VS Code PORTS panel: right-click the stale entry → **Stop Forwarding Port**
3. Restart the dev server: `npm run dev`
4. VS Code re-detects the port and adds a fresh entry — click the globe icon or forwarded address to open

## Quick reference

```bash
# Find and kill vite
ps aux | grep vite | grep -v grep
kill <pid>

# Restart (default host is fine under VS Code SSH)
cd <project>/web && npm run dev
```

**Why:** VS Code SSH tunneling works even with localhost-only binding. The stale PORTS entry is the culprit when it stops working after a restart — not a host binding or security group issue.
