"""MF-END-08 — the REAL run: isolated ComfyUI server, one GPU inference job + one CPU-only
prefix (tensor-preview) job, then a proven clean shutdown.

Protocol copied from the accepted proof (R28 P2/P3):
  * isolated server: own base-directory (input/output/temp/user under MF-END-08),
    --models-directory pointing at the shared read-only model root, own port,
    --reserve-vram 1.0, --disable-auto-launch;
  * one job at a time: submit -> /history -> download output -> (next job) -> shutdown;
  * receipts carry pid/port/epoch, wall time, VRAM peak, output files + sha256;
  * shutdown = stop ONLY this process, then prove the port refuses (10061) and the pid is gone.

The prefix job loads NO model (it stops at the reference intake), so the only GPU inference
is the declared single golden job.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-08")
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
SRC = RT / "ComfyUI"
VENV_PY = RT / "venv/Scripts/python.exe"
BASE = EV / "runtime"
PORT = 8341
BASE_URL = f"http://127.0.0.1:{PORT}"
PROOF_DERIVED = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                     "mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B/"
                     "derived_inference_input/i1d_cast_dan_choi_standing_on_neutral_bg.png")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def http_json(path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_bytes(path: str, timeout: int = 120) -> bytes:
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return r.read()


def port_state() -> dict:
    s = socket.socket()
    s.settimeout(2.0)
    try:
        s.connect(("127.0.0.1", PORT))
        s.close()
        return {"listening": True, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"listening": False, "error": repr(e), "errno": getattr(e, "errno", None)}


def nvidia() -> list[int]:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    rows = []
    for line in out.strip().splitlines():
        parts = [int(x.strip()) for x in line.split(",")]
        rows += parts
    return rows


class VramSampler(threading.Thread):
    def __init__(self, period: float = 0.7):
        super().__init__(daemon=True)
        self.period, self.samples, self.stop_flag = period, [], False

    def run(self) -> None:
        while not self.stop_flag:
            try:
                self.samples.append(nvidia())
            except Exception:  # noqa: BLE001
                pass
            time.sleep(self.period)


def wait_history(prompt_id: str, timeout_s: float) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            h = http_json(f"/history/{prompt_id}")
        except Exception:  # noqa: BLE001
            time.sleep(2)
            continue
        if prompt_id in h:
            return h[prompt_id]
        time.sleep(1.5)
    raise TimeoutError(f"history for {prompt_id} not complete within {timeout_s}s")


def collect_outputs(hist: dict) -> list[dict]:
    files = []
    for node, out in (hist.get("outputs") or {}).items():
        for img in out.get("images", []) or []:
            q = urllib.parse.urlencode({"filename": img["filename"],
                                        "subfolder": img.get("subfolder", ""),
                                        "type": img.get("type", "output")})
            data = http_bytes("/view?" + q)
            files.append({"node": node, "filename": img["filename"],
                          "subfolder": img.get("subfolder", ""), "type": img.get("type", "output"),
                          "bytes": len(data), "sha256": sha256_bytes(data), "_data": data})
    return files


def run_job(name: str, graph: dict, timeout_s: float, sampler: VramSampler | None) -> dict:
    t_submit = time.time()
    sub = http_json("/prompt", {"prompt": graph, "client_id": f"mf-end-08-{name}"})
    pid = sub["prompt_id"]
    try:
        hist = wait_history(pid, timeout_s)
    except TimeoutError as e:
        hist = {"status": {"status_str": "timeout", "completed": False, "messages": [[repr(e), {}]]}}
    wall = time.time() - t_submit
    status = hist.get("status", {})
    rec = {"job": name, "prompt_id": pid, "submitted_at_unix": t_submit,
           "wall_s": round(wall, 3),
           "graph_object_sha256": sha256_bytes(json.dumps(
               graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
           "status_str": status.get("status_str"), "completed": bool(status.get("completed")),
           "messages": status.get("messages"),
           "queue_remaining_after": _queue_remaining()}
    if status.get("completed"):
        files = collect_outputs(hist)
        rec["outputs"] = [{k: v for k, v in f.items() if k != "_data"} for f in files]
        rec["_files"] = {f["filename"]: f["_data"] for f in files}
    else:
        # pull the queue/error surface for the record
        try:
            rec["queue_dump"] = http_json("/queue")
        except Exception as e:  # noqa: BLE001
            rec["queue_dump"] = repr(e)
    return rec


def _queue_remaining() -> int | None:
    try:
        q = http_json("/queue")
        return len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
    except Exception:  # noqa: BLE001
        return None


def prefix_graph(doc: dict) -> dict:
    g = doc["graph"]
    keep = ["REF_LOAD", "REF_SIZE", "REF_BG", "REF_INVERT", "REF_COMP", "REF_RESIZE"]
    out = {k: json.loads(json.dumps(g[k])) for k in keep}
    out["PREVIEW_COMP"] = {"class_type": "SaveImage",
                           "inputs": {"filename_prefix": "mf_reference_asset_v1/tensor_preview/ref_composite",
                                      "images": ["REF_COMP", 0]}}
    out["PREVIEW_RESIZED"] = {"class_type": "SaveImage",
                              "inputs": {"filename_prefix": "mf_reference_asset_v1/tensor_preview/ref_resized",
                                         "images": ["REF_RESIZE", 0]}}
    return out


def main() -> int:
    for sub in ("input", "output", "temp", "user", "custom_nodes"):
        (BASE / sub).mkdir(parents=True, exist_ok=True)
    rec: dict = {"artifact": "run_record.json", "port": PORT,
                 "runtime": {"comfyui_dir": str(SRC).replace("\\", "/"),
                             "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=SRC,
                                                    capture_output=True, text=True).stdout.strip()},
                 "base_directory": str(BASE).replace("\\", "/"),
                 "models_directory": str(RT / "models").replace("\\", "/"),
                 "gpu_before": nvidia(), "port_before": port_state()}
    log = open(BASE / "server.log", "ab")
    argv = [str(VENV_PY), "-u", str(SRC / "main.py"), "--listen", "127.0.0.1", "--port", str(PORT),
            "--base-directory", str(BASE), "--models-directory", str(RT / "models"),
            "--input-directory", str(BASE / "input"), "--output-directory", str(BASE / "output"),
            "--temp-directory", str(BASE / "temp"), "--user-directory", str(BASE / "user"),
            "--reserve-vram", "1.0", "--disable-auto-launch"]
    rec["launch_argv"] = [a.replace(str(EV), "<MF-END-08>").replace(str(RT), "<runtime/video14b>")
                          for a in argv]
    launched = time.time()
    proc = subprocess.Popen(argv, cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)
    rec["epoch"] = {"instance_id": uuid.uuid4().hex, "pid": proc.pid, "port": PORT,
                    "launched_at_unix": launched,
                    "launched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(launched))}
    j1 = j2 = None
    err = None
    sampler = VramSampler()
    sampler.start()
    try:
        # readiness
        t0 = time.time()
        stats = None
        while time.time() - t0 < 300:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited early rc={proc.returncode}")
            try:
                stats = http_json("/system_stats", timeout=5)
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        if stats is None:
            raise RuntimeError("server did not become ready within 300s")
        rec["ready_after_s"] = round(time.time() - t0, 2)
        rec["system_stats"] = stats
        rec["epoch"]["device"] = json.dumps(stats.get("devices", []))[:300]

        # live object_info against MY input dir + validate the delivered graph
        oi = http_json("/object_info", timeout=120)
        (EV / "raw/object_info_live.json").write_text(json.dumps(oi), encoding="utf-8")
        rec["object_info_nodes"] = len(oi)
        rec["object_info_loadimage_inputs"] = sorted(
            oi["LoadImage"]["input"]["required"]["image"][0])[:20]
        sys.path.insert(0, str(EV / "tools"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mf_end_08_test", WT / "tests/product_delivery/test_mf_end_08.py")
        tmod = importlib.util.module_from_spec(spec)
        sys.modules["mf_end_08_test"] = tmod
        spec.loader.exec_module(tmod)
        doc = json.loads((WT / "app/media_workflows/reference_asset_v1.json").read_text(encoding="utf-8"))
        rep = tmod.validate_graph(doc["graph"], oi, ("SAVE",))
        rec["live_validation"] = rep
        if rep["errors"]:
            raise RuntimeError(f"live validation failed: {rep['errors']}")

        # job 1: CPU-only prefix (tensor preview) — no model nodes in this graph
        pf = prefix_graph(doc)
        j1 = run_job("prefix_tensor_preview", pf, 300, sampler)
        rec["prefix_job"] = j1
        if not j1["completed"]:
            raise RuntimeError("prefix job did not complete")

        # job 2: the declared single GPU inference job (the delivered golden graph)
        j2 = run_job("golden_reference_asset", doc["graph"], 900, sampler)
        rec["golden_job"] = j2
    except Exception as e:  # noqa: BLE001
        err = repr(e)
        rec["error"] = err
    finally:
        sampler.stop_flag = True
        try:
            sampler.join(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        peaks = [max(s[i] for s in sampler.samples) if sampler.samples else None
                 for i in range(2)]
        rec["vram_peak_mib"], rec["gpu_util_peak_pct"] = peaks[0], peaks[1]
        # clean shutdown: stop ONLY the pid this run launched
        pre = port_state()
        alive = proc.poll()
        if alive is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=20)
        time.sleep(2)
        post = port_state()
        tasklist = subprocess.run(["tasklist", "/FI", f"PID eq {proc.pid}"],
                                  capture_output=True, text=True).stdout
        rec["shutdown"] = {"phase": "POST_STOP_VERIFIED" if not post["listening"] else "STILL_UP",
                           "pid": proc.pid, "pre": pre, "post": post,
                           "pid_exists": str(proc.pid) in tasklist,
                           "tasklist_row": tasklist.strip().splitlines()[-1] if tasklist else "",
                           "stop_scope": "ONLY the pid this run launched (Popen handle)"}
        log.close()
        rec["gpu_after"] = nvidia()

    # pixel comparisons for the prefix job (the tensor-truth preview)
    staged = json.loads((EV / "raw/stage_input.json").read_text(encoding="utf-8"))
    exp = staged["tensor_preview_expected"]
    files = (j1 or {}).get("_files", {})
    import numpy as np
    from PIL import Image
    import io as _io
    cmp_rows = {}
    for tag, key in (("composite", "ref_composite_00001_.png"),
                     ("resized", "ref_resized_00001_.png")):
        data = files.get(key)
        if data is None:
            cmp_rows[tag] = {"missing": key}
            continue
        img = np.asarray(Image.open(_io.BytesIO(data)).convert("RGB")).astype("int32")
        cmp_rows[tag] = {"file": key, "dims": [int(img.shape[1]), int(img.shape[0])],
                         "pixels_sha256": sha256_bytes(img.astype("uint8").tobytes())}
        if tag == "composite":
            want_sha = exp["composite_display_pixels_sha256"]
            cmp_rows[tag]["expected_pixels_sha256"] = want_sha
            cmp_rows[tag]["pixels_match_offline_expectation"] = (
                cmp_rows[tag]["pixels_sha256"] == want_sha)
            if PROOF_DERIVED.exists():
                pv = np.asarray(Image.open(PROOF_DERIVED).convert("RGB")).astype("int32")
                d = np.abs(pv - img)
                cmp_rows[tag]["proof_derived_delta"] = {
                    "differing_pixels": int((d.sum(axis=2) > 0).sum()),
                    "max_abs_delta_0_255": int(d.max())}
        else:
            want_sha = exp["resized_display_pixels_sha256"]
            cmp_rows[tag]["expected_pixels_sha256"] = want_sha
            cmp_rows[tag]["expected_dims"] = exp["resized_display_dims"]
            cmp_rows[tag]["pixels_match_offline_expectation"] = (
                cmp_rows[tag]["pixels_sha256"] == want_sha)
    rec["tensor_preview_comparison"] = cmp_rows

    # freeze the golden asset bytes into the evidence root
    afiles = (j2 or {}).get("_files", {})
    if afiles:
        asset_dir = EV / "asset"
        asset_dir.mkdir(parents=True, exist_ok=True)
        frozen = []
        for name, data in afiles.items():
            p = asset_dir / name
            p.write_bytes(data)
            frozen.append({"file": name, "path": str(p).replace("\\", "/"),
                           "bytes": len(data), "sha256": sha256_bytes(data)})
        rec["frozen_asset_files"] = frozen
        main_png = [f for f in frozen if f["file"].endswith(".png")]
        if main_png:
            im = Image.open(main_png[0]["path"])
            rec["golden_asset"] = {"file": main_png[0]["file"], "path": main_png[0]["path"],
                                   "bytes": main_png[0]["bytes"], "sha256": main_png[0]["sha256"],
                                   "dims": list(im.size), "mode": im.mode}
    for r in (rec.get("prefix_job"), rec.get("golden_job")):
        if r:
            r.pop("_files", None)
    (EV / "raw/run_record.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    print(json.dumps({k: v for k, v in rec.items()
                      if k in ("epoch", "ready_after_s", "object_info_nodes",
                               "live_validation", "prefix_job", "golden_job", "vram_peak_mib",
                               "gpu_util_peak_pct", "shutdown", "tensor_preview_comparison",
                               "golden_asset", "gpu_before", "gpu_after")},
                     indent=1, ensure_ascii=False)[:6000])
    ok = (err is None
          and rec.get("golden_job", {}).get("completed")
          and rec.get("shutdown", {}).get("phase") == "POST_STOP_VERIFIED"
          and rec.get("golden_asset", {}).get("dims") == [1024, 1024])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
