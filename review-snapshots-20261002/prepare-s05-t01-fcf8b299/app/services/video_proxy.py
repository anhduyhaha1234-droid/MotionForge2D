"""Bounded editing-proxy generation service (S05-T03) — the GENERATE_PROXY job.

Implements the exact timebase/proxy contract stated in ``docs/architecture/
CANONICAL_TIMEBASE_PROXY_CONTRACT.md`` and consumes the S05-T02 managed
import (``app/services/video_import.py``) as its input:

- **Submit** (:func:`submit_proxy`) validates the ownership chain and the
  source artifact (``kind='video'``, ``state='ready'``, ``artifact_owner``
  purpose ``source`` with a recorded SHA-256) **before** Job creation, then
  creates the durable ``GENERATE_PROXY`` Job with an **owner-scoped**
  idempotency key ``GENERATE_PROXY:video_item:<video_item_id>:
  <source_sha256>:<generation>`` — the same source bytes proxied for two
  different VideoItems create two independent Jobs/effect sets.  A completed
  duplicate returns the existing Job; an active duplicate raises
  ``IdempotencyKeyInUse``; retry/restart of a failed/cancelled Job is a
  successor with the same key and generation (DURABLE_JOB_CONTRACT
  §6.4/§8.5).  The request path never runs FFmpeg.
- **Source phase** re-validates ownership + source artifact at run time,
  resolves the managed source file **read-only** from the artifact's
  normalized relative path, and runs the bounded probe (30s, list-args,
  JSON, discovery only via ``app.services.ffmpeg_utils``).  The probe is
  checkpointed so a re-run reuses it instead of re-probing.
- **Timebase phase** builds the canonical timeline mapping
  (:class:`app.services.timebase.CanonicalTimebase`) from the probe's
  ``fps_classification`` + rational fps (CFR → ``r_frame_rate``; VFR →
  ``avg_frame_rate``).  The schema-versioned payload is persisted in the
  checkpoint — this is where the canonical timebase becomes durable.
- **Generate phase** runs FFmpeg with **list arguments only** (no shell),
  discovery only via ``ffmpeg_utils.find_ffmpeg``, bounded by
  ``ProxyProfile.timeout_seconds``, writing to the managed staging path
  ``staging/<job_id>/<step_code>/proxy.mp4``.  The subprocess is polled
  against ``ctx.is_cancelled()``: cancel terminates it and removes the
  staging partial (``CANCELLED``); a budget overrun terminates and raises
  ``PROXY_TIMEOUT`` (transient → the durable worker auto-retries).
- **Verify phase** bounded-probes the generated proxy: it must decode
  (positive duration/width/height), its recorded fps must equal the
  canonical grid exactly, and its duration must match the source within a
  bounded tolerance — the proxy's metadata is truthful.
- **Publish phase** atomically moves the staged file into the final managed
  path ``artifacts/<workspace_id>/video/<job_id>/<step_code>/proxy.mp4`` and
  then, in **one transaction**, upserts the ``artifact`` row
  (``kind='video'``, ``state='ready'``, sha256, size, relative path) with a
  deterministic id and the ``artifact_owner`` link (purpose ``proxy``).  A
  DB failure removes the just-published file **only when this attempt
  created it**; replay finds the ready row/file and reuses it (no duplicate
  effects, committed files never deleted — S05-T02 correction #4 pattern).
- **Completion gate** — ``GENERATE_PROXY`` registers an ``output_validator``
  that re-verifies the published file on disk (exists + sha256 + size match
  the handler's evidence); a Job can never reach ``completed`` before
  verified publication.
- **Path containment** — every managed path goes through ``ManagedRoot``;
  ``ManagedPathError`` maps to the stable ``PATH_CONTAINMENT`` envelope.
  No absolute managed path is ever persisted: checkpoints and manifests
  carry only normalized relative paths (the probe payload's display-only
  ``file_path`` is stripped before it becomes durable).

No new schema: the durable write surface is exactly the existing
``artifact`` and ``artifact_owner`` tables; the canonical timebase is
persisted only in the Job checkpoint/attempt JSON.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
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
from app.services.ffmpeg_utils import find_ffmpeg
from app.services.timebase import (
    CanonicalTimebase,
)
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "ARTIFACT_PURPOSE_PROXY",
    "CODE_CANCELLED",
    "CODE_FFMPEG_BINARY_NOT_FOUND",
    "CODE_INPUT_UNREADABLE",
    "CODE_INSUFFICIENT_DISK",
    "CODE_INVALID_PROXY_PROFILE",
    "CODE_OWNERSHIP_MISMATCH",
    "CODE_PATH_CONTAINMENT",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_PROXY_FFMPEG_FAILED",
    "CODE_PROXY_TIMEOUT",
    "CODE_PROXY_VALIDATION_FAILED",
    "CODE_PUBLICATION_FAILED",
    "CODE_SOURCE_ARTIFACT_NOT_FOUND",
    "CODE_SOURCE_FILE_MISSING",
    "CODE_SOURCE_NOT_READY",
    "CODE_SOURCE_OWNER_MISMATCH",
    "CODE_VIDEO_ITEM_NOT_FOUND",
    "DEFAULT_PROXY_TIMEOUT_SECONDS",
    "JOB_TYPE_GENERATE_PROXY",
    "PROXY_DURATION_TOLERANCE_RATIO",
    "PROXY_SCHEMA_VERSION",
    "PROXY_STEP_CODE",
    "ProxyProfile",
    "ProxySubmitResult",
    "VideoProxyError",
    "VIETNAMESE_ACTIONS",
    "generate_proxy_handler",
    "generate_proxy_steps",
    "register_generate_proxy_handler",
    "submit_proxy",
]

#: Stable job type registered by this task (DURABLE_JOB_CONTRACT §3 job-class
#: list extension, documented in CANONICAL_TIMEBASE_PROXY_CONTRACT.md).
JOB_TYPE_GENERATE_PROXY = "GENERATE_PROXY"

#: The single sync step that executes the whole proxy pipeline.
PROXY_STEP_CODE = "proxy"

#: Schema version of the proxy checkpoint payload.
PROXY_SCHEMA_VERSION = 1

#: Artifact-owner purpose for a VideoItem's editing proxy (MANAGED_ARTIFACT
#: visibility classes: user-visible preview, never the import Job result).
ARTIFACT_PURPOSE_PROXY = "proxy"

#: Default bounded FFmpeg budget (seconds) for one proxy generation.
DEFAULT_PROXY_TIMEOUT_SECONDS = 120

#: Relative duration tolerance for proxy-vs-source truthfulness (ratio of
#: source duration, floored at 0.05s) — covers one-frame resampling edges.
PROXY_DURATION_TOLERANCE_RATIO = 0.05

# ── Stable error codes (contract "Stable error taxonomy" section) ───────────

CODE_SOURCE_ARTIFACT_NOT_FOUND = "SOURCE_ARTIFACT_NOT_FOUND"
CODE_SOURCE_NOT_READY = "SOURCE_NOT_READY"
CODE_SOURCE_OWNER_MISMATCH = "SOURCE_OWNER_MISMATCH"
CODE_SOURCE_FILE_MISSING = "SOURCE_FILE_MISSING"
CODE_FFMPEG_BINARY_NOT_FOUND = "FFMPEG_BINARY_NOT_FOUND"
CODE_PROXY_FFMPEG_FAILED = "PROXY_FFMPEG_FAILED"
CODE_PROXY_TIMEOUT = "PROXY_TIMEOUT"
CODE_PROXY_VALIDATION_FAILED = "PROXY_VALIDATION_FAILED"
CODE_INVALID_PROXY_PROFILE = "INVALID_PROXY_PROFILE"

#: Reused stable codes from the approved import taxonomy (VIDEO_PREFLIGHT
#: CONTRACT §7 + S05-T02 corrections).
CODE_VIDEO_ITEM_NOT_FOUND = video_import.CODE_VIDEO_ITEM_NOT_FOUND
CODE_PROJECT_NOT_FOUND = video_import.CODE_PROJECT_NOT_FOUND
CODE_OWNERSHIP_MISMATCH = video_import.CODE_OWNERSHIP_MISMATCH
CODE_PUBLICATION_FAILED = video_import.CODE_PUBLICATION_FAILED
CODE_CANCELLED = video_import.CODE_CANCELLED
CODE_PATH_CONTAINMENT = video_import.CODE_PATH_CONTAINMENT
CODE_INSUFFICIENT_DISK = video_import.CODE_INSUFFICIENT_DISK
CODE_INPUT_UNREADABLE = video_import.CODE_INPUT_UNREADABLE

#: Vietnamese suggested actions (PRD §9 Step 5 acceptance / FR-08) for every
#: stable code this service raises; reused codes keep the approved actions.
VIETNAMESE_ACTIONS: dict[str, str] = {
    **video_import.VIETNAMESE_ACTIONS,
    CODE_SOURCE_ARTIFACT_NOT_FOUND: (
        "Artifact nguồn không tồn tại hoặc không thuộc Workspace này. Hãy kiểm "
        "tra lại Video Item và import nguồn trước."
    ),
    CODE_SOURCE_NOT_READY: (
        "Artifact nguồn chưa sẵn sàng (không phải video ready hoặc thiếu "
        "checksum). Hãy đợi import hoàn tất rồi thử lại."
    ),
    CODE_SOURCE_OWNER_MISMATCH: (
        "Artifact nguồn không được liên kết với Video Item này (thiếu liên kết "
        "purpose=source). Hãy import lại nguồn cho đúng Video Item."
    ),
    CODE_SOURCE_FILE_MISSING: (
        "Tệp nguồn được quản lý không tồn tại hoặc kích thước không khớp. Hãy "
        "kiểm tra lại storage và import lại nếu cần."
    ),
    CODE_FFMPEG_BINARY_NOT_FOUND: (
        "Không tìm thấy ffmpeg. Cài đặt FFmpeg (winget install Gyan.FFmpeg) "
        "hoặc đặt MOTIONFORGE_FFMPEG rồi thử lại."
    ),
    CODE_PROXY_FFMPEG_FAILED: (
        "FFmpeg không tạo được proxy. Tệp nguồn có thể bị hỏng hoặc profile "
        "proxy không tương thích; hãy kiểm tra lại nguồn và cấu hình proxy."
    ),
    CODE_PROXY_TIMEOUT: (
        "Quá thời gian tạo proxy. Hãy thử lại; nếu tệp quá lớn, hãy kiểm tra "
        "định dạng hoặc tốc độ ổ đĩa."
    ),
    CODE_PROXY_VALIDATION_FAILED: (
        "Proxy tạo ra không đạt kiểm tra (không decode được hoặc metadata không "
        "khớp). Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống kèm Job id."
    ),
    CODE_INVALID_PROXY_PROFILE: (
        "Profile proxy không hợp lệ (kích thước/CRF/preset/bitrate/timeout). "
        "Hãy kiểm tra lại cấu hình proxy."
    ),
}

#: Known libx264 presets (bounded set — a proxy profile may not pick an
#: arbitrary encoder option).
_KNOWN_PRESETS = frozenset(
    {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
        "placebo",
    }
)


class VideoProxyError(Exception):
    """A stable, actionable proxy-generation failure (contract §10.1).

    ``code`` is the machine-readable stable error code; ``action`` is the
    Vietnamese suggested action; ``location``/``details`` carry structured
    context for the error envelope.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.location = location
        self.details = details or {}

    def action(self) -> str:
        """The Vietnamese suggested action for this error's code."""
        return VIETNAMESE_ACTIONS.get(
            self.code, "Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống."
        )


