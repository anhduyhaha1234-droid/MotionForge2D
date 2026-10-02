"""DELTA-F1 probe — REAL public-path round-trip proof (base RED / fix GREEN).

Drives the ONLY public persist path (FullApplyService.submit) for a
comfy_shot_engine plan, then measures, in order:

  1. planner members  (plan["chunks"][i]["member_layer_ids"])
  2. SQLite PRAGMA of s10_full_apply_chunk (column presence)
  3. raw DB rows (member_layer_ids_json, if the column exists)
  4. repository read  (S10ApplyRepository.list_chunks -> record.member_layer_ids)
  5. worker read      (app.workflow.s10_full_apply_jobs._list_chunks)
  6. worker guard     (_render_shot_chunk_via_engine) with a SCRIPTED engine
     standing at the engine boundary (no GPU, no ComfyUI).

Exit code 0 = GREEN (members survive end-to-end AND the worker proceeds),
1 = RED (defect reproduced).  Prints a JSON verdict so a reviewer can diff
base vs fixed without trusting prose.

Usage:
    python tools/probe_roundtrip.py <worktree-root> <scratch-dir>

Backslashes are never used in this file on purpose (MSYS heredoc trap #32).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

WT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
SCRATCH = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(os.environ.get("TEMP", ".")) / "delta_f1_probe"
sys.path.insert(0, str(WT))

REPORT: dict = {"worktree": str(WT), "steps": {}}


def _sha_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_mp4(path: Path, frames: int, seed: int = 0) -> Path:
    import numpy as np

    from app.services.renderer_routes.composite import write_frames_mp4

    path.parent.mkdir(parents=True, exist_ok=True)
    arr = []
    for i in range(frames):
        f = np.zeros((48, 64, 3), dtype=np.uint8)
        f[:, :, 0] = (int(seed) + i * 3) % 255
        f[:, :, 1] = 60
        f[:, :, 2] = 200
        arr.append(f)
    write_frames_mp4(arr, path, fps=30.0)
    return path


def main() -> int:
    import uuid

    import numpy as np
    from sqlalchemy import text

    from app.persistence import create_engine_for_path, create_session_factory

    scratch = SCRATCH
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    db = scratch / "probe.db"
    artifacts = scratch / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    # -- schema via the REAL migration chain (proves the migration applies) ----
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///" + db.as_posix())
    command.upgrade(cfg, "head")

    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    import hashlib
    import cv2

    from app.persistence.artifacts import hash_file

    ws = "default"
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, ws) is None:
            s.add(Workspace(id=ws, name=ws))
            s.commit()
    with factory() as s:
        proj = "proj-" + uuid.uuid4().hex[:6]
        vid = "vid-" + uuid.uuid4().hex[:6]
        scene_pk = "sc-" + uuid.uuid4().hex[:6]
        s.execute(text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"), {"p": proj, "w": ws})
        s.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"), {"v": vid, "p": proj})
        s.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,0,99,0,1000,'pending')"), {"s": scene_pk, "v": vid})
        char = "ch-" + uuid.uuid4().hex[:6]
        s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,'Hero',:code)"), {"c": char, "w": ws, "code": "hero_" + uuid.uuid4().hex[:4]})
        pv = "pv-" + uuid.uuid4().hex[:6]
        s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"), {"pv": pv, "c": char, "w": ws})
        role = "role-" + uuid.uuid4().hex[:6]
        s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"), {"r": role, "w": ws, "p": proj, "v": vid})
        rc = "rc-" + uuid.uuid4().hex[:6]
        params = {"anchor": {"x": 0.5, "y": 0.5}, "scale": 1.0, "fit_mode": "contain", "clip_mode": "asset_alpha", "offset": {"x": 0.0, "y": 0.0}, "rotation_offset_deg": 0.0, "opacity": 1.0}
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"), {"rc": rc, "w": ws, "p": proj, "r": role, "c": char, "pv": pv, "params": json.dumps(params, sort_keys=True, separators=(",", ":"))})
        src_rel = "s10_full_apply/_probe/" + vid + "/source.mp4"
        src_abs = artifacts / src_rel
        _write_mp4(src_abs, 100, seed=1)
        src_sha = hash_file(src_abs)
        src_art = "art-src-" + uuid.uuid4().hex[:6]
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','video',:rel,'ready',:sha,:sz,1)"), {"id": src_art, "rel": src_rel, "sha": src_sha, "sz": src_abs.stat().st_size})
        s.execute(text("UPDATE video_item SET source_artifact_id=:aid WHERE id=:vid"), {"aid": src_art, "vid": vid})
        asset_rel = "s10_full_apply/_probe/" + vid + "/asset.png"
        asset_abs = artifacts / asset_rel
        asset_abs.parent.mkdir(parents=True, exist_ok=True)
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        hx = hashlib.sha256(pv.encode()).hexdigest()
        img[:, :, 0] = int(hx[0:2], 16)
        img[:, :, 1] = int(hx[2:4], 16)
        img[:, :, 2] = int(hx[4:6], 16)
        img[:, :, 3] = 255
        cv2.imwrite(str(asset_abs), img)
        asset_art = "art-asset-" + uuid.uuid4().hex[:6]
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"), {"id": asset_art, "rel": asset_rel, "sha": hash_file(asset_abs), "sz": asset_abs.stat().st_size})
        s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"), {"id": "ca-" + uuid.uuid4().hex[:6], "pv": pv, "aid": asset_art})
        s.commit()
        seed = {"workspace_id": ws, "project_id": proj, "video_item_id": vid, "pack_version_id": pv, "reskin_config_id": rc, "role_id": role}

    # -- v2 checkpoint (same shape the workflow tests freeze) ------------------
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository

    h64 = lambda s: hashlib.sha256(s.encode()).hexdigest()
    with factory() as s:
        src_art = s.execute(text("SELECT id FROM artifact WHERE id LIKE 'art-src-%' AND workspace_id=:w ORDER BY id LIMIT 1"), {"w": ws}).scalar()
        scene_id = s.execute(text("SELECT id FROM scene WHERE video_item_id=:v ORDER BY position LIMIT 1"), {"v": seed["video_item_id"]}).scalar()
        mask_art = "art-mask-" + uuid.uuid4().hex[:6]
        mask_rel = "s10_full_apply/_probe/" + seed["video_item_id"] + "/mask.png"
        mask_abs = artifacts / mask_rel
        mask_abs.parent.mkdir(parents=True, exist_ok=True)
        mask_img = np.zeros((40, 40, 4), dtype=np.uint8)
        mask_img[:, :, 3] = 255
        cv2.imwrite(str(mask_abs), mask_img)
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"), {"id": mask_art, "rel": mask_rel, "sha": hash_file(mask_abs), "sz": mask_abs.stat().st_size})
        seg_repo = StructuralEvidenceRepository(s)
        seg_rec, _sc = seg_repo.create_segment(
            ws, seed["project_id"], seed["video_item_id"], seed["role_id"], str(scene_id), "Hero",
            0, 99, 0, 3300, "1", kind="character", confidence_source="user",
            segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [str(seg_rec.id)],
            "fingerprints": {"z_order": h64("z"), "contacts": h64("c")},
            "segments": [{"occurrence_segment_id": str(seg_rec.id), "route": "sprite_affine", "anchor": {"x": 0.5, "y": 0.5}, "start_frame": 0, "end_frame": 99, "provenance": {"why": "delta-f1-probe"}}],
            "policy_version": "structural-thresholds-v1",
        }
        man, _mc = lock_repo.create_manifest(ws, seed["project_id"], seed["video_item_id"], "1", manifest_dict)
        lock_repo.record_render_route(ws, seed["project_id"], seed["video_item_id"], str(seg_rec.id), "sprite_affine", 0.5, 0.5, 0, 99, provenance={"why": "delta-f1-probe"}, reasons=["delta-f1-probe"], structural_lock_manifest_id=man.id)
        s.execute(text("UPDATE reskin_config SET structural_lock_manifest_id=:m, lock_policy_version=:p WHERE id=:rc"), {"m": man.id, "p": man.policy_version, "rc": seed["reskin_config_id"]})
        s.flush()
        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint_v2(ws, reskin_config_id=str(seed["reskin_config_id"]), expected_reskin_revision=1, pack_version_ids=[str(seed["pack_version_id"])], note="delta-f1 probe")
        assert created is True
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = str(record.reskin_config_revision)

    # -- 1. PUBLIC submit with the comfy backend -------------------------------
    from app.services.s10_full_apply import FullApplyService

    graph_sha = _sha_file(WT / "app" / "media_workflows" / "wan_shot_v1.json")
    with factory() as s:
        svc = FullApplyService(s)
        rec, created, plan = svc.submit(
            workspace_id=ws,
            project_id=seed["project_id"],
            video_item_id=seed["video_item_id"],
            apply_checkpoint_id=seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"],
            expected_checkpoint_revision=int(seed["checkpoint_revision"]),
            chunk_config={"chunk_frames": 120, "overlap_frames": 4},
            execution_backend={"backend": "comfy_shot_engine", "profile_id": "wan_animate2_int8_pad640x368_cacheoff", "graph_sha256": graph_sha, "shot_prompts": {scene_pk: "probe prompt"}},
        )
        s.commit()
        run_id = rec.id

    plan_members = {c["chunk_id"]: list(c.get("member_layer_ids") or []) for c in plan["chunks"]}
    REPORT["steps"]["1_plan_members"] = plan_members
    REPORT["run_id"] = run_id

    # -- 2. PRAGMA -------------------------------------------------------------
    import sqlite3

    con = sqlite3.connect(str(db))
    cols = [r[1] for r in con.execute("PRAGMA table_info(s10_full_apply_chunk)").fetchall()]

    # -- 3. raw rows -----------------------------------------------------------
    have_col = "member_layer_ids_json" in cols
    raw_rows = []
    if have_col:
        raw_rows = con.execute("SELECT chunk_index, natural_key, member_layer_ids_json FROM s10_full_apply_chunk WHERE run_id=? ORDER BY chunk_index", (run_id,)).fetchall()
    else:
        raw_rows = con.execute("SELECT chunk_index, natural_key FROM s10_full_apply_chunk WHERE run_id=? ORDER BY chunk_index", (run_id,)).fetchall()
    con.close()
    REPORT["steps"]["2_pragma"] = {"n_cols": len(cols), "has_member_column": have_col, "columns": cols}
    REPORT["steps"]["3_raw_rows"] = raw_rows

    # -- 4. repository read ----------------------------------------------------
    from app.persistence.s10_full_apply import S10ApplyRepository

    with factory() as s:
        repo_rows = S10ApplyRepository(s).list_chunks(ws, run_id)
        repo_members = {r.id: list(getattr(r, "member_layer_ids", ()) or ()) for r in repo_rows}
    REPORT["steps"]["4_repo_members"] = repo_members

    # -- 5. worker read --------------------------------------------------------
    from app.workflow import s10_full_apply_jobs as jobs

    worker_rows = jobs._list_chunks(factory, ws, run_id)
    worker_members = [list(r.get("member_layer_ids") or []) for r in worker_rows]
    worker_chunk_ids = [jobs._shot_chunk_identity(r)[1] for r in worker_rows]
    REPORT["steps"]["5_worker_members"] = dict(zip(worker_chunk_ids, worker_members, strict=False))

    # -- 6. worker guard -> engine boundary ------------------------------------
    managed = scratch / "managed"
    stage_src = _write_mp4(managed / "src" / "source.mp4", 100, seed=7)
    shot_id = worker_rows[0]["shot_id"]
    members = worker_members[0]
    assets = {}
    for lid in members:
        p = managed / "assets" / (lid + ".png")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG" + b"asset" * 4)
        assets[lid] = {"artifact_id": "art-" + lid[:8], "rel": "assets/" + lid + ".png", "sha256": _sha_file(p), "size_bytes": p.stat().st_size}
    anchor = managed / "anchor" / "anchor_00001_.png"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_bytes(b"\x89PNG" + b"anchor" * 4)
    authority = dict(plan["render_authority"])
    backend = {
        "backend": "comfy_shot_engine",
        "profile_id": "wan_animate2_int8_pad640x368_cacheoff",
        "capability": "source_video_motion_transfer",
        "graph_file": "app/media_workflows/wan_shot_v1.json",
        "graph_sha256": graph_sha,
        "output_node": "246",
        "seed": 42,
        "shot_prompts": {shot_id: "probe prompt"},
        "shot_anchors": {shot_id: {"relative_path": "anchor/anchor_00001_.png", "sha256": _sha_file(anchor)}},
    }
    manifest = {
        "managed_root": str(managed),
        "source_media_rel": "src/source.mp4",
        "source_media_sha256": _sha_file(stage_src),
        "source_media_size_bytes": stage_src.stat().st_size,
        "replacement_assets": assets,
    }
    engine_calls: list[str] = []

    def fake_render(*, managed_root, request):  # noqa: ANN001, ANN202
        engine_calls.append(str(request["chunk_id"]))
        rel = "engine_out/" + request["chunk_id"] + "_00001_.mp4"
        path = _write_mp4(managed_root / rel, 10, seed=3)
        from app.services.renderer_routes.composite import canonical_frame_sha256, decode_rgb_frames

        frames = decode_rgb_frames(path)
        return {
            "output_relative_path": rel,
            "output_sha256": _sha_file(path),
            "output_size_bytes": path.stat().st_size,
            "decoded_sha256": canonical_frame_sha256(frames),
            "decoded_frame_count": len(frames),
            "fps_num": 30,
            "fps_den": 1,
            "prompt_id": "probe-pid",
            "graph_object_sha256_submitted": "e" * 64,
        }

    jobs._run_shot_render = fake_render  # engine boundary (scripted, labeled)
    render_error = None
    render_rel = None
    try:
        row = dict(worker_rows[0])
        rel_out, sha_out, size_out, ev = jobs._render_shot_chunk_via_engine(
            managed_root=managed,
            run_id=run_id,
            chunk=row,
            chunk_index=0,
            fps_num=30,
            fps_den=1,
            workspace_id=ws,
            project_id=seed["project_id"],
            video_item_id=seed["video_item_id"],
            authority=authority,
            manifest=manifest,
            backend=backend,
            session_factory=factory,
        )
        render_rel = str(rel_out)
        REPORT["steps"]["6_render"] = {"ok": True, "rel": render_rel, "sha": sha_out, "size": size_out, "engine_calls": engine_calls}
    except Exception as exc:  # noqa: BLE001
        render_error = type(exc).__name__ + ": " + str(exc)
        REPORT["steps"]["6_render"] = {"ok": False, "error": render_error, "engine_calls": engine_calls}

    # -- verdict ---------------------------------------------------------------
    members_persisted = bool(worker_members) and all(
        worker_members[i] == plan_members.get(worker_chunk_ids[i]) and worker_members[i]
        for i in range(len(worker_chunk_ids))
    )
    green = bool(members_persisted and render_error is None and engine_calls)
    REPORT["members_persisted_end_to_end"] = members_persisted
    REPORT["worker_proceeds_to_engine"] = render_error is None and bool(engine_calls)
    REPORT["verdict"] = "GREEN" if green else "RED"
    print(json.dumps(REPORT, indent=1, default=str))
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
