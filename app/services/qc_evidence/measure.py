"""MF-P1-QC-EVIDENCE — bounded, deterministic measurements over persisted bytes.

All measurements here read ONLY artifacts that :mod:`sources` already
re-verified against the database digest; nothing is invented and no network
or model is touched (the same discipline the W6 detectors follow).

Bounding: every measurement takes an explicit ``max_frames`` window so the
composer can never decode an unbounded amount of media inside a request.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.services.qc_evidence.errors import malformed

#: Decode/measure revision — bump when a measurement definition changes.
MEASURE_REVISION = "1.0.0"

#: Hard bound on how many media frames one composition may decode.
MAX_WINDOW_FRAMES = 24

#: Grayscale normalisation used for every luminance/centroid measurement.
GRAY_SCALE = 255.0


def content_digest(value: Any) -> str:
    """sha256 over the canonical JSON of a value (deterministic)."""
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def crop_sha256(pixels: Sequence[Sequence[float]]) -> str:
    """The exact digest convention the W6 crop detectors verify.

    ``identity_drift``/``edge_halo`` hash ``json.dumps(crop["pixels"])`` with
    the default separators — this helper reproduces that byte-for-byte.
    """
    raw = json.dumps([list(row) for row in pixels], separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


def decode_png_gray(data: bytes, *, detector: str) -> tuple[list[list[float]], int, int]:
    """Decode mask/asset PNG bytes into a 0..255 grayscale matrix."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            gray = image.convert("L")
            width, height = gray.size
            matrix = np.asarray(gray, dtype=np.float64)
    except Exception as exc:
        raise malformed(
            detector, f"persisted PNG bytes are undecodable: {exc}"
        ) from exc
    if width < 1 or height < 1 or matrix.size == 0:
        raise malformed(
            detector, "persisted PNG decodes to an empty image (fail closed)"
        )
    return matrix.tolist(), int(width), int(height)


def mask_bbox(matrix: Sequence[Sequence[float]]) -> tuple[int, int, int, int]:
    """Bounding box (x0, y0, x1, y1) of the NON-ZERO mask pixels (x1/y1 excl)."""
    block = np.asarray(matrix, dtype=np.float64) > 0.0
    if not block.any():
        raise malformed(
            "qc_evidence",
            "persisted mask artifact contains no non-zero pixels — an empty "
            "mask carries no geometry to judge",
        )
    rows = np.any(block, axis=1)
    cols = np.any(block, axis=0)
    y0, y1 = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]))
    x0, x1 = int(np.argmax(cols)), int(len(cols) - np.argmax(cols[::-1]))
    return x0, y0, x1, y1


def mask_area(matrix: Sequence[Sequence[float]]) -> int:
    return int((np.asarray(matrix, dtype=np.float64) > 0.0).sum())


def disc_radius_px(area: int) -> float:
    """Equivalent radius of a filled disc of ``area`` pixels (T06A2 geometry)."""
    if area <= 0:
        raise malformed("edge_halo", "expected mask has zero area")
    return float(math.sqrt(float(area) / math.pi))


def decode_video_frames(
    path: Path, frame_indices: Sequence[int], *, detector: str
) -> dict[int, list[list[float]]]:
    """Decode specific frames of a persisted media artifact as gray matrices.

    Bounded by :data:`MAX_WINDOW_FRAMES`.  Missing frames are OMITTED from the
    result (the caller decides whether the omission is a refusal).
    """
    import cv2  # local import: only the measurement path needs OpenCV

    wanted = sorted({int(i) for i in frame_indices})[:MAX_WINDOW_FRAMES]
    if not wanted:
        return {}
    out: dict[int, list[list[float]]] = {}
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise malformed(
            detector,
            f"persisted media artifact {path.name!r} cannot be decoded "
            "(no readable video stream)",
        )
    try:
        for index in wanted:
            capture.set(cv2.CAP_PROP_POS_FRAMES, float(index))
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            out[index] = np.asarray(gray, dtype=np.float64).tolist()
    finally:
        capture.release()
    return out


def frame_luminance(frames: dict[int, list[list[float]]]) -> dict[int, float]:
    """Per-frame mean grayscale (0..255), rounded to 9 dp (deterministic)."""
    return {
        int(index): round(float(np.asarray(matrix, dtype=np.float64).mean()), 9)
        for index, matrix in sorted(frames.items())
    }


def crop_region(
    matrix: Sequence[Sequence[float]],
    bbox: tuple[int, int, int, int],
) -> list[list[float]]:
    """Crop a gray matrix to ``bbox`` (clipped to the matrix bounds)."""
    array = np.asarray(matrix, dtype=np.float64)
    x0, y0, x1, y1 = bbox
    height, width = array.shape[:2]
    x0 = max(0, min(int(x0), width - 1))
    x1 = max(x0 + 1, min(int(x1), width))
    y0 = max(0, min(int(y0), height - 1))
    y1 = max(y0 + 1, min(int(y1), height))
    return array[y0:y1, x0:x1].tolist()


