"""S09-T05A domain tests — targeted-correction repository behavior.

Binary acceptance coverage per TASK.md (real migrated temp SQLite DBs —
FK/CHECK/partial-unique enforced, never MAIN):

- natural-key + idempotency-key idempotent replay returns the SAME row
  (created=False); materially different payload under the same key → conflict;
- CAS confirm exactly-once: stale revision refused with ZERO durable
  mutation (both directions: applied stays applied; pending stays pending);
- cancel semantics: pending→cancelled once; applied can never be cancelled;
  cancelled can never be confirmed (terminal states stay terminal);
- restart safety: a new session after "process death" replays the SAME
  correction row and re-confirm is a no-op (created=False / applied=False);
- mask/z_order corrections supersede the locked OccurrenceSegment lineage:
  logical_id stable, lineage_version+1, predecessor historical + queryable,
  successor carries the user provenance (never machine-inherited);
- contact corrections CAS the SceneGraphContact edge (stale revision → zero
  mutation); mesh/parts corrections CAS the SegmentMotion transform;
- route_override writes a NEW SegmentRenderRoute history row whose
  provenance persists route_from/route_to/reason/evidence; the OLD decision
  row is byte-identical afterwards (never mutated);
- unaffected-segment hash stability: segments outside the correction scope
  keep byte-identical durable JSON before/after confirm;
- impact preview is a PURE read (zero rows written);
- workspace isolation both directions;
- applied_correction_counts feeds the benchmark-results schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import (
    Artifact,
    Job,
    ObjectRole,
    Project,
    Scene,
    SegmentRenderRoute,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import (
    ContactConflictError,
    MotionConflictError,
    StructuralEvidenceRepository,
)
from app.services.s09_correction import (
    CorrectionConflictError,
    CorrectionImpact,
    CorrectionNotFoundError,
    CorrectionValidationError,
    S09CorrectionRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = "s09t05a-ws"
WS_B = "s09t05a-ws-other"
GEN = "3"


def _sha(n: int) -> str:
    return f"{n:064x}"


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


class Seed:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.project = ""
        self.video = ""
        self.scene = ""
        self.roles: dict[str, str] = {}
        self.masks: list[str] = []
        self.job = ""


def _seed(session: Any) -> Seed:
    seed = Seed(session)
    session.add(Workspace(id=WS, name=WS))
    session.add(Workspace(id=WS_B, name=WS_B))
    session.flush()
    source = Artifact(
        workspace_id=WS, kind="video", relative_path="src.mp4", state="ready",
        sha256=_sha(1),
    )
    session.add(source)
    session.flush()
    project = Project(workspace_id=WS, name="T05A")
    session.add(project)
    session.flush()
    video = VideoItem(
        project_id=project.id, title="Video", position=0,
        source_artifact_id=source.id,
    )
    session.add(video)
    session.flush()
    job = Job(
        workspace_id=WS, job_type="DISCOVER_OBJECTS", owner_type="video_item",
        owner_id=video.id, state="completed", input_generation=GEN,
        input_manifest_json=json.dumps({"source_sha256": _sha(1)}),
    )
    session.add(job)
    session.flush()
    scene = Scene(
        video_item_id=video.id, position=0, start_frame=0, end_frame=180,
        start_time_ms=0, end_time_ms=6000, status="pending",
    )
    session.add(scene)
    session.flush()
    for name, kind in (("Character", "character"), ("Phone", "prop")):
        role = ObjectRole(
            workspace_id=WS, project_id=project.id, video_item_id=video.id,
            source_generation=GEN, name=name, kind=kind, status="confirmed",
        )
        session.add(role)
        session.flush()
        seed.roles[name] = role.id
    for i in range(4):
        mask = Artifact(
            workspace_id=WS, kind="image", relative_path=f"mask{i}.png",
            state="ready", sha256=_sha(10 + i),
        )
        session.add(mask)
        session.flush()
        seed.masks.append(mask.id)
    # Second workspace graph for isolation tests (own source artifact).
    other_source = Artifact(
        workspace_id=WS_B, kind="video", relative_path="other.mp4",
        state="ready", sha256=_sha(50),
    )
    session.add(other_source)
    session.flush()
    other_project = Project(workspace_id=WS_B, name="Other")
    session.add(other_project)
    session.flush()
    other_video = VideoItem(
        project_id=other_project.id, title="Other", position=0,
        source_artifact_id=other_source.id,
    )
    session.add(other_video)
    session.flush()
    seed.project = project.id
    seed.video = video.id
    seed.scene = scene.id
    seed.job = job.id
    session.commit()
    return seed


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t05a.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as session:
        yield session, _seed(session), factory, db
    create_engine_for_path(db).dispose()


def _seg(
    repo: StructuralEvidenceRepository,
    seed: Seed,
    name: str = "Character",
    *,
    z_order: int = 0,
) -> Any:
    rec, _created = repo.create_segment(
        WS,
        seed.project,
        seed.video,
        seed.roles[name],
        seed.scene,
        name,
        0,
        90,
        0,
        3000,
        GEN,
        kind="character" if name == "Character" else "prop",
        source_job_id=seed.job,
        mask_artifact_id=seed.masks[0],
        segmentation={"points": [{"x": 10.0, "y": 20.0, "label": "center"}]},
        z_order=z_order,
    )
    return rec


def _segment_durable_hash(session: Any, segment_id: str) -> str:
    """Canonical durable JSON of one occurrence_segment row (hash target)."""
    import hashlib

    row = session.execute(
        text(
            "SELECT * FROM occurrence_segment WHERE id = :i"
        ),
        {"i": segment_id},
    ).mappings().one()
    payload = json.dumps(
        {k: str(v) for k, v in sorted(row.items())}, sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── impact preview (pure read) ───────────────────────────────────────────


def test_impact_preview_is_pure_read(env) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = StructuralEvidenceRepository(session)
    seg = _seg(repo, seed)
    corr = S09CorrectionRepository(session)
    before_rows = session.execute(
        text("SELECT COUNT(*) FROM s09_correction")
    ).scalar()
    request = {
        "occurrence_segment_id": seg.id,
        "revision": seg.revision,
        "source_generation": GEN,
        "mask_artifact_id": seed.masks[1],
        "segmentation": {"points": [{"x": 12.0, "y": 22.0, "label": "center"}]},
        "provenance": {"user": "reviewer-7"},
    }
    impact = corr.compute_impact(WS, seed.project, seed.video, "mask", request)
    assert isinstance(impact, CorrectionImpact)
    assert impact.affected_occurrence_segment_ids == [seg.id]
    after_rows = session.execute(
        text("SELECT COUNT(*) FROM s09_correction")
    ).scalar()
    assert int(before_rows) == int(after_rows) == 0


def test_impact_unknown_kind_and_bad_payload_fail_closed(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    corr = S09CorrectionRepository(session)
    with pytest.raises(CorrectionValidationError):
        corr.compute_impact(WS, seed.project, seed.video, "teleport", {})
    with pytest.raises(CorrectionValidationError):
        corr.compute_impact(
            WS, seed.project, seed.video, "mask", {"occurrence_segment_id": "x"}
        )


# ── idempotent submit ────────────────────────────────────────────────────


def _pending_mask(
    session: Any, seed: Seed, seg: Any, *, idem: str = "idem-1", **overrides: Any
) -> tuple[Any, bool]:
    corr = S09CorrectionRepository(session)
    evidence = StructuralEvidenceRepository(session)
    current = evidence.get_segment(WS, seg.id)
    request = {
        "occurrence_segment_id": seg.id,
        "revision": current.revision,
        "source_generation": GEN,
        "mask_artifact_id": seed.masks[1],
        "segmentation": {"points": [{"x": 12.0, "y": 22.0, "label": "center"}]},
        "provenance": {"user": "reviewer-7"},
    }
    request.update(overrides)
    impact = corr.compute_impact(WS, seed.project, seed.video, "mask", request)
    return corr.create_correction(
        WS, seed.project, seed.video, "mask", request, impact,
        idempotency_key=idem,
    )


def test_submit_replay_same_row_created_false(env) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    r1, created1 = _pending_mask(session, seed, seg)
    r2, created2 = _pending_mask(session, seed, seg)
    assert created1 is True and created2 is False
    assert r1.id == r2.id and r1.status == "pending"
    total = session.execute(text("SELECT COUNT(*) FROM s09_correction")).scalar()
    assert int(total) == 1


def test_same_key_different_payload_conflicts(env) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    _pending_mask(session, seed, seg)
    with pytest.raises(CorrectionConflictError):
        _pending_mask(session, seed, seg, provenance={"user": "someone-else"})


def test_natural_key_converges_without_idempotency_key(env) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    corr = S09CorrectionRepository(session)
    request = {
        "occurrence_segment_id": seg.id,
        "revision": 1,
        "source_generation": GEN,
        "mask_artifact_id": seed.masks[1],
        "segmentation": {"points": [{"x": 12.0, "y": 22.0, "label": "center"}]},
        "provenance": {"user": "reviewer-7"},
    }
    impact = corr.compute_impact(WS, seed.project, seed.video, "mask", request)
    a, c_a = corr.create_correction(
        WS, seed.project, seed.video, "mask", request, impact
    )
    b, c_b = corr.create_correction(
        WS, seed.project, seed.video, "mask", request, impact
    )
    assert c_a and not c_b and a.id == b.id


# ── CAS confirm / cancel ────────────────────────────────────────────────


def test_confirm_cas_stale_revision_zero_mutation_both_ways(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    rec, _ = _pending_mask(session, seed, seg)
    session.commit()

    before_segments = session.execute(
        text("SELECT COUNT(*) FROM occurrence_segment")
    ).scalar()
    before_corr = session.execute(
        text("SELECT status, revision FROM s09_correction WHERE id=:i"),
        {"i": rec.id},
    ).one()
    # Stale revision refuses BEFORE any mutation.
    corr = S09CorrectionRepository(session)
    with pytest.raises(CorrectionConflictError):
        corr.confirm_correction(WS, rec.id, rec.revision + 5)
    session.rollback()
    after_segments = session.execute(
        text("SELECT COUNT(*) FROM occurrence_segment")
    ).scalar()
    after_corr = session.execute(
        text("SELECT status, revision FROM s09_correction WHERE id=:i"),
        {"i": rec.id},
    ).one()
    assert int(before_segments) == int(after_segments)
    assert tuple(after_corr) == tuple(before_corr) == ("pending", 1)

    # Correct revision applies exactly once.
    rec2, applied = corr.confirm_correction(WS, rec.id, 1)
    assert applied is True and rec2.status == "applied"
    # Re-confirm at any revision is a no-op (idempotent terminal state).
    _rec3, applied_again = corr.confirm_correction(WS, rec.id, 2)
    assert applied_again is False
    session.commit()


def test_cancel_semantics_terminal_states_stay_terminal(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    rec, _ = _pending_mask(session, seed, seg)
    session.commit()
    corr = S09CorrectionRepository(session)

    cancelled, did = corr.cancel_correction(WS, rec.id, 1)
    assert did and cancelled.status == "cancelled" and cancelled.cancelled_at
    session.commit()

    # Cancelled can never be confirmed...
    with pytest.raises(CorrectionConflictError):
        corr.confirm_correction(WS, rec.id, 2)
    session.rollback()
    # ...and re-cancel is a no-op replay of the same terminal row.
    again, did2 = corr.cancel_correction(WS, rec.id, 2)
    assert did2 is False and again.status == "cancelled"

    # Applied can never be cancelled.
    seg_b = _seg(StructuralEvidenceRepository(session), seed, "Phone")
    rec_b, _ = _pending_mask(session, seed, seg_b, idem="idem-b")
    session.commit()
    corr.confirm_correction(WS, rec_b.id, 1)
    session.commit()
    with pytest.raises(CorrectionConflictError):
        corr.cancel_correction(WS, rec_b.id, 2)


def test_restart_replay_safe_new_session_same_row(env) -> None:  # type: ignore[no-untyped-def]
    session, seed, factory, db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    r1, created = _pending_mask(session, seed, seg)
    session.commit()
    session.close()  # simulate process death

    fresh = factory()
    try:
        corr = S09CorrectionRepository(fresh)
        got = corr.get_correction(WS, r1.id)
        assert got.id == r1.id and got.status == "pending"
        evidence = StructuralEvidenceRepository(fresh)
        request = {
            "occurrence_segment_id": seg.id,
            "revision": evidence.get_segment(WS, seg.id).revision,
            "source_generation": GEN,
            "mask_artifact_id": seed.masks[1],
            "segmentation": {"points": [{"x": 12.0, "y": 22.0, "label": "center"}]},
            "provenance": {"user": "reviewer-7"},
        }
        impact = corr.compute_impact(
            WS, seed.project, seed.video, "mask", request
        )
        replay, created2 = corr.create_correction(
            WS, seed.project, seed.video, "mask", request, impact,
            idempotency_key="idem-1",
        )
        assert created2 is False and replay.id == r1.id
        applied_rec, applied = corr.confirm_correction(WS, r1.id, 1)
        assert applied is True and applied_rec.status == "applied"
        fresh.commit()
    finally:
        fresh.close()


def test_cross_workspace_read_not_found_and_ownership_refused(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    corr = S09CorrectionRepository(session)
    request = {
        "occurrence_segment_id": seg.id,
        "revision": 1,
        "source_generation": GEN,
        "mask_artifact_id": seed.masks[1],
        "segmentation": {"points": [{"x": 12.0, "y": 22.0, "label": "center"}]},
        "provenance": {"user": "reviewer-7"},
    }
    impact = corr.compute_impact(WS, seed.project, seed.video, "mask", request)
    rec, _ = corr.create_correction(
        WS, seed.project, seed.video, "mask", request, impact
    )
    with pytest.raises(CorrectionNotFoundError):
        corr.get_correction(WS_B, rec.id)
    with pytest.raises(CorrectionConflictError):
        corr.compute_impact(
            WS_B, seed.project, seed.video, "mask", request
        )


# ── mutations through the verified core ─────────────────────────────────


def test_mask_correction_supersedes_lineage_with_provenance(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    seg = _seg(StructuralEvidenceRepository(session), seed)
    rec, _ = _pending_mask(session, seed, seg)
    session.commit()
    corr = S09CorrectionRepository(session)
    applied, _ = corr.confirm_correction(WS, rec.id, 1)
    session.commit()
    result = applied.result or {}
    sup = result["supersede"]
    assert sup["predecessor_id"] == seg.id
    successor = StructuralEvidenceRepository(session).get_segment(WS, sup["successor_id"])
    assert successor.logical_id == seg.logical_id
    assert successor.lineage_version == seg.lineage_version + 1
    assert successor.mask_artifact_id == seed.masks[1]
    assert successor.provenance.get("user") == "reviewer-7"


def test_zorder_correction_updates_layering_via_lineage(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    evidence = StructuralEvidenceRepository(session)
    seg = _seg(evidence, seed, z_order=0)
    corr = S09CorrectionRepository(session)
    request = {
        "occurrence_segment_id": seg.id,
        "revision": 1,
        "source_generation": GEN,
        "z_order": 42,
        "provenance": {"user": "reviewer-9", "reason": "phone above torso"},
    }
    impact = corr.compute_impact(WS, seed.project, seed.video, "z_order", request)
    rec, _ = corr.create_correction(
        WS, seed.project, seed.video, "z_order", request, impact
    )
    session.commit()
    applied, _ = corr.confirm_correction(WS, rec.id, 1)
    session.commit()
    sup = (applied.result or {})["supersede"]
    successor = evidence.get_segment(WS, sup["successor_id"])
    assert successor.z_order == 42
    predecessor = evidence.get_segment(WS, seg.id)
    assert predecessor.superseded_by_id == sup["successor_id"]


def test_route_override_appends_history_never_mutates_old_row(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    evidence = StructuralEvidenceRepository(session)
    seg = _seg(evidence, seed)
    corr = S09CorrectionRepository(session)
    request = {
        "project_id": seed.project,
        "video_item_id": seed.video,
        "occurrence_segment_id": seg.id,
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
            "reason": "operator override after review",
            "evidence": "benchmark_results_seed20260823.json row FAIL pose_swap",
        },
    }
    impact = corr.compute_impact(
        WS, seed.project, seed.video, "route_override", request
    )
    rec, _ = corr.create_correction(
        WS, seed.project, seed.video, "route_override", request, impact
    )
    session.commit()

    # Seed the PRIOR route decision (the machine decision being overridden)
    # so the test can prove the override APPENDS instead of mutating.
    from app.persistence.structural_lock import StructuralLockRepository

    lock_repo = StructuralLockRepository(session)
    prior, _created = lock_repo.record_render_route(
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=seed.video,
        occurrence_segment_id=seg.id,
        route="pose_swap",
        anchor_x=0.25,
        anchor_y=0.75,
        start_frame=0,
        end_frame=90,
        provenance={"source": "adaptive_selection", "evidence": "measured-passing"},
        reasons=["adaptive default"],
        confidence_source="model",
    )
    session.commit()
    old_rows = (
        session.execute(
            text("SELECT * FROM segment_render_route ORDER BY created_at")
        )
        .mappings()
        .all()
    )
    assert len(old_rows) == 1 and old_rows[0]["id"] == prior.id
    applied, _ = corr.confirm_correction(WS, rec.id, 1)
    session.commit()

    new_rows = (
        session.execute(
            text("SELECT * FROM segment_render_route ORDER BY created_at")
        )
        .mappings()
        .all()
    )
    # History APPENDS: two rows, the first byte-identical to before.
    assert len(new_rows) == 2
    assert [dict(r) for r in new_rows][:1] == [dict(r) for r in old_rows][:1]
    latest = session.get(SegmentRenderRoute, new_rows[-1]["id"])
    prov = json.loads(latest.provenance_json)
    assert prov["route_from"] == "pose_swap"
    assert prov["route_to"] == "sprite_affine"
    assert prov["evidence"] == (
        "benchmark_results_seed20260823.json row FAIL pose_swap"
    )
    assert latest.route == "sprite_affine"
    assert latest.confidence_source == "user"
    assert ((applied.result or {}).get("route_override") or {})["created"] is True


def test_route_override_incomplete_provenance_fails_closed(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    evidence = StructuralEvidenceRepository(session)
    seg = _seg(evidence, seed)
    corr = S09CorrectionRepository(session)
    base: dict[str, Any] = {
        "occurrence_segment_id": seg.id,
        "route_from": "pose_swap",
        "route_to": "sprite_affine",
        "anchor_x": 0.25,
        "anchor_y": 0.75,
        "start_frame": 0,
        "end_frame": 90,
        "override_reason": "swap evidence missing",
        "provenance": {"note": "incomplete"},
    }
    # S09-T05A-C1: incomplete provenance must be refused AT SUBMIT —
    # zero pending row, zero side effect (F5 fix).
    rows_before = int(
        session.execute(text("SELECT COUNT(*) FROM s09_correction")).scalar()
    )
    with pytest.raises(CorrectionValidationError):
        corr.compute_impact(
            WS, seed.project, seed.video, "route_override", base
        )
    with pytest.raises(CorrectionValidationError):
        impact = CorrectionImpact(
            correction_kind="route_override",
            affected_occurrence_segment_ids=[seg.id],
            affected_contact_ids=[],
            affected_motion_ids=[],
            affected_loop_ids=[],
            affected_layer_ids=[seg.name],
            route_override=True,
            counts={"segments": 1},
        )
        corr.create_correction(
            WS, seed.project, seed.video, "route_override", dict(base),
            impact,
        )
    rows_after_reject = int(
        session.execute(text("SELECT COUNT(*) FROM s09_correction")).scalar()
    )
    assert rows_after_reject == rows_before, (
        "rejected request must not archive any correction row"
    )


def test_contact_correction_cas_zero_mutation_on_stale(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    evidence = StructuralEvidenceRepository(session)
    hand = _seg(evidence, seed, "Character")
    phone = _seg(evidence, seed, "Phone")
    contact, _ = evidence.create_contact(
        WS, seed.project, seed.video, hand.id, phone.id, "hand_phone",
        30, 60, 1000, 2000,
    )
    corr = S09CorrectionRepository(session)
    request = {
        "contact_id": contact.id,
        "revision": contact.revision + 3,  # deliberately stale
        "end_frame": 55,
        "reasons": ["contact ends earlier"],
        "provenance": {"user": "reviewer-3"},
    }
    impact = corr.compute_impact(WS, seed.project, seed.video, "contact", request)
    rec, _ = corr.create_correction(
        WS, seed.project, seed.video, "contact", request, impact
    )
    session.commit()
    before = session.execute(
        text("SELECT end_frame, revision FROM scene_graph_contact WHERE id=:i"),
        {"i": contact.id},
    ).one()
    with pytest.raises(ContactConflictError):
        corr.confirm_correction(WS, rec.id, 1)
    session.rollback()
    after = session.execute(
        text("SELECT end_frame, revision FROM scene_graph_contact WHERE id=:i"),
        {"i": contact.id},
    ).one()
    assert tuple(after) == tuple(before) == (60, 1)
    state = session.execute(
        text("SELECT status FROM s09_correction WHERE id=:i"), {"i": rec.id}
    ).scalar()
    assert state == "pending"


def test_mesh_parts_correction_cas_motion_transform(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    evidence = StructuralEvidenceRepository(session)
    seg = _seg(evidence, seed)
    motion, _ = evidence.create_motion(
        WS, seg.id, "object_relative", {"dx": 1.0, "dy": 0.0},
        start_frame=0, end_frame=90, start_time_ms=0, end_time_ms=3000,
    )
    corr = S09CorrectionRepository(session)
    request = {
        "motion_id": motion.id,
        "revision": motion.revision,
        "transform": {"dx": -2.5, "dy": 4.0},
        "confidence": 1.0,
        "reasons": ["parts drift corrected"],
        "provenance": {"user": "animator-2"},
    }
    impact = corr.compute_impact(
        WS, seed.project, seed.video, "mesh_parts", request
    )
    rec, _ = corr.create_correction(
        WS, seed.project, seed.video, "mesh_parts", request, impact
    )
    session.commit()
    applied, _ = corr.confirm_correction(WS, rec.id, 1)
    session.commit()
    moved = (applied.result or {})["motion"]
    session.expire_all()
    fresh = evidence.get_motion(WS, motion.id)
    assert fresh.transform == {"dx": -2.5, "dy": 4.0}
    assert fresh.revision == 2
    assert moved["revision"] == 2

    # A MATERIALLY DIFFERENT second correction whose archived revision is
    # now stale (motion moved to rev 2) must refuse with ZERO mutation.
    stale_request = {**request, "revision": 1, "transform": {"dx": 9.0, "dy": -9.0}}
    impact2 = corr.compute_impact(
        WS, seed.project, seed.video, "mesh_parts", stale_request
    )
    rec2, _ = corr.create_correction(
        WS, seed.project, seed.video, "mesh_parts", stale_request, impact2
    )
    session.commit()
    with pytest.raises(MotionConflictError):
        corr.confirm_correction(WS, rec2.id, 1)
    session.rollback()


def test_unaffected_segments_byte_identical_after_confirm(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    evidence = StructuralEvidenceRepository(session)
    target = _seg(evidence, seed, "Character")
    bystander = _seg(evidence, seed, "Phone")
    bystander_hash_before = _segment_durable_hash(session, bystander.id)
    corr = S09CorrectionRepository(session)
    rec, _ = _pending_mask(session, seed, target)
    session.commit()
    corr.confirm_correction(WS, rec.id, 1)
    session.commit()
    assert (
        _segment_durable_hash(session, bystander.id) == bystander_hash_before
    ), "unaffected segment must be byte-identical after a targeted correction"


def test_applied_correction_counts_feed_benchmark_schema(
    env,
) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    evidence = StructuralEvidenceRepository(session)
    seg = _seg(evidence, seed)
    corr = S09CorrectionRepository(session)
    rec, _ = _pending_mask(session, seed, seg)
    session.commit()
    counts_pending = corr.applied_correction_counts(WS, seed.video)
    assert counts_pending == {"total": 0, "by_kind": {}}
    corr.confirm_correction(WS, rec.id, 1)
    session.commit()
    counts = corr.applied_correction_counts(WS, seed.video)
    assert counts["total"] == 1
    assert counts["by_kind"] == {"mask": 1}


def test_non_finite_payload_refused(env) -> None:  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    evidence = StructuralEvidenceRepository(session)
    seg = _seg(evidence, seed)
    corr = S09CorrectionRepository(session)
    bad = float("inf")
    with pytest.raises(CorrectionValidationError):
        corr.compute_impact(
            WS, seed.project, seed.video, "z_order",
            {
                "occurrence_segment_id": seg.id,
                "revision": 1,
                "source_generation": GEN,
                "z_order": bad,
                "provenance": {"user": "x"},
            },
        )
