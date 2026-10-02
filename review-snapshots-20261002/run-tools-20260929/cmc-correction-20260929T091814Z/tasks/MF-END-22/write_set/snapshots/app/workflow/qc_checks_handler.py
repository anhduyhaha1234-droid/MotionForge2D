"""S11-T03G (W8) — durable RUN_QC_CHECKS handler + server-owned submission.

The check-run is durable through the EXISTING Job/JobStep/JobAttempt
infrastructure (NO new QCCheckRun table, NO migration): job type
``RUN_QC_CHECKS``; the durable handler invokes the T03F orchestrator
(``run_full_check_set``) over the manifest's server-owned detector band.

Completion evidence (JobAttempt ``result`` + step checkpoint):

- ``policy_id`` / ``policy_content_hash``  — frozen T03A thresholds policy,
  read-only (``app.services.qc_checks.thresholds``);
- ``source_generation`` / ``source_artifact_fingerprint`` /
  ``evidence_fingerprint`` — the video's current evidence identity the run
  is valid for;
- ``scope`` / ``scope_fingerprint`` — the server-owned band requested;
- ``detector_revisions`` — registry-frozen revisions of the executed band;
- ``summary`` — the orchestrator's MEASURED summary (nothing fabricated);
- ``zero_item_completion`` — explicit zero-item completion evidence so a
  clean run is provably distinct from never-run (C4-F2, GAP-8).

Server-owned scopes (clients never name detectors/handlers/providers):

- ``full``  — every registered detector, in registry registration order;
- ``audio`` — the audio band (``audio_missing`` + ``av_sync_drift``).

Idempotency key
``RUN_QC_CHECKS:video_item:<video_id>:<evidence_fingerprint>:<policy_hash>:<scope>``
— an active duplicate fails closed (``IdempotencyKeyInUse``), a completed
duplicate reuses the same Job (AC4).  Restart/retry never duplicates
QCItems or run effects: the orchestrator's natural-key idempotency +
content-derived run fingerprint (AC5).

Fail-closed semantics of the handler:

- evidence fingerprint changed since submit → permanent
  ``QC_RUN_EVIDENCE_CHANGED`` (a NEW logical run must be submitted);
- orchestrator detector errors (``summary.errors > 0``) → permanent
  ``QC_RUN_DETECTOR_ERRORS`` — an errored run is NEVER recorded as a
  completed run (readiness stays ``not_run`` with check-state detail);
- deadline / cancel (transient boundary exhaustion) → ``TRANSIENT`` so the
  durable worker's bounded retry policy decides; a cancelled Job drains to
  terminal ``cancelled`` with zero QCItem effects.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.jobs import IdempotencyKeyInUse, StepInput
from app.persistence.models import Artifact, ProjectCastMapping, VideoItem
from app.services import video_import
from app.services.qc_checks.orchestrator import (
    OrchestratorSummary,
    run_full_check_set,
)
from app.services.qc_checks.registry import QcRegistryError, registry
from app.services.qc_checks.runner import (
    QC_RUNNER_CANCELLED,
    QC_RUNNER_DEADLINE_EXCEEDED,
    QcRunnerError,
)
from app.services.qc_checks.thresholds import POLICY_ID, load_policy
from app.workflow.durable_worker import WorkerContext

#: Durable job type for check-runs (worker dispatches by this).
JOB_TYPE_RUN_QC_CHECKS = "RUN_QC_CHECKS"

#: Sole step code of a check-run Job.
RUN_QC_STEP_CODE = "run_qc_checks"

#: Schema version of the manifest / completion block.
RUN_QC_SCHEMA_VERSION = 1

#: Server-owned scopes.  Clients may name ONLY these — never a handler,
#: provider or detector implementation (Decision A).
SCOPE_FULL = "full"
SCOPE_AUDIO = "audio"
VALID_SCOPES: frozenset[str] = frozenset({SCOPE_FULL, SCOPE_AUDIO})

#: Audio band (server-owned; frozen list).  The FULL band is the binding
#: 10-detector band derived from the frozen T03A policy calibration
#: metrics — NOT the live registry order (the registry is a runtime
#: discovery view tests may populate partially, so the submission
#: authority pins the binding band to the frozen policy contract).
SCOPE_BANDS: Mapping[str, Sequence[str]] = {
    SCOPE_AUDIO: ("audio_missing", "av_sync_drift"),
    SCOPE_FULL: (
        "trajectory_drift",
        "cut_drift",
        "contact_break",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "edge_halo",
        "temporal_flicker",
        "audio_missing",
        "av_sync_drift",
    ),
}

#: Server-side default execution bounds (bounded runner contract).
DEFAULT_DEADLINE_SEC = 300.0
DEFAULT_CAPTURE_CAP_BYTES = 64 * 1024

#: Stable failure codes (worker taxonomy: see ``TRANSIENT_ERROR_CODES``).
QC_RUN_UNKNOWN_SCOPE = "QC_RUN_UNKNOWN_SCOPE"
QC_RUN_MISSING_ARGS = "QC_RUN_MISSING_ARGS"
QC_RUN_EVIDENCE_UNAVAILABLE = "QC_RUN_EVIDENCE_UNAVAILABLE"
QC_RUN_BOOTSTRAP_CONFLICT = "QC_RUN_BOOTSTRAP_CONFLICT"
QC_RUN_EVIDENCE_CHANGED = "QC_RUN_EVIDENCE_CHANGED"
QC_RUN_DETECTOR_ERRORS = "QC_RUN_DETECTOR_ERRORS"
QC_RUN_NO_SESSION = "QC_RUN_NO_SESSION"

#: MF-END-23 additive contract identity of the OUTPUT-BOUND evidence identity.
#: ORTHOGONAL to the frozen T03A policy and to the T03G read authority: this
#: contract only widens WHAT the run identity covers (source + rendered output
#: + cast), never how a verdict is computed.
EVIDENCE_BINDING_SCHEMA = "mf-end-23/evidence-binding@1"


class RunQcChecksError(Exception):
    """Stable-code error for the RUN_QC_CHECKS submission/execution surface."""

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
        self.details = dict(details or {}) if details else None


class QcCheckRunSubmitError(RunQcChecksError):
    """Submission-time failure (before any Job row is created)."""


@dataclass(frozen=True)
class QcCheckRunSubmitResult:
    """Outcome of :func:`submit_run_qc_checks`."""

    job_id: str
    reused: bool
    idempotency_key: str
    evidence_fingerprint: str


# ── content-derived helpers ──────────────────────────────────────────────────


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def scope_detectors(scope: str) -> list[str]:
    """Resolve a server-owned scope to its ordered detector band.

    Both bands are frozen server-owned lists (the FULL band is pinned to
    the frozen T03A policy contract — the registry is a runtime discovery
    view the orchestrator consumes read-only, never the authority for
    what "full" means).  Unknown scopes fail closed.
    """
    band = SCOPE_BANDS.get(scope)
    if band is None:
        raise RunQcChecksError(
            QC_RUN_UNKNOWN_SCOPE,
            f"unknown RUN_QC_CHECKS scope {scope!r}; valid: {sorted(VALID_SCOPES)}",
            details={"scope": scope, "valid_scopes": sorted(VALID_SCOPES)},
        )
    return list(band)


def scope_fingerprint(scope: str) -> str:
    """Content-derived identity of the scope's ordered detector band."""
    return _sha256({"scope": scope, "detectors": scope_detectors(scope)})


