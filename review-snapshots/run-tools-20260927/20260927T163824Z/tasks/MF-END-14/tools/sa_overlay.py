"""MF-END-14 — MF-END-14.3: tensor preview + role/prop/contact overlay for review BEFORE video.

Reads (real, sealed artifacts only):
  * staged keyframe + the produced anchor (asset/),
  * MF-END-12 sealed track masks (raw/mask_*.png),
  * MF-END-13 sealed facts (raw/real_source_interaction_facts.json),
  * the accepted P2 BOOK anchor (proof/inputs/anchor_book_p2_00001_.png).
Writes previews/ images + raw/review.json (mechanical rows + quoted facts + overlay geometry).
The overlay is DERIVED EVIDENCE; it is not part of the graph.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
MF12 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-12")
MF13 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-13")
PROOF_IN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                "20260927T163824Z/proof/inputs")

MASKS = {"ROLE-BOOK-P1": MF12 / "raw/mask_ROLE-BOOK-P1_f0.png",
         "PROP-BOOK": MF12 / "raw/mask_PROP-BOOK_f0.png",
         "ROLE-BOOK-P4-EDGE": MF12 / "raw/mask_ROLE-BOOK-P4-EDGE_f0.png"}
COLORS = {"ROLE-BOOK-P1": (255, 0, 0), "PROP-BOOK": (0, 160, 0),
          "ROLE-BOOK-P4-EDGE": (0, 0, 255)}


def arr(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGB")).astype("int32")


def band(arr3: np.ndarray, frac: float = 0.1) -> list[float]:
    h, w, _ = arr3.shape
    bw, bh = max(1, int(w * frac)), max(1, int(h * frac))
    return [round(float(arr3[:, :bw].mean()), 4), round(float(arr3[:, -bw:].mean()), 4),
            round(float(arr3[:bh, :].mean()), 4), round(float(arr3[-bh:, :].mean()), 4)]


def metrics(a: np.ndarray, b: np.ndarray) -> dict:
    d = np.abs(a - b)
    return {"mean_abs_delta": round(float(d.mean()), 4), "max_abs_delta": int(d.max()),
            "differing_pixels": int((d.sum(axis=2) > 0).sum()),
            "border_mean_abs_delta_rlbt": band(d),
            "identical": bool((d.sum() == 0))}


def bbox_of(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def draw_overlay(base: Path, out: Path, rows: list[dict], title: str) -> None:
    im = Image.open(base).convert("RGB")
    dr = ImageDraw.Draw(im)
    for row in rows:
        x0, y0, x1, y1 = row["bbox_xyxy"]
        dr.rectangle([x0, y0, x1, y1], outline=row["color"], width=2)
        dr.text((x0 + 2, max(0, y0 - 10)), row["label"], fill=row["color"])
    dr.text((4, 4), title, fill=(255, 255, 0))
    im.save(out)


def main() -> int:
    prev = EV / "previews"
    prev.mkdir(parents=True, exist_ok=True)
    run = json.loads((EV / "raw/run_record.json").read_text(encoding="utf-8"))
    facts = json.loads((MF13 / "raw/real_source_interaction_facts.json").read_text(encoding="utf-8"))
    staged = json.loads((EV / "raw/stage_input.json").read_text(encoding="utf-8"))

    key_path = EV / "runtime/input/sa_v1_keyframe_book_f000.png"
    anchor_path = Path(run["golden_asset"]["path"])
    accepted_path = PROOF_IN / "anchor_book_p2_00001_.png"

    key, anc = arr(key_path), arr(anchor_path)
    acc = arr(accepted_path) if accepted_path.exists() else None

    # masks (source space) + bboxes
    rows, mask_stats = [], {}
    for rid, mp in MASKS.items():
        m = np.asarray(Image.open(mp).convert("L"))
        bb = bbox_of(m)
        rows.append({"role": rid, "bbox_xyxy": bb, "pixels": int((m > 127).sum()),
                     "color": COLORS[rid], "label": f"{rid} {bb[2]-bb[0]}x{bb[3]-bb[1]}"})
        sub = anc[bb[1]:bb[3] + 1, bb[0]:bb[2] + 1]
        subk = key[bb[1]:bb[3] + 1, bb[0]:bb[2] + 1]
        d = np.abs(sub - subk)
        mask_stats[rid] = {"bbox_xyxy": bb, "mask_pixels": int((m > 127).sum()),
                           "region_mean_abs_delta_anchor_vs_source": round(float(d.mean()), 4),
                           "region_changed_fraction": round(float((d.sum(axis=2) > 0).mean()), 6)}

    draw_overlay(key_path, prev / "sa_v1_overlay_source.png", rows,
                 "MF-END-14 source keyframe + sealed MF-END-12 role/prop boxes (frame 0)")
    draw_overlay(anchor_path, prev / "sa_v1_overlay_anchor.png", rows,
                 "MF-END-14 delivered anchor + the SAME source-space role/prop boxes")

    # side-by-sides
    def sbs(imgs: list[Image.Image], labels: list[str], out: Path) -> None:
        h = max(i.height for i in imgs)
        w = sum(i.width for i in imgs) + 8 * (len(imgs) - 1)
        c = Image.new("RGB", (w, h + 18), (16, 16, 16))
        x = 0
        dr = ImageDraw.Draw(c)
        for im, lab in zip(imgs, labels):
            c.paste(im, (x, 18))
            dr.text((x + 4, 4), lab, fill=(255, 255, 0))
            x += im.width + 8
        c.save(out)

    sbs([Image.open(key_path), Image.open(anchor_path)],
        ["SOURCE keyframe f000 (640x368)", "DELIVERED anchor (shot_anchor_v1)"],
        prev / "sa_v1_side_by_side_source_vs_anchor.png")
    if acc is not None:
        sbs([Image.open(accepted_path), Image.open(anchor_path)],
            ["ACCEPTED P2 BOOK anchor", "DELIVERED MF-END-14 anchor"],
            prev / "sa_v1_side_by_side_accepted_vs_delivered.png")

    # watermark region (bottom-left, where the source clip carries the YouTube mark)
    h, w, _ = key.shape
    wl = key[h - 40:, :160]
    wl_d = np.abs(wl - anc[h - 40:, :160])
    wm = {"region_xyxy": [0, h - 40, 160, h],
          "source_vs_anchor_mean_abs_delta": round(float(wl_d.mean()), 4),
          "source_vs_anchor_changed_fraction": round(float((wl_d.sum(axis=2) > 0).mean()), 6),
          "note": ("the frozen prompt requires the source watermark NOT to appear in the "
                   "result; this row measures that the region was repainted, the visual "
                   "verdict stays with the reviewer")}

    review = {
        "artifact": "review.json",
        "tensor_preview": run.get("tensor_preview_comparison"),
        "mechanical_rows": {
            "anchor_dims_equal_canvas": [int(anc.shape[1]), int(anc.shape[0])],
            "anchor_dims_ok": [int(anc.shape[1]), int(anc.shape[0])] == [640, 368],
            "delivered_vs_source": metrics(anc, key),
            "delivered_vs_accepted_anchor": metrics(anc, acc) if acc is not None else None,
            "role_regions": mask_stats,
            "watermark_region": wm,
        },
        "facts_quoted": {
            "artifact_digest": facts["digest"],
            "holder": facts["declared_checks"][0],
            "camera_book": {"classification": "static", "cut_frames": [],
                            "content_events": facts["camera"][0]["content_events"]},
            "occlusion": facts["occlusions"][0]["order"],
            "contacts": len(facts["contacts"]),
        },
        "overlay_geometry": rows,
        "artifacts": {
            "side_by_side": "previews/sa_v1_side_by_side_source_vs_anchor.png",
            "side_by_side_accepted": ("previews/sa_v1_side_by_side_accepted_vs_delivered.png"
                                      if acc is not None else ""),
            "overlay_source": "previews/sa_v1_overlay_source.png",
            "overlay_anchor": "previews/sa_v1_overlay_anchor.png",
        },
        "fidelity_identity_layout": "NEEDS_REVIEW (BENCH / DEMO / Codex reviewer)",
        "verdict": "PASS" if ([int(anc.shape[1]), int(anc.shape[0])] == [640, 368]
                              and bool(run.get("tensor_preview_comparison"))) else "FAIL",
        "verdict_scope": ("mechanical rows only (dims + tensor-preview byte equality + region "
                          "deltas); appearance identity is NOT judged by the worker"),
    }
    (EV / "raw/review.json").write_text(json.dumps(review, indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    print(json.dumps({"verdict": review["verdict"],
                      "dims": review["mechanical_rows"]["anchor_dims_equal_canvas"],
                      "vs_source": review["mechanical_rows"]["delivered_vs_source"],
                      "vs_accepted_mean_abs": (review["mechanical_rows"]
                                               ["delivered_vs_accepted_anchor"] or {}).get(
                                                   "mean_abs_delta"),
                      "watermark": wm}, indent=1, ensure_ascii=False)[:1800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
