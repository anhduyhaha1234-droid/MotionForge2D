"""S11-T03E (W6): audio_missing / original-audio presence check (Decision D).

Frozen Decision D (freeze C2-F2) semantics, implemented as a W6 detector
registered in the T03A registry and runnable through the common bounded
runner:

- A source that REALLY has no audio (``NO_AUDIO_PRESENT`` terminal fact)
  is a valid terminal source fact: the check result is ``not_applicable``,
  ZERO QCItems, nothing fabricated, readiness NOT blocked.
- A source that HAS audio, where the expected output is missing / the
  attach job failed / the validated output lost its audio, produces ONE
  QCItem with severity ``blocker`` and status ``open`` (reason_code =
  binding code ``audio_missing``).

Evidence is content-derived ONLY from the checkpoint / published / error
envelopes (``source_audio_present``, ``source_audio_codec``,
``output_audio_duration``, ``audio_time_base`` ...) — no injected
timestamps, no randomness, byte-identical across identical inputs
(idempotent, enforced in the test suite).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.qc_checks.registry import register_detector

DETECTOR_NAME = "audio_missing"
DETECTOR_ENTRY_POINT = "app.services.qc_checks.audio_missing:detect"
DETECTOR_REVISION = "1.0.0"

RESULT_NOT_APPLICABLE = "not_applicable"
RESULT_APPLICABLE = "applicable"

STATUS_PASS = "pass"
STATUS_BLOCKER = "blocker"

REASON_AUDIO_MISSING = "audio_missing"
CATEGORY_AUDIO_MISSING = "audio_missing"

#: Stable failure kinds inside the evidence (content-derived, closed set).
FAILURE_ATTACH_FAILED = "attach_failed"
FAILURE_OUTPUT_MISSING = "output_missing"
FAILURE_OUTPUT_LOST_AUDIO = "output_lost_audio"


def _canonical_json(value: dict[str, Any]) -> str:
    """Byte-stable canonical JSON (deterministic key order, compact)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _window_key(*, video_item_id: str, failure_kind: str) -> str:
    """Content-derived stable evidence window key (<= 64 chars).

    The natural-key discriminator for a QCItem is its evidence window;
    deriving it from content guarantees identical inputs -> identical
    window keys -> idempotent re-runs.
    """
    digest = hashlib.sha256(
        _canonical_json(
            {
                "detector": DETECTOR_NAME,
                "video_item_id": video_item_id,
                "failure_kind": failure_kind,
            }
        ).encode("utf-8")
    )
    return digest.hexdigest()  # 64 lowercase hex chars


def _source_audio_present(
    checkpoint: dict[str, Any], published: dict[str, Any] | None
) -> bool:
    """Derive the source audio presence fact from the envelopes.

    Decision precedence: an explicit source_audio_present flag wins; else
    the source audio codec; else the NO_AUDIO_PRESENT terminal markers.
    """
    explicit = checkpoint.get("source_audio_present")
    if explicit is not None:
        return bool(explicit)
    codec = str(checkpoint.get("source_audio_codec") or "").strip()
    if codec:
        return True
    if str(checkpoint.get("status") or "") == "NO_AUDIO_PRESENT":
        return False
    if published is not None:
        no_audio = published.get("no_audio_present")
        if no_audio is True:
            return False
        if no_audio is False:
            return True
    return False


def _build_qc_item(
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    layer_ref_type: str,
    layer_ref_id: str,
    checkpoint_ref: str,
    failure_kind: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """One QCItem payload (severity=blocker, status=open) ready for the
    T03F orchestrator to persist through the T02B repository."""
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "layer_ref_type": layer_ref_type,
        "layer_ref_id": layer_ref_id,
        "reason_code": REASON_AUDIO_MISSING,
        "evidence_window_key": _window_key(
            video_item_id=video_item_id, failure_kind=failure_kind
        ),
        "evidence": {
            "schema_version": 1,
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            **evidence,
        },
        "status": "open",
        "severity": STATUS_BLOCKER,
        "category": CATEGORY_AUDIO_MISSING,
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_REVISION,
        "confidence": 1.0,
        "confidence_source": "detector",
        "checkpoint_ref": checkpoint_ref,
    }


