"""MF-END-25 guard re-run (outside the worktree) — clean porcelain + preimage proof."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WT = Path(sys.argv[1])
EVID = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-25"
)

MODIFIED = [
    "frontend/src/lib/api.ts",
    "frontend/src/components/ImportAnalyzePanel.tsx",
    "frontend/src/app/(app)/projects/[id]/page.tsx",
    "frontend/src/app/(app)/apply/page.tsx",
    "frontend/src/app/(app)/export/page.tsx",
]
NEW = "tests/product_delivery/test_mf_end_25.py"

PREIMAGE_MARKERS = {
    "frontend/src/lib/api.ts": ["buildJourneyStages", "journeyNextStage", "JourneyStageView"],
    "frontend/src/components/ImportAnalyzePanel.tsx": ['data-testid="import-go-project"', 'e.key === "Enter"'],
    "frontend/src/app/(app)/projects/[id]/page.tsx": ["project-journey", "applyStage?.href"],
    "frontend/src/app/(app)/apply/page.tsx": ["apply-go-export", "buildExportHref"],
    "frontend/src/app/(app)/export/page.tsx": ["ExportScopePicker", "s12:export:lastScope"],
}


def _git(*args: str) -> bytes:
    out = subprocess.run(["git", *args], cwd=str(WT), capture_output=True, check=False)
    assert out.returncode == 0, f"git {' '.join(args)} rc={out.returncode}: {out.stderr[:200]}"
    return out.stdout


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(data: bytes) -> int:
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    head = _git("rev-parse", "HEAD").decode().strip()
    porcelain = [ln for ln in _git("status", "--porcelain").decode().splitlines() if ln.strip()]

    report: dict = {
        "head": head,
        "porcelain": porcelain,
        "write_set": {},
        "preimage": {},
        "protected_drift": [],
        "shrunk": [],
    }

    for rel in MODIFIED:
        before = _git("show", f"HEAD:{rel}")
        after = (WT / rel).read_bytes()
        row = {
            "before_sha256": _sha(before),
            "before_bytes": len(before),
            "before_lines": _lines(before),
            "after_sha256": _sha(after),
            "after_bytes": len(after),
            "after_lines": _lines(after),
            "changed": _sha(before) != _sha(after),
        }
        report["write_set"][rel] = row
        if row["after_lines"] < row["before_lines"]:
            report["shrunk"].append(rel)

    new_bytes = (WT / NEW).read_bytes()
    report["new_file"] = {
        "path": NEW,
        "bytes": len(new_bytes),
        "lines": _lines(new_bytes),
        "sha256": _sha(new_bytes),
    }

    for rel, markers in PREIMAGE_MARKERS.items():
        base_text = _git("show", f"HEAD:{rel}").decode("utf-8")
        now_text = (WT / rel).read_text(encoding="utf-8")
        report["preimage"][rel] = {
            "absent_at_base": {m: (m not in base_text) for m in markers},
            "present_in_worktree": {m: (m in now_text) for m in markers},
        }

    for ln in porcelain:
        path = ln[3:].strip()
        if path.startswith("tests/") and path != NEW:
            report["protected_drift"].append(path)

    expected = {f" M {rel}" for rel in MODIFIED} | {f"?? {NEW}"}
    report["porcelain_matches_allowlist"] = set(porcelain) == expected

    ok = (
        not report["shrunk"]
        and not report["protected_drift"]
        and report["porcelain_matches_allowlist"]
        and all(v["changed"] for v in report["write_set"].values())
        and all(
            all(row["absent_at_base"].values()) and all(row["present_in_worktree"].values())
            for row in report["preimage"].values()
        )
    )
    report["verdict"] = "CLEAN" if ok else "VIOLATION"

    out = EVID / "raw" / "write_set_guard.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "verdict": report["verdict"],
        "shrunk": report["shrunk"],
        "protected_drift": report["protected_drift"],
        "porcelain_matches_allowlist": report["porcelain_matches_allowlist"],
        "porcelain": len(porcelain),
    }))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
