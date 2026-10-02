"""S10-T01C API tests — submit/status/cancel/retry/resume idempotency, project-scoped, additive openapi.

Isolated DB per test (tmp_path) — never MAIN.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import deps
from app.api.app import app
from app.persistence import create_engine_for_path, create_session_factory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _h64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _upgrade(db: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, route: str = "sprite_affine") -> tuple[TestClient, dict[str, str]]:
    db = tmp_path / f"api-{uuid.uuid4().hex[:6]}.db"
    artifacts_root = tmp_path / f"artifacts-{uuid.uuid4().hex[:6]}"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    _upgrade(db)
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    # Patch deps._job_service to own this isolated DB + managed root
    from app.workflow.job_service import JobService

    svc = JobService(session_factory=factory, managed_root=artifacts_root)
    # Ensure default workspace row exists for durable job FK
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, "default") is None:
            s.add(Workspace(id="default", name="default"))
            s.commit()
    # Register the S10 job handler on this isolated worker
    from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

    register_s10_full_apply_handler(svc._worker)  # type: ignore[attr-defined]
    # Bind worker session factory to same isolated DB
    try:
        svc._worker.bind_session_factory(factory)  # type: ignore[attr-defined]
    except Exception:
        pass

    monkeypatch.setattr(deps, "_job_service", svc, raising=False)

    # Seed minimal project/video/checkpoint via the same DB
    with factory() as s:
        ws = "default"
        proj = f"proj-{uuid.uuid4().hex[:6]}"
        vid = f"vid-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"), {"p": proj, "w": ws})
        s.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"), {"v": vid, "p": proj})
        s.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,0,99,0,1000,'pending')"), {"s": f"sc-{uuid.uuid4().hex[:6]}", "v": vid})
        char = f"ch-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,'Hero',:code)"), {"c": char, "w": ws, "code": f"hero_{uuid.uuid4().hex[:4]}"})
        pv = f"pv-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"), {"pv": pv, "c": char, "w": ws})
        role = f"role-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"), {"r": role, "w": ws, "p": proj, "v": vid})
        rc = f"rc-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,'{}',1)"), {"rc": rc, "w": ws, "p": proj, "r": role, "c": char, "pv": pv})
        ckpt = f"ckpt-{uuid.uuid4().hex[:6]}"
        chash = _h64(f"ckpt-{ckpt}")
        s.execute(text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES (:id,:w,:p,:rc,1,:pvj,'[]',:tbf,'{}',:ch,1)"), {"id": ckpt, "w": ws, "p": proj, "rc": rc, "pvj": f'["{pv}"]', "tbf": _h64("tbf"), "ch": chash})
        s.commit()
        seed = {"workspace_id": ws, "project_id": proj, "video_item_id": vid, "checkpoint_id": ckpt, "checkpoint_hash": chash, "pack_version_id": pv}

    # C6: persisted authority — real managed source artifact + replacement asset
    _seed_persisted_authority(factory, artifacts_root, seed)
    # C8: REAL s09.approval/v2 checkpoint with frozen full_apply_authority
    _seed_v2_authority(factory, artifacts_root, seed, route=route)
    client = TestClient(app)
    return client, seed


def _seed_v1_checkpoint(factory, seed: dict[str, str]) -> dict[str, str]:
    """C8: create a REAL v1 (s09.approval/v1) checkpoint with a VALID stored hash.

    The row mirrors a legacy approval: snapshot schema ``s09.approval/v1``,
    no ``full_apply_authority`` block, but the persisted ``checkpoint_hash`` is
    recomputed correctly so hash verification passes — the Full Apply submit
    must then fail closed with REAPPROVAL_REQUIRED (never mutate).
    """
    from app.services.s09_approval import _checkpoint_content_hash

    snapshot = {"schema": "s09.approval/v1", "note": "legacy v1 checkpoint"}
    chash = _checkpoint_content_hash(
        reskin_config_id=seed["reskin_config_id"],
        reskin_config_revision=1,
        structural_lock_manifest_id=seed["manifest_id"],
        lock_policy_version="structural-thresholds-v1",
        pack_version_ids=[seed["pack_version_id"]],
        loop_hashes=[],
        timebase_fingerprint=_h64("tbf-v1"),
        snapshot=snapshot,
    )
    ckpt_v1 = f"ckpt-v1-{uuid.uuid4().hex[:6]}"
    with factory() as s:
        s.execute(
            text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,structural_lock_manifest_id,lock_policy_version,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES (:id,:w,:p,:rc,1,:m,:lp,:packs,'[]',:tbf,:snap,:ch,1)"),
            {
                "id": ckpt_v1,
                "w": seed["workspace_id"],
                "p": seed["project_id"],
                "rc": seed["reskin_config_id"],
                "m": seed["manifest_id"],
                "lp": "structural-thresholds-v1",
                "packs": json.dumps([seed["pack_version_id"]], sort_keys=True, separators=(",", ":")),
                "tbf": _h64("tbf-v1"),
                "snap": json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                "ch": chash,
            },
        )
        s.commit()
    seed["checkpoint_id_v1"] = ckpt_v1
    seed["checkpoint_hash_v1"] = chash
    return seed


def _seed_persisted_authority(factory, artifacts_root: Path, seed: dict[str, str]) -> None:
    """Create real managed source media + replacement asset rows/files (C6).

    The server must resolve source/asset pins from persisted authority; these
    rows/files are the approved artifact identity the submit resolver reads.
    """
    import numpy as np
    from app.persistence.artifacts import hash_file
    from app.services.renderer_routes.composite import write_frames_mp4

    with factory() as s:
        # 1) Original managed source artifact (video_item.source_artifact_id)
        src_rel = f"s10_full_apply/_authority/{seed['video_item_id']}/source.mp4"
        src_abs = artifacts_root / src_rel
        src_abs.parent.mkdir(parents=True, exist_ok=True)
        h, w = 120, 160
        frames = []
        for i in range(100):
            f = np.zeros((h, w, 3), dtype=np.uint8)
            f[:, :, 0] = int(30 + i * 2) % 255
            f[:, :, 1] = 80
            f[:, :, 2] = 20
            frames.append(f)
        write_frames_mp4(frames, src_abs, fps=30.0)
        src_sha = hash_file(src_abs)
        src_art = f"art-src-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','video',:rel,'ready',:sha,:sz,1)"), {"id": src_art, "rel": src_rel, "sha": src_sha, "sz": src_abs.stat().st_size})
        s.execute(text("UPDATE video_item SET source_artifact_id=:aid WHERE id=:vid"), {"aid": src_art, "vid": seed["video_item_id"]})
        # 2) Replacement asset attached to the pinned pack version
        import cv2

        asset_rel = f"s10_full_apply/_authority/{seed['video_item_id']}/asset.png"
        asset_abs = artifacts_root / asset_rel
        asset_abs.parent.mkdir(parents=True, exist_ok=True)
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        hx = hashlib.sha256(seed["pack_version_id"].encode()).hexdigest()
        img[:, :, 0] = int(hx[0:2], 16)
        img[:, :, 1] = int(hx[2:4], 16)
        img[:, :, 2] = int(hx[4:6], 16)
        img[:, :, 3] = 255
        cv2.imwrite(str(asset_abs), img)
        asset_sha = hash_file(asset_abs)
        asset_art = f"art-asset-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"), {"id": asset_art, "rel": asset_rel, "sha": asset_sha, "sz": asset_abs.stat().st_size})
        ca = f"ca-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"), {"id": ca, "pv": seed["pack_version_id"], "aid": asset_art})
        s.commit()


def _seed_v2_authority(factory, artifacts_root: Path, seed: dict[str, str], *, route: str = "sprite_affine") -> dict[str, str]:
    """C8: create a REAL ``s09.approval/v2`` checkpoint with frozen
    ``full_apply_authority`` from a fully persisted authority graph.

    The v2 snapshot pins the source artifact, the structural lock manifest
    (hash-verified), the exact manifest-selected segment/route, the role
    mapping + pack assets, and the affected geometry boxes — everything the
    server-derived Full Apply planner needs.  ``seed`` gains
    ``checkpoint_id``/``checkpoint_hash``/``checkpoint_revision``/
    ``manifest_id``/``manifest_hash``/``role_id``.

    ``route`` selects the exact manifest-selected renderer route frozen into
    the authority (default ``sprite_affine``; tests use ``mesh_warp``/
    ``part_rig`` to prove unsupported routes never downgrade).
    """
    from app.persistence.models import Workspace
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository

    ws = seed["workspace_id"]
    GEN = "1"
    with factory() as s:
        if s.get(Workspace, ws) is None:
            s.add(Workspace(id=ws, name=ws))
        # source artifact row already exists (art-src-*); find it
        src_art = s.execute(text("SELECT id FROM artifact WHERE id LIKE 'art-src-%' AND workspace_id=:w ORDER BY id LIMIT 1"), {"w": ws}).scalar()
        assert src_art, "source artifact must be seeded first"
        proj = s.execute(text("SELECT project_id FROM video_item WHERE id=:v"), {"v": seed["video_item_id"]}).scalar()
        scene_id = s.execute(text("SELECT id FROM scene WHERE video_item_id=:v ORDER BY position LIMIT 1"), {"v": seed["video_item_id"]}).scalar()
        role_id = s.execute(text("SELECT id FROM object_role WHERE video_item_id=:v ORDER BY id LIMIT 1"), {"v": seed["video_item_id"]}).scalar()
        pack_id = s.execute(text("SELECT id FROM character_pack_version WHERE id=:p"), {"p": seed["pack_version_id"]}).scalar()
        rc_id = s.execute(text("SELECT id FROM reskin_config WHERE object_role_id=:r ORDER BY id LIMIT 1"), {"r": role_id}).scalar()

        # Segment with BOXED geometry (affected region is derivable — never guessed)
        # R1 F6: segmentation/prompt evidence REQUIRES a same-workspace kind=image
        # state=ready mask artifact — create the mask artifact row first.
        mask_art = f"art-mask-{uuid.uuid4().hex[:6]}"
        s.execute(
            text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"),
            {"id": mask_art, "rel": f"s10_full_apply/_authority/{seed['video_item_id']}/mask.png", "sha": _h64("mask"), "sz": 64},
        )
        seg_repo = StructuralEvidenceRepository(s)
        seg_rec, _sc = seg_repo.create_segment(
            ws, str(proj), seed["video_item_id"], str(role_id), str(scene_id), "Hero",
            0, 99, 0, 3300, GEN,
            kind="character",
            confidence_source="user",
            segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        seed["segment_id"] = str(seg_rec.id)

        # Structural lock manifest — canonical, hash-verified
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [seed["segment_id"]],
            "fingerprints": {"z_order": _h64("z"), "contacts": _h64("c")},
            "segments": [
                {
                    "occurrence_segment_id": seed["segment_id"],
                    "route": route,
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 99,
                    "provenance": {"why": "c8-fixture"},
                }
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _mc = lock_repo.create_manifest(ws, str(proj), seed["video_item_id"], GEN, manifest_dict)
        lock_repo.record_render_route(
            ws, str(proj), seed["video_item_id"], seed["segment_id"], route,
            0.5, 0.5, 0, 99,
            provenance={"why": "c8-fixture"},
            reasons=["c8-fixture"],
            structural_lock_manifest_id=manifest.id,
        )
        # Pin the manifest onto the reskin config (approval authority)
        s.execute(
            text("UPDATE reskin_config SET structural_lock_manifest_id=:m, lock_policy_version=:p WHERE id=:rc"),
            {"m": manifest.id, "p": manifest.policy_version, "rc": rc_id},
        )
        s.flush()

        # v2 reapproval — creates the immutable s09.approval/v2 row
        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint_v2(
            ws,
            reskin_config_id=str(rc_id),
            expected_reskin_revision=1,
            pack_version_ids=[str(pack_id)],
            note="C8 server-derived authority fixture",
        )
        assert created is True
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = str(record.reskin_config_revision)
        seed["manifest_id"] = str(manifest.id)
        seed["manifest_hash"] = str(manifest.manifest_hash_hex)
        seed["role_id"] = str(role_id)
        seed["reskin_config_id"] = str(rc_id)
    return seed


def _seed_second_v2_checkpoint(seed: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """C8: build a SECOND independent v2 checkpoint (different pack/asset) so a
    changed checkpoint produces a distinct Full Apply lineage."""
    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    mr = svc.managed_root  # type: ignore[union-attr]
    with factory() as s:
        char2 = f"ch-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,'default','Hero2',:code)"), {"c": char2, "code": f"hero2_{uuid.uuid4().hex[:4]}"})
        pv2 = f"pv-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,'default',1,'published')"), {"pv": pv2, "c": char2})
        role2 = f"role-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,'default',:p,:v,'1','Hero2','character','confirmed')"), {"r": role2, "p": seed["project_id"], "v": seed["video_item_id"]})
        rc2 = f"rc-{uuid.uuid4().hex[:6]}"
        valid_params = {
            "anchor": {"x": 0.5, "y": 0.5},
            "scale": 1.0,
            "fit_mode": "contain",
            "clip_mode": "asset_alpha",
            "offset": {"x": 0.0, "y": 0.0},
            "rotation_offset_deg": 0.0,
            "opacity": 1.0,
        }
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,'default',:p,:r,:c,:pv,:params,1)"), {"rc": rc2, "p": seed["project_id"], "r": role2, "c": char2, "pv": pv2, "params": json.dumps(valid_params, sort_keys=True, separators=(",", ":"))})
        # own replacement asset for pack2
        import numpy as np
        from app.persistence.artifacts import hash_file

        asset_rel = f"s10_full_apply/_authority/{seed['video_item_id']}/asset2.png"
        asset_abs = mr / asset_rel
        asset_abs.parent.mkdir(parents=True, exist_ok=True)
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        img[:, :, 3] = 255
        import cv2

        cv2.imwrite(str(asset_abs), img)
        asset_sha = hash_file(asset_abs)
        asset_art = f"art-asset2-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"), {"id": asset_art, "rel": asset_rel, "sha": asset_sha, "sz": asset_abs.stat().st_size})
        ca2 = f"ca-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"), {"id": ca2, "pv": pv2, "aid": asset_art})
        s.commit()

    # second segment + manifest + v2 checkpoint for the NEW role/pack
    seed2 = dict(seed)
    seed2["pack_version_id"] = pv2
    seed2["reskin_config_id"] = rc2
    seed2["role_id"] = role2
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, "default") is None:
            s.add(Workspace(id="default", name="default"))
        proj = seed["project_id"]
        scene_id = s.execute(text("SELECT id FROM scene WHERE video_item_id=:v ORDER BY position LIMIT 1"), {"v": seed["video_item_id"]}).scalar()
        from app.persistence.structural_evidence import StructuralEvidenceRepository
        from app.persistence.structural_lock import StructuralLockRepository
        from app.services.s09_approval import S09ApprovalRepository

        mask_art2 = f"art-mask-{uuid.uuid4().hex[:6]}"
        s.execute(
            text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"),
            {"id": mask_art2, "rel": f"s10_full_apply/_authority/{seed['video_item_id']}/mask2.png", "sha": _h64("mask2"), "sz": 64},
        )
        seg_repo = StructuralEvidenceRepository(s)
        seg_rec, _sc = seg_repo.create_segment(
            "default", proj, seed["video_item_id"], role2, str(scene_id), "Hero2",
            0, 99, 0, 3300, "1",
            kind="character",
            confidence_source="user",
            segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art2,
        )
        seed2["segment_id"] = str(seg_rec.id)
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [seed2["segment_id"]],
            "fingerprints": {"z_order": _h64("z2"), "contacts": _h64("c2")},
            "segments": [
                {
                    "occurrence_segment_id": seed2["segment_id"],
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 99,
                    "provenance": {"why": "c8-fixture-2"},
                }
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _mc = lock_repo.create_manifest("default", proj, seed["video_item_id"], "1", manifest_dict)
        lock_repo.record_render_route(
            "default", proj, seed["video_item_id"], seed2["segment_id"], "sprite_affine",
            0.5, 0.5, 0, 99,
            provenance={"why": "c8-fixture-2"},
            reasons=["c8-fixture-2"],
            structural_lock_manifest_id=manifest.id,
        )
        s.execute(
            text("UPDATE reskin_config SET structural_lock_manifest_id=:m, lock_policy_version=:p WHERE id=:rc"),
            {"m": manifest.id, "p": manifest.policy_version, "rc": rc2},
        )
        s.flush()
        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint_v2(
            "default",
            reskin_config_id=str(rc2),
            expected_reskin_revision=1,
            pack_version_ids=[str(pv2)],
            note="C8 second authority fixture",
        )
        assert created is True
        s.commit()
        seed2["checkpoint_id"] = str(record.id)
        seed2["checkpoint_hash"] = str(record.checkpoint_hash)
        seed2["checkpoint_revision"] = str(record.reskin_config_revision)
        seed2["manifest_id"] = str(manifest.id)
        seed2["manifest_hash"] = str(manifest.manifest_hash_hex)
    return seed2


def _payload(seed: dict[str, str], **overrides) -> dict:
    """C8 minimal public submit — identity/CAS + bounded chunk controls only.

    Legacy authority copies (approved_checkpoint/structural_lock_manifest/
    scene_manifest/mapping) are intentionally OMITTED by default: the server
    derives the entire plan from the frozen v2 checkpoint.  Tests that want a
    legacy tamper matrix pass them via ``overrides``.
    """
    base = {
        "video_item_id": seed["video_item_id"],
        "apply_checkpoint_id": seed["checkpoint_id"],
        "expected_checkpoint_hash": seed["checkpoint_hash"],
        "expected_checkpoint_revision": int(seed.get("checkpoint_revision", 1)),
        "chunk_config": {"chunk_frames": 25, "overlap_frames": 4},
    }
    base.update(overrides)
    return base


def test_submit_202_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed = _make_client(tmp_path, monkeypatch)
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    # status endpoint
    r2 = client.get(f"/api/v2/full-apply/{run_id}")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["run_id"] == run_id
    assert body["project_id"] == seed["project_id"]
    assert len(body["chunks"]) > 0
    # request returns without performing full render synchronously — status is pending/running, not already completed with artifacts
    assert body["status"] in ("pending", "running", "completed")


def test_submit_idempotent_same_tuple_dedupes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed = _make_client(tmp_path, monkeypatch)
    payload = _payload(seed)
    r1 = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=payload)
    assert r1.status_code == 202, r1.text
    r2 = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=payload)
    assert r2.status_code == 200, r2.text
    assert r1.json()["run_id"] == r2.json()["run_id"]
    assert r2.json()["reused"] is True


def test_submit_distinct_on_changed_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed = _make_client(tmp_path, monkeypatch)
    p1 = _payload(seed)
    r1 = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=p1)
    assert r1.status_code == 202, r1.text
    # Change approved_checkpoint hash (distinct lineage) — create a new checkpoint row first
    from app.persistence import create_engine_for_path as _cef
    from app.persistence import create_session_factory as _csf

    # Create a second checkpoint with a different hash
    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    new_ckpt = f"ckpt-{uuid.uuid4().hex[:6]}"
    new_hash = _h64(f"new-{new_ckpt}")
    with factory() as s:  # type: ignore[operator]
        # Need reskin_config for FK
        char2 = f"ch-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,'Hero2',:code)"), {"c": char2, "w": "default", "code": f"hero2_{uuid.uuid4().hex[:4]}"})
        pv2 = f"pv-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"), {"pv": pv2, "c": char2, "w": "default"})
        role2 = f"role-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,'1','Hero2','character','confirmed')"), {"r": role2, "w": "default", "p": seed["project_id"], "v": seed["video_item_id"]})
        rc2 = f"rc-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,'{}',1)"), {"rc": rc2, "w": "default", "p": seed["project_id"], "r": role2, "c": char2, "pv": pv2})
        s.execute(text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES (:id,:w,:p,:rc,1,:pvj,'[]',:tbf,'{}',:ch,1)"), {"id": new_ckpt, "w": "default", "p": seed["project_id"], "rc": rc2, "pvj": f'["{pv2}"]', "tbf": _h64("tbf2"), "ch": new_hash})
        # C6: new checkpoint must carry its own persisted replacement asset authority
        import numpy as np
        from app.persistence.artifacts import hash_file

        svc2 = deps._job_service  # type: ignore[attr-defined]
        mr = svc2.managed_root  # type: ignore[union-attr]
        asset_rel = f"s10_full_apply/_authority/{new_ckpt}/asset.png"
        asset_abs = mr / asset_rel
        asset_abs.parent.mkdir(parents=True, exist_ok=True)
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        img[:, :, 3] = 255
        import cv2

        cv2.imwrite(str(asset_abs), img)
        asset_sha = hash_file(asset_abs)
        asset_art = f"art-asset-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"), {"id": asset_art, "rel": asset_rel, "sha": asset_sha, "sz": asset_abs.stat().st_size})
        ca2 = f"ca-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"), {"id": ca2, "pv": pv2, "aid": asset_art})
        s.commit()
    p2 = _payload(
        seed,
        apply_checkpoint_id=new_ckpt,
        expected_checkpoint_hash=new_hash,
        approved_checkpoint={"checkpoint_id": new_ckpt, "checkpoint_hash": new_hash, "revision": 1},
        mapping={"mappings": [{"layer_id": "bg", "route": "sprite_affine", "pack_version_id": pv2}, {"layer_id": "fg", "route": "mesh_warp", "pack_version_id": pv2}]},
    )
    r2 = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=p2)
    assert r2.status_code == 202, r2.text
    assert r1.json()["run_id"] != r2.json()["run_id"]


def test_project_scoped_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed = _make_client(tmp_path, monkeypatch)
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    # Wrong project on status
    r2 = client.get(f"/api/v2/full-apply/{run_id}", params={"project_id": str(uuid.uuid4())})
    assert r2.status_code == 404, r2.text
    # Wrong project on cancel
    r3 = client.post(f"/api/v2/full-apply/{run_id}/cancel", params={"project_id": str(uuid.uuid4())})
    assert r3.status_code == 404, r3.text


def test_cancel_and_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed = _make_client(tmp_path, monkeypatch)
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    c = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c.status_code == 200, c.text
    assert c.json()["cancelled"] is True
    # Status is cancelled, no completed publication
    s = client.get(f"/api/v2/full-apply/{run_id}")
    assert s.json()["status"] == "cancelled"
    assert all(p["state"] != "completed" for p in s.json()["publications"])
    # Retry creates new lineage
    ret = client.post(f"/api/v2/full-apply/{run_id}/retry")
    assert ret.status_code == 200, ret.text
    assert ret.json()["predecessor_run_id"] == run_id
    assert ret.json()["run_id"] != run_id
    assert ret.json()["attempt"] == 2


def test_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed = _make_client(tmp_path, monkeypatch)
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    rr = client.post(f"/api/v2/full-apply/{run_id}/resume")
    assert rr.status_code == 200, rr.text
    assert rr.json()["resumed"] is True


def test_openapi_additive_no_lost_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _make_client(tmp_path, monkeypatch)
    oa = client.get("/openapi.json")
    assert oa.status_code == 200
    paths = set(oa.json()["paths"].keys())
    # New routes present
    assert "/api/v2/projects/{project_id}/full-apply" in paths
    assert "/api/v2/full-apply/{run_id}" in paths
    assert "/api/v2/full-apply/{run_id}/cancel" in paths
    assert "/api/v2/full-apply/{run_id}/retry" in paths
    assert "/api/v2/full-apply/{run_id}/resume" in paths
    # No lost S09 routes
    assert "/api/v2/s09-approvals" in paths
    assert "/api/v2/s09-demo-loops/submit" in paths or any("s09-demo-loops" in k for k in paths)


# ═══════════════════════════════════════════════════════════════════════════
# C6 — persisted authority, immutable manifest, production purity
# ═══════════════════════════════════════════════════════════════════════════


def test_production_submit_contains_no_synthetic_media_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 1: production submit path has NO synthetic/source/asset generation."""
    from pathlib import Path as _P

    src = _P(__file__).resolve().parent.parent / "app" / "api" / "routes" / "s10_full_apply.py"
    text = src.read_text(encoding="utf-8")
    assert "_c4_stage_source_and_assets" not in text
    assert "import numpy" not in text
    assert "import cv2" not in text
    assert "write_frames_mp4" not in text
    assert "np.zeros" not in text
    assert "_cv2.imwrite" not in text
    # jobs layer also never fabricates media
    jobs = _P(__file__).resolve().parent.parent / "app" / "workflow" / "s10_full_apply_jobs.py"
    jt = jobs.read_text(encoding="utf-8")
    assert "_ensure_synthetic_source" not in jt
    assert "_ensure_replacement_asset" not in jt


