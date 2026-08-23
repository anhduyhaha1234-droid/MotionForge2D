"""Original Audio Remux Engine (S11-T01B).

Pure/bounded remux of the CANONICAL FIRST AUDIO STREAM (S11 frozen product
decision §1): the output carries the first video stream (stream-copied) and
EXACTLY ONE audio stream — the source's first audio stream — either
stream-copied (AAC source) or transcoded to AAC (any other codec).  The
engine is a PURE MODULE: it takes an already-resolved source path plus a
managed output directory and returns a deterministic result/checkpoint.  It
never touches the import policy, the durable-job wiring, the database, the
network or the GPU, and it never mutates the source bytes.

Frozen decisions implemented here (S11-SPRINT_CONTRACT.md):

1. First audio stream is canonical; streams are never mixed (``-map 0:a:0``
   only — a multi-stream source publishes exactly one audio stream).
2. Video input contract: MP4 (ISO-BMFF family) + H.264/HEVC — refused
   otherwise (``UNSUPPORTED_CONTAINER`` / ``UNSUPPORTED_VIDEO_CODEC``).
3. AAC first audio → stream-copy (``-c:a copy``).
4. Non-AAC first audio → AAC transcode (``-c:a aac``).
5. No audio → explicit ``NO_AUDIO_PRESENT`` terminal status; no fabricated
   audio is ever generated.
6. Corrupt/unsupported sources FAIL CLOSED with stable error codes — never
   a silent fallback, never a partial publication.

Bounding contract (mirrors the S08-H02 bounded-output discipline of
``app/services/video_probe.py``, whose public :func:`remaining_budget`
helper is reused as the single budget authority):

- FFmpeg/ffprobe are invoked with LIST ARGS and ``shell=False`` (no shell
  interpolation ever), ``-nostdin`` (the child can never block on stdin).
- stdout/stderr are drained concurrently by daemon reader threads against a
  COMBINED byte ceiling; oversized output kills the child and fails closed.
- Every wait/reap/join uses ONLY the remaining deadline budget — never a
  fresh fixed window after the deadline.
- Cancellation (a ``threading.Event``) terminates the FULL child process
  tree (psutil, children first) and removes the staging file.
- The staged output size is polled while ffmpeg runs; exceeding
  ``max_output_bytes`` kills the child and fails closed
  (``OUTPUT_CAP_EXCEEDED``) — the ``-fs`` muxer option alone does NOT fail,
  so the cap is enforced by the engine, not delegated to ffmpeg.
- Publication is atomic: ffmpeg writes a uniquely-named staging file inside
  the managed directory; the staging file is probed and validated (codec ==
  aac, duration within tolerance, positive timebase, size under cap) BEFORE
  ``os.replace`` publishes it under the final name.  A partial output is
  never visible at the published path.
- Determinism: outputs are produced with ``-fflags +bitexact
  -flags:a +bitexact`` so identical inputs yield byte-identical outputs and
  therefore identical SHA-256 checkpoints across runs (verified empirically
  for both the copy and the transcode path).
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe
from app.services.video_probe import remaining_budget

try:  # psutil is the precise child-tree killer; degrade gracefully without it.
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared dependency
    psutil = None

__all__ = [
    "CODE_CANCELLED",
    "CODE_CORRUPT_SOURCE",
    "CODE_DEADLINE_EXCEEDED",
    "CODE_FFMPEG_FAILED",
    "CODE_FFMPEG_NOT_FOUND",
    "CODE_MISSING_VIDEO_STREAM",
    "CODE_NO_AUDIO_PRESENT",
    "CODE_OUTPUT_CAP_EXCEEDED",
    "CODE_PATH_ESCAPE",
    "CODE_PROBE_OUTPUT_TOO_LARGE",
    "CODE_SOURCE_MUTATED",
    "CODE_SOURCE_NOT_FOUND",
    "CODE_UNSUPPORTED_CONTAINER",
    "CODE_UNSUPPORTED_VIDEO_CODEC",
    "CODE_VALIDATION_FAILED",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_REMUX_TIMEOUT_SECONDS",
    "ORIGINAL_AUDIO_REMUX_SCHEMA_VERSION",
    "OUTPUT_FILENAME_DEFAULT",
    "STATUS_NO_AUDIO_PRESENT",
    "STATUS_STREAM_COPY",
    "STATUS_TRANSCODE",
    "VIETNAMESE_ACTIONS",
    "OriginalAudioRemuxError",
    "OriginalAudioRemuxResult",
    "remux_original_audio",
]

#: Schema version of the deterministic checkpoint payload.
ORIGINAL_AUDIO_REMUX_SCHEMA_VERSION = 1

#: Default published file name inside the managed output directory.
OUTPUT_FILENAME_DEFAULT = "original_audio.mp4"

#: Fail-closed ceiling on the staged output size (bytes).  A remux of the
#: accepted inputs (MP4 + H.264/HEVC, stream-copied video) is a container
#: rewrite and stays close to the source size; 8 GiB leaves headroom while
#: still failing closed far below runaway-encode territory.
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024 * 1024

#: Default wall-clock budget for the whole operation (seconds) when the
#: caller provides neither ``deadline`` nor ``timeout_seconds``.
DEFAULT_REMUX_TIMEOUT_SECONDS = 600.0

#: Hard combined ceiling for ffprobe/ffmpeg stdout+stderr capture (bytes).
#: The restricted queries emit well under 16 KiB; this bound fails closed
#: long before a hostile child could weaponize unbounded capture.
_MAX_TOOL_OUTPUT_BYTES = 1 * 1024 * 1024

#: Fail-closed ceiling on parsed streams per probe query (matches
#: ``video_probe.PROBE_MAX_STREAMS``).
_MAX_STREAMS = 4

#: AAC encoder bitrate for the transcode path (bits/second).
_TRANSCODE_AUDIO_BITRATE = "192k"

#: Absolute + relative tolerance applied when validating the published
#: audio duration against the source audio duration.  AAC priming/padding
#: and container rounding shift short clips by tens of milliseconds
#: (measured: AC-3→AAC +20 ms, Opus→AAC +13 ms); 0.5 s absolute or 5 %
#: relative (whichever is larger) fails closed on real truncation while
#: tolerating codec framing noise.
_DURATION_TOLERANCE_ABSOLUTE = 0.5
_DURATION_TOLERANCE_RELATIVE = 0.05

# ── Stable error codes ───────────────────────────────────────────────────────

CODE_SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
CODE_SOURCE_NOT_A_FILE = "SOURCE_NOT_A_FILE"
CODE_PATH_ESCAPE = "PATH_ESCAPE"
CODE_CORRUPT_SOURCE = "CORRUPT_SOURCE"
CODE_PROBE_OUTPUT_TOO_LARGE = "PROBE_OUTPUT_TOO_LARGE"
CODE_UNSUPPORTED_CONTAINER = "UNSUPPORTED_CONTAINER"
CODE_UNSUPPORTED_VIDEO_CODEC = "UNSUPPORTED_VIDEO_CODEC"
CODE_MISSING_VIDEO_STREAM = "MISSING_VIDEO_STREAM"
CODE_NO_AUDIO_PRESENT = "NO_AUDIO_PRESENT"
CODE_FFMPEG_NOT_FOUND = "FFMPEG_NOT_FOUND"
CODE_FFMPEG_FAILED = "FFMPEG_FAILED"
CODE_OUTPUT_CAP_EXCEEDED = "OUTPUT_CAP_EXCEEDED"
CODE_DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
CODE_CANCELLED = "CANCELLED"
CODE_VALIDATION_FAILED = "VALIDATION_FAILED"
CODE_SOURCE_MUTATED = "SOURCE_MUTATED"

#: Terminal result statuses (``error_code`` is None for these).
STATUS_STREAM_COPY = "STREAM_COPY"
STATUS_TRANSCODE = "TRANSCODE"
STATUS_NO_AUDIO_PRESENT = "NO_AUDIO_PRESENT"

#: Vietnamese suggested actions for every stable code (PRD FR-08 style).
VIETNAMESE_ACTIONS: dict[str, str] = {
    CODE_SOURCE_NOT_FOUND: (
        "Không tìm thấy tệp nguồn. Hãy kiểm tra lại đường dẫn và thử lại."
    ),
    CODE_SOURCE_NOT_A_FILE: (
        "Đường dẫn nguồn không phải là một tệp. Hãy kiểm tra lại nguồn."
    ),
    CODE_PATH_ESCAPE: (
        "Đường dẫn đầu ra nằm ngoài thư mục quản lý. Hãy dùng tên tệp hợp lệ."
    ),
    CODE_CORRUPT_SOURCE: (
        "Tệp nguồn hỏng hoặc không đọc được. Hãy kiểm tra lại tệp gốc."
    ),
    CODE_PROBE_OUTPUT_TOO_LARGE: (
        "Kết quả phân tích tệp vượt giới hạn an toàn. Hãy báo lỗi hệ thống."
    ),
    CODE_UNSUPPORTED_CONTAINER: (
        "Định dạng container không được hỗ trợ (chỉ nhận MP4). Hãy chuyển đổi "
        "tệp về MP4 trước khi thử lại."
    ),
    CODE_UNSUPPORTED_VIDEO_CODEC: (
        "Codec video không được hỗ trợ (chỉ nhận H.264 hoặc HEVC). Hãy chuyển "
        "đổi tệp trước khi thử lại."
    ),
    CODE_MISSING_VIDEO_STREAM: (
        "Tệp không có luồng video hợp lệ. Hãy kiểm tra lại tệp nguồn."
    ),
    CODE_NO_AUDIO_PRESENT: (
        "Tệp nguồn không có âm thanh nên không thể đính kèm âm thanh gốc."
    ),
    CODE_FFMPEG_NOT_FOUND: (
        "Chưa cài đặt FFmpeg trên máy. Hãy cài FFmpeg rồi thử lại."
    ),
    CODE_FFMPEG_FAILED: (
        "Xử lý âm thanh thất bại. Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi "
        "hệ thống."
    ),
    CODE_OUTPUT_CAP_EXCEEDED: (
        "Tệp kết quả vượt giới hạn dung lượng cho phép. Hãy thử lại với tệp "
        "ngắn hơn."
    ),
    CODE_DEADLINE_EXCEEDED: (
        "Xử lý quá thời gian cho phép. Hãy thử lại; nếu lỗi lặp lại, hãy báo "
        "lỗi hệ thống."
    ),
    CODE_CANCELLED: (
        "Yêu cầu đã bị hủy bởi người dùng."
    ),
    CODE_VALIDATION_FAILED: (
        "Tệp kết quả không đạt kiểm tra chất lượng và đã bị loại bỏ an toàn. "
        "Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống."
    ),
    CODE_SOURCE_MUTATED: (
        "Tệp nguồn bị thay đổi trong quá trình xử lý. Hãy thử lại với nguồn "
        "khác."
    ),
}


class OriginalAudioRemuxError(Exception):
    """A stable, actionable original-audio remux failure.

    ``code`` is the machine-readable stable error code; ``action()`` returns
    the Vietnamese suggested action; ``details`` carries structured context.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def action(self) -> str:
        """The Vietnamese suggested action for this error's code."""
        return VIETNAMESE_ACTIONS.get(
            self.code, "Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống."
        )


