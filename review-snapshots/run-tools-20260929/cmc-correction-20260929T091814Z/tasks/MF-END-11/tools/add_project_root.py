#!/usr/bin/env python
"""MF-END-11 correction — define PROJECT_ROOT in the test module (CRLF bounded)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/tests/product_delivery/test_mf_end_11.py"
)

OLD = b'MF_TS_SIZE = "160x120"\r\n'
NEW = (
    b'MF_TS_SIZE = "160x120"\r\n'
    b'PROJECT_ROOT = Path(__file__).resolve().parents[2]\r\n'
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
