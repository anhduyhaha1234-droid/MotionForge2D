"""S09-T06A-C1 durability tests — production dependency semantics (F4).

Review finding F4: production ``get_db_session`` closes WITHOUT committing;
the original T06A API fixture auto-committed after every request and masked
the missing ``session.commit()`` in the submit route.  These tests re-prove
durability under EXACT production semantics:

- the HTTP dependency override only yields/closes (no auto-commit anywhere);
- a successful submit MUST be visible from a BRAND-NEW engine/session
  (process restart proxy) including pinned manifest evidence;
- refused/blocked submits leave ZERO rows (no half-written checkpoints);
- replay converges on the SAME single committed row across sessions.

No QA patch, no monkeypatched commit, no test-only commit wrapper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import deps
from app.api.routes.s09_approval import router as s09_approval_router
from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import (
    Artifact,
    Character,
    CharacterPackVersion,
    ObjectRole,
    Project,
    ReskinConfig,
    Scene,
    VideoItem,
    Workspace,
)
from app.services.s09_approval import S09ApprovalRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = "s09t06ac1-ws"
GEN = "3"

VALID_PARAMS = {
    "anchor": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "fit_mode": "contain",
    "clip_mode": "asset_alpha",
    "offset": {"x": 0.0, "y": 0.0},
    "rotation_offset_deg": 0.0,
    "opacity": 1.0,
}


def _sha(n: int) -> str:
    return f"{n:064x}"


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


class Seed:
    project = ""
    reskin_config = ""
    pack_version = ""


def _seed(factory: Any) -> Seed:
    """Minimal FK-valid workspace graph for an approval submission."""
    seed = Seed()
    with factory() as s:
        s.add(Workspace(id=WS, name=WS))
        source = Artifact(
            workspace_id=WS, kind="video", relative_path="src-c1.mp4",
            state="ready", sha256=_sha(101),
        )
        s.add(source)
        s.flush()
        project = Project(workspace_id=WS, name="T06A-C1")
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id, title="C1", position=0,
            source_artifact_id=source.id,
        )
        s.add(video)
        s.flush()
        scene = Scene(
            video_item_id=video.id, position=0, start_frame=0, end_frame=90,
            start_time_ms=0, end_time_ms=3000, status="pending",
        )
        s.add(scene)
        role = ObjectRole(
            workspace_id=WS, project_id=project.id, video_item_id=video.id,
            source_generation=GEN, name="Character", kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=WS, name="CharC1", code="cr_c1")
        s.add(char)
        s.flush()
        pack = CharacterPackVersion(
            workspace_id=WS, character_id=char.id, version=1, status="published",
        )
        s.add(pack)
        s.flush()
        reskin = ReskinConfig(
            workspace_id=WS,
            project_id=project.id,
            object_role_id=role.id,
            character_id=char.id,
            pack_version_id=pack.id,
            params_json=json.dumps(VALID_PARAMS, sort_keys=True, separators=(",", ":")),
        )
        s.add(reskin)
        s.flush()
        seed.project = project.id
        seed.reskin_config = reskin.id
        seed.pack_version = pack.id
        s.commit()
    return seed


def _body(seed: Seed, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reskin_config_id": seed.reskin_config,
        "expected_reskin_revision": 1,
        "pack_version_ids": [seed.pack_version],
    }
    body.update(overrides)
    return body


def _fresh_count(db: Path) -> int:
    """Row count read through a COMPLETELY NEW engine (restart proxy)."""
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(text("SELECT COUNT(*) FROM apply_checkpoint")).scalar()
                or 0
            )
    finally:
        engine.dispose()


@pytest.fixture()
def prod_env(tmp_path: Path):  # type: ignore[no-untyped-def]
    """App + DB wired with PRODUCTION dependency semantics (close-only)."""
    db = tmp_path / "t06a-c1.db"
    command.upgrade(_config(db), "head")
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    def _production_get_db_session() -> Any:
        # Mirrors app.api.deps.get_db_session EXACTLY: yield, then close().
        # No commit. If a route forgets to commit, its writes evaporate.
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(s09_approval_router)
    app.dependency_overrides[deps.get_db_session] = _production_get_db_session
    seed = _seed(factory)
    with TestClient(app) as client:
        yield client, seed, factory, db
    engine.dispose()


def test_submit_is_durable_for_new_sessions(prod_env):  # type: ignore[no-untyped-def]
    """AC1: production semantics submit -> BRAND-NEW session reloads it."""
    http, seed, factory, db = prod_env
    resp = http.post(
        "/api/v2/s09-approvals", params={"workspace_id": WS}, json=_body(seed)
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()

    # Fresh ENGINE (process-restart proxy) must already see exactly ONE row.
    assert _fresh_count(db) == 1

    # Fresh SESSION from a different factory handle re-reads and re-verifies
    # the immutable checkpoint INCLUDING pinned evidence columns.
    fresh_engine = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        from sqlalchemy.orm import Session as OrmSession

        with OrmSession(bind=fresh_engine) as s2:
            from app.persistence.models import ApplyCheckpoint
            from app.services.s09_approval import S09ApprovalRepository

            repo = S09ApprovalRepository(s2)
            record = repo.get_checkpoint(created["id"], WS)
            verified = repo.verify_checkpoint(record.id, WS)
            assert verified.verified is True
            assert record.checkpoint_hash == created["checkpoint_hash"]
            assert record.pack_version_ids == [seed.pack_version]
            assert record.snapshot["schema"] == "s09.approval/v1"
            row = s2.query(ApplyCheckpoint).filter_by(id=record.id).one()
            assert row.pack_version_ids_json == json.dumps(
                [seed.pack_version], separators=(",", ":")
            )
    finally:
        fresh_engine.dispose()


def _pending_correction(factory: Any, project_id: str, video_id: str) -> str:
    from app.persistence.models import S09Correction

    with factory() as s:
        row = S09Correction(
            workspace_id=WS, project_id=project_id, video_item_id=video_id,
            correction_kind="z_order", status="pending",
            request_json=json.dumps({"z_order": 3}),
            impact_json=json.dumps({"loop_ids": []}),
        )
        s.add(row)
        s.commit()
        return str(row.id)


def test_blocked_submit_leaves_zero_rows(prod_env):  # type: ignore[no-untyped-def]
    """AC2a: blocker refusal -> NO half-written checkpoint anywhere."""
    http, seed, factory, db = prod_env
    video_id: str
    with factory() as s:
        video = s.query(VideoItem).first()
        assert video is not None
        video_id = str(video.id)
    pending_id = _pending_correction(factory, seed.project, video_id)

    before = _fresh_count(db)
    assert before == 0
    resp = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, correction_ids=[pending_id]),
    )
    assert resp.status_code == 409
    # Rollback happened INSIDE the route; nothing was flushed to disk.
    assert _fresh_count(db) == 0


def test_stale_revision_submit_leaves_zero_rows(prod_env):  # type: ignore[no-untyped-def]
    """AC2b: CAS conflict -> ZERO durable mutation under prod semantics."""
    http, seed, _factory, db = prod_env
    resp = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, expected_reskin_revision=99),
    )
    assert resp.status_code == 409
    assert _fresh_count(db) == 0


def test_replay_across_sessions_single_committed_row(prod_env):  # type: ignore[no-untyped-def]
    """Equivalent replay through SEPARATE request sessions converges."""
    http, seed, _factory, db = prod_env
    r1 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="c1-key"),
    )
    assert r1.status_code == 201
    r2 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="c1-key"),
    )
    assert r2.status_code == 200
    assert r2.json()["replayed"] is True
    assert r2.json()["id"] == r1.json()["id"]
    # Both requests used DIFFERENT sessions; exactly one committed row exists.
    assert _fresh_count(db) == 1


def test_midsubmit_failure_rolls_back_no_partial_checkpoint(
    prod_env, monkeypatch
):  # type: ignore[no-untyped-def]
    """AC3: failure AFTER flush but BEFORE route commit -> nothing persists.

    Simulates a crash between the repository insert and the route's
    ``session.commit()`` by raising from a wrapper around the service call.
    The row was already flushed inside the transaction; only an explicit
    route-level rollback prevents a half-written immutable checkpoint.
    """
    http, seed, _factory, db = prod_env
    from app.services import s09_approval as svc_mod

    original = svc_mod.S09ApprovalRepository.submit_checkpoint

    def _explode(self: Any, *args: Any, **kwargs: Any) -> Any:
        record, created = original(self, *args, **kwargs)
        assert created is True  # row is now flushed-but-uncommitted
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(
        svc_mod.S09ApprovalRepository, "submit_checkpoint", _explode
    )
    before = _fresh_count(db)
    with pytest.raises(RuntimeError):
        http.post(
            "/api/v2/s09-approvals",
            params={"workspace_id": WS},
            json=_body(seed),
        )
    # Route-level rollback discarded the flushed row: ZERO rows on disk.
    assert _fresh_count(db) == before == 0


def test_uncommitted_service_writes_never_persist(prod_env):  # type: ignore[no-untyped-def]
    """Negative control: WITHOUT an explicit commit nothing survives close().

    Proves the production-style fixture is honest — a missing route commit
    could never pass AC1 while this control holds.
    """
    _http, seed, factory, db = prod_env
    assert _fresh_count(db) == 0
    with factory() as s:
        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint(
            WS,
            seed.reskin_config,
            1,
            [seed.pack_version],
            idempotency_key="never-committed",
        )
        assert created is True
        assert record.id
    # Session closed WITHOUT commit -> the write must be gone.
    assert _fresh_count(db) == 0
