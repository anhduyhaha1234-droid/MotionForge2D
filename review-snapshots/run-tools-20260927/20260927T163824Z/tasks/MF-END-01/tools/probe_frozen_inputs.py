"""Read-only probe: real facts for MF-END-01 frozen examples.

Sources (all pinned by the PROOF_GATE candidate):
* BOOK source window  C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows/BOOK_src.mp4
  (sha256 recorded in P1_UNIT_MANIFESTS.json: 0a7ed862...cacc)
* BOOK p3b output     RUN/proof/output/p3b/animate2_book_p3b_00001_.mp4
  (sha dfc4e37b...d77f, 208053 B, from P3B_RECEIPT.json)
* accepted DTO blob   f0b918b:app/schemas/media_engine.py (CONTRACT branch)

Prints ONE compact JSON document; nothing is written outside stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUN = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")
BOOK_SRC = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows/BOOK_src.mp4")
OUT_CLIP = RUN / "proof" / "output" / "p3b" / "animate2_book_p3b_00001_.mp4"
CONTRACT_TREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract")
WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_ffprobe() -> str | None:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffprobe.exe"
    return str(links) if links.is_file() else None


def ffprobe(exe: str, path: Path) -> dict:
    cmd = [
        exe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,time_base,start_pts,start_time,nb_frames,duration,codec_name",
        "-of", "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out: dict = {"rc": proc.returncode, "exists": path.is_file()}
    if path.is_file():
        out["bytes"] = path.stat().st_size
    if proc.returncode == 0:
        try:
            out["streams"] = json.loads(proc.stdout).get("streams", [])
        except Exception as exc:  # pragma: no cover
            out["parse_error"] = repr(exc)
    else:
        out["stderr_tail"] = (proc.stderr or "")[-200:]
    return out


def git_out(args: list[str], cwd: Path) -> dict:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    return {
        "rc": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr_tail": (proc.stderr or "").strip()[-160:],
    }


def main() -> int:
    report: dict = {"probe": "mf_end_01_frozen_inputs"}
    report["book_src"] = {
        "path": str(BOOK_SRC),
        "sha256": sha256_file(BOOK_SRC) if BOOK_SRC.is_file() else None,
        "expected_sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
    }
    exe = find_ffprobe()
    report["ffprobe_exe"] = exe
    report["book_src"]["ffprobe"] = ffprobe(exe, BOOK_SRC) if exe else {"rc": None}
    report["p3b_output_clip"] = {
        "path": str(OUT_CLIP),
        "sha256": sha256_file(OUT_CLIP) if OUT_CLIP.is_file() else None,
        "expected_sha256": "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f",
    }
    report["p3b_output_clip"]["ffprobe"] = ffprobe(exe, OUT_CLIP) if exe else {"rc": None}
    report["dto_blob"] = git_out(["rev-parse", "f0b918b:app/schemas/media_engine.py"], WORKTREE)
    dto_on_disk = CONTRACT_TREE / "app" / "schemas" / "media_engine.py"
    report["dto_on_disk_contract_tree"] = {
        "path": str(dto_on_disk),
        "sha256": sha256_file(dto_on_disk) if dto_on_disk.is_file() else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
