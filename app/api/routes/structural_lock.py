"""Public StructuralLock producer API (S09-LOCK-PRODUCER-B01).

``POST /api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock``
— the bounded public caller for the durable
:class:`app.persistence.structural_lock.StructuralLockRepository`.

Contract (mirrors the S09-T06A route conventions):

- The workspace is SERVER-OWNED (``DEFAULT_WORKSPACE_ID``); the request body
  can only select the documented policy, assert ``expected_*`` current
  identities (stale → 409 typed conflict) and carry an idempotency key.
  Unknown fields — workspace, paths, routes, filesystem or readiness
  fields — are rejected at the schema boundary (422).
- 201 when a NEW manifest version is created, 200 on an equivalent replay
  (``created=false``, same durable row).  Denials are typed:
  ``{"code": ..., "message": ..., "reasons": [...]}`` with 404
  (unknown/cross-scope project or video), 409 (stale identity / conflict)
  or 422 (missing/tampered/cross-scope/unsupported evidence).
- The commit is explicit and strictly after every validation + durable
  write succeeded; any failure rolls the whole transaction back — no
  partially authoritative manifest/route/pin state can persist.

No auto-approval: pinning the returned manifest stays the existing
ReskinConfig CAS pin endpoint and approval stays the S09 reapproval path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep, get_managed_root
from app.persistence import DEFAULT_WORKSPACE_ID
from app.schemas.structural_lock import (
    StructuralLockProduceRequest,
    StructuralLockProduceResponse,
)
from app.services.structural_lock_producer import (
    ProducerError,
    StructuralLockProducer,
)

router = APIRouter(prefix="/api/v2", tags=["structural-lock"])

#: Server-owned workspace authority (never client-supplied).
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.post(
    "/projects/{project_id}/videos/{video_item_id}/structural-lock",
    response_model=StructuralLockProduceResponse,
    status_code=201,
)
def produce_structural_lock(
    project_id: str,
    video_item_id: str,
    body: StructuralLockProduceRequest,
    session: SessionDep,
    response: Response,
) -> StructuralLockProduceResponse:
    """Produce (or replay) the CURRENT StructuralLockManifest.

    Server-derived from the current source/evidence graph only; any
    denial leaves ZERO durable mutation behind.
    """
    producer = StructuralLockProducer(session, managed_root=get_managed_root())
    try:
        outcome = producer.produce(
            WORKSPACE_ID,
            project_id,
            video_item_id,
            expected_source_generation=body.expected_source_generation,
            expected_source_sha256=body.expected_source_sha256,
            policy_version=body.policy_version,
            idempotency_key=body.idempotency_key,
        )
    except ProducerError as err:
        # Fail closed: discard every unflushed/uncommitted change so a
        # refused production attempt leaves ZERO rows in any state.
        session.rollback()
        raise HTTPException(
            status_code=err.http_status, detail=err.detail()
        ) from err
    except SQLAlchemyError as err:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "STRUCTURAL_LOCK_READ_ERROR",
                "message": f"durable read failed: {err}",
                "reasons": [],
            },
        ) from err
    except Exception:
        # Unexpected failure mid-production — never persist partial work.
        session.rollback()
        raise

    if outcome.created:
        # PRODUCTION commit semantics: get_db_session only closes the
        # session — the manifest + its route decisions are durable only
        # when THIS route commits explicitly, strictly after every
        # validation and durable write succeeded.
        try:
            session.commit()
        except Exception as err:
            session.rollback()
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "STRUCTURAL_LOCK_COMMIT_FAILED",
                    "message": "structural lock commit failed; nothing was "
                    "persisted",
                    "reasons": [],
                },
            ) from err
    else:
        # Replay path: no new durable rows — never carry an accidental
        # write out of the request boundary.
        session.rollback()

    record = outcome.record
    if not outcome.created:
        response.status_code = 200
    return StructuralLockProduceResponse(
        workspace_id=outcome.graph.workspace_id,
        project_id=outcome.graph.project_id,
        video_item_id=outcome.graph.video_item_id,
        manifest_id=record.id,
        manifest_hash=record.manifest_hash_hex,
        source_generation=record.source_generation,
        source_frame_count=int(outcome.graph.frame_count),
        source_fps_num=int(outcome.graph.fps_num),
        source_fps_den=int(outcome.graph.fps_den),
        policy_version=record.policy_version,
        version=int(record.version),
        status=record.status,
        created=bool(outcome.created),
        segment_count=len(outcome.graph.segment_ids),
        route_decisions_created=int(outcome.route_decisions_created),
        reasons=[],
    )
