#!/usr/bin/env python
"""MF-END-11 lint fixups for app/services/shot_reskin_plan.py (new file, LF).

Seven exact replacements (import of the frozen refusal type + six long lines),
each asserted to occur EXACTLY once.  Growth-only vs shrink is not the point
here (a new allowlisted file); the asserts prove no accidental duplication.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11/app/services/shot_reskin_plan.py"
)

REPLACEMENTS: list[tuple[str, str]] = [
    (
        "from app.schemas.shot_reskin import (\n    SourceSpan,\n    TimebaseFacts,\n    payload_sha256,\n)",
        "from app.schemas.shot_reskin import (\n    ShotReskinRefusal,\n    SourceSpan,\n"
        "    TimebaseFacts,\n    payload_sha256,\n)",
    ),
    (
        '            output_trim_start=int(payload.get("output_trim_start", '
        'payload.get("output_trim", [0, 0])[0])),\n',
        '            output_trim_start=int(\n                payload.get("output_trim_start", '
        'payload.get("output_trim", [0, 0])[0])\n            ),\n',
    ),
    (
        '            output_trim_end=int(payload.get("output_trim_end", '
        'payload.get("output_trim", [0, 0])[1])),\n',
        '            output_trim_end=int(\n                payload.get("output_trim_end", '
        'payload.get("output_trim", [0, 0])[1])\n            ),\n',
    ),
    (
        '            protected_straddles=tuple(str(value) for value in '
        'payload.get("protected_straddles") or ()),\n',
        '            protected_straddles=tuple(\n                str(value) for value in '
        'payload.get("protected_straddles") or ()\n            ),\n',
    ),
    (
        '                f"chunk {chunk.chunk_id} core starts at {chunk.core.start_frame}, '
        'expected {cursor}",\n',
        '                f"chunk {chunk.chunk_id} core starts at {chunk.core.start_frame}, "\n'
        '                f"expected {cursor}",\n',
    ),
    (
        '        if chunk.context_right_frames != chunk.render.end_frame_exclusive - '
        'chunk.core.end_frame_exclusive:\n',
        '        if (\n            chunk.context_right_frames\n            != '
        'chunk.render.end_frame_exclusive - chunk.core.end_frame_exclusive\n        ):\n',
    ),
    (
        '            raise ShotPlanError(CODE_SERIALIZATION_INVALID, f"timebase block invalid: '
        '{err}") from err\n',
        '            raise ShotPlanError(\n                CODE_SERIALIZATION_INVALID, '
        'f"timebase block invalid: {err}"\n            ) from err\n',
    ),
]


def main() -> int:
    data = TARGET.read_text(encoding="utf-8")
    before = hashlib.sha256(data.encode("utf-8")).hexdigest()
    for index, (old, new) in enumerate(REPLACEMENTS):
        count = data.count(old)
        if count != 1:
            print(f"replacement #{index}: preimage count {count} != 1; refusing")
            return 2
        data = data.replace(old, new, 1)
    TARGET.write_text(data, encoding="utf-8", newline="")
    after = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    print(f"lint fixups applied: {len(REPLACEMENTS)}")
    print(f"  bytes {len(before) // 2 if False else 'see sha'} -> lines {data.count(chr(10))}")
    print(f"  sha256 {before[:16]} -> {after[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
