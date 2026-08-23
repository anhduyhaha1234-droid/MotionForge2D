"""Managed video import service (S05-T02) — the ANALYZE_MEDIA durable job.

Implements the approved import path of ``docs/architecture/
VIDEO_PREFLIGHT_CONTRACT.md`` §6 with the resolutions from ``docs/
architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md``:

- **Submit** (:func:`submit_import`) creates the durable ``ANALYZE_MEDIA``
  Job with an **owner-scoped** idempotency key: the VideoItem owner is part
  of the logical identity so the same source bytes imported into two
  different VideoItems create two independent Jobs/effect sets.  The shape is
  ``ANALYZE_MEDIA:video_item:<video_item_id>:<source_sha256>:<generation>``
  when a preflight hash is supplied, and ``ANALYZE_MEDIA:video_item:
  <video_item_id>:<generation>`` when it is not (no content identity is
  claimed before the hash exists — the worker records the canonical SHA
  after the streaming copy).  A completed duplicate returns the existing
  Job; an active duplicate raises ``IdempotencyKeyInUse``.
- **Ownership gate** (:func:`_validate_ownership`): before Job creation and
  again at publication the active VideoItem must belong to the stated
  Project and that Project must belong to the stated Workspace; a
  cross-workspace/cross-project combination is rejected before any managed
  write (no artifact/owner/job side effects).
- **Probe phase** runs the bounded ffprobe (30s, list-args, JSON, discovery
  only via ``app.services.ffmpeg_utils``), builds the schema-versioned
  canonical probe payload (§3) and enforces the V1 media decision: MP4
  container, H.264/HEVC video, no HDR/10-bit, positive
  duration/width/height.  ``NO_AUDIO_STREAM`` is recorded as a warning and
  accepted.  Since S11 (``docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md``,
  B5 resolution), a non-AAC **first** audio stream is ALSO accepted with an
  explicit ``UNSUPPORTED_AUDIO_CODEC`` warning — never rejected just for the
  audio codec; the S11 remux engine (ATTACH_ORIGINAL_AUDIO) owns the AAC
  transcode.  Only the container / video-codec / HDR gates remain
  fail-closed.  The probe result is persisted as the step checkpoint so
  retry reuses it instead of re-probing (§6.3).
- **Copy phase** streams the source into the managed staging area with
  ``ManagedRoot.atomic_write_stream`` and ``expected_sha256`` (the preflight
  hash when available): SHA-256 and size are computed during the copy and a
  mismatch aborts before publish (``CHECKSUM_MISMATCH``).  A free-disk guard
  (source size * 1.1 + 1 GiB reserve) runs before any byte is copied
  (``INSUFFICIENT_DISK``).  Leftover ``.staging`` partials — including a
  predecessor Job's — are garbage-collected on re-run.
- **Publish phase** atomically moves the staged file into the final managed
  path ``artifacts/<workspace_id>/video/<job_id>/<step_code>/<name>`` and
  then, in **one transaction**, upserts the ``artifact`` row
  (``kind='video'``, ``state='ready'``, sha256, size, relative path) with a
  deterministic id, upserts the ``artifact_owner`` link (purpose ``source``)
  and writes the ``video_item`` probe columns + ``source_artifact_id``.
  A DB failure removes the just-published file (no orphan); a replay finds
  the ready row and skips publication (no duplicate effects).
- **Cancellation/failure** cleanup: every phase observes
  ``ctx.is_cancelled()`` and removes its staging/partial files before
  raising ``CANCELLED``; the worker drains to terminal ``cancelled`` with no
  final outputs.
- **Path containment**: every managed path is validated by ``ManagedRoot``
  (normalized relative path, no ``..``, no absolute/drive/UNC paths,
  symlink-escape rejection).  ``ManagedPathError`` maps to the stable
  ``PATH_CONTAINMENT`` envelope.  The original source is opened read-only
  and is never mutated or deleted.

No new schema: the durable write surface is exactly the existing
``artifact``, ``artifact_owner`` and ``video_item`` tables.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.artifacts import (
    ArtifactWriteError,
    ManagedPathError,
    ManagedRoot,
    hash_file,
)
from app.persistence.jobs import StepInput
from app.persistence.models import Artifact, ArtifactOwner, Project, VideoItem
from app.services.ffmpeg_utils import find_ffprobe
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "ARTIFACT_PURPOSE_SOURCE",
    "COPY_STEP_CODE",
    "CODE_CANCELLED",
    "CODE_CHECKSUM_MISMATCH",
    "CODE_HDR_UNSUPPORTED",
    "CODE_INPUT_MISSING",
    "CODE_INPUT_UNREADABLE",
    "CODE_INSUFFICIENT_DISK",
    "CODE_INVALID_VIDEO_METADATA",
    "CODE_NO_AUDIO_STREAM",
    "CODE_NO_VIDEO_STREAM",
    "CODE_OWNERSHIP_MISMATCH",
    "CODE_PATH_CONTAINMENT",
    "CODE_PROBE_BINARY_NOT_FOUND",
    "CODE_PROBE_JSON_PARSE_ERROR",
    "CODE_PROBE_NONZERO_EXIT",
    "CODE_PROBE_TIMEOUT",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_PUBLICATION_FAILED",
    "CODE_UNSUPPORTED_AUDIO_CODEC",
    "CODE_UNSUPPORTED_CODEC",
    "CODE_UNSUPPORTED_CONTAINER",
    "CODE_VIDEO_ITEM_NOT_FOUND",
    "DISK_RESERVE_BYTES",
    "DISK_SAFETY_MARGIN",
    "ImportSubmitResult",
    "JOB_TYPE_ANALYZE_MEDIA",
    "PROBE_SCHEMA_VERSION",
    "PROBE_TIMEOUT_SECONDS",
    "VideoImportError",
    "VIETNAMESE_ACTIONS",
    "analyze_media_handler",
    "analyze_media_steps",
    "probe_source",
    "register_analyze_media_handler",
    "submit_import",
]

#: Stable job type approved by DURABLE_JOB_CONTRACT §3.
JOB_TYPE_ANALYZE_MEDIA = "ANALYZE_MEDIA"

#: The single sync step that executes the whole import (probe→copy→publish).
COPY_STEP_CODE = "import"

#: Schema version of the canonical probe payload (contract §3.1).
PROBE_SCHEMA_VERSION = 1

#: Probe step timeout (seconds) — kept from the current helper, worker
#: context (contract §5.3: probe step 30s).
PROBE_TIMEOUT_SECONDS = 30

#: Free-disk guard (V1 PM decision B2): source size * margin + reserve.
DISK_SAFETY_MARGIN = 1.1

#: Minimum free-disk reserve (1 GiB).
DISK_RESERVE_BYTES = 1024 * 1024 * 1024

#: Artifact-owner purpose for a VideoItem's source media.
ARTIFACT_PURPOSE_SOURCE = "source"

# ── Stable error codes (VIDEO_PREFLIGHT_CONTRACT §7 + V1 PM decisions) ──────

CODE_INPUT_MISSING = "INPUT_MISSING"
CODE_INPUT_UNREADABLE = "INPUT_UNREADABLE"
CODE_NO_VIDEO_STREAM = "NO_VIDEO_STREAM"
CODE_UNSUPPORTED_CONTAINER = "UNSUPPORTED_CONTAINER"
CODE_UNSUPPORTED_CODEC = "UNSUPPORTED_CODEC"
CODE_UNSUPPORTED_AUDIO_CODEC = "UNSUPPORTED_AUDIO_CODEC"
CODE_NO_AUDIO_STREAM = "NO_AUDIO_STREAM"
CODE_PROBE_TIMEOUT = "PROBE_TIMEOUT"
CODE_PROBE_BINARY_NOT_FOUND = "PROBE_BINARY_NOT_FOUND"
CODE_PROBE_NONZERO_EXIT = "PROBE_NONZERO_EXIT"
CODE_PROBE_JSON_PARSE_ERROR = "PROBE_JSON_PARSE_ERROR"
CODE_CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
CODE_INSUFFICIENT_DISK = "INSUFFICIENT_DISK"
CODE_HDR_UNSUPPORTED = "HDR_UNSUPPORTED"
CODE_INVALID_VIDEO_METADATA = "INVALID_VIDEO_METADATA"
CODE_PATH_CONTAINMENT = "PATH_CONTAINMENT"
CODE_VIDEO_ITEM_NOT_FOUND = "VIDEO_ITEM_NOT_FOUND"
CODE_PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
CODE_OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"
CODE_PUBLICATION_FAILED = "PUBLICATION_FAILED"
CODE_CANCELLED = "CANCELLED"

#: Vietnamese suggested actions (PRD §9 Step 5 acceptance / FR-08) for every
#: stable code this service raises.
VIETNAMESE_ACTIONS: dict[str, str] = {
    CODE_INPUT_MISSING: (
        "Tệp nguồn không tồn tại hoặc đã bị di chuyển. Vui lòng chọn lại tệp video."
    ),
    CODE_INPUT_UNREADABLE: (
        "Không thể đọc tệp nguồn (thiếu quyền hoặc tệp đang bị khóa). Kiểm tra "
        "quyền truy cập và thử lại."
    ),
    CODE_NO_VIDEO_STREAM: (
        "Tệp không chứa luồng video. Tệp này có thể không phải video hợp lệ; "
        "hãy chọn tệp video khác."
    ),
    CODE_UNSUPPORTED_CONTAINER: (
        "Định dạng container chưa được hỗ trợ. Chỉ hỗ trợ MP4; hãy chuyển đổi tệp "
        "sang MP4 (H.264/HEVC + AAC) rồi thử lại."
    ),
    CODE_UNSUPPORTED_CODEC: (
        "Codec video chưa được hỗ trợ. Chỉ hỗ trợ H.264 (AVC) và HEVC (H.265); "
        "hãy chuyển đổi codec rồi thử lại."
    ),
    CODE_UNSUPPORTED_AUDIO_CODEC: (
        "Âm thanh không phải AAC nhưng vẫn được import kèm cảnh báo; khi chạy "
        "ATTACH_ORIGINAL_AUDIO hệ thống sẽ tự transcode sang AAC — bạn không cần "
        "chuyển đổi thủ công."
    ),
    CODE_NO_AUDIO_STREAM: (
        "Video không có âm thanh. Vẫn import được nhưng output sẽ không có audio "
        "(PRD §9 Step 4/FR-07)."
    ),
    CODE_PROBE_TIMEOUT: (
        "Quá thời gian phân tích. Hãy thử lại; nếu tệp quá lớn, hãy kiểm tra định "
        "dạng hoặc tốc độ ổ đĩa."
    ),
    CODE_PROBE_BINARY_NOT_FOUND: (
        "Không tìm thấy ffprobe. Cài đặt FFmpeg (winget install Gyan.FFmpeg) hoặc "
        "đặt MOTIONFORGE_FFMPEG/MOTIONFORGE_FFPROBE rồi thử lại."
    ),
    CODE_PROBE_NONZERO_EXIT: (
        "ffprobe không đọc được tệp. Tệp có thể bị hỏng hoặc không phải video hợp "
        "lệ; hãy kiểm tra lại tệp nguồn."
    ),
    CODE_PROBE_JSON_PARSE_ERROR: (
        "Kết quả phân tích không hợp lệ. Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi "
        "hệ thống kèm tệp nguồn."
    ),
    CODE_CHECKSUM_MISMATCH: (
        "Kiểm tra toàn vẹn tệp thất bại (checksum không khớp). Nguồn có thể bị "
        "thay đổi hoặc hỏng; hãy kiểm tra lại tệp nguồn trước khi import."
    ),
    CODE_INSUFFICIENT_DISK: (
        "Không đủ dung lượng ổ đĩa cho tệp nguồn cộng với vùng dự phòng 1 GiB. "
        "Giải phóng dung lượng trên ổ lưu trữ rồi thử lại."
    ),
    CODE_HDR_UNSUPPORTED: (
        "Đầu vào HDR/10-bit chưa được hỗ trợ ở phiên bản V1. Hãy chuyển đổi tệp "
        "sang SDR 8-bit trước khi import."
    ),
    CODE_INVALID_VIDEO_METADATA: (
        "Thông số video không hợp lệ (cần thời lượng và kích thước dương). Hãy "
        "kiểm tra lại tệp nguồn."
    ),
    CODE_PATH_CONTAINMENT: (
        "Đường dẫn tệp không hợp lệ hoặc cố thoát khỏi vùng lưu trữ được quản lý. "
        "Hãy kiểm tra lại tên tệp nguồn."
    ),
    CODE_VIDEO_ITEM_NOT_FOUND: (
        "Video Item không tồn tại hoặc đã bị lưu trữ. Hãy tạo lại Video Item rồi "
        "thử import."
    ),
    CODE_PROJECT_NOT_FOUND: (
        "Project không tồn tại hoặc đã bị lưu trữ. Hãy kiểm tra Project và thử lại."
    ),
    CODE_OWNERSHIP_MISMATCH: (
        "Video Item không thuộc Project/Workspace được khai báo. Hãy chọn đúng "
        "Project và Workspace chứa Video Item rồi thử lại."
    ),
    CODE_PUBLICATION_FAILED: (
        "Không thể công bố artifact nguồn. Hãy thử lại; nếu lỗi lặp lại, hãy báo "
        "lỗi hệ thống kèm Job id."
    ),
    CODE_CANCELLED: "Import đã bị hủy theo yêu cầu.",
}


class VideoImportError(Exception):
    """A stable, actionable import failure (contract §7 / §10.1).

    ``code`` is the machine-readable stable error code; ``action`` is the
    Vietnamese suggested action; ``location``/``details`` carry structured
    context for the error envelope.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.location = location
        self.details = details or {}

    def action(self) -> str:
        """The Vietnamese suggested action for this error's code."""
        return VIETNAMESE_ACTIONS.get(
            self.code, "Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống."
        )


