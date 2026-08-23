"""Content-probe based media validation (S08-H02 + S08-H02-C1).

The upload boundary must never trust a filename extension or a client-supplied
``Content-Type`` header.  These helpers decide media type from the BYTES and
verify the payload actually decodes:

- :func:`probe_image` — sniffs PNG/JPEG/WebP magic (a prefilter only), then
  **fully decodes** the payload with Pillow (``load()``) so that truncated /
  corrupt payloads with a valid magic header are rejected, re-opens to read
  the real dimensions, and enforces a maximum pixel side AND a maximum total
  pixel count.  The canonical MIME/extension come from the verified Pillow
  format, never from the filename.  Anything that is not a decodable
  allowlisted image of bounded size raises :class:`MediaValidationError`.
- :func:`sniff_video_container` — recognizes real video containers
  (MP4/MOV/3GP ``ftyp``, Matroska/WebM EBML, Ogg, AVI) from the leading
  bytes.  This is a PRE-FILTER only; the upload route must run the bounded
  ffprobe probe (:func:`app.services.video_probe.probe_video`) before
  publishing.
- :func:`is_reserved_entry_name` — case-insensitive reserved-name check for
  entries that a client-supplied filename must never collide with.

Both probe helpers are pure read-only functions over bytes, so callers can
probe a staged temp file before any atomic publish.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PurePath

from app.config import config

#: Image MIME types accepted by the replacement upload (and the S08 content
#: endpoints).  Mirrors the API-level allowlist; the decision is byte-based.
IMAGE_MIME_ALLOWLIST: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)

#: Canonical file extension per verified Pillow format (used to store a
#: replacement under the CORRECT extension/Content-Type contract).
_FORMAT_EXTENSION: dict[str, str] = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
}
_FORMAT_MIME: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}

#: Magic signatures used only as a cheap prefilter; the authoritative gate is
#: the Pillow full-decode below.
_MAGIC_BY_MIME: tuple[tuple[str, bytes], ...] = (
    ("image/png", b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", b"\xff\xd8\xff"),
    ("image/webp", b"RIFF"),
)

#: Entry names under a project/object dir that must never be overwritten by a
#: client-supplied upload filename (comparison is case-insensitive for
#: Windows).  Storage is server-owned, so this is defense-in-depth.
_RESERVED_ENTRY_NAMES: frozenset[str] = frozenset(
    {
        "project.json",
        "objects",
        "frames",
        "scenes",
        "debug",
        "audio",
        "dubbing",
        "gallery_manifest.json",
    }
)


class MediaValidationError(ValueError):
    """Uploaded bytes are not a valid, safely-sized media payload."""


@dataclass(frozen=True)
class ImageProbe:
    """The verified identity + dimensions of an image payload."""

    mime_type: str
    width: int
    height: int
    format: str

    def canonical_extension(self) -> str:
        """The extension matching the VERIFIED format (e.g. ``"png"``)."""
        return _FORMAT_EXTENSION[self.format]


def _sniff_image_mime(data: bytes) -> str | None:
    """Return the image MIME the leading bytes claim, else None (prefilter)."""
    for mime, magic in _MAGIC_BY_MIME:
        if data.startswith(magic):
            if mime == "image/webp":
                # RIFF ... WEBP at offset 8.
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return mime
            else:
                return mime
    return None


def probe_image(
    data: bytes,
    *,
    max_dimension: int | None = None,
    max_pixels: int | None = None,
) -> ImageProbe:
    """Fully verify *data* is a decodable allowlisted image and return it.

    The MIME decision comes from the bytes (never the caller's declared
    Content-Type).  The payload is FULLY decoded (``Image.load()``) so a
    truncated/corrupt file with a valid magic header is rejected; the file is
    then re-opened to read its real dimensions.  Both the pixel side and total
    pixel count are capped before publishing, so a decompression bomb can
    never drive an unbounded allocation.

    Raises :class:`MediaValidationError` for anything that is not a decodable
    PNG/JPEG/WebP of sane size.
    """
    if not isinstance(data, bytes) or not data:
        raise MediaValidationError("empty media payload")
    if max_dimension is None:
        max_dimension = config.max_image_dimension
    if max_pixels is None:
        max_pixels = config.max_image_pixels

    magic_mime = _sniff_image_mime(data)
    if magic_mime is None:
        raise MediaValidationError(
            "media payload does not match a supported image signature "
            "(PNG/JPEG/WebP)"
        )

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()  # FULL decode — catches truncated/corrupt payloads
            fmt = (image.format or "").upper()
            width, height = image.size
        # Re-open for a second, independent decode of the header (the first
        # context is closed after load()).
        with Image.open(io.BytesIO(data)) as image:
            width2, height2 = image.size
    except Exception as exc:  # noqa: BLE001 - corrupt/unknown => reject
        raise MediaValidationError(f"media payload is not a decodable image: {exc}") from exc

    verified_mime = _FORMAT_MIME.get(fmt)
    if verified_mime is None or verified_mime not in IMAGE_MIME_ALLOWLIST:
        raise MediaValidationError(f"unsupported image format {fmt!r}")
    # The header magic and the Pillow-verified format must agree.
    if verified_mime != magic_mime:
        raise MediaValidationError(
            f"image header mismatch: magic claims {magic_mime}, "
            f"decoder reports {verified_mime}"
        )
    if width <= 0 or height <= 0:
        raise MediaValidationError("media payload declares empty dimensions")
    if (width, height) != (width2, height2):
        raise MediaValidationError("media payload reports inconsistent dimensions")
    if width > max_dimension or height > max_dimension:
        raise MediaValidationError(
            f"media dimensions {width}x{height} exceed the maximum allowed "
            f"side of {max_dimension}px"
        )
    total_pixels = width * height
    if total_pixels > max_pixels:
        raise MediaValidationError(
            f"media pixel count {total_pixels} exceeds the maximum allowed "
            f"total of {max_pixels} pixels"
        )
    return ImageProbe(
        mime_type=verified_mime,
        width=width,
        height=height,
        format=fmt,
    )


def sniff_video_container(data: bytes) -> str | None:
    """Recognize a real video container from its leading bytes (prefilter).

    Returns a stable MIME for recognized containers, or None when the payload
    is not a known video container.  This is NOT sufficient on its own — the
    upload route must run the bounded ffprobe probe before publishing.
    """
    if not data:
        return None
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if data.startswith(b"OggS"):
        return "video/ogg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "video/x-msvideo"
    return None


def is_reserved_entry_name(name: str) -> bool:
    """Case-insensitive check for project/object entries a client-supplied
    filename must never collide with (Windows is case-insensitive)."""
    return PurePath(name).name.casefold() in _RESERVED_ENTRY_NAMES
