#!/usr/bin/env python
"""Usage ledger builder (Manager tool) - reads the real API-call receipt lines.

Source of truth: C:/Users/Admin/AppData/Local/hermes/logs/agent.log
Only lines matching 'API call #N: model=... provider=... in=... out=... cache=X/Y'

usage: usage_ledger.py [session_id ...]
Appends one row per (session, api_call) seen; dedupes by (session, call_no).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z")
LEDGER = RUN_ROOT / "ledgers" / "usage-ledger.jsonl"
# v1 (session,call_no) dedupe was WRONG for resumed sessions: numbering restarts at
# #1 each round, so the second round's rows were silently dropped. v2 is the fix.
LEDGER_V2 = RUN_ROOT / "ledgers" / "usage-ledger.v2.jsonl"
LOG = Path("C:/Users/Admin/AppData/Local/hermes/logs/agent.log")

LINE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \w+ \[(?P<sid>[0-9_a-z]+)\] "
    r"agent\.conversation_loop: API call #(?P<n>\d+): model=(?P<model>\S+) provider=(?P<prov>\S+) "
    r"in=(?P<in>\d+) out=(?P<out>\d+) total=(?P<total>\d+) latency=(?P<lat>[\d.]+)s"
    r"(?: cache=(?P<cache>\d+)/(?P<cachebase>\d+) \((?P<pct>\d+)%\))?"
)
TASK_BY_SESSION = {
    "20260929_041810_bc7c61": "MF-DEMO-E2E-R5",
    "20260928_121441_bdf0d8": "MF-END-11",
    "20260928_181430_0350c2": "MF-END-22",
    "20260929_161633_4008ff": "MANAGER",
}


def load_seen() -> set:
    seen = set()
    for path in (LEDGER, LEDGER_V2):
        if not path.exists():
            continue
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                seen.add(_key(d["session"], d["api_call_no"], d["model"], d["at_local"]))
            except Exception:  # noqa: BLE001
                continue
    return seen


def _key(sid: str, n: int, model: str, at_local: str) -> tuple:
    """A resumed session RESTARTS call numbering at #1, so (session, n) alone
    collides across rounds and silently drops the new round's rows. Include the
    model and the request timestamp (unique per logged request)."""
    return (sid, n, model, at_local)


def main() -> int:
    sids = set(sys.argv[1:]) or None
    seen = load_seen()
    added = 0
    LEDGER_V2.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_V2.open("a", encoding="utf-8") as out:
        for raw in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LINE.match(raw)
            if not m:
                continue
            sid = m.group("sid")
            if sids and sid not in sids:
                continue
            n = int(m.group("n"))
            if (sid, n, m.group("model"), m.group("ts")) in seen:
                continue
            tin = int(m.group("in"))
            cache = int(m.group("cache")) if m.group("cache") else 0
            row = {
                "at_local": m.group("ts"),
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "task": TASK_BY_SESSION.get(sid, "UNMAPPED"),
                "session": sid,
                "model": m.group("model"),
                "provider": m.group("prov"),
                "api_call_no": n,
                "input_total": tin,
                "cache_read": cache,
                "uncached_input": tin - cache,
                "output": int(m.group("out")),
                "latency_s": float(m.group("lat")),
                "cache_pct": (round(100.0 * cache / tin, 2) if tin else None),
                "cost": "unknown",
                "cache_low_and_big": bool(tin > 80000 and (cache / tin if tin else 0) < 0.5),
            }
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            seen.add((sid, n, m.group("model"), m.group("ts")))
            added += 1
    print(f"rows_added={added} ledger={LEDGER_V2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
