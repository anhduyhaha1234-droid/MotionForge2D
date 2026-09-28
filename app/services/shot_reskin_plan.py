"""Shot plan and precise timebase for source-locked reskin (MF-END-11).

One deterministic pipeline turns a REAL source MP4 into a versioned shot-plan
artifact:

* ``probe_source_facts`` (:data:`MF-END-11.1`) — ffprobe + packet/​PTS
  measurement (and an optional deep decode count) pinned with the full-file
  source sha256 and audio metadata.  Numbers are MEASURED, never assumed:
  the packet PTS table is read from the container, sorted into display order,
  and the decoded frame count is cross-checked when requested.
* ``detect_shot_intervals`` / ``plan_shot_intervals`` (:data:`MF-END-11.2`) —
  cut detection REUSES the legacy detector through the additive adapter
  ``app.services.scene_detection.detect_scene_intervals``; intervals are
  rebuilt against the MEASURED frame count so the partition
  ``[0, frame_count)`` is gap-free and duplicate-free by construction and is
  validated by the half-open adapter in ``app.services.source_locked_timeline``
  (same typed ``TIMELINE_*`` codes as the frozen block).
* ``plan_shot_chunks`` (:data:`MF-END-11.3`) — chunks respect the engine
  capability frame limit (largest ``4n+1`` shape <= ``max_frames``), carry an
  exact trim/context map (context frames are never double counted in the
  export core), and boundaries avoid protected interaction intervals when a
  nearby valid boundary exists; an unavoidable straddle is FLAGGED with the
  span id, never silently cut.
* ``ShotPlanArtifact`` (:data:`MF-END-11.4`) — versioned, canonical-JSON
  serializable with a content digest re-verified on load; a changed source
  (or measured timebase) invalidates the plan with a typed verdict.

No render, no GPU: this module plans and serializes only.  Contract types
(``SourceSpan``/``TimebaseFacts``) come from the FROZEN MF-END-01 module
``app/schemas/shot_reskin.py``; this module never modifies it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.schemas.shot_reskin import (
    ShotReskinRefusal,
    SourceSpan,
    TimebaseFacts,
    payload_sha256,
)
from app.services.ffmpeg_utils import find_ffprobe
from app.services.source_locked_timeline import (
    pick_partition_code,
    validate_half_open_partition,
)
from app.services.timebase import CLASSIFICATION_CFR, CLASSIFICATION_VFR

__all__ = [
    "CODE_CAPABILITY_INVALID",
    "CODE_CONTEXT_INVALID",
    "CODE_COVERAGE_INVALID",
    "CODE_DIGEST_MISMATCH",
    "CODE_FACTS_INVALID",
    "CODE_FRAME_COUNT_MISMATCH",
    "CODE_PROBE_FAILED",
    "CODE_PTS_LIMIT_EXCEEDED",
    "CODE_PTS_MEASUREMENT_FAILED",
    "CODE_SERIALIZATION_INVALID",
    "CODE_SOURCE_CHANGED",
    "CODE_SOURCE_MISSING",
    "CODE_TIMEBASE_CHANGED",
    "CODE_TIMEBASE_UNAVAILABLE",
    "CODE_VALID",
    "CODE_VERSION_UNSUPPORTED",
    "DEFAULT_COMFY_CAPABILITY",
    "DEFAULT_MIN_SCENE_LEN_FRAMES",
    "DEFAULT_SCENE_THRESHOLD",
    "INVALIDATION_SOURCE_CHANGED",
    "INVALIDATION_TIMEBASE_CHANGED",
    "INVALIDATION_VALID",
    "PLAN_MAX_PTS_ENTRIES",
    "PLAN_SCHEMA_VERSION",
    "AudioStreamFacts",
    "CapabilityFrameLimit",
    "DetectorFacts",
    "DroppedCut",
    "InvalidationVerdict",
    "PlannedChunk",
    "PlannedShot",
    "ProtectedInterval",
    "ShotPlanArtifact",
    "ShotPlanError",
    "SourceFacts",
    "SourcePartition",
    "build_shot_plan",
    "check_plan_validity",
    "detect_shot_intervals",
    "file_sha256",
    "invalidate_if_source_changed",
    "normalize_pts_ticks",
    "parse_rational",
    "plan_shot_chunks",
    "plan_shot_intervals",
    "probe_source_facts",
    "require_current_plan",
    "require_matching_frame_counts",
]

#: Version of the persisted shot-plan artifact (managed-artifact version tag).
PLAN_SCHEMA_VERSION = "mf.shot_reskin.plan.v1"

#: Fail-closed ceiling on the packet/PTS table size (≈9.2 h at 30 fps).
PLAN_MAX_PTS_ENTRIES = 1_000_000

#: Bounded timeout for one ffprobe invocation (seconds).
_PROBE_TIMEOUT_SECONDS = 120.0

#: Legacy detector defaults (re-exported from ``scene_detection`` semantics).
DEFAULT_SCENE_THRESHOLD = 27.0
DEFAULT_MIN_SCENE_LEN_FRAMES = 15

# ── typed reason codes (planner-local, stable strings) ───────────────────────

CODE_SOURCE_MISSING = "SHOT_PLAN_SOURCE_MISSING"
CODE_PROBE_FAILED = "SHOT_PLAN_PROBE_FAILED"
CODE_SOURCE_CHANGED = "SHOT_PLAN_SOURCE_CHANGED"
CODE_TIMEBASE_UNAVAILABLE = "SHOT_PLAN_TIMEBASE_UNAVAILABLE"
CODE_TIMEBASE_CHANGED = "SHOT_PLAN_TIMEBASE_CHANGED"
CODE_PTS_MEASUREMENT_FAILED = "SHOT_PLAN_PTS_MEASUREMENT_FAILED"
CODE_PTS_LIMIT_EXCEEDED = "SHOT_PLAN_PTS_LIMIT_EXCEEDED"
CODE_FRAME_COUNT_MISMATCH = "SHOT_PLAN_FRAME_COUNT_MISMATCH"
CODE_FACTS_INVALID = "SHOT_PLAN_FACTS_INVALID"
CODE_COVERAGE_INVALID = "SHOT_PLAN_COVERAGE_INVALID"
CODE_CAPABILITY_INVALID = "SHOT_PLAN_CAPABILITY_INVALID"
CODE_CONTEXT_INVALID = "SHOT_PLAN_CONTEXT_INVALID"
CODE_VERSION_UNSUPPORTED = "SHOT_PLAN_VERSION_UNSUPPORTED"
CODE_DIGEST_MISMATCH = "SHOT_PLAN_DIGEST_MISMATCH"
CODE_SERIALIZATION_INVALID = "SHOT_PLAN_SERIALIZATION_INVALID"
CODE_VALID = "SHOT_PLAN_VALID"

#: Invalidation statuses (the plan-vs-source verdict vocabulary).
INVALIDATION_VALID = "valid"
INVALIDATION_SOURCE_CHANGED = "stale_source_changed"
INVALIDATION_TIMEBASE_CHANGED = "stale_timebase_changed"


class ShotPlanError(ValueError):
    """Typed fail-closed error for shot-plan work (planner-local codes)."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