@dataclass(frozen=True)
class OriginalAudioRemuxResult:
    """Deterministic outcome of one remux operation.

    ``checkpoint`` is the durable, schema-versioned payload: it contains
    ONLY content-derived values (statuses, codecs, exact decimal durations,
    SHA-256 hashes, sizes) — no paths and no timestamps — so two runs over
    identical inputs produce byte-identical checkpoints.
    """

    status: str
    error_code: str | None
    source_path: str
    source_sha256: str
    source_size_bytes: int
    post_remux_source_sha256: str | None = None
    output_path: str | None = None
    output_sha256: str | None = None
    output_size_bytes: int | None = None
    source_audio_codec: str | None = None
    output_audio_codec: str | None = None
    source_audio_duration: str | None = None
    output_audio_duration: str | None = None
    audio_time_base: str | None = None
    video_codec: str | None = None
    command: tuple[str, ...] = ()
    checkpoint: dict[str, Any] = field(default_factory=dict)


# ── Bounded subprocess plumbing ──────────────────────────────────────────────


class _CaptureState:
    """Thread-safe combined stdout+stderr byte accounting (video_probe pattern).

    ``accept`` makes the keep/reject decision for each chunk ATOMICALLY under
    one lock and sets ``abort`` exactly once the combined ceiling is exceeded,
    so retained output can never grow past the boundary.
    """

    __slots__ = ("count", "cap", "abort", "_lock")

    def __init__(self, cap: int) -> None:
        self.count = 0
        self.cap = cap
        self.abort = threading.Event()
        self._lock = threading.Lock()

    def accept(self, n: int) -> bool:
        with self._lock:
            if self.abort.is_set():
                return False
            if self.count + n > self.cap:
                self.abort.set()
                return False
            self.count += n
            return True


