"""S05-C03 — Final lifecycle correction (Codex CHANGES_REQUESTED round 3).

TRUE process-lifecycle + source-supersession tests through the REAL FastAPI
application lifespan and the REAL durable services on real synthetic media
(ffmpeg-generated CFR fixtures under ``tmp_path``; never mock data):

1. ``test_process_lifecycle_restart_resumes_chain_without_api_requests`` —
   the binary AC: POST once → import completes → the first app/TestClient
   lifespan is FULLY shut down → a FRESH app/TestClient over the same
   database is started → NO analyze API request (no POST/GET/retry) →
   the proxy job materializes and completes; repeat the restart and the
   scene job materializes and completes.  The orchestrator is started and
   stopped by the real lifespan; the startup scan-and-resume is proven
   synchronously (the next chain Job EXISTS immediately after lifespan
   startup, before any polling could have run).  The orchestrator's poll
   cadence is blocked (test-only sleeper) so the materialization on
   restart can only come from the startup scan.

2. ``test_lifespan_owned_chain_completes_across_real_restarts`` — the same
   proof with the REAL process-wide orchestrator accessor and REAL poll
   cadence: three/four app generations over one DB, exactly one POST, zero
   analyze API calls afterwards, chain completes, exactly one effect set,
   and a further restart duplicates nothing.

3. ``test_replace_source_supersedes_video_item_new_chain_completes`` —
   source replacement with a different SHA performs an explicit
   VideoItem/version supersession (PERSISTENCE_DOMAIN_CONTRACT §4/§5):
   the previous VideoItem is ARCHIVED with its jobs/artifacts/scenes
   byte-identical and immutable; a NEW VideoItem gets distinct identity
   and outputs; the NEW chain reaches completed; chain state exposes only
   the current source.  GET stays read-only (snapshot equality around
   repeated GETs).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Job,
    Scene,
    VideoItem,
)
from app.services import video_import, video_proxy
from app.services.scene_detector import register_scene_detection_handler
from app.services.video_proxy import register_generate_proxy_handler
from app.workflow import analyze_orchestrator as ao_module
from app.workflow.analyze_orchestrator import AnalyzeChainOrchestrator
from app.workflow.durable_worker import DurableWorker, WorkerConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── DB fixtures ──────────────────────────────────────────────────────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "lifecycle.db"


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
def worker(session_factory, managed_root: Path) -> DurableWorker:
    """A worker with fake clock/sleeper and the full S05 handler set."""
    w = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="lifecycle-worker",
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
    """TestClient over the real FastAPI app with deps pointed at the same
    database + managed root — the exact UI-facing surface.  (No ``with``:
    the lifespan is NOT entered here; the lifecycle tests below enter it
    explicitly through :func:`_app_generation`.)"""
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
    ao_module.reset_analyze_orchestrator()


@contextmanager
def _app_generation(db_path: Path, managed_root: Path) -> Iterator[Any]:
    """One full application 'process generation'.

    A FRESH JobService (own worker + own session factory), a fresh
    process-wide orchestrator binding and a fresh TestClient whose
    ``with`` block runs the REAL FastAPI lifespan over the SAME database
    file.  On exit the lifespan fully shuts down (orchestrator stop/join
    BEFORE worker stop/join) and the deps singletons are restored.
    """
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.api.app import app
    from app.config import AppConfig
    from app.workflow.job_service import JobService
    from app.workflow.project_workflow import ProjectWorkflowService

    factory = create_session_factory(create_engine_for_path(db_path))
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
    deps._job_service = JobService(factory, managed_root=managed_root)
    deps._lifecycle_db = db_path
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        (
            deps._config,
            deps._project_wf,
            deps._job_service,
            deps._lifecycle_db,
        ) = saved
        ao_module.reset_analyze_orchestrator()


# ── Synthetic media fixtures (real ffmpeg → tmp_path) ───────────────────────


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


def _make_cut_video(
    path: Path, *, fps: int = 30, rate: str | None = None, crf: int = 28
) -> Path | None:
    """A 2s/60-frame clip with ONE hard cut: blue (1s) → red (1s)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    rate_arg = rate or str(fps)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:duration=1.0:size=320x240:rate={rate_arg}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=red:duration=1.0:size=320x240:rate={rate_arg}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return path


