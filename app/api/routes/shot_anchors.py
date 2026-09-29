"""MF-END-15 (C15 correction) — public shot-anchor API over the EXISTING durable job.

The P1-04 finding: ``app.workflow.shot_anchor_jobs`` shipped the anchor job but
NO public caller/route existed, so "import → choose cast → anchor → Comfy" could
only be driven by a script.  This module is the additive bridge that closes that
finding.

Reuse, not a second service (proved in the evidence, not claimed): every route
below reads or creates the SAME ``Job`` rows through the SAME ``JobService`` /
``DurableWorker`` the rest of the app uses, calls the SAME
``shot_anchor_jobs.submit_shot_anchor_job`` / ``anchor_gate`` /
``run_anchor_attempt`` functions, and writes anchor evidence through the SAME
``ManagedRoot`` atomic-write contract.  There is NO new queue, table, service or
migration in this file — it is HTTP surface only.

HTTP contract (PINNED here before any UI builds on it):

==============================  ==================================  ====================
Method / path                   Purpose                             Status
==============================  ==================================  ====================
POST   /api/v2/projects/{pid}/shot-anchors                         202 new / 200 reused
GET    /api/v2/shot-anchors/{job_id}                               200 / 404
POST   /api/v2/shot-anchors/{job_id}/retry                         200 reuse / 202 generation / 409 active
GET    /api/v2/projects/{pid}/shot-anchors/{shot}/preview          200 / 404
POST   /api/v2/projects/{pid}/shot-anchors/{shot}/accept           200 / 409
POST   /api/v2/projects/{pid}/shot-anchors/{shot}/reject           200 / 409
POST   /api/v2/projects/{pid}/shot-anchors/{shot}/video-gate       200 / 409
==============================  ==================================  ====================

Fail-closed laws enforced at this boundary:

* the REFERENCES come from the PUBLISHED cast authority (``CharacterRepository``
  pack versions), never from the client: a draft/unpublished version, a missing
  view/pose slot, a mask-shaped artifact, a placeholder id or one artifact
  reused for two poses of the same role is REFUSED (422) and NO job is created;
* the readiness gate runs at SUBMIT time as well as inside the handler, so a
  request can never leave a half-created job behind (warnings never auto-accept);
* accept/reject are bound to the CURRENT manifest hash (the client must quote the
  hash it previewed), and a rejected or stale anchor blocks the video gate.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, get_job_service
from app.api.helpers import job_response
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import IdempotencyKeyInUse, JobNotFoundError
from app.services.shot_input_readiness import evaluate_shot_input_readiness
from app.workflow import shot_anchor_jobs as anchors
from app.workflow.shot_anchor_jobs import (
    JOB_TYPE_SHOT_ANCHOR_RUN,
    ShotAnchorRefusal,
    ShotAnchorRefusalCode,
)

router = APIRouter(prefix="/api/v2", tags=["shot-anchors"])

#: Refusals that mean "the request itself is wrong / not proven" → 422.
_422_CODES = frozenset({
    ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
    ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
    ShotAnchorRefusalCode.ANCHOR_REFERENCE_MASK_AS_ARTWORK,
    ShotAnchorRefusalCode.ANCHOR_REFERENCE_NOT_PUBLISHED,
    ShotAnchorRefusalCode.ANCHOR_REFERENCE_HASH_MISMATCH,
    ShotAnchorRefusalCode.ANCHOR_REFERENCE_VIEW_DUPLICATED,
    ShotAnchorRefusalCode.ANCHOR_REFERENCE_PLACEHOLDER,
    ShotAnchorRefusalCode.ANCHOR_CAST_REFERENCE_REQUIRED,
    ShotAnchorRefusalCode.ANCHOR_READINESS_BLOCKED,
})
#: Refusals that mean "the state does not allow this transition" → 409.
_409_CODES = frozenset({
    ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED,
    ShotAnchorRefusalCode.ANCHOR_STALE_INPUT,
    ShotAnchorRefusalCode.ANCHOR_JOB_ACTIVE,
    ShotAnchorRefusalCode.ANCHOR_DECISION_STALE,
    ShotAnchorRefusalCode.ANCHOR_DECISION_INVALID,
    ShotAnchorRefusalCode.ANCHOR_ARTIFACT_HASH_MISMATCH,
})
#: Non-terminal job states: a retry of one of these is refused (409, no new job).
_ACTIVE_STATES = frozenset({"pending", "queued", "running", "cancelling"})


def _http_for(exc: ShotAnchorRefusal) -> HTTPException:
    """Map a typed anchor refusal onto the pinned HTTP status vocabulary."""
    if exc.code is ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING:
        status = 404
    elif exc.code in _409_CODES:
        status = 409
    elif exc.code in _422_CODES:
        status = 422
    else:  # engine/boundary failures surfaced to the caller as an unproven request
        status = 422
    return HTTPException(
        status_code=status,
        detail={"code": exc.code.value, "detail": exc.detail, "context": exc.context},
    )


# ── request DTOs (server-owned resolution; extra fields forbidden) ────────────


class CastRequirement(BaseModel):
    """One role's published cast for this shot: character + immutable pack version
    + the views/pose slots the anchor must carry.  No client may name an artifact
    id here — the server resolves them from the published authority."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    pack_version_id: str = Field(min_length=1)
    views: tuple[str, ...] = Field(min_length=1)
    #: Declared placeholder artifact ids (packs whose art is still a flat-color
    #: stand-in).  Resolution refuses to carry one into the engine.
    placeholder_artifact_ids: tuple[str, ...] = ()


