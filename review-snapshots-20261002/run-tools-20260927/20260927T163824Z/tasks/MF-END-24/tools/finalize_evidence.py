"""MF-END-24 evidence manifest + hash16 (deterministic; excludes itself)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-24"
)
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24")
EXCLUDE_NAMES = {"evidence_manifest.json"}

SHIPPED = [
    "frontend/src/features/shot-review/shotReviewLogic.ts",
    "frontend/src/features/shot-review/shotReviewApi.ts",
    "frontend/src/features/shot-review/useShotReview.ts",
    "frontend/src/features/shot-review/BeforeAfterSync.tsx",
    "frontend/src/features/shot-review/QcMarkerList.tsx",
    "frontend/src/features/shot-review/ShotList.tsx",
    "frontend/src/features/shot-review/ShotReviewPanel.tsx",
    "frontend/src/features/shot-review/index.ts",
    "frontend/src/features/apply/ApplyShotReview.tsx",
    "frontend/src/features/apply/ApplyProgress.tsx",
    "frontend/src/features/apply/index.ts",
    "frontend/src/features/demo/DemoShotReview.tsx",
    "frontend/src/features/demo/DemoComparePanel.tsx",
    "tests/product_delivery/test_mf_end_24.py",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    files: dict[str, dict] = {}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.name in EXCLUDE_NAMES:
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        files[rel] = {"sha256": sha256(path), "size_bytes": path.stat().st_size}
    manifest = {
        "task": "MF-END-24",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_root": str(ROOT).replace("\\", "/"),
        "file_count": len(files),
        "files": files,
    }
    (ROOT / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    hashes16 = {rel: sha256(WT / rel)[:16] for rel in SHIPPED if (WT / rel).is_file()}
    (ROOT / "hash16.json").write_text(json.dumps(hashes16, indent=2), encoding="utf-8")
    print(json.dumps({"manifest_files": len(files), "shipped_hashed": len(hashes16)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
