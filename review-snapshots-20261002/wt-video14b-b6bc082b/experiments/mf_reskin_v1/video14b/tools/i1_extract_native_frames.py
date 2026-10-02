"""MF-V1-VIDEO14B round I1 -- decode the source frames NATIVELY and pad by translation.

Round D's observation frames were produced with
    ffmpeg -vf "select='eq(n,<idx>)',scale=640:368:flags=area"
(`raw/d_extract_shot_frames.py:71`) -- a RESAMPLE of a 640x360 window onto the 640x368
generation canvas, i.e. a 368/360 = 1.02222 vertical stretch.  That is the F07 geometry
defect (`tools/v14b_geometry.py`: the canvas must grow "by translation only, never by
resampling").  Those files are fine as an IDENTITY observation source and are still the
round-D freeze record, but they are not a valid geometry reference for a generation canvas.

This tool produces the reference frames I1 actually feeds the encoder:

  1. decode frame <idx> of the pinned source window at its NATIVE 640x360 (no filter),
  2. pad 640x360 -> 640x368 with `v14b_geometry.pad_image` (4 blank lines top + 4 bottom,
     pure translation, zero resampling),
  3. measure both the native+padded frame and the round-D frame owned by the same index so
     the difference is a number, not a claim.

usage:
  python i1_extract_native_frames.py <out_dir> <out_json>
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v14b_geometry import PAD_BOTTOM, PAD_TOP, crop_image, pad_image  # noqa: E402

BENCH = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows")
ROUND_D = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input/roundD_refs/shots")
WANT = {
    "BOOK": ("BOOK_src.mp4", (0,)),
    "TURN": ("TURN_795_src.mp4", (0, 80)),
    "OCC": ("OCC_14768_src.mp4", (0, 40)),
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(p: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,nb_frames,r_frame_rate,duration,pix_fmt", "-of", "json", str(p)])
    st = json.loads(r.stdout)["streams"][0]
    return {k: st[k] for k in ("width", "height", "nb_frames", "r_frame_rate", "duration", "pix_fmt")}


def row_means(p: Path) -> dict:
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(p).convert("RGB")).astype(float)
    return {"top_rows_mean": [round(float(a[i].mean()), 2) for i in range(4)],
            "bottom_rows_mean": [round(float(a[a.shape[0] - 1 - i].mean()), 2) for i in range(4)]}


def main() -> int:
    out_dir = Path(sys.argv[1].replace("\\", "/"))
    out_json = Path(sys.argv[2].replace("\\", "/"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rec: dict = {"artifact": "i1_native_frames.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
                 "pad": {"top": PAD_TOP, "bottom": PAD_BOTTOM, "canvas": [640, 368],
                         "rule": "canvas grows by translation only, never by resampling",
                         "module": "tools/v14b_geometry.py"},
                 "why_not_round_d_frames": (
                     "round D's shot frames were written by d_extract_shot_frames.py:71 with "
                     "ffmpeg -vf \"select=...,scale=640:368:flags=area\", i.e. 640x360 -> 640x368 "
                     "by RESAMPLING (a 1.02222 vertical stretch). They stay valid as an identity "
                     "observation source; they are not a geometry reference for generation."),
                 "frames": {}, "errors": []}
    for shot, (fn, idxs) in WANT.items():
        src = BENCH / fn
        geom = probe(src)
        rec["frames"][shot] = {"source_window": str(src).replace("\\", "/"),
                               "source_window_sha256": sha256_file(src),
                               "source_geometry": geom, "frames": []}
        for idx in idxs:
            native = out_dir / f"{shot}_f{idx:03d}_native_640x360.png"
            r = run(["ffmpeg", "-v", "error", "-y", "-i", str(src),
                     "-vf", f"select='eq(n\\,{idx})'", "-frames:v", "1", "-pix_fmt", "rgb24", str(native)])
            from PIL import Image
            if not native.is_file() or native.stat().st_size == 0:
                rec["errors"].append(f"{shot} f{idx}: ffmpeg wrote no native frame (rc={r.returncode}) {r.stderr[-200:]}")
                continue
            if Image.open(native).size != (640, 360):
                rec["errors"].append(f"{shot} f{idx}: native decode is {Image.open(native).size}, not (640, 360)")
            padded_path = out_dir / f"{shot}_f{idx:03d}_640x368.png"
            pad_image(Image.open(native)).save(padded_path)
            back = out_dir / f"{shot}_f{idx:03d}_roundtrip_640x360.png"
            crop_image(Image.open(padded_path)).save(back)
            import numpy as np
            bit_exact_roundtrip = bool((np.asarray(Image.open(native).convert("RGB"))
                                        == np.asarray(Image.open(back).convert("RGB"))).all())
            rd = ROUND_D / f"{shot}_f{idx:03d}_640x368.png"
            rec["frames"][shot]["frames"].append({
                "index": idx,
                "ffmpeg_argv": ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf",
                                f"select='eq(n\\,{idx})'", "-frames:v", "1", "-pix_fmt", "rgb24", str(native)],
                "native": {"path": str(native).replace("\\", "/"), "size": list(Image.open(native).size),
                           "sha256": sha256_file(native), "bytes": native.stat().st_size},
                "padded_640x368": {"path": str(padded_path).replace("\\", "/"),
                                   "size": list(Image.open(padded_path).size),
                                   "sha256": sha256_file(padded_path), "bytes": padded_path.stat().st_size,
                                   "top_rows_mean": row_means(padded_path)["top_rows_mean"],
                                   "bottom_rows_mean": row_means(padded_path)["bottom_rows_mean"]},
                "pad_roundtrip_is_bit_exact_to_the_native_decode": bit_exact_roundtrip,
                "round_d_frame_of_the_same_index": (
                    {"path": str(rd).replace("\\", "/"), "sha256": sha256_file(rd),
                     "bytes": rd.stat().st_size, **row_means(rd)} if rd.is_file() else None),
                "round_d_frame_is_not_the_padded_native":
                    (sha256_file(rd) != sha256_file(padded_path)) if rd.is_file() else None,
            })
    rec["all_pads_roundtrip_bit_exact"] = all(
        f["pad_roundtrip_is_bit_exact_to_the_native_decode"]
        for s in rec["frames"].values() for f in s["frames"]) and not rec["errors"]
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"shots": {s: [{"idx": f["index"], "padded_sha": f["padded_640x368"]["sha256"][:12],
                                     "native_sha": f["native"]["sha256"][:12],
                                     "roundtrip_exact": f["pad_roundtrip_is_bit_exact_to_the_native_decode"],
                                     "rd_differs": f["round_d_frame_is_not_the_padded_native"]}
                                    for f in v["frames"]] for s, v in rec["frames"].items()},
                      "all_pads_roundtrip_bit_exact": rec["all_pads_roundtrip_bit_exact"],
                      "errors": rec["errors"], "json": str(out_json)}, indent=1))
    return 1 if rec["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
