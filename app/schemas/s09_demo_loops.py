"""Pydantic schemas for the S09 demo-loop API (S09-T03).

Strict, typed, extra-forbidden, strict-mode DTOs between
app/api/routes/s09_demo_loops and the durable core app/workflow/s09_demo_jobs.

Invariants (mirroring reskin_config schemas):
- model_config = ConfigDict(extra="forbid", strict=True) on every request
  model — unknown field → 422, no silent coercion.
- No client-fabricated workspace authority: workspace_id never appears in
  requests (server-owned DEFAULT_WORKSPACE_ID).
- requested_loops: 1..8 stable fixture loop ids; pinned_routes values must
  be one of the canonical renderer routes (validated against RENDERER_ROUTES).
- Deterministic serialization via typed Pydantic read models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LoopId = str


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DemoLoopSubmitRequest(_StrictBase):
    """Submit one risk-selected demo-loop batch as a durable Job.

    ``requested_loops`` must JOINTLY cover all six S09-T03 risk classes —
    enforced by the planner at run time (fail-closed); the schema only
    enforces shape so clients get 201/409/422 semantics without running
    evidence lookups on the request path.
    """

    requested_loops: list[LoopId] = Field(..., min_length=1, max_length=8)
    benchmark_results: str = Field(..., min_length=1)
    fixtures_dir: str = Field(..., min_length=1)
    #: Optional per-risk-class pinned SegmentRenderRoute overrides.  A pin is
    #: honored only when it is measured-passing for that class (fail-closed
    #: at plan time; otherwise the submission refuses with 422).
    pinned_routes: dict[str, str] | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)


class PublishedLoopArtifact(_StrictBase):
    loop_id: str
    relative_path: str
    artifact_id: str
    sha256: str
    size_bytes: int
    frame_count: int | None = None
    reused_existing_file: bool | None = None


class PlanRouteSummary(_StrictBase):
    loop_id: str
    routes_by_risk_class: dict[str, str]
    route_notes: list[str] = []


class DemoLoopPlanSummary(_StrictBase):
    covered_risk_classes: list[str]
    frozen_content_sha256: str
    thresholds_policy: str | None
    loops: list[PlanRouteSummary]


class DemoLoopSubmitResponse(_StrictBase):
    """201 create / 200 idempotent-replay response body."""

    job_id: str
    status: str
    reused: bool = False
    detail_url: str


class DemoLoopStatusResponse(_StrictBase):
    """Status + published artifacts of one demo-loop Job."""

    job_id: str
    job_type: str
    state: str
    progress: float
    error: dict[str, Any] | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    plan: DemoLoopPlanSummary | None = None
    published: list[PublishedLoopArtifact] = []
