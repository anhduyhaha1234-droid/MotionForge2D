"""Character pack validation engine (S06-T03, corrected).

Validates a character pack version before publication.  The repository
publish gate (:meth:`app.persistence.characters.CharacterRepository.
publish_pack_version`) calls :func:`validate_character_pack`, so an invalid
pack cannot publish — neither through the API nor through a direct service
call.

Checks performed per pose asset:

- Six core pose slot completeness (``front``, ``three_quarter``, ``side``,
  ``back``, ``sitting``, ``walking``).
- The pose slot is linked to an ``Artifact`` row that is in state
  ``ready`` and carries checksum/size metadata.
- The managed file exists on disk under the configured storage root.
- The on-disk byte size matches the registered size.
- The on-disk SHA-256 matches the registered checksum.
- The file decodes as an image.
- The image has an alpha channel (transparency policy).
- The image meets the minimum resolution policy.

Validation returns a list of human-readable error strings; an empty list
means the pack is publishable.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.persistence.artifacts import ManagedPathError, ManagedRoot, hash_file
from app.persistence.characters import AssetRecord, PackVersionRecord
from app.persistence.models import CORE_POSE_SLOTS

#: Minimum width (px) required for a publishable pose asset.
MIN_POSE_WIDTH = 128

#: Minimum height (px) required for a publishable pose asset.
MIN_POSE_HEIGHT = 128

#: Pose assets must carry REAL transparency — at least one effective alpha
#: pixel below 255 — so they can be composited over arbitrary scenes without
#: a hard opaque box (character-library contract).  An RGBA/LA image whose
#: every alpha pixel is fully opaque is rejected even though its mode is
#: alpha-capable.
REQUIRE_ALPHA_CHANNEL = True


def validate_character_pack(
    version: PackVersionRecord, storage_root: Path | None = None
) -> list[str]:
    """Validate completeness and asset quality of a character pack version.

    Args:
        version: PackVersionRecord to validate.
        storage_root: Root path for managed storage artifacts.  Defaults to
            ``Path("artifacts")`` (the importer/repository default).

    Returns:
        List of validation error strings.  Empty list indicates the pack is
        publishable.
    """
    errors: list[str] = []

    if storage_root is None:
        storage_root = Path("artifacts")
    managed = ManagedRoot(storage_root)

    attached_slots = {asset.pose_slot: asset for asset in version.assets}

    # 1. Core pose slot completeness
    missing_slots = [slot for slot in CORE_POSE_SLOTS if slot not in attached_slots]
    if missing_slots:
        errors.append(
            f"Missing required core pose slots: {', '.join(sorted(missing_slots))}"
        )

    # 2. Per-asset integrity (canonical slot order keeps messages stable)
    for slot in CORE_POSE_SLOTS:
        asset = attached_slots.get(slot)
        if asset is None:
            continue
        errors.extend(_validate_asset(slot, asset, managed))

    return errors


def is_pack_publishable(
    version: PackVersionRecord, storage_root: Path | None = None
) -> bool:
    """Return True if character pack version satisfies all publish criteria."""
    return len(validate_character_pack(version, storage_root)) == 0


def _validate_asset(slot: str, asset: AssetRecord, managed: ManagedRoot) -> list[str]:
    """Validate one pose asset against its Artifact row and managed file."""
    errors: list[str] = []

    if not asset.artifact_id:
        errors.append(f"Pose slot '{slot}' is not linked to an artifact")
        return errors

    if not asset.artifact_state:
        errors.append(f"Pose slot '{slot}' artifact has no state (missing Artifact row)")
        return errors
    if asset.artifact_state != "ready":
        errors.append(
            f"Pose slot '{slot}' artifact is not in ready state "
            f"(state={asset.artifact_state!r})"
        )

    if not asset.artifact_relative_path:
        errors.append(f"Pose slot '{slot}' artifact has no relative path")
        return errors

    try:
        path = managed.resolve(asset.artifact_relative_path)
    except ManagedPathError as exc:
        errors.append(
            f"Pose slot '{slot}' artifact path escapes managed storage: {exc}"
        )
        return errors

    if not path.is_file():
        errors.append(
            f"Pose slot '{slot}' artifact file missing on disk: "
            f"{asset.artifact_relative_path}"
        )
        return errors

    stat = path.stat()
    if asset.artifact_size_bytes is None:
        errors.append(f"Pose slot '{slot}' artifact is missing its size")
    elif stat.st_size != asset.artifact_size_bytes:
        errors.append(
            f"Pose slot '{slot}' size mismatch: registered "
            f"{asset.artifact_size_bytes} bytes, on disk {stat.st_size} bytes"
        )

    if not asset.artifact_sha256:
        errors.append(f"Pose slot '{slot}' artifact is missing its SHA-256 checksum")
    else:
        actual_sha256 = hash_file(path)
        if actual_sha256 != asset.artifact_sha256:
            errors.append(
                f"Pose slot '{slot}' SHA-256 mismatch: registered "
                f"{asset.artifact_sha256[:12]}..., on disk {actual_sha256[:12]}..."
            )

    errors.extend(_validate_image(slot, path))
    return errors


def _validate_image(slot: str, path: Path) -> list[str]:
    """Decode *path* as an image and apply transparency/resolution policies."""
    errors: list[str] = []
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            if REQUIRE_ALPHA_CHANNEL and not _has_real_transparency(img):
                errors.append(
                    f"Pose slot '{slot}' image has no real transparency "
                    f"(mode={img.mode!r}, every effective alpha pixel is fully opaque)"
                )
            if width < MIN_POSE_WIDTH or height < MIN_POSE_HEIGHT:
                errors.append(
                    f"Pose slot '{slot}' image resolution {width}x{height} is below "
                    f"the required {MIN_POSE_WIDTH}x{MIN_POSE_HEIGHT}"
                )
    except Exception as exc:  # noqa: BLE001 - decode failure is a validation error
        errors.append(f"Pose slot '{slot}' file is not a decodable image: {exc}")
    return errors


def _has_real_transparency(img: Image.Image) -> bool:
    """Return True only if at least one RENDERED pixel has alpha < 255.

    Mode alone is not enough, and neither is the presence of a declared
    palette transparency entry: an RGBA image whose alpha channel is 255
    everywhere is alpha-capable but fully opaque, and a P image may declare
    a transparent palette index that no pixel actually uses.

    The safe check converts the image to RGBA (applying the palette and any
    tRNS transparency) and inspects the effective alpha-channel extrema.
    Returns True iff the minimum rendered alpha is below 255.
    """
    try:
        rgba = img.convert("RGBA")
        low, _high = rgba.getchannel("A").getextrema()
        low_value = float(low[0]) if isinstance(low, tuple) else float(low)
        return low_value < 255
    except Exception:  # noqa: BLE001 - treat unreadable alpha as opaque
        return False
