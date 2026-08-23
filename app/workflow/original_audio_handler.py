"""Durable ATTACH_ORIGINAL_AUDIO job wiring (S11-T01C).

Thin adapter between the S02 durable ``DurableWorker`` and the S11-T01B
pure remux engine (:mod:`app.services.original_audio_remux`).  The engine
owns the remux/transcode policy (ORIGINAL_AUDIO_REMUX_CONTRACT §4); this
module only resolves the authoritative managed source, drives the engine,
and publishes its deterministic output as a managed artifact:

- **Submit** (:func:`submit_attach_original_audio`) creates the durable
  ``ATTACH_ORIGINAL_AUDIO`` Job with an **owner-scoped** idempotency key
  embedding the source content identity
  (``ATTACH_ORIGINAL_AUDIO:video_item:<video_item_id>:<source_sha256>:<generation>``
  — the GENERATE_PROXY pattern).  A completed duplicate returns the existing
  Job; an active duplicate raises ``IdempotencyKeyInUse``.  The request path
  NEVER accepts a filesystem path: the source is resolved from the
  VideoItem's ready ``source`` artifact authority, re-validated at run time.
- **Source phase**: ownership chain + source-artifact validity are
  re-validated in one transaction (S05-T02 correction #2 pattern) before any
  managed write; the resolved managed file must still match its recorded
  size evidence.
- **Remux phase**: calls :func:`app.services.original_audio_remux.remux_original_audio`
  with the managed source and a staging output directory under the managed
  root.  A cooperative cancel-watcher thread bridges the durable cancel flag
  (``ctx.is_cancelled()``) to the engine's ``threading.Event`` so a durable
  cancel terminates the FULL ffmpeg child tree.  The engine validates the
  staged output BEFORE publishing it under the final name inside its managed
  directory (atomic ``os.replace``), so a partial file is never visible.
- **Publish phase**: registers the engine's validated output under the
  final managed artifact path (verified checksum before adoption) as a
  managed artifact row (``kind='audio'``, ``state='ready'``) with an
  :class:`~app.persistence.models.ArtifactOwner` link
  (``owner_type='video_item'``, purpose ``original_audio``) in ONE
  transaction.  Replay-safe: an existing verified final file/row is reused;
  a DB failure removes only files THIS attempt created.
- **Completion gate**: an ``output_validator`` re-verifies the published
  audio on disk (existence, sha256, size) after the handler returns, so the
  Job reaches ``completed`` only after verified publication (contract §9.3).

No new schema, no migration, no change to durable worker semantics, and no
change to the analysis generation: the source bytes are read-only end-to-end
(the engine itself proves the source-unmutated invariant), probe JSON of the
import pipeline is never rewritten, and DISCOVER_OBJECTS state is untouched.

Checkpoint payloads carry ONLY content-derived evidence plus normalized
relative paths — no absolute managed path ever becomes durable (the engine's
result carries absolute display paths; they are stripped before
``write_checkpoint``).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.artifacts import (
    ManagedPathError,
    ManagedRoot,
    hash_file,
)
from app.persistence.jobs import StepInput
from app.persistence.models import Artifact, ArtifactOwner
from app.services import video_import
from app.services.original_audio_remux import (
    CODE_CANCELLED as ENGINE_CODE_CANCELLED,
)
from app.services.original_audio_remux import (
    OUTPUT_FILENAME_DEFAULT,
    OriginalAudioRemuxError,
    OriginalAudioRemuxResult,
    remux_original_audio,
)
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "ARTIFACT_PURPOSE_ORIGINAL_AUDIO",
    "ATTACH_STEP_CODE",
    "CODE_ATTACH_VALIDATION_FAILED",
    "CODE_CANCELLED",
    "CODE_ENGINE_FAILED",
    "CODE_PUBLICATION_FAILED",
    "CODE_SOURCE_ARTIFACT_NOT_FOUND",
    "CODE_SOURCE_NOT_READY",
    "CODE_SOURCE_OWNER_MISMATCH",
    "AttachAudioError",
    "AttachSubmitResult",
    "JOB_TYPE_ATTACH_ORIGINAL_AUDIO",
    "NO_AUDIO_SCHEMA_VERSION",
    "REMUX_TIMEOUT_SECONDS",
    "attach_original_audio_handler",
    "attach_original_audio_steps",
    "register_attach_original_audio_handler",
    "submit_attach_original_audio",
]

#: Stable job type for the original-audio attach slice (S11 frozen §3-5).
JOB_TYPE_ATTACH_ORIGINAL_AUDIO = "ATTACH_ORIGINAL_AUDIO"

#: The single sync step that executes the whole attach
#: (source → remux → publish).  Mirrors GENERATE_PROXY's one-step plan.
ATTACH_STEP_CODE = "attach"

#: Schema version of this handler's checkpoint payload.
NO_AUDIO_SCHEMA_VERSION = 1

#: Artifact-owner purpose for a VideoItem's canonical original audio.
ARTIFACT_PURPOSE_ORIGINAL_AUDIO = "original_audio"

#: Wall-clock budget handed to the bounded remux engine (seconds).  The
#: engine enforces only its REMAINING budget on every wait/reap/join.
REMUX_TIMEOUT_SECONDS = 600

# ── Stable error codes ───────────────────────────────────────────────────────

#: Source artifact missing/not-in-workspace (video_proxy SOURCE_* pattern).
CODE_SOURCE_ARTIFACT_NOT_FOUND = "SOURCE_ARTIFACT_NOT_FOUND"
#: Source artifact not a ready video with recorded checksum.
CODE_SOURCE_NOT_READY = "SOURCE_NOT_READY"
#: Source artifact not linked to the VideoItem with purpose ``source``.
CODE_SOURCE_OWNER_MISMATCH = "SOURCE_OWNER_MISMATCH"
#: Engine refused the operation (stable engine code preserved in details).
CODE_ENGINE_FAILED = "ENGINE_FAILED"
#: Published audio failed the post-publication verification.
CODE_ATTACH_VALIDATION_FAILED = "ATTACH_VALIDATION_FAILED"
#: Publication transaction/filesystem failure.
CODE_PUBLICATION_FAILED = "PUBLICATION_FAILED"
#: Durable cancellation.
CODE_CANCELLED = "CANCELLED"


class AttachAudioError(Exception):
    """A stable, actionable ATTACH_ORIGINAL_AUDIO failure.

    ``code`` is the machine-readable stable code (engine codes are
    preserved verbatim for engine-originated failures); ``details`` carries
    structured context that survives into the worker's error envelope.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class AttachSubmitResult:
    """Result of :func:`submit_attach_original_audio` — Job id + reuse flag."""

    def __init__(self, job_id: str, reused: bool) -> None:
        self.job_id = job_id
        self.reused = reused


