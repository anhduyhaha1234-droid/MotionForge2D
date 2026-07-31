"""Project CRUD endpoints."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import (
    get_config,
    get_final_render_service,
    get_job_service,
    get_object_extraction_service,
    get_preview_render_service,
    get_project_workflow,
    get_replacement_service,
    get_segmentation_service,
)
from app.api.helpers import job_response
from app.schemas import (
    ObjectKind,
    ProjectData,
    ReplacementConfig,
    SceneInfo,
    SelectionInput,
    TrackedObject,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ─── Request/Response models ─────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str


class CreateProjectResponse(BaseModel):
    project_id: str
    project: ProjectData


class CreateObjectRequest(BaseModel):
    name: str
    kind: ObjectKind = ObjectKind.CHARACTER
    selection: SelectionInput
    scene_id: int
    mask_data: list[list[int]] | None = None


class PreviewMaskRequest(BaseModel):
    frame_index: int
    selection: SelectionInput
    backend: str = "contour"


class ReplacementSettingsRequest(BaseModel):
    replacement_config: ReplacementConfig


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_project(body: CreateProjectRequest) -> CreateProjectResponse:
    """Create a new project."""
    pwf = get_project_workflow()
    project_id, data = pwf.create_project(body.name)
    return CreateProjectResponse(project_id=project_id, project=data)


@router.post("/{project_id}/video")
async def upload_video(project_id: str, file: UploadFile) -> dict:
    """Upload a video file for the project."""
    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    dest = proj_dir / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    pwf.set_video(project_id, file.filename)
    return {"status": "ok", "filename": file.filename}


@router.post("/{project_id}/ingest")
def trigger_ingest(project_id: str) -> dict:
    """Trigger ingest (probe + scene detect + frame extract). Returns a job."""
    from app.workflow.ingest_service import IngestService

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    svc = IngestService(get_project_workflow()._config, pwf)
    job_svc = get_job_service()

    def worker(progress_cb, is_cancelled):
        return svc.ingest(project_id, progress_cb, is_cancelled)

    info = job_svc.create_job("ingest", worker)
    return job_response(info)


@router.get("/{project_id}")
def get_project(project_id: str) -> ProjectData:
    """Get project data."""
    pwf = get_project_workflow()
    try:
        return pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err


@router.get("/{project_id}/scenes")
def list_scenes(project_id: str) -> list[SceneInfo]:
    """List scenes for a project."""
    pwf = get_project_workflow()
    try:
        data = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err
    return data.scenes


@router.get("/{project_id}/frames/{frame_index}")
def get_frame(project_id: str, frame_index: int, scene_id: int = 0) -> FileResponse:
    """Serve a frame image."""
    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)
    frame_path = (
        proj_dir / "frames" / f"scene_{scene_id}"
        / f"frame_{frame_index:06d}.png"
    )

    if not frame_path.exists():
        raise HTTPException(404, f"Frame {frame_index} not found")
    return FileResponse(str(frame_path), media_type="image/png")


@router.post("/{project_id}/objects/preview-mask")
def preview_mask(project_id: str, body: PreviewMaskRequest) -> dict:
    """Preview mask for a selection on a frame."""
    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)
    frame_path = (
        proj_dir / "frames" / "scene_0" / f"frame_{body.frame_index:06d}.png"
    )

    if not frame_path.exists():
        for scene_dir in (proj_dir / "frames").glob("scene_*"):
            candidate = scene_dir / f"frame_{body.frame_index:06d}.png"
            if candidate.exists():
                frame_path = candidate
                break
        else:
            raise HTTPException(404, f"Frame {body.frame_index} not found")

    seg_svc = get_segmentation_service()
    try:
        mask = seg_svc.preview_mask(frame_path, body.selection, body.backend)
    except Exception as e:
        raise HTTPException(500, str(e)) from e

    import cv2

    mask_dir = proj_dir / "debug"
    mask_dir.mkdir(parents=True, exist_ok=True)
    mask_path = mask_dir / f"preview_mask_{body.frame_index}.png"
    cv2.imwrite(str(mask_path), mask)

    return {
        "mask_path": str(mask_path),
        "nonzero_pixels": int((mask > 0).sum()),
        "frame_index": body.frame_index,
    }


@router.post("/{project_id}/objects", status_code=201)
def create_object(project_id: str, body: CreateObjectRequest) -> dict:
    """Create a tracked object."""
    import cv2
    import numpy as np

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    obj_id = uuid.uuid4().hex[:8]
    obj = TrackedObject(
        object_id=obj_id,
        name=body.name,
        kind=body.kind,
        selection=body.selection,
        scene_id=body.scene_id,
    )

    proj_dir = pwf._project_dir(project_id)
    mask_dir = proj_dir / "objects" / obj_id / "masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    initial_mask_path = mask_dir / "initial_mask.png"

    if body.mask_data:
        mask_arr = np.array(body.mask_data, dtype=np.uint8)
        cv2.imwrite(str(initial_mask_path), mask_arr)
    else:
        # Fallback 1: specific frame preview mask
        f_idx = body.selection.frame_index
        debug_mask_path = proj_dir / "debug" / f"preview_mask_{f_idx}.png"
        if debug_mask_path.exists():
            shutil.copy2(str(debug_mask_path), str(initial_mask_path))
        else:
            # Fallback 2: most recent preview mask by mtime
            debug_dir = proj_dir / "debug"
            if debug_dir.exists():
                preview_masks = sorted(
                    debug_dir.glob("preview_mask_*.png"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if preview_masks:
                    shutil.copy2(str(preview_masks[0]), str(initial_mask_path))

        # Fallback 3: compute mask directly
        if not initial_mask_path.exists():
            try:
                s_id = body.scene_id
                frame_path = (
                    proj_dir / "frames" / f"scene_{s_id}" / f"frame_{f_idx:06d}.png"
                )
                if not frame_path.exists():
                    for scene_dir in (proj_dir / "frames").glob("scene_*"):
                        candidate = scene_dir / f"frame_{f_idx:06d}.png"
                        if candidate.exists():
                            frame_path = candidate
                            break
                if frame_path.exists():
                    seg_svc = get_segmentation_service()
                    mask = seg_svc.preview_mask(frame_path, body.selection, "contour")
                    cv2.imwrite(str(initial_mask_path), mask)
            except Exception:
                pass

    data = pwf.add_tracked_object(project_id, obj)
    return {"object_id": obj_id, "project": data.model_dump()}


@router.post("/{project_id}/objects/{object_id}/propagate")
def propagate_object(project_id: str, object_id: str) -> dict:
    """Propagate masks for a tracked object. Returns a job."""
    import cv2

    from app.services.motion_extraction import compute_scene_motion, smooth_motion

    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)

    try:
        obj = pwf.get_tracked_object(project_id, object_id)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, str(e)) from e

    mask_path = proj_dir / "objects" / object_id / "masks" / "initial_mask.png"
    if not mask_path.exists():
        debug_dir = proj_dir / "debug"
        f_idx = obj.selection.frame_index
        frame_mask = debug_dir / f"preview_mask_{f_idx}.png"
        if frame_mask.exists():
            mask_dir = proj_dir / "objects" / object_id / "masks"
            mask_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(frame_mask), str(mask_path))
        else:
            preview_masks = (
                sorted(
                    debug_dir.glob("preview_mask_*.png"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if debug_dir.exists()
                else []
            )
            if preview_masks:
                mask_dir = proj_dir / "objects" / object_id / "masks"
                mask_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(preview_masks[0]), str(mask_path))
            else:
                try:
                    s_id = obj.scene_id
                    frame_path = (
                        proj_dir / "frames" / f"scene_{s_id}" / f"frame_{f_idx:06d}.png"
                    )
                    if not frame_path.exists():
                        for scene_dir in (proj_dir / "frames").glob("scene_*"):
                            candidate = scene_dir / f"frame_{f_idx:06d}.png"
                            if candidate.exists():
                                frame_path = candidate
                                break
                    if frame_path.exists():
                        seg_svc = get_segmentation_service()
                        mask = seg_svc.preview_mask(frame_path, obj.selection, "contour")
                        mask_dir = proj_dir / "objects" / object_id / "masks"
                        mask_dir.mkdir(parents=True, exist_ok=True)
                        cv2.imwrite(str(mask_path), mask)
                except Exception:
                    pass

    if not mask_path.exists():
        raise HTTPException(
            400, "No initial mask. Preview a mask or create with mask_data."
        )

    scene_id = obj.scene_id
    frames_dir = proj_dir / "frames" / f"scene_{scene_id}"
    frame_paths = sorted(frames_dir.glob("frame_*.png"))
    if not frame_paths:
        raise HTTPException(400, f"No frames found for scene {scene_id}")

    initial_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if initial_mask is None:
        raise HTTPException(500, "Failed to load initial mask")

    sel_idx = min(obj.selection.frame_index, len(frame_paths) - 1)
    scene_frame_start = int(frame_paths[0].stem.split("_")[1])
    list_idx = sel_idx - scene_frame_start
    list_idx = max(0, min(list_idx, len(frame_paths) - 1))

    seg_svc = get_segmentation_service()
    obj_ext_svc = get_object_extraction_service()
    job_svc = get_job_service()

    def worker(progress_cb, is_cancelled):
        def seg_progress(pct, msg):
            progress_cb(pct * 0.6, msg)

        masks = seg_svc.propagate_masks(
            frame_paths, initial_mask, list_idx,
            backend="sam2", progress_cb=seg_progress,
            is_cancelled=is_cancelled,
        )

        if is_cancelled():
            return ""

        progress_cb(65, "Computing motion data")
        motion = compute_scene_motion(masks, sel_idx, list_idx)
        motion.scene_id = scene_id
        motion_smoothed = smooth_motion(motion.frames)

        from app.schemas import SceneMotion

        final_motion = SceneMotion(
            scene_id=scene_id,
            frames=motion_smoothed,
            reference_bbox=motion.reference_bbox,
        )

        pwf.update_object(project_id, object_id, motion=final_motion)

        if is_cancelled():
            return ""

        progress_cb(80, "Extracting object crops")
        obj_with_motion = pwf.get_tracked_object(project_id, object_id)
        obj_ext_svc.extract_crops(
            project_id, proj_dir, obj_with_motion, frame_paths, masks,
        )

        progress_cb(100, "Propagation complete")
        return str(proj_dir / "objects" / object_id)

    info = job_svc.create_job("propagate", worker)
    return job_response(info)


@router.get("/{project_id}/objects/{object_id}")
def get_object(project_id: str, object_id: str) -> dict:
    """Get tracked object with motion data."""
    pwf = get_project_workflow()
    try:
        obj = pwf.get_tracked_object(project_id, object_id)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, str(e)) from e
    return obj.model_dump()


@router.get("/{project_id}/objects/{object_id}/gallery")
def get_gallery(project_id: str, object_id: str) -> dict:
    """Get gallery manifest for a tracked object."""
    import json as json_mod

    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)
    manifest_path = proj_dir / "objects" / object_id / "gallery_manifest.json"

    if not manifest_path.exists():
        raise HTTPException(404, "Gallery not found. Run propagation first.")

    with open(manifest_path) as f:
        return json_mod.load(f)


@router.post("/{project_id}/objects/{object_id}/replacement")
async def upload_replacement(
    project_id: str, object_id: str, file: UploadFile,
) -> dict:
    """Upload a replacement PNG for a tracked object."""
    pwf = get_project_workflow()
    try:
        pwf.get_tracked_object(project_id, object_id)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, str(e)) from e

    proj_dir = pwf._project_dir(project_id)
    obj_dir = proj_dir / "objects" / object_id
    obj_dir.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then let service copy to final location
    import tempfile
    from pathlib import Path
    suffix = Path(file.filename or "replacement.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        rep_svc = get_replacement_service()
        rel_path = rep_svc.upload_replacement(project_id, object_id, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"status": "ok", "asset_path": rel_path}


@router.patch("/{project_id}/objects/{object_id}/replacement-settings")
def update_replacement_settings(
    project_id: str, object_id: str, body: ReplacementSettingsRequest,
) -> dict:
    """Update replacement transform settings."""
    rep_svc = get_replacement_service()
    try:
        obj = rep_svc.update_settings(
            project_id, object_id, body.replacement_config,
        )
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, str(e)) from e
    return obj.model_dump()


@router.post("/{project_id}/preview")
def render_preview(project_id: str, object_id: str = "") -> dict:
    """Render a preview video. Returns a job."""
    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)

    try:
        project = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    if not object_id and project.objects:
        object_id = project.objects[0].object_id

    try:
        obj = pwf.get_tracked_object(project_id, object_id)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, str(e)) from e

    preview_svc = get_preview_render_service()
    job_svc = get_job_service()

    def worker(progress_cb, is_cancelled):
        return preview_svc.render_preview(
            proj_dir, project, obj, progress_cb, is_cancelled,
        )

    info = job_svc.create_job("preview", worker)
    return job_response(info)


@router.post("/{project_id}/render")
def render_final(project_id: str, object_id: str = "") -> dict:
    """Render the final video. Returns a job."""
    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)

    try:
        project = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    if not object_id and project.objects:
        object_id = project.objects[0].object_id

    try:
        obj = pwf.get_tracked_object(project_id, object_id)
    except (FileNotFoundError, KeyError) as e:
        raise HTTPException(404, str(e)) from e

    final_svc = get_final_render_service()
    job_svc = get_job_service()

    def worker(progress_cb, is_cancelled):
        return final_svc.render_final(
            proj_dir, project, obj, progress_cb, is_cancelled,
        )

    info = job_svc.create_job("render", worker)
    return job_response(info)


# ── Dubbing endpoints ───────────────────────────────────────────────────────

class DubbingRequest(BaseModel):
    scene_id: int
    source_lang: str = "vi"
    target_lang: str = "en"
    whisper_model: str = "base"
    tts_voice: str = "en-US-AriaNeural"


@router.post("/{project_id}/dubbing/separate")
def separate_audio(project_id: str, scene_id: int) -> dict:
    """Separate scene audio into vocal and background tracks."""
    from app.workflow.audio_dubbing_service import AudioDubbingService  # noqa: PLC0415

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    audio_path = proj_dir / "audio" / f"scene_{scene_id:03d}.aac"
    if not audio_path.exists():
        raise HTTPException(404, f"Audio for scene {scene_id} not found")

    output_dir = proj_dir / "dubbing" / f"scene_{scene_id:03d}"
    svc = AudioDubbingService()
    vocal, bgm = svc.separate_vocals(audio_path, output_dir)

    return {
        "vocal_track": str(vocal),
        "bgm_track": str(bgm),
    }


@router.post("/{project_id}/dubbing/transcribe")
def transcribe_scene(
    project_id: str, scene_id: int,
    source_lang: str = "vi", whisper_model: str = "base",
) -> dict:
    """Transcribe scene vocal track to text."""
    from app.workflow.audio_dubbing_service import AudioDubbingService  # noqa: PLC0415

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    vocal_path = proj_dir / "dubbing" / f"scene_{scene_id:03d}" / "vocal_track.wav"
    if not vocal_path.exists():
        raise HTTPException(400, "Run audio separation first")

    svc = AudioDubbingService()
    segments = svc.transcribe(vocal_path, language=source_lang, model_size=whisper_model)
    srt_path = svc.segments_to_srt(
        segments,
        proj_dir / "dubbing" / f"scene_{scene_id:03d}" / "subtitles_original.srt",
    )

    return {"segments": segments, "srt_path": str(srt_path)}


@router.post("/{project_id}/dubbing/translate")
def translate_subtitles(
    project_id: str, scene_id: int,
    target_lang: str = "en", source_lang: str = "auto",
) -> dict:
    """Translate scene subtitles to target language."""
    from app.workflow.audio_dubbing_service import AudioDubbingService  # noqa: PLC0415

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    dubbing_dir = proj_dir / "dubbing" / f"scene_{scene_id:03d}"

    svc = AudioDubbingService()

    # Try to load existing segments
    vocal_path = dubbing_dir / "vocal_track.wav"
    if not vocal_path.exists():
        raise HTTPException(400, "Run audio separation and transcription first")

    segments = svc.transcribe(vocal_path, language=source_lang)
    translated = svc.translate_segments(segments, target_lang=target_lang)
    srt_path = svc.segments_to_srt(translated, dubbing_dir / "subtitles_translated.srt")

    return {"segments": translated, "srt_path": str(srt_path)}


@router.post("/{project_id}/dubbing/tts")
def generate_tts(
    project_id: str, scene_id: int,
    target_lang: str = "en",
    tts_voice: str = "en-US-AriaNeural",
) -> dict:
    """Generate TTS audio for translated segments."""
    from app.workflow.audio_dubbing_service import AudioDubbingService  # noqa: PLC0415

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    dubbing_dir = proj_dir / "dubbing" / f"scene_{scene_id:03d}"

    # Load translated segments
    translated_srt = dubbing_dir / "subtitles_translated.srt"
    if not translated_srt.exists():
        raise HTTPException(400, "Run translation first")

    svc = AudioDubbingService()
    # Parse SRT back to segments
    segments = svc.transcribe(dubbing_dir / "vocal_track.wav", language=target_lang)

    # Generate TTS
    tts_dir = dubbing_dir / "tts_segments"
    tts_paths = svc.tts_segments(segments, tts_dir, voice=tts_voice)

    return {"tts_count": len(tts_paths), "tts_dir": str(tts_dir)}


@router.post("/{project_id}/dubbing/remux")
def remux_dubbed_audio(
    project_id: str, scene_id: int,
    tts_voice: str = "en-US-AriaNeural",
) -> dict:
    """Remux TTS with background music into final dubbed audio."""
    from app.workflow.audio_dubbing_service import AudioDubbingService  # noqa: PLC0415

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    dubbing_dir = proj_dir / "dubbing" / f"scene_{scene_id:03d}"
    bgm_path = dubbing_dir / "bgm_sfx_track.wav"

    if not bgm_path.exists():
        raise HTTPException(400, "Run audio separation first")

    svc = AudioDubbingService()

    # Get TTS files
    tts_dir = dubbing_dir / "tts_segments"
    tts_paths = sorted(tts_dir.glob("tts_*.wav"))
    if not tts_paths:
        raise HTTPException(400, "Generate TTS first")

    # Parse timing from translated SRT
    segments = svc.transcribe(dubbing_dir / "vocal_track.wav")
    translated = svc.translate_segments(segments, target_lang="en")

    # Remux
    final_path = dubbing_dir / "dubbed_audio.wav"
    svc.remux_audio(tts_paths, translated, bgm_path, final_path)

    return {"final_audio": str(final_path)}


@router.post("/{project_id}/dubbing/full")
def full_dubbing_pipeline(project_id: str, body: DubbingRequest) -> dict:
    """Run full dubbing pipeline for a scene."""
    from app.workflow.audio_dubbing_service import AudioDubbingService  # noqa: PLC0415

    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    audio_path = proj_dir / "audio" / f"scene_{body.scene_id:03d}.aac"
    if not audio_path.exists():
        raise HTTPException(404, f"Audio for scene {body.scene_id} not found")

    output_dir = proj_dir / "dubbing" / f"scene_{body.scene_id:03d}"
    svc = AudioDubbingService()

    result = svc.dub_scene(
        audio_path=audio_path,
        output_dir=output_dir,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        whisper_model=body.whisper_model,
        tts_voice=body.tts_voice,
    )

    return result


# ── Scene management endpoints ──────────────────────────────────────────────

class SceneStatusUpdate(BaseModel):
    status: str  # "pending" | "draft" | "approved"
    notes: str = ""


@router.post("/{project_id}/scenes/chunk")
def chunk_scenes(project_id: str, threshold: float = 27.0) -> dict:
    """Re-chunk video into scenes and extract per-scene audio."""
    from app.workflow.scene_chunking_service import SceneChunkingService

    pwf = get_project_workflow()
    config = get_config()
    try:
        proj = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    video_path = Path(proj.video_metadata.file_path)
    if not video_path.exists():
        raise HTTPException(400, "Video file not found")

    proj_dir = pwf._project_dir(project_id)
    audio_dir = proj_dir / "audio"

    svc = SceneChunkingService(config)
    scene_details = svc.chunk_video(video_path, audio_dir, threshold=threshold)

    # Update project with scene details
    proj.scene_details = scene_details
    pwf._save_project(project_id, proj)

    return {
        "scene_count": len(scene_details),
        "scenes": [s.model_dump() for s in scene_details],
    }


@router.get("/{project_id}/scenes/details")
def get_scene_details(project_id: str) -> list[dict]:
    """Get scene details with status."""
    pwf = get_project_workflow()
    try:
        proj = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    return [s.model_dump() for s in proj.scene_details]


@router.patch("/{project_id}/scenes/{scene_id}/status")
def update_scene_status(
    project_id: str, scene_id: int, body: SceneStatusUpdate,
) -> dict:
    """Update a scene's status (pending/draft/approved)."""
    pwf = get_project_workflow()
    try:
        proj = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    valid_statuses = {"pending", "draft", "approved"}
    if body.status not in valid_statuses:
        raise HTTPException(400, f"Invalid status: {body.status}")

    found = False
    for sd in proj.scene_details:
        if sd.scene_id == scene_id:
            sd.status = body.status
            sd.notes = body.notes
            found = True
            break

    if not found:
        raise HTTPException(404, f"Scene {scene_id} not found")

    pwf._save_project(project_id, proj)
    return {"ok": True, "scene_id": scene_id, "status": body.status}


