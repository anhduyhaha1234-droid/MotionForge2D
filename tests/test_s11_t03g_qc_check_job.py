"""S11-T03G (W8) — durable RUN_QC_CHECKS job + idempotency + read authority.

Binary acceptances (production plan REV7/C6 SHA 34247926... block W8):

1. Completed run with ZERO QCItems still carries durable completion
   evidence (JobAttempt result + step checkpoint) and is distinguishable
   from never-run (AC1).
2. No completed current run — or only queued/running/failed/stale runs —
   ⇒ readiness not_run fail-closed with check-state detail (AC2).
3. Completed current run with zero blocker ⇒ clean/ready candidate (AC3).
4. Idempotency key embeds video item / current evidence fingerprint /
   policy hash / scope; duplicate ACTIVE submit conflicts fail-closed
   (IdempotencyKeyInUse), duplicate after COMPLETION reuses the same job
   (AC4).
5. Restart / retry never duplicates QCItems or run effects (AC5).

Isolation: per-test temp SQLite DB (Alembic head — production schema),
short unique Windows-native basetemp supplied by the runner, plus
``-p no:cacheprovider`` and ``MOTIONFORGE_DATABASE_URL`` stripped by the
runner command.  The REAL default JobService registration block runs
(worker=None) — the RUN_QC_CHECKS handler is registered by
``app/workflow/job_service.py`` exactly like ATTACH_ORIGINAL_AUDIO.

Detector args are server-composed deterministic fixtures (the T03E
envelope contract: content-derived checkpoint/published dicts — a
NO_AUDIO_PRESENT terminal fact yields zero QCItems; a source-with-audio
with missing output yields blockers).  No ffmpeg is required.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.jobs import IdempotencyKeyInUse
from app.persistence.models import (
    Job,
    JobAttempt,
    JobLease,
    JobStep,
)
from app.persistence.qc_items import QCItemRepository
from app.services.qc_checks import audio_missing, av_sync_drift  # noqa: F401  (self-register)
from app.services.qc_checks.registry import registry
from app.workflow.durable_worker import DurableWorker, WorkerConfig
from app.workflow.job_service import JobService

# RED gate: these modules do NOT exist at WAVE_BASE — importing them here
# is the RED proof (ModuleNotFoundError before implementation).
from app.persistence.qc_check_runs import (
    CheckRunReadiness,
    check_run_readiness,
    full_coverage_detectors,
    full_scope_fingerprint,
    latest_check_run_state,
)
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_AUDIO,
    SCOPE_FULL,
    QcCheckRunSubmitError,
    evidence_fingerprint,
    policy_bundle,
    scope_detectors,
    scope_fingerprint,
    submit_run_qc_checks,
)

#: Frozen audio-band registration identities (T03A registry contract) — the
#: orchestrator consumes the registry read-only; a previous suite may have
#: unregistered members, so this fixture re-registers the binding band
#: deterministically for THIS module (T03F convention, no teardown harm).
_AUDIO_REGISTRATION = [
    ("audio_missing", "app.services.qc_checks.audio_missing:detect"),
    ("av_sync_drift", "app.services.qc_checks.av_sync_drift:detect"),
]


@pytest.fixture(scope="module", autouse=True)
def _ensure_audio_band_registered() -> None:
    for name, entry_point in _AUDIO_REGISTRATION:
        registry.register(name, entry_point)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

WS = "ws-s11-t03g"
P1 = "p-s11-t03g"


def _new_id() -> str:
    return str(uuid.uuid4())


# ── deterministic clock/sleeper (mirror test_s11_attach_original_audio_job) ──


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 3, 22, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ── DB fixtures (production schema via Alembic) ─────────────────────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "qc_run_job.db"


@pytest.fixture()
def session_factory(db_path: Path):
    _upgrade(db_path)
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def managed_root(tmp_path: Path) -> Path:
    root = tmp_path / "managed"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def sleeper() -> FakeSleeper:
    return FakeSleeper()


@pytest.fixture()
def svc(
    session_factory,
    managed_root: Path,
    clock: FakeClock,
    sleeper: FakeSleeper,
) -> JobService:
    """The DEFAULT production JobService over temp roots.

    worker=None → the service constructs its own DurableWorker and runs the
    REAL registration block, which must include the RUN_QC_CHECKS handler
    (the bounded job_service.py registration patch).
    """
    service = JobService(session_factory, managed_root=managed_root)
    worker = service.worker
    assert worker is not None
    worker._config = WorkerConfig(  # noqa: SLF001 - test seam on own instance
        worker_id="qc-run-worker",
        lease_ttl=60,
        heartbeat_interval=15,
        poll_interval=0.01,
        max_attempts=3,
        staging_root=managed_root,
    )
    object.__setattr__(worker, "_clock", clock)
    object.__setattr__(worker, "_sleeper", sleeper)
    return service


@pytest.fixture()
def worker(svc: JobService) -> DurableWorker:
    w = svc.worker
    assert w is not None
    return w


def seed_ws_project(session: Session, *, video_id: str | None = None) -> str:
    if video_id is None:
        video_id = _new_id()
    from sqlalchemy import text as _t

    session.execute(
        _t("INSERT INTO workspace(id, name) VALUES (:w, :w) ON CONFLICT(id) DO NOTHING"),
        {"w": WS},
    )
    session.execute(
        _t(
            "INSERT INTO project(id, workspace_id, name, description, status) "
            "VALUES (:p, :w, :p, '', 'active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": P1, "w": WS},
    )
    session.execute(
        _t(
            "INSERT INTO video_item(id, project_id, title, position, status) "
            "VALUES (:v, :p, :v, "
            "(SELECT COALESCE(MAX(position),0)+1 FROM video_item WHERE project_id=:p), "
            "'imported') ON CONFLICT(id) DO NOTHING"
        ),
        {"v": video_id, "p": P1},
    )
    session.commit()
    return video_id


def no_audio_envelope(*, video_id: str) -> dict[str, Any]:
    """The REAL terminal fact envelope: source has NO audio stream.

    Mirrors the T03F ``_no_audio_checkpoint`` evidence shape — content
    derived, deterministic, zero QCItems (Decision D).
    """
    return {
        "checkpoint": {
            "schema_version": 1,
            "status": "NO_AUDIO_PRESENT",
            "mode": None,
            "source_sha256": "a" * 64,
            "source_size_bytes": 1024,
            "source_audio_codec": None,
            "source_audio_duration": None,
            "output_audio_codec": None,
            "output_audio_duration": None,
            "audio_time_base": None,
            "video_codec": "h264",
        },
        "published": {
            "no_audio_present": True,
            "artifact_id": None,
            "final_rel": None,
            "sha256": None,
            "size_bytes": None,
            "status": "NO_AUDIO_PRESENT",
        },
    }


def source_has_audio_missing_output_envelope(*, video_id: str) -> dict[str, Any]:
    """Source HAS audio but the expected output publish is missing.

    audio_missing → blocker/open (FAILURE_OUTPUT_MISSING); av_sync_drift →
    blocker (THRESHOLD_UNKNOWN_SCENE, no usable scene timeline).  Used by
    the idempotency/restart tests to prove items are created exactly once.
    """
    return {
        "checkpoint": {
            "schema_version": 1,
            "status": "STREAM_COPY",
            "mode": "stream_copy",
            "source_sha256": "b" * 64,
            "source_size_bytes": 2048,
            "source_audio_codec": "aac",
            "source_audio_duration": "2.000000",
            "output_audio_codec": None,
            "output_audio_duration": None,
            "audio_time_base": "1/48000",
            "video_codec": "h264",
        },
        "published": None,
    }


def audio_scope_args(envelope: dict[str, Any]) -> dict[str, Any]:
    """Server-composed args for the AUDIO band from a persisted envelope."""
    return {
        "audio_missing": {
            "checkpoint": envelope["checkpoint"],
            "published": envelope.get("published"),
            "error": None,
            "checkpoint_ref": "s11-t03g",
        },
        "av_sync_drift": {
            "checkpoint": envelope["checkpoint"],
            "scene_timeline": {"duration_seconds": 2.0},
            "published": envelope.get("published"),
            "checkpoint_ref": "s11-t03g",
        },
    }


def _submit(
    session_factory,
    *,
    video_id: str,
    scope: str = SCOPE_AUDIO,
    detector_args: dict[str, Any] | None = None,
    generation: str = "1",
):
    if detector_args is None:
        detector_args = audio_scope_args(no_audio_envelope(video_id=video_id))
    return submit_run_qc_checks(
        session_factory,
        workspace_id=WS,
        project_id=P1,
        video_item_id=video_id,
        scope=scope,
        detector_args=detector_args,
        generation=generation,
    )


# ── helpers ─────────────────────────────────────────────────────────────────


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _attempt_results(session_factory, job_id: str) -> list[dict[str, Any]]:
    with session_factory() as s:
        repo = JobRepository(s)
        out: list[dict[str, Any]] = []
        for att in repo.list_attempts(job_id):
            if att.result is not None:
                out.append(att.result)
        return out


def _attempt_errors(session_factory, job_id: str) -> list[dict[str, Any]]:
    with session_factory() as s:
        repo = JobRepository(s)
        out: list[dict[str, Any]] = []
        for att in repo.list_attempts(job_id):
            if att.error is not None:
                out.append(att.error)
        return out


def _step_checkpoint(session_factory, job_id: str) -> dict[str, Any]:
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(job_id)[0].id)
        return json.loads(step_row.checkpoint_json or "{}")


def _qc_items(session_factory, video_id: str) -> list[Any]:
    with session_factory() as s:
        records, _total = QCItemRepository(s).list(
            workspace_id=WS, video_item_id=video_id, limit=10000
        )
        return records


def _count_qc_items(session_factory, video_id: str) -> int:
    return len(_qc_items(session_factory, video_id))


def _force_replay(session_factory, job_id: str) -> None:
    """Reset a terminal job+step to queued/pending, drop lease + attempts —
    the crash-restart path that re-executes the SAME job row."""
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(job_id)[0].id)
        step_row.state = "pending"
        step_row.attempt = 0
        step_row.error_json = None
        step_row.started_at = None
        step_row.finished_at = None
        job_row = s.get(Job, job_id)
        job_row.state = "queued"
        job_row.attempt = 0
        job_row.error_json = None
        job_row.started_at = None
        job_row.finished_at = None
        lease = s.get(JobLease, job_id)
        if lease is not None:
            s.delete(lease)
        for attempt in s.scalars(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        ):
            s.delete(attempt)
        s.commit()


def _readiness(
    session_factory,
    video_id: str,
    *,
    generation: str = "1",
) -> CheckRunReadiness:
    with session_factory() as s:
        fp = evidence_fingerprint(
            s, workspace_id=WS, video_item_id=video_id, generation=generation
        )
        return check_run_readiness(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            evidence_fingerprint=fp,
            policy_content_hash=policy_bundle()["policy_content_hash"],
        )


# ═══════════════════════════════════════════════════════════════════════════
# 0. Registration (the bounded job_service.py patch)
# ═══════════════════════════════════════════════════════════════════════════


def test_default_jobservice_registers_qc_checks_handler(svc: JobService) -> None:
    """The default production JobService registers RUN_QC_CHECKS → the
    durable handler (the job_service.py registration patch is real)."""
    worker = svc.worker
    assert worker is not None
    with worker._lock:  # noqa: SLF001 - registry introspection (attach-test pattern)
        assert JOB_TYPE_RUN_QC_CHECKS in worker._handlers  # noqa: SLF001
        entry = worker._handlers[JOB_TYPE_RUN_QC_CHECKS]  # noqa: SLF001
    assert entry.handler.__name__ == "qc_checks_handler"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Submit: server-owned manifest + idempotency key composition (AC4)
# ═══════════════════════════════════════════════════════════════════════════


def test_submit_creates_server_owned_manifest_with_composed_key(
    session_factory, svc: JobService
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    result = _submit(session_factory, video_id=video_id)

    with session_factory() as s:
        record = JobRepository(s).get_job(result.job_id)
        manifest = record.input_manifest

    assert record.job_type == JOB_TYPE_RUN_QC_CHECKS
    assert record.owner_type == "video_item"
    assert record.owner_id == video_id
    assert record.state == "queued"
    assert manifest["schema_version"] == RUN_QC_SCHEMA_VERSION
    assert manifest["scope"] == SCOPE_AUDIO
    assert manifest["policy_id"] == policy_bundle()["policy_id"]
    assert manifest["policy_content_hash"] == policy_bundle()["policy_content_hash"]
    assert manifest["source_generation"] == "1"
    # server-owned band, never client-chosen implementation names
    assert set(manifest["detector_args"]) == {"audio_missing", "av_sync_drift"}
    assert manifest["scope_fingerprint"] == scope_fingerprint(SCOPE_AUDIO)
    with session_factory() as s:
        expected_fp = evidence_fingerprint(
            s, workspace_id=WS, video_item_id=video_id
        )
    assert manifest["evidence_fingerprint"] == expected_fp

    # idempotency key embeds video / evidence fingerprint / policy hash / scope
    parts = record.idempotency_key.split(":")
    assert parts[0] == JOB_TYPE_RUN_QC_CHECKS
    assert parts[1] == "video_item"
    assert parts[2] == video_id
    assert parts[3] == manifest["evidence_fingerprint"]
    assert parts[4] == manifest["policy_content_hash"]
    assert parts[5] == SCOPE_AUDIO


def test_submit_unknown_scope_fails_closed(session_factory, svc: JobService) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    with pytest.raises(QcCheckRunSubmitError):
        submit_run_qc_checks(
            session_factory,
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            scope="bogus-scope",
            detector_args={},
        )


def test_submit_missing_band_args_fails_closed(
    session_factory, svc: JobService
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    # only ONE detector of the audio band supplied → fail fast at submit
    with pytest.raises(QcCheckRunSubmitError):
        _submit(
            session_factory,
            video_id=video_id,
            detector_args={
                "audio_missing": {
                    "checkpoint": {},
                    "published": None,
                    "error": None,
                    "checkpoint_ref": "x",
                }
            },
        )


def test_submit_cross_owner_fails_closed(session_factory, svc: JobService) -> None:
    other = "ws-s11-t03g-other"
    with session_factory() as s:
        from sqlalchemy import text as _t

        s.execute(
            _t(
                "INSERT INTO workspace(id, name) VALUES (:w, :w) "
                "ON CONFLICT(id) DO NOTHING"
            ),
            {"w": other},
        )
        s.commit()
    video_id = seed_ws_project(session_factory(), video_id=None)
    with pytest.raises(Exception):
        submit_run_qc_checks(
            session_factory,
            workspace_id=other,
            project_id=P1,
            video_item_id=video_id,
            scope=SCOPE_AUDIO,
            detector_args=audio_scope_args(no_audio_envelope(video_id=video_id)),
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. AC1: zero-item completed run vs never-run
# ═══════════════════════════════════════════════════════════════════════════


def test_completed_zero_item_run_has_durable_completion_evidence(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    result = _submit(session_factory, video_id=video_id)  # NO_AUDIO_PRESENT → 0 items

    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"
    assert _count_qc_items(session_factory, video_id) == 0

    # durable completion evidence lives in the JobAttempt result
    results = _attempt_results(session_factory, result.job_id)
    assert len(results) == 1
    completion = results[0]
    assert completion["schema_version"] == RUN_QC_SCHEMA_VERSION
    assert completion["job_type"] == JOB_TYPE_RUN_QC_CHECKS
    assert completion["completed"] is True
    assert len(completion["run_id"]) == 64
    assert completion["policy_id"] == policy_bundle()["policy_id"]
    assert completion["policy_content_hash"] == policy_bundle()["policy_content_hash"]
    assert completion["source_generation"] == "1"
    assert completion["scope"] == SCOPE_AUDIO
    assert completion["scope_fingerprint"] == scope_fingerprint(SCOPE_AUDIO)
    assert completion["evidence_fingerprint"] == result.evidence_fingerprint
    assert completion["detectors"] == ["audio_missing", "av_sync_drift"]
    assert completion["detector_revisions"]  # non-empty server-owned revisions
    summary = completion["summary"]
    assert summary["checks_requested"] == 2
    assert summary["checks_run"] == 2
    assert summary["errors"] == 0
    assert summary["created"] == 0
    assert summary["not_applicable"] == 2
    # zero-item completion evidence — the GAP-8 fabrication guard
    assert completion["zero_item_completion"] == {
        "evidence": True,
        "qc_items_created": 0,
        "issues_found": 0,
        "checks_run": 2,
        "not_applicable": 2,
    }

    # the step checkpoint carries the same durable block
    checkpoint = _step_checkpoint(session_factory, result.job_id)
    assert checkpoint["completed"] is True
    assert checkpoint["zero_item_completion"]["evidence"] is True


def test_zero_item_completed_run_distinguishable_from_never_run(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    ran_id = seed_ws_project(session_factory(), video_id=None)
    never_id = seed_ws_project(session_factory(), video_id=None)

    # C1-A: the authority is the FULL band — drive a real completed FULL
    # run (zero-item: the seeded envelope creates no blockers).
    _seed_full_job(session_factory, video_id=ran_id)

    # both videos have ZERO QCItems — only the durable run evidence can
    # tell "ran clean" apart from "never checked"
    assert _count_qc_items(session_factory, ran_id) == 0
    assert _count_qc_items(session_factory, never_id) == 0

    with session_factory() as s:
        ran_fp = evidence_fingerprint(s, workspace_id=WS, video_item_id=ran_id)
        ran_state = latest_check_run_state(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=ran_id,
            evidence_fingerprint=ran_fp,
            policy_content_hash=policy_bundle()["policy_content_hash"],
        )
        never_fp = evidence_fingerprint(s, workspace_id=WS, video_item_id=never_id)
        never_state = latest_check_run_state(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=never_id,
            evidence_fingerprint=never_fp,
            policy_content_hash=policy_bundle()["policy_content_hash"],
        )

    assert ran_state.run_state == "completed"
    assert ran_state.zero_item_completion is True
    assert ran_state.summary is not None
    assert ran_state.summary["created"] == 0
    assert never_state.run_state == "never_run"
    assert never_state.zero_item_completion is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. AC2/AC3: readiness fail-closed
# ═══════════════════════════════════════════════════════════════════════════


def test_readiness_never_run_and_running_not_run_fail_closed(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    never_id = seed_ws_project(session_factory(), video_id=None)
    r = _readiness(session_factory, never_id)
    assert r.status == "not_run"
    assert r.run_state == "never_run"
    assert r.check_state_detail  # check-state detail present (fail-closed)

    queued_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=queued_id, state="queued")
    r = _readiness(session_factory, queued_id)
    assert r.status == "not_run"
    assert r.run_state == "queued"
    assert r.check_state_detail

    # C1-A: a completed CURRENT FULL run (zero-item) is the ready candidate.
    ready_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=ready_id)
    r = _readiness(session_factory, ready_id)
    assert r.status == "ready"  # AC3: completed current run zero blocker
    assert r.run_state == "completed"
    assert r.blockers == 0
    assert r.zero_item_completion is True


def test_readiness_failed_run_not_run_with_detail(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    # C1-A: the failed run must be a FULL-scope run row (audio-only runs
    # are invisible to the FULL authority and would report never_run
    # instead).  Seeded directly through the repo (no worker execution —
    # the FULL band has no server-side evidence composition path).
    failed_id = _seed_full_job(
        session_factory, video_id=video_id, state="failed"
    )
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"
    assert r.run_state == "failed"
    assert r.latest_job_id == failed_id
    assert "failed" in r.check_state_detail


def test_readiness_blocked_when_completed_run_has_blockers(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    """A completed run that FOUND blockers is not clean (AC3 inverse).

    C1-A: blockers must ride on a completed CURRENT FULL run — a seeded
    FULL completion proves the binding 10-detector coverage, and the
    blocker comes from a real QCItem row (invariant 5: later audio-only
    activity never clears a blocker the FULL authority found).
    """
    video_id = seed_ws_project(session_factory(), video_id=None)
    full_job_id = _seed_full_job(session_factory, video_id=video_id)
    with session_factory() as s:
        repo = QCItemRepository(s)
        repo.create(
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            layer_ref_type="video_item",
            layer_ref_id=video_id,
            reason_code="audio_missing",
            evidence_window_key=f"c1a-blocker:{video_id}",
            evidence={"source": "seed-c1a", "job_id": full_job_id},
            severity="blocker",
            category="audio_missing",
            detector="audio_missing",
            detector_revision="1.0.0",
            confidence=1.0,
            confidence_source="derived",
            checkpoint_ref="seed-c1a",
        )
        s.commit()
    assert _count_qc_items(session_factory, video_id) >= 1
    r = _readiness(session_factory, video_id)
    assert r.status == "blocked"
    assert r.run_state == "completed"
    assert r.blockers >= 1

    # A NEWER completed audio-only run does not clear the FULL authority's
    # blocker verdict (invariant 5 — the blocker query still blocks).
    _seed_full_job(
        session_factory, video_id=video_id, scope=SCOPE_AUDIO,
        detectors=["audio_missing", "av_sync_drift"],
    )
    r2 = _readiness(session_factory, video_id)
    assert r2.status == "blocked"
    assert r2.run_state == "completed"
    assert r2.latest_job_id == full_job_id


# ═══════════════════════════════════════════════════════════════════════════
# 4. AC4: idempotency — active duplicate conflict, completed reuse
# ═══════════════════════════════════════════════════════════════════════════


def test_idempotency_active_duplicate_conflict_fail_closed(
    session_factory, svc: JobService
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    first = _submit(session_factory, video_id=video_id)
    with pytest.raises(IdempotencyKeyInUse):
        _submit(session_factory, video_id=video_id)
    # distinct video → distinct key → allowed even while the first is active
    other_id = seed_ws_project(session_factory(), video_id=None)
    second = _submit(session_factory, video_id=other_id)
    assert second.job_id != first.job_id


def test_idempotency_completed_duplicate_reuse(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    first = _submit(session_factory, video_id=video_id)
    worker.run_once()
    assert _job_state(session_factory, first.job_id) == "completed"
    items_after_first = _count_qc_items(session_factory, video_id)

    second = _submit(session_factory, video_id=video_id)
    assert second.reused is True
    assert second.job_id == first.job_id
    # exactly one effect set — the completed run is reused, not re-run
    assert _count_qc_items(session_factory, video_id) == items_after_first
    assert len(_attempt_results(session_factory, first.job_id)) == 1


def test_idempotency_key_changes_with_generation_or_scope(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    gen1 = _submit(session_factory, video_id=video_id, generation="1")
    worker.run_once()
    assert _job_state(session_factory, gen1.job_id) == "completed"

    # same video, bumped generation → different evidence fingerprint → a NEW
    # logical run is created (completed job is NOT reused across generations)
    with session_factory() as s:
        fp2 = evidence_fingerprint(
            s, workspace_id=WS, video_item_id=video_id, generation="2"
        )
        assert fp2 != _attempt_results(session_factory, gen1.job_id)[0][
            "evidence_fingerprint"
        ]
    gen2 = _submit(session_factory, video_id=video_id, generation="2")
    assert gen2.reused is False
    assert gen2.job_id != gen1.job_id


# ═══════════════════════════════════════════════════════════════════════════
# 5. AC5: restart / retry never duplicate QCItems or run effects
# ═══════════════════════════════════════════════════════════════════════════


def test_restart_replay_no_duplicate_qcitem_or_run_effect(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    result = _submit(
        session_factory,
        video_id=video_id,
        detector_args=audio_scope_args(
            source_has_audio_missing_output_envelope(video_id=video_id)
        ),
    )
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"
    items_first = _qc_items(session_factory, video_id)
    assert items_first, "fixture must create at least one blocker"
    first_run_id = _attempt_results(session_factory, result.job_id)[0]["run_id"]

    # Crash-restart: the SAME job row is replayed (lease/attempts dropped)
    _force_replay(session_factory, result.job_id)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"

    # zero duplicate QCItems (natural-key idempotency of the orchestrator)
    items_second = _qc_items(session_factory, video_id)
    assert len(items_second) == len(items_first)
    assert {i.evidence_window_key for i in items_second} == {
        i.evidence_window_key for i in items_first
    }
    # run effect is a single completion — the orchestrator fingerprint is
    # deterministic, so the restarted run carried the SAME run_id evidence
    results = _attempt_results(session_factory, result.job_id)
    assert len(results) == 1
    assert results[0]["run_id"] == first_run_id
    assert results[0]["zero_item_completion"]["evidence"] is False


def test_worker_retry_transient_no_duplicate_qcitem(
    session_factory, svc: JobService, worker: DurableWorker, sleeper: FakeSleeper
) -> None:
    """In-worker retry after a transient failure (deadline exceeded) still
    yields exactly ONE item set and ONE completion evidence block."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    result = _submit(
        session_factory,
        video_id=video_id,
        detector_args=audio_scope_args(
            source_has_audio_missing_output_envelope(video_id=video_id)
        ),
    )

    from app.services.qc_checks.runner import QC_RUNNER_DEADLINE_EXCEEDED, QcRunnerError
    from app.workflow import qc_checks_handler as h

    real_runner = h.run_full_check_set
    calls = {"n": 0}

    def flaky_runner(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise QcRunnerError(
                QC_RUNNER_DEADLINE_EXCEEDED, "simulated first-attempt deadline"
            )
        return real_runner(*args, **kwargs)

    try:
        h.run_full_check_set = flaky_runner  # type: ignore[assignment]
        worker.run_once()
    finally:
        h.run_full_check_set = real_runner

    assert _job_state(session_factory, result.job_id) == "completed"
    assert calls["n"] == 2, "exactly one retry after the transient failure"
    assert len(_attempt_errors(session_factory, result.job_id)) == 1
    results = _attempt_results(session_factory, result.job_id)
    assert len(results) == 1, "only the SUCCESSFUL attempt carries completion"
    assert results[0]["completed"] is True
    # exactly one item set across both attempts
    items = _qc_items(session_factory, video_id)
    assert len(items) >= 1
    assert len({i.evidence_window_key for i in items}) == len(items)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Read authority: stale filtering (evidence fingerprint + policy hash)
# ═══════════════════════════════════════════════════════════════════════════


def test_read_authority_stale_when_evidence_fingerprint_changes(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    # C1-A: staleness attaches to the FULL authority (the seeded FULL run
    # is current for generation "1" — helpers must pass generation through).
    full_job_id = _seed_full_job(session_factory, video_id=video_id)
    assert _readiness(session_factory, video_id).status == "ready"

    # the video's evidence changed (generation bump simulates re-import /
    # source replacement) → not_run.  (The generation knob is folded into
    # the completion's evidence fingerprint at submit time, so a bumped
    # generation makes the completion's evidence fingerprint NON-current:
    # the envelope gate fires first with the evidence-identity reason.
    # The policy-hash sibling below exercises the manifest-staleness
    # branch instead — the two staleness surfaces are covered between
    # them.)
    r = _readiness(session_factory, video_id, generation="2")
    assert r.status == "not_run"
    assert r.run_state == "failed"
    assert "evidence fingerprint" in r.check_state_detail
    assert r.check_state_detail
    with session_factory() as s:
        state = latest_check_run_state(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            evidence_fingerprint=evidence_fingerprint(
                s, workspace_id=WS, video_item_id=video_id, generation="2"
            ),
            policy_content_hash=policy_bundle()["policy_content_hash"],
        )
    assert state.run_state == "failed"
    assert state.job_id == full_job_id
    assert "evidence fingerprint" in state.check_state_detail


def test_read_authority_stale_when_policy_hash_changes(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    video_id = seed_ws_project(session_factory(), video_id=None)
    # C1-A: policy-hash staleness attaches to the FULL authority.
    _seed_full_job(session_factory, video_id=video_id)

    # a different (newer) policy hash — the run was computed against the old
    # policy → STALE for the new policy → not_run.  (Staleness via the
    # caller-supplied CURRENT policy is the manifest-staleness branch: the
    # seeded completion still matches its OWN manifest identity, so the
    # envelope gate passes and the manifest-vs-current comparison fires.)
    other_hash = "f" * 64
    assert other_hash != policy_bundle()["policy_content_hash"]
    with session_factory() as s:
        fp = evidence_fingerprint(s, workspace_id=WS, video_item_id=video_id)
        state = latest_check_run_state(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            evidence_fingerprint=fp,
            policy_content_hash=other_hash,
        )
        readiness = check_run_readiness(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            evidence_fingerprint=fp,
            policy_content_hash=other_hash,
        )
    assert state.run_state == "stale"
    assert readiness.status == "not_run"
    assert readiness.policy_matches is False


# ═══════════════════════════════════════════════════════════════════════════
# 7. C1-A: FULL-run authority — the binding 10-detector coverage gate
# ═══════════════════════════════════════════════════════════════════════════


def _seed_full_job(
    session_factory,
    *,
    video_id: str,
    state: str = "completed",
    scope: str = SCOPE_FULL,
    detectors: list[str] | None = None,
    summary_errors: int = 0,
    summary_skipped: int = 0,
    stale_fp: bool = False,
    policy_hash: str | None = None,
    policy_id: str | None = None,
    tamper_manifest_fp: bool = False,
    tamper_completion_scope: bool = False,
    tamper_evidence_fp: bool = False,
    tamper_policy_id: bool = False,
    tamper_generation: bool = False,
    drop_summary_key: str | None = None,
    summary_override: dict[str, Any] | None = None,
    drop_completion_key: str | None = None,
    extra_revision: bool = False,
    drop_revision: str | None = None,
    empty_revision: str | None = None,
    duplicate_detector: bool = False,
    requested_count: int | None = None,
    run_count: int | None = None,
) -> str:
    """Seed ONE durable RUN_QC_CHECKS job with a controlled envelope.

    Fresh real DB through the production ``JobRepository`` path (Decision
    A — seeding through the repo, never HTTP): the completion block is
    shaped EXACTLY like ``build_completion_block`` (schema/job_type/
    completed/run_id + policy identity + fingerprints + measured summary +
    zero-item evidence), so the read authority trusts it exactly as it
    trusts a real worker run.

    C2-A1 tamper knobs (each produces EXACTLY one envelope defect so the
    matrix proves the fail-closed gate names it): manifest tamper
    (``tamper_manifest_fp``), completion identity tamper
    (``tamper_completion_scope`` / ``tamper_evidence_fp`` /
    ``tamper_policy_id`` / ``tamper_generation`` / ``policy_hash`` /
    ``policy_id``), dropped completion keys (``drop_completion_key``),
    dropped/overridden summary fields (``drop_summary_key`` /
    ``summary_override`` — wrong-typed values included), revision
    envelope defects (``extra_revision`` / ``drop_revision`` /
    ``empty_revision``), detector multiset defects
    (``duplicate_detector`` / ``detectors=``), and count defects
    (``requested_count`` / ``run_count``).
    """
    from app.persistence.jobs import StepInput
    from app.persistence.jobs import JobRepository as _Repo

    band = full_coverage_detectors()
    names = list(detectors) if detectors is not None else list(band)
    if duplicate_detector and names:
        names = names + [names[0]]
    with session_factory() as s:
        fp = evidence_fingerprint(s, workspace_id=WS, video_item_id=video_id)
        if stale_fp:
            fp = "9" * 64
            assert fp != evidence_fingerprint(
                s, workspace_id=WS, video_item_id=video_id
            )
        bundle = policy_bundle()
        manifest_fp = (
            "8" * 64 if tamper_manifest_fp else scope_fingerprint(scope)
        )
        manifest = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "workspace_id": WS,
            "project_id": P1,
            "video_item_id": video_id,
            "evidence_fingerprint": fp,
            "policy_id": bundle["policy_id"],
            "policy_content_hash": bundle["policy_content_hash"],
            "source_generation": "1",
            "source_artifact_id": None,
            "source_sha256": "",
            "scope": scope,
            "scope_fingerprint": manifest_fp,
        }
        repo = _Repo(s)
        key_suffix = uuid.uuid4().hex[:8]
        record = repo.create_job(
            workspace_id=WS,
            job_type=JOB_TYPE_RUN_QC_CHECKS,
            owner_type="video_item",
            owner_id=video_id,
            input_manifest=manifest,
            idempotency_key=(
                f"{JOB_TYPE_RUN_QC_CHECKS}:video_item:{video_id}:{key_suffix}:1"
            ),
            input_generation="1",
            steps=[StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
            actor="api",
        )
        step = repo.list_steps(record.id)[0]
        repo.transition_step(
            step.id, "ready", actor="system",
            expected_revision=step.revision, fence_token="seed-c1a",
        )
        step2 = repo.list_steps(record.id)[0]
        repo.transition_step(
            step2.id, "running", actor="system",
            expected_revision=step2.revision, fence_token="seed-c1a",
        )
        step3 = repo.list_steps(record.id)[0]
        if state == "completed":
            revisions = {name: "1.0.0" for name in names}
            if extra_revision:
                revisions["ghost_detector"] = "9.9.9"
            if drop_revision is not None:
                revisions.pop(drop_revision, None)
            if empty_revision is not None and empty_revision in revisions:
                revisions[empty_revision] = ""
            summary: dict[str, Any] = {
                "run_id": "c" * 64,
                "checks_requested": (
                    requested_count
                    if requested_count is not None
                    else len(names)
                ),
                "checks_run": (
                    run_count if run_count is not None else len(names)
                ),
                "checks_skipped": summary_skipped,
                "created": 0,
                "reused": 0,
                "resolved_after_recheck": 0,
                "reopened_stale": 0,
                "not_applicable": len(names),
                "errors": summary_errors,
                "cancelled": False,
                "deadline_exceeded": False,
                "run_sec": 0.001,
                "per_detector": {},
            }
            if drop_summary_key is not None:
                summary.pop(drop_summary_key, None)
            if summary_override:
                summary.update(summary_override)
            completion = {
                "schema_version": RUN_QC_SCHEMA_VERSION,
                "job_type": JOB_TYPE_RUN_QC_CHECKS,
                "completed": True,
                "run_id": "c" * 64,
                "policy_id": (
                    "tampered-policy"
                    if tamper_policy_id
                    else (
                        policy_id
                        if policy_id is not None
                        else bundle["policy_id"]
                    )
                ),
                "policy_content_hash": (
                    policy_hash
                    if policy_hash is not None
                    else bundle["policy_content_hash"]
                ),
                "source_generation": (
                    "999" if tamper_generation else "1"
                ),
                "source_artifact_id": None,
                "source_artifact_fingerprint": "",
                "evidence_fingerprint": (
                    "7" * 64 if tamper_evidence_fp else fp
                ),
                "scope": (
                    SCOPE_AUDIO if tamper_completion_scope else scope
                ),
                "scope_fingerprint": scope_fingerprint(
                    SCOPE_AUDIO if tamper_completion_scope else scope
                ),
                "detectors": names,
                "detector_revisions": revisions,
                "summary": summary,
                "zero_item_completion": {
                    "evidence": (
                        summary_errors == 0
                        and summary_skipped == 0
                        and True
                    ),
                    "qc_items_created": 0,
                    "issues_found": 0,
                    "checks_run": len(names),
                    "not_applicable": len(names),
                },
            }
            if drop_completion_key is not None:
                completion.pop(drop_completion_key, None)
            repo.record_attempt(
                job_id=record.id,
                step_id=step3.id,
                step_code="run_qc_checks",
                attempt=1,
                worker_id="seed-c1a",
                fence_token="seed-c1a",
                result=completion,
            )
            repo.transition_step(
                step3.id, "completed", actor="system",
                expected_revision=step3.revision, fence_token="seed-c1a",
            )
            r1 = repo.transition_job(
                record.id, "running", actor="system",
                expected_revision=record.revision,
            )
            repo.transition_job(
                record.id, "completed", actor="system",
                expected_revision=r1.revision,
            )
        elif state == "running":
            repo.transition_job(
                record.id, "running", actor="system",
                expected_revision=record.revision,
            )
        elif state == "failed":
            r1 = repo.transition_job(
                record.id, "running", actor="system",
                expected_revision=record.revision,
            )
            repo.transition_job(
                record.id, "failed", actor="system",
                expected_revision=r1.revision,
                error={"code": "QC_RUN_INFRA_FAILURE", "message": "seed-c1a"},
            )
        # "queued" needs no transition (create_job leaves the job queued).
        s.commit()
        return record.id


def _full_state(session_factory, video_id: str):
    with session_factory() as s:
        fp = evidence_fingerprint(s, workspace_id=WS, video_item_id=video_id)
        return latest_check_run_state(
            s,
            workspace_id=WS,
            project_id=P1,
            video_item_id=video_id,
            evidence_fingerprint=fp,
            policy_content_hash=policy_bundle()["policy_content_hash"],
        )


def test_c1a_binding_band_is_ten_detectors_from_frozen_policy(
    session_factory,
) -> None:
    """The authority's FULL band is DERIVED (frozen policy metrics), not
    guessed: 8 visual + 2 audio, equal to scope_detectors(SCOPE_FULL)."""
    band = full_coverage_detectors()
    assert sorted(band) == sorted(scope_detectors(SCOPE_FULL))
    assert len(band) == 10
    visual = set(band) - set(scope_detectors(SCOPE_AUDIO))
    assert len(visual) == 8
    assert set(scope_detectors(SCOPE_AUDIO)) == {"audio_missing", "av_sync_drift"}
    assert full_scope_fingerprint() == scope_fingerprint(SCOPE_FULL)


def test_c1a_audio_only_completed_is_not_full_authority(
    session_factory, svc: JobService, worker: DurableWorker
) -> None:
    """Codex probe: 1 video + exactly 1 completed SCOPE_AUDIO run (the 2
    audio detectors) ⇒ readiness not_run, never ready."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    result = _submit(session_factory, video_id=video_id)  # SCOPE_AUDIO band
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"

    state = _full_state(session_factory, video_id)
    assert state.run_state == "never_run"
    assert state.job_id is None  # the audio job is invisible to the authority
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"
    assert r.run_state == "never_run"
    assert r.check_state_detail


def test_c1a_newer_audio_run_does_not_displace_full_authority(
    session_factory, svc: JobService
) -> None:
    """Completed FULL run, then a NEWER completed audio-only run ⇒ the
    authority still reports the FULL job (latest_job_id) and readiness."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    full_id = _seed_full_job(session_factory, video_id=video_id)
    audio_id = _seed_full_job(
        session_factory, video_id=video_id, scope=SCOPE_AUDIO,
        detectors=["audio_missing", "av_sync_drift"],
    )
    assert full_id != audio_id

    state = _full_state(session_factory, video_id)
    assert state.run_state == "completed"
    assert state.job_id == full_id  # never the newer audio job id
    assert state.scope == SCOPE_FULL
    r = _readiness(session_factory, video_id)
    assert r.status == "ready"
    assert r.latest_job_id == full_id


def test_c1a_audio_over_stale_full_stays_not_run(
    session_factory, svc: JobService
) -> None:
    """Stale FULL run + newer completed audio run ⇒ still not_run (the
    audio run can never backfill full authority)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id, stale_fp=True)
    _seed_full_job(
        session_factory, video_id=video_id, scope=SCOPE_AUDIO,
        detectors=["audio_missing", "av_sync_drift"],
    )
    state = _full_state(session_factory, video_id)
    # stale_fp seeds BOTH manifest and completion with the non-current
    # fingerprint, so the C2-A1 envelope gate fires first: the verdict is
    # coverage-unproven (failed), and the newer audio run stays invisible.
    # The invariant — audio never backfills full authority — holds either
    # way; readiness stays not_run.
    assert state.run_state == "failed"
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"
    assert r.run_state == "failed"


def test_c1a_newest_full_queued_running_failed_never_falls_back(
    session_factory, svc: JobService
) -> None:
    """A completed FULL run followed by a NEWER non-completed FULL run
    (queued / running / failed) ⇒ not_run with the NEWER job id — the
    authority never falls back to the older completed full run."""
    for nonterminal in ("queued", "running", "failed"):
        video_id = seed_ws_project(session_factory(), video_id=None)
        old_id = _seed_full_job(session_factory, video_id=video_id)
        new_id = _seed_full_job(
            session_factory, video_id=video_id, state=nonterminal
        )
        assert old_id != new_id
        state = _full_state(session_factory, video_id)
        assert state.job_id == new_id
        assert state.run_state == (
            "queued" if nonterminal == "queued"
            else "running" if nonterminal == "running"
            else "failed"
        )
        r = _readiness(session_factory, video_id)
        assert r.status == "not_run"
        assert r.latest_job_id == new_id


def test_c1a_newest_full_stale_never_falls_back(
    session_factory, svc: JobService
) -> None:
    """Completed current FULL run, then a NEWER stale FULL run ⇒ stale /
    not_run (no fallback to the older completed full run)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    old_id = _seed_full_job(session_factory, video_id=video_id)
    new_id = _seed_full_job(session_factory, video_id=video_id, stale_fp=True)
    assert old_id != new_id
    state = _full_state(session_factory, video_id)
    assert state.job_id == new_id
    # stale_fp seeds BOTH manifest and completion with the non-current
    # fingerprint: the C2-A1 envelope gate (completion vs CURRENT) fires
    # first, so the verdict is coverage-unproven (failed), not stale.
    # The invariant under test — no fallback to the older valid full —
    # holds either way; readiness stays not_run.
    assert state.run_state == "failed"
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"


def test_c1a_manifest_completion_scope_mismatch_fails_closed(
    session_factory, svc: JobService
) -> None:
    """Manifest scope full but completion scope audio (and the reverse) ⇒
    coverage-unproven ⇒ failed / not_run, never ready."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id, tamper_completion_scope=True)
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert "coverage" in state.check_state_detail
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"

    video_id2 = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(
        session_factory, video_id=video_id2, scope=SCOPE_AUDIO,
        detectors=["audio_missing", "av_sync_drift"],
        tamper_completion_scope=False,
    )
    # audio manifest ⇒ invisible: never_run (not even failed)
    state2 = _full_state(session_factory, video_id2)
    assert state2.run_state == "never_run"


def test_c1a_manifest_scope_fingerprint_mismatch_fails_closed(
    session_factory, svc: JobService
) -> None:
    """Manifest scope full but scope fingerprint tampered ⇒ the submit-time
    band was not the full band ⇒ failed / not_run."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id, tamper_manifest_fp=True)
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert "fingerprint" in state.check_state_detail
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"


def test_c1a_full_missing_any_detector_fails_closed(
    session_factory, svc: JobService
) -> None:
    """A completion missing ANY binding detector (here: one visual check
    dropped) ⇒ coverage-unproven ⇒ failed / not_run.  Partial runs are
    never summed into coverage."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    band = full_coverage_detectors()
    partial = [name for name in band if name != "edge_halo"]
    assert len(partial) == 9
    _seed_full_job(session_factory, video_id=video_id, detectors=partial)
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert "coverage" in state.check_state_detail
    r = _readiness(session_factory, video_id)
    assert r.status == "not_run"


def test_c1a_full_with_errors_or_skipped_fails_closed(
    session_factory, svc: JobService
) -> None:
    """errors > 0 or checks_skipped > 0 in the summary ⇒ the run is never
    the readiness authority (failed / not_run)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id, summary_errors=1)
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert "error" in state.check_state_detail
    assert _readiness(session_factory, video_id).status == "not_run"

    video_id2 = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id2, summary_skipped=2)
    state2 = _full_state(session_factory, video_id2)
    assert state2.run_state == "failed"
    assert "skipped" in state2.check_state_detail
    assert _readiness(session_factory, video_id2).status == "not_run"


def test_c1a_full_current_complete_zero_item_is_ready_candidate(
    session_factory, svc: JobService
) -> None:
    """Completed CURRENT full run, binding coverage, zero errors/skipped,
    zero blockers ⇒ completed + ready candidate (zero-item evidence)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    job_id = _seed_full_job(session_factory, video_id=video_id)
    state = _full_state(session_factory, video_id)
    assert state.run_state == "completed"
    assert state.job_id == job_id
    assert state.scope == SCOPE_FULL
    assert state.zero_item_completion is True
    assert state.summary is not None
    r = _readiness(session_factory, video_id)
    assert r.status == "ready"
    assert r.run_state == "completed"
    assert r.latest_job_id == job_id


def test_c1a_partial_runs_never_sum_into_coverage(
    session_factory, svc: JobService
) -> None:
    """Two partial runs (visual-only shaped + audio-only) side by side ⇒
    still never_run: coverage is per-run, never summed across runs."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    band = full_coverage_detectors()
    visual_only = [name for name in band if name not in ("audio_missing", "av_sync_drift")]
    assert len(visual_only) == 8
    _seed_full_job(session_factory, video_id=video_id, detectors=visual_only)
    _seed_full_job(
        session_factory, video_id=video_id, scope=SCOPE_AUDIO,
        detectors=["audio_missing", "av_sync_drift"],
    )
    state = _full_state(session_factory, video_id)
    # the visual-only FULL-manifest run is newest-full ⇒ failed (coverage);
    # the audio run is invisible.  Either way: never ready.
    assert state.run_state == "failed"
    assert _readiness(session_factory, video_id).status == "not_run"


# ── C2-A1 matrix: completion envelope + unbounded matching-full authority ──


def _band(session_factory=None) -> list[str]:
    from app.persistence.qc_check_runs import full_coverage_detectors

    return full_coverage_detectors()


@pytest.mark.parametrize(
    "key", ["errors", "checks_requested", "checks_run", "checks_skipped"]
)
@pytest.mark.parametrize("bad", ["missing", "null", "string", "bool"])
def test_c2a1_summary_count_wrong_type_never_defaults_to_zero(
    session_factory, svc: JobService, key: str, bad: str
) -> None:
    """C2-A1 probe 1: a count that is missing/null/string/bool is NEVER
    defaulted to zero — the envelope fails closed (failed / not_run)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    if bad == "missing":
        kwargs: dict[str, Any] = {"drop_summary_key": key}
    elif bad == "null":
        kwargs = {"summary_override": {key: None}}
    elif bad == "string":
        kwargs = {"summary_override": {key: "0"}}
    else:
        kwargs = {"summary_override": {key: True if key != "errors" else False}}
        # NOTE: even False (a bool) is rejected — bool is not a JSON
        # number, so the gate cannot be laundered through falsy values.
    _seed_full_job(session_factory, video_id=video_id, **kwargs)  # type: ignore[arg-type]
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"{key}={bad} was accepted as zero"
    assert "not a JSON number" in state.check_state_detail
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize("key", ["checks_skipped"])
@pytest.mark.parametrize("bad", ["missing", "null", "string", "bool"])
def test_c2a1_summary_skipped_wrong_type_never_defaults_to_zero(
    session_factory, svc: JobService, key: str, bad: str
) -> None:
    """C2-A1 probe 1 (skipped leg): same fail-closed rule for
    ``checks_skipped`` — separated so the matrix names the field."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    if bad == "missing":
        kwargs = {"drop_summary_key": key}
    elif bad == "null":
        kwargs = {"summary_override": {key: None}}
    elif bad == "string":
        kwargs = {"summary_override": {key: "0"}}
    else:
        kwargs = {"summary_override": {key: False}}
    _seed_full_job(session_factory, video_id=video_id, **kwargs)  # type: ignore[arg-type]
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"{key}={bad} was accepted as zero"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize(
    "tamper",
    [
        "evidence_fp",
        "policy_hash",
        "policy_id",
        "generation",
        "completion_scope",
    ],
)
def test_c2a1_completion_identity_tamper_fails_closed(
    session_factory, svc: JobService, tamper: str
) -> None:
    """C2-A1 probe 2: the completion identity must match the manifest /
    current video evidence + policy — any tamper fails closed."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    kwargs = {
        "evidence_fp": {"tamper_evidence_fp": True},
        "policy_hash": {"policy_hash": "0" * 64},
        "policy_id": {"policy_id": "other-policy"},
        "generation": {"tamper_generation": True},
        "completion_scope": {"tamper_completion_scope": True},
    }[tamper]
    _seed_full_job(session_factory, video_id=video_id, **kwargs)  # type: ignore[arg-type]
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"tamper {tamper} was accepted"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize(
    "tamper",
    ["drop_schema", "drop_job_type", "drop_evidence_fp", "drop_policy_hash"],
)
def test_c2a1_completion_identity_missing_fails_closed(
    session_factory, svc: JobService, tamper: str
) -> None:
    """C2-A1 probe 2 (missing leg): a dropped identity key is not filled
    with a default — the envelope fails closed."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    key = {
        "drop_schema": "schema_version",
        "drop_job_type": "job_type",
        "drop_evidence_fp": "evidence_fingerprint",
        "drop_policy_hash": "policy_content_hash",
    }[tamper]
    _seed_full_job(
        session_factory, video_id=video_id, drop_completion_key=key
    )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"dropped {key} was accepted"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize(
    "counts", ["missing_counts", "zero", "nine", "eleven", "unequal"]
)
def test_c2a1_summary_counts_must_be_exact_band_size(
    session_factory, svc: JobService, counts: str
) -> None:
    """C2-A1 probe 3: requested/run must each equal the binding band size
    (10) and each other — missing/0/9/11/unequal all fail closed."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    band = _band()
    assert len(band) == 10
    if counts == "missing_counts":
        kwargs: dict[str, Any] = {"drop_summary_key": "checks_requested"}
    elif counts == "zero":
        kwargs = {"requested_count": 0, "run_count": 0}
    elif counts == "nine":
        kwargs = {"requested_count": 9, "run_count": 9}
    elif counts == "eleven":
        kwargs = {"requested_count": 11, "run_count": 11}
    else:
        kwargs = {"requested_count": 10, "run_count": 9}
    _seed_full_job(session_factory, video_id=video_id, **kwargs)  # type: ignore[arg-type]
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"counts {counts} were accepted"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize("flag", ["cancelled", "deadline"])
def test_c2a1_cancelled_or_deadline_true_fails_closed(
    session_factory, svc: JobService, flag: str
) -> None:
    """C2-A1 probe 3 (interrupt leg): cancelled/deadline_exceeded true ⇒
    the run is never authority, even with perfect counts/coverage."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    override = (
        {"cancelled": True} if flag == "cancelled"
        else {"deadline_exceeded": True}
    )
    _seed_full_job(
        session_factory, video_id=video_id, summary_override=override
    )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"{flag}=true was accepted"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize("flag", ["cancelled", "deadline_exceeded"])
