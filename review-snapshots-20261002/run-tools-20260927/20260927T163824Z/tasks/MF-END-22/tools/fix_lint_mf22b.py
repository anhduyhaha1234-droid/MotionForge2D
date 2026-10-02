"""MF-END-22 lint fix #2b: insert the module-level _hidden_frames helper.

Anchor: the unique ``def _reference_extent(`` definition line.  The helper
takes ``dict[str, Any]`` so no new typing import is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-22")
PATH = ROOT / "app/services/qc_checks/z_order_error.py"

ANCHOR = b"def _reference_extent(\r\n"
HELPER = (
    b"def _hidden_frames(role_rows: dict[str, Any], frames: list[int]) -> list[int]:\r\n"
    b'    """Frames of the FACT window the role pays no usable mask for."""\r\n'
    b"    hidden = (\r\n"
    b'        set(role_rows["occluded_frames"])\r\n'
    b'        | set(role_rows["gap_frames"])\r\n'
    b'        | set(role_rows["out_of_frame_frames"])\r\n'
    b"    )\r\n"
    b"    return sorted(hidden & set(frames))\r\n"
    b"\r\n"
    b"\r\n"
)


def main() -> int:
    data = PATH.read_bytes()
    if HELPER in data:
        print("helper already present")
        return 0
    count = data.count(ANCHOR)
    print(f"anchor_count={count}")
    if count != 1:
        return 1
    PATH.write_bytes(data.replace(ANCHOR, HELPER + ANCHOR, 1))
    print("helper inserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
