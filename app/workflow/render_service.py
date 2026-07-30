"""Render service — preview and final render orchestration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from app.schemas import ProjectData, TrackedObject
from app.services.compositing import composite_object, load_replacement_image
from app.services.render import render_video
from app.services.video_probe import probe_video


class PreviewRenderService:
    """Renders a quick preview (lower quality, fewer frames)."""

    def render_preview(
        self,
        project_dir: Path,
        project: ProjectData,
        obj: TrackedObject,
        progress_cb: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Render a preview video for a single object's scene."""
        return self._do_render(
            project_dir, project, obj, preview=True,
            progress_cb=progress_cb, is_cancelled=is_cancelled,
        )

    def _do_render(
        self,
        project_dir: Path,
        project: ProjectData,
        obj: TrackedObject,
        preview: bool,
        progress_cb: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Common render logic for preview and final."""
        def _pct(pct: float, msg: str) -> None:
            if progress_cb:
                progress_cb(pct, msg)

        def _cancelled() -> bool:
            return is_cancelled() if is_cancelled else False

        motion = obj.motion
        if motion is None or not motion.frames:
            raise ValueError("Object has no motion data")

        scene_id = obj.scene_id
        frames_dir = project_dir / "frames" / f"scene_{scene_id}"
        frame_paths = sorted(frames_dir.glob("frame_*.png"))
        if not frame_paths:
            raise FileNotFoundError(f"No frames found in {frames_dir}")

        if preview and len(frame_paths) > 30:
            step = len(frame_paths) // 30
            frame_paths = frame_paths[::step]

        _pct(10, "Loading frames and masks")

        replacement_img = None
        if obj.replacement_image:
            rep_path = project_dir / obj.replacement_image
            if rep_path.exists():
                ref_bbox = motion.reference_bbox
                if ref_bbox:
                    rep_w = max(1, int(ref_bbox.width))
                    rep_h = max(1, int(ref_bbox.height))
                else:
                    rep_w, rep_h = 100, 100
                replacement_img = load_replacement_image(rep_path, rep_w, rep_h)

        _pct(20, "Compositing frames")

        renders_dir = project_dir / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)

        suffix = "preview" if preview else "final"
        composited_dir = renders_dir / f"scene_{scene_id}_{suffix}"
        composited_dir.mkdir(parents=True, exist_ok=True)

        for i, fp in enumerate(frame_paths):
            if _cancelled():
                return str(composited_dir)

            frame = cv2.imread(str(fp))
            if frame is None:
                continue

            frame_idx = i
            fm = (
                motion.frames[frame_idx]
                if frame_idx < len(motion.frames)
                else None
            )

            if (
                replacement_img is not None
                and fm is not None
                and fm.visibility
            ):
                h, w = frame.shape[:2]
                mask = np.zeros((h, w), dtype=np.uint8)
                bw = int(fm.bbox.width)
                bh = int(fm.bbox.height)
                if bw > 0 and bh > 0:
                    bx = int(fm.bbox.x)
                    by = int(fm.bbox.y)
                    mask[by:by + bh, bx:bx + bw] = 255
                result = composite_object(frame, mask, replacement_img, fm)
            else:
                result = frame

            out_path = composited_dir / f"frame_{i:06d}.png"
            cv2.imwrite(str(out_path), result)

            pct = 20 + 60 * (i / len(frame_paths))
            _pct(pct, f"Compositing frame {i}/{len(frame_paths)}")

        _pct(80, "Rendering video")

        output_video = renders_dir / f"scene_{scene_id}_{suffix}.mp4"

        metadata = project.video_metadata or probe_video(project.source_video)

        audio_path = project_dir / "audio" / "original_audio.aac"
        render_video(
            composited_dir, output_video, metadata,
            audio_path if audio_path.exists() else None,
        )

        _pct(100, "Render complete")
        return str(output_video)


class FinalRenderService:
    """Renders the final high-quality output."""

    def render_final(
        self,
        project_dir: Path,
        project: ProjectData,
        obj: TrackedObject,
        progress_cb: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Render the final video for a tracked object."""
        svc = PreviewRenderService()
        return svc._do_render(
            project_dir, project, obj, preview=False,
            progress_cb=progress_cb, is_cancelled=is_cancelled,
        )
