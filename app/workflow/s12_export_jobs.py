"""S12-T03C — durable S12 export job type + reconciler (s12-export-v1 §6).

Consumes read-only (frozen, never rewritten here):
- ``app/persistence/s12_export.py`` (T03A) — run/lease rows own ALL export
  state (``create_run`` / ``claim_run`` / ``transition_run`` /
  ``heartbeat_lease`` / ``release_lease``).  This module never issues raw
  SQL against export tables and never mutates a row except through those
  fenced methods.
- ``app/persistence/jobs.py`` (S02) — the durable ``Job`` queue owns job
  lifecycle (``create_job`` / ``create_successor`` / ``transition_job``).
  Submission goes through ``JobService.create_job``; the reconciler below
  only releases *expired* export leases so a fresh claim can resume from
  the T03B checkpoint — it never completes, fails, or rewrites a run.
- ``app/services/s12_export/runner.py`` (T03B) — chunk render / resume /
  assemble.  The handler never marks the run ``completed`` and never
  publishes (T03C publication owns that in a later file).

Crash safety: a crash leaves ``pending``/``running`` rows + ``.partial``
scratch only — resume re-renders them, never accepts them as completed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

__all__ = [
    "S12_EXPORT_JOB_TYPE",
    "S12ExportSubmitError",
    "S12ExportLineageError",
    "submit_export_job",
    "submit_retry_export_job",
    "register_s12_export_handler",
    "reconcile_export_jobs",
]

#: Stable durable job-type code for S12 export render work.
S12_EXPORT_JOB_TYPE = "s12_export"


class S12ExportSubmitError(ValueError):
    """Fail-closed submission error (stale pins, missing authority)."""


class S12ExportLineageError(S12ExportSubmitError):
    """Typed denial for malformed durable retry lineage."""

    code = "S12_EXPORT_INVALID_LINEAGE"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


# ── MF-END-26: export-gate refusal + server-owned original audio ────────────
#
# Every S12 export leg CONSUMES the additive ``mf-end-23/export-gate@1``
# report (``app/persistence/readiness.py``) through the preflight's ONE
# consumption contract — no second gate is defined here.  Uniform rule: a
# gate verdict of ``blocked`` refuses the export at submit, at retry and at
# PRE-PUBLISH.  ``not_run`` (no completed CURRENT full-scope QC run at all)
# is owned by the readiness authority every leg already consumes; it is
# never duplicated.
#
# Audio (26.1/26.2): the stitch's audio source is SERVER-OWNED — resolved
# from the SAME completed-publication artifact the export renders from and
# probed for real (codec / sample-rate / channels / exact duration /
# timebase) before it is recorded in the run manifest.  A source without an
# audio stream stays honestly silent — no audio is ever fabricated.

#: Gate video status meaning "no completed CURRENT full-scope run exists".
_GATE_VIDEO_NOT_RUN = "not_run"


def export_gate_refusal(
    session: Any,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> str | None:
    """Typed refusal message when the MF-END-23 gate is BLOCKED, else None.

    Read-only.  Only an EXPLICIT gate verdict of ``blocked`` refuses; a
    ``not_run`` verdict (no completed CURRENT full-scope run) is owned by the
    readiness authority every leg already consumes, and a gate that cannot be
    resolved (environment/runtime-root guard, unreadable rows) is NOT turned
    into a fabricated refusal here — the preflight authority check still
    fails closed on it (``resolve_export_authority``), and the standing
    readiness/source contract keeps gating the submit/publish legs.
    """
    from app.persistence.readiness import compute_export_gate  # noqa: PLC0415
    from app.services.s12_export.preflight import (  # noqa: PLC0415
        export_gate_consumption,
    )

    try:
        record = compute_export_gate(
            session, workspace_id=workspace_id, project_id=project_id
        )
    except Exception:  # noqa: BLE001 — no verdict: readiness authority owns it
        return None
    verdict = export_gate_consumption(record, video_item_id)
    if verdict.passed or verdict.video_status == _GATE_VIDEO_NOT_RUN:
        return None
    return f"{verdict.reason}: {verdict.detail}"


def resolve_original_audio_source(
    source_path: str | Path,
) -> tuple[str | None, dict[str, Any]]:
    """Server-owned original-audio resolution for the export stitch (26.2).

    Probes the export source (the completed Full Apply publication artifact —
    the SAME artifact the chunks render from) through the original-audio
    remux engine's bounded probe.  Returns ``(audio_path_or_None,
    provenance)``: the path is the source itself (the stitch remuxes its
    canonical first audio stream once onto the stitched timeline), and the
    provenance records the measured shape for the run manifest.
    """
    from app.services.original_audio_remux import (  # noqa: PLC0415
        OriginalAudioRemuxError,
        probe_original_audio,
    )

    base: dict[str, Any] = {"source": "completed_publication_artifact"}
    try:
        probe = probe_original_audio(source_path)
    except OriginalAudioRemuxError as exc:
        return None, {**base, "mode": "absent", "reason": f"probe failed closed: {exc.code}"}
    except Exception as exc:  # noqa: BLE001 — never crash the submit leg
        return None, {
            **base,
            "mode": "absent",
            "reason": f"probe error: {type(exc).__name__}",
        }
    if not probe.present:
        return None, {**base, "mode": "absent", "detail": probe.detail}
    return str(source_path), {
        **base,
        "mode": "source_remux",
        "codec": probe.codec,
        "sample_rate": probe.sample_rate,
        "channels": probe.channels,
        "duration": probe.duration,
        "time_base": probe.time_base,
        "stream_index": probe.stream_index,
        "container": probe.container,
    }


# ── Durable Job discovery / classification (R6 F01 union identity) ───────
#
# ONE discovery/classification contract resolves which durable Job (if
# any) actually claims an export Run.  The claim set is a UNION gathered
# BEFORE any scope/type filter: (a) the run's own durable pointer, (b) the
# canonical key ``s12_export_job:{run.id}`` in ANY workspace, (c) any Job
# whose ``input_manifest_json.run_id`` is this run (ANY key/workspace),
# and (d) relevant generation/owner evidence.  A Job that still carries
# the manifest run identity claims the run even when its key or workspace
# was changed — such a claimant is never filtered away.  Equal
# ``input_generation`` alone is NOT a unique Run identity: valid retry
# attempts legitimately share ``run.plan_hash``, so generation/owner
# evidence only forbids treating a run as a true orphan.


@dataclass(frozen=True)
class _JobClaim:
    """One durable Job observed while resolving a run's claimed Job."""

    job: Any
    sources: tuple[str, ...]
    problems: tuple[str, ...]


