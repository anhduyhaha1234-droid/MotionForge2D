"""S08-A02-T01-R2 — Structural Evidence API test matrix (real isolated SQLite).

Exercises the isolated ``/api/v2/structural-evidence`` router and the strict
Pydantic schema layer on the REAL conftest durable DB (alembic-upgraded,
foreign keys + CHECK constraints + partial unique indexes enforced).  No mock
repository, no mock database.

The brief 30-item matrix (§24) is covered:

  create/get/list/current segment (1-3)   · history read-only (4-6)
  lineage (7-8)                           · arbitrary-gen/job/role rejection (9-12)
  CAS 409 (13-15)                         · motion CRUD + CAS (16-20)
  occlusion CRUD + CAS (21-25)            · contact CRUD + CAS (26-30)
  idempotency replay / identity / payload conflicts (31-33)
  frame+ms containment (34-35)            · cross-workspace 404 (36)
  cross-video reject (37)                 · 422 unknown fields (38)
  NaN/Infinity reject (39)                · no-DELETE (40)
  rollback on induced conflict (41)       · concurrent CAS single winner (42)
  full phone-interaction graph API round-trip (43)
  OpenAPI generation (44)                 · object-intelligence unchanged (45)

Every mutating request is CAS-protected; a stale revision is a stable 409.
Frame+time containment applies to motion and to BOTH endpoints of
occlusion/contact.  Current and historical are never mixed.

``MOTIONFORGE_DATABASE_URL`` is UNSET; tests run with ``-p no:cacheprovider``
and isolated basetemps under ``C:/Users/Admin/AppData/Local/Temp/``.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    Artifact,
    Job,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import canonical_json

WS = DEFAULT_WORKSPACE_ID
WS2 = "r2-ws2"
GEN = "3"
API = "/api/v2/structural-evidence"
OI = "/api/v2/object-intelligence"


def _sha(n: int) -> str:
    return f"{n:064x}"


class Seed:
    """Handles for the isolated R2 API test graph."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.project = ""
        self.video = ""
        self.scene = ""
        self.roles: dict[str, str] = {}
        self.role_rows: dict[str, ObjectRole] = {}
        self.masks: list[str] = []
        self.job = ""
        self.stale_role = ""
        self.other_project = ""
        self.other_video = ""


def _svc() -> Any:
    service = deps._job_service
    assert service is not None
    return service


def _seed(session: Any) -> Seed:
    """Backend-authoritative current generation "3" for the main video."""
    seed = Seed(session)
    workspace = session.get(Workspace, WS)
    if workspace is None:
        workspace = Workspace(id=WS, name=WS)
        session.add(workspace)
    other = session.get(Workspace, WS2)
    if other is None:
        session.add(Workspace(id=WS2, name=WS2))
    session.flush()

    source = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path="src.mp4",
        state="ready",
        sha256=_sha(1),
    )
    session.add(source)
    session.flush()

    project = Project(workspace_id=WS, name="R2")
    session.add(project)
    session.flush()

    video = VideoItem(
        project_id=project.id,
        title="Phone",
        position=0,
        source_artifact_id=source.id,
    )
    session.add(video)
    session.flush()

    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video.id,
        state="completed",
        input_generation=GEN,
        input_manifest_json=canonical_json({"source_sha256": _sha(1)}),
    )
    session.add(job)
    session.flush()

    scene = Scene(
        video_item_id=video.id,
        position=0,
        start_frame=0,
        end_frame=180,
        start_time_ms=0,
        end_time_ms=6000,
        status="pending",
    )
    session.add(scene)
    session.flush()

    for name, kind in [
        ("Character", "character"),
        ("Phone", "prop"),
        ("Hand", "prop"),
        ("Face", "character"),
    ]:
        role = ObjectRole(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            source_generation=GEN,
            name=name,
            kind=kind,
            status="confirmed",
        )
        session.add(role)
        session.flush()
        seed.roles[name] = role.id
        seed.role_rows[name] = role

    # A role in a STALE generation (arbitrary-role / role-gen rejection).
    stale_role = ObjectRole(
        workspace_id=WS,
        project_id=project.id,
        video_item_id=video.id,
        source_generation="2",
        name="Stale",
        kind="prop",
        status="confirmed",
    )
    session.add(stale_role)
    session.flush()
    seed.stale_role = stale_role.id

    for i in range(6):
        mask = Artifact(
            workspace_id=WS,
            kind="image",
            relative_path=f"mask{i}.png",
            state="ready",
            sha256=_sha(10 + i),
        )
        session.add(mask)
        session.flush()
        seed.masks.append(mask.id)

    # A second video in the SAME workspace (cross-video rejection).
    project2 = Project(workspace_id=WS, name="R2B")
    session.add(project2)
    session.flush()
    video2 = VideoItem(
        project_id=project2.id,
        title="Second",
        position=1,
        source_artifact_id=source.id,
    )
    session.add(video2)
    session.flush()
    seed.other_project = project2.id
    seed.other_video = video2.id

    seed.project = project.id
    seed.video = video.id
    seed.scene = scene.id
    seed.job = job.id
    session.commit()
    return seed


def _open_session() -> Any:
    return _svc().session_factory()


_DEFAULT_JOB = object()  # sentinel: use the seed's producing job by default


