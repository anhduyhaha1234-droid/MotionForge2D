"""Authored reference-artwork ingest for a draft CharacterPackVersion (MF-END-03).

Public surface (implemented on the EXISTING durable-characters router, so
``app/api/app.py`` stays untouched)::

    POST /api/v2/characters/versions/{version_id}/reference-artwork
    multipart: file=<UploadFile>, reference_key=<str>, purpose=<str, default artwork>

Why this exists (measured D0-02/D2-01): a ready ``Artifact`` can already be
attached to a pack version (``POST /versions/{id}/assets``), but until now **no
public route CREATES an authored artwork artifact**.  The real extraction
provider publishes a segmentation candidate mask as PNG colour type 0 / PIL
mode ``L`` (no alpha) — correct for segmentation and refused by the pack
publish validator, which is exactly right.  The fix is a real artwork ingest,
never a mask conversion.

Boundaries (frozen, do not weaken):

* **A mask stays a mask.**  A single-channel greyscale payload (mode ``L`` /
  ``1``, PNG colour type 0) is REFUSED as artwork with a typed refusal, is
  never converted, and its bytes are never written to managed storage.
* **Admission is decided by decoded bytes + declared purpose + the pack
  contract** — never by the file extension and never by a "the pixels look
  grey" heuristic.  Accepted decoded colour representations are exactly RGB
  and RGBA; an RGB payload whose channels happen to be equal is still authored
  artwork.
* **Reference pixels ride the EXISTING ``character_asset`` rows** under the
  namespaced reference key ``<view>@<role>`` (e.g. ``front@character``) — no
  second store, no new column, no migration (``pose_slot`` carries only
  length/uniqueness CHECKs).

Verification chain (lifted from the strongest existing public upload path,
``app/api/routes/projects.py::upload_replacement``):

1. ``reference_key`` grammar + declared purpose + the client filename are
   validated BEFORE any write;
2. the pack version is resolved workspace-scoped and must be a DRAFT, BEFORE
   any write;
3. the body is read with a hard byte ceiling (``ReferenceArtworkTooLargeError``);
4. magic prefilter + FULL Pillow decode + dimension/pixel caps
   (``app.services.media_validation.probe_image``);
5. the decoded representation must agree with the container header and be
   RGB/RGBA (typed refusal otherwise);
6. ONE atomic managed write (``ManagedRoot.atomic_write_bytes``) -> ready
   ``Artifact`` row (sha256/size/mime/width/height) -> ``attach_asset`` under
   the namespaced key; any failure discards the bytes this call wrote.

Callers own the database transaction (this module never commits), mirroring
``app/persistence/artifacts.py``.  On failure the caller rolls back and calls
:func:`discard_written_files` (the service already self-discards after its own
managed write, so cleanup is idempotent).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from pathlib import Path
from typing import BinaryIO

from PIL import Image
from sqlalchemy.orm import Session

from app.persistence.artifacts import ManagedRoot
from app.persistence.characters import (
    CharacterRepository,
    PackVersionImmutableError,
    PackVersionRecord,
)
from app.persistence.models import CORE_POSE_SLOTS, Artifact
from app.services.media_validation import (
    MediaValidationError,
    probe_image,
)

__all__ = [
    "ACCEPTED_DECODED_MODES",
    "MAX_REFERENCE_KEY_LENGTH",
    "REFERENCE_KEY_SEPARATOR",
    "REFERENCE_ROLES",
    "REFERENCE_VIEWS",
    "ReferenceArtworkIngestResult",
    "ReferenceArtworkPayloadError",
    "ReferenceArtworkRefusedError",
    "ReferenceArtworkTooLargeError",
    "ReferenceFilenameRefusedError",
    "ReferenceIngestError",
    "ReferenceKeyRefusedError",
    "ReferencePurposeRefusedError",
    "discard_written_files",
    "ingest_reference_artwork",
    "validate_reference_key",
    "validate_reference_purpose",
]

#: Namespaced reference-key grammar (measured shape from
#: ``PUBLIC_REFERENCE_INGEST_DELTA_R27.md`` D-3): ``<view>@<role>``.
REFERENCE_KEY_SEPARATOR = "@"

#: Views a reference key may name — the pack contract's measured view
#: vocabulary (``CORE_POSE_SLOTS``); no invented names.
REFERENCE_VIEWS: frozenset[str] = frozenset(CORE_POSE_SLOTS)

#: Roles a reference key may name — the measured character_type vocabulary.
REFERENCE_ROLES: frozenset[str] = frozenset({"character", "prop", "other"})

#: Maximum reference-key length (mirrors CHECK
#: ``ck_character_asset_pose_slot_len``: ``length(pose_slot) <= 64``).
MAX_REFERENCE_KEY_LENGTH = 64

#: Maximum length of one ``<view>`` / ``<role>`` part.
MAX_REFERENCE_KEY_PART_LENGTH = 32

#: Declared purposes accepted as authored artwork.
AUTHORED_ARTWORK_PURPOSES: frozenset[str] = frozenset({"artwork", "reference_artwork"})

#: Decoded PIL modes accepted as authored artwork (RGB colour types 2 and 6).
ACCEPTED_DECODED_MODES: frozenset[str] = frozenset({"RGB", "RGBA"})

#: PIL decoded modes of the single-channel greyscale family — the mask
#: representation (PNG colour type 0) that is never ingested as artwork.
_MASK_DECODED_MODES: frozenset[str] = frozenset({"L", "1"})

#: PNG colour type -> PIL decoded modes that may represent that colour type.
_PNG_MODES_BY_COLOUR_TYPE: dict[int, frozenset[str]] = {
    0: frozenset({"L", "1"}),
    2: frozenset({"RGB"}),
    3: frozenset({"P"}),
    4: frozenset({"LA"}),
    6: frozenset({"RGBA"}),
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_READ_CHUNK_BYTES = 64 * 1024

_PART_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789_"
)


class ReferenceIngestError(ValueError):
    """Base class for typed reference-artwork ingest refusals.

    ``code`` is a class-level default that an instance may specialise (e.g. a
    mask payload vs an unsupported colour type both raise
    :class:`ReferenceArtworkRefusedError` but with distinct codes).
    """

    code = "REFERENCE_INGEST_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details: dict = dict(details or {})


class ReferenceKeyRefusedError(ReferenceIngestError):
    """The reference key is not a valid ``<view>@<role>`` key (422)."""

    code = "REFERENCE_KEY_REFUSED"


class ReferencePurposeRefusedError(ReferenceIngestError):
    """The declared purpose is not authored artwork (422)."""

    code = "INVALID_PURPOSE"


class ReferenceFilenameRefusedError(ReferenceIngestError):
    """The client filename is hostile (separator/traversal/absolute) (422)."""

    code = "REFERENCE_FILENAME_REFUSED"


class ReferenceArtworkPayloadError(ReferenceIngestError):
    """The payload is not a decodable, bounded allowlisted image (415)."""

    code = "REFERENCE_ARTWORK_UNREADABLE"


class ReferenceArtworkTooLargeError(ReferenceArtworkPayloadError):
    """The payload exceeds the configured byte ceiling (413)."""

    code = "REFERENCE_ARTWORK_TOO_LARGE"


class ReferenceArtworkRefusedError(ReferenceIngestError):
    """The payload decodes but is not authored artwork (mask / no colour) (422).

    ``code`` is specialised per refusal so a client can distinguish a mask
    payload (``MASK_PAYLOAD_REFUSED``) from an unsupported colour type
    (``UNSUPPORTED_COLOUR_TYPE``).
    """

    code = "REFERENCE_ARTWORK_REFUSED"


@dataclass(frozen=True)
class ReferenceArtworkIngestResult:
    """Provenance of one successful reference-artwork ingest."""

    asset_id: str
    artifact_id: str
    version_id: str
    character_id: str
    workspace_id: str
    reference_key: str
    view: str
    role: str
    purpose: str
    source_filename: str
    sha256: str
    size_bytes: int
    mime_type: str
    width: int
    height: int
    decoded_mode: str
    colour_type: int | None
    has_alpha: bool
    replaced_existing: bool
    created_at: datetime | None = None


def validate_reference_key(reference_key: str) -> tuple[str, str]:
    """Validate a namespaced reference key and return ``(view, role)``.

    The grammar is the measured/frozen shape ``<view>@<role>`` (delta D-3):
    exactly one ``@``; ``view`` in the pack view vocabulary; ``role`` in
    ``character|prop|other``; each part lowercase ``[a-z][a-z0-9_]*``; total
    length bounded by the ``character_asset.pose_slot`` CHECK (64).

    Raises:
        ReferenceKeyRefusedError: for every malformed/unsafe key, including
            traversal (``..``/separators), absolute forms, whitespace, and
            unknown views/roles.
    """
    if not isinstance(reference_key, str) or reference_key == "":
        raise ReferenceKeyRefusedError("reference_key is required")
    if reference_key != reference_key.strip():
        raise ReferenceKeyRefusedError(
            "reference_key must not carry surrounding whitespace"
        )
    if len(reference_key) > MAX_REFERENCE_KEY_LENGTH:
        raise ReferenceKeyRefusedError(
            f"reference_key must be at most {MAX_REFERENCE_KEY_LENGTH} characters"
        )
    if reference_key.count(REFERENCE_KEY_SEPARATOR) != 1:
        raise ReferenceKeyRefusedError(
            "reference_key must be exactly '<view>@<role>' "
            f"(one {REFERENCE_KEY_SEPARATOR!r})"
        )
    view, role = reference_key.split(REFERENCE_KEY_SEPARATOR)
    for part, label in ((view, "view"), (role, "role")):
        if not part:
            raise ReferenceKeyRefusedError(f"reference_key {label} must not be empty")
        if len(part) > MAX_REFERENCE_KEY_PART_LENGTH:
            raise ReferenceKeyRefusedError(
                f"reference_key {label} must be at most "
                f"{MAX_REFERENCE_KEY_PART_LENGTH} characters"
            )
        if not set(part) <= _PART_ALLOWED or not part[0].isalpha():
            raise ReferenceKeyRefusedError(
                f"reference_key {label} {part!r} must match [a-z][a-z0-9_]* "
                "(no traversal, separators, dots or spaces)"
            )
    if view not in REFERENCE_VIEWS:
        raise ReferenceKeyRefusedError(
            f"reference_key view {view!r} is not in the pack view vocabulary "
            f"{sorted(REFERENCE_VIEWS)}"
        )
    if role not in REFERENCE_ROLES:
        raise ReferenceKeyRefusedError(
            f"reference_key role {role!r} is not one of {sorted(REFERENCE_ROLES)}"
        )
    return view, role


def validate_reference_purpose(purpose: str) -> str:
    """Normalise/validate the declared ingest purpose.

    Only authored-artwork purposes are accepted.  Any mask/segmentation
    purpose is refused with ``MASK_PURPOSE_REFUSED`` — a segmentation mask is
    never ingested as artwork, even when the bytes would decode.

    Raises:
        ReferencePurposeRefusedError: for a mask purpose (mask code) or an
            unknown/empty purpose.
    """
    raw = ("" if purpose is None else str(purpose)).strip().lower()
    if raw == "":
        raise ReferencePurposeRefusedError("purpose must not be empty")
    if raw in AUTHORED_ARTWORK_PURPOSES:
        return raw
    if "mask" in raw or raw in {"matte", "segmentation", "alpha"}:
        raise ReferencePurposeRefusedError(
            f"declared purpose {purpose!r} is a mask/segmentation purpose; "
            "masks are never ingested as authored artwork",
            code="MASK_PURPOSE_REFUSED",
        )
    raise ReferencePurposeRefusedError(
        f"unsupported purpose {purpose!r}; authored artwork ingest accepts "
        f"{sorted(AUTHORED_ARTWORK_PURPOSES)}"
    )


def _sanitize_upload_filename(filename: str | None) -> str:
    """Return the safe single-segment client filename ('' when absent).

    Storage is server-owned; refusing a hostile name is defense in depth
    (mirrors ``_reject_hostile_upload_filename`` in the project routes).
    """
    raw = (filename or "").strip()
    if not raw:
        return ""
    name = raw.replace("\x00", "")
    if "/" in name or "\\" in name or ".." in name or name in (".", ".."):
        raise ReferenceFilenameRefusedError(
            "upload filename must be a single safe segment"
        )
    if Path(name).is_absolute() or PurePath(name).name != name:
        raise ReferenceFilenameRefusedError(
            "upload filename must be a single safe segment"
        )
    return name


def _read_capped(stream: BinaryIO, max_bytes: int) -> bytes:
    """Read *stream* fully, refusing an over-limit or empty payload."""
    if max_bytes <= 0:
        raise ReferenceArtworkPayloadError("max_bytes must be positive")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ReferenceArtworkTooLargeError(
                f"reference artwork exceeds the {max_bytes}-byte limit"
            )
        chunks.append(bytes(chunk))
    data = b"".join(chunks)
    if not data:
        raise ReferenceArtworkPayloadError("empty reference artwork payload")
    return data


def _png_colour_type(data: bytes) -> int | None:
    """PNG IHDR colour type of *data*, or None when not a PNG/IHDR payload."""
    if not data.startswith(_PNG_SIGNATURE):
        return None
    # signature(8) + length(4) + 'IHDR'(4) + width(4) + height(4) + depth(1)
    if len(data) < 26 or data[12:16] != b"IHDR":
        return None
    return int(data[25])


def _decode_representation(data: bytes) -> tuple[str, int | None]:
    """Return ``(decoded_mode, png_colour_type)`` for an already-probed payload."""
    colour_type = _png_colour_type(data)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            mode = str(image.mode)
    except Exception as exc:  # noqa: BLE001 - decode failure fails closed
        raise ReferenceArtworkPayloadError(
            f"reference artwork is not a decodable image: {exc}"
        ) from exc
    return mode, colour_type


def _assert_representation_is_artwork(
    *,
    reference_key: str,
    mode: str,
    colour_type: int | None,
) -> None:
    """Refuse a decoded representation that is not authored RGB/RGBA artwork.

    Raises:
        ReferenceArtworkPayloadError: container header disagrees with the
            decoded mode (inconsistent payload).
        ReferenceArtworkRefusedError: mask representation (code
            ``MASK_PAYLOAD_REFUSED``) or unsupported colour type.
    """
    if colour_type is not None:
        expected = _PNG_MODES_BY_COLOUR_TYPE.get(colour_type)
        if expected is None or mode not in expected:
            raise ReferenceArtworkPayloadError(
                f"reference artwork PNG colour type {colour_type} does not "
                f"agree with the decoded mode {mode!r}"
            )
    if mode in ACCEPTED_DECODED_MODES:
        return
    details = {
        "decoded_mode": mode,
        "colour_type": colour_type,
        "has_alpha": False,
        "reference_key": reference_key,
    }
    if mode in _MASK_DECODED_MODES or colour_type == 0:
        raise ReferenceArtworkRefusedError(
            f"reference artwork {reference_key!r} is a single-channel "
            f"greyscale payload (mode={mode!r}, colour_type={colour_type!r}): "
            "a mask is not authored artwork and is never converted",
            code="MASK_PAYLOAD_REFUSED",
            details=details,
        )
    raise ReferenceArtworkRefusedError(
        f"reference artwork {reference_key!r} decodes to mode {mode!r}; "
        "authored artwork must be RGB or RGBA",
        code="UNSUPPORTED_COLOUR_TYPE",
        details=details,
    )


def _assert_draft_version(version: PackVersionRecord) -> None:
    """Refuse ingest into anything but a live draft pack version (409)."""
    status = getattr(version, "status", None)
    archived_at = getattr(version, "archived_at", None)
    if status != "draft" or archived_at is not None:
        raise PackVersionImmutableError(
            f"Cannot ingest reference artwork into pack version {version.id!r} "
            f"in status {status!r}: draft-only ingest"
        )


def discard_written_files(
    storage_root: str | Path, relative_paths: Iterable[str]
) -> list[str]:
    """Delete managed files written by a failed ingest (idempotent, contained).

    Only paths recorded by the ingest itself are touched, only files that
    resolve inside the managed root are removed, and empty parent directories
    are pruned up to (not including) the managed root.  Returns the removed
    relative paths.
    """
    managed = ManagedRoot(storage_root)
    removed: list[str] = []
    for rel in list(relative_paths):
        try:
            path = managed.resolve(rel)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            continue
        try:
            if path.is_file():
                path.unlink()
                removed.append(rel)
            parent = path.parent
            while parent != managed.root and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            continue
    return removed


def ingest_reference_artwork(
    *,
    session: Session,
    storage_root: str | Path,
    workspace_id: str,
    version_id: str,
    reference_key: str,
    filename: str | None,
    stream: BinaryIO,
    max_bytes: int,
    max_dimension: int,
    max_pixels: int,
    purpose: str = "artwork",
    written: list[str] | None = None,
) -> ReferenceArtworkIngestResult:
    """Ingest ONE authored artwork payload into a draft pack version.

    Order (all pre-write checks happen BEFORE any byte is written):
    key -> purpose -> filename -> workspace-scoped draft version -> capped
    read -> full decode/caps -> representation policy -> atomic managed write
    -> ready ``Artifact`` -> ``attach_asset`` under the namespaced key.

    The caller owns the transaction (commit on success; on failure roll back
    and call :func:`discard_written_files` with the same *written* list).

    Raises:
        ReferenceKeyRefusedError / ReferencePurposeRefusedError /
            ReferenceFilenameRefusedError: 422-family refusals.
        PackVersionNotFoundError: version missing or foreign to the workspace.
        PackVersionImmutableError: version is not a draft (published/archived).
        ReferenceArtworkTooLargeError: byte ceiling exceeded.
        ReferenceArtworkPayloadError: empty/corrupt/oversize-pixels payload.
        ReferenceArtworkRefusedError: decodable but not authored artwork.
    """
    view, role = validate_reference_key(reference_key)
    normalised_purpose = validate_reference_purpose(purpose)
    safe_filename = _sanitize_upload_filename(filename)

    repo = CharacterRepository(session, storage_root=Path(storage_root))
    version = repo.get_pack_version(version_id, workspace_id)
    _assert_draft_version(version)
    replaced_existing = any(a.pose_slot == reference_key for a in version.assets)

    data = _read_capped(stream, max_bytes)
    try:
        probe = probe_image(
            data,
            max_dimension=max_dimension,
            max_pixels=max_pixels,
        )
    except MediaValidationError as err:
        raise ReferenceArtworkPayloadError(
            f"reference artwork is not a decodable, bounded image: {err}"
        ) from err
    mode, colour_type = _decode_representation(data)
    _assert_representation_is_artwork(
        reference_key=reference_key, mode=mode, colour_type=colour_type
    )

    rel_path = (
        f"characters/{version.workspace_id}/{version.character_id}"
        f"/reference_{view}_{role}_{uuid.uuid4().hex[:8]}"
        f".{probe.canonical_extension()}"
    )
    managed = ManagedRoot(storage_root)
    try:
        sha256, size_bytes = managed.atomic_write_bytes(rel_path, data)
    except Exception as err:  # noqa: BLE001 - fail closed before any DB row
        raise ReferenceArtworkPayloadError(
            f"managed write failed for {rel_path!r}: {err}"
        ) from err
    if written is not None:
        written.append(rel_path)

    try:
        artifact = Artifact(
            workspace_id=version.workspace_id,
            kind="image",
            relative_path=rel_path,
            state="ready",
            sha256=sha256,
            size_bytes=size_bytes,
            mime_type=probe.mime_type,
            width=probe.width,
            height=probe.height,
        )
        session.add(artifact)
        session.flush()
        asset = repo.attach_asset(
            version_id=version_id,
            workspace_id=workspace_id,
            pose_slot=reference_key,
            artifact_id=artifact.id,
        )
    except BaseException:
        # This call wrote the bytes; do not leave an orphan managed file
        # behind even when the caller forgets to clean up.
        discard_written_files(storage_root, [rel_path])
        raise

    return ReferenceArtworkIngestResult(
        asset_id=asset.id,
        artifact_id=artifact.id,
        version_id=version_id,
        character_id=version.character_id,
        workspace_id=version.workspace_id,
        reference_key=reference_key,
        view=view,
        role=role,
        purpose=normalised_purpose,
        source_filename=safe_filename,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=probe.mime_type,
        width=probe.width,
        height=probe.height,
        decoded_mode=mode,
        colour_type=colour_type,
        has_alpha=mode == "RGBA",
        replaced_existing=replaced_existing,
        created_at=asset.created_at,
    )
