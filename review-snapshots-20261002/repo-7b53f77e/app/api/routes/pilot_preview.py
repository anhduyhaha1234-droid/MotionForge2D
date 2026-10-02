"""Public V3 single-shot pilot-preview API.

This namespace is intentionally separate from S09/S10.  The route only
resolves the existing legacy project + durable chain identity and submits a
reconstructable pilot job; rendering is owned by the durable worker.
"""

from __future__ import annotations

import hashlib
import math
import os
from fractions import Fraction
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import get_config, get_job_service, get_project_service, get_project_workflow
from app.api.helpers import job_response
from app.persistence import IdempotencyKeyInUse
from app.persistence.artifacts import ManagedRoot
from app.persistence.models import Job
from app.schemas.pilot_preview import (
    PilotPreviewContextRequest,
    PilotPreviewContextResponse,
    PilotPreviewJobResponse,
    PilotPreviewSubmitRequest,
    PilotPreviewSubmitResponse,
)
from app.services.pilot_preview.pose_composition import COMPOSITION_REVISION
from app.services.pilot_preview.clean_plate_pack import PlateResolutionError, resolve_reviewed_plate
from app.services.pilot_preview.scene_contract import (
    COMPAT_REQUIREMENTS,
    build_scene_contract,
    scene_contract_hash,
)
from app.services.pilot_preview.scene_reconstruction import (
    PROTECTED_ROLES,
    RECONSTRUCTION_REVISION,
)
from app.services.video_probe import probe_video
from app.workflow import analyze_orchestrator
from app.workflow.pilot_preview_jobs import (
    _ASSET_REL,
    JOB_TYPE_PILOT_PREVIEW,
    PILOT_PIPELINE_REVISION,
    PILOT_RENDER_GEOMETRY,
    PilotPreviewError,
    build_output_relpaths,
    compute_input_identity_sha256,
    output_relpaths_for_manifest,
    pack_gate_verdict,
)

router = APIRouter(prefix="/api/v2/pilot-preview", tags=["pilot-preview"])
WORKSPACE_ID = "default"
PINNED_ASSET_SHA256 = "e07e2a3a76ea3d7d3144ae43f89ebbcc225a37cf91aa6ab159961f6d7349dc47"
PINNED_SAM2_SHA256 = "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_path() -> Path:
    return (Path(get_config().project_root).resolve().parent / _ASSET_REL).resolve()


def _sam2_path() -> Path:
    return (Path(get_config().project_root).resolve().parent / "models" / "sam2.1_hiera_large.pt").resolve()


def _pack_root() -> Path:
    """Isolated runtime pack root; never MAIN/S11/S12 or the repository."""
    return (Path(get_config().project_root).resolve().parent / "assets" / "pilot-packs").resolve()


def _clean_plate_root() -> Path:
    """Server-owned reviewed plates, separate from the immutable source pack."""
    # The launcher declares MOTIONFORGE_PILOT_RUN_ROOT as the WorkRoot while
    # the effective mutable runtime is its ``runtime`` child.  Resolve plates
    # beside the server-owned pack/models roots under that effective runtime;
    # otherwise a fresh launcher run would silently look in WorkRoot/assets
    # and reject a plate that was validated under runtime/assets.
    runtime_parent = Path(get_config().project_root).resolve().parent
    if runtime_parent.name.lower() == "runtime":
        return (runtime_parent / "assets" / "pilot-plates").resolve()
    return (_pilot_runtime_root() / "assets" / "pilot-plates").resolve()


def _pilot_runtime_root() -> Path:
    """Use the launcher-declared fresh run root for every pilot manifest."""
    configured = os.environ.get("MOTIONFORGE_PILOT_RUN_ROOT", "").strip()
    return Path(configured).resolve() if configured else Path(get_config().project_root).resolve().parent


