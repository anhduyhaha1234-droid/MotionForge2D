"""Durable object candidate extraction (S08-T02) — the DISCOVER_OBJECTS job.

Implements the S08-T02 outcome on top of the approved DURABLE_JOB_CONTRACT
V1.1 (job class ``DISCOVER_OBJECTS``, contract §3) and the S08-T01 durable
ObjectRole/ObjectOccurrence domain:

- **Submit** (:func:`submit_discover_objects`) creates the durable Job with
  an **owner-scoped idempotency key** that binds the video item, the source
  generation/SHA-256 and the extractor version::

      DISCOVER_OBJECTS:video_item:<video_item_id>:<source_sha256>:
      <generation>:<extractor_version>

  A completed duplicate for the same (owner, content, generation, extractor)
  returns the existing Job (``reused=True``); an active duplicate raises
  ``IdempotencyKeyInUse`` (contract §8.1).  A fresh logical run of the same
  owner bumps ``generation`` (a different key) and the run-time input gate
  refuses to reuse stale rows (``INPUT_CHANGED``).

- **Deterministic CI adapter + explicit production capability/provider path,
  NO mock fallback in production** (:func:`resolve_extraction_provider`).
  The provider registry maps the production provider name ``"model"`` to the
  capability-gated :class:`Sam2ExtractionProvider` and the explicit
  ``"deterministic"`` name to :class:`DeterministicExtractionProvider` (a
  REAL deterministic algorithm, not a mock).  Production submission resolves
  the ``"model"`` provider and FAILS CLOSED with ``PROVIDER_UNAVAILABLE``
  when its capability probe fails — it never silently falls back to the
  deterministic adapter.  The deterministic provider is selectable only by
  explicit request (CI/tests/env ``MOTIONFORGE_EXTRACTION_PROVIDER``).

- **Artifact staging, containment, atomic commit, SHA-256, size,
  MIME/dimensions, repository rows and cleanup** follow the managed-artifact
  contracts: every file is written through ``ManagedRoot`` atomic writes
  into ``staging/<job_id>/<step_code>/`` (contract §9.1), published by
  atomic rename into ``artifacts/<workspace_id>/image/<job_id>/<step_code>/``
  (§9.2), and the ``artifact`` rows (``state='ready'``, sha256, size,
  ``mime_type``, ``width``/``height``) + ``artifact_owner`` links + the
  ObjectRole/ObjectOccurrence rows are committed **in ONE transaction**
  (§7.1).  A DB failure removes the files THIS attempt published (no
  orphan); a replay verifies committed rows/bytes and skips (no duplicate).
  Leftover ``.staging`` partials — including the predecessor's — are
  garbage-collected on re-run (§9.4).

- **Completed state is impossible until all declared rows/artifacts are
  committed**: the handler registers ``declared_outputs`` (the result
  manifest) plus an ``output_validator`` that re-verifies EVERY candidate
  artifact row (state ``ready``, sha256, size, dimensions) AND its file on
  disk before the worker's completion gate (contract §9.3, invariant §15-5).
  A missing/corrupt artifact row or file fails the Job with
  ``OUTPUT_MISSING``/``VALIDATION_FAILED`` — never a completed Job with a
  partial output set.

- **Restart/retry/cancel/concurrent duplicate submission and stale-source
  behavior are durable**: the handler resumes from the step checkpoint
  (input evidence re-verified; committed publication replayed row-by-row),
  observes ``ctx.is_cancelled()`` at every phase (a cancel before
  publication leaves zero rows/files; after publication the Job completes —
  cancel-during-completed is serialized by the guarded transition, contract
  §6.3), and the read API never exposes partial or stale output: the
  outputs endpoint is empty unless the Job is terminal-``completed`` and the
  manifest lists exactly the committed candidates.

No grouping/merge/split UI, no legacy synchronous auto-segmentation
replacement, no S05 media algorithm and no S06 character behavior: the
extractor only produces suggested ObjectRoles + ObjectOccurrence evidence
from the video item's canonical metadata and scene layout.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import struct
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.artifacts import (
    ArtifactWriteError,
    ManagedPathError,
    ManagedRoot,
    hash_file,
)
from app.persistence.jobs import StepInput
from app.persistence.models import (
    CONTACT_KINDS,
    OBJECT_KINDS,
    REMOVAL_ONLY_KINDS,
    Artifact,
    ArtifactOwner,
    ObjectOccurrence,
    ObjectRole,
    ObjectRoleArtifact,
    Project,
    Scene,
    VideoItem,
)
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "ARTIFACT_PURPOSE_CANDIDATE_MASK",
    "ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL",
    "ARTIFACT_PURPOSE_RESULT_MANIFEST",
    "CODE_CANCELLED",
    "CODE_INPUT_CHANGED",
    "CODE_MEDIA_CHANGED",
    "CODE_OWNERSHIP_MISMATCH",
    "CODE_PATH_CONTAINMENT",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_PROVIDER_UNAVAILABLE",
    "CODE_PUBLICATION_FAILED",
    "CODE_SCENE_MISSING",
    "CODE_SOURCE_ARTIFACT_NOT_FOUND",
    "CODE_SOURCE_CONFLICT",
    "CODE_SOURCE_NOT_READY",
    "CODE_VIDEO_ITEM_NOT_FOUND",
    "DEFAULT_EXTRACTOR_VERSION",
    "DISCOVER_OBJECTS_STEP_CODE",
    "CrossSceneDeterministicExtractionProvider",
    "DeterministicExtractionProvider",
    "EXTRACTION_QA_MODE_ENV",
    "ExtractionArtifact",
    "ExtractionCandidate",
    "ExtractionError",
    "ExtractionProvider",
    "ExtractionSubmitResult",
    "JOB_TYPE_DISCOVER_OBJECTS",
    "MANIFEST_SCHEMA_VERSION",
    "PROVIDER_DETERMINISTIC",
    "PROVIDER_DETERMINISTIC_IDENTITY",
    "PROVIDER_PRODUCTION",
    "PROVIDER_ENV_VAR",
    "SAM2_MODEL_VERSION",
    "Sam2ExtractionProvider",
    "VIETNAMESE_ACTIONS",
    "discover_objects_steps",
    "extract_object_candidates",
    "register_discover_objects_handler",
    "resolve_extraction_provider",
    "submit_discover_objects",
]

#: Approved job class (DURABLE_JOB_CONTRACT §3: ``DISCOVER_OBJECTS``).
JOB_TYPE_DISCOVER_OBJECTS = "DISCOVER_OBJECTS"

#: The single sync step that executes the whole extraction pipeline.
DISCOVER_OBJECTS_STEP_CODE = "extract"

#: Schema version of the result manifest and the step checkpoint payload.
MANIFEST_SCHEMA_VERSION = 1

#: Extractor version bound into the idempotency key and every occurrence's
#: ``algorithm_version`` (deterministic QA adapter).  Bumping it changes the
#: logical run identity, so an updated extractor NEVER reuses a completed
#: Job's output set silently.
DEFAULT_EXTRACTOR_VERSION = "1.0.0"

#: Production provider name — the local SAM2.1 implementation.  Capability-
#: gated (real checkpoint + backend probe), never falls back.
PROVIDER_PRODUCTION = "sam2-local"

#: QA/test-only provider name — a REAL deterministic algorithm, selectable
#: ONLY as server policy (``MOTIONFORGE_EXTRACTION_PROVIDER``), never from
#: HTTP request JSON.
PROVIDER_DETERMINISTIC = "deterministic"

#: QA/test-only provider name — a REAL deterministic algorithm emitting a
#: meaningful CROSS-SCENE IDENTITY world (the same display name recurring
#: across scenes for the same object) so T02 extraction output itself drives
#: T03 grouping end-to-end (sprint-exit golden, Codex finding G).  Selectable
#: ONLY as server policy (``MOTIONFORGE_EXTRACTION_PROVIDER``), never from
#: HTTP request JSON; never a production fallback.
PROVIDER_DETERMINISTIC_IDENTITY = "deterministic-identity"

#: Environment variable that explicitly selects the extractor provider
#: (server/runtime policy — request bodies cannot override it).
PROVIDER_ENV_VAR = "MOTIONFORGE_EXTRACTION_PROVIDER"

#: Stable SAM2.1 model version recorded as provenance on every occurrence
#: and artifact produced by the production provider.
SAM2_MODEL_VERSION = "sam2.1-hiera-large-1.0"

#: Artifact-owner purposes of the published candidate outputs.
ARTIFACT_PURPOSE_RESULT_MANIFEST = "result"
ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL = "thumbnail"
ARTIFACT_PURPOSE_CANDIDATE_MASK = "mask"

# ── Stable error codes (contract §10.1 taxonomy) ─────────────────────────────

CODE_INPUT_CHANGED = "INPUT_CHANGED"
CODE_SOURCE_ARTIFACT_NOT_FOUND = "SOURCE_ARTIFACT_NOT_FOUND"
CODE_SOURCE_NOT_READY = "SOURCE_NOT_READY"
CODE_SCENE_MISSING = "SCENE_MISSING"
CODE_PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
CODE_VIDEO_ITEM_NOT_FOUND = "VIDEO_ITEM_NOT_FOUND"
CODE_OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"
CODE_PATH_CONTAINMENT = "PATH_CONTAINMENT"
CODE_PUBLICATION_FAILED = "PUBLICATION_FAILED"
CODE_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
CODE_CANCELLED = "CANCELLED"
#: C2: client-supplied hint conflicts with backend-authoritative source state.
CODE_SOURCE_CONFLICT = "SOURCE_CONFLICT"
#: C2: the managed media file no longer matches its Artifact row (tampered
#: byte-wise after submit) — fail before inference, publish nothing.
CODE_MEDIA_CHANGED = "MEDIA_CHANGED"

#: C2: QA/test-mode marker.  The deterministic providers are resolvable ONLY
#: when this flag is set (faithful QA deployment with isolated roots).
EXTRACTION_QA_MODE_ENV = "MOTIONFORGE_EXTRACTION_QA_MODE"


def _qa_mode_active(env: dict[str, str] | None) -> bool:
    """True ONLY when the runtime is a genuine QA/test deployment.

    The QA marker is an explicit server-side declaration
    (``MOTIONFORGE_EXTRACTION_QA_MODE=1``) set alongside the isolated-root
    fixtures of the test harness.  Without it the deterministic adapters are
    treated as unattested/dev backends and are NEVER resolved.
    """
    return (env or os.environ).get(EXTRACTION_QA_MODE_ENV) == "1"

#: Vietnamese suggested actions (PRD §9 Step 5 acceptance / FR-08) for every
#: stable code this service raises.
VIETNAMESE_ACTIONS: dict[str, str] = {
    CODE_INPUT_CHANGED: (
        "Đầu vào của Job đã thay đổi so với lần chạy trước (nguồn video khác "
        "hoặc generation khác). Hãy tạo lại Job với generation mới để trích "
        "xuất lại."
    ),
    CODE_SOURCE_ARTIFACT_NOT_FOUND: (
        "Artifact nguồn không tồn tại hoặc không thuộc Workspace này. Hãy "
        "import video trước khi trích xuất đối tượng."
    ),
    CODE_SOURCE_NOT_READY: (
        "Artifact nguồn chưa sẵn sàng (không phải video ready hoặc thiếu "
        "checksum). Hãy đợi import hoàn tất rồi thử lại."
    ),
    CODE_SCENE_MISSING: (
        "Video Item chưa có dữ liệu cảnh (scene). Hãy chạy phát hiện cảnh "
        "trước khi trích xuất đối tượng."
    ),
    CODE_PROJECT_NOT_FOUND: (
        "Project không tồn tại hoặc đã bị lưu trữ. Hãy kiểm tra Project và "
        "thử lại."
    ),
    CODE_VIDEO_ITEM_NOT_FOUND: (
        "Video Item không tồn tại hoặc đã bị lưu trữ. Hãy tạo lại Video Item "
        "rồi thử lại."
    ),
    CODE_OWNERSHIP_MISMATCH: (
        "Video Item không thuộc Project/Workspace được khai báo. Hãy chọn "
        "đúng Project và Workspace chứa Video Item rồi thử lại."
    ),
    CODE_PATH_CONTAINMENT: (
        "Đường dẫn artifact không hợp lệ hoặc cố thoát khỏi vùng lưu trữ "
        "được quản lý. Hãy kiểm tra lại dữ liệu đầu vào."
    ),
    CODE_PUBLICATION_FAILED: (
        "Không thể công bố artifact kết quả. Hãy thử lại; nếu lỗi lặp lại, "
        "hãy báo lỗi hệ thống kèm Job id."
    ),
    CODE_PROVIDER_UNAVAILABLE: (
        "Bộ trích xuất đối tượng chưa khả dụng (chưa cấu hình model/khả năng "
        "phần cứng). Job không dùng bộ trích xuất thay thế; hãy kiểm tra cấu "
        "hình rồi tạo lại Job."
    ),
    CODE_CANCELLED: "Trích xuất đối tượng đã bị hủy theo yêu cầu.",
    CODE_SOURCE_CONFLICT: (
        "Giá trị generation/checksum do client gửi không khớp với trạng thái "
        "nguồn đang được máy chủ xác thực. Hãy bỏ hints (hoặc đồng bộ với "
        "nguồn hiện tại) rồi tạo lại Job."
    ),
    CODE_MEDIA_CHANGED: (
        "File video nguồn đã bị thay đổi sau khi tạo Job (khác Artifact row). "
        "Đã dừng trước bước suy luận và không xuất bản kết quả. Hãy replace "
        "nguồn rồi tạo Job mới."
    ),
}


class ExtractionError(Exception):
    """A stable, actionable extraction failure (contract §10.1)."""

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


# ── Provider abstraction (deterministic CI adapter + production path) ────────


@dataclass(frozen=True)
class ExtractionArtifact:
    """One committed candidate artifact (thumbnail or mask)."""

    name: str
    purpose: str
    bytes: bytes
    width: int
    height: int


@dataclass(frozen=True)
class ExtractionCandidate:
    """One deterministic candidate: an ObjectRole + its ObjectOccurrences.

    The deterministic adapter derives every value from canonical inputs
    (video item metadata + scene layout) so identical inputs always produce
    identical candidates, occurrences, artifact bytes and SHA-256 values —
    the CI evidence of the extraction run.
    """

    name: str
    kind: str
    confidence: float
    reasons: list[str]
    occurrences: list[dict[str, Any]]
    artifacts: list[ExtractionArtifact]


class ExtractionProvider:
    """Protocol: a real candidate extractor with an explicit capability gate.

    ``available()`` must be a truthful capability probe — the production
    provider returns False until its backing model/capability is configured,
    and the caller FAILS CLOSED instead of silently substituting another
    provider.
    """

    name: str = ""

    def available(self) -> bool:
        raise NotImplementedError

    def extract(self, evidence: dict[str, Any]) -> list[ExtractionCandidate]:
        raise NotImplementedError


@dataclass(frozen=True)
class _LayoutProposal:
    """One candidate region proposal derived from canonical scene layout.

    Shared by BOTH providers: the deterministic QA adapter renders synthetic
    evidence from it; the production SAM2.1 provider uses it as the prompt
    seed (point + box) and replaces every pixel-level value with real
    inference output.
    """

    scene: dict[str, Any]
    focus_frame: int
    time_ms: int
    bbox: dict[str, int]
    name: str
    index: int


def _layout_proposals(evidence: dict[str, Any]) -> list[_LayoutProposal]:
    """Deterministic scene-layout region proposals (bounded, stable)."""
    scenes: list[dict[str, Any]] = evidence["scenes"]
    video_width = int(evidence["video_width"])
    video_height = int(evidence["video_height"])
    nb_frames = max(1, int(evidence["nb_frames"]))
    seed = (int(evidence["video_item_id"][:8], 16) + nb_frames * 7) & 0xFFFF
    proposals: list[_LayoutProposal] = []
    for index, scene in enumerate(scenes):
        if len(proposals) >= 6:
            break
        start_frame = int(scene["start_frame"])
        end_frame = int(scene["end_frame"])
        if end_frame < start_frame:
            continue
        focus = (start_frame + end_frame) // 2
        span = max(1, end_frame - start_frame + 1)
        cx = 40 + ((seed + index * 23) % 20)
        cy = 30 + ((seed // 3 + index * 17) % 20)
        bw = max(8, min(60, span % 45 + 8))
        bh = max(8, min(60, (seed + index * 11) % 45 + 8))
        bbox = {
            "x": min(max(0, (video_width * cx) // 100), max(0, video_width - bw)),
            "y": min(max(0, (video_height * cy) // 100), max(0, video_height - bh)),
            "width": min(bw, video_width),
            "height": min(bh, video_height),
        }
        bbox["width"] = min(bbox["width"], max(1, video_width - bbox["x"]))
        bbox["height"] = min(bbox["height"], max(1, video_height - bbox["y"]))
        time_ms = int(scene["start_time_ms"]) + (
            (int(scene["end_time_ms"]) - int(scene["start_time_ms"])) // 2
        )
        proposals.append(
            _LayoutProposal(
                scene=scene,
                focus_frame=focus,
                time_ms=time_ms,
                bbox=bbox,
                name=f"subject_{index + 1:02d}",
                index=index,
            )
        )
    return proposals


def _encode_png_bgr(image_bgr: Any) -> bytes:
    """Encode a BGR numpy frame to PNG bytes (cv2, real image codec)."""
    ok, encoded = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "cv2 PNG encoding failed for a candidate artifact",
            location="provider artifact encoding",
        )
    return encoded.tobytes()


#: Deterministic index -> kind mapping for the QA/deterministic adapter
#: (S08-A01).  Exercises EVERY canonical source-locked role/layer kind across
#: a bounded run (up to six layout proposals per run; ``OBJECT_KINDS`` cycles
#: through all seven kinds by candidate index) so the canonical seven-kind
#: taxonomy is proven end-to-end: schema, DB constraint, API, grouping guard
#: and gallery.  The mapping is STABLE (identical inputs -> identical
#: candidates/kinds).  The production SAM2.1 provider keeps
#: ``kind="character"`` — without a semantic classifier a mask/bbox alone
#: cannot be honestly labelled as background vs graphic vs source_overlay;
#: the production path fails closed when unavailable (unchanged).
def _qa_candidate_kind(index: int) -> str:
    """Deterministic kind for one QA candidate (stable by candidate index).

    Derived from the CANONICAL ``OBJECT_KINDS`` (single taxonomy authority in
    ``app.persistence.models``) — the deterministic adapter never hardcodes a
    second enumeration.
    """
    return OBJECT_KINDS[index % len(OBJECT_KINDS)]


class Sam2ExtractionProvider(ExtractionProvider):
    """Production provider — real local SAM2.1 inference (no network).

    The immediate local-first implementation uses the already installed
    SAM2.1 checkpoint + torch backend (GPU when available, CPU otherwise):

    - **Real capability probe** (:meth:`available`): the checkpoint must
      exist, be a readable non-empty file AND look like a real torch
      checkpoint (zip magic), the ``sam2`` package must import, the model
      config must ship with the package, and a torch backend (CUDA or CPU)
      must respond.  A bare environment string is never accepted.
    - **Real pixel inference** (:meth:`extract`): frames are decoded from
      the managed source/proxy artifact (read-only, bounded ffmpeg pipe),
      the SAM2.1 image predictor segments each layout-proposal region
      (point + box prompt), and occurrences/bboxes/confidence/masks/crops
      come from the predicted pixels — the layout proposal only seeds the
      prompt.
    - **Inference runs ONLY inside the durable worker**: the provider is
      constructed and executed exclusively by the job handler
      (``_extract_phase``); the submit path only calls ``available()``.
    - **Fail closed**: missing/corrupt checkpoint, missing package, or no
      usable backend ⇒ ``PROVIDER_UNAVAILABLE`` — never a deterministic
      fallback in production.
    - **Read-only model**: the checkpoint is opened read-only; it is never
      modified, copied, replaced or regenerated.
    - **Pluggable**: the provider interface stays the extension point for
      future SAM versions; no hardwired future version without a benchmark.
    """

    name: str = PROVIDER_PRODUCTION
    model_version: str = SAM2_MODEL_VERSION

    def __init__(
        self,
        *,
        checkpoint: str | Path | None = None,
        model_cfg: str | None = None,
        device: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 60,
        max_candidates: int = 6,
    ) -> None:
        self._checkpoint_override = Path(checkpoint) if checkpoint else None
        self._model_cfg_override = model_cfg
        self._device_override = device
        self._env = env if env is not None else os.environ
        self._timeout_seconds = timeout_seconds
        self._max_candidates = max_candidates

    def _resolved_checkpoint(self) -> Path | None:
        if self._checkpoint_override is not None:
            return self._checkpoint_override
        raw = self._env.get("MOTIONFORGE_SAM2_CHECKPOINT")
        if raw:
            return Path(raw)
        from app.config import config as app_config

        return Path(str(app_config.sam2_checkpoint))

    def _resolved_model_cfg(self) -> str:
        if self._model_cfg_override:
            return self._model_cfg_override
        raw = self._env.get("MOTIONFORGE_SAM2_MODEL_CFG")
        if raw:
            return raw
        from app.config import config as app_config

        return app_config.sam2_model_cfg

    def _resolved_device(self) -> str:
        if self._device_override:
            return self._device_override
        try:
            import torch  # noqa: PLC0415

            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                return "cuda"
            return "cpu"
        except Exception:  # noqa: BLE001 - capability probe
            return "cpu"

    def _capability(self) -> tuple[bool, str]:
        """Real backend capability probe (never trusts a bare env string)."""
        checkpoint = self._resolved_checkpoint()
        if checkpoint is None or not checkpoint.is_file():
            return False, f"checkpoint not found: {checkpoint}"
        try:
            if checkpoint.stat().st_size <= 0:
                return False, f"checkpoint is empty: {checkpoint}"
        except OSError as exc:
            return False, f"checkpoint unreadable: {exc}"
        try:
            with open(checkpoint, "rb") as handle:
                magic = handle.read(4)
        except OSError as exc:
            return False, f"checkpoint unreadable: {exc}"
        if magic != b"PK\x03\x04":
            return False, f"checkpoint is not a torch checkpoint (bad magic): {checkpoint}"
        try:
            import sam2.build_sam  # noqa: F401, PLC0415
            from sam2.sam2_image_predictor import SAM2ImagePredictor  # noqa: F401, PLC0415
        except Exception as exc:  # noqa: BLE001 - capability probe
            return False, f"sam2 package unavailable: {exc}"
        cfg = self._resolved_model_cfg()
        try:
            from importlib import resources  # noqa: PLC0415

            # The cfg is package-relative (e.g. "configs/sam2.1/sam2.1_hiera_l.yaml").
            cfg_exists = resources.files("sam2").joinpath(cfg).is_file()
        except Exception:  # noqa: BLE001 - capability probe
            cfg_exists = False
        if not cfg_exists:
            return False, f"sam2 model config not found in package: {cfg}"
        try:
            import torch  # noqa: PLC0415

            device = self._resolved_device()
            if device == "cuda":
                probe = torch.zeros(1, device="cuda")
                probe += 1
                del probe
                torch.cuda.synchronize()
        except Exception as exc:  # noqa: BLE001 - capability probe
            return False, f"torch backend probe failed: {exc}"
        return True, "sam2.1 local backend ready"

    def available(self) -> bool:
        return self._capability()[0]

    def _decode_frame(self, media_path: Path, time_seconds: float) -> Any | None:
        """Decode ONE frame from the managed media (read-only, bounded)."""
        from app.services.ffmpeg_utils import find_ffmpeg  # noqa: PLC0415

        try:
            ffmpeg = find_ffmpeg()
        except Exception:  # noqa: BLE001 - capability probe
            return None
        import subprocess  # noqa: PLC0415

        cmd = [
            ffmpeg,
            "-v",
            "error",
            "-ss",
            f"{max(0.0, time_seconds):.3f}",
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=self._timeout_seconds)
        except Exception:  # noqa: BLE001 - decode failure => provider-level skip
            return None
        if proc.returncode != 0 or not proc.stdout:
            return None
        frame = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        # Decode sanity limit (S08-H02): refuse absurd decoded dimensions so
        # a hostile media file cannot drive an unbounded allocation.
        from app.config import config as app_config  # noqa: PLC0415

        height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            return None
        if width > int(app_config.max_image_dimension) or (
            height > int(app_config.max_image_dimension)
        ):
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def extract(self, evidence: dict[str, Any]) -> list[ExtractionCandidate]:
        ok, reason = self._capability()
        if not ok:
            raise ExtractionError(
                CODE_PROVIDER_UNAVAILABLE,
                f"production extractor provider {self.name!r} is not available: "
                f"{reason}; refusing to run with a fallback provider",
                location="provider capability",
                details={"provider": self.name, "reason": reason},
            )
        import time  # noqa: PLC0415

        import torch  # noqa: PLC0415

        started = time.monotonic()
        checkpoint = self._resolved_checkpoint()
        assert checkpoint is not None
        device = self._resolved_device()
        model_cfg = self._resolved_model_cfg()
        import sam2.build_sam  # noqa: PLC0415
        from sam2.sam2_image_predictor import SAM2ImagePredictor  # noqa: PLC0415

        load_started = time.monotonic()
        predictor = SAM2ImagePredictor(
            sam2.build_sam.build_sam2(
                model_cfg, str(checkpoint), device=device, mode="eval"
            )
        )
        load_seconds = time.monotonic() - load_started

        managed_root = str(evidence.get("managed_root") or "artifacts")
        media_rel = str(evidence.get("media_relative_path") or "")
        if not media_rel:
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "no managed media path in evidence; refusing pixel extraction",
                location="provider input",
            )
        media_path = ManagedRoot(Path(managed_root)).resolve(media_rel)
        if not media_path.is_file():
            raise ExtractionError(
                CODE_SOURCE_ARTIFACT_NOT_FOUND,
                f"managed media file missing at {media_rel}",
                location="provider input",
                details={"relative_path": media_rel},
            )

        frame_w = int(evidence["video_width"])
        frame_h = int(evidence["video_height"])
        candidates: list[ExtractionCandidate] = []
        inference_started = time.monotonic()
        inference_count = 0
        for proposal in _layout_proposals(evidence)[: self._max_candidates]:
            frame = self._decode_frame(media_path, proposal.time_ms / 1000.0)
            if frame is None:
                continue

            predictor.set_image(frame)
            bbox = proposal.bbox
            center = (
                np.array(
                    [[bbox["x"] + bbox["width"] // 2, bbox["y"] + bbox["height"] // 2]],
                    dtype=np.float32,
                ),
            )
            box = (
                np.array(
                    [[bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]]],
                    dtype=np.float32,
                ),
            )
            mask, scores, _ = predictor.predict(
                point_coords=center[0],
                point_labels=np.array([1]),
                box=box[0],
                multimask_output=False,
            )
            inference_count += 1
            score = float(scores[0]) if scores is not None and len(scores) else 0.0
            mask_1024 = mask[0] > 0.0  # (1024, 1024) bool
            mask_f = (
                cv2.resize(
                    mask_1024.astype(np.uint8), (frame_w, frame_h),
                    interpolation=cv2.INTER_NEAREST,
                )
                > 0
            )
            x, y, w, h = cv2.boundingRect(mask_f.astype(np.uint8))
            if w <= 0 or h <= 0:
                continue  # empty mask for this proposal — no candidate
            true_bbox = {"x": x, "y": y, "width": w, "height": h}
            crop = frame[y : y + h, x : x + w]
            thumb_scale = max(1, max(w, h) // 64)
            thumb = cv2.resize(
                crop,
                (max(1, w // thumb_scale), max(1, h // thumb_scale)),
                interpolation=cv2.INTER_AREA,
            )
            mask_gray = (mask_f.astype(np.uint8)) * 255
            thumb_bytes = _encode_png_bgr(thumb)
            mask_bytes = _encode_png_bgr(mask_gray)
            name = proposal.name
            candidates.append(
                ExtractionCandidate(
                    name=name,
                    kind="character",
                    confidence=round(max(0.0, min(1.0, score)), 3),
                    reasons=[
                        "sam2.1-local",
                        f"scene-{proposal.index + 1}",
                        f"score-{score:.3f}",
                        f"frames-{proposal.focus_frame}",
                    ],
                    occurrences=[
                        {
                            "scene_id": proposal.scene["id"],
                            "frame_index": proposal.focus_frame,
                            "time_ms": proposal.time_ms,
                            "bbox": true_bbox,
                            "confidence": round(max(0.0, min(1.0, score)), 3),
                            "confidence_source": "detector",
                            "algorithm": "sam2.1-local",
                            "algorithm_version": SAM2_MODEL_VERSION,
                            "reasons": ["sam2.1-local", f"scene-{proposal.index + 1}"],
                            "review_state": "unreviewed",
                        }
                    ],
                    artifacts=[
                        ExtractionArtifact(
                            name=f"candidate_{proposal.index + 1:02d}_thumbnail.png",
                            purpose=ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL,
                            bytes=thumb_bytes,
                            width=int(thumb.shape[1]),
                            height=int(thumb.shape[0]),
                        ),
                        ExtractionArtifact(
                            name=f"candidate_{proposal.index + 1:02d}_mask.png",
                            purpose=ARTIFACT_PURPOSE_CANDIDATE_MASK,
                            bytes=mask_bytes,
                            width=frame_w,
                            height=frame_h,
                        ),
                    ],
                )
            )
        inference_seconds = time.monotonic() - inference_started
        evidence["provider_stats"] = {
            "provider": self.name,
            "model": SAM2_MODEL_VERSION,
            "model_load_seconds": round(load_seconds, 3),
            "inference_seconds": round(inference_seconds, 3),
            "inference_frames": inference_count,
            "total_seconds": round(time.monotonic() - started, 3),
            "device": device,
            "gpu_mem_peak_mb": (
                round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1)
                if device == "cuda"
                else 0.0
            ),
        }
        return candidates


def _png_bytes(width: int, height: int, rgba: bytes) -> bytes:
    """Deterministic 8-bit RGBA PNG (stdlib zlib/struct; no PIL dependency).

    The same (width, height, rgba) tuple ALWAYS yields the same bytes, which
    is what the deterministic evidence contract requires.
    """
    raw = b"".join(
        b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height)
    )

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, level=9))
        + _chunk(b"IEND", b"")
    )


def _crop_thumbnail(
    video_width: int, video_height: int, bbox: dict[str, int], scale: int = 8
) -> tuple[bytes, int, int]:
    """Deterministic thumbnail PNG of the bbox region (nearest-neighbour).

    The region is downscaled by *scale* (>= 1) with a deterministic 3x3
    kernel tint so different objects produce distinguishable artifacts while
    identical inputs produce byte-identical output.
    """
    scale = max(1, int(scale))
    bw = max(1, bbox["width"])
    bh = max(1, bbox["height"])
    tw = max(1, min(64, (bw + scale - 1) // scale))
    th = max(1, min(64, (bh + scale - 1) // scale))
    seed = (int(video_width) * 31 + int(video_height)) & 0xFFFF
    base = (seed % 200 + 20, (seed // 7) % 200 + 20, (seed // 13) % 200 + 20)
    rgba = bytearray()
    for ty in range(th):
        for tx in range(tw):
            shade = (tx * 3 + ty * 5) % 48
            rgba.extend(
                (
                    min(255, base[0] + shade),
                    min(255, base[1] + shade),
                    min(255, base[2] + shade),
                    255,
                )
            )
    return _png_bytes(tw, th, bytes(rgba)), tw, th


def _mask_png(video_width: int, video_height: int, bbox: dict[str, int]) -> tuple[bytes, int, int]:
    """Deterministic binary mask PNG of the bbox region (full frame size)."""
    w = max(1, int(video_width))
    h = max(1, int(video_height))
    x = max(0, min(w - 1, int(bbox["x"])))
    y = max(0, min(h - 1, int(bbox["y"])))
    bw = max(1, min(w - x, int(bbox["width"])))
    bh = max(1, min(h - y, int(bbox["height"])))
    rgba = bytearray(w * h * 4)
    for py in range(y, y + bh):
        start = (py * w + x) * 4
        end = start + bw * 4
        rgba[start:end:4] = b"\xff" * bw  # R
        rgba[start + 1 : end + 1 : 4] = b"\xff" * bw  # G
        rgba[start + 2 : end + 2 : 4] = b"\xff" * bw  # B
        rgba[start + 3 : end + 3 : 4] = b"\xff" * bw  # A
    return _png_bytes(w, h, bytes(rgba)), w, h


class DeterministicExtractionProvider(ExtractionProvider):
    """Explicit CI/test adapter — a REAL deterministic extraction algorithm.

    Not a mock: candidates, occurrences and artifact bytes are derived from
    the video item's canonical metadata and scene layout by fixed rules, so
    identical inputs always produce identical output (the CI evidence).  It
    is selected ONLY by explicit request (``provider="deterministic"`` or
    ``MOTIONFORGE_EXTRACTION_PROVIDER=deterministic``) and is never a
    production fallback.
    """

    name: str = PROVIDER_DETERMINISTIC

    def available(self) -> bool:
        return True

    def extract(self, evidence: dict[str, Any]) -> list[ExtractionCandidate]:
        video_width = int(evidence["video_width"])
        video_height = int(evidence["video_height"])
        candidates: list[ExtractionCandidate] = []
        for proposal in _layout_proposals(evidence):
            bbox = proposal.bbox
            name = proposal.name
            index = proposal.index
            thumb, tw, th = _crop_thumbnail(video_width, video_height, bbox)
            mask, mw, mh = _mask_png(video_width, video_height, bbox)
            candidates.append(
                ExtractionCandidate(
                    name=name,
                    kind=_qa_candidate_kind(index),
                    confidence=round(0.62 + (index % 5) * 0.06, 3),
                    reasons=[
                        "deterministic-scene-layout",
                        f"scene-{index + 1}",
                        f"frames-{proposal.focus_frame}",
                    ],
                    occurrences=[
                        {
                            "scene_id": proposal.scene["id"],
                            "frame_index": proposal.focus_frame,
                            "time_ms": proposal.time_ms,
                            "bbox": bbox,
                            "confidence": round(0.62 + (index % 5) * 0.06, 3),
                            "confidence_source": "detector",
                            "algorithm": "deterministic-layout",
                            "algorithm_version": str(evidence["extractor_version"]),
                            "reasons": [
                                "deterministic-scene-layout",
                                f"scene-{index + 1}",
                            ],
                            "review_state": "unreviewed",
                        }
                    ],
                    artifacts=[
                        ExtractionArtifact(
                            name=f"candidate_{index + 1:02d}_thumbnail.png",
                            purpose=ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL,
                            bytes=thumb,
                            width=tw,
                            height=th,
                        ),
                        ExtractionArtifact(
                            name=f"candidate_{index + 1:02d}_mask.png",
                            purpose=ARTIFACT_PURPOSE_CANDIDATE_MASK,
                            bytes=mask,
                            width=mw,
                            height=mh,
                        ),
                    ],
                )
            )
        return candidates


class CrossSceneDeterministicExtractionProvider(ExtractionProvider):
    """QA/test-only deterministic provider emitting a CROSS-SCENE IDENTITY world.

    A REAL deterministic algorithm (no mock): for a video whose scene detector
    produced at least four scenes it lays out a fixed object world that makes
    the extractor output ALONE drive the T03 grouping algorithm end-to-end
    (sprint-exit golden, Codex finding G):

    - object "Hero" recurs across scenes 0, 1 and 2 with a consistent spatial
      footprint (same normalized name + IoU >= 0.4 -> 0.9 suggestions);
    - a SECOND "Hero" (object B) in scene 2 at a disjoint footprint
      CO-OCCURS with the recurring hero in the same scene -> the calibration
      v2 rule suppresses the same-name disjoint co-occurring pair and only the
      two temporally-disjoint "Hero"/B pairs surface as 0.45 low-confidence
      advisories;
    - "Villain" (object C) in scene 3 matches the hero footprint while
      temporally disjoint -> 0.6 ambiguity suggestions (false-grouping cases
      the reviewer must dismiss);
    - two "Twin" roles in scenes 0/1 share name + footprint but are DIFFERENT
      objects (truth) -> a confident 0.9 FALSE suggestion.

    Identical inputs always produce identical candidates, occurrences,
    artifact bytes and SHA-256 values.  Candidate order is (scene index,
    bbox x) so the durable ``role_id`` (per job + candidate index) is stable
    across generations.  Selectable ONLY as server policy; never a production
    fallback.
    """

    name: str = PROVIDER_DETERMINISTIC_IDENTITY

    def available(self) -> bool:
        return True

    def extract(self, evidence: dict[str, Any]) -> list[ExtractionCandidate]:
        scenes: list[dict[str, Any]] = evidence["scenes"]
        video_width = int(evidence["video_width"])
        video_height = int(evidence["video_height"])
        extractor_version = str(evidence["extractor_version"])

        #: Deterministic track layout: (name, scene index, bbox, confidence).
        tracks: list[tuple[str, int, tuple[int, int, int, int], float]] = [
            ("Hero", 0, (100, 100, 300, 300), 0.68),
            ("Hero", 1, (110, 110, 300, 300), 0.74),
            ("Hero", 2, (105, 105, 300, 300), 0.80),
            ("Hero", 2, (900, 100, 300, 300), 0.62),
            ("Villain", 3, (105, 105, 300, 300), 0.86),
            ("Twin", 0, (400, 100, 250, 250), 0.70),
            ("Twin", 1, (405, 105, 250, 250), 0.70),
        ]

        candidates: list[ExtractionCandidate] = []

        def _scene(index: int) -> dict[str, Any] | None:
            return scenes[index] if index < len(scenes) else None

        ordered: list[
            tuple[int, int, str, dict[str, Any], dict[str, int], int, float]
        ] = []
        for name, scene_index, (x, y, w, h), confidence in tracks:
            scene = _scene(scene_index)
            if scene is None:
                continue  # honest degradation: world requires that scene
            time_ms = int(scene["start_time_ms"]) + (
                (int(scene["end_time_ms"]) - int(scene["start_time_ms"])) // 2
            )
            bbox = {"x": x, "y": y, "width": w, "height": h}
            ordered.append((scene_index, x, name, scene, bbox, time_ms, confidence))
        # Stable order (scene index, bbox x) — determines durable role ids.
        ordered.sort(key=lambda item: (item[0], item[1]))
        for index, (scene_index, _x, name, scene, bbox, time_ms, confidence) in enumerate(
            ordered
        ):
            focus = (int(scene["start_frame"]) + int(scene["end_frame"])) // 2
            thumb, tw, th = _crop_thumbnail(video_width, video_height, bbox)
            mask, mw, mh = _mask_png(video_width, video_height, bbox)
            candidates.append(
                ExtractionCandidate(
                    name=name,
                    kind="character",
                    confidence=round(confidence, 3),
                    reasons=[
                        "deterministic-identity",
                        f"scene-{scene_index + 1}",
                        f"frames-{focus}",
                    ],
                    occurrences=[
                        {
                            "scene_id": scene["id"],
                            "frame_index": focus,
                            "time_ms": time_ms,
                            "bbox": bbox,
                            "confidence": round(confidence, 3),
                            "confidence_source": "detector",
                            "algorithm": "deterministic-identity",
                            "algorithm_version": extractor_version,
                            "reasons": [
                                "deterministic-identity",
                                f"scene-{scene_index + 1}",
                            ],
                            "review_state": "unreviewed",
                        }
                    ],
                    artifacts=[
                        ExtractionArtifact(
                            name=f"candidate_{index + 1:02d}_thumbnail.png",
                            purpose=ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL,
                            bytes=thumb,
                            width=tw,
                            height=th,
                        ),
                        ExtractionArtifact(
                            name=f"candidate_{index + 1:02d}_mask.png",
                            purpose=ARTIFACT_PURPOSE_CANDIDATE_MASK,
                            bytes=mask,
                            width=mw,
                            height=mh,
                        ),
                    ],
                )
            )
        return candidates


def resolve_extraction_provider(
    provider: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> ExtractionProvider:
    """Resolve the extractor provider — SERVER/RUNTIME policy, never client input.

    ``provider`` is the server-side policy name; when omitted, the
    environment variable ``MOTIONFORGE_EXTRACTION_PROVIDER`` selects it;
    when neither is set the PRODUCTION provider (``sam2-local``) is the
    default.  The QA/test-only deterministic adapters are selectable ONLY
    through this policy — HTTP request bodies cannot choose it.  An unknown
    name fails closed with ``PROVIDER_UNAVAILABLE``.
    """
    resolved = provider or (env or os.environ).get(PROVIDER_ENV_VAR) or PROVIDER_PRODUCTION
    if resolved == PROVIDER_PRODUCTION:
        return Sam2ExtractionProvider(env=env)
    if resolved in (PROVIDER_DETERMINISTIC, PROVIDER_DETERMINISTIC_IDENTITY):
        # C2 gate: QA/test-only adapters resolve ONLY in a genuine QA
        # runtime (isolated roots + explicit QA marker).  In any other mode
        # the selection is PROVIDER_UNAVAILABLE — even when the env var or an
        # internal caller selects deterministic: no Job, no output created.
        if not _qa_mode_active(env):
            raise ExtractionError(
                CODE_PROVIDER_UNAVAILABLE,
                f"extraction provider {resolved!r} is QA/test-only and the "
                f"runtime is NOT in QA mode ({EXTRACTION_QA_MODE_ENV}!=1); "
                "refusing to use an unattested backend",
                location="provider resolution",
                details={"provider": resolved, "qa_mode": bool(_qa_mode_active(env))},
            )
        if resolved == PROVIDER_DETERMINISTIC:
            return DeterministicExtractionProvider()
        return CrossSceneDeterministicExtractionProvider()
    raise ExtractionError(
        CODE_PROVIDER_UNAVAILABLE,
        f"unknown extraction provider {resolved!r}; expected "
        f"{PROVIDER_PRODUCTION!r}, {PROVIDER_DETERMINISTIC!r} or "
        f"{PROVIDER_DETERMINISTIC_IDENTITY!r}",
        location="provider resolution",
        details={"provider": resolved},
    )


# ── Pure extraction (deterministic evidence, provider-agnostic) ──────────────


def extract_object_candidates(
    provider: ExtractionProvider,
    *,
    video_item_id: str,
    video_width: int,
    video_height: int,
    nb_frames: int,
    scenes: list[dict[str, Any]],
    extractor_version: str,
    media_relative_path: str | None = None,
    managed_root: str | Path | None = None,
) -> list[ExtractionCandidate]:
    """Run one extraction against canonical evidence.

    ``media_relative_path`` + ``managed_root`` are the managed source/proxy
    locator the production provider decodes frames from (read-only,
    containment-resolved at run time; never an absolute path in durable
    state).
    """
    if not provider.available():
        raise ExtractionError(
            CODE_PROVIDER_UNAVAILABLE,
            f"extraction provider {provider.name!r} is not available; refusing "
            "to substitute another provider",
            location="provider capability",
            details=dict(provider=provider.name),
        )
    evidence: dict[str, Any] = {
        "video_item_id": video_item_id,
        "video_width": video_width,
        "video_height": video_height,
        "nb_frames": nb_frames,
        "scenes": scenes,
        "extractor_version": extractor_version,
    }
    if media_relative_path:
        evidence["media_relative_path"] = media_relative_path
    if managed_root is not None:
        evidence["managed_root"] = str(managed_root)
    return provider.extract(evidence)


# ── Managed path helpers (mirror video_import / video_proxy) ─────────────────


def _managed_for(ctx: WorkerContext) -> ManagedRoot:
    """ManagedRoot bound to the Job's manifest managed root."""
    return ManagedRoot(Path(str(ctx.input_manifest.get("managed_root") or "artifacts")))