class AnchorSubmitRequest(BaseModel):
    """The anchor run request: identity + the FROZEN shot plan + the cast
    requirements the server resolves.  ``plan`` is the ``ShotPlan`` the readiness
    gate reads; ``cast`` is resolved server-side against published pack versions."""

    model_config = ConfigDict(extra="forbid")

    video_item_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    series_id: str | None = None
    seed: int = Field(ge=0)
    capability: str | None = None
    cast: tuple[CastRequirement, ...] = ()
    plan: dict[str, Any]
    source: dict[str, Any]
    graph: dict[str, Any]
    staged_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    engine: dict[str, Any] = Field(default_factory=dict)


class AnchorDecisionRequest(BaseModel):
    """accept/reject body — the client must quote the CURRENT manifest hash."""

    model_config = ConfigDict(extra="forbid")

    manifest_sha256: str = Field(min_length=64, max_length=64)
    note: str | None = None


class AnchorRejectRequest(AnchorDecisionRequest):
    reason: str = Field(min_length=1)


class VideoGateRequest(BaseModel):
    """Optional freshness claim for the video gate: the digest of the input
    identity the caller believes is current.  A mismatch is STALE (409)."""

    model_config = ConfigDict(extra="forbid")

    input_identity_digest: str | None = Field(default=None, min_length=64, max_length=64)


# ── helpers ──────────────────────────────────────────────────────────────────


def _managed_root() -> Any:
    return get_job_service().managed_root


def _requirements(payload: AnchorSubmitRequest) -> list[dict[str, Any]]:
    return [
        {
            "role": requirement.role,
            "character_id": requirement.character_id,
            "pack_version_id": requirement.pack_version_id,
            "views": list(requirement.views),
            "placeholder_artifact_ids": list(requirement.placeholder_artifact_ids),
        }
        for requirement in payload.cast
    ]


def _build_request(
    session: Session, payload: AnchorSubmitRequest, *, workspace_id: str
) -> dict[str, Any]:
    """Resolve the published cast + run the readiness gate, THEN assemble the
    durable anchor request.  Any refusal happens BEFORE a job row exists."""
    resolved = anchors.resolve_published_cast_references(
        session,
        workspace_id=workspace_id,
        requirements=_requirements(payload),
        managed_root=_managed_root(),
    )
    required_views = {requirement.role: list(requirement.views) for requirement in payload.cast}
    report = evaluate_shot_input_readiness(
        anchors.plan_from_payload(payload.plan),
        required_views=required_views,
        resolve_reference=anchors.reference_resolver(resolved),
    )
    if report["verdict"] != "ready":
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_READINESS_BLOCKED,
            "shot input readiness is BLOCKED: " + ", ".join(report["blocking_rows"]),
            blocking_rows=list(report["blocking_rows"]),
            details={
                row: (report["rows"].get(row) or {}).get("detail")
                for row in report["blocking_rows"]
            },
        )
    request = payload.model_dump()
    request["workspace_id"] = workspace_id
    request["project_id"] = payload.plan.get("project_id")
    if not request["project_id"]:
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            "the shot plan carries no project_id",
        )
    request["cast_entries"] = [entry.to_dict() | {
        "character_id": entry.character_id,
        "pack_version_id": entry.pack_version_id,
        "store_relative_path": entry.store_relative_path,
    } for entry in resolved]
    request["readiness_report_sha256"] = report.get("report_sha256")
    return request