@dataclass(frozen=True)
class ProxyProfile:
    """Bounded encoding profile for one editing proxy (all knobs validated).

    Attributes:
        max_width: Maximum output width; smaller sources are never upscaled.
        max_height: Maximum output height; smaller sources are never upscaled.
        crf: libx264 CRF in ``[0, 51]`` (higher = smaller/lower quality).
        preset: One of the known libx264 presets.
        audio_bitrate: AAC bitrate string (``64k`` etc.).
        include_audio: When True the proxy keeps a low-bitrate AAC track when
            the source has audio; otherwise ``-an``.
        timeout_seconds: Bounded FFmpeg budget (> 0).
    """

    max_width: int = 640
    max_height: int = 360
    crf: int = 28
    preset: str = "ultrafast"
    audio_bitrate: str = "64k"
    include_audio: bool = True
    timeout_seconds: int = DEFAULT_PROXY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.max_width <= 0 or self.max_height <= 0:
            raise VideoProxyError(
                CODE_INVALID_PROXY_PROFILE,
                f"max_width/max_height must be positive: {self.max_width}x{self.max_height}",
                location="proxy_profile",
                details={"max_width": self.max_width, "max_height": self.max_height},
            )
        if not 0 <= self.crf <= 51:
            raise VideoProxyError(
                CODE_INVALID_PROXY_PROFILE,
                f"crf must be within [0, 51]: {self.crf}",
                location="proxy_profile",
                details={"crf": self.crf},
            )
        if self.preset not in _KNOWN_PRESETS:
            raise VideoProxyError(
                CODE_INVALID_PROXY_PROFILE,
                f"preset {self.preset!r} is not a known libx264 preset",
                location="proxy_profile",
                details={"preset": self.preset, "known": sorted(_KNOWN_PRESETS)},
            )
        if not re.fullmatch(r"\d+(?:[kKmM])?", self.audio_bitrate):
            raise VideoProxyError(
                CODE_INVALID_PROXY_PROFILE,
                f"audio_bitrate {self.audio_bitrate!r} is not a valid bitrate",
                location="proxy_profile",
                details={"audio_bitrate": self.audio_bitrate},
            )
        if self.timeout_seconds <= 0:
            raise VideoProxyError(
                CODE_INVALID_PROXY_PROFILE,
                f"timeout_seconds must be positive: {self.timeout_seconds}",
                location="proxy_profile",
                details={"timeout_seconds": self.timeout_seconds},
            )

    def to_json(self) -> dict[str, Any]:
        """Schema-versioned durable profile payload (manifest/checkpoint)."""
        return {
            "schema_version": 1,
            "max_width": self.max_width,
            "max_height": self.max_height,
            "crf": self.crf,
            "preset": self.preset,
            "audio_bitrate": self.audio_bitrate,
            "include_audio": self.include_audio,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any] | None) -> ProxyProfile:
        """Rebuild a profile from :meth:`to_json`; missing → default profile."""
        if not payload:
            return cls()
        return cls(
            max_width=int(payload.get("max_width", 640)),
            max_height=int(payload.get("max_height", 360)),
            crf=int(payload.get("crf", 28)),
            preset=str(payload.get("preset", "ultrafast")),
            audio_bitrate=str(payload.get("audio_bitrate", "64k")),
            include_audio=bool(payload.get("include_audio", True)),
            timeout_seconds=int(payload.get("timeout_seconds", DEFAULT_PROXY_TIMEOUT_SECONDS)),
        )


