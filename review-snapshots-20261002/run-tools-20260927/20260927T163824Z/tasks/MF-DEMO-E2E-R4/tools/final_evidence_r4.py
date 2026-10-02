"""Final evidence collector (read-only): DB harvest digest + the exact
submit-time audio resolution for the R4 publication + the cut_drift window
replay (code-accurate arithmetic on the real scenes).
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

out: dict = {"at": "final_evidence"}

db = json.loads((EVID / "raw" / "db_harvest.json").read_text(encoding="utf-8"))
out["jobs"] = [{k: str(r.get(k))[:60] for k in ("id", "job_type", "state", "owner_type", "owner_id")
                if k in r} for r in db.get("job", [])]
out["job_steps"] = [{str(k): str(v)[:40] for k, v in r.items()
                     if k in ("step_code", "position", "state")} for r in db.get("job_step", [])]
out["publication_rows"] = db.get("s10_full_apply_publication", [])
out["chunk_rows"] = [{k: r.get(k) for k in ("id", "chunk_index", "shot_id", "state", "verified",
                                            "attempt", "core_start_frame", "core_end_frame")}
                     for r in db.get("s10_full_apply_chunk", [])]
out["counts"] = {t: len(db.get(t, [])) for t in ("job", "job_step", "s10_full_apply_run",
                                                 "s10_full_apply_chunk", "s10_full_apply_publication",
                                                 "qc_item", "s12_export_run")}

# exact submit-time audio resolution for the R4 publication
from app.services.original_audio_remux import probe_original_audio  # noqa: E402
from app.workflow.s12_export_jobs import resolve_original_audio_source  # noqa: E402

try:
    from sqlalchemy import create_engine, text  # noqa: E402
    eng = create_engine(f"sqlite:///{MFR4 / 'data' / 'motionforge.db'}", future=True)
    with eng.connect() as c:
        pub_rel = c.execute(text(
            "SELECT a.relative_path FROM s10_full_apply_publication p JOIN artifact a"
            " ON a.id = p.artifact_id ORDER BY p.created_at DESC LIMIT 1")).scalar()
    pub_abs = MFR4 / "artifacts" / str(pub_rel)
    value, prov = resolve_original_audio_source(pub_abs)
    out["export_audio_resolution"] = {
        "source_path": str(pub_rel), "exists": pub_abs.is_file(),
        "audio_value": value, "provenance": prov,
        "probe": {"present": probe_original_audio(pub_abs).present,
                  "detail": str(probe_original_audio(pub_abs).detail)[:160]},
    }
except Exception as exc:  # noqa: BLE001
    out["export_audio_resolution"] = {"error": f"{type(exc).__name__}: {exc}"}

# cut_drift window replay: the exact arithmetic of
# compose._cut_drift lines (budget=MAX_WINDOW_FRAMES=24) on the REAL scenes
try:
    from app.services.qc_evidence.measure import MAX_WINDOW_FRAMES as MW  # noqa: E402
    scenes = [(0, 119), (120, 239), (240, 359)]
    budget = max(4, int(MW))
    spans = {}
    for index, (start, end) in enumerate(scenes):
        low = scenes[index - 1][0] + 1 if index > 0 else start
        span = (max(0, low), end)
        if span[1] - span[0] + 1 > budget:
            begin = min(max(span[0], start - budget // 2), span[1] - budget + 1)
            span = (begin, begin + budget - 1)
        spans[start] = span
    wanted: set = set()
    for start, span in spans.items():
        for frame in range(span[0], span[1] + 1):
            wanted.add(frame - 1)
            wanted.add(frame)
    indices = sorted(wanted)[:MW]
    out["cut_drift_window_replay"] = {
        "max_window_frames": MW, "scene_spans": {str(k): list(v) for k, v in spans.items()},
        "wanted_count": len(wanted), "decoded_indices": [min(indices), max(indices)],
        "decoded_count": len(indices),
        "boundary_120_needs": [107, 131],
        "boundary_120_decodable_pairs": [f for f in range(108, 132) if (f - 1) in indices and f in indices],
    }
except Exception as exc:  # noqa: BLE001
    out["cut_drift_window_replay"] = {"error": f"{type(exc).__name__}: {exc}"}

(EVID / "raw" / "final_evidence.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str),
                                                 encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False, default=str)[:3600])