# ── Managed paths / deterministic ids ────────────────────────────────────────


def _managed_for(ctx: WorkerContext) -> ManagedRoot:
    """ManagedRoot bound to the Job's manifest managed root."""
    return ManagedRoot(
        Path(str(ctx.input_manifest.get("managed_root") or "artifacts"))
    )


def _remux_dir_relative_path(ctx: WorkerContext) -> str:
    """Managed relative directory receiving the engine's published output.

    The engine owns staging + validation + atomic publish INSIDE this one
    managed directory; the adapter then adopts its output at the final
    artifact relative path (:func:`_final_relative_path`).
    """
    return f"staging/{ctx.job_id}/{ctx.step_code}/engine"


def _final_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the published audio (contract §9.2)."""
    workspace_id = str(ctx.input_manifest.get("workspace_id") or "default")
    return f"artifacts/{workspace_id}/audio/{ctx.job_id}/{ctx.step_code}/{name}"


def _artifact_id(ctx: WorkerContext, final_rel: str) -> str:
    """Deterministic artifact id for (job, step, path) — replay-safe (§8.3)."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_OID,
            f"attach-original-audio:{ctx.job_id}:{final_rel}",
        )
    )


def _remove_file(path: Path) -> None:
    """Best-effort removal of a managed file (never raises)."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _wrap_managed_errors(exc: ManagedPathError) -> AttachAudioError:
    """Map a containment failure to a stable envelope."""
    return AttachAudioError(
        CODE_ATTACH_VALIDATION_FAILED,
        f"managed path rejected: {exc}",
        details={"reason": str(exc)},
    )


# ── Source validation (submit + run-time) ────────────────────────────────────


def _validate_source_artifact(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
    source_artifact_id: str | None,
) -> Artifact:
    """Verify the managed source artifact authority for the VideoItem.

    The canonical source is the VideoItem's OWN ready video source artifact.
    R5-P1: the VideoItem's CURRENT ``source_artifact_id`` column is the
    SINGLE authority — *source_artifact_id* (e.g. the id pinned in a stale
    Job manifest) must equal it exactly.  A pointer that moved between
    submit and run rejects the stale id (``SOURCE_OWNER_MISMATCH``) so no
    audio is ever derived from, or published for, a detached artifact.  The
    client never supplies a filesystem path.

    Raises:
        AttachAudioError: ``SOURCE_ARTIFACT_NOT_FOUND`` /
            ``SOURCE_NOT_READY`` / ``SOURCE_OWNER_MISMATCH``.
    """
    from app.persistence.models import VideoItem

    item = session.get(VideoItem, video_item_id)
    current_id = item.source_artifact_id if item is not None else None
    if not current_id:
        raise AttachAudioError(
            CODE_SOURCE_ARTIFACT_NOT_FOUND,
            f"video item {video_item_id!r} has no source artifact to attach "
            "original audio from",
            details={"video_item_id": video_item_id},
        )
    if source_artifact_id and source_artifact_id != current_id:
        raise AttachAudioError(
            CODE_SOURCE_OWNER_MISMATCH,
            "video item source authority changed since this job was "
            "submitted; refusing to run against the stale artifact",
            details={
                "manifest_source_artifact_id": source_artifact_id,
                "current_source_artifact_id": current_id,
                "video_item_id": video_item_id,
            },
        )
    # Manifest id (when present) already equals the current authority.
    source_artifact_id = current_id
    artifact = session.get(Artifact, source_artifact_id)
    if artifact is None or artifact.workspace_id != workspace_id:
        raise AttachAudioError(
            CODE_SOURCE_ARTIFACT_NOT_FOUND,
            f"source artifact {source_artifact_id!r} not found in workspace "
            f"{workspace_id!r}",
            details={"source_artifact_id": source_artifact_id},
        )
    if artifact.kind != "video" or artifact.state != "ready" or not artifact.sha256:
        raise AttachAudioError(
            CODE_SOURCE_NOT_READY,
            f"source artifact {source_artifact_id!r} is not a ready video "
            f"with a recorded checksum (kind={artifact.kind!r}, "
            f"state={artifact.state!r})",
            details={
                "artifact_id": artifact.id,
                "kind": artifact.kind,
                "state": artifact.state,
                "has_sha256": artifact.sha256 is not None,
            },
        )
    owner = session.get(
        ArtifactOwner,
        (
            artifact.id,
            "video_item",
            video_item_id,
            video_import.ARTIFACT_PURPOSE_SOURCE,
        ),
    )
    if owner is None:
        raise AttachAudioError(
            CODE_SOURCE_OWNER_MISMATCH,
            f"source artifact {artifact.id!r} is not linked as the source of "
            f"video item {video_item_id!r}",
            details={"artifact_id": artifact.id, "video_item_id": video_item_id},
        )
    return artifact


# ── The ATTACH_ORIGINAL_AUDIO handler ────────────────────────────────────────


def attach_original_audio_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one ATTACH_ORIGINAL_AUDIO Job: source → remux → publish.

    The handler resumes from the step checkpoint: valid source evidence is
    reused, a completed engine run is verified and reused, and a published
    effect is verified and skipped.  Every phase observes the durable cancel
    flag; the remux phase bridges it into the engine's cooperative
    cancellation so the ffmpeg child tree is terminated.
    """
    managed = _managed_for(ctx)
    cp = ctx.checkpoint
    if not isinstance(cp, dict):
        cp = {"schema_version": NO_AUDIO_SCHEMA_VERSION}

    source_ev = _source_phase(ctx, cp, managed)
    cp = {**cp, "source": source_ev, "phase": "source"}
    remux_ev = _remux_phase(ctx, cp, managed, source_ev)
    cp = {**cp, "remux": remux_ev, "phase": "remux"}
    published = _publish_phase(ctx, cp, managed, remux_ev, source_ev)
    return {"source": source_ev, "remux": remux_ev, "published": published}


