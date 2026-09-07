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
from app.persistence.s10_full_apply import S10ApplyRepository
from app.persistence.structural_lock import (
    StructuralLockNotFoundError,
    StructuralLockRepository,
)
from app.schemas.s12_export import (
    ExportPreflightRequest,
    ExportPreflightResponse,
)
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

    # ── source media facts (read-only) ──────────────────────────────
    artifact = None
    if video.source_artifact_id:
        artifact = session.get(Artifact, video.source_artifact_id)
    source_found = artifact is not None
    source_ready = bool(source_found and artifact.state == "ready")
    source_partial = bool(
        source_found and ".partial" in str(artifact.relative_path or "")
    )
    source_w = video.width
    source_h = video.height
    frame_count: int | None = None
    try:
        if video.duration_ms and video.fps_num and video.fps_den:
            frame_count = int(video.duration_ms * video.fps_num / video.fps_den / 1000)
            if frame_count < 1:
                frame_count = None
    except (TypeError, ValueError, ZeroDivisionError):
        frame_count = None
    # F-OBS-01: native_4k resolved AFTER the checkpoint block below (it
    # needs the checkpoint pin facts as the native-origin authority).
    _artifact_sha = str(getattr(artifact, "sha256", "") or "") if source_found else ""
    native_4k = False

    # ── checkpoint pin facts (read-only row comparison) ─────────────
    s10 = S10ApplyRepository(session)
    ckpt_found = ckpt_hash_ok = ckpt_rev_ok = False
    ckpt_cross = False
    try:
        current: list = s10.list_runs(workspace_id, project_id=project_id)
        ckpt_row = None
        for run in current:
            if run.video_item_id == body.video_item_id and run.status == "completed":
                break
        # Direct checkpoint row read for the requested pin.
        from app.persistence.models import ApplyCheckpoint as _Ckpt

        ckpt_row = session.get(_Ckpt, body.checkpoint.checkpoint_id)
        if ckpt_row is not None and str(ckpt_row.workspace_id) == workspace_id:
            ckpt_found = True
            ckpt_cross = str(ckpt_row.project_id) != project_id
            ckpt_hash_ok = str(ckpt_row.checkpoint_hash) == body.checkpoint.checkpoint_hash
            ckpt_rev_ok = (
                int(ckpt_row.reskin_config_revision) == body.checkpoint.checkpoint_revision
            )
    except HTTPException:
        raise
    except Exception:
        ckpt_found = False

    # F-OBS-01: native label needs PROVED native origin — dims alone never
    # suffice.  The server-owned native-origin authority T01 reads is the
    # full-apply lineage: recorded artifact sha256 AND a matching checkpoint
    # pin AND ready 3840x2160 source with no .partial marker.  Anything else
    # (incl. 3840x2160 of unproved origin, e.g. an already-upscaled file)
    # is upscale honesty.
    native_4k = (
        source_ready
        and not source_partial
        and source_w == 3840
        and source_h == 2160
        and len(_artifact_sha) == 64
        and ckpt_found
        and ckpt_hash_ok
        and ckpt_rev_ok
        and not ckpt_cross
    )

    # ── structural-lock pin facts (read-only) ───────────────────────
    lock_repo = StructuralLockRepository(session)
    lock_found = lock_hash_ok = lock_gen_ok = False
    try:
        manifest = lock_repo.get_manifest(body.lock.manifest_id, workspace_id)
        lock_found = True
        lock_hash_ok = manifest.manifest_hash_hex == body.lock.manifest_hash
        lock_gen_ok = (
            manifest.video_item_id == body.video_item_id
            and manifest.project_id == project_id
            and manifest.source_generation == body.lock.source_generation
            and manifest.status in ("draft", "active")
        )
    except StructuralLockNotFoundError:
        lock_found = False
    except Exception:
        lock_found = False

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
    return evaluate_preflight(body, ctx)
