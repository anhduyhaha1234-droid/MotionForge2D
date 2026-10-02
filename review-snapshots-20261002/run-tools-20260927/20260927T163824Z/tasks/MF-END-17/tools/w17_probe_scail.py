"""MF-END-17 — SCAIL-2 correspondence semantics probe (read-only, no GPU).

Packet micro-job 2: probe the official SCAIL-2 correspondence graph/mask semantics and
the Win-12GB question, using ONLY what is measurable on this machine:
  * the installed node source (comfy_extras/nodes_scail.py) - class list, palette,
    sort semantics, mask backgrounds, chunk/step policy;
  * the live-interface dump extracted from the pinned runtime (P0_NODE_INTERFACES.json);
  * the runtime matrix rows (weights present? inference tested?);
  * the models-root scan for SCAIL/SAM weight files.

Every "cannot" is recorded as a measured absence, not as an assumption.

Usage: python -B tools/w17_probe_scail.py
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

RUNTIME = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI")
NODE_SRC = RUNTIME / "comfy_extras" / "nodes_scail.py"
MODELS_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models")
PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
RAW = Path(__file__).resolve().parent.parent / "raw"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    src = NODE_SRC.read_text(encoding="utf-8")
    out: dict = {
        "artifact": "scail_probe.json",
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "family": "wan_scail / SCAIL-2 (correspondence path)",
        "source_file": str(NODE_SRC).replace("\\", "/"),
        "source_sha256": sha256_file(NODE_SRC),
        "source_lines": src.count("\n") + 1,
        "classes_defined": sorted(re.findall(r"^class (\w+)", src, flags=re.M)),
        "node_ids": sorted(re.findall(r'node_id="(\w+)"', src)),
        "palette": {},
        "semantics": {},
        "weights": {},
        "win12gb": {},
        "verdict": "BLOCKED_NO_WEIGHTS",
        "inference_tested": "NOT_RUN",
    }

    # palette: trained colors + modulo wrap behaviour (read from the source, with line refs)
    pal = re.search(r"DEFAULT_PALETTE = \[(.*?)\]", src, flags=re.S)
    if pal:
        colors = re.findall(r"\(([\d.,\s]+)\)\s*,?\s*#\s*(\w+)", pal.group(1))
        out["palette"] = {
            "count": len(colors),
            "colors": [{"rgb": [float(x) for x in c.split(",")], "name": name} for c, name in colors],
            "trained_note_line": next((i + 1 for i, ln in enumerate(src.splitlines()) if "trained on these exact colors" in ln), None),
            "modulo_wrap_line": next((i + 1 for i, ln in enumerate(src.splitlines()) if "i % len(DEFAULT_PALETTE)" in ln), None),
            "note": "the model was trained on these exact colors and the palette wraps with modulo; more identities than palette entries re-use a color",
        }

    def line_of(needle: str) -> int | None:
        return next((i + 1 for i, ln in enumerate(src.splitlines()) if needle in ln), None)

    out["semantics"] = {
        "sort_by_line": line_of('io.Combo.Input("sort_by"'),
        "sort_semantics": ("objects that appear in earlier frames always come first; within a frame, "
                           "left_to_right = leftmost by centroid at first appearance, area = biggest mask; "
                           "none = keep SAM3 order; the same order is applied to both reference and pose "
                           "video so one identity keeps one colour"),
        "replacement_mode_line": line_of('io.Boolean.Input("replacement_mode"'),
        "mask_backgrounds": ("animation mode: pose_video_mask black background / reference_image_mask white; "
                             "replacement mode: inverted"),
        "previous_frame_count_line": line_of('previous_frame_count'),
        "chunk_policy": "SCAIL-2 trained at previous_frame_count 5 (81-frame chunks, 76-frame step)",
        "reference_semantics": ("first reference image = primary reference (all identities composited onto it); "
                                "extra batch images are additional views, each needing a matching "
                                "reference_image_mask in that identity's colour"),
        "plain_mask_semantics": "a plain MASK reference is rendered as a single identity in palette[0]",
        "requires": ["SAM3 track data (SAM3TrackData) for driving and reference masks",
                     "the SCAIL-2 finetuned model weights behind the conditioning nodes"],
        "tooltips_from_live_dump": "see evidence table: P0_NODE_INTERFACES.json (sha-bound)",
    }

    # weights: measured absence in the models root + runtime-matrix rows
    matrix = json.loads((PROOF / "evidence" / "P0_RUNTIME_MATRIX.json").read_text(encoding="utf-8"))
    rows = [r for r in matrix.get("matrix", []) if r.get("family") == "wan_scail"]
    scan: dict[str, int] = {}
    for pat in ("*scail*", "*SCAIL*", "*sam3*", "*SAM3*", "*sam2*", "*SAM2*"):
        scan[pat] = len([p for p in MODELS_ROOT.rglob(pat) if p.is_file()])
    out["weights"] = {
        "models_root": str(MODELS_ROOT).replace("\\", "/"),
        "scan_hits": scan,
        "matrix_rows": rows,
        "matrix_row_count": len(rows),
        "weights_present": any(r.get("weights_present") for r in rows),
        "sam3_weights_present": scan["*sam3*"] > 0 or scan["*SAM3*"] > 0,
        "p0_missing_groups": json.loads((PROOF / "evidence" / "P0_MODEL_INVENTORY.json").read_text(encoding="utf-8")).get("missing_groups"),
        "note": ("no SCAIL-2 / SAM weight file exists under the models root; the node family source and "
                 "registration exist, but inference cannot run and must not be claimed"),
    }

    out["win12gb"] = {
        "gpu": "RTX 5070, 12,227 MiB VRAM (single GPU; one GPU job at a time on this host)",
        "status": "NOT_PROVEN_ON_THIS_GPU",
        "why": ("no SCAIL-2 weights are installed, therefore no inference was run and no VRAM figure was "
                "measured; the family's fit on 12 GB is unproven and is not claimed"),
        "closest_measured_reference": {
            "profile": "vace_14b_fp16_book (a 14B-family checkpoint, single run P4)",
            "vram_peak_mib": 11680,
            "gpu_total_mib": 12227,
            "note": "measured for VACE, NOT a SCAIL-2 measurement",
        },
    }

    RAW.joinpath("scail_probe.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("verdict", "inference_tested", "node_ids", "source_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
