"""Read-only probe #2: full QC compose failures on the LIVE R4 runtime.

Runs compose_check_run_args against the R4 DB + managed root (MOTIONFORGE_ROOT
must be Temp/mfr4) and measures the real inter-frame deltas of the publication
around the scene boundary at frame 120 (what cut_drift judges).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R4")
MFR4 = Path("C:/Users/Admin/AppData/Local/Temp/mfr4")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")

assert os.environ.get("MOTIONFORGE_ROOT", "").lower().replace("\\", "/").endswith("temp/mfr4"), \
    "MOTIONFORGE_ROOT must point at the live R4 runtime"
sys.path.insert(0, str(WT))

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.workflow.qc_checks_handler import compose_check_run_args  # noqa: E402

st = json.loads((EVID / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
DB = MFR4 / "data" / "motionforge.db"
out: dict = {"project_id": pid, "video_id": vid, "db": str(DB), "compose": {}}

factory = create_session_factory(create_engine_for_path(DB))
with factory() as s:
    try:
        args = compose_check_run_args(s, workspace_id=WS, project_id=pid,
                                      video_item_id=vid, scope="full")
        out["compose"] = {"ok": True, "detectors": sorted(args)}
        if "cut_drift" in args:
            cd = args["cut_drift"]
            out["compose"]["cut_drift_keys"] = sorted(cd)
    except Exception as exc:  # noqa: BLE001
        details = getattr(exc, "details", None) or {}
        failed = details.get("failed_detectors") or {}
        out["compose"] = {"ok": False, "type": type(exc).__name__,
                          "code": str(getattr(exc, "code", "")),
                          "message": str(exc)[:600],
                          "failed_detectors": {k: {kk: str(vv)[:300] for kk, vv in (v or {}).items()}
                                               for k, v in failed.items()}}
    # publication geometry + real inter-frame deltas around boundary 120
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        from sqlalchemy import text as _t  # noqa: PLC0415

        row = s.execute(_t(
            "SELECT a.relative_path FROM s10_full_apply_publication p "
            "JOIN artifact a ON a.id = p.artifact_id ORDER BY p.created_at DESC LIMIT 1"
        )).mappings().first()
        pub = MFR4 / "artifacts" / str(row["relative_path"])
        cap = cv2.VideoCapture(str(pub))
        frames = []
        prev = None
        deltas = []
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
            if prev is not None and 100 <= idx <= 140:
                deltas.append({"pair": [idx - 1, idx],
                               "mad": round(float(np.mean(np.abs(gray - prev))), 4)})
            prev = gray
            idx += 1
        cap.release()
        out["publication"] = {"path": str(row["relative_path"]), "frames": idx,
                              "deltas_100_140": deltas}
    except Exception as exc:  # noqa: BLE001
        out["publication"] = {"error": f"{type(exc).__name__}: {exc}"}

(EVID / "raw" / "probe_qc_compose_r4.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False)[:4000])