def _parse_job_claim_manifest(job: Any) -> dict[str, Any]:
    """Parse a candidate Job's input manifest, failing closed on corruption."""
    try:
        payload = json.loads(getattr(job, "input_manifest_json", None) or "")
    except (TypeError, ValueError) as err:
        raise S12ExportSubmitError(
            f"durable Job {getattr(job, 'id', None)!r} has malformed input "
            "manifest JSON; refusing (fail closed)"
        ) from err
    if not isinstance(payload, dict):
        raise S12ExportSubmitError(
            f"durable Job {getattr(job, 'id', None)!r} input manifest is not "
            "a JSON object; refusing (fail closed)"
        )
    return payload


def _run_job_claim_problems(run: Any, job: Any) -> tuple[str, ...]:
    """Identity problems of *job* as a claim on *run* (empty == valid claim).

    Mirrors the durable ``bind_job`` contract: workspace, job type, owner,
    canonical key, pinned generation, the full manifest run identity and
    every present immutable lineage field must agree.  Unparseable
    manifests raise (fail closed) instead of being classified.
    """
    problems: list[str] = []
    canonical_key = f"s12_export_job:{run.id}"
    if str(job.workspace_id) != str(run.workspace_id):
        problems.append(f"workspace {job.workspace_id!r} != {run.workspace_id!r}")
    if job.job_type != S12_EXPORT_JOB_TYPE:
        problems.append(f"job_type {job.job_type!r}")
    if job.owner_type != "project" or str(job.owner_id) != str(run.project_id):
        problems.append(f"owner {job.owner_type!r}/{job.owner_id!r}")
    if job.idempotency_key != canonical_key:
        problems.append(f"canonical key {job.idempotency_key!r} != {canonical_key!r}")
    if str(job.input_generation) != str(run.plan_hash):
        problems.append("generation mismatch")
    manifest = _parse_job_claim_manifest(job)
    for key, expected in (
        ("run_id", run.id),
        ("workspace_id", run.workspace_id),
        ("project_id", run.project_id),
        ("video_item_id", run.video_item_id),
        ("plan_hash", run.plan_hash),
        ("checkpoint_hash", run.checkpoint_hash),
    ):
        if str(manifest.get(key)) != str(expected):
            problems.append(f"manifest {key} mismatch")
    optional_identity = {
        "manifest_id": run.manifest_id,
        "manifest_generation": run.manifest_generation,
        "lineage_id": run.lineage_id,
        "predecessor_run_id": run.predecessor_run_id,
        "attempt": run.attempt,
    }
    for key, expected in optional_identity.items():
        if key in manifest and manifest[key] != expected:
            problems.append(f"manifest {key} mismatch")
    if "chunk_config" in manifest:
        try:
            stored_chunk_config = json.loads(run.chunk_config_json)
        except (TypeError, ValueError) as err:
            raise S12ExportSubmitError(
                f"export run {run.id!r} has corrupt chunk configuration"
            ) from err
        if manifest["chunk_config"] != stored_chunk_config:
            problems.append("manifest chunk_config mismatch")
    return tuple(problems)


def _manifest_sibling_proof(session: Any, job: Any, manifest: dict[str, Any]) -> bool:
    """True only when the manifest names another run that OWNS this Job.

    Sibling attribution requires PROOF (reviewer F02): the referenced run
    must exist and its durable pointer must be this exact Job.  A manifest
    run reference that is absent, names a nonexistent run, or names a run
    that does not own the Job proves nothing — the candidate stays
    unresolved and the caller must fail closed.
    """
    from app.persistence.models import S12ExportRun  # noqa: PLC0415

    referenced_run_id = str(manifest.get("run_id") or "")
    if not referenced_run_id:
        return False
    referenced = session.get(S12ExportRun, referenced_run_id)
    if referenced is None:
        return False
    return str(referenced.job_id or "") == str(job.id)


