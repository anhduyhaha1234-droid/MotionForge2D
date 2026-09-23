"""Per-artifact dimensions for the M1 review bundle (structural check, NOT a visual verdict).

Proves every produced image/video is a real, non-degenerate file: PNG dimensions are read
from the IHDR header, mp4 dimensions/frame counts from ffprobe.  A reviewer opening these
files still decides quality; this only says "the renderer did not write an empty sheet".

Writes: <review_dir>/review_bundle_dimensions_m1.json
usage:  python m1_review_dimensions.py <review_dir>
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path


def png_size(p: Path) -> list[int] | None:
    d = p.read_bytes()[:33]
    if len(d) < 24 or d[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", d[16:24])
    return [w, h]


def probe(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_frames,codec_name",
                        "-of", "json", str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[-200:]}
    s = json.loads(r.stdout)["streams"][0]
    return {"codec": s.get("codec_name"), "size": [s.get("width"), s.get("height")],
            "frames": s.get("nb_frames")}


def main() -> int:
    out = Path(sys.argv[1])
    rows = []
    for p in sorted(out.iterdir()):
        if not p.is_file():
            continue
        row = {"file": p.name, "bytes": p.stat().st_size}
        if p.suffix.lower() == ".png":
            row["kind"] = "image"
            row["size"] = png_size(p)
        elif p.suffix.lower() == ".mp4":
            row["kind"] = "video"
            row.update(probe(p))
        else:
            row["kind"] = p.suffix.lstrip(".") or "none"
        rows.append(row)
    record = {
        "artifact": "review_bundle_dimensions_m1.json",
        "task_id": "MF-V1-VIDEO14B",
        "round": "waveB_m1",
        "dir": str(out),
        "files": len(rows),
        "non_zero": sum(1 for r in rows if r["bytes"] > 0),
        "zero_byte_files": [r["file"] for r in rows if r["bytes"] == 0],
        "degenerate_images": [r["file"] for r in rows if r.get("size") in ([0, 0], None) and r["kind"] == "image"],
        "total_bytes": sum(r["bytes"] for r in rows),
        "verdict_label": "STRUCTURAL_ONLY__NOT_A_VISUAL_VERDICT",
        "note": "dimensions and byte counts only; no frame of any clip was viewed by the worker",
        "rows": rows,
    }
    (out / "review_bundle_dimensions_m1.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("files", "non_zero", "zero_byte_files",
                                             "degenerate_images", "total_bytes")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