@dataclass(frozen=True)
class ProxySubmitResult:
    """Result of :func:`submit_proxy` — the durable Job id and reuse flag."""

    job_id: str
    reused: bool


# ── Managed path / staging helpers (mirror video_import) ────────────────────


def _managed_for(ctx: WorkerContext) -> ManagedRoot:
    """ManagedRoot bound to the Job's manifest managed root."""
    return ManagedRoot(Path(str(ctx.input_manifest.get("managed_root") or "artifacts")))


def _staging_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the staged proxy (contract §9.1)."""
    return f"staging/{ctx.job_id}/{ctx.step_code}/{name}"


def _final_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the published proxy (contract §9.2)."""
    workspace_id = str(ctx.input_manifest.get("workspace_id") or "default")
    return f"artifacts/{workspace_id}/video/{ctx.job_id}/{ctx.step_code}/{name}"


def _artifact_id(ctx: WorkerContext, final_rel: str) -> str:
    """Deterministic artifact id for (job, step, path) — replay-safe (§8.3)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"generate-proxy:{ctx.job_id}:{final_rel}"))


def _predecessor_job_id(ctx: WorkerContext) -> str | None:
    """The predecessor Job id of this Job (retry/restart chain, §6.4)."""
    if ctx.session_factory is None:
        return None
    try:
        from app.persistence.jobs import JobRepository

        with ctx.session_factory() as session:
            return JobRepository(session).get_job(ctx.job_id).predecessor_job_id
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        return None


def _cleanup_staging_partials(ctx: WorkerContext, managed: ManagedRoot, name: str) -> None:
    """Remove leftover partial proxy files for this Job and its predecessor.

    FFmpeg writes directly to ``staging/<job>/<step>/<name>`` (no
    ``.staging`` suffix), so crash leftovers live at the exact target plus
    any ``.staging`` files from atomic helpers.  Only staging owned by this
    Job or its predecessor is ever touched — never published artifacts.
    """
    root = managed.root
    step_code = ctx.step_code
    dirs = [root / "staging" / ctx.job_id / step_code]
    predecessor = _predecessor_job_id(ctx)
    if predecessor is not None:
        dirs.append(root / "staging" / predecessor / step_code)
    for staging_dir in dirs:
        if not staging_dir.is_dir():
            continue
        _remove_file(staging_dir / name)
        for partial in staging_dir.glob("*.staging"):
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)


def _remove_file(path: Path) -> None:
    """Best-effort removal of a managed file (never raises)."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _raise_if_cancelled(ctx: WorkerContext, phase: str) -> None:
    """Fail with the stable cancel code when the durable flag is set."""
    if ctx.is_cancelled():
        raise VideoProxyError(
            CODE_CANCELLED,
            f"proxy generation cancelled before {phase} phase",
            location=f"phase:{phase}",
        )