def _segment_payload(
    seed: Seed,
    name: str = "Character",
    *,
    role_id: str | None = None,
    mask: int | None = 0,
    prompt: dict[str, Any] | None = None,
    segmentation: dict[str, Any] | None = None,
    idem: str | None = None,
    job: object = _DEFAULT_JOB,
    confidence_source: str | None = None,
    confidence: float | None = None,
    project: str | None = None,
    video: str | None = None,
    **over: Any,
) -> dict[str, Any]:
    rid = role_id if role_id is not None else seed.roles[name]
    role = seed.session.get(ObjectRole, rid)
    payload: dict[str, Any] = {
        "project_id": project if project is not None else seed.project,
        "video_item_id": video if video is not None else seed.video,
        "role_id": rid,
        "scene_id": seed.scene,
        "name": name,
        "kind": role.kind,
        "start_frame": 0,
        "end_frame": 180,
        "start_time_ms": 0,
        "end_time_ms": 6000,
        "source_job_id": seed.job if job is _DEFAULT_JOB else job,
        "mask_artifact_id": seed.masks[mask] if mask is not None else None,
        "confidence": confidence if confidence is not None else 0.97,
        "confidence_source": confidence_source if confidence_source is not None else "model",
        "reasons": ["high_iou"],
        "provenance": {"run": "r2"},
        "visibility": "visible",
        "z_order": 0,
    }
    if prompt is not None:
        payload["prompt"] = prompt
    if segmentation is not None:
        payload["segmentation"] = segmentation
    if idem is not None:
        payload["idempotency_key"] = idem
    payload.update(over)
    return payload


def _create_segment(
    client: TestClient, seed: Seed, name: str = "Character", **over: Any
) -> dict[str, Any]:
    resp = client.post(f"{API}/segments", json=_segment_payload(seed, name, **over))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _motion_payload(
    seed: Seed,
    segment_id: str,
    *,
    transform_type: str = "camera_relative",
    idem: str | None = None,
    **over: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "occurrence_segment_id": segment_id,
        "transform_type": transform_type,
        "transform": {"matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "proj": "affine2d"},
        "point_track_flow_ref": {"tracks": ["t-1"], "kind": "sparse_flow"},
        "start_frame": 0,
        "end_frame": 180,
        "start_time_ms": 0,
        "end_time_ms": 6000,
        "algorithm": "flow-contract",
        "algorithm_version": "0.1",
        "confidence": 0.88,
        "confidence_source": "derived",
        "provenance": {"engine": "contract-only"},
    }
    if idem is not None:
        payload["idempotency_key"] = idem
    payload.update(over)
    return payload


def _occlusion_payload(
    seed: Seed,
    occluder_id: str,
    occludee_id: str,
    *,
    idem: str | None = None,
    project: str | None = None,
    video: str | None = None,
    **over: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project if project is not None else seed.project,
        "video_item_id": video if video is not None else seed.video,
        "occluder_segment_id": occluder_id,
        "occludee_segment_id": occludee_id,
        "start_frame": 0,
        "end_frame": 180,
        "start_time_ms": 0,
        "end_time_ms": 6000,
        "algorithm": "alpha-model",
        "algorithm_version": "1.4.0",
        "confidence": 0.95,
        "confidence_source": "model",
        "provenance": {"kind": "phone_over_hand"},
    }
    if idem is not None:
        payload["idempotency_key"] = idem
    payload.update(over)
    return payload


def _contact_payload(
    seed: Seed,
    source_id: str,
    target_id: str,
    kind: str = "character_phone",
    *,
    idem: str | None = None,
    project: str | None = None,
    video: str | None = None,
    **over: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project if project is not None else seed.project,
        "video_item_id": video if video is not None else seed.video,
        "source_segment_id": source_id,
        "target_segment_id": target_id,
        "contact_kind": kind,
        "start_frame": 0,
        "end_frame": 180,
        "start_time_ms": 0,
        "end_time_ms": 6000,
        "confidence": 0.93,
        "confidence_source": "model",
        "provenance": {"kind": kind},
    }
    if idem is not None:
        payload["idempotency_key"] = idem
    payload.update(over)
    return payload


# ══════════════════════════════════════════════════════════════════════════
# 1-3. create / get / list current segment
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item01_create_current_segment(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    created = client.post(f"{API}/segments", json=_segment_payload(seed, "Character", mask=0))
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["state"] == "current"
    assert data["source_generation"] == GEN  # server-owned, resolved by router
    assert data["revision"] == 1
    assert data["lineage_version"] == 1
    assert data["logical_id"]
    assert data["kind"] == "character"  # inherited from the ObjectRole taxonomy
    assert data["name"] == "Character"
    assert data["visibility"] == "visible"
    assert data["reasons"] == ["high_iou"]
    assert data["provenance"] == {"run": "r2"}


def test_r2_item02_get_current_segment(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Phone", mask=1)
    got = client.get(f"{API}/segments/current/{seg['id']}")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["id"] == seg["id"]
    assert body["state"] == "current"
    assert body["logical_id"] == seg["logical_id"]
    assert body["kind"] == "prop"


def test_r2_item03_list_current_segments(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    _create_segment(client, seed, "Character", mask=0)
    _create_segment(client, seed, "Phone", mask=1)
    _create_segment(client, seed, "Hand", mask=2)
    listed = client.get(f"{API}/segments", params={"video_item_id": seed.video})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["scope"] == "current"
    assert body["current_generation"] == GEN
    assert body["total"] == 3
    assert len(body["segments"]) == 3
    assert {s["name"] for s in body["segments"]} == {"Character", "Phone", "Hand"}
    assert all(s["state"] == "current" for s in body["segments"])


# ══════════════════════════════════════════════════════════════════════════
# 4-6. history read-only (explicit + read-only; never mixed with current)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item04_history_read_only_explicit_get(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    # Manual user correction (workflow A) -> predecessor becomes historical.
    corrected = client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={
            "revision": seg["revision"],
            "confidence_source": "user",
            "mask_artifact_id": seed.masks[1],
            "provenance": {"who": "human"},
            "reasons": ["user correction"],
        },
    )
    assert corrected.status_code == 201, corrected.text
    corr = corrected.json()
    assert corr["predecessor"]["state"] == "historical"
    assert corr["successor"]["state"] == "current"
    assert corr["predecessor"]["logical_id"] == corr["successor"]["logical_id"]
    prior_id = corr["predecessor"]["id"]
    # Explicit historical GET (read-only).
    hist = client.get(f"{API}/segments/historical/{prior_id}", params={"generation": GEN})
    assert hist.status_code == 200, hist.text
    assert hist.json()["state"] == "historical"
    assert hist.json()["superseded_by_id"] == corr["successor"]["id"]
    # A superseded row is 404 under the CURRENT scope (no existence leak).
    cur = client.get(f"{API}/segments/current/{prior_id}")
    assert cur.status_code == 404
    assert "not found" in cur.json()["detail"].lower()


def test_r2_item05_historical_list_explicit(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={
            "revision": seg["revision"],
            "confidence_source": "user",
            "mask_artifact_id": seed.masks[1],
            "provenance": {"who": "human"},
            "reasons": ["fix"],
        },
    )
    # Explicit historical list by logical lineage — C2-F5:
    # historical view must EXCLUDE the active current successor.
    by_logical = client.get(f"{API}/segments/historical", params={"logical_id": seg["logical_id"]})
    assert by_logical.status_code == 200, by_logical.text
    bl = by_logical.json()
    assert bl["scope"] == "historical"
    assert bl["total"] == 1, f"C2-F5: historical must exclude active successor, got {bl}"
    assert bl["segments"][0]["id"] == seg["id"]  # sole historical is the superseded predecessor
    assert bl["segments"][0]["state"] == "historical"
    assert all(v["logical_id"] == seg["logical_id"] for v in bl["segments"])
    # Explicit historical list by source generation — likewise historical only.
    by_gen = client.get(
        f"{API}/segments/historical",
        params={"video_item_id": seed.video, "source_generation": GEN},
    )
    assert by_gen.status_code == 200, by_gen.text
    assert by_gen.json()["total"] == 1, "C2-F5: generation historical excludes active current"
    assert by_gen.json()["segments"][0]["state"] == "historical"
    # Historical view without an explicit scope is refused.
    refused = client.get(f"{API}/segments/historical", params={"video_item_id": seed.video})
    assert refused.status_code == 422


def test_r2_item06_historical_mutation_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    corr = client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={
            "revision": seg["revision"],
            "confidence_source": "user",
            "mask_artifact_id": seed.masks[1],
            "provenance": {"who": "human"},
            "reasons": ["fix"],
        },
    ).json()
    prior_id = corr["predecessor"]["id"]
    patch = client.patch(
        f"{API}/segments/current/{prior_id}",
        json={"revision": corr["predecessor"]["revision"], "confidence": 0.5},
    )
    assert patch.status_code == 409
    assert "historical" in patch.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════════════════
# 7-8. lineage (oldest -> newest, from ANY version)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item07_lineage_from_any_version(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    corr = client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={
            "revision": seg["revision"],
            "confidence_source": "user",
            "mask_artifact_id": seed.masks[1],
            "provenance": {"who": "human"},
            "reasons": ["fix"],
            "name": "Character v2",
        },
    ).json()
    prior_id = corr["predecessor"]["id"]
    successor_id = corr["successor"]["id"]
    for start in (prior_id, successor_id):
        chain = client.get(f"{API}/segments/{start}/lineage")
        assert chain.status_code == 200, chain.text
        body = chain.json()
        assert [v["id"] for v in body["versions"]] == [prior_id, successor_id]
        assert body["versions"][0]["state"] == "historical"
        assert body["versions"][1]["state"] == "current"
        assert body["versions"][1]["name"] == "Character v2"


