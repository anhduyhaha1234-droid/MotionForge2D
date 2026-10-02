"""Scene detection durable job (S05-T04) — reuses the approved ANALYZE_MEDIA class.

Implements the S05-T04 outcome on top of the approved S05-T02 import and
S05-T03 canonical timebase + managed proxy:

- **Job class reuse** — scene detection runs as an ``ANALYZE_MEDIA`` Job
  (DURABLE_JOB_CONTRACT §3, the approved import/analyze class; WS-03 lists
  "Scene detection/keyframes" inside Import & Analyze).  The step code is
  ``scene_detect`` (``SCENE_DETECT_STEP_CODE``), distinct from the S05-T02
  import step ``import``.  No new job type is invented; registration installs
  one ``ANALYZE_MEDIA`` dispatcher that routes ``import`` steps to the
  approved S05-T02 handler and ``scene_detect`` steps to this module's
  handler, so existing import jobs behave exactly as before.
- **Input** — the managed ``ready`` proxy artifact (S05-T03, purpose
  ``proxy``) when one is supplied and still valid, otherwise the managed
  source artifact (purpose ``source``).  Every path goes through
  ``ManagedRoot``; the input is opened read-only and never modified.
- **Canonical timebase** — ``CanonicalTimebase.from_probe`` (S05-T03 exact
  rational grid, CFR → ``r_frame_rate``, VFR → ``avg_frame_rate``); the
  schema-versioned payload is persisted in the checkpoint.  Detected cut
  timestamps are parsed as exact decimal ``Fraction`` and mapped to frame
  indexes with :meth:`CanonicalTimebase.time_to_frame` (round_half_up) —
  no binary float on the mapping path.
- **Detection** — FFmpeg's ``scene`` filter + ``showinfo`` (list arguments
  only, discovery only via ``app.services.ffmpeg_utils.find_ffmpeg``,
  bounded budget, polled against ``ctx.is_cancelled()``).  No PySceneDetect,
  no OpenCV, no direct frame-byte reads — the deprecated legacy frame access
  (``app/services/scene_detection.py``) is not used and ``legacy_scene_id``
  is never written (rows are created with ``legacy_scene_id = NULL``).
- **Stable Scene IDs** — scene rows are committed **in one transaction** with
  deterministic ids derived from ``(job_id, position)`` (DURABLE_JOB_CONTRACT
  §8.3).  Retry/replay/restart reuses rows by checkpoint: a committed
  ``published`` checkpoint is verified row-by-row; the crash-window (rows
  committed, published checkpoint not yet written) is closed by reusing rows
  whose evidence exactly matches the detection spec.  Rows from any other
  source (legacy import, a different generation) fail closed with
  ``SCENE_EVIDENCE_CONFLICT`` — never overwritten, never deleted.
- **Cleanup** — cancellation/failure/timeout raise before the effect
  transaction (or the transaction rolls back), so a partial attempt leaves
  zero scene rows; committed rows survive every later failure.  The
  detection itself writes no staging files, so there is nothing to
  garbage-collect on disk.
- **Containment** — source and proxy artifacts are never modified; the
  checkpoint carries only normalized relative paths (no absolute managed
  path is persisted).

No schema change: the durable write surface is exactly the existing
``scene`` table (PERSISTENCE_DOMAIN_CONTRACT §4).
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.artifacts import ManagedPathError, ManagedRoot
from app.persistence.jobs import StepInput
from app.persistence.models import Artifact, ArtifactOwner, Scene
from app.services import video_import, video_proxy
from app.services.ffmpeg_utils import find_ffmpeg
from app.services.timebase import CanonicalTimebase, TimebaseError
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "ARTIFACT_PURPOSE_PROXY",
    "CODE_CANCELLED",
    "CODE_FFMPEG_BINARY_NOT_FOUND",
    "CODE_INPUT_CHANGED",
    "CODE_OWNERSHIP_MISMATCH",
    "CODE_PATH_CONTAINMENT",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_PROXY_ARTIFACT_NOT_FOUND",
    "CODE_PROXY_NOT_READY",
    "CODE_PROXY_OWNER_MISMATCH",
    "CODE_PUBLICATION_FAILED",
    "CODE_SCENE_DETECT_FAILED",
    "CODE_SCENE_DETECT_TIMEOUT",
    "CODE_SCENE_EVIDENCE_CONFLICT",
    "CODE_SCENE_PROFILE_INVALID",
    "CODE_SOURCE_ARTIFACT_NOT_FOUND",
    "CODE_SOURCE_FILE_MISSING",
    "CODE_SOURCE_NOT_READY",
    "CODE_SOURCE_OWNER_MISMATCH",
    "CODE_UNKNOWN_ANALYZE_STEP",
    "CODE_VIDEO_ITEM_NOT_FOUND",
    "DEFAULT_SCENE_DETECT_TIMEOUT_SECONDS",
    "DEFAULT_SCENE_THRESHOLD",
    "DEFAULT_MIN_SCENE_LEN_FRAMES",
    "JOB_TYPE_ANALYZE_MEDIA",
    "SCENE_DETECT_STEP_CODE",
    "SCENE_SCHEMA_VERSION",
    "SCENE_STATUS_PENDING",
    "SceneDetectionProfile",
    "SceneDetectionSubmitResult",
    "SceneDetectorError",
    "VIETNAMESE_ACTIONS",
    "register_scene_detection_handler",
    "scene_detection_handler",
    "scene_detection_steps",
    "submit_scene_detection",
]

#: Approved job class reused for scene detection (DURABLE_JOB_CONTRACT §3;
#: WS-03 "Scene detection/keyframes" is part of Import & Analyze).
JOB_TYPE_ANALYZE_MEDIA = video_import.JOB_TYPE_ANALYZE_MEDIA

#: The sync step that executes the whole scene-detection pipeline
#: (distinct from the S05-T02 import step ``import``).
SCENE_DETECT_STEP_CODE = "scene_detect"

#: Schema version of the scene-detection checkpoint payload.
SCENE_SCHEMA_VERSION = 1

#: Status of auto-detected scenes (PERSISTENCE_DOMAIN_CONTRACT §4: pending,
#: draft, approved — auto-detection produces unapproved rows).
SCENE_STATUS_PENDING = "pending"

#: Artifact-owner purpose of the S05-T03 editing proxy.
ARTIFACT_PURPOSE_PROXY = video_proxy.ARTIFACT_PURPOSE_PROXY

#: Default scene-change sensitivity (FFmpeg scene score, 0..1; higher = fewer
#: cuts).  Mirrors the legacy default threshold of 27/100 ≈ 0.27, rounded up.
DEFAULT_SCENE_THRESHOLD = 0.3

#: Default minimum scene length in frames (mirrors the legacy default).
DEFAULT_MIN_SCENE_LEN_FRAMES = 15

#: Default bounded FFmpeg budget (seconds) for one detection run.
DEFAULT_SCENE_DETECT_TIMEOUT_SECONDS = 120

# ── Stable error codes ───────────────────────────────────────────────────────

CODE_SCENE_DETECT_FAILED = "SCENE_DETECT_FAILED"
CODE_SCENE_DETECT_TIMEOUT = "SCENE_DETECT_TIMEOUT"
CODE_SCENE_PROFILE_INVALID = "SCENE_PROFILE_INVALID"
CODE_INPUT_CHANGED = "INPUT_CHANGED"
CODE_SCENE_EVIDENCE_CONFLICT = "SCENE_EVIDENCE_CONFLICT"
CODE_UNKNOWN_ANALYZE_STEP = "UNKNOWN_ANALYZE_STEP"
CODE_PROXY_ARTIFACT_NOT_FOUND = "PROXY_ARTIFACT_NOT_FOUND"
CODE_PROXY_NOT_READY = "PROXY_NOT_READY"
CODE_PROXY_OWNER_MISMATCH = "PROXY_OWNER_MISMATCH"

#: Reused stable codes from the approved import/proxy taxonomies.
CODE_VIDEO_ITEM_NOT_FOUND = video_import.CODE_VIDEO_ITEM_NOT_FOUND
CODE_PROJECT_NOT_FOUND = video_import.CODE_PROJECT_NOT_FOUND
CODE_OWNERSHIP_MISMATCH = video_import.CODE_OWNERSHIP_MISMATCH
CODE_PUBLICATION_FAILED = video_import.CODE_PUBLICATION_FAILED
CODE_CANCELLED = video_import.CODE_CANCELLED
CODE_PATH_CONTAINMENT = video_import.CODE_PATH_CONTAINMENT
CODE_SOURCE_ARTIFACT_NOT_FOUND = video_proxy.CODE_SOURCE_ARTIFACT_NOT_FOUND
CODE_SOURCE_NOT_READY = video_proxy.CODE_SOURCE_NOT_READY
CODE_SOURCE_OWNER_MISMATCH = video_proxy.CODE_SOURCE_OWNER_MISMATCH
CODE_SOURCE_FILE_MISSING = video_proxy.CODE_SOURCE_FILE_MISSING
CODE_FFMPEG_BINARY_NOT_FOUND = video_proxy.CODE_FFMPEG_BINARY_NOT_FOUND

#: Vietnamese suggested actions (PRD §9 Step 5 acceptance / FR-08) for every
#: stable code this module raises; reused codes keep the approved actions.
VIETNAMESE_ACTIONS: dict[str, str] = {
    **video_import.VIETNAMESE_ACTIONS,
    **video_proxy.VIETNAMESE_ACTIONS,
    CODE_SCENE_DETECT_FAILED: (
        "Không phát hiện được cảnh (ffmpeg thoát lỗi). Tệp proxy/nguồn có thể "
        "bị hỏng; hãy kiểm tra lại và thử lại."
    ),
    CODE_SCENE_DETECT_TIMEOUT: (
        "Quá thời gian phát hiện cảnh. Hãy thử lại; nếu tệp quá lớn, hãy kiểm "
        "tra định dạng hoặc tốc độ ổ đĩa."
    ),
    CODE_SCENE_PROFILE_INVALID: (
        "Profile phát hiện cảnh không hợp lệ (ngưỡng phải trong [0,1], độ dài "
        "tối thiểu ≥ 1, thời gian > 0). Hãy kiểm tra lại cấu hình."
    ),
    CODE_INPUT_CHANGED: (
        "Đầu vào của Job đã thay đổi so với lần chạy trước (proxy/nguồn khác "
        "hoặc tệp bị thay thế). Hãy tạo lại Job với generation mới để phân "
        "tích lại."
    ),
    CODE_SCENE_EVIDENCE_CONFLICT: (
        "Dữ liệu cảnh hiện có của Video Item không khớp với kết quả phát hiện "
        "(cảnh đã tồn tại từ nguồn khác). Job không ghi đè cảnh của nguồn "
        "khác; hãy kiểm tra dữ liệu cảnh hiện có trước khi phân tích lại."
    ),
    CODE_UNKNOWN_ANALYZE_STEP: (
        "Bước ANALYZE_MEDIA không xác định. Hãy báo lỗi hệ thống kèm Job id."
    ),
    CODE_PROXY_ARTIFACT_NOT_FOUND: (
        "Artifact proxy không tồn tại hoặc không thuộc Workspace này. Hãy tạo "
        "proxy (S05-T03) trước khi phát hiện cảnh."
    ),
    CODE_PROXY_NOT_READY: (
        "Artifact proxy chưa sẵn sàng (không phải video ready hoặc thiếu "
        "checksum). Hãy đợi proxy hoàn tất rồi thử lại."
    ),
    CODE_PROXY_OWNER_MISMATCH: (
        "Artifact proxy không được liên kết với Video Item này (thiếu liên kết "
        "purpose=proxy). Hãy tạo proxy cho đúng Video Item."
    ),
}


class SceneDetectorError(Exception):
    """A stable, actionable scene-detection failure (contract §10.1).

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
class SceneDetectionProfile:
    """Bounded scene-detection knobs (all validated).

    Attributes:
        threshold: FFmpeg scene score threshold in ``[0, 1]`` (higher =
            fewer cuts).
        min_scene_len_frames: Minimum scene length in frames (>= 1); cuts
            closer than this are merged into the preceding scene.
        timeout_seconds: Bounded FFmpeg budget (> 0).
    """

    threshold: float = DEFAULT_SCENE_THRESHOLD
    min_scene_len_frames: int = DEFAULT_MIN_SCENE_LEN_FRAMES
    timeout_seconds: int = DEFAULT_SCENE_DETECT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise SceneDetectorError(
                CODE_SCENE_PROFILE_INVALID,
                f"threshold must be within [0, 1]: {self.threshold}",
                location="scene_detection_profile",
                details={"threshold": self.threshold},
            )
        if self.min_scene_len_frames < 1:
            raise SceneDetectorError(
                CODE_SCENE_PROFILE_INVALID,
                f"min_scene_len_frames must be >= 1: {self.min_scene_len_frames}",
                location="scene_detection_profile",
                details={"min_scene_len_frames": self.min_scene_len_frames},
            )
        if self.timeout_seconds <= 0:
            raise SceneDetectorError(
                CODE_SCENE_PROFILE_INVALID,
                f"timeout_seconds must be positive: {self.timeout_seconds}",
                location="scene_detection_profile",
                details={"timeout_seconds": self.timeout_seconds},
            )

    def to_json(self) -> dict[str, Any]:
        """Schema-versioned durable profile payload (manifest/checkpoint)."""
        return {
            "schema_version": 1,
            "threshold": self.threshold,
            "min_scene_len_frames": self.min_scene_len_frames,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any] | None) -> SceneDetectionProfile:
        """Rebuild a profile from :meth:`to_json`; missing → default profile."""
        if not payload:
            return cls()
        return cls(
            threshold=float(payload.get("threshold", DEFAULT_SCENE_THRESHOLD)),
            min_scene_len_frames=int(
                payload.get("min_scene_len_frames", DEFAULT_MIN_SCENE_LEN_FRAMES)
            ),
            timeout_seconds=int(
                payload.get("timeout_seconds", DEFAULT_SCENE_DETECT_TIMEOUT_SECONDS)
            ),
        )