def _wrap_managed_errors(exc: ManagedPathError) -> VideoProxyError:
    """Map a containment failure to the stable PATH_CONTAINMENT envelope."""
    return VideoProxyError(
        CODE_PATH_CONTAINMENT,
        f"managed path rejected: {exc}",
        location="managed path",
        details={"reason": str(exc)},
    )


def _monotonic() -> float:
    """Monotonic clock seam (tests inject a fake to force timeouts)."""
    return time.monotonic()


def _strip_probe_paths(probe: dict[str, Any]) -> dict[str, Any]:
    """Remove the display-only absolute ``file_path`` before durable storage.

    No absolute managed path may leak into durable/public data; the probe
    payload is persisted in the Job checkpoint, so the absolute path is
    stripped there (it is re-derived from the artifact relative path at run
    time).
    """
    return {**probe, "file_path": None}


# ── Source validation (submit + run-time) ───────────────────────────────────


def _validate_source_artifact(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
    source_artifact_id: str,
) -> Artifact:
    """Verify the managed source artifact chain for the VideoItem.

    The artifact must exist in *workspace_id*, be ``kind='video'`` and
    ``state='ready'`` with a recorded SHA-256, and carry an ``artifact_owner``
    link (``video_item``/``video_item_id``/purpose ``source``).  Called
    **before Job creation** (``submit_proxy``) and **again in the source
    phase** so a stale/deleted source fails closed with zero side effects.

    Raises:
        VideoProxyError: ``SOURCE_ARTIFACT_NOT_FOUND`` / ``SOURCE_NOT_READY``
            / ``SOURCE_OWNER_MISMATCH``.
    """
    artifact = session.get(Artifact, source_artifact_id)
    if artifact is None or artifact.workspace_id != workspace_id:
        raise VideoProxyError(
            CODE_SOURCE_ARTIFACT_NOT_FOUND,
            f"source artifact {source_artifact_id!r} not found in workspace "
            f"{workspace_id!r}",
            location="artifact",
            details={"source_artifact_id": source_artifact_id},
        )
    if artifact.kind != "video" or artifact.state != "ready" or not artifact.sha256:
        raise VideoProxyError(
            CODE_SOURCE_NOT_READY,
            f"source artifact {source_artifact_id!r} is not a ready video with "
            f"a recorded checksum (kind={artifact.kind!r}, state={artifact.state!r})",
            location="artifact",
            details={
                "artifact_id": artifact.id,
                "kind": artifact.kind,
                "state": artifact.state,
                "has_sha256": artifact.sha256 is not None,
            },
        )
    owner = session.get(
        ArtifactOwner,
        (artifact.id, "video_item", video_item_id, video_import.ARTIFACT_PURPOSE_SOURCE),
    )
    if owner is None:
        raise VideoProxyError(
            CODE_SOURCE_OWNER_MISMATCH,
            f"source artifact {artifact.id!r} is not linked as the source of "
            f"video item {video_item_id!r}",
            location="artifact_owner",
            details={"artifact_id": artifact.id, "video_item_id": video_item_id},
        )
    return artifact


# ── The GENERATE_PROXY handler ───────────────────────────────────────────────