def detect(args: dict[str, Any]) -> dict[str, Any]:
    """Audio-missing check entry point (T03A runner child protocol).

    ``args`` carries the content-derived envelopes:
    - ``checkpoint``: remux checkpoint (status, source_audio_codec,
      source_audio_duration, output_audio_codec, output_audio_duration,
      audio_time_base, ...);
    - ``published``: optional handler published envelope
      (no_audio_present, artifact_id, ...);
    - ``error``: optional attach-job error envelope (error_type, code);
    - identity: workspace_id, project_id, video_item_id, layer_ref_type,
      layer_ref_id, checkpoint_ref.

    Returns a JSON-serializable result dict (never raises for envelope
    shape drift — missing envelopes degrade to the safe branch).
    """
    checkpoint = args.get("checkpoint") or {}
    published = args.get("published")
    if isinstance(published, dict) is False:
        published = None
    error = args.get("error")
    if isinstance(error, dict) is False:
        error = None

    identity = {
        "workspace_id": str(args.get("workspace_id") or ""),
        "project_id": str(args.get("project_id") or ""),
        "video_item_id": str(args.get("video_item_id") or ""),
        "layer_ref_type": str(args.get("layer_ref_type") or "video_item"),
        "layer_ref_id": str(args.get("layer_ref_id") or ""),
        "checkpoint_ref": str(args.get("checkpoint_ref") or ""),
    }

    source_audio = _source_audio_present(checkpoint, published)
    checkpoint_status = str(checkpoint.get("status") or "")

    base_evidence: dict[str, Any] = {
        "status": checkpoint_status,
        "source_audio_present": source_audio,
        "source_audio_codec": checkpoint.get("source_audio_codec"),
        "source_audio_duration": checkpoint.get("source_audio_duration"),
        "output_audio_codec": checkpoint.get("output_audio_codec"),
        "output_audio_duration": checkpoint.get("output_audio_duration"),
        "audio_time_base": checkpoint.get("audio_time_base"),
        "published_no_audio_present": (
            published.get("no_audio_present") if published else None
        ),
    }

    if not source_audio or checkpoint_status == "NO_AUDIO_PRESENT":
        # Decision D: terminal source fact — nothing to check, nothing to
        # fabricate, readiness untouched.
        return {
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            "applicability": RESULT_NOT_APPLICABLE,
            "status": RESULT_NOT_APPLICABLE,
            "qc_items": [],
            "block_readiness": False,
            "evidence": base_evidence,
        }

    # Source HAS audio.  Determine the failure kind (closed set).
    failure_kind: str | None = None
    if error is not None:
        failure_kind = FAILURE_ATTACH_FAILED
        base_evidence["error_type"] = error.get("error_type")
        base_evidence["error_code"] = error.get("code")
    elif published is None or not published.get("artifact_id"):
        failure_kind = FAILURE_OUTPUT_MISSING
    else:
        output_codec = str(checkpoint.get("output_audio_codec") or "").strip()
        output_duration = checkpoint.get("output_audio_duration")
        if not output_codec or output_duration is None:
            failure_kind = FAILURE_OUTPUT_LOST_AUDIO

    if failure_kind is not None:
        base_evidence["failure_kind"] = failure_kind
        item = _build_qc_item(
            **identity,
            failure_kind=failure_kind,
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

    return {
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_REVISION,
        "applicability": RESULT_APPLICABLE,
        "status": STATUS_PASS,
        "qc_items": [],
        "block_readiness": False,
        "evidence": base_evidence,
    }


register_detector(
    DETECTOR_NAME,
    DETECTOR_ENTRY_POINT,
    version=DETECTOR_REVISION,
    description=(
        "audio_missing (Decision D): NO_AUDIO_PRESENT -> not_applicable "
        "zero QCItem; source-has-audio with lost/missing/failed output -> "
        "blocker/open."
    ),
)