"""Shared utilities for FFmpeg/ffprobe binary discovery."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _find_binary(name: str) -> str:
    """Find a binary by name, checking PATH and common install locations.

    Args:
        name: Binary name (e.g., "ffmpeg" or "ffprobe").

    Returns:
        Full path to the binary.

    Raises:
        FileNotFoundError: If binary not found.
    """
    # 1. Check PATH
    found = shutil.which(name)
    if found:
        return found

    # 2. Check WinGet Links (common Windows install path)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_links = Path(local_app_data) / "Microsoft" / "WinGet" / "Links"
        candidate = winget_links / f"{name}.exe"
        if candidate.exists():
            # Add to PATH for subprocess children
            links_str = str(winget_links)
            if links_str not in os.environ.get("PATH", ""):
                os.environ["PATH"] = links_str + os.pathsep + os.environ.get("PATH", "")
            return str(candidate)

    # 3. Check common Windows paths
    for candidate in [
        rf"C:\ffmpeg\bin\{name}.exe",
        rf"C:\Program Files\FFmpeg\bin\{name}.exe",
    ]:
        if Path(candidate).exists():
            return candidate

    raise FileNotFoundError(
        f"{name} not found. Install FFmpeg and ensure it's on PATH, "
        "or install via: winget install Gyan.FFmpeg"
    )


def find_ffmpeg() -> str:
    """Locate ffmpeg binary."""
    return _find_binary("ffmpeg")


def find_ffprobe() -> str:
    """Locate ffprobe binary."""
    return _find_binary("ffprobe")