def _weak_generation_candidates(session: Any, run: Any) -> list[Any]:
    """Relevant unresolved Job evidence that forbids orphan repair.

    Discovery deliberately does NOT trust ``job_type`` / ``workspace_id`` /
    ``owner_id`` / key fields before classification — any of them may be
    the corrupted field (reviewer F02).  Every Job whose pinned generation
    matches the run's plan is a candidate regardless of those fields.  A
    candidate is excluded only with the proof of
    :func:`_manifest_sibling_proof` (valid retry chains legitimately share
    ``plan_hash``); everything else is unresolved relevant evidence, and
    the caller refuses to treat this run as a true zero-Job orphan.
    """
    from app.persistence.models import Job as JobRow  # noqa: PLC0415

    rows = session.scalars(
        select(JobRow).where(JobRow.input_generation == run.plan_hash)
    )
    weak: list[Any] = []
    for job in rows:
        manifest = _parse_job_claim_manifest(job)
        if _manifest_sibling_proof(session, job, manifest):
            continue  # proven: an existing run's durable pointer owns it
        weak.append(job)
    return weak


def _resolve_run_durable_job(session: Any, run: Any) -> Any | None:
    """Union discovery + classification of the durable Job claiming *run*.

    Returns the single VALID claimant Job row, or ``None`` when the run is
    a true zero-Job orphan (repair allowed exactly once by the caller).
    Typed denials (:class:`S12ExportSubmitError`, zero mutation) are raised
    for contradictory or ambiguous claimants, unresolved relevant
    candidates, a dangling run pointer, and every read/parse failure.  The
    SAME contract serves initial replay, retry preparation and fresh
    commit reconciliation (enqueue/bind/commit/lost-ack).
    """
    from app.persistence.models import Job as JobRow  # noqa: PLC0415
    from app.persistence.models import S12ExportRun  # noqa: PLC0415

    run_row = session.get(S12ExportRun, str(getattr(run, "id", run)))
    if run_row is None:
        raise S12ExportSubmitError(f"export run {run!r} not found")
    run_id = str(run_row.id)
    canonical_key = f"s12_export_job:{run_id}"
    claims: dict[str, dict[str, Any]] = {}

    def _add(job: Any, source: str) -> None:
        entry = claims.setdefault(str(job.id), {"job": job, "sources": []})
        if source not in entry["sources"]:
            entry["sources"].append(source)

    # (a) the run's own durable pointer.
    if run_row.job_id is not None:
        pointed = session.get(JobRow, str(run_row.job_id))
        if pointed is None:
            raise S12ExportSubmitError(
                f"export run {run_id!r} durable Job pointer "
                f"{run_row.job_id!r} has no Job row (corrupt pointer)"
            )
        _add(pointed, "pointer")
    # (b) the canonical key — ANY workspace (cross-scope claimants are
    #     denied by classification, never filtered away).
    for job in session.scalars(
        select(JobRow).where(JobRow.idempotency_key == canonical_key)
    ):
        _add(job, "key")
    # (c) the manifest run identity — ANY key/workspace.  The raw substring
    #     is only a pre-filter; the deciding value is always the SEMANTIC
    #     manifest ``run_id`` (``json.loads`` handles \uXXXX-escaped and
    #     reformatted JSON that a raw byte match would miss).
    for job in session.scalars(
        select(JobRow).where(
            JobRow.input_manifest_json.contains(run_id, autoescape=True)
        )
    ):
        if str(_parse_job_claim_manifest(job).get("run_id") or "") == run_id:
            _add(job, "manifest")
    # (d) semantic manifest claims discovered through the pinned-generation
    #     union (ANY type/workspace/owner/key): a Job that semantically
    #     names this run is a claimant even when its raw bytes were escaped
    #     or reformatted, and it must be classified — never assumed absent.
    for job in session.scalars(
        select(JobRow).where(JobRow.input_generation == run_row.plan_hash)
    ):
        if str(job.id) in claims:
            continue
        if str(_parse_job_claim_manifest(job).get("run_id") or "") == run_id:
            _add(job, "generation")

    valid: list[Any] = []
    contradictory: list[tuple[Any, tuple[str, ...]]] = []
    for entry in claims.values():
        problems = _run_job_claim_problems(run_row, entry["job"])
        if problems:
            contradictory.append((entry["job"], problems))
        else:
            valid.append(entry["job"])
    if contradictory:
        job, problems = contradictory[0]
        raise S12ExportSubmitError(
            f"S12_EXPORT_JOB_IDENTITY_CONTRADICTION: run {run_id!r} has a "
            f"contradictory durable Job claimant {job.id!r} "
            f"({'; '.join(problems)}); refusing with zero mutation"
        )
    if len(valid) > 1:
        raise S12ExportSubmitError(
            f"S12_EXPORT_JOB_IDENTITY_AMBIGUOUS: run {run_id!r} resolves to "
            f"{len(valid)} durable Job claimants "
            f"({', '.join(sorted(str(j.id) for j in valid))}); refusing "
            "first-match"
        )
    if len(valid) == 1:
        return valid[0]
    # (e) unresolved relevant generation evidence forbids orphan repair
    #     (a contradictory or unresolved claimant cannot become an orphan).
    weak = _weak_generation_candidates(session, run_row)
    if weak:
        raise S12ExportSubmitError(
            f"S12_EXPORT_JOB_IDENTITY_UNRESOLVED: run {run_id!r} has "
            f"{len(weak)} unresolved relevant Job candidate(s) "
            f"({', '.join(sorted(str(j.id) for j in weak))}) with "
            "generation/owner evidence but no canonical or manifest claim; "
            "refusing orphan repair"
        )
    return None


