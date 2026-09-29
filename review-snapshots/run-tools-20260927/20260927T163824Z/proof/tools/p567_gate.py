"""Gates for the P5/P6 batch: TURN + OCC coverage, BOOK overlap16 seam comparison, BOOK nocache A/B.

Every number is measured from the produced media.  Vision verdicts are recorded separately by the
worker (see the report); this script writes the objective part plus the preview paths.
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
PREV = PROOF / "evidence" / "previews"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p567_frames")
SRC = {"TURN": PROOF / "inputs" / "TURN_795_src.mp4", "OCC": PROOF / "inputs" / "OCC_14768_src.mp4",
       "BOOK": PROOF / "inputs" / "BOOK_src.mp4"}
CLIPS = {
    "TURN": PROOF / "output" / "p5_turn" / "animate2_turn_p5_00001_.mp4",
    "OCC": PROOF / "output" / "p5_occ" / "animate2_occ_p5_00001_.mp4",
    "BOOK_OV16": PROOF / "output" / "p5_book_overlap16" / "animate2_book_ov16_00001_.mp4",
    "BOOK_NOCACHE": PROOF / "output" / "p6_book_nocache" / "animate2_book_nocache_00001_.mp4",
}
P3B_BOOK = PROOF / "output" / "p3b" / "animate2_book_p3b_00001_.mp4"


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
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    w, h = [int(x) for x in r.stdout.strip().split(",")[:2]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)


def save_frame(p: pathlib.Path, idx: int, tag: str) -> Image.Image:
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}{tag}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def seam_profile(p: pathlib.Path, lo: int = 68, hi: int = 96) -> dict:
    a = frames_arr(p)
    n = a.shape[0]
    d = [round(float(np.abs(a[i + 1].astype(np.int16) - a[i].astype(np.int16)).mean()), 4)
         for i in range(n - 1)]
    dd = np.array(d) if d else np.zeros(1)
    hi = min(hi, n - 1)
    window = [{"pair": f"{i}->{i + 1}", "mean_abs_diff": d[i]} for i in range(lo, hi) if i < len(d)]
    wv = np.array([w["mean_abs_diff"] for w in window]) if window else np.zeros(1)
    return {"frames": n, "median": round(float(np.median(dd)), 4),
            "p99": round(float(np.percentile(dd, 99)), 4), "max": round(float(dd.max()), 4),
            "zero_pairs": int((dd == 0).sum()), "window": window,
            "window_max": round(float(wv.max()), 4),
            "flag": "SEAM_ANOMALY_FLAGGED" if wv.max() > float(np.percentile(dd, 99)) else
                    "NO_SEAM_ANOMALY"}


def coverage(shot: str, clip: pathlib.Path, src: pathlib.Path) -> list:
    out = []
    for idx in (0, 60, 119):
        gen = save_frame(clip, idx, f"_{shot}")
        s = save_frame(src, min(idx, 119), "_src")
        sb = s.resize(gen.size, Image.Resampling.LANCZOS) if s.size != gen.size else s
        sheet = Image.new("RGB", (gen.size[0] * 2 + 8, gen.size[1] + 18), (24, 24, 28))
        sheet.paste(sb, (0, 18))
        sheet.paste(gen, (gen.size[0] + 8, 18))
        d = ImageDraw.Draw(sheet)
        d.text((4, 3), f"{shot} frame {idx}: SOURCE (left) | generated (right)",
               fill=(235, 235, 235))
        sp = PREV / f"p5_{shot.lower()}_coverage_frame{idx:03d}_src_vs_gen.png"
        sheet.save(sp)
        out.append({"frame": idx, "sheet": f"previews/{sp.name}", "gen_dims": list(gen.size)})
    return out


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    res = {}
    # --- TURN / OCC -------------------------------------------------------------------
    for shot in ("TURN", "OCC"):
        clip = CLIPS[shot]
        if not clip.is_file():
            res[shot] = {"present": False}
            continue
        p = ffprobe(clip)
        pts = pts_times(clip)
        res[shot] = {"present": True, "file": str(clip.relative_to(PROOF)).replace("\\", "/"),
                     "bytes": clip.stat().st_size, "sha256": sha(clip), "ffprobe": p,
                     "dims_640x368": [int(p.get("width", 0)), int(p.get("height", 0))] == [640, 368],
                     "frames_120": p.get("nb_read_frames") == "120",
                     "fps_30_1": p.get("r_frame_rate") == "30/1",
                     "duration_4s": p.get("duration") == "4.000000",
                     "pts_monotonic": all(b > a for a, b in zip(pts, pts[1:])),
                     "pts_count": len(pts),
                     "coverage_previews": coverage(shot, clip, SRC[shot]),
                     "motion": {k: v for k, v in seam_profile(clip).items()
                                if k in ("median", "p99", "max", "zero_pairs")}}
    (PROOF / "evidence" / "P5_TURN_OCC_GATE.json").write_text(json.dumps(
        {"artifact": "P5_TURN_OCC_GATE.json", "round": "R28-PROOF-P5",
         "shots": res, "quality_accepted": False,
         "quality_verdict_owner": "BENCH / DEMO / Codex",
         "note": "TURN/OCC gates mirror P3b: dims, 120f/30fps/4.0s, PTS monotonic, coverage "
                 "previews for the vision pass, no watermark (vision)"}, indent=1,
        ensure_ascii=False) + "\n", encoding="utf-8")

    # --- BOOK overlap16 seam comparison ----------------------------------------------
    ov = CLIPS["BOOK_OV16"]
    base = json.loads((PROOF / "evidence" / "P3B_GEOMETRY_GATE.json").read_text(encoding="utf-8"))
    if ov.is_file():
        prof = seam_profile(ov)
        strip_frames = [save_frame(ov, i, "_ov16") for i in range(68, 97)]
        w, h = strip_frames[0].size
        sc = 0.5
        tw, th = int(w * sc), int(h * sc)
        strip = Image.new("RGB", (tw * 6, (th + 18) * 5), (24, 24, 28))
        ds = ImageDraw.Draw(strip)
        for k, (im, i) in enumerate(zip(strip_frames, range(68, 97))):
            x, y = (k % 6) * tw, (k // 6) * (th + 18)
            strip.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (x, y + 18))
            ds.text((x + 3, y + 3), f"f{i}", fill=(235, 235, 235))
        sp = PREV / "p5_overlap16_seam_strip.png"
        strip.save(sp)
        gate = {"artifact": "P5_OVERLAP_GATE.json", "round": "R28-PROOF-P5",
                "hypothesis": "context_overlap 8 -> 16 reduces the frame-to-frame elevation around "
                              "the 80->81 join",
                "clip": {"file": str(ov.relative_to(PROOF)).replace("\\", "/"),
                         "bytes": ov.stat().st_size, "sha256": sha(ov), "ffprobe": ffprobe(ov)},
                "overlap16_profile": prof, "seam_strip": f"previews/{sp.name}",
                "baseline_p3b": {"clip_median": base["seam"]["clip_diff_stats"]["diff_median"],
                                 "clip_p99": base["seam"]["clip_diff_stats"]["diff_p99"],
                                 "clip_max": base["seam"]["clip_diff_stats"]["diff_max"],
                                 "join_80_81": 2.1582, "max_at_85_86": 2.3195,
                                 "verdict": base["seam"]["verdict"],
                                 "vision": "NO_VISIBLE_SEAM_DEFECT"},
                "comparison": {},
                "quality_accepted": False}
        b = gate["baseline_p3b"]
        gate["comparison"] = {
            "join_pair_80_81": {"p3b": b["join_80_81"],
                                "overlap16": next((w["mean_abs_diff"] for w in prof["window"]
                                                   if w["pair"] == "80->81"), None)},
            "clip_max": {"p3b": b["clip_max"], "overlap16": prof["max"]},
            "clip_median": {"p3b": b["clip_median"], "overlap16": prof["median"]},
            "clip_p99": {"p3b": b["clip_p99"], "overlap16": prof["p99"]},
            "window_max": {"p3b": 2.3195, "overlap16": prof["window_max"]},
            "flag": {"p3b": "SEAM_ANOMALY_FLAGGED", "overlap16": prof["flag"]},
            "delta_note": "positive delta means overlap16 LOWERED the value (improvement)"}
        (PROOF / "evidence" / "P5_OVERLAP_GATE.json").write_text(
            json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        res["BOOK_OV16"] = {"present": True, "profile": {k: prof[k] for k in
                                                         ("median", "p99", "max", "zero_pairs",
                                                          "window_max", "flag")},
                            "comparison": gate["comparison"]}
    else:
        res["BOOK_OV16"] = {"present": False}

    # --- BOOK nocache A/B -------------------------------------------------------------
    nc = CLIPS["BOOK_NOCACHE"]
    if nc.is_file():
        p = ffprobe(nc)
        pts = pts_times(nc)
        ab = []
        for idx in (0, 60, 119):
            gen = save_frame(nc, idx, "_nocache")
            ref = save_frame(P3B_BOOK, idx, "_p3b")
            sheet = Image.new("RGB", (ref.size[0] * 2 + 8, ref.size[1] + 18), (24, 24, 28))
            sheet.paste(ref, (0, 18))
            sheet.paste(gen.resize(ref.size, Image.Resampling.LANCZOS), (ref.size[0] + 8, 18))
            d = ImageDraw.Draw(sheet)
            d.text((4, 3), f"frame {idx}: P3b cache-ON (left) | P6 cache-OFF (right)",
                   fill=(235, 235, 235))
            sp = PREV / f"p6_ab_frame{idx:03d}_cacheon_vs_cacheoff.png"
            sheet.save(sp)
            ab.append({"frame": idx, "sheet": f"previews/{sp.name}"})
        rec_nc = json.loads((PROOF / "evidence" / "P6_NOCACHE_RECEIPT.json").read_text(encoding="utf-8"))
        rec_p3b = json.loads((PROOF / "evidence" / "P3B_RECEIPT.json").read_text(encoding="utf-8"))
        gate = {"artifact": "P6_NOCACHE_GATE.json", "round": "R28-PROOF-P6",
                "clip": {"file": str(nc.relative_to(PROOF)).replace("\\", "/"),
                         "bytes": nc.stat().st_size, "sha256": sha(nc), "ffprobe": p,
                         "pts_monotonic": all(b2 > a for a, b2 in zip(pts, pts[1:]))},
                "ab_previews": ab,
                "wall_table": {"cache_on_p3b": {"server_wall_s": 154.67, "vram_peak_mib": 10973},
                               "cache_off": {"server_wall_s": rec_nc.get("server_side_wall_s"),
                                             "vram_peak_mib": rec_nc.get("vram_peak_mib")},
                               "seed_identical": rec_nc.get("seed") == 582699151003550,
                               "note": "both runs are warm on the same server; the comparison is "
                                       "wall/VRAM and a visual A/B at the same seed"},
                "quality_accepted": False, "quality_verdict_owner": "BENCH / DEMO / Codex"}
        (PROOF / "evidence" / "P6_NOCACHE_GATE.json").write_text(
            json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        res["BOOK_NOCACHE"] = {"present": True, "dims": [p.get("width"), p.get("height")],
                               "frames": p.get("nb_read_frames"), "fps": p.get("r_frame_rate"),
                               "wall_s": rec_nc.get("server_side_wall_s"),
                               "vram_peak_mib": rec_nc.get("vram_peak_mib")}
    else:
        res["BOOK_NOCACHE"] = {"present": False}
    print(json.dumps(res, indent=1, ensure_ascii=False)[:2400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
