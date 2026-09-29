"""P2 gate tooling: side-by-side previews, a contact sheet and the measurable part of the gate.

Everything objective is MEASURED (size, palette count, edge density, difference vs the source
frame, border correlation as a camera proxy).  The criteria that need eyes are listed with
`measured: null` and `verdict: UNJUDGED` and are decided from the real image in the vision pass -
never auto-passed here.  `quality_accepted` stays false: that verdict is not the worker's.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import numpy as np
from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
ANCHORS = PROOF / "output" / "anchors"
PREV = PROOF / "evidence" / "previews"
INPUTS = PROOF / "inputs"
SHOTS = {"BOOK": "i1_BOOK_f000_640x368.png", "TURN": "i1_TURN_f000_640x368.png",
         "OCC": "i1_OCC_f000_640x368.png"}


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def metrics(src: Image.Image, out: Image.Image) -> dict:
    a = np.asarray(src.convert("RGB")).astype(np.int32)
    b = np.asarray(out.convert("RGB").resize(src.size, Image.Resampling.BILINEAR)).astype(np.int32)
    d = np.abs(a - b)
    # edge density: fraction of pixels whose right neighbour differs by > 12
    e = (np.abs(np.diff(b, axis=1)).sum(axis=2) > 12).mean()
    borders = ((d[:4].mean(), d[-4:].mean(), d[:, :4].mean(), d[:, -4:].mean()))
    return {"source_dims": list(src.size), "output_dims": list(out.size),
            "mean_abs_delta_vs_source": round(float(d.mean()), 4),
            "max_abs_delta_vs_source": int(d.max()),
            "edge_density": round(float(e), 5),
            "border_delta_mean_rlbt": [round(float(x), 3) for x in borders],
            "unique_colours_output": int(len(np.unique(np.asarray(out.convert("RGB"))
                                                       .reshape(-1, 3), axis=0))),
            "unique_colours_source": int(len(np.unique(np.asarray(src.convert("RGB"))
                                                       .reshape(-1, 3), axis=0))),
            "is_uniform_block": bool(len(np.unique(np.asarray(out.convert("RGB"))
                                                   .reshape(-1, 3), axis=0)) <= 2),
            "identical_to_source": bool(d.max() == 0)}


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    gate = {"artifact": "P2_ANCHOR_GATES.json", "round": "R28-PROOF-P2",
            "quality_accepted": False,
            "quality_verdict_owner": "BENCH / DEMO / Codex reviewer - NOT the worker",
            "criteria_source": "packet §2.4 + COMFY_UNITS_RESEARCH.md §7 P2",
            "shots": {}}
    tiles = []
    for shot, frame in SHOTS.items():
        src_p = INPUTS / frame
        outs = sorted(ANCHORS.glob(f"anchor_{shot.lower()}_p2_*.png"))
        row = {"source_frame": frame, "source_sha256": sha(src_p) if src_p.is_file() else None,
               "anchors": [], "criteria": {}}
        for o in outs:
            with Image.open(src_p) as s, Image.open(o) as im:
                m = metrics(s, im)
                canvas = Image.new("RGB", (s.size[0] + im.size[0] + 8, max(s.size[1], im.size[1])),
                                   (24, 24, 28))
                canvas.paste(s.convert("RGB"), (0, 0))
                canvas.paste(im.convert("RGB"), (s.size[0] + 8, 0))
                sp = PREV / f"p2_{shot.lower()}_sidebyside_{o.stem}.png"
                canvas.save(sp)
                tiles.append((shot, s.convert("RGB"), im.convert("RGB")))
            row["anchors"].append({"file": o.name, "bytes": o.stat().st_size, "sha256": sha(o),
                                   "side_by_side": f"previews/{sp.name}", "metrics": m})
        gate["shots"][shot] = row
    if tiles:
        w, h = tiles[0][1].size
        sheet = Image.new("RGB", (w, h * 2 * len(tiles) + 8 * len(tiles) + 24), (24, 24, 28))
        d = ImageDraw.Draw(sheet)
        y = 4
        for shot, s, im in tiles:
            d.text((4, y + 2), f"{shot}  source (top) | anchor P2 (bottom)", fill=(230, 230, 230))
            y += 18
            sheet.paste(s, (0, y))
            sheet.paste(im, (0, y + h + 4))
            y += h * 2 + 8
        sheet.save(PREV / "p2_contact_sheet_source_vs_anchor.png")
        gate["contact_sheet"] = "previews/p2_contact_sheet_source_vs_anchor.png"
    gate["criterion_placeholders"] = {
        "all_roles_present_incl_partial_P4": {"measured": None, "verdict": "UNJUDGED"},
        "correct_holder_BOOK_P1_book_closed_at_frame0": {"measured": None, "verdict": "UNJUDGED"},
        "layout_scale_crop_camera_direction_kept": {"measured": None, "verdict": "UNJUDGED"},
        "no_people_merged": {"measured": None, "verdict": "UNJUDGED"},
        "background_props_follow_style_policy": {"measured": None, "verdict": "UNJUDGED"},
        "placeholders_are_not_claimed_as_appearance": {"declared": True, "verdict": "POLICY"},
    }
    (PROOF / "evidence" / "P2_ANCHOR_GATES.json").write_text(
        json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({s: {"anchors": len(v["anchors"]),
                          "dims": (v["anchors"][0]["metrics"]["output_dims"]
                                   if v["anchors"] else None)}
                      for s, v in gate["shots"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