def _job_row(job_id: str) -> Any:
    """Read the durable Job row (input manifest) through the shared session factory."""
    service = get_job_service()
    factory = service.session_factory
    if factory is None:  # pragma: no cover - service is initialized by the app lifecycle
        raise HTTPException(status_code=503, detail={"code": "job_service_unavailable"})
    from app.persistence.jobs import JobRepository  # noqa: PLC0415

    with factory() as session:
        repo = JobRepository(session)
        try:
            return repo.get_job(job_id)
        except JobNotFoundError:
            raise HTTPException(
                status_code=404, detail={"code": "anchor_job_not_found", "job_id": job_id}
            ) from None


def _status_body(info: Any, row: Any) -> dict[str, Any]:
    body = job_response(info)
    manifest = dict(getattr(row, "input_manifest", None) or {})
    anchor_request = dict(manifest.get("anchor_request") or {})
    body["job_type"] = info.job_type
    body["shot_id"] = anchor_request.get("shot_id") or manifest.get("shot_id")
    body["input_identity_digest"] = manifest.get("input_identity_digest")
    body["anchor_manifest_path"] = anchors.anchor_manifest_rel_path(
        str(body["shot_id"] or "")
    )
    return body


# ── routes ───────────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/shot-anchors", status_code=202)
def submit_shot_anchor(
    project_id: str, payload: AnchorSubmitRequest, session: SessionDep
) -> dict[str, Any]:
    """Submit ONE durable anchor job for this shot's resolved inputs (202).

    Re-submitting the identical inputs converges on the existing job (200,
    ``reused: true``) — the idempotency key is derived from the input identity
    digest, so a retry never multiplies jobs.
    """
    if payload.plan.get("project_id") not in (None, project_id):
        raise HTTPException(
            status_code=422,
            detail={"code": "anchor_input_invalid", "detail": "plan.project_id != path project_id"},
        )
    try:
        request = _build_request(session, payload, workspace_id=DEFAULT_WORKSPACE_ID)
    except ShotAnchorRefusal as exc:
        raise _http_for(exc) from exc
    service = get_job_service()
    try:
        info = anchors.submit_shot_anchor_job(service, request=request)
        reused = False
    except IdempotencyKeyInUse as exc:
        existing_id = getattr(exc, "job_id", None)
        info = service.get_job(str(existing_id)) if existing_id else None
        if info is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "anchor_job_active", "detail": str(exc)},
            ) from exc
        if info.state.value in _ACTIVE_STATES:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "anchor_job_active",
                    "job_id": info.job_id,
                    "state": info.state.value,
                    "detail": "an anchor job for this input identity is already active",
                },
            ) from exc
        reused = True
    body = {
        "job_id": info.job_id,
        "state": info.state.value,
        "status": info.state.value,
        "reused": reused,
        "shot_id": request["shot_id"],
        "input_identity_digest": anchors.anchor_input_identity_digest(
            anchors.anchor_input_identity(request)
        ),
        "anchor_manifest_path": anchors.anchor_manifest_rel_path(str(request["shot_id"])),
    }
    if reused:
        # an identical request converges on the existing job: no new row, no work
        return JSONResponse(status_code=200, content=body)
    return body


@router.get("/shot-anchors/{job_id}")
def get_shot_anchor_status(job_id: str) -> dict[str, Any]:
    """Status of one anchor job through the shared durable job authority."""
    info = get_job_service().get_job(job_id)
    if info is None:
        raise HTTPException(status_code=404, detail={"code": "anchor_job_not_found",
                                                    "job_id": job_id})
    if info.job_type != JOB_TYPE_SHOT_ANCHOR_RUN:
        raise HTTPException(
            status_code=409,
            detail={"code": "anchor_job_type_mismatch", "job_type": info.job_type},
        )
    return _status_body(info, _job_row(job_id))