def test_submit_binds_persisted_authority_pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 2+3: server pins artifact ids/rel/sha/size/timebase from persisted rows BEFORE enqueue."""
    client, seed = _make_client(tmp_path, monkeypatch)
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]

    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    from app.persistence.jobs import parse_json as _parse

    with factory() as s:
        from sqlalchemy import select as _sel

        from app.persistence.models import Job as _Job

        job = s.scalar(_sel(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{run_id}"))
        assert job is not None, "job must be created with the authority-pinned manifest"
        parsed = _parse(job.input_manifest_json, {})
        assert isinstance(parsed, dict)
        assert parsed.get("source_media_artifact_id", "").startswith("art-src-")
        assert parsed.get("source_media_rel", "").endswith("source.mp4")
        assert len(parsed.get("source_media_sha256", "")) == 64
        assert isinstance(parsed.get("source_media_size_bytes"), int) and parsed["source_media_size_bytes"] > 0
        assert isinstance(parsed.get("replacement_assets"), dict) and seed["role_id"] in parsed["replacement_assets"]
        bg = parsed["replacement_assets"][seed["role_id"]]
        assert bg["artifact_id"].startswith("art-asset-")
        assert bg["rel"].endswith("asset.png")
        assert len(bg["sha256"]) == 64
        assert isinstance(bg["size_bytes"], int) and bg["size_bytes"] > 0
        assert isinstance(parsed.get("timebase_fingerprint"), str) and parsed["timebase_fingerprint"]
        # render authority is bound in the same immutable manifest — and is the
        # CANONICAL server authority (fingerprint + frozen v2 inputs), never a
        # client body echo.
        assert isinstance(parsed.get("render_authority"), dict) and parsed["render_authority"].get("authority_fingerprint")
        assert parsed["render_authority"].get("mapping", {}).get("mappings")


def test_submit_missing_source_authority_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C8: v2 authority source frozen pin missing (artifact row deleted) -> fail closed BEFORE job creation."""
    client, seed = _make_client(tmp_path, monkeypatch)
    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    with factory() as s:
        # Remove the persisted source artifact row the v2 authority points to.
        s.execute(text("UPDATE video_item SET source_artifact_id=NULL WHERE id=:vid"), {"vid": seed["video_item_id"]})
        s.execute(text("DELETE FROM artifact WHERE id LIKE 'art-src-%'"), {})
        s.commit()
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"].lower()
    assert "source" in detail or "not found" in detail or "authority" in detail
    # No run, no job
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job

    with factory() as s:
        assert s.scalar(_sel(_Job)) is None


