"""Sequential runner for the P5/P6 batch: TURN, OCC, BOOK-overlap16, BOOK-nocache.

One job in flight at any moment (the loop awaits each before submitting the next).  Per job the
receipt records the server's own execution timestamps, the VRAM peak sampled during that job only,
the produced files with sha256/ffprobe, and the graph sha that produced them.
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
EVID = PROOF / "evidence"
BASE = "http://127.0.0.1:8321"
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
PQI = 0x1000
JOBS = [
    ("TURN", "graphs/animate2_turn.p5.api.json", "output/p5_turn", "P5_TURN_RECEIPT.json", 2026092801),
    ("OCC", "graphs/animate2_occ.p5.api.json", "output/p5_occ", "P5_OCC_RECEIPT.json", 2026092802),
    ("BOOK_OV16", "graphs/animate2_book.p5overlap16.api.json", "output/p5_book_overlap16",
     "P5_OVERLAP_RECEIPT.json", 582699151003550),
    ("BOOK_NOCACHE", "graphs/animate2_book.p6nocache.api.json", "output/p6_book_nocache",
     "P6_NOCACHE_RECEIPT.json", 582699151003550),
]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def ram_mib(pid):
    h = ctypes.windll.kernel32.OpenProcess(PQI, False, pid)
    if not h:
        return None
    try:
        c = PMC()
        c.cb = ctypes.sizeof(c)
        return (round(c.WorkingSetSize / (1 << 20), 1)
                if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else None)
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


def run_job(name, graph_rel, out_rel, receipt_name, seed):
    gpath = PROOF / graph_rel
    graph = json.loads(gpath.read_text(encoding="utf-8"))
    outdir = PROOF / out_rel
    outdir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in outdir.rglob("*") if p.is_file()}
    peak = {"vram": 0, "util": 0, "ram": 0.0, "n": 0}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            m, u = vram()
            peak["vram"] = max(peak["vram"], m)
            peak["util"] = max(peak["util"], u)
            r = ram_mib(PID)
            if r is not None:
                peak["ram"] = max(peak["ram"], r)
                peak["n"] += 1
            time.sleep(3)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
        {"prompt": graph, "client_id": f"mf-{name.lower()}"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        pid_ = json.loads(r.read())["prompt_id"]
    print(f"[{name}] prompt_id {pid_}", flush=True)
    hist, deadline = None, time.time() + 7200
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
    wall = (round((stamps["execution_success"] - stamps["execution_start"]) / 1000.0, 2)
            if stamps.get("execution_success") and stamps.get("execution_start") else None)
    after = sorted(p for p in outdir.rglob("*") if p.is_file() and p.name not in before)
    media = [{"file": str(p.relative_to(PROOF / "output")).replace("\\", "/"),
              "bytes": p.stat().st_size, "sha256": sha(p), "ffprobe": ffprobe(p)} for p in after]
    rec = {"artifact": receipt_name, "job": name, "graph": graph_rel,
           "graph_sha256": sha(gpath), "seed": seed, "prompt_id": pid_,
           "completed": bool(hist), "status": (hist or {}).get("status"),
           "server_side_wall_s": wall,
           "seconds_per_output_second": round(wall / 4.0, 2) if wall else None,
           "vram_peak_mib": peak["vram"], "gpu_util_peak_pct": peak["util"],
           "server_ram_peak_mib": peak["ram"] if peak["n"] else None,
           "ram_sample_count": peak["n"],
           "output_files": media, "output_count": len(media),
           "quality_accepted": False,
           "quality_verdict_owner": "BENCH / DEMO / Codex - the worker does not accept quality",
           "at": datetime.now(timezone.utc).isoformat()}
    (EVID / receipt_name).write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    print(f"[{name}] completed={bool(hist)} wall={wall}s vram={peak['vram']}MiB "
          f"files={[m['file'] for m in media]}", flush=True)
    return rec


def main() -> int:
    out = {"artifact": "P567_RUNS.json", "jobs": {}}
    for name, graph_rel, out_rel, receipt, seed in JOBS:
        try:
            out["jobs"][name] = run_job(name, graph_rel, out_rel, receipt, seed)
        except Exception as e:  # noqa: BLE001
            out["jobs"][name] = {"job": name, "error": repr(e)[:400], "completed": False}
            print(f"[{name}] ERROR {e!r}", flush=True)
    (EVID / "P567_RUNS.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    print(json.dumps({k: {"completed": v.get("completed"), "wall": v.get("server_side_wall_s"),
                          "files": len(v.get("output_files", []))}
                      for k, v in out["jobs"].items()}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
