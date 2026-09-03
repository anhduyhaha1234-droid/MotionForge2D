"""S11 QC checks package (T03A — W5).

Freeze point for the threshold policy: ``thresholds`` owns the single
production policy path (versioned + content-hashed), ``runner`` provides
the common bounded execution harness (``_run_bounded`` pattern), and
``registry`` provides the detector registration contract that W6
detector tasks (T03B/C/D/E) will use.

Ownership boundaries:
- thresholds.py  — T03A OWNER (policy path production; freeze)
- runner.py     — T03A OWNER (bounded harness common)
- registry.py   — T03A OWNER (detector registry contract)
- detector modules (T03B/C/D/E) and the orchestrator (T03F) are FORBIDDEN
  here — they consume this package read-only.
"""

from __future__ import annotations

from app.services.qc_checks.registry import (
    QC_REGISTRY_CONFLICT,
    QC_REGISTRY_INVALID_ARGS,
    QC_REGISTRY_UNKNOWN,
    DetectorRegistry,
    DetectorSpec,
    QcRegistryError,
    get_detector,
    register_detector,
    registry,
    unregister_detector,
)
from app.services.qc_checks.runner import (
    QC_RUNNER_CANCELLED,
    QC_RUNNER_CHILD_ERROR,
    QC_RUNNER_DEADLINE_EXCEEDED,
    QC_RUNNER_INVALID_ARGS,
    QC_RUNNER_OK,
    QC_RUNNER_OUTPUT_CAP_EXCEEDED,
    DetectorRun,
    QcRunnerError,
    run_detector,
)
from app.services.qc_checks.thresholds import (
    CALIBRATION_REVISION,
    CODE_THRESHOLD_BLOCKER,
    CODE_THRESHOLD_INVALID,
    CODE_THRESHOLD_PASS,
    CODE_THRESHOLD_WARNING,
    POLICY_ID,
    SCHEMA_VERSION,
    STATUS_BLOCKER,
    STATUS_INVALID,
    STATUS_PASS,
    STATUS_WARNING,
    QC_THRESHOLD_CALIBRATION_INVALID,
    QC_THRESHOLD_CALIBRATION_MISSING,
    QC_THRESHOLD_UNKNOWN_METRIC,
    QcThresholdError,
    build_policy,
    classify,
    get_threshold,
    load_policy,
)

__all__ = [
    "CALIBRATION_REVISION",
    "CODE_THRESHOLD_BLOCKER",
    "CODE_THRESHOLD_INVALID",
    "CODE_THRESHOLD_PASS",
    "CODE_THRESHOLD_WARNING",
    "DetectorRegistry",
    "DetectorRun",
    "DetectorSpec",
    "POLICY_ID",
    "QC_REGISTRY_CONFLICT",
    "QC_REGISTRY_INVALID_ARGS",
    "QC_REGISTRY_UNKNOWN",
    "QC_RUNNER_CANCELLED",
    "QC_RUNNER_CHILD_ERROR",
    "QC_RUNNER_DEADLINE_EXCEEDED",
    "QC_RUNNER_INVALID_ARGS",
    "QC_RUNNER_OK",
    "QC_RUNNER_OUTPUT_CAP_EXCEEDED",
    "QC_THRESHOLD_CALIBRATION_INVALID",
    "QC_THRESHOLD_CALIBRATION_MISSING",
    "QC_THRESHOLD_UNKNOWN_METRIC",
    "QcRegistryError",
    "QcRunnerError",
    "QcThresholdError",
    "SCHEMA_VERSION",
    "STATUS_BLOCKER",
    "STATUS_INVALID",
    "STATUS_PASS",
    "STATUS_WARNING",
    "build_policy",
    "classify",
    "get_detector",
    "get_threshold",
    "load_policy",
    "register_detector",
    "registry",
    "run_detector",
    "unregister_detector",
]