def changed_centroid_x(
    source: Sequence[Sequence[float]],
    rendered: Sequence[Sequence[float]],
    *,
    threshold: float = 8.0,
) -> float | None:
    """Column centroid of the pixels that differ between two same-size frames.

    This is the measured placement of whatever the render actually composited
    inside the frame: no assumption about the layer is made beyond "the bytes
    differ there".  Returns ``None`` when nothing changed (no rendered delta).
    """
    a = np.asarray(source, dtype=np.float64)
    b = np.asarray(rendered, dtype=np.float64)
    if a.shape != b.shape:
        raise malformed(
            "trajectory_drift",
            f"source frame {a.shape} and render frame {b.shape} have "
            "different geometry",
        )
    changed = np.abs(a - b) >= float(threshold)
    if not changed.any():
        return None
    cols = np.where(changed.any(axis=0))[0]
    weights = changed.sum(axis=0)[cols].astype(np.float64)
    columns = cols.astype(np.float64)
    return float((columns * weights).sum() / weights.sum())


def window_indices(start: int, end: int, *, limit: int = MAX_WINDOW_FRAMES) -> list[int]:
    """Evenly spaced frame indices inside ``[start, end]`` (bounded)."""
    if end < start:
        raise malformed(
            "qc_evidence", f"window {start}..{end} is inverted (fail closed)"
        )
    span = end - start + 1
    if span <= limit:
        return list(range(start, end + 1))
    step = span / float(limit)
    return sorted({start + int(i * step) for i in range(limit)})


def crop_revision(pixels: Sequence[Sequence[float]]) -> str:
    """Short content-derived crop revision (pins the exact crop payload)."""
    return crop_sha256(pixels)[:16]


# ── MF-END-22: source-facts ↔ output-observations comparison ─────────────────
#
# The comparison band consumes TWO independently produced artifacts and never
# substitutes one for the other (U21):
#
# * SOURCE facts — ``app/services/source_interaction_facts.py`` (MF-END-13),
#   derived from the real role tracks of ``app/services/source_role_tracks.py``
#   (MF-END-12) decoded from the SOURCE video;
# * OUTPUT observations — ``app/services/rendered_observations.py`` (MF-END-21),
#   measured on the pixels of the RENDERED output.
#
# The measurement vocabulary below is the SOURCE side's own vocabulary, cited
# from its constants (never re-invented); a missing or ambiguous input is a
# typed UNKNOWN/refusal, never a guess.

COMPARISON_REVISION = "1.0.0"
COMPARISON_SCHEMA_VERSION = 1
COMPARISON_POLICY_ID = "mf-end-22-comparison-v1"

#: Derivation levels (T06A2 convention: warning = level-2 raw MEASURED value,
#: blocker = level-4 raw MEASURED value, sanity = [0, max calibrated]).
COMPARISON_WARNING_LEVEL = 2
COMPARISON_BLOCKER_LEVEL = 4

#: Error levels: hard defects dominate the verdict (a pretty image never
#: compensates a hard relation/identity failure); soft defects warn.
LEVEL_HARD = "hard"
LEVEL_SOFT = "soft"

#: Verdict vocabulary — only ``pass`` is a pass (binary gate).
VERDICT_PASS = "pass"
VERDICT_WARN = "warn"
VERDICT_FAIL = "fail"
VERDICT_UNKNOWN = "unknown"
VERDICT_BLOCKED = "blocked"

#: Frozen comparison metric taxonomy (one metric per compared relation).
METRIC_CONTACT_GAP = "contact_gap_px"
METRIC_OCCLUSION_REVERSAL = "occlusion_reversal_containment"
METRIC_IDENTITY_UNLINKED = "identity_unlinked_ratio"
METRIC_MOTION_ATTENUATION = "motion_attenuation_ratio"
METRIC_FRAME_SHIFT = "frame_shift_frames"
COMPARISON_METRICS = (
    METRIC_CONTACT_GAP,
    METRIC_OCCLUSION_REVERSAL,
    METRIC_IDENTITY_UNLINKED,
    METRIC_MOTION_ATTENUATION,
    METRIC_FRAME_SHIFT,
)

#: Units of the frozen metrics.
COMPARISON_METRIC_UNITS = {
    METRIC_CONTACT_GAP: "px",
    METRIC_OCCLUSION_REVERSAL: "ratio",
    METRIC_IDENTITY_UNLINKED: "ratio",
    METRIC_MOTION_ATTENUATION: "ratio",
    METRIC_FRAME_SHIFT: "frame",
}

#: Shared measurement constants — SAME values the source side (MF-END-13)
#: calibrates against (cited, never re-derived):
#: contact = bbox edge gap <= 8 px with containment >= 0.55 (grasp),
#: occlusion cue = containment >= 0.55, content static read <= 0.03 px/frame.
COMPARISON_CONTACT_MAX_GAP_PX = 8.0
COMPARISON_CONTACT_MIN_CONTAINMENT = 0.55
COMPARISON_OCCLUSION_MIN_CONTAINMENT = 0.55
COMPARISON_STATIC_MAX_PX_PER_FRAME = 0.03

