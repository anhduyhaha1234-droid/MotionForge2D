"""MF-V1-BENCH - regression tests for harness invariants (CPU only, hermetic).

No network, no GPU, no model, no write outside `tmp_path`. Each test names the measured
defect or gate rule it locks down, and each gate-row test also asserts the opposite
verdict on the corrected input so it cannot pass vacuously.

Run:  python -m pytest experiments/mf_reskin_v1/bench -q --cache-clear --basetemp=C:/pt_bench
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assertions as A          # noqa: E402
import common as C              # noqa: E402
import compare as CMP           # noqa: E402
import wave2_eval_book as W     # noqa: E402
import wave2_review_bundle as RB  # noqa: E402

SPEC = {"expected_frames": 12, "pts_duration": 0.4, "min_change_mae": 2.0,
        "max_identical_run": 2, "pairing_radius": 5, "pairing_margin_floor": 0.01,
        "video": {"codec": "h264", "width": 64, "height": 36, "pix_fmt": "yuv420p"},
        "audio_optional": True, "window_start_frame": 0, "window_frame_count": 12}


def make_clip(path, w=64, h=36, n=12, color="gray"):
    """A tiny deterministic CFR h264 clip, encoded with ffmpeg (the harness's own tool)."""
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=%s:s=%dx%d:r=30:d=%.3f" % (color, w, h, n / 30.0),
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


# --------------------------------------------------------------------------- #
# 1. command transcript must never destroy a previous run's evidence
# --------------------------------------------------------------------------- #

def test_flush_ledger_appends_and_never_truncates(tmp_path):
    """Defect locked: flush_ledger opened the transcript with "w" and a later run
    replaced an earlier run's 305 rows with 20. Appends only."""
    t = tmp_path / "cmd_transcript.jsonl"
    C.LEDGER.clear()
    C.LEDGER.append({"label": "run1-a", "argv": ["ffmpeg"], "exit_code": 0})
    C.flush_ledger(t)
    first = t.read_text(encoding="utf-8").splitlines()
    C.LEDGER.clear()
    C.LEDGER.append({"label": "run2-a", "argv": ["ffprobe"], "exit_code": 0})
    C.flush_ledger(t)
    rows = [json.loads(x) for x in t.read_text(encoding="utf-8").splitlines()]
    labels = [r.get("label") for r in rows]
    assert len(first) == 2 and len(rows) == 4, "each run adds its header plus its rows"
    assert "run1-a" in labels and "run2-a" in labels, "run 1 survived run 2"
    assert labels.count("run1-a") == 1 and labels.count("run2-a") == 1
    C.LEDGER.clear()


def test_flush_ledger_header_marks_the_run(tmp_path):
    t = tmp_path / "cmd_transcript.jsonl"
    C.LEDGER.clear()
    C.LEDGER.append({"label": "x", "argv": ["ffmpeg"], "exit_code": 0})
    C.flush_ledger(t)
    head = json.loads(t.read_text(encoding="utf-8").splitlines()[0])
    assert head["run"] == "start" and head["commands"] == 1 and "when" in head and "cwd" in head
    C.LEDGER.clear()


# --------------------------------------------------------------------------- #
# 2. ffmpeg exits 0 having written nothing -> the artifact guard must fire
# --------------------------------------------------------------------------- #

def test_require_nonempty_rejects_missing_and_zero_byte(tmp_path):
    """Defect locked: 4 grip strips were 0 bytes/absent after an exit-0 ffmpeg call."""
    missing = tmp_path / "absent.png"
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    full = tmp_path / "full.png"
    full.write_bytes(b"x" * 32)
    with pytest.raises(SystemExit):
        RB.require_nonempty(missing, "absent")
    with pytest.raises(SystemExit):
        RB.require_nonempty(empty, "zero-byte")
    assert RB.require_nonempty(full, "ok") == 32, "a real artifact is returned, not rejected"


# --------------------------------------------------------------------------- #
# 3. the geometry row: 8 extra rows must FAIL the codec/size contract
# --------------------------------------------------------------------------- #

def test_codec_contract_fails_on_geometry_mismatch_but_passes_when_declared(tmp_path):
    """Locks the wave-2 geometry FAIL: candidate 64x36 vs a 64x32 spec is a FAIL, and the
    same file is a PASS once the spec declares 36 - so the row is not vacuous."""
    clip = make_clip(tmp_path / "c.mp4", w=64, h=36)
    bad = dict(SPEC, video={"codec": "h264", "width": 64, "height": 32, "pix_fmt": "yuv420p"})
    assert A.a_video_codec_contract(clip, bad)["verdict"] == "FAIL"
    good = dict(SPEC, video={"codec": "h264", "width": 64, "height": 36, "pix_fmt": "yuv420p"})
    r = A.a_video_codec_contract(clip, good)
    assert r["verdict"] == "PASS" and r["measured"]["got"]["height"] == 36


def test_geometry_helper_reports_the_measured_delta():
    """Locks the numbers quoted in EVAL_BOOK_R4.md: +8 rows, ratio 1.022222, +2.2222 %."""
    g = W.geometry({"width": 640, "height": 368}, {"width": 640, "height": 360})
    assert (g["height_delta_px"], g["vertical_ratio_candidate_over_source"],
            g["pct_vertical_stretch_if_scaled_to_match"]) == (8, 1.022222, 2.2222)
    same = W.geometry({"width": 640, "height": 360}, {"width": 640, "height": 360})
    assert same["height_delta_px"] == 0, "no false mismatch when the geometry agrees"


# --------------------------------------------------------------------------- #
# 4. a non-discriminating measurement is UNMEASURED, never PASS (GATE_VOCAB rule 4)
# --------------------------------------------------------------------------- #

def test_flat_offset_curve_is_unmeasured_not_pass(tmp_path):
    """Two identical clips make the whole-clip offset curve flat: the pairing row must be
    UNMEASURED. This is the BOOK trap - a candidate near its source yields no alignment
    claim at all, and 'looks green' must not become PASS."""
    a = make_clip(tmp_path / "a.mp4")
    b = make_clip(tmp_path / "b.mp4")
    spec = dict(SPEC, source_clip=b)
    r = A.a_frame_pairing(a, spec)
    assert r["verdict"] == "UNMEASURED", r["measured"]
    assert "advantage" in r["measured"]["verdict_reason"], "the reason must name the advantage"
    assert "spread" in r["measured"]["verdict_reason"], "and the curve spread as a separate fact"
    assert r["measured"]["advantage_of_offset0"] == 0.0


def test_frame_pairing_message_is_self_consistent(tmp_path):
    """Defect locked: the UNMEASURED reason compared the curve SPREAD against the
    advantage floor and printed 'spread 0.0202 < floor 0.01'. Two identical clips give
    spread 0.0, so the old wording printed the self-contradicting 'spread 0.0 < floor 0.01'."""
    a = make_clip(tmp_path / "a.mp4")
    b = make_clip(tmp_path / "b.mp4")
    m = A.a_frame_pairing(a, dict(SPEC, source_clip=b))["measured"]
    why = m["verdict_reason"]
    assert not re.search(r"spread\s+[\d.]+\s*<\s*floor", why), "spread must not be compared to the advantage floor"
    assert "advantage of offset 0" in why and "below the floor" in why and "curve spread" in why
    assert str(m["margin_floor"]) in why, "the floor it compares against must appear"
    assert str(m["offset_curve_spread"]) in why, "the spread must still be recorded, as its own fact"


# --------------------------------------------------------------------------- #
# 5. a copy of the source must FAIL not_source_copy (CHECKLIST row 5 rule)
# --------------------------------------------------------------------------- #

def test_source_copy_fails_not_source_copy(tmp_path):
    src = make_clip(tmp_path / "src.mp4")
    same = make_clip(tmp_path / "same.mp4")
    r = A.a_not_source_copy(same, dict(SPEC, source_clip=src))
    assert r["verdict"] == "FAIL" and r["measured"]["mae_median"] == 0.0
    changed = make_clip(tmp_path / "changed.mp4", color="white")
    assert A.a_not_source_copy(changed, dict(SPEC, source_clip=src))["verdict"] == "PASS", \
        "the row must pass on content that really differs"


def test_delta_facts_is_zero_only_for_identical_input():
    a = np.zeros((3, 8, 8), dtype=np.uint8)
    d = CMP.delta_facts(a, a.copy())
    assert d["measured"] and d["mae_median"] == 0.0 and d["identical_frames"] == 3
    d2 = CMP.delta_facts(np.full((3, 8, 8), 10, dtype=np.uint8), a)
    assert d2["mae_median"] == 10.0 and d2["identical_frames"] == 0
