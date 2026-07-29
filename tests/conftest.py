"""Pytest configuration and fixtures."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure FFmpeg is findable on Windows (WinGet installs to non-PATH location)
_ffmpeg = shutil.which("ffmpeg")
if _ffmpeg is None:
    _winget_links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    if _winget_links.is_dir():
        os.environ["PATH"] = str(_winget_links) + os.pathsep + os.environ.get("PATH", "")


@pytest.fixture
def sample_project_data() -> dict:
    """Minimal valid project data for testing."""
    return {
        "version": "1.0.0",
        "name": "Test Project",
        "source_video": "/tmp/test.mp4",
        "video_metadata": {
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "duration_seconds": 10.0,
            "total_frames": 300,
            "codec": "h264",
            "has_audio": True,
            "audio_codec": "aac",
            "file_size_bytes": 5000000,
            "file_path": "/tmp/test.mp4",
        },
        "scenes": [
            {
                "scene_id": 0,
                "start_frame": 0,
                "end_frame": 149,
                "start_time_sec": 0.0,
                "end_time_sec": 5.0,
                "duration_sec": 5.0,
                "frame_count": 150,
            },
            {
                "scene_id": 1,
                "start_frame": 150,
                "end_frame": 299,
                "start_time_sec": 5.0,
                "end_time_sec": 10.0,
                "duration_sec": 5.0,
                "frame_count": 150,
            },
        ],
        "objects": [],
    }


@pytest.fixture
def sample_frame() -> np.ndarray[Any, Any]:
    """A simple 100x100 BGR test frame with a colored rectangle."""
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:, :] = (30, 30, 30)  # Dark gray background
    cv2.rectangle(frame, (20, 20), (80, 80), (0, 0, 255), -1)  # Red square
    return frame


@pytest.fixture
def sample_mask() -> np.ndarray[Any, Any]:
    """A 100x100 binary mask matching the red square in sample_frame."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:80, 20:80] = 255
    return mask
