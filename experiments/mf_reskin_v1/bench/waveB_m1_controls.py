"""MF-V1-BENCH wave B (round 2) - NEGATIVE CONTROLS for the M1 evaluation.

A green row proves nothing unless the same row can be made to FAIL. Every assertion is run
against a deliberately broken input built on CPU with ffmpeg; the control only counts as
non-vacuous when the assertion returns FAIL on that input (UNMEASURED is not proof).

Extra targeted control (not in assertions.build_broken): HEIGHT_368 re-encodes the candidate
padded to 640x368 - exactly the shape of the old geometry defect - so the geometry row is shown
to fire on the regression it is meant to catch.

For the two rows that legitimately LACK discriminating power on this window (cut_timeline,
frame_pairing) the positive controls are recorded too: a window of the same film that HAS a hard
cut, and a known +5-frame shift built from the film itself.

Writes <NEW>/BENCH/raw/m1_negative_controls.json
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")
BENCH_SRC = WT / "experiments" / "mf_reskin_v1" / "bench"
sys.path.insert(0, str(BENCH_SRC))
import common as C          # noqa: E402
import numpy as np          # noqa: E402
import probe as P           # noqa: E402
import compare as CMP       # noqa: E402
import assertions as A      # noqa: E402

NEW = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
           "mf-core-tool-delivery-20260923/20260923T1535Z")
CORR = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
            "mf-reskin-correction-20260922/20260922T0955Z")
M1 = (NEW / "manager" / "frozen" / "M1_book4s_animate2" / "M1_book4s_animate2" / "files" / "waveB_m1")
CAND = M1 / "clip" / "final_book4s_m1_decoded119_640x360.mp4"
SRC_FROZEN = M1 / "review" / "source_window_120f.mp4"
SRC_ALT = (CORR / "manager" / "frozen" / "BOOK_animate2_waveA_inputs" / "files" / "src_windows"
           / "BOOK_src.mp4")
RAW = NEW / "BENCH" / "raw"
WORK = NEW / "BENCH" / "work" / "m1_scratch"
BROKEN = WORK / "broken_m1"
C.set_ledger_path(RAW / "cmd_transcript.jsonl")

SPEC = {"expected_frames": 120, "pts_duration": 4.0,
        "video": {"codec": "h264", "width": 640, "height": 360, "pix_fmt": "yuv420p"},
        "audio": {"codec": "aac", "sample_rate": 44100, "channels": 2},
        "audio_optional": True, "min_change_mae": 2.0, "max_identical_run": 2,
        "pairing_radius": 5, "pairing_min_fraction": 0.98, "pairing_margin_floor": 0.01,
        "window_start_frame": 0, "window_frame_count": 120}
CUT660 = C.RUNTIME / "src_windows" / "CUT_660_src.mp4"
TURN795 = C.RUNTIME / "src_windows" / "TURN_795_src.mp4"

BASE = SRC_ALT if SRC_ALT.exists() else SRC_FROZEN
spec = dict(SPEC, source_clip=BASE)
overrides = {"cut_timeline": CUT660, "frame_pairing": TURN795}
C.ensure(BROKEN)

print("[ctl] base=%s" % BASE)
res = A.run_negative_controls(BASE, BROKEN, spec, overrides)

# --- extra targeted control: the old geometry defect (640x368) must be caught -------------
VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
h368 = BROKEN / "broken_height_368.mp4"
C.run(["ffmpeg", "-y", "-v", "error", "-i", str(CAND), "-vf", "pad=640:368:0:4:color=black",
       *VENC, "-c:a", "copy", str(h368)], label="build HEIGHT_368")
h368_spec = dict(SPEC, source_clip=BASE)
h368_probe = A.a_video_codec_contract(CAND, h368_spec)
h368_res = A.a_video_codec_contract(h368, h368_spec)
extra = {"assertion": "video_codec_contract", "control": "HEIGHT_368",
         "why": "640x368 is the exact shape of the old geometry defect (the +8-row pad)",
         "base_input": str(CAND), "base_input_positives": h368_probe["verdict"],
         "broken_input": str(h368), "broken_facts": P.container_facts(h368)["video"],
         "assertion_verdict_on_broken_input": h368_res["verdict"],
         "control_proves_non_vacuity": h368_res["verdict"] == "FAIL",
         "measured": h368_res["measured"], "rule": h368_res["rule"]}

# --- positive controls for the two rows without discriminating power ----------------------
def gray(path, n=120):
    return CMP.frames_gray(path, None, 4.0, n, 640, 360)


def cut_offsets(arr):
    if len(arr) < 2:
        return []
    d = CMP.per_frame_absdiff(arr[:-1], arr[1:])
    return [int(i + 1) for i in np.where(d > 40.0)[0]]


film = C.REF_FILM
cut_ctl = gray(CUT660)


def gsel(path, start, count):
    argv = ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
            "select='between(n\\,%d\\,%d)',scale=640:360,format=gray" % (start, start + count - 1),
            "-vsync", "0", "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    buf = C.run_bytes(argv, label="gray window %d..%d" % (start, start + count - 1))
    cnt = len(buf) // (640 * 360)
    return np.frombuffer(buf[:cnt * 640 * 360], dtype=np.uint8).reshape(cnt, 360, 640)


film_win = gsel(film, 1650, 120)
film_p5 = gsel(film, 1655, 120)
srcw = gray(BASE)


def pairing(a, b, radius=15):
    n = min(len(a), len(b))
    curve = {}
    for off in range(-radius, radius + 1):
        vals = [float(np.abs(a[i].astype(np.int16) - b[i + off].astype(np.int16)).mean())
                for i in range(n) if 0 <= i + off < len(b)]
        curve[off] = round(float(np.median(vals)), 6) if vals else None
    u = {k: v for k, v in curve.items() if v is not None}
    best = min(u, key=lambda k: u[k])
    others = [v for k, v in u.items() if k != best]
    return {"argmin": best, "advantage_of_offset0": round(min(others) - u[0], 6),
            "spread": round(max(u.values()) - min(u.values()), 6), "curve": curve}


pos = {"cut_timeline": {
    "control": "a window of the same film that DOES contain a hard cut",
    "base_input": str(CUT660), "cut_offsets_measured": cut_offsets(cut_ctl),
    "fires_when": "offsets non-empty: the detector reports a real cut when one exists, so an empty "
                  "result on the BOOK window means 'no cut here', not 'detector broken'",
    "harness_control_on_this_base": [r for r in res if r["assertion"] == "cut_timeline"]},
    "frame_pairing": {
        "control": "known +5-frame shift built from the film (film [1655,1775) vs film [1650,1770))",
        "known_0_shift": pairing(srcw, film_win),
        "known_5_shift": pairing(film_p5, film_win),
        "fires_when": "the +5 pair resolves argmin=+5 (and the harness verdict on it must not be PASS), "
                      "so the curve DOES move when the content is really shifted"}}

out = {"artifact": "m1_negative_controls.json", "task_id": "MF-V1-BENCH",
       "wave": "B (round 2) - negative controls for the M1 evaluation",
       "run_id": C.RUN_ID, "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
       "kind": "control_non_vacuity_evidence",
       "rule": "a control proves non-vacuity only when the assertion returns FAIL on the broken input; "
               "UNMEASURED does not count",
       "default_base_input": str(BASE), "candidate_under_evaluation": str(CAND),
       "base_overrides": {k: str(v) for k, v in overrides.items()},
       "per_control_notes": {
           "not_source_copy": "its base_input_positives reads FAIL by construction: the default base input IS "
                              "the source, so a comparison of the base with itself is 0-lane-vs-itself and this "
                              "assertion is meant to fail there. The row's real positive is the candidate under "
                              "evaluation (mae_median 45.2095, PASS); the control proves the assertion fires on a "
                              "byte copy of the source (mae_median 0.0, FAIL).",
           "cut_timeline": "base_input_positives reads UNMEASURED because the default base window has no hard cut; "
                           "the SHIFT_3 control is built on the CUT_660 window (see base_overrides), which does.",
           "frame_pairing": "base_input_positives reads UNMEASURED for the same reason; the SHIFT_3 control is "
                            "built on the TURN_795 window (moving camera), which has the power to resolve a shift."},
       "harness_controls": res,
       "harness_controls_non_vacuous": sum(1 for r in res if r["control_proves_non_vacuity"]),
       "harness_controls_total": len(res),
       "harness_controls_that_did_not_fire": [r["assertion"] for r in res
                                              if not r["control_proves_non_vacuity"]],
       "extra_targeted_controls": [extra],
       "positive_controls_for_unmeasured_rows": pos,
       "all_controls_fired": (all(r["control_proves_non_vacuity"] for r in res)
                              and extra["control_proves_non_vacuity"])}
C.write_json(RAW / "m1_negative_controls.json", out)
C.flush_ledger()

for r in res:
    print("[ctl] %-24s control=%-14s on_broken=%-11s fired=%s"
          % (r["assertion"], r["control"], r["assertion_verdict_on_broken_input"],
             r["control_proves_non_vacuity"]))
print("[ctl] extra HEIGHT_368 -> %s (fired=%s)"
      % (extra["assertion_verdict_on_broken_input"], extra["control_proves_non_vacuity"]))
print("[ctl] cut positive control offsets=%s | pairing 0-shift argmin=%s, +5-shift argmin=%s"
      % (pos["cut_timeline"]["cut_offsets_measured"], pos["frame_pairing"]["known_0_shift"]["argmin"],
         pos["frame_pairing"]["known_5_shift"]["argmin"]))
print("[ctl] ALL_CONTROLS_FIRED=%s (%d/%d + 1 targeted)"
      % (out["all_controls_fired"], out["harness_controls_non_vacuous"], out["harness_controls_total"]))
print("[ctl] wrote", RAW / "m1_negative_controls.json", "commands=%d" % C.command_count())
