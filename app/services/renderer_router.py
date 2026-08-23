"""Adaptive renderer ROUTER (S09-T00-I02) — TARGET_PROFILE §4 P0-7 + §8.

Deterministic capability registry over installed ``BackendAdapter``s:

- registry ordering is DETERMINISTIC (insertion order of the adapters list;
  ties broken by backend_id) so repeated construction yields identical order;
- route selection picks the FIRST available+licensed+threshold-passing
  adapter bound to the requested route; ``select_backend`` exposes the
  explicit override API for Demo review;
- escalation is evidence-driven ONLY: a RouteProvenance with all five fields
  plus an on-disk evidence artifact is produced when the measured error of
  the current route exceeds its gate and the NEXT route reduces it;
- FAIL CLOSED everywhere: unknown backend, unknown capability, missing
  license, below-threshold benchmark or missing binary RAISE — there is no
  silent fallback to another backend/route and no automatic model switch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.persistence.models import RENDERER_ROUTES
from app.services.renderer_contract import (
    BackendAdapter,
    BackendBinaryMissingError,
    BenchmarkBelowThresholdError,
    CapabilityMismatchError,
    LicenseMissingError,
    RenderRequest,
    RenderResult,
    RendererContractCode,
    RendererRoute,
    ROUTE_PRIORITY,
    UnknownBackendError,
    UnknownCapabilityError,
    validate_license_for_product_use,
)

__all__ = [
    "RendererRouter",
]


class RendererRouter:
    """Deterministic fail-closed router over registered renderer backends."""

    def __init__(
        self,
        adapters: list[BackendAdapter] | tuple[BackendAdapter, ...],
        *,
        default_routes: dict[str, RendererRoute] | None = None,
        evidence_dir: Path | None = None,
    ) -> None:
        if not adapters:
            raise CapabilityMismatchError(
                "RendererRouter requires at least one adapter"
            )
        self._adapters = list(adapters)
        self._evidence_dir = evidence_dir
        # Deterministic registry: sort by (route rank, backend_id).
        def _key(a: BackendAdapter) -> tuple[int, str]:
            return (ROUTE_PRIORITY.index(a.route), a.backend_id)

        self._registry: dict[RendererRoute, list[BackendAdapter]] = {
            route: [] for route in RENDERER_ROUTES
        }
        for adapter in sorted(self._adapters, key=_key):
            self._registry.setdefault(adapter.route, []).append(adapter)
            # A single adapter instance must not be double-registered.
            if len(self._registry.get(adapter.route, [])) != len(
                {a.backend_id for a in self._registry[adapter.route]}
            ):
                raise CapabilityMismatchError(
                    f"duplicate backend_id {adapter.backend_id!r} "
                    f"on route {adapter.route!r}"
                )
        self._default_routes: dict[str, RendererRoute] = {}
        if default_routes:
            unknown = set(default_routes) - set(RENDERER_ROUTES)
            if unknown:
                raise CapabilityMismatchError(
                    f"default_routes has unknown routes: {sorted(unknown)}"
                )
            self._default_routes = dict(default_routes)

    # ── Capability surface ────────────────────────────────────────────────

    def capabilities(self) -> list[tuple[str, str]]:
        """Deterministic (backend_id, route) listing of every registration."""
        return [
            (a.backend_id, a.route)
            for route in ROUTE_PRIORITY
            for a in self._registry.get(route, [])
        ]

    def available_backends_for_route(self, route: RendererRoute) -> list[str]:
        """Backend ids on this route that pass license+availability gates."""
        self._require_known_route(route)
        out: list[str] = []
        for adapter in self._registry[route]:
            cap = adapter.capability()
            if not cap.available:
                continue
            try:
                validate_license_for_product_use(cap.license_id)
            except Exception:
                continue
            out.append(cap.backend_id)
        return out

    # ── Selection ─────────────────────────────────────────────────────────

    def _require_known_route(self, route: RendererRoute) -> None:
        if route not in ROUTE_PRIORITY:
            raise CapabilityMismatchError(
                f"route must be one of {ROUTE_PRIORITY}, got {route!r}"
            )

    def select_backend(
        self,
        request: RenderRequest,
        *,
        allow_unavailable_probe: bool = False,
    ) -> BackendAdapter:
        """Pick the adapter that will serve this request — fail closed.

        Override rule (Demo review): an explicit ``backend_override`` MUST be
        honored exactly or raised; the router never substitutes a different
        backend when the override fails its gates.
        """
        self._require_known_route(request.route)
        if request.backend_override is not None:
            for adapter in self._registry.get(request.route, []):
                if adapter.backend_id == request.backend_override:
                    self._gate_adapter(adapter, request)
                    return adapter
            raise UnknownBackendError(
                f"override backend {request.backend_override!r} is not "
                f"registered for route {request.route!r}"
            )

        candidates = self._registry.get(request.route, [])
        if not candidates:
            raise UnknownCapabilityError(
                f"no backend registered for route {request.route!r}"
            )
        errors: list[str] = []
        last_specific: Exception | None = None
        for adapter in candidates:  # deterministic order
            try:
                self._gate_adapter(adapter, request)
                return adapter
            except (
                BenchmarkBelowThresholdError,
                LicenseMissingError,
                BackendBinaryMissingError,
            ) as err:
                # Deterministic single-backend gate failures keep their exact
                # taxonomy code (TASK.md: every failure kind raises ITS type).
                errors.append(f"{adapter.backend_id}: {err}")
                last_specific = err
            except Exception as err:
                errors.append(f"{adapter.backend_id}: {err}")
        if len(candidates) == 1 and last_specific is not None:
            raise last_specific
        raise UnknownCapabilityError(
            "no candidate backend passed the gates for route "
            f"{request.route!r} ({'; '.join(errors)})"
        )

    def _gate_adapter(
        self,
        adapter: BackendAdapter,
        request: RenderRequest,
        *,
        allow_unavailable_probe: bool = False,
    ) -> None:
        """License + availability + threshold gates; raises on any failure."""
        cap = adapter.capability()
        validate_license_for_product_use(cap.license_id)
        if allow_unavailable_probe:
            return
        if not cap.available:
            code = cap.unavailable_reason_code or "unknown_capability"
            if code == RendererContractCode.BACKEND_BINARY_MISSING.value:
                raise BackendBinaryMissingError(
                    f"backend {cap.backend_id!r} unavailable: "
                    f"{cap.details.get('error', 'binary missing')}"
                )
            if code == RendererContractCode.LICENSE_MISSING.value:
                raise LicenseMissingError(
                    f"backend {cap.backend_id!r} unavailable: license gate"
                )
            raise UnknownCapabilityError(
                f"backend {cap.backend_id!r} reports unavailable"
                f" ({cap.evidence_source})"
            )
        if (
            request.max_runtime_ms_per_frame is not None
            and cap.runtime_ms_per_frame is not None
            and cap.runtime_ms_per_frame > request.max_runtime_ms_per_frame
        ):
            raise BenchmarkBelowThresholdError(
                f"backend {cap.backend_id!r} measured "
                f"{cap.runtime_ms_per_frame:.2f} ms/frame > gate "
                f"{request.max_runtime_ms_per_frame:.2f} ms/frame"
            )

    # ── Execution (never crosses routes/backends silently) ───────────────

    def execute(self, request: RenderRequest) -> RenderResult:
        adapter = self.select_backend(request)
        return adapter.render(request)

    # ── Evidence-driven escalation ────────────────────────────────────────

    def maybe_escalate(
        self,
        segment_id: str,
        route_from: RendererRoute,
        metric_name: str,
        metric_value: float,
        threshold: float,
        candidate_route: RendererRoute,
        *,
        artifact_path: str,
        candidate_metric_projection: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        """Escalate ONLY when measured error strictly exceeds the gate AND
        the next route actually reduces the same metric (overlay §8/S09-T00:
        mesh/part/flow selected only where it reduces MEASURED error).

        ``candidate_metric_projection`` is the measured/fixture-projected
        metric the escalated route would achieve — REQUIRED evidence that
        escalation reduces error; absent projection → refused (fail closed).

        Returns ``(escalated, provenance_or_reason)``; writes the JSON
        evidence artifact either way (auditable no-op on refusal).
        """
        from app.services.renderer_contract import RouteProvenance  # local: leaf

        self._require_known_route(route_from)
        self._require_known_route(candidate_route)
        if ROUTE_PRIORITY.index(candidate_route) <= ROUTE_PRIORITY.index(route_from):
            reason = (
                f"refused: candidate {candidate_route!r} is not a forward step "
                f"from {route_from!r}"
            )
            self._write_refusal(segment_id, artifact_path, reason)
            return False, reason

        if not metric_value > threshold:
            reason = (
                f"refused: {metric_name}={metric_value!r} does not exceed "
                f"threshold={threshold!r}"
            )
            self._write_refusal(segment_id, artifact_path, reason)
            return False, reason

        if candidate_metric_projection is None:
            reason = (
                "refused: no candidate_metric_projection evidence that route "
                f"{candidate_route!r} reduces {metric_name}"
            )
            self._write_refusal(segment_id, artifact_path, reason)
            return False, reason

        if not candidate_metric_projection < metric_value:
            reason = (
                f"refused: projected {candidate_metric_projection!r} on "
                f"{candidate_route!r} does not reduce {metric_name} below the "
                f"measured {metric_value!r}"
            )
            self._write_refusal(segment_id, artifact_path, reason)
            return False, reason

        baseline = self.available_backends_for_route(route_from)
        upgraded = self.available_backends_for_route(candidate_route)
        if not upgraded:
            reason = (
                f"refused: no available backend on escalated route "
                f"{candidate_route!r}"
            )
            self._write_refusal(segment_id, artifact_path, reason)
            return False, reason

        prov = RouteProvenance(
            segment_id=segment_id,
            route_from=route_from,
            route_to=candidate_route,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
            evidence_artifact_path=artifact_path,
        )
        path = Path(prov.write_evidence(extra))
        record = prov.to_dict()
        record["baseline_backends"] = baseline
        record["escalated_backends"] = upgraded
        record["evidence_bytes"] = path.stat().st_size
        return True, record

    def _write_refusal(self, segment_id: str, artifact_path: str, reason: str) -> None:
        payload: dict[str, Any] = {
            "kind": "renderer_route_escalation_refused",
            "segment_id": segment_id,
            "reason": reason,
        }
        path = Path(artifact_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )
