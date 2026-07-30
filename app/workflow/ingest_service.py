"""Ingest service — probe video, detect scenes, extract frames."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

from app.config import AppConfig
from app.services.frame_extraction import extract_frames
from app.services.scene_detection import detect_scenes
from app.services.video_probe import extract_audio, probe_video
from app.workflow.project_workflow import ProjectWorkflowService


class IngestService:
    """Orchestrates video ingest: probe + scene detect + frame extract."""

    def __init__(self, config: AppConfig, project_wf: ProjectWorkflowService) -> None:
        self._config = config
        self._project_wf = project_wf

    def ingest(
        self,
        project_id: str,
        progress_cb: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Run full ingest pipeline for a project.

        Args:
            project_id: Target project ID.
            progress_cb: Optional callback(progress_pct, message).
            is_cancelled: Optional callback returning True if cancelled.

        Returns:
            Project directory path on success.

        Raises:
            FileNotFoundError: If video file not found.
        """
        proj_dir = self._project_wf._project_dir(project_id)
        project = self._project_wf.get_project(project_id)
        video_path = Path(project.source_video)

        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        def _pct(pct: float, msg: str) -> None:
            if progress_cb:
                progress_cb(pct, msg)

        def _cancelled() -> bool:
            return is_cancelled() if is_cancelled else False

        # Step 1: Probe video
        _pct(10, "Probing video metadata")
        metadata = probe_video(video_path)

        svc = self._project_wf.get_project_service(project_id)
        svc.load()
        svc.set_video_metadata(metadata)

        if _cancelled():
            return str(proj_dir)

        # Step 2: Detect scenes
        _pct(30, "Detecting scenes")
        scenes = detect_scenes(video_path)
        svc.set_scenes(scenes)

        if _cancelled():
            return str(proj_dir)

        # Step 3: Extract frames
        total_scenes = len(scenes)
        for i, scene in enumerate(scenes):
            if _cancelled():
                return str(proj_dir)
            pct = 50 + 40 * (i / max(total_scenes, 1))
            _pct(pct, f"Extracting frames for scene {i}")
            frames_dir = proj_dir / "frames" / f"scene_{scene.scene_id}"
            extract_frames(video_path, frames_dir, scene)

        # Step 4: Extract audio (if present)
        if metadata.has_audio:
            _pct(90, "Extracting audio")
            audio_dir = proj_dir / "audio"
            with contextlib.suppress(Exception):
                extract_audio(video_path, audio_dir / "original_audio.aac")

        _pct(100, "Ingest complete")
        return str(proj_dir)
