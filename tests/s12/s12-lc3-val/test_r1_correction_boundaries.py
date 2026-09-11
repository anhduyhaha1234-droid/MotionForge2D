"""LC3-R1 reproductions for fenced cleanup, commit recovery, and pipe deadlines."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

TEST03C = Path(__file__).resolve().parents[1] / "s12-t03c"
sys.path.insert(0, str(TEST03C))
import test_publication as publication_base  # noqa: E402

from app.persistence.s12_export import FencedWorkerError, S12ExportRepository  # noqa: E402
from app.services.ffmpeg_utils import find_ffmpeg  # noqa: E402
from app.services.s12_export import publication as pub  # noqa: E402
from app.services.s12_export import validation as val  # noqa: E402
from app.services.s12_export.validation import (  # noqa: E402
    AudioReference,
    SourceReference,
    ValidationExpectation,
    probe_audio_shape,
    probe_frame_psnr,
    sha256_file,
    validate,
)

env = publication_base.env


def _ffmpeg(*args: str | Path) -> Path:
    target = Path(str(args[-1]))
    completed = subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-500:]
    return target


def test_r01_fenced_out_publisher_preserves_current_owner_candidate(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A stale caller cannot delete a candidate claimed by the new owner."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    with factory() as session:
        repo = S12ExportRepository(session)
        repo.release_lease(kw["run_id"], kw["worker_id"], kw["fence_token"])
        session.commit()
    with factory() as session:
        current = S12ExportRepository(session).claim_run(kw["run_id"], "worker-B")
        session.commit()

    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    payload = b"candidate belongs to current fenced owner B"
    candidate.write_bytes(payload)
    with factory() as session:
        with pytest.raises(FencedWorkerError):
            pub.publish_export_run(session, **kw)
        session.rollback()
    with factory() as session:
        live = S12ExportRepository(session).get_lease(kw["run_id"])
    print(
        "R01_STALE_CLEANUP "
        + json.dumps(
            {
                "candidate_exists": candidate.exists(),
                "current_owner": live.worker_id if live else None,
                "current_token_unchanged": live is not None
                and live.fence_token == current.fence_token,
            },
            sort_keys=True,
        )
    )
    assert candidate.is_file()
    assert candidate.read_bytes() == payload


def test_r02_actual_commit_failure_has_recoverable_publication(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A commit fault after rename must not strand an unadoptable winner."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)

    with factory() as session:
        def fail_commit() -> None:
            raise RuntimeError("injected database commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="database commit"):
            pub.publish_export_run(session, **kw)
        session.rollback()

    final = Path(kw["manifest"]["output_path"])
    sidecar = pub._sidecar_path(final)
    with factory() as session:
        status = S12ExportRepository(session).get_run(kw["run_id"]).status
    before_sha = pub._sha256_file(final)
    before_mtime = final.stat().st_mtime_ns
    with factory() as session:
        repo = S12ExportRepository(session)
        repo.release_lease(kw["run_id"], kw["worker_id"], kw["fence_token"])
        session.commit()
    with factory() as session:
        restarted = S12ExportRepository(session).claim_run(kw["run_id"], "worker-B")
        session.commit()
    restarted_kw = {
        **kw,
        "worker_id": "worker-B",
        "fence_token": restarted.fence_token,
    }
    retry_error: str | None = None
    recovered = None
    with factory() as session:
        try:
            recovered = pub.publish_export_run(session, **restarted_kw)
        except Exception as exc:  # pragma: no cover - expected until repaired
            retry_error = str(exc)
        session.rollback()
    with factory() as session:
        recovered_status = S12ExportRepository(session).get_run(kw["run_id"]).status
    print(
        "R02_COMMIT_GAP "
        + json.dumps(
            {
                "run_status": status,
                "recovered_status": recovered_status,
                "public_exists": final.exists(),
                "sidecar_exists": sidecar.exists(),
                "retry_error": retry_error,
            },
            sort_keys=True,
        )
    )
    assert retry_error is None
    assert recovered is not None and recovered["recovered"] is True
    assert recovered_status == "completed"
    assert pub._sha256_file(final) == before_sha
    assert final.stat().st_mtime_ns == before_mtime


def test_r02_lost_commit_ack_replays_completed_bytes(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A commit that succeeded before acknowledgement loss is replay-safe."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    before_sha = pub._sha256_file(Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4")
    before_mtime = final.stat().st_mtime_ns if final.exists() else None

    with factory() as session:
        original_commit = session.commit

        def commit_then_lose_ack() -> None:
            original_commit()
            raise RuntimeError("database commit acknowledgement lost")

        monkeypatch.setattr(session, "commit", commit_then_lose_ack)
        with pytest.raises(RuntimeError, match="acknowledgement lost"):
            pub.publish_export_run(session, **kw)

    with factory() as session:
        status = S12ExportRepository(session).get_run(kw["run_id"]).status
        replay = pub.publish_export_run(session, **kw)
        session.rollback()
    print(
        "R02_LOST_ACK "
        + json.dumps(
            {
                "status": status,
                "reused": replay.get("reused"),
                "sha256": replay.get("artifact_sha256"),
            },
            sort_keys=True,
        )
    )
    assert status == "completed"
    assert replay["reused"] is True
    assert replay["artifact_sha256"] == before_sha
    if before_mtime is not None:
        assert final.stat().st_mtime_ns == before_mtime


def test_r01_authority_change_during_validation_preserves_new_owner_bytes(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """The second fence check rejects an old session after a real handoff."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    payload = b"current owner B candidate after validation handoff"

    def handoff_then_pass(path, expectation):  # type: ignore[no-untyped-def]
        with factory() as session:
            repo = S12ExportRepository(session)
            repo.release_lease(kw["run_id"], kw["worker_id"], kw["fence_token"])
            session.commit()
        with factory() as session:
            S12ExportRepository(session).claim_run(kw["run_id"], "worker-B")
            session.commit()
        candidate.write_bytes(payload)
        return publication_base._Verdict("PASS", ["frame_count", "av_policy"])

    monkeypatch.setattr("app.services.s12_export.validation.validate", handoff_then_pass)
    with factory() as session:
        with pytest.raises(pub.PublicationError, match="fence lost"):
            pub.publish_export_run(session, **kw)
        session.rollback()
    with factory() as session:
        live = S12ExportRepository(session).get_lease(kw["run_id"])
    print(
        "R01_POST_VALIDATION_HANDOFF "
        + json.dumps(
            {
                "candidate_exists": candidate.exists(),
                "candidate_sha256": pub._sha256_file(candidate) if candidate.exists() else None,
                "current_owner": live.worker_id if live else None,
                "current_token_present": live is not None,
            },
            sort_keys=True,
        )
    )
    assert candidate.is_file()
    assert pub._sha256_file(candidate) == hashlib.sha256(payload).hexdigest()
    assert live is not None and live.worker_id == "worker-B"


