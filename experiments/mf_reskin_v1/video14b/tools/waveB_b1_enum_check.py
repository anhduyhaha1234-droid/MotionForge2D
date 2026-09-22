"""MF-V1-VIDEO14B wave B step B1 — live /object_info enum check (BLOCKING).

Reads the LIVE /object_info of the reserved wave-B engine port and proves the
three enums the wave-A static validation flagged as stale actually resolve:

  node 75:70 UNETLoader.unet_name  = flux-2-klein-4b-fp8.safetensors
  node 75:71 CLIPLoader.clip_name  = qwen_3_4b.safetensors
  node 75:72 VAELoader.vae_name    = flux2-vae.safetensors

It also confirms the classes the run contract depends on exist on this boot
(save nodes + the Animate-2 template's own nodes), so a missing class is caught
here instead of after a 60-minute GPU slot is spent.

Evidence written next to the script's --out argument:
  object_info_live_<port>.json.gz          (the full raw body, gzipped)
  object_info_live_<port>.filtered.json    (the enums + class presence above)
Verdict JSON goes to stdout: BLOCKED_DEPENDENCY on any missing enum.

usage: python waveB_b1_enum_check.py <port> <out_dir>
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ENUMS = [
    ("75:70", "UNETLoader", "unet_name", "flux-2-klein-4b-fp8.safetensors"),
    ("75:71", "CLIPLoader", "clip_name", "qwen_3_4b.safetensors"),
    ("75:72", "VAELoader", "vae_name", "flux2-vae.safetensors"),
]

REQUIRED_CLASSES = [
    # anchor (FLUX.2 klein 4B reference) graph
    "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "EmptyFlux2LatentImage",
    "ImageScaleToTotalPixels", "Flux2Scheduler", "KSamplerSelect", "CFGGuider",
    "RandomNoise", "SamplerCustomAdvanced", "VAEDecode", "GetImageSize",
    "ReferenceLatent", "ConditioningZeroOut", "LoadImage", "SaveImage",
    # animate-2 run graph
    "LoadVideo", "GetVideoComponents", "CreateVideo", "SaveVideo", "SaveAnimatedWEBP",
    "LoraLoaderModelOnly", "CLIPVisionLoader", "CLIPVisionEncode", "WanAnimate2ToVideo",
    "WanAnimate2Cache", "ModelSamplingSD3", "BasicScheduler", "SamplerCustom",
    "TrimVideoLatent", "ImageFromBatch", "ImageStitch", "ResizeImageMaskNode",
    "ComfyMathExpression", "ComfySwitchNode", "GetItemFromList", "CreateList",
    "StartLoop", "EndLoop", "ContextWindowsManual", "RebatchImages", "PrimitiveInt",
]

# B4-only: reported for information, never a B1 blocker.  The VACE control path is
# conditional and its class list is taken from the run graph itself at convert
# time; a class missing here says nothing about B1's three enums.
INFO_CLASSES = ["WanVaceToVideo", "WanVideoVAEEncode", "WanVideoVAEDecode"]


def main() -> int:
    port = int(sys.argv[1])
    out_dir = Path(str(sys.argv[2]).replace("\\", "/"))
    if str(out_dir).startswith("/") and out_dir.drive == "":
        out_dir = Path(str(out_dir)[1].upper() + ":" + str(out_dir)[2:])
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{port}/object_info"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        status = resp.status
        body = resp.read()
    sha = hashlib.sha256(body).hexdigest()
    (out_dir / f"object_info_live_{port}.json.gz").write_bytes(gzip.compress(body, 9))
    oi = json.loads(body)

    filtered: dict = {"url": url, "http_status": status, "body_bytes": len(body),
                      "body_sha256": sha, "class_count": len(oi), "enums": {},
                      "classes": {}, "missing_enums": [], "missing_classes": []}
    for node, cls, inp, val in ENUMS:
        entry: dict = {"class_type": cls, "input": inp, "node": node, "value": val}
        c = oi.get(cls)
        entry["class_present"] = c is not None
        choices = (((c or {}).get("input") or {}).get("required") or {}).get(inp)
        if isinstance(choices, list) and choices and isinstance(choices[0], list):
            options = list(choices[0])
        else:
            options = None
        entry["enum_present"] = options is not None
        entry["enum_size"] = len(options) if options is not None else None
        entry["value_in_enum"] = bool(options is not None and val in options)
        entry["enum_sample"] = options[:8] if options else None
        if options is not None and val in options:
            entry["enum_index"] = options.index(val)
        filtered["enums"][f"{node}:{cls}.{inp}"] = entry
        if not entry["value_in_enum"]:
            filtered["missing_enums"].append(f"{node}:{cls}.{inp}={val}")
    for cls in REQUIRED_CLASSES:
        c = oi.get(cls)
        filtered["classes"][cls] = {
            "present": c is not None,
            "output_node": bool((c or {}).get("output_node")),
            "python_module": (c or {}).get("python_module"),
        }
        if c is None:
            filtered["missing_classes"].append(cls)
    filtered["info_classes"] = {cls: bool(oi.get(cls)) for cls in INFO_CLASSES}

    filtered["verdict"] = "BLOCKED_DEPENDENCY" if (filtered["missing_enums"] or filtered["missing_classes"]) else "B1_ENUMS_RESOLVE_LIVE"
    (out_dir / f"object_info_live_{port}.filtered.json").write_text(
        json.dumps(filtered, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: filtered[k] for k in
                      ("url", "http_status", "body_bytes", "body_sha256", "class_count",
                       "verdict", "missing_enums", "missing_classes")}, indent=1))
    print(json.dumps(filtered["enums"], indent=1))
    return 0 if filtered["verdict"] != "BLOCKED_DEPENDENCY" else 5


if __name__ == "__main__":
    raise SystemExit(main())
