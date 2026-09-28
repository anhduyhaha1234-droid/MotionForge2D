"""Structural Evidence API routes (S08-A02-T01-R2).

Isolated router under ``/api/v2/structural-evidence`` (disjoint from every
legacy route and from ``/api/v2/object-intelligence``).  Built on top of the
VERIFIED durable core (``app.persistence.structural_evidence``) — R2 does NOT
modify persistence; if a core bug were exposed R2 would STOP with a
C1-core-correction finding instead of editing core.

Contract (R2 §4/§5):

- Segments: create current, get current, get historical (explicit), list
  current, list historical versions (explicit), update current (CAS), manual
  correction / supersede (CAS), lineage oldest -> newest.
- Motion / occlusion / contact: create / get / list / update (CAS).
- NO DELETE endpoints anywhere.
- Defaults: current generation + ACTIVE record only; historical is explicit
  and read-only; current and historical are never mixed.
- One request = one transaction: commit after a successful repository call,
  rollback before every mapped error; ORM objects are never returned (DTO
  boundary); every mutating endpoint is CAS-protected (stale revision -> 409).
- ``source_generation`` and ``logical_id`` are server/repository-owned: they
  are resolved from the backend authority / repository, never accepted from
  the client (an attempt is an unknown-field 422 at the schema boundary).

Stable error mapping: schema/enum/range -> 422; not found / cross-workspace
-> 404 (no existence leak); stale CAS / ownership / idempotency conflict ->
409; unexpected DB error -> rollback + fail closed (no raw SQL surfaced).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import OccurrenceSegment
from app.persistence.object_intelligence import RoleNotFoundError
from app.persistence.structural_evidence import (
    ContactConflictError,
    ContactNotFoundError,
    MalformedJsonError,
    MotionConflictError,
    MotionNotFoundError,
    OcclusionConflictError,
    OcclusionNotFoundError,
    OwnershipMismatchError,
    SegmentConflictError,
    SegmentNotFoundError,
    StructuralEvidenceRepository,
    parse_json,
)
from app.schemas.structural_evidence import (
    ContactCreateRequest,
    ContactData,
    ContactUpdateRequest,
    LineageResponse,
    MotionCreateRequest,
    MotionData,
    MotionUpdateRequest,
    OcclusionCreateRequest,
    OcclusionData,
    OcclusionUpdateRequest,
    PromptEvidence,
    SegmentCreateRequest,
    SegmentData,
    SegmentListResponse,
    SegmentSupersedeRequest,
    SegmentUpdateRequest,
    SupersedeResultData,
)

log = logging.getLogger("motionforge.structural-evidence")

# ── MF-END-13: source interaction facts (measurement-only producer) ──────────
from app.services import source_interaction_facts as sif  # noqa: E402
from app.services import source_role_tracks as srt  # noqa: E402


class _StructuralEvidenceRoute(APIRoute):
    """Router-local validation wrapper (C2-F6): sanitize NaN/Infinity and any
    Pydantic validation error into a stable 422 with a safe detail string.
    Prevents Starlette's ``allow_nan=False`` JSONResponse from echoing the raw
    body and crashing to 500 when the client sends NaN/Infinity."""

    def get_route_handler(self) -> Any:
        original = super().get_route_handler()

        async def _handler(request: Request) -> Any:
            try:
                return await original(request)
            except RequestValidationError as exc:
                # Build a safe, compact detail without echoing raw NaN floats
                try:
                    first = exc.errors()[0] if exc.errors() else {}
                    loc = ".".join(str(part) for part in first.get("loc", [])) or "body"
                    msg = first.get("msg", "validation error")
                    detail = f"{loc}: {msg}"
                except Exception:
                    detail = "validation error"
                return JSONResponse(status_code=422, content={"detail": detail})
            except ValidationError as exc:
                return JSONResponse(
                    status_code=422,
                    content={"detail": _first_validation_error(exc)},
                )

        return _handler


router = APIRouter(
    prefix="/api/v2/structural-evidence",
    tags=["structural-evidence"],
    route_class=_StructuralEvidenceRoute,
)
WORKSPACE_ID = DEFAULT_WORKSPACE_ID

#: Module-level FastAPI Body marker (B008: no function call in argument
#: defaults).  Kept for reference; body validation is now via typed DTOs with
#: ``extra="forbid"`` and ``allow_inf_nan=False`` (stable 422, never a 500).
_JSON_BODY: Any = Body(...)


def _repo(session: SessionDep) -> StructuralEvidenceRepository:
    return StructuralEvidenceRepository(session)



def _first_validation_error(err: ValidationError) -> str:
    """Compact, stable 422 detail: ``<field>: <message>`` for the FIRST error.

    The full Pydantic message is kept so the failing field is always visible
    in the response body (never a raw float/NaN that would break Starlette's
    ``allow_nan=False`` JSON renderer).
    """
    first = err.errors()[0]
    loc = ".".join(str(part) for part in first.get("loc", [])) or "body"
    return f"{loc}: {first.get('msg', 'validation error')}"



def _raise_mapped(session: SessionDep, err: Exception) -> None:
    """Rollback then raise a stable, machine-readable HTTP error (R2 §5).

    Order matters: not-found and conflict families first, then the
    backend-authoritative generation resolver (404), then value/JSON 422, and
    finally a fail-closed generic 500 (never a raw SQL error surfaced).
    """
    session.rollback()
    if isinstance(
        err,
        (
            SegmentNotFoundError,
            MotionNotFoundError,
            OcclusionNotFoundError,
            ContactNotFoundError,
        ),
    ):
        raise HTTPException(404, str(err)) from err
    if isinstance(
        err,
        (
            SegmentConflictError,
            MotionConflictError,
            OcclusionConflictError,
            ContactConflictError,
            OwnershipMismatchError,
        ),
    ):
        raise HTTPException(409, str(err)) from err
    if isinstance(err, RoleNotFoundError):
        raise HTTPException(404, str(err)) from err
    if isinstance(err, (ValueError, MalformedJsonError)):
        raise HTTPException(422, str(err)) from err
    log.exception("unexpected structural-evidence error")
    raise HTTPException(500, "internal server error") from err


def _evidence_dict(evidence: PromptEvidence | None) -> dict[str, Any] | None:
    """Convert strict prompt/segmentation evidence to the canonical payload.

    Only keys the client actually set are emitted (matching the repository's
    exact-shape contract); an evidence object with neither points nor boxes is
    treated as absent.
    """
    if evidence is None or (evidence.points is None and evidence.boxes is None):
        return None
    payload: dict[str, Any] = {}
    if evidence.points is not None:
        payload["points"] = [point.model_dump() for point in evidence.points]
    if evidence.boxes is not None:
        payload["boxes"] = [box.model_dump() for box in evidence.boxes]
    return payload


def _parse_evidence(raw: str | None) -> PromptEvidence | None:
    if raw is None:
        return None
    parsed = parse_json(raw)
    if not isinstance(parsed, dict):
        raise MalformedJsonError("segment evidence is not a JSON object (fail closed)")
    return PromptEvidence.model_validate(parsed)


def _current_state(
    repo: StructuralEvidenceRepository,
    workspace_id: str,
    record: Any,
) -> str:
    """Explicit current/historical state for one segment record (R2 §3).

    ``current`` = ACTIVE (not superseded) AND in the backend-authoritative
    current source generation; everything else is ``historical``.  The two
    states are never mixed.
    """
    if record.superseded_by_id is not None:
        return "historical"
    try:
        current = repo.current_generation(workspace_id, record.video_item_id)
    except Exception:  # pragma: no cover - repository scopes keep the video visible
        return "historical"
    return "current" if record.source_generation == current else "historical"


def _segment_data(
    record: Any,
    workspace_id: str,
    repo: Any = None,
    *,
    state: str | None = None,
) -> SegmentData:
    """Map a segment record (DTO or ORM row) to the read schema — never an
    ORM object leaves the router."""
    resolved_state = (
        state
        if state is not None
        else (
            _current_state(repo, workspace_id, record)
            if repo is not None
            else "historical"
        )
    )
    reasons = (
        list(record.reasons)
        if hasattr(record, "reasons")
        else _string_list(record.reasons_json)
    )
    provenance = (
        dict(record.provenance)
        if hasattr(record, "provenance")
        else _provenance_dict(record.provenance_json)
    )
    return SegmentData(
        id=record.id,
        logical_id=record.logical_id,
        lineage_version=record.lineage_version,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        role_id=record.role_id,
        scene_id=record.scene_id,
        name=record.name,
        kind=record.kind,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        source_generation=record.source_generation,
        source_job_id=record.source_job_id,
        prompt=_parse_evidence(record.prompt_json),
        segmentation=_parse_evidence(record.segmentation_json),
        mask_artifact_id=record.mask_artifact_id,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        visibility=record.visibility,
        z_order=record.z_order,
        superseded_by_id=record.superseded_by_id,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=reasons,
        provenance=provenance,
        state=resolved_state,
    )


def _string_list(raw: str | None) -> list[str]:
    parsed = parse_json(raw)
    if parsed is None:
        return []
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise MalformedJsonError("reasons_json is not an array of strings (fail closed)")
    return list(parsed)


def _provenance_dict(raw: str | None) -> dict[str, Any]:
    parsed = parse_json(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise MalformedJsonError("provenance_json is not an object (fail closed)")
    return dict(parsed)


def _active_segments(
    session: SessionDep,
    *,
    workspace_id: str,
    video_item_id: str,
    role_id: str | None,
    current_generation: str,
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    """Current-generation ACTIVE-only segment page (R2 default scope).

    The durable repository lists by source generation only; the current view
    must additionally exclude superseded (historical) rows so current and
    historical are never mixed.  This scoped read lives in the router (the
    verified core is not modified by R2).
    """
    filters = [
        OccurrenceSegment.workspace_id == workspace_id,
        OccurrenceSegment.video_item_id == video_item_id,
        OccurrenceSegment.source_generation == current_generation,
        OccurrenceSegment.superseded_by_id.is_(None),
    ]
    if role_id is not None:
        filters.append(OccurrenceSegment.role_id == role_id)
    total = int(
        session.scalar(select(func.count(OccurrenceSegment.id)).where(*filters)) or 0
    )
    rows = session.scalars(
        select(OccurrenceSegment)
        .where(*filters)
        .order_by(
            OccurrenceSegment.start_frame,
            OccurrenceSegment.end_frame,
            OccurrenceSegment.z_order,
            OccurrenceSegment.id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


# ── segments: create current ────────────────────────────────────────────────

@router.post("/segments", status_code=201)
@router.post("/segments/", status_code=201)
def create_segment(
    session: SessionDep,
    response: Response,
    body: SegmentCreateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> SegmentData:
    """Create a CURRENT occurrence segment (server-owned generation)."""
    payload = body
    repo = _repo(session)
    try:
        # R2: ``source_generation`` is server-owned — resolved from the
        # backend authority, never accepted from the client.
        source_generation = repo.current_generation(workspace_id, payload.video_item_id)
        record, created = repo.create_segment(
            workspace_id,
            payload.project_id,
            payload.video_item_id,
            payload.role_id,
            payload.scene_id,
            payload.name,
            payload.start_frame,
            payload.end_frame,
            payload.start_time_ms,
            payload.end_time_ms,
            source_generation,
            kind=payload.kind,
            source_job_id=payload.source_job_id,
            prompt=_evidence_dict(payload.prompt),
            segmentation=_evidence_dict(payload.segmentation),
            mask_artifact_id=payload.mask_artifact_id,
            algorithm=payload.algorithm,
            algorithm_version=payload.algorithm_version,
            confidence=payload.confidence,
            confidence_source=payload.confidence_source,
            reasons=payload.reasons,
            provenance=payload.provenance,
            visibility=payload.visibility,
            z_order=payload.z_order,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    if not created:
        # Idempotent replay: return the existing durable segment with 200.
        response.status_code = 200
    return _segment_data(record, workspace_id, state="current")


# ── segments: list current ──────────────────────────────────────────────────

@router.get("/segments")
@router.get("/segments/")
def list_current_segments(
    session: SessionDep,
    video_item_id: Annotated[str, Query(description="video item to scope the current generation")],
    workspace_id: str = WORKSPACE_ID,
    role_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SegmentListResponse:
    """List CURRENT segments (current generation + active record only).

    The current generation is inherently per-video, so ``video_item_id`` is
    required — without it there is no single backend current to scope to.
    Historical rows are never mixed into this view.
    """
    repo = _repo(session)
    try:
        current_generation = repo.current_generation(workspace_id, video_item_id)
        rows, total = _active_segments(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            role_id=role_id,
            current_generation=current_generation,
            limit=limit,
            offset=offset,
        )
    except Exception as err:
        _raise_mapped(session, err)
    return SegmentListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        scope="current",
        current_generation=current_generation,
        source_generation=None,
        segments=[_segment_data(row, workspace_id, state="current") for row in rows],
    )


# ── segments: get current ───────────────────────────────────────────────────

@router.get("/segments/current/{segment_id}")
@router.get("/segments/current/{segment_id}/")
def get_current_segment(
    segment_id: str,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> SegmentData:
    """Get the CURRENT ACTIVE segment.

    A superseded (historical) row of the same generation is 404 under the
    current scope — no existence leak; historical access is the separate
    explicit contract.
    """
    repo = _repo(session)
    try:
        record = repo.get_segment(workspace_id, segment_id, only_current=True)
        if record.superseded_by_id is not None:
            raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
    except Exception as err:
        _raise_mapped(session, err)
    return _segment_data(record, workspace_id, state="current")


# ── segments: list historical (explicit) ────────────────────────────────────

@router.get("/segments/historical")
@router.get("/segments/historical/")
def list_historical_segments(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    video_item_id: str | None = None,
    source_generation: str | None = None,
    logical_id: str | None = None,
    role_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SegmentListResponse:
    """List historical segment versions — EXPLICIT and read-only.

    Exactly one of ``source_generation`` (all rows of one generation) or
    ``logical_id`` (every version of one lineage, oldest -> newest) must be
    supplied; a non-explicit historical view is refused.
    """
    repo = _repo(session)
    if source_generation is None and logical_id is None:
        raise HTTPException(
            422,
            "historical segment view requires an explicit source_generation "
            "or logical_id (historical is explicit and read-only)",
        )
    if source_generation is not None and logical_id is not None:
        raise HTTPException(
            422,
            "historical segment view requires exactly one of source_generation "
            "or logical_id -- both were provided (provide exactly one)",
        )
    try:
        if logical_id is not None:
            all_records = repo.get_segment_by_logical_id(workspace_id, logical_id)
            # C2-F5: historical view must exclude the active current successor.
            # Truly historical = superseded OR stale generation.
            filtered: list[Any] = []
            for rec in all_records:
                # Determine if this record is truly historical
                is_superseded = rec.superseded_by_id is not None
                # Check if stale generation (need video's current generation)
                try:
                    cur_gen = repo.current_generation(workspace_id, rec.video_item_id)
                except Exception:
                    cur_gen = None
                is_stale_gen = cur_gen is not None and rec.source_generation != cur_gen
                if is_superseded or is_stale_gen:
                    filtered.append(rec)
            # Pagination after filter (C2-F5)
            total = len(filtered)
            # Apply offset/limit to filtered historical set
            paged = filtered[offset : offset + limit] if limit is not None else filtered[offset:]
            current_generation = None
            scope = "historical"
            rows = [
                _segment_data(record, workspace_id, state="historical") for record in paged
            ]
        else:
            # C3 BLOCKER 2: push historical filtering into SQL/repository -- no 10k cap,
            # no full-history load into RAM; total/offset/limit applied after filter in SQL
            assert source_generation is not None  # narrowed by exactly-one check above
            paged2, total = repo.list_historical_segments(
                workspace_id,
                source_generation,
                video_item_id=video_item_id,
                role_id=role_id,
                limit=limit,
                offset=offset,
            )
            current_generation = (
                repo.current_generation(workspace_id, video_item_id)
                if video_item_id is not None
                else None
            )
            scope = "historical"
            rows = [
                _segment_data(record, workspace_id, state="historical") for record in paged2
            ]
    except Exception as err:
        _raise_mapped(session, err)
    return SegmentListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        scope=scope,
        current_generation=current_generation,
        source_generation=source_generation if logical_id is None else None,
        segments=rows,
    )


# ── segments: get historical (explicit) ─────────────────────────────────────

@router.get("/segments/historical/{segment_id}")
@router.get("/segments/historical/{segment_id}/")
def get_historical_segment(
    segment_id: str,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    generation: str | None = None,
) -> SegmentData:
    """Get ONE segment under the explicit historical scope (read-only).

    ``generation`` may pin the exact view; a row not in that generation is
    404 (no existence leak).  Without ``generation`` the row is returned under
    its true explicit state.
    """
    repo = _repo(session)
    try:
        record = repo.get_segment(
            workspace_id, segment_id, only_current=False, source_generation=generation
        )
    except Exception as err:
        _raise_mapped(session, err)
    return _segment_data(record, workspace_id, repo)


# ── segments: update current (CAS) ──────────────────────────────────────────

@router.patch("/segments/current/{segment_id}")
@router.patch("/segments/current/{segment_id}/")
def update_segment(
    segment_id: str,
    session: SessionDep,
    body: SegmentUpdateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> SegmentData:
    """CAS in-place update of the CURRENT ACTIVE segment.

    A superseded (historical) segment or a stale ``revision`` is refused with
    ZERO mutation (409).
    """
    payload = body
    repo = _repo(session)
    try:
        record = repo.update_segment(
            workspace_id,
            segment_id,
            payload.revision,
            name=payload.name,
            kind=payload.kind,
            start_frame=payload.start_frame,
            end_frame=payload.end_frame,
            start_time_ms=payload.start_time_ms,
            end_time_ms=payload.end_time_ms,
            prompt=_evidence_dict(payload.prompt),
            segmentation=_evidence_dict(payload.segmentation),
            mask_artifact_id=payload.mask_artifact_id,
            algorithm=payload.algorithm,
            algorithm_version=payload.algorithm_version,
            confidence=payload.confidence,
            reasons=payload.reasons,
            provenance=payload.provenance,
            visibility=payload.visibility,
            z_order=payload.z_order,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    return _segment_data(record, workspace_id, state="current")


# ── segments: manual correction / supersede (CAS) ───────────────────────────

@router.post("/segments/current/{segment_id}/supersede", status_code=201)
@router.post("/segments/current/{segment_id}/supersede/", status_code=201)
def supersede_segment(
    segment_id: str,
    session: SessionDep,
    body: SegmentSupersedeRequest,
    workspace_id: str = WORKSPACE_ID,
) -> SupersedeResultData:
    """AUDITED correction (C1-F1) — manual user correction in the current
    generation (workflow A) or re-analysis transition to the backend current
    generation (workflow B).

    The router resolves the backend current generation (server-owned — never
    accepted from the client) and the repository decides the workflow.  The
    response shows the predecessor (historical), the successor (current),
    their shared logical lineage, revisions and provenance — no silent
    mutation.
    """
    payload = body
    repo = _repo(session)
    try:
        # Server-owned generation authority for BOTH workflows.
        prior = repo.get_segment(workspace_id, segment_id)
        source_generation = repo.current_generation(
            workspace_id, prior.video_item_id
        )
        predecessor, successor = repo.supersede_segment(
            workspace_id,
            segment_id,
            payload.revision,
            source_generation=source_generation,
            name=payload.name,
            kind=payload.kind,
            start_frame=payload.start_frame,
            end_frame=payload.end_frame,
            start_time_ms=payload.start_time_ms,
            end_time_ms=payload.end_time_ms,
            source_job_id=payload.source_job_id,
            target_role_id=payload.target_role_id,
            prompt=_evidence_dict(payload.prompt),
            segmentation=_evidence_dict(payload.segmentation),
            mask_artifact_id=payload.mask_artifact_id,
            algorithm=payload.algorithm,
            algorithm_version=payload.algorithm_version,
            confidence=payload.confidence,
            confidence_source=payload.confidence_source,
            reasons=payload.reasons,
            provenance=payload.provenance,
            visibility=payload.visibility,
            z_order=payload.z_order,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    return SupersedeResultData(
        predecessor=_segment_data(predecessor, workspace_id, state="historical"),
        successor=_segment_data(successor, workspace_id, state="current"),
        logical_id=predecessor.logical_id,
        source_generation=successor.source_generation,
        predecessor_revision=predecessor.revision,
        successor_revision=successor.revision,
    )


# ── segments: lineage ───────────────────────────────────────────────────────

@router.get("/segments/{segment_id}/lineage")
@router.get("/segments/{segment_id}/lineage/")
def get_lineage(
    segment_id: str,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> LineageResponse:
    """Full lineage of a segment from ANY version, OLDEST -> NEWEST (R1 F7)."""
    repo = _repo(session)
    try:
        records = repo.segment_lineage(workspace_id, segment_id)
    except Exception as err:
        _raise_mapped(session, err)
    return LineageResponse(
        workspace_id=workspace_id,
        logical_id=records[0].logical_id,
        versions=[_segment_data(record, workspace_id, repo) for record in records],
    )


# ── motion ──────────────────────────────────────────────────────────────────

@router.post("/motions", status_code=201)
@router.post("/motions/", status_code=201)
def create_motion(
    session: SessionDep,
    response: Response,
    body: MotionCreateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> MotionData:
    payload = body
    repo = _repo(session)
    try:
        record, created = repo.create_motion(
            workspace_id,
            payload.occurrence_segment_id,
            payload.transform_type,
            dict(payload.transform),
            point_track_flow_ref=(
                payload.point_track_flow_ref if payload.point_track_flow_ref is not None else None
            ),
            start_frame=payload.start_frame,
            end_frame=payload.end_frame,
            start_time_ms=payload.start_time_ms,
            end_time_ms=payload.end_time_ms,
            algorithm=payload.algorithm,
            algorithm_version=payload.algorithm_version,
            confidence=payload.confidence,
            confidence_source=payload.confidence_source,
            reasons=payload.reasons,
            provenance=payload.provenance,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    if not created:
        response.status_code = 200
    return MotionData(
        id=record.id,
        workspace_id=record.workspace_id,
        occurrence_segment_id=record.occurrence_segment_id,
        transform_type=record.transform_type,
        transform=dict(record.transform),
        point_track_flow_ref=record.point_track_flow_ref,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


@router.get("/motions")
@router.get("/motions/")
def list_motions(
    session: SessionDep,
    segment_id: Annotated[str, Query(description="segment to list motions for")],
    workspace_id: str = WORKSPACE_ID,
) -> list[MotionData]:
    repo = _repo(session)
    try:
        records = repo.list_motions(workspace_id, segment_id)
    except Exception as err:
        _raise_mapped(session, err)
    return [
        MotionData(
            id=record.id,
            workspace_id=record.workspace_id,
            occurrence_segment_id=record.occurrence_segment_id,
            transform_type=record.transform_type,
            transform=dict(record.transform),
            point_track_flow_ref=record.point_track_flow_ref,
            start_frame=record.start_frame,
            end_frame=record.end_frame,
            start_time_ms=record.start_time_ms,
            end_time_ms=record.end_time_ms,
            algorithm=record.algorithm,
            algorithm_version=record.algorithm_version,
            confidence=record.confidence,
            confidence_source=record.confidence_source,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            reasons=list(record.reasons or []),
            provenance=dict(record.provenance or {}),
        )
        for record in records
    ]


@router.get("/motions/{motion_id}")
@router.get("/motions/{motion_id}/")
def get_motion(
    motion_id: str,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> MotionData:
    repo = _repo(session)
    try:
        record = repo.get_motion(workspace_id, motion_id)
    except Exception as err:
        _raise_mapped(session, err)
    return MotionData(
        id=record.id,
        workspace_id=record.workspace_id,
        occurrence_segment_id=record.occurrence_segment_id,
        transform_type=record.transform_type,
        transform=dict(record.transform),
        point_track_flow_ref=record.point_track_flow_ref,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


@router.patch("/motions/{motion_id}")
@router.patch("/motions/{motion_id}/")
def update_motion(
    motion_id: str,
    session: SessionDep,
    body: MotionUpdateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> MotionData:
    payload = body
    repo = _repo(session)
    try:
        record = repo.update_motion(
            workspace_id,
            motion_id,
            payload.revision,
            transform=dict(payload.transform) if payload.transform is not None else None,
            point_track_flow_ref=payload.point_track_flow_ref,
            end_frame=payload.end_frame,
            end_time_ms=payload.end_time_ms,
            confidence=payload.confidence,
            reasons=payload.reasons,
            provenance=payload.provenance,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    return MotionData(
        id=record.id,
        workspace_id=record.workspace_id,
        occurrence_segment_id=record.occurrence_segment_id,
        transform_type=record.transform_type,
        transform=dict(record.transform),
        point_track_flow_ref=record.point_track_flow_ref,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


# ── occlusion ───────────────────────────────────────────────────────────────

@router.post("/occlusions", status_code=201)
@router.post("/occlusions/", status_code=201)
def create_occlusion(
    session: SessionDep,
    response: Response,
    body: OcclusionCreateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> OcclusionData:
    payload = body
    repo = _repo(session)
    try:
        record, created = repo.create_occlusion(
            workspace_id,
            payload.project_id,
            payload.video_item_id,
            payload.occluder_segment_id,
            payload.occludee_segment_id,
            payload.start_frame,
            payload.end_frame,
            payload.start_time_ms,
            payload.end_time_ms,
            algorithm=payload.algorithm,
            algorithm_version=payload.algorithm_version,
            confidence=payload.confidence,
            confidence_source=payload.confidence_source,
            reasons=payload.reasons,
            provenance=payload.provenance,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    if not created:
        response.status_code = 200
    return OcclusionData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        occluder_segment_id=record.occluder_segment_id,
        occludee_segment_id=record.occludee_segment_id,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


@router.get("/occlusions")
@router.get("/occlusions/")
def list_occlusions(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    segment_id: str | None = None,
) -> list[OcclusionData]:
    repo = _repo(session)
    records = repo.list_occlusions(workspace_id, segment_id=segment_id)
    return [
        OcclusionData(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            occluder_segment_id=record.occluder_segment_id,
            occludee_segment_id=record.occludee_segment_id,
            start_frame=record.start_frame,
            end_frame=record.end_frame,
            start_time_ms=record.start_time_ms,
            end_time_ms=record.end_time_ms,
            algorithm=record.algorithm,
            algorithm_version=record.algorithm_version,
            confidence=record.confidence,
            confidence_source=record.confidence_source,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            reasons=list(record.reasons or []),
            provenance=dict(record.provenance or {}),
        )
        for record in records
    ]


@router.get("/occlusions/{occlusion_id}")
@router.get("/occlusions/{occlusion_id}/")
def get_occlusion(
    occlusion_id: str,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> OcclusionData:
    repo = _repo(session)
    try:
        record = repo.get_occlusion(workspace_id, occlusion_id)
    except Exception as err:
        _raise_mapped(session, err)
    return OcclusionData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        occluder_segment_id=record.occluder_segment_id,
        occludee_segment_id=record.occludee_segment_id,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


@router.patch("/occlusions/{occlusion_id}")
@router.patch("/occlusions/{occlusion_id}/")
def update_occlusion(
    occlusion_id: str,
    session: SessionDep,
    body: OcclusionUpdateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> OcclusionData:
    payload = body
    repo = _repo(session)
    try:
        record = repo.update_occlusion(
            workspace_id,
            occlusion_id,
            payload.revision,
            end_frame=payload.end_frame,
            end_time_ms=payload.end_time_ms,
            confidence=payload.confidence,
            reasons=payload.reasons,
            provenance=payload.provenance,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    return OcclusionData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        occluder_segment_id=record.occluder_segment_id,
        occludee_segment_id=record.occludee_segment_id,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


# ── contact ─────────────────────────────────────────────────────────────────

@router.post("/contacts", status_code=201)
@router.post("/contacts/", status_code=201)
def create_contact(
    session: SessionDep,
    response: Response,
    body: ContactCreateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> ContactData:
    payload = body
    repo = _repo(session)
    try:
        record, created = repo.create_contact(
            workspace_id,
            payload.project_id,
            payload.video_item_id,
            payload.source_segment_id,
            payload.target_segment_id,
            payload.contact_kind,
            payload.start_frame,
            payload.end_frame,
            payload.start_time_ms,
            payload.end_time_ms,
            algorithm=payload.algorithm,
            algorithm_version=payload.algorithm_version,
            confidence=payload.confidence,
            confidence_source=payload.confidence_source,
            reasons=payload.reasons,
            provenance=payload.provenance,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    if not created:
        response.status_code = 200
    return ContactData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        source_segment_id=record.source_segment_id,
        target_segment_id=record.target_segment_id,
        contact_kind=record.contact_kind,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


@router.get("/contacts")
@router.get("/contacts/")
def list_contacts(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    segment_id: str | None = None,
) -> list[ContactData]:
    repo = _repo(session)
    records = repo.list_contacts(workspace_id, segment_id=segment_id)
    return [
        ContactData(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            source_segment_id=record.source_segment_id,
            target_segment_id=record.target_segment_id,
            contact_kind=record.contact_kind,
            start_frame=record.start_frame,
            end_frame=record.end_frame,
            start_time_ms=record.start_time_ms,
            end_time_ms=record.end_time_ms,
            algorithm=record.algorithm,
            algorithm_version=record.algorithm_version,
            confidence=record.confidence,
            confidence_source=record.confidence_source,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            reasons=list(record.reasons or []),
            provenance=dict(record.provenance or {}),
        )
        for record in records
    ]


@router.get("/contacts/{contact_id}")
@router.get("/contacts/{contact_id}/")
def get_contact(
    contact_id: str,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> ContactData:
    repo = _repo(session)
    try:
        record = repo.get_contact(workspace_id, contact_id)
    except Exception as err:
        _raise_mapped(session, err)
    return ContactData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        source_segment_id=record.source_segment_id,
        target_segment_id=record.target_segment_id,
        contact_kind=record.contact_kind,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )


@router.patch("/contacts/{contact_id}")
@router.patch("/contacts/{contact_id}/")
def update_contact(
    contact_id: str,
    session: SessionDep,
    body: ContactUpdateRequest,
    workspace_id: str = WORKSPACE_ID,
) -> ContactData:
    payload = body
    repo = _repo(session)
    try:
        record = repo.update_contact(
            workspace_id,
            contact_id,
            payload.revision,
            end_frame=payload.end_frame,
            end_time_ms=payload.end_time_ms,
            confidence=payload.confidence,
            reasons=payload.reasons,
            provenance=payload.provenance,
        )
        session.commit()
    except Exception as err:
        _raise_mapped(session, err)
    return ContactData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        source_segment_id=record.source_segment_id,
        target_segment_id=record.target_segment_id,
        contact_kind=record.contact_kind,
        start_frame=record.start_frame,
        end_frame=record.end_frame,
        start_time_ms=record.start_time_ms,
        end_time_ms=record.end_time_ms,
        algorithm=record.algorithm,
        algorithm_version=record.algorithm_version,
        confidence=record.confidence,
        confidence_source=record.confidence_source,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reasons=list(record.reasons or []),
        provenance=dict(record.provenance or {}),
    )
# ── source interaction facts (MF-END-13) ─────────────────────────────────────


class _SourceFactsPublishBody(BaseModel):
    """Bounded request: server-owned workspace; no client paths/authority."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    project_id: str = Field(..., min_length=1, max_length=36)
    video_item_id: str = Field(..., min_length=1, max_length=36)
    #: The sealed MF-END-12 track artifact (inline; the server never reads a
    #: client path).  Exactly one of ``track_artifact`` / ``artifact`` is used.
    track_artifact: dict[str, Any] | None = None
    #: role_id -> occurrence_segment_id for REAL current segments.
    bindings: dict[str, str]
    #: Optional prebuilt + sealed facts artifact (re-verified, never trusted).
    artifact: dict[str, Any] | None = None
    idempotency_prefix: str | None = Field(None, min_length=1, max_length=120)


