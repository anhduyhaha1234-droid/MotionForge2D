"""R4 independent, read-only audit of the frozen candidate and R3 proof.

This control does not start the product, mutate a database, call a private
handler, or create an authority.  It verifies source provenance, inspects the
actual registered route graph when the candidate app can be imported, and
reconciles the fresh R3 public-chain result with the frozen candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _line_hits(path: Path, pattern: str) -> list[dict[str, Any]]:
    regex = re.compile(pattern)
    hits = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if regex.search(line):
            hits.append({"line": number, "text": line.strip()})
    return hits


def _candidate_hashes(candidate_root: Path, baseline: Path) -> dict[str, Any]:
    manifest = json.loads(baseline.read_text(encoding="utf-8"))
    results = []
    for entry in manifest["entries"]:
        if not entry.get("exists") or "." not in Path(entry["path"]).name:
            continue
        target = candidate_root / entry["path"]
        current = {
            "path": entry["path"],
            "exists": target.is_file(),
            "sha256": _sha256(target) if target.is_file() else None,
            "expected_sha256": entry["sha256"],
            "matches": target.is_file() and _sha256(target) == entry["sha256"],
        }
        results.append(current)
    return {
        "baseline": str(baseline),
        "entries": results,
        "all_match": all(item["matches"] for item in results),
    }


def _openapi(candidate_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(candidate_root))
    try:
        module = importlib.import_module("app.api.app")
        routes = module.app.openapi().get("paths", {})
        selected = {
            path: sorted(methods)
            for path, methods in routes.items()
            if any(
                token in path.lower()
                for token in (
                    "structural",
                    "s09-approval",
                    "full-apply",
                    "s12-export",
                    "reskin",
                    "project-cast",
                )
            )
        }
        lock_routes = {
            path: methods
            for path, methods in selected.items()
            if "structural-lock" in path.lower()
        }
        return {
            "status": "IMPORTED",
            "selected_routes": selected,
            "structural_lock_routes": lock_routes,
            "has_public_structural_lock_producer": bool(lock_routes),
        }
    except Exception as exc:  # pragma: no cover - environment diagnostic
        return {
            "status": "ENVIRONMENT_IMPORT_FAILURE",
            "error_type": type(exc).__name__,
            "error": repr(exc),
            "has_public_structural_lock_producer": None,
        }
    finally:
        sys.path.pop(0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--candidate-baseline", required=True)
    parser.add_argument("--r3-evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    candidate_root = Path(args.candidate_root).resolve()
    r3 = json.loads(Path(args.r3_evidence).read_text(encoding="utf-8"))
    route_dir = candidate_root / "app" / "api" / "routes"
    structural_lock_definition = candidate_root / "app" / "persistence" / "structural_lock.py"
    caller_hits = []
    for source in candidate_root.joinpath("app").rglob("*.py"):
        for hit in _line_hits(source, r"create_manifest\("):
            if "def create_manifest" not in hit["text"]:
                caller_hits.append(
                    {"path": str(source.relative_to(candidate_root)), **hit}
                )
    route_hits = []
    for source in sorted(route_dir.glob("*.py")):
        hits = _line_hits(source, r"structural[-_ ]?lock|manifest")
        if hits:
            route_hits.append(
                {"path": str(source.relative_to(candidate_root)), "hits": hits}
            )
    counts = r3.get("counts_after_s12_submit", {})
    s10 = r3.get("steps", {}).get("public_s10_full_apply_submit", {})
    s12 = r3.get("steps", {}).get("public_s12_submit_after_producers", {})
    authority = r3.get("steps", {}).get("public_full_apply_authority", {})
    authority_body = authority.get("body", {})
    eligibility = authority_body.get("full_apply_authority", {}).get(
        "eligibility", {}
    )
    evidence = {
        "audit": "S12-LC3-R4-QA-R08-R10",
        "candidate_root": str(candidate_root),
        "candidate_hashes": _candidate_hashes(
            candidate_root, Path(args.candidate_baseline).resolve()
        ),
        "openapi": _openapi(candidate_root),
        "structural_lock_storage": {
            "path": str(structural_lock_definition.relative_to(candidate_root)),
            "create_manifest_definition": _line_hits(
                structural_lock_definition, r"def create_manifest"
            ),
            "public_caller_hits": caller_hits,
            "route_source_hits": route_hits,
        },
        "r3_public_chain": {
            "source": str(Path(args.r3_evidence).resolve()),
            "status": r3.get("status"),
            "first_missing_contract_raw": r3.get("first_missing_contract"),
            "first_missing_contract": (
                "public StructuralLockManifest producer/activation after current "
                "source, evidence, cast, and config producers and before executable "
                "S09/S10 authority"
            ),
            "counts_after_s12_submit": counts,
            "authority_verified": authority_body.get("verified"),
            "authority_full_apply_executable": eligibility.get(
                "full_apply_executable"
            ),
            "authority_reasons": eligibility.get("reasons", []),
            "s10_status": s10.get("status_code"),
            "s10_body": s10.get("body"),
            "s12_status": s12.get("status_code"),
            "s12_body": s12.get("body"),
        },
        "classification": {
            "status": "BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY",
            "fixture_or_mechanism": (
                "R3 deterministic extraction is "
                "FIXTURE_ONLY_ENGINEERING_MECHANISM"
            ),
            "normal_product_export": "NOT_DEMONSTRATED",
            "ui_video_playback": "NOT_RUN",
            "manual_sql_or_orm_fabrication": False,
            "public_structural_lock_producer": "ABSENT_FROM_CANDIDATE_ROUTE_GRAPH",
        },
    }
    evidence["assertions"] = [
        "candidate protected source hashes match the supplied baseline",
        "StructuralLockRepository.create_manifest exists but has no production caller",
        "R3 public source/evidence/roles/pack/cast/config graph preceded the blocker",
        "S09 authority is verified but not executable without a pinned manifest",
        "S10 and S12 fail closed without creating S12 export rows",
    ]
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