class _PipeReader(threading.Thread):
    """Drain ONE binary pipe in bounded chunks until EOF or cap abort."""

    def __init__(self, state: _CaptureState, stream: Any, label: str) -> None:
        super().__init__(daemon=True, name=f"remux-{label}-reader")
        self.state = state
        self.stream = stream
        self.chunks: list[bytes] = []

    def run(self) -> None:
        try:
            while not self.state.abort.is_set():
                chunk = self.stream.read(8192)
                if chunk == b"":
                    break
                if self.state.accept(len(chunk)):
                    self.chunks.append(chunk)
        except BaseException:  # pragma: no cover - defensive
            pass


def _kill_tree(proc: Any) -> None:
    """Terminate the FULL child process tree (children first), then the child.

    Uses psutil so a grandchild inherited onto the pipes cannot survive as an
    orphan; falls back to ``proc.kill()`` alone when psutil is unavailable.
    """
    if psutil is not None:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error):
                    child.kill()
            with contextlib.suppress(psutil.Error):
                parent.kill()
        except psutil.Error:
            pass
    with contextlib.suppress(OSError):
        proc.kill()


def _drop_stream(stream: Any) -> None:
    """Best-effort close of a pipe read-end to unblock its daemon reader."""
    with contextlib.suppress(OSError, ValueError):
        stream.close()


class _BoundedRunResult:
    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_bounded(
    cmd: list[str],
    *,
    deadline: float,
    cancel_event: threading.Event | None = None,
    staging_path: Path | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    on_poll: Callable[[], None] | None = None,
    poll_interval: float = 0.05,
) -> _BoundedRunResult:
    """Run *cmd* (LIST ARGS, ``shell=False``) under ALL bounding conditions.

    Enforced simultaneously by the MAIN thread while two daemon readers drain
    stdout/stderr concurrently:

    - combined stdout+stderr byte ceiling → ``PROBE_OUTPUT_TOO_LARGE``;
    - deadline (only the REMAINING budget is ever granted) →
      ``DEADLINE_EXCEEDED``;
    - ``cancel_event`` set → ``CANCELLED``;
    - staged output size beyond ``max_output_bytes`` (when *staging_path* is
      given) → ``OUTPUT_CAP_EXCEEDED``.

    Every failure path kills the FULL child tree and reaps/joins using only
    the remaining deadline budget — no orphan process, no fresh fixed window.
    """
    proc = subprocess_popen(cmd)
    assert proc.stdout is not None and proc.stderr is not None
    state = _CaptureState(_MAX_TOOL_OUTPUT_BYTES)
    out_reader = _PipeReader(state, proc.stdout, "stdout")
    err_reader = _PipeReader(state, proc.stderr, "stderr")
    out_reader.start()
    err_reader.start()

    def _finish_failure(code: str, message: str) -> OriginalAudioRemuxError:
        _kill_tree(proc)
        budget = remaining_budget(deadline)
        if budget > 0:
            with contextlib.suppress(Exception):
                proc.wait(timeout=budget)
        else:
            proc.poll()
        for reader, stream in ((out_reader, proc.stdout), (err_reader, proc.stderr)):
            if reader.is_alive():
                _drop_stream(stream)
        with contextlib.suppress(Exception):
            reader.join(timeout=remaining_budget(deadline))
        return OriginalAudioRemuxError(code, message)

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise _finish_failure(
                    CODE_CANCELLED, "operation cancelled by request"
                )
            if state.abort.is_set():
                raise _finish_failure(
                    CODE_PROBE_OUTPUT_TOO_LARGE,
                    f"child output exceeded the combined "
                    f"{_MAX_TOOL_OUTPUT_BYTES}-byte ceiling",
                )
            if remaining_budget(deadline) <= 0:
                raise _finish_failure(
                    CODE_DEADLINE_EXCEEDED,
                    f"deadline exceeded running {Path(cmd[0]).name}",
                )
            if staging_path is not None:
                with contextlib.suppress(OSError):
                    if staging_path.exists() and (
                        staging_path.stat().st_size > max_output_bytes
                    ):
                        raise _finish_failure(
                            CODE_OUTPUT_CAP_EXCEEDED,
                            f"staged output exceeded the "
                            f"{max_output_bytes}-byte cap",
                        )
            if on_poll is not None:
                on_poll()
            if not out_reader.is_alive() and not err_reader.is_alive():
                break
            time.sleep(poll_interval)
        budget = remaining_budget(deadline)
        if budget <= 0:
            raise _finish_failure(
                CODE_DEADLINE_EXCEEDED, "deadline exceeded reaping the child"
            )
        try:
            proc.wait(timeout=budget)
        except subprocess_timeout() as exc:
            raise _finish_failure(
                CODE_DEADLINE_EXCEEDED, "deadline exceeded reaping the child"
            ) from exc
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
            budget = remaining_budget(deadline)
            if budget > 0:
                with contextlib.suppress(Exception):
                    proc.wait(timeout=budget)
            else:
                proc.poll()
        for reader, stream in ((out_reader, proc.stdout), (err_reader, proc.stderr)):
            if reader.is_alive():
                _drop_stream(stream)
        for reader in (out_reader, err_reader):
            with contextlib.suppress(Exception):
                reader.join(timeout=remaining_budget(deadline))

    out_text = b"".join(out_reader.chunks).decode("utf-8", errors="replace")
    err_text = b"".join(err_reader.chunks).decode("utf-8", errors="replace")
    return _BoundedRunResult(
        proc.returncode if proc.returncode is not None else -1, out_text, err_text
    )