def _raise_if_cancelled(ctx: WorkerContext, phase: str) -> None:
    """Fail with the stable cancel code when the durable flag is set."""
    if ctx.is_cancelled():
        raise AttachAudioError(
            CODE_CANCELLED,
            f"original-audio attach cancelled before {phase} phase",
            details={"phase": phase},
        )


def _strip_engine_paths(ctx: WorkerContext, result: OriginalAudioRemuxResult) -> dict[str, Any]:
    """Content-derived engine evidence WITHOUT absolute display paths.

    Only the checkpoint (already path-free by engine contract), codecs,
    durations and statuses become durable; ``source_path`` /
    ``output_path`` are absolute display fields and never persisted.  The
    managed relative location is re-derived at run time from the artifact
    row / job manifest instead.
    """
    checkpoint = dict(result.checkpoint or {})
    # The engine publishes inside the adapter-owned managed directory under
    # a fixed default name; re-derive its RELATIVE location for durable
    # storage instead of persisting any absolute display path.
    evidence: dict[str, Any] = {
        "schema_version": NO_AUDIO_SCHEMA_VERSION,
        "status": result.status,
        "engine_schema_version": checkpoint.get("schema_version"),
        "checkpoint": checkpoint,
    }
    if result.output_path is not None:
        evidence["produced_relative_path"] = (
            f"{_engine_dir_relative(ctx)}/{OUTPUT_FILENAME_DEFAULT}"
        )
        evidence["output_sha256"] = result.output_sha256
        evidence["output_size_bytes"] = result.output_size_bytes
    for key in (
        "source_sha256",
        "source_size_bytes",
        "post_remux_source_sha256",
        "source_audio_codec",
        "output_audio_codec",
        "source_audio_duration",
        "output_audio_duration",
        "audio_time_base",
        "video_codec",
    ):
        value = getattr(result, key, None)
        if value is not None:
            evidence[key] = value
    return evidence


def _engine_dir_relative(ctx: WorkerContext) -> str:
    """Managed relative directory the engine publishes into (remux phase)."""
    return _remux_dir_relative_path(ctx)


class _DurableCancelWatcher:
    """Bridge the durable cancel flag to the engine's threading.Event.

    A tiny daemon thread polls ``ctx.is_cancelled()`` (a DB read per tick)
    and sets the engine event when the Job enters ``cancelling``; the
    engine's bounded run then kills the FULL ffmpeg child tree.  Stopped
    deterministically from the adapter's ``__exit__``/finally paths.
    """

    def __init__(
        self,
        is_cancelled: Callable[[], bool],
        cancel_event: threading.Event,
        poll_interval: float = 0.25,
    ) -> None:
        self._is_cancelled = is_cancelled
        self._event = cancel_event
        self._interval = max(0.05, poll_interval)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="attach-audio-cancel-watch", daemon=True
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if self._is_cancelled():
                    self._event.set()
                    return
            except Exception:  # noqa: BLE001 - watcher must never crash the run
                continue

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)


