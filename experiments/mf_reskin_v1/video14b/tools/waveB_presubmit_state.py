"""MF-V1-VIDEO14B wave B step B3 — durable PRE-SUBMIT state.

Written BEFORE the POST (the packet's survival rule: if the CLI iteration limit is
reached while the load/log is progressing, that is not authority to kill the GPU
job -- the stage state you set before submit is what a later reconcile reads).

Records: the reserved attempt identity, engine epoch (instance/pid/port), the
matched official config set, the exact graph/driving/reference hashes, the stage
root, and the wall-cap arithmetic.  The post-run record is written by
w2_run_stage.py into the same directory; this file is never overwritten.

usage: python waveB_presubmit_state.py <attempt_id> <stage_name> <out_dir> <graph.api.json>
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha(p: Path) -> dict:
    if not p.is_file():
        return {"path": str(p), "missing": True}
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return {"path": str(p), "bytes": p.stat().st_size, "sha256": h.hexdigest()}


def main() -> int:
    attempt_id, stage_name, out_dir, graph_path = (
        sys.argv[1], sys.argv[2], _p(sys.argv[3]), _p(sys.argv[4]))
    out_dir.mkdir(parents=True, exist_ok=True)
    g = json.loads(graph_path.read_text(encoding="utf-8"))

    # the matched official set is read OUT of the graph, not typed in by hand
    cfg: dict = {}
    for nid, node in g.items():
        ct, ins = node["class_type"], node.get("inputs", {})
        if ct == "UNETLoader":
            cfg["checkpoint"] = {"node": nid, "file": ins["unet_name"]}
        elif ct == "LoraLoaderModelOnly":
            cfg["lora"] = {"node": nid, "file": ins["lora_name"],
                           "strength_model": ins.get("strength_model")}
        elif ct == "CLIPLoader":
            cfg["text_encoder"] = {"node": nid, "file": ins["clip_name"], "type": ins.get("type")}
        elif ct == "CLIPVisionLoader":
            cfg["clip_vision"] = {"node": nid, "file": ins["clip_name"]}
        elif ct == "VAELoader":
            cfg["vae"] = {"node": nid, "file": ins["vae_name"]}
        elif ct == "KSamplerSelect":
            cfg["sampler"] = {"node": nid, "sampler_name": ins["sampler_name"]}
        elif ct == "BasicScheduler":
            cfg["scheduler"] = {"node": nid, "scheduler": ins["scheduler"],
                                "steps": ins["steps"], "denoise": ins.get("denoise")}
        elif ct == "ModelSamplingSD3":
            cfg["model_sampling_sd3_shift"] = {"node": nid, "shift": ins.get("shift")}
        elif ct == "SamplerCustom":
            cfg["sampler_custom"] = {"node": nid, "cfg": ins.get("cfg"),
                                     "noise_seed": ins.get("noise_seed"),
                                     "add_noise": ins.get("add_noise")}
        elif ct == "WanAnimate2Cache":
            cfg["cache"] = {"node": nid, "device": ins.get("device"), "dtype": ins.get("dtype")}
        elif ct == "WanAnimate2ToVideo":
            cfg["animate2"] = {"node": nid, "pose_strength": ins.get("pose_strength"),
                               "reference_image_strength": ins.get("reference_image_strength")}
        elif ct == "LoadVideo":
            cfg["driving_video"] = {"node": nid, "file": ins["file"]}
        elif ct == "LoadImage":
            cfg["reference_image"] = {"node": nid, "file": ins["image"]}
        elif ct == "ContextWindowsManual":
            cfg["context_windows"] = {"node": nid, "context_length": ins.get("context_length"),
                                      "context_overlap": ins.get("context_overlap"),
                                      "schedule": ins.get("context_schedule")}

    model_hashes = {}
    for key, (sub, name) in {"checkpoint": ("diffusion_models", cfg["checkpoint"]["file"]),
                             "lora": ("loras", cfg["lora"]["file"]),
                             "text_encoder": ("text_encoders", cfg["text_encoder"]["file"]),
                             "clip_vision": ("clip_vision", cfg["clip_vision"]["file"]),
                             "vae": ("vae", cfg["vae"]["file"])}.items():
        model_hashes[key] = sha(RT / "models" / sub / name)

    inputs = {
        "driving_video": sha(RT / "input" / cfg["driving_video"]["file"]),
        "reference_image": sha(RT / "input" / cfg["reference_image"]["file"]),
    }
    epoch = json.loads((RT / "instance_epoch.json").read_text(encoding="utf-8"))
    port = epoch["port"]
    with socket.socket() as s:
        s.settimeout(3.0)
        try:
            s.connect(("127.0.0.1", port))
            listener = True
        except Exception:  # noqa: BLE001
            listener = False

    state = {
        "row": "B3", "task_id": "MF-V1-VIDEO14B", "wave": "B",
        "attempt_id": attempt_id,
        "stage_name": stage_name,
        "stage_root": str(RT / "output" / stage_name),
        "out_dir": str(out_dir),
        "graph_path": str(graph_path),
        "graph_sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
        "graph_api_nodes": len(g),
        "engine": {"port": port, "instance_id": epoch["instance_id"], "pid": epoch["pid"],
                   "comfyui_version": epoch["comfyui_version"],
                   "comfyui_commit": epoch["comfyui_commit"], "listener_accepts": listener},
        "matched_official_config": cfg,
        "model_hashes": model_hashes,
        "input_hashes": inputs,
        "wall_cap_rule": "60 min wall INCLUDING model load; the CLI's own iteration limit is NOT "
                         "authority to kill the GPU job -- reconcile /queue + /history instead",
        "written_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "written_at_epoch": time.time(),
        "submit_started": False,
    }
    p = out_dir / "presubmit_state.json"
    p.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"presubmit_state": str(p), "attempt_id": attempt_id,
                      "engine": state["engine"],
                      "config": {k: (v.get("file") or v) for k, v in cfg.items()},
                      "model_hashes": {k: v.get("sha256", "MISSING")[:16] for k, v in model_hashes.items()},
                      "inputs": {k: v.get("sha256", "MISSING")[:16] for k, v in inputs.items()}},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
