"""Canonical timeline mapping for MotionForge 2D (S05-T03).

One deterministic mapping converts between frame index, canonical timestamp
and duration for both accepted CFR and accepted VFR inputs using **exact
rational arithmetic** (``fractions.Fraction``) — never binary-float drift
(PRD §9 Step 1 acceptance: *"Video CFR/VFR đều map về canonical timebase
chính xác"*; MASTER_PLAN_V1 WS-03 "Canonical timebase/CFR-VFR policy";
VIDEO_PREFLIGHT_CONTRACT §3.1/§6.4).

Contract (also stated in ``docs/architecture/
CANONICAL_TIMEBASE_PROXY_CONTRACT.md``):

- **Canonical grid** — CFR inputs use the container's ``r_frame_rate``
  rational; VFR inputs use ``avg_frame_rate`` rational (the deterministic
  canonical grid the editing proxy is resampled onto).  Both rationals must
  be positive; a zero/negative/invalid rational fails closed with
  ``INVALID_TIMEBASE`` and a Vietnamese suggested action — never a bare
  exception.
- **Exact conversions** — :meth:`CanonicalTimebase.frame_to_time` returns an
  exact ``Fraction``; :meth:`CanonicalTimebase.time_to_frame` applies an
  **explicit rounding mode** (``floor`` = the frame whose interval contains
  the timestamp, ``round_half_up`` = nearest frame for extraction,
  ``ceil`` = the first frame at/after the timestamp).
- **Monotonicity** — increasing timestamps never map to a smaller frame
  (floor/round are non-decreasing); increasing frames map to strictly
  increasing exact times.
- **Boundary/duration** — frame 0 → time 0; ``frame_count_for_duration`` is
  nearest-half-up ``round(d * fps)`` with a minimum of 1 for any positive
  duration; ``duration_for_frames`` is exact ``n / fps``; negative frames or
  negative durations fail closed (``INVALID_FRAME_INDEX`` /
  ``INVALID_DURATION``).
- **Durability** — a mapping is a plain value object; when persisted it is
  serialized as a schema-versioned JSON payload (``to_json`` /
  ``from_json``) that carries the exact rationals and classification.  The
  ``GENERATE_PROXY`` job stores this payload in its checkpoint so a restarted
  job resumes the exact same canonical grid.

No float arithmetic is used anywhere on the conversion path; the only float
inputs (ffprobe's ``duration_seconds``) are converted to exact ``Fraction``
via their decimal string representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

__all__ = [
    "CLASSIFICATION_CFR",
    "CLASSIFICATION_VFR",
    "CODE_INVALID_DURATION",
    "CODE_INVALID_FRAME_INDEX",
    "CODE_INVALID_TIMEBASE",
    "CODE_UNSUPPORTED_CLASSIFICATION",
    "TIMEBASE_SCHEMA_VERSION",
    "CanonicalTimebase",
    "RoundingMode",
    "TimebaseError",
    "VIETNAMESE_ACTIONS",
    "exact_seconds",
]

#: Stable classification values (VIDEO_PREFLIGHT_CONTRACT §3.1).
CLASSIFICATION_CFR = "CFR"
CLASSIFICATION_VFR = "VFR"

#: Schema version of the persisted canonical-timebase payload.
TIMEBASE_SCHEMA_VERSION = 1

#: Stable error codes (contract "Stable error taxonomy" section).
CODE_INVALID_TIMEBASE = "INVALID_TIMEBASE"
CODE_UNSUPPORTED_CLASSIFICATION = "UNSUPPORTED_CLASSIFICATION"
CODE_INVALID_FRAME_INDEX = "INVALID_FRAME_INDEX"
CODE_INVALID_DURATION = "INVALID_DURATION"

#: Vietnamese suggested actions (PRD §9 Step 5 acceptance / FR-08) for every
#: stable code this module raises.
VIETNAMESE_ACTIONS: dict[str, str] = {
    CODE_INVALID_TIMEBASE: (
        "Thông số tốc độ khung hình không hợp lệ (tử số và mẫu số phải là số "
        "nguyên dương). Hãy kiểm tra lại metadata của tệp nguồn."
    ),
    CODE_UNSUPPORTED_CLASSIFICATION: (
        "Phân loại tốc độ khung hình không được hỗ trợ (chỉ chấp nhận CFR hoặc "
        "VFR). Hãy kiểm tra lại kết quả phân tích tệp nguồn."
    ),
    CODE_INVALID_FRAME_INDEX: (
        "Chỉ số khung hình không hợp lệ (phải là số nguyên không âm). Hãy kiểm "
        "tra lại giá trị frame được yêu cầu."
    ),
    CODE_INVALID_DURATION: (
        "Thời lượng không hợp lệ (phải là số không âm). Hãy kiểm tra lại metadata "
        "của tệp nguồn."
    ),
}

#: Explicit rounding modes for :meth:`CanonicalTimebase.time_to_frame`.
RoundingMode = Literal["floor", "round_half_up", "ceil"]


class TimebaseError(ValueError):
    """A stable, actionable canonical-timebase failure.

    ``code`` is the machine-readable stable error code; ``action`` is the
    Vietnamese suggested action; ``location``/``details`` carry structured
    context for the error envelope (DURABLE_JOB_CONTRACT §10.1).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.location = location
        self.details = details or {}

    def action(self) -> str:
        """The Vietnamese suggested action for this error's code."""
        return VIETNAMESE_ACTIONS.get(
            self.code, "Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống."
        )


