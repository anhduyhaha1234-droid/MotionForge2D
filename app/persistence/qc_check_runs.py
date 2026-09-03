"""S11-T03G (W8) — read authority over durable check-run evidence.

Compute-on-the-fly ONLY (Decision F): this module reads the existing
Job/JobStep/JobAttempt rows plus the QCItem table — there is NO check-run
table and NO migration.  It answers, for one video_item:

- ``latest_check_run_state`` — the latest **SCOPE_FULL** RUN_QC_CHECKS
  Job for the video with its durable state, and -- for the completed case
  -- whether the run is CURRENT (matches the caller-supplied current video
  evidence fingerprint + policy content hash) or STALE.  ONLY a completed
  full run whose completion envelope proves the binding 10-detector
  coverage (manifest scope + scope fingerprint + detector names + zero
  errors + zero skipped) is the readiness authority; newest-audio/partial
  runs never substitute (C1-A).
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
    SCOPE_FULL,
    scope_fingerprint,
)

#: The binding FULL-scope detector band (server-owned): 8 visual checks +
#: 2 audio checks.  Derived — not guessed — from the frozen T03A policy
#: calibration metric names (``thresholds`` owns the single production
#: policy path): every policy metric maps to exactly one detector, with
#: the ``no_audio_source_fact`` metric owned by the ``audio_missing``
#: detector (T03E contract: the metric is the source-fact the detector
#: evaluates, not a detector name).
_POLICY_METRIC_TO_DETECTOR: dict[str, str] = {
    "trajectory_drift": "trajectory_drift",
    "cut_drift": "cut_drift",
    "contact_break": "contact_break",
    "z_order_error": "z_order_error",
    "silhouette_clipping": "silhouette_clipping",
    "identity_drift": "identity_drift",
    "edge_halo": "edge_halo",
    "temporal_flicker": "temporal_flicker",
    "no_audio_source_fact": "audio_missing",
    "av_sync_drift": "av_sync_drift",
}

# (The server-owned audio-band names come from ``scope_detectors`` at the
# call sites that need them; this module only names the FULL authority.)


def full_coverage_detectors() -> list[str]:
    """The binding FULL-scope detector band (frozen metric → detector map).

    Built from the frozen policy thresholds ("thresholds" metric keys, in
    sorted order) through ``_POLICY_METRIC_TO_DETECTOR`` so the authority
    never guesses a detector name: an unmapped policy metric raises
    fail-closed instead of silently narrowing coverage.
    """
    policy = load_policy()
    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("frozen policy has no thresholds; coverage unknowable")
    band: list[str] = []
    for metric in sorted(thresholds):
        detector = _POLICY_METRIC_TO_DETECTOR.get(str(metric))
        if detector is None:
            raise ValueError(
                f"policy metric {metric!r} has no mapped detector; "
                "full-run coverage is unknowable (fail closed)"
            )
        band.append(detector)
    return band


def full_scope_fingerprint() -> str:
    """Content-derived identity the FULL scope fingerprint must equal."""
    return scope_fingerprint(SCOPE_FULL)

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


def _manifest_scope_fingerprint(manifest: Any) -> str:
    """The manifest's recorded scope fingerprint (empty when absent)."""
    if isinstance(manifest, dict):
        return str(manifest.get("scope_fingerprint") or "")
    return ""


def _completion_proves_full_coverage(
    completion: dict[str, Any],
    *,
    manifest_scope: str,
    manifest_scope_fp: str,
) -> tuple[bool, str]:
    """Whether a completion block proves the binding FULL-scope coverage.

    ALL of these must hold (fail-closed, with the reason named):
      1. manifest scope is ``full`` (the server-owned full band);
      2. manifest scope fingerprint equals the content-derived FULL
         fingerprint (the submit-time band was the full band);
      3. completion scope + scope fingerprint agree with the manifest
         (the envelope the handler wrote matches the submitted band);
      4. completion detectors equal the binding full band (order-insensitive;
         audio-only / visual-only / partial runs never substitute, and
         partial runs are never summed into coverage);
      5. completion revisions cover every full-band detector;
      6. summary errors == 0 AND checks_skipped == 0 (an errored or
         partially-skipped run is never authority).
    """
    if manifest_scope != SCOPE_FULL:
        return False, (
            f"manifest scope {manifest_scope!r} is not the full band "
            "(audio-only/partial runs never substitute for full authority)"
        )
    expected_fp = full_scope_fingerprint()
    if manifest_scope_fp != expected_fp:
        return False, (
            "manifest scope fingerprint does not match the content-derived "
            "full-band identity (the submitted band was not the full band)"
        )
    completion_scope = completion.get("scope")
    if completion_scope != SCOPE_FULL:
        return False, (
            f"completion scope {completion_scope!r} does not match the full "
            "band (completion/manifest scope mismatch)"
        )
    if str(completion.get("scope_fingerprint") or "") != expected_fp:
        return False, (
            "completion scope fingerprint does not match the content-derived "
            "full-band identity"
        )
    expected_detectors = full_coverage_detectors()
    completion_detectors = completion.get("detectors")
    if (
        not isinstance(completion_detectors, list)
        or sorted(str(name) for name in completion_detectors)
        != sorted(expected_detectors)
    ):
        return False, (
            "completion detectors do not equal the binding full band "
            f"(expected {sorted(expected_detectors)}; "
            "audio-only/partial runs never substitute, and partial runs "
            "are never summed into coverage)"
        )
    revisions = completion.get("detector_revisions")
    if not isinstance(revisions, dict) or any(
        name not in revisions for name in expected_detectors
    ):
        return False, (
            "completion detector revisions do not cover the full band"
        )
    summary = completion.get("summary")
    if not isinstance(summary, dict):
        return False, "completion summary is missing (cannot prove coverage)"
    try:
        errors = int(summary.get("errors") or 0)
        skipped = int(summary.get("checks_skipped") or 0)
    except (TypeError, ValueError):
        return False, "completion summary counts are unreadable"
    if errors != 0:
        return False, (
            f"completion summary reports {errors} error(s); an errored run "
            "is never the readiness authority"
        )
    if skipped != 0:
        return False, (
            f"completion summary reports {skipped} skipped check(s); a "
            "partially-skipped run is never the readiness authority"
        )
    return True, ""


