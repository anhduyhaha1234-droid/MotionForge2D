"""S12-C2 C26 — Scenario F on the NORMAL product path.

Normal-app flow with real production pieces:
  submit_export_job (normal API enqueue) -> _s12_export_handler (the F01
  real worker caller of publish_export_run) -> real chunk render at the
  selected profile raster -> publication gate.

Findings recorded, NOT fixed (verifier):
- F11-T06B-01 (owner T03C/T04A): publication._expectation_for supplies
  NO server-owned authority to the source-locked validator
  (expected_sha256=None -> provenance FAIL; frame_digests/cuts empty ->
  frame_order NOT_MEASURED).  Every real job is therefore rejected at
  publication with the run failing between ``runtime`` and ``failed``
  (retryable) AFTER a real candidate exists.  The positive publish path
  is not closable on this base; the fail-closed behaviour itself is
  asserted here (no case removal, no waive).
- C28-F01 (owner T03C/T04A): _expectation_for never attaches
  AudioReference for audio-source jobs -> audio-present candidates are
  rejected as ``absent``.  Jobs hereby run silent; C28 covers audio
  mapping at the assembly layer.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.persistence import create_engine_for_path
from app.workflow.job_service import JobService
from app.workflow.s12_export_jobs import (
    _s12_export_handler,
    submit_export_job,
)

from conftest import (  # type: ignore[import-not-found]
    CHK_HASH,
    FPS,
    PLAN_HASH,
    PLAN_ID,
    WS,
    build_media_silent,
    ffprobe_json,
    probe_dims,
    probe_has_audio,
)

F_1080 = 30
F_4K_NATIVE = 20
F_43 = 30


def _manifest_hash(factory: Any, manifest_id: str) -> str:
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        assert row is not None
        return str(row.manifest_hash)


def _run_normal_job(
    factory: Any,
    svc: JobService,
    manifest_id: str,
    dirs: dict[str, str],
    source: Path,
    *,
    frame_count: int,
    worker: str = "worker-c26",
    fps: float = FPS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Submit ONE normal job and run the real worker handler."""
    manifest_hash = _manifest_hash(factory, manifest_id)
    payload = {
        "schema_version": 1,
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": manifest_hash,
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": frame_count,
        "chunk_config": {"overlap": 4, "max_frames": 12},
        "source_path": str(source),
        "fps": float(fps),
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "audio_source": None,
        "max_frames_per_chunk": 12,
        "overlap_frames": 4,
        "fps_num": int(round(fps)),
        "fps_den": 1,
    }
    run, job, created = submit_export_job(
        svc,
        workspace_id=payload["workspace_id"],
        project_id=payload["project_id"],
        video_item_id=payload["video_item_id"],
        checkpoint_id=payload["checkpoint_id"],
        checkpoint_hash=payload["checkpoint_hash"],
        checkpoint_revision=payload["checkpoint_revision"],
        manifest_id=payload["manifest_id"],
        manifest_hash=payload["manifest_hash"],
        manifest_generation=payload["manifest_generation"],
        profile_id=payload["profile_id"],
        plan_id=payload["plan_id"],
        plan_hash=payload["plan_hash"],
        frame_count=payload["frame_count"],
        chunk_config=payload["chunk_config"],
        source_path=payload["source_path"],
        fps=payload["fps"],
        chunk_dir=payload["chunk_dir"],
        scratch_dir=payload["scratch_dir"],
        output_path=payload["output_path"],
        audio_source=payload.get("audio_source"),
        fps_num=payload.get("fps_num", 0),
        fps_den=payload.get("fps_den", 0),
    )
    assert created is True
    assert run.status == "pending"
    payload["run_id"] = run.id
    ctx = SimpleNamespace(
        input_manifest=payload,
        worker_id=worker,
        session_factory=factory,
    )
    outcome = _s12_export_handler(ctx)
    return outcome, payload


