"""S11-T06A1 deterministic media builders (ffmpeg lavfi, no network).

Owned module (W3 write-set) — every builder produces REAL media bytes with
local ffmpeg 8.1.2+ (gyan.dev) lavfi synthonics: ``testsrc``/``color``/
``sine`` + local encoders (libx264, libvpx-vp9, mpeg4, aac).  Rules from
lane-B TEST_FIXTURE_PLAN §3:

1. no URL/font/network input — lavfi synthonics only;
2. ffmpeg/ffprobe resolved locally (``app.services.ffmpeg_utils`` with a
   ``shutil.which`` fast path; conftest already prepends WinGet Links);
3. list-args + ``shell=False`` + bounded timeout (<= 120 s) everywhere;
4. EVERY builder ASSERT-SAFTER-BUILD with real ffprobe (codec / duration /
   stream counts) and fails the test immediately when the output deviates
   (lane-B §3.4) — no downstream test eats a mis-built fixture indirectly;
5. no media binary is committed — everything is rebuilt at runtime into
   the caller's temp dir.

``build_all_media(dest_dir)`` is the ONE-COMMAND dataset builder
(acceptance criterion 1): seven scenarios, deterministic, no network, no
committed binaries.

Determinism convention (lane-B §1.1): within one machine + one ffmpeg
build the outputs repeat byte-for-byte (asserted by the harness ×2 runs);
NO hard cross-machine byte hash is ever asserted — codecs/stream counts/
duration-with-tolerance are the cross-machine stable facts, and they are
frozen in the committed media manifests.

Scenario inventory (matches tests/fixtures/s11_qc/media_manifests/*.json):
- two_scene_source            MP4 H.264 + AAC, 2 contrasting solid-color
                              scenes concatenated (known cut boundary)
- multistream_duration_variant MP4 H.264 + 4 AAC, duration-variant (3 s)
- unsupported_non_mp4         H.264+AAC in Matroska (.mkv) container
- unsupported_vp9             VP9 video in MP4 (unsupported codec)
- unsupported_mpeg4           MPEG-4 Part 2 video in MP4 (unsupported)
- corrupt_truncate            valid source whose middle bytes are removed
                              (lane-B §2.2) → ffprobe rejects it
- no_audio_source             H.264 video with ZERO audio streams
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe  # noqa: E402

__all__ = [
    "MEDIA_SCENARIOS",
    "MediaProbeError",
    "build_all_media",
    "build_corrupt_truncate",
    "build_multistream_duration_variant",
    "build_no_audio_source",
    "build_two_scene_source",
    "build_unsupported_mpeg4",
    "build_unsupported_non_mp4",
    "build_unsupported_vp9",
    "ffmpeg",
    "ffmpeg_available",
    "ffprobe",
    "iter_manifests",
    "load_manifest",
    "probe",
    "probe_facts",
]

#: Canonical scenario order — the fixture suite iterates this exactly once.
MEDIA_SCENARIOS: tuple[str, ...] = (
    "two_scene_source",
    "multistream_duration_variant",
    "unsupported_non_mp4",
    "unsupported_vp9",
    "unsupported_mpeg4",
    "corrupt_truncate",
    "no_audio_source",
)

#: Committed manifest directory — the deterministic description of every
#: scenario (builder + params + probe expectations + seed plan).
MANIFEST_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "s11_qc" / "media_manifests"
)

#: Bounded command timeout for every ffmpeg/ffprobe fixture command
#: (lane-B §3.3).  The whole dataset builds in well under this per file.
_CMD_TIMEOUT_S = 120

#: Common lavfi geometry for every video fixture (measured S11 convention:
#: short clips, small frames — heavy pipeline sections stay cheap).
_WIDTH, _HEIGHT, _RATE = 320, 240, 30

_SCRUB_HEX_PTR = re.compile(r"(?:@\s*)?(?:0x)?[0-9a-fA-F]{8,}")
_SCRUB_ABS_PATH = re.compile(r"[A-Za-z]:[\\/][^ :\r\n]*")


def _scrub_probe_error(text: str) -> str:
    """Deterministic error text for cross-run comparison.

    ffprobe stderr embeds the ABSOLUTE path of the probed file and raw
    memory addresses of internal contexts (``@ 0x...``) — both differ run
    to run.  Scrub them (plus whitespace collapse) so the ×2 determinism
    comparison and the corrupt-manifest check see ONLY the stable message
    fragments ("moov atom not found", "Invalid data found ...").
    """
    text = _SCRUB_HEX_PTR.sub("0xPTR", text)
    text = _SCRUB_ABS_PATH.sub("<ABS>", text)
    return " ".join(text.split())[:400]


class MediaProbeError(RuntimeError):
    """ffprobe rejected the file (media is corrupt or not a media file)."""


# ── binary resolution ──────────────────────────────────────────────────────

def ffmpeg() -> str:
    """Resolve the local ffmpeg (shutil fast path → ffmpeg_utils)."""
    return shutil.which("ffmpeg") or find_ffmpeg()


def ffprobe() -> str:
    """Resolve the local ffprobe (shutil fast path → ffmpeg_utils)."""
    return shutil.which("ffprobe") or find_ffprobe()


def ffmpeg_available() -> bool:
    """True when BOTH binaries resolve locally (skip-mark for the suite)."""
    try:
        ffmpeg()
        ffprobe()
        return True
    except (RuntimeError, FileNotFoundError):
        return False


# ── probing ────────────────────────────────────────────────────────────────

def probe(path: Path) -> dict[str, Any]:
    """Full ffprobe JSON (format + streams).  Raises ``MediaProbeError``
    when ffprobe rejects the file (stderr included for diagnosis)."""
    result = subprocess.run(
        [
            ffprobe(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=_CMD_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise MediaProbeError(
            f"ffprobe rejected {path}: {result.stderr.strip()[:300]}"
        )
    data = json.loads(result.stdout)
    assert "format" in data and "streams" in data, (
        f"unexpected probe payload for {path}: {result.stdout[:200]}"
    )
    return data


def probe_facts(path: Path, *, allow_error: bool = False) -> dict[str, Any]:
    """Deterministic, comparable probe facts for one media file.

    Success:  ``{"probe_ok": True, "size_bytes", "format_name",
    "duration_sec", "streams": [...]}`` where streams carries only stable
    fields (index/codec_type/codec_name/width/height/channels/sample_rate)
    and duration is rounded to 3 decimals (float-noise safe).
    Failure (only when ``allow_error=True``): ``{"probe_ok": False,
    "size_bytes", "probe_error": <stderr excerpt>}`` — the corrupt-truncate
    scenario and the ×2 determinism comparison rely on this shape.
    """
    size = Path(path).stat().st_size
    try:
        data = probe(path)
    except MediaProbeError as err:
        if not allow_error:
            raise
        return {
            "probe_ok": False,
            "size_bytes": size,
            "probe_error": _scrub_probe_error(str(err)),
        }
    fmt = data["format"]
    streams = []
    for s in data["streams"]:
        streams.append(
            {
                "index": s.get("index"),
                "codec_type": s.get("codec_type"),
                "codec_name": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "channels": s.get("channels"),
                "sample_rate": s.get("sample_rate"),
            }
        )
    duration = fmt.get("duration")
    return {
        "probe_ok": True,
        "size_bytes": size,
        "format_name": fmt.get("format_name", ""),
        "duration_sec": round(float(duration), 3) if duration else None,
        "streams": streams,
    }


# ── manifests ──────────────────────────────────────────────────────────────

def load_manifest(scenario: str) -> dict[str, Any]:
    """Load one commit-able media manifest (schema frozen by the harness)."""
    path = MANIFEST_DIR / f"{scenario}.json"
    if not path.exists():
        raise FileNotFoundError(f"media manifest missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_manifests() -> list[dict[str, Any]]:
    """All manifests, in canonical scenario order."""
    return [load_manifest(s) for s in MEDIA_SCENARIOS]


# ── internal build helper ──────────────────────────────────────────────────

def _run_ffmpeg(args: list[str]) -> None:
    """Bounded, list-arg ffmpeg execution; non-zero exit = hard failure."""
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=_CMD_TIMEOUT_S
    )
    assert result.returncode == 0, (
        f"ffmpeg fixture generation failed: {result.stderr[-400:]}"
    )


def _assert_probe_facts(
    path: Path,
    *,
    format_contains: str,
    duration_sec: float,
    duration_tolerance: float,
    streams: list[tuple[str, str, int]],
) -> None:
    """Fail-fast post-build assertion (lane-B §3.4): real ffprobe facts
    must match the builder's contract — format family, duration (tolerance
    for container variance), and (codec_type, codec_name, count) per kind.

    Raises immediately when the fixture deviates; a downstream test never
    silently consumes a mis-built file.
    """
    facts = probe_facts(path)
    assert facts["probe_ok"]
    assert format_contains in facts["format_name"], (
        f"{path.name}: expected format containing {format_contains!r}, "
        f"got {facts['format_name']!r}"
    )
    duration = facts["duration_sec"]
    assert duration is not None and abs(duration - duration_sec) <= duration_tolerance, (
        f"{path.name}: expected duration {duration_sec} ± {duration_tolerance}, "
        f"got {duration}"
    )
    for codec_type, codec_name, count in streams:
        actual = [
            s
            for s in facts["streams"]
            if s["codec_type"] == codec_type and s["codec_name"] == codec_name
        ]
        assert len(actual) == count, (
            f"{path.name}: expected {count} {codec_type}/{codec_name} "
            f"stream(s), got {len(actual)}: {facts['streams']}"
        )


def _assert_corrupt(path: Path, source_size: int) -> None:
    """Fail-fast assertion for the corrupt scenario: bytes were removed
    from the middle (lane-B §2.2) and REAL ffprobe rejects the file."""
    size = path.stat().st_size
    assert 0 < size < source_size, (
        f"{path.name}: truncation must shrink the source ({source_size} "
        f"-> {size} bytes)"
    )
    facts = probe_facts(path, allow_error=True)
    assert facts["probe_ok"] is False, (
        f"{path.name}: truncated file must not probe cleanly"
    )
    assert "moov atom not found" in facts["probe_error"].lower() or (
        "invalid data" in facts["probe_error"].lower()
    ), f"{path.name}: unexpected probe error text: {facts['probe_error']}"


# ── builders (each asserts its own output) ─────────────────────────────────

def build_two_scene_source(
    path: Path,
    *,
    duration_a: float = 2.0,
    duration_b: float = 2.0,
    width: int = _WIDTH,
    height: int = _HEIGHT,
    rate: int = _RATE,
) -> Path:
    """MP4 with TWO contrasting solid-color scenes (known cut boundary for
    cut-drift checks) + one AAC 440 Hz audio stream (total duration =
    duration_a + duration_b)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = duration_a + duration_b
    _run_ffmpeg(
        [
            ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"color=c=0xDE6B35:size={width}x{height}:rate={rate}:duration={duration_a}",
            "-f", "lavfi", "-i",
            f"color=c=0x223355:size={width}x{height}:rate={rate}:duration={duration_b}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={total}",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            str(path),
        ]
    )
    _assert_probe_facts(
        path,
        format_contains="mp4",
        duration_sec=total,
        duration_tolerance=0.35,
        streams=[("video", "h264", 1), ("audio", "aac", 1)],
    )
    return path


