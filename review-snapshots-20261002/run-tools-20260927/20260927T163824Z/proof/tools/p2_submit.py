"""P2 step 2: submit the three anchor graphs to the isolated GPU server, one job at a time.

Per job: POST /prompt -> poll /history/<id> -> collect the PNG -> receipt with prompt_id, wall
time, peak VRAM (sampled by a second thread), output path/size/sha256/dims.  One prompt in flight
at any moment (the packet's 1-job-at-a-time rule is enforced by construction: the loop awaits).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
PORT = 8321
BASE = f"http://127.0.0.1:{PORT}"
OUT_DIR = PROOF / "output" / "anchors"
SHOTS = ("BOOK", "TURN", "OCC")
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
LAUNCH_ARGV = ("<venv>/python.exe -u main.py --listen 127.0.0.1 --port 8321 "
               "--base-directory <runtime/video14b> --reserve-vram 1.0 --disable-auto-launch "
               "--input-directory <PROOF>/inputs --output-directory <PROOF>/output "
               "--temp-directory <PROOF>/temp --user-directory <PROOF>/user")
WHY_BASE_DIRECTORY = ("the real model roots live in the SIBLING runtime/video14b/models (research "
                      "§1) and only appear when --base-directory points there; the first launch "
                      "without it was rejected by /prompt with 'unet_name ... not in []' - "
                      "measured, not guessed, and recorded in the P2 receipt")


def post(path: str, payload: dict, timeout: int = 120):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get(path: str, timeout: int = 60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.read()


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def vram_mib():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True,
                         text=True).stdout.strip().splitlines()
    vals = []
    for line in out:
        parts = [re.sub(r"[^0-9]", "", x) for x in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            vals.append((int(parts[0]), int(parts[1] or 0)))
    return vals


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # --- wait for the server ---------------------------------------------------------------
    stats = None
    for _ in range(90):
        try:
            stats = json.loads(get("/system_stats"))
            break
        except Exception:  # noqa: BLE001
            time.sleep(3)
    assert stats, "server never answered"
    dev = (stats.get("devices") or [{}])[0]
    epoch = {"instance_id": hashlib.sha256(f"{time.time()}:{PORT}:{PID}".encode())
             .hexdigest()[:32], "launched_at": time.time(), "port": PORT, "pid": PID,
             "base_url": BASE, "device": dev.get("name"), "vram_total_mib": dev.get("vram_total"),
             "python": "venv 3.11.9", "launch_argv": LAUNCH_ARGV,
             "why_base_directory": WHY_BASE_DIRECTORY,
             "reserve_vram_gb": 1.0}
    (PROOF / "evidence" / "P2_instance_epoch.json").write_text(
        json.dumps(epoch, indent=1), encoding="utf-8")

    receipts = {"artifact": "P2_ANCHOR_RECEIPTS.json", "round": "R28-PROOF-P2",
                "one_job_at_a_time": True, "epoch": epoch,
                "gpu_before": vram_mib(), "jobs": {}}
    for shot in SHOTS:
        gpath = PROOF / "graphs" / f"anchor_{shot.lower()}.p2.api.json"
        graph = json.loads(gpath.read_text(encoding="utf-8"))
        peak = {"mib": 0, "util": 0}
        stop = threading.Event()

        def sample():
            while not stop.is_set():
                for mib, util in vram_mib():
                    peak["mib"] = max(peak["mib"], mib)
                    peak["util"] = max(peak["util"], util)
                time.sleep(2)

        th = threading.Thread(target=sample, daemon=True)
        t0 = time.time()
        th.start()
        submitted = post("/prompt", {"prompt": graph, "client_id": f"mf-p2-{shot.lower()}"})
        pid_ = submitted["prompt_id"]
        hist = None
        deadline = time.time() + 1500
        while time.time() < deadline:
            try:
                h = json.loads(get(f"/history/{pid_}"))
            except Exception:  # noqa: BLE001
                h = {}
            if pid_ in h and h[pid_].get("status", {}).get("completed"):
                hist = h[pid_]
                break
            time.sleep(3)
        stop.set()
        th.join(timeout=5)
        wall = time.time() - t0
        outputs = []
        if hist:
            for nid, imgs in (hist.get("outputs") or {}).items():
                for im in imgs.get("images", []):
                    p = OUT_DIR / im["filename"]
                    if p.is_file():
                        from PIL import Image
                        with Image.open(p) as im_:
                            dims = list(im_.size)
                        outputs.append({"node": nid, "file": p.name, "bytes": p.stat().st_size,
                                        "sha256": sha(p), "dims": dims})
        receipts["jobs"][shot] = {
            "prompt_id": pid_, "graph": f"graphs/anchor_{shot.lower()}.p2.api.json",
            "graph_sha256": sha(gpath), "submitted_at": datetime.now(timezone.utc).isoformat(),
            "wall_s": round(wall, 2), "completed": bool(hist),
            "status": (hist or {}).get("status"),
            "queue_remaining_after": json.loads(get("/queue")).get("exec_info", {}).get(
                "queue_remaining"),
            "vram_peak_mib": peak["mib"], "gpu_util_peak_pct": peak["util"],
            "outputs": outputs, "output_count": len(outputs),
            "raw_history_keys": sorted((hist or {}).keys()),
        }
        print(f"{shot}: prompt {pid_} completed={bool(hist)} wall {wall:.1f}s "
              f"vram_peak {peak['mib']} MiB outputs {len(outputs)}", flush=True)
        if not hist:
            print("  NOT COMPLETED within the deadline - stopping the loop", flush=True)
            break
    (PROOF / "evidence" / "P2_ANCHOR_RECEIPTS.json").write_text(
        json.dumps(receipts, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: {"completed": v["completed"], "wall_s": v["wall_s"],
                          "outputs": [o["file"] for o in v["outputs"]]}
                      for k, v in receipts["jobs"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
