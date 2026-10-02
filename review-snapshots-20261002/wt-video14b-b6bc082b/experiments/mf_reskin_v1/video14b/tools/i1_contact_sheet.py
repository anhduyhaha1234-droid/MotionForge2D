"""MF-V1-VIDEO14B round I1 -- contact-sheet builder (CPU, evidence tooling).

Builds a labelled contact sheet from a JSON spec so a reviewer can look at the
source window, the references actually read by the encoder and the produced
anchor side by side, at the same canvas index.

usage:
  python i1_contact_sheet.py <spec.json> <out.png>

spec.json:
  {"title": "...", "cell_w": 640, "cell_h": 368, "pad": 8, "label_px": 16,
   "rows": [{"label": "row A", "cells": [{"path": "...png", "label": "BOOK f000"}]}]}

Every cell is drawn at its own aspect ratio, fitted INSIDE cell_w x cell_h with
nearest/bilinear resample, then labelled.  A missing path is drawn as a red
"FILE ABSENT" cell -- a sheet never silently omits a missing input.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def build(spec: dict, out: Path) -> dict:
    cw, ch = int(spec.get("cell_w", 640)), int(spec.get("cell_h", 368))
    pad = int(spec.get("pad", 8))
    lp = int(spec.get("label_px", 16))
    rows = spec["rows"]
    ncol = max(len(r["cells"]) for r in rows)
    row_h = lp + ch + pad
    W = pad + ncol * (cw + pad)
    H = lp + len(rows) * row_h + pad
    sheet = Image.new("RGB", (W, H), (18, 18, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((pad, 2), str(spec.get("title", "")), fill=(255, 255, 255))
    manifest = []
    for ri, row in enumerate(rows):
        y = lp + ri * row_h
        dr.text((pad, y), str(row.get("label", "")), fill=(200, 220, 255))
        for ci, cell in enumerate(row["cells"]):
            x = pad + ci * (cw + pad)
            p = _p(cell["path"])
            entry = {"row": ri, "col": ci, "label": cell.get("label", ""), "path": str(p)}
            if p.is_file():
                im = Image.open(p).convert("RGB")
                entry["src_size"] = list(im.size)
                entry["bytes"] = os.path.getsize(p)
                r = min(cw / im.width, ch / im.height)
                nw, nh = max(1, round(im.width * r)), max(1, round(im.height * r))
                im = im.resize((nw, nh), Image.LANCZOS)
                sheet.paste(im, (x + (cw - nw) // 2, y + lp + (ch - nh) // 2))
                entry["absent"] = False
            else:
                entry["absent"] = True
                dr.rectangle([x, y + lp, x + cw - 1, y + lp + ch - 1], outline=(255, 0, 0), width=3)
                dr.text((x + 8, y + lp + 8), "FILE ABSENT", fill=(255, 0, 0))
            dr.rectangle([x, y + lp, x + cw - 1, y + lp + ch - 1], outline=(70, 70, 80))
            dr.text((x + 2, y + lp + ch + 1), entry["label"], fill=(230, 230, 230))
            manifest.append(entry)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return {"sheet": str(out), "size": list(sheet.size), "cells": manifest,
            "any_absent": any(c["absent"] for c in manifest)}


def main() -> int:
    spec = json.loads(_p(sys.argv[1]).read_text(encoding="utf-8"))
    rep = build(spec, _p(sys.argv[2]))
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return 1 if rep["any_absent"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
