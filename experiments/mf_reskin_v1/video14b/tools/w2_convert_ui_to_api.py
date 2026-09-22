"""S0d primary mechanism: drive the PINNED frontend's own UI->API converter
headlessly against the running task-local server, and save the API (execution)
prompt for a UI-format run copy.

Usage (base python has playwright):
  python w2_convert_ui_to_api.py <ui_workflow.json> <out.api.json>

Mechanism: the pinned backend (commit 73c9bad4) has no server-side UI->API
converter; the conversion is a frontend job (`graphToPrompt`). This script loads
the graph into the served frontend and calls it there, so the flattening of
subgraph instances and bypass (mode 4) resolution is the frontend's own code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Wave B: same reserved engine port as the stage runner (see w2_run_stage.py
# ENGINE_PORT).  Point this at :8210 and the converter would flatten the graph
# against wave A's boot instead of the server the run is submitted to.
SERVER = "http://127.0.0.1:8310"


def _p(s: str) -> Path:
    """Normalise an MSYS path (/c/Users/...) to a Windows native path."""
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: w2_convert_ui_to_api.py <ui_workflow.json> <out.api.json>")
        return 2
    src = _p(sys.argv[1])
    dst = _p(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    ui = json.loads(src.read_text(encoding="utf-8"))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(SERVER, wait_until="load", timeout=90_000)
        page.wait_for_function(
            "() => !!window.app && typeof window.app.loadGraphData === 'function'",
            timeout=90_000,
        )
        page.wait_for_function(
            "() => typeof window.app.graphToPrompt === 'function'", timeout=90_000
        )
        res = page.evaluate(
            """async (graph) => {
                await window.app.loadGraphData(graph, true, false);
                const out = await window.app.graphToPrompt();
                return {
                    has_output: !!out && !!out.output,
                    keys: Object.keys(out || {}),
                    output: out && out.output ? out.output : null,
                    node_count: window.app.graph ? Object.keys(window.app.graph._nodes_by_id || {}).length : -1,
                };
            }""",
            ui,
        )
        browser.close()

    if errors:
        print("PAGE_ERRORS:", errors[:5])
    if not res.get("has_output"):
        print("CONVERSION_FAILED keys=", res.get("keys"))
        return 1
    out = res["output"]
    dst.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({
        "src": str(src),
        "dst": str(dst),
        "ui_nodes": len(ui.get("nodes", [])),
        "api_nodes": len(out),
        "frontend_graph_nodes": res.get("node_count"),
        "page_errors": errors[:5],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
