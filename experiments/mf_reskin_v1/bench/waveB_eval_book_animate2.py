"""MF-V1-BENCH wave B - independent CPU verification of the frozen candidate (E2/E3/E4).

Read-only on every frozen artifact. Every external command goes through common.run/run_bytes
so the run's command ledger covers the independent verification too, not just run_dryrun.py.

E2  audio: decode the clip's first 4 s and the film's [55.000, 59.000) window to PCM and
    compare; report bit-exactness, sample counts, MAE, mismatch count and the PCM sha256 of
    BOTH sides. Container delta and decoded delta are separate labelled numbers.
E3  geometry: prove the delivered frame is 640x360 and locate the content rect by measuring
    the row offset against the raw 640x368 render (4 px pad top + bottom).
E4  frame pairing: measure whether the harness's offset-0 rule has discriminating power on
    this window, with two controls built from the film itself (a known 0-shift pair and a
    known +5-shift pair) so the candidate's deviation is comparable to a real shift.

No quality verdict, no visual claim.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

WT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")
sys.path.insert(0, str(WT / "experiments" / "mf_reskin_v1" / "bench"))
import common as C          # noqa: E402

# F10 isolation (c3): this evaluation's evidence ledger is the packet ledger, so it says so
# explicitly instead of inheriting it as a process-global default.
C.set_ledger_path(C.EVIDENCE_LEDGER)

NEW = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-correction-20260922/20260922T0955Z")
FROZEN = NEW / "manager" / "frozen"
CAND = FROZEN / "BOOK_animate2_waveB" / "files" / "final_book4s_decoded119_640x360.mp4"
RAW = FROZEN / "BOOK_animate2_waveB" / "files" / "media" / "chosen_animate2_book4s_00003_.mp4"
SRC = FROZEN / "BOOK_animate2_waveA_inputs" / "files" / "src_windows" / "BOOK_src.mp4"
FILM = C.REF_FILM
OUT = NEW / "BENCH" / "waveB" / "raw" / "waveB_eval_animate2.json"
WSF = 1650                       # film frame the window starts on
NF = 120


def sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pcm_interleaved(path, ss=None, t=None):
    argv = ["ffmpeg", "-v", "error"]
    if ss is not None:
        argv += ["-ss", "%.6f" % ss]
    argv += ["-i", str(path)]
    if t is not None:
        argv += ["-t", "%.6f" % t]
    argv += ["-vn", "-acodec", "pcm_s16le", "-ac", "2", "-ar", "44100", "-f", "s16le", "-"]
    raw = C.run_bytes(argv, label="pcm %s ss=%s t=%s" % (Path(path).name, ss, t))
    a = np.frombuffer(raw, dtype="<i2")
    if a.size % 2:
        a = a[:-1]
    return raw, a.reshape(-1, 2)


def compare_pcm(c, f):
    n = min(len(c), len(f))
    d = np.abs(c[:n].astype(np.int32) - f[:n].astype(np.int32))
    return {"compared_samples_total": int(n * 2), "mae_int16_levels": round(float(d.mean()), 8),
            "max_abs_diff_int16": int(d.max()), "mismatch_count_samples": int((d != 0).sum()),
            "identical_fraction": round(float((d == 0).mean()), 8), "bit_exact": bool((d == 0).all())}


def ffprobe_json(path, entries):
    rc, out, err = C.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                         label="ffprobe %s" % Path(path).name)
    if rc != 0:
        raise SystemExit("ffprobe failed: %s" % err[-300:])
    return json.loads(out)


def gray_frame(path, w, h, select=None, n=None):
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
    buf = C.run_bytes(argv, label="gray %s w=%d h=%d sel=%s n=%s" % (Path(path).name, w, h, select, n))
    cnt = len(buf) // (w * h)
    return np.frombuffer(buf[:cnt * w * h], dtype=np.uint8).reshape(cnt, h, w)


def pairing_ext(a, b, radius=15):
    """pairing_facts with a bigger radius, at NATIVE resolution. Measurement only."""
    n = min(len(a), len(b))
    curve = {}
    for off in range(-radius, radius + 1):
        vals = [float(np.abs(a[i].astype(np.int16) - b[i + off].astype(np.int16)).mean())
                for i in range(n) if 0 <= i + off < len(b)]
        curve[off] = round(float(np.median(vals)), 6) if vals else None
    usable = {k: v for k, v in curve.items() if v is not None}
    lo, hi = min(usable.values()), max(usable.values())
    best = min(usable, key=lambda k: usable[k])
    others = [v for k, v in usable.items() if k != best]
    margin = round(usable[best] - min(others), 6)
    return {"curve": curve, "argmin": best, "margin_over_runner_up": margin,
            "curve_min": lo, "curve_max": hi, "spread": round(hi - lo, 6),
            "median_absdiff": usable.get(0),
            "margin_relative_to_median_pct": round(abs(margin) / usable[best] * 100.0, 6) if usable[best] else None}


rec = {"artifact": "waveB_eval_animate2.json", "task_id": "MF-V1-BENCH",
       "wave": "B (CPU evaluation of the frozen candidate BOOK_animate2_waveB)",
       "kind": "measurement_not_quality_score", "run_id": C.RUN_ID,
       "no_vision": "every semantic row stays NOT_REVIEWED; nothing here is a quality pass",
       "frozen_inputs": {"candidate_clip": str(CAND), "raw_render": str(RAW),
                         "source_window": str(SRC), "source_film": str(FILM),
                         "film_sha256_matches_pin": C.sha256_file(FILM) == C.REF_FILM_SHA}}

# --------------------------------------------------------------------------- E2 audio
cand_bytes, cand = pcm_interleaved(CAND, t=4.0)
film_bytes, film = pcm_interleaved(FILM, ss=55.0, t=4.0)
e2 = {"A_requested_first_4s": {
        "candidate": {"decode": "candidate, -t 4.000000 (no -ss)", "samples_per_channel": int(len(cand)),
                      "total_samples_2ch": int(cand.size), "pcm_sha256": sha_b(cand_bytes)},
        "film_window": {"decode": "film, -ss 55.000000 -t 4.000000", "samples_per_channel": int(len(film)),
                        "total_samples_2ch": int(film.size), "pcm_sha256": sha_b(film_bytes)},
        "window": "[55.000, 59.000) = 4.000000 s exactly"}}
e2["A_requested_first_4s"].update(compare_pcm(cand, film))

cand_full_bytes, cand_full = pcm_interleaved(CAND)
film_full_bytes, film_full = pcm_interleaved(FILM, ss=55.0, t=4.001995)
e2["B_full_stream"] = {
    "candidate_full_seconds": round(len(cand_full) / 44100.0, 6),
    "candidate_samples_per_channel": int(len(cand_full)), "candidate_pcm_sha256": sha_b(cand_full_bytes),
    "film_window": "[55.000, 60.001995)", "film_samples_per_channel": int(len(film_full)),
    "film_pcm_sha256": sha_b(film_full_bytes)}
e2["B_full_stream"].update(compare_pcm(cand_full, film_full))
e2["B_full_stream"]["decoded_delta_samples_per_channel"] = int(len(cand_full) - len(film_full))
e2["B_full_stream"]["decoded_delta_ms"] = round((len(cand_full) - len(film_full)) / 44.1, 6)
tail = film_full[len(cand_full):] if len(film_full) > len(cand_full) else None
e2["B_full_stream"]["film_tail_beyond_candidate"] = (None if tail is None else
                                                     {"samples_per_channel": int(len(tail)),
                                                      "pcm_sha256": sha_b(tail.tobytes())})

probe = ffprobe_json(CAND, "stream=index,codec_type,codec_name,duration,nb_frames,sample_rate,channels,time_base,width,height")
streams = {s["codec_type"]: s for s in probe.get("streams", [])}
v_dur, a_dur = float(streams["video"]["duration"]), float(streams["audio"]["duration"])
e2["C_deltas"] = {"container_delta_audio_minus_video_ms": round((a_dur - v_dur) * 1000.0, 6),
                  "container_audio_duration_s": a_dur, "container_video_duration_s": v_dur,
                  "container_vs_requested_4s_ms": round((a_dur - 4.0) * 1000.0, 6),
                  "decoded_delta_samples_per_channel": e2["B_full_stream"]["decoded_delta_samples_per_channel"],
                  "decoded_delta_ms": e2["B_full_stream"]["decoded_delta_ms"],
                  "audio_nb_frames": streams["audio"].get("nb_frames"),
                  "label": "container delta = STREAM duration difference; decoded delta = decoded PCM sample "
                           "difference - two different numbers, kept separate"}
rec["E2_audio"] = e2
rec["E2_requested"] = {"bit_exact": e2["A_requested_first_4s"]["bit_exact"],
                       "sample_count": {"candidate_total_2ch": e2["A_requested_first_4s"]["candidate"]["total_samples_2ch"],
                                        "film_window_total_2ch": e2["A_requested_first_4s"]["film_window"]["total_samples_2ch"]},
                       "mae": e2["A_requested_first_4s"]["mae_int16_levels"],
                       "mismatches": e2["A_requested_first_4s"]["mismatch_count_samples"],
                       "pcm_sha256_candidate": e2["A_requested_first_4s"]["candidate"]["pcm_sha256"],
                       "pcm_sha256_film_window": e2["A_requested_first_4s"]["film_window"]["pcm_sha256"],
                       "container_delta_ms": e2["C_deltas"]["container_delta_audio_minus_video_ms"],
                       "container_minus_4s_ms": e2["C_deltas"]["container_vs_requested_4s_ms"],
                       "decoded_delta_samples": e2["C_deltas"]["decoded_delta_samples_per_channel"]}

# --------------------------------------------------------------------------- E3 geometry
cw, ch = streams["video"].get("width"), streams["video"].get("height")
rs = ffprobe_json(RAW, "stream=width,height,codec_name,nb_frames,r_frame_rate")["streams"][0]
pad = (rs["height"] - ch) // 2
e3 = {"clip_wh": "%sx%s" % (cw, ch), "raw_wh": "%sx%s" % (rs["width"], rs["height"]),
      "clip_stream": {"codec": streams["video"]["codec_name"], "width": cw, "height": ch},
      "raw_stream": {"codec": rs["codec_name"], "width": rs["width"], "height": rs["height"], "nb_frames": rs.get("nb_frames")},
      "declared_pad_px_per_side": pad}

clip_f0 = gray_frame(CAND, cw, ch, n=1)[0].astype(np.int16)
raw_f0 = gray_frame(RAW, rs["width"], rs["height"], n=1)[0].astype(np.int16)
curve = {y: round(float(np.abs(clip_f0 - raw_f0[y:y + ch]).mean()), 6) for y in range(0, rs["height"] - ch + 1)}
best_y = min(curve, key=lambda k: curve[k])
e3["crop_offset_scan_y"] = curve
e3["crop_offset_measured_y"] = best_y
e3["crop_offset_declared_y"] = pad
e3["mae_at_declared_offset"] = curve[pad]
e3["mae_at_zero_offset_no_crop"] = curve[0]
hcurve = {}
for dx in (-2, -1, 0, 1, 2):
    if dx < 0:
        a, b = clip_f0[:, :cw + dx], raw_f0[best_y:best_y + ch, -dx:]
    elif dx > 0:
        a, b = clip_f0[:, dx:], raw_f0[best_y:best_y + ch, :cw - dx]
    else:
        a, b = clip_f0, raw_f0[best_y:best_y + ch]
    hcurve[dx] = round(float(np.abs(a - b).mean()), 6)
e3["crop_offset_scan_x_at_best_y"] = hcurve
e3["crop_offset_measured_x"] = min(hcurve, key=lambda k: hcurve[k])

rows_off = {}
for r in range(ch):
    lo = max(0, r - 2)
    win = raw_f0[lo:min(rs["height"], r + 7)]
    vals = {(lo + k) - r: float(np.abs(clip_f0[r] - win[k]).mean()) for k in range(len(win))}
    rows_off[r] = min(vals, key=lambda k: vals[k])
hist = {}
for r, v in rows_off.items():
    hist[str(v)] = hist.get(str(v), 0) + 1
e3["per_row_best_raw_offset_histogram"] = dict(sorted(hist.items(), key=lambda kv: int(kv[0])))
e3["per_row_best_raw_offset_mode"] = int(max(hist, key=lambda k: hist[k]))
e3["fraction_rows_matching_r_plus_pad"] = round(sum(1 for v in rows_off.values() if v == pad) / float(ch), 6)
e3["fraction_rows_matching_r_plus_0"] = round(sum(1 for v in rows_off.values() if v == 0) / float(ch), 6)
e3["raw_pad_band_stats"] = {
    "raw_top_rows_mean": [round(float(raw_f0[i].mean()), 4) for i in range(0, pad)],
    "row3_vs_row4_mae": round(float(np.abs(raw_f0[pad - 1] - raw_f0[pad]).mean()), 6),
    "raw_bottom_rows_mean": [round(float(raw_f0[i].mean()), 4) for i in range(rs["height"] - pad, rs["height"])],
    "row364_vs_row363_mae": round(float(np.abs(raw_f0[rs["height"] - pad] - raw_f0[rs["height"] - pad - 1]).mean()), 6),
    "raw_rows": int(rs["height"]), "clip_rows": int(ch)}
e3["bands_absent_in_clip"] = {
    "reason": "the clip has %d rows; the raw content rect is rows [%d, %d) of the raw's %d rows, so the %d+%d pad "
              "rows cannot be present" % (ch, pad, pad + ch, rs["height"], pad, pad),
    "measured_offset_equals_pad": best_y == pad,
    "clip_row0_best_raw_row_offset": rows_off.get(0), "fraction_rows_at_r_plus_0": e3["fraction_rows_matching_r_plus_0"],
    "raw_rows_present_in_clip": int(ch), "raw_rows_dropped": int(rs["height"] - ch)}

cf = gray_frame(CAND, cw, ch, n=NF).astype(np.int16)
rf = gray_frame(RAW, rs["width"], rs["height"], n=NF).astype(np.int16)[:, pad:pad + ch, :]
per = [round(float(np.abs(cf[i] - rf[i]).mean()), 6) for i in range(min(len(cf), len(rf)))]
e3["clip_vs_raw_cropped_per_frame_mae"] = {"frames": len(per), "mae_max": max(per), "mae_mean": round(float(np.mean(per)), 6),
                                           "first10": per[:10]}
rec["E3_geometry"] = e3

# --------------------------------------------------------------------------- E4 pairing power
cand_native = cf                                  # candidate at native 640x360, 120 frames
src_native = gray_frame(SRC, cw, ch, n=NF)
film_win = gray_frame(FILM, cw, ch, select="between(n\\,%d\\,%d)" % (WSF, WSF + NF - 1))
film_win_p5 = gray_frame(FILM, cw, ch, select="between(n\\,%d\\,%d)" % (WSF + 5, WSF + NF + 4))

e4 = {"metric": "whole-clip median per-frame |delta| vs frame offset, NATIVE %dx%d, radius 15" % (cw, ch),
      "harness_rule": "PASS needs a strict minimum at offset 0 with margin >= 0.01; a FLAT curve is UNMEASURED",
      "note": "two controls are built from the film itself: a known 0-shift pair (frozen source window vs film "
              "frames [1650,1770)) and a known +5-shift pair (film [1655,1775) vs film [1650,1770)). A candidate "
              "deviation can only be read as a frame shift if it is comparable to what a REAL +5 shift produces."}
e4["candidate_vs_source_window"] = pairing_ext(cand_native, src_native)
e4["control_known_0_shift_source_vs_film_window"] = pairing_ext(src_native, film_win)
e4["control_known_5_shift_film_plus5_vs_film_window"] = pairing_ext(film_win_p5, film_win)

per_argmin = {}
for i in range(min(NF, len(cand_native), len(src_native))):
    vals = {off: float(np.abs(cand_native[i].astype(np.int16) - src_native[i + off].astype(np.int16)).mean())
            for off in range(-5, 6) if 0 <= i + off < len(src_native)}
    if vals:
        am = min(vals, key=lambda k: vals[k])
        per_argmin[am] = per_argmin.get(am, 0) + 1
e4["candidate_per_frame_argmin_histogram"] = dict(sorted(per_argmin.items()))
e4["candidate_per_frame_argmin_zero_fraction"] = round(per_argmin.get(0, 0) / float(NF), 6)
e4["frames_decoded"] = {"candidate": int(len(cf)), "source_window": int(len(src_native)),
                        "film_window": int(len(film_win)), "film_window_plus5": int(len(film_win_p5))}
rec["E4_pairing"] = e4

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
C.flush_ledger()

print("E2 requested-4s: bit_exact=%s cand_total_2ch=%d film_total_2ch=%d mae=%s mismatches=%d" % (
    e2["A_requested_first_4s"]["bit_exact"], e2["A_requested_first_4s"]["candidate"]["total_samples_2ch"],
    e2["A_requested_first_4s"]["film_window"]["total_samples_2ch"], e2["A_requested_first_4s"]["mae_int16_levels"],
    e2["A_requested_first_4s"]["mismatch_count_samples"]))
print("   pcm sha cand=%s film=%s" % (e2["A_requested_first_4s"]["candidate"]["pcm_sha256"],
                                      e2["A_requested_first_4s"]["film_window"]["pcm_sha256"]))
print("E2 full: cand=%d film=%d bit_exact=%s decoded_delta=%s samples / %s ms | container delta audio-video=%s ms, container-4s=%s ms" % (
    e2["B_full_stream"]["candidate_samples_per_channel"], e2["B_full_stream"]["film_samples_per_channel"],
    e2["B_full_stream"]["bit_exact"], e2["C_deltas"]["decoded_delta_samples_per_channel"],
    e2["C_deltas"]["decoded_delta_ms"], e2["C_deltas"]["container_delta_audio_minus_video_ms"],
    e2["C_deltas"]["container_vs_requested_4s_ms"]))
print("E3 clip=%s raw=%s pad=%d measured_offset_y=%d (mae %.6f) vs y=0 (mae %.6f) vs declared y=%d (mae %.6f)" % (
    e3["clip_wh"], e3["raw_wh"], pad, best_y, curve[pad], curve[0], pad, curve[pad]))
print("E3 per-row offset mode=%d frac_at_pad=%.4f frac_at_0=%.4f x=%d | clip-vs-raw-crop mae_max=%s" % (
    e3["per_row_best_raw_offset_mode"], e3["fraction_rows_matching_r_plus_pad"], e3["fraction_rows_matching_r_plus_0"],
    e3["crop_offset_measured_x"], e3["clip_vs_raw_cropped_per_frame_mae"]["mae_max"]))
for k in ("candidate_vs_source_window", "control_known_0_shift_source_vs_film_window",
          "control_known_5_shift_film_plus5_vs_film_window"):
    p = e4[k]
    print("E4 %-46s argmin=%+d margin=%s spread=%s median0=%s rel=%s%%" % (
        k, p["argmin"], p["margin_over_runner_up"], p["spread"], p["median_absdiff"], p["margin_relative_to_median_pct"]))
    print("      curve:", json.dumps(p["curve"]))
print("   candidate per-frame argmin hist=%s zero_frac=%.4f" % (json.dumps(e4["candidate_per_frame_argmin_histogram"]),
                                                                e4["candidate_per_frame_argmin_zero_fraction"]))
print("wrote", OUT, "commands=%d" % C.command_count())
