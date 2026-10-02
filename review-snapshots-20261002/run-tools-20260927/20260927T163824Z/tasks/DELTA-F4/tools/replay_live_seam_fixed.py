"""Replay the FIXED key resolution against the RECORD of the failed live run.

Reads the persisted job manifest + render authority of run
90319e92-af21-4951-b030-5da5ed6d4cb1 (MF-DEMO-E2E-R2 harvest DB) and runs the
FIXED production helpers exactly as the worker group path does:

    mapping_by_layer = _authoritative_mapping_by_layer(authority)
    asset_key        = _replacement_asset_key(mapping_by_layer[lid], lid)
    assert asset_key in manifest["replacement_assets"]

No file IO for assets (the live managed root is gone); this proves the KEY
resolution only — the disk-level resolution is proven by the focused tests.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F4")
sys.path.insert(0, str(WT))

from app.workflow import s10_full_apply_jobs as jobs  # noqa: E402

DB = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2/raw/runtime_harvest/data/motionforge.db"
)
RUN = "90319e92-af21-4951-b030-5da5ed6d4cb1"
JOB = "5295be80-36cd-4cb7-82c4-c5afb8f43e55"


def main() -> int:
    con = sqlite3.connect(str(DB))
    manifest = json.loads(
        con.execute("SELECT input_manifest_json FROM job WHERE id=?", (JOB,)).fetchone()[0]
    )
    authority = manifest["render_authority"]
    members = json.loads(
        con.execute(
            "SELECT member_layer_ids_json FROM s10_full_apply_chunk "
            "WHERE run_id=? AND chunk_index=0",
            (RUN,),
        ).fetchone()[0]
    )
    mapping_by_layer = jobs._authoritative_mapping_by_layer(authority)
    assets = manifest.get("replacement_assets") or {}
    rows = []
    for lid in members:
        entry = mapping_by_layer[lid]
        key = jobs._replacement_asset_key(entry, lid)
        rows.append(
            {
                "layer_id": lid,
                "mapping_role_id": entry.get("role_id"),
                "resolved_asset_key": key,
                "present_in_manifest": key in assets,
                "asset_sha256": (assets.get(key) or {}).get("sha256"),
            }
        )
    ok = all(r["present_in_manifest"] for r in rows)
    for r in rows:
        print(
            f"{r['layer_id']} -> role {r['mapping_role_id']} -> key {r['resolved_asset_key']} "
            f"present={r['present_in_manifest']} sha={(r['asset_sha256'] or '')[:12]}"
        )
    print("ALL_MEMBERS_RESOLVE:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
