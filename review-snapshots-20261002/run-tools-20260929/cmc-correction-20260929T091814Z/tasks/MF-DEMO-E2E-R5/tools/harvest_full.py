"""D0.1 (cont.) — full harvest: DB, engine evidence, artifacts, commands log,
heartbeat, and the QC detector matrix of the completed run.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
MANAGED = MFR5 / "artifacts"
DB = MFR5 / "data" / "motionforge.db"
RAW = RUN / "raw"
RAW.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


out: dict = {"at": now()}

# ── DB harvest (counts + key rows) ─────────────────────────────────────────
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
TABLES = ("job", "job_attempt", "job_step", "s10_full_apply_run", "s10_full_apply_chunk",
          "s10_full_apply_publication", "qc_item", "s12_export_run", "s12_export_chunk",
          "artifact", "artifact_owner", "occurrence_segment", "scene", "object_role",
          "character", "character_asset", "reskin_config")
db: dict = {}
for t in TABLES:
    try:
        db[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t}").fetchall()]
    except Exception as exc:  # noqa: BLE001
        db[t] = [{"error": str(exc)}]
out["db_counts"] = {k: len(v) for k, v in db.items()}
out["jobs"] = [{k: str(r.get(k)) for k in ("job_type", "state", "id")} for r in db["job"]]
out["qc_items"] = [{k: str(r.get(k))[:80] for k in ("reason_code", "severity", "status")}
                   for r in db["qc_item"]]
out["export_runs"] = [{k: str(r.get(k))[:80] for k in ("id", "status", "profile_id")}
                      for r in db["s12_export_run"]]
con.close()
(RAW / "db_harvest.json").write_text(json.dumps(db, indent=1, ensure_ascii=False, default=str),
                                     encoding="utf-8")

# ── engine evidence + receipts (harvest from the isolated runtime) ─────────
ev_root = MANAGED / "media_engine" / "comfy_shot_engine"
harvest = {"engine_state": [], "renders": [], "server_outputs": []}
if ev_root.exists():
    for p in sorted(ev_root.rglob("*")):
        if not p.is_file() or ".tmp" in p.name:
            continue
        rel = p.relative_to(ev_root)
        if "reservations" in rel.parts and "closed" not in rel.parts:
            continue
        dst = RAW / "engine_state" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        harvest["engine_state"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                        "bytes": dst.stat().st_size})
rr = MANAGED / "shot_render"
if rr.exists():
    for p in sorted(rr.rglob("*")):
        if not p.is_file() or ".tmp" in p.name:
            continue
        rel = p.relative_to(rr)
        dst = RAW / "renders" / "shot_render" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        harvest["renders"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                   "bytes": dst.stat().st_size})
CB = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R5/comfy-base")
if (CB / "output").exists():
    for p in sorted((CB / "output").rglob("*.mp4")):
        rel = p.relative_to(CB / "output")
        dst = RAW / "renders" / "server_output" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        harvest["server_outputs"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                          "bytes": dst.stat().st_size})
out["harvest"] = {k: len(v) for k, v in harvest.items()}
(RAW / "engine_harvest.json").write_text(json.dumps(harvest, indent=1, ensure_ascii=False),
                                         encoding="utf-8")

# ── ComfyUI history ────────────────────────────────────────────────────────
try:
    with urllib.request.urlopen("http://127.0.0.1:8375/history", timeout=20) as r:
        hist = json.loads(r.read().decode("utf-8"))
    out["comfy_history"] = {pid: {"status": (rec.get("status") or {}).get("status_str"),
                                  "completed": (rec.get("status") or {}).get("completed")}
                            for pid, rec in hist.items()}
    (RAW / "comfy_history.json").write_text(json.dumps(hist, indent=1, ensure_ascii=False)[:200000],
                                            encoding="utf-8")
except Exception as exc:  # noqa: BLE001
    out["comfy_history"] = {"error": f"{type(exc).__name__}: {exc}"}

# ── publication + export candidate ffprobe ─────────────────────────────────
h1 = json.loads((RAW / "harvest_d01.json").read_text(encoding="utf-8"))
pub = Path(h1["publication_path"]) if h1.get("publication_path") else None
stat: dict = {}
for label, p in (("publication", pub),):
    if p and p.is_file():
        pr = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                             "-of", "json", str(p)], capture_output=True, text=True)
        stat[label] = {"path": str(p), "sha256": sha_file(p), "bytes": p.stat().st_size,
                       "probe": json.loads(pr.stdout)}
out["probe"] = stat
(RAW / "ffprobe_publication.json").write_text(json.dumps(stat, indent=1, ensure_ascii=False),
                                              encoding="utf-8")

# ── heartbeat + commands rows ──────────────────────────────────────────────
hb = RUN / "HEARTBEAT.jsonl"
with open(hb, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "at": now(), "task": "MF-DEMO-E2E-R5", "phase": "D0 correction",
        "progress": "harvest done; QC 202 + readiness ready + observations published; "
                    "export submit 202 but run FAILED on av_policy (48-sample phase offset)",
        "latest_log": "raw/d05_repro2_assemble.json, raw/d05_repro3_audio.json",
        "blocker": "av_policy phase-offset + 3 unit content mismatches (masks/inputs)",
        "next": "write FINDINGS/REPORT, guard, final gate",
        "slots": "GPU 1 job/lan; comfy pid 35184 port 8375; app pid 4632 port 8035",
    }, ensure_ascii=False) + "\n")

cmds = RAW / "commands.jsonl"
rows_added = 0
existing = cmds.read_text(encoding="utf-8").count("\n") if cmds.is_file() else 0
with open(cmds, "a", encoding="utf-8") as fh:
    for step, detail in (
        ("d01_harvest", "harvest_d01.json"),
        ("d02_observations_attempt1", "d02_observations.json (RENDERED_OBSERVATIONS_REFERENCE_INVALID)"),
        ("d04_real_reference_plus_observations", "d04_d02_observations.json (published)"),
        ("export_submit_409_output_evidence", "export_receipt.json"),
        ("export_submit_500_profile", "export_receipt.json"),
        ("export_submit_202_run_7da2cb5f", "export_receipt.json"),
        ("export_run_failed_av_policy", "d05_repro2_assemble.json"),
        ("av_policy_repro_self_compare", "d05_repro3_audio.json"),
        ("time_map_and_units", "units_evidence.json"),
        ("full_harvest", "db_harvest.json/engine_harvest.json"),
    ):
        fh.write(json.dumps({"ts": now(), "kind": "step", "step": step, "evidence": detail},
                            ensure_ascii=False) + "\n")
        rows_added += 1
out["commands_rows_before"] = existing
out["commands_rows_added"] = rows_added

(RAW / "harvest_full.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str),
                                       encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False, default=str)[:2400])
