"""Durable object-candidate extraction API (S08-T02).

Isolated under ``/api/v2/object-intelligence/extraction`` (disjoint from
every legacy route).  Three focused endpoints:

- ``POST /`` — submit a ``DISCOVER_OBJECTS`` Job through the public
  initialized JobService factory (durable insert; no long synchronous work).
  The production provider path fails closed with ``PROVIDER_UNAVAILABLE``
  (503) when the capability probe fails — never a silent fallback.
- ``GET /{job_id}`` — Job status + published outputs.  Read-only: repeated
  and concurrent GETs cause ZERO database mutations.
- ``GET /{job_id}/outputs`` — the committed output set (manifest-derived
  candidates + artifacts).  409 while the Job is active; only a
  terminal-``completed`` Job exposes outputs — partial or stale output is
  never visible.

All reads go through public ``JobService.session_factory`` /
``JobService.managed_root`` bindings (S05-C04) — no private member access,
no state-advancing helper endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import get_job_service
from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import IdempotencyKeyInUse, JobNotFoundError, JobRepository
from app.persistence.models import Artifact
from app.schemas.object_extraction import (
    ExtractionCandidateData,
    ExtractionContactData,
    ExtractionJobResponse,
    ExtractionMotionData,
    ExtractionOcclusionData,
    ExtractionOutputData,
    ExtractionSegmentData,
    ExtractionSubmitRequest,
    ExtractionSubmitResponse,
)
from app.services.object_extraction import (
    CODE_INPUT_CHANGED,
    CODE_OWNERSHIP_MISMATCH,
    CODE_PROJECT_NOT_FOUND,
    CODE_PROVIDER_UNAVAILABLE,
    CODE_SOURCE_ARTIFACT_NOT_FOUND,
    CODE_SOURCE_CONFLICT,
    CODE_VIDEO_ITEM_NOT_FOUND,
    DEFAULT_EXTRACTOR_VERSION,
    ExtractionError,
    submit_discover_objects,
)
from app.workflow.job_service import JobService

router = APIRouter(
    prefix="/api/v2/object-intelligence/extraction", tags=["object-extraction"]
)

_OUTPUT_PURPOSES = (
    "thumbnail",
    "mask",
    "result",
)


def _job_service() -> JobService:
    svc = get_job_service()
    if svc.session_factory is None:
        raise HTTPException(503, "job service is not initialized")
    return svc


def _http_error(err: ExtractionError) -> HTTPException:
    if err.code in (
        CODE_PROJECT_NOT_FOUND,
        CODE_VIDEO_ITEM_NOT_FOUND,
        CODE_SOURCE_ARTIFACT_NOT_FOUND,
    ):
        return HTTPException(404, err.message)
    if err.code in (CODE_OWNERSHIP_MISMATCH, CODE_INPUT_CHANGED, CODE_SOURCE_CONFLICT):
        return HTTPException(409, err.message)
    if err.code == CODE_PROVIDER_UNAVAILABLE:
        return HTTPException(503, err.message)
    return HTTPException(422, err.message)


@router.post("", status_code=201)
@router.post("/", status_code=201)
def submit_extraction(body: ExtractionSubmitRequest) -> ExtractionSubmitResponse:
    """Submit one durable candidate extraction (idempotent, fail-closed).

    Provider selection is SERVER/RUNTIME policy: a client-supplied
    ``provider`` value is rejected (422) — the QA/test-only deterministic
    adapter can never be selected through request JSON (finding B3).

    C2 BACKEND SOURCE AUTHORITY: ``source_sha256``/``generation`` in the
    body are ASSERTIONS ONLY — the server resolves the current source
    artifact, SHA and generation itself from durable state; a mismatched
    hint fails closed 409 with NO Job row (acceptance 1-4).
    """
    if body.provider is not None:
        raise HTTPException(
            422,
            "provider is server/runtime policy (MOTIONFORGE_EXTRACTION_PROVIDER); "
            "client-supplied provider values are rejected",
        )
    svc = _job_service()
    factory = svc.session_factory
    assert factory is not None  # _job_service() already guaranteed this
    try:
        result = submit_discover_objects(
            factory,
            workspace_id="default",
            project_id=body.project_id,
            video_item_id=body.video_item_id,
            source_sha256=body.source_sha256,
            generation=body.generation,
            extractor_version=body.extractor_version or DEFAULT_EXTRACTOR_VERSION,
            provider=None,  # server policy only
            managed_root=svc.managed_root,
        )
    except IdempotencyKeyInUse as err:
        raise HTTPException(409, str(err)) from err
    except ExtractionError as err:
        raise _http_error(err) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    return ExtractionSubmitResponse(
        job_id=result.job_id,
        reused=result.reused,
        status="queued",
    )


def _load_job(job_id: str) -> Any:
    """Return the JobRecord for *job_id* or raise 404 (session closed)."""
    svc = _job_service()
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        repo = JobRepository(session)
        try:
            return repo.get_job(job_id)
        except JobNotFoundError as err:
            raise HTTPException(404, "Job not found") from err


def _published_outputs(svc: Any, job: Any) -> list[ExtractionOutputData]:
    """Artifacts published by this Job (scoped by the managed path).

    Only rows whose ``relative_path`` lives under
    ``artifacts/<workspace>/image/<job_id>/`` are considered; staging files
    are never rows and never exposed.
    """
    factory = svc.session_factory
    assert factory is not None
    prefix = f"artifacts/{job.workspace_id}/image/{job.id}/"
    with factory() as session:
        rows = session.scalars(
            select(Artifact)
            .where(
                Artifact.workspace_id == job.workspace_id,
                Artifact.relative_path.like(prefix + "%"),
                Artifact.state == "ready",
            )
            .order_by(Artifact.relative_path)
        ).all()
        return [
            ExtractionOutputData(
                artifact_id=row.id,
                name=Path(row.relative_path).name,
                purpose=_purpose_for(session, row.id, job.workspace_id),
                relative_path=row.relative_path,
                sha256=row.sha256 or "",
                size_bytes=row.size_bytes or 0,
                width=row.width,
                height=row.height,
                mime_type=row.mime_type,
            )
            for row in rows
        ]


def _purpose_for(session: Any, artifact_id: str, workspace_id: str) -> str:
    """The output purpose of an artifact (its video_item owner link purpose)."""
    from app.persistence.models import ArtifactOwner

    owner = session.execute(
        select(ArtifactOwner.purpose).where(ArtifactOwner.artifact_id == artifact_id)
    ).first()
    if owner is not None and owner[0] in _OUTPUT_PURPOSES:
        return str(owner[0])
    return "result"


def _manifest_candidates(svc: Any, job: Any) -> list[ExtractionCandidateData]:
    """Parse the committed result manifest (completed Jobs only)."""
    factory = svc.session_factory
    assert factory is not None
    manifest_rel = f"artifacts/{job.workspace_id}/image/{job.id}/extract/result.json"
    managed = ManagedRoot(svc.managed_root)
    try:
        target = managed.resolve(manifest_rel)
    except Exception:  # noqa: BLE001 - read-only failure => no outputs
        return []
    if not target.is_file():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    candidates: list[ExtractionCandidateData] = []
    for entry in payload.get("candidates", []):
        candidates.append(
            ExtractionCandidateData(
                index=int(entry["index"]),
                role_id=str(entry.get("role_id") or ""),
                name=str(entry["name"]),
                kind=str(entry["kind"]),
                confidence=float(entry["confidence"]),
                reasons=list(entry.get("reasons", [])),
                occurrences=list(entry.get("occurrences", [])),
                artifacts=[
                    ExtractionOutputData(
                        artifact_id="",
                        name=str(a["name"]),
                        purpose=str(a["purpose"]),
                        relative_path=(
                            f"artifacts/{job.workspace_id}/image/{job.id}/extract/"
                            f"{a['name']}"
                        ),
                        sha256=str(a["sha256"]),
                        size_bytes=int(a["size_bytes"]),
                        width=int(a["width"]),
                        height=int(a["height"]),
                        mime_type="image/png",
                    )
                    for a in entry.get("artifacts", [])
                ],
            )
        )
    return candidates


@router.get("/current")
def get_current_extraction(
    video_item_id: str,
    source_generation: str | None = None,
) -> ExtractionJobResponse:
    """Backend-authoritative lookup of the CURRENT completed extraction.

    Returns the newest terminal-``completed`` DISCOVER_OBJECTS Job for the
    video item, filtered by source generation when given (correction B8/B9).
    Browser storage is never required — the backend is the authority.  No
    current completed extraction => 404.
    """
    svc = _job_service()
    factory = svc.session_factory
    assert factory is not None
    from app.persistence.models import Job as JobORM

    filters = [JobORM.job_type == "DISCOVER_OBJECTS", JobORM.state == "completed"]
    # The owner_id column is an exact index; video_item_id is re-verified
    # against the manifest below (owner mismatch => 409).
    filters.append(JobORM.owner_id == video_item_id)
    if source_generation:
        filters.append(JobORM.input_generation == source_generation)
    with factory() as session:
        row = session.scalar(
            select(JobORM)
            .where(*filters)
            .order_by(JobORM.created_at.desc(), JobORM.id.desc())
            .limit(1)
        )
        if row is None:
            raise HTTPException(
                404,
                f"no completed extraction for video item {video_item_id!r}"
                + (f" generation {source_generation!r}" if source_generation else ""),
            )
        job = JobRepository(session).get_job(row.id)
    manifest = job.input_manifest or {}
    if manifest.get("video_item_id") != video_item_id:
        raise HTTPException(409, "job owner mismatch; refusing stale lookup")
    outputs: list[ExtractionOutputData] = []
    candidates: list[ExtractionCandidateData] = []
    if job.state == "completed":
        outputs = _published_outputs(svc, job)
        candidates = _manifest_candidates(svc, job)
    return ExtractionJobResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.state,
        progress=job.progress,
        message=_message_for(job, job.state),
        provider=str(manifest.get("provider") or None) or None,
        extractor_version=str(manifest.get("extractor_version") or None) or None,
        generation=str(manifest.get("generation") or None) or None,
        source_sha256=str(manifest.get("source_sha256") or None) or None,
        video_item_id=str(manifest.get("video_item_id") or None) or None,
        created_at=job.created_at,
        finished_at=job.finished_at,
        outputs=outputs,
        candidates=candidates,
    )


@router.get("")
@router.get("/")
def list_extractions(
    video_item_id: str | None = None,
    source_generation: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List DISCOVER_OBJECTS jobs with source-generation filtering.

    Historical approved rows stay auditable through this list (filtered by
    generation), but the CURRENT lookup (:func:`get_current_extraction`)
    and grouping/gallery consumers never mix generations (correction B9).
    Read-only — zero durable mutations.
    """
    svc = _job_service()
    factory = svc.session_factory
    assert factory is not None
    from app.persistence.models import Job as JobORM

    filters = [JobORM.job_type == "DISCOVER_OBJECTS"]
    if video_item_id:
        filters.append(JobORM.owner_id == video_item_id)
    if source_generation:
        filters.append(JobORM.input_generation == source_generation)
    if status:
        filters.append(JobORM.state == status)
    with factory() as session:
        rows = session.scalars(
            select(JobORM).where(*filters).order_by(JobORM.created_at.desc())
        ).all()
        jobs = [
            {
                "job_id": row.id,
                "status": row.state,
                "job_type": row.job_type,
                "generation": row.input_generation,
                "video_item_id": row.owner_id,
                "provider": _manifest_value(row, "provider"),
                "extractor_version": _manifest_value(row, "extractor_version"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]
    return {"jobs": jobs, "total": len(jobs)}


def _manifest_value(row: Any, key: str) -> str | None:
    from app.persistence.jobs import parse_json

    manifest = parse_json(row.input_manifest_json, {})
    if not isinstance(manifest, dict):
        return None
    value = manifest.get(key)
    return str(value) if value else None


def _structural_graph_for_job(svc: Any, job: Any) -> tuple[list[ExtractionSegmentData], list[ExtractionMotionData], list[ExtractionOcclusionData], list[ExtractionContactData]]:  # noqa: E501
    """Fetch structural graph for a completed job (read-only, zero mutation).

    Returns (segments, motions, occlusions, contacts) for the job's generation.
    Empty when job not completed or no graph exists.
    """
    if job.state != "completed":
        return [], [], [], []
    factory = svc.session_factory
    assert factory is not None
    import json as _json

    from sqlalchemy import select as _select

    from app.persistence.models import (
        OccurrenceSegment,
        SceneGraphContact,
        SceneGraphOcclusion,
        SegmentMotion,
    )
    with factory() as session:
        segs = session.scalars(
            _select(OccurrenceSegment)
            .where(OccurrenceSegment.source_job_id == job.id, OccurrenceSegment.workspace_id == job.workspace_id)  # noqa: E501
            .order_by(OccurrenceSegment.start_frame, OccurrenceSegment.id)
        ).all()
        seg_data: list[ExtractionSegmentData] = []
        for s in segs:
            try:
                prompt = _json.loads(s.prompt_json) if s.prompt_json else None
            except Exception:
                prompt = None
            try:
                segm = _json.loads(s.segmentation_json) if s.segmentation_json else None
            except Exception:
                segm = None
            seg_data.append(
                ExtractionSegmentData(
                    id=s.id,
                    logical_id=s.logical_id,
                    role_id=s.role_id,
                    scene_id=s.scene_id,
                    name=s.name,
                    kind=s.kind,
                    start_frame=s.start_frame,
                    end_frame=s.end_frame,
                    start_time_ms=s.start_time_ms,
                    end_time_ms=s.end_time_ms,
                    source_generation=s.source_generation,
                    source_job_id=s.source_job_id,
                    mask_artifact_id=s.mask_artifact_id,
                    prompt=prompt,
                    segmentation=segm,
                    algorithm=s.algorithm,
                    algorithm_version=s.algorithm_version,
                    confidence=s.confidence,
                    confidence_source=s.confidence_source,
                    visibility=s.visibility,
                    z_order=s.z_order,
                    revision=s.revision,
                )
            )
        seg_ids = [s.id for s in segs]
        motions: list[ExtractionMotionData] = []
        occlusions: list[ExtractionOcclusionData] = []
        contacts: list[ExtractionContactData] = []
        if seg_ids:
            motion_rows = session.scalars(
                _select(SegmentMotion).where(SegmentMotion.occurrence_segment_id.in_(seg_ids)).order_by(SegmentMotion.transform_type, SegmentMotion.start_frame)  # noqa: E501
            ).all()
            for m in motion_rows:
                try:
                    tr = _json.loads(m.transform_json) if m.transform_json else {}
                except Exception:
                    tr = {}
                try:
                    ref = _json.loads(m.point_track_flow_ref_json) if m.point_track_flow_ref_json else None  # noqa: E501
                except Exception:
                    ref = None
                motions.append(
                    ExtractionMotionData(
                        id=m.id,
                        occurrence_segment_id=m.occurrence_segment_id,
                        transform_type=m.transform_type,
                        transform=tr if isinstance(tr, dict) else {},
                        point_track_flow_ref=ref,
                        start_frame=m.start_frame,
                        end_frame=m.end_frame,
                        start_time_ms=m.start_time_ms,
                        end_time_ms=m.end_time_ms,
                        algorithm=m.algorithm,
                        algorithm_version=m.algorithm_version,
                        confidence=m.confidence,
                        confidence_source=m.confidence_source,
                        revision=m.revision,
                    )
                )
            occ_rows = session.scalars(
                _select(SceneGraphOcclusion).where(SceneGraphOcclusion.workspace_id == job.workspace_id, SceneGraphOcclusion.project_id == segs[0].project_id, SceneGraphOcclusion.video_item_id == segs[0].video_item_id).order_by(SceneGraphOcclusion.start_frame)  # noqa: E501
            ).all() if segs else []
            # Filter to edges whose endpoints are in this job's segments
            seg_set = set(seg_ids)
            for o in occ_rows:
                if o.occluder_segment_id in seg_set and o.occludee_segment_id in seg_set:
                    occlusions.append(
                        ExtractionOcclusionData(
                            id=o.id,
                            occluder_segment_id=o.occluder_segment_id,
                            occludee_segment_id=o.occludee_segment_id,
                            start_frame=o.start_frame,
                            end_frame=o.end_frame,
                            start_time_ms=o.start_time_ms,
                            end_time_ms=o.end_time_ms,
                            confidence=o.confidence,
                            confidence_source=o.confidence_source,
                            revision=o.revision,
                        )
                    )
            contact_rows = session.scalars(
                _select(SceneGraphContact).where(SceneGraphContact.workspace_id == job.workspace_id, SceneGraphContact.project_id == segs[0].project_id, SceneGraphContact.video_item_id == segs[0].video_item_id).order_by(SceneGraphContact.start_frame)  # noqa: E501
            ).all() if segs else []
            for c in contact_rows:
                if c.source_segment_id in seg_set and c.target_segment_id in seg_set:
                    contacts.append(
                        ExtractionContactData(
                            id=c.id,
                            source_segment_id=c.source_segment_id,
                            target_segment_id=c.target_segment_id,
                            contact_kind=c.contact_kind,
                            start_frame=c.start_frame,
                            end_frame=c.end_frame,
                            start_time_ms=c.start_time_ms,
                            end_time_ms=c.end_time_ms,
                            confidence=c.confidence,
                            confidence_source=c.confidence_source,
                            revision=c.revision,
                        )
                    )
        return seg_data, motions, occlusions, contacts


@router.get("/{job_id}")
def get_extraction_job(job_id: str) -> ExtractionJobResponse:
    """Job status + published outputs (read-only; fenced state never exposed).

    Repeated/concurrent GETs cause ZERO durable mutations.
    """
    svc = _job_service()
    job = _load_job(job_id)
    manifest = job.input_manifest or {}
    state = job.state
    error: str | None = None
    if job.error is not None:
        err = job.error.get("message") if isinstance(job.error, dict) else job.error
        error = str(err) if err else None
    outputs: list[ExtractionOutputData] = []
    candidates: list[ExtractionCandidateData] = []
    segments: list[ExtractionSegmentData] = []
    motions: list[ExtractionMotionData] = []
    occlusions: list[ExtractionOcclusionData] = []
    contacts: list[ExtractionContactData] = []
    if state == "completed":
        outputs = _published_outputs(svc, job)
        candidates = _manifest_candidates(svc, job)
        segments, motions, occlusions, contacts = _structural_graph_for_job(svc, job)
    return ExtractionJobResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=state,
        progress=job.progress,
        message=_message_for(job, state),
        error=error,
        provider=str(manifest.get("provider") or None) or None,
        extractor_version=str(manifest.get("extractor_version") or None) or None,
        generation=str(manifest.get("generation") or None) or None,
        source_sha256=str(manifest.get("source_sha256") or None) or None,
        video_item_id=str(manifest.get("video_item_id") or None) or None,
        created_at=job.created_at,
        finished_at=job.finished_at,
        outputs=outputs,
        candidates=candidates,
        segments=segments,
        motions=motions,
        occlusions=occlusions,
        contacts=contacts,
    )


@router.get("/{job_id}/outputs")
def get_extraction_outputs(job_id: str) -> dict[str, Any]:
    """The committed output set of a DISCOVER_OBJECTS Job.

    ``409`` while the Job is active (no partial exposure); the outputs are
    served only for terminal-``completed`` Jobs.  ``cancelled``/``failed``
    Jobs return an empty output set (contract §9.5 / §11.2).
    The structural graph (segments/motions/occlusions/contacts) is also exposed
    only for completed jobs (T02 wiring, read-only).
    """
    svc = _job_service()
    job = _load_job(job_id)
    if job.state not in ("completed", "cancelled", "failed"):
        raise HTTPException(409, f"Job is {job.state}; outputs are not published yet")
    outputs = _published_outputs(svc, job) if job.state == "completed" else []
    candidates = _manifest_candidates(svc, job) if job.state == "completed" else []
    segments: list[Any] = []
    motions: list[Any] = []
    occlusions: list[Any] = []
    contacts: list[Any] = []
    if job.state == "completed":
        segments, motions, occlusions, contacts = _structural_graph_for_job(svc, job)
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.state,
        "outputs": [output.model_dump() for output in outputs],
        "candidates": [candidate.model_dump() for candidate in candidates],
        "segments": [s.model_dump() for s in segments],
        "motions": [m.model_dump() for m in motions],
        "occlusions": [o.model_dump() for o in occlusions],
        "contacts": [c.model_dump() for c in contacts],
    }


