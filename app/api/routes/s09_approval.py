"""HTTP surface for the S09-T06A immutable approval/checkpoint backend.

POST /api/v2/s09-approvals                submit v1 (idempotent, immutable)
POST /api/v2/s09-approvals/reapprove      reapproval → NEW s09.approval/v2
GET  /api/v2/s09-approvals/{id}           read one (hash-verified)
GET  /api/v2/s09-approvals/{id}/full-apply-authority
                                          server-derived v2 authority (read)
GET  /api/v2/s09-approvals                list (workspace/project scoped)
POST /api/v2/s09-approvals/{id}/verify    recompute stored hash
POST /api/v2/s09-approvals/replay-probe   explicit replay lookup by key
POST /api/v2/s09-approvals/conflict-probe direction-B conflict probe

v2 semantics (S10-C6A): ``reapprove`` NEVER mutates/backfills v1 rows — it
creates a NEW checkpoint whose snapshot schema is ``s09.approval/v2`` with
the nested ``full_apply_authority`` frozen from persisted/canonical rows.
The full-apply-authority endpoint is read-only and fails closed for v1
(REAPPROVAL_REQUIRED) and for tampered v2 rows.

NOTE: the router is wired into app.api.app by the S09-T56 integration
phase (both route groups mounted on the production app).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.schemas.s09_approval import (
    CheckpointListOut,
    CheckpointOut,
    ConflictProbeRequest,
    FullApplyAuthorityOut,
    ReapproveRequest,
    ReplayProbeRequest,
    SubmitCheckpointRequest,
    SubmittedCheckpointOut,
    VerifyCheckpointOut,
)
from app.services.s09_approval import (
    ApprovalBlockedError,
    ApprovalConflictError,
    ApprovalNotFoundError,
    ApprovalValidationError,
    CheckpointIntegrity,
    S09ApprovalIntegrityError,
    S09ApprovalRecord,
    S09ApprovalRepository,
)

router = APIRouter(
    prefix="/api/v2",
    tags=["s09-approvals"],
)


def _repo(session: Session) -> S09ApprovalRepository:
    return S09ApprovalRepository(session)


def _http_status(err: Exception) -> int:
    if isinstance(err, ApprovalNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(err, ApprovalConflictError):
        return status.HTTP_409_CONFLICT
    if isinstance(err, ApprovalBlockedError):
        # Blocked approvals are a state conflict with the durable demo/
        # correction history: 409, zero mutation already guaranteed.
        return status.HTTP_409_CONFLICT
    if isinstance(err, ApprovalValidationError):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    if isinstance(err, S09ApprovalIntegrityError):
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _out(record: S09ApprovalRecord) -> dict[str, Any]:
    return CheckpointOut(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        reskin_config_id=record.reskin_config_id,
        reskin_config_revision=record.reskin_config_revision,
        structural_lock_manifest_id=record.structural_lock_manifest_id,
        lock_policy_version=record.lock_policy_version,
        pack_version_ids=list(record.pack_version_ids),
        loop_hashes=[dict(item) for item in record.loop_hashes],
        timebase_fingerprint=record.timebase_fingerprint,
        snapshot=dict(record.snapshot),
        checkpoint_hash=record.checkpoint_hash,
        note=record.note,
        created_at=record.created_at,
        updated_at=record.updated_at,
    ).model_dump(mode="json")


@router.post(
    "/s09-approvals",
    response_model=SubmittedCheckpointOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_checkpoint(
    body: SubmitCheckpointRequest,
    session: SessionDep,
    workspace_id: str = Query(min_length=1),
) -> Any:
    repo = _repo(session)
    try:
        record, created = repo.submit_checkpoint(
            workspace_id,
            body.reskin_config_id,
            body.expected_reskin_revision,
            list(body.pack_version_ids),
            demo_artifact_ids=list(body.demo_artifact_ids),
            correction_ids=list(body.correction_ids),
            accepted_warnings=list(body.accepted_warnings),
            overrides=list(body.overrides),
            note=body.note,
            idempotency_key=body.idempotency_key,
        )
    except (
        ApprovalBlockedError,
        ApprovalConflictError,
        ApprovalNotFoundError,
        ApprovalValidationError,
    ) as err:
        # Fail closed: discard every unflushed/uncommitted change so a
        # refused submission leaves ZERO rows in any transaction state.
        session.rollback()
        raise HTTPException(status_code=_http_status(err), detail=str(err)) from err
    except Exception:
        # Unexpected failure mid-submit — never persist partial work.
        session.rollback()
        raise
    if created:
        # PRODUCTION dependency semantics (review F4): get_db_session only
        # closes the session — it NEVER commits on the caller's behalf.  The
        # checkpoint is durable only when THIS route commits explicitly.
        # Commit happens strictly AFTER all validation succeeded, so any
        # failure above/below rolls back to a clean sheet: a failed submit
        # cannot leave a half-written immutable row behind.
        try:
            session.commit()
        except Exception as err:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="checkpoint commit failed; nothing was persisted",
            ) from err
    else:
        # Replay path returned an EXISTING committed row; this transaction
        # must not carry any accidental write out of the request boundary.
        session.rollback()
    payload = _out(record)
    payload["replayed"] = not created
    # 201 created / 200 replayed (same contract as S09-T05A submit).
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@router.post(
    "/s09-approvals/reapprove",
    response_model=SubmittedCheckpointOut,
    status_code=status.HTTP_201_CREATED,
)
def reapprove_checkpoint(
    body: ReapproveRequest,
    session: SessionDep,
    workspace_id: str = Query(min_length=1),
) -> Any:
    """Deterministic reapproval — creates a NEW ``s09.approval/v2`` row.

    Same closed-domain payload as a v1 submission; the v2 snapshot freezes
    the nested ``full_apply_authority`` derived from persisted/canonical
    rows.  v1 rows are never mutated.  201 created / 200 replayed.
    """
    repo = _repo(session)
    try:
        record, created = repo.submit_checkpoint_v2(
            workspace_id,
            body.reskin_config_id,
            body.expected_reskin_revision,
            list(body.pack_version_ids),
            demo_artifact_ids=list(body.demo_artifact_ids),
            correction_ids=list(body.correction_ids),
            accepted_warnings=list(body.accepted_warnings),
            overrides=list(body.overrides),
            note=body.note,
            idempotency_key=body.idempotency_key,
        )
    except (
        ApprovalBlockedError,
        ApprovalConflictError,
        ApprovalNotFoundError,
        ApprovalValidationError,
    ) as err:
        session.rollback()
        raise HTTPException(status_code=_http_status(err), detail=str(err)) from err
    except Exception:
        session.rollback()
        raise
    if created:
        # PRODUCTION dependency semantics (review F4): commit explicitly,
        # only after every validation passed; failure rolls back to a clean
        # sheet so a failed reapproval leaves ZERO rows behind.
        try:
            session.commit()
        except Exception as err:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="checkpoint commit failed; nothing was persisted",
            ) from err
    else:
        session.rollback()
    payload = _out(record)
    payload["replayed"] = not created
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@router.get(
    "/s09-approvals/{checkpoint_id}/full-apply-authority",
    response_model=FullApplyAuthorityOut,
)
def full_apply_authority_endpoint(
    checkpoint_id: str, session: SessionDep, workspace_id: str = Query(min_length=1)
) -> dict[str, Any]:
    """Read-only server-derived Full Apply authority for one checkpoint.

    A v1 checkpoint fails closed with ``REAPPROVAL_REQUIRED`` (422, reason
    in the detail) and ZERO mutation.  A tampered v2 row fails closed 500.
    """
    repo = _repo(session)
    try:
        authority = repo.full_apply_authority(checkpoint_id, workspace_id)
        integrity = repo.verify_checkpoint(checkpoint_id, workspace_id)
        snapshot_schema = authority.get("authority_version")
        return {
            "checkpoint_id": checkpoint_id,
            "snapshot_schema": snapshot_schema,
            "verified": integrity.verified,
            "eligibility": authority.get("eligibility") or {},
            "full_apply_authority": authority,
        }
    except ApprovalNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ApprovalValidationError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except S09ApprovalIntegrityError as err:
        raise HTTPException(status_code=500, detail=str(err)) from err


@router.get("/s09-approvals/{checkpoint_id}", response_model=CheckpointOut)
def get_checkpoint(
    checkpoint_id: str, session: SessionDep, workspace_id: str = Query(min_length=1)
) -> dict[str, Any]:
    repo = _repo(session)
    try:
        record = repo.get_checkpoint(checkpoint_id, workspace_id)
    except ApprovalNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except S09ApprovalIntegrityError as err:
        raise HTTPException(status_code=500, detail=str(err)) from err
    return _out(record)


@router.get("/s09-approvals", response_model=CheckpointListOut)
def list_checkpoints(
    session: SessionDep,
    workspace_id: str = Query(min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    repo = _repo(session)
    records = repo.list_checkpoints(workspace_id, project_id)
    return {"total": len(records), "items": [_out(r) for r in records]}


@router.post(
    "/s09-approvals/{checkpoint_id}/verify",
    response_model=VerifyCheckpointOut,
)
def verify_endpoint(
    checkpoint_id: str, session: SessionDep, workspace_id: str = Query(min_length=1)
) -> VerifyCheckpointOut:
    repo = _repo(session)
    try:
        integrity: CheckpointIntegrity = repo.verify_checkpoint(
            checkpoint_id, workspace_id
        )
    except ApprovalNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return VerifyCheckpointOut(
        checkpoint_id=integrity.checkpoint_id,
        verified=integrity.verified,
        reason=integrity.reason,
    )


@router.post("/s09-approvals/replay-probe", response_model=SubmittedCheckpointOut)
def replay_probe(
    body: ReplayProbeRequest,
    session: SessionDep,
    workspace_id: str = Query(min_length=1),
) -> dict[str, Any]:
    repo = _repo(session)
    try:
        record = repo.replay_probe(workspace_id, body.idempotency_key)
    except ApprovalNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    payload = _out(record)
    payload["replayed"] = True
    return payload


@router.post("/s09-approvals/conflict-probe")
def conflict_probe(
    body: ConflictProbeRequest,
    session: SessionDep,
    workspace_id: str = Query(min_length=1),
) -> dict[str, Any]:
    """Always raises: 409 when the key is bound to different content."""
    repo = _repo(session)
    try:
        repo.conflict_probe(
            workspace_id,
            body.idempotency_key,
            body.reskin_config_id,
            body.expected_reskin_revision,
            list(body.pack_version_ids),
            demo_artifact_ids=list(body.demo_artifact_ids),
            correction_ids=list(body.correction_ids),
            accepted_warnings=list(body.accepted_warnings),
            overrides=list(body.overrides),
        )
    except ApprovalConflictError:
        raise HTTPException(status_code=409, detail="conflict confirmed") from None
    except ApprovalNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ApprovalValidationError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    raise HTTPException(status_code=500, detail="conflict probe did not raise")
