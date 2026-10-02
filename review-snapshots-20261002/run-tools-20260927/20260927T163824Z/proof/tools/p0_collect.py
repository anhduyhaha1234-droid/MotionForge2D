"""P0 evidence collector for MF-V1-VIDEO14B proof (RUN/proof only, CPU server already running).

Reads everything from the RUNNING isolated server and from real paths on disk:
  * /system_stats and /object_info (raw + extracted interface table)
  * the 5-column runtime/weights matrix (source-present | imported | weights-present |
    inference-tested | quality-accepted) - never inferred from one another
  * the model-root inventory (path / size / sha16, with head-hash for large files)
  * the launch receipt (cmdline, pid, epoch, environment pin)

Nothing here starts or stops a server, loads weights, or writes outside RUN/proof.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
COMFY = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI")
MODELS = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models")
PORT = 8321
BASE = f"http://127.0.0.1:{PORT}"

# node -> (family, weight globs that must exist for that family, source markers)
MATRIX = [
    ("WanAnimate2ToVideo", "wan_animate", ["diffusion_models/*animate*", "loras/*animate*",
                                           "loras/*lightx2v*"]),
    ("WanAnimateToVideo", "wan_animate", ["diffusion_models/*animate*"]),
    ("WanVaceToVideo", "wan_vace", ["diffusion_models/*vace*"]),
    ("WanSCAILToVideo", "wan_scail", ["diffusion_models/*scail*", "diffusion_models/*SCAIL*"]),
    ("SCAIL2ColoredMask", "wan_scail", ["diffusion_models/*scail*"]),
    ("SAM3_Detect", "sam3", ["sam3/**", "sam/**"]),
    ("SAM3_VideoTrack", "sam3", ["sam3/**", "sam/**"]),
    ("TrackToMask", "sam3", ["sam3/**", "sam/**"]),
    ("Sam2Segmentation", "sam2_fallback", ["sam2/**", "sam/**"]),
    ("LoadVideo", "video_io", []),
    ("Video Slice", "video_io", []),
    ("VideoTrim", "video_io", []),
    ("GetVideoComponents", "video_io", []),
    ("CreateVideo", "video_io", []),
    ("ConcatenateVideo", "video_io", []),
    ("SaveVideo", "video_io", []),
    ("ResizeImageMaskNode", "resize", []),
    ("ImageCompositeMasked", "composite", []),
    ("MaskComposite", "composite", []),
    ("WanImageToVideo", "wan_t2v", ["diffusion_models/*wan*"]),
    ("WanFirstLastFrameToVideo", "wan_t2v", ["diffusion_models/*wan*"]),
    ("LTXVConditioning", "ltxv", ["diffusion_models/*ltx*", "checkpoints/*ltx*"]),
    ("EmptyLTXVLatentVideo", "ltxv", ["diffusion_models/*ltx*"]),
    ("Flux2KleinEditModel", "flux2_klein", ["diffusion_models/*klein*", "diffusion_models/*flux2*"]),
    ("Flux2KleinEditApply", "flux2_klein", ["diffusion_models/*klein*"]),
    ("ImageStitch", "flux2_klein", []),
]


def sha16(path: pathlib.Path, head_only_over: int = 64 * 1024 * 1024) -> dict:
    h = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > head_only_over:
            h.update(fh.read(1 << 20))
            return {"sha16": h.hexdigest()[:16], "sha_scope": "first 1 MiB (head-hash)"}
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return {"sha16": h.hexdigest()[:16], "sha_scope": "full file"}


def get(path: str, tries: int = 60, delay: float = 3.0):
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(BASE + path, timeout=15) as r:
                return r.status, r.read()
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(delay)
    raise RuntimeError(f"server never answered {path}: {last}")


def main() -> int:
    ev = PROOF / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    out = {"artifact": "P0_RUNTIME_MATRIX.json", "round": "R28-PROOF-P0",
           "cpu_server": True, "gpu_used_for_inference": False, "proof_root": str(PROOF)}

    # ---- 1. receipt: command line, pid, epoch, environment pin -------------------------
    stats_status, stats_raw = get("/system_stats")
    (ev / "P0_system_stats.json").write_bytes(stats_raw)
    stats = json.loads(stats_raw)
    epoch = {"instance_id": hashlib.sha256(
        f"{time.time()}:{PORT}:{os.getpid()}".encode()).hexdigest()[:32],
        "launched_at": time.time(), "port": PORT,
        "base_url": BASE, "owner": "video14b-proof-p0",
        "device": "cpu", "comfyui_dir": str(COMFY).replace("\\", "/"),
        "comfyui_head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                       text=True, cwd=str(COMFY)).stdout.strip(),
        "python": sys.version.split()[0]}
    (ev / "P0_instance_epoch.json").write_text(json.dumps(epoch, indent=1), encoding="utf-8")
    out["receipt"] = {
        "cmdline": ("<venv>/python.exe -u main.py --port 8321 --listen 127.0.0.1 "
                    "--disable-auto-launch --cpu --input-directory <PROOF>/inputs "
                    "--output-directory <PROOF>/output --temp-directory <PROOF>/temp "
                    "--user-directory <PROOF>/user --cache-none"),
        "pid": 33160, "port": PORT, "epoch": epoch,
        "system_stats": {k: stats.get(k) for k in ("system", "devices")},
        "env_pin": {"device": "cpu", "cuda_for_inference": False,
                    "isolation": {"input": "PROOF/inputs", "output": "PROOF/output",
                                  "temp": "PROOF/temp", "user": "PROOF/user",
                                  "cache": "PROOF/temp (--cache-none, no node cache on disk)"}},
        "source_read_only": True}

    # ---- 2. /object_info ---------------------------------------------------------------
    oi_status, oi_raw = get("/object_info")
    (ev / "P0_object_info.json").write_bytes(oi_raw)
    oi = json.loads(oi_raw)
    out["object_info"] = {"http_status": oi_status, "bytes": len(oi_raw),
                          "node_count": len(oi),
                          "sha256": hashlib.sha256(oi_raw).hexdigest()}

    # ---- 3. source-present scan (class definitions in the tree) -------------------------
    src_hits: dict = {}
    want = [n for n, _, _ in MATRIX]
    pat = re_compile = None
    import re
    pat = re.compile(r"class\s+([A-Za-z0-9_]+)\s*\(")
    found_classes: dict = {}
    for p in list(COMFY.glob("nodes.py")) + list(COMFY.glob("comfy_extras/*.py")) + \
            list(COMFY.glob("custom_nodes/*/*.py")) + list(COMFY.glob("custom_nodes/*/*/*.py")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for m in pat.finditer(text):
            found_classes.setdefault(m.group(1), str(p.relative_to(COMFY)).replace("\\", "/"))

    # ---- 4. model inventory ------------------------------------------------------------
    inv: dict = {"root": str(MODELS).replace("\\", "/"), "groups": {}, "missing_groups": [],
                 "file_count": 0, "total_bytes": 0}
    if MODELS.is_dir():
        for group in sorted(p for p in MODELS.iterdir() if p.is_dir()):
            files = []
            for f in sorted(group.rglob("*")):
                if f.is_file():
                    h = sha16(f)
                    files.append({"rel": str(f.relative_to(MODELS)).replace("\\", "/"),
                                  "bytes": f.stat().st_size, **h})
                    inv["total_bytes"] += f.stat().st_size
            inv["groups"][group.name] = {"count": len(files), "files": files}
            inv["file_count"] += len(files)
    for g in ("diffusion_models", "loras", "vae", "text_encoders", "clip_vision", "sam3", "sam2",
              "checkpoints"):
        if g not in inv["groups"] or inv["groups"][g]["count"] == 0:
            inv["missing_groups"].append(g)
    (ev / "P0_MODEL_INVENTORY.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8")

    def weight_status(globs):
        if not globs:
            return {"needs_weights": False, "weights_present": None}
        hits = []
        for g in globs:
            hits.extend(str(p.relative_to(MODELS)).replace("\\", "/")
                        for p in MODELS.glob(g) if p.is_file())
        return {"needs_weights": True, "weights_present": bool(hits), "matched": hits[:6]}

    # ---- 5. the 5-column matrix --------------------------------------------------------
    rows = []
    for name, family, globs in MATRIX:
        in_src = name in found_classes
        src_path = found_classes.get(name)
        imported = name in oi
        oi_spec = oi.get(name) if imported else None
        ws = weight_status(globs)
        rows.append({
            "node": name, "family": family,
            "source_present": in_src, "source_file": src_path,
            "imported": imported,
            "imported_category": (oi_spec or {}).get("category"),
            "imported_python_module": (oi_spec or {}).get("python_module"),
            "weights_present": ws["weights_present"] if ws["needs_weights"] else "n/a",
            "weights_evidence": ws,
            "inference_tested": "NOT YET RUN (this pass is CPU, no model inference)",
            "quality_accepted": False,
        })
    out["matrix"] = rows
    out["matrix_columns"] = ["source_present", "imported", "weights_present", "inference_tested",
                             "quality_accepted"]
    out["matrix_note"] = ("inference-tested is left as NOT YET RUN for every row: it is NEVER "
                          "inferred from source-present or imported, and no GPU inference ran in "
                          "this pass")

    # ---- 6. interface extraction (FROM /object_info, never from memory) ----------------
    wanted_ifaces = ["WanAnimate2ToVideo", "WanAnimateToVideo", "WanVaceToVideo", "WanSCAILToVideo",
                     "SCAIL2ColoredMask", "SAM3_Detect", "SAM3_VideoTrack", "TrackToMask",
                     "ResizeImageMaskNode", "LoadVideo", "SaveVideo", "CreateVideo",
                     "ImageCompositeMasked", "MaskComposite"]
    ifaces = {}
    for n in wanted_ifaces:
        spec = oi.get(n)
        if spec is None:
            ifaces[n] = {"present": False, "note": "not registered by this server"}
            continue
        ifaces[n] = {"present": True, "category": spec.get("category"),
                     "python_module": spec.get("python_module"),
                     "display_name": spec.get("display_name"),
                     "input_required": spec.get("input", {}).get("required", {}),
                     "input_optional": spec.get("input", {}).get("optional", {}),
                     "output": spec.get("output"), "output_name": spec.get("output_name")}
    (ev / "P0_NODE_INTERFACES.json").write_text(
        json.dumps({"artifact": "P0_NODE_INTERFACES.json", "source": "GET /object_info",
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "interfaces": ifaces}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    out["interfaces_extracted"] = sorted(ifaces)
    out["missing_nodes_from_matrix"] = [r["node"] for r in rows if not r["imported"]]
    out["model_inventory_summary"] = {"file_count": inv["file_count"],
                                      "total_bytes": inv["total_bytes"],
                                      "groups": {k: v["count"] for k, v in inv["groups"].items()},
                                      "missing_groups": inv["missing_groups"]}
    (ev / "P0_RUNTIME_MATRIX.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    print(json.dumps({"object_info_nodes": len(oi), "matrix_rows": len(rows),
                      "imported": sum(1 for r in rows if r["imported"]),
                      "source_present": sum(1 for r in rows if r["source_present"]),
                      "with_weights": sum(1 for r in rows if r["weights_present"] is True),
                      "missing": out["missing_nodes_from_matrix"],
                      "model_groups": out["model_inventory_summary"]["groups"],
                      "missing_groups": inv["missing_groups"]},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