def _make_video(
    path: Path,
    *,
    duration: float = 1.0,
    fps: int = 30,
    color: str = "blue",
) -> Path | None:
    """Create a CFR synthetic MP4/H.264 clip (static color)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:duration={duration}:size=320x240:rate={fps}",
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


# ── API / durable-row helpers ───────────────────────────────────────────────


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


def _submit_chain(api_client, project_id: str, title: str | None = None) -> dict:
    resp = api_client.post(
        f"/api/projects/{project_id}/analyze",
        json={"generation": "1", "title": title},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get_chain(api_client, project_id: str) -> dict:
    resp = api_client.get(f"/api/projects/{project_id}/analyze")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _wait_for(predicate, timeout: float = 180.0, message: str = "condition") -> Any:
    """Poll *predicate* (truthy result = done) until it holds or timeout."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except Exception as exc:  # noqa: BLE001 - reported in the failure
            last = f"{type(exc).__name__}: {exc}"
        if last:
            return last
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {message}; last={last!r}")


def _count_jobs_like(session_factory, key_prefix: str) -> int:
    with session_factory() as s:
        return len(
            s.scalars(
                select(Job).where(Job.idempotency_key.like(f"{key_prefix}%"))
            ).all()
        )


def _count_jobs_for_item(session_factory, item_id: str) -> int:
    with session_factory() as s:
        return len(
            s.scalars(
                select(Job).where(
                    Job.owner_type == "video_item", Job.owner_id == item_id
                )
            ).all()
        )


def _chain_jobs(session_factory, video_item_id: str) -> list[Job]:
    with session_factory() as s:
        return list(
            s.scalars(
                select(Job)
                .where(
                    Job.owner_type == "video_item",
                    Job.owner_id == video_item_id,
                )
                .order_by(Job.created_at)
            ).all()
        )


def _scene_rows(session_factory, video_item_id: str) -> list[Scene]:
    with session_factory() as s:
        return list(
            s.scalars(
                select(Scene)
                .where(Scene.video_item_id == video_item_id)
                .order_by(Scene.position)
            ).all()
        )


def _staging_files(managed_root: Path) -> list[Path]:
    staging = managed_root / "staging"
    if not staging.is_dir():
        return []
    return [p for p in staging.rglob("*") if p.is_file()]


def _fast_orchestrator(
    session_factory, managed_root: Path, monkeypatch
) -> AnalyzeChainOrchestrator:
    """A fast-polling orchestrator injected as the route's accessor."""
    orch = AnalyzeChainOrchestrator(
        session_factory,
        managed_root,
        poll_interval=0.01,
    )
    monkeypatch.setattr(ao_module, "get_analyze_orchestrator", lambda: orch)
    return orch


def _drive_to_terminal(
    worker: DurableWorker,
    session_factory,
    video_item_id: str,
    max_rounds: int = 20,
) -> None:
    """Worker + explicit orchestrator advancement (backend ownership) until
    the chain's scene job is terminal — repository reads only."""
    for _ in range(max_rounds):
        worker.run_once()
        ao_module.get_analyze_orchestrator().advance_once()
        jobs = _chain_jobs(session_factory, video_item_id)
        if len(jobs) >= 3 and jobs[-1].state in ("completed", "failed", "cancelled"):
            return
    raise AssertionError("chain did not reach a terminal scene state")


