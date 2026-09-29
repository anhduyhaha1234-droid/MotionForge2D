#!/usr/bin/env python
"""MF-END-11 bounded patch #2 — additive half-open partition adapter.

Two byte-exact edits in app/services/source_locked_timeline.py (CRLF):
  1. add "validate_half_open_partition" to __all__ right after validate_partition;
  2. append the function at EOF.
Asserts each preimage occurs exactly once, only GROWTH, and prints deltas.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/app/services/source_locked_timeline.py"
)

PRE_ALL = b'    "validate_partition",\r\n'
PRE_TAIL = (
    b'            raise TimelineAuthorityError(CODE_TIMELINE_INVALID, '
    b'f"occurrence {layer_id!r} route missing")\r\n'
)

BLOCK_LF = '''def validate_half_open_partition(spans: Any, frame_count: Any) -> list[str]:
    """Half-open ``[start, end)`` variant of :func:`validate_partition`.

    MF-END-11 (shot plan) keeps the product convention - half-open,
    exclusive end - while the frozen timeline block above keeps the
    inclusive one; the problem strings use the SAME vocabulary so
    :func:`pick_partition_code` maps them onto the same typed codes.
    Contract: strictly increasing starts, first ``start == 0``, contiguous
    (``cur.start == prev.end``), last ``end == frame_count``.

    Returns problem strings (``[]`` = ok).
    """
    problems: list[str] = []
    if not isinstance(spans, list) or not spans:
        return ["no shots"]
    ordered: list[tuple[int, int]] = []
    for index, span in enumerate(spans):
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            return [f"shot[{index}] must be a [start, end) pair"]
        try:
            start = int(span[0])
            end = int(span[1])
        except (TypeError, ValueError):
            return [f"shot[{index}] missing/invalid frames"]
        ordered.append((start, end))
    if ordered[0][0] != 0:
        problems.append(f"first shot must start at 0, got {ordered[0][0]}")
    prev: int | None = None
    for start, end in ordered:
        if end <= start:
            problems.append(f"shot [{start},{end}) is empty or inverted")
        if prev is not None:
            if start < prev:
                problems.append(
                    f"shots overlap or non-monotonic: start {start} < previous end {prev}"
                )
            elif start > prev:
                problems.append(
                    f"gap between shots: previous ends at {prev}, next starts at {start}"
                )
        prev = end
    if problems:
        return problems
    assert prev is not None
    if not isinstance(frame_count, int) or frame_count < 1:
        problems.append(f"frame_count {frame_count!r} must be int >= 1")
    elif prev != frame_count:
        problems.append(
            f"coverage mismatch: shots cover {prev} frames, frame_count is {frame_count}"
        )
    return problems
'''


def main() -> int:
    data = TARGET.read_bytes()
    before_sha = hashlib.sha256(data).hexdigest()
    if data.count(PRE_ALL) != 1:
        print(f"__all__ PREIMAGE count {data.count(PRE_ALL)} != 1; refusing")
        return 2
    if not data.endswith(PRE_TAIL):
        print("TAIL PREIMAGE MISMATCH; last 200 bytes:")
        print(repr(data[-200:]))
        return 2

    addition_all = b'    "validate_half_open_partition",\r\n'
    step1 = data.replace(PRE_ALL, PRE_ALL + addition_all, 1)
    if len(step1) != len(data) + len(addition_all):
        print("step1 size accounting failed; refusing")
        return 2

    block = BLOCK_LF.replace("\n", "\r\n").encode("utf-8")
    post = step1 + b"\r\n" + block
    if len(post) <= len(step1):
        print("PATCH DID NOT GROW THE FILE; refusing")
        return 2
    crlf = chr(13).encode() + chr(10).encode()
    expected = len(data) + len(addition_all) + 2 + len(block)
    if len(post) != expected:
        print(f"final size {len(post)} != expected {expected}; refusing")
        return 2
    TARGET.write_bytes(post)
    after = TARGET.read_bytes()
    print(f"source_locked_timeline.py  bytes {len(data)} -> {len(after)}")
    print(f"  lines {data.count(chr(10).encode())} -> {after.count(chr(10).encode())}")
    print(f"  crlf {data.count(crlf)} -> {after.count(crlf)}")
    print(f"  sha256 {before_sha[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
