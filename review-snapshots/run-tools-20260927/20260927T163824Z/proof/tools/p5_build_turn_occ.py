"""P5-TURN/OCC: clone the P3b graph per shot with declared deltas only, and report the cache wiring
needed for P6.

Per shot the deltas are exactly: LoadImage -> that shot's P2 anchor, LoadVideo -> that shot's pinned
source window, the two SaveVideo prefixes -> p5_<shot>/, the sampler seed -> a new declared
constant.  Geometry (P3B_PAD 640x368), models, steps, sampler, cache node, context windows are
carried over untouched from the p3b graph.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
BASE = PROOF / "graphs" / "animate2_book.p3b.api.json"
SHOTS = {
    "TURN": {"anchor": "anchor_turn_p2_00001_.png", "drive": "TURN_795_src.mp4",
             "prefix": "p5_turn/animate2_turn_p5", "seed": 2026092801},
    "OCC": {"anchor": "anchor_occ_p2_00001_.png", "drive": "OCC_14768_src.mp4",
            "prefix": "p5_occ/animate2_occ_p5", "seed": 2026092802},
}


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


base = json.loads(BASE.read_text(encoding="utf-8"))
oi = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
out = {"artifact": "P5_TURN_OCC_GRAPHS.json", "base_graph": "graphs/animate2_book.p3b.api.json",
       "base_sha256": sha(BASE), "shots": {}, "cache_wiring": {}, "validation": {}}

# cache wiring for P6 (who feeds WanAnimate2Cache and who consumes it)
node = base.get("672:594")
out["cache_wiring"]["node"] = {"id": "672:594", "class_type": (node or {}).get("class_type"),
                               "inputs": {k: v for k, v in (node or {}).get("inputs", {}).items()
                                          if not (isinstance(v, list) and len(v) == 2)},
                               "links": {k: v for k, v in (node or {}).get("inputs", {}).items()
                                         if isinstance(v, list) and len(v) == 2}}
out["cache_wiring"]["consumers"] = [
    {"node": nid, "class_type": n["class_type"], "input": k, "from": v}
    for nid, n in base.items() for k, v in n["inputs"].items()
    if isinstance(v, list) and len(v) == 2 and v[0] == "672:594"]

for shot, cfg in SHOTS.items():
    g = json.loads(BASE.read_text(encoding="utf-8"))
    deltas = []
    for nid, key, new in (("189", "image", cfg["anchor"]), ("240", "file", cfg["drive"]),
                          ("672:597", "noise_seed", cfg["seed"])):
        old = g[nid]["inputs"][key]
        g[nid]["inputs"][key] = new
        deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": key,
                       "template": old, "built": new})
    for nid in ("246", "292"):
        old = g[nid]["inputs"]["filename_prefix"]
        g[nid]["inputs"]["filename_prefix"] = cfg["prefix"]
        deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": "filename_prefix",
                       "template": old, "built": cfg["prefix"]})
    p = PROOF / "graphs" / f"animate2_{shot.lower()}.p5.api.json"
    p.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = []
    for nid, n in g.items():
        ct = n["class_type"]
        if ct not in oi:
            errs.append(f"{nid}: {ct} not registered")
            continue
        for k in (oi[ct]["input"].get("required", {}) or {}):
            if k not in n["inputs"]:
                errs.append(f"{nid} ({ct}): missing required {k}")
    out["shots"][shot] = {"graph": f"graphs/animate2_{shot.lower()}.p5.api.json",
                          "sha256": sha(p), "nodes": len(g), "deltas": deltas,
                          "seed": cfg["seed"],
                          "anchor_present": (PROOF / "inputs" / cfg["anchor"]).is_file(),
                          "drive_present": (PROOF / "inputs" / cfg["drive"]).is_file(),
                          "pad_target": [g["P3B_PAD"]["inputs"]["target_width"],
                                         g["P3B_PAD"]["inputs"]["target_height"]],
                          "context": [g["672:586"]["inputs"]["context_length"],
                                      g["672:586"]["inputs"]["context_overlap"]]}
    out["validation"][shot] = {"errors": errs, "ok": not errs, "nodes": len(g)}
    print(f"{shot}: {len(g)} nodes, seed {cfg['seed']}, errors {errs}, sha {out['shots'][shot]['sha256'][:16]}")
(PROOF / "evidence" / "P5_TURN_OCC_GRAPHS.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"cache": out["cache_wiring"]}, indent=1, ensure_ascii=False)[:900])
