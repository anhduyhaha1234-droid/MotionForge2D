"""MF-P1-QC-EVIDENCE — real persisted evidence composition for the QC band.

Public surface:

- :func:`compose_visual_band` — server-side compositor for the eight
  non-audio detectors of the FULL band, built ONLY from persisted evidence
  (with byte-level integrity verification);
- :data:`CONTRACTS` / :func:`table_digest` / :func:`render_markdown` — the
  FROZEN detector → input → producer → provenance table;
- :class:`QcEvidenceError` and the stable refusal codes.

The audio pair (``audio_missing`` / ``av_sync_drift``) keeps the existing
T03E attach-envelope composition path owned by the workflow handler; this
package deliberately does not re-implement it.
"""

from __future__ import annotations

from app.services.qc_evidence.compose import (
    CHECKPOINT_REF,
    CROP_WINDOW_PX,
    VISUAL_DETECTORS,
    compose_visual_band,
)
from app.services.qc_evidence.contract import (
    CONTRACTS,
    EVIDENCE_FAMILIES,
    FULL_BAND,
    DetectorInputContract,
    contract_for,
    render_markdown,
    table_digest,
    table_payload,
)
from app.services.qc_evidence.errors import (
    EVIDENCE_REFUSAL_CODES,
    QC_EVIDENCE_DEPENDENCY,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_TAMPERED,
    QcEvidenceError,
)

__all__ = [
    "CHECKPOINT_REF",
    "CONTRACTS",
    "CROP_WINDOW_PX",
    "EVIDENCE_FAMILIES",
    "EVIDENCE_REFUSAL_CODES",
    "FULL_BAND",
    "QC_EVIDENCE_DEPENDENCY",
    "QC_EVIDENCE_FOREIGN",
    "QC_EVIDENCE_MALFORMED",
    "QC_EVIDENCE_MISSING",
    "QC_EVIDENCE_STALE",
    "QC_EVIDENCE_TAMPERED",
    "QcEvidenceError",
    "VISUAL_DETECTORS",
    "DetectorInputContract",
    "compose_visual_band",
    "contract_for",
    "render_markdown",
    "table_digest",
    "table_payload",
]
