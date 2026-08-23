"""Targeted tests for S05-T03 — canonical rational timebase (app/services/timebase.py).

Covers the required scenarios of ``docs/pm/sessions/S05-T03-canonical-timebase-proxy/
TASK.md`` AC1:

- exact rational conversions: ``frame_to_time`` is an exact ``Fraction``
  (``frame * fps_den / fps_num``), never binary-float drift; frame 0 → time 0;
- explicit rounding modes for ``time_to_frame``: ``floor`` (the frame whose
  interval contains the timestamp), ``round_half_up`` (nearest, half up) and
  ``ceil`` (first frame at/after the timestamp);
- monotonicity: increasing timestamps never map to a smaller frame for every
  rounding mode; increasing frames map to strictly increasing exact times;
- boundary/duration behavior: ``frame_count_for_duration`` is nearest-half-up
  ``round(d * fps)`` with a minimum of 1 for any positive duration and 0 for a
  zero duration; ``duration_for_frames`` is exact ``n / fps``;
- fail-closed stable error codes: ``INVALID_TIMEBASE`` (zero/negative/invalid
  fps rational), ``UNSUPPORTED_CLASSIFICATION`` (unknown classification or
  unknown persisted schema version), ``INVALID_FRAME_INDEX`` (negative frame),
  ``INVALID_DURATION`` (negative/unparseable duration) — never a bare exception;
- CFR/VFR input policy: CFR grids use ``r_frame_rate``; VFR grids use
  ``avg_frame_rate`` (``from_probe``); a VFR probe with a zero/missing
  ``avg_frame_rate`` fails closed;
- durability: ``to_json``/``from_json`` round-trip the exact rationals and the
  classification (schema-versioned); the mapping is a plain value object.

No FFmpeg is needed — these are pure arithmetic tests.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.services.timebase import (
    CLASSIFICATION_CFR,
    CLASSIFICATION_VFR,
    CODE_INVALID_DURATION,
    CODE_INVALID_FRAME_INDEX,
    CODE_INVALID_TIMEBASE,
    CODE_UNSUPPORTED_CLASSIFICATION,
    TIMEBASE_SCHEMA_VERSION,
    CanonicalTimebase,
    TimebaseError,
    exact_seconds,
)


def _cfr(num: int = 30, den: int = 1, **kw) -> CanonicalTimebase:
    return CanonicalTimebase.from_rational(num, den, classification=CLASSIFICATION_CFR, **kw)


# ── Exact conversions ─────────────────────────────────────────────────────────


def test_frame_zero_maps_to_exact_zero() -> None:
    """Boundary: frame 0 → exact time 0 (Fraction, never 0.0)."""
    tb = _cfr()
    t = tb.frame_to_time(0)
    assert t == Fraction(0, 1)
    assert isinstance(t, Fraction)


def test_frame_to_time_is_exact_rational() -> None:
    """frame_to_time returns the exact Fraction frame * fps_den / fps_num."""
    tb = _cfr(30, 1)
    assert tb.frame_to_time(7) == Fraction(7, 30)
    assert tb.frame_to_time(60) == Fraction(2, 1)
    # 23.976 (24000/1001): frame 1001 lands exactly on 1001*1001/24000 s.
    tb_ntsc = _cfr(24000, 1001)
    assert tb_ntsc.frame_to_time(1001) == Fraction(1001 * 1001, 24000)
    assert tb_ntsc.frame_to_time(24000) == Fraction(1001, 1)  # 24000 frames = 1001 s


def test_frame_to_time_strictly_increasing() -> None:
    """Monotonicity: increasing frames map to strictly increasing exact times."""
    for num, den in ((30, 1), (24000, 1001), (30000, 1001), (25, 1)):
        tb = _cfr(num, den)
        prev = tb.frame_to_time(0)
        for frame in range(1, 500):
            t = tb.frame_to_time(frame)
            assert t > prev, f"frame {frame} did not advance at {num}/{den}"
            prev = t


# ── Explicit rounding modes ──────────────────────────────────────────────────


def test_time_to_frame_floor_returns_containing_frame() -> None:
    """floor: the frame whose interval [n/fps, (n+1)/fps) contains the time."""
    tb = _cfr(30, 1)
    assert tb.time_to_frame(Fraction(0, 1), rounding="floor") == 0
    assert tb.time_to_frame(Fraction(1, 30), rounding="floor") == 1  # exact boundary
    assert tb.time_to_frame(Fraction(1, 60), rounding="floor") == 0  # inside frame 0
    assert tb.time_to_frame(Fraction(119, 60), rounding="floor") == 59  # 1.9833s


def test_time_to_frame_round_half_up_nearest() -> None:
    """round_half_up: nearest frame; the half boundary goes up."""
    tb = _cfr(30, 1)
    assert tb.time_to_frame(Fraction(1, 60), rounding="round_half_up") == 1  # 0.5 → up
    assert tb.time_to_frame(Fraction(1, 30), rounding="round_half_up") == 1
    assert tb.time_to_frame(Fraction(3, 60), rounding="round_half_up") == 2  # 1.5 → up
    assert tb.time_to_frame(Fraction(4, 60), rounding="round_half_up") == 2  # 2.0 → 2
    assert tb.nearest_frame(Fraction(1, 60)) == 1  # alias


def test_time_to_frame_ceil_first_frame_at_or_after() -> None:
    """ceil: the first frame at/after the timestamp (safety edges)."""
    tb = _cfr(30, 1)
    assert tb.time_to_frame(Fraction(0, 1), rounding="ceil") == 0
    assert tb.time_to_frame(Fraction(1, 60), rounding="ceil") == 1
    assert tb.time_to_frame(Fraction(1, 30), rounding="ceil") == 1
    # 1/29s is past the 1/30s boundary but still inside frame 1's interval
    # [1/30, 2/30) → the first frame at/after it is frame 2.
    assert tb.time_to_frame(Fraction(1, 29), rounding="ceil") == 2
    assert tb.time_to_frame(Fraction(61, 60), rounding="ceil") == 31


def test_time_to_frame_monotonic_non_decreasing_all_modes() -> None:
    """Monotonicity: increasing timestamps never map to a smaller frame."""
    tb = _cfr(30, 1)
    for rounding in ("floor", "round_half_up", "ceil"):
        prev = -1
        for i in range(0, 121):  # 0..2s in 1/60 steps
            t = Fraction(i, 60)
            frame = tb.time_to_frame(t, rounding=rounding)  # type: ignore[arg-type]
            assert frame >= prev, f"{rounding} decreased at t={t}"
            prev = frame


def test_time_to_frame_float_input_uses_exact_decimal() -> None:
    """Float inputs are converted exactly via their decimal repr (never float math)."""
    tb = _cfr(30, 1)
    # 0.1 is exactly 1/10 in decimal; the conversion path stays rational.
    assert tb.time_to_frame(0.1, rounding="floor") == tb.time_to_frame(
        Fraction(1, 10), rounding="floor"
    )
    assert tb.time_to_frame(0.5, rounding="round_half_up") == 15


# ── Fail-closed stable codes ─────────────────────────────────────────────────


def test_invalid_fps_components_fail_closed() -> None:
    """Zero/negative/non-integer fps rationals → INVALID_TIMEBASE, never bare."""
    for num, den in ((0, 1), (30, 0), (-30, 1), (30, -1), (0, 0)):
        with pytest.raises(TimebaseError) as ei:
            CanonicalTimebase.from_rational(num, den)
        assert ei.value.code == CODE_INVALID_TIMEBASE
        assert ei.value.action()  # Vietnamese suggested action is present


def test_non_integer_fps_components_fail_closed() -> None:
    """Non-integer rational components fail closed (int() coercion fails)."""
    for num, den in (("abc", 1), (30, "x"), (None, 1)):
        with pytest.raises(TimebaseError) as ei:
            CanonicalTimebase.from_rational(num, den)  # type: ignore[arg-type]
        assert ei.value.code == CODE_INVALID_TIMEBASE


def test_unknown_classification_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        CanonicalTimebase.from_rational(30, 1, classification="VARIABLE")
    assert ei.value.code == CODE_UNSUPPORTED_CLASSIFICATION


def test_negative_frame_fails_closed() -> None:
    tb = _cfr()
    with pytest.raises(TimebaseError) as ei:
        tb.frame_to_time(-1)
    assert ei.value.code == CODE_INVALID_FRAME_INDEX
    with pytest.raises(TimebaseError) as ei:
        tb.duration_for_frames(-5)
    assert ei.value.code == CODE_INVALID_FRAME_INDEX


def test_negative_duration_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        CanonicalTimebase.from_rational(30, 1, duration_seconds="-1.5")
    assert ei.value.code == CODE_INVALID_DURATION
    tb = _cfr()
    with pytest.raises(TimebaseError) as ei:
        tb.frame_count_for_duration(Fraction(-1, 30))
    assert ei.value.code == CODE_INVALID_DURATION


def test_garbage_duration_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        exact_seconds("not-a-number")
    assert ei.value.code == CODE_INVALID_DURATION


def test_negative_nb_frames_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        CanonicalTimebase.from_rational(30, 1, nb_frames=-3)
    assert ei.value.code == CODE_INVALID_FRAME_INDEX


# ── Duration / frame-count behavior ──────────────────────────────────────────


def test_frame_count_for_duration_round_half_up_min_one() -> None:
    """Nearest-half-up round(d × fps); ≥ 1 for any positive duration; 0 for 0."""
    tb = _cfr(10, 1)
    assert tb.frame_count_for_duration(Fraction(1, 10)) == 1
    assert tb.frame_count_for_duration(Fraction(15, 100)) == 2  # 1.5 → up
    assert tb.frame_count_for_duration(Fraction(25, 100)) == 3  # 2.5 → up
    assert tb.frame_count_for_duration(Fraction(1, 100)) == 1  # 0.1 → min 1
    assert tb.frame_count_for_duration(Fraction(1, 20)) == 1  # 0.5 → 1
    assert tb.frame_count_for_duration(Fraction(0, 1)) == 0
    tb30 = _cfr(30, 1)
    assert tb30.frame_count_for_duration(Fraction(1, 30)) == 1
    assert tb30.frame_count_for_duration(Fraction(2, 1)) == 60


def test_duration_for_frames_exact() -> None:
    tb = _cfr(30, 1)
    assert tb.duration_for_frames(30) == Fraction(1, 1)
    assert tb.duration_for_frames(1) == Fraction(1, 30)
    assert tb.duration_for_frames(0) == Fraction(0, 1)
    tb_ntsc = _cfr(24000, 1001)
    assert tb_ntsc.duration_for_frames(24000) == Fraction(1001, 1)


def test_frame_count_derivation_from_duration() -> None:
    """Without nb_frames, the count derives via the documented rounding rule."""
    tb = CanonicalTimebase.from_rational(30, 1, duration_seconds="2.0")
    assert tb.nb_frames == 60
    tb_tiny = CanonicalTimebase.from_rational(30, 1, duration_seconds="0.001")
    assert tb_tiny.nb_frames == 1  # min 1 for any positive duration
    # A zero duration has no frames to derive — the count stays unknown (None).
    tb_zero = CanonicalTimebase.from_rational(30, 1, duration_seconds="0")
    assert tb_zero.nb_frames is None


def test_clamp_frame_playhead_semantics() -> None:
    tb = CanonicalTimebase.from_rational(30, 1, nb_frames=30)
    assert tb.clamp_frame(-5) == 0
    assert tb.clamp_frame(0) == 0
    assert tb.clamp_frame(29) == 29
    assert tb.clamp_frame(30) == 29
    unbounded = _cfr(30, 1)
    assert unbounded.clamp_frame(-1) == 0
    assert unbounded.clamp_frame(100) == 100


# ── CFR/VFR input policy ─────────────────────────────────────────────────────


def _probe(
    classification: str,
    *,
    r_num: int = 30,
    r_den: int = 1,
    avg_num: int = 30,
    avg_den: int = 1,
    duration: str = "2.0",
    nb_frames: int = 60,
) -> dict:
    return {
        "container": {"duration_seconds": duration},
        "video_stream": {
            "fps_classification": classification,
            "r_frame_rate": {"num": r_num, "den": r_den},
            "avg_frame_rate": {"num": avg_num, "den": avg_den},
            "nb_frames": nb_frames,
        },
    }


def test_from_probe_cfr_uses_r_frame_rate() -> None:
    """CFR canonical grid = r_frame_rate rational (avg ignored even if different)."""
    tb = CanonicalTimebase.from_probe(
        _probe(CLASSIFICATION_CFR, r_num=30, r_den=1, avg_num=30000, avg_den=1001)
    )
    assert (tb.fps_num, tb.fps_den) == (30, 1)
    assert tb.classification == CLASSIFICATION_CFR
    assert not tb.is_vfr


def test_from_probe_vfr_uses_avg_frame_rate() -> None:
    """VFR canonical grid = avg_frame_rate rational (the deterministic grid)."""
    tb = CanonicalTimebase.from_probe(
        _probe(CLASSIFICATION_VFR, r_num=30, r_den=1, avg_num=30000, avg_den=1001)
    )
    assert (tb.fps_num, tb.fps_den) == (30000, 1001)
    assert tb.classification == CLASSIFICATION_VFR
    assert tb.is_vfr
    # Exactness: 1001 frames of 30000/1001 land exactly on 1001*1001/30000 s.
    assert tb.frame_to_time(1001) == Fraction(1001 * 1001, 30000)


def test_from_probe_vfr_zero_avg_fails_closed() -> None:
    """A VFR probe whose avg_frame_rate is zero/missing cannot define a grid."""
    for avg in ({"num": 0, "den": 0}, {}, {"num": 0, "den": 1}):
        probe = {
            "container": {"duration_seconds": "2.0"},
            "video_stream": {
                "fps_classification": CLASSIFICATION_VFR,
                "r_frame_rate": {"num": 30, "den": 1},
                "avg_frame_rate": avg,
            },
        }
        with pytest.raises(TimebaseError) as ei:
            CanonicalTimebase.from_probe(probe)
        assert ei.value.code == CODE_INVALID_TIMEBASE


def test_from_probe_unknown_classification_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        CanonicalTimebase.from_probe(_probe("UNKNOWN"))
    assert ei.value.code == CODE_UNSUPPORTED_CLASSIFICATION


def test_from_probe_cfr_zero_r_rate_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        CanonicalTimebase.from_probe(_probe(CLASSIFICATION_CFR, r_num=0, r_den=0))
    assert ei.value.code == CODE_INVALID_TIMEBASE


# ── Durability (checkpoint JSON) ─────────────────────────────────────────────


def test_to_json_from_json_roundtrip_exact() -> None:
    """The durable payload preserves exact rationals and classification."""
    tb = CanonicalTimebase.from_probe(
        _probe(CLASSIFICATION_VFR, avg_num=30000, avg_den=1001, duration="41.708333")
    )
    payload = tb.to_json()
    assert payload["schema_version"] == TIMEBASE_SCHEMA_VERSION
    assert payload["classification"] == CLASSIFICATION_VFR
    rebuilt = CanonicalTimebase.from_json(payload)
    assert rebuilt.fps_num == 30000
    assert rebuilt.fps_den == 1001
    assert rebuilt.classification == CLASSIFICATION_VFR
    assert rebuilt.duration_seconds == Fraction("41.708333")
    assert rebuilt.frame_to_time(1001) == tb.frame_to_time(1001)
    # Round-trip JSON-serializable: the payload contains only JSON types.
    import json

    json.dumps(payload)


def test_from_json_unknown_schema_version_fails_closed() -> None:
    with pytest.raises(TimebaseError) as ei:
        CanonicalTimebase.from_json({"schema_version": 999, "fps_num": 30, "fps_den": 1})
    assert ei.value.code == CODE_UNSUPPORTED_CLASSIFICATION


def test_from_json_missing_components_fails_closed() -> None:
    with pytest.raises((TimebaseError, KeyError)):
        CanonicalTimebase.from_json({"schema_version": 1})


# ── exact_seconds helper ─────────────────────────────────────────────────────


def test_exact_seconds_parses_decimal_exactly() -> None:
    assert exact_seconds("12.5") == Fraction(25, 2)
    assert exact_seconds("0.1") == Fraction(1, 10)
    assert exact_seconds(12) == Fraction(12, 1)
    assert exact_seconds(Fraction(1, 3)) == Fraction(1, 3)
    # A binary float enters the path through its shortest decimal repr, so the
    # value stays an exact decimal rational — never binary-float drift.
    assert exact_seconds(0.1) == Fraction(1, 10)
    assert exact_seconds(0.5) == Fraction(1, 2)


def test_no_float_arithmetic_on_conversion_path() -> None:
    """The conversion path never multiplies/divides floats."""
    tb = _cfr(24000, 1001)
    assert tb.frame_to_time(0) == Fraction(0, 1)
    for frame in (1, 1001):
        t = tb.frame_to_time(frame)
        assert isinstance(t, Fraction)
        assert t.denominator == 24000  # exact rational denominator preserved
