"""Reviewed clean-plate intake and provenance for the pilot preview worker.

The worker is deliberately fail-closed here: a source-derived inpaint is not a
reviewed clean plate and cannot satisfy the render gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PLATE_PACK_REVISION = "reviewed-clean-plate-v1"
PLATE_MANIFEST_FILENAME = "manifest.json"
PRIVATE_PREVIEW_STATUSES = frozenset({"APPROVED", "PRIVATE_PREVIEW_INPUT_READY", "PREVIEW_CANDIDATE"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PlateResolutionError(ValueError):
    """Raised when a reviewed plate cannot be proven to match the job."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details or {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_sha256(manifest_path: Path) -> str:
    return _sha256(manifest_path)


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _require(condition: bool, code: str, message: str, **details: Any) -> None:
    if not condition:
        raise PlateResolutionError(code, message, details=details)


def _as_pair(value: Any, *, field: str) -> tuple[int, int]:
    _require(isinstance(value, (list, tuple)) and len(value) == 2, "PLATE_MANIFEST_INVALID", f"{field} must be a pair")
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError) as exc:
        raise PlateResolutionError("PLATE_MANIFEST_INVALID", f"{field} must contain integers") from exc


def _canonical_content_payload(
    *,
    plate_id: str,
    version: str,
    image_sha256: str,
    source_sha256: str,
    source_window: tuple[int, int],
    canvas_size: tuple[int, int],
    camera_view: str,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "revision": PLATE_PACK_REVISION,
        "plate_id": plate_id,
        "version": version,
        "image_sha256": image_sha256,
        "source_sha256": source_sha256,
        "source_window": list(source_window),
        "canvas_size": list(canvas_size),
        "camera_view": camera_view,
        "coverage": coverage,
    }


