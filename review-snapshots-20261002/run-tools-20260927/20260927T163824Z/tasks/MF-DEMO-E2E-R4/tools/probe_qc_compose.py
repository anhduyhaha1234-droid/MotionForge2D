"""Read-only probe: predict the QC submit outcome for the R4 chain.

Runs the SAME compose_check_run_args entry point as POST /qc-check-runs against
the PRESERVED R3 runtime (DB + managed root under Temp/mfr3) using #7 code.

Read-only: opens the R3 sqlite DB, runs the compose select/byte-verification
path, and probes the publication for an audio stream.  Writes ONLY
raw/probe_qc_compose.json under the R4 evidence root.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R4")
R3EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")
MFR3 = Path("C:/Users/Admin/AppData/Local/Temp/mfr3")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")

assert os.environ.get("MOTIONFORGE_ROOT", "").lower().replace("\\", "/").endswith("temp/mfr3"), \
    "MOTIONFORGE_ROOT must point at the preserved R3 runtime"
sys.path.insert(0, str(WT))

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.workflow.qc_checks_handler import compose_check_run_args  # noqa: E402

st = json.loads((R3EV / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
DB = MFR3 / "data" / "motionforge.db"
out: dict = {"project_id": pid, "video_id": vid, "db": str(DB),
             "db_bytes": DB.stat().st_size if DB.is_file() else None, "at": "probe"}

factory = create_session_factory(create_engine_for_path(DB))
with factory() as s:
    try:
        args = compose_check_run_args(s, workspace_id=WS, project_id=pid,
                                      video_item_id=vid, scope="full")
        out["compose"] = {"ok": True, "detectors": sorted(args)}
    except Exception as exc:  # noqa: BLE001 — the typed refusal IS the measurement
        details = getattr(exc, "details", None) or {}
        failed = details.get("failed_detectors") or {}
        out["compose"] = {"ok": False, "type": type(exc).__name__,
                          "code": str(getattr(exc, "code", "")),
                          "message": str(exc)[:900],
                          "failed_detectors": {k: {kk: str(vv)[:200] for kk, vv in (v or {}).items()}
                                               for k, v in failed.items()}}
    try:
        from app.persistence.readiness import compute_project_readiness  # noqa: PLC0415
        r = compute_project_readiness(s, workspace_id=WS, project_id=pid)
        out["readiness"] = {"status": str(r.status),
                            "blockers": [str(b) for b in (r.blockers or [])][:10]}
    except Exception as exc:  # noqa: BLE001
        out["readiness"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        from sqlalchemy import text as _t  # noqa: PLC0415
        row = s.execute(_t(
            "SELECT a.id, a.relative_path, a.sha256 FROM s10_full_apply_publication p "
            "JOIN artifact a ON a.id = p.artifact_id ORDER BY p.created_at DESC LIMIT 1"
        )).mappings().first()
        if row:
            pub = Path(MFR3) / "artifacts" / str(row["relative_path"])
            from app.services.original_audio_remux import probe_original_audio  # noqa: PLC0415
            try:
                pr = probe_original_audio(pub)
                out["publication_audio_probe"] = {
                    "publication": str(row["relative_path"]), "exists": pub.is_file(),
                    "present": bool(pr.present), "codec": pr.codec, "detail": str(pr.detail)[:200]}
            except Exception as exc:  # noqa: BLE001
                out["publication_audio_probe"] = {"error": f"{type(exc).__name__}: {exc}",
                                                  "exists": pub.is_file()}
    except Exception as exc:  # noqa: BLE001
        out["publication_audio_probe"] = {"error": f"{type(exc).__name__}: {exc}"}

(EVID / "raw").mkdir(parents=True, exist_ok=True)
(EVID / "raw" / "probe_qc_compose.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False))
