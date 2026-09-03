"""Structural comparison and review-entry gate (S10-T04A-C2).

Pure deterministic compare of rendered full-apply output vs source-locked
manifest.  No DB, no IO, no ambient leakage.  Every check is fail-closed
and every BLOCKED failure carries an actionable pointer
(role/layer/segment/route) plus an explicit reason with thresholds.

Thresholds are frozen per TARGET_PROFILE_2D_SOURCE_LOCKED:

  trajectory median <=0.5%  P95 <=1.0%  of source-frame diagonal
  scale P95 <=3%  rotation P95 <=3 degrees  contact P95 <=1.0% diagonal
  zero z-order inversion, zero unexplained visibility, no silhouette clipping
  exact frame_count, canonical timebase, shot order, cut frames
  missing/empty/NaN, missing annotation or wrong policy -> BLOCK

Measurement method s10-structural-v1 (version "1") — deterministic,
server-derived, per-metric family (exact formula + units + threshold):

  family      units          formula (per persisted evidence row)                threshold
  frame_count frames         len(decode_rgb_frames(publication))                 == manifest frame_count (exact)
  timebase    rational fps   probe_source_timebase(publication)                  == manifest timebase (exact)
  shot_order  ordered ids    chunk core_start_frame boundary order               == manifest shot_order (exact)
  cut_frames  frames         chunk core_start_frame boundaries                   == manifest cut_frames (exact, tol 0)
  trajectory  % of diagonal  hypot(dx,dy)/D*100 per segment_motion row           median <=0.5%  P95 <=1.0%
  scale       %              |s_act - s_exp|/s_exp*100 per motion row            P95 <=3%
  rotation    degrees        |r_act - r_exp| per motion row                      P95 <=3 deg
  contact     % of diagonal  |dist_act - dist_exp|/D*100 per contact row         P95 <=1.0%
  z_order     count          adjacent z decreases ordered by (start_frame,id)    0
  visibility  count          non-visible segments without an occlusion row       0
  clipping    bool           non-source segment mask == source-generation silhouette id   False

  D = hypot(width, height) px (manifest dims, else decoded frame dims).
  Source expectations per segment come from the pinned manifest segments[]
  (anchor/scale/rotation_deg; defaults (0,0)/1.0/0.0).  Rendered motion,
  contact, z-order, visibility and clipping are measured from persisted
  segment_motion.transform_json, scene_graph_contact,
  occurrence_segment(z_order, visibility, mask_artifact_id) and
  scene_graph_occlusion rows — the renderer's durable output evidence.
  Source and rendered authorities are INDEPENDENT: rendered values are never
  mirrored into source.  Any required authority missing/empty/NaN, policy
  mismatch, decode/hash/size mismatch or unsupported measurement => BLOCKED.
  Cryptographic hashes prove identity/integrity only and never substitute for
  geometric/temporal measurement.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CONTACT_P95_MAX_PCT",
    "CUT_DRIFT_TOLERANCE_FRAMES",
    "MEASUREMENT_METHOD",
    "MEASUREMENT_VERSION",
    "REQUIRED_ANNOTATIONS",
    "ROTATION_P95_MAX_DEG",
    "SCALE_P95_MAX_PCT",
    "TRAJECTORY_MEDIAN_MAX_PCT",
    "TRAJECTORY_P95_MAX_PCT",
    "VISIBILITY_MAX",
    "Z_ORDER_MAX",
    "S10StructuralCompareError",
    "S10StructuralCompareService",
    "S10StructuralEvidenceError",
    "ServerDerivedCompareInput",
    "ServerDerivedCompareResult",
    "StructuralCompareResult",
    "StructuralFailure",
    "build_server_derived_result",
    "expected_components",
    "expected_segment_for_frame",
    "hash_canonical",
    "measure_contact_error_pct",
    "measure_rotation_error_deg",
    "measure_scale_error_pct",
    "measure_trajectory_error_pct",
    "transform_components",
    "transform_parse",
]

# ── Frozen thresholds (TARGET_PROFILE §8) ──────────────────────────────────

TRAJECTORY_MEDIAN_MAX_PCT = 0.5
TRAJECTORY_P95_MAX_PCT = 1.0
SCALE_P95_MAX_PCT = 3.0
ROTATION_P95_MAX_DEG = 3.0
CONTACT_P95_MAX_PCT = 1.0
Z_ORDER_MAX = 0
VISIBILITY_MAX = 0
CUT_DRIFT_TOLERANCE_FRAMES = 0  # exact cut frame required (TARGET: <=1 frame is hard gate, T04A uses 0 for binary)

REQUIRED_ANNOTATIONS = ("shot_order", "cut_frames", "z_order", "visibility")

MEASUREMENT_METHOD = "s10-structural-v1"
MEASUREMENT_VERSION = "1"

# ── Errors ───────────────────────────────────────────────────────────────────

class S10StructuralCompareError(ValueError):
    """Fail-closed compare error (bad input shape, not a gate failure)."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_nan(v: Any) -> bool:
    if isinstance(v, float):
        return math.isnan(v) or math.isinf(v)
    return False


def _has_nan(values: Any) -> bool:
    if isinstance(values, (list, tuple)):
        for x in values:
            if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
                return True
            if isinstance(x, dict):
                for vv in x.values():
                    if isinstance(vv, float) and (math.isnan(vv) or math.isinf(vv)):
                        return True
            if isinstance(x, (list, tuple)) and _has_nan(x):
                return True
    elif isinstance(values, float) and (math.isnan(values) or math.isinf(values)):
        return True
    return False


def _median(values: list[float]) -> float:
    if not values:
        raise S10StructuralCompareError("median of empty list")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        raise S10StructuralCompareError("percentile of empty list")
    if not (0 <= p <= 100):
        raise S10StructuralCompareError("percentile p must be 0..100")
    s = sorted(values)
    n = len(s)
    # nearest-rank method: ceil(p/100 * n) - 1  (1-indexed)
    k = math.ceil(p / 100.0 * n)
    idx = max(0, min(n - 1, k - 1))
    return float(s[idx])


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, (list, tuple, dict, str)) and len(value) == 0)


