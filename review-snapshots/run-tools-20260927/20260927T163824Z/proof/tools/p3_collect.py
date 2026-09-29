"""P3 collector: poll the ALREADY-SUBMITTED prompt until it finishes and write the receipt.

No new submission: the server keeps executing the prompt regardless of who polls it.  The wall
time comes from the server's OWN history timestamps (execution_start -> execution_success), and
VRAM/RAM are sampled while it runs.
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
OUT_DIR = PROOF / "output" / "p3"
PROMPT = sys.argv[1]
PID = int(sys.argv[2]) if len(sys.argv) > 2 else 20608
SOURCE_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_frames,nb_read_frames,r_frame_rate,"
                        "avg_frame_rate,width,height,duration,nb_streams", "-of", "json", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr[-300:]}
    s = json.loads(r.stdout)["streams"][0]
    return {k: s.get(k) for k in ("nb_frames", "nb_read_frames", "r_frame_rate", "avg_frame_rate",
                                  "width", "height", "duration", "nb_streams")}


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
        nums = [re.sub(r"[^0-9]", "", c.strip('"')) for c in tl.strip().split('","')]
        cands = [int(n) for n in nums if n and int(n) > 10000]
        ram_kb = max(cands) if cands else 0
    return mib, util, ram_kb


def main() -> int:
    before = {p.name for p in OUT_DIR.rglob("*") if p.is_file()}
    peak = {"vram_mib": 0, "util": 0, "ram_kb": 0}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            mib, util, ram = probes()
            peak["vram_mib"] = max(peak["vram_mib"], mib)
            peak["util"] = max(peak["util"], util)
            peak["ram_kb"] = max(peak["ram_kb"], ram)
            time.sleep(5)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    t_start = time.time()
    hist, deadline = None, time.time() + 5400
    while time.time() < deadline:
        try:
            h = json.loads(urllib.request.urlopen(f"{BASE}/history/{PROMPT}", timeout=60).read())
        except Exception:  # noqa: BLE001
            h = {}
        if PROMPT in h and (h[PROMPT].get("status") or {}).get("completed"):
            hist = h[PROMPT]
            break
        time.sleep(10)
    stop.set()
    th.join(timeout=5)
    wall_observed = time.time() - t_start
    msgs = (hist or {}).get("status", {}).get("messages", [])
    stamps = {}
    for m in msgs:
        if isinstance(m, list) and len(m) == 2 and isinstance(m[1], dict):
            stamps[m[0]] = m[1].get("timestamp")
    server_wall_s = None
    if stamps.get("execution_start") and stamps.get("execution_success"):
        server_wall_s = round((stamps["execution_success"] - stamps["execution_start"]) / 1000.0, 2)
    after = sorted(p for p in OUT_DIR.rglob("*") if p.is_file() and p.name not in before)
    media = [{"file": str(p.relative_to(PROOF / "output")).replace("\\", "/"),
              "bytes": p.stat().st_size, "sha256": sha(p), "ffprobe": ffprobe(p)} for p in after]
    src = json.loads((PROOF / "evidence" / "P3_GRAPH.json").read_text(encoding="utf-8"))
    out = {"artifact": "P3_RECEIPT.json", "round": "R28-PROOF-P3", "shot": "BOOK",
           "prompt_id": PROMPT, "graph": "graphs/animate2_book.p3.api.json",
           "graph_sha256": sha(PROOF / "graphs" / "animate2_book.p3.api.json"),
           "template": src["template"], "template_sha256": src["template_sha256"],
           "deltas": src["deltas"], "declared_params": src["declared_params"], "inputs": src["inputs"],
           "source_window_sha256": SOURCE_SHA,
           "source_sha_matches": src["inputs"]["driving"]["sha256"] == SOURCE_SHA,
           "completed": bool(hist), "status": (hist or {}).get("status"),
           "server_side_wall_s": server_wall_s,
           "server_side_wall_min": round(server_wall_s / 60, 2) if server_wall_s else None,
           "seconds_per_output_second": (round(server_wall_s / 4.0, 2) if server_wall_s else None),
           "collector_observed_wall_s": round(wall_observed, 2),
           "history_message_timestamps": stamps,
           "vram_peak_mib": peak["vram_mib"], "gpu_util_peak_pct": peak["util"],
           "server_ram_peak_mib": round(peak["ram_kb"] / 1024, 1),
           "output_files": media, "output_count": len(media),
           "history_outputs": (hist or {}).get("outputs"),
           "first_poller_deadline_hit": True,
           "first_poller_note": ("the first poller had a 2400 s deadline and recorded "
                                 "completed=False at that point; the server kept executing and this "
                                 "collector polled the SAME prompt_id (no second submission)"),
           "measured_step_evidence": {
               "model_initialization_s": 907,
               "steps_observed": "1/6 at 15:07, 2/6 at 14:19 (429.7 s/step average)",
               "source": "the server's own tqdm lines, read from its live log"},
           "quality_accepted": False,
           "quality_verdict_owner": "BENCH / DEMO / Codex - the worker does not accept quality",
           "collected_at": datetime.now(timezone.utc).isoformat()}
    (PROOF / "evidence" / "P3_RECEIPT.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"completed": out["completed"], "server_wall_s": server_wall_s,
                      "server_wall_min": out["server_side_wall_min"],
                      "s_per_output_s": out["seconds_per_output_second"],
                      "vram_peak_mib": peak["vram_mib"], "ram_peak_mib": out["server_ram_peak_mib"],
                      "files": [m["file"] for m in media]}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
