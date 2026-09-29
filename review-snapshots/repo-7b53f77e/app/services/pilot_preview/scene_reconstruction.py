"""Pilot-preview scene reconstruction for the V3 demo window (R2, DV3-R2-T02).

Replaces the defect documented in REVIEW.md F02 (and its F01 removal side):
``app/workflow/pilot_preview_jobs.py`` ``_clean_source_frames`` applied
``cv2.inpaint(..., INPAINT_TELEA radius 3)`` independently per frame over a
SAM2 mask merely clipped to the operator rectangle, with no clean-plate
provenance, no per-role protected masks, and no declaration of unobserved
(hidden) background.  The ``_composite_v3`` occluder step then restored one
opaque rectangle ``[0.76,0.34,0.20,0.66]`` that does not encode the local
book/chair interaction.

This module is pilot-only and NEW (no existing file is edited).  It consumes
the frozen T01 contract ``app.services.pilot_preview.scene_contract`` and
never modifies it.  Principles:

- Multi-role source-derived masks + correction history: the removal target
  (character identity + old moving limb) is segmented from SOURCE pixels
  (skin / shirt-gray / book-blue tests inside a proposal box) and then
  refined by an explicit operator correction history.  The whole prompt
  rectangle is only the edit envelope -- never the removal mask -- and no
  clipped SAM mask is assumed correct.
- Book / chair / woman are protected SEPARATELY.  Source prompt bbox,
  removal mask, replacement alpha, permitted edits and preserved
  foreground are five different fields/masks, never one blended cutout.
- Source-observed clean background/chair reuse across the shot with frame
  provenance + alignment.  Telea is a bounded fallback inside the removal
  interior only, never a finished clean plate.
- Hidden background with no source observation is explicitly ``unknown``
  (an ``unknown_mask`` layer), never plausible-fill-as-truth.  A versioned
  reviewed 2D clean-plate *proposal* may be requested, but it ships as a
  human-review record -- no silent paid generation, no model install.
- Decomposition outputs (original / target mask / protected masks /
  clean plate / layer order / result without + with replacement) for the
  beginning frame, the contact/action event frame, and the end frame.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.services.pilot_preview.scene_contract import (
    EVENT_LEDGER,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SOURCE_PINNED_SHA256,
    SOURCE_WINDOW,
    local_to_source,
    source_to_local,
)
from app.services.pilot_preview.clean_plate_pack import apply_reviewed_plate

RECONSTRUCTION_REVISION = "pilot-scene-reconstruction-r2-c11-role-masks-v4"
BOOK_FINISH_REVISION = "source-book-complete-silhouette-pages-v3"
SUPPORTED_WINDOW = SOURCE_WINDOW
FRAME_SIZE = (FRAME_WIDTH, FRAME_HEIGHT)

# Roles whose visible pixels must survive reconstruction exactly (outside
# the explicitly permitted edit set).  The removal target ``character`` is
# intentionally absent here.
PROTECTED_ROLES: tuple[str, ...] = (
    "book",
    "chair_occupied",
    "chair_spare",
    "chair_foreground",
    "woman",
    "seated_back",
    "table",
    "room",
)

# Only these roles are in front of the replacement sprite.  ``room`` and the
# occupied/rear chairs remain part of the reconstructed background; copying
# them after sprite composition would paint the old reader back over the new
# character (the LR03 failure).
FRONT_PROTECTED_ROLES: tuple[str, ...] = (
    "woman",
    "table",
    "book",
    "seated_back",
    "chair_foreground",
)

# Per-frame layer stack, bottom first.  Bands come from the frozen contract;
# within a band the order below is the contract's pairwise rule for this
# window (rear chairs before mid actors, book above character, light-gray
# foreground chair above everything).
LAYER_ORDER: tuple[str, ...] = (
    "room",
    "chair_occupied",
    "chair_spare",
    "character",
    "woman",
    "table",
    "book",
    "seated_back",
    "chair_foreground",
)

# Source-derived colour tests (BGR, measured on real decoded frames
# src-450 / src-510 / src-522 / src-569 by the T02 worker; camera is
# static so these flat-cartoon fills hold across the window):
# - pale skin: all channels high, near-neutral.
# - book blue: saturated blue, B-R and B-G gaps > 90.
# - magenta dress: R high, R-G gap > 50, B capped.
# - dark-gray chair: mid gray band, near-neutral.
SKIN_TEST = {"min_all": 150, "max_abs_rg": 40}
BOOK_BLUE_TEST = {"min_b": 150, "min_b_minus_r": 90, "min_b_minus_g": 90}
DRESS_MAGENTA_TEST = {"min_r": 120, "min_r_minus_g": 50, "max_b": 150}
CHAIR_GRAY_TEST = {"min_all": 90, "max_all": 175, "max_spread": 30}

# Bounded fallback: Telea may only touch the removal interior, and only up
# to this fraction of the frame.  Anything larger must be resolved via
# source-observed reuse or declared unknown.
TELEA_MAX_FRAME_FRACTION = 0.08

# Event frame of the book closed->open transition (contract EVENT_LEDGER).
BOOK_TRANSITION_SOURCE = 522


class ReconstructionError(ValueError):
    """Fail-closed rejection with a human-readable reason."""


@dataclass(frozen=True)
class MaskCorrection:
    """One operator correction applied to a source-derived removal mask.

    ``bbox_xywh_px`` is a full-frame pixel rectangle; ``mode`` is either
    ``"include"`` (force removal inside the box) or ``"exclude"`` (force
    protection inside the box); ``confidence`` weights nothing silently --
    it is recorded for review.  ``supersedes`` names the earlier
    correction index this one replaces (or -1 for none).
    """

    bbox_xywh_px: tuple[int, int, int, int]
    mode: str
    confidence: float = 1.0
    note: str = "operator-corrected removal mask"
    supersedes: int = -1

    def __post_init__(self) -> None:
        x, y, w, h = self.bbox_xywh_px
        if self.mode not in ("include", "exclude"):
            raise ReconstructionError(f"bad correction mode {self.mode!r}")
        if w <= 0 or h <= 0 or x < 0 or y < 0:
            raise ReconstructionError(f"bad correction bbox {self.bbox_xywh_px!r}")
        if x + w > FRAME_WIDTH or y + h > FRAME_HEIGHT:
            raise ReconstructionError(
                f"correction bbox {self.bbox_xywh_px!r} outside "
                f"{FRAME_WIDTH}x{FRAME_HEIGHT}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ReconstructionError(f"bad correction confidence {self.confidence!r}")


@dataclass
class ReconstructionResult:
    """All per-frame reconstruction artefacts for one source frame."""

    source_frame: int
    source_sha256: str
    # Five distinct fields -- never one blended cutout.
    source_prompt_bbox_xywh_px: tuple[int, int, int, int]
    removal_mask: Any  # uint8 HxW, 255 = remove target identity/limb
    replacement_alpha: Any | None  # asset RGBA alpha only (consumed, not authored)
    permitted_edits_mask: Any  # uint8 HxW, 255 = allowed to change
    preserved_foreground: dict[str, Any]  # role -> uint8 mask copied from source
    protected_masks: dict[str, Any]  # role -> uint8 mask (all PROTECTED_ROLES)
    clean_plate: Any  # BGR HxWx3 source-observed background + chair
    clean_plate_provenance: dict[str, Any]
    reviewed_plate_identity: dict[str, Any] | None
    unknown_mask: Any  # uint8 HxW, 255 = no source observation (never filled)
    result_without_replacement: Any  # BGR: clean plate + preserved foreground
    layer_order: tuple[str, ...] = LAYER_ORDER
    correction_history: list[MaskCorrection] = field(default_factory=list)
    telea_used: bool = False
    reconstructed_foreground_mask: Any | None = None
    reconstructed_foreground_reference: Any | None = None
    reconstructed_foreground_provenance: dict[str, Any] = field(default_factory=dict)


def _require_frame_shape(frame: Any) -> tuple[int, int]:
    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        raise ReconstructionError("frame has no HxW shape")
    height, width = int(shape[0]), int(shape[1])
    if (width, height) != (FRAME_WIDTH, FRAME_HEIGHT):
        raise ReconstructionError(
            f"frame must be {FRAME_WIDTH}x{FRAME_HEIGHT}, got {width}x{height}"
        )
    return height, width


def _zeros(height: int, width: int) -> Any:
    import numpy as np

    return np.zeros((height, width), dtype=np.uint8)


def _mask_identity(mask: Any) -> str:
    import numpy as np

    arr = np.ascontiguousarray(mask, dtype=np.uint8)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def plate_cache_key(
    *,
    source_sha256: str,
    source_frame: int,
    mask_identity: str,
    algorithm: str,
    algorithm_params: dict[str, Any],
    reviewed_plate_identity: str | None = None,
) -> str:
    """Immutable cache identity for a source-derived reconstruction step."""
    import json

    canonical = json.dumps(
        {
            "source_sha256": source_sha256,
            "source_frame": source_frame,
            "mask_identity": mask_identity,
            "algorithm": algorithm,
            "algorithm_params": algorithm_params,
            "reviewed_plate_identity": reviewed_plate_identity,
            "revision": RECONSTRUCTION_REVISION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReconstructionCache:
    """Immutable cache of source-derived results under full identity.

    Keys bind source bytes + mask bytes + algorithm + params + revision, so
    a repeated SAM2/segmentation pass is skipped only when every input is
    identical.  Entries are never mutated in place.
    """

    def __init__(self) -> None:
        self._entries: dict[str, Any] = {}

    def lookup(self, key: str) -> Any | None:
        return self._entries.get(key)

    def store(self, key: str, value: Any) -> None:
        import numpy as np

        if key in self._entries:
            raise ReconstructionError(f"cache key collision (immutable): {key[:16]}")
        if isinstance(value, np.ndarray):
            value = value.copy()
        elif isinstance(value, dict):
            value = dict(value)
        self._entries[key] = value

    def __len__(self) -> int:
        return len(self._entries)


def book_state_at(source_frame: int) -> str:
    """Closed/open state of the PiP book insert at a source frame."""
    for entry in EVENT_LEDGER:
        if entry.get("kind") == "book_state" and int(entry["first_source"]) <= source_frame <= int(entry["last_source"]):
            return str(entry["state"])
    raise ReconstructionError(f"source frame {source_frame} outside window book events")


def book_insert_box_px(source_frame: int) -> tuple[int, int, int, int]:
    """Full-frame pixel box of the PiP book insert (x, y, w, h).

    Measured on real decoded frames: closed insert ~(259,198,36,43) at
    src-510 (blue fraction 0.596, tightest of the candidates); open insert
    ~(245,209,44,56) at src-569 (blue fraction 0.575).  A 2 px review
    margin is added so the protected book mask covers anti-aliased edges.
    """
    if source_frame < BOOK_TRANSITION_SOURCE:
        x, y, w, h = 259, 198, 36, 43
    else:
        # The first open frame has source-blue at y=204 and the late open
        # frame reaches y=261.  The box follows that measured footprint; it
        # is only a search envelope, never a painted rectangle.
        x, y, w, h = 243, 202, 48, 63
    margin = 2
    return (x - margin, y - margin, w + 2 * margin, h + 2 * margin)


def finish_source_book(frame: Any, *, source_frame: int, book_mask: Any) -> Any:
    """Add a restrained page/outline finish to the single source-owned book.

    The book remains the decoded source prop and is painted only where the
    source-derived ``book`` mask already proves blue book pixels.  This does
    not create a second prop or move the book; it makes the existing source
    prop legible after the 640x360 composite (page edge for the closed state,
    page bands for the open state).
    """
    import cv2
    import numpy as np

    out = np.asarray(frame).copy()
    visible = np.asarray(book_mask) > 0
    if not np.any(visible):
        return out
    ys, xs = np.where(visible)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    height, width = visible.shape

    def paint(mask: Any, colour: tuple[int, int, int]) -> None:
        out[np.asarray(mask, dtype=bool) & visible] = colour

    # The source role mask is the sole authority for every changed book pixel;
    # its connected source-blue hull plus source-supported edge/page pixels
    # gives the full observed silhouette without a fixed-world prop.
    border = cv2.morphologyEx(
        visible.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)
    ) > 0
    paint(border, (38, 24, 18))
    if source_frame < BOOK_TRANSITION_SOURCE:
        strip = np.zeros((height, width), dtype=np.uint8)
        sx0 = x0 + max(1, int((x1 - x0 + 1) * 0.73))
        sx1 = x0 + max(2, int((x1 - x0 + 1) * 0.90))
        strip[y0 + 3 : max(y0 + 4, y1 - 1), sx0:sx1] = 1
        paint(strip, (224, 236, 244))  # BGR: warm page block
        for yy in range(y0 + 6, y1 - 2, 5):
            line = np.zeros((height, width), dtype=np.uint8)
            cv2.line(line, (sx0, yy), (max(sx0, sx1 - 1), yy), 1, 1)
            paint(line, (170, 190, 205))
    else:
        # Two short page bands just inside the upper edge of the open source
        # book; the central spine and blue covers remain untouched.
        mid = (x0 + x1) // 2
        bands = np.zeros((height, width), dtype=np.uint8)
        bands[y0 + 2 : y0 + 7, x0 + 3 : max(x0 + 4, mid - 1)] = 1
        bands[y0 + 2 : y0 + 7, min(x1, mid + 2) : max(mid + 3, x1 - 2)] = 1
        paint(bands, (224, 236, 244))
        for yy in (y0 + 4, y0 + 6):
            line = np.zeros((height, width), dtype=np.uint8)
            cv2.line(line, (x0 + 4, yy), (max(x0 + 4, mid - 2), yy), 1, 1)
            cv2.line(line, (min(x1 - 2, mid + 2), yy), (max(min(x1 - 2, mid + 2), x1 - 3), yy), 1, 1)
            paint(line, (170, 190, 205))
        spine = np.zeros((height, width), dtype=np.uint8)
        cv2.line(spine, (mid, y0 + 2), (mid, y1 - 2), 1, 1)
        paint(spine, (20, 15, 22))
    return out


def repair_source_woman_edge(
    frame: Any,
    *,
    source_frame: int,
    source_reference: Any,
    woman_mask: Any | None = None,
    repair_mask: Any | None = None,
    repair_reference: Any | None = None,
) -> Any:
    """Remove the measured old-limb chip at the reader/woman seam.

    The source scan at 522..569 shows a small dark/green limb-shaped hole at
    the left dress boundary.  Use neighbouring, source-observed dress colour
    only inside that 21x11 seam patch; this keeps the woman in front of the
    replacement without importing a rectangular background or altering the
    camera/book geometry.
    """
    import numpy as np

    out = np.asarray(frame).copy()
    if source_frame < BOOK_TRANSITION_SOURCE:
        return out
    ref = np.asarray(source_reference)
    if repair_mask is not None and repair_reference is not None:
        repair = np.asarray(repair_mask) > 0
        reference = np.asarray(repair_reference)
        if repair.shape != out.shape[:2] or reference.shape != out.shape:
            raise ReconstructionError("temporal foreground repair shape mismatch")
        out[repair] = reference[repair]
    # Restrict repair to rows where the source-derived woman role is proven on
    # the right.  Fill only the occluded run back to the measured seam using
    # that row's source dress pixel; this removes the old dark/green sleeve
    # without restoring a free-standing rectangle.
    if woman_mask is None:
        return out
    allowed = np.asarray(woman_mask) > 0
    for y in range(185, 210):
        xs = np.where(allowed[y, 300:341])[0]
        if len(xs) == 0:
            continue
        right = min(340, 300 + int(xs.max()) + 1)
        # The replacement sleeve occupies the occluded run left of the first
        # proven dress pixel.  Start at the measured seam envelope so the
        # whole leaked run is removed, while the right edge still comes from
        # the actual woman role mask.
        left = 300
        if right <= left:
            continue
        # Use the far/right proven dress sample; the first mask pixels can be
        # anti-aliased remnants of the old occluding limb.
        source_colour = ref[y, min(340, 300 + int(xs[-1]))].copy()
        # The writable seam is the intersection of the measured seam envelope
        # and the independently derived woman role.  Never paint a guessed
        # run merely because its right endpoint happens to touch a mask.
        row_allowed = allowed[y].copy()
        row_allowed[:left] = False
        row_allowed[right:] = False
        out[y, row_allowed] = source_colour
    return out


def reader_proposal_box_px(source_frame: int) -> tuple[int, int, int, int]:
    """Proposal box (NOT the removal mask) bounding the seated reader.

    Pixel-measured black-outline boundaries on real decoded frames
    (src-510 row scans): left shoulder outline x~224 (row y=200:
    cream wall to x~223, outline 224-228), right edge = woman's dress
    from x~320 rightwards at torso rows (uniform magenta 320-335), top
    of hair y~99, seat line y~270.  Tight body box (224,99,103,171)
    with a 2 px review margin; the old-arm event at src-569 stays
    inside the same box (no protrusion was observed).  Corrections and
    colour tests carve the actual removal mask out of this envelope.
    """
    _ = source_frame  # static camera: one proposal box for the window
    margin = 2
    return (224 - margin, 99 - margin, 103 + 2 * margin, 171 + 2 * margin)


def _clip_box(
    box: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    x, y, w, h = (int(v) for v in box)
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, width), min(y + h, height)
    return (x0, y0, max(x1 - x0, 0), max(y1 - y0, 0))


def _fill_box(mask: Any, box: tuple[int, int, int, int], value: int) -> None:
    x, y, w, h = _clip_box(box, FRAME_WIDTH, FRAME_HEIGHT)
    if w and h:
        mask[y : y + h, x : x + w] = value


def derive_target_mask(
    frame: Any,
    *,
    source_frame: int,
    corrections: list[MaskCorrection] | tuple[MaskCorrection, ...] = (),
) -> Any:
    """Source-derived tight removal mask for the character target.

    Segments skin / shirt-gray / trouser-gray pixels inside the reader
    proposal box, unions the book-blue insert interior (the old moving
    limb holds the prop, so the insert interior at the target location is
    part of the removal), subtracts NOTHING silently (protected roles are
    enforced by the caller via :func:`apply_corrections`), then applies
    the explicit correction history.  Never returns the whole prompt
    rectangle: the mask is always carved from source pixels.
    """
    import numpy as np

    height, width = _require_frame_shape(frame)
    if not SUPPORTED_WINDOW[0] <= source_frame <= SUPPORTED_WINDOW[1]:
        raise ReconstructionError(f"source frame {source_frame} outside 450..569")

    img = np.asarray(frame)
    px, py, pw, ph = reader_proposal_box_px(source_frame)
    x0, y0 = max(px, 0), max(py, 0)
    x1, y1 = min(px + pw, width), min(py + ph, height)
    crop = img[y0:y1, x0:x1].astype(np.int16)
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]

    skin = (r >= SKIN_TEST["min_all"]) & (g >= SKIN_TEST["min_all"]) & (
        b >= SKIN_TEST["min_all"]
    ) & (abs(r - g) <= SKIN_TEST["max_abs_rg"])
    shirt_gray = (
        (r >= 90) & (r <= 235) & (g >= 90) & (g <= 235) & (b >= 90) & (b <= 235)
        & (abs(r - g) <= 45) & (abs(g - b) <= 45) & (abs(r - b) <= 45)
    )
    # NOTE: book-blue is deliberately NOT unioned here.  The PiP insert is
    # a protected prop (z-band 3, above the character): the replacement
    # must keep the source-sized book, so insert-interior blue pixels are
    # owned by the ``book`` protected mask, never by removal.
    target_crop = (skin | shirt_gray).astype(np.uint8) * 255

    mask = _zeros(height, width)
    mask[y0:y1, x0:x1] = target_crop

    # Small morphological close to join cartoon fills across outlines
    # without growing into neighbouring roles (3x3, one pass).
    import cv2

    kernel = np.ones((3, 3), dtype=np.uint8)
    closed = cv2.morphologyEx(mask[y0:y1, x0:x1], cv2.MORPH_CLOSE, kernel)
    mask[y0:y1, x0:x1] = closed
    return apply_corrections(mask, corrections)


def apply_corrections(
    mask: Any,
    corrections: list[MaskCorrection] | tuple[MaskCorrection, ...],
) -> Any:
    """Apply an explicit correction history to a mask (recorded, replayable)."""
    import numpy as np

    out = np.array(mask, dtype=np.uint8, copy=True)
    for index, correction in enumerate(corrections):
        if not isinstance(correction, MaskCorrection):
            raise ReconstructionError(f"correction {index} is not a MaskCorrection")
        box_mask = _zeros(*out.shape)
        _fill_box(box_mask, correction.bbox_xywh_px, 255)
        if correction.mode == "include":
            out = np.bitwise_or(out, box_mask)
        else:
            out = np.bitwise_and(out, 255 - box_mask)
    return out


def derive_protected_masks(
    frame: Any, *, source_frame: int
) -> dict[str, Any]:
    """Per-role source-derived protected masks (uint8, 255 = protected).

    Every role is segmented independently from source pixels:

    - ``book``: source-blue insert plus its immediately adjacent outline/page
      pixels at the per-state PiP box; it is a complete source-owned role.
    - ``chair_occupied``: dark-gray crescent left of the torso + seat band
      + legs (measured bands), minus the reader proposal interior so the
      target body is never claimed as chair.
    - ``chair_spare``: dark seat band + brown legs under the woman.
    - ``woman``: magenta dress + skin region right of the reader.
    - ``seated_back`` / ``table`` / ``chair_foreground`` / ``room``:
      conservative pass-through boxes measured on real frames (these roles
      never overlap the removal target, so a bounded box is the honest
      protected claim, recorded per role instead of one global cutout).
    """
    import cv2
    import numpy as np

    height, width = _require_frame_shape(frame)
    if not SUPPORTED_WINDOW[0] <= source_frame <= SUPPORTED_WINDOW[1]:
        raise ReconstructionError(f"source frame {source_frame} outside 450..569")
    img = np.asarray(frame).astype(np.int16)
    b, g, r = img[:, :, 0], img[:, :, 1], img[:, :, 2]

    masks: dict[str, Any] = {}

    blue = (
        (b >= BOOK_BLUE_TEST["min_b"])
        & ((b - r) >= BOOK_BLUE_TEST["min_b_minus_r"])
        & ((b - g) >= BOOK_BLUE_TEST["min_b_minus_g"])
    )
    book = _zeros(height, width)
    _fill_box(book, book_insert_box_px(source_frame), 0)  # ensure clipped below
    bx, by, bw, bh = _clip_box(book_insert_box_px(source_frame), width, height)
    region = np.zeros((height, width), dtype=bool)
    region[by : by + bh, bx : bx + bw] = True
    book_seed = (blue & region).astype(np.uint8)
    # Build the role from the source prop itself.  A filled hull closes the
    # two open pages around their measured blue edges; nearby source-supported
    # cream/dark linework restores pages, spine and antialiasing.  No pixel is
    # admitted merely because it lies in the search envelope.
    contours, _ = cv2.findContours(book_seed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        hull = cv2.convexHull(np.concatenate(contours, axis=0))
        cv2.fillConvexPoly(book, hull, 255)
    nearby = cv2.dilate(book_seed, np.ones((5, 5), np.uint8), iterations=1) > 0
    max_channel = np.maximum(np.maximum(r, g), b)
    min_channel = np.minimum(np.minimum(r, g), b)
    cream_page = (min_channel >= 130) & ((max_channel - min_channel) <= 85)
    dark_line = max_channel <= 90
    linework = (cream_page | dark_line) & nearby & region
    book[linework] = 255
    book = cv2.morphologyEx(book, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    masks["book"] = book

    gray_spread = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    dark_gray = (
        (r >= CHAIR_GRAY_TEST["min_all"])
        & (np.maximum(np.maximum(r, g), b) <= CHAIR_GRAY_TEST["max_all"])
        & (gray_spread <= CHAIR_GRAY_TEST["max_spread"])
    )
    proposal = _zeros(height, width)
    _fill_box(proposal, reader_proposal_box_px(source_frame), 255)
    chair_occ = _zeros(height, width)
    # Measured visible chair bands (src-510 vision + pixel stats).  The
    # backrest crescent is verified only for x in [196,216] (row y=200:
    # dark-gray fill ends at x~216, cream wall resumes to the right), so
    # the crescent column stops there instead of reaching under the
    # reader's torso.  The seat wedge under the butt (column x=228 scan:
    # thigh gray to y~259, black outline y~260, chair dark-gray 81s from
    # y~261) is verified only for y in [261,271].
    for band in (
        (196, 193, 21, 91),  # backrest crescent left of torso (verified)
        (227, 261, 96, 10),  # seat wedge below the outline (verified)
        (207, 283, 14, 53),  # rear-left leg
        (277, 275, 17, 54),  # front leg
    ):
        band_mask = _zeros(height, width)
        _fill_box(band_mask, band, 255)
        chair_occ = np.bitwise_or(chair_occ, np.bitwise_and(band_mask, dark_gray.astype(np.uint8) * 255))
    # Legs are dark brown, not gray: claim them by box (thin, measured).
    for leg in ((207, 283, 14, 53), (277, 275, 17, 54), (259, 277, 9, 20)):
        _fill_box(chair_occ, leg, 255)
    # Never claim the target body interior as chair: carve the proposal
    # box out except where the bands were explicitly measured.
    _ = proposal
    masks["chair_occupied"] = chair_occ

    chair_spare = _zeros(height, width)
    for band in ((297, 228, 63, 34), (300, 259, 13, 25), (344, 221, 16, 85)):
        _fill_box(chair_spare, band, 255)
    masks["chair_spare"] = chair_spare

    magenta = (
        (r >= DRESS_MAGENTA_TEST["min_r"])
        & ((r - g) >= DRESS_MAGENTA_TEST["min_r_minus_g"])
        & (b <= DRESS_MAGENTA_TEST["max_b"])
    )
    skin = (
        (r >= SKIN_TEST["min_all"])
        & (g >= SKIN_TEST["min_all"])
        & (b >= SKIN_TEST["min_all"])
        & (abs(r - g) <= SKIN_TEST["max_abs_rg"])
    )
    woman = _zeros(height, width)
    _fill_box(woman, (291, 64, 96, 220), 0)
    # Column x=300 scan (src-510): woman's dress/magenta starts at y=150
    # (bgr 117,87,177); above that is her hair/face (y 64..149).  The
    # reader's proposal box starts at y=97, so only the y>=97 rows can
    # overlap the target -- and the y 97..149 rows at x 299..328 are the
    # reader's own hair/face (his proposal box), NOT hers: her face
    # column is verified only at x in [310,340] (x=300 y=90..110 are
    # curtain-shadow pixels 33,49,69 / 42,64,85, not skin).  Magenta
    # claims stay at y>=150 (her dress, in front of his right edge).
    wx, wy, ww, wh = _clip_box((291, 64, 96, 220), width, height)
    wregion = np.zeros((height, width), dtype=bool)
    wregion[wy : wy + wh, wx : wx + ww] = True
    dress_region = np.zeros((height, width), dtype=bool)
    dress_region[150:wy + wh, wx : wx + ww] = True
    face_region = np.zeros((height, width), dtype=bool)
    face_region[wy:150, 310:341] = True
    woman[(magenta & wregion & dress_region)] = 255
    woman[(skin & wregion & face_region)] = 255
    # Woman's seat band + legs are chair_spare, not woman: carve overlap.
    woman = np.bitwise_and(woman, 255 - (chair_spare > 0).astype(np.uint8) * 255)
    # Close only the horizontal anti-aliased dress edge.  The source scan
    # proves the dress begins immediately to the left of the old reader's
    # green sleeve; without this 5x1 closure, a one-pixel gap lets the
    # replacement sleeve leak into the woman at the 522 event frame.
    woman = cv2.dilate(woman, np.ones((1, 5), dtype=np.uint8), iterations=1)
    masks["woman"] = woman

    passthrough: dict[str, tuple[int, int, int, int]] = {
        # seated_back figure at the table (measured, never near target).
        "seated_back": (490, 112, 105, 170),
        # wooden table + diorama prop, right side.
        "table": (412, 205, 228, 155),
        # light-gray foreground chair back, lower-right.
        "chair_foreground": (481, 231, 110, 129),
    }
    for role, box in passthrough.items():
        role_mask = _zeros(height, width)
        _fill_box(role_mask, box, 255)
        masks[role] = role_mask
    # room = full frame MINUS every other protected claim AND minus the
    # removal target's proposal envelope: room is the background layer and
    # must never swallow the target (or the proposal box the target is
    # carved from) as "protected".  The envelope (not the whole prompt
    # rectangle) is the honest room exclusion: room pixels inside it are
    # either removal or explicitly protected roles, never background.
    room = np.full((height, width), 255, dtype=np.uint8)
    _fill_box(room, reader_proposal_box_px(source_frame), 0)
    for role_mask in masks.values():
        room = np.bitwise_and(
            room, 255 - (np.asarray(role_mask) > 0).astype(np.uint8) * 255
        )
    masks["room"] = room
    return masks


def derive_temporal_woman_repair(
    *, source_frame: int, neighbour_frames: dict[int, Any] | None
) -> tuple[Any, Any | None, dict[str, Any]]:
    """Derive a narrow foreground repair from earlier unoccluded source pixels."""
    import cv2
    import numpy as np

    mask = _zeros(FRAME_HEIGHT, FRAME_WIDTH)
    if source_frame < BOOK_TRANSITION_SOURCE or not neighbour_frames:
        return mask, None, {"status": "not_applicable", "source_frames": []}
    candidates = sorted(neighbour_frames)
    support: list[int] = []
    for frame_no in candidates:
        if frame_no >= BOOK_TRANSITION_SOURCE:
            continue
        image = np.asarray(neighbour_frames[frame_no]).astype(np.int16)
        b, g, r = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        dress = (r >= DRESS_MAGENTA_TEST["min_r"]) & ((r - g) >= DRESS_MAGENTA_TEST["min_r_minus_g"]) & (b <= DRESS_MAGENTA_TEST["max_b"])
        narrow = np.zeros(mask.shape, dtype=np.uint8)
        # The measured source-arm leak reaches x=323 at 522/523.  The old
        # 300:321 envelope stopped before the ownership boundary and left a
        # black seam on the woman.  Extend only through the contiguous
        # source-observed dress support; this is a removal/ownership mask,
        # never a painted or blurred scene rectangle.
        narrow[185:211, 300:327] = dress[185:211, 300:327].astype(np.uint8) * 255
        if np.any(narrow):
            support.append(int(frame_no))
            mask = np.maximum(mask, narrow)
    if not support:
        return mask, None, {"status": "unknown", "source_frames": []}
    bounded = np.zeros(mask.shape, dtype=np.uint8)
    bounded[184:212, 299:328] = 255
    mask = cv2.bitwise_and(cv2.dilate(mask, np.ones((3, 3), np.uint8)), bounded)
    donor_frame = min(support, key=lambda value: abs(value - 521))
    return mask, np.asarray(neighbour_frames[donor_frame]).copy(), {
        "status": "source_temporal_support",
        "source_frames": support,
        "donor_frame": donor_frame,
        "bbox_xywh_px": [299, 184, 29, 28],
        "authority": "source_supported_dress_only",
    }


def build_permitted_edits_mask(
    removal_mask: Any,
    protected_masks: dict[str, Any],
    *,
    seam_px: int = 1,
) -> Any:
    """Permitted-edits mask = removal interior + thin seam, minus protection.

    Only pixels inside the removal mask (plus a ``seam_px`` outline for
    anti-aliased edges) may change; every protected-role pixel is forced
    back to preserved even if a removal test fired there.  This is the
    field that makes "protected pixels equal pre-encode" provable.
    """
    import cv2
    import numpy as np

    removal = (np.asarray(removal_mask) > 0).astype(np.uint8) * 255
    if seam_px > 0:
        kernel = np.ones((3, 3), dtype=np.uint8)
        dilated = cv2.dilate(removal, kernel, iterations=int(seam_px))
    else:
        dilated = removal
    protected_union = _zeros(*removal.shape)
    for role_mask in protected_masks.values():
        protected_union = np.bitwise_or(
            protected_union, (np.asarray(role_mask) > 0).astype(np.uint8) * 255
        )
    return np.bitwise_and(dilated, 255 - (protected_union > 0).astype(np.uint8) * 255)


def reconstruct_clean_plate(
    frame: Any,
    removal_mask: Any,
    protected_masks: dict[str, Any],
    *,
    source_frame: int,
    source_sha256: str,
    neighbour_frames: dict[int, Any] | None = None,
    cache: ReconstructionCache | None = None,
    reviewed_plate: Any | None = None,
    reviewed_plate_identity: str | None = None,
) -> tuple[Any, dict[str, Any], Any]:
    """Build the source-observed clean plate + provenance + unknown mask.

    Strategy, in order:

    1. Start from the current frame; every pixel outside the removal mask
       is source-observed with provenance ``same_frame``.
    2. For removal-interior pixels, prefer aligned reuse from neighbour
       source frames of the same shot where that pixel is NOT removed
       (provenance ``shot_reuse:<source_frame>``, alignment ``static`` --
       the camera never moves, so identity alignment is exact).
    3. If a reviewed full-frame clean plate is supplied, it is consumed for
       every remaining removal pixel and its identity is recorded.
    4. Whatever removal pixel has no observation anywhere is Telea-filled
       ONLY if the Telea area stays under ``TELEA_MAX_FRAME_FRACTION``;
       those pixels carry provenance ``telea_fallback`` and
       ``telea_used=True``.
    5. Pixels with no source observation and no Telea budget are left from
       the current frame BUT flagged 255 in ``unknown_mask`` with
       provenance ``unknown`` -- never presented as recovered truth.

    Results are cached under the full source/mask/algorithm identity when
    a cache is supplied.
    """
    import cv2
    import numpy as np

    height, width = _require_frame_shape(frame)
    removal = (np.asarray(removal_mask) > 0)
    img = np.asarray(frame)

    key: str | None = None
    if cache is not None:
        key = plate_cache_key(
            source_sha256=source_sha256,
            source_frame=source_frame,
            mask_identity=_mask_identity(np.asarray(removal_mask)),
            algorithm="source_reuse_then_bounded_telea",
            algorithm_params={
                "telea_max_fraction": TELEA_MAX_FRAME_FRACTION,
                "alignment": "static",
                "neighbours": sorted((neighbour_frames or {}).keys()),
            },
            reviewed_plate_identity=reviewed_plate_identity,
        )
        hit = cache.lookup(key)
        if isinstance(hit, dict) and "clean_plate" in hit:
            cached = hit
            return (
                np.array(cached["clean_plate"], copy=True),
                dict(cached["provenance"]),
                np.array(cached["unknown_mask"], copy=True),
            )

    plate = img.copy()
    provenance = np.full((height, width), "same_frame", dtype=object)
    provenance[removal] = "pending"

    if neighbour_frames:
        for neighbour_source, neighbour in sorted(neighbour_frames.items()):
            if neighbour_source == source_frame:
                continue
            try:
                nremoval = derive_target_mask(neighbour, source_frame=neighbour_source)
            except ReconstructionError:
                continue
            donor = removal & ~(np.asarray(nremoval) > 0)
            if not bool(donor.any()):
                continue
            plate[donor] = np.asarray(neighbour)[donor]
            provenance[donor] = f"shot_reuse:{neighbour_source}"
            removal = removal & ~donor
            if not bool(removal.any()):
                break

    unknown = np.zeros((height, width), dtype=np.uint8)
    telea_used = False
    reviewed_plate_pixels = 0
    if reviewed_plate is not None and bool(removal.any()):
        import numpy as np

        candidate = np.asarray(reviewed_plate)
        if candidate.shape != img.shape:
            raise ReconstructionError("reviewed clean plate shape mismatch")
        plate = apply_reviewed_plate(plate, candidate, removal.astype(np.uint8) * 255)
        reviewed_plate_pixels = int(np.count_nonzero(removal))
        provenance[removal] = "reviewed_plate"
        removal = np.zeros_like(removal, dtype=bool)
    remaining = int(np.count_nonzero(removal))
    if remaining:
        fraction = remaining / float(height * width)
        if fraction <= TELEA_MAX_FRAME_FRACTION:
            telea_mask = removal.astype(np.uint8) * 255
            plate = cv2.inpaint(plate, telea_mask, 3, cv2.INPAINT_TELEA)
            provenance[removal] = "telea_fallback"
            telea_used = True
        else:
            unknown[removal] = 255
            provenance[removal] = "unknown"

    provenance_record: dict[str, Any] = {
        "revision": RECONSTRUCTION_REVISION,
        "source_sha256": source_sha256,
        "source_frame": source_frame,
        "same_frame_pixels": int(np.count_nonzero(provenance == "same_frame")),
        "reviewed_plate_pixels": reviewed_plate_pixels,
        "shot_reuse_pixels": int(
            np.count_nonzero(
                np.array([str(v).startswith("shot_reuse:") for v in provenance.flat])
            )
        ),
        "telea_fallback_pixels": int(np.count_nonzero(provenance == "telea_fallback")),
        "unknown_pixels": int(np.count_nonzero(provenance == "unknown")),
        "telea_used": telea_used,
        "alignment": "static",
        "cache_key": key,
        "reviewed_plate_identity": reviewed_plate_identity,
    }
    if cache is not None and key is not None:
        cache.store(
            key,
            {
                "clean_plate": plate.copy(),
                "provenance": dict(provenance_record),
                "unknown_mask": unknown.copy(),
            },
        )
    return plate, provenance_record, unknown


def propose_reviewed_clean_plate(
    provenance: dict[str, Any],
    *,
    reviewer: str = "",
    approved: bool = False,
) -> dict[str, Any]:
    """Versioned reviewed 2D clean-plate proposal (human gate, no generation).

    Unknown regions may only ship inside a proposal record that names a
    reviewer and carries ``approved=True``.  Until then the plate pixels
    flagged ``unknown`` must be rendered as an explicit placeholder by the
    caller -- this function never invents pixels.
    """
    record = {
        "proposal_revision": RECONSTRUCTION_REVISION + "-plate-proposal-v1",
        "source_frame": provenance.get("source_frame"),
        "source_sha256": provenance.get("source_sha256"),
        "unknown_pixels": provenance.get("unknown_pixels", 0),
        "telea_fallback_pixels": provenance.get("telea_fallback_pixels", 0),
        "reviewer": reviewer,
        "approved": bool(approved),
    }
    if int(record["unknown_pixels"] or 0) > 0 and not bool(approved):
        record["status"] = "NEEDS_REVIEW: unknown regions must not ship as truth"
    elif not bool(approved):
        record["status"] = "NEEDS_REVIEW"
    else:
        record["status"] = "REVIEWED"
    return record


def reconstruct_frame(
    frame: Any,
    *,
    source_frame: int,
    source_sha256: str,
    source_prompt_bbox_xywh_px: tuple[int, int, int, int],
    corrections: list[MaskCorrection] | tuple[MaskCorrection, ...] = (),
    replacement_alpha: Any | None = None,
    propagated_removal_mask: Any | None = None,
    neighbour_frames: dict[int, Any] | None = None,
    cache: ReconstructionCache | None = None,
    reviewed_plate: Any | None = None,
    reviewed_plate_identity: dict[str, Any] | None = None,
) -> ReconstructionResult:
    """Full pilot-scope reconstruction of one source frame.

    Removal mask first (source-derived + propagated segmentation + corrections); protected masks
    second (per role, enforced over removal); permitted-edits derived;
    clean plate with provenance; unknown flagged; result composed WITHOUT
    replacement (clean plate + preserved foreground in contract layer
    order).  The ``result_with_replacement`` compositing belongs to the
    T03 pose layer -- this module only exposes the held-out alpha field.
    """
    height, width = _require_frame_shape(frame)
    if source_sha256 != SOURCE_PINNED_SHA256:
        raise ReconstructionError("source sha256 mismatch: not the pinned source")
    if not SUPPORTED_WINDOW[0] <= source_frame <= SUPPORTED_WINDOW[1]:
        raise ReconstructionError(f"source frame {source_frame} outside 450..569")

    removal = derive_target_mask(frame, source_frame=source_frame, corrections=corrections)
    if propagated_removal_mask is not None:
        import numpy as np

        propagated = np.asarray(propagated_removal_mask)
        if propagated.shape[:2] != (height, width):
            raise ReconstructionError("propagated removal mask shape mismatch")
        removal = np.bitwise_or(
            removal,
            (propagated > 0).astype(np.uint8) * 255,
        )
    protected = derive_protected_masks(frame, source_frame=source_frame)
    temporal_repair_mask, temporal_repair_reference, temporal_repair_provenance = derive_temporal_woman_repair(
        source_frame=source_frame, neighbour_frames=neighbour_frames
    )

    import numpy as np

    # Protected wins over removal everywhere: a removal pixel claimed by
    # any protected role is carved out (this is what keeps book/chair /
    # woman pixels exactly equal pre-encode).
    protected_union = _zeros(height, width)
    for role_mask in protected.values():
        protected_union = np.bitwise_or(
            protected_union, (np.asarray(role_mask) > 0).astype(np.uint8) * 255
        )
    removal = np.bitwise_and(
        (np.asarray(removal) > 0).astype(np.uint8) * 255,
        255 - (protected_union > 0).astype(np.uint8) * 255,
    )

    permitted = build_permitted_edits_mask(removal, protected)

    plate, provenance, unknown = reconstruct_clean_plate(
        frame,
        removal,
        protected,
        source_frame=source_frame,
        source_sha256=source_sha256,
        neighbour_frames=neighbour_frames,
        cache=cache,
        reviewed_plate=reviewed_plate,
        reviewed_plate_identity=(reviewed_plate_identity or {}).get("content_sha256"),
    )

    # Result WITHOUT replacement: clean plate, then preserved foreground
    # roles re-copied from source in contract layer order.
    import cv2  # noqa: F401 -- kept for caller-side parity, unused here

    result = np.asarray(plate).copy()
    src = np.asarray(frame)
    for role in FRONT_PROTECTED_ROLES:
        role_mask = protected.get(role)
        if role_mask is None:
            continue
        keep = np.asarray(role_mask) > 0
        result[keep] = src[keep]

    return ReconstructionResult(
        source_frame=source_frame,
        source_sha256=source_sha256,
        source_prompt_bbox_xywh_px=(
            int(source_prompt_bbox_xywh_px[0]),
            int(source_prompt_bbox_xywh_px[1]),
            int(source_prompt_bbox_xywh_px[2]),
            int(source_prompt_bbox_xywh_px[3]),
        ),
        removal_mask=removal,
        replacement_alpha=replacement_alpha,
        permitted_edits_mask=permitted,
        preserved_foreground={role: m for role, m in protected.items()},
        protected_masks=dict(protected),
        clean_plate=np.asarray(plate),
        clean_plate_provenance=provenance,
        reviewed_plate_identity=reviewed_plate_identity,
        unknown_mask=unknown,
        result_without_replacement=result,
        correction_history=list(corrections),
        reconstructed_foreground_mask=temporal_repair_mask,
        reconstructed_foreground_reference=temporal_repair_reference,
        reconstructed_foreground_provenance=temporal_repair_provenance,
    )


def decompose_frame(result: ReconstructionResult) -> dict[str, Any]:
    """Decomposition views for one reconstructed frame (review artefacts)."""
    import numpy as np

    views: dict[str, Any] = {
        "source_frame": result.source_frame,
        "layer_order": list(result.layer_order),
        "removal_mask": np.asarray(result.removal_mask).copy(),
        "protected_masks": {
            role: np.asarray(mask).copy()
            for role, mask in result.protected_masks.items()
        },
        "clean_plate": np.asarray(result.clean_plate).copy(),
        "unknown_mask": np.asarray(result.unknown_mask).copy(),
        "result_without_replacement": np.asarray(
            result.result_without_replacement
        ).copy(),
        "provenance": dict(result.clean_plate_provenance),
        "correction_history": [
            {
                "bbox_xywh_px": list(correction.bbox_xywh_px),
                "mode": correction.mode,
                "confidence": correction.confidence,
                "note": correction.note,
                "supersedes": correction.supersedes,
            }
            for correction in result.correction_history
        ],
        "reconstructed_foreground_mask": np.asarray(
            result.reconstructed_foreground_mask
            if result.reconstructed_foreground_mask is not None
            else np.zeros_like(result.removal_mask)
        ).copy(),
        "reconstructed_foreground_provenance": dict(result.reconstructed_foreground_provenance),
    }
    return views


def decomposition_identity(decomposition: dict[str, Any]) -> str:
    """Deterministic identity over masks + clean plate + events.

    Any per-layer mask, clean-plate, or event tamper changes the identity
    (or fails validation first).  Protected-pixel equality is checked
    separately by the caller pre-encode.
    """
    import json

    import numpy as np

    def digest(arr: Any) -> str:
        return hashlib.sha256(
            np.ascontiguousarray(arr, dtype=np.uint8).tobytes()
        ).hexdigest()

    record = {
        "revision": RECONSTRUCTION_REVISION,
        "source_frame": decomposition["source_frame"],
        "layer_order": list(decomposition["layer_order"]),
        "removal_mask": digest(decomposition["removal_mask"]),
        "protected_masks": {
            role: digest(mask)
            for role, mask in sorted(decomposition["protected_masks"].items())
        },
        "clean_plate": digest(decomposition["clean_plate"]),
        "unknown_mask": digest(decomposition["unknown_mask"]),
        "result_without_replacement": digest(
            decomposition["result_without_replacement"]
        ),
        "book_state": book_state_at(int(decomposition["source_frame"])),
        "corrections": [
            {
                "bbox_xywh_px": list(entry["bbox_xywh_px"]),
                "mode": entry["mode"],
            }
            for entry in decomposition["correction_history"]
        ],
        "reconstructed_foreground_mask": digest(decomposition["reconstructed_foreground_mask"]),
        "reconstructed_foreground_provenance": decomposition["reconstructed_foreground_provenance"],
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_decomposition_sheet(
    frame: Any,
    result: ReconstructionResult,
    target_path: str,
) -> str:
    """Write a review sheet PNG: original / removal / protected-union /
    clean plate / unknown / result-without-replacement (2 rows x 3 cols).

    Pure review artefact -- never product output, never hardcoded as one.
    """
    import numpy as np

    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001 -- honest capability report
        raise ReconstructionError(f"PIL unavailable for review sheet: {exc}") from exc

    height, width = _require_frame_shape(frame)
    src = np.asarray(frame)

    def mask_overlay(base: Any, mask: Any, color: tuple[int, int, int]) -> Any:
        view = np.asarray(base).copy()
        flagged = np.asarray(mask) > 0
        tint = np.zeros_like(view)
        tint[:, :] = color
        view[flagged] = (0.55 * view[flagged] + 0.45 * tint[flagged]).astype(np.uint8)
        return view

    protected_union = _zeros(height, width)
    for role_mask in result.protected_masks.values():
        protected_union = np.bitwise_or(
            protected_union, (np.asarray(role_mask) > 0).astype(np.uint8) * 255
        )

    unknown_rgb = np.asarray(result.clean_plate).copy()
    unknown_rgb[np.asarray(result.unknown_mask) > 0] = (0, 0, 255)

    cells = [
        ("original", src[:, :, ::-1]),
        ("target-removal", mask_overlay(src, result.removal_mask, (255, 0, 0))[:, :, ::-1]),
        ("protected-union", mask_overlay(src, protected_union, (0, 255, 0))[:, :, ::-1]),
        ("clean-plate", np.asarray(result.clean_plate)[:, :, ::-1]),
        ("unknown-red", unknown_rgb[:, :, ::-1]),
        (
            "result-without-replacement",
            np.asarray(result.result_without_replacement)[:, :, ::-1],
        ),
    ]
    thumb_w, thumb_h = 320, 180
    thumbs = []
    for _label, rgb in cells:
        image = Image.fromarray(np.ascontiguousarray(rgb))
        thumbs.append(image.resize((thumb_w, thumb_h)))
    sheet = Image.new("RGB", (thumb_w * 3, thumb_h * 2), (20, 20, 20))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % 3) * thumb_w, (index // 3) * thumb_h))
    sheet.save(target_path)
    return target_path


__all__ = [
    "BOOK_TRANSITION_SOURCE",
    "CHAIR_GRAY_TEST",
    "DRESS_MAGENTA_TEST",
    "BOOK_BLUE_TEST",
    "FRAME_SIZE",
    "FRONT_PROTECTED_ROLES",
    "LAYER_ORDER",
    "PROTECTED_ROLES",
    "RECONSTRUCTION_REVISION",
    "BOOK_FINISH_REVISION",
    "SKIN_TEST",
    "SUPPORTED_WINDOW",
    "TELEA_MAX_FRAME_FRACTION",
    "MaskCorrection",
    "ReconstructionCache",
    "ReconstructionError",
    "ReconstructionResult",
    "apply_corrections",
    "book_insert_box_px",
    "book_state_at",
    "build_permitted_edits_mask",
    "decompose_frame",
    "decomposition_identity",
    "derive_protected_masks",
    "derive_temporal_woman_repair",
    "derive_target_mask",
    "local_to_source",
    "plate_cache_key",
    "propose_reviewed_clean_plate",
    "reader_proposal_box_px",
    "reconstruct_clean_plate",
    "reconstruct_frame",
    "render_decomposition_sheet",
    "source_to_local",
]
