#!/usr/bin/env python
"""MF-END-11 correction — fix 4 test expectations (CRLF bounded, measured counts)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/tests/product_delivery/test_mf_end_11.py"
)

SPAN_KW = b"start_frame=0, end_frame_exclusive="

REPLACEMENTS: list[tuple[bytes, bytes, int]] = [
    (b"plan.SourceSpan(0, 1)", b"plan.SourceSpan(start_frame=0, end_frame_exclusive=1)", 2),
    (b"plan.SourceSpan(1, 2)", b"plan.SourceSpan(start_frame=1, end_frame_exclusive=2)", 1),
    (
        b"    assert verdict.valid is False\r\n"
        b"    assert verdict.missing_boundaries == ()\r\n"
        b"    assert verdict.unexpected_boundaries == ()\r\n"
        b"    assert verdict.coverage_problems == ()\r\n"
        b'    assert [(row["cut_frame"], row["window_local_frame"]) for row in verdict.internal_cuts] == [\r\n',
        b"    assert verdict.valid is False\r\n"
        b"    assert verdict.missing_boundaries == (30,)\r\n"
        b"    assert verdict.unexpected_boundaries == ()\r\n"
        b"    assert verdict.coverage_problems == ()\r\n"
        b'    assert [(row["cut_frame"], row["window_local_frame"]) for row in verdict.internal_cuts] == [\r\n',
        1,
    ),
]


def main() -> int:
    data = TARGET.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    for index, (old, new, want) in enumerate(REPLACEMENTS):
        count = data.count(old)
        if count != want:
            print(f"replacement #{index}: count {count} != {want}; refusing")
            return 2
        data = data.replace(old, new)
    if b"plan.SourceSpan(0, 1)" in data or b"plan.SourceSpan(1, 2)" in data:
        print("positional SourceSpan still present; refusing")
        return 2
    TARGET.write_bytes(data)
    after = TARGET.read_bytes()
    print(f"bytes {len(before)} -> {len(after)}")
    print(f"items {len(REPLACEMENTS)} applied; lines {after.count(chr(10).encode())}")
    print(f"sha256 {before[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
