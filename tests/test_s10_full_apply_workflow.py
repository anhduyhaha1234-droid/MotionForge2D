"""S10-T01C workflow tests — checkpoint durable, resume, cancel zero false publication, dedupe/distinct, atomic publication.

C4: production worker LOADs server-side render_authority + pinned source media /
replacement assets; these fixtures STAGE real media OUTSIDE the handler and pass
explicit pins in the job manifest.  Negative tests prove every fabricated/missing
input fails closed (source, asset, mapping, route, zero chunks, stitch, crash-hook).

Isolated DB per test (tmp_path) — never MAIN.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from app.persistence import create_engine_for_path, create_session_factory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _h64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _lp_test(path: Path, *, force: bool = False) -> Path:
    """Test-side mirror of production extended-length path handling.

    On Windows a path over the classic MAX_PATH (or the managed ROOT with
    ``force=True``) must carry the ``\\\\?\\\\`` prefix to be addressable at all;
    fixture staging and long-path assertions go through this helper so they
    exercise the same >260-char form the production worker uses.
    """
    import os

    raw = str(path)
    if os.name == "nt" and not raw.startswith("\\\\?\\\\") and (force or len(raw) > 259):
        return Path("\\\\?\\\\" + os.path.abspath(raw))
    return path


def _upgrade(db: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")


def _valid_reskin_params() -> dict:
    """The VALID canonical reskin params contract (v2 authority validates it)."""
    return {
        "anchor": {"x": 0.5, "y": 0.5},
        "scale": 1.0,
        "fit_mode": "contain",
        "clip_mode": "asset_alpha",
        "offset": {"x": 0.0, "y": 0.0},
        "rotation_offset_deg": 0.0,
        "opacity": 1.0,
    }


def _seed(tmp_path: Path) -> tuple[Path, Path, object, dict[str, str]]:
    """C8: seed a REAL s09.approval/v2 checkpoint + persisted authority graph.

    The v2 checkpoint carries a frozen ``full_apply_authority`` (source
    artifact, hash-verified structural lock manifest, exact segment/route,
    role mapping + pack assets, boxed geometry) so the FullApply service can
    derive the plan server-side from identity/CAS only.
    """
    import numpy as np

    from app.persistence.artifacts import hash_file
    from app.services.renderer_routes.composite import write_frames_mp4

    db = tmp_path / f"wf-{uuid.uuid4().hex[:6]}.db"
    artifacts_root = tmp_path / f"artifacts-{uuid.uuid4().hex[:6]}"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    _upgrade(db)
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, "default") is None:
            s.add(Workspace(id="default", name="default"))
            s.commit()
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
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"), {"rc": rc, "w": ws, "p": proj, "r": role, "c": char, "pv": pv, "params": json.dumps(_valid_reskin_params(), sort_keys=True, separators=(",", ":"))})
        # C8: persisted managed SOURCE artifact (video_item.source_artifact_id)
        src_rel = f"s10_full_apply/_authority/{vid}/source.mp4"
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
        s.execute(text("UPDATE video_item SET source_artifact_id=:aid WHERE id=:vid"), {"aid": src_art, "vid": vid})
        # C8: persisted replacement ASSET attached to the pinned pack version
        import cv2

        asset_rel = f"s10_full_apply/_authority/{vid}/asset.png"
        asset_abs = artifacts_root / asset_rel
        asset_abs.parent.mkdir(parents=True, exist_ok=True)
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        hx = hashlib.sha256(pv.encode()).hexdigest()
        img[:, :, 0] = int(hx[0:2], 16)
        img[:, :, 1] = int(hx[2:4], 16)
        img[:, :, 2] = int(hx[4:6], 16)
        img[:, :, 3] = 255
        cv2.imwrite(str(asset_abs), img)
        asset_sha = hash_file(asset_abs)
        asset_art = f"art-asset-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"), {"id": asset_art, "rel": asset_rel, "sha": asset_sha, "sz": asset_abs.stat().st_size})
        ca = f"ca-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"), {"id": ca, "pv": pv, "aid": asset_art})
        s.commit()
        seed = {"workspace_id": ws, "project_id": proj, "video_item_id": vid, "pack_version_id": pv, "reskin_config_id": rc, "role_id": role}
    _seed_v2_checkpoint(factory, artifacts_root, seed)
    return db, artifacts_root, factory, seed


def _seed_v2_checkpoint(factory, artifacts_root: Path, seed: dict[str, str]) -> None:
    """C8: freeze a REAL s09.approval/v2 checkpoint for the seeded graph."""
    import numpy as np

    from app.persistence.artifacts import hash_file
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository

    ws = seed["workspace_id"]
    GEN = "1"
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, ws) is None:
            s.add(Workspace(id=ws, name=ws))
        src_art = s.execute(text("SELECT id FROM artifact WHERE id LIKE 'art-src-%' AND workspace_id=:w ORDER BY id LIMIT 1"), {"w": ws}).scalar()
        assert src_art, "source artifact must be seeded first"
        proj = seed["project_id"]
        scene_id = s.execute(text("SELECT id FROM scene WHERE video_item_id=:v ORDER BY position LIMIT 1"), {"v": seed["video_item_id"]}).scalar()
        role_id = seed["role_id"]
        pack_id = seed["pack_version_id"]
        rc_id = seed["reskin_config_id"]

        mask_art = f"art-mask-{uuid.uuid4().hex[:6]}"
        mask_rel = f"s10_full_apply/_authority/{seed['video_item_id']}/mask.png"
        mask_abs = artifacts_root / mask_rel
        mask_abs.parent.mkdir(parents=True, exist_ok=True)
        import cv2

        mask_img = np.zeros((40, 40, 4), dtype=np.uint8)
        mask_img[:, :, 3] = 255
        cv2.imwrite(str(mask_abs), mask_img)
        mask_sha = hash_file(mask_abs)
        s.execute(
            text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"),
            {"id": mask_art, "rel": mask_rel, "sha": mask_sha, "sz": mask_abs.stat().st_size},
        )
        seg_repo = StructuralEvidenceRepository(s)
        seg_rec, _sc = seg_repo.create_segment(
            ws, proj, seed["video_item_id"], role_id, str(scene_id), "Hero",
            0, 99, 0, 3300, GEN,
            kind="character",
            confidence_source="user",
            segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        seed["segment_id"] = str(seg_rec.id)

        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [seed["segment_id"]],
            "fingerprints": {"z_order": _h64("z"), "contacts": _h64("c")},
            "segments": [
                {
                    "occurrence_segment_id": seed["segment_id"],
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 99,
                    "provenance": {"why": "c8-workflow-fixture"},
                }
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _mc = lock_repo.create_manifest(ws, proj, seed["video_item_id"], GEN, manifest_dict)
        lock_repo.record_render_route(
            ws, proj, seed["video_item_id"], seed["segment_id"], "sprite_affine",
            0.5, 0.5, 0, 99,
            provenance={"why": "c8-workflow-fixture"},
            reasons=["c8-workflow-fixture"],
            structural_lock_manifest_id=manifest.id,
        )
        s.execute(
            text("UPDATE reskin_config SET structural_lock_manifest_id=:m, lock_policy_version=:p WHERE id=:rc"),
            {"m": manifest.id, "p": manifest.policy_version, "rc": rc_id},
        )
        s.flush()
        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint_v2(
            ws,
            reskin_config_id=str(rc_id),
            expected_reskin_revision=1,
            pack_version_ids=[str(pack_id)],
            note="C8 workflow authority fixture",
        )
        assert created is True
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = str(record.reskin_config_revision)
        seed["manifest_id"] = str(manifest.id)
        seed["manifest_hash"] = str(manifest.manifest_hash_hex)


# ── C4: REAL media staged OUTSIDE the production handler ─────────────────────


def _stage_source(artifacts_root: Path, run_id: str, frames: int = 100, fps: float = 30.0) -> dict[str, str]:
    """Build a REAL decodable source MP4 under the managed root (fixture-owned)."""
    import numpy as np
    from app.persistence.artifacts import hash_file
    from app.services.renderer_routes.composite import write_frames_mp4

    rel = f"s10_full_apply/{run_id}/_source.mp4"
    abs_p = _lp_test(artifacts_root / rel)
    abs_p.parent.mkdir(parents=True, exist_ok=True)
    h, w = 120, 160
    src_frames = []
    for i in range(frames):
        f = np.zeros((h, w, 3), dtype=np.uint8)
        f[:, :, 0] = int(30 + i * 2) % 255
        f[:, :, 1] = 80
        f[:, :, 2] = 20
        src_frames.append(f)
    write_frames_mp4(src_frames, abs_p, fps=fps)
    return {"source_media_rel": rel, "source_media_sha256": hash_file(abs_p)}


def _stage_asset(artifacts_root: Path, layer_id: str) -> dict[str, str]:
    """Build a REAL RGBA replacement/pose asset (fixture-owned, outside handler)."""
    import cv2
    import numpy as np
    from app.persistence.artifacts import hash_file

    rel = f"s10_full_apply/_assets/{layer_id}.png"
    abs_p = _lp_test(artifacts_root / rel)
    abs_p.parent.mkdir(parents=True, exist_ok=True)
    img = np.zeros((40, 40, 4), dtype=np.uint8)
    hx = hashlib.sha256(layer_id.encode()).hexdigest()
    img[:, :, 0] = int(hx[0:2], 16)
    img[:, :, 1] = int(hx[2:4], 16)
    img[:, :, 2] = int(hx[4:6], 16)
    img[:, :, 3] = 255
    cv2.imwrite(str(abs_p), img)
    return {"rel": rel, "sha256": hash_file(abs_p)}


def _submit_run(factory, seed: dict[str, str], *, chunk_frames: int = 25, frame_count: int = 100, mapping: dict | None = None) -> tuple[str, dict]:
    """C8: minimal public submit (identity/CAS + bounded controls) against the
    frozen v2 checkpoint; returns (run_id, canonical render_authority)."""
    from app.services.s10_full_apply import FullApplyService

    with factory() as s:
        svc = FullApplyService(s)
        rec, _created, plan = svc.submit(
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            video_item_id=seed["video_item_id"],
            apply_checkpoint_id=seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"],
            expected_checkpoint_revision=int(seed.get("checkpoint_revision", 1)),
            chunk_config={"chunk_frames": chunk_frames, "overlap_frames": 4},
        )
        s.commit()
        # NOTE: replay submits (same tuple) legitimately return created=False;
        # tests that need a FRESH lineage call this helper once per tuple.
        return rec.id, plan["render_authority"]


def _register(monkeypatch: pytest.MonkeyPatch, artifacts_root: Path, factory) -> object:
    from app.api import deps
    from app.workflow.job_service import JobService

    svc = JobService(session_factory=factory, managed_root=artifacts_root)
    monkeypatch.setattr(deps, "_job_service", svc, raising=False)
    from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

    register_s10_full_apply_handler(svc._worker)  # type: ignore[attr-defined]
    try:
        svc._worker.bind_session_factory(factory)  # type: ignore[attr-defined]
    except Exception:
        pass
    return svc


def _make_job_manifest(
    seed: dict[str, str],
    run_id: str,
    artifacts_root: Path,
    authority: dict,
    *,
    layers: tuple[str, ...] | None = None,
    stop_key: bool = False,
) -> dict:
    """Server-side job manifest: canonical authority + staged source + pinned assets.

    The render_authority comes from the server submit plan (fingerprint
    included); the manifest also carries ``apply_checkpoint_id`` so the worker
    can re-derive the authority fingerprint from the persisted v2 row and
    fence any mutation before render.

    stop_key=True simulates a caller trying to inject a crash hook through the
    production manifest — the worker must reject it (fail closed).
    """
    m: dict = {
        "run_id": run_id,
        "workspace_id": seed["workspace_id"],
        "project_id": seed["project_id"],
        "video_item_id": seed["video_item_id"],
        "apply_checkpoint_id": seed["checkpoint_id"],
        "managed_root": str(artifacts_root),
        "render_authority": authority,
    }
    m.update(_stage_source(artifacts_root, run_id))
    assets: dict[str, dict[str, str]] = {}
    if layers is None:
        layers = (seed["role_id"],)
    for layer in layers:
        assets[layer] = _stage_asset(artifacts_root, layer)
    m["replacement_assets"] = assets
    if stop_key:
        m["stop_after_chunk"] = 1  # callers must NEVER be able to do this
    return m


def _post_step_checkpoint(factory, job_id: str, cp: dict) -> None:
    from sqlalchemy import select as _sel  # noqa: PLC0415

    from app.persistence.models import JobStep as _JobStep  # noqa: PLC0415

    with factory() as s:
        row = s.scalar(_sel(_JobStep).where(_JobStep.job_id == job_id))
        assert row is not None
        row.checkpoint_json = json.dumps(cp, sort_keys=True)
        s.commit()


def test_checkpoint_durable_before_stop_and_resume_skips_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, artifacts_root, factory, seed = _seed(tmp_path)
    import app.workflow.s10_full_apply_jobs as mod
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)

    # First worker run: execute chunks 0,1 then STOP via the TEST-OWNED control
    # (module global — production API manifest cannot provide this).
    monkeypatch.setattr(mod, "_TEST_STOP_AFTER_CHUNK", 1)
    job = svc.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        _make_job_manifest(seed, run_id, artifacts_root, authority),
        workspace_id=seed["workspace_id"],
        owner_type="project",
        owner_id=seed["project_id"],
        idempotency_key=f"s10_wf_test_{run_id[:8]}",
    )
    svc._worker.run_once()  # type: ignore[attr-defined]
    # Checkpoint must be durable at next_chunk_index=2
    with factory() as s:
        from app.persistence.jobs import JobRepository

        steps = JobRepository(s).list_steps(job.job_id)
        assert len(steps) == 1
        cp = steps[0].checkpoint or {}
        if isinstance(cp, str):
            cp = json.loads(cp)
        assert cp.get("next_chunk_index") == 2, f"checkpoint not durable at stop: {cp}"
        assert len(cp.get("executed", [])) == 2
    with factory() as s:
        rows = s.execute(text("SELECT chunk_index, state, verified, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY chunk_index"), {"rid": run_id}).mappings().all()
        assert rows[0]["verified"] == 1 and rows[0]["state"] == "completed"
        assert rows[1]["verified"] == 1 and rows[1]["state"] == "completed"
        assert rows[2]["verified"] == 0
        before_artifacts = {r["artifact_id"] for r in rows[:2]}
        before_files: list[str] = []
        for r in rows[:2]:
            art = s.execute(text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": r["artifact_id"]}).scalar()
            assert art is not None
            assert (artifacts_root / art).is_file()
            assert ".partial" not in art
            before_files.append(art)
    # Resume: fresh job, NO crash control, checkpoint seeded at 2
    monkeypatch.setattr(mod, "_TEST_STOP_AFTER_CHUNK", None)
    job2 = svc.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        _make_job_manifest(seed, run_id, artifacts_root, authority),
        workspace_id=seed["workspace_id"],
        owner_type="project",
        owner_id=seed["project_id"],
        idempotency_key=f"s10_wf_resume_{run_id[:8]}",
    )
    with factory() as s:
        from app.persistence.models import JobStep as _JobStep
        from sqlalchemy import select as _sel

        row = s.scalar(_sel(_JobStep).where(_JobStep.job_id == job2.job_id))
        assert row is not None
        row.checkpoint_json = json.dumps({"schema_version": 1, "run_id": run_id, "next_chunk_index": 2, "executed": [0, 1]}, sort_keys=True)
        s.commit()
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        rows = s.execute(text("SELECT chunk_index, artifact_id, verified FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY chunk_index"), {"rid": run_id}).mappings().all()
        assert all(r["verified"] == 1 for r in rows)
        after_first_two = {r["artifact_id"] for r in rows[:2]}
        assert after_first_two == before_artifacts, "fresh process rerendered verified completed chunks"
        assert len(rows) == 4  # 100 frames, 25 chunk_frames, 1 canonical role/shot => 4 chunks
        for r in rows:
            art = s.execute(text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": r["artifact_id"]}).scalar()
            assert art is not None and ".partial" not in art
            assert (artifacts_root / art).is_file()
            from app.persistence.artifacts import hash_file

            assert len(hash_file(artifacts_root / art)) == 64


def test_cancel_leaves_zero_falsely_completed_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    _register(monkeypatch, artifacts_root, factory)
    run_id, _ = _submit_run(factory, seed)
    from app.services.s10_full_apply import FullApplyService

    with factory() as s:
        fsvc = FullApplyService(s)
        rec = fsvc.cancel_run(run_id, seed["workspace_id"], project_id=seed["project_id"])
        s.commit()
        assert rec.status == "cancelled"
        pubs = fsvc.list_publications(seed["workspace_id"], run_id)
        assert all(p.state != "completed" for p in pubs), "cancel left falsely completed publication"
        new_rec = fsvc.retry_run(run_id, seed["workspace_id"], project_id=seed["project_id"])
        s.commit()
        assert new_rec.id != run_id
        assert new_rec.attempt == rec.attempt + 1
        assert new_rec.status == "pending"


def test_same_tuple_dedupes_changed_plan_distinct(tmp_path: Path) -> None:
    _db, _art, factory, seed = _seed(tmp_path)
    run_id_1, _ = _submit_run(factory, seed, chunk_frames=25)
    run_id_2, _ = _submit_run(factory, seed, chunk_frames=25)
    assert run_id_1 == run_id_2, "same approved tuple should dedupe"
    run_id_3, _ = _submit_run(factory, seed, chunk_frames=10)
    assert run_id_3 != run_id_1, "changed chunk plan should produce distinct lineage"


def test_artifacts_atomic_and_sha256(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    svc.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        _make_job_manifest(seed, run_id, artifacts_root, authority),
        workspace_id=seed["workspace_id"],
        owner_type="project",
        owner_id=seed["project_id"],
        idempotency_key=f"s10_atomic_{run_id[:8]}",
    )
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        rows = s.execute(text("SELECT relative_path, state FROM artifact")).mappings().all()
        assert len(rows) > 0
        for r in rows:
            rel = r["relative_path"]
            assert ".partial" not in rel
            assert (artifacts_root / rel).is_file()
            from app.persistence.artifacts import hash_file

            sha = hash_file(artifacts_root / rel)
            assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
            assert not (artifacts_root / (rel + ".staging")).exists()


def test_corrupted_ready_artifact_quarantined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    import app.workflow.s10_full_apply_jobs as mod
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    monkeypatch.setattr(mod, "_TEST_STOP_AFTER_CHUNK", 0)
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_corrupt_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        row = s.execute(text("SELECT artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid AND chunk_index=0"), {"rid": run_id}).scalar()
        art_row = s.execute(text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": row}).mappings().first()
        assert art_row is not None
        abs_p = artifacts_root / art_row["relative_path"]
        abs_p.write_bytes(b"corrupted bytes not matching sha")
    monkeypatch.setattr(mod, "_TEST_STOP_AFTER_CHUNK", None)
    job2 = svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_corrupt2_{run_id[:8]}")
    _post_step_checkpoint(factory, job2.job_id, {"schema_version": 1, "run_id": run_id, "next_chunk_index": 0, "executed": []})
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        new_aid = s.execute(text("SELECT artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid AND chunk_index=0"), {"rid": run_id}).scalar()
        art2 = s.execute(text("SELECT relative_path, sha256 FROM artifact WHERE id=:aid"), {"aid": new_aid}).mappings().first()
        assert art2 is not None
        from app.persistence.artifacts import hash_file

        assert hash_file(artifacts_root / art2["relative_path"]) == art2["sha256"]
        from app.services.renderer_routes.composite import decode_rgb_frames

        frames = decode_rgb_frames(artifacts_root / art2["relative_path"])
        assert len(frames) > 0


def test_absent_parent_directories_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    import shutil
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    parent = artifacts_root / f"s10_full_apply/{run_id}"
    if parent.exists():
        shutil.rmtree(parent)
    assert not parent.exists()
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_mkdir_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        chunks = s.execute(text("SELECT artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": run_id}).fetchall()
        assert len(chunks) > 0
        for (aid,) in chunks:
            rel = s.execute(text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": aid}).scalar()
            assert (artifacts_root / rel).is_file()
            assert (artifacts_root / rel).parent.exists()


def test_stitch_failure_run_failed_no_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    import app.workflow.s10_full_apply_jobs as mod
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    orig = mod._stitch_verified_chunks

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("injected stitch failure")

    monkeypatch.setattr(mod, "_stitch_verified_chunks", _boom)
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_stitchfail_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    monkeypatch.setattr(mod, "_stitch_verified_chunks", orig)
    with factory() as s:
        status = s.execute(text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar()
        assert status == "failed"
        completed = s.execute(text("SELECT COUNT(*) FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": run_id}).scalar()
        assert completed == 0


def test_no_publication_on_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    _register(monkeypatch, artifacts_root, factory)
    run_id, _ = _submit_run(factory, seed)
    from app.services.s10_full_apply import FullApplyService

    with factory() as s:
        fsvc = FullApplyService(s)
        fsvc.cancel_run(run_id, seed["workspace_id"], project_id=seed["project_id"])
        s.commit()
        pubs = fsvc.list_publications(seed["workspace_id"], run_id)
        assert all(p.state != "completed" for p in pubs)


def _cancel_queued_via_route(client: "TestClient", seed: dict[str, str], run_id: str) -> None:
    """F1 cancel: the run cancel + durable job ->cancelling land atomically."""
    c = client.post(
        f"/api/v2/full-apply/{run_id}/cancel?workspace_id={seed['workspace_id']}&project_id={seed['project_id']}"
    )
    assert c.status_code == 200, c.text
    assert c.json()["cancelled"] is True


def _run_status(factory, run_id: str) -> str:
    with factory() as s:
        return str(s.execute(text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar())


def _job_state(factory, run_id: str, key: str = "s10_full_apply_job") -> str | None:
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job

    with factory() as s:
        job = s.scalar(_sel(_Job).where(_Job.idempotency_key == f"{key}:{run_id}"))
        return None if job is None else str(job.state)


def _job_state_by_id(factory, job_id: str) -> str | None:
    from sqlalchemy import select as _sel

    from app.persistence.models import Job as _Job

    with factory() as s:
        job = s.scalar(_sel(_Job).where(_Job.id == job_id))
        return None if job is None else str(job.state)


def _job_event_pairs(factory, job_id: str) -> list[tuple[str | None, str | None, str]]:
    from sqlalchemy import select as _sel

    from app.persistence.models import JobEvent as _JobEvent

    with factory() as s:
        events = s.scalars(_sel(_JobEvent).where(_JobEvent.job_id == job_id).order_by(_JobEvent.created_at)).all()
        return [(e.from_state, e.to_state, e.actor) for e in events]


def _run_claimed_worker(svc, job_id: str) -> None:
    """Drive an ALREADY-CLAIMED (running, leased) job through worker execution.

    ``run_once`` only claims queued / unleased-cancelling jobs; a job that a
    (simulated concurrent) worker already claimed is executed here exactly
    like run_once would (lease check + _execute_job + caller commit).
    """
    from app.persistence.jobs import JobRepository as _JR

    with svc._worker._session_factory() as session:  # type: ignore[attr-defined]
        repo = _JR(session)
        job_rec = repo.get_job(job_id)
        assert repo.get_lease(job_id) is not None, "test precondition: running job must hold a live lease"
        svc._worker._execute_job(session, repo, job_rec)  # type: ignore[attr-defined]
        session.commit()


def test_cancel_queued_before_claim_never_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 1: cancel a queued run BEFORE the worker claims the job.

    The route-level atomic cancel (F1) must put the durable job in
    ``cancelling``; a later drain claim resolves it to terminal ``cancelled``
    with ZERO handler effects — no chunk render, no publication, and the
    run stays cancelled.
    """
    db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.api.app import app as fastapi_app

    monkeypatch.setattr(deps, "_job_service", svc, raising=False)
    client = TestClient(fastapi_app)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    job = svc.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        _make_job_manifest(seed, run_id, artifacts_root, authority),
        workspace_id=seed["workspace_id"],
        owner_type="project",
        owner_id=seed["project_id"],
        idempotency_key=f"s10_full_apply_job:{run_id}",
    )
    assert job.state == "queued"
    _cancel_queued_via_route(client, seed, run_id)
    assert _job_state(factory, run_id) == "cancelling"
    assert _run_status(factory, run_id) == "cancelled"
    # Drain: the unleased cancelling job is claimed (queued-cancel fallback)
    # and drained to terminal cancelled with zero handler effects.
    svc._worker.run_once()  # type: ignore[attr-defined]
    assert _job_state(factory, run_id) == "cancelled"
    with factory() as s:
        chunks = s.execute(
            text("SELECT verified, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()
        assert all(r["verified"] == 0 and r["artifact_id"] is None for r in chunks), "cancelled job rendered chunks"
        pubs = s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()
        assert all(str(r["state"]) != "completed" for r in pubs)


def test_cancel_after_last_chunk_before_stitch_withholds_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 4: cancel lands after the last chunk but before stitch.

    The pre-stitch fence (F2) must stop the worker: every chunk may be
    verified, but NO publication row and NO completed run may appear — the
    job history shows cancelling -> cancelled.
    """
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    import app.workflow.s10_full_apply_jobs as jobs_mod

    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    job = svc.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        _make_job_manifest(seed, run_id, artifacts_root, authority),
        workspace_id=seed["workspace_id"],
        owner_type="project",
        owner_id=seed["project_id"],
        idempotency_key=f"s10_full_apply_job:{run_id}",
    )

    cancellable: dict[str, object] = {"on": False}
    render_orig = jobs_mod._render_chunk_via_real_executor
    render_calls = {"n": 0}

    def _render_with_cancel(**kwargs):
        render_calls["n"] += 1
        if cancellable["on"] and render_calls["n"] == total_chunks_hint["n"]:
            cancellable["on"] = False
            # Flip the durable job to cancelling during the LAST chunk's
            # render — the loop's post-chunk fence must then fire before
            # stitch/publication.
            _flip_job_cancelling(factory, job.job_id)
        return render_orig(**kwargs)

    monkeypatch.setattr(jobs_mod, "_render_chunk_via_real_executor", _render_with_cancel)

    with factory() as s:
        from app.persistence.jobs import JobRepository as _JR

        repo = _JR(s)
        lease = repo.acquire_lease(job.job_id, "worker-a", ttl_seconds=60)
        repo.transition_job(
            job.job_id,
            "running",
            actor="worker",
            expected_revision=repo.get_job(job.job_id).revision,
            fence_token=lease.fence_token,
        )
        s.commit()

    total_chunks_hint = {
        "n": len(
            factory()
            .execute(text("SELECT id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": run_id})
            .mappings()
            .all()
        )
    }
    assert total_chunks_hint["n"] >= 2

    # Arm the cancel: it fires during the LAST chunk's render, so the durable
    # cancel commits while the chunk loop is still running (the pre-stitch
    # fence then withholds stitch/publication/completion).
    cancellable["on"] = True
    _run_claimed_worker(svc, job.job_id)

    assert _job_state_by_id(factory, job.job_id) == "cancelled"
    assert _run_status(factory, run_id) == "cancelled"
    assert render_calls["n"] == total_chunks_hint["n"], "cancel must land during the last chunk render"
    with factory() as s:
        rows = s.execute(
            text("SELECT verified FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY chunk_index"), {"rid": run_id}
        ).mappings().all()
        assert all(r["verified"] == 1 for r in rows), "test precondition: every chunk rendered before the cancel"
        pubs = s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()
        assert all(str(r["state"]) != "completed" for r in pubs), "publication survived post-chunk cancel fence"


def _flip_job_cancelling(factory, job_id: str) -> None:
    """Durable cancel signal, applied exactly like the API route would.

    Opens its own short write transaction on the shared SQLite file (same
    shape as a concurrent route request while the worker runs).
    """
    from app.persistence.jobs import JobRepository as _JR

    with factory() as js:
        jr = _JR(js)
        jrow = jr.get_job(job_id)
        if jrow.state == "running":
            jr.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=jrow.revision,
                reason_code="CANCEL_REQUESTED",
            )
            js.commit()


def test_cancel_mid_chunk_stops_without_further_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullet 3: the cancel signal lands DURING chunk 0's render.

    Chunk 0 completes (its effect was already started — cancel never
    mid-destroys an in-flight effect), then the loop fence stops chunk 1:
    checkpoint stays at next_chunk_index=1, run -> cancelled, job history
    shows cancelling -> cancelled, and NO publication exists.
    """
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    import app.workflow.s10_full_apply_jobs as jobs_mod

    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    job = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "midchunk")

    render_orig = jobs_mod._render_chunk_via_real_executor
    calls = {"n": 0}

    def _render_with_cancel(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            _flip_job_cancelling(factory, job.job_id)
        return render_orig(**kwargs)

    monkeypatch.setattr(jobs_mod, "_render_chunk_via_real_executor", _render_with_cancel)
    _run_claimed_worker(svc, job.job_id)

    assert _job_state_by_id(factory, job.job_id) == "cancelled"
    assert _run_status(factory, run_id) == "cancelled"
    assert calls["n"] == 1, "worker must not start chunk 1 after the cancel fence"
    with factory() as s:
        rows = s.execute(
            text("SELECT verified FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY chunk_index"),
            {"rid": run_id},
        ).mappings().all()
        assert rows[0]["verified"] == 1 and all(r["verified"] == 0 for r in rows[1:])
        pubs = s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()
        assert all(str(r["state"]) != "completed" for r in pubs)
        from app.persistence.jobs import JobRepository as _JR

        steps = _JR(s).list_steps(job.job_id)
        cp = steps[0].checkpoint or {}
        if isinstance(cp, str):
            cp = json.loads(cp)
        assert cp.get("next_chunk_index") == 1, cp
        assert cp.get("completed") is not True
    events = _job_event_pairs(factory, job.job_id)
    assert ("running", "cancelling", "api") in events, events
    assert ("cancelling", "cancelled", "worker") in events, events


def test_cancel_concurrent_with_claim_drains_with_history_invariants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 bullets 2+8: cancel lands right after the claim, worker drains.

    The signal is set while the first chunk's state mark runs; after the
    worker drains: run stays cancelled, job history carries running ->
    cancelling (actor api) -> cancelled, ZERO completed publications and no
    completed checkpoint anywhere.
    """
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    import app.workflow.s10_full_apply_jobs as jobs_mod

    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    job = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "concurrent")

    cs_orig = jobs_mod._mark_chunk_state
    flipped = {"on": False}

    def _cs_with_cancel(session_factory, ws: str, chunk_id: str, state: str) -> None:
        if state == "running" and not flipped["on"]:
            flipped["on"] = True
            _flip_job_cancelling(session_factory, job.job_id)
        cs_orig(session_factory, ws, chunk_id, state)

    monkeypatch.setattr(jobs_mod, "_mark_chunk_state", _cs_with_cancel)
    _run_claimed_worker(svc, job.job_id)

    assert _job_state_by_id(factory, job.job_id) == "cancelled"
    assert _run_status(factory, run_id) == "cancelled"
    with factory() as s:
        pubs = s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": run_id}
        ).mappings().all()
        assert all(str(r["state"]) != "completed" for r in pubs)
        from app.persistence.jobs import JobRepository as _JR

        steps = _JR(s).list_steps(job.job_id)
        assert all(
            not (isinstance(st.checkpoint, dict) and st.checkpoint.get("completed") is True)
            and not (isinstance(st.checkpoint, str) and json.loads(st.checkpoint).get("completed") is True)
            for st in steps
        )
    events = _job_event_pairs(factory, job.job_id)
    assert ("running", "cancelling", "api") in events, events
    assert ("cancelling", "cancelled", "worker") in events, events


def test_publication_exact_hash_size_decodable_shot_order_cuts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_pub_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        status = s.execute(text("SELECT status, frame_count, apply_checkpoint_id, apply_checkpoint_hash FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).mappings().first()
        assert status is not None and status["status"] == "completed"
        pubs = s.execute(text("SELECT id, artifact_id, content_hash, frame_count, state, checkpoint_id, checkpoint_hash FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": run_id}).mappings().all()
        completed = [p for p in pubs if p["state"] == "completed"]
        assert len(completed) == 1
        pub = completed[0]
        assert pub["checkpoint_id"] == status["apply_checkpoint_id"]
        assert pub["checkpoint_hash"] == status["apply_checkpoint_hash"]
        art = s.execute(text("SELECT relative_path, sha256, size_bytes, state FROM artifact WHERE id=:aid"), {"aid": pub["artifact_id"]}).mappings().first()
        assert art is not None and art["state"] == "ready"
        assert art["sha256"] is not None and len(art["sha256"]) == 64
        assert int(art["size_bytes"]) > 0
        assert ".partial" not in art["relative_path"]
        abs_p = artifacts_root / art["relative_path"]
        assert abs_p.is_file()
        from app.persistence.artifacts import hash_file

        assert hash_file(abs_p) == art["sha256"]
        assert abs_p.stat().st_size == int(art["size_bytes"])
        from app.services.renderer_routes.composite import decode_rgb_frames

        frames = decode_rgb_frames(abs_p)
        assert len(frames) == pub["frame_count"] == status["frame_count"] == 100
        assert len(frames) == 100


def test_tampered_ready_artifact_quarantined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    import app.workflow.s10_full_apply_jobs as mod
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    monkeypatch.setattr(mod, "_TEST_STOP_AFTER_CHUNK", 0)
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_tamp_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        aid = s.execute(text("SELECT artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid AND chunk_index=0"), {"rid": run_id}).scalar()
        art = s.execute(text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": aid}).mappings().first()
        abs_p = artifacts_root / art["relative_path"]
        data = abs_p.read_bytes()
        abs_p.write_bytes(data + bytes([0, 1, 2]))
    monkeypatch.setattr(mod, "_TEST_STOP_AFTER_CHUNK", None)
    job2 = svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_tamp2_{run_id[:8]}")
    _post_step_checkpoint(factory, job2.job_id, {"schema_version": 1, "run_id": run_id, "next_chunk_index": 0, "executed": []})
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        new_aid = s.execute(text("SELECT artifact_id, verified FROM s10_full_apply_chunk WHERE run_id=:rid AND chunk_index=0"), {"rid": run_id}).mappings().first()
        assert int(new_aid["verified"]) == 1
        art2 = s.execute(text("SELECT sha256, relative_path FROM artifact WHERE id=:aid"), {"aid": new_aid["artifact_id"]}).mappings().first()
        from app.persistence.artifacts import hash_file

        assert hash_file(artifacts_root / art2["relative_path"]) == art2["sha256"]


# ═══════════════════════════════════════════════════════════════════════════
# C4 NEGATIVE TESTS — every fabricated/missing input fails closed
# ═══════════════════════════════════════════════════════════════════════════


def _run_and_check_failed(factory, run_id: str) -> None:
    with factory() as s:
        status = s.execute(text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar()
        assert status == "failed", f"run should be failed (fail closed), got {status!r}"
        completed = s.execute(text("SELECT COUNT(*) FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": run_id}).scalar()
        assert completed == 0
        run_completed = s.execute(text("SELECT COUNT(*) FROM s10_full_apply_run WHERE id=:rid AND status='completed'"), {"rid": run_id}).scalar()
        assert run_completed == 0


def test_missing_source_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    manifest = _make_job_manifest(seed, run_id, artifacts_root, authority)
    manifest["source_media_rel"] = "s10_full_apply/missing/source.mp4"  # pinned path does not exist
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, manifest, workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_missrc_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    _run_and_check_failed(factory, run_id)


def test_missing_asset_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    manifest = _make_job_manifest(seed, run_id, artifacts_root, authority)
    manifest["replacement_assets"][seed["role_id"]]["rel"] = "s10_full_apply/_assets/does_not_exist.png"
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, manifest, workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_missast_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    _run_and_check_failed(factory, run_id)


def test_fabricated_mapping_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C8: a fabricated mapping (client tampering the canonical authority to
    drop the pinned affected_region) fails closed — zero render/publication.

    The worker re-derives the authority fingerprint from the persisted v2 row
    and fences ANY mutation of the manifest authority before render; a client
    can never supply its own mapping authority.
    """
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    manifest = _make_job_manifest(seed, run_id, artifacts_root, authority)
    # Client tampers the manifest authority mapping (drops affected_region).
    manifest["render_authority"]["mapping"]["mappings"][0]["affected_region"] = None
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, manifest, workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_fabmap_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    _run_and_check_failed(factory, run_id)


def test_unsupported_route_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A manifest authority whose route was tampered to a planner-known but
    non-executable route (mesh_warp) must fail, never downgrade to
    sprite_affine.  The worker re-derives the fingerprint from the persisted
    v2 row; a tampered authority (or a fabricated route) fails closed before
    any render/publication."""
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    manifest = _make_job_manifest(seed, run_id, artifacts_root, authority)
    manifest["render_authority"]["mapping"]["mappings"][0]["route"] = "mesh_warp"
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, manifest, workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_route_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    _run_and_check_failed(factory, run_id)


def test_zero_chunks_fails_closed_non_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    with factory() as s:
        s.execute(text("DELETE FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": run_id})
        s.commit()
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, _make_job_manifest(seed, run_id, artifacts_root, authority), workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_zero_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    _run_and_check_failed(factory, run_id)


def test_caller_crash_hook_injection_rejected_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A manifest carrying stop_after_chunk is rejected outright (fail closed)."""
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    manifest = _make_job_manifest(seed, run_id, artifacts_root, authority, stop_key=True)
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, manifest, workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_hook_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]
    _run_and_check_failed(factory, run_id)


# ═══════════════════════════════════════════════════════════════════════════
# C6 — immutable manifest fencing (reconciler) + long-path evidence
# ═══════════════════════════════════════════════════════════════════════════


def _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root: Path, tag: str) -> object:
    """Create an S10 job, claim + transition it to running, return the job object."""
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    job = svc.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        _make_job_manifest(seed, run_id, artifacts_root, authority),
        workspace_id=seed["workspace_id"],
        owner_type="project",
        owner_id=seed["project_id"],
        idempotency_key=f"s10_fence_{tag}_{run_id[:8]}",
    )
    with factory() as s:
        from app.persistence.jobs import JobRepository

        repo = JobRepository(s)
        lease = repo.acquire_lease(job.job_id, "worker-a", ttl_seconds=60)
        repo.transition_job(
            job.job_id,
            "running",
            actor="worker",
            expected_revision=repo.get_job(job.job_id).revision,
            fence_token=lease.fence_token,
        )
        s.commit()
    return job


