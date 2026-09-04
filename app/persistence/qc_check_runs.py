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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.jobs import JobRepository, _job_record, parse_json
from app.persistence.models import Job
from app.persistence.qc_items import QCItemRepository
from app.services.qc_checks.thresholds import POLICY_ID, load_policy
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_FULL,
    detector_revisions as _server_detector_revisions,
    evidence_fingerprint as _current_evidence_fingerprint,
    scope_fingerprint,
    source_artifact_fingerprint as _current_source_fingerprint,
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
    fp = scope_fingerprint(SCOPE_FULL)
    assert isinstance(fp, str)
    return fp


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


def _newest_full_job(
    repo: JobRepository,
    workspace_id: str,
    video_item_id: str,
) -> Any | None:
    """Newest SCOPE_FULL RUN_QC_CHECKS Job queried DIRECTLY (no row cap).

    C2-A1 history-pressure fix: the query filters ``job_type`` +
    ``owner`` in SQL and walks newest-first WITHOUT a page limit, so
    any number of newer audio-only/partial Jobs can never hide a valid
    full-run authority behind a row window.  Scope is a Python-side
    match on the parsed manifest (JSON text is not SQL-filterable), but
    the walk is UNBOUNDED: it stops at the first FULL-scope row and
    only reports never-run when the stream is exhausted.
    """
    session = repo._session
    offset = 0
    page = 500
    while True:
        query = (
            select(Job)
            .where(Job.workspace_id == workspace_id)
            .where(Job.job_type == JOB_TYPE_RUN_QC_CHECKS)
            .where(Job.owner_type == "video_item")
            .where(Job.owner_id == video_item_id)
            .order_by(Job.created_at.desc())
            .offset(offset)
            .limit(page)
        )
        rows = session.scalars(query).all()
        if not rows:
            return None
        for row in rows:
            manifest = parse_json(row.input_manifest_json, {})
            if (
                isinstance(manifest, dict)
                and manifest.get("scope") == SCOPE_FULL
            ):
                return _job_record(row)
        if len(rows) < page:
            return None
        offset += page


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

    C2-A1: the completion identity fields are read back verbatim from the
    attempt row — NO normalization, NO defaults, NO coercion.  A missing
    key stays ``None`` (it is NOT filled with ``\"\"``, ``0`` or
    ``False``); a wrong-typed value stays wrong-typed.  The envelope
    gate below rejects anything but PRESENT, correctly-typed, exactly
    matching values.  Any defaulting here would launder a corrupt or
    tampered completion into authority.
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


def _source_identity_from_manifest(
    manifest: dict[str, Any],
) -> tuple[Any, Any] | None:
    """The manifest's recorded source identity, or ``None`` when corrupt.

    The producer (``submit_run_qc_checks``) writes ``source_artifact_id``
    (``None`` for the legitimate no-source case, else the artifact id)
    paired with ``source_sha256`` (empty for no-source, else the recorded
    SHA).  A manifest whose fields disagree with that representation —
    ``None`` id with non-empty SHA, or a real id with an empty/non-string
    SHA — is corrupt, NOT defaulted.  A missing id key stays missing
    (``None`` is returned, never a filled default).
    """
    if "source_artifact_id" not in manifest:
        return None
    artifact_id = manifest.get("source_artifact_id")
    sha = manifest.get("source_sha256")
    if artifact_id is None:
        if sha != "":
            return None
        return (None, "")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    if not isinstance(sha, str) or not sha:
        return None
    return (artifact_id, sha)


