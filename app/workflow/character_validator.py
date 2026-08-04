"""Character pack validation engine (S06-T03).

Validates character pack pose completeness and asset quality before a pack
version may be published:

- Completeness of the 6 required core pose slots (``front``, ``three_quarter``,
  ``side``, ``back``, ``sitting``, ``walking``).
- Asset file integrity: the pose slot is linked to a ``ready`` Artifact whose
  managed file exists on disk, is non-empty, and whose registered size/SHA-256
  still match the bytes on disk.
- Image quality: minimum edge resolution (default 512x512), an RGBA alpha
  channel (transparency), and a sane aspect ratio.

The publish gate in ``CharacterRepository.publish_pack_version`` calls
:func:`validate_character_pack` and refuses to publish while any error is
reported.

Record-level checks (slot completeness, artifact linking) always run.  File
and image checks require a database ``Session`` so the validator can resolve
each ``Artifact`` row (relative path / size / checksum) and a ``storage_root``
so managed files can be located.  The repository supplies both during publish;
callers without a session only get record-level validation.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.artifacts import ManagedRoot, hash_file
from app.persistence.characters import AssetRecord, PackVersionRecord
from app.persistence.models import CORE_POSE_SLOTS, Artifact

#: Default managed storage root when none is supplied (matches
#: ``JobService``/``CharacterPresetImporter`` defaults).
DEFAULT_STORAGE_ROOT = "artifacts"
#: Default minimum edge length (px) for a publishable pose asset.
DEFAULT_MIN_DIMENSION = 512
#: Default maximum width/height ratio tolerated for a pose asset.
DEFAULT_MAX_ASPECT_RATIO = 4.0


def validate_character_pack(
    version: PackVersionRecord,
    session: Session | None = None,
    storage_root: Path | None = None,
    min_dimension: int = DEFAULT_MIN_DIMENSION,
    max_aspect_ratio: float = DEFAULT_MAX_ASPECT_RATIO,
) -> list[str]:
    """Validate completeness and asset quality of a character pack version.

    Args:
        version: PackVersionRecord to validate.
        session: Optional DB session used to resolve Artifact metadata and
            perform file/image checks.  When ``None`` only record-level
            checks (core slot completeness, artifact linking) are performed.
        storage_root: Root of the managed artifact tree.  Defaults to
            ``artifacts`` (the same default as ``JobService`` and
            ``CharacterPresetImporter``).
        min_dimension: Minimum allowed width and height in pixels.
        max_aspect_ratio: Maximum tolerated ratio between the longer and
            shorter image edge.

    Returns:
        List of validation error strings.  Empty list indicates the pack
        version satisfies every publish criterion.
    """
    errors: list[str] = []
    attached = {asset.pose_slot: asset for asset in version.assets}

    # 1. Core pose slot completeness
    missing_slots = [slot for slot in CORE_POSE_SLOTS if slot not in attached]
    if missing_slots:
        errors.append(
            f"Missing required core pose slots: {', '.join(sorted(missing_slots))}"
        )

    # 2. Asset file integrity and image quality
    if session is None:
        for slot in CORE_POSE_SLOTS:
            asset = attached.get(slot)
            if asset is not None and not asset.artifact_id:
                errors.append(f"Pose slot '{slot}' is not linked to an artifact")
        return errors

    managed = ManagedRoot(storage_root or Path(DEFAULT_STORAGE_ROOT))
    artifacts = _load_artifacts(
        session, [asset.artifact_id for asset in attached.values() if asset.artifact_id]
    )
    for slot in CORE_POSE_SLOTS:
        asset = attached.get(slot)
        if asset is None:
            continue
        errors.extend(
            _validate_asset(
                slot,
                asset,
                artifacts,
                managed,
                min_dimension=min_dimension,
                max_aspect_ratio=max_aspect_ratio,
            )
        )
    return errors


def is_pack_publishable(
    version: PackVersionRecord,
    session: Session | None = None,
    storage_root: Path | None = None,
    min_dimension: int = DEFAULT_MIN_DIMENSION,
    max_aspect_ratio: float = DEFAULT_MAX_ASPECT_RATIO,
) -> bool:
    """Return True if character pack version satisfies all publish criteria."""
    return (
        len(
            validate_character_pack(
                version,
                session=session,
                storage_root=storage_root,
                min_dimension=min_dimension,
                max_aspect_ratio=max_aspect_ratio,
            )
        )
        == 0
    )


def _load_artifacts(
    session: Session, artifact_ids: list[str]
) -> dict[str, Artifact]:
    """Load Artifact rows by id; missing rows are simply absent from the map."""
    if not artifact_ids:
        return {}
    rows = session.scalars(
        select(Artifact).where(Artifact.id.in_(artifact_ids))
    ).all()
    return {art.id: art for art in rows}


def _validate_asset(
    slot: str,
    asset: AssetRecord,
    artifacts: dict[str, Artifact],
    managed: ManagedRoot,
    *,
    min_dimension: int,
    max_aspect_ratio: float,
) -> list[str]:
    """Validate a single attached pose asset (file + image quality)."""
    errors: list[str] = []

    if not asset.artifact_id:
        return [f"Pose slot '{slot}' is not linked to an artifact"]

    art = artifacts.get(asset.artifact_id)
    if art is None:
        return [f"Pose slot '{slot}' references missing artifact {asset.artifact_id}"]

    if art.state != "ready":
        errors.append(
            f"Pose slot '{slot}' artifact is not in ready state (state={art.state})"
        )

    try:
        path = managed.resolve(art.relative_path)
    except ValueError as exc:
        errors.append(f"Pose slot '{slot}' artifact path is invalid: {exc}")
        return errors

    if not path.is_file():
        errors.append(
            f"Pose slot '{slot}' artifact file is missing on disk: {art.relative_path}"
        )
        return errors

    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        errors.append(f"Pose slot '{slot}' artifact file is empty (0 bytes)")
        return errors

    if art.size_bytes is not None and art.size_bytes != size_bytes:
        errors.append(
            f"Pose slot '{slot}' artifact size mismatch: "
            f"registered {art.size_bytes} bytes, disk has {size_bytes}"
        )

    if art.sha256:
        actual = hash_file(path)
        if actual != art.sha256:
            errors.append(
                f"Pose slot '{slot}' artifact checksum mismatch: "
                f"registered {art.sha256}, disk has {actual}"
            )

    image = _read_image(path)
    if image is None:
        errors.append(f"Pose slot '{slot}' file is not a readable image")
        return errors

    height, width = image.shape[:2]
    if width < min_dimension or height < min_dimension:
        errors.append(
            f"Pose slot '{slot}' resolution {width}x{height} is below the "
            f"minimum {min_dimension}x{min_dimension}"
        )

    channels = image.shape[2] if image.ndim == 3 else 1
    if channels != 4:
        errors.append(
            f"Pose slot '{slot}' image lacks alpha channel "
            f"(expected RGBA, got {channels} channel(s))"
        )

    if width > 0 and height > 0:
        ratio = max(width, height) / min(width, height)
        if ratio > max_aspect_ratio:
            errors.append(
                f"Pose slot '{slot}' aspect ratio {width}x{height} "
                f"exceeds {max_aspect_ratio}:1"
            )

    return errors


def _read_image(path: Path) -> np.ndarray | None:
    """Decode an image file with cv2, or None when it is not a readable image.

    Uses ``np.fromfile`` + ``cv2.imdecode`` so non-ASCII Windows paths work
    (``cv2.imread`` cannot open such paths).
    """
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
