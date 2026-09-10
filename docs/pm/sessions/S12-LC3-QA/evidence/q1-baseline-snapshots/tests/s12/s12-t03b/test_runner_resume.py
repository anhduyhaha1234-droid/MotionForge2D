"""S12-T03B — runner + checkpoint-resume tests on a real migrated temp DB.

- Full resume: ensure_plan → render_pending → assemble == FRAMES exact;
  completed candidate decodes and .partial never lingers as completed.
- Fresh-process resume: new repository/session replays rows + files;
  verified+exact chunks reused (no re-render), tampered/short file
  re-rendered (never accepted).
- Crash simulation: partial chunk rows + .partial scratch → resume finishes.
- Fail-closed: stale lease (foreign worker/expired), cancel flag + run
  status, tampered chunk hash on replay, missing source.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.persistence.s12_export import (
    FencedWorkerError,
    S12ExportRepository,
    StaleIdentityError,
)
from app.services.s12_export.runner import (
    CancelledError,
    DiskFullError,
    ExportRunner,
    RunnerError,
    StaleLeaseError,
)
from app.services.s12_export.stitch import count_video_frames
import importlib.util as _importlib_util
from pathlib import Path as _Path

_spec = _importlib_util.spec_from_file_location(
    "s12_t03b_fixtures", _Path(__file__).parent / "conftest.py"
)
assert _spec is not None and _spec.loader is not None
_t03b_fixtures = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_t03b_fixtures)
FRAMES = _t03b_fixtures.FRAMES
make_config = _t03b_fixtures.make_config
make_run = _t03b_fixtures.make_run


def _resume_cfg(factory, manifest_id, source, workdir, **over):  # type: ignore[no-untyped-def]
    run, lease = make_run(factory, manifest_id)
    return make_config(run, lease, source, workdir, **over), run, lease


def test_full_run_assembles_exact_frames(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    assert Path(out).is_file()
    assert count_video_frames(out) == FRAMES
    assert not Path(str(out) + ".partial").exists()
    with factory() as s:
        rows = S12ExportRepository(s).list_chunks(run.id)
        assert rows
        assert all(c.state == "completed" and c.verified == 1 for c in rows)


def test_resume_reuses_verified_chunks(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        media = runner.render_pending(specs)
        s.commit()
    mtimes = {m.spec.chunk_index: m.path.stat().st_mtime_ns for m in media}
    # Fresh process: brand-new session + repository, same lease + files.
    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        specs2 = runner2.ensure_plan()
        media2 = runner2.render_pending(specs2)
        s2.commit()
    assert [m.spec.content_hash for m in media2] == [
        m.spec.content_hash for m in media
    ]
    for m in media2:
        assert m.path.stat().st_mtime_ns == mtimes[m.spec.chunk_index]


def test_resume_rerenders_tampered_chunk_file(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        media = runner.render_pending(specs)
        s.commit()
    # Tamper: truncate the first chunk file to garbage bytes (decodes short).
    victim = media[0].path
    with open(victim, "r+b") as handle:
        handle.truncate(1024)
    # Fresh process: completed+verified row + tampered file → fail closed
    # (tampered chunk is never silently accepted, terminal row never
    # rewritten by the T03B runner).
    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        specs2 = runner2.ensure_plan()
        with pytest.raises(RunnerError, match="tampered chunk"):
            runner2.render_pending(specs2)
    # Restore the chunk file (re-render just that window, row stays valid)
    # and the full resume finishes to an exact candidate.
    with factory() as s3:
        runner3 = ExportRunner(S12ExportRepository(s3), cfg)
        specs3 = runner3.ensure_plan()
        runner3._render_window_file(  # noqa: SLF001
            specs3[0], runner3.chunk_path(specs3[0].chunk_index)
        )
        media3 = runner3.render_pending(specs3)
        out = runner3.assemble(media3)
        s3.commit()
    assert count_video_frames(out) == FRAMES


def test_crash_mid_run_resumes_to_candidate(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        # Render only the first chunk, then "crash" (no commit of the rest,
        # stray .partial scratch left behind).
        first = specs[0]
        row = S12ExportRepository(s).list_chunks(run.id)[0]
        s2repo = S12ExportRepository(s)
        row = s2repo.transition_chunk(
            row.id,
            "running",
            actor="worker-1",
            fence_token=cfg.fence_token,
            expected_revision=row.revision,
        )
        runner._render_window_file(  # noqa: SLF001
            first, runner.chunk_path(first.chunk_index)
        )
        s2repo.transition_chunk(
            row.id,
            "completed",
            actor="worker-1",
            fence_token=cfg.fence_token,
            expected_revision=row.revision,
            verified=1,
        )
        (workdir / "chunks" / "crash-leftover.mp4.partial").parent.mkdir(
            parents=True, exist_ok=True
        )
        (workdir / "chunks" / "crash-leftover.mp4.partial").write_bytes(b"junk")
        s.commit()
    with factory() as s3:
        runner3 = ExportRunner(S12ExportRepository(s3), cfg)
        out = runner3.resume()
        s3.commit()
    assert count_video_frames(out) == FRAMES


def test_stale_lease_foreign_worker_fails(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    cfg.worker_id = "worker-2"
    cfg.fence_token = "0" * 32
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        with pytest.raises((StaleLeaseError, FencedWorkerError)):
            runner.ensure_plan()


def test_expired_lease_fails_closed(ctx) -> None:  # type: ignore[no-untyped-def]
    import datetime

    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        from app.persistence.models import S12ExportLease

        row = s.get(S12ExportLease, run.id)
        assert row is not None
        row.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=1
        )
        s.commit()
    with factory() as s2:
        runner = ExportRunner(S12ExportRepository(s2), cfg)
        with pytest.raises(StaleLeaseError):
            runner.ensure_plan()
        assert ExportRunner.code_for(StaleLeaseError("x")) == "S12_T03B_STALE_LEASE"


def test_cancel_flag_stops_run(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    flag = workdir / "CANCEL"
    cfg, _run, _lease = _resume_cfg(
        factory, manifest_id, source, workdir, cancel_flag=flag
    )
    flag.write_text("cancel")
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        with pytest.raises(CancelledError):
            runner.resume()
        assert ExportRunner.code_for(CancelledError("x")) == "S12_T03B_CANCELLED"


def test_cancelled_status_stops_run(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.transition_run(
            run.id,
            "cancelled",
            actor="worker-1",
            expected_revision=run.revision + 1,
            fence_token=lease.fence_token,
        )
        s.commit()
    with factory() as s2:
        runner = ExportRunner(S12ExportRepository(s2), cfg)
        with pytest.raises(CancelledError):
            runner.resume()


def test_tampered_chunk_hash_replay_fails(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _resume_cfg(factory, manifest_id, source, workdir)
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        s.commit()
    # Same slot, different content_hash → T03A fails closed.
    with factory() as s2:
        repo = S12ExportRepository(s2)
        with pytest.raises(StaleIdentityError):
            repo.upsert_chunk(
                run_id=run.id,
                workspace_id=cfg.workspace_id,
                chunk_index=specs[0].chunk_index,
                order_index=specs[0].order_index,
                core_start_frame=specs[0].core_start_frame,
                core_end_frame=specs[0].core_end_frame,
                content_hash="f" * 64,
                attempt=specs[0].attempt,
                actor="worker-1",
                fence_token=cfg.fence_token,
            )
        assert ExportRunner.code_for(StaleIdentityError("x")) == (
            "S12_T03B_STALE_IDENTITY"
        )


def test_missing_source_fails_closed(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, _source, _audio, workdir = ctx
    cfg, _run, _lease = _resume_cfg(
        factory, manifest_id, workdir / "no-such-source.mp4", workdir
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        with pytest.raises(RunnerError):
            runner.render_pending(specs)


def test_audio_mapping_exact_not_looped(ctx) -> None:  # type: ignore[no-untyped-def]
    factory, manifest_id, source, audio_src, workdir = ctx
    cfg, _run, _lease = _resume_cfg(
        factory, manifest_id, source, workdir, audio_source=audio_src
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    assert count_video_frames(out) == FRAMES
    # Audio stream present exactly once.
    import json
    import subprocess

    from app.services.ffmpeg_utils import find_ffprobe

    completed = subprocess.run(
        [
            find_ffprobe(),
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    kinds = [st["codec_type"] for st in json.loads(completed.stdout)["streams"]]
    assert kinds.count("audio") == 1
    assert kinds.count("video") == 1
    assert ExportRunner.code_for(DiskFullError("x")) == "S12_T03B_DISK_FULL"
    assert os.path.basename(str(out)) == "export.mp4"