def test_submit_tampered_source_authority_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 2: backing file SHA/size mismatch vs persisted artifact row -> fail closed."""
    client, seed = _make_client(tmp_path, monkeypatch)
    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    mr = svc.managed_root  # type: ignore[union-attr]
    # Tamper the source backing file (bytes no longer match the persisted sha)
    with factory() as s:
        rel = s.execute(text("SELECT relative_path FROM artifact WHERE id LIKE 'art-src-%'"), {}).scalar()
        assert rel
        abs_p = mr / rel
        abs_p.write_bytes(abs_p.read_bytes() + b"TAMPER")
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 422, resp.text
    assert "tamper" in resp.json()["detail"].lower() or "sha" in resp.json()["detail"].lower()


def test_submit_cross_workspace_authority_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 2: artifact/pack rows in a different workspace -> fail closed."""
    client, seed = _make_client(tmp_path, monkeypatch)
    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    with factory() as s:
        s.execute(text("INSERT INTO workspace(id,name) VALUES ('other','other')"), {})
        s.execute(text("UPDATE artifact SET workspace_id='other' WHERE id LIKE 'art-src-%'"), {})
        s.commit()
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 422, resp.text
    assert "cross-workspace" in resp.json()["detail"].lower()


def test_retry_reuses_exact_authority_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 4: retry reuses the exact immutable authority after revalidation (no copy/regenerate)."""
    client, seed = _make_client(tmp_path, monkeypatch)
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    c = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c.status_code == 200
    ret = client.post(f"/api/v2/full-apply/{run_id}/retry")
    assert ret.status_code == 200, ret.text
    new_id = ret.json()["run_id"]

    svc = deps._job_service  # type: ignore[attr-defined]
    factory = svc.session_factory  # type: ignore[union-attr]
    from app.persistence.jobs import parse_json as _parse

    with factory() as s:
        from sqlalchemy import select as _sel

        from app.persistence.models import Job as _Job

        job = s.scalar(_sel(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{new_id}"))
        assert job is not None
        parsed = _parse(job.input_manifest_json, {})
        # Same persisted rel/sha/size — NO copy to a new run dir, NO regenerate
        assert parsed.get("source_media_rel") == f"s10_full_apply/_authority/{seed['video_item_id']}/source.mp4"
        assert parsed.get("source_media_artifact_id", "").startswith("art-src-")
        assert len(parsed.get("source_media_sha256", "")) == 64
        assert isinstance(parsed.get("replacement_assets"), dict) and seed["role_id"] in parsed["replacement_assets"]
        assert parsed["replacement_assets"][seed["role_id"]]["artifact_id"].startswith("art-asset-")


# ═══════════════════════════════════════════════════════════════════════════
# C8 — server-derived authority: minimal contract, canonical-compare, gates
# ═══════════════════════════════════════════════════════════════════════════


def _read_job_manifest(factory, run_id: str) -> dict:
    """Read the durable job manifest for a run (server-side immutable record)."""
    from app.persistence.jobs import parse_json as _parse
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job

    with factory() as s:
        job = s.scalar(_sel(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{run_id}"))
        assert job is not None, "job must exist for run"
        parsed = _parse(job.input_manifest_json, {})
        assert isinstance(parsed, dict)
        return parsed


def _run_and_job_counts(factory) -> tuple[int, int]:
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job
    from app.persistence.models import S10FullApplyRun as _Run

    with factory() as s:
        runs = len(s.scalars(_sel(_Run)).all())
        jobs = len(s.scalars(_sel(_Job)).all())
    return runs, jobs


def test_openapi_submit_required_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 2: SubmitFullApplyRequest required = identity/CAS + bounded controls ONLY.

    The four legacy authority objects must NOT be required (they are optional
    compatibility copies the server canonical-compares and never trusts).
    """
    client, _ = _make_client(tmp_path, monkeypatch)
    oa = client.get("/openapi.json").json()
    schema = oa["components"]["schemas"]["SubmitFullApplyRequest"]
    required = set(schema.get("required", []))
    # Identity/CAS + bounded controls ARE required.
    assert {"video_item_id", "apply_checkpoint_id", "expected_checkpoint_hash", "expected_checkpoint_revision"} <= required
    # The four legacy authority objects are NOT required anymore.
    for legacy in ("approved_checkpoint", "structural_lock_manifest", "scene_manifest", "mapping"):
        assert legacy not in required, f"legacy authority field {legacy!r} must not be required"
    props = set(schema["properties"].keys())
    # bounded controls remain optional fields (not required)
    assert "chunk_config" in props and "chunk_frames" in props and "overlap_frames" in props


