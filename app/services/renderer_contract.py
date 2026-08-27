"""Renderer router CONTRACT (S09-T00-I02) — TARGET_PROFILE §4 P0-7 + §10.

This module is the stable vocabulary of the adaptive 2D renderer router:

- failure taxonomy (stable string codes + one exception type per code);
- frozen dataclasses for RenderRequest / RenderResult / CapabilityDescriptor /
  RouteProvenance;
- the ``BackendAdapter`` protocol every renderer backend implements;
- the license gate for any checkpoint/model/backend entering the product path.

Hard rules (TASK.md S09-T00-I02):
- FAIL CLOSED: unknown backend / unknown capability / missing license /
  below-threshold benchmark are RAISED, never silently routed around.
- No silent fallback: a result may only ever come from a backend bound to the
  exact route the request asked for.
- NC/no-permission checkpoints are refused in the product path (overlay §10).
- No heavy imports at module level (stdlib only: dataclasses/enums/json/pathlib
  /typing/datetime) so importing the contract never pulls cv2/torch/sqlalchemy.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: Re-exported single authority for the five canonical routes.  Imported from
#: the ORM constants so the taxonomy is never duplicated (I01 ownership).
from app.persistence.models import RENDERER_ROUTES

RendererRoute = str  # constrained at runtime to RENDERER_ROUTES values

__all__ = [
    "AffectedRegion",
    "AffineKeyframe",
    "BACKEND_LICENSE_REGISTRY",
    "BenchmarkBelowThresholdError",
    "BackendBinaryMissingError",
    "BackendAdapter",
    "CapabilityDescriptor",
    "CapabilityMismatchError",
    "LayerOrderEntry",
    "LicenseMissingError",
    "PROVENANCE_REQUIRED_FIELDS",
    "PoseSwapEntry",
    "RenderRequest",
    "RenderResult",
    "RendererContractCode",
    "RendererRouterError",
    "ReplacementAsset",
    "ROUTE_PRIORITY",
    "RouteProvenance",
    "SourceTimebase",
    "UnknownBackendError",
    "UnknownCapabilityError",
    "utc_now_iso",
    "validate_license_for_product_use",
]


# ── Failure taxonomy ──────────────────────────────────────────────────────────


class RendererContractCode(str, Enum):
    """Stable failure-taxonomy codes (wire format — never rename values)."""

    UNKNOWN_BACKEND = "unknown_backend"
    UNKNOWN_CAPABILITY = "unknown_capability"
    LICENSE_MISSING = "license_missing"
    CAPABILITY_MISMATCH = "capability_mismatch"
    BENCHMARK_BELOW_THRESHOLD = "benchmark_below_threshold"
    BACKEND_BINARY_MISSING = "backend_binary_missing"
    INVALID_REQUEST = "invalid_request"


class RendererRouterError(Exception):
    """Base error carrying the stable taxonomy code."""

    def __init__(self, code: RendererContractCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


#: The five provenance fields TASK.md requires on every escalation event.
PROVENANCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "route_from",
    "route_to",
    "metric_name",
    "metric_value",
    "threshold",
)


class UnknownBackendError(RendererRouterError):
    """Named backend/route target is not in the registry — fail closed."""

    def __init__(self, detail: str) -> None:
        super().__init__(RendererContractCode.UNKNOWN_BACKEND, detail)


class UnknownCapabilityError(RendererRouterError):
    """No AVAILABLE backend serves the requested route — fail closed."""

    def __init__(self, detail: str) -> None:
        super().__init__(RendererContractCode.UNKNOWN_CAPABILITY, detail)


class LicenseMissingError(RendererRouterError):
    """License gate failed: unapproved, unknown or NC/no-permission license."""

    def __init__(self, detail: str) -> None:
        super().__init__(RendererContractCode.LICENSE_MISSING, detail)


class CapabilityMismatchError(RendererRouterError):
    """Request/escalation contradicts the declared capability matrix."""

    def __init__(self, detail: str) -> None:
        super().__init__(RendererContractCode.CAPABILITY_MISMATCH, detail)


class BenchmarkBelowThresholdError(RendererRouterError):
    """Measured structural/runtime metric is worse than the required gate."""

    def __init__(self, detail: str) -> None:
        super().__init__(RendererContractCode.BENCHMARK_BELOW_THRESHOLD, detail)


class BackendBinaryMissingError(RendererRouterError):
    """Backend binary/driver probe failed — adapter refuses to run."""

    def __init__(self, detail: str) -> None:
        super().__init__(RendererContractCode.BACKEND_BINARY_MISSING, detail)


# ── Route priority (TARGET_PROFILE §8 reference-specific priority) ───────────


#: Escalation ladder, cheapest/most-deterministic first (overlay §8).  An
#: escalation may jump FORWARD any number of steps but never backward.
ROUTE_PRIORITY: tuple[RendererRoute, ...] = RENDERER_ROUTES


def _route_rank(route: RendererRoute) -> int:
    try:
        return ROUTE_PRIORITY.index(route)
    except ValueError as err:  # pragma: no cover - defensive
        raise CapabilityMismatchError(f"unknown route {route!r}") from err


# ── Frozen dataclasses ────────────────────────────────────────────────────────


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── S09-T02-C1: typed replacement/reskin contract ────────────────────────────
#
# F1 correction: a render request must carry the FULL reskin contract —
# source, replacement asset(s) or pose-state assets, alpha/mask, normalized
# anchor, frame range, pose schedule / affine keyframes, output — and every
# boundary must be validated FAIL-CLOSED before any adapter runs.


def _require_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CapabilityMismatchError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise CapabilityMismatchError(
            f"{name} must be finite, got {value!r}"
        )
    return number


@dataclass(frozen=True)
class ReplacementAsset:
    """A typed replacement layer pinned to the workspace media root.

    ``path`` MUST be inside ``workspace_root`` (path-containment, fail-closed);
    ``kind`` selects the compositing semantics; ``alpha_mode`` decides how the
    asset's own alpha interacts with the destination region.
    """

    path: Path
    kind: str = "sprite"  # sprite | pose_state | mask_overlay
    alpha_mode: str = "straight"  # straight | premultiplied | opaque

    def __post_init__(self) -> None:
        p = self.path
        if not isinstance(p, Path):
            raise CapabilityMismatchError(
                f"replacement asset path must be a Path, got {type(p)}"
            )
        if self.kind not in ("sprite", "pose_state", "mask_overlay"):
            raise CapabilityMismatchError(
                f"replacement kind {self.kind!r} not in "
                "(sprite|pose_state|mask_overlay)"
            )
        if self.alpha_mode not in ("straight", "premultiplied", "opaque"):
            raise CapabilityMismatchError(
                f"alpha_mode {self.alpha_mode!r} not in "
                "(straight|premultiplied|opaque)"
            )


@dataclass(frozen=True)
class PoseSwapEntry:
    """One scheduled pose/expression swap on the canonical timebase."""

    frame: int
    state_id: str  # e.g. "head_closed_rep"
    asset: ReplacementAsset

    def __post_init__(self) -> None:
        if isinstance(self.frame, bool) or not isinstance(self.frame, int):
            raise CapabilityMismatchError(
                f"pose swap frame must be an int, got {self.frame!r}"
            )
        if self.frame < 0:
            raise CapabilityMismatchError(
                f"pose swap frame must be >= 0, got {self.frame}"
            )
        state = self.state_id
        if not isinstance(state, str) or not state.strip():
            raise CapabilityMismatchError("pose swap state_id must be non-empty")


@dataclass(frozen=True)
class AffineKeyframe:
    """One affine keyframe for the replacement layer (NOT the source frame).

    All values are finite floats; translation is normalized to frame units,
    scale/rotation are absolute layer transforms anchored at ``anchor``.
    """

    frame: int
    translation_xy: tuple[float, float] = (0.0, 0.0)
    scale: float = 1.0
    rotation_deg: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.frame, bool) or not isinstance(self.frame, int) \
                or self.frame < 0:
            raise CapabilityMismatchError(
                f"affine keyframe frame must be a non-negative int, "
                f"got {self.frame!r}"
            )
        t = self.translation_xy
        if (
            not isinstance(t, tuple)
            or len(t) != 2
        ):
            raise CapabilityMismatchError(
                "translation_xy must be a (x, y) tuple of numbers"
            )
        _require_finite(t[0], "translation_xy.x")
        _require_finite(t[1], "translation_xy.y")
        _require_finite(self.scale, "scale")
        if self.scale <= 0.0:
            raise CapabilityMismatchError(
                f"scale must be positive, got {self.scale!r}"
            )
        _require_finite(self.rotation_deg, "rotation_deg")


@dataclass(frozen=True)
class AffectedRegion:
    """The region a route may change — everything OUTSIDE stays bit-stable.

    ``bbox_xywh_norm`` is in [0,1] normalized coordinates of the source
    frame.  A None region means the whole frame is affected.
    """

    bbox_xywh_norm: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        bbox = self.bbox_xywh_norm
        if bbox is None:
            return
        if not isinstance(bbox, tuple) or len(bbox) != 4:
            raise CapabilityMismatchError(
                "affected region must be a (x, y, w, h) tuple"
            )
        vals = [
            _require_finite(v, f"affected_region[{i}]")
            for i, v in enumerate(bbox)
        ]
        x, y, w, h = vals
        if min(x, y, w, h) < 0.0 or x + w > 1.0 + 1e-9 or y + h > 1.0 + 1e-9:
            raise CapabilityMismatchError(
                f"affected region must lie inside [0,1]^2, got {vals!r}"
            )
        if w <= 0.0 or h <= 0.0:
            raise CapabilityMismatchError(
                f"affected region width/height must be positive, got {vals!r}"
            )


@dataclass(frozen=True)
class SourceTimebase:
    """Rational source fps/timebase of the INPUT media (S09-T02-C2, F5).

    The output MUST preserve the source timebase exactly — no retime to a
    canonical fps.  ``fps_num/fps_den`` is the rational frame rate (e.g.
    30000/1001 for 29.97, 24000/1001 for 23.976, 24/1, 30/1);
    ``time_base`` is the container time base as ``num/den`` (e.g. "1/15360")
    and is provenance-only metadata.  ``fps_exact`` exposes the exact
    Fraction for math without float drift.
    """

    fps_num: int
    fps_den: int
    time_base: str = "1/30000"

    def __post_init__(self) -> None:
        if isinstance(self.fps_num, bool) or not isinstance(self.fps_num, int):
            raise CapabilityMismatchError(
                f"fps_num must be an int, got {self.fps_num!r}"
            )
        if isinstance(self.fps_den, bool) or not isinstance(self.fps_den, int):
            raise CapabilityMismatchError(
                f"fps_den must be an int, got {self.fps_den!r}"
            )
        if self.fps_num <= 0 or self.fps_den <= 0:
            raise CapabilityMismatchError(
                f"source fps must be positive rational, got "
                f"{self.fps_num}/{self.fps_den}"
            )
        ratio = Fraction(self.fps_num, self.fps_den)
        if ratio < Fraction(1, 1000) or ratio > Fraction(1000, 1):
            raise CapabilityMismatchError(
                f"source fps out of bounds (0.001..1000): {ratio}"
            )
        tb = self.time_base
        if not isinstance(tb, str) or "/" not in tb:
            raise CapabilityMismatchError(
                f"time_base must be 'num/den', got {tb!r}"
            )
        try:
            tn, td = tb.split("/", 1)
            tbn, tbd = int(tn), int(td)
        except ValueError as err:
            raise CapabilityMismatchError(
                f"time_base not parseable as 'num/den': {tb!r}"
            ) from err
        if tbn <= 0 or tbd <= 0:
            raise CapabilityMismatchError(
                f"time_base must be positive, got {tb!r}"
            )

    @property
    def fps_exact(self) -> Fraction:
        return Fraction(self.fps_num, self.fps_den)

    @property
    def fps_float(self) -> float:
        return self.fps_num / self.fps_den


@dataclass(frozen=True)
class LayerOrderEntry:
    """Per-frame layer ordering / occlusion directive (S09-T02-C2, F5).

    Represents ``f5_group_occlusion`` WITHOUT special fixture branches:
    a replacement layer is placed at an integer z-depth relative to the
    occluders named in ``request.occluder_assets``.  Semantics executed by
    the compositor:

    - z > 0 → replacement draws AFTER (on top of) those occluders;
    - z < 0 → occluders draw on top of the replacement (occlusion);
    - z == 0 → undefined order, refused at validation.

    ``frame_from``/``frame_to`` are INCLUSIVE bounds inside the render range;
    entries may overlap — later entries win for overlapping frames per layer.
    """

    frame_from: int
    frame_to: int
    layer_id: str = "replacement"
    z: int = 0

    def __post_init__(self) -> None:
        for name in ("frame_from", "frame_to"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise CapabilityMismatchError(
                    f"{name} must be an int, got {value!r}"
                )
        if self.frame_from < 0 or self.frame_to < self.frame_from:
            raise CapabilityMismatchError(
                "need 0 <= frame_from <= frame_to, got "
                f"{self.frame_from}..{self.frame_to}"
            )
        if not isinstance(self.layer_id, str) or not self.layer_id.strip():
            raise CapabilityMismatchError("layer_id must be non-empty")
        if isinstance(self.z, bool) or not isinstance(self.z, int):
            raise CapabilityMismatchError(f"z must be an int, got {self.z!r}")
        if self.z == 0:
            raise CapabilityMismatchError(
                "z must be non-zero (0 = ambiguous draw order)"
            )


@dataclass(frozen=True)
class RenderRequest:
    """One bounded render ask, pinned to an occurrence-segment frame range.

    S09-T02-C1 (F1): the request carries the FULL typed reskin contract.
    Every field is boundary-validated in :meth:`validate_for_render` —
    adapters call it BEFORE any encode/composite work (fail BEFORE success).
    """

    request_id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    occurrence_segment_id: str
    route: RendererRoute
    start_frame: int
    end_frame: int
    #: Explicit backend choice (Demo-review override); None = router default.
    backend_override: str | None = None
    #: Structural gates the SELECTED route must meet (fail-closed benchmark
    #: thresholds, e.g. {"runtime_ms_per_frame": 120.0}).
    max_runtime_ms_per_frame: float | None = None
    #: Real media paths for adapters that encode (benchmark/production alike).
    input_media: Path | None = None
    output_media: Path | None = None

    # ── C1 replacement contract ───────────────────────────────────────────
    #: Workspace media root; every asset/mask path MUST live inside it.
    workspace_root: Path | None = None
    #: Replacement layer for sprite_affine / whole-segment reskins.
    replacement_asset: ReplacementAsset | None = None
    #: Pose/expression state assets for pose_swap (state_id → asset).
    pose_state_assets: dict[str, ReplacementAsset] | None = None
    #: Scheduled swaps on the canonical timebase (frame → state_id).
    pose_schedule: tuple[PoseSwapEntry, ...] | None = None
    #: Affine keyframes of the REPLACEMENT layer (sprite_affine).
    affine_keyframes: tuple[AffineKeyframe, ...] | None = None
    #: Normalized anchor [0,1]^2 the layer is pinned to.
    anchor_xy_norm: tuple[float, float] | None = None
    #: Alpha/mask limiting WHERE the replacement may change pixels.  A mask
    #: PNG's alpha channel multiplies the replacement layer.
    mask_asset: ReplacementAsset | None = None
    #: The region routes may change; outside stays source-stable.
    affected_region: AffectedRegion | None = None

    # ── C2 timebase + layer ordering contract ─────────────────────────────
    #: Rational source fps/timebase; output preserves it EXACTLY (no retime
    #: to a canonical fps).  Required for any encode-backed render.  A plain
    #: ``(num, den)`` tuple is accepted and coerced in __post_init__.
    source_timebase: SourceTimebase | (tuple[int, int] | None) = None
    #: Occluder layers (f5_group_occlusion): typed replacement assets drawn
    #: BETWEEN the source and the replacement layer according to the z-order
    #: directives in ``layer_order``.  No special fixture branch needed —
    #: plain public request fields.
    occluder_assets: dict[str, ReplacementAsset] | None = None
    #: Per-occluder placement rect (J1-C2-v2): ``name -> (x, y, w, h)`` in
    #: NORMALIZED frame units.  When declared for an occluder, that layer is
    #: drawn ONLY inside its sub-rect (stretched to it) — the replacement
    #: layer stays free-roam everywhere else.  Occluders WITHOUT a region
    #: keep the legacy behavior (full-frame cover when bbox is None,
    #: affected-region stretch otherwise).  Fail-closed: unknown names,
    #: out-of-bounds or non-finite values are refused before any artifact.
    occluder_regions: dict[str, tuple[float, float, float, float]] | None = None
    #: Per-frame layer ordering/occlusion (z>0: replacement above the named
    #: occluders, z<0: below).  Empty/None = no occluder semantics.
    layer_order: tuple[LayerOrderEntry, ...] | None = None
    #: Typed identity declaration (C2): an EMPTY keyframe track means the
    #: replacement layer is composited with NO transform.  Replaces the old
    #: ``request_id.endswith("@identity")`` control — request IDs never
    #: change business behavior.
    identity_transform: bool = False

    def __post_init__(self) -> None:
        if self.route not in ROUTE_PRIORITY:
            raise CapabilityMismatchError(
                f"route must be one of {ROUTE_PRIORITY}, got {self.route!r}"
            )
        if self.start_frame < 0 or self.end_frame < self.start_frame:
            raise CapabilityMismatchError(
                "need 0 <= start_frame <= end_frame, got "
                f"{self.start_frame}..{self.end_frame}"
            )
        # C2: identity declaration only pairs with an EMPTY keyframe track —
        # a non-empty track plus identity_transform=True is contradictory.
        if self.identity_transform and self.affine_keyframes:
            raise CapabilityMismatchError(
                "identity_transform=True requires affine_keyframes=() "
                "(no transform), got a non-empty keyframe track"
            )
        # C2: layer-order entries must be typed LayerOrderEntry instances
        # (fail closed on untyped tuples/dicts at the boundary).
        for entry in self.layer_order or ():
            if not isinstance(entry, LayerOrderEntry):
                raise CapabilityMismatchError(
                    f"layer_order entries must be LayerOrderEntry, got "
                    f"{entry!r}"
                )

    # ── fail-closed boundary validation (F1) ──────────────────────────────

    def validate_for_render(self) -> None:
        """Full fail-closed validation of the reskin contract.

        Raises CapabilityMismatchError (stable taxonomy code) on ANY
        violation: missing required fields, path escape from the workspace
        root, missing files on disk, frame order, anchor bounds, NaN/Inf,
        schedule/keyframe inconsistencies, unsupported media containers.
        Adapters MUST call this before producing any output artifact.
        """
        if self.input_media is None or self.output_media is None:
            raise CapabilityMismatchError(
                "input_media and output_media are required to render"
            )
        if self.workspace_root is None:
            raise CapabilityMismatchError(
                "workspace_root is required to contain replacement assets"
            )
        root = Path(self.workspace_root).resolve()
        if not root.is_dir():
            raise CapabilityMismatchError(
                f"workspace_root does not exist: {root}"
            )

        def _contain(p_raw: Path, what: str) -> Path:
            p = Path(p_raw)
            try:
                resolved = p.resolve(strict=False)
                resolved.relative_to(root)
            except ValueError as err:
                raise CapabilityMismatchError(
                    f"{what} escapes workspace_root ({root}): {p}"
                ) from err
            return resolved

        src = _contain(self.input_media, "input_media")
        out = _contain(self.output_media, "output_media")
        if not src.is_file():
            raise CapabilityMismatchError(f"input_media missing: {src}")
        if src.suffix.lower() not in (".mp4", ".mov", ".mkv", ".avi"):
            raise CapabilityMismatchError(
                f"unsupported input media container: {src.suffix!r}"
            )
        # C2 (F5): the output must be a REAL separate artifact — never an
        # in-place overwrite of the source — and must use a supported
        # container so downstream decoders can read it.
        if out.resolve(strict=False) == src.resolve(strict=False):
            raise CapabilityMismatchError(
                f"output_media must differ from input_media ({src})"
            )
        if out.suffix.lower() not in (".mp4", ".mov", ".mkv", ".avi"):
            raise CapabilityMismatchError(
                f"unsupported output media container: {out.suffix!r}"
            )

        # C2 (F5): exact source fps/timebase is REQUIRED — encode keeps it.
        if self.source_timebase is None:
            raise CapabilityMismatchError(
                "source_timebase is required (rational fps/timebase "
                "preservation is part of the render contract)"
            )
        # Ergonomic coercion: accept a plain (num, den) pair.
        if isinstance(self.source_timebase, (tuple, list)):
            num, den = self.source_timebase
            object.__setattr__(
                self,
                "source_timebase",
                SourceTimebase(fps_num=int(num), fps_den=int(den)),
            )

        assets: list[ReplacementAsset] = []
        if self.replacement_asset is not None:
            assets.append(self.replacement_asset)
        if self.mask_asset is not None:
            assets.append(self.mask_asset)
        assets.extend((self.pose_state_assets or {}).values())
        for asset in assets:
            resolved = _contain(asset.path, "asset")
            if not resolved.is_file():
                raise CapabilityMismatchError(f"asset file missing: {resolved}")

        if self.anchor_xy_norm is not None:
            ax, ay = self.anchor_xy_norm
            _require_finite(ax, "anchor_x")
            _require_finite(ay, "anchor_y")
            if not (0.0 <= float(ax) <= 1.0 and 0.0 <= float(ay) <= 1.0):
                raise CapabilityMismatchError(
                    f"anchor must lie in [0,1]^2, got "
                    f"({ax!r}, {ay!r})"
                )

        if self.pose_state_assets and not self.pose_schedule:
            raise CapabilityMismatchError(
                "pose_state_assets provided without a pose_schedule"
            )
        if self.pose_schedule:
            if not self.pose_state_assets:
                raise CapabilityMismatchError(
                    "pose_schedule references states but no pose_state_assets"
                )
            unknown_states = [
                entry.state_id
                for entry in self.pose_schedule
                if entry.state_id not in (self.pose_state_assets or {})
            ]
            if unknown_states:
                raise CapabilityMismatchError(
                    f"pose_schedule references unknown state_ids: "
                    f"{sorted(set(unknown_states))}"
                )
            for entry in self.pose_schedule:
                if not (
                    self.start_frame <= entry.frame <= self.end_frame
                ):
                    raise CapabilityMismatchError(
                        f"pose swap at frame {entry.frame} outside render "
                        f"range {self.start_frame}..{self.end_frame}"
                    )

        if self.affine_keyframes:
            frames = [kf.frame for kf in self.affine_keyframes]
            if frames != sorted(frames):
                raise CapabilityMismatchError(
                    "affine_keyframes must be sorted by frame ascending"
                )
            for kf in self.affine_keyframes:
                if not (
                    self.start_frame <= kf.frame <= self.end_frame
                ):
                    raise CapabilityMismatchError(
                        f"affine keyframe at frame {kf.frame} outside render "
                        f"range {self.start_frame}..{self.end_frame}"
                    )
            if self.anchor_xy_norm is None:
                raise CapabilityMismatchError(
                    "affine_keyframes require a normalized anchor_xy_norm"
                )

        if (
            self.route == "pose_swap"
            and not self.pose_schedule
        ):
            raise CapabilityMismatchError(
                "pose_swap requires a pose_schedule with pose_state_assets"
            )
        if (
            self.route == "sprite_affine"
            and self.replacement_asset is None
        ):
            raise CapabilityMismatchError(
                "sprite_affine requires a replacement_asset"
            )

        # ── C2: occluder / layer-order validation (f5_group_occlusion) ────
        if self.layer_order and not self.occluder_assets:
            raise CapabilityMismatchError(
                "layer_order provided without occluder_assets — z ordering "
                "needs layers to order against"
            )
        if self.occluder_assets:
            if not self.layer_order:
                raise CapabilityMismatchError(
                    "occluder_assets provided without layer_order — "
                    "occlusion semantics need explicit per-frame z orders"
                )
            for name, asset in self.occluder_assets.items():
                resolved = _contain(asset.path, f"occluder {name!r}")
                if not resolved.is_file():
                    raise CapabilityMismatchError(
                        f"occluder asset missing: {resolved}"
                    )
                if asset.kind != "sprite":
                    raise CapabilityMismatchError(
                        f"occluder {name!r} must be kind='sprite', got "
                        f"{asset.kind!r}"
                    )
            order_entries = self.layer_order or ()
            for order_entry in order_entries:
                if order_entry.frame_to < self.start_frame or (
                    order_entry.frame_from > self.end_frame
                ):
                    raise CapabilityMismatchError(
                        f"layer_order entry {order_entry.frame_from}.."
                        f"{order_entry.frame_to} outside render range "
                        f"{self.start_frame}..{self.end_frame}"
                    )
        # ── J1-C2-v2: per-occluder placement rects (fail-closed) ─────────
        for name, rect in (self.occluder_regions or {}).items():
            if not self.occluder_assets or name not in self.occluder_assets:
                raise CapabilityMismatchError(
                    f"occluder region {name!r} has no matching "
                    "occluder_assets entry"
                )
            rx, ry, rw, rh = rect
            _require_finite(rx, f"occluder_region[{name!r}].x")
            _require_finite(ry, f"occluder_region[{name!r}].y")
            _require_finite(rw, f"occluder_region[{name!r}].w")
            _require_finite(rh, f"occluder_region[{name!r}].h")
            if rw <= 0.0 or rh <= 0.0:
                raise CapabilityMismatchError(
                    f"occluder_region[{name!r}] needs positive w/h, got "
                    f"{rw}x{rh}"
                )
            if rx < 0.0 or ry < 0.0 or rx + rw > 1.0 or ry + rh > 1.0:
                raise CapabilityMismatchError(
                    f"occluder_region[{name!r}] {rx},{ry},{rw}x{rh} outside "
                    "the normalized frame bounds [0,1]"
                )
        # Output parent must exist or be creatable INSIDE the root.
        out.parent.mkdir(parents=True, exist_ok=True)

    def timebase(self) -> SourceTimebase:
        """The validated rational timebase (coerced from a tuple if needed).

        Adapters MUST use this accessor instead of touching the raw union
        field — after :meth:`validate_for_render` the coercion guarantees a
        real :class:`SourceTimebase`.
        """
        tb = self.source_timebase
        if isinstance(tb, SourceTimebase):
            return tb
        raise CapabilityMismatchError(
            "source_timebase is required (rational fps/timebase "
            "preservation is part of the render contract)"
        )


@dataclass(frozen=True)
class CapabilityDescriptor:
    """What a backend CAN do right now — measured, not assumed."""

    backend_id: str
    route: RendererRoute
    available: bool
    license_id: str
    #: Measured encoding cost (ms per output frame) — None until benched.
    runtime_ms_per_frame: float | None = None
    #: Peak VRAM bytes observed while serving the route (None if CPU-only).
    vram_bytes: int | None = None
    #: Where the numbers came from: measured_live | probed_config | declared.
    evidence_source: str = "declared"
    measured_at_utc: str | None = None
    #: When ``available`` is False, the EXACT taxonomy code explaining why
    #: (e.g. "backend_binary_missing"); lets gates re-raise the precise
    #: failure type instead of a generic unknown_capability.
    unavailable_reason_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_source not in ("measured_live", "probed_config", "declared"):
            raise CapabilityMismatchError(
                f"evidence_source must be measured_live|probed_config|declared, "
                f"got {self.evidence_source!r}"
            )
        if self.available and self.unavailable_reason_code is not None:
            raise CapabilityMismatchError(
                "available capability must not carry unavailable_reason_code"
            )


@dataclass(frozen=True)
class RouteProvenance:
    """Why a segment escalated from one route to another (§4 P0-7 audit)."""

    segment_id: str
    route_from: RendererRoute
    route_to: RendererRoute
    metric_name: str
    metric_value: float
    threshold: float
    evidence_artifact_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "renderer_route_escalation",
            "segment_id": self.segment_id,
            "route_from": self.route_from,
            "route_to": self.route_to,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "evidence_artifact_path": self.evidence_artifact_path,
            "recorded_at_utc": utc_now_iso(),
        }

    def write_evidence(self, extra: dict[str, Any] | None = None) -> Path:
        """Persist the JSON evidence artifact; returns its path."""
        path = Path(self.evidence_artifact_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        if extra:
            payload["extra"] = extra
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )
        return path


@dataclass(frozen=True)
class RenderResult:
    """Outcome of one adapter.render() call."""

    request_id: str
    route: RendererRoute
    backend_id: str
    ok: bool
    frames_rendered: int
    wall_time_ms: float
    output_media: Path | None = None
    error_code: RendererContractCode | None = None
    error_detail: str | None = None


@runtime_checkable
class BackendAdapter(Protocol):
    """Every renderer backend plugs in through this surface."""

    @property
    def backend_id(self) -> str: ...

    @property
    def route(self) -> RendererRoute: ...

    def capability(self) -> CapabilityDescriptor: ...

    def render(self, request: RenderRequest) -> RenderResult: ...


# ── License gate (TARGET_PROFILE overlay §10) ────────────────────────────────

#: Licenses approved for the PRODUCT path (code + checkpoint distribution).
#: Anything absent here is refused; NC/research-only entries are listed in
#: FORBIDDEN_PRODUCT_LICENSES and can never be re-added silently.
BACKEND_LICENSE_REGISTRY: dict[str, dict[str, str]] = {
    "ffmpeg-lgpl": {
        "spdx": "LGPL-2.1-or-later",
        "subject": "FFmpeg (LGPL build)",
        "product_use": "approved",
    },
    "ffmpeg-gpl-build": {
        "spdx": "GPL-2.0-or-later",
        "subject": "FFmpeg (GPL --enable-gpl/--enable-version3 build; local "
        "use, redistribution requires GPL compliance)",
        "product_use": "approved-local-use",
    },
    "nvidia-nvenc-runtime": {
        "spdx": "NVIDIA-driver-bundled",
        "subject": "NVENC encoder runtime (driver-provided, not "
        "redistributed by MotionForge)",
        "product_use": "approved-local-use",
    },
}

#: Overlay §10 — never ship in the product path regardless of registry edits.
FORBIDDEN_PRODUCT_LICENSES: tuple[str, ...] = (
    "CC-BY-NC-4.0",
    "CC-BY-NC-SA-4.0",
    "research-only",
    "non-commercial",
)


def validate_license_for_product_use(license_id: str) -> None:
    """Fail-closed license gate: raise LicenseMissingError unless approved."""
    entry = BACKEND_LICENSE_REGISTRY.get(license_id)
    if entry is None:
        raise LicenseMissingError(
            f"license_id {license_id!r} is not in BACKEND_LICENSE_REGISTRY"
        )
    if entry.get("product_use") not in ("approved", "approved-local-use"):
        raise LicenseMissingError(
            f"license {license_id!r} is not approved for product use"
        )
    spdx = entry.get("spdx", "")
    for forbidden in FORBIDDEN_PRODUCT_LICENSES:
        if forbidden.lower() in spdx.lower() or forbidden.lower() in license_id.lower():
            raise LicenseMissingError(
                f"license {license_id!r} carries no-permission terms ({forbidden})"
            )
