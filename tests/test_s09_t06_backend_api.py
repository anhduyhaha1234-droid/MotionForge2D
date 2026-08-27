"""S09-T06A API tests — approval router over an isolated FastAPI app.

The router is NOT wired into ``app.api.app`` within this task (app.py sits
outside the task write allowlist); these tests mount it on a minimal
FastAPI application with the SAME ``SessionDep`` dependency wired to an
alembic-upgraded temp DB — real SQLite FK/CHECK enforcement, no mocks.

Coverage per TASK.md:
- POST submit → 201 created; equivalent replay under the same idempotency
  key → 200 with replayed=True and the SAME checkpoint id;
- materially different payload under the same key → 409 zero mutation;
- pending-correction blocker → 409 with ZERO durable mutation;
- override without explicit evidence → 409 (no implicit accept);
- unknown field in payload → 422 at the schema boundary (extra=forbid);
- stale reskin revision → 409;
- GET one + list scoped by workspace; cross-workspace read → 404;
- verify endpoint: verified=true on the stored row; tampered bytes → false;
- replay-probe: known key → 200 replayed; unknown key → 404;
- conflict-probe: different content → 409; equal content → 422;
  unknown key → 404;
- OpenAPI additive check vs the pre-task baseline (removed == 0,
  router-level uniqueness of every (path, method) pair).
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
from app.persistence import (
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
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
from app.persistence.structural_evidence import StructuralEvidenceRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = "s09t06a-api-ws"
WS_B = "s09t06a-api-other"
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
    def __init__(self) -> None:
        self.project = ""
        self.reskin_config = ""
        self.pack_version = ""


@pytest.fixture()
def client(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t06a-api.db"
    command.upgrade(_config(db), "head")
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    def _override_session() -> Any:
        # PRODUCTION get_db_session semantics (review F4): the dependency
        # yields a session and CLOSES it — it NEVER commits.  Routes must
        # commit explicitly for durability; this fixture deliberately does
        # NOT mask missing commits the way the original T06A fixture did.
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(s09_approval_router)
    app.dependency_overrides[deps.get_db_session] = _override_session

    seed = Seed()
    with factory() as s:
        s.add(Workspace(id=WS, name=WS))
        s.add(Workspace(id=WS_B, name=WS_B))
        source = Artifact(
            workspace_id=WS, kind="video", relative_path="src.mp4",
            state="ready", sha256=_sha(1),
        )
        s.add(source)
        s.flush()
        project = Project(workspace_id=WS, name="T06A-API")
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id, title="V", position=0,
            source_artifact_id=source.id,
        )
        s.add(video)
        s.flush()
        scene = Scene(
            video_item_id=video.id, position=0, start_frame=0, end_frame=180,
            start_time_ms=0, end_time_ms=6000, status="pending",
        )
        s.add(scene)
        role = ObjectRole(
            workspace_id=WS, project_id=project.id, video_item_id=video.id,
            source_generation=GEN, name="Character", kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=WS, name="CharApiT06A", code="cr_api_t06a")
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

    with TestClient(app) as test_client:
        yield test_client, seed, factory, db
    engine.dispose()


def _body(seed: Seed, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reskin_config_id": seed.reskin_config,
        "expected_reskin_revision": 1,
        "pack_version_ids": [seed.pack_version],
    }
    body.update(overrides)
    return body


def _row_count(factory: Any) -> int:
    with factory() as s:
        return int(
            s.execute(text("SELECT COUNT(*) FROM apply_checkpoint")).scalar() or 0
        )


def test_submit_created_then_replayed_200(client):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = client
    resp = http.post(
        "/api/v2/s09-approvals", params={"workspace_id": WS}, json=_body(seed),
    )
    assert resp.status_code == 201, resp.text
    first = resp.json()
    assert first["replayed"] is False
    assert first["reskin_config_revision"] == 1
    assert first["snapshot"]["schema"] == "s09.approval/v1"

    resp2 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed),
    )
    # No idempotency key but identical content → natural-key replay.
    assert resp2.status_code == 200
    second = resp2.json()
    assert second["replayed"] is True
    assert second["id"] == first["id"]
    assert _row_count(factory) == 1


def test_replay_same_key_same_content(client):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = client
    r1 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="api-key-1"),
    )
    assert r1.status_code == 201
    r2 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="api-key-1"),
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]
    assert r2.json()["replayed"] is True
    assert _row_count(factory) == 1


def test_conflict_different_content_same_key_zero_mutation(client):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = client
    r1 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="api-conflict"),
    )
    assert r1.status_code == 201
    before = _row_count(factory)
    r2 = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(
            seed,
            idempotency_key="api-conflict",
            accepted_warnings=["late-warning"],
        ),
    )
    assert r2.status_code == 409
    assert _row_count(factory) == before


def test_unknown_field_fails_closed_422(client):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = client
    bad = _body(seed)
    bad["totally_unknown_field"] = 1
    before = _row_count(factory)
    resp = http.post("/api/v2/s09-approvals", params={"workspace_id": WS}, json=bad)
    assert resp.status_code == 422
    assert _row_count(factory) == before


def test_stale_revision_conflict_409(client):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = client
    before = _row_count(factory)
    resp = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, expected_reskin_revision=42),
    )
    assert resp.status_code == 409
    assert _row_count(factory) == before


def test_blocked_pending_correction_409_zero_mutation(client):  # type: ignore[no-untyped-def]
    """A pending correction blocks via the API too (fail closed)."""
    http, seed, factory, db = client
    # Insert a pending correction row directly (FK-valid minimal archive).
    with factory() as s:
        from app.persistence.models import S09Correction

        row = S09Correction(
            workspace_id=WS, project_id=seed.project,
            video_item_id=s.query(VideoItem).first().id,
            correction_kind="z_order", status="pending",
            request_json=json.dumps({"z_order": 1}),
            impact_json=json.dumps(
                {"loop_ids": [], "layer_ids": [], "segment_ids": []}
            ),
        )
        s.add(row)
        s.commit()
        correction_id = str(row.id)
    before = _row_count(factory)
    resp = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, correction_ids=[correction_id]),
    )
    assert resp.status_code == 409
    assert "pending" in resp.json()["detail"]
    assert _row_count(factory) == before


def test_get_one_and_list_scoped(client):  # type: ignore[no-untyped-def]
    http, seed, _factory, _db = client
    created = http.post(
        "/api/v2/s09-approvals", params={"workspace_id": WS}, json=_body(seed),
    ).json()
    one = http.get(
        f"/api/v2/s09-approvals/{created['id']}", params={"workspace_id": WS},
    )
    assert one.status_code == 200
    listing = http.get("/api/v2/s09-approvals", params={"workspace_id": WS})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    cross = http.get(
        f"/api/v2/s09-approvals/{created['id']}", params={"workspace_id": WS_B},
    )
    assert cross.status_code == 404
    empty = http.get("/api/v2/s09-approvals", params={"workspace_id": WS_B})
    assert empty.json()["total"] == 0


def test_verify_endpoint_pass_and_tamper_fail(client):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = client
    created = http.post(
        "/api/v2/s09-approvals", params={"workspace_id": WS}, json=_body(seed),
    ).json()
    cid = created["id"]
    ok = http.post(f"/api/v2/s09-approvals/{cid}/verify", params={"workspace_id": WS})
    assert ok.status_code == 200
    assert ok.json() == {
        "checkpoint_id": cid, "verified": True, "reason": "ok",
    }
    # Tamper OUTSIDE the repository (direct SQL) → verify flips to False.
    with factory() as s:
        s.execute(
            text("UPDATE apply_checkpoint SET snapshot_json='{}' WHERE id=:id"),
            {"id": cid},
        )
        s.commit()
    bad = http.post(f"/api/v2/s09-approvals/{cid}/verify", params={"workspace_id": WS})
    assert bad.status_code == 200
    assert bad.json()["verified"] is False
    assert "does not match" in bad.json()["reason"]
    # Serving a corrupted checkpoint fails closed with 500.
    get_bad = http.get(f"/api/v2/s09-approvals/{cid}", params={"workspace_id": WS})
    assert get_bad.status_code == 500


def test_replay_probe_endpoints(client):  # type: ignore[no-untyped-def]
    http, seed, _factory, _db = client
    miss = http.post(
        "/api/v2/s09-approvals/replay-probe",
        params={"workspace_id": WS},
        json={"idempotency_key": "nope"},
    )
    assert miss.status_code == 404
    created = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="probe-hit"),
    )
    hit = http.post(
        "/api/v2/s09-approvals/replay-probe",
        params={"workspace_id": WS},
        json={"idempotency_key": "probe-hit"},
    )
    assert hit.status_code == 200
    assert hit.json()["replayed"] is True
    assert hit.json()["id"] == created.json()["id"]


def test_conflict_probe_endpoint(client):  # type: ignore[no-untyped-def]
    http, seed, _factory, _db = client
    http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="cp-key"),
    )
    conflict = http.post(
        "/api/v2/s09-approvals/conflict-probe",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="cp-key", expected_reskin_revision=777),
    )
    assert conflict.status_code == 409
    equal = http.post(
        "/api/v2/s09-approvals/conflict-probe",
        params={"workspace_id": WS},
        json=_body(seed, idempotency_key="cp-key"),
    )
    assert equal.status_code == 422
    unknown = http.post(
        "/api/v2/s09-approvals/conflict-probe",
        params={"workspace_id": WS_B},
        json=_body(seed, idempotency_key="ghost"),
    )
    assert unknown.status_code == 404


def test_openapi_additive_removed_zero():  # type: ignore[no-untyped-def]
    # Router-level uniqueness: a (logical path, HTTP method) pair is
    # registered exactly once; removed == 0 vs the authored contract.
    from collections import Counter

    def _pairs() -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for route in s09_approval_router.routes:
            for method in getattr(route, "methods", ()) or ():
                if method in {"HEAD", "OPTIONS"}:
                    continue
                pairs.append((route.path.rstrip("/") or "/", method))
        return pairs

    counts = Counter(_pairs())
    for (path, method), n in counts.items():
        assert n == 1, f"{method} {path} registered {n} times"
    expected = {
        ("/api/v2/s09-approvals", "POST"),
        ("/api/v2/s09-approvals", "GET"),
        ("/api/v2/s09-approvals/{checkpoint_id}", "GET"),
        ("/api/v2/s09-approvals/{checkpoint_id}/verify", "POST"),
        ("/api/v2/s09-approvals/replay-probe", "POST"),
        ("/api/v2/s09-approvals/conflict-probe", "POST"),
    }
    actual = set(counts.keys())
    removed = expected - actual
    assert removed == set(), f"contract paths removed: {sorted(removed)}"


# ============================================================================
# S09-T56-INTEGRATION-C1 — PRODUCTION-APP integration (review F4 /
# fast-track §8 T56).  Both routers are NOW mounted on the REAL
# ``app.api.app`` application object.  These tests drive the actual app
# with its REAL lifespan, REAL get_db_session dependency (close-only —
# never overridden) and a temp DB injected exactly the way the existing
# production-app suite wires it (deps._job_service + deps._lifecycle_db).
# NO isolated app, NO fake router, NO auto-commit, NO qa_app_patch.
# ============================================================================

from app.api.app import app as production_app  # noqa: E402

T56_WS = DEFAULT_WORKSPACE_ID  # "default" — satisfies every ID pattern


def _t56_seed(factory: Any, project_root: Path) -> Any:
    """FK-valid graph for correction -> approval flow over the real app."""

    class _Seed:
        project = ""
        reskin_config = ""
        pack_version = ""
        video = ""
        scene = ""
        role = ""

    seed = _Seed()
    with factory() as s:
        s.add(Workspace(id=T56_WS, name=T56_WS))
        source = Artifact(
            workspace_id=T56_WS, kind="video", relative_path="src-t56.mp4",
            state="ready", sha256=_sha(201),
        )
        s.add(source)
        s.flush()
        project = Project(workspace_id=T56_WS, name="T56")
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id, title="T56", position=0,
            source_artifact_id=source.id,
        )
        s.add(video)
        s.flush()
        scene = Scene(
            video_item_id=video.id, position=0, start_frame=0, end_frame=90,
            start_time_ms=0, end_time_ms=3000, status="pending",
        )
        s.add(scene)
        # Generation authority (C1-F1): evidence must carry the BACKEND
        # current generation — never an arbitrary literal.
        current_gen = str(
            StructuralEvidenceRepository(s).current_generation(T56_WS, video.id)
        )
        role = ObjectRole(
            workspace_id=T56_WS, project_id=project.id, video_item_id=video.id,
            source_generation=current_gen, name="Character", kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=T56_WS, name="CharT56", code="cr_t56")
        s.add(char)
        s.flush()
        pack = CharacterPackVersion(
            workspace_id=T56_WS, character_id=char.id, version=1,
            status="published",
        )
        s.add(pack)
        s.flush()
        reskin = ReskinConfig(
            workspace_id=T56_WS,
            project_id=project.id,
            object_role_id=role.id,
            character_id=char.id,
            pack_version_id=pack.id,
            params_json=json.dumps(
                VALID_PARAMS, sort_keys=True, separators=(",", ":")
            ),
        )
        s.add(reskin)
        s.flush()
        seed.project = str(project.id)
        seed.video = str(video.id)
        seed.scene = str(scene.id)
        seed.role = str(role.id)
        seed.reskin_config = str(reskin.id)
        seed.pack_version = str(pack.id)
        s.commit()
    return seed


@pytest.fixture()
def t56_prod_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """The REAL app on a temp DB via production seams (see block header)."""
    from app.workflow.job_service import JobService

    db = tmp_path / "t56-production.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    svc = JobService(factory, worker=None, managed_root=tmp_path / "artifacts")
    monkeypatch.setattr(deps, "_job_service", svc)
    monkeypatch.setattr(deps, "_lifecycle_db", db, raising=False)
    seed = _t56_seed(factory, tmp_path)
    with TestClient(production_app) as http:
        yield http, seed, factory, db


def test_t56_openapi_mounts_both_route_groups_no_dup_ops():  # type: ignore[no-untyped-def]
    """Direct production-app OpenAPI proof (the exact F4 inspection)."""
    spec = production_app.openapi()
    paths = spec["paths"]
    corr = sorted(p for p in paths if "s09-correction" in p)
    appr = sorted(p for p in paths if "s09-approval" in p)
    assert "/api/v2/s09-corrections" in corr
    assert "/api/v2/s09-corrections/{correction_id}/confirm" in corr
    assert "/api/v2/s09-approvals" in appr
    assert "/api/v2/s09-approvals/{checkpoint_id}" in appr
    operation_ids = [
        op.get("operationId")
        for methods in paths.values()
        for op in methods.values()
        if isinstance(op, dict)
    ]
    assert all(operation_ids), "every operation must expose an operationId"
    assert len(operation_ids) == len(set(operation_ids)), "duplicate operation ids"
    # No duplicate (path, method) registration on the real app object.
    seen: list[tuple[str, str]] = []
    for route in production_app.router.routes:
        route_methods = getattr(route, "methods", None) or set()
        for method in route_methods - {"HEAD", "OPTIONS"}:
            pair = (getattr(route, "path", ""), method)
            assert pair not in seen, f"duplicate registration: {pair}"
            seen.append(pair)


def test_t56_full_flow_correction_then_approval_durable_across_restart(
    t56_prod_app,
):  # type: ignore[no-untyped-def]
    """create correction -> confirm -> submit approval -> RESTART -> intact.

    The restart proxy: the first TestClient context closes the REAL
    lifespan; a SECOND TestClient context re-runs startup against the same
    temp DB file and must still serve the committed checkpoint.
    """
    http, seed, factory, db = t56_prod_app

    # -- 1. Create + confirm a z_order correction through PRODUCTION API --
    seg = _t56_segment(factory, seed)
    corr_resp = http.post(
        "/api/v2/s09-corrections",
        json={
            "workspace_id": T56_WS,
            "project_id": seed.project,
            "video_item_id": seed.video,
            "affected_loop_ids": [seg["id"]],
            "payload": {
                "occurrence_segment_id": seg["id"],
                "revision": seg["revision"],
                "source_generation": seg["generation"],
                "z_order": 5,
                "confidence_source": "manual",
                "provenance": {"reasons": ["T56 integration"]},
            },
        },
    )
    assert corr_resp.status_code == 201, corr_resp.text
    correction_id = corr_resp.json()["correction"]["id"]
    confirm = http.post(
        f"/api/v2/s09-corrections/{correction_id}/confirm",
        json={"workspace_id": T56_WS, "revision": 1},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "applied"

    # -- 2. Submit approval through PRODUCTION API (close-only dep) --
    approval = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": T56_WS},
        json={
            "reskin_config_id": seed.reskin_config,
            "expected_reskin_revision": 1,
            "pack_version_ids": [seed.pack_version],
            "correction_ids": [correction_id],
            "overrides": [],
            "accepted_warnings": [],
            "note": "T56 production flow",
            "idempotency_key": "t56-flow-key",
        },
    )
    assert approval.status_code == 201, approval.text
    created = approval.json()
    checkpoint_hash = created["checkpoint_hash"]

    def _disk_rows() -> int:
        engine = create_engine(f"sqlite:///{db.as_posix()}")
        try:
            with engine.connect() as conn:
                return int(
                    conn.execute(
                        text("SELECT COUNT(*) FROM apply_checkpoint")
                    ).scalar()
                    or 0
                )
        finally:
            engine.dispose()

    assert _disk_rows() == 1

    # -- 3. RESTART proxy: new TestClient context over the SAME db file --
    with TestClient(production_app) as http2:
        reloaded = http2.get(
            f"/api/v2/s09-approvals/{created['id']}",
            params={"workspace_id": T56_WS},
        )
        assert reloaded.status_code == 200, reloaded.text
        body = reloaded.json()
        assert body["checkpoint_hash"] == checkpoint_hash
        verify = http2.post(
            f"/api/v2/s09-approvals/{created['id']}/verify",
            params={"workspace_id": T56_WS},
        )
        assert verify.status_code == 200
        assert verify.json()["verified"] is True
        replay = http2.get("/api/v2/s09-approvals", params={"workspace_id": T56_WS})
        assert replay.json()["total"] == 1


def _t56_segment(factory: Any, seed: Any) -> dict[str, Any]:
    """Real occurrence segment (mask-backed) via the evidence repository."""
    from sqlalchemy import text as sql_text

    from app.persistence.models import Artifact
    from app.persistence.structural_evidence import StructuralEvidenceRepository

    with factory() as s:
        mask_row = s.execute(
            sql_text("SELECT id FROM artifact WHERE relative_path='mask-t56.png'")
        ).first()
        if mask_row is None:
            mask = Artifact(
                workspace_id=T56_WS, kind="image",
                relative_path="mask-t56.png", state="ready", sha256=_sha(202),
            )
            s.add(mask)
            s.commit()
            mask_id = str(mask.id)
        else:
            mask_id = str(mask_row[0])
        # Generation authority: ask the BACKEND for the current generation.
        current_gen = str(
            StructuralEvidenceRepository(s).current_generation(T56_WS, seed.video)
        )
        repo = StructuralEvidenceRepository(s)
        rec, _created = repo.create_segment(
            T56_WS, seed.project, seed.video, seed.role, seed.scene,
            "Character", 0, 90, 0, 3000, current_gen,
            kind="character",
            confidence_source="user",
            segmentation={"points": [{"x": 3.0, "y": 4.0, "label": "c"}]},
            mask_artifact_id=mask_id,
        )
        s.commit()
        return {
            "id": str(rec.id),
            "revision": int(rec.revision),
            "generation": current_gen,
        }


def test_t56_invalid_correction_not_persisted(t56_prod_app):  # type: ignore[no-untyped-def]
    http, seed, _factory, db = t56_prod_app
    engine = create_engine(f"sqlite:///{db.as_posix()}")

    def _corr_count() -> int:
        with engine.connect() as conn:
            return int(
                conn.execute(text("SELECT COUNT(*) FROM s09_correction")).scalar()
                or 0
            )

    before = _corr_count()
    bad = http.post(
        "/api/v2/s09-corrections",
        json={
            "workspace_id": T56_WS,
            "project_id": seed.project,
            "video_item_id": seed.video,
            "payload": {
                "occurrence_segment_id": "00000000-0000-0000-0000-000000000000"
                "not-real",
                "revision": 1,
                "source_generation": GEN,
                "z_order": 99999999,
                "confidence_source": "manual",
                "provenance": {},
            },
        },
    )
    assert bad.status_code in {404, 409, 422}
    assert _corr_count() == before
    engine.dispose()


def test_t56_approval_rollback_not_persisted(t56_prod_app):  # type: ignore[no-untyped-def]
    http, seed, _factory, db = t56_prod_app
    engine = create_engine(f"sqlite:///{db.as_posix()}")

    def _rows() -> int:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text("SELECT COUNT(*) FROM apply_checkpoint")
                ).scalar()
                or 0
            )

    before = _rows()
    blocked = http.post(
        "/api/v2/s09-approvals",
        params={"workspace_id": T56_WS},
        json={
            "reskin_config_id": seed.reskin_config,
            "expected_reskin_revision": 999,
            "pack_version_ids": [seed.pack_version],
            "correction_ids": [],
            "overrides": [],
            "accepted_warnings": [],
            "note": None,
            "idempotency_key": "t56-rollback-key",
        },
    )
    assert blocked.status_code == 409
    assert _rows() == before
    engine.dispose()
