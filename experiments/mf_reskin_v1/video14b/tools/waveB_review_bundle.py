"""MF-V1-VIDEO14B wave B step B-review — human review bundle (CPU, ffmpeg only).

There is no vision on this route, so the deliverable cannot be judged here: this
tool only makes the review POSSIBLE for a human/Codex reviewer.  It renders, from
the delivered clip plus the frozen source window:

  1x and 0.5x review copies of the clip
  a source/candidate side-by-side (source | candidate) at full clip resolution
  contact sheets of the candidate (20 frames per sheet, 5x4)
  contact sheets of the side-by-side
  2x-zoom crops of the book/grip frames f68..f80 and f119 (the interaction the
  instruction names: closed -> open book, single pointing hand)

Every generated artifact is asserted to exist with size > 0 (a zero-byte file from
a select expression that matched nothing is treated as failure, not as success).

usage:
  python waveB_review_bundle.py <clip.mp4> <source_window.mp4> <out_dir> [--width 640 --height 360]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

FPS = 30
GRIP_FRAMES = list(range(68, 81)) + [119]     # f68..f80 + f119
CROP = "crop=320:180:160:150,scale=640:360:flags=neighbor"   # centre-lower, 2x zoom


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def run(argv: list[str], log: list[dict]) -> None:
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log.append({"argv": argv, "returncode": r.returncode, "stderr_tail": (r.stderr or "")[-300:]})
    if r.returncode != 0:
        raise SystemExit(f"command failed rc={r.returncode}: {' '.join(argv)}\n{(r.stderr or '')[-1500:]}")


def artefact(path: Path, log: list[dict], expect_min: int = 1) -> dict:
    if not path.exists():
        raise SystemExit(f"ARTIFACT_MISSING (ffmpeg exited 0 but wrote nothing): {path}")
    size = path.stat().st_size
    if size < expect_min:
        raise SystemExit(f"ARTIFACT_EMPTY: {path} is {size} bytes")
    log.append({"artifact": str(path), "bytes": size})
    return {"path": str(path), "bytes": size}


def probed_frame_count(path: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return int((r.stdout or "0").strip() or 0)


def main() -> int:
    clip, source, out_dir = _p(sys.argv[1]), _p(sys.argv[2]), _p(sys.argv[3])
    W, H = 640, 360
    if "--width" in sys.argv:
        W = int(sys.argv[sys.argv.index("--width") + 1])
    if "--height" in sys.argv:
        H = int(sys.argv[sys.argv.index("--height") + 1])
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    made: dict = {}
    n_clip = probed_frame_count(clip)

    shutil.copy2(clip, out_dir / "review_1x_120f.mp4")
    made["review_1x"] = artefact(out_dir / "review_1x_120f.mp4", log)

    run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", f"scale={W // 2}:{H // 2}",
         "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-an", str(out_dir / "review_0.5x_120f.mp4")], log)
    made["review_0.5x"] = artefact(out_dir / "review_0.5x_120f.mp4", log)

    # source | candidate, horizontally, frame-locked at the same index
    run(["ffmpeg", "-v", "error", "-y",
         "-i", str(clip), "-i", str(source),
         "-filter_complex", f"[0:v]scale={W}:{H}[a];[1:v]scale={W}:{H}[b];[b][a]hstack=inputs=2[v]",
         "-map", "[v]", "-r", str(FPS), "-c:v", "libx264", "-crf", "16", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-an", str(out_dir / "side_by_side_source_candidate_120f.mp4")], log)
    made["side_by_side"] = artefact(out_dir / "side_by_side_source_candidate_120f.mp4", log)

    for name, src in (("candidate", clip), ("side_by_side", out_dir / "side_by_side_source_candidate_120f.mp4")):
        sheet_i = 0
        for start in range(0, n_clip, 20):
            sheet_i += 1
            out = out_dir / f"contact_sheet_{name}_{sheet_i:02d}_f{start:03d}-{min(start + 19, n_clip - 1):03d}.png"
            run(["ffmpeg", "-v", "error", "-y", "-i", str(src),
                 "-vf", f"select='between(n\\,{start}\\,{min(start + 19, n_clip - 1)})',"
                        f"scale=-2:{max(H // 4, 90)},tile=5x4:padding=2:margin=2",
                 "-frames:v", "1", str(out)], log)
            made.setdefault("contact_sheets", []).append(artefact(out, log))

    # grip/book frames, 2x zoom, individual + one strip each
    crops: list[Path] = []
    for f in GRIP_FRAMES:
        out = out_dir / f"grip_f{f:03d}_2xzoom.png"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(clip),
             "-vf", f"select='eq(n\\,{f})',{CROP}", "-frames:v", "1", str(out)], log)
        made.setdefault("grip_crops", []).append(artefact(out, log))
        crops.append(out)
    for tag, subset in (("f068_f080", crops[:-1]), ("f119", [crops[-1]])):
        strip = out_dir / f"grip_strip_{tag}_2xzoom.png"
        if len(subset) == 1:
            # hstack rejects inputs=1 ("Value 1.000000 for parameter 'inputs' out of
            # range [2 - ...]"): a one-frame strip is the frame itself, copied --
            # never an empty ffmpeg chain that exits non-zero having written nothing.
            shutil.copy2(subset[0], strip)
        else:
            argv = ["ffmpeg", "-v", "error", "-y"]
            for c in subset:
                argv += ["-i", str(c)]
            argv += ["-filter_complex", f"hstack=inputs={len(subset)}", str(strip)]
            run(argv, log)
        made.setdefault("grip_strips", []).append(artefact(strip, log))

    record = {
        "clip": str(clip), "clip_frames": n_clip, "source": str(source),
        "out_dir": str(out_dir), "grip_frames": GRIP_FRAMES, "crop_filter": CROP,
        "quality_status": "NOT_VISUALLY_APPROVED",
        "note": "review inputs only; nothing here claims a visual verdict",
        "made": made, "commands": log,
    }
    (out_dir / "review_bundle_manifest.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"clip_frames": n_clip, "artifacts": sum(
        len(v) if isinstance(v, list) else 1 for v in made.values()),
        "files": sorted(p.name for p in out_dir.iterdir())}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