def submit_export_job(
    job_service: Any,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    checkpoint_id: str,
    checkpoint_hash: str,
    checkpoint_revision: int,
    manifest_id: str,
    manifest_hash: str,
    manifest_generation: str,
    profile_id: str,
    plan_id: str,
    plan_hash: str,
    frame_count: int,
    chunk_config: dict[str, Any],
    source_path: str,
    fps: float,
    chunk_dir: str,
    scratch_dir: str,
    output_path: str,
    audio_source: str | None = None,
    idempotency_key: str | None = None,
    natural_key: str | None = None,
    priority: int = 50,
    expected_sha256: str | None = None,
    fps_num: int = 0,
    fps_den: int = 0,
) -> tuple[Any, Any, bool]:
    """Pin the export run (T03A, idempotent) and enqueue its durable job.

    Returns ``(run, job, created)`` — ``created=False`` on idempotent
    replay of the same lineage (the existing run + its job are returned,
    never a duplicate successor).  The HTTP request never renders: it
    only commits the ``pending`` run row and the ``queued`` job row.
    """
    from app.persistence.jobs import JobRepository  # noqa: PLC0415
    from app.persistence.models import S12ExportRun  # noqa: PLC0415
    from app.persistence.s12_export import (  # noqa: PLC0415
        S12ExportRepository,
        StaleIdentityError,
    )

    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        raise S12ExportSubmitError("job service has no session factory")
    if fps <= 0:
        raise S12ExportSubmitError("fps must be > 0")
    if frame_count < 1:
        raise S12ExportSubmitError("frame_count must be >= 1")

    # 26.1/26.2 — the stitch's audio source is SERVER-OWNED: resolved from
    # the same completed-publication artifact the export renders from and
    # probed before it enters the manifest (never a loose/client file).
    audio_value: str | None
    audio_provenance: dict[str, Any]
    if audio_source:
        audio_value = str(audio_source)
        audio_provenance = {
            "mode": "explicit",
            "source": "caller-supplied (legacy compatibility)",
        }
    else:
        audio_value, audio_provenance = resolve_original_audio_source(source_path)

    with factory() as session:
        # 26.3 — the MF-END-23 export gate is consumed BEFORE any mutation:
        # a BLOCKED gate refuses the (re)enqueue with a typed message and
        # zero rows written.
        refusal = export_gate_refusal(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        if refusal is not None:
            session.rollback()
            raise S12ExportSubmitError(refusal)
        repo = S12ExportRepository(session)
        try:
            run, created = repo.create_run(
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                checkpoint_id=checkpoint_id,
                checkpoint_hash=checkpoint_hash,
                checkpoint_revision=checkpoint_revision,
                manifest_id=manifest_id,
                manifest_hash=manifest_hash,
                manifest_generation=manifest_generation,
                profile_id=profile_id,
                plan_id=plan_id,
                plan_hash=plan_hash,
                frame_count=frame_count,
                chunk_config=dict(chunk_config),
                idempotency_key=idempotency_key,
                natural_key=natural_key,
            )
        except StaleIdentityError as err:
            session.rollback()
            raise S12ExportSubmitError(str(err)) from err
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run.id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "profile_id": profile_id,
            "plan_hash": plan_hash,
            "checkpoint_hash": checkpoint_hash,
            "frame_count": frame_count,
            "source_path": source_path,
            "fps": float(fps),
            "chunk_dir": chunk_dir,
            "scratch_dir": scratch_dir,
            "output_path": output_path,
            "audio_source": audio_value,
            "audio_provenance": audio_provenance,
            "max_frames_per_chunk": int(chunk_config.get("max_frames", 120)),
            "overlap_frames": int(chunk_config.get("overlap", 4)),
            # MF-END-26: the caller-supplied ``expected_sha256`` is the
            # APPROVED-ARTIFACT identity (source reference), NEVER a
            # pre-render OUTPUT identity.  The S12 assembly re-encodes
            # (stitch + AAC), so the validator's output identity must be the
            # server-MEASURED candidate sha (psnr mode); asserting the source
            # sha as the output sha made every re-encoded export fail the
            # ``provenance`` probe (typed FAIL, retryable).  The approved sha
            # is kept under its own audit key.
            "expected_sha256": None,
            "authority_sha256": None,
            "approved_artifact_sha256": str(expected_sha256 or ""),
            "fps_num": int(fps_num),
            "fps_den": int(fps_den),
        }
        job_key = f"s12_export_job:{run.id}"
        if not created:
            # Existing run: resolve the durable pair through the SAME union
            # discovery/classification contract used by retry preparation
            # and commit reconciliation (R6 F01).  Exactly one valid
            # claimant replays (a missing pointer is restored once); a true
            # zero-Job orphan is repaired exactly once; contradictory,
            # ambiguous or unresolved identity denies with zero mutation.
            try:
                claimant = _resolve_run_durable_job(session, run)
                if claimant is None:
                    repaired_job, bound_run = _enqueue_and_bind_job(
                        job_service,
                        factory=factory,
                        run=run,
                        manifest=manifest,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        job_key=job_key,
                        input_generation=plan_hash,
                        priority=int(priority),
                    )
                    session.rollback()
                    return bound_run, repaired_job, False
                run_row = session.get(S12ExportRun, str(run.id))
                pointer_was_missing = run_row is None or run_row.job_id is None
                job_record = JobRepository(session).get_job(str(claimant.id))
                repo.bind_job(run.id, str(claimant.id))
                replay_job = job_service._job_info(job_record)
                if pointer_was_missing:
                    # Repair-once: a restored durable pointer must persist.
                    session.commit()
                else:
                    # Ordinary replay is read-only.
                    session.rollback()
            except S12ExportSubmitError:
                session.rollback()
                raise
            except Exception as err:
                session.rollback()
                raise S12ExportSubmitError(
                    f"existing export Run/Job replay failed closed: {err}"
                ) from err
            return run, replay_job, False
        # Commit the run BEFORE opening the second writer for the job —
        # one SQLite writer at a time (S10-C10 precedent).
        try:
            session.commit()
        except Exception as err:
            session.rollback()
            raise S12ExportSubmitError(f"export run commit failed: {err}") from err

    job, run = _enqueue_and_bind_job(
        job_service,
        factory=factory,
        run=run,
        manifest=manifest,
        workspace_id=workspace_id,
        project_id=project_id,
        job_key=job_key,
        input_generation=plan_hash,
        priority=int(priority),
    )
    return run, job, created