@router.get("/{job_id}/segments")
def get_extraction_segments(job_id: str) -> dict[str, Any]:
    """Structural segments for a completed DISCOVER_OBJECTS job (read-only).

    409 while active; empty for queued/running/cancelled/failed; graph only when completed.
    """
    svc = _job_service()
    job = _load_job(job_id)
    if job.state not in ("completed", "cancelled", "failed"):
        raise HTTPException(409, f"Job is {job.state}; segments are not published yet")
    segments: list[Any] = []
    motions: list[Any] = []
    occlusions: list[Any] = []
    contacts: list[Any] = []
    if job.state == "completed":
        segments, motions, occlusions, contacts = _structural_graph_for_job(svc, job)
    return {
        "job_id": job.id,
        "status": job.state,
        "segments": [s.model_dump() for s in segments],
        "motions": [m.model_dump() for m in motions],
        "occlusions": [o.model_dump() for o in occlusions],
        "contacts": [c.model_dump() for c in contacts],
    }


@router.get("/{job_id}/graph")
def get_extraction_graph(job_id: str) -> dict[str, Any]:
    """Full structural graph for a completed job (read-only)."""
    svc = _job_service()
    job = _load_job(job_id)
    if job.state not in ("completed", "cancelled", "failed"):
        raise HTTPException(409, f"Job is {job.state}; graph is not published yet")
    segments: list[Any] = []
    motions: list[Any] = []
    occlusions: list[Any] = []
    contacts: list[Any] = []
    if job.state == "completed":
        segments, motions, occlusions, contacts = _structural_graph_for_job(svc, job)
    return {
        "job_id": job.id,
        "status": job.state,
        "segments": [s.model_dump() for s in segments],
        "motions": [m.model_dump() for m in motions],
        "occlusions": [o.model_dump() for o in occlusions],
        "contacts": [c.model_dump() for c in contacts],
    }


