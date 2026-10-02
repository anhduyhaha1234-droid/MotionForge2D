"""MF-END-22 lint fix: trailing newline + flicker item rebind (bounded).

Reads each file as bytes, verifies the expected preimage fragment is present
exactly once, applies the bounded replacement and writes the bytes back.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-22"
)
FILES = [
    "app/services/qc_checks/contact_break.py",
    "app/services/qc_checks/z_order_error.py",
    "app/services/qc_checks/trajectory_drift.py",
    "app/services/qc_checks/identity_drift.py",
    "app/services/qc_checks/temporal_flicker.py",
]


def ensure_newline(path: Path) -> str:
    data = path.read_bytes()
    if data.endswith(b"\n"):
        return "already"
    path.write_bytes(data + b"\n")
    return "added"


def replace_once(path: Path, old: bytes, new: bytes) -> int:
    data = path.read_bytes()
    count = data.count(old)
    if count != 1:
        print(f"PREIMAGE_COUNT={count} for {path.name}: refusing")
        return 1
    path.write_bytes(data.replace(old, new, 1))
    return 0


def main() -> int:
    rc = 0
    for relative in FILES:
        path = ROOT / relative
        state = ensure_newline(path)
        print(f"newline {relative}: {state}")

    flicker = ROOT / "app/services/qc_checks/temporal_flicker.py"
    old_block = (
        b"        items.append(\r\n"
        b"            qcm.comparison_item(\r\n"
        b'                metric=qcm.METRIC_MOTION_ATTENUATION + ":flicker",\r\n'
        b"                code=CODE_FLICKER_BLOCKER,\r\n"
    )
    new_block = (
        b"        items.append(\r\n"
        b"            _flicker_item(\r\n"
        b"                code=CODE_FLICKER_BLOCKER,\r\n"
    )
    rc |= replace_once(flicker, old_block, new_block)
    old_block2 = (
        b"        items.append(\r\n"
        b"            qcm.comparison_item(\r\n"
        b'                metric=qcm.METRIC_MOTION_ATTENUATION + ":flicker",\r\n'
        b"                code=CODE_FLICKER_WARNING,\r\n"
    )
    new_block2 = (
        b"        items.append(\r\n"
        b"            _flicker_item(\r\n"
        b"                code=CODE_FLICKER_WARNING,\r\n"
    )
    rc |= replace_once(flicker, old_block2, new_block2)

    old_frames = (
        b'    frames = list(range(int(window.get("start_frame", 0)), '
        b'int(window.get("start_frame", 0)) + len(luminance)))\r\n'
    )
    new_frames = (
        b'    window_start = int(window.get("start_frame", 0))\r\n'
        b"    frames = list(range(window_start, window_start + len(luminance)))\r\n"
    )
    rc |= replace_once(flicker, old_frames, new_frames)

    zorder = ROOT / "app/services/qc_checks/z_order_error.py"
    old_hidden = (
        b"\r\n"
        b"        def _hidden(role_rows: dict[str, Any]) -> list[int]:\r\n"
        b"            hidden = (\r\n"
        b'                set(role_rows["occluded_frames"])\r\n'
        b'                | set(role_rows["gap_frames"])\r\n'
        b'                | set(role_rows["out_of_frame_frames"])\r\n'
        b"            )\r\n"
        b"            return sorted(hidden & set(frames))\r\n"
    )
    rc |= replace_once(zorder, old_hidden, b"\r\n")
    old_calls = b"        occludee_hidden = _hidden(occludee)\r\n        occluder_hidden = _hidden(occluder)\r\n"
    new_calls = (
        b"        occludee_hidden = _hidden_frames(occludee, frames)\r\n"
        b"        occluder_hidden = _hidden_frames(occluder, frames)\r\n"
    )
    rc |= replace_once(zorder, old_calls, new_calls)
    old_helper_anchor = b'_reference_extent(\r\n'
    helper = (
        b"def _hidden_frames(role_rows: Mapping[str, Any], frames: list[int]) -> list[int]:\r\n"
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
    rc |= replace_once(zorder, old_helper_anchor, helper + old_helper_anchor)

    contact = ROOT / "app/services/qc_checks/contact_break.py"
    old_imports = (
        b'from app.services.qc_checks.thresholds import (\r\n'
        b"    STATUS_BLOCKER,\r\n"
        b"    classify,\r\n"
        b"    get_threshold,\r\n"
        b")\r\n"
        b"from app.services import source_interaction_facts as sif\r\n"
        b"from app.services.qc_evidence import measure as qcm\r\n"
    )
    new_imports = (
        b"from app.services import source_interaction_facts as sif\r\n"
        b'from app.services.qc_checks.thresholds import (\r\n'
        b"    STATUS_BLOCKER,\r\n"
        b"    classify,\r\n"
        b"    get_threshold,\r\n"
        b")\r\n"
        b"from app.services.qc_evidence import measure as qcm\r\n"
    )
    rc |= replace_once(contact, old_imports, new_imports)
    return rc


if __name__ == "__main__":
    sys.exit(main())
