"""One-off fix: re-insert the seeded reskin_configs with UUID ids.

The public CAS pin route is /api/v2/reskin-configs/{config_id:uuid}; the seed
(harness-style, mirroring MF-END-19) used short prefixed ids for reskin_config
which the uuid path converter cannot match (404).  This script deletes the old
rows and re-inserts byte-identical configs under uuid4 ids, then patches
raw/state.json so the journey continues.  Only reskin_config rows change; the
produced StructuralLockManifest does not reference them.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
DB = EVID / "app-runtime" / "data" / "motionforge.db"
STATE_P = EVID / "raw" / "state.json"
sys.path.insert(0, str(WT))

from sqlalchemy import text  # noqa: E402

from app.persistence import create_engine_for_path, create_session_factory  # noqa: E402

factory = create_session_factory(create_engine_for_path(DB))
st = json.loads(STATE_P.read_text(encoding="utf-8"))
rc_map = dict(st["seed"]["reskin_configs"])
new_map = {}
changes = []
with factory() as s:
    for role, old_id in rc_map.items():
        row = s.execute(text("SELECT * FROM reskin_config WHERE id=:r"), {"r": old_id}).mappings().first()
        assert row is not None, f"missing reskin_config {old_id}"
        new_id = str(uuid.uuid4())
        cols = [c for c in row.keys() if c != "id"]
        col_sql = ",".join(cols)
        val_sql = ",".join(f":{c}" for c in cols)
        params = {c: row[c] for c in cols}
        s.execute(text(f"DELETE FROM reskin_config WHERE id=:r"), {"r": old_id})
        s.execute(text(f"INSERT INTO reskin_config(id,{col_sql}) VALUES (:new_id,{val_sql})"),
                  {"new_id": new_id, **params})
        new_map[role] = new_id
        changes.append({"role": role, "old": old_id, "new": new_id})
    s.commit()
st["seed"]["reskin_configs"] = new_map
st.setdefault("fixes", []).append({"what": "reskin_config ids -> uuid4 for the CAS pin route",
                                   "at": "2026-09-28T16:05Z", "changes": changes})
STATE_P.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(changes, indent=1))
