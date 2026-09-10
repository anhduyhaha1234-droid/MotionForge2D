"""S12-T03B stitch — seam-exact assembly with audio time-mapping.

Consumes read-only (frozen, never rewritten here):
- ``docs/contracts/s12-export.md`` (``s12-export-v1``) §5/§6 — the
  ``.partial`` suffix is frozen: a ``.partial`` path is never a completed
  output, and a completed output is never overwritten.
- ``app/services/s12_export/chunks.py`` — :class:`ChunkSpec` core ranges +
  :func:`render_window` (this module trims context overlaps, never the DB).
- ``app/services/ffmpeg_utils.py`` — ``find_ffmpeg`` / ``find_ffprobe``
  (real binaries, never synthetic media).

Assembly rule: every chunk file holds the full render window (core +
context overlaps).  Only core frames enter the final timeline — overlaps
are trimmed with frame-exact ``trim=start_frame:end_frame`` filters, so no
frame is duplicated or dropped at any seam.  Verification is frame-count
exact: stitched frames must equal the summed core coverage.

Audio rule: chunks render SILENT (video-only).  The source audio is muxed
exactly ONCE at final assembly, mapped to the stitched video timeline
(``-t <video_duration>`` — never ``-shortest``, which would cut video when
audio runs short).  Audio is never looped or cut per chunk.

Crash/cancel/disk-full safety: intermediates + candidate live under
``.partial`` scratch names; the completed path appears via one atomic
``os.replace``.  A crash leaves only ``.partial`` scratch (resumable,
never visible as completed).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe
from app.services.s12_export.chunks import ChunkSpec, render_window

__all__ = [
    "PARTIAL_SUFFIX",
    "StitchError",
    "ChunkMedia",
    "count_video_frames",
    "probe_duration_sec",
    "check_source_cfr",
    "trim_core",
    "concat_cores",
    "mux_audio_once",
    "assemble_run",
]

#: Frozen ``.partial`` suffix (contract §6 — never a completed output).
PARTIAL_SUFFIX = ".partial"


class StitchError(ValueError):
    """Fail-closed stitch/assembly error."""


@dataclass(frozen=True)
class ChunkMedia:
    """One rendered chunk file + its frozen boundary spec."""

    spec: ChunkSpec
    path: Path


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        raise StitchError(f"ffmpeg/ffprobe spawn failed: {err}") from err


def count_video_frames(path: str | Path) -> int:
    """Decode-count video frames (real ffprobe, never synthetic)."""
    completed = _run(
        [
            find_ffprobe(),
            "-hide_banner",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    if completed.returncode != 0:
        raise StitchError(
            f"ffprobe cannot read frames of {path}: "
            f"{completed.stderr.strip()[:300]}"
        )
    try:
        return int(completed.stdout.strip().splitlines()[0].strip())
    except (IndexError, ValueError) as err:
        raise StitchError(f"ffprobe gave no frame count for {path}") from err


def probe_duration_sec(path: str | Path) -> float | None:
    """Container duration in seconds, None when unmeasurable."""
    completed = _run(
        [
            find_ffprobe(),
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
        return float(payload["format"]["duration"])
    except (ValueError, TypeError, KeyError):
        return None


def check_source_cfr(path: str | Path) -> tuple[float, str, str]:
    """Pre-work CFR gate: reject VFR sources before any chunk renders.

    Returns ``(fps, r_frame_rate, avg_frame_rate)``.  Raises
    :class:`StitchError` when the video stream is unreadable or
    ``r_frame_rate != avg_frame_rate`` (variable frame rate — the T03B
    frame-exact trim math assumes constant frame rate).  Never guesses.
    """
    completed = _run(
        [
            find_ffprobe(),
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ]
    )
    if completed.returncode != 0:
        raise StitchError(
            f"ffprobe cannot read video stream of {path}: "
            f"{completed.stderr.strip()[:300]}"
        )
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        rfr = str(stream["r_frame_rate"])
        afr = str(stream["avg_frame_rate"])
    except (ValueError, TypeError, KeyError, IndexError) as err:
        raise StitchError(f"frame-rate entries unreadable for {path}") from err
    if rfr != afr:
        raise StitchError(
            f"VFR source rejected pre-work: r_frame_rate={rfr} != "
            f"avg_frame_rate={afr} (frame-exact trim needs CFR)"
        )
    try:
        num, den = afr.split("/", 1)
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError) as err:
        raise StitchError(f"unparseable avg_frame_rate {afr!r}") from err
    if fps <= 0:
        raise StitchError(f"non-positive fps {afr!r}")
    return fps, rfr, afr


def trim_core(
    chunk_path: str | Path,
    spec: ChunkSpec,
    *,
    frame_count: int,
    fps: float,
    dest: str | Path,
    encoder: str = "libx264",
) -> Path:
    """Trim one render window down to its core-only segment (frame-exact).

    ``chunk_path`` holds frames ``[rs, re]`` (:func:`render_window`); the
    core starts at offset ``spec.core_start_frame - rs`` inside the file.
    Only the ``core_frame_count`` frames enter the timeline.

    F03 — the trim re-encodes with the *selected supported* encoder (from
    the frozen profile), never a hardcoded ``libx264``: HEVC chunks stay
    HEVC through the final assembly.
    """
    src = Path(chunk_path)
    if not src.is_file():
        raise StitchError(f"chunk file missing: {src}")
    if src.name.endswith(PARTIAL_SUFFIX):
        raise StitchError(f"refusing .partial chunk as stitch input: {src.name}")
    if fps <= 0:
        raise StitchError("fps must be > 0")
    if not encoder:
        raise StitchError("encoder must be non-empty")
    rs, _ = render_window(spec, frame_count)
    offset = spec.core_start_frame - rs
    if offset < 0:
        raise StitchError("chunk render window is stale (negative core offset)")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    completed = _run(
        [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"trim=start_frame={offset}:end_frame={offset + spec.core_frame_count},"
            "setpts=PTS-STARTPTS",
            "-an",
            "-c:v",
            encoder,
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ]
    )
    if completed.returncode != 0:
        raise StitchError(
            f"core trim failed for chunk {spec.chunk_index}: "
            f"{completed.stderr.strip()[-300:]}"
        )
    got = count_video_frames(dest)
    if got != spec.core_frame_count:
        raise StitchError(
            f"trimmed core {spec.chunk_index} has {got} frames, expected "
            f"{spec.core_frame_count} (tampered/short chunk?)"
        )
    return dest


def concat_cores(
    cores: list[str | Path], *, dest: str | Path, fps: float
) -> Path:
    """Concat core-only segments in order (stream copy — no re-encode drift)."""
    if not cores:
        raise StitchError("no core segments to concat")
    if fps <= 0:
        raise StitchError("fps must be > 0")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for core in cores:
        if not Path(core).is_file():
            raise StitchError(f"core segment missing: {core}")
    list_file = dest.parent / "_s12_t03b_concat.txt"
    with open(list_file, "w", encoding="utf-8") as handle:
        for core in cores:
            handle.write(f"file '{Path(core).as_posix()}'\n")
    try:
        completed = _run(
            [
                find_ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(dest),
            ]
        )
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass
    if completed.returncode != 0:
        raise StitchError(
            f"concat failed ({len(cores)} cores): "
            f"{completed.stderr.strip()[-300:]}"
        )
    return dest


def mux_audio_once(
    video_path: str | Path,
    audio_path: str | Path | None,
    *,
    dest: str | Path,
    total_frames: int,
    fps: float,
) -> Path:
    """Mux source audio ONCE onto the stitched timeline (no per-chunk audio).

    The output duration is pinned to the video timeline
    (``-t <total_frames / fps>``) so a short audio track can never cut video
    frames and audio is never looped to fill — it maps 1:1 onto the timeline
    start.  ``audio_path=None`` yields a silent completed output.
    """
    src = Path(video_path)
    if not src.is_file():
        raise StitchError(f"stitched video missing: {src}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = total_frames / fps
    if audio_path is None:
        completed = _run(
            [
                find_ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(dest),
            ]
        )
        if completed.returncode != 0:
            raise StitchError(
                f"silent finalize failed: {completed.stderr.strip()[-300:]}"
            )
        return dest
    audio = Path(audio_path)
    if not audio.is_file():
        raise StitchError(f"audio source missing: {audio}")
    audio_dur = probe_duration_sec(audio)
    if audio_dur is not None and audio_dur + 0.5 < duration:
        raise StitchError(
            f"audio source too short: {audio_dur:.3f}s < video {duration:.3f}s "
            "(refusing to loop/pad per-chunk audio)"
        )
    completed = _run(
        [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-t",
            f"{duration:.6f}",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    if completed.returncode != 0:
        raise StitchError(
            f"audio mux failed: {completed.stderr.strip()[-300:]}"
        )
    return dest


def assemble_run(
    chunks: list[ChunkMedia],
    *,
    frame_count: int,
    fps: float,
    output_path: str | Path,
    audio_source: str | Path | None,
    scratch_dir: str | Path,
    encoder: str = "libx264",
) -> Path:
    """Full stitch pipeline: trim cores → concat → mux audio → atomic finalize.

    Writes the candidate to ``<output>.partial`` scratch, verifies the exact
    stitched frame count, then atomically replaces the completed path.  An
    existing completed output is NEVER overwritten (contract §6).  Crash-safe:
    only ``.partial`` scratch remains on failure.

    F03 — ``encoder`` is the profile-selected supported codec; the trim
    keeps it (never hardcoded libx264) so the final candidate codec matches
    the selected profile.  F07 — the output produced here is a PRIVATE
    candidate path the caller owns; publication is never part of assembly.
    """
    output = Path(output_path)
    if output.name.endswith(PARTIAL_SUFFIX):
        raise StitchError("completed output must not carry the .partial suffix")
    if output.is_file():
        raise StitchError(
            f"completed output exists — refusing overwrite: {output}"
        )
    if fps <= 0:
        raise StitchError("fps must be > 0")
    if frame_count < 1:
        raise StitchError("frame_count must be >= 1")
    if not encoder:
        raise StitchError("encoder must be non-empty")
    ordered = sorted(chunks, key=lambda item: item.spec.order_index)
    if not ordered:
        raise StitchError("no chunk media to assemble")
    expected = sum(item.spec.core_frame_count for item in ordered)
    if expected != frame_count:
        raise StitchError(
            f"chunk cores cover {expected} frames, run expects {frame_count}"
        )
    scratch = Path(scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    # Candidate keeps a muxable .mp4 name during encode (ffmpeg sniffs the
    # muxer from the extension); the completed path appears via ONE atomic
    # os.replace.  Crash-safe: only scratch remains on failure.
    candidate = scratch / "candidate.tmp-finalize.mp4"

    try:
        cores: list[Path] = []
        for item in ordered:
            cores.append(
                trim_core(
                    item.path,
                    item.spec,
                    frame_count=frame_count,
                    fps=fps,
                    dest=scratch / f"core_{item.spec.order_index:04d}.mp4",
                    encoder=encoder,
                )
            )
        stitched = scratch / "stitched_video.mp4"
        concat_cores(cores, dest=stitched, fps=fps)
        got_video = count_video_frames(stitched)
        if got_video != frame_count:
            raise StitchError(
                f"stitched video has {got_video} frames, expected {frame_count}"
            )
        mux_audio_once(
            stitched, audio_source, dest=candidate, total_frames=frame_count, fps=fps
        )
        got_final = count_video_frames(candidate)
        if got_final != frame_count:
            raise StitchError(
                f"final candidate has {got_final} frames, expected {frame_count}"
            )
        _verify_codec(candidate, encoder, "final candidate")
        os.replace(candidate, output)
        return output
    except BaseException:
        _cleanup_assembly_scratch(scratch)
        raise


def _cleanup_assembly_scratch(scratch: Path) -> None:
    """Remove only assembly-private files after a failed stitch."""
    names = {
        "candidate.tmp-finalize.mp4",
        "stitched_video.mp4",
        "_s12_t03b_concat.txt",
    }
    try:
        children = list(scratch.iterdir())
    except OSError:
        return
    for child in children:
        if child.is_symlink() or not child.is_file():
            continue
        name = child.name.lower()
        if (
            name in names
            or (name.startswith("core_") and name.endswith(".mp4"))
            or name.endswith(".partial")
        ):
            try:
                child.unlink()
            except OSError:
                pass


def _verify_codec(path: str | Path, encoder: str, label: str) -> None:
    """Assert the file's actual video codec matches the selected encoder."""
    expected_codec = "hevc" if "265" in encoder.lower() else "h264"
    completed = _run(
        [
            find_ffprobe(),
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    if completed.returncode != 0:
        raise StitchError(f"{label} codec probe failed: {path}")
    actual = (completed.stdout or "").strip().splitlines()
    if not actual or actual[0].strip() != expected_codec:
        raise StitchError(
            f"{label} codec {actual[0] if actual else '?'} != selected "
            f"{expected_codec} ({encoder}) — substitution rejected"
        )
