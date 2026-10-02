#!/usr/bin/env python
"""Dispatch-ledger reconciliation (Manager tool).

Builds a reconciled, deterministic view of the append-only dispatch ledger and
proves receipt-file coverage. Detects the two failure modes measured before:
  * duplicate rows for the same (task, round) dispatch
  * a dispatch with no receipt file on disk

usage: reconcile_dispatch_ledger.py [--emit]   (--emit writes the reconciled jsonl)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z")
LEDGER = RUN / "ledgers" / "dispatch-ledger.jsonl"
OUT = RUN / "ledgers" / "dispatch-ledger.reconciled.jsonl"
NOTE = RUN / "manager" / "DISPATCH_RECONCILIATION.md"


def main() -> int:
    rows = [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    dispatches = [r for r in rows if r.get("action") == "dispatch"]
    exits = [r for r in rows if r.get("action") == "exit"]

    # pair by (task, receipt) - the receipt path is minted per dispatch
    pairs = []
    for d in dispatches:
        m = [e for e in exits if e.get("receipt") == d.get("receipt")]
        pairs.append({
            "task_id": d.get("task_id"),
            "utc_start": d.get("utc_start") or d.get("at_utc"),
            "resume_session_requested": d.get("resume_session_requested"),
            "model": d.get("model"),
            "cwd": d.get("cwd"),
            "receipt": d.get("receipt"),
            "log": d.get("log"),
            "packet_sha256": d.get("packet_sha256"),
            "packet_bytes": d.get("packet_bytes"),
            "utc_end": m[0].get("at_utc") if m else None,
            "exit_code": m[0].get("exit_code") if m else None,
            "outcome": "EXITED" if m else "STILL_RUNNING_OR_KILLED",
            "receipt_exists": bool(d.get("receipt") and Path(d["receipt"]).is_file()),
        })

    dupes = {k: v for k, v in Counter((p["task_id"], p["receipt"]) for p in pairs).items() if v > 1}
    missing = [p for p in pairs if not p["receipt_exists"]]
    running = [p for p in pairs if p["outcome"] != "EXITED"]

    report = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "ledger": LEDGER.as_posix(),
        "rows_total": len(rows),
        "dispatches": len(dispatches),
        "exits": len(exits),
        "receipt_files_on_disk": len(list((RUN / "manager" / "receipts").glob("*.json"))),
        "duplicate_dispatch_rows": dupes,
        "dispatches_missing_receipt": [p["task_id"] for p in missing],
        "not_yet_exited": [{"task_id": p["task_id"], "started": p["utc_start"]} for p in running],
    }
    if "--emit" in sys.argv:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(json.dumps(p, ensure_ascii=False, sort_keys=True) for p in pairs) + "\n",
                       encoding="utf-8")
        NOTE.write_text(
            "# Dispatch ledger reconciliation\n\n"
            f"Generated {report['at_utc']}.\n\n"
            "| metric | value |\n|---|---|\n"
            f"| rows in append-only ledger | {report['rows_total']} |\n"
            f"| dispatch rows | {report['dispatches']} |\n"
            f"| exit rows | {report['exits']} |\n"
            f"| receipt files on disk | {report['receipt_files_on_disk']} |\n"
            f"| duplicate dispatch rows | {len(dupes)} |\n"
            f"| dispatches missing a receipt | {len(missing)} |\n"
            f"| dispatches not yet exited | {len(running)} |\n\n"
            "A `dispatch` row exists for the FAILED first attempt (MSYS path bug) which was re-dispatched\n"
            "under the SAME receipt name; that first attempt's receipt was overwritten by the successful\n"
            "retry. It is listed here rather than deleted: the round was re-dispatched, not re-run.\n\n"
            + "\n".join(
                f"- `{p['task_id']}` start={p['utc_start']} exit={p['exit_code']} "
                f"resume={p['resume_session_requested']} receipt_on_disk={p['receipt_exists']}"
                for p in pairs
            ) + "\n",
            encoding="utf-8")
        print(f"emitted {OUT} and {NOTE}")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