def subprocess_popen(cmd: list[str]) -> Any:
    """Single Popen site: list args, no shell, pipes, platform-clean."""
    import subprocess

    return subprocess.Popen(
        cmd,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def subprocess_timeout() -> type[Exception]:
    """The subprocess timeout exception class (single reference site)."""
    import subprocess

    return subprocess.TimeoutExpired


# ── Probing ──────────────────────────────────────────────────────────────────


def _parse_positive_fraction(raw: object) -> Fraction | None:
    """Parse an ffprobe rational string like ``1/44100``; None unless positive."""
    try:
        value = Fraction(str(raw))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _parse_decimal(value: object) -> float | None:
    """Best-effort finite-float parse of an ffprobe decimal; None otherwise."""
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (
        float("inf"), float("-inf")
    ) else None


def _probe_one_stream(
    source: Path,
    *,
    select: str,
    deadline: float,
    cancel_event: threading.Event | None,
) -> list[dict[str, Any]]:
    """One bounded, stream-SELECTED ffprobe query (``-select_streams``).

    R6-F1: the probe queries EXACTLY the stream specifier it needs
    (``v:0`` or ``a:0`` — the video_probe discipline), so a source with
    many audio/subtitle/data streams can never blow up the parse surface:
    ffprobe itself returns at most ONE stream dict here.  Corruption is
    still detected: an unparseable file makes ffprobe exit non-zero
    (verified empirically), which the caller maps to ``CORRUPT_SOURCE``.
    """
    ffprobe = find_ffprobe()
    # NOTE: ffprobe has no -nostdin option; stdin is cut off via
    # ``stdin=subprocess.DEVNULL`` in the single Popen site instead.
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-select_streams", select,
        "-show_entries",
        "stream=index,codec_type,codec_name,time_base,duration,sample_rate,channels",
        str(source),
    ]
    try:
        run = _run_bounded(cmd, deadline=deadline, cancel_event=cancel_event)
    except OriginalAudioRemuxError as exc:
        if exc.code in (
            CODE_CANCELLED,
            CODE_DEADLINE_EXCEEDED,
            CODE_PROBE_OUTPUT_TOO_LARGE,
        ):
            raise
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, f"source probe failed: {exc.message}"
        ) from exc
    except FileNotFoundError as exc:
        raise OriginalAudioRemuxError(
            CODE_FFMPEG_NOT_FOUND, f"ffprobe not found: {exc}"
        ) from exc
    if run.returncode != 0:
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE,
            f"ffprobe failed on {source.name}: {run.stderr.strip()[:300]}",
        )
    try:
        data = json.loads(run.stdout)
    except ValueError as exc:
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, "ffprobe stdout is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, "ffprobe stdout is not a JSON object"
        )
    streams = data.get("streams")
    if not isinstance(streams, list):
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, "ffprobe returned no stream section"
        )
    # Bounded by construction: a single v:0/a:0 specifier yields at most
    # one stream; anything else would be an ffprobe contract violation.
    if len(streams) > _MAX_STREAMS:
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE,
            f"ffprobe returned {len(streams)} streams for a single "
            f"-select_streams {select} query; refusing to parse",
        )
    return streams


def _probe_streams(
    source: Path,
    *,
    deadline: float,
    cancel_event: threading.Event | None,
) -> dict[str, Any]:
    """Bounded probe of the source: FIRST video + FIRST audio + format.

    R6-F1: two stream-SELECTED queries (``-select_streams v:0`` and
    ``a:0``) share the ONE remaining deadline budget — the second probe
    gets only what is left after the first (``remaining_budget``), never
    a fresh window.  Extra audio/subtitle/data streams are ignored by
    construction (never fetched), so a valid ≥5-stream MP4 is accepted
    and the canonical first audio stays the selection target.
    """
    video_streams = _probe_one_stream(
        source, select="v:0", deadline=deadline, cancel_event=cancel_event
    )
    # Shared-budget discipline: the audio probe consumes only the
    # remaining budget left by the video probe.
    audio_streams = _probe_one_stream(
        source,
        select="a:0",
        deadline=deadline,
        cancel_event=cancel_event,
    )
    fmt = _probe_format(
        source, deadline=deadline, cancel_event=cancel_event
    )
    return {
        "streams": [*video_streams, *audio_streams],
        "format": fmt,
    }


