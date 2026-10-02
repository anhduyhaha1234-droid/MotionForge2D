#!/usr/bin/env python
"""Manager heartbeat (append-only) - one row per invocation, no LLM calls.

usage: heartbeat.py "note text"
Reads: launcher receipts, lane log size+mtime, app health, Comfy queue, R5 DB job table.
Writes: RUN/manager/HEARTBEAT.jsonl  (append)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z")
DB = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/data/motionforge.db")
OUT = RUN / "manager" / "HEARTBEAT.jsonl"


def probe(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def lane(fn: str) -> dict:
    log = RUN / "manager" / "logs" / f"{fn}.log"
    rec = RUN / "manager" / "receipts" / f"{fn}.json"
    d: dict = {"log_bytes": log.stat().st_size if log.exists() else None}
    if log.exists():
        age = (time.time() - log.stat().st_mtime) / 60.0
        d["log_last_write_ago_min"] = round(age, 2)
        d["log_last_write"] = datetime.fromtimestamp(log.stat().st_mtime).strftime("%H:%M:%S")
    if rec.exists():
        r = json.loads(rec.read_text(encoding="utf-8"))
        d["exit_code"] = r.get("exit_code")
        d["model"] = r.get("model")
        d["resume_requested"] = r.get("resume_session_requested")
    return d


def db_jobs() -> dict:
    if not DB.exists():
        return {"exists": False}
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    jobs = [list(r) for r in con.execute("SELECT job_type, state, COUNT(*) FROM job GROUP BY job_type, state")]
    s12 = list(con.execute("SELECT COUNT(*) FROM s12_export_run"))[0][0]
    try:
        qc = list(con.execute("SELECT COUNT(*) FROM qc_item"))[0][0]
    except Exception:  # noqa: BLE001
        qc = None
    con.close()
    return {"jobs": jobs, "s12_export_run_rows": s12, "qc_item_rows": qc}


def main() -> int:
    row = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": sys.argv[1] if len(sys.argv) > 1 else "",
        "manager_session": "20260929_161633_4008ff",
        "app_health": probe("http://127.0.0.1:8035/health"),
        "comfy_queue": probe("http://127.0.0.1:8375/queue"),
        "lanes": {k: lane(k) for k in ("MF-DEMO-E2E-R5", "MF-END-11")},
        "r5_db": db_jobs(),
        "active_streams": 3,
        "stream_cap": 3,
        "slots": "Manager + D0(GPU) + C11(CPU); C22/C15 waiting",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(row, ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
