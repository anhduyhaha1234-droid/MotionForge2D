"""FFmpeg binary discovery + build-configuration probe (S09-T00-I02).

Fail-closed: every function returns a probe result; ``available=False`` plus
the exact error is the contract — callers must raise BackendBinaryMissingError
rather than guessing.  No heavy imports (stdlib subprocess only).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["FfmpegProbe", "probe_ffmpeg"]

_WINGET_LINKS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
)


def _candidate_dirs() -> tuple[Path, ...]:
    dirs = [_WINGET_LINKS] if str(_WINGET_LINKS) else []
    from_shutil = shutil.which("ffmpeg")
    if from_shutil:
        parent = Path(from_shutil).parent
        return (parent, *dirs)
    return tuple(dirs)


@dataclass(frozen=True)
class FfmpegProbe:
    """Result of locating and fingerprinting the FFmpeg binary."""

    available: bool
    ffmpeg_path: str | None = None
    version_line: str | None = None
    configuration_flags: tuple[str, ...] = field(default_factory=tuple)
    is_gpl_build: bool = False
    is_lgpl_build: bool = False
    license_id: str | None = None
    error: str | None = None


def _license_from_flags(flags: tuple[str, ...]) -> str:
    if "--enable-nonfree" in flags:
        # gyan "full" builds do not ship nonfree; if present anyway the build
        # cannot be redistributed — treat as GPL-family local use.
        return "ffmpeg-gpl-build"
    if "--enable-gpl" in flags:
        return "ffmpeg-gpl-build"
    return "ffmpeg-lgpl"


def probe_ffmpeg(timeout_s: float = 20.0) -> FfmpegProbe:
    """Locate FFmpeg and read its version + configuration header."""
    exe: str | None = shutil.which("ffmpeg")
    if exe is None:
        for directory in _candidate_dirs():
            candidate = directory / "ffmpeg.exe"
            if candidate.is_file():
                exe = str(candidate)
                break
    if exe is None:
        return FfmpegProbe(
            available=False,
            error="ffmpeg not found on PATH nor in WinGet Links",
        )
    try:
        completed = subprocess.run(
            [exe, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return FfmpegProbe(available=False, ffmpeg_path=exe, error=str(err))
    if completed.returncode != 0:
        return FfmpegProbe(
            available=False,
            ffmpeg_path=exe,
            error=f"ffmpeg -version exited {completed.returncode}",
        )
    lines = completed.stdout.splitlines()
    version_line = lines[0].strip() if lines else None
    flags: tuple[str, ...] = ()
    for line in lines:
        if line.startswith("configuration:"):
            flags = tuple(line.split(":", 1)[1].split())
            break
    is_gpl = "--enable-gpl" in flags
    # An --enable-gpl build is GPL-family even if some LGPL components remain;
    # a pure LGPL build simply lacks the flag.
    is_lgpl = (not is_gpl) and ("--disable-gpl" not in flags)
    return FfmpegProbe(
        available=True,
        ffmpeg_path=exe,
        version_line=version_line,
        configuration_flags=flags,
        is_gpl_build=is_gpl,
        is_lgpl_build=is_lgpl,
        license_id=_license_from_flags(flags),
    )
