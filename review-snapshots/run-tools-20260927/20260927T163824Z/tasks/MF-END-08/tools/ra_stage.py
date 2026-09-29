"""MF-END-08 — stage the identity reference + build the tensor-truth preview (CPU only).

Semantics copied from the ACCEPTED proof tool
(`mf_reskin_v1/video14b/tools/i1_make_anchor_graphs.py`, R28 V-1/V-2):
  * composite ONCE:  out = rgb*(alpha/255) + neutral*(1 - alpha/255); neutral = (128,128,128)
  * node dims:       ResizeImageMaskNode 'scale longer dimension' -> python round() (half-to-even)
  * node pixels:     torch.nn.functional.interpolate(size=(h,w), mode='area') on the float32
                     [1,C,H,W] tensor LoadImage hands over; returned [1,H,W,C]
  * display:         np.clip(255.0*t, 0, 255).astype(uint8)  (SaveImage's conversion)

Writes the staged input PNG into the MF-END-08 isolated runtime input dir and a JSON record.
Read-only on the character presets and on the pinned runtime.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
IN_DIR = EV / "runtime" / "input"
PRESET = Path("C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-p1-ui-build/presets/characters/dan_choi_standing.png")
NEUTRAL_RGB = (128, 128, 128)
NEUTRAL_INT = (128 << 16) | (128 << 8) | 128          # EmptyImage color widget = 0xRRGGBB
REF_LONGER = 768                                      # RefImageMaskNode 'scale longer dimension'
STAGED_NAME = "ra_v1_ref_dan_choi.png"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def node_longer_side_dims(w: int, h: int, longer: int) -> list[int]:
    if h > w:
        return [int(round((w / h) * longer)), int(longer)]
    if w > h:
        return [int(longer), int(round((h / w) * longer))]
    return [int(longer), int(longer)]


def composite_rgb(img: Image.Image, bg=NEUTRAL_RGB) -> Image.Image:
    a = np.asarray(img.convert("RGBA")).astype("float64")
    alpha = a[:, :, 3:4] / 255.0
    out = a[:, :, :3] * alpha + np.asarray(bg, dtype="float64") * (1.0 - alpha)
    return Image.fromarray(np.rint(out).clip(0, 255).astype("uint8"), mode="RGB")


def float_tensor_hash(t: torch.Tensor) -> str:
    return hashlib.sha256(t.detach().contiguous().cpu().numpy().tobytes()).hexdigest()


def preview(img_rgb: Image.Image, size: list[int]) -> dict:
    a = np.asarray(img_rgb.convert("RGB"), dtype=np.float32) / 255.0
    chw = torch.from_numpy(a).unsqueeze(0).movedim(-1, 1).contiguous()
    resized = torch.nn.functional.interpolate(
        chw, size=(int(size[1]), int(size[0])), mode="area").movedim(1, -1)
    disp = np.clip(255.0 * resized.detach().cpu().numpy(), 0, 255).astype(np.uint8)
    return {"tensor_shape_bhwc": [int(v) for v in resized.shape],
            "tensor_dtype": str(resized.dtype),
            "tensor_hash_before_quantization": float_tensor_hash(resized),
            "display_pixels_sha256": sha256_bytes(disp.tobytes()),
            "expected_png_bytes_sha256": None,  # filled by the caller after the server-side run
            "_display": disp}


def server_faithful_composite(rgba: Image.Image) -> torch.Tensor:
    """The exact node path in float32: LoadImage pixels [0,1] + MASK=1-alpha -> InvertMask ->
    ImageCompositeMasked(mask*src + (1-mask)*dst) with dst = EmptyImage 128/255."""
    arr = np.asarray(rgba.convert("RGBA"))
    rgb = torch.from_numpy(np.ascontiguousarray(arr[:, :, :3])).to(torch.float32) / 255.0
    a = torch.from_numpy(np.ascontiguousarray(arr[:, :, 3])).to(torch.float32) / 255.0
    mask = 1.0 - a                                       # LoadImage MASK convention (measured)
    inv = torch.ones_like(mask) - mask                   # InvertMask  -> alpha
    src = rgb.unsqueeze(0)                               # [1,H,W,C]
    dst = torch.full_like(src, 128.0 / 255.0)
    inv4 = inv.unsqueeze(0).unsqueeze(-1)                # [1,H,W,1]
    return inv4 * src + (torch.ones_like(inv4) - inv4) * dst


def display_of(t: torch.Tensor) -> np.ndarray:
    return np.clip(255.0 * t.detach().cpu().numpy(), 0, 255).astype(np.uint8)


def main() -> int:
    IN_DIR.mkdir(parents=True, exist_ok=True)
    src = Image.open(PRESET)
    src_rgba = src.convert("RGBA")
    arr = np.asarray(src_rgba)
    alpha = arr[:, :, 3]
    src_bytes = PRESET.read_bytes()

    # STAGED input = the RAW authored artwork (RGBA, byte copy). The GRAPH performs the
    # composite itself, so the in-graph alpha policy is really exercised by the golden run.
    staged = IN_DIR / STAGED_NAME
    staged.write_bytes(src_bytes)
    staged_bytes = staged.read_bytes()

    comp_t = server_faithful_composite(src_rgba)
    comp_disp = display_of(comp_t)
    comp_png = Image.fromarray(comp_disp[0], mode="RGB")
    prev = EV / "previews"
    prev.mkdir(parents=True, exist_ok=True)
    comp_png.save(prev / "ra_v1_ref_composited.png")

    w, h = src_rgba.size
    dims = node_longer_side_dims(w, h, REF_LONGER)
    chw = comp_t.movedim(-1, 1)
    resized = torch.nn.functional.interpolate(chw, size=(dims[1], dims[0]), mode="area")
    res_disp = display_of(resized.movedim(1, -1))

    # cross-check vs the ACCEPTED proof's derived input (independent implementation, float64+rint)
    proof = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                 "mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B/"
                 "derived_inference_input/i1d_cast_dan_choi_standing_on_neutral_bg.png")
    proof_delta = None
    if proof.exists():
        pv = np.asarray(Image.open(proof).convert("RGB")).astype("int32")
        d = np.abs(pv - comp_disp[0].astype("int32"))
        proof_delta = {"file": str(proof).replace("\\", "/"),
                       "sha256": sha256_bytes(proof.read_bytes()),
                       "differing_pixels": int((d.sum(axis=2) > 0).sum()),
                       "max_abs_delta_0_255": int(d.max()),
                       "note": "independent implementation (float64 + rint) vs this float32 path"}

    rec = {
        "artifact": "stage_input.json",
        "staged_input": {"file": STAGED_NAME, "path": str(staged).replace("\\", "/"),
                         "bytes": len(staged_bytes), "sha256": sha256_bytes(staged_bytes),
                         "dims": [w, h], "mode": "RGBA (raw authored artwork byte-copy)",
                         "why_raw": ("the GRAPH composites RGBA once on the declared neutral; "
                                     "staging the raw artwork is what exercises that policy")},
        "source_artwork": {"path": str(PRESET).replace("\\", "/"),
                           "bytes": PRESET.stat().st_size, "sha256": sha256_bytes(src_bytes),
                           "dims": list(src.size), "mode": src.mode,
                           "alpha_extrema": [int(alpha.min()), int(alpha.max())],
                           "fully_transparent_fraction": round(float((alpha == 0).mean()), 8),
                           "frozen_reference": ("this sha is the accepted proof's BOOK-P2 cast "
                                                "reference (P1_UNIT_MANIFESTS / shot_reskin "
                                                "FROZEN_EXAMPLES _FROZEN_REF_SHA)")},
        "alpha_policy_applied": {"neutral_rgb": list(NEUTRAL_RGB),
                                 "emptyimage_color_int": NEUTRAL_INT,
                                 "formula": "out = mask*src + (1 - mask)*dst ; mask = InvertMask(1-alpha)",
                                 "applied_times": 1, "in_graph": True},
        "resize_plan": {"resize_type": "scale longer dimension", "longer_size": REF_LONGER,
                        "scale_method": "area", "source_wh": [w, h], "resized_wh": dims,
                        "no_crop": True, "no_stretch": True,
                        "node_formula": "comfy_extras/nodes_post_processing.py scale_longer_dimension"},
        "tensor_preview_expected": {
            "implementation": ("float32 node path: LoadImage[0,1] -> invert mask -> "
                               "ImageCompositeMasked -> F.interpolate(mode='area') -> [1,H,W,C]"),
            "composite_display_pixels_sha256": sha256_bytes(comp_disp.tobytes()),
            "composite_display_dims": [w, h],
            "resized_display_pixels_sha256": sha256_bytes(res_disp.tobytes()),
            "resized_display_dims": dims,
            "display_conversion": "np.clip(255.0*t,0,255).astype(uint8) (SaveImage's own)",
            "proof_derived_input_delta": proof_delta,
        },
        "note": ("expected values = the OFFLINE float32 node path; the isolated server run "
                 "produces the same two images through the real nodes and the pixels are "
                 "compared (measured delta, no assumption)"),
    }
    out = EV / "raw" / "stage_input.json"
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(rec, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
