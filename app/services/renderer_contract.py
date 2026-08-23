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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

#: Re-exported single authority for the five canonical routes.  Imported from
#: the ORM constants so the taxonomy is never duplicated (I01 ownership).
from app.persistence.models import RENDERER_ROUTES

RendererRoute = str  # constrained at runtime to RENDERER_ROUTES values

__all__ = [
    "BACKEND_LICENSE_REGISTRY",
    "BenchmarkBelowThresholdError",
    "BackendBinaryMissingError",
    "BackendAdapter",
    "CapabilityDescriptor",
    "CapabilityMismatchError",
    "LicenseMissingError",
    "PROVENANCE_REQUIRED_FIELDS",
    "RenderRequest",
    "RenderResult",
    "RendererContractCode",
    "RendererRouterError",
    "ROUTE_PRIORITY",
    "RouteProvenance",
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
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class RenderRequest:
    """One bounded render ask, pinned to an occurrence-segment frame range."""

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