@dataclass(frozen=True)
class SceneDetectionSubmitResult:
    """Result of :func:`submit_scene_detection` — the durable Job id and
    reuse flag."""

    job_id: str
    reused: bool


# ── Managed path helpers (mirror video_import / video_proxy) ─────────────────


def _managed_for(ctx: WorkerContext) -> ManagedRoot:
    """ManagedRoot bound to the Job's manifest managed root."""
    return ManagedRoot(Path(str(ctx.input_manifest.get("managed_root") or "artifacts")))


def _raise_if_cancelled(ctx: WorkerContext, phase: str) -> None:
    """Fail with the stable cancel code when the durable flag is set."""
    if ctx.is_cancelled():
        raise SceneDetectorError(
            CODE_CANCELLED,
            f"scene detection cancelled before {phase} phase",
            location=f"phase:{phase}",
        )


def _wrap_managed_errors(exc: ManagedPathError) -> SceneDetectorError:
    """Map a containment failure to the stable PATH_CONTAINMENT envelope."""
    return SceneDetectorError(
        CODE_PATH_CONTAINMENT,
        f"managed path rejected: {exc}",
        location="managed path",
        details={"reason": str(exc)},
    )


def _monotonic() -> float:
    """Monotonic clock seam (tests inject a fake to force timeouts)."""
    return time.monotonic()


