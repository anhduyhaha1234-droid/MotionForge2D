"""probe5: PREDICT the QC full-band compose + detector verdicts for the R5 seed.

Works on a COPY of the R4 runtime (Temp/mfr5p) so neither the R4 evidence nor
the real R5 runtime is touched: per-role masks + one rendered-side mask
artifact (artifact_owner(video_item, purpose='mask')) are seeded into the copy,
then compose_check_run_args(scope='full') + the REAL runner (child spawn) are
executed in-process to predict failure modes BEFORE burning GPU time.
Read-only with respect to the INTEGRATION tree.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

R5 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R5")
R4 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R4")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
MFR4 = Path("C:/Users/Admin/AppData/Local/Temp/mfr4")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5p")

os.environ["MOTIONFORGE_ROOT"] = str(MFR5)
sys.path.insert(0, str(WT))

# ── 0. copy the R4 runtime (first run only) ─────────────────────────────────
if not MFR5.exists():
    shutil.copytree(MFR4, MFR5)
print("runtime copy ready:", MFR5, flush=True)

# per-role boxes (x0, y0, x1, y1) exclusive; rendered = subset of BOOK-P1
BOXES = {
    "BOOK-P1": (64, 36, 256, 144),
    "BOOK-P2": (192, 108, 384, 216),
    "BOOK-P3": (384, 36, 576, 144),
    "BOOK-P4": (64, 216, 256, 324),
    "TURN-CERT": (480, 36, 640, 144),
    "OCC-PEN": (320, 144, 512, 252),
}
RENDERED = (68, 40, 252, 140)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.services.qc_evidence import compose_visual_band  # noqa: E402
from app.workflow.qc_checks_handler import compose_check_run_args  # noqa: E402

st = json.loads((R4 / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
DB = MFR5 / "data" / "motionforge.db"
MANAGED = MFR5 / "artifacts"
out: dict = {"project_id": pid, "video_id": vid, "db": str(DB), "boxes": BOXES,
             "rendered_box": list(RENDERED)}

factory = create_session_factory(create_engine_for_path(DB))


def _mk_mask(path: Path, box) -> dict:
    x0, y0, x1, y1 = box
    img = np.zeros((360, 640), dtype=np.uint8)
    img[y0:y1, x0:x1] = 255
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    import hashlib

    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"rel": str(path.relative_to(MANAGED)).replace("\\", "/"), "sha256": h,
            "bytes": path.stat().st_size}


# ── 1. seed per-role masks + rendered mask into the COPY ────────────────────
seed_info: dict = {"masks": {}, "rendered": None}
with factory() as s:
    rows = s.execute(text(
        "SELECT s.id, r.name FROM occurrence_segment s "
        "JOIN object_role r ON r.id = s.role_id "
        "WHERE s.video_item_id = :v AND s.source_generation = '1'"
    ), {"v": vid}).all()
    assert len(rows) == 6, f"expected 6 segments, got {len(rows)}"
    for seg_id, role_name in rows:
        box = BOXES[str(role_name)]
        rel = f"s10_full_apply/_authority/{vid}/masks/mask_{str(role_name).replace('-', '_')}.png"
        meta = _mk_mask(MANAGED / rel, box)
        art_id = f"art-r5m-{str(role_name).replace('-', '').lower()}"
        s.execute(text(
            "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,"
            "sha256,size_bytes,revision) VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1) "
            "ON CONFLICT(id) DO UPDATE SET relative_path=excluded.relative_path,"
            "sha256=excluded.sha256,size_bytes=excluded.size_bytes,state='ready'"
        ), {"id": art_id, "w": WS, "rel": rel, "sha": meta["sha256"], "sz": meta["bytes"]})
        s.execute(text("UPDATE occurrence_segment SET mask_artifact_id = :a WHERE id = :s"),
                  {"a": art_id, "s": seg_id})
        seed_info["masks"][str(role_name)] = {"artifact_id": art_id, **meta, "box": box}
    rrel = f"s10_full_apply/_authority/{vid}/masks/rendered_mask.png"
    rmeta = _mk_mask(MANAGED / rrel, RENDERED)
    rart = "art-r5m-rendered"
    s.execute(text(
        "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,"
        "sha256,size_bytes,revision) VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1) "
        "ON CONFLICT(id) DO UPDATE SET relative_path=excluded.relative_path,"
        "sha256=excluded.sha256,size_bytes=excluded.size_bytes,state='ready'"
    ), {"id": rart, "w": WS, "rel": rrel, "sha": rmeta["sha256"], "sz": rmeta["bytes"]})
    s.execute(text(
        "INSERT INTO artifact_owner(artifact_id,owner_type,owner_id,purpose) "
        "VALUES (:a,'video_item',:v,'mask') ON CONFLICT DO NOTHING"), {"a": rart, "v": vid})
    s.commit()
    seed_info["rendered"] = {"artifact_id": rart, **rmeta, "box": RENDERED}
out["seed"] = seed_info

# ── 2. compose the full band ────────────────────────────────────────────────
args_all = None
try:
    with factory() as s:
        args_all = compose_check_run_args(s, workspace_id=WS, project_id=pid,
                                          video_item_id=vid, scope="full")
    out["compose"] = {"ok": True, "detectors": sorted(args_all)}
except Exception as exc:  # noqa: BLE001
    details = getattr(exc, "details", None) or {}
    out["compose"] = {
        "ok": False, "type": type(exc).__name__, "code": str(getattr(exc, "code", "")),
        "message": str(exc)[:800],
        "failed_detectors": {k: {kk: str(vv)[:400] for kk, vv in (v or {}).items()}
                             for k, v in (details.get("failed_detectors") or {}).items()},
    }

# z_order measured numbers + edge_halo provenance (when composed)
if args_all:
    if "z_order_error" in args_all:
        zo = args_all["z_order_error"]
        out["z_order_error"] = {
            "render_order": zo.get("render_order"),
            "render_stacking": zo.get("render_stacking"),
            "analysis_window": zo.get("analysis_window"),
        }
    if "edge_halo" in args_all:
        eh = args_all["edge_halo"]
        prov = (eh.get("evidence_provenance") or {}).get("families", {}).get("artifact", {})
        out["edge_halo"] = {
            "expected_bbox": prov.get("expected_bbox"), "rendered_bbox": prov.get("rendered_bbox"),
            "window": prov.get("window"), "window_bounded": (eh.get("evidence_provenance") or {})
            .get("derivations", {}).get("window_bounded"),
            "expected_artifact": (eh.get("expected") or {}).get("artifact_id"),
            "rendered_artifact": (eh.get("rendered") or {}).get("artifact_id"),
        }

# ── 3. run every composed detector through the REAL child transport ─────────
det_out: dict = {}
if args_all:
    from app.services.qc_checks.registry import get_detector
    from app.services.qc_checks.runner import run_detector
    from app.workflow.qc_checks_handler import ensure_full_band_registered

    ensure_full_band_registered()

    import importlib

    for name in sorted(args_all):
        try:
            spec = get_detector(name)
        except Exception as exc:  # noqa: BLE001
            det_out[name] = {"registered": False, "error": str(exc)[:200]}
            continue
        mod = importlib.import_module(spec.entry_point.split(":")[0])
        fn = mod
        for part in spec.entry_point.split(":")[1].split("."):
            fn = getattr(fn, part)
        try:
            run = run_detector(name, args=dict(args_all[name]), deadline_sec=600,
                               capture_cap_bytes=8_000_000)
            out_res = run.output
            if isinstance(out_res, dict):
                det_out[name] = {"ok": True, "run_status": run.status,
                                 "run_code": run.code, "run_sec": round(run.run_sec, 3),
                                 "status": out_res.get("status"),
                                 "code": out_res.get("code"),
                                 "items": len(out_res.get("items") or []),
                                 "output": out_res}
            elif isinstance(out_res, list):
                det_out[name] = {"ok": True, "run_status": run.status,
                                 "run_code": run.code, "run_sec": round(run.run_sec, 3),
                                 "items": len(out_res), "output": out_res}
            else:
                det_out[name] = {"ok": True, "output": str(out_res)[:400]}
        except Exception as exc:  # noqa: BLE001
            det_out[name] = {"ok": False, "type": type(exc).__name__,
                             "code": str(getattr(exc, "code", "")),
                             "error": str(exc)[:400]}
out["detectors"] = det_out

(R5 / "raw").mkdir(parents=True, exist_ok=True)
(R5 / "raw" / "probe5_seed_compose.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False, default=str)[:6000])
