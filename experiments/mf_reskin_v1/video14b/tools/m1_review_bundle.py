"""MF-V1-VIDEO14B wave B round M1 — human review inputs for the delivered clip.

No vision exists on this route, so the round cannot judge its own output.  This tool
only makes judging POSSIBLE for a human/Codex reviewer: it renders, from the
delivered M1 clip plus the frozen source window,

  contact sheets of the candidate (20 frames per sheet => all 120 frames covered)
  a source | candidate side-by-side, frame-locked at the same index
  contact sheets of that side-by-side
  2x-zoom crops of the interaction frames f68..f80 plus f119, and one strip over them
  1x and 0.5x review copies of the clip
  copies of both source windows (the 120f control used for the side-by-side, and the
  exact 121f conditioning input the run consumed) so a reviewer compares like-for-like

Rendering itself is delegated to the already-verified sibling tool
`waveB_review_bundle.py` (same repository, same conventions as wave B) — this driver
adds the M1-specific parts: the source-window copies, a per-file size assertion over
EVERY produced artifact, and a record with sha256 for each of them.

A `select` that matches nothing exits 0 and writes nothing, so every artifact is
asserted to exist AND to be > 0 bytes; a zero-byte file is a hard failure here.

usage:
  python m1_review_bundle.py <clip.mp4> <source_window_120f.mp4> <out_dir>
      [--conditioning-input <padded_121f.mp4>]

Exit code 0 only when every artifact exists with non-zero bytes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE_TOOL = HERE / "waveB_review_bundle.py"

EXPECTED_SHEETS = 6          # 120 frames / 20 per sheet
EXPECTED_GRIP = list(range(68, 81)) + [119]


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def assert_nonzero(p: Path) -> dict:
    if not p.exists():
        raise SystemExit(f"ARTIFACT_MISSING: {p}")
    size = p.stat().st_size
    if size <= 0:
        raise SystemExit(f"ARTIFACT_ZERO_BYTES: {p}")
    return {"path": str(p), "bytes": size, "sha256": sha256_file(p)}


def main() -> int:
    clip, source, out_dir = _p(sys.argv[1]), _p(sys.argv[2]), _p(sys.argv[3])
    conditioning = None
    if "--conditioning-input" in sys.argv:
        conditioning = _p(sys.argv[sys.argv.index("--conditioning-input") + 1])
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. delegate the rendering to the sibling tool (same conventions as wave B)
    argv = [sys.executable, str(BUNDLE_TOOL), str(clip), str(source), str(out_dir),
            "--width", "640", "--height", "360"]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"waveB_review_bundle.py failed rc={r.returncode}\n{r.stdout[-800:]}\n{r.stderr[-1200:]}")

    # 2. copy the source windows beside the review copies (like-for-like comparison)
    copies = {"source_window_120f.mp4": source}
    if conditioning is not None:
        copies["source_conditioning_padded_121f_640x368.mp4"] = conditioning
    for name, src in copies.items():
        dst = out_dir / name
        shutil.copy2(src, dst)

    # 3. assert every artifact, including the copies and the manifest
    made = [assert_nonzero(p) for p in sorted(out_dir.iterdir()) if p.is_file()]
    manifest = json.loads((out_dir / "review_bundle_manifest.json").read_text(encoding="utf-8"))
    sheets = [m for m in made if m["path"].split("\\")[-1].startswith("contact_sheet_candidate_")]
    if len(sheets) != EXPECTED_SHEETS:
        raise SystemExit(f"expected {EXPECTED_SHEETS} candidate contact sheets, found {len(sheets)}")
    if manifest.get("clip_frames") != 120:
        raise SystemExit(f"clip_frames={manifest.get('clip_frames')} (expected 120)")
    if manifest.get("grip_frames") != EXPECTED_GRIP:
        raise SystemExit(f"grip_frames={manifest.get('grip_frames')} (expected {EXPECTED_GRIP})")

    record = {
        "artifact": "m1_review_bundle_record.json",
        "task_id": "MF-V1-VIDEO14B",
        "round": "waveB_m1",
        "clip": str(clip),
        "clip_sha256": sha256_file(clip),
        "source_used_in_side_by_side": str(source),
        "source_sha256": sha256_file(source),
        "conditioning_input_copied": str(conditioning) if conditioning else None,
        "conditioning_input_sha256": sha256_file(conditioning) if conditioning else None,
        "out_dir": str(out_dir),
        "frames_covered_by_contact_sheets": 120,
        "sheets": len(sheets),
        "grip_frames": EXPECTED_GRIP,
        "files": made,
        "zero_byte_files": [m["path"] for m in made if m["bytes"] == 0],
        "quality_status": "NOT_VISUALLY_APPROVED",
        "note": "review inputs only; nothing in this bundle claims a visual verdict",
    }
    (out_dir / "m1_review_bundle_record.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"files": len(made), "min_bytes": min(m["bytes"] for m in made),
                      "total_bytes": sum(m["bytes"] for m in made),
                      "sheets": len(sheets)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
