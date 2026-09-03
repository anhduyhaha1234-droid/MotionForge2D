"""S11-T03E (W6): av_sync_drift check (Decision D, frozen policy).

Compares the remux ``output_audio_duration`` (decimal6 seconds) against the
scene timeline, converting BOTH sides ONE-WAY through the canonical
timebase with EXACT rational arithmetic (``CanonicalTimebase`` /
``fractions.Fraction``) — raw floats between frame/ms/s are forbidden.

Classification goes through the frozen T03A policy
(``s11-qc-thresholds-v1``, metric ``av_sync_drift``: warning boundary =
level-2 T06A2 raw 0.1 s, blocker boundary = level-4 raw 0.5 s, sanity
envelope [0.0, 0.5]):

- drift below the warning boundary            -> ``pass``, zero QCItem;
- drift inside the warning band               -> QCItem severity=warning;
- drift at/over the blocker boundary          -> QCItem severity=blocker;
- drift OUTSIDE the calibrated envelope       -> fail-closed blocker with
  ``unit_mismatch_caught=True`` (a frame/ms value misread as seconds can
  never silently pass).

A real NO_AUDIO_PRESENT source is ``not_applicable`` with zero QCItems
(nothing to synchronize).  Evidence is content-derived and idempotent.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from typing import Any

from app.services.qc_checks.registry import register_detector
from app.services.qc_checks.thresholds import (
    STATUS_BLOCKER,
    STATUS_INVALID,
    STATUS_PASS,
    STATUS_WARNING,
    classify,
    get_threshold,
)
from app.services.timebase import (
    CanonicalTimebase,
    TimebaseError,
    exact_seconds,
)

DETECTOR_NAME = "av_sync_drift"
DETECTOR_ENTRY_POINT = "app.services.qc_checks.av_sync_drift:detect"
DETECTOR_REVISION = "1.0.0"

RESULT_NOT_APPLICABLE = "not_applicable"
RESULT_APPLICABLE = "applicable"

REASON_AV_SYNC_DRIFT = "av_sync_drift"
CATEGORY_AV_SYNC_DRIFT = "av_sync_drift"

_METRIC = "av_sync_drift"


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _window_key(
    *,
    video_item_id: str,
    drift_seconds: Fraction,
    classification: str,
) -> str:
    """Content-derived stable evidence window key (<= 64 chars)."""
    digest = hashlib.sha256(
        _canonical_json(
            {
                "detector": DETECTOR_NAME,
                "video_item_id": video_item_id,
                "drift_exact": f"{drift_seconds.numerator}/{drift_seconds.denominator}",
                "classification": classification,
            }
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _scene_duration_fraction(scene: dict[str, Any] | None) -> Fraction | None:
    """Scene timeline -> exact canonical seconds (ONE-WAY conversion).

    Accepts either an explicit ``duration_seconds`` decimal or an exact
    frame grid (``fps_num`` / ``fps_den`` / ``nb_frames``) converted
    through ``CanonicalTimebase.duration_for_frames``.  Returns None when
    the scene timeline is absent/unusable.
    """
    if not isinstance(scene, dict) or not scene:
        return None
    duration_seconds = scene.get("duration_seconds")
    if duration_seconds is not None:
        try:
            return exact_seconds(duration_seconds)
        except TimebaseError:
            return None
    fps_num = scene.get("fps_num")
    fps_den = scene.get("fps_den")
    nb_frames = scene.get("nb_frames")
    if fps_num is None or fps_den is None or nb_frames is None:
        return None
    try:
        timebase = CanonicalTimebase.from_rational(
            int(fps_num), int(fps_den), classification="CFR"
        )
        return timebase.duration_for_frames(int(nb_frames))
    except (TimebaseError, TypeError, ValueError):
        return None


def _build_qc_item(
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    layer_ref_type: str,
    layer_ref_id: str,
    checkpoint_ref: str,
    severity: str,
    classification_code: str,
    drift_seconds: Fraction,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """One QCItem payload (warning or blocker, status=open) ready for the
    T03F orchestrator to persist through the T02B repository."""
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "layer_ref_type": layer_ref_type,
        "layer_ref_id": layer_ref_id,
        "reason_code": REASON_AV_SYNC_DRIFT,
        "evidence_window_key": _window_key(
            video_item_id=video_item_id,
            drift_seconds=drift_seconds,
            classification=classification_code,
        ),
        "evidence": {
            "schema_version": 1,
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            **evidence,
        },
        "status": "open",
        "severity": severity,
        "category": CATEGORY_AV_SYNC_DRIFT,
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_REVISION,
        "confidence": 1.0,
        "confidence_source": "detector",
        "checkpoint_ref": checkpoint_ref,
    }


def detect(args: dict[str, Any]) -> dict[str, Any]:
    """A/V-sync drift check entry point (T03A runner child protocol).

    ``args``:
    - ``checkpoint``: remux checkpoint (status, source_audio_present,
      source_audio_codec, output_audio_duration decimal6, audio_time_base);
    - ``scene_timeline``: {"duration_seconds": ...} or
      {"fps_num", "fps_den", "nb_frames"};
    - ``published``: optional published envelope (used only for the
      NO_AUDIO_PRESENT terminal fact);
    - identity: workspace_id, project_id, video_item_id, layer_ref_type,
      layer_ref_id, checkpoint_ref.

    Returns a JSON-serializable result dict.
    """
    checkpoint = args.get("checkpoint") or {}
    scene = args.get("scene_timeline")
    published = args.get("published")
    if isinstance(published, dict) is False:
        published = None

    identity = {
        "workspace_id": str(args.get("workspace_id") or ""),
        "project_id": str(args.get("project_id") or ""),
        "video_item_id": str(args.get("video_item_id") or ""),
        "layer_ref_type": str(args.get("layer_ref_type") or "video_item"),
        "layer_ref_id": str(args.get("layer_ref_id") or ""),
        "checkpoint_ref": str(args.get("checkpoint_ref") or ""),
    }

    checkpoint_status = str(checkpoint.get("status") or "")
    source_audio = checkpoint.get("source_audio_present")
    no_audio_published = (
        published.get("no_audio_present") if published is not None else None
    )

    base_evidence: dict[str, Any] = {
        "status": checkpoint_status,
        "source_audio_present": source_audio,
        "source_audio_codec": checkpoint.get("source_audio_codec"),
        "output_audio_duration": checkpoint.get("output_audio_duration"),
        "audio_time_base": checkpoint.get("audio_time_base"),
        "scene_timeline": scene if isinstance(scene, dict) else None,
    }

    # Decision D: NO_AUDIO_PRESENT -> not_applicable, zero QCItem.
    if (
        checkpoint_status == "NO_AUDIO_PRESENT"
        or source_audio is False
        or no_audio_published is True
    ):
        return {
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            "applicability": RESULT_NOT_APPLICABLE,
            "status": RESULT_NOT_APPLICABLE,
            "qc_items": [],
            "block_readiness": False,
            "evidence": base_evidence,
        }

    remux_duration_raw = checkpoint.get("output_audio_duration")
    scene_duration = _scene_duration_fraction(scene)

    # Frozen policy boundaries (read-only, cited in evidence).
    threshold = get_threshold(_METRIC)
    warning_boundary = threshold["warning_boundary"]
    blocker_boundary = threshold["blocker_boundary"]

    # Fail-closed: without a usable scene timeline the drift is unknown —
    # never a silent pass.
    if scene_duration is None or remux_duration_raw is None:
        base_evidence.update(
            {
                "warning_boundary": warning_boundary,
                "blocker_boundary": blocker_boundary,
                "drift_unknown_reason": (
                    "scene_timeline_missing"
                    if scene_duration is None
                    else "output_audio_duration_missing"
                ),
            }
        )
        item = _build_qc_item(
            **identity,
            severity=STATUS_BLOCKER,
            classification_code="THRESHOLD_UNKNOWN_SCENE",
            drift_seconds=Fraction(0),
            evidence=base_evidence,
        )
        return {
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            "applicability": RESULT_APPLICABLE,
            "status": STATUS_BLOCKER,
            "qc_items": [item],
            "block_readiness": True,
            "evidence": base_evidence,
        }

    remux_duration = exact_seconds(remux_duration_raw)

    # Exact one-way drift: |remux - scene| in canonical seconds.
    drift = abs(remux_duration - scene_duration)
    drift_float = float(drift)

    classification_status, classification_code = classify(_METRIC, drift_float)
    unit_mismatch = classification_status == STATUS_INVALID

    base_evidence.update(
        {
            "remux_duration_exact": str(remux_duration),
            "scene_duration_exact": str(scene_duration),
            "drift_seconds": drift_float,
            "drift_seconds_exact": str(drift),
            "unit": threshold.get("unit", "s"),
            "warning_boundary": warning_boundary,
            "blocker_boundary": blocker_boundary,
            "classification": classification_status,
            "classification_code": classification_code,
            "unit_mismatch_caught": unit_mismatch,
        }
    )

    if unit_mismatch:
        # Outside the calibrated envelope (e.g. a ms/frame value misread as
        # seconds) -> fail-closed blocker, never a silent pass.
        base_evidence["failure_kind"] = "unit_mismatch_or_uncalibrated"
        item = _build_qc_item(
            **identity,
            severity=STATUS_BLOCKER,
            classification_code=classification_code,
            drift_seconds=drift,
            evidence=base_evidence,
        )
        return {
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            "applicability": RESULT_APPLICABLE,
            "status": STATUS_BLOCKER,
            "qc_items": [item],
            "block_readiness": True,
            "evidence": base_evidence,
        }

    if classification_status == STATUS_PASS:
        return {
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            "applicability": RESULT_APPLICABLE,
            "status": STATUS_PASS,
            "qc_items": [],
            "block_readiness": False,
            "evidence": base_evidence,
        }

    severity = (
        STATUS_WARNING
        if classification_status == STATUS_WARNING
        else STATUS_BLOCKER
    )
    item = _build_qc_item(
        **identity,
        severity=severity,
        classification_code=classification_code,
        drift_seconds=drift,
        evidence=base_evidence,
    )
    return {
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_REVISION,
        "applicability": RESULT_APPLICABLE,
        "status": severity,
        "qc_items": [item],
        "block_readiness": severity == STATUS_BLOCKER,
        "evidence": base_evidence,
    }


register_detector(
    DETECTOR_NAME,
    DETECTOR_ENTRY_POINT,
    version=DETECTOR_REVISION,
    description=(
        "av_sync_drift (Decision D): one-way CanonicalTimebase exact "
        "Fraction drift vs frozen policy bands; unit mismatch fail-closed "
        "blocker; NO_AUDIO_PRESENT -> not_applicable."
    ),
)