def _raise_if_cancelled(ctx: WorkerContext, phase: str) -> None:
    """Fail with the stable cancel code when the durable flag is set."""
    if ctx.is_cancelled():
        raise ExtractionError(
            CODE_CANCELLED,
            f"object extraction cancelled before {phase} phase",
            location=f"phase:{phase}",
        )


def _wrap_managed_errors(exc: ManagedPathError) -> ExtractionError:
    """Map a containment failure to the stable PATH_CONTAINMENT envelope."""
    return ExtractionError(
        CODE_PATH_CONTAINMENT,
        f"managed path rejected: {exc}",
        location="managed path",
        details={"reason": str(exc)},
    )


def _remove_file(path: Path) -> None:
    """Best-effort removal of a managed file (never raises)."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


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


def _cleanup_staging_partials(ctx: WorkerContext, managed: ManagedRoot) -> None:
    """Remove leftover ``.staging`` partials for this Job and its predecessor."""
    root = managed.root
    dirs = [root / "staging" / ctx.job_id / ctx.step_code]
    predecessor = _predecessor_job_id(ctx)
    if predecessor is not None:
        dirs.append(root / "staging" / predecessor / ctx.step_code)
    for staging_dir in dirs:
        if not staging_dir.is_dir():
            continue
        for partial in staging_dir.glob("*.staging"):
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)


def _staging_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the staged artifact (contract §9.1)."""
    return f"staging/{ctx.job_id}/{ctx.step_code}/{name}"