def submit_retry_export_job(
    job_service: Any,
    *,
    predecessor_run_id: str,
    workspace_id: str,
    project_id: str,
    source_path: str,
    fps: float,
    chunk_dir: str,
    scratch_dir: str,
    output_path: str,
    expected_sha256: str | None = None,
    audio_source: str | None = None,
    fps_num: int = 0,
    fps_den: int = 0,
    priority: int = 50,
) -> tuple[Any, Any, bool]:
    """Append one successor and its Job in one durable transaction."""
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    from app.persistence import StepInput  # noqa: PLC0415
    from app.persistence.jobs import IdempotencyKeyInUse, JobRepository  # noqa: PLC0415
    from app.persistence.models import S12ExportRun  # noqa: PLC0415
    from app.persistence.s12_export import (  # noqa: PLC0415
        IdempotencyConflictError,
        InvalidLineageError,
        S12ExportError,
        S12ExportRepository,
    )

    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        raise S12ExportSubmitError("job service has no session factory")
    key = f"s12_retry:{predecessor_run_id}"

    def make_manifest(run: Any) -> dict[str, Any]:
        try:
            chunk_config = json.loads(run_chunk_config(run))
        except (TypeError, ValueError) as err:
            raise S12ExportSubmitError(
                "retry predecessor has corrupt chunk configuration"
            ) from err
        if not isinstance(chunk_config, dict):
            raise S12ExportSubmitError("retry predecessor has invalid chunk configuration")
        return {
            "schema_version": 1,
            "managed_root": str(getattr(job_service, "managed_root", "")),
            "run_id": run.id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": run.video_item_id,
            "profile_id": run.profile_id,
            "plan_hash": run.plan_hash,
            "checkpoint_hash": run.checkpoint_hash,
            "frame_count": run.frame_count,
            "source_path": source_path,
            "fps": float(fps),
            "chunk_dir": chunk_dir,
            "scratch_dir": scratch_dir,
            "output_path": output_path,
            "audio_source": audio_value,
            "audio_provenance": audio_provenance,
            "max_frames_per_chunk": int(chunk_config.get("max_frames", 120)),
            "overlap_frames": int(chunk_config.get("overlap", 4)),
            # MF-END-26: same mapping as the initial submit — the approved
            # artifact sha is audit-only; the output identity is the
            # server-MEASURED candidate sha (psnr mode).
            "expected_sha256": None,
            "authority_sha256": None,
            "approved_artifact_sha256": str(expected_sha256 or ""),
            "fps_num": int(fps_num),
            "fps_den": int(fps_den),
            "manifest_id": run.manifest_id,
            "manifest_generation": run.manifest_generation,
            "lineage_id": run.lineage_id,
            "predecessor_run_id": run.predecessor_run_id,
            "attempt": run.attempt,
            "chunk_config": chunk_config,
        }

    def ensure_pair(session: Any, run: Any, manifest: dict[str, Any]) -> Any:
        """Resolve the run's ONE durable Job under the union contract (R6 F01).

        Same discovery/classification contract as initial replay and fresh
        commit reconciliation: exactly one valid claimant is accepted (a
        missing pointer is restored once); a true zero-Job orphan is
        repaired with exactly one Job creation, converging on a concurrent
        winner; a contradictory, ambiguous or unresolved identity denies
        with zero mutation — a changed key/workspace/manifest claimant is
        never filtered away and never becomes a second Job.
        """
        jobs = JobRepository(session)
        repo = S12ExportRepository(session)
        claimant = _resolve_run_durable_job(session, run)
        if claimant is not None:
            job_record = jobs.get_job(str(claimant.id))
        else:
            try:
                job_record = jobs.create_job(
                    workspace_id=workspace_id,
                    job_type=S12_EXPORT_JOB_TYPE,
                    owner_type="project",
                    owner_id=project_id,
                    input_manifest=manifest,
                    idempotency_key=f"s12_export_job:{run.id}",
                    input_generation=run.plan_hash,
                    priority=int(priority),
                    steps=[StepInput(step_code="run", position=0, step_type="sync")],
                    actor="api",
                )
            except (IdempotencyKeyInUse, IntegrityError) as err:
                # A concurrent creator won the orphan race: converge on the
                # durable winner through the SAME union contract.  The only
                # payload on these paths is the conflicted attempt itself, so
                # a post-flush broken session is safely rolled back and
                # re-resolved from durable truth — never a second Job.
                try:
                    converged = _resolve_run_durable_job(session, run)
                except Exception:
                    session.rollback()
                    converged = _resolve_run_durable_job(session, run)
                if converged is None:
                    raise S12ExportSubmitError(
                        f"retry Job creation conflicted for run {run.id!r} and "
                        f"convergence found no durable claimant: {err}"
                    ) from err
                job_record = jobs.get_job(str(converged.id))
        repo.bind_job(run.id, job_record.id)
        return job_record

    def reconcile_pair() -> tuple[Any, Any, bool]:
        with factory() as session:
            repo = S12ExportRepository(session)
            successor = session.scalar(
                select(S12ExportRun).where(
                    S12ExportRun.predecessor_run_id == predecessor_run_id
                )
            )
            if successor is None:
                raise S12ExportSubmitError(
                    "retry transaction uncertainty resolved to no successor"
                )
            run = repo.get_run(successor.id)
            job_record = ensure_pair(session, run, make_manifest(run))
            session.commit()
            return repo.get_run(run.id), job_service._job_info(job_record), False

    # 26.1/26.2 — retry keeps the predecessor's material audio identity when
    # it was recorded; a legacy predecessor without one gets the server-owned
    # resolution (never a loose/client file).
    audio_value: str | None
    audio_provenance: dict[str, Any]
    if audio_source:
        audio_value = str(audio_source)
        audio_provenance = {
            "mode": "explicit",
            "source": "predecessor manifest (material identity preserved)",
        }
    else:
        audio_value, audio_provenance = resolve_original_audio_source(source_path)

    with factory() as session:
        repo = S12ExportRepository(session)
        # 26.3 — same gate consumption as the initial submit: a BLOCKED gate
        # refuses the retry with a typed message and zero rows written.  The
        # predecessor row supplies the video identity; an unreadable
        # predecessor cannot be retried at all (lineage refusal below).
        try:
            predecessor = repo.get_run(predecessor_run_id)
        except Exception:  # noqa: BLE001 — lineage refusal owns this case
            predecessor = None
        if predecessor is not None:
            refusal = export_gate_refusal(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=str(predecessor.video_item_id),
            )
            if refusal is not None:
                session.rollback()
                raise S12ExportSubmitError(refusal)
        try:
            run, created = repo.create_successor_run(
                predecessor_run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                idempotency_key=key,
            )
            job_record = ensure_pair(session, run, make_manifest(run))
            bound_run = repo.get_run(run.id)
        except InvalidLineageError as err:
            session.rollback()
            raise S12ExportLineageError(str(err)) from err
        except S12ExportSubmitError:
            session.rollback()
            raise
        except (IdempotencyConflictError, S12ExportError) as err:
            session.rollback()
            raise S12ExportSubmitError(str(err)) from err
        except Exception as err:
            # Preparation/query failures did not attempt COMMIT.  They are
            # fail-closed and must never be interpreted as commit uncertainty.
            session.rollback()
            raise S12ExportSubmitError(
                f"retry preparation failed closed: {err}"
            ) from err

        try:
            session.commit()
        except Exception as err:
            # Reconciliation is limited to the one operation whose outcome
            # may be unknown: COMMIT itself.
            session.rollback()
            try:
                return reconcile_pair()
            except S12ExportSubmitError:
                raise
            except Exception as reconcile_err:
                raise S12ExportSubmitError(
                    f"retry commit outcome uncertain: {err}; "
                    f"reconciliation failed: {reconcile_err}"
                ) from reconcile_err
        return bound_run, job_service._job_info(job_record), created


