"""MF-END-14 — stage the 4 real inputs into the isolated runtime input dir (byte copies) and
compute the OFFLINE tensor-truth expectations for the prefix (tensor-preview) job.

Node semantics replicated (float32, measured in the accepted proof / MF-END-08):
  * composite ONCE: out = rgb*(alpha/255) + neutral*(1 - alpha/255); neutral = (128,128,128)
    (opaque inputs -> the identity path)
  * resize: ResizeImageMaskNode 'scale longer dimension' -> python round() (half-to-even),
    pixels torch.nn.functional.interpolate(size=(h,w), mode='area')
  * display: np.clip(255.0*t, 0, 255).astype(uint8)  (SaveImage's conversion)
Read-only on the proof inputs; writes only into the MF-END-14 evidence tree.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
IN_DIR = EV / "runtime/input"
PROOF_IN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                "20260927T163824Z/proof/inputs")
RAW_ARTWORK = Path("C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-p1-ui-build/"
                   "presets/characters/dan_choi_standing.png")

NEUTRAL = (128, 128, 128)
REF_LONGER = 368

STAGE = [
    ("KEY", "i1_BOOK_f000_640x368.png", "sa_v1_keyframe_book_f000.png"),
    ("R1", "i1d_cast_boy_hacker_sitting_on_neutral_bg.png", "sa_v1_ref_p1_boy_hacker.png"),
    ("R2", "i1d_cast_dan_choi_standing_on_neutral_bg.png", "sa_v1_ref_p2_dan_choi.png"),
    ("R3", "i1d_cast_gau_nau_back_on_neutral_bg.png", "sa_v1_ref_p3_gau_nau_back.png"),
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def node_longer_side_dims(w: int, h: int, longer: int) -> list[int]:
    if h > w:
        return [int(round((w / h) * longer)), int(longer)]
    if w > h:
        return [int(longer), int(round((h / w) * longer))]
    return [int(longer), int(longer)]


def server_faithful_composite(img: Image.Image) -> torch.Tensor:
    """LoadImage pixels [0,1] + MASK=1-alpha -> InvertMask -> ImageCompositeMasked(
    mask*src + (1-mask)*dst) with dst = EmptyImage 128/255."""
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    rgb = torch.from_numpy(np.ascontiguousarray(arr[:, :, :3])).to(torch.float32) / 255.0
    a = torch.from_numpy(np.ascontiguousarray(arr[:, :, 3])).to(torch.float32) / 255.0
    mask = 1.0 - a
    inv = torch.ones_like(mask) - mask
    src = rgb.unsqueeze(0)
    dst = torch.full_like(src, 128.0 / 255.0)
    inv4 = inv.unsqueeze(0).unsqueeze(-1)
    return inv4 * src + (torch.ones_like(inv4) - inv4) * dst


def display_of(t: torch.Tensor) -> np.ndarray:
    return np.clip(255.0 * t.detach().cpu().numpy(), 0, 255).astype(np.uint8)


def main() -> int:
    IN_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"artifact": "stage_input.json", "one_job_at_a_time": True, "staged": [],
           "tensor_preview_expected": {}}
    for tag, src_name, staged_name in STAGE:
        src = PROOF_IN / src_name
        data = src.read_bytes()
        staged = IN_DIR / staged_name
        staged.write_bytes(data)
        assert sha256_bytes(staged.read_bytes()) == sha256_bytes(data), "staging copy drift"
        img = Image.open(staged)
        w, h = img.size
        comp = server_faithful_composite(img)
        disp = display_of(comp)
        png = Image.fromarray(disp[0], mode="RGB")
        prev = EV / "previews"
        prev.mkdir(parents=True, exist_ok=True)
        png.save(prev / f"sa_v1_offline_{tag.lower()}_composite.png")
        staged_rgb = np.asarray(img.convert("RGB")).astype(np.int32)
        identity_px = int((np.abs(staged_rgb - disp[0].astype(np.int32)).sum(axis=2) > 0).sum())
        entry = {"tag": tag, "source_path": str(src).replace("\\", "/"),
                 "source_sha256": sha256_bytes(data), "staged_file": staged_name,
                 "staged_path": str(staged).replace("\\", "/"), "bytes": len(data),
                 "dims": [w, h], "mode": img.mode,
                 "composite_display_pixels_sha256": sha256_bytes(disp.tobytes()),
                 "composite_identity_vs_staged_differing_pixels": identity_px}
        exp = {"composite_display_pixels_sha256": sha256_bytes(disp.tobytes()),
               "composite_display_dims": [w, h]}
        if tag != "KEY":
            dims = node_longer_side_dims(w, h, REF_LONGER)
            resized = torch.nn.functional.interpolate(
                comp.movedim(-1, 1), size=(dims[1], dims[0]), mode="area").movedim(1, -1)
            rdisp = display_of(resized)
            Image.fromarray(rdisp[0], mode="RGB").save(prev / f"sa_v1_offline_{tag.lower()}_resized.png")
            entry["resize_plan"] = {"resize_type": "scale longer dimension",
                                    "longer_size": REF_LONGER, "scale_method": "area",
                                    "source_wh": [w, h], "resized_wh": dims}
            exp["resized_display_pixels_sha256"] = sha256_bytes(rdisp.tobytes())
            exp["resized_display_dims"] = dims
        rec["staged"].append(entry)
        rec["tensor_preview_expected"][tag] = exp

    # independent cross-check: composite(raw RGBA artwork) == staged on-neutral ref (float64+rint)
    if RAW_ARTWORK.exists():
        raw = Image.open(RAW_ARTWORK)
        arr = np.asarray(raw.convert("RGBA")).astype("float64")
        alpha = arr[:, :, 3:4] / 255.0
        out = arr[:, :, :3] * alpha + np.asarray(NEUTRAL, dtype="float64") * (1.0 - alpha)
        ref = Image.fromarray(np.rint(out).clip(0, 255).astype("uint8"), mode="RGB")
        staged_ref = np.asarray(Image.open(IN_DIR / "sa_v1_ref_p2_dan_choi.png").convert("RGB")).astype("int32")
        d = np.abs(np.asarray(ref).astype("int32") - staged_ref)
        rec["alpha_proof_derived_crosscheck"] = {
            "raw_artwork": str(RAW_ARTWORK).replace("\\", "/"),
            "raw_artwork_sha256": sha256_bytes(RAW_ARTWORK.read_bytes()),
            "raw_mode": raw.mode, "raw_alpha_extrema": list(raw.getchannel("A").getextrema()),
            "implementation": "float64 + rint (independent of the float32 node path)",
            "staged_ref": "sa_v1_ref_p2_dan_choi.png",
            "differing_pixels": int((d.sum(axis=2) > 0).sum()),
            "max_abs_delta_0_255": int(d.max()),
        }
    rec["note"] = ("expected values are the OFFLINE float32 node path; the isolated-server prefix "
                   "job renders the same tensors through the REAL nodes and the pixels are "
                   "compared (measured, no assumption)")
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    (EV / "raw/stage_input.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    for e in rec["staged"]:
        print(e["tag"], e["staged_file"], e["dims"], e["mode"], "identity_diff_px=",
              e["composite_identity_vs_staged_differing_pixels"])
    print("crosscheck:", json.dumps(rec.get("alpha_proof_derived_crosscheck"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
