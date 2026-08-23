"""S11-T01B — Original Audio Remux Engine required tests (binary 1-16).

Every test is self-contained: temp media is generated with FFmpeg
lavfi/anullsrc sources (skipped cleanly when FFmpeg is unavailable), the
database is never touched, the managed root is an isolated per-test temp
directory, and pytest runs with its own Windows-native ``--basetemp`` and
``-p no:cacheprovider`` (invoker contract).

Required-test map (TASK.md "Required tests (binary)"):

1.  test_01_aac_stream_copy_path            — AAC source → STREAM_COPY
2.  test_02_mp3_transcoded_to_aac           — MP3 source → TRANSCODE aac
3.  test_03_ac3_transcoded_to_aac           — AC-3 source → TRANSCODE aac
4.  test_04_pcm_opus_per_frozen_contract    — PCM/Opus → TRANSCODE aac
5.  test_05_no_audio_explicit_status        — NO_AUDIO_PRESENT, no publish
6.  test_06_corrupt_source_fails_closed     — CORRUPT_SOURCE, no publish
7.  test_07_multi_stream_selects_first_only — exactly one output audio
8.  test_08_duration_timebase_validation    — staged probe + tolerance
9.  test_09_validation_failure_no_publish   — injected bad output refused
10. test_10_path_escape_refused             — PATH_ESCAPE on escapes
11. test_11_output_cap_enforced             — OUTPUT_CAP_EXCEEDED, cleanup
12. test_12_timeout_cleanup_no_orphan       — DEADLINE_EXCEEDED, tree dead
13. test_13_cancellation_cleanup_no_orphan  — CANCELLED, tree dead
14. test_14_child_cleanup_on_ffmpeg_failure — corrupt child, tree dead
15. test_15_atomic_publication              — staging→validate→publish only
16. test_16_deterministic_result_checkpoint — byte-identical outputs
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from app.services.original_audio_remux import (
    CODE_CANCELLED,
    CODE_CORRUPT_SOURCE,
    CODE_DEADLINE_EXCEEDED,
    CODE_OUTPUT_CAP_EXCEEDED,
    CODE_PATH_ESCAPE,
    CODE_SOURCE_MUTATED,
    CODE_UNSUPPORTED_CONTAINER,
    CODE_UNSUPPORTED_VIDEO_CODEC,
    CODE_VALIDATION_FAILED,
    STATUS_NO_AUDIO_PRESENT,
    STATUS_STREAM_COPY,
    STATUS_TRANSCODE,
    OriginalAudioRemuxError,
    remux_original_audio,
)

# ── FFmpeg availability ──────────────────────────────────────────────────────


def _ffmpeg_bin() -> str | None:
    import shutil

    found = shutil.which("ffmpeg")
    if found is not None:
        return found
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / (
        "Microsoft/WinGet/Links/ffmpeg.exe"
    )
    return str(winget) if winget.is_file() else None


FFMPEG = _ffmpeg_bin()

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not available")


def _run_media_gen(args: list[str]) -> None:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_audio_streams(path: Path) -> list[dict]:
    ffprobe = str(Path(FFMPEG).with_name("ffprobe.exe")).replace(
        "ffprobe.exe", "ffprobe.exe"
    )
    if not Path(ffprobe).is_file():
        ffprobe = str(Path(FFMPEG).with_name("ffprobe"))
    out = subprocess.run(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-select_streams", "a",
            "-show_entries", "stream=index,codec_name",
            str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out).get("streams") or []


def probe_all_streams(path: Path) -> list[dict]:
    ffprobe = str(Path(FFMPEG).with_name("ffprobe.exe"))
    if not Path(ffprobe).is_file():
        ffprobe = str(Path(FFMPEG).with_name("ffprobe"))
    out = subprocess.run(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_entries", "stream=index,codec_type,codec_name",
            str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out).get("streams") or []


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def managed_root(tmp_path: Path) -> Path:
    """Isolated managed output root per test (never the repo or MAIN tree)."""
    root = tmp_path / "managed"
    root.mkdir()
    return root


@pytest.fixture()
def media_factory(tmp_path: Path):
    """Generate temp media with lavfi sources into the per-test temp dir."""
    counter = {"n": 0}

    def _make(name: str, args: list[str]) -> Path:
        counter["n"] += 1
        target = tmp_path / name
        _run_media_gen([*args, str(target)])
        return target

    return _make


def _av_source(
    media_factory, name: str, audio_args: str, audio_codec: list[str]
) -> Path:
    """A 2 s 320x240 H.264 clip with the requested first-audio codec."""
    return media_factory(
        name,
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
            "-f", "lavfi", "-i", audio_args,
            "-c:v", "libx264", "-preset", "ultrafast",
            *audio_codec,
        ],
    )


@pytest.fixture()
def aac_source(media_factory) -> Path:
    return _av_source(
        media_factory, "src_aac.mp4", "sine=frequency=440:duration=2",
        ["-c:a", "aac", "-b:a", "128k"],
    )


@pytest.fixture()
def mp3_source(media_factory) -> Path:
    return _av_source(
        media_factory, "src_mp3.mp4", "sine=frequency=440:duration=2",
        ["-c:a", "libmp3lame", "-b:a", "128k"],
    )


@pytest.fixture()
def ac3_source(media_factory) -> Path:
    return _av_source(
        media_factory, "src_ac3.mp4", "sine=frequency=300:duration=2",
        ["-c:a", "ac3", "-b:a", "192k"],
    )


@pytest.fixture()
def no_audio_source(media_factory) -> Path:
    return media_factory(
        "src_noaudio.mp4",
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast",
        ],
    )


def _published(managed_root: Path) -> Path:
    return managed_root / "original_audio.mp4"


# ── 1. AAC stream-copy path ──────────────────────────────────────────────────


def test_01_aac_stream_copy_path(aac_source, managed_root):
    """AAC first audio is stream-copied (mode stream_copy, -c:a copy)."""
    result = remux_original_audio(aac_source, managed_root)
    assert result.status == STATUS_STREAM_COPY
    assert result.error_code is None
    assert result.source_audio_codec == "aac"
    assert result.output_audio_codec == "aac"
    published = _published(managed_root)
    assert published.is_file() and published.stat().st_size > 0
    # The video stream is copied through; the audio codec stays AAC.
    codecs = {
        s["codec_type"]: s["codec_name"] for s in probe_all_streams(published)
    }
    assert codecs.get("video") in {"h264", "hevc"}
    assert codecs.get("audio") == "aac"
    # Stream copy: the remux command carries -c:a copy.
    assert "-c:a" in result.command
    assert result.command[result.command.index("-c:a") + 1] == "copy"
    # Checkpoint is schema-versioned and content-derived.
    assert result.checkpoint["schema_version"] == 1
    assert result.checkpoint["mode"] == "stream_copy"
    assert result.checkpoint["output_sha256"] == sha256_of(published)


# ── 2. MP3 → AAC ─────────────────────────────────────────────────────────────


def test_02_mp3_transcoded_to_aac(mp3_source, managed_root):
    """Non-AAC (MP3) first audio is transcoded to AAC."""
    result = remux_original_audio(mp3_source, managed_root)
    assert result.status == STATUS_TRANSCODE
    assert result.source_audio_codec == "mp3"
    assert result.output_audio_codec == "aac"
    published = _published(managed_root)
    codecs = {
        s["codec_type"]: s["codec_name"] for s in probe_all_streams(published)
    }
    assert codecs.get("audio") == "aac"
    assert result.command[result.command.index("-c:a") + 1] == "aac"
    assert result.checkpoint["mode"] == "transcode"


# ── 3. AC-3 → AAC ────────────────────────────────────────────────────────────


def test_03_ac3_transcoded_to_aac(ac3_source, managed_root):
    """Non-AAC (AC-3) first audio is transcoded to AAC."""
    result = remux_original_audio(ac3_source, managed_root)
    assert result.status == STATUS_TRANSCODE
    assert result.source_audio_codec == "ac3"
    assert result.output_audio_codec == "aac"
    published = _published(managed_root)
    audio = [
        s for s in probe_all_streams(published)
        if s["codec_type"] == "audio"
    ]
    assert len(audio) == 1 and audio[0]["codec_name"] == "aac"


# ── 4. PCM / Opus per frozen contract ────────────────────────────────────────


def test_04_pcm_opus_per_frozen_contract(media_factory, managed_root):
    """PCM and Opus first audio are non-AAC → transcoded to AAC (frozen §4)."""
    for name, codec in (("src_pcm.mp4", "pcm_s16le"), ("src_opus.mp4", "libopus")):
        source = _av_source(
            media_factory, name, "sine=frequency=300:duration=2",
            ["-c:a", codec],
        )
        result = remux_original_audio(source, managed_root)
        assert result.status == STATUS_TRANSCODE, name
        assert result.source_audio_codec == codec.replace("lib", ""), name
        assert result.output_audio_codec == "aac", name
        audio = [
            s for s in probe_all_streams(_published(managed_root))
            if s["codec_type"] == "audio"
        ]
        assert len(audio) == 1 and audio[0]["codec_name"] == "aac", name


# ── 5. No audio ──────────────────────────────────────────────────────────────


def test_05_no_audio_explicit_status(no_audio_source, managed_root):
    """A source without audio yields explicit NO_AUDIO_PRESENT; no publish."""
    result = remux_original_audio(no_audio_source, managed_root)
    assert result.status == STATUS_NO_AUDIO_PRESENT
    assert result.error_code is None
    assert result.output_path is None
    assert result.checkpoint["status"] == STATUS_NO_AUDIO_PRESENT
    assert not _published(managed_root).exists()
    # No staging residue either.
    assert list(managed_root.iterdir()) == []


# ── 6. Corrupt source ────────────────────────────────────────────────────────


def test_06_corrupt_source_fails_closed(tmp_path, managed_root):
    """A corrupt/garbage source fails closed with a stable code; no publish.

    Note: 4096 random bytes are USUALLY unparseable (``CORRUPT_SOURCE``),
    but ffprobe's format probing very rarely recognizes them as another
    container (measured ~0.75%: the ``lrc`` lyrics demuxer).  Either way
    the engine must fail closed — both stable codes are accepted; what is
    asserted strictly is no-publish and no residue.
    """
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(os.urandom(4096))
    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(corrupt, managed_root)
    assert excinfo.value.code in {CODE_CORRUPT_SOURCE, CODE_UNSUPPORTED_CONTAINER}
    assert not _published(managed_root).exists()
    # Truncated-but-real MP4 also fails closed (missing moov atom).
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2")
    with pytest.raises(OriginalAudioRemuxError) as excinfo2:
        remux_original_audio(truncated, managed_root)
    assert excinfo2.value.code == CODE_CORRUPT_SOURCE
    assert not _published(managed_root).exists()


# ── 7. Multi-stream selects first only ───────────────────────────────────────


def test_07_multi_stream_selects_first_only(media_factory, managed_root):
    """Only the FIRST audio stream is canonical: output has exactly one."""
    source = media_factory(
        "src_multi.mp4",
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "96k", "-strict", "-2",
        ],
    )
    assert len(probe_audio_streams(source)) == 2  # precondition: two audios
    result = remux_original_audio(source, managed_root)
    assert result.status == STATUS_STREAM_COPY
    published = _published(managed_root)
    audio_out = probe_audio_streams(published)
    assert len(audio_out) == 1
    assert audio_out[0]["codec_name"] == "aac"


# ── 8. Duration / timebase validation ────────────────────────────────────────


def test_08_duration_timebase_validation(aac_source, managed_root):
    """Published output is probe-validated: aac codec, positive timebase,
    audio duration within the AAC-framing tolerance of the source."""
    result = remux_original_audio(aac_source, managed_root)
    assert result.audio_time_base
    num, den = result.audio_time_base.split("/")
    assert int(num) > 0 and int(den) > 0
    src_dur = float(result.source_audio_duration)
    out_dur = float(result.output_audio_duration)
    tolerance = max(0.5, src_dur * 0.05)
    assert abs(out_dur - src_dur) <= tolerance
    assert result.checkpoint["audio_time_base"] == result.audio_time_base


# ── 9. Validation failure → no publish ───────────────────────────────────────


def test_09_validation_failure_no_publish(
    aac_source, managed_root, monkeypatch,
):
    """A staged output that fails validation is never published."""
    import app.services.original_audio_remux as engine

    def _bad_validate(*args, **kwargs):
        raise OriginalAudioRemuxError(
            CODE_VALIDATION_FAILED, "injected validation failure"
        )

    monkeypatch.setattr(engine, "_validate_staged_output", _bad_validate)
    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(aac_source, managed_root)
    assert excinfo.value.code == CODE_VALIDATION_FAILED
    assert not _published(managed_root).exists()
    # The staging file was cleaned up — the directory holds nothing.
    assert list(managed_root.iterdir()) == []


# ── 10. Path escape refusal ──────────────────────────────────────────────────


def test_10_path_escape_refused(aac_source, tmp_path):
    """Absolute/traversal/subdir output names are refused (PATH_ESCAPE)."""
    managed = tmp_path / "managed10"
    managed.mkdir()
    for bad in ("../escape.mp4", "sub/dir/out.mp4", "..\\escape2.mp4", "."):
        with pytest.raises(OriginalAudioRemuxError) as excinfo:
            remux_original_audio(aac_source, managed, output_filename=bad)
        assert excinfo.value.code == CODE_PATH_ESCAPE, bad
    # Absolute path as the filename is also an escape.
    with pytest.raises(OriginalAudioRemuxError) as excinfo_abs:
        remux_original_audio(
            aac_source, managed,
            output_filename=str((tmp_path / "outside.mp4").as_posix()),
        )
    assert excinfo_abs.value.code == CODE_PATH_ESCAPE
    assert not (tmp_path / "escape.mp4").exists()
    assert not (tmp_path / "outside.mp4").exists()


# ── 11. Output cap ───────────────────────────────────────────────────────────


def test_11_output_cap_enforced(media_factory, managed_root):
    """A staged output beyond the cap fails closed; staging is cleaned."""
    source = media_factory(
        "src_cap.mp4",
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
        ],
    )
    assert source.stat().st_size > 100_000  # precondition: real media
    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(source, managed_root, max_output_bytes=100_000)
    assert excinfo.value.code == CODE_OUTPUT_CAP_EXCEEDED
    assert not _published(managed_root).exists()
    assert list(managed_root.iterdir()) == []


# ── 12. Timeout cleanup ──────────────────────────────────────────────────────


def _owned_ffmpeg_pids(marker: str) -> set[int]:
    """PIDs of ffmpeg/ffprobe processes OWNED by this test run.

    Ownership is decided by TWO independent signals, and a pid counts as
    ours only if BOTH agree:
      1. process-tree: the process is a recursive descendant of THIS
         pytest process (psutil parent walk from os.getpid());
      2. command-line marker: *marker* — the run's managed-root path,
         unique per test via tmp_path — appears in its cmdline.
    A foreign suite's ffmpeg shares neither our tree nor our marker, so
    concurrent invocations can never cross-blame.

    NOTE (R4-P2): this scan only sees processes still attached to our
    tree AT CALL TIME.  It is the right primitive for DURING-RUN
    snapshots; post-run leak checks must poll the snapshot's fixed PID
    set instead (see _assert_no_orphans) because Windows re-parents
    orphaned children once their parent's handle closes.
    """
    me = psutil.Process(os.getpid())
    try:
        descendants = {p.pid for p in me.children(recursive=True)}
    except psutil.Error:
        descendants = set()

    owned: set[int] = set()
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.pid not in descendants:
                continue
            name = (proc.info["name"] or "").lower()
            if "ffmpeg" not in name and "ffprobe" not in name:
                continue
            cmdline = [str(a) for a in (proc.info["cmdline"] or [])]
            if any(marker in arg for arg in cmdline):
                owned.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
    return owned


class _OwnedPidRecorder:
    """Records every engine-spawned ffmpeg/ffprobe PID while the engine runs.

    R4-P2: wraps ``engine.subprocess_popen`` so each spawn is captured at
    creation time — BEFORE any chance of re-parenting.  The recorder also
    keeps a background sampler that repeatedly unions the tree∧marker scan
    into the same PID set, so any ffmpeg/ffprobe carrying THIS run's
    managed-root marker is tracked even if it was spawned by an indirect
    code path.  Cross-run isolation is preserved: another suite's
    processes carry a different managed-root path and are never recorded.
    """

    def __init__(self, engine_module, marker: str) -> None:
        self._engine = engine_module
        self._marker = marker
        self._real_popen = engine_module.subprocess_popen
        self.known_pids: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- capture layer -----------------------------------------------------
    def _popen_recorder(self, cmd):
        proc = self._real_popen(cmd)
        name = Path(cmd[0]).name.lower() if cmd else ""
        if "ffmpeg" in name or "ffprobe" in name:
            with self._lock:
                self.known_pids.add(proc.pid)
        return proc

    def _sampler(self) -> None:
        while not self._stop.is_set():
            for pid in _owned_ffmpeg_pids(self._marker):
                with self._lock:
                    self.known_pids.add(pid)
            self._stop.wait(0.05)

    # -- lifecycle -----------------------------------------------------------
    def __enter__(self) -> _OwnedPidRecorder:
        self._popen_recorder_ref = self._popen_recorder  # keep alive
        self._engine.subprocess_popen = self._popen_recorder
        self._thread = threading.Thread(target=self._sampler, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._engine.subprocess_popen = self._real_popen


def _assert_no_orphans(
    marker: str,
    known_pids: set[int] | None = None,
    deadline: float = 5.0,
) -> None:
    """Bounded-poll assertion that every run-owned child is reaped.

    Two phases (R4-P2 re-parent-proof):
      * known_pids given → poll EXACTLY those PIDs until each has exited
        or the deadline lapses.  This does NOT depend on the process
        still being in our descendant tree, so orphans whose parent died
        mid-run (re-parented on Windows) can never slip through.  A PID
        that got reused by a NON-ffmpeg process counts as exited (the
        name check guards against Windows PID-reuse false positives).
      * known_pids omitted → fall back to the during-run tree∧marker scan
        (only meaningful while the engine is still running).
    No fixed sleeps anywhere — bounded polling with a hard deadline only.
    """
    deadline_at = time.monotonic() + deadline

    if known_pids is not None:
        # psutil.Process(pid) raises NoSuchProcess for already-dead PIDs —
        # which is the desired end state, so tolerate it here.
        pending: dict[int, psutil.Process] = {}
        for pid in {int(p) for p in known_pids}:
            with contextlib.suppress(psutil.Error):
                pending[pid] = psutil.Process(pid)  # already gone → skipped

        def _survives(proc: psutil.Process) -> bool:
            try:
                name = (proc.name() or "").lower()
            except psutil.Error:
                return False  # gone — exactly what we want
            # PID alive AND still an ffmpeg/ffprobe: a real survivor.
            # If Windows reused the PID for some other binary, the name
            # check fails and the slot counts as exited.
            return proc.is_running() and (
                "ffmpeg" in name or "ffprobe" in name
            )

        while pending and time.monotonic() < deadline_at:
            pending = {
                pid: proc
                for pid, proc in pending.items()
                if _survives(proc)
            }
            if pending and time.monotonic() < deadline_at:
                time.sleep(0.05)
        assert not pending, (
            f"orphaned children of this run survived past deadline: "
            f"{sorted(pending)}"
        )
        return

    while True:
        alive = _owned_ffmpeg_pids(marker)
        if not alive or time.monotonic() >= deadline_at:
            assert not alive, f"orphaned children of this run: {alive}"
            return
        time.sleep(0.05)


def test_12_timeout_cleanup_no_orphan(tmp_path, managed_root):
    """A deadline breach kills the full child tree; no orphan, no publish."""
    # A ~300 s clip whose MP3→AAC transcode takes ~8 s: a 3 s deadline
    # deterministically breaches mid-encode.
    source = tmp_path / "long_mp3.mp4"
    if not source.exists():
        _run_media_gen(
            [
                "-f", "lavfi", "-i",
                "testsrc=size=320x240:rate=24:duration=300",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=300",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(source),
            ]
        )
    start = time.monotonic()
    import app.services.original_audio_remux as engine

    # R4-P2: snapshot run-owned PIDs DURING the run (spawn-wrap + sampler),
    # then poll that fixed PID set after the engine returns — re-parent-proof.
    with (
        _OwnedPidRecorder(engine, str(managed_root)) as recorder,
        pytest.raises(OriginalAudioRemuxError) as excinfo,
    ):
        remux_original_audio(source, managed_root, timeout_seconds=3.0)
    elapsed = time.monotonic() - start
    assert excinfo.value.code == CODE_DEADLINE_EXCEEDED
    assert elapsed < 10.0  # bounded: no fresh fixed window after the breach
    _assert_no_orphans(str(managed_root), known_pids=recorder.known_pids)
    assert not _published(managed_root).exists()
    assert list(managed_root.iterdir()) == []  # staging removed


# ── 13. Cancellation cleanup ─────────────────────────────────────────────────


def test_13_cancellation_cleanup_no_orphan(tmp_path, managed_root):
    """A cooperative cancel kills the full child tree; no orphan, no publish."""
    source = tmp_path / "long_mp3_c.mp4"
    if not source.exists():
        _run_media_gen(
            [
                "-f", "lavfi", "-i",
                "testsrc=size=320x240:rate=24:duration=300",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=300",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(source),
            ]
        )
    cancel_event = threading.Event()
    timer = threading.Timer(2.0, cancel_event.set)
    timer.start()
    start = time.monotonic()
    import app.services.original_audio_remux as engine

    # R4-P2: snapshot run-owned PIDs DURING the run, then poll the fixed
    # PID set after the engine returns — re-parent-proof.
    try:
        with (
            _OwnedPidRecorder(engine, str(managed_root)) as recorder,
            pytest.raises(OriginalAudioRemuxError) as excinfo,
        ):
            remux_original_audio(
                source, managed_root, cancel_event=cancel_event
            )
        elapsed = time.monotonic() - start
        assert excinfo.value.code == CODE_CANCELLED
        assert elapsed < 10.0
    finally:
        timer.cancel()
    _assert_no_orphans(str(managed_root), known_pids=recorder.known_pids)
    assert not _published(managed_root).exists()
    assert list(managed_root.iterdir()) == []


# ── 14. Child cleanup on ffmpeg failure ──────────────────────────────────────


def test_14_child_cleanup_on_ffmpeg_failure(
    aac_source, managed_root, monkeypatch,
):
    """When ffmpeg exits non-zero the child is reaped and nothing publishes.

    The engine's AAC path first tries stream-copy; the injected failure
    breaks BOTH attempts (copy + recorded transcode fallback), so the
    engine must fail closed with FFMPEG_FAILED and leave no residue.
    """
    import app.services.original_audio_remux as engine

    real_popen = engine.subprocess_popen
    fail_count = {"n": 0}

    def _popen_fail_remux(cmd):
        # Fail only REMUX invocations (ffmpeg writing a staging file);
        # probes (ffprobe) pass through untouched.
        if (
            fail_count["n"] < 2
            and "ffmpeg" in Path(cmd[0]).name.lower()
            and any(arg.endswith(".staging.mp4") for arg in cmd)
        ):
            fail_count["n"] += 1
            broken = list(cmd)
            # An unreadable input guarantees a fast non-zero exit.
            broken[broken.index("-i") + 1] = str(
                Path(cmd[-1]).parent / "definitely_missing_input.mp4"
            )
            return real_popen(broken)
        return real_popen(cmd)

    monkeypatch.setattr(engine, "subprocess_popen", _popen_fail_remux)
    # R4-P2: snapshot run-owned PIDs DURING the run, then poll the fixed
    # PID set after the engine returns — re-parent-proof.
    with (
        _OwnedPidRecorder(engine, str(managed_root)) as recorder,
        pytest.raises(OriginalAudioRemuxError) as excinfo,
    ):
        remux_original_audio(aac_source, managed_root)
    assert excinfo.value.code == "FFMPEG_FAILED"
    assert fail_count["n"] == 2  # copy attempt + transcode fallback both ran
    _assert_no_orphans(str(managed_root), known_pids=recorder.known_pids)
    assert not _published(managed_root).exists()
    assert list(managed_root.iterdir()) == []


# ── 15. Atomic publication ───────────────────────────────────────────────────


def test_15_atomic_publication(aac_source, managed_root):
    """Publication is atomic: unique staging → validate → os.replace.

    While the remux runs, the managed dir contains ONLY the staging file;
    after success the staging name is gone and the published name exists.
    """
    import app.services.original_audio_remux as engine

    observed: dict[str, list[str]] = {}
    real_popen = engine.subprocess_popen

    def _popen_observer(cmd):
        proc = real_popen(cmd)
        if "ffmpeg" in Path(cmd[0]).name.lower():
            # The child is now live: poll until the staging FILE appears
            # (ffmpeg creates it right after startup, bounded wait).
            deadline = time.monotonic() + 5.0
            names: list[str] = []
            while time.monotonic() < deadline:
                names = sorted(p.name for p in managed_root.iterdir())
                if any(n.endswith(".staging") for n in names):
                    break
                time.sleep(0.01)
            observed["at_start"] = names
        return proc

    engine.subprocess_popen = _popen_observer
    try:
        result = remux_original_audio(aac_source, managed_root)
    finally:
        engine.subprocess_popen = real_popen
    assert result.status == STATUS_STREAM_COPY
    # At child start the published name did NOT exist (staging only).
    assert "original_audio.mp4" not in observed["at_start"]
    staging_name = next(
        (n for n in observed["at_start"] if ".staging" in n), None
    )
    assert staging_name is not None, observed["at_start"]
    # After success: published exists, no staging residue.
    published = _published(managed_root)
    assert published.is_file()
    names = [p.name for p in managed_root.iterdir()]
    assert names == ["original_audio.mp4"]
    # The staging name recorded at start is unique per run (uuid-based).
    assert staging_name != "original_audio.mp4"


# ── 16. Deterministic result / checkpoint ────────────────────────────────────


def test_16_deterministic_result_checkpoint(aac_source, mp3_source, tmp_path):
    """Identical inputs → byte-identical outputs and equal checkpoints."""
    for source in (aac_source, mp3_source):
        dir_a = tmp_path / "det_a_run"
        dir_b = tmp_path / "det_b_run"
        dir_a.mkdir(exist_ok=True)
        dir_b.mkdir(exist_ok=True)
        result_a = remux_original_audio(source, dir_a)
        result_b = remux_original_audio(source, dir_b)
        assert result_a.status == result_b.status
        out_a = Path(result_a.output_path)
        out_b = Path(result_b.output_path)
        assert sha256_of(out_a) == sha256_of(out_b)
        assert result_a.checkpoint == result_b.checkpoint
        # The result dataclass itself is deterministic (paths differ by
        # design; every content field matches).
        assert result_a.source_sha256 == result_b.source_sha256
        assert result_a.output_sha256 == result_b.output_sha256
        assert result_a.audio_time_base == result_b.audio_time_base
        assert result_a.source_audio_duration == result_b.source_audio_duration


# ── Supplementary: container/codec refusals (frozen §2, fail closed) ─────────


def test_source_mutation_detected_before_publication(
    aac_source, managed_root, monkeypatch,
):
    """P1 regression: SOURCE_MUTATED ⇒ no published target, no residue.

    The source is mutated DETERMINISTICALLY between the engine's pre-hash
    and its pre-publication re-hash by monkeypatching the engine's single
    ``_sha256_file`` hook: calls against the SOURCE return a wrong digest
    only AFTER the first (pre-remux) hash — i.e. exactly at the re-hash
    that guards publication.  No sleeps, no races.  Asserts:
      (a) OriginalAudioRemuxError with stable code SOURCE_MUTATED;
      (b) the published target does NOT exist after the call;
      (c) no staging/temp residue remains in the managed dir.
    """
    import app.services.original_audio_remux as engine

    real_sha256 = engine._sha256_file
    seen = {"n": 0}

    def _sha256_mutating(path, *args, **kwargs):
        seen["n"] += 1
        digest = real_sha256(path, *args, **kwargs)
        if Path(path) == aac_source and seen["n"] > 1:
            # First call = legitimate pre-hash; every later SOURCE hash
            # (the pre-publication re-hash) sees mutated bytes' digest.
            return "0" * 64
        return digest

    monkeypatch.setattr(engine, "_sha256_file", _sha256_mutating)

    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(aac_source, managed_root)
    assert excinfo.value.code == CODE_SOURCE_MUTATED
    # (b) invariant: mutation detected ⇒ nothing published.
    assert not _published(managed_root).exists()
    # (c) staging residue cleaned: managed dir must be empty.
    assert list(managed_root.iterdir()) == []


def test_supplementary_container_and_codec_refusals(media_factory, tmp_path):
    """MKV container and non-H.264/HEVC video fail closed (frozen §2)."""
    mkv = media_factory(
        "src.mkv",
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        ],
    )
    managed = tmp_path / "managed_mkv"
    managed.mkdir()
    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(mkv, managed)
    assert excinfo.value.code == CODE_UNSUPPORTED_CONTAINER

    mpeg4 = media_factory(
        "src_mpeg4.mp4",
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "mpeg4", "-qscale:v", "20", "-c:a", "aac",
        ],
    )
    managed2 = tmp_path / "managed_mpeg4"
    managed2.mkdir()
    with pytest.raises(OriginalAudioRemuxError) as excinfo2:
        remux_original_audio(mpeg4, managed2)
    assert excinfo2.value.code == CODE_UNSUPPORTED_VIDEO_CODEC


def test_supplementary_missing_source(tmp_path, managed_root):
    """A missing source path fails closed with SOURCE_NOT_FOUND."""
    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(tmp_path / "ghost.mp4", managed_root)
    assert excinfo.value.code == "SOURCE_NOT_FOUND"


# ── R6 regressions (Codex round 6: F1 + F3) ─────────────────────────────────


def test_r6_f1_five_stream_source_accepted(media_factory, managed_root):
    """R6-F1: a valid H.264 MP4 with ≥5 streams is NOT rejected.

    The old probe read every stream and refused when the TOTAL exceeded
    the 4-stream ceiling (``source declares 5 streams`` → CORRUPT_SOURCE)
    even though the source was perfectly valid.  Per contract §1 the
    first audio is canonical and extra audio streams are ignored — so
    the engine must accept the file, publish exactly ONE audio stream
    (the canonical FIRST one), and never raise a stream-count error.
    """
    five_stream = media_factory(
        "src_five_stream.mp4",
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=1320:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=1760:duration=2",
            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a",
            "-map", "4:a",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "64k",
        ],
    )
    # Precondition: the fixture REALLY carries 5 streams (1 video + 4 audio).
    assert len(probe_all_streams(five_stream)) == 5

    result = remux_original_audio(five_stream, managed_root)
    # Acceptance 1+2: accepted; canonical FIRST audio stream-copied.
    assert result.status == STATUS_STREAM_COPY
    assert result.error_code is None
    published = _published(managed_root)
    assert published.is_file()
    out_streams = probe_all_streams(published)
    assert len(out_streams) == 2  # exactly 1 video + 1 audio
    audios = [s for s in out_streams if s.get("codec_type") == "audio"]
    assert len(audios) == 1
    assert audios[0]["codec_name"] == "aac"
    # The canonical selection is the FIRST audio stream of the source.
    assert result.source_audio_codec == "aac"


def test_r6_f3_no_audio_mutation_raises_source_mutated(
    no_audio_source, managed_root, monkeypatch,
):
    """R6-F3: NO_AUDIO_PRESENT keeps the source-unmutated invariant.

    The old no-audio path hashed the source before the probe and again
    just before returning SUCCESS, silently reporting two different
    digests.  Every successful terminal outcome must prove the source
    unchanged: a drift between pre-hash and terminal re-hash now raises
    SOURCE_MUTATED with zero target (nothing is ever staged/published
    on this path).  Deterministic via the single ``_sha256_file`` hook.
    """
    import app.services.original_audio_remux as engine

    real_sha256 = engine._sha256_file
    seen = {"n": 0}

    def _sha256_mutating(path, *args, **kwargs):
        seen["n"] += 1
        digest = real_sha256(path, *args, **kwargs)
        if Path(path) == no_audio_source and seen["n"] > 1:
            # Call 1 = legitimate pre-hash; the terminal re-hash on the
            # no-audio path sees mutated bytes' digest.
            return "f" * 64
        return digest

    monkeypatch.setattr(engine, "_sha256_file", _sha256_mutating)

    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(no_audio_source, managed_root)
    assert excinfo.value.code == CODE_SOURCE_MUTATED
    # Zero target / zero residue: the no-audio path publishes nothing.
    assert not _published(managed_root).exists()
    assert list(managed_root.iterdir()) == []


def test_r6_f3_no_audio_terminal_cancel_wins(
    no_audio_source, managed_root, monkeypatch,
):
    """R6-F3: cancel observed AT the no-audio terminal boundary wins.

    A durable cancel that fires while the engine is finishing must never
    be reported as a SUCCESS result: the terminal boundary re-checks the
    cancel_event and raises CANCELLED (zero target, zero residue).
    Deterministic: a ``_sha256_file`` hook flips the event exactly at
    the terminal re-hash — no sleeps, no races.
    """
    import app.services.original_audio_remux as engine

    real_sha256 = engine._sha256_file
    seen = {"n": 0}
    cancel_event = threading.Event()

    def _cancel_at_terminal_hash(path, *args, **kwargs):
        seen["n"] += 1
        digest = real_sha256(path, *args, **kwargs)
        if Path(path) == no_audio_source and seen["n"] == 2:
            # Call 2 = the terminal-boundary integrity hash; flip the
            # durable cancel EXACTLY there.
            cancel_event.set()
        return digest

    monkeypatch.setattr(engine, "_sha256_file", _cancel_at_terminal_hash)

    with pytest.raises(OriginalAudioRemuxError) as excinfo:
        remux_original_audio(
            no_audio_source, managed_root, cancel_event=cancel_event
        )
    assert excinfo.value.code == CODE_CANCELLED
    assert not _published(managed_root).exists()
    assert list(managed_root.iterdir()) == []


# ── Concurrency regression control (Codex round 3, P1) ───────────────────────


def _spawn_remux_worker(workdir: Path, tag: str) -> subprocess.Popen:
    """Launch an independent pytest process that remuxes a long clip.

    The worker runs the REAL engine against its own managed root under
    *workdir* (unique per invocation) and, after the remux call, asserts
    the ownership-scoped orphan check for ITS marker only.  Its stdout
    carries ``WORKER_<tag>_RESULT: <code>`` lines the caller parses.
    """
    worker_script = workdir / f"worker_{tag}.py"
    managed = workdir / f"managed_{tag}"
    managed.mkdir(parents=True, exist_ok=True)
    worker_script.write_text(
        "import sys, time, threading\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, r'{repo}')\n"
        "sys.path.insert(0, r'{tests_dir}')\n"
        "import psutil\n"
        "from app.services.original_audio_remux import (\n"
        "    OriginalAudioRemuxError, remux_original_audio,\n"
        ")\n"
        "\n"
        "# R4-P2 semantics inside the worker: record engine-spawned PIDs at\n"
        "# spawn time (re-parent-proof snapshot) and post-run poll EXACTLY\n"
        "# those PIDs — never a machine-wide name-only scan.\n"
        "class _Recorder:\n"
        "    def __init__(self, engine, marker):\n"
        "        self._engine = engine\n"
        "        self._marker = marker\n"
        "        self._real = engine.subprocess_popen\n"
        "        self.known = set()\n"
        "        self._lock = threading.Lock()\n"
        "\n"
        "    def popen(self, cmd):\n"
        "        proc = self._real(cmd)\n"
        "        name = Path(cmd[0]).name.lower() if cmd else ''\n"
        "        if 'ffmpeg' in name or 'ffprobe' in name:\n"
        "            with self._lock:\n"
        "                self.known.add(proc.pid)\n"
        "        return proc\n"
        "\n"
        "def poll_known_pids(known, deadline_s=5.0):\n"
        "    pending = {{}}\n"
        "    for pid in known:\n"
        "        try:\n"
        "            pending[pid] = psutil.Process(pid)\n"
        "        except psutil.Error:\n"
        "            pass\n"
        "    end = time.monotonic() + deadline_s\n"
        "    while pending and time.monotonic() < end:\n"
        "        alive = {{}}\n"
        "        for pid, proc in pending.items():\n"
        "            try:\n"
        "                nm = (proc.name() or '').lower()\n"
        "                if proc.is_running() and ('ffmpeg' in nm or 'ffprobe' in nm):\n"
        "                    alive[pid] = proc\n"
        "            except psutil.Error:\n"
        "                pass  # gone — good\n"
        "        pending = alive\n"
        "        if pending and time.monotonic() < end:\n"
        "            time.sleep(0.05)\n"
        "    return set(pending)\n"
        "\n"
        "marker = r'{managed}'\n"
        "src = Path(r'{source}')\n"
        "TAG = {tag!r}\n"
        "import app.services.original_audio_remux as engine\n"
        "rec = _Recorder(engine, marker)\n"
        "engine.subprocess_popen = rec.popen\n"
        "try:\n"
        "    result = remux_original_audio(src, marker, timeout_seconds=1.5)\n"
        "    print(f'WORKER_{{TAG}}_RESULT: UNEXPECTED_OK', flush=True)\n"
        "except OriginalAudioRemuxError as exc:\n"
        "    code = str(exc.code)\n"
        "    # Re-parent-proof: poll the FIXED pid set captured at spawn time;\n"
        "    # the check must NOT depend on processes still being descendants.\n"
        "    assert rec.known, 'no ffmpeg/ffprobe pids recorded during run'\n"
        "    survivors = poll_known_pids(rec.known)\n"
        "    status = 'CLEAN' if not survivors else f'ORPHANS={{sorted(survivors)}}'\n"
        "    print(f'WORKER_{{TAG}}_PIDS: {{len(rec.known)}}', flush=True)\n"
        "    print(f'WORKER_{{TAG}}_RESULT: {{code}} {{status}}', flush=True)\n",
        encoding="utf-8",
    )
    rendered = worker_script.read_text(encoding="utf-8").format(
        repo=str(Path(__file__).resolve().parents[1]),
        tests_dir=str(Path(__file__).resolve().parent),
        managed=str(managed),
        source=str(workdir / f"long_{tag}.mp4"),
        tag=tag,
    )
    worker_script.write_text(rendered, encoding="utf-8")

    # Shared long source per worker (300 s clip ⇒ 1.5 s timeout breaches).
    source = workdir / f"long_{tag}.mp4"
    if not source.exists():
        _run_media_gen(
            [
                "-f", "lavfi", "-i",
                "testsrc=size=320x240:rate=24:duration=300",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=300",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                "-c:a", "libmp3lame", "-b:a", "128k", str(source),
            ]
        )
    return subprocess.Popen(
        [sys.executable, str(worker_script)],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_concurrent_invocations_no_cross_blame(tmp_path):
    """Two independent engine invocations run SIMULTANEOUSLY.

    Each has its own basetemp-style workdir and managed root.  Both hit
    their own deadline breach and both must observe ONLY their own
    processes via the re-parent-proof pid-snapshot check (R4-P2) — no
    cross-blaming the other suite's live ffmpeg as an orphan (the P1
    failure mode), and no missing a re-parented survivor (the P2
    failure mode): the worker asserts its recorded pid set is non-empty
    and polls exactly those PIDs after the engine returns.
    """
    workers = [
        _spawn_remux_worker(tmp_path / f"suite_{tag}", tag)
        for tag in ("alpha", "beta")
    ]
    deadline = time.monotonic() + 120.0
    outputs: list[str] = []
    for proc in workers:
        try:
            stdout, _ = proc.communicate(
                timeout=max(5.0, deadline - time.monotonic())
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
        outputs.append(stdout or "")
    for proc in workers:
        assert proc.returncode == 0

    results: dict[str, str] = {}
    pid_counts: dict[str, int] = {}
    for out in outputs:
        for line in out.splitlines():
            if line.startswith("WORKER_"):
                head, _, payload = line.partition(":")
                tag = head.removeprefix("WORKER_").rsplit("_", 1)[0]
                if head.endswith("_PIDS"):
                    pid_counts[tag] = int(payload.strip())
                else:
                    results[tag] = payload.strip()
    assert set(results) == {"alpha", "beta"}, outputs
    # R4-P2: each worker REALLY recorded its own engine children during
    # the run (the snapshot is not vacuously empty).
    assert set(pid_counts) == {"alpha", "beta"}, outputs
    assert all(n >= 1 for n in pid_counts.values()), pid_counts
    # Each breach reported its OWN stable code and ITS OWN clean scope —
    # polled by fixed PID, independent of the descendant tree.
    for tag, payload in results.items():
        code, _, status = payload.partition(" ")
        assert code == CODE_DEADLINE_EXCEEDED, (tag, payload)
        assert status == "CLEAN", (tag, payload)