def _strip_probe_paths(probe: dict[str, Any]) -> dict[str, Any]:
    """Remove the display-only absolute ``file_path`` before durable storage."""
    return {**probe, "file_path": None}


# ── Input validation (submit + run-time) ─────────────────────────────────────


def _validate_proxy_artifact(
    session: Session,
    *,
    workspace_id: str,
    video_item_id: str,
    proxy_artifact_id: str,
) -> Artifact:
    """Verify the managed proxy artifact chain for the VideoItem.

    The artifact must exist in *workspace_id*, be ``kind='video'`` and
    ``state='ready'`` with a recorded SHA-256, and carry an ``artifact_owner``
    link (``video_item``/``video_item_id``/purpose ``proxy``).  Called at
    submit time (fail fast) and again in the input phase.
    """
    artifact = session.get(Artifact, proxy_artifact_id)
    if artifact is None or artifact.workspace_id != workspace_id:
        raise SceneDetectorError(
            CODE_PROXY_ARTIFACT_NOT_FOUND,
            f"proxy artifact {proxy_artifact_id!r} not found in workspace {workspace_id!r}",
            location="artifact",
            details={"proxy_artifact_id": proxy_artifact_id},
        )
    if artifact.kind != "video" or artifact.state != "ready" or not artifact.sha256:
        raise SceneDetectorError(
            CODE_PROXY_NOT_READY,
            f"proxy artifact {proxy_artifact_id!r} is not a ready video with a "
            f"recorded checksum (kind={artifact.kind!r}, state={artifact.state!r})",
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
        (artifact.id, "video_item", video_item_id, ARTIFACT_PURPOSE_PROXY),
    )
    if owner is None:
        raise SceneDetectorError(
            CODE_PROXY_OWNER_MISMATCH,
            f"proxy artifact {artifact.id!r} is not linked as the proxy of "
            f"video item {video_item_id!r}",
            location="artifact_owner",
            details={"artifact_id": artifact.id, "video_item_id": video_item_id},
        )
    return artifact