def test_c2a1_interrupt_flag_missing_fails_closed(
    session_factory, svc: JobService, flag: str
) -> None:
    """C2-A1 probe 3 (missing-producer-field leg): a dropped interrupt
    flag is not defaulted to False — the envelope fails closed."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(
        session_factory, video_id=video_id, drop_summary_key=flag
    )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"dropped {flag} was accepted"
    assert _readiness(session_factory, video_id).status == "not_run"


def test_c2a1_duplicate_detector_displacing_a_member_fails_closed(
    session_factory, svc: JobService
) -> None:
    """C2-A1 probe 3 (duplicate leg): N names with one duplicated member
    (hence another member missing) fail the multiset gate."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id, duplicate_detector=True)
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert _readiness(session_factory, video_id).status == "not_run"


def test_c2a1_extra_detector_name_fails_closed(
    session_factory, svc: JobService
) -> None:
    """C2-A1 probe 3 (extra leg): N+1 names (band + intruder) fail the
    exact-length multiset gate."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    band = _band()
    _seed_full_job(
        session_factory, video_id=video_id,
        detectors=list(band) + ["ghost_detector"],
    )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert _readiness(session_factory, video_id).status == "not_run"


def test_c2a1_wrong_type_guard_names_the_field(
    session_factory, svc: JobService
) -> None:
    """The wrong-type gate names the offending summary field (fail-closed
    with a reason, not a silent default)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(
        session_factory, video_id=video_id,
        summary_override={"checks_run": "10"},
    )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed"
    assert "'checks_run'" in state.check_state_detail
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize(
    "rev_tamper", ["extra", "missing", "empty", "dropped"]
)
def test_c2a1_revision_envelope_must_match_band_exactly(
    session_factory, svc: JobService, rev_tamper: str
) -> None:
    """C2-A1 probe 3 (revision leg): revision keys must equal the band
    exactly with non-empty values — extra/missing/empty/dropped fail."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    band = _band()
    if rev_tamper == "extra":
        kwargs: dict[str, Any] = {"extra_revision": True}
    elif rev_tamper == "missing":
        kwargs = {"drop_revision": band[0]}
    elif rev_tamper == "empty":
        kwargs = {"empty_revision": band[0]}
    else:
        kwargs = {"drop_completion_key": "detector_revisions"}
    _seed_full_job(session_factory, video_id=video_id, **kwargs)  # type: ignore[arg-type]
    state = _full_state(session_factory, video_id)
    assert state.run_state == "failed", f"revision {rev_tamper} accepted"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize("n_audio", [51, 101])
def test_c2a1_valid_full_survives_many_newer_audio_runs(
    session_factory, svc: JobService, n_audio: int
) -> None:
    """C2-A1 probe 4: a valid completed CURRENT full run keeps exact
    authority even with 51 / 101 NEWER audio-only jobs (history
    pressure past the old 50-row window)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    full_job_id = _seed_full_job(session_factory, video_id=video_id)
    for _ in range(n_audio):
        _seed_full_job(
            session_factory, video_id=video_id, scope=SCOPE_AUDIO,
            detectors=["audio_missing", "av_sync_drift"],
        )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "completed", (
        f"full authority hidden behind {n_audio} newer audio jobs"
    )
    assert state.job_id == full_job_id
    assert _readiness(session_factory, video_id).status == "ready"