@router.get("/{project_id}/scenes/{scene_id}/audio")
def get_scene_audio(project_id: str, scene_id: int) -> FileResponse:
    """Serve the audio file for a scene."""
    pwf = get_project_workflow()
    try:
        pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    proj_dir = pwf._project_dir(project_id)
    audio_path = proj_dir / "audio" / f"scene_{scene_id:03d}.aac"

    if not audio_path.exists():
        raise HTTPException(404, f"Audio for scene {scene_id} not found")

    return FileResponse(str(audio_path), media_type="audio/aac")


@router.post("/{project_id}/scenes/stitch")
def stitch_scenes(project_id: str) -> dict:
    """Stitch all approved scenes into final video."""
    from app.workflow.scene_stitch_service import SceneStitchService

    pwf = get_project_workflow()
    config = get_config()
    try:
        proj = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    # Check all scenes are approved
    pending = [s for s in proj.scene_details if s.status != "approved"]
    if pending:
        raise HTTPException(
            400,
            f"{len(pending)} scenes not approved yet: "
            f"{[s.scene_id for s in pending]}",
        )

    proj_dir = pwf._project_dir(project_id)
    output_path = proj_dir / "renders" / "final_output.mp4"

    svc = SceneStitchService(config)
    result = svc.stitch_with_audio(proj_dir, proj.scene_details, output_path)

    return {"ok": True, "output_path": str(result)}


# ── Bulk character mapping ───────────────────────────────────────────────────

class BulkMappingRequest(BaseModel):
    object_id: str
    scene_ids: list[int] = Field(default_factory=list)  # empty = all scenes


@router.post("/{project_id}/objects/{object_id}/apply-bulk")
def apply_bulk_mapping(
    project_id: str, object_id: str, body: BulkMappingRequest,
) -> dict:
    """Apply an object's replacement config to multiple scenes."""
    pwf = get_project_workflow()
    try:
        proj = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Project not found") from err

    # Find the source object
    source_obj = None
    for obj in proj.objects:
        if obj.object_id == object_id:
            source_obj = obj
            break

    if source_obj is None:
        raise HTTPException(404, "Object not found")

    # Determine target scenes
    target_scenes = body.scene_ids
    if not target_scenes:
        target_scenes = [s.scene_id for s in proj.scene_details]

    # Apply replacement config to all objects in target scenes
    applied = []
    for obj in proj.objects:
        if obj.object_id == object_id:
            continue  # skip source
        if obj.scene_id in target_scenes:
            obj.replacement_config = source_obj.replacement_config
            applied.append(obj.object_id)

    pwf._save_project(project_id, proj)
    return {"applied_to": applied, "scene_ids": target_scenes}
