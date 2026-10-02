#!/usr/bin/env python
"""MF-END-11 — three deterministic fixups in the new test file (LF)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/tests/product_delivery/test_mf_end_11.py"
)

REPLACEMENTS: list[tuple[str, str]] = [
    (
        "    assert [(d.cut_frame, d.reason) for d in partition.dropped_cuts] == [\n"
        '        (0, "at_zero"),\n'
        '        (90, "out_of_range"),\n'
        '        (-3, "out_of_range"),\n'
        '        (5, "duplicate"),\n'
        "    ]\n",
        "    assert [(d.cut_frame, d.reason) for d in partition.dropped_cuts] == [\n"
        '        (0, "at_zero"),\n'
        '        (5, "duplicate"),\n'
        '        (90, "out_of_range"),\n'
        '        (-3, "out_of_range"),\n'
        "    ]\n",
    ),
    (
        "    assert facts.pts_uniform is False\n"
        "    # Duration x avg-fps must NOT be trusted as the frame count.\n"
        "    assert facts.frame_count != round(2.0 * 45 / 2) or True  # documented, not enforced\n",
        "    assert facts.pts_uniform is False\n",
    ),
    (
        'def test_artifact_span_tamper_refuses_coverage(cfr30: Path) -> None:\n'
        "    payload = plan.build_shot_plan(cfr30).to_json()\n"
        '    payload["shots"][0]["span"] = [1, 30]  # coverage of [0, 30) is broken\n'
        "    _refuses(plan.CODE_COVERAGE_INVALID, plan.ShotPlanArtifact.from_json, payload)\n",
        'def test_artifact_span_tamper_refuses_coverage(cfr30: Path) -> None:\n'
        "    payload = plan.build_shot_plan(cfr30).to_json()\n"
        "    # Self-consistent tamper (span + chunk) so the COVERAGE law is the one red.\n"
        '    payload["shots"][0]["span"] = [0, 29]\n'
        '    payload["shots"][0]["chunks"][0]["core"] = [0, 29]\n'
        "    _refuses(plan.CODE_COVERAGE_INVALID, plan.ShotPlanArtifact.from_json, payload)\n",
    ),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    before = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for index, (old, new) in enumerate(REPLACEMENTS):
        count = text.count(old)
        if count != 1:
            print(f"replacement #{index}: preimage count {count} != 1; refusing")
            return 2
        text = text.replace(old, new, 1)
    TARGET.write_text(text, encoding="utf-8", newline="")
    after = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    print(f"test fixups applied: {len(REPLACEMENTS)}")
    print(f"  lines {text.count(chr(10))}")
    print(f"  sha256 {before[:16]} -> {after[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