def exact_seconds(value: Any) -> Fraction:
    """Convert an ffprobe-style decimal duration to an exact ``Fraction``.

    The decimal string is parsed exactly (``Fraction("12.5") == 25/2``) so a
    binary float never enters the conversion path.  Missing/garbage values
    fail closed with ``INVALID_DURATION``.
    """
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Fraction(value, 1)
    if isinstance(value, float):
        value = repr(value)
    raw = str(value or "").strip()
    try:
        return Fraction(raw)
    except (ValueError, ZeroDivisionError) as exc:
        raise TimebaseError(
            CODE_INVALID_DURATION,
            f"cannot parse duration as an exact rational: {value!r}",
            location="duration",
            details={"raw": raw},
        ) from exc


def _rational(num: Any, den: Any) -> Fraction:
    """Build the fps rational, failing closed on zero/negative components."""
    try:
        n = int(num)
        d = int(den)
    except (TypeError, ValueError) as exc:
        raise TimebaseError(
            CODE_INVALID_TIMEBASE,
            f"frame-rate rational components must be integers: {num!r}/{den!r}",
            location="fps rational",
            details={"num": num, "den": den},
        ) from exc
    if n <= 0 or d <= 0:
        raise TimebaseError(
            CODE_INVALID_TIMEBASE,
            f"frame-rate rational must be positive: {n}/{d}",
            location="fps rational",
            details={"num": n, "den": d},
        )
    return Fraction(n, d)


