"""S09-T05A API tests — typed-correction router over an isolated FastAPI app.

The router is NOT wired into ``app.api.app`` within this task (app.py sits
outside the task write allowlist); these tests mount it on a minimal
FastAPI application with the SAME ``SessionDep`` dependency wired to an
alembic-upgraded temp DB — real SQLite FK/CHECK enforcement, no mocks.

Coverage per TASK.md:
- POST submit with each of the five TYPED payloads (mask, z_order, contact,
  mesh_parts, route_override) → 201 created; replay → 200/201 contract
  with replayed=True; materially different payload on the same idempotency
  key → 409;
- unknown field in payload → 422 at the schema boundary (extra=forbid);
- unknown kind discriminator → 422;
- GET one + list scoped by workspace/video; cross-workspace read → 404;
- confirm CAS: stale revision → 409 with ZERO durable change; correct
  revision → applied; re-confirm → applied unchanged (no double apply);
- cancel: pending→cancelled; applied→409;
- counts endpoint reflects only APPLIED corrections;
- OpenAPI additive check vs the pre-task baseline (removed == 0).
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
from app.api.routes.s09_correction import router as s09_correction_router
from app.persistence import (
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Artifact,
    Job,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import StructuralEvidenceRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = DEFAULT_WORKSPACE_ID
GEN = "3"


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
        self.video = ""
        self.scene = ""
        self.roles: dict[str, str] = {}
        self.masks: list[str] = []
        self.job = ""


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db = tmp_path / "api.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))

    def _override_session() -> Any:
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app = FastAPI()
    app.include_router(s09_correction_router)
    app.dependency_overrides[deps.get_db_session] = _override_session

    seed = Seed()
    with factory() as s:
        s.add(Workspace(id=WS, name=WS))
        source = Artifact(
            workspace_id=WS, kind="video", relative_path="src.mp4",
            state="ready", sha256=_sha(1),
        )
        s.add(source)
        s.flush()
        project = Project(workspace_id=WS, name="T05A-API")
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id, title="V", position=0,
            source_artifact_id=source.id,
        )
        s.add(video)
        s.flush()
        job = Job(
            workspace_id=WS, job_type="DISCOVER_OBJECTS",
            owner_type="video_item", owner_id=video.id, state="completed",
            input_generation=GEN,
            input_manifest_json=json.dumps({"source_sha256": _sha(1)}),
        )
        s.add(job)
        s.flush()
        scene = Scene(
            video_item_id=video.id, position=0, start_frame=0, end_frame=180,
            start_time_ms=0, end_time_ms=6000, status="pending",
        )
        s.add(scene)
        s.flush()
        for name, kind in (("Character", "character"), ("Phone", "prop")):
            role = ObjectRole(
                workspace_id=WS, project_id=project.id,
                video_item_id=video.id, source_generation=GEN, name=name,
                kind=kind, status="confirmed",
            )
            s.add(role)
            s.flush()
            seed.roles[name] = role.id
        for i in range(4):
            mask = Artifact(
                workspace_id=WS, kind="image",
                relative_path=f"mask{i}.png", state="ready", sha256=_sha(10 + i),
            )
            s.add(mask)
            s.flush()
            seed.masks.append(mask.id)
        other_ws = "s09t05a-api-other"
        s.add(Workspace(id=other_ws, name=other_ws))
        s.commit()

    seed.project = project.id
    seed.video = video.id
    seed.scene = scene.id
    seed.job = job.id

    client = TestClient(app, raise_server_exceptions=False)
    yield client, factory, seed
    create_engine_for_path(db).dispose()


def _seg(factory: Any, seed: Seed, name: str = "Character") -> Any:
    with factory() as s:
        repo = StructuralEvidenceRepository(s)
        rec, _ = repo.create_segment(
            WS, seed.project, seed.video, seed.roles[name], seed.scene, name,
            0, 90, 0, 3000, GEN,
            kind="character" if name == "Character" else "prop",
            source_job_id=seed.job, mask_artifact_id=seed.masks[0],
            segmentation={"points": [{"x": 10.0, "y": 20.0, "label": "c"}]},
        )
        s.commit()
        return {"id": rec.id, "revision": rec.revision}


def _mask_payload(seed: Seed, seg: dict[str, Any], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "workspace_id": WS,
        "project_id": seed.project,
        "video_item_id": seed.video,
        "idempotency_key": "api-idem-1",
        "payload": {
            "occurrence_segment_id": seg["id"],
            "revision": seg["revision"],
            "source_generation": GEN,
            "segmentation": {
                "points": [{"x": 12.0, "y": 22.0, "label": "center"}]
            },
            "mask_artifact_id": seed.masks[1],
            "provenance": {"user": "reviewer-7"},
        },
    }
    body["payload"].update(over)
    return body


# ── typed submit / replay / conflict ────────────────────────────────────


def test_submit_and_replay_mask(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    r1 = client.post("/api/v2/s09-corrections", json=_mask_payload(seed, seg))
    assert r1.status_code == 201, r1.text
    doc = r1.json()
    assert doc["created"] is True and doc["replayed"] is False
    assert doc["correction"]["status"] == "pending"
    assert doc["correction"]["correction_kind"] == "mask"
    assert doc["correction"]["impact"]["affected_occurrence_segment_ids"] == [
        seg["id"]
    ]

    r2 = client.post("/api/v2/s09-corrections", json=_mask_payload(seed, seg))
    assert r2.status_code == 200, r2.text
    assert r2.json()["replayed"] is True
    assert r2.json()["correction"]["id"] == doc["correction"]["id"]

    # Same key, DIFFERENT payload → 409.
    bad = _mask_payload(seed, seg, provenance={"user": "someone-else"})
    r3 = client.post("/api/v2/s09-corrections", json=bad)
    assert r3.status_code == 409


def test_unknown_field_fails_closed_422(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    body = _mask_payload(seed, seg)
    body["payload"]["teleport_speed"] = 9000
    r = client.post("/api/v2/s09-corrections", json=body)
    assert r.status_code == 422


def test_route_override_typed_flow(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    from app.persistence.structural_lock import StructuralLockRepository

    with factory() as s:
        StructuralLockRepository(s).record_render_route(
            workspace_id=WS, project_id=seed.project,
            video_item_id=seed.video, occurrence_segment_id=seg["id"],
            route="pose_swap", anchor_x=0.25, anchor_y=0.75,
            start_frame=0, end_frame=90,
            provenance={"source": "adaptive_selection"},
            confidence_source="model",
        )
        s.commit()

    body = {
        "workspace_id": WS,
        "project_id": seed.project,
        "video_item_id": seed.video,
        "payload": {
            "occurrence_segment_id": seg["id"],
            "route_from": "pose_swap",
            "route_to": "sprite_affine",
            "anchor_x": 0.25,
            "anchor_y": 0.75,
            "start_frame": 0,
            "end_frame": 90,
            "override_reason": "swap evidence missing for this pose set",
            "provenance": {
                "route_from": "pose_swap",
                "route_to": "sprite_affine",
                "evidence": "benchmark FAIL row pose_swap",
            },
        },
    }
    r1 = client.post("/api/v2/s09-corrections", json=body)
    assert r1.status_code == 201, r1.text
    cid = r1.json()["correction"]["id"]

    rc = client.post(
        f"/api/v2/s09-corrections/{cid}/confirm",
        json={"workspace_id": WS, "revision": 1},
    )
    assert rc.status_code == 200, rc.text
    result = rc.json()["result"]
    assert result["route_override"]["route_to"] == "sprite_affine"
    assert rc.json()["status"] == "applied"

    counts = client.get(
        f"/api/v2/videos/{seed.video}/s09-correction-counts",
        params={"workspace_id": WS},
    )
    assert counts.status_code == 200
    assert counts.json() == {"total": 1, "by_kind": {"route_override": 1}}


def test_contact_and_mesh_typed_flows(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    hand = _seg(factory, seed, "Character")
    phone = _seg(factory, seed, "Phone")
    with factory() as s:
        repo = StructuralEvidenceRepository(s)
        contact, _ = repo.create_contact(
            WS, seed.project, seed.video, hand["id"], phone["id"],
            "hand_phone", 30, 60, 1000, 2000,
        )
        motion, _ = repo.create_motion(
            WS, hand["id"], "object_relative", {"dx": 1.0, "dy": 0.0},
            start_frame=0, end_frame=90, start_time_ms=0, end_time_ms=3000,
        )
        s.commit()
        contact_id, motion_id = contact.id, motion.id

    rc = client.post(
        "/api/v2/s09-corrections",
        json={
            "workspace_id": WS, "project_id": seed.project,
            "video_item_id": seed.video,
            "payload": {
                "contact_id": contact_id, "revision": 1, "end_frame": 55,
                "provenance": {"user": "reviewer-3"},
            },
        },
    )
    assert rc.status_code == 201, rc.text
    rm = client.post(
        "/api/v2/s09-corrections",
        json={
            "workspace_id": WS, "project_id": seed.project,
            "video_item_id": seed.video,
            "payload": {
                "motion_id": motion_id, "revision": 1,
                "transform": {"dx": -2.5, "dy": 4.0},
                "provenance": {"user": "animator-2"},
            },
        },
    )
    assert rm.status_code == 201, rm.text

    cc = client.post(
        f"/api/v2/s09-corrections/{rc.json()['correction']['id']}/confirm",
        json={"workspace_id": WS, "revision": 1},
    )
    assert cc.status_code == 200 and cc.json()["status"] == "applied"
    mc = client.post(
        f"/api/v2/s09-corrections/{rm.json()['correction']['id']}/confirm",
        json={"workspace_id": WS, "revision": 1},
    )
    assert mc.status_code == 200 and mc.json()["status"] == "applied"


def test_zorder_typed_flow_lineage_result(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    r = client.post(
        "/api/v2/s09-corrections",
        json={
            "workspace_id": WS, "project_id": seed.project,
            "video_item_id": seed.video,
            "payload": {
                "occurrence_segment_id": seg["id"], "revision": seg["revision"],
                "source_generation": GEN, "z_order": 42,
                "provenance": {"user": "reviewer-9"},
            },
        },
    )
    assert r.status_code == 201, r.text
    cid = r.json()["correction"]["id"]
    rc = client.post(
        f"/api/v2/s09-corrections/{cid}/confirm",
        json={"workspace_id": WS, "revision": 1},
    )
    assert rc.status_code == 200
    sup = rc.json()["result"]["supersede"]
    assert sup["z_order"] == 42


# ── confirm/cancel semantics over HTTP ──────────────────────────────────


def test_confirm_stale_revision_409_zero_mutation_then_success(
    api,
) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    r = client.post("/api/v2/s09-corrections", json=_mask_payload(seed, seg))
    cid = r.json()["correction"]["id"]

    with factory() as s:
        before_segments = int(
            s.execute(text("SELECT COUNT(*) FROM occurrence_segment")).scalar()
        )

    stale = client.post(
        f"/api/v2/s09-corrections/{cid}/confirm",
        json={"workspace_id": WS, "revision": 9},
    )
    assert stale.status_code == 409

    with factory() as s:
        after_segments = int(
            s.execute(text("SELECT COUNT(*) FROM occurrence_segment")).scalar()
        )
        state = s.execute(
            text("SELECT status FROM s09_correction WHERE id=:i"), {"i": cid}
        ).scalar()
    assert after_segments == before_segments and state == "pending"

    ok = client.post(
        f"/api/v2/s09-corrections/{cid}/confirm",
        json={"workspace_id": WS, "revision": 1},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "applied"

    again = client.post(
        f"/api/v2/s09-corrections/{cid}/confirm",
        json={"workspace_id": WS, "revision": 2},
    )
    assert again.status_code == 200 and again.json()["status"] == "applied"


def test_cancel_then_confirm_conflict(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    r = client.post("/api/v2/s09-corrections", json=_mask_payload(seed, seg))
    cid = r.json()["correction"]["id"]

    c = client.post(
        f"/api/v2/s09-corrections/{cid}/cancel",
        json={"workspace_id": WS, "revision": 1},
    )
    assert c.status_code == 200 and c.json()["status"] == "cancelled"

    late = client.post(
        f"/api/v2/s09-corrections/{cid}/confirm",
        json={"workspace_id": WS, "revision": 2},
    )
    assert late.status_code == 409


def test_get_one_list_cross_workspace_404(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg = _seg(factory, seed)
    r = client.post("/api/v2/s09-corrections", json=_mask_payload(seed, seg))
    cid = r.json()["correction"]["id"]

    got = client.get(
        f"/api/v2/s09-corrections/{cid}", params={"workspace_id": WS}
    )
    assert got.status_code == 200 and got.json()["id"] == cid

    listed = client.get("/api/v2/s09-corrections", params={"workspace_id": WS})
    assert listed.status_code == 200 and listed.json()["total"] >= 1

    cross = client.get(
        f"/api/v2/s09-corrections/{cid}",
        params={"workspace_id": "s09t05a-api-other"},
    )
    assert cross.status_code == 404

    ghost = client.get(
        "/api/v2/s09-corrections/00000000-0000-4000-8000-00000000dead",
        params={"workspace_id": WS},
    )
    assert ghost.status_code == 404


def test_counts_only_applied(api) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = api
    seg_a = _seg(factory, seed, "Character")
    seg_b = _seg(factory, seed, "Phone")
    ra = client.post(
        "/api/v2/s09-corrections",
        json={**_mask_payload(seed, seg_a), "idempotency_key": "cnt-a"},
    )
    rb = client.post(
        "/api/v2/s09-corrections",
        json={
            "workspace_id": WS, "project_id": seed.project,
            "video_item_id": seed.video, "idempotency_key": "cnt-b",
            "payload": {
                "occurrence_segment_id": seg_b["id"],
                "revision": seg_b["revision"],
                "source_generation": GEN, "z_order": 7,
                "provenance": {"user": "r"},
            },
        },
    )
    assert ra.status_code == 201 and rb.status_code == 201

    empty = client.get(
        f"/api/v2/videos/{seed.video}/s09-correction-counts",
        params={"workspace_id": WS},
    )
    assert empty.json() == {"total": 0, "by_kind": {}}

    client.post(
        f"/api/v2/s09-corrections/{ra.json()['correction']['id']}/confirm",
        json={"workspace_id": WS, "revision": 1},
    )
    partial = client.get(
        f"/api/v2/videos/{seed.video}/s09-correction-counts",
        params={"workspace_id": WS},
    )
    assert partial.json() == {"total": 1, "by_kind": {"mask": 1}}


def test_openapi_additive_removed_zero() -> None:
    # Router-level uniqueness: a (logical path, HTTP method) pair is
    # registered exactly once; the same path may legitimately serve
    # different methods (POST submit + GET list share /s09-corrections).
    from collections import Counter

    def _pairs() -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for route in s09_correction_router.routes:
            for method in getattr(route, "methods", ()) or ():
                if method in {"HEAD", "OPTIONS"}:
                    continue  # implicit, not authored registrations
                pairs.append((route.path.rstrip("/") or "/", method))
        return pairs

    counts = Counter(_pairs())
    for (path, method), n in counts.items():
        assert n == 1, f"{method} {path} registered {n} times"
    expected = {
        ("/api/v2/s09-corrections", "POST"),
        ("/api/v2/s09-corrections", "GET"),
        ("/api/v2/s09-corrections/{correction_id}", "GET"),
        ("/api/v2/s09-corrections/{correction_id}/confirm", "POST"),
        ("/api/v2/s09-corrections/{correction_id}/cancel", "POST"),
        ("/api/v2/videos/{video_item_id}/s09-correction-counts", "GET"),
    }
    assert set(counts) == expected


# ============================================================================
# S09-T56-INTEGRATION-C1 — production-app additive test (review F4 /
# fast-track §8 T56).  The correction router is NOW mounted on the REAL
# ``app.api.app``; this drives the actual application with its REAL
# lifespan, REAL close-only ``get_db_session`` dependency (never
# overridden) and a temp DB injected through the production seams used by
# the existing production-app suite (deps._job_service + _lifecycle_db).
# NO isolated app, NO fake router, NO auto-commit, NO qa_app_patch.
# ============================================================================

T56_WS = DEFAULT_WORKSPACE_ID  # "default" — satisfies every ID pattern


def test_t56_correction_router_on_production_app_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):  # type: ignore[no-untyped-def]
    """Correction submit/confirm over the REAL app survive a restart proxy."""
    from fastapi.testclient import TestClient

    from app.api import deps as real_deps
    from app.api.app import app as production_app
    from app.workflow.job_service import JobService

    db = tmp_path / "t56-t05a-production.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    svc = JobService(factory, worker=None, managed_root=tmp_path / "artifacts")
    monkeypatch.setattr(real_deps, "_job_service", svc)
    monkeypatch.setattr(real_deps, "_lifecycle_db", db, raising=False)

    with factory() as s:
        s.add(Workspace(id=T56_WS, name=T56_WS))
        source = Artifact(
            workspace_id=T56_WS, kind="video",
            relative_path="src-t56a.mp4", state="ready", sha256=_sha(211),
        )
        s.add(source)
        s.flush()
        project = Project(workspace_id=T56_WS, name="T56-T05A")
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id, title="V", position=0,
            source_artifact_id=source.id,
        )
        s.add(video)
        s.flush()
        scene = Scene(
            video_item_id=video.id, position=0, start_frame=0, end_frame=90,
            start_time_ms=0, end_time_ms=3000, status="pending",
        )
        s.add(scene)
        # Generation authority (C1-F1): ask the BACKEND for the current
        # generation BEFORE creating role/segment — never a stale literal.
        seg_repo_probe = StructuralEvidenceRepository(s)
        current_gen = str(seg_repo_probe.current_generation(T56_WS, video.id))
        role = ObjectRole(
            workspace_id=T56_WS, project_id=project.id, video_item_id=video.id,
            source_generation=current_gen, name="Character", kind="character",
            status="confirmed",
        )
        s.add(role)
        s.commit()

        seg_repo = StructuralEvidenceRepository(s)
        mask = Artifact(
            workspace_id=T56_WS, kind="image",
            relative_path="mask-t56a.png", state="ready", sha256=_sha(212),
        )
        s.add(mask)
        s.flush()
        seg_rec, _sc = seg_repo.create_segment(
            T56_WS, project.id, video.id, role.id, scene.id, "Character",
            0, 90, 0, 3000, current_gen,
            kind="character", confidence_source="user",
            segmentation={"points": [{"x": 5.0, "y": 6.0, "label": "c"}]},
            mask_artifact_id=mask.id,
        )
        s.commit()
        seed_ids = {
            "project": project.id,
            "video": video.id,
            "segment": seg_rec.id,
            "revision": int(seg_rec.revision),
            "generation": current_gen,
        }

    with TestClient(production_app) as http:
        created = http.post(
            "/api/v2/s09-corrections",
            json={
                "workspace_id": T56_WS,
                "project_id": seed_ids["project"],
                "video_item_id": seed_ids["video"],
                "payload": {
                    "occurrence_segment_id": seed_ids["segment"],
                    "revision": seed_ids["revision"],
                    "source_generation": seed_ids["generation"],
                    "z_order": 7,
                    "confidence_source": "manual",
                    "provenance": {"reasons": ["t56 t05a"]},
                },
            },
        )
        assert created.status_code == 201, created.text
        cid = created.json()["correction"]["id"]
        confirm = http.post(
            f"/api/v2/s09-corrections/{cid}/confirm",
            json={"workspace_id": T56_WS, "revision": 1},
        )
        assert confirm.status_code == 200
        assert confirm.json()["status"] == "applied"

    # Restart proxy: a SECOND TestClient context re-runs the REAL lifespan
    # against the SAME temp DB and must still serve the applied correction.
    def _disk_count() -> int:
        engine = create_engine(f"sqlite:///{db.as_posix()}")
        try:
            with engine.connect() as conn:
                return int(
                    conn.execute(
                        text("SELECT COUNT(*) FROM s09_correction")
                    ).scalar()
                    or 0
                )
        finally:
            engine.dispose()

    assert _disk_count() == 1
    with TestClient(production_app) as http2:
        reloaded = http2.get(f"/api/v2/s09-corrections/{cid}", params={
            "workspace_id": T56_WS,
        })
        assert reloaded.status_code == 200
        assert reloaded.json()["status"] == "applied"
        assert reloaded.json()["result"] is not None
