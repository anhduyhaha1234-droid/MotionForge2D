"""Pydantic schemas for targeted object correction (S08-T05).

The correction workflow is durable and two-phase:

1. ``CorrectionRequest`` (POST /preview and POST /) describes ONE targeted
   correction: reassign an occurrence, edit candidate metadata (role or
   occurrence), or the explicit merge/split curation operations.  The
   response's ``ImpactData`` is the pre-confirmation scope report (exact
   affected sets — the UI must show it BEFORE confirmation).
2. Confirm (CAS ``pending -> applied``) applies the targeted mutation +
   supersession + the RECOMPUTE_OBJECTS Job in one transaction; the durable
   correction row is the archive of the old affected state.

Every mutation carries the CAS revisions captured at preview time; a stale
revision is a stable 409 (never a silent overwrite).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.persistence.models import OBJECT_KIND_PATTERN
from app.schemas.object_intelligence import BboxInput


class CorrectionRequest(BaseModel):
    """One targeted correction (all fields optional; kind selects the set).

    Required per kind (validated fail-closed in the repository):
      reassign       -> occurrence_id, occurrence_revision, source_role_id,
                        target_role_id
      candidate_edit -> target, role_id (+ role_revision for target=role,
                        occurrence_id + occurrence_revision for
                        target=occurrence), and at least one edited field
      merge          -> target_role_id, target_revision, source_role_ids
      split          -> target_role_id, target_revision, original_role_id
    Common: project_id, video_item_id, generation (the source generation the
    affected roles belong to).
    """

    kind: Literal["reassign", "candidate_edit", "merge", "split"]
    project_id: str = Field(..., min_length=1)
    video_item_id: str = Field(..., min_length=1)
    generation: str = Field(..., min_length=1, max_length=64)

    # reassign
    occurrence_id: str | None = None
    occurrence_revision: int | None = Field(None, ge=1)
    source_role_id: str | None = None
    target_role_id: str | None = None

    # candidate_edit
    target: Literal["role", "occurrence"] | None = None
    role_id: str | None = None
    role_revision: int | None = Field(None, ge=1)
    name: str | None = Field(None, min_length=1, max_length=240)
    #: Role kind edit (JSON field ``role_kind`` — ``kind`` is already the
    #: correction kind).  Canonical seven-kind ObjectRole taxonomy (S08-A01),
    #: pattern derived from ``OBJECT_KINDS`` (F3 single authority).
    kind_field: str | None = Field(None, pattern=OBJECT_KIND_PATTERN, alias="role_kind")
    description: str | None = None
    bbox: BboxInput | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    review_state: Literal["unreviewed", "accepted", "rejected", "edited"] | None = None
    reasons: list[str] | None = None

    # merge / split
    target_revision: int | None = Field(None, ge=1)
    source_role_ids: list[str] | None = None
    suggestion_id: str | None = None
    original_role_id: str | None = None
    note: str | None = Field(None, max_length=500)

    idempotency_key: str | None = Field(None, max_length=255)


class ImpactData(BaseModel):
    """The pre-confirmation impacted-scope report (read-only computation)."""

    correction_type: str
    affected_role_ids: list[str]
    affected_occurrence_ids: list[str]
    invalidated_suggestion_ids: list[str]
    artifact_role_ids: list[str]
    regenerate_suggestions: bool
    recompute_needed: bool
    counts: dict[str, int]


class RecomputeStateData(BaseModel):
    """The honest recompute outcome (follows the successor chain)."""

    recompute_needed: bool
    job_id: str | None
    status: str | None
    progress: float | None
    error: str | None


class CorrectionData(BaseModel):
    """Read model of one durable correction."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    correction_type: str
    status: str
    request: dict[str, Any]
    impact: ImpactData
    result: dict[str, Any] | None
    recompute_job_id: str | None
    applied_at: datetime | None
    idempotency_key: str | None
    natural_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    recompute: RecomputeStateData | None = None

    @classmethod
    def from_record(
        cls, record: Any, recompute: RecomputeStateData | None = None
    ) -> CorrectionData:
        impact = record.impact or {}
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            correction_type=record.correction_type,
            status=record.status,
            request=record.request,
            impact=ImpactData(
                correction_type=str(
                    impact.get("correction_type") or record.correction_type
                ),
                affected_role_ids=list(impact.get("affected_role_ids") or []),
                affected_occurrence_ids=list(
                    impact.get("affected_occurrence_ids") or []
                ),
                invalidated_suggestion_ids=list(
                    impact.get("invalidated_suggestion_ids") or []
                ),
                artifact_role_ids=list(impact.get("artifact_role_ids") or []),
                regenerate_suggestions=bool(
                    impact.get("regenerate_suggestions")
                ),
                recompute_needed=bool(impact.get("recompute_needed")),
                counts={
                    str(k): int(v)
                    for k, v in (impact.get("counts") or {}).items()
                },
            ),
            result=record.result,
            recompute_job_id=record.recompute_job_id,
            applied_at=record.applied_at,
            idempotency_key=record.idempotency_key,
            natural_key=record.natural_key,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            recompute=recompute,
        )


class CorrectionCreateResponse(BaseModel):
    correction: CorrectionData
    created: bool
    status: str


class CorrectionConfirmRequest(BaseModel):
    revision: int = Field(..., ge=1)


class CorrectionCancelRequest(BaseModel):
    revision: int = Field(..., ge=1)


class CorrectionListResponse(BaseModel):
    workspace_id: str
    limit: int
    offset: int
    total: int
    corrections: list[CorrectionData]
