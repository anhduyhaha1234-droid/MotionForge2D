"""MF-END-08 — review evidence: side-by-side + mechanical style metrics + the recorded verdict.

The VERDICT rows below are the reviewer's observations of the asset image AS RENDERED
(inspected directly, not inferred from a path or text). The mechanical metrics are computed
here and cannot upgrade or replace them.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
REF = EV / "previews/ra_v1_ref_composited.png"
ASSET = EV / "asset/dan_choi_back_00001_.png"
NEUTRAL = (128, 128, 128)


def sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def metrics(p: Path) -> dict:
    im = Image.open(p).convert("RGB")
    a = np.asarray(im).astype("int32")
    near_bg = (np.abs(a - np.array(NEUTRAL)).max(axis=2) <= 8).mean()
    near_black = (a.max(axis=2) <= 40).mean()
    return {"file": str(p).replace("\\", "/"), "dims": list(im.size), "mode": im.mode,
            "sha256": sha_b(p.read_bytes()), "bytes": p.stat().st_size,
            "near_neutral_128_fraction": round(float(near_bg), 6),
            "near_black_fraction": round(float(near_black), 6),
            "mean_rgb": [round(float(v), 2) for v in a.reshape(-1, 3).mean(axis=0)]}


def main() -> int:
    ref, out = Image.open(REF).convert("RGB"), Image.open(ASSET).convert("RGB")
    w, h, gap = 1024, 1024, 24
    sheet = Image.new("RGB", (w * 2 + gap, h), (255, 255, 255))
    sheet.paste(ref.resize((w, h)), (0, 0))
    sheet.paste(out.resize((w, h)), (w + gap, 0))
    prev = EV / "previews"
    side = prev / "review_side_by_side_ref_left_asset_right.png"
    sheet.save(side)
    det = prev / "review_asset_detail_upper.png"
    Image.open(ASSET).convert("RGB").crop((96, 60, 928, 700)).save(det)

    rec = {
        "artifact": "review.json",
        "reviewer": "Hermes owner session (native vision: the image was rendered into the "
                    "reviewer's context and inspected directly)",
        "reviewed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "artifacts": {"identity_reference": metrics(REF), "generated_asset": metrics(ASSET),
                      "side_by_side": str(side).replace("\\", "/"),
                      "detail_crop": str(det).replace("\\", "/")},
        "rubric": [
            {"criterion": "view == back (no face/eyes visible)",
             "verdict": "PASS",
             "observed": ("the figure is drawn from directly behind: the head shows the back of "
                          "the black cap plus a narrow pale rim of the back of the head; no eyes, "
                          "no face, no facial features anywhere in the image")},
            {"criterion": "identity preserved (same design elements)",
             "verdict": "PASS",
             "observed": ("same black baseball cap with its brim to the left and the same two "
                          "small dot marks, same black hoodie (now seen from its back, hood flat at "
                          "the neck), same black trousers, same black sneakers with lace details, "
                          "same tail curling out to the left, same monochrome palette")},
            {"criterion": "clothes / proportions NOT changed between views",
             "verdict": "PASS",
             "observed": ("no garment was swapped or recoloured; the head-to-body ratio, the "
                          "sleeve/trouser shapes and the sneaker shapes read the same as the "
                          "reference; the pose stays seated cross-legged")},
            {"criterion": "style == flat black ink doodle on plain grey",
             "verdict": "PASS",
             "observed": ("solid flat black fills with one thin outline on the same flat grey "
                          "field, no gradients, no shading, no photographic texture")},
            {"criterion": "no extra colours / props / text / watermark",
             "verdict": "PASS",
             "observed": ("the only colours present are black, the pale head/hand tone and the "
                          "neutral grey field; no STREET label (correctly hidden on the chest "
                          "side), no watermark, no added background objects; the only held object "
                          "is the same phone, now a small black shape held at the right hip")},
            {"criterion": "declared output dimensions",
             "verdict": "PASS", "observed": "1024x1024 RGB PNG, equal to the declared canvas"},
        ],
        "disclosed_deviations": [
            "the two small cap marks that sit on the SIDE strap aperture in the reference were "
            "redrawn on the cap crown from this angle (still black-on-black; no identity break)",
            "the pale area behind the cap reads as the back of the head/hood rim - the reference's "
            "pale face area is not visible from behind by construction",
            "the arms and both hands are hidden behind the body; one hand and the phone are "
            "visible at the right hip, as the prompt requested",
        ],
        "verdict": "PASS",
        "scope_note": ("review covers view + identity + style + dimensions of THIS asset; it does "
                       "not assert library ingest, alpha/background removal, or any QC beyond the "
                       "declared rubric"),
    }
    (EV / "raw/review.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    print(json.dumps({k: v for k, v in rec.items()
                      if k in ("verdict", "artifacts", "rubric")}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
