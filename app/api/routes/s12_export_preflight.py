"""S12-T01 — export preflight READ-ONLY route (frozen contract).

``POST /api/v2/projects/{project_id}/export/preflight`` evaluates the frozen
preflight verdict WITHOUT rendering anything in the HTTP request.  All
durable authorities are consumed read-only:

- readiness via ``compute_project_readiness`` (Decision F, untouched);
- full-apply checkpoint pin via ``S10ApplyRepository`` row reads;
- structural-lock pin via ``StructuralLockRepository`` row reads;
- source media via ``VideoItem`` + ``Artifact`` row reads.

Fail-closed HTTP mapping: unknown project/video → 404, cross-project →
409, stale/param violations → 422.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, get_managed_root
from app.persistence.models import Artifact, Project, VideoItem
from app.persistence.readiness import compute_project_readiness
from app.schemas.s12_export import (
    ExportPreflightRequest,
    ExportPreflightResponse,
    PreflightCheck,
)
from app.services.s12_export.authority import resolve_export_authority
from app.services.s12_export.preflight import (
    PreflightContext,
    evaluate_preflight,
    probe_encoder_support,
)

router = APIRouter(prefix="/api/v2", tags=["s12-export-preflight"])


def _resolve_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404, detail=f"project {project_id!r} not found"
        )
    return project


@router.post(
    "/projects/{project_id}/export/preflight",
    response_model=ExportPreflightResponse,
)
def post_export_preflight(
    project_id: str,
    body: ExportPreflightRequest,
    session: SessionDep,
) -> ExportPreflightResponse:
    """Evaluate the frozen export preflight (no render in request)."""
    project = _resolve_project(session, project_id)
    workspace_id = str(project.workspace_id)

    video = session.get(VideoItem, body.video_item_id)
    if video is None or str(video.project_id) != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"video {body.video_item_id!r} not found in project {project_id!r}",
        )

    # ── SERVER-OWNED AUTHORITY (F02) ────────────────────────────────
    # Every durable identity is resolved READ-ONLY by the authority module:
    # checkpoint pin (workspace/project/hash/revision), config/pack binding
    # through the checkpoint's reskin_config, structural-lock pin, and the
    # immutable CURRENT completed Full Apply output artifact.  An original
    # import is never the export source.
    authority = resolve_export_authority(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=body.video_item_id,
        checkpoint_id=body.checkpoint.checkpoint_id,
        checkpoint_hash=body.checkpoint.checkpoint_hash,
        checkpoint_revision=body.checkpoint.checkpoint_revision,
        manifest_id=body.lock.manifest_id,
        manifest_hash=body.lock.manifest_hash,
        manifest_generation=body.lock.source_generation,
    )
    src_artifact = (
        session.get(Artifact, authority.source_artifact_id)
        if authority.source_artifact_id
        else None
    )
    source_found = src_artifact is not None
    source_ready = bool(
        source_found
        and src_artifact.state == "ready"
        and authority.full_apply_ok
    )
    source_partial = bool(
        src_artifact is not None
        and ".partial" in str(src_artifact.relative_path or "")
    )
    source_w = (
        authority.source_width
        if authority.source_width is not None
        else (video.width if video.width else None)
    )
    source_h = (
        authority.source_height
        if authority.source_height is not None
        else (video.height if video.height else None)
    )
    frame_count: int | None = authority.source_frame_count
    if frame_count is None:
        # Estimate fallback ONLY for the disk heuristic — never identity.
        try:
            if video.duration_ms and video.fps_num and video.fps_den:
                frame_count = int(
                    video.duration_ms * video.fps_num / video.fps_den / 1000
                )
                if frame_count < 1:
                    frame_count = None
        except (TypeError, ValueError, ZeroDivisionError):
            frame_count = None
    native_4k = authority.source_origin == "proved-native"
    ckpt_found = ckpt_hash_ok = ckpt_rev_ok = authority.checkpoint_ok
    ckpt_cross = any(
        c.name == "checkpoint_cross_project" and not c.passed
        for c in authority.checks
    )
    lock_found = lock_hash_ok = lock_gen_ok = authority.lock_ok

    # ── readiness aggregate (consumed, Decision F) ──────────────────
    try:
        readiness = compute_project_readiness(
            session, workspace_id=workspace_id, project_id=project_id
        )
        readiness_status = str(readiness.status)
        readiness_policy = f"{readiness.policy_version}:{readiness.content_hash}"
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"readiness unavailable: {exc}"
        ) from exc
    from app.workflow.qc_checks_handler import policy_bundle as _policy_bundle

    try:
        current_policy = _policy_bundle()
        policy_current = readiness_policy == (
            f"{current_policy['policy_id']}:{current_policy['policy_content_hash']}"
        )
    except Exception:
        policy_current = False

    # ── disk facts for the managed export root ──────────────────────
    # The isolated test root may not exist on disk yet — walk up to the
    # first existing ancestor so disk_usage never fails on a missing dir.
    try:
        _disk_path = Path(str(get_managed_root()))
        while not _disk_path.exists() and len(_disk_path.parts) > 1:
            _disk_path = _disk_path.parent
        disk_free: int | None = shutil.disk_usage(str(_disk_path)).free
    except Exception:
        disk_free = None

    # C02 real capability probe (no permanent stub, no const flag): support
    # is True ONLY when the ffmpeg encoder probe passes; any failure keeps
    # the profile check failed with the concrete reason.
    _cap_ok, profile_basis = probe_encoder_support(str(body.profile_id))
    ctx = PreflightContext(
        project_id=project_id,
        video_item_id=body.video_item_id,
        source_found=source_found,
        source_ready=source_ready,
        source_is_partial=source_partial,
        source_width=source_w,
        source_height=source_h,
        source_frame_count=frame_count,
        source_native_4k=native_4k,
        upscale_method=None,
        checkpoint_found=ckpt_found,
        checkpoint_hash_match=ckpt_hash_ok,
        checkpoint_revision_match=ckpt_rev_ok,
        checkpoint_cross_project=ckpt_cross,
        lock_found=lock_found,
        lock_hash_match=lock_hash_ok,
        lock_generation_match=lock_gen_ok,
        readiness_status=readiness_status,
        readiness_policy=readiness_policy,
        readiness_policy_current=policy_current,
        disk_free_bytes=disk_free,
        profile_supported=_cap_ok,
        profile_support_basis=profile_basis,
    )
    resp = evaluate_preflight(body, ctx)
    # Attach the SERVER-RESOLVED durable identities (F02) — actual artifact/
    # run/publication ids — plus authority-only reasons the generic gates do
    # not express (FULL_APPLY_MISSING / SOURCE_STALE / CONFIG_MISSING).
    resp.source_artifact_id = authority.source_artifact_id
    resp.source_sha256 = authority.source_sha256
    resp.source_frame_count = authority.source_frame_count
    resp.source_fps_num = authority.source_fps_num
    resp.source_fps_den = authority.source_fps_den
    resp.full_apply_run_id = authority.full_apply_run_id
    resp.full_apply_publication_id = authority.full_apply_publication_id
    resp.job_id = None  # preflight never mutates: no export Job is created here
    seen = set(resp.reasons)
    for c in authority.checks:
        if c.passed:
            continue
        resp.checks.append(
            PreflightCheck(
                name="authority_" + c.name,
                passed=False,
                reason=c.reason,
                detail=c.detail,
            )
        )
        if c.reason not in seen:
            resp.reasons.append(c.reason)
            seen.add(c.reason)
    resp.eligible = all(c.passed for c in resp.checks)
    return resp
