#!/usr/bin/env python
"""MF-END-11 — fix: a single-frame source has no inter-frame gaps, so the grid
is vacuously uniform.  Module + matching test assertion."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

MODULE = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/app/services/shot_reskin_plan.py"
)
TEST = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/tests/product_delivery/test_mf_end_11.py"
)

FIXES: list[tuple[Path, str, str]] = [
    (
        MODULE,
        "        pts_uniform=len(set(gaps)) == 1,\n",
        "        pts_uniform=len(gaps) <= 1 or len(set(gaps)) == 1,\n",
    ),
    (
        TEST,
        "    assert facts.frame_count == 1\n    assert facts.pts_ticks == (0,)\n",
        "    assert facts.frame_count == 1\n    assert facts.pts_ticks == (0,)\n"
        "    assert facts.pts_uniform is True  # no gaps -> vacuously uniform\n",
    ),
]


def main() -> int:
    for target, old, new in FIXES:
        text = target.read_text(encoding="utf-8")
        before = hashlib.sha256(text.encode("utf-8")).hexdigest()
        count = text.count(old)
        if count != 1:
            print(f"{target.name}: preimage count {count} != 1; refusing")
            return 2
        target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
        after = hashlib.sha256(target.read_bytes()).hexdigest()
        print(f"{target.name}: sha {before[:12]} -> {after[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
