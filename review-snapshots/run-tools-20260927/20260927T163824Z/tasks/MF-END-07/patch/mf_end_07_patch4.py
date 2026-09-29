"""MF-END-07 patch #4: import GenerationPlanData (bounded preimage)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)

OLD = """from app.schemas.cast_recommendation import (
    REQUIRED_VIEW_VOCABULARY,
    _unique_nonempty,
)"""
NEW = """from app.schemas.cast_recommendation import (
    REQUIRED_VIEW_VOCABULARY,
    GenerationPlanData,
    _unique_nonempty,
)"""


def main() -> int:
    path = ROOT / "app/schemas/project_cast.py"
    before = path.read_bytes()
    text = before.decode("utf-8")
    assert text.count(OLD) == 1, "preimage count != 1"
    path.write_bytes(text.replace(OLD, NEW, 1).encode("utf-8"))
    after = path.read_bytes()
    record = {
        "path": "app/schemas/project_cast.py",
        "edit": "import GenerationPlanData",
        "sha256_before": hashlib.sha256(before).hexdigest(),
        "sha256_after": hashlib.sha256(after).hexdigest(),
        "bytes_before": len(before),
        "bytes_after": len(after),
        "crlf_after": after.count(b"\r\n") == after.count(b"\n"),
    }
    (EV / "raw" / "patch_applied4.json").write_text(
        json.dumps(record, indent=1), encoding="utf-8"
    )
    print(json.dumps(record, indent=1))
    print("PATCH4_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
