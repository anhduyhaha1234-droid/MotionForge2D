"""MF-END-14 — recompute the tensor-preview comparison from the FROZEN server outputs.

The run harness (sa_run.py) wrote the prefix outputs under runtime/output/... and its receipt
recorded their sha256.  A filename-mapping bug in that harness's inline comparison missed them
(harness RC=1); the GPU job itself succeeded.  This tool:
  1. re-reads the 7 prefix PNGs from the isolated server output dir,
  2. proves each file's sha256 equals the receipt's recorded sha256 (compared bytes ARE the
     server-produced bytes),
  3. compares their pixels to the OFFLINE float32 node path expectations (raw/stage_input.json),
  4. merges the result into raw/run_record.json as `tensor_preview_comparison` with an explicit
     provenance note; no GPU rerun, no server start.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
OUT = EV / "runtime/output/mf_shot_anchor_v1/tensor_preview"

MAPPING = [("KEY_COMP", "KEY", "key_comp_00001_.png"),
           ("R1_COMP", "R1", "r1_comp_00001_.png"),
           ("R1_RES", "R1", "r1_res_00001_.png"),
           ("R2_COMP", "R2", "r2_comp_00001_.png"),
           ("R2_RES", "R2", "r2_res_00001_.png"),
           ("R3_COMP", "R3", "r3_comp_00001_.png"),
           ("R3_RES", "R3", "r3_res_00001_.png")]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    rec = json.loads((EV / "raw/run_record.json").read_text(encoding="utf-8"))
    staged = json.loads((EV / "raw/stage_input.json").read_text(encoding="utf-8"))
    exp = staged["tensor_preview_expected"]
    receipt = {o["filename"]: o for o in rec["prefix_job"].get("outputs", [])}
    rows = {}
    for node, tag, fname in MAPPING:
        p = OUT / fname
        data = p.read_bytes()
        got_sha = sha256_bytes(data)
        want_sha = (receipt.get(fname) or {}).get("sha256")
        arr = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
        px = sha256_bytes(arr.astype(np.uint8).tobytes())
        kind = "resized" if node.endswith("RES") else "composite"
        rows[node] = {
            "file": fname, "bytes": len(data), "file_sha256": got_sha,
            "file_sha256_matches_receipt": got_sha == want_sha,
            "dims": [int(arr.shape[1]), int(arr.shape[0])],
            "pixels_sha256": px,
            "expected_pixels_sha256": exp[tag][f"{kind}_display_pixels_sha256"],
            "pixels_match_offline_expectation": px == exp[tag][f"{kind}_display_pixels_sha256"],
            "expected_dims": exp[tag][f"{kind}_display_dims"],
        }
    rec["tensor_preview_comparison"] = rows
    rec["tensor_preview_comparison_source"] = (
        "recomputed post-hoc from the frozen isolated-server output files; each file's sha256 is "
        "verified against the prefix-job receipt BEFORE the pixel comparison (no GPU rerun). "
        "The harness's inline mapping used different pseudo-names and reported the rows as "
        "missing (harness RC=1); the GPU job, live validation and shutdown in this same record "
        "are unaffected.")
    (EV / "raw/run_record.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    ok = True
    for node, r in rows.items():
        ok &= bool(r["file_sha256_matches_receipt"]) and bool(
            r["pixels_match_offline_expectation"]) and r["dims"] == r["expected_dims"]
        print(f"{node:8s} sha_ok={r['file_sha256_matches_receipt']} px_match="
              f"{r['pixels_match_offline_expectation']} dims={r['dims']} "
              f"want={r['expected_dims']}")
    print("ALL_ROWS_OK", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
