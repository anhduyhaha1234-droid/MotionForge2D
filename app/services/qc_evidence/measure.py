"""MF-P1-QC-EVIDENCE — bounded, deterministic measurements over persisted bytes.

All measurements here read ONLY artifacts that :mod:`sources` already
re-verified against the database digest; nothing is invented and no network
or model is touched (the same discipline the W6 detectors follow).

Bounding: every measurement takes an explicit ``max_frames`` window so the
composer can never decode an unbounded amount of media inside a request.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from app.services.qc_evidence.errors import malformed

#: Decode/measure revision — bump when a measurement definition changes.
MEASURE_REVISION = "1.0.0"

#: Hard bound on how many media frames one composition may decode.
MAX_WINDOW_FRAMES = 24

#: Grayscale normalisation used for every luminance/centroid measurement.
GRAY_SCALE = 255.0


def content_digest(value: Any) -> str:
    """sha256 over the canonical JSON of a value (deterministic)."""
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def crop_sha256(pixels: Sequence[Sequence[float]]) -> str:
    """The exact digest convention the W6 crop detectors verify.

    ``identity_drift``/``edge_halo`` hash ``json.dumps(crop["pixels"])`` with
    the default separators — this helper reproduces that byte-for-byte.
    """
    raw = json.dumps([list(row) for row in pixels], separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


def decode_png_gray(data: bytes, *, detector: str) -> tuple[list[list[float]], int, int]:
    """Decode mask/asset PNG bytes into a 0..255 grayscale matrix."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            gray = image.convert("L")
            width, height = gray.size
            matrix = np.asarray(gray, dtype=np.float64)
    except Exception as exc:
        raise malformed(
            detector, f"persisted PNG bytes are undecodable: {exc}"
        ) from exc
    if width < 1 or height < 1 or matrix.size == 0:
        raise malformed(
            detector, "persisted PNG decodes to an empty image (fail closed)"
        )
    return matrix.tolist(), int(width), int(height)


def mask_bbox(matrix: Sequence[Sequence[float]]) -> tuple[int, int, int, int]:
    """Bounding box (x0, y0, x1, y1) of the NON-ZERO mask pixels (x1/y1 excl)."""
    block = np.asarray(matrix, dtype=np.float64) > 0.0
    if not block.any():
        raise malformed(
            "qc_evidence",
            "persisted mask artifact contains no non-zero pixels — an empty "
            "mask carries no geometry to judge",
        )
    rows = np.any(block, axis=1)
    cols = np.any(block, axis=0)
    y0, y1 = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]))
    x0, x1 = int(np.argmax(cols)), int(len(cols) - np.argmax(cols[::-1]))
    return x0, y0, x1, y1


def mask_area(matrix: Sequence[Sequence[float]]) -> int:
    return int((np.asarray(matrix, dtype=np.float64) > 0.0).sum())


def disc_radius_px(area: int) -> float:
    """Equivalent radius of a filled disc of ``area`` pixels (T06A2 geometry)."""
    if area <= 0:
        raise malformed("edge_halo", "expected mask has zero area")
    return float(math.sqrt(float(area) / math.pi))


def decode_video_frames(
    path: Path, frame_indices: Sequence[int], *, detector: str
) -> dict[int, list[list[float]]]:
    """Decode specific frames of a persisted media artifact as gray matrices.

    Bounded by :data:`MAX_WINDOW_FRAMES`.  Missing frames are OMITTED from the
    result (the caller decides whether the omission is a refusal).
    """
    import cv2  # local import: only the measurement path needs OpenCV

    wanted = sorted({int(i) for i in frame_indices})[:MAX_WINDOW_FRAMES]
    if not wanted:
        return {}
    out: dict[int, list[list[float]]] = {}
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise malformed(
            detector,
            f"persisted media artifact {path.name!r} cannot be decoded "
            "(no readable video stream)",
        )
    try:
        for index in wanted:
            capture.set(cv2.CAP_PROP_POS_FRAMES, float(index))
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            out[index] = np.asarray(gray, dtype=np.float64).tolist()
    finally:
        capture.release()
    return out


def frame_luminance(frames: dict[int, list[list[float]]]) -> dict[int, float]:
    """Per-frame mean grayscale (0..255), rounded to 9 dp (deterministic)."""
    return {
        int(index): round(float(np.asarray(matrix, dtype=np.float64).mean()), 9)
        for index, matrix in sorted(frames.items())
    }


def crop_region(
    matrix: Sequence[Sequence[float]],
    bbox: tuple[int, int, int, int],
) -> list[list[float]]:
    """Crop a gray matrix to ``bbox`` (clipped to the matrix bounds)."""
    array = np.asarray(matrix, dtype=np.float64)
    x0, y0, x1, y1 = bbox
    height, width = array.shape[:2]
    x0 = max(0, min(int(x0), width - 1))
    x1 = max(x0 + 1, min(int(x1), width))
    y0 = max(0, min(int(y0), height - 1))
    y1 = max(y0 + 1, min(int(y1), height))
    return array[y0:y1, x0:x1].tolist()


def changed_centroid_x(
    source: Sequence[Sequence[float]],
    rendered: Sequence[Sequence[float]],
    *,
    threshold: float = 8.0,
) -> float | None:
    """Column centroid of the pixels that differ between two same-size frames.

    This is the measured placement of whatever the render actually composited
    inside the frame: no assumption about the layer is made beyond "the bytes
    differ there".  Returns ``None`` when nothing changed (no rendered delta).
    """
    a = np.asarray(source, dtype=np.float64)
    b = np.asarray(rendered, dtype=np.float64)
    if a.shape != b.shape:
        raise malformed(
            "trajectory_drift",
            f"source frame {a.shape} and render frame {b.shape} have "
            "different geometry",
        )
    changed = np.abs(a - b) >= float(threshold)
    if not changed.any():
        return None
    cols = np.where(changed.any(axis=0))[0]
    weights = changed.sum(axis=0)[cols].astype(np.float64)
    columns = cols.astype(np.float64)
    return float((columns * weights).sum() / weights.sum())


def window_indices(start: int, end: int, *, limit: int = MAX_WINDOW_FRAMES) -> list[int]:
    """Evenly spaced frame indices inside ``[start, end]`` (bounded)."""
    if end < start:
        raise malformed(
            "qc_evidence", f"window {start}..{end} is inverted (fail closed)"
        )
    span = end - start + 1
    if span <= limit:
        return list(range(start, end + 1))
    step = span / float(limit)
    return sorted({start + int(i * step) for i in range(limit)})


def crop_revision(pixels: Sequence[Sequence[float]]) -> str:
    """Short content-derived crop revision (pins the exact crop payload)."""
    return crop_sha256(pixels)[:16]