def _source_phase(
    ctx: WorkerContext, cp: dict[str, Any], managed: ManagedRoot
) -> dict[str, Any]:
    """Source phase: re-validate ownership + source artifact authority.

    R5-P1: the VideoItem's CURRENT ``source_artifact_id`` is re-read from
    the database BEFORE any checkpointed evidence is trusted — bytes that
    still hash correctly are irrelevant once the item's authority moved to
    another artifact.  Fresh runs always re-resolve from the database
    (never from a client-supplied path).
    """
    manifest = ctx.input_manifest
    video_item_id = str(manifest["video_item_id"])
    source_ev = cp.get("source")
    if isinstance(source_ev, dict):
        # Authority revalidation precedes every byte-level check (R5-P1 #4):
        # a bytes-valid checkpoint for a DETACHED artifact must fail closed.
        if ctx.session_factory is None:
            raise AttachAudioError(
                CODE_PUBLICATION_FAILED,
                "worker context has no session factory; cannot revalidate "
                "source authority",
                details={"phase": "source"},
            )
        from app.persistence.models import VideoItem

        with ctx.session_factory() as session:
            item = session.get(VideoItem, video_item_id)
            current_id = item.source_artifact_id if item is not None else None
        if current_id is None or current_id != str(
            source_ev.get("artifact_id") or ""
        ):
            _purge_run_staging(ctx, managed)
            raise AttachAudioError(
                CODE_SOURCE_OWNER_MISMATCH,
                "video item source authority no longer matches the "
                "checkpointed source evidence",
                details={
                    "checkpointed_artifact_id": source_ev.get("artifact_id"),
                    "current_source_artifact_id": current_id,
                    "video_item_id": video_item_id,
                },
            )
        if _source_evidence_valid(managed, source_ev):
            return source_ev
    _raise_if_cancelled(ctx, "source")
    if ctx.session_factory is None:
        raise AttachAudioError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot resolve the source",
            details={"phase": "source"},
        )
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    source_artifact_id = manifest.get("source_artifact_id")
    source_artifact_id = (
        str(source_artifact_id) if source_artifact_id else None
    )

    with ctx.session_factory() as session:
        # Ownership chain re-validated at run time (correction #2 pattern):
        # the video item may have moved/archived between submit and run.
        video_import._validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        artifact = _validate_source_artifact(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            source_artifact_id=source_artifact_id,
        )
        rel = artifact.relative_path
        sha256 = artifact.sha256 or ""
        size = artifact.size_bytes

    try:
        src_path = managed.resolve(rel)
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    if not src_path.is_file():
        raise AttachAudioError(
            CODE_SOURCE_NOT_READY,
            f"managed source file missing at {rel}",
            details={"relative_path": rel},
        )
    actual_size = src_path.stat().st_size
    if size is not None and actual_size != size:
        raise AttachAudioError(
            CODE_SOURCE_NOT_READY,
            f"managed source file size {actual_size} does not match the "
            f"recorded artifact size {size}",
            details={"relative_path": rel, "expected_size": size},
        )

    source_ev = {
        "artifact_id": artifact.id,
        "relative_path": rel,
        "sha256": sha256,
        "size_bytes": size,
    }
    # Source-artifact authority (R4-P1): the on-disk bytes must hash to the
    # recorded artifact checksum BEFORE this run checkpoints them as its
    # input — a same-size mutation is never accepted.
    disk_sha256 = _hash_or_none(src_path)
    if disk_sha256 != sha256:
        raise AttachAudioError(
            CODE_SOURCE_NOT_READY,
            "managed source file content does not match the recorded "
            "artifact checksum",
            details={
                "relative_path": rel,
                "expected_sha256": sha256,
                "actual_sha256": disk_sha256,
            },
        )
    ctx.write_checkpoint({**cp, "source": source_ev, "phase": "source"})
    return source_ev


def _hash_or_none(path: Path) -> str | None:
    """SHA-256 of ``path``, or None when it cannot be read."""
    try:
        return hash_file(path)
    except OSError:
        return None


def _source_evidence_valid(managed: ManagedRoot, source_ev: dict[str, Any]) -> bool:
    """True when the checkpointed source evidence still matches on disk.

    Both the recorded size AND the recorded SHA-256 are re-verified against
    the current bytes (R4-P1): a same-size mutation of the managed source
    invalidates the checkpoint and forces re-resolution from the database.
    """
    rel = source_ev.get("relative_path")
    if not isinstance(rel, str):
        return False
    try:
        src_path = managed.resolve(rel)
    except ManagedPathError:
        return False
    if not src_path.is_file():
        return False
    recorded_size = source_ev.get("size_bytes")
    if recorded_size is not None:
        try:
            if src_path.stat().st_size != int(recorded_size):
                return False
        except OSError:
            return False
    recorded_sha256 = source_ev.get("sha256")
    if not isinstance(recorded_sha256, str) or not recorded_sha256:
        return False
    return _hash_or_none(src_path) == recorded_sha256