# ── Exact integer-millisecond helpers (rational arithmetic only) ─────────────


def _exact_ms(x: Fraction) -> int:
    """Nearest integer millisecond of an exact ``Fraction`` (round half-up)."""
    if x.numerator >= 0:
        return (2 * x.numerator + x.denominator) // (2 * x.denominator)
    return -((2 * -x.numerator + x.denominator) // (2 * x.denominator))


def scene_ms_range(
    timebase: CanonicalTimebase, start_frame: int, end_frame: int
) -> tuple[int, int]:
    """Canonical integer-ms range of the inclusive frame interval [start, end].

    The interval is treated half-open: ``[t(start), t(end + 1))``.  The start
    bound is ``round_half_up(t(start) * 1000)``; the end bound is
    ``round_half_up(t(end + 1) * 1000) - 1`` (the last integer millisecond
    inside the interval), clamped to never fall below the start bound.  All
    arithmetic is exact (``Fraction``), never binary-float drift.
    """
    start_ms = _exact_ms(timebase.frame_to_time(start_frame) * 1000)
    end_exclusive_ms = _exact_ms(timebase.frame_to_time(end_frame + 1) * 1000)
    return start_ms, max(start_ms, end_exclusive_ms - 1)


def cuts_to_scenes(
    cuts: list[int], nb_frames: int, min_scene_len_frames: int
) -> list[tuple[int, int]]:
    """Turn sorted cut frame indexes into inclusive (start, end) scene pairs.

    A cut at frame ``f`` means "a new scene starts at ``f``" (the previous
    scene ends at ``f - 1``).  Cuts closer than ``min_scene_len_frames`` to
    the previous boundary are merged into the preceding scene; a final tail
    shorter than the minimum is merged into the last scene.  The whole video
    is always at least one scene ``(0, nb_frames - 1)``; empty intervals are
    dropped.  Deterministic: same inputs ⇒ same output.
    """
    kept: list[int] = []
    prev = 0
    for f in sorted(set(int(c) for c in cuts)):
        f = min(max(f, 0), nb_frames - 1)
        if f - prev < min_scene_len_frames:
            continue
        kept.append(f)
        prev = f
    if kept and nb_frames - 1 - kept[-1] < min_scene_len_frames:
        kept.pop()
    scenes: list[tuple[int, int]] = []
    start = 0
    for f in kept:
        scenes.append((start, f - 1))
        start = f
    scenes.append((start, nb_frames - 1))
    return [(s, e) for s, e in scenes if s <= e]


# ── The ANALYZE_MEDIA scene_detect handler ───────────────────────────────────


def scene_detection_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one scene-detection run: input → detect → publish (idempotent).

    The handler resumes from the step checkpoint: a valid input evidence is
    re-verified, a completed detection is reused instead of re-running FFmpeg,
    and a published effect is verified row-by-row and skipped.  Every phase
    observes ``ctx.is_cancelled()``; scene rows are committed in ONE
    transaction so a partial attempt leaves zero rows.
    """
    managed = _managed_for(ctx)
    cp = ctx.checkpoint
    if not isinstance(cp, dict):
        cp = {"schema_version": SCENE_SCHEMA_VERSION}

    input_ev = _input_phase(ctx, cp, managed)
    cp = {**cp, "input": input_ev, "phase": "input"}
    ctx.progress(10, "input resolved")
    det_ev = _detect_phase(ctx, cp, managed, input_ev)
    cp = {**cp, "detection": det_ev, "phase": "detection"}
    ctx.progress(60, "scene cuts detected")
    published = _publish_phase(ctx, cp, input_ev, det_ev)
    ctx.progress(100, "scenes published")
    return {"input": input_ev, "detection": det_ev, "published": published}


def _input_phase(ctx: WorkerContext, cp: dict[str, Any], managed: ManagedRoot) -> dict[str, Any]:
    """Input phase: re-validate the chain and resolve proxy-or-source.

    The managed ``ready`` proxy artifact is preferred (S05-T03); when the
    manifest names a proxy that is absent/not-ready/not-linked or whose
    managed file is missing/size-mismatched, the managed source artifact is
    used instead.  On replay the resolved input must equal the checkpointed
    input evidence exactly, else ``INPUT_CHANGED`` (the logical run's inputs
    changed; a new generation is required).
    """
    _raise_if_cancelled(ctx, "input")
    if ctx.session_factory is None:
        raise SceneDetectorError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot resolve the input",
            location="artifact (input phase)",
        )
    manifest = ctx.input_manifest
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    video_item_id = str(manifest["video_item_id"])
    source_artifact_id = str(manifest["source_artifact_id"])
    proxy_artifact_id = manifest.get("proxy_artifact_id")

    with ctx.session_factory() as session:
        video_import._validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        source = video_proxy._validate_source_artifact(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            source_artifact_id=source_artifact_id,
        )
        proxy: Artifact | None = None
        if proxy_artifact_id:
            try:
                proxy = _validate_proxy_artifact(
                    session,
                    workspace_id=workspace_id,
                    video_item_id=video_item_id,
                    proxy_artifact_id=str(proxy_artifact_id),
                )
            except SceneDetectorError:
                # Proxy chain invalid at run time → fall back to the managed
                # source ("or managed source if proxy absent").
                proxy = None

    artifact = proxy if proxy is not None else source
    kind = "proxy" if proxy is not None else "source"
    rel = artifact.relative_path
    sha256 = artifact.sha256 or ""
    size = artifact.size_bytes

    try:
        input_path = managed.resolve(rel)
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    if not input_path.is_file():
        raise SceneDetectorError(
            CODE_SOURCE_FILE_MISSING,
            f"managed {kind} file missing at {rel}",
            location=f"artifact (input phase, kind={kind})",
            details={"relative_path": rel, "kind": kind},
        )
    if size is not None and input_path.stat().st_size != size:
        raise SceneDetectorError(
            CODE_SOURCE_FILE_MISSING,
            f"managed {kind} file size {input_path.stat().st_size} does not "
            f"match the recorded artifact size {size}",
            location=f"artifact (input phase, kind={kind})",
            details={"relative_path": rel, "expected_size": size, "kind": kind},
        )

    input_ev = {
        "kind": kind,
        "artifact_id": artifact.id,
        "relative_path": rel,
        "sha256": sha256,
        "size_bytes": size,
    }
    previous = cp.get("input")
    if isinstance(previous, dict) and previous != input_ev:
        raise SceneDetectorError(
            CODE_INPUT_CHANGED,
            "job input changed between attempts "
            f"(was {previous.get('kind')!r}/{previous.get('artifact_id')!r}, "
            f"now {kind!r}/{artifact.id!r})",
            location="artifact (input phase)",
            details={"previous": previous, "current": input_ev},
        )
    ctx.write_checkpoint({**cp, "input": input_ev, "phase": "input"})
    return input_ev


def _detect_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    managed: ManagedRoot,
    input_ev: dict[str, Any],
) -> dict[str, Any]:
    """Detect phase: reuse the checkpointed cuts or run FFmpeg once.

    The checkpointed detection is reused when its recorded input evidence
    still matches the resolved input and the managed file still exists with
    the recorded size — a re-run never re-detects a valid input.  A detection
    checkpoint whose input no longer matches fails closed with
    ``INPUT_CHANGED`` (never silently re-detects against different bytes).
    """
    det_ev = cp.get("detection")
    if isinstance(det_ev, dict) and _detection_evidence_valid(managed, det_ev, input_ev):
        return det_ev
    if isinstance(det_ev, dict):
        raise SceneDetectorError(
            CODE_INPUT_CHANGED,
            "checkpointed detection evidence no longer matches the resolved input",
            location="detect phase",
            details={
                "checkpointed_input": det_ev.get("input"),
                "resolved_input": input_ev,
            },
        )
    _raise_if_cancelled(ctx, "detect")

    profile = SceneDetectionProfile.from_json(ctx.input_manifest.get("scene_detection_profile"))
    try:
        input_path = managed.resolve(str(input_ev["relative_path"]))
    except ManagedPathError as exc:
        raise _wrap_managed_errors(exc) from exc
    probe = video_import.probe_source(input_path)
    timebase = CanonicalTimebase.from_probe(probe)
    nb_frames = timebase.nb_frames
    if not nb_frames or nb_frames < 1:
        raise TimebaseError(
            "INVALID_TIMEBASE",
            "scene detection requires a known positive canonical frame count",
            location="nb_frames",
            details={"nb_frames": nb_frames},
        )

    cuts = _run_scene_detect(ctx, input_path, profile, timebase)
    scenes = cuts_to_scenes(cuts, nb_frames, profile.min_scene_len_frames)
    scene_specs: list[dict[str, Any]] = []
    for position, (start_frame, end_frame) in enumerate(scenes):
        start_time_ms, end_time_ms = scene_ms_range(timebase, start_frame, end_frame)
        scene_specs.append(
            {
                "position": position,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "start_time_ms": start_time_ms,
                "end_time_ms": end_time_ms,
                "status": SCENE_STATUS_PENDING,
            }
        )
    det_ev = {
        "schema_version": SCENE_SCHEMA_VERSION,
        "input": input_ev,
        "timebase": timebase.to_json(),
        "cuts": cuts,
        "nb_frames": nb_frames,
        "scenes": scene_specs,
        "detected_at": datetime.now(UTC).isoformat(),
    }
    ctx.write_checkpoint({**cp, "detection": det_ev, "phase": "detection"})
    return det_ev


def _detection_evidence_valid(
    managed: ManagedRoot, det_ev: dict[str, Any], input_ev: dict[str, Any]
) -> bool:
    """True when the checkpointed detection still describes the same input."""
    if det_ev.get("schema_version") != SCENE_SCHEMA_VERSION:
        return False
    if det_ev.get("input") != input_ev:
        return False
    if not isinstance(det_ev.get("scenes"), list):
        return False
    rel = input_ev.get("relative_path")
    if not isinstance(rel, str):
        return False
    try:
        input_path = managed.resolve(rel)
    except ManagedPathError:
        return False
    if not input_path.is_file():
        return False
    recorded_size = input_ev.get("size_bytes")
    if recorded_size is not None:
        try:
            if input_path.stat().st_size != int(recorded_size):
                return False
        except OSError:
            return False
    return True


def _run_scene_detect(
    ctx: WorkerContext,
    input_path: Path,
    profile: SceneDetectionProfile,
    timebase: CanonicalTimebase,
) -> list[int]:
    """Run the bounded, cancellable FFmpeg scene detection.

    ``select='gt(scene,THRESHOLD)',showinfo`` emits one stderr line per cut
    frame; each cut's ``pts_time`` is parsed as an exact decimal ``Fraction``
    and mapped to the canonical frame index with round-half-up rational
    arithmetic.  List arguments only; discovery only via ``ffmpeg_utils``;
    no shell; no frame-byte reads outside the approved toolchain path.
    """
    try:
        ffmpeg = find_ffmpeg()
    except FileNotFoundError as exc:
        raise SceneDetectorError(
            CODE_FFMPEG_BINARY_NOT_FOUND,
            "ffmpeg binary not found by app.services.ffmpeg_utils",
            location="toolchain",
        ) from exc

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-i",
        str(input_path),
        "-an",
        "-vf",
        f"select='gt(scene,{profile.threshold!r})',showinfo",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        raise SceneDetectorError(
            CODE_SCENE_DETECT_FAILED,
            f"could not start ffmpeg: {exc}",
            location="detect phase",
        ) from exc

    deadline = _monotonic() + profile.timeout_seconds
    stderr_tail = ""
    try:
        while True:
            if ctx.is_cancelled():
                _terminate_proc(proc)
                raise SceneDetectorError(
                    CODE_CANCELLED,
                    "scene detection cancelled during ffmpeg",
                    location="phase:detect",
                )
            remaining = deadline - _monotonic()
            if remaining <= 0:
                _terminate_proc(proc)
                raise SceneDetectorError(
                    CODE_SCENE_DETECT_TIMEOUT,
                    f"ffmpeg exceeded the {profile.timeout_seconds}s bounded budget",
                    location="detect phase",
                    details={"timeout_seconds": profile.timeout_seconds},
                )
            try:
                _out, err = proc.communicate(timeout=min(0.5, max(0.01, remaining)))
                stderr_tail = (err or "")[-2000:]
                break
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        _terminate_proc(proc)
        raise
    if proc.returncode != 0:
        raise SceneDetectorError(
            CODE_SCENE_DETECT_FAILED,
            f"ffmpeg exited {proc.returncode}",
            location="detect phase",
            details={"returncode": proc.returncode, "stderr_tail": stderr_tail},
        )

    cut_frames: list[int] = []
    for pts_text in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr_tail):
        try:
            pts = Fraction(pts_text)
        except (ValueError, ZeroDivisionError):
            continue
        cut_frames.append(timebase.time_to_frame(pts, rounding="round_half_up"))
    return sorted(set(cut_frames))


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


def _scene_evidence(row: Scene) -> dict[str, Any]:
    """The durable evidence of a committed scene row (for equality checks)."""
    return {
        "position": row.position,
        "start_frame": row.start_frame,
        "end_frame": row.end_frame,
        "start_time_ms": row.start_time_ms,
        "end_time_ms": row.end_time_ms,
        "status": row.status,
    }


def _publish_phase(
    ctx: WorkerContext,
    cp: dict[str, Any],
    input_ev: dict[str, Any],
    det_ev: dict[str, Any],
) -> dict[str, Any]:
    """Publish phase: commit the scene rows in ONE transaction.

    Idempotent replay: a committed ``published`` checkpoint is verified
    row-by-row and skipped; the crash-window (rows committed, published
    checkpoint not yet written) is closed by reusing rows whose evidence
    exactly matches the detection spec.  Rows that exist but do not match
    (legacy data, a different generation) fail closed with
    ``SCENE_EVIDENCE_CONFLICT`` — never overwritten, never deleted.
    """
    del input_ev  # input already checkpointed; publish owns the rows
    published = cp.get("published")
    if isinstance(published, dict) and published.get("schema_version") == SCENE_SCHEMA_VERSION:
        _verify_published_rows(ctx, published)
        return published
    _raise_if_cancelled(ctx, "publish")

    rows = _commit_scene_rows(ctx, det_ev)
    published = {"schema_version": SCENE_SCHEMA_VERSION, "scenes": rows}
    ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
    return published


def _verify_published_rows(ctx: WorkerContext, published: dict[str, Any]) -> None:
    """Verify every row recorded in the published checkpoint still matches."""
    if ctx.session_factory is None:
        raise SceneDetectorError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot verify scene rows",
            location="scene (publish step)",
        )
    video_item_id = str(ctx.input_manifest["video_item_id"])
    recorded = published.get("scenes")
    if not isinstance(recorded, list):
        raise SceneDetectorError(
            CODE_SCENE_EVIDENCE_CONFLICT,
            "published checkpoint has no scene list",
            location="checkpoint",
        )
    with ctx.session_factory() as session:
        for entry in recorded:
            row = session.get(Scene, str(entry["scene_id"]))
            if row is None or row.video_item_id != video_item_id:
                raise SceneDetectorError(
                    CODE_SCENE_EVIDENCE_CONFLICT,
                    f"committed scene {entry['scene_id']!r} is missing or "
                    f"belongs to another video item",
                    location="scene (publish step)",
                    details={"scene_id": entry.get("scene_id")},
                )
            expected = {
                "position": entry["position"],
                "start_frame": entry["start_frame"],
                "end_frame": entry["end_frame"],
                "start_time_ms": entry["start_time_ms"],
                "end_time_ms": entry["end_time_ms"],
                "status": entry["status"],
            }
            if _scene_evidence(row) != expected:
                raise SceneDetectorError(
                    CODE_SCENE_EVIDENCE_CONFLICT,
                    f"committed scene {row.id!r} evidence changed after publication",
                    location="scene (publish step)",
                    details={"scene_id": row.id, "row": _scene_evidence(row), "expected": expected},
                )


def _commit_scene_rows(ctx: WorkerContext, det_ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert/reuse the scene rows for the detection spec in one transaction.

    Returns the committed rows (position, scene_id, evidence) sorted by
    position, for the published checkpoint.  Rows already present with
    exactly matching evidence are reused untouched (no revision churn); any
    row that does not match the spec raises ``SCENE_EVIDENCE_CONFLICT``.
    """
    if ctx.session_factory is None:
        raise SceneDetectorError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot commit scene rows",
            location="scene (publish step)",
        )
    video_item_id = str(ctx.input_manifest["video_item_id"])
    specs = det_ev.get("scenes")
    if not isinstance(specs, list):
        raise SceneDetectorError(
            CODE_SCENE_EVIDENCE_CONFLICT,
            "detection checkpoint has no scene spec list",
            location="detect phase",
        )

    with ctx.session_factory() as session:
        existing = {
            row.position: row
            for row in session.scalars(
                select(Scene).where(Scene.video_item_id == video_item_id)
            ).all()
        }
        spec_by_pos = {int(spec["position"]): spec for spec in specs}
        for position, row in existing.items():
            if position not in spec_by_pos:
                raise SceneDetectorError(
                    CODE_SCENE_EVIDENCE_CONFLICT,
                    f"scene row at position {position} exists but the detection "
                    f"spec has no such position (rows from another source)",
                    location="scene (publish step)",
                    details={"position": position, "scene_id": row.id},
                )
            if _scene_evidence(row) != spec_by_pos[position]:
                raise SceneDetectorError(
                    CODE_SCENE_EVIDENCE_CONFLICT,
                    f"scene row at position {position} does not match the "
                    f"detection evidence (rows from another source)",
                    location="scene (publish step)",
                    details={
                        "position": position,
                        "scene_id": row.id,
                        "row": _scene_evidence(row),
                        "expected": spec_by_pos[position],
                    },
                )

        committed: list[dict[str, Any]] = []
        for spec in specs:
            position = int(spec["position"])
            existing_row = existing.get(position)
            if existing_row is not None:
                committed.append(
                    {
                        "position": position,
                        "scene_id": existing_row.id,
                        **_scene_evidence(existing_row),
                    }
                )
                continue
            scene_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"scene-detect:{ctx.job_id}:{position}"))
            session.add(
                Scene(
                    id=scene_id,
                    video_item_id=video_item_id,
                    legacy_scene_id=None,
                    position=position,
                    start_frame=int(spec["start_frame"]),
                    end_frame=int(spec["end_frame"]),
                    start_time_ms=int(spec["start_time_ms"]),
                    end_time_ms=int(spec["end_time_ms"]),
                    status=str(spec["status"]),
                )
            )
            committed.append(
                {
                    "position": position,
                    "scene_id": scene_id,
                    "start_frame": int(spec["start_frame"]),
                    "end_frame": int(spec["end_frame"]),
                    "start_time_ms": int(spec["start_time_ms"]),
                    "end_time_ms": int(spec["end_time_ms"]),
                    "status": str(spec["status"]),
                }
            )
        session.commit()
        committed.sort(key=lambda entry: int(entry["position"]))
        return committed


