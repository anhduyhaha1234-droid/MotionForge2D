"""Read-only DTOs for the compute-on-the-fly readiness aggregate (S11-T05A).

Shape follows lane-c REVIEW_QUEUE_CONTRACT §4.2 + Decision F: status
``ready|blocked|not_run``, ``blockers[]`` (every entry with WS-07
location/reason/action), ``warning_count`` (only counted, never listed),
plus the D-F identity fields ``policy_version`` (frozen T03A POLICY_ID
constant) and ``content_hash`` (frozen policy content hash).

Responses are strict (``extra="forbid"``) matching the project's durable
DTO convention; the per-video entries carry the fail-closed check-state
detail required for never-run/queued/running/failed/stale (T03G).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.qc_navigation import CanonicalLocationData, NavigationActionData

__all__ = ["ReadinessBlocker", "ReadinessResponse", "ReadinessVideo"]

#: The closed readiness vocabulary (lane-C §4.2 / lane-A fail-closed).
READINESS_STATUS_VALUES: tuple[str, ...] = ("ready", "blocked", "not_run")

StatusLiteral = Literal["ready", "blocked", "not_run"]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadinessBlocker(_StrictBase):
    """One unresolved blocker of a CURRENT check run (WS-07 full detail)."""

    qc_item_id: str
    code: str
    video_item_id: str
    layer_ref_type: str
    layer_ref_id: str
    location: CanonicalLocationData
    reason_vi: str
    action_vi: str
    action: NavigationActionData


class ReadinessVideo(_StrictBase):
    """Per-video fail-closed verdict consumed from the T03G authority."""

    video_item_id: str
    status: StatusLiteral
    run_state: str
    check_state_detail: str
    zero_item_completion: bool | None = None
    latest_job_id: str | None = None
    blockers: int = 0


class ReadinessResponse(_StrictBase):
    """GET /api/v2/projects/{project_id}/readiness body (Decision F)."""

    status: StatusLiteral
    blockers: list[ReadinessBlocker]
    warning_count: int
    videos: list[ReadinessVideo]
    policy_version: str
    content_hash: str
    computed_at: str