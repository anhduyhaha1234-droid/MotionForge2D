"""Scene chunking — detect scenes and extract per-scene audio."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import AppConfig
from app.schemas import SceneDetail, SceneStatus
from app.services.scene_detection import detect_scenes


class SceneChunkingService:
    """Detect scenes and extract synced audio per scene."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def chunk_video(
        self,
        video_path: Path,
        output_dir: Path,
        threshold: float = 27.0,
    ) -> list[SceneDetail]:
        """Detect scenes and extract audio for each scene.

        Args:
            video_path: Path to input video.
            output_dir: Directory to write scene audio files.
            threshold: Scene detection sensitivity.

        Returns:
            List of SceneDetail with status=PENDING and audio_path set.
        """
        scenes = detect_scenes(video_path, threshold=threshold)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Check if video has audio
        has_audio = self._check_audio(video_path)

        scene_details: list[SceneDetail] = []
        for scene in scenes:
            audio_path = ""
            if has_audio:
                audio_filename = f"scene_{scene.scene_id:03d}.aac"
                audio_file = output_dir / audio_filename
                self._extract_audio(
                    video_path, audio_file,
                    scene.start_time_sec, scene.end_time_sec,
                )
                audio_path = str(audio_file.relative_to(output_dir.parent.parent))

            scene_details.append(SceneDetail(
                scene_id=scene.scene_id,
                start_frame=scene.start_frame,
                end_frame=scene.end_frame,
                start_time_sec=scene.start_time_sec,
                end_time_sec=scene.end_time_sec,
                duration_sec=scene.duration_sec,
                frame_count=scene.frame_count,
                status=SceneStatus.PENDING,
                audio_path=audio_path,
            ))

        return scene_details

    def _extract_audio(
        self,
        video_path: Path,
        output_path: Path,
        start_sec: float,
        end_sec: float,
    ) -> None:
        """Extract audio segment using FFmpeg."""
        ffmpeg = self._find_ffmpeg()
        duration = end_sec - start_sec
        cmd = [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-ss", str(start_sec),
            "-t", str(duration),
            "-vn",           # no video
            "-acodec", "copy",  # copy audio codec (no re-encode)
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    def _check_audio(self, video_path: Path) -> bool:
        """Check if video has audio stream."""
        ffprobe = self._find_ffprobe()
        cmd = [
            ffprobe, "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "audio" in result.stdout

    def _find_ffmpeg(self) -> str:
        """Find FFmpeg binary."""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        # Try Windows path
        win_path = Path(r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe")
        if win_path.exists():
            return str(win_path)
        raise FileNotFoundError("ffmpeg not found")

    def _find_ffprobe(self) -> str:
        """Find FFprobe binary."""
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            return ffprobe
        win_path = Path(r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe")
        if win_path.exists():
            return str(win_path)
        raise FileNotFoundError("ffprobe not found")
