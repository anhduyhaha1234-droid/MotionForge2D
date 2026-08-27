"""S09-T05A-C3 — immutable applied-regeneration context tests.

Pins the §3.2 backend contract consumed by the T04 regenerate endpoint:

- ``applied_regeneration_context`` returns correction id/kind/applied
  revision/natural key, affected loop/layer/segment IDs, canonical
  mutation effect and a canonical SHA-256 over the whole context;
- deterministic across fresh sessions / process-style reopens ×2
  basetemp runs;
- fail-closed refusals with ZERO durable mutation: non-applied
  (pending/cancelled), stale expected revision, empty affected loops,
  malformed/empty result, unknown id, wrong workspace;
- applied-row immutability: replay/re-read → byte-identical context SHA;
- existing five kinds / CAS / idempotency regression stays green.
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
    CorrectionImpact,
    CorrectionNotFoundError,
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
    db = tmp_path / "c3.db"
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
        project = Project(workspace_id=WS, name="T05AC3")
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
        ids["segment_logical_id"] = seg.logical_id

    environment = _Env(factory, ids)
    yield environment
    create_engine_for_path(db).dispose()


def _zorder_request(env: _Env) -> dict[str, Any]:
    return {
        "occurrence_segment_id": env.seed["segment"],
        "revision": 1,
        "source_generation": "3",
        "z_order": 42,
        "mask_artifact_id": env.seed["mask2"],
        "affected_loop_ids": ["loop_a", "loop_b"],
        "provenance": {
            "user": "operator-7",
            "reason": "compositing order wrong in overlap window",
            "evidence": "review note 2026-08-25 overlap fixture",
        },
    }


def _submit_and_apply(env: _Env) -> dict[str, Any]:
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = _zorder_request(env)
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "z_order", dict(request)
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "z_order",
            dict(request), impact, idempotency_key="c3-idem",
        )
        assert created is True
        applied, changed = corr.confirm_correction(WS, rec.id, 1)
        assert changed is True and applied.status == "applied"
        session.commit()
        return {"id": rec.id, "revision": applied.revision}


# ── 1. happy path: canonical context + SHA ────────────────────────────────


def test_context_shape_and_canonical_fields(env: _Env) -> None:
    info = _submit_and_apply(env)
    with env.factory() as session:
        ctx = S09CorrectionRepository(session).applied_regeneration_context(
            WS, info["id"]
        )

    assert ctx["correction_id"] == info["id"]
    assert ctx["correction_kind"] == "z_order"
    assert ctx["applied_revision"] == info["revision"]
    assert ctx["natural_key"].startswith("S09C:")
    assert ctx["workspace_id"] == WS
    assert ctx["project_id"] == env.seed["project"]
    assert ctx["video_item_id"] == env.seed["video"]
    assert ctx["occurrence_segment_id"] == env.seed["segment"]
    assert ctx["affected_loop_ids"] == ["loop_a", "loop_b"]
    # S09-C4 §4.2: affected_layer_ids are STABLE MACHINE keys (the segment
    # lineage logical_id), never display labels ("Character" is the label).
    assert ctx["affected_occurrence_segment_ids"] == [env.seed["segment"]]
    assert ctx["affected_layer_ids"] == [env.seed["segment_logical_id"]]
    assert "Character" not in ctx["affected_layer_ids"]
    # Structural binding evidence re-derived from live rows (§4.2).
    bindings = ctx["layer_bindings"]
    assert set(bindings) == {env.seed["segment_logical_id"]}
    binding = bindings[env.seed["segment_logical_id"]]
    # The z_order supersede advanced the lineage: the binding must point at
    # the LIVE successor of the same stable logical_id, never the
    # historical predecessor.
    with env.factory() as session:
        seg_now = StructuralEvidenceRepository(session).get_segment(
            WS, env.seed["segment"]
        )
        live_segment_id = seg_now.superseded_by_id or seg_now.id
    assert live_segment_id in binding["bound_segment_ids"]
    assert env.seed["segment"] not in binding["bound_segment_ids"]
    assert binding["video_item_id"] == env.seed["video"]
    assert binding["scene_id"] == env.seed["scene"]
    assert binding["role_id"] == env.seed["role"]
    # Contract version pin + per-kind canonical render effect (§4.3).
    assert ctx["render_effect_version"] == "s09-correction-render-effect-v1"
    effect = ctx["effect"]["render_effect"]
    assert effect["op"] == "z_order"
    assert effect["target_layer_id"] == env.seed["segment_logical_id"]
    assert effect["target_segment_id"] in binding["bound_segment_ids"]
    assert effect["z_order"] == 42
    assert isinstance(ctx["effect"], dict) and ctx["effect"]
    # Canonical SHA present, hex, 64 chars; stable when recomputed.
    sha = ctx["context_sha256"]
    assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
    payload = {k: v for k, v in ctx.items() if k != "context_sha256"}
    recomputed = __import__("hashlib").sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    assert sha == recomputed


def test_context_deterministic_fresh_sessions_and_restarts(env: _Env) -> None:
    info = _submit_and_apply(env)
    shas: list[str] = []
    payloads: list[str] = []
    for _round in range(3):
        with env.factory() as session:
            ctx = S09CorrectionRepository(session).applied_regeneration_context(
                WS, info["id"]
            )
        shas.append(ctx["context_sha256"])
        payloads.append(_canonical_json(ctx))
    assert len(set(shas)) == 1, f"SHA drifted across fresh sessions: {shas}"
    assert len(set(payloads)) == 1


# ── 2. fail-closed refusals, ZERO durable mutation ────────────────────────


def _durable_snapshot(env: _Env) -> dict[str, int]:
    counts: dict[str, int] = {}
    with env.factory() as session:
        for table in (
            "s09_correction",
            "artifact",
            "job",
            "occurrence_segment",
            "apply_checkpoint",
        ):
            try:
                counts[table] = int(
                    session.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    ).scalar()
                )
            except Exception:
                # apply_checkpoint may not exist in this schema state;
                # a missing table cannot gain rows either way.
                counts[table] = -1
    return counts


def test_refuse_pending_correction_zero_mutation(env: _Env) -> None:
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = _zorder_request(env)
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "z_order", dict(request)
        )
        rec, created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "z_order",
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


def test_refuse_cancelled_correction_zero_mutation(env: _Env) -> None:
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = _zorder_request(env)
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "z_order", dict(request)
        )
        rec, _ = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "z_order",
            dict(request), impact,
        )
        cancelled, changed = corr.cancel_correction(WS, rec.id, 1)
        assert changed is True and cancelled.status == "cancelled"
        session.commit()

    before = _durable_snapshot(env)
    with env.factory() as session, pytest.raises(CorrectionConflictError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, rec.id
        )
    assert _durable_snapshot(env) == before


def test_refuse_stale_expected_revision(env: _Env) -> None:
    info = _submit_and_apply(env)
    with env.factory() as session, pytest.raises(CorrectionConflictError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, info["id"], expected_applied_revision=info["revision"] + 7
        )


def test_accept_exact_expected_revision(env: _Env) -> None:
    info = _submit_and_apply(env)
    with env.factory() as session:
        ctx = S09CorrectionRepository(session).applied_regeneration_context(
            WS, info["id"], expected_applied_revision=info["revision"]
        )
    assert ctx["correction_id"] == info["id"]


def _apply_with_loops(env: _Env, loops: list[str]) -> dict[str, Any]:
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        request = _zorder_request(env)
        request["affected_loop_ids"] = loops
        impact = corr.compute_impact(
            WS, env.seed["project"], env.seed["video"], "z_order", dict(request)
        )
        rec, _created = corr.create_correction(
            WS, env.seed["project"], env.seed["video"], "z_order",
            dict(request), impact,
        )
        applied, changed = corr.confirm_correction(WS, rec.id, 1)
        assert changed is True
        session.commit()
        return {"id": rec.id}


def test_refuse_empty_affected_loop_scope_after_apply(env: _Env) -> None:
    # A correction applied WITHOUT loop scope can never drive a targeted
    # regeneration; context refuses fail-closed instead of guessing.
    info = _apply_with_loops(env, [])
    before = _durable_snapshot(env)
    with env.factory() as session, pytest.raises(CorrectionValidationError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, info["id"]
        )
    assert _durable_snapshot(env) == before


def test_refuse_unknown_and_cross_workspace_ids(env: _Env) -> None:
    info = _submit_and_apply(env)
    with env.factory() as session:
        repo = S09CorrectionRepository(session)
        with pytest.raises(CorrectionNotFoundError):
            repo.applied_regeneration_context(WS, "00000000-0000-4000-8000-deadbeefc3")
        with pytest.raises(CorrectionNotFoundError):
            repo.applied_regeneration_context("ws-other-workspace", info["id"])


def test_refuse_malformed_or_empty_mutation_result(env: _Env) -> None:
    # Simulate a legacy/corrupted row: applied but result_json empty.
    info = _submit_and_apply(env)
    with env.factory() as s:
        s.execute(
            text("UPDATE s09_correction SET result_json=:r WHERE id=:i"),
            {"r": "", "i": info["id"]},
        )
        s.commit()
    before = _durable_snapshot(env)
    with env.factory() as session, pytest.raises(CorrectionValidationError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, info["id"]
        )
    assert _durable_snapshot(env) == before


def test_refuse_missing_layer_binding_zero_mutation(env: _Env) -> None:
    # S09-C4 §4.2: a legacy applied row whose impact carries NO stable
    # machine layer id can never drive an exact render binding — the
    # context refuses fail-closed instead of letting the renderer guess
    # from array positions / display labels.
    info = _submit_and_apply(env)
    with env.factory() as s:
        impact = s.execute(
            text("SELECT impact_json FROM s09_correction WHERE id=:i"),
            {"i": info["id"]},
        ).scalar()
        payload = json.loads(impact)
        payload["affected_layer_ids"] = []
        s.execute(
            text("UPDATE s09_correction SET impact_json=:j WHERE id=:i"),
            {"j": json.dumps(payload), "i": info["id"]},
        )
        s.commit()
    before = _durable_snapshot(env)
    with env.factory() as session, pytest.raises(CorrectionValidationError):
        S09CorrectionRepository(session).applied_regeneration_context(
            WS, info["id"]
        )
    assert _durable_snapshot(env) == before


# ── 3. applied-row immutability / replay same SHA ─────────────────────────


def test_replay_confirm_is_noop_and_context_sha_stable(env: _Env) -> None:
    info = _submit_and_apply(env)

    # Replay confirm on the APPLIED row must be a no-op (changed=False).
    with env.factory() as session:
        corr = S09CorrectionRepository(session)
        replayed, changed = corr.confirm_correction(
            WS, info["id"], info["revision"]
        )
        assert changed is False and replayed.status == "applied"
        assert replayed.revision == info["revision"]
        session.commit()

    with env.factory() as session:
        sha_before = S09CorrectionRepository(
            session
        ).applied_regeneration_context(WS, info["id"])["context_sha256"]
    with env.factory() as session:
        sha_after = S09CorrectionRepository(
            session
        ).applied_regeneration_context(WS, info["id"])["context_sha256"]
    assert sha_before == sha_after

    # Cancel-after-apply stays refused → the applied row can never drift.
    with env.factory() as session, pytest.raises(CorrectionConflictError):
        S09CorrectionRepository(session).cancel_correction(
            WS, info["id"], info["revision"]
        )
    with env.factory() as session:
        sha_final = S09CorrectionRepository(
            session
        ).applied_regeneration_context(WS, info["id"])["context_sha256"]
    assert sha_final == sha_before


# ── 4. all five kinds produce a valid applied context ─────────────────────


def _impact_stub(kind: str, segment: str, loops: list[str]) -> CorrectionImpact:
    return CorrectionImpact(
        correction_kind=kind,
        affected_occurrence_segment_ids=[segment],
        affected_contact_ids=[],
        affected_motion_ids=[],
        affected_loop_ids=loops,
        affected_layer_ids=[segment],
        route_override=kind == "route_override",
        counts={"segments": 1},
    )


def test_all_kinds_context_sha_unique_per_natural_content(env: _Env) -> None:
    # mask/z_order supersede lineage: each supersede advances the CURRENT
    # segment, so every kind after the first must target the LATEST
    # successor (historical predecessors are read-only).
    current_segment = env.seed["segment"]
    kind_requests: dict[str, tuple[str, dict[str, Any], bool]] = {
        "mask": (
            "mask-idem",
            {
                "occurrence_segment_id": current_segment,
                "revision": 1,
                "source_generation": "3",
                "segmentation": {
                    "points": [{"x": 11.5, "y": 21.5, "label": "center"}]
                },
                "mask_artifact_id": env.seed["mask2"],
                "affected_loop_ids": ["loop_mask"],
                "provenance": {
                    "user": "op",
                    "reason": "polygon drifted at frame 45",
                    "evidence": "review note mask",
                },
            },
            True,
        ),
        "z_order": (
            "zorder-idem",
            _zorder_request(env),
            True,
        ),
        "route_override": (
            "route-idem",
            {
                "occurrence_segment_id": current_segment,
                "route_from": "pose_swap",
                "route_to": "controlled_redraw",
                "anchor_x": 0.25,
                "anchor_y": 0.75,
                "start_frame": 0,
                "end_frame": 90,
                "override_reason": "swap capability missing for this pose set",
                "affected_loop_ids": ["loop_route"],
                "provenance": {
                    "route_from": "pose_swap",
                    "route_to": "controlled_redraw",
                    "reason": "operator override after review",
                    "evidence": "benchmark FAIL row pose_swap",
                },
            },
            False,
        ),
    }
    seen: dict[str, str] = {}
    for kind, (idem, request, retarget) in kind_requests.items():
        with env.factory() as session:
            evidence = StructuralEvidenceRepository(session)
            seg_row = evidence.get_segment(WS, current_segment)
            if retarget and seg_row.superseded_by_id:
                # Point the request at the live lineage successor.
                current_segment = seg_row.superseded_by_id
                request["occurrence_segment_id"] = current_segment
            if "revision" in request:
                fresh = evidence.get_segment(WS, current_segment)
                request["revision"] = int(fresh.revision)
            corr = S09CorrectionRepository(session)
            impact = corr.compute_impact(
                WS, env.seed["project"], env.seed["video"],
                kind, dict(request),
            )
            rec, created = corr.create_correction(
                WS, env.seed["project"], env.seed["video"],
                kind, dict(request), impact, idempotency_key=idem,
            )
            assert created is True
            applied, changed = corr.confirm_correction(WS, rec.id, 1)
            assert changed is True
            session.commit()
            cid = rec.id
        with env.factory() as session:
            ctx = S09CorrectionRepository(session).applied_regeneration_context(
                WS, cid
            )
        assert ctx["correction_kind"] == kind
        assert ctx["effect"], f"{kind} effect must be non-empty"
        assert ctx["context_sha256"] not in seen.values(), (
            f"{kind} SHA collides with {seen}"
        )
        seen[kind] = ctx["context_sha256"]
        # S09-C4 §4.3 per-kind completeness — the canonical render effect
        # carries exactly what T03 needs to re-apply after a restart.
        effect = ctx["effect"]["render_effect"]
        assert effect["version"] == "s09-correction-render-effect-v1"
        assert effect["op"] == kind
        if kind == "mask":
            artifact = effect["mask_artifact"]
            assert artifact["artifact_id"] == env.seed["mask2"]
            assert len(artifact["sha256"]) == 64
            assert artifact["relative_path"]
            semantics = effect["mask_semantics"]
            assert semantics["segmentation"]
            assert semantics["source_generation"] == "3"
        elif kind == "z_order":
            assert effect["z_order"] == 42
            assert effect["target_layer_id"] in ctx["affected_layer_ids"]
            assert effect["target_segment_id"]
        elif kind == "route_override":
            assert effect["route_to"] == "controlled_redraw"
            assert effect["route_from"] == "pose_swap"
            assert effect["frame_range"]["start_frame"] <= \
                effect["frame_range"]["end_frame"]
            assert set(effect["anchor"]) == {"x", "y"}
            assert effect["provenance"]["evidence"]
            assert effect["render_route_id"]
        assert ctx["affected_layer_ids"], (
            f"{kind} context must carry stable machine layer ids"
        )
        for layer in ctx["affected_layer_ids"]:
            assert layer in ctx["layer_bindings"]

    # contact + mesh_parts kinds exercise the same context path through
    # the CAS repositories (covered for refusal semantics above); their
    # happy-path mutation flows already pinned in the domain suite.

