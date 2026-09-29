#!/usr/bin/env python
"""MF-END-11 correction — fix the one long line introduced by the patch."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/app/services/shot_reskin_plan.py"
)

OLD = (
    b"    measured = facts if facts is not None else probe_source_facts(source_path, "
    b"deep_count=deep_count)\r\n"
)
NEW = (
    b"    measured = (\r\n"
    b"        facts\r\n"
    b"        if facts is not None\r\n"
    b"        else probe_source_facts(source_path, deep_count=deep_count)\r\n"
    b"    )\r\n"
)


def main() -> int:
    data = TARGET.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    count = data.count(OLD)
    if count != 1:
        print(f"preimage count {count} != 1; refusing")
        return 2
    post = data.replace(OLD, NEW, 1)
    if len(post) <= len(data):
        print("did not grow; refusing")
        return 2
    TARGET.write_bytes(post)
    after = TARGET.read_bytes()
    print(f"bytes {len(data)} -> {len(after)} (+{len(after) - len(data)})")
    print(f"lines {data.count(chr(10).encode())} -> {after.count(chr(10).encode())}")
    print(f"sha256 {before[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
