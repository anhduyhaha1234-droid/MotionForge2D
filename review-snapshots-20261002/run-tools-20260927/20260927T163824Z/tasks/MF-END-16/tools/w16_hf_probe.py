"""MF-END-16 tool — probe the model provenance on the Hub and save the raw evidence.

Records, per pinned revision: repo license, revision date, and per-file size + LFS oid so the
manifest's `hf_lfs_oid_equals_measured_sha256` claim is backed by a saved raw artifact.
Writes raw/hf_provenance_probe.json. Read-only (network GET only).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "raw"

TARGETS = [
    ("Comfy-Org/Wan-Animate-2", "ed158470869ff31fa51cf56012dac33fb00f494b", [
        "diffusion_models/wan_animate_2_int8_convrot.safetensors",
        "loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "vae/Wan2_1_VAE_bf16.safetensors",
        "clip_vision/clip_vision_h.safetensors",
    ]),
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "617a7633e636506f850e043bc4605f290a466a8e", [
        "split_files/diffusion_models/wan2.1_vace_14B_fp16.safetensors",
    ]),
]


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def main() -> int:
    out = {"artifact": "hf_provenance_probe.json", "repos": []}
    for repo, rev, files in TARGETS:
        info = get(f"https://huggingface.co/api/models/{repo}/revision/{rev}")
        tree = get(f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true&revision={rev}")
        by = {e["path"]: e for e in tree}
        row = {
            "repo": repo,
            "revision": info.get("sha"),
            "license": (info.get("cardData") or {}).get("license"),
            "lastModified": info.get("lastModified"),
            "files": [],
        }
        for path in files:
            e = by.get(path)
            row["files"].append({
                "path": path,
                "exists": e is not None,
                "size": e.get("size") if e else None,
                "lfs_oid": (e.get("lfs") or {}).get("oid") if e else None,
            })
        out["repos"].append(row)
        print(f"{repo}@{rev[:12]} license={row['license']} files={len(row['files'])}")
    dest = RAW / "hf_provenance_probe.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
