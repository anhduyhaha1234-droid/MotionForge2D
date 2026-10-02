"""Read-only probe #4: the S12 export authority legs on the LIVE R4 runtime.

Resolves the export context + authority + readiness + gate exactly like
POST /s12-exports/submit does, and records every check with its pass/fail
so the report can show WHICH leg refuses.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R4")
MFR4 = Path("C:/Users/Admin/AppData/Local/Temp/mfr4")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
assert os.environ.get("MOTIONFORGE_ROOT", "").lower().replace("\\", "/").endswith("temp/mfr4")
sys.path.insert(0, str(WT))

# register the full detector band the way the running app does (module-level
# register_detector calls); without this the probe's registry is empty and the
# export gate reads as an artificial QcRegistryError.
import app.services.qc_checks.audio_missing  # noqa: E402,F401
import app.services.qc_checks.av_sync_drift  # noqa: E402,F401
import app.services.qc_checks.contact_break  # noqa: E402,F401
import app.services.qc_checks.cut_drift  # noqa: E402,F401
import app.services.qc_checks.edge_halo  # noqa: E402,F401
import app.services.qc_checks.identity_drift  # noqa: E402,F401
import app.services.qc_checks.silhouette_clipping  # noqa: E402,F401
import app.services.qc_checks.temporal_flicker  # noqa: E402,F401
import app.services.qc_checks.trajectory_drift  # noqa: E402,F401
import app.services.qc_checks.z_order_error  # noqa: E402,F401

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)

st = json.loads((EVID / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
DB = MFR4 / "data" / "motionforge.db"
out: dict = {"at": "probe4"}

factory = create_session_factory(create_engine_for_path(DB))
with factory() as s:
    from app.services.s12_export.authority import (  # noqa: PLC0415
        resolve_export_authority,
        resolve_export_context,
    )

    ctx = resolve_export_context(s, workspace_id=WS, project_id=pid, video_item_id=vid)
    out["context"] = {"reasons": list(ctx.reasons), "checkpoint_id": ctx.checkpoint_id,
                      "manifest_id": ctx.manifest_id, "frame_count": ctx.frame_count,
                      "chunk_config": ctx.chunk_config}
    auth = resolve_export_authority(
        s, workspace_id=WS, project_id=pid, video_item_id=vid,
        checkpoint_id=str(ctx.checkpoint_id), checkpoint_hash=str(ctx.checkpoint_hash),
        checkpoint_revision=int(ctx.checkpoint_revision), manifest_id=str(ctx.manifest_id),
        manifest_hash=str(ctx.manifest_hash), manifest_generation=str(ctx.manifest_generation),
    )
    out["authority"] = {"resolved": bool(auth.resolved),
                        "failed_reasons": list(auth.failed_reasons or []),
                        "checks": [{"name": c.name, "passed": bool(c.passed), "reason": c.reason,
                                    "detail": str(c.detail)[:160]} for c in auth.checks]}
    from app.persistence.readiness import compute_project_readiness  # noqa: PLC0415
    r = compute_project_readiness(s, workspace_id=WS, project_id=pid)
    out["readiness"] = {"status": str(r.status),
                        "blockers": [str(b) for b in (r.blockers or [])][:6]}
    from app.persistence.readiness import compute_export_gate  # noqa: PLC0415
    try:
        g = compute_export_gate(s, workspace_id=WS, project_id=pid)
        out["export_gate"] = {"status": str(getattr(g, "status", g))}
        try:
            out["export_gate"]["videos"] = [
                {"video_status": v.video_status, "passed": v.passed, "detail": str(v.detail)[:160]}
                for v in (getattr(g, "videos", None) or [])][:6]
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        out["export_gate"] = {"error": f"{type(exc).__name__}: {exc}"[:240]}

(EVID / "raw" / "probe4_export_authority.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False)[:3200])