def _expire_s10_lease(factory, job_id: str) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text as _text

    past = datetime.now(UTC) - timedelta(seconds=10)
    with factory() as s:
        s.execute(
            _text(
                "UPDATE job_lease SET expires_at = :past, heartbeat_at = :past, "
                "acquired_at = :past2 WHERE job_id = :jid"
            ),
            {"past": past, "past2": past - timedelta(seconds=60), "jid": job_id},
        )
        s.commit()


def test_arbitrary_s10_manifest_mutation_fenced_input_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 3: ANY S10 manifest mutation after creation (incl. source/asset pins)
    -> reconciler fails the job INPUT_CHANGED; zero resume render/publication."""
    from datetime import UTC, datetime

    from app.workflow.job_reconciler import ReconcileConfig, JobReconciler

    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    job = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "mut")
    # Mutate the manifest AFTER creation — any key, including a source pin.
    from app.persistence.jobs import JobRepository
    from sqlalchemy import text as _text

    with factory() as s:
        s.execute(
            _text("UPDATE job SET input_manifest_json = :m WHERE id = :jid"),
            {"m": '{"run_id": "' + run_id + '", "workspace_id": "' + seed["workspace_id"] + '", "tampered": true}', "jid": job.job_id},
        )
        s.commit()
    _expire_s10_lease(factory, job.job_id)

    class _Clock:
        now = datetime.now(UTC)

    rec = JobReconciler(
        factory,
        config=ReconcileConfig(batch_size=50, fence_grace_seconds=0.0, poll_interval=0.01),
        clock=lambda: _Clock.now,
    )
    report = rec.reconcile_once()
    with factory() as s:
        from app.persistence.models import Job as _Job
        from sqlalchemy import select as _sel

        row = s.scalar(_sel(_Job).where(_Job.id == job.job_id))
        assert row is not None and row.state == "failed"
        repo = JobRepository(s)
        events = [e for e in repo.list_events(job.job_id) if e.to_state == "failed"]
        assert events and events[-1].reason_code == "INPUT_CHANGED"
        # zero resume render/publication
        status = s.execute(_text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar()
        completed = s.execute(_text("SELECT COUNT(*) FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": run_id}).scalar()
        assert status != "completed"
        assert completed == 0
    assert report.failed == 1


def test_restart_on_unchanged_manifest_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 3 (positive): a fenced S10 job with an UNCHANGED manifest is requeued,
    then a fresh worker run completes — no INPUT_CHANGED, one publication."""
    from datetime import UTC, datetime

    from app.workflow.job_reconciler import ReconcileConfig, JobReconciler

    _db, artifacts_root, factory, seed = _seed(tmp_path)
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    job = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "ok")
    _expire_s10_lease(factory, job.job_id)

    class _Clock:
        now = datetime.now(UTC)

    rec = JobReconciler(
        factory,
        config=ReconcileConfig(batch_size=50, fence_grace_seconds=0.0, poll_interval=0.01),
        clock=lambda: _Clock.now,
    )
    report = rec.reconcile_once()
    with factory() as s:
        from app.persistence.models import Job as _Job
        from sqlalchemy import select as _sel

        row = s.scalar(_sel(_Job).where(_Job.id == job.job_id))
        assert row is not None and row.state == "queued", f"unchanged manifest must requeue, got {row.state if row else None}"
    assert report.requeued == 1
    # Fresh worker run completes the run.
    svc._worker.run_once()  # type: ignore[attr-defined]
    with factory() as s:
        from sqlalchemy import text as _text

        status = s.execute(_text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar()
        completed = s.execute(_text("SELECT COUNT(*) FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": run_id}).scalar()
        assert status == "completed"
        assert completed == 1


def test_long_nested_path_gt_260_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req 5: FullApply media/evidence survive final/staging paths >260 chars on
    Windows — final + sidecar under the managed root, SHA/size exact, zero
    orphan .staging files."""
    # Build a DEEP managed root so chunk/evidence absolute paths exceed 260.
    deep = tmp_path
    parts = ["s10_longpath", "nest_" + "x" * 30, "nest_" + "y" * 30, "nest_" + "z" * 30]
    for p in parts:
        deep = deep / p
    deep.mkdir(parents=True, exist_ok=True)
    # Managed root itself deep; chunk rel paths add ~60 more chars.
    artifacts_root = deep / "managed"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    _db, seeded_root, factory, seed = _seed(tmp_path)
    # The seeded persisted authority media (source/asset/mask) lives under the
    # SHALLOW seeded root; move those files to the DEEP managed root so every
    # artifact row's backing file exists at the final root (relative paths in
    # the artifact rows are identical).
    import shutil

    seeded_auth = seeded_root / "s10_full_apply" / "_authority"
    if seeded_auth.exists():
        dst_auth = artifacts_root / "s10_full_apply" / "_authority"
        dst_auth.mkdir(parents=True, exist_ok=True)
        for child in seeded_auth.iterdir():
            if child.is_dir():
                shutil.copytree(child, dst_auth / child.name, dirs_exist_ok=True)
            else:
                shutil.copy2(child, dst_auth / child.name)
    # Re-point the registered JobService at the deep managed root.
    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY

    # Manifest pins media under the deep root; stage real source/asset there.
    m = _make_job_manifest(seed, run_id, artifacts_root, authority)
    svc.create_job(JOB_TYPE_S10_FULL_APPLY, m, workspace_id=seed["workspace_id"], owner_type="project", owner_id=seed["project_id"], idempotency_key=f"s10_long_{run_id[:8]}")
    svc._worker.run_once()  # type: ignore[attr-defined]

    # Sanity: at least one final/staging-class path exceeded 260 chars.
    long_seen = False
    with factory() as s:
        from sqlalchemy import text as _text

        rows = s.execute(_text("SELECT relative_path FROM artifact WHERE workspace_id='default' AND state='ready'")).mappings().all()
        assert len(rows) > 0
        for r in rows:
            abs_p = _lp_test(artifacts_root / r["relative_path"])
            assert abs_p.is_file(), f"missing artifact file {r['relative_path']}"
            if len(str(abs_p)) > 260:
                long_seen = True
            # SHA/size exact vs persisted row
            from app.persistence.artifacts import hash_file

            sha = s.execute(_text("SELECT sha256, size_bytes FROM artifact WHERE relative_path=:rel"), {"rel": r["relative_path"]}).mappings().first()
            assert sha is not None
            assert hash_file(abs_p) == sha["sha256"]
            assert abs_p.stat().st_size == int(sha["size_bytes"])
            # sidecar evidence exists next to every chunk/stitch artifact
            # (persisted authority source/asset/mask rows are inputs, not
            # render outputs — they never carry an evidence sidecar)
            if f"s10_full_apply/{run_id}" in r["relative_path"]:
                ev = _lp_test(artifacts_root / (r["relative_path"] + ".evidence.json"))
                assert ev.is_file(), f"missing evidence sidecar for {r['relative_path']}"
                if len(str(ev)) > 260:
                    long_seen = True
        # zero orphan .staging under the managed root (force-prefix so the
        # rglob descends through >260-char children on Windows)
        staging = [p for p in _lp_test(artifacts_root, force=True).rglob("*.staging")]
        assert staging == [], f"orphan staging files: {staging}"
        status = s.execute(_text("SELECT status FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).scalar()
        completed = s.execute(_text("SELECT COUNT(*) FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": run_id}).scalar()
        assert status == "completed"
        assert completed == 1
    assert long_seen, "test must actually exercise a >260-char path"




# ── S10-T01C-C10: completion-CAS exit in the has_completed resume branch (F2) ─


def _c10_flip_cancel(factory, job_id: str, run_id: str) -> None:
    """Durable cancel landing BETWEEN the resume pre-check and the completion
    CAS — applies the exact same atomic run+job transition the cancel route
    uses (job -> cancelling, run -> cancelled, one commit)."""
    from app.persistence.jobs import JobRepository as _JR

    with factory() as js:
        jr = _JR(js)
        jrow = jr.get_job(job_id)
        if jrow.state in ("queued", "running"):
            jr.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=jrow.revision,
                reason_code="CANCEL_REQUESTED",
            )
        js.execute(
            text("UPDATE s10_full_apply_run SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=:rid AND workspace_id=:ws AND status != 'cancelled'"),
            {"rid": run_id, "ws": "default"},
        )
        js.commit()


def _c10_completed_checkpoint(factory, job_id: str) -> bool:
    with factory() as s:
        from sqlalchemy import select as _sel

        from app.persistence.models import JobStep as _JobStep

        row = s.scalar(_sel(_JobStep).where(_JobStep.job_id == job_id))
        if row is None:
            return False
        # ORM column is checkpoint_json (str|None); parse defensively.
        raw = getattr(row, "checkpoint_json", None)
        cp: object = None
        if isinstance(raw, str):
            try:
                cp = json.loads(raw)
            except Exception:
                cp = {}
        if cp is None:
            return False
        return isinstance(cp, dict) and cp.get("completed") is True


def test_c10_resume_completion_race_cancel_wins_no_completed_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C10 F2: deterministic completed-publication resume race — the pre-check
    sees no cancel, the durable cancel commits, THEN the completion CAS runs.
    The cancel must win: run stays cancelled, NO completed checkpoint, no new
    publication, job drains cancelling/cancelled."""
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    import app.workflow.s10_full_apply_jobs as jobs_mod

    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)

    # Real worker completes the run once (truthful completion baseline).
    job1 = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "c10a")
    _run_claimed_worker(svc, job1.job_id)
    assert _run_status(factory, run_id) == "completed"
    assert _c10_completed_checkpoint(factory, job1.job_id) is True

    # Crash-after-publication-commit simulation: the publication row is
    # durable (completed) but the run completion is replayed by a fresh job.
    with factory() as s:
        s.execute(
            text("UPDATE s10_full_apply_run SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=:rid"),
            {"rid": run_id},
        )
        s.commit()
    assert _run_status(factory, run_id) == "running"

    job2 = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "c10b")

    # Test-only barrier: when the completion-CAS helper exists (post-fix), the
    # cancel lands BETWEEN the false pre-check and the CAS — the mandated race.
    if hasattr(jobs_mod, "_complete_run_cas"):
        real_cas = jobs_mod._complete_run_cas

        def _cancel_then_cas(*args, **kwargs):  # type: ignore[no-untyped-def]
            _c10_flip_cancel(factory, job2.job_id, run_id)
            return real_cas(*args, **kwargs)

        monkeypatch.setattr(jobs_mod, "_complete_run_cas", _cancel_then_cas)

    _run_claimed_worker(svc, job2.job_id)

    assert _run_status(factory, run_id) == "cancelled", "cancel must win the completion race"
    assert _c10_completed_checkpoint(factory, job2.job_id) is False, "no completed checkpoint after cancel"
    assert _job_state_by_id(factory, job2.job_id) in ("cancelling", "cancelled")
    with factory() as s:
        pubs = s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"),
            {"rid": run_id},
        ).mappings().all()
    assert len(pubs) == 1, f"no NEW publication may be created, got {pubs}"
    assert str(pubs[0]["state"]) == "completed", "the pre-existing publication must be untouched"


