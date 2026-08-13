#!/usr/bin/env python3
"""Render <run-dir>/viz.html from <run-dir>/run.json.

The orchestrator used to author this page inline at every node transition — a 21KB
HTML document edited in-context six times over a single run, rendering values that
run.json already holds. This script exists so the graph state is written once, as
data, and the page is derived from it.

Usage:  python3 ~/.claude/pipeline/render_viz.py <run-dir>
Then:   Artifact(file_path="<run-dir>/viz.html", ...)  — same path every time.
"""

import html
import json
import sys
from pathlib import Path

# The graph is fixed; run.json supplies only per-node state.
GRAPH = [
    ("N0",  "Init",           "run dir, run id, clean-tree check",        None),
    ("N1",  "Plan",           "project-manager — plan + runnable evals",   "project-manager"),
    ("N2",  "Research",       "scout ×1 → researcher ×3 → link-check",     "workflow"),
    ("N3",  "Skeptic",        "3 adversarial lenses on the consensus",     "workflow"),
    ("G1",  "Gate 1",         "approve findings and plan",                 None),
    ("N4",  "Branch",         "git checkout -b",                           "coding agent"),
    ("N5",  "Tests (red)",    "one named test per [auto] AC",              "coding agent"),
    ("N6",  "Implement",      "green — only what the plan calls for",      "coding agent"),
    ("N7",  "Verify",         "lint · evals · change guard · structure",   "coding agent"),
    ("N8",  "SQA",            "software-quality-engineer, 4 lenses",       "workflow"),
    ("N9",  "Docs",           "technical-writer",                          "technical-writer"),
    ("N10", "Push + PR",      "gh push, gh pr create",                     None),
    ("N11", "PR review",      "pr-reviewer, fresh context",                "pr-reviewer"),
    ("G2",  "Gate 2",         "approve reviewer tagging",                  None),
    ("N12", "Close out",      "ledger, final artifact, handoff",           None),
]

STATE_LABEL = {
    "DONE": "done", "RUNNING": "running", "FAILED": "failed",
    "WAITING": "gate", "LOOPING": "looping", "PENDING": "pending",
}


def esc(v):
    return html.escape(str(v if v is not None else ""))


def node_state(run, nid):
    """Gates carry their own key; everything else lives under nodes{}."""
    if nid.startswith("G"):
        g = run.get(f"gate{nid[1:]}") or run.get("gates", {}).get(nid, {})
        if not g:
            return "PENDING", ""
        if g.get("decision"):
            return "DONE", g.get("decision", "")
        return "WAITING", g.get("reason", "awaiting human")
    n = run.get("nodes", {}).get(nid, {})
    return n.get("status", "PENDING"), n.get("note", "")