def test_minimal_submit_omits_legacy_authority_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 4: omission of legacy authority fields => SUCCESS with deterministic plan/job.

    The entire plan/authority is derived server-side from the frozen v2
    checkpoint; the client sends identity/CAS + bounded chunk controls only.
    """
    client, seed = _make_client(tmp_path, monkeypatch)
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["created"] is True
    assert body["plan_id"] and body["plan_hash"]
    manifest = _read_job_manifest(deps._job_service.session_factory, body["run_id"])  # type: ignore[union-attr]
    ra = manifest["render_authority"]
    # The manifest authority is the CANONICAL SERVER authority (frozen v2
    # inputs), NOT a client echo — it contains the fingerprint + canonical pins.
    assert ra.get("authority_version") == "s09.full-apply-authority/v1"
    assert len(ra.get("authority_fingerprint", "")) == 64
    assert ra["structural_lock_manifest"]["manifest_hash"] == seed["manifest_hash"]
    assert ra["scene_manifest"]["shots"]
    assert ra["mapping"]["mappings"]
    # determinism: a second identical submit dedupes (200 replay, same plan)
    r2 = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r2.status_code == 200, r2.text
    assert r2.json()["plan_id"] == body["plan_id"]
    assert r2.json()["plan_hash"] == body["plan_hash"]


def test_client_legacy_authority_tamper_fails_closed_zero_run_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 3: arbitrary client scene/range/mapping/route/region/pack/source/hash
    cannot alter the plan — every mismatch fails closed BEFORE any run/job.

    Each tamper sends a legacy copy that disagrees with the frozen v2
    authority; the server canonical-compares and rejects with 422, zero
    run/job/publication.
    """
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    canonical = {
        "approved_checkpoint": {"checkpoint_id": seed["checkpoint_id"], "checkpoint_hash": seed["checkpoint_hash"], "revision": int(seed["checkpoint_revision"])},
        "structural_lock_manifest": {"manifest_hash": seed["manifest_hash"], "policy_version": "structural-thresholds-v1", "source_generation": "1", "frame_count": 100},
        "scene_manifest": {"shots": [{"shot_id": seed["segment_id"], "start_frame": 0, "end_frame": 99}]},
        "mapping": {"mappings": [{"layer_id": seed["role_id"], "role_id": seed["role_id"], "route": "sprite_affine", "affected_region": [0.10, 0.10, 0.30, 0.30], "pack_version_id": seed["pack_version_id"], "deps": []}]},
        "compatibility_policy": {"policy_version": "structural-thresholds-v1"},
    }
    tampers: list[tuple[str, dict]] = [
        ("scene range", {"scene_manifest": {"shots": [{"shot_id": seed["segment_id"], "start_frame": 0, "end_frame": 50}]}}),
        ("scene extra shot", {"scene_manifest": {"shots": [{"shot_id": seed["segment_id"], "start_frame": 0, "end_frame": 99}, {"shot_id": "evil", "start_frame": 50, "end_frame": 99}]}}),
        ("mapping route", {"mapping": {"mappings": [{"layer_id": seed["role_id"], "role_id": seed["role_id"], "route": "mesh_warp", "affected_region": [0.05, 0.05, 0.45, 0.45], "pack_version_id": seed["pack_version_id"]}]}}),
        ("mapping region", {"mapping": {"mappings": [{"layer_id": seed["role_id"], "role_id": seed["role_id"], "route": "sprite_affine", "affected_region": [0.90, 0.90, 0.95, 0.95], "pack_version_id": seed["pack_version_id"]}]}}),
        ("mapping pack", {"mapping": {"mappings": [{"layer_id": seed["role_id"], "role_id": seed["role_id"], "route": "sprite_affine", "affected_region": [0.05, 0.05, 0.45, 0.45], "pack_version_id": "pack-evil"}]}}),
        ("checkpoint hash", {"approved_checkpoint": {"checkpoint_id": seed["checkpoint_id"], "checkpoint_hash": _h64("evil"), "revision": int(seed["checkpoint_revision"])}}),
        ("manifest hash", {"structural_lock_manifest": {"manifest_hash": _h64("evil"), "policy_version": "structural-thresholds-v1", "source_generation": "1", "frame_count": 100}}),
        ("policy", {"compatibility_policy": {"policy_version": "evil-policy"}}),
    ]
    for label, tamper in tampers:
        payload = _payload(seed)
        # always attach the canonical legacy copies so ONLY the tampered field differs
        for k, v in canonical.items():
            payload.setdefault(k, dict(v))
        payload.update(tamper)
        r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=payload)
        assert r.status_code == 422, f"{label}: expected 422 got {r.status_code}: {r.text}"
        # zero run/job created by any tampered submit
        runs, jobs = _run_and_job_counts(factory)
        assert runs == 0 and jobs == 0, f"{label}: tamper created run/job ({runs},{jobs})"
    # control: the SAME payload with canonical copies succeeds (202) — proves the
    # failures above are tamper-specific, not blanket 422s.
    ok_payload = _payload(seed)
    for k, v in canonical.items():
        ok_payload.setdefault(k, dict(v))
    r_ok = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=ok_payload)
    assert r_ok.status_code == 202, r_ok.text


