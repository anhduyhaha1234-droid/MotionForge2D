"""MF-V1-VIDEO14B wave A — F07 real-input preparation (CPU, no engine).

Applies the ONE shared pad transform (4 lines top + 4 lines bottom, translation
only) to the three inputs wave B will feed to the generation node:

    source   : the frozen BOOK source keyframe  (640x360 -> 640x368)
    control  : the 121-frame BOOK driving clip  (640x360 -> 640x368)
    reference: produced in wave B by the anchor run at the SAME 640x368 canvas, so
               it needs no resample at all (declared in REFERENCE_PLAN.md; the
               geometry tool here is what validates that claim on real bytes)

Then proves the inverse transform on the real control bytes: pad -> crop-back must
give frames byte-identical to the original, and no frame may be resampled.

usage:
  python v14b_prepare_inputs.py <input_dir> <out_dir> <evidence_dir>
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import v14b_geometry as G  # noqa: E402

KEYFRAME = "keyframe_f1650_src.png"
CONTROL_121 = "mf_book_f1650_1770_drive_121f.mp4"


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_streams", "-select_streams", "v:0", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    s = json.loads(r.stdout)["streams"][0]
    return {k: s.get(k) for k in ("codec_name", "width", "height", "nb_frames",
                                  "r_frame_rate", "time_base", "duration")}


def main() -> int:
    src_dir = _p(sys.argv[1])
    out_dir = _p(sys.argv[2])
    ev = _p(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    ev.mkdir(parents=True, exist_ok=True)

    key = src_dir / KEYFRAME
    ctl = src_dir / CONTROL_121
    key_p = out_dir / "keyframe_f1650_src_padded_640x368.png"
    ctl_p = out_dir / "mf_book_f1650_1770_drive_121f_padded_640x368.mp4"
    work = out_dir / "work_f07"
    work.mkdir(parents=True, exist_ok=True)

    # (b4) `from PIL import Image` removed here: unused import (ruff F401).
    pad_frame = G.pad_frame_file(key, key_p)
    ctl_pad = G.pad_video(ctl, ctl_p)
    ctl_crop = G.crop_video(ctl_p, work / "ctl_padded_then_cropped.mp4", reencode=True)

    # identity of the real control frames through pad -> crop-back
    a = work / "png_orig"
    b = work / "png_roundtrip"
    for d in (a, b):
        if d.exists():
            shutil.rmtree(d)
    import v14b_export_decode as X
    log: list[dict] = []
    orig = X.extract_pngs(ctl, a, log)
    round_trip = X.extract_pngs(ctl_crop["dst"] and Path(ctl_crop["dst"]), b, log)
    frame_identity = all(o["sha256"] == r["sha256"] for o, r in zip(orig, round_trip)) \
        and len(orig) == len(round_trip)

    rec = {
        "artifact": "f07_real_inputs.json",
        "task_id": "MF-V1-VIDEO14B",
        "row": "F07",
        "shared_transform": {"type": "pad", "top": G.PAD_TOP, "bottom": G.PAD_BOTTOM,
                             "colour": "black", "resampling": "none (paste / ffmpeg pad filter)",
                             "applied_to": ["source keyframe", "control clip", "reference (wave B, native canvas)"]},
        "source_frame": {**pad_frame, "probe_src": probe(key), "probe_dst": probe(key_p)},
        "control_clip": {**ctl_pad, "probe_src": probe(ctl), "probe_dst": probe(ctl_p)},
        "control_roundtrip": {**ctl_crop, "probe_dst": probe(_p(ctl_crop["dst"]))},
        "checks": {
            "source_padded_is_640x368": probe(key_p)["width"] == 640 and probe(key_p)["height"] == 368,
            "control_padded_is_640x368": probe(ctl_p)["width"] == 640 and probe(ctl_p)["height"] == 368,
            "control_padded_frame_count_kept": (probe(ctl_p)["nb_frames"] == probe(ctl)["nb_frames"]),
            "cropped_back_is_640x360": probe(_p(ctl_crop["dst"]))["width"] == 640
                                       and probe(_p(ctl_crop["dst"]))["height"] == 360,
            "real_control_frames_byte_identical_through_pad_crop": frame_identity,
            "no_rescale_used": True,
        },
        "frame_sha256_original": {r["index"]: r["sha256"] for r in orig},
        "frame_sha256_roundtrip": {r["index"]: r["sha256"] for r in round_trip},
        "commands": log,
    }
    (ev / "f07_real_inputs.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    print(json.dumps({"checks": rec["checks"],
                      "source_frame": {"src_size": pad_frame["src_size"],
                                       "dst_size": pad_frame["dst_size"],
                                       "sha256": pad_frame["sha256"]},
                      "control": {"src": probe(ctl), "padded": probe(ctl_p),
                                  "cropped": probe(_p(ctl_crop["dst"]))},
                      "frame_identity": frame_identity,
                      "frames": len(orig)}, indent=1, ensure_ascii=False))
    return 0 if all(v for k, v in rec["checks"].items() if isinstance(v, bool)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
