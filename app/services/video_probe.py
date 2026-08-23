"""Video probe service — extracts metadata from video files using ffprobe.

S08-H02-C2 bounded-output contract: the ffprobe subprocess is run with an
explicit stdout/stderr SIZE CEILING (``PROBE_MAX_OUTPUT_BYTES``) and timeout,
and queries ONLY the required fields for the FIRST relevant streams
(``-select_streams v:0`` / ``a:0`` + ``-show_entries``) instead of
``-show_streams``.  Oversized, malformed or non-terminating probe output fails
closed (:class:`ProbeOutputTooLargeError`` / ``subprocess.TimeoutExpired`` /
``RuntimeError``) — callers must never publish media when the probe fails.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from pathlib import Path

from app.schemas import VideoMetadata
from app.services.ffmpeg_utils import find_ffprobe

#: Hard ceiling (bytes) for ffprobe stdout/stderr.  The restricted probe output
#: is <16 KiB; this bound is far larger yet still fails closed well below
#: anything a hostile container could weaponize for unbounded capture/parse.
PROBE_MAX_OUTPUT_BYTES = 1 * 1024 * 1024

#: Fail-closed ceiling on the number of parsed streams (the query requests a
#: single stream; anything beyond this many is refused).
PROBE_MAX_STREAMS = 4

#: Default bounded timeout for a single ffprobe invocation (seconds).
_PROBE_TIMEOUT_SECONDS = 30.0


class ProbeOutputTooLargeError(RuntimeError):
    """ffprobe produced more output than the bounded-output contract allows."""


def _to_int(value: object, default: int) -> int:
    """Best-effort int conversion of an ffprobe JSON value (never raises)."""
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _to_float(value: object, default: float) -> float:
    """Best-effort float conversion of an ffprobe JSON value (never raises)."""
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default


class _CaptureState:
    """Shared, thread-safe state for the two concurrent pipe readers.

    ``count`` tracks the COMBINED retained stdout+stderr byte total against
    ``cap``; :meth:`accept` makes the keep/reject decision for each chunk
    ATOMICALLY under one lock (S08-H02-C5 Finding 1) and sets ``abort``
    exactly once the moment the combined ceiling is exceeded, so the sibling
    reader can neither keep counting nor append a new chunk after that, and
    the combined observed overshoot of the retained bytes is no larger than
    one reader chunk.
    """

    __slots__ = ("count", "cap", "abort", "_lock")

    def __init__(self, cap: int) -> None:
        self.count = 0
        self.cap = cap
        self.abort = threading.Event()
        self._lock = threading.Lock()

    def accept(self, n: int) -> bool:
        """Atomically account for a *n*-byte chunk under the state lock.

        Returns True when the chunk is RETAINED (the combined total stays at
        or below ``cap``); False when the cap would be exceeded — the chunk
        is DISCARDED and ``abort`` is set exactly once.  After abort no chunk
        is ever counted or retained again, so retained output can never grow
        past the boundary and the combined overshoot of the retained bytes is
        at most one reader chunk.
        """
        with self._lock:
            if self.abort.is_set():
                return False
            new_count = self.count + n
            if new_count > self.cap:
                self.abort.set()
                return False
            self.count = new_count
            return True


class _PipeReader(threading.Thread):
    """Drain ONE BINARY pipe in bounded chunks until EOF or the cap aborts.

    Runs as a daemon so the two streams can be drained CONCURRENTLY (a pipe
    whose buffer fills can never block the other stream) while the timeout is
    owned by the main thread.  Killing the child closes the write end, which
    unblocks a pending :meth:`read` and lets the thread exit promptly.

    S08-H02-C4 (Finding 2): the pipe is read as RAW BYTES and the byte count
    uses the true ``len(bytes)``, so a multibyte UTF-8 stream can never slip
    past the byte ceiling.  S08-H02-C5 (Finding 1): each chunk is submitted to
    the shared :meth:`_CaptureState.accept` which atomically decides keep vs
    reject; a chunk that trips the cap is discarded (never appended) and abort
    is set exactly once, so retained output can never grow after abort.
    """

    def __init__(self, state: _CaptureState, stream: object, label: str) -> None:
        super().__init__(daemon=True, name=f"ffprobe-{label}-reader")
        self.state = state
        self.stream = stream
        self.label = label
        self.chunks: list[bytes] = []
        self.exc: BaseException | None = None

    def run(self) -> None:
        try:
            while not self.state.abort.is_set():
                chunk = self.stream.read(8192)  # type: ignore[attr-defined]  # binary pipe
                if chunk == b"":
                    break
                # Atomic keep/reject under one lock: a chunk at/under the cap
                # is retained; a chunk that would exceed it is DISCARDED and
                # abort is set exactly once (no append, no further counting).
                if self.state.accept(len(chunk)):
                    self.chunks.append(chunk)
        except BaseException as exc:  # pragma: no cover - defensive
            self.exc = exc


def remaining_budget(deadline: float) -> float:
    """Seconds left before *deadline* on the monotonic clock, floored at 0.

    This is the SINGLE shared budget helper for the probe path (S08-H02-C5
    Finding 2): every wait/join — child reap, pipe-drop, reader joins — passes
    ``remaining_budget(deadline)`` so cleanup can never grant the child or a
    reader a fresh fixed window after the deadline.  When the budget is 0 the
    helpers only reap/poll WITHOUT blocking.
    """
    return max(0.0, deadline - time.monotonic())


def _drop_stream(stream: object) -> None:
    """Best-effort close of a pipe read-end to unblock its daemon reader.

    Only used in the cleanup path when a reader is still attached after the
    child was killed (a killed child normally closes its own write ends, but a
    grandchild that inherited them can keep the reader blocked).  Closing our
    read end makes the blocked :meth:`~_PipeReader.run` unblock promptly; the
    reader records any exception and exits — it never holds the caller.
    """
    with contextlib.suppress(OSError, ValueError):
        stream.close()  # type: ignore[attr-defined]


def _kill_proc(proc: subprocess.Popen[bytes], deadline: float) -> None:
    """Terminate the full child process, then reap using ONLY the remaining
    deadline budget (S08-H02-C5 Finding 2: no fixed wait window).

    ``kill`` always precedes the wait, so the child is never granted further
    execution time.  With budget left we wait up to that budget; with no
    budget we reap/poll WITHOUT blocking — the OS reclaims the killed child
    asynchronously, never at the caller's expense.
    """
    if proc.poll() is None:
        with contextlib.suppress(OSError):
            proc.kill()
    budget = remaining_budget(deadline)
    if budget > 0:
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=budget)
    else:
        proc.poll()  # non-blocking reap only; never block past the deadline


def _run_ffprobe(
    cmd: list[str], *, timeout: float = _PROBE_TIMEOUT_SECONDS
) -> tuple[int, str, str]:
    """Run *cmd* with a hard combined output ceiling + enforced deadline.

    stdout and stderr are drained CONCURRENTLY by two daemon reader threads so
    a single pipe whose buffer fills can never block the other stream (no
    deadlock), and the deadline is enforced by the MAIN thread — a child that
    produces no output (or a newline-less stream) can no longer block past
    *timeout*.  Exceeding the combined byte ceiling or the deadline kills and
    reaps the full child, then raises — the caller must translate that into a
    probe failure (never a silent partial parse).

    S08-H02-C4 (Finding 2): the pipes are read as RAW BYTES and the combined
    ``len(bytes)`` is counted BEFORE any decoding, so a multibyte UTF-8 stream
    counts its true byte weight against the ceiling.  UTF-8/errors=replace
    decoding happens ONLY after the child has terminated and the byte cap
    passed.  S08-H02-C4 (Finding 3): every wait uses only the REMAINING
    deadline budget (``max(0, deadline - monotonic())``) — never a fresh full
    timeout window after the readers reach EOF.

    Returns ``(returncode, stdout, stderr)``.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None
    state = _CaptureState(PROBE_MAX_OUTPUT_BYTES)
    out_reader = _PipeReader(state, proc.stdout, "stdout")
    err_reader = _PipeReader(state, proc.stderr, "stderr")
    deadline = time.monotonic() + timeout
    out_reader.start()
    err_reader.start()
    try:
        # The MAIN thread owns both enforced conditions while the reader
        # threads drain concurrently.  Poll tightly so an abort (combined cap)
        # or the deadline raises promptly — never after a blocked pipe read.
        while True:
            if state.abort.is_set():
                _kill_proc(proc, deadline)
                raise ProbeOutputTooLargeError(
                    f"ffprobe output exceeded the combined "
                    f"{PROBE_MAX_OUTPUT_BYTES}-byte ceiling"
                )
            if remaining_budget(deadline) <= 0:
                _kill_proc(proc, deadline)
                raise subprocess.TimeoutExpired(cmd, timeout)
            if not out_reader.is_alive() and not err_reader.is_alive():
                break
            time.sleep(0.01)
        # Both streams hit EOF -> the child has closed its pipes.  Reap it
        # with only the REMAINING deadline budget; no budget left means kill
        # and fail immediately (C4 Finding 3 / C5 Finding 2 — never a second
        # full window, and never a fixed cleanup timeout).
        budget = remaining_budget(deadline)
        if budget <= 0:
            _kill_proc(proc, deadline)
            raise subprocess.TimeoutExpired(cmd, timeout)
        try:
            proc.wait(timeout=budget)
        except subprocess.TimeoutExpired:
            _kill_proc(proc, deadline)
            raise subprocess.TimeoutExpired(cmd, timeout) from None
    finally:
        if proc.poll() is None:
            _kill_proc(proc, deadline)
        # Unblock any reader still attached (a killed child normally closes
        # its pipe write ends; if a grandchild inherited them, dropping our
        # read ends unblocks the daemon).  Reap/join use ONLY the remaining
        # deadline budget — never a fresh fixed window.
        for reader, stream in (
            (out_reader, proc.stdout),
            (err_reader, proc.stderr),
        ):
            if reader.is_alive():
                _drop_stream(stream)
        with contextlib.suppress(Exception):
            out_reader.join(timeout=remaining_budget(deadline))
        with contextlib.suppress(Exception):
            err_reader.join(timeout=remaining_budget(deadline))
    # Child terminated + byte cap passed: decode only now (C4 Finding 2).
    out_text = b"".join(out_reader.chunks).decode("utf-8", errors="replace")
    err_text = b"".join(err_reader.chunks).decode("utf-8", errors="replace")
    return proc.returncode, out_text, err_text


