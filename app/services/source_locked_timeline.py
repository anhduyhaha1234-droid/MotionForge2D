"""Source-locked timeline authority — shared frozen-contract helpers.

S12-PUBLIC-AUTHORITY-BRIDGE (bounded cross-sprint bridge under Manager B).
Normative basis: ``docs/pm/sessions/S12-PUBLIC-AUTHORITY-BRIDGE/CONTRACT.md``
v0.1 (commit ``3963d31``) + Manager B freeze rulings
(``BRIDGE_CONTRACT_FREEZE_REVIEW.md``) + amendment v0.2
(``BRIDGE_RULING_Q4_region_scale_v0.2.md``: dual-mode region derivation).

Pure module: values in, values out — no DB, no IO, no time/process leakage.
Shared by the S09 authority builder (approval time) and by the S10 planner /
worker consumption path (fail-closed validation of the frozen block).

Vocabulary (frozen, CONTRACT §7 + v0.2):
  boxed geometry (Q1): segmentation.boxes[0] -> prompt.boxes[0] precedence;
  0 boxes -> missing; >1 differing boxes within a key -> ambiguous (deny);
  malformed numeric entry -> tampered.
  region derivation (v0.2): Mode A normalized [0,1] xywh; Mode B pixel-scale
  divided by persisted source dims; neither -> denied with a typed code.
  timeline block: version ``s09.full-apply-timeline/v1`` lives inside
  ``full_apply_authority.timeline`` and is covered by ``checkpoint_hash``.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "TIMELINE_VERSION",
    "TimelineAuthorityError",
    "CODE_SCENE_MISSING",
    "CODE_ORDER_MISMATCH",
    "CODE_COVERAGE_GAP",
    "CODE_COVERAGE_OVERLAP",
    "CODE_COVERAGE_FRAME_COUNT",
    "CODE_OCCURRENCE_OUT_OF_RANGE",
    "CODE_SOURCE_GENERATION_MISMATCH",
    "CODE_TIME_BASE_UNAVAILABLE",
    "CODE_TIME_BASE_MISMATCH",
    "CODE_BOX_MISSING",
    "CODE_BOX_AMBIGUOUS",
    "CODE_GEOMETRY_TAMPERED",
    "CODE_REGION_OUT_OF_BOUNDS",
    "CODE_REGION_SCALE_UNRESOLVED",
    "CODE_DUPLICATE_IDENTITY",
    "CODE_ROLE_UNMAPPED",
    "CODE_ROUTE_NOT_EXECUTABLE",
    "CODE_LEGACY_AUTHORITY",
    "normalize_box",
    "select_occurrence_box",
    "derive_region",
    "validate_partition",
    "validate_timeline_block",
    "parse_time_base",
    "pick_partition_code",
]

#: Version tag of the frozen timeline block (CONTRACT §5 / ruling Q6).
TIMELINE_VERSION = "s09.full-apply-timeline/v1"

# ── typed reason codes (stable machine-readable strings) ─────────────────────
CODE_SCENE_MISSING = "TIMELINE_SCENE_MISSING"
CODE_ORDER_MISMATCH = "TIMELINE_ORDER_MISMATCH"
CODE_COVERAGE_GAP = "TIMELINE_COVERAGE_GAP"
CODE_COVERAGE_OVERLAP = "TIMELINE_COVERAGE_OVERLAP"
CODE_COVERAGE_FRAME_COUNT = "TIMELINE_COVERAGE_FRAME_COUNT_MISMATCH"
CODE_OCCURRENCE_OUT_OF_RANGE = "TIMELINE_OCCURRENCE_OUT_OF_RANGE"
CODE_SOURCE_GENERATION_MISMATCH = "TIMELINE_SOURCE_GENERATION_MISMATCH"
CODE_TIME_BASE_UNAVAILABLE = "TIMELINE_TIME_BASE_UNAVAILABLE"
CODE_TIME_BASE_MISMATCH = "TIMELINE_TIME_BASE_MISMATCH"
CODE_BOX_MISSING = "OCCURRENCE_GEOMETRY_BOX_MISSING"
CODE_BOX_AMBIGUOUS = "OCCURRENCE_GEOMETRY_AMBIGUOUS"
CODE_GEOMETRY_TAMPERED = "OCCURRENCE_GEOMETRY_TAMPERED"
CODE_REGION_OUT_OF_BOUNDS = "OCCURRENCE_REGION_OUT_OF_BOUNDS"
CODE_REGION_SCALE_UNRESOLVED = "OCCURRENCE_REGION_SCALE_UNRESOLVED"
CODE_DUPLICATE_IDENTITY = "OCCURRENCE_DUPLICATE_IDENTITY"
CODE_ROLE_UNMAPPED = "OCCURRENCE_ROLE_UNMAPPED"
CODE_ROUTE_NOT_EXECUTABLE = "OCCURRENCE_ROUTE_NOT_EXECUTABLE"
#: Consumption-time classification of a pre-timeline v2 authority row.
CODE_LEGACY_AUTHORITY = "LEGACY_AUTHORITY_REAPPROVAL_REQUIRED"
#: Consumption-time structural failure of a present-but-invalid timeline.
CODE_TIMELINE_INVALID = "TIMELINE_AUTHORITY_INVALID"

_EPS = 1e-9


class TimelineAuthorityError(ValueError):
    """Typed fail-closed error for timeline authority work."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def normalize_box(raw: Any) -> list[float] | None:
    """Coerce a persisted box entry to ``[x, y, w, h]`` floats.

    Accepts the canonical ``{"x","y","w","h"}`` dict and 4+-element numeric
    arrays.  Returns ``None`` when the entry is not numeric (caller classifies
    as tampered — never guessed).
    """
    if isinstance(raw, dict):
        try:
            return [
                float(raw["x"]),
                float(raw["y"]),
                float(raw["w"]),
                float(raw["h"]),
            ]
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return [float(v) for v in raw[:4]]
        except (TypeError, ValueError):
            return None
    return None