def render(run):
    rows = []
    for nid, title, detail, agent in GRAPH:
        status, note = node_state(run, nid)
        cls = STATE_LABEL.get(status, "pending")
        gate = " gate" if nid.startswith("G") else ""
        rows.append(f"""
      <div class="node s-{cls}{gate}">
        <div class="dot"></div>
        <div class="card">
          <div class="card-head">
            <span class="nid">{esc(nid)}</span>
            <span class="ntitle">{esc(title)}</span>
            <span class="badge b-{cls}">{esc(status.lower())}</span>
          </div>
          <div class="nagent">{esc(detail)}{f' · {esc(agent)}' if agent else ''}</div>
          {f'<div class="nnote">{esc(note)}</div>' if note else ''}
        </div>
      </div>""")

    loops, caps = run.get("loops", {}), run.get("caps", {})
    loop_html = []
    for name, used in loops.items():
        cap = caps.get(name, {"skeptic": 2, "sqa": 3, "prReview": 2, "infraRetry": 2}.get(name, 2))
        pips = "".join(f'<span class="pip{" used" if i < used else ""}"></span>' for i in range(cap))
        loop_html.append(f"""
      <div class="loop">
        <div class="loop-head"><span class="loop-name">{esc(name)}</span>
        <span class="loop-count">{used}/{cap}</span></div>
        <div class="pips">{pips}</div>
      </div>""")

    br = run.get("blastRadius", {}) or {}
    br_rows = ""
    if br:
        def cell(label, actual, expected, trip):
            over = actual is not None and trip is not None and actual > trip
            return (f'<tr><td>{esc(label)}</td><td class="num">{esc(expected)}</td>'
                    f'<td class="num">{esc(trip)}</td>'
                    f'<td class="num{" over" if over else ""}">'
                    f'{esc(actual) if actual is not None else "—"}</td></tr>')
        br_rows = ("<table class=\"tbl\"><thead><tr><th></th><th>estimate</th>"
                   "<th>trip at</th><th>actual</th></tr></thead><tbody>"
                   + cell("files", br.get("actual_files"), br.get("expected_files"), br.get("trip_files"))
                   + cell("lines", br.get("actual_lines"), br.get("expected_lines"), br.get("trip_lines"))
                   + "</tbody></table>")

    ev = run.get("evals", {}) or {}
    ev_html = ""
    if ev:
        if isinstance(ev.get("results"), list):
            body = "".join(
                f'<tr><td>{esc(r.get("id"))}</td><td>{esc(r.get("desc"))}</td>'
                f'<td class="v-{esc(str(r.get("status","")).lower())}">{esc(r.get("status"))}</td></tr>'
                for r in ev["results"])
            ev_html = f'<table class="tbl"><tbody>{body}</tbody></table>'
        else:
            ev_html = ('<div class="kv">'
                       + "".join(f'<div><span class="k">{esc(k)}</span>{esc(v)}</div>'
                                 for k, v in ev.items()) + "</div>")

    inc = run.get("incidents", []) or []
    inc_html = "".join(
        f'<div class="incident"><div class="k">{esc(i.get("at"))}</div>'
        f'<div>{esc(i.get("defect"))}</div>'
        f'<div class="muted">detected by {esc(i.get("detectedBy"))} · cost {esc(i.get("cost"))}</div>'
        f'<div class="fix">fix: {esc(i.get("fix"))}</div></div>' for i in inc)

    def panel(title, body):
        return f'<section class="panel"><h2>{esc(title)}</h2>{body or "<p class=empty>—</p>"}</section>'

    status = run.get("status", "RUNNING")
    return f"""<title>Pipeline · {esc(run.get('runId', 'run'))}</title>
<style>
  :root {{
    --bg:#fbfbfa; --fg:#1f1e1c; --muted:#6b6862; --line:#e3e1dc; --card:#fff;
    --done:#3f7d58; --running:#b06a1e; --failed:#b3402f; --gate:#7a5cad; --pending:#a5a29b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#171614; --fg:#eceae5; --muted:#98948c; --line:#302e2a; --card:#1f1e1b;
      --done:#6fb98a; --running:#d9a05b; --failed:#e08573; --gate:#a68cd4; --pending:#5d5a54; }}
  }}
  :root[data-theme="dark"] {{ --bg:#171614; --fg:#eceae5; --muted:#98948c; --line:#302e2a; --card:#1f1e1b;
    --done:#6fb98a; --running:#d9a05b; --failed:#e08573; --gate:#a68cd4; --pending:#5d5a54; }}
  :root[data-theme="light"] {{ --bg:#fbfbfa; --fg:#1f1e1c; --muted:#6b6862; --line:#e3e1dc; --card:#fff;
    --done:#3f7d58; --running:#b06a1e; --failed:#b3402f; --gate:#7a5cad; --pending:#a5a29b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif; }}
  .wrap {{ max-width:940px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }}
  .masthead {{ border-bottom:1px solid var(--line); padding-bottom:1.25rem; margin-bottom:2rem; }}
  .eyebrow {{ font-size:.75rem; letter-spacing:.09em; text-transform:uppercase; color:var(--muted); }}
  .goal {{ font-size:1.5rem; font-weight:600; margin:.4rem 0 .5rem; line-height:1.3; }}
  .runid {{ font-family:ui-monospace,monospace; font-size:.8rem; color:var(--muted); }}
  .st {{ display:inline-block; margin-left:.5rem; padding:.1rem .5rem; border-radius:999px;
    font-size:.7rem; letter-spacing:.05em; background:var(--line); }}
  .graph {{ position:relative; margin:0 0 2.5rem; }}
  .graph::before {{ content:""; position:absolute; left:5px; top:12px; bottom:12px; width:2px; background:var(--line); }}
  .node {{ position:relative; padding-left:2rem; margin-bottom:.55rem; }}
  .dot {{ position:absolute; left:0; top:1rem; width:12px; height:12px; border-radius:50%;
    background:var(--bg); border:2px solid var(--pending); }}
  .s-done .dot {{ border-color:var(--done); background:var(--done); }}
  .s-running .dot {{ border-color:var(--running); background:var(--running); }}
  .s-failed .dot {{ border-color:var(--failed); background:var(--failed); }}
  .s-gate .dot {{ border-color:var(--gate); background:var(--gate); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:.7rem .9rem; }}
  .gate .card {{ border-color:var(--gate); border-left-width:3px; }}
  .card-head {{ display:flex; align-items:baseline; gap:.6rem; flex-wrap:wrap; }}
  .nid {{ font-family:ui-monospace,monospace; font-size:.75rem; color:var(--muted); }}
  .ntitle {{ font-weight:600; }}
  .badge {{ margin-left:auto; font-size:.68rem; letter-spacing:.06em; text-transform:uppercase;
    padding:.1rem .45rem; border-radius:4px; background:var(--line); color:var(--muted); }}
  .b-done {{ color:var(--done); }} .b-running {{ color:var(--running); }}
  .b-failed {{ color:var(--failed); }} .b-gate {{ color:var(--gate); }}
  .nagent {{ font-size:.82rem; color:var(--muted); margin-top:.15rem; }}
  .nnote {{ font-size:.85rem; margin-top:.4rem; padding-top:.4rem; border-top:1px solid var(--line); }}
  .panel {{ margin-bottom:1.75rem; }}
  .panel h2 {{ font-size:.78rem; letter-spacing:.09em; text-transform:uppercase; color:var(--muted);
    margin:0 0 .7rem; font-weight:600; }}
  .loops {{ display:flex; gap:1.5rem; flex-wrap:wrap; }}
  .loop-head {{ display:flex; gap:.5rem; align-items:baseline; }}
  .loop-name {{ font-size:.85rem; }} .loop-count {{ font-family:ui-monospace,monospace; font-size:.78rem; color:var(--muted); }}
  .pips {{ display:flex; gap:4px; margin-top:.3rem; }}
  .pip {{ width:22px; height:5px; border-radius:3px; background:var(--line); }}
  .pip.used {{ background:var(--running); }}
  .tblwrap {{ overflow-x:auto; }}
  .tbl {{ border-collapse:collapse; width:100%; font-size:.85rem; }}
  .tbl th {{ text-align:left; font-weight:500; color:var(--muted); font-size:.75rem;
    padding:.3rem .6rem .3rem 0; border-bottom:1px solid var(--line); }}
  .tbl td {{ padding:.35rem .6rem .35rem 0; border-bottom:1px solid var(--line); }}
  .num {{ font-family:ui-monospace,monospace; text-align:right; }}
  .num.over {{ color:var(--failed); font-weight:600; }}
  .v-pass {{ color:var(--done); }} .v-fail {{ color:var(--failed); }}
  .kv div {{ font-size:.85rem; padding:.2rem 0; }}
  .k {{ color:var(--muted); display:inline-block; min-width:9rem; }}
  .incident {{ border-left:3px solid var(--failed); padding:.5rem .8rem; margin-bottom:.7rem;
    background:var(--card); border-radius:0 6px 6px 0; font-size:.85rem; }}
  .muted {{ color:var(--muted); font-size:.8rem; }}
  .fix {{ color:var(--done); font-size:.8rem; margin-top:.2rem; }}
  .empty {{ color:var(--muted); font-size:.85rem; margin:0; }}
</style>
<div class="wrap">
  <header class="masthead">
    <div class="eyebrow">Graph pipeline</div>
    <h1 class="goal">{esc(run.get('goal', ''))}</h1>
    <div class="runid">{esc(run.get('runId', ''))} · {esc(run.get('repo', ''))}
      · branch {esc(run.get('branch', '—'))}<span class="st">{esc(status)}</span></div>
  </header>
  <div class="graph">{''.join(rows)}</div>
  {panel('Loops against caps', f'<div class="loops">{"".join(loop_html)}</div>' if loop_html else '')}
  {panel('Blast radius', f'<div class="tblwrap">{br_rows}</div>' if br_rows else '')}
  {panel('Evals', f'<div class="tblwrap">{ev_html}</div>' if ev_html else '')}
  {panel('Incidents', inc_html)}
</div>
"""


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: render_viz.py <run-dir>")
    run_dir = Path(sys.argv[1]).expanduser()
    run_json = run_dir / "run.json"
    if not run_json.exists():
        sys.exit(f"no run.json at {run_json}")
    run = json.loads(run_json.read_text())
    out = run_dir / "viz.html"
    out.write_text(render(run))
    print(f"wrote {out} ({out.stat().st_size:,}B) — node {run.get('currentNode')}, status {run.get('status')}")


if __name__ == "__main__":
    main()
