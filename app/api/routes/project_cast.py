"""Project Cast Mapping API routes (S07-T01 + S07-T02 picker/compat).

Isolated router under /api/v2/project-cast (disjoint from every legacy route).
Built on the verified durable core app.persistence.project_cast — this layer
is the strict API boundary (no business logic, no silent fallback).

Contract:
- Create (POST): idempotent via idempotency_key; equivalent replay 200, conflict 409;  # noqa: E501
  compatibility enforced via authoritative repo policy.
- Get (GET /{id}): single mapping, workspace-isolated, 404 no leak.
- List (GET /): paginated, optionally filtered by project_id, workspace-isolated.
- Update (PATCH /{id}): CAS with revision, stale 409, concurrent one winner; compatibility enforced.
- Delete (DELETE /{id}): CAS required, missing revision → 422, stale → 409, cross-workspace → 404.
- Picker (GET /picker/packs): browse packs, published only, deterministic.
- Compatibility (POST /compatibility/evaluate): deterministic pure eval via same repo function.
- Strict schemas: extra=forbid, strict=True → unknown field 422, no wrong coercion.
- No client workspace authority: workspace_id is server-owned DEFAULT_WORKSPACE_ID.
- Deterministic serialization via typed Pydantic read models.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import SessionDep, get_managed_root
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    Character,
    CharacterPackVersion,
    ObjectRole,
    ProjectCastMapping,
)
from app.persistence.project_cast import (
    ProjectCastConflictError,
    ProjectCastNotFoundError,
    ProjectCastOwnershipError,
    ProjectCastRepository,
    SeriesCastConflictError,
    SeriesCastEntryInput,
    SeriesCastNotFoundError,
    SeriesCastOwnershipError,
    SeriesCastRepository,
    SeriesCastSnapshotRecord,
    SeriesCastStaleError,
    evaluate_compatibility,
)
from app.schemas.cast_recommendation import (
    CastCandidateData,
    CastRecommendationRequest,
    CastRecommendationResult,
    CastRoleRequirement,
    RoleRecommendationData,
)
from app.schemas.project_cast import (
    CastConfirmRequest,
    CastConfirmResponse,
    CastConfirmTraceData,
    CastConfirmWarningData,
    CompatibilityEvaluateRequest,
    CompatibilityEvaluateResponse,
    PickerPackItem,
    PickerPacksResponse,
    ProjectCastCreateRequest,
    ProjectCastData,
    ProjectCastListResponse,
    ProjectCastUpdateRequest,
    SeriesCastApplyEntryData,
    SeriesCastApplyRequest,
    SeriesCastApplyResponse,
    SeriesCastEntryData,
    SeriesCastReferenceData,
    SeriesCastSnapshotCreateRequest,
    SeriesCastSnapshotData,
    SeriesCastSnapshotListResponse,
)
from app.services.cast_recommendation import (
    AdvisoryClient,
    CastRecommendationInputError,
    CastRecommendationNotFoundError,
    recommend_cast,
)

router = APIRouter(prefix="/api/v2/project-cast", tags=["project-cast"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_mapping(
    body: ProjectCastCreateRequest,
    session: SessionDep,
    response: Response,
    ) -> ProjectCastData:
    repo = ProjectCastRepository(session)
    try:
        record, created = repo.create_mapping(
            workspace_id=WORKSPACE_ID,
            project_id=body.project_id,
            object_role_id=body.object_role_id,
            character_id=body.character_id,
            pack_version_id=body.pack_version_id,
            idempotency_key=body.idempotency_key,
            fallback_acknowledged=body.fallback_acknowledged,
        )
        session.commit()
    except ProjectCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "cast mapping conflict") from err
    if not created:
        response.status_code = 200
    return ProjectCastData.from_record(record)


@router.get("/picker/packs", status_code=200)
def picker_packs(
    session: SessionDep,
        q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PickerPacksResponse:
    from sqlalchemy import func as _func

    filters = [
        CharacterPackVersion.workspace_id == WORKSPACE_ID,
        CharacterPackVersion.status == "published",
    ]
    base_q = (
        select(CharacterPackVersion, Character)
        .join(Character, Character.id == CharacterPackVersion.character_id)
        .where(*filters)
    )
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        base_q = base_q.where(
            (_func.lower(Character.name).like(term))
            | (_func.lower(Character.code).like(term))
            | (_func.lower(CharacterPackVersion.id).like(term))
        )
    count_q = select(_func.count()).select_from(base_q.subquery())
    total = int(session.scalar(count_q) or 0)
    rows = session.execute(
        base_q.options(joinedload(CharacterPackVersion.assets))
        .order_by(CharacterPackVersion.created_at.desc(), CharacterPackVersion.id)
        .offset(offset)
        .limit(limit)
    ).unique().all()
    packs: list[PickerPackItem] = []
    for pack, char in rows:
        packs.append(
            PickerPackItem(
                id=pack.id,
                character_id=pack.character_id,
                workspace_id=pack.workspace_id,
                version=pack.version,
                status=pack.status,
                character_name=char.name,
                character_code=char.code,
                character_type=char.character_type,
                symmetry=char.symmetry,
                published_at=pack.published_at,
                revision=pack.revision,
                created_at=pack.created_at,
                updated_at=pack.updated_at,
                asset_count=len(pack.assets or []),
                pose_slots=[a.pose_slot for a in (pack.assets or [])],
            )
        )
    return PickerPacksResponse(
        workspace_id=WORKSPACE_ID,
        limit=limit,
        offset=offset,
        total=total,
        packs=packs,
        query=q,
    )


@router.post("/compatibility/evaluate", status_code=200)
def evaluate_compatibility_route(
    body: CompatibilityEvaluateRequest,
    session: SessionDep,
    ) -> CompatibilityEvaluateResponse:
    pack = session.get(CharacterPackVersion, body.pack_version_id)
    char_id = pack.character_id if pack is not None else ""
    result = evaluate_compatibility(
        session,
        workspace_id=WORKSPACE_ID,
        project_id=body.project_id,
        object_role_id=body.object_role_id,
        character_id=char_id,
        pack_version_id=body.pack_version_id,
        expected_revision=body.expected_revision,
        mapping_id=body.mapping_id,
    )
    return CompatibilityEvaluateResponse(
        compatible=result.compatible,
        reasons=result.reasons,
        fallback_allowed=result.fallback_allowed,
        fallback_description=result.fallback_description,
        blocked=result.blocked,
        pinned_version_id=result.pinned_version_id,
        current_revision=result.current_revision,
        workspace_id=result.workspace_id,
    )


@router.get("", status_code=200)
@router.get("/", status_code=200)
def list_mappings(
    session: SessionDep,
        project_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectCastListResponse:
    repo = ProjectCastRepository(session)
    try:
        records, total = repo.list_mappings(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
    except ProjectCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return ProjectCastListResponse(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        limit=limit,
        offset=offset,
        total=total,
        mappings=[ProjectCastData.from_record(r) for r in records],
    )


@router.get("/{mapping_id:uuid}", status_code=200)
@router.get("/{mapping_id:uuid}/", status_code=200)
def get_mapping(
    mapping_id: uuid.UUID,
    session: SessionDep,
    ) -> ProjectCastData:
    repo = ProjectCastRepository(session)
    try:
        record = repo.get_mapping(str(mapping_id), WORKSPACE_ID)
    except ProjectCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return ProjectCastData.from_record(record)


@router.patch("/{mapping_id:uuid}", status_code=200)
@router.patch("/{mapping_id:uuid}/", status_code=200)
def update_mapping(
    mapping_id: uuid.UUID,
    body: ProjectCastUpdateRequest,
    session: SessionDep,
    ) -> ProjectCastData:
    repo = ProjectCastRepository(session)
    try:
        record = repo.update_mapping(
            str(mapping_id),
            WORKSPACE_ID,
            expected_revision=body.revision,
            pack_version_id=body.pack_version_id,
            character_id=body.character_id,
            fallback_acknowledged=body.fallback_acknowledged,
        )
        session.commit()
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    return ProjectCastData.from_record(record)


@router.delete("/{mapping_id:uuid}", status_code=204)
@router.delete("/{mapping_id:uuid}/", status_code=204)
def delete_mapping(
    mapping_id: uuid.UUID,
    session: SessionDep,
        revision: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    repo = ProjectCastRepository(session)
    # F-C: workspace-scoped lookup MUST precede the revision requirement so a
    # cross-workspace mapping id yields 404 (no existence leak) even when the
    # caller omitted revision; only a mapping that exists in THIS workspace
    # proceeds to the 422 missing-revision branch below.
    try:
        repo.get_mapping(str(mapping_id), WORKSPACE_ID)
    except ProjectCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    if revision is None:
        raise HTTPException(422, "revision is required for delete")
    try:
        repo.delete_mapping(str(mapping_id), WORKSPACE_ID, expected_revision=revision)
        session.commit()
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    return Response(status_code=204)


# ── MF-END-05: series cast snapshot ("series pin") ───────────────────────────
#
# The durable freeze ("snapshot") and the copy-to-new-video operation ride the
# EXISTING per-video cast authority (ProjectCastRepository.create_mapping);
# these routes are the strict API boundary over app.persistence.project_cast.


def _series_snapshot_data(record: SeriesCastSnapshotRecord) -> SeriesCastSnapshotData:
    return SeriesCastSnapshotData(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        snapshot_index=record.snapshot_index,
        entries_sha256=record.entries_sha256,
        created_at=record.created_at,
        updated_at=record.updated_at,
        entries=[
            SeriesCastEntryData(
                role_key=entry.role_key,
                character_id=entry.character_id,
                pack_version_id=entry.pack_version_id,
                pack_contract_version=entry.pack_contract_version,
                manifest_sha256=entry.manifest_sha256,
                style_version=entry.style_version,
                references=[
                    SeriesCastReferenceData(
                        pose_slot=ref.pose_slot,
                        artifact_id=ref.artifact_id,
                        sha256=ref.sha256,
                    )
                    for ref in entry.references
                ],
            )
            for entry in record.entries
        ],
    )


@router.post("/series-cast/snapshots", status_code=201)
@router.post("/series-cast/snapshots/", status_code=201)
def freeze_series_cast_snapshot(
    body: SeriesCastSnapshotCreateRequest,
    session: SessionDep,
    response: Response,
) -> SeriesCastSnapshotData:
    repo = SeriesCastRepository(session)
    try:
        record, created = repo.freeze_snapshot(
            workspace_id=WORKSPACE_ID,
            project_id=body.project_id,
            entries=[
                SeriesCastEntryInput(
                    role_key=entry.role_key,
                    character_id=entry.character_id,
                    pack_version_id=entry.pack_version_id,
                    style_version=entry.style_version,
                )
                for entry in body.entries
            ],
        )
        session.commit()
    except SeriesCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except SeriesCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except SeriesCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "series cast snapshot conflict") from err
    if not created:
        response.status_code = 200
    return _series_snapshot_data(record)


@router.get("/series-cast/snapshots", status_code=200)
@router.get("/series-cast/snapshots/", status_code=200)
def list_series_cast_snapshots(
    session: SessionDep,
    project_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SeriesCastSnapshotListResponse:
    repo = SeriesCastRepository(session)
    try:
        records, total = repo.list_snapshots(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
    except SeriesCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return SeriesCastSnapshotListResponse(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        limit=limit,
        offset=offset,
        total=total,
        snapshots=[_series_snapshot_data(record) for record in records],
    )


@router.get("/series-cast/snapshots/{snapshot_id:uuid}", status_code=200)
@router.get("/series-cast/snapshots/{snapshot_id:uuid}/", status_code=200)
def get_series_cast_snapshot(
    snapshot_id: uuid.UUID,
    session: SessionDep,
) -> SeriesCastSnapshotData:
    repo = SeriesCastRepository(session)
    try:
        record = repo.get_snapshot(str(snapshot_id), WORKSPACE_ID)
    except SeriesCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except SeriesCastConflictError as err:
        # fail closed: a snapshot whose stored digest does not match its
        # entries is refused, never silently returned.
        raise HTTPException(409, str(err)) from err
    return _series_snapshot_data(record)


@router.post("/series-cast/snapshots/{snapshot_id:uuid}/apply", status_code=200)
@router.post("/series-cast/snapshots/{snapshot_id:uuid}/apply/", status_code=200)
def apply_series_cast_snapshot(
    snapshot_id: uuid.UUID,
    body: SeriesCastApplyRequest,
    session: SessionDep,
) -> SeriesCastApplyResponse:
    repo = SeriesCastRepository(session)
    try:
        result = repo.apply_snapshot_to_video(
            snapshot_id=str(snapshot_id),
            workspace_id=WORKSPACE_ID,
            video_item_id=body.video_item_id,
            resolutions=[
                (resolution.role_key, resolution.object_role_id)
                for resolution in body.resolutions
            ],
        )
        session.commit()
    except SeriesCastStaleError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastOwnershipError as err:
        # covers SeriesCastOwnershipError AND the base ownership refusal that
        # the EXISTING cast service raises from inside create_mapping.
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        # stale-before-conflict ordering above; covers SeriesCastConflictError
        # and the base compatibility/idempotency refusals of the existing
        # cast service.
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "series cast apply conflict") from err
    created = sum(1 for entry in result.entries if entry.created)
    return SeriesCastApplyResponse(
        snapshot_id=result.snapshot_id,
        workspace_id=result.workspace_id,
        project_id=result.project_id,
        video_item_id=result.video_item_id,
        entries_sha256=result.entries_sha256,
        applied=[
            SeriesCastApplyEntryData(
                role_key=entry.role_key,
                object_role_id=entry.object_role_id,
                mapping_id=entry.mapping_id,
                character_id=entry.character_id,
                pack_version_id=entry.pack_version_id,
                manifest_sha256=entry.manifest_sha256,
                created=entry.created,
            )
            for entry in result.entries
        ],
        created_count=created,
        replayed_count=len(result.entries) - created,
    )


# ── MF-END-07: recommendation (read-only) + confirm (guarded mutation) ───────
#
# The suggestion route surfaces the MF-END-06 service verbatim: role
# requirements and the series pin are read from the SERVER (never supplied by
# the client), nothing is written and no job is enqueued.  The confirm route
# re-derives that recommendation from the live state and refuses (typed 409,
# zero mutation) whenever the user's trace no longer matches it — only then
# does it write through the EXISTING ProjectCastRepository authority.


def get_cast_advisory_client() -> AdvisoryClient | None:
    """Advisory client for the suggestion route: None = the pinned default.

    Exposed as a dependency so a test (or an embedding host) can override it
    and prove that no advisory call happens on paths that do not need one.
    """
    return None


CastAdvisoryDep = Annotated[AdvisoryClient | None, Depends(get_cast_advisory_client)]


@router.post("/recommendations", status_code=200)
@router.post("/recommendations/", status_code=200)
def recommend_cast_route(
    body: CastRecommendationRequest,
    session: SessionDep,
    advisory_client: CastAdvisoryDep,
) -> CastRecommendationResult:
    """Suggest a cast set for one video (READ-ONLY: never mutates a pin)."""
    try:
        return recommend_cast(
            session,
            WORKSPACE_ID,
            body,
            advisory_client=advisory_client,
            managed_root=get_managed_root(),
        )
    except CastRecommendationNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except CastRecommendationInputError as err:
        raise HTTPException(422, str(err)) from err


def _match_trace_role(
    plan: CastRecommendationResult, body: CastConfirmRequest
) -> RoleRecommendationData:
    """Resolve the role the trace names — 409 when it is not this video's role."""
    trace = body.recommendation
    role = next((item for item in plan.roles if item.role_key == trace.role_key), None)
    if role is None:
        raise HTTPException(
            409,
            f"recommendation trace role_key {trace.role_key!r} is not one of this "
            "video's server-derived cast requirements",
        )
    if role.object_role_id != body.object_role_id:
        raise HTTPException(
            409,
            f"recommendation trace role_key {trace.role_key!r} maps to object role "
            f"{role.object_role_id!r}, not {body.object_role_id!r}",
        )
    return role


