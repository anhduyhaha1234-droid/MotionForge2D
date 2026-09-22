"""S1d anchor graph (SUPERSEDED for wave B by `v14b_f08_graph.py`).

Reviewer row F08 (P1): the instruction below used to redesign only "the seated
older reader" and "the room", and the released `ImageScaleToTotalPixels`
(megapixels = 1) silently upscaled the 640x360 source to ~1 MP, so the anchor came
out 1360x768 - a different canvas from the source.  Both are fixed here:

  * the instruction now specifies a concrete appearance for EVERY visible actor,
    each prop and the background, and forbids adding/removing a person or a hand;
  * `ImageScaleToTotalPixels.megapixels` is set to the identity for a 640x368
    input so the node cannot resample the source or change the canvas.

The canonical wave-B builder is `tools/v14b_f08_graph.py` (it also validates the
graph against `/object_info`); this module is kept so the old call shape keeps
working with the corrected instruction.

usage: python w2_make_anchor_graph.py <api_in.json> <api_out.json> <attempt_tag> <seed>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SOURCE_KEYFRAME = "keyframe_f1650_src_padded_640x368.png"
# identity scale for a 640x368 canvas: 640*368/1e6.  Anything above this resamples.
MEGAPIXELS_IDENTITY_640x368 = 0.23552

INSTRUCTION = (
    "Restyle this exact frame as a 2D cel-shaded animation illustration in a flat "
    "colour palette, and redesign EVERY visible thing in it. Keep the identical "
    "composition, camera, scale, aspect ratio and every contact between bodies and "
    "objects. "
    "Foreground: the seated reader gets a new character design - new hair shape and "
    "colour, new face design, new clothing silhouette with a new cut and new flat "
    "colour scheme, new cel shading; keep the same screen position of head, "
    "shoulders, arms and hands and the same silhouette envelope. Do not just recolour "
    "the existing shirt. "
    "Behind, the standing woman gets her own new character design: new hair, new "
    "dress shape and colour, new face design, same position and same occlusion. "
    "The man seated with his back turned gets a new outfit, new hair and a new back "
    "silhouette, staying seated in the same place with the same overlap. "
    "Every other partially visible person stays present, in the same position, with "
    "the same amount of body showing, redrawn in the new style - the number of people "
    "must not change. "
    "The book becomes the redesigned prop: new cover colour and new page geometry, "
    "keeping the same size, the same position and the same interaction - closed at "
    "the start and opening where it opens in the source, with a single hand pointing "
    "where the source hand points. Do not add a second hand on the book and do not "
    "remove either person. "
    "The table and the chairs are redrawn with new materials and colours, in the same "
    "positions. The wall and the door become a new flat background design with a new "
    "colour scheme and new panel shapes, keeping the same vanishing direction and the "
    "same openings. "
    "Keep the blank band at the very top and the very bottom of the frame. "
    "No viewpoint change, no camera movement, no zoom, no crop, no letterbox, no added "
    "or removed character, no change of aspect ratio, no text, no watermark."
)


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def main() -> int:
    src, dst, tag, seed = _p(sys.argv[1]), _p(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    g = json.loads(src.read_text(encoding="utf-8"))
    changed = {"load_images": [], "prompts": [], "saves": []}
    for nid, node in g.items():
        ct = node["class_type"]
        ins = node["inputs"]
        if ct == "LoadImage":
            ins["image"] = SOURCE_KEYFRAME
            changed["load_images"].append(nid)
        elif ct == "CLIPTextEncode":
            ins["text"] = INSTRUCTION
            changed["prompts"].append(nid)
        elif ct == "SaveImage":
            ins["filename_prefix"] = f"mf_reskin_v1/video14b/anchor_book_1650_{tag}"
            changed["saves"].append(nid)
        elif ct == "ImageScaleToTotalPixels":
            ins["megapixels"] = MEGAPIXELS_IDENTITY_640x368
            changed.setdefault("scales", []).append(nid)
        elif ct == "RandomNoise":
            ins["noise_seed"] = seed
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"src": str(src), "dst": str(dst), "changed": changed,
                      "source_keyframe": SOURCE_KEYFRAME, "seed": seed,
                      "instruction": INSTRUCTION}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
