"""MF-END-14 — the REAL run: isolated ComfyUI server, one CPU-only prefix job (tensor preview)
then ONE GPU inference job (the delivered shot_anchor_v1 graph), then a proven clean shutdown.

Protocol copied from the accepted proof + MF-END-08 (which measured the base-directory trap):
  * isolated server: own base-directory (input/output/temp/user/custom_nodes under MF-END-14),
    --models-directory pointing at the shared read-only model root, own port,
    --reserve-vram 1.0, --disable-auto-launch; the base dir must contain an EXISTING empty
    custom_nodes dir (main.py::execute_prestartup_script lists it before serving);
  * one job at a time: submit -> /history -> download output -> (next job) -> shutdown;
  * receipts carry pid/port/epoch, wall time, VRAM peak, output files + sha256;
  * shutdown = stop ONLY this process, then prove the port refuses and the pid is gone.
"""
from __future__ import annotations

import hashlib
import io
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-14")
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
SRC = RT / "ComfyUI"
VENV_PY = RT / "venv/Scripts/python.exe"
BASE = EV / "runtime"
PORT = 8342
BASE_URL = f"http://127.0.0.1:{PORT}"

PREFIX_SAVES = ["KEY_COMP", "R1_COMP", "R1_RES", "R2_COMP", "R2_RES", "R3_COMP", "R3_RES"]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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
        rows += [int("".join(ch for ch in x if ch.isdigit()) or 0) for x in line.split(",")]
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
                          "subfolder": img.get("subfolder", ""),
                          "type": img.get("type", "output"), "bytes": len(data),
                          "sha256": sha256_bytes(data), "_data": data})
    return files


