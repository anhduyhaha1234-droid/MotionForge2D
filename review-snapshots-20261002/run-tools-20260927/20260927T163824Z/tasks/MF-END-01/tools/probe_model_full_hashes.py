"""Read-only probe: full-file sha256 for the 5 pinned Wan Animate 2 profile files.

The proof gate recorded only head-hashes (first 1 MiB, sha16) for these files in
P0_MODEL_INVENTORY.json.  The accepted media-engine DTO requires a 64-hex
``file_sha256`` for a model pin, so MF-END-01 measures the full hashes once
(read-only) and freezes them in the shot-reskin examples.

Also re-checks that the CONTRACT-tree copy of the accepted DTO equals the pinned
git blob (``git hash-object``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

MODELS_ROOT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models")
CONTRACT_TREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract")

TARGETS = {
    "unet": ("diffusion_models/wan_animate_2_int8_convrot.safetensors", "f7ba70b820aa441f", 16653175528),
    "lora": (
        "loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "9683d8ac899a3084",
        738005744,
    ),
    "text_encoder": ("text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "c4ef905e4c984b93", 6735906897),
    "clip_vision": ("clip_vision/clip_vision_h.safetensors", "7809e2986b05a5f1", 1264219396),
    "vae": ("vae/Wan2_1_VAE_bf16.safetensors", "744600e1e656c99d", 253806278),
}


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def head_sha16(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        h.update(fh.read(1024 * 1024))
    return h.hexdigest()[:16]


def main() -> int:
    out: dict = {"probe": "mf_end_01_model_full_hashes", "models": {}}
    for key, (rel, sha16_expected, bytes_expected) in TARGETS.items():
        path = MODELS_ROOT / rel
        entry: dict = {"rel": rel, "exists": path.is_file()}
        if path.is_file():
            entry["sha256"], entry["bytes"] = sha256_file(path)
            entry["sha16_recomputed"] = head_sha16(path)
            entry["sha16_expected"] = sha16_expected
            entry["head_hash_matches"] = entry["sha16_recomputed"] == sha16_expected
            entry["bytes_match_inventory"] = entry["bytes"] == bytes_expected
        out["models"][key] = entry
        print(f"  hashed {key}: {entry.get('sha256', 'MISSING')[:16]} bytes={entry.get('bytes')}", file=sys.stderr)
    dto = CONTRACT_TREE / "app" / "schemas" / "media_engine.py"
    proc = subprocess.run(
        ["git", "-C", str(CONTRACT_TREE), "hash-object", "app/schemas/media_engine.py"],
        capture_output=True,
        text=True,
    )
    out["dto_hash_object"] = {
        "rc": proc.returncode,
        "blob": proc.stdout.strip(),
        "expected_blob": "9e4586a1b2cbc8aeb6d35a75c038327533b81b2a",
        "matches_pinned_blob": proc.stdout.strip() == "9e4586a1b2cbc8aeb6d35a75c038327533b81b2a",
        "file_sha256": hashlib.sha256(dto.read_bytes()).hexdigest() if dto.is_file() else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
