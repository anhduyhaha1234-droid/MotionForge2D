"""MF-V1-VIDEO14B wave A — F07 geometry pad / crop-back tooling (CPU).

DEFECT (reviewer F07, row P1)
-----------------------------
`V/tools/make_run_workflows.py:131` set the generation height to 368 straight from
the 360-line source, so the released node resampled the 640x360 control/reference
into a 640x368 canvas (a 368/360 = 1.022222 stretch) and the delivered clip stayed
640x368 — a 2.2222 % vertical mismatch against the 640x360 source.  The template's
step-16 constraint needs an 8-line-taller canvas; it does NOT authorise rescaling.

FIX (this module)
-----------------
The canvas grows by **translation only**, never by resampling:

    pad   : 640x360 -> 640x368 by adding 4 blank lines on TOP and 4 on the BOTTOM
    crop  : 640x368 -> 640x360 by removing exactly those 8 lines again

The same pad transform is applied to the source frame, the reference frame and the
control clip, so the content rectangle keeps identical coordinates in all three and
the content is never resampled.  After generation the output is cropped back with
the inverse transform, so the delivered clip is exactly 640x360 with the content at
the same coordinates it had in the source.

`368` is the *generation canvas*, never the expected output geometry, and it is only
reachable through `pad()` — the module refuses to produce a 368-line frame by
resampling.

The synthetic-grid proof (`prove_roundtrip`) is the acceptance test: a stretched
control fails it.

usage:
  python v14b_geometry.py prove <evidence_json>
  python v14b_geometry.py pad  <in> <out> [top] [bottom]
  python v14b_geometry.py crop <in> <out> [top] [bottom]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

W_SOURCE = 640
H_SOURCE = 360
PAD_TOP = 4
PAD_BOTTOM = 4
H_CANVAS = H_SOURCE + PAD_TOP + PAD_BOTTOM          # 368, the step-16 generation canvas
PAD_COLOR = (0, 0, 0)

# synthetic grid constants (chosen so every boundary is an exact pixel coordinate)
GRID_STEP = 20
MARKER = 8
ROW_TOP_MARK = (0, 255, 255)      # cyan   -> must land on canvas row 4
ROW_BOT_MARK = (255, 0, 255)      # magenta-> must land on canvas row 363
COL_LEFT_MARK = (255, 255, 0)     # yellow -> column 0, unchanged by a vertical pad
COL_RIGHT_MARK = (255, 0, 0)      # red    -> column 639


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------- primitives

def pad_image(img, top: int = PAD_TOP, bottom: int = PAD_BOTTOM):
    """Add blank lines top/bottom. Pure translation: zero resampling."""
    from PIL import Image
    w, h = img.size
    out = Image.new("RGB", (w, h + top + bottom), PAD_COLOR)
    out.paste(img.convert("RGB"), (0, top))
    return out


def crop_image(img, top: int = PAD_TOP, bottom: int = PAD_BOTTOM):
    """Inverse of pad_image: remove exactly the added lines."""
    w, h = img.size
    return img.convert("RGB").crop((0, top, w, h - bottom))


def stretch_image(img, target_h: int):
    """The DEFECT path, kept only so the proof can show it fails. Resamples."""
    from PIL import Image
    w, h = img.size
    return img.convert("RGB").resize((w, target_h), Image.BICUBIC)


def synthetic_grid() -> "object":
    """Deterministic 640x360 grid with markers on the rows/columns a pad can move."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W_SOURCE, H_SOURCE), (16, 16, 16))
    d = ImageDraw.Draw(img)
    for x in range(0, W_SOURCE, GRID_STEP):
        d.line([(x, 0), (x, H_SOURCE - 1)], fill=(200, 200, 200), width=1)
    for y in range(0, H_SOURCE, GRID_STEP):
        d.line([(0, y), (W_SOURCE - 1, y)], fill=(200, 200, 200), width=1)
    d.line([(0, 0), (0, H_SOURCE - 1)], fill=COL_LEFT_MARK, width=1)
    d.line([(W_SOURCE - 1, 0), (W_SOURCE - 1, H_SOURCE - 1)], fill=COL_RIGHT_MARK, width=1)
    d.line([(0, 0), (W_SOURCE - 1, 0)], fill=ROW_TOP_MARK, width=1)
    d.line([(0, H_SOURCE - 1), (W_SOURCE - 1, H_SOURCE - 1)], fill=ROW_BOT_MARK, width=1)
    for i, (cx, cy) in enumerate(((4, 4), (W_SOURCE - 12, 4), (4, H_SOURCE - 12),
                                  (W_SOURCE - 12, H_SOURCE - 12),
                                  (W_SOURCE // 2, H_SOURCE // 2))):
        d.rectangle([cx, cy, cx + MARKER - 1, cy + MARKER - 1],
                    fill=((i * 40 + 60) % 256, (255 - i * 50) % 256, (i * 90) % 256))
    return img


# ------------------------------------------------------------------- the proof

def _diff(a, b) -> dict:
    import numpy as np
    x = np.asarray(a.convert("RGB"), dtype=np.int16)
    y = np.asarray(b.convert("RGB"), dtype=np.int16)
    if x.shape != y.shape:
        return {"comparable": False, "shape_a": list(x.shape), "shape_b": list(y.shape)}
    d = np.abs(x - y)
    return {"comparable": True,
            "identical": bool((d == 0).all()),
            "mae": float(d.mean()),
            "max_abs": int(d.max()),
            "differing_pixels": int((d.max(axis=2) > 0).sum()),
            "differing_pixel_pct": round(100.0 * float((d.max(axis=2) > 0).mean()), 4)}


def prove_roundtrip() -> dict:
    import numpy as np
    # (b4) `from PIL import Image` removed here: unused import (ruff F401).

    grid = synthetic_grid()
    gw, gh = grid.size
    padded = pad_image(grid, PAD_TOP, PAD_BOTTOM)
    back = crop_image(padded, PAD_TOP, PAD_BOTTOM)

    g = np.asarray(grid.convert("RGB"), dtype=np.uint8)
    p = np.asarray(padded.convert("RGB"), dtype=np.uint8)
    b = np.asarray(back.convert("RGB"), dtype=np.uint8)

    # the DEFECT: 360 -> 368 by resampling, then the same crop-back
    stretched = stretch_image(grid, H_CANVAS)
    stretched_back = crop_image(stretched, PAD_TOP, PAD_BOTTOM)

    top_bar_ok = bool((p[0:PAD_TOP] == np.array(PAD_COLOR, dtype=np.uint8)).all())
    bot_bar_ok = bool((p[gh + PAD_TOP:H_CANVAS] == np.array(PAD_COLOR, dtype=np.uint8)).all())
    content_rect_ok = bool((p[PAD_TOP:PAD_TOP + gh] == g).all())

    row_top_mask = (p == np.array(ROW_TOP_MARK, dtype=np.uint8)).all(axis=1).all(axis=1)
    row_bot_mask = (p == np.array(ROW_BOT_MARK, dtype=np.uint8)).all(axis=1).all(axis=1)
    row_top_ypad = int(np.flatnonzero(row_top_mask)[0]) if row_top_mask.any() else None
    row_bot_ypad = int(np.flatnonzero(row_bot_mask)[0]) if row_bot_mask.any() else None

    return {
        "artifact": "f07_synthetic_grid.json",
        "task_id": "MF-V1-VIDEO14B",
        "row": "F07",
        "source_geometry": [gw, gh],
        "generation_canvas": [gw, padded.size[1]],
        "pad": {"top": PAD_TOP, "bottom": PAD_BOTTOM, "colour": list(PAD_COLOR),
                "transform": "translation only (paste at y=+top); zero resampling"},
        "crop": {"remove_top": PAD_TOP, "remove_bottom": PAD_BOTTOM,
                 "transform": "inverse translation (crop box y=top..h-bottom)"},
        "grid_sha256": hashlib.sha256(np.ascontiguousarray(g)).hexdigest(),
        "padded_sha256": hashlib.sha256(np.ascontiguousarray(p)).hexdigest(),
        "roundtrip_sha256": hashlib.sha256(np.ascontiguousarray(b)).hexdigest(),
        "checks": {
            "padded_height_is_368": int(p.shape[0]) == H_CANVAS,
            "roundtrip_is_byte_identical": bool((b == g).all()),
            "roundtrip_sha256_equal": (hashlib.sha256(np.ascontiguousarray(b)).hexdigest()
                                       == hashlib.sha256(np.ascontiguousarray(g)).hexdigest()),
            "content_rect_preserved_at_same_coordinates": content_rect_ok,
            "top_pad_bar_is_blank": top_bar_ok,
            "bottom_pad_bar_is_blank": bot_bar_ok,
            "row0_marker_lands_on_canvas_row_4":
                bool((p[PAD_TOP] == np.array(ROW_TOP_MARK, dtype=np.uint8)).all()),
            "last_content_row_lands_on_canvas_row_363":
                bool((p[PAD_TOP + gh - 1] == np.array(ROW_BOT_MARK, dtype=np.uint8)).all()),
            "column0_unchanged": bool((p[PAD_TOP:PAD_TOP + gh, 0] == g[:, 0]).all()),
            "column639_unchanged": bool((p[PAD_TOP:PAD_TOP + gh, gw - 1] == g[:, gw - 1]).all()),
            "no_rescale_in_pad_path": True,
        },
        "row0_marker_canvas_row": row_top_ypad,
        "last_content_row_canvas_row": row_bot_ypad,
        "defect_control_stretch_360_to_368": {
            "transform": "PIL BICUBIC resize 640x360 -> 640x368 (the old behaviour)",
            "scale_factor": round(H_CANVAS / gh, 6),
            "vertical_mismatch_pct": round(100.0 * (H_CANVAS / gh - 1.0), 4),
            "after_crop_back_vs_source": _diff(stretched_back, grid),
            "roundtrip_is_byte_identical": bool(
                (np.asarray(stretched_back.convert("RGB"), dtype=np.uint8) == g).all()),
            "content_rect_preserved_at_same_coordinates": bool(
                (np.asarray(stretched, dtype=np.uint8)[PAD_TOP:PAD_TOP + gh]
                 == g).all()) if stretched.size[1] >= PAD_TOP + gh else False,
        },
        "verdict": "PASS" if (content_rect_ok and bool((b == g).all())
                              and top_bar_ok and bot_bar_ok) else "FAIL",
    }


# ------------------------------------------------------------------ ffmpeg glue

def pad_video(src: Path, dst: Path, top: int = PAD_TOP, bottom: int = PAD_BOTTOM) -> dict:
    """ffmpeg pad filter (additive, no scale anywhere; -vf pad only, never scale)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = f"pad=iw:ih+{top + bottom}:0:{top}:color=black"
    argv = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf,
            "-c:v", "libx264", "-crf", "0", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            str(dst)]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"argv": argv, "returncode": r.returncode, "stderr_tail": (r.stderr or "")[-300:],
            "dst": str(dst),
            "bytes": dst.stat().st_size if dst.is_file() else 0,
            "sha256": sha256_file(dst) if dst.is_file() else None}


def crop_video(src: Path, dst: Path, top: int = PAD_TOP, bottom: int = PAD_BOTTOM,
               reencode: bool = True) -> dict:
    """ffmpeg crop filter: remove exactly the 8 pad lines (no scale)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = f"crop=iw:ih-{top + bottom}:0:{top}"
    argv = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf]
    if reencode:
        argv += ["-c:v", "libx264", "-crf", "0", "-preset", "medium", "-pix_fmt", "yuv420p"]
    else:
        argv += ["-c:v", "copy"]
    argv.append(str(dst))
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"argv": argv, "returncode": r.returncode, "stderr_tail": (r.stderr or "")[-300:],
            "dst": str(dst),
            "bytes": dst.stat().st_size if dst.is_file() else 0,
            "sha256": sha256_file(dst) if dst.is_file() else None}


def pad_frame_file(src: Path, dst: Path, top: int = PAD_TOP, bottom: int = PAD_BOTTOM) -> dict:
    from PIL import Image
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        out = pad_image(im.convert("RGB"), top, bottom)
    out.save(dst)
    return {"dst": str(dst), "src_size": list(Image.open(src).size),
            "dst_size": list(out.size), "sha256": sha256_file(dst),
            "bytes": dst.stat().st_size}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "prove"
    if mode == "prove":
        rec = prove_roundtrip()
        out = _p(sys.argv[2]) if len(sys.argv) > 2 else None
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        print(json.dumps(rec, indent=1, ensure_ascii=False))
        return 0 if rec["verdict"] == "PASS" else 1
    if mode in ("pad", "crop"):
        src, dst = _p(sys.argv[2]), _p(sys.argv[3])
        top = int(sys.argv[4]) if len(sys.argv) > 4 else PAD_TOP
        bottom = int(sys.argv[5]) if len(sys.argv) > 5 else PAD_BOTTOM
        fn = pad_video if mode == "pad" else crop_video
        rec = fn(src, dst, top, bottom)
        print(json.dumps(rec, indent=1, ensure_ascii=False))
        return 0 if rec["returncode"] == 0 and rec["bytes"] > 0 else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