# ── Submit (contract §8.1 idempotency, owner-scoped) ─────────────────────────


def _idempotency_key(video_item_id: str, source_sha256: str, generation: str) -> str:
    """Owner-scoped scene-detection idempotency key.

    The logical identity is scoped to the VideoItem owner, the source content
    (the managed source artifact's SHA-256) and the operation discriminator
    ``scene_detect`` — the import key namespace (``ANALYZE_MEDIA:video_item:``)
    is never collided with:::

        ANALYZE_MEDIA:scene_detect:video_item:<video_item_id>:<source_sha256>:<generation>

    The proxy choice does not change the logical identity (scenes describe the
    VideoItem's canonical timeline, not a specific proxy).  ``generation``
    distinguishes explicit re-detections of the same owner+source.
    """
    return (
        f"{JOB_TYPE_ANALYZE_MEDIA}:scene_detect:video_item:{video_item_id}:"
        f"{source_sha256}:{generation}"
    )


def submit_scene_detection(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    source_artifact_id: str,
    proxy_artifact_id: str | None = None,
    generation: str = "1",
    managed_root: str | Path | None = None,
    title: str | None = None,
    profile: SceneDetectionProfile | None = None,
) -> SceneDetectionSubmitResult:
    """Create the durable scene-detection Job for one VideoItem.

    The job class is the approved ``ANALYZE_MEDIA`` (DURABLE_JOB_CONTRACT §3);
    the step code is ``scene_detect``.  The idempotency key is owner-scoped
    and embeds the source content identity; a completed duplicate returns the
    existing Job (``reused=True``), an active duplicate raises
    ``IdempotencyKeyInUse`` — exactly one effect set per logical detection.

    Ownership and the source artifact chain are validated **before any
    managed write**; when *proxy_artifact_id* is supplied it is validated at
    submit (fail fast) and re-validated at run time (with a fallback to the
    managed source when the proxy is no longer usable).

    The request path never runs FFmpeg — detection runs in the durable worker.

    Raises:
        SceneDetectorError: ``VIDEO_ITEM_NOT_FOUND`` / ``PROJECT_NOT_FOUND``
            / ``OWNERSHIP_MISMATCH`` / ``SOURCE_ARTIFACT_NOT_FOUND`` /
            ``SOURCE_NOT_READY`` / ``SOURCE_OWNER_MISMATCH`` /
            ``PROXY_ARTIFACT_NOT_FOUND`` / ``PROXY_NOT_READY`` /
            ``PROXY_OWNER_MISMATCH`` / ``SCENE_PROFILE_INVALID``.
        ValueError: for empty ids.
        IdempotencyKeyInUse: an active Job already exists for the key.
    """
    if not workspace_id or not project_id or not video_item_id or not source_artifact_id:
        raise ValueError(
            "workspace_id, project_id, video_item_id and source_artifact_id are required"
        )
    profile = profile or SceneDetectionProfile()

    with session_factory() as session:
        from app.persistence.jobs import JobRepository
        from app.persistence.models import Job as JobORM

        video_import._validate_ownership(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        source = video_proxy._validate_source_artifact(
            session,
            workspace_id=workspace_id,
            video_item_id=video_item_id,
            source_artifact_id=source_artifact_id,
        )
        proxy: Artifact | None = None
        if proxy_artifact_id:
            proxy = _validate_proxy_artifact(
                session,
                workspace_id=workspace_id,
                video_item_id=video_item_id,
                proxy_artifact_id=proxy_artifact_id,
            )
        source_sha256 = source.sha256 or ""

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "source_artifact_id": source_artifact_id,
            "source_sha256": source_sha256,
            "source_relative_path": source.relative_path,
            "generation": generation,
            "title": title or "scene_detect",
            "scene_detection_profile": profile.to_json(),
        }
        if proxy is not None:
            manifest["proxy_artifact_id"] = proxy.id
            manifest["proxy_sha256"] = proxy.sha256 or ""
            manifest["proxy_relative_path"] = proxy.relative_path
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
            job_type=JOB_TYPE_ANALYZE_MEDIA,
            owner_type="video_item",
            owner_id=video_item_id,
            input_manifest=manifest,
            idempotency_key=idempotency_key,
            input_generation=generation,
            steps=scene_detection_steps(),
            actor="api",
        )
        session.commit()
        return SceneDetectionSubmitResult(job_id=job.id, reused=completed_exists is not None)


