"""P5FIX2 step 2: split the cut window into segments, extract their clips, build the seg anchor and
the two video graphs.

Measured cut (P5FIX2_CUT_SCAN.json): OCC has exactly one cut, at the 101->102 pair, so
  seg1 = source frames [0, 102)   (102 frames, 3.400 s)
  seg2 = source frames [102, 120) (18 frames, 0.600 s)
BOOK and TURN have no cut above the declared threshold and are left as single units.

Per segment:
  * drive clip extracted frame-exactly with libx264 crf18 (declared re-encode; spans add up to the
    original 120 frames, no gaps, no overlap)
  * seg2 gets its own anchor: the P2 klein recipe (anchor_occ.p2.api.json) with LoadImage swapped to
    the segment's first frame (OCC frame 102, padded to 640x368 with the same centred 4+4 rule),
    the pinned cast refs and the shot's I1 prompt unchanged
  * seg1's anchor is the existing anchor_occ_p2 (its first frame IS OCC frame 0)
  * video graphs: the p5fix OCC graph with LoadImage/LoadVideo/prefix/seed swapped ONLY
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
SRC = PROOF / "inputs" / "OCC_14768_src.mp4"
OI = json.loads((EVID / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
SEG1 = PROOF / "inputs" / "p5fix2_occ_seg1.mp4"
SEG2 = PROOF / "inputs" / "p5fix2_occ_seg2.mp4"
SEG2_FRAME = PROOF / "inputs" / "p5fix2_occ_seg2_f102_640x368.png"


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate,duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0] if r.returncode == 0 else {}


out = {"artifact": "P5FIX2_SPLIT.json", "round": "R28-PROOF-P5FIX2",
       "cut": {"window": "OCC", "cut_frame": 102,
               "segments": [{"id": "OCC_SEG1", "span": [0, 102], "frames": 102},
                            {"id": "OCC_SEG2", "span": [102, 120], "frames": 18}]},
       "no_cut_windows": ["BOOK", "TURN"], "steps": {}, "graphs": {}, "validation": {}}

# ---- extract the segment clips (frame-exact; the two spans add up to 120) ------------------
if not SEG1.is_file():
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-frames:v", "102",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(SEG1)],
                   capture_output=True, text=True)
if not SEG2.is_file():
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-vf",
                    "select='gte(n\\,102)'", "-vsync", "0", "-frames:v", "18",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(SEG2)],
                   capture_output=True, text=True)
if not SEG2_FRAME.is_file():
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-vf",
                    "select='eq(n\\,102)',pad=640:368:0:4:black", "-frames:v", "1", str(SEG2_FRAME)],
                   capture_output=True, text=True)
out["steps"]["clips"] = {
    "seg1": {"file": "inputs/p5fix2_occ_seg1.mp4", "sha256": sha(SEG1), "ffprobe": probe(SEG1)},
    "seg2": {"file": "inputs/p5fix2_occ_seg2.mp4", "sha256": sha(SEG2), "ffprobe": probe(SEG2)},
    "seg2_first_frame": {"file": "inputs/p5fix2_occ_seg2_f102_640x368.png", "sha256": sha(SEG2_FRAME),
                         "bytes": SEG2_FRAME.stat().st_size}}
frames_check = (int(probe(SEG1).get("nb_read_frames") or 0)
                + int(probe(SEG2).get("nb_read_frames") or 0))
out["steps"]["clips"]["frames_add_up"] = {"sum": frames_check, "original": 120,
                                          "ok": frames_check == 120}

# ---- seg2 anchor graph (klein recipe clone) ----------------------------------------------
ak = PROOF / "graphs" / "animate2_anchor_occ_seg2.p5fix2.api.json"
g = json.loads((PROOF / "graphs" / "anchor_occ.p2.api.json").read_text(encoding="utf-8"))
deltas = []
for nid, node in g.items():
    if node["class_type"] == "LoadImage":
        old = node["inputs"]["image"]
        node["inputs"]["image"] = SEG2_FRAME.name
        deltas.append({"node": nid, "class_type": "LoadImage", "input": "image", "template": old,
                       "built": SEG2_FRAME.name})
    if node["class_type"] == "SaveImage":
        old = node["inputs"]["filename_prefix"]
        node["inputs"]["filename_prefix"] = "anchors/anchor_occ_seg2_p5fix2"
        deltas.append({"node": nid, "class_type": "SaveImage", "input": "filename_prefix",
                       "template": old, "built": "anchors/anchor_occ_seg2_p5fix2"})
    if node["class_type"] in ("RandomNoise",):
        old = node["inputs"].get("noise_seed")
        node["inputs"]["noise_seed"] = 2026092821
        deltas.append({"node": nid, "class_type": "RandomNoise", "input": "noise_seed",
                       "template": old, "built": 2026092821})
ak.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
out["graphs"]["anchor_occ_seg2"] = {"graph": "graphs/animate2_anchor_occ_seg2.p5fix2.api.json",
                                    "sha256": sha(ak), "nodes": len(g), "deltas": deltas,
                                    "prompt_sha": hashlib.sha256(
                                        g["75:74"]["inputs"]["text"].encode()).hexdigest()[:16]}

# ---- video graphs for the two segments ----------------------------------------------------
base = json.loads((PROOF / "graphs" / "animate2_occ.p5fix.api.json").read_text(encoding="utf-8"))
for seg, clip, anchor, prefix, seed in (("OCC_SEG1", SEG1.name, "anchor_occ_p2_00001_.png",
                                         "p5fix2_occ_seg1/animate2_occ_seg1_p5fix2", 2026092831),
                                        ("OCC_SEG2", SEG2.name, "anchor_occ_seg2_p5fix2_00001_.png",
                                         "p5fix2_occ_seg2/animate2_occ_seg2_p5fix2", 2026092832)):
    g2 = json.loads((PROOF / "graphs" / "animate2_occ.p5fix.api.json").read_text(encoding="utf-8"))
    dl = []
    for nid, key, new in (("189", "image", anchor), ("240", "file", clip),
                          ("672:597", "noise_seed", seed)):
        old = g2[nid]["inputs"][key]
        g2[nid]["inputs"][key] = new
        dl.append({"node": nid, "class_type": g2[nid]["class_type"], "input": key,
                   "template": old, "built": new})
    for nid in ("246", "292"):
        old = g2[nid]["inputs"]["filename_prefix"]
        g2[nid]["inputs"]["filename_prefix"] = prefix
        dl.append({"node": nid, "class_type": g2[nid]["class_type"], "input": "filename_prefix",
                   "template": old, "built": prefix})
    p = PROOF / "graphs" / f"animate2_{seg.lower()}.p5fix2.api.json"
    p.write_text(json.dumps(g2, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    errs = []
    for nid, n in g2.items():
        ct = n["class_type"]
        if ct not in OI:
            errs.append(f"{nid}: {ct} not registered")
            continue
        for k in (OI[ct]["input"].get("required", {}) or {}):
            if k not in n["inputs"]:
                errs.append(f"{nid} ({ct}): missing required {k}")
    out["graphs"][seg] = {"graph": f"graphs/animate2_{seg.lower()}.p5fix2.api.json",
                          "sha256": sha(p), "nodes": len(g2), "deltas": dl, "errors": errs,
                          "prompt_sha": hashlib.sha256(
                              g2["672:582"]["inputs"]["text"].encode()).hexdigest()[:16]}
    out["validation"][seg] = {"ok": not errs, "errors": errs}
    print(seg, len(g2), "nodes errs", len(errs), "sha", out["graphs"][seg]["sha256"][:16],
          "clip", probe(PROOF / "inputs" / clip).get("nb_read_frames"), "frames")
(EVID / "P5FIX2_SPLIT.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
print("saved P5FIX2_SPLIT.json | frames_add_up", out["steps"]["clips"]["frames_add_up"]["ok"])