def generate_proxy_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one GENERATE_PROXY Job: source → timebase → generate → verify → publish.

    The handler resumes from the step checkpoint: a valid source evidence is
    reused (never re-probes the source), the canonical timebase is rebuilt
    from its persisted payload, a completed generation is verified and
    reused, and a published effect is verified and skipped.  Every phase
    cleans its own staging/partial files on cancel/failure.
    """
    managed = _managed_for(ctx)
    cp = ctx.checkpoint
    if not isinstance(cp, dict):
        cp = {"schema_version": PROXY_SCHEMA_VERSION}

    source_ev = _source_phase(ctx, cp, managed)
    cp = {**cp, "source": source_ev, "phase": "source"}
    tb_ev = _timebase_phase(ctx, cp, source_ev)
    cp = {**cp, "timebase": tb_ev, "phase": "timebase"}
    gen_ev = _generate_phase(ctx, cp, managed, source_ev, tb_ev)
    cp = {**cp, "generate": gen_ev, "phase": "generate"}
    verify_ev = _verify_phase(ctx, cp, managed, source_ev, tb_ev, gen_ev)
    cp = {**cp, "verify": verify_ev, "phase": "verify"}
    published = _publish_phase(ctx, cp, managed, gen_ev, verify_ev)
    return {
        "source": source_ev,
        "timebase": tb_ev,
        "generate": gen_ev,
        "verify": verify_ev,
        "published": published,
    }


def _source_phase(
    ctx: WorkerContext, cp: dict[str, Any], managed: ManagedRoot
) -> dict[str, Any]:
    """Source phase: re-validate ownership + source artifact, probe the source.

    The checkpointed source evidence is reused when the artifact row is
    still ready and the managed file still exists with the recorded size —
    a re-run never re-probes a valid source.
    """
    source_ev = cp.get("source")
    if isinstance(source_ev, dict) and _source_evidence_valid(managed, source_ev):
        return source_ev
    _raise_if_cancelled(ctx, "source")
    if ctx.session_factory is None:
        raise VideoProxyError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot resolve the source",
            location="artifact (source phase)",
        )
    manifest = ctx.input_manifest
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    video_item_id = str(manifest["video_item_id"])
    source_artifact_id = str(manifest["source_artifact_id"])

    with ctx.session_factory() as session:
        # Ownership chain re-validated at run time (S05-T02 correction #2
        # pattern): the video item may have moved between submit and run.
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
        raise VideoProxyError(
            CODE_SOURCE_FILE_MISSING,
            f"managed source file missing at {rel}",
            location="artifact (source phase)",
            details={"relative_path": rel},
        )
    if size is not None and src_path.stat().st_size != size:
        raise VideoProxyError(
            CODE_SOURCE_FILE_MISSING,
            f"managed source file size {src_path.stat().st_size} does not match "
            f"the recorded artifact size {size}",
            location="artifact (source phase)",
            details={"relative_path": rel, "expected_size": size},
        )

    probe = video_import.probe_source(src_path)
    source_ev = {
        "artifact_id": artifact.id,
        "relative_path": rel,
        "sha256": sha256,
        "size_bytes": size,
        "probe": _strip_probe_paths(probe),
    }
    ctx.write_checkpoint({**cp, "source": source_ev, "phase": "source"})
    return source_ev


def _source_evidence_valid(managed: ManagedRoot, source_ev: dict[str, Any]) -> bool:
    """True when the checkpointed source evidence still matches on disk."""
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
    return isinstance(source_ev.get("probe"), dict)


def _timebase_phase(
    ctx: WorkerContext, cp: dict[str, Any], source_ev: dict[str, Any]
) -> dict[str, Any]:
    """Timebase phase: build the canonical mapping from the source probe.

    CFR inputs use ``r_frame_rate``; VFR inputs use ``avg_frame_rate``
    (exact rationals, see :class:`app.services.timebase.CanonicalTimebase`).
    The schema-versioned payload becomes durable in the checkpoint.
    """
    tb_ev = cp.get("timebase")
    if isinstance(tb_ev, dict) and tb_ev.get("schema_version") == 1:
        return tb_ev
    _raise_if_cancelled(ctx, "timebase")
    timebase = CanonicalTimebase.from_probe(source_ev["probe"])
    tb_ev = timebase.to_json()
    ctx.write_checkpoint({**cp, "timebase": tb_ev, "phase": "timebase"})
    return tb_ev


def _generate_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    source_ev: dict[str, Any],
    tb_ev: dict[str, Any],
) -> dict[str, Any]:
    """Generate phase: run bounded, cancellable FFmpeg into the staging path.

    The checkpointed generation evidence is reused when the staged file
    still exists and hashes to the recorded value; anything else re-runs
    FFmpeg from the managed source.
    """
    gen_ev = cp.get("generate")
    if isinstance(gen_ev, dict) and _generate_evidence_valid(managed, gen_ev):
        return gen_ev
    _raise_if_cancelled(ctx, "generate")

    profile = ProxyProfile.from_json(ctx.input_manifest.get("proxy_profile"))
    timebase = CanonicalTimebase.from_json(tb_ev)
    name = "proxy.mp4"
    staged_rel = _staging_relative_path(ctx, name)
    _cleanup_staging_partials(ctx, managed, name)

    src_path = managed.resolve(str(source_ev["relative_path"]))
    staged_path = managed.resolve(staged_rel)
    video_import._check_disk_space(managed, src_path)
    _remove_file(staged_path)
    # The worker creates the step staging dir lazily via ctx.staging_dir();
    # the proxy handler writes directly through ManagedRoot, so create the
    # FFmpeg output directory explicitly (contract §9.1 staging path).
    staged_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        ffmpeg = find_ffmpeg()
    except FileNotFoundError as exc:
        raise VideoProxyError(
            CODE_FFMPEG_BINARY_NOT_FOUND,
            "ffmpeg binary not found by app.services.ffmpeg_utils",
            location="toolchain",
        ) from exc

    cmd = _build_ffmpeg_command(
        ffmpeg, src_path, staged_path, profile, timebase, source_ev["probe"]
    )
    _run_ffmpeg(ctx, cmd, timeout_seconds=profile.timeout_seconds, staged_path=staged_path)

    if ctx.is_cancelled():
        _remove_file(staged_path)
        raise VideoProxyError(
            CODE_CANCELLED,
            "proxy generation cancelled after encode; staged file removed",
            location="phase:generate",
        )

    sha256 = hash_file(staged_path)
    size = staged_path.stat().st_size
    gen_ev = {
        "staged_rel": staged_rel,
        "name": name,
        "sha256": sha256,
        "size_bytes": size,
        "profile": profile.to_json(),
    }
    ctx.write_checkpoint({**cp, "generate": gen_ev, "phase": "generate"})
    return gen_ev


def _generate_evidence_valid(managed: ManagedRoot, gen_ev: dict[str, Any]) -> bool:
    """True when the checkpointed generation evidence still matches on disk."""
    staged_rel = gen_ev.get("staged_rel")
    if not isinstance(staged_rel, str):
        return False
    try:
        staged_path = managed.resolve(staged_rel)
    except ManagedPathError:
        return False
    if not staged_path.is_file():
        return False
    recorded = gen_ev.get("sha256")
    if not isinstance(recorded, str):
        return False
    try:
        return hash_file(staged_path) == recorded
    except OSError:
        return False


def _verify_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    source_ev: dict[str, Any],
    tb_ev: dict[str, Any],
    gen_ev: dict[str, Any],
) -> dict[str, Any]:
    """Verify phase: the generated proxy must decode with truthful metadata.

    Bounded ffprobe of the staged proxy: positive duration/width/height
    (V1 media decision), recorded fps == the canonical grid exactly, and
    duration within the bounded tolerance of the source duration.  A proxy
    that fails any check raises ``PROXY_VALIDATION_FAILED`` and the staged
    file is removed.
    """
    verify_ev = cp.get("verify")
    if isinstance(verify_ev, dict) and _verify_evidence_valid(verify_ev, gen_ev):
        return verify_ev
    _raise_if_cancelled(ctx, "verify")

    staged_path = managed.resolve(str(gen_ev["staged_rel"]))
    timebase = CanonicalTimebase.from_json(tb_ev)
    source_probe = source_ev["probe"]
    try:
        proxy_probe = video_import.probe_source(staged_path)
    except video_import.VideoImportError as exc:
        _remove_file(staged_path)
        raise VideoProxyError(
            CODE_PROXY_VALIDATION_FAILED,
            f"generated proxy failed the decode probe: {exc.message}",
            location="verify phase",
            details={"reason_code": exc.code, "reason": exc.message},
        ) from exc

    proxy_video = proxy_probe["video_stream"]
    proxy_r = proxy_video["r_frame_rate"]
    fps_matches = (
        proxy_r.get("num") == timebase.fps_num and proxy_r.get("den") == timebase.fps_den
    )
    src_duration = float(source_probe["container"].get("duration_seconds") or 0.0)
    proxy_duration = float(proxy_probe["container"].get("duration_seconds") or 0.0)
    tolerance = max(0.05, src_duration * PROXY_DURATION_TOLERANCE_RATIO)
    duration_ok = abs(proxy_duration - src_duration) <= tolerance

    if not fps_matches or not duration_ok:
        _remove_file(staged_path)
        raise VideoProxyError(
            CODE_PROXY_VALIDATION_FAILED,
            "generated proxy metadata is not truthful: "
            f"fps={proxy_r.get('num')}/{proxy_r.get('den')} "
            f"(expected {timebase.fps_num}/{timebase.fps_den}), "
            f"duration={proxy_duration:.6f}s (source {src_duration:.6f}s, "
            f"tolerance {tolerance:.6f}s)",
            location="verify phase",
            details={
                "proxy_fps": proxy_r,
                "canonical_fps": {"num": timebase.fps_num, "den": timebase.fps_den},
                "proxy_duration_seconds": proxy_duration,
                "source_duration_seconds": src_duration,
                "tolerance_seconds": tolerance,
            },
        )

    verify_ev = {
        "probe": _strip_probe_paths(proxy_probe),
        "duration_seconds": proxy_duration,
        "fps_num": proxy_r.get("num"),
        "fps_den": proxy_r.get("den"),
        "duration_within_tolerance": True,
    }
    ctx.write_checkpoint({**cp, "verify": verify_ev, "phase": "verify"})
    return verify_ev


def _verify_evidence_valid(verify_ev: dict[str, Any], gen_ev: dict[str, Any]) -> bool:
    """True when the checkpointed verification still describes the same file."""
    if not verify_ev.get("duration_within_tolerance"):
        return False
    return isinstance(verify_ev.get("probe"), dict) and isinstance(gen_ev.get("sha256"), str)


def _publish_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    gen_ev: dict[str, Any],
    verify_ev: dict[str, Any],
) -> dict[str, Any]:
    """Publish phase: move staged bytes into the final path and persist the
    artifact + owner link in ONE transaction.

    Idempotent replay: if the final file already exists with the recorded
    checksum it is reused; if the artifact row is already ``ready`` with
    matching evidence publication is skipped.  A DB failure removes the
    just-published file **only when THIS attempt created/moved it** — a
    pre-existing committed final file reused by replay is never removed
    (S05-T02 correction #4 pattern).
    """
    del verify_ev  # verification already checkpointed; publication owns bytes
    published = cp.get("published")
    if isinstance(published, dict) and published.get("artifact_id"):
        return published
    _raise_if_cancelled(ctx, "publish")

    staged_rel = str(gen_ev["staged_rel"])
    sha256 = str(gen_ev["sha256"])
    size = int(gen_ev["size_bytes"])
    name = Path(staged_rel).name
    final_rel = _final_relative_path(ctx, name)
    try:
        staged_path = managed.resolve(staged_rel)
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    try:
        final_path = managed.resolve(final_rel)
    except ManagedPathError as exc:
        # Containment failure before publication: remove the staged copy so
        # a rejected generation never leaves staging/partial files behind.
        _remove_file(staged_path)
        raise _wrap_managed_errors(exc) from exc

    created_final = False
    try:
        created_final = _publish_file(managed, staged_path, final_path, sha256)
    except VideoProxyError:
        _remove_file(staged_path)
        raise
    try:
        _publish_effect(ctx, final_rel, sha256, size)
    except VideoProxyError:
        _remove_file(staged_path)
        if created_final:
            _remove_file(final_path)
        raise
    except Exception as exc:  # noqa: BLE001 - publication failures are permanent
        _remove_file(staged_path)
        if created_final:
            _remove_file(final_path)
        raise VideoProxyError(
            CODE_PUBLICATION_FAILED,
            f"publication transaction failed: {exc}",
            location="artifact (publish step)",
            details={"error_type": type(exc).__name__},
        ) from exc

    _remove_file(staged_path)
    published = {
        "final_rel": final_rel,
        "artifact_id": _artifact_id(ctx, final_rel),
        "sha256": sha256,
        "size_bytes": size,
    }
    ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
    return published


def _publish_file(
    managed: ManagedRoot, staged_path: Path, final_path: Path, sha256: str
) -> bool:
    """Atomically move the staged proxy to its final managed path.

    Returns ``True`` when THIS attempt created/moved the final file (the
    failing attempt owns the bytes and may remove them on a later failure),
    ``False`` when an existing verified final file was reused (replay of a
    previously committed publication — the file is NOT owned by this attempt
    and must never be removed).
    """
    if final_path.exists():
        if hash_file(final_path) != sha256:
            raise VideoProxyError(
                CODE_PROXY_VALIDATION_FAILED,
                "final file exists but does not match the recorded proxy checksum",
                location="artifact (publish step)",
                details={"expected_sha256": sha256},
            )
        _remove_file(staged_path)
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged_path, final_path)
    except OSError as exc:
        raise VideoProxyError(
            CODE_PUBLICATION_FAILED,
            f"atomic rename into final path failed: {exc}",
            location="artifact (publish step)",
        ) from exc
    return True


def _publish_effect(
    ctx: WorkerContext,
    final_rel: str,
    sha256: str,
    size: int,
) -> None:
    """Persist artifact row + owner link in ONE transaction (state+effect
    coupling, contract §7.1/§9.2)."""
    if ctx.session_factory is None:
        raise VideoProxyError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot persist publication",
            location="artifact (publish step)",
        )
    workspace_id = str(ctx.input_manifest["workspace_id"])
    project_id = str(ctx.input_manifest["project_id"])
    video_item_id = str(ctx.input_manifest["video_item_id"])
    artifact_id = _artifact_id(ctx, final_rel)

    with ctx.session_factory() as session:
        # Ownership + source re-validation at publication (correction #2
        # pattern): the chain may have changed between submit and run.
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
            source_artifact_id=str(ctx.input_manifest["source_artifact_id"]),
        )

        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            artifact = Artifact(
                id=artifact_id,
                workspace_id=workspace_id,
                kind="video",
                relative_path=final_rel,
                state="ready",
                sha256=sha256,
                size_bytes=size,
                mime_type="video/mp4",
            )
            session.add(artifact)
        else:
            # Replay: the row exists from an earlier attempt.  Verify the
            # evidence and repair a partial row; a mismatched row means the
            # file changed between attempts and must fail closed.
            if artifact.sha256 != sha256 or artifact.size_bytes != size:
                raise VideoProxyError(
                    CODE_PROXY_VALIDATION_FAILED,
                    "existing artifact row conflicts with the proxy evidence",
                    location="artifact (publish step)",
                    details={"artifact_id": artifact_id},
                )
            if artifact.state != "ready":
                artifact.state = "ready"
                artifact.updated_at = datetime.now(UTC)

        owner = session.get(
            ArtifactOwner,
            (artifact_id, "video_item", video_item_id, ARTIFACT_PURPOSE_PROXY),
        )
        if owner is None:
            session.add(
                ArtifactOwner(
                    artifact_id=artifact_id,
                    owner_type="video_item",
                    owner_id=video_item_id,
                    purpose=ARTIFACT_PURPOSE_PROXY,
                )
            )
        session.commit()


# ── Output validator (verified-publication completion gate) ─────────────────


def _proxy_output_validator(
    ctx: WorkerContext, result: dict[str, Any], staging_dir: Path
) -> dict[str, Any]:
    """Re-verify the published proxy on disk before the step may complete.

    The worker invokes this after the handler returns; the Job reaches
    ``completed`` only after this validator passes (contract §9.3: completed
    never precedes verified publication).
    """
    del staging_dir
    published = result.get("published") or {}
    final_rel = published.get("final_rel")
    if not isinstance(final_rel, str):
        raise RuntimeError("proxy result missing published.final_rel")
    managed = _managed_for(ctx)
    try:
        target = managed.resolve(final_rel)
    except ManagedPathError as exc:
        raise RuntimeError(f"proxy output path rejected: {exc}") from exc
    if not target.is_file():
        raise RuntimeError(f"published proxy missing at {final_rel}")
    sha = hash_file(target)
    size = target.stat().st_size
    if sha != published.get("sha256") or size != published.get("size_bytes"):
        raise RuntimeError(
            "published proxy sha256/size do not match the handler evidence"
        )
    return {
        "proxy": {
            "relative_path": final_rel,
            "sha256": sha,
            "size_bytes": size,
        }
    }


# ── FFmpeg invocation (bounded + cancellable, list args only) ───────────────


def _build_ffmpeg_command(
    ffmpeg: str,
    src_path: Path,
    staged_path: Path,
    profile: ProxyProfile,
    timebase: CanonicalTimebase,
    source_probe: dict[str, Any],
) -> list[str]:
    """Build the FFmpeg argument list (never a shell string).

    Output is forced onto the canonical CFR grid (``-r num/den`` +
    ``-fps_mode cfr``), downscaled to fit the profile box (never upscaled),
    H.264/yuv420p at the profile CRF, with a low-bitrate AAC track when the
    source has audio, bounded to the source duration.
    """
    cmd = [ffmpeg, "-y", "-i", str(src_path)]
    duration = source_probe.get("container", {}).get("duration_seconds")
    if duration is not None and float(duration) > 0:
        cmd += ["-t", f"{float(duration):.6f}"]
    cmd += [
        "-vf",
        (
            f"scale={profile.max_width}:{profile.max_height}:"
            "force_original_aspect_ratio=decrease"
        ),
        "-r",
        f"{timebase.fps_num}/{timebase.fps_den}",
        "-fps_mode",
        "cfr",
        "-c:v",
        "libx264",
        "-preset",
        profile.preset,
        "-crf",
        str(profile.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if profile.include_audio and source_probe.get("has_audio"):
        cmd += ["-c:a", "aac", "-b:a", profile.audio_bitrate, "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd.append(str(staged_path))
    return cmd


def _run_ffmpeg(
    ctx: WorkerContext, cmd: list[str], *, timeout_seconds: int, staged_path: Path
) -> None:
    """Run FFmpeg with list args, a bounded budget and cooperative cancel.

    The process is polled every ≤0.5s: a durable cancel flag terminates it
    (``CANCELLED``); the bounded budget terminates it (``PROXY_TIMEOUT``,
    transient); a non-zero exit fails with ``PROXY_FFMPEG_FAILED``.  The
    staging partial is removed on every failure path.
    """
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    except OSError as exc:
        raise VideoProxyError(
            CODE_PROXY_FFMPEG_FAILED,
            f"could not start ffmpeg: {exc}",
            location="generate phase",
        ) from exc
    deadline = _monotonic() + timeout_seconds
    stderr_tail = ""
    try:
        while True:
            if ctx.is_cancelled():
                _terminate_proc(proc)
                _remove_file(staged_path)
                raise VideoProxyError(
                    CODE_CANCELLED,
                    "proxy generation cancelled during ffmpeg",
                    location="phase:generate",
                )
            remaining = deadline - _monotonic()
            if remaining <= 0:
                _terminate_proc(proc)
                _remove_file(staged_path)
                raise VideoProxyError(
                    CODE_PROXY_TIMEOUT,
                    f"ffmpeg exceeded the {timeout_seconds}s bounded budget",
                    location="generate phase",
                    details={"timeout_seconds": timeout_seconds},
                )
            try:
                _out, err = proc.communicate(timeout=min(0.5, max(0.01, remaining)))
                stderr_tail = (err or "")[-400:]
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        _terminate_proc(proc)
        raise
    if proc.returncode != 0:
        _remove_file(staged_path)
        raise VideoProxyError(
            CODE_PROXY_FFMPEG_FAILED,
            f"ffmpeg exited {proc.returncode}",
            location="generate phase",
            details={"returncode": proc.returncode, "stderr_tail": stderr_tail},
        )


def _terminate_proc(proc: subprocess.Popen[Any]) -> None:
    """Terminate then kill a running subprocess (bounded wait)."""
    with contextlib.suppress(Exception):  # noqa: BLE001 - best-effort teardown
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


# ── Submit (contract §8.1 idempotency, owner-scoped) ────────────────────────


def _idempotency_key(video_item_id: str, source_sha256: str, generation: str) -> str:
    """Owner-scoped GENERATE_PROXY idempotency key.

    The logical identity is scoped to the VideoItem owner and the source
    content (the managed source artifact's SHA-256), so the same source
    bytes proxied for two different VideoItems create two independent
    Jobs/effect sets::

        GENERATE_PROXY:video_item:<video_item_id>:<source_sha256>:<generation>

    ``generation`` distinguishes explicit re-proxies of the same owner+source.
    """
    return f"{JOB_TYPE_GENERATE_PROXY}:video_item:{video_item_id}:{source_sha256}:{generation}"


def submit_proxy(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    source_artifact_id: str,
    generation: str = "1",
    managed_root: str | Path | None = None,
    title: str | None = None,
    profile: ProxyProfile | None = None,
) -> ProxySubmitResult:
    """Create the durable GENERATE_PROXY Job for one managed source artifact.

    The idempotency key is **owner-scoped** and embeds the source content
    identity (the managed artifact's SHA-256).  A completed duplicate for
    the same (owner, source, generation) returns the existing Job
    (``reused=True``); an active duplicate raises ``IdempotencyKeyInUse`` —
    exactly one effect set per logical proxy of a VideoItem.

    Ownership and source-artifact validity are checked **before any managed
    write** (S05-T02 correction #2 pattern): the active VideoItem must belong
    to *project_id*/*workspace_id* and the source artifact must be a
    ``ready`` video linked with purpose ``source`` to that VideoItem.  The
    worker re-validates the same chain at run time and at publication.

    The request path never runs FFmpeg and never hashes the source — the
    proxy is generated by the durable worker, which computes the proxy's
    SHA-256/size during/after the encode.

    Raises:
        VideoProxyError: ``INPUT_MISSING``/``VIDEO_ITEM_NOT_FOUND`` /
            ``PROJECT_NOT_FOUND`` / ``OWNERSHIP_MISMATCH`` /
            ``SOURCE_ARTIFACT_NOT_FOUND`` / ``SOURCE_NOT_READY`` /
            ``SOURCE_OWNER_MISMATCH`` / ``INVALID_PROXY_PROFILE``.
        ValueError: for empty ids.
        IdempotencyKeyInUse: an active Job already exists for the key.
    """
    if not workspace_id or not project_id or not video_item_id or not source_artifact_id:
        raise ValueError(
            "workspace_id, project_id, video_item_id and source_artifact_id are required"
        )
    profile = profile or ProxyProfile()

    with session_factory() as session:
        from app.persistence.jobs import JobRepository
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
            source_artifact_id=source_artifact_id,
        )
        source_sha256 = artifact.sha256 or ""
        source_relative_path = artifact.relative_path

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "source_artifact_id": source_artifact_id,
            "source_sha256": source_sha256,
            "source_relative_path": source_relative_path,
            "generation": generation,
            "title": title or "proxy",
            "proxy_profile": profile.to_json(),
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
        job = JobRepository(session).create_job(
            workspace_id=workspace_id,
            job_type=JOB_TYPE_GENERATE_PROXY,
            owner_type="video_item",
            owner_id=video_item_id,
            input_manifest=manifest,
            idempotency_key=idempotency_key,
            input_generation=generation,
            steps=generate_proxy_steps(),
            actor="api",
        )
        session.commit()
        return ProxySubmitResult(job_id=job.id, reused=completed_exists is not None)


def generate_proxy_steps() -> list[StepInput]:
    """The GENERATE_PROXY step plan (one sync step: generate→verify→publish)."""
    return [StepInput(step_code=PROXY_STEP_CODE, position=0, step_type="sync")]


def register_generate_proxy_handler(worker: Any) -> None:
    """Register the GENERATE_PROXY handler on a DurableWorker instance.

    An ``output_validator`` re-verifies the published proxy on disk before
    the step may complete, so the Job's ``completed`` state can never
    precede verified publication (contract §9.3).
    """
    worker.register_handler(
        JOB_TYPE_GENERATE_PROXY,
        generate_proxy_handler,
        output_validator=_proxy_output_validator,
    )
