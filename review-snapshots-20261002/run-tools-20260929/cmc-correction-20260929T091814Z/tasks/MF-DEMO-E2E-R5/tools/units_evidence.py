"""D0.5/D0.6/D0.7/D0.8 — measure the unit-level facts on the REAL run.

(a) D0.6 time map: detect the source's own scene boundaries (frame-difference
    peaks) and compare them with the persisted scene rows / segments.
(b) D0.5/D0.8: per-unit source-window vs rendered-output frame differences +
    contact sheets (source | output) so the visual verdict is measurable.
(c) D0.7: record which masks the QC run ACTUALLY read (seeded pre-render
    rectangles vs the output-derived observations).

No GPU, read-only on app code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
MANAGED = MFR5 / "artifacts"
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

st = json.loads((RUN / "raw" / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
OUT = RUN / "raw" / "units"
OUT.mkdir(parents=True, exist_ok=True)
factory = create_session_factory(create_engine_for_path(MFR5 / "data" / "motionforge.db"))
out: dict = {"at": "units", "video_item_id": vid}

# ── rendered output = the real publication ─────────────────────────────────
pub_rows = json.loads((RUN / "raw" / "harvest_d01.json").read_text(encoding="utf-8"))
pub_rel = pub_rows.get("publication_path")
pub = Path(pub_rel) if pub_rel else None
out["publication"] = str(pub)


def frames_of(path: Path, idxs: list[int]) -> dict:
    cap = cv2.VideoCapture(str(path))
    got = {}
    for i in sorted(idxs):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if ok:
            got[int(i)] = f
    cap.release()
    return got


SRC = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R5/raw/source_12s.mp4")
if not SRC.is_file():
    SRC = MANAGED / st["seed"]["source_rel"]

# ── (a) time map: scene-cut peaks in the SOURCE ────────────────────────────
cap = cv2.VideoCapture(str(SRC))
prev, deltas, i = None, [], 0
while True:
    ok, f = cap.read()
    if not ok:
        break
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float64)
    if prev is not None:
        deltas.append(float(np.mean(np.abs(g - prev))))
    prev = g
    i += 1
cap.release()
arr = np.asarray(deltas)
order = np.argsort(arr)[::-1]
peaks = []
for k in order:
    fr = int(k) + 1
    if all(abs(fr - p) > 10 for p in peaks):
        peaks.append(fr)
    if len(peaks) >= 6:
        break
out["source"] = {"path": str(SRC), "frames": i,
                 "cut_peaks": sorted(peaks),
                 "peak_values": {str(f): round(float(arr[f - 1]), 2) for f in sorted(peaks)}}

with factory() as s:
    scenes = [dict(r) for r in s.execute(text(
        "SELECT position,start_frame,end_frame,start_time_ms,end_time_ms FROM scene"
        " WHERE video_item_id=:v ORDER BY position"), {"v": vid}).mappings().all()]
    segs = [dict(r) for r in s.execute(text(
        "SELECT o.name, os.start_frame, os.end_frame, os.mask_artifact_id FROM occurrence_segment os"
        " JOIN object_role o ON o.id=os.role_id WHERE os.video_item_id=:v"), {"v": vid}).mappings().all()]
    masks = [dict(r) for r in s.execute(text(
        "SELECT a.id,a.relative_path,a.width,a.height,ao.purpose FROM artifact a"
        " JOIN artifact_owner ao ON ao.artifact_id=a.id WHERE a.kind='image'")).mappings().all()]
out["scene_rows"] = scenes
out["segments"] = segs
out["image_artifacts"] = masks

# ── (b) per-unit source-window vs output window ────────────────────────────
units = [("BOOK", 0, 120), ("TURN", 120, 240), ("OCC", 240, 360)]
per_unit = {}
for name, s0, s1 in units:
    idxs = [s0 + int(round(k * (s1 - s0 - 1) / 3)) for k in range(4)]
    sf = frames_of(SRC, idxs)
    of = frames_of(pub, idxs) if pub and pub.is_file() else {}
    rows = []
    for k, fr in enumerate(idxs):
        a, b = sf.get(fr), of.get(fr)
        if a is None or b is None:
            rows.append({"frame": fr, "missing": bool(a is None or b is None)})
            continue
        bb = cv2.resize(b, (a.shape[1], a.shape[0]))
        mad = float(np.mean(np.abs(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float64)
                                  - cv2.cvtColor(bb, cv2.COLOR_BGR2GRAY).astype(np.float64))))
        rows.append({"frame": fr, "mad": round(mad, 2)})
        tile = np.hstack([a, bb])
        cv2.imwrite(str(OUT / f"{name}_f{fr:03d}_src_vs_out.png"), tile)
    per_unit[name] = {"span": [s0, s1], "samples": rows,
                      "sheet": f"units/{name}_f{idxs[0]:03d}_src_vs_out.png"}
out["units"] = per_unit
out["note_vision"] = ("contact sheets written for visual review; numeric MAD is NOT a "
                      "content verdict (style/action match needs eyes)")

(RUN / "raw" / "units_evidence.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print("source cut_peaks:", out["source"]["cut_peaks"], flush=True)
print("scene rows:", [(c["position"], c["start_frame"], c["end_frame"]) for c in scenes], flush=True)
print("segments:", [(s["name"], s["start_frame"], s["end_frame"]) for s in segs], flush=True)
print("MAD:", {k: [r.get("mad") for r in v["samples"]] for k, v in per_unit.items()}, flush=True)
