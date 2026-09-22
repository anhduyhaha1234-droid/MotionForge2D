"""MF-V1-VIDEO14B wave B step B3 — apply the DOCUMENTED geometry to the
frontend-converted Animate-2 API graph, and nothing else.

The official Animate-2 template hard-codes its example's portrait 480p canvas
(`ResizeImageMaskNode` 672:600 = 482x854, crop=center) and its example's driving
clip.  The two edits below are the ONLY changes made to the official
configuration; the checkpoint / LoRA / sampler / steps set is untouched (that is
the "no hand-mixing" rule — it protects the model configuration, while the input
geometry must follow THIS source, whose canvas is documented as 640x368).

  edit 1  node 240 LoadVideo.file  -> the 121-frame control clip padded 4+4
                                       (640x368).  121 % 4 == 1 is what the
                                       template's own loop math requires
                                       (672:667 `(F % 4 == 1)`), and 121 frames
                                       == the 120-frame source window plus the
                                       single repeated last frame.
  edit 2  node 672:600 width/height -> 640 x 368 (identity for that clip).
                                       Leaving 482x854 with crop=center would
                                       scale-to-cover and centre-crop the
                                       landscape frame into portrait, i.e. change
                                       the camera framing the instruction forbids.

Everything else is asserted unchanged against the input graph, so a later reader
can see this was a two-key patch and not a re-authored workflow.

usage: python waveB_geometry_patch.py <in.api.json> <out.api.json> <record.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DRIVE_CLIP = "mf_book_f1650_1770_drive_121f_padded_640x368.mp4"
CANVAS = {"width": 640, "height": 368}


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def main() -> int:
    src, dst, rec_path = _p(sys.argv[1]), _p(sys.argv[2]), _p(sys.argv[3])
    raw = src.read_bytes()
    g = json.loads(raw.decode("utf-8"))
    before = json.loads(raw.decode("utf-8"))

    # --- edit 1 -----------------------------------------------------------------
    n240 = g["240"]
    assert n240["class_type"] == "LoadVideo", n240["class_type"]
    drive_before = n240["inputs"]["file"]
    n240["inputs"]["file"] = DRIVE_CLIP

    # --- edit 2 -----------------------------------------------------------------
    n600 = g["672:600"]
    assert n600["class_type"] == "ResizeImageMaskNode", n600["class_type"]
    wh_before = {k: n600["inputs"].get(k) for k in ("resize_type.width", "resize_type.height")}
    n600["inputs"]["resize_type.width"] = CANVAS["width"]
    n600["inputs"]["resize_type.height"] = CANVAS["height"]
    assert n600["inputs"].get("resize_type.crop") == "center"
    assert n600["inputs"]["resize_type"] == "scale dimensions"

    # --- nothing else changed ---------------------------------------------------
    diffs = []
    for k in sorted(set(before) | set(g)):
        if k not in before:
            diffs.append({"node": k, "kind": "added"})
        elif k not in g:
            diffs.append({"node": k, "kind": "removed"})
        elif before[k] != g[k]:
            keys = sorted({*before[k].get("inputs", {}), *g[k].get("inputs", {})})
            changed = {kk: [before[k]["inputs"].get(kk), g[k]["inputs"].get(kk)]
                       for kk in keys if before[k]["inputs"].get(kk) != g[k]["inputs"].get(kk)}
            diffs.append({"node": k, "kind": "inputs_changed", "class_type": g[k]["class_type"],
                          "changed": changed})
    unexpected = [d for d in diffs
                  if not (d["node"] == "240" and set(d.get("changed", {})) == {"file"})
                  and not (d["node"] == "672:600"
                           and set(d.get("changed", {})) <= {"resize_type.width", "resize_type.height"})]

    out = json.dumps(g, indent=1, ensure_ascii=False)
    dst.write_text(out, encoding="utf-8")
    record = {
        "in": str(src), "out": str(dst),
        "in_sha256": hashlib.sha256(raw).hexdigest(),
        "out_sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
        "out_bytes": dst.stat().st_size,
        "api_node_count": len(g),
        "edit_1": {"node": "240", "class_type": "LoadVideo", "key": "inputs.file",
                   "before": drive_before, "after": DRIVE_CLIP},
        "edit_2": {"node": "672:600", "class_type": "ResizeImageMaskNode",
                   "key": "resize_type.width/height", "before": wh_before,
                   "after": CANVAS, "crop": n600["inputs"]["resize_type.crop"],
                   "why": "482x854 + crop=center is the template example's portrait 480p "
                          "canvas; against a 640x368 landscape control it is scale-to-cover "
                          "+ centre-crop, i.e. a camera/framing change the instruction forbids"},
        "whole_graph_diffs": diffs,
        "unexpected_diffs": unexpected,
        "verdict": "GEOMETRY_PATCHED_TWO_KEYS" if not unexpected else "PATCH_TOUCHED_MORE_THAN_EXPECTED",
        "saves": {k: v["class_type"] for k, v in g.items() if v["class_type"].startswith("Save")},
    }
    rec_path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("verdict", "in_sha256", "out_sha256", "out_bytes",
                                             "api_node_count", "edit_1", "edit_2", "saves",
                                             "unexpected_diffs")}, indent=1, ensure_ascii=False))
    return 0 if not unexpected else 7


if __name__ == "__main__":
    raise SystemExit(main())