@dataclass(frozen=True)
class CanonicalTimebase:
    """One deterministic canonical timeline mapping.

    Attributes:
        fps_num: Numerator of the canonical frame rate (exact rational).
        fps_den: Denominator of the canonical frame rate.
        classification: ``CFR`` (grid = ``r_frame_rate``) or ``VFR``
            (grid = ``avg_frame_rate``).
        duration_seconds: Optional exact duration (``Fraction`` or decimal).
        nb_frames: Optional exact frame count; when absent/zero it is derived
            from duration × fps with the documented rounding rule.
    """

    fps_num: int
    fps_den: int
    classification: str = CLASSIFICATION_CFR
    duration_seconds: Fraction | str | None = None
    nb_frames: int | None = None

    def __post_init__(self) -> None:
        # Normalize duration to an exact Fraction (may raise INVALID_DURATION).
        duration: Fraction | None = None
        if self.duration_seconds is not None:
            duration = exact_seconds(self.duration_seconds)
            if duration < 0:
                raise TimebaseError(
                    CODE_INVALID_DURATION,
                    f"duration must be non-negative: {duration}",
                    location="duration",
                    details={"duration_seconds": str(duration)},
                )
        if self.classification not in (CLASSIFICATION_CFR, CLASSIFICATION_VFR):
            raise TimebaseError(
                CODE_UNSUPPORTED_CLASSIFICATION,
                f"classification must be CFR or VFR, got {self.classification!r}",
                location="fps_classification",
                details={"classification": self.classification},
            )
        fps = _rational(self.fps_num, self.fps_den)
        frames = self.nb_frames
        if frames is not None and frames < 0:
            raise TimebaseError(
                CODE_INVALID_FRAME_INDEX,
                f"nb_frames must be non-negative: {frames}",
                location="nb_frames",
                details={"nb_frames": frames},
            )
        if (frames is None or frames == 0) and duration is not None and duration > 0:
            frames = _round_half_up(duration * fps)
            if frames < 1:
                frames = 1
        # Frozen dataclass: object.__setattr__ is required to normalize.
        object.__setattr__(self, "fps_num", fps.numerator)
        object.__setattr__(self, "fps_den", fps.denominator)
        object.__setattr__(self, "duration_seconds", duration)
        object.__setattr__(self, "nb_frames", frames)

    # ── Constructors ────────────────────────────────────────────────────────

    @classmethod
    def from_rational(
        cls,
        fps_num: int,
        fps_den: int,
        *,
        classification: str = CLASSIFICATION_CFR,
        duration_seconds: Fraction | str | None = None,
        nb_frames: int | None = None,
    ) -> CanonicalTimebase:
        """Build a mapping from explicit rational frame-rate components."""
        return cls(
            fps_num=fps_num,
            fps_den=fps_den,
            classification=classification,
            duration_seconds=duration_seconds,
            nb_frames=nb_frames,
        )

    @classmethod
    def from_probe(cls, probe: dict[str, Any]) -> CanonicalTimebase:
        """Build the canonical mapping from the S05-T02 canonical probe payload.

        CFR inputs use ``video_stream.r_frame_rate``; VFR inputs use
        ``video_stream.avg_frame_rate`` (both recorded as exact rationals by
        ``app.services.video_import.probe_source``).  A VFR probe whose
        ``avg_frame_rate`` is zero/missing fails closed — the canonical grid
        cannot be derived.
        """
        video_stream = probe.get("video_stream") or {}
        classification = str(video_stream.get("fps_classification") or "")
        r_rate = video_stream.get("r_frame_rate") or {}
        avg_rate = video_stream.get("avg_frame_rate") or {}
        if classification == CLASSIFICATION_CFR:
            num, den = r_rate.get("num", 0), r_rate.get("den", 0)
        elif classification == CLASSIFICATION_VFR:
            num, den = avg_rate.get("num", 0), avg_rate.get("den", 0)
        else:
            raise TimebaseError(
                CODE_UNSUPPORTED_CLASSIFICATION,
                f"probe fps_classification must be CFR or VFR, got {classification!r}",
                location="video_stream.fps_classification",
                details={"fps_classification": classification},
            )
        if int(num or 0) <= 0 or int(den or 0) <= 0:
            raise TimebaseError(
                CODE_INVALID_TIMEBASE,
                f"probe frame-rate rational must be positive: {num}/{den}",
                location="video_stream",
                details={
                    "classification": classification,
                    "r_frame_rate": r_rate,
                    "avg_frame_rate": avg_rate,
                },
            )
        duration = probe.get("container", {}).get("duration_seconds")
        if duration is None:
            duration = video_stream.get("duration_seconds")
        return cls(
            fps_num=int(num),
            fps_den=int(den),
            classification=classification,
            duration_seconds=duration,
            nb_frames=int(video_stream.get("nb_frames") or 0) or None,
        )

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def fps(self) -> Fraction:
        """The canonical frame rate as an exact ``Fraction``."""
        return Fraction(self.fps_num, self.fps_den)

    @property
    def is_vfr(self) -> bool:
        """True when the source was classified VFR."""
        return self.classification == CLASSIFICATION_VFR

    @property
    def frame_count(self) -> int | None:
        """The exact canonical frame count (None only when unknowable)."""
        return self.nb_frames

    # ── Exact conversions ───────────────────────────────────────────────────

    def frame_to_time(self, frame: int) -> Fraction:
        """Exact canonical timestamp of *frame*: ``frame / fps``.

        Raises:
            TimebaseError: ``INVALID_FRAME_INDEX`` for a negative frame.
        """
        if frame < 0:
            raise TimebaseError(
                CODE_INVALID_FRAME_INDEX,
                f"frame index must be non-negative: {frame}",
                location="frame",
                details={"frame": frame},
            )
        return Fraction(frame * self.fps_den, self.fps_num)

    def time_to_frame(
        self, time: Fraction | str | float, *, rounding: RoundingMode = "floor"
    ) -> int:
        """Map a canonical timestamp to a frame index with explicit rounding.

        ``floor`` (default) returns the frame whose interval contains the
        timestamp — frame ``n`` covers ``[n/fps, (n+1)/fps)``.  ``round_half_up``
        returns the nearest frame (half goes up); ``ceil`` returns the first
        frame at/after the timestamp.  All three are monotonic non-decreasing
        in the timestamp.  A negative timestamp maps to a negative frame; use
        :meth:`clamp_frame` for playhead semantics.
        """
        t = exact_seconds(time)
        x = t * self.fps  # exact: Fraction(t.num * fps_num, t.den * fps_den)
        if rounding == "floor":
            return x.numerator // x.denominator
        if rounding == "ceil":
            return -((-x.numerator) // x.denominator)
        if rounding == "round_half_up":
            return _round_half_up(x)
        # The parameter is typed Literal; anything else is a programming error.
        raise ValueError(f"unknown rounding mode {rounding!r}")  # pragma: no cover

    def nearest_frame(self, time: Fraction | str | float) -> int:
        """Nearest frame to *time* (half-up), for extraction use."""
        return self.time_to_frame(time, rounding="round_half_up")

    def clamp_frame(self, frame: int) -> int:
        """Clamp *frame* into the canonical frame range (playhead semantics).

        With a known frame count the result lies in ``[0, nb_frames - 1]``;
        without one, negative frames clamp to 0.
        """
        if frame < 0:
            return 0
        if self.nb_frames is not None and frame >= self.nb_frames:
            return max(0, self.nb_frames - 1)
        return frame

    # ── Duration behavior ───────────────────────────────────────────────────

    def frame_count_for_duration(self, duration: Fraction | str | float) -> int:
        """Exact frame count for *duration*: nearest-half-up ``round(d * fps)``.

        Any positive duration yields at least 1 frame; a zero duration yields
        0; a negative duration fails closed (``INVALID_DURATION``).
        """
        d = exact_seconds(duration)
        if d < 0:
            raise TimebaseError(
                CODE_INVALID_DURATION,
                f"duration must be non-negative: {d}",
                location="duration",
                details={"duration_seconds": str(d)},
            )
        if d == 0:
            return 0
        frames = _round_half_up(d * self.fps)
        return max(1, frames)

    def duration_for_frames(self, frame_count: int) -> Fraction:
        """Exact duration of *frame_count* frames: ``frame_count / fps``."""
        if frame_count < 0:
            raise TimebaseError(
                CODE_INVALID_FRAME_INDEX,
                f"frame count must be non-negative: {frame_count}",
                location="frame_count",
                details={"frame_count": frame_count},
            )
        return Fraction(frame_count * self.fps_den, self.fps_num)

    # ── Serialization (durable JSON payload) ────────────────────────────────

    def to_json(self) -> dict[str, Any]:
        """Schema-versioned durable payload (checkpoint/manifest friendly)."""
        payload: dict[str, Any] = {
            "schema_version": TIMEBASE_SCHEMA_VERSION,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "classification": self.classification,
        }
        if self.duration_seconds is not None:
            payload["duration_seconds"] = str(self.duration_seconds)
        if self.nb_frames is not None:
            payload["nb_frames"] = self.nb_frames
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> CanonicalTimebase:
        """Rebuild a mapping from :meth:`to_json`; unknown version fails closed."""
        if not isinstance(payload, dict):
            raise TimebaseError(
                CODE_UNSUPPORTED_CLASSIFICATION,
                "canonical timebase payload must be a dict",
                location="checkpoint",
            )
        if int(payload.get("schema_version") or 0) != TIMEBASE_SCHEMA_VERSION:
            raise TimebaseError(
                CODE_UNSUPPORTED_CLASSIFICATION,
                f"unknown canonical timebase schema version: "
                f"{payload.get('schema_version')!r}",
                location="checkpoint",
                details={"schema_version": payload.get("schema_version")},
            )
        duration = payload.get("duration_seconds")
        return cls(
            fps_num=int(payload["fps_num"]),
            fps_den=int(payload["fps_den"]),
            classification=str(payload.get("classification") or CLASSIFICATION_CFR),
            duration_seconds=duration,
            nb_frames=payload.get("nb_frames"),
        )


def _round_half_up(x: Fraction) -> int:
    """Nearest integer to *x*, halves rounding away from zero ("half-up").

    Exact integer arithmetic: for ``x = n/d`` the half boundary sits at
    ``(2n + d) / (2d)``; negative ``n`` mirrors away from zero so
    ``-1/2 -> -1`` and ``-3/2 -> -2`` (conventional round-half-up).
    """
    if x.numerator >= 0:
        return (2 * x.numerator + x.denominator) // (2 * x.denominator)
    return -((2 * -x.numerator + x.denominator) // (2 * x.denominator))
