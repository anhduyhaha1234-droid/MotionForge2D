"""MF-DEMO-E2E-R3 harness — DEMO THẬT: app HTTP + isolated ComfyUI + GPU 3 shot 12s.

Phases (argv[1]): prep | app | journey | monitor | qc | export | verify | report | shutdown
State: raw/state.json (merged per phase). Every shell command + HTTP call is
appended to raw/commands.jsonl (UTC, rc, duration).  The candidate tree is
READ-ONLY code: the app runs with cwd=WT + PYTHONDONTWRITEBYTECODE=1 and every
runtime root resolves under EVID.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
COMFY_SRC = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy")
VENV_PY = RT / "venv" / "Scripts" / "python.exe"
COMFYUI = RT / "ComfyUI"
MODELS = RT / "models"
MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr3")
APP_ROOT = MFRT  # F3: keep MOTIONFORGE_ROOT SHORT; runtime harvested back to EVID
MANAGED = APP_ROOT / "artifacts"
DB = APP_ROOT / "data" / "motionforge.db"
COMFY_BASE = EVID / "comfy-base"
RAW = EVID / "raw"
TOOLS = EVID / "tools"
R2EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")
EXPORT = RAW / "export"
APP_PORT = 8032
COMFY_PORT = 8373
APP_URL = f"http://127.0.0.1:{APP_PORT}"
COMFY_URL = f"http://127.0.0.1:{COMFY_PORT}"
PROFILE = "wan_animate2_int8_pad640x368_cacheoff"
SEED = 582699151003550
GRAPH_REL = "app/media_workflows/wan_shot_v1.json"
SOURCES = ["BOOK_src.mp4", "TURN_795_src.mp4", "OCC_14768_src.mp4"]
ANCHOR_BY_START = {
    0: "anchor_book_p2_00001_.png",
    120: "anchor_turn_p2_00001_.png",
    240: "anchor_occ_p2_00001_.png",
}
CAST_PROOF = [
    "i1_cast_boy_hacker_sitting.png",
    "i1_cast_dan_choi_standing.png",
    "i1_cast_gau_nau_back.png",
    "i1d_cast_boy_hacker_sitting_on_neutral_bg.png",
    "i1d_cast_dan_choi_standing_on_neutral_bg.png",
    "i1d_cast_gau_nau_back_on_neutral_bg.png",
]
STATE_P = RAW / "state.json"
CMDS = RAW / "commands.jsonl"
SRC_12S = RAW / "source_12s.mp4"

sys.path.insert(0, str(WT))
sys.path.insert(0, str(EVID / "mf_comfy_pkg"))


# ── helpers ──────────────────────────────────────────────────────────────────
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_state() -> dict:
    if STATE_P.is_file():
        return json.loads(STATE_P.read_text(encoding="utf-8"))
    return {}


def save_state(patch: dict) -> dict:
    st = load_state()
    st.update(patch)
    RAW.mkdir(parents=True, exist_ok=True)
    STATE_P.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
    return st


def log_row(row: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with open(CMDS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def sh(argv: list, step: str, timeout: int = 300, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    t0 = time.time()
    proc = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                          timeout=timeout, cwd=str(cwd) if cwd else None)
    dur = round(time.time() - t0, 3)
    log_row({"ts": now(), "kind": "cmd", "step": step, "argv": [str(a) for a in argv],
             "rc": proc.returncode, "dur_s": dur, "stdout_tail": proc.stdout[-300:],
             "stderr_tail": proc.stderr[-300:]})
    print(f"[{step}] rc={proc.returncode} dur={dur}s", flush=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{step} rc={proc.returncode}: {proc.stderr[-500:]}")
    return proc


def http(method: str, path: str, body: dict | None = None, timeout: int = 60,
         base: str = APP_URL) -> tuple[int, object]:
    url = base + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    except Exception as e:  # noqa: BLE001
        log_row({"ts": now(), "kind": "http", "method": method, "path": path,
                 "status": None, "error": f"{type(e).__name__}:{e}"})
        print(f"[http] {method} {path} -> CONN_ERROR {type(e).__name__}", flush=True)
        return 0, {"error": str(e)}
    dur = round(time.time() - t0, 3)
    try:
        parsed: object = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        parsed = raw.decode("utf-8", errors="replace")
    preview = json.dumps(parsed, ensure_ascii=False)[:600] if not isinstance(parsed, str) else parsed[:600]
    log_row({"ts": now(), "kind": "http", "method": method, "path": path,
             "status": status, "dur_s": dur, "body_preview": preview})
    print(f"[http] {method} {path} -> {status} ({dur}s)", flush=True)
    return status, parsed


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def listener_pids(port: int) -> list:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            try:
                pids.append(int(line.split()[-1]))
            except Exception:  # noqa: BLE001
                pass
    return sorted(set(pids))


def nvidia() -> str:
    return subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
         "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def make_dirs() -> None:
    for p in (RAW, TOOLS, EXPORT, APP_ROOT / "data", APP_ROOT / "output", MANAGED,
              COMFY_BASE, EVID / "build_comfy"):
        p.mkdir(parents=True, exist_ok=True)
    for sub in ("input", "output", "temp", "user", "custom_nodes"):
        (COMFY_BASE / sub).mkdir(parents=True, exist_ok=True)


# ── phase: prep ──────────────────────────────────────────────────────────────
def phase_prep() -> int:
    make_dirs()
    st = load_state()
    # 1) 12s source - REUSE the R2-produced source byte-for-byte (same inputs)
    if not SRC_12S.is_file():
        shutil.copyfile(R2EV / "raw" / "source_12s.mp4", SRC_12S)
    _r2st = json.loads((R2EV / "raw" / "state.json").read_text(encoding="utf-8"))
    assert sha_file(SRC_12S) == _r2st["source_12s"]["sha256"], "R3 source != R2 source (drift)"
    _pa = sh(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
              "stream=codec_name", "-of", "csv=p=0", str(SRC_12S)], "probe_audio_existing")
    has_audio = bool(_pa.stdout.strip())
    # verify
    probe = sh(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate",
                "-show_entries", "format=duration", "-of", "json", str(SRC_12S)], "probe_12s")
    doc = json.loads(probe.stdout)
    stream = (doc.get("streams") or [{}])[0]
    dur = float((doc.get("format") or {}).get("duration") or 0)
    src_info = {"path": str(SRC_12S), "sha256": sha_file(SRC_12S),
                "bytes": SRC_12S.stat().st_size, "frames": int(stream.get("nb_read_frames") or 0),
                "width": stream.get("width"), "height": stream.get("height"),
                "fps": stream.get("r_frame_rate"), "duration_s": dur,
                "audio_default": has_audio}
    assert src_info["frames"] == 360 and abs(dur - 12.0) < 0.05, f"12s source invalid: {src_info}"
    (RAW / "source_12s.json").write_text(json.dumps(src_info, indent=1), encoding="utf-8")
    save_state({"source_12s": src_info})

    # 2) REUSE the pinned mf_comfy dependency built for R2 (pin 70f7180)
    if not (EVID / "mf_comfy_pkg" / "mf_comfy" / "__init__.py").is_file():
        shutil.copytree(R2EV / "mf_comfy_pkg", EVID / "mf_comfy_pkg")
    from app.adapters.media_engine.comfy import engine_status  # noqa: PLC0415
    status = engine_status()
    print("engine_status:", json.dumps(status, ensure_ascii=False)[:300], flush=True)
    assert status.get("available") is True, f"mf_comfy not available: {status}"
    save_state({"engine_status": {k: v for k, v in status.items() if isinstance(v, (str, bool, int))}})

    # 3) stage the 3 anchors under the managed root (digest-pinned inputs)
    anchor_dir = MANAGED / "shot_render" / "inputs"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    anchors = {}
    for name in ANCHOR_BY_START.values():
        dst = anchor_dir / name
        shutil.copyfile(PROOF / "inputs" / name, dst)
        anchors[name] = {"relative_path": f"shot_render/inputs/{name}",
                         "sha256": sha_file(dst), "size": dst.stat().st_size}
    shutil.copyfile(SRC_12S, COMFY_BASE / "input" / SRC_12S.name)
    for name in ANCHOR_BY_START.values():
        shutil.copyfile(PROOF / "inputs" / name, COMFY_BASE / "input" / name)
    save_state({"anchors": anchors})

    # 4) isolated ComfyUI server (1 GPU job at a time; own port + base dir)
    if port_open(COMFY_PORT):
        save_state({"comfy_ready": {"already_listening": True, "port": COMFY_PORT}})
        return 0
    argv = [str(VENV_PY), "-u", str(COMFYUI / "main.py"), "--listen", "127.0.0.1",
            "--port", str(COMFY_PORT), "--base-directory", str(COMFY_BASE),
            "--models-directory", str(MODELS), "--input-directory", str(COMFY_BASE / "input"),
            "--output-directory", str(COMFY_BASE / "output"), "--temp-directory", str(COMFY_BASE / "temp"),
            "--user-directory", str(COMFY_BASE / "user"), "--reserve-vram", "1.0",
            "--disable-auto-launch"]
    logf = open(COMFY_BASE / "server.log", "w", encoding="utf-8", errors="replace")
    creationflags = 0x08000000 if os.name == "nt" else 0
    proc = subprocess.Popen(argv, cwd=str(COMFY_BASE), stdout=logf, stderr=subprocess.STDOUT,
                            creationflags=creationflags)
    t0 = time.time()
    ready = False
    stats = {}
    while time.time() - t0 < 240:
        try:
            with urllib.request.urlopen(COMFY_URL + "/system_stats", timeout=5) as r:
                stats = json.loads(r.read().decode("utf-8"))
            ready = True
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    ready_s = round(time.time() - t0, 2)
    if not ready:
        proc.kill()
        raise RuntimeError("ComfyUI server did not become ready in 240s")
    epoch = {"instance_id": hashlib.sha256(f"{time.time()}:{COMFY_PORT}:{proc.pid}".encode()).hexdigest(),
             "base_url": COMFY_URL, "port": COMFY_PORT, "pid": proc.pid,
             "comfyui_version": (stats.get("system") or {}).get("comfyui_version", ""),
             "written_at_unix": time.time(), "written_at_utc": now(),
             "launcher": "mf_demo_e2e", "one_job_at_a_time": True}
    ep = MANAGED / "media_engine" / "comfy_shot_engine" / "instance_epoch.json"
    ep.parent.mkdir(parents=True, exist_ok=True)
    ep.write_text(json.dumps(epoch, indent=1), encoding="utf-8")
    (RAW / "comfy_epoch.json").write_text(json.dumps({"epoch": epoch, "ready_s": ready_s,
                                                      "system_stats": stats}, indent=1), encoding="utf-8")
    save_state({"comfy": {"pid": proc.pid, "port": COMFY_PORT, "ready_s": ready_s,
                          "version": epoch["comfyui_version"], "epoch_instance_id": epoch["instance_id"],
                          "argv": [a.replace(str(RT), "<RT>") for a in argv]}})
    print(f"comfy READY pid={proc.pid} in {ready_s}s", flush=True)
    return 0


# ── phase: app ───────────────────────────────────────────────────────────────
def phase_app() -> int:
    make_dirs()
    st = load_state()
    if st.get("app", {}).get("pid") and pid_alive(int(st["app"]["pid"])):
        print("app already running", flush=True)
        return 0
    if port_open(APP_PORT):
        raise RuntimeError(f"port {APP_PORT} already in use")
    env = dict(os.environ)
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "MOTIONFORGE_ROOT": str(APP_ROOT),
        "MOTIONFORGE_OUTPUT": str(APP_ROOT / "output"),
        "PYTHONPATH": str(WT) + os.pathsep + str(EVID / "mf_comfy_pkg"),
    })
    argv = [sys.executable, "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
            "--port", str(APP_PORT), "--log-level", "info"]
    logf = open(RAW / "app.log", "w", encoding="utf-8", errors="replace")
    creationflags = 0x08000000 if os.name == "nt" else 0
    proc = subprocess.Popen(argv, cwd=str(WT), env=env, stdout=logf, stderr=subprocess.STDOUT,
                            creationflags=creationflags)
    t0 = time.time()
    health = None
    while time.time() - t0 < 180:
        try:
            with urllib.request.urlopen(APP_URL + "/health", timeout=5) as r:
                health = json.loads(r.read().decode("utf-8"))
                break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    ready_s = round(time.time() - t0, 2)
    if not health:
        raise RuntimeError("app /health did not answer in 180s; see raw/app.log")
    app_state = {"pid": proc.pid, "port": APP_PORT, "ready_s": ready_s,
                 "health": health, "started_at_utc": now(),
                 "epoch_unix": time.time(),
                 "argv": [a.replace(str(WT), "<WT>") for a in argv],
                 "env": {"MOTIONFORGE_ROOT": str(APP_ROOT)},
                 "candidate_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(WT),
                                                  capture_output=True, text=True).stdout.strip()}
    (RAW / "app_launch.json").write_text(json.dumps(app_state, indent=1), encoding="utf-8")
    save_state({"app": app_state})
    print(f"app READY pid={proc.pid} in {ready_s}s health={health}", flush=True)
    return 0


# ── phase: journey ───────────────────────────────────────────────────────────
def _session_factory():
    from app.persistence import create_engine_for_path, create_session_factory  # noqa: PLC0415
    return create_session_factory(create_engine_for_path(DB))


def _ws_id() -> str:
    from app.persistence import DEFAULT_WORKSPACE_ID  # noqa: PLC0415
    return str(DEFAULT_WORKSPACE_ID)


def _seed(st: dict, pid: str, vid: str) -> dict:
    """Seed the business authority EXACTLY like the product's own harnesses do.

    Disclosed as SEEDED in the report (the extraction/analyze legs need ML
    models unavailable here); every later step (lock/approval/submit/status/
    export) goes through the real public HTTP routes.
    """
    import uuid as _uuid  # noqa: PLC0415

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    from app.persistence.models import Workspace  # noqa: PLC0415
    from app.persistence.structural_evidence import StructuralEvidenceRepository  # noqa: PLC0415

    WS = _ws_id()
    factory = _session_factory()
    src_rel = f"s10_full_apply/_authority/{vid}/{SRC_12S.name}"
    src_abs = MANAGED / src_rel
    src_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC_12S, src_abs)
    src_sha = sha_file(src_abs)
    assert src_sha == st["source_12s"]["sha256"], "staged source drift"

    roles = [("BOOK-P1", 0), ("BOOK-P2", 0), ("BOOK-P3", 0), ("BOOK-P4", 0),
             ("TURN-CERT", 1), ("OCC-PEN", 2)]
    scenes = [(0, 119, 0, 4000), (120, 239, 4000, 8000), (240, 359, 8000, 12000)]
    out = {"roles": {}, "pack_versions": {}, "reskin_configs": {}, "scenes": {}, "segments": []}
    with factory() as s:
        if s.get(Workspace, WS) is None:
            s.add(Workspace(id=WS, name=WS))
            s.flush()
        src_art = f"art-src-{_uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision)"
                       " VALUES (:id,:w,'video',:rel,'ready',:sha,:sz,1)"),
                  {"id": src_art, "w": WS, "rel": src_rel, "sha": src_sha, "sz": src_abs.stat().st_size})
        cols = {str(r[1]) for r in s.execute(text("PRAGMA table_info(video_item)"))}
        updates = {"source_artifact_id": src_art, "source_generation": "1", "duration_ms": 12000,
                   "width": 640, "height": 360, "fps_num": 30, "fps_den": 1}
        sets = ", ".join(f"{k}=:{k}" for k in updates if k in cols)
        s.execute(text(f"UPDATE video_item SET {sets} WHERE id=:v"),
                  {**{k: v for k, v in updates.items() if k in cols}, "v": vid})
        scene_ids = {}
        for i, (sf, ef, sms, ems) in enumerate(scenes):
            sid = f"sc-{_uuid.uuid4().hex[:6]}"
            scene_ids[i] = sid
            s.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,"
                           "end_time_ms,status) VALUES (:s,:v,:p,:sf,:ef,:sms,:ems,'pending')"),
                      {"s": sid, "v": vid, "p": i, "sf": sf, "ef": ef, "sms": sms, "ems": ems})
        mask_art = f"art-mask-{_uuid.uuid4().hex[:6]}"
        mask_rel = f"s10_full_apply/_authority/{vid}/mask.png"
        mask_abs = MANAGED / mask_rel
        mimg = np.zeros((40, 40, 4), dtype=np.uint8)
        mimg[:, :, 3] = 255
        cv2.imwrite(str(mask_abs), mimg)
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision)"
                       " VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                  {"id": mask_art, "w": WS, "rel": mask_rel, "sha": sha_file(mask_abs), "sz": mask_abs.stat().st_size})
        seg_repo = StructuralEvidenceRepository(s)
        for i, (role, scene_i) in enumerate(roles):
            role_id = f"role-{_uuid.uuid4().hex[:6]}"
            out["roles"][role] = role_id
            s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,"
                           "name,kind,status) VALUES (:r,:w,:p,:v,'1',:n,'character','confirmed')"),
                      {"r": role_id, "w": WS, "p": pid, "v": vid, "n": role})
            char = f"ch-{_uuid.uuid4().hex[:6]}"
            s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,:n,:code)"),
                      {"c": char, "w": WS, "n": role, "code": f"{role.lower().replace('-', '_')}_{_uuid.uuid4().hex[:4]}"})
            pv = f"pv-{_uuid.uuid4().hex[:6]}"
            out["pack_versions"][role] = pv
            s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
                           " VALUES (:pv,:c,:w,1,'published')"), {"pv": pv, "c": char, "w": WS})
            asset_rel = f"s10_full_apply/_authority/{vid}/asset_{i}.png"
            asset_abs = MANAGED / asset_rel
            shutil.copyfile(PROOF / "inputs" / CAST_PROOF[i], asset_abs)
            asset_art = f"art-asset-{_uuid.uuid4().hex[:6]}"
            s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision)"
                           " VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                      {"id": asset_art, "w": WS, "rel": asset_rel, "sha": sha_file(asset_abs),
                       "sz": asset_abs.stat().st_size})
            s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id)"
                           " VALUES (:id,:pv,:w,'base',:aid)"),
                      {"id": f"ca-{_uuid.uuid4().hex[:6]}", "pv": pv, "w": WS, "aid": asset_art})
            for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
                s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id)"
                               " VALUES (:id,:pv,:w,:slot,:aid)"),
                          {"id": f"ca-{_uuid.uuid4().hex[:6]}", "pv": pv, "w": WS, "slot": slot, "aid": asset_art})
            rc_i = str(_uuid.uuid4())
            out["reskin_configs"][role] = rc_i
            params = {"anchor": {"x": 0.5, "y": 0.5}, "scale": 1.0, "fit_mode": "contain",
                      "clip_mode": "asset_alpha", "offset": {"x": 0.0, "y": 0.0},
                      "rotation_offset_deg": 0.0, "opacity": 1.0}
            s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,"
                           "pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"),
                      {"rc": rc_i, "w": WS, "p": pid, "r": role_id, "c": char, "pv": pv,
                       "params": json.dumps(params, sort_keys=True, separators=(",", ":"))})
            sf, ef, sms, ems = scenes[scene_i]
            seg, _ = seg_repo.create_segment(
                WS, pid, vid, role_id, scene_ids[scene_i], role, sf, ef, sms, ems, "1",
                kind="character", confidence_source="user",
                segmentation={"boxes": [{"x": 0.1 + 0.1 * (i % 3), "y": 0.1, "w": 0.2, "h": 0.3}]},
                prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.3, "h": 0.4}]},
                mask_artifact_id=mask_art,
            )
            out["segments"].append(str(seg.id))
        s.commit()
    out["source_artifact_id"] = src_art
    out["source_rel"] = src_rel
    out["source_sha"] = src_sha
    return out


def phase_journey() -> int:
    st = load_state()
    WS = _ws_id()
    milestones = st.get("milestones", {})

    # ── 1. project create (HTTP) ─────────────────────────────────────────
    if st.get("project_id"):
        pid = st["project_id"]
        print("project (reuse)", pid, flush=True)
    else:
        sc, body = http("POST", f"/api/v2/projects?workspace_id={WS}", {"name": "MF-DEMO-E2E-12s"})
        assert sc == 201 and isinstance(body, dict), f"project create failed: {sc} {body}"
        pid = body.get("project_id") or body.get("id")
        assert pid, f"project id missing: {body}"
        milestones["project_create"] = {"method": "POST", "path": "/api/v2/projects", "status": sc,
                                        "at": now(), "project_id": pid}
        save_state({"project_id": pid, "milestones": milestones})
        print("project", pid, flush=True)

    # ── 2. video item create (HTTP) ──────────────────────────────────────
    if st.get("video_id"):
        vid = st["video_id"]
        print("video (reuse)", vid, flush=True)
    else:
        sc, body = http("POST", f"/api/v2/projects/{pid}/videos?workspace_id={WS}",
                        {"title": "12s 3-shot demo"})
        assert sc == 201 and isinstance(body, dict), f"video create failed: {sc} {body}"
        vid = body.get("video_item_id") or body.get("id")
        assert vid, f"video id missing: {body}"
        save_state({"video_id": vid})
        print("video", vid, flush=True)

    # ── 3. seed the business authority (disclosed; product-harness style) ─
    if not st.get("seed"):
        seed_doc = _seed(st, pid, vid)
        save_state({"seed": seed_doc})
        (RAW / "seed_authority.json").write_text(json.dumps(seed_doc, indent=1), encoding="utf-8")
        st = load_state()
    seed = st["seed"]

    # ── 4. structural lock producer (HTTP) ───────────────────────────────
    sc, body = http("POST", f"/api/v2/projects/{pid}/videos/{vid}/structural-lock",
                    {"idempotency_key": f"demo-lock-{pid}"})
    if sc in (200, 201) and isinstance(body, dict) and body.get("manifest_id"):
        manifest_id = body["manifest_id"]
        milestones["structural_lock"] = {"method": "POST", "path": "structural-lock", "status": sc,
                                         "at": now(), "manifest_id": manifest_id}
        save_state({"manifest": body, "milestones": milestones})
    else:
        raise RuntimeError(f"structural-lock producer refused: {sc} {body}")
    print("manifest", manifest_id, flush=True)

    # ── 5. pin every reskin config to the produced manifest (HTTP CAS) ───
    from sqlalchemy import text  # noqa: PLC0415
    factory = _session_factory()
    pinned = {}
    for role, rc in seed["reskin_configs"].items():
        with factory() as s:
            rev = int(s.execute(text("SELECT revision FROM reskin_config WHERE id=:r"), {"r": rc}).scalar())
        sc, body = http("PATCH", f"/api/v2/reskin-configs/{rc}",
                        {"revision": rev, "structural_lock_manifest_id": manifest_id})
        assert sc == 200, f"pin {role} failed: {sc} {body}"
        pinned[role] = {"revision_before": rev, "revision_after": body.get("revision")}
    save_state({"pinned": pinned})
    print("pinned", len(pinned), flush=True)

    # ── 6. S09 approvals: v1 then v2 reapprove (HTTP) ────────────────────
    rc_book = seed["reskin_configs"]["BOOK-P1"]
    with factory() as s:
        rev_now = int(s.execute(text("SELECT revision FROM reskin_config WHERE id=:r"), {"r": rc_book}).scalar())
    body = {"reskin_config_id": rc_book, "expected_reskin_revision": rev_now,
            "pack_version_ids": [seed["pack_versions"][r] for r in seed["pack_versions"]],
            "note": "MF-DEMO-E2E 12s demo approval"}
    sc, resp1 = http("POST", f"/api/v2/s09-approvals?workspace_id={WS}", body)
    assert sc in (200, 201), f"approval v1 failed: {sc} {resp1}"
    sc, resp2 = http("POST", f"/api/v2/s09-approvals/reapprove?workspace_id={WS}", body)
    assert sc in (200, 201), f"approval v2 failed: {sc} {resp2}"
    ckpt = {"id": resp2.get("id"), "hash": resp2.get("checkpoint_hash"),
            "revision": resp2.get("reskin_config_revision"), "v2_response": resp2}
    assert ckpt["id"] and ckpt["hash"] and ckpt["revision"], f"checkpoint fields missing: {resp2}"
    milestones["approval_v2"] = {"method": "POST", "path": "/api/v2/s09-approvals/reapprove",
                                 "status": sc, "at": now(), "checkpoint_id": ckpt["id"]}
    save_state({"checkpoint": ckpt, "milestones": milestones})
    print("checkpoint", ckpt["id"], ckpt["hash"][:16], flush=True)

    # ── 7. read the v2 authority back (HTTP, read-only) ──────────────────
    sc, auth = http("GET", f"/api/v2/s09-approvals/{ckpt['id']}/full-apply-authority?workspace_id={WS}")
    assert sc == 200 and isinstance(auth, dict), f"authority read failed: {sc} {auth}"
    save_state({"authority_read": {"status": sc, "keys": sorted(auth.keys())}})

    # ── 8. plan (in-process deterministic planner; no GPU, no shortcut) ──
    import re  # noqa: PLC0415

    from app.services.s09_approval import S09ApprovalRepository  # noqa: PLC0415
    from app.services.s10_chunk_plan import plan_full_apply  # noqa: PLC0415
    from app.services.s10_full_apply import _canonical_planner_inputs  # noqa: PLC0415

    graph_path = WT / GRAPH_REL
    graph_sha = sha_file(graph_path)
    graph_doc = json.loads(graph_path.read_text(encoding="utf-8"))
    prompt_text = ""
    for p in graph_doc["parameters"]:
        if p["name"] == "prompt":
            ptr = p["pointer"].split("|")[0]
            prompt_text = graph_doc["graph"][ptr.split("/")[1]]["inputs"]["text"]
    assert len(prompt_text) > 100, "frozen prompt not resolved"
    with factory() as s:
        authority = S09ApprovalRepository(s).full_apply_authority(ckpt["id"], WS)
    canonical = _canonical_planner_inputs(authority, checkpoint_id=ckpt["id"],
                                          checkpoint_hash=ckpt["hash"], checkpoint_revision=ckpt["revision"])
    dry = plan_full_apply(canonical["approved_checkpoint"], canonical["structural_lock_manifest"],
                          canonical["scene_manifest"], canonical["mapping"], canonical["compatibility_policy"],
                          chunk_config={"chunk_frames": 120, "overlap_frames": 0})
    dry_chunks = list(dry["chunks"])
    # Legacy (no-backend) plans emit one chunk per role layer; the real run
    # plans the GROUP shape (one generation unit per shot).  Derive the shot
    # ids + spans from the legacy chunks (unique shot_id, min start frame).
    shot_spans: dict = {}
    for c in dry_chunks:
        sid = str(c["shot_id"])
        s0 = int(c["core_start_frame"])
        shot_spans[sid] = min(shot_spans.get(sid, s0), s0)
    shots = sorted(shot_spans.items(), key=lambda kv: kv[1])
    print("dry shots:", shots, flush=True)
    assert len(shots) == 3, f"expected 3 shots, got {shots}"
    assert [kv[1] for kv in shots] == [0, 120, 240], f"shot spans unexpected: {shots}"
    bm = {"backend": "comfy_shot_engine", "profile_id": PROFILE,
          "capability": "source_video_motion_transfer", "graph_file": GRAPH_REL,
          "graph_sha256": graph_sha, "output_node": "246", "engine_base_url": COMFY_URL,
          "seed": SEED, "require_accepted_anchor": False,
          "shot_prompts": {sid: prompt_text for sid, _ in shots},
          "shot_anchors": {sid: {
              "relative_path": st["anchors"][ANCHOR_BY_START[s0]]["relative_path"],
              "sha256": st["anchors"][ANCHOR_BY_START[s0]]["sha256"]}
              for sid, s0 in shots}}
    real = plan_full_apply(canonical["approved_checkpoint"], canonical["structural_lock_manifest"],
                           canonical["scene_manifest"], canonical["mapping"], canonical["compatibility_policy"],
                           chunk_config={"chunk_frames": 120, "overlap_frames": 0, "execution_backend": bm})
    real_chunks = list(real["chunks"])
    assert len(real_chunks) == 3, f"group plan expected 3 chunks, got {len(real_chunks)}"
    real_shots = sorted({(str(c["shot_id"]), int(c["core_start_frame"])) for c in real_chunks},
                        key=lambda kv: kv[1])
    assert real_shots == shots, f"shot ids drifted: {real_shots} != {shots}"

    # ── 9. stage the 3 driving windows into the engine's input dir ───────
    from app.services.renderer_routes.composite import decode_rgb_frames, write_frames_mp4  # noqa: PLC0415
    frames = decode_rgb_frames(MANAGED / seed["source_rel"])
    assert len(frames) == 360, f"source decodes to {len(frames)} frames, expected 360"
    safe_re = re.compile(r"[^A-Za-z0-9._-]")
    windows = {}
    for c in real_chunks:
        sf, ef = int(c["core_start_frame"]), int(c["core_end_frame"]) + 1
        safe = safe_re.sub("_", str(c["chunk_id"])) or "chunk"
        basename = f"shotwin_{safe}_{sf}_{ef}.mp4"
        out_p = COMFY_BASE / "input" / basename
        write_frames_mp4(list(frames[sf:ef]), out_p, fps=30.0)
        assert out_p.is_file() and out_p.stat().st_size > 0, f"window write failed {basename}"
        windows[str(c["chunk_id"])] = {"basename": basename, "sha256": sha_file(out_p),
                                       "size": out_p.stat().st_size, "span": [sf, ef]}
    save_state({"plan": {"dry": [{"shot_id": str(c["shot_id"]), "start": c["core_start_frame"],
                                  "end": c["core_end_frame"]} for c in dry_chunks],
                         "real_chunks": [{"chunk_id": str(c["chunk_id"]), "shot_id": str(c["shot_id"]),
                                          "start": c["core_start_frame"], "end": c["core_end_frame"]} for c in real_chunks],
                         "windows": windows, "probe_sha": sha_file(SRC_12S)},
                "backend_manifest": bm})

    # ── 10. render submit (HTTP) ─────────────────────────────────────────
    submit_body = {"video_item_id": vid, "apply_checkpoint_id": ckpt["id"],
                   "expected_checkpoint_hash": ckpt["hash"], "expected_checkpoint_revision": ckpt["revision"],
                   "chunk_config": {"chunk_frames": 120, "overlap_frames": 0, "execution_backend": bm}}
    sc, resp = http("POST", f"/api/v2/projects/{pid}/full-apply?workspace_id={WS}", submit_body, timeout=120)
    assert sc in (200, 201, 202), f"render submit failed: {sc} {resp}"
    run_id = resp.get("run_id")
    assert run_id, f"no run_id: {resp}"
    milestones["render_submit"] = {"method": "POST", "path": "/api/v2/projects/{id}/full-apply",
                                   "status": sc, "at": now(), "run_id": run_id}
    milestones["status"] = {"method": "GET", "path": "/api/v2/full-apply/{run_id}",
                            "status": None, "at": now(), "run_id": run_id}
    save_state({"run_id": run_id, "milestones": milestones})
    print("RUN_ID", run_id, flush=True)
    return 0


# ── phase: monitor ───────────────────────────────────────────────────────────
def _dump_run(run_id: str) -> dict:
    from sqlalchemy import text  # noqa: PLC0415
    factory = _session_factory()
    out: dict = {}
    with factory() as s:
        run = s.execute(text("SELECT status,frame_count,plan_id,plan_hash FROM s10_full_apply_run"
                             " WHERE id=:r"), {"r": run_id}).mappings().first()
        out["run"] = dict(run) if run else None
        chunks = [dict(r) for r in s.execute(
            text("SELECT * FROM s10_full_apply_chunk WHERE run_id=:r ORDER BY chunk_index"),
            {"r": run_id}).mappings().all()]
        out["chunks"] = chunks
        pubs = [dict(r) for r in s.execute(
            text("SELECT * FROM s10_full_apply_publication WHERE run_id=:r"), {"r": run_id}).mappings().all()]
        for p in pubs:
            art = s.execute(text("SELECT id,relative_path,sha256,size_bytes FROM artifact WHERE id=:a"),
                            {"a": p.get("artifact_id")}).mappings().first()
            p["artifact"] = dict(art) if art else None
        out["publications"] = pubs
    return out


def phase_monitor() -> int:
    st = load_state()
    WS = _ws_id()
    run_id = st["run_id"]
    transitions = []
    gpu_samples = []
    last = None
    deadline = time.time() + 2700
    final_status = None
    while time.time() < deadline:
        sc, body = http("GET", f"/api/v2/full-apply/{run_id}?workspace_id={WS}", timeout=30)
        if sc == 200 and isinstance(body, dict):
            status = body.get("status")
            if status != last:
                transitions.append({"at": now(), "status": status, "body_preview":
                                    json.dumps(body, ensure_ascii=False)[:300]})
                print("status", status, flush=True)
                last = status
            if status in ("completed", "failed", "cancelled"):
                final_status = status
                break
        if len(gpu_samples) < 40:
            gpu_samples.append({"at": now(), "gpu": nvidia()})
        time.sleep(10)
    st = load_state()
    ms = st.get("milestones", {})
    if ms.get("status", {}).get("status") is None and sc == 200:
        ms["status"] = {**ms["status"], "status": sc, "at": now(), "final": final_status}
        save_state({"milestones": ms})
    time.sleep(5)
    dump = _dump_run(run_id)
    # per-chunk shot render records (executor receipts)
    import re as _re
    safe = _re.compile(r"[^A-Za-z0-9._-]")
    records = {}
    for c in dump["chunks"]:
        shot = str(c.get("shot_id") or "")
        cid = str(c.get("id") or "")
        rel = f"shot_render/{safe.sub('_', shot)}/{safe.sub('_', cid)}.json"
        p = MANAGED / rel
        if p.is_file():
            doc = json.loads(p.read_text(encoding="utf-8"))
            records[cid] = {"relative_path": rel, "sha256": sha_file(p),
                            "verdict": doc.get("verdict"),
                            "prompt_id": (doc.get("receipt") or {}).get("prompt_id"),
                            "output": (doc.get("output") or {}).get("sha256"),
                            "server_wall_s": (doc.get("receipt") or {}).get("server_side_wall_s"),
                            "vram_peak_mib": (doc.get("receipt") or {}).get("vram_peak_mib"),
                            "graph_submitted": (doc.get("graph") or {}).get("object_sha256_submitted"),
                            "window": doc.get("window")}
    chunk_members = {str(c.get("id")): c.get("member_layer_ids_json") for c in dump["chunks"]}
    result = {"transitions": transitions, "final_status": final_status, "db": dump,
              "chunk_members": chunk_members, "shot_records": records, "gpu_samples": gpu_samples[-8:],
              "window_files": sorted(p.name for p in (COMFY_BASE / "output").rglob("*.mp4"))[:12]}
    (RAW / "run_result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    save_state({"run_result_summary": {"final_status": final_status,
                                       "chunks": len(dump["chunks"]),
                                       "publications": [p.get("state") for p in dump["publications"]]}})
    print("MONITOR_DONE", final_status, "chunks", len(dump["chunks"]), flush=True)
    return 0 if final_status == "completed" else 1


# ── phase: qc ────────────────────────────────────────────────────────────────
def phase_qc() -> int:
    st = load_state()
    pid, vid = st["project_id"], st["video_id"]
    sc, body = http("POST", f"/api/v2/projects/{pid}/qc-check-runs",
                    {"video_item_id": vid, "scope": "full"})
    qc = {"submit_status": sc, "submit_body": body, "at": now()}
    if sc != 202:
        qc["error"] = f"qc submit refused: {sc}"
        save_state({"qc": qc})
        (RAW / "qc_receipt.json").write_text(json.dumps(qc, indent=1), encoding="utf-8")
        print("QC refused", sc, flush=True)
        return 0
    job_id = (body or {}).get("job_id")
    qc["job_id"] = job_id
    deadline = time.time() + 240
    runs = None
    while time.time() < deadline:
        sc2, listing = http("GET", f"/api/v2/projects/{pid}/qc-check-runs")
        if sc2 == 200:
            runs = listing
            state = ""
            if isinstance(listing, dict):
                rows = listing.get("runs") or listing.get("check_runs") or listing.get("items") or []
                for r in rows:
                    if str(r.get("video_item_id")) == str(vid):
                        state = str(r.get("state") or r.get("status") or "")
            qc["state"] = state
            if state.lower() in ("completed", "failed", "cancelled", "succeeded", "success"):
                break
        time.sleep(10)
    qc["listing"] = runs
    items = None
    for candidate in (f"/api/v2/projects/{pid}/qc-items", f"/api/v2/qc-items?project_id={pid}",
                      f"/api/v2/qc-items?video_item_id={vid}"):
        sc3, items = http("GET", candidate)
        if sc3 == 200:
            qc["items_path"] = candidate
            break
    if isinstance(items, dict):
        rows = items.get("items") or items.get("qc_items") or []
        qc["items_count"] = len(rows) if isinstance(rows, list) else None
        qc["items_sample"] = rows[:5] if isinstance(rows, list) else str(items)[:400]
    else:
        qc["items_raw"] = str(items)[:400]
    save_state({"qc": qc})
    (RAW / "qc_receipt.json").write_text(json.dumps(qc, indent=1, ensure_ascii=False), encoding="utf-8")
    print("QC_DONE", qc.get("state"), flush=True)
    return 0


# ── phase: export ────────────────────────────────────────────────────────────
def http_download(path: str, out_path: Path) -> tuple[int, int]:
    url = APP_URL + path
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        data = e.read()
        status = e.code
    if status == 200:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
    log_row({"ts": now(), "kind": "http_download", "path": path, "status": status,
             "bytes": len(data) if status == 200 else 0, "dur_s": round(time.time() - t0, 3)})
    print(f"[download] {path} -> {status} ({len(data)} bytes)", flush=True)
    return status, len(data)


def _poll_job(job_id: str, table: str = "job", deadline_s: int = 600) -> str:
    from sqlalchemy import text  # noqa: PLC0415
    factory = _session_factory()
    deadline = time.time() + deadline_s
    state = ""
    while time.time() < deadline:
        with factory() as s:
            row = s.execute(text(f"SELECT state FROM {table} WHERE id=:j"), {"j": job_id}).mappings().first()
        state = str((row or {}).get("state") or "")
        if state.lower() in ("completed", "failed", "cancelled", "succeeded", "success", "done"):
            break
        time.sleep(6)
    return state


def phase_export() -> int:
    st = load_state()
    pid, vid = st["project_id"], st["video_id"]
    WS = _ws_id()
    ckpt = st["checkpoint"]
    out: dict = {"at": now()}

    # 1. original-audio attach (durable job through the public action route)
    sc, body = http("POST", f"/api/v2/projects/{pid}/original-audio-attach", {"video_item_id": vid})
    out["audio_attach"] = {"status": sc, "body": body}
    job_id = None
    if isinstance(body, dict):
        job_id = body.get("job_id") or body.get("id") or (body.get("job") or {}).get("id")
    if job_id:
        out["audio_attach"]["job_id"] = job_id
        out["audio_attach"]["final_state"] = _poll_job(str(job_id))
    print("audio attach:", sc, out["audio_attach"].get("final_state"), flush=True)

    # 2. export submit (HTTP)
    submit = {"project_id": pid, "video_item_id": vid, "profile_id": PROFILE,
              "checkpoint_id": ckpt["id"], "checkpoint_hash": ckpt["hash"],
              "checkpoint_revision": ckpt["revision"], "idempotency_key": f"demo-export-{pid}"}
    sc, resp = http("POST", f"/s12-exports/submit?workspace_id={WS}", submit, timeout=120)
    out["submit"] = {"status": sc, "body": resp}
    milestones = st.get("milestones", {})
    if sc not in (200, 201, 202):
        milestones["export_submit"] = {"method": "POST", "path": "/s12-exports/submit",
                                       "status": sc, "at": now(), "error": json.dumps(resp)[:400]}
        save_state({"export": out, "milestones": milestones})
        (RAW / "export_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print("EXPORT refused", sc, flush=True)
        return 1
    run_id = (resp or {}).get("run_id") or (resp or {}).get("id")
    out["run_id"] = run_id
    milestones["export_submit"] = {"method": "POST", "path": "/s12-exports/submit",
                                   "status": sc, "at": now(), "run_id": run_id}
    save_state({"export": out, "milestones": milestones})
    print("export run", run_id, flush=True)

    # 3. poll run state
    deadline = time.time() + 1800
    final = None
    last = None
    while time.time() < deadline:
        sc2, body2 = http("GET", f"/s12-exports/{run_id}?workspace_id={WS}")
        status = (body2 or {}).get("state") or (body2 or {}).get("status") if isinstance(body2, dict) else None
        if status != last:
            print("export state", status, flush=True)
            last = status
        if str(status).lower() in ("completed", "failed", "cancelled", "succeeded", "success", "published"):
            final = status
            break
        time.sleep(10)
    out["final_state"] = final

    # 4. result + media
    sc3, res = http("GET", f"/s12-exports/{run_id}/result?workspace_id={WS}")
    out["result"] = {"status": sc3, "body": res}
    media_path = EXPORT / "demo_final.mp4"
    sc4, nbytes = http_download(f"/s12-exports/{run_id}/media?workspace_id={WS}", media_path)
    out["media"] = {"status": sc4, "bytes": nbytes, "path": str(media_path),
                    "sha256": sha_file(media_path) if media_path.is_file() else None}
    save_state({"export": out})
    (RAW / "export_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = media_path.is_file() and media_path.stat().st_size > 0
    print("EXPORT_DONE", final, "media", out["media"]["sha256"], flush=True)
    return 0 if ok else 1


# ── phase: verify ────────────────────────────────────────────────────────────
def _ffprobe_json(path: Path) -> dict:
    p = sh(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], "ffprobe")
    return json.loads(p.stdout)


def phase_verify() -> int:
    st = load_state()
    demo = EXPORT / "demo_final.mp4"
    pub = None
    rr = st.get("run_result_summary") or {}
    dump = st.get("_tmp") or {}
    # publication artifact (from monitor dump file)
    pub_meta = None
    rrf = RAW / "run_result.json"
    if rrf.is_file():
        dump = json.loads(rrf.read_text(encoding="utf-8"))
        for p in dump.get("db", {}).get("publications", []):
            art = p.get("artifact") or {}
            if art.get("relative_path"):
                cand = MANAGED / str(art["relative_path"])
                if cand.is_file():
                    pub_meta = {"path": str(cand), "sha256": sha_file(cand),
                                "size": cand.stat().st_size, "declared_sha": art.get("sha256"),
                                "state": p.get("state")}
    if not demo.is_file():
        assert pub_meta, "no export media and no publication found"
        shutil.copyfile(pub_meta["path"], demo)
    n = None
    probe = _ffprobe_json(demo)
    vstream = next((s for s in probe["streams"] if s.get("codec_type") == "video"), {})
    astream = next((s for s in probe["streams"] if s.get("codec_type") == "audio"), None)
    fps = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate")
    duration = float((probe.get("format") or {}).get("duration") or 0)
    # PTS scan
    pts_p = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                "-of", "csv=p=0", str(demo)], "ffprobe_pts")
    pts = [float(x.split(",")[0]) for x in pts_p.stdout.replace("\r", "").split("\n") if x.strip()]
    monotonic = all(pts[i] < pts[i + 1] for i in range(len(pts) - 1))
    # full decode
    dec = sh(["ffmpeg", "-v", "error", "-i", str(demo), "-f", "null", "-"], "ffmpeg_decode", timeout=300)
    # contact sheet 9 frames
    nframes = len(pts)
    idx = [round(i * (nframes - 1) / 8) for i in range(9)] if nframes > 9 else list(range(nframes))
    expr = "+".join(f"eq(n\\,{i})" for i in idx)
    sheet = RAW / "preview_contact_sheet.png"
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(demo), "-vf", f"select='{expr}',tile=3x3",
        "-frames:v", "1", str(sheet)], "contact_sheet", timeout=300)
    sheet_ok = sheet.is_file() and sheet.stat().st_size > 0
    assert sheet_ok, "contact sheet was not written (0 bytes / missing)"
    verify = {
        "demo": str(demo), "demo_sha256": sha_file(demo), "demo_bytes": demo.stat().st_size,
        "publication": pub_meta,
        "video": {"codec": vstream.get("codec_name"), "width": vstream.get("width"),
                  "height": vstream.get("height"), "fps": fps, "frames": nframes,
                  "duration_s": duration, "pts_monotonic": monotonic,
                  "pts_first": pts[0] if pts else None, "pts_last": pts[-1] if pts else None},
        "audio": ({"codec": astream.get("codec_name"), "sample_rate": astream.get("sample_rate"),
                   "channels": astream.get("channels")} if astream else None),
        "decode_rc": dec.returncode, "decode_ok": dec.returncode == 0,
        "contact_sheet": {"path": str(sheet), "bytes": sheet.stat().st_size, "frames": idx},
        "gpu_after": nvidia(),
    }
    (RAW / "ffprobe_demo.txt").write_text(json.dumps(probe, indent=1) + "\n\nPTS_MONOTONIC="
                                          + str(monotonic) + "\nDECODE_RC=" + str(dec.returncode) + "\n",
                                          encoding="utf-8")
    # sha256 manifest over the evidence root (locked live files recorded, not fatal)
    lines = []
    locked = []
    for p in sorted(EVID.rglob("*")):
        if p.is_file():
            try:
                lines.append(f"{sha_file(p)}  {p.relative_to(EVID).as_posix()}  {p.stat().st_size}")
            except PermissionError:
                locked.append(p.relative_to(EVID).as_posix())
    if locked:
        lines.append("# locked-during-scan (live runtime): " + ", ".join(locked))
    (RAW / "sha256_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_state({"verify": verify, "manifest_files": len(lines), "manifest_locked": locked})
    (RAW / "verify_receipt.json").write_text(json.dumps(verify, indent=1, ensure_ascii=False), encoding="utf-8")
    print("VERIFY", json.dumps({k: verify[k] for k in ("demo_sha256", "video", "audio", "decode_ok")},
                               ensure_ascii=False), flush=True)
    ok = (verify["video"]["width"] == 640 and verify["video"]["height"] == 368
          and verify["video"]["frames"] == 360 and verify["decode_ok"] and monotonic)
    return 0 if ok else 1


# ── phase: report ────────────────────────────────────────────────────────────
def phase_report() -> int:
    st = load_state()
    rr = json.loads((RAW / "run_result.json").read_text(encoding="utf-8")) if (RAW / "run_result.json").is_file() else {}
    exp = st.get("export", {})
    ver = st.get("verify", {})
    ms = st.get("milestones", {})
    d = rr.get("db", {})
    run = d.get("run") or {}
    chunks = d.get("chunks") or []
    pubs = d.get("publications") or []
    recs = rr.get("shot_records") or {}
    lines = []
    A = lines.append
    A("# REPORT - MF-DEMO-E2E-R3 (Phase C final: FROZEN CANDIDATE #6)")
    A("")
    A(f"- Owner: session này · Mode NEW_SESSION_ONE_TASK · Model `ocg/deepseek-v4.1-flash` (custom, thinking ON, fallback OFF)")
    A(f"- Tree (READ-ONLY code): `{WT}` · HEAD đo tại chỗ: `{st.get('app', {}).get('candidate_head', '?')}`")
    A("- Candidate HEAD do tai cho: `" + str(st.get("app", {}).get("candidate_head", "?")) + "`")
    A(f"- Evidence root: `{EVID}` · terminal **TASK_SUBMITTED** · QUALITY_ACCEPTED=0 · không push")
    A("")
    A("## 1. App chạy được (từ candidate, HTTP thật)")
    app = st.get("app", {})
    A(f"- uvicorn pid `{app.get('pid')}` port `{app.get('port')}` ready `{app.get('ready_s')}s`; `/health` → `{app.get('health')}`")
    A(f"- Runtime cô lập: MOTIONFORGE_ROOT=`{APP_ROOT}` (DB `db/…/motionforge.db`, managed `artifacts/`); cwd=tree; `PYTHONDONTWRITEBYTECODE=1`.")
    A("")
    A("## 2. HTTP milestones (status 2xx thật)")
    for k in ("project_create", "structural_lock", "approval_v2", "render_submit", "status", "export_submit"):
        m = ms.get(k)
        if m:
            A(f"- **{k}**: `{m.get('method')} {m.get('path')}` → `{m.get('status')}` at {m.get('at')}")
    A("")
    A("## 3. Engine (ComfyUI cô lập, 1 GPU job/lần)")
    cx = st.get("comfy", {})
    A(f"- port `{cx.get('port')}`, pid `{cx.get('pid')}`, ready `{cx.get('ready_s')}s`, version `{cx.get('version')}`, epoch `{str(cx.get('epoch_instance_id'))[:16]}`")
    A(f"- profile `{PROFILE}` · seed `{SEED}` · graph `{GRAPH_REL}` sha `{(st.get('plan') or {}).get('probe_sha', '')}`")
    A(f"- argv: `{' '.join((cx.get('argv') or [])[:8])} …`")
    A("")
    A("## 4. Run 3 shot (12s) — DB + receipt từng shot")
    A(f"- run `{st.get('run_id')}` status **{run.get('status')}** frame_count `{run.get('frame_count')}` plan `{str(run.get('plan_id'))[:20]}`")
    for c in chunks:
        rec = recs.get(str(c.get("id"))) or {}
        A(f"- chunk `{str(c.get('id'))[:18]}` shot `{str(c.get('shot_id'))[:18]}` [{c.get('core_start_frame')},{c.get('core_end_frame')}] state `{c.get('state')}` verified `{c.get('verified')}`")
        if rec:
            A(f"    - receipt verdict `{rec.get('verdict')}` prompt_id `{rec.get('prompt_id')}` wall `{rec.get('server_wall_s')}s` vram `{rec.get('vram_peak_mib')}` MiB out `{str(rec.get('output'))[:16]}`")
    for p in pubs:
        art = p.get("artifact") or {}
        A(f"- publication `{p.get('id')}` state `{p.get('state')}` frames `{p.get('frame_count')}` artifact `{art.get('relative_path')}` sha `{str(art.get('sha256'))[:16]}`")
    A("")
    A("## 5. QC + Export")
    qc = st.get("qc") or {}
    A(f"- QC submit `{qc.get('submit_status')}` job `{qc.get('job_id')}` state `{qc.get('state')}` items `{qc.get('items_count')}`")
    A(f"- export run `{exp.get('run_id')}` final `{exp.get('final_state')}` submit `{(exp.get('submit') or {}).get('status')}`")
    A(f"- demo media: `{exp.get('media', {}).get('path')}` sha `{exp.get('media', {}).get('sha256')}` bytes `{exp.get('media', {}).get('bytes')}`")
    A("")
    A("## 6. Verify (số đo thật)")
    A(f"- video: {ver.get('video')}")
    A(f"- audio: {ver.get('audio')}")
    A(f"- decode_ok `{ver.get('decode_ok')}` · contact sheet `{ver.get('contact_sheet', {}).get('path')}` bytes `{ver.get('contact_sheet', {}).get('bytes')}`")
    A(f"- demo sha256 `{ver.get('demo_sha256')}` · publication `{ver.get('publication')}`")
    A("")
    A("## 7. Disclosures / findings")
    A("- Bước import/analyze/evidence + placement nguồn gắn qua DB seed đúng kiểu harness sản phẩm (không có route upload durable); mọi mốc khác đi HTTP thật; xem OPEN_FINDING nếu còn.")
    A("- Oversized/khác: xem `raw/commands.jsonl` + `raw/*_receipt.json`.")
    (EVID / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("REPORT written", flush=True)
    return 0


# ── phase: shutdown ──────────────────────────────────────────────────────────
def phase_shutdown() -> int:
    st = load_state()
    out: dict = {"at": now()}
    app = st.get("app") or {}
    if app.get("pid"):
        sh(["taskkill", "/PID", str(app["pid"]), "/F"], "stop_app")
        time.sleep(3)
        out["app"] = {"pid": app["pid"], "pid_gone": not pid_alive(int(app["pid"])),
                      "port_closed": not port_open(APP_PORT)}
    comfy = st.get("comfy") or {}
    if comfy.get("pid"):
        before = listener_pids(COMFY_PORT)
        sh(["taskkill", "/PID", str(comfy["pid"]), "/F"], "stop_comfy")
        time.sleep(3)
        for lp in listener_pids(COMFY_PORT):
            sh(["taskkill", "/PID", str(lp), "/F"], "stop_comfy_listener")
        time.sleep(2)
        out["comfy"] = {"pid": comfy["pid"], "pid_gone": not pid_alive(int(comfy["pid"])),
                        "listener_pids_before": before, "listeners_after": listener_pids(COMFY_PORT),
                        "port_closed": not port_open(COMFY_PORT)}
    phase_harvest()
    por = sh(["git", "status", "--porcelain"], "porcelain", cwd=WT)
    head = sh(["git", "rev-parse", "HEAD"], "head", cwd=WT)
    out["tree"] = {"porcelain": [ln for ln in por.stdout.split("\n") if ln.strip()],
                   "head": head.stdout.strip()}
    out["POST_STOP_VERIFIED"] = bool(out.get("comfy", {}).get("pid_gone")
                                     and out.get("comfy", {}).get("port_closed"))
    (RAW / "comfy_shutdown.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    save_state({"shutdown": out})
    print("SHUTDOWN", json.dumps(out.get("comfy", {}), ensure_ascii=False), "porcelain",
          len(out["tree"]["porcelain"]), flush=True)
    return 0


# ── phase: engine (real GPU renders through the app's own executor) ──────────
def _engine_inputs():
    """Rebuild the worker's canonical inputs WITHOUT touching the tree.

    The same private app functions the worker calls: canonical planner inputs
    (route path), canonical render pins (route path), authoritative mapping
    (worker path).  Returns (canonical, manifest_pins, mapping_by_layer, plan).
    """
    from app.api.routes.s10_full_apply import _resolve_canonical_render_pins  # noqa: PLC0415
    from app.services.s09_approval import S09ApprovalRepository  # noqa: PLC0415
    from app.services.s10_chunk_plan import plan_full_apply  # noqa: PLC0415
    from app.services.s10_full_apply import _canonical_planner_inputs  # noqa: PLC0415
    from app.workflow.s10_full_apply_jobs import _authoritative_mapping_by_layer  # noqa: PLC0415

    st = load_state()
    WS = _ws_id()
    ckpt = st["checkpoint"]
    bm = st["backend_manifest"]
    factory = _session_factory()
    with factory() as s:
        auth_v2 = S09ApprovalRepository(s).full_apply_authority(ckpt["id"], WS)
        canonical = _canonical_planner_inputs(auth_v2, checkpoint_id=ckpt["id"],
                                              checkpoint_hash=ckpt["hash"],
                                              checkpoint_revision=ckpt["revision"])
        pins = _resolve_canonical_render_pins(
            s, workspace_id=WS, project_id=st["project_id"], video_item_id=st["video_id"],
            apply_checkpoint_id=ckpt["id"], authority=auth_v2, managed_root=MANAGED)
    mapping_by_layer = _authoritative_mapping_by_layer(canonical)
    plan = plan_full_apply(canonical["approved_checkpoint"], canonical["structural_lock_manifest"],
                           canonical["scene_manifest"], canonical["mapping"], canonical["compatibility_policy"],
                           chunk_config={"chunk_frames": 120, "overlap_frames": 0, "execution_backend": bm})
    return canonical, pins, mapping_by_layer, plan


def phase_engine() -> int:
    import re as _re  # noqa: PLC0415

    st = load_state()
    dry = os.environ.get("MFDEMO_ENGINE_DRY") == "1"
    WS = _ws_id()
    seed = st["seed"]
    bm = st["backend_manifest"]
    canonical, pins, mapping_by_layer, plan = _engine_inputs()
    manifest = dict(pins)
    manifest["shot_render_max_wall_s"] = 1800.0
    # The engine's reservation/receipt filenames are <64-hex instance id>__<attempt>
    # + suffix; with the deep EVID root they exceed Windows MAX_PATH (measured:
    # 276 chars).  Stage this run under a SHORT managed root (Windows-native,
    # outside the checkout) and harvest the receipts back into the evidence root.
    SM = MANAGED  # R2: engine runs on the LIVE short managed root (epoch already staged)
    for sub in ("media_engine/comfy_shot_engine", "shot_render/inputs",
                f"s10_full_apply/_authority/{st['video_id']}"):
        (SM / sub).mkdir(parents=True, exist_ok=True)
    ep = SM / "media_engine" / "comfy_shot_engine" / "instance_epoch.json"
    assert ep.is_file(), f"engine epoch missing at {ep}"
    for name, meta in (st.get("anchors") or {}).items():
        dst = SM / "shot_render" / "inputs" / name
        src = MANAGED / meta["relative_path"]
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        assert sha_file(dst) == meta["sha256"], f"anchor copy drift {name}"
    src_dst = SM / "s10_full_apply" / "_authority" / st["video_id"] / SRC_12S.name
    src = MANAGED / st["seed"]["source_rel"]
    if src.resolve() != src_dst.resolve():
        shutil.copyfile(src, src_dst)
    assert sha_file(src_dst) == st["source_12s"]["sha256"], "source copy drift"
    print("engine managed root:", SM, flush=True)
    chunks = list(plan["chunks"])
    assert len(chunks) == 3, f"engine plan expected 3 chunks, got {len(chunks)}"
    print("pins keys:", sorted(pins.keys()), flush=True)
    print("replacement_assets keys:", sorted((pins.get("replacement_assets") or {}).keys()), flush=True)
    print("mapping layers:", sorted(mapping_by_layer.keys()), flush=True)
    out: dict = {"shots": []}
    for i, c in enumerate(chunks):
        shot_id, chunk_id = str(c["shot_id"]), str(c["chunk_id"])
        members = [str(m) for m in c["member_layer_ids"]]
        print(f"chunk {chunk_id} shot {shot_id} span {c['core_start_frame']}-{c['core_end_frame']} members {members}", flush=True)
        cast = []
        for layer_id in members:
            m = mapping_by_layer[layer_id]
            entry = (manifest.get("replacement_assets") or {}).get(layer_id) or {}
            if not entry:  # role-keyed fallback (pins are keyed by object_role_id)
                entry = (manifest.get("replacement_assets") or {}).get(str(m.get("role_id") or "")) or {}
            cast.append({
                "role": layer_id,
                "character_id": str(m.get("role_id") or layer_id),
                "pack_version_id": str(m["pack_version"]),
                "references": [{
                    "key": f"{layer_id}@base",
                    "artifact_id": str(entry.get("artifact_id") or ""),
                    "kind": "image",
                    "sha256": str(entry.get("sha256") or "").lower(),
                    "store_relative_path": str(entry.get("rel") or ""),
                    "size_bytes": entry.get("size_bytes"),
                }],
            })
        anchor_entry = bm["shot_anchors"][shot_id]
        request = {
            "workspace_id": WS, "project_id": st["project_id"], "video_id": st["video_id"],
            "shot_id": shot_id, "chunk_id": chunk_id,
            "attempt_id": f"shot-demo-{chunk_id[:12]}",
            "backend": bm,
            "graph": {"file": str(bm["graph_file"]), "file_sha256": str(bm["graph_sha256"])},
            "parameters": {
                "prompt": bm["shot_prompts"][shot_id],
                "filename_prefix": f"s10_full_apply/demo/{shot_id}",
                "seed": int(bm["seed"]),
            },
            "staged_inputs": {"anchor": {"relative_path": anchor_entry["relative_path"],
                                         "sha256": anchor_entry["sha256"]}},
            "anchor": {"relative_path": anchor_entry["relative_path"], "sha256": anchor_entry["sha256"]},
            "cast": cast,
            "source": {
                "artifact_id": str(manifest.get("source_media_artifact_id") or ""),
                "sha256": str(manifest["source_media_sha256"]),
                "relative_path": str(manifest["source_media_rel"]),
                "size_bytes": manifest.get("source_media_size_bytes"),
                "fps": {"num": 30, "den": 1},
                "span": {"start_frame": int(c["core_start_frame"]),
                         "end_frame_exclusive": int(c["core_end_frame"]) + 1},
            },
            "output_contract": {
                "width": 640, "height": 368, "fps_num": 30, "fps_den": 1,
                "frame_count": int(c["core_end_frame"]) - int(c["core_start_frame"]) + 1,
                "container": "mp4", "video_codec": "h264",
                "audio": {"mode": "source_remux",
                          "source_artifact_id": str(manifest.get("source_media_artifact_id") or "")},
            },
            "budget": {"resource_class": "gpu_12gb", "max_wall_seconds": 1800.0},
            "require_accepted_anchor": False,
            "anchor_identity_digest": None,
        }
        if dry:
            out["shots"].append({"chunk_id": chunk_id, "shot_id": shot_id, "members": members,
                                 "cast_refs": [r["references"][0]["sha256"][:16] for r in cast],
                                 "span": request["source"]["span"]})
            continue
        from app.services.shot_reskin_executor import run_shot_render  # noqa: PLC0415
        t0 = time.time()
        res = run_shot_render(managed_root=str(SM), request=request)
        wall = round(time.time() - t0, 2)
        rec = {k: res.get(k) for k in ("output_relative_path", "output_sha256", "output_size_bytes",
                                       "decoded_sha256", "decoded_frame_count", "fps_num", "fps_den",
                                       "prompt_id", "graph_object_sha256_submitted", "verdict")}
        rec["wall_s"] = wall
        rec["window"] = res.get("window")
        rec["chunk_id"] = chunk_id
        rec["shot_id"] = shot_id
        out["shots"].append(rec)
        print("SHOT_DONE", json.dumps({k: rec[k] for k in ("shot_id", "prompt_id", "wall_s",
                                                          "output_sha256", "output_size_bytes")}, default=str), flush=True)
        save_state({"engine": out})
    if dry:
        save_state({"engine_dry": out})
        (RAW / "engine_dry.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print("ENGINE_DRY:", json.dumps(out, ensure_ascii=False)[:1200], flush=True)
        return 0

    # harvest the engine receipts + outputs back into the evidence root
    harvest = {"records": [], "outputs": []}
    for p in sorted((SM / "shot_render").rglob("*")):
        if p.is_file():
            rel = p.relative_to(SM)
            dst = EVID / "raw" / "renders" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            harvest["records"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                       "bytes": dst.stat().st_size})
    for r in out["shots"]:
        src_o = SM / str(r["output_relative_path"])
        dst_o = MANAGED / str(r["output_relative_path"])
        if src_o.resolve() != dst_o.resolve():
            dst_o.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_o, dst_o)
        assert sha_file(dst_o) == r["output_sha256"], "output copy drift"
        harvest["outputs"].append({"rel": str(r["output_relative_path"]), "sha256": r["output_sha256"],
                                   "bytes": r["output_size_bytes"]})
    out["harvest"] = harvest
    for p in sorted((SM / "media_engine" / "comfy_shot_engine").rglob("*.json")):
        rel = p.relative_to(SM)
        if "reservations" in rel.parts and "closed" not in rel.parts:
            continue
        dst = EVID / "raw" / "engine_state" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
    # assemble the 12s demo: concat the 3 shot outputs + original audio remux
    outs = [MANAGED / str(r["output_relative_path"]) for r in out["shots"]]
    for p in outs:
        assert p.is_file() and p.stat().st_size > 0, f"shot output missing: {p}"
    lst = RAW / "concat_shots.txt"
    lst.write_text("\n".join("file '" + str(p).replace("\\", "/") + "'" for p in outs) + "\n", encoding="utf-8")
    concat_v = RAW / "shots_concat.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c", "copy", "-an", str(concat_v)], "concat_shots", check=True)
    demo = EXPORT / "demo_final.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(concat_v), "-i", str(SRC_12S),
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-t", "12.0", str(demo)], "assemble_demo", check=True)
    assert demo.is_file() and demo.stat().st_size > 0, "assembled demo missing"
    out["demo"] = {"path": str(demo), "sha256": sha_file(demo), "bytes": demo.stat().st_size}
    out["source_sha"] = st["source_12s"]["sha256"]
    out["assembly"] = {"concat_manifest": str(lst), "mode": "concat_copy + source audio remux (-t 12.0)"}
    save_state({"engine": out})
    (RAW / "engine_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("DEMO_READY", out["demo"]["sha256"], out["demo"]["bytes"], flush=True)
    return 0


# ── phase: engine3 (shots 2+3 + assembly after the typed engine refusal) ─────
def _harvest_server_outputs(shot_id: str) -> list[dict]:
    """Copy the server-side outputs of one shot into the evidence root."""
    out = []
    base = COMFY_BASE / "output" / "s10_full_apply" / "demo"
    for p in sorted(base.glob(f"{shot_id}_*.mp4")):
        rel = p.relative_to(COMFY_BASE / "output")
        dst = EVID / "raw" / "renders" / "server_output" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        pr = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                 "-show_entries", "stream=width,height,nb_read_frames",
                 "-show_entries", "format=duration", "-of", "csv=p=0", str(dst)], f"probe_{p.name}")
        out.append({"file": rel.as_posix(), "sha256": sha_file(dst), "bytes": dst.stat().st_size,
                    "probe": pr.stdout.strip()})
    return out


def _history_for(shot_id: str) -> list[dict]:
    import urllib.request as _u  # noqa: PLC0415
    try:
        with _u.urlopen(COMFY_URL + "/history", timeout=30) as r:
            hist = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    hits = []
    for pid, rec in hist.items():
        for nid, o in (rec.get("outputs") or {}).items():
            for item in (o.get("images") or []):
                if str(item.get("filename", "")).startswith(shot_id):
                    hits.append({"prompt_id": pid, "node": nid,
                                 "status": (rec.get("status") or {}).get("status_str"),
                                 "filename": item.get("filename")})
    return hits


def phase_engine3() -> int:
    st = load_state()
    WS = _ws_id()
    bm = st["backend_manifest"]
    canonical, pins, mapping_by_layer, plan = _engine_inputs()
    manifest = dict(pins)
    manifest["shot_render_max_wall_s"] = 1800.0
    SM = Path("C:/Users/Admin/AppData/Local/Temp/mfd-e2e")
    chunks = list(plan["chunks"])
    out: dict = {"shots": [], "refusals": [], "at": now()}

    for c in chunks:
        shot_id, chunk_id = str(c["shot_id"]), str(c["chunk_id"])
        span = (int(c["core_start_frame"]), int(c["core_end_frame"]) + 1)
        if (SM / "shot_render" / shot_id).is_dir() or st.get("engine3_skip", {}).get(chunk_id):
            pass
        # re-stage the window + graph + binding exactly like the executor does
        import re as _re  # noqa: PLC0415

        from app.adapters.media_engine.comfy import ComfyShotEngine  # noqa: PLC0415
        from app.schemas.shot_reskin import EngineDecodedFacts  # noqa: PLC0415
        from app.services import shot_reskin_executor as EX  # noqa: PLC0415
        root = EX.ManagedRoot(str(SM))
        anchor_entry = bm["shot_anchors"][shot_id]
        EX._verify_staged_inputs(root, {"anchor": {"relative_path": anchor_entry["relative_path"],
                                                   "sha256": anchor_entry["sha256"]}})
        anchor_abs = SM / anchor_entry["relative_path"]
        anchor_ref = EX.ArtifactRef(artifact_id=str(anchor_entry.get("artifact_id") or anchor_entry["sha256"][:32]),
                                    kind="image", sha256=anchor_entry["sha256"],
                                    store_relative_path=anchor_entry["relative_path"],
                                    size_bytes=anchor_abs.stat().st_size)
        window = EX._stage_shot_source_window(root, chunk_id=chunk_id,
                                              source_abs=SM / str(manifest["source_media_rel"]),
                                              span_start=span[0], span_end_exclusive=span[1],
                                              fps_num=30, fps_den=1)
        graph_doc = json.loads((WT / str(bm["graph_file"])).read_text(encoding="utf-8"))
        parameters = {"prompt": bm["shot_prompts"][shot_id],
                      "filename_prefix": f"s10_full_apply/demo/{shot_id}",
                      "seed": int(bm["seed"]), "source": window["basename"],
                      "anchor": Path(str(anchor_entry["relative_path"])).name}
        patched_graph, _patch = EX.prepare_graph(graph_doc, parameters)
        submitted_sha = EX._graph_object_sha256(patched_graph)
        profile = EX.select_profile(PROFILE)
        primary, auxiliary = EX.profile_models(profile)
        request = {
            "workspace_id": WS, "project_id": st["project_id"], "video_id": st["video_id"],
            "shot_id": shot_id, "chunk_id": chunk_id, "attempt_id": f"shot-demo-{chunk_id[:12]}",
            "backend": bm,
            "graph": {"file": str(bm["graph_file"]), "file_sha256": str(bm["graph_sha256"])},
            "parameters": parameters,
            "staged_inputs": {"anchor": {"relative_path": anchor_entry["relative_path"],
                                         "sha256": anchor_entry["sha256"]}},
            "anchor": {"relative_path": anchor_entry["relative_path"], "sha256": anchor_entry["sha256"]},
            "cast": [],
            "source": {"artifact_id": str(manifest.get("source_media_artifact_id") or ""),
                       "sha256": str(manifest["source_media_sha256"]),
                       "relative_path": str(manifest["source_media_rel"]),
                       "size_bytes": manifest.get("source_media_size_bytes"),
                       "fps": {"num": 30, "den": 1},
                       "span": {"start_frame": span[0], "end_frame_exclusive": span[1]}},
            "output_contract": {"width": 640, "height": 368, "fps_num": 30, "fps_den": 1,
                                "frame_count": span[1] - span[0], "container": "mp4",
                                "video_codec": "h264",
                                "audio": {"mode": "source_remux",
                                          "source_artifact_id": str(manifest.get("source_media_artifact_id") or "")}},
            "budget": {"resource_class": "gpu_12gb", "max_wall_seconds": 1800.0},
            "require_accepted_anchor": False, "anchor_identity_digest": None,
        }
        for layer_id in [str(m) for m in c["member_layer_ids"]]:
            m = mapping_by_layer[layer_id]
            entry = (manifest.get("replacement_assets") or {}).get(layer_id) or {}
            if not entry:
                entry = (manifest.get("replacement_assets") or {}).get(str(m.get("role_id") or "")) or {}
            request["cast"].append({"role": layer_id, "character_id": str(m.get("role_id") or layer_id),
                                    "pack_version_id": str(m["pack_version"]),
                                    "references": [{"key": f"{layer_id}@base",
                                                    "artifact_id": str(entry.get("artifact_id") or ""),
                                                    "kind": "image",
                                                    "sha256": str(entry.get("sha256") or "").lower(),
                                                    "store_relative_path": str(entry.get("rel") or ""),
                                                    "size_bytes": entry.get("size_bytes")}]})
        binding = EX._build_binding(request=request, capability="source_video_motion_transfer",
                                    attempt_id=request["attempt_id"], primary=primary, auxiliary=auxiliary,
                                    graph_sha256=submitted_sha, seed=int(bm["seed"]), fps_num=30, fps_den=1,
                                    anchor_ref=anchor_ref)
        terminal = {str(bm.get("output_node") or "246"): {"kind": "video", "media_type": "video"}}
        engine = ComfyShotEngine(managed_root=str(SM), base_url=COMFY_URL)
        t0 = time.time()
        refusal = None
        try:
            rec = engine.run_shot(binding, graph=patched_graph, terminal_outputs=terminal, shot_id=shot_id,
                                  decoded_facts=EngineDecodedFacts(decoded_frames=span[1] - span[0],
                                                                   first_pts_ticks=0, timebase="30/1",
                                                                   mapping=None))
            outcome = "completed"
        except Exception as exc:  # noqa: BLE001 — the pinned-engine refusal is the recorded finding
            refusal = {"type": type(exc).__name__, "code": str(getattr(exc, "code", "")),
                       "message": str(exc)[:300]}
            outcome = "refused"
        finally:
            import contextlib as _ctx  # noqa: PLC0415
            with _ctx.suppress(Exception):
                engine.close()
        wall = round(time.time() - t0, 2)
        harvested = _harvest_server_outputs(shot_id)
        hist = _history_for(shot_id)
        out["shots"].append({"shot_id": shot_id, "chunk_id": chunk_id, "span": list(span),
                             "outcome": outcome, "wall_s": wall, "refusal": refusal,
                             "prompt_ids": sorted({h["prompt_id"] for h in hist}),
                             "prompt_status": sorted({str(h["status"]) for h in hist}),
                             "server_outputs": harvested})
        if refusal:
            out["refusals"].append({"shot_id": shot_id, **refusal})
        print("SHOT3_DONE", json.dumps({"shot_id": shot_id, "outcome": outcome, "wall_s": wall,
                                        "prompts": sorted({h['prompt_id'] for h in hist}),
                                        "files": [h["file"] for h in harvested]}, ensure_ascii=False), flush=True)
        save_state({"engine3": out})

    # assembly: one main 120f/640-wide server clip per shot (highest counter) + audio remux
    mains = []
    for c in chunks:
        sid = str(c["shot_id"])
        base = COMFY_BASE / "output" / "s10_full_apply" / "demo"
        pick = None
        for p in sorted(base.glob(f"{sid}_*.mp4")):
            pr = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                     "-show_entries", "stream=width,nb_read_frames", "-of", "csv=p=0", str(p)],
                    f"pick_{p.name}")
            parts = [x for x in pr.stdout.replace("\r", "").split("\n") if x.strip()]
            if parts and parts[0].split(",")[:2] == ["640", "120"]:
                pick = p  # sorted() keeps the newest counter last
        assert pick is not None, f"no main 120f clip for {sid}"
        mains.append(pick)
    lst = RAW / "concat_shots.txt"
    lst.write_text("\n".join("file '" + str(p).replace("\\", "/") + "'" for p in mains) + "\n", encoding="utf-8")
    concat_v = RAW / "shots_concat.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
        "-an", str(concat_v)], "concat_shots", check=True)
    demo = EXPORT / "demo_final.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(concat_v), "-i", str(SRC_12S), "-map", "0:v:0",
        "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-t", "12.0", str(demo)],
       "assemble_demo", check=True)
    assert demo.is_file() and demo.stat().st_size > 0, "assembled demo missing"
    out["demo"] = {"path": str(demo), "sha256": sha_file(demo), "bytes": demo.stat().st_size,
                   "mains": [str(p) for p in mains]}
    out["assembly"] = "3x server 00001_ clips concat(copy) + source audio remux (-t 12.0)"
    save_state({"engine3": out})
    (RAW / "engine3_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("DEMO_READY", out["demo"]["sha256"], out["demo"]["bytes"], flush=True)
    return 0


# ── phase: harvest_engine (worker-owned renders: receipts + records + DB) ────
def phase_harvest_engine() -> int:
    from sqlalchemy import text as _text  # noqa: PLC0415
    out: dict = {"at": now(), "engine_state": [], "renders": [], "server_outputs": []}
    ev_root = MANAGED / "media_engine" / "comfy_shot_engine"
    if ev_root.exists():
        for p in sorted(ev_root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ev_root)
            if "reservations" in rel.parts and "closed" not in rel.parts:
                continue
            if ".tmp" in p.name:
                continue
            dst = EVID / "raw" / "engine_state" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            out["engine_state"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                        "bytes": dst.stat().st_size})
    rr_root = MANAGED / "shot_render"
    if rr_root.exists():
        for p in sorted(rr_root.rglob("*")):
            if not p.is_file() or ".tmp" in p.name:
                continue
            rel = p.relative_to(rr_root)
            dst = EVID / "raw" / "renders" / "shot_render" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            out["renders"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                   "bytes": dst.stat().st_size})
    so_root = COMFY_BASE / "output"
    if so_root.exists():
        for p in sorted(so_root.rglob("*.mp4")):
            rel = p.relative_to(so_root)
            dst = EVID / "raw" / "renders" / "server_output" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            out["server_outputs"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                          "bytes": dst.stat().st_size})
    dbdump: dict = {}
    factory = _session_factory()
    with factory() as s:
        for t in ("job", "job_step", "s10_full_apply_run", "s10_full_apply_chunk",
                  "s10_full_apply_publication", "qc_item", "s12_export_run", "s12_export_chunk"):
            try:
                rows = [dict(r) for r in s.execute(_text(f"SELECT * FROM {t}")).mappings().all()]
            except Exception as exc:  # noqa: BLE001
                rows = [{"error": f"{type(exc).__name__}:{exc}"}]
            dbdump[t] = rows
    (RAW / "db_harvest.json").write_text(json.dumps(dbdump, indent=1, ensure_ascii=False, default=str),
                                         encoding="utf-8")
    out["db_tables"] = {k: len(v) for k, v in dbdump.items()}
    save_state({"engine_harvest": {"engine_state": len(out["engine_state"]),
                                   "renders": len(out["renders"]),
                                   "server_outputs": len(out["server_outputs"]),
                                   "db_tables": out["db_tables"]}})
    (RAW / "engine_harvest.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                             encoding="utf-8")
    print("ENGINE_HARVEST", len(out["engine_state"]), len(out["renders"]),
          len(out["server_outputs"]), out["db_tables"], flush=True)
    return 0


# ── phase: harvest (copy the SHORT-root runtime back into the evidence root) ─
def phase_harvest() -> int:
    out = {"at": now(), "files": [], "skipped_live": []}
    dst_root = EVID / "raw" / "runtime_harvest"
    for sub in ("media_engine/comfy_shot_engine", "shot_render", "shot_render_cache",
                "s10_full_apply"):
        src_root = MANAGED / sub
        if not src_root.exists():
            continue
        for p in sorted(src_root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(MANAGED)
            if "reservations" in rel.parts or ".tmp" in p.name:
                continue
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(p, dst)
            except PermissionError:
                out["skipped_live"].append(rel.as_posix())
                continue
            out["files"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                 "bytes": dst.stat().st_size})
    if DB.is_file():
        dst = dst_root / "data" / DB.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DB, dst)
        out["files"].append({"rel": "data/" + DB.name, "sha256": sha_file(dst),
                             "bytes": dst.stat().st_size})
    (RAW / "harvest_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    save_state({"harvest_summary": {"files": len(out["files"]), "skipped_live": out["skipped_live"]}})
    print("HARVEST", len(out["files"]), "files; skipped_live", len(out["skipped_live"]), flush=True)
    return 0


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"prep": phase_prep, "app": phase_app, "journey": phase_journey,
          "monitor": phase_monitor, "qc": phase_qc, "export": phase_export,
          "verify": phase_verify, "report": phase_report, "shutdown": phase_shutdown,
          "harvest": phase_harvest,
          "harvest_engine": phase_harvest_engine,
          "engine": phase_engine, "engine3": phase_engine3}.get(phase)
    if fn is None:
        print(f"phase {phase!r} not implemented yet", flush=True)
        raise SystemExit(2)
    raise SystemExit(fn())
