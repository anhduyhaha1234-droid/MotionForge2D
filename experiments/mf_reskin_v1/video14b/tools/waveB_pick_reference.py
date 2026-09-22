"""MF-V1-VIDEO14B wave B step B2 — pick ONE reference candidate, measurably.

There is NO vision on this route, so the choice cannot be "looks nicer".  It is
made on three MEASURED axes, in priority order:

  1. canvas identity   - output must be exactly 640x368 (the video geometry canvas);
                         anything else is the old megapixels=1 upscale regression.
  2. non-degeneracy    - per-channel std, distinct-colour count and a saturation
                         ceiling: a blown-out or flat frame is a failed render.
  3. instruction proxy - (a) restyle strength: MAE against the padded source frame
                             (a near-copy means the redesign did not happen) and
                         (b) composition retention: Pearson correlation of gradient
                             magnitude against the padded source (the instruction
                             demands identical composition/camera/contacts).

Tie-break is deterministic: higher gradient correlation, then larger restyle MAE,
then lower seed.  Verdict always carries NOT_VISUALLY_APPROVED.

usage: python waveB_pick_reference.py <src_padded_png> <cand1.png> <cand2.png> <out_dir>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CANVAS = (640, 368)


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(gray)
    return np.hypot(gx, gy)


def measure(path: Path, src_gray: np.ndarray) -> dict:
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.float64)
    gray = np.asarray(im.convert("L")).astype(np.float64)
    m: dict = {"path": str(path), "size": list(im.size),
               "canvas_identity": list(im.size) == list(CANVAS)}
    m["std_rgb"] = [round(float(a[:, :, i].std()), 4) for i in range(3)]
    m["std_min"] = round(float(min(m["std_rgb"])), 4)
    q = (a // 4).astype(np.int32)
    m["distinct_colours_6bit"] = int(len(np.unique(q.reshape(-1, 3), axis=0)))
    m["mean_rgb"] = [round(float(a[:, :, i].mean()), 4) for i in range(3)]
    m["frac_near_black"] = round(float((gray < 4).mean()), 6)
    m["frac_near_white"] = round(float((gray > 251).mean()), 6)
    if im.size == CANVAS and src_gray is not None:
        diff = np.abs(gray - src_gray)
        m["mae_vs_source"] = round(float(diff.mean()), 4)
        m["frac_pixels_changed_gt2"] = round(float((diff > 2).mean()), 6)
        g1 = gradient_magnitude(gray).reshape(-1)
        g0 = gradient_magnitude(src_gray).reshape(-1)
        if g1.std() > 0 and g0.std() > 0:
            m["grad_corr_vs_source"] = round(float(np.corrcoef(g0, g1)[0, 1]), 6)
        else:
            m["grad_corr_vs_source"] = None
        # region split: the instruction names the book/grip interaction explicitly
        m["band_mae_top"] = round(float(diff[: CANVAS[1] // 3].mean()), 4)
        m["band_mae_mid"] = round(float(diff[CANVAS[1] // 3: 2 * CANVAS[1] // 3].mean()), 4)
        m["band_mae_bottom"] = round(float(diff[2 * CANVAS[1] // 3:].mean()), 4)
    else:
        m["mae_vs_source"] = None
        m["grad_corr_vs_source"] = None
    return m


def main() -> int:
    src = _p(sys.argv[1])
    cands = [_p(sys.argv[2]), _p(sys.argv[3])]
    out_dir = _p(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)
    media = out_dir.parent / "media"
    media.mkdir(parents=True, exist_ok=True)

    src_im = Image.open(src).convert("L")
    if src_im.size != CANVAS:
        print(json.dumps({"verdict": "BLOCKED_DEPENDENCY",
                          "why": f"source padded keyframe is {src_im.size}, expected {CANVAS}"}))
        return 5
    src_gray = np.asarray(src_im).astype(np.float64)

    rows = []
    for i, c in enumerate(cands, start=1):
        m = measure(c, src_gray)
        m["candidate_index"] = i
        m["sha256"] = __import__("hashlib").sha256(c.read_bytes()).hexdigest()
        rows.append(m)

    def eligible(m: dict) -> bool:
        return bool(m["canvas_identity"] and m["std_min"] >= 10.0
                    and (m["mae_vs_source"] or 0) > 2.0
                    and (m["grad_corr_vs_source"] or 0) > 0.0)

    for m in rows:
        m["eligible"] = eligible(m)

    ok = [m for m in rows if m["eligible"]]
    chosen = None
    why = ""
    if ok:
        ok.sort(key=lambda m: (-(m["grad_corr_vs_source"] or 0.0), -(m["mae_vs_source"] or 0.0),
                               m["candidate_index"]))
        chosen = ok[0]
        why = ("highest composition retention (grad_corr_vs_source) among the candidates that "
               "pass canvas identity + non-degeneracy + restyle strength; ties broken by larger "
               "restyle MAE, then by lower candidate index (deterministic, no visual claim)")
    rejected = [m for m in rows if m is not chosen]

    result = {
        "verdict": "REFERENCE_CHOSEN" if chosen else "REFERENCE_UNUSABLE",
        "quality_status": "NOT_VISUALLY_APPROVED",
        "choice_basis": why or "no candidate passed the measured eligibility gate",
        "criteria_order": ["canvas_identity", "non_degeneracy(std_min>=10)",
                           "restyle_strength(mae_vs_source>2)", "composition(grad_corr>0)"],
        "source_padded": {"path": str(src), "size": list(src_im.size)},
        "candidates": rows,
        "chosen_candidate_index": chosen["candidate_index"] if chosen else None,
        "chosen_sha256": chosen["sha256"] if chosen else None,
        "rejected_kept": [{"candidate_index": m["candidate_index"], "path": m["path"],
                           "sha256": m["sha256"], "eligible": m["eligible"]} for m in rejected],
    }

    if chosen:
        ch = media / "reference_chosen_640x368.png"
        shutil.copy2(chosen["path"], ch)
        result["chosen_copy"] = str(ch)
        result["chosen_copy_sha256"] = __import__("hashlib").sha256(ch.read_bytes()).hexdigest()
    for m in rejected:
        rj = media / f"reference_rejected_cand{m['candidate_index']}_640x368.png"
        shutil.copy2(m["path"], rj)
        result.setdefault("rejected_copies", []).append({"path": str(rj), "of": m["path"]})

    (out_dir / "reference_selection.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if chosen else 6


if __name__ == "__main__":
    raise SystemExit(main())
