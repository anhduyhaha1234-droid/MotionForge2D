"""S0d assertions on a converted API (execution) graph + loader extraction.

usage: python w2_validate_api.py <object_info.json> <api.json> [--label NAME]
Outputs JSON to stdout:
  classes / missing_classes / counts_by_class / loaders / excluded_weight_hits
  / wan_animate_wiring / vace_wiring
Every check below is a measurement against the live /object_info and the graph
itself; nothing is inferred from the template's documentation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXCLUDED = ("Wan21_CausVid", "CausVid")


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


LOADER_KEYS = {
    "ckpt_name": "checkpoint",
    "unet_name": "unet/diffusion_model",
    "lora_name": "lora",
    "clip_name": "text_encoder",
    "clip_name1": "text_encoder1",
    "clip_name2": "text_encoder2",
    "vae_name": "vae",
    "model_name": "model",
    "image": "image",
    "video": "video",
    "file": "file",
    "audio": "audio",
    "control_video": "control_video",
}


def main() -> int:
    oi = json.loads(_p(sys.argv[1]).read_text(encoding="utf-8"))
    api = json.loads(_p(sys.argv[2]).read_text(encoding="utf-8"))
    label = sys.argv[4] if len(sys.argv) > 4 else _p(sys.argv[2]).stem

    classes = {}
    loaders = []
    strings = []
    for nid, node in api.items():
        ct = node.get("class_type")
        classes[ct] = classes.get(ct, 0) + 1
        for k, v in (node.get("inputs") or {}).items():
            if isinstance(v, str):
                strings.append({"id": nid, "input": k, "value": v})
                if k in LOADER_KEYS:
                    loaders.append({"id": nid, "class_type": ct, "input": k,
                                    "kind": LOADER_KEYS[k], "value": v})

    excluded_hits = [s for s in strings if any(x in s["value"] for x in EXCLUDED)]

    # wiring: for a node of class C, report each input's origin (id/class + literal)
    def wiring(cls: str) -> dict:
        out = {}
        for nid, node in api.items():
            if node.get("class_type") != cls:
                continue
            sub = {}
            for k, v in (node.get("inputs") or {}).items():
                if isinstance(v, list) and len(v) == 2 and str(v[0]) in api:
                    sub[k] = {"from": str(v[0]), "from_class": api[str(v[0])]["class_type"]}
                else:
                    sub[k] = {"literal": v}
            out[str(nid)] = sub
        return out

    report = {
        "label": label,
        "api_nodes": len(api),
        "classes": len(classes),
        "counts_by_class": dict(sorted(classes.items())),
        "missing_classes": sorted(c for c in classes if c not in oi),
        "loaders": loaders,
        "excluded_weight_hits": excluded_hits,
        "wan_animate_wiring": wiring("WanAnimate2ToVideo"),
        "vace_wiring": wiring("WanVaceToVideo"),
        "model_sampling_wiring": wiring("ModelSamplingSD3"),
        "save_video_wiring": wiring("SaveVideo"),
        "output_nodes": wiring("CreateVideo"),
    }
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 1 if (report["missing_classes"] or excluded_hits) else 0


if __name__ == "__main__":
    raise SystemExit(main())