def _confirm_basis(
    session: Session, body: CastConfirmRequest
) -> tuple[CastRecommendationResult, RoleRecommendationData]:
    """Re-derive the LIVE recommendation basis for the trace being confirmed.

    The trace's view / capability / style claims are fed back as an explicit
    requirement (the kind always comes from the live role — a client never
    supplies it), so the confirm validates against the SAME deterministic
    filter the user was shown and can report the real missing assets for the
    chosen pack.
    """
    trace = body.recommendation
    requirements: list[CastRoleRequirement] | None = None
    if trace.required_views or trace.required_capabilities or trace.style_version:
        base_plan = recommend_cast(
            session,
            WORKSPACE_ID,
            CastRecommendationRequest(video_item_id=body.video_item_id, advisory="off"),
        )
        base_role = _match_trace_role(base_plan, body)
        requirements = [
            CastRoleRequirement(
                role_key=trace.role_key,
                kind=base_role.kind,
                object_role_id=body.object_role_id,
                required_views=list(trace.required_views),
                required_capabilities=list(trace.required_capabilities),
                style_version=trace.style_version,
            )
        ]
    plan = recommend_cast(
        session,
        WORKSPACE_ID,
        CastRecommendationRequest(
            video_item_id=body.video_item_id,
            requirements=requirements,
            advisory="off",
        ),
    )
    return plan, _match_trace_role(plan, body)