def _clean_plate_verdict(plate_id: str | None, source_sha256: str) -> dict[str, Any]:
    if not plate_id:
        return {
            "compatible": False,
            "code": "CLEAN_PLATE_REQUIRED",
            "reason": "an approved source-bound full-frame clean plate is required before render",
            "missing": ["clean_plate_id"],
        }
    try:
        plate = resolve_reviewed_plate(
            plate_id,
            _clean_plate_root(),
            source_sha256=source_sha256,
            source_window=(450, 570),
            allow_private_preview=True,
        )
    except PlateResolutionError as exc:
        return {"compatible": False, "code": exc.code, "reason": str(exc), "missing": []}
    return {
        "compatible": True,
        "plate": plate,
        **{key: plate[key] for key in ("plate_id", "version", "approval_status", "manifest_sha256", "content_sha256", "image_sha256")},
    }


def _resolve_project(project_id: str) -> tuple[str, str | None]:
    """Resolve either the legacy id or the durable UUID to a legacy project."""
    workflow = get_project_workflow()
    try:
        workflow.get_project(project_id)
        legacy_id = project_id
    except FileNotFoundError:
        durable = next(
            (record for record in get_project_service().list(WORKSPACE_ID, active_only=False) if record.id == project_id),
            None,
        )
        if durable is None or not durable.legacy_id:
            raise HTTPException(404, "Pilot project not found")
        legacy_id = durable.legacy_id
    durable_id = next(
        (record.id for record in get_project_service().list(WORKSPACE_ID, active_only=False) if record.legacy_id == legacy_id),
        None,
    )
    return legacy_id, durable_id


