"""MF-END-10 — byte before/after cho write-set (worker evidence, không thay guard của Manager).

- "before": bytes tại base commit c0c99519 (worktree sạch trước khi writer chạy)
  → lấy bằng `git show <base>:<path>`.
- "after": bytes trên đĩa sau khi writer xong.

Chỉ đọc; không ghi vào worktree.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-10")
BASE = "c0c99519072d49e319724e2d06ebbc0a651bd9c1"

ALLOWLIST = [
    "frontend/src/app/(app)/characters/page.tsx",
    "frontend/src/features/project-cast/ProjectCastPicker.tsx",
    "frontend/src/features/project-cast/LibraryPicker.tsx",
    "frontend/src/features/project-cast/CompatibilityWarnings.tsx",
    "frontend/src/features/reference-library/referenceLibraryApi.ts",
    "frontend/src/features/reference-library/reasonText.ts",
    "frontend/src/features/reference-library/ReferenceViewBoard.tsx",
    "frontend/src/features/reference-library/CastRecommendationPanel.tsx",
    "frontend/src/features/reference-library/index.ts",
    "tests/product_delivery/test_mf_end_10.py",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def git_bytes(path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(WORKTREE), "show", f"{BASE}:{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def main() -> int:
    manifest = {
        "task": "MF-END-10",
        "base": BASE,
        "captured_at": datetime.now(UTC).isoformat(),
        "paths": {},
    }
    for rel in ALLOWLIST:
        before = git_bytes(rel)
        abs_path = WORKTREE / rel
        after = abs_path.read_bytes() if abs_path.is_file() else None
        manifest["paths"][rel] = {
            "before": None
            if before is None
            else {"sha256": _sha(before), "bytes": len(before), "lines": _lines(before)},
            "after": None
            if after is None
            else {"sha256": _sha(after), "bytes": len(after), "lines": _lines(after)},
        }
    print(json.dumps(manifest, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
