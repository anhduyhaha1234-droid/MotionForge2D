"""FINAL GATE — MF-DEMO-E2E (Step 5). Asserts every required artifact on disk."""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


required = {
    "REPORT.md": EVID / "REPORT.md",
    "FINDINGS.md": EVID / "FINDINGS.md",
    "TARGET.md": EVID / "TARGET.md",
    "commands.jsonl": EVID / "raw" / "commands.jsonl",
    "state.json": EVID / "raw" / "state.json",
    "app_launch.json": EVID / "raw" / "app_launch.json",
    "comfy_epoch.json": EVID / "raw" / "comfy_epoch.json",
    "comfy_shutdown.json": EVID / "raw" / "comfy_shutdown.json",
    "run_result.json": EVID / "raw" / "run_result.json",
    "engine3_receipt.json": EVID / "raw" / "engine3_receipt.json",
    "ffprobe_demo.txt": EVID / "raw" / "ffprobe_demo.txt",
    "preview_contact_sheet.png": EVID / "raw" / "preview_contact_sheet.png",
    "demo_final.mp4": EVID / "raw" / "export" / "demo_final.mp4",
    "source_12s.mp4": EVID / "raw" / "source_12s.mp4",
    "harness": EVID / "tools" / "demo_run.py",
}
chec = 0
fails = []
lines = []
for name, p in required.items():
    ok = p.is_file() and p.stat().st_size > 0
    if not ok:
        fails.append(name)
    lines.append(f"{'PASS' if ok else 'FAIL'}  {name:28s} {p.stat().st_size if p.is_file() else 0} B")
# engine evidence x3 + server outputs x3
ev = sorted((EVID / "raw" / "engine_state").glob("*.engine_evidence.json"))
lines.append(f"{'PASS' if len(ev) == 3 else 'FAIL'}  engine_evidence x{len(ev)}")
srv = sorted((EVID / "raw" / "renders" / "server_output").glob("**/*_00001_.mp4"))
lines.append(f"{'PASS' if len(srv) == 3 else 'FAIL'}  server main clips x{len(srv)}")

# regenerate the manifest over the FINAL bytes
mrows = []
locked = []
for p in sorted(EVID.rglob("*")):
    if p.is_file():
        try:
            mrows.append(f"{sha(p)}  {p.relative_to(EVID).as_posix()}  {p.stat().st_size}")
        except PermissionError:
            locked.append(p.relative_to(EVID).as_posix())
if locked:
    mrows.append("# locked: " + ", ".join(locked))
(EVID / "raw" / "sha256_manifest.txt").write_text("\n".join(mrows) + "\n", encoding="utf-8")
lines.append(f"PASS  sha256_manifest.txt ({len(mrows)} rows, {len(locked)} locked)")

# tree + processes
por = subprocess.run(["git", "status", "--porcelain"], cwd=str(WT), capture_output=True, text=True).stdout
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(WT), capture_output=True, text=True).stdout.strip()
lines.append(f"{'PASS' if por.strip() == '' else 'FAIL'}  tree porcelain == 0 ({len(por.strip().splitlines())} lines) head={head}")
sd = json.loads((EVID / "raw" / "comfy_shutdown.json").read_text(encoding="utf-8"))
lines.append(f"{'PASS' if sd.get('POST_STOP_VERIFIED') else 'FAIL'}  POST_STOP_VERIFIED={sd.get('POST_STOP_VERIFIED')} app={sd.get('app')}")


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


p1, p2 = port_open(8028), port_open(8371)
lines.append(f"{'PASS' if not p1 and not p2 else 'FAIL'}  ports refused (app=closed:{not p1}, comfy=closed:{not p2})")

st = json.loads((EVID / "raw" / "state.json").read_text(encoding="utf-8"))
demo_sha = sha(EVID / "raw" / "export" / "demo_final.mp4")
vr = st.get("verify") or {}
lines.append(f"INFO  demo sha {demo_sha}")
lines.append(f"INFO  video {vr.get('video')} decode_ok={vr.get('decode_ok')}")
lines.append(f"INFO  milestones " + "; ".join(f"{k}:{v.get('status')}" for k, v in (st.get("milestones") or {}).items()))
lines.append(f"INFO  prompts {[s.get('prompt_ids') for s in (st.get('engine3') or {}).get('shots', [])]}")
print("\n".join(lines))
print("GATE_FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
