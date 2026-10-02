"""P3b submit: one BOOK baseline submission with the geometry fix (seed unchanged).

Differences vs the P3 submit script:
  * reads graphs/animate2_book.p3b.api.json, writes output/p3b + evidence/P3B_RECEIPT.json
  * RAM is sampled with the Windows API (ctypes GetProcessMemoryInfo) because the tasklist column
    parse returned 0 last time - a measurement that fails must not be reported as a number
  * deadline 5400 s: the P3 run took 2387.78 s server-side and only just beat the old 2400 s limit
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
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
OUT_DIR = PROOF / "output" / "p3b"
GRAPH = PROOF / "graphs" / "animate2_book.p3b.api.json"
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 0

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def ram_mib(pid: int):
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        c = PROCESS_MEMORY_COUNTERS()
        c.cb = ctypes.sizeof(c)
        if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return round(c.WorkingSetSize / (1 << 20), 1)
        return None
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate,duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0] if r.returncode == 0 else {"error": r.stderr[-200:]}


def vram():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    mib = util = 0
    for line in out.strip().splitlines():
        parts = [re.sub(r"[^0-9]", "", x) for x in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            mib, util = max(mib, int(parts[0])), max(util, int(parts[1] or 0))
    return mib, util


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    before = {p.name for p in OUT_DIR.rglob("*") if p.is_file()}
    peak = {"vram": 0, "util": 0, "ram": 0.0, "ram_samples": 0}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            m, u = vram()
            peak["vram"] = max(peak["vram"], m)
            peak["util"] = max(peak["util"], u)
            r = ram_mib(PID)
            if r is not None:
                peak["ram"] = max(peak["ram"], r)
                peak["ram_samples"] += 1
            time.sleep(3)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
        {"prompt": graph, "client_id": "mf-p3b-book"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        submitted = json.loads(r.read())
    pid_ = submitted["prompt_id"]
    print("prompt_id", pid_, flush=True)
    hist, deadline = None, time.time() + 5400
    while time.time() < deadline:
        try:
            h = json.loads(urllib.request.urlopen(f"{BASE}/history/{pid_}", timeout=60).read())
        except Exception:  # noqa: BLE001
            h = {}
        if pid_ in h and (h[pid_].get("status") or {}).get("completed"):
            hist = h[pid_]
            break
        time.sleep(10)
    stop.set()
    th.join(timeout=5)
    msgs = (hist or {}).get("status", {}).get("messages", [])
    stamps = {m[0]: m[1].get("timestamp") for m in msgs
              if isinstance(m, list) and len(m) == 2 and isinstance(m[1], dict)}
    server_wall = (round((stamps["execution_success"] - stamps["execution_start"]) / 1000.0, 2)
                   if stamps.get("execution_success") and stamps.get("execution_start") else None)
    after = sorted(p for p in OUT_DIR.rglob("*") if p.is_file() and p.name not in before)
    media = [{"file": str(p.relative_to(PROOF / "output")).replace("\\", "/"),
              "bytes": p.stat().st_size, "sha256": sha(p), "ffprobe": ffprobe(p)} for p in after]
    g3b = json.loads((PROOF / "evidence" / "P3B_GRAPH.json").read_text(encoding="utf-8"))
    g3 = json.loads((PROOF / "evidence" / "P3_GRAPH.json").read_text(encoding="utf-8"))
    out = {"artifact": "P3B_RECEIPT.json", "round": "R28-PROOF-P3B", "shot": "BOOK",
           "prompt_id": pid_, "graph": "graphs/animate2_book.p3b.api.json",
           "graph_sha256": sha(GRAPH), "graph_diff_vs_p3": {
               "added": list(g3b["added"]), "rewired": g3b["rewired"], "removed": g3b["removed"]},
           "template": g3["template"], "template_sha256": g3["template_sha256"],
           "deltas_vs_template": g3["deltas"], "declared_params": g3["declared_params"],
           "inputs": g3["inputs"], "completed": bool(hist),
           "status": (hist or {}).get("status"), "server_side_wall_s": server_wall,
           "server_side_wall_min": round(server_wall / 60, 2) if server_wall else None,
           "seconds_per_output_second": round(server_wall / 4.0, 2) if server_wall else None,
           "vram_peak_mib": peak["vram"], "gpu_util_peak_pct": peak["util"],
           "server_ram_peak_mib": peak["ram"] if peak["ram_samples"] else None,
           "ram_sample_count": peak["ram_samples"],
           "output_files": media, "output_count": len(media),
           "expected_dims": [640, 368], "quality_accepted": False,
           "quality_verdict_owner": "BENCH / DEMO / Codex - the worker does not accept quality",
           "submitted_at": datetime.now(timezone.utc).isoformat()}
    (PROOF / "evidence" / "P3B_RECEIPT.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"completed": out["completed"], "server_wall_s": server_wall,
                      "s_per_output_s": out["seconds_per_output_second"],
                      "vram_peak_mib": peak["vram"], "ram_peak_mib": out["server_ram_peak_mib"],
                      "files": {m["file"]: m["ffprobe"] for m in media}}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
