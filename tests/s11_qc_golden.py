"""S11-T06B — golden expected-outcome manifest helper (W9, own write-set).

Reads the committed golden manifests under
``tests/fixtures/s11_qc/golden_manifests/`` — the frozen expected-outcome
truth for T06C dynamic assertions.  Each manifest:

- references the frozen T03A threshold policy ONLY by id/hash
  (``policy_ref``) — it carries NO threshold boundary values;
- references T06A1 fixture builders by NAME (``consumes.media``) instead of
  inlining media parameters;
- declares expected QCItems (reason_code / severity / status-at-create),
  expected readiness verdicts before/after (T03G ``check_run_readiness``
  semantics), and — for rerun scenarios — the expected rerun scope.

Ownership boundaries (S11-T02..T06 production plan, W9):
- ``tests/fixtures/s11_golden/qc_thresholds.json`` is READ-ONLY (T03A owns
  it); this module only reads policy_id/content_hash for staleness checks.
- T06A1 fixture builders / T06A2 calibration / T03F orchestrator / T03G read
  authority are consumed by NAME — never copied or edited here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Committed golden manifest directory (T06B-owned write-set).
GOLDEN_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "s11_qc" / "golden_manifests"
)

#: Frozen T03A threshold policy fixture — READ-ONLY consumption.
POLICY_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "s11_golden" / "qc_thresholds.json"
)

#: Canonical manifest order — T06C iterates exactly this once
#: (lane-C E2E_SCENARIOS + lane-A GAP-7 scenario matrix freeze).
GOLDEN_MANIFESTS: tuple[str, ...] = (
    "scenario_d_targeted_rerun",
    "e2e_01_vertical_review",
    "e2e_02_blocker_readiness",
    "e2e_03_queue_states",
    "e2e_04_a11y_mobile",
)

#: Readiness verdict statuses of the T03G read authority (Decision F
#: consumption point, fail-closed).  Mirrors app/persistence/qc_check_runs.py.
READINESS_STATUSES: tuple[str, ...] = ("not_run", "ready", "blocked")

#: Run states of the T03G read authority.
READINESS_RUN_STATES: tuple[str, ...] = (
    "never_run",
    "queued",
    "failed",
    "completed",
    "stale",
)

#: Keys a T06A1 media reference may carry — anything else would be inlined
#: media parameters (forbidden by W9: reference by name, never duplicate).
_MEDIA_REF_KEYS: frozenset[str] = frozenset({"scenario", "builder", "manifest"})


def load_manifest(manifest_id: str) -> dict[str, Any]:
    """Load one golden manifest dict (raises FileNotFoundError when stale/missing)."""
    path = GOLDEN_DIR / f"{manifest_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def iter_manifests() -> list[dict[str, Any]]:
    """All golden manifests, in canonical order (GOLDEN_MANIFESTS)."""
    return [load_manifest(manifest_id) for manifest_id in GOLDEN_MANIFESTS]


def load_policy() -> dict[str, Any]:
    """Frozen T03A policy doc (read-only; never mutated)."""
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def policy_boundary_numbers() -> set[float]:
    """Every numeric threshold boundary in the frozen policy.

    Returns warning_boundary / blocker_boundary / sanity_bounds.min/max for
    EVERY metric — the exact set the W9 binary scan forbids in manifests
    (derived from the policy itself, never hardcoded here).
    """
    policy = load_policy()
    boundaries: set[float] = set()
    for metric, entry in policy["thresholds"].items():
        boundaries.add(float(entry["warning_boundary"]))
        boundaries.add(float(entry["blocker_boundary"]))
        sanity = entry["sanity_bounds"]
        boundaries.add(float(sanity["min"]))
        boundaries.add(float(sanity["max"]))
    return boundaries


def collect_numbers(doc: Any) -> list[float]:
    """All JSON numeric literals in a manifest, as floats (recursive walk)."""
    found: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            found.append(float(node))

    walk(doc)
    return found


def policy_ref_matches(manifest: dict[str, Any]) -> tuple[bool, str]:
    """True when the manifest's policy_ref equals the frozen T03A policy."""
    policy = load_policy()
    ref = manifest.get("policy_ref", {})
    if ref.get("policy_id") != policy.get("policy_id"):
        return False, (
            f"policy_id mismatch: manifest={ref.get('policy_id')!r} "
            f"policy={policy.get('policy_id')!r}"
        )
    if ref.get("policy_content_hash") != policy.get("content_hash"):
        return False, (
            "policy_content_hash mismatch: manifest="
            f"{ref.get('policy_content_hash')!r} policy={policy.get('content_hash')!r}"
        )
    return True, ""