def select_occurrence_box(
    geometry: dict[str, Any] | None,
) -> tuple[list[float] | None, str | None, str | None]:
    """Select the authoritative box for one occurrence (ruling Q1).

    Precedence across keys is ``segmentation.boxes`` -> ``prompt.boxes``
    (a documented rule, not a guess).  Within a key:
      - 0 boxes -> try the next key; none anywhere -> ``CODE_BOX_MISSING``;
      - >1 box where any two differ -> ``CODE_BOX_AMBIGUOUS`` (deny);
      - all boxes equal -> select the first, provenance ``"<key>.boxes[0]"``;
      - non-numeric entry -> ``CODE_GEOMETRY_TAMPERED``.

    Returns ``(box, geometry_source, error_code)``; ``error_code`` is None on
    success (``box`` may be None only together with ``CODE_BOX_MISSING``).
    """
    if not isinstance(geometry, dict):
        return None, None, CODE_BOX_MISSING
    for key in ("segmentation", "prompt"):
        evidence = geometry.get(key)
        if not isinstance(evidence, dict):
            continue
        boxes = evidence.get("boxes") or []
        if not isinstance(boxes, list) or not boxes:
            continue
        first = normalize_box(boxes[0])
        if first is None:
            return None, None, CODE_GEOMETRY_TAMPERED
        for extra in boxes[1:]:
            nxt = normalize_box(extra)
            if nxt is None:
                return None, None, CODE_GEOMETRY_TAMPERED
            if nxt != first:
                return None, None, CODE_BOX_AMBIGUOUS
        return first, f"{key}.boxes[0]", None
    return None, None, CODE_BOX_MISSING


def derive_region(
    raw_box: list[float] | tuple[float, ...],
    src_w: Any,
    src_h: Any,
) -> tuple[list[float], str]:
    """Dual-mode region derivation (amendment v0.2 §2 — deterministic).

    Mode A (normalized): finite, ``x,y >= 0``, ``w,h > 0``,
    ``x+w <= 1+eps``, ``y+h <= 1+eps`` -> ``region_norm = raw``,
    ``scale_mode = "normalized"``.

    Mode B (pixel): finite, ``x,y >= 0``, ``w,h > 0``, source dims positive,
    the box INTERSECTS the frame (``x < src_w`` and ``y < src_h``) ->
    ``region_norm = [x/sw, y/sh, (x2-x)/sw, (y2-y)/sh]`` with
    ``x2 = min(x+w, src_w)``, ``y2 = min(y+h, src_h)`` (deterministic clip to
    the physical frame; the sanctioned extraction provider persists PADDED
    pixel boxes that may overrun the frame edge, and pixels outside the frame
    do not exist), ``scale_mode = "pixel"``.  A box fully outside the frame
    matches neither mode -> ``OCCURRENCE_REGION_OUT_OF_BOUNDS``.

    Pixel-scale values with dims unavailable ->
    ``OCCURRENCE_REGION_SCALE_UNRESOLVED``.  Matches neither mode ->
    ``OCCURRENCE_REGION_OUT_OF_BOUNDS``.  Raises
    :class:`TimelineAuthorityError`; never guesses.
    """
    if not (
        isinstance(raw_box, (list, tuple))
        and len(raw_box) == 4
        and all(_finite(v) for v in raw_box)
    ):
        raise TimelineAuthorityError(
            CODE_REGION_OUT_OF_BOUNDS, f"box must be 4 finite numbers, got {raw_box!r}"
        )
    x, y, w, h = (float(v) for v in raw_box)
    if (
        x >= 0.0
        and y >= 0.0
        and w > 0.0
        and h > 0.0
        and x + w <= 1.0 + _EPS
        and y + h <= 1.0 + _EPS
    ):
        return [x, y, w, h], "normalized"
    dims_ok = _finite(src_w) and _finite(src_h) and float(src_w) > 0 and float(src_h) > 0
    if dims_ok:
        sw, sh = float(src_w), float(src_h)
        if x >= 0.0 and y >= 0.0 and w > 0.0 and h > 0.0 and x < sw and y < sh:
            x2 = min(x + w, sw)
            y2 = min(y + h, sh)
            return [
                min(x / sw, 1.0),
                min(y / sh, 1.0),
                max(min((x2 - x) / sw, 1.0 - x / sw), 0.0),
                max(min((y2 - y) / sh, 1.0 - y / sh), 0.0),
            ], "pixel"
        raise TimelineAuthorityError(
            CODE_REGION_OUT_OF_BOUNDS,
            f"box {raw_box!r} outside normalized [0,1] and does not intersect "
            f"the {sw}x{sh} frame",
        )
    raise TimelineAuthorityError(
        CODE_REGION_SCALE_UNRESOLVED,
        f"box {raw_box!r} is not normalized and source dims are unavailable "
        "(scale cannot be resolved without guessing)",
    )