def _pointer_from_context(ctx: dict[str, Any] | None) -> dict[str, str]:
    base = {"role": "unknown", "layer": "unknown", "segment": "unknown", "route": "unknown"}
    if ctx:
        for k in ("role", "layer", "segment", "route"):
            if k in ctx and isinstance(ctx[k], str) and ctx[k]:
                base[k] = str(ctx[k])
    return base


def _fmt_pointer(ptr: dict[str, str]) -> str:
    return f"role={ptr['role']} layer={ptr['layer']} segment={ptr['segment']} route={ptr['route']}"


# ── Deterministic measurement primitives (s10-structural-v1) ────────────────
# Pure functions the server-side gate uses to turn persisted evidence into the
# per-metric error series.  All formulas/units are documented in the module
# docstring.  Unsupported measurement raises S10StructuralEvidenceError so
# the caller BLOCKs instead of guessing.

def _as_float(value: Any, default: float) -> float:
    """Coerce a value to finite float with an explicit default."""
    if value is None or isinstance(value, bool):
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def transform_parse(raw: str | None) -> dict[str, Any]:
    """Parse a persisted ``segment_motion.transform_json`` (fail-closed).

    Empty/whitespace blob is treated as identity (``{}``).  A blob that is
    not a JSON object is an unsupported measurement and raises.
    """
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return {}
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - any malformed blob is unsupported
        raise S10StructuralEvidenceError(
            f"segment_motion.transform_json is not valid JSON (unsupported measurement): {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise S10StructuralEvidenceError(
            "segment_motion.transform_json is not a JSON object (unsupported measurement)"
        )
    return dict(parsed)


def transform_components(transform: dict[str, Any]) -> tuple[float, float, float, float, float]:
    """Deterministic components of a transform dict.

    Returns ``(tx, ty, scale, rotation_deg, contact_offset)`` with documented
    defaults: translate (0,0), scale 1.0, rotation 0 deg, contact offset 0 px.
    Scale accepts a scalar or a ``{"x": .., "y": ..}`` dict (uniform mean).
    """
    tr = transform.get("translate")
    tx = _as_float(tr.get("x") if isinstance(tr, dict) else None, 0.0)
    ty = _as_float(tr.get("y") if isinstance(tr, dict) else None, 0.0)
    s = transform.get("scale")
    if isinstance(s, dict):
        sx = _as_float(s.get("x"), 1.0)
        sy = _as_float(s.get("y"), 1.0)
        scale = (sx + sy) / 2.0
    else:
        scale = _as_float(s, 1.0)
    rot = _as_float(transform.get("rotation_deg"), 0.0)
    co = _as_float(transform.get("contact_offset"), 0.0)
    return tx, ty, scale, rot, co


def expected_components(seg: dict[str, Any] | None) -> tuple[float, float, float, float]:
    """Source-expected ``(anchor_x, anchor_y, scale, rotation_deg)`` for a
    pinned-manifest segment.  Defaults: anchor (0,0), scale 1.0, rotation 0 deg.
    """
    if not isinstance(seg, dict):
        return 0.0, 0.0, 1.0, 0.0
    anc = seg.get("anchor")
    if not isinstance(anc, dict):
        return 0.0, 0.0, 1.0, 0.0
    ex = _as_float(anc.get("x"), 0.0)
    ey = _as_float(anc.get("y"), 0.0)
    s_exp = _as_float(seg.get("scale"), 1.0)
    r_exp = _as_float(seg.get("rotation_deg"), 0.0)
    return ex, ey, s_exp, r_exp


def expected_segment_for_frame(segments: list[dict[str, Any]] | None, frame: int) -> dict[str, Any] | None:
    """Pick the pinned-manifest segment covering ``frame`` (last with
    start_frame <= frame), else None (identity expectations apply)."""
    if not segments:
        return None
    cand: dict[str, Any] | None = None
    for s in segments:
        if not isinstance(s, dict):
            continue
        try:
            sf = int(s.get("start_frame", 0))
        except (TypeError, ValueError):
            continue
        if sf <= frame:
            cand = s
    return cand


def _require_diagonal(diagonal: float) -> float:
    if not math.isfinite(diagonal) or diagonal <= 0.0:
        raise S10StructuralEvidenceError(
            "frame diagonal must be finite and positive (unsupported measurement)"
        )
    return float(diagonal)


def measure_trajectory_error_pct(transform: dict[str, Any], seg: dict[str, Any] | None, diagonal: float) -> float:
    """Trajectory error = |applied translate - expected anchor| / D * 100 (% of diagonal)."""
    d = _require_diagonal(diagonal)
    tx, ty, _, _, _ = transform_components(transform)
    ex, ey, _, _ = expected_components(seg)
    return math.hypot(tx - ex, ty - ey) / d * 100.0


def measure_scale_error_pct(transform: dict[str, Any], seg: dict[str, Any] | None, diagonal: float) -> float:
    """Scale error = |applied scale - expected scale| / expected scale * 100 (%)."""
    _require_diagonal(diagonal)
    _, _, scale, _, _ = transform_components(transform)
    _, _, s_exp, _ = expected_components(seg)
    if s_exp <= 0.0:
        raise S10StructuralEvidenceError(
            "expected scale must be positive (unsupported scale measurement)"
        )
    return abs(scale - s_exp) / s_exp * 100.0


def measure_rotation_error_deg(transform: dict[str, Any], seg: dict[str, Any] | None) -> float:
    """Rotation error = |applied rotation - expected rotation| (degrees)."""
    _, _, _, rot, _ = transform_components(transform)
    _, _, _, r_exp = expected_components(seg)
    return abs(rot - r_exp)