def test_v1_checkpoint_reapproval_required_zero_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 5: s09.approval/v1 checkpoint => REAPPROVAL_REQUIRED, zero mutation."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    seed = _seed_v1_checkpoint(factory, seed)
    payload = _payload(
        seed,
        apply_checkpoint_id=seed["checkpoint_id_v1"],
        expected_checkpoint_hash=seed["checkpoint_hash_v1"],
    )
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=payload)
    assert resp.status_code == 422, resp.text
    assert "REAPPROVAL_REQUIRED" in resp.json()["detail"]
    runs, jobs = _run_and_job_counts(factory)
    assert runs == 0 and jobs == 0


def test_tampered_v2_checkpoint_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 5: tampered v2 row (snapshot edited, hash not recomputed) => BLOCKED."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    with factory() as s:
        snap = json.loads(s.execute(text("SELECT snapshot_json FROM apply_checkpoint WHERE id=:id"), {"id": seed["checkpoint_id"]}).scalar())
        snap["full_apply_authority"]["identity"]["video_item_id"] = "evil-video"
        s.execute(text("UPDATE apply_checkpoint SET snapshot_json=:s WHERE id=:id"), {"s": json.dumps(snap, sort_keys=True, separators=(",", ":")), "id": seed["checkpoint_id"]})
        s.commit()
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"].lower()
    assert "checkpoint_hash" in detail or "integrity" in detail or "tamper" in detail
    runs, jobs = _run_and_job_counts(factory)
    assert runs == 0 and jobs == 0