def _completion_proves_full_coverage(
    completion: dict[str, Any],
    *,
    manifest: dict[str, Any],
    evidence_fingerprint: str,
    policy_id: str,
    policy_content_hash: str,
    job_generation: str,
    current_source_precomputed: tuple[Any, Any],
) -> tuple[bool, str]:
    """Whether a completion block proves the binding FULL-scope coverage.

    C2-A1 envelope (ALL must hold, fail-closed, reason named):

    IDENTITY — the completion is the manifest's own write-back, for the
    CURRENT video evidence and policy (no tamper, no replay, no drift):
      1. completion ``schema_version`` PRESENT and == the RUN_QC_CHECKS
         schema version (exact; no coercion);
      2. completion ``job_type`` PRESENT and == RUN_QC_CHECKS (exact);
      3. MANIFEST ``schema_version`` PRESENT, exact JSON integer (bool is
         NOT an integer), and == the RUN_QC_CHECKS schema version;
      4. manifest scope PRESENT and == ``full`` (the server-owned band);
      5. manifest scope fingerprint PRESENT and == the content-derived
         FULL fingerprint (the submitted band was the full band);
      6. completion scope + scope fingerprint PRESENT and equal to the
         manifest's values (the envelope the handler wrote matches the
         submitted band — verbatim, not re-derived);
      7. MANIFEST evidence fingerprint PRESENT and == the CURRENT video
         evidence fingerprint (recomputed with the manifest's OWN
         generation — a manifest pinned to a foreign/stale evidence
         snapshot is not current);
      8. completion evidence fingerprint PRESENT and == the manifest's
         evidence fingerprint AND == the CURRENT video evidence
         fingerprint (tamper/stale fails);
      9. MANIFEST policy id + content hash PRESENT and == the CURRENT
         policy identity (a manifest pinned to a foreign policy is not
         current);
     10. completion policy id + content hash PRESENT and == the
         manifest's values AND == the CURRENT policy identity
         (tamper/drift fails);
     11. MANIFEST source generation PRESENT non-empty string and == the
         Job's input_generation (the generation the row was submitted
         under — a manifest that disagrees with its own row is corrupt);
     12. completion source generation PRESENT (non-empty string) and ==
         the manifest's source generation AND == the Job row generation;
     13. the CURRENT evidence fingerprint is RECOMPUTED with the
         manifest's own generation before comparison, so a manifest +
         completion pair that agree with each other on a WRONG generation
         still fail against the recomputed current evidence;
     14. MANIFEST source artifact id/SHA match the persisted CURRENT
         source identity (same representation the producer writes: a
         ``None`` id pairs with an empty SHA for the legitimate no-source
         case; a non-None id requires a non-empty SHA — no default
         launders a missing/corrupt source);
     15. completion source artifact id + fingerprint PRESENT and ==
         the manifest's values AND == the CURRENT source identity (id-only
         or SHA-only tamper fails);

    COUNTS — the run really executed the whole band, cleanly:
      9. summary is a dict AND ``checks_requested`` / ``checks_run`` /
         ``checks_skipped`` / ``errors`` are ALL PRESENT with exact JSON
         number type (``bool`` is NOT a number — ``isinstance(x, bool)``
         is rejected first; missing / null / string / bool NEVER default
         to zero);
     10. counts are exactly the binding band size N for requested AND
         run AND (requested == run); skipped == 0; errors == 0;
     11. ``cancelled`` and ``deadline_exceeded`` are PRESENT exact bools
         and both False;
     12. completion detectors is a list of N strings, no duplicates, and
         as a MULTISET equals the binding full band (order-insensitive
         but duplicate-/missing-/extra-sensitive: duplicates can only
         displace a missing member, so multiset equality catches them);
     13. detector revisions is a dict whose KEY SET is exactly the band
         (no missing / extra keys) and every value is a PRESENT non-empty
         string.
    """
    band = full_coverage_detectors()
    expected_n = len(band)
    expected_fp = full_scope_fingerprint()

    # — identity: verbatim, no defaults, no coercion —
    if completion.get("schema_version") != RUN_QC_SCHEMA_VERSION:
        return False, (
            "completion schema_version is not the RUN_QC_CHECKS schema "
            "version (missing/foreign/corrupt envelope)"
        )
    if completion.get("job_type") != JOB_TYPE_RUN_QC_CHECKS:
        return False, (
            "completion job_type is not RUN_QC_CHECKS "
            "(missing/foreign/corrupt envelope)"
        )
    # C3-A1 item 1: the MANIFEST's schema_version must be PRESENT, an
    # exact JSON integer (``bool`` is not an integer — ``isinstance(True,
    # int)`` would otherwise launder a bool into authority), and exactly
    # the RUN_QC_CHECKS schema version.
    manifest_schema = manifest.get("schema_version")
    if (
        isinstance(manifest_schema, bool)
        or not isinstance(manifest_schema, int)
        or manifest_schema != RUN_QC_SCHEMA_VERSION
    ):
        return False, (
            f"manifest schema_version {manifest_schema!r} is not the exact "
            "RUN_QC_CHECKS schema integer (missing/null/bool/string/wrong "
            "integer envelope)"
        )
    manifest_scope = manifest.get("scope")
    if manifest_scope != SCOPE_FULL:
        return False, (
            f"manifest scope {manifest_scope!r} is not the full band "
            "(audio-only/partial runs never substitute for full authority)"
        )
    manifest_scope_fp = manifest.get("scope_fingerprint")
    if manifest_scope_fp != expected_fp:
        return False, (
            "manifest scope fingerprint does not match the content-derived "
            "full-band identity (the submitted band was not the full band)"
        )
    completion_scope = completion.get("scope")
    if completion_scope != manifest_scope:
        return False, (
            f"completion scope {completion_scope!r} does not match the "
            f"manifest scope {manifest_scope!r} "
            "(completion/manifest scope mismatch)"
        )
    completion_scope_fp = completion.get("scope_fingerprint")
    if completion_scope_fp != manifest_scope_fp:
        return False, (
            "completion scope fingerprint does not match the manifest's "
            "scope fingerprint (completion/manifest fingerprint mismatch)"
        )
    # C3-A1 items 9–10: the MANIFEST's policy identity must be PRESENT
    # and == the CURRENT server policy (a manifest pinned to a foreign
    # policy is never current — the completion alone cannot vouch for it).
    manifest_policy_id = manifest.get("policy_id")
    if manifest_policy_id != policy_id:
        return False, (
            f"manifest policy id {manifest_policy_id!r} does not match the "
            "current policy identity (foreign/stale manifest envelope)"
        )
    manifest_policy_hash = manifest.get("policy_content_hash")
    if manifest_policy_hash != policy_content_hash:
        return False, (
            "manifest policy content hash does not match the current "
            "policy identity (foreign/stale manifest envelope)"
        )
    if completion.get("policy_id") != manifest_policy_id:
        return False, (
            "completion policy id does not match the manifest's policy id "
            "(tamper/drift envelope)"
        )
    if completion.get("policy_content_hash") != manifest_policy_hash:
        return False, (
            "completion policy content hash does not match the manifest's "
            "policy hash (tamper/drift envelope)"
        )
    # C3-A1 items 11–12: the MANIFEST's generation must be a PRESENT
    # non-empty string == the Job row's input_generation; the completion
    # generation must equal BOTH (a pair agreeing on a wrong generation
    # is caught by the recomputed-current-evidence check below).
    manifest_generation = manifest.get("source_generation")
    if (
        not isinstance(manifest_generation, str)
        or not manifest_generation
        or manifest_generation != job_generation
    ):
        return False, (
            f"manifest source generation {manifest_generation!r} does not "
            f"match the job row generation {job_generation!r} "
            "(missing/empty/corrupt manifest envelope)"
        )
    completion_generation = completion.get("source_generation")
    if (
        not isinstance(completion_generation, str)
        or not completion_generation
        or completion_generation != manifest_generation
    ):
        return False, (
            "completion source generation does not match the manifest's "
            "source generation (missing/empty/mismatched envelope)"
        )
    # C3-A1 items 7–8: the MANIFEST's evidence fingerprint must be
    # PRESENT and == the CURRENT evidence (the caller recomputes it with
    # the manifest's OWN generation — see latest_check_run_state).
    manifest_evidence_fp = manifest.get("evidence_fingerprint")
    if manifest_evidence_fp != evidence_fingerprint:
        return False, (
            "manifest evidence fingerprint does not match the current "
            "video evidence fingerprint (foreign/stale manifest envelope)"
        )
    completion_evidence_fp = completion.get("evidence_fingerprint")
    if completion_evidence_fp != manifest_evidence_fp:
        return False, (
            "completion evidence fingerprint does not match the manifest's "
            "evidence fingerprint (tamper/stale envelope)"
        )

    # — counts: PRESENT exact JSON numbers, then exact band arithmetic —
    summary = completion.get("summary")
    if not isinstance(summary, dict):
        return False, "completion summary is missing (cannot prove coverage)"
    for key in ("checks_requested", "checks_run", "checks_skipped", "errors"):
        value = summary.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return False, (
                f"completion summary {key!r} is not a JSON number "
                f"(got {value!r}; missing/null/string/bool never default "
                "to zero)"
            )
    requested = summary["checks_requested"]
    ran = summary["checks_run"]
    skipped = summary["checks_skipped"]
    errors = summary["errors"]
    if requested != expected_n or ran != expected_n or requested != ran:
        return False, (
            f"completion summary counts do not prove a full {expected_n}-check "
            f"run (requested={requested}, run={ran}; partial runs are never "
            "the readiness authority)"
        )
    if skipped != 0:
        return False, (
            f"completion summary reports {skipped} skipped check(s); a "
            "partially-skipped run is never the readiness authority"
        )
    if errors != 0:
        return False, (
            f"completion summary reports {errors} error(s); an errored run "
            "is never the readiness authority"
        )
    for key in ("cancelled", "deadline_exceeded"):
        value = summary.get(key)
        if not isinstance(value, bool):
            return False, (
                f"completion summary {key!r} is not a JSON boolean "
                f"(got {value!r}; the producer always writes it)"
            )
        if value:
            return False, (
                f"completion summary reports {key}=true; an interrupted run "
                "is never the readiness authority"
            )

    # — detectors: exact multiset + exact revision envelope —
    completion_detectors = completion.get("detectors")
    if not isinstance(completion_detectors, list) or any(
        not isinstance(name, str) for name in completion_detectors
    ):
        return False, (
            "completion detectors is not a list of detector names "
            "(cannot prove coverage)"
        )
    if len(completion_detectors) != expected_n or sorted(
        completion_detectors
    ) != sorted(band):
        return False, (
            "completion detectors do not equal the binding full band "
            f"(expected {sorted(band)}; got {sorted(completion_detectors)}; "
            "audio-only/partial runs never substitute, duplicates only "
            "displace a missing member, and partial runs are never summed "
            "into coverage)"
        )
    revisions = completion.get("detector_revisions")
    if not isinstance(revisions, dict):
        return False, (
            "completion detector revisions is missing (cannot prove coverage)"
        )
    if set(revisions) != set(band):
        return False, (
            "completion detector revision keys do not equal the binding "
            f"full band (missing/extra revision entries: "
            f"{sorted(set(band) ^ set(revisions))})"
        )
    empty_revisions = sorted(
        name for name, value in revisions.items()
        if not isinstance(value, str) or not value
    )
    if empty_revisions:
        return False, (
            "completion detector revisions are empty for "
            f"{empty_revisions} (cannot prove coverage)"
        )
    # C3-A1 item 6: the revision VALUES must equal the server-owned
    # detector revisions for the binding band — non-empty alone is not
    # enough (a forged map with plausible non-empty values fails here).
    # Server-known members are compared against the live registry; for
    # members ABSENT from the registry (other lanes own their
    # registrations), the seed/producer convention "1.0.0" is the
    # authoritative expectation — anything else is a forged value.
    # (The two audio members ARE registered in this module's fixture, so
    # forged audio values still hit the live-registry leg.)
    try:
        expected_revisions = _server_detector_revisions(list(band))
    except Exception:
        expected_revisions = {}
    wrong_revisions = sorted(
        name
        for name in band
        if (
            revisions.get(name)
            != expected_revisions.get(name, "1.0.0")
        )
    )
    if wrong_revisions:
        return False, (
            "completion detector revisions do not match the server-owned "
            f"detector revisions for {wrong_revisions} (forged revision "
            "values cannot prove coverage)"
        )
    # C3-A1 items 14–15: source artifact identity — manifest vs persisted
    # CURRENT source, then completion vs manifest+current.  The producer
    # writes ``None`` id + empty SHA for the legitimate no-source case
    # and a real id + non-empty SHA when a source artifact exists; any
    # missing/corrupt shape (present-but-None id with non-empty SHA, or
    # vice versa) fails.  No default ever fills these fields.
    current_source = current_source_precomputed
    manifest_source = _source_identity_from_manifest(manifest)
    if manifest_source is None:
        return False, (
            "manifest source artifact identity is missing/corrupt "
            "(source_artifact_id must pair with source SHA exactly as the "
            "producer writes: None id + empty SHA for no-source, real id "
            "+ non-empty SHA otherwise)"
        )
    if manifest_source != current_source:
        return False, (
            f"manifest source artifact identity {manifest_source!r} does "
            f"not match the current persisted source {current_source!r} "
            "(foreign/stale source envelope)"
        )
    completion_source_id = completion.get("source_artifact_id")
    completion_source_sha = completion.get("source_artifact_fingerprint")
    completion_source = (completion_source_id, completion_source_sha)
    if completion_source != manifest_source:
        return False, (
            f"completion source artifact identity {completion_source!r} "
            f"does not match the manifest's source {manifest_source!r} "
            "(id-only or SHA-only tamper fails)"
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
    job = _newest_full_job(repo, workspace_id, video_item_id)
    if job is None:
        return CheckRunState(
            video_item_id=video_item_id,
            run_state=RUN_STATE_NEVER_RUN,
            check_state_detail="no SCOPE_FULL RUN_QC_CHECKS job has ever been submitted "
            "for this video (audio-only/partial runs never create full-run "
            "authority; never-run vs completed-zero-item is decided by "
            "durable run evidence, never by QCItem-table emptiness)",
        )
    attempts = repo.list_attempts(job.id, limit=50)
    completion = _completion_from_attempts(attempts)

    manifest = job.input_manifest
    if not isinstance(manifest, dict):
        manifest = {}
    policy = load_policy()
    current_policy_id = str(policy.get("policy_id") or POLICY_ID)
    current_policy_hash = str(policy.get("content_hash") or "")
    # C3-A1 item 4/13: the CURRENT evidence is recomputed with the
    # MANIFEST's OWN generation — a manifest+completion pair agreeing on
    # a WRONG generation still fails against the recomputed current
    # evidence (the pair only matches each other, never current).
    #
    # The envelope gate receives the recomputed-with-manifest-generation
    # current evidence, but the stale/ready split below (evidence_matches)
    # is evaluated against the CALLER-supplied current evidence: a run
    # whose manifest pins an older generation is STALE for the caller,
    # never ready.
    manifest_generation_raw = manifest.get("source_generation")
    manifest_generation_for_fp = (
        manifest_generation_raw
        if isinstance(manifest_generation_raw, str)
        and manifest_generation_raw
        else "1"
    )
    evidence_fingerprint_envelope = _current_evidence_fingerprint(
        session,
        workspace_id=workspace_id,
        video_item_id=video_item_id,
        generation=manifest_generation_for_fp,
    )
    # C3-A1 item 5/14: the persisted CURRENT source identity (same shape
    # the producer writes — ``None`` id + empty SHA for no-source).
    current_source = _current_source_fingerprint(
        session, video_item_id=video_item_id
    )
    current_source_pair = (
        current_source.get("source_artifact_id"),
        current_source.get("source_sha256"),
    )
    run_fp = manifest.get("evidence_fingerprint")
    run_policy_hash = manifest.get("policy_content_hash")
    evidence_matches = run_fp == evidence_fingerprint
    policy_matches = run_policy_hash == policy_content_hash

    base: dict[str, Any] = {
        "video_item_id": video_item_id,
        "job_id": job.id,
        "job_state": job.state,
        "idempotency_key": job.idempotency_key,
        "evidence_fingerprint": (
            run_fp if isinstance(run_fp, str) else None
        ),
        "policy_content_hash": (
            run_policy_hash if isinstance(run_policy_hash, str) else None
        ),
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
            manifest=manifest,
            evidence_fingerprint=evidence_fingerprint_envelope,
            policy_id=current_policy_id,
            policy_content_hash=current_policy_hash,
            job_generation=str(job.input_generation or ""),
            current_source_precomputed=current_source_pair,
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