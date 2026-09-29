"""MF-END-08 — offline hash collection (models, node sources, templates, runtime).

Read-only on the pinned runtime. Writes ONE json under the MF-END-08 evidence root.
Full sha256 for the models; head-1MiB sha256 in the proof's own scope string as well.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
RT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
SRC = RT / "ComfyUI"
MODELS = RT / "models"
TPL = RT / "venv/Lib/site-packages/comfyui_workflow_templates_json/templates"

CLASSES = ["LoadImage", "EmptyImage", "SaveImage", "GetImageSize", "VAEEncode", "VAEDecode",
           "ImageCompositeMasked", "InvertMask", "ResizeImageMaskNode", "EmptyFlux2LatentImage",
           "Flux2Scheduler", "ReferenceLatent", "ConditioningZeroOut", "CLIPTextEncode",
           "UNETLoader", "CLIPLoader", "VAELoader", "SamplerCustomAdvanced", "KSamplerSelect",
           "RandomNoise", "CFGGuider"]

MODEL_FILES = ["diffusion_models/flux-2-klein-4b-fp8.safetensors",
               "text_encoders/qwen_3_4b.safetensors",
               "vae/flux2-vae.safetensors"]

TEMPLATE_FILES = ["image_flux2_klein_image_edit_4b_distilled.json",
                  "image_flux2_klein_image_edit_4b_base.json"]


def sha256_file(p: Path, head_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        if head_bytes is None:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        else:
            h.update(f.read(head_bytes))
    return h.hexdigest()


def locate_class(name: str) -> list[str]:
    pat = re.compile(rf'(class {name}\b|node_id="{name}")')
    hits = []
    for base in (SRC / "nodes.py",):
        if pat.search(base.read_text(encoding="utf-8", errors="replace")):
            hits.append(str(base.relative_to(SRC)).replace("\\", "/"))
    for p in sorted((SRC / "comfy_extras").glob("*.py")):
        if pat.search(p.read_text(encoding="utf-8", errors="replace")):
            hits.append(str(p.relative_to(SRC)).replace("\\", "/"))
    return hits


def main() -> int:
    out: dict = {"artifact": "model_and_node_hashes.json",
                 "runtime": {
                     "comfyui_dir": str(SRC).replace("\\", "/"),
                     "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=SRC,
                                            capture_output=True, text=True).stdout.strip(),
                     "porcelain": subprocess.run(["git", "status", "--porcelain"], cwd=SRC,
                                                 capture_output=True, text=True).stdout.splitlines(),
                     "version_file_sha256": sha256_file(SRC / "comfyui_version.py"),
                 },
                 "models": [], "node_sources": [], "templates": [],
                 "head_hash_scope": "sha256 of the FIRST 1 MiB (the proof's sha16 scope)"}

    for rel in MODEL_FILES:
        p = MODELS / rel
        out["models"].append({"role": rel.split("/")[0], "file": p.name,
                              "rel": rel, "path": str(p).replace("\\", "/"),
                              "bytes": p.stat().st_size,
                              "sha256": sha256_file(p),
                              "sha256_first_1mib": sha256_file(p, 1 << 20)})

    for cls in CLASSES:
        files = locate_class(cls)
        out["node_sources"].append({"class_type": cls, "defining_files": files,
                                    "sha256": {f: sha256_file(SRC / f) for f in files}})

    for name in TEMPLATE_FILES:
        p = TPL / name
        out["templates"].append({"file": name, "path": str(p).replace("\\", "/"),
                                 "bytes": p.stat().st_size, "sha256": sha256_file(p),
                                 "package": "comfyui_workflow_templates_json 0.1.92 (installed)"})

    dest = EV / "raw" / "model_and_node_hashes.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("WROTE", dest)
    print("models:", [(m["file"], m["bytes"], m["sha256"][:16]) for m in out["models"]])
    for n in out["node_sources"]:
        if not n["defining_files"]:
            print("UNLOCATED", n["class_type"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