def run_chunk_config(run: Any) -> str:
    """Keep retry config access narrow while accepting immutable RunRecord snapshots."""
    value = getattr(run, "chunk_config_json", None)
    if value is not None:
        return str(value)
    raise S12ExportSubmitError("retry run snapshot omitted chunk configuration")


def _enqueue_and_bind_job(
    job_service: Any,
    *,
    factory: Callable[[], Any],
    run: Any,
    manifest: dict[str, Any],
    workspace_id: str,
    project_id: str,
    job_key: str,
    input_generation: str,
    priority: int,
) -> tuple[Any, Any]:
    try:
        job = job_service.create_job(
            S12_EXPORT_JOB_TYPE,
            manifest,
            workspace_id=workspace_id,
            owner_type="project",
            owner_id=project_id,
            idempotency_key=job_key,
            input_generation=input_generation,
            priority=priority,
        )
    except Exception as err:
        if type(err).__name__ not in ("IdempotencyKeyInUse", "IntegrityError"):
            raise S12ExportSubmitError(f"export job enqueue failed: {err}") from err
        try:
            claimant = _resolve_claim_after_enqueue_conflict(factory, run)
            job = job_service._job_info(claimant)
        except S12ExportSubmitError:
            raise
        except Exception as lookup_err:
            raise S12ExportSubmitError(
                f"export Job replay lookup failed closed: {lookup_err}"
            ) from lookup_err
    job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
    if not job_id:
        raise S12ExportSubmitError("durable Job response omitted its actual job_id")
    try:
        with factory() as session:
            from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415

            bound_run = S12ExportRepository(session).bind_job(run.id, str(job_id))
            session.commit()
    except Exception as err:
        raise S12ExportSubmitError(f"export Job binding failed closed: {err}") from err
    return job, bound_run


