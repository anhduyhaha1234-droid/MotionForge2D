"""Read-only probe: exact PTS + audio stream facts for the frozen BOOK example.

Measures (read-only) on the two pinned artifacts:
* BOOK source window  .../bench/src_windows/BOOK_src.mp4        (sha 0a7ed862...cacc)
* BOOK p3b output     RUN/proof/output/p3b/animate2_book_p3b_00001_.mp4 (sha dfc4e37b...d77f)

For each file: full stream list (video+audio), video first/last packet PTS in stream
ticks, decoded frame count.  Nothing is written.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUN = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")
BOOK_SRC = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows/BOOK_src.mp4")
OUT_CLIP = RUN / "proof" / "output" / "p3b" / "animate2_book_p3b_00001_.mp4"


def find_ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffprobe.exe"
    if links.is_file():
        return str(links)
    raise SystemExit("ffprobe not found")


def run(exe: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def packet_pts(exe: str, path: Path) -> dict:
    proc = run(
        exe,
        [
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "packet=pts,pts_time,flags",
            "-of", "json",
            str(path),
        ],
    )
    if proc.returncode != 0:
        return {"rc": proc.returncode, "stderr_tail": (proc.stderr or "")[-200:]}
    packets = json.loads(proc.stdout).get("packets", [])
    return {
        "rc": 0,
        "packet_count": len(packets),
        "first_pts": packets[0]["pts"] if packets else None,
        "last_pts": packets[-1]["pts"] if packets else None,
        "first_pts_time": packets[0].get("pts_time") if packets else None,
        "last_pts_time": packets[-1].get("pts_time") if packets else None,
    }


def streams(exe: str, path: Path) -> dict:
    proc = run(exe, ["-v", "error", "-show_streams", "-of", "json", str(path)])
    if proc.returncode != 0:
        return {"rc": proc.returncode, "stderr_tail": (proc.stderr or "")[-200:]}
    keep = (
        "index", "codec_type", "codec_name", "width", "height", "r_frame_rate",
        "time_base", "start_pts", "nb_frames", "duration", "sample_rate", "channels",
    )
    return {
        "rc": 0,
        "streams": [{k: s.get(k) for k in keep if k in s} for s in json.loads(proc.stdout).get("streams", [])],
    }


def probe(exe: str, path: Path) -> dict:
    return {
        "path": str(path),
        "streams": streams(exe, path),
        "video_pts": packet_pts(exe, path),
    }


def main() -> int:
    exe = find_ffprobe()
    report = {
        "probe": "mf_end_01_pts_audio",
        "ffprobe": exe,
        "book_src": probe(exe, BOOK_SRC),
        "p3b_output": probe(exe, OUT_CLIP),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