def _item_evidence(session_factory, managed_root: Path, item_id: str) -> dict:
    """Every durable row owned by one VideoItem (jobs, scenes, artifacts,
    owners) plus managed-file content hashes — for byte-identical
    immutability comparisons across supersession."""
    with session_factory() as s:
        jobs = sorted(
            tuple(getattr(j, c) for c in list(Job.__table__.columns.keys()))
            for j in s.scalars(
                select(Job).where(
                    Job.owner_type == "video_item", Job.owner_id == item_id
                )
            ).all()
        )
        scenes = sorted(
            tuple(getattr(r, c) for c in list(Scene.__table__.columns.keys()))
            for r in s.scalars(
                select(Scene).where(Scene.video_item_id == item_id)
            ).all()
        )
        artifact_ids = list(
            s.scalars(
                select(ArtifactOwner.artifact_id).where(
                    ArtifactOwner.owner_type == "video_item",
                    ArtifactOwner.owner_id == item_id,
                )
            ).all()
        )
        artifacts: list[tuple] = []
        owners: list[tuple] = []
        for aid in artifact_ids:
            art = s.get(Artifact, str(aid))
            if art is not None:
                artifacts.append(
                    tuple(getattr(art, c) for c in list(Artifact.__table__.columns.keys()))
                )
            owners.extend(
                tuple(getattr(o, c) for c in list(ArtifactOwner.__table__.columns.keys()))
                for o in s.scalars(
                    select(ArtifactOwner).where(ArtifactOwner.artifact_id == str(aid))
                ).all()
            )
    files: dict[str, str] = {}
    root = managed_root.resolve()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {
        "jobs": sorted(jobs),
        "scenes": sorted(scenes),
        "artifacts": sorted(artifacts),
        "owners": sorted(owners),
        "files": files,
    }


def _db_snapshot(session_factory, managed_root: Path) -> dict:
    """Every durable row (as plain tuples) + every managed file path."""
    models = (
        Job,
        Scene,
        Artifact,
        ArtifactOwner,
        VideoItem,
    )
    tables: dict[str, list] = {}
    with session_factory() as s:
        for model in models:
            rows = s.execute(select(model)).scalars().all()
            cols = list(model.__table__.columns.keys())
            tables[model.__name__] = sorted(
                tuple(getattr(r, c) for c in cols) for r in rows
            )
    files = sorted(
        str(p.relative_to(managed_root))
        for p in managed_root.rglob("*")
        if p.is_file()
    )
    return {"tables": tables, "files": files}


def _assert_old_files_unchanged(before_files: dict[str, str], after_files: dict[str, str]) -> None:
    """Every managed file of an earlier snapshot still exists with the
    SAME content hash (new files may legitimately appear — the evidence of
    a superseding chain)."""
    missing = [p for p in before_files if p not in after_files]
    changed = [
        p
        for p in before_files
        if p in after_files and after_files[p] != before_files[p]
    ]
    assert missing == [], f"old managed files disappeared: {missing}"
    assert changed == [], f"old managed files changed: {changed}"


# ── AC 1/2: TRUE process lifecycle — lifespan-owned scan-and-resume ─────────


def _blocking_cadence_orchestrator(
    db_path: Path, managed_root: Path
) -> AnalyzeChainOrchestrator:
    """An orchestrator whose poll loop NEVER advances on its own while
    running: the loop's first pass runs (like the startup scan), then the
    sleeper blocks until ``stop()``.  Any chain Job that appears while a
    generation is up can ONLY come from the lifespan startup scan (or an
    explicit submit) — deterministic restart evidence."""
    orch = AnalyzeChainOrchestrator(
        create_session_factory(create_engine_for_path(db_path)),
        managed_root,
        poll_interval=3600.0,
    )

    def _blocking_sleeper(seconds: float) -> None:
        deadline = time.monotonic() + float(seconds)
        while time.monotonic() < deadline:
            if orch._stop.is_set():  # stop() must join promptly
                return
            time.sleep(0.01)

    orch._sleeper = _blocking_sleeper  # test-only deterministic cadence
    return orch


