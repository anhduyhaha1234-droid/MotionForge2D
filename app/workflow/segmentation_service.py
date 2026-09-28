"""Segmentation service — mask preview and propagation using SAM2 or contour."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from app.adapters.segmentation import create_segmentation_adapter
from app.config import AppConfig
from app.schemas import SelectionInput


class SegmentationService:
    """Mask generation and propagation."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def preview_mask(
        self,
        frame_path: str | Path,
        selection: SelectionInput,
        backend: str = "contour",
    ) -> np.ndarray:
        """Generate a mask preview for a single frame."""
        frame = cv2.imread(str(frame_path))
        if frame is None:
            raise FileNotFoundError(f"Frame not found: {frame_path}")

        kwargs: dict[str, object] = {}
        if backend == "sam2":
            kwargs = {
                "model_cfg": self._config.sam2_model_cfg,
                "checkpoint": self._config.sam2_checkpoint,
            }

        adapter = create_segmentation_adapter(backend=backend, **kwargs)
        try:
            mask = adapter.segment_frame(frame, selection)
        finally:
            adapter.cleanup()
        return mask

    def propagate_masks(
        self,
        frame_paths: list[Path],
        initial_mask: np.ndarray,
        initial_frame_idx: int,
        backend: str = "contour",
        progress_cb: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[np.ndarray]:
        """Propagate mask across multiple frames."""
        if not frame_paths:
            return []

        if progress_cb:
            progress_cb(0, "Loading frames")

        frames = []
        for p in frame_paths:
            if is_cancelled and is_cancelled():
                return []
            img = cv2.imread(str(p))
            if img is None:
                raise FileNotFoundError(f"Frame not found: {p}")
            frames.append(img)

        if progress_cb:
            progress_cb(30, "Running propagation")

        kwargs: dict[str, object] = {}
        if backend == "sam2":
            kwargs = {
                "model_cfg": self._config.sam2_model_cfg,
                "checkpoint": self._config.sam2_checkpoint,
            }

        adapter = create_segmentation_adapter(backend=backend, **kwargs)
        try:
            masks = adapter.propagate_masks(frames, initial_mask, initial_frame_idx)
        finally:
            adapter.cleanup()

        if progress_cb:
            progress_cb(100, "Propagation complete")

        return masks

    def capability(self, backend: str = "contour") -> dict[str, object]:
        """Real availability record for one segmentation backend (MF-END-12).

        Nothing is inferred from the backend NAME: for ``sam2`` the configured
        checkpoint is stat-ed and magic-checked and the ``sam2`` package must
        import (the production provider's own probe criteria); ``contour`` is
        pure OpenCV and always present.  A missing checkpoint answers
        ``available=False`` with the concrete reason instead of raising, so a
        caller can record BLOCKED_DEPENDENCY evidence (path checked, result).
        """
        report: dict[str, object] = {
            "backend": backend,
            "available": False,
            "reason": "",
            "checkpoint": None,
            "checkpoint_bytes": None,
        }
        if backend == "sam2":
            checkpoint = Path(str(self._config.sam2_checkpoint))
            report["checkpoint"] = str(checkpoint)
            if not checkpoint.is_file():
                report["reason"] = f"checkpoint not found: {checkpoint}"
                return report
            try:
                size = int(checkpoint.stat().st_size)
            except OSError as exc:
                report["reason"] = f"checkpoint unreadable: {exc}"
                return report
            report["checkpoint_bytes"] = size
            if size <= 0:
                report["reason"] = f"checkpoint is empty: {checkpoint}"
                return report
            try:
                with open(checkpoint, "rb") as handle:
                    magic = handle.read(4)
            except OSError as exc:
                report["reason"] = f"checkpoint unreadable: {exc}"
                return report
            if magic != b"PK\x03\x04":
                report["reason"] = f"checkpoint is not a torch checkpoint (bad magic): {checkpoint}"
                return report
            try:
                from sam2.build_sam import build_sam2  # noqa: F401, PLC0415
            except Exception as exc:  # noqa: BLE001 - capability probe
                report["reason"] = f"sam2 package unavailable: {exc}"
                return report
            report["available"] = True
            report["reason"] = "sam2.1 checkpoint + package present"
            return report
        if backend == "contour":
            report["available"] = True
            report["reason"] = "opencv contour adapter present"
            return report
        report["reason"] = f"unknown segmentation backend: {backend}"
        return report

    def preview_mask_with_provenance(
        self,
        frame_path: str | Path,
        selection: SelectionInput,
        backend: str = "contour",
    ) -> tuple[np.ndarray, dict[str, object]]:
        """Mask preview + a REAL frame->mask provenance record (MF-END-12).

        The record binds the decoded frame path and selection frame index to
        the produced mask: shape, granted area and the mask's packed-bit
        sha256 — the same digest convention the role-track artifact uses, so a
        downstream track observation can be traced back to this call.
        """
        mask = self.preview_mask(frame_path, selection, backend=backend)
        mask_u8 = np.asarray(mask)
        binary = mask_u8 > 127
        record: dict[str, object] = {
            "backend": backend,
            "frame_path": str(frame_path),
            "frame_index": int(selection.frame_index),
            "mask_shape": [int(v) for v in mask_u8.shape],
            "mask_area_px": int(np.count_nonzero(binary)),
            "mask_sha256": hashlib.sha256(np.packbits(binary).tobytes()).hexdigest(),
        }
        return mask, record
