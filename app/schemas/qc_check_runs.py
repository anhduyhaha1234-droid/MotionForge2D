"""S11-T03G (W8) — check-run HTTP schemas (server-owned action contract).

Decision A: the POST payload carries ONLY the video identity + the
server-owned scope.  The request model forbids extra fields, so a client
can never smuggle a handler/provider/detector implementation choice into
the request (fails closed with 422).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflow.qc_checks_handler import SCOPE_AUDIO, SCOPE_FULL

#: Server-owned scopes the API accepts (exactly the handler's closed set).
QcCheckRunScope = Literal[SCOPE_FULL, SCOPE_AUDIO]


class QcCheckRunSubmitRequest(BaseModel):
    """Server-owned check-run submission.

    ``extra="forbid"`` is the binary Decision-A gate: any payload field
    that tries to pick an implementation (handler/provider/detector/...)
    is rejected with 422 before the route body runs.
    """

    model_config = ConfigDict(extra="forbid")

    video_item_id: str = Field(min_length=1, max_length=36)
    scope: QcCheckRunScope


class QcCheckRunSubmitResponse(BaseModel):
    """Accepted durable check-run submission (202)."""

    job_id: str
    reused: bool
    state: str
    idempotency_key: str
    scope: str


class QcCheckRunStateResponse(BaseModel):
    """Read authority: latest check-run state for one video_item."""

    workspace_id: str
    project_id: str
    video_item_id: str
    run_state: str
    job_id: str | None = None
    job_state: str | None = None
    idempotency_key: str | None = None
    evidence_fingerprint: str | None = None
    policy_content_hash: str | None = None
    scope: str | None = None
    scope_fingerprint: str | None = None
    detector_revisions: dict[str, str] | None = None
    summary: dict[str, Any] | None = None
    zero_item_completion: bool | None = None
    evidence_matches: bool | None = None
    policy_matches: bool | None = None
    latest_error: dict[str, Any] | None = None
    check_state_detail: str = ""


class QcCheckRunReadinessResponse(BaseModel):
    """Fail-closed readiness verdict (Decision F consumption point)."""

    workspace_id: str
    project_id: str
    video_item_id: str
    status: str
    run_state: str
    blockers: int = 0
    zero_item_completion: bool | None = None
    evidence_matches: bool | None = None
    policy_matches: bool | None = None
    policy_id: str = ""
    policy_content_hash: str = ""
    current_evidence_fingerprint: str = ""
    check_state_detail: str = ""
    latest_job_id: str | None = None