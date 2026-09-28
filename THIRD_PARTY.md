# MotionForge 2D — Third-Party Dependencies

## Python Packages

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| **PyTorch** | 2.11.0+cu128 | BSD-3-Clause | Deep learning framework for SAM 2.1 |
| **torchvision** | 0.26.0+cu128 | BSD-3-Clause | Vision utilities for PyTorch |
| **SAM-2** | 1.0 | Apache-2.0 | Segment Anything Model 2 by Meta AI |
| **FastAPI** | 0.139.2+ | MIT | Web API framework |
| **Pydantic** | 2.13.4+ | MIT | Data validation and serialization |
| **SQLAlchemy** | 2.0.51+ | MIT | Database ORM |
| **aiosqlite** | 0.22.1+ | MIT | Async SQLite driver |
| **OpenCV** (opencv-python-headless) | 5.0.0+ | Apache-2.0 | Image processing, contour detection |
| **NumPy** | 2.4.4+ | BSD-3-Clause | Numerical computing |
| **Pillow** | 12.2.0+ | MIT-CMU | Image I/O |
| **PySceneDetect** | 0.7.1+ | BSD-3-Clause | Video scene boundary detection |
| **hydra-core** | 1.3.4+ | MIT | Configuration management (SAM2 dep) |
| **omegaconf** | 2.3.1+ | BSD-3-Clause | YAML config (SAM2 dep) |
| **iopath** | 0.1.10+ | MIT | File I/O abstraction (SAM2 dep) |
| **uvicorn** | 0.51.0+ | BSD-3-Clause | ASGI server |
| **httpx** | 0.28.1+ | BSD-3-Clause | HTTP client |
| **tqdm** | 4.69.0+ | MIT | Progress bars |

### Dev Dependencies

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| **pytest** | 9.1.1+ | MIT | Testing framework |
| **pytest-asyncio** | 1.4.0+ | Apache-2.0 | Async test support |
| **ruff** | 0.3.0+ | MIT | Python linter |
| **mypy** | 1.8.0+ | MIT | Static type checker |

## System Dependencies

| Tool | Version | License | Purpose |
|------|---------|---------|---------|
| **FFmpeg** | 8.1.2 | LGPL-2.1+ (GPL build) | Video encoding/decoding |
| **Python** | 3.11 | PSF | Runtime |
| **Node.js** | 26.x | MIT | Frontend build |

## AI Model Checkpoints

