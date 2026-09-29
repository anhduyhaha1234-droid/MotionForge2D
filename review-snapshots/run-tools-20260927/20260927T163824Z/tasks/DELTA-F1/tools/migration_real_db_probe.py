"""DELTA-F1 final gate probe: upgrade a REAL pre-fix demo database (22 cols,
with real chunk rows) through the new migration chain and measure.

Read-only w.r.t. the demo DB (works on a copy in %TEMP%).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F1")
SRC = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-DEMO-E2E/app-runtime/data/motionforge.db"
)
TMP = Path("C:/Users/Admin/AppData/Local/Temp/delta_f1_migprobe/demo_copy.db")
OUT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F1/raw/migration_on_real_demo_db.json"
)


def cols(db: Path) -> list[str]:
    con = sqlite3.connect(str(db))
    try:
        return [r[1] for r in con.execute("PRAGMA table_info(s10_full_apply_chunk)").fetchall()]
    finally:
        con.close()


def main() -> int:
    TMP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, TMP)
    before = cols(TMP)
    rev_before = None
    con = sqlite3.connect(str(TMP))
    try:
        rev_before = con.execute("SELECT version_num FROM alembic_version").fetchall()
    finally:
        con.close()

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"db_url=sqlite:///{TMP.as_posix()}", "upgrade", "head"],
        cwd=str(WT),
        capture_output=True,
        text=True,
    )
    after = cols(TMP)
    con = sqlite3.connect(str(TMP))
    try:
        rev_after = con.execute("SELECT version_num FROM alembic_version").fetchall()
        nulls = con.execute(
            "SELECT COUNT(*), SUM(member_layer_ids_json IS NULL) FROM s10_full_apply_chunk"
        ).fetchone()
    finally:
        con.close()

    payload = {
        "src_db": str(SRC),
        "copy": str(TMP),
        "cols_before": len(before),
        "has_member_col_before": "member_layer_ids_json" in before,
        "alembic_before": rev_before,
        "upgrade_rc": proc.returncode,
        "upgrade_tail": proc.stderr.strip().split("\n")[-3:],
        "cols_after": len(after),
        "has_member_col_after": "member_layer_ids_json" in after,
        "alembic_after": rev_after,
        "chunk_rows": int(nulls[0] or 0),
        "rows_with_null_members": int(nulls[1] or 0),
        "verdict": "PASS" if (
            proc.returncode == 0
            and "member_layer_ids_json" not in before
            and "member_layer_ids_json" in after
            and rev_after == [("b3c4d5e6f7a8",)]
        ) else "FAIL",
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=1, sort_keys=True))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
