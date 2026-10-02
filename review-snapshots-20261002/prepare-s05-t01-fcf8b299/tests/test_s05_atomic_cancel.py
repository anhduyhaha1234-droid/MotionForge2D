"""S05-C04-R3 — atomic project-chain cancel endpoint tests (Codex finding 1).

Codex CHANGES_REQUESTED (finding 1, RED gate): the UI derived the cancel
target from a polled chain snapshot, so a click during an
import→proxy→scene transition could target a stale/terminal job or no job
at all (zero /cancel requests reached the backend in the desktop gate).

The correction adds an ATOMIC chain-cancel endpoint
``POST /api/projects/{id}/analyze/cancel`` that resolves the currently
ACTIVE durable step ON THE BACKEND at cancel time (the route re-reads the
chain state and, when the chain is mid-transition, uses the orchestrator's
own idempotent advance pass to materialize the next Job before cancelling
it).  These tests prove, through the REAL UI-facing API surface on real
synthetic media (never mocks):

1. a cancel during an actively RUNNING step resolves and cancels that
   step's job → 200 ``cancel_requested`` with the ACTIVE job id; the chain
   drains to terminal ``cancelled``; retry remains available;
2. a cancel during the step-transition GAP (previous step completed, next
   Job not materialized) still returns 200 and cancels the materialized
   next step — no stale-snapshot miss;
3. a cancel on a genuinely completed chain fails honestly (400) and the
   read-only GET /analyze surface still reports completed;
4. a second cancel while ``cancelling`` is idempotent (200, same job id);
5. unknown project → 404;
6. after cancellation there is NO successor/orphan effect: only the
   chain's own jobs exist, the cancelled job is terminal, and no later
   step Job was created.

Every test uses a temporary Alembic-migrated SQLite DB + temporary managed
root; the API client fixture points ``app.api.deps`` at the same DB and
managed root and restores the previous deps state afterwards.  Tests skip
gracefully when ffmpeg is not available (mirroring test_s05_orchestration).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

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
from app.persistence.models import Job
from app.services import video_proxy
from app.services.scene_detector import register_scene_detection_handler
from app.services.video_proxy import register_generate_proxy_handler
from app.workflow.analyze_orchestrator import get_analyze_orchestrator
from app.workflow.durable_worker import DurableWorker, WorkerConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── DB fixtures (mirror test_s05_orchestration) ─────────────────────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "atomic-cancel.db"


@pytest.fixture()
def session_factory(db_path: Path):
    _upgrade(db_path)
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def session(session_factory) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture()
def managed_root(tmp_path: Path) -> Path:
    root = tmp_path / "managed"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture()
def worker(session_factory, managed_root: Path) -> DurableWorker:
    w = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="atomic-cancel-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
    )
    register_generate_proxy_handler(w)
    register_scene_detection_handler(w)
    return w


@pytest.fixture()
def api_client(session_factory, managed_root: Path, db_path: Path):
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.api.app import app
    from app.config import AppConfig
    from app.workflow.job_service import JobService
    from app.workflow.project_workflow import ProjectWorkflowService

    cfg = AppConfig(
        project_root=db_path.parent / "proj",
        models_dir=db_path.parent / "proj" / "models",
        output_dir=db_path.parent / "proj" / "output",
    )
    saved = (
        getattr(deps, "_config", None),
        getattr(deps, "_project_wf", None),
        getattr(deps, "_job_service", None),
        getattr(deps, "_lifecycle_db", None),
    )
    deps._config = cfg
    deps._project_wf = ProjectWorkflowService(cfg)
    deps._job_service = JobService(session_factory, managed_root=managed_root)
    deps._lifecycle_db = db_path
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    (
        deps._config,
        deps._project_wf,
        deps._job_service,
        deps._lifecycle_db,
    ) = saved


# ── Synthetic media fixtures (real ffmpeg → tmp_path) ───────────────────────


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


def _make_cut_video(path: Path, *, fps: int = 30) -> Path | None:
    """A 2s/60-frame clip with ONE hard cut (blue → red), scene score ~1."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:duration=1.0:size=320x240:rate={fps}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=red:duration=1.0:size=320x240:rate={fps}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return path


