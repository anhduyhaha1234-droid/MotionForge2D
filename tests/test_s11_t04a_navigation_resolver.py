"""S11-T04A (W9) — canonical navigation RESOLVER unit tests.

The resolver (``app.services.qc_navigation``) maps every QCItem location
kind to a navigation target whose endpoint EXISTS in the real FastAPI app,
without EVER inferring location from free text (constraint MASTER_PLAN
§10 / lane-c REVIEW_QUEUE_CONTRACT §2):

- ``frame``       → serve_frame         ``GET /api/projects/{project_id}/frames/{frame_index}``
- ``object``      → gallery route       ``GET /api/projects/{project_id}/objects/{object_id}/gallery``
- ``audio``       → job info            ``GET /api/jobs/{job_id}`` (ATTACH_ORIGINAL_AUDIO context)
- ``scene``       → scenes endpoint     ``GET /api/projects/{project_id}/scenes/{scene_id}/objects``
- ``segment``     → structural-evidence ``GET /api/v2/structural-evidence/segments/current/{segment_id}``
- ``render``      → project page        ``GET /api/projects/{project_id}``
- ``route``       → segment owning the renderer route (structural_lock contract
                   ``RENDERER_ROUTES``) — a value outside the contract explains
                   fail-closed instead of guessing
- ``video_item``  → project page        (video-level issue, repository default)

Canonical location (scene_id / frame_index / timecode_ms / object_role_id /
segment_row_id / segment_logical_id) is extracted ONLY from structured
fields — typed evidence keys and the frozen QCItem fields — never from
free text.  Missing structured anchor ⇒ ``action.kind="explain"`` (Decision
E: issue ngoài phạm vi rerun V1 — blocker + explanation, no dead link).
Unknown kind ⇒ ``NavigationResolutionError`` (router answers 500 fail-closed,
never a guess).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text as _text

from app.persistence.qc_items import QCItemRecord, QCItemRepository
from app.schemas.qc_items import QCItemData
from app.services.qc_navigation import (
    LOCATION_KINDS,
    NavigationResolutionError,
    canonical_location,
    resolve_navigation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

P1 = str(uuid.uuid4())
V1 = str(uuid.uuid4())
WS = "default"


def _seed_ws_project_video(session: Any) -> None:
    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS}
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT04A','','active')"
        ),
        {"p": P1, "w": WS},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidT04A',0,'imported')"
        ),
        {"v": V1, "p": P1},
    )
    session.commit()


def _create_item(
    session: Any,
    *,
    layer_ref_type: str,
    layer_ref_id: str,
    ewk: str,
    evidence: dict[str, Any],
    reason_code: str = "edge_halo",
    category: str = "edge_halo",
) -> QCItemRecord:
    repo = QCItemRepository(session)
    record = repo.create(
        workspace_id=WS,
        project_id=P1,
        video_item_id=V1,
        layer_ref_type=layer_ref_type,
        layer_ref_id=layer_ref_id,
        reason_code=reason_code,
        evidence_window_key=ewk,
        evidence=evidence,
        severity="warning",
        category=category,
        detector="qc-t04a-resolver",
        detector_revision="1.0.0",
        confidence=0.9,
        confidence_source="model",
        checkpoint_ref="ckpt-t04a",
    )
    session.commit()
    return record


def _dto(record: QCItemRecord) -> QCItemData:
    return QCItemData.from_record(record)


def _registered_templates() -> set[str]:
    """Every path template actually registered in the real app.  Uses
    the generated OpenAPI surface (all included routers, incl. nested
    `_IncludedRouter` wrappers) as the endpoint-existence authority."""
    from app.api.app import app

    return set(app.openapi().get("paths", {}).keys())


@pytest.fixture()
def qc_session(_patch_project_root: Path):
    """A session bound to the SAME temp DB the client fixture serves."""
    from app.api import deps

    factory = deps.get_job_service().session_factory
    assert factory is not None
    session = factory()
    _seed_ws_project_video(session)
    try:
        yield session
    finally:
        session.close()


# ── canonical kind set ──────────────────────────────────────────────────────


def test_canonical_location_kind_set() -> None:
    assert LOCATION_KINDS == (
        "frame",
        "object",
        "audio",
        "scene",
        "segment",
        "render",
        "route",
    )


# ── one target per kind — endpoint EXISTS in the real app ───────────────────


@pytest.mark.parametrize(
    ("kind", "layer_ref_id", "evidence", "expected_template"),
    [
        (
            "frame",
            "frame-ref-42",
            {"schema_version": 1, "frame_index": 42, "scene_id": 0},
            "/api/projects/{project_id}/frames/{frame_index}",
        ),
        (
            "object",
            "obj-1",
            {"schema_version": 1, "object_role_id": "role-1", "object_id": "obj-1"},
            "/api/projects/{project_id}/objects/{object_id}/gallery",
        ),
        (
            "audio",
            "job-audio-1",
            {"schema_version": 1, "job_id": "job-audio-1", "timecode_ms": 1500},
            "/api/jobs/{job_id}",
        ),
        (
            "scene",
            "scene-ref-1",
            {"schema_version": 1, "scene_id": 1},
            "/api/projects/{project_id}/scenes/{scene_id}/objects",
        ),
        (
            "segment",
            "seg-1",
            {"schema_version": 1, "segment_id": "seg-1"},
            "/api/v2/structural-evidence/segments/current/{segment_id}",
        ),
        (
            "render",
            "render-ref",
            {"schema_version": 1, "renderer_route": "sprite_affine"},
            "/api/projects/{project_id}",
        ),
        (
            "route",
            "seg-route-9",
            {"schema_version": 1, "segment_id": "seg-route-9", "renderer_route": "mesh_warp"},
            "/api/v2/structural-evidence/segments/current/{segment_id}",
        ),
        (
            "video_item",
            "video_item",
            {"schema_version": 1, "timecode_ms": 0},
            "/api/projects/{project_id}",
        ),
    ],
)
def test_every_location_kind_target_registered(
    qc_session: Any,
    kind: str,
    layer_ref_id: str,
    evidence: dict[str, Any],
    expected_template: str,
) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type=kind,
        layer_ref_id=layer_ref_id,
        ewk=f"ewk-{kind}",
        evidence=evidence,
    )
    item = _dto(record)
    resolved = resolve_navigation(item)

    assert resolved.action.kind == "navigate", f"{kind}: {resolved.action}"
    assert resolved.action.method == "GET"
    assert resolved.action.target is not None, f"{kind}: target must not be None"
    assert resolved.action.endpoint == expected_template, f"{kind}"
    # Endpoint template must be a REAL registered route in the app.
    assert expected_template in _registered_templates(), (
        f"{kind}: endpoint template {expected_template!r} not registered"
    )
    # Canonical location is always present in the resolution.
    loc = resolved.canonical_location
    for field in ("scene_id", "frame_index", "timecode_ms", "object_role_id"):
        assert hasattr(loc, field)


# ── canonical location: structured ONLY, no free-text inference ─────────────


def test_canonical_location_from_structured_evidence_only(qc_session: Any) -> None:
    evidence = {
        "schema_version": 1,
        "frame_index": 42,
        "scene_id": 0,
        "timecode_ms": 1500,
        "object_role_id": "role-9",
        "free_text": "frame 42 of scene 0 with role-9 at 00:01.500",
    }
    record = _create_item(
        qc_session,
        layer_ref_type="object",
        layer_ref_id="obj-1",
        ewk="ewk-canonical",
        evidence=evidence,
    )
    loc = canonical_location(_dto(record))
    assert loc.scene_id == 0
    assert loc.frame_index == 42
    assert loc.timecode_ms == 1500
    assert loc.object_role_id == "role-9"


def test_canonical_location_never_parsed_from_free_text(qc_session: Any) -> None:
    # The SAME values appear only as free text — structured keys absent ⇒
    # anchors are None (MASTER_PLAN §10: no inference from free text).
    evidence = {
        "schema_version": 1,
        "description": "at frame 42 in scene 0, object role-9, timecode 1500ms",
    }
    record = _create_item(
        qc_session,
        layer_ref_type="frame",
        layer_ref_id="ref",
        ewk="ewk-freetext",
        evidence=evidence,
    )
    loc = canonical_location(_dto(record))
    assert loc.scene_id is None
    assert loc.frame_index is None
    assert loc.timecode_ms is None
    assert loc.object_role_id is None


def test_canonical_location_typed_fail_closed(qc_session: Any) -> None:
    # Wrong-typed structured values are NOT coerced/guessed — they are
    # treated as absent (frame_index must be a real int, not string/float).
    record = _create_item(
        qc_session,
        layer_ref_type="frame",
        layer_ref_id="ref",
        ewk="ewk-type",
        evidence={"schema_version": 1, "frame_index": "42", "scene_id": 0.5},
    )
    loc = canonical_location(_dto(record))
    assert loc.frame_index is None
    assert loc.scene_id is None


# ── explain-action (Decision E — issue ngoài phạm vi, không đích chết) ──────


@pytest.mark.parametrize(
    ("kind", "layer_ref_id", "evidence", "expected_code"),
    [
        # frame missing the structured frame anchor
        ("frame", "ref", {"schema_version": 1, "scene_id": 0}, "missing_frame_anchor"),
        # object without role AND without object anchor
("object", V1, {"schema_version": 1}, "missing_object_anchor"),
        # audio without attach job id
        ("audio", "ref", {"schema_version": 1}, "missing_job_id"),
        # segment without any segment id
("segment", V1, {"schema_version": 1}, "missing_segment_id"),
        # route without the segment id owning the renderer route
("route", V1, {"schema_version": 1, "renderer_route": "pose_swap"}, "missing_segment_id"),
    ],
)
def test_explain_action_when_anchor_missing(
    qc_session: Any,
    kind: str,
    layer_ref_id: str,
    evidence: dict[str, Any],
    expected_code: str,
) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type=kind,
        layer_ref_id=layer_ref_id,
        ewk=f"ewk-explain-{kind}",
        evidence=evidence,
    )
    resolved = resolve_navigation(_dto(record))

    # Decision E: blocker is still presented with an EXPLAIN action — the
    # response never dies (no target at all = no dead link), never crashes.
    assert resolved.action.kind == "explain"
    assert resolved.action.target is None, "explain action must not carry a dead link"
    assert resolved.action.reason, "explain action must carry a reason"
    assert resolved.action.code == expected_code
    # Canonical location is still present in the response.
    assert hasattr(resolved.canonical_location, "frame_index")


def test_route_kind_renderer_route_outside_contract_explains(qc_session: Any) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type="route",
        layer_ref_id="seg-1",
        ewk="ewk-route-bad",
        evidence={"schema_version": 1, "segment_id": "seg-1", "renderer_route": "warp_everything"},
    )
    resolved = resolve_navigation(_dto(record))
    assert resolved.action.kind == "explain"
    assert resolved.action.code == "renderer_route_outside_contract"
    assert resolved.action.target is None


def test_route_kind_valid_route_carried_as_contract_value(qc_session: Any) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type="route",
        layer_ref_id="seg-1",
        ewk="ewk-route-ok",
        evidence={"schema_version": 1, "segment_id": "seg-1", "renderer_route": "part_rig"},
    )
    resolved = resolve_navigation(_dto(record))
    assert resolved.action.kind == "navigate"
    assert resolved.renderer_route == "part_rig"


# ── fail-closed: unknown kind → 500 stable error, never a guess ─────────────


def test_unknown_kind_fail_closed(qc_session: Any) -> None:
    record = _create_item(
        qc_session,
        layer_ref_type="mystery_kind",
        layer_ref_id="ref",
        ewk="ewk-unknown",
        evidence={"schema_version": 1},
    )
    with pytest.raises(NavigationResolutionError) as exc_info:
        resolve_navigation(_dto(record))
    assert exc_info.value.code == "unknown_kind"


def test_segment_ids_anchor_from_item_fields(qc_session: Any) -> None:
    # segment_row_id / segment_logical_id (structured QCItem fields) anchor
    # segment navigation when the frozen DTO carries them (no evidence key
    # needed) — the durable join key, never a free-text parse.
    from datetime import datetime, timezone

    from app.persistence.qc_items import QCItemRecord as _Rec

    record = _Rec(
        id=str(uuid.uuid4()),
        workspace_id=WS,
        project_id=P1,
        video_item_id=V1,
        segment_row_id="seg-row-77",
        segment_logical_id="seg-logical-77",
        layer_ref_type="segment",
        layer_ref_id=V1,
        reason_code="contact_break",
        evidence_window_key="ewk-seg-fields",
        evidence={"schema_version": 1},
        status="open",
        severity="warning",
        category="contact_break",
        detector="qc-t04a-resolver",
        detector_revision="1.0.0",
        confidence=0.9,
        confidence_source="derived",
        checkpoint_ref="ckpt-t04a",
        revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    item = _dto(record)
    assert item.segment_row_id == "seg-row-77"

    resolved = resolve_navigation(item)
    assert resolved.action.kind == "navigate"
    assert resolved.action.target == "/api/v2/structural-evidence/segments/current/seg-row-77"
    loc = resolved.canonical_location
    assert loc.segment_row_id == "seg-row-77"
    assert loc.segment_logical_id == "seg-logical-77"