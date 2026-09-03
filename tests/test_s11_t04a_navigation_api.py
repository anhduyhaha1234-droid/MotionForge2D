"""S11-T04A (W9) — canonical navigation API tests (HTTP surface).

``GET /api/v2/qc-navigation/{item_id}`` is the READ-ONLY navigation router
(schema ``app/schemas/qc_navigation.py`` — FREEZE C2-F1; the QC-item schema
itself stays T02B-owned and is only imported here).

Binary gates verified with REAL calls on the temp app/db:

1. For every location kind seeded in the fixtures, GET navigation answers
   200 with a target whose endpoint EXISTS — the target path template is a
   registered route AND a real HTTP call to that target dispatches (JSON
   body, never the Starlette plain-text 404 of an unregistered path).
2. An issue without a structured role/frame anchor still answers 200 with
   ``action.kind="explain"`` (Decision E — blocker + explanation, no dead
   link, no crash).
3. Missing canonical-location mapping (unknown kind) answers a stable
   500 fail-closed error — never a guessed target.
4. The router is GET-only by construction: zero mutation method decorators
   in the router source and exactly one ``include_router(qc_navigation)``
   line in app.py.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as _text

from app.persistence.qc_items import QCItemRecord, QCItemRepository

REPO_ROOT = Path(__file__).resolve().parent.parent

WS = "default"
WS2 = "ws-t04a-other"
P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
V1 = str(uuid.uuid4())
V2 = str(uuid.uuid4())

#: Every location kind exercised by the fixtures, with the structured
#: evidence that makes each one navigable.
KIND_FIXTURES: dict[str, dict[str, Any]] = {
    "frame": {
        "layer_ref_id": "frame-ref-42",
        "evidence": {"schema_version": 1, "frame_index": 42, "scene_id": 0},
    },
    "object": {
        "layer_ref_id": "obj-1",
        "evidence": {"schema_version": 1, "object_role_id": "role-1", "object_id": "obj-1"},
    },
    "audio": {
        "layer_ref_id": "job-audio-1",
        "evidence": {"schema_version": 1, "job_id": "job-audio-1", "timecode_ms": 1500},
    },
    "scene": {
        "layer_ref_id": "scene-ref-1",
        "evidence": {"schema_version": 1, "scene_id": 1},
    },
    "segment": {
        "layer_ref_id": "seg-1",
        "evidence": {"schema_version": 1, "segment_id": "seg-1"},
    },
    "render": {
        "layer_ref_id": "render-ref",
        "evidence": {"schema_version": 1, "renderer_route": "sprite_affine"},
    },
    "route": {
        "layer_ref_id": "seg-route-9",
        "evidence": {"schema_version": 1, "segment_id": "seg-route-9", "renderer_route": "mesh_warp"},
    },
    "video_item": {
        "layer_ref_id": "video_item",
        "evidence": {"schema_version": 1, "timecode_ms": 0},
    },
}

#: Expected registered path template per kind (endpoint EXISTS check).
KIND_TEMPLATES: dict[str, str] = {
    "frame": "/api/projects/{project_id}/frames/{frame_index}",
    "object": "/api/projects/{project_id}/objects/{object_id}/gallery",
    "audio": "/api/jobs/{job_id}",
    "scene": "/api/projects/{project_id}/scenes/{scene_id}/objects",
    "segment": "/api/v2/structural-evidence/segments/current/{segment_id}",
    "render": "/api/projects/{project_id}",
    "route": "/api/v2/structural-evidence/segments/current/{segment_id}",
    "video_item": "/api/projects/{project_id}",
}


def _seed_ws_project_video(session: Any, *, ws: str, pid: str, vid: str) -> None:
    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT04A','','active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": pid, "w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidT04A',0,'imported')"
        ),
        {"v": vid, "p": pid},
    )
    session.commit()


def _create_item(
    session: Any,
    *,
    layer_ref_type: str,
    layer_ref_id: str,
    ewk: str,
    evidence: dict[str, Any],
    workspace_id: str = WS,
    project_id: str = P1,
    video_item_id: str = V1,
) -> QCItemRecord:
    repo = QCItemRepository(session)
    record = repo.create(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        layer_ref_type=layer_ref_type,
        layer_ref_id=layer_ref_id,
        reason_code="edge_halo",
        evidence_window_key=ewk,
        evidence=evidence,
        severity="warning",
        category="edge_halo",
        detector="qc-t04a-api",
        detector_revision="1.0.0",
        confidence=0.9,
        confidence_source="model",
        checkpoint_ref="ckpt-t04a",
    )
    session.commit()
    return record


@pytest.fixture()
def qc_session():
    """A session bound to the SAME temp DB the client fixture serves."""
    from app.api import deps

    factory = deps.get_job_service().session_factory
    assert factory is not None
    session = factory()
    _seed_ws_project_video(session, ws=WS, pid=P1, vid=V1)
    _seed_ws_project_video(session, ws=WS2, pid=P2, vid=V2)
    try:
        yield session
    finally:
        session.close()


def _call_target(client: TestClient, target: str) -> Any:
    """Real HTTP call to the navigation target on the temp app.

    A dispatchable endpoint answers a JSON error/body (404/400/200).  An
    UNREGISTERED path answers Starlette's plain-text 404 — the signal used
    to prove endpoint existence.
    """
    response = client.get(target)
    assert response.status_code in (200, 400, 404), (
        f"target {target!r} answered {response.status_code}: {response.text[:200]}"
    )
    assert "application/json" in response.headers.get("content-type", ""), (
        f"target {target!r} did not dispatch (plain-text 404 = unregistered path)"
    )
    return response


# ── AC1: every fixture kind → navigation target whose endpoint EXISTS ───────


@pytest.mark.parametrize("kind", list(KIND_FIXTURES))
def test_api_navigation_target_exists_for_every_kind(
    client: TestClient, qc_session: Any, kind: str
) -> None:
    fixture = KIND_FIXTURES[kind]
    record = _create_item(
        qc_session,
        layer_ref_type=kind,
        layer_ref_id=fixture["layer_ref_id"],
        ewk=f"ewk-api-{kind}",
        evidence=fixture["evidence"],
    )

    response = client.get(f"/api/v2/qc-navigation/{record.id}")
    assert response.status_code == 200, response.text
    body = response.json()

    # Canonical location is REQUIRED in every response (AC3).
    loc = body["canonical_location"]
    for field in ("scene_id", "frame_index", "timecode_ms", "object_role_id"):
        assert field in loc, f"canonical_location missing {field!r}: {body}"

    action = body["action"]
    assert action["kind"] == "navigate"
    assert action["method"] == "GET"
    assert action["target"] is not None
    assert action["endpoint"] == KIND_TEMPLATES[kind]

    # Endpoint continues to exist: REAL call on the temp app dispatches.
    _call_target(client, action["target"])


def test_api_frame_target_query_scene_id_dispatches(
    client: TestClient, qc_session: Any
) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type="frame",
        layer_ref_id="frame-ref-42",
        ewk="ewk-api-frame-q",
        evidence={"schema_version": 1, "frame_index": 42, "scene_id": 0},
    )
    body = client.get(f"/api/v2/qc-navigation/{record.id}").json()
    target = body["action"]["target"]
    assert "?scene_id=0" in target
    _call_target(client, target)


# ── AC2: out-of-scope issue → explain action, no dead link, no crash ────────


def test_api_explain_action_when_role_frame_missing(
    client: TestClient, qc_session: Any
) -> None:
    # object kind WITHOUT any structured object role/frame anchor — the
    # Decision E out-of-scope-rerun case.
    record = _create_item(
        qc_session,
        layer_ref_type="object",
        layer_ref_id=V1,
        ewk="ewk-api-explain",
        evidence={"schema_version": 1},
    )
    response = client.get(f"/api/v2/qc-navigation/{record.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    action = body["action"]
    assert action["kind"] == "explain"
    assert action["target"] is None
    assert action["code"] == "missing_object_anchor"
    assert action["reason"]
    # Canonical location is still required even for the explain case.
    assert "canonical_location" in body


# ── AC3: canonical mapping missing → 500 fail-closed stable error ───────────


def test_api_unknown_kind_fail_closed_500(client: TestClient, qc_session: Any) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type="mystery_kind",
        layer_ref_id="ref",
        ewk="ewk-api-unknown",
        evidence={"schema_version": 1},
    )
    response = client.get(f"/api/v2/qc-navigation/{record.id}")
    assert response.status_code == 500, response.text
    assert "application/json" in response.headers.get("content-type", "")
    detail = response.json().get("detail")
    assert isinstance(detail, dict) and detail.get("code") == "unknown_kind", detail
    # No guessed target is ever returned for an unknown kind.
    assert "target" not in str(detail)


def test_api_missing_item_404(client: TestClient, qc_session: Any) -> None:
    response = client.get(f"/api/v2/qc-navigation/{uuid.uuid4()}")
    assert response.status_code == 404
    assert "application/json" in response.headers.get("content-type", "")


def test_api_foreign_workspace_404(client: TestClient, qc_session: Any) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type="segment",
        layer_ref_id="seg-x",
        ewk="ewk-api-foreign",
        evidence={"schema_version": 1, "segment_id": "seg-x"},
        workspace_id=WS2,
        project_id=P2,
        video_item_id=V2,
    )
    response = client.get(f"/api/v2/qc-navigation/{record.id}")
    assert response.status_code == 404  # fail-closed ownership, zero leak


# ── AC4: router GET-only + app.py single include line ───────────────────────


def test_router_source_get_only() -> None:
    source = (REPO_ROOT / "app/api/routes/qc_navigation.py").read_text(encoding="utf-8")
    mutators = re.findall(r"@router\.(post|put|patch|delete)\b", source)
    assert mutators == [], f"mutation HTTP methods found in router: {mutators}"
    gets = re.findall(r"@router\.get\b", source)
    assert len(gets) >= 1, "expected at least one GET route"


def test_app_registers_qc_navigation_router_exactly_once() -> None:
    source = (REPO_ROOT / "app/api/app.py").read_text(encoding="utf-8")
    includes = re.findall(r"include_router\(\s*qc_navigation\s*\.router", source)
    assert len(includes) == 1, f"expected exactly 1 include_router(qc_navigation), got {len(includes)}"


def test_openapi_navigation_path_get_only(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    path = "/api/v2/qc-navigation/{item_id}"
    assert path in spec["paths"], f"{path!r} missing from OpenAPI"
    methods = set(spec["paths"][path].keys())
    assert methods == {"get"}, f"qc-navigation must be GET-only, got {methods}"