def _probe_format(
    source: Path,
    *,
    deadline: float,
    cancel_event: threading.Event | None,
) -> dict[str, Any]:
    """Bounded ffprobe of ONLY the container format section."""
    ffprobe = find_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_entries", "format=format_name,duration",
        str(source),
    ]
    try:
        run = _run_bounded(cmd, deadline=deadline, cancel_event=cancel_event)
    except OriginalAudioRemuxError as exc:
        if exc.code in (
            CODE_CANCELLED,
            CODE_DEADLINE_EXCEEDED,
            CODE_PROBE_OUTPUT_TOO_LARGE,
        ):
            raise
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, f"source probe failed: {exc.message}"
        ) from exc
    except FileNotFoundError as exc:
        raise OriginalAudioRemuxError(
            CODE_FFMPEG_NOT_FOUND, f"ffprobe not found: {exc}"
        ) from exc
    if run.returncode != 0:
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE,
            f"ffprobe failed on {source.name}: {run.stderr.strip()[:300]}",
        )
    try:
        data = json.loads(run.stdout)
    except ValueError as exc:
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, "ffprobe stdout is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, "ffprobe stdout is not a JSON object"
        )
    fmt = data.get("format")
    if not isinstance(fmt, dict):
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE, "ffprobe returned no format section"
        )
    return fmt


def _first_stream(
    data: dict[str, Any], codec_type: str
) -> dict[str, Any] | None:
    """The first stream dict of *codec_type*, or None."""
    streams = data.get("streams")
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type:
            return stream
    return None


_ISO_BMFF_MARKERS = ("mp4", "mov", "m4a", "3gp", "mj2")
_ACCEPTED_VIDEO_CODECS = frozenset({"h264", "hevc"})


def _validate_source_container_and_video(
    data: dict[str, Any], *, source: Path
) -> str:
    """Fail closed on non-MP4 containers / non-H.264-or-HEVC video (frozen §2).

    Returns the source video codec name.
    """
    fmt = data.get("format")
    format_name = ""
    if isinstance(fmt, dict):
        format_name = str(fmt.get("format_name") or "").lower()
    if not any(marker in format_name for marker in _ISO_BMFF_MARKERS):
        raise OriginalAudioRemuxError(
            CODE_UNSUPPORTED_CONTAINER,
            f"unsupported container {format_name!r} for {source.name}; the "
            "engine accepts the MP4 (ISO-BMFF) family only",
        )
    video = _first_stream(data, "video")
    if video is None:
        raise OriginalAudioRemuxError(
            CODE_MISSING_VIDEO_STREAM,
            f"no video stream found in {source.name}",
        )
    video_codec = str(video.get("codec_name") or "")
    if video_codec not in _ACCEPTED_VIDEO_CODECS:
        raise OriginalAudioRemuxError(
            CODE_UNSUPPORTED_VIDEO_CODEC,
            f"unsupported video codec {video_codec!r} for {source.name}; the "
            "engine accepts H.264/HEVC only",
        )
    return video_codec


# ── Checkpoint ───────────────────────────────────────────────────────────────


def _decimal6(value: float | None) -> str | None:
    """Deterministic 6-decimal rendering of a duration (never locale-bound)."""
    if value is None:
        return None
    return f"{value:.6f}"


def _build_checkpoint(
    *,
    status: str,
    mode: str | None,
    source_sha256: str,
    source_size_bytes: int,
    source_audio_codec: str | None,
    source_audio_duration: str | None,
    output_audio_codec: str | None,
    output_audio_duration: str | None,
    audio_time_base: str | None,
    video_codec: str | None,
    output_sha256: str | None,
    output_size_bytes: int | None,
) -> dict[str, Any]:
    """Schema-versioned checkpoint with ONLY content-derived values."""
    checkpoint: dict[str, Any] = {
        "schema_version": ORIGINAL_AUDIO_REMUX_SCHEMA_VERSION,
        "status": status,
        "mode": mode,
        "source_sha256": source_sha256,
        "source_size_bytes": source_size_bytes,
        "source_audio_codec": source_audio_codec,
        "source_audio_duration": source_audio_duration,
        "video_codec": video_codec,
    }
    if output_sha256 is not None:
        checkpoint["output_sha256"] = output_sha256
    if output_size_bytes is not None:
        checkpoint["output_size_bytes"] = output_size_bytes
    if output_audio_codec is not None:
        checkpoint["output_audio_codec"] = output_audio_codec
    if output_audio_duration is not None:
        checkpoint["output_audio_duration"] = output_audio_duration
    if audio_time_base is not None:
        checkpoint["audio_time_base"] = audio_time_base
    return checkpoint


# ── Hashing ──────────────────────────────────────────────────────────────────


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Streaming lowercase hex SHA-256 of *path*."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ── Path containment ─────────────────────────────────────────────────────────


