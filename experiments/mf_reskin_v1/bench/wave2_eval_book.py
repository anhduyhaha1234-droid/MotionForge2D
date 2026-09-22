"""MF-V1-BENCH wave-2 audit - independent CPU re-measurement of ONE frozen candidate.

Read-only with respect to every frozen artifact. Produces a JSON evidence record with:
  A. pts_audit      - container/frame/packet PTS of the candidate AND of the two
                      upstream renders (owner raw 121f, superseded r3 export), so the
                      "was the PTS normalised?" question is answered by measurement,
                      and it is unambiguous which file each number came from.
  B. audio_pcm      - bit-level PCM comparison of the candidate's audio track against
                      the source film decoded over the mapped window.
  C. frame_argmin   - per-frame nearest-neighbour (argmin) check of
                      candidate frame i against film frame 1650 + i + offset,
                      measured at NATIVE resolution (the harness pairs at 160x90).
  D. geometry       - the 640x368 vs 640x360 mismatch expressed as measured numbers.

No quality verdict is produced. Nothing here is a semantic/visual pass.
Usage:
  python wave2_eval_book.py --candidate <mp4> --film <mp4> --out <json> [--raw <mp4>] [--r3 <mp4>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def ffprobe_csv(path, entries, stream="v:0"):
    argv = ["ffprobe", "-v", "error", "-select_streams", stream,
            "-show_entries", entries, "-of", "csv=p=0", str(path)]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    rows = []
    for line in r.stdout.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        rows.append([x for x in line.split(",")])
    return rows, r.returncode, r.stderr.strip()[-300:]


def stream_facts(path):
    argv = ["ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,time_base,start_pts,start_time,nb_frames,r_frame_rate",
            "-of", "json", str(path)]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        s = (json.loads(r.stdout).get("streams") or [{}])[0]
    except Exception:
        s = {}
    return s


def pts_audit(path, expect_frames=120):
    """Frame PTS (as stored) + packet PTS (decode order) + the zero-based CFR test."""
    frames, rc1, err1 = ffprobe_csv(path, "frame=pts")
    fpts = [int(x[0]) for x in frames if x and x[0].lstrip("-").isdigit()]
    packets, rc2, err2 = ffprobe_csv(path, "packet=pts")
    ppts = [int(x[0]) for x in packets if x and x[0].lstrip("-").isdigit()]
    st = stream_facts(path)
    expected = [i * 512 for i in range(expect_frames)]
    srt = sorted(fpts)
    out = {
        "path": str(path),
        "stream": {k: st.get(k) for k in ("codec_name", "width", "height", "time_base",
                                          "start_pts", "start_time", "nb_frames", "r_frame_rate")},
        "frame_pts_count": len(fpts),
        "frame_pts_first3": fpts[:3],
        "frame_pts_first6": fpts[:6],
        "frame_pts_last": fpts[-1] if fpts else None,
        "frame_pts_min": min(fpts) if fpts else None,
        "frame_pts_max": max(fpts) if fpts else None,
        "frame_pts_sorted_equals_i_times_512": bool(srt == expected),
        "sorted_vs_expected": {
            "n_expected": len(expected), "n_actual": len(srt),
            "first_mismatch": next(([i, a, b] for i, (a, b) in enumerate(zip(srt, expected)) if a != b), None),
        },
        "packet_pts_count": len(ppts),
        "packet_pts_first6_decode_order": ppts[:6],
        "packet_delta_set_first24": sorted({ppts[i + 1] - ppts[i] for i in range(min(len(ppts) - 1, 24))}),
        "packet_pts_monotonic_decode_order": bool(ppts == sorted(ppts)),
        "ffprobe_rc": [rc1, rc2], "ffprobe_err": [err1, err2],
    }
    # the contract the harness asserts, evaluated in PRESENTATION (sorted) order
    out["contract_pts_equals_frame_id_x512_presentation_order"] = bool(srt == expected)
    return out


def pcm(path, ss=None, t=None):
    argv = ["ffmpeg", "-v", "error"]
    if ss is not None:
        argv += ["-ss", "%.6f" % ss]
    argv += ["-i", str(path)]
    if t is not None:
        argv += ["-t", "%.6f" % t]
    argv += ["-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "2", "-ar", "44100", "-"]
    r = subprocess.run(argv, capture_output=True)
    if r.returncode != 0:
        return None, r.stderr.decode("utf-8", "replace")[-300:]
    a = np.frombuffer(r.stdout, dtype="<i2").astype(np.int32)
    if a.size % 2:
        a = a[:-1]
    return a.reshape(-1, 2), ""


def audio_pcm(cand, film, ss, dur):
    c, e1 = pcm(cand)
    f, e2 = pcm(film, ss=ss, t=dur)
    if c is None or f is None:
        return {"measured": False, "err": [e1, e2]}
    n = min(len(c), len(f))
    d = np.abs(c[:n] - f[:n])
    return {"measured": True, "ss_film": ss, "duration_s": dur,
            "candidate_samples_per_channel": int(len(c)), "film_window_samples_per_channel": int(len(f)),
            "compared_samples_total": int(n * 2),
            "candidate_seconds": round(len(c) / 44100.0, 6), "film_window_seconds": round(len(f) / 44100.0, 6),
            "mae_int16_levels": round(float(d.mean()), 8),
            "max_abs_diff_int16": int(d.max()),
            "mismatch_count_samples": int((d != 0).sum()),
            "identical_fraction": round(float((d == 0).mean()), 8),
            "bit_identical": bool((d == 0).all())}


def gray_frames(path, w, h, select=None, n=None):
    argv = ["ffmpeg", "-v", "error", "-i", str(path)]
    vf = []
    if select:
        vf.append("select='%s'" % select)
    vf += ["scale=%d:%d" % (w, h), "format=gray"]
    argv += ["-vf", ",".join(vf)]
    if select:
        argv += ["-vsync", "0"]
    if n:
        argv += ["-frames:v", str(n)]
    argv += ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    r = subprocess.run(argv, capture_output=True)
    buf = r.stdout
    cnt = len(buf) // (w * h)
    return np.frombuffer(buf[:cnt * w * h], dtype=np.uint8).reshape(cnt, h, w)


def frame_argmin(cand, film, start_frame=1650, n=120, radius=3, gw=640, gh=360):
    c = gray_frames(cand, gw, gh, n=n)
    film_sel = "between(n\\,%d\\,%d)" % (start_frame - radius, start_frame + n - 1 + radius)
    f = gray_frames(film, gw, gh, select=film_sel)
    out = {"measured": False}
    if len(c) == 0 or len(f) == 0:
        out["reason"] = "empty decode"
        return out
    idx = {}          # film absolute frame number -> index in f
    for j, fn in enumerate(range(start_frame - radius, start_frame + n - 1 + radius + 1)):
        if j < len(f):
            idx[fn] = j
    rows, argmins, margin0 = [], [], []
    for i in range(min(n, len(c))):
        target = start_frame + i
        cand_offsets = {}
        for off in range(-radius, radius + 1):
            fn = target + off
            if fn not in idx:
                continue
            d = float(np.abs(c[i].astype(np.int16) - f[idx[fn]].astype(np.int16)).mean())
            cand_offsets[off] = round(d, 4)
        if not cand_offsets:
            continue
        am = min(cand_offsets, key=lambda k: cand_offsets[k])
        others = [v for k, v in cand_offsets.items() if k != 0]
        argmins.append(am)
        rows.append({"i": i, "film_frame_target": target, "argmin_offset": am,
                     "mae_offset0": cand_offsets.get(0), "mae_at_argmin": cand_offsets[am],
                     "advantage_offset0": round(min(others) - cand_offsets.get(0, 0.0), 4) if others else None})
        if others:
            margin0.append(min(others) - cand_offsets.get(0, 0.0))
    out.update({
        "measured": True, "grid": [gw, gh], "radius": radius, "frames_scored": len(rows),
        "candidate_frames_decoded": int(len(c)), "film_frames_decoded": int(len(f)),
        "argmin_offset_histogram": {str(k): argmins.count(k) for k in sorted(set(argmins))},
        "argmin_is_zero_for_all_frames": bool(all(a == 0 for a in argmins)),
        "n_argmin_zero": int(sum(1 for a in argmins if a == 0)),
        "min_advantage_of_offset0": round(float(min(margin0)), 4) if margin0 else None,
        "median_advantage_of_offset0": round(float(np.median(margin0)), 4) if margin0 else None,
        "median_mae_at_offset0": round(float(np.median([r["mae_offset0"] for r in rows])), 4),
        "per_frame": rows,
    })
    return out


def geometry(cand_stream, src_stream, harness_grid=(160, 90)):
    ch, sh = cand_stream.get("height"), src_stream.get("height")
    g = {"candidate_width_x_height": "%sx%s" % (cand_stream.get("width"), ch),
         "source_width_x_height": "%sx%s" % (src_stream.get("width"), sh),
         "height_delta_px": (ch - sh) if (ch and sh) else None,
         "vertical_ratio_candidate_over_source": round(ch / float(sh), 6) if (ch and sh) else None,
         "pct_vertical_stretch_if_scaled_to_match": round((ch / float(sh) - 1.0) * 100.0, 4) if (ch and sh) else None,
         "harness_compare_grid": "%dx%d" % harness_grid,
         "harness_scale_filter": "scale=%d:%d (ignores aspect: %d rows of 368 squeezed into 90)" % (harness_grid[0], harness_grid[1], ch),
         "harness_rows_per_source_row": round(harness_grid[1] / float(sh), 6) if sh else None,
         "harness_rows_per_candidate_row": round(harness_grid[1] / float(ch), 6) if ch else None,
         "note": "a 640x368 candidate paired with a 640x360 source under scale=160:90 is resampled at a different vertical phase than the source; any row-exact comparison (crop strips, per-frame argmin, grip-region crops) carries a sub-pixel-to-1.02x vertical mismatch"}
    return g


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--film", required=True)
    ap.add_argument("--src-clip", default=None)
    ap.add_argument("--raw", default=None)
    ap.add_argument("--r3", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    rec = {"artifact": "wave2_eval_book_r4.json", "task_id": "MF-V1-BENCH",
           "wave": "wave 2 (CPU evaluation of a frozen candidate)",
           "kind": "measurement_not_quality_score",
           "note": "no vision on this route; every semantic row stays NOT_REVIEWED"}

    rec["A_pts_audit"] = {"candidate": pts_audit(a.candidate)}
    if a.raw:
        rec["A_pts_audit"]["owner_raw_render"] = pts_audit(a.raw, expect_frames=121)
    if a.r3:
        rec["A_pts_audit"]["superseded_r3_export"] = pts_audit(a.r3)

    rec["B_audio_pcm"] = {
        "candidate_full_vs_film_55p000_plus_4p001995":
            audio_pcm(a.candidate, a.film, 55.0, 4.001995),
        "candidate_full_vs_film_55p000_plus_4p000000":
            audio_pcm(a.candidate, a.film, 55.0, 4.0),
    }

    rec["C_frame_argmin_vs_frame_map"] = frame_argmin(a.candidate, a.film)

    cs = stream_facts(a.candidate)
    ss = stream_facts(a.src_clip) if a.src_clip else stream_facts(a.film)
    rec["D_geometry"] = geometry(cs, ss)

    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote %s (%d bytes)" % (p, p.stat().st_size))
    print("A candidate pts == i*512 (presentation):", rec["A_pts_audit"]["candidate"]["contract_pts_equals_frame_id_x512_presentation_order"])
    for k, v in rec["B_audio_pcm"].items():
        print("B %-44s bit_identical=%s mae=%s samples=%s mismatches=%s" % (
            k, v.get("bit_identical"), v.get("mae_int16_levels"),
            v.get("compared_samples_total"), v.get("mismatch_count_samples")))
    c = rec["C_frame_argmin_vs_frame_map"]
    print("C argmin_zero_all=%s hist=%s median_adv=%s med_mae0=%s" % (
        c.get("argmin_is_zero_for_all_frames"), c.get("argmin_offset_histogram"),
        c.get("median_advantage_of_offset0"), c.get("median_mae_at_offset0")))
    print("D %s vs %s delta=%s px ratio=%s" % (rec["D_geometry"]["candidate_width_x_height"],
                                               rec["D_geometry"]["source_width_x_height"],
                                               rec["D_geometry"]["height_delta_px"],
                                               rec["D_geometry"]["vertical_ratio_candidate_over_source"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