def parse_time_base(time_base: Any, fps: Any) -> tuple[int, int]:
    """Exact rational ``(fps_num, fps_den)`` from the producer manifest.

    The producer stamps ``time_base`` as ``"{fps_den}/{fps_num}"``
    (``app/services/structural_lock_producer.py``).  The parse is exact
    integer parsing — no float round-trip — and ``fps`` must equal
    ``fps_num/fps_den`` within 1e-9.  Unprovable -> typed deny (D1 path:
    works against the current producer format and B01's enforcement-only
    fix alike).
    """
    if not isinstance(time_base, str) or time_base.count("/") != 1:
        raise TimelineAuthorityError(
            CODE_TIME_BASE_UNAVAILABLE, f"time_base {time_base!r} is not '<den>/<num>'"
        )
    left, right = time_base.split("/")
    try:
        fps_den = int(left)
        fps_num = int(right)
    except (TypeError, ValueError) as err:
        raise TimelineAuthorityError(
            CODE_TIME_BASE_UNAVAILABLE, f"time_base {time_base!r} has non-int components"
        ) from err
    if fps_num <= 0 or fps_den <= 0:
        raise TimelineAuthorityError(
            CODE_TIME_BASE_UNAVAILABLE,
            f"time_base {time_base!r} must be positive rational components",
        )
    if not _finite(fps):
        raise TimelineAuthorityError(
            CODE_TIME_BASE_UNAVAILABLE, f"fps {fps!r} is not a finite number"
        )
    if abs(float(fps) - (fps_num / fps_den)) > 1e-9:
        raise TimelineAuthorityError(
            CODE_TIME_BASE_MISMATCH,
            f"fps {fps!r} != parsed {fps_num}/{fps_den}",
        )
    return fps_num, fps_den


def validate_partition(
    shots: Any, frame_count: Any
) -> list[str]:
    """Validate the scene-shot partition; returns problem strings ([] = ok).

    Contract §2: strictly increasing, first start == 0, contiguous
    (``cur.start == prev.end + 1``), last ``end + 1 == frame_count``.
    """
    problems: list[str] = []
    if not isinstance(shots, list) or not shots:
        return ["no shots"]
    ordered: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return [f"shot[{index}] must be an object"]
        try:
            start = int(shot["start_frame"])
            end = int(shot["end_frame"])
        except (KeyError, TypeError, ValueError):
            return [f"shot[{index}] missing/invalid frames"]
        ordered.append({"shot_id": str(shot.get("shot_id") or ""), "start_frame": start, "end_frame": end})
    ordered.sort(key=lambda s: (s["start_frame"], s["shot_id"]))
    if ordered[0]["start_frame"] != 0:
        problems.append(f"first shot must start at 0, got {ordered[0]['start_frame']}")
    prev: int | None = None
    for shot in ordered:
        if prev is not None:
            if shot["start_frame"] <= prev:
                problems.append(
                    f"shots overlap or non-monotonic: {shot['shot_id']} starts "
                    f"at {shot['start_frame']} <= previous end {prev}"
                )
            elif shot["start_frame"] != prev + 1:
                problems.append(
                    f"gap between shots: previous ends at {prev}, "
                    f"{shot['shot_id']} starts at {shot['start_frame']}"
                )
        prev = shot["end_frame"]
    if problems:
        return problems
    assert prev is not None
    if not isinstance(frame_count, int) or frame_count < 1:
        problems.append(f"frame_count {frame_count!r} must be int >= 1")
    elif prev + 1 != frame_count:
        problems.append(
            f"coverage mismatch: shots cover {prev + 1} frames, "
            f"frame_count is {frame_count}"
        )
    return problems


