#!/usr/bin/env python
"""MF-END-11 bounded patch #1 — additive adapter in app/services/scene_detection.py.

Byte-exact preimage replacement (the file is CRLF; the patch tool is not used on
CRLF files by policy).  Asserts the preimage occurs exactly once, that the file
only GROWS, and prints before/after sha256 + bytes + line counts.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/app/services/scene_detection.py"
)

PRE = b"    return scenes\r\n"

BLOCK_LF = '''def detect_scene_intervals(
    video_path: str | Path,
    threshold: float = 27.0,
    min_scene_len_frames: int = 15,
) -> list[tuple[int, int]]:
    """MF-END-11 adapter: frame-exact HALF-OPEN ``[start, end)`` intervals.

    Thin adapter over :func:`detect_scenes` for the MF-END shot planner
    (``app/services/shot_reskin_plan.py``); the legacy detector contract is
    untouched.  ``SceneInfo.end_frame`` is inclusive, so the exclusive bound
    is ``end_frame + 1``.  The planner always re-validates the partition
    against the MEASURED frame count, so a detector boundary beyond the
    measured tail is reconciled (dropped + recorded) there - never silently
    kept.
    """
    scenes = detect_scenes(
        video_path, threshold=threshold, min_scene_len_frames=min_scene_len_frames
    )
    return [(scene.start_frame, scene.end_frame + 1) for scene in scenes]
'''


def main() -> int:
    data = TARGET.read_bytes()
    before_sha = hashlib.sha256(data).hexdigest()
    if not data.endswith(PRE):
        print("PREIMAGE TAIL MISMATCH; last 160 bytes:")
        print(repr(data[-160:]))
        return 2
    if data.count(PRE) != 1:
        print(f"PREIMAGE count {data.count(PRE)} != 1; refusing")
        return 2
    block = BLOCK_LF.replace("\n", "\r\n").encode("utf-8")
    post = data + b"\r\n" + block
    if len(post) <= len(data):
        print("PATCH DID NOT GROW THE FILE; refusing")
        return 2
    expected_crlf = data.count(b"\r\n") + 1 + block.count(b"\r\n")
    if post.count(b"\r\n") != expected_crlf:
        print(f"CRLF accounting mismatch {post.count(chr(13).encode() + chr(10).encode())} != {expected_crlf}")
        return 2
    TARGET.write_bytes(post)
    after = TARGET.read_bytes()
    print(f"scene_detection.py  bytes {len(data)} -> {len(after)}")
    print(f"  lines {data.count(chr(10).encode())} -> {after.count(chr(10).encode())}")
    print(f"  sha256 {before_sha[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
