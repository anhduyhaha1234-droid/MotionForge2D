"""P3 step 2: one Wan Animate 2 BOOK submission on the isolated GPU server.

Measures wall time, peak VRAM (nvidia-smi) and the server process's RAM (tasklist), collects the
produced media, and runs the decode checks (frame count / fps / PTS vs the pinned source span).
No quality verdict is produced here - that belongs to BENCH/DEMO/Codex.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
PORT = 8321
BASE = f"http://127.0.0.1:{PORT}"
OUT_DIR = PROOF / "output" / "p3"
PID = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 20608
SOURCE_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_frames,r_frame_rate,avg_frame_rate,width,height,duration,"
                        "start_time,time_base,nb_read_frames", "-count_frames", "-of", "json",
                        str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr[-300:]}
    s = json.loads(r.stdout)["streams"][0]
    return {k: s.get(k) for k in ("nb_frames", "nb_read_frames", "r_frame_rate", "avg_frame_rate",
                                  "width", "height", "duration", "start_time", "time_base")}


def probes():
    g = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    mib, util = 0, 0
    for line in g.strip().splitlines():
        parts = [re.sub(r"[^0-9]", "", x) for x in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            mib, util = max(mib, int(parts[0])), max(util, int(parts[1] or 0))
    tl = subprocess.run(["tasklist", "/FI", f"PID eq {PID}", "/FO", "CSV", "/NH"],
                        capture_output=True, text=True).stdout
    ram_kb = 0
    if "python" in tl.lower():
        cols = [c.strip('"') for c in tl.strip().split('","')]
        nums = [re.sub(r"[^0-9]", "", c) for c in cols]
        cands = [int(n) for n in nums if n and int(n) > 10000]
        ram_kb = max(cands) if cands else 0
    return mib, util, ram_kb


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    graph = json.loads((PROOF / "graphs" / "animate2_book.p3.api.json").read_text(encoding="utf-8"))
    before = {p.name for p in OUT_DIR.rglob("*") if p.is_file()}
    peak = {"vram_mib": 0, "util": 0, "ram_kb": 0}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            mib, util, ram = probes()
            peak["vram_mib"] = max(peak["vram_mib"], mib)
            peak["util"] = max(peak["util"], util)
            peak["ram_kb"] = max(peak["ram_kb"], ram)
            time.sleep(2)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    t0 = time.time()
    req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
        {"prompt": graph, "client_id": "mf-p3-book"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        submitted = json.loads(r.read())
    pid_ = submitted["prompt_id"]
    print("prompt_id", pid_, flush=True)
    hist, deadline = None, time.time() + 2400
    while time.time() < deadline:
        try:
            h = json.loads(urllib.request.urlopen(f"{BASE}/history/{pid_}", timeout=60).read())
        except Exception:  # noqa: BLE001
            h = {}
        if pid_ in h and (h[pid_].get("status") or {}).get("completed"):
            hist = h[pid_]
            break
        time.sleep(5)
    stop.set()
    th.join(timeout=5)
    wall = time.time() - t0
    after = sorted(p for p in OUT_DIR.rglob("*") if p.is_file() and p.name not in before)
    media = [{"file": str(p.relative_to(PROOF / "output")).replace("\\", "/"),
              "bytes": p.stat().st_size, "sha256": sha(p), "ffprobe": ffprobe(p)} for p in after]
    src = json.loads((PROOF / "evidence" / "P3_GRAPH.json").read_text(encoding="utf-8"))
    out = {"artifact": "P3_RECEIPT.json", "round": "R28-PROOF-P3", "shot": "BOOK",
           "prompt_id": pid_, "graph": "graphs/animate2_book.p3.api.json",
           "graph_sha256": sha(PROOF / "graphs" / "animate2_book.p3.api.json"),
           "template": src["template"], "template_sha256": src["template_sha256"],
           "deltas": src["deltas"], "declared_params": src["declared_params"],
           "inputs": src["inputs"], "source_window_sha256": SOURCE_SHA,
           "source_sha_matches": src["inputs"]["driving"]["sha256"] == SOURCE_SHA,
           "completed": bool(hist), "status": (hist or {}).get("status"),
           "wall_s": round(wall, 2), "wall_min": round(wall / 60, 2),
           "seconds_per_output_second": round(wall / 4.0, 2),
           "vram_peak_mib": peak["vram_mib"], "gpu_util_peak_pct": peak["util"],
           "server_ram_peak_mib": round(peak["ram_kb"] / 1024, 1),
           "output_files": media, "output_count": len(media),
           "history_outputs": (hist or {}).get("outputs"),
           "decode_check": {"expected_frames": 120, "expected_fps": "30/1",
                            "expected_duration_s": 4.0,
                            "measured": [m["ffprobe"] for m in media]},
           "quality_accepted": False,
           "quality_verdict_owner": "BENCH / DEMO / Codex - the worker does not accept quality",
           "submitted_at": datetime.now(timezone.utc).isoformat()}
    (PROOF / "evidence" / "P3_RECEIPT.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"completed": out["completed"], "wall_s": out["wall_s"],
                      "vram_peak_mib": peak["vram_mib"], "ram_peak_mib": out["server_ram_peak_mib"],
                      "files": [m["file"] for m in media]}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
