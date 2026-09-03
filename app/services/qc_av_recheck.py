"""S11-T04C (W11) — A/V recheck trigger after verified attach completion.

This module owns the FAIL-CLOSED bridge between a VERIFIED
ATTACH_ORIGINAL_AUDIO completion and the durable A/V recheck
(RUN_QC_CHECKS, ``audio`` scope — ``audio_missing`` + ``av_sync_drift``):

- :func:`ensure_av_recheck` enqueues the recheck through the T03G submit
  authority (:func:`app.workflow.qc_checks_handler.submit_run_qc_checks`)
  — the client NEVER picks a handler, provider, detector or scope here.
  The idempotency key binds the video evidence fingerprint (source
  artifact id + SHA-256 + generation) + policy content hash + scope, so:
    * a COMPLETED duplicate reuses the same run (``reused=True``);
    * an ACTIVE duplicate is covered (``active=True`` — no duplicate run);
    * a terminal FAILED/CANCELLED duplicate cannot be silently covered —
      the ensure FAILS closed (``RECHECK_TERMINAL_BLOCKED``) so the
      attach step never completes without real recheck coverage.
  Any genuine enqueue failure propagates (fail-closed: the caller must
  NOT report the attach completed).
- :func:`attach_recheck_evidence` reads a completed ATTACH_ORIGINAL_AUDIO
  job's successful attempt result through the orchestrator lifecycle
  (JobRepository attempt history — the ONLY allowed evidence resolution:
  no code path here reads or writes the detection-ledger rows directly).

The recheck must only ever be triggered on the VERIFIED output-validation
completion path (published bytes OK or the terminal NO_AUDIO_PRESENT
outcome) — the caller (:mod:`app.workflow.original_audio_handler`
``_attach_output_validator``) owns that ordering; this module FAILS
closed on any malformed/unverified input instead of fabricating checks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.jobs import IdempotencyKeyInUse, JobRepository
from app.persistence.models import Job, VideoItem
from app.workflow.qc_checks_handler import (
    SCOPE_AUDIO,
    QcCheckRunSubmitResult,
    submit_run_qc_checks,
)
from app.workflow.original_audio_handler import JOB_TYPE_ATTACH_ORIGINAL_AUDIO

__all__ = [
    "RECHECK_CHECKPOINT_REF",
    "RECHECK_EVIDENCE_REQUIRED",
    "RECHECK_TERMINAL_BLOCKED",
    "AvRecheckEnqueueError",
    "AvRecheckEnsureResult",
    "attach_recheck_evidence",
    "ensure_av_recheck",
]

#: Provenance marker embedded in the recheck detector args (distinct from
#: the interactive T03G composition so recheck-originated runs are
#: traceable end-to-end).
RECHECK_CHECKPOINT_REF = "s11-qc-av-recheck"

#: Claim priority of a recheck run — deliberately BELOW the default 50
#: used by user-facing jobs (imports/attaches).  The RUN_QC_CHECKS audit
#: triggered by an attach completion is background work: it must never
#: preempt a later user job (``run_once`` claims priority-desc, oldest
#: first); it runs whenever the queue has no higher-priority work.
RECHECK_PRIORITY = 40
RECHECK_PRIORITY_DEFAULT = 50

#: Stable failure codes (fail-closed, never fabricated).
RECHECK_EVIDENCE_REQUIRED = "RECHECK_EVIDENCE_REQUIRED"
RECHECK_TERMINAL_BLOCKED = "RECHECK_TERMINAL_BLOCKED"


class AvRecheckEnqueueError(Exception):
    """The A/V recheck could not be (safely) enqueued — fail closed.

    ``code`` is the stable machine-readable code; ``details`` carry
    structured context for the error envelope / HTTP detail.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class AvRecheckEnsureResult:
    """Outcome of :func:`ensure_av_recheck` — the recheck run identity."""

    job_id: str | None
    reused: bool
    active: bool
    idempotency_key: str
    scope: str = SCOPE_AUDIO

    @property
    def state(self) -> str:
        """Compact routing state: ``queued`` (new run) / ``reused``
        (completed duplicate) / ``active`` (already-running duplicate)."""
        if self.reused:
            return "reused"
        if self.active:
            return "active"
        return "queued"