def build_multistream_duration_variant(
    path: Path,
    *,
    duration: float = 3.0,
    audio_streams: int = 4,
) -> Path:
    """MP4 H.264 + N AAC streams at distinct frequencies (440/880/1320/
    1760 Hz) — the duration-VARIANT of the S11 ``_make_multistream_aac``
    pattern (lane-B TEST_FIXTURE_PLAN §1.1 / §2.1)."""
    assert audio_streams >= 1, "audio_streams must be >= 1"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    freqs = [440, 880, 1320, 1760, 2200, 2640]
    args = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    args += [
        "-f", "lavfi", "-i",
        f"testsrc=duration={duration}:size={_WIDTH}x{_HEIGHT}:rate={_RATE}",
    ]
    for i in range(audio_streams):
        args += ["-f", "lavfi", "-i", f"sine=frequency={freqs[i]}:duration={duration}"]
    args += ["-map", "0:v"]
    for i in range(audio_streams):
        args += ["-map", f"{i + 1}:a"]
    args += [
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k",
        str(path),
    ]
    _run_ffmpeg(args)
    _assert_probe_facts(
        path,
        format_contains="mp4",
        duration_sec=duration,
        duration_tolerance=0.35,
        streams=[("video", "h264", 1), ("audio", "aac", audio_streams)],
    )
    return path


