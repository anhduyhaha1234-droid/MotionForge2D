"""Convert the NEW DELTA-F2 test file to CRLF (repo convention) and verify.

Write-tool output is LF; every other file in this worktree is CRLF
(core.autocrlf=true), so normalise the new file byte-wise and assert the result
has no mixed endings.  Idempotent.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
TARGETS = [WT / "tests" / "product_delivery" / "test_delta_f2.py"]


def main() -> int:
    for path in TARGETS:
        data = path.read_bytes()
        lf = data.count(b"\n")
        crlf = data.count(b"\r\n")
        lone_cr = data.count(b"\r") - crlf
        if crlf == lf and lone_cr == 0:
            print(f"{path.name}: already CRLF (lf={lf} crlf={crlf})")
            continue
        assert lone_cr == 0, f"{path.name} has lone CR bytes"
        fixed = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        new_crlf = fixed.count(b"\r\n")
        assert new_crlf == fixed.count(b"\n") == lf
        path.write_bytes(fixed)
        print(f"{path.name}: lf={lf} crlf {crlf}->{new_crlf} "
              f"sha256 {hashlib.sha256(fixed).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
