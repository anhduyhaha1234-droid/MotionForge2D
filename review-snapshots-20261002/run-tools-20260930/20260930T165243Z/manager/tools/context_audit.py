#!/usr/bin/env python
"""M1-01 T001b: context-health audit of the MF-END-10 owner session.

Read-only. Evidence for rules §4 (context health) — a single weak signal is not
enough to abandon an owner; this prints the measured counters only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time

DB = r"C:\Users\Admin\AppData\Local\hermes\state.db"
OWNER = "20260928_181955_a6d89a"

PATTERNS = {
    "iteration_exit": r"maximum (?:tool-calling )?iterations|max_turns|out of turns|"
                      r"iteration limit|turn limit|reached the limit",
    "quota": r"GoUsageLimitError|usage limit|quota|rate limit|429",
    "conn_error": r"API call failed after \d+ retries|502|503|504|connect timeout|"
                  r"socket reset|disconnected",
    "unsafe_write": r"write_file|whole-file|overwrite|truncat|destroyed|removed .* lines",
    "no_bytes": r"no (?:usable )?bytes|nothing written|empty diff",
}


def main() -> int:
    uri = "file:///" + DB.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(messages)")]
    rows = list(cur.execute(
        "SELECT id, role, content, timestamp FROM messages "
        "WHERE session_id=? ORDER BY id", (OWNER,)))
    con.close()

    roles: dict[str, int] = {}
    hits: dict[str, list[int]] = {k: [] for k in PATTERNS}
    first_ts = rows[0][3] if rows else None
    last_ts = rows[-1][3] if rows else None
    total_chars = 0
    for mid, role, content, ts in rows:
        roles[role] = roles.get(role, 0) + 1
        text = content or ""
        total_chars += len(text)
        low = text.lower()
        for name, rx in PATTERNS.items():
            if re.search(rx, low, re.IGNORECASE):
                hits[name].append(mid)

    out = {
        "session": OWNER,
        "messages_columns": cols,
        "messages": len(rows),
        "roles": roles,
        "message_chars_total": total_chars,
        "first_message_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(first_ts)) if first_ts else None,
        "last_message_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_ts)) if last_ts else None,
        "idle_hours": round((time.time() - last_ts) / 3600.0, 2) if last_ts else None,
        "pattern_hits": {k: {"count": len(v), "first_ids": v[:5]} for k, v in hits.items()},
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
