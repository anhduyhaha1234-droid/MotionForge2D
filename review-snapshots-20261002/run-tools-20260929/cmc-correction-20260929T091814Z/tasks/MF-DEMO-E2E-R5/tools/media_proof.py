"""D0.9 — media/audio proof + artifact reopen + publication copy into evidence.

1. ffprobe both publication and the export candidate assembly (video+audio).
2. Prove audio content identity between the assembled candidate and the
   attached original audio (aligned correlation).
3. Re-open every produced artifact through the REST routes (publication,
   export media when present) so "reopen" is HTTP-verified.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
MFR5 = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")
RAW = RUN / "raw"
EXPORT = RAW / "export"
EXPORT.mkdir(parents=True, exist_ok=True)
APP = "http://127.0.0.1:8035"
WS = "default"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fprobe(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                        "-of", "json", str(p)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return {"error": r.stderr[-300:]}


def http(method: str, path: str, timeout: int = 60) -> tuple[int, object]:
    req = urllib.request.Request(APP + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


out: dict = {"at": now()}

# ── 1. publication → evidence copy + probe (video only, by design) ─────────
h1 = json.loads((RAW / "harvest_d01.json").read_text(encoding="utf-8"))
pub = Path(h1["publication_path"])
demo = EXPORT / "demo_final.mp4"
if pub.is_file() and not demo.is_file():
    shutil.copyfile(pub, demo)
out["publication"] = {"src": str(pub), "copy": str(demo),
                      "sha256": sha(demo) if demo.is_file() else None,
                      "bytes": demo.stat().st_size if demo.is_file() else 0}
out["publication_probe"] = fprobe(pub) if pub.is_file() else None
(RAW / "ffprobe_demo.txt").write_text(
    json.dumps(out["publication_probe"], indent=1) + "\nSHA256=" + str(out["publication"]["sha256"])
    + "\n", encoding="utf-8")

# ── 2. assembled export candidate (real audio) + identity proof ────────────
cand = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/artifacts/s12-exports/4b09baee-d1a7-4c17-8078-88827279559a/"
            "302a6b71-ebb5-44d8-b373-005f9d34f8de/scratch/probe_repro/candidate_probe.mp4")
audio_ref = Path("C:/Users/Admin/AppData/Local/Temp/mfr5/artifacts/artifacts/default/audio/"
                 "d33a1085-aace-41e4-983c-594a5ecf8b5f/attach/original_audio.mp4")
out["export_candidate"] = {"path": str(cand), "exists": cand.is_file()}
if cand.is_file():
    out["export_candidate"]["sha256"] = sha(cand)
    out["export_candidate"]["bytes"] = cand.stat().st_size
    out["export_candidate_probe"] = fprobe(cand)
    # aligned correlation (the measured root cause of av_policy)
    import numpy as np  # noqa: E402
    tmp = RAW / "muxtest"
    tmp.mkdir(parents=True, exist_ok=True)

    def pcm(p: Path) -> "np.ndarray":
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-ac", "1",
                            "-ar", "48000", "-f", "s16le", "-"], capture_output=True)
        return np.frombuffer(r.stdout, dtype="<i2").astype(np.float64)

    a, b = pcm(cand), pcm(audio_ref)
    n = min(len(a), len(b))
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    cc = np.fft.irfft(np.fft.rfft(a) * np.conj(np.fft.rfft(b)), n)
    lag = int(np.argmax(cc))
    if lag > n // 2:
        lag -= n
    ax = a[max(0, lag):]
    bx = b[max(0, -lag):]
    m = min(len(ax), len(bx))
    out["audio_identity"] = {
        "raw_corr": round(float(np.corrcoef(a, b)[0, 1]), 4),
        "best_lag_samples": lag, "best_lag_ms": round(lag / 48.0, 3),
        "aligned_corr": round(float(np.corrcoef(ax[:m], bx[:m])[0, 1]), 4),
        "candidate_audio_codec": next((s.get("codec_name") for s in
                                       (out["export_candidate_probe"].get("streams") or [])
                                       if s.get("codec_type") == "audio"), None),
        "candidate_audio_channels": next((s.get("channels") for s in
                                          (out["export_candidate_probe"].get("streams") or [])
                                          if s.get("codec_type") == "audio"), None),
    }
    # keep a copy of the candidate as the "reassembled export (audio present)" for review
    shutil.copyfile(cand, EXPORT / "export_candidate_with_audio.mp4")
    out["export_candidate"]["evidence_copy"] = str(EXPORT / "export_candidate_with_audio.mp4")

# ── 3. reopen artifacts over HTTP ──────────────────────────────────────────
st = json.loads((RAW / "state.json").read_text(encoding="utf-8"))
pid, vid = st["project_id"], st["video_id"]
run_id = st["run_id"]
reopen = {}
sc, body = http("GET", f"/api/v2/full-apply/{run_id}?workspace_id={WS}")
reopen["full_apply_run"] = {"status": sc, "state": (body or {}).get("status")}
sc, body = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}/readiness")
reopen["readiness"] = {"status": sc, "readiness": (body or {}).get("status")}
sc, body = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}")
reopen["qc_run"] = {"status": sc, "run_state": (body or {}).get("run_state")}
sc, body = http("GET", f"/api/v2/projects/{pid}/qc-items")
reopen["qc_items"] = {"status": sc,
                      "count": len(((body or {}).get("items") or []))}
sc, body = http("GET", f"/s12-exports/7da2cb5f-2ea0-414a-a2db-8803ee8f0f59?workspace_id={WS}")
reopen["export_run"] = {"status": sc, "state": (body or {}).get("state")}
sc, body = http("GET", f"/s12-exports/7da2cb5f-2ea0-414a-a2db-8803ee8f0f59/media?workspace_id={WS}")
reopen["export_media"] = {"status": sc, "detail": str((body or {}).get("detail"))[:160]}
out["reopen"] = reopen

(RAW / "media_proof.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str),
                                      encoding="utf-8")
print(json.dumps({k: out[k] for k in ("publication", "export_candidate", "audio_identity", "reopen")},
                 indent=1, ensure_ascii=False, default=str)[:2400])