def _resolve_claim_after_enqueue_conflict(factory: Callable[[], Any], run: Any) -> Any:
    """Resolve the enqueue-conflict winner through the SAME union contract.

    An ``IdempotencyKeyInUse``/``IntegrityError`` on creation means some
    durable contender exists; it is accepted only when the union discovery
    classifies it as this run's single valid claimant.  Contradictory,
    ambiguous or unresolved identity fails closed — never a first-key-wins
    adoption; query failures propagate to the caller's fail-closed map.
    """
    from app.persistence.jobs import JobRepository  # noqa: PLC0415

    with factory() as session:
        claimant = _resolve_run_durable_job(session, run)
        if claimant is None:
            raise S12ExportSubmitError(
                f"export Job enqueue conflict for run {run.id!r} resolved to "
                "no durable claimant"
            )
        return JobRepository(session).get_job(str(claimant.id))


def _s12_export_handler(ctx: Any) -> dict[str, Any]:
    """Execute one S12 export job: claim → render/resume → PUBLISH.

    Real production publisher (C2 F01): the handler is the ONLY caller of
    :func:`publish_export_run <app.services.s12_export.publication.publish_export_run>`
    on the normal worker path.  The runner assembles a PRIVATE candidate
    under the scratch dir; publication validates it source-locked and, on
    PASS, atomically moves it to the public output and completes the run.
    The durable job completes AFTER the run reached ``completed`` — states
    always agree (M13 closed).

    A restart re-claims the expired lease and resumes from the T03B
    checkpoint.  Failures raise so the durable worker records the failed
    job; the run lands ``failed`` (retryable) when publication rejects.
    """
    from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415
    from app.services.s12_export.publication import (  # noqa: PLC0415
        _publication_receipt_path,
        publish_export_run,
    )
    from app.services.s12_export.runner import (  # noqa: PLC0415
        ExportRunner,
        RunnerConfig,
        cleanup_owned_export_artifacts,
    )

    manifest = ctx.input_manifest
    run_id = str(manifest["run_id"])
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    factory = getattr(ctx, "session_factory", None)
    if factory is None:
        raise RuntimeError("s12 export handler requires a session factory")

    with factory() as session:
        repo = S12ExportRepository(session)
        lease = repo.claim_run(
            run_id,
            ctx.worker_id,
            job_id=getattr(ctx, "job_id", None),
        )
        session.commit()
        claimed_run = repo.get_run(run_id)
        owner_scratch = (
            Path(str(manifest["scratch_dir"]))
            / f"attempt-{claimed_run.attempt}-fence-{lease.fence_token}"
        )
        owned_manifest = dict(manifest)
        owned_manifest["scratch_dir"] = str(owner_scratch)
        owned_manifest["candidate_path"] = str(owner_scratch / "candidate_final.mp4")
        owned_manifest["attempt"] = int(claimed_run.attempt)
        # The runner writes its assembly to a PRIVATE candidate under the
        # server-owned scratch dir — never to the public output (C2 F07).
        candidate_path = _candidate_for(owned_manifest)
        cfg = RunnerConfig(
            run_id=run_id,
            workspace_id=workspace_id,
            worker_id=ctx.worker_id,
            fence_token=lease.fence_token,
            source_path=str(manifest["source_path"]),
            fps=float(manifest["fps"]),
            chunk_dir=str(manifest["chunk_dir"]),
            scratch_dir=str(owner_scratch),
            output_path=str(candidate_path),
            audio_source=manifest.get("audio_source"),
            max_frames_per_chunk=int(manifest.get("max_frames_per_chunk", 120)),
            overlap_frames=int(manifest.get("overlap_frames", 4)),
            extra={
                "fence_token": lease.fence_token,
                "attempt": str(claimed_run.attempt),
            },
        )
        try:
            ExportRunner(repo, cfg).resume()
            session.commit()
            # 26.3 — pre-publish re-check of the MF-END-23 export gate: a
            # gate that turned BLOCKED while the run was queued/rendering
            # must never publish.  The refusal lands the run ``failed``
            # (retryable) and the candidate stays in the PRIVATE scratch —
            # no public output is ever written from a blocked gate.
            refusal = export_gate_refusal(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=str(manifest["video_item_id"]),
            )
            if refusal is not None:
                raise S12ExportSubmitError(f"pre-publish {refusal}")
            outcome = publish_export_run(
                session,
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                worker_id=ctx.worker_id,
                fence_token=lease.fence_token,
                manifest=owned_manifest,
            )
            session.commit()
        except Exception:
            # Coherent states: ordinary render/publication failure lands the
            # run ``failed`` (retryable) under the fence.  An uncertain
            # filesystem/SQLite boundary deliberately remains resumable.
            try:
                rec = repo.get_run(run_id)
                # A rename + receipt followed by a DB commit exception is an
                # uncertain filesystem/SQLite boundary.  Keep the run
                # resumable so a fresh owner can revalidate and reconcile it;
                # never downgrade a recoverable publication to failed and
                # strand an immutable-looking public file.
                final = Path(str(owned_manifest.get("output_path") or ""))
                uncertain_publication = (
                    rec.status in ("running", "verifying")
                    and final.is_file()
                    and _publication_receipt_path(final).is_file()
                )
                if not uncertain_publication:
                    repo.transition_run(
                        run_id,
                        "failed",
                        actor=ctx.worker_id,
                        expected_revision=rec.revision,
                        fence_token=lease.fence_token,
                    )
                    session.commit()
            except Exception:
                # Lost the fence mid-failure (fresh owner reclaimed): the
                # run is owned elsewhere; nothing more to mutate.
                session.rollback()
            cleanup_owned_export_artifacts(
                scratch_dir=owned_manifest.get("scratch_dir"),
                chunk_dir=owned_manifest.get("chunk_dir"),
                candidate_path=owned_manifest.get("candidate_path"),
                repository=repo,
                owner_run_id=run_id,
                owner_worker_id=ctx.worker_id,
                owner_fence_token=lease.fence_token,
            )
            raise
    return {
        "run_id": run_id,
        "status": outcome["status"],
        "output_path": str(outcome.get("output_path") or ""),
        "artifact_sha256": str(outcome.get("artifact_sha256") or ""),
        "verdict": str(outcome.get("verdict") or ""),
        "frame_count": int(manifest["frame_count"]),
    }


