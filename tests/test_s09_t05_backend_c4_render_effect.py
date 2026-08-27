"""S09-T05A-C4 — canonical render-effect context tests (contact / mesh_parts).

Completes the five-kind §4.3 coverage started in
``test_s09_t05_backend_c3_context.py`` (mask/z_order/route_override live
there).  Every test runs against REAL migrated SQLite databases through the
CAS repositories — no mocks, no stubs:

- ``contact``: the applied context binds the exact contact effect to its
  bound operation — both endpoint segment bindings (stable machine
  ``logical_id`` layer keys), exact start/end frame + time and the CASed
  post-apply values; the durable scene_graph_contact row really moved;
- ``mesh_parts``: the context carries the FULL applied transform (every
  parameter, not just ``transform_type``) plus the exact frame range;
- replay/immutability: re-reading through fresh sessions (process-restart
  simulation) yields byte-identical payloads and SHAs;
- refusals stay fail-closed with ZERO durable mutation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

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
from app.services.s09_correction import (
    CorrectionConflictError,
    CorrectionValidationError,
    S09CorrectionRepository,
    _canonical_json,
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


class _Env:
    def __init__(self, factory: Any, seed_data: dict[str, Any]) -> None:
        self.factory = factory
        self.seed = seed_data


@pytest.fixture()
def env(tmp_path: Path) -> Any:
    db = tmp_path / "c4.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    ids: dict[str, Any] = {}
    with factory() as s:
        s.add(Workspace(id=WS, name=WS))
        art = Artifact(
            workspace_id=WS, kind="video", relative_path="src.mp4",
            state="ready", sha256=_sha(1),
        )
        s.add(art)
        s.flush()
        project = Project(workspace_id=WS, name="T05AC4")
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
                workspace_id=WS, project_id=project.id, video_item_id=video.id,
                source_generation="3", name=name, kind=kind, status="confirmed",
            )
            s.add(role)
            s.flush()
            ids[f"role_{name.lower()}"] = role.id
        mask = Artifact(
            workspace_id=WS, kind="image", relative_path="m.png",
            state="ready", sha256=_sha(2),
        )
        s.add(mask)
        s.flush()
        s.commit()
        ids.update(project=project.id, video=video.id, scene=scene.id,
                   job=job.id, mask=mask.id)

    with factory() as s:
        repo = StructuralEvidenceRepository(s)
        hand, _ = repo.create_segment(
            WS, ids["project"], ids["video"], ids["role_character"],
            ids["scene"], "Character", 0, 90, 0, 3000, "3", kind="character",
            source_job_id=ids["job"], mask_artifact_id=ids["mask"],
            segmentation={"points": [{"x": 10.0, "y": 20.0, "label": "h"}]},
        )
        phone, _ = repo.create_segment(
            WS, ids["project"], ids["video"], ids["role_phone"],
            ids["scene"], "Phone", 20, 90, 700, 3000, "3", kind="prop",
            source_job_id=ids["job"], mask_artifact_id=ids["mask"],
            segmentation={"points": [{"x": 40.0, "y": 50.0, "label": "p"}]},
        )
        contact, _ = repo.create_contact(
            WS, ids["project"], ids["video"], hand.id, phone.id, "hand_phone",
            30, 60, 1000, 2000,
        )
        motion, _ = repo.create_motion(
            WS, hand.id, "object_relative", {"dx": 1.0, "dy": 0.0},
            start_frame=0, end_frame=90, start_time_ms=0, end_time_ms=3000,
        )
        s.commit()
        ids.update(
            hand=hand.id, hand_logical=hand.logical_id,
            phone=phone.id, phone_logical=phone.logical_id,
            contact=contact.id, contact_revision=contact.revision,
            motion=motion.id, motion_revision=motion.revision,
        )

    environment = _Env(factory, ids)
    yield environment
    create_engine_for_path(db).dispose()


def _apply(env: _Env, kind: str, request: dict[str, Any], idem: str) -> str:
    """Archive + confirm one correction; return the correction id."""
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], kind, dict(request)
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], kind,
            dict(request), impact, idempotency_key=idem,
        )
        assert created is True
        applied, changed = corr.confirm_correction(WS, rec.id, 1)
        assert changed is True and applied.status == "applied"
        session.commit()
        return rec.id


def _read_ctx(env: _Env, cid: str) -> dict[str, Any]:
    with env.factory() as session:
        return S09CorrectionRepository(session).applied_regeneration_context(
            WS, cid
        )


# ── contact: exact bound-operation effect ─────────────────────────────────


def test_contact_context_binds_exact_operation_and_replay_same_sha(
    env: _Env,
) -> None:
    request = {
        "contact_id": env.seed["contact"],
        "revision": env.seed["contact_revision"],
        "end_frame": 55,
        "end_time_ms": 1850,
        "reasons": ["contact ends earlier"],
        "provenance": {"user": "reviewer-c4"},
        "affected_loop_ids": ["loop_contact"],
    }
    cid = _apply(env, "contact", request, "c4-contact-idem")
    ctx = _read_ctx(env, cid)

    # Stable MACHINE layer keys for BOTH endpoint lineages (§4.2), not
    # display labels.
    assert ctx["affected_layer_ids"] == sorted(
        [env.seed["hand_logical"], env.seed["phone_logical"]]
    )
    bindings = ctx["layer_bindings"]
    assert set(bindings) == set(ctx["affected_layer_ids"])
    assert env.seed["hand"] in bindings[env.seed["hand_logical"]]["bound_segment_ids"]
    assert env.seed["phone"] in bindings[env.seed["phone_logical"]]["bound_segment_ids"]
    assert bindings[env.seed["hand_logical"]]["video_item_id"] == env.seed["video"]
    assert bindings[env.seed["hand_logical"]]["scene_id"] == env.seed["scene"]

    # Exact contact effect BOUND to its operation (§4.3) — post-apply CAS
    # values, never a display label.
    effect = ctx["effect"]["render_effect"]
    assert effect["version"] == "s09-correction-render-effect-v1"
    assert effect["op"] == "contact"
    assert effect["target_contact_id"] == env.seed["contact"]
    assert effect["source_segment_id"] == env.seed["hand"]
    assert effect["target_segment_id"] == env.seed["phone"]
    assert effect["contact_kind"] == "hand_phone"
    assert effect["start_frame"] == 30
    assert effect["end_frame"] == 55          # corrected post-apply value
    assert effect["start_time_ms"] == 1000
    assert effect["end_time_ms"] == 1850      # corrected post-apply value

    # The bound durable operation REALLY moved (no false success).
    with env.factory() as session:
        row = session.execute(
            text(
                "SELECT end_frame, end_time_ms FROM scene_graph_contact "
                "WHERE id=:i"
            ),
            {"i": env.seed["contact"]},
        ).one()
    assert tuple(row) == (55, 1850)

    # Immutability / restart: byte-identical payload + SHA via fresh sessions.
    payloads = {_canonical_json(_read_ctx(env, cid)) for _ in range(3)}
    assert len(payloads) == 1
    canonical = payloads.pop()
    recomputed = __import__("hashlib").sha256(
        _canonical_json({k: v for k, v in json.loads(canonical).items()
                         if k != "context_sha256"}).encode("utf-8")
    ).hexdigest()
    assert json.loads(canonical)["context_sha256"] == recomputed


# ── mesh_parts: FULL applied transform ────────────────────────────────────


def test_mesh_parts_context_carries_full_applied_transform(env: _Env) -> None:
    full_transform = {
        "dx": -2.5,
        "dy": 4.0,
        "rotate_deg": 12.5,
        "scale_xy": [1.25, 0.75],
    }
    request = {
        "motion_id": env.seed["motion"],
        "revision": env.seed["motion_revision"],
        "transform": dict(full_transform),
        "confidence": 1.0,
        "reasons": ["parts drift corrected"],
        "provenance": {"user": "animator-c4"},
        "affected_loop_ids": ["loop_mesh"],
    }
    cid = _apply(env, "mesh_parts", request, "c4-mesh-idem")
    ctx = _read_ctx(env, cid)

    assert ctx["affected_layer_ids"] == [env.seed["hand_logical"]]
    binding = ctx["layer_bindings"][env.seed["hand_logical"]]
    assert env.seed["hand"] in binding["bound_segment_ids"]
    assert ctx["affected_motion_ids"] == [env.seed["motion"]]

    effect = ctx["effect"]["render_effect"]
    assert effect["version"] == "s09-correction-render-effect-v1"
    assert effect["op"] == "mesh_parts"
    assert effect["target_motion_id"] == env.seed["motion"]
    assert effect["transform_type"] == "object_relative"
    # FULL applied transform — EVERY parameter survives into the context,
    # not just transform_type (C3-F3 root cause).
    assert effect["applied_transform"] == full_transform
    assert effect["frame_range"] == {
        "start_frame": 0,
        "end_frame": 90,
        "start_time_ms": 0,
        "end_time_ms": 3000,
    }

    # The durable motion row really carries the full transform.
    with env.factory() as session:
        raw = session.execute(
            text("SELECT transform_json FROM segment_motion WHERE id=:i"),
            {"i": env.seed["motion"]},
        ).scalar()
    assert json.loads(raw) == full_transform

    # Replay through fresh sessions: byte-identical payload + stable SHA.
    payloads = {_canonical_json(_read_ctx(env, cid)) for _ in range(3)}
    assert len(payloads) == 1


# ── fail-closed refusals (zero durable mutation) ──────────────────────────


def _durable_snapshot(env: _Env) -> dict[str, int]:
    counts: dict[str, int] = {}
    with env.factory() as session:
        for table in (
            "s09_correction",
            "artifact",
            "job",
            "occurrence_segment",
            "segment_motion",
            "scene_graph_contact",
            "apply_checkpoint",
        ):
            try:
                counts[table] = int(
                    session.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    ).scalar()
                )
            except Exception:
                counts[table] = -1
    return counts


def test_refuse_pending_contact_context_zero_mutation(env: _Env) -> None:
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = {
            "contact_id": env.seed["contact"],
            "revision": env.seed["contact_revision"],
            "end_frame": 58,
            "reasons": ["never confirmed"],
            "provenance": {"user": "reviewer-c4"},
            "affected_loop_ids": ["loop_contact"],
        }
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "contact", dict(request)
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "contact",
            dict(request), impact,
        )
        assert created is True
        session.commit()

    before = _durable_snapshot(env)
    with env.factory() as session, pytest.raises(CorrectionConflictError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, rec.id
        )
    assert _durable_snapshot(env) == before


def test_refuse_cancelled_mesh_context_zero_mutation(env: _Env) -> None:
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = {
            "motion_id": env.seed["motion"],
            "revision": env.seed["motion_revision"],
            "transform": {"dx": 9.0, "dy": -9.0},
            "reasons": ["cancelled before apply"],
            "provenance": {"user": "animator-c4"},
            "affected_loop_ids": ["loop_mesh"],
        }
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "mesh_parts",
            dict(request),
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "mesh_parts",
            dict(request), impact,
        )
        assert created is True
        cancelled, changed = corr.cancel_correction(WS, rec.id, 1)
        assert changed is True and cancelled.status == "cancelled"
        session.commit()

    before = _durable_snapshot(env)
    with env.factory() as session, pytest.raises(CorrectionConflictError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, rec.id
        )
    assert _durable_snapshot(env) == before


# ── §4.3 five-kind completeness: every kind's canonical render effect ────


def _zorder_request_for(env: _Env, segment: str) -> dict[str, Any]:
    with env.factory() as session:
        fresh = StructuralEvidenceRepository(session).get_segment(WS, segment)
        revision = int(fresh.revision)
    return {
        "occurrence_segment_id": segment,
        "revision": revision,
        "source_generation": "3",
        "z_order": 42,
        "affected_loop_ids": [env.seed.get("loop", f"loop_{segment[:8]}")],
        "provenance": {
            "user": "operator-c4",
            "reason": "compositing order wrong in overlap window",
            "evidence": "review note c4 overlap fixture",
        },
    }


def test_zorder_and_mask_and_route_contexts_carry_canonical_effects(
    env: _Env,
) -> None:
    # z_order happy path through the C4 file's own seeded environment.
    zreq = _zorder_request_for(env, env.seed["hand"])
    cid = _apply(env, "z_order", zreq, "c4-z-idem")
    ctx = _read_ctx(env, cid)
    effect = ctx["effect"]["render_effect"]
    assert effect["op"] == "z_order"
    assert effect["target_layer_id"] == env.seed["hand_logical"]
    assert ctx["affected_layer_ids"] == [env.seed["hand_logical"]]
    assert effect["z_order"] == 42
    binding = ctx["layer_bindings"][env.seed["hand_logical"]]
    assert effect["target_segment_id"] in binding["bound_segment_ids"]
    assert ctx["effect"]["applied_layer_bindings"] == ctx["layer_bindings"]

    # mask: resolved immutable artifact evidence from the artifact store.
    # z_order superseded the hand lineage above, so the mask request must
    # retarget the LIVE successor (historical rows are read-only).
    with env.factory() as session:
        seg_now = StructuralEvidenceRepository(session).get_segment(
            WS, env.seed["hand"]
        )
        mask_target = seg_now.superseded_by_id or seg_now.id
    mreq = {
        "occurrence_segment_id": mask_target,
        "revision": 1,  # successor starts a fresh CAS revision
        "source_generation": "3",
        "segmentation": {"points": [{"x": 12.5, "y": 22.5, "label": "h2"}]},
        "mask_artifact_id": env.seed["mask"],
        "confidence_source": "manual",
        "reasons": ["polygon drifted at frame 45"],
        "provenance": {
            "user": "op-c4",
            "reason": "mask drifted",
            "evidence": "review note c4 mask",
        },
        "affected_loop_ids": ["loop_mask_c4"],
    }
    cid = _apply(env, "mask", mreq, "c4-mask-idem")
    ctx = _read_ctx(env, cid)
    effect = ctx["effect"]["render_effect"]
    artifact = effect["mask_artifact"]
    assert artifact["artifact_id"] == env.seed["mask"]
    assert len(artifact["sha256"]) == 64 and artifact["relative_path"]
    assert artifact["kind"] == "image"
    semantics = effect["mask_semantics"]
    assert semantics["segmentation"] == mreq["segmentation"]
    assert semantics["source_generation"] == "3"
    assert semantics["version"] == "s09-mask-semantics-v1"
    assert semantics["confidence_source"] == "manual"
    assert effect["target_layer_id"] == env.seed["hand_logical"]
    assert ctx["effect"]["supersede"]["successor_id"] == effect["target_segment_id"]

    # route_override: exact target/segment + measured-passing route_to +
    # frame range/anchor/provenance on the NEW history row.
    rreq = {
        "occurrence_segment_id": env.seed["phone"],
        "route_from": "pose_swap",
        "route_to": "controlled_redraw",
        "anchor_x": 0.25,
        "anchor_y": 0.75,
        "start_frame": 20,
        "end_frame": 90,
        "override_reason": "swap capability missing for this pose set",
        "affected_loop_ids": ["loop_route_c4"],
        "provenance": {
            "route_from": "pose_swap",
            "route_to": "controlled_redraw",
            "reason": "operator override after review",
            "evidence": "benchmark FAIL row pose_swap",
        },
    }
    cid = _apply(env, "route_override", rreq, "c4-route-idem")
    ctx = _read_ctx(env, cid)
    effect = ctx["effect"]["render_effect"]
    assert effect["target_layer_id"] == env.seed["phone_logical"]
    assert effect["target_segment_id"] == env.seed["phone"]
    assert effect["route_from"] == "pose_swap"
    assert effect["route_to"] == "controlled_redraw"
    assert effect["frame_range"] == {
        "start_frame": 20,
        "end_frame": 90,
    }
    assert effect["anchor"] == {"x": 0.25, "y": 0.75}
    assert effect["provenance"]["evidence"] == "benchmark FAIL row pose_swap"
    assert effect["render_route_id"] == (
        ctx["effect"]["route_override"]["render_route_id"]
    )


# ── §4 replay immutability under lineage stacking ─────────────────────────


def test_context_sha_immutable_when_lineage_superseded_later(env: _Env) -> None:
    """A later correction on the same lineage must NOT mutate the earlier
    applied context (SHA drift regression): bindings are frozen into each
    applied result at confirm time and re-read from there."""
    first_request = _zorder_request_for(env, env.seed["hand"])
    first_cid = _apply(env, "z_order", dict(first_request), "c4-stack-1")
    first_ctx = _read_ctx(env, first_cid)
    first_sha = first_ctx["context_sha256"]
    first_payload = _canonical_json(first_ctx)
    assert first_ctx["layer_bindings"][env.seed["hand_logical"]][
        "bound_segment_ids"
    ] == [first_ctx["effect"]["render_effect"]["target_segment_id"]]

    # Second correction supersedes the SAME logical_id again.
    successor = first_ctx["effect"]["render_effect"]["target_segment_id"]
    second_cid = _apply(env, "z_order", _zorder_request_for(env, successor),
                        "c4-stack-2")

    first_after = _read_ctx(env, first_cid)
    assert _canonical_json(first_after) == first_payload
    assert first_after["context_sha256"] == first_sha

    second_ctx = _read_ctx(env, second_cid)
    second_sha = second_ctx["context_sha256"]
    assert second_sha != first_sha
    assert set(second_ctx["effect"]["applied_layer_bindings"]) == {
        env.seed["hand_logical"]
    }
    # Both contexts still resolve the SAME stable machine layer id.
    assert first_after["affected_layer_ids"] == [
        env.seed["hand_logical"]
    ] == second_ctx["affected_layer_ids"]

    # Replay both after a fresh session (restart simulation): byte-identical.
    replay_first = {_canonical_json(_read_ctx(env, first_cid)) for _ in range(2)}
    replay_second = {_canonical_json(_read_ctx(env, second_cid)) for _ in range(2)}
    assert len(replay_first) == 1 and len(replay_second) == 1
    assert json.loads(replay_first.pop())["context_sha256"] == first_sha
    assert json.loads(replay_second.pop())["context_sha256"] == second_sha


def test_confirm_refuses_impact_without_stable_layer_ids_zero_mutation(
    env: _Env,
) -> None:
    """Confirm-time fail-closed guard: an archived impact without stable
    machine layer ids refuses BEFORE any durable mutation."""
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = _zorder_request_for(env, env.seed["phone"])
        request["affected_loop_ids"] = ["loop_badimpact"]
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "z_order",
            dict(request),
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "z_order",
            dict(request), impact,
        )
        assert created is True
        # Corrupt the archived impact to a legacy shape WITHOUT stable ids.
        session.execute(
            text("UPDATE s09_correction SET impact_json=:j WHERE id=:i"),
            {"j": json.dumps({"affected_layer_labels": ["Phone"]}),
             "i": rec.id},
        )
        session.commit()
        before = _durable_snapshot(env)
        with pytest.raises(CorrectionValidationError):
            corr.confirm_correction(WS, rec.id, 1)
        session.rollback()
        assert _durable_snapshot(env) == before