def _resolve_managed_target(
    managed_output_dir: str | Path, output_filename: str
) -> Path:
    """Resolve the published target STRICTLY inside *managed_output_dir*.

    Raises ``PATH_ESCAPE`` for absolute paths, drive/UNC prefixes, parent
    traversal, separators, or any symlink-resolved escape from the managed
    directory.
    """
    managed = Path(managed_output_dir)
    if not managed.is_absolute():
        raise OriginalAudioRemuxError(
            CODE_PATH_ESCAPE,
            f"managed output dir must be absolute: {managed_output_dir!r}",
        )
    managed_resolved = managed.resolve()
    raw = output_filename.replace("\\", "/")
    if (
        not raw
        or raw in (".", "./")
        or "/" in raw
        or ":" in raw[:2]
        or raw.startswith("/")
        or ".." in raw.split("/")
    ):
        raise OriginalAudioRemuxError(
            CODE_PATH_ESCAPE,
            f"output filename must be a single contained path component: "
            f"{output_filename!r}",
        )
    candidate = managed_resolved / raw
    candidate_resolved = candidate.resolve()
    if candidate_resolved != managed_resolved and (
        managed_resolved not in candidate_resolved.parents
    ):
        raise OriginalAudioRemuxError(
            CODE_PATH_ESCAPE,
            f"output path escapes the managed directory: {output_filename!r}",
        )
    return candidate_resolved


# ── Engine entry point ───────────────────────────────────────────────────────