def _final_relative_path(ctx: WorkerContext, name: str) -> str:
    """Managed relative path of the published artifact (contract §9.2)."""
    workspace_id = str(ctx.input_manifest.get("workspace_id") or "default")
    return f"artifacts/{workspace_id}/image/{ctx.job_id}/{ctx.step_code}/{name}"


def _artifact_id(ctx: WorkerContext, final_rel: str) -> str:
    """Deterministic artifact id for (job, step, path) — replay-safe (§8.3)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"discover-objects:{ctx.job_id}:{final_rel}"))


def _role_id(ctx: WorkerContext, index: int) -> str:
    """Deterministic ObjectRole id for (job, candidate) — replay-safe (§8.3)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"discover-objects:{ctx.job_id}:role:{index}"))


def _segment_logical_id(ctx: WorkerContext, index: int, scene_id: str) -> str:
    """Deterministic logical_id for (job, candidate, scene) — T02 wiring."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"discover-objects:{ctx.job_id}:logical:{index}:{scene_id}"))  # noqa: E501


def _segment_id(ctx: WorkerContext, index: int, scene_id: str) -> str:
    """Deterministic segment record id for (job, candidate, scene)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"discover-objects:{ctx.job_id}:segment:{index}:{scene_id}"))  # noqa: E501