def _session_factory_or_raise(
    session_factory: Callable[[], Session] | None,
) -> Callable[[], Session]:
    if session_factory is None:
        raise AvRecheckEnqueueError(
            RECHECK_EVIDENCE_REQUIRED,
            "no session factory bound; cannot enqueue the A/V recheck",
        )
    return session_factory


def _verified_attach_envelope(
    attach_result: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract the VERIFIED attach envelope (checkpoint + published).

    Fail-closed: a missing remux checkpoint or a published outcome that is
    neither a published file nor the terminal NO_AUDIO_PRESENT fact is
    rejected — the recheck is never fabricated from partial evidence.
    """
    if not isinstance(attach_result, Mapping):
        raise AvRecheckEnqueueError(
            RECHECK_EVIDENCE_REQUIRED,
            "attach result missing; cannot compose the A/V recheck",
        )
    remux = attach_result.get("remux")
    checkpoint = remux.get("checkpoint") if isinstance(remux, Mapping) else None
    if not isinstance(checkpoint, dict):
        raise AvRecheckEnqueueError(
            RECHECK_EVIDENCE_REQUIRED,
            "attach result carries no remux checkpoint; refusing to "
            "fabricate A/V recheck inputs",
            details={"has_remux": isinstance(remux, Mapping)},
        )
    published = attach_result.get("published")
    if not isinstance(published, Mapping):
        raise AvRecheckEnqueueError(
            RECHECK_EVIDENCE_REQUIRED,
            "attach result carries no published outcome; refusing to "
            "fabricate A/V recheck inputs",
        )
    valid_outcome = bool(published.get("no_audio_present")) or isinstance(
        published.get("final_rel"), str
    )
    if not valid_outcome:
        raise AvRecheckEnqueueError(
            RECHECK_EVIDENCE_REQUIRED,
            "attach result carries no verified published outcome (neither "
            "published bytes nor the terminal NO_AUDIO_PRESENT fact)",
        )
    return checkpoint, dict(published)


def _scene_timeline(
    session: Session, video_item_id: str
) -> dict[str, Any] | None:
    """Server-side persisted scene timeline (mirror of the T03G
    composition: ``video_item.duration_ms`` → seconds; None when absent)."""
    item = session.get(VideoItem, video_item_id)
    if item is None or item.duration_ms is None:
        return None
    return {"duration_seconds": float(item.duration_ms) / 1000.0}


def _detector_args(
    session: Session,
    *,
    video_item_id: str,
    checkpoint: dict[str, Any],
    published: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Server-composed audio-band detector args (T03E envelope contract).

    Mirrors ``compose_check_run_args`` byte-for-byte in envelope shape but
    sources the envelope from the VERIFIED attach result passed by the
    caller (the orchestrator lifecycle resolution is the caller's job) —
    never from client-supplied values.
    """
    base: dict[str, Any] = {
        "checkpoint": checkpoint,
        "published": published,
        "error": None,
        "checkpoint_ref": RECHECK_CHECKPOINT_REF,
    }
    return {
        "audio_missing": dict(base),
        "av_sync_drift": {
            **base,
            "scene_timeline": _scene_timeline(session, video_item_id),
        },
    }


def _demote_recheck_priority(
    session_factory: Callable[[], Session], job_id: str
) -> None:
    """Schedule a freshly created recheck run as BACKGROUND work.

    The RUN_QC_CHECKS audit enqueued at attach completion must never
    preempt later user-facing jobs (imports/attaches are created with the
    default priority 50 and ``run_once`` claims priority-desc, oldest
    first).  Applied ONCE at creation: a job already claimed or already
    demoted is left untouched, and a non-default priority is respected.
    """
    with session_factory() as session:
        row = session.get(Job, job_id)
        if row is None or row.state != "queued":
            return
        if row.priority != RECHECK_PRIORITY_DEFAULT:
            if row.priority == RECHECK_PRIORITY:
                return
            return  # an explicitly prioritized job is never touched
        row.priority = RECHECK_PRIORITY
        session.commit()


def _blocking_job_state(
    session_factory: Callable[[], Session], workspace_id: str, key: str
) -> tuple[str | None, str | None]:
    """(job_id, state) of the job currently occupying the idempotency key.

    Read-only lookup through the standard Job rows (never through the
    detection-ledger rows).
    """
    if not key:
        return None, None
    with session_factory() as session:
        row = session.scalar(
            select(Job).where(
                Job.workspace_id == workspace_id,
                Job.idempotency_key == key,
            ).order_by(Job.created_at.desc())
        )
        if row is None:
            return None, None
        return str(row.id), str(row.state)


def ensure_av_recheck(
    session_factory: Callable[[], Session] | None,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    attach_result: Mapping[str, Any] | None,
    generation: str = "1",
) -> AvRecheckEnsureResult:
    """Idempotently guarantee an A/V recheck run for the verified attach.

    Uses the T03G submit authority (``submit_run_qc_checks``) with the
    server-owned ``audio`` scope; the idempotency key binds the video
    evidence fingerprint (source artifact identity + generation) + policy
    content hash + scope, so the attach job/result fingerprint is exactly
    the run's identity: retrying after a verified completion NEVER
    duplicates the run, and a run missing for a completed attach is
    backfilled by a later call.

    Raises:
        AvRecheckEnqueueError: malformed evidence (``RECHECK_EVIDENCE_REQUIRED``),
            a terminal FAILED/CANCELLED duplicate (``RECHECK_TERMINAL_BLOCKED``),
            or a missing session factory.  Any submit-authority enqueue
            failure propagates (fail-closed).
    """
    factory = _session_factory_or_raise(session_factory)
    checkpoint, published = _verified_attach_envelope(attach_result)

    with factory() as session:
        args = _detector_args(
            session,
            video_item_id=video_item_id,
            checkpoint=checkpoint,
            published=published,
        )

    try:
        result: QcCheckRunSubmitResult = submit_run_qc_checks(
            factory,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            scope=SCOPE_AUDIO,
            detector_args=args,
            generation=generation,
        )
    except IdempotencyKeyInUse as exc:
        # A duplicate already occupies the key.  Classification:
        #  - completed   → covered by the existing run (reuse);
        #  - active      → covered by the in-flight run (no duplicate ok);
        #  - failed/cancelled → NOT covered — the ensure fails closed.
        job_id, state = _blocking_job_state(factory, workspace_id, exc.key)
        job_id = job_id or exc.job_id
        if state == "completed":
            return AvRecheckEnsureResult(
                job_id=job_id,
                reused=True,
                active=False,
                idempotency_key=exc.key,
            )
        if state in ("failed", "cancelled"):
            raise AvRecheckEnqueueError(
                RECHECK_TERMINAL_BLOCKED,
                "an earlier A/V recheck run terminated without completion; "
                "the recheck cannot be re-enqueued under the same evidence "
                "identity",
                details={
                    "job_id": job_id,
                    "state": state,
                    "idempotency_key": exc.key,
                },
            )
        return AvRecheckEnsureResult(
            job_id=job_id,
            reused=False,
            active=True,
            idempotency_key=exc.key,
        )
    if not result.reused:
        _demote_recheck_priority(factory, result.job_id)
    return AvRecheckEnsureResult(
        job_id=result.job_id,
        reused=result.reused,
        active=False,
        idempotency_key=result.idempotency_key,
    )


def attach_recheck_evidence(
    session_factory: Callable[[], Session] | None,
    *,
    workspace_id: str,
    attach_job_id: str,
) -> dict[str, Any] | None:
    """Completed ATTACH_ORIGINAL_AUDIO attempt result → T03E envelope.

    Resolves evidence ONLY through the orchestrator lifecycle (the
    append-only JobAttempt history via JobRepository — mirror of the
    T03G composition read); the job must be a completed attach job with a
    successful attempt carrying a remux checkpoint, otherwise ``None``
    (the caller fails closed — never fabricated).  No detection-ledger
    access.
    """
    del workspace_id  # the job id is the authority; ownership is caller-validated
    if session_factory is None:
        return None
    with session_factory() as session:
        repo = JobRepository(session)
        try:
            job = repo.get_job(attach_job_id)
        except Exception:  # noqa: BLE001 - missing job → no evidence
            return None
        if job.job_type != JOB_TYPE_ATTACH_ORIGINAL_AUDIO or job.state != "completed":
            return None
        for attempt in repo.list_attempts(attach_job_id, limit=20):
            if attempt.error is not None:
                continue
            result = attempt.result or {}
            remux = result.get("remux")
            checkpoint = remux.get("checkpoint") if isinstance(remux, dict) else None
            if isinstance(checkpoint, dict):
                return {"remux": dict(remux), "published": result.get("published")}
    return None