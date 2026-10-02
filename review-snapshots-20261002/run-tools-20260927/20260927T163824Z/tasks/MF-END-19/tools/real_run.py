"""MF-END-19 REAL RUN — public app FullApply → ComfyShotEngine → isolated ComfyUI.

One GPU job at a time; the isolated server runs from this evidence root with its
own base-directory (input/output/temp/user/custom_nodes), the shared read-only
models root, its own port, --reserve-vram 1.0, --disable-auto-launch.  The run
goes through the PUBLIC app path: POST /projects/{id}/full-apply (the real
route, real v2 authority, real job system) → durable worker → shot executor →
the app's ONE Comfy door -> the real server (prompt_id) -> artifact harvest ->
publication.  Then the server is stopped and the shutdown is proved.

Nothing here mocks anything: the only fixture work is seeding the business DB
(workspace/project/video/cast/authority) exactly like the product tests do, and
pre-placing the byte-identical staged inputs into the server input dir (the
documented driver contract of the executor).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-19")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-19")
PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
SRC = RT / "ComfyUI"
VENV_PY = RT / "venv/Scripts/python.exe"
COMFY_SRC = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy")
PORT = 8361
BASE = EVID / "runtime"
MANAGED = EVID / "managed"
DB = EVID / "runtime" / "mf19_run.db"
BASE_URL = f"http://127.0.0.1:{PORT}"
BOOK_SRC = PROOF / "inputs" / "BOOK_src.mp4"
BOOK_ANCHOR = PROOF / "inputs" / "anchor_book_p2_00001_.png"
WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"
BOOK_PROMPT_SHA = "540d16b7b7300c40b3768bd589e963b03bf400e8aa6010ef2068d2161676bd9d"
SEED = 582699151003550

os.environ.setdefault("PYTHONPATH", str(WT))
sys.path.insert(0, str(WT))
sys.path.insert(0, str(EVID / "mf_comfy_pkg"))

RESULT: dict = {"steps": []}


def log(step: str, **kw) -> None:
    row = {"step": step, "at_unix": time.time(), **kw}
    RESULT["steps"].append(row)
    print(json.dumps(row, ensure_ascii=False)[:400], flush=True)


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def listener_pids(port: int) -> list[int]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids: list[int] = []
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            try:
                pids.append(int(line.split()[-1]))
            except Exception:
                pass
    return sorted(set(pids))


def nvidia() -> str:
    return subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,name",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    ).stdout.strip()


def http_json(path: str, timeout: int = 30):
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    RESULT["gpu_before"] = nvidia()
    log("preflight", gpu=RESULT["gpu_before"], port_free=not port_open(PORT))
    if port_open(PORT):
        log("BLOCKED", reason=f"port {PORT} already listening")
        return 2

    # ── 0. build + install the pinned mf_comfy dependency ─────────────────
    if not (EVID / "mf_comfy_pkg" / "mf_comfy" / "__init__.py").is_file():
        proc = subprocess.run(
            [sys.executable, str(WT / "scripts" / "build_mf_comfy_dependency.py"),
             "--source-repo", str(COMFY_SRC), "--out", str(EVID / "build_comfy"),
             "--install-target", str(EVID / "mf_comfy_pkg"),
             "--report", str(EVID / "raw" / "mf19_build_report.json")],
            cwd=str(WT), capture_output=True, text=True, timeout=600,
        )
        log("build_mf_comfy", rc=proc.returncode, tail=proc.stdout.strip()[-200:])
        if proc.returncode != 0:
            print(proc.stderr[-800:], flush=True)
            return 2
    import importlib.util
    spec = importlib.util.find_spec("mf_comfy")
    log("mf_comfy_import", origin=str(getattr(spec, "origin", None)))
    from app.adapters.media_engine.comfy import engine_status
    status = engine_status()
    RESULT["engine_status"] = status
    log("engine_status", **{k: v for k, v in status.items() if k in ("available", "code", "detail")})
    if not status.get("available"):
        return 2

    # ── 1. seed the book unit business DB (public app fixtures) ───────────
    BOOK_SHA = sha_file(BOOK_SRC)
    ANCHOR_SHA = sha_file(BOOK_ANCHOR)
    RESULT["book_sha"] = BOOK_SHA
    RESULT["anchor_sha"] = ANCHOR_SHA
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import text
    from app.persistence import create_engine_for_path, create_session_factory

    EVID.mkdir(parents=True, exist_ok=True)
    MANAGED.mkdir(parents=True, exist_ok=True)
    BASE.mkdir(parents=True, exist_ok=True)
    for sub in ("input", "output", "temp", "user", "custom_nodes"):
        (BASE / sub).mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    cfg = AlembicConfig(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{DB.as_posix()}")
    command.upgrade(cfg, "head")
    engine = create_engine_for_path(DB)
    factory = create_session_factory(engine)
    import uuid as _uuid

    from app.persistence.models import Artifact, Workspace

    ws = "default"
    proj = f"proj-{_uuid.uuid4().hex[:6]}"
    vid = f"vid-{_uuid.uuid4().hex[:6]}"
    roles = ["BOOK-P1", "BOOK-P2", "BOOK-P3", "BOOK-P4"]
    with factory() as s:
        if s.get(Workspace, ws) is None:
            s.add(Workspace(id=ws, name=ws))
            s.flush()
        # source media under the managed root: the REAL BOOK window clip
        src_rel = f"s10_full_apply/_authority/{vid}/BOOK_src.mp4"
        src_abs = MANAGED / src_rel
        src_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BOOK_SRC, src_abs)
        assert sha_file(src_abs) == BOOK_SHA
        src_art = f"art-src-{_uuid.uuid4().hex[:6]}"
        s.execute(
            text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','video',:rel,'ready',:sha,:sz,1)"),
            {"id": src_art, "rel": src_rel, "sha": BOOK_SHA, "sz": src_abs.stat().st_size},
        )
        s.execute(text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'MF19')"), {"p": proj, "w": ws})
        s.execute(
            text("INSERT INTO video_item(id,project_id,title,position,source_artifact_id) VALUES (:v,:p,'BOOK unit',0,:a)"),
            {"v": vid, "p": proj, "a": src_art},
        )
        s.execute(
            text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,0,119,0,4000,'pending')"),
            {"s": f"sc-{_uuid.uuid4().hex[:6]}", "v": vid},
        )
        role_ids = {}
        pack_versions = {}
        rc_ids = {}
        import cv2
        import numpy as np

        for i, role in enumerate(roles):
            role_id = f"role-{_uuid.uuid4().hex[:6]}"
            role_ids[role] = role_id
            s.execute(
                text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,'1',:n,'character','confirmed')"),
                {"r": role_id, "w": ws, "p": proj, "v": vid, "n": role},
            )
            char = f"ch-{_uuid.uuid4().hex[:6]}"
            s.execute(
                text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,:n,:code)"),
                {"c": char, "w": ws, "n": f"Reader{i + 1}", "code": f"reader{i}_{_uuid.uuid4().hex[:4]}"},
            )
            pv = f"pv-{_uuid.uuid4().hex[:6]}"
            pack_versions[role] = pv
            s.execute(
                text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"),
                {"pv": pv, "c": char, "w": ws},
            )
            asset_rel = f"s10_full_apply/_authority/{vid}/asset_{i}.png"
            asset_abs = MANAGED / asset_rel
            asset_abs.parent.mkdir(parents=True, exist_ok=True)
            img = np.zeros((48, 48, 4), dtype=np.uint8)
            img[:, :, 0] = 40 + i * 30
            img[:, :, 1] = 90
            img[:, :, 2] = 160 - i * 20
            img[:, :, 3] = 255
            cv2.imwrite(str(asset_abs), img)
            asset_art = f"art-asset-{_uuid.uuid4().hex[:6]}"
            s.execute(
                text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"),
                {"id": asset_art, "rel": asset_rel, "sha": sha_file(asset_abs), "sz": asset_abs.stat().st_size},
            )
            ca = f"ca-{_uuid.uuid4().hex[:6]}"
            s.execute(
                text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"),
                {"id": ca, "pv": pv, "aid": asset_art},
            )
            rc_i = f"rc-{_uuid.uuid4().hex[:6]}"
            rc_ids[role] = rc_i
            s.execute(
                text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"),
                {"rc": rc_i, "w": ws, "p": proj, "r": role_id, "c": char, "pv": pv,
                 "params": json.dumps({"anchor": {"x": 0.5, "y": 0.5}, "scale": 1.0, "fit_mode": "contain",
                                       "clip_mode": "asset_alpha", "offset": {"x": 0.0, "y": 0.0},
                                       "rotation_offset_deg": 0.0, "opacity": 1.0}, sort_keys=True, separators=(",", ":"))},
            )
        rc = rc_ids["BOOK-P1"]
        seed_pack_ids = [pack_versions[r] for r in roles]
        s.commit()
    log("seed_business_rows", roles=roles, source_sha=BOOK_SHA)

    # ── 2. structural lock + v2 authority for the 120-frame BOOK shot ─────
    from app.persistence.artifacts import hash_file
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository

    with factory() as s:
        scene_id = s.execute(text("SELECT id FROM scene WHERE video_item_id=:v ORDER BY position LIMIT 1"), {"v": vid}).scalar()
        mask_art = f"art-mask-{_uuid.uuid4().hex[:6]}"
        mask_rel = f"s10_full_apply/_authority/{vid}/mask.png"
        mask_abs = MANAGED / mask_rel
        import cv2
        import numpy as np
        mimg = np.zeros((40, 40, 4), dtype=np.uint8)
        mimg[:, :, 3] = 255
        cv2.imwrite(str(mask_abs), mimg)
        s.execute(
            text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,'default','image',:rel,'ready',:sha,:sz,1)"),
            {"id": mask_art, "rel": mask_rel, "sha": hash_file(mask_abs), "sz": mask_abs.stat().st_size},
        )
        seg_repo = StructuralEvidenceRepository(s)
        lock_repo = StructuralLockRepository(s)
        seg_ids = []
        for i, role in enumerate(roles):
            seg, _ = seg_repo.create_segment(
                ws, proj, vid, role_ids[role], str(scene_id), role, 0, 119, 0, 4000, "1",
                kind="character", confidence_source="user",
                segmentation={"boxes": [{"x": 0.1 + i * 0.1, "y": 0.1, "w": 0.2, "h": 0.3}]},
                prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.3, "h": 0.4}]},
                mask_artifact_id=mask_art,
            )
            seg_ids.append(str(seg.id))
        manifest_dict = {
            "frame_count": 120,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": seg_ids,
            "fingerprints": {"z_order": hashlib.sha256(b"z").hexdigest(), "contacts": hashlib.sha256(b"c").hexdigest()},
            "segments": [
                {"occurrence_segment_id": sid, "route": "sprite_affine", "anchor": {"x": 0.5, "y": 0.5},
                 "start_frame": 0, "end_frame": 119, "provenance": {"why": "mf19 real-run seed"}}
                for sid in seg_ids
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _ = lock_repo.create_manifest(ws, proj, vid, "1", manifest_dict)
        for sid in seg_ids:
            lock_repo.record_render_route(
                ws, proj, vid, sid, "sprite_affine", 0.5, 0.5, 0, 119,
                provenance={"why": "mf19 real-run seed"}, reasons=["mf19 real-run seed"],
                structural_lock_manifest_id=manifest.id,
            )
        rc_list = list(rc_ids.values())
        placeholders = ",".join(f":rc{i}" for i in range(len(rc_list)))
        s.execute(
            text(
                "UPDATE reskin_config SET structural_lock_manifest_id=:m,"
                f" lock_policy_version=:p WHERE id IN ({placeholders})"
            ),
            {"m": manifest.id, "p": manifest.policy_version,
             **{f"rc{i}": v for i, v in enumerate(rc_list)}},
        )
        s.flush()
        record, created = S09ApprovalRepository(s).submit_checkpoint_v2(
            ws, reskin_config_id=rc, expected_reskin_revision=1,
            pack_version_ids=seed_pack_ids, note="mf19 real-run authority",
        )
        assert created is True
        s.commit()
        ckpt_id, ckpt_hash, ckpt_rev = str(record.id), str(record.checkpoint_hash), int(record.reskin_config_revision)
    RESULT["checkpoint"] = {"id": ckpt_id, "hash": ckpt_hash, "revision": ckpt_rev}
    log("seed_v2_authority", checkpoint_id=ckpt_id, hash16=ckpt_hash[:16], revision=ckpt_rev)

    # ── 3. learn the shot_id + chunk from the canonical authority ─────────
    from app.services.s09_approval import S09ApprovalRepository as _S09
    from app.services.s10_chunk_plan import plan_full_apply
    from app.services.s10_full_apply import _canonical_planner_inputs

    with factory() as s:
        authority = _S09(s).full_apply_authority(ckpt_id, ws)
    canonical = _canonical_planner_inputs(authority, checkpoint_id=ckpt_id, checkpoint_hash=ckpt_hash, checkpoint_revision=ckpt_rev)
    dry_plan = plan_full_apply(
        canonical["approved_checkpoint"], canonical["structural_lock_manifest"],
        canonical["scene_manifest"], canonical["mapping"], canonical["compatibility_policy"],
        chunk_config={"chunk_frames": 120, "overlap_frames": 0},
    )
    shot_id = str(dry_plan["chunks"][0]["shot_id"]) if dry_plan["chunks"] else ""
    log("dry_plan", shots=[c["shot_id"] for c in dry_plan["chunks"]][:2], shot_id=shot_id, chunks=len(dry_plan["chunks"]))
    if not shot_id:
        return 2

    # the frozen per-shot prompt = the graph file's own golden prompt bytes
    graph_doc = json.loads((WT / "app/media_workflows/wan_shot_v1.json").read_text(encoding="utf-8"))
    prompt_text = ""
    for p in graph_doc["parameters"]:
        if p["name"] == "prompt":
            pointer = p["pointer"].split("|")[0]
            node_id = pointer.split("/")[1]
            prompt_text = graph_doc["graph"][node_id]["inputs"]["text"]
    assert hashlib.sha256(prompt_text.encode("utf-8")).hexdigest() == BOOK_PROMPT_SHA
    graph_sha = sha_file(WT / "app/media_workflows/wan_shot_v1.json")

    # ── 4. stage the executor's inputs + mirror them into the server ──────
    anchor_rel = f"shot_render/inputs/anchor_book_p2_00001_.png"
    anchor_abs = MANAGED / anchor_rel
    anchor_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BOOK_ANCHOR, anchor_abs)
    assert sha_file(anchor_abs) == ANCHOR_SHA
    backend_manifest = {
        "backend": "comfy_shot_engine",
        "profile_id": WAN_PROFILE,
        "capability": "source_video_motion_transfer",
        "graph_file": "app/media_workflows/wan_shot_v1.json",
        "graph_sha256": graph_sha,
        "output_node": "246",
        "engine_base_url": BASE_URL,
        "seed": SEED,
        "shot_prompts": {shot_id: prompt_text},
        "shot_anchors": {shot_id: {"relative_path": anchor_rel, "sha256": ANCHOR_SHA}},
        "require_accepted_anchor": False,
    }
    with factory() as s:
        authority2 = _S09(s).full_apply_authority(ckpt_id, ws)
    canonical2 = _canonical_planner_inputs(authority2, checkpoint_id=ckpt_id, checkpoint_hash=ckpt_hash, checkpoint_revision=ckpt_rev)
    real_plan = plan_full_apply(
        canonical2["approved_checkpoint"], canonical2["structural_lock_manifest"],
        canonical2["scene_manifest"], canonical2["mapping"], canonical2["compatibility_policy"],
        chunk_config={"chunk_frames": 120, "overlap_frames": 0, "execution_backend": backend_manifest},
    )
    assert len(real_plan["chunks"]) == 1, f"expected ONE shot-group chunk, got {len(real_plan['chunks'])}"
    chunk = real_plan["chunks"][0]
    chunk_id = str(chunk["chunk_id"])
    members = list(chunk["member_layer_ids"])
    safe_chunk = "".join(c if (c.isalnum() or c in "._-") else "_" for c in chunk_id)
    window_name = f"shotwin_{safe_chunk}_0_120.mp4"
    window_rel = f"media_engine/comfy_shot_engine/stage/inputs/{safe_chunk}/{window_name}"
    window_abs = MANAGED / window_rel
    window_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BOOK_SRC, window_abs)  # byte copy == what the executor will write
    RESULT["plan"] = {"plan_id": real_plan["plan_id"], "chunk_id": chunk_id, "members": members,
                      "window": window_rel, "window_sha": sha_file(window_abs)}
    log("real_plan", chunk_id=chunk_id, members=members, window_name=window_name)

    # ── 5. launch the isolated Comfy server ───────────────────────────────
    for sub in ("input", "output", "temp", "user", "custom_nodes"):
        (BASE / sub).mkdir(parents=True, exist_ok=True)
    for name, sha in ((window_name, sha_file(window_abs)), ("anchor_book_p2_00001_.png", ANCHOR_SHA), ("BOOK_src.mp4", BOOK_SHA)):
        dst = BASE / "input" / name
        if name == window_name:
            shutil.copyfile(window_abs, dst)
        elif name == "BOOK_src.mp4":
            shutil.copyfile(BOOK_SRC, dst)
        else:
            shutil.copyfile(anchor_abs, dst)
        assert sha_file(dst) == sha, f"server input mirror mismatch for {name}"
    log("server_inputs_mirrored", files=[window_name, "anchor_book_p2_00001_.png", "BOOK_src.mp4"])

    argv = [str(VENV_PY), "-u", str(SRC / "main.py"), "--listen", "127.0.0.1", "--port", str(PORT),
            "--base-directory", str(BASE), "--models-directory", str(RT / "models"),
            "--input-directory", str(BASE / "input"), "--output-directory", str(BASE / "output"),
            "--temp-directory", str(BASE / "temp"), "--user-directory", str(BASE / "user"),
            "--reserve-vram", "1.0", "--disable-auto-launch"]
    RESULT["launch_argv"] = [a.replace(str(EVID), "<MF19-EVID>").replace(str(RT), "<runtime/video14b>") for a in argv]
    logp = open(BASE / "server.log", "w", encoding="utf-8", errors="replace")
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    proc = subprocess.Popen(argv, cwd=str(BASE), stdout=logp, stderr=subprocess.STDOUT, creationflags=creationflags)
    RESULT["server_pid"] = proc.pid
    t0 = time.time()
    ready = False
    while time.time() - t0 < 180:
        try:
            stats = http_json("/system_stats", timeout=5)
            ready = True
            RESULT["server_stats"] = {"comfyui_version": stats.get("system", {}).get("comfyui_version"),
                                      "ready_s": round(time.time() - t0, 2)}
            break
        except Exception:
            time.sleep(2)
    log("server_ready", ready=ready, pid=proc.pid, **RESULT.get("server_stats", {}))
    if not ready:
        proc.kill()
        return 2
    epoch_path = MANAGED / "media_engine" / "comfy_shot_engine" / "instance_epoch.json"
    epoch_path.parent.mkdir(parents=True, exist_ok=True)
    epoch = {"instance_id": hashlib.sha256(f"{time.time()}:{PORT}:{proc.pid}".encode()).hexdigest(),
             "base_url": BASE_URL, "port": PORT, "pid": proc.pid,
             "comfyui_version": RESULT.get("server_stats", {}).get("comfyui_version", ""),
             "written_at_unix": time.time(), "launcher": "mf_end19_harness", "one_job_at_a_time": True}
    epoch_path.write_text(json.dumps(epoch, indent=1), encoding="utf-8")
    log("epoch_written", epoch_path=str(epoch_path), instance_id=epoch["instance_id"][:16])

    # ── 6. the PUBLIC app path: route POST → job → worker ────────────────
    from app.api import deps
    from app.workflow.job_service import JobService
    from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler
    from fastapi.testclient import TestClient
    from app.api.app import app as fastapi_app

    svc = JobService(session_factory=factory, managed_root=MANAGED)
    deps._job_service = svc
    register_s10_full_apply_handler(svc._worker)
    with __import__("contextlib").suppress(Exception):
        svc._worker.bind_session_factory(factory)
    client = TestClient(fastapi_app)
    body = {
        "video_item_id": vid,
        "apply_checkpoint_id": ckpt_id,
        "expected_checkpoint_hash": ckpt_hash,
        "expected_checkpoint_revision": ckpt_rev,
        "chunk_config": {"chunk_frames": 120, "overlap_frames": 0, "execution_backend": backend_manifest},
    }
    resp = client.post(f"/api/v2/projects/{proj}/full-apply?workspace_id={ws}", json=body)
    RESULT["submit"] = {"status_code": resp.status_code, "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]}
    log("route_submit", rc=resp.status_code, body=str(RESULT["submit"]["body"])[:200])
    if resp.status_code not in (200, 201, 202):
        return 2
    run_id = resp.json()["run_id"]
    RESULT["run_id"] = run_id

    if os.environ.get("MF19_DRY") == "1":
        # dry pass: every non-GPU stage has run (build/install, seed, plan,
        # staging + server mirror, launch, epoch, route POST).  Verify the run
        # + chunks + job exist, then stop the server cleanly.  No worker call.
        with factory() as s:
            dry_run = dict(
                s.execute(
                    text(
                        "SELECT status, plan_id, frame_count, chunk_config_json"
                        " FROM s10_full_apply_run WHERE id=:r"
                    ),
                    {"r": run_id},
                ).mappings().first()
            )
            dry_chunks = [
                dict(r)
                for r in s.execute(
                    text(
                        "SELECT id AS chunk_id, shot_id, layer_id, core_start_frame,"
                        " core_end_frame, state FROM s10_full_apply_chunk WHERE run_id=:r"
                    ),
                    {"r": run_id},
                ).mappings().all()
            ]
        RESULT["dry"] = {"run": dry_run, "chunks": dry_chunks}
        log("dry_state", status=dry_run.get("status"), chunks=len(dry_chunks))
        before = listener_pids(PORT)
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except Exception:
            proc.kill()
        for pid in listener_pids(PORT):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
        time.sleep(3)
        RESULT["shutdown"] = {"port_closed": not port_open(PORT), "listener_pids_before": before}
        RESULT["verdict"] = (
            "DRY_PASS"
            if dry_run.get("status") == "pending"
            and len(dry_chunks) == 1
            and RESULT["shutdown"]["port_closed"]
            else "DRY_FAIL"
        )
        (EVID / "raw" / "real_run_receipt.json").write_text(
            json.dumps(RESULT, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        print(f"DRY_VERDICT={RESULT['verdict']}", flush=True)
        return 0 if RESULT["verdict"] == "DRY_PASS" else 1

    def _run_worker() -> None:
        svc._worker.run_once()

    worker = threading.Thread(target=_run_worker, name="mf19-worker", daemon=False)
    t_job = time.time()
    worker.start()
    worker.join(timeout=1500)
    job_wall = round(time.time() - t_job, 2)
    RESULT["job_wall_s"] = job_wall
    log("worker_done", alive=worker.is_alive(), wall_s=job_wall)

    # ── 7. verify run/publication/chunks from the DB + disk ──────────────
    with factory() as s:
        run = dict(s.execute(text("SELECT status, frame_count, plan_id, plan_hash FROM s10_full_apply_run WHERE id=:r"), {"r": run_id}).mappings().first())
        chunks = [dict(r) for r in s.execute(text("SELECT id AS chunk_id, state, verified, artifact_id, core_start_frame, core_end_frame FROM s10_full_apply_chunk WHERE run_id=:r ORDER BY chunk_index"), {"r": run_id}).mappings().all()]
        pubs = [dict(r) for r in s.execute(text("SELECT id, state, artifact_id, content_hash, frame_count FROM s10_full_apply_publication WHERE run_id=:r"), {"r": run_id}).mappings().all()]
    RESULT["run"] = run
    RESULT["chunks"] = chunks
    RESULT["publications"] = pubs
    log("db_state", run_status=run.get("status"), chunks=len(chunks), pubs=[p["state"] for p in pubs])

    pub_artifact_rel = pub_artifact_sha = None
    if pubs:
        with factory() as s:
            art = s.execute(text("SELECT relative_path, sha256, size_bytes FROM artifact WHERE id=:a"), {"a": pubs[0]["artifact_id"]}).mappings().first()
        if art:
            pub_artifact_rel, pub_artifact_sha = str(art["relative_path"]), str(art["sha256"])
    RESULT["publication_artifact"] = {"relative_path": pub_artifact_rel, "sha256": pub_artifact_sha}
    if pub_artifact_rel:
        abs_pub = MANAGED / pub_artifact_rel
        RESULT["publication_artifact"]["exists"] = abs_pub.is_file()
        RESULT["publication_artifact"]["on_disk_sha"] = sha_file(abs_pub) if abs_pub.is_file() else None
        RESULT["publication_artifact"]["is_source"] = (RESULT["publication_artifact"]["on_disk_sha"] == BOOK_SHA)
    record_rel = f"shot_render/{shot_id}/{chunk_id}.json"
    record_abs = MANAGED / record_rel
    if record_abs.is_file():
        doc = json.loads(record_abs.read_text(encoding="utf-8"))
        RESULT["shot_render_record"] = {
            "relative_path": record_rel, "sha256": sha_file(record_abs),
            "verdict": doc.get("verdict"), "prompt_id": (doc.get("receipt") or {}).get("prompt_id"),
            "output_sha256": (doc.get("output") or {}).get("sha256"),
            "server_side_wall_s": (doc.get("receipt") or {}).get("server_side_wall_s"),
            "vram_peak_mib": (doc.get("receipt") or {}).get("vram_peak_mib"),
            "graph_object_sha256_submitted": (doc.get("graph") or {}).get("object_sha256_submitted"),
        }
    else:
        RESULT["shot_render_record"] = {"missing": record_rel}

    # ── 8. stop the server; prove the port refuses and the pid is gone ───
    before = listener_pids(PORT)
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except Exception:
        proc.kill()
    for pid in listener_pids(PORT):
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
    time.sleep(3)
    gone = False
    try:
        os.kill(proc.pid, 0)
    except OSError:
        gone = True
    RESULT["shutdown"] = {
        "port_closed": not port_open(PORT),
        "pid_gone": gone,
        "pid": proc.pid,
        "listener_pids_before": before,
    }
    log("shutdown", **RESULT["shutdown"])
    RESULT["gpu_after"] = nvidia()
    RESULT["host"] = {"python": sys.version.split()[0], "cwd": str(Path.cwd())}
    (EVID / "raw" / "real_run_receipt.json").write_text(json.dumps(RESULT, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = (
        run.get("status") == "completed"
        and any(p.get("state") == "completed" for p in pubs)
        and RESULT["shot_render_record"].get("verdict") == "accepted"
        and bool(RESULT["shot_render_record"].get("prompt_id"))
        and RESULT["publication_artifact"].get("exists") is True
        and RESULT["publication_artifact"].get("on_disk_sha") == pub_artifact_sha
        and RESULT["publication_artifact"].get("is_source") is False
        and RESULT["shutdown"]["port_closed"] and RESULT["shutdown"]["pid_gone"]
    )
    RESULT["verdict"] = "PASS" if ok else "FAIL"
    (EVID / "raw" / "real_run_receipt.json").write_text(json.dumps(RESULT, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"REAL_RUN_VERDICT={RESULT['verdict']}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
