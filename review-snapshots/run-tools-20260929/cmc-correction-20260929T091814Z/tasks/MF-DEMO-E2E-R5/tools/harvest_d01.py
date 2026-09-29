"""D0.1 — Harvest the aborted R5 run (no GPU, no writes outside evidence).

Reads the isolated runtime Temp/mfr5 + the old evidence copy and writes a
complete harvest: DB table counts, run/chunk/publication rows, ComfyUI history
for the 3 executions, artifact listing with sha256/size, ffprobe of the
publication, and the explicit list of MISSING steps (QC/readiness/export/report)
so an exit_code=0 wrapper can never be read as completion.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
OLD = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
DB = MFR5 / "data" / "motionforge.db"
MANAGED = MFR5 / "artifacts"
COMFY_URL = "http://127.0.0.1:8375"
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


out: dict = {"at": now(), "db": str(DB), "db_exists": DB.is_file()}

TABLES = ("job", "job_attempt", "s10_full_apply_run", "s10_full_apply_chunk",
          "s10_full_apply_publication", "qc_item", "s12_export_run", "artifact",
          "artifact_owner", "occurrence_segment", "scene")

if DB.is_file():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    counts, rows = {}, {}
    for t in TABLES:
        try:
            counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            counts[t] = f"ERR {exc}"
    out["counts"] = counts
    for t in ("job", "s10_full_apply_run", "s10_full_apply_chunk",
              "s10_full_apply_publication"):
        try:
            rows[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t}").fetchall()]
        except Exception as exc:  # noqa: BLE001
            rows[t] = [{"error": str(exc)}]
    out["rows"] = rows
    out["jobs"] = [{k: str(r.get(k))[:70] for k in ("id", "job_type", "state", "owner_type",
                                                    "owner_id", "started_at", "finished_at")}
                   for r in rows.get("job", [])]
    out["chunks"] = [{k: r.get(k) for k in ("id", "chunk_index", "shot_id", "state", "verified",
                                           "core_start_frame", "core_end_frame", "attempt")}
                     for r in rows.get("s10_full_apply_chunk", [])]
    con.close()
else:
    out["counts"] = {}

# ── ComfyUI history (3 executions) ──────────────────────────────────────────
hist_out: dict = {}
try:
    with urllib.request.urlopen(COMFY_URL + "/history", timeout=30) as r:
        hist = json.loads(r.read().decode("utf-8"))
    for pid, rec in hist.items():
        st = (rec.get("status") or {})
        outputs = rec.get("outputs") or {}
        files = []
        for nid, o in outputs.items():
            for it in (o.get("images") or []) + (o.get("gifs") or []) + (o.get("videos") or []):
                files.append({"node": nid, "filename": it.get("filename"),
                              "subfolder": it.get("subfolder"), "type": it.get("type")})
        hist_out[pid] = {"status": st.get("status_str"), "completed": st.get("completed"),
                         "messages": [m[0] for m in (st.get("messages") or [])][:12],
                         "files": files}
    out["comfy_history"] = hist_out
except Exception as exc:  # noqa: BLE001
    out["comfy_history"] = {"error": f"{type(exc).__name__}: {exc}"}

# ── artifact listing + sha256 of the publication ───────────────────────────
arts = []
if MANAGED.exists():
    for p in sorted(MANAGED.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".mp4", ".png", ".json"):
            try:
                arts.append({"rel": p.relative_to(MANAGED).as_posix(),
                             "bytes": p.stat().st_size, "sha256": sha_file(p)})
            except PermissionError:
                arts.append({"rel": p.relative_to(MANAGED).as_posix(), "locked": True})
out["artifacts"] = arts

# ── ffprobe of the publication (video-only proof) ───────────────────────────
pub_rel = None
for r in out.get("rows", {}).get("s10_full_apply_publication", []):
    if isinstance(r, dict) and r.get("artifact_id"):
        pub_rel = r["artifact_id"]
pub_path = None
for a in arts:
    if pub_rel and str(a.get("rel", "")).endswith(".mp4") and "stitch" in str(a.get("rel")):
        pub_path = MANAGED / a["rel"]
out["publication_artifact_id"] = pub_rel
out["publication_path"] = str(pub_path) if pub_path else None
if pub_path and pub_path.is_file():
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                         "-of", "json", str(pub_path)], capture_output=True, text=True)
    try:
        doc = json.loads(pr.stdout)
        out["publication_probe"] = {
            "streams": [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height",
                                               "nb_frames", "duration", "sample_rate", "channels")}
                        for s in doc.get("streams", [])],
            "duration": (doc.get("format") or {}).get("duration"),
            "sha256": sha_file(pub_path), "bytes": pub_path.stat().st_size,
        }
    except Exception as exc:  # noqa: BLE001
        out["publication_probe"] = {"error": str(exc), "rc": pr.returncode,
                                    "stderr": pr.stderr[-200:]}

# ── explicit missing-step list (exit 0 must not read as done) ───────────────
st = json.loads((OLD / "raw" / "state.json").read_text(encoding="utf-8"))
missing = []
if not st.get("qc"):
    missing += ["qc_submit", "qc_readiness"]
if not st.get("export"):
    missing += ["export_submit", "export_run", "export_media"]
if not (OLD / "REPORT.md").is_file():
    missing.append("REPORT.md")
if not (OLD / "FINDINGS.md").is_file():
    missing.append("FINDINGS.md")
if not st.get("shutdown"):
    missing.append("shutdown/harvest")
out["state_keys_old"] = sorted(st.keys())
out["aborted_by_quota"] = True
out["missing_steps"] = missing
out["completed_steps"] = ["app_launch", "comfy_launch", "journey_to_full_apply",
                          "full_apply_run_completed_3_of_3_chunks"]
out["wrapper_exit_code_note"] = ("wrapper ghi exit_code=0 nhưng log kết thúc bằng "
                                 "GoUsageLimitError → exit 0 KHÔNG phải hoàn tất")

(RAW / "harvest_d01.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str),
                                      encoding="utf-8")
print(json.dumps({k: out[k] for k in ("db_exists", "counts", "missing_steps",
                                      "aborted_by_quota")}, indent=1, ensure_ascii=False))
print("raw/harvest_d01.json written")
