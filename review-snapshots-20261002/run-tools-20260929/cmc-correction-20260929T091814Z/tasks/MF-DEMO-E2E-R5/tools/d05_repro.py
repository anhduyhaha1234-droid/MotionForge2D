"""D0.5/D0.9 repro — reproduce the export `av_policy` FAIL in-process.

Builds the exact ValidationExpectation the runner builds (`_expectation_for`)
for the FAILED run and validates the actual exported candidate so the failing
probe detail is measured instead of guessed. Read-only against app code.
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
from app.services.s12_export.validation import validate  # noqa: E402

WS = str(DEFAULT_WORKSPACE_ID)
RUN_ID = "7da2cb5f-2ea0-414a-a2db-8803ee8f0f59"
out: dict = {"at": "d05_repro", "run_id": RUN_ID}

con = sqlite3.connect(f"file:{MFR5 / 'data' / 'motionforge.db'}?mode=ro", uri=True)
manifest = json.loads(con.execute(
    "SELECT input_manifest_json FROM job WHERE id=?",
    ("1e7c146f-f26d-45b3-860d-28dd91d06ed8",)).fetchone()[0])
candidate = Path(manifest["output_path"])
out["candidate"] = str(candidate)
out["candidate_exists"] = candidate.is_file()

factory = create_session_factory(create_engine_for_path(MFR5 / "data" / "motionforge.db"))
with factory() as s:
    repo = S12ExportRepository(s)
    run = repo.get_run(RUN_ID)
    out["run_status"] = str(getattr(run, "status", None))
    try:
        exp = _expectation_for(run, manifest, candidate_sha="0" * 64)
        out["expectation"] = {
            "width": exp.width, "height": exp.height, "codec": exp.codec,
            "frame_count": getattr(exp, "frame_count", None),
            "source_reference": {
                "mode": getattr(getattr(exp, "audio", None) or getattr(exp, "audio_reference", None), "mode", None),
            },
        }
    except Exception as exc:  # noqa: BLE001
        out["expectation_error"] = f"{type(exc).__name__}: {exc}"
        exp = None

# the manifest's own audio authority + what the mux actually produced
aud = str(manifest.get("audio_source") or "")
out["manifest_audio_source"] = aud
out["manifest_audio_exists"] = Path(aud).is_file()

# validate EVERY chunk + the (missing) final path so we can see the av_policy probe
targets = [candidate]
chunk_dir = Path(manifest["chunk_dir"]) if manifest.get("chunk_dir") else None
if chunk_dir and chunk_dir.is_dir():
    targets += sorted(chunk_dir.glob("*.mp4"))
probes = []
for t in targets:
    if not t.is_file():
        continue
    try:
        v = validate(t, exp) if exp is not None else validate(t)
        probes.append({"path": str(t), "verdict": v.verdict,
                       "failed": [{"name": p.name, "verdict": p.verdict, "detail": p.detail}
                                  for p in v.probes if p.verdict != "PASS"]})
    except Exception as exc:  # noqa: BLE001
        probes.append({"path": str(t), "error": f"{type(exc).__name__}: {exc}"})
out["validate"] = probes

(RUN / "raw" / "d05_repro_avpolicy.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
