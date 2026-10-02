"""Read-only probe #3: prove the cut_drift window starvation + measure the
identity_drift argv bloat, on the LIVE R4 runtime (#7 code, in-memory patches
only — no file/DB writes).

1. Call compose._cut_drift with defaults -> expect the typed refusal.
2. Re-call with a LARGER frame window (in-memory patch) -> if the cut becomes
   observable, the render evidence exists and the window slice is the blocker.
3. Call compose._identity_drift with a raised argv ceiling -> measure the
   composed byte size + per-key breakdown (who eats the ~32500 B budget).
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

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.services.qc_evidence import compose as C  # noqa: E402
from app.services.qc_evidence import sources as src  # noqa: E402

st = json.loads((EVID / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
DB = MFR4 / "data" / "motionforge.db"
out: dict = {"project_id": pid, "video_id": vid, "at": "probe3"}


def _sz(v: object) -> int:
    return len(json.dumps(v, separators=(",", ":")).encode("utf-8"))


factory = create_session_factory(create_engine_for_path(DB))
with factory() as s:
    scope = src.load_scope(s, workspace_id=WS, project_id=pid, video_item_id=vid)
    ctx = C._Context(session=s, managed_root=MFR4 / "artifacts", scope=scope)

    # 1) default window
    try:
        C._cut_drift(ctx)
        out["cut_drift_default"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        out["cut_drift_default"] = {"ok": False, "code": str(getattr(exc, "code", "")),
                                    "message": str(exc)[:280]}

    # 2) larger window (in-memory only)
    old_const, old_attr = C.MAX_WINDOW_FRAMES, ctx.max_frames
    C.MAX_WINDOW_FRAMES = 2000
    ctx.max_frames = 2000
    try:
        r = C._cut_drift(ctx)
        obs = r.get("observed_cut") or r.get("observed") or {}
        out["cut_drift_wide_window"] = {
            "ok": True, "top_level_keys": sorted(r),
            "observed_cut": obs if isinstance(obs, dict) else str(obs)[:200],
            "measured_frames_count": len((obs or {}).get("deltas") or {}) if isinstance(obs, dict) else None,
        }
    except Exception as exc:  # noqa: BLE001
        out["cut_drift_wide_window"] = {"ok": False, "code": str(getattr(exc, "code", "")),
                                        "message": str(exc)[:400]}
    finally:
        C.MAX_WINDOW_FRAMES, ctx.max_frames = old_const, old_attr

    # 3) identity argv bloat
    old_ok, old_206 = C.ARGV_CEILING_SPAWN_OK_BYTES, C.ARGV_CEILING_WINERROR_206_BYTES
    C.ARGV_CEILING_SPAWN_OK_BYTES = 10**9
    C.ARGV_CEILING_WINERROR_206_BYTES = 10**9
    try:
        args = C._identity_drift(ctx)
        out["identity_raised_ceiling"] = {
            "ok": True, "total_bytes": _sz(args),
            "per_key_bytes": {str(k): _sz(v) for k, v in args.items()},
        }
    except Exception as exc:  # noqa: BLE001
        out["identity_raised_ceiling"] = {"ok": False, "message": str(exc)[:300]}
    finally:
        C.ARGV_CEILING_SPAWN_OK_BYTES, C.ARGV_CEILING_WINERROR_206_BYTES = old_ok, old_206

    out["constants"] = {"MAX_WINDOW_FRAMES": old_const,
                        "argv_ceiling_spawn_ok": old_ok,
                        "argv_ceiling_winerror206": old_206}

(EVID / "raw" / "probe3_cut_identity.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False)[:4500])