def _remux_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    source_ev: dict[str, Any],
) -> dict[str, Any]:
    """Remux phase: drive the bounded T01B engine against the managed source.

    Reuse rule: checkpointed engine evidence whose recorded output still
    hashes to the same sha256 AND whose source checksum matches is reused —
    a retry after a publication failure must NOT duplicate artifacts (the
    engine output itself is deterministic).  Anything else re-runs the
    engine from scratch (its staging leftovers are its own to clean).
    """
    remux_ev = cp.get("remux")
    if isinstance(remux_ev, dict) and _remux_evidence_valid(
        managed, source_ev, remux_ev, cp.get("published")
    ):
        return remux_ev
    _raise_if_cancelled(ctx, "remux")

    try:
        src_path = managed.resolve(str(source_ev["relative_path"]))
        remux_dir = managed.resolve(_remux_dir_relative_path(ctx))
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    # Crash leftovers in THIS Job's engine directory are garbage before any
    # re-run (the engine's own staging files are unique-named and internal).
    _cleanup_engine_dir(ctx, managed)

    cancel_event = threading.Event()
    watcher = _DurableCancelWatcher(ctx.is_cancelled, cancel_event)
    watcher.start()
    try:
        result = remux_original_audio(
            src_path,
            remux_dir,
            deadline=None,
            timeout_seconds=REMUX_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
    except OriginalAudioRemuxError as exc:
        # The engine cleans its own staging on bounded failures but a kill
        # racing the post-publish probe can leave a partial ``.staging``*
        # file behind in THIS Job's engine directory; it is garbage either
        # way (never the checkpointed ``original_audio.mp4`` output).
        with contextlib.suppress(Exception):
            _cleanup_engine_dir(ctx, managed)
        if exc.code == ENGINE_CODE_CANCELLED:
            raise AttachAudioError(
                CODE_CANCELLED,
                "original-audio attach cancelled during the remux",
                details={"engine_code": exc.code},
            ) from exc
        # Fail closed with the engine's stable code preserved verbatim.
        raise AttachAudioError(
            CODE_ENGINE_FAILED,
            f"remux engine refused: {exc.message}",
            details={
                "engine_code": exc.code,
                "engine_action": exc.action(),
                **({"engine_details": dict(exc.details)} if exc.details else {}),
            },
        ) from exc
    finally:
        watcher.stop()

    if ctx.is_cancelled():
        # Zero-residue (R6-F2): the engine returned SUCCESS, so its output
        # already exists in THIS Job's engine staging directory.  A durable
        # cancel observed here is terminal — purge this Job's staging
        # (never another Job's) BEFORE raising, and do NOT checkpoint any
        # remux/published evidence for a cancelled run.
        _purge_run_staging(ctx, managed)
        raise AttachAudioError(
            CODE_CANCELLED,
            "original-audio attach cancelled right after the remux",
            details={"phase": "remux"},
        )

    evidence = _strip_engine_paths(ctx, result)
    # Post-engine source-integrity gate (R4-P1): the engine's recorded
    # input/post-remux identities must match THIS run's source evidence;
    # any drift is fail-closed before anything is checkpointed as usable.
    _verify_source_identity(ctx, managed, source_ev, evidence)
    ctx.write_checkpoint({**cp, "remux": evidence, "phase": "remux"})
    return evidence


def _verify_source_identity(
    ctx: WorkerContext,
    managed: ManagedRoot,
    source_ev: dict[str, Any],
    remux_ev: dict[str, Any],
) -> None:
    """Fail closed when engine-recorded source identity drifts (R4-P1 #3).

    Both the engine's ``source_sha256`` and its ``post_remux_source_sha256``
    must equal the validated source evidence checksum.  On mismatch the
    engine staging owned by THIS run is purged (the produced output no
    longer describes the authoritative input) and a stable permanent error
    is raised — zero publication.
    """
    expected = str(source_ev.get("sha256") or "")
    actual = remux_ev.get("source_sha256")
    post = remux_ev.get("post_remux_source_sha256")
    if actual == expected and (post is None or post == expected):
        return
    _purge_run_staging(ctx, managed)
    raise AttachAudioError(
        CODE_ENGINE_FAILED,
        "remux engine source identity does not match the validated source "
        "artifact; refusing to continue",
        details={
            "expected_sha256": expected,
            "engine_source_sha256": (
                actual if isinstance(actual, str) else None
            ),
            "engine_post_remux_source_sha256": (
                post if isinstance(post, str) else None
            ),
        },
    )


def _purge_run_staging(ctx: WorkerContext, managed: ManagedRoot) -> None:
    """Remove THIS Job's engine staging directory entirely.

    Used when the run's own output can no longer be trusted (source
    identity drift): unlike :func:`_cleanup_engine_dir` nothing is kept —
    the produced output describes bytes that are no longer authoritative.
    Only ``staging/<job_id>/<step_code>/engine`` is ever touched.
    """
    try:
        engine_dir = managed.resolve(_remux_dir_relative_path(ctx))
    except ManagedPathError:
        return
    if engine_dir.is_dir():
        shutil.rmtree(engine_dir, ignore_errors=True)
    # Drop now-empty parents (staging/<job>/<step>, staging/<job>) so a
    # failed/cancelled run leaves no directory shells either.  ``rmdir``
    # only succeeds on EMPTY directories, so a sibling Job's populated
    # subtree can never be crossed.
    with contextlib.suppress(OSError):
        step_dir = engine_dir.parent  # staging/<job_id>/<step_code>
        step_dir.rmdir()
    with contextlib.suppress(OSError):
        job_root = step_dir.parent  # staging/<job_id>
        job_root.rmdir()


def _remux_evidence_valid(
    managed: ManagedRoot,
    source_ev: dict[str, Any],
    remux_ev: dict[str, Any],
    published_ev: Any = None,
) -> bool:
    """True when the checkpointed engine evidence still describes reality.

    ``produced_relative_path`` points into this Job's staging tree, which
    only survives while the output has NOT been adopted into the artifacts
    tree yet.  Once publication happened, the evidence stays reusable via
    the checkpointed ``published`` record (same sha256/size, adopted final
    location) — a restart after publication never re-runs the engine.
    """
    if remux_ev.get("schema_version") != NO_AUDIO_SCHEMA_VERSION:
        return False
    if remux_ev.get("status") != "NO_AUDIO_PRESENT":
        # An audio-producing run is reusable ONLY while its output still
        # exists somewhere durable and hashes to the recorded value: either
        # (a) still in the staging tree pre-publication, or (b) already
        # adopted at the checkpointed published location post-publication.
        recorded = remux_ev.get("output_sha256")
        candidates: list[Path] = []
        rel = remux_ev.get("produced_relative_path")
        if isinstance(rel, str):
            with contextlib.suppress(ManagedPathError):
                candidates.append(managed.resolve(rel))
        if (
            isinstance(published_ev, dict)
            and isinstance(published_ev.get("final_rel"), str)
        ):
            with contextlib.suppress(ManagedPathError):
                candidates.append(managed.resolve(str(published_ev["final_rel"])))
        if not any(
            c.is_file() and hash_file(c) == recorded
            for c in candidates
            if isinstance(recorded, str)
        ):
            return False
    # The SOURCE must be unchanged since the engine ran (content identity of
    # the whole operation); otherwise the evidence describes another input
    # (R4-P1 #4: both the input and post-remux identities are required).
    return (
        remux_ev.get("source_sha256") == source_ev.get("sha256")
        and remux_ev.get("post_remux_source_sha256") in (None, source_ev.get("sha256"))
    )


def _publish_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    remux_ev: dict[str, Any],
    source_ev: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish phase: adopt the validated engine output as an artifact row.

    For ``NO_AUDIO_PRESENT`` there is nothing on disk to publish — the
    explicit metadata outcome IS the effect set (no fabricated audio ever).
    Otherwise the engine's already-validated file is copied once into the
    final managed artifact path (checksum verified before adoption), and
    artifact + owner rows are committed in ONE transaction.  Replay-safe:
    an existing verified final file/row is reused; a failure removes only
    files THIS attempt created.
    """
    published = cp.get("published")
    if isinstance(published, dict) and published.get("artifact_id"):
        return published
    if ctx.is_cancelled():
        # Zero-residue (R6-F2): the engine output already exists in THIS
        # Job's staging (remux checkpointed it).  Purge this Job's staging
        # before raising — never another Job's — and leave the checkpoint
        # without any published record.
        _purge_run_staging(ctx, managed)
        raise AttachAudioError(
            CODE_CANCELLED,
            "original-audio attach cancelled before publish",
            details={"phase": "publish"},
        )
    video_item_id = str(ctx.input_manifest["video_item_id"])

    status = str(remux_ev.get("status"))

    if status == "NO_AUDIO_PRESENT":
        published = {
            "no_audio_present": True,
            "artifact_id": None,
            "final_rel": None,
            "sha256": None,
            "size_bytes": None,
            "status": status,
        }
        ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
        return published

    produced_rel = remux_ev.get("produced_relative_path")
    if not isinstance(produced_rel, str):
        raise AttachAudioError(
            CODE_ATTACH_VALIDATION_FAILED,
            "remux evidence carries no produced output path",
            details={"status": status},
        )
    sha256 = str(remux_ev["output_sha256"])
    size = int(remux_ev["output_size_bytes"])
    name = Path(produced_rel).name
    final_rel = _final_relative_path(ctx, name)

    try:
        produced_path = managed.resolve(produced_rel)
        final_path = managed.resolve(final_rel)
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc

    # Pre-publication source-integrity gate (R4-P1 #4 + R5-P1 #5): the
    # item's CURRENT authority artifact id AND its recorded sha256 are
    # re-read from the database and matched against this run's source and
    # remux evidence; the managed source is re-hashed one last time.
    # Nothing is published on any drift, and this run's engine staging
    # (output describing non-authoritative input) is purged.
    if isinstance(source_ev, dict):
        expected = str(source_ev.get("sha256") or "")
        expected_id = str(source_ev.get("artifact_id") or "")
        src_rel = source_ev.get("relative_path")
        current = None
        if ctx.session_factory is not None:
            from app.persistence.models import VideoItem

            with ctx.session_factory() as session:
                item = session.get(VideoItem, video_item_id)
                current_id = (
                    item.source_artifact_id if item is not None else None
                )
                art = session.get(Artifact, expected_id)
            if current_id != expected_id or art is None or (
                art.sha256 or ""
            ) != expected:
                _purge_run_staging(ctx, managed)
                raise AttachAudioError(
                    CODE_SOURCE_OWNER_MISMATCH,
                    "video item source authority changed before "
                    "publication; refusing to publish output derived "
                    "from a detached artifact",
                    details={
                        "expected_artifact_id": expected_id,
                        "current_source_artifact_id": current_id,
                        "artifact_sha256": (
                            art.sha256 if art is not None else None
                        ),
                        "expected_sha256": expected,
                    },
                )
        if (
            isinstance(src_rel, str)
            and remux_ev.get("source_sha256") == expected
            and remux_ev.get("post_remux_source_sha256") in (None, expected)
        ):
            with contextlib.suppress(ManagedPathError):
                current = _hash_or_none(managed.resolve(src_rel))
        if current != expected:
            _purge_run_staging(ctx, managed)
            raise AttachAudioError(
                CODE_ENGINE_FAILED,
                "source artifact changed before publication; refusing to "
                "publish output derived from it",
                details={
                    "expected_sha256": expected,
                    "actual_sha256": current,
                },
            )

    created_final = False
    try:
        created_final = _adopt_file(managed, produced_path, final_path, sha256)
        _publish_effect(ctx, final_rel, sha256, size)
    except AttachAudioError:
        # Cleanup owns ONLY this attempt's committed bytes: the adopted
        # final file is removed only when THIS attempt created it.  The
        # produced engine file STAYS in this Job's staging tree — a same-job
        # retry/resume re-verifies it against the checkpointed checksum and
        # skips the whole remux (restart-preserves-checkpoint); a successor
        # Job owns a different staging directory and never sees it.
        if created_final:
            _remove_file(final_path)
        raise
    except Exception as exc:  # noqa: BLE001 - publication failures are permanent
        if created_final:
            _remove_file(final_path)
        raise AttachAudioError(
            CODE_PUBLICATION_FAILED,
            f"publication transaction failed: {exc}",
            details={"error_type": type(exc).__name__},
        ) from exc

    published = {
        "no_audio_present": False,
        "final_rel": final_rel,
        "artifact_id": _artifact_id(ctx, final_rel),
        "sha256": sha256,
        "size_bytes": size,
        "status": status,
    }
    ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
    return published


def _remove_produced_and_maybe_final(
    created_final: bool, produced_path: Path, final_path: Path
) -> None:
    """Best-effort cleanup owned by THIS attempt only.

    The adopted final file is removed only when this attempt created it —
    a pre-existing committed final file is never deleted (correction #4).
    """
    _remove_file(produced_path)
    if created_final:
        _remove_file(final_path)


def _cleanup_engine_dir(ctx: WorkerContext, managed: ManagedRoot) -> None:
    """Garbage-collect THIS Job's engine staging directory before a re-run.

    Crash leftovers (a killed ffmpeg's partial staging file) are never
    treated as published content; the engine always creates a fresh unique
    staging file.  Only ``staging/<job_id>/<step_code>/engine`` is touched —
    never another Job's directory, never a published artifact path.
    """
    try:
        engine_dir = managed.resolve(_remux_dir_relative_path(ctx))
    except ManagedPathError:
        return
    if not engine_dir.is_dir():
        return
    for leftover in engine_dir.iterdir():
        # Keep a checkpointed produced output (verified separately by the
        # remux-evidence reuse rule); drop everything else.
        if leftover.name == OUTPUT_FILENAME_DEFAULT:
            continue
        with contextlib.suppress(OSError):
            if leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
            else:
                leftover.unlink(missing_ok=True)


def _adopt_file(
    managed: ManagedRoot, produced_path: Path, final_path: Path, sha256: str
) -> bool:
    """Move the engine's validated output to the final artifact path.

    Returns ``True`` when THIS attempt created/moved the final file;
    ``False`` when an existing verified final file was reused (replay).
    A checksum mismatch against a pre-existing final file fails closed
    WITHOUT removing that file (it may be a previously committed ready
    artifact).
    """
    del managed  # containment was proven by both resolve() calls upstream
    if final_path.exists():
        if hash_file(final_path) != sha256:
            raise AttachAudioError(
                CODE_ATTACH_VALIDATION_FAILED,
                "final file exists but does not match the recorded audio "
                "checksum",
                details={"expected_sha256": sha256},
            )
        _remove_file(produced_path)
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(produced_path, final_path)
    except OSError as exc:
        raise AttachAudioError(
            CODE_PUBLICATION_FAILED,
            f"atomic rename into the final artifact path failed: {exc}",
            details={"final_relative_path": final_path.name},
        ) from exc
    return True


def _publish_effect(
    ctx: WorkerContext,
    final_rel: str,
    sha256: str,
    size: int,
) -> None:
    """Persist artifact row + owner link in ONE transaction (§7.1/§9.2).

    Ownership and source-artifact validity are re-validated first so a
    rejection has zero side effects inside this transaction.
    """
    if ctx.session_factory is None:
        raise AttachAudioError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot persist publication",
            details={"phase": "publish"},
        )
    manifest = ctx.input_manifest
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    video_item_id = str(manifest["video_item_id"])
    source_artifact_id = manifest.get("source_artifact_id")
    source_artifact_id = str(source_artifact_id) if source_artifact_id else None
    artifact_id = _artifact_id(ctx, final_rel)

    with ctx.session_factory() as session:
        video_import._validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        _validate_source_artifact(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            source_artifact_id=source_artifact_id,
        )

        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            artifact = Artifact(
                id=artifact_id,
                workspace_id=workspace_id,
                kind="audio",
                relative_path=final_rel,
                state="ready",
                sha256=sha256,
                size_bytes=size,
                mime_type="audio/mp4",
            )
            session.add(artifact)
        else:
            # Replay: verify the evidence; repair a partial row; a mismatched
            # row means the content changed between attempts → fail closed.
            if artifact.sha256 != sha256 or artifact.size_bytes != size:
                raise AttachAudioError(
                    CODE_ATTACH_VALIDATION_FAILED,
                    "existing artifact row conflicts with the remux evidence",
                    details={"artifact_id": artifact_id},
                )
            if artifact.state != "ready":
                artifact.state = "ready"
                artifact.updated_at = datetime.now(UTC)

        owner = session.get(
            ArtifactOwner,
            (
                artifact_id,
                "video_item",
                video_item_id,
                ARTIFACT_PURPOSE_ORIGINAL_AUDIO,
            ),
        )
        if owner is None:
            session.add(
                ArtifactOwner(
                    artifact_id=artifact_id,
                    owner_type="video_item",
                    owner_id=video_item_id,
                    purpose=ARTIFACT_PURPOSE_ORIGINAL_AUDIO,
                )
            )
        session.commit()


# ── Output validator (verified-publication completion gate) ──────────────────


def _attach_output_validator(
    ctx: WorkerContext, result: dict[str, Any], staging_dir: Path
) -> dict[str, Any]:
    """Re-verify the published audio on disk before the step may complete.

    The worker invokes this after the handler returns; the Job reaches
    ``completed`` only after this validator passes (contract §9.3).  A
    ``NO_AUDIO_PRESENT`` result verifies the ABSENCE of any published file
    instead (nothing may exist).
    """
    del staging_dir
    published = result.get("published") or {}
    if published.get("no_audio_present"):
        final_rel = published.get("final_rel")
        if final_rel:
            raise RuntimeError("NO_AUDIO_PRESENT result carries a published path")
        return {
            "original_audio": {
                "status": "NO_AUDIO_PRESENT",
                "no_audio_present": True,
            }
        }
    final_rel = published.get("final_rel")
    if not isinstance(final_rel, str):
        raise RuntimeError("attach result missing published.final_rel")
    managed = _managed_for(ctx)
    try:
        target = managed.resolve(final_rel)
    except ManagedPathError as exc:
        raise RuntimeError(f"published audio path rejected: {exc}") from exc
    if not target.is_file():
        raise RuntimeError(f"published original audio missing at {final_rel}")
    sha = hash_file(target)
    size = target.stat().st_size
    if sha != published.get("sha256") or size != published.get("size_bytes"):
        raise RuntimeError(
            "published original audio sha256/size do not match the handler "
            "evidence"
        )
    return {
        "original_audio": {
            "relative_path": final_rel,
            "sha256": sha,
            "size_bytes": size,
            "status": published.get("status"),
        }
    }


# ── Step plan + registration ─────────────────────────────────────────────────


def attach_original_audio_steps() -> list[StepInput]:
    """The ATTACH_ORIGINAL_AUDIO step plan (one sync step)."""
    return [StepInput(step_code=ATTACH_STEP_CODE, position=0, step_type="sync")]


def register_attach_original_audio_handler(worker: Any) -> None:
    """Register the ATTACH_ORIGINAL_AUDIO handler on a DurableWorker.

    An ``output_validator`` re-verifies the published audio before the step
    may complete, mirroring GENERATE_PROXY's verified-publication gate.
    """
    worker.register_handler(
        JOB_TYPE_ATTACH_ORIGINAL_AUDIO,
        attach_original_audio_handler,
        output_validator=_attach_output_validator,
    )


# ── Submit (contract §8.1 idempotency, owner-scoped) ─────────────────────────


def _idempotency_key(
    video_item_id: str, source_sha256: str, generation: str
) -> str:
    """Owner-scoped ATTACH_ORIGINAL_AUDIO idempotency key.

    Deterministic and content-bound (GENERATE_PROXY pattern)::

        ATTACH_ORIGINAL_AUDIO:video_item:<id>:<source_sha256>:<generation>

    Equivalent submits (same owner + same source bytes + same generation)
    reuse the Job/effects; any other combination is a different logical key.
    """
    return (
        f"{JOB_TYPE_ATTACH_ORIGINAL_AUDIO}:video_item:{video_item_id}:"
        f"{source_sha256}:{generation}"
    )


def submit_attach_original_audio(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    generation: str = "1",
    managed_root: str | Path | None = None,
) -> AttachSubmitResult:
    """Create the durable ATTACH_ORIGINAL_AUDIO Job for one VideoItem.

    The source authority is ALWAYS the VideoItem's ready ``source``
    artifact — no filesystem path is accepted from the caller (Required
    behavior 2).  The idempotency key embeds that artifact's SHA-256, so
    equivalent submits reuse the completed Job (``reused=True``) while an
    active duplicate raises ``IdempotencyKeyInUse`` (fail closed).

    Raises:
        VideoImportError: ownership chain failures (S05 stable codes).
        AttachAudioError: missing/not-ready/mismatched source artifact.
        ValueError: empty ids.
        IdempotencyKeyInUse: an active Job exists for the key.
    """
    if not workspace_id or not project_id or not video_item_id:
        raise ValueError(
            "workspace_id, project_id and video_item_id are required"
        )

    with session_factory() as session:
        from app.persistence.jobs import IdempotencyKeyInUse, JobRepository
        from app.persistence.models import Job as JobORM

        video_import._validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        artifact = _validate_source_artifact(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            source_artifact_id=None,
        )
        source_sha256 = artifact.sha256 or ""
        source_artifact_id = artifact.id

        manifest: dict[str, Any] = {
            "schema_version": NO_AUDIO_SCHEMA_VERSION,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "source_artifact_id": source_artifact_id,
            "source_sha256": source_sha256,
            "generation": generation,
        }
        if managed_root is not None:
            manifest["managed_root"] = str(managed_root)

        idempotency_key = _idempotency_key(video_item_id, source_sha256, generation)

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
                job_type=JOB_TYPE_ATTACH_ORIGINAL_AUDIO,
                owner_type="video_item",
                owner_id=video_item_id,
                input_manifest=manifest,
                idempotency_key=idempotency_key,
                input_generation=generation,
                steps=attach_original_audio_steps(),
                actor="api",
            )
        except IdempotencyKeyInUse:
            session.rollback()
            raise
        session.commit()
        return AttachSubmitResult(job_id=job.id, reused=completed_exists is not None)
