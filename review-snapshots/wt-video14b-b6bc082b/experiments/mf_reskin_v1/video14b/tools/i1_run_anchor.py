"""MF-V1-VIDEO14B round I1 -- engine runner: submit one anchor graph and record the facts.

Every submission is a LEDGER ROW (append-only jsonl) so the round's generation budget can be
audited: <=3 anchors + <=1 diagnosed correction, and a correction row CARRYING a reason written
before the POST.  Per submission this tool records:

  * engine epoch (instance_id / pid / port) resolved from instance_epoch.json at submit time,
  * VRAM before, a 1 s VRAM sample trace while the prompt runs, VRAM after,
  * the prompt id, queue wait, execution start/end and the engine's own status messages,
  * the SERVER LOG SLICE written while that prompt ran (so the model load/unload lines belong
    to one request and can be quoted),
  * `/free {unload_models:true, free_memory:true}` before and after, with VRAM either side.

usage:
  python i1_run_anchor.py ready
  python i1_run_anchor.py post <graph.json> <shot> <attempt_tag> [--reason "..." ] [--unload-before]
  python i1_run_anchor.py unload <label>
  python i1_run_anchor.py vram <label>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8310"
RT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
STATE = RT / "state" / "roundI1"
LEDGER = STATE / "i1_prompt_ledger.jsonl"
SERVER_LOG = RT / "logs" / "server_gpu_i1.log"


def nvidia() -> dict:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()
    parts = [p.strip() for p in out.split(",")]
    d = {}
    for k, v in zip(("total_mib", "used_mib", "free_mib", "util_pct"), parts):
        d[k] = int("".join(ch for ch in v if ch.isdigit()) or 0)
    return d


def stats() -> dict:
    try:
        s = json.loads(urllib.request.urlopen(BASE + "/system_stats", timeout=10).read())
        dev = (s.get("devices") or [{}])[0]
        return {"vram_total_mib": dev.get("vram_total", 0) // (1 << 20),
                "vram_free_mib": dev.get("vram_free", 0) // (1 << 20),
                "torch_vram_total_mib": dev.get("torch_vram_total", 0) // (1 << 20),
                "torch_vram_free_mib": dev.get("torch_vram_free", 0) // (1 << 20)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def epoch() -> dict:
    return json.loads((RT / "instance_epoch.json").read_text(encoding="utf-8"))


def alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    return str(pid) in out


def ledger(row: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:          # APPEND ONLY: never truncate history
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def logsize() -> int:
    return SERVER_LOG.stat().st_size if SERVER_LOG.is_file() else 0


def logslice(start: int, path: Path) -> dict:
    raw = SERVER_LOG.read_bytes()
    chunk = raw[start:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(chunk)
    txt = chunk.decode("utf-8", "replace")
    return {"path": str(path), "start_offset": start, "end_offset": len(raw), "bytes": len(chunk),
            "load_lines": [ln.strip() for ln in txt.splitlines() if "Requested to load" in ln],
            "prepare_lines": [ln.strip() for ln in txt.splitlines() if "prepared for dynamic VRAM" in ln],
            "unload_lines": [ln.strip() for ln in txt.splitlines() if "unload" in ln.lower()]}


def post(graph: dict, client_id: str) -> dict:
    body = json.dumps({"prompt": graph, "client_id": client_id}).encode()
    req = urllib.request.Request(BASE + "/prompt", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return {"http": r.status, "body": json.loads(r.read())}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": json.loads(e.read() or b"{}")}


def free_memory() -> dict:
    before = {"nvidia": nvidia(), "stats": stats()}
    req = urllib.request.Request(BASE + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            code, txt = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, txt = e.code, e.read().decode()
    time.sleep(2)
    after = {"nvidia": nvidia(), "stats": stats()}
    return {"http": code, "body": txt[:200], "before": before, "after": after}


def wait_history(pid: str, timeout_s: int = 900, sample_s: float = 1.0) -> dict:
    t0 = time.time()
    samples = []
    while time.time() - t0 < timeout_s:
        samples.append({"t": round(time.time() - t0, 1), **nvidia()})
        try:
            h = json.loads(urllib.request.urlopen(BASE + f"/history/{pid}", timeout=15).read())
        except Exception:  # noqa: BLE001
            h = {}
        if pid in h:
            return {"history": h[pid], "wall_s": round(time.time() - t0, 2), "vram_samples": samples}
        time.sleep(sample_s)
    return {"history": None, "wall_s": round(time.time() - t0, 2), "vram_samples": samples,
            "timeout": True}


def summarize(h: dict) -> dict:
    msgs = ((h or {}).get("status") or {}).get("messages") or []
    times = {}
    for m in msgs:
        times[m[0]] = m[1].get("timestamp") if isinstance(m[1], dict) else None
    outs = []
    for nid, o in (h or {}).get("outputs", {}).items():
        for im in o.get("images", []) or []:
            outs.append({"node": nid, "filename": im.get("filename"), "subfolder": im.get("subfolder", ""),
                         "type": im.get("type")})
    return {"status_str": (h or {}).get("status", {}).get("status_str"),
            "completed": (h or {}).get("status", {}).get("completed"),
            "message_types": [m[0] for m in msgs], "message_times": times,
            "images": outs, "error": next((m[1] for m in msgs if m[0] == "execution_error"), None)}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ready"
    if cmd == "ready":
        ep = epoch()
        print(json.dumps({"epoch": ep, "pid_alive": alive(ep["pid"]), "stats": stats(),
                          "nvidia": nvidia(), "server_log_bytes": logsize()}, indent=1))
        return 0
    if cmd == "vram":
        label = sys.argv[2]
        row = {"ts": time.time(), "event": "vram_sample", "label": label,
               "nvidia": nvidia(), "stats": stats()}
        ledger(row)
        print(json.dumps(row, indent=1))
        return 0
    if cmd == "unload":
        label = sys.argv[2]
        res = free_memory()
        row = {"ts": time.time(), "event": "unload", "label": label, **res}
        ledger(row)
        print(json.dumps(row, indent=1))
        return 0
    if cmd == "post":
        gp, shot, tag = Path(sys.argv[2].replace("\\", "/")), sys.argv[3], sys.argv[4]
        reason = None
        unload_before = False
        if "--reason" in sys.argv:
            reason = sys.argv[sys.argv.index("--reason") + 1]
        if "--unload-before" in sys.argv:
            unload_before = True
        graph = json.loads(gp.read_text(encoding="utf-8"))
        ep = epoch()
        if not alive(ep["pid"]):
            print(json.dumps({"REFUSED": "engine pid is not alive", "epoch": ep}, indent=1))
            return 3
        pre_unload = free_memory() if unload_before else None
        vram_before = {"nvidia": nvidia(), "stats": stats()}
        client_id = f"i1-{shot}-{tag}"
        s0 = logsize()
        t_post = time.time()
        res = post(graph, client_id)
        pid = (res.get("body") or {}).get("prompt_id")
        row = {"ts": t_post, "event": "post", "shot": shot, "attempt_tag": tag, "reason": reason,
               "graph": str(gp), "graph_sha256": __import__("hashlib").sha256(gp.read_bytes()).hexdigest(),
               "client_id": client_id, "epoch": {"instance_id": ep["instance_id"], "pid": ep["pid"], "port": ep["port"]},
               "http": res["http"], "prompt_id": pid, "post_body": res["body"] if pid is None else None,
               "vram_before": vram_before, "pre_unload": pre_unload, "client_id_tag": client_id}
        if pid is None:
            row["result"] = "REJECTED_AT_SUBMIT"
            row["log"] = logslice(s0, STATE / f"logslice_{shot}_{tag}_rejected.log")
            ledger(row)
            print(json.dumps(row, indent=1, ensure_ascii=False))
            return 4
        w = wait_history(pid)
        summ = summarize(w["history"])
        vram_after = {"nvidia": nvidia(), "stats": stats()}
        hp = STATE / f"history_{shot}_{tag}.json"
        hp.write_text(json.dumps(w["history"], indent=1, ensure_ascii=False), encoding="utf-8")
        ls = logslice(s0, STATE / f"logslice_{shot}_{tag}.log")
        row.update({"result": "DONE" if summ["status_str"] == "success" else summ["status_str"],
                    "queue_wait_s": round((summ["message_times"].get("execution_start") or 0) - t_post, 2),
                    "exec_s": round((summ["message_times"].get("execution_success") or 0)
                                    - (summ["message_times"].get("execution_start") or 0), 2),
                    "engine_wall_s": w["wall_s"], "summary": summ,
                    "history_json": str(hp), "vram_after": vram_after, "log": ls,
                    "vram_sample_peak_mib": max((s["used_mib"] for s in w["vram_samples"]), default=0),
                    "vram_samples": w["vram_samples"]})
        ledger(row)
        print(json.dumps({k: v for k, v in row.items() if k != "vram_samples"}, indent=1, ensure_ascii=False))
        return 0 if row["result"] == "DONE" else 5
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