def measure_contact_error_pct(
    transform_src: dict[str, Any],
    transform_tgt: dict[str, Any],
    seg_src: dict[str, Any] | None,
    seg_tgt: dict[str, Any] | None,
    diagonal: float,
) -> float:
    """Contact error = |dist(actual anchors) - dist(expected anchors)| / D * 100 (%)."""
    d = _require_diagonal(diagonal)
    ax, ay, _, _, _ = transform_components(transform_src)
    bx, by, _, _, _ = transform_components(transform_tgt)
    eax, eay, _, _ = expected_components(seg_src)
    ebx, eby, _, _ = expected_components(seg_tgt)
    dist_act = math.hypot(ax - bx, ay - by)
    dist_exp = math.hypot(eax - ebx, eay - eby)
    return abs(dist_act - dist_exp) / d * 100.0


# ── Result datatypes ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StructuralFailure:
    code: str
    reason: str
    role: str = "unknown"
    layer: str = "unknown"
    segment: str = "unknown"
    route: str = "unknown"
    metric: str = ""
    value: Any = None
    threshold: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "role": self.role,
            "layer": self.layer,
            "segment": self.segment,
            "route": self.route,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class StructuralCompareResult:
    status: str  # REVIEW_REQUIRED or BLOCKED
    passed: bool
    failures: tuple[StructuralFailure, ...] = field(default_factory=tuple)
    checks: dict[str, Any] = field(default_factory=dict)
    policy_version: str | None = None
    expected_policy_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "failures": [f.to_dict() for f in self.failures],
            "checks": dict(self.checks),
            "policy_version": self.policy_version,
            "expected_policy_version": self.expected_policy_version,
        }


# ── Service ─────────────────────────────────────────────────────────────────