# ── small pure helpers ────────────────────────────────────────────────────────


def parse_rational(text: Any, *, what: str = "rational") -> tuple[int, int]:
    """Exact ``"<num>/<den>"`` (or bare int) parse — never a float round-trip.

    Non-integer, zero or negative components fail closed with
    ``SHOT_PLAN_TIMEBASE_UNAVAILABLE``.
    """
    raw = str(text or "").strip()
    parts = raw.split("/")
    if len(parts) not in (1, 2):
        raise ShotPlanError(CODE_TIMEBASE_UNAVAILABLE, f"{what} {text!r} is not '<num>/<den>'")
    try:
        num = int(parts[0])
        den = int(parts[1]) if len(parts) == 2 else 1
    except (TypeError, ValueError) as err:
        raise ShotPlanError(
            CODE_TIMEBASE_UNAVAILABLE, f"{what} {text!r} has non-integer components"
        ) from err
    if num <= 0 or den <= 0:
        raise ShotPlanError(
            CODE_TIMEBASE_UNAVAILABLE, f"{what} {text!r} must be a positive rational"
        )
    return num, den


def file_sha256(path: str | Path) -> str:
    """Full-file sha256 (streamed; lowercase hex)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_pts_ticks(raw: Sequence[int]) -> tuple[tuple[int, ...], int]:
    """Sort the measured packet PTS into DISPLAY order and normalise to origin 0.

    Decode order is not presentation order (B-frames reorder PTS), so the
    table used for the frame↔time map is the sorted one; duplicate display
    timestamps break the 1:1 frame map and fail closed.  Returns
    ``(sorted_ticks, origin)`` where ``origin = min(min(raw), 0)`` is the
    shift applied (0 for the normal all-non-negative case; a negative first
    PTS is shifted instead of hidden).
    """
    if not raw:
        raise ShotPlanError(CODE_PTS_MEASUREMENT_FAILED, "no packet PTS values were measured")
    values = sorted(int(value) for value in raw)
    for previous, current in zip(values, values[1:]):
        if current == previous:
            raise ShotPlanError(
                CODE_PTS_MEASUREMENT_FAILED,
                f"duplicate display timestamp {current} ticks (frame map is not 1:1)",
            )
    origin = min(values[0], 0)
    return tuple(value - origin for value in values), origin


def require_matching_frame_counts(packet_count: int, decoded_count: int) -> None:
    """Cross-check the packet count against a deep decode count (fail closed)."""
    if packet_count != decoded_count:
        raise ShotPlanError(
            CODE_FRAME_COUNT_MISMATCH,
            f"packet PTS count {packet_count} != decoded frame count {decoded_count}",
        )


def _run_ffprobe(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except subprocess.TimeoutExpired as err:
        raise ShotPlanError(
            CODE_PROBE_FAILED, f"ffprobe exceeded the {timeout}s bounded budget"
        ) from err
    except OSError as err:
        raise ShotPlanError(CODE_PROBE_FAILED, f"ffprobe could not be executed: {err}") from err


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _to_str_pair_fps(num: int, den: int) -> str:
    return f"{num}/{den}"


# ── measured source facts (MF-END-11.1) ───────────────────────────────────────


@dataclass(frozen=True)
class AudioStreamFacts:
    """First audio stream of the locked source (pinned, never guessed)."""

    index: int
    codec_name: str
    sample_rate: int
    channels: int
    duration_seconds: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "codec_name": self.codec_name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> AudioStreamFacts:
        try:
            index = int(payload["index"])
            sample_rate = int(payload["sample_rate"])
            channels = int(payload["channels"])
            codec_name = str(payload["codec_name"])
        except (KeyError, TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"audio facts are malformed: {payload!r}"
            ) from err
        if index < 0 or sample_rate <= 0 or channels <= 0 or not codec_name:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"audio facts are out of range: {payload!r}"
            )
        duration = payload.get("duration_seconds")
        return cls(
            index=index,
            codec_name=codec_name,
            sample_rate=sample_rate,
            channels=channels,
            duration_seconds=None if duration is None else str(duration),
        )


@dataclass(frozen=True)
class SourceFacts:
    """The measured facts of one locked source artifact (display-order PTS)."""

    source_sha256: str
    file_size_bytes: int
    width: int
    height: int
    codec_name: str
    fps_num: int
    fps_den: int
    fps_classification: str
    stream_timebase_num: int | None
    stream_timebase_den: int | None
    frame_count: int
    pts_ticks: tuple[int, ...]
    pts_start_ticks: int
    pts_end_ticks: int
    pts_origin_ticks: int
    pts_uniform: bool
    decoded_frame_count: int | None
    container_nb_frames: int | None
    audio: AudioStreamFacts | None

    def __post_init__(self) -> None:
        problems: list[str] = []
        if len(self.source_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.source_sha256
        ):
            problems.append("source_sha256 must be 64 lowercase hex chars")
        if self.fps_num <= 0 or self.fps_den <= 0:
            problems.append(f"fps rational {self.fps_num}/{self.fps_den} must be positive")
        if self.fps_classification not in (CLASSIFICATION_CFR, CLASSIFICATION_VFR):
            problems.append(f"fps_classification {self.fps_classification!r} is not CFR/VFR")
        if (self.stream_timebase_num is None) != (self.stream_timebase_den is None):
            problems.append("stream time_base must be a complete rational pair or absent")
        if self.frame_count != len(self.pts_ticks) or self.frame_count < 1:
            problems.append(
                f"frame_count {self.frame_count} != PTS table length {len(self.pts_ticks)} (or < 1)"
            )
        if self.pts_ticks:
            if any(b <= a for a, b in zip(self.pts_ticks, self.pts_ticks[1:])):
                problems.append("PTS table is not strictly increasing (display order)")
            if self.pts_start_ticks != self.pts_ticks[0]:
                problems.append("pts_start_ticks != first PTS entry")
            if self.pts_end_ticks != self.pts_ticks[-1]:
                problems.append("pts_end_ticks != last PTS entry")
        if self.decoded_frame_count is not None and self.decoded_frame_count != self.frame_count:
            problems.append(
                f"decoded_frame_count {self.decoded_frame_count} != frame_count {self.frame_count}"
            )
        if problems:
            raise ShotPlanError(CODE_FACTS_INVALID, "; ".join(problems))

    @property
    def fps(self) -> Fraction:
        """The canonical frame rate as an exact ``Fraction``."""
        return Fraction(self.fps_num, self.fps_den)

    @property
    def fps_text(self) -> str:
        return _to_str_pair_fps(self.fps_num, self.fps_den)

    def timebase_facts(self) -> TimebaseFacts:
        """The frozen MF-END-01 ``TimebaseFacts`` view of these measurements."""
        return TimebaseFacts(
            fps_num=self.fps_num,
            fps_den=self.fps_den,
            stream_timebase_num=self.stream_timebase_num,
            stream_timebase_den=self.stream_timebase_den,
            pts_start_ticks=self.pts_start_ticks,
            pts_end_ticks=self.pts_end_ticks,
            decoded_frame_count=self.decoded_frame_count,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "file_size_bytes": self.file_size_bytes,
            "width": self.width,
            "height": self.height,
            "codec_name": self.codec_name,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "fps_classification": self.fps_classification,
            "stream_timebase_num": self.stream_timebase_num,
            "stream_timebase_den": self.stream_timebase_den,
            "frame_count": self.frame_count,
            "pts_ticks": list(self.pts_ticks),
            "pts_start_ticks": self.pts_start_ticks,
            "pts_end_ticks": self.pts_end_ticks,
            "pts_origin_ticks": self.pts_origin_ticks,
            "pts_uniform": self.pts_uniform,
            "decoded_frame_count": self.decoded_frame_count,
            "container_nb_frames": self.container_nb_frames,
            "audio": None if self.audio is None else self.audio.to_json(),
        }

    @classmethod
    def from_json(cls, payload: Any) -> SourceFacts:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "source facts must be an object")
        required = (
            "source_sha256",
            "file_size_bytes",
            "width",
            "height",
            "codec_name",
            "fps_num",
            "fps_den",
            "fps_classification",
            "frame_count",
            "pts_ticks",
            "pts_start_ticks",
            "pts_end_ticks",
            "pts_origin_ticks",
            "pts_uniform",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"source facts missing keys: {missing}"
            )
        try:
            ticks = tuple(int(value) for value in payload["pts_ticks"])
            audio_payload = payload.get("audio")
            timebase_num = payload.get("stream_timebase_num")
            timebase_den = payload.get("stream_timebase_den")
            return cls(
                source_sha256=str(payload["source_sha256"]),
                file_size_bytes=int(payload["file_size_bytes"]),
                width=int(payload["width"]),
                height=int(payload["height"]),
                codec_name=str(payload["codec_name"]),
                fps_num=int(payload["fps_num"]),
                fps_den=int(payload["fps_den"]),
                fps_classification=str(payload["fps_classification"]),
                stream_timebase_num=None if timebase_num is None else int(timebase_num),
                stream_timebase_den=None if timebase_den is None else int(timebase_den),
                frame_count=int(payload["frame_count"]),
                pts_ticks=ticks,
                pts_start_ticks=int(payload["pts_start_ticks"]),
                pts_end_ticks=int(payload["pts_end_ticks"]),
                pts_origin_ticks=int(payload["pts_origin_ticks"]),
                pts_uniform=bool(payload["pts_uniform"]),
                decoded_frame_count=(
                    None
                    if payload.get("decoded_frame_count") is None
                    else int(payload["decoded_frame_count"])
                ),
                container_nb_frames=(
                    None
                    if payload.get("container_nb_frames") is None
                    else int(payload["container_nb_frames"])
                ),
                audio=(
                    None
                    if audio_payload is None
                    else AudioStreamFacts.from_json(audio_payload)
                ),
            )
        except ShotPlanError:
            raise
        except (TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"source facts are malformed: {err}"
            ) from err


def probe_source_facts(
    source_path: str | Path,
    *,
    expected_sha256: str | None = None,
    deep_count: bool = False,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> SourceFacts:
    """Measure the locked source (MF-END-11.1) — ffprobe + packet PTS table.

    * full-file sha256 (``expected_sha256`` given and different refuses with
      ``SHOT_PLAN_SOURCE_CHANGED``);
    * exact rational fps + classification (CFR grid = ``r_frame_rate``, VFR
      grid = ``avg_frame_rate``);
    * stream ``time_base`` as a rational pair;
    * the packet PTS table, sorted to display order and normalised to origin 0
      (the delivered frame/PTS numbers — never ``duration × fps``);
    * ``deep_count=True`` additionally DECODES (``-count_frames``) and
      cross-checks ``nb_read_frames`` against the packet count;
    * the first audio stream's codec/sample_rate/channels/duration.

    Fails closed with planner-local typed codes; never guesses.
    """
    path = Path(source_path)
    if not path.exists():
        raise ShotPlanError(CODE_SOURCE_MISSING, f"source file does not exist: {path}")
    digest = file_sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ShotPlanError(
            CODE_SOURCE_CHANGED,
            f"source sha256 {digest[:16]}… != expected {expected_sha256[:16]}…",
        )

    ffprobe = find_ffprobe()
    probe_cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,"
        "time_base,nb_frames,sample_rate,channels,duration:format=duration",
        str(path),
    ]
    result = _run_ffprobe(probe_cmd, timeout=timeout)
    if result.returncode != 0:
        raise ShotPlanError(
            CODE_PROBE_FAILED,
            f"ffprobe exited {result.returncode}: {(result.stderr or '').strip()[:300]}",
        )
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError as err:
        raise ShotPlanError(CODE_PROBE_FAILED, "ffprobe stdout is not valid JSON") from err
    streams = data.get("streams")
    if not isinstance(streams, list):
        raise ShotPlanError(CODE_PROBE_FAILED, "ffprobe returned no stream section")
    video = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), None
    )
    if video is None:
        raise ShotPlanError(CODE_PROBE_FAILED, "container has no video stream")
    audio_stream = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"), None
    )

    width = _to_int(video.get("width")) or 0
    height = _to_int(video.get("height")) or 0
    if width <= 0 or height <= 0:
        raise ShotPlanError(CODE_PROBE_FAILED, f"invalid video dimensions {width}x{height}")

    r_rate: tuple[int, int] | None = None
    avg_rate: tuple[int, int] | None = None
    try:
        r_rate = parse_rational(video.get("r_frame_rate"), what="r_frame_rate")
    except ShotPlanError:
        r_rate = None
    try:
        avg_rate = parse_rational(video.get("avg_frame_rate"), what="avg_frame_rate")
    except ShotPlanError:
        avg_rate = None
    if r_rate is not None and avg_rate is not None and r_rate == avg_rate:
        fps_num, fps_den = r_rate
        classification = CLASSIFICATION_CFR
    elif avg_rate is not None:
        fps_num, fps_den = avg_rate
        classification = CLASSIFICATION_VFR
    else:
        raise ShotPlanError(
            CODE_TIMEBASE_UNAVAILABLE,
            f"neither r_frame_rate {video.get('r_frame_rate')!r} nor avg_frame_rate "
            f"{video.get('avg_frame_rate')!r} is a usable positive rational",
        )

    timebase_num: int | None = None
    timebase_den: int | None = None
    if video.get("time_base") is not None:
        try:
            timebase_num, timebase_den = parse_rational(
                video.get("time_base"), what="stream time_base"
            )
        except ShotPlanError:
            timebase_num, timebase_den = None, None

    packet_cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "packet=pts",
        "-of", "csv=p=0",
        str(path),
    ]
    packets = _run_ffprobe(packet_cmd, timeout=timeout)
    if packets.returncode != 0:
        raise ShotPlanError(
            CODE_PTS_MEASUREMENT_FAILED,
            f"packet probe exited {packets.returncode}: "
            f"{(packets.stderr or '').strip()[:300]}",
        )
    raw_pts: list[int] = []
    for line in (packets.stdout or "").splitlines():
        token = line.strip().rstrip(",")
        if not token:
            continue
        try:
            raw_pts.append(int(token))
        except ValueError as err:
            raise ShotPlanError(
                CODE_PTS_MEASUREMENT_FAILED,
                f"packet PTS token {token!r} is not an integer (fail closed)",
            ) from err
    if len(raw_pts) > PLAN_MAX_PTS_ENTRIES:
        raise ShotPlanError(
            CODE_PTS_LIMIT_EXCEEDED,
            f"{len(raw_pts)} packets exceed the {PLAN_MAX_PTS_ENTRIES}-entry plan ceiling",
        )
    ticks, origin = normalize_pts_ticks(raw_pts)
    frame_count = len(ticks)

    decoded_frame_count: int | None = None
    if deep_count:
        deep = _run_ffprobe(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-count_frames",
                "-show_entries", "stream=nb_read_frames",
                "-of", "csv=p=0",
                str(path),
            ],
            timeout=timeout,
        )
        decoded = _to_int((deep.stdout or "").strip())
        if deep.returncode != 0 or decoded is None:
            raise ShotPlanError(
                CODE_FRAME_COUNT_MISMATCH,
                "deep decode count unavailable: "
                f"rc={deep.returncode} out={(deep.stdout or '').strip()[:80]!r}",
            )
        require_matching_frame_counts(frame_count, decoded)
        decoded_frame_count = decoded

    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    audio = None
    if audio_stream is not None:
        audio = AudioStreamFacts(
            index=_to_int(audio_stream.get("index")) or 0,
            codec_name=str(audio_stream.get("codec_name") or ""),
            sample_rate=_to_int(audio_stream.get("sample_rate")) or 0,
            channels=_to_int(audio_stream.get("channels")) or 0,
            duration_seconds=(
                None
                if audio_stream.get("duration") is None
                else str(audio_stream.get("duration"))
            ),
        )

    return SourceFacts(
        source_sha256=digest,
        file_size_bytes=path.stat().st_size,
        width=width,
        height=height,
        codec_name=str(video.get("codec_name") or ""),
        fps_num=fps_num,
        fps_den=fps_den,
        fps_classification=classification,
        stream_timebase_num=timebase_num,
        stream_timebase_den=timebase_den,
        frame_count=frame_count,
        pts_ticks=ticks,
        pts_start_ticks=ticks[0],
        pts_end_ticks=ticks[-1],
        pts_origin_ticks=origin,
        pts_uniform=len(gaps) <= 1 or len(set(gaps)) == 1,
        decoded_frame_count=decoded_frame_count,
        container_nb_frames=_to_int(video.get("nb_frames")),
        audio=audio,
    )

# ── engine capability + shot partition (MF-END-11.2) ─────────────────────────

DEFAULT_COMFY_CAPABILITY_LABEL = "comfy.video.4n+1"


@dataclass(frozen=True)
class CapabilityFrameLimit:
    """The engine's frame capability for ONE call (shape-aware budget).

    ``budget()`` is the largest length <= ``max_frames`` in the engine's
    accepted frame-shape family (``(length - shape_offset) % shape_modulus == 0``
    — for the local video nodes the ``4n+1`` family; 81 is the template default,
    not a requirement that every shot be 81 frames).
    """

    max_frames: int
    shape_modulus: int = 4
    shape_offset: int = 1
    label: str = DEFAULT_COMFY_CAPABILITY_LABEL

    def __post_init__(self) -> None:
        if self.max_frames < 1:
            raise ShotPlanError(CODE_CAPABILITY_INVALID, f"max_frames {self.max_frames} < 1")
        if self.shape_modulus < 1:
            raise ShotPlanError(
                CODE_CAPABILITY_INVALID, f"shape_modulus {self.shape_modulus} < 1"
            )
        if not 0 <= self.shape_offset < self.shape_modulus:
            raise ShotPlanError(
                CODE_CAPABILITY_INVALID,
                f"shape_offset {self.shape_offset} outside [0,{self.shape_modulus})",
            )
        if not self.label:
            raise ShotPlanError(CODE_CAPABILITY_INVALID, "label must be non-empty")

    def budget(self) -> int:
        """Largest shape-aligned length <= ``max_frames`` (always >= 1)."""
        remainder = (self.max_frames - self.shape_offset) % self.shape_modulus
        return max(1, self.max_frames - remainder)

    def to_json(self) -> dict[str, Any]:
        return {
            "max_frames": self.max_frames,
            "shape_modulus": self.shape_modulus,
            "shape_offset": self.shape_offset,
            "label": self.label,
        }

    @classmethod
    def from_json(cls, payload: Any) -> CapabilityFrameLimit:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "capability must be an object")
        try:
            return cls(
                max_frames=int(payload["max_frames"]),
                shape_modulus=int(payload.get("shape_modulus", 4)),
                shape_offset=int(payload.get("shape_offset", 1)),
                label=str(payload.get("label") or DEFAULT_COMFY_CAPABILITY_LABEL),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"capability is malformed: {err}"
            ) from err


DEFAULT_COMFY_CAPABILITY = CapabilityFrameLimit(
    max_frames=81, shape_modulus=4, shape_offset=1, label=DEFAULT_COMFY_CAPABILITY_LABEL
)


@dataclass(frozen=True)
class ProtectedInterval:
    """A source interval the chunker must not cut through when avoidable.

    The role/interaction layer supplies these once it has measured them; the
    planner itself never invents interactions.
    """

    span_id: str
    span: SourceSpan

    def __post_init__(self) -> None:
        if not self.span_id:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, "protected interval span_id must be non-empty"
            )


@dataclass(frozen=True)
class DroppedCut:
    """A cut candidate the planner refused to keep (recorded, never silent).

    ``reason`` is one of ``at_zero`` / ``out_of_range`` / ``duplicate``.
    """

    cut_frame: int
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"cut_frame": self.cut_frame, "reason": self.reason}

    @classmethod
    def from_json(cls, payload: Any) -> DroppedCut:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "dropped cut must be an object")
        try:
            cut = cls(cut_frame=int(payload["cut_frame"]), reason=str(payload["reason"]))
        except (KeyError, TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"dropped cut is malformed: {err}"
            ) from err
        if cut.reason not in ("at_zero", "out_of_range", "duplicate"):
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"dropped cut reason {cut.reason!r} is unknown"
            )
        return cut


@dataclass(frozen=True)
class SourcePartition:
    """The validated gap-free shot partition of one source."""

    frame_count: int
    shots: tuple[SourceSpan, ...]
    dropped_cuts: tuple[DroppedCut, ...]


def _span_to_json(span: SourceSpan) -> list[int]:
    return [span.start_frame, span.end_frame_exclusive]


def _span_from_json(raw: Any, *, what: str) -> SourceSpan:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ShotPlanError(CODE_SERIALIZATION_INVALID, f"{what} must be a [start, end) pair")
    try:
        return SourceSpan(start_frame=int(raw[0]), end_frame_exclusive=int(raw[1]))
    except (TypeError, ValueError) as err:
        raise ShotPlanError(
            CODE_SERIALIZATION_INVALID, f"{what} has non-integer bounds"
        ) from err
    except ShotReskinRefusal as err:
        raise ShotPlanError(
            CODE_SERIALIZATION_INVALID, f"{what} is not a valid interval: {err}"
        ) from err


def plan_shot_intervals(cuts: Iterable[int], frame_count: int) -> SourcePartition:
    """Build the shot partition from candidate cut frames (MF-END-11.2).

    Cut candidates are frame indices where a new shot STARTS.  The partition
    is rebuilt from ``[0, frame_count)`` with the kept cuts as boundaries, so
    coverage is gap-free and duplicate-free BY CONSTRUCTION; the result is
    then validated by the half-open adapter (``validate_half_open_partition``)
    and any failure refuses with ``SHOT_PLAN_COVERAGE_INVALID`` carrying the
    frozen ``TIMELINE_*`` code.  Candidates equal to 0, outside
    ``(0, frame_count)`` or duplicated are DROPPED and recorded.
    """
    if not isinstance(frame_count, int) or isinstance(frame_count, bool) or frame_count < 1:
        raise ShotPlanError(
            CODE_COVERAGE_INVALID, f"frame_count {frame_count!r} must be int >= 1"
        )
    kept: list[int] = []
    dropped: list[DroppedCut] = []
    seen: set[int] = set()
    for candidate in cuts:
        try:
            value = int(candidate)
        except (TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_COVERAGE_INVALID, f"cut candidate {candidate!r} is not an integer"
            ) from err
        if value == 0:
            dropped.append(DroppedCut(value, "at_zero"))
            continue
        if value < 0 or value >= frame_count:
            dropped.append(DroppedCut(value, "out_of_range"))
            continue
        if value in seen:
            dropped.append(DroppedCut(value, "duplicate"))
            continue
        seen.add(value)
        kept.append(value)
    kept.sort()
    boundaries = [0, *kept, frame_count]
    shots = tuple(
        SourceSpan(start_frame=low, end_frame_exclusive=high)
        for low, high in zip(boundaries, boundaries[1:])
    )
    problems = validate_half_open_partition(
        [(span.start_frame, span.end_frame_exclusive) for span in shots], frame_count
    )
    if problems:
        raise ShotPlanError(
            CODE_COVERAGE_INVALID, f"{pick_partition_code(problems)}: {'; '.join(problems)}"
        )
    return SourcePartition(
        frame_count=frame_count, shots=shots, dropped_cuts=tuple(dropped)
    )


def detect_shot_intervals(
    video_path: str | Path,
    frame_count: int,
    *,
    threshold: float = DEFAULT_SCENE_THRESHOLD,
    min_scene_len_frames: int = DEFAULT_MIN_SCENE_LEN_FRAMES,
) -> SourcePartition:
    """Cut detection REUSING the legacy detector (MF-END-11.2).

    The legacy detector is reached through the additive adapter
    ``app.services.scene_detection.detect_scene_intervals`` (frame-exact
    half-open intervals); the adapter's boundaries are used as CUT
    CANDIDATES only — the partition is rebuilt against the MEASURED
    ``frame_count`` so a detector tail estimate beyond the measured end is
    reconciled (dropped + recorded), never silently kept.
    """
    from app.services.scene_detection import detect_scene_intervals  # noqa: PLC0415

    raw = detect_scene_intervals(
        video_path, threshold=threshold, min_scene_len_frames=min_scene_len_frames
    )
    cuts = [int(span[0]) for span in raw[1:]]
    return plan_shot_intervals(cuts, frame_count)


# ── chunk planning: capability limit + trim/context map (MF-END-11.3) ───────


@dataclass(frozen=True)
class PlannedChunk:
    """One engine call's slice of a shot: exclusive core + rendered context.

    ``core`` is the part exclusively owned by this chunk (exported once);
    ``render`` is what the engine receives (``core`` plus context, clamped to
    the shot — context never crosses a hard cut) and is the ONLY interval that
    must respect the capability frame limit.  ``output_trim_start/end`` are
    the core's bounds in the RENDER's LOCAL frame indices, so context frames
    are never counted twice at export.
    """

    chunk_id: str
    core: SourceSpan
    render: SourceSpan
    output_trim_start: int
    output_trim_end: int
    context_left_frames: int
    context_right_frames: int
    protected_straddles: tuple[str, ...] = ()

    def context_map(self) -> dict[str, Any]:
        """The trim/context map for this chunk (expanded form)."""
        return {
            "chunk_id": self.chunk_id,
            "core": _span_to_json(self.core),
            "render": _span_to_json(self.render),
            "output_trim": [self.output_trim_start, self.output_trim_end],
            "context_left_frames": self.context_left_frames,
            "context_right_frames": self.context_right_frames,
            "protected_straddles": list(self.protected_straddles),
        }

    def to_json(self) -> dict[str, Any]:
        return self.context_map()

    @classmethod
    def from_json(cls, payload: Any) -> PlannedChunk:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "chunk must be an object")
        chunk = cls(
            chunk_id=str(payload.get("chunk_id") or ""),
            core=_span_from_json(payload.get("core"), what="chunk.core"),
            render=_span_from_json(payload.get("render"), what="chunk.render"),
            output_trim_start=int(
                payload.get("output_trim_start", payload.get("output_trim", [0, 0])[0])
            ),
            output_trim_end=int(
                payload.get("output_trim_end", payload.get("output_trim", [0, 0])[1])
            ),
            context_left_frames=int(payload.get("context_left_frames") or 0),
            context_right_frames=int(payload.get("context_right_frames") or 0),
            protected_straddles=tuple(
                str(value) for value in payload.get("protected_straddles") or ()
            ),
        )
        if not chunk.chunk_id:
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "chunk_id missing")
        return chunk


@dataclass(frozen=True)
class PlannedShot:
    """One shot's planned chunks + the audited boundary moves."""

    shot_id: str
    span: SourceSpan
    chunks: tuple[PlannedChunk, ...]
    boundary_shifts: tuple[tuple[int, int], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "span": _span_to_json(self.span),
            "chunks": [chunk.to_json() for chunk in self.chunks],
            "boundary_shifts": [list(pair) for pair in self.boundary_shifts],
        }

    @classmethod
    def from_json(cls, payload: Any) -> PlannedShot:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "shot must be an object")
        chunks_raw = payload.get("chunks")
        if not isinstance(chunks_raw, list) or not chunks_raw:
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "shot.chunks must be a non-empty list")
        shifts_raw = payload.get("boundary_shifts") or []
        shifts: list[tuple[int, int]] = []
        for pair in shifts_raw:
            try:
                shifts.append((int(pair[0]), int(pair[1])))
            except (TypeError, ValueError, IndexError) as err:
                raise ShotPlanError(
                    CODE_SERIALIZATION_INVALID, f"boundary shift {pair!r} is malformed"
                ) from err
        shot = cls(
            shot_id=str(payload.get("shot_id") or ""),
            span=_span_from_json(payload.get("span"), what="shot.span"),
            chunks=tuple(PlannedChunk.from_json(item) for item in chunks_raw),
            boundary_shifts=tuple(shifts),
        )
        if not shot.shot_id:
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "shot_id missing")
        _require_shot_chunk_invariants(shot)
        return shot

    def context_map(self) -> list[dict[str, Any]]:
        return [chunk.context_map() for chunk in self.chunks]

    def covers_span(self) -> bool:
        return sum(chunk.core.frame_count for chunk in self.chunks) == self.span.frame_count


