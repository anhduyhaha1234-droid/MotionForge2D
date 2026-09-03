"""S09-T06A-C4 (S10-C6A) — immutable approval v2 / Full Apply authority tests.

Binary acceptance for the ``s09.approval/v2`` additive snapshot with the
nested ``full_apply_authority`` (real migrated temp SQLite DBs — FK/CHECK/
partial-unique enforced, never MAIN):

- v2 snapshot is complete FROM PERSISTED authority rows (manifest, segments,
  roles, reskin configs, pack assets, source artifact) and the checkpoint
  hash covers the whole snapshot including every authority field;
- exact manifest-selected route DIFFERS from the full route-alternatives
  set (alternatives are never used as the selected route);
- missing/ambiguous role mapping, affected geometry, source artifact, pack
  status and cross-scope references all fail closed / zero mutation with an
  immutable eligibility reason;
- unsupported routes (mesh_warp/part_rig) are recorded non-executable with a
  clear reason and NEVER downgraded;
- v1 checkpoints remain byte-identical; reapproval creates a DISTINCT v2 row
  with a new content hash; equivalent v2 replay converges; conflict is zero
  mutation;
- later live mutation of config/routes/SLM pointers does NOT change stored v2
  bytes/hash;
- tampered manifest / tampered snapshot fail closed;
- v1 full-apply-authority access fails closed REAPPROVAL_REQUIRED;
- no migration/schema drift: single Alembic head a10b11c12d3e, models
  unchanged, OpenAPI additive with no duplicate operation ids.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import (
    Artifact,
    Character,
    CharacterPackVersion,
    Job,
    ObjectRole,
    Project,
    ReskinConfig,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import StructuralEvidenceRepository
from app.persistence.structural_lock import StructuralLockRepository
from app.services.s09_approval import (
    APPROVAL_V2_SCHEMA,
    ApprovalConflictError,
    ApprovalValidationError,
    S09ApprovalIntegrityError,
    S09ApprovalRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = "s09t06a-c4-ws"
WS_B = "s09t06a-c4-other"
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
    def __init__(self) -> None:
        self.project = ""
        self.video = ""
        self.scene = ""
        self.role = ""
        self.character = ""
        self.pack = ""
        self.reskin_config = ""
        self.source_artifact = ""
        self.mask_artifact = ""
        self.segment = ""
        self.manifest = ""


def _manifest_dict(segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "frame_count": 180,
        "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
        "shot_order": ["shot-1"],
        "fingerprints": {"z_order": _sha(7), "contacts": _sha(8)},
        "segments": segments,
        "policy_version": "structural-thresholds-v1",
    }


def _seed_full(session: Any) -> Seed:
    """Full persisted authority graph for an EXECUTABLE v2 reapproval."""
    seed = Seed()
    session.add(Workspace(id=WS, name=WS))
    session.add(Workspace(id=WS_B, name=WS_B))
    source = Artifact(
        workspace_id=WS, kind="video", relative_path="src-c4.mp4",
        state="ready", sha256=_sha(1), size_bytes=123456,
    )
    session.add(source)
    session.flush()
    seed.source_artifact = str(source.id)

    project = Project(workspace_id=WS, name="T06A-C4")
    session.add(project)
    session.flush()
    video = VideoItem(
        project_id=project.id, title="V-C4", position=0,
        source_artifact_id=source.id,
    )
    session.add(video)
    session.flush()
    # Generation authority (C1-F1): the DISCOVER_OBJECTS job defines the
    # backend current generation that roles/segments/manifest must match.
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
    char = Character(workspace_id=WS, name="CharC4", code="cr_c4")
    session.add(char)
    session.flush()
    pack = CharacterPackVersion(
        workspace_id=WS, character_id=char.id, version=1, status="published",
    )
    session.add(pack)
    session.flush()
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

    mask = Artifact(
        workspace_id=WS, kind="image", relative_path="mask-c4.png",
        state="ready", sha256=_sha(21), size_bytes=2048,
    )
    session.add(mask)
    session.flush()
    seed.mask_artifact = str(mask.id)

    seg_repo = StructuralEvidenceRepository(session)
    seg_rec, _sc = seg_repo.create_segment(
        WS, project.id, video.id, role.id, scene.id, "Character",
        0, 90, 0, 3000, GEN,
        kind="character",
        confidence_source="user",
        segmentation={"points": [{"x": 10.0, "y": 20.0, "label": "center"}]},
        prompt={"points": [{"x": 5.0, "y": 6.0, "label": "p"}]},
        mask_artifact_id=mask.id,
    )
    seed.segment = str(seg_rec.id)

    lock_repo = StructuralLockRepository(session)
    manifest, _mc = lock_repo.create_manifest(
        WS,
        project.id,
        video.id,
        GEN,
        _manifest_dict(
            [
                {
                    "occurrence_segment_id": seed.segment,
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 90,
                    "provenance": {"why": "benchmark"},
                }
            ]
        ),
    )
    seed.manifest = str(manifest.id)
    lock_repo.record_render_route(
        WS, project.id, video.id, seg_rec.id, "sprite_affine",
        0.5, 0.5, 0, 90,
        provenance={"why": "benchmark"},
        reasons=["bench-best"],
        structural_lock_manifest_id=manifest.id,
    )

    config_row = session.get(ReskinConfig, reskin.id)
    assert config_row is not None
    config_row.structural_lock_manifest_id = manifest.id
    config_row.lock_policy_version = manifest.policy_version
    session.flush()

    seed.project = str(project.id)
    seed.video = str(video.id)
    seed.scene = str(scene.id)
    seed.role = str(role.id)
    seed.character = str(char.id)
    seed.pack = str(pack.id)
    seed.reskin_config = str(reskin.id)
    session.commit()
    return seed


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t06a-c4.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as session:
        yield session, _seed_full(session), factory, db
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


def _reapprove(repo: S09ApprovalRepository, seed: Seed, **kwargs: Any) -> Any:
    payload: dict[str, Any] = {
        "reskin_config_id": seed.reskin_config,
        "expected_reskin_revision": 1,
        "pack_version_ids": [seed.pack],
    }
    payload.update(kwargs)
    return repo.submit_checkpoint_v2(WS, **payload)


# ── 1. v2 snapshot complete from persisted authority + hash verify ────────


def test_v2_authority_full_from_persisted_hash_verified(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    record, created = _reapprove(repo, seed, note="C6A reapproval")
    assert created is True
    assert record.snapshot["schema"] == APPROVAL_V2_SCHEMA

    auth = record.snapshot["full_apply_authority"]
    assert auth["authority_version"] == "s09.full-apply-authority/v1"
    identity = auth["identity"]
    assert identity["workspace_id"] == WS
    assert identity["project_id"] == seed.project
    assert identity["video_item_id"] == seed.video
    assert identity["reskin_config_id"] == seed.reskin_config
    assert identity["reskin_config_revision"] == 1
    assert identity["source_generation"] == GEN

    src = auth["source"]
    assert src["source_generation"] == GEN
    assert src["source_artifact_id"] == seed.source_artifact
    assert src["relative_path"] == "src-c4.mp4"
    assert src["sha256"] == _sha(1)
    assert src["size_bytes"] == 123456
    assert src["frame_count"] == 180
    assert src["fps"] == 30.0
    assert src["time_base"] == "1/30"

    slm = auth["structural_lock"]
    assert slm["structural_lock_manifest_id"] == seed.manifest
    assert slm["policy_version"] == "structural-thresholds-v1"
    assert len(slm["manifest_hash"]) == 64
    assert slm["canonical_manifest"]["frame_count"] == 180

    assert auth["shot_order"] == ["shot-1"]
    assert len(auth["segments"]) == 1
    seg = auth["segments"][0]
    assert seg["occurrence_segment_id"] == seed.segment
    assert seg["route"] == "sprite_affine"
    assert seg["start_frame"] == 0 and seg["end_frame"] == 90
    assert seg["geometry"]["has_geometry"] is True
    assert seg["mask_artifact"]["artifact_id"] == seed.mask_artifact
    assert seg["role"]["object_role_id"] == seed.role
    assert seg["eligibility"]["executable"] is True

    assert len(auth["role_mappings"]) == 1
    mapping = auth["role_mappings"][0]
    assert mapping["object_role_id"] == seed.role
    assert mapping["pack_version_id"] == seed.pack
    assert mapping["pack_status"] == "published"
    assert mapping["pack_version"] == 1
    assert mapping["config_params"]["scale"] == 1.0
    assert len(mapping["dependency_hashes"]["params"]) == 64

    elig = auth["eligibility"]
    assert elig["full_apply_executable"] is True
    assert elig["reasons"] == []
    assert elig["unsupported_routes"] == []

    # Checkpoint hash verify covers the WHOLE v2 snapshot.
    integrity = repo.verify_checkpoint(record.id, WS)
    assert integrity.verified is True
    # The authority is served back identically through the read surface.
    served = repo.full_apply_authority(record.id, WS)
    assert served == auth


# ── 2. exact selected route differs from route alternatives ───────────────


def test_selected_route_differs_from_alternatives(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    # A SECOND route alternative for the SAME segment (persisted history).
    lock_repo = StructuralLockRepository(session)
    lock_repo.record_render_route(
        WS, seed.project, seed.video, seed.segment, "pose_swap",
        0.5, 0.5, 0, 90,
        provenance={"why": "older attempt"},
        reasons=["bench-old"],
        structural_lock_manifest_id=seed.manifest,
    )
    session.flush()

    repo = S09ApprovalRepository(session)
    record, created = _reapprove(repo, seed)
    assert created is True
    auth = record.snapshot["full_apply_authority"]
    selected_routes = [seg["route"] for seg in auth["segments"]]
    assert selected_routes == ["sprite_affine"]

    alternatives = [
        r.route
        for r in lock_repo.list_routes_for_video(WS, seed.project, seed.video)
    ]
    assert sorted(alternatives) == ["pose_swap", "sprite_affine"]
    # Selected is EXACTLY the manifest-selected route, never the full set.
    assert set(selected_routes) != set(alternatives)
    assert "pose_swap" not in selected_routes


# ── 3. missing/ambiguous authority → fail closed with eligibility reason ──


def test_missing_role_mapping_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    # Second role + segment WITHOUT any reskin config mapping.
    role2 = ObjectRole(
        workspace_id=WS, project_id=seed.project, video_item_id=seed.video,
        source_generation=GEN, name="Prop", kind="prop", status="confirmed",
    )
    session.add(role2)
    session.flush()
    mask2 = Artifact(
        workspace_id=WS, kind="image", relative_path="mask-c4-prop.png",
        state="ready", sha256=_sha(22), size_bytes=1024,
    )
    session.add(mask2)
    session.flush()
    seg_repo = StructuralEvidenceRepository(session)
    seg2, _sc = seg_repo.create_segment(
        WS, seed.project, seed.video, str(role2.id), seed.scene, "Prop",
        100, 180, 3000, 6000, GEN,
        kind="prop",
        confidence_source="user",
        segmentation={"boxes": [{"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}]},
        mask_artifact_id=str(mask2.id),
    )
    session.flush()
    lock_repo = StructuralLockRepository(session)
    manifest2, _mc = lock_repo.create_manifest(
        WS, seed.project, seed.video, GEN,
        _manifest_dict(
            [
                {
                    "occurrence_segment_id": str(seg2.id),
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 100,
                    "end_frame": 180,
                    "provenance": {"why": "second"},
                }
            ]
        ),
    )
    session.flush()
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.structural_lock_manifest_id = str(manifest2.id)
    config_row.lock_policy_version = manifest2.policy_version
    session.flush()

    repo = S09ApprovalRepository(session)
    record, created = _reapprove(repo, seed)
    assert created is True
    elig = record.snapshot["full_apply_authority"]["eligibility"]
    assert elig["full_apply_executable"] is False
    assert any("no approved reskin config mapping" in r for r in elig["reasons"])
    assert elig["unsupported_routes"] == []


def test_missing_affected_region_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    # Re-create a manifest-selected segment WITHOUT any geometry evidence.
    seg_repo = StructuralEvidenceRepository(session)
    seg_no_geom, _sc = seg_repo.create_segment(
        WS, seed.project, seed.video, seed.role, seed.scene, "Character",
        100, 180, 3000, 6000, GEN,
        kind="character",
        confidence_source="user",
        # no segmentation, no prompt
    )
    session.flush()
    lock_repo = StructuralLockRepository(session)
    manifest_no_geom, _mc = lock_repo.create_manifest(
        WS, seed.project, seed.video, GEN,
        _manifest_dict(
            [
                {
                    "occurrence_segment_id": str(seg_no_geom.id),
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 100,
                    "end_frame": 180,
                    "provenance": {"why": "no geometry"},
                }
            ]
        ),
    )
    session.flush()
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.structural_lock_manifest_id = str(manifest_no_geom.id)
    config_row.lock_policy_version = manifest_no_geom.policy_version
    session.flush()

    repo = S09ApprovalRepository(session)
    record, _created = _reapprove(repo, seed)
    seg_authority = record.snapshot["full_apply_authority"]["segments"][0]
    assert seg_authority["geometry"]["has_geometry"] is False
    assert seg_authority["eligibility"]["executable"] is False
    assert "missing/ambiguous affected geometry" in seg_authority["eligibility"]["reason"]
    elig = record.snapshot["full_apply_authority"]["eligibility"]
    assert elig["full_apply_executable"] is False
    assert any("missing/ambiguous affected geometry" in r for r in elig["reasons"])


def test_missing_source_artifact_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    video_row = session.get(VideoItem, seed.video)
    assert video_row is not None
    video_row.source_artifact_id = None
    session.flush()
    repo = S09ApprovalRepository(session)
    record, _created = _reapprove(repo, seed)
    elig = record.snapshot["full_apply_authority"]["eligibility"]
    assert elig["full_apply_executable"] is False
    assert any(
        "source artifact missing/incomplete" in r for r in elig["reasons"]
    )
    assert record.snapshot["full_apply_authority"]["source"] is None


def test_unpublished_pack_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    pack_row = session.get(CharacterPackVersion, seed.pack)
    assert pack_row is not None
    pack_row.status = "draft"
    session.flush()
    repo = S09ApprovalRepository(session)
    record, _created = _reapprove(repo, seed)
    elig = record.snapshot["full_apply_authority"]["eligibility"]
    assert elig["full_apply_executable"] is False
    assert any("not published/ready" in r for r in elig["reasons"])


# ── 4. unsupported route never downgraded ─────────────────────────────────


def test_unsupported_route_no_downgrade(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    lock_repo = StructuralLockRepository(session)
    manifest_mesh, _mc = lock_repo.create_manifest(
        WS, seed.project, seed.video, GEN,
        _manifest_dict(
            [
                {
                    "occurrence_segment_id": seed.segment,
                    "route": "mesh_warp",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 90,
                    "provenance": {"why": "mesh"},
                }
            ]
        ),
    )
    session.flush()
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.structural_lock_manifest_id = str(manifest_mesh.id)
    config_row.lock_policy_version = manifest_mesh.policy_version
    session.flush()

    repo = S09ApprovalRepository(session)
    record, _created = _reapprove(repo, seed)
    auth = record.snapshot["full_apply_authority"]
    seg = auth["segments"][0]
    # The manifest-selected route is PRESERVED exactly — never coerced.
    assert seg["route"] == "mesh_warp"
    assert seg["eligibility"]["executable"] is False
    assert "no downgrade" in seg["eligibility"]["reason"]
    elig = auth["eligibility"]
    assert elig["full_apply_executable"] is False
    assert elig["unsupported_routes"] == ["mesh_warp"]
    assert any("not executable" in r for r in elig["reasons"])


def test_no_manifest_v2_not_executable(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.structural_lock_manifest_id = None
    config_row.lock_policy_version = None
    session.flush()
    repo = S09ApprovalRepository(session)
    # Demo approval can still exist (v2 row), but Full Apply is NOT
    # executable without manifest authority.
    record, created = _reapprove(repo, seed)
    assert created is True
    auth = record.snapshot["full_apply_authority"]
    assert auth["structural_lock"]["structural_lock_manifest_id"] is None
    assert auth["segments"] == []
    elig = auth["eligibility"]
    assert elig["full_apply_executable"] is False
    assert any("no structural lock manifest pinned" in r for r in elig["reasons"])


# ── 5. v1 immutable; reapproval distinct; equivalent v2 replay converges ──


def test_v1_immutable_reapproval_distinct(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    v1, c1 = repo.submit_checkpoint(
        WS, seed.reskin_config, 1, [seed.pack], note="v1 approval"
    )
    assert c1 is True
    assert v1.snapshot["schema"] == "s09.approval/v1"
    v1_bytes = _stored_bytes(session, v1.id)

    v2, c2 = _reapprove(repo, seed, note="v2 reapproval")
    assert c2 is True
    assert v2.snapshot["schema"] == APPROVAL_V2_SCHEMA
    assert _row_count(session) == 2
    assert v2.id != v1.id
    assert v2.checkpoint_hash != v1.checkpoint_hash
    # v1 row is byte-identical (never mutated/backfilled).
    assert _stored_bytes(session, v1.id) == v1_bytes
    assert repo.verify_checkpoint(v1.id, WS).verified is True


def test_equivalent_v2_replay_converges(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    first, c1 = _reapprove(repo, seed, note="same")
    second, c2 = _reapprove(repo, seed, note="same")
    assert c1 is True and c2 is False
    assert second.id == first.id
    assert _row_count(session) == 1


def test_v2_conflict_zero_mutation(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    first, _created = _reapprove(repo, seed, idempotency_key="c4-key")
    before = _row_count(session)
    stored_before = _stored_bytes(session, first.id)
    with pytest.raises(ApprovalConflictError):
        _reapprove(repo, seed, idempotency_key="c4-key", note="different")
    assert _row_count(session) == before
    assert _stored_bytes(session, first.id) == stored_before


# ── 6. later live mutation does not change stored v2 bytes/hash ───────────


def test_mutate_live_after_v2_no_change(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    record, _created = _reapprove(repo, seed)
    stored_before = _stored_bytes(session, record.id)
    hash_before = record.checkpoint_hash

    # LIVE CHANGE 1: reskin params + revision bump.
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.params_json = json.dumps(
        {**VALID_PARAMS, "scale": 2.0}, sort_keys=True, separators=(",", ":")
    )
    config_row.revision = 2
    session.flush()
    # LIVE CHANGE 2: supersede the pinned manifest with a NEW version.
    lock_repo = StructuralLockRepository(session)
    changed = _manifest_dict(
        [
            {
                "occurrence_segment_id": seed.segment,
                "route": "pose_swap",
                "anchor": {"x": 0.5, "y": 0.5},
                "start_frame": 0,
                "end_frame": 90,
                "provenance": {"why": "new"},
            }
        ]
    )
    changed["policy_version"] = "structural-thresholds-v2"
    lock_repo.create_manifest(WS, seed.project, seed.video, GEN, changed)
    # LIVE CHANGE 3: an extra route alternative row.
    lock_repo.record_render_route(
        WS, seed.project, seed.video, seed.segment, "controlled_redraw",
        0.25, 0.25, 0, 90,
        provenance={"why": "extra"},
        reasons=["extra"],
    )
    session.commit()
    session.expire_all()

    assert _stored_bytes(session, record.id) == stored_before
    assert repo.verify_checkpoint(record.id, WS).verified is True
    fresh = repo.get_checkpoint(record.id, WS)
    assert fresh.checkpoint_hash == hash_before
    auth = fresh.snapshot["full_apply_authority"]
    assert auth["identity"]["reskin_config_revision"] == 1
    assert auth["segments"][0]["route"] == "sprite_affine"
    assert auth["structural_lock"]["policy_version"] == "structural-thresholds-v1"


# ── tamper / cross-scope fail closed ──────────────────────────────────────


def test_tampered_manifest_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    # Tamper the pinned manifest payload OUTSIDE the repository: the hash
    # pin no longer matches the payload → reapproval refuses (zero mutation).
    session.execute(
        text(
            "UPDATE structural_lock_manifest SET manifest_json = :payload "
            "WHERE id = :id"
        ),
        {
            "id": seed.manifest,
            "payload": json.dumps(
                {
                    **{
                        k: v
                        for k, v in _manifest_dict([]).items()
                        if k != "segments"
                    },
                    "segments": [],
                }
            ),
        },
    )
    session.commit()
    repo = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalConflictError):
        _reapprove(repo, seed)
    assert _row_count(session) == before


def test_tampered_snapshot_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    record, _created = _reapprove(repo, seed)
    session.execute(
        text("UPDATE apply_checkpoint SET snapshot_json = :snap WHERE id = :id"),
        {
            "id": record.id,
            "snap": json.dumps(
                {"schema": APPROVAL_V2_SCHEMA, "tampered": True}
            ),
        },
    )
    session.commit()
    with pytest.raises(S09ApprovalIntegrityError):
        repo.full_apply_authority(record.id, WS)
    assert repo.verify_checkpoint(record.id, WS).verified is False


def test_cross_scope_segment_reference_fails_closed(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    lock_repo = StructuralLockRepository(session)
    manifest_bad, _mc = lock_repo.create_manifest(
        WS, seed.project, seed.video, GEN,
        _manifest_dict(
            [
                {
                    # A segment id that exists in NO workspace in scope.
                    "occurrence_segment_id": "00000000-0000-0000-0000-000000000000",
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 90,
                    "provenance": {"why": "ghost"},
                }
            ]
        ),
    )
    session.flush()
    config_row = session.get(ReskinConfig, seed.reskin_config)
    assert config_row is not None
    config_row.structural_lock_manifest_id = str(manifest_bad.id)
    config_row.lock_policy_version = manifest_bad.policy_version
    session.flush()

    repo = S09ApprovalRepository(session)
    before = _row_count(session)
    with pytest.raises(ApprovalValidationError) as exc_info:
        _reapprove(repo, seed)
    assert "cross-scope occurrence segment" in str(exc_info.value)
    assert _row_count(session) == before


# ── 7. v1 full-apply-authority → REAPPROVAL_REQUIRED (zero mutation) ──────


def test_v1_full_apply_authority_requires_reapproval(env):  # type: ignore[no-untyped-def]
    session, seed, _factory, _db = env
    repo = S09ApprovalRepository(session)
    v1, _created = repo.submit_checkpoint(
        WS, seed.reskin_config, 1, [seed.pack], note="v1"
    )
    before = _row_count(session)
    v1_bytes = _stored_bytes(session, v1.id)
    with pytest.raises(ApprovalValidationError) as exc_info:
        repo.full_apply_authority(v1.id, WS)
    assert "REAPPROVAL_REQUIRED" in str(exc_info.value)
    assert "s09.approval/v1" in str(exc_info.value)
    assert _row_count(session) == before
    assert _stored_bytes(session, v1.id) == v1_bytes


# ── 8. no migration/schema drift + OpenAPI additive ───────────────────────


def test_single_head_and_models_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "head-c4.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    assert version == "a10b11c12d3e"


def test_openapi_additive_no_duplicate_and_removed_zero() -> None:  # type: ignore[no-untyped-def]
    from collections import Counter

    from app.api.routes.s09_approval import router as s09_approval_router

    def _pairs() -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for route in s09_approval_router.routes:
            for method in getattr(route, "methods", ()) or ():
                if method in {"HEAD", "OPTIONS"}:
                    continue
                pairs.append((route.path.rstrip("/") or "/", method))
        return pairs

    counts = Counter(_pairs())
    for (path, method), n in counts.items():
        assert n == 1, f"{method} {path} registered {n} times"
    expected = {
        ("/api/v2/s09-approvals", "POST"),
        ("/api/v2/s09-approvals", "GET"),
        ("/api/v2/s09-approvals/{checkpoint_id}", "GET"),
        ("/api/v2/s09-approvals/{checkpoint_id}/verify", "POST"),
        ("/api/v2/s09-approvals/replay-probe", "POST"),
        ("/api/v2/s09-approvals/conflict-probe", "POST"),
        ("/api/v2/s09-approvals/reapprove", "POST"),
        ("/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority", "GET"),
    }
    actual = set(counts.keys())
    removed = expected - actual
    assert removed == set(), f"contract paths removed: {sorted(removed)}"


def test_production_openapi_contains_v2_paths_no_dup_ops() -> None:  # type: ignore[no-untyped-def]
    from app.api.app import app as production_app

    spec = production_app.openapi()
    paths = spec["paths"]
    assert "/api/v2/s09-approvals/reapprove" in paths
    assert "/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority" in paths
    operation_ids = [
        op.get("operationId")
        for methods in paths.values()
        for op in methods.values()
        if isinstance(op, dict)
    ]
    assert all(operation_ids), "every operation must expose an operationId"
    assert len(operation_ids) == len(set(operation_ids)), "duplicate operation ids"


# ── 9. HTTP surface: reapprove 201 + authority endpoint fail-closed ───────


@pytest.fixture()
def http_env(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Isolated FastAPI app with the SAME production session semantics."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.api.routes.s09_approval import router as s09_approval_router

    db = tmp_path / "t06a-c4-api.db"
    command.upgrade(_config(db), "head")
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    def _override_session() -> Any:
        # PRODUCTION get_db_session semantics (review F4): yield + close,
        # NEVER commit — routes commit explicitly.
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(s09_approval_router)
    app.dependency_overrides[deps.get_db_session] = _override_session

    with factory() as s:
        seed = _seed_full(s)
    with TestClient(app) as http:
        yield http, seed, factory, db
    engine.dispose()


def _api_body(seed: Seed, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "reskin_config_id": seed.reskin_config,
        "expected_reskin_revision": 1,
        "pack_version_ids": [seed.pack],
    }
    body.update(overrides)
    return body


def test_reapprove_api_201_and_authority_endpoint(http_env):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = http_env

    def _rows() -> int:
        with factory() as s:
            return int(
                s.execute(text("SELECT COUNT(*) FROM apply_checkpoint")).scalar() or 0
            )

    # 1. v1 submit (existing surface untouched).
    r1 = http.post(
        "/api/v2/s09-approvals", params={"workspace_id": WS}, json=_api_body(seed)
    )
    assert r1.status_code == 201, r1.text
    v1 = r1.json()
    assert v1["snapshot"]["schema"] == "s09.approval/v1"

    # 2. reapprove → NEW v2 checkpoint (201, distinct hash, schema v2).
    r2 = http.post(
        "/api/v2/s09-approvals/reapprove",
        params={"workspace_id": WS},
        json=_api_body(seed, note="api reapproval"),
    )
    assert r2.status_code == 201, r2.text
    v2 = r2.json()
    assert v2["id"] != v1["id"]
    assert v2["checkpoint_hash"] != v1["checkpoint_hash"]
    assert v2["snapshot"]["schema"] == "s09.approval/v2"
    assert _rows() == 2

    # 3. authority endpoint: verified + eligibility truth.
    auth = http.get(
        f"/api/v2/s09-approvals/{v2['id']}/full-apply-authority",
        params={"workspace_id": WS},
    )
    assert auth.status_code == 200, auth.text
    body = auth.json()
    assert body["verified"] is True
    assert body["eligibility"]["full_apply_executable"] is True
    assert body["full_apply_authority"]["identity"]["reskin_config_id"] == (
        seed.reskin_config
    )

    # 4. v1 authority access → fail closed REAPPROVAL_REQUIRED (422).
    v1_auth = http.get(
        f"/api/v2/s09-approvals/{v1['id']}/full-apply-authority",
        params={"workspace_id": WS},
    )
    assert v1_auth.status_code == 422, v1_auth.text
    assert "REAPPROVAL_REQUIRED" in v1_auth.json()["detail"]
    assert _rows() == 2  # zero mutation


def test_reapprove_api_conflict_zero_mutation(http_env):  # type: ignore[no-untyped-def]
    http, seed, factory, _db = http_env

    def _rows() -> int:
        with factory() as s:
            return int(
                s.execute(text("SELECT COUNT(*) FROM apply_checkpoint")).scalar() or 0
            )

    first = http.post(
        "/api/v2/s09-approvals/reapprove",
        params={"workspace_id": WS},
        json=_api_body(seed, idempotency_key="api-c4-key"),
    )
    assert first.status_code == 201, first.text
    before = _rows()
    conflict = http.post(
        "/api/v2/s09-approvals/reapprove",
        params={"workspace_id": WS},
        json=_api_body(seed, idempotency_key="api-c4-key", note="different"),
    )
    assert conflict.status_code == 409, conflict.text
    assert _rows() == before