@pytest.fixture()
def cfr_cut_video(tmp_path: Path) -> Path:
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    out = _make_cut_video(tmp_path / "cfr_cut.mp4", fps=30)
    assert out is not None, "ffmpeg failed to create the CFR cut fixture"
    return out


# ── API chain helpers ────────────────────────────────────────────────────────


def _create_project(api_client, name: str) -> str:
    resp = api_client.post("/api/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["project_id"]


def _upload_video(api_client, project_id: str, source: Path) -> None:
    with source.open("rb") as handle:
        resp = api_client.post(
            f"/api/projects/{project_id}/video",
            files={"file": (source.name, handle, "video/mp4")},
        )
    assert resp.status_code == 200, resp.text


def _submit_chain(api_client, project_id: str) -> dict:
    resp = api_client.post(
        f"/api/projects/{project_id}/analyze",
        json={"generation": "1", "title": "atomic-cancel"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get_chain(api_client, project_id: str) -> dict:
    resp = api_client.get(f"/api/projects/{project_id}/analyze")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_job(worker: DurableWorker) -> None:
    worker.run_once()


def _advance() -> None:
    """ONE backend-owned chain progression pass (the durable orchestrator)."""
    get_analyze_orchestrator().advance_once()


def _chain_job_rows(session_factory, video_item_id: str) -> list[Job]:
    with session_factory() as s:
        return list(
            s.scalars(
                select(Job).where(
                    Job.owner_type == "video_item",
                    Job.owner_id == video_item_id,
                )
            ).all()
        )


# ── Atomic chain-cancel endpoint tests ──────────────────────────────────────


def test_atomic_cancel_during_active_step_cancels_that_job(
    worker, session_factory, api_client, cfr_cut_video, monkeypatch
) -> None:
    """A cancel during an actively RUNNING step resolves and cancels that
    step's job (the active proxy encode) — 200 cancel_requested with the
    ACTIVE job id; the chain drains to cancelled; retry stays available;
    no successor/orphan is created."""
    pid = _create_project(api_client, "S05C04R3 atomic cancel active")
    _upload_video(api_client, pid, cfr_cut_video)
    _submit_chain(api_client, pid)
    _run_job(worker)  # import completes → committed source artifact
    _advance()
    chain = _get_chain(api_client, pid)
    proxy_job_id = chain["steps"]["proxy"]["job_id"]
    assert proxy_job_id is not None
    assert chain["steps"]["import"]["status"] == "completed"

    real_ffmpeg = video_proxy._run_ffmpeg
    cancel_result: dict[str, str] = {}

    def encode_then_atomic_cancel(ctx, cmd, *, timeout_seconds, staged_path):
        # The atomic endpoint resolves the ACTIVE job (the proxy encode is
        # running right now) — it must return that job, not a stale id.
        resp = api_client.post(f"/api/projects/{pid}/analyze/cancel")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cancel_result["status"] = body["status"]
        cancel_result["job_id"] = body["job_id"]
        return real_ffmpeg(ctx, cmd, timeout_seconds=timeout_seconds, staged_path=staged_path)

    monkeypatch.setattr(video_proxy, "_run_ffmpeg", encode_then_atomic_cancel)
    _run_job(worker)
    monkeypatch.undo()

    # The endpoint resolved the CURRENTLY ACTIVE durable job.
    assert cancel_result["status"] == "cancel_requested"
    assert cancel_result["job_id"] == proxy_job_id

    _advance()
    chain = _get_chain(api_client, pid)
    assert chain["chain_status"] == "cancelled"
    assert chain["steps"]["proxy"]["status"] == "cancelled"
    # The scene step was never created (no orphan jobs).
    assert chain["steps"]["scene_detect"]["status"] == "not_created"
    assert chain["steps"]["scene_detect"]["job_id"] is None

    # No successor/orphan effect: exactly the chain's own import + proxy
    # jobs exist, import completed + proxy terminal-cancelled.
    rows = _chain_job_rows(session_factory, chain["video_item_id"])
    assert len(rows) == 2
    assert {r.state for r in rows} == {"completed", "cancelled"}

    # Retry remains available: the successor path creates a NEW proxy job
    # linked to the cancelled predecessor (contract §8.5).
    resp = api_client.post(f"/api/projects/{pid}/analyze/retry")
    assert resp.status_code == 200, resp.text
    retry = resp.json()
    assert retry["steps"]["proxy"]["job_id"] != proxy_job_id
    assert retry["steps"]["proxy"]["predecessor_job_id"] == proxy_job_id


def test_atomic_cancel_during_transition_gap_materializes_and_cancels(
    worker, session_factory, api_client, cfr_cut_video, monkeypatch
) -> None:
    """A click DURING the import→proxy transition (import completed, proxy
    Job not materialized yet) must still cancel the chain: the endpoint
    materializes the next Job (the orchestrator's own idempotent advance),
    waits for the durable worker to claim it, and cancels it — 200 with
    that job id, chain cancelled, no orphan."""
    import threading
    import time

    pid = _create_project(api_client, "S05C04R3 atomic cancel gap")
    _upload_video(api_client, pid, cfr_cut_video)
    _submit_chain(api_client, pid)
    _run_job(worker)  # import completes
    chain = _get_chain(api_client, pid)
    assert chain["steps"]["import"]["status"] == "completed"
    # The transition gap: NO advance pass ran, so the proxy Job does not
    # exist yet — exactly the window where the old polled-snapshot UI
    # silently did nothing.
    assert chain["steps"]["proxy"]["status"] == "not_created"
    assert chain["steps"]["proxy"]["job_id"] is None

    # Hold the proxy handler once the worker claims it, so the endpoint's
    # bounded claim-wait observes `running` deterministically.
    hold = threading.Event()
    release = threading.Event()
    real_ffmpeg = video_proxy._run_ffmpeg

    def encode_hold(ctx, cmd, *, timeout_seconds, staged_path):
        hold.set()
        release.wait(timeout=15)
        return real_ffmpeg(ctx, cmd, timeout_seconds=timeout_seconds, staged_path=staged_path)

    monkeypatch.setattr(video_proxy, "_run_ffmpeg", encode_hold)

    def run_worker_loop():
        while not release.is_set():
            worker.run_once()
            time.sleep(0.02)

    thread = threading.Thread(target=run_worker_loop, daemon=True)
    thread.start()
    try:
        resp = api_client.post(f"/api/projects/{pid}/analyze/cancel")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "cancel_requested"
        proxy_job_id = body["job_id"]
        assert proxy_job_id is not None
        # The proxy job was materialized by the endpoint's advance pass and
        # cancelled after the worker claimed it (no lease-less cancelling).
        assert hold.wait(timeout=10)
    finally:
        release.set()
        thread.join(timeout=15)
    monkeypatch.undo()

    chain = _get_chain(api_client, pid)
    assert chain["steps"]["proxy"]["job_id"] == proxy_job_id
    assert chain["steps"]["scene_detect"]["status"] == "not_created"

    _advance()
    chain = _get_chain(api_client, pid)
    assert chain["chain_status"] == "cancelled"
    assert chain["steps"]["proxy"]["status"] == "cancelled"
    assert chain["steps"]["scene_detect"]["job_id"] is None

    # No successor/orphan: import (completed) + proxy (cancelled) only.
    rows = _chain_job_rows(session_factory, chain["video_item_id"])
    assert len(rows) == 2
    assert {r.state for r in rows} == {"completed", "cancelled"}
    with session_factory() as s:
        proxy = JobRepository(s).get_job(proxy_job_id)
        assert proxy.job_type == "GENERATE_PROXY"
        assert proxy.owner_id == chain["video_item_id"]
        # Chain jobs are materialized by the orchestrator (not durable
        # successors): the chain link is the shared idempotency-key
        # identity, and no successor/orphan was created by the cancel.
        assert proxy.predecessor_job_id is None


def test_atomic_cancel_on_completed_chain_fails_honestly(
    worker, api_client, cfr_cut_video
) -> None:
    """Cancel on a GENUINELY completed chain fails honestly (400) and the
    read-only GET /analyze surface still reports completed."""
    pid = _create_project(api_client, "S05C04R3 atomic cancel completed")
    _upload_video(api_client, pid, cfr_cut_video)
    _submit_chain(api_client, pid)
    # Drive the whole chain to completed (backend-owned model).
    for _ in range(12):
        _run_job(worker)
        _advance()
        chain = _get_chain(api_client, pid)
        if chain["chain_status"] == "completed":
            break
    assert chain["chain_status"] == "completed"

    resp = api_client.post(f"/api/projects/{pid}/analyze/cancel")
    assert resp.status_code == 400, resp.text
    assert "no active job to cancel" in resp.json()["detail"].lower()

    # GET /analyze stays read-only and honest.
    chain = _get_chain(api_client, pid)
    assert chain["chain_status"] == "completed"
    assert chain["steps"]["scene_detect"]["status"] == "completed"


def test_atomic_cancel_idempotent_while_cancelling(
    worker, api_client, cfr_cut_video, monkeypatch
) -> None:
    """A second cancel while the job is ``cancelling`` is an idempotent 200
    with the SAME job id (contract §6.3, exactly like POST /api/jobs/{id}/cancel)."""
    import threading
    import time

    pid = _create_project(api_client, "S05C04R3 atomic cancel idempotent")
    _upload_video(api_client, pid, cfr_cut_video)
    _submit_chain(api_client, pid)
    _run_job(worker)  # import completes
    _advance()
    chain = _get_chain(api_client, pid)
    proxy_job_id = chain["steps"]["proxy"]["job_id"]
    assert proxy_job_id is not None

    # Hold the proxy encode so the job stays `cancelling` between the two
    # cancel requests (the worker's drain cannot finish while the handler
    # is blocked).
    hold = threading.Event()
    release = threading.Event()
    real_ffmpeg = video_proxy._run_ffmpeg

    def encode_hold(ctx, cmd, *, timeout_seconds, staged_path):
        hold.set()
        release.wait(timeout=15)
        return real_ffmpeg(ctx, cmd, timeout_seconds=timeout_seconds, staged_path=staged_path)

    monkeypatch.setattr(video_proxy, "_run_ffmpeg", encode_hold)

    def run_worker_loop():
        while not release.is_set():
            worker.run_once()
            time.sleep(0.02)

    thread = threading.Thread(target=run_worker_loop, daemon=True)
    thread.start()
    try:
        assert hold.wait(timeout=10)  # proxy encode running
        resp1 = api_client.post(f"/api/projects/{pid}/analyze/cancel")
        assert resp1.status_code == 200, resp1.text
        assert resp1.json()["status"] == "cancel_requested"
        assert resp1.json()["job_id"] == proxy_job_id

        # The job is now cancelling (the held handler cannot drain yet).
        chain = _get_chain(api_client, pid)
        assert chain["steps"]["proxy"]["status"] == "cancelling"

        # Second cancel while cancelling: idempotent 200, same job id.
        resp2 = api_client.post(f"/api/projects/{pid}/analyze/cancel")
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["status"] == "cancel_requested"
        assert resp2.json()["job_id"] == proxy_job_id  # same active job, no new job
    finally:
        release.set()
        thread.join(timeout=15)
    monkeypatch.undo()

    _advance()
    chain = _get_chain(api_client, pid)
    assert chain["chain_status"] == "cancelled"
    assert chain["steps"]["proxy"]["status"] == "cancelled"


def test_atomic_cancel_unknown_project_404(api_client) -> None:
    resp = api_client.post("/api/projects/does-not-exist-xyz/analyze/cancel")
    assert resp.status_code == 404, resp.text
