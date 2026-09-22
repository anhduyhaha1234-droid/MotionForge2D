"""S0d conversion repair: flatten the frontend's dotted autogrow keys back into
the list form the PINNED BACKEND expects.

Measured defect (BOOK attempt 1, prompt rejected in 0.34 s):
  MF_COMFY_INVALID_GRAPH {node_id: "672:636", class_type: "ComfyMathExpression",
                          input: "values"}
The pinned frontend emitted `"values.a": ["672:537", 2], "values.b": [...]` while
the pinned backend's ComfyMathExpression schema for that input is
COMFY_AUTOGROW_V3 (template names a..z, min 1) -> it needs a single `values`
LIST. Only ComfyMathExpression nodes are touched: other dotted keys in the same
graphs (e.g. SaveVideo's "format.codec") are accepted by the backend as-is and
are left exactly as converted.

usage: python w2_fix_autogrow.py <api_in.json> <api_out.json>
"""
from __future__ import annotations

import json
import re
import string
import sys
from pathlib import Path

NAMES = list(string.ascii_lowercase)


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def main() -> int:
    src, dst = _p(sys.argv[1]), _p(sys.argv[2])
    g = json.loads(src.read_text(encoding="utf-8"))
    fixed = []
    for nid, node in g.items():
        if node.get("class_type") != "ComfyMathExpression":
            continue
        ins = node["inputs"]
        dotted = {m.group(1): k for k in list(ins)
                  for m in [re.fullmatch(r"values\.([a-z])", k)] if m}
        if not dotted:
            continue
        values = [ins.pop(f"values.{n}") for n in NAMES if n in dotted]
        ins["values"] = values
        fixed.append({"node": nid, "values": values,
                      "expression": ins.get("expression")})
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"src": str(src), "dst": str(dst), "fixed_nodes": fixed,
                      "fixed_count": len(fixed)}, indent=1, ensure_ascii=False))
    return 0 if fixed else 1


if __name__ == "__main__":
    raise SystemExit(main())