class S10StructuralCompareService:
    """Deterministic structural compare gate.

    Inputs are plain dicts/lists; no DB.  All thresholds are frozen and
    compared exactly.  Any missing/empty/NaN -> BLOCKED.  Policy mismatch ->
    BLOCKED.  Annotation missing -> BLOCKED.  Every BLOCKED failure carries
    an explicit reason and an actionable pointer (role/layer/segment/route).
    """

    def __init__(
        self,
        *,
        trajectory_median_max: float = TRAJECTORY_MEDIAN_MAX_PCT,
        trajectory_p95_max: float = TRAJECTORY_P95_MAX_PCT,
        scale_p95_max: float = SCALE_P95_MAX_PCT,
        rotation_p95_max: float = ROTATION_P95_MAX_DEG,
        contact_p95_max: float = CONTACT_P95_MAX_PCT,
        expected_policy_version: str | None = None,
    ) -> None:
        self.trajectory_median_max = float(trajectory_median_max)
        self.trajectory_p95_max = float(trajectory_p95_max)
        self.scale_p95_max = float(scale_p95_max)
        self.rotation_p95_max = float(rotation_p95_max)
        self.contact_p95_max = float(contact_p95_max)
        self.expected_policy_version_default = expected_policy_version

    # ── public compare ───────────────────────────────────────────────────────

    def compare(
        self,
        *,
        source_frame_count: int | None = None,
        rendered_frame_count: int | None = None,
        source_fps_num: int | None = None,
        source_fps_den: int | None = None,
        rendered_fps_num: int | None = None,
        rendered_fps_den: int | None = None,
        source_shot_order: list[str] | None = None,
        rendered_shot_order: list[str] | None = None,
        source_cut_frames: list[int] | None = None,
        rendered_cut_frames: list[int] | None = None,
        trajectory_errors: list[float] | None = None,
        scale_errors: list[float] | None = None,
        rotation_errors: list[float] | None = None,
        contact_errors: list[float] | None = None,
        z_order_inversions: int | None = None,
        visibility_events: int | None = None,
        clipping_via_silhouette_reuse: bool | None = None,
        policy_version: str | None = None,
        expected_policy_version: str | None = None,
        annotations: dict[str, Any] | None = None,
        required_annotations: tuple[str, ...] | list[str] | None = None,
        context: dict[str, Any] | None = None,
        source_width: int | None = None,
        source_height: int | None = None,
        # loose dict passthrough for caller convenience (source_manifest style)
        source_manifest: dict[str, Any] | None = None,
        rendered_manifest: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> StructuralCompareResult:
        """Run every required check and gate to REVIEW_REQUIRED or BLOCKED.

        Accepts either flat kwargs or dict wrappers.  Flat kwargs take
        precedence over dict-wrapped values.  Missing/empty/NaN always BLOCKS.
        """

        # ── normalize dict wrappers ──────────────────────────────────────────
        if source_manifest is not None:
            if source_frame_count is None and "frame_count" in source_manifest:
                source_frame_count = source_manifest.get("frame_count")
            if source_fps_num is None and "fps_num" in source_manifest:
                source_fps_num = source_manifest.get("fps_num")
            if source_fps_den is None and "fps_den" in source_manifest:
                source_fps_den = source_manifest.get("fps_den")
            if source_shot_order is None and "shot_order" in source_manifest:
                source_shot_order = source_manifest.get("shot_order")
            if source_cut_frames is None and "cut_frames" in source_manifest:
                source_cut_frames = source_manifest.get("cut_frames")
            if policy_version is None and "policy_version" in source_manifest:
                policy_version = source_manifest.get("policy_version")
            if source_width is None and "width" in source_manifest:
                source_width = source_manifest.get("width")
            if source_height is None and "height" in source_manifest:
                source_height = source_manifest.get("height")

        if rendered_manifest is not None:
            if rendered_frame_count is None and "frame_count" in rendered_manifest:
                rendered_frame_count = rendered_manifest.get("frame_count")
            if rendered_fps_num is None and "fps_num" in rendered_manifest:
                rendered_fps_num = rendered_manifest.get("fps_num")
            if rendered_fps_den is None and "fps_den" in rendered_manifest:
                rendered_fps_den = rendered_manifest.get("fps_den")
            if rendered_shot_order is None and "shot_order" in rendered_manifest:
                rendered_shot_order = rendered_manifest.get("shot_order")
            if rendered_cut_frames is None and "cut_frames" in rendered_manifest:
                rendered_cut_frames = rendered_manifest.get("cut_frames")

        if metrics is not None:
            if trajectory_errors is None and "trajectory_errors" in metrics:
                trajectory_errors = metrics.get("trajectory_errors")
            if scale_errors is None and "scale_errors" in metrics:
                scale_errors = metrics.get("scale_errors")
            if rotation_errors is None and "rotation_errors" in metrics:
                rotation_errors = metrics.get("rotation_errors")
            if contact_errors is None and "contact_errors" in metrics:
                contact_errors = metrics.get("contact_errors")
            if z_order_inversions is None and "z_order_inversions" in metrics:
                z_order_inversions = metrics.get("z_order_inversions")
            if visibility_events is None and "visibility_events" in metrics:
                visibility_events = metrics.get("visibility_events")
            if clipping_via_silhouette_reuse is None and "clipping_via_silhouette_reuse" in metrics:
                clipping_via_silhouette_reuse = metrics.get("clipping_via_silhouette_reuse")

        exp_policy = expected_policy_version if expected_policy_version is not None else self.expected_policy_version_default
        req_ann = tuple(required_annotations) if required_annotations is not None else REQUIRED_ANNOTATIONS
        ptr_base = _pointer_from_context(context)

        failures: list[StructuralFailure] = []
        checks: dict[str, Any] = {}

        def _fail(code: str, reason: str, metric: str = "", value: Any = None, threshold: Any = None, ctx: dict[str, Any] | None = None) -> None:
            p = _pointer_from_context(ctx if ctx is not None else context)
            failures.append(
                StructuralFailure(
                    code=code,
                    reason=f"{reason} [{_fmt_pointer(p)}]",
                    role=p["role"],
                    layer=p["layer"],
                    segment=p["segment"],
                    route=p["route"],
                    metric=metric,
                    value=value,
                    threshold=threshold,
                )
            )

        # ── 1) frame_count exact ─────────────────────────────────────────────
        if _is_missing(source_frame_count) or _is_missing(rendered_frame_count):
            _fail("FRAME_COUNT_MISSING", "frame_count missing (source or rendered is None/empty)", metric="frame_count", value={"source": source_frame_count, "rendered": rendered_frame_count})
            checks["frame_count"] = "BLOCKED_MISSING"
        elif _is_nan(source_frame_count) or _is_nan(rendered_frame_count):
            _fail("FRAME_COUNT_NAN", "frame_count is NaN/Inf", metric="frame_count", value={"source": source_frame_count, "rendered": rendered_frame_count})
            checks["frame_count"] = "BLOCKED_NAN"
        elif not isinstance(source_frame_count, int) or not isinstance(rendered_frame_count, int):
            _fail("FRAME_COUNT_TYPE", "frame_count must be int", metric="frame_count", value={"source": source_frame_count, "rendered": rendered_frame_count})
            checks["frame_count"] = "BLOCKED_TYPE"
        elif source_frame_count != rendered_frame_count:
            _fail(
                "FRAME_COUNT_MISMATCH",
                f"frame_count mismatch: source={source_frame_count} rendered={rendered_frame_count}",
                metric="frame_count",
                value={"source": source_frame_count, "rendered": rendered_frame_count},
                threshold=source_frame_count,
            )
            checks["frame_count"] = "BLOCKED_MISMATCH"
        else:
            checks["frame_count"] = "PASS"

        # ── 2) timebase (fps_num/fps_den) exact ──────────────────────────────
        tb_missing = any(_is_missing(v) for v in (source_fps_num, source_fps_den, rendered_fps_num, rendered_fps_den))
        if tb_missing:
            _fail("TIMEBASE_MISSING", "timebase missing (fps_num/fps_den is None/empty)", metric="timebase", value={"source": (source_fps_num, source_fps_den), "rendered": (rendered_fps_num, rendered_fps_den)})
            checks["timebase"] = "BLOCKED_MISSING"
        elif any(_is_nan(v) for v in (source_fps_num, source_fps_den, rendered_fps_num, rendered_fps_den)):
            _fail("TIMEBASE_NAN", "timebase contains NaN/Inf", metric="timebase", value={"source": (source_fps_num, source_fps_den), "rendered": (rendered_fps_num, rendered_fps_den)})
            checks["timebase"] = "BLOCKED_NAN"
        elif (source_fps_num, source_fps_den) != (rendered_fps_num, rendered_fps_den):
            _fail(
                "TIMEBASE_MISMATCH",
                f"timebase mismatch: source={source_fps_num}/{source_fps_den} rendered={rendered_fps_num}/{rendered_fps_den}",
                metric="timebase",
                value={"source": (source_fps_num, source_fps_den), "rendered": (rendered_fps_num, rendered_fps_den)},
                threshold=(source_fps_num, source_fps_den),
            )
            checks["timebase"] = "BLOCKED_MISMATCH"
        else:
            checks["timebase"] = "PASS"

        # ── 3) shot order exact ──────────────────────────────────────────────
        if _is_missing(source_shot_order) or _is_missing(rendered_shot_order):
            _fail("SHOT_ORDER_MISSING", "shot_order missing (None/empty)", metric="shot_order", value={"source": source_shot_order, "rendered": rendered_shot_order})
            checks["shot_order"] = "BLOCKED_MISSING"
        elif not isinstance(source_shot_order, list) or not isinstance(rendered_shot_order, list):
            _fail("SHOT_ORDER_TYPE", "shot_order must be list[str]", metric="shot_order", value={"source": source_shot_order, "rendered": rendered_shot_order})
            checks["shot_order"] = "BLOCKED_TYPE"
        elif _has_nan(source_shot_order) or _has_nan(rendered_shot_order):
            _fail("SHOT_ORDER_NAN", "shot_order contains NaN/Inf", metric="shot_order")
            checks["shot_order"] = "BLOCKED_NAN"
        elif list(source_shot_order) != list(rendered_shot_order):
            _fail(
                "SHOT_ORDER_MISMATCH",
                f"shot_order mismatch: source={source_shot_order!r} rendered={rendered_shot_order!r}",
                metric="shot_order",
                value={"source": source_shot_order, "rendered": rendered_shot_order},
            )
            checks["shot_order"] = "BLOCKED_MISMATCH"
        else:
            checks["shot_order"] = "PASS"

        # ── 4) cut frames exact ──────────────────────────────────────────────
        if _is_missing(source_cut_frames) or _is_missing(rendered_cut_frames):
            _fail("CUT_FRAMES_MISSING", "cut_frames missing (None/empty)", metric="cut_frames", value={"source": source_cut_frames, "rendered": rendered_cut_frames})
            checks["cut_frames"] = "BLOCKED_MISSING"
        elif not isinstance(source_cut_frames, list) or not isinstance(rendered_cut_frames, list):
            _fail("CUT_FRAMES_TYPE", "cut_frames must be list[int]", metric="cut_frames")
            checks["cut_frames"] = "BLOCKED_TYPE"
        elif _has_nan(source_cut_frames) or _has_nan(rendered_cut_frames):
            _fail("CUT_FRAMES_NAN", "cut_frames contains NaN/Inf", metric="cut_frames")
            checks["cut_frames"] = "BLOCKED_NAN"
        elif len(source_cut_frames) != len(rendered_cut_frames):
            _fail(
                "CUT_FRAME_COUNT_MISMATCH",
                f"cut frame count mismatch: source len {len(source_cut_frames)} vs rendered len {len(rendered_cut_frames)}",
                metric="cut_frames",
                value={"source_len": len(source_cut_frames), "rendered_len": len(rendered_cut_frames)},
            )
            checks["cut_frames"] = "BLOCKED_MISMATCH"
        else:
            drift = [abs(int(a) - int(b)) for a, b in zip(source_cut_frames, rendered_cut_frames)]
            max_drift = max(drift) if drift else 0
            if max_drift > CUT_DRIFT_TOLERANCE_FRAMES:
                # find first drifting index for actionable pointer
                first_idx = next(i for i, d in enumerate(drift) if d > CUT_DRIFT_TOLERANCE_FRAMES)
                ctx_cut = {"role": ptr_base["role"], "layer": ptr_base["layer"], "segment": f"cut_{first_idx}", "route": ptr_base["route"]}
                _fail(
                    "CUT_DRIFT",
                    f"cut frame drift {max_drift} at index {first_idx}: source={source_cut_frames[first_idx]} rendered={rendered_cut_frames[first_idx]} (tolerance {CUT_DRIFT_TOLERANCE_FRAMES})",
                    metric="cut_frames",
                    value={"drift": max_drift, "source": source_cut_frames, "rendered": rendered_cut_frames},
                    threshold=CUT_DRIFT_TOLERANCE_FRAMES,
                    ctx=ctx_cut,
                )
                checks["cut_frames"] = "BLOCKED_DRIFT"
            else:
                checks["cut_frames"] = "PASS"

        # ── 5) trajectory median + P95 ────────────────────────────────────────
        if _is_missing(trajectory_errors):
            _fail("TRAJECTORY_MISSING", "trajectory_errors missing/empty", metric="trajectory_median")
            checks["trajectory"] = "BLOCKED_MISSING"
        elif _has_nan(trajectory_errors):
            _fail("TRAJECTORY_NAN", "trajectory_errors contains NaN/Inf", metric="trajectory_median", value=trajectory_errors)
            checks["trajectory"] = "BLOCKED_NAN"
        elif not isinstance(trajectory_errors, list):
            _fail("TRAJECTORY_TYPE", "trajectory_errors must be list[float]", metric="trajectory_median")
            checks["trajectory"] = "BLOCKED_TYPE"
        else:
            vals = [float(x) for x in trajectory_errors]
            med = _median(vals)
            p95 = _percentile(vals, 95)
            checks["trajectory_median"] = med
            checks["trajectory_p95"] = p95
            if med > self.trajectory_median_max:
                _fail(
                    "TRAJECTORY_MEDIAN_EXCEEDED",
                    f"trajectory median {med:.4f}% > {self.trajectory_median_max}% threshold",
                    metric="trajectory_median",
                    value=med,
                    threshold=self.trajectory_median_max,
                )
                checks["trajectory"] = "BLOCKED_MEDIAN"
            elif p95 > self.trajectory_p95_max:
                _fail(
                    "TRAJECTORY_P95_EXCEEDED",
                    f"trajectory P95 {p95:.4f}% > {self.trajectory_p95_max}% threshold",
                    metric="trajectory_p95",
                    value=p95,
                    threshold=self.trajectory_p95_max,
                )
                checks["trajectory"] = "BLOCKED_P95"
            else:
                checks["trajectory"] = "PASS"

        # ── 6) scale P95 ─────────────────────────────────────────────────────
        if _is_missing(scale_errors):
            _fail("SCALE_MISSING", "scale_errors missing/empty", metric="scale_p95")
            checks["scale"] = "BLOCKED_MISSING"
        elif _has_nan(scale_errors):
            _fail("SCALE_NAN", "scale_errors contains NaN/Inf", metric="scale_p95", value=scale_errors)
            checks["scale"] = "BLOCKED_NAN"
        elif not isinstance(scale_errors, list):
            _fail("SCALE_TYPE", "scale_errors must be list[float]", metric="scale_p95")
            checks["scale"] = "BLOCKED_TYPE"
        else:
            vals = [float(x) for x in scale_errors]
            p95 = _percentile(vals, 95)
            checks["scale_p95"] = p95
            if p95 > self.scale_p95_max:
                _fail(
                    "SCALE_P95_EXCEEDED",
                    f"scale P95 {p95:.4f}% > {self.scale_p95_max}% threshold",
                    metric="scale_p95",
                    value=p95,
                    threshold=self.scale_p95_max,
                )
                checks["scale"] = "BLOCKED_P95"
            else:
                checks["scale"] = "PASS"

        # ── 7) rotation P95 ──────────────────────────────────────────────────
        if _is_missing(rotation_errors):
            _fail("ROTATION_MISSING", "rotation_errors missing/empty", metric="rotation_p95")
            checks["rotation"] = "BLOCKED_MISSING"
        elif _has_nan(rotation_errors):
            _fail("ROTATION_NAN", "rotation_errors contains NaN/Inf", metric="rotation_p95", value=rotation_errors)
            checks["rotation"] = "BLOCKED_NAN"
        elif not isinstance(rotation_errors, list):
            _fail("ROTATION_TYPE", "rotation_errors must be list[float]", metric="rotation_p95")
            checks["rotation"] = "BLOCKED_TYPE"
        else:
            vals = [float(x) for x in rotation_errors]
            p95 = _percentile(vals, 95)
            checks["rotation_p95"] = p95
            if p95 > self.rotation_p95_max:
                _fail(
                    "ROTATION_P95_EXCEEDED",
                    f"rotation P95 {p95:.4f} deg > {self.rotation_p95_max} deg threshold",
                    metric="rotation_p95",
                    value=p95,
                    threshold=self.rotation_p95_max,
                )
                checks["rotation"] = "BLOCKED_P95"
            else:
                checks["rotation"] = "PASS"

        # ── 8) contact P95 ───────────────────────────────────────────────────
        if _is_missing(contact_errors):
            _fail("CONTACT_MISSING", "contact_errors missing/empty", metric="contact_p95")
            checks["contact"] = "BLOCKED_MISSING"
        elif _has_nan(contact_errors):
            _fail("CONTACT_NAN", "contact_errors contains NaN/Inf", metric="contact_p95", value=contact_errors)
            checks["contact"] = "BLOCKED_NAN"
        elif not isinstance(contact_errors, list):
            _fail("CONTACT_TYPE", "contact_errors must be list[float]", metric="contact_p95")
            checks["contact"] = "BLOCKED_TYPE"
        else:
            vals = [float(x) for x in contact_errors]
            p95 = _percentile(vals, 95)
            checks["contact_p95"] = p95
            if p95 > self.contact_p95_max:
                _fail(
                    "CONTACT_P95_EXCEEDED",
                    f"contact P95 {p95:.4f}% > {self.contact_p95_max}% threshold",
                    metric="contact_p95",
                    value=p95,
                    threshold=self.contact_p95_max,
                )
                checks["contact"] = "BLOCKED_P95"
            else:
                checks["contact"] = "PASS"

        # ── 9) z-order inversion ──────────────────────────────────────────────
        if z_order_inversions is None:
            _fail("Z_ORDER_MISSING", "z_order_inversions missing (None)", metric="z_order_inversions")
            checks["z_order"] = "BLOCKED_MISSING"
        elif _is_nan(z_order_inversions):
            _fail("Z_ORDER_NAN", "z_order_inversions is NaN/Inf", metric="z_order_inversions", value=z_order_inversions)
            checks["z_order"] = "BLOCKED_NAN"
        elif not isinstance(z_order_inversions, int):
            _fail("Z_ORDER_TYPE", "z_order_inversions must be int", metric="z_order_inversions", value=z_order_inversions)
            checks["z_order"] = "BLOCKED_TYPE"
        elif z_order_inversions > Z_ORDER_MAX:
            _fail(
                "Z_ORDER_INVERSION",
                f"z-order inversion count {z_order_inversions} > {Z_ORDER_MAX} (zero tolerance)",
                metric="z_order_inversions",
                value=z_order_inversions,
                threshold=Z_ORDER_MAX,
            )
            checks["z_order"] = "BLOCKED_INVERSION"
        else:
            checks["z_order"] = "PASS"

        # ── 10) visibility ───────────────────────────────────────────────────
        if visibility_events is None:
            _fail("VISIBILITY_MISSING", "visibility_events missing (None)", metric="visibility_events")
            checks["visibility"] = "BLOCKED_MISSING"
        elif _is_nan(visibility_events):
            _fail("VISIBILITY_NAN", "visibility_events is NaN/Inf", metric="visibility_events", value=visibility_events)
            checks["visibility"] = "BLOCKED_NAN"
        elif not isinstance(visibility_events, int):
            _fail("VISIBILITY_TYPE", "visibility_events must be int", metric="visibility_events", value=visibility_events)
            checks["visibility"] = "BLOCKED_TYPE"
        elif visibility_events > VISIBILITY_MAX:
            _fail(
                "VISIBILITY_UNEXPLAINED",
                f"unexplained visibility events {visibility_events} > {VISIBILITY_MAX} (zero tolerance)",
                metric="visibility_events",
                value=visibility_events,
                threshold=VISIBILITY_MAX,
            )
            checks["visibility"] = "BLOCKED_UNEXPLAINED"
        else:
            checks["visibility"] = "PASS"

        # ── 11) clipping via silhouette reuse ────────────────────────────────
        if clipping_via_silhouette_reuse is None:
            _fail("CLIPPING_MISSING", "clipping_via_silhouette_reuse missing (None)", metric="clipping_via_silhouette_reuse")
            checks["clipping"] = "BLOCKED_MISSING"
        elif not isinstance(clipping_via_silhouette_reuse, bool):
            _fail("CLIPPING_TYPE", "clipping_via_silhouette_reuse must be bool", metric="clipping_via_silhouette_reuse", value=clipping_via_silhouette_reuse)
            checks["clipping"] = "BLOCKED_TYPE"
        elif clipping_via_silhouette_reuse is True:
            _fail(
                "CLIPPING_SILHOUETTE_REUSE",
                "source-silhouette clipping detected (reusing source silhouette as replacement silhouette) — must be zero",
                metric="clipping_via_silhouette_reuse",
                value=True,
                threshold=False,
            )
            checks["clipping"] = "BLOCKED_CLIPPING"
        else:
            checks["clipping"] = "PASS"

        # ── 12) policy version ────────────────────────────────────────────────
        if exp_policy is not None:
            if _is_missing(policy_version):
                _fail("POLICY_VERSION_MISSING", "policy_version missing (None/empty) while expected is set", metric="policy_version", value=policy_version, threshold=exp_policy)
                checks["policy_version"] = "BLOCKED_MISSING"
            elif not isinstance(policy_version, str):
                _fail("POLICY_VERSION_TYPE", "policy_version must be str", metric="policy_version", value=policy_version)
                checks["policy_version"] = "BLOCKED_TYPE"
            elif policy_version != exp_policy:
                _fail(
                    "POLICY_VERSION_MISMATCH",
                    f"policy_version mismatch: got {policy_version!r} expected {exp_policy!r}",
                    metric="policy_version",
                    value=policy_version,
                    threshold=exp_policy,
                )
                checks["policy_version"] = "BLOCKED_MISMATCH"
            else:
                checks["policy_version"] = "PASS"
        else:
            checks["policy_version"] = "SKIPPED_NO_EXPECTED"

        # ── 13) required annotations ─────────────────────────────────────────
        if annotations is None:
            _fail("ANNOTATIONS_MISSING", "annotations missing (None)", metric="annotations")
            checks["annotations"] = "BLOCKED_MISSING"
        elif not isinstance(annotations, dict):
            _fail("ANNOTATIONS_TYPE", "annotations must be dict", metric="annotations", value=annotations)
            checks["annotations"] = "BLOCKED_TYPE"
        else:
            missing_keys: list[str] = []
            for k in req_ann:
                v = annotations.get(k)
                if v is None or (isinstance(v, (list, dict, str)) and len(v) == 0):
                    missing_keys.append(k)
                elif (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) or (isinstance(v, list) and _has_nan(v)):
                    missing_keys.append(f"{k}:NaN")
            if missing_keys:
                _fail(
                    "ANNOTATION_MISSING",
                    f"missing required annotation(s): {missing_keys!r}",
                    metric="annotations",
                    value=missing_keys,
                )
                checks["annotations"] = "BLOCKED_MISSING_KEYS"
            else:
                checks["annotations"] = "PASS"

        # ── 14) generic missing/NaN metric guard (defensive) ─────────────────
        # already covered per-metric above; keep checks dict complete
        # ── final gate ───────────────────────────────────────────────────────
        passed = len(failures) == 0
        status = "REVIEW_REQUIRED" if passed else "BLOCKED"
        return StructuralCompareResult(
            status=status,
            passed=passed,
            failures=tuple(failures),
            checks=checks,
            policy_version=policy_version if isinstance(policy_version, str) else None,
            expected_policy_version=exp_policy,
        )

    # ── convenience: compare from manifests + metrics dicts ─────────────────

    def compare_manifests(
        self,
        source_manifest: dict[str, Any],
        rendered_manifest: dict[str, Any],
        metrics: dict[str, Any],
        annotations: dict[str, Any] | None = None,
        expected_policy_version: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> StructuralCompareResult:
        return self.compare(
            source_manifest=source_manifest,
            rendered_manifest=rendered_manifest,
            metrics=metrics,
            annotations=annotations,
            expected_policy_version=expected_policy_version,
            context=context,
        )


# ── Server-derived layer (S10-T04A-C1) ───────────────────────────────────


class S10StructuralEvidenceError(ValueError):
    """Server evidence missing/tampered/undecodable — fail-closed BLOCK."""


@dataclass(frozen=True)
class ServerDerivedCompareInput:
    source_manifest: dict[str, Any]
    source_manifest_hash: str
    policy_version: str
    rendered_frame_count: int
    rendered_fps_num: int
    rendered_fps_den: int
    rendered_shot_order: list[str] | None
    rendered_cut_frames: list[int] | None
    trajectory_errors: list[float] | None
    scale_errors: list[float] | None
    rotation_errors: list[float] | None
    contact_errors: list[float] | None
    z_order_inversions: int | None
    visibility_events: int | None
    clipping_via_silhouette_reuse: bool | None
    annotations: dict[str, Any] | None
    rendered_sha256: str
    rendered_size_bytes: int
    decoded_frame_count: int
    publication_id: str
    publication_content_hash: str
    evidence_hashes: dict[str, str]
    measurement_method: str = MEASUREMENT_METHOD
    measurement_version: str = MEASUREMENT_VERSION


@dataclass(frozen=True)
class ServerDerivedCompareResult:
    result: StructuralCompareResult
    input_hashes: dict[str, str]
    rendered_sha256: str
    rendered_size_bytes: int
    publication_content_hash: str
    policy_version: str
    source_manifest_hash: str
    measurement_method: str = MEASUREMENT_METHOD
    measurement_version: str = MEASUREMENT_VERSION
    evidence_hashes: dict[str, str] = field(default_factory=dict)
    decoded_frame_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = self.result.to_dict()
        d["input_hashes"] = dict(self.input_hashes)
        d["rendered_sha256"] = self.rendered_sha256
        d["rendered_size_bytes"] = self.rendered_size_bytes
        d["publication_content_hash"] = self.publication_content_hash
        d["source_manifest_hash"] = self.source_manifest_hash
        d["measurement_method"] = self.measurement_method
        d["measurement_version"] = self.measurement_version
        d["evidence_hashes"] = dict(self.evidence_hashes)
        d["decoded_frame_count"] = self.decoded_frame_count
        return d


def hash_canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def expected_publication_lineage_hash(
    run_id: str, artifact_sha256: str, natural_key: str | None
) -> str | None:
    """Return the lineage content_hash a publication MUST have to bind its artifact.

    Producer contract (unchanged, S10-T01A):
    - FullApply publications (natural_key is NULL):
      content_hash = sha256("pub:{run_id}:{artifact_sha256}")
    - Partial-recompute publications (natural_key "recompute-pub:{run_id}:{correction_id}"):
      content_hash = sha256("pub-recompute:{run_id}:{correction_id}:{artifact_sha256}")

    content_hash is a LINEAGE key (UniqueConstraint(run_id, content_hash) +
    lineage dedupe), NOT a raw file digest — the artifact's own sha256 is
    verified against the managed file separately.  Returns None when
    provenance cannot be resolved (unknown natural_key pattern, malformed
    recompute key, or embedded run_id not matching the row) so the caller
    fails closed.
    """
    sha = str(artifact_sha256)
    if natural_key:
        nk = str(natural_key)
        if nk.startswith("recompute-pub:"):
            parts = nk.split(":", 2)
            if len(parts) >= 3 and parts[1] == str(run_id) and parts[2]:
                correction_id = parts[2]
                return hashlib.sha256(
                    f"pub-recompute:{run_id}:{correction_id}:{sha}".encode()
                ).hexdigest()
            return None  # malformed/foreign recompute provenance -> fail closed
        return None  # unknown provenance -> fail closed
    return hashlib.sha256(f"pub:{run_id}:{sha}".encode()).hexdigest()


def build_server_derived_result(
    inp: ServerDerivedCompareInput,
    *,
    expected_policy_version: str | None = None,
    context: dict[str, Any] | None = None,
) -> ServerDerivedCompareResult:
    svc = S10StructuralCompareService(
        expected_policy_version=expected_policy_version or inp.policy_version
    )
    src = dict(inp.source_manifest)
    # C2: Derive source timebase ONLY from pinned manifest timebase, never
    # from rendered.  Mirroring rendered fps into source is a placeholder.
    if "fps_num" not in src and "fps_den" not in src:
        tb = src.get("timebase")
        if isinstance(tb, dict) and "fps" in tb:
            try:
                fps_val = float(tb["fps"])
                if fps_val == 30.0:
                    src["fps_num"] = 30
                    src["fps_den"] = 1
                else:
                    src["fps_num"] = int(round(fps_val * 1000))
                    src["fps_den"] = 1000
            except Exception:
                pass
        # If manifest has no timebase, source fps remains missing -> BLOCKED
        # via TIMEBASE_MISSING. Never mirror rendered fps into source.
    # C4: Source cut_frames derive ONLY from persisted source manifest
    # evidence: explicit cut_frames when present, otherwise interior segment
    # start_frame boundaries (>0) from manifest segments.  Rendered cuts are
    # NEVER mirrored into source — the two authorities remain independent.
    # When no source authority exists the value stays missing and the gate
    # BLOCKs with CUT_FRAMES_MISSING (fail-closed).
    if "cut_frames" not in src or not isinstance(src.get("cut_frames"), list) or len(src.get("cut_frames") or []) == 0:
        segs = src.get("segments")
        if isinstance(segs, list) and len(segs) > 0:
            _seg_starts = sorted({int(s.get("start_frame", 0)) for s in segs if isinstance(s, dict) and int(s.get("start_frame", 0)) > 0})
            if _seg_starts:
                src["cut_frames"] = _seg_starts
            # single segment at 0 => no interior cut -> leave missing -> BLOCKED
    rend = {
        "frame_count": inp.rendered_frame_count,
        "fps_num": inp.rendered_fps_num,
        "fps_den": inp.rendered_fps_den,
        "shot_order": list(inp.rendered_shot_order) if inp.rendered_shot_order is not None else None,
        "cut_frames": list(inp.rendered_cut_frames) if inp.rendered_cut_frames is not None else inp.rendered_cut_frames,
    }
    # C3: metrics may be None (missing authority -> BLOCKED fail-closed)
    metrics = {
        "trajectory_errors": list(inp.trajectory_errors) if inp.trajectory_errors is not None else None,
        "scale_errors": list(inp.scale_errors) if inp.scale_errors is not None else None,
        "rotation_errors": list(inp.rotation_errors) if inp.rotation_errors is not None else None,
        "contact_errors": list(inp.contact_errors) if inp.contact_errors is not None else None,
        "z_order_inversions": inp.z_order_inversions,
        "visibility_events": inp.visibility_events,
        "clipping_via_silhouette_reuse": inp.clipping_via_silhouette_reuse,
    }
    result = svc.compare(
        source_manifest=src,
        rendered_manifest=rend,
        metrics=metrics,
        annotations=dict(inp.annotations) if inp.annotations is not None else None,
        policy_version=inp.policy_version,
        expected_policy_version=expected_policy_version or inp.policy_version,
        context=context,
    )
    input_hashes = {
        "source_manifest": inp.source_manifest_hash,
        "source_policy": hash_canonical(inp.policy_version),
        "rendered_sha256": inp.rendered_sha256,
        "publication_content_hash": inp.publication_content_hash,
        "evidence": hash_canonical(inp.evidence_hashes),
        "metrics": hash_canonical(metrics),
        "annotations": hash_canonical(inp.annotations),
    }
    return ServerDerivedCompareResult(
        result=result,
        input_hashes=input_hashes,
        rendered_sha256=inp.rendered_sha256,
        rendered_size_bytes=inp.rendered_size_bytes,
        publication_content_hash=inp.publication_content_hash,
        policy_version=inp.policy_version,
        source_manifest_hash=inp.source_manifest_hash,
        measurement_method=inp.measurement_method,
        measurement_version=inp.measurement_version,
        evidence_hashes=dict(inp.evidence_hashes),
        decoded_frame_count=int(inp.decoded_frame_count),
    )