def _bounded_json(stdout: str, cmd: list[str]) -> dict[str, object]:
    """Parse probe stdout as a JSON object; malformed output fails closed."""
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise RuntimeError("ffprobe stdout is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("ffprobe stdout is not a JSON object")
    return data


def probe_video(video_path: str | Path) -> VideoMetadata:
    """Extract video metadata using ffprobe (bounded, first relevant stream).

    Args:
        video_path: Path to the video file.

    Returns:
        VideoMetadata with all fields populated.

    Raises:
        FileNotFoundError: If video or ffprobe not found.
        RuntimeError: If ffprobe fails, the output exceeds the bounded-output
            contract, or the file has no valid video stream.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    ffprobe = find_ffprobe()

    # Video probe: only the FIRST video stream and only the needed fields.
    video_cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-select_streams", "v:0",
        "-show_entries",
        "format=filename,duration,size:"
        "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames",
        str(video_path),
    ]
    rc, stdout, stderr = _run_ffprobe(video_cmd)
    if rc != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.strip()[:300]}")
    data = _bounded_json(stdout, video_cmd)

    streams = data.get("streams")
    if not isinstance(streams, list):
        raise RuntimeError("ffprobe returned no stream section")
    if len(streams) > PROBE_MAX_STREAMS:
        raise RuntimeError(
            f"video declares {len(streams)} streams; refusing to parse beyond "
            f"the {PROBE_MAX_STREAMS}-stream ceiling"
        )
    video_stream: dict[str, object] | None = None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            video_stream = stream
            break
    if video_stream is None:
        raise RuntimeError("No video stream found in file")

    # Audio probe: only the FIRST audio stream's existence + codec (bounded).
    audio_cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type,codec_name",
        str(video_path),
    ]
    a_rc, a_stdout, _ = _run_ffprobe(audio_cmd)
    has_audio = False
    audio_codec: str | None = None
    if a_rc == 0:
        a_data = _bounded_json(a_stdout, audio_cmd)
        a_streams = a_data.get("streams")
        if isinstance(a_streams, list) and a_streams:
            first = a_streams[0]
            if isinstance(first, dict) and first.get("codec_type") == "audio":
                has_audio = True
                audio_codec = str(first.get("codec_name")) if first.get("codec_name") else None

    # Parse FPS from r_frame_rate (e.g. "30000/1001").
    fps_str = str(video_stream.get("r_frame_rate", "30/1"))
    if "/" in fps_str:
        num, den = fps_str.split("/", 1)
        fps = float(num) / float(den)
    else:
        fps = float(fps_str)

    fmt = data.get("format")
    if not isinstance(fmt, dict):
        raise RuntimeError("ffprobe returned no format section")
    # Duration / size: best-effort numeric parse (fail-closed on garbage).
    duration = _to_float(fmt.get("duration"), 0.0)
    file_size = _to_int(fmt.get("size"), 0)

    total_frames = _to_int(video_stream.get("nb_frames"), 0)
    if total_frames == 0:
        total_frames = int(round(duration * fps))

    width = _to_int(video_stream.get("width"), 0)
    height = _to_int(video_stream.get("height"), 0)

    # Decoder sanity limits (S08-H02): refuse absurd dimensions so a hostile
    # container can never drive an unbounded decode/display allocation.
    from app.config import config as app_config  # noqa: PLC0415

    max_dim = int(app_config.max_image_dimension)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Video has invalid dimensions {width}x{height}")
    if width > max_dim or height > max_dim:
        raise RuntimeError(
            f"Video dimensions {width}x{height} exceed the maximum allowed "
            f"side of {max_dim}px"
        )

    return VideoMetadata(
        width=width,
        height=height,
        fps=round(fps, 3),
        duration_seconds=round(duration, 3),
        total_frames=total_frames,
        codec=str(video_stream.get("codec_name", "unknown")),
        has_audio=has_audio,
        audio_codec=audio_codec,
        file_size_bytes=file_size,
        file_path=str(video_path.resolve()),
    )


def extract_audio(video_path: str | Path, output_path: str | Path) -> Path:
    """Extract audio track from video to a separate file.

    Args:
        video_path: Source video.
        output_path: Where to save the audio (e.g. .aac or .wav).

    Returns:
        Path to the extracted audio file.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from app.services.ffmpeg_utils import find_ffmpeg
    ffmpeg = find_ffmpeg()

    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-vn",           # No video
        "-acodec", "copy",  # Copy codec (no re-encode)
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr}")

    return output_path
