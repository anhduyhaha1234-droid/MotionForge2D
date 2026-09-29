"""MF-END-16 tool — full sha256 of the WAN-path model files used by the pinned profile.

Read-only: opens each file and hashes it; never writes into the runtime tree.
Output: raw/model_full_hashes.json
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

MODELS_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models")

FILES = [
    ("diffusion_models", "wan_animate_2_int8_convrot.safetensors"),
    ("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"),
    ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    ("clip_vision", "clip_vision_h.safetensors"),
    ("vae", "Wan2_1_VAE_bf16.safetensors"),
    ("diffusion_models", "wan2.1_vace_14B_fp16.safetensors"),
]


def head_sha256(path: Path, limit: int = 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        data = fh.read(limit)
    h.update(data)
    return h.hexdigest(), len(data)


def full_sha256(path: Path) -> tuple[str, int, float]:
    h = hashlib.sha256()
    total = 0
    t0 = time.time()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024 * 8)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total, round(time.time() - t0, 3)


def main() -> int:
    out = {
        "artifact": "model_full_hashes.json",
        "models_root": str(MODELS_ROOT),
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": [],
    }
    for group, name in FILES:
        path = MODELS_ROOT / group / name
        rec: dict = {"group": group, "file": name, "path": str(path)}
        if not path.is_file():
            rec["exists"] = False
            out["files"].append(rec)
            print(f"MISSING {path}", flush=True)
            continue
        rec["exists"] = True
        rec["bytes"] = path.stat().st_size
        head16, head_len = head_sha256(path)
        rec["sha256_first_1mib"] = head16
        rec["sha256_first_1mib_len"] = head_len
        full, total, dur = full_sha256(path)
        rec["sha256"] = full
        rec["hash_seconds"] = dur
        out["files"].append(rec)
        print(f"HASHED {group}/{name} {rec['bytes']} {full} {dur}s", flush=True)
    out["ok"] = all(f.get("exists") for f in out["files"])
    dest = Path(__file__).resolve().parent.parent / "raw" / "model_full_hashes.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE {dest}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
