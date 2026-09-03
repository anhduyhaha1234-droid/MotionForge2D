"""S11-T03C evidence generator — idempotency x2 byte-identical, severity
mapping, binding reason-code audit, hard-code scan, runner cross-process
idempotency.  Output: docs/pm/sessions/S11-T03C/evidence/audit.txt

Isolation enforced externally: env -u MOTIONFORGE_DATABASE_URL, short
Windows-native basetemp, -p no:cacheprovider.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[5]  # evidence→S11-T03C→sessions→pm→docs→root
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.persistence.models import QC_REASON_CODES  # noqa: E402
from app.services.qc_checks import (  # noqa: E402
    QC_RUNNER_OK,
    get_threshold,
    run_detector,
)
from app.services.qc_checks.contact_break import (  # noqa: E402
    DETECTOR_NAME as CB_NAME,
    detect_contact_break,
    register as register_cb,
)
from app.services.qc_checks.silhouette_clipping import (  # noqa: E402
    DETECTOR_NAME as SC_NAME,
    detect_silhouette_clipping,
    register as register_sc,
)
from app.services.qc_checks.z_order_error import (  # noqa: E402
    DETECTOR_NAME as ZO_NAME,
    detect_z_order_error,
    register as register_zo,
)

WINDOW = {"start_frame": 0, "end_frame": 47}
W = WINDOW["end_frame"] - WINDOW["start_frame"] + 1


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def contact_args():
    blk = get_threshold("contact_break")["blocker_boundary"]
    a = {"id": "seg-a", "logical_id": "L-seg-a", "z_order": 10,
         "start_frame": 0, "end_frame": 47, "mask_artifact_id": "mask-a",
         "bbox_per_frame": [[10.0, 10.0, 40.0, 20.0]] * W}
    b = {"id": "seg-b", "logical_id": "L-seg-b", "z_order": 20,
         "start_frame": 0, "end_frame": 47, "mask_artifact_id": "mask-b",
         "bbox_per_frame": [[10.0, 20.0 + blk, 40.0, 40.0 + blk]] * W}
    return {"analysis_window": WINDOW,
            "contacts": [{"id": "c1", "source_segment_id": "seg-a",
                          "target_segment_id": "seg-b", "contact_kind": "touch",
                          "start_frame": 0, "end_frame": 20,
                          "confidence": 0.98, "confidence_source": "derived"}],
            "segments": [a, b]}


def zorder_args():
    segments = [{"id": f"s{i}", "z_order": 9 - i, "start_frame": 0,
                 "end_frame": 47} for i in range(9)]
    edges = [{"id": f"e{i}", "occluder_segment_id": f"s{i}",
              "occludee_segment_id": f"s{i + 1}", "start_frame": 0,
              "end_frame": 47, "confidence": 0.99,
              "confidence_source": "derived"} for i in range(8)]
    return {"analysis_window": WINDOW, "segments": segments,
            "occlusion_edges": edges,
            "render_order": [f"s{i}" for i in range(9)]}


def clip_args():
    return {"analysis_window": WINDOW, "frame": {"width": 100.0, "height": 100.0},
            "segments": [{"id": "seg-a", "logical_id": "L-seg-a", "z_order": 10,
                          "start_frame": 0, "end_frame": 47,
                          "mask_artifact_id": "mask-a",
                          "bbox": [70.0, 30.0, 130.0, 70.0]}]}


def main() -> int:
    lines: list[str] = []
    add = lines.append

    # 1. binding reason codes (Decision B partition — corrected 10-code enum)
    add("== 1. Binding reason codes ==")
    for name in (CB_NAME, ZO_NAME, SC_NAME):
        add(f"  {name}: in QC_REASON_CODES = {name in QC_REASON_CODES}")
        assert name in QC_REASON_CODES, f"{name} not in binding enum"

    # 2. severity mapping + policy provenance per detector
    add("== 2. Severity mapping vs frozen T03A policy ==")
    for metric in ("contact_break", "z_order_error", "silhouette_clipping"):
        entry = get_threshold(metric)
        add(f"  {metric}: warn={entry['warning_boundary']} "
            f"block={entry['blocker_boundary']} unit={entry['unit']} "
            f"kind={entry['kind']} fixture={entry['provenance']['fixture']}")

    # 3. idempotency x2 (same args, two calls) — evidence byte-identical
    add("== 3. Evidence idempotency x2 (same args, in-process) ==")
    cases = [
        ("contact_break", detect_contact_break, contact_args()),
        ("z_order_error", detect_z_order_error, zorder_args()),
        ("silhouette_clipping", detect_silhouette_clipping, clip_args()),
    ]
    for name, fn, args in cases:
        first = fn(args)
        second = fn(args)
        same = canonical_json(first) == canonical_json(second)
        keys_same = first[0]["evidence_window_key"] == second[0]["evidence_window_key"]
        add(f"  {name}: items={len(first)} byte_identical={same} "
            f"window_key_identical={keys_same} "
            f"schema_version={first[0]['evidence']['schema_version']}")
        assert same and keys_same and first[0]["evidence"]["schema_version"] == 1

    # 4. cross-process idempotency through the T03A bounded runner
    add("== 4. Cross-process idempotency (bounded runner x2) ==")
    for fn in (register_cb, register_zo, register_sc):
        fn()
    r1 = run_detector(ZO_NAME, args=zorder_args(), deadline_sec=30.0,
                      capture_cap_bytes=65536)
    r2 = run_detector(ZO_NAME, args=zorder_args(), deadline_sec=30.0,
                      capture_cap_bytes=65536)
    same = canonical_json(r1.output) == canonical_json(r2.output)
    add(f"  z_order_error: run1={r1.code} run2={r2.code} "
        f"status={r1.status} byte_identical={same}")
    assert r1.code == QC_RUNNER_OK and r2.code == QC_RUNNER_OK and same

    # 5. hard-code scan: no boundary literal in any detector module
    add("== 5. Hard-code scan (boundary literals absent from detectors) ==")
    detector_dir = _PROJECT_ROOT / "app" / "services" / "qc_checks"
    banned = ("4.0", "16.0", "0.166666667", "0.5", "warning_boundary =", "blocker_boundary =")
    for fname in ("contact_break.py", "z_order_error.py", "silhouette_clipping.py"):
        text = (detector_dir / fname).read_text(encoding="utf-8")
        hits = [b for b in banned if b in text]
        add(f"  {fname}: boundary literals found = {hits if hits else 'NONE'}")
        assert not hits, f"{fname} contains hard-coded boundary tokens: {hits}"

    out = Path(__file__).resolve().parent / "audit.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nAUDIT_WRITTEN={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())