@router.post("/shot-anchors/{job_id}/retry")
def retry_shot_anchor(job_id: str) -> dict[str, Any]:
    """Idempotent retry of the SAME anchor inputs.

    completed  → 200 ``reused: true`` (durable evidence replayed, NO new job,
                 NO engine work);
    active     → 409 (a retry may not race a live attempt);
    failed/cancelled → 202 with exactly ONE successor job (generation + 1) for
                 the same input identity.
    """
    row = _job_row(job_id)
    state = str(row.state)
    body: dict[str, Any] = {"job_id": job_id, "state": state, "status": state}
    if state in _ACTIVE_STATES:
        raise HTTPException(
            status_code=409,
            detail={"code": "anchor_job_active", "job_id": job_id, "state": state},
        )
    if state == "completed":
        body["reused"] = True
        body["new_generation"] = False
        return body
    manifest = dict(getattr(row, "input_manifest", None) or {})
    request = dict(manifest.get("anchor_request") or {})
    if not request:
        raise HTTPException(
            status_code=409,
            detail={"code": "anchor_input_invalid",
                    "detail": "the durable job carries no anchor_request to retry"},
        )
    generation = int(request.get("generation") or 0) + 1
    request["generation"] = generation
    service = get_job_service()
    try:
        info = anchors.submit_shot_anchor_job(service, request=request, generation=generation)
    except IdempotencyKeyInUse as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "anchor_job_active", "detail": str(exc)},
        ) from exc
    body.update({
        "job_id": info.job_id,
        "state": info.state.value,
        "status": info.state.value,
        "reused": False,
        "new_generation": True,
        "generation": generation,
    })
    # a terminal failure gets exactly ONE successor job for the same inputs
    return JSONResponse(status_code=202, content=body)


@router.get("/projects/{project_id}/shot-anchors/{shot_id}/preview")
def preview_shot_anchor(project_id: str, shot_id: str) -> dict[str, Any]:
    """Current anchor state of one shot: verdict, hashes, staleness, decision."""
    return anchors.anchor_status(get_job_service().managed_root, shot_id)


@router.post("/projects/{project_id}/shot-anchors/{shot_id}/accept")
def accept_shot_anchor(
    project_id: str, shot_id: str, payload: AnchorDecisionRequest
) -> dict[str, Any]:
    """Accept the anchor whose CURRENT manifest hash the client quoted (409 if stale)."""
    try:
        return anchors.record_anchor_decision(
            get_job_service().managed_root,
            shot_id,
            "accepted",
            expected_manifest_sha256=payload.manifest_sha256,
            note=payload.note,
        )
    except ShotAnchorRefusal as exc:
        raise _http_for(exc) from exc


@router.post("/projects/{project_id}/shot-anchors/{shot_id}/reject")
def reject_shot_anchor(
    project_id: str, shot_id: str, payload: AnchorRejectRequest
) -> dict[str, Any]:
    """Reject the anchor (bound to its CURRENT hash).  A rejected anchor blocks video."""
    try:
        return anchors.record_anchor_decision(
            get_job_service().managed_root,
            shot_id,
            "rejected",
            expected_manifest_sha256=payload.manifest_sha256,
            reason=payload.reason,
        )
    except ShotAnchorRefusal as exc:
        raise _http_for(exc) from exc


@router.post("/projects/{project_id}/shot-anchors/{shot_id}/video-gate")
def video_gate(
    project_id: str, shot_id: str, payload: VideoGateRequest | None = None
) -> dict[str, Any]:
    """The gate every video submit calls: 200 only for an accepted, current anchor."""
    expected = payload.input_identity_digest if payload is not None else None
    try:
        gate = anchors.require_accepted_anchor(
            managed_root=get_job_service().managed_root,
            shot_id=shot_id,
            expected_identity_digest=expected,
        )
    except ShotAnchorRefusal as exc:
        raise _http_for(exc) from exc
    return {"video_allowed": True, "shot_id": shot_id, "anchor": gate}
