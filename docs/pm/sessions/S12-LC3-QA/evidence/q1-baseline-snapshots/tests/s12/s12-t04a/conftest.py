"""S12-T04A isolated fixtures — real-media builders, no shared-conftest touch.

Every file is encoded with real ffmpeg into an isolated root; mutation
tests (truncate/corrupt/partial) always copy into their own ``tmp_path``
first so shared session media stays pristine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_FPS = 10
_DURATION = 2.0
_FRAME_COUNT = int(_FPS * _DURATION)


def _find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    links = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Links"
        / "ffmpeg.exe"
    )
    if links.is_file():
        return str(links)
    raise FileNotFoundError("ffmpeg not found (needed to build S12-T04A media)")


def build_media(
    dest: Path,
    *,
    width: int,
    height: int,
    codec: str = "h264",
    fps: int = _FPS,
    duration: float = _DURATION,
    audio: bool = False,
) -> Path:
    """Encode a real testsrc (+ optional sine audio) clip at ``dest``."""
    if codec == "h264":
        vcodec = ["-c:v", "libx264", "-preset", "ultrafast"]
    elif codec == "hevc":
        vcodec = ["-c:v", "libx265", "-preset", "ultrafast"]
    else:  # pragma: no cover - defensive, tests only use h264/hevc
        raise ValueError(f"unsupported test codec: {codec}")
    cmd = [
        _find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += [*vcodec, "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(dest))
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, f"ffmpeg failed: {completed.stderr[:500]}"
    assert dest.is_file()
    return dest


@pytest.fixture(scope="session")
def media_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("s12t04a")


@pytest.fixture(scope="session")
def good_4k(media_root: Path) -> Path:
    """Silent 3840x2160 h264, 10fps x 2s = 20 frames."""
    return build_media(media_root / "good_4k.mp4", width=3840, height=2160)


@pytest.fixture(scope="session")
def good_4k_audio(media_root: Path) -> Path:
    """3840x2160 h264 + aac audio, 10fps x 2s = 20 frames."""
    return build_media(
        media_root / "good_4k_audio.mp4", width=3840, height=2160, audio=True
    )


@pytest.fixture(scope="session")
def small_1080(media_root: Path) -> Path:
    """1920x1080 h264 (wrong-dimension negative control)."""
    return build_media(media_root / "small_1080.mp4", width=1920, height=1080)


@pytest.fixture(scope="session")
def tiny_hevc(media_root: Path) -> Path:
    """Tiny hevc clip (codec-branch control without 4K HEVC cost)."""
    return build_media(media_root / "tiny_hevc.mp4", width=320, height=180, codec="hevc")