def pick_partition_code(problems: list[str]) -> str:
    joined = " ".join(problems)
    if "overlap" in joined:
        return CODE_COVERAGE_OVERLAP
    if "gap" in joined or "start at 0" in joined:
        return CODE_COVERAGE_GAP
    return CODE_COVERAGE_FRAME_COUNT


def validate_timeline_block(
    timeline: Any, *, frame_count: int | None = None
) -> None:
    """Structural validation for CONSUMERS of the frozen timeline block.

    Re-derives every invariant from the stored values (never trusts flags);
    raises :class:`TimelineAuthorityError` with a typed code on any failure.
    """
    if not isinstance(timeline, dict):
        raise TimelineAuthorityError(CODE_TIMELINE_INVALID, "timeline must be an object")
    if timeline.get("timeline_version") != TIMELINE_VERSION:
        raise TimelineAuthorityError(
            CODE_TIMELINE_INVALID,
            f"timeline_version {timeline.get('timeline_version')!r} != {TIMELINE_VERSION!r}",
        )
    tf_frame_count = timeline.get("frame_count")
    if not isinstance(tf_frame_count, int) or tf_frame_count < 1:
        raise TimelineAuthorityError(
            CODE_TIMELINE_INVALID, f"frame_count {tf_frame_count!r} must be int >= 1"
        )
    if frame_count is not None and tf_frame_count != frame_count:
        raise TimelineAuthorityError(
            CODE_COVERAGE_FRAME_COUNT,
            f"timeline frame_count {tf_frame_count} != expected {frame_count}",
        )
    problems = validate_partition(timeline.get("shots"), tf_frame_count)
    if problems:
        raise TimelineAuthorityError(pick_partition_code(problems), "; ".join(problems))
    for key in ("fps_num", "fps_den"):
        value = timeline.get(key)
        if not isinstance(value, int) or value < 1:
            raise TimelineAuthorityError(
                CODE_TIME_BASE_UNAVAILABLE, f"timeline.{key} {value!r} must be int >= 1"
            )
    if timeline.get("cfr") is not True:
        raise TimelineAuthorityError(
            CODE_TIME_BASE_UNAVAILABLE, "timeline.cfr must be true (CFR sources only)"
        )
    occurrences = timeline.get("occurrences")
    if not isinstance(occurrences, list):
        raise TimelineAuthorityError(CODE_TIMELINE_INVALID, "occurrences must be a list")
    seen_layers: set[str] = set()
    for index, occ in enumerate(occurrences):
        if not isinstance(occ, dict):
            raise TimelineAuthorityError(CODE_TIMELINE_INVALID, f"occurrences[{index}] must be an object")
        layer_id = occ.get("layer_id")
        if not isinstance(layer_id, str) or not layer_id:
            raise TimelineAuthorityError(CODE_TIMELINE_INVALID, f"occurrences[{index}].layer_id missing")
        if layer_id in seen_layers:
            raise TimelineAuthorityError(
                CODE_DUPLICATE_IDENTITY, f"duplicate occurrence identity {layer_id!r}"
            )
        seen_layers.add(layer_id)
        start = occ.get("start_frame")
        end = occ.get("end_frame")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end >= tf_frame_count
        ):
            raise TimelineAuthorityError(
                CODE_OCCURRENCE_OUT_OF_RANGE,
                f"occurrence {layer_id!r} range [{start!r},{end!r}] outside [0,{tf_frame_count})",
            )
        region = occ.get("affected_region")
        if not (
            isinstance(region, (list, tuple))
            and len(region) == 4
            and all(_finite(v) for v in region)
        ):
            raise TimelineAuthorityError(
                CODE_REGION_OUT_OF_BOUNDS, f"occurrence {layer_id!r} region must be 4 finite numbers"
            )
        rx, ry, rw, rh = (float(v) for v in region)
        if rx < 0 or ry < 0 or rw <= 0 or rh <= 0 or rx + rw > 1 + _EPS or ry + rh > 1 + _EPS:
            raise TimelineAuthorityError(
                CODE_REGION_OUT_OF_BOUNDS,
                f"occurrence {layer_id!r} region {region!r} outside normalized bounds",
            )
        route = occ.get("route")
        if not isinstance(route, str) or not route:
            raise TimelineAuthorityError(CODE_TIMELINE_INVALID, f"occurrence {layer_id!r} route missing")
