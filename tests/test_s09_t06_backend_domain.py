"""S09-T06A domain tests — immutable approval/checkpoint repository.

Binary acceptance coverage per TASK.md (real migrated temp SQLite DBs —
FK/CHECK/partial-unique enforced, never MAIN):

- blockers fail-closed: pending/cancelled correction refs refuse the
  approval with ZERO durable mutation; unknown refs 404-semantics refuse;
- overrides are explicit-only: an override without matching applied
  correction evidence blocks (no implicit accept);
- warnings/overrides are hashed INTO the checkpoint (explicit opt-in);
- equivalent replay idempotent: same payload → SAME row, created=False,
  row count unchanged; materially different payload under the same
  idempotency key → conflict, zero mutation;
- conflict zero mutation BOTH directions: direction A (different content
  under existing key) and direction B (conflict-probe raises; row count
  and stored bytes identical afterwards);
- checkpoint hash verify pass/fail correct: verify_checkpoint → verified;
  a hand-tampered snapshot_json → NOT verified (and serving the record
  raises S09ApprovalIntegrityError); restoring the bytes restores pass;
- later-source-change does not mutate: after approval, updating the
  reskin config (params + revision CAS bump) and superseding the pinned
  manifest leaves the stored row byte-identical and hash still verified.
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
    Character,
    CharacterPackVersion,
    Job,
    ObjectRole,
    Project,
    ReskinConfig,
    S09Correction,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import StructuralEvidenceRepository
from app.persistence.structural_lock import StructuralLockRepository
from app.services.s09_approval import (
    ApprovalBlockedError,
    ApprovalConflictError,
    ApprovalNotFoundError,
    ApprovalValidationError,
    S09ApprovalIntegrityError,
    S09ApprovalRepository,
)
from app.services.s09_correction import CorrectionImpact, S09CorrectionRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = "s09t06a-ws"
WS_B = "s09t06a-ws-other"
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
    def __init__(self, session: Any) -> None:
        self.session = session
        self.project = ""
        self.video = ""
        self.scene = ""
        self.role = ""
        self.character = ""
        self.pack_version = ""
        self.reskin_config = ""


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
    project = Project(workspace_id=WS, name="T06A")
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
    role = ObjectRole(
        workspace_id=WS, project_id=project.id, video_item_id=video.id,
        source_generation=GEN, name="Character", kind="character",
        status="confirmed",
    )
    session.add(role)
    session.flush()
    seed.role = role.id

    char = Character(workspace_id=WS, name="CharT06A", code="cr_t06a")
    session.add(char)
    session.flush()
    seed.character = char.id
    pack = CharacterPackVersion(
        workspace_id=WS, character_id=char.id, version=1, status="published",
    )
    session.add(pack)
    session.flush()
    seed.pack_version = pack.id

    # Second workspace graph for isolation tests (own artifact).
    other_source = Artifact(
        workspace_id=WS_B, kind="video", relative_path="other.mp4",
        state="ready", sha256=_sha(50),
    )
    session.add(other_source)

    reskin = ReskinConfig(
        workspace_id=WS,
        project_id=project.id,
        object_role_id=role.id,
        character_id=char.id,
        pack_version_id=pack.id,
        params_json=json.dumps(VALID_PARAMS, sort_keys=True, separators=(",", ":")),
    )
    session.add(reskin)
    session.flush()
    seed.reskin_config = reskin.id

    seed.project = project.id
    seed.video = video.id
    seed.scene = scene.id
    session.commit()
    return seed


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t06a.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as session:
        yield session, _seed(session), factory, db
    create_engine_for_path(db).dispose()


def _row_count(session: Any) -> int:
    return int(
        session.execute(text("SELECT COUNT(*) FROM apply_checkpoint")).scalar() or 0
    )


def _stored_bytes(session: Any, checkpoint_id: str) -> str:
    row = session.execute(
        text(
            "SELECT snapshot_json || '|' || checkpoint_hash || '|' || "
            "CAST(revision AS TEXT) FROM apply_checkpoint WHERE id = :id"
        ),
        {"id": checkpoint_id},
    ).scalar()
    assert isinstance(row, str)
    return row


def _submit(repo: S09ApprovalRepository, seed: Seed, **kwargs: Any) -> Any:
    payload: dict[str, Any] = {
        "reskin_config_id": seed.reskin_config,
        "expected_reskin_revision": 1,
        "pack_version_ids": [seed.pack_version],
    }
    payload.update(kwargs)
    return repo.submit_checkpoint(WS, **payload)


# ── happy path + immutability of shape ───────────────────────────────────


def test_submit_freezes_full_snapshot(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    record, created = _submit(
        repo,
        seed,
        accepted_warnings=["low_confidence_mask"],
        note="approved by PM",
    )
    assert created is True
    assert record.reskin_config_revision == 1
    assert record.pack_version_ids == [seed.pack_version]
    snap = record.snapshot
    assert snap["schema"] == "s09.approval/v1"
    assert snap["warnings_accepted"] == ["low_confidence_mask"]
    assert snap["overrides"] == []
    assert snap["demo_artifact_refs"] == []
    assert snap["correction_history_refs"] == []
    policy = snap["compatibility_policy"]
    assert policy["policy_version"] is None  # no manifest pinned on config
    assert policy["renderer_routes_per_segment"] == []
    integrity = repo.verify_checkpoint(record.id, WS)
    assert integrity.verified is True


# ── blockers fail closed ─────────────────────────────────────────────────


def test_pending_correction_blocks_zero_mutation(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    corr_repo = S09CorrectionRepository(session)
    impact = CorrectionImpact(
        correction_kind="z_order",
        affected_occurrence_segment_ids=[],
        affected_contact_ids=[],
        affected_motion_ids=[],
        affected_loop_ids=[],
        affected_layer_ids=[],
        route_override=False,
        counts={},
    )
    # A REAL segment row first (s09_correction carries an FK to it).
    seg_repo = StructuralEvidenceRepository(session)
    mask = Artifact(
        workspace_id=WS, kind="image", relative_path="mask-pending.png",
        state="ready", sha256=_sha(31),
    )
    session.add(mask)
    session.flush()
    seg_rec, _sc = seg_repo.create_segment(
        WS, seed.project, seed.video, seed.role, seed.scene, "Character",
        0, 90, 0, 3000, GEN,
        confidence_source="user",
        segmentation={"points": [{"x": 1.0, "y": 2.0, "label": "c"}]},
        mask_artifact_id=mask.id,
    )
    corr_repo.create_correction(
        WS,
        seed.project,
        seed.video,
        "z_order",
        {
            "occurrence_segment_id": seg_rec.id,
            "revision": 1,
            "source_generation": GEN,
            "z_order": 2,
            "confidence_source": "manual",
            "provenance": {"reasons": ["user asked"]},
        },
        impact,
    )
    pending_row = session.query(S09Correction).first()
    assert pending_row is not None and pending_row.status == "pending"
    before_count = _row_count(session)
    with pytest.raises(ApprovalBlockedError):
        _submit(repo, seed, correction_ids=[str(pending_row.id)])
    assert _row_count(session) == before_count  # ZERO mutation


def test_cancelled_correction_blocks(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    row = S09Correction(
        workspace_id=WS, project_id=seed.project, video_item_id=seed.video,
        correction_kind="z_order", status="cancelled",
        request_json=json.dumps({"z_order": 1}),
        impact_json=json.dumps({"loop_ids": [], "layer_ids": [], "segment_ids": []}),
    )
    session.add(row)
    session.flush()
    repo2 = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalBlockedError):
        _submit(repo2, seed, correction_ids=[str(row.id)])
    assert _row_count(session) == before


def test_applied_correction_allows_and_is_recorded(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    from app.persistence.models import S09Correction

    row = S09Correction(
        workspace_id=WS, project_id=seed.project, video_item_id=seed.video,
        correction_kind="z_order", status="applied",
        request_json=json.dumps({
            "occurrence_segment_id": "seg-1",
            "z_order": 3,
            "reasons": ["override-z"],
            "provenance": {"reasons": []},
        }),
        impact_json=json.dumps({"loop_ids": [], "layer_ids": [], "segment_ids": []}),
        result_json=json.dumps({"ok": True}),
    )
    session.add(row)
    session.flush()
    record, created = _submit(
        repo, seed, correction_ids=[str(row.id)], overrides=["override-z"]
    )
    assert created is True
    assert record.snapshot["correction_history_refs"] == [str(row.id)]
    assert record.snapshot["overrides"] == ["override-z"]


def test_override_without_explicit_evidence_blocks(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalBlockedError):
        _submit(repo, seed, overrides=["no-evidence"])
    assert _row_count(session) == before  # no implicit accept


# ── F3 P1: route-override evidence mirrors FE reasonsOf contract ─────────


def _applied_route_override_row(
    session: Any, seed: Seed, request_payload: dict[str, Any],
) -> Any:
    """Applied route-override correction carrying arbitrary request payload."""
    from app.persistence.models import S09Correction

    row = S09Correction(
        workspace_id=WS, project_id=seed.project, video_item_id=seed.video,
        correction_kind="route_override", status="applied",
        request_json=json.dumps(request_payload),
        impact_json=json.dumps({"loop_ids": [], "layer_ids": [], "segment_ids": []}),
        result_json=json.dumps({"ok": True}),
    )
    session.add(row)
    session.flush()
    return row


def test_override_matches_top_level_override_reason(env):  # type: ignore[no-untyped-def]
    """RouteOverrideCorrectionRequest.override_reason alone must satisfy."""
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    row = _applied_route_override_row(
        session, seed,
        {"z_order_delta": 1, "override_reason": "override-z",
         "provenance": {"operator": "pm"}},
    )
    record, created = _submit(
        repo, seed, correction_ids=[str(row.id)], overrides=["override-z"]
    )
    assert created is True
    assert record.snapshot["overrides"] == ["override-z"]


def test_override_matches_provenance_evidence_alone(env):  # type: ignore[no-untyped-def]
    """RouteOverrideProvenance.evidence alone must satisfy (FE mirror)."""
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    row = _applied_route_override_row(
        session, seed,
        {"z_order_delta": 2,
         "provenance": {"reasons": [], "evidence": "evidence-only"}},
    )
    record, created = _submit(
        repo, seed, correction_ids=[str(row.id)], overrides=["evidence-only"]
    )
    assert created is True
    assert record.snapshot["overrides"] == ["evidence-only"]


def test_override_with_unrelated_evidence_still_blocks(env):  # type: ignore[no-untyped-def]
    """A correction present but carrying UNRELATED evidence still refuses."""
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    row = _applied_route_override_row(
        session, seed,
        {"z_order_delta": 3, "override_reason": "different-override",
         "provenance": {"evidence": "different-evidence"}},
    )
    before = _row_count(session)
    with pytest.raises(ApprovalBlockedError):
        _submit(repo, seed, correction_ids=[str(row.id)], overrides=["override-z"])
    assert _row_count(session) == before


def test_unknown_correction_ref_not_found(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalNotFoundError):
        _submit(repo, seed, correction_ids=["00000000-0000-0000-0000-000000000001"])
    assert _row_count(session) == before


def test_cross_workspace_pack_refused(env):  # type: ignore[no-untyped-def]
    session, seed, factory, _db = env
    with factory() as s2:
        char = Character(workspace_id=WS_B, name="Other", code="cr_other")
        s2.add(char)
        s2.flush()
        pack_b_row = CharacterPackVersion(
            workspace_id=WS_B, character_id=char.id, version=1, status="published",
        )
        s2.add(pack_b_row)
        s2.flush()
        pack_b = str(pack_b_row.id)
        s2.commit()
    repo = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalNotFoundError):
        _submit(repo, seed, pack_version_ids=[pack_b])
    assert _row_count(session) == before


# ── replay idempotent + conflicts ────────────────────────────────────────


def test_equivalent_replay_returns_same_row(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    first, c1 = _submit(
        repo, seed,
        idempotency_key="replay-key-1",
        accepted_warnings=["low_confidence_mask"],
        note="approved by PM",
    )
    assert c1 is True
    second, c2 = _submit(
        repo, seed,
        idempotency_key="replay-key-1",
        accepted_warnings=["low_confidence_mask"],
        note="approved by PM",
    )
    # Equivalent replay → SAME row, created=False, count unchanged.
    assert c2 is False
    assert second.id == first.id
    assert second.checkpoint_hash == first.checkpoint_hash
    assert _row_count(session) == 1


def test_replay_with_different_content_conflicts(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    first, created = _submit(repo, seed, idempotency_key="k-diff")
    assert created is True
    before = _row_count(session)
    stored_before = _stored_bytes(session, first.id)
    with pytest.raises(ApprovalConflictError):
        _submit(repo, seed, idempotency_key="k-diff", note="different")
    assert _row_count(session) == before
    assert _stored_bytes(session, first.id) == stored_before


def test_natural_key_duplicate_converges_one_row(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    first, c1 = _submit(repo, seed, note="same")
    second, c2 = _submit(repo, seed, note="same")
    assert c1 is True and c2 is False
    assert second.id == first.id
    assert _row_count(session) == 1


def test_stale_reskin_revision_conflicts(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalConflictError):
        _submit(repo, seed, expected_reskin_revision=99)
    assert _row_count(session) == before


def test_direction_b_conflict_probe(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    first, _ = _submit(repo, seed, idempotency_key="probe-k")
    before = _row_count(session)
    stored_before = _stored_bytes(session, first.id)
    with pytest.raises(ApprovalConflictError):
        repo.conflict_probe(
            WS, "probe-k", seed.reskin_config, 999, [seed.pack_version],
        )
    with pytest.raises(ApprovalValidationError):
        # Equal payload must NOT be treated as conflict material.
        repo.conflict_probe(
            WS, "probe-k", seed.reskin_config, 1, [seed.pack_version],
        )
    assert _row_count(session) == before
    assert _stored_bytes(session, first.id) == stored_before


# ── hash verify pass/fail ────────────────────────────────────────────────


def test_hash_verify_pass_and_tamper_fail(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    repo = S09ApprovalRepository(session)
    record, created = _submit(repo, seed)
    assert created is True
    assert repo.verify_checkpoint(record.id, WS).verified is True

    # Hand-tamper the durable snapshot OUTSIDE the repository (simulates
    # storage corruption / manual edit) → hash mismatch fail-closed.
    session.execute(
        text(
            "UPDATE apply_checkpoint SET snapshot_json = :snap WHERE id = :id"
        ),
        {
            "id": record.id,
            "snap": json.dumps({"schema": "s09.approval/v1", "tampered": True}),
        },
    )
    session.commit()
    integrity = repo.verify_checkpoint(record.id, WS)
    assert integrity.verified is False
    assert "does not match" in integrity.reason
    with pytest.raises(S09ApprovalIntegrityError):
        repo.get_checkpoint(record.id, WS)


# ── later changes never mutate the checkpoint ────────────────────────────


def test_later_source_change_does_not_mutate(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, db = env
    repo = S09ApprovalRepository(session)

    # Pin a manifest + route evidence BEFORE approval.
    lock_repo = StructuralLockRepository(session)
    manifest_dict = {
        "frame_count": 180,
        "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
        "shot_order": ["shot-1"],
        "fingerprints": {"z_order": _sha(7), "contacts": _sha(8)},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }
    manifest, _mc = lock_repo.create_manifest(
        WS, seed.project, seed.video, GEN, manifest_dict
    )

    seg_repo = StructuralEvidenceRepository(session)
    mask = Artifact(
        workspace_id=WS, kind="image", relative_path="mask-t06a.png",
        state="ready", sha256=_sha(21),
    )
    session.add(mask)
    session.flush()
    seg_rec, _sc = seg_repo.create_segment(
        WS, seed.project, seed.video, seed.role, seed.scene, "Character",
        0, 90, 0, 3000, GEN,
        confidence_source="user",
        segmentation={"points": [{"x": 10.0, "y": 20.0, "label": "center"}]},
        mask_artifact_id=mask.id,
    )
    lock_repo.record_render_route(
        WS, seed.project, seed.video, seg_rec.id, "sprite_affine",
        0.5, 0.5, 0, 90,
        provenance={"why": "benchmark"},
        reasons=["bench-best"],
        structural_lock_manifest_id=manifest.id,
    )

    # Approve over the pinned config.
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.structural_lock_manifest_id = manifest.id
    config_row.lock_policy_version = manifest.policy_version
    session.flush()

    record, created = _submit(repo, seed)
    assert created is True
    assert record.structural_lock_manifest_id == manifest.id
    assert record.lock_policy_version == "structural-thresholds-v1"
    routes_in_snapshot = record.snapshot["compatibility_policy"][
        "renderer_routes_per_segment"
    ]
    assert len(routes_in_snapshot) == 1
    assert routes_in_snapshot[0]["route"] == "sprite_affine"

    stored_before = _stored_bytes(session, record.id)
    hash_before = record.checkpoint_hash

    # LATER CHANGE 1: update the reskin config params (revision CAS bump).
    config_row.params_json = json.dumps(
        {**VALID_PARAMS, "scale": 2.0}, sort_keys=True, separators=(",", ":")
    )
    config_row.revision = 2
    config_row.updated_at = config_row.updated_at  # unchanged semantics here
    session.flush()

    # LATER CHANGE 2: supersede the pinned manifest with a NEW version.
    changed = dict(manifest_dict)
    changed["policy_version"] = "structural-thresholds-v2"
    lock_repo.create_manifest(WS, seed.project, seed.video, GEN, changed)

    session.commit()
    session.expire_all()

    # The checkpoint row is BYTE-IDENTICAL and still hash-verifies.
    assert _stored_bytes(session, record.id) == stored_before
    after = repo.verify_checkpoint(record.id, WS)
    assert after.verified is True
    fresh = repo.get_checkpoint(record.id, WS)
    assert fresh.checkpoint_hash == hash_before
    # Frozen at approval time even though config + manifest changed after.
    assert fresh.reskin_config_revision == 1
    policy = fresh.snapshot["compatibility_policy"]
    assert policy["policy_version"] == "structural-thresholds-v1"


def test_workspace_isolation_both_directions(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    record, _created = _submit(repo, seed)
    with pytest.raises(ApprovalNotFoundError):
        repo.get_checkpoint(record.id, WS_B)
    assert repo.list_checkpoints(WS_B) == []
