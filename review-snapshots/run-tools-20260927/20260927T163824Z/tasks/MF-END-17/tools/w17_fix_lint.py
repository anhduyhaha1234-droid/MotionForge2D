"""MF-END-17 — fix the 12 E501 findings on the test file (exact-line replacements).

Also normalises end-of-line to CRLF (repo convention) with a final newline.
Each replacement asserts exactly one occurrence before writing.
"""

from __future__ import annotations

import sys
from pathlib import Path

P = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-17/tests/product_delivery/test_mf_end_17.py")

FIXES = [
    (
        'RUN_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-17")',
        'RUN_ROOT = Path(\n'
        '    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-17"\n'
        ')',
    ),
    (
        'PROOF_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")',
        'PROOF_ROOT = Path(\n'
        '    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof"\n'
        ')',
    ),
    (
        '            verdicts = [gates.get(k, {}).get("verdict") for k in ("real_local_mp4", "quality", "vram")]',
        '            verdicts = [gates.get(k, {}).get("verdict")\n'
        '                        for k in ("real_local_mp4", "quality", "vram")]',
    ),
    (
        '                "candidates", "path_status", "eligibility_policy", "model_area_policy", "claims", "evidence"):',
        '                "candidates", "path_status", "eligibility_policy", "model_area_policy",\n'
        '                "claims", "evidence"):',
    ),
    (
        '    for banned in ("supports multi-reference", "supports multiple references", "multi-ref workflow"):',
        '    banned_phrases = ("supports multi-reference", "supports multiple references",\n'
        '                      "multi-ref workflow")\n'
        '    for banned in banned_phrases:',
    ),
    (
        '    for fid in ("F1_GEOMETRY_CROP", "F2_PROMPT_CARRYOVER", "F3_SEGMENT_AT_CUT", "F4_WATERMARK_COPY",\n'
        '                "F5_BOOK_STATE", "F6_RAM_INSTRUMENT", "F7_SEAM_FLAG_BOOK", "F8_TURN_TRANSIENT_GLYPH"):',
        '    for fid in ("F1_GEOMETRY_CROP", "F2_PROMPT_CARRYOVER", "F3_SEGMENT_AT_CUT",\n'
        '                "F4_WATERMARK_COPY", "F5_BOOK_STATE", "F6_RAM_INSTRUMENT",\n'
        '                "F7_SEAM_FLAG_BOOK", "F8_TURN_TRANSIENT_GLYPH"):',
    ),
    (
        '    assert d["graph_validation"]["p0_object_info"]["ok"] and d["graph_validation"]["p3_object_info_gpu"]["ok"]',
        '    assert d["graph_validation"]["p0_object_info"]["ok"]\n'
        '    assert d["graph_validation"]["p3_object_info_gpu"]["ok"]',
    ),
    (
        '    ("multi_ref_claimed", lambda d: d["contract"]["multi_reference"].update({"claimed_multi_ref": True})),',
        '    ("multi_ref_claimed",\n'
        '     lambda d: d["contract"]["multi_reference"].update({"claimed_multi_ref": True})),',
    ),
    (
        '    ("candidate_multi_ref_claimed", lambda d: d["candidates"][1]["semantics"].update({"multi_ref_claim": True})),',
        '    ("candidate_multi_ref_claimed",\n'
        '     lambda d: d["candidates"][1]["semantics"].update({"multi_ref_claim": True})),',
    ),
    (
        '    ("gate_loosening_allowed", lambda d: d["contract"].update({"gate_loosening": "allowed for challengers"})),',
        '    ("gate_loosening_allowed",\n'
        '     lambda d: d["contract"].update({"gate_loosening": "allowed for challengers"})),',
    ),
    (
        '        return [gates[k]["verdict"] for k in ("real_local_mp4", "quality", "vram")] == ["PASS", "PASS", "PASS"]',
        '        checked = ("real_local_mp4", "quality", "vram")\n'
        '        return [gates[k]["verdict"] for k in checked] == ["PASS", "PASS", "PASS"]',
    ),
    (
        '    base = {"real_local_mp4": {"verdict": "PASS"}, "quality": {"verdict": "PASS"}, "vram": {"verdict": "PASS"}}',
        '    base = {\n'
        '        "real_local_mp4": {"verdict": "PASS"},\n'
        '        "quality": {"verdict": "PASS"},\n'
        '        "vram": {"verdict": "PASS"},\n'
        '    }',
    ),
]


def main() -> int:
    text = P.read_bytes().decode("utf-8").replace("\r\n", "\n")
    for i, (old, new) in enumerate(FIXES):
        n = text.count(old)
        if n != 1:
            print(f"FIX {i}: count {n} != 1 for anchor: {old[:70]!r}")
            return 2
        text = text.replace(old, new)
    out = text.replace("\n", "\r\n").encode("utf-8")
    if not out.endswith(b"\r\n"):
        out += b"\r\n"
    P.write_bytes(out)
    print(f"fixed {len(FIXES)} lines; bytes={len(out)} crlf={out.count(bytes([13, 10]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