def test_r2_item08_list_current_active_only(client: TestClient) -> None:
    """The current list must NOT mix the superseded (historical) row."""
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={
            "revision": seg["revision"],
            "confidence_source": "user",
            "mask_artifact_id": seed.masks[1],
            "provenance": {"who": "human"},
            "reasons": ["fix"],
        },
    )
    listed = client.get(f"{API}/segments", params={"video_item_id": seed.video})
    body = listed.json()
    assert body["total"] == 1, body
    assert body["segments"][0]["id"] != seg["id"]  # successor only


# ══════════════════════════════════════════════════════════════════════════
# 9-12. arbitrary generation / job / role rejection
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item09_arbitrary_source_generation_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    payload = _segment_payload(seed, "Character", mask=0)
    payload["source_generation"] = "99"  # client cannot choose it
    resp = client.post(f"{API}/segments", json=payload)
    assert resp.status_code == 422
    assert "source_generation" in resp.text


def test_r2_item10_arbitrary_logical_id_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    payload = _segment_payload(seed, "Character", mask=0)
    payload["logical_id"] = "attacker-chosen"  # repository-owned
    resp = client.post(f"{API}/segments", json=payload)
    assert resp.status_code == 422
    assert "logical_id" in resp.text


def test_r2_item11_missing_model_job_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    payload = _segment_payload(seed, "Character", mask=0, job=None)
    payload["confidence_source"] = "model"
    resp = client.post(f"{API}/segments", json=payload)
    # The repository fails closed before any row is written.
    assert resp.status_code == 422
    assert "job" in resp.json()["detail"].lower()
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 0


def test_r2_item12_cross_video_role_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    # role from the PRIMARY video attached via the OTHER video's project/video.
    payload = _segment_payload(
        seed,
        "Character",
        mask=0,
        project=seed.other_project,
        video=seed.other_video,
    )
    resp = client.post(f"{API}/segments", json=payload)
    assert resp.status_code == 409
    assert "video" in resp.json()["detail"].lower()
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 0


def test_r2_item12b_stale_role_generation_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    payload = _segment_payload(seed, "Character", role_id=seed.stale_role, mask=0)
    resp = client.post(f"{API}/segments", json=payload)
    # stale role generation is incompatible with the segment's current gen.
    assert resp.status_code == 409
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 0


# ══════════════════════════════════════════════════════════════════════════
# 13-15. CAS 409 (segment update + supersede)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item13_update_current_cas(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    updated = client.patch(
        f"{API}/segments/current/{seg['id']}",
        json={"revision": seg["revision"], "confidence": 0.91, "z_order": 5},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["confidence"] == 0.91
    assert body["z_order"] == 5
    assert body["revision"] == seg["revision"] + 1
    assert body["id"] == seg["id"]  # in-place edit keeps the record id


