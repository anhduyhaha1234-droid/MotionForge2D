#!/usr/bin/env python
"""Delivery ledger append (Manager) — full-prefix snapshot + append-only.

usage: append_ledger_delivery.py <events.json>
Snapshots the WHOLE current prefix (not just 36 rows) to RUN/manager/snapshots/,
appends events, re-verifies the prefix byte-for-byte.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
              "mf-core-tool-delivery-20260924/20260924T1557Z/manager/dispatch-ledger.jsonl")
RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    events_path = Path(sys.argv[1])
    events = json.loads(events_path.read_text(encoding="utf-8"))
    if not isinstance(events, list) or not events:
        print("REFUSED: events must be a non-empty list")
        return 2

    raw = LEDGER.read_bytes()
    lines = raw.splitlines(keepends=True)
    prefix = b"".join(lines)
    snap = RUN / "manager" / "snapshots" / "dispatch-ledger.whole-prefix.before-delivery.jsonl"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_bytes(prefix)
    snap_ok = sha(snap.read_bytes()) == sha(prefix)

    now = datetime.now(timezone.utc).isoformat()
    payload = []
    for ev in events:
        ev.setdefault("at_utc", now)
        payload.append(json.dumps(ev, ensure_ascii=False, sort_keys=True))
    blob = ("\n".join(payload) + "\n").encode("utf-8")

    with LEDGER.open("ab") as f:
        f.write(blob)

    after = LEDGER.read_bytes()
    after_prefix = b"".join(after.splitlines(keepends=True)[:len(lines)])
    try:
        after_prefix.decode("utf-8")
    except Exception:
        pass
    report = {
        "ledger": LEDGER.as_posix(),
        "prefix_sha256_before": sha(prefix),
        "prefix_sha256_after": sha(after_prefix),
        "prefix_immutable": sha(prefix) == sha(after_prefix),
        "snapshot": snap.as_posix(),
        "snapshot_verified": snap_ok,
        "rows_before": len(lines), "rows_after": after.count(b"\n"),
        "appended_rows": len(events),
        "bytes_before": len(prefix), "bytes_after": len(after),
        "appended_sha256": sha(blob),
    }
    out = events_path.parent / "ledger_append_delivery_result.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["prefix_immutable"] and report["snapshot_verified"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