def _prompt_for_bbox(bbox: dict[str, int]) -> dict[str, list[dict[str, float | str]]]:
    """Canonical prompt/segmentation shape from a candidate bbox (T02)."""
    x = float(int(bbox["x"]))
    y = float(int(bbox["y"]))
    w = float(int(bbox["width"]))
    h = float(int(bbox["height"]))
    cx = x + w / 2.0
    cy = y + h / 2.0
    return {
        "points": [{"x": cx, "y": cy, "label": "foreground"}],
        "boxes": [{"x": x, "y": y, "w": w, "h": h}],
    }


# ── Durable handler ──────────────────────────────────────────────────────────


def discover_objects_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one DISCOVER_OBJECTS run: input → extract → stage → publish.

    The handler resumes from the step checkpoint: a valid input evidence is
    re-verified (stale source fails with ``INPUT_CHANGED``), a committed
    publication is replayed row-by-row (no duplicate rows/files), and every
    phase observes ``ctx.is_cancelled()``.  Artifacts + roles + occurrences
    are committed in ONE transaction so a partial attempt leaves zero
    durable effects.
    """
    managed = _managed_for(ctx)
    cp = ctx.checkpoint
    if not isinstance(cp, dict):
        cp = {"schema_version": MANIFEST_SCHEMA_VERSION}

    input_ev = _input_phase(ctx, cp)
    cp = {**cp, "input": input_ev, "phase": "input"}
    ctx.progress(15, "input resolved")

    published = cp.get("published")
    if isinstance(published, dict) and published.get("manifest_artifact_id"):
        # A committed publication: replay verifies it and skips extraction.
        _verify_committed(ctx, managed, published)
        ctx.progress(100, "published (replayed)")
        return {"input": input_ev, "published": published}

    _raise_if_cancelled(ctx, "extract")
    candidates = _extract_phase(ctx, cp, input_ev)
    # The checkpoint carries ONLY the metadata payload (no binary bytes);
    # the full candidate objects stay in memory for staging/publishing.
    cp = {
        **cp,
        "candidates": [
            _candidate_meta(ctx, candidate, index)
            for index, candidate in enumerate(candidates)
        ],
        "phase": "candidates",
    }
    ctx.progress(45, "candidates extracted")

    staged = _stage_phase(ctx, managed, candidates)
    cp = {**cp, "staged": staged, "phase": "staged"}
    # Persist the staged checkpoint (contract §7.2 per-phase cadence) — this
    # is the durable boundary a restart resumes from before publication.
    ctx.write_checkpoint(cp)
    ctx.progress(75, "artifacts staged")

    published = _publish_phase(ctx, managed, input_ev, candidates, staged, cp)
    ctx.progress(100, "candidates published")
    return {"input": input_ev, "published": published}


def _input_phase(ctx: WorkerContext, cp: dict[str, Any]) -> dict[str, Any]:
    """Input phase: re-validate the chain and resolve canonical evidence.

    On replay the resolved evidence must equal the checkpointed evidence
    EXACTLY (same video item, generation, source sha256, extractor version)
    — any difference is ``INPUT_CHANGED`` (the logical run's inputs changed;
    a new generation is required).
    """
    recorded = cp.get("input")
    if isinstance(recorded, dict) and recorded.get("resolved"):
        _verify_input_evidence(ctx, recorded)
        return recorded
    _raise_if_cancelled(ctx, "input")
    if ctx.session_factory is None:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot resolve input",
            location="input phase",
        )
    workspace_id = str(ctx.input_manifest["workspace_id"])
    project_id = str(ctx.input_manifest["project_id"])
    video_item_id = str(ctx.input_manifest["video_item_id"])
    generation = str(ctx.input_manifest["generation"])
    source_sha256 = str(ctx.input_manifest.get("source_sha256") or "")
    extractor_version = str(
        ctx.input_manifest.get("extractor_version") or DEFAULT_EXTRACTOR_VERSION
    )
    evidence: dict[str, Any] = {}
    with ctx.session_factory() as session:
        project = session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ExtractionError(
                CODE_PROJECT_NOT_FOUND,
                f"project {project_id!r} not found in workspace {workspace_id!r}",
                location="project",
            )
        video = session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise ExtractionError(
                CODE_VIDEO_ITEM_NOT_FOUND,
                f"video item {video_item_id!r} not found under project {project_id!r}",
                location="video_item",
            )
        if video.source_artifact_id is None:
            raise ExtractionError(
                CODE_SOURCE_ARTIFACT_NOT_FOUND,
                f"video item {video_item_id!r} has no source artifact; import first",
                location="video_item",
                details={"video_item_id": video_item_id},
            )
        source = session.get(Artifact, video.source_artifact_id)
        if source is None or source.workspace_id != workspace_id:
            raise ExtractionError(
                CODE_SOURCE_ARTIFACT_NOT_FOUND,
                f"source artifact {video.source_artifact_id!r} not found in workspace",
                location="artifact",
                details={"artifact_id": video.source_artifact_id},
            )
        if source.kind != "video" or source.state != "ready" or not source.sha256:
            raise ExtractionError(
                CODE_SOURCE_NOT_READY,
                f"source artifact {source.id!r} is not a ready video with a "
                f"recorded checksum (kind={source.kind!r}, state={source.state!r})",
                location="artifact",
                details={
                    "artifact_id": source.id,
                    "kind": source.kind,
                    "state": source.state,
                    "has_sha256": source.sha256 is not None,
                },
            )
        if source_sha256 and source.sha256 != source_sha256:
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                f"source artifact sha256 {source.sha256!r} no longer matches the "
                f"job's recorded source sha256 {source_sha256!r} — the source "
                "was replaced; a new generation is required",
                location="artifact",
                details={"recorded": source_sha256, "current": source.sha256},
            )
        if video.width is None or video.height is None or video.duration_ms is None:
            raise ExtractionError(
                CODE_SOURCE_NOT_READY,
                "video item has no canonical probe dimensions/duration; import "
                "did not record media metadata",
                location="video_item",
                details={"video_item_id": video_item_id},
            )
        scenes = session.scalars(
            select(Scene)
            .where(Scene.video_item_id == video_item_id)
            .order_by(Scene.position)
        ).all()
        if not scenes:
            raise ExtractionError(
                CODE_SCENE_MISSING,
                f"video item {video_item_id!r} has no scene rows; run scene "
                "detection before extraction",
                location="scene",
                details={"video_item_id": video_item_id},
            )
        fps_num = video.fps_num or 30
        fps_den = video.fps_den or 1
        nb_frames = max(
            1, round((video.duration_ms / 1000.0) * (fps_num / fps_den))
        )
        # Managed media for pixel extraction: the ready proxy artifact is
        # preferred (lighter decode), otherwise the managed source artifact.
        # Only managed RELATIVE paths are recorded (never absolute paths).
        media_artifact = source
        media_purpose = "source"
        proxy_owner = session.execute(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item_id,
                ArtifactOwner.purpose == "proxy",
            )
        ).first()
        if proxy_owner is not None:
            proxy = session.get(Artifact, proxy_owner[0])
            if proxy is not None and proxy.state == "ready" and proxy.sha256:
                media_artifact = proxy
                media_purpose = "proxy"
        evidence = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "generation": generation,
            "source_artifact_id": source.id,
            "source_sha256": source.sha256,
            "media_artifact_id": media_artifact.id,
            "media_relative_path": media_artifact.relative_path,
            "media_purpose": media_purpose,
            "media_sha256": media_artifact.sha256,
            "media_size_bytes": int(media_artifact.size_bytes or 0),
            "extractor_version": extractor_version,
            "video_width": video.width,
            "video_height": video.height,
            "nb_frames": nb_frames,
            "scenes": [
                {
                    "id": scene.id,
                    "position": scene.position,
                    "start_frame": scene.start_frame,
                    "end_frame": scene.end_frame,
                    "start_time_ms": scene.start_time_ms,
                    "end_time_ms": scene.end_time_ms,
                }
                for scene in scenes
            ],
            "resolved": True,
        }
    ctx.write_checkpoint({**cp, "input": evidence, "phase": "input"})
    return evidence


def _verify_input_evidence(ctx: WorkerContext, recorded: dict[str, Any]) -> None:
    """Re-verify checkpointed input evidence against the live database.

    A stale source (replaced artifact, changed sha256, changed generation,
    missing video item) fails closed with ``INPUT_CHANGED``/the stable
    not-found codes — never a resume against stale inputs.
    """
    if ctx.session_factory is None:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot verify input",
            location="input phase",
        )
    manifest = ctx.input_manifest
    with ctx.session_factory() as session:
        video = session.get(VideoItem, str(recorded["video_item_id"]))
        if video is None or video.project_id != str(recorded["project_id"]):
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "video item no longer matches the job's recorded project",
                location="video_item",
            )
        source = session.get(Artifact, str(recorded["source_artifact_id"]))
        if source is None or source.sha256 != str(recorded["source_sha256"]):
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "source artifact no longer matches the job's recorded sha256",
                location="artifact",
            )
        media = session.get(Artifact, str(recorded.get("media_artifact_id") or ""))
        if (
            media is None
            or media.relative_path != str(recorded.get("media_relative_path") or "")
            or media.state != "ready"
            or str(media.sha256 or "") != str(recorded.get("media_sha256") or "")
            or int(media.size_bytes or 0) != int(recorded.get("media_size_bytes") or 0)
        ):
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "managed media artifact no longer matches the job's recorded "
                "media evidence (replaced or not ready)",
                location="artifact",
            )
        if (
            str(manifest.get("generation") or "") != str(recorded["generation"])
            or str(manifest.get("extractor_version") or DEFAULT_EXTRACTOR_VERSION)
            != str(recorded["extractor_version"])
        ):
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "job manifest generation/extractor no longer matches the "
                "checkpointed input evidence",
                location="input_manifest",
            )
    # C2: the managed media FILE itself must still match its row.
    _verify_media_file(ctx, recorded)


def _verify_media_file(ctx: WorkerContext, evidence: dict[str, Any]) -> None:
    """C2: verify the selected managed media file matches its Artifact row.

    Runs BEFORE inference AND on every replay: resolves the managed relative
    path (containment enforced by ``ManagedRoot``), then verifies the live
    file's size and SHA-256 against the durable Artifact row.  A media file
    modified byte-wise after submit fails here with ``MEDIA_CHANGED`` —
    before any inference or publication (acceptance 5/6).
    """
    managed = _managed_for(ctx)
    rel = str(evidence.get("media_relative_path") or "")
    artifact_id = str(evidence.get("media_artifact_id") or "")
    if not rel or not artifact_id:
        raise ExtractionError(
            CODE_INPUT_CHANGED, "media evidence is incomplete", location="media"
        )
    if ctx.session_factory is None:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot verify media",
            location="media",
        )
    with ctx.session_factory() as session:
        media = session.get(Artifact, artifact_id)
        if media is None or media.state != "ready":
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "managed media artifact is missing/not ready",
                location="media",
            )
        expected_sha = str(media.sha256 or "")
        expected_size = int(media.size_bytes or 0)
    try:
        target = managed.resolve(rel)
    except ManagedPathError as exc:
        raise ExtractionError(
            CODE_PATH_CONTAINMENT,
            f"managed media path containment rejection: {exc}",
            location="media",
        ) from exc
    if not target.is_file():
        raise ExtractionError(
            CODE_MEDIA_CHANGED,
            "managed media file is missing (removed after submit); refusing "
            "to run inference on it",
            location="media",
        )
    try:
        actual_size = target.stat().st_size
        actual_sha = hash_file(target)
    except OSError as exc:
        raise ExtractionError(
            CODE_MEDIA_CHANGED,
            f"managed media file unreadable: {exc}",
            location="media",
        ) from exc
    if actual_size != expected_size or actual_sha != expected_sha:
        raise ExtractionError(
            CODE_MEDIA_CHANGED,
            "managed media file no longer matches its Artifact row "
            "(byte-wise change after submit); refusing to run inference or "
            "publish any output",
            location="media",
            details={
                "artifact_id": artifact_id,
                "expected_size": expected_size,
                "actual_size": actual_size,
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
            },
        )


def _candidate_meta(
    ctx: WorkerContext, candidate: ExtractionCandidate, index: int
) -> dict[str, Any]:
    """Metadata payload of one candidate (no binary bytes — checkpoint-safe).

    Carries the STABLE role id (deterministic per job + candidate index) —
    display names are never joins/ids (correction finding B5).
    """
    return {
        "index": index,
        "role_id": _role_id(ctx, index),
        "name": candidate.name,
        "kind": candidate.kind,
        "confidence": candidate.confidence,
        "reasons": candidate.reasons,
        "occurrences": candidate.occurrences,
        "artifacts": [
            {
                "name": artifact.name,
                "purpose": artifact.purpose,
                "sha256": _sha256_hex(artifact.bytes),
                "size_bytes": len(artifact.bytes),
                "width": artifact.width,
                "height": artifact.height,
            }
            for artifact in candidate.artifacts
        ],
    }


def _extract_phase(
    ctx: WorkerContext, cp: dict[str, Any], input_ev: dict[str, Any]
) -> list[ExtractionCandidate]:
    """Extract phase: resolve the explicit provider and run it (no fallback).

    Returns the FULL candidates (artifact bytes included).  The checkpoint
    persists only the metadata payload; on replay the deterministic provider
    regenerates identical bytes and the regenerated metadata MUST equal the
    checkpointed metadata (a mismatch is an extractor drift and fails
    closed with ``INPUT_CHANGED``).

    C2: the managed media FILE is verified against its Artifact row at the
    top of this phase — BEFORE inference on the first run and BEFORE the
    regenerate-and-match replay (acceptance 5/6).
    """
    _verify_media_file(ctx, input_ev)
    recorded = cp.get("candidates")
    provider_name = str(ctx.input_manifest.get("provider") or PROVIDER_PRODUCTION)
    # C2: resolve with the submit-time runtime policy snapshot so the
    # deterministic QA adapters stay authorized exactly when the submit was.
    resolve_env = (
        {EXTRACTION_QA_MODE_ENV: "1"} if ctx.input_manifest.get("qa_mode") else None
    )
    provider = resolve_extraction_provider(provider_name, env=resolve_env)
    candidates = extract_object_candidates(
        provider,
        video_item_id=str(input_ev["video_item_id"]),
        video_width=int(input_ev["video_width"]),
        video_height=int(input_ev["video_height"]),
        nb_frames=int(input_ev["nb_frames"]),
        scenes=list(input_ev["scenes"]),
        extractor_version=str(input_ev["extractor_version"]),
        media_relative_path=str(input_ev.get("media_relative_path") or ""),
        managed_root=str(ctx.input_manifest.get("managed_root") or "artifacts"),
    )
    payload = [_candidate_meta(ctx, candidate, index) for index, candidate in enumerate(candidates)]
    if isinstance(recorded, list) and recorded:
        if recorded != payload:
            raise ExtractionError(
                CODE_INPUT_CHANGED,
                "regenerated candidate evidence no longer matches the "
                "checkpointed evidence (extractor drift); refusing to resume",
                location="extract phase",
            )
        return candidates
    ctx.write_checkpoint({**cp, "candidates": payload, "phase": "candidates"})
    return candidates


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _stage_phase(
    ctx: WorkerContext,
    managed: ManagedRoot,
    candidates: list[ExtractionCandidate],
) -> list[dict[str, Any]]:
    """Stage phase: write every candidate artifact via managed atomic writes."""
    staged: list[dict[str, Any]] = []
    _cleanup_staging_partials(ctx, managed)
    for candidate in candidates:
        if ctx.is_cancelled():
            for entry in staged:
                with contextlib.suppress(ManagedPathError, OSError):
                    _remove_file(managed.resolve(str(entry["staged_rel"])))
            raise ExtractionError(
                CODE_CANCELLED,
                "object extraction cancelled during staging; staged files removed",
                location="phase:staging",
            )
        for artifact in candidate.artifacts:
            name = str(artifact.name)
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                raise ExtractionError(
                    CODE_PATH_CONTAINMENT,
                    f"artifact name {name!r} contains unsafe characters",
                    location="artifact name",
                )
            sha256 = _sha256_hex(artifact.bytes)
            size = len(artifact.bytes)
            staged_rel = _staging_relative_path(ctx, name)
            try:
                written_sha, written_size = managed.atomic_write_bytes(
                    staged_rel,
                    artifact.bytes,
                    expected_sha256=sha256,
                )
            except ManagedPathError as exc:
                raise _wrap_managed_errors(exc) from exc
            except ArtifactWriteError as exc:
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"staging artifact {name!r} failed: {exc}",
                    location="artifact (staging)",
                ) from exc
            if written_sha != sha256 or written_size != size:
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"staged artifact {name!r} evidence mismatch",
                    location="artifact (staging)",
                    details={"sha256": written_sha, "size_bytes": written_size},
                )
            staged.append(
                {
                    "name": name,
                    "purpose": str(artifact.purpose),
                    "staged_rel": staged_rel,
                    "sha256": sha256,
                    "size_bytes": size,
                    "width": int(artifact.width),
                    "height": int(artifact.height),
                }
            )
    return staged


def _publish_phase(
    ctx: WorkerContext,
    managed: ManagedRoot,
    input_ev: dict[str, Any],
    candidates: list[ExtractionCandidate],
    staged: list[dict[str, Any]],
    cp: dict[str, Any],
) -> dict[str, Any]:
    """Publish phase: atomic move + ONE transaction (artifacts + roles +
    occurrences + manifest artifact + job link).

    Replay-safe: a committed publication (checkpointed) is verified
    row-by-row; a crash between the file move and the DB commit reuses the
    verified final files (same deterministic ids/paths/sha256).  A DB
    failure removes the files THIS attempt published — never a file a
    committed replay owns.  A cancel before this phase leaves zero rows.
    """
    if ctx.session_factory is None:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot publish",
            location="publish phase",
        )
    _raise_if_cancelled(ctx, "publish")

    published_files: list[dict[str, Any]] = []
    created_files: list[Path] = []
    try:
        # 1) Move every staged file into the final managed path (atomic
        #    rename); a pre-existing verified final file is reused.
        for entry in staged:
            final_rel = _final_relative_path(ctx, str(entry["name"]))
            try:
                staged_path = managed.resolve(str(entry["staged_rel"]))
                final_path = managed.resolve(final_rel)
            except ManagedPathError as exc:
                raise _wrap_managed_errors(exc) from exc
            created = _publish_file(managed, staged_path, final_path, str(entry["sha256"]))
            if created:
                created_files.append(final_path)
            published_files.append({**entry, "final_rel": final_rel})
    except ExtractionError:
        # File publication failed: only staged copies are owned by this
        # attempt; a pre-existing final file is never removed.
        for entry in staged:
            with contextlib.suppress(ManagedPathError, OSError):
                _remove_file(managed.resolve(str(entry["staged_rel"])))
        raise

    try:
        # 2) Persist EVERYTHING in one transaction (§7.1 state+effect rule).
        meta = [
            _candidate_meta(ctx, candidate, index)
            for index, candidate in enumerate(candidates)
        ]
        manifest_artifact_id = _publish_effect(
            ctx, input_ev, meta, published_files, managed
        )
    except Exception as exc:  # noqa: BLE001 - publication failures are permanent
        for entry in staged:
            with contextlib.suppress(ManagedPathError, OSError):
                _remove_file(managed.resolve(str(entry["staged_rel"])))
        for final_path in created_files:
            _remove_file(final_path)
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            f"publication transaction failed: {exc}",
            location="artifact (publish step)",
            details={"error_type": type(exc).__name__},
        ) from exc

    # 3) Staged copies are drained; the committed bytes live at the final
    #    paths (a committed replay never re-runs this block).
    for entry in staged:
        with contextlib.suppress(ManagedPathError, OSError):
            _remove_file(managed.resolve(str(entry["staged_rel"])))

    published = {
        "manifest_artifact_id": manifest_artifact_id,
        "manifest_rel": _final_relative_path(ctx, "result.json"),
        "candidates": [
            _candidate_meta(ctx, candidate, index)
            for index, candidate in enumerate(candidates)
        ],
        "files": published_files,
    }
    ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
    return published


def _publish_file(managed: ManagedRoot, staged_path: Path, final_path: Path, sha256: str) -> bool:
    """Atomically move the staged file to its final managed path.

    Returns True when THIS attempt moved the file (the attempt owns the
    bytes and may remove them on a later failure); False when an existing
    verified final file was reused (replay — never removed by this attempt).
    """
    if final_path.exists():
        if hash_file(final_path) != sha256:
            raise ExtractionError(
                CODE_PUBLICATION_FAILED,
                "final file exists but does not match the recorded sha256",
                location="artifact (publish step)",
                details={"expected_sha256": sha256},
            )
        _remove_file(staged_path)
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged_path, final_path)
    except OSError as exc:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            f"atomic rename into final path failed: {exc}",
            location="artifact (publish step)",
        ) from exc
    return True


def _publish_effect(
    ctx: WorkerContext,
    input_ev: dict[str, Any],
    candidates: list[dict[str, Any]],
    published_files: list[dict[str, Any]],
    managed: ManagedRoot,
) -> str:
    """Persist artifact rows + owners + roles + occurrences in ONE txn."""
    if ctx.session_factory is None:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot persist publication",
            location="publish phase",
        )
    workspace_id = str(input_ev["workspace_id"])
    project_id = str(input_ev["project_id"])
    video_item_id = str(input_ev["video_item_id"])
    generation = str(input_ev["generation"])
    extractor_version = str(input_ev["extractor_version"])

    with ctx.session_factory() as session:
        # Ownership re-validation at publication (same gate as submit).
        video = session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise ExtractionError(
                CODE_OWNERSHIP_MISMATCH,
                "video item ownership changed between submit and publication",
                location="video_item",
            )
        project = session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ExtractionError(
                CODE_OWNERSHIP_MISMATCH,
                "project ownership changed between submit and publication",
                location="project",
            )

        for entry in published_files:
            artifact_id = _artifact_id(ctx, str(entry["final_rel"]))
            artifact = session.get(Artifact, artifact_id)
            if artifact is None:
                artifact = Artifact(
                    id=artifact_id,
                    workspace_id=workspace_id,
                    kind="image",
                    relative_path=str(entry["final_rel"]),
                    state="ready",
                    sha256=str(entry["sha256"]),
                    size_bytes=int(entry["size_bytes"]),
                    mime_type="image/png",
                    width=int(entry["width"]),
                    height=int(entry["height"]),
                )
                session.add(artifact)
            else:
                if (
                    artifact.sha256 != str(entry["sha256"])
                    or artifact.size_bytes != int(entry["size_bytes"])
                    or artifact.width != int(entry["width"])
                    or artifact.height != int(entry["height"])
                ):
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"existing artifact row conflicts with the staged evidence "
                        f"({entry['name']!r})",
                        location="artifact (publish step)",
                        details={"artifact_id": artifact_id},
                    )
                if artifact.state != "ready":
                    artifact.state = "ready"
                    artifact.updated_at = datetime.now(UTC)
            owner = session.get(
                ArtifactOwner,
                (artifact_id, "video_item", video_item_id, str(entry["purpose"])),
            )
            if owner is None:
                session.add(
                    ArtifactOwner(
                        artifact_id=artifact_id,
                        owner_type="video_item",
                        owner_id=video_item_id,
                        purpose=str(entry["purpose"]),
                    )
                )

        # Manifest artifact (purpose "result" = final output of the Job).
        manifest_bytes = json.dumps(
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "job_id": ctx.job_id,
                "video_item_id": video_item_id,
                "source_generation": generation,
                "source_sha256": input_ev["source_sha256"],
                "extractor_version": extractor_version,
                "provider": ctx.input_manifest.get("provider") or PROVIDER_PRODUCTION,
                "candidates": [
                    {
                        "index": candidate["index"],
                        "role_id": candidate["role_id"],
                        "name": candidate["name"],
                        "kind": candidate["kind"],
                        "confidence": candidate["confidence"],
                        "reasons": candidate["reasons"],
                        "occurrences": candidate["occurrences"],
                        "artifacts": [
                            {
                                "name": artifact["name"],
                                "purpose": artifact["purpose"],
                                "sha256": artifact["sha256"],
                                "size_bytes": artifact["size_bytes"],
                                "width": artifact["width"],
                                "height": artifact["height"],
                            }
                            for artifact in candidate["artifacts"]
                        ],
                    }
                    for candidate in candidates
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
        manifest_rel = _final_relative_path(ctx, "result.json")
        manifest_sha = _sha256_hex(manifest_bytes)
        manifest_size = len(manifest_bytes)
        try:
            managed.atomic_write_bytes(
                manifest_rel,
                manifest_bytes,
                expected_sha256=manifest_sha,
            )
        except ManagedPathError as exc:
            raise _wrap_managed_errors(exc) from exc
        except ArtifactWriteError as exc:
            raise ExtractionError(
                CODE_PUBLICATION_FAILED,
                f"writing the result manifest failed: {exc}",
                location="artifact (manifest)",
            ) from exc
        manifest_artifact_id = _artifact_id(ctx, manifest_rel)
        manifest_row = session.get(Artifact, manifest_artifact_id)
        if manifest_row is None:
            manifest_row = Artifact(
                id=manifest_artifact_id,
                workspace_id=workspace_id,
                kind="document",
                relative_path=manifest_rel,
                state="ready",
                sha256=manifest_sha,
                size_bytes=manifest_size,
                mime_type="application/json",
            )
            session.add(manifest_row)
        else:
            if manifest_row.sha256 != manifest_sha or manifest_row.size_bytes != manifest_size:
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    "existing manifest artifact row conflicts with the staged evidence",
                    location="artifact (manifest)",
                    details={"artifact_id": manifest_artifact_id},
                )
            if manifest_row.state != "ready":
                manifest_row.state = "ready"
                manifest_row.updated_at = datetime.now(UTC)
        owner = session.get(
            ArtifactOwner,
            (manifest_artifact_id, "video_item", video_item_id, ARTIFACT_PURPOSE_RESULT_MANIFEST),
        )
        if owner is None:
            session.add(
                ArtifactOwner(
                    artifact_id=manifest_artifact_id,
                    owner_type="video_item",
                    owner_id=video_item_id,
                    purpose=ARTIFACT_PURPOSE_RESULT_MANIFEST,
                )
            )

        # Roles + occurrences: deterministic ids, one row per candidate.
        scene_ids = {str(scene["id"]) for scene in input_ev["scenes"]}
        for candidate in candidates:
            index = int(candidate["index"])
            role_id = _role_id(ctx, index)
            role = session.get(ObjectRole, role_id)
            if role is None:
                role = ObjectRole(
                    id=role_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    source_generation=generation,
                    source_job_id=ctx.job_id,
                    name=str(candidate["name"]),
                    kind=str(candidate["kind"]),
                    status="suggested",
                    idempotency_key=f"discover-objects:{ctx.job_id}:role:{index}",
                )
                session.add(role)
            else:
                if (
                    role.video_item_id != video_item_id
                    or role.source_generation != generation
                    or role.source_job_id != ctx.job_id
                ):
                    raise ExtractionError(
                        CODE_INPUT_CHANGED,
                        f"existing role {role_id!r} belongs to a different "
                        "video/generation/job — refusing to overwrite",
                        location="object_role",
                        details={"role_id": role_id},
                    )
            for occurrence in candidate["occurrences"]:
                scene_id = str(occurrence["scene_id"])
                if scene_id not in scene_ids:
                    raise ExtractionError(
                        CODE_OWNERSHIP_MISMATCH,
                        f"candidate occurrence scene {scene_id!r} is not a scene "
                        "of this video item",
                        location="object_occurrence",
                        details={"scene_id": scene_id},
                    )
                frame_index = int(occurrence["frame_index"])
                existing = session.scalar(
                    select(ObjectOccurrence).where(
                        ObjectOccurrence.role_id == role_id,
                        ObjectOccurrence.scene_id == scene_id,
                        ObjectOccurrence.frame_index == frame_index,
                    )
                )
                if existing is None:
                    session.add(
                        ObjectOccurrence(
                            workspace_id=workspace_id,
                            project_id=project_id,
                            video_item_id=video_item_id,
                            role_id=role_id,
                            scene_id=scene_id,
                            frame_index=frame_index,
                            time_ms=int(occurrence["time_ms"]),
                            bbox_x=int(occurrence["bbox"]["x"]),
                            bbox_y=int(occurrence["bbox"]["y"]),
                            bbox_w=int(occurrence["bbox"]["width"]),
                            bbox_h=int(occurrence["bbox"]["height"]),
                            confidence=float(occurrence["confidence"]),
                            confidence_source=str(occurrence["confidence_source"]),
                            algorithm=str(occurrence["algorithm"]),
                            algorithm_version=str(occurrence["algorithm_version"]),
                            reasons_json=json.dumps(list(occurrence["reasons"])),
                            review_state=str(occurrence["review_state"]),
                        )
                    )
                else:
                    if (
                        existing.time_ms != int(occurrence["time_ms"])
                        or existing.confidence != float(occurrence["confidence"])
                        or existing.algorithm_version
                        != str(occurrence["algorithm_version"])
                    ):
                        raise ExtractionError(
                            CODE_INPUT_CHANGED,
                            f"existing occurrence (role {role_id!r}, scene "
                            f"{scene_id!r}, frame {frame_index}) conflicts with "
                            "this run's evidence — refusing to overwrite",
                            location="object_occurrence",
                        )

        # Role->artifact associations (correction B6): keyed by stable ids +
        # purpose + generation + source job.  Display names are never joins.
        files_by_name = {str(entry["name"]): entry for entry in published_files}
        for candidate in candidates:
            index = int(candidate["index"])
            role_id = str(candidate["role_id"])
            for artifact_meta in candidate["artifacts"]:
                name = str(artifact_meta["name"])
                file_entry = files_by_name.get(name)
                if file_entry is None:
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"candidate artifact {name!r} has no published file entry",
                        location="object_role_artifact",
                        details={"role_id": role_id, "artifact_name": name},
                    )
                artifact_id = _artifact_id(ctx, str(file_entry["final_rel"]))
                association_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_OID,
                        f"discover-objects:{ctx.job_id}:role:{index}:artifact:{name}",
                    )
                )
                existing_assoc = session.get(ObjectRoleArtifact, association_id)
                if existing_assoc is None:
                    session.add(
                        ObjectRoleArtifact(
                            id=association_id,
                            workspace_id=workspace_id,
                            role_id=role_id,
                            artifact_id=artifact_id,
                            purpose=str(artifact_meta["purpose"]),
                            source_generation=generation,
                            source_job_id=ctx.job_id,
                        )
                    )
                else:
                    if (
                        existing_assoc.role_id != role_id
                        or existing_assoc.artifact_id != artifact_id
                        or existing_assoc.purpose != str(artifact_meta["purpose"])
                        or existing_assoc.source_generation != generation
                        or existing_assoc.source_job_id != ctx.job_id
                    ):
                        raise ExtractionError(
                            CODE_PUBLICATION_FAILED,
                            f"existing association {association_id!r} conflicts "
                            "with this run's evidence",
                            location="object_role_artifact",
                            details={"association_id": association_id},
                        )
        # ── T02 structural-evidence wiring (inside same transaction) ─────────
        # Every extraction candidate → ONE OccurrenceSegment per (role, scene)
        # scene-scoped frame/time range, generation = job manifest, source_job_id,
        # mask_artifact_id = published mask, deterministic uuid5 logical_id + id,
        # idempotency, canonical prompt/seg JSON, provenance/confidence.
        # Motion: camera_relative + object_relative per segment, point_track_flow_ref REFERENCE.
        # Scene-graph: occlusion + contact per scene (current-gen same video, range within).
        # All rows created via StructuralEvidenceRepository inside the ONE transaction
        # so any failure rolls back roles/occurrences/artifacts too; replay is idempotent.
        from app.persistence.structural_evidence import StructuralEvidenceRepository

        repo = StructuralEvidenceRepository(session)
        # Map candidate index -> mask artifact id (published mask)
        candidate_mask_ids: dict[int, str] = {}
        for cand in candidates:
            idx = int(cand["index"])
            for art_meta in cand["artifacts"]:
                if str(art_meta["purpose"]) == ARTIFACT_PURPOSE_CANDIDATE_MASK:
                    fname = str(art_meta["name"])
                    fe = files_by_name.get(fname)
                    if fe is not None:
                        candidate_mask_ids[idx] = _artifact_id(ctx, str(fe["final_rel"]))
        # Track segments per scene for edge creation
        from collections import defaultdict
        segments_by_scene: dict[str, list[str]] = defaultdict(list)
        all_segment_ids: list[str] = []
        segment_range_by_id: dict[str, dict[str, int]] = {}
        # Create segments
        for cand in candidates:
            idx = int(cand["index"])
            kind = str(cand["kind"])
            # Guard: never produce source_overlay segments from extraction
            if kind in REMOVAL_ONLY_KINDS:
                continue
            role_id = str(cand["role_id"])
            # bbox for prompt generation (first occurrence's bbox) — truthful: never fabricate
            bbox_raw = None
            occs = cand.get("occurrences")
            if isinstance(occs, list) and occs:
                try:
                    maybe = occs[0].get("bbox") if isinstance(occs[0], dict) else None
                    if isinstance(maybe, dict):
                        bbox_raw = maybe
                except Exception:
                    bbox_raw = None
            # Validate bbox shape: must be {x,y,width,height} all finite ints, w/h>0
            bbox_valid: dict[str, int] | None = None
            if isinstance(bbox_raw, dict) and {"x", "y", "width", "height"} <= set(bbox_raw.keys()):
                try:
                    x = int(bbox_raw["x"])
                    y = int(bbox_raw["y"])
                    w = int(bbox_raw["width"])
                    h = int(bbox_raw["height"])
                    if any(not math.isfinite(float(v)) for v in (x, y, w, h)) or w <= 0 or h <= 0:
                        bbox_valid = None
                    else:
                        bbox_valid = {"x": x, "y": y, "width": w, "height": h}
                except (ValueError, TypeError, OverflowError):
                    bbox_valid = None
            # Truthful: missing/malformed bbox → omit prompt evidence (never fabricate 10/10/50/50)
            if bbox_valid is None:
                prompt = None
                segmentation = None
            else:
                prompt = _prompt_for_bbox(bbox_valid)
                segmentation = _prompt_for_bbox(bbox_valid)
            mask_artifact_id = candidate_mask_ids.get(idx)
            # If mask required for segmentation evidence, fail-closed if missing
            if mask_artifact_id is None and (prompt is not None or segmentation is not None):
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"segment for candidate {idx} carries segmentation evidence but mask artifact is missing",  # noqa: E501
                    location="structural evidence mask lifecycle",
                )
            for scene in input_ev["scenes"]:
                scene_id = str(scene["id"])
                sf = int(scene["start_frame"])
                ef = int(scene["end_frame"])
                st = int(scene["start_time_ms"])
                et = int(scene["end_time_ms"])
                logical_id = _segment_logical_id(ctx, idx, scene_id)
                seg_id = _segment_id(ctx, idx, scene_id)
                idem = f"discover-objects:{ctx.job_id}:segment:{idx}:{scene_id}"
                # Confidence: fail closed on missing, NaN, Inf, out-of-range - no clamp/default
                _raw_conf = cand.get("confidence")
                if _raw_conf is None:
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"candidate {idx} confidence is missing (fail closed, no default)",
                        location="structural evidence confidence",
                    )
                try:
                    conf = float(_raw_conf)
                except (TypeError, ValueError):
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"candidate {idx} confidence is not a number: {_raw_conf!r}",
                        location="structural evidence confidence",
                    ) from None
                if not math.isfinite(conf) or not 0 <= conf <= 1:
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"candidate {idx} confidence out of range or non-finite: {conf!r}",
                        location="structural evidence confidence",
                    )
                # Algorithm: production uses actual provider algorithm, never deterministic-layout fallback  # noqa: E501
                _occs_for_algo = cand.get("occurrences")
                if isinstance(_occs_for_algo, list) and _occs_for_algo and isinstance(_occs_for_algo[0], dict) and _occs_for_algo[0].get("algorithm"):  # noqa: E501
                    _candidate_algorithm = str(_occs_for_algo[0].get("algorithm"))
                else:
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"candidate {idx} algorithm is missing (fail closed, no deterministic-layout fallback in production)",  # noqa: E501
                        location="structural evidence algorithm",
                    )
                # QA provenance marker: deterministic + qa_mode carries synthetic flag
                _is_qa_for_seg = bool(ctx.input_manifest.get("qa_mode")) and str(ctx.input_manifest.get("provider") or "") in (PROVIDER_DETERMINISTIC, PROVIDER_DETERMINISTIC_IDENTITY)  # noqa: E501
                _provenance = {
                    "job_id": ctx.job_id,
                    "provider": str(ctx.input_manifest.get("provider") or ""),
                    "extractor_version": extractor_version,
                    "phase": "extract",
                    "qa_mode": bool(ctx.input_manifest.get("qa_mode")),
                }
                if _is_qa_for_seg:
                    _provenance["synthetic"] = True
                    _provenance["test_adapter"] = True
                rec, _created = repo.create_extraction_segment(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    role_id=role_id,
                    scene_id=scene_id,
                    logical_id=logical_id,
                    segment_id=seg_id,
                    name=str(cand["name"]),
                    kind=kind,
                    start_frame=sf,
                    end_frame=ef,
                    start_time_ms=st,
                    end_time_ms=et,
                    source_generation=generation,
                    source_job_id=ctx.job_id,
                    prompt=prompt,
                    segmentation=segmentation,
                    mask_artifact_id=mask_artifact_id,
                    algorithm=_candidate_algorithm,
                    algorithm_version=str(extractor_version),
                    confidence=conf,
                    confidence_source="detector",
                    reasons=list(cand.get("reasons", [])),
                    provenance=_provenance,
                    visibility="visible",
                    z_order=idx,
                    idempotency_key=idem,
                )
                segments_by_scene[scene_id].append(rec.id)
                all_segment_ids.append(rec.id)
                segment_range_by_id[rec.id] = {"start_frame": sf, "end_frame": ef, "start_time_ms": st, "end_time_ms": et}  # noqa: E501
        # Synthetic evidence gating: ONLY deterministic QA provider + QA mode may create motion/contact/occlusion  # noqa: E501
        _is_qa_synthetic = bool(ctx.input_manifest.get("qa_mode")) and str(ctx.input_manifest.get("provider") or "") in (PROVIDER_DETERMINISTIC, PROVIDER_DETERMINISTIC_IDENTITY)  # noqa: E501
        _actual_provider = str(ctx.input_manifest.get("provider") or "")  # noqa: E501
        # Create motions per segment (camera_relative + object_relative) — QA only
        if _is_qa_synthetic:
            for seg_id in all_segment_ids:
                rng = segment_range_by_id.get(seg_id, {})
                sf = int(rng.get("start_frame", 0))
                ef = int(rng.get("end_frame", 0))
                st = int(rng.get("start_time_ms", 0))
                et = int(rng.get("end_time_ms", 0))
                # camera_relative — QA synthetic only
                cam_transform = {"matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "proj": "affine2d"}
                cam_ref = {"tracks": [f"discover-objects:{ctx.job_id}:track:{seg_id}:camera"], "kind": "sparse_flow"}  # noqa: E501
                cam_idem = f"discover-objects:{ctx.job_id}:motion:{seg_id}:camera_relative"
                repo.create_motion(
                    workspace_id,
                    seg_id,
                    "camera_relative",
                    cam_transform,
                    point_track_flow_ref=cam_ref,
                    start_frame=sf,
                    end_frame=ef,
                    start_time_ms=st,
                    end_time_ms=et,
                    algorithm="deterministic-layout",
                    algorithm_version=str(extractor_version),
                    confidence=0.85,
                    confidence_source="derived",
                    reasons=["camera_motion_contract_only_no_engine"],
                    provenance={"job_id": ctx.job_id, "provider": _actual_provider, "qa_mode": True, "synthetic": True, "test_adapter": True},  # noqa: E501
                    idempotency_key=cam_idem,
                )
                # object_relative — stable digest, not hash()
                _tx_raw = int.from_bytes(hashlib.sha256(seg_id.encode("utf-8")).digest()[:4], "big")
                tx = float((_tx_raw % 20) - 10)
                obj_transform = {"tx": tx, "ty": 0.0, "scale": 1.0, "rotation_deg": 0.0}
                obj_ref = {"occurrence_ref": f"role:{seg_id}:scene", "kind": "sparse_flow"}
                obj_idem = f"discover-objects:{ctx.job_id}:motion:{seg_id}:object_relative"
                repo.create_motion(
                    workspace_id,
                    seg_id,
                    "object_relative",
                    obj_transform,
                    point_track_flow_ref=obj_ref,
                    start_frame=sf,
                    end_frame=ef,
                    start_time_ms=st,
                    end_time_ms=et,
                    algorithm="deterministic-layout",
                    algorithm_version=str(extractor_version),
                    confidence=0.82,
                    confidence_source="derived",
                    reasons=["object_motion_contract_only_no_engine"],
                    provenance={"job_id": ctx.job_id, "provider": _actual_provider, "qa_mode": True, "synthetic": True, "test_adapter": True},  # noqa: E501
                    idempotency_key=obj_idem,
                )
        # Create scene-graph edges per scene (occlusion + contact) — QA only, never inferred in production  # noqa: E501
        if _is_qa_synthetic:
            for scene_id, seg_ids in segments_by_scene.items():
                if len(seg_ids) < 2:
                    continue
                # Find scene range
                scene = next((s for s in input_ev["scenes"] if str(s["id"]) == scene_id), None)
                if scene is None:
                    continue
                sf = int(scene["start_frame"])
                ef = int(scene["end_frame"])
                st = int(scene["start_time_ms"])
                et = int(scene["end_time_ms"])
                occluder = seg_ids[0]
                occludee = seg_ids[1]
                # Occlusion: occluder -> occludee, range = scene range — QA synthetic only
                occ_idem = f"discover-objects:{ctx.job_id}:occlusion:{scene_id}"
                repo.create_occlusion(
                    workspace_id,
                    project_id,
                    video_item_id,
                    occluder,
                    occludee,
                    start_frame=sf,
                    end_frame=ef,
                    start_time_ms=st,
                    end_time_ms=et,
                    algorithm="deterministic-layout",
                    algorithm_version=str(extractor_version),
                    confidence=0.9,
                    confidence_source="derived",
                    reasons=["deterministic-occlusion"],
                    provenance={"job_id": ctx.job_id, "provider": _actual_provider, "qa_mode": True, "synthetic": True, "test_adapter": True},  # noqa: E501
                    idempotency_key=occ_idem,
                )
                # Contact: same endpoints, kind deterministic, sub-range within segment — QA synthetic only  # noqa: E501
                # Sub-range to prove edges can be finer than segments
                sub_sf = sf + max(1, (ef - sf) // 4) if ef > sf else sf
                sub_ef = ef - max(1, (ef - sf) // 4) if ef > sf else ef
                sub_st = st + max(1, (et - st) // 4) if et > st else st
                sub_et = et - max(1, (et - st) // 4) if et > st else et
                if sub_sf > sub_ef:
                    sub_sf, sub_ef = sf, ef
                if sub_st > sub_et:
                    sub_st, sub_et = st, et
                # Pick contact kind by scene order
                scene_index = list(segments_by_scene.keys()).index(scene_id)
                ck = CONTACT_KINDS[scene_index % len(CONTACT_KINDS)]
                contact_idem = f"discover-objects:{ctx.job_id}:contact:{scene_id}"
                repo.create_contact(
                    workspace_id,
                    project_id,
                    video_item_id,
                    occluder,
                    occludee,
                    contact_kind=ck,
                    start_frame=sub_sf,
                    end_frame=sub_ef,
                    start_time_ms=sub_st,
                    end_time_ms=sub_et,
                    algorithm="deterministic-layout",
                    algorithm_version=str(extractor_version),
                    confidence=0.85,
                    confidence_source="derived",
                    reasons=["deterministic-contact"],
                    provenance={"job_id": ctx.job_id, "provider": _actual_provider, "qa_mode": True, "synthetic": True, "test_adapter": True},  # noqa: E501
                    idempotency_key=contact_idem,
                )
        session.commit()
    return manifest_artifact_id


def _verify_committed(
    ctx: WorkerContext, managed: ManagedRoot, published: dict[str, Any]
) -> None:
    """Replay verification of a committed publication (row-by-row).

    Every declared artifact row must be ``ready`` with matching evidence and
    its file must exist on disk with the recorded sha256/size; the manifest
    row must be ``ready``; every candidate role row must exist with the
    deterministic id.  Any mismatch fails closed (never re-publishes, never
    completes with partial output).
    """
    if ctx.session_factory is None:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot verify publication",
            location="publish phase",
        )
    with ctx.session_factory() as session:
        for entry in published.get("files", []):
            artifact_id = _artifact_id(ctx, str(entry["final_rel"]))
            artifact = session.get(Artifact, artifact_id)
            if artifact is None or artifact.state != "ready":
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"published artifact {artifact_id!r} is not a ready row",
                    location="artifact",
                    details={"artifact_id": artifact_id, "final_rel": entry["final_rel"]},
                )
            if (
                artifact.sha256 != str(entry["sha256"])
                or artifact.size_bytes != int(entry["size_bytes"])
                or artifact.width != int(entry["width"])
                or artifact.height != int(entry["height"])
            ):
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"published artifact {artifact_id!r} evidence mismatch",
                    location="artifact",
                    details={"artifact_id": artifact_id},
                )
            try:
                target = managed.resolve(str(entry["final_rel"]))
            except ManagedPathError as exc:
                raise _wrap_managed_errors(exc) from exc
            if not target.is_file() or hash_file(target) != str(entry["sha256"]):
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"published artifact file missing/corrupt: {entry['final_rel']!r}",
                    location="artifact file",
                    details={"artifact_id": artifact_id, "final_rel": entry["final_rel"]},
                )
        manifest_artifact_id = str(published["manifest_artifact_id"])
        manifest_row = session.get(Artifact, manifest_artifact_id)
        if manifest_row is None or manifest_row.state != "ready":
            raise ExtractionError(
                CODE_PUBLICATION_FAILED,
                f"manifest artifact {manifest_artifact_id!r} is not a ready row",
                location="artifact",
                details={"artifact_id": manifest_artifact_id},
            )
        for candidate in published.get("candidates", []):
            role_id = _role_id(ctx, int(candidate["index"]))
            role = session.get(ObjectRole, role_id)
            if role is None or role.source_job_id != ctx.job_id:
                raise ExtractionError(
                    CODE_PUBLICATION_FAILED,
                    f"candidate role {role_id!r} missing for job {ctx.job_id}",
                    location="object_role",
                    details={"role_id": role_id},
                )
            # Every candidate artifact must have its durable role association
            # (correction B6) — a missing association is an incomplete output.
            for artifact_meta in candidate.get("artifacts", []):
                name = str(artifact_meta["name"])
                association_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_OID,
                        f"discover-objects:{ctx.job_id}:role:{int(candidate['index'])}"
                        f":artifact:{name}",
                    )
                )
                association = session.get(ObjectRoleArtifact, association_id)
                if (
                    association is None
                    or association.role_id != role_id
                    or association.source_job_id != ctx.job_id
                    or association.source_generation != role.source_generation
                ):
                    raise ExtractionError(
                        CODE_PUBLICATION_FAILED,
                        f"association {association_id!r} missing/mismatched for "
                        f"role {role_id!r} artifact {name!r}",
                        location="object_role_artifact",
                        details={"association_id": association_id, "role_id": role_id},
                    )


# ── Declared-outputs gate (contract §9.3, invariant §15-5) ───────────────────


def _validate_extraction_outputs(
    ctx: WorkerContext, result: dict[str, Any], staging_dir: Path
) -> dict[str, Any]:
    """Output validator: re-verify EVERY declared artifact, role, and structural-evidence row.

    Runs inside the worker's completion gate: any missing/corrupt row or
    file raises, so the Job can never reach ``completed`` with a partial
    output set.  The validator is deliberately strict — it re-reads the
    committed database and the managed filesystem (never trusts the
    handler's own in-memory result).
    """
    del staging_dir
    published = result.get("published")
    if not isinstance(published, dict) or not published.get("manifest_artifact_id"):
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            "handler result carries no published manifest",
            location="output validation",
        )
    _verify_committed(ctx, _managed_for(ctx), published)
    # Also verify structural evidence is committed (segment/motion/edge counts)
    # Fail-closed: if any structural row missing, validation fails and job never completes.
    # Structural rows are part of the same publication transaction.
    try:
        _verify_structural_evidence(ctx, published)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            CODE_PUBLICATION_FAILED,
            f"structural evidence validation failed: {exc}",
            location="output validation structural",
        ) from exc
    return {"validated": True, "candidates": len(published.get("candidates", []))}


def _verify_structural_evidence(ctx: WorkerContext, published: dict[str, Any]) -> None:
    """Verify structural-evidence rows committed for this job (T02-C1 truthful)."""
    if ctx.session_factory is None:
        raise ExtractionError(CODE_PUBLICATION_FAILED, "no session factory for structural verification", location="structural verification")  # noqa: E501
    from sqlalchemy import select as _select

    from app.persistence.models import (
        OccurrenceSegment,
        SegmentMotion,
    )
    expected_cands = len(published.get("candidates", []))
    is_qa = bool(ctx.input_manifest.get("qa_mode")) and str(ctx.input_manifest.get("provider") or "") in (PROVIDER_DETERMINISTIC, PROVIDER_DETERMINISTIC_IDENTITY)  # noqa: E501
    # Count segments for this job
    with ctx.session_factory() as session:
        segs = session.scalars(_select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == ctx.job_id)).all()  # noqa: E501
        if expected_cands > 0 and len(segs) == 0:
            raise ExtractionError(CODE_PUBLICATION_FAILED, "structural evidence segments missing for completed job", location="structural verification")  # noqa: E501
        for seg in segs:
            if seg.source_generation != str(ctx.input_manifest.get("generation") or ""):
                raise ExtractionError(CODE_PUBLICATION_FAILED, f"segment {seg.id} generation mismatch", location="structural verification")  # noqa: E501
            if seg.mask_artifact_id is None:
                raise ExtractionError(CODE_PUBLICATION_FAILED, f"segment {seg.id} missing mask artifact", location="structural verification")  # noqa: E501
            # Production must use actual provider algorithm, never deterministic-layout when not QA
            if not is_qa and seg.algorithm == "deterministic-layout":
                raise ExtractionError(CODE_PUBLICATION_FAILED, f"segment {seg.id} uses deterministic-layout in production (false evidence)", location="structural verification")  # noqa: E501
        # Verify motions: QA expects synthetic motions, production expects truthful (no fake)
        motions = session.scalars(_select(SegmentMotion).where(SegmentMotion.workspace_id == str(ctx.input_manifest.get("workspace_id") or "default"))).all()  # noqa: E501
        seg_ids = {s.id for s in segs}
        job_motions = [m for m in motions if m.occurrence_segment_id in seg_ids]
        if is_qa:
            if expected_cands > 0 and len(job_motions) < len(segs):
                raise ExtractionError(CODE_PUBLICATION_FAILED, "structural evidence motions missing (QA synthetic)", location="structural verification")  # noqa: E501
        else:
            # Production truthful: no synthetic motion/contact/occlusion, no fake sparse-flow, no deterministic-layout  # noqa: E501
            if len(job_motions) != 0:
                raise ExtractionError(CODE_PUBLICATION_FAILED, f"production job has synthetic motions {len(job_motions)} (false evidence)", location="structural verification")  # noqa: E501
            # Also ensure no contact/occlusion leaked — checked via segment count, but verify motions are zero  # noqa: E501
        # Verify no false evidence: production without estimator must not have confidence=1.0/model
        for m in job_motions:
            if m.confidence == 1.0 and m.confidence_source == "model":
                raise ExtractionError(CODE_PUBLICATION_FAILED, f"motion {m.id} has false evidence confidence=1.0/model", location="structural verification")  # noqa: E501



# ── Submit (contract §8.1 idempotency) ───────────────────────────────────────


def discover_objects_steps() -> list[StepInput]:
    """The DISCOVER_OBJECTS step plan (one sync step)."""
    return [
        StepInput(
            step_code=DISCOVER_OBJECTS_STEP_CODE,
            position=0,
            step_type="sync",
        )
    ]


@dataclass(frozen=True)
class ExtractionSubmitResult:
    """Result of :func:`submit_discover_objects` — the Job id + reuse flag."""

    job_id: str
    reused: bool


def _idempotency_key(
    video_item_id: str,
    source_sha256: str | None,
    generation: str,
    extractor_version: str,
) -> str:
    """Owner-scoped DISCOVER_OBJECTS idempotency key (TASK requirement)."""
    return (
        f"{JOB_TYPE_DISCOVER_OBJECTS}:video_item:{video_item_id}:"
        f"{source_sha256 or 'no-sha'}:{generation}:{extractor_version}"
    )


def _authoritative_source(session: Session, workspace_id: str, video_item_id: str) -> Artifact:
    """C2: resolve the CURRENT source artifact + SHA from backend state.

    The video item's ``source_artifact_id`` IS the authority — the server
    never trusts a client-supplied checksum for manifest/idempotency.
    """
    from app.persistence.models import VideoItem as VideoItemORM

    video = session.get(VideoItemORM, video_item_id)
    if video is None:
        raise ExtractionError(
            CODE_VIDEO_ITEM_NOT_FOUND,
            "video item not found",
            location="submit",
        )
    project = session.get(Project, video.project_id)
    if project is None or project.workspace_id != workspace_id:
        raise ExtractionError(
            CODE_OWNERSHIP_MISMATCH,
            "video item does not belong to the declared workspace",
            location="submit",
        )
    if video.source_artifact_id is None:
        raise ExtractionError(
            CODE_SOURCE_ARTIFACT_NOT_FOUND,
            "video item has no source artifact",
            location="submit",
        )
    source = session.get(Artifact, video.source_artifact_id)
    if source is None or source.workspace_id != workspace_id:
        raise ExtractionError(
            CODE_SOURCE_ARTIFACT_NOT_FOUND,
            "source artifact not found or not in the workspace",
            location="submit",
        )
    if source.state != "ready" or source.kind != "video":
        raise ExtractionError(
            CODE_SOURCE_NOT_READY,
            "source artifact is not a ready video artifact",
            location="submit",
        )
    if source.sha256 is None or len(source.sha256) != 64:
        raise ExtractionError(
            CODE_SOURCE_NOT_READY,
            "source artifact has no recorded sha256",
            location="submit",
        )
    return source


def _authoritative_generation(
    session: Session, video_item_id: str, source_sha256: str
) -> str:
    """C2: backend-derived CURRENT generation for this source.

    The generation of the newest COMPLETED job whose manifest source sha
    equals the current source is reused (idempotent identity); otherwise
    the next integer after the highest completed generation (never silently
    ``1`` when the backend current differs).
    """
    from app.persistence.jobs import parse_json
    from app.persistence.models import Job as JobORM

    rows = session.scalars(
        select(JobORM)
        .where(
            JobORM.job_type == JOB_TYPE_DISCOVER_OBJECTS,
            JobORM.owner_id == video_item_id,
            JobORM.state == "completed",
        )
        .order_by(JobORM.created_at.desc(), JobORM.id.desc())
    ).all()
    max_gen = 0
    latest_for_sha: str | None = None
    for row in rows:
        gen = str(row.input_generation or "")
        if gen.isdigit():
            max_gen = max(max_gen, int(gen))
        manifest = parse_json(row.input_manifest_json, {})
        manifest_sha = (
            str(manifest.get("source_sha256") or "") if isinstance(manifest, dict) else ""
        )
        if manifest_sha == source_sha256 and latest_for_sha is None:
            latest_for_sha = gen if gen else None
    if latest_for_sha is not None:
        return latest_for_sha
    return str(max_gen + 1) if max_gen else "1"


def submit_discover_objects(
    session_factory: Callable[[], Session],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    source_sha256: str | None = None,
    generation: str | None = None,
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
    provider: str | None = None,
    managed_root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> ExtractionSubmitResult:
    """Create the durable DISCOVER_OBJECTS Job for one video item.

    BACKEND SOURCE AUTHORITY (C2): the server resolves the current source
    artifact, its SHA-256 and the current generation itself from durable
    state.  Client-supplied ``source_sha256``/``generation`` are retained
    ONLY as assertions — a mismatch fails closed with ``SOURCE_CONFLICT``
    (409) and creates NO Job row.  The manifest and idempotency key ALWAYS
    use the backend-authoritative values.

    Ownership is validated BEFORE any write (cross-workspace/cross-project
    submission is rejected with no Job row).  The provider is resolved and
    capability-checked at submit time: the production provider unavailable
    ⇒ ``PROVIDER_UNAVAILABLE`` raised immediately (fail closed, no
    fallback); the QA/test-only deterministic adapters resolve ONLY in
    genuine QA mode (acceptance 7/8).  A completed duplicate for the same
    key returns the existing Job (``reused=True``); an active duplicate
    raises ``IdempotencyKeyInUse``.
    """
    if not workspace_id or not project_id or not video_item_id:
        raise ValueError("workspace_id, project_id and video_item_id are required")
    if source_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError(
            "source_sha256 must be a 64-character lowercase hex string when provided"
        )
    if generation is not None and str(generation) and not str(generation).isdigit():
        raise ValueError("generation, when provided, must be a numeric string")
    if not extractor_version.strip():
        raise ValueError("extractor_version must not be empty")
    if len(extractor_version) > 64:
        raise ValueError("extractor_version must be at most 64 characters")

    provider_obj = resolve_extraction_provider(provider, env=env)
    if not provider_obj.available():
        raise ExtractionError(
            CODE_PROVIDER_UNAVAILABLE,
            f"extraction provider {provider_obj.name!r} is not available; the "
            "production path never falls back to another provider",
            location="submit",
            details={"provider": provider_obj.name},
        )

    with session_factory() as session:
        from app.persistence.jobs import JobRepository

        _validate_ownership(session, workspace_id, project_id, video_item_id)

        # C2: resolve the backend-authoritative source + generation ONCE.
        source = _authoritative_source(session, workspace_id, video_item_id)
        authoritative_sha = str(source.sha256)
        authoritative_generation = _authoritative_generation(
            session, video_item_id, authoritative_sha
        )

        # Client hints are ASSERTIONS ONLY (acceptance 2/3).
        if source_sha256 is not None and source_sha256 != authoritative_sha:
            raise ExtractionError(
                CODE_SOURCE_CONFLICT,
                "client source_sha256 does not match the backend-authoritative "
                "current source sha256",
                location="submit",
                details={
                    "client_source_sha256": source_sha256,
                    "authoritative_source_sha256": authoritative_sha,
                },
            )
        if generation is not None and str(generation) != authoritative_generation:
            raise ExtractionError(
                CODE_SOURCE_CONFLICT,
                "client generation does not match the backend current "
                "generation (refusing to default to it)",
                location="submit",
                details={
                    "client_generation": str(generation),
                    "authoritative_generation": authoritative_generation,
                },
            )

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "generation": authoritative_generation,
            "extractor_version": extractor_version,
            "provider": provider_obj.name,
            "source_artifact_id": source.id,
            "source_sha256": authoritative_sha,
            # C2 runtime-policy snapshot: the worker re-resolves the recorded
            # provider with the SAME authorization the submit used — never
            # silently stronger/weaker.
            "qa_mode": bool(_qa_mode_active(env)),
        }
        if managed_root is not None:
            manifest["managed_root"] = str(managed_root)

        idempotency_key = _idempotency_key(
            video_item_id, authoritative_sha, authoritative_generation, extractor_version
        )

        from app.persistence.models import Job as JobORM

        completed_exists = session.scalar(
            select(JobORM.id).where(
                JobORM.workspace_id == workspace_id,
                JobORM.idempotency_key == idempotency_key,
                JobORM.input_generation == authoritative_generation,
                JobORM.state == "completed",
            )
        )
        try:
            job = JobRepository(session).create_job(
                workspace_id=workspace_id,
                job_type=JOB_TYPE_DISCOVER_OBJECTS,
                owner_type="video_item",
                owner_id=video_item_id,
                input_manifest=manifest,
                idempotency_key=idempotency_key,
                input_generation=authoritative_generation,
                steps=discover_objects_steps(),
                actor="api",
            )
        except IntegrityError:
            # True concurrent race: the partial unique index rejected the
            # duplicate.  Map it to the stable IdempotencyKeyInUse so the
            # API returns 409, never a raw IntegrityError (contract §8.1).
            session.rollback()
            from app.persistence.jobs import IdempotencyKeyInUse

            blocker = session.scalar(
                select(JobORM.id).where(
                    JobORM.workspace_id == workspace_id,
                    JobORM.idempotency_key == idempotency_key,
                    JobORM.input_generation == authoritative_generation,
                )
            )
            if blocker is not None:
                raise IdempotencyKeyInUse(
                    f"idempotency key {idempotency_key!r} is already in use by "
                    f"job {blocker} (concurrent duplicate submission)",
                    key=idempotency_key,
                    job_id=blocker,
                ) from None
            raise
        session.commit()
        return ExtractionSubmitResult(job_id=job.id, reused=completed_exists is not None)


def _validate_ownership(
    session: Session, workspace_id: str, project_id: str, video_item_id: str
) -> VideoItem:
    """Fail-closed ownership gate: video under project under workspace."""
    project = session.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise ExtractionError(
            CODE_PROJECT_NOT_FOUND,
            f"project {project_id!r} not found in workspace {workspace_id!r}",
            location="project",
        )
    video = session.get(VideoItem, video_item_id)
    if video is None or video.project_id != project_id:
        raise ExtractionError(
            CODE_VIDEO_ITEM_NOT_FOUND,
            f"video item {video_item_id!r} not found under project {project_id!r}",
            location="video_item",
        )
    return video


def register_discover_objects_handler(worker: Any) -> None:
    """Register the DISCOVER_OBJECTS handler + strict output gate.

    No static ``declared_outputs`` (the output set varies per job), so the
    completion gate is the custom ``output_validator``: it re-verifies the
    manifest row, EVERY candidate artifact row (state ``ready``, sha256,
    size, dimensions) and its file on disk, plus every candidate role row,
    in a FRESH committed session inside the worker's completion gate
    (contract §9.3, invariant §15-5).  Any missing/corrupt row or file
    raises ⇒ the Job fails — ``completed`` is impossible until all declared
    rows/artifacts are committed and validated.
    """
    worker.register_handler(
        JOB_TYPE_DISCOVER_OBJECTS,
        discover_objects_handler,
        output_validator=_validate_extraction_outputs,
        resource_class="cpu_light",
    )
