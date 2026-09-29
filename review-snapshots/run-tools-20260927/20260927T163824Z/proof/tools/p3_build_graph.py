"""P3 step 1: build the Wan Animate 2 baseline graph for BOOK from the wave-B template that ran.

Base = waveB/workflows/mf_animate2_book4s.fixed.api.json (the BOOK 4s Animate-2 graph).
Declared, measured deltas only:
  * LoadImage 189  -> the P2 BOOK anchor (copied into PROOF/inputs)
  * LoadVideo 240  -> the pinned BOOK source window (BOOK_src.mp4, sha 0a7ed862), staged
  * SaveVideo prefixes -> PROOF output
Everything else (models, LoRA, cache node, scheduler, sampler, seeds, context windows, the
assembly machinery) is carried over untouched, and the delta is printed so it is provable.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
WB = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                  r"mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/waveB/workflows")
TEMPLATE = WB / "mf_animate2_book4s.shim.api.json"
ANCHOR = PROOF / "output" / "anchors" / "anchor_book_p2_00001_.png"
DRIVE = PROOF / "inputs" / "BOOK_src.mp4"
NEW_PREFIX = "p3/animate2_book_p3"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_frames,r_frame_rate,width,height,duration", "-of", "json",
                        str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr[-200:]}
    s = json.loads(r.stdout)["streams"][0]
    return {"nb_frames": s.get("nb_frames"), "r_frame_rate": s.get("r_frame_rate"),
            "width": s.get("width"), "height": s.get("height"), "duration": s.get("duration")}


g = json.loads(TEMPLATE.read_text(encoding="utf-8"))
anchor_local = PROOF / "inputs" / ANCHOR.name
if not anchor_local.exists() or sha(anchor_local) != sha(ANCHOR):
    shutil.copy2(ANCHOR, anchor_local)

deltas = []
old_img = g["189"]["inputs"]["image"]
g["189"]["inputs"]["image"] = ANCHOR.name
deltas.append({"node": "189", "class_type": "LoadImage", "input": "image",
               "template": old_img, "built": ANCHOR.name})
old_vid = g["240"]["inputs"]["file"]
g["240"]["inputs"]["file"] = DRIVE.name
deltas.append({"node": "240", "class_type": "LoadVideo", "input": "file",
               "template": old_vid, "built": DRIVE.name})
for nid in ("246", "292"):
    if nid in g and "filename_prefix" in g[nid]["inputs"]:
        deltas.append({"node": nid, "class_type": g[nid]["class_type"], "input": "filename_prefix",
                       "template": g[nid]["inputs"]["filename_prefix"], "built": NEW_PREFIX})
        g[nid]["inputs"]["filename_prefix"] = NEW_PREFIX
out = PROOF / "graphs" / "animate2_book.p3.api.json"
out.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

oi = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
errs, warns = [], []
for nid, node in g.items():
    ct = node["class_type"]
    if ct not in oi:
        errs.append(f"node {nid}: class_type {ct!r} not registered")
        continue
    req = oi[ct]["input"].get("required", {}) or {}
    opt = oi[ct]["input"].get("optional", {}) or {}
    for k in req:
        if k not in node["inputs"]:
            errs.append(f"node {nid} ({ct}): missing required input {k!r}")
    for k in node["inputs"]:
        base = k.split(".", 1)[0]
        if base not in req and base not in opt:
            warns.append(f"node {nid} ({ct}): input {k!r} not declared")

manifest = {"artifact": "P3_GRAPH.json", "template": str(TEMPLATE).replace("\\", "/"),
            "why_the_shim_variant": ("the plain/fixed variants carry the NESTED autogrow form and are "
                                     "REJECTED by /prompt with required_input_missing values.a on 7 "
                                     "ComfyMathExpression nodes plus inputs.input0 on CreateList; the "
                                     "shim variant carries the DOTTED keys (values.a, inputs.input0, "
                                     "terminations.termination0) that the API validator requires - "
                                     "measured this run, and it is the variant wave B ran"),
            "template_sha256": sha(TEMPLATE), "built": str(out).replace("\\", "/"),
            "built_sha256": sha(out), "nodes": len(g), "deltas": deltas,
            "deltas_are_inputs_and_outputs_only": True,
            "declared_params": {
                "unet": g["672:578"]["inputs"]["unet_name"],
                "lora": g["672:579"]["inputs"]["lora_name"],
                "clip": g["672:580"]["inputs"]["clip_name"],
                "clip_vision": g["672:583"]["inputs"]["clip_name"],
                "vae": g["672:584"]["inputs"]["vae_name"],
                "cache_node": g["672:594"]["class_type"] + " " +
                              json.dumps({k: v for k, v in g["672:594"]["inputs"].items()
                                          if not isinstance(v, list)}),
                "steps": g["672:591"]["inputs"]["steps"],
                "sampler": g["672:593"]["inputs"]["sampler_name"],
                "cfg": g["672:597"]["inputs"]["cfg"],
                "seed": g["672:597"]["inputs"]["noise_seed"],
                "model_sampling_shift": g["672:592"]["inputs"]["shift"],
                "pose_strength": g["672:587"]["inputs"]["pose_strength"],
                "pose_start_percent": g["672:587"]["inputs"]["pose_start_percent"],
                "pose_end_percent": g["672:587"]["inputs"]["pose_end_percent"],
                "reference_image_strength": g["672:587"]["inputs"]["reference_image_strength"],
                "context_length": g["672:586"]["inputs"]["context_length"],
                "context_overlap": g["672:586"]["inputs"]["context_overlap"],
                "chunk_length_primitive": g["672:635"]["inputs"]["value"]},
            "inputs": {
                "anchor": {"file": ANCHOR.name, "sha256": sha(ANCHOR),
                           "copy": f"inputs/{ANCHOR.name}",
                           "copy_sha256": sha(anchor_local), "dims": [640, 368]},
                "driving": {"file": DRIVE.name, "sha256": sha(DRIVE),
                            "ffprobe": ffprobe(DRIVE),
                            "why_this_clip": ("the pinned BOOK source window itself "
                                              "(sha 0a7ed862..., 120 frames @30/1) instead of the "
                                              "template's re-encoded 120f drive clip; the packet "
                                              "requires the source window as the driver and the "
                                              "delta is declared here")}},
            "validation": {"errors": errs, "warnings": warns, "ok": not errs,
                           "validated_against": "P3_object_info_gpu.json (the RUNNING GPU server "
                                                "with --base-directory, 959 nodes)"},
            "output_prefix": NEW_PREFIX}
(PROOF / "evidence" / "P3_GRAPH.json").write_text(
    json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"deltas": deltas, "errors": errs, "warnings": warns[:4],
                  "driving": manifest["inputs"]["driving"], "nodes": len(g),
                  "graph_sha": manifest["built_sha256"][:16]}, indent=1, ensure_ascii=False))