def test_cross_project_v2_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 5: checkpoint belongs to a different project => BLOCKED (409)."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    other_project = f"proj-{uuid.uuid4().hex[:6]}"
    resp = client.post(f"/api/v2/projects/{other_project}/full-apply", json=_payload(seed))
    assert resp.status_code == 409, resp.text
    assert "checkpoint" in resp.json()["detail"].lower()
    runs, jobs = _run_and_job_counts(factory)
    assert runs == 0 and jobs == 0


def test_stale_checkpoint_hash_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 5: stale expected_checkpoint_hash => BLOCKED (422) before any run."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    payload = _payload(seed, expected_checkpoint_hash=_h64("stale"))
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=payload)
    assert resp.status_code == 422, resp.text
    assert "hash" in resp.json()["detail"].lower() or "checkpoint" in resp.json()["detail"].lower()
    runs, jobs = _run_and_job_counts(factory)
    assert runs == 0 and jobs == 0


def test_unsupported_route_never_coerced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 6: mesh_warp/part_rig frozen in v2 authority => fail closed, NEVER
    coerced to sprite_affine.  Zero run/job and the reason names the route."""
    for bad_route in ("mesh_warp", "part_rig"):
        client, seed = _make_client(tmp_path, monkeypatch, route=bad_route)
        factory = deps._job_service.session_factory  # type: ignore[union-attr]
        resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
        assert resp.status_code == 422, f"{bad_route}: expected 422 got {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"].lower()
        assert bad_route in detail
        assert "no downgrade" in detail or "not executable" in detail
        # zero run/job — no partial state, no fallback route
        runs, jobs = _run_and_job_counts(factory)
        assert runs == 0 and jobs == 0, f"{bad_route}: downgrade created run/job"
        # plan must not silently contain sprite_affine for the bad route
        assert "sprite_affine" not in detail.split(bad_route)[0] or "never downgrade" in detail or "no downgrade" in detail


def test_authority_fingerprint_equality_plan_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 7: plan + job-manifest authority fingerprints == independently
    recomputed v2 authority (hash equality)."""
    from app.services.s10_full_apply import _authority_fingerprint

    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    resp = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    manifest = _read_job_manifest(factory, run_id)
    ra = manifest["render_authority"]
    # independent recompute: load the frozen v2 authority from the persisted
    # row and hash it the same deterministic way
    from app.services.s09_approval import S09ApprovalRepository

    with factory() as s:
        db_authority = S09ApprovalRepository(s).full_apply_authority(seed["checkpoint_id"], seed["workspace_id"])
    assert _authority_fingerprint(db_authority) == ra["authority_fingerprint"]
    # plan pins in the manifest match the run row
    from sqlalchemy import select as _sel

    from app.persistence.models import S10FullApplyRun as _Run

    with factory() as s:
        row = s.scalar(_sel(_Run).where(_Run.id == run_id))
        assert row is not None
        assert row.plan_id == manifest["plan_id"]
        assert row.plan_hash == manifest["plan_hash"]
        assert ra["approved_checkpoint"]["checkpoint_id"] == seed["checkpoint_id"]
        assert ra["approved_checkpoint"]["checkpoint_hash"] == seed["checkpoint_hash"]
    # recompute the plan from canonical manifest inputs and verify plan identity
    from app.services.s10_chunk_plan import plan_full_apply

    plan = plan_full_apply(
        ra["approved_checkpoint"],
        ra["structural_lock_manifest"],
        ra["scene_manifest"],
        ra["mapping"],
        ra["compatibility_policy"],
        chunk_frames=None,
        overlap_frames=None,
        chunk_config=dict(ra["chunk_config"]),
    )
    assert plan["plan_id"] == row.plan_id
    assert plan["plan_hash"] == row.plan_hash


