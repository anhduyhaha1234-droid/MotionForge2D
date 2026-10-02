"""S11-T03A threshold policy v1 (W5) — FREEZE point for all QC policies.

Owner: T03A (single writer of the production policy path).  After this task
is MANAGER_VERIFIED every other task may only READ this policy; changing it
requires resuming this T03A session and re-running dependent gates
(Decision C — lane-A GAP-4/R2/R6: versioned thresholds prevent
tune-after-result).

Policy identity:
- ``policy_id`` = ``s11-qc-thresholds-v1``; ``content_hash`` = sha256 over
  the canonical JSON of the policy body (stable across every load/build —
  two loads produce byte-identical digests).

Derivation rule (C4-F4: threshold provenance cites the TRUE T06A2 builder /
manifest / measurement record — never fabricated numbers):
- every boundary is one RAW VALUE read from the frozen T06A2 calibration
  fixtures ``tests/fixtures/s11_qc/calibration/*.json``, which are produced
  by real measurements in ``tests/s11_qc_calibration_builders.py``
  (``CALIBRATION_REVISION == measurement_function_revision == 1.0.0``);
- increasing metrics: warning = level-2 raw value (first calibrated
  escalation), blocker = level-4 raw value (max calibrated defect);
- constant fact metrics (e.g. no_audio_source_fact): warning = blocker =
  the calibrated constant — any deviation breaks the invariant;
- sanity bounds: min = 0.0 (physical non-negativity: no negative
  px/frame/count/second/ratio/level), max = the maximum calibrated raw
  value (values beyond the measured envelope are uncalibrated ->
  invalid, fail-closed).

Classification (``classify``): sanity first (non-finite or outside the
envelope -> ``THRESHOLD_INVALID``), then increasing: ``>= blocker`` ->
``THRESHOLD_BLOCKER``, ``>= warning`` -> ``THRESHOLD_WARNING``, else
``THRESHOLD_PASS``; constant: deviation -> ``THRESHOLD_BLOCKER``.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

#: Frozen policy identity — v1 is the first FREEZE (W5).
POLICY_ID = "s11-qc-thresholds-v1"
SCHEMA_VERSION = 1

#: Revision of the T06A2 measurement functions that produced the raw
#: values.  Every calibration record must carry exactly this revision
#: (provenance pin — mismatch raises ``QC_THRESHOLD_CALIBRATION_INVALID``).
CALIBRATION_REVISION = "1.0.0"

#: Derivation rule anchors (documented in the policy body as well).
WARNING_LEVEL = 2
BLOCKER_LEVEL = 4

#: Physical floor for every calibrated metric (px / frame / count / second /
#: ratio / level are all non-negative quantities).
SANITY_MIN_VALUE = 0.0

#: Stable classification statuses and codes.
STATUS_PASS = "pass"
STATUS_WARNING = "warning"
STATUS_BLOCKER = "blocker"
STATUS_INVALID = "invalid"
CODE_THRESHOLD_PASS = "THRESHOLD_PASS"
CODE_THRESHOLD_WARNING = "THRESHOLD_WARNING"
CODE_THRESHOLD_BLOCKER = "THRESHOLD_BLOCKER"
CODE_THRESHOLD_INVALID = "THRESHOLD_INVALID"

#: Stable error codes.
QC_THRESHOLD_UNKNOWN_METRIC = "THRESHOLD_UNKNOWN_METRIC"
QC_THRESHOLD_CALIBRATION_MISSING = "THRESHOLD_CALIBRATION_MISSING"
QC_THRESHOLD_CALIBRATION_INVALID = "THRESHOLD_CALIBRATION_INVALID"


class QcThresholdError(Exception):
    """Policy violation carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


#: Project root = app/services/qc_checks/thresholds.py -> parents[3].
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Frozen T06A2 inputs consumed READ-ONLY (single source of raw values).
CALIBRATION_DIR = (
    _PROJECT_ROOT / "tests" / "fixtures" / "s11_qc" / "calibration"
)

_CALIBRATION_SOURCE_PREFIX = "tests/fixtures/s11_qc/calibration/"


