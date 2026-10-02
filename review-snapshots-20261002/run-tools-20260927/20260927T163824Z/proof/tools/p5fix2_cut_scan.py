"""P5FIX2 step 1: cut scan of the three pinned source windows.

Measured, declared rule: decode every frame (rgb24) and, for each consecutive pair, compute
  * mean_abs_diff      = mean |f[i+1] - f[i]| over all channels
  * changed_fraction   = fraction of pixels whose max-channel change > 32
  * cut_score          = mean_abs_diff * changed_fraction
A pair is declared a CUT when changed_fraction >= 0.50 AND mean_abs_diff >= 12.0 - i.e. at least
half the picture is repainted AND the average change is large.  The distributions (median / p90 /
p99 / top-5 pairs) are written next to the verdict so the threshold can be argued from the data
instead of assumed.  Nothing is inferred from the prompt or a summary.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import numpy as np

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
WINDOWS = {"BOOK": PROOF / "inputs" / "BOOK_src.mp4",
           "TURN": PROOF / "inputs" / "TURN_795_src.mp4",
           "OCC": PROOF / "inputs" / "OCC_14768_src.mp4"}
CHANGED_PIXEL_DELTA = 32
MIN_CHANGED_FRACTION = 0.50
MIN_MEAN_ABS_DIFF = 12.0


def arr(p: pathlib.Path) -> np.ndarray:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    w, h = [int(x) for x in r.stdout.strip().split(",")[:2]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)


out = {"artifact": "P5FIX2_CUT_SCAN.json", "round": "R28-PROOF-P5FIX2",
       "rule": {"changed_pixel_delta": CHANGED_PIXEL_DELTA,
                "min_changed_fraction": MIN_CHANGED_FRACTION,
                "min_mean_abs_diff": MIN_MEAN_ABS_DIFF,
                "declare_cut_when": "changed_fraction >= 0.50 AND mean_abs_diff >= 12.0",
                "why": "a hard cut repaints most of the frame and moves the average a lot; both "
                       "conditions together avoid flagging motion or a lighting change"},
       "windows": {}}
for name, path in WINDOWS.items():
    a = arr(path).astype(np.int16)
    n = a.shape[0]
    rows = []
    for i in range(n - 1):
        d = np.abs(a[i + 1] - a[i])
        mad = float(d.mean())
        cf = float((d.max(axis=2) > CHANGED_PIXEL_DELTA).mean())
        rows.append({"pair": f"{i}->{i + 1}", "mean_abs_diff": round(mad, 4),
                     "changed_fraction": round(cf, 4), "cut_score": round(mad * cf, 4)})
    mads = np.array([r["mean_abs_diff"] for r in rows])
    cuts = [r for r in rows if r["changed_fraction"] >= MIN_CHANGED_FRACTION
            and r["mean_abs_diff"] >= MIN_MEAN_ABS_DIFF]
    top = sorted(rows, key=lambda r: -r["cut_score"])[:5]
    out["windows"][name] = {
        "file": str(path.relative_to(PROOF)).replace("\\", "/"), "frames": n,
        "stats": {"median_mean_abs_diff": round(float(np.median(mads)), 4),
                  "p90": round(float(np.percentile(mads, 90)), 4),
                  "p99": round(float(np.percentile(mads, 99)), 4),
                  "max": round(float(mads.max()), 4)},
        "top5_by_cut_score": top,
        "cuts": cuts,
        "cut_frames": sorted({int(r["pair"].split("->")[1]) for r in cuts}),
        "verdict": "CUTS_FOUND" if cuts else "NO_CUT_OVER_THRESHOLD"}
    print(name, n, "frames | cuts", out["windows"][name]["cut_frames"],
          "| median", out["windows"][name]["stats"]["median_mean_abs_diff"],
          "| max", out["windows"][name]["stats"]["max"])
(EVID / "P5FIX2_CUT_SCAN.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
print("saved P5FIX2_CUT_SCAN.json")
