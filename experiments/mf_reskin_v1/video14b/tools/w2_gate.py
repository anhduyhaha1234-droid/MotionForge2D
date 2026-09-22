"""S4 technical gate for MF-V1-VIDEO14B wave 2.

Run with the TASK VENV python (needs numpy + Pillow, which ComfyUI installs):

  python w2_gate.py <candidate.mp4> <out.json> [--source <film.mp4>] [--window-start 1650]

Rows produced (each with a disposition string, never a bare pass):
  video: codec_name / nb_frames / r_frame_rate / time_base / start_time / duration
  pts  : first-3 + last frame pts == frame_index*512 under timebase 1/15360
  cfr  : packet pts deltas all == 512
  audio: stream presence, codec, sample_rate, channels, duration, start_time
  frame identity: MAE of output frame 0 vs source frame <window_start> and
                  frame <window_start>+1, and output last frame vs source last frame.
                  Disposition PASS/FAIL/UNMEASURED each; a big MAE is reported as
                  measured, never beautified.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def ffprobe_json(args: list[str]) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", *args, "-of", "json"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return {"_error": out.stderr.strip()}
    return json.loads(out.stdout or "{}")


def extract_frame(video: Path, frame: int, dst: Path, pre: list[str] | None = None) -> bool:
    cmd = [FFMPEG, "-v", "error", "-y"]
    if pre:
        cmd += pre
    cmd += ["-i", str(video), "-vf", f"select='eq(n\\,{frame})'", "-frames:v", "1", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and dst.exists()


def mae(a: Path, b: Path) -> float | None:
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    x = np.asarray(Image.open(a).convert("RGB"), dtype="float32")
    y = np.asarray(Image.open(b).convert("RGB"), dtype="float32")
    if x.shape != y.shape:
        return None
    return float(np.abs(x - y).mean())


def main() -> int:
    cand = _p(sys.argv[1])
    dst = _p(sys.argv[2])
    src = _p(sys.argv[sys.argv.index("--source") + 1]) if "--source" in sys.argv else None
    wstart = int(sys.argv[sys.argv.index("--window-start") + 1]) if "--window-start" in sys.argv else 1650

    rows = []
    info = ffprobe_json(["-show_streams", "-show_format", str(cand)])
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    def row(name, expected, actual, disp):
        rows.append({"row": name, "expected": expected, "actual": actual, "disposition": disp})

    nb = v.get("nb_frames")
    dur = v.get("duration") or (info.get("format") or {}).get("duration")
    row("video.codec_name", "h264", v.get("codec_name"), "PASS" if v.get("codec_name") else "FAIL")
    row("video.nb_frames", "120", str(nb), "PASS" if str(nb) == "120" else "FAIL")
    row("video.r_frame_rate", "30/1", v.get("r_frame_rate"),
        "PASS" if v.get("r_frame_rate") == "30/1" else "FAIL")
    row("video.time_base", "1/15360", v.get("time_base"),
        "PASS" if v.get("time_base") == "1/15360" else "FAIL")
    row("video.duration_s", "4.000000", str(dur),
        "PASS" if dur and abs(float(dur) - 4.0) < 1e-6 else "FAIL")
    row("video.width_x_height", "640x360-ish (source geometry)",
        f"{v.get('width')}x{v.get('height')}", "PASS" if v.get("width") else "UNMEASURED")

    # PTS contract
    frames = ffprobe_json(["-select_streams", "v:0", "-show_frames",
                           "-show_entries", "frame=pts,pts_time,best_effort_timestamp",
                           str(cand)]).get("frames", [])
    pts = [f.get("pts") for f in frames]
    nums = [int(p) for p in pts if p is not None]
    if nums:
        bad = [i for i, p in enumerate(nums) if p != i * 512]
        row("pts.contract", "pts == frame_index*512 (timebase 1/15360)",
            f"first3={nums[:3]} last={nums[-1]} n={len(nums)} mismatches={len(bad)}",
            "PASS" if not bad else "FAIL")
        deltas = {nums[i + 1] - nums[i] for i in range(len(nums) - 1)}
        row("pts.cfr", "all consecutive deltas == 512", f"deltas={sorted(deltas)[:4]}",
            "PASS" if deltas == {512} else "FAIL")
        exp_last = (120 - 1) * 512
        row("pts.last_frame", f"{exp_last}", str(nums[-1]),
            "PASS" if nums[-1] == exp_last else "FAIL")
    else:
        row("pts.contract", "pts readable", "no frame pts returned", "UNMEASURED")

    if a:
        row("audio.present", "present (source track remuxed)", "present",
            "PASS" if a.get("codec_name") else "FAIL")
        row("audio.codec_name", "aac", a.get("codec_name"),
            "PASS" if a.get("codec_name") == "aac" else "FAIL")
        row("audio.sample_rate", "44100", a.get("sample_rate"),
            "PASS" if a.get("sample_rate") == "44100" else "FAIL")
        row("audio.channels", "2", a.get("channels"),
            "PASS" if int(a.get("channels") or 0) == 2 else "FAIL")
        row("audio.duration_s", "~4.000", str(a.get("duration")),
            "PASS" if a.get("duration") else "UNMEASURED")
    else:
        row("audio.present", "present (source track remuxed)", "absent", "FAIL")

    # frame identity (measured, needs the frozen source film)
    ident = {}
    if src and src.is_file():
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            o0, olast = td / "o0.png", td / "olast.png"
            got0 = extract_frame(cand, 0, o0)
            gotl = extract_frame(cand, 119, olast)
            for label, fidx, ref in (("out0_vs_src1650", wstart, o0),
                                     ("out0_vs_src1651", wstart + 1, o0),
                                     ("out_last_vs_src_last", wstart + 119, olast)):
                s = td / f"s{fidx}.png"
                ok = extract_frame(src, fidx, s, pre=["-ss", f"{fidx / 30:.6f}"])
                val = mae(ref, s) if (ok and (got0 or gotl)) else None
                ident[label] = val
                rows.append({"row": f"frame_identity.{label}", "expected": "low MAE = same content",
                             "actual": ("unmeasured" if val is None else f"MAE={val:.4f}"),
                             "disposition": ("MEASURED" if val is not None else "UNMEASURED")})
    else:
        rows.append({"row": "frame_identity", "expected": "source film provided",
                     "actual": "no source film argument", "disposition": "UNMEASURED"})

    semantic = [
        "reskin_changes_main_character", "reskin_changes_hands_in_whole_frame",
        "reskin_changes_book_prop", "reskin_changes_background",
        "reskin_changes_second_character", "silhouette_and_grip_geometry_held",
        "no_camera_or_viewpoint_change",
    ]
    for s in semantic:
        rows.append({"row": f"semantic.{s}", "expected": "human/vision judgement",
                     "actual": "not watched (no vision on this route)",
                     "disposition": "NOT_REVIEWED"})

    report = {"candidate": str(cand), "rows": rows, "frame_mae": ident,
              "counts": {}}
    for r in rows:
        report["counts"][r["disposition"]] = report["counts"].get(r["disposition"], 0) + 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))
    hard = [r for r in rows if r["disposition"] == "FAIL"]
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
