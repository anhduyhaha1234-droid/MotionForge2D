"""D0.5 repro #2 — run the REAL assembly+validation in-process to see the
exact failing probe of the failed export run (read-only w.r.t. app code).

Rebuilds the runner config exactly as the durable job would for run
7da2cb5f…, re-assembles from the real chunk files into the run's own scratch
(a new candidate path is chosen: the runner's candidate name), then calls the
product's own validate() with the expectation built by `_expectation_for`.
"""
from __future__ import annotations

import json
import os
import sqlite3
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
from app.persistence.s12_export import S12ExportRepository  # noqa: E402
from app.services.s12_export.publication import _expectation_for  # noqa: E402
from app.services.s12_export.stitch import assemble_run, count_video_frames  # noqa: E402
from app.services.s12_export.validation import validate  # noqa: E402

WS = str(DEFAULT_WORKSPACE_ID)
RUN_ID = "7da2cb5f-2ea0-414a-a2db-8803ee8f0f59"
con = sqlite3.connect(f"file:{MFR5 / 'data' / 'motionforge.db'}?mode=ro", uri=True)
manifest = json.loads(con.execute(
    "SELECT input_manifest_json FROM job WHERE id=?",
    ("1e7c146f-f26d-45b3-860d-28dd91d06ed8",)).fetchone()[0])

out: dict = {"at": "d05_repro2"}

# Spec objects taken from the persisted chunk rows so the assembly is the real one.
factory = create_session_factory(create_engine_for_path(MFR5 / "data" / "motionforge.db"))
from app.services.s12_export.chunks import ChunkSpec  # noqa: E402
from app.services.s12_export.stitch import ChunkMedia  # noqa: E402

with factory() as s:
    repo = S12ExportRepository(s)
    rows = list(repo.list_chunks(RUN_ID))
    media = []
    for row in rows:
        media.append(ChunkMedia(
            path=Path(manifest["chunk_dir"]) / f"chunk_{int(row.chunk_index):04d}.mp4",
            spec=ChunkSpec(
                chunk_index=int(row.chunk_index),
                content_hash=str(row.content_hash),
                order_index=int(row.order_index),
                core_start_frame=int(row.core_start_frame),
                core_end_frame=int(row.core_end_frame),
                overlap_before=int(row.overlap_before),
                overlap_after=int(row.overlap_after),
            ),
        ))
    out["media"] = [{"path": str(m.path), "exists": m.path.is_file(),
                     "core": [m.spec.core_start_frame, m.spec.core_end_frame],
                     "overlap": [m.spec.overlap_before, m.spec.overlap_after]} for m in media]
    scratch = Path(manifest["scratch_dir"]) / "probe_repro"
    candidate = scratch / "candidate_probe.mp4"
    if candidate.is_file():
        candidate.unlink()
    try:
        got = assemble_run(media, frame_count=360, fps=30.0,
                           output_path=candidate,
                           audio_source=manifest.get("audio_source"),
                           scratch_dir=scratch, encoder="libx264")
        out["assemble"] = {"ok": True, "path": str(got),
                           "frames": count_video_frames(got),
                           "sha256": __import__("hashlib").sha256(got.read_bytes()).hexdigest()}
        run = repo.get_run(RUN_ID)
        exp = _expectation_for(run, manifest, candidate_sha=None)
        v = validate(got, exp)
        out["validate"] = {"verdict": v.verdict,
                           "probes": [{"name": p.name, "verdict": p.verdict, "detail": p.detail}
                                      for p in v.probes]}
    except Exception as exc:  # noqa: BLE001
        out["assemble"] = {"ok": False, "type": type(exc).__name__, "message": str(exc)[:600]}

(RUN / "raw" / "d05_repro2_assemble.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
