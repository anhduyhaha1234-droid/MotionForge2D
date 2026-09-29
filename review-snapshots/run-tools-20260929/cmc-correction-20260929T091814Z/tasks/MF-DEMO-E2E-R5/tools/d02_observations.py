"""D0.2 — Produce the missing MF-END-21 rendered-observations artifact.

Finding (measured): `publish_rendered_observations` / `observe_rendered_output`
have NO production caller (no route, no job, no workflow) — grep app/ returns
only the module itself. The S12 export gate therefore blocks every export with
EXPORT_BLOCKED_OUTPUT_EVIDENCE.

This script calls the product's OWN public service API on the REAL publication
pixels of the aborted R5 lineage (no fabricated mask: the engine computes the
observation from the decoded output frame's own pixels). Disclosed: the engine
is the module's documented CI-pixel source (provenance FIXTURE), so
`production=False` — recorded in the payload.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")

os.environ["MOTIONFORGE_ROOT"] = str(MFR5)
sys.path.insert(0, str(WT))

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.services import rendered_observations as ro  # noqa: E402
from app.services.qc_evidence import sources as src  # noqa: E402

st = json.loads((RUN / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
factory = create_session_factory(create_engine_for_path(MFR5 / "data" / "motionforge.db"))
MANAGED = MFR5 / "artifacts"

print("engine:", ro.LevelComponentMaskSource.__name__, flush=True)
out: dict = {"at": "d02", "video_item_id": vid, "workspace_id": WS}
with factory() as s:
    scope = src.load_scope(s, workspace_id=WS, project_id=pid, video_item_id=vid)
    print("scope:", scope.video_item_id, scope.source_generation, flush=True)
    engine = ro.LevelComponentMaskSource()
    try:
        artifact = ro.observe_rendered_output(
            s, MANAGED, scope, engine=engine, production=False, strict=True,
        )
        out["build"] = {"ok": True, "digest": getattr(artifact, "digest", None),
                        "output": getattr(getattr(artifact, "output", None), "sha256", None)}
        rel = f"s10_full_apply_observations/{vid}/rendered_observations.json"
        pub = ro.publish_rendered_observations(
            s, MANAGED, workspace_id=WS, video_item_id=vid,
            relative_path=rel, artifact=artifact,
        )
        s.commit()
        out["publish"] = pub
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out["build"] = {"ok": False, "type": type(exc).__name__,
                        "code": str(getattr(exc, "code", "")),
                        "message": str(exc)[:700]}

(RUN / "raw" / "d02_observations.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, default=str)[:1500], flush=True)
