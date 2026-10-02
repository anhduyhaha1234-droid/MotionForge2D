#!/usr/bin/env python
"""Local lane monitor (Manager tool) - no LLM calls.

Reads only local state: launcher receipts, lane log tails/size, app/Comfy listeners,
Comfy queue+history, and the R5 DB job table. Appends one heartbeat row per run.

usage: monitor_lanes.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUN_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z")
HEARTBEAT = RUN_ROOT / "ledgers" / "heartbeat.jsonl"
R5_DB = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/data")
COMFY = "http://127.0.0.1:8375"
APP = "http://127.0.0.1:8035/health"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(url: str, timeout: int = 6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - probe only
        return {"error": f"{type(exc).__name__}: {exc}"}


def comfy_queue():
    return {"queue": http_json(f"{COMFY}/queue"), "running": http_json(f"{COMFY}/prompt")}


def app_health():
    return http_json(APP)


def db_jobs():
    out = {}
    if not R5_DB.exists():
        return {"db_root": str(R5_DB), "exists": False}
    cands = sorted(R5_DB.glob("*.db")) + sorted(R5_DB.glob("*.sqlite*"))
    out["db_root"] = str(R5_DB)
    out["exists"] = True
    for db in cands:
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            rows = list(con.execute("SELECT job_type, state, COUNT(*) FROM job GROUP BY job_type, state"))
            out.setdefault("jobs", {})[db.name] = [list(r) for r in rows]
            try:
                rows2 = list(con.execute("SELECT COUNT(*) FROM s12_export_run"))
                out.setdefault("s12_export_run", {})[db.name] = rows2[0][0]
            except Exception:  # noqa: BLE001
                pass
            con.close()
        except Exception as exc:  # noqa: BLE001
            out.setdefault("errors", []).append(f"{db.name}: {type(exc).__name__}: {exc}")
    return out


def log_state(log: Path | None) -> dict:
    if log is None or str(log) in ("", "."):
        return {"exists": False, "reason": "receipt has no log path yet (still running)"}
    if not log.exists():
        return {"exists": False}
    data = log.read_bytes()
    tail = data[-3000:].decode("utf-8", "replace")
    interesting = [ln.strip() for ln in tail.splitlines()
                   if any(k in ln for k in ("API failed", "HTTP 5", "HTTP 4", "GoUsageLimit",
                                            "Resume this session", "Session:", "Messages:",
                                            "Duration:", "Error", "error"))]
    return {"exists": True, "bytes": len(data), "tail_markers": interesting[-8:]}


def main() -> int:
    row = {"at_utc": utc(), "app_health": app_health(), "comfy": comfy_queue(), "db": db_jobs(),
           "lanes": {}}
    for receipt in sorted((RUN_ROOT / "manager" / "receipts").glob("*.json")):
        try:
            r = json.loads(receipt.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            row["lanes"][receipt.stem] = {"receipt_error": str(exc)}
            continue
        log = Path(r["log"]) if r.get("log") else (RUN_ROOT / "manager" / "logs" / f"{r.get('task_id')}.log")
        row["lanes"][receipt.stem] = {
            "task_id": r.get("task_id"), "model": r.get("model"),
            "resume_requested": r.get("resume_session_requested"),
            "exit_code": r.get("exit_code"), "utc_start": r.get("utc_start"),
            "log": log_state(log) if log else {"exists": False},
        }
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    with HEARTBEAT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(row, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
