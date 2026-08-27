"""Durable targeted demo-review correction repository (S09-T05A).

Implements the S09-T05A targeted-correction surface on top of the verified
durable core — the correction ARCHIVE is new (``s09_correction``), but every
MUTATION it applies reuses the existing verified repositories (no parallel
write path, no silent substitute):

- **mask / z_order** → ``StructuralEvidenceRepository.supersede_segment``
  (C1-F1 workflow A): the locked OccurrenceSegment lineage is superseded
  with explicit user/manual provenance; history is never overwritten.
- **contact** → ``StructuralEvidenceRepository.update_contact`` (CAS R1 F8).
- **mesh_parts** → ``StructuralEvidenceRepository.update_motion`` (CAS) on
  the segment's ``object_relative`` transform contract.
- **route_override** → ``StructuralLockRepository.record_render_route``
  with a NEW SegmentRenderRoute history row carrying the full provenance
  (route_from/route_to/reason/evidence).  The old decision row is NEVER
  mutated — history is preserved via the natural key.

Design rules (mirroring structural_lock + object_correction):

- Workspace/project/video/segment ownership validated fail-closed on every
  write; cross-workspace reads raise NotFound.
- Request/impact/result JSON are canonical finite-only JSON validated
  BEFORE any write (zero mutation on invalid payloads).
- Idempotent replay: UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL;
  equivalent replay returns the existing row (created=False), a materially
  different payload under the same key → conflict.
- Natural key replay: content-derived sha256 over (kind + target ids +
  canonical request) makes duplicate submissions converge on ONE row.
- Confirm is an atomic CAS transition ``pending -> applied``: the targeted
  mutation + result archive in ONE transaction (the route owns commit);
  stale revision → conflict with ZERO durable mutation.
- Cancel is CAS ``pending -> cancelled``; applied corrections can never be
  cancelled or re-confirmed (terminal states stay terminal).
- Impact preview is a PURE read reporting the exact affected scope:
  affected loop/layer/segment ids — regeneration touches ONLY those.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.models import (
    RENDERER_ROUTES,
    S09_CORRECTION_KINDS,
    Artifact,
    OccurrenceSegment,
    Project,
    S09Correction,
    VideoItem,
    utc_now,
)
from app.persistence.structural_evidence import (
    ContactNotFoundError,
    MotionNotFoundError,
    StructuralEvidenceRepository,
)
from app.persistence.structural_lock import (
    StructuralLockOwnershipError,
    StructuralLockParamsError,
    StructuralLockRepository,
)

__all__ = [
    "CorrectionConflictError",
    "CorrectionImpact",
    "CorrectionNotFoundError",
    "CorrectionRecord",
    "CorrectionValidationError",
    "RENDER_EFFECT_VERSION",
    "RouteOverrideProvenanceError",
    "S09CorrectionRepository",
    "correction_natural_key",
]

#: Version tag of the canonical per-kind render-effect block embedded in
#: every applied-regeneration context (S09-T05A-C4 §4.2/§4.3).
RENDER_EFFECT_VERSION = "s09-correction-render-effect-v1"

#: Version tag of the mask semantics recorded alongside the resolved
#: immutable mask-artifact evidence.
MASK_SEMANTICS_VERSION = "s09-mask-semantics-v1"


class CorrectionConflictError(Exception):
    """CAS stale revision, terminal-state misuse or idempotency conflict."""


class CorrectionNotFoundError(Exception):
    """No correction row for the requested id inside this workspace."""


class CorrectionValidationError(ValueError):
    """Payload outside its closed domain (fail-closed validation)."""


class RouteOverrideProvenanceError(CorrectionValidationError):
    """A route override correction without complete provenance evidence."""


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_non_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise CorrectionValidationError(f"non-finite number at {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")


def _parse_payload(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


#: Identifier-shaped values: repo-internal UUID/slug ids only.  Anything
#: carrying a separator, a dot-dot climb or control characters is treated
#: as a path-escape attempt and refused fail-closed.
_PATH_ESCAPE_PATTERN = r"^[A-Za-z0-9._:\-]{1,128}$"

#: Which request fields per kind are identifier-shaped.
_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "mask": ("occurrence_segment_id", "source_generation", "mask_artifact_id"),
    "z_order": ("occurrence_segment_id", "source_generation"),
    "contact": ("contact_id",),
    "mesh_parts": ("motion_id",),
    "route_override": (
        "occurrence_segment_id",
        "structural_lock_manifest_id",
    ),
}


def _reject_path_escape_ids(correction_kind: str, request: dict[str, Any]) -> None:
    import re

    for field in _ID_FIELDS[correction_kind]:
        value = request.get(field)
        if not isinstance(value, str):
            continue
        if not re.match(_PATH_ESCAPE_PATTERN, value):
            raise CorrectionValidationError(
                f"{field} is not a valid identifier (path escape refused): "
                f"{value!r}"
            )


def _validate_route_override_request(request: dict[str, Any]) -> None:
    """Closed-domain checks for route_override — canonical routes only.

    Mirrors the Pydantic boundary exactly so direct-repository callers
    get the same fail-closed semantics as HTTP clients.
    """
    route_from = request.get("route_from")
    if route_from not in RENDERER_ROUTES:
        raise CorrectionValidationError(
            f"route_from must be one of {RENDERER_ROUTES}, got {route_from!r}"
        )
    route_to = request.get("route_to")
    if route_to not in RENDERER_ROUTES:
        raise CorrectionValidationError(
            f"route_to must be one of {RENDERER_ROUTES}, got {route_to!r}"
        )

    def _bounded_anchor(name: str) -> float:
        raw = request.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise CorrectionValidationError(f"{name} must be a number")
        value = float(raw)
        if not math.isfinite(value):
            raise CorrectionValidationError(
                f"{name} must be finite (NaN/Inf refused)"
            )
        if not 0.0 <= value <= 1.0:
            raise CorrectionValidationError(
                f"{name} must be within [0, 1], got {value!r}"
            )
        return value

    _bounded_anchor("anchor_x")
    _bounded_anchor("anchor_y")

    try:
        start_frame = int(request["start_frame"])
        end_frame = int(request["end_frame"])
    except (TypeError, ValueError) as err:
        raise CorrectionValidationError(
            "start_frame/end_frame must be integers"
        ) from err
    if start_frame < 0 or end_frame < 0:
        raise CorrectionValidationError(
            "start_frame/end_frame must be >= 0"
        )
    if start_frame > end_frame:
        raise CorrectionValidationError(
            f"start_frame ({start_frame}) must be <= end_frame ({end_frame})"
        )

    reason = request.get("override_reason")
    if (
        not isinstance(reason, str)
        or not reason.strip()
    ):
        raise CorrectionValidationError(
            "route_override requires a non-empty override_reason"
        )
    # NORMALIZE in place so the archived request_json is clean too.
    request["override_reason"] = reason.strip()
    provenance = request.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    prov_evidence = provenance.get("evidence")
    if not isinstance(prov_evidence, str) or not prov_evidence.strip():
        raise CorrectionValidationError(
            "route_override requires non-empty normalized provenance.evidence"
        )
    provenance["evidence"] = prov_evidence.strip()


def correction_natural_key(
    *,
    correction_kind: str,
    video_item_id: str,
    request: dict[str, Any],
) -> str:
    """Content-derived natural key: kind + video + canonical request hash."""
    digest = hashlib.sha256(
        _canonical_json({"kind": correction_kind, "video_item_id": video_item_id,
                         "request": request}).encode("utf-8")
    ).hexdigest()
    return f"S09C:{correction_kind}:{digest[:48]}"


@dataclass(frozen=True)
class CorrectionRecord:
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    occurrence_segment_id: str | None
    correction_kind: str
    status: str
    request: dict[str, Any]
    impact: dict[str, Any]
    result: dict[str, Any] | None
    applied_at: datetime | None
    cancelled_at: datetime | None
    idempotency_key: str | None
    natural_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


def _map_record(row: S09Correction) -> CorrectionRecord:
    result = _parse_payload(row.result_json)
    return CorrectionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        occurrence_segment_id=row.occurrence_segment_id,
        correction_kind=row.correction_kind,
        status=row.status,
        request=_parse_payload(row.request_json),
        impact=_parse_payload(row.impact_json),
        result=result or None,
        applied_at=row.applied_at,
        cancelled_at=row.cancelled_at,
        idempotency_key=row.idempotency_key,
        natural_key=row.natural_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass(frozen=True)
class CorrectionImpact:
    """Pure-read affected-scope report (NO writes at preview time)."""

    correction_kind: str
    affected_occurrence_segment_ids: list[str]
    affected_contact_ids: list[str]
    affected_motion_ids: list[str]
    affected_loop_ids: list[str]
    #: Stable MACHINE layer keys (segment lineage ``logical_id``) — the
    #: render binding authority (S09-C4 §4.2), never a display label.
    affected_layer_ids: list[str]
    route_override: bool
    counts: dict[str, int]
    #: Human-readable display labels, kept OUT of the machine binding.
    affected_layer_labels: list[str] = dataclasses_field(default_factory=list)


class S09CorrectionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._evidence = StructuralEvidenceRepository(session)

    # ── impact (pure read) ────────────────────────────────────────────────

    def compute_impact(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        correction_kind: str,
        request: dict[str, Any],
    ) -> CorrectionImpact:
        """Exact impacted scope for one correction — ZERO durable writes.

        Affected surfaces per kind:
          mask           -> [occurrence_segment_id] (supersede lineage)
          z_order        -> [occurrence_segment_id] (supersede lineage)
          contact        -> [the contact's endpoint segments] (CAS contact)
          mesh_parts     -> [segment owning the motion] (CAS motion)
          route_override -> [segment] (NEW SegmentRenderRoute history row)
        """
        self._validate_kind(correction_kind)
        self._assert_ownership(workspace_id, project_id, video_item_id)
        request = self._validated_request(correction_kind, request)

        segments: list[str] = []
        contacts: list[str] = []
        motions: list[str] = []
        # Stable MACHINE keys only (S09-C4 §4.2): the lineage ``logical_id``
        # survives supersede corrections, unlike per-version ids or display
        # names.  Display labels are still reported separately via
        # affected_layer_labels so nothing is lost for humans.
        layers: list[str] = []
        layer_labels: list[str] = []
        loops: list[str] = [
            str(x) for x in (request.get("affected_loop_ids") or []) if str(x).strip()
        ]
        seg_id = request.get("occurrence_segment_id")
        if seg_id is not None:
            # Fail-closed existence + ownership BEFORE anything else.
            record = self._evidence.get_segment(workspace_id, str(seg_id))
            segments.append(record.id)
            layers.append(record.logical_id)
            layer_labels.append(record.name)

        if correction_kind == "contact":
            contact_id = request.get("contact_id")
            try:
                contact = self._evidence.get_contact(workspace_id, str(contact_id))
            except ContactNotFoundError as err:
                raise CorrectionConflictError(str(err)) from err
            contacts.append(contact.id)
            for endpoint in (contact.source_segment_id, contact.target_segment_id):
                if endpoint not in segments:
                    record = self._evidence.get_segment(workspace_id, endpoint)
                    segments.append(record.id)
                    layers.append(record.logical_id)
                    layer_labels.append(record.name)

        if correction_kind == "mesh_parts":
            motion_id = request.get("motion_id")
            try:
                motion = self._evidence.get_motion(workspace_id, str(motion_id))
            except MotionNotFoundError as err:
                raise CorrectionConflictError(str(err)) from err
            motions.append(motion.id)
            if motion.occurrence_segment_id not in segments:
                record = self._evidence.get_segment(
                    workspace_id, motion.occurrence_segment_id
                )
                segments.append(record.id)
                layers.append(record.logical_id)
                layer_labels.append(record.name)

        total_segments = int(
            self._session.scalar(
                select(func.count(S09Correction.id)).where(
                    S09Correction.workspace_id == workspace_id,
                    S09Correction.video_item_id == video_item_id,
                    S09Correction.status == "applied",
                )
            )
            or 0
        )
        return CorrectionImpact(
            correction_kind=correction_kind,
            affected_occurrence_segment_ids=segments,
            affected_contact_ids=contacts,
            affected_motion_ids=motions,
            affected_loop_ids=loops,
            affected_layer_ids=layers,
            affected_layer_labels=layer_labels,
            route_override=correction_kind == "route_override",
            counts={
                "affected_segments": len(segments),
                "affected_contacts": len(contacts),
                "affected_motions": len(motions),
                "previously_applied_corrections": total_segments,
            },
        )

    # ── create (natural-key + idempotency-key idempotent) ────────────────

    def create_correction(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        correction_kind: str,
        request: dict[str, Any],
        impact: CorrectionImpact,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[CorrectionRecord, bool]:
        """Archive the pending correction (idempotent replay -> same row)."""
        self._validate_kind(correction_kind)
        self._assert_ownership(workspace_id, project_id, video_item_id)
        canonical_request = self._validated_request(correction_kind, request)
        if idempotency_key is not None:
            if len(idempotency_key) > 255:
                raise CorrectionValidationError("idempotency_key too long")
            if not idempotency_key.strip():
                raise CorrectionValidationError(
                    "idempotency_key must not be empty if provided"
                )
        natural_key = correction_natural_key(
            correction_kind=correction_kind,
            video_item_id=video_item_id,
            request=canonical_request,
        )

        existing = self._session.scalar(
            select(S09Correction).where(
                S09Correction.workspace_id == workspace_id,
                S09Correction.natural_key == natural_key,
            )
        )
        if existing is not None:
            self._assert_equivalent(existing, project_id, video_item_id,
                                    correction_kind, canonical_request)
            return _map_record(existing), False
        if idempotency_key:
            keyed = self._session.scalar(
                select(S09Correction).where(
                    S09Correction.workspace_id == workspace_id,
                    S09Correction.idempotency_key == idempotency_key,
                )
            )
            if keyed is not None:
                self._assert_equivalent(keyed, project_id, video_item_id,
                                        correction_kind, canonical_request)
                return _map_record(keyed), False

        row = S09Correction(
            id=_new_id(),
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            occurrence_segment_id=(
                canonical_request.get("occurrence_segment_id")
                if isinstance(canonical_request.get("occurrence_segment_id"), str)
                else None
            ),
            correction_kind=correction_kind,
            status="pending",
            request_json=_canonical_json(canonical_request),
            impact_json=_canonical_json(self._impact_payload(impact)),
            idempotency_key=idempotency_key,
            natural_key=natural_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            raced = self._session.scalar(
                select(S09Correction).where(
                    S09Correction.workspace_id == workspace_id,
                    S09Correction.natural_key == natural_key,
                )
            )
            if raced is not None:
                self._assert_equivalent(raced, project_id, video_item_id,
                                        correction_kind, canonical_request)
                return _map_record(raced), False
            raise CorrectionConflictError(
                f"s09 correction conflicts with an existing row: {err.orig}"
            ) from err
        return _map_record(row), True

    # ── confirm (atomic CAS pending -> applied) ──────────────────────────

    def confirm_correction(
        self,
        workspace_id: str,
        correction_id: str,
        revision: int,
    ) -> tuple[CorrectionRecord, bool]:
        """Apply the pending correction exactly once (atomic CAS).

        The targeted mutation through the verified core repositories plus
        the result archive happen inside THIS transaction (the caller owns
        commit/rollback); a stale revision raises with ZERO mutation.
        """
        row = self._correction_row(workspace_id, correction_id)
        if row.status == "applied":
            return _map_record(row), False
        if row.status == "cancelled":
            raise CorrectionConflictError(
                "correction was cancelled; it can never be confirmed"
            )
        # CAS FIRST: a stale revision refuses BEFORE the targeted mutation
        # touches any durable core row (zero-mutation guarantee).
        if row.revision != revision:
            raise CorrectionConflictError(
                f"stale revision {revision}; current revision is {row.revision}"
            )
        request = _parse_payload(row.request_json)
        # Fail-closed guards run BEFORE the targeted mutation touches any
        # durable core row (same zero-mutation discipline as the CAS check):
        # resolve the stable layer ids from the archived impact and prove a
        # live binding exists for every one of them (pure reads — a
        # defective/legacy row refuses without a single flushed write).
        layer_ids = self._impact_layer_ids(row)
        self._context_layer_binding(workspace_id, layer_ids)
        result = self._apply_mutation(
            workspace_id,
            row.correction_kind,
            request,
            project_id=row.project_id,
            video_item_id=row.video_item_id,
        )
        # S09-C4 §4.2/§4 replay: freeze the POST-APPLY stable binding
        # evidence (live successor rows) INTO the applied result; every
        # later applied_regeneration_context read re-reads that archived
        # snapshot instead of re-deriving, so the context (and its SHA)
        # stays byte-identical even after the lineage is superseded again.
        result["applied_layer_bindings"] = self._context_layer_binding(
            workspace_id, layer_ids
        )

        row.status = "applied"
        row.applied_at = utc_now()
        row.updated_at = utc_now()
        row.revision = revision + 1
        row.result_json = _canonical_json(result)
        try:
            self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            raise CorrectionConflictError(
                f"s09 correction update conflicted: {err.orig}"
            ) from err
        return _map_record(row), True

    # ── cancel (CAS pending -> cancelled) ────────────────────────────────

    def cancel_correction(
        self,
        workspace_id: str,
        correction_id: str,
        revision: int,
    ) -> tuple[CorrectionRecord, bool]:
        row = self._correction_row(workspace_id, correction_id)
        if row.status == "cancelled":
            return _map_record(row), False
        if row.status == "applied":
            raise CorrectionConflictError(
                "correction was already applied; it cannot be cancelled"
            )
        if row.revision != revision:
            raise CorrectionConflictError(
                f"stale revision {revision}; current revision is {row.revision}"
            )
        row.status = "cancelled"
        row.cancelled_at = utc_now()
        row.updated_at = utc_now()
        row.revision = revision + 1
        try:
            self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            raise CorrectionConflictError(
                f"s09 correction update conflicted: {err.orig}"
            ) from err
        return _map_record(row), True

    # ── reads ─────────────────────────────────────────────────────────────

    def get_correction(self, workspace_id: str, correction_id: str) -> CorrectionRecord:
        return _map_record(self._correction_row(workspace_id, correction_id))

    # ── applied-regeneration context (S09-T05A-C3, pure read) ────────────

    def applied_regeneration_context(
        self,
        workspace_id: str,
        correction_id: str,
        *,
        expected_applied_revision: int | None = None,
    ) -> dict[str, Any]:
        """Immutable APPLIED-REGENERATION CONTEXT for one applied correction.

        S09-C3 §3.2 contract consumed by the T04 regenerate endpoint: the
        canonical, restart-stable description of WHAT changed so a partial
        regeneration can target exactly the affected loops.  Pure read —
        ZERO durable mutation on success AND on every refusal.

        Returned dict carries ``context_sha256`` =
        sha256(canonical-json(context minus the sha field)); the payload
        contains only stable post-apply facts (no timestamps), and an
        applied row is immutable (confirm-replay is a no-op, cancel is
        refused), so replays — even through fresh sessions/process
        restarts — yield the byte-identical SHA.

        Fail-closed refusals (before any read-derived value is trusted):
        unknown id → CorrectionNotFoundError; pending/cancelled →
        CorrectionConflictError; ``expected_applied_revision`` mismatch →
        CorrectionConflictError (CAS-style stale guard); empty affected
        loop scope, missing natural key, missing applied_at, or
        malformed/empty mutation result → CorrectionValidationError.
        """
        row = self._correction_row(workspace_id, correction_id)
        if row.status != "applied":
            raise CorrectionConflictError(
                f"correction {correction_id} is {row.status!r}; "
                "regeneration context exists only for APPLIED corrections"
            )
        if (
            expected_applied_revision is not None
            and row.revision != expected_applied_revision
        ):
            raise CorrectionConflictError(
                f"stale revision {expected_applied_revision}; "
                f"current applied revision is {row.revision}"
            )
        if not row.natural_key:
            raise CorrectionValidationError(
                "applied correction is missing its natural key"
            )
        if row.applied_at is None:
            raise CorrectionValidationError(
                "applied correction is missing applied_at"
            )
        impact = _parse_payload(row.impact_json)
        loops = sorted({str(x) for x in (impact.get("affected_loop_ids") or [])})
        if not loops:
            raise CorrectionValidationError(
                "applied correction has an empty affected loop scope; "
                "a targeted regeneration cannot be derived"
            )
        # S09-C4 §4.2 fail-closed binding guard: an applied row whose
        # archived impact carries NO stable machine layer id can never
        # drive an exact render binding — refuse instead of letting T03
        # fall back to array positions / display labels.
        layer_ids = sorted({str(x) for x in (impact.get("affected_layer_ids") or [])})
        if not layer_ids:
            raise CorrectionValidationError(
                "applied correction has no stable machine layer binding "
                "(empty affected_layer_ids); refusing to guess a render target"
            )
        result = _parse_payload(row.result_json)
        if not result:
            raise CorrectionValidationError(
                "applied correction has a malformed or empty mutation result"
            )

        def _ids(key: str) -> list[str]:
            return sorted({str(x) for x in (impact.get(key) or [])})

        context: dict[str, Any] = {
            "correction_id": row.id,
            "workspace_id": row.workspace_id,
            "project_id": row.project_id,
            "video_item_id": row.video_item_id,
            "correction_kind": row.correction_kind,
            "applied_revision": row.revision,
            "render_effect_version": RENDER_EFFECT_VERSION,
            "natural_key": row.natural_key,
            "occurrence_segment_id": row.occurrence_segment_id,
            "affected_occurrence_segment_ids": _ids(
                "affected_occurrence_segment_ids"
            ),
            "affected_contact_ids": _ids("affected_contact_ids"),
            "affected_motion_ids": _ids("affected_motion_ids"),
            "affected_loop_ids": loops,
            "affected_layer_ids": layer_ids,
            # S09-C4 §4.2: structural evidence keyed by the stable
            # logical_id so T03 can re-bind the exact render operation
            # without name/position ambiguity.  IMMUTABILITY (§4 replay
            # contract): the binding snapshot is FROZEN into the applied
            # row's result at confirm time and re-read from there on every
            # later call — a later supersede of the same lineage must never
            # mutate this correction's already-archived context (same SHA).
            # Legacy rows confirmed before that field existed fall back to
            # re-derived live bindings.
            "layer_bindings": (
                result.get("applied_layer_bindings")
                or self._context_layer_binding(workspace_id, layer_ids)
            ),
            "effect": result,
        }
        try:
            digest = hashlib.sha256(
                _canonical_json(context).encode("utf-8")
            ).hexdigest()
        except (TypeError, ValueError) as err:
            raise CorrectionValidationError(
                f"applied correction context is not canonically serializable: {err}"
            ) from err
        context["context_sha256"] = digest
        return context

    def list_corrections(
        self,
        workspace_id: str,
        video_item_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CorrectionRecord], int]:
        filters = [S09Correction.workspace_id == workspace_id]
        if video_item_id is not None:
            filters.append(S09Correction.video_item_id == video_item_id)
        total = int(
            self._session.scalar(select(func.count(S09Correction.id)).where(*filters))
            or 0
        )
        rows = self._session.scalars(
            select(S09Correction)
            .where(*filters)
            .order_by(S09Correction.created_at.desc(), S09Correction.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_map_record(r) for r in rows], total

    def applied_correction_counts(
        self, workspace_id: str, video_item_id: str
    ) -> dict[str, Any]:
        """Applied correction counts per kind — the benchmark-results feed."""
        rows = self._session.execute(
            select(S09Correction.correction_kind, func.count(S09Correction.id))
            .where(
                S09Correction.workspace_id == workspace_id,
                S09Correction.video_item_id == video_item_id,
                S09Correction.status == "applied",
            )
            .group_by(S09Correction.correction_kind)
        ).all()
        by_kind = {str(kind): int(count) for kind, count in rows}
        return {
            "total": sum(by_kind.values()),
            "by_kind": {k: by_kind[k] for k in sorted(by_kind)},
        }

    # ── mutations through the verified core ──────────────────────────────

    def _apply_mutation(
        self,
        workspace_id: str,
        correction_kind: str,
        request: dict[str, Any],
        *,
        project_id: str | None = None,
        video_item_id: str | None = None,
    ) -> dict[str, Any]:
        if correction_kind == "mask":
            provenance = self._required_provenance(request, correction_kind)
            predecessor, successor = self._evidence.supersede_segment(
                workspace_id,
                str(request["occurrence_segment_id"]),
                int(request["revision"]),
                source_generation=str(request["source_generation"]),
                segmentation=request["segmentation"],
                mask_artifact_id=request["mask_artifact_id"],
                confidence_source=str(request.get("confidence_source", "user")),
                reasons=list(request.get("reasons") or ["mask correction"]),
                provenance=provenance,
                idempotency_key=request.get("mutation_idempotency_key"),
            )
            return {
                "supersede": {
                    "predecessor_id": predecessor.id,
                    "successor_id": successor.id,
                    "logical_id": successor.logical_id,
                    "lineage_version": successor.lineage_version,
                    "mask_artifact_id": successor.mask_artifact_id,
                },
                # S09-C4 §4.3: canonical render-effect block — resolved
                # immutable artifact evidence + REAL semantics so a restart
                # can reproduce the identical effect.
                "render_effect": self._render_mask_effect(successor, request),
            }
        if correction_kind == "z_order":
            provenance = self._required_provenance(request, correction_kind)
            predecessor, successor = self._evidence.supersede_segment(
                workspace_id,
                str(request["occurrence_segment_id"]),
                int(request["revision"]),
                source_generation=str(request["source_generation"]),
                z_order=int(request["z_order"]),
                confidence_source=str(request.get("confidence_source", "user")),
                reasons=list(request.get("reasons") or ["z_order correction"]),
                provenance=provenance,
                idempotency_key=request.get("mutation_idempotency_key"),
            )
            return {
                "supersede": {
                    "predecessor_id": predecessor.id,
                    "successor_id": successor.id,
                    "logical_id": successor.logical_id,
                    "lineage_version": successor.lineage_version,
                    "z_order": successor.z_order,
                },
                # S09-C4 §4.3: exact corrected z-order on the exact target
                # layer binding (stable logical_id, never a display label).
                "render_effect": {
                    "version": RENDER_EFFECT_VERSION,
                    "op": "z_order",
                    "target_layer_id": successor.logical_id,
                    "target_segment_id": successor.id,
                    "z_order": int(successor.z_order),
                },
            }
        if correction_kind == "contact":
            contact = self._evidence.update_contact(
                workspace_id,
                str(request["contact_id"]),
                int(request["revision"]),
                end_frame=request.get("end_frame"),
                end_time_ms=request.get("end_time_ms"),
                confidence=request.get("confidence"),
                reasons=list(request.get("reasons") or ["contact correction"]),
                provenance=self._optional_provenance(request),
            )
            return {
                "contact": {
                    "contact_id": contact.id,
                    "revision": contact.revision,
                    "end_frame": contact.end_frame,
                },
                # S09-C4 §4.3: full contact effect BOUND to its endpoint
                # operation (exact end-frame/end-time on both segment
                # bindings), not a display label.
                "render_effect": {
                    "version": RENDER_EFFECT_VERSION,
                    "op": "contact",
                    "target_contact_id": contact.id,
                    "source_segment_id": contact.source_segment_id,
                    "target_segment_id": contact.target_segment_id,
                    "contact_kind": contact.contact_kind,
                    "start_frame": int(contact.start_frame),
                    "end_frame": int(contact.end_frame),
                    "start_time_ms": int(contact.start_time_ms),
                    "end_time_ms": int(contact.end_time_ms),
                },
            }
        if correction_kind == "mesh_parts":
            motion = self._evidence.update_motion(
                workspace_id,
                str(request["motion_id"]),
                int(request["revision"]),
                transform=request["transform"],
                confidence=request.get("confidence"),
                reasons=list(request.get("reasons") or ["mesh/parts correction"]),
                provenance=self._optional_provenance(request),
            )
            return {
                "motion": {
                    "motion_id": motion.id,
                    "revision": motion.revision,
                    "transform_type": motion.transform_type,
                },
                # S09-C4 §4.3: FULL applied transform (every parameter),
                # not just ``transform_type`` — this is what makes the
                # visual effect reproducible after a restart.
                "render_effect": {
                    "version": RENDER_EFFECT_VERSION,
                    "op": "mesh_parts",
                    "target_motion_id": motion.id,
                    "transform_type": motion.transform_type,
                    "applied_transform": dict(motion.transform or {}),
                    "frame_range": {
                        "start_frame": int(motion.start_frame),
                        "end_frame": int(motion.end_frame),
                        "start_time_ms": int(motion.start_time_ms),
                        "end_time_ms": int(motion.end_time_ms),
                    },
                },
            }
        if correction_kind == "route_override":
            return self._apply_route_override(
                workspace_id,
                request,
                project_id=project_id,
                video_item_id=video_item_id,
            )
        raise CorrectionValidationError(  # pragma: no cover - CHECK-guarded
            f"unknown correction kind {correction_kind!r}"
        )

    def _apply_route_override(
        self,
        workspace_id: str,
        request: dict[str, Any],
        *,
        project_id: str | None = None,
        video_item_id: str | None = None,
    ) -> dict[str, Any]:
        """Write a NEW SegmentRenderRoute history row (never mutate the old).

        Provenance MUST carry route_from/route_to/reason/evidence — an
        incomplete override refuses fail-closed BEFORE any write.
        Ownership-scoped project/video ids come from the ARCHIVED ROW
        (authoritative, already ownership-asserted at submit), never from
        the request dict — a payload can never point the route row
        elsewhere.
        """
        if project_id is None or video_item_id is None:
            raise CorrectionValidationError(
                "route_override apply requires the archived row's "
                "project_id and video_item_id"
            )
        route_to = request.get("route_to")
        if route_to not in RENDERER_ROUTES:
            raise CorrectionValidationError(
                f"route_to must be one of {RENDERER_ROUTES}, got {route_to!r}"
            )
        route_from = request.get("route_from")
        if route_from not in RENDERER_ROUTES:
            raise CorrectionValidationError(
                f"route_from must be one of {RENDERER_ROUTES}, got {route_from!r}"
            )
        reason = request.get("override_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise RouteOverrideProvenanceError(
                "route_override requires a non-empty override_reason"
            )
        provenance = request.get("provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("route_from") != route_from
            or provenance.get("route_to") != route_to
            or not str(provenance.get("evidence") or "").strip()
        ):
            raise RouteOverrideProvenanceError(
                "route_override provenance must persist route_from, route_to "
                "and non-empty evidence (fail-closed audit trail)"
            )
        lock_repo = StructuralLockRepository(self._session)
        try:
            record, created = lock_repo.record_render_route(
                workspace_id=workspace_id,
                project_id=str(project_id),
                video_item_id=str(video_item_id),
                occurrence_segment_id=str(request["occurrence_segment_id"]),
                route=str(route_to),
                anchor_x=float(request["anchor_x"]),
                anchor_y=float(request["anchor_y"]),
                start_frame=int(request["start_frame"]),
                end_frame=int(request["end_frame"]),
                provenance=dict(provenance),
                reasons=[str(reason)],
                algorithm=request.get("algorithm"),
                algorithm_version=request.get("algorithm_version"),
                confidence=float(request.get("confidence", 1.0)),
                confidence_source="user",
                structural_lock_manifest_id=request.get(
                    "structural_lock_manifest_id"
                ),
                idempotency_key=request.get("mutation_idempotency_key"),
            )
        except (StructuralLockOwnershipError, StructuralLockParamsError) as err:
            raise CorrectionConflictError(str(err)) from err
        # Resolve the target segment for the STABLE layer binding key
        # (§4.2): machine logical_id from structural evidence, never a
        # display label or array position.
        seg_record = self._evidence.get_segment(
            workspace_id, str(request["occurrence_segment_id"])
        )
        return {
            "route_override": {
                "render_route_id": record.id,
                "route_from": route_from,
                "route_to": record.route,
                "created": created,
                "start_frame": record.start_frame,
                "end_frame": record.end_frame,
                "provenance": provenance,
            },
            # S09-C4 §4.3: exact target/segment + measured-passing route_to
            # + frame range/anchor/provenance — the full targeted plan.
            "render_effect": {
                "version": RENDER_EFFECT_VERSION,
                "op": "route_override",
                "target_layer_id": seg_record.logical_id,
                "target_segment_id": str(request["occurrence_segment_id"]),
                "render_route_id": record.id,
                "route_from": route_from,
                "route_to": record.route,
                "frame_range": {
                    "start_frame": int(record.start_frame),
                    "end_frame": int(record.end_frame),
                },
                "anchor": {"x": float(record.anchor_x), "y": float(record.anchor_y)},
                "provenance": dict(provenance),
            },
        }

    # ── canonical render-effect helpers (S09-T05A-C4 §4.3) ────────────────

    def _context_layer_binding(
        self, workspace_id: str, layer_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Re-derive stable structural bindings from LIVE segment rows.

        §4.2: the context must carry machine-verifiable binding evidence —
        per stable ``logical_id``, the exact live segment id(s) bound to
        that lineage plus video/scene/role ownership keys.  Derived from
        the durable occurrence_segment table (never from a caller-supplied
        payload) so T03 can re-resolve the target after a restart.  The
        result is FROZEN into the applied row at confirm time
        (``applied_layer_bindings``) and re-read from there afterwards, so
        this derivation runs exactly once per correction — a later
        supersede of the same lineage cannot mutate an already-applied
        context.  A logical_id with no live segment row fails closed.
        """
        bindings: dict[str, dict[str, Any]] = {}
        rows = self._session.scalars(
            select(OccurrenceSegment).where(
                OccurrenceSegment.workspace_id == workspace_id,
                OccurrenceSegment.logical_id.in_(layer_ids),
                OccurrenceSegment.superseded_by_id.is_(None),
            )
        ).all()
        by_logical: dict[str, list[OccurrenceSegment]] = {}
        for seg in rows:
            by_logical.setdefault(seg.logical_id, []).append(seg)
        missing = [k for k in layer_ids if k not in by_logical]
        if missing:
            raise CorrectionValidationError(
                "no live segment binding for affected layer id(s): "
                f"{sorted(missing)}"
            )
        for key in layer_ids:
            matches = sorted(by_logical[key], key=lambda s: s.id)
            primary = matches[0]
            bindings[key] = {
                "bound_segment_ids": [m.id for m in matches],
                "video_item_id": primary.video_item_id,
                "scene_id": primary.scene_id,
                "role_id": primary.role_id,
                "lineage_versions": sorted({int(m.lineage_version) for m in matches}),
            }
        return bindings

    @staticmethod
    def _impact_layer_ids(row: S09Correction) -> list[str]:
        """Stable machine layer ids from the row's OWN archived impact.

        Confirm-time authority for which lineages the correction touches:
        the impact archived at submit (already derived from structural
        evidence through compute_impact), never caller-supplied request
        fields.  Empty → fail closed (an applied row without a stable
        layer binding can never drive an exact render target).
        """
        try:
            impact = json.loads(row.impact_json or "{}")
        except (TypeError, ValueError):
            impact = {}
        layer_ids = sorted(
            {str(x) for x in (impact.get("affected_layer_ids") or []) if str(x).strip()}
        )
        if not layer_ids:
            raise CorrectionValidationError(
                "applied correction has no stable machine layer binding "
                "(empty affected_layer_ids); refusing to guess a render target"
            )
        return layer_ids

    def _render_mask_effect(
        self, successor: Any, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolved immutable mask-artifact evidence + REAL semantics.

        The artifact is resolved through the durable store (id → row) so the
        context carries path/hash/kind evidence instead of a bare id; a
        missing/unready artifact refuses fail-closed BEFORE the mutation is
        archived as applied (the surrounding transaction rolls back).
        """
        artifact = self._session.get(Artifact, str(successor.mask_artifact_id))
        if artifact is None:
            raise CorrectionValidationError(
                "mask correction references an unknown mask artifact: "
                f"{successor.mask_artifact_id!r}"
            )
        if artifact.state != "ready":
            raise CorrectionValidationError(
                "mask artifact is not ready: "
                f"{artifact.id!r} state={artifact.state!r}"
            )
        if not artifact.sha256:
            raise CorrectionValidationError(
                f"mask artifact {artifact.id!r} carries no sha256 evidence"
            )
        segmentation = request.get("segmentation")
        if not isinstance(segmentation, dict) or not segmentation:
            raise CorrectionValidationError(
                "mask render effect requires non-empty segmentation semantics"
            )
        return {
            "version": RENDER_EFFECT_VERSION,
            "op": "mask",
            "target_layer_id": successor.logical_id,
            "target_segment_id": successor.id,
            "lineage_version": int(successor.lineage_version),
            "mask_artifact": {
                "artifact_id": artifact.id,
                "sha256": artifact.sha256,
                "relative_path": artifact.relative_path,
                "kind": artifact.kind,
                "byte_size": (
                    int(artifact.size_bytes or 0)
                    if artifact.size_bytes is not None
                    else None
                ),
            },
            "mask_semantics": {
                "version": MASK_SEMANTICS_VERSION,
                "source_generation": str(request["source_generation"]),
                "segmentation": segmentation,
                "confidence_source": str(request.get("confidence_source", "user")),
                "reasons": list(request.get("reasons") or ["mask correction"]),
            },
        }

    # ── validation helpers ───────────────────────────────────────────────

    @staticmethod
    def _validate_kind(correction_kind: str) -> None:
        if correction_kind not in S09_CORRECTION_KINDS:
            raise CorrectionValidationError(
                f"unknown correction kind {correction_kind!r}; expected one "
                f"of {S09_CORRECTION_KINDS}"
            )

    def _validated_request(
        self, correction_kind: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Fail-closed canonicalization BEFORE any write (zero mutation).

        S09-T05A-C1: the FULL closed-domain check for every kind lives
        here — canonical routes, bounded anchors, ordered frames and
        normalized provenance evidence — so an invalid request is refused
        before ``compute_impact`` AND before any pending row can be
        archived.  Confirm-time checks re-run defensively but must never
        be the first line of defense.
        """
        if not isinstance(request, dict):
            raise CorrectionValidationError("request must be a JSON object")
        _reject_non_finite(request)
        required: dict[str, tuple[str, ...]] = {
            "mask": ("occurrence_segment_id", "revision", "source_generation",
                     "mask_artifact_id", "segmentation"),
            "z_order": ("occurrence_segment_id", "revision", "source_generation",
                        "z_order"),
            "contact": ("contact_id", "revision"),
            "mesh_parts": ("motion_id", "revision", "transform"),
            "route_override": (
                "occurrence_segment_id",
                "route_from", "route_to", "anchor_x", "anchor_y",
                "start_frame", "end_frame", "override_reason",
            ),
        }
        missing = [key for key in required[correction_kind] if key not in request]
        if missing:
            raise CorrectionValidationError(
                f"{correction_kind} requires: {', '.join(missing)}"
            )
        if "revision" in request and int(request["revision"]) < 1:
            raise CorrectionValidationError("revision must be >= 1")
        if correction_kind == "z_order":
            z = int(request["z_order"])
            if not -1000000 <= z <= 1000000:
                raise CorrectionValidationError(
                    "z_order must be within [-1000000, 1000000]"
                )
        if correction_kind == "mesh_parts" and not isinstance(
            request["transform"], dict
        ):
            raise CorrectionValidationError("transform must be a JSON object")
        if correction_kind == "route_override":
            _validate_route_override_request(request)
        # Path-escape refusal on identifier-shaped values (fail closed).
        _reject_path_escape_ids(correction_kind, request)
        canonical: dict[str, Any] = json.loads(_canonical_json(request))
        return canonical

    @staticmethod
    def _required_provenance(
        request: dict[str, Any], correction_kind: str
    ) -> dict[str, Any]:
        """Manual lineage supersede REQUIRES explicit human provenance."""
        provenance = request.get("provenance")
        if (
            not isinstance(provenance, dict)
            or not provenance
        ):
            raise CorrectionValidationError(
                f"{correction_kind} correction requires non-empty provenance "
                "(human audit trail — never inherit machine provenance)"
            )
        _reject_non_finite(provenance)
        return provenance

    @staticmethod
    def _optional_provenance(request: dict[str, Any]) -> dict[str, Any] | None:
        provenance = request.get("provenance")
        if provenance is None:
            return None
        if not isinstance(provenance, dict):
            raise CorrectionValidationError("provenance must be a JSON object")
        _reject_non_finite(provenance)
        return provenance

    @staticmethod
    def _impact_payload(impact: CorrectionImpact) -> dict[str, Any]:
        return {
            "correction_kind": impact.correction_kind,
            "affected_occurrence_segment_ids": list(
                impact.affected_occurrence_segment_ids
            ),
            "affected_contact_ids": list(impact.affected_contact_ids),
            "affected_motion_ids": list(impact.affected_motion_ids),
            "affected_loop_ids": list(impact.affected_loop_ids),
            "affected_layer_ids": list(impact.affected_layer_ids),
            "affected_layer_labels": list(impact.affected_layer_labels),
            "route_override": impact.route_override,
            "counts": dict(impact.counts),
        }

    @staticmethod
    def _assert_equivalent(
        existing: S09Correction,
        project_id: str,
        video_item_id: str,
        correction_kind: str,
        request: dict[str, Any],
    ) -> None:
        if (
            existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.correction_kind != correction_kind
            or existing.request_json != _canonical_json(request)
        ):
            raise CorrectionConflictError(
                "an existing s09 correction is already bound to this "
                "idempotency/natural key with a DIFFERENT payload"
            )

    def _correction_row(
        self, workspace_id: str, correction_id: str
    ) -> S09Correction:
        row = self._session.scalar(
            select(S09Correction).where(
                S09Correction.id == correction_id,
                S09Correction.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise CorrectionNotFoundError(
                f"S09 correction {correction_id!r} not found in workspace"
            )
        return row

    def _assert_ownership(
        self, workspace_id: str, project_id: str, video_item_id: str
    ) -> None:
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise CorrectionConflictError("project ownership mismatch")
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise CorrectionConflictError("video item ownership mismatch")
