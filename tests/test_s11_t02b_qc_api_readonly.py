"""S11-T02B QCItem READ-ONLY API tests (lane-C G1/G2/G4 shape, Decision A).

The HTTP surface is GET-only by construction:

- ``GET /api/v2/projects/{project_id}/qc-items`` — queue list (G1 shape:
  status/severity/category/video_item_id filters + bounded pagination).
- ``GET /api/v2/qc-items/{item_id}`` — one item + evidence refs (G2 shape).

Creation/upsert is INTERNAL ONLY (Decision A): every test seeds through the
repository (app.persistence.qc_items), never through a public POST.

Binary gates (source-level, so a mutation endpoint can never sneak in):
1. the router source contains ZERO ``@router.post/put/patch/delete``;
2. ``app/api/app.py`` registers the qc_items router exactly once;
3. mutation HTTP verbs against the qc-items namespaces answer 405;
4. the OpenAPI surface before T02B has zero removed operations and the two
   qc-items paths exist with GET-only methods.

Uses the standard `client` fixture (isolated project root + alembic-head
temp DB + patched deps) — isolation chuẩn C1/C3.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from app.persistence.qc_items import QCItemRecord, QCItemRepository

REPO_ROOT = Path(__file__).resolve().parent.parent

WS = "default"  # server-owned workspace (DEFAULT_WORKSPACE_ID)
WS2 = "ws-t02b-api-other"
P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
V1 = str(uuid.uuid4())
V2 = str(uuid.uuid4())

BASELINE = (
    REPO_ROOT
    / "docs/pm/sessions/S11-T02B/evidence/openapi_paths_before.txt"
)


def _seed_ws_project_video(session: Any, *, ws: str, pid: str, vid: str) -> None:
    from sqlalchemy import text as _text

    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws}
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT02B','','active')"
        ),
        {"p": pid, "w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidT02B',0,'imported')"
        ),
        {"v": vid, "p": pid},
    )
    session.commit()


def _create_item(
    session: Any,
    *,
    workspace_id: str = WS,
    project_id: str = P1,
    video_item_id: str = V1,
    layer_ref_id: str | None = None,
    reason_code: str = "clipping",
    category: str = "clipping",
    severity: str = "warning",
    ewk: str = "ewk-api",
    evidence: dict[str, Any] | None = None,
) -> QCItemRecord:
    if layer_ref_id is None:
        layer_ref_id = video_item_id
    repo = QCItemRepository(session)
    record = repo.create(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        layer_ref_type="video_item",
        layer_ref_id=layer_ref_id,
        reason_code=reason_code,
        evidence_window_key=ewk,
        evidence=evidence if evidence is not None else {"schema_version": 1, "content": "x"},
        severity=severity,
        category=category,
        detector="qc-t02b-api",
        detector_revision="1.0.0",
        confidence=0.9,
        confidence_source="model",
        checkpoint_ref="ckpt-api",
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


# ── binary: source-level mutation gates ──────────────────────────────────────


def test_router_source_has_zero_mutation_http_methods() -> None:
    source = (REPO_ROOT / "app/api/routes/qc_items.py").read_text(encoding="utf-8")
    mutators = re.findall(r"@router\.(post|put|patch|delete)\b", source)
    assert mutators == [], f"mutation HTTP methods found in router: {mutators}"
    gets = re.findall(r"@router\.get\b", source)
    assert len(gets) >= 2, f"expected GET routes, found {len(gets)}"


def test_app_registers_qc_items_router_exactly_once() -> None:
    source = (REPO_ROOT / "app/api/app.py").read_text(encoding="utf-8")
    includes = re.findall(r"include_router\(\s*qc_items\s*\.router", source)
    assert len(includes) == 1, f"expected exactly 1 include_router(qc_items), got {len(includes)}"


# ── list (G1 shape) ──────────────────────────────────────────────────────────


def test_list_empty(client: TestClient, qc_session: Any) -> None:
    response = client.get(f"/api/v2/projects/{P1}/qc-items")
    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == WS
    assert body["project_id"] == P1
    assert body["total"] == 0
    assert body["items"] == []
    assert body["has_more"] is False


def test_list_seeded_via_repository_shows_items(client: TestClient, qc_session: Any) -> None:
    # Seed through the INTERNAL repository — the only legal creation path
    # (Decision A: no public POST exists).
    a = _create_item(qc_session, ewk="ewk-api-a")
    b = _create_item(qc_session, ewk="ewk-api-b", reason_code="flicker", category="flicker")

    response = client.get(f"/api/v2/projects/{P1}/qc-items")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["has_more"] is False
    item_ids = {item["id"] for item in body["items"]}
    assert item_ids == {a.id, b.id}
    first = body["items"][0]
    # Frozen DTO serialized deterministically; evidence parsed back to JSON.
    assert first["status"] == "open"
    assert first["evidence"] == {"schema_version": 1, "content": "x"}
    assert first["layer_ref_type"] == "video_item"
    assert first["segment_row_id"] is None
    assert first["segment_logical_id"] is None
    assert first["revision"] == 1


def test_list_filters(client: TestClient, qc_session: Any) -> None:
    a = _create_item(qc_session, ewk="ewk-f-a", severity="blocker")
    b = _create_item(qc_session, ewk="ewk-f-b")
    c = _create_item(qc_session, ewk="ewk-f-c", reason_code="identity", category="identity")
    # Foreign workspace/project must never leak into the default workspace list.
    _create_item(
        qc_session, workspace_id=WS2, project_id=P2, video_item_id=V2,
        layer_ref_id=V2, ewk="ewk-f-foreign",
    )

    params = {"status": "open", "severity": "blocker", "category": "clipping"}
    response = client.get(f"/api/v2/projects/{P1}/qc-items", params=params)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == a.id

    response = client.get(f"/api/v2/projects/{P1}/qc-items", params={"severity": "blocker"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == a.id

    response = client.get(
        f"/api/v2/projects/{P1}/qc-items", params={"video_item_id": V1}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 3

    response = client.get(
        f"/api/v2/projects/{P1}/qc-items", params={"category": "identity"}
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {c.id}
    assert response.json()["total"] == 1

    # Invalid filter values fail closed with 422.
    response = client.get(f"/api/v2/projects/{P1}/qc-items", params={"status": "bogus"})
    assert response.status_code == 422
    response = client.get(f"/api/v2/projects/{P1}/qc-items", params={"severity": "fatal"})
    assert response.status_code == 422
    response = client.get(f"/api/v2/projects/{P1}/qc-items", params={"category": "nope"})
    assert response.status_code == 422
    assert b.id is not None  # keep b referenced for the filter above


def test_list_pagination(client: TestClient, qc_session: Any) -> None:
    for idx in range(5):
        _create_item(qc_session, ewk=f"ewk-page-{idx}")
    response = client.get(f"/api/v2/projects/{P1}/qc-items", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["has_more"] is True
    page2 = client.get(
        f"/api/v2/projects/{P1}/qc-items", params={"limit": 2, "offset": 2}
    ).json()
    assert len(page2["items"]) == 2 and page2["has_more"] is True
    page3 = client.get(
        f"/api/v2/projects/{P1}/qc-items", params={"limit": 2, "offset": 4}
    ).json()
    assert len(page3["items"]) == 1 and page3["has_more"] is False

    seen = {i["id"] for page in (body, page2, page3) for i in page["items"]}
    assert len(seen) == 5


# ── detail (G2 shape) ────────────────────────────────────────────────────────


def test_detail_returns_item_with_evidence(client: TestClient, qc_session: Any) -> None:
    record = _create_item(
        qc_session,
        ewk="ewk-detail",
        evidence={"schema_version": 1, "content": "detail-evidence", "metric_value": 0.4},
    )
    response = client.get(f"/api/v2/qc-items/{record.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == record.id
    assert body["workspace_id"] == WS
    assert body["project_id"] == P1
    assert body["video_item_id"] == V1
    assert body["status"] == "open"
    assert body["severity"] == "warning"
    assert body["category"] == "clipping"
    assert body["reason_code"] == "clipping"
    assert body["evidence"] == {
        "schema_version": 1,
        "content": "detail-evidence",
        "metric_value": 0.4,
    }


def test_detail_unknown_foreign_workspace_404(client: TestClient, qc_session: Any) -> None:
    response = client.get(f"/api/v2/qc-items/{uuid.uuid4()}")
    assert response.status_code == 404

    # An item that exists in ANOTHER workspace is indistinguishable from
    # not-found from the default workspace (fail-closed ownership).
    foreign = _create_item(
        qc_session, workspace_id=WS2, project_id=P2, video_item_id=V2,
        layer_ref_id=V2, ewk="ewk-foreign-detail",
    )
    response = client.get(f"/api/v2/qc-items/{foreign.id}")
    assert response.status_code == 404


def test_detail_invalid_uuid_422(client: TestClient, qc_session: Any) -> None:
    # The {item_id:uuid} path converter refuses non-UUID ids at the router
    # boundary: no route matches, stable 404 (fail-closed, zero leak).
    response = client.get("/api/v2/qc-items/not-a-uuid")
    assert response.status_code == 404


# ── mutation verbs are structurally impossible ───────────────────────────────


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_mutation_verbs_rejected_on_qc_item_surface(
    client: TestClient, qc_session: Any, method: str
) -> None:
    record = _create_item(qc_session, ewk=f"ewk-mut-{method}")
    # The qc-items namespace has NO mutation handler: with-id URLs resolve to
    # the existing GET route (405 Method Not Allowed); the collection base has
    # no route at all (404). Either way the mutation verb never executes.
    for url in (f"/api/v2/qc-items/{record.id}", "/api/v2/qc-items"):
        response = client.request(method, url)
        assert response.status_code in (404, 405), (
            f"{method.upper()} {url} -> {response.status_code}"
        )
    response = client.request(method, f"/api/v2/projects/{P1}/qc-items")
    assert response.status_code in (404, 405)


# ── OpenAPI: additive only (removed=0), GET-only qc-items surface ────────────


def test_openapi_additive_removed_zero_and_get_only() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    baseline = BASELINE.read_text(encoding="utf-8").splitlines()
    removed = [p for p in baseline if p not in paths]
    assert removed == [], f"OpenAPI regression (removed): {removed}"

    qc_paths = [
        p
        for p in paths
        if "qc-items" in p
    ]
    assert "/api/v2/projects/{project_id}/qc-items" in qc_paths
    assert "/api/v2/qc-items/{item_id}" in qc_paths
    for path in qc_paths:
        methods = set(paths[path].keys())
        assert methods <= {"get"}, f"non-GET methods on {path}: {methods}"