"""Independent S12 export output validator (S12-T04A).

Pure output validator over the frozen ``s12-export-v1`` contract
(``docs/contracts/s12-export.md`` §5 ``ValidationContract``, T01 owner).
It consumes the frozen manifest contract read-only — it needs no runner
code, no DB and no publication side effect.

Pipeline (probes follow ``ValidationContract.required_probes`` order):

1. ``completeness`` — file exists, no ``.partial`` suffix, decodes.
2. ``resolution`` — raster WxH vs expected (master 3840x2160).
3. ``codec`` — video codec vs expected (h264/hevc).
4. ``streams`` — stream inventory (video present, audio policy).
5. ``frame_count`` — decoded frame count vs expected (when measurable).
6. ``frame_order`` — presentation-timestamp monotonicity (B-frame safe).
7. ``timebase`` — stream time_base/fps present and sane.
8. ``duration`` — container duration vs expected (A-V policy).
9. ``av_policy`` — audio presence/absence vs expected policy.
10. ``provenance`` — sha256 identity vs manifest hash (never file size).

Verdict vocabulary (frozen): ``PASS | FAIL | NOT_MEASURED``.
Insufficient evidence → FAIL or NOT_MEASURED, never a fake PASS.

Source-locked mode (C2 F07/C12/C19/C28): when ``ValidationExpectation``
is built with ``source_locked=True`` plus a :class:`SourceReference`
(independently supplied immutable evidence from the server-owned Full
Apply authority / approved output), the candidate is compared against
that reference — monotonic PTS, codec keyframes, audio presence and
self-hashing the candidate are NOT source-truth proof on their own.
Missing reference authority → FAIL/NOT_MEASURED, never a fake PASS.

The validator never publishes and never touches the DB: :func:`validate`
is a pure function returning a :class:`ValidationVerdict`.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from fractions import Fraction
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe

__all__ = [
    "MASTER_WIDTH",
    "MASTER_HEIGHT",
    "PARTIAL_SUFFIX",
    "REQUIRED_PROBES",
    "VERDICTS",
    "ProbeVerdict",
    "ValidationExpectation",
    "ValidationVerdict",
    "SourceReference",
    "AudioReference",
    "CutPoint",
    "sha256_file",
    "probe_frame_digests",
    "probe_audio_digest",
    "probe_audio_content",
    "probe_frame_psnr",
    "validate",
]

#: Frozen master raster (contract §4/§5).
MASTER_WIDTH = 3840
MASTER_HEIGHT = 2160

#: Frozen ``.partial`` suffix — never a completed output (contract §6).
PARTIAL_SUFFIX = ".partial"

#: Probe order consumed from ``ValidationContract.required_probes``.
REQUIRED_PROBES: tuple[str, ...] = (
    "resolution",
    "codec",
    "streams",
    "frame_count",
    "frame_order",
    "timebase",
    "duration",
    "av_policy",
    "provenance",
    "completeness",
)

#: Frozen verdict vocabulary.
VERDICTS: tuple[str, ...] = ("PASS", "FAIL", "NOT_MEASURED")

Verdict = Literal["PASS", "FAIL", "NOT_MEASURED"]

_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ProbeVerdict:
    """One named probe outcome inside the validation verdict."""

    name: str
    verdict: Verdict
    detail: str = ""


@dataclass(frozen=True)
class ValidationExpectation:
    """Expected output facts the validator compares the media against.

    All expectations come from the frozen manifest/run contract (T01/T03A
    authorities). ``None`` means "not asserted by the manifest" — the
    corresponding probe then reports NOT_MEASURED instead of guessing.
    """

    width: int = MASTER_WIDTH
    height: int = MASTER_HEIGHT
    codec: str = "h264"
    # Audio policy: "required" (must carry audio), "absent" (must be
    # silent), "either" (manifest does not constrain audio).
    audio_policy: str = "either"
    expected_frame_count: int | None = None
    expected_duration_sec: float | None = None
    # Duration tolerance as a relative fraction (2% default).
    duration_tolerance: float = 0.02
    # Provenance identity: sha256 of the completed output, from the
    # manifest. ``None`` → provenance probe is NOT_MEASURED.
    expected_sha256: str | None = None
    # CFR control: manifest-asserted fps. ``None`` → unconstrained.
    expected_fps: float | None = None
    # VFR inputs are rejected pre-work (C12): any r_frame_rate vs
    # avg_frame_rate mismatch fails ``timebase``. Disable only when the
    # manifest explicitly allows variable frame rate (never for masters).
    reject_vfr: bool = True
    # Source-locked seam cuts in seconds (C12): each cut must land on a
    # keyframe within tolerance. Empty → unconstrained.
    expected_cuts: tuple[float, ...] = ()
    # Cut match tolerance in frame durations (rational, CFR-derived).
    cut_tolerance_frames: float = 1.5
    # C2 source-locked mode (F07): when True the validator compares the
    # candidate against ``source_reference`` — independently supplied
    # immutable evidence — instead of trusting candidate self-evidence
    # (monotonic PTS/keyframes/audio presence/self-hash). Missing
    # reference authority fails closed.
    source_locked: bool = False
    source_reference: SourceReference | None = None
    # C2 interface-delta (T03C findfix 47dae37): re-encoded export output
    # is never byte-identical, so source-locked frame comparison supports
    # a measured tolerance mode:
    #   "exact" (default, fail-closed) — decoded frame digests must match
    #     the reference exactly (tamper-proof, but rejects any lossy
    #     re-encode, including legitimate profile upscale/encode).
    #   "psnr" — decoded frames at the approved raster are compared with
    #     PSNR per frame; every frame must be >= ``frame_psnr_min_db``.
    #     The threshold is the CONSUMER's documented per-profile value
    #     (e.g. master-4k >= 30dB); missing threshold or missing
    #     reference_path fails closed. Reorder/content drift drops PSNR
    #     far below any sane encode threshold, so tamper still FAILs.
    frame_match_mode: str = "exact"
    frame_psnr_min_db: float | None = None
    # Server-owned job scratch for bounded statistics only; decoded raw media
    # is never materialized here.
    scratch_dir: str | Path | None = None
    cancel_flag: str | Path | None = None
    validation_timeout_sec: float = 600.0


@dataclass(frozen=True)
class CutPoint:
    """One immutable source cut: frame index + exact rational seconds.

    ``frame_index`` is the 0-based presentation-order frame where the cut
    begins (the first frame of the new seam segment); ``pts_num/pts_den``
    is that frame's exact rational timestamp in seconds (source timebase).
    """

    frame_index: int
    pts_num: int
    pts_den: int


@dataclass(frozen=True)
class AudioReference:
    """Independently supplied approved-audio evidence (C28).

    ``mode`` is explicit about how the candidate may carry the audio:
    - ``remux``: byte-exact copy of the approved audio — decoded PCM
      content must match ``digest`` (mapping + content proof).
    - ``transcode``: audio may be re-encoded, but independent bounded
      source-referenced content, mapping, and A/V start/end drift are asserted.
    - ``absent``: candidate must carry no audio stream.
    ``digest`` is the sha256 of the decoded s16le PCM of the approved
    audio track (see :func:`probe_audio_digest`); required for ``remux``.
    """

    mode: Literal["remux", "transcode", "absent"]
    digest: str | None = None
    stream_index: int = 0
    # Transcode mode still requires independent source-referenced proof.
    reference_path: str | None = None
    channels: int | None = None
    sample_rate: int | None = None


@dataclass(frozen=True)
class SourceReference:
    """Immutable reference evidence for source-locked validation (C2 F07).

    Every field is supplied independently (server-owned Full Apply
    authority / approved output contract), never derived from the
    candidate being validated. Absence of the authority fails closed.
    """

    artifact_sha256: str = ""
    frame_count: int | None = None
    fps_num: int = 0
    fps_den: int = 0
    # Per-frame decoded-content digests (presentation order). When
    # non-empty it must have exactly ``frame_count`` entries and proves
    # content order — equal-length reordered content FAILs.
    frame_digests: tuple[str, ...] = ()
    # Immutable server-owned approved-artifact media path used ONLY for
    # measured PSNR comparison (``frame_match_mode="psnr"``). Never a
    # client-supplied path; absent → PSNR probe fails closed.
    reference_path: str | None = None
    # Raster of the immutable approved artifact (server-probed). When the
    # PSNR comparison is cross-raster (e.g. 1080p -> 4K upscale), the
    # reference is scale+pad'ed to the candidate raster with the product
    # letterbox policy (fit, never stretch) before measuring dB.
    reference_width: int | None = None
    reference_height: int | None = None
    # Exact source cuts in frame index + rational seconds.
    cuts: tuple[CutPoint, ...] = ()
    # Approved audio evidence (``None`` = approved output has no audio).
    audio: AudioReference | None = None


@dataclass(frozen=True)
class ValidationVerdict:
    """Pure validator outcome — no publish, no DB write."""

    verdict: Verdict
    probes: tuple[ProbeVerdict, ...] = field(default_factory=tuple)
    output_path: str = ""
    contract_version: str = "s12-export-v1"

    def probe(self, name: str) -> ProbeVerdict | None:
        for item in self.probes:
            if item.name == name:
                return item
        return None


def sha256_file(path: Path, chunk_size: int = _HASH_CHUNK) -> str:
    """Streamed sha256 of ``path`` (lowercase 64-hex, contract §1)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ffprobe_json(path: Path) -> dict | None:
    """Run ffprobe stream+format inventory; None when unmeasurable."""
    try:
        completed = subprocess.run(
            [
                find_ffprobe(),
                "-hide_banner",
                "-v",
                "error",
                "-show_entries",
                (
                    "stream=index,codec_type,codec_name,width,height,r_frame_rate,"
                    "avg_frame_rate,time_base,duration,nb_frames,channels,sample_rate"
                ),
                "-show_entries",
                "format=duration,nb_streams,size",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _ffprobe_frames(path: Path) -> list[dict] | None:
    """Decode-order frame table; None when the file does not decode."""
    try:
        completed = subprocess.run(
            [
                find_ffprobe(),
                "-hide_banner",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame=pts,pkt_dts,pict_type,key_frame",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError):
        return None
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, list):
        return None
    return [item for item in frames if isinstance(item, dict)]


def _fail(name: str, detail: str) -> ProbeVerdict:
    return ProbeVerdict(name=name, verdict="FAIL", detail=detail)


def _pass(name: str, detail: str) -> ProbeVerdict:
    return ProbeVerdict(name=name, verdict="PASS", detail=detail)


def _unknown(name: str, detail: str) -> ProbeVerdict:
    return ProbeVerdict(name=name, verdict="NOT_MEASURED", detail=detail)


def _aggregate(probes: list[ProbeVerdict]) -> Verdict:
    if any(item.verdict == "FAIL" for item in probes):
        return "FAIL"
    if any(item.verdict == "NOT_MEASURED" for item in probes):
        return "NOT_MEASURED"
    return "PASS"


def _parse_rate(value: object) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    try:
        num, den = value.split("/", 1)
        rate = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return None
    if rate <= 0:
        return None
    return rate


def _read_exact(handle, size: int) -> bytes | None:
    """Read exactly ``size`` bytes or return None on short read."""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = handle.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def probe_frame_digests(
    path: str | Path, width: int, height: int
) -> tuple[str, ...] | None:
    """Decode v:0 to raw yuv420p and sha256 each frame (presentation order).

    One digest per decoded frame — independent content-order evidence the
    validator can compare against a supplied :class:`SourceReference`.
    Returns None when the media does not fully decode.
    """
    frame_size = width * height * 3 // 2
    if frame_size <= 0:
        return None
    try:
        proc = subprocess.Popen(
            [
                find_ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "yuv420p",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    assert proc.stdout is not None
    digests: list[str] = []
    try:
        while True:
            frame = _read_exact(proc.stdout, frame_size)
            if frame is None:
                break
            digests.append(hashlib.sha256(frame).hexdigest())
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
    rc = proc.wait(timeout=300)
    if rc != 0:
        return None
    return tuple(digests) if digests else None


def _fit_filter(width: int, height: int) -> str:
    # Product letterbox policy: fit into the canvas, never stretch.
    # ``scale`` with force_original_aspect_ratio=decrease preserves the
    # source aspect inside WxH; ``pad`` centers it with black bars —
    # exactly the WS-08 preserve policy, no silent stretch/crop.
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def probe_frame_psnr(
    candidate: str | Path,
    reference: str | Path,
    width: int,
    height: int,
    reference_width: int | None = None,
    reference_height: int | None = None,
    scratch_dir: str | Path | None = None,
    cancel_flag: str | Path | None = None,
    timeout_sec: float = 600.0,
) -> tuple[float, ...] | None:
    """Measure every aligned frame with ffmpeg's native PSNR filter.

    Only one small text line per decoded frame is retained.  No full-clip raw
    file is created, and pixel arithmetic stays in ffmpeg's native filter.
    """
    if width <= 0 or height <= 0 or timeout_sec <= 0:
        return None
    root = Path(scratch_dir) if scratch_dir else Path(candidate).resolve().parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        stats = root / f".s12-psnr-{time.monotonic_ns()}.log"
        stats.unlink(missing_ok=True)
    except OSError:
        return None
    if (
        reference_width is not None
        and reference_height is not None
        and (reference_width, reference_height) != (width, height)
        and reference_width > 0
        and reference_height > 0
    ):
        reference_filter = _fit_filter(width, height)
    else:
        reference_filter = "format=yuv420p"
    filter_graph = (
        f"[1:v]{reference_filter}[reference];"
        f"[0:v][reference]psnr=stats_file={stats.name}:stats_version=2"
    )
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            [
                find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                "-reinit_filter", "0", "-i", str(Path(candidate).resolve()),
                "-reinit_filter", "0", "-i", str(Path(reference).resolve()),
                "-filter_complex", filter_graph,
                "-an", "-f", "null", "-",
            ],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + timeout_sec
        while proc.poll() is None:
            if cancel_flag is not None and Path(cancel_flag).exists():
                proc.kill()
                proc.wait()
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait()
                return None
            try:
                proc.wait(timeout=min(0.2, remaining))
            except subprocess.TimeoutExpired:
                continue
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        if proc.returncode != 0 or stderr:
            return None
        values: list[float] = []
        expected_n = 1
        for line in stats.read_text(encoding="ascii").splitlines():
            if not line.strip() or line.startswith("psnr_log_version:"):
                continue
            match = re.search(r"\bn:(\d+)\b.*\bpsnr_avg:([^\s]+)", line)
            if not match or int(match.group(1)) != expected_n:
                return None
            raw = match.group(2).lower()
            values.append(99.0 if raw in {"inf", "infinity"} else float(raw))
            expected_n += 1
        return tuple(values) if values else None
    except (OSError, ValueError, subprocess.SubprocessError):
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        return None
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        try:
            stats.unlink(missing_ok=True)
        except OSError:
            pass


def probe_audio_digest(
    path: str | Path, stream_index: int = 0
) -> str | None:
    """Decode audio stream ``stream_index`` to s16le and sha256 the PCM.

    Used to prove approved audio CONTENT (remux mode): a byte-exact copy
    of the approved audio decodes to the same digest. Returns None when
    the stream is absent or does not decode.
    """
    try:
        proc = subprocess.Popen(
            [
                find_ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-map",
                f"0:a:{stream_index}",
                "-f",
                "s16le",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    assert proc.stdout is not None
    digest = hashlib.sha256()
    try:
        while True:
            chunk = proc.stdout.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
    rc = proc.wait(timeout=300)
    if rc != 0:
        return None
    return digest.hexdigest()


def probe_audio_shape(path: str | Path, stream_index: int = 0) -> tuple[int, int] | None:
    """Return ``(channels, sample_rate)`` for an audio ordinal."""
    inventory = _ffprobe_json(Path(path))
    if inventory is None:
        return None
    streams = inventory.get("streams")
    audio = [
        item for item in streams or []
        if isinstance(item, dict) and item.get("codec_type") == "audio"
    ]
    if stream_index < 0 or stream_index >= len(audio):
        return None
    try:
        channels = int(audio[stream_index]["channels"])
        sample_rate = int(audio[stream_index]["sample_rate"])
    except (KeyError, TypeError, ValueError):
        return None
    if channels < 1 or sample_rate < 1:
        return None
    return channels, sample_rate


def probe_audio_content(
    reference: str | Path,
    candidate: str | Path,
    *,
    reference_stream_index: int = 0,
    candidate_stream_index: int = 0,
    channels: int,
    sample_rate: int,
    max_drift_sec: float,
    timeout_sec: float = 600.0,
    cancel_flag: str | Path | None = None,
) -> dict[str, float] | None:
    """Compare source-referenced audio in bounded vectorized windows.

    Both streams are decoded by ffmpeg to bounded PCM chunks.  Numpy then
    measures channel-preserving waveform correlation, relative level error,
    and broadband spectral cosine similarity for every chunk.  This is a
    source-referenced content comparison, not a dominant-frequency test;
    the conservative AAC tolerance is correlation >= 0.80, spectral cosine
    >= 0.85, and relative RMS error <= 40% in every content-bearing window.
    A silent/reference-energy mismatch always fails.  A/V packet timing is
    checked separately against the one-source-frame bound.
    """
    if channels < 1 or sample_rate < 1 or max_drift_sec < 0 or timeout_sec <= 0:
        return None
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return None
    chunk_samples = 8192
    chunk_bytes = chunk_samples * channels * 4
    commands = []
    for path, ordinal in (
        (reference, reference_stream_index),
        (candidate, candidate_stream_index),
    ):
        commands.append(
            [
                find_ffmpeg(), "-hide_banner", "-loglevel", "error",
                "-i", str(Path(path).resolve()), "-map", f"0:a:{ordinal}",
                "-ac", str(channels), "-ar", str(sample_rate),
                "-f", "f32le", "-acodec", "pcm_f32le", "-",
            ]
        )
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for argv in commands:
            processes.append(
                subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        deadline = time.monotonic() + timeout_sec
        counts = [0, 0]
        mins: list[float] = []
        spectral_mins: list[float] = []
        level_maxes: list[float] = []
        active = [True, True]
        while any(active):
            if cancel_flag is not None and Path(cancel_flag).exists():
                return None
            if time.monotonic() >= deadline:
                return None
            blocks: list[bytes] = []
            for index, process in enumerate(processes):
                if not active[index]:
                    blocks.append(b"")
                    continue
                assert process.stdout is not None
                block = process.stdout.read(chunk_bytes)
                blocks.append(block)
                if not block:
                    active[index] = False
                if len(block) % (channels * 4):
                    return None
                counts[index] += len(block) // (channels * 4)
            if not blocks[0] or not blocks[1]:
                continue
            left = np.frombuffer(blocks[0], dtype="<f4").reshape(-1, channels)
            right = np.frombuffer(blocks[1], dtype="<f4").reshape(-1, channels)
            size = min(len(left), len(right))
            if size == 0:
                continue
            left = left[:size]
            right = right[:size]
            for channel in range(channels):
                x = left[:, channel].astype(np.float64, copy=False)
                y = right[:, channel].astype(np.float64, copy=False)
                rms_x = float(np.sqrt(np.mean(x * x)))
                rms_y = float(np.sqrt(np.mean(y * y)))
                if rms_x <= 1e-5:
                    if rms_y > 1e-5:
                        return None
                    mins.append(1.0)
                    spectral_mins.append(1.0)
                    level_maxes.append(0.0)
                    continue
                if rms_y <= 1e-5:
                    return None
                centered_x = x - np.mean(x)
                centered_y = y - np.mean(y)
                denominator = float(np.linalg.norm(centered_x) * np.linalg.norm(centered_y))
                correlation = float(np.dot(centered_x, centered_y) / denominator) if denominator else 0.0
                spectrum_x = np.abs(np.fft.rfft(centered_x)) ** 2
                spectrum_y = np.abs(np.fft.rfft(centered_y)) ** 2
                spectrum_den = float(np.linalg.norm(spectrum_x) * np.linalg.norm(spectrum_y))
                spectral = float(np.dot(spectrum_x, spectrum_y) / spectrum_den) if spectrum_den else 0.0
                mins.append(correlation)
                spectral_mins.append(spectral)
                level_maxes.append(abs(rms_y - rms_x) / max(rms_x, 1e-5))
        for process in processes:
            if process.poll() is None:
                process.wait(timeout=1)
            if process.returncode != 0:
                return None
        if not mins:
            return None
        sample_delta = abs(counts[0] - counts[1])
        return {
            "windows": float(len(mins)),
            "reference_samples": float(counts[0]),
            "candidate_samples": float(counts[1]),
            "sample_delta": float(sample_delta),
            "max_allowed_sample_delta": float(sample_rate * max_drift_sec),
            "min_correlation": min(mins),
            "min_spectral_cosine": min(spectral_mins),
            "max_relative_rms_error": max(level_maxes),
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


def _probe_av_bounds(
    path: Path, video_index: int, audio_index: int
) -> dict[str, float] | None:
    """First/last packet pts (seconds) for the video and audio streams.

    Returns ``{"v_first","v_last","a_first","a_last"}`` or None when the
    packet table is unreadable. Drift checks compare these within the
    one-source-frame bound (1/fps seconds).
    """
    try:
        completed = subprocess.run(
            [
                find_ffprobe(),
                "-hide_banner",
                "-v",
                "error",
                "-show_entries",
                "packet=stream_index,pts_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError):
        return None
    packets = payload.get("packets") if isinstance(payload, dict) else None
    if not isinstance(packets, list):
        return None
    v_first = v_last = a_first = a_last = None
    v_pts: list[float] = []
    a_pts: list[float] = []
    for item in packets:
        if not isinstance(item, dict):
            return None
        try:
            idx = int(item.get("stream_index"))
            pts = float(item.get("pts_time"))
        except (TypeError, ValueError):
            return None
        if idx == video_index:
            v_first = pts if v_first is None else min(v_first, pts)
            v_last = pts if v_last is None else max(v_last, pts)
            v_pts.append(pts)
        elif idx == audio_index:
            a_first = pts if a_first is None else min(a_first, pts)
            a_last = pts if a_last is None else max(a_last, pts)
            a_pts.append(pts)
    if v_first is None or v_last is None:
        return None
    v_pts.sort()
    a_pts.sort()

    def _median_delta(values: list[float]) -> float:
        deltas = sorted(
            b - a for a, b in zip(values, values[1:]) if b - a > 1e-9
        )
        if not deltas:
            return 0.0
        mid = len(deltas) // 2
        if len(deltas) % 2:
            return deltas[mid]
        return (deltas[mid - 1] + deltas[mid]) / 2.0

    return {
        "v_first": v_first,
        "v_last": v_last,
        "v_delta": _median_delta(v_pts),
        "a_first": a_first if a_first is not None else float("nan"),
        "a_last": a_last if a_last is not None else float("nan"),
        "a_delta": _median_delta(a_pts),
    }


def _check_cuts(
    pts_values: list[int],
    key_pts: list[int],
    stream: dict,
    exp: ValidationExpectation,
) -> list[ProbeVerdict]:
    """Cut/seam sub-checks folded into ``frame_order`` (C12 source-locked).

    Every manifest cut must land on a keyframe (I-frame) within
    ``cut_tolerance_frames`` frame durations, compared as exact rationals
    (pts x time_base) -- never float seconds. No cuts asserted → no verdict
    (keeps the 10-probe shape stable).
    """
    if not exp.expected_cuts:
        return []
    try:
        num, den = str(stream.get("time_base", "1/90000")).split("/", 1)
        scale = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return [_unknown("frame_order", "time_base unreadable for cut check")]
    fps = exp.expected_fps or _parse_rate(stream.get("avg_frame_rate"))
    if not fps:
        return [_unknown("frame_order", "fps unreadable for cut check")]
    frame_dur = Fraction(1, 1) / Fraction(fps).limit_denominator(100000)
    key_times = {Fraction(pts) * scale for pts in key_pts}
    step = float(frame_dur) * exp.cut_tolerance_frames
    missing = [
        cut
        for cut in exp.expected_cuts
        if not any(abs(float(key) - cut) <= step for key in key_times)
    ]
    if missing:
        return [
            _fail(
                "frame_order",
                f"cuts without keyframe: {missing} (keys={len(key_pts)})",
            )
        ]
    return [_pass("frame_order", f"{len(exp.expected_cuts)} cuts keyframe-locked")]


def _replace_probes(
    probes: list[ProbeVerdict], name: str, verdicts: list[ProbeVerdict]
) -> list[ProbeVerdict]:
    """Drop every earlier verdict for ``name`` and append fresh ones."""
    return [item for item in probes if item.name != name] + verdicts


def _source_locked_overrides(
    probes: list[ProbeVerdict],
    exp: ValidationExpectation,
    path: Path,
    inventory: dict,
    streams: list,
    video: list,
    audio: list,
    frames: list[dict] | None,
) -> list[ProbeVerdict]:
    """C2 F07: re-validate source-truth probes against the independent
    :class:`SourceReference`. Candidate self-evidence (monotonic PTS,
    keyframes, audio presence, self-hash) is NOT accepted as proof here;
    missing reference authority fails closed.
    """
    ref = exp.source_reference
    if ref is None:
        probes.append(
            ProbeVerdict(
                name="reference",
                verdict="FAIL",
                detail="source-locked validation requires independent "
                "SourceReference evidence",
            )
        )
        return probes
    if ref.fps_num <= 0 or ref.fps_den <= 0:
        probes.append(
            ProbeVerdict(
                name="reference",
                verdict="FAIL",
                detail=f"reference fps invalid: {ref.fps_num}/{ref.fps_den}",
            )
        )
        return probes
    if ref.frame_count is None or ref.frame_count < 0:
        probes.append(
            ProbeVerdict(
                name="reference",
                verdict="FAIL",
                detail="reference frame_count missing",
            )
        )
        return probes
    fps = Fraction(ref.fps_num, ref.fps_den)
    one_frame = float(Fraction(ref.fps_den, ref.fps_num))  # 1/fps seconds
    reference_ok = ProbeVerdict(
        name="reference",
        verdict="PASS",
        detail=f"reference artifact {ref.artifact_sha256[:16]}… "
        f"fps={ref.fps_num}/{ref.fps_den} frames={ref.frame_count}",
    )
    probes = [item for item in probes if item.name != "reference"]
    probes.append(reference_ok)

    if not video:
        probes = _replace_probes(
            probes,
            "frame_count",
            [_fail("frame_count", "no video stream")],
        )
        probes = _replace_probes(
            probes,
            "frame_order",
            [_fail("frame_order", "no video stream")],
        )
        probes = _replace_probes(
            probes,
            "timebase",
            [_fail("timebase", "no video stream")],
        )
        probes = _replace_probes(
            probes,
            "streams",
            [_fail("streams", "no video stream present")],
        )
        probes = _replace_probes(
            probes,
            "duration",
            [_fail("duration", "no video stream")],
        )
        probes = _replace_probes(
            probes,
            "av_policy",
            [_fail("av_policy", "no video stream")],
        )
        return probes

    # --- streams inventory vs approved output ---------------------------
    audio_ref = ref.audio
    expected_audio = 0 if (audio_ref is None or audio_ref.mode == "absent") else 1
    foreign = [
        s
        for s in streams
        if isinstance(s, dict) and s.get("codec_type") not in ("video", "audio")
    ]
    if foreign:
        kinds = sorted({str(s.get("codec_type")) for s in foreign})
        probes = _replace_probes(
            probes, "streams", [_fail("streams", f"unexpected stream types: {kinds}")]
        )
    elif len(audio) != expected_audio:
        probes = _replace_probes(
            probes,
            "streams",
            [
                _fail(
                    "streams",
                    f"audio streams={len(audio)} but approved output has "
                    f"{expected_audio}",
                )
            ],
        )
    else:
        probes = _replace_probes(
            probes,
            "streams",
            [
                _pass(
                    "streams",
                    f"video=1 audio={len(audio)} total={len(streams)} "
                    "(approved inventory)",
                )
            ],
        )

    # --- frame_count ----------------------------------------------------
    decoded = len(frames) if frames is not None else None
    if frames is None:
        probes = _replace_probes(
            probes, "frame_count", [_fail("frame_count", "frames do not decode")]
        )
    elif decoded == ref.frame_count:
        probes = _replace_probes(
            probes,
            "frame_count",
            [_pass("frame_count", f"{decoded} frames == reference")],
        )
    else:
        probes = _replace_probes(
            probes,
            "frame_count",
            [
                _fail(
                    "frame_count",
                    f"decoded={decoded}, reference={ref.frame_count}",
                )
            ],
        )

    # --- timebase: exact rational CFR vs reference -----------------------
    avg_raw = video[0].get("avg_frame_rate")
    rfr_raw = video[0].get("r_frame_rate")
    avg_frac = _parse_rational(avg_raw)
    rfr_frac = _parse_rational(rfr_raw)
    if avg_frac is None:
        probes = _replace_probes(
            probes,
            "timebase",
            [_fail("timebase", "candidate avg_frame_rate unreadable")],
        )
    elif avg_frac != fps:
        probes = _replace_probes(
            probes,
            "timebase",
            [
                _fail(
                    "timebase",
                    f"candidate fps={avg_raw} != reference {ref.fps_num}/{ref.fps_den}",
                )
            ],
        )
    elif rfr_frac is not None and rfr_frac != fps:
        probes = _replace_probes(
            probes,
            "timebase",
            [
                _fail(
                    "timebase",
                    f"VFR rejected: r_frame_rate={rfr_raw} != reference "
                    f"{ref.fps_num}/{ref.fps_den}",
                )
            ],
        )
    else:
        probes = _replace_probes(
            probes,
            "timebase",
            [
                _pass(
                    "timebase",
                    f"time_base={video[0].get('time_base')} "
                    f"fps={ref.fps_num}/{ref.fps_den} exact",
                )
            ],
        )

    # --- frame_order: psnr tolerance > content digests > cuts > unknown --
    if exp.frame_match_mode not in ("exact", "psnr"):
        probes = _replace_probes(
            probes,
            "frame_order",
            [
                _fail(
                    "frame_order",
                    f"unknown frame_match_mode={exp.frame_match_mode!r} "
                    "(fail-closed)",
                )
            ],
        )
    elif exp.frame_match_mode == "psnr":
        probes = _replace_probes(
            probes,
            "frame_order",
            _measure_psnr_order(path, video[0], exp, ref),
        )
    elif ref.frame_digests:
        if len(ref.frame_digests) != ref.frame_count:
            probes = _replace_probes(
                probes,
                "frame_order",
                [
                    _fail(
                        "frame_order",
                        "reference digest authority length "
                        f"{len(ref.frame_digests)} != frame_count {ref.frame_count}",
                    )
                ],
            )
        else:
            try:
                width = int(video[0].get("width"))
                height = int(video[0].get("height"))
            except (TypeError, ValueError):
                width = height = 0
            candidate = probe_frame_digests(path, width, height) if width and height else None
            if candidate is None:
                probes = _replace_probes(
                    probes,
                    "frame_order",
                    [
                        _fail(
                            "frame_order",
                            "candidate content digests not measurable (decode fail)",
                        )
                    ],
                )
            elif len(candidate) != len(ref.frame_digests):
                probes = _replace_probes(
                    probes,
                    "frame_order",
                    [
                        _fail(
                            "frame_order",
                            f"candidate frames={len(candidate)} != reference "
                            f"digests={len(ref.frame_digests)}",
                        )
                    ],
                )
            else:
                mismatch = next(
                    (
                        i
                        for i, (got, want) in enumerate(
                            zip(candidate, ref.frame_digests)
                        )
                        if got != want
                    ),
                    None,
                )
                if mismatch is None:
                    probes = _replace_probes(
                        probes,
                        "frame_order",
                        [
                            _pass(
                                "frame_order",
                                f"decoded content order matches {len(candidate)} "
                                "reference frame digests",
                            )
                        ],
                    )
                else:
                    probes = _replace_probes(
                        probes,
                        "frame_order",
                        [
                            _fail(
                                "frame_order",
                                f"content order mismatch at frame {mismatch}: "
                                f"got {candidate[mismatch][:12]}… expected "
                                f"{ref.frame_digests[mismatch][:12]}…",
                            )
                        ],
                    )
    elif ref.cuts:
        probes = _replace_probes(
            probes,
            "frame_order",
            _check_rational_cuts(path, frames, video[0], ref, fps, one_frame),
        )
    else:
        probes = _replace_probes(
            probes,
            "frame_order",
            [
                ProbeVerdict(
                    name="frame_order",
                    verdict="NOT_MEASURED",
                    detail="no independent content-order/cut reference authority",
                )
            ],
        )

    # --- duration: one-source-frame bound (1/fps), not 2% + 50ms ---------
    expected_duration = float(Fraction(ref.frame_count * ref.fps_den, ref.fps_num))
    raw: object = inventory.get("format", {}).get("duration") if isinstance(
        inventory.get("format"), dict
    ) else None
    if raw is None:
        raw = video[0].get("duration")
    try:
        measured = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        measured = None
    if measured is None or measured <= 0:
        probes = _replace_probes(
            probes, "duration", [_fail("duration", "candidate duration unreadable")]
        )
    elif abs(measured - expected_duration) <= one_frame:
        probes = _replace_probes(
            probes,
            "duration",
            [
                _pass(
                    "duration",
                    f"{measured:.3f}s vs reference {expected_duration:.3f}s "
                    f"(<= {one_frame:.4f}s one-source-frame bound)",
                )
            ],
        )
    else:
        probes = _replace_probes(
            probes,
            "duration",
            [
                _fail(
                    "duration",
                    f"{measured:.3f}s vs reference {expected_duration:.3f}s "
                    f"(bound {one_frame:.4f}s = 1 source frame)",
                )
            ],
        )

    # --- av_policy: approved audio presence/mapping/content/drift ---------
    probes = _replace_probes(
        probes,
        "av_policy",
        _source_locked_audio(
            path,
            audio,
            video[0],
            audio_ref,
            fps,
            one_frame,
            cancel_flag=exp.cancel_flag,
            timeout_sec=exp.validation_timeout_sec,
        ),
    )

    # --- provenance: server-owned output hash required --------------------
    if exp.expected_sha256 is None:
        probes = _replace_probes(
            probes,
            "provenance",
            [
                ProbeVerdict(
                    name="provenance",
                    verdict="FAIL",
                    detail="source-locked validation requires server-owned "
                    "output sha256 authority",
                )
            ],
        )
    else:
        try:
            actual = sha256_file(path)
            ok = actual == exp.expected_sha256
        except OSError:
            actual = None
            ok = False
        probes = _replace_probes(
            probes,
            "provenance",
            [
                (
                    _pass("provenance", f"sha256={actual[:16]}…")
                    if ok
                    else _fail(
                        "provenance",
                        "sha256 mismatch got="
                        f"{(actual or '?')[:16]}… expected={exp.expected_sha256[:16]}…",
                    )
                )
            ],
        )
    return probes


def _measure_psnr_order(
    path: Path,
    stream: dict,
    exp: ValidationExpectation,
    ref: SourceReference,
) -> list[ProbeVerdict]:
    """Measured tolerance frame-order check (interface-delta).

    Decoded candidate frames are compared against the immutable
    approved-artifact media at the approved raster; every frame must be
    >= ``frame_psnr_min_db`` (documented per profile by the consumer).
    Missing threshold or missing reference_path fails closed. Content
    reorder/wrong-reference drops PSNR far below any sane profile
    threshold, so tamper still FAILs under tolerance.
    """
    threshold = exp.frame_psnr_min_db
    if threshold is None or threshold <= 0:
        return [
            _fail(
                "frame_order",
                "psnr mode requires documented frame_psnr_min_db (per profile)",
            )
        ]
    reference_path = ref.reference_path
    if not reference_path or not Path(reference_path).is_file():
        return [
            _fail(
                "frame_order",
                "psnr mode requires immutable reference_path (approved artifact)",
            )
        ]
    try:
        width = int(stream.get("width"))
        height = int(stream.get("height"))
    except (TypeError, ValueError):
        width = height = 0
    if not width or not height:
        return [_fail("frame_order", "candidate raster unreadable for PSNR")]
    values = probe_frame_psnr(
        path,
        reference_path,
        width,
        height,
        ref.reference_width,
        ref.reference_height,
        exp.scratch_dir,
        exp.cancel_flag,
        exp.validation_timeout_sec,
    )
    if values is None:
        return [
            _fail(
                "frame_order",
                "candidate/reference PSNR not measurable (decode failure)",
            )
        ]
    if len(values) != ref.frame_count:
        return [
            _fail(
                "frame_order",
                f"PSNR frames={len(values)} != reference frame_count "
                f"{ref.frame_count}",
            )
        ]
    low = [
        (i, value)
        for i, value in enumerate(values)
        if value < threshold
    ]
    if low:
        worst = min(low, key=lambda item: item[1])
        return [
            _fail(
                "frame_order",
                f"PSNR frame {worst[0]} = {worst[1]:.2f} dB < "
                f"threshold {threshold:.1f} dB (tamper/content drift)",
            )
        ]
    geometry = ""
    if (
        ref.reference_width is not None
        and ref.reference_height is not None
        and (ref.reference_width, ref.reference_height) != (width, height)
    ):
        geometry = (
            f" (reference {ref.reference_width}x{ref.reference_height} "
            f"fit+pad to {width}x{height})"
        )
    return [
        _pass(
            "frame_order",
            f"{len(values)} frames PSNR >= {threshold:.1f} dB{geometry}",
        )
    ]


def _parse_rational(value: object) -> Fraction | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    try:
        num, den = value.split("/", 1)
        frac = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return None
    if frac <= 0:
        return None
    return frac


def _check_rational_cuts(
    path: Path,
    frames: list[dict] | None,
    stream: dict,
    ref: SourceReference,
    fps: Fraction,
    one_frame: float,
) -> list[ProbeVerdict]:
    """Placement of every reference cut on the candidate timeline.

    Each cut frame must present at its exact rational timestamp within
    the one-source-frame bound (1/fps). Candidate frame times are
    pts x time_base — rational, never float seconds.
    """
    if not ref.cuts:
        return [
            ProbeVerdict(
                name="frame_order",
                verdict="NOT_MEASURED",
                detail="no independent content-order/cut reference authority",
            )
        ]
    try:
        num, den = str(stream.get("time_base", "1/90000")).split("/", 1)
        tb = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return [_fail("frame_order", "candidate time_base unreadable")]
    if frames is None:
        return [_fail("frame_order", "frames do not decode")]
    pts_sorted: list[Fraction] = []
    for item in frames:
        try:
            pts_sorted.append(Fraction(int(item["pts"])) * tb)
        except (KeyError, TypeError, ValueError):
            continue
    if not pts_sorted:
        return [_fail("frame_order", "candidate pts unreadable")]
    pts_sorted.sort()
    pts_by_index = {index: pts for index, pts in enumerate(pts_sorted)}
    missing: list[str] = []
    for cut in ref.cuts:
        frame_time = pts_by_index.get(cut.frame_index)
        if frame_time is None:
            missing.append(f"#{cut.frame_index}")
            continue
        want = Fraction(cut.pts_num, cut.pts_den)
        if abs(float(frame_time - want)) > one_frame:
            missing.append(
                f"#{cut.frame_index}@{float(frame_time):.4f}s!={float(want):.4f}s"
            )
    if missing:
        return [_fail("frame_order", f"cuts misplaced: {missing}")]
    return [_pass("frame_order", f"{len(ref.cuts)} rational cuts placed in bound")]


def _source_locked_audio(
    path: Path,
    audio: list,
    video_stream: dict,
    audio_ref: AudioReference | None,
    fps: Fraction,
    one_frame: float,
    *,
    cancel_flag: str | Path | None = None,
    timeout_sec: float = 600.0,
) -> list[ProbeVerdict]:
    """Approved-audio check: presence, mapping, remux content, A/V drift."""
    absent = audio_ref is None or audio_ref.mode == "absent"
    if absent:
        if audio:
            return [
                _fail(
                    "av_policy",
                    f"audio present ({len(audio)} streams) but approved output is silent",
                )
            ]
        return [_pass("av_policy", "no audio as approved (absent)")]
    if not audio:
        return [_fail("av_policy", f"approved audio missing (mode={audio_ref.mode})")]
    ordinal = audio_ref.stream_index
    if ordinal >= len(audio):
        return [
            _fail(
                "av_policy",
                f"approved audio mapping stream_index={ordinal} missing "
                f"(candidate has {len(audio)})",
            )
        ]
    audio_stream = audio[ordinal]
    content_detail = ""
    if audio_ref.channels is not None:
        try:
            candidate_channels = int(audio_stream.get("channels"))
        except (TypeError, ValueError):
            return [_fail("av_policy", "candidate audio channel count unreadable")]
        if candidate_channels != audio_ref.channels:
            return [
                _fail(
                    "av_policy",
                    f"audio channels={candidate_channels} != approved "
                    f"{audio_ref.channels}",
                )
            ]
    if audio_ref.sample_rate is not None:
        try:
            candidate_rate = int(audio_stream.get("sample_rate"))
        except (TypeError, ValueError):
            return [_fail("av_policy", "candidate audio sample rate unreadable")]
        if candidate_rate != audio_ref.sample_rate:
            return [
                _fail(
                    "av_policy",
                    f"audio sample_rate={candidate_rate} != approved "
                    f"{audio_ref.sample_rate}",
                )
            ]
    if audio_ref.mode == "remux":
        if not audio_ref.digest:
            return [
                _fail("av_policy", "remux reference missing audio digest authority")
            ]
        got = probe_audio_digest(path, ordinal)
        if got is None:
            return [_fail("av_policy", "approved audio not decodable in candidate")]
        if got != audio_ref.digest:
            return [
                _fail(
                    "av_policy",
                    f"audio content digest mismatch got={got[:12]}… "
                    f"expected={audio_ref.digest[:12]}…",
                )
            ]
    elif audio_ref.mode == "transcode":
        if not audio_ref.reference_path or not Path(audio_ref.reference_path).is_file():
            return [
                _fail(
                    "av_policy",
                    "transcode reference requires immutable approved audio path",
                )
            ]
        shape = probe_audio_content(
            audio_ref.reference_path,
            path,
            reference_stream_index=audio_ref.stream_index,
            candidate_stream_index=ordinal,
            channels=audio_ref.channels or 0,
            sample_rate=audio_ref.sample_rate or 0,
            max_drift_sec=one_frame,
            timeout_sec=timeout_sec,
            cancel_flag=cancel_flag,
        )
        if shape is None:
            return [_fail("av_policy", "transcoded audio content not measurable")]
        if shape["sample_delta"] > shape["max_allowed_sample_delta"]:
            return [
                _fail(
                    "av_policy",
                    f"audio decoded sample length drift={shape['sample_delta']:.0f} "
                    f"> {shape['max_allowed_sample_delta']:.0f} bound",
                )
            ]
        if (
            shape["min_correlation"] < 0.80
            or shape["min_spectral_cosine"] < 0.85
            or shape["max_relative_rms_error"] > 0.40
        ):
            return [
                _fail(
                    "av_policy",
                    "transcoded audio content differs: "
                    f"corr>={shape['min_correlation']:.3f}, "
                    f"spectral>={shape['min_spectral_cosine']:.3f}, "
                    f"rms_error<={shape['max_relative_rms_error']:.3f}",
                )
            ]
        content_detail = (
            f"content windows={shape['windows']:.0f}, "
            f"corr>={shape['min_correlation']:.3f}, "
            f"spectral>={shape['min_spectral_cosine']:.3f}, "
            f"rms_error<={shape['max_relative_rms_error']:.3f}"
        )
    try:
        video_index = int(video_stream.get("index"))
    except (TypeError, ValueError):
        return [_fail("av_policy", "candidate video stream index unreadable")]
    try:
        audio_index = int(audio_stream.get("index"))
    except (TypeError, ValueError):
        return [_fail("av_policy", "candidate audio stream index unreadable")]
    bounds = _probe_av_bounds(path, video_index, audio_index)
    if bounds is None:
        return [_fail("av_policy", "A/V packet table unreadable")]
    # End alignment accounts for the last packet's own duration (median
    # packet spacing), so a video ending at v_last + v_delta and audio at
    # a_last + a_delta must agree within the one-source-frame bound.
    v_end = bounds["v_last"] + bounds["v_delta"]
    a_end = bounds["a_last"] + bounds["a_delta"]
    drift_start = abs(bounds["a_first"] - bounds["v_first"])
    drift_end = abs(a_end - v_end)
    if drift_start > one_frame or drift_end > one_frame:
        return [
            _fail(
                "av_policy",
                f"A/V drift start={drift_start:.4f}s end={drift_end:.4f}s "
                f"> bound {one_frame:.4f}s (1 source frame)",
            )
        ]
    mode_detail = {
        "remux": "content digest match",
        "transcode": content_detail,
    }.get(audio_ref.mode, "")
    return [
        _pass(
            "av_policy",
            f"approved audio mode={audio_ref.mode} mapping ok, "
            f"{mode_detail}, drift start={drift_start:.4f}s end={drift_end:.4f}s "
            f"<= {one_frame:.4f}s",
        )
    ]


def validate(
    output_path: str | Path,
    expectation: ValidationExpectation | None = None,
) -> ValidationVerdict:
    """Validate one completed export output (pure: no publish, no DB).

    ``output_path`` must be the final completed path — a ``.partial``
    path fails ``completeness``. Missing/truncated/corrupt media fails
    (or reports NOT_MEASURED when the evidence is insufficient), never a
    fake PASS.
    """
    exp = expectation or ValidationExpectation()
    path = Path(output_path)
    probes: list[ProbeVerdict] = []

    # --- completeness: existence + suffix + container readability ---------
    if path.suffix == PARTIAL_SUFFIX or path.name.endswith(PARTIAL_SUFFIX):
        probes.append(_fail("completeness", f"partial path rejected: {path.name}"))
        return ValidationVerdict(
            verdict="FAIL", probes=tuple(probes), output_path=str(path)
        )
    if not path.is_file():
        probes.append(_fail("completeness", f"output missing: {path}"))
        return ValidationVerdict(
            verdict="FAIL", probes=tuple(probes), output_path=str(path)
        )

    inventory = _ffprobe_json(path)
    if inventory is None:
        probes.append(_fail("completeness", "ffprobe cannot read container"))
        return ValidationVerdict(
            verdict="FAIL", probes=tuple(probes), output_path=str(path)
        )
    probes.append(_pass("completeness", "container readable, completed suffix"))

    streams = inventory.get("streams")
    if not isinstance(streams, list):
        streams = []
    video = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audio = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]

    # --- resolution -------------------------------------------------------
    if not video:
        probes.append(_fail("resolution", "no video stream"))
    else:
        primary = video[0]
        width = primary.get("width")
        height = primary.get("height")
        if width == exp.width and height == exp.height:
            probes.append(_pass("resolution", f"{width}x{height}"))
        elif isinstance(width, int) and isinstance(height, int):
            probes.append(
                _fail(
                    "resolution",
                    f"got {width}x{height}, expected {exp.width}x{exp.height}",
                )
            )
        else:
            probes.append(_unknown("resolution", "width/height unreadable"))

    # --- codec ------------------------------------------------------------
    if not video:
        probes.append(_fail("codec", "no video stream"))
    else:
        codec = str(video[0].get("codec_name") or "")
        if codec == exp.codec:
            probes.append(_pass("codec", codec))
        elif codec:
            probes.append(_fail("codec", f"got {codec}, expected {exp.codec}"))
        else:
            probes.append(_unknown("codec", "codec_name unreadable"))

    # --- streams ----------------------------------------------------------
    foreign = [
        s
        for s in streams
        if isinstance(s, dict) and s.get("codec_type") not in ("video", "audio")
    ]
    if not video:
        probes.append(_fail("streams", "no video stream present"))
    elif foreign:
        kinds = sorted({str(s.get("codec_type")) for s in foreign})
        probes.append(_fail("streams", f"unexpected stream types: {kinds}"))
    else:
        probes.append(
            _pass(
                "streams",
                f"video=1 audio={len(audio)} total={len(streams)}",
            )
        )

    # --- frame_count / frame_order / timebase (decode layer) --------------
    frames = _ffprobe_frames(path) if video else None
    if not video:
        probes.append(_fail("frame_count", "no video stream"))
        probes.append(_fail("frame_order", "no video stream"))
        probes.append(_fail("timebase", "no video stream"))
    elif frames is None:
        probes.append(_fail("frame_count", "frames do not decode"))
        probes.append(_fail("frame_order", "frames do not decode"))
        probes.append(_fail("timebase", "frames do not decode"))
    else:
        if exp.expected_frame_count is None:
            probes.append(
                _unknown(
                    "frame_count",
                    f"decoded={len(frames)} but manifest asserts no count",
                )
            )
        elif len(frames) == exp.expected_frame_count:
            probes.append(_pass("frame_count", f"{len(frames)} frames"))
        else:
            probes.append(
                _fail(
                    "frame_count",
                    f"decoded={len(frames)}, expected={exp.expected_frame_count}",
                )
            )

        pts_values: list[int] = []
        key_pts: list[int] = []
        order_ok = True
        for item in frames:
            try:
                pts_values.append(int(item["pts"]))
                try:
                    is_key = int(item.get("key_frame", 0)) == 1
                except (TypeError, ValueError):
                    is_key = False
                if is_key or item.get("pict_type") == "I":
                    key_pts.append(pts_values[-1])
            except (KeyError, TypeError, ValueError):
                order_ok = False
                break
        if not pts_values:
            probes.append(_unknown("frame_order", "no presentation timestamps"))
        elif not order_ok:
            probes.append(_fail("frame_order", "unreadable presentation timestamp"))
        elif all(later > earlier for earlier, later in zip(pts_values, pts_values[1:])):
            probes.append(_pass("frame_order", f"{len(pts_values)} pts strictly increasing"))
            probes.extend(_check_cuts(pts_values, key_pts, video[0], exp))
        else:
            probes.append(_fail("frame_order", "presentation timestamps not monotonic"))

        time_base = video[0].get("time_base")
        fps = _parse_rate(video[0].get("avg_frame_rate"))
        rfr = _parse_rate(video[0].get("r_frame_rate"))
        if isinstance(time_base, str) and "/" in time_base and fps is not None:
            if (
                exp.reject_vfr
                and rfr is not None
                and abs(rfr - fps) > max(0.01 * fps, 1e-3)
            ):
                probes.append(
                    _fail(
                        "timebase",
                        "VFR rejected: r_frame_rate="
                        f"{video[0].get('r_frame_rate')!r} != avg_frame_rate="
                        f"{video[0].get('avg_frame_rate')!r}",
                    )
                )
            elif exp.expected_fps is not None and abs(fps - exp.expected_fps) > max(
                0.01 * exp.expected_fps, 1e-3
            ):
                probes.append(
                    _fail(
                        "timebase",
                        f"fps~{fps:.3f} vs expected {exp.expected_fps:.3f}",
                    )
                )
            else:
                probes.append(_pass("timebase", f"time_base={time_base} fps~{fps:.3f}"))
        else:
            probes.append(
                _unknown(
                    "timebase",
                    f"time_base={time_base!r} avg_frame_rate={video[0].get('avg_frame_rate')!r}",
                )
            )

    # --- duration ---------------------------------------------------------
    if exp.expected_duration_sec is None:
        probes.append(_unknown("duration", "manifest asserts no duration"))
    else:
        raw: object = inventory.get("format", {}).get("duration") if isinstance(
            inventory.get("format"), dict
        ) else None
        if raw is None and video:
            raw = video[0].get("duration")
        try:
            measured = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            measured = None
        if measured is None or measured <= 0:
            probes.append(_unknown("duration", "duration unreadable"))
        else:
            tolerance = abs(exp.expected_duration_sec) * exp.duration_tolerance + 0.05
            if abs(measured - exp.expected_duration_sec) <= tolerance:
                probes.append(
                    _pass("duration", f"{measured:.3f}s vs {exp.expected_duration_sec:.3f}s")
                )
            else:
                probes.append(
                    _fail(
                        "duration",
                        f"{measured:.3f}s vs expected {exp.expected_duration_sec:.3f}s",
                    )
                )

    # --- av_policy --------------------------------------------------------
    if exp.audio_policy not in ("required", "absent", "either"):
        probes.append(_fail("av_policy", f"unknown audio_policy={exp.audio_policy!r}"))
    elif exp.audio_policy == "either":
        probes.append(_unknown("av_policy", f"audio streams={len(audio)}, unconstrained"))
    elif exp.audio_policy == "required" and audio:
        probes.append(_pass("av_policy", f"audio present ({audio[0].get('codec_name')})"))
    elif exp.audio_policy == "absent" and not audio:
        probes.append(_pass("av_policy", "no audio stream as required"))
    elif exp.audio_policy == "required":
        probes.append(_fail("av_policy", "audio required but no audio stream"))
    else:
        probes.append(_fail("av_policy", f"audio must be absent, found {len(audio)}"))

    # --- provenance (identity, never file size) ----------------------------
    if exp.expected_sha256 is None:
        probes.append(_unknown("provenance", "manifest asserts no sha256"))
    else:
        try:
            actual = sha256_file(path)
        except OSError as exc:
            probes.append(_fail("provenance", f"unhashable output: {exc}"))
            actual = None
        if actual is not None:
            if actual == exp.expected_sha256:
                probes.append(_pass("provenance", f"sha256={actual[:16]}…"))
            else:
                probes.append(
                    _fail(
                        "provenance",
                        f"sha256 mismatch got={actual[:16]}… expected={exp.expected_sha256[:16]}…",
                    )
                )

    # C2 source-locked mode (F07): re-validate against independent
    # reference evidence; missing authority fails closed.
    if exp.source_locked:
        probes = _source_locked_overrides(
            probes, exp, path, inventory, streams, video, audio, frames
        )

    # Order probes per REQUIRED_PROBES for a stable verdict shape.
    order = {name: index for index, name in enumerate(REQUIRED_PROBES)}
    probes.sort(key=lambda item: order.get(item.name, len(order)))
    return ValidationVerdict(
        verdict=_aggregate(probes), probes=tuple(probes), output_path=str(path)
    )
