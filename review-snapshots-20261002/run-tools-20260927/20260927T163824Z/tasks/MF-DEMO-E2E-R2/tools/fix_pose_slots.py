"""One-off fix: complete every seeded character pack with CORE_POSE_SLOTS.

The CAS pin route validates pack completeness (front/three_quarter/side/back/
sitting/walking).  The harness seed (MF-END-19 style) created a single 'base'
asset; this adds the six core slots, each reusing the pack's existing asset
artifact.  Idempotent: only missing (pack, slot) pairs are inserted.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
DB = EVID / "app-runtime" / "data" / "motionforge.db"
STATE_P = EVID / "raw" / "state.json"
import sys

sys.path.insert(0, str(WT))

from sqlalchemy import text  # noqa: E402

from app.persistence import create_engine_for_path, create_session_factory  # noqa: E402
from app.persistence.models import CORE_POSE_SLOTS  # noqa: E402

factory = create_session_factory(create_engine_for_path(DB))
st = json.loads(STATE_P.read_text(encoding="utf-8"))
added = []
with factory() as s:
    for role, pv in st["seed"]["pack_versions"].items():
        row = s.execute(text("SELECT id, artifact_id, pose_slot FROM character_asset WHERE pack_version_id=:p ORDER BY rowid LIMIT 1"),
                        {"p": pv}).mappings().first()
        assert row is not None, f"pack {pv} has no asset"
        art = str(row["artifact_id"])
        present = {str(r[0]) for r in s.execute(text("SELECT pose_slot FROM character_asset WHERE pack_version_id=:p"),
                                                {"p": pv})}
        for slot in CORE_POSE_SLOTS:
            if slot in present:
                continue
            s.execute(text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id)"
                           " VALUES (:id,:pv,'default',:slot,:aid)"),
                      {"id": f"ca-{uuid.uuid4().hex[:6]}", "pv": pv, "slot": slot, "aid": art})
            added.append({"role": role, "pack": pv, "slot": slot})
    s.commit()
st.setdefault("fixes", []).append({"what": "character packs completed with CORE_POSE_SLOTS",
                                   "at": "2026-09-28T16:10Z", "added": added})
STATE_P.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
print("added rows:", len(added))