def _run_blocked(
    factory: Any,
    svc: JobService,
    manifest_id: str,
    dirs: dict[str, str],
    source: Path,
    *,
    frame_count: int,
) -> Path:
    """Run ONE normal job: render is real, publication fails closed.

    Asserts the F11-T06B-01 fail-closed behaviour AND that the real
    3840x2160 candidate was produced and never surfaced as final.
    """
    from app.services.s12_export.publication import PublicationError

    try:
        outcome = _run_normal_job(
            factory, svc, manifest_id, dirs, source,
            frame_count=frame_count, worker="worker-c26",
        )
        raise AssertionError(
            f"job unexpectedly published: {outcome[0].get('status')} "
            "(did F11 authority wiring land in base?)"
        )
    except PublicationError as err:
        assert "validation" in str(err), str(err)
    candidate = Path(dirs["scratch"]) / "candidate_final.mp4"
    assert candidate.is_file(), "real render candidate missing"
    return candidate


@pytest.fixture(autouse=True)
def _ready_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness is an S11 external gate (mocked exactly like T03C)."""
    from app.services.s12_export import publication as _pubmod

    monkeypatch.setattr(_pubmod, "_require_ready", lambda session, **kw: None)


@pytest.fixture()
def job_env(tmp_path: Path, db_factory: Any):  # type: ignore[no-untyped-def]
    """Migrated isolated DB + lineage + JobService + server-owned dirs."""
    factory, manifest_id, _db = db_factory
    svc = JobService(factory, managed_root=tmp_path / "artifacts")
    dirs = {
        "chunk": str(tmp_path / "chunks"),
        "scratch": str(tmp_path / "scratch"),
        "output": str(tmp_path / "out" / "final.mp4"),
    }
    yield factory, manifest_id, svc, dirs
    create_engine_for_path(_db).dispose()


def _assert_media(candidate: Path, *, frames: int, duration_s: float) -> None:
    """Real candidate: 3840x2160 raster, exact frames/timing, silent, whole."""
    assert probe_dims(candidate) == (3840, 2160)
    assert not candidate.name.endswith(".partial")
    info = ffprobe_json(candidate)
    assert float(info["format"]["duration"]) == pytest.approx(duration_s, abs=0.3)
    assert probe_has_audio(candidate) is False
    from app.services.s12_export.stitch import count_video_frames

    assert count_video_frames(candidate) == frames
    # No .partial anywhere in scratch/chunks -> never a completed leftover.
    assert list(Path(candidate).parent.glob("*.partial")) == []


@pytest.mark.measured
def test_c26_upscale_1080p_to_4k_real_render(job_env: Any, tmp_path: Path) -> None:
    factory, manifest_id, svc, dirs = job_env
    src = build_media_silent(tmp_path / "src1080.mp4", width=1920, height=1080, duration=3.0)
    assert probe_dims(src) == (1920, 1080)
    candidate = _run_blocked(factory, svc, manifest_id, dirs, src, frame_count=F_1080)
    _assert_media(candidate, frames=F_1080, duration_s=3.0)
    print("\n[C26] 1920x1080 -> 3840x2160 real render done; publish fail-closed (F11-T06B-01)")


@pytest.mark.measured
def test_c26_native_4k_control(job_env: Any, tmp_path: Path) -> None:
    factory, manifest_id, svc, dirs = job_env
    src = build_media_silent(tmp_path / "src4k.mp4", width=3840, height=2160, duration=2.0)
    assert probe_dims(src) == (3840, 2160)
    candidate = _run_blocked(factory, svc, manifest_id, dirs, src, frame_count=F_4K_NATIVE)
    _assert_media(candidate, frames=F_4K_NATIVE, duration_s=2.0)
    print("\n[C26] native 4K control: render 3840x2160 done; publish fail-closed (F11-T06B-01)")


@pytest.mark.measured
def test_c26_non_16_9_control(job_env: Any, tmp_path: Path) -> None:
    factory, manifest_id, svc, dirs = job_env
    src = build_media_silent(tmp_path / "src43.mp4", width=1440, height=1080, duration=3.0)
    assert probe_dims(src) == (1440, 1080)  # 4:3
    candidate = _run_blocked(factory, svc, manifest_id, dirs, src, frame_count=F_43)
    _assert_media(candidate, frames=F_43, duration_s=3.0)
    print("\n[C26] 4:3 control: letterbox pad 3840x2160 done; publish fail-closed (F11-T06B-01)")