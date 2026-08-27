"""S09-T01 Source-Locked domain tests — StructuralLockManifest pin on ReskinConfig.

TASK-SL outcome 1 (binary, fail-closed, zero mutation on every refusal):
1. Pin at create: manifest must exist in THIS workspace; hash integrity is
   re-verified against canonical_manifest_json + sha256; policy_version is
   DERIVED from the manifest (client-supplied lock_policy_version must match).
2. Cross-workspace manifest pin → ownership refusal, zero mutation.
3. Hash mismatch (tampered manifest_json) → conflict refusal, zero mutation.
4. Route enum: every pinned manifest segment route MUST be one of the exact
   five RENDERER_ROUTES (single authority) — anything else refused.
5. CAS update semantics: omitted → pin unchanged; explicit id → re-pin;
   "" sentinel → unpin (both columns cleared); wrong policy hint refused.
6. Evidence surface list_renderer_route_evidence: per-segment persisted
   SegmentRenderRoute rows for the pinned video — never an opaque score.

Runs on the isolated conftest client fixture DB only (never MAIN).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import RENDERER_ROUTES
from app.persistence.reskin_config import (
    ReskinConfigConflictError,
    ReskinConfigOwnershipError,
    ReskinConfigRepository,
)
from app.persistence.structural_lock import (
    StructuralLockRepository,
    canonical_manifest_json,
)

VALID_PARAMS = {
    "anchor": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "fit_mode": "contain",
    "clip_mode": "asset_alpha",
    "offset": {"x": 0.0, "y": 0.0},
    "rotation_offset_deg": 0.0,
    "opacity": 1.0,
}

WS_OTHER = "ws-sl-other"

#: Side-channel for ids created inside _seed_project (scene, foreign proj/vid).
_SL_EXTRA: dict[str, str] = {}


def _sf():
    svc = deps._job_service
    assert svc is not None
    return svc._session_factory()


def _manifest_payload(**overrides):
    payload = {
        "frame_count": 100,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }
    payload.update(overrides)
    return payload


def _seed_project(ws: str = DEFAULT_WORKSPACE_ID):
    """Project + video + scene + confirmed role + published complete pack."""
    with _sf() as s:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from app.persistence.models import (
            CORE_POSE_SLOTS,
            Artifact,
            Character,
            CharacterPackVersion,
            ObjectRole,
            Project,
            Scene,
            VideoItem,
            Workspace,
        )

        s.execute(
            sqlite_insert(Workspace)
            .values(id=ws, name=ws)
            .on_conflict_do_nothing(index_elements=[Workspace.id])
        )
        s.execute(
            sqlite_insert(Workspace)
            .values(id=WS_OTHER, name=WS_OTHER)
            .on_conflict_do_nothing(index_elements=[Workspace.id])
        )
        proj = Project(workspace_id=ws, name=f"SLProj-{uuid.uuid4().hex[:6]}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title="Vid", position=0)
        s.add(vid)
        s.flush()
        scene = Scene(
            video_item_id=vid.id,
            position=0,
            start_frame=0,
            end_frame=100,
            start_time_ms=0,
            end_time_ms=3000,
            status="pending",
        )
        s.add(scene)
        s.flush()
        role = ObjectRole(
            workspace_id=ws,
            project_id=proj.id,
            video_item_id=vid.id,
            source_generation="1",
            name="Hero",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=ws, name="CharSL", code=f"csl_{uuid.uuid4().hex[:6]}")
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(
            character_id=char.id, workspace_id=ws, version=1, status="published"
        )
        s.add(pv)
        s.flush()
        for slot in CORE_POSE_SLOTS:
            art = Artifact(
                workspace_id=ws,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="c" * 64,
            )
            s.add(art)
            s.flush()
            from app.persistence.models import CharacterAsset

            s.add(
                CharacterAsset(
                    pack_version_id=pv.id,
                    workspace_id=ws,
                    pose_slot=slot,
                    artifact_id=art.id,
                )
            )
        # A second workspace's project+video for cross-workspace refusals.
        proj_b = Project(workspace_id=WS_OTHER, name=f"OtherProj-{uuid.uuid4().hex[:4]}")
        s.add(proj_b)
        s.flush()
        vid_b = VideoItem(project_id=proj_b.id, title="VidB", position=0)
        s.add(vid_b)
        s.flush()
        s.commit()
        _SL_EXTRA.update(
            {
                "scene_id": scene.id,
                "foreign_proj": proj_b.id,
                "foreign_vid": vid_b.id,
            }
        )
        return proj.id, vid.id, role.id, char.id, pv.id


def _create_manifest(ws: str, project_id: str, video_id: str, **overrides):
    with _sf() as s:
        repo = StructuralLockRepository(s)
        record, _created = repo.create_manifest(
            ws, project_id, video_id, "g1", _manifest_payload(**overrides)
        )
        s.commit()
        return record


def _create_pinned_config(ws: str, proj: str, role: str, char: str, pv: str, manifest_id: str):
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        record, created = repo.create_config(
            ws, proj, role, char, pv, dict(VALID_PARAMS), None,
            structural_lock_manifest_id=manifest_id,
        )
        s.commit()
        assert created
        return record


# ── Outcome 2: happy-path pin derives policy_version ─────────────────────────


@pytest.fixture()
def _seed_sl_env(_patch_project_root: object):
    """Seed one project/video/role/char/published-complete-pack tuple."""
    return _seed_project()


def test_create_with_pin_derives_policy_version(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    manifest = _create_manifest(DEFAULT_WORKSPACE_ID, proj, vid)
    config = _create_pinned_config(
        DEFAULT_WORKSPACE_ID, proj, role, char, pv, manifest.id
    )
    assert config.structural_lock_manifest_id == manifest.id
    assert config.lock_policy_version == "structural-thresholds-v1"
    assert config.revision == 1


# ── Outcome 2: cross-workspace / unknown manifest refused ────────────────────


def test_pin_unknown_or_cross_workspace_refused(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    with _sf() as s:
        repo_b = StructuralLockRepository(s)
        other, _ = repo_b.create_manifest(
            WS_OTHER, _SL_EXTRA["foreign_proj"], _SL_EXTRA["foreign_vid"],
            "g1", _manifest_payload(),
        )
        s.commit()
        foreign_id = other.id

    session = _sf()
    try:
        repo = ReskinConfigRepository(session)
        with pytest.raises((ReskinConfigOwnershipError, ReskinConfigConflictError)):
            repo.create_config(
                DEFAULT_WORKSPACE_ID, proj, role, char, pv, dict(VALID_PARAMS),
                None, structural_lock_manifest_id=foreign_id,
            )
    finally:
        session.rollback()
        session.close()


# ── Outcome 2: hash mismatch (tampered stored manifest) refused ──────────────


def test_pin_tampered_manifest_hash_refused_zero_mutation(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    manifest = _create_manifest(DEFAULT_WORKSPACE_ID, proj, vid)
    ws = DEFAULT_WORKSPACE_ID
    # Tamper = flip ONE character inside the stored manifest_json while the
    # stored hash stays frozen: canonical re-validation still succeeds but the
    # recomputed sha256 no longer matches manifest_hash → hash-mismatch branch.
    with _sf() as s:
        from sqlalchemy import text as sqltext

        tampered = canonical_manifest_json(_manifest_payload(frame_count=101))
        s.execute(
            sqltext(
                "UPDATE structural_lock_manifest SET manifest_json=:j "
                "WHERE id=:i"
            ),
            {"j": tampered, "i": manifest.id},
        )
        s.commit()

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        before = len(repo.list_configs(ws)[0])
        with pytest.raises(ReskinConfigConflictError, match="hash mismatch"):
            repo.create_config(
                ws, proj, role, char, pv, dict(VALID_PARAMS),
                None, structural_lock_manifest_id=manifest.id,
            )
        s.rollback()
        assert len(repo.list_configs(ws)[0]) == before


# ── Outcome 2: voided manifest cannot back a live contract ───────────────────


def test_pin_voided_draft_manifest_refused(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = StructuralLockRepository(s)
        draft, _ = repo.create_manifest(
            ws, proj, vid, "g9", _manifest_payload(), activate=False
        )
        repo.void_manifest(draft.id, ws, 1)
        s.commit()
        voided_id = draft.id

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        with pytest.raises(ReskinConfigConflictError, match="voided"):
            repo.create_config(
                ws, proj, role, char, pv, dict(VALID_PARAMS),
                None, structural_lock_manifest_id=voided_id,
            )


# ── Outcome 2: route enum enforced over pinned segments ──────────────────────


def test_pin_manifest_route_enum_enforced(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    good = _manifest_payload(
        segments=[
            {
                "occurrence_segment_id": "sg-1",
                "route": RENDERER_ROUTES[1],
                "anchor": {"x": 0.25, "y": 0.75},
                "start_frame": 0,
                "end_frame": 50,
                "provenance": {},
            }
        ]
    )
    with _sf() as s:
        repo = StructuralLockRepository(s)
        rec, _ = repo.create_manifest(ws, proj, vid, "g1", good)
        s.commit()
        good_id = rec.id

    config = _create_pinned_config(ws, proj, role, char, pv, good_id)
    assert config.structural_lock_manifest_id == good_id

    bad = _manifest_payload(
        policy_version="other-policy-v2",
        segments=[
            {
                "occurrence_segment_id": "sg-b1",
                "route": "sprite_affine",
                "anchor": {"x": 0.5, "y": 0.5},
                "start_frame": 0,
                "end_frame": 10,
                "provenance": {},
            }
        ],
    )
    with _sf() as s:
        s_repo = StructuralLockRepository(s)
        bad_rec, _ = s_repo.create_manifest(ws, proj, vid, "g2", bad)
        s.commit()
        bad_id = bad_rec.id
        import json

        from sqlalchemy import text as sqltext

        # Tamper the STORED json: swap the route to a value outside the enum
        # while keeping the rest canonical — canonical_manifest_json cannot be
        # used here (it would refuse the payload at build time); raw dumps
        # simulates a corrupted/hand-edited row. _resolve_lock_pin must then
        # fail closed on the route-enum check, zero mutation.
        tampered_segments = [dict(bad["segments"][0])]
        tampered_segments[0]["route"] = "fabric_draw"
        s.execute(
            sqltext("UPDATE structural_lock_manifest SET manifest_json=:j WHERE id=:i"),
            {
                "j": json.dumps({**bad, "segments": tampered_segments}, sort_keys=True),
                "i": bad_id,
            },
        )
        s.commit()

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        with pytest.raises(ReskinConfigConflictError):
            repo.create_config(
                ws, proj, role, char, pv, dict(VALID_PARAMS),
                None, structural_lock_manifest_id=bad_id,
            )


# ── Outcome 3: CAS update pin semantics ──────────────────────────────────────


def test_update_pin_repin_unpin_and_keep(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    m1 = _create_manifest(ws, proj, vid)
    m2 = _create_manifest(ws, proj, vid, frame_count=120)
    config = _create_pinned_config(ws, proj, role, char, pv, m1.id)

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        # Params-only update keeps the pin.
        kept = repo.update_config(
            config.id, ws, expected_revision=1,
            params={**VALID_PARAMS, "scale": 1.25},
        )
        assert kept.structural_lock_manifest_id == m1.id
        assert kept.lock_policy_version == "structural-thresholds-v1"
        assert kept.revision == 2
        s.commit()

        # Re-pin to m2 (policy derived again).
        repinned = repo.update_config(
            config.id, ws, expected_revision=2,
            structural_lock_manifest_id=m2.id,
        )
        assert repinned.structural_lock_manifest_id == m2.id
        assert repinned.lock_policy_version == "structural-thresholds-v1"
        assert repinned.revision == 3
        s.commit()

        # Unpin via "" sentinel clears BOTH columns.
        unpinned = repo.update_config(
            config.id, ws, expected_revision=3,
            structural_lock_manifest_id="",
        )
        assert unpinned.structural_lock_manifest_id is None
        assert unpinned.lock_policy_version is None
        assert unpinned.revision == 4
        s.commit()

        # Re-pin after unpin works and bumps again.
        repin_again = repo.update_config(
            config.id, ws, expected_revision=4,
            structural_lock_manifest_id=m1.id,
        )
        assert repin_again.structural_lock_manifest_id == m1.id
        assert repin_again.revision == 5


# ── Outcome 4: evidence surface per segment (no opaque global score) ─────────


def test_renderer_route_evidence_per_segment(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        lock_repo = StructuralLockRepository(s)
        manifest, _ = lock_repo.create_manifest(
            ws, proj, vid, "g1",
            _manifest_payload(
                segments=[
                    {
                        "occurrence_segment_id": "sg-e1",
                        "route": "pose_swap",
                        "anchor": {"x": 0.5, "y": 0.25},
                        "start_frame": 0,
                        "end_frame": 40,
                        "provenance": {"residual": 0.11},
                    },
                    {
                        "occurrence_segment_id": "sg-e2",
                        "route": "controlled_redraw",
                        "anchor": {"x": 0.75, "y": 0.75},
                        "start_frame": 41,
                        "end_frame": 100,
                        "provenance": {"residual": 0.92},
                    },
                ]
            ),
        )
        # Persist the REAL occurrence segments first (FK ownership is
        # fail-closed in record_render_route). role_id must be the actual
        # seeded role id; scene from _SL_EXTRA.
        from sqlalchemy import text as sqltext

        for seg_id, lg, sf_, ef_ in (
            ("sg-e1", "lg-e1", 0, 40),
            ("sg-e2", "lg-e2", 41, 100),
        ):
            s.execute(
                sqltext(
                    "INSERT INTO occurrence_segment(id,workspace_id,project_id,video_item_id,"
                    "role_id,scene_id,logical_id,lineage_version,name,kind,start_frame,end_frame,"
                    "start_time_ms,end_time_ms,source_generation,confidence,confidence_source,"
                    "reasons_json,visibility,z_order,revision) VALUES (:id,:w,:p,:v,:rl,:sc,"
                    ":lg,1,'Hero','character',:sf,:ef,:sf,:ef,'1',0.9,'model','[]','visible',0,1)"
                ),
                {
                    "id": seg_id,
                    "w": ws,
                    "p": proj,
                    "v": vid,
                    "rl": role,
                    "sc": _SL_EXTRA["scene_id"],
                    "lg": lg,
                    "sf": sf_,
                    "ef": ef_,
                },
            )
        lock_repo.record_render_route(
            ws, proj, vid, "sg-e1", "pose_swap", 0.5, 0.25, 0, 40,
            provenance={"residual": 0.11}, reasons=["auto-route"],
            structural_lock_manifest_id=manifest.id,
        )
        lock_repo.record_render_route(
            ws, proj, vid, "sg-e2", "controlled_redraw", 0.75, 0.75, 41, 100,
            provenance={"residual": 0.92}, reasons=["complex-shot"],
            structural_lock_manifest_id=manifest.id,
        )
        s.commit()
        manifest_id = manifest.id

    config = _create_pinned_config(ws, proj, role, char, pv, manifest_id)

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rows = repo.list_renderer_route_evidence(ws, config.id)
    by_seg = {r["occurrence_segment_id"]: r for r in rows}
    assert set(by_seg) == {"sg-e1", "sg-e2"}
    assert by_seg["sg-e1"]["route"] == "pose_swap"
    assert by_seg["sg-e1"]["anchor"] == {"x": 0.5, "y": 0.25}
    assert (by_seg["sg-e1"]["start_frame"], by_seg["sg-e1"]["end_frame"]) == (0, 40)
    assert by_seg["sg-e2"]["route"] == "controlled_redraw"
    assert by_seg["sg-e2"]["confidence_source"]
    # Per-segment evidence — two distinct decisions, never one global number.
    assert len(rows) == 2


def test_renderer_route_evidence_unpinned_empty(_seed_sl_env) -> None:
    proj, _vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        record, created = repo.create_config(
            ws, proj, role, char, pv, dict(VALID_PARAMS), None
        )
        s.commit()
        assert created
        assert repo.list_renderer_route_evidence(ws, record.id) == []


# ── Idempotent replay keeps pin equivalence strict ───────────────────────────


def test_idempotent_replay_pin_conflict_detected(_seed_sl_env) -> None:
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    m1 = _create_manifest(ws, proj, vid)
    m2 = _create_manifest(ws, proj, vid, frame_count=150)
    key = f"idem-sl-{uuid.uuid4().hex[:8]}"
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        record, created = repo.create_config(
            ws, proj, role, char, pv, dict(VALID_PARAMS), key,
            structural_lock_manifest_id=m1.id,
        )
        s.commit()
        assert created
        # Same key + different pin → conflict (zero mutation).
        before_rev = record.revision
        with pytest.raises(ReskinConfigConflictError, match="already bound"):
            repo.create_config(
                ws, proj, role, char, pv, dict(VALID_PARAMS), key,
                structural_lock_manifest_id=m2.id,
            )
        s.rollback()
        after = repo.get_config(record.id, ws)
        assert after.revision == before_rev


# ── F6 C1: pinned route evidence isolation (strict) ──────────────────────────


def _seed_segment_row(
    session: Session,
    ws: str,
    proj: str,
    vid: str,
    role: str,
    seg_id: str,
) -> None:
    """Insert one real occurrence_segment row (FK target for route rows)."""
    from sqlalchemy import text as sqltext

    session.execute(
        sqltext(
            "INSERT INTO occurrence_segment(id,workspace_id,project_id,video_item_id,"
            "role_id,scene_id,logical_id,lineage_version,name,kind,start_frame,end_frame,"
            "start_time_ms,end_time_ms,source_generation,confidence,confidence_source,"
            "reasons_json,visibility,z_order,revision) VALUES (:id,:w,:p,:v,:rl,:sc,"
            ":lg,1,'Hero','character',:sf,:ef,:sf,:ef,'1',0.9,'model','[]','visible',0,1)"
        ),
        {
            "id": seg_id,
            "w": ws,
            "p": proj,
            "v": vid,
            "rl": role,
            "sc": _SL_EXTRA["scene_id"],
            "lg": f"lg-{seg_id}",
            "sf": (abs(hash(seg_id)) % 1000),
            "ef": (abs(hash(seg_id)) % 1000) + 50,
        },
    )


def _route_record_route(
    lock_repo: StructuralLockRepository,
    ws: str,
    proj: str,
    vid: str,
    seg_id: str,
    manifest_id: str | None,
    anchor_x: float = 0.5,
) -> None:
    lock_repo.record_render_route(
        ws, proj, vid, seg_id, "pose_swap", anchor_x, 0.5, 0, 100,
        provenance={"seg": seg_id}, reasons=[f"reason-{seg_id}"],
        structural_lock_manifest_id=manifest_id,
    )


def test_f6_evidence_excludes_null_manifest_rows(_seed_sl_env) -> None:
    """Legacy/unattributed rows (manifest IS NULL) must NOT leak into the
    pinned evidence surface (F6 exact leak being corrected)."""
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        from app.persistence.models import ReskinConfig

        lock_repo = StructuralLockRepository(s)
        manifest, _ = lock_repo.create_manifest(
            ws, proj, vid, "g1", _manifest_payload()
        )
        _seed_segment_row(s, ws, proj, vid, role, "sg-null")
        _seed_segment_row(s, ws, proj, vid, role, "sg-pinned")
        # Both rows written BEFORE the pin: the NULL one is the legacy leak
        # class being excluded, the bound one is the only legitimate evidence.
        _route_record_route(lock_repo, ws, proj, vid, "sg-null", None)
        _route_record_route(lock_repo, ws, proj, vid, "sg-pinned", manifest.id)
        s.commit()

        config = _create_pinned_config(ws, proj, role, char, pv, manifest.id)

        cid = (
            s.query(ReskinConfig.id)
            .filter(ReskinConfig.structural_lock_manifest_id == manifest.id)
            .scalar()
        )
        assert cid == config.id

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rows = repo.list_renderer_route_evidence(ws, config.id)
    segs = [r["occurrence_segment_id"] for r in rows]
    assert segs == ["sg-pinned"], f"NULL-manifest row leaked: {segs}"
    assert all(r["structural_lock_manifest_id"] == manifest.id for r in rows)


def test_f6_evidence_excludes_other_manifest_rows(_seed_sl_env) -> None:
    """Rows bound to a DIFFERENT manifest of the same video are excluded."""
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        lock_repo = StructuralLockRepository(s)
        m1, _ = lock_repo.create_manifest(ws, proj, vid, "g1", _manifest_payload())
        m2, _ = lock_repo.create_manifest(
            ws, proj, vid, "g2", _manifest_payload(frame_count=120)
        )
        _seed_segment_row(s, ws, proj, vid, role, "sg-m1")
        _seed_segment_row(s, ws, proj, vid, role, "sg-m2")
        _route_record_route(lock_repo, ws, proj, vid, "sg-m1", m1.id)
        _route_record_route(
            lock_repo, ws, proj, vid, "sg-m2", m2.id, anchor_x=0.9
        )
        s.commit()

    config = _create_pinned_config(ws, proj, role, char, pv, m1.id)
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rows = repo.list_renderer_route_evidence(ws, config.id)
    segs = {r["occurrence_segment_id"] for r in rows}
    assert segs == {"sg-m1"}, f"foreign-manifest row leaked: {segs}"
    assert all(r["structural_lock_manifest_id"] == m1.id for r in rows)


def test_f6_evidence_excludes_rows_created_after_pin(_seed_sl_env) -> None:
    """Route decisions recorded AFTER the pin moment stay out of the frozen
    evidence surface even when bound to the correct manifest."""
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        lock_repo = StructuralLockRepository(s)
        manifest, _ = lock_repo.create_manifest(
            ws, proj, vid, "g1", _manifest_payload()
        )
        _seed_segment_row(s, ws, proj, vid, role, "sg-before")
        _route_record_route(lock_repo, ws, proj, vid, "sg-before", manifest.id)
        s.commit()

    config = _create_pinned_config(ws, proj, role, char, pv, manifest.id)

    with _sf() as s:
        lock_repo = StructuralLockRepository(s)
        _seed_segment_row(s, ws, proj, vid, role, "sg-after")
        _route_record_route(
            lock_repo, ws, proj, vid, "sg-after", manifest.id, anchor_x=0.8
        )
        s.commit()

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rows = repo.list_renderer_route_evidence(ws, config.id)
    segs = {r["occurrence_segment_id"] for r in rows}
    assert segs == {"sg-before"}, f"post-pin row leaked: {segs}"


def test_f6_evidence_stable_across_fresh_db_reload(_seed_sl_env) -> None:
    """Reload through a brand-new session against the same committed DB gives
    the identical evidence set (durability of the frozen surface)."""
    proj, vid, role, char, pv = _seed_sl_env
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        lock_repo = StructuralLockRepository(s)
        manifest, _ = lock_repo.create_manifest(
            ws, proj, vid, "g1", _manifest_payload()
        )
        _seed_segment_row(s, ws, proj, vid, role, "sg-r1")
        _route_record_route(lock_repo, ws, proj, vid, "sg-r1", manifest.id)
        s.commit()

    config = _create_pinned_config(ws, proj, role, char, pv, manifest.id)

    first = []
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        first = repo.list_renderer_route_evidence(ws, config.id)
    assert len(first) == 1 and first[0]["occurrence_segment_id"] == "sg-r1"

    second = []
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        second = repo.list_renderer_route_evidence(ws, config.id)
    assert first == second
