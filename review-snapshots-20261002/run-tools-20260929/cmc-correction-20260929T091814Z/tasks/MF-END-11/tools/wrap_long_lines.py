#!/usr/bin/env python
"""MF-END-11 correction — wrap two long assertion lines (CRLF bounded)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/tests/product_delivery/test_mf_end_11.py"
)

REPLACEMENTS: list[tuple[bytes, bytes]] = [
    (
        b'    first = plan.audio_sample_span_for_frames(facts, '
        b'plan.SourceSpan(start_frame=0, end_frame_exclusive=1))\r\n',
        b'    span_first = plan.SourceSpan(start_frame=0, end_frame_exclusive=1)\r\n'
        b'    first = plan.audio_sample_span_for_frames(facts, span_first)\r\n',
    ),
    (
        b'    second = plan.audio_sample_span_for_frames(facts, '
        b'plan.SourceSpan(start_frame=1, end_frame_exclusive=2))\r\n',
        b'    span_second = plan.SourceSpan(start_frame=1, end_frame_exclusive=2)\r\n'
        b'    second = plan.audio_sample_span_for_frames(facts, span_second)\r\n',
    ),
]


def main() -> int:
    data = TARGET.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    for index, (old, new) in enumerate(REPLACEMENTS):
        count = data.count(old)
        if count != 1:
            print(f"replacement #{index}: count {count} != 1; refusing")
            return 2
        data = data.replace(old, new, 1)
    TARGET.write_bytes(data)
    after = TARGET.read_bytes()
    print(f"bytes {len(before)} -> {len(after)}")
    print(f"lines {after.count(chr(10).encode())}")
    print(f"sha256 {before[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