def latest_check_run_state(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    evidence_fingerprint: str,
    policy_content_hash: str,
) -> CheckRunState:
    """Latest FULL-scope RUN_QC_CHECKS run for the video, fail-closed.

    The readiness authority is the newest FULL-scope run row — NEVER the
    newest RUN_QC_CHECKS row regardless of scope:

    - never-run is reported ONLY when no FULL-scope RUN_QC_CHECKS Job
      exists for the video (audio-only/partial runs never create full
      authority; a completed full zero-item run is provably distinct
      through its durable completion evidence);
    - audio-only/partial runs are INVISIBLE to this authority: a newer
      audio-only completed run never displaces a completed full run, and
      a newer audio-only run over a stale/absent full run still reports
      not_run;
    - the newest FULL-scope Job wins even when it is queued/running/
      failed/stale/corrupt — the authority NEVER falls back to an older
      completed full run (newest-full fail-closed);
    - ONLY a completed full run whose completion envelope proves the
      binding 10-detector coverage (manifest scope + scope fingerprint +
      detector names + revisions + zero errors + zero skipped) is the
      current run; anything weaker is stale/corrupt (not_run).

    The ``latest_job_id`` of the readiness verdict is therefore the newest
    FULL-scope Job id (never an audio/partial Job id).
    """
    del project_id  # ownership is validated by the caller / submit authority
    repo = JobRepository(session)
    jobs = repo.list_jobs(
        workspace_id,
        owner_type="video_item",
        owner_id=video_item_id,
        limit=50,
    )
    full_jobs = [
        j
        for j in jobs
        if j.job_type == JOB_TYPE_RUN_QC_CHECKS
        and isinstance(j.input_manifest, dict)
        and str(j.input_manifest.get("scope") or "") == SCOPE_FULL
    ]
    if not full_jobs:
        return CheckRunState(
            video_item_id=video_item_id,
            run_state=RUN_STATE_NEVER_RUN,
            check_state_detail="no SCOPE_FULL RUN_QC_CHECKS job has ever been submitted "
            "for this video (audio-only/partial runs never create full-run "
            "authority; never-run vs completed-zero-item is decided by "
            "durable run evidence, never by QCItem-table emptiness)",
        )

    job = full_jobs[0]  # newest FULL-scope run first (list_jobs ordering)
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
                    "latest FULL-scope RUN_QC_CHECKS job is completed but carries no "
                    "valid completion evidence (corrupt/foreign attempt "
                    "history); state is not trustworthy"
                ),
                **base,
            )
        coverage_ok, coverage_reason = _completion_proves_full_coverage(
            completion,
            manifest_scope=str(manifest.get("scope") or ""),
            manifest_scope_fp=_manifest_scope_fingerprint(manifest),
        )
        if not coverage_ok:
            return CheckRunState(
                run_state=RUN_STATE_FAILED,
                zero_item_completion=(
                    bool(completion.get("zero_item_completion", {}).get("evidence"))
                    if isinstance(completion.get("zero_item_completion"), dict)
                    else None
                ),
                summary=completion.get("summary"),
                detector_revisions=completion.get("detector_revisions"),
                check_state_detail=(
                    "completed FULL-scope run does NOT prove full coverage "
                    f"({coverage_reason}); readiness stays not_run"
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
                    "completed FULL-scope run is STALE: "
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
            check_state_detail="completed current FULL-scope run with durable completion "
            "evidence proving the binding 10-detector coverage and matching "
            "the current video evidence fingerprint and policy hash",
            **base,
        )

    if job.state in ("queued", "pending"):
        return CheckRunState(
            run_state=RUN_STATE_QUEUED,
            zero_item_completion=None,
            check_state_detail="latest FULL-scope RUN_QC_CHECKS job is "
            f"{job.state} (not completed; the authority never falls back to "
            "an older completed full run)",
            **base,
        )
    if job.state in ("running", "cancelling"):
        return CheckRunState(
            run_state=RUN_STATE_RUNNING,
            zero_item_completion=None,
            check_state_detail="latest FULL-scope RUN_QC_CHECKS job is "
            f"{job.state} (not completed; the authority never falls back to "
            "an older completed full run)",
            **base,
        )
    # cancelled / failed / fenced
    return CheckRunState(
        run_state=RUN_STATE_FAILED,
        zero_item_completion=None,
        check_state_detail="latest FULL-scope RUN_QC_CHECKS job is "
        f"{job.state} (not completed; readiness stays not_run)",
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
    """Fail-closed readiness for one video (Decision F, AC2/AC3, C1-A).

    - no completed CURRENT FULL-scope run (never_run / queued / running /
      failed / stale / coverage-unproven) ⇒ ``not_run`` with check-state
      detail; audio-only/partial runs never create authority and newest
      non-completed full runs never fall back to an older completed full;
    - completed current FULL run with zero unresolved blocker items ⇒
      ``ready``;
    - completed current FULL run that found blockers ⇒ ``blocked``.
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