def test_c10_resume_no_cancel_control_completes_truthfully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C10 F2 control: the same resume path WITHOUT a cancel must complete
    truthfully — verified CAS first, THEN the completed checkpoint."""
    _db, artifacts_root, factory, seed = _seed(tmp_path)
    import app.workflow.s10_full_apply_jobs as jobs_mod

    svc = _register(monkeypatch, artifacts_root, factory)
    run_id, authority = _submit_run(factory, seed)

    job1 = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "c10c")
    _run_claimed_worker(svc, job1.job_id)
    assert _run_status(factory, run_id) == "completed"

    with factory() as s:
        s.execute(
            text("UPDATE s10_full_apply_run SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=:rid"),
            {"rid": run_id},
        )
        s.commit()

    job2 = _s10_job_running(factory, svc, seed, run_id, authority, artifacts_root, "c10d")
    # If the shared CAS helper exists, assert the contract holds through it.
    if hasattr(jobs_mod, "_complete_run_cas"):
        real_cas = jobs_mod._complete_run_cas

        def _passthrough_cas(*args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_cas(*args, **kwargs)
            assert result is True, "no-cancel resume CAS must verify completion"
            return result

        monkeypatch.setattr(jobs_mod, "_complete_run_cas", _passthrough_cas)

    _run_claimed_worker(svc, job2.job_id)

    assert _run_status(factory, run_id) == "completed"
    assert _c10_completed_checkpoint(factory, job2.job_id) is True
    with factory() as s:
        pubs = s.execute(
            text("SELECT state FROM s10_full_apply_publication WHERE run_id=:rid"),
            {"rid": run_id},
        ).mappings().all()
    assert len(pubs) == 1 and str(pubs[0]["state"]) == "completed"
    assert _job_state_by_id(factory, job2.job_id) == "completed"
