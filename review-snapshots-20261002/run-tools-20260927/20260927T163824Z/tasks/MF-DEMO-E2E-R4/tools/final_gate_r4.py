"""FINAL GATE (R4): prove the finished state on disk.

Checks: HEAD == FROZEN #7, porcelain 0, required artifacts present with sizes,
engine evidence prompt ids, regeneration of raw/sha256_manifest.txt over the
whole evidence root, video ffprobe headline. Writes raw/final_gate.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R4")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
FROZEN = "dfdad73457d499a83e36a887ff64cd35c6f5d929"

out: dict = {"frozen": FROZEN, "checks": {}}
ok = True


def check(name: str, passed: bool, detail: object = None) -> None:
    global ok
    out["checks"][name] = {"pass": bool(passed), "detail": detail}
    ok = ok and bool(passed)


head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(WT), capture_output=True, text=True).stdout.strip()
por = subprocess.run(["git", "status", "--porcelain"], cwd=str(WT), capture_output=True, text=True).stdout
check("head_is_frozen_7", head == FROZEN, head)
check("porcelain_empty", por.strip() == "", por.strip()[:200])

required = [
    "TARGET.md", "REPORT.md", "FINDINGS.md",
    "raw/state.json", "raw/commands.jsonl", "raw/app_launch.json", "raw/comfy_epoch.json",
    "raw/comfy_shutdown.json", "raw/harvest_receipt.json", "raw/engine_harvest.json",
    "raw/db_harvest.json", "raw/audio_receipt.json", "raw/qc_receipt.json",
    "raw/export_receipt.json", "raw/run_result.json", "raw/probe_qc_compose.json",
    "raw/probe_qc_compose_r4.json", "raw/probe3_cut_identity.json",
    "raw/probe4_export_authority.json", "raw/final_evidence.json",
    "raw/verify_receipt.json", "raw/ffprobe_demo.txt", "raw/preview_contact_sheet.png",
    "raw/export/demo_final.mp4", "raw/sha256_manifest.txt",
]
missing = []
sizes = {}
for rel in required:
    p = EVID / rel
    if p.is_file() and p.stat().st_size > 0:
        sizes[rel] = p.stat().st_size
    else:
        missing.append(rel)
check("required_artifacts", not missing, missing or f"{len(required)} present")
out["artifact_sizes"] = sizes

# engine evidence prompt ids
ev = {}
for f in sorted((EVID / "raw" / "engine_state" / "evidence").glob("*.engine_evidence.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    ev[f.name] = {"status": d.get("status"), "prompt_id": d.get("prompt_id"),
                  "bucket": ((d.get("video_shape_proof") or {}).get("bucket"))}
check("engine_evidence_3_validated", len(ev) == 3 and all(v["status"] == "validated" for v in ev.values()), ev)
out["engine_evidence"] = ev

# video headline probe
probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,nb_frames",
                        "-show_entries", "format=duration", "-of", "json",
                        str(EVID / "raw" / "export" / "demo_final.mp4")],
                       capture_output=True, text=True).stdout
pj = json.loads(probe)
vs = [s for s in pj["streams"] if s.get("codec_type") == "video"]
v = vs[0] if vs else {}
check("demo_video_640x360_360f",
      v.get("width") == 640 and v.get("height") == 360 and bool(vs) and abs(float(pj["format"]["duration"]) - 12.0) < 0.05,
      {k: v.get(k) for k in ("codec_name", "width", "height", "nb_frames")} | {"duration": pj["format"]["duration"]})

# regenerate the sha256 manifest over the whole evidence root (after the final files)
lines = []
manifest = EVID / "raw" / "sha256_manifest.txt"
count = 0
for p in sorted(EVID.rglob("*")):
    if not p.is_file() or p == manifest:
        continue
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    lines.append(f"{h.hexdigest()}  {p.relative_to(EVID).as_posix()}  {p.stat().st_size}")
    count += 1
manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
check("manifest_regenerated", count > 80, {"files": count})
out["manifest_files"] = count

out["final"] = "PASS" if ok else "FAIL"
(EVID / "raw" / "final_gate.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                              encoding="utf-8")
print(json.dumps({"final": out["final"], "checks": {k: v["pass"] for k, v in out["checks"].items()},
                  "manifest_files": count}, indent=1))
sys.exit(0 if ok else 1)
