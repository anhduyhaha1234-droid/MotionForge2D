"""Capture the QC-state/readiness read authority + the publication evidence receipt."""
import json
import shutil
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")
RAW = EVID / "raw"
APP = "http://127.0.0.1:8032"
MANAGED = Path("C:/Users/Admin/AppData/Local/Temp/mfr3/artifacts")
st = json.loads((RAW / "state.json").read_text(encoding="utf-8"))
pid = st["project_id"]
vid = st["video_id"]
run = st["run_id"]

out = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": run}

def get(path: str):
    t0 = time.time()
    try:
        with urllib.request.urlopen(APP + path, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8")), round(time.time() - t0, 3)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, body, round(time.time() - t0, 3)

sc, body, dur = get(f"/api/v2/projects/{pid}/qc-check-runs/{vid}?workspace_id=default")
out["qc_state"] = {"path": f"/api/v2/projects/{pid}/qc-check-runs/{vid}", "status": sc, "dur_s": dur, "body": body}
sc, body, dur = get(f"/api/v2/projects/{pid}/qc-check-runs/{vid}/readiness?workspace_id=default")
out["qc_readiness"] = {"path": f"/api/v2/projects/{pid}/qc-check-runs/{vid}/readiness", "status": sc, "dur_s": dur, "body": body}

(RAW / "extra_http.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("QC_STATE", out["qc_state"]["status"], json.dumps(out["qc_state"]["body"], ensure_ascii=False)[:400])
print("QC_READINESS", out["qc_readiness"]["status"], json.dumps(out["qc_readiness"]["body"], ensure_ascii=False)[:400])

# publication evidence receipt (written by the app's publication step)
src = MANAGED / "s10_full_apply" / str(run) / "stitch_shot_chunks.mp4.evidence.json"
if src.is_file():
    dst = RAW / "app_receipts"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst / src.name)
    print("PUB_EVIDENCE_COPIED", (dst / src.name).stat().st_size)
else:
    print("PUB_EVIDENCE_MISSING", src)
