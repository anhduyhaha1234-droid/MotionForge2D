"""S0d conversion repair (generalised): the pinned FRONTEND (comfyui_frontend_package
1.52.7) serialises autogrow inputs as dotted keys (`values.a`, `inputs.input0`),
while the pinned BACKEND (ComfyUI v0.37.0, commit 73c9bad4) declares those inputs as
COMFY_AUTOGROW_V3 and requires a single KEYED value (dict).

Measured on the real server (two rejected /prompt attempts, both kept as evidence):
  attempt 1  -> ComfyMathExpression 672:636  missing 'values'
  attempt 2  -> CreateList          672:648  missing 'inputs'

A dotted key is only collapsed when the PARENT key is declared by the live
/object_info for that exact class AND its declared type is an autogrow type or
carries a template `names` list. Legitimately nested widget keys (e.g. SaveVideo's
"format.codec", whose parent 'format' is a plain COMBO with no template) are left
exactly as the frontend produced them.

usage: python w2_fix_dotted.py <api_in.json> <api_out.json> <object_info.json>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DOTTED = re.compile(r"^(.+)\.([A-Za-z_][A-Za-z_0-9]*)$")


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def decl(oi: dict, cls: str, key: str):
    spec = (oi.get(cls) or {}).get("input") or {}
    for group in ("required", "optional"):
        e = (spec.get(group) or {}).get(key)
        if e is not None:
            return e
    return None


def is_autogrow(entry) -> bool:
    if not isinstance(entry, list) or not entry:
        return False
    t = entry[0]
    if isinstance(t, str) and t.startswith("COMFY_AUTOGROW"):
        return True
    meta = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
    return bool(meta.get("template"))


def order_key(name: str, names: list[str]) -> tuple:
    if names and name in names:
        return (0, names.index(name))
    m = re.search(r"(\d+)$", name)
    if m:
        return (1, int(m.group(1)))
    return (2, name)


def main() -> int:
    src, dst, oi_path = _p(sys.argv[1]), _p(sys.argv[2]), _p(sys.argv[3])
    g = json.loads(src.read_text(encoding="utf-8"))
    oi = json.loads(oi_path.read_text(encoding="utf-8"))

    report = {"fixed": [], "left_as_is": []}
    for nid, node in g.items():
        cls = node.get("class_type")
        ins = node.get("inputs") or {}
        groups: dict[str, list[str]] = {}
        for k in list(ins):
            m = DOTTED.match(k)
            if not m:
                continue
            parent, item = m.group(1), m.group(2)
            entry = decl(oi, cls, parent)
            if entry is not None and is_autogrow(entry):
                groups.setdefault(parent, []).append(item)
            else:
                report["left_as_is"].append({"node": nid, "class_type": cls,
                                             "key": k, "reason": "parent not autogrow"})
        for parent, items in groups.items():
            entry = decl(oi, cls, parent)
            meta = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
            names = (meta.get("template") or {}).get("names") or []
            items = sorted(items, key=lambda n: order_key(n, names))
            values = {i: ins.pop(f"{parent}.{i}") for i in items}
            ins[parent] = values
            report["fixed"].append({"node": nid, "class_type": cls, "parent": parent,
                                    "items": items, "value_count": len(values)})

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    report.update({"src": str(src), "dst": str(dst),
                   "fixed_count": len(report["fixed"]),
                   "left_count": len(report["left_as_is"])})
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
