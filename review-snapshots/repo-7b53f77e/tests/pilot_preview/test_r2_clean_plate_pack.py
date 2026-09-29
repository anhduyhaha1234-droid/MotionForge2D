"""Reviewed clean-plate ownership, approval, and pixel-consumption tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.pilot_preview.clean_plate_pack import (
    PlateResolutionError,
    apply_reviewed_plate,
    resolve_reviewed_plate,
)


def _plate(root: Path, *, source_sha256: str = "a" * 64) -> tuple[Path, str]:
    pack = root / "reviewed-plate-v1"
    pack.mkdir(parents=True)
    image_path = pack / "clean.png"
    image = np.full((360, 640, 3), (31, 47, 61), dtype=np.uint8)
    image[266, 275] = (0, 0, 255)
    assert cv2.imwrite(str(image_path), image)
    manifest = {
        "plate_id": "reviewed-plate-v1",
        "version": "plate-test-v1",
        "revision": "reviewed-clean-plate-v1",
        "camera_view": "three_quarter_front",
        "source_sha256": source_sha256,
        "source_window": [450, 570],
        "canvas_size": [640, 360],
        "image": "clean.png",
        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "coverage": {"mode": "full_frame"},
        "approval": {"status": "APPROVED", "reviewer": "reviewer-1", "reviewed_at": "2026-09-09T00:00:00Z"},
    }
    (pack / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return root, "reviewed-plate-v1"


def test_reviewed_plate_resolves_and_consumes_real_pixels(tmp_path: Path) -> None:
    root, plate_id = _plate(tmp_path / "plates")
    resolved = resolve_reviewed_plate(plate_id, root, source_sha256="a" * 64)
    assert resolved["content_sha256"]
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    plate = cv2.imread(resolved["image_path"], cv2.IMREAD_COLOR)
    mask = np.zeros((360, 640), dtype=np.uint8)
    mask[266, 275] = 255
    output = apply_reviewed_plate(frame, plate, mask)
    assert tuple(output[266, 275]) == (0, 0, 255)
    assert tuple(output[0, 0]) == (0, 0, 0)


def test_reviewed_plate_source_ownership_and_tamper_fail_closed(tmp_path: Path) -> None:
    root, plate_id = _plate(tmp_path / "plates")
    with pytest.raises(PlateResolutionError, match="PLATE_SOURCE_MISMATCH"):
        resolve_reviewed_plate(plate_id, root, source_sha256="b" * 64)
    image = root / plate_id / "clean.png"
    image.write_bytes(image.read_bytes() + b"tamper")
    with pytest.raises(PlateResolutionError, match="PLATE_IMAGE_HASH_MISMATCH"):
        resolve_reviewed_plate(plate_id, root, source_sha256="a" * 64)


def test_full_frame_one_pixel_coverage_is_rejected(tmp_path: Path) -> None:
    root, plate_id = _plate(tmp_path / "plates")
    pack = root / plate_id
    mask_path = pack / "coverage.png"
    mask = np.zeros((360, 640), dtype=np.uint8)
    mask[266, 275] = 255
    assert cv2.imwrite(str(mask_path), mask)
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["coverage"] = {
        "mode": "full_frame",
        "mask": "coverage.png",
        "mask_sha256": hashlib.sha256(mask_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(PlateResolutionError, match="PLATE_COVERAGE_INCOMPLETE"):
        resolve_reviewed_plate(plate_id, root, source_sha256="a" * 64)