def remux_original_audio(
    source_path: str | Path,
    managed_output_dir: str | Path,
    *,
    output_filename: str = OUTPUT_FILENAME_DEFAULT,
    deadline: float | None = None,
    timeout_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> OriginalAudioRemuxResult:
    """Remux the canonical FIRST audio stream of *source_path*.

    Behavior (TASK.md Required behavior 1-10):

    1. Resolves the canonical first audio stream (``-select_streams a:0``).
    2. AAC → stream-copy; any other codec → AAC transcode (192 kbit/s).
    3. No audio → explicit ``NO_AUDIO_PRESENT`` result; nothing published.
    4. Corrupt sources fail closed with stable error codes.
    5. FFmpeg/ffprobe list args, ``shell=False``, bounded stdout/stderr.
    6. Deadline/remaining-budget bounded; cancellation kills the child tree.
    7. Cleanup consumes only the remaining budget; no orphan survives.
    8. Managed-path containment; unique staging file; validate-then-publish
       atomically; partial output is never exposed at the published path.
    9. The staged output is probed (codec/duration/timebase) before publish;
       the source bytes are hashed before AND after and must be unchanged.
    10. No network, no GPU, no Demucs/ASR/TTS/dubbing — pure local remux.

    Args:
        source_path: Already-resolved source media path (read-only).
        managed_output_dir: Absolute managed directory owning the output.
        output_filename: Single-component published file name.
        deadline: Optional monotonic deadline overriding ``timeout_seconds``.
        timeout_seconds: Optional wall-clock budget from now.
        cancel_event: Optional cooperative cancellation signal.
        max_output_bytes: Fail-closed ceiling on the staged output size.

    Returns:
        :class:`OriginalAudioRemuxResult` (``status`` is one of
        ``STREAM_COPY`` / ``TRANSCODE`` / ``NO_AUDIO_PRESENT``).

    Raises:
        OriginalAudioRemuxError: On any fail-closed condition (stable
            ``code``); nothing is ever published on a raise.
    """
    source = Path(source_path)
    if not source.exists():
        raise OriginalAudioRemuxError(
            CODE_SOURCE_NOT_FOUND, f"source not found: {source}"
        )
    if not source.is_file():
        raise OriginalAudioRemuxError(
            CODE_SOURCE_NOT_A_FILE, f"source is not a file: {source}"
        )

    target = _resolve_managed_target(managed_output_dir, output_filename)
    managed_resolved = target.parent
    managed_resolved.mkdir(parents=True, exist_ok=True)

    if deadline is None:
        budget = (
            timeout_seconds
            if timeout_seconds is not None
            else DEFAULT_REMUX_TIMEOUT_SECONDS
        )
        deadline = time.monotonic() + max(0.0, float(budget))

    source_sha256 = _sha256_file(source)
    source_size_bytes = source.stat().st_size

    # ── Phase 1: bounded source probe ────────────────────────────────────
    data = _probe_streams(
        source, deadline=deadline, cancel_event=cancel_event
    )
    video_codec = _validate_source_container_and_video(data, source=source)

    audio = _first_stream(data, "audio")
    if audio is None:
        # Frozen decision §5: explicit NO_AUDIO_PRESENT, no fabricated audio,
        # nothing published.
        #
        # R6-F3: a successful terminal outcome STILL honors the
        # source-unmutated invariant — re-hash the source here and fail
        # closed on any drift (zero target: nothing was ever staged or
        # published on this path).  A durable cancel observed at this
        # terminal boundary also wins (CANCELLED), never a success result.
        if cancel_event is not None and cancel_event.is_set():
            raise OriginalAudioRemuxError(
                CODE_CANCELLED,
                "operation cancelled at the no-audio terminal boundary",
            )
        post_source_sha256 = _sha256_file(source)
        if post_source_sha256 != source_sha256:
            raise OriginalAudioRemuxError(
                CODE_SOURCE_MUTATED,
                f"source bytes changed during the remux: {source}",
            )
        # Re-check AFTER the integrity gate too: a durable cancel racing
        # the terminal publication must win over a SUCCESS result.
        if cancel_event is not None and cancel_event.is_set():
            raise OriginalAudioRemuxError(
                CODE_CANCELLED,
                "operation cancelled right before the no-audio result",
            )
        return OriginalAudioRemuxResult(
            status=STATUS_NO_AUDIO_PRESENT,
            error_code=None,
            source_path=str(source),
            source_sha256=source_sha256,
            source_size_bytes=source_size_bytes,
            post_remux_source_sha256=post_source_sha256,
            video_codec=video_codec,
            command=(),
            checkpoint=_build_checkpoint(
                status=STATUS_NO_AUDIO_PRESENT,
                mode=None,
                source_sha256=source_sha256,
                source_size_bytes=source_size_bytes,
                source_audio_codec=None,
                source_audio_duration=None,
                output_audio_codec=None,
                output_audio_duration=None,
                audio_time_base=None,
                video_codec=video_codec,
                output_sha256=None,
                output_size_bytes=None,
            ),
        )

    source_audio_codec = str(audio.get("codec_name") or "")
    source_audio_index = audio.get("index")
    source_audio_duration = _parse_decimal(audio.get("duration"))
    if source_audio_duration is None:
        fmt = data.get("format")
        if isinstance(fmt, dict):
            source_audio_duration = _parse_decimal(fmt.get("duration"))
    if source_audio_duration is None or source_audio_duration <= 0:
        raise OriginalAudioRemuxError(
            CODE_CORRUPT_SOURCE,
            f"source audio duration unknown or non-positive for {source.name}",
        )

    # ── Phase 2: stage the remux (unique staging file, atomic later) ─────
    ffmpeg = _find_ffmpeg_or_raise()
    staging = target.with_name(
        f".{target.stem}.{uuid.uuid4().hex}.staging{target.suffix}"
    )
    # Contract §4.1: AAC → stream-copy when safe; if the copy attempt fails
    # (codec-in-container mismatch), fall back to transcode and RECORD which
    # path was taken — never a silent fallback.
    copy_mode = source_audio_codec == "aac"
    copy_fallback = False
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source),
        "-map", "0:v:0",
        # Canonical FIRST audio stream: 0:a:0 is the first AUDIO stream
        # specifier (the container index is recorded as evidence in
        # the checkpoint, not used for mapping).
        "-map", "0:a:0",
        "-c:v", "copy",
    ]
    if copy_mode:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", _TRANSCODE_AUDIO_BITRATE]
    # Bitexact muxing/encoding: identical inputs → byte-identical outputs
    # (verified empirically for BOTH the copy and the transcode path).
    cmd += ["-fflags", "+bitexact", "-flags:a", "+bitexact", str(staging)]

    try:
        run = _run_bounded(
            cmd,
            deadline=deadline,
            cancel_event=cancel_event,
            staging_path=staging,
            max_output_bytes=max_output_bytes,
        )
    except OriginalAudioRemuxError:
        with contextlib.suppress(OSError):
            staging.unlink(missing_ok=True)
        raise
    except FileNotFoundError as exc:
        with contextlib.suppress(OSError):
            staging.unlink(missing_ok=True)
        raise OriginalAudioRemuxError(
            CODE_FFMPEG_NOT_FOUND, f"ffmpeg not found: {exc}"
        ) from exc

    if run.returncode != 0:
        if not copy_mode:
            # Transcode path failed: fail closed (no second profile).
            with contextlib.suppress(OSError):
                staging.unlink(missing_ok=True)
            raise OriginalAudioRemuxError(
                CODE_FFMPEG_FAILED,
                f"ffmpeg failed with exit code {run.returncode}: "
                f"{run.stderr.strip()[:300]}",
            )
        # Contract §4.1 fallback: stream-copy unsafe → transcode, recorded.
        copy_fallback = True
        copy_mode = False
        cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(source),
            "-map", "0:v:0",
            # Canonical FIRST audio stream: 0:a:0 is the first AUDIO stream
        # specifier (the container index is recorded as evidence in
        # the checkpoint, not used for mapping).
        "-map", "0:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", _TRANSCODE_AUDIO_BITRATE,
            "-fflags", "+bitexact", "-flags:a", "+bitexact", str(staging),
        ]
        try:
            run = _run_bounded(
                cmd,
                deadline=deadline,
                cancel_event=cancel_event,
                staging_path=staging,
                max_output_bytes=max_output_bytes,
            )
        except OriginalAudioRemuxError:
            with contextlib.suppress(OSError):
                staging.unlink(missing_ok=True)
            raise
        if run.returncode != 0:
            with contextlib.suppress(OSError):
                staging.unlink(missing_ok=True)
            raise OriginalAudioRemuxError(
                CODE_FFMPEG_FAILED,
                f"ffmpeg failed with exit code {run.returncode} on both the "
                f"stream-copy and the transcode fallback: "
                f"{run.stderr.strip()[:300]}",
            )

    # ── Phase 3: validate the STAGED output BEFORE publishing ───────────
    try:
        _validate_staged_output(
            staging,
            target=target,
            source_audio_duration=source_audio_duration,
            max_output_bytes=max_output_bytes,
            deadline=deadline,
            cancel_event=cancel_event,
        )
    except OriginalAudioRemuxError:
        with contextlib.suppress(OSError):
            staging.unlink(missing_ok=True)
        raise

    staged_probe = _probe_media(
        staging, deadline=deadline, cancel_event=cancel_event
    )
    staged_audio = _first_stream(staged_probe, "audio")
    staged_audio_codec = (
        str(staged_audio.get("codec_name") or "") if staged_audio else ""
    )
    staged_time_base = (
        str(staged_audio.get("time_base") or "") if staged_audio else ""
    )
    staged_audio_duration = (
        _parse_decimal(staged_audio.get("duration")) if staged_audio else None
    )

    # ── Phase 4: atomic publish (os.replace, same directory/filesystem) ──
    # Flush the staging file to stable storage BEFORE the rename: open a
    # fresh writable handle (the remux child already closed its own).
    staging_fd = os.open(staging, os.O_RDWR)
    try:
        os.fsync(staging_fd)
    finally:
        os.close(staging_fd)

    # ── Phase 5: source-bytes-unchanged invariant (behavior 9) ──────────
    # Verified BEFORE publication: ``SOURCE_MUTATED`` must never co-exist
    # with a published target (fail-closed ordering).  Any mismatch cleans
    # the staging residue and raises without publishing.
    post_source_sha256 = _sha256_file(source)
    if post_source_sha256 != source_sha256:
        with contextlib.suppress(OSError):
            staging.unlink(missing_ok=True)
        raise OriginalAudioRemuxError(
            CODE_SOURCE_MUTATED,
            f"source bytes changed during the remux: {source}",
        )

    os.replace(staging, target)

    output_sha256 = _sha256_file(target)
    output_size_bytes = target.stat().st_size
    status = STATUS_STREAM_COPY if copy_mode else STATUS_TRANSCODE
    mode = "stream_copy" if copy_mode else "transcode"
    checkpoint = _build_checkpoint(
        status=status,
        mode=mode,
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
        source_audio_codec=source_audio_codec,
        source_audio_duration=_decimal6(source_audio_duration),
        output_audio_codec=staged_audio_codec or "aac",
        output_audio_duration=_decimal6(staged_audio_duration),
        audio_time_base=staged_time_base or None,
        video_codec=video_codec,
        output_sha256=output_sha256,
        output_size_bytes=output_size_bytes,
    )
    # Contract §2 selection evidence + §4.1 fallback record (content-derived).
    if isinstance(source_audio_index, int):
        checkpoint["audio_stream_index"] = source_audio_index
    if copy_fallback:
        checkpoint["copy_fallback"] = "stream_copy_unsafe_transcoded"
    return OriginalAudioRemuxResult(
        status=status,
        error_code=None,
        source_path=str(source),
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
        post_remux_source_sha256=post_source_sha256,
        output_path=str(target),
        output_sha256=output_sha256,
        output_size_bytes=output_size_bytes,
        source_audio_codec=source_audio_codec,
        output_audio_codec=staged_audio_codec or "aac",
        source_audio_duration=_decimal6(source_audio_duration),
        output_audio_duration=_decimal6(staged_audio_duration),
        audio_time_base=staged_time_base or None,
        video_codec=video_codec,
        command=tuple(cmd),
        checkpoint=checkpoint,
    )