#: Physical floor for the COMPARISON metrics (px / ratio / frame are all
#: non-negative quantities); the comparison metrics are unbounded above.
SANITY_FLOOR = 0.0
CODE_COMPARISON_INVALID = "QC_COMPARISON_INVALID"
CODE_COMPARISON_SOURCE_INVALID = "QC_COMPARISON_SOURCE_INVALID"
CODE_COMPARISON_OUTPUT_INVALID = "QC_COMPARISON_OUTPUT_INVALID"
CODE_COMPARISON_FRAME_MAP = "QC_COMPARISON_FRAME_MAP_INVALID"
CODE_COMPARISON_NOT_OBSERVED = "QC_COMPARISON_NOT_OBSERVED"
CODE_COMPARISON_UNKNOWN = "QC_COMPARISON_UNKNOWN"
CODE_COMPARISON_BLOCKED = "QC_COMPARISON_BLOCKED"
CODE_CONTACT_LOST = "QC_COMPARISON_CONTACT_LOST"
CODE_CONTACT_WEAKENED = "QC_COMPARISON_CONTACT_WEAKENED"
CODE_CONTACT_OWNER_CHANGED = "QC_COMPARISON_CONTACT_OWNER_CHANGED"
CODE_OCCLUSION_REVERSED = "QC_COMPARISON_OCCLUSION_REVERSED"
CODE_OCCLUSION_WEAKENED = "QC_COMPARISON_OCCLUSION_WEAKENED"
CODE_IDENTITY_LOST = "QC_COMPARISON_IDENTITY_LOST"
CODE_IDENTITY_WEAK = "QC_COMPARISON_IDENTITY_WEAK"
CODE_MOTION_STATIC = "QC_COMPARISON_MOTION_STATIC"
CODE_MOTION_LOST = "QC_COMPARISON_MOTION_LOST"
CODE_MOTION_ATTENUATED = "QC_COMPARISON_MOTION_ATTENUATED"
CODE_FRAME_SHIFT = "QC_COMPARISON_FRAME_SHIFT"


# ── measurement primitives (the SOURCE side's own definitions) ───────────────