def _require_shot_chunk_invariants(shot: PlannedShot) -> None:
    """Chunk invariants that do not need the capability echo."""
    cursor = shot.span.start_frame
    for chunk in shot.chunks:
        if chunk.core.start_frame != cursor:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID,
                f"chunk {chunk.chunk_id} core starts at {chunk.core.start_frame}, "
                f"expected {cursor}",
            )
        if not shot.span.contains(chunk.render) or not chunk.render.contains(chunk.core):
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID,
                f"chunk {chunk.chunk_id} render {chunk.render.key()} must contain the core "
                f"and stay inside the shot {shot.span.key()}",
            )
        if chunk.context_left_frames != chunk.core.start_frame - chunk.render.start_frame:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"chunk {chunk.chunk_id} context_left mismatch"
            )
        if (
            chunk.context_right_frames
            != chunk.render.end_frame_exclusive - chunk.core.end_frame_exclusive
        ):
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"chunk {chunk.chunk_id} context_right mismatch"
            )
        if chunk.output_trim_start != chunk.context_left_frames:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"chunk {chunk.chunk_id} output_trim_start mismatch"
            )
        if chunk.output_trim_end != chunk.output_trim_start + chunk.core.frame_count:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"chunk {chunk.chunk_id} output_trim_end mismatch"
            )
        cursor = chunk.core.end_frame_exclusive
    if cursor != shot.span.end_frame_exclusive:
        raise ShotPlanError(
            CODE_SERIALIZATION_INVALID,
            f"chunks of {shot.shot_id} end at {cursor}, shot ends at "
            f"{shot.span.end_frame_exclusive}",
        )