def test_c2a1_no_full_with_many_audio_is_never_run(
    session_factory, svc: JobService
) -> None:
    """C2-A1 probe 4 (negative leg): 101 audio-only jobs and NO full job
    ⇒ never_run (audio never creates full authority)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    for _ in range(101):
        _seed_full_job(
            session_factory, video_id=video_id, scope=SCOPE_AUDIO,
            detectors=["audio_missing", "av_sync_drift"],
        )
    state = _full_state(session_factory, video_id)
    assert state.run_state == "never_run"
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize("terminal", ["queued", "running", "failed"])
def test_c2a1_newest_full_nonterminal_never_falls_back(
    session_factory, svc: JobService, terminal: str
) -> None:
    """Newest FULL non-completed (queued/running/failed) ⇒ its own state,
    never an older completed full (no fallback)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id)  # older valid full
    _seed_full_job(session_factory, video_id=video_id, state=terminal)
    state = _full_state(session_factory, video_id)
    assert state.run_state == terminal
    assert _readiness(session_factory, video_id).status == "not_run"


@pytest.mark.parametrize("corrupt", ["stale", "tampered_scope", "bad_counts"])
def test_c2a1_newest_full_corrupt_never_falls_back(
    session_factory, svc: JobService, corrupt: str
) -> None:
    """Newest FULL completed-but-c corrupt (stale/tampered/bad counts) ⇒
    failed, never an older completed full (no fallback)."""
    video_id = seed_ws_project(session_factory(), video_id=None)
    _seed_full_job(session_factory, video_id=video_id)  # older valid full
    if corrupt == "stale":
        _seed_full_job(session_factory, video_id=video_id, stale_fp=True)
    elif corrupt == "tampered_scope":
        _seed_full_job(
            session_factory, video_id=video_id, tamper_completion_scope=True
        )
    else:
        _seed_full_job(
            session_factory, video_id=video_id,
            requested_count=5, run_count=5,
        )
    state = _full_state(session_factory, video_id)
    assert state.run_state in ("failed", "stale"), corrupt
    assert _readiness(session_factory, video_id).status == "not_run"