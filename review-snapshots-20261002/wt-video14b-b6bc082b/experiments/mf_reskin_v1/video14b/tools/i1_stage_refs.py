"""MF-V1-VIDEO14B round I1 -- stage the reference PNGs at the engine's input ROOT.

Why: `LoadImage.INPUT_TYPES` lists only the FILES at the root of `<base-directory>/input`
(`os.path.isfile` on `os.listdir`), so a reference kept in a subdirectory is not in the
`/object_info` enum the engine validates against.  Every reference declared in
`i1_make_anchor_graphs.SHOTS` is therefore copied to `<input>/i1_<basename>.png` and the
copy is proven byte-identical to the frozen round-D file it came from.

usage:
  python i1_stage_refs.py <out_manifest.json>
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from i1_make_anchor_graphs import SHOTS, load_of  # noqa: E402

INPUT_ROOT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    out = Path(sys.argv[1].replace("\\", "/"))
    rows, errors = [], []
    seen: dict[str, str] = {}
    for shot, s in SHOTS.items():
        for i, ref in enumerate(s["refs"], start=1):
            src = INPUT_ROOT / ref["file"]
            dst = INPUT_ROOT / load_of(ref["file"])
            if not src.is_file():
                errors.append(f"{shot}[{i}]: frozen reference absent: {src}")
                continue
            if seen.get(str(dst), str(src)) != str(src):
                errors.append(f"{shot}[{i}]: staged name collision on {dst.name}")
            seen[str(dst)] = str(src)
            if not dst.is_file() or sha256_file(dst) != sha256_file(src):
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            rows.append({
                "shot": shot, "index": i, "role": ref["role"],
                "frozen_path": str(src), "frozen_sha256": sha256_file(src),
                "frozen_bytes": src.stat().st_size,
                "loadimage_value": load_of(ref["file"]),
                "staged_path": str(dst), "staged_sha256": sha256_file(dst),
                "staged_bytes": dst.stat().st_size,
                "byte_identical": sha256_file(src) == sha256_file(dst),
            })
    rep = {"artifact": "i1_ref_manifest.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
           "why_staging_is_needed": "LoadImage enumerates only files at the root of <base>/input",
           "rows": rows, "errors": errors,
           "all_staged_files_byte_identical": all(r["byte_identical"] for r in rows) and not errors}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "errors": errors,
                      "all_identical": rep["all_staged_files_byte_identical"],
                      "manifest": str(out)}, indent=1))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