def _in_protected(frame: int, protected: Sequence[ProtectedInterval]) -> tuple[str, ...]:
    return tuple(
        interval.span_id
        for interval in protected
        if interval.span.start_frame < frame < interval.span.end_frame_exclusive
    )


def _candidate_offsets(search: int) -> list[int]:
    offsets = [0]
    for step in range(1, search + 1):
        offsets.append(-step)
        offsets.append(step)
    return offsets


def _even_sizes(total: int, parts: int) -> list[int]:
    base, extra = divmod(total, parts)
    return [base + 1] * extra + [base] * (parts - extra)


def plan_shot_chunks(
    shot_span: SourceSpan,
    *,
    shot_id: str,
    capability: CapabilityFrameLimit = DEFAULT_COMFY_CAPABILITY,
    context_frames_per_side: int = 0,
    protected_intervals: Sequence[ProtectedInterval] = (),
    boundary_search_frames: int = 8,
) -> PlannedShot:
    """Split one shot into capability-sized chunks (MF-END-11.3).

    Sizes are as even as possible under ``core_budget = budget - 2*context``
    (context never makes a render exceed the capability).  Interior
    boundaries keep the nearest valid position that is NOT strictly inside a
    protected interval (search bounded by ``boundary_search_frames``); when no
    valid position exists the ideal boundary is kept and the straddled span
    ids are FLAGGED on the affected chunk.  Every boundary move is audited in
    ``boundary_shifts``.
    """
    if not shot_id:
        raise ShotPlanError(CODE_SERIALIZATION_INVALID, "shot_id must be non-empty")
    if not isinstance(capability, CapabilityFrameLimit):
        raise ShotPlanError(CODE_CAPABILITY_INVALID, "capability must be a CapabilityFrameLimit")
    if context_frames_per_side < 0:
        raise ShotPlanError(
            CODE_CONTEXT_INVALID, f"context_frames_per_side {context_frames_per_side} < 0"
        )
    if boundary_search_frames < 0:
        raise ShotPlanError(
            CODE_CONTEXT_INVALID, f"boundary_search_frames {boundary_search_frames} < 0"
        )
    budget = capability.budget()
    core_budget = budget - 2 * context_frames_per_side
    if core_budget < 1:
        raise ShotPlanError(
            CODE_CONTEXT_INVALID,
            f"context {context_frames_per_side}/side leaves no core room under the "
            f"{capability.max_frames}-frame capability (aligned budget {budget})",
        )
    start = shot_span.start_frame
    end = shot_span.end_frame_exclusive
    frame_total = end - start

    chunk_count = -(-frame_total // core_budget)
    sizes = _even_sizes(frame_total, chunk_count)
    ideal: list[int] = [start]
    for size in sizes[:-1]:
        ideal.append(ideal[-1] + size)
    ideal.append(end)

    boundaries: list[int] = [start]
    shifts: list[tuple[int, int]] = []
    straddles: dict[int, tuple[str, ...]] = {}
    for index in range(1, chunk_count):
        ideal_frame = ideal[index]
        chosen: int | None = None
        for offset in _candidate_offsets(boundary_search_frames):
            candidate = ideal_frame + offset
            previous = boundaries[index - 1]
            remaining = end - candidate
            chunks_left = chunk_count - index
            if candidate <= previous or candidate >= end:
                continue
            if candidate - previous > core_budget:
                continue
            if remaining < chunks_left:
                continue
            if -(-remaining // chunks_left) > core_budget:
                continue
            if _in_protected(candidate, protected_intervals):
                continue
            chosen = candidate
            break
        if chosen is None:
            chosen = ideal_frame
            straddles[chosen] = _in_protected(ideal_frame, protected_intervals)
        boundaries.append(chosen)
        if chosen != ideal_frame:
            shifts.append((ideal_frame, chosen))
    boundaries.append(end)

    chunks: list[PlannedChunk] = []
    for index in range(chunk_count):
        core_start = boundaries[index]
        core_end = boundaries[index + 1]
        render_start = max(core_start - context_frames_per_side, start)
        render_end = min(core_end + context_frames_per_side, end)
        core = SourceSpan(start_frame=core_start, end_frame_exclusive=core_end)
        render = SourceSpan(start_frame=render_start, end_frame_exclusive=render_end)
        if render.frame_count > capability.max_frames:
            raise ShotPlanError(
                CODE_CAPABILITY_INVALID,
                f"chunk render {render.key()} holds {render.frame_count} frames, above the "
                f"{capability.max_frames}-frame capability",
            )
        chunks.append(
            PlannedChunk(
                chunk_id=f"{shot_id}:chunk-{index:03d}",
                core=core,
                render=render,
                output_trim_start=core_start - render_start,
                output_trim_end=core_start - render_start + core.frame_count,
                context_left_frames=core_start - render_start,
                context_right_frames=render_end - core_end,
                protected_straddles=straddles.get(core_start, ()),
            )
        )
    shot = PlannedShot(
        shot_id=shot_id, span=shot_span, chunks=tuple(chunks), boundary_shifts=tuple(shifts)
    )
    _require_shot_chunk_invariants(shot)
    return shot


# ── versioned plan artifact (MF-END-11.4) ────────────────────────────────────


@dataclass(frozen=True)
class DetectorFacts:
    """How the cut candidates were obtained (audited, never implied)."""

    mode: str  # "scenedetect" | "override"
    threshold: float
    min_scene_len_frames: int
    raw_scene_interval_count: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("scenedetect", "override"):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, f"detector mode {self.mode!r} unknown")

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "threshold": self.threshold,
            "min_scene_len_frames": self.min_scene_len_frames,
            "raw_scene_interval_count": self.raw_scene_interval_count,
        }

    @classmethod
    def from_json(cls, payload: Any) -> DetectorFacts:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "detector facts must be an object")
        try:
            raw_count = payload.get("raw_scene_interval_count")
            return cls(
                mode=str(payload["mode"]),
                threshold=float(payload["threshold"]),
                min_scene_len_frames=int(payload["min_scene_len_frames"]),
                raw_scene_interval_count=None if raw_count is None else int(raw_count),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"detector facts are malformed: {err}"
            ) from err


