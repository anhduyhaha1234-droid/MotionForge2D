"""P5FIX3: give OCC_SEG2 its own prompt (the person-at-the-table scene read from its source frames)
and build the p5fix3 graph.

ONE variable: `672:582.text`.  Everything else is byte-identical to
`graphs/animate2_occ_seg2.p5fix2.api.json` (same anchor from the segment's first frame, same driver
clip, same params), except the two SaveVideo prefixes (p5fix3_occ_seg2/) and a newly declared seed,
which the packet's seed policy requires for a new run.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
BASE = PROOF / "graphs" / "animate2_occ_seg2.p5fix2.api.json"
OI = json.loads((EVID / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
PREFIX = "p5fix3_occ_seg2/animate2_occ_seg2_p5fix3"
SEED = 2026092841

# authored from the measured segment frames (P5FIX3_SEG2_SOURCE.json + the source strip preview):
# one seated young man with short pale grey hair, dark grey jacket over a black shirt, holding a
# bright blue book open in both hands at his chest; a cream cup with a light blue straw on a white
# table with a reddish-brown front edge; a white wall band, a large flat blue window panel and a
# teal floor behind him; same camera, no watermark.
NEW_PROMPT = (
    "Reference image 1 is the exact frame to redraw. Redraw it as a flat 2D cel-shaded animation "
    "illustration of the SAME shot: a young man sitting at a table and facing the camera, short "
    "pale grey hair, a dark grey jacket over a black shirt, holding a bright blue book open with "
    "both hands at his chest. A cream cup with a light blue straw stands on the white table top "
    "that has a reddish-brown front edge. Behind him: a white wall band, one large flat blue "
    "window panel and a teal floor. Keep the exact same camera, framing, scale, pose and prop "
    "positions as the reference frame. Flat colour fills, thin clean outlines, no gradients, no "
    "photographic texture, no watermark, no text overlay, no subtitles."
)


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def th(s):
    return hashlib.sha256(s.encode()).hexdigest()


g = json.loads(BASE.read_text(encoding="utf-8"))
old = g["672:582"]["inputs"]["text"]
deltas = [{"node": "672:582", "class_type": "CLIPTextEncode", "input": "text",
           "sha_before": th(old)[:16], "sha_after": th(NEW_PROMPT)[:16],
           "len_before": len(old), "len_after": len(NEW_PROMPT),
           "source": "authored for OCC_SEG2 from the measured source frames 102-119 "
                     "(P5FIX3_SEG2_SOURCE.json; the old text was the OCC certificate prompt)"}]
g["672:582"]["inputs"]["text"] = NEW_PROMPT
for nid in ("246", "292"):
    o = g[nid]["inputs"]["filename_prefix"]
    g[nid]["inputs"]["filename_prefix"] = PREFIX
    deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": "filename_prefix",
                   "template": o, "built": PREFIX})
o = g["672:597"]["inputs"]["noise_seed"]
g["672:597"]["inputs"]["noise_seed"] = SEED
deltas.append({"node": "672:597", "class_type": "SamplerCustom", "input": "noise_seed",
               "template": o, "built": SEED})
p = PROOF / "graphs" / "animate2_occ_seg2.p5fix3.api.json"
p.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
errs = []
for nid, n in g.items():
    ct = n["class_type"]
    if ct not in OI:
        errs.append(f"{nid}: {ct} not registered")
        continue
    for k in (OI[ct]["input"].get("required", {}) or {}):
        if k not in n["inputs"]:
            errs.append(f"{nid} ({ct}): missing required {k}")
out = {"artifact": "P5FIX3_GRAPH.json", "variable": "OCC_SEG2 prompt only",
       "base": "graphs/animate2_occ_seg2.p5fix2.api.json", "base_sha256": sha(BASE),
       "graph": "graphs/animate2_occ_seg2.p5fix3.api.json", "sha256": sha(p), "nodes": len(g),
       "deltas": deltas, "errors": errs,
       "unchanged": {"anchor": g["189"]["inputs"]["image"], "driver": g["240"]["inputs"]["file"],
                     "steps": g["672:591"]["inputs"]["steps"],
                     "sampler": g["672:593"]["inputs"]["sampler_name"],
                     "cfg": g["672:597"]["inputs"]["cfg"],
                     "pad": [g["P3B_PAD"]["inputs"]["target_width"],
                             g["P3B_PAD"]["inputs"]["target_height"]]},
       "prompt_old_head": old[:80], "prompt_new_head": NEW_PROMPT[:80]}
(EVID / "P5FIX3_GRAPH.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
print("graph sha", out["sha256"][:16], "nodes", len(g), "errs", len(errs),
      "prompt", deltas[0]["sha_before"], "->", deltas[0]["sha_after"])
