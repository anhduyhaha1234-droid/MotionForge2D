"""P4-BOOK: VACE 14B controlled challenger baseline for the BOOK unit.

Base = the wave2 VACE graph that ran for real (mf_vace14b_book4s.api.fixed.json, 15 nodes,
WanVaceToVideo 640x368 length 121 - the node owns the geometry, so no resize fix is needed).
Declared deltas only:
  * 134 LoadImage.image  -> the P2 BOOK anchor (staged in PROOF/inputs)
  * 145 LoadVideo.file   -> mf_book_f1650_1770_drive_121f.mp4, staged read-only (121 frames is the
   4n+1 shape the node needs; it is the same 1650..1770 window as BOOK_src.mp4 plus one frame)
  * 3   KSampler.seed    -> 582699151003550 (same declared seed policy as P3/P3b)
  * 114 SaveVideo.filename_prefix -> p4/animate2_vace_book_p4
Everything else (models, 20 steps, cfg 6, uni_pc, shift 8, prompts) is carried over untouched.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
TPL = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                   r"mf-reskin-model-upgrade-20260922/20260922T0345Z/VIDEO14B/wave2/api/"
                   r"mf_vace14b_book4s.api.fixed.json")
RUNTIME_INPUT = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")
DRIVE = "mf_book_f1650_1770_drive_121f.mp4"
ANCHOR = "anchor_book_p2_00001_.png"
SEED = 582699151003550
PREFIX = "p4/animate2_vace_book_p4"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


tpl = json.loads(TPL.read_text(encoding="utf-8"))
g = json.loads(TPL.read_text(encoding="utf-8"))

# stage the drive clip into PROOF/inputs (read-only source; copy only)
stage = {}
src_drive = RUNTIME_INPUT / DRIVE
dst_drive = PROOF / "inputs" / DRIVE
if src_drive.is_file():
    if not dst_drive.exists() or sha(dst_drive) != sha(src_drive):
        shutil.copy2(src_drive, dst_drive)
    stage["drive"] = {"from": str(src_drive).replace("\\", "/"), "to": f"inputs/{DRIVE}",
                      "bytes": dst_drive.stat().st_size, "sha256": sha(dst_drive),
                      "byte_identical": sha(dst_drive) == sha(src_drive)}
anchor = PROOF / "inputs" / ANCHOR
stage["anchor"] = {"file": f"inputs/{ANCHOR}", "present": anchor.is_file(),
                   "sha256": sha(anchor) if anchor.is_file() else None}

deltas = []
for nid, key, new in (("134", "image", ANCHOR), ("145", "file", DRIVE),
                      ("3", "seed", SEED), ("114", "filename_prefix", PREFIX)):
    old = g[nid]["inputs"][key]
    g[nid]["inputs"][key] = new
    deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": key,
                   "template": old, "built": new})

out = PROOF / "graphs" / "animate2_vace_book.p4.api.json"
out.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

oi = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
errs = []
for nid, node in g.items():
    ct = node["class_type"]
    if ct not in oi:
        errs.append(f"{nid}: class {ct} not registered")
        continue
    for k in (oi[ct]["input"].get("required", {}) or {}):
        if k not in node["inputs"]:
            errs.append(f"{nid} ({ct}): missing required input {k}")

prompt = g["6"]["inputs"]["text"]
man = {"artifact": "P4_GRAPH.json", "model_family": "WanVaceToVideo 14B fp16 (challenger)",
       "template": str(TPL).replace("\\", "/"), "template_sha256": sha(TPL),
       "built": "graphs/animate2_vace_book.p4.api.json", "built_sha256": sha(out),
       "nodes": len(g), "deltas": deltas, "staged": stage,
       "declared_params": {
           "unet": g["106"]["inputs"]["unet_name"], "vae": g["105"]["inputs"]["vae_name"],
           "clip": g["110"]["inputs"]["clip_name"], "steps": g["3"]["inputs"]["steps"],
           "cfg": g["3"]["inputs"]["cfg"], "sampler": g["3"]["inputs"]["sampler_name"],
           "scheduler": g["3"]["inputs"]["scheduler"], "seed": g["3"]["inputs"]["seed"],
           "shift": g["48"]["inputs"]["shift"], "length": g["49"]["inputs"]["length"],
           "width": g["49"]["inputs"]["width"], "height": g["49"]["inputs"]["height"],
           "fps": g["68"]["inputs"]["fps"]},
       "prompt_text_used": prompt, "prompt_note":
           "the template's own VACE prompt is kept byte-for-byte (the challenger keeps its own "
           "prompt; changing it would be a second variable). It is NOT the R27-02 instruction the "
           "Animate graph uses - that difference is declared here on purpose",
       "validation": {"errors": errs, "ok": not errs, "against": "P3_object_info_gpu.json"},
       "declared_delta_vs_p3b": "reference = the SAME P2 anchor; driving = the same 1650..1770 "
                                "window (121-frame variant); seed identical 582699151003550; "
                                "geometry native 640x368; only the model graph differs"}
(PROOF / "evidence" / "P4_GRAPH.json").write_text(
    json.dumps(man, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"errors": errs, "nodes": len(g), "deltas": deltas, "stage": stage,
                  "graph_sha": man["built_sha256"][:16],
                  "prompt_head": prompt[:120]}, indent=1, ensure_ascii=False))
