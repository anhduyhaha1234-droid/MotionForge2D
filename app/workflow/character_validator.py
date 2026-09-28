"""Character pack validation engine (S06-T03, corrected; reference branch MF-END-04).

Validates a character pack version before publication.  The repository
publish gate (:meth:`app.persistence.characters.CharacterRepository.
publish_pack_version`) calls :func:`validate_character_pack`, so an invalid
pack cannot publish — neither through the API nor through a direct service
call.

TWO CONTRACT BRANCHES — the branch is DATA (``character_pack_version.
pack_contract_version``), never a universal constant:

``legacy_six_slot_2d`` (every pre-existing row) — the LEGACY contract, kept
unchanged.  Checks performed per pose asset:

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

``reference_pack_v1`` (MF-END-04) — validation follows the pack's FROZEN
requirement manifest (``requirement_manifest_json`` +
``requirement_manifest_sha256``); ``CORE_POSE_SLOTS`` completeness is never
demanded of this branch and the wording "pose" never appears in its
refusals:

- Manifest integrity first: the stored text must parse as a JSON object, its
  recomputed SHA-256 must equal the recorded hash, the manifest version must
  be supported and its declared contract must match the version's branch.
  Any failure fails the pack closed.
- Every declared requirement is a reference key ``<view>@<role>`` (the
  frozen ingest grammar, re-validated here).  Each required key must be
  attached; a refusal names the EXACT missing view/key.  Duplicate
  requirement keys are refused.
- Per-asset integrity is the same policies as legacy (ready state, managed
  path, size/checksum, decode, minimum resolution) with reference-key
  wording; real transparency is required ONLY where the requirement
  declares ``alpha: true`` (alpha policy per asset requirement).  A
  single-channel greyscale (mask) representation never satisfies a
  reference requirement, and authored artwork must decode to RGB or RGBA
  (mask/artwork boundary).
- Every claimed engine capability must be an accepted capability and must
  meet the pinned capability floor (``ENGINE_REFERENCE_MINIMA_PIN``, read
  from ``app.schemas.shot_reskin`` — the mirror of the accepted
  ``media_engine.CAPABILITY_REFERENCE_REQUIREMENTS``): at least the minimum
  number of roles carrying the minimum number of INDEPENDENT references
  (distinct artifact SHA-256) each.  A declaration may select or add
  requirements, never lower a minimum to pass.

Validation returns a list of human-readable error strings; an empty list
means the pack is publishable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.persistence.artifacts import ManagedPathError, ManagedRoot, hash_file
from app.persistence.characters import AssetRecord, PackVersionRecord
from app.persistence.models import (
    CORE_POSE_SLOTS,
    PACK_CONTRACT_VERSION_LEGACY,
    PACK_CONTRACT_VERSION_REFERENCE,
)

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


# ── reference-pack branch (MF-END-04) ─────────────────────────────────────────

#: Manifest versions this validator can consume (``manifest_version`` field).
REFERENCE_MANIFEST_VERSIONS_SUPPORTED = (1,)

#: Decoded representations admitted as authored reference artwork (the frozen
#: ingest admission: PNG colour type 2/6; a mask is never artwork).
ACCEPTED_ARTWORK_MODES = frozenset({"RGB", "RGBA"})

#: Decoded modes of the single-channel greyscale family (the mask payload).
MASK_DECODED_MODES = frozenset({"L", "1"})


@dataclass(frozen=True)
class PackContractBranch:
    """The branch declaration read from ``character_pack_version``."""

    pack_contract_version: str
    requirement_manifest_json: str | None = None
    requirement_manifest_sha256: str | None = None


@dataclass(frozen=True)
class ReferenceRequirement:
    """One declared requirement: a reference key plus its asset requirement.

    ``alpha_required`` is the per-asset transparency policy of this key —
    ``True`` (the default when a bare key string is declared) means the
    attached artwork must carry REAL transparency; ``False`` admits an
    opaque RGB reference (e.g. an original identity image).
    """

    key: str
    view: str
    role: str
    alpha_required: bool


@dataclass(frozen=True)
class ReferenceManifest:
    """Parsed reference manifest; integrity failures are returned as errors."""

    manifest_version: int | None
    capabilities: tuple[str, ...]
    requirements: tuple[ReferenceRequirement, ...]
    errors: list[str] = field(default_factory=list)


def _capability_pins() -> tuple[tuple[str, ...], dict[str, tuple[int, int]]]:
    """Pinned engine capability vocabulary + floor (single tree authority).

    Read from ``app.schemas.shot_reskin`` (MF-END-01), whose
    ``ENGINE_REFERENCE_MINIMA_PIN`` mirrors the accepted
    ``media_engine.CAPABILITY_REFERENCE_REQUIREMENTS``; the media-engine
    module itself is not present in this tree.
    """
    from app.schemas.shot_reskin import (  # noqa: PLC0415
        ENGINE_CAPABILITY_PINS,
        ENGINE_REFERENCE_MINIMA_PIN,
    )

    return tuple(ENGINE_CAPABILITY_PINS), dict(ENGINE_REFERENCE_MINIMA_PIN)


def _empty_reference_manifest(error: str) -> ReferenceManifest:
    return ReferenceManifest(
        manifest_version=None, capabilities=(), requirements=(), errors=[error]
    )


def parse_reference_manifest(branch: PackContractBranch) -> ReferenceManifest:
    """Parse + integrity-check the reference manifest of *branch*.

    Never raises for manifest CONTENT problems: every integrity failure is
    returned as an error string so publish/validation can report the exact
    reason and fail closed.  The parsed requirements/capabilities are only
    meaningful when ``errors`` is empty.
    """
    from app.workflow.character_reference_ingest import (  # noqa: PLC0415
        ReferenceKeyRefusedError,
        validate_reference_key,
    )

    text = branch.requirement_manifest_json
    if text is None or text.strip() == "":
        return _empty_reference_manifest(
            "Reference manifest is missing for a reference_pack_v1 version"
        )

    recomputed = hashlib.sha256(text.encode("utf-8")).hexdigest()
    recorded = branch.requirement_manifest_sha256
    if recorded is None or recorded.strip().lower() != recomputed:
        return _empty_reference_manifest(
            "Reference manifest SHA-256 mismatch: recorded "
            f"{str(recorded)[:12]}..., recomputed {recomputed[:12]}..."
        )

    try:
        payload = json.loads(text)
    except ValueError as exc:
        return _empty_reference_manifest(f"Reference manifest is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        return _empty_reference_manifest(
            f"Reference manifest must be a JSON object, got {type(payload).__name__}"
        )

    errors: list[str] = []
    version = payload.get("manifest_version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in REFERENCE_MANIFEST_VERSIONS_SUPPORTED
    ):
        errors.append(
            f"Unsupported reference manifest version {version!r}; supported: "
            f"{list(REFERENCE_MANIFEST_VERSIONS_SUPPORTED)}"
        )
    declared_contract = payload.get("pack_contract")
    if declared_contract != PACK_CONTRACT_VERSION_REFERENCE:
        errors.append(
            f"Reference manifest pack_contract {declared_contract!r} does not "
            f"match the version branch {PACK_CONTRACT_VERSION_REFERENCE!r}"
        )

    accepted: tuple[str, ...] = ()
    try:
        accepted, _floor = _capability_pins()
    except Exception as exc:  # noqa: BLE001 - missing profile fails the pack closed
        errors.append(f"Engine capability profile unavailable: {exc}")

    capabilities: list[str] = []
    raw_caps = payload.get("capabilities", [])
    if not isinstance(raw_caps, list) or any(
        not isinstance(cap, str) for cap in raw_caps
    ):
        errors.append(
            "Reference manifest capabilities must be a list of capability names"
        )
        raw_caps = []
    for cap in raw_caps:
        if cap not in accepted:
            errors.append(
                f"Reference manifest claims unknown engine capability {cap!r}; "
                f"accepted: {list(accepted)}"
            )
        elif cap not in capabilities:
            capabilities.append(cap)

    requirements: list[ReferenceRequirement] = []
    seen_keys: set[str] = set()
    raw_reqs = payload.get("requirements")
    if not isinstance(raw_reqs, list) or not raw_reqs:
        errors.append(
            "Reference manifest requirements must be a non-empty list of "
            "entries ('<view>@<role>' strings or {'key','alpha'} objects)"
        )
        raw_reqs = []
    for index, entry in enumerate(raw_reqs):
        if isinstance(entry, str):
            key, alpha_required = entry, True
        elif isinstance(entry, dict):
            key = entry.get("key")
            alpha = entry.get("alpha", True)
            if not isinstance(key, str) or not isinstance(alpha, bool):
                errors.append(
                    f"Reference manifest requirement #{index} must be "
                    "{'key': str, 'alpha': bool}"
                )
                continue
            alpha_required = alpha
        else:
            errors.append(
                f"Reference manifest requirement #{index} has unsupported type "
                f"{type(entry).__name__}; use a '<view>@<role>' string or a "
                "{'key','alpha'} object"
            )
            continue
        try:
            view, role = validate_reference_key(key)
        except ReferenceKeyRefusedError as exc:
            errors.append(f"Reference requirement key {key!r} is invalid: {exc}")
            continue
        if key in seen_keys:
            errors.append(f"Duplicate reference requirement key {key!r} in the manifest")
            continue
        seen_keys.add(key)
        requirements.append(
            ReferenceRequirement(
                key=key, view=view, role=role, alpha_required=alpha_required
            )
        )

    return ReferenceManifest(
        manifest_version=version if isinstance(version, int) else None,
        capabilities=tuple(capabilities),
        requirements=tuple(requirements),
        errors=errors,
    )


def reference_pack_completeness(
    version: PackVersionRecord, manifest: ReferenceManifest
) -> tuple[bool, list[str]]:
    """Return ``(complete, missing_keys)`` for the reference branch.

    ``complete`` is TRUE only when the required reference set is knowable
    (the manifest passed integrity) AND every declared requirement key is
    attached.  An attached-but-invalid asset does NOT make the pack
    incomplete: completeness and validation validity are separate answers
    and are never conflated (a pack can be complete and still fail).
    """
    if manifest.errors:
        return False, []
    attached = {asset.pose_slot for asset in version.assets}
    missing = [req.key for req in manifest.requirements if req.key not in attached]
    return (not missing), missing


def validate_character_pack(
    version: PackVersionRecord,
    storage_root: Path | None = None,
    *,
    branch: PackContractBranch | None = None,
) -> list[str]:
    """Validate *version* against its declared contract branch.

    ``branch=None`` (or the legacy contract) keeps the legacy six-slot
    behaviour EXACTLY.  ``reference_pack_v1`` validates against the frozen
    requirement manifest instead of ``CORE_POSE_SLOTS``.
    """
    if storage_root is None:
        storage_root = Path("artifacts")
    managed = ManagedRoot(storage_root)

    if branch is None:
        branch = PackContractBranch(
            pack_contract_version=PACK_CONTRACT_VERSION_LEGACY
        )
    if branch.pack_contract_version == PACK_CONTRACT_VERSION_LEGACY:
        return _validate_legacy_pack(version, managed)
    if branch.pack_contract_version == PACK_CONTRACT_VERSION_REFERENCE:
        return _validate_reference_pack(version, managed, branch)
    return [
        f"Unknown pack contract branch {branch.pack_contract_version!r}; "
        f"supported: {[PACK_CONTRACT_VERSION_LEGACY, PACK_CONTRACT_VERSION_REFERENCE]}"
    ]


def _validate_legacy_pack(version: PackVersionRecord, managed: ManagedRoot) -> list[str]:
    """The legacy contract gate — behaviour preserved exactly (S06-T03)."""
    errors: list[str] = []

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
    version: PackVersionRecord,
    storage_root: Path | None = None,
    *,
    branch: PackContractBranch | None = None,
) -> bool:
    """Return True if character pack version satisfies all publish criteria."""
    return len(validate_character_pack(version, storage_root, branch=branch)) == 0


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



# ── reference-branch validation (MF-END-04) ───────────────────────────────────


def _validate_reference_pack(
    version: PackVersionRecord, managed: ManagedRoot, branch: PackContractBranch
) -> list[str]:
    """Validate a ``reference_pack_v1`` pack against its frozen manifest."""
    manifest = parse_reference_manifest(branch)
    if manifest.errors:
        return list(manifest.errors)

    errors: list[str] = []
    attached = {asset.pose_slot: asset for asset in version.assets}
    for req in manifest.requirements:
        prefix = f"Reference {req.key!r}"
        asset = attached.get(req.key)
        if asset is None:
            errors.append(
                f"Missing required reference {req.key!r} "
                f"(view {req.view!r}, role {req.role!r})"
            )
            continue
        errors.extend(_validate_reference_asset(prefix, req, asset, managed))
    errors.extend(_capability_floor_errors(manifest, attached))
    return errors


def _capability_floor_errors(
    manifest: ReferenceManifest, attached: dict[str, AssetRecord]
) -> list[str]:
    """Enforce the pinned capability floor for every claimed capability.

    A role qualifies when it carries at least ``refs_min`` INDEPENDENT
    reference pixels (distinct artifact SHA-256 — the same bytes attached
    under two keys are ONE reference).  The declaration must select at least
    ``min_roles`` qualifying roles; it may never lower the minimum to pass.
    """
    if not manifest.capabilities:
        return []
    _accepted, floor = _capability_pins()

    independent: dict[str, set[str]] = {}
    for req in manifest.requirements:
        asset = attached.get(req.key)
        if asset is None:
            continue
        bucket = independent.setdefault(req.role, set())
        if asset.artifact_sha256:
            bucket.add(asset.artifact_sha256.strip().lower())

    errors: list[str] = []
    for cap in manifest.capabilities:
        minima = floor.get(cap)
        if minima is None:
            continue  # already refused by the manifest parser
        min_roles, refs_min = minima
        qualifying = 0
        observed: list[str] = []
        for role, shas in sorted(independent.items()):
            observed.append(f"{role}: {len(shas)}")
            if len(shas) >= refs_min:
                qualifying += 1
        if qualifying < min_roles:
            errors.append(
                f"Capability {cap!r} requires at least {min_roles} role(s) "
                f"with >= {refs_min} independent reference(s) each; declared "
                f"roles carry [{', '.join(observed) or 'none'}]"
            )
    return errors


def _validate_reference_asset(
    prefix: str, req: ReferenceRequirement, asset: AssetRecord, managed: ManagedRoot
) -> list[str]:
    """Validate one required reference asset against its Artifact row."""
    errors: list[str] = []

    if not asset.artifact_id:
        errors.append(f"{prefix} is not linked to an artifact")
        return errors

    if not asset.artifact_state:
        errors.append(f"{prefix} artifact has no state (missing Artifact row)")
        return errors
    if asset.artifact_state != "ready":
        errors.append(
            f"{prefix} artifact is not in ready state (state={asset.artifact_state!r})"
        )

    if not asset.artifact_relative_path:
        errors.append(f"{prefix} artifact has no relative path")
        return errors

    try:
        path = managed.resolve(asset.artifact_relative_path)
    except ManagedPathError as exc:
        errors.append(f"{prefix} artifact path escapes managed storage: {exc}")
        return errors

    if not path.is_file():
        errors.append(
            f"{prefix} artifact file missing on disk: {asset.artifact_relative_path}"
        )
        return errors

    stat = path.stat()
    if asset.artifact_size_bytes is None:
        errors.append(f"{prefix} artifact is missing its size")
    elif stat.st_size != asset.artifact_size_bytes:
        errors.append(
            f"{prefix} size mismatch: registered "
            f"{asset.artifact_size_bytes} bytes, on disk {stat.st_size} bytes"
        )

    if not asset.artifact_sha256:
        errors.append(f"{prefix} artifact is missing its SHA-256 checksum")
    else:
        actual_sha256 = hash_file(path)
        if actual_sha256 != asset.artifact_sha256:
            errors.append(
                f"{prefix} SHA-256 mismatch: registered "
                f"{asset.artifact_sha256[:12]}..., on disk {actual_sha256[:12]}..."
            )

    errors.extend(
        _validate_reference_image(prefix, path, alpha_required=req.alpha_required)
    )
    return errors


def _validate_reference_image(
    prefix: str, path: Path, *, alpha_required: bool
) -> list[str]:
    """Decode *path* and apply the per-requirement asset policies."""
    errors: list[str] = []
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            mode = img.mode
            artwork_error = _artwork_representation_error(prefix, mode)
            if artwork_error is not None:
                errors.append(artwork_error)
            elif alpha_required and not _has_real_transparency(img):
                errors.append(
                    f"{prefix} image has no real transparency while the "
                    f"requirement declares alpha: true "
                    f"(mode={mode!r}, every effective alpha pixel is fully opaque)"
                )
            if width < MIN_POSE_WIDTH or height < MIN_POSE_HEIGHT:
                errors.append(
                    f"{prefix} image resolution {width}x{height} is below "
                    f"the required {MIN_POSE_WIDTH}x{MIN_POSE_HEIGHT}"
                )
    except Exception as exc:  # noqa: BLE001 - decode failure is a validation error
        errors.append(f"{prefix} file is not a decodable image: {exc}")
    return errors


def _artwork_representation_error(prefix: str, mode: str) -> str | None:
    """Refuse a decoded representation that is not authored RGB/RGBA artwork.

    The mask/artwork boundary is frozen (never converted): a single-channel
    greyscale payload stays a mask and never satisfies a reference
    requirement, whatever the requirement's alpha policy says.
    """
    if mode in ACCEPTED_ARTWORK_MODES:
        return None
    if mode in MASK_DECODED_MODES:
        return (
            f"{prefix} decodes to a single-channel greyscale representation "
            f"(mode={mode!r}): a mask is not authored artwork"
        )
    return f"{prefix} decodes to mode {mode!r}; authored artwork must be RGB or RGBA"

