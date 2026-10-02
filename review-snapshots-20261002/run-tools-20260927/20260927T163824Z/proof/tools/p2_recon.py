"""P2 recon: what the R27-I1 graph actually ran with, what is registered, what is on disk.

Read-only.  Prints the facts P2 needs: spec params, graph node/class map with the model names it
loaded, object_info presence for every class in that graph, and the model files available.
"""
from __future__ import annotations

import json
import pathlib

R27 = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                   r"mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B")
PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
MODELS = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models")

spec = json.loads((R27 / "graph_proposals" / "roundI1_spec.json").read_text(encoding="utf-8"))
oi = json.loads((PROOF / "evidence" / "P0_object_info.json").read_text(encoding="utf-8"))
print("=== spec ===")
print("canvas", spec["canvas"], "steps", spec["steps"], "ref_longer_side", spec["ref_longer_side"])
print("template", spec["template"], spec["template_sha256"][:16])
g = json.loads((R27 / "graph_proposals" / "anchor_book.i1.api.json").read_text(encoding="utf-8"))
print("=== graph classes ===")
classes = {}
for nid, node in g.items():
    classes.setdefault(node["class_type"], []).append(nid)
for ct, ids in sorted(classes.items()):
    print(f"  {ct} x{len(ids)} @ {ids[:4]}")
print("=== graph key inputs ===")
for nid, node in g.items():
    ct = node["class_type"]
    inp = node["inputs"]
    keep = {k: v for k, v in inp.items() if not (isinstance(v, list) and len(v) == 2)}
    if ct in ("UNETLoader", "CLIPLoader", "VAELoader", "EmptyFlux2LatentImage", "RandomNoise",
              "KSamplerSelect", "Flux2Scheduler", "CFGGuider", "SaveImage", "ImageScaleToTotalPixels",
              "ResizeImageMaskNode", "LoadImage", "CLIPTextEncode", "BasicGuider"):
        print(f"  {nid} {ct}: {json.dumps(keep)[:220]}")
print("=== object_info presence for the graph's classes ===")
missing = [ct for ct in classes if ct not in oi]
print("  missing:", missing or "NONE")
for ct in sorted(classes):
    if ct in oi:
        req = oi[ct]["input"].get("required", {})
        print(f"  {ct}: required={list(req)[:8]}")
print("=== model files ===")
for grp in ("diffusion_models", "loras", "vae", "text_encoders", "clip_vision"):
    d = MODELS / grp
    if d.is_dir():
        for f in sorted(d.rglob("*")):
            if f.is_file():
                print(f"  {grp}/{f.relative_to(d)} {f.stat().st_size/2**30:.2f} GiB")