@dataclass(frozen=True)
class ImportSubmitResult:
    """Result of :func:`submit_import` — the durable Job id and reuse flag."""

    job_id: str
    reused: bool


# ── Small numeric helpers ────────────────────────────────────────────────────


def _to_int(value: Any) -> int:
    """Best-effort int conversion (0 on garbage, matching current probe)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    """Best-effort float conversion (0.0 on garbage)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rational(value: Any) -> dict[str, int]:
    """Parse an ffprobe rational string ``"num/den"`` into ``{num, den}``.

    A missing/garbage/zero-denominator value yields ``{"num": 0, "den": 1}``
    (callers must validate positivity before persisting — the ``video_item``
    CHECK requires ``fps_num > 0`` and ``fps_den > 0``).
    """
    raw = str(value or "")
    if "/" in raw:
        num_s, den_s = raw.split("/", 1)
        try:
            num = int(num_s)
        except ValueError:
            num = 0
        try:
            den = int(den_s)
        except ValueError:
            den = 0
        if den != 0:
            return {"num": num, "den": den}
    return {"num": 0, "den": 1}


def _sanitize_name(name: str) -> str:
    """Reduce an arbitrary source filename to a safe managed path component.

    Path components (including ``..``) are stripped by taking the basename;
    any remaining unsafe characters become ``_``; leading/trailing dots are
    removed; an empty result falls back to ``source``.  The final component
    is still validated by ``ManagedRoot`` containment.
    """
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = base.strip("._")
    if not base:
        base = "source"
    if "." not in base:
        base = f"{base}.mp4"
    return base


