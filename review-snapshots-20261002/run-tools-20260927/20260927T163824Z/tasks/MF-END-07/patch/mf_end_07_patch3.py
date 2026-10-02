"""MF-END-07 patch #3: fix the three undefined names found by ruff (bounded preimage)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)

EDITS = {
    "app/schemas/project_cast.py": [
        (
            "from app.schemas.cast_recommendation import REQUIRED_VIEW_VOCABULARY",
            "from app.schemas.cast_recommendation import (\n"
            "    REQUIRED_VIEW_VOCABULARY,\n"
            "    _unique_nonempty,\n"
            ")",
        ),
    ],
    "app/api/routes/project_cast.py": [
        ("from sqlalchemy.orm import joinedload", "from sqlalchemy.orm import Session, joinedload"),
    ],
}


def main() -> int:
    records = []
    for rel, edits in EDITS.items():
        path = ROOT / rel
        before = path.read_bytes()
        text = before.decode("utf-8")
        for old, new in edits:
            count = text.count(old)
            assert count == 1, f"{rel}: preimage count {count} != 1"
            text = text.replace(old, new, 1)
        path.write_bytes(text.encode("utf-8"))
        after = path.read_bytes()
        records.append(
            {
                "path": rel,
                "edits": len(edits),
                "sha256_before": hashlib.sha256(before).hexdigest(),
                "sha256_after": hashlib.sha256(after).hexdigest(),
                "bytes_before": len(before),
                "bytes_after": len(after),
                "crlf_after": after.count(b"\r\n") == after.count(b"\n"),
            }
        )
    (EV / "raw" / "patch_applied3.json").write_text(
        json.dumps(records, indent=1), encoding="utf-8"
    )
    print(json.dumps(records, indent=1))
    print("PATCH3_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
