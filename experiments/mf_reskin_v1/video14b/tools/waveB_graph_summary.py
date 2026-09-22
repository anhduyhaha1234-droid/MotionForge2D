"""MF-V1-VIDEO14B wave B: summarise a UI workflow graph (nodes/types/modes/widgets)."""
from __future__ import annotations
import json, sys
from pathlib import Path


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def main() -> int:
    g = json.loads(_p(sys.argv[1]).read_text(encoding="utf-8"))
    nodes = g["nodes"]
    print("ui_nodes", len(nodes), "last_node_id", g.get("last_node_id"))
    for n in nodes:
        wv = n.get("widgets_values")
        s = json.dumps(wv, ensure_ascii=False)
        if len(s) > 220:
            s = s[:220] + "..."
        print(f"{n['id']:>5} {n['type']:<28} mode={n.get('mode')} title={str(n.get('title'))[:34]!r} {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
