"""P3b: fix the GEOMETRY of the BOOK graph - portrait 482x854 center-crop -> the source aspect.

Defect (measured on the P3 run): node `672:600 ResizeImageMaskNode` hard-coded
`resize_type.width=482, resize_type.height=854, resize_type.crop="center"`, so every driving frame
was centre-cropped (accumulate=1 side loss: table, the back-facing figure and the right-edge
partial BOOK-P4 disappeared) and the latent came out 480x848 portrait.

Why not just flip `crop` to "disabled": nodes_post_processing.py:440 documents it as
"'disabled' STRETCHES to fit" - that would distort the frame.  The registered node
`ResizeAndPadImage` (comfy_extras/nodes_images.py:594) instead does scale=min(fit) + CENTERED pad
with a chosen colour (lines 616-638), so 640x360 -> scale 1.0 -> 640x360 content + 4 rows top and
4 rows bottom = exactly 640x368 with FULL content.

Wiring change (the only one):
  * + P3B_PAD = ResizeAndPadImage(image <- 672:595.images, 640, 368, black, area)
  * 672:596 GetImageSize.image   : 672:600 -> P3B_PAD     (this is what feeds
    672:587 WanAnimate2ToVideo.width/height through the DECLARED chain)
  * 672:599 ImageFromBatch.image : 672:600 -> P3B_PAD
  * 672:587 WanAnimate2ToVideo.pose_video : 672:600 -> P3B_PAD
  * - 672:600 (now unreferenced)
  * 672:590 (reference resize) keeps taking width/height FROM 672:596, so it becomes 640x368 too,
    and on the 640x368 anchor a center-crop resize is the identity - no reference content lost.
Everything else - models, LoRA, steps, sampler, seed, cache node, context windows - is untouched.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
SRC = PROOF / "graphs" / "animate2_book.p3.api.json"
OUT = PROOF / "graphs" / "animate2_book.p3b.api.json"
PAD_ID = "P3B_PAD"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


g = json.loads(SRC.read_text(encoding="utf-8"))
before = json.loads(SRC.read_text(encoding="utf-8"))

g[PAD_ID] = {"inputs": {"image": ["672:595", 0], "target_width": 640, "target_height": 368,
                        "padding_color": "black", "interpolation": "area"},
             "class_type": "ResizeAndPadImage",
             "_meta": {"title": "Resize And Pad Image (P3b geometry fix)"}}
rewired = []
for nid, key in (("672:596", "image"), ("672:599", "image"), ("672:587", "pose_video")):
    old = g[nid]["inputs"][key]
    assert old == ["672:600", 0], (nid, key, old)
    g[nid]["inputs"][key] = [PAD_ID, 0]
    rewired.append({"node": nid, "class_type": g[nid]["class_type"], "input": key,
                    "from": old, "to": [PAD_ID, 0]})
removed = {"node": "672:600", "class_type": g["672:600"]["class_type"],
           "removed_because": "carried the hard-coded 482x854 center-crop",
           "was": json.loads(SRC.read_text(encoding="utf-8"))["672:600"]["inputs"]}
del g["672:600"]

# who else consumed the removed node?
dangling = [(nid, k) for nid, n in g.items() for k, v in n["inputs"].items()
            if isinstance(v, list) and len(v) == 2 and v[0] == "672:600"]
OUT.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

oi = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
errs = []
for nid, node in g.items():
    ct = node["class_type"]
    if ct not in oi:
        errs.append(f"{nid}: class {ct} not registered")
        continue
    req = oi[ct]["input"].get("required", {}) or {}
    for k in req:
        if k not in node["inputs"]:
            errs.append(f"{nid} ({ct}): missing required input {k}")

manifest = {"artifact": "P3B_GRAPH.json", "purpose": "P3b geometry fix: portrait -> source aspect",
            "source_graph": "graphs/animate2_book.p3.api.json", "source_sha256": sha(SRC),
            "built": "graphs/animate2_book.p3b.api.json", "built_sha256": sha(OUT),
            "nodes_before": len(before), "nodes_after": len(g),
            "added": {PAD_ID: {"class_type": "ResizeAndPadImage", "target": [640, 368],
                               "padding_color": "black", "interpolation": "area",
                               "semantics_source": "comfy_extras/nodes_images.py:594-641 "
                                                   "(scale=min(fit), centered pad)"}},
            "rewired": rewired, "removed": removed, "dangling_refs_to_removed_node": dangling,
            "declared_chain": {
                "pose_video": f"{PAD_ID} -> 672:587 WarpAnimate2ToVideo.pose_video",
                "size_authority": "672:596 GetImageSize(P3B_PAD) -> "
                                  "672:587 WanAnimate2ToVideo.width/height (only this chain)",
                "reference": "672:590 resize takes width/height from 672:596 (now 640x368); the "
                             "anchor is already 640x368 so the center-crop resize is the identity",
                "expected_output_dims": [640, 368],
                "assembly_note": "the pad is centered (4 rows top + 4 rows bottom); to recover the "
                                 "source's 640x360 the assembly step crops 4 rows from each side"},
            "unchanged_declared": {"seed": g["672:597"]["inputs"]["noise_seed"],
                                   "steps": g["672:591"]["inputs"]["steps"],
                                   "sampler": g["672:593"]["inputs"]["sampler_name"],
                                   "cfg": g["672:597"]["inputs"]["cfg"],
                                   "unet": g["672:578"]["inputs"]["unet_name"],
                                   "lora": g["672:579"]["inputs"]["lora_name"]},
            "validation": {"errors": errs, "ok": not errs,
                           "against": "P3_object_info_gpu.json"},
            "diff_nodes": sorted(set(before) ^ set(g) | {n for n in set(before) & set(g)
                                                         if before[n] != g[n]})}
(PROOF / "evidence" / "P3B_GRAPH.json").write_text(
    json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"errors": errs, "nodes": [len(before), len(g)],
                  "diff_nodes": manifest["diff_nodes"], "dangling": dangling,
                  "out_sha": manifest["built_sha256"][:16]}, indent=1))