def _message_for(job: Any, state: str) -> str:
    """Derive the legacy-style message string from the durable state."""
    if state == "queued":
        return "Queued"
    if state == "running":
        return "Running"
    if state == "cancelling":
        return "Cancelling"
    if state == "cancelled":
        return "Cancelled"
    if state == "completed":
        return "Completed"
    if state == "failed":
        err = job.error.get("message") if isinstance(job.error, dict) else job.error
        return f"Failed: {err}" if err else "Failed"
    return "Pending"


_IMAGE_MIME_ALLOWLIST = frozenset({"image/png", "image/jpeg", "image/webp"})


@router.get("/{job_id}/artifacts/{artifact_id}/content")
def get_artifact_content(job_id: str, artifact_id: str, request: Request) -> Any:
    """Contained image content endpoint for ready thumbnail/mask artifacts.

    Correction B7 guarantees:
    - resolution ONLY through ``ManagedRoot`` (client never supplies a
      filesystem path; containment is enforced by the managed-path rules);
    - ownership: the artifact must be linked to THIS job via the durable
      ObjectRoleArtifact association (stable ids), and its path must live
      under the job's managed image prefix;
    - allowlisted image MIME, recorded size/hash verified against the live
      file (a missing/stale/corrupt file is 409, never a partial body);
    - ``ETag`` from the artifact SHA-256 (304 on ``If-None-Match``) and
      ``X-Content-Type-Options: nosniff``;
    - 404 for unknown job/artifact or a non-image artifact; 409 for
      non-ready, stale (hash/size mismatch), missing-file or escaped-path
      artifacts.
    """
    from fastapi import Response
    from fastapi.responses import FileResponse

    from app.persistence.artifacts import (
        ManagedPathError,
    )
    from app.persistence.artifacts import (
        hash_file as artifact_hash,
    )
    from app.persistence.models import ObjectRoleArtifact as RoleArtifactORM

    svc = _job_service()
    factory = svc.session_factory
    assert factory is not None
    job = _load_job(job_id)
    with factory() as session:
        artifact = session.get(Artifact, artifact_id)
        if artifact is None or artifact.workspace_id != job.workspace_id:
            raise HTTPException(404, "artifact not found")
        if artifact.state != "ready":
            raise HTTPException(409, "artifact is not ready")
        if artifact.kind != "image" or artifact.mime_type not in _IMAGE_MIME_ALLOWLIST:
            raise HTTPException(404, "artifact is not an allowlisted image")
        if artifact.sha256 is None or len(artifact.sha256) != 64:
            raise HTTPException(409, "artifact has no recorded sha256")
        prefix = f"artifacts/{job.workspace_id}/image/{job.id}/"
        if not artifact.relative_path.startswith(prefix):
            raise HTTPException(409, "artifact path is outside this job's scope")
        association = session.execute(
            select(RoleArtifactORM.id).where(
                RoleArtifactORM.artifact_id == artifact_id,
                RoleArtifactORM.source_job_id == job_id,
            )
        ).first()
        if association is None:
            raise HTTPException(404, "artifact is not associated with this job")
    try:
        target = ManagedRoot(svc.managed_root).resolve(artifact.relative_path)
    except ManagedPathError as exc:
        raise HTTPException(409, f"containment rejection: {exc}") from exc
    if not target.is_file():
        raise HTTPException(409, "artifact file is missing (stale)")
    try:
        actual_size = target.stat().st_size
        actual_sha = artifact_hash(target)
    except OSError as exc:
        raise HTTPException(409, f"artifact file unreadable: {exc}") from exc
    if actual_size != (artifact.size_bytes or 0) or actual_sha != artifact.sha256:
        raise HTTPException(409, "artifact file is stale/corrupt (hash/size mismatch)")

    etag = f'"{artifact.sha256}"'
    headers = {
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=31536000, immutable",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(
        path=str(target),
        media_type=artifact.mime_type,
        headers=headers,
        filename=None,
    )
