"""MF-V1-BENCH sheet.py - contact sheets, crop strips, 1x / 0.5x review copies.

Playback deliverables for the human reviewer. CPU only, deterministic ffmpeg filters.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def contact_sheet(src, out, fps=4, tile="4x4", scale=320, t0=None, duration=None) -> Path:
    out = Path(out)
    C.ensure(out.parent)
    vf = "fps=%s,scale=%d:-2,tile=%s" % (fps, scale, tile)
    argv = ["ffmpeg", "-y", "-v", "error"]
    if t0 is not None:
        argv += ["-ss", str(t0)]
    argv += ["-i", str(src)]
    if duration is not None:
        argv += ["-t", str(duration)]
    argv += ["-vf", vf, "-frames:v", "1", str(out)]
    C.run(argv, label="contact sheet %s" % out.name)
    return out


def crop_strip(src, out, crop, scale=None, t0=None, duration=None, fps=6, tile="6x2") -> Path:
    out = Path(out)
    C.ensure(out.parent)
    vf = "crop=%s" % crop
    if scale:
        vf += ",scale=%s" % scale
    vf += ",fps=%s,tile=%s" % (fps, tile)
    argv = ["ffmpeg", "-y", "-v", "error"]
    if t0 is not None:
        argv += ["-ss", str(t0)]
    argv += ["-i", str(src)]
    if duration is not None:
        argv += ["-t", str(duration)]
    argv += ["-vf", vf, "-frames:v", "1", str(out)]
    C.run(argv, label="crop strip %s" % out.name)
    return out


def review_copy(src, out, speed=1.0, t0=None, duration=None) -> Path:
    """Full-length review copy. speed 1.0 = as-is; 0.5 = half-speed playback."""
    out = Path(out)
    C.ensure(out.parent)
    argv = ["ffmpeg", "-y", "-v", "error"]
    if t0 is not None:
        argv += ["-ss", str(t0)]
    argv += ["-i", str(src)]
    if duration is not None:
        argv += ["-t", str(duration)]
    vf = "setpts=%.4f*PTS" % (1.0 / speed)
    argv += ["-vf", vf]
    if speed == 0.5:
        argv += ["-af", "atempo=0.5"]
    else:
        argv += ["-af", "anull"]
    argv += [*VENC, "-c:a", "aac", "-b:a", "160k", str(out)]
    C.run(argv, label="review copy %s" % out.name)
    return out
