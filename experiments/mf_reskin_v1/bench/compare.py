"""MF-V1-BENCH compare.py - before/after ALIGNMENT FACTS (measurements, not scores).

Deliberately produces no quality score. Everything here is a measurement:
frame pairing offset, duration delta, audio offset in ms, per-frame |delta| in grey
levels (0-255). A metric computed against a copy of the source is a diagnostic
reconstruction check and can never be a semantic-quality pass (see GATE_VOCAB.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

GW, GH = 160, 90


def frames_gray(path, t0: float = None, duration: float = None, n: int = None,
                w: int = GW, h: int = GH):
    """Decode to greyscale frames -> ndarray (N,H,W) uint8."""
    argv = ["ffmpeg", "-v", "error"]
    if t0 is not None:
        argv += ["-ss", str(t0)]
    argv += ["-i", str(path)]
    if duration is not None:
        argv += ["-t", str(duration)]
    if n is not None:
        argv += ["-frames:v", str(n)]
    argv += ["-vf", "scale=%d:%d,format=gray" % (w, h), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = C.run_bytes(argv, label="ffmpeg decode gray %s" % Path(path).name)
    if not raw:
        return np.zeros((0, h, w), dtype=np.uint8)
    cnt = len(raw) // (w * h)
    return np.frombuffer(raw[:cnt * w * h], dtype=np.uint8).reshape(cnt, h, w)


def per_frame_absdiff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = min(len(a), len(b))
    if n == 0:
        return np.zeros((0,))
    return np.abs(a[:n].astype(np.int16) - b[:n].astype(np.int16)).mean(axis=(1, 2))


def duration_delta(a_facts: dict, b_facts: dict) -> dict:
    da = (a_facts.get("video") or {}).get("duration_s")
    db = (b_facts.get("video") or {}).get("duration_s")
    return {"a_duration_s": da, "b_duration_s": db,
            "delta_s": None if (da is None or db is None) else round(db - da, 6),
            "delta_frames_at_30fps": None if (da is None or db is None) else round((db - da) * C.FPS, 3)}


def audio_envelope(path, t0: float = None, duration: float = None, sr: int = 8000) -> np.ndarray:
    argv = ["ffmpeg", "-v", "error"]
    if t0 is not None:
        argv += ["-ss", str(t0)]
    argv += ["-i", str(path)]
    if duration is not None:
        argv += ["-t", str(duration)]
    argv += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = C.run_bytes(argv, label="ffmpeg decode audio %s" % Path(path).name)
    if not raw:
        return np.zeros((0,), dtype=np.float32)
    x = np.frombuffer(raw[: (len(raw) // 2) * 2], dtype=np.int16).astype(np.float32)
    # 20 ms RMS envelope
    hop = max(1, sr // 50)
    k = len(x) // hop
    if k < 2:
        return np.zeros((0,), dtype=np.float32)
    return np.sqrt((x[: k * hop].reshape(k, hop) ** 2).mean(axis=1))


def audio_offset(a: np.ndarray, b: np.ndarray, sr: int = 8000, max_lag_s: float = 1.0) -> dict:
    """Cross-correlate RMS envelopes -> best lag in ms (measurement, not a score)."""
    if len(a) < 4 or len(b) < 4:
        return {"measured": False, "reason": "no audio envelope on one side"}
    n = min(len(a), len(b))
    a2, b2 = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    max_lag = int(max_lag_s * sr / (sr // 50))
    lags, corrs = [], []
    denom = (np.linalg.norm(a2) * np.linalg.norm(b2)) or 1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            c = float(np.dot(a2[lag:], b2[: n - lag]) / denom)
        else:
            c = float(np.dot(a2[: n + lag], b2[-lag:]) / denom)
        lags.append(lag)
        corrs.append(c)
    i = int(np.argmax(corrs))
    return {"measured": True, "best_lag_units_20ms": lags[i],
            "best_lag_ms": round(lags[i] * 20.0, 1), "corr": round(corrs[i], 5),
            "corr_at_lag0": round(corrs[lags.index(0)], 5), "envelope_units": n}


def pairing_facts(clip: np.ndarray, src: np.ndarray, radius: int = 5) -> dict:
    """Frame correspondence: |delta| per frame for every candidate GLOBAL offset.

    The curve (median |delta| over frames vs offset) is the honest measurement: with a
    near-identical reconstruction the per-frame argmin is noise-dominated (measured: the
    per-frame histogram of a 1.0-grey-level reconstruction spreads over +-3), so the
    alignment claim rests on the whole-clip curve, not on single frames.
    Returns measurements only - never a quality score.
    """
    n = min(len(clip), len(src))
    if n == 0:
        return {"measured": False, "reason": "empty decode", "frames": 0}
    curve, mae0 = {}, []
    for off in range(-radius, radius + 1):
        vals = []
        for i in range(n):
            j = i + off
            if 0 <= j < len(src):
                vals.append(float(np.abs(clip[i].astype(np.int16) - src[j].astype(np.int16)).mean()))
        curve[off] = round(float(np.median(vals)), 4) if vals else None
        if off == 0:
            mae0 = vals
    usable = {k: v for k, v in curve.items() if v is not None}
    best_off = min(usable, key=lambda k: usable[k])
    others = [v for k, v in usable.items() if k != best_off]
    margin = round(usable[best_off] - min(others), 4) if others else None
    # discriminating power: how much does the SOURCE itself change per frame? if the shot
    # is near-static and the candidate is near-identical, the offset curve is flat and no
    # alignment claim can be made at this resolution - reported UNMEASURED, never PASS.
    sm = per_frame_absdiff(src[:-1], src[1:]) if len(src) > 1 else np.zeros((0,))
    src_motion = {
        "seen": int(len(sm)),
        "median_consecutive_absdiff": round(float(np.median(sm)), 4) if len(sm) else None,
        "p90_consecutive_absdiff": round(float(np.percentile(sm, 90)), 4) if len(sm) else None,
        "max_consecutive_absdiff": round(float(np.max(sm)), 4) if len(sm) else None,
        "candidate_vs_source_offset0": round(float(np.median(mae0)), 4) if len(mae0) else None}
    curve_spread = round(max(usable.values()) - min(usable.values()), 4) if usable else None
    discriminator = {"offset_curve_spread": curve_spread, "source_motion": src_motion}
    return {"measured": True, "frames": n, "radius": radius, "discriminator": discriminator,
            "offset_curve_median_absdiff": curve,
            "argmin_offset": best_off, "argmin_value": usable[best_off],
            "runner_up_offset": min(others, key=lambda v: v) if others else None,
            "margin_vs_runner_up": margin,
            "aligned_at_zero": best_off == 0,
            "mae_offset0_median": round(float(np.median(mae0)), 4),
            "mae_offset0_max": round(float(np.max(mae0)), 4)}


def delta_facts(clip: np.ndarray, src: np.ndarray) -> dict:
    """Per-frame absolute difference vs source (grey levels 0-255). Measurement only."""
    d = per_frame_absdiff(clip, src)
    if len(d) == 0:
        return {"measured": False, "reason": "empty decode"}
    return {"measured": True, "frames": int(len(d)),
            "mae_median": round(float(np.median(d)), 4), "mae_mean": round(float(d.mean()), 4),
            "mae_min": round(float(d.min()), 4), "mae_max": round(float(d.max()), 4),
            "fraction_frames_mae_gt_2": round(float((d > 2.0).mean()), 6),
            "identical_frames": int((d == 0).sum()),
            "per_frame_mae": [round(float(x), 4) for x in d]}


def align_report(clip_path, src_path, t0_src: float = None, duration: float = None, n: int = None) -> dict:
    clip = frames_gray(clip_path, None, duration, n)
    src = frames_gray(src_path, t0_src, duration, n)
    out = {"clip": str(clip_path), "source": str(src_path),
           "kind": "measurement_not_quality_score",
           "clip_frames_decoded": int(len(clip)), "source_frames_decoded": int(len(src)),
           "frame_pairing": pairing_facts(clip, src),
           "pixel_delta_vs_source": delta_facts(clip, src)}
    return out


if __name__ == "__main__":
    print(json.dumps(align_report(sys.argv[1], sys.argv[2]), indent=1)[:3000])
