"""MF-END-28 — byte-exact bounded patch for THIRD_PARTY.md (CRLF file).

Insertion-only; preimage asserted (count == 1) before any write.
"""
import hashlib
import pathlib
import sys

WT = pathlib.Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-28")
TARGET = WT / "THIRD_PARTY.md"
NL = chr(10)
CR = chr(13)

BEFORE_SHA = "3dc600b38834248225f0132d47546cddad99954a62c642b80f069c81f3e2ce6a"

SECTION_LINES = [
    "## ComfyUI Engine And Shot-Engine Dependency (MF-END-18 / MF-END-28)",
    "",
    "| Component | Pin | License | Notes |",
    "|-----------|-----|---------|-------|",
    "| **ComfyUI engine** (external runtime) | 0.37.0, head"
    " `73c9bad4d21e7addbe1d13bc92eee0f1431b017d` | GPL-3.0 (LICENSE at"
    " the engine repo root) | executed as an external process via"
    " `/prompt` + `/object_info`; MotionForge does not redistribute"
    " engine binaries |",
    "| **mf-comfy** (in-house stage adapter, dist `mf-comfy` 0.1.0) |"
    " source commit `70f718098f00f9dbdeb6cc9c5d7808b243eb0c57`, 11"
    " module files | in-house (MotionForge), built by"
    " `scripts/build_mf_comfy_dependency.py` | built from the git object"
    " store at the pinned commit; never imported from a developer"
    " worktree at runtime |",
    "",
    "## AI Model Checkpoints For The Demo Graphs (external - never bundled)",
    "",
    "Weights stay in the external read-only model root (`MF2D_MODELS_ROOT`;",
    "see `packaging/demo/models.json`). Nothing here is copied into the",
    "package, the checkout, or git. File hashes (sha256) are recorded in",
    "`packaging/demo/models.json`.",
    "",
    "| Model file (rel under models root) | Bytes | License | Source |",
    "|-----------------------------------|-------|---------|--------|",
    "| `diffusion_models/wan_animate_2_int8_convrot.safetensors` |"
    " 16,653,175,528 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |",
    "| `loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors`"
    " | 738,005,744 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |",
    "| `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` |"
    " 6,735,906,897 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |",
    "| `clip_vision/clip_vision_h.safetensors` | 1,264,219,396 |"
    " apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |",
    "| `vae/Wan2_1_VAE_bf16.safetensors` | 253,806,278 | apache-2.0 |"
    " Comfy-Org/Wan-Animate-2 @ ed158470 |",
    "| `diffusion_models/flux-2-klein-4b-fp8.safetensors` | 4,070,624,520 |"
    " apache-2.0 | black-forest-labs/FLUX.2-klein-4b-fp8 |",
    "| `text_encoders/qwen_3_4b.safetensors` | 8,044,982,048 | apache-2.0"
    " | Comfy-Org/vae-text-encorder-for-flux-klein-4b |",
    "| `vae/flux2-vae.safetensors` | 336,211,292 | apache-2.0 |"
    " Comfy-Org/vae-text-encorder-for-flux-klein-4b |",
    "",
    "License-status notes (measured, not assumed):",
    "",
    "- Model **weights not licensed for use** are separated from the runtime",
    "  model set and never loaded:"
    " `runtime/video14b/excluded_unlicensed_weights/`",
    "  holds the Wan2.1 CausVid LoRA files excluded for exactly this reason.",
    "- The `vace_14b_fp16_book` profile is NOT selected (open watermark-copy",
    "  blocker, recorded in `app/media_workflows/model_profiles.json`); its",
    "  weights are not part of the demo model manifest.",
    "- License records and artifact hashes in `packaging/demo/*.json` carry",
    "  IDs and digests only - no keys, tokens or credentials.",
    "",
]

CHECKLIST_OLD = "- [x] Fully offline-capable after model download"
CHECKLIST_ADD = [
    "- [x] ComfyUI engine + mf-comfy dependency pins recorded (no engine"
    " redistribution by MotionForge)",
    "- [x] Demo model weights external + unlicensed weights excluded from"
    " the runtime set",
    "- [x] No secrets in license/hash records (`packaging/demo/*.json`,"
    " launcher output)",
]


def to_crlf(lines):
    return (CR + NL).join(lines).encode("utf-8")


def main() -> int:
    data = TARGET.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != BEFORE_SHA:
        print(f"PREIMAGE_MISMATCH: {got} != {BEFORE_SHA}")
        return 2

    anchor = "## Renderer Router Wired Backends (S09-T00-I02)"
    marker = anchor.encode("utf-8")
    if data.count(marker) != 1:
        print(f"ANCHOR1_COUNT={data.count(marker)}")
        return 2

    block = to_crlf(SECTION_LINES + [anchor])
    new = data.replace(marker, block, 1)

    cl_old = CHECKLIST_OLD.encode("utf-8")
    if new.count(cl_old) != 1:
        print(f"ANCHOR2_COUNT={new.count(cl_old)}")
        return 2
    cl_new = to_crlf([CHECKLIST_OLD] + CHECKLIST_ADD)
    new = new.replace(cl_old, cl_new, 1)

    TARGET.write_bytes(new)
    after = hashlib.sha256(new).hexdigest()
    print(f"BEFORE_SHA={got}")
    print(f"AFTER_SHA={after}")
    print(f"BYTES {len(data)} -> {len(new)}")
    print(f"LINES {data.count(bytes([10]))} -> {new.count(bytes([10]))}")
    return 0


def verify() -> int:
    data = TARGET.read_bytes()
    print(f"VERIFY_SHA={hashlib.sha256(data).hexdigest()}")
    print(f"VERIFY_BYTES={len(data)}")
    print(f"VERIFY_LINES={data.count(bytes([10]))}")
    ok = (b"## ComfyUI Engine And Shot-Engine Dependency" in data
          and b"## Renderer Router Wired Backends" in data
          and CHECKLIST_ADD[-1].encode("utf-8") in data)
    print(f"VERIFY_SECTION_PRESENT={ok}")
    return 0 if ok else 2


if __name__ == "__main__":
    if "--verify" in sys.argv:
        raise SystemExit(verify())
    raise SystemExit(main())