def resolve_reviewed_plate(
    plate_id: str,
    plates_root: str | Path,
    *,
    source_sha256: str,
    source_window: tuple[int, int] = (450, 570),
    canvas_size: tuple[int, int] = (640, 360),
    expected_manifest_sha256: str | None = None,
    expected_content_sha256: str | None = None,
    allow_private_preview: bool = False,
) -> dict[str, Any]:
    """Resolve an approved, source-bound, full-frame reviewed plate.

    The returned paths and hashes are the values that must be copied into the
    canonical job identity.  Client capabilities are intentionally absent from
    this function and cannot affect its result.
    """

    _require(isinstance(plate_id, str) and _ID_RE.fullmatch(plate_id) is not None, "PLATE_ID_INVALID", "invalid plate id")
    root = Path(plates_root).resolve()
    plate_root = (root / plate_id).resolve()
    _require(_contained(plate_root, root), "PLATE_PATH_ESCAPE", "plate path escapes the configured plate root")
    manifest_path = plate_root / PLATE_MANIFEST_FILENAME
    _require(manifest_path.is_file(), "PLATE_MANIFEST_MISSING", "reviewed plate manifest is missing")
    manifest_sha = _manifest_sha256(manifest_path)
    if expected_manifest_sha256:
        _require(manifest_sha == expected_manifest_sha256, "PLATE_MANIFEST_HASH_MISMATCH", "reviewed plate manifest hash mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlateResolutionError("PLATE_MANIFEST_INVALID", "reviewed plate manifest is not valid JSON") from exc

    _require(manifest.get("plate_id") == plate_id, "PLATE_ID_MISMATCH", "manifest plate id does not match the selected id")
    _require(manifest.get("revision") == PLATE_PACK_REVISION, "PLATE_REVISION_UNSUPPORTED", "reviewed plate revision is unsupported")
    approval = manifest.get("approval")
    approval_status = approval.get("status") if isinstance(approval, dict) else None
    allowed_statuses = PRIVATE_PREVIEW_STATUSES if allow_private_preview else frozenset({"APPROVED"})
    _require(approval_status in allowed_statuses, "PLATE_NOT_APPROVED", "reviewed plate is not approved for this execution mode")
    _require(
        isinstance(approval, dict)
        and bool(approval.get("reviewer"))
        and bool(approval.get("reviewed_at")),
        "PLATE_APPROVAL_INCOMPLETE",
        "plate approval provenance is incomplete",
    )
    _require(manifest.get("source_sha256") == source_sha256, "PLATE_SOURCE_MISMATCH", "reviewed plate is bound to a different source")
    actual_window = _as_pair(manifest.get("source_window"), field="source_window")
    _require(actual_window == tuple(source_window), "PLATE_WINDOW_MISMATCH", "reviewed plate source window does not match the job")
    actual_canvas = _as_pair(manifest.get("canvas_size"), field="canvas_size")
    _require(actual_canvas == tuple(canvas_size), "PLATE_CANVAS_MISMATCH", "reviewed plate canvas size does not match the job")
    camera_view = manifest.get("camera_view")
    _require(camera_view == "three_quarter_front", "PLATE_CAMERA_VIEW_MISMATCH", "reviewed plate camera view is incompatible")

    image_rel = manifest.get("image")
    _require(isinstance(image_rel, str) and image_rel, "PLATE_IMAGE_MISSING", "reviewed plate image is missing from the manifest")
    image_path = (plate_root / image_rel).resolve()
    _require(_contained(image_path, plate_root) and image_path.is_file(), "PLATE_IMAGE_INVALID", "reviewed plate image is outside the pack or missing")
    image_sha = _sha256(image_path)
    _require(image_sha == manifest.get("image_sha256"), "PLATE_IMAGE_HASH_MISMATCH", "reviewed plate image hash mismatch")
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    _require(image is not None and image.shape[:2] == (canvas_size[1], canvas_size[0]), "PLATE_IMAGE_INVALID", "reviewed plate image cannot be decoded at the declared canvas size")

    coverage = manifest.get("coverage")
    _require(isinstance(coverage, dict) and coverage.get("mode") == "full_frame", "PLATE_COVERAGE_INCOMPLETE", "reviewed plate does not cover the full source frame")
    mask_rel = coverage.get("mask")
    mask_sha = None
    if mask_rel is not None:
        _require(isinstance(mask_rel, str) and mask_rel, "PLATE_COVERAGE_INVALID", "coverage mask path is invalid")
        mask_path = (plate_root / mask_rel).resolve()
        _require(_contained(mask_path, plate_root) and mask_path.is_file(), "PLATE_COVERAGE_INVALID", "coverage mask is outside the pack or missing")
        mask_sha = _sha256(mask_path)
        _require(mask_sha == coverage.get("mask_sha256"), "PLATE_COVERAGE_HASH_MISMATCH", "coverage mask hash mismatch")
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        required_pixels = int(mask.shape[0] * mask.shape[1]) if mask is not None else 0
        _require(
            mask is not None
            and mask.shape == image.shape[:2]
            and int(np.count_nonzero(mask)) == required_pixels,
            "PLATE_COVERAGE_INCOMPLETE",
            "full-frame coverage mask does not cover every pixel",
        )

    content_payload = _canonical_content_payload(
        plate_id=plate_id,
        version=str(manifest.get("version", "")),
        image_sha256=image_sha,
        source_sha256=source_sha256,
        source_window=actual_window,
        canvas_size=actual_canvas,
        camera_view=camera_view,
        coverage=coverage,
    )
    content_sha = hashlib.sha256(json.dumps(content_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if expected_content_sha256:
        _require(content_sha == expected_content_sha256, "PLATE_CONTENT_HASH_MISMATCH", "reviewed plate content hash mismatch")
    return {
        "plate_id": plate_id,
        "version": str(manifest.get("version", "")),
        "root": str(plate_root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "image_path": str(image_path),
        "image_sha256": image_sha,
        "coverage_mask_sha256": mask_sha,
        "approval_status": approval_status,
        "source_sha256": source_sha256,
        "source_window": list(actual_window),
        "canvas_size": list(actual_canvas),
        "camera_view": camera_view,
        "coverage": coverage,
        "content_sha256": content_sha,
        "revision": PLATE_PACK_REVISION,
    }


def load_reviewed_plate(resolved: dict[str, Any], *, canvas_size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """Load the already-validated plate for actual pixel consumption."""

    image = cv2.imread(str(resolved["image_path"]), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (canvas_size[1], canvas_size[0]):
        raise PlateResolutionError("PLATE_IMAGE_INVALID", "validated reviewed plate could not be loaded")
    return image


def apply_reviewed_plate(frame: np.ndarray, plate: np.ndarray, replacement_mask: np.ndarray) -> np.ndarray:
    """Replace only the requested pixels with pixels from the reviewed plate."""

    _require(frame.shape == plate.shape, "PLATE_FRAME_SIZE_MISMATCH", "source frame and reviewed plate have different shapes")
    _require(replacement_mask.shape == frame.shape[:2], "PLATE_MASK_SIZE_MISMATCH", "replacement mask has the wrong shape")
    result = frame.copy()
    result[replacement_mask.astype(bool)] = plate[replacement_mask.astype(bool)]
    return result
