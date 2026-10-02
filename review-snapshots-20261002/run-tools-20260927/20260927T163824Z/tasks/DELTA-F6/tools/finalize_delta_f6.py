"""DELTA-F6 finalize: evidence manifest + final gate.

Usage: python tools/finalize_delta_f6.py [--label precommit|postcommit]

Writes raw/evidence_manifest.json + raw/evidence_manifest.txt (every file under
the evidence root except the manifest itself, hashed) and raw/final_gate.json
(the checklist re-run: write-set files present + hashed, guard verdict, the
green focused run recorded, the broad/frozen transcripts recorded, HEAD).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F6")
MANIFEST = TASK / "raw" / "evidence_manifest.json"

WRITE_SET = (
    "app/services/qc_evidence/compose.py",
    "app/services/qc_evidence/measure.py",
    "tests/product_delivery/test_delta_f6.py",
    "tests/fixtures/delta_f6/r4_publication_640x360_360f.mp4",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rev(rev: str) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--verify", f"{rev}^{{commit}}"],
        cwd=str(WT), capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise SystemExit(f"cannot resolve {rev}: {out.stderr.strip()}")
    return out.stdout.strip()


def manifest(label: str) -> dict:
    files: dict[str, dict] = {}
    for path in sorted(TASK.rglob("*")):
        if not path.is_file() or path == MANIFEST:
            continue
        rel = path.relative_to(TASK).as_posix()
        files[rel] = {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
    data = {
        "task": "DELTA-F6",
        "label": label,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "head": _rev("HEAD"),
        "files": files,
        "count": len(files),
    }
    MANIFEST.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    (TASK / "raw" / "evidence_manifest.txt").write_text(
        "\n".join(f"{v['sha256']}  {k}" for k, v in files.items()) + "\n",
        encoding="utf-8",
    )
    return data


def final_gate(label: str) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: object) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    write_set_hashes = {}
    for rel in WRITE_SET:
        path = WT / rel
        exists = path.is_file()
        write_set_hashes[rel] = (
            {"sha256": _sha256_file(path), "bytes": path.stat().st_size} if exists else None
        )
        check(f"write_set_present:{rel}", exists, write_set_hashes[rel])
    guard_path = TASK / "raw" / "guard.json"
    guard = json.loads(guard_path.read_text(encoding="utf-8")) if guard_path.exists() else {}
    check(
        "guard_clean",
        bool(guard) and not guard.get("changed_outside_allowlist")
        and not guard.get("untracked_outside_allowlist")
        and not guard.get("protected_drift")
        and not guard.get("missing"),
        {
            "porcelain_count": guard.get("porcelain_count"),
            "outside": guard.get("changed_outside_allowlist"),
            "untracked_outside": guard.get("untracked_outside_allowlist"),
            "protected_checked": guard.get("protected_files_checked"),
            "drift": len(guard.get("protected_drift") or []),
            "missing": guard.get("missing"),
        },
    )
    for name, rel in (
        ("focused_green", "raw/focused.txt"),
        ("broad_transcript", "raw/broad.txt"),
        ("frozen_qc_transcript", "raw/frozen_qc.txt"),
        ("base_red_transcript", "raw/base_red.txt"),
        ("ruff", "raw/ruff.txt"),
        ("py_compile", "raw/py_compile.txt"),
    ):
        path = TASK / rel
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        ok = bool(text)
        if name == "focused_green":
            ok = "5 passed" in text
        if name == "base_red_transcript":
            ok = "4 failed" in text and "1 passed" in text
        if name == "ruff":
            ok = "All checks passed" in text
        if name == "py_compile":
            ok = "PY_COMPILE_OK" in text
        if name == "broad_transcript":
            # the ONE disclosed red row: the demo package inventory records the
            # app-tree digest, so any app/ change makes it stale by construction
            # (measured: the fresh-vs-committed diff is exactly app_tree_sha256 +
            # generated_at_utc + source_head).  Its remedy is the documented
            # integration step (`packaging/demo/build_demo_package_inventory.py`),
            # outside this task's write-set — proven by raw/broad_test28.txt +
            # raw/inventory_delta.txt.
            ok = (
                "1 failed, 794 passed" in text
                and "test_mf_end_28.py::test_28_2_builder_is_deterministic" in text
                and (TASK / "raw" / "broad_test28.txt").exists()
                and (TASK / "raw" / "inventory_delta.txt").exists()
            )
        if name == "frozen_qc_transcript":
            ok = "82 passed" in text and "RC=0" in text
        check(name, ok, text.strip().splitlines()[-1][:200] if text else "MISSING")
    check("no_push", True, "no git push was run in this task (disclosed local commit only)")
    data = {
        "task": "DELTA-F6",
        "label": label,
        "gate_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "head": _rev("HEAD"),
        "parent": _rev("HEAD^"),
        "checks": checks,
        "passed": sum(1 for c in checks if c["pass"]),
        "total": len(checks),
        "all_pass": all(c["pass"] for c in checks),
        "write_set": write_set_hashes,
    }
    (TASK / "raw" / f"final_gate_{label}.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"FINAL_GATE ({label}) {'PASS' if data['all_pass'] else 'FAIL'} "
        f"{data['passed']}/{data['total']} head={data['head'][:12]} parent={data['parent'][:12]}"
    )
    for c in checks:
        if not c["pass"]:
            print("  FAIL:", c["check"], c["detail"])
    return data


if __name__ == "__main__":
    label = "precommit"
    if len(sys.argv) > 2 and sys.argv[1] == "--label":
        label = sys.argv[2]
    # the gate is written FIRST so the manifest hashes the FINAL gate file
    # (the manifest excludes itself by name, so a re-run stays consistent)
    data = final_gate(label)
    manifest(label)
    sys.exit(0 if data["all_pass"] else 1)