def scene_detection_steps() -> list[StepInput]:
    """The scene-detection step plan (one sync step)."""
    return [StepInput(step_code=SCENE_DETECT_STEP_CODE, position=0, step_type="sync")]


def register_scene_detection_handler(worker: Any) -> None:
    """Register the ANALYZE_MEDIA dispatcher on a DurableWorker instance.

    One registered handler per job class (the worker dispatches by
    ``job_type``): ``import`` steps run the approved S05-T02
    ``analyze_media_handler`` (unchanged behavior), ``scene_detect`` steps run
    this module's handler.  No declared final outputs: the completion gate is
    the scene-row publication transaction itself (mirroring ANALYZE_MEDIA).
    """

    def _analyze_media_dispatcher(ctx: WorkerContext) -> dict[str, Any]:
        if ctx.step_code == video_import.COPY_STEP_CODE:
            return video_import.analyze_media_handler(ctx)
        if ctx.step_code == SCENE_DETECT_STEP_CODE:
            return scene_detection_handler(ctx)
        raise SceneDetectorError(
            CODE_UNKNOWN_ANALYZE_STEP,
            f"unknown ANALYZE_MEDIA step {ctx.step_code!r}",
            location="step",
            details={"step_code": ctx.step_code},
        )

    worker.register_handler(JOB_TYPE_ANALYZE_MEDIA, _analyze_media_dispatcher)
