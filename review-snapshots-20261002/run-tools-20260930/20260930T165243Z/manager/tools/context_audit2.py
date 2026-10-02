#!/usr/bin/env python
"""M1-01 T001c: refined context-health audit (assistant-role only).

The first pass (context_audit.py) scanned raw message CONTENT including tool
RESULTS, so documentation text ("never overwrite", "502 retry policy", rules
prose) produced phantom hits. This pass scans only assistant-role messages and
classifies real tool usage from the tool_calls column, which is the actual
event log.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time

DB = r"C:\Users\Admin\AppData\Local\hermes\state.db"
OWNER = "20260928_181955_a6d89a"

EVENT = {
    "iteration_cap": r"maximum .{0,20}iteration|max[_ ]turns|out of turns|"
                     r"iteration limit|turn limit|reached the limit|hit the cap",
    "quota": r"GoUsageLimitError|usage limit reached|quota exceeded|rate limit exceeded",
    "conn_error": r"API call failed after \d+ retries|connect timeout|socket reset|"
                  r"connection reset|502 Bad Gateway|503 Service",
    "destructive_write": r"\brmtree\b|\bgit reset --hard\b|\bgit clean\b|"
                         r"\bgit checkout --\b|shutil\.move|os\.remove",
}


def main() -> int:
    uri = "file:///" + DB.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    cur = con.cursor()
    rows = list(cur.execute(
        "SELECT id, role, content, tool_calls, tool_name, finish_reason, timestamp "
        "FROM messages WHERE session_id=? ORDER BY id", (OWNER,)))
    con.close()

    tools: dict[str, int] = {}
    files_touched: dict[str, int] = {}
    finish: dict[str, int] = {}
    hits: dict[str, list[int]] = {k: [] for k in EVENT}
    assistant_text = 0

    for mid, role, content, tool_calls, tool_name, fr, _ts in rows:
        if role == "assistant":
            text = content or ""
            assistant_text += len(text)
            for name, rx in EVENT.items():
                if re.search(rx, text, re.IGNORECASE):
                    hits[name].append(mid)
        if role == "assistant" and tool_calls:
            try:
                calls = json.loads(tool_calls)
            except (TypeError, ValueError):
                calls = []
            for call in calls if isinstance(calls, list) else []:
                fn = (call.get("function") or {}).get("name") or "?"
                tools[fn] = tools.get(fn, 0) + 1
                args = (call.get("function") or {}).get("arguments") or ""
                for m in re.finditer(
                        r"[\w./\\()\[\]-]+\.(?:py|ts|tsx|json|md)", str(args)):
                    key = m.group(0).replace("\\", "/").split("/")[-1]
                    files_touched[key] = files_touched.get(key, 0) + 1
        if tool_name == "terminal":
            pass
        if fr:
            finish[fr] = finish.get(fr, 0) + 1

    out = {
        "session": OWNER,
        "messages": len(rows),
        "assistant_text_chars": assistant_text,
        "tool_call_totals": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
        "finish_reason_histogram": finish,
        "assistant_only_event_hits": {k: {"count": len(v), "ids": v[:5]}
                                     for k, v in hits.items()},
        "distinct_filenames_in_tool_args": len(files_touched),
        "top_filenames": sorted(files_touched.items(), key=lambda kv: -kv[1])[:15],
        "note": ("tool RESULTS were excluded on purpose: the first pass matched "
                 "documentation prose inside skill/rule files and produced phantom "
                 "hits. A keyword scan over tool output is NOT evidence of an "
                 "incident happening."),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