def _ffprobe_version(ffprobe: str) -> str:
    """Best-effort ffprobe version string (bounded, never raises)."""
    try:
        result = subprocess.run(
            [ffprobe, "-version"], capture_output=True, text=True, timeout=5
        )
    except Exception:  # noqa: BLE001 - version is display-only metadata
        return "unknown"
    output = result.stdout or result.stderr
    first = output.splitlines()[0].strip() if output else ""
    match = re.match(r"ffprobe version (\S+)", first)
    return match.group(1) if match else first


def _is_hdr_or_10bit(pix_fmt: str, color_transfer: str) -> bool:
    """True for HDR/10-bit inputs, which V1 rejects (PM decision #6).

    10/12-bit pixel formats are named ``...10le``/``...12be`` etc.; the
    bit-depth digits are not the suffix, so a regex matches the depth +
    endianness tail.
    """
    if re.search(r"(?:10|12)(?:le|be)$", pix_fmt):
        return True
    return color_transfer in ("smpte2084", "arib-std-b67")


# ── Probe (contract §5 + §3) ─────────────────────────────────────────────────


def probe_source(
    source_path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Run the bounded probe on *source_path* and return the canonical payload.

    The probe is read-only: it never copies bytes, never registers artifacts
    and never mutates the source (contract §2 boundary rule AC2).  It
    enforces the V1 media decision (PM decisions) and fails closed with
    stable ``VideoImportError`` codes — never a bare ``RuntimeError``.

    Raises:
        VideoImportError: with a stable code from the contract §7 taxonomy
            plus the V1-specific codes (``INSUFFICIENT_DISK`` is not raised
            here — it is a copy-phase guard).
    """
    source = Path(source_path)
    if not source.exists():
        raise VideoImportError(
            CODE_INPUT_MISSING,
            f"source file does not exist: {source}",
            location="source file path",
        )
    if not os.access(source, os.R_OK):
        raise VideoImportError(
            CODE_INPUT_UNREADABLE,
            f"source file is not readable: {source}",
            location="source file path",
        )

    try:
        ffprobe = find_ffprobe()
    except FileNotFoundError as exc:
        raise VideoImportError(
            CODE_PROBE_BINARY_NOT_FOUND,
            "ffprobe binary not found by app.services.ffmpeg_utils",
            location="toolchain",
        ) from exc

    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoImportError(
            CODE_PROBE_TIMEOUT,
            f"ffprobe exceeded the {PROBE_TIMEOUT_SECONDS}s bounded budget",
            location="probe step",
        ) from exc
    if result.returncode != 0:
        raise VideoImportError(
            CODE_PROBE_NONZERO_EXIT,
            f"ffprobe exited {result.returncode}: {(result.stderr or '').strip()[:300]}",
            location="probe step",
        )
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise VideoImportError(
            CODE_PROBE_JSON_PARSE_ERROR,
            "ffprobe stdout is not valid JSON",
            location="probe step",
        ) from exc

    streams = data.get("streams") or []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    if video is None:
        raise VideoImportError(
            CODE_NO_VIDEO_STREAM,
            "container has no video stream",
            location="streams",
        )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    fmt = data.get("format") or {}

    # ── V1 media decision (PM decisions #1/#2/#6/#7) ───────────────────────
    format_name = str(fmt.get("format_name") or "")
    format_tokens = [token.strip() for token in format_name.split(",")]
    if "mp4" not in format_tokens:
        raise VideoImportError(
            CODE_UNSUPPORTED_CONTAINER,
            f"container {format_name!r} is not in the supported set (MP4 only)",
            location="container.format_name",
            details={"format_name": format_name},
        )
    codec_name = str(video.get("codec_name") or "")
    if codec_name not in ("h264", "hevc"):
        raise VideoImportError(
            CODE_UNSUPPORTED_CODEC,
            f"video codec {codec_name!r} is not H.264/HEVC",
            location="video_stream.codec_name",
            details={"codec_name": codec_name},
        )
    # Warnings accumulate in probe order; the audio gates below append to
    # this list (S11 B5: non-AAC first audio is a warning, not a rejection).
    warnings: list[dict[str, Any]] = []
    audio_payload: dict[str, Any] | None = None
    if audio is not None:
        # S11 B5 resolution (ORIGINAL_AUDIO_REMUX_CONTRACT §2): the FIRST
        # audio stream is canonical and is accepted regardless of codec.
        # A non-AAC first audio stream is an explicit WARNING, never a
        # rejection — the S11 remux engine (ATTACH_ORIGINAL_AUDIO, T01B)
        # transcodes it to AAC downstream.  Import itself does not
        # transcode or mutate the source bytes (contract §4).
        audio_codec = str(audio.get("codec_name") or "")
        audio_payload = {
            "index": _to_int(audio.get("index")),
            "codec_name": audio_codec,
            "codec_long_name": str(audio.get("codec_long_name") or ""),
            "channels": _to_int(audio.get("channels")),
            "sample_rate": _to_int(audio.get("sample_rate")),
            "duration_seconds": _to_float(audio.get("duration")),
        }
        if audio_codec != "aac":
            warnings.append(
                {
                    "code": CODE_UNSUPPORTED_AUDIO_CODEC,
                    "severity": "warning",
                    "location": "audio_stream.codec_name",
                    "reason": (
                        f"first audio stream codec {audio_codec!r} is not AAC; "
                        "accepted with warning per ORIGINAL_AUDIO_REMUX_CONTRACT "
                        "(S11 B5 resolution) — ATTACH_ORIGINAL_AUDIO will "
                        "transcode to AAC"
                    ),
                    "action": VIETNAMESE_ACTIONS[CODE_UNSUPPORTED_AUDIO_CODEC],
                    "details": {
                        "audio_codec": audio_codec,
                        "audio_stream_index": audio_payload["index"],
                        "channels": audio_payload["channels"],
                        "sample_rate": audio_payload["sample_rate"],
                    },
                }
            )
    pix_fmt = str(video.get("pix_fmt") or "")
    color_transfer = str(video.get("color_transfer") or "")
    if _is_hdr_or_10bit(pix_fmt, color_transfer):
        raise VideoImportError(
            CODE_HDR_UNSUPPORTED,
            f"HDR/10-bit input rejected in V1 (pix_fmt={pix_fmt!r}, "
            f"color_transfer={color_transfer!r})",
            location="video_stream.pix_fmt",
            details={"pix_fmt": pix_fmt, "color_transfer": color_transfer},
        )

    width = _to_int(video.get("width"))
    height = _to_int(video.get("height"))
    duration = _to_float(fmt.get("duration") or video.get("duration"))
    r_rate = _rational(video.get("r_frame_rate"))
    if width <= 0 or height <= 0 or duration <= 0:
        raise VideoImportError(
            CODE_INVALID_VIDEO_METADATA,
            "structural minimums not met: positive duration and width/height required",
            location="video_stream",
            details={"width": width, "height": height, "duration_seconds": duration},
        )
    if r_rate["num"] <= 0 or r_rate["den"] <= 0:
        # The video_item CHECK requires fps_num/fps_den > 0; reject before a
        # confusing DB CHECK violation at publish time.
        raise VideoImportError(
            CODE_INVALID_VIDEO_METADATA,
            "invalid frame-rate rational",
            location="video_stream.r_frame_rate",
            details={"r_frame_rate": r_rate},
        )

    avg_rate = _rational(video.get("avg_frame_rate"))
    fps_nominal = r_rate["num"] / r_rate["den"]
    fps_avg = avg_rate["num"] / avg_rate["den"] if avg_rate["den"] else 0.0
    fps_classification = (
        "CFR" if (avg_rate == r_rate and r_rate["num"] != 0) else "VFR"
    )

    if audio is None:
        audio_payload = None
        warnings.append(
            {
                "code": CODE_NO_AUDIO_STREAM,
                "severity": "warning",
                "location": "audio_stream",
                "reason": "no audio stream present",
                "action": VIETNAMESE_ACTIONS[CODE_NO_AUDIO_STREAM],
            }
        )

    return {
        "schema_version": PROBE_SCHEMA_VERSION,
        "probe_tool": {"name": "ffprobe", "version": _ffprobe_version(ffprobe)},
        "container": {
            "format_name": format_name,
            "format_long_name": str(fmt.get("format_long_name") or ""),
            "file_size_bytes": _to_int(fmt.get("size")),
            "duration_seconds": duration,
            "start_time_seconds": _to_float(fmt.get("start_time")),
        },
        "video_stream": {
            "index": _to_int(video.get("index")),
            "codec_name": codec_name,
            "codec_long_name": str(video.get("codec_long_name") or ""),
            "width": width,
            "height": height,
            "r_frame_rate": r_rate,
            "avg_frame_rate": avg_rate,
            "fps_nominal": round(fps_nominal, 3),
            "fps_avg": round(fps_avg, 3),
            "fps_classification": fps_classification,
            "duration_seconds": duration,
            "nb_frames": _to_int(video.get("nb_frames")),
            "pix_fmt": pix_fmt,
            "color_transfer": color_transfer,
        },
        "audio_stream": audio_payload,
        "has_audio": audio is not None,
        "warnings": warnings,
        "sha256": expected_sha256,
        "file_path": str(source.resolve()),
    }


# ── Disk guard (V1 PM decision #2) ───────────────────────────────────────────


def _disk_free_bytes(root: Path) -> int:
    """Free bytes on the filesystem containing *root* (monkeypatch seam)."""
    return shutil.disk_usage(root).free


def _check_disk_space(managed: ManagedRoot, source_path: Path) -> None:
    """Require source*1.1 + 1 GiB free on the managed root before copying."""
    try:
        size = source_path.stat().st_size
        free = _disk_free_bytes(managed.root)
    except OSError as exc:
        raise VideoImportError(
            CODE_INPUT_UNREADABLE,
            f"cannot stat source or managed root: {exc}",
            location="source file path",
        ) from exc
    required = int(size * DISK_SAFETY_MARGIN) + DISK_RESERVE_BYTES
    if free < required:
        raise VideoImportError(
            CODE_INSUFFICIENT_DISK,
            f"free disk {free} bytes < required {required} bytes "
            f"(source {size} * {DISK_SAFETY_MARGIN} + {DISK_RESERVE_BYTES} reserve)",
            location="managed root",
            details={
                "free_bytes": free,
                "required_bytes": required,
                "source_size_bytes": size,
                "safety_margin": DISK_SAFETY_MARGIN,
                "reserve_bytes": DISK_RESERVE_BYTES,
            },
        )


# ── Staging / final paths ────────────────────────────────────────────────────


def _managed_for(ctx: WorkerContext) -> ManagedRoot:
    """ManagedRoot bound to the Job's manifest managed root."""
    return ManagedRoot(Path(str(ctx.input_manifest.get("managed_root") or "artifacts")))


def _staging_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the staged copy (contract §9.1)."""
    return f"staging/{ctx.job_id}/{ctx.step_code}/{name}"


def _final_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the published artifact (contract §9.2)."""
    workspace_id = str(ctx.input_manifest.get("workspace_id") or "default")
    return f"artifacts/{workspace_id}/video/{ctx.job_id}/{ctx.step_code}/{name}"


def _artifact_id(ctx: WorkerContext, final_rel: str) -> str:
    """Deterministic artifact id for (job, step, path) — replay-safe (§8.3)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"analyze-media:{ctx.job_id}:{final_rel}"))


def _predecessor_job_id(ctx: WorkerContext) -> str | None:
    """The predecessor Job id of this Job (retry/restart chain, §6.4)."""
    if ctx.session_factory is None:
        return None
    try:
        from app.persistence.jobs import JobRepository

        with ctx.session_factory() as session:
            return JobRepository(session).get_job(ctx.job_id).predecessor_job_id
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        return None


def _cleanup_staging_partials(ctx: WorkerContext, managed: ManagedRoot) -> None:
    """Remove leftover ``.staging`` partial files for this Job and its
    predecessor (crash leftovers are never treated as published content)."""
    root = managed.root
    step_code = ctx.step_code
    dirs = [root / "staging" / ctx.job_id / step_code]
    predecessor = _predecessor_job_id(ctx)
    if predecessor is not None:
        dirs.append(root / "staging" / predecessor / step_code)
    for staging_dir in dirs:
        if not staging_dir.is_dir():
            continue
        for partial in staging_dir.glob("*.staging"):
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)


def _remove_file(path: Path) -> None:
    """Best-effort removal of a managed file (never raises)."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _raise_if_cancelled(ctx: WorkerContext, phase: str) -> None:
    """Fail with the stable cancel code when the durable flag is set."""
    if ctx.is_cancelled():
        raise VideoImportError(
            CODE_CANCELLED,
            f"import cancelled before {phase} phase",
            location=f"phase:{phase}",
        )


def _wrap_managed_errors(exc: ManagedPathError) -> VideoImportError:
    """Map a containment failure to the stable PATH_CONTAINMENT envelope."""
    return VideoImportError(
        CODE_PATH_CONTAINMENT,
        f"managed path rejected: {exc}",
        location="managed path",
        details={"reason": str(exc)},
    )


def _validate_ownership(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> VideoItem:
    """Verify the VideoItem → Project → Workspace ownership chain.

    The active (non-archived) VideoItem must belong to *project_id* and that
    Project must belong to *workspace_id*.  Called **before Job creation**
    (``submit_import``) and **again at publication** (``_publish_effect``) so
    a cross-workspace/cross-project combination is rejected before any
    managed write — no artifact/owner/job side effects survive the rejection.

    Raises:
        VideoImportError: ``VIDEO_ITEM_NOT_FOUND`` / ``PROJECT_NOT_FOUND``
            when the required row is missing or archived, ``OWNERSHIP_MISMATCH``
            when the chain does not match the stated ids.
    """
    # Project first: a nonexistent/archived project is reported precisely
    # (PROJECT_NOT_FOUND) before the video-item checks; then the workspace
    # link; then the video item and its project link.
    project = session.get(Project, project_id)
    if project is None or project.status == "archived":
        raise VideoImportError(
            CODE_PROJECT_NOT_FOUND,
            f"Project {project_id!r} not found or archived",
            location="project",
        )
    if project.workspace_id != workspace_id:
        raise VideoImportError(
            CODE_OWNERSHIP_MISMATCH,
            f"Project {project_id!r} belongs to workspace {project.workspace_id!r}, "
            f"not the stated workspace {workspace_id!r}",
            location="project.workspace_id",
            details={
                "project_id": project_id,
                "actual_workspace_id": project.workspace_id,
                "stated_workspace_id": workspace_id,
            },
        )
    video = session.scalar(
        select(VideoItem).where(
            VideoItem.id == video_item_id,
            VideoItem.status != "archived",
        )
    )
    if video is None:
        raise VideoImportError(
            CODE_VIDEO_ITEM_NOT_FOUND,
            f"Video Item {video_item_id!r} not found or archived",
            location="video_item",
        )
    if video.project_id != project_id:
        raise VideoImportError(
            CODE_OWNERSHIP_MISMATCH,
            f"Video Item {video_item_id!r} belongs to project {video.project_id!r}, "
            f"not the stated project {project_id!r}",
            location="video_item.project_id",
            details={
                "video_item_id": video_item_id,
                "actual_project_id": video.project_id,
                "stated_project_id": project_id,
            },
        )
    return video


# ── The ANALYZE_MEDIA handler (contract §6.2) ────────────────────────────────


def analyze_media_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one ANALYZE_MEDIA Job: probe → copy → publish (idempotent).

    The handler resumes from the step checkpoint: a completed probe is
    reused instead of re-probing, a completed copy is verified and reused,
    and a published effect is verified and skipped.  Every phase cleans its
    staging/partial files on cancel/failure.

    The checkpoint is threaded through the phases in-memory so each phase's
    write preserves the earlier phases' payloads (probe → copy → published).
    """
    managed = _managed_for(ctx)
    cp = ctx.checkpoint
    if not isinstance(cp, dict):
        cp = {"schema_version": PROBE_SCHEMA_VERSION}

    probe = _probe_phase(ctx, cp, managed)
    cp = {**cp, "probe": probe, "phase": "probe"}
    copy_ev = _copy_phase(ctx, cp, managed, probe)
    cp = {**cp, "copy": copy_ev, "phase": "copy"}
    published = _publish_phase(ctx, cp, managed, probe, copy_ev)
    return {"probe": probe, "copy": copy_ev, "published": published}


def _probe_phase(
    ctx: WorkerContext, cp: dict[str, Any], managed: ManagedRoot
) -> dict[str, Any]:
    """Probe phase: reuse the checkpointed probe result or run ffprobe."""
    del managed  # probe is read-only; no managed writes in this phase
    probe = cp.get("probe")
    if isinstance(probe, dict) and probe.get("schema_version") == PROBE_SCHEMA_VERSION:
        return probe
    _raise_if_cancelled(ctx, "probe")
    source_path = str(ctx.input_manifest["source_path"])
    expected = ctx.input_manifest.get("source_sha256")
    probe = probe_source(source_path, expected_sha256=expected)
    ctx.write_checkpoint({**cp, "probe": probe, "phase": "probe"})
    return probe


def _copy_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    probe: dict[str, Any],
) -> dict[str, Any]:
    """Copy phase: stream the source into the managed staging area.

    SHA-256 and size are computed during the copy (``atomic_write_stream``
    hashes the staged bytes before publish and aborts on ``expected_sha256``
    mismatch).  Returns the copy evidence dict.
    """
    copy_ev = cp.get("copy")
    if isinstance(copy_ev, dict) and _copy_evidence_valid(managed, copy_ev):
        return copy_ev
    _raise_if_cancelled(ctx, "copy")
    source_path = Path(str(ctx.input_manifest["source_path"]))
    expected = ctx.input_manifest.get("source_sha256")
    name = _sanitize_name(str(ctx.input_manifest.get("title") or source_path.name))
    staged_rel = _staging_relative_path(ctx, name)
    _cleanup_staging_partials(ctx, managed)
    _check_disk_space(managed, source_path)

    try:
        with source_path.open("rb") as handle:
            sha256, size = managed.atomic_write_stream(
                staged_rel, handle, expected_sha256=expected
            )
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    except ArtifactWriteError as exc:
        if "SHA-256 mismatch" in str(exc):
            raise VideoImportError(
                CODE_CHECKSUM_MISMATCH,
                f"copied bytes do not match expected source sha256: {exc}",
                location="artifact (copy step)",
                details={"expected_sha256": expected},
            ) from exc
        raise VideoImportError(
            CODE_PUBLICATION_FAILED,
            f"atomic copy to managed root failed: {exc}",
            location="artifact (copy step)",
        ) from exc
    except OSError as exc:
        raise VideoImportError(
            CODE_INPUT_UNREADABLE,
            f"failed reading source during copy: {exc}",
            location="source file path",
        ) from exc

    if ctx.is_cancelled():
        _remove_file(managed.resolve(staged_rel))
        raise VideoImportError(
            CODE_CANCELLED,
            "import cancelled after copy; staged file removed",
            location="phase:copy",
        )

    copy_ev = {
        "staged_rel": staged_rel,
        "sha256": sha256,
        "size_bytes": size,
    }
    ctx.write_checkpoint({**cp, "copy": copy_ev, "phase": "copy"})
    return copy_ev


def _copy_evidence_valid(managed: ManagedRoot, copy_ev: dict[str, Any]) -> bool:
    """True when the checkpointed copy evidence still matches on disk.

    A re-run reuses the staged file only when it exists and still hashes to
    the recorded value; anything else re-copies from the source.
    """
    staged_rel = copy_ev.get("staged_rel")
    if not isinstance(staged_rel, str):
        return False
    try:
        staged_path = managed.resolve(staged_rel)
    except ManagedPathError:
        return False
    if not staged_path.is_file():
        return False
    recorded = copy_ev.get("sha256")
    if not isinstance(recorded, str):
        return False
    try:
        return hash_file(staged_path) == recorded
    except OSError:
        return False


def _publish_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    probe: dict[str, Any],
    copy_ev: dict[str, Any],
) -> dict[str, Any]:
    """Publish phase: move staged bytes into the final path and persist the
    artifact + owner + video_item probe columns in ONE transaction.

    Idempotent replay: if the final file already exists with the recorded
    checksum, it is reused; if the artifact row is already ``ready`` with
    matching evidence, publication is skipped.  A DB failure removes the
    just-published file **only when THIS attempt created/moved it** — a
    pre-existing committed final file reused by replay is never removed
    (correction #4: cleanup never deletes bytes it does not own).
    """
    published = cp.get("published")
    if isinstance(published, dict) and published.get("artifact_id"):
        return published
    _raise_if_cancelled(ctx, "publish")

    staged_rel = str(copy_ev["staged_rel"])
    sha256 = str(copy_ev["sha256"])
    size = int(copy_ev["size_bytes"])
    name = Path(staged_rel).name
    final_rel = _final_relative_path(ctx, name)
    try:
        staged_path = managed.resolve(staged_rel)
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    try:
        final_path = managed.resolve(final_rel)
    except ManagedPathError as exc:
        # Containment failure before publication: remove the staged copy so
        # a rejected import never leaves staging/partial files behind.
        _remove_file(staged_path)
        raise _wrap_managed_errors(exc) from exc

    # Whether THIS attempt moved the staged bytes into the final path.  When
    # False, the final file pre-existed (a committed ready artifact or a
    # crash-between-move-and-commit partial) and must survive any later
    # failure untouched.
    created_final = False
    try:
        created_final = _publish_file(managed, staged_path, final_path, sha256)
    except VideoImportError:
        # _publish_file raised: it did NOT create the final file (checksum
        # mismatch against a pre-existing file, or atomic-rename failure) —
        # removing the final path here could delete a previously committed
        # ready artifact.  Only the staged copy (owned by this attempt) is
        # cleaned.
        _remove_file(staged_path)
        raise
    try:
        _publish_effect(ctx, final_rel, sha256, size, probe)
    except VideoImportError:
        _remove_file(staged_path)
        if created_final:
            _remove_file(final_path)
        raise
    except Exception as exc:  # noqa: BLE001 - publication failures are permanent
        _remove_file(staged_path)
        if created_final:
            _remove_file(final_path)
        raise VideoImportError(
            CODE_PUBLICATION_FAILED,
            f"publication transaction failed: {exc}",
            location="artifact (publish step)",
            details={"error_type": type(exc).__name__},
        ) from exc

    _remove_file(staged_path)
    artifact_id = _artifact_id(ctx, final_rel)
    published = {
        "final_rel": final_rel,
        "artifact_id": artifact_id,
        "sha256": sha256,
        "size_bytes": size,
    }
    ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
    return published


def _publish_file(
    managed: ManagedRoot, staged_path: Path, final_path: Path, sha256: str
) -> bool:
    """Atomically move the staged file to its final managed path.

    Returns ``True`` when THIS attempt created/moved the final file (the
    failing attempt owns the bytes and may remove them on a later failure),
    ``False`` when an existing verified final file was reused (replay of a
    previously committed publication — the file is NOT owned by this attempt
    and must never be removed).

    Replay-safe: when the final file already exists it is verified against
    the recorded checksum and reused (a crash between the file move and the
    DB commit leaves the verified bytes in place); the stale staged copy is
    removed either way.  A checksum mismatch against a **pre-existing** final
    file raises ``CHECKSUM_MISMATCH`` WITHOUT removing that file (correction
    #4: it may be a previously committed ready artifact).
    """
    if final_path.exists():
        if hash_file(final_path) != sha256:
            raise VideoImportError(
                CODE_CHECKSUM_MISMATCH,
                "final file exists but does not match the recorded copy checksum",
                location="artifact (publish step)",
                details={"expected_sha256": sha256},
            )
        _remove_file(staged_path)
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged_path, final_path)
    except OSError as exc:
        raise VideoImportError(
            CODE_PUBLICATION_FAILED,
            f"atomic rename into final path failed: {exc}",
            location="artifact (publish step)",
        ) from exc
    return True


def _publish_effect(
    ctx: WorkerContext,
    final_rel: str,
    sha256: str,
    size: int,
    probe: dict[str, Any],
) -> None:
    """Persist artifact + owner link + video_item probe columns in ONE txn.

    This is the state+effect coupling point (contract §7.1/§9.2): the
    ``artifact`` row becomes ``ready`` only after the atomic filesystem
    write succeeded, and the caller (``_publish_phase``) removes the file on
    any failure so a rolled-back transaction never leaves an orphan.
    """
    if ctx.session_factory is None:
        raise VideoImportError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot persist publication",
            location="artifact (publish step)",
        )
    workspace_id = str(ctx.input_manifest["workspace_id"])
    project_id = str(ctx.input_manifest["project_id"])
    video_item_id = str(ctx.input_manifest["video_item_id"])
    artifact_id = _artifact_id(ctx, final_rel)

    video_stream = probe["video_stream"]
    r_rate = video_stream["r_frame_rate"]
    duration_ms = round(float(probe["container"]["duration_seconds"]) * 1000)

    with ctx.session_factory() as session:
        # Ownership re-validation at publication (correction #2): the chain
        # may have changed between submit and run.  Validate BEFORE any row
        # is added so a rejection has zero artifact/owner/video_item side
        # effects inside this transaction.
        video = _validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )

        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            artifact = Artifact(
                id=artifact_id,
                workspace_id=workspace_id,
                kind="video",
                relative_path=final_rel,
                state="ready",
                sha256=sha256,
                size_bytes=size,
                mime_type="video/mp4",
            )
            session.add(artifact)
        else:
            # Replay: the row exists from an earlier attempt.  Verify the
            # evidence and repair a partial row; a mismatched row means the
            # source changed between attempts and must fail closed.
            if artifact.sha256 != sha256 or artifact.size_bytes != size:
                raise VideoImportError(
                    CODE_CHECKSUM_MISMATCH,
                    "existing artifact row conflicts with the copy evidence",
                    location="artifact (publish step)",
                    details={"artifact_id": artifact_id},
                )
            if artifact.state != "ready":
                artifact.state = "ready"
                artifact.updated_at = datetime.now(UTC)

        owner = session.get(
            ArtifactOwner, (artifact_id, "video_item", video_item_id, ARTIFACT_PURPOSE_SOURCE)
        )
        if owner is None:
            session.add(
                ArtifactOwner(
                    artifact_id=artifact_id,
                    owner_type="video_item",
                    owner_id=video_item_id,
                    purpose=ARTIFACT_PURPOSE_SOURCE,
                )
            )

        video.duration_ms = duration_ms
        video.width = int(video_stream["width"])
        video.height = int(video_stream["height"])
        video.fps_num = int(r_rate["num"])
        video.fps_den = int(r_rate["den"])
        video.source_artifact_id = artifact_id
        video.revision = (video.revision or 1) + 1
        video.updated_at = datetime.now(UTC)
        session.commit()


# ── Submit (contract §8.1 idempotency, corrections #1/#2/#3) ────────────────


def _idempotency_key(
    video_item_id: str, source_sha256: str | None, generation: str
) -> str:
    """Owner-scoped ANALYZE_MEDIA idempotency key (correction #1/#3).

    The logical identity is scoped to the VideoItem owner, so the same
    source bytes imported into two different VideoItems create two
    independent Jobs/effect sets (never a cross-owner collision)::

        ANALYZE_MEDIA:video_item:<video_item_id>:<source_sha256>:<generation>
            (preflight hash supplied — content identity is known)
        ANALYZE_MEDIA:video_item:<video_item_id>:<generation>
            (no preflight hash — per (owner, generation) only)

    Without a preflight hash NO content identity is claimed before the hash
    exists (V1 PM decision #6 / correction #3): the canonical SHA is computed
    during the streaming copy and recorded on the artifact by the worker.
    With a preflight hash the content identity is part of the key, so
    duplicate submits of the same bytes for the same item reuse (completed)
    or reject (active) per DURABLE_JOB_CONTRACT §8.1.  ``generation``
    distinguishes explicit re-imports of the same owner+bytes and is always
    kept in the key.
    """
    if source_sha256 is not None:
        return (
            f"{JOB_TYPE_ANALYZE_MEDIA}:video_item:{video_item_id}:"
            f"{source_sha256}:{generation}"
        )
    return f"{JOB_TYPE_ANALYZE_MEDIA}:video_item:{video_item_id}:{generation}"


def submit_import(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    source_path: str | Path,
    source_sha256: str | None = None,
    generation: str = "1",
    managed_root: str | Path | None = None,
    title: str | None = None,
) -> ImportSubmitResult:
    """Create the durable ANALYZE_MEDIA Job for one source video.

    The idempotency key is **owner-scoped** (correction #1):
    ``ANALYZE_MEDIA:video_item:<video_item_id>:<source_sha256?>:<generation>``.
    A completed duplicate for the same (owner, content, generation) returns
    the existing Job (``reused=True``); an active duplicate raises
    ``IdempotencyKeyInUse`` — exactly one effect set per logical import of a
    VideoItem.

    ``source_sha256`` is **optional** (correction #3 / V1 PM decision #6).
    When supplied it is the preflight hash and the worker verifies the
    streaming copy against it, aborting before publish on mismatch
    (``CHECKSUM_MISMATCH``).  When absent, the request path never hashes an
    arbitrarily large file synchronously: the submission identity is the
    stable per-owner key above (no content identity is claimed), the worker
    computes the canonical SHA-256 and size during the managed copy and
    records them on the artifact.  Retry/restart of a failed/cancelled Job is
    a successor with the same key and generation (DURABLE_JOB_CONTRACT
    §6.4/§8.5); a fresh logical run of the same owner bumps ``generation``.

    Ownership is validated **before any managed write** (correction #2): the
    active VideoItem must belong to *project_id* and that Project must belong
    to *workspace_id*, else ``VIDEO_ITEM_NOT_FOUND`` / ``PROJECT_NOT_FOUND``
    / ``OWNERSHIP_MISMATCH`` is raised and no Job row is created.  The worker
    re-validates the same chain at publication.

    Raises:
        VideoImportError: ``INPUT_MISSING`` / ``INPUT_UNREADABLE`` for a bad
            source; ``VIDEO_ITEM_NOT_FOUND`` / ``PROJECT_NOT_FOUND`` /
            ``OWNERSHIP_MISMATCH`` for a broken ownership chain.
        ValueError: for a malformed sha256 or empty ids.
        IdempotencyKeyInUse: an active Job already exists for the key.
    """
    source = Path(source_path)
    if not source.exists():
        raise VideoImportError(
            CODE_INPUT_MISSING,
            f"source file does not exist: {source}",
            location="source file path",
        )
    if not os.access(source, os.R_OK):
        raise VideoImportError(
            CODE_INPUT_UNREADABLE,
            f"source file is not readable: {source}",
            location="source file path",
        )
    if source_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError(
            "source_sha256 must be a 64-character lowercase hex string when provided"
        )
    if not workspace_id or not project_id or not video_item_id:
        raise ValueError("workspace_id, project_id and video_item_id are required")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source_path": str(source.resolve()),
        "source_size_bytes": source.stat().st_size,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "generation": generation,
        "title": title or source.name,
    }
    if source_sha256 is not None:
        manifest["source_sha256"] = source_sha256
    if managed_root is not None:
        manifest["managed_root"] = str(managed_root)

    idempotency_key = _idempotency_key(video_item_id, source_sha256, generation)

    with session_factory() as session:
        from app.persistence.jobs import JobRepository
        from app.persistence.models import Job as JobORM

        # Ownership gate BEFORE any managed write: a cross-workspace or
        # cross-project submit is rejected with no Job row/effect
        # (correction #2).
        _validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )

        # Detect a completed logical run BEFORE create_job so the caller
        # learns whether the returned Job was reused (contract §8.1: a
        # completed key returns the existing Job).  An ACTIVE duplicate is
        # rejected by create_job with IdempotencyKeyInUse.
        completed_exists = session.scalar(
            select(JobORM.id).where(
                JobORM.workspace_id == workspace_id,
                JobORM.idempotency_key == idempotency_key,
                JobORM.input_generation == generation,
                JobORM.state == "completed",
            )
        )
        job = JobRepository(session).create_job(
            workspace_id=workspace_id,
            job_type=JOB_TYPE_ANALYZE_MEDIA,
            owner_type="video_item",
            owner_id=video_item_id,
            input_manifest=manifest,
            idempotency_key=idempotency_key,
            input_generation=generation,
            steps=analyze_media_steps(),
            actor="api",
        )
        session.commit()
        return ImportSubmitResult(job_id=job.id, reused=completed_exists is not None)


def analyze_media_steps() -> list[StepInput]:
    """The ANALYZE_MEDIA step plan (one sync step: probe→copy→publish)."""
    return [StepInput(step_code=COPY_STEP_CODE, position=0, step_type="sync")]


def register_analyze_media_handler(worker: Any) -> None:
    """Register the ANALYZE_MEDIA handler on a DurableWorker instance.

    No declared final outputs: this job type's completion gate is the
    publication transaction itself (contract §6.2 step 3), not a separate
    disk validation of an output list.
    """
    worker.register_handler(JOB_TYPE_ANALYZE_MEDIA, analyze_media_handler)
