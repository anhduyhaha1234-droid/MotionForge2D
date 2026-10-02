"""P3b verification: geometry gate, coverage previews, seam analysis (P5) and decode checks.

All numbers come from the produced media:
  * dims must equal the declared target 640x368 (the fixed chain), frames 120, fps 30/1, PTS
    monotonic - read from ffprobe.
  * coverage: frames 0/60/119 extracted next to the same source frames so a human/reviewer can see
    whether the table, the back-facing figure and the right-edge partial BOOK-P4 are back.
  * seam (P5): the graph's chunks are 81 frames with an 8-frame overlap, so the join sits around
    frames 73-81.  The strip frames 68..96 are extracted, and the frame-to-frame mean-abs-diff
    profile over the WHOLE clip is compared with the seam window: a seam jump would spike above
    the clip's own p99, a stall would show an exactly-zero diff across the join.  Report numbers,
    not adjectives.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
P3B = PROOF / "output" / "p3b"
PREV = PROOF / "evidence" / "previews"
SRC = PROOF / "inputs" / "BOOK_src.mp4"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p3b_frames")
MAIN = "animate2_book_p3b_00001_.mp4"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate,duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0] if r.returncode == 0 else {"error": r.stderr[-200:]}


def pts_times(p: pathlib.Path) -> list:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        tok = line.strip().split(",")[0].strip()
        if tok:
            try:
                out.append(round(float(tok), 5))
            except ValueError:
                pass
    return out


def frames_arr(p: pathlib.Path) -> np.ndarray:
    """decode the whole clip to a uint8 array [N,H,W,3] via rawvideo pipe"""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    w, h = [int(x) for x in r.stdout.strip().split(",")[:2]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)


def save_frame(p: pathlib.Path, idx: int) -> Image.Image:
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    vids = sorted(P3B.glob("*.mp4"))
    main_v = P3B / MAIN
    assert main_v.is_file(), f"missing {MAIN} in {P3B}"
    probe = ffprobe(main_v)
    pts = pts_times(main_v)
    arr = frames_arr(main_v)
    n = arr.shape[0]
    diffs = [round(float(np.abs(arr[i + 1].astype(np.int16) - arr[i].astype(np.int16)).mean()), 4)
             for i in range(n - 1)]
    d = np.array(diffs) if diffs else np.zeros(1)
    # seam window: chunks of 81 with 8 overlap -> joins near 73..81; inspect 68..96
    lo, hi = 68, min(96, n - 1)
    seam = [{"pair": f"{i}->{i + 1}", "mean_abs_diff": diffs[i]} for i in range(lo, hi) if i < len(diffs)]
    seam_vals = np.array([s["mean_abs_diff"] for s in seam]) if seam else np.zeros(1)
    stats = {"frames": n, "diff_median": round(float(np.median(d)), 4),
             "diff_p90": round(float(np.percentile(d, 90)), 4),
             "diff_p99": round(float(np.percentile(d, 99)), 4),
             "diff_min": round(float(d.min()), 4), "diff_max": round(float(d.max()), 4),
             "zero_diff_pairs": int((d == 0).sum())}
    seam_verdict = ("NO_SEAM_ANOMALY" if seam_vals.max() <= stats["diff_p99"] and
                    int((seam_vals == 0).sum()) == 0 else "SEAM_ANOMALY_FLAGGED")
    # coverage previews
    cov = []
    for idx in (0, 60, n - 1):
        gen = save_frame(main_v, idx)
        src = save_frame(SRC, min(idx, 119))
        src_b = src.resize(gen.size, Image.Resampling.LANCZOS) if src.size != gen.size else src
        sheet = Image.new("RGB", (gen.size[0] * 2 + 8, gen.size[1] + 18), (24, 24, 28))
        sheet.paste(src_b, (0, 18))
        sheet.paste(gen, (gen.size[0] + 8, 18))
        dd = ImageDraw.Draw(sheet)
        dd.text((4, 3), f"frame {idx}: SOURCE (left) | P3b generated (right)", fill=(235, 235, 235))
        sp = PREV / f"p3b_coverage_frame{idx:03d}_src_vs_gen.png"
        sheet.save(sp)
        cov.append({"frame": idx, "sheet": f"previews/{sp.name}",
                    "gen_dims": list(gen.size), "src_dims": list(src.size)})
    # seam strip
    strip_frames = [save_frame(main_v, i) for i in range(lo, hi + 1)]
    w, h = strip_frames[0].size
    sc = 0.5
    tw, th = int(w * sc), int(h * sc)
    strip = Image.new("RGB", (tw * 6, (th + 18) * 5), (24, 24, 28))
    ds = ImageDraw.Draw(strip)
    for k, (im, i) in enumerate(zip(strip_frames, range(lo, hi + 1))):
        x, y = (k % 6) * tw, (k // 6) * (th + 18)
        strip.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (x, y + 18))
        ds.text((x + 3, y + 3), f"f{i}", fill=(235, 235, 235))
    sp = PREV / "p3b_seam_strip.png"
    strip.save(sp)
    gate = {"artifact": "P3B_GEOMETRY_GATE.json", "round": "R28-PROOF-P3B",
            "graph": "graphs/animate2_book.p3b.api.json",
            "graph_sha256": sha(PROOF / "graphs" / "animate2_book.p3b.api.json"),
            "expected_dims": [640, 368],
            "main_clip": {"file": f"p3b/{MAIN}", "sha256": sha(main_v), "bytes": main_v.stat().st_size,
                          "ffprobe": probe},
            "dims_gate": {"pass": [int(probe.get("width", 0)), int(probe.get("height", 0))] == [640, 368],
                          "measured": [probe.get("width"), probe.get("height")]},
            "timing_gate": {"frames": probe.get("nb_read_frames"), "fps": probe.get("r_frame_rate"),
                            "duration": probe.get("duration"),
                            "frames_120": probe.get("nb_read_frames") == "120",
                            "fps_30_1": probe.get("r_frame_rate") == "30/1",
                            "duration_4s": probe.get("duration") == "4.000000",
                            "pts_first": pts[0] if pts else None,
                            "pts_last": pts[-1] if pts else None,
                            "pts_count": len(pts),
                            "pts_monotonic": all(b > a for a, b in zip(pts, pts[1:]))},
            "crop_policy": "ResizeAndPadImage pads CENTERED (4 rows top + 4 rows bottom) so the "
                           "640x368 target keeps the full 640x360 content; recovering the source "
                           "shape at assembly means cropping 4 rows from each side, never the sides",
            "coverage_previews": cov,
            "coverage_verdict": "SEE_VISION_PASS",
            "seam": {"window_pairs": [lo, hi], "values": seam, "clip_diff_stats": stats,
                     "verdict": seam_verdict, "strip": "previews/p3b_seam_strip.png",
                     "method": "frame-to-frame mean abs diff on the decoded frames; the join is "
                               "expected near 73-81 (chunk 81, overlap 8)"},
            "all_other_videos": {p.name: {"bytes": p.stat().st_size, "sha256": sha(p),
                                          "ffprobe": ffprobe(p)} for p in vids if p != main_v},
            "quality_accepted": False,
            "quality_verdict_owner": "BENCH / DEMO / Codex"}
    (PROOF / "evidence" / "P3B_GEOMETRY_GATE.json").write_text(
        json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"dims": gate["dims_gate"], "timing": gate["timing_gate"],
                      "seam_verdict": seam_verdict, "stats": stats,
                      "seam_max": round(float(seam_vals.max()), 4),
                      "coverage": [c["sheet"] for c in cov]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