def _candidate_for(manifest: dict[str, Any]) -> Path:
    """Private candidate path for the runner's assembly (never public)."""
    scratch = Path(str(manifest["scratch_dir"]))
    scratch.mkdir(parents=True, exist_ok=True)
    candidate = Path(str(manifest.get("candidate_path") or scratch / "candidate_final.mp4"))
    if candidate.resolve().parent != scratch.resolve():
        raise RuntimeError("candidate path must be a direct child of owned scratch")
    return candidate


def register_s12_export_handler(worker: Any) -> None:
    """Register the S12 export handler on a DurableWorker instance."""
    worker.register_handler(S12_EXPORT_JOB_TYPE, _s12_export_handler)


def reconcile_export_jobs(
    session_factory: Callable[[], Any],
    *,
    batch_size: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normal-startup S12 recovery scan (C2 F05/F01, zero-mutation).

    The T03A C2 fencing contract makes recovery self-healing: a fresh
    ``claim_run`` CAS re-claims an expired/released lease on a ``running``
    run (exactly one winner; losers never mutate).  This reconciler is the
    REAL production startup caller that reports every resumable orphan —
    a ``running`` run whose lease ``expires_at`` has passed — so the
    restarted worker's job claim resumes it from the T03B checkpoint.

    It NEVER calls ``release_lease`` (live-lease fencing) and NEVER flips a
    run status: expired leases are reported as ``expired``/``resumable``,
    live leases are skipped, terminal runs are untouched.  Bounded,
    restart-safe, never raises: per-run failures are recorded on the report
    and the pass continues.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.persistence.models import (  # noqa: PLC0415
        S12ExportLease,
        S12ExportRun,
    )

    report: dict[str, Any] = {"scanned": 0, "expired": 0, "resumable": [], "errors": []}
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        with session_factory() as session:
            rows = session.scalars(
                select(S12ExportLease)
                .join(S12ExportRun, S12ExportLease.run_id == S12ExportRun.id)
                .where(S12ExportRun.status == "running")
                .order_by(S12ExportLease.expires_at.asc())
                .limit(max(1, int(batch_size)))
            ).all()
            candidates = [
                (row.run_id, row.worker_id, row.expires_at)
                for row in rows
            ]
    except Exception as exc:
        report["errors"].append({"stage": "scan", "error": str(exc)})
        return report
    report["scanned"] = len(candidates)
    for run_id, _worker_id, expires_at in candidates:
        exp = expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp > moment:
            continue
        # Expired lease on a running run: a fresh claim resumes from the
        # checkpoint — record the resumable orphan, mutate nothing.
        report["expired"] += 1
        report["resumable"].append(run_id)
    return report