def policy_bundle() -> dict[str, str]:
    """Frozen thresholds policy identity (read-only; local import cache)."""
    policy = load_policy()
    return {
        "policy_id": str(policy.get("policy_id") or POLICY_ID),
        "policy_content_hash": str(policy["content_hash"]),
    }


def source_artifact_fingerprint(
    session: Session, *, video_item_id: str
) -> dict[str, Any]:
    """The video item's current source evidence identity, persisted-read.

    Deterministic and content-derived: artifact id + recorded SHA-256 (or
    empty when unset).  Never a client-supplied string.
    """
    item = session.get(VideoItem, video_item_id)
    artifact_id: str | None = None
    sha256 = ""
    if item is not None and item.source_artifact_id:
        artifact = session.get(Artifact, item.source_artifact_id)
        if artifact is not None:
            artifact_id = artifact.id
            sha256 = str(artifact.sha256 or "")
    return {"source_artifact_id": artifact_id, "source_sha256": sha256}


def output_evidence_binding(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """The video's CURRENT output-bound evidence identity (MF-END-23).

    Composes, from PERSISTED ROWS ONLY (no byte reads), the three facts a
    check-run's validity depends on:

    * ``source`` — the imported source artifact id + recorded sha256;
    * ``render`` — the current rendered output row (:func:`output_render_row`
      over ``app.services.qc_evidence.compose``: newest completed publication,
      else the newest render-side artifact owned by the video), including its
      publication/checkpoint identity; ``None`` when the video has no rendered
      output distinct from its source;
    * ``cast`` — every ProjectCastMapping row of the project (role →
      character / immutable pack version / revision), digest-pinned.

    ``digest`` content-addresses the whole binding.  ``resolver_error`` is
    recorded (never swallowed) when a component cannot be resolved, so a
    consumer can fail closed instead of reading a degraded binding as fresh.
    """
    from app.services.qc_evidence.compose import render_row  # lazy: no cycle

    item = session.get(VideoItem, video_item_id)
    resolved_project = project_id or (
        str(item.project_id) if item is not None and item.project_id else None
    )
    source = source_artifact_fingerprint(session, video_item_id=video_item_id)

    resolver_error: str | None = None
    render: dict[str, Any] | None = None
    if resolved_project:
        try:
            render = render_row(
                session,
                workspace_id=workspace_id,
                project_id=resolved_project,
                video_item_id=video_item_id,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            resolver_error = f"{type(exc).__name__}: {exc}"
    else:
        resolver_error = "project_unresolved_for_video_item"

    cast_rows = session.execute(
        select(
            ProjectCastMapping.object_role_id,
            ProjectCastMapping.character_id,
            ProjectCastMapping.pack_version_id,
            ProjectCastMapping.revision,
            ProjectCastMapping.id,
        )
        .where(
            ProjectCastMapping.workspace_id == workspace_id,
            ProjectCastMapping.project_id == str(resolved_project or ""),
        )
        .order_by(ProjectCastMapping.object_role_id, ProjectCastMapping.id)
    ).all()
    cast_block: dict[str, Any] = {
        "roles": [
            {
                "object_role_id": str(row[0]),
                "character_id": str(row[1]),
                "pack_version_id": str(row[2]),
                "revision": int(row[3]),
                "mapping_id": str(row[4]),
            }
            for row in cast_rows
        ]
    }
    cast_block["digest"] = _sha256(cast_block)

    binding: dict[str, Any] = {
        "schema": EVIDENCE_BINDING_SCHEMA,
        "workspace_id": workspace_id,
        "project_id": resolved_project,
        "video_item_id": video_item_id,
        "source": {
            "artifact_id": source["source_artifact_id"],
            "sha256": source["source_sha256"],
        },
        "render": render,
        "cast": cast_block,
        "resolver_error": resolver_error,
    }
    binding["digest"] = _sha256(binding)
    return binding


def evidence_fingerprint(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
    generation: str = "1",
    project_id: str | None = None,
) -> str:
    """Current video evidence fingerprint — OUTPUT-BOUND (MF-END-23).

    Additive contract ``mf-end-23/evidence-binding@1``: the identity a
    check-run is valid for now covers the whole evidence chain the FULL band
    actually measures, so a change ANYWHERE in it makes a completed run stale
    instead of silently current:

    * the imported SOURCE identity + generation (the pre-MF-END-23 identity,
      kept bit-for-bit computable via :func:`legacy_evidence_fingerprint`);
    * the CURRENT rendered OUTPUT (artifact id + recorded sha256 + the
      completed publication's checkpoint identity), resolved through the
      same disclosed precedence the evidence composer uses;
    * the project CAST binding (every ProjectCastMapping row's role →
      character/pack-version/revision).

    The read authority (``app.persistence.qc_check_runs``) recomputes this
    fingerprint before trusting a completion envelope, so a render change or
    a cast change invalidates readiness (``not_run``) — and therefore blocks
    export — with NO change to the policy or readiness authority itself.
    """
    binding = output_evidence_binding(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
    )
    source = binding["source"]
    return _sha256(
        {
            "schema": EVIDENCE_BINDING_SCHEMA,
            "source_artifact_id": source["artifact_id"],
            "source_sha256": source["sha256"],
            "source_generation": generation,
            "output_binding_digest": binding["digest"],
        }
    )


def legacy_evidence_fingerprint(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
    generation: str = "1",
) -> str:
    """The pre-MF-END-23 fingerprint formula (source identity + generation).

    Kept computable — never used for authority — so the additive change is
    provable in review: the legacy identity answers ONLY "did the source
    change?", which is exactly the question that could no longer see a
    render/cast change (MF-END-23 finding).
    """
    del workspace_id  # the persisted source identity is authoritative
    source = source_artifact_fingerprint(session, video_item_id=video_item_id)
    return _sha256(
        {
            "source_artifact_id": source["source_artifact_id"],
            "source_sha256": source["source_sha256"],
            "source_generation": generation,
        }
    )


def detector_revisions(detectors: Sequence[str]) -> dict[str, str]:
    """Server-owned detector revisions (registry frozen, content-bound)."""
    revisions: dict[str, str] = {}
    for name in detectors:
        spec = registry.get(name)  # QC_REGISTRY_UNKNOWN when absent
        revisions[name] = spec.version
    return revisions


# ── C4-A: deterministic production detector bootstrap ───────────────────────

#: C4-R2: process-wide re-entrant lock serializing the WHOLE bootstrap
#: transaction (snapshot→imports→pre-existing checks→explicit
#: registrations→post-verify→rollback).  Per-dict-op locking is
#: insufficient: detector imports self-register at module level, so two
#: live threads racing bootstrap could interleave import side effects
#: with explicit registrations / post-verify / rollback and leave a
#: partial registry.  ``threading.RLock`` (re-entrant) so nested or
#: repeated bootstrap calls from the same thread never deadlock.
_BOOTSTRAP_LOCK = threading.RLock()


def _ensure_full_band_registered_locked() -> dict[str, str]:
    """Register the binding FULL band in the process registry (idempotent).

    A clean production process starts with an EMPTY detector registry (no
    detector module is imported at ``JobService`` construction time), so a
    real production ``RUN_QC_CHECKS`` would die with
    ``QC_ORCHESTRATOR_MISSING_ARGS`` before any detector runs.  This
    bootstrap is the ONLY production registration path: it imports the
    seven self-registering detector modules (registration is their
    module-level identity-idempotent side effect) and calls ``register()``
    on the three explicit-registration modules, in exact
    ``SCOPE_BANDS[SCOPE_FULL]`` order; every name, entry point and revision
    comes from the detector modules' own constants (never hard-coded
    here, never a test-only shim).

    Fail-closed with FULL rollback: the ENTIRE pre-call registry (every
    name with its entry point, version and description) is snapshotted
    before any state is touched, and EVERY failure path — conflicting
    pre-existing identity, import-time conflict, explicit-registration
    failure, post-bootstrap mismatch, foreign (non-band) entries — restores
    that snapshot exactly and raises ``RunQcChecksError`` with code
    ``QC_RUN_BOOTSTRAP_CONFLICT`` (the registry only conflicts on entry
    points, so the revision leg is verified here).  Success requires the
    post-bootstrap registry to equal the binding FULL band EXACTLY (same
    set, same order, same revisions — a foreign ``ghost_detector`` entry
    is rejected, never absorbed).  Calling twice is a no-op returning the
    same revision map.
    """
    band = list(SCOPE_BANDS[SCOPE_FULL])
    # C4-R1: FULL pre-call snapshot of the ENTIRE registry (every name,
    # not just band members).  Detector imports self-register at module
    # level — they would overwrite (launder) a conflicting pre-existing
    # identity before any check could see it — so every failure path below
    # restores this snapshot exactly (same set, same order, same
    # entry/version/description per name).
    def _snapshot() -> list[tuple[str, str, str, str]]:
        snap: list[tuple[str, str, str, str]] = []
        for _name in registry.names():
            _spec = registry.get(_name)
            snap.append(
                (_name, _spec.entry_point, _spec.version, _spec.description)
            )
        return snap

    def _restore(snap: list[tuple[str, str, str, str]]) -> None:
        for _name in registry.names():
            registry.unregister(_name)
        for _name, _entry, _version, _desc in snap:
            registry.register(
                _name, _entry, version=_version, description=_desc
            )

    pre_call = _snapshot()
    pre_existing = {
        _name: (_entry, _version) for _name, _entry, _version, _ in pre_call
    }
    try:
        from app.services.qc_checks import (  # noqa: E402  (bootstrap imports)
            audio_missing,
            av_sync_drift,
            contact_break,
            cut_drift,
            edge_halo,
            identity_drift,
            silhouette_clipping,
            temporal_flicker,
            trajectory_drift,
            z_order_error,
        )
    except QcRegistryError as exc:
        _restore(pre_call)
        raise RunQcChecksError(
            QC_RUN_BOOTSTRAP_CONFLICT,
            "detector bootstrap hit a conflicting registry identity "
            f"during detector import ({exc.code}: {exc.message})",
            details={"registry_code": exc.code, "registry_message": exc.message},
        ) from exc
    expected: dict[str, tuple[str, str]] = {
        trajectory_drift.DETECTOR_NAME: (
            f"{trajectory_drift.__name__}:detect",
            trajectory_drift.DETECTOR_VERSION,
        ),
        cut_drift.DETECTOR_NAME: (
            f"{cut_drift.__name__}:detect",
            cut_drift.DETECTOR_VERSION,
        ),
        contact_break.DETECTOR_NAME: (
            f"{contact_break.__name__}:detect_contact_break",
            contact_break.DETECTOR_REVISION,
        ),
        z_order_error.DETECTOR_NAME: (
            f"{z_order_error.__name__}:detect_z_order_error",
            z_order_error.DETECTOR_REVISION,
        ),
        silhouette_clipping.DETECTOR_NAME: (
            f"{silhouette_clipping.__name__}:detect_silhouette_clipping",
            silhouette_clipping.DETECTOR_REVISION,
        ),
        identity_drift.REASON_CODE: (
            f"{identity_drift.__name__}:detect",
            identity_drift.DETECTOR_REVISION,
        ),
        edge_halo.REASON_CODE: (
            f"{edge_halo.__name__}:detect",
            edge_halo.DETECTOR_REVISION,
        ),
        temporal_flicker.REASON_CODE: (
            f"{temporal_flicker.__name__}:detect",
            temporal_flicker.DETECTOR_REVISION,
        ),
        audio_missing.DETECTOR_NAME: (
            f"{audio_missing.__name__}:detect",
            audio_missing.DETECTOR_REVISION,
        ),
        av_sync_drift.DETECTOR_NAME: (
            f"{av_sync_drift.__name__}:detect",
            av_sync_drift.DETECTOR_REVISION,
        ),
    }
    if sorted(expected) != sorted(band):
        _restore(pre_call)
        raise RunQcChecksError(
            QC_RUN_BOOTSTRAP_CONFLICT,
            "bootstrap binding drifted from the frozen FULL band "
            f"(expected {sorted(band)}; bound {sorted(expected)})",
            details={"band": sorted(band), "bound": sorted(expected)},
        )
    # Pre-check on the PRE-IMPORT snapshot: a conflicting registration that
    # existed before the detector imports ran fails closed even when the
    # import side effect already overwrote (laundered) the live entry.
    # The live registry is restored BEFORE raising, so a conflict never
    # leaves a partial or poisoned registry behind (a retry sees the exact
    # pre-call state, never laundered entries).
    for name in band:
        entry_point, version = expected[name]
        snap = pre_existing.get(name)
        if snap is not None and (snap[0] != entry_point or snap[1] != version):
            _restore(pre_call)
            raise RunQcChecksError(
                QC_RUN_BOOTSTRAP_CONFLICT,
                f"detector {name!r} already registered with a conflicting "
                f"identity (registered {snap[0]!r}@{snap[1]!r}; "
                f"binding {entry_point!r}@{version!r})",
                details={
                    "name": name,
                    "registered_entry_point": snap[0],
                    "registered_version": snap[1],
                    "binding_entry_point": entry_point,
                    "binding_version": version,
                },
            )
    # A foreign (non-band) pre-existing entry is NOT part of the binding
    # band: absorbing it would silently widen the production detector
    # surface, so it fails closed with the snapshot restored.  Only names
    # (not entry-point strings) participate — an entry point that merely
    # MENTIONS a band module path is still a foreign registration name and
    # is judged by its own name.
    _band_names = set(band)
    foreign = [name for name in pre_existing if name not in _band_names]
    if foreign:
        _restore(pre_call)
        raise RunQcChecksError(
            QC_RUN_BOOTSTRAP_CONFLICT,
            "detector registry holds foreign entries outside the binding "
            f"FULL band ({sorted(foreign)}); refusing to absorb unknown "
            "detectors into the production band",
            details={"foreign": sorted(foreign), "band": band},
        )
    # Importing the seven self-registering modules above already registered
    # them (module-level identity-idempotent side effect); the three
    # explicit modules need their register() call.  The registry keeps
    # FIRST-insertion order, so a registry pre-populated by earlier imports
    # (any subset, any order) is re-seated into exact band order:
    # unregister plus re-register of the SAME identity is contract-safe,
    # and the pre-check above already rejected every conflicting identity.
    _EXPLICIT = {
        "contact_break": contact_break.register,
        "z_order_error": z_order_error.register,
        "silhouette_clipping": silhouette_clipping.register,
    }
    try:
        for name in band:
            if name in _EXPLICIT:
                registry.unregister(name)
                _EXPLICIT[name]()
        if [name for name in registry.names() if name in set(band)] != band:
            for name in band:
                registry.unregister(name)
            for name in band:
                entry_point, version = expected[name]
                register_fn = _EXPLICIT.get(name)
                if register_fn is not None:
                    register_fn()
                else:
                    registry.register(name, entry_point, version=version)
    except QcRegistryError as exc:
        _restore(pre_call)
        raise RunQcChecksError(
            QC_RUN_BOOTSTRAP_CONFLICT,
            "detector bootstrap failed during explicit registration "
            f"({exc.code}: {exc.message})",
            details={
                "registry_code": exc.code,
                "registry_message": exc.message,
            },
        ) from exc
    # Post-verify: namespace, order and revision map must equal the binding.
    names = registry.names()
    try:
        revisions = detector_revisions(band)
    except QcRegistryError as exc:
        _restore(pre_call)
        raise RunQcChecksError(
            QC_RUN_BOOTSTRAP_CONFLICT,
            "post-bootstrap registry does not equal the binding FULL band "
            f"({exc.code}: {exc.message})",
            details={"band": band, "registered": names},
        ) from exc
    if names != band or any(
        revisions[name] != expected[name][1] for name in band
    ):
        _restore(pre_call)
        raise RunQcChecksError(
            QC_RUN_BOOTSTRAP_CONFLICT,
            "post-bootstrap registry does not equal the binding FULL band",
            details={
                "band": band,
                "registered": names,
                "revisions": revisions,
            },
        )
    return revisions


def _bootstrap_snapshot() -> list[tuple[str, str, str, str]]:
    """Module-level FULL snapshot helper (mirrors the inner snapshot)."""
    snap: list[tuple[str, str, str, str]] = []
    for _name in registry.names():
        _spec = registry.get(_name)
        snap.append(
            (_name, _spec.entry_point, _spec.version, _spec.description)
        )
    return snap


def _bootstrap_restore(
    snap: list[tuple[str, str, str, str]],
) -> None:
    """Module-level exact restore helper (mirrors the inner restore)."""
    for _name in registry.names():
        registry.unregister(_name)
    for _name, _entry, _version, _desc in snap:
        registry.register(
            _name, _entry, version=_version, description=_desc
        )


def ensure_full_band_registered() -> dict[str, str]:
    """Public bootstrap entry: whole transaction under the process lock.

    C4-R2 rows 1-3: serializes the ENTIRE bootstrap transaction
    (snapshot→imports→pre-existing checks→explicit registrations→
    post-verify→rollback) on ``_BOOTSTRAP_LOCK``; ANY ordinary Python
    exception escaping the inner bootstrap restores the COMPLETE
    pre-call snapshot before a stable
    ``RunQcChecksError(QC_RUN_BOOTSTRAP_CONFLICT)`` escapes (original
    exception kept as ``__cause__`` with truthful details);
    ``KeyboardInterrupt``/``SystemExit`` policy: rollback STILL runs,
    then the original is re-raised unwrapped (never converted, never
    swallowed) so cancellation semantics are preserved.
    """
    with _BOOTSTRAP_LOCK:
        pre_call = _bootstrap_snapshot()
        try:
            return _ensure_full_band_registered_locked()
        except (KeyboardInterrupt, SystemExit):
            _bootstrap_restore(pre_call)
            raise
        except RunQcChecksError:
            _bootstrap_restore(pre_call)
            raise
        except Exception as exc:
            _bootstrap_restore(pre_call)
            raise RunQcChecksError(
                QC_RUN_BOOTSTRAP_CONFLICT,
                "detector bootstrap hit an unexpected failure "
                f"({type(exc).__name__}: {exc})",
                details={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            ) from exc


# ── completion block ─────────────────────────────────────────────────────────


def build_completion_block(
    *,
    scope: str,
    scope_fp: str,
    evidence_fp: str,
    source_fp: dict[str, Any],
    source_generation: str,
    detectors: Sequence[str],
    revisions: Mapping[str, str],
    summary: OrchestratorSummary,
    evidence_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic completion evidence recorded in JobAttempt result +
    step checkpoint (zero-item completion evidence included)."""
    run = summary
    issues_found = sum(
        int(entry.get("items_found") or 0)
        for entry in run.per_detector.values()
    )
    summary_block = {
        "run_id": run.run_id,
        "checks_requested": run.checks_requested,
        "checks_run": run.checks_run,
        "checks_skipped": run.checks_skipped,
        "created": run.created,
        "reused": run.reused,
        "resolved_after_recheck": run.resolved_after_recheck,
        "reopened_stale": run.reopened_stale,
        "not_applicable": run.not_applicable,
        "errors": run.errors,
        "cancelled": run.cancelled,
        "deadline_exceeded": run.deadline_exceeded,
        "run_sec": round(run.run_sec, 6),
        "per_detector": {
            name: dict(entry) for name, entry in run.per_detector.items()
        },
    }
    return {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "job_type": JOB_TYPE_RUN_QC_CHECKS,
        "completed": True,
        "run_id": run.run_id,
        "policy_id": policy_bundle()["policy_id"],
        "policy_content_hash": policy_bundle()["policy_content_hash"],
        "source_generation": source_generation,
        "source_artifact_id": source_fp["source_artifact_id"],
        "source_artifact_fingerprint": source_fp["source_sha256"],
        "evidence_fingerprint": evidence_fp,
        "scope": scope,
        "scope_fingerprint": scope_fp,
        "detectors": list(detectors),
        "detector_revisions": dict(revisions),
        "evidence_binding": (
            dict(evidence_binding) if evidence_binding is not None else None
        ),
        "summary": summary_block,
        "zero_item_completion": {
            # Reuse-safe: the flag is the detectors' REPORTED issue count
            # (zero = the band found nothing), never the row-creation count
            # (a replay reuses existing rows and would misreport as clean).
            "evidence": (
                run.errors == 0
                and run.checks_skipped == 0
                and issues_found == 0
            ),
            "qc_items_created": run.created,
            "issues_found": issues_found,
            "checks_run": run.checks_run,
            "not_applicable": run.not_applicable,
        },
    }


# ── the durable handler ──────────────────────────────────────────────────────


class _CancelFlag(threading.Event):
    """Adapter: expose the worker's durable cancel flag as a real ``Event``.

    Subclasses :class:`threading.Event` so the bounded runner/orchestrator
    type contract (``cancel_event: Event | None``) holds, while the flag
    stays PULL-based — ``is_set()`` consults the worker's durable cancel
    state through *is_cancelled* instead of a process-local event; no
    background thread and no behavior change from the plain-adapter form.
    """

    def __init__(self, is_cancelled: Callable[[], bool]) -> None:
        super().__init__()
        self._is_cancelled = is_cancelled

    def is_set(self) -> bool:
        return self._is_cancelled()


def qc_checks_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one RUN_QC_CHECKS Job: orchestrator + durable completion.

    The manifest is server-owned (written by :func:`submit_run_qc_checks`
    or the check-run API route).  The handler re-derives the CURRENT video
    evidence fingerprint and policy identity; any mismatch with the
    submit-time values fails closed (the run is no longer current).  The
    completion block is written to the step checkpoint BEFORE returning so
    a crash between orchestrator commit and attempt record still leaves
    durable evidence; a replay re-runs the orchestrator idempotently.
    """
    manifest = ctx.input_manifest
    scope = str(manifest.get("scope") or "")
    detectors = scope_detectors(scope)
    evidence_fp = str(manifest.get("evidence_fingerprint") or "")
    submitted_policy_hash = str(manifest.get("policy_content_hash") or "")
    source_generation = str(manifest.get("source_generation") or "1")

    if ctx.session_factory is None:
        raise RunQcChecksError(
            QC_RUN_NO_SESSION,
            "RUN_QC_CHECKS handler requires a bound session factory",
        )

    with ctx.session_factory() as session:
        # Fail-closed: the video's evidence must be exactly what the run was
        # submitted against — otherwise this run is no longer current.
        current_fp = evidence_fingerprint(
            session,
            workspace_id=str(manifest.get("workspace_id") or ""),
            video_item_id=str(manifest.get("video_item_id") or ""),
            generation=source_generation,
            project_id=str(manifest.get("project_id") or "") or None,
        )
        if current_fp != evidence_fp:
            raise RunQcChecksError(
                QC_RUN_EVIDENCE_CHANGED,
                "video evidence fingerprint changed since submission; "
                "a new RUN_QC_CHECKS job must be submitted",
                details={
                    "submitted_evidence_fingerprint": evidence_fp,
                    "current_evidence_fingerprint": current_fp,
                },
            )
        if submitted_policy_hash != policy_bundle()["policy_content_hash"]:
            raise RunQcChecksError(
                QC_RUN_EVIDENCE_CHANGED,
                "threshold policy content hash changed since submission; "
                "a new RUN_QC_CHECKS job must be submitted",
                details={
                    "submitted_policy_content_hash": submitted_policy_hash,
                    "current_policy_content_hash": policy_bundle()["policy_content_hash"],
                },
            )

        deadline_sec = float(manifest.get("deadline_sec") or DEFAULT_DEADLINE_SEC)
        capture_cap = int(
            manifest.get("capture_cap_bytes") or DEFAULT_CAPTURE_CAP_BYTES
        )
        detector_args: Mapping[str, Mapping[str, Any]] = manifest.get(
            "detector_args"
        ) or {}
        missing = [name for name in detectors if name not in detector_args]
        if missing:
            raise RunQcChecksError(
                QC_RUN_MISSING_ARGS,
                f"no args supplied for band detectors: {sorted(missing)}",
                details={"missing": sorted(missing)},
            )

        try:
            summary = run_full_check_set(
                session,
                workspace_id=str(manifest.get("workspace_id") or ""),
                project_id=str(manifest.get("project_id") or ""),
                video_item_id=str(manifest.get("video_item_id") or ""),
                detector_args=detector_args,
                detectors=detectors,
                deadline_sec=deadline_sec,
                capture_cap_bytes=capture_cap,
                cancel_event=_CancelFlag(ctx.is_cancelled),
                commit=True,
            )
        except QcRunnerError as exc:
            transient = exc.code in (QC_RUNNER_DEADLINE_EXCEEDED, QC_RUNNER_CANCELLED)
            raise RunQcChecksError(
                "TRANSIENT" if transient else str(exc.code),
                f"qc orchestrator failed: {exc.message}",
                details={
                    "qc_run_code": str(exc.code),
                    "qc_run_message": exc.message,
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001 - classified by stable code
            raise RunQcChecksError(
                str(getattr(exc, "code", None) or "QC_RUN_FAILED"),
                f"qc check run failed: {exc}",
                details={"error_type": type(exc).__name__},
            ) from exc

        source_fp = source_artifact_fingerprint(
            session, video_item_id=str(manifest.get("video_item_id") or "")
        )
        binding_for_completion = output_evidence_binding(
            session,
            workspace_id=str(manifest.get("workspace_id") or ""),
            project_id=str(manifest.get("project_id") or "") or None,
            video_item_id=str(manifest.get("video_item_id") or ""),
        )

    # Fail-closed completion: an errored / deadline-exhausted / cancelled
    # orchestrator run is NEVER recorded as a completed check-run — the
    # readiness authority keeps reporting not_run with check-state detail.
    if summary.errors > 0 or summary.deadline_exceeded or summary.cancelled:
        partial = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "job_type": JOB_TYPE_RUN_QC_CHECKS,
            "completed": False,
            "run_id": summary.run_id,
            "scope": scope,
            "scope_fingerprint": scope_fingerprint(scope),
            "evidence_fingerprint": evidence_fp,
            "summary": {
                "checks_requested": summary.checks_requested,
                "checks_run": summary.checks_run,
                "checks_skipped": summary.checks_skipped,
                "created": summary.created,
                "errors": summary.errors,
                "cancelled": summary.cancelled,
                "deadline_exceeded": summary.deadline_exceeded,
            },
            "zero_item_completion": {"evidence": False},
        }
        ctx.write_checkpoint(partial)
        if summary.cancelled:
            raise RunQcChecksError(
                "TRANSIENT",
                "qc check run cancelled",
                details={"qc_run_code": QC_RUNNER_CANCELLED},
            )
        if summary.deadline_exceeded:
            raise RunQcChecksError(
                "TRANSIENT",
                "qc check run exceeded its bounded deadline",
                details={"qc_run_code": QC_RUNNER_DEADLINE_EXCEEDED},
            )
        raise RunQcChecksError(
            QC_RUN_DETECTOR_ERRORS,
            "qc check run completed with detector errors",
            details={
                "errors": summary.errors,
                "per_detector": {
                    name: dict(entry)
                    for name, entry in summary.per_detector.items()
                    if entry.get("error_code")
                },
            },
        )

    source_fp = source_fp
    completion = build_completion_block(
        scope=scope,
        scope_fp=scope_fingerprint(scope),
        evidence_fp=evidence_fp,
        source_fp=source_fp,
        source_generation=source_generation,
        detectors=detectors,
        revisions=detector_revisions(detectors),
        summary=summary,
        evidence_binding=binding_for_completion,
    )
    ctx.write_checkpoint(completion)
    return completion


# ── step plan + registration ─────────────────────────────────────────────────


def run_qc_checks_steps() -> list[StepInput]:
    """The RUN_QC_CHECKS step plan (one sync step)."""
    return [StepInput(step_code=RUN_QC_STEP_CODE, position=0, step_type="sync")]


def register_qc_checks_handler(worker: Any) -> None:
    """Register the RUN_QC_CHECKS handler on a DurableWorker (dispatched by
    job_type)."""
    worker.register_handler(JOB_TYPE_RUN_QC_CHECKS, qc_checks_handler)


# ── server-owned submission authority ────────────────────────────────────────


def compose_check_run_args(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    scope: str,
) -> dict[str, dict[str, Any]]:
    """Server-composed detector args for a scope from PERSISTED evidence only.

    The audio band is composed from the video's latest completed
    ATTACH_ORIGINAL_AUDIO attempt result (the T03E envelope contract) —
    never from client-supplied values.  The non-audio band is composed by
    ``app.services.qc_evidence`` from persisted source/result/annotation
    artifacts (byte-verified on read).  When the persisted evidence is
    missing, superseded (stale), foreign, malformed or tampered — or a
    required fact has no producer at all — the composition fails closed
    (``QC_RUN_EVIDENCE_UNAVAILABLE``) carrying the typed evidence code:
    nothing is fabricated (GAP-8).
    """
    detectors = scope_detectors(scope)
    visual = _compose_visual_evidence(
        session,
        scope=scope,
        detectors=detectors,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
    )
    args: dict[str, dict[str, Any]] = {}
    for name in detectors:
        if name in ("audio_missing", "av_sync_drift"):
            envelope = _audio_envelope_from_attach(
                session,
                workspace_id=workspace_id,
                video_item_id=video_item_id,
            )
            args[name] = {
                "checkpoint": envelope["checkpoint"],
                "published": envelope.get("published"),
                "error": None,
                "checkpoint_ref": "s11-qc-check-runs",
            }
            if name == "av_sync_drift":
                args[name]["scene_timeline"] = _scene_timeline(session, video_item_id)
            continue
        if name in visual:
            args[name] = dict(visual[name])
            continue
        raise QcCheckRunSubmitError(
            QC_RUN_EVIDENCE_UNAVAILABLE,
            f"no server-side evidence composition path for scope {scope!r} "
            f"detector {name!r}; refusing to fabricate check inputs",
            details={"scope": scope, "detector": name},
        )
    return args


def _evidence_managed_root() -> Any:
    """The public managed-artifact root the evidence reader verifies bytes in.

    Resolved through the application's OWN public accessor
    (``app.api.deps.get_managed_root``) — the same root every other server
    component (worker, reconciler, APIs, manifests) resolves through.  A
    private fallback here would let the evidence reader verify bytes against a
    root the rest of the application never writes to, which reads as
    "artifact missing" for evidence that is present.
    """
    from app.api.deps import get_managed_root

    return get_managed_root()


def _compose_visual_evidence(
    session: Session,
    *,
    scope: str,
    detectors: Sequence[str],
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> dict[str, dict[str, Any]]:
    """Compose the non-audio band from persisted, integrity-checked evidence.

    The audio-only band is untouched (returns an empty map without touching
    the evidence reader — the existing audio-only path keeps working).  Any
    refusal is surfaced as ``QC_RUN_EVIDENCE_UNAVAILABLE`` whose message and
    details carry the TYPED evidence code (missing / stale / foreign /
    malformed / tampered / dependency) plus, when a fact has no producer,
    the exact dependency report.
    """
    if not any(name not in ("audio_missing", "av_sync_drift") for name in detectors):
        return {}
    from app.services.qc_evidence import QcEvidenceError, compose_visual_band

    try:
        return compose_visual_band(
            session,
            managed_root=_evidence_managed_root(),
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
    except QcEvidenceError as exc:
        details = dict(exc.details)
        details["scope"] = scope
        raise QcCheckRunSubmitError(
            QC_RUN_EVIDENCE_UNAVAILABLE,
            f"{exc.code}: {exc.message}",
            details=details,
        ) from exc


def _scene_timeline(session: Session, video_item_id: str) -> dict[str, Any] | None:
    item = session.get(VideoItem, video_item_id)
    if item is None or item.duration_ms is None:
        return None
    return {"duration_seconds": float(item.duration_ms) / 1000.0}


def _audio_envelope_from_attach(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
) -> dict[str, Any]:
    """Latest completed ATTACH_ORIGINAL_AUDIO attempt result → T03E envelope.

    Reads the append-only JobAttempt history through the existing
    repository; only a COMPLETED attach job's SUCCESSFUL attempt result is
    authoritative evidence.
    """
    from app.persistence.jobs import JobRepository

    repo = JobRepository(session)
    jobs = repo.list_jobs(
        workspace_id,
        owner_type="video_item",
        owner_id=video_item_id,
        limit=20,
    )
    for job in jobs:
        if job.job_type != "ATTACH_ORIGINAL_AUDIO":
            continue
        if job.state != "completed":
            continue
        for attempt in repo.list_attempts(job.id, limit=20):
            if attempt.error is not None:
                continue
            result = attempt.result or {}
            remux = result.get("remux")
            checkpoint = remux.get("checkpoint") if isinstance(remux, dict) else None
            if isinstance(checkpoint, dict):
                return {
                    "checkpoint": checkpoint,
                    "published": result.get("published"),
                }
    raise QcCheckRunSubmitError(
        QC_RUN_EVIDENCE_UNAVAILABLE,
        "video has no completed original-audio evidence to compose the "
        "audio check inputs from",
        details={
            "workspace_id": workspace_id,
            "video_item_id": video_item_id,
        },
    )


def submit_run_qc_checks(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    scope: str,
    detector_args: Mapping[str, Mapping[str, Any]],
    generation: str = "1",
    deadline_sec: float | None = None,
    capture_cap_bytes: int | None = None,
) -> QcCheckRunSubmitResult:
    """Create the durable RUN_QC_CHECKS Job for one VideoItem (server-owned).

    The idempotency key embeds the current video evidence fingerprint +
    policy content hash + scope; an ACTIVE duplicate raises
    ``IdempotencyKeyInUse`` (fail closed), a COMPLETED duplicate reuses the
    same Job (``reused=True``).
    """
    if not workspace_id or not project_id or not video_item_id:
        raise QcCheckRunSubmitError(
            QC_RUN_UNKNOWN_SCOPE,
            "workspace_id, project_id and video_item_id are required",
        )
    try:
        scope_detectors(scope)  # validate scope first (fail closed)
    except RunQcChecksError as exc:
        raise QcCheckRunSubmitError(
            exc.code, exc.message, details=exc.details
        ) from exc

    with session_factory() as session:
        video_import._validate_ownership(  # noqa: SLF001 - established contract
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        from app.persistence.jobs import JobRepository
        from app.persistence.models import Job as JobORM

        fp = evidence_fingerprint(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            generation=generation,
            project_id=project_id,
        )
        binding = output_evidence_binding(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        policy = policy_bundle()
        scope_fp = scope_fingerprint(scope)
        detectors = scope_detectors(scope)

        # Band completeness checked BEFORE any Job row (fail fast; the
        # orchestrator must never be submitted with a half band).
        missing = [name for name in detectors if name not in detector_args]
        if missing:
            raise QcCheckRunSubmitError(
                QC_RUN_MISSING_ARGS,
                f"detector_args missing for band members: {sorted(missing)}",
                details={"missing": sorted(missing)},
            )
        unexpected = [name for name in detector_args if name not in detectors]
        if unexpected:
            raise QcCheckRunSubmitError(
                QC_RUN_MISSING_ARGS,
                f"detector_args supplied for detectors outside the band: "
                f"{sorted(unexpected)}",
                details={"unexpected": sorted(unexpected)},
            )

        source_fp = source_artifact_fingerprint(session, video_item_id=video_item_id)

        manifest: dict[str, Any] = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "scope": scope,
            "scope_fingerprint": scope_fp,
            "evidence_fingerprint": fp,
            "policy_id": policy["policy_id"],
            "policy_content_hash": policy["policy_content_hash"],
            "source_generation": generation,
            "source_artifact_id": source_fp["source_artifact_id"],
            "source_sha256": source_fp["source_sha256"],
            "evidence_binding": binding,
            "deadline_sec": float(deadline_sec or DEFAULT_DEADLINE_SEC),
            "capture_cap_bytes": int(capture_cap_bytes or DEFAULT_CAPTURE_CAP_BYTES),
            "detector_args": {
                name: dict(detector_args[name]) for name in detectors
            },
        }

        idempotency_key = (
            f"{JOB_TYPE_RUN_QC_CHECKS}:video_item:{video_item_id}:"
            f"{fp}:{policy['policy_content_hash']}:{scope}"
        )

        completed_exists = session.scalar(
            select(JobORM.id).where(
                JobORM.workspace_id == workspace_id,
                JobORM.idempotency_key == idempotency_key,
                JobORM.input_generation == generation,
                JobORM.state == "completed",
            )
        )

        try:
            job = JobRepository(session).create_job(
                workspace_id=workspace_id,
                job_type=JOB_TYPE_RUN_QC_CHECKS,
                owner_type="video_item",
                owner_id=video_item_id,
                input_manifest=manifest,
                idempotency_key=idempotency_key,
                input_generation=generation,
                steps=run_qc_checks_steps(),
                actor="api",
            )
        except IdempotencyKeyInUse:
            session.rollback()
            raise
        session.commit()
        return QcCheckRunSubmitResult(
            job_id=job.id,
            reused=completed_exists is not None,
            idempotency_key=idempotency_key,
            evidence_fingerprint=fp,
        )
