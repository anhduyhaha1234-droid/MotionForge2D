#!/usr/bin/env python
"""MF-END-11 correction — insert the two CMC fixtures at a unique anchor (CRLF)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/tests/product_delivery/test_mf_end_11.py"
)

ANCHOR = (
    "            \"-filter_complex\", \"[0:v][1:v]concat=n=2:v=1[out]\", \"-map\", \"[out]\",\r\n"
    "            \"-c:v\", \"libx264\", \"-pix_fmt\", \"yuv420p\", str(path),\r\n"
    "        ]\r\n"
    "    )\r\n"
    "    assert path.stat().st_size > 0\r\n"
    "    return path\r\n"
)

ADDITION_LF = '''

@pytest.fixture(scope="session")
def demo12s() -> Path:
    """The REAL demo fixture bytes (not synthesized here) — measured, never assumed."""
    path = PROJECT_ROOT / "tests" / "fixtures" / "delta_f5" / "source_12s.mp4"
    assert path.is_file(), f"demo fixture missing: {path}"
    return path


@pytest.fixture(scope="session")
def cfr30_noaudio(media_dir: Path) -> Path:
    path = media_dir / "cfr30_noaudio.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=duration=1:size={MF_TS_SIZE}:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )
    assert path.stat().st_size > 0
    return path
'''

ADDITION = ADDITION_LF.replace("\n", "\r\n").encode("utf-8")
ANCHOR_B = ANCHOR.encode("utf-8")


def main() -> int:
    data = TARGET.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    count = data.count(ANCHOR_B)
    if count != 1:
        print(f"anchor count {count} != 1; refusing")
        return 2
    post = data.replace(ANCHOR_B, ANCHOR_B + ADDITION, 1)
    if len(post) <= len(data):
        print("insert did not grow the file; refusing")
        return 2
    TARGET.write_bytes(post)
    after = TARGET.read_bytes()
    print(f"test_mf_end_11.py  bytes {len(data)} -> {len(after)} (+{len(after) - len(data)})")
    print(f"  lines {data.count(chr(10).encode())} -> {after.count(chr(10).encode())}")
    print(f"  sha256 {before[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
