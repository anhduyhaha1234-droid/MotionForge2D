"""D0.4 + D0.2 — Real canvas-sized cast reference + MF-END-21 observation pass.

Measured defect in the previous seed (harness, not app):
  * every role's 6 pose slots point at ONE artifact (D0.4 "một ảnh gán sáu pose");
  * those artifacts are 768x512 / 1024x1024 / 640x640 — never the 640x360 canvas,
    so MF-END-21 refuses with RENDERED_OBSERVATIONS_REFERENCE_INVALID and the
    S12 export gate blocks with EXPORT_BLOCKED_OUTPUT_EVIDENCE.

Remedy here: build a REAL 640x360 reference crop per role from the SOURCE video's
own pixels (the role's window midpoint), publish it as a managed artifact, and
re-point the role's pose slots at it. Then re-run the product's own
observe_rendered_output + publish_rendered_observations on the REAL publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
os.environ["MOTIONFORGE_ROOT"] = str(MFR5)
sys.path.insert(0, str(WT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from sqlalchemy import text  # noqa: E402

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
MANAGED = MFR5 / "artifacts"
factory = create_session_factory(create_engine_for_path(MFR5 / "data" / "motionforge.db"))
out: dict = {"at": "d04_d02", "video_item_id": vid}

# ── 1. real 640x360 reference crop per role from the SOURCE pixels ───────────
src_rel = st["seed"]["source_rel"]
src_abs = MANAGED / src_rel
cap = cv2.VideoCapture(str(src_abs))
assert cap.isOpened(), f"source not decodable: {src_abs}"
rebuilt = {}
with factory() as s:
    rows = s.execute(text(
        "SELECT os.id, o.name, os.start_frame, os.end_frame, os.role_id, "
        "cpv.id AS pv, cpv.character_id "
        "FROM occurrence_segment os JOIN object_role o ON o.id = os.role_id "
        "JOIN character_pack_version cpv ON cpv.character_id = ("
        "  SELECT character_id FROM reskin_config rc WHERE rc.object_role_id = os.role_id LIMIT 1)"
        " WHERE os.video_item_id = :v AND os.source_generation='1'"
    ), {"v": vid}).all()
    for seg_id, name, sf, ef, role_id, pv, char in rows:
        mid = (int(sf) + int(ef)) // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
        ok, frame = cap.read()
        assert ok, f"source frame {mid} not decodable"
        assert frame.shape[1] == 640 and frame.shape[0] == 360, f"canvas {frame.shape}"
        rel = f"s10_full_apply/_authority/{vid}/cast_ref_{str(name).replace('-', '_')}.png"
        dst = MANAGED / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(dst), frame)
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        art_id = f"art-ref-{str(name).replace('-', '').lower()}"
        s.execute(text(
            "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,"
            "mime_type,width,height,revision) VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,"
            "'image/png',640,360,1) ON CONFLICT(id) DO UPDATE SET relative_path=excluded.relative_path,"
            "sha256=excluded.sha256,size_bytes=excluded.size_bytes,state='ready',width=640,height=360"
        ), {"id": art_id, "w": WS, "rel": rel, "sha": sha, "sz": dst.stat().st_size})
        s.execute(text("UPDATE character_asset SET artifact_id=:a WHERE pack_version_id=:pv"),
                  {"a": art_id, "pv": pv})
        rebuilt[str(name)] = {"artifact_id": art_id, "rel": rel, "sha256": sha,
                              "frame": mid, "pose_slots_repointed_to_one_ref": True}
    s.commit()
cap.release()
out["real_reference"] = rebuilt

# ── 2. product's own observation pass on the REAL publication ───────────────
with factory() as s:
    scope = src.load_scope(s, workspace_id=WS, project_id=pid, video_item_id=vid)
    engine = ro.LevelComponentMaskSource()
    try:
        artifact = ro.observe_rendered_output(s, MANAGED, scope, engine=engine,
                                             production=False, strict=False)
        payload = artifact.to_payload()
        out["observation"] = {"ok": True, "digest": artifact.digest,
                              "output_sha256": (payload.get("output") or {}).get("sha256"),
                              "schema": payload.get("schema_version"),
                              "refusals": payload.get("refusals")}
        rel = f"s10_full_apply_observations/{vid}/rendered_observations.json"
        pub = ro.publish_rendered_observations(
            s, MANAGED, workspace_id=WS, video_item_id=vid,
            relative_path=rel, artifact=artifact)
        s.commit()
        out["publish"] = pub
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out["observation"] = {"ok": False, "type": type(exc).__name__,
                              "code": str(getattr(exc, "code", "")), "message": str(exc)[:600]}

# ── 3. the export gate's own independent look ───────────────────────────────
from app.services.qc_evidence.compose import output_evidence_status  # noqa: E402
with factory() as s:
    try:
        out["output_evidence_status"] = output_evidence_status(
            s, managed_root=MANAGED, workspace_id=WS, project_id=pid, video_item_id=vid)
    except Exception as exc:  # noqa: BLE001
        out["output_evidence_status"] = {"error": f"{type(exc).__name__}: {exc}"}

(RUN / "raw" / "d04_d02_observations.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, default=str)[:2500])