def _load_calibration_records() -> list[dict[str, Any]]:
    """Load every metric record from the frozen calibration fixtures.

    Fail-closed: missing directory -> ``QC_THRESHOLD_CALIBRATION_MISSING``;
    unreadable/inconsistent records -> ``QC_THRESHOLD_CALIBRATION_INVALID``.
    """
    if not CALIBRATION_DIR.is_dir():
        raise QcThresholdError(
            QC_THRESHOLD_CALIBRATION_MISSING,
            f"calibration fixture directory missing: {CALIBRATION_DIR}",
        )
    fixtures = sorted(CALIBRATION_DIR.glob("*.json"))
    if not fixtures:
        raise QcThresholdError(
            QC_THRESHOLD_CALIBRATION_MISSING,
            f"no calibration fixtures under {CALIBRATION_DIR}",
        )
    records: list[dict[str, Any]] = []
    for path in fixtures:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise QcThresholdError(
                QC_THRESHOLD_CALIBRATION_INVALID,
                f"calibration fixture unreadable: {path.name}: {exc}",
            ) from exc
        fixture_records = doc.get("metrics")
        if not isinstance(fixture_records, list) or not fixture_records:
            raise QcThresholdError(
                QC_THRESHOLD_CALIBRATION_INVALID,
                f"calibration fixture has no metric records: {path.name}",
            )
        for record in fixture_records:
            if (
                record.get("measurement_function_revision")
                != CALIBRATION_REVISION
            ):
                raise QcThresholdError(
                    QC_THRESHOLD_CALIBRATION_INVALID,
                    f"{path.name}:{record.get('metric')} revision "
                    f"{record.get('measurement_function_revision')!r} != "
                    f"pinned {CALIBRATION_REVISION!r}",
                )
            records.append({"fixture": path.name, "record": record})
    return records


def _derive_entry(fixture: str, record: dict[str, Any]) -> dict[str, Any]:
    """Derive ONE threshold entry from a calibration record (no invented
    numbers — every boundary is a raw value at a cited level)."""
    metric = record["metric"]
    monotonic = record.get("monotonic")
    levels = {
        lv["level"]: lv["raw_value"]
        for lv in record.get("perturbation_levels", [])
    }
    if monotonic not in ("increasing", "constant") or not levels:
        raise QcThresholdError(
            QC_THRESHOLD_CALIBRATION_INVALID,
            f"{fixture}:metric={metric} malformed monotonic/levels",
        )
    if monotonic == "increasing":
        for level in (WARNING_LEVEL, BLOCKER_LEVEL):
            if level not in levels:
                raise QcThresholdError(
                    QC_THRESHOLD_CALIBRATION_INVALID,
                    f"{fixture}:metric={metric} missing level {level}",
                )
        warning = levels[WARNING_LEVEL]
        blocker = levels[BLOCKER_LEVEL]
        warn_level = WARNING_LEVEL
        blk_level = BLOCKER_LEVEL
    else:
        calibrated = levels[1]
        if any(value != calibrated for value in levels.values()):
            raise QcThresholdError(
                QC_THRESHOLD_CALIBRATION_INVALID,
                f"{fixture}:metric={metric} declared constant but levels "
                f"differ: {sorted(levels.values())}",
            )
        warning = blocker = calibrated
        warn_level = 1
        blk_level = 1
    if not math.isfinite(warning) or not math.isfinite(blocker):
        raise QcThresholdError(
            QC_THRESHOLD_CALIBRATION_INVALID,
            f"{fixture}:metric={metric} non-finite boundary",
        )
    entry: dict[str, Any] = {
        "metric": metric,
        "unit": record.get("unit", ""),
        "kind": monotonic,
        "warning_boundary": warning,
        "blocker_boundary": blocker,
        "sanity_bounds": {"min": SANITY_MIN_VALUE, "max": blocker},
        "provenance": {
            "fixture": fixture,
            "metric_record": f"{fixture}:metrics[metric={metric}]",
            "measurement_function_revision": CALIBRATION_REVISION,
            "deterministic_seed": record.get("deterministic_seed"),
            "source_reference": record.get("source_reference"),
            "result_reference": record.get("result_reference"),
            "monotonic": monotonic,
            "warning_boundary_source": (
                f"{_CALIBRATION_SOURCE_PREFIX}{fixture}"
                f":metric={metric}:level={warn_level}:raw_value"
            ),
            "blocker_boundary_source": (
                f"{_CALIBRATION_SOURCE_PREFIX}{fixture}"
                f":metric={metric}:level={blk_level}:raw_value"
            ),
            "sanity_min_rule": (
                "physical non-negativity: px/frame/count/second/ratio/level "
                "cannot be negative"
            ),
            "sanity_max_source": (
                f"{_CALIBRATION_SOURCE_PREFIX}{fixture}"
                f":metric={metric}:level={blk_level}:raw_value "
                f"(max calibrated envelope)"
            ),
        },
    }
    return entry


