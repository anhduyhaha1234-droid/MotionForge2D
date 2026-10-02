"""D0.5 repro #3 — call the validator's OWN audio-content probe so the
av_policy numbers are measured by the product's code, not re-derived by hand.

Also prints the streams of both sides and the per-channel correlation, to tell
a genuine content mismatch from a measurement/decode artefact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
os.environ["MOTIONFORGE_ROOT"] = str(MFR5)
sys.path.insert(0, str(WT))

from app.services.s12_export.validation import (  # noqa: E402
    probe_audio_content,
    probe_audio_shape,
    probe_audio_digest,
)

cand = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/artifacts/s12-exports/4b09baee-d1a7-4c17-8078-88827279559a/302a6b71-ebb5-44d8-b373-005f9d34f8de/scratch/probe_repro/candidate_probe.mp4")
ref = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/artifacts/artifacts/default/audio/d33a1085-aace-41e4-983c-594a5ecf8b5f/attach/original_audio.mp4")
src = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/artifacts/s10_full_apply/_authority/302a6b71-ebb5-44d8-b373-005f9d34f8de/source_12s.mp4")

out: dict = {"at": "d05_repro3"}


def probe(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name,sample_rate,channels,start_time,duration,time_base",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)


out["cand_streams"] = probe(cand)
out["ref_streams"] = probe(ref)
out["ref_is_source_audio"] = (ref.read_bytes() == src.read_bytes())

for label, refp in (("ref_attach", ref), ("source_12s", src)):
    shape = probe_audio_shape(str(refp), 0)
    out[f"shape_{label}"] = list(shape) if shape else None
    out[f"digest_{label}"] = probe_audio_digest(str(refp), 0)

cshape = probe_audio_shape(str(cand), 0)
out["shape_cand"] = list(cshape) if cshape else None
out["digest_cand"] = probe_audio_digest(str(cand), 0)

try:
    got = probe_audio_content(
        str(ref), str(cand), reference_stream_index=0, candidate_stream_index=0,
        channels=int((cshape or (0, 0))[0] or 0), sample_rate=int((cshape or (0, 0))[1] or 0),
        max_drift_sec=1 / 30.0, timeout_sec=600.0,
    )
    out["probe_audio_content"] = dict(got) if got else None
except Exception as exc:  # noqa: BLE001
    out["probe_audio_content"] = {"error": f"{type(exc).__name__}: {exc}"}

# independent per-channel correlation at a few windows
import numpy as np  # noqa: E402


def decode_mono(p: Path, ch: int) -> "np.ndarray":
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-map", f"0:a:0",
                        "-af", f"pan=mono|c0=c{ch}", "-ar", "48000", "-f", "s16le", "-"],
                       capture_output=True)
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float64)


per_ch = {}
for ch in (0, 1):
    a, b = decode_mono(cand, ch), decode_mono(ref, ch)
    n = min(len(a), len(b))
    w = min(48000 * 2, n)
    per_ch[ch] = {"samples_cand": int(len(a)), "samples_ref": int(len(b)),
                  "corr_first2s": round(float(np.corrcoef(a[:w], b[:w])[0, 1]), 4),
                  "rms_cand": round(float(np.sqrt((a[:w] ** 2).mean())), 1),
                  "rms_ref": round(float(np.sqrt((b[:w] ** 2).mean())), 1)}
out["per_channel"] = per_ch

(RUN / "raw" / "d05_repro3_audio.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, default=str)[:2600])