def _require_fresh_series_basis(
    body: CastConfirmRequest,
    role: RoleRecommendationData,
    candidate: CastCandidateData,
) -> None:
    """The trace's frozen snapshot must BE the live series pin (else 409)."""
    trace = body.recommendation
    pin = role.series_pin
    if (
        trace.selection_mode != "series_pin"
        or trace.series_snapshot_id != candidate.snapshot_id
        or trace.series_snapshot_index != candidate.snapshot_index
        or (pin is not None and trace.series_entries_sha256 != pin.entries_sha256)
    ):
        raise HTTPException(
            409,
            "stale recommendation basis: the live series pin for role "
            f"{trace.role_key!r} is snapshot {candidate.snapshot_id!r} "
            f"(index {candidate.snapshot_index}), not snapshot "
            f"{trace.series_snapshot_id!r} (index {trace.series_snapshot_index})",
        )


@router.post("/recommendations/confirm", status_code=201)
@router.post("/recommendations/confirm/", status_code=201)
def confirm_recommendation_route(
    body: CastConfirmRequest,
    session: SessionDep,
    response: Response,
) -> CastConfirmResponse:
    """Confirm ONE recommended choice — the only mutating path of this API.

    A mutation requires: the trace still matching the LIVE recommendation, the
    chosen pack being a live candidate, and (when an existing pin is replaced)
    an explicit matching ``expected_revision``.  Every refusal returns
    404/409/422 with ZERO mutation, and the write itself rides the existing
    cast repository — no new store, no new job type, no new table.
    """
    trace = body.recommendation
    role_row = session.get(ObjectRole, body.object_role_id)
    if (
        role_row is None
        or role_row.workspace_id != WORKSPACE_ID
        or role_row.video_item_id != body.video_item_id
    ):
        raise HTTPException(
            404,
            f"object role {body.object_role_id!r} does not belong to this video "
            "in this workspace",
        )
    plan, role = _confirm_basis(session, body)
    if trace.selected_pack_version_id != body.pack_version_id:
        raise HTTPException(
            409,
            "confirmed pack_version_id does not match the recommendation trace "
            f"proposal {trace.selected_pack_version_id!r}",
        )
    candidate = next(
        (item for item in role.candidates if item.pack_version_id == body.pack_version_id),
        None,
    )
    if candidate is None:
        excluded = next(
            (
                item
                for item in role.filtered
                if item.pack_version_id == body.pack_version_id
            ),
            None,
        )
        detail = (
            "; ".join(f"{reason.code}: {reason.detail}" for reason in excluded.reasons)
            if excluded is not None
            else "the pack is not among this role's live candidates"
        )
        raise HTTPException(
            409,
            f"pack {body.pack_version_id!r} is not a live candidate for role "
            f"{trace.role_key!r} ({detail})",
        )
    if candidate.character_id != body.character_id:
        raise HTTPException(
            409,
            "character_id does not match the recommended candidate's character "
            f"{candidate.character_id!r}",
        )
    if candidate.source == "series_snapshot":
        _require_fresh_series_basis(body, role, candidate)
    elif trace.selection_mode == "series_pin":
        raise HTTPException(
            409,
            "stale recommendation basis: the frozen series entry this trace was "
            "derived from is no longer the live series pin for this role",
        )
    if candidate.live_ok is False:
        raise HTTPException(
            409,
            "stale recommendation basis: the frozen series entry no longer matches "
            "the live library (" + "; ".join(candidate.live_problems) + ")",
        )
    repo = ProjectCastRepository(session)
    existing = session.scalar(
        select(ProjectCastMapping).where(
            ProjectCastMapping.workspace_id == WORKSPACE_ID,
            ProjectCastMapping.project_id == plan.project_id,
            ProjectCastMapping.object_role_id == body.object_role_id,
        )
    )
    created = False
    replayed = False
    try:
        if existing is not None and (
            existing.character_id == body.character_id
            and existing.pack_version_id == body.pack_version_id
        ):
            # Idempotent replay: this choice is already pinned — zero mutation.
            record = repo.get_mapping(str(existing.id), WORKSPACE_ID)
            replayed = True
        else:
            if existing is None:
                record, created = repo.create_mapping(
                    workspace_id=WORKSPACE_ID,
                    project_id=plan.project_id,
                    object_role_id=body.object_role_id,
                    character_id=body.character_id,
                    pack_version_id=body.pack_version_id,
                    idempotency_key=body.idempotency_key,
                    fallback_acknowledged=body.fallback_acknowledged,
                )
            else:
                if body.expected_revision is None:
                    raise HTTPException(
                        422,
                        "expected_revision is required to replace the existing pin "
                        f"of role {body.object_role_id!r}",
                    )
                record = repo.update_mapping(
                    str(existing.id),
                    WORKSPACE_ID,
                    expected_revision=body.expected_revision,
                    character_id=body.character_id,
                    pack_version_id=body.pack_version_id,
                    fallback_acknowledged=body.fallback_acknowledged,
                )
            session.commit()
    except HTTPException:
        session.rollback()
        raise
    except ProjectCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "cast confirm conflict") from err
    if not created:
        response.status_code = 200
    warnings: list[CastConfirmWarningData] = []
    if candidate.missing_views:
        warnings.append(
            CastConfirmWarningData(
                code="missing_required_views",
                detail=(
                    "the chosen pack does not cover required views: "
                    + ", ".join(candidate.missing_views)
                ),
                action=(
                    "create the missing assets before rendering; the generation "
                    "plan below is the actionable list"
                ),
            )
        )
    if candidate.missing_capabilities:
        warnings.append(
            CastConfirmWarningData(
                code="missing_required_capabilities",
                detail=(
                    "the chosen pack does not declare: "
                    + ", ".join(candidate.missing_capabilities)
                ),
                action=(
                    "confirm a pack that declares the capability or extend this one"
                ),
            )
        )
    if role.generation.required:
        warnings.append(
            CastConfirmWarningData(
                code="generation_plan_required",
                detail=role.generation.note,
                action=(
                    "hand this plan to the generation flow (assets are created "
                    "only when missing)"
                ),
            )
        )
    return CastConfirmResponse(
        workspace_id=WORKSPACE_ID,
        project_id=plan.project_id,
        mapping=ProjectCastData.from_record(record),
        trace=CastConfirmTraceData(
            role_key=trace.role_key,
            selection_mode=trace.selection_mode,
            selected_pack_version_id=trace.selected_pack_version_id,
            verified_source=(
                "series_pin"
                if candidate.source == "series_snapshot"
                else "library_candidate"
            ),
            snapshot_id=candidate.snapshot_id,
            snapshot_index=candidate.snapshot_index,
            entries_sha256=(
                role.series_pin.entries_sha256 if role.series_pin is not None else None
            ),
        ),
        warnings=warnings,
        missing_views=list(candidate.missing_views),
        generation=role.generation,
        created=created,
        replayed=replayed,
        mutations=0 if replayed else 1,
        read_only=False,
    )
