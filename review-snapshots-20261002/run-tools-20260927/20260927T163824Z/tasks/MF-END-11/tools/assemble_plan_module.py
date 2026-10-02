#!/usr/bin/env python
"""MF-END-11 assemble — concatenate the new module from its two author parts.

Part 1 landed via the file tool (header + measured facts); part 2 (capability,
partition, chunking, artifact, invalidation) was authored into the evidence
tree.  This script asserts the part-1 tail, joins with a blank line, refuses a
shrinking result, then compiles the module and prints sha/bytes/lines.
"""

from __future__ import annotations

import hashlib
import py_compile
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/app/services/shot_reskin_plan.py"
)
REST = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-11/tools/_rest_part.py"
)
TAIL = b"        audio=audio,\n    )\n"


def main() -> int:
    part1 = TARGET.read_bytes()
    if not part1.endswith(TAIL):
        print("part1 tail mismatch; last 120 bytes:")
        print(repr(part1[-120:]))
        return 2
    before_len = len(part1)
    rest = REST.read_bytes()
    if b"def build_shot_plan(" not in rest or b"class ShotPlanArtifact" not in rest:
        print("rest part looks incomplete (missing landmark symbols); refusing")
        return 2
    post = part1 + b"\n" + rest
    if len(post) <= before_len:
        print("assembly did not grow the module; refusing")
        return 2
    TARGET.write_bytes(post)
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as err:
        print("COMPILE FAILED:", err)
        return 3
    data = TARGET.read_bytes()
    print(f"shot_reskin_plan.py  bytes {before_len} -> {len(data)}")
    print(f"  lines {data.count(chr(10).encode())}")
    print(f"  sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