def _find_ffmpeg_or_raise() -> str:
    """Resolve ffmpeg, mapping discovery failure to the stable code."""
    try:
        return find_ffmpeg()
    except FileNotFoundError as exc:
        raise OriginalAudioRemuxError(
            CODE_FFMPEG_NOT_FOUND, f"ffmpeg not found: {exc}"
        ) from exc


def _probe_media(
    path: Path,
    *,
    deadline: float,
    cancel_event: threading.Event | None,
) -> dict[str, Any]:
    """Bounded ffprobe of a produced file (validation-time probe)."""
    ffprobe = find_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,time_base,duration",
        str(path),
    ]
    try:
        run = _run_bounded(cmd, deadline=deadline, cancel_event=cancel_event)
    except FileNotFoundError as exc:
        raise OriginalAudioRemuxError(
            CODE_FFMPEG_NOT_FOUND, f"ffprobe not found: {exc}"
        ) from exc
    if run.returncode != 0:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED,
            f"staged output probe failed: {run.stderr.strip()[:300]}",
        )
    try:
        data = json.loads(run.stdout)
    except ValueError as exc:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "staged output probe is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "staged output probe is not a JSON object"
        )
    return data


def _validate_staged_output(
    staging: Path,
    *,
    target: Path,
    source_audio_duration: float,
    max_output_bytes: int,
    deadline: float,
    cancel_event: threading.Event | None,
) -> None:
    """Fail closed unless the STAGED file satisfies the output contract.

    Checks (before any publish): existence, size cap, exactly-parseable
    streams, first audio codec == aac, positive audio timebase, and audio
    duration within the AAC-framing tolerance of the source duration.
    """
    if not staging.exists() or staging.stat().st_size == 0:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "staged output is missing or empty"
        )
    if staging.stat().st_size > max_output_bytes:
        raise OriginalAudioRemuxError(
            CODE_OUTPUT_CAP_EXCEEDED,
            f"staged output {staging.stat().st_size} bytes exceeds the "
            f"{max_output_bytes}-byte cap",
        )
    data = _probe_media(staging, deadline=deadline, cancel_event=cancel_event)
    streams = data.get("streams")
    if not isinstance(streams, list) or not streams:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "staged output declares no streams"
        )
    if len(streams) > _MAX_STREAMS:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED,
            f"staged output declares {len(streams)} streams; refusing to "
            f"parse beyond the {_MAX_STREAMS}-stream ceiling",
        )
    staged_audio = _first_stream(data, "audio")
    if staged_audio is None:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "staged output has no audio stream"
        )
    staged_codec = str(staged_audio.get("codec_name") or "")
    if staged_codec != "aac":
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED,
            f"staged first audio codec is {staged_codec!r}, expected 'aac'",
        )
    time_base = _parse_positive_fraction(staged_audio.get("time_base"))
    if time_base is None:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED,
            f"staged audio time_base is not a positive rational: "
            f"{staged_audio.get('time_base')!r}",
        )
    staged_duration = _parse_decimal(staged_audio.get("duration"))
    if staged_duration is None:
        fmt = data.get("format")
        if isinstance(fmt, dict):
            staged_duration = _parse_decimal(fmt.get("duration"))
    if staged_duration is None:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "staged audio duration unknown"
        )
    tolerance = max(
        _DURATION_TOLERANCE_ABSOLUTE,
        abs(source_audio_duration) * _DURATION_TOLERANCE_RELATIVE,
    )
    if abs(staged_duration - source_audio_duration) > tolerance:
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED,
            f"staged audio duration {staged_duration:.6f}s deviates from the "
            f"source audio duration {source_audio_duration:.6f}s by more "
            f"than the {tolerance:.3f}s tolerance",
        )