def test_process_lifecycle_restart_resumes_chain_without_api_requests(
    db_path, session_factory, managed_root, cfr_cut_video, monkeypatch
) -> None:
    """The binary AC: POST once → import completes → FULL first-app
    shutdown → FRESH app over the same DB → NO analyze API request →
    proxy job materializes and completes; restart again → scene job
    materializes and completes."""
    orch = _blocking_cadence_orchestrator(db_path, managed_root)
    monkeypatch.setattr(ao_module, "get_analyze_orchestrator", lambda: orch)
    factory = session_factory

    try:
        # ── Generation 1: POST once; complete ONLY import; full shutdown.
        with _app_generation(db_path, managed_root) as client1:
            pid = _create_project(client1, "S05C03 lifecycle")
            _upload_video(client1, pid, cfr_cut_video)
            resp = client1.post(
                f"/api/projects/{pid}/analyze",
                json={"generation": "1", "title": cfr_cut_video.name},
            )
            assert resp.status_code == 200, resp.text
            state = resp.json()
            import_job_id = state["steps"]["import"]["job_id"]
            assert import_job_id is not None
            assert state["steps"]["proxy"]["status"] == "not_created"
            assert state["steps"]["scene_detect"]["status"] == "not_created"
            item_id = state["video_item_id"]

            # The app's OWN lifespan worker executes the import job.
            _wait_for(
                lambda: _job_state(factory, import_job_id) == "completed",
                message="import completed in generation 1",
            )
            # The blocked poll loop must NOT have materialized proxy yet —
            # "complete only import" before shutdown.
            assert _count_jobs_like(factory, "GENERATE_PROXY:") == 0
        # lifespan shutdown: orchestrator stopped+joined, worker stopped.

        # ── Generation 2: FRESH app over the same DB; NO analyze API call.
        with _app_generation(db_path, managed_root):
            # The startup scan-and-resume materialized the proxy job
            # synchronously during lifespan startup (idempotent; the
            # blocked loop cannot have created it).
            _wait_for(
                lambda: _count_jobs_like(factory, "GENERATE_PROXY:") == 1,
                timeout=30.0,
                message="proxy job materialized by startup scan",
            )
            assert _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 0
            proxy_job_id = _chain_jobs(factory, item_id)[1].id
            # The fresh app's OWN worker completes the proxy job.
            _wait_for(
                lambda: _job_state(factory, proxy_job_id) == "completed",
                message="proxy completed in generation 2",
            )
            assert _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 0
        # full shutdown of generation 2.

        # ── Generation 3: restart after proxy; scene materializes+completes.
        with _app_generation(db_path, managed_root):
            _wait_for(
                lambda: _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 1,
                timeout=30.0,
                message="scene job materialized by startup scan",
            )
            scene_job_id = _chain_jobs(factory, item_id)[2].id
            _wait_for(
                lambda: _job_state(factory, scene_job_id) == "completed",
                message="scene completed in generation 3",
            )

        # ── Terminal proof: exactly one effect set per step.
        jobs = _chain_jobs(factory, item_id)
        assert [j.job_type for j in jobs] == [
            video_import.JOB_TYPE_ANALYZE_MEDIA,
            video_proxy.JOB_TYPE_GENERATE_PROXY,
            video_import.JOB_TYPE_ANALYZE_MEDIA,
        ]
        assert [j.state for j in jobs] == ["completed", "completed", "completed"]
        assert len(_scene_rows(factory, item_id)) == 2
        assert _count_jobs_like(factory, "GENERATE_PROXY:") == 1
        assert _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 1
        assert _staging_files(managed_root) == []
    finally:
        orch.stop(timeout=2.0)
        ao_module.reset_analyze_orchestrator()


def test_lifespan_owned_chain_completes_across_real_restarts(
    db_path, session_factory, managed_root, cfr_cut_video
) -> None:
    """The same AC with the REAL process-wide orchestrator accessor and
    REAL poll cadence: exactly one POST; the lifespan-owned orchestrator +
    worker of each fresh generation resume the chain from durable rows
    with zero analyze API calls; a further restart duplicates nothing."""
    factory = session_factory
    item_id: str | None = None
    import_job_id: str | None = None

    # Generation 1: POST once; wait for import under the app's own worker.
    with _app_generation(db_path, managed_root) as client1:
        pid = _create_project(client1, "S05C03 real restarts")
        _upload_video(client1, pid, cfr_cut_video)
        resp = client1.post(
            f"/api/projects/{pid}/analyze",
            json={"generation": "1", "title": cfr_cut_video.name},
        )
        assert resp.status_code == 200, resp.text
        state = resp.json()
        item_id = state["video_item_id"]
        import_job_id = state["steps"]["import"]["job_id"]
        assert import_job_id is not None
        _wait_for(
            lambda: _job_state(factory, import_job_id) == "completed",
            message="import completed in generation 1",
        )

    # Generation 2 (restart after import): NO analyze API request; the
    # lifespan startup scan materializes the proxy and the fresh worker
    # completes it.
    with _app_generation(db_path, managed_root):
        _wait_for(
            lambda: (
                _count_jobs_like(factory, "GENERATE_PROXY:") == 1
                and _chain_jobs(factory, item_id)[1].state == "completed"
            ),
            message="proxy materialized + completed in generation 2",
        )

    # Generation 3 (restart after proxy): scene materializes + completes.
    with _app_generation(db_path, managed_root):
        _wait_for(
            lambda: (
                _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 1
                and _chain_jobs(factory, item_id)[2].state == "completed"
            ),
            message="scene materialized + completed in generation 3",
        )

    # Terminal: exactly one effect set per step, staging empty.
    jobs = _chain_jobs(factory, item_id)
    assert len(jobs) == 3
    assert [j.state for j in jobs] == ["completed", "completed", "completed"]
    assert len(_scene_rows(factory, item_id)) == 2
    assert _count_jobs_like(factory, "GENERATE_PROXY:") == 1
    assert _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 1
    assert _staging_files(managed_root) == []

    # Generation 4: a further restart over the completed chain duplicates
    # nothing — the startup scan is a no-op for completed chains.
    with _app_generation(db_path, managed_root):
        time.sleep(3.0)  # several scan/poll cycles
        assert len(_chain_jobs(factory, item_id)) == 3
        assert [j.state for j in _chain_jobs(factory, item_id)] == [
            "completed",
            "completed",
            "completed",
        ]
        assert _count_jobs_like(factory, "GENERATE_PROXY:") == 1
        assert _count_jobs_like(factory, "ANALYZE_MEDIA:scene_detect:") == 1
    ao_module.reset_analyze_orchestrator()


