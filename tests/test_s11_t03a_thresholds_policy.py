"""S11-T03A threshold policy v1 tests (W5).

Covers the T03A policy contract:
- versioned policy identity (policy_id + content_hash) stable across loads;
- every threshold entry carries the 5 required attributes
  (unit / warning boundary / blocker boundary / provenance / sanity bounds);
- boundaries are DERIVED from the frozen T06A2 calibration fixtures —
  this test recomputes them independently from the raw JSON records and
  asserts zero drift;
- the golden fixture tests/fixtures/s11_golden/qc_thresholds.json matches
  the code-derived policy 100 %;
- sanity bounds reject irrational values (negative / beyond calibrated
  envelope / NaN / inf);
- classify() returns stable status codes; unknown metric -> stable error.

Isolation: short Windows-native basetemp via the session fixture in
conftest_isolate; -p no:cacheprovider; env strips MOTIONFORGE_DATABASE_URL
(see LOG.md).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.qc_checks import (
    CODE_THRESHOLD_BLOCKER,
    CODE_THRESHOLD_INVALID,
    CODE_THRESHOLD_PASS,
    CODE_THRESHOLD_WARNING,
    POLICY_ID,
    QC_THRESHOLD_UNKNOWN_METRIC,
    QcThresholdError,
    STATUS_BLOCKER,
    STATUS_INVALID,
    STATUS_PASS,
    STATUS_WARNING,
    build_policy,
    classify,
    get_threshold,
    load_policy,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CALIBRATION_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "s11_qc" / "calibration"
_GOLDEN = _PROJECT_ROOT / "tests" / "fixtures" / "s11_golden" / "qc_thresholds.json"
_BUILDERS = _PROJECT_ROOT / "tests" / "s11_qc_calibration_builders.py"

_REQUIRED_ATTRIBUTES = (
    "unit",
    "warning_boundary",
    "blocker_boundary",
    "provenance",
    "sanity_bounds",
)


def _load_calibration_metrics() -> dict[str, dict]:
    """Independently read every calibration fixture (frozen T06A2 inputs)."""
    metrics: dict[str, dict] = {}
    for fixture_path in sorted(_CALIBRATION_DIR.glob("*.json")):
        doc = json.loads(fixture_path.read_text(encoding="utf-8"))
        for record in doc["metrics"]:
            metrics[record["metric"]] = {
                "fixture": fixture_path.name,
                "record": record,
            }
    return metrics


def test_policy_has_versioned_identity() -> None:
    policy = build_policy()
    assert policy["policy_id"] == POLICY_ID == "s11-qc-thresholds-v1"
    assert policy["schema_version"] == 1
    digest = policy["content_hash"]
    assert isinstance(digest, str) and len(digest) == 64
    int(digest, 16)  # hex — raises ValueError if not


def test_content_hash_stable_across_two_loads_and_builds() -> None:
    p1, p2 = build_policy(), build_policy()
    assert p1["content_hash"] == p2["content_hash"]
    l1, l2 = load_policy(), load_policy()
    assert l1 == l2
    assert l1["content_hash"] == p1["content_hash"]


def test_golden_fixture_matches_code_one_hundred_percent() -> None:
    assert _GOLDEN.is_file(), f"golden fixture missing: {_GOLDEN}"
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert golden == load_policy(), (
        "golden fixture drifted from code-derived policy"
    )


def test_every_threshold_has_all_five_attributes() -> None:
    policy = load_policy()
    thresholds = policy["thresholds"]
    assert thresholds, "policy has no thresholds"
    for metric, entry in thresholds.items():
        for attr in _REQUIRED_ATTRIBUTES:
            assert attr in entry, f"{metric} missing attribute {attr!r}"
        sanity = entry["sanity_bounds"]
        assert set(sanity) == {"min", "max"}
        assert sanity["min"] <= sanity["max"], f"{metric} sanity min>max"
        assert entry["warning_boundary"] >= 0
        assert entry["blocker_boundary"] >= 0
        # every threshold must have a warning AND blocker boundary value
        assert entry["warning_boundary"] <= entry["blocker_boundary"], (
            f"{metric}: warning {entry['warning_boundary']} > "
            f"blocker {entry['blocker_boundary']}"
        )


def test_policy_covers_all_calibration_metrics() -> None:
    calibration = _load_calibration_metrics()
    policy_metrics = set(load_policy()["thresholds"])
    assert policy_metrics == set(calibration), (
        f"policy metrics {sorted(policy_metrics)} != "
        f"calibration metrics {sorted(calibration)}"
    )


def test_boundaries_derived_from_calibration_raw_values() -> None:
    """Every boundary must equal a raw_value at a cited level — recomputed
    independently from the frozen calibration JSONs (zero drift, zero
    arbitrary numbers)."""
    policy = load_policy()
    for metric, info in _load_calibration_metrics().items():
        record = info["record"]
        levels = {lv["level"]: lv["raw_value"] for lv in record["perturbation_levels"]}
        entry = policy["thresholds"][metric]
        monotonic = record["monotonic"]
        if monotonic == "constant":
            calibrated = levels[1]
            assert entry["warning_boundary"] == calibrated
            assert entry["blocker_boundary"] == calibrated
            assert entry["sanity_bounds"]["max"] == calibrated
        else:
            assert record["monotonic"] == "increasing"
            assert entry["warning_boundary"] == levels[2], (
                f"{metric}: warning must be calibration level-2 raw value"
            )
            assert entry["blocker_boundary"] == levels[4], (
                f"{metric}: blocker must be level-4 (max calibrated) raw value"
            )
            assert entry["sanity_bounds"]["max"] == levels[4]
        assert entry["sanity_bounds"]["min"] == 0.0


def test_provenance_citations_resolve_to_real_t06a2_records() -> None:
    policy = load_policy()
    calibration = _load_calibration_metrics()
    for metric, entry in policy["thresholds"].items():
        prov = entry["provenance"]
        info = calibration[metric]
        # fixture file really exists and matches the metric's fixture
        assert prov["fixture"] == info["fixture"]
        assert (_CALIBRATION_DIR / prov["fixture"]).is_file()
        # builder/measurement references resolve into the real module
        import s11_qc_calibration_builders  # tests dir is on sys.path

        for ref in (prov["source_reference"], prov["result_reference"]):
            fn_name = ref.split(":")[-1]
            fn = getattr(s11_qc_calibration_builders, fn_name, None)
            assert callable(fn), f"provenance reference does not resolve: {ref}"
        # revision matches the frozen measurement-function revision
        record = info["record"]
        assert (
            prov["measurement_function_revision"]
            == record["measurement_function_revision"]
            == "1.0.0"
        )
        assert prov["deterministic_seed"] == record["deterministic_seed"]
        # boundary sources cite file+metric+level exactly
        monotonic = record["monotonic"]
        warn_level = 1 if monotonic == "constant" else 2
        blk_level = 1 if monotonic == "constant" else 4
        assert prov["warning_boundary_source"].startswith(
            f"tests/fixtures/s11_qc/calibration/{info['fixture']}"
        )
        assert f":metric={metric}" in prov["warning_boundary_source"]
        assert f":level={warn_level}" in prov["warning_boundary_source"]
        assert f":metric={metric}" in prov["blocker_boundary_source"]
        assert f":level={blk_level}" in prov["blocker_boundary_source"]


def test_sanity_bounds_reject_irrational_values() -> None:
    for metric, entry in load_policy()["thresholds"].items():
        sanity = entry["sanity_bounds"]
        # negative is physically impossible for every calibrated metric
        assert classify(metric, -1.0)[0] == STATUS_INVALID
        # beyond the calibrated envelope -> invalid (fail-closed)
        assert classify(metric, sanity["max"] + 1.0)[0] == STATUS_INVALID
        # non-finite values can never pass comparisons
        assert classify(metric, math.nan)[0] == STATUS_INVALID
        assert classify(metric, math.inf)[0] == STATUS_INVALID
        # exact envelope edges are still valid measurements
        assert classify(metric, sanity["min"])[0] != STATUS_INVALID


def test_classify_threshold_statuses_from_calibration_levels() -> None:
    """L1 raw -> PASS, L2 raw -> WARNING, L3 raw -> WARNING, L4 raw ->
    BLOCKER for every increasing metric; constant metric deviates -> the
    fact is broken (blocker/INVALID path, never PASS)."""
    for metric, info in _load_calibration_metrics().items():
        record = info["record"]
        levels = {lv["level"]: lv["raw_value"] for lv in record["perturbation_levels"]}
        if record["monotonic"] == "constant":
            assert classify(metric, levels[1])[0] == STATUS_PASS
            broken = classify(metric, levels[1] + 1)
            assert broken[0] in (STATUS_BLOCKER, STATUS_INVALID)
            assert broken[1].startswith("THRESHOLD_")
            continue
        status_l1, _ = classify(metric, levels[1])
        status_l2, code_l2 = classify(metric, levels[2])
        status_l3, _ = classify(metric, levels[3])
        status_l4, code_l4 = classify(metric, levels[4])
        assert status_l1 == STATUS_PASS
        assert status_l2 == STATUS_WARNING and code_l2 == CODE_THRESHOLD_WARNING
        assert status_l3 == STATUS_WARNING
        assert status_l4 == STATUS_BLOCKER and code_l4 == CODE_THRESHOLD_BLOCKER


def test_classify_pass_code_is_stable() -> None:
    for metric, info in _load_calibration_metrics().items():
        record = info["record"]
        level1 = record["perturbation_levels"][0]["raw_value"]
        status, code = classify(metric, level1)
        if record["monotonic"] != "constant" or level1 == 0:
            if status == STATUS_PASS:
                assert code == CODE_THRESHOLD_PASS
            else:
                assert code in (
                    CODE_THRESHOLD_WARNING,
                    CODE_THRESHOLD_BLOCKER,
                    CODE_THRESHOLD_INVALID,
                )


def test_unknown_metric_raises_stable_error() -> None:
    with pytest.raises(QcThresholdError) as exc_info:
        get_threshold("no_such_metric")
    assert exc_info.value.code == QC_THRESHOLD_UNKNOWN_METRIC
    with pytest.raises(QcThresholdError) as exc_info:
        classify("no_such_metric", 1.0)
    assert exc_info.value.code == QC_THRESHOLD_UNKNOWN_METRIC


def test_load_policy_marks_unknown_metrics_only() -> None:
    """get_threshold succeeds for every known metric (no false unknown)."""
    for metric in load_policy()["thresholds"]:
        entry = get_threshold(metric)
        assert entry["metric"] == metric