"""MF-V1-VIDEO14B wave B step B3 — autogrow serialisation SHIM.

Measured problem (both rejections reproduced on this boot and kept as evidence):

  A. the pinned FRONTEND (comfyui_frontend_package 1.52.7) serialises an autogrow
     input's slots as DOTTED keys (`values.a`, `inputs.input0`,
     `terminations.termination0`), and never writes the parent key itself;
  B. the pinned BACKEND (ComfyUI 0.37.0 commit 73c9bad4, validation in
     `execution.py` + `comfy_api/latest/_io.py::Autogrow`) expands the schema
     against the SUPPLIED keys: `expected_id = finalize_prefix(prefix, name)`
     (i.e. `values.a`) is looked up in the live inputs, and the first `min` of
     them are REQUIRED.  A collapsed `values: {...}` dict therefore fails with
     `required_input_missing: a`;
  C. the frozen COMFY adapter's own pre-POST validator
     (`mf_comfy.adapter._validate_graph`, wt-comfy @3105006) checks the declared
     required NAMES from `/object_info` -- which for those nodes is the parent
     (`values`, `inputs`, `terminations`) -- so a graph carrying only the dotted
     keys is refused locally with `MF_COMFY_INVALID_GRAPH` and never reaches the
     wire.

Both pure forms are therefore rejected by one of the two validators (evidence:
`raw/run_b3_book4s/` = dotted form refused locally, `raw/run_b3_book4s_a2/` =
collapsed-dict form refused by the server).  The shim keeps the frontend's dotted
keys (what the server executes) and ADDS the parent key as the equivalent nested
dict, so the declared name exists for the local validator.  The backend only
iterates the FINALIZED schema when validating and building node inputs, so an
extra key that is not part of that schema is inert -- it is never passed to the
node.  No model, sampler, step, prompt or geometry value is touched.

usage: python waveB_autogrow_shim.py <frontend.api.json> <out.api.json> <object_info.json>
"""
from __future__ import annotations

import hashlib
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


def declared(oi: dict, cls: str, key: str):
    spec = (oi.get(cls) or {}).get("input") or {}
    for group in ("required", "optional"):
        entry = (spec.get(group) or {}).get(key)
        if entry is not None:
            return entry
    return None


def is_autogrow(entry) -> bool:
    if not isinstance(entry, list) or not entry:
        return False
    t = entry[0]
    if isinstance(t, str) and t.startswith("COMFY_AUTOGROW"):
        return True
    meta = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
    return bool(meta.get("template"))


def main() -> int:
    src, dst, oi_path = _p(sys.argv[1]), _p(sys.argv[2]), _p(sys.argv[3])
    raw = src.read_bytes()
    g = json.loads(raw.decode("utf-8"))
    oi = json.loads(oi_path.read_text(encoding="utf-8"))

    shimmed, left = [], []
    for nid, node in g.items():
        cls = node.get("class_type")
        ins = node.get("inputs") or {}
        groups: dict[str, dict] = {}
        for k in list(ins):
            m = DOTTED.match(k)
            if not m:
                continue
            parent, item = m.group(1), m.group(2)
            entry = declared(oi, cls, parent)
            if entry is not None and is_autogrow(entry):
                groups.setdefault(parent, {})[item] = ins[k]
            else:
                left.append({"node": nid, "class_type": cls, "key": k,
                             "reason": "parent not a declared autogrow input"})
        for parent, nested in groups.items():
            if parent in ins:
                raise SystemExit(f"REFUSED: node {nid} already carries parent key {parent!r}")
            ins[parent] = nested
            shimmed.append({"node": nid, "class_type": cls, "parent": parent,
                            "slots": sorted(nested), "slot_count": len(nested),
                            "dotted_keys_kept": [f"{parent}.{s}" for s in sorted(nested)]})

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    record = {
        "in": str(src), "out": str(dst),
        "in_sha256": hashlib.sha256(raw).hexdigest(),
        "out_sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
        "api_nodes": len(g),
        "shimmed_count": len(shimmed), "shimmed": shimmed,
        "left_dotted_count": len(left), "left_dotted": left,
        "note": "dotted keys are KEPT (server requirement) and the parent key is ADDED as a "
                "nested dict (frozen adapter validator requirement); solver/value semantics "
                "unchanged",
    }
    out_rec = dst.with_suffix(".shim.json")
    out_rec.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("in_sha256", "out_sha256", "api_nodes",
                                             "shimmed_count", "left_dotted_count")}, indent=1))
    for s in shimmed:
        print("  SHIM", s["node"], s["class_type"], s["parent"], s["slots"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