def test_r02_pending_tampered_output_is_preserved_and_not_adopted(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """An output with mismatched receipt identity cannot replace or be adopted."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    final.write_bytes(b"foreign existing output")
    pub._write_sidecar(final, pub._sha256_file(final))
    receipt = pub._publication_receipt_path(final)
    receipt.write_text(
        json.dumps({"version": 1, "run_id": "other-run"}), encoding="utf-8"
    )
    before = pub._sha256_file(final)
    with factory() as session:
        with pytest.raises(pub.PublicationError, match="refusing overwrite"):
            pub.publish_export_run(session, **kw)
        session.rollback()
    assert pub._sha256_file(final) == before


def test_r01_multicomponent_aac_transcode_passes_source_referenced_check(
    tmp_path: Path,
) -> None:
    """A broadband-plus-tone AAC encode passes without a tone-only shortcut."""
    source = _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=64x36:rate=4:duration=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000:duration=1",
        "-f",
        "lavfi",
        "-i",
        "anoisesrc=color=white:sample_rate=16000:amplitude=0.03:duration=1",
        "-filter_complex",
        "[1:a][2:a]amix=inputs=2:duration=first[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-shortest",
        tmp_path / "multicomponent-source.mp4",
    )
    candidate = _ffmpeg(
        "-i",
        source,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "16000",
        "-ac",
        "1",
        tmp_path / "multicomponent-aac.mp4",
    )
    shape = probe_audio_shape(source, 0)
    assert shape is not None
    channels, sample_rate = shape
    verdict = validate(
        candidate,
        ValidationExpectation(
            width=64,
            height=36,
            codec="h264",
            source_locked=True,
            expected_frame_count=4,
            expected_duration_sec=1.0,
            expected_fps=4.0,
            expected_sha256=sha256_file(candidate),
            frame_match_mode="psnr",
            frame_psnr_min_db=20.0,
            source_reference=SourceReference(
                artifact_sha256=sha256_file(source),
                frame_count=4,
                fps_num=4,
                fps_den=1,
                reference_path=str(source),
                reference_width=64,
                reference_height=36,
                audio=AudioReference(
                    mode="transcode",
                    reference_path=str(source),
                    channels=channels,
                    sample_rate=sample_rate,
                ),
            ),
        ),
    )
    print("R01_MULTICOMPONENT " + json.dumps({"verdict": verdict.verdict, "probes": [p.name for p in verdict.probes]}))
    assert verdict.verdict == "PASS", verdict.probes


def test_r03_validator_resource_scaling_uses_bounded_owned_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Measure the actual ffmpeg validator process on small duration samples."""
    try:
        import psutil
    except ImportError:  # pragma: no cover - the supported runtime includes it
        pytest.fail("psutil is required for validator resource evidence")

    base_root = Path(os.environ.get("S12_VAL_RUNTIME_ROOT", str(tmp_path)))
    root = base_root / f"validator-resource-{time.monotonic_ns()}"
    root.mkdir(parents=True, exist_ok=True)
    scratch = root / "scratch"
    popen_processes: list[subprocess.Popen[bytes]] = []
    real_popen = val.subprocess.Popen

    def observe_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        process = real_popen(*args, **kwargs)
        popen_processes.append(process)
        return process

    monkeypatch.setattr(val.subprocess, "Popen", observe_popen)
    stop_monitor = threading.Event()
    peak_rss = 0
    peak_scratch = 0

    def monitor() -> None:
        nonlocal peak_rss, peak_scratch
        while not stop_monitor.is_set():
            for process in popen_processes:
                try:
                    if process.poll() is None:
                        peak_rss = max(peak_rss, psutil.Process(process.pid).memory_info().rss)
                except (psutil.Error, OSError):
                    pass
            try:
                peak_scratch = max(
                    peak_scratch,
                    sum(item.stat().st_size for item in scratch.iterdir() if item.is_file()),
                )
            except OSError:
                pass
            time.sleep(0.005)

    monitor_thread = threading.Thread(target=monitor, name="s12-val-resource-monitor")
    monitor_thread.start()
    measurements = []
    try:
        for frames in (4, 8, 16):
            duration = frames / 4
            reference = _ffmpeg(
                "-f", "lavfi", "-i", f"testsrc2=size=64x36:rate=4:duration={duration}",
                "-c:v", "libx264", "-preset", "ultrafast", "-an",
                root / f"reference-{frames}.mp4",
            )
            candidate = _ffmpeg(
                "-i", reference, "-vf", "scale=96:54", "-c:v", "libx264",
                "-preset", "ultrafast", "-an", root / f"candidate-{frames}.mp4",
            )
            free_before = shutil.disk_usage(root).free
            start = time.perf_counter()
            values = probe_frame_psnr(
                candidate, reference, 96, 54, 64, 36, scratch, None, 30
            )
            elapsed = time.perf_counter() - start
            free_after = shutil.disk_usage(root).free
            assert values is not None and len(values) == frames
            measurements.append(
                {
                    "frames": frames,
                    "duration_sec": round(elapsed, 6),
                    "scratch_bytes_after": sum(
                        item.stat().st_size for item in scratch.iterdir() if item.is_file()
                    ),
                    "free_disk_before": free_before,
                    "free_disk_after": free_after,
                }
            )
    finally:
        stop_monitor.set()
        monitor_thread.join(timeout=1.0)
    ffmpeg_version = subprocess.run(
        [find_ffmpeg(), "-version"], capture_output=True, text=True, timeout=30
    ).stdout.splitlines()[0]
    print(
        "R03_VALIDATOR_RESOURCE "
        + json.dumps(
            {
                "root": str(root),
                "raster": "96x54 candidate / 64x36 reference",
                "measurements": measurements,
                "peak_validator_ffmpeg_rss_bytes": peak_rss,
                "peak_stats_scratch_bytes": peak_scratch,
                "scratch_bytes_after": sum(
                    item.stat().st_size for item in scratch.iterdir() if item.is_file()
                ),
                "ffmpeg_version": ffmpeg_version,
                "duration_30_min_is_extrapolation": True,
            },
            sort_keys=True,
        )
    )
    assert peak_rss > 0
    assert peak_scratch <= 64 * 1024
    assert all(item["scratch_bytes_after"] == 0 for item in measurements)


def test_r03_stderr_pressure_and_nonzero_decoder_are_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A noisy failing decoder cannot fill stderr or survive the probe."""
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def noisy_decoder(argv, **kwargs):  # type: ignore[no-untyped-def]
        child = real_popen(
            [
                sys.executable,
                "-B",
                "-c",
                "import sys; sys.stderr.write('x' * 262144); sys.stderr.flush(); sys.exit(7)",
            ],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(val.subprocess, "Popen", noisy_decoder)
    start = time.monotonic()
    result = val.probe_audio_content(
        tmp_path / "reference",
        tmp_path / "candidate",
        channels=1,
        sample_rate=8000,
        max_drift_sec=0.1,
        timeout_sec=1.0,
    )
    elapsed = time.monotonic() - start
    print(
        "R03_STDERR_PRESSURE "
        + json.dumps(
            {
                "elapsed_sec": elapsed,
                "children_reaped": all(child.poll() is not None for child in children),
                "result": result,
            },
            sort_keys=True,
        )
    )
    assert result is None
    assert elapsed < 1.0
    assert all(child.poll() is not None for child in children)


def test_r03_audio_cancel_mid_read_reaps_both_children(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cancellation while both decoder reads are blocked is bounded."""
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def stalled_decoder(argv, **kwargs):  # type: ignore[no-untyped-def]
        child = real_popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(2)"],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(val.subprocess, "Popen", stalled_decoder)
    cancel_flag = tmp_path / "cancel.flag"
    result: list[object] = []

    def run_probe() -> None:
        result.append(
            val.probe_audio_content(
                tmp_path / "reference",
                tmp_path / "candidate",
                channels=1,
                sample_rate=8000,
                max_drift_sec=0.1,
                timeout_sec=5.0,
                cancel_flag=cancel_flag,
            )
        )

    worker = threading.Thread(target=run_probe)
    start = time.monotonic()
    worker.start()
    time.sleep(0.1)
    cancel_flag.write_text("cancel\n", encoding="ascii")
    worker.join(timeout=1.0)
    elapsed = time.monotonic() - start
    print(
        "R03_AUDIO_CANCEL "
        + json.dumps(
            {
                "elapsed_sec": elapsed,
                "thread_alive": worker.is_alive(),
                "children_reaped": all(child.poll() is not None for child in children),
                "result": result,
            },
            sort_keys=True,
        )
    )
    assert not worker.is_alive()
    assert result == [None]
    assert elapsed < 1.0
    assert all(child.poll() is not None for child in children)


def test_r03_audio_deadline_interrupts_blocked_decoder_pipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blocked decoder read is interrupted at the total deadline."""
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def silent_decoder(argv, **kwargs):  # type: ignore[no-untyped-def]
        child = real_popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(2)"],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(val.subprocess, "Popen", silent_decoder)
    start = time.monotonic()
    result = val.probe_audio_content(
        tmp_path / "reference",
        tmp_path / "candidate",
        channels=1,
        sample_rate=8000,
        max_drift_sec=0.1,
        timeout_sec=0.1,
    )
    elapsed = time.monotonic() - start
    print(
        "R03_AUDIO_DEADLINE "
        + json.dumps(
            {
                "timeout_sec": 0.1,
                "elapsed_sec": elapsed,
                "children_reaped": all(child.poll() is not None for child in children),
                "result": result,
            },
            sort_keys=True,
        )
    )
    assert result is None
    assert elapsed < 1.0
    assert all(child.poll() is not None for child in children)