def build_policy() -> dict[str, Any]:
    """Derive the full v1 policy fresh from the frozen calibration inputs.

    Deterministic: two calls produce identical dicts and identical
    ``content_hash`` digests (test-enforced).  Not cached on purpose —
    ``load_policy`` is the cached view.
    """
    records = _load_calibration_records()
    thresholds: dict[str, Any] = {}
    sources: set[str] = set()
    for item in records:
        fixture = item["fixture"]
        record = item["record"]
        entry = _derive_entry(fixture, record)
        thresholds[record["metric"]] = entry
        sources.add(f"{_CALIBRATION_SOURCE_PREFIX}{fixture}")
    if not thresholds:
        raise QcThresholdError(
            QC_THRESHOLD_CALIBRATION_INVALID,
            "calibration fixtures yielded no thresholds",
        )
    body: dict[str, Any] = {
        "policy_id": POLICY_ID,
        "schema_version": SCHEMA_VERSION,
        "derivation_rule": (
            "increasing: warning=level-2 raw_value, blocker=level-4 "
            "(max calibrated) raw_value, sanity=[0, max calibrated]; "
            "constant: warning=blocker=calibrated constant, sanity="
            "[0, calibrated constant]; sanity min=0.0 physical "
            "non-negativity; every boundary is a raw_value cited in "
            "provenance from tests/fixtures/s11_qc/calibration/*.json "
            "(T06A2, builder tests/s11_qc_calibration_builders.py "
            "revision 1.0.0)"
        ),
        "calibration_revision": CALIBRATION_REVISION,
        "calibration_sources": sorted(sources),
        "thresholds": dict(sorted(thresholds.items())),
    }
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {**body, "content_hash": digest}


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    """Cached view of ``build_policy`` — same content, same hash every call."""
    return build_policy()


def get_threshold(metric: str) -> dict[str, Any]:
    """Return one threshold entry; unknown metric -> stable error."""
    entry = load_policy()["thresholds"].get(metric)
    if entry is None:
        raise QcThresholdError(
            QC_THRESHOLD_UNKNOWN_METRIC, f"unknown metric: {metric!r}"
        )
    # load_policy is lru_cache-wrapped -> mypy sees Any from the wrapper.
    # The entry is a dict by policy schema after the None check — cast
    # here instead of relaxing the return annotation.
    return cast(dict[str, Any], entry)


def classify(metric: str, value: float) -> tuple[str, str]:
    """Classify a measured *value* against the frozen v1 policy.

    Returns ``(status, code)`` with stable string values.  Fail-closed:
    non-finite values and anything outside the calibrated envelope are
    ``THRESHOLD_INVALID`` before any threshold comparison.
    """
    entry = get_threshold(metric)
    sanity = entry["sanity_bounds"]
    if (
        not math.isfinite(value)
        or value < sanity["min"]
        or value > sanity["max"]
    ):
        return STATUS_INVALID, CODE_THRESHOLD_INVALID
    if entry["kind"] == "constant":
        if value != entry["blocker_boundary"]:
            return STATUS_BLOCKER, CODE_THRESHOLD_BLOCKER
        return STATUS_PASS, CODE_THRESHOLD_PASS
    if value >= entry["blocker_boundary"]:
        return STATUS_BLOCKER, CODE_THRESHOLD_BLOCKER
    if value >= entry["warning_boundary"]:
        return STATUS_WARNING, CODE_THRESHOLD_WARNING
    return STATUS_PASS, CODE_THRESHOLD_PASS