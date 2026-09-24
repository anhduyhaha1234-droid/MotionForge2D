"""MF-V1-BENCH assertions.py - automated assertions, each with a NEGATIVE CONTROL.

An assertion without a failing negative control is not evidence. Every assertion
below names the deliberately broken input that must make it FAIL; build_broken()
produces those inputs with ffmpeg on CPU only, and run_negative_controls() records
the measured verdict of the assertion on the broken input.

Verdicts: PASS / FAIL / UNMEASURED (empty measurement is never PASS - F02 lesson).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C          # noqa: E402
import probe as P           # noqa: E402
import compare as CMP       # noqa: E402

# static ffmpeg encoder settings for negative controls (CPU only)
VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def _rr(v):
    if not v:
        return None
    s = str(v)
    if "/" in s:
        n, d = s.split("/")
        try:
            return round(float(n) / float(d), 6)
        except ZeroDivisionError:
            return None
    try:
        return round(float(s), 6)
    except ValueError:
        return None


def _verdict(ok, measured):
    if measured is None:
        return "UNMEASURED"
    return "PASS" if ok else "FAIL"


def frame_signals(path, w: int = 160, h: int = 90, n: int = None):
    arr = CMP.frames_gray(path, None, None, n, w, h)
    if len(arr) == 0:
        return None
    std = arr.reshape(len(arr), -1).std(axis=1)
    uniq = np.array([len(np.unique(f)) for f in arr])
    mean = arr.reshape(len(arr), -1).mean(axis=1)
    return {"arr": arr, "std": std, "unique": uniq, "mean": mean}


# --------------------------------------------------------------------------- #
# assertions
# --------------------------------------------------------------------------- #

def a_frame_count_exact(path, spec):
    d = P.decoded_frame_count(path)
    exp = spec.get("expected_frames")
    m = d.get("nb_read_frames")
    return {"assertion": "frame_count_exact", "measured": {"decoded_frames": m, "declared_nb_frames": d.get("nb_frames"), "expected": exp},
            "rule": "decoded frame count == expected window length (120 frames = 4.000 s @30fps)",
            "verdict": _verdict(m == exp, m), "negative_control": "TAIL_TRUNCATE (-frames:v 90)"}


def a_pts_contract(path, spec):
    t0 = spec.get("pts_t0", 0.0)
    dur = spec.get("pts_duration")
    pc = P.pts_contract(path, t0, dur, window_start_frame=spec.get("window_start_frame"),
                        window_frame_count=spec.get("window_frame_count"))
    return {"assertion": "pts_contract", "measured": {"sampled_frames": pc["sampled_frames"], "first_pts": pc["first_pts"],
                                                      "last_pts": pc["last_pts"], "timebase_den": pc["timebase_den"],
                                                      "ticks_per_frame": pc["ticks_per_frame"],
                                                      "violations": {k: (len(v) if isinstance(v, list) else v) for k, v in pc["violations"].items()},
                                                      "violation_samples": {k: v[:3] for k, v in pc["violations"].items() if v}},
            "rule": "pts = frame_id * 512 exactly, tb 1/15360, t = frame_id/30, contiguous",
            "verdict": _verdict(pc["ok"], pc["sampled_frames"]), "negative_control": "DROP_RANGE (select drops frames 30..59, fps_mode passthrough)"}


def a_duration_contract(path, spec):
    f = P.container_facts(path)
    v = f.get("video") or {}
    dur = f.get("format_duration_s") if f.get("format_duration_s") is not None else v.get("duration_s")
    exp_dur = (spec.get("expected_frames") / float(C.FPS)) if spec.get("expected_frames") else None
    ok_rate = _rr(v.get("r_frame_rate")) == 30.0 and _rr(v.get("avg_frame_rate")) == 30.0
    ok_dur = (dur is not None and exp_dur is not None and abs(dur - exp_dur) <= (1.0 / C.FPS))
    return {"assertion": "duration_contract", "measured": {"r_frame_rate": v.get("r_frame_rate"), "avg_frame_rate": v.get("avg_frame_rate"),
                                                           "container_duration_s": dur, "expected_duration_s": exp_dur,
                                                           "delta_frames": None if (dur is None or exp_dur is None) else round((dur - exp_dur) * C.FPS, 3)},
            "rule": "r_frame_rate == avg_frame_rate == 30/1 and duration within 1 frame of frames/30 (CFR, no silent fps change)",
            "verdict": _verdict(bool(ok_rate and ok_dur), dur), "negative_control": "FPS_25 (re-encode at 25 fps)"}


def a_video_codec_contract(path, spec):
    f = P.container_facts(path)
    v = f.get("video") or {}
    want = spec.get("video") or {}
    got = {k: v.get(k) for k in ("codec", "width", "height", "pix_fmt")}
    ok = all(got.get(k) == want.get(k) for k in want)
    return {"assertion": "video_codec_contract", "measured": {"got": got, "want": want},
            "rule": "video codec/size/pix_fmt as declared in the acceptance spec",
            "verdict": _verdict(ok, got.get("codec")), "negative_control": "DOWNSCALE (scale=320:180)"}


def a_audio_contract(path, spec):
    a = P.audio_facts(path)
    want = spec.get("audio") or {}
    if not a.get("present"):
        v = "NOT_APPLICABLE" if spec.get("audio_optional") else "FAIL"
        return {"assertion": "audio_contract", "measured": {"present": False, "want": want},
                "rule": "when audio is required the stream must exist with the declared codec/rate/channels; when optional, absence is NOT_APPLICABLE (never PASS)",
                "verdict": v, "negative_control": "NO_AUDIO (-an)"}
    got = {k: a.get(k) for k in want}
    ok = all(got.get(k) == want.get(k) for k in want)
    return {"assertion": "audio_contract", "measured": {"present": True, "got": got, "want": want,
                                                        "duration_s": a.get("duration_s"),
                                                        "sample_rate": a.get("sample_rate"), "channels": a.get("channels"),
                                                        "codec": a.get("codec"), "bit_rate": a.get("bit_rate")},
            "rule": "audio stream codec/sample-rate/channels equal the declared contract",
            "verdict": _verdict(ok, a.get("codec")), "negative_control": "NO_AUDIO (-an)"}


def a_non_degenerate(path, spec):
    sig = frame_signals(path)
    if sig is None:
        return {"assertion": "non_degenerate_frames", "measured": None, "rule": "no all-black / zero-variance frames",
                "verdict": "UNMEASURED", "negative_control": "BLACK_TAIL (drawbox fill enable gte(n,90))"}
    min_std = float(sig["std"].min())
    min_uniq = int(sig["unique"].min())
    bad = [int(i) for i in np.where(sig["std"] < 1.0)[0]]
    ok = (min_std >= 1.0) and (min_uniq >= 4)
    return {"assertion": "non_degenerate_frames", "measured": {"min_per_frame_std": round(min_std, 4),
                                                              "min_unique_gray_levels": min_uniq,
                                                              "degenerate_frames": bad[:20], "degenerate_count": len(bad),
                                                              "frames": int(len(sig["std"]))},
            "rule": "every frame has per-frame grey std >= 1.0 and >= 4 unique grey levels",
            "verdict": _verdict(ok, sig["std"]), "negative_control": "BLACK_TAIL (drawbox fill enable gte(n,90))"}


def a_not_frozen(path, spec):
    sig = frame_signals(path)
    if sig is None or len(sig["arr"]) < 2:
        return {"assertion": "not_frozen", "measured": None, "rule": "no long run of byte-identical consecutive frames",
                "verdict": "UNMEASURED", "negative_control": "FREEZE_TAIL (frame 89 repeated for 30 frames)"}
    d = CMP.per_frame_absdiff(sig["arr"][:-1], sig["arr"][1:])
    runs, cur = [], 0
    for x in d:
        if x == 0:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    max_run = max(runs) if runs else 0
    ok = max_run <= spec.get("max_identical_run", 2)
    return {"assertion": "not_frozen", "measured": {"max_identical_consecutive_run": max_run, "runs": runs[:20],
                                                    "frames": int(len(sig["arr"])), "threshold": spec.get("max_identical_run", 2)},
            "rule": "longest run of identical consecutive frames <= 2 (a stuck/frozen frame is not motion)",
            "verdict": _verdict(ok, d), "negative_control": "FREEZE_TAIL (frame 89 repeated for 30 frames)"}


def a_not_source_copy(path, spec):
    src = spec.get("source_clip")
    if not src:
        return {"assertion": "not_source_copy", "measured": None, "rule": "props/background must actually change",
                "verdict": "UNMEASURED", "negative_control": "SOURCE_COPY (byte copy of the source window)"}
    clip = CMP.frames_gray(path, None, spec.get("pts_duration"))
    s = CMP.frames_gray(src, None, spec.get("pts_duration"))
    d = CMP.delta_facts(clip, s)
    thr = spec.get("min_change_mae", 2.0)
    if not d.get("measured"):
        return {"assertion": "not_source_copy", "measured": d, "rule": "median per-frame |delta| vs source >= %.1f grey levels" % thr,
                "verdict": "UNMEASURED", "negative_control": "SOURCE_COPY (byte copy of the source window)"}
    ok = d["mae_median"] >= thr
    return {"assertion": "not_source_copy", "measured": {"mae_median": d["mae_median"], "mae_mean": d["mae_mean"],
                                                        "fraction_frames_mae_gt_2": d["fraction_frames_mae_gt_2"],
                                                        "identical_frames": d["identical_frames"], "threshold_mae": thr,
                                                        "frames": d["frames"],
                                                        "note": "diagnostic reconstruction delta, NOT a quality score"},
            "rule": "median per-frame |delta| vs the source window >= %.1f grey levels (props+background actually changed); a copy of the source must FAIL" % thr,
            "verdict": _verdict(ok, d["mae_median"]), "negative_control": "SOURCE_COPY (byte copy of the source window)"}


def _cuts(arr, thresh=40.0):
    if len(arr) < 2:
        return []
    d = CMP.per_frame_absdiff(arr[:-1], arr[1:])
    return [int(i + 1) for i in np.where(d > thresh)[0]]


def a_cut_timeline(path, spec):
    # NOTE (measured during the dry-run): DROP_RANGE is NOT a valid control for this row.
    # A dropped frame range in a CFR container is padded back to 30 fps by the decoder, so
    # the cut offsets survive; the drop surfaces as a PTS gap (pts_contract) and as a run of
    # duplicated frames (not_frozen) instead. The control that moves a cut is SHIFT_3.
    src = spec.get("source_clip")
    dur = spec.get("pts_duration")
    clip = CMP.frames_gray(path, None, dur)
    if not src or len(clip) == 0:
        return {"assertion": "cut_timeline", "measured": None, "rule": "hard cuts land on the same frame offsets as the source",
                "verdict": "UNMEASURED", "negative_control": "SHIFT_3 (content shifted by 3 frames)"}
    s = CMP.frames_gray(src, None, dur)
    oc, sc = _cuts(clip), _cuts(s)
    ok = oc == sc
    v = "PASS" if ok else "FAIL"
    if not sc and not oc:
        v = "UNMEASURED"   # nothing to compare: a cut row cannot pass when no cut is measured
    return {"assertion": "cut_timeline", "measured": {"clip_cut_frame_offsets": oc, "source_cut_frame_offsets": sc,
                                                      "cut_threshold_mae": 40.0,
                                                      "clip_frames": int(len(clip)), "source_frames": int(len(s))},
            "rule": "measured scene-change offsets in the candidate == source offsets (cut positions preserved)",
            "verdict": v, "negative_control": "SHIFT_3 (content shifted by 3 frames)"}


def a_frame_pairing(path, spec):
    src = spec.get("source_clip")
    dur = spec.get("pts_duration")
    nc = "SHIFT_3 (re-extract the source starting 3 frames later)"
    if not src:
        return {"assertion": "frame_pairing", "measured": None, "rule": "candidate frame i is source frame i",
                "verdict": "UNMEASURED", "negative_control": nc}
    clip = CMP.frames_gray(path, None, dur)
    s = CMP.frames_gray(src, None, dur)
    pf = CMP.pairing_facts(clip, s, spec.get("pairing_radius", 5))
    if not pf.get("measured"):
        return {"assertion": "frame_pairing", "measured": pf,
                "rule": "whole-clip |delta|-vs-offset curve has its strict minimum at offset 0",
                "verdict": "UNMEASURED", "negative_control": nc}
    floor = spec.get("pairing_margin_floor", 0.01)
    curve = pf["offset_curve_median_absdiff"]
    c0 = curve.get(0)
    alts = {k: v for k, v in curve.items() if k != 0 and v is not None}
    alt_min = min(alts.values()) if alts else None
    # advantage of offset 0 over the BEST other offset: > 0 means offset 0 wins
    adv = round(alt_min - c0, 4) if (alt_min is not None and c0 is not None) else None
    if adv is not None and adv >= floor:
        verdict, why = "PASS", "offset 0 is the strict minimum of the whole-clip curve (advantage %.4f over the best other offset >= floor %.2f)" % (adv, floor)
    elif adv is not None and adv <= -floor:
        verdict, why = "FAIL", "curve minimised at offset %s (offset 0 is worse by %.4f) -> the candidate is shifted vs the source" % (pf["argmin_offset"], -adv)
    else:
        verdict, why = "UNMEASURED", ("flat offset curve (advantage of offset 0 %s is below the floor %.2f; curve spread over offsets "
                                     "was %s): the candidate is so close to the source that no alignment claim is resolvable at this "
                                     "resolution - never PASS" % (adv, floor, pf["discriminator"]["offset_curve_spread"]))
    return {"assertion": "frame_pairing",
            "measured": {"verdict_reason": why,
                         "advantage_of_offset0": adv,
                         "offset_curve_median_absdiff": pf["offset_curve_median_absdiff"],
                         "offset_curve_spread": pf["discriminator"]["offset_curve_spread"],
                         "source_motion": pf["discriminator"]["source_motion"],
                         "argmin_offset": pf["argmin_offset"], "argmin_value": pf["argmin_value"],
                         "margin_vs_runner_up": pf["margin_vs_runner_up"],
                         "mae_offset0_median": pf["mae_offset0_median"],
                         "mae_offset0_max": pf["mae_offset0_max"],
                         "frames": pf["frames"], "radius": pf["radius"], "margin_floor": floor},
            "rule": "the whole-clip median |delta| curve is strictly minimised at offset 0 with margin >= %.2f; a FLAT curve is UNMEASURED (the test has no discriminating power), never PASS" % floor,
            "verdict": _verdict(True, pf["frames"]) if verdict == "PASS" else verdict, "negative_control": nc}


ASSERTIONS = [a_frame_count_exact, a_pts_contract, a_duration_contract, a_video_codec_contract,
              a_audio_contract, a_non_degenerate, a_not_frozen, a_not_source_copy, a_cut_timeline, a_frame_pairing]
TECHNICAL_ROWS = {"frame_count_exact": 8, "pts_contract": 8, "duration_contract": 7, "video_codec_contract": 8,
                  "audio_contract": 8, "non_degenerate_frames": 7, "not_frozen": 7, "not_source_copy": 5,
                  "cut_timeline": 8, "frame_pairing": 8}



def technical_disposition(rows):
    """The technical verdict, with `fail` and `notmeasured` kept APART (R11 reporting rule).

    * any FAIL                                        -> TECHNICAL_FAIL
    * all PASS / NOT_APPLICABLE                       -> TECHNICAL_PASS
    * no FAIL, at least one row with no discriminating power -> TECHNICAL_NOTMEASURED

    A row whose measurement cannot decide anything is `notmeasured` (harness spelling UNMEASURED
    or UNKNOWN). It is not a failure and must never be reported as one, exactly as it must never
    be reported as a pass.
    """
    verdicts = [r["verdict"] for r in rows]
    counts = {"pass": verdicts.count("PASS"), "fail": verdicts.count("FAIL"),
              "notmeasured": sum(1 for v in verdicts if v in ("UNMEASURED", "UNKNOWN")),
              "not_applicable": verdicts.count("NOT_APPLICABLE"),
              "total": len(verdicts)}
    if counts["fail"]:
        verdict = "TECHNICAL_FAIL"
    elif counts["notmeasured"]:
        verdict = "TECHNICAL_NOTMEASURED"
    elif counts["pass"] or counts["not_applicable"]:
        verdict = "TECHNICAL_PASS"
    else:
        verdict = "TECHNICAL_NOTMEASURED"
    return verdict, counts


def evaluate(path, spec):
    rows = []
    for fn in ASSERTIONS:
        rows.append(fn(path, spec))
    verdict, counts = technical_disposition(rows)
    return {"path": str(path), "assertions": rows,
            "derived": {"technical_verdict": verdict,
                        "technical_counts": counts,
                        "notmeasured_rows": [r["assertion"] for r in rows
                                             if r["verdict"] in ("UNMEASURED", "UNKNOWN")],
                        "visual_verdict": "VISUAL_NOT_REVIEWED"}}


# --------------------------------------------------------------------------- #
# negative controls
# --------------------------------------------------------------------------- #

def build_broken(src, kind, out_dir) -> Path:
    src, out_dir = Path(src), C.ensure(out_dir)
    out = out_dir / ("broken_%s.mp4" % kind.lower())
    if kind == "SOURCE_COPY":
        shutil.copyfile(src, out)
    elif kind == "TAIL_TRUNCATE":
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-frames:v", "90", *VENC,
               "-c:a", "copy", str(out)], label="build TAIL_TRUNCATE")
    elif kind == "DROP_RANGE":
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
               "-vf", "select='not(between(n,30,59))'", "-fps_mode", "passthrough", *VENC,
               "-c:a", "copy", str(out)], label="build DROP_RANGE")
    elif kind == "FPS_25":
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "fps=25", *VENC,
               "-c:a", "copy", str(out)], label="build FPS_25")
    elif kind == "DOWNSCALE":
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale=320:180", *VENC,
               "-c:a", "copy", str(out)], label="build DOWNSCALE")
    elif kind == "NO_AUDIO":
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an", *VENC, str(out)],
              label="build NO_AUDIO")
    elif kind == "BLACK_TAIL":
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
               "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='gte(n,90)'", *VENC,
               "-c:a", "copy", str(out)], label="build BLACK_TAIL")
    elif kind == "SHIFT_3":
        # content shifted 3 frames later; 120 frames kept, so a cut that sat at offset 21
        # must now measure at offset 18 -> the row must FAIL.
        C.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.1", "-i", str(src),
               "-frames:v", "117", *VENC, "-c:a", "copy", str(out)],
              label="build SHIFT_3")
    elif kind == "FREEZE_TAIL":
        still = C.ensure(out_dir) / "broken_freeze_tail_frame89.png"
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "select='eq(n,89)'",
               "-frames:v", "1", str(still)], label="build FREEZE_TAIL still")
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-loop", "1", "-i", str(still),
               "-filter_complex", "[0:v]trim=0:90,setpts=PTS-STARTPTS[a];[1:v]scale=iw:ih,trim=0:30,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]",
               "-map", "[v]", "-r", "30", *VENC, "-an", str(out)], label="build FREEZE_TAIL")
    else:
        raise ValueError("unknown negative control kind: %s" % kind)
    return out


def run_negative_controls(src, out_dir, spec_template, base_overrides=None):
    """Every assertion must FAIL on the input its control breaks. Vacuity is measured.

    A control only proves non-vacuity when the assertion returns FAIL on the broken input.
    UNMEASURED does NOT count as proof. Controls that need a window with real content get
    their own base input via base_overrides (a hard-cut window for cut_timeline, a
    moving-camera window for frame_pairing) - otherwise the control itself would be vacuous.
    """
    base_overrides = base_overrides or {}
    results = []
    for fn in ASSERTIONS:
        name = fn.__name__[2:]
        # discover the declared control from a baseline evaluation (assertion dict carries it)
        base_probe = fn(src, dict(spec_template, source_clip=src))
        kind = base_probe.get("negative_control", "").split(" ")[0]
        base = Path(base_overrides.get(name, src))
        spec = dict(spec_template)
        spec["source_clip"] = base
        if name == "audio_contract":
            spec["audio_optional"] = False      # the control must be able to FAIL the row
        broken = build_broken(base, kind, out_dir)
        res = fn(broken, spec)
        results.append({"assertion": name, "control": kind, "base_input": str(base),
                        "base_input_positives": base_probe["verdict"], "broken_input": str(broken),
                        "assertion_verdict_on_broken_input": res["verdict"],
                        "control_proves_non_vacuity": res["verdict"] == "FAIL",
                        "measured": res["measured"],
                        "rule": res["rule"]})
    return results