def _source_for(legacy_id: str) -> tuple[Any, Path]:
    try:
        project = get_project_workflow().get_project(legacy_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Pilot project not found") from exc
    source = getattr(project, "source_video", "") or ""
    path = Path(source).resolve()
    if not path.is_file():
        raise HTTPException(409, "Source video is missing; run the public upload step first")
    return project, path


def _chain(legacy_id: str, generation: str) -> dict[str, object]:
    return analyze_orchestrator.get_analyze_orchestrator().chain_state(legacy_id, generation)


def _job_manifest(job_id: str) -> tuple[Any, dict[str, Any]]:
    from app.persistence import JobNotFoundError

    service = get_job_service()
    info = service.get_job(job_id)
    if info is None or service.session_factory is None:
        raise HTTPException(404, "Pilot preview job not found")
    with service.session_factory() as session:
        try:
            record = session.get(Job, job_id)
        except JobNotFoundError as exc:
            raise HTTPException(404, "Pilot preview job not found") from exc
        if record is None or record.workspace_id != WORKSPACE_ID or record.job_type != JOB_TYPE_PILOT_PREVIEW or record.owner_type != "pilot_preview":
            raise HTTPException(404, "Pilot preview job not found")
        try:
            import json
            manifest = json.loads(record.input_manifest_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(409, "Pilot preview manifest is malformed") from exc
        if not isinstance(manifest, dict):
            raise HTTPException(409, "Pilot preview manifest is malformed")
        try:
            if compute_input_identity_sha256(manifest) != manifest.get("input_identity_sha256"):
                raise ValueError("identity")
            output_relpaths_for_manifest(manifest)
        except Exception as exc:  # noqa: BLE001 - fail closed on persisted tampering
            raise HTTPException(409, "Pilot preview manifest identity is invalid") from exc
        policy = manifest.get("policy")
        if not isinstance(policy, dict) or policy.get("preview_only") is not True or policy.get("no_full_apply") is not True:
            raise HTTPException(409, "Pilot preview policy binding is invalid (preview-only)")
        if str(manifest.get("project_id")) != str(record.owner_id):
            raise HTTPException(409, "Pilot preview owner binding is invalid")
        if str(manifest.get("generation")) != str(record.input_generation):
            raise HTTPException(409, "Pilot preview generation binding is invalid")
        return info, manifest


def _validate_annotations(body: PilotPreviewSubmitRequest, metadata: Any) -> None:
    if body.role != "seated_character":
        raise HTTPException(422, "pilot preview role must be seated_character")
    if body.source_prompt.strip() != body.source_prompt:
        raise HTTPException(422, "source_prompt must not have leading/trailing whitespace")
    if not body.source_prompt.strip():
        raise HTTPException(422, "source_prompt must be non-empty")
    annotation_values = (
        *body.mask_correction.bbox_xywh_norm,
        body.mask_correction.confidence,
        *body.occluder.region_xywh_norm,
    )
    if not all(math.isfinite(value) for value in annotation_values):
        raise HTTPException(422, "mask and occluder annotations must contain finite values")
    if Fraction(metadata.fps).limit_denominator(1001 * 32) != Fraction(30, 1):
        raise HTTPException(422, "pilot preview requires an exact 30/1 source timebase")
    if (metadata.width, metadata.height) != (640, 360):
        raise HTTPException(422, "pilot preview requires the pinned 640x360 source geometry")
    if not body.start_frame <= body.mask_correction.source_frame < body.end_frame:
        raise HTTPException(422, "mask correction source_frame must lie inside the preview window")
    keyframes = body.anchor_keyframes
    frames = [item.frame for item in keyframes]
    if frames[0] != body.start_frame or frames[-1] != body.end_frame - 1 or frames != sorted(frames) or len(set(frames)) != len(frames):
        raise HTTPException(422, "anchor keyframes must strictly cover the preview window")
    for item in keyframes:
        if not body.start_frame <= item.frame < body.end_frame:
            raise HTTPException(422, "anchor keyframe lies outside the preview window")
        if not all(math.isfinite(value) for value in (*item.anchor_xy_norm, *item.operator_offset_xy_norm, item.scale, item.rotation_deg)):
            raise HTTPException(422, "anchor keyframes must contain finite values")
    if body.anchor_mode == "source_derived" and any(item.operator_offset_xy_norm != (0.0, 0.0) for item in keyframes):
        raise HTTPException(422, "source_derived anchor mode cannot carry an operator offset")


@router.get("/asset")
def get_pinned_asset() -> FileResponse:
    path = _asset_path()
    if not path.is_file() or _sha256(path) != PINNED_ASSET_SHA256:
        raise HTTPException(503, "Pinned V3 RGBA asset is unavailable or hash-mismatched")
    return FileResponse(str(path), media_type="image/png", filename="v3-seated-rgba.png")


@router.post("/context", response_model=PilotPreviewContextResponse)
def resolve_context(body: PilotPreviewContextRequest) -> PilotPreviewContextResponse:
    legacy_id, durable_id = _resolve_project(body.project_id)
    project, source = _source_for(legacy_id)
    try:
        metadata = probe_video(source)
    except Exception as exc:  # noqa: BLE001 - stable API boundary
        raise HTTPException(503, f"Source probe unavailable: {exc}") from exc
    chain = _chain(legacy_id, body.generation)
    durable_video_id = chain.get("video_item_id")
    fps = Fraction(metadata.fps).limit_denominator(1001 * 32)
    source_sha = _sha256(source)
    if body.pack_id:
        selected_pack_verdict = pack_gate_verdict(
            {
                "asset_sha256": "",
                "pack_id": body.pack_id,
                "pack_root": str(_pack_root()),
                "source_sha256": source_sha,
            }
        )
        selected_asset_sha = str(selected_pack_verdict.get("pack_content_sha256", ""))
        selected_asset_url = ""
    else:
        selected_pack_verdict = pack_gate_verdict({"asset_sha256": PINNED_ASSET_SHA256})
        selected_asset_sha = PINNED_ASSET_SHA256
        selected_asset_url = "/api/v2/pilot-preview/asset"
    plate_verdict = _clean_plate_verdict(body.clean_plate_id, source_sha)
    return PilotPreviewContextResponse(
        project_id=body.project_id,
        legacy_project_id=legacy_id,
        durable_project_id=durable_id,
        durable_video_item_id=str(durable_video_id) if durable_video_id else None,
        generation=body.generation,
        chain_status=str(chain.get("chain_status", "idle")),
        source_name=Path(source).name,
        source_sha256=source_sha,
        width=metadata.width,
        height=metadata.height,
        fps_num=fps.numerator,
        fps_den=fps.denominator,
        frame_count=metadata.total_frames,
        duration_seconds=metadata.duration_seconds,
        allowed_frame_window=(0, metadata.total_frames),
        asset_sha256=selected_asset_sha,
        asset_url=selected_asset_url,
        import_endpoint=f"/api/projects/{legacy_id}/video",
        analyze_endpoint=f"/api/projects/{legacy_id}/analyze",
        legacy_id_bridge={
            "submitted_project_id": body.project_id,
            "legacy_project_id": legacy_id,
            "durable_project_id": durable_id,
            "durable_video_item_id": str(durable_video_id) if durable_video_id else None,
        },
        composition_revision=COMPOSITION_REVISION,
        pack_required_capabilities=list(COMPAT_REQUIREMENTS),
        pack_verdict_for_pinned_asset=selected_pack_verdict,
        selected_pack_id=body.pack_id,
        clean_plate_required=True,
        clean_plate_verdict=plate_verdict,
        selected_clean_plate_id=body.clean_plate_id,
    )


@router.post("/jobs", response_model=PilotPreviewSubmitResponse, status_code=202)
def submit_preview(body: PilotPreviewSubmitRequest) -> PilotPreviewSubmitResponse:
    legacy_id, durable_id = _resolve_project(body.project_id)
    _project, source = _source_for(legacy_id)
    try:
        metadata = probe_video(source)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Source probe unavailable: {exc}") from exc
    if (body.start_frame, body.end_frame) != (450, 570):
        raise HTTPException(422, "pilot preview is fixed to source window [450,570) (120 frames)")
    if body.end_frame > metadata.total_frames:
        raise HTTPException(422, "pilot preview frame range exceeds the decoded source")
    if (metadata.width, metadata.height) != (640, 360):
        raise HTTPException(422, "pilot preview requires the pinned 640x360 source geometry")
    _validate_annotations(body, metadata)
    # Server-owned pack verdict BEFORE chain lookup, job creation, or any
    # heavy work: compatibility reasons are exposed here, with no job row.
    gate = pack_gate_verdict(
        {
            "asset_sha256": body.asset_sha256,
            "pack_id": body.pack_id,
            "pack_root": str(_pack_root()),
            "source_sha256": _sha256(source),
        }
    )
    if not gate["compatible"]:
        missing = ", ".join(gate.get("missing") or ["see reason"])
        raise HTTPException(
            422,
            f"{gate['code']}: {gate['reason']} (missing: {missing})",
        )
    chain = _chain(legacy_id, body.generation)
    if chain.get("chain_status") != "completed":
        raise HTTPException(409, f"fresh public import/analyze chain is not completed: {chain.get('chain_status')}")

    pack = gate["pack"]
    asset_state = pack["states"]["seated_book_closed"]
    asset = Path(asset_state["path"])
    sam2 = _sam2_path()
    if not sam2.is_file() or _sha256(sam2) != PINNED_SAM2_SHA256:
        raise HTTPException(503, "Pinned SAM2 checkpoint is unavailable or hash-mismatched")

    scene_contract = build_scene_contract(source_sha256=_sha256(source))
    clean_plate = _clean_plate_verdict(body.clean_plate_id, _sha256(source))
    if body.clean_plate_id and not clean_plate.get("compatible"):
        raise HTTPException(422, f"{clean_plate.get('code', 'CLEAN_PLATE_REQUIRED')}: {clean_plate.get('reason', 'reviewed clean plate rejected')}")
    resolved_plate = clean_plate.get("plate") if clean_plate.get("compatible") else None

    manifest: dict[str, Any] = {
        "schema_version": "pilot-preview-v1",
        "pipeline_revision": PILOT_PIPELINE_REVISION,
        "render_geometry_contract": dict(PILOT_RENDER_GEOMETRY),
        "composition_revision": COMPOSITION_REVISION,
        "pack_id": pack["pack_id"],
        "pack_version": pack["version"],
        "pack_root": str(_pack_root()),
        "pack_manifest_path": pack["manifest_path"],
        "pack_manifest_sha256": pack["manifest_sha256"],
        "pack_content_sha256": pack["content_sha256"],
        "pack_approval_status": pack["approval_status"],
        "pack_semantic_review_status": pack["semantic_review_status"],
        "pack_state_identity": {
            state_id: {
                "sha256": state["sha256"],
                "canvas_size": state["canvas_size"],
                "anchors": state["anchors"],
                "pose": state["pose"],
                "mouth": state["mouth"],
                "book": state["book"],
                "arm_rig": (
                    {
                        "revision": state["arm_rig"]["revision"],
                        "joints": state["arm_rig"]["joints"],
                        "bend_sign": state["arm_rig"]["bend_sign"],
                        "occlusion": state["arm_rig"]["occlusion"],
                        "roles": {
                            side: {
                                role_name: {
                                    "relative_path": role["relative_path"],
                                    "sha256": role["sha256"],
                                    "start_joint": role["start_joint"],
                                    "end_joint": role["end_joint"],
                                }
                                for role_name, role in sorted(state["arm_rig"]["roles"][side].items())
                            }
                            for side in ("left", "right")
                        },
                    }
                    if isinstance(state.get("arm_rig"), dict)
                    else None
                ),
            }
            for state_id, state in pack["states"].items()
        },
        "pack_capabilities": pack["capabilities"],
        "managed_root": str(get_job_service().managed_root),
        "project_root": str(get_config().project_root),
        "runtime_root": str(_pilot_runtime_root()),
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "asset_path": str(asset),
        "asset_sha256": pack["content_sha256"],
        "asset_state_sha256": asset_state["sha256"],
        "asset_state_id": "seated_book_closed",
        "anchor_mode": body.anchor_mode,
        "sam2_checkpoint_path": str(sam2),
        "sam2_checkpoint_sha256": PINNED_SAM2_SHA256,
        "sam2_model_cfg": "configs/sam2.1/sam2.1_hiera_l.yaml",
        "sam2_device": "cpu",
        "project_id": legacy_id,
        "durable_project_id": durable_id,
        "durable_video_item_id": chain.get("video_item_id"),
        "legacy_id_bridge": {
            "submitted_project_id": body.project_id,
            "legacy_project_id": legacy_id,
            "durable_project_id": durable_id,
            "durable_video_item_id": chain.get("video_item_id"),
        },
        "generation": body.generation,
        "start_frame": body.start_frame,
        "end_frame": body.end_frame,
        "role": body.role,
        "source_prompt": body.source_prompt,
        "mask_correction": body.mask_correction.model_dump(),
        "anchor_keyframes": [item.model_dump() for item in body.anchor_keyframes],
        "occluder": body.occluder.model_dump(),
        "scene_contract_hash": scene_contract_hash(scene_contract),
        "reconstruction_revision": RECONSTRUCTION_REVISION,
        "clean_plate_identity": {
            "revision": resolved_plate["revision"] if resolved_plate else RECONSTRUCTION_REVISION,
            "status": resolved_plate["approval_status"] if resolved_plate else "REQUIRED",
            "source_sha256": _sha256(source),
            "mask_correction": body.mask_correction.model_dump(),
            "algorithm": "reviewed_plate_pixels_only" if resolved_plate else "diagnostic_only_source_reuse_then_bounded_telea",
        },
        "clean_plate_id": resolved_plate["plate_id"] if resolved_plate else None,
        "clean_plate_root": str(_clean_plate_root()),
        "clean_plate_manifest_sha256": resolved_plate["manifest_sha256"] if resolved_plate else None,
        "clean_plate_content_sha256": resolved_plate["content_sha256"] if resolved_plate else None,
        "clean_plate_image_sha256": resolved_plate["image_sha256"] if resolved_plate else None,
        "clean_plate_source_sha256": resolved_plate["source_sha256"] if resolved_plate else None,
        "clean_plate_source_window": resolved_plate["source_window"] if resolved_plate else None,
        "clean_plate_revision": resolved_plate["revision"] if resolved_plate else None,
        "protected_masks_identity": {
            "revision": RECONSTRUCTION_REVISION,
            "roles": list(PROTECTED_ROLES),
            "source_sha256": _sha256(source),
        },
        "effective_geometry": dict(PILOT_RENDER_GEOMETRY),
        "policy": {
            "preview_only": True,
            "single_shot": True,
            "max_frames": 150,
            "no_full_apply": True,
            "no_s12": True,
            "preserve_source_audio": True,
        },
    }
    manifest["input_identity_sha256"] = compute_input_identity_sha256(manifest)
    manifest["output_relpaths"] = build_output_relpaths(manifest["input_identity_sha256"])
    idempotency_key = f"pilot-preview:{manifest['input_identity_sha256']}"
    try:
        info = get_job_service().create_job(
            JOB_TYPE_PILOT_PREVIEW,
            manifest,
            workspace_id=WORKSPACE_ID,
            owner_type="pilot_preview",
            owner_id=legacy_id,
            idempotency_key=idempotency_key,
            input_generation=body.generation,
            priority=40,
            max_attempts=1,
        )
    except IdempotencyKeyInUse as exc:
        winner_id = exc.job_id
        service = get_job_service()
        if winner_id is None and service.session_factory is not None:
            with service.session_factory() as session:
                winner = session.scalar(select(Job).where(
                    Job.workspace_id == WORKSPACE_ID,
                    Job.idempotency_key == idempotency_key,
                    Job.input_generation == body.generation,
                ))
                winner_id = winner.id if winner is not None else None
        if winner_id is None:
            raise HTTPException(409, "pilot preview idempotency winner could not be resolved") from exc
        info, existing_manifest = _job_manifest(winner_id)
        if existing_manifest.get("input_identity_sha256") != manifest["input_identity_sha256"]:
            raise HTTPException(409, "pilot preview idempotency winner has a different input identity") from exc
        return PilotPreviewSubmitResponse(job_id=info.job_id, status=info.state.value, manifest=existing_manifest)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(409, f"pilot preview submission rejected: {exc}") from exc
    return PilotPreviewSubmitResponse(job_id=info.job_id, status=info.state.value, manifest=manifest)


@router.get("/jobs/{job_id}", response_model=PilotPreviewJobResponse)
def get_preview_job(job_id: str) -> PilotPreviewJobResponse:
    info, manifest = _job_manifest(job_id)
    data = job_response(info)
    media: dict[str, str] = {}
    if data.get("status") == "completed":
        media = {
            "before": f"/api/v2/pilot-preview/jobs/{job_id}/media/before",
            "after": f"/api/v2/pilot-preview/jobs/{job_id}/media/after",
            "evidence": f"/api/v2/pilot-preview/jobs/{job_id}/media/evidence",
        }
    return PilotPreviewJobResponse(job=data, manifest=manifest, media=media)


@router.post("/jobs/{job_id}/cancel")
def cancel_preview_job(job_id: str) -> dict[str, object]:
    service = get_job_service()
    _job_manifest(job_id)
    if not service.cancel_job(job_id):
        info = service.get_job(job_id)
        raise HTTPException(409, f"Pilot preview is already terminal: {info.state.value if info else 'unknown'}")
    return {"status": "cancel_requested", "job_id": job_id}


@router.post("/jobs/{job_id}/approve")
def reject_preview_approval(job_id: str) -> dict[str, object]:
    """Preview-only authority proof: approvals are never authorized here.

    The route exists so the UI (and tests) can prove that no preview job
    can mint an approval or Full Apply authorization.  It always fails
    closed with 403 and mutates nothing.
    """
    _job_manifest(job_id)
    raise HTTPException(403, "pilot preview is preview-only; approvals and Full Apply are never authorized")


@router.get("/jobs/{job_id}/media/{kind}")
def get_preview_media(job_id: str, kind: str) -> FileResponse:
    _info, manifest = _job_manifest(job_id)
    info = get_job_service().get_job(job_id)
    if info is None or info.state.value != "completed":
        raise HTTPException(409, "Pilot preview media is not ready")
    try:
        relative = output_relpaths_for_manifest(manifest)[kind]
    except (KeyError, PilotPreviewError):
        raise HTTPException(404, "Unknown pilot preview media kind")
    path = ManagedRoot(Path(manifest["managed_root"])).resolve(relative)
    if not path.is_file():
        raise HTTPException(404, "Pilot preview output is missing")
    media_type = "application/json" if kind == "evidence" else "video/mp4"
    return FileResponse(str(path), media_type=media_type, filename=path.name)


__all__ = ["router"]
