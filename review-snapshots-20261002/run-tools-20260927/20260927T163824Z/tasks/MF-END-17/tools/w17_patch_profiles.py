"""MF-END-17 — bounded preimage patch for app/media_workflows/model_profiles.json.

The file EXISTS at base (7,360 B, sha 629f7a14...) so it must be edited with a bounded
patch that asserts its exact preimage, never with whole-file generation.  Every replacement
below asserts count(old)==1 on the raw bytes (CRLF preserved) before writing, and the patched
document is re-checked against the predecessor's own invariants (test_mf_end_16 contract).

Usage: python -B tools/w17_patch_profiles.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-17")
REL = "app/media_workflows/model_profiles.json"
PATH = WORKTREE / REL
PREIMAGE_SHA = "629f7a14f2fc9b38476e63a103195007bc2a78ba589e6b8551d0b8915c9b2df6"

REPLACEMENTS = [
    # 1. vace profile gains a pointer to the controlled-shot artifact (additive)
    (
        '   "benchmark": {\r\n'
        '    "status": "COMPLETE_TECHNICAL",\r\n'
        '    "scope": "BOOK case only, same unit/seed as the Wan baseline"\r\n'
        '   },\r\n',
        '   "benchmark": {\r\n'
        '    "status": "COMPLETE_TECHNICAL",\r\n'
        '    "scope": "BOOK case only, same unit/seed as the Wan baseline"\r\n'
        '   },\r\n'
        '   "controlled_artifact": {\r\n'
        '    "graph_id": "controlled_shot_v1",\r\n'
        '    "graph_file": "app/media_workflows/controlled_shot_v1.json",\r\n'
        '    "manifest_file": "app/media_workflows/controlled_shot_v1.manifest.json",\r\n'
        '    "controlled_path_status": "UNSUPPORTED_ON_THIS_RUNTIME",\r\n'
        '    "decided_by": "MF-END-17"\r\n'
        '   },\r\n',
    ),
    # 2. the END-17 note is resolved in place (kept, outcome appended)
    (
        '"end17_note": "no profile change is forced by speed; END-17 activates only if review rejects the Wan candidate or the masked-edit path is required"',
        '"end17_note": "no profile change is forced by speed; END-17 resolved: activation trigger not met on the measured rows -> SKIPPED_NOT_NEEDED (not a test pass); the masked-edit path stays UNSUPPORTED (SCAIL-2 weights absent; VACE watermark blocker) - see controlled_shot_v1.manifest.json"',
    ),
    # 3. top-level controlled_shot record (additive)
    (
        '  "decided_by": "MF-END-16 worker per packet 16.4 (eligibility measured here; quality acceptance reserved)"\r\n'
        ' },\r\n'
        ' "claims": {\r\n',
        '  "decided_by": "MF-END-16 worker per packet 16.4 (eligibility measured here; quality acceptance reserved)"\r\n'
        ' },\r\n'
        ' "controlled_shot": {\r\n'
        '  "artifact": "app/media_workflows/controlled_shot_v1.json",\r\n'
        '  "manifest": "app/media_workflows/controlled_shot_v1.manifest.json",\r\n'
        '  "activation": "SKIPPED_NOT_NEEDED",\r\n'
        '  "counts_as_test_pass": false,\r\n'
        '  "path_status": "UNSUPPORTED_ON_THIS_RUNTIME",\r\n'
        '  "candidates": {\r\n'
        '   "scail2_wan_scail": "BLOCKED_NO_WEIGHTS",\r\n'
        '   "vace_14b_fp16_book": "MEASURED_INELIGIBLE (copies the source watermark)"\r\n'
        '  },\r\n'
        '  "decided_by": "MF-END-17 worker (measured rows only; quality acceptance reserved)"\r\n'
        ' },\r\n'
        ' "claims": {\r\n',
    ),
]


def check_invariants(doc: dict) -> list[str]:
    """the predecessor's own contract (test_mf_end_16.py) must keep passing."""
    failures: list[str] = []
    prof = doc
    if len(prof["profiles"]) != 2:
        failures.append("profiles length != 2")
    ids = {p["id"]: p for p in prof["profiles"]}
    wan = ids.get("wan_animate2_int8_pad640x368_cacheoff", {})
    vace = ids.get("vace_14b_fp16_book", {})
    if wan.get("benchmark", {}).get("status") != "COMPLETE":
        failures.append("wan benchmark status changed")
    if wan.get("eligibility", {}).get("status") != "ELIGIBLE_PENDING_QUALITY_OWNER":
        failures.append("wan eligibility status changed")
    if vace.get("benchmark", {}).get("status") != "COMPLETE_TECHNICAL":
        failures.append("vace benchmark status changed")
    if vace.get("eligibility", {}).get("status") != "INELIGIBLE":
        failures.append("vace eligibility changed")
    if not any("watermark" in b.lower() for b in vace.get("eligibility", {}).get("blockers", [])):
        failures.append("vace watermark blocker lost")
    if prof["selection"]["chosen"] != "wan_animate2_int8_pad640x368_cacheoff":
        failures.append("selection.chosen changed")
    if prof["claims"]["no_best_newest_claim"] is not True:
        failures.append("no_best_newest_claim lost")
    if prof["claims"]["quality_accepted"] is not False:
        failures.append("quality_accepted claim changed")
    blob = json.dumps(prof).lower()
    for banned in ("best model", "newest model", "fastest model"):
        if banned in blob:
            failures.append(f"banned claim leaked: {banned}")
    for p in prof["profiles"]:
        cost = p["cost"]
        if cost["accepted_seconds"] == 0 and cost["cost_per_accepted_second"] != "UNDEFINED":
            failures.append(f"{p['id']}: fabricated denominator")
    return failures


def main() -> int:
    data = PATH.read_bytes()
    before_sha = hashlib.sha256(data).hexdigest()
    if before_sha != PREIMAGE_SHA:
        print(json.dumps({"error": "PREIMAGE MISMATCH — refusing to patch",
                          "expected": PREIMAGE_SHA, "got": before_sha}))
        return 2
    text = data.decode("utf-8")
    for old, new in REPLACEMENTS:
        n = text.count(old)
        if n != 1:
            print(json.dumps({"error": f"preimage count {n} != 1", "anchor": old[:80]}))
            return 2
        text = text.replace(old, new)
    out = text.encode("utf-8")
    doc = json.loads(out.decode("utf-8"))
    failures = check_invariants(doc)
    if failures:
        print(json.dumps({"error": "invariant failures", "failures": failures}))
        return 2
    PATH.write_bytes(out)
    after = PATH.read_bytes()
    record = {
        "file": REL,
        "before_sha256": before_sha, "before_bytes": len(data), "before_lines": data.count(b"\n") + 1,
        "after_sha256": hashlib.sha256(after).hexdigest(), "after_bytes": len(after),
        "after_lines": after.count(b"\n") + 1,
        "replacements": len(REPLACEMENTS), "grew_bytes": len(after) - len(data),
        "invariants_ok": True,
    }
    (Path(__file__).resolve().parent.parent / "raw" / "profile_patch_record.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