| Model | Size | License | Source |
|-------|------|---------|--------|
| **sam2.1_hiera_large.pt** | ~890MB | Apache-2.0 | [Meta AI SAM2](https://github.com/facebookresearch/sam2) |

## ComfyUI Engine And Shot-Engine Dependency (MF-END-18 / MF-END-28)

| Component | Pin | License | Notes |
|-----------|-----|---------|-------|
| **ComfyUI engine** (external runtime) | 0.37.0, head `73c9bad4d21e7addbe1d13bc92eee0f1431b017d` | GPL-3.0 (LICENSE at the engine repo root) | executed as an external process via `/prompt` + `/object_info`; MotionForge does not redistribute engine binaries |
| **mf-comfy** (in-house stage adapter, dist `mf-comfy` 0.1.0) | source commit `70f718098f00f9dbdeb6cc9c5d7808b243eb0c57`, 11 module files | in-house (MotionForge), built by `scripts/build_mf_comfy_dependency.py` | built from the git object store at the pinned commit; never imported from a developer worktree at runtime |

## AI Model Checkpoints For The Demo Graphs (external - never bundled)

Weights stay in the external read-only model root (`MF2D_MODELS_ROOT`;
see `packaging/demo/models.json`). Nothing here is copied into the
package, the checkout, or git. File hashes (sha256) are recorded in
`packaging/demo/models.json`.

| Model file (rel under models root) | Bytes | License | Source |
|-----------------------------------|-------|---------|--------|
| `diffusion_models/wan_animate_2_int8_convrot.safetensors` | 16,653,175,528 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |
| `loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | 738,005,744 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |
| `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6,735,906,897 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |
| `clip_vision/clip_vision_h.safetensors` | 1,264,219,396 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |
| `vae/Wan2_1_VAE_bf16.safetensors` | 253,806,278 | apache-2.0 | Comfy-Org/Wan-Animate-2 @ ed158470 |
| `diffusion_models/flux-2-klein-4b-fp8.safetensors` | 4,070,624,520 | apache-2.0 | black-forest-labs/FLUX.2-klein-4b-fp8 |
| `text_encoders/qwen_3_4b.safetensors` | 8,044,982,048 | apache-2.0 | Comfy-Org/vae-text-encorder-for-flux-klein-4b |
| `vae/flux2-vae.safetensors` | 336,211,292 | apache-2.0 | Comfy-Org/vae-text-encorder-for-flux-klein-4b |

License-status notes (measured, not assumed):

- Model **weights not licensed for use** are separated from the runtime
  model set and never loaded: `runtime/video14b/excluded_unlicensed_weights/`
  holds the Wan2.1 CausVid LoRA files excluded for exactly this reason.
- The `vace_14b_fp16_book` profile is NOT selected (open watermark-copy
  blocker, recorded in `app/media_workflows/model_profiles.json`); its
  weights are not part of the demo model manifest.
- License records and artifact hashes in `packaging/demo/*.json` carry
  IDs and digests only - no keys, tokens or credentials.

## Renderer Router Wired Backends (S09-T00-I02)

The renderer router wires ONLY backends verified present on the build machine.
License entries below are limited to what is ACTUALLY wired — nothing
pre-registered for future/unwired components.

| Backend | Routes served | Detected build / runtime | License (as detected) |
|---------|---------------|--------------------------|------------------------|
| **FFmpeg encode path** (`ffmpeg_binary.probe_ffmpeg`) | pose_swap, sprite_affine | FFmpeg 8.1.2-full_build-www.gyan.dev; `configuration:` header contains `--enable-gpl --enable-version3` (no `--enable-nonfree` detected) | GPL-2.0-or-later family build (registry id `ffmpeg-gpl-build`). Local use approved; REDISTRIBUTION of this binary requires full GPL compliance — or ship an LGPL-only FFmpeg build instead |
| **NVIDIA NVENC runtime** (`h264_nvenc` via `nvenc.probe_nvenc`) | pose_swap, sprite_affine (GPU encode) | NVENC SDK 13.1 loaded from installed GeForce driver; NVIDIA GeForce RTX 5070, SM 12.0 | Bundled with the installed NVIDIA display driver; MotionForge does not redistribute any NVIDIA binary |

## License Notes

- **SAM 2.1** is released under Apache 2.0 by Meta AI, permitting commercial use.
- **PyTorch** uses BSD-3-Clause, permitting commercial use.
- **FFmpeg** is built with `--enable-gpl` flags. If distributing binaries, ensure
  compliance with GPL-2.0+ or use an LGPL-only build.
- All Python packages are permissively licensed (MIT, BSD, Apache).
- No proprietary or paywalled APIs are used.
- No user data is sent to external services.

## Compliance Checklist

- [x] All dependencies checked for compatible licenses
- [x] SAM 2.1 checkpoint license verified (Apache 2.0)
- [x] FFmpeg GPL flags noted for distribution awareness
- [x] Renderer-router wired backends license-gated at runtime (`validate_license_for_product_use`); no-permission licenses (CC-BY-NC family) hard-refused
- [x] No commercial API keys required
- [x] Fully offline-capable after model download
- [x] ComfyUI engine + mf-comfy dependency pins recorded (no engine redistribution by MotionForge)
- [x] Demo model weights external + unlicensed weights excluded from the runtime set
- [x] No secrets in license/hash records (`packaging/demo/*.json`, launcher output)
