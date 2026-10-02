"""Byte-exact ruff fixes for MF-END-19 new code (CRLF-safe, count==1 asserted).

Fixes only NEW lint errors introduced by the task:
  * schemas/s10_full_apply.py: UP037 + E501
  * services/shot_reskin_executor.py: UP035 + E501 x4 + SIM102 + SIM105 x2
"""
from __future__ import annotations

import sys
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-19")
H = "\r\n"


def fix(rel: str, pairs: list[tuple[str, str]]) -> None:
    path = WT / rel
    with path.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    for old, new in pairs:
        old_c = old.replace("\n", H)
        new_c = new.replace("\n", H)
        count = text.count(old_c)
        if count != 1:
            print(f"ANCHOR FAIL {rel}: count={count} for {old_c[:70]!r}")
            sys.exit(1)
        text = text.replace(old_c, new_c)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print(f"FIXED {rel} ({len(pairs)} edits)")


fix(
    "app/schemas/s10_full_apply.py",
    [
        (
            '    def _cross_check(self) -> "ExecutionBackendManifest":',
            "    def _cross_check(self) -> ExecutionBackendManifest:",
        ),
        (
            '                "engine_base_url must be a loopback URL (the engine only ever drives a local instance)"',
            '                "engine_base_url must be loopback (the engine only drives a local instance)"',
        ),
    ],
)

fix(
    "app/services/shot_reskin_executor.py",
    [
        (
            "from typing import Any, Callable, Mapping",
            "from collections.abc import Callable, Mapping\nfrom typing import Any",
        ),
        (
            "import hashlib\nimport json\nimport re\nimport time",
            "import contextlib\nimport hashlib\nimport json\nimport re\nimport time",
        ),
        (
            '        blockers = list((eligibility or {}).get("blockers") or []) if isinstance(eligibility, dict) else []',
            '        blockers: list[Any] = []\n'
            "        if isinstance(eligibility, dict):\n"
            '            blockers = list(eligibility.get("blockers") or [])',
        ),
        (
            '        if ptype == "int":\n'
            "            if not isinstance(value, int) or isinstance(value, bool):\n"
            "                raise ShotRenderRefusal(\n"
            "                    ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,\n"
            '                    f"parameter {name!r} is declared int; got {type(value).__name__}",\n'
            "                )\n"
            '        elif ptype == "string":\n'
            "            if not isinstance(value, str):\n"
            "                raise ShotRenderRefusal(\n"
            "                    ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,\n"
            '                    f"parameter {name!r} is declared string; got {type(value).__name__}",\n'
            "                )",
            '        if ptype == "int" and (not isinstance(value, int) or isinstance(value, bool)):\n'
            "            raise ShotRenderRefusal(\n"
            "                ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,\n"
            '                f"parameter {name!r} is declared int; got {type(value).__name__}",\n'
            "            )\n"
            '        elif ptype == "string" and not isinstance(value, str):\n'
            "            raise ShotRenderRefusal(\n"
            "                ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,\n"
            '                f"parameter {name!r} is declared string; got {type(value).__name__}",\n'
            "            )",
        ),
        (
            "def _write_record(root: ManagedRoot, shot_id: str, chunk_id: str, payload: dict[str, Any]) -> dict[str, Any]:",
            "def _write_record(\n"
            "    root: ManagedRoot, shot_id: str, chunk_id: str, payload: dict[str, Any]\n"
            ") -> dict[str, Any]:",
        ),
        (
            "            try:\n"
            "                _write_record(\n"
            "                    root,\n"
            "                    shot_id,\n"
            "                    chunk_id,\n"
            "                    _rejected_payload(request=request, reasons=[refusal.as_dict()]),\n"
            "                )\n"
            "            except Exception:  # noqa: BLE001 — recording must never mask the refusal\n"
            "                pass",
            "            with contextlib.suppress(Exception):\n"
            "                # Recording must never mask the refusal itself.\n"
            "                _write_record(\n"
            "                    root,\n"
            "                    shot_id,\n"
            "                    chunk_id,\n"
            "                    _rejected_payload(request=request, reasons=[refusal.as_dict()]),\n"
            "                )",
        ),
        (
            "            try:\n"
            "                engine_obj.close()\n"
            "            except Exception:  # noqa: BLE001 — best-effort close\n"
            "                pass",
            "            with contextlib.suppress(Exception):\n"
            "                engine_obj.close()",
        ),
        (
            '    probed = probe_source_timebase(produced_path)\n'
            '    if tuple(probed) != (int(output_spec.get("fps_num") or fps_num), int(output_spec.get("fps_den") or fps_den)):',
            "    probed = probe_source_timebase(produced_path)\n"
            "    expected_tb = (\n"
            '        int(output_spec.get("fps_num") or fps_num),\n'
            '        int(output_spec.get("fps_den") or fps_den),\n'
            "    )\n"
            "    if tuple(probed) != expected_tb:",
        ),
        (
            '                "span": [int(span_raw.get("start_frame")), int(span_raw.get("end_frame_exclusive"))],',
            '                "span": [\n'
            '                    int(span_raw.get("start_frame")),\n'
            '                    int(span_raw.get("end_frame_exclusive")),\n'
            "                ],",
        ),
    ],
)
print("ALL FIXES APPLIED")
