"""Pydantic schemas for cross-scene grouping and curation (S08-T03).

Reviewable grouping suggestions (confidence/reasons/provenance, never
auto-confirmed) plus the explicit durable merge/split/confirm operations and
their read-only audit history.  Every mutation is CAS-protected (required
``revision``) and every read exposes the review reasons/audit payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.object_intelligence import RoleData


class GenerateSuggestionsRequest(BaseModel):
    """Deterministic grouping run over one video item's active roles."""

    video_item_id: str = Field(..., min_length=1)
    source_generation: str = Field(..., min_length=1, max_length=64)
    scope: Literal["video"] = "video"
    algorithm_version: str = Field("1", min_length=1, max_length=64)
    idempotency_key: str | None = Field(None, max_length=255)


class SuggestionDismissRequest(BaseModel):
    """CAS payload to dismiss (reject) one pending suggestion."""

    revision: int = Field(..., ge=1)


class MergeRequest(BaseModel):
    """Explicit durable merge of source roles into the target role."""

    revision: int = Field(..., ge=1)
    video_item_id: str = Field(..., min_length=1)
    source_role_ids: list[str] = Field(..., min_length=1, max_length=20)
    suggestion_id: str | None = Field(None, min_length=1)
    idempotency_key: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=500)


class SplitRequest(BaseModel):
    """Explicit durable split of one merged original role out of the target."""

    revision: int = Field(..., ge=1)
    video_item_id: str = Field(..., min_length=1)
    original_role_id: str = Field(..., min_length=1)
    idempotency_key: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=500)


class ConfirmRequest(BaseModel):
    """Explicit durable confirmation of one role (audit + CAS)."""

    revision: int = Field(..., ge=1)
    video_item_id: str = Field(..., min_length=1)
    idempotency_key: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=500)


class SuggestionData(BaseModel):
    """Read model of one reviewable grouping suggestion."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    status: str
    role_ids: list[str]
    target_role_id: str | None
    confidence: float
    reasons: list[str]
    algorithm: str
    algorithm_version: str
    scope: str
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> SuggestionData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            source_generation=record.source_generation,
            status=record.status,
            role_ids=list(record.role_ids or []),
            target_role_id=record.target_role_id,
            confidence=record.confidence,
            reasons=list(record.reasons or []),
            algorithm=record.algorithm,
            algorithm_version=record.algorithm_version,
            scope=record.scope,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class SuggestionListResponse(BaseModel):
    """Paged, current-generation-default suggestion listing (finding C2).

    ``scope`` is ``"current"`` (the backend-authoritative current
    generation) or ``"historical"`` (an explicit ``source_generation``
    was supplied — the only way to inspect a non-current generation).
    ``current_generation`` is echoed when a single video item scopes the
    query; ``source_generation`` echoes the explicit filter when given
    (None for the current default).
    """

    workspace_id: str
    limit: int
    offset: int
    total: int
    scope: str
    source_generation: str | None
    current_generation: str | None
    suggestions: list[SuggestionData]


class GroupingPolicyData(BaseModel):
    """Backend-authoritative grouping policy metadata (correction C1)."""

    algorithm: str
    algorithm_version: str
    calibration_version: str
    review_threshold: float
    advisory: bool
    confidence_semantics: list[str]
    note: str

    @classmethod
    def from_policy(cls, policy: Any) -> GroupingPolicyData:
        return cls(
            algorithm=policy.algorithm,
            algorithm_version=policy.algorithm_version,
            calibration_version=policy.calibration_version,
            review_threshold=policy.review_threshold,
            advisory=policy.advisory,
            confidence_semantics=list(policy.confidence_semantics or []),
            note=policy.note,
        )


class GenerateResultData(BaseModel):
    """Outcome of one grouping generation run."""

    video_item_id: str
    source_generation: str
    algorithm: str
    algorithm_version: str
    calibration_version: str
    scope: str
    created_count: int
    replayed_count: int
    superseded_count: int
    total: int
    suggestions: list[SuggestionData]
    policy: GroupingPolicyData


class TransferEntryData(BaseModel):
    """One source role's occurrence ids moved by a merge/split."""

    role_id: str
    occurrence_ids: list[str]


class OperationData(BaseModel):
    """Read model of one audit-recorded merge/split/confirm operation."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    operation_type: str
    target_role_id: str
    source_role_ids: list[str]
    created_role_ids: list[str]
    transfer_map: list[TransferEntryData]
    suggestion_id: str | None
    idempotency_key: str | None
    revision_after: int
    note: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> OperationData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            operation_type=record.operation_type,
            target_role_id=record.target_role_id,
            source_role_ids=list(record.source_role_ids or []),
            created_role_ids=list(record.created_role_ids or []),
            transfer_map=[
                TransferEntryData(
                    role_id=entry.role_id,
                    occurrence_ids=list(entry.occurrence_ids or []),
                )
                for entry in (record.transfer_map or [])
            ],
            suggestion_id=record.suggestion_id,
            idempotency_key=record.idempotency_key,
            revision_after=record.revision_after,
            note=record.note,
            created_at=record.created_at,
        )


class OperationListResponse(BaseModel):
    workspace_id: str
    limit: int
    offset: int
    total: int
    operations: list[OperationData]


class MergeResultData(BaseModel):
    operation: OperationData
    target_role: RoleData


class SplitResultData(BaseModel):
    operation: OperationData
    created_role: RoleData


class ConfirmResultData(BaseModel):
    operation: OperationData
    role: RoleData