def bbox_of(observation: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    """``[x, y, w, h]`` from an observation payload; None when unusable.

    Mirrors ``source_interaction_facts._bbox`` (w/h must be positive).
    """
    raw = observation.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0.0 or h <= 0.0:
        return None
    return (x, y, w, h)


def bbox_gap_px(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> float:
    """Edge-to-edge distance between two ``[x, y, w, h]`` boxes (px).

    Byte-for-byte the source side's ``_gap_px`` definition (0.0 on overlap).
    """
    ax0, ay0, aw, ah = first
    bx0, by0, bw, bh = second
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return float(math.hypot(dx, dy))


def bbox_containment(
    subject: tuple[float, float, float, float],
    object_box: tuple[float, float, float, float],
) -> float:
    """Intersection area / object area — the source side's ``_containment``."""
    ax0, ay0, aw, ah = subject
    bx0, by0, bw, bh = object_box
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    return (ix * iy) / (bw * bh)


def bbox_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = box
    return (x + w / 2.0, y + h / 2.0)


def observations_by_frame(
    track: Mapping[str, Any],
    *,
    frame_map: Mapping[int, int] | None = None,
) -> dict[int, Mapping[str, Any]]:
    """The track's observations keyed by SOURCE frame index.

    ``frame_map`` translates the observation's OUTPUT frame index into the
    source frame index it depicts (preserved frame mapping — never guessed:
    callers that pass no map declare the identity mapping in evidence).
    """
    rows: dict[int, Mapping[str, Any]] = {}
    for item in track.get("observations") or []:
        if not isinstance(item, Mapping):
            continue
        frame = int(item.get("frame", -1))
        if frame < 0:
            continue
        source_frame = int(frame_map[frame]) if frame_map is not None else frame
        rows[source_frame] = item
    return rows


def missing_flags(track: Mapping[str, Any]) -> dict[str, set[int]]:
    """Frames the track pays no usable mask for, by typed reason."""
    return {
        "gap_frames": {int(v) for v in track.get("gap_frames") or []},
        "out_of_frame_frames": {int(v) for v in track.get("out_of_frame_frames") or []},
        "partial_frames": {int(v) for v in track.get("partial_frames") or []},
    }


def covered_frames(track: Mapping[str, Any]) -> set[int]:
    runs = track.get("occlusion_runs") or []
    out: set[int] = set()
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        start = int(run.get("start_frame", 0))
        end = int(run.get("end_frame", start))
        out.update(range(start, end))
    return out


def motion_px_per_frame(series: Sequence[tuple[float, float]]) -> float:
    """Mean centroid step (px/frame) of a centre series (0.0 when < 2 points)."""
    if len(series) < 2:
        return 0.0
    total = 0.0
    for (ax, ay), (bx, by) in zip(series[:-1], series[1:], strict=True):
        total += math.hypot(float(bx) - float(ax), float(by) - float(ay))
    return total / float(len(series) - 1)


def step_series(series: Sequence[float]) -> list[float]:
    """First differences of a scalar series (empty for < 2 points)."""
    return [float(b) - float(a) for a, b in zip(series[:-1], series[1:], strict=True)]


def measure_contact_gap_px(
    subject_rows: Mapping[int, Mapping[str, Any]],
    object_rows: Mapping[int, Mapping[str, Any]],
    frames: Sequence[int],
) -> float | None:
    """Min measured bbox gap (px) between two instances over ``frames``.

    Frames where either side has no measured box contribute no measurement
    (they are counted by the caller); ``None`` when nothing is measurable.
    """
    gaps: list[float] = []
    for frame in frames:
        left = bbox_of(subject_rows.get(int(frame)) or {})
        right = bbox_of(object_rows.get(int(frame)) or {})
        if left is None or right is None:
            continue
        gaps.append(bbox_gap_px(left, right))
    if not gaps:
        return None
    return float(min(gaps))


def measure_containment_mean(
    first_rows: Mapping[int, Mapping[str, Any]],
    second_rows: Mapping[int, Mapping[str, Any]],
    frames: Sequence[int],
) -> float | None:
    """Mean containment of the FIRST instance's box inside the SECOND's box.

    ``mean(containment(first, second))`` — the same directional containment
    the source side measures (1.0 = the first instance's box sits fully inside
    the second's box on every measured frame).
    """
    values: list[float] = []
    for frame in frames:
        left = bbox_of(first_rows.get(int(frame)) or {})
        right = bbox_of(second_rows.get(int(frame)) or {})
        if left is None or right is None:
            continue
        values.append(bbox_containment(left, right))
    if not values:
        return None
    return float(sum(values) / len(values))


def measure_unlinked_ratio(states: Sequence[str]) -> float:
    """Fraction of frames whose role link is not ``matched`` (0.0 when empty)."""
    if not states:
        return 0.0
    unlinked = sum(1 for state in states if str(state) != "matched")
    return float(unlinked) / float(len(states))


def measure_motion_attenuation(
    source_series: Sequence[tuple[float, float]],
    output_series: Sequence[tuple[float, float]],
) -> float | None:
    """``1 - output_motion / source_motion`` in px/frame (None when unmeasurable).

    A source that does not move cannot be attenuated: no attenuation value is
    fabricated for it (the caller treats it as a no-op comparison).
    """
    source = motion_px_per_frame(source_series)
    output = motion_px_per_frame(output_series)
    if source <= 0.0:
        return None
    return float(1.0 - (output / source))


def measure_frame_shift(
    source_steps: Sequence[float],
    output_steps: Sequence[float],
    *,
    max_shift: int = 8,
) -> int:
    """Best matching time shift (frames) between two step series.

    The shift ``s`` minimises ``mean|output_step[i + s] - source_step[i]|``
    over the overlap (positive = the output happens LATER).  Deterministic;
    ties resolve to the smallest |shift| then the smaller shift.
    """
    best_shift = 0
    best_score: float | None = None
    for shift in range(-int(max_shift), int(max_shift) + 1):
        pairs = [
            (float(source_steps[i]), float(output_steps[i + shift]))
            for i in range(len(source_steps))
            if 0 <= i + shift < len(output_steps)
        ]
        if not pairs:
            continue
        score = sum(abs(b - a) for a, b in pairs) / float(len(pairs))
        key = (score, abs(shift), shift)
        if best_score is None or key < (best_score, abs(best_shift), best_shift):
            best_score, best_shift = score, shift
    return int(best_shift)


# ── the FROZEN comparison policy (calibrated BEFORE any candidate) ───────────
#
# Every boundary is a MEASURED raw value at a deliberately perturbed level,
# never an invented number: the control row (level 1) plus the wrong
# role/camera/time/contact rows (levels 2..4) are run through the SAME
# measurement functions the comparators use, at import time, and the frozen
# policy's boundaries are read off those measurements.  A candidate that
# fails is never an argument for widening a boundary (uphold-after-fail).


def _calibration_scene_boxes(offset_px: float) -> tuple[
    tuple[float, float, float, float], tuple[float, float, float, float]
]:
    """Two boxes: the object displaced by ``offset_px`` from the subject."""
    subject = (0.0, 0.0, 20.0, 20.0)
    object_box = (20.0 + float(offset_px), 4.0, 8.0, 8.0)
    return subject, object_box


def _calibration_rows() -> dict[str, dict[int, float]]:
    """MEASURED calibration rows: control + deliberately wrong cases.

    level 1 = control (relation intact), levels 2..4 = increasing deliberate
    defects of the four kinds the task names (contact, role, camera/time,
    ordering).  Values are measured, never typed in by hand.
    """
    rows: dict[str, dict[int, float]] = {}

    # contact / BOOK: object displaced 0, 2, 8, 24 px from the subject
    contact: dict[int, float] = {}
    for level, offset in ((1, 0.0), (2, 2.0), (3, 8.0), (4, 24.0)):
        subject, object_box = _calibration_scene_boxes(offset)
        measured = measure_contact_gap_px(
            {0: {"bbox": list(subject)}}, {0: {"bbox": list(object_box)}}, [0]
        )
        contact[level] = float(measured if measured is not None else 0.0)
    rows[METRIC_CONTACT_GAP] = contact

    # occlusion order: how much of the OCCLUDEE's reference box the declared
    # OCCLUDER now covers — the REVERSED relation, at 0.0 / 0.55 / 0.72 / 0.90
    reversal: dict[int, float] = {}
    for level, target in ((1, 0.0), (2, 0.55), (3, 0.72), (4, 0.90)):
        # reference box 100x100; the covering box scaled to the target share
        reference_box = (0.0, 0.0, 100.0, 100.0)
        side = math.sqrt(max(0.0, target)) * 100.0
        covering_box = (0.0, 0.0, side, side)
        measured = measure_containment_mean(
            {0: {"bbox": list(covering_box)}},
            {0: {"bbox": list(reference_box)}},
            [0],
        )
        reversal[level] = float(measured if measured is not None else 0.0)
    rows[METRIC_OCCLUSION_REVERSAL] = reversal

    # identity / wrong role: unlinked frames 0 / 12 of 12 ...
    identity: dict[int, float] = {}
    for level, unlinked in ((1, 0), (2, 1), (3, 3), (4, 6)):
        states = ["matched"] * (12 - unlinked) + ["unknown"] * unlinked
        identity[level] = measure_unlinked_ratio(states)
    rows[METRIC_IDENTITY_UNLINKED] = identity

    # motion / wrong camera: attenuation 0.0, 0.35, 0.60, 0.90
    motion: dict[int, float] = {}
    source_series = [(float(i) * 10.0, 0.0) for i in range(12)]
    for level, retained in ((1, 1.0), (2, 0.65), (3, 0.40), (4, 0.10)):
        output_series = [(float(i) * 10.0 * retained, 0.0) for i in range(12)]
        measured = measure_motion_attenuation(source_series, output_series)
        motion[level] = float(measured if measured is not None else 0.0)
    rows[METRIC_MOTION_ATTENUATION] = motion

    # time / wrong timing: a motion burst shifted by 0, 1, 2, 4 frames
    shift: dict[int, float] = {}
    burst = [0.0] * 12
    burst[3] = 6.0
    burst[6] = -4.0
    for level, offset in ((1, 0), (2, 1), (3, 2), (4, 4)):
        shifted = [0.0] * 12
        for index, value in enumerate(burst):
            if 0 <= index + offset < len(shifted):
                shifted[index + offset] = value
        shift[level] = float(measure_frame_shift(burst, shifted))
    rows[METRIC_FRAME_SHIFT] = shift
    return rows


#: Frozen measured calibration rows (computed at import, deterministic).
COMPARISON_CALIBRATION: dict[str, dict[int, float]] = _calibration_rows()


def comparison_policy() -> dict[str, Any]:
    """Derive the frozen comparison policy from the MEASURED calibration rows.

    Derivation rule (same as the T03A policy): increasing metrics take
    warning = level-2 raw value and blocker = level-4 raw value; the sanity
    envelope carries the physical floor 0.0 only (the comparison metrics are
    unbounded above); every boundary cites its row.  Two calls produce the
    same body and the same ``content_hash`` (no hidden state).
    """
    thresholds: dict[str, Any] = {}
    for metric in COMPARISON_METRICS:
        rows = COMPARISON_CALIBRATION[metric]
        warning = float(rows[COMPARISON_WARNING_LEVEL])
        blocker = float(rows[COMPARISON_BLOCKER_LEVEL])
        if blocker < warning:
            raise malformed(
                "qc_comparison",
                f"calibration for {metric!r} is not increasing "
                f"(warning={warning!r} > blocker={blocker!r})",
            )
        thresholds[metric] = {
            "metric": metric,
            "unit": COMPARISON_METRIC_UNITS[metric],
            "kind": "increasing",
            "warning_boundary": warning,
            "blocker_boundary": blocker,
            # Comparison metrics are UNBOUNDED ABOVE (a contact can be lost by
            # an arbitrarily large gap, a render can be shifted by arbitrarily
            # many frames): the sanity envelope is the physical FLOOR only.
            # Non-finite/negative values are invalid (fail closed); a value
            # worse than the level-4 row is still classified by the same
            # monotone boundaries.
            "sanity_bounds": {"min": SANITY_FLOOR, "max": None},
            "provenance": {
                "policy": COMPARISON_POLICY_ID,
                "revision": COMPARISON_REVISION,
                "warning_boundary_source": (
                    f"COMPARISON_CALIBRATION[{metric}][level="
                    f"{COMPARISON_WARNING_LEVEL}] (measured)"
                ),
                "blocker_boundary_source": (
                    f"COMPARISON_CALIBRATION[{metric}][level="
                    f"{COMPARISON_BLOCKER_LEVEL}] (measured)"
                ),
                "sanity_rule": (
                    "physical non-negativity floor only; comparison metrics are "
                    "unbounded above, so a value beyond the level-4 row stays a "
                    "blocker instead of becoming unmeasurable"
                ),
            },
        }
    body: dict[str, Any] = {
        "policy_id": COMPARISON_POLICY_ID,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "revision": COMPARISON_REVISION,
        "derivation_rule": (
            "increasing: warning = level-2 measured raw value, blocker = "
            "level-4 measured raw value, sanity = [0, level-4 raw]; the "
            "calibration rows are measured by the same functions the "
            "comparators use, before any candidate is evaluated; a failing "
            "candidate never widens a boundary"
        ),
        "thresholds": dict(sorted(thresholds.items())),
        "calibration": {
            metric: {str(level): value for level, value in sorted(rows.items())}
            for metric, rows in sorted(COMPARISON_CALIBRATION.items())
        },
    }
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {**body, "content_hash": digest}


_FROZEN_COMPARISON_POLICY: dict[str, Any] | None = None


def frozen_comparison_policy() -> dict[str, Any]:
    """The policy as frozen at first use (same content, same digest, always)."""
    global _FROZEN_COMPARISON_POLICY
    if _FROZEN_COMPARISON_POLICY is None:
        _FROZEN_COMPARISON_POLICY = comparison_policy()
    return _FROZEN_COMPARISON_POLICY


def comparison_policy_digest() -> str:
    return str(frozen_comparison_policy()["content_hash"])


def comparison_threshold(metric: str) -> dict[str, Any]:
    entry = frozen_comparison_policy()["thresholds"].get(metric)
    if entry is None:
        raise malformed("qc_comparison", f"unknown comparison metric: {metric!r}")
    return dict(entry)


def classify_comparison(metric: str, value: float) -> tuple[str, str]:
    """Classify a measured value against the FROZEN comparison policy.

    Returns ``(status, code)`` with the T03A status vocabulary; non-finite or
    out-of-envelope values are ``invalid`` (fail closed) before comparison.
    """
    entry = comparison_threshold(metric)
    bounds = entry["sanity_bounds"]
    if not math.isfinite(float(value)) or float(value) < bounds["min"]:
        return "invalid", "THRESHOLD_INVALID"
    if bounds.get("max") is not None and float(value) > bounds["max"]:
        return "invalid", "THRESHOLD_INVALID"
    if float(value) >= entry["blocker_boundary"]:
        return "blocker", "THRESHOLD_BLOCKER"
    if float(value) >= entry["warning_boundary"]:
        return "warning", "THRESHOLD_WARNING"
    return "pass", "THRESHOLD_PASS"


# ── comparison items + the dominating verdict ────────────────────────────────


def comparison_item(
    *,
    metric: str,
    code: str,
    level: str,
    severity: str,
    role_id: str,
    frames: Sequence[int],
    detail: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """One classifier item: metric + code + hard/soft level + role/frames."""
    measured = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "metric": metric,
        "code": code,
        "level": level,
        "severity": severity,
        "role_id": str(role_id),
        "frames": [int(v) for v in frames],
        "detail": str(detail),
        "policy": comparison_threshold(metric),
        "revision": COMPARISON_REVISION,
    }
    measured["evidence"] = dict(evidence)
    measured["evidence_window_key"] = content_digest(measured)
    return measured


def compare_verdict(
    items: Sequence[Mapping[str, Any]],
    *,
    uncertain: Sequence[Mapping[str, Any]] = (),
    blocked: Sequence[Mapping[str, Any]] = (),
    appearance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The binary verdict: a HARD defect fails outright.

    ``appearance`` records what the output looks like (support separation,
    luminance stability, ...) as EVIDENCE only: it can never upgrade a verdict
    (a pretty image does not compensate a hard relation/identity failure).
    Missing/ambiguous data (``uncertain``/``blocked``) is never a pass either —
    the verdict is ``unknown``/``blocked`` with its typed reasons.
    """
    hard = [dict(item) for item in items if item.get("level") == LEVEL_HARD]
    soft = [dict(item) for item in items if item.get("level") == LEVEL_SOFT]
    if hard:
        verdict = VERDICT_FAIL
    elif blocked:
        verdict = VERDICT_BLOCKED
    elif uncertain:
        verdict = VERDICT_UNKNOWN
    elif soft:
        verdict = VERDICT_WARN
    else:
        verdict = VERDICT_PASS
    return {
        "verdict": verdict,
        "passed": verdict == VERDICT_PASS,
        "hard_failures": [item["code"] for item in hard],
        "soft_failures": [item["code"] for item in soft],
        "unknown": [dict(item) for item in uncertain],
        "blocked": [dict(item) for item in blocked],
        "appearance": dict(appearance) if appearance else None,
        "appearance_cannot_override_hard_fail": True,
        "items": [dict(item) for item in items],
        "policy_id": COMPARISON_POLICY_ID,
        "policy_digest": comparison_policy_digest(),
        "revision": COMPARISON_REVISION,
    }


def comparison_frame_map(
    *,
    source_span: Mapping[str, int],
    output_span: Mapping[str, int],
    declared: Mapping[int, int] | None,
) -> tuple[dict[int, int] | None, dict[str, Any]]:
    """Resolve the source→output frame mapping, PRESERVING the declaration.

    Returns ``(frame_map, evidence)``.  ``frame_map`` is ``None`` (with a
    typed refusal in the evidence) when the mapping cannot be proven: an
    explicit declaration is used as given; without one the mapping is the
    identity ONLY when the two spans are the same interval (measured), and the
    identity basis is recorded — it is never assumed silently.
    """
    def _span(payload: Mapping[str, int]) -> tuple[int, int]:
        return (
            int(payload.get("start_frame", 0)),
            int(payload.get("end_frame_exclusive", payload.get("end_frame", 0))),
        )

    src = _span(source_span)
    out = _span(output_span)
    evidence: dict[str, Any] = {
        "source_span": {"start_frame": src[0], "end_frame_exclusive": src[1]},
        "output_span": {"start_frame": out[0], "end_frame_exclusive": out[1]},
        "declared": {str(k): int(v) for k, v in (declared or {}).items()},
    }
    if declared is not None:
        mapping = {int(k): int(v) for k, v in declared.items()}
        evidence["basis"] = "declared"
        mismatched = [
            frame for frame, mapped in mapping.items() if not (out[0] <= mapped < out[1])
        ]
        if mismatched:
            evidence["code"] = CODE_COMPARISON_FRAME_MAP
            evidence["detail"] = (
                f"declared mapping sends source frames {sorted(mismatched)[:5]} "
                f"outside the output span [{out[0]}, {out[1]})"
            )
            return None, evidence
        return mapping, evidence
    if src == out:
        evidence["basis"] = "identical_spans"
        return {frame: frame for frame in range(src[0], src[1])}, evidence
    evidence["code"] = CODE_COMPARISON_FRAME_MAP
    evidence["detail"] = (
        f"no declared frame mapping and the spans differ "
        f"(source [{src[0]}, {src[1]}) vs output [{out[0]}, {out[1]})) — the "
        "mapping is not guessed"
    )
    return None, evidence


def load_source_facts(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify an MF-END-13 facts payload independently (digest + contract)."""
    body = dict(payload)
    digest = str(body.get("digest", ""))
    without = {key: value for key, value in body.items() if key != "digest"}
    if not digest:
        return {}, {"code": CODE_COMPARISON_SOURCE_INVALID, "detail": "no digest"}
    recomputed = content_digest(without)
    if recomputed != digest:
        return {}, {
            "code": CODE_COMPARISON_SOURCE_INVALID,
            "detail": (
                f"facts digest {digest} != recomputed {recomputed}; the source "
                "facts are not the bytes their record seals"
            ),
        }
    return body, {}


def load_output_observations(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify an MF-END-21 observations payload independently (sealed digest)."""
    from app.services import rendered_observations as ro  # lazy: no import cycle

    body = dict(payload)
    try:
        artifact = ro.RenderedObservationsArtifact.from_payload(body)
    except Exception as err:  # noqa: BLE001 - typed refusal, never a crash
        return {}, {
            "code": CODE_COMPARISON_OUTPUT_INVALID,
            "detail": f"rendered-observations payload refused: {err}",
        }
    violations = ro.check_artifact(artifact)
    if violations:
        return {}, {
            "code": CODE_COMPARISON_OUTPUT_INVALID,
            "detail": "; ".join(violations),
        }
    return artifact.to_payload(), {}


def load_source_tracks(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify an MF-END-12 role-tracks payload independently (sealed contract)."""
    from app.services import source_role_tracks as srt  # lazy: no import cycle

    body = dict(payload)
    try:
        artifact = srt.RoleTracksArtifact.from_payload(body)
    except Exception as err:  # noqa: BLE001 - typed refusal, never a crash
        return {}, {
            "code": CODE_COMPARISON_SOURCE_INVALID,
            "detail": f"role-tracks payload refused: {err}",
        }
    violations = srt.check_artifact(artifact)
    if violations:
        return {}, {
            "code": CODE_COMPARISON_SOURCE_INVALID,
            "detail": "; ".join(violations),
        }
    return artifact.to_payload(), {}


def track_by_role(payload: Mapping[str, Any], role_id: str) -> dict[str, Any] | None:
    for track in payload.get("tracks") or []:
        if isinstance(track, Mapping) and str(track.get("role_id")) == str(role_id):
            return dict(track)
    return None


def refused_role(payload: Mapping[str, Any], role_id: str) -> dict[str, Any] | None:
    for item in payload.get("refused_tracks") or payload.get("refused_seeds") or []:
        if isinstance(item, Mapping) and str(item.get("role_id")) == str(role_id):
            return dict(item)
    return None


def granted_rows(
    track: Mapping[str, Any], *, permission_key: str = "permission"
) -> dict[int, Mapping[str, Any]]:
    """Rows of a SOURCE track with a granted mask, keyed by frame.

    A frame the source track does not grant (occlusion run / gap) carries no
    usable box and therefore no measurable row.
    """
    rows: dict[int, Mapping[str, Any]] = {}
    for item in track.get("observations") or []:
        if not isinstance(item, Mapping):
            continue
        permission = item.get(permission_key)
        if permission is not None and str(permission) != "granted":
            continue
        frame = int(item.get("frame", -1))
        if frame < 0 or bbox_of(item) is None:
            continue
        rows[frame] = item
    return rows


def output_rows(ctx: Mapping[str, Any], role_id: str) -> dict[str, Any] | None:
    """The OUTPUT track of one role with its rows mapped back to source frames.

    Returns ``None`` when the output carries no track for the role (the
    caller records a typed refusal instead of inventing an observation).
    """
    track = track_by_role(ctx["observations"], role_id)
    if track is None:
        return None
    mapping = dict(ctx["output_to_source"])
    rows: dict[int, Mapping[str, Any]] = {}
    for item in track.get("observations") or []:
        if not isinstance(item, Mapping):
            continue
        frame = int(item.get("frame", -1))
        if frame not in mapping:
            continue
        rows[int(mapping[frame])] = item
    missing = {
        key: sorted({int(mapping[f]) for f in values if int(f) in mapping})
        for key, values in missing_flags(track).items()
    }

    def _mapped(frames: set[int]) -> list[int]:
        return sorted({int(mapping[f]) for f in frames if int(f) in mapping})

    return {
        "track": track,
        "rows": rows,
        "gap_frames": _mapped({int(v) for v in track.get("gap_frames") or []}),
        "out_of_frame_frames": _mapped(
            {int(v) for v in track.get("out_of_frame_frames") or []}
        ),
        "partial_frames": _mapped({int(v) for v in track.get("partial_frames") or []}),
        "occluded_frames": _mapped(covered_frames(track)),
        "missing": missing,
    }


def reference_box(rows: Mapping[int, Mapping[str, Any]], order: Sequence[int]) -> tuple[
    float, float, float, float
] | None:
    """First usable box in ``order`` — the instance's measured extent."""
    for frame in order:
        box = bbox_of(rows.get(int(frame)) or {})
        if box is not None:
            return box
    return None


def comparison_result(
    *,
    detector: str,
    reason_code: str,
    verdict: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    uncertain: Sequence[Mapping[str, Any]],
    blocked: Sequence[Mapping[str, Any]],
    checked: Sequence[Mapping[str, Any]],
    ctx: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The shared comparator result envelope (deterministic, JSON-safe)."""
    result: dict[str, Any] = {
        "detector": detector,
        "reason_code": reason_code,
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "revision": COMPARISON_REVISION,
        "policy": {
            "policy_id": COMPARISON_POLICY_ID,
            "digest": comparison_policy_digest(),
        },
        "verdict": dict(verdict),
        "items": [dict(item) for item in items],
        "unknown": [dict(item) for item in uncertain],
        "blocked": [dict(item) for item in blocked],
        "checked": [dict(item) for item in checked],
        "mapping": dict(ctx.get("mapping") or {}),
        "provenance": dict(ctx.get("provenance") or {}),
    }
    if extra:
        result.update(dict(extra))
    return result


def comparison_context(
    args: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verify BOTH sides of a comparison and resolve the frame mapping.

    The two artifacts are sealed independently (MF-END-13 facts / MF-END-21
    observations) and must bind to the SAME source bytes; the source→output
    frame mapping is preserved (declared or identical spans), never guessed.
    Any failure is a typed refusal — the comparators then report it as
    ``blocked`` and never fabricate a measurement.
    """
    refusals: list[dict[str, Any]] = []
    facts, refusal = load_source_facts(args.get("source_facts") or {})
    if refusal:
        refusals.append(dict(refusal, side="source_facts"))
    observations, refusal = load_output_observations(
        args.get("output_observations") or {}
    )
    if refusal:
        refusals.append(dict(refusal, side="output_observations"))
    source_tracks: dict[str, Any] = {}
    if args.get("source_tracks") is not None:
        source_tracks, refusal = load_source_tracks(args.get("source_tracks") or {})
        if refusal:
            refusals.append(dict(refusal, side="source_tracks"))
    if refusals:
        return {}, refusals

    facts_source = str((facts.get("source") or {}).get("sha256") or "")
    output_block = observations.get("output") or {}
    bound_source = str(
        output_block.get("source_sha256") or observations.get("source_sha256") or ""
    )
    if facts_source and bound_source and facts_source != bound_source:
        return {}, [
            {
                "code": CODE_COMPARISON_SOURCE_INVALID,
                "side": "binding",
                "detail": (
                    f"the facts artifact measures source {facts_source} but the "
                    f"output observations are bound to source {bound_source}; "
                    "the two sides do not describe the same render of the same "
                    "source (fail closed)"
                ),
            }
        ]

    raw_map = args.get("frame_map")
    declared: Mapping[Any, Any] | None = None
    if isinstance(raw_map, Mapping):
        declared = (
            raw_map.get("source_to_output")
            if "source_to_output" in raw_map
            else raw_map
        )
    frame_map, mapping_evidence = comparison_frame_map(
        source_span=(facts.get("source") or {}).get("span") or {},
        output_span=observations.get("span") or {},
        declared=declared,
    )
    if frame_map is None:
        return {}, [
            {
                "code": CODE_COMPARISON_FRAME_MAP,
                "side": "frame_map",
                "detail": str(mapping_evidence.get("detail", "")),
            }
        ]
    output_to_source = {int(mapped): int(source) for source, mapped in frame_map.items()}
    ctx: dict[str, Any] = {
        "facts": facts,
        "observations": observations,
        "source_tracks": source_tracks,
        "frame_map": frame_map,
        "output_to_source": output_to_source,
        "mapping": mapping_evidence,
        "provenance": {
            "source_production": bool(facts.get("production")),
            "output_production": bool(observations.get("production")),
            "output_sha256": str(output_block.get("sha256") or ""),
            "output_engine": str((observations.get("engine") or {}).get("engine_id") or ""),
            "source_sha256": facts_source,
            "source_track_digest": str(
                (facts.get("track_artifact") or {}).get("digest") or ""
            ),
        },
    }
    return ctx, []