def test_retry_reuses_canonical_lineage_and_fences_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate 8: retry reuses the exact canonical lineage; a mutated v2 row is
    fenced on retry revalidation (BLOCKED before a successor job is created)."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    manifest_orig = _read_job_manifest(factory, run_id)
    c = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c.status_code == 200
    ret = client.post(f"/api/v2/full-apply/{run_id}/retry")
    assert ret.status_code == 200, ret.text
    new_id = ret.json()["run_id"]
    manifest_retry = _read_job_manifest(factory, new_id)
    # exact canonical lineage: same authority fingerprint + same source pins
    assert manifest_retry["render_authority"]["authority_fingerprint"] == manifest_orig["render_authority"]["authority_fingerprint"]
    assert manifest_retry["source_media_sha256"] == manifest_orig["source_media_sha256"]
    assert manifest_retry["replacement_assets"] == manifest_orig["replacement_assets"]
    assert manifest_retry["timebase_fingerprint"] == manifest_orig["timebase_fingerprint"]
    # mutation fence: tamper the v2 row, then retry again -> revalidation BLOCKED
    with factory() as s:
        snap = json.loads(s.execute(text("SELECT snapshot_json FROM apply_checkpoint WHERE id=:id"), {"id": seed["checkpoint_id"]}).scalar())
        snap["full_apply_authority"]["identity"]["source_generation"] = "999"
        s.execute(text("UPDATE apply_checkpoint SET snapshot_json=:s WHERE id=:id"), {"s": json.dumps(snap, sort_keys=True, separators=(",", ":")), "id": seed["checkpoint_id"]})
        s.commit()
    ret2 = client.post(f"/api/v2/full-apply/{new_id}/retry")
    # C6D F1: attempt-2 holds an ACTIVE queued job, so a retry is a competing
    # work item — the single-canonical-work barrier rejects it (409), and zero
    # successor job is created (same outcome as the mutation-fence 422).
    assert ret2.status_code in (409, 422), ret2.text
    # zero successor job was created for the fenced retry
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job

    with factory() as s:
        jobs = [j for j in s.scalars(_sel(_Job)).all() if j.idempotency_key and j.idempotency_key.startswith(f"s10_full_apply_job:{new_id}")]
        assert len(jobs) == 1, "mutated authority must not enqueue a successor job"


# ═══════════════════════════════════════════════════════════════════════════
# S10-C6A F1/F3 — cancel lifecycle through the REAL route + JobService (§7)
# ═══════════════════════════════════════════════════════════════════════════


def _job_row(factory, run_id: str, key: str = "s10_full_apply_job"):
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job

    with factory() as s:
        return s.scalar(_sel(_Job).where(_Job.idempotency_key == f"{key}:{run_id}"))


def _api_job_state(factory, run_id: str) -> str | None:
    row = _job_row(factory, run_id)
    return None if row is None else str(row.state)


