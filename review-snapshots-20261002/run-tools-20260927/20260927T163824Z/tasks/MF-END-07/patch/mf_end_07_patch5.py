"""MF-END-07 patch #5: normalise the 4 LF-only newlines patch #3 inserted.

The file is CRLF throughout; patch #3 inserted its replacement block with LF
newlines, so 4 lines ended up LF-only.  This restores the file's own newline
convention byte-for-byte everywhere else (assert-counted, no other change).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)


def main() -> int:
    path = ROOT / "app/schemas/project_cast.py"
    before = path.read_bytes()
    lone_lf = len(re.findall(rb"(?<!\r)\n", before))
    assert lone_lf == 4, f"expected exactly 4 lone LF, found {lone_lf}"
    after = re.sub(rb"(?<!\r)\n", b"\r\n", before)
    assert after.count(b"\r\n") == after.count(b"\n"), "still mixed"
    assert after.replace(b"\r\n", b"\n") == before.replace(b"\r\n", b"\n"), (
        "content changed beyond newline normalisation"
    )
    path.write_bytes(after)
    record = {
        "path": "app/schemas/project_cast.py",
        "edit": "normalise 4 LF-only newlines to CRLF (content proven unchanged)",
        "lone_lf_fixed": lone_lf,
        "sha256_before": hashlib.sha256(before).hexdigest(),
        "sha256_after": hashlib.sha256(after).hexdigest(),
        "bytes_before": len(before),
        "bytes_after": len(after),
        "crlf_after": after.count(b"\r\n") == after.count(b"\n"),
    }
    (EV / "raw" / "patch_applied5.json").write_text(
        json.dumps(record, indent=1), encoding="utf-8"
    )
    print(json.dumps(record, indent=1))
    print("PATCH5_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
