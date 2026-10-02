"""MF-END-07 patch #2: add the missing `field_validator` import (bounded preimage)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)

OLD = "from pydantic import BaseModel, ConfigDict, Field, model_validator"
NEW = "from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator"


def main() -> int:
    path = ROOT / "app/schemas/project_cast.py"
    before = path.read_bytes()
    text = before.decode("utf-8")
    assert text.count(OLD) == 1, "preimage count != 1"
    text = text.replace(OLD, NEW, 1)
    path.write_bytes(text.encode("utf-8"))
    after = path.read_bytes()
    record = {
        "path": "app/schemas/project_cast.py",
        "edit": "add field_validator import (missing in patch #1)",
        "sha256_before": hashlib.sha256(before).hexdigest(),
        "sha256_after": hashlib.sha256(after).hexdigest(),
        "bytes_before": len(before),
        "bytes_after": len(after),
        "crlf_after": after.count(b"\r\n") == after.count(b"\n"),
    }
    (EV / "raw" / "patch_applied2.json").write_text(
        json.dumps(record, indent=1), encoding="utf-8"
    )
    print(json.dumps(record, indent=1))
    print("PATCH2_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
