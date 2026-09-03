"""S11-T03G (W8) — read authority over durable check-run evidence.

Compute-on-the-fly ONLY (Decision F): this module reads the existing
Job/JobStep/JobAttempt rows plus the QCItem table — there is NO check-run
table and NO migration.  It answers, for one video_item:

- ``latest_check_run_state`` — the latest RUN_QC_CHECKS Job for the video
  with its durable state, and -- for the completed case -- whether the run
  is CURRENT (matches the caller-supplied current video evidence
  fingerprint + policy content hash) or STALE;
- ``check_run_readiness`` — the fail-closed readiness verdict:
  ``ready`` only for a completed current run with zero unresolved
  blocker-severity items; ``blocked`` for a completed current run that
  found blockers; ``not_run`` for never-run / queued / running / failed /
  stale — always with check-state detail (loading the distinction between
  never-run and completed-zero-item runs onto the DURABLE run evidence,
  never onto the emptiness of the QCItem table).

The ``evidence_fingerprint`` and ``policy_content_hash`` arguments are
the CALLER-computed current values (T05A / API routes compute them through
``app.workflow.qc_checks_handler.evidence_fingerprint`` /
``policy_bundle``) — this module stays a pure read authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.persistence.jobs import JobRepository
from app.persistence.qc_items import QCItemRepository
from app.services.qc_checks.thresholds import POLICY_ID, load_policy
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
)

#: Durable run states the authority can report (closed set).
RUN_STATE_NEVER_RUN = "never_run"
RUN_STATE_QUEUED = "queued"
RUN_STATE_RUNNING = "running"
RUN_STATE_FAILED = "failed"
RUN_STATE_STALE = "stale"
RUN_STATE_COMPLETED = "completed"

#: Readiness verdicts (fail-closed; T05A consumes this authority).
READINESS_NOT_RUN = "not_run"
READINESS_BLOCKED = "blocked"
READINESS_READY = "ready"


@dataclass(frozen=True)
class CheckRunState:
    """Read authority view of the latest check-run for one video_item."""

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
    started_at: Any = None
    finished_at: Any = None
    check_state_detail: str = ""


@dataclass(frozen=True)
class CheckRunReadiness:
    """Fail-closed readiness verdict (Decision F: computed on the fly)."""

    status: str
    run_state: str
    video_item_id: str
    blockers: int = 0
    zero_item_completion: bool | None = None
    evidence_matches: bool | None = None
    policy_matches: bool | None = None
    policy_id: str = POLICY_ID
    policy_content_hash: str = ""
    check_state_detail: str = ""
    latest_job_id: str | None = None


def _completion_from_attempts(
    attempts: list[Any],
) -> dict[str, Any] | None:
    """The completion block of the latest SUCCESSFUL attempt (result).

    Append-only attempt history; an attempt with an error envelope never
    carries completion evidence.  Only blocks with the RUN_QC_CHECKS
    schema version are trusted (a foreign or corrupt payload is ignored
    fail-closed — never misread as completion).
    """
    for attempt in attempts:  # newest first
        if attempt.error is not None:
            continue
        result = attempt.result
        if not isinstance(result, dict):
            continue
        if result.get("schema_version") != RUN_QC_SCHEMA_VERSION:
            continue
        if result.get("job_type") != JOB_TYPE_RUN_QC_CHECKS:
            continue
        if result.get("completed") is True:
            return result
    return None


def latest_check_run_state(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    evidence_fingerprint: str,
    policy_content_hash: str,
) -> CheckRunState:
    """Latest RUN_QC_CHECKS run for the video, classified fail-closed.

    Never-run is reported ONLY when no RUN_QC_CHECKS Job exists for the
    video (a completed zero-item run is provably distinct through its
    durable completion evidence).  A completed run whose recorded evidence
    fingerprint or policy hash differs from the caller's CURRENT values is
    STALE — it must not be treated as the current run.
    """
    del project_id  # ownership is validated by the caller / submit authority
    repo = JobRepository(session)
    jobs = repo.list_jobs(
        workspace_id,
        owner_type="video_item",
        owner_id=video_item_id,
        limit=50,
    )
    run_jobs = [j for j in jobs if j.job_type == JOB_TYPE_RUN_QC_CHECKS]
    if not run_jobs:
        return CheckRunState(
            video_item_id=video_item_id,
            run_state=RUN_STATE_NEVER_RUN,
            check_state_detail="no RUN_QC_CHECKS job has ever been submitted "
            "for this video (never-run vs completed-zero-item is decided by "
            "durable run evidence, never by QCItem-table emptiness)",
        )

    job = run_jobs[0]  # newest first (list_jobs ordering)
    attempts = repo.list_attempts(job.id, limit=50)
    completion = _completion_from_attempts(attempts)

    manifest = job.input_manifest
    run_fp = str(manifest.get("evidence_fingerprint") or "")
    run_policy = str(manifest.get("policy_content_hash") or "")
    evidence_matches = run_fp == evidence_fingerprint
    policy_matches = run_policy == policy_content_hash

    base: dict[str, Any] = {
        "video_item_id": video_item_id,
        "job_id": job.id,
        "job_state": job.state,
        "idempotency_key": job.idempotency_key,
        "evidence_fingerprint": run_fp,
        "policy_content_hash": run_policy,
        "scope": manifest.get("scope"),
        "scope_fingerprint": manifest.get("scope_fingerprint"),
        "evidence_matches": evidence_matches,
        "policy_matches": policy_matches,
        "latest_error": job.error,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }

    if job.state == "completed":
        if completion is None:
            # Terminal completed WITHOUT a completion block: corrupt /
            # foreign history — fail closed (never claim a clean run).
            return CheckRunState(
                run_state=RUN_STATE_FAILED,
                check_state_detail=(
                    "latest RUN_QC_CHECKS job is completed but carries no "
                    "valid completion evidence (corrupt/foreign attempt "
                    "history); state is not trustworthy"
                ),
                **base,
            )
        if not (evidence_matches and policy_matches):
            return CheckRunState(
                run_state=RUN_STATE_STALE,
                zero_item_completion=(
                    bool(completion.get("zero_item_completion", {}).get("evidence"))
                    if isinstance(completion.get("zero_item_completion"), dict)
                    else None
                ),
                summary=completion.get("summary"),
                detector_revisions=completion.get("detector_revisions"),
                check_state_detail=(
                    "completed run is STALE: "
                    + ("evidence fingerprint changed" if not evidence_matches else "")
                    + ("; policy content hash changed" if not policy_matches else "")
                ),
                **base,
            )
        return CheckRunState(
            run_state=RUN_STATE_COMPLETED,
            zero_item_completion=_zero_item_flag(completion),
            summary=completion.get("summary"),
            detector_revisions=completion.get("detector_revisions"),
            check_state_detail="completed current run with durable completion "
            "evidence matching the current video evidence fingerprint and "
            "policy hash",
            **base,
        )

    if job.state in ("queued", "pending"):
        return CheckRunState(
            run_state=RUN_STATE_QUEUED,
            zero_item_completion=None,
            check_state_detail=f"latest RUN_QC_CHECKS job is {job.state} "
            "(not completed)",
            **base,
        )
    if job.state in ("running", "cancelling"):
        return CheckRunState(
            run_state=RUN_STATE_RUNNING,
            zero_item_completion=None,
            check_state_detail=f"latest RUN_QC_CHECKS job is {job.state} "
            "(not completed)",
            **base,
        )
    # cancelled / failed / fenced
    return CheckRunState(
        run_state=RUN_STATE_FAILED,
        zero_item_completion=None,
        check_state_detail=f"latest RUN_QC_CHECKS job is {job.state} "
        "(not completed; readiness stays not_run)",
        **base,
    )


def _zero_item_flag(completion: dict[str, Any]) -> bool | None:
    zic = completion.get("zero_item_completion")
    if isinstance(zic, dict):
        return bool(zic.get("evidence"))
    return None


def check_run_readiness(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    evidence_fingerprint: str,
    policy_content_hash: str,
) -> CheckRunReadiness:
    """Fail-closed readiness for one video (Decision F, AC2/AC3).

    - no completed current run (never_run / queued / running / failed /
      stale) ⇒ ``not_run`` with check-state detail;
    - completed current run with zero unresolved blocker items ⇒ ``ready``;
    - completed current run that found blockers ⇒ ``blocked``.
    """
    state = latest_check_run_state(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        evidence_fingerprint=evidence_fingerprint,
        policy_content_hash=policy_content_hash,
    )
    policy = load_policy()

    if state.run_state != RUN_STATE_COMPLETED:
        return CheckRunReadiness(
            status=READINESS_NOT_RUN,
            run_state=state.run_state,
            video_item_id=video_item_id,
            zero_item_completion=state.zero_item_completion,
            evidence_matches=state.evidence_matches,
            policy_matches=state.policy_matches,
            policy_id=str(policy.get("policy_id") or POLICY_ID),
            policy_content_hash=str(policy["content_hash"]),
            check_state_detail=state.check_state_detail,
            latest_job_id=state.job_id,
        )

    records, _total = QCItemRepository(session).list(
        workspace_id, video_item_id=video_item_id, limit=1_000_000
    )
    blockers = sum(
        1
        for r in records
        if str(r.severity) == "blocker" and str(r.status) == "open"
    )
    status = READINESS_READY if blockers == 0 else READINESS_BLOCKED
    return CheckRunReadiness(
        status=status,
        run_state=RUN_STATE_COMPLETED,
        video_item_id=video_item_id,
        blockers=blockers,
        zero_item_completion=state.zero_item_completion,
        evidence_matches=True,
        policy_matches=True,
        policy_id=str(policy.get("policy_id") or POLICY_ID),
        policy_content_hash=str(policy["content_hash"]),
        check_state_detail=(
            "completed current run; zero unresolved blocker items"
            if blockers == 0
            else f"completed current run; {blockers} unresolved blocker item(s)"
        ),
        latest_job_id=state.job_id,
    )