def run_job(name: str, graph: dict, timeout_s: float) -> dict:
    t_submit = time.time()
    sub = http_json("/prompt", {"prompt": graph, "client_id": f"mf-end-14-{name}"})
    pid = sub["prompt_id"]
    try:
        hist = wait_history(pid, timeout_s)
    except TimeoutError as e:
        hist = {"status": {"status_str": "timeout", "completed": False,
                           "messages": [[repr(e), {}]]}}
    wall = time.time() - t_submit
    status = hist.get("status", {})
    rec = {"job": name, "prompt_id": pid, "submitted_at_unix": t_submit, "wall_s": round(wall, 3),
           "graph_object_sha256": sha256_bytes(json.dumps(
               graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
           "status_str": status.get("status_str"), "completed": bool(status.get("completed")),
           "messages": status.get("messages")}
    if status.get("completed"):
        files = collect_outputs(hist)
        rec["outputs"] = [{k: v for k, v in f.items() if k != "_data"} for f in files]
        rec["_files"] = {f["filename"]: f["_data"] for f in files}
    return rec


def prefix_graph(doc: dict) -> dict:
    g = doc["graph"]
    keep = ["KEY_LOAD", "KEY_SIZE", "KEY_BG", "KEY_INV", "KEY_COMP",
            "R1_LOAD", "R1_SIZE", "R1_BG", "R1_INV", "R1_COMP", "R1_RES",
            "R2_LOAD", "R2_SIZE", "R2_BG", "R2_INV", "R2_COMP", "R2_RES",
            "R3_LOAD", "R3_SIZE", "R3_BG", "R3_INV", "R3_COMP", "R3_RES"]
    out = {k: json.loads(json.dumps(g[k])) for k in keep}
    for nid in PREFIX_SAVES:
        out[f"PREVIEW_{nid}"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"mf_shot_anchor_v1/tensor_preview/{nid.lower()}",
                       "images": [nid, 0]}}
    return out


def pixels_sha(data: bytes) -> tuple[str, list[int]]:
    arr = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    return sha256_bytes(arr.astype(np.uint8).tobytes()), [int(arr.shape[1]), int(arr.shape[0])]


def main() -> int:
    for sub in ("input", "output", "temp", "user", "custom_nodes"):
        (BASE / sub).mkdir(parents=True, exist_ok=True)
    pre = port_state()
    if pre["listening"]:
        print(json.dumps({"error": f"port {PORT} already listening", "pre": pre}))
        return 2
    rec: dict = {"artifact": "run_record.json", "port": PORT,
                 "runtime": {"comfyui_dir": str(SRC).replace("\\", "/"),
                             "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=SRC,
                                                    capture_output=True, text=True).stdout.strip()},
                 "base_directory": str(BASE).replace("\\", "/"),
                 "models_directory": str(RT / "models").replace("\\", "/"),
                 "gpu_before": nvidia(), "port_before": pre}
    log = open(BASE / "server.log", "ab")
    argv = [str(VENV_PY), "-u", str(SRC / "main.py"), "--listen", "127.0.0.1", "--port", str(PORT),
            "--base-directory", str(BASE), "--models-directory", str(RT / "models"),
            "--input-directory", str(BASE / "input"), "--output-directory", str(BASE / "output"),
            "--temp-directory", str(BASE / "temp"), "--user-directory", str(BASE / "user"),
            "--reserve-vram", "1.0", "--disable-auto-launch"]
    rec["launch_argv"] = [a.replace(str(EV), "<MF-END-14>").replace(str(RT), "<runtime/video14b>")
                          for a in argv]
    launched = time.time()
    proc = subprocess.Popen(argv, cwd=str(BASE), stdout=log, stderr=subprocess.STDOUT)
    rec["epoch"] = {"instance_id": uuid.uuid4().hex, "pid": proc.pid, "port": PORT,
                    "launched_at_unix": launched,
                    "launched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(launched))}
    sampler = VramSampler()
    sampler.start()
    err = None
    j1 = j2 = None
    try:
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

        oi = http_json("/object_info", timeout=120)
        (EV / "raw/object_info_live.json").write_text(json.dumps(oi), encoding="utf-8")
        rec["object_info_nodes"] = len(oi)

        # live validation of the DELIVERED graph through the delivered test's own validator
        import importlib.util
        try:
            import pytest  # noqa: F401
        except ModuleNotFoundError:
            # the pinned runtime venv has no pytest: stub the symbols the test module touches at
            # import time (parametrize decorators) so validate_graph/save_node_ids can be reused
            import types
            stub = types.ModuleType("pytest")

            class _Mark:
                @staticmethod
                def parametrize(*a, **k):
                    return lambda fn: fn

            stub.mark = _Mark()
            stub.skip = lambda *a, **k: None
            sys.modules["pytest"] = stub
        spec = importlib.util.spec_from_file_location(
            "mf_end_14_test", WT / "tests/product_delivery/test_mf_end_14.py")
        tmod = importlib.util.module_from_spec(spec)
        sys.modules["mf_end_14_test"] = tmod
        spec.loader.exec_module(tmod)
        doc = json.loads((WT / "app/media_workflows/shot_anchor_v1.json").read_text(encoding="utf-8"))
        rep = tmod.validate_graph(doc["graph"], oi, tmod.save_node_ids(doc["graph"]))
        rec["live_validation"] = rep
        if rep["errors"] or rep["warnings"]:
            raise RuntimeError(f"live validation failed: {rep['errors']} {rep['warnings']}")

        pf = prefix_graph(doc)
        (EV / "raw/prefix_graph.api.json").write_text(json.dumps(pf, indent=1), encoding="utf-8")
        j1 = run_job("prefix_tensor_preview", pf, 300)
        rec["prefix_job"] = j1
        if not j1["completed"]:
            raise RuntimeError("prefix job did not complete")

        j2 = run_job("golden_shot_anchor", doc["graph"], 900)
        rec["golden_job"] = j2
        if not j2["completed"]:
            raise RuntimeError("golden job did not complete")
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
        pre_stop = port_state()
        alive = proc.poll()
        if alive is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=20)
        time.sleep(2)
        post_stop = port_state()
        tasklist = subprocess.run(["tasklist", "/FI", f"PID eq {proc.pid}"],
                                  capture_output=True, text=True).stdout
        rec["shutdown"] = {"phase": "POST_STOP_VERIFIED" if not post_stop["listening"] else "STILL_UP",
                           "pid": proc.pid, "pre": pre_stop, "post": post_stop,
                           "pid_exists": str(proc.pid) in tasklist,
                           "stop_scope": "ONLY the pid this run launched (Popen handle)"}
        log.close()
        rec["gpu_after"] = nvidia()

    # ── tensor-preview comparison: rendered pixels vs the OFFLINE float32 node path ──
    staged = json.loads((EV / "raw/stage_input.json").read_text(encoding="utf-8"))
    exp = staged["tensor_preview_expected"]
    rows = {}
    files = (j1 or {}).get("_files", {})
    mapping = [("KEY_COMP", "KEY", "key_comp_00001_.png"),
               ("R1_COMP", "R1", "r1_comp_00001_.png"),
               ("R1_RES", "R1", "r1_res_00001_.png"),
               ("R2_COMP", "R2", "r2_comp_00001_.png"),
               ("R2_RES", "R2", "r2_res_00001_.png"),
               ("R3_COMP", "R3", "r3_comp_00001_.png"),
               ("R3_RES", "R3", "r3_res_00001_.png")]
    for node, tag, fname in mapping:
        data = files.get(fname)
        if data is None:
            rows[node] = {"missing": fname}
            continue
        px, dims = pixels_sha(data)
        kind = "resized" if node.endswith("RES") else "composite"
        want = exp[tag][f"{kind}_display_pixels_sha256"]
        rows[node] = {"file": fname, "bytes": len(data), "file_sha256": sha256_bytes(data),
                      "dims": dims, "pixels_sha256": px, "expected_pixels_sha256": want,
                      "pixels_match_offline_expectation": px == want,
                      "expected_dims": exp[tag][f"{kind}_display_dims"]}
    rec["tensor_preview_comparison"] = rows

    # freeze the golden anchor bytes into the evidence tree
    afiles = (j2 or {}).get("_files", {})
    if afiles:
        asset_dir = EV / "asset"
        asset_dir.mkdir(parents=True, exist_ok=True)
        frozen = []
        for name, data in afiles.items():
            p = asset_dir / name
            p.write_bytes(data)
            frozen.append({"file": name, "path": str(p).replace("\\", "/"), "bytes": len(data),
                           "sha256": sha256_bytes(data)})
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
                      if k in ("epoch", "ready_after_s", "object_info_nodes", "live_validation",
                               "prefix_job", "golden_job", "vram_peak_mib", "gpu_util_peak_pct",
                               "shutdown", "tensor_preview_comparison", "golden_asset",
                               "gpu_before", "gpu_after", "error")},
                     indent=1, ensure_ascii=False)[:5000])
    ok = (err is None
          and (rec.get("golden_job") or {}).get("completed")
          and rec.get("shutdown", {}).get("phase") == "POST_STOP_VERIFIED"
          and (rec.get("golden_asset") or {}).get("dims") == [640, 368]
          and all(r.get("pixels_match_offline_expectation") is True
                  for r in rec["tensor_preview_comparison"].values()))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
