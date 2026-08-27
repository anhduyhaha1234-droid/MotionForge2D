"""S09-T05A-C1 adversarial tests — correction validation BEFORE mutation.

Review finding F5: the old schema accepted bogus routes, unbounded
anchors, reversed frames and empty evidence, letting an invalid request
be ARCHIVED as a pending correction before confirm refused it.  These
tests pin the corrected fail-closed behavior at every layer:

- direct Pydantic probes on ``RouteOverrideCorrectionRequest`` /
  ``RouteOverrideProvenance`` (bogus routes, anchor 9.0/-2.0/NaN/Inf,
  reversed frames 20..1, empty evidence, path escape, unknown fields);
- direct repository probes proving ZERO durable side effects when a
  request is rejected (s09_correction row count unchanged);
- HTTP-level probes through the real router mounted on a local FastAPI
  app (invalid submit → 4xx AND DB row count + artifacts unchanged);
- canonical renderer contract enum only ({pose_swap, sprite_affine,
  mesh_warp, part_rig, controlled_redraw}) — stale literals
  (direct_composite/keyed_pipeline) are refused;
- valid requests remain deterministic/idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app.api import deps
from app.api.routes.s09_correction import router as s09_correction_router
from app.persistence import (
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    RENDERER_ROUTES,
    Artifact,
    Job,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import StructuralEvidenceRepository
from app.schemas.s09_correction import (
    RendererRoute,
    RouteOverrideCorrectionRequest,
    RouteOverrideProvenance,
)
from app.services.s09_correction import (
    CorrectionImpact,
    CorrectionValidationError,
    S09CorrectionRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = DEFAULT_WORKSPACE_ID


def _sha(n: int) -> str:
    return f"{n:064x}"


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


# ── 1. canonical route contract ──────────────────────────────────────────


def test_renderer_route_literal_matches_frozen_policy() -> None:
    assert set(get_args(RendererRoute)) == {
        "pose_swap",
        "sprite_affine",
        "mesh_warp",
        "part_rig",
        "controlled_redraw",
    }
    assert set(RENDERER_ROUTES) == set(get_args(RendererRoute))


# ── 2. direct Pydantic adversarial probes ────────────────────────────────


def _override_request(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        occurrence_segment_id="seg-1",
        route_from="pose_swap",
        route_to="sprite_affine",
        anchor_x=0.25,
        anchor_y=0.75,
        start_frame=0,
        end_frame=90,
        override_reason="swap evidence missing for this pose set",
        provenance={
            "route_from": "pose_swap",
            "route_to": "sprite_affine",
            "evidence": "benchmark FAIL row pose_swap",
        },
    )
    base.update(over)
    return base


@pytest.mark.parametrize(
    ("name", "overrides"),
    [
        ("bogus_from", {"route_from": "bogus_from"}),
        ("stale_literal_from", {"route_from": "direct_composite"}),
        ("stale_literal_to", {"route_to": "keyed_pipeline"}),
        ("bogus_to", {"route_to": "teleport"}),
        ("anchor_x_9", {"anchor_x": 9.0}),
        ("anchor_y_-2", {"anchor_y": -2.0}),
        ("anchor_nan", {"anchor_x": float("nan")}),
        ("anchor_inf", {"anchor_y": float("inf")}),
        (
            "reversed_frames",
            {"start_frame": 20, "end_frame": 1},
        ),
        (
            "empty_evidence",
            {
                "provenance": {
                    "route_from": "pose_swap",
                    "route_to": "sprite_affine",
                    "evidence": "   ",
                }
            },
        ),
        (
            "missing_evidence",
            {
                "provenance": {
                    "route_from": "pose_swap",
                    "route_to": "sprite_affine",
                }
            },
        ),
        (
            "provenance_route_mismatch",
            {
                "provenance": {
                    "route_from": "mesh_warp",
                    "route_to": "sprite_affine",
                    "evidence": "x",
                }
            },
        ),
        ("path_escape_segment", {"occurrence_segment_id": "../../etc/passwd"}),
        ("path_escape_manifest", {"structural_lock_manifest_id": "..\\x"}),
        ("negative_start_frame", {"start_frame": -5}),
        ("unknown_field", {"teleport_speed": 9000}),
        ("empty_reason", {"override_reason": "   "}),
        ("confidence_out_of_range", {"confidence": 1.5}),
    ],
)
def test_pydantic_rejects_invalid_route_override(
    name: str, overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        RouteOverrideCorrectionRequest(**_override_request(**overrides))


def test_valid_request_normalizes_and_accepts() -> None:
    req = RouteOverrideCorrectionRequest(
        **_override_request(
            override_reason="  padded reason  ",
            provenance={
                "route_from": "pose_swap",
                "route_to": "sprite_affine",
                "evidence": "  benchmark FAIL row pose_swap  ",
            },
        )
    )
    assert req.override_reason == "padded reason"
    assert req.provenance.evidence == "benchmark FAIL row pose_swap"


def test_provenance_model_alone_rejects_stale_literal() -> None:
    with pytest.raises(ValidationError):
        RouteOverrideProvenance(
            route_from="direct_composite",
            route_to="sprite_affine",
            evidence="x",
        )


def test_mask_payload_deep_non_finite_refused() -> None:
    from app.schemas.s09_correction import MaskCorrectionRequest

    with pytest.raises(ValidationError):
        MaskCorrectionRequest(
            occurrence_segment_id="seg-1",
            revision=1,
            source_generation="3",
            segmentation={"points": [{"x": float("inf"), "y": 2.0}]},
            mask_artifact_id="m-1",
            provenance={"user": "r"},
        )


# ── 3. repository-level zero-side-effect rejection ────────────────────────


class _Env:
    def __init__(self, factory: Any, seed_data: dict[str, Any]) -> None:
        self.factory = factory
        self.seed = seed_data


@pytest.fixture()
def env(tmp_path: Path) -> _Env:  # type: ignore[type-arg]
    db = tmp_path / "c1.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    sha = "1" * 64
    ids: dict[str, Any] = {}
    with factory() as s:
        s.add(Workspace(id=WS, name=WS))
        art = Artifact(
            workspace_id=WS, kind="video", relative_path="src.mp4",
            state="ready", sha256=sha,
        )
        s.add(art)
        s.flush()
        project = Project(workspace_id=WS, name="T05AC1")
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id, title="V", position=0,
            source_artifact_id=art.id,
        )
        s.add(video)
        s.flush()
        job = Job(
            workspace_id=WS, job_type="DISCOVER_OBJECTS",
            owner_type="video_item", owner_id=video.id, state="completed",
            input_generation="3",
            input_manifest_json=json.dumps({"source_sha256": sha}),
        )
        s.add(job)
        s.flush()
        scene = Scene(
            video_item_id=video.id, position=0, start_frame=0, end_frame=180,
            start_time_ms=0, end_time_ms=6000, status="pending",
        )
        s.add(scene)
        s.flush()
        role = ObjectRole(
            workspace_id=WS, project_id=project.id, video_item_id=video.id,
            source_generation="3", name="Character", kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        mask = Artifact(
            workspace_id=WS, kind="image", relative_path="m.png",
            state="ready", sha256=_sha(2),
        )
        s.add(mask)
        s.flush()
        s.commit()
        ids.update(
            project=project.id, video=video.id, scene=scene.id,
            role=role.id, job=job.id, mask2=mask.id,
        )

    with factory() as s:
        repo = StructuralEvidenceRepository(s)
        seg, _created = repo.create_segment(
            WS, ids["project"], ids["video"], ids["role"], ids["scene"],
            "Character", 0, 90, 0, 3000, "3", kind="character",
            source_job_id=ids["job"], mask_artifact_id=ids["mask2"],
            segmentation={"points": [{"x": 10.0, "y": 20.0, "label": "c"}]},
        )
        s.commit()
        ids["segment"] = seg.id

    environment = _Env(factory, ids)
    yield environment  # type: ignore[misc]
    create_engine_for_path(db).dispose()


def _correction_row_count(env: _Env) -> int:
    with env.factory() as s:
        return int(
            s.execute(text("SELECT COUNT(*) FROM s09_correction")).scalar()
        )


def _render_route_count(env: _Env) -> int:
    with env.factory() as s:
        return int(
            s.execute(text("SELECT COUNT(*) FROM segment_render_route")).scalar()
        )


@pytest.mark.parametrize(
    ("name", "mutation"),
    [
        ("bogus_from", {"route_from": "bogus_from"}),
        ("stale_literal", {"route_to": "keyed_pipeline"}),
        ("anchor9", {"anchor_x": 9.0}),
        ("anchor_neg", {"anchor_y": -2.0}),
        ("frames_rev", {"start_frame": 20, "end_frame": 1}),
        (
            "empty_ev",
            {
                "provenance": {
                    "route_from": "pose_swap",
                    "route_to": "sprite_affine",
                    "evidence": "",
                }
            },
        ),
    ],
)
def test_invalid_submit_zero_durable_side_effect(
    env: _Env, name: str, mutation: dict[str, Any]
) -> None:

    request = {
        "occurrence_segment_id": env.seed["segment"],
        "route_from": "pose_swap",
        "route_to": "sprite_affine",
        "anchor_x": 0.25,
        "anchor_y": 0.75,
        "start_frame": 0,
        "end_frame": 90,
        "override_reason": "measured swap capability missing for this pose set",
        "provenance": {
            "route_from": "pose_swap",
            "route_to": "sprite_affine",
            "evidence": "benchmark FAIL row pose_swap",
        },
    }
    request.update(mutation)

    rows_before = _correction_row_count(env)
    routes_before = _render_route_count(env)

    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        # compute_impact path must refuse...
        with pytest.raises(CorrectionValidationError):
            corr.compute_impact(
                WS, env.seed["project"], env.seed["video"],
                "route_override", dict(request),
            )
        # ...and create_correction must ALSO refuse (no pending archive).
        impact = CorrectionImpact(
            correction_kind="route_override",
            affected_occurrence_segment_ids=[env.seed["segment"]],
            affected_contact_ids=[],
            affected_motion_ids=[],
            affected_loop_ids=[],
            affected_layer_ids=["Character"],
            route_override=True,
            counts={"segments": 1},
        )
        with pytest.raises(CorrectionValidationError):
            corr.create_correction(
                WS, env.seed["project"], env.seed["video"],
                "route_override", dict(request), impact,
            )

    assert _correction_row_count(env) == rows_before
    assert _render_route_count(env) == routes_before


def test_valid_submit_then_confirm_still_works_and_is_idempotent(
    env: _Env,
) -> None:

    request = {
        "occurrence_segment_id": env.seed["segment"],
        "route_from": "pose_swap",
        "route_to": "controlled_redraw",
        "anchor_x": 0.25,
        "anchor_y": 0.75,
        "start_frame": 0,
        "end_frame": 90,
        "override_reason": "measured swap capability missing for this pose set",
        "provenance": {
            "route_from": "pose_swap",
            "route_to": "controlled_redraw",
            "reason": "operator override after review",
            "evidence": "benchmark_results_seed20260823.json row FAIL pose_swap",
        },
    }
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"],
            "route_override", dict(request),
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"],
            "route_override", dict(request), impact,
            idempotency_key="c1-idem",
        )
        session.commit()
    assert created is True

    # Replay: same key + same payload → SAME row, no duplicate archive.
    with env.factory() as session:
        corr2 = S09CorrectionRepository(session)
        impact2 = corr2.compute_impact(
            WS, env.seed["project"], env.seed["video"],
            "route_override", dict(request),
        )
        rec2, created2 = corr2.create_correction(
            WS, env.seed["project"], env.seed["video"],
            "route_override", dict(request), impact2,
            idempotency_key="c1-idem",
        )
        session.commit()
    assert created2 is False and rec2.id == rec.id
    assert _correction_row_count(env) == 1

    # Confirm applies the override through a NEW SegmentRenderRoute row.
    with env.factory() as session:
        corr3 = S09CorrectionRepository(session)
        applied, _changed = corr3.confirm_correction(WS, rec.id, 1)
        session.commit()
        assert (applied.result or {})["route_override"]["created"] is True
    assert _render_route_count(env) == 1


# ── 4. HTTP boundary adversarial probes ──────────────────────────────────


@pytest.fixture()
def api(env: _Env):  # type: ignore[no-untyped-def]
    def _override_session():  # type: ignore[no-untyped-def]
        session = env.factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app = FastAPI()
    app.include_router(s09_correction_router)
    app.dependency_overrides[deps.get_db_session] = _override_session
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _http_submit_body(seed: dict[str, Any], **payload_over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "occurrence_segment_id": seed["segment"],
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
    }
    payload.update(payload_over)
    return {
        "workspace_id": WS,
        "project_id": seed["project"],
        "video_item_id": seed["video"],
        "idempotency_key": "api-c1",
        "payload": payload,
    }


@pytest.mark.parametrize(
    ("name", "overrides", "want_status"),
    [
        ("bogus_from", {"route_from": "bogus_from"}, 422),
        ("stale_literal", {"route_to": "keyed_pipeline"}, 422),
        ("anchor9", {"anchor_x": 9.0}, 422),
        ("anchor-2", {"anchor_y": -2.0}, 422),
        ("frames_rev", {"start_frame": 20, "end_frame": 1}, 422),
        (
            "empty_evidence",
            {
                "provenance": {
                    "route_from": "pose_swap",
                    "route_to": "sprite_affine",
                    "evidence": " ",
                }
            },
            422,
        ),
        (
            "path_escape",
            {"occurrence_segment_id": "../../etc/passwd"},
            422,
        ),
        ("unknown_field", {"teleport": True}, 422),
        # Unknown segment (valid shape, nonexistent) → 409 conflict, and
        # still zero durable side effect.
        (
            "ghost_segment",
            {"occurrence_segment_id": "00000000-0000-4000-8000-deadbeef0001"},
            409,
        ),
    ],
)
def test_api_rejects_without_side_effects(
    env: _Env,
    api,  # type: ignore[no-untyped-def]
    name: str,
    overrides: dict[str, Any],
    want_status: int,
) -> None:
    body = _http_submit_body(env.seed, **overrides)

    rows_before = _correction_row_count(env)
    routes_before = _render_route_count(env)

    response = api.post("/api/v2/s09-corrections", json=body)
    assert response.status_code == want_status, (
        f"{name}: expected {want_status}, got {response.status_code} "
        f"{response.text[:200]}"
    )

    assert _correction_row_count(env) == rows_before
    assert _render_route_count(env) == routes_before


def test_api_valid_submit_deterministic_replay(env: _Env, api) -> None:  # type: ignore[no-untyped-def]
    body = _http_submit_body(env.seed)

    r1 = api.post("/api/v2/s09-corrections", json=body)
    assert r1.status_code == 201, r1.text
    doc = r1.json()
    assert doc["created"] is True and doc["replayed"] is False

    r2 = api.post("/api/v2/s09-corrections", json=body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["replayed"] is True
    assert r2.json()["correction"]["id"] == doc["correction"]["id"]

    # Same key, DIFFERENT payload → 409 (idempotency conflict).
    r3 = api.post(
        "/api/v2/s09-corrections",
        json=_http_submit_body(env.seed, anchor_x=0.5),
    )
    assert r3.status_code == 409

    assert _correction_row_count(env) == 1