# ── AC 3/4: source replacement → explicit VideoItem supersession ────────────


def test_replace_source_supersedes_video_item_new_chain_completes(
    worker, session_factory, managed_root, api_client, cfr_cut_video, monkeypatch
) -> None:
    """Replacing the project source with a different SHA performs an
    explicit VideoItem/version supersession: the old VideoItem is archived
    with its jobs/artifacts/scenes byte-identical and immutable; the new
    source gets a DISTINCT VideoItem identity and its own outputs; the new
    chain reaches completed; chain state exposes only the current source;
    GET stays read-only."""
    pid = _create_project(api_client, "S05C03 supersede source")
    _upload_video(api_client, pid, cfr_cut_video)
    orch = _fast_orchestrator(session_factory, managed_root, monkeypatch)

    # First chain completes on item_a.
    first = _submit_chain(api_client, pid, cfr_cut_video.name)
    orch.stop(timeout=2.0)
    item_a = first["video_item_id"]
    _drive_to_terminal(worker, session_factory, item_a)
    jobs_a = _chain_jobs(session_factory, item_a)
    assert len(jobs_a) == 3
    assert [j.state for j in jobs_a] == ["completed", "completed", "completed"]
    proxy_artifact_a = _get_chain(api_client, pid)["proxy_artifact_id"]
    sha_a = _get_chain(api_client, pid)["source_sha256"]
    assert sha_a == hashlib.sha256(cfr_cut_video.read_bytes()).hexdigest()
    evidence_a = _item_evidence(session_factory, managed_root, item_a)
    assert len(evidence_a["scenes"]) == 2
    assert len(evidence_a["artifacts"]) == 2  # source + proxy

    # ── Replacement with DIFFERENT evidence (24fps green clip) ──────────
    replacement = _make_video(
        managed_root.parent / "replacement.mp4",
        duration=1.0,
        fps=24,
        color="green",
    )
    assert replacement is not None, "ffmpeg failed to create the replacement fixture"
    assert replacement.read_bytes() != cfr_cut_video.read_bytes()
    _upload_video(api_client, pid, replacement)

    second = _submit_chain(api_client, pid, "replacement")
    orch.stop(timeout=2.0)
    sha_b = hashlib.sha256(replacement.read_bytes()).hexdigest()
    item_b = second["video_item_id"]
    assert item_b != item_a  # DISTINCT VideoItem identity
    assert second["source_sha256"] == sha_b
    assert second["source_sha256"] != sha_a

    # Old VideoItem ARCHIVED; every old row byte-identical (immutable).
    with session_factory() as s:
        old = s.get(VideoItem, item_a)
        assert old is not None
        assert old.status == "archived"
        assert old.archived_at is not None
    after_supersede = _item_evidence(session_factory, managed_root, item_a)
    assert after_supersede["jobs"] == evidence_a["jobs"]
    assert after_supersede["scenes"] == evidence_a["scenes"]
    assert after_supersede["artifacts"] == evidence_a["artifacts"]
    assert after_supersede["owners"] == evidence_a["owners"]
    _assert_old_files_unchanged(evidence_a["files"], after_supersede["files"])

    # The NEW chain COMPLETES with distinct identity and outputs.
    _drive_to_terminal(worker, session_factory, item_b)
    jobs_b = _chain_jobs(session_factory, item_b)
    assert len(jobs_b) == 3
    new_import_b, new_proxy_b, new_scene_b = jobs_b
    old_import_a, old_proxy_a, old_scene_a = _chain_jobs(session_factory, item_a)
    assert new_import_b.id != old_import_a.id
    assert new_proxy_b.id != old_proxy_a.id
    assert new_scene_b.id != old_scene_a.id
    assert [j.state for j in jobs_b] == ["completed", "completed", "completed"]
    rows_b = _scene_rows(session_factory, item_b)
    assert rows_b != []  # fresh scene evidence on the NEW item
    scene_ids_a = [r.id for r in _scene_rows(session_factory, item_a)]
    assert [r.id for r in rows_b] != scene_ids_a  # never the old scene rows

    # Chain state exposes ONLY the current source.
    mid = _get_chain(api_client, pid)
    assert mid["video_item_id"] == item_b
    assert mid["source_sha256"] == sha_b
    assert mid["proxy_artifact_id"] is not None
    assert mid["proxy_artifact_id"] != proxy_artifact_a  # never the stale artifact
    assert mid["scenes_count"] == len(rows_b)

    # The archived chain is frozen: no new jobs, no new files for it.
    assert _count_jobs_for_item(session_factory, item_a) == 3
    assert _staging_files(managed_root) == []

    # GET read-only: repeated reads cause zero DB mutations (C02 guarantee).
    before = _db_snapshot(session_factory, managed_root)
    for _ in range(3):
        assert _get_chain(api_client, pid)["video_item_id"] == item_b
    assert _db_snapshot(session_factory, managed_root) == before

    # ── Replacement with IDENTICAL evidence (same grid, different bytes) ─
    reencoded = _make_cut_video(managed_root.parent / "reencoded.mp4", fps=30, crf=30)
    assert reencoded is not None, "ffmpeg failed to create the re-encoded fixture"
    _upload_video(api_client, pid, reencoded)
    third = _submit_chain(api_client, pid, "reencoded")
    orch.stop(timeout=2.0)
    sha_c = hashlib.sha256(reencoded.read_bytes()).hexdigest()
    item_c = third["video_item_id"]
    assert item_c not in (item_a, item_b)  # another DISTINCT identity
    assert third["source_sha256"] == sha_c
    assert sha_c != sha_a
    _drive_to_terminal(worker, session_factory, item_c)

    jobs_c = _chain_jobs(session_factory, item_c)
    assert len(jobs_c) == 3
    assert [j.state for j in jobs_c] == ["completed", "completed", "completed"]
    final = _get_chain(api_client, pid)
    assert final["video_item_id"] == item_c  # only the CURRENT source
    assert final["source_sha256"] == sha_c
    assert final["proxy_artifact_id"] != mid["proxy_artifact_id"]
    assert final["proxy_artifact_id"] != proxy_artifact_a
    assert final["scenes_count"] == len(_scene_rows(session_factory, item_c))

    # Everything before remains immutable and frozen.
    final_evidence = _item_evidence(session_factory, managed_root, item_a)
    assert final_evidence["jobs"] == evidence_a["jobs"]
    assert final_evidence["scenes"] == evidence_a["scenes"]
    assert final_evidence["artifacts"] == evidence_a["artifacts"]
    assert final_evidence["owners"] == evidence_a["owners"]
    _assert_old_files_unchanged(evidence_a["files"], final_evidence["files"])
    assert _count_jobs_for_item(session_factory, item_a) == 3
    assert _count_jobs_for_item(session_factory, item_b) == 3
    assert [r.id for r in _scene_rows(session_factory, item_a)] == scene_ids_a
    assert [r.id for r in _scene_rows(session_factory, item_b)] == [
        r.id for r in rows_b
    ]
    assert _staging_files(managed_root) == []
