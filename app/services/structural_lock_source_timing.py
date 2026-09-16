"""Exact source timing proof for the public StructuralLock producer (F03).

R7 correction (finding F03): the producer must never fabricate source timing.
A missing numerator/denominator/duration is a TYPED denial with zero durable
mutation, and every accepted lock carries an EXACT frame count plus CFR
evidence proved from the current source artifact bytes through the existing
verified facilities:

- :func:`app.services.video_import.probe_source` — the verified bounded
  import probe (rational ``r_frame_rate``/``avg_frame_rate``,
  ``fps_classification``, ``nb_frames``, stream width/height, container
  duration).  Read-only by contract: it never copies, registers or mutates.
- :class:`app.persistence.artifacts.ManagedRoot` + ``hash_file`` — the
  durable managed-storage resolver and streaming sha256.

Proof rules (any doubt fails closed as :class:`SourceTimingError`):

1. Persisted VideoItem timing facts must ALL be present and positive —
   ``fps_num``, ``fps_den``, ``duration_ms``, ``width``, ``height``.  There
   is no 30fps / denominator-1 / one-frame fallback anywhere on this path
   (``STRUCTURAL_LOCK_SOURCE_TIMING_MISSING``).
2. The READY source artifact must resolve inside the managed root, exist,
   and hash EXACTLY to its recorded checksum before any trust is placed in
   it (``STRUCTURAL_LOCK_SOURCE_TIMING_UNPROVEN``).
3. The verified probe must succeed, classify the source as CFR, and report
   an EQUAL rational for ``r_frame_rate`` and ``avg_frame_rate``
   (``STRUCTURAL_LOCK_SOURCE_VFR`` otherwise — VFR cannot be frame-exact).
4. The exact frame count is the container's ``nb_frames`` — never a rounded
   duration estimate — and every persisted fact must agree EXACTLY with the
   probe: rational FPS equal, width/height equal, and
   ``duration_ms == round(nb_frames * den * 1000 / num)`` computed with
   ``Fraction`` arithmetic (``STRUCTURAL_LOCK_SOURCE_TIMING_MISMATCH``).

The proof result is returned to the producer, which stamps the exact
``frame_count``/``time_base`` into the manifest; the proof itself is
enforced, not re-derived later.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.persistence.artifacts import ManagedPathError, ManagedRoot, hash_file
from app.services.video_import import VideoImportError, probe_source

__all__ = [
    "CODE_SOURCE_VFR",
    "CODE_TIMING_MISMATCH",
    "CODE_TIMING_MISSING",
    "CODE_TIMING_UNPROVEN",
    "SourceTimingError",
    "SourceTimingProof",
    "prove_source_timing",
]

#: Persisted rational FPS / duration / dimensions are missing or non-positive.
CODE_TIMING_MISSING = "STRUCTURAL_LOCK_SOURCE_TIMING_MISSING"

#: The source artifact cannot be proved from its managed bytes (missing file,
#: unreadable, checksum tampered, or the verified probe failed).
CODE_TIMING_UNPROVEN = "STRUCTURAL_LOCK_SOURCE_TIMING_UNPROVEN"

#: The current source is not constant frame rate (r_frame_rate !=
#: avg_frame_rate) — frame-exact locking requires CFR.
CODE_SOURCE_VFR = "STRUCTURAL_LOCK_SOURCE_VFR"

#: Persisted facts disagree with the exact probe proof (rational FPS,
#: dimensions or frame-exact duration).
CODE_TIMING_MISMATCH = "STRUCTURAL_LOCK_SOURCE_TIMING_MISMATCH"


class SourceTimingError(Exception):
    """Typed fail-closed source timing denial (stable code + reasons)."""

    def __init__(
        self, code: str, message: str, *, reasons: tuple[str, ...] = ()
    ) -> None:
        self.code = code
        self.reasons = tuple(reasons)
        super().__init__(message)


@dataclass(frozen=True)
class SourceTimingProof:
    """Exact, probe-proved source timing facts for one accepted lock."""

    frame_count: int
    fps_num: int
    fps_den: int
    fps: float
    time_base: str
    classification: str
    r_frame_rate: str
    avg_frame_rate: str
    exact_duration_ms: int
    source_sha256: str


def _rational_text(raw: Any) -> str:
    """Human-stable ``num/den`` text for a probe rational ('' when absent)."""
    if isinstance(raw, dict):
        return f"{int(raw.get('num') or 0)}/{int(raw.get('den') or 0)}"
    return str(raw or "")


def _rational_pair(raw: Any) -> tuple[int, int]:
    if not isinstance(raw, dict):
        return (0, 0)
    try:
        return (int(raw.get("num") or 0), int(raw.get("den") or 0))
    except (TypeError, ValueError):
        return (0, 0)


def prove_source_timing(
    *,
    managed_root: str | Path | None,
    video: Any,
    source_artifact: Any,
) -> SourceTimingProof:
    """Prove the CURRENT source timing exactly; any doubt raises.

    Never defaults, never rounds a duration into a frame count.  Only the
    container's authoritative ``nb_frames`` + an CFR-equal rational pair
    (attested by the persisted import facts) can satisfy this proof.
    """
    # ── 1. persisted timing facts (no defaults; None/<=0 is a denial) ─────
    missing: list[str] = []
    fps_num = video.fps_num
    fps_den = video.fps_den
    duration_ms = video.duration_ms
    width = video.width
    height = video.height
    if fps_num is None or int(fps_num) <= 0:
        missing.append("fps_num")
    if fps_den is None or int(fps_den) <= 0:
        missing.append("fps_den")
    if duration_ms is None or int(duration_ms) <= 0:
        missing.append("duration_ms")
    if width is None or int(width) <= 0:
        missing.append("width")
    if height is None or int(height) <= 0:
        missing.append("height")
    if missing:
        raise SourceTimingError(
            CODE_TIMING_MISSING,
            "current source timing is not fully persisted; the producer "
            "never defaults missing rational/duration facts",
            reasons=tuple(missing),
        )
    fps_num = int(fps_num)
    fps_den = int(fps_den)
    duration_ms = int(duration_ms)
    width = int(width)
    height = int(height)

    # ── 2. resolve + hash the managed source artifact bytes ───────────────
    if managed_root is None:
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            "managed storage root is not configured; the source artifact "
            "cannot be proved",
        )
    relative = str(source_artifact.relative_path or "")
    if not relative:
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            "source artifact has no managed relative path",
        )
    try:
        path = ManagedRoot(Path(managed_root)).resolve(relative)
    except (ManagedPathError, OSError, ValueError) as exc:
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            f"source artifact path is not resolvable inside the managed "
            f"root: {exc}",
        ) from exc
    if not path.is_file():
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            "source artifact file is missing; exact timing cannot be proved",
        )
    recorded = str(source_artifact.sha256 or "")
    try:
        actual = hash_file(path)
    except OSError as exc:
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            f"source artifact is not readable: {exc}",
        ) from exc
    if actual != recorded:
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            "source artifact bytes do not match the recorded checksum; "
            "exact timing cannot be proved",
        )

    # ── 3. the verified bounded import probe (read-only) ──────────────────
    try:
        payload = probe_source(path, expected_sha256=recorded)
    except VideoImportError as exc:
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            "the verified source probe failed: "
            f"{getattr(exc, 'code', 'PROBE_FAILED')}: {exc}",
        ) from exc
    stream = payload.get("video_stream") if isinstance(payload, dict) else None
    if not isinstance(stream, dict):
        raise SourceTimingError(
            CODE_TIMING_UNPROVEN,
            "the verified source probe returned no video stream section",
        )

    r_pair = _rational_pair(stream.get("r_frame_rate"))
    a_pair = _rational_pair(stream.get("avg_frame_rate"))
    classification = str(stream.get("fps_classification") or "")
    try:
        nb_frames = int(stream.get("nb_frames") or 0)
        probe_width = int(stream.get("width") or 0)
        probe_height = int(stream.get("height") or 0)
    except (TypeError, ValueError):
        nb_frames, probe_width, probe_height = 0, 0, 0

    r_num, r_den = r_pair
    if r_num <= 0 or r_den <= 0:
        raise SourceTimingError(
            CODE_TIMING_MISSING,
            "the source probe did not report a positive rational frame rate",
            reasons=("r_frame_rate",),
        )
    if nb_frames <= 0:
        raise SourceTimingError(
            CODE_TIMING_MISSING,
            "the source probe did not report an exact positive frame count; "
            "a rounded duration estimate is never accepted",
            reasons=("nb_frames",),
        )

    # ── 4. CFR proof: equal r/avg rationals, classification CFR ───────────
    if classification != "CFR" or a_pair != r_pair:
        raise SourceTimingError(
            CODE_SOURCE_VFR,
            "the source is not constant frame rate "
            "(r_frame_rate != avg_frame_rate); frame-exact locking needs CFR",
            reasons=(
                f"r_frame_rate={_rational_text(stream.get('r_frame_rate'))}",
                f"avg_frame_rate={_rational_text(stream.get('avg_frame_rate'))}",
                f"classification={classification or 'UNKNOWN'}",
            ),
        )

    # ── 5. persisted facts must agree EXACTLY with the proof ──────────────
    exact_ms = int(round(Fraction(nb_frames * r_den * 1000, r_num)))
    if (fps_num, fps_den) != (r_num, r_den):
        raise SourceTimingError(
            CODE_TIMING_MISMATCH,
            "persisted rational FPS disagrees with the current source probe",
            reasons=(f"persisted={fps_num}/{fps_den}", f"probe={r_num}/{r_den}"),
        )
    if (width, height) != (probe_width, probe_height):
        raise SourceTimingError(
            CODE_TIMING_MISMATCH,
            "persisted dimensions disagree with the current source probe",
            reasons=(
                f"persisted={width}x{height}",
                f"probe={probe_width}x{probe_height}",
            ),
        )
    if duration_ms != exact_ms:
        raise SourceTimingError(
            CODE_TIMING_MISMATCH,
            "persisted duration disagrees with the exact frame-count timing "
            "(nb_frames * den / num)",
            reasons=(
                f"persisted_ms={duration_ms}",
                f"exact_ms={exact_ms}",
                f"nb_frames={nb_frames}",
            ),
        )

    return SourceTimingProof(
        frame_count=nb_frames,
        fps_num=r_num,
        fps_den=r_den,
        fps=r_num / r_den,
        time_base=f"{r_den}/{r_num}",
        classification=classification,
        r_frame_rate=_rational_text(stream.get("r_frame_rate")),
        avg_frame_rate=_rational_text(stream.get("avg_frame_rate")),
        exact_duration_ms=exact_ms,
        source_sha256=recorded,
    )
