#!/usr/bin/env python
"""Bounded R27 progress monitor (Manager-owned, READ-ONLY).

Polls the three lane sessions + evidence roots every ~8 minutes for a bounded
number of iterations, appends one line per poll to monitor_phaseb_c.log and writes a
heartbeat JSON. It NEVER dispatches, kills, or writes anything outside the
manager/ directory. Exits on its own after the iteration budget.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sqlite3
import sys
import time
from pathlib import Path

DB = "C:/Users/Admin/AppData/Local/hermes/state.db"
RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")
LOG = RUN / "manager" / "monitor_phaseb_c.log"
LANES = {"MF-END-13": "20260928_134838_000ad7", "MF-END-04": "20260928_140316_f42754"}
ITERATIONS = 6
SLEEP_S = 480

PORTS = ["8301", "8304", "8310", "8188", "8300"]


def poll() -> dict:
    con = sqlite3.connect(f"file:{Path(DB).as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out = {}
    for lane, sid in LANES.items():
        rows = list(cur.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id=?", (sid,)))
        last = list(cur.execute(
            "SELECT timestamp, role, substr(content,1,90) AS head FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT 1", (sid,)))
        sess = list(cur.execute(
            "SELECT api_call_count, end_reason FROM sessions WHERE id=?", (sid,)))
        ev = RUN / lane
        ev_files = len([p for p in ev.rglob("*") if p.is_file()]) if ev.exists() else 0
        out[lane] = {
            "messages": rows[0]["n"] if rows else 0,
            "api": sess[0]["api_call_count"] if sess else None,
            "end": sess[0]["end_reason"] if sess else None,
            "last_ts": last[0]["timestamp"] if last else None,
            "age_s": round(time.time() - float(last[0]["timestamp"]), 1) if last else None,
            "ev_files": ev_files,
        }
    con.close()
    return out


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"=== monitor start {dt.datetime.now(dt.timezone.utc).isoformat()} "
                f"({ITERATIONS} iters x {SLEEP_S}s) ===\n")
        prev = None
        for i in range(ITERATIONS):
            time.sleep(SLEEP_S)
            snap = poll()
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%SZ")
            verdicts = []
            for lane, d in snap.items():
                delta = ""
                if prev:
                    delta = f" (+{d['messages'] - prev[lane]['messages']}msg)"
                stall = ""
                if d["age_s"] is not None and d["age_s"] > 8 * 60 and d["end"] is None:
                    stall = " STALL_AUDIT>8min"
                verdicts.append(f"{lane}: {d['messages']}msg{delta} api={d['api']} "
                                f"ev={d['ev_files']} age={d['age_s']}s "
                                f"end={d['end']}{stall}")
            line = f"[{stamp}] iter {i + 1}/{ITERATIONS} | " + " | ".join(verdicts)
            f.write(line + "\n")
            f.flush()
            print(line, flush=True)
            (RUN / "manager" / "monitor_last.json").write_text(
                json.dumps({"stamp": stamp, "iter": i + 1, "snap": snap}, indent=2),
                encoding="utf-8")
            prev = snap
        f.write(f"=== monitor stop {dt.datetime.now(dt.timezone.utc).isoformat()} ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
