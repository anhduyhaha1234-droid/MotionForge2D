"""P5 (overlap hypothesis) + P6 (cache off) graph builders, both cloned from the p3b BOOK graph.

P5 single hypothesis: `672:586 ContextWindowsManual.context_overlap` 8 -> 16 (context_length stays
21).  Seed kept at the P3b value 582699151003550 so the ONLY difference against the P3b clip is that
one field - which is what makes the seam measurement comparable.

P6 cache off: the cache node `672:594 WanAnimate2Cache` takes model <- 672:588 and feeds
672:591 BasicScheduler.model and 672:592 ModelSamplingSD3.model; "off" therefore means REMOVE it and
wire both consumers straight to 672:588.  Same seed/params as P3b.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
BASE = PROOF / "graphs" / "animate2_book.p3b.api.json"
SEED_BOOK = 582699151003550


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


oi = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
report = {"artifact": "P5_P6_GRAPHS.json", "base_sha256": sha(BASE), "graphs": {}}


def validate(g):
    errs = []
    for nid, n in g.items():
        ct = n["class_type"]
        if ct not in oi:
            errs.append(f"{nid}: {ct} not registered")
            continue
        for k in (oi[ct]["input"].get("required", {}) or {}):
            if k not in n["inputs"]:
                errs.append(f"{nid} ({ct}): missing required {k}")
    return errs


# ---- P5: overlap 8 -> 16 -----------------------------------------------------------------
g = json.loads(BASE.read_text(encoding="utf-8"))
deltas = []
old = g["672:586"]["inputs"]["context_overlap"]
g["672:586"]["inputs"]["context_overlap"] = 16
deltas.append({"node": "672:586", "class_type": "ContextWindowsManual", "input": "context_overlap",
               "template": old, "built": 16})
for nid in ("246", "292"):
    o = g[nid]["inputs"]["filename_prefix"]
    g[nid]["inputs"]["filename_prefix"] = "p5_book_overlap16/animate2_book_ov16"
    deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": "filename_prefix",
                   "template": o, "built": "p5_book_overlap16/animate2_book_ov16"})
p5 = PROOF / "graphs" / "animate2_book.p5overlap16.api.json"
p5.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
report["graphs"]["P5_OVERLAP16"] = {
    "graph": "graphs/animate2_book.p5overlap16.api.json", "sha256": sha(p5), "nodes": len(g),
    "deltas": deltas, "hypothesis": "raising the context-window overlap 8->16 reduces the "
    "frame-to-frame elevation measured around the 80->81 join",
    "context_after": [g["672:586"]["inputs"]["context_length"],
                      g["672:586"]["inputs"]["context_overlap"]],
    "seed": g["672:597"]["inputs"]["noise_seed"], "errors": validate(g),
    "windows_note": "stride becomes context_length - overlap = 5 frames per window instead of 13, "
                    "so this run does more window passes"}
# ---- P6: cache node removed --------------------------------------------------------------
g2 = json.loads(BASE.read_text(encoding="utf-8"))
consumers = [{"node": nid, "input": k} for nid, n in g2.items() for k, v in n["inputs"].items()
             if isinstance(v, list) and len(v) == 2 and v[0] == "672:594"]
cache_node = {"node": "672:594", "class_type": g2["672:594"]["class_type"],
              "was_inputs": {k: v for k, v in g2["672:594"]["inputs"].items()}}
del g2["672:594"]
rewired = []
for c in consumers:
    old_v = g2[c["node"]]["inputs"][c["input"]]
    g2[c["node"]]["inputs"][c["input"]] = ["672:588", 0]
    rewired.append({"node": c["node"], "class_type": g2[c["node"]]["class_type"],
                    "input": c["input"], "from": old_v, "to": ["672:588", 0]})
for nid in ("246", "292"):
    o = g2[nid]["inputs"]["filename_prefix"]
    g2[nid]["inputs"]["filename_prefix"] = "p6_book_nocache/animate2_book_nocache"
    rewired.append({"node": nid, "class_type": g2[nid]["class_type"], "input": "filename_prefix",
                    "template": o, "built": "p6_book_nocache/animate2_book_nocache"})
p6 = PROOF / "graphs" / "animate2_book.p6nocache.api.json"
p6.write_text(json.dumps(g2, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
report["graphs"]["P6_NOCACHE"] = {
    "graph": "graphs/animate2_book.p6nocache.api.json", "sha256": sha(p6), "nodes": len(g2),
    "method": "the cache node was REMOVED and its two consumers were wired straight to 672:588 "
              "(the node has no toggle input; device/dtype are its only settings)",
    "removed": cache_node, "rewired": rewired, "errors": validate(g2),
    "seed": g2["672:597"]["inputs"]["noise_seed"], "nodes_after": len(g2)}
(PROOF / "evidence" / "P5_P6_GRAPHS.json").write_text(
    json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"P5": {"sha": report["graphs"]["P5_OVERLAP16"]["sha256"][:16],
                         "errors": report["graphs"]["P5_OVERLAP16"]["errors"],
                         "context": report["graphs"]["P5_OVERLAP16"]["context_after"]},
                  "P6": {"sha": report["graphs"]["P6_NOCACHE"]["sha256"][:16],
                         "errors": report["graphs"]["P6_NOCACHE"]["errors"],
                         "removed": cache_node["node"], "rewired": rewired}},
                 indent=1, ensure_ascii=False))
