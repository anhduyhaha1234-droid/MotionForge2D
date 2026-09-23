"""MF-V1-BENCH wave B (round 2) - side-by-side review artifacts for the M1 candidate.

Three sources, one row each, in this order: SOURCE WINDOW | OLD CANDIDATE | NEW (M1) CANDIDATE.
Everything is built on CPU with ffmpeg from FROZEN inputs only; nothing is judged here, the
bundle exists so a human can look at the motion without doing file archaeology.

Artifacts (all asserted to exist AND to be non-zero bytes):
  <NEW>/BENCH/review/m1/m1_3up_source_old_new_sheet_<seg>.png     3-up contact sheets
  <NEW>/BENCH/review/m1/m1_3up_source_old_new_grip2x_<seg>.png    3-up 2x centre-zoom strips
  <NEW>/BENCH/review/m1/m1_3up_source_old_new_1x.mp4              full-length 3-up video
  <NEW>/BENCH/review/m1/m1_3up_source_old_new_0.5x.mp4            half-speed 3-up video
  plus per-side 1x review copies of the source window and the old candidate (provenance)

Writes <NEW>/BENCH/raw/m1_review_manifest.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")
BENCH_SRC = WT / "experiments" / "mf_reskin_v1" / "bench"
sys.path.insert(0, str(BENCH_SRC))
import common as C          # noqa: E402

NEW = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
           "mf-core-tool-delivery-20260923/20260923T1535Z")
CORR = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
            "mf-reskin-correction-20260922/20260922T0955Z")
M1 = (NEW / "manager" / "frozen" / "M1_book4s_animate2" / "M1_book4s_animate2" / "files" / "waveB_m1")
SRC = M1 / "review" / "source_window_120f.mp4"
NEWC = M1 / "clip" / "final_book4s_m1_decoded119_640x360.mp4"
OLDC = (CORR / "manager" / "frozen" / "BOOK_animate2_waveB" / "files"
        / "final_book4s_decoded119_640x360.mp4")
OUT = NEW / "BENCH" / "review" / "m1"
RAW = NEW / "BENCH" / "raw"
C.set_ledger_path(RAW / "cmd_transcript.jsonl")
C.ensure(OUT)

VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
ROW_ORDER = ["source_window", "old_candidate", "new_candidate_m1"]
SEGS = [("A_f000_f059", "0", "2"), ("B_f060_f119", "2", "2")]
items = []


def sha256_file(p):
    return C.sha256_file(p)


def add(kind, path, note, dims=None):
    p = Path(path)
    rec = {"kind": kind, "path": str(p), "exists": p.exists(),
           "bytes": p.stat().st_size if p.exists() else 0, "note": note}
    if p.exists() and p.suffix.lower() == ".png":
        try:
            from PIL import Image
            with Image.open(p) as im:
                rec["size_px"] = list(im.size)
        except Exception as e:                                    # noqa: BLE001
            rec["size_px"] = None
            rec["pil_error"] = str(e)[:200]
    elif p.exists() and p.suffix.lower() == ".mp4":
        pv = C.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=width,height,nb_frames,duration", "-of", "json", str(p)],
                   label="ffprobe bundle " + p.name)
        rec["stream"] = json.loads(pv[1] or "{}")
    if p.exists():
        rec["sha256"] = sha256_file(p)
    items.append(rec)
    return rec


def montage(seg_label, t0, dur, tile, crop=None, scale=None, fps=5):
    """3-up PNG: row 0 source window, row 1 old candidate, row 2 M1 candidate."""
    out = OUT / ("m1_3up_source_old_new_%s_%s.png" % ("grip2x" if crop else "sheet", seg_label))
    parts = []
    for i, src in enumerate((SRC, OLDC, NEWC)):
        vf = []
        if crop:
            vf.append("crop=%s" % crop)
        if scale:
            vf.append("scale=%s" % scale)
        vf += ["fps=%s" % fps, "tile=%s" % tile]
        parts.append("[%d:v]%s[r%d]" % (i, ",".join(vf), i))
    fc = ";".join(parts) + ";[r0][r1][r2]vstack=inputs=3[v]"
    argv = ["ffmpeg", "-y", "-v", "error", "-ss", str(t0), "-t", str(dur), "-i", str(SRC),
            "-ss", str(t0), "-t", str(dur), "-i", str(OLDC),
            "-ss", str(t0), "-t", str(dur), "-i", str(NEWC),
            "-filter_complex", fc, "-map", "[v]", "-frames:v", "1", str(out)]
    C.run(argv, label="montage " + out.name)
    return out


def three_up_video(out, speed=1.0):
    fc = ("[0:v]scale=640:360,setsar=1[a];[1:v]scale=640:360,setsar=1[b];"
          "[2:v]scale=640:360,setsar=1[c];[a][b][c]hstack=inputs=3[v]")
    if speed == 1.0:
        cmap, amap = "[v]", "2:a"
    else:
        fc += ";[v]setpts=%.4f*PTS[v2];[2:a]atempo=%.2f[aud]" % (1.0 / speed, speed)
        cmap, amap = "[v2]", "[aud]"
    argv = ["ffmpeg", "-y", "-v", "error", "-i", str(SRC), "-i", str(OLDC), "-i", str(NEWC),
            "-filter_complex", fc, "-map", cmap, "-map", amap, *VENC,
            "-c:a", "aac", "-b:a", "160k", str(out)]
    C.run(argv, label="3-up video " + Path(out).name)
    return out


def review_copy(src, out):
    C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "setpts=1.0*PTS",
           "-af", "anull", *VENC, "-c:a", "aac", "-b:a", "160k", str(out)],
          label="review copy " + Path(out).name)
    return out


print("[bundle] contact sheets (3 rows: source | old | new)")
for seg, t0, dur in SEGS:
    add("sheet_3up", montage(seg, t0, dur, "5x2"),
        "3-up contact sheet, 10 frames at fps=5 over %ss from t=%ss; row order %s"
        % (dur, t0, " | ".join(ROW_ORDER)))
print("[bundle] 2x centre-zoom grip strips (hands+book region)")
for seg, t0, dur in SEGS:
    add("grip_3up_2x", montage(seg, t0, dur, "6x1", crop="320:180:160:90", scale="640:360", fps=3),
        "3-up strip, 6 anchors at 2x zoom of the centre 320x180 (hands+book) over %ss from t=%ss; "
        "row order %s" % (dur, t0, " | ".join(ROW_ORDER)))
print("[bundle] full-length 3-up video 1x + 0.5x")
add("video_3up_1x", three_up_video(OUT / "m1_3up_source_old_new_1x.mp4", 1.0),
    "1920x360 hstack of source|old|new at 1x; audio track is the M1 candidate's")
add("video_3up_0.5x", three_up_video(OUT / "m1_3up_source_old_new_0.5x.mp4", 0.5),
    "same 3-up, half-speed video (setpts) + atempo 0.5 audio, for motion judgement")
print("[bundle] per-side provenance copies")
add("side_1x", review_copy(SRC, OUT / "side_source_window_1x.mp4"), "source window as-is (no audio stream)")
add("side_1x", review_copy(OLDC, OUT / "side_old_candidate_1x.mp4"), "old submitted candidate as-is")

zero = [i["path"] for i in items if not i["bytes"]]
man = {"artifact": "m1_review_manifest.json", "task_id": "MF-V1-BENCH",
       "wave": "B (round 2) - side-by-side source/old/new bundle",
       "run_id": C.RUN_ID, "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
       "verdict_label": "STRUCTURAL_ONLY__NOT_A_VISUAL_VERDICT",
       "note": "no frame of any clip was viewed on this route: every row here is a measured size, "
               "not a judgement about the book opening or the hand pointing",
       "row_order": ROW_ORDER,
       "inputs": {"source_window": {"path": str(SRC), "sha256": sha256_file(SRC)},
                  "old_candidate": {"path": str(OLDC), "sha256": sha256_file(OLDC)},
                  "new_candidate_m1": {"path": str(NEWC), "sha256": sha256_file(NEWC)}},
       "files": len(items), "nonzero": len(items) - len(zero), "zero_byte_files": zero,
       "all_images_nonzero": not zero,
       "items": items}
C.write_json(RAW / "m1_review_manifest.json", man)
C.flush_ledger()

for i in items:
    print("[bundle] %-18s %10d B  %s" % (i["kind"], i["bytes"], Path(i["path"]).name))
print("[bundle] zero-byte files: %s" % zero)
print("[bundle] ALL_NONZERO=%s" % (not zero))
print("[bundle] wrote", RAW / "m1_review_manifest.json", "commands=%d" % C.command_count())