@dataclass(frozen=True)
class ShotPlanArtifact:
    """The versioned shot-plan managed artifact for one locked source."""

    plan_artifact_id: str
    source_artifact_id: str
    facts: SourceFacts
    capability: CapabilityFrameLimit
    context_frames_per_side: int
    detector: DetectorFacts
    shots: tuple[PlannedShot, ...]
    dropped_cuts: tuple[DroppedCut, ...]
    plan_version: str = PLAN_SCHEMA_VERSION
    content_sha256: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Re-derive every invariant from the stored values (never trusts flags)."""
        if self.plan_version != PLAN_SCHEMA_VERSION:
            raise ShotPlanError(
                CODE_VERSION_UNSUPPORTED,
                f"plan_version {self.plan_version!r} is not {PLAN_SCHEMA_VERSION!r}",
            )
        if not self.plan_artifact_id or not self.source_artifact_id:
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "artifact ids must be non-empty")
        if not self.shots:
            raise ShotPlanError(CODE_COVERAGE_INVALID, "plan declares no shots")
        problems = validate_half_open_partition(
            [(shot.span.start_frame, shot.span.end_frame_exclusive) for shot in self.shots],
            self.facts.frame_count,
        )
        if problems:
            raise ShotPlanError(
                CODE_COVERAGE_INVALID, f"{pick_partition_code(problems)}: {'; '.join(problems)}"
            )
        for shot in self.shots:
            _require_shot_chunk_invariants(shot)
            for chunk in shot.chunks:
                if chunk.render.frame_count > self.capability.max_frames:
                    raise ShotPlanError(
                        CODE_CAPABILITY_INVALID,
                        f"chunk {chunk.chunk_id} render holds {chunk.render.frame_count} "
                        f"frames, above the {self.capability.max_frames}-frame capability",
                    )

    def timebase(self) -> TimebaseFacts:
        """The frozen-contract timebase view of the measured facts."""
        return self.facts.timebase_facts()

    def to_json(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "plan_artifact_id": self.plan_artifact_id,
            "source_artifact_id": self.source_artifact_id,
            "source": {
                "sha256": self.facts.source_sha256,
                "size_bytes": self.facts.file_size_bytes,
            },
            "frame_count": self.facts.frame_count,
            "timebase": self.facts.timebase_facts().model_dump(mode="json"),
            "source_facts": self.facts.to_json(),
            "capability": self.capability.to_json(),
            "context_frames_per_side": self.context_frames_per_side,
            "detector": self.detector.to_json(),
            "shots": [shot.to_json() for shot in self.shots],
            "dropped_cuts": [cut.to_json() for cut in self.dropped_cuts],
            "content_sha256": self.content_sha256,
        }

    def digest_payload(self) -> dict[str, Any]:
        payload = self.to_json()
        payload.pop("content_sha256")
        return payload

    def computed_digest(self) -> str:
        return payload_sha256(self.digest_payload())

    def verify_digest(self) -> None:
        if not self.content_sha256:
            raise ShotPlanError(CODE_DIGEST_MISMATCH, "plan is not sealed (empty content digest)")
        if self.content_sha256 != self.computed_digest():
            raise ShotPlanError(
                CODE_DIGEST_MISMATCH,
                "plan content digest mismatch (payload was modified after sealing)",
            )

    @classmethod
    def from_json(cls, payload: Any) -> ShotPlanArtifact:
        if not isinstance(payload, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "plan payload must be an object")
        if payload.get("plan_version") != PLAN_SCHEMA_VERSION:
            raise ShotPlanError(
                CODE_VERSION_UNSUPPORTED,
                f"plan_version {payload.get('plan_version')!r} is not {PLAN_SCHEMA_VERSION!r}",
            )
        required = (
            "plan_artifact_id",
            "source_artifact_id",
            "source",
            "frame_count",
            "timebase",
            "source_facts",
            "capability",
            "context_frames_per_side",
            "detector",
            "shots",
            "content_sha256",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, f"plan payload missing keys: {missing}")
        facts = SourceFacts.from_json(payload["source_facts"])
        source_block = payload.get("source")
        if not isinstance(source_block, dict):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "plan.source must be an object")
        if (
            str(source_block.get("sha256")) != facts.source_sha256
            or int(source_block.get("size_bytes", -1)) != facts.file_size_bytes
        ):
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID,
                "plan.source does not match source_facts (sha/size)",
            )
        if int(payload.get("frame_count", -1)) != facts.frame_count:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, "plan.frame_count does not match source_facts"
            )
        try:
            timebase = TimebaseFacts.model_validate(payload["timebase"])
        except ValueError as err:
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, f"timebase block invalid: {err}"
            ) from err
        if timebase != facts.timebase_facts():
            raise ShotPlanError(
                CODE_SERIALIZATION_INVALID, "plan.timebase does not match source_facts"
            )
        shots_raw = payload.get("shots")
        if not isinstance(shots_raw, list):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "plan.shots must be a list")
        dropped_raw = payload.get("dropped_cuts") or []
        if not isinstance(dropped_raw, list):
            raise ShotPlanError(CODE_SERIALIZATION_INVALID, "plan.dropped_cuts must be a list")
        artifact = cls(
            plan_artifact_id=str(payload["plan_artifact_id"]),
            source_artifact_id=str(payload["source_artifact_id"]),
            facts=facts,
            capability=CapabilityFrameLimit.from_json(payload["capability"]),
            context_frames_per_side=int(payload["context_frames_per_side"]),
            detector=DetectorFacts.from_json(payload["detector"]),
            shots=tuple(PlannedShot.from_json(item) for item in shots_raw),
            dropped_cuts=tuple(DroppedCut.from_json(item) for item in dropped_raw),
            plan_version=str(payload["plan_version"]),
            content_sha256=str(payload["content_sha256"]),
        )
        artifact.verify_digest()
        return artifact


def build_shot_plan(
    source_path: str | Path,
    *,
    plan_artifact_id: str = "shot-plan",
    source_artifact_id: str = "source",
    capability: CapabilityFrameLimit = DEFAULT_COMFY_CAPABILITY,
    context_frames_per_side: int = 0,
    protected_intervals: Sequence[ProtectedInterval] = (),
    threshold: float = DEFAULT_SCENE_THRESHOLD,
    min_scene_len_frames: int = DEFAULT_MIN_SCENE_LEN_FRAMES,
    boundary_search_frames: int = 8,
    deep_count: bool = False,
    facts: SourceFacts | None = None,
    cuts: Sequence[int] | None = None,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> ShotPlanArtifact:
    """Build the sealed shot-plan artifact for one source (MF-END-11.1–4).

    ``facts`` and ``cuts`` are injection seams for unit rows ONLY; the
    acceptance path calls the real probe + real detector (defaults), which is
    what the evidence harness exercises.
    """
    measured = (
        facts
        if facts is not None
        else probe_source_facts(source_path, deep_count=deep_count, timeout=timeout)
    )
    if cuts is None:
        partition = detect_shot_intervals(
            source_path,
            measured.frame_count,
            threshold=threshold,
            min_scene_len_frames=min_scene_len_frames,
        )
        detector = DetectorFacts(
            mode="scenedetect",
            threshold=threshold,
            min_scene_len_frames=min_scene_len_frames,
            raw_scene_interval_count=len(partition.shots),
        )
    else:
        partition = plan_shot_intervals(cuts, measured.frame_count)
        detector = DetectorFacts(
            mode="override",
            threshold=threshold,
            min_scene_len_frames=min_scene_len_frames,
            raw_scene_interval_count=None,
        )
    shots = tuple(
        plan_shot_chunks(
            span,
            shot_id=f"shot-{index:04d}",
            capability=capability,
            context_frames_per_side=context_frames_per_side,
            protected_intervals=protected_intervals,
            boundary_search_frames=boundary_search_frames,
        )
        for index, span in enumerate(partition.shots)
    )
    artifact = ShotPlanArtifact(
        plan_artifact_id=plan_artifact_id,
        source_artifact_id=source_artifact_id,
        facts=measured,
        capability=capability,
        context_frames_per_side=context_frames_per_side,
        detector=detector,
        shots=shots,
        dropped_cuts=partition.dropped_cuts,
    )
    return replace(artifact, content_sha256=artifact.computed_digest())


# ── invalidation: the plan is valid only for the source it measured ──────────


@dataclass(frozen=True)
class InvalidationVerdict:
    """Plan-vs-source verdict (typed; ``valid`` is the only good status)."""

    status: str
    reasons: tuple[str, ...]
    expected_sha256: str
    measured_sha256: str | None

    @property
    def valid(self) -> bool:
        return self.status == INVALIDATION_VALID

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "expected_sha256": self.expected_sha256,
            "measured_sha256": self.measured_sha256,
        }


def _as_sealed_artifact(plan: ShotPlanArtifact | dict[str, Any]) -> ShotPlanArtifact:
    if isinstance(plan, ShotPlanArtifact):
        plan.verify_digest()
        return plan
    return ShotPlanArtifact.from_json(plan)


def check_plan_validity(
    plan: ShotPlanArtifact | dict[str, Any], *, current_facts: SourceFacts
) -> InvalidationVerdict:
    """Compare the sealed plan against freshly measured source facts.

    A changed source digest is ``stale_source_changed``; a changed measured
    timebase (frame count / fps rationals / classification) with the same
    digest is ``stale_timebase_changed`` (defence in depth — a facts row that
    contradicts the bytes must not resurrect the plan).
    """
    artifact = _as_sealed_artifact(plan)
    pinned = artifact.facts
    if current_facts.source_sha256 != pinned.source_sha256:
        return InvalidationVerdict(
            INVALIDATION_SOURCE_CHANGED,
            (CODE_SOURCE_CHANGED,),
            pinned.source_sha256,
            current_facts.source_sha256,
        )
    if (
        current_facts.frame_count != pinned.frame_count
        or current_facts.fps_num != pinned.fps_num
        or current_facts.fps_den != pinned.fps_den
        or current_facts.fps_classification != pinned.fps_classification
    ):
        return InvalidationVerdict(
            INVALIDATION_TIMEBASE_CHANGED,
            (CODE_TIMEBASE_CHANGED,),
            pinned.source_sha256,
            current_facts.source_sha256,
        )
    return InvalidationVerdict(
        INVALIDATION_VALID, (CODE_VALID,), pinned.source_sha256, current_facts.source_sha256
    )


def invalidate_if_source_changed(
    plan: ShotPlanArtifact | dict[str, Any],
    source_path: str | Path,
    *,
    deep_count: bool = False,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> InvalidationVerdict:
    """Re-probe the source from disk and return the typed verdict (MF-END-11.4)."""
    current = probe_source_facts(source_path, deep_count=deep_count, timeout=timeout)
    return check_plan_validity(plan, current_facts=current)


def require_current_plan(
    plan: ShotPlanArtifact | dict[str, Any],
    *,
    source_path: str | Path | None = None,
    current_facts: SourceFacts | None = None,
    deep_count: bool = False,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> ShotPlanArtifact:
    """Return the sealed plan ONLY when it is still valid; otherwise refuse."""
    if current_facts is None:
        if source_path is None:
            raise ShotPlanError(
                CODE_SOURCE_MISSING, "require_current_plan needs current_facts or source_path"
            )
        current_facts = probe_source_facts(source_path, deep_count=deep_count, timeout=timeout)
    artifact = _as_sealed_artifact(plan)
    verdict = check_plan_validity(artifact, current_facts=current_facts)
    if not verdict.valid:
        raise ShotPlanError(
            verdict.reasons[0],
            f"plan {artifact.plan_artifact_id} is stale ({verdict.status}); "
            "the plan must be rebuilt for the current source",
        )
    return artifact
