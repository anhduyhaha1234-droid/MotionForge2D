"""P5FIX3 step 1: look at the SEG2 source frames before writing its prompt.

Writes a 3-frame strip (seg frames 0 / 8 / 17 = OCC frames 102 / 110 / 119) of the segment's own
source clip so the prompt can be written from the pixels, and records frame hashes.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
PREV = EVID / "previews"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p5fix3_frames")
SEG2 = PROOF / "inputs" / "p5fix2_occ_seg2.mp4"


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def frame(p, idx):
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


out = {"artifact": "P5FIX3_SEG2_SOURCE.json", "segment": "OCC_SEG2",
       "clip": "inputs/p5fix2_occ_seg2.mp4", "sha256": sha(SEG2), "frames": 18,
       "source_span_in_window": [102, 120]}
tiles = [(i, frame(SEG2, i)) for i in (0, 8, 17)]
w, h = tiles[0][1].size
sheet = Image.new("RGB", (w * 3, h + 18), (24, 24, 28))
d = ImageDraw.Draw(sheet)
d.text((4, 3), "OCC_SEG2 SOURCE frames (seg f0/OCC f102, seg f8/OCC f110, seg f17/OCC f119)",
       fill=(235, 235, 235))
for k, (idx, im) in enumerate(tiles):
    sheet.paste(im, (k * w, 18))
    d.text((k * w + 3, h - 4), f"seg f{idx}", fill=(255, 235, 120))
sp = PREV / "p5fix3_occ_seg2_source_frames.png"
sheet.save(sp)
out["preview"] = f"previews/{sp.name}"
out["frame_hashes"] = {f"f{i}": hashlib.sha256(
    TMP.joinpath(f"{SEG2.stem}_f{i:04d}.png").read_bytes()).hexdigest()[:16] for i in (0, 8, 17)}
(EVID / "P5FIX3_SEG2_SOURCE.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
print("saved strip", out["preview"], out["frame_hashes"])
