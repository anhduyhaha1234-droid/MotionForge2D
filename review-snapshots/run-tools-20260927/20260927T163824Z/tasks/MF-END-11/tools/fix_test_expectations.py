#!/usr/bin/env python
"""MF-END-11 — correct two test expectations (measured planner behaviour)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/tests/product_delivery/test_mf_end_11.py"
)

OLD1 = (
    "    partition = plan.plan_shot_intervals([0, 5, 5, 90, -3, 10], 100)\n"
    "    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [\n"
    "        (0, 5),\n"
    "        (5, 10),\n"
    "        (10, 100),\n"
    "    ]\n"
    "    assert [(d.cut_frame, d.reason) for d in partition.dropped_cuts] == [\n"
    '        (0, "at_zero"),\n'
    '        (5, "duplicate"),\n'
    '        (90, "out_of_range"),\n'
    '        (-3, "out_of_range"),\n'
    "    ]\n"
)
NEW1 = (
    "    partition = plan.plan_shot_intervals([0, 5, 5, 120, -3, 10], 100)\n"
    "    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [\n"
    "        (0, 5),\n"
    "        (5, 10),\n"
    "        (10, 100),\n"
    "    ]\n"
    "    assert [(d.cut_frame, d.reason) for d in partition.dropped_cuts] == [\n"
    '        (0, "at_zero"),\n'
    '        (5, "duplicate"),\n'
    '        (120, "out_of_range"),\n'
    '        (-3, "out_of_range"),\n'
    "    ]\n"
)

OLD2 = (
    "    # Self-consistent tamper (span + chunk) so the COVERAGE law is the one red.\n"
    '    payload["shots"][0]["span"] = [0, 29]\n'
    '    payload["shots"][0]["chunks"][0]["core"] = [0, 29]\n'
)
NEW2 = (
    "    # Self-consistent tamper (span = core = render = trim) so ONLY the\n"
    "    # coverage law is red, not the per-chunk consistency checks.\n"
    '    payload["shots"][0]["span"] = [0, 29]\n'
    '    payload["shots"][0]["chunks"][0]["core"] = [0, 29]\n'
    '    payload["shots"][0]["chunks"][0]["render"] = [0, 29]\n'
    '    payload["shots"][0]["chunks"][0]["output_trim_end"] = 29\n'
)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    before = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for index, (old, new) in enumerate(((OLD1, NEW1), (OLD2, NEW2))):
        count = text.count(old)
        if count != 1:
            print(f"replacement #{index}: preimage count {count} != 1; refusing")
            return 2
        text = text.replace(old, new, 1)
    TARGET.write_text(text, encoding="utf-8", newline="")
    after = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    print(f"expectation fixups applied: 2")
    print(f"  lines {text.count(chr(10))}")
    print(f"  sha256 {before[:16]} -> {after[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
