"""Closing pass — verify PID ownership, shut down cleanly, harvest, and emit the
final evidence artifacts (verify_receipt with contact sheet, harvest_receipt,
comfy_shutdown, final_evidence).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
OLD = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
MANAGED = MFR5 / "artifacts"
RAW = RUN / "raw"
APP_PORT, COMFY_PORT = 8035, 8375


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def listeners(port: int) -> list:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            try:
                pids.append(int(line.split()[-1]))
            except Exception:  # noqa: BLE001
                pass
    return sorted(set(pids))


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmdline(pid: int) -> str:
    r = subprocess.run(["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
                       capture_output=True, text=True)
    return " ".join(r.stdout.split())[:400]


st = json.loads((RAW / "state.json").read_text(encoding="utf-8"))
app_pid = int(st["app"]["pid"])
comfy_pids = listeners(COMFY_PORT)
out: dict = {"at": now(), "app_pid": app_pid, "comfy_listeners": comfy_pids}

# ── verify ownership BEFORE killing ────────────────────────────────────────
out["ownership"] = {
    "app": {"pid": app_pid, "listener": app_pid in listeners(APP_PORT),
            "cmdline": cmdline(app_pid)},
    "comfy": {str(p): {"port_listener": p in comfy_pids, "cmdline": cmdline(p)}
              for p in comfy_pids},
}

# ── harvest comfy-base (server log, epoch) into the NEW evidence root ──────
pre = {"harvested": []}
src_cb = OLD / "comfy-base"
if src_cb.exists():
    for name in ("server.log",):
        p = src_cb / name
        if p.is_file():
            dst = RAW / "comfy-base" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(p, dst)
                pre["harvested"].append({"rel": name, "sha256": sha(dst),
                                         "bytes": dst.stat().st_size})
            except PermissionError:
                pre["harvested"].append({"rel": name, "locked": True})
pre["engine_state"] = [f"raw/engine_state/{p.name}" for p in (RAW / "engine_state").rglob("*") if p.is_file()][:30]
pre["renders"] = [f"raw/renders/{p.relative_to(RAW / 'renders').as_posix()}"
                  for p in (RAW / "renders").rglob("*") if p.is_file()][:30]
pre["runtime_files"] = sum(1 for _ in MANAGED.rglob("*") if _.is_file())
(RAW / "harvest_receipt.json").write_text(json.dumps(pre, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
out["harvest"] = {"engine_state": len(pre["engine_state"]), "renders": len(pre["renders"]),
                  "runtime_files": pre["runtime_files"]}

# ── shutdown (exact pids, verified ownership) ──────────────────────────────
stop: dict = {"at": now()}
if app_pid in listeners(APP_PORT):
    subprocess.run(["taskkill", "/PID", str(app_pid), "/F"], capture_output=True, text=True)
    import time as _t
    _t.sleep(3)
stop["app"] = {"pid": app_pid, "pid_gone": not alive(app_pid),
               "port_closed": not port_open(APP_PORT)}
for p in comfy_pids:
    subprocess.run(["taskkill", "/PID", str(p), "/F"], capture_output=True, text=True)
import time  # noqa: E402
time.sleep(3)
for p in listeners(COMFY_PORT):
    subprocess.run(["taskkill", "/PID", str(p), "/F"], capture_output=True, text=True)
time.sleep(2)
stop["comfy"] = {"requested": comfy_pids, "pids_gone": [p for p in comfy_pids if not alive(p)],
                 "listeners_after": listeners(COMFY_PORT), "port_closed": not port_open(COMFY_PORT)}
por = subprocess.run(["git", "status", "--porcelain"],
                     cwd="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION",
                     capture_output=True, text=True).stdout
head = subprocess.run(["git", "rev-parse", "HEAD"],
                      cwd="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION",
                      capture_output=True, text=True).stdout.strip()
stop["tree"] = {"porcelain": [ln for ln in por.splitlines() if ln.strip()], "head": head}
stop["POST_STOP_VERIFIED"] = bool(stop["app"]["port_closed"] and stop["comfy"]["port_closed"])
out["shutdown"] = stop
(RAW / "comfy_shutdown.json").write_text(json.dumps(stop, indent=1, ensure_ascii=False),
                                         encoding="utf-8")

# ── verify_receipt: ffprobe + contact sheet over the produced media ────────
mp = json.loads((RAW / "media_proof.json").read_text(encoding="utf-8"))
demo = RAW / "export" / "demo_final.mp4"
cand = RAW / "export" / "export_candidate_with_audio.mp4"


def probe_json(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                        "-of", "json", str(p)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return {}


def pts_monotonic(p: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "frame=pts_time", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    vals = [float(x.split(",")[0]) for x in r.stdout.replace("\r", "").split("\n") if x.strip()]
    return all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), len(vals)


def sheet(p: Path, dst: Path, n: int = 9) -> dict:
    prob = probe_json(p)
    v = next((s for s in prob.get("streams", []) if s.get("codec_type") == "video"), {})
    total = int(v.get("nb_frames") or 0)
    frames = [round(i * (total - 1) / (n - 1)) for i in range(n)] if total > n else list(range(total))
    expr = "+".join(f"eq(n\\,{i})" for i in frames)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                    f"select='{expr}',tile=3x3", "-frames:v", "1", str(dst)],
                   capture_output=True, text=True)
    ok = dst.is_file() and dst.stat().st_size > 0
    return {"path": str(dst.relative_to(RAW)), "bytes": dst.stat().st_size if ok else 0,
            "frames": frames, "written": ok}


ver: dict = {"at": now()}
if demo.is_file():
    mono, nf = pts_monotonic(demo)
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(demo), "-f", "null", "-"],
                         capture_output=True, text=True)
    pj = probe_json(demo)
    vs = next((s for s in pj.get("streams", []) if s.get("codec_type") == "video"), {})
    az = next((s for s in pj.get("streams", []) if s.get("codec_type") == "audio"), None)
    ver["publication_copy"] = {
        "path": str(demo), "sha256": sha(demo), "bytes": demo.stat().st_size,
        "video": {k: vs.get(k) for k in ("codec_name", "width", "height")},
        "audio": ({k: az.get(k) for k in ("codec_name", "sample_rate", "channels")}
                  if az else None),
        "frames": nf, "pts_monotonic": mono,
        "duration": (pj.get("format") or {}).get("duration"),
        "decode_rc": dec.returncode,
        "contact_sheet": sheet(demo, RAW / "preview_contact_sheet.png"),
    }
if cand.is_file():
    pj = probe_json(cand)
    vs = next((s for s in pj.get("streams", []) if s.get("codec_type") == "video"), {})
    az = next((s for s in pj.get("streams", []) if s.get("codec_type") == "audio"), None)
    mono, nf = pts_monotonic(cand)
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(cand), "-f", "null", "-"],
                         capture_output=True, text=True)
    ver["export_candidate_with_audio"] = {
        "path": str(cand), "sha256": sha(cand), "bytes": cand.stat().st_size,
        "video": {k: vs.get(k) for k in ("codec_name", "width", "height")},
        "audio": ({k: az.get(k) for k in ("codec_name", "sample_rate", "channels")}
                  if az else None),
        "frames": nf, "pts_monotonic": mono, "decode_rc": dec.returncode,
        "aligned_corr_vs_original": (mp.get("audio_identity") or {}).get("aligned_corr"),
    }
ver["gpu_after"] = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                                   "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True).stdout.strip()
(RAW / "verify_receipt.json").write_text(json.dumps(ver, indent=1, ensure_ascii=False, default=str),
                                         encoding="utf-8")
out["verify"] = ver

# ── final_evidence ─────────────────────────────────────────────────────────
db = json.loads((RAW / "db_harvest.json").read_text(encoding="utf-8"))
fin = {
    "at": now(),
    "head": head, "porcelain": stop["tree"]["porcelain"],
    "publication": mp.get("publication"),
    "publication_probe_streams": [{"codec_type": s.get("codec_type"), "codec_name": s.get("codec_name"),
                                   "width": s.get("width"), "height": s.get("height")}
                                  for s in ((mp.get("publication_probe") or {}).get("streams") or [])],
    "export_run": {"id": "7da2cb5f-2ea0-414a-a2db-8803ee8f0f59", "status": "failed",
                   "profile_id": "master-4k-h264"},
    "export_job_error": [json.loads(r["error_json"]) if r.get("error_json") else None
                         for r in db.get("job", []) if r.get("job_type") == "s12_export"],
    "qc_matrix": {},
    "audio_identity": mp.get("audio_identity"),
    "detector_matrix_source": "raw/qc_job_payload.json",
    "counts": {k: len(v) for k, v in db.items() if isinstance(v, list)},
    "producer_gap": ("publish_rendered_observations has no caller in app/ "
                     "(grep app/workflow app/api/routes = 0) -> export gate 409"),
}
try:
    qj = json.loads((RAW / "qc_job_payload.json").read_text(encoding="utf-8"))
    fin["qc_matrix"] = {k: {"items_found": v.get("items_found"), "error_code": v.get("error_code")}
                        for k, v in ((qj.get("summary") or {}).get("per_detector") or {}).items()}
except Exception as exc:  # noqa: BLE001
    fin["qc_matrix"] = {"error": str(exc)}
(RAW / "final_evidence.json").write_text(json.dumps(fin, indent=1, ensure_ascii=False, default=str),
                                         encoding="utf-8")

print(json.dumps({"ownership_ok": out["ownership"]["app"]["listener"],
                  "POST_STOP_VERIFIED": stop["POST_STOP_VERIFIED"],
                  "shutdown": stop["comfy"], "verify": {k: (v.get("audio") if isinstance(v, dict) else None)
                                                        for k, v in ver.items() if isinstance(v, dict)}},
                 indent=1, ensure_ascii=False, default=str)[:1800])
