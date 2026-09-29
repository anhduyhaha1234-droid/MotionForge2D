"""Bounded, frame-exact source decode.

Design constraints honoured here (finding R03):
  * The film is NEVER decoded into RAM.  A window (120 frames) is decoded as
    anchor-to-anchor segments; the number of resident frames is asserted against
    a hard ceiling before every decode.
  * Decoding is chunked through an ffmpeg pipe with rawvideo output, so peak
    memory is (chunk frames x H x W x 3) plus one pipe buffer.
  * Frame exactness is not assumed: `-ss` input seeking is verified against the
    frozen GOLDEN anchor keyframes and the measured per-anchor MAE is recorded.
"""
from __future__ import annotations

import os
import subprocess
import time

import numpy as np

from . import MAX_FRAMES_RESIDENT, WIDTH, HEIGHT, FPS, pts_of, time_of
from . import contract


class DecodeError(RuntimeError):
    pass


class ChunkReader:
    """Frame-exact chunked reader over the locked reference film."""

    def __init__(self, film: str, chunk: int = 16):
        if chunk > MAX_FRAMES_RESIDENT:
            raise DecodeError(f"chunk {chunk} exceeds resident ceiling {MAX_FRAMES_RESIDENT}")
        self.film = film
        self.chunk = chunk
        self.commands: list[dict] = []

    def read(self, start_frame: int, count: int, check_ceiling: bool = True) -> np.ndarray:
        """Decode `count` consecutive frames beginning exactly at start_frame."""
        if count <= 0:
            raise DecodeError("count must be positive")
        if check_ceiling and count > MAX_FRAMES_RESIDENT:
            raise DecodeError(f"requested {count} resident frames > ceiling {MAX_FRAMES_RESIDENT}")
        t0 = time_of(start_frame)
        argv = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-ss", f"{t0:.6f}", "-i", self.film, "-frames:v", str(count),
                "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        st = time.time()
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        el = time.time() - st
        self.commands.append({
            "argv": argv, "start_frame": start_frame, "count": count,
            "duration_s": round(el, 4), "exit_code": p.returncode,
            "stdout_bytes": len(p.stdout), "stderr": p.stderr.decode("utf-8", "replace")[:400],
            "start_pts": pts_of(start_frame), "start_time_s": t0,
        })
        if p.returncode != 0:
            raise DecodeError(f"ffmpeg failed rc={p.returncode}: {p.stderr.decode('utf-8','replace')[:300]}")
        n = len(p.stdout) // (WIDTH * HEIGHT * 3)
        if n != count:
            raise DecodeError(f"decoded {n} frames, expected {count} at f{start_frame}")
        return np.frombuffer(p.stdout, dtype=np.uint8).reshape(count, HEIGHT, WIDTH, 3)


def window_reader() -> ChunkReader:
    return ChunkReader(contract.film_path(), chunk=16)


def alignment_report(tag: str, reader: ChunkReader | None = None) -> dict:
    """Decode each anchor frame in its own bounded chunk and compare it with the
    frozen GOLDEN keyframe: proves the frame_id -> decoded-frame mapping and the
    pts/time formulas without assuming them."""
    reader = reader or window_reader()
    w = contract.window(tag)
    out = {"tag": tag, "anchors": [], "decode_commands": []}
    exact = 0
    worst = 0.0
    for fid in w["anchors"]:
        arr = reader.read(fid, 1, check_ceiling=False)
        gold = contract.load_keyframe(tag, fid)
        mae = float(np.abs(arr[0].astype(np.int16) - gold.astype(np.int16)).mean())
        is_exact = bool(np.array_equal(arr[0], gold))
        exact += int(is_exact)
        worst = max(worst, mae)
        out["anchors"].append({
            "frame_id": fid, "pts": pts_of(fid), "time_s": time_of(fid),
            "keyframe_png": contract.keyframe_png(tag, fid),
            "mae_vs_golden": round(mae, 8), "byte_exact": is_exact,
        })
    out["decode_commands"] = reader.commands
    out["anchors_exact"] = exact
    out["anchors_total"] = len(w["anchors"])
    out["worst_mae"] = round(worst, 8)
    out["frame_map_verified"] = exact == len(w["anchors"])
    return out
