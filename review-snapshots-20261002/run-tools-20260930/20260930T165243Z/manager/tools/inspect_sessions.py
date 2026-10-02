#!/usr/bin/env python
"""M1-01 T001 preflight: read-only session liveness + context audit.

Opens the Hermes state DB with mode=ro + query_only=ON. Never mutates.
Prints JSON to stdout; caller tees it into the RUN evidence root.
"""
import json
import os
import sqlite3
import sys
import time

DB = r"C:\Users\Admin\AppData\Local\hermes\state.db"

WATCH = [
    "20260929_161633_4008ff",  # OLD manager (must NOT be resumed)
    "20260928_181955_a6d89a",  # MF-END-10 owner (target of resume)
    "20260928_140316_f42754",  # MF-END-04 owner (blocked)
    "20260926_180042_1990da",  # historical S12-LC3-INT
]


def main() -> int:
    out = {
        "db": DB,
        "db_size_bytes": os.path.getsize(DB),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "access": "mode=ro; query_only=ON",
    }
    uri = "file:///" + DB.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    cur = con.cursor()

    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    out["tables"] = tables

    sess_cols = [r[1] for r in cur.execute("PRAGMA table_info(sessions)")]
    out["sessions_columns"] = sess_cols

    # ---- watched sessions -------------------------------------------------
    rows = []
    for sid in WATCH:
        r = list(cur.execute(
            "SELECT id, model, started_at, ended_at, message_count, "
            "tool_call_count, api_call_count, cwd, git_branch, title, "
            "archived, pinned, profile_name "
            "FROM sessions WHERE id=?", (sid,)))
        if not r:
            rows.append({"id": sid, "found": False})
            continue
        c = dict(zip(
            ["id", "model", "started_at", "ended_at", "message_count",
             "tool_call_count", "api_call_count", "cwd", "git_branch",
             "title", "archived", "pinned", "profile_name"], r[0]))
        c["found"] = True
        if c.get("started_at"):
            c["started_utc"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(c["started_at"]))
        # latest message timestamp for this session (bounded, indexed on session)
        try:
            m = list(cur.execute(
                "SELECT MAX(timestamp), COUNT(*) FROM messages "
                "WHERE session_id=?", (sid,)))
            if m and m[0][0] is not None:
                c["last_message_utc"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(m[0][0]))
                c["last_message_epoch"] = m[0][0]
            c["message_rows"] = m[0][1] if m else None
        except sqlite3.Error as e:
            c["message_query_error"] = str(e)
        rows.append(c)
    out["watched_sessions"] = rows

    # ---- any OTHER session with activity in the last 3 hours --------------
    cutoff = time.time() - 3 * 3600
    recent = []
    for r in cur.execute(
            "SELECT id, model, started_at, ended_at, message_count, "
            "api_call_count, cwd, title FROM sessions "
            "WHERE started_at > ? ORDER BY started_at DESC LIMIT 40",
            (cutoff,)):
        recent.append({
            "id": r[0], "model": r[1],
            "started_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(r[2])) if r[2] else None,
            "ended_at": r[3], "message_count": r[4],
            "api_call_count": r[5], "cwd": r[6], "title": r[7],
        })
    out["sessions_started_last_3h"] = recent

    # ---- top-level counts -------------------------------------------------
    out["total_sessions"] = list(cur.execute(
        "SELECT COUNT(*) FROM sessions"))[0][0]
    con.close()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