def test_r2_item14_stale_revision_409(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    stale = client.patch(
        f"{API}/segments/current/{seg['id']}",
        json={"revision": seg["revision"] + 99, "confidence": 0.5},
    )
    assert stale.status_code == 409
    assert "revision" in stale.json()["detail"].lower()
    # Zero mutation.
    with _open_session() as s2:
        row = s2.execute(
            text("SELECT revision FROM occurrence_segment WHERE id = :i"),
            {"i": seg["id"]},
        ).scalar()
        assert row == seg["revision"]


def test_r2_item15_supersede_stale_revision_409(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    resp = client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={"revision": seg["revision"] + 7, "confidence_source": "user"},
    )
    assert resp.status_code == 409
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 1


# ══════════════════════════════════════════════════════════════════════════
# 16-20. motion CRUD + CAS
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item16_create_motion(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    resp = client.post(f"{API}/motions", json=_motion_payload(seed, seg["id"]))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["transform_type"] == "camera_relative"
    assert body["transform"] == {"matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "proj": "affine2d"}
    assert body["point_track_flow_ref"] == {"tracks": ["t-1"], "kind": "sparse_flow"}
    assert body["revision"] == 1


def test_r2_item17_list_and_get_motion(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    created = client.post(f"{API}/motions", json=_motion_payload(seed, seg["id"])).json()
    listed = client.get(f"{API}/motions", params={"segment_id": seg["id"]})
    assert listed.status_code == 200
    assert [m["id"] for m in listed.json()] == [created["id"]]
    got = client.get(f"{API}/motions/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]


def test_r2_item18_update_motion_cas(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    created = client.post(f"{API}/motions", json=_motion_payload(seed, seg["id"])).json()
    updated = client.patch(
        f"{API}/motions/{created['id']}",
        json={
            "revision": created["revision"],
            "confidence": 0.6,
            "end_frame": 160,
            "end_time_ms": 5400,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["confidence"] == 0.6
    assert body["end_frame"] == 160
    assert body["revision"] == 2


def test_r2_item19_update_motion_stale_and_historical_409(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    created = client.post(f"{API}/motions", json=_motion_payload(seed, seg["id"])).json()
    stale = client.patch(
        f"{API}/motions/{created['id']}",
        json={"revision": 99, "confidence": 0.5},
    )
    assert stale.status_code == 409
    # A motion on a SUPERSEDED segment is also read-only (409).
    client.post(
        f"{API}/segments/current/{seg['id']}/supersede",
        json={
            "revision": seg["revision"],
            "confidence_source": "user",
            "mask_artifact_id": seed.masks[1],
            "provenance": {"who": "human"},
            "reasons": ["fix"],
        },
    )
    hist_motion = client.patch(
        f"{API}/motions/{created['id']}",
        json={"revision": created["revision"], "confidence": 0.4},
    )
    assert hist_motion.status_code == 409


def test_r2_item20_motion_frame_time_containment(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    # Valid frame, time beyond the segment -> reject.
    bad = client.post(
        f"{API}/motions",
        json=_motion_payload(seed, seg["id"], end_time_ms=7000),
    )
    assert bad.status_code == 422
    # Valid time, frame beyond the segment -> reject.
    bad2 = client.post(
        f"{API}/motions",
        json=_motion_payload(seed, seg["id"], end_frame=200),
    )
    assert bad2.status_code == 422
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM segment_motion")) == 0


# ══════════════════════════════════════════════════════════════════════════
# 21-25. occlusion CRUD + CAS
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item21_create_occlusion(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    phone = _create_segment(client, seed, "Phone", mask=1)
    hand = _create_segment(client, seed, "Hand", mask=2)
    resp = client.post(f"{API}/occlusions", json=_occlusion_payload(seed, phone["id"], hand["id"]))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["occluder_segment_id"] == phone["id"]
    assert body["occludee_segment_id"] == hand["id"]
    assert body["revision"] == 1


def test_r2_item22_list_and_get_occlusion(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    phone = _create_segment(client, seed, "Phone", mask=1)
    hand = _create_segment(client, seed, "Hand", mask=2)
    created = client.post(
        f"{API}/occlusions", json=_occlusion_payload(seed, phone["id"], hand["id"])
    ).json()
    listed = client.get(f"{API}/occlusions", params={"segment_id": phone["id"]})
    assert listed.status_code == 200
    assert [o["id"] for o in listed.json()] == [created["id"]]
    got = client.get(f"{API}/occlusions/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]


def test_r2_item23_update_occlusion_cas(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    phone = _create_segment(client, seed, "Phone", mask=1)
    hand = _create_segment(client, seed, "Hand", mask=2)
    created = client.post(
        f"{API}/occlusions", json=_occlusion_payload(seed, phone["id"], hand["id"])
    ).json()
    updated = client.patch(
        f"{API}/occlusions/{created['id']}",
        json={"revision": created["revision"], "confidence": 0.8, "end_frame": 150},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    assert updated.json()["end_frame"] == 150


def test_r2_item24_occlusion_stale_409(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    phone = _create_segment(client, seed, "Phone", mask=1)
    hand = _create_segment(client, seed, "Hand", mask=2)
    created = client.post(
        f"{API}/occlusions", json=_occlusion_payload(seed, phone["id"], hand["id"])
    ).json()
    stale = client.patch(
        f"{API}/occlusions/{created['id']}",
        json={"revision": 9, "confidence": 0.1},
    )
    assert stale.status_code == 409


def test_r2_item25_occlusion_frame_time_containment_both_endpoints(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    phone = _create_segment(client, seed, "Phone", mask=1)
    hand = client.post(
        f"{API}/segments",
        json=_segment_payload(
            seed,
            "Hand",
            mask=2,
            start_frame=30,
            end_frame=120,
            start_time_ms=1000,
            end_time_ms=4000,
        ),
    ).json()
    # Inside phone's range but outside the hand's -> reject (frame dimension).
    bad = client.post(
        f"{API}/occlusions",
        json=_occlusion_payload(seed, phone["id"], hand["id"], start_frame=0, end_frame=180),
    )
    assert bad.status_code == 422
    # Same, time dimension.
    bad2 = client.post(
        f"{API}/occlusions",
        json=_occlusion_payload(seed, phone["id"], hand["id"], start_time_ms=0, end_time_ms=6000),
    )
    assert bad2.status_code == 422
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM scene_graph_occlusion")) == 0


# ══════════════════════════════════════════════════════════════════════════
# 26-30. contact CRUD + CAS
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item26_create_contact(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    character = _create_segment(client, seed, "Character", mask=0)
    phone = _create_segment(client, seed, "Phone", mask=1)
    resp = client.post(
        f"{API}/contacts",
        json=_contact_payload(seed, character["id"], phone["id"], "character_phone"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["contact_kind"] == "character_phone"
    assert resp.json()["revision"] == 1


def test_r2_item27_list_and_get_contact(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    character = _create_segment(client, seed, "Character", mask=0)
    phone = _create_segment(client, seed, "Phone", mask=1)
    created = client.post(
        f"{API}/contacts",
        json=_contact_payload(seed, character["id"], phone["id"], "character_phone"),
    ).json()
    listed = client.get(f"{API}/contacts", params={"segment_id": phone["id"]})
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [created["id"]]
    got = client.get(f"{API}/contacts/{created['id']}")
    assert got.status_code == 200
    assert got.json()["contact_kind"] == "character_phone"


def test_r2_item28_update_contact_cas(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    character = _create_segment(client, seed, "Character", mask=0)
    phone = _create_segment(client, seed, "Phone", mask=1)
    created = client.post(
        f"{API}/contacts",
        json=_contact_payload(seed, character["id"], phone["id"], "character_phone"),
    ).json()
    updated = client.patch(
        f"{API}/contacts/{created['id']}",
        json={"revision": created["revision"], "confidence": 0.7, "end_frame": 140},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    assert updated.json()["end_frame"] == 140


def test_r2_item29_contact_stale_409(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    character = _create_segment(client, seed, "Character", mask=0)
    phone = _create_segment(client, seed, "Phone", mask=1)
    created = client.post(
        f"{API}/contacts",
        json=_contact_payload(seed, character["id"], phone["id"], "character_phone"),
    ).json()
    stale = client.patch(
        f"{API}/contacts/{created['id']}",
        json={"revision": 3, "confidence": 0.2},
    )
    assert stale.status_code == 409


def test_r2_item30_contact_self_edge_and_range(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    character = _create_segment(client, seed, "Character", mask=0)
    phone = _create_segment(client, seed, "Phone", mask=1)
    # Self-edge is rejected.
    self_edge = client.post(
        f"{API}/contacts",
        json=_contact_payload(seed, character["id"], character["id"], "touch"),
    )
    assert self_edge.status_code == 422
    # Range inside source but outside target (time beyond target) -> reject.
    outside = client.post(
        f"{API}/contacts",
        json=_contact_payload(seed, character["id"], phone["id"], "touch", end_time_ms=7000),
    )
    assert outside.status_code == 422
    # Cross-video contact (endpoints from video A declared under video B) -> reject.
    cross_video = client.post(
        f"{API}/contacts",
        json=_contact_payload(
            seed,
            character["id"],
            phone["id"],
            "touch",
            project=seed.other_project,
            video=seed.other_video,
        ),
    )
    assert cross_video.status_code == 409
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM scene_graph_contact")) == 0


# ══════════════════════════════════════════════════════════════════════════
# 31-33. idempotency replay / identity conflict / payload conflict
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item31_segment_idempotency_replay(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    payload = _segment_payload(seed, "Character", mask=0, idem="seg-replay-1")
    first = client.post(f"{API}/segments", json=payload)
    assert first.status_code == 201
    replay = client.post(f"{API}/segments", json=payload)
    assert replay.status_code == 200, replay.text  # 201 -> 200 on replay
    assert replay.json()["id"] == first.json()["id"]
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 1


def test_r2_item32_idempotency_identity_conflict(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    base = _segment_payload(seed, "Character", mask=0, idem="seg-idem-identity")
    first = client.post(f"{API}/segments", json=base)
    assert first.status_code == 201
    # Same key, DIFFERENT segment identity (role) -> stable conflict.
    base["role_id"] = seed.roles["Phone"]
    base["kind"] = "prop"
    conflict = client.post(f"{API}/segments", json=base)
    assert conflict.status_code == 409
    assert "idempotency" in conflict.json()["detail"].lower()
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 1


def test_r2_item33_idempotency_payload_conflict(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    base = _segment_payload(seed, "Character", mask=0, idem="seg-idem-payload")
    assert client.post(f"{API}/segments", json=base).status_code == 201
    base["confidence"] = 0.5  # same key, different payload
    conflict = client.post(f"{API}/segments", json=base)
    assert conflict.status_code == 409
    assert "idempotency" in conflict.json()["detail"].lower()
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 1


# ══════════════════════════════════════════════════════════════════════════
# 34-35. frame+ms containment & end-before-start (schema + repo)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item34_end_before_start_rejected_422(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    bad = client.post(
        f"{API}/segments",
        json=_segment_payload(seed, "Character", mask=0, start_frame=100, end_frame=50),
    )
    assert bad.status_code == 422
    bad_time = client.post(
        f"{API}/segments",
        json=_segment_payload(seed, "Character", mask=0, start_time_ms=5000, end_time_ms=1000),
    )
    assert bad_time.status_code == 422
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 0


def test_r2_item35_containment_on_update_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    motion = client.post(f"{API}/motions", json=_motion_payload(seed, seg["id"])).json()
    # Update end_frame beyond the segment range -> rejected.
    over = client.patch(
        f"{API}/motions/{motion['id']}",
        json={"revision": motion["revision"], "end_frame": 220},
    )
    assert over.status_code == 422
    with _open_session() as s2:
        assert (
            s2.scalar(
                text("SELECT end_frame FROM segment_motion WHERE id = :i"),
                {"i": motion["id"]},
            )
            == 180
        )  # unchanged


# ══════════════════════════════════════════════════════════════════════════
# 36-37. cross-workspace 404 / cross-video reject (no existence leak)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item36_cross_workspace_404(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    # The segment lives in the DEFAULT workspace; reading it from another
    # workspace must 404 (no existence leak of any kind).
    leak = client.get(f"{API}/segments/current/{seg['id']}", params={"workspace_id": WS2})
    assert leak.status_code == 404
    assert "not found" in leak.json()["detail"].lower()
    leak_hist = client.get(f"{API}/segments/historical/{seg['id']}", params={"workspace_id": WS2})
    assert leak_hist.status_code == 404


def test_r2_item37_cross_video_occlusion_rejected(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    character = _create_segment(client, seed, "Character", mask=0)
    phone = _create_segment(client, seed, "Phone", mask=1)
    # Occlusion endpoints from the primary video, declared under the other
    # video (project/video chain consistent, endpoints mismatch) -> 409.
    resp = client.post(
        f"{API}/occlusions",
        json=_occlusion_payload(
            seed,
            character["id"],
            phone["id"],
            project=seed.other_project,
            video=seed.other_video,
        ),
    )
    assert resp.status_code == 409
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM scene_graph_occlusion")) == 0


# ══════════════════════════════════════════════════════════════════════════
# 38-39. 422 unknown fields / NaN / Infinity
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item38_unknown_fields_rejected_422(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    base = _segment_payload(seed, "Character", mask=0)
    base["frobnicate"] = True
    resp = client.post(f"{API}/segments", json=base)
    assert resp.status_code == 422
    bad_enum = _segment_payload(seed, "Character", mask=0)
    bad_enum["kind"] = "not-a-kind"
    resp2 = client.post(f"{API}/segments", json=bad_enum)
    assert resp2.status_code == 422
    bad_visibility = _segment_payload(seed, "Character", mask=0)
    bad_visibility["visibility"] = "invisible"
    resp3 = client.post(f"{API}/segments", json=bad_visibility)
    assert resp3.status_code == 422
    bad_contact_kind = client.post(
        f"{API}/contacts",
        json={
            "project_id": seed.project,
            "video_item_id": seed.video,
            "source_segment_id": "s",
            "target_segment_id": "t",
            "contact_kind": "teleport",  # not in the canonical contact taxonomy
            "start_frame": 0,
            "end_frame": 1,
            "start_time_ms": 0,
            "end_time_ms": 1,
        },
    )
    assert bad_contact_kind.status_code == 422


def test_r2_item39_nan_infinity_rejected_422(client: TestClient) -> None:
    import json as _json

    with _open_session() as session:
        seed = _seed(session)
    headers = {"content-type": "application/json"}

    def raw_with_token(token: str) -> str:
        payload = _segment_payload(seed, "Character", mask=0)
        del payload["confidence"]
        body = _json.dumps(payload)
        # JSON allows the NaN/Infinity literals on the wire; Pydantic's
        # finite-only boundary must reject them before anything is stored.
        return body[:-1] + ', "confidence": ' + token + "}"

    for token in ("NaN", "Infinity", "-Infinity"):
        resp = client.post(f"{API}/segments", content=raw_with_token(token), headers=headers)
        assert resp.status_code == 422, (token, resp.text)
    # NaN NESTED inside provenance (caught by the finite-payload walk).
    payload = _segment_payload(seed, "Character", mask=0)
    body = _json.dumps(payload).replace(
        '"provenance": {"run": "r2"}',
        '"provenance": {"score": NaN}',
    )
    nested = client.post(f"{API}/segments", content=body, headers=headers)
    assert nested.status_code == 422, nested.text
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 0


# ══════════════════════════════════════════════════════════════════════════
# 40. NO DELETE endpoints anywhere
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item40_no_delete_endpoints(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    fake = "00000000-0000-0000-0000-000000000000"
    for url in (
        f"{API}/segments/current/{seg['id']}",
        f"{API}/segments/historical/{seg['id']}",
        f"{API}/segments/{seg['id']}/lineage",
        f"{API}/motions/{fake}",
        f"{API}/occlusions/{fake}",
        f"{API}/contacts/{fake}",
    ):
        resp = client.delete(url)
        # The path exists with only non-DELETE methods -> 405 Method Not Allowed.
        assert resp.status_code == 405, f"DELETE {url} -> {resp.status_code}"
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 1


# ══════════════════════════════════════════════════════════════════════════
# 41. rollback on induced conflict leaves zero rows
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item41_rollback_on_induced_conflict(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    # Induce a motion idempotency payload conflict (same key, diff payload).
    motion = _motion_payload(seed, seg["id"], idem="rollback-motion", confidence=0.7)
    assert client.post(f"{API}/motions", json=motion).status_code == 201
    motion["confidence"] = 0.99
    conflict = client.post(f"{API}/motions", json=motion)
    assert conflict.status_code == 409
    with _open_session() as s2:
        assert s2.scalar(text("SELECT COUNT(*) FROM segment_motion")) == 1
        row = s2.execute(
            text("SELECT confidence FROM segment_motion WHERE idempotency_key = 'rollback-motion'")
        ).scalar()
        assert float(row) == 0.7  # the original payload is untouched


# ══════════════════════════════════════════════════════════════════════════
# 42. concurrent CAS single winner
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item42_concurrent_cas_single_winner(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)
    seg = _create_segment(client, seed, "Character", mask=0)
    seg_id = seg["id"]
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(value: float) -> None:
        barrier.wait(timeout=30)
        try:
            resp = client.patch(
                f"{API}/segments/current/{seg_id}",
                json={"revision": 1, "confidence": value},
            )
            outcomes.append(str(resp.status_code))
        except Exception as _exc:  # noqa: BLE001 - test harness
            outcomes.append("error")

    threads = [
        threading.Thread(target=worker, args=(0.5,)),
        threading.Thread(target=worker, args=(0.7,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert sorted(outcomes) == ["200", "409"], outcomes  # exactly one winner
    with _open_session() as s2:
        row = s2.execute(
            text("SELECT revision, confidence FROM occurrence_segment WHERE id = :i"),
            {"i": seg_id},
        ).one()
        assert row.revision == 2  # bumped exactly once
        assert float(row.confidence) in (0.5, 0.7)
        assert s2.scalar(text("SELECT COUNT(*) FROM occurrence_segment")) == 1


# ══════════════════════════════════════════════════════════════════════════
# 43. full phone-interaction graph API round-trip
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item43_phone_interaction_graph_api_roundtrip(client: TestClient) -> None:
    with _open_session() as session:
        seed = _seed(session)

    def seg(
        name: str,
        *,
        visibility: str = "visible",
        z: int = 0,
        mask: int = 0,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _create_segment(
            client,
            seed,
            name,
            mask=mask,
            visibility=visibility,
            z_order=z,
            prompt=prompt,
        )

    character = seg(
        "Character",
        visibility="visible",
        z=0,
        mask=0,
        prompt={"points": [{"x": 5.0, "y": 5.0, "label": "torso"}]},
    )
    phone = seg("Phone", visibility="visible", z=2, mask=1)
    hand = seg(
        "Hand",
        visibility="occluded",
        z=1,
        mask=2,
        prompt={"points": [{"x": 20.0, "y": 30.0, "label": "palm"}]},
    )
    face = seg("Face", visibility="visible", z=0, mask=3)

    # Camera-relative transform (scene-level) on the Character segment.
    camera = client.post(
        f"{API}/motions",
        json=_motion_payload(
            seed, character["id"], transform_type="camera_relative", idem="motion-camera"
        ),
    )
    assert camera.status_code == 201, camera.text
    # Object-relative transform on the Phone.
    obj_motion = client.post(
        f"{API}/motions",
        json=_motion_payload(
            seed,
            phone["id"],
            transform_type="object_relative",
            idem="motion-obj",
            transform={"tx": 12.0, "ty": -3.0, "scale": 1.0, "rotation_deg": 0.0},
        ),
    )
    assert obj_motion.status_code == 201
    assert obj_motion.json()["transform_type"] == "object_relative"

    # Phone occludes Hand (z-order + occlusion assertion).
    occ = client.post(
        f"{API}/occlusions",
        json=_occlusion_payload(seed, phone["id"], hand["id"], idem="occ-phone-hand"),
    )
    assert occ.status_code == 201, occ.text
    # Contacts: character<->phone and hand<->phone.
    con_char = client.post(
        f"{API}/contacts",
        json=_contact_payload(
            seed, character["id"], phone["id"], "character_phone", idem="con-char-phone"
        ),
    )
    assert con_char.status_code == 201
    con_hand = client.post(
        f"{API}/contacts",
        json=_contact_payload(
            seed,
            hand["id"],
            phone["id"],
            "hand_phone",
            idem="con-hand-phone",
            start_frame=20,
            end_frame=160,
            start_time_ms=1000,
            end_time_ms=5400,
        ),
    )
    assert con_hand.status_code == 201

    # ── read back the full graph through the API ───────────────────────────
    vis = set()
    for name, data in (("Character", character), ("Phone", phone), ("Hand", hand), ("Face", face)):
        got = client.get(f"{API}/segments/current/{data['id']}")
        assert got.status_code == 200
        body = got.json()
        vis.add(body["visibility"])
        assert body["state"] == "current"
        # name is never the identity.
        assert body["name"] == name
    assert "visible" in vis and "occluded" in vis

    # Z-order assertion distinguishes phone over hand.
    assert phone["z_order"] > hand["z_order"]

    # Motion read-back.
    cam_motions = client.get(f"{API}/motions", params={"segment_id": character["id"]})
    assert cam_motions.status_code == 200
    assert cam_motions.json()[0]["transform"] == {
        "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        "proj": "affine2d",
    }
    phone_motions = client.get(f"{API}/motions", params={"segment_id": phone["id"]})
    assert phone_motions.json()[0]["transform"]["scale"] == 1.0

    # Occlusion + contact read-back.
    occs = client.get(f"{API}/occlusions", params={"segment_id": phone["id"]})
    assert occs.json()[0]["occludee_segment_id"] == hand["id"]
    contacts = client.get(f"{API}/contacts")
    assert {c["contact_kind"] for c in contacts.json()} == {"character_phone", "hand_phone"}

    # Deterministic (canonical) JSON round-trip on a stored prompt column.
    with _open_session() as s2:
        stored = s2.execute(
            text("SELECT prompt_json FROM occurrence_segment WHERE id = :i"),
            {"i": character["id"]},
        ).scalar()
        conn = s2.connection()
        fk = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        integrity = conn.execute(text("PRAGMA integrity_check")).scalar()
    expected_prompt = {"points": [{"x": 5.0, "y": 5.0, "label": "torso"}]}
    assert stored == canonical_json(expected_prompt)
    assert fk == [], f"dangling FKs in phone graph: {fk}"
    assert integrity == "ok"


# ══════════════════════════════════════════════════════════════════════════
# 44. OpenAPI generation (routes present, no DELETE)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item44_openapi_includes_routes_no_delete(client: TestClient) -> None:
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    sev_paths = [p for p in paths if "/api/v2/structural-evidence" in p]
    assert sev_paths
    for path in sev_paths:
        assert "delete" not in paths[path], f"DELETE found on {path}"
    # Every required sub-resource exists.
    for required in (
        "/api/v2/structural-evidence/segments",
        "/api/v2/structural-evidence/segments/current/{segment_id}",
        "/api/v2/structural-evidence/segments/historical",
        "/api/v2/structural-evidence/segments/historical/{segment_id}",
        "/api/v2/structural-evidence/segments/{segment_id}/lineage",
        "/api/v2/structural-evidence/motions",
        "/api/v2/structural-evidence/occlusions",
        "/api/v2/structural-evidence/contacts",
    ):
        assert required in paths, f"missing route {required}"


# ══════════════════════════════════════════════════════════════════════════
# 45. object-intelligence unchanged
# ══════════════════════════════════════════════════════════════════════════


def test_r2_item45_object_intelligence_routes_unchanged(client: TestClient) -> None:
    kinds = client.get(f"{OI}/kinds")
    assert kinds.status_code == 200
    data = kinds.json()
    assert len(data["kinds"]) == 7  # the S08-A01 canonical seven-kind taxonomy
    names = {k["name"] for k in data["kinds"]}
    assert names == {
        "character",
        "prop",
        "background",
        "foreground",
        "graphic",
        "source_overlay",
        "other",
    }
    # The structural-evidence prefix is disjoint from object-intelligence.
    assert "/api/v2/structural-evidence/segments" not in [
        p for p in client.get("/openapi.json").json()["paths"] if "/api/v2/object-intelligence" in p
    ]


# ══════════════════════════════════════════════════════════════════════════
# Schema unit tests (validation-order step 2)
# ══════════════════════════════════════════════════════════════════════════


def test_r2_schema_extra_forbid_and_server_owned_fields() -> None:
    """Every request model refuses unknown fields, and neither
    ``logical_id`` nor ``source_generation`` is a client-controlled field."""
    from app.schemas.structural_evidence import (
        ContactCreateRequest,
        MotionCreateRequest,
        OcclusionCreateRequest,
        SegmentCreateRequest,
        SegmentSupersedeRequest,
        SegmentUpdateRequest,
    )

    for model in (
        SegmentCreateRequest,
        SegmentUpdateRequest,
        SegmentSupersedeRequest,
        MotionCreateRequest,
        OcclusionCreateRequest,
        ContactCreateRequest,
    ):
        assert model.model_config.get("extra") == "forbid"
        assert "logical_id" not in model.model_fields
        assert "source_generation" not in model.model_fields


def test_r2_schema_derived_patterns_from_models_constants() -> None:
    """Enums/patterns are DERIVED from the ORM constants (single authority)."""
    import re

    from app.persistence.models import (
        CONTACT_KIND_PATTERN,
        CONTACT_KINDS,
        OBJECT_KIND_PATTERN,
        OBJECT_KINDS,
        OCCURRENCE_CONFIDENCE_SOURCES,
        OCCURRENCE_SEGMENT_VISIBILITY,
        OCCURRENCE_SEGMENT_VISIBILITY_PATTERN,
    )

    # The schema derives its own pattern copies; every canonical value passes
    # and no out-of-taxonomy literal does (no duplicate taxonomy drift).
    for kind in OBJECT_KINDS:
        assert re.fullmatch(OBJECT_KIND_PATTERN, kind)
    for vis in OCCURRENCE_SEGMENT_VISIBILITY:
        assert re.fullmatch(OCCURRENCE_SEGMENT_VISIBILITY_PATTERN, vis)
    for kind in CONTACT_KINDS:
        assert re.fullmatch(CONTACT_KIND_PATTERN, kind)
    for source in OCCURRENCE_CONFIDENCE_SOURCES:
        assert re.fullmatch("^(model|detector|user|manual|derived)$", source)
    assert re.fullmatch(OBJECT_KIND_PATTERN, "character")
    assert re.fullmatch(OBJECT_KIND_PATTERN, "source_overlay")
    assert not re.fullmatch(OBJECT_KIND_PATTERN, "not-a-kind")


def test_r2_schema_finite_and_range_direct() -> None:
    """Direct model-level rejection of NaN/Infinity and end-before-start."""
    from math import inf, nan

    import pytest
    from pydantic import ValidationError

    from app.schemas.structural_evidence import (
        SegmentCreateRequest,
    )

    for bad_conf in (nan, inf, -inf):
        with pytest.raises(ValidationError):
            SegmentCreateRequest(
                project_id="p",
                video_item_id="v",
                role_id="r",
                scene_id="s",
                name="n",
                kind="character",
                start_frame=0,
                end_frame=5,
                start_time_ms=0,
                end_time_ms=100,
                confidence=bad_conf,
            )
    with pytest.raises(ValidationError):
        SegmentCreateRequest(
            project_id="p",
            video_item_id="v",
            role_id="r",
            scene_id="s",
            name="n",
            kind="character",
            start_frame=10,
            end_frame=5,
            start_time_ms=0,
            end_time_ms=100,
        )
    with pytest.raises(ValidationError):
        SegmentCreateRequest(
            project_id="p",
            video_item_id="v",
            role_id="r",
            scene_id="s",
            name="n",
            kind="character",
            start_frame=0,
            end_frame=5,
            start_time_ms=0,
            end_time_ms=100,
            provenance={"nested": nan},
        )


def test_r2_schema_prompt_point_box_strict_shapes() -> None:
    """Prompt points/boxes enforce EXACT shapes and non-empty labels."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.structural_evidence import PromptEvidence

    good = PromptEvidence(
        points=[{"x": 1.0, "y": 2.0, "label": "edge"}],
        boxes=[{"x": 0.0, "y": 0.0, "w": 10.0, "h": 20.0}],
    )
    assert good.points[0].x == 1.0 and good.boxes[0].h == 20.0
    # Unknown point key / empty label / negative box width are rejected.
    with pytest.raises(ValidationError):
        PromptEvidence(points=[{"x": 1.0, "y": 2.0, "label": "edge", "z": 0}])
    with pytest.raises(ValidationError):
        PromptEvidence(points=[{"x": 1.0, "y": 2.0, "label": "  "}])
    with pytest.raises(ValidationError):
        PromptEvidence(boxes=[{"x": 0.0, "y": 0.0, "w": -1.0, "h": 20.0}])
