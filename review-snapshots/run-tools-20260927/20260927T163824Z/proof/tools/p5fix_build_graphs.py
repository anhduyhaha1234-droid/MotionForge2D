"""P5fix graph builder: per-unit prompt text (the ONE fix) + cache node off (the profile decision).

Delta list per shot, nothing else:
  1. node 672:582 CLIPTextEncode.text  -> the unit's I1 prompt, verbatim
     (TURN sha eca92d5e…, OCC sha b2a1e176…; the wrong BOOK prompt was 540d16b7…)
  2. node 672:594 WanAnimate2Cache REMOVED, its two consumers rewired to 672:588
     (proven pixel-neutral in P6; the manager pinned cache OFF for the profile)
  3. SaveVideo prefixes -> p5fix_<unit>/
  4. SamplerCustom.noise_seed -> new declared constants (TURN 2026092811, OCC 2026092812)
Negative prompt, models, LoRA, steps, sampler, shift, context and the pad are untouched.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
R27 = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                   r"mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B/graph_proposals")
OI = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
SHOTS = {"TURN": {"base": "animate2_turn.p5.api.json", "i1": "anchor_turn.i1.api.json",
                  "prefix": "p5fix_turn/animate2_turn_p5fix", "seed": 2026092811},
         "OCC": {"base": "animate2_occ.p5.api.json", "i1": "anchor_occ.i1.api.json",
                 "prefix": "p5fix_occ/animate2_occ_p5fix", "seed": 2026092812}}


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def th(s):
    return hashlib.sha256(s.encode()).hexdigest()


out = {"artifact": "P5FIX_GRAPHS.json", "fix": "per-unit positive prompt from I1 + cache node off",
       "why": "the p5 graphs carried the BOOK prompt (672:582 sha 540d16b7b7300c40 in all three "
              "graphs) so TURN/OCC rendered a seated-reader scene", "shots": {}}
for shot, cfg in SHOTS.items():
    base = PROOF / "graphs" / cfg["base"]
    g = json.loads(base.read_text(encoding="utf-8"))
    t = json.loads((R27 / cfg["i1"]).read_text(encoding="utf-8"))["75:74"]["inputs"]["text"]
    old = g["672:582"]["inputs"]["text"]
    deltas = [{"node": "672:582", "class_type": "CLIPTextEncode", "input": "text",
               "sha_before": th(old)[:16], "sha_after": th(t)[:16],
               "len_before": len(old), "len_after": len(t),
               "source": f"R27-I1 graph_proposals/{cfg['i1']} node 75:74 (verbatim)"}]
    g["672:582"]["inputs"]["text"] = t
    cache = {"node": "672:594", "class_type": g["672:594"]["class_type"],
             "was": {k: v for k, v in g["672:594"]["inputs"].items()
                     if not (isinstance(v, list) and len(v) == 2)}}
    cons = [{"node": nid, "input": k, "class_type": g[nid]["class_type"]}
            for nid, n in g.items() for k, v in n["inputs"].items()
            if isinstance(v, list) and len(v) == 2 and v[0] == "672:594"]
    del g["672:594"]
    for c in cons:
        g[c["node"]]["inputs"][c["input"]] = ["672:588", 0]
    deltas.append({"cache_removed": cache, "rewired": cons})
    for nid in ("246", "292"):
        o = g[nid]["inputs"]["filename_prefix"]
        g[nid]["inputs"]["filename_prefix"] = cfg["prefix"]
        deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": "filename_prefix",
                       "template": o, "built": cfg["prefix"]})
    o = g["672:597"]["inputs"]["noise_seed"]
    g["672:597"]["inputs"]["noise_seed"] = cfg["seed"]
    deltas.append({"node": "672:597", "class_type": "SamplerCustom", "input": "noise_seed",
                   "template": o, "built": cfg["seed"]})
    p = PROOF / "graphs" / f"animate2_{shot.lower()}.p5fix.api.json"
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
    out["shots"][shot] = {"graph": f"graphs/animate2_{shot.lower()}.p5fix.api.json",
                          "sha256": sha(p), "nodes": len(g), "deltas": deltas,
                          "errors": errs, "neg_prompt_sha": th(g["672:581"]["inputs"]["text"])[:16],
                          "params": {"steps": g["672:591"]["inputs"]["steps"],
                                     "sampler": g["672:593"]["inputs"]["sampler_name"],
                                     "cfg": g["672:597"]["inputs"]["cfg"],
                                     "shift": g["672:592"]["inputs"]["shift"],
                                     "unet": g["672:578"]["inputs"]["unet_name"],
                                     "vae": g["672:584"]["inputs"]["vae_name"],
                                     "pad": [g["P3B_PAD"]["inputs"]["target_width"],
                                             g["P3B_PAD"]["inputs"]["target_height"]]}}
    print(shot, "nodes", len(g), "errs", len(errs), "sha", out["shots"][shot]["sha256"][:16],
          "prompt", deltas[0]["sha_before"], "->", deltas[0]["sha_after"])
(PROOF / "evidence" / "P5FIX_GRAPHS.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("saved P5FIX_GRAPHS.json", len(json.dumps(out)))