def build_unsupported_non_mp4(
    path: Path, *, duration: float = 2.0
) -> Path:
    """H.264+AAC in a Matroska (.mkv) container — the non-MP4 negative
    (engine accepts MP4 container only, frozen decision 2)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc=duration={duration}:size={_WIDTH}x{_HEIGHT}:rate={_RATE}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            str(path),
        ]
    )
    _assert_probe_facts(
        path,
        format_contains="matroska",
        duration_sec=duration,
        duration_tolerance=0.35,
        streams=[("video", "h264", 1), ("audio", "aac", 1)],
    )
    return path


def build_unsupported_vp9(path: Path, *, duration: float = 2.0) -> Path:
    """VP9 video in an MP4 container — unsupported-codec negative (frozen
    decision 2: H.264/HEVC only)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc=duration={duration}:size={_WIDTH}x{_HEIGHT}:rate={_RATE}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libvpx-vp9", "-b:v", "200k",
            "-c:a", "aac", "-b:a", "64k",
            str(path),
        ]
    )
    _assert_probe_facts(
        path,
        format_contains="mp4",
        duration_sec=duration,
        duration_tolerance=0.35,
        streams=[("video", "vp9", 1), ("audio", "aac", 1)],
    )
    return path


def build_unsupported_mpeg4(path: Path, *, duration: float = 2.0) -> Path:
    """MPEG-4 Part 2 video in an MP4 container — unsupported-codec negative
    (frozen decision 2)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc=duration={duration}:size={_WIDTH}x{_HEIGHT}:rate={_RATE}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "mpeg4", "-q:v", "5",
            "-c:a", "aac", "-b:a", "64k",
            str(path),
        ]
    )
    _assert_probe_facts(
        path,
        format_contains="mp4",
        duration_sec=duration,
        duration_tolerance=0.35,
        streams=[("video", "mpeg4", 1), ("audio", "aac", 1)],
    )
    return path


def build_corrupt_truncate(
    path: Path,
    *,
    source_duration: float = 2.0,
    remove_ratio: float = 0.5,
) -> Path:
    """Corrupt-source negative (lane-B §2.2 pattern): build a VALID MP4
    first, then REMOVE real bytes from the middle of the file (the
    [25 %, 75 %) window) and write the remainder.  Asserts the output is
    byte-reduced and that REAL ffprobe rejects it (measured: 'moov atom
    not found', rc=1) — the engine's fail-closed import precondition."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    valid_source = path.parent / (path.stem + "_valid_src.mp4")
    build_no_audio_source(valid_source, duration=source_duration)
    data = valid_source.read_bytes()
    n = len(data)
    cut_start = int(n * 0.25)
    cut_end = int(n * (1.0 - remove_ratio / 2))
    truncated = data[:cut_start] + data[cut_end:]
    path.write_bytes(truncated)
    valid_source.unlink(missing_ok=True)
    _assert_corrupt(path, source_size=n)
    return path


def build_no_audio_source(path: Path, *, duration: float = 2.0) -> Path:
    """H.264 video with ZERO audio streams — the NO_AUDIO_PRESENT path
    (frozen decision 5: explicit no-audio, nothing fabricated)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc=duration={duration}:size={_WIDTH}x{_HEIGHT}:rate={_RATE}",
            "-map", "0:v",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p",
            str(path),
        ]
    )
    _assert_probe_facts(
        path,
        format_contains="mp4",
        duration_sec=duration,
        duration_tolerance=0.35,
        streams=[("video", "h264", 1)],
    )
    return path


# ── one-command dataset build (acceptance criterion 1) ─────────────────────

_BUILDERS: dict[str, Callable[..., Path]] = {
    "build_two_scene_source": build_two_scene_source,
    "build_multistream_duration_variant": build_multistream_duration_variant,
    "build_unsupported_non_mp4": build_unsupported_non_mp4,
    "build_unsupported_vp9": build_unsupported_vp9,
    "build_unsupported_mpeg4": build_unsupported_mpeg4,
    "build_corrupt_truncate": build_corrupt_truncate,
    "build_no_audio_source": build_no_audio_source,
}


def build_all_media(dest_dir: Path) -> dict[str, Path]:
    """ONE command builds the ENTIRE media dataset into ``dest_dir``
    (created if missing) and returns {scenario: file path} in canonical
    order.  No network, no committed binaries — every file is generated
    locally and asserted with real ffprobe before returning."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    built: dict[str, Path] = {}
    for scenario in MEDIA_SCENARIOS:
        manifest = load_manifest(scenario)
        builder = _BUILDERS[manifest["media"]["builder"]]
        params = dict(manifest["media"]["params"])
        relative = manifest["media"]["relative_path"]
        out_path = dest / relative
        out_path.parent.mkdir(parents=True, exist_ok=True)
        built[scenario] = builder(out_path, **params)
    return built