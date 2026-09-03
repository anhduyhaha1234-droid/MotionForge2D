"""Frozen read DTOs for the QCItem domain (S11-T02B).

Durable DTO boundary (lane-A §2 #4): the repository returns a frozen
``QCItemRecord`` dataclass; the API layer maps records into these frozen
response DTOs so no ORM object ever crosses the API boundary.  Both types
are plain ``@dataclass(frozen=True)`` — deterministic field order and
serialization, no mutable attributes, no SQLAlchemy dependency.

Shape follows lane-C API_UI_GAP_MATRIX G1/G2 (queue list + item detail):
every location/evidence reference the review UI needs for navigation is
exposed explicitly (project/video/segment logical refs, layer ref, evidence
payload, timestamps).  Canonical navigation RESOLUTION is T04A's scope;
T02B only serves navigation-ready data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = ["QCItemData", "QCItemListResponse"]


@dataclass(frozen=True)
class QCItemData:
    """READ-ONLY view of one QCItem (G2 detail shape + G1 list row)."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    segment_row_id: str | None
    segment_logical_id: str | None
    layer_ref_type: str
    layer_ref_id: str
    reason_code: str
    evidence_window_key: str
    evidence: dict[str, Any]
    status: str
    severity: str
    category: str
    detector: str
    detector_revision: str
    confidence: float
    confidence_source: str
    checkpoint_ref: str
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> QCItemData:
        """Map a repository frozen record to the API DTO (no ORM involved)."""
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            segment_row_id=record.segment_row_id,
            segment_logical_id=record.segment_logical_id,
            layer_ref_type=record.layer_ref_type,
            layer_ref_id=record.layer_ref_id,
            reason_code=record.reason_code,
            evidence_window_key=record.evidence_window_key,
            evidence=record.evidence,
            status=record.status,
            severity=record.severity,
            category=record.category,
            detector=record.detector,
            detector_revision=record.detector_revision,
            confidence=record.confidence,
            confidence_source=record.confidence_source,
            checkpoint_ref=record.checkpoint_ref,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


@dataclass(frozen=True)
class QCItemListResponse:
    """Paged, filterable queue list for one project (G1 shape)."""

    workspace_id: str
    project_id: str
    limit: int
    offset: int
    total: int
    has_more: bool
    items: list[QCItemData]