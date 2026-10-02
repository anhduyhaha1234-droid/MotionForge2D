#!/usr/bin/env python
"""MF-END-11 correction — correct the internal_cuts expectation (measured truth)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/tests/product_delivery/test_mf_end_11.py"
)

OLD = (
    b'    assert verdict.internal_cuts == (\r\n'
    b'        {"shot_id": "BOOK", "cut_frame": 121, "window_local_frame": 121,\r\n'
    b'         "must_be_represented_as": "boundary_or_declared_event"},\r\n'
    b'        {"shot_id": "TURN", "cut_frame": 241, "window_local_frame": 121,\r\n'
    b'         "must_be_represented_as": "boundary_or_declared_event"},\r\n'
    b'        {"shot_id": "OCC", "cut_frame": 343, "window_local_frame": 103,\r\n'
    b'         "must_be_represented_as": "boundary_or_declared_event"},\r\n'
    b'    )\r\n'
)
NEW = (
    b'    # measured cuts fall INSIDE the declared windows: 121 in TURN [120,239],\r\n'
    b'    # 241 and 343 in OCC [240,359]; BOOK [0,119] contains none.\r\n'
    b'    assert verdict.internal_cuts == (\r\n'
    b'        {"shot_id": "TURN", "cut_frame": 121, "window_local_frame": 1,\r\n'
    b'         "must_be_represented_as": "boundary_or_declared_event"},\r\n'
    b'        {"shot_id": "OCC", "cut_frame": 241, "window_local_frame": 1,\r\n'
    b'         "must_be_represented_as": "boundary_or_declared_event"},\r\n'
    b'        {"shot_id": "OCC", "cut_frame": 343, "window_local_frame": 103,\r\n'
    b'         "must_be_represented_as": "boundary_or_declared_event"},\r\n'
    b'    )\r\n'
)


def main() -> int:
    data = TARGET.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    count = data.count(OLD)
    if count != 1:
        print(f"preimage count {count} != 1; refusing")
        return 2
    TARGET.write_bytes(data.replace(OLD, NEW, 1))
    after = TARGET.read_bytes()
    print(f"bytes {len(data)} -> {len(after)}")
    print(f"sha256 {before[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