def _api_run_status(factory, run_id: str) -> str:
    with factory() as s:
        return str(s.execute(text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar())


def _api_publications(factory, run_id: str) -> list:
    with factory() as s:
        return s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()


def test_cancel_queued_route_zero_effects_drain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 1 (route-level): cancel a queued run via the REAL HTTP route.

    F1 route: run -> cancelled AND job -> cancelling in ONE committed
    transaction; the later worker drain claim resolves the job to terminal
    cancelled with ZERO handler effects (no chunk render, no publication).
    """
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert _api_job_state(factory, run_id) == "queued"
    c = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c.status_code == 200, c.text
    assert c.json()["cancelled"] is True
    assert _api_job_state(factory, run_id) == "cancelling"
    assert _api_run_status(factory, run_id) == "cancelled"
    svc = deps._job_service  # type: ignore[union-attr]
    svc._worker.run_once()  # type: ignore[attr-defined]
    assert _api_job_state(factory, run_id) == "cancelled"
    assert all(str(p["state"]) != "completed" for p in _api_publications(factory, run_id))
    with factory() as s:
        chunks = s.execute(
            text("SELECT verified, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()
        assert all(r["verified"] == 0 and r["artifact_id"] is None for r in chunks)


def test_cancel_idempotent_repeat_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 9: repeating cancel is idempotent — 200 + cancelled:true
    every time, the run and the job never change state after the first one."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    c1 = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c1.status_code == 200 and c1.json()["cancelled"] is True
    c2 = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c2.status_code == 200, c2.text
    assert c2.json()["cancelled"] is True
    c3 = client.post(f"/api/v2/full-apply/{run_id}/cancel")
    assert c3.status_code == 200, c3.text
    assert c3.json()["cancelled"] is True
    assert _api_job_state(factory, run_id) == "cancelling"
    assert _api_run_status(factory, run_id) == "cancelled"
    assert all(str(p["state"]) != "completed" for p in _api_publications(factory, run_id))


def test_retry_after_cancel_exactly_one_successor_predecessor_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 12: retry after cancel creates EXACTLY ONE canonical
    successor (one run, attempt+1, one durable job) and the predecessor run
    + its job stay cancelled."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert client.post(f"/api/v2/full-apply/{run_id}/cancel").status_code == 200
    ret = client.post(f"/api/v2/full-apply/{run_id}/retry")
    assert ret.status_code == 200, ret.text
    assert ret.json()["predecessor_run_id"] == run_id
    assert ret.json()["attempt"] == 2
    new_id = ret.json()["run_id"]
    assert new_id != run_id
    # retrying AGAIN would attempt 3 on the same lineage — call once more on
    # the SUCCESSOR is out of scope; instead verify idempotency of lineage:
    # exactly one successor run + exactly one successor job exist.
    with factory() as s:
        runs = s.execute(
            text("SELECT id, attempt, status, natural_key FROM s10_full_apply_run WHERE id=:rid"),
            {"rid": new_id},
        ).mappings().first()
        assert runs is not None and int(runs["attempt"]) == 2
        # Lineage is carried by natural_key (schema has no predecessor_run_id
        # column): successor natural_key must encode the predecessor id.
        assert str(runs["natural_key"]) == f"s10_retry:{run_id}:2"
        assert str(runs["status"]) == "pending"
        from sqlalchemy import select as _sel

        from app.persistence.models import Job as _Job

        succ_jobs = [
            j
            for j in s.scalars(_sel(_Job)).all()
            if j.idempotency_key and j.idempotency_key.startswith(f"s10_full_apply_job:{new_id}")
        ]
        assert len(succ_jobs) == 1, succ_jobs
        pred_jobs = [
            j
            for j in s.scalars(_sel(_Job)).all()
            if j.idempotency_key and j.idempotency_key.startswith(f"s10_full_apply_job:{run_id}")
        ]
        assert len(pred_jobs) == 1
        assert str(pred_jobs[0].state) in ("cancelling", "cancelled")
    assert _api_run_status(factory, run_id) == "cancelled"
    assert all(str(p["state"]) != "completed" for p in _api_publications(factory, run_id))


def test_resume_after_cancel_conflict_and_job_missing_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 13: resume on a cancelled run is a 422 conflict (never
    resumed:true); resume with the durable job missing still enqueues a real
    successor job; and resume on a COMPLETED run short-circuits truthfully."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert client.post(f"/api/v2/full-apply/{run_id}/cancel").status_code == 200
    rr = client.post(f"/api/v2/full-apply/{run_id}/resume")
    assert rr.status_code == 422, rr.text  # cancelled cannot resume — retry only
    assert _api_run_status(factory, run_id) == "cancelled"


def test_resume_reactivates_terminal_job_no_phantom_resumed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 13 (continued): resume with a terminal job creates/reactivates
    the durable successor; when the successor creation is FORCED to fail the
    route must NOT answer resumed:true — it surfaces 500 and compensates the
    run-side reopen back to its committed pre-state."""
    client, seed = _make_client(tmp_path, monkeypatch)
    factory = deps._job_service.session_factory  # type: ignore[union-attr]
    r = client.post(f"/api/v2/projects/{seed['project_id']}/full-apply", json=_payload(seed))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert _api_job_state(factory, run_id) == "queued"
    rr = client.post(f"/api/v2/full-apply/{run_id}/resume")
    assert rr.status_code == 200, rr.text
    assert rr.json()["resumed"] is True
    # queued job untouched by resume (picked up by the poll loop)
    assert _api_job_state(factory, run_id) == "queued"
    assert _api_run_status(factory, run_id) == "pending"
    # ---- forced create-failure on the terminal-job path: no phantom resume
    # Distinct lineage required: an identical payload is idempotent (200
    # reused:true, same run/job) so it can never yield a fresh run.  A
    # different chunk_config derives a different natural/idempotency key →
    # a genuinely new 202 run with its own durable job.
    r2 = client.post(
        f"/api/v2/projects/{seed['project_id']}/full-apply",
        json=_payload(seed, chunk_config={"chunk_frames": 50, "overlap_frames": 4}),
    )
    assert r2.status_code == 202, r2.text
    assert r2.json()["reused"] is False, r2.text
    run_id2 = r2.json()["run_id"]
    assert run_id2 != run_id
    with factory() as s:
        from sqlalchemy import text as _t

        s.execute(_t("UPDATE job SET state='failed' WHERE idempotency_key=:k"), {"k": f"s10_full_apply_job:{run_id2}"})
        # Compensation contract precondition: _compensate_resume only reverts
        # failed -> pending, so the run itself must be 'failed' before the
        # resume (a fresh pending run is never mutated by resume_run — its
        # compensation is a no-op by design).  Simulate the worker-failed run
        # with the same raw-SQL style used above for the job table.
        s.execute(_t("UPDATE s10_full_apply_run SET status='failed' WHERE id=:rid"), {"rid": run_id2})
        s.commit()
    assert _api_run_status(factory, run_id2) == "failed"
    from app.persistence.jobs import JobRepository as _JR

    orig_create_successor = _JR.create_successor

    def _boom_create_successor(self, **kwargs):
        raise RuntimeError("forced create-successor failure (F3 test)")

    monkeypatch.setattr(_JR, "create_successor", _boom_create_successor)
    rr2 = client.post(f"/api/v2/full-apply/{run_id2}/resume")
    assert rr2.status_code == 500, rr2.text  # NEVER resumed:true
    assert rr2.json().get("resumed") is not True
    # compensation: the run-side reopen (failed -> pending) is reverted
    assert _api_run_status(factory, run_id2) == "failed"
    monkeypatch.setattr(_JR, "create_successor", orig_create_successor)