def _readiness_errors(readiness: Any, label: str) -> list[str]:
    """Validate one expected-readiness verdict block (T03G semantics)."""
    errors: list[str] = []
    if not isinstance(readiness, dict):
        return [f"expected_readiness.{label}: must be an object"]
    status = readiness.get("status")
    if status not in READINESS_STATUSES:
        errors.append(
            f"expected_readiness.{label}.status: {status!r} not in "
            f"{READINESS_STATUSES}"
        )
    run_state = readiness.get("run_state")
    if run_state not in READINESS_RUN_STATES:
        errors.append(
            f"expected_readiness.{label}.run_state: {run_state!r} not in "
            f"{READINESS_RUN_STATES}"
        )
    blockers = readiness.get("expected_blocker_codes")
    if blockers is not None and not isinstance(blockers, list):
        errors.append(
            f"expected_readiness.{label}.expected_blocker_codes: must be a list"
        )
    return errors


def schema_violations(manifest: dict[str, Any]) -> list[str]:
    """Schema validation for one golden manifest — non-empty means INVALID.

    Mirrors the W9 test contract: scenario -> expected items per
    reason_code/severity/status, policy ref, consumes-by-name.
    """
    errors: list[str] = []

    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    if manifest.get("schema_version") != 1:
        errors.append(f"schema_version: {manifest.get('schema_version')!r} != 1")
    manifest_id = manifest.get("manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id:
        errors.append("manifest_id: missing/empty")

    # policy_ref — the ONLY policy data a manifest may carry.
    ref = manifest.get("policy_ref")
    if not isinstance(ref, dict):
        errors.append("policy_ref: missing/not an object")
    else:
        if not isinstance(ref.get("policy_id"), str) or not ref["policy_id"]:
            errors.append("policy_ref.policy_id: missing/empty")
        digest = ref.get("policy_content_hash")
        if not isinstance(digest, str) or len(digest) != 64:
            errors.append("policy_ref.policy_content_hash: must be a 64-char hex string")
        else:
            try:
                int(digest, 16)
            except ValueError:
                errors.append("policy_ref.policy_content_hash: not hex")
        if not isinstance(ref.get("policy_source"), str) or not ref["policy_source"]:
            errors.append("policy_ref.policy_source: missing/empty")

    # consumes — references by NAME only (T06A1 builders, T03F, T03G).
    consumes = manifest.get("consumes")
    if not isinstance(consumes, dict) or not consumes:
        errors.append("consumes: missing/empty object")
    else:
        media = consumes.get("media")
        if not isinstance(media, list) or not media:
            errors.append("consumes.media: missing/non-empty list required")
        else:
            for idx, entry in enumerate(media):
                if not isinstance(entry, dict):
                    errors.append(f"consumes.media[{idx}]: not an object")
                    continue
                if set(entry) != _MEDIA_REF_KEYS:
                    errors.append(
                        f"consumes.media[{idx}]: keys {sorted(entry)} — must be "
                        f"exactly {sorted(_MEDIA_REF_KEYS)} (reference by name, "
                        "never inline media params)"
                    )
                for key in ("scenario", "builder", "manifest"):
                    if not isinstance(entry.get(key), str) or not entry[key]:
                        errors.append(f"consumes.media[{idx}].{key}: missing/empty")
        seed_refs = consumes.get("seed")
        if not isinstance(seed_refs, list) or not seed_refs:
            errors.append("consumes.seed: missing/non-empty list required")
        elif not all(
            isinstance(seed_ref, str) and seed_ref for seed_ref in seed_refs
        ):
            errors.append("consumes.seed: every entry must be a non-empty string")
        for key in ("orchestrator", "read_authority"):
            entry = consumes.get(key)
            if not isinstance(entry, dict):
                errors.append(f"consumes.{key}: missing/not an object")
            elif not (
                isinstance(entry.get("module"), str)
                and isinstance(entry.get("entry"), str)
            ):
                errors.append(
                    f"consumes.{key}: must carry string 'module' and 'entry'"
                )

    # expected_qc_items — reason_code/severity/status-at-create per item.
    items = manifest.get("expected_qc_items")
    if not isinstance(items, list) or not items:
        errors.append("expected_qc_items: missing/non-empty list required")
    else:
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"expected_qc_items[{idx}]: not an object")
                continue
            reason_code = item.get("reason_code")
            if not isinstance(reason_code, str) or not reason_code:
                errors.append(f"expected_qc_items[{idx}].reason_code: missing/empty")
            count = item.get("expected_count")
            if not isinstance(count, int) or count < 1:
                errors.append(
                    f"expected_qc_items[{idx}].expected_count: must be an int >= 1"
                )

    # expected_readiness — before/after (+ optional extra verdict blocks).
    readiness = manifest.get("expected_readiness")
    if not isinstance(readiness, dict):
        errors.append("expected_readiness: missing/not an object")
    else:
        for label in ("before", "after"):
            if label not in readiness:
                errors.append(f"expected_readiness.{label}: missing")
            else:
                errors.extend(_readiness_errors(readiness[label], label))

    return errors


def validate_all() -> list[str]:
    """Aggregate schema violations across every golden manifest (GREEN gate)."""
    all_errors: list[str] = []
    for manifest_id in GOLDEN_MANIFESTS:
        try:
            manifest = load_manifest(manifest_id)
        except FileNotFoundError:
            all_errors.append(f"{manifest_id}: manifest file missing")
            continue
        for error in schema_violations(manifest):
            all_errors.append(f"{manifest_id}: {error}")
    return all_errors