def _source_facts_status(err: sif.SourceFactsError) -> int:
    if err.code in (sif.CODE_FACT_CONFLICT, sif.CODE_OUTPUT_OVERWRITE):
        return 409
    return 422


@router.post("/source-interaction-facts", status_code=201)
@router.post("/source-interaction-facts/", status_code=201)
def publish_source_interaction_facts(
    session: SessionDep,
    response: Response,
    body: _SourceFactsPublishBody,
    workspace_id: str = WORKSPACE_ID,
) -> dict[str, Any]:
    """Publish measured source facts through the structural-evidence authority.

    The facts are derived from the supplied REAL track artifact (or an
    already-sealed facts artifact is re-verified) and written ONLY through
    ``StructuralEvidenceRepository`` — both endpoints of every contact and
    occlusion must be real current segments, otherwise the publish refuses
    with ``SOURCE_FACTS_SECOND_SEGMENT_MISSING`` (no fake segment is created).
    """
    repo = _repo(session)
    try:
        if body.artifact is None:
            if body.track_artifact is None:
                raise sif.SourceFactsError(
                    sif.CODE_MISSING_DATA,
                    "one of track_artifact / artifact is required",
                )
            tracks = srt.RoleTracksArtifact.from_payload(body.track_artifact)
            facts: Any = sif.build_artifact(tracks=tracks)
        else:
            facts = sif.FactSet(payload=dict(body.artifact))
            violations = sif.check_artifact(facts)
            if violations:
                raise sif.SourceFactsError(
                    sif.CODE_ARTIFACT_INVALID, f"artifact invalid: {list(violations)}"
                )
        segment_ranges: dict[str, dict[str, int]] = {}
        for segment_id in sorted(set(dict(body.bindings).values())):
            record = repo.get_segment(workspace_id, segment_id)
            segment_ranges[segment_id] = {
                "start_frame": int(record.start_frame),
                "end_frame": int(record.end_frame),
            }
        outcome = sif.publish_facts(
            session,
            workspace_id=workspace_id,
            project_id=body.project_id,
            video_item_id=body.video_item_id,
            artifact=facts,
            bindings=body.bindings,
            segment_ranges=segment_ranges,
            idempotency_prefix=body.idempotency_prefix,
        )
        session.commit()
    except sif.SourceFactsError as err:
        session.rollback()
        raise HTTPException(
            status_code=_source_facts_status(err), detail=err.as_dict()
        ) from err
    except srt.RoleTracksError as err:
        session.rollback()
        raise HTTPException(
            status_code=422, detail={"code": err.code, "message": err.detail}
        ) from err
    except Exception as err:
        _raise_mapped(session, err)
    created = (
        outcome.contacts_created + outcome.occlusions_created + outcome.motions_created
    )
    if created == 0:
        response.status_code = 200
    return {
        "artifact_digest": outcome.artifact_digest,
        "algorithm": sif.ALGORITHM,
        "policy_version": sif.POLICY_VERSION,
        "contacts_created": outcome.contacts_created,
        "contacts_replayed": outcome.contacts_replayed,
        "occlusions_created": outcome.occlusions_created,
        "occlusions_replayed": outcome.occlusions_replayed,
        "motions_created": outcome.motions_created,
        "motions_replayed": outcome.motions_replayed,
        "segment_ids": list(outcome.segment_ids),
    }


@router.get("/source-interaction-facts")
@router.get("/source-interaction-facts/")
def list_source_interaction_facts(
    session: SessionDep,
    video_item_id: Annotated[str, Query(min_length=1, max_length=36)],
    workspace_id: str = WORKSPACE_ID,
) -> dict[str, Any]:
    """Read the published source facts for one video item (no side effects)."""
    rows = _repo(session).list_source_algorithm_facts(
        workspace_id, video_item_id, algorithm=sif.ALGORITHM
    )
    return {
        "video_item_id": video_item_id,
        "algorithm": sif.ALGORITHM,
        "contacts": rows["contacts"],
        "occlusions": rows["occlusions"],
        "motions": rows["motions"],
    }

