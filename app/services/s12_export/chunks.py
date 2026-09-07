"""S12-T03B chunk planner — bounded-memory/disk-aware exact frame ranges.

Consumes read-only (frozen, never rewritten here):
- ``docs/contracts/s12-export.md`` (``s12-export-v1``) — frame-range and
  ``.partial`` vocabulary only.
- ``app/persistence/s12_export.py`` (T03A) — chunk boundary rows
  (``upsert_chunk`` / ``transition_chunk`` own every DB write; this module
  never touches the DB).
- ``app/services/s12_export/preflight.py`` — ``ESTIMATE_BPP`` heuristic
  (T01 frozen estimate factor, read-only import).

Core ranges are contiguous and non-overlapping: chunk ``i`` covers
``[core_start_frame, core_end_frame]`` inclusive, the next chunk starts at
``core_end_frame + 1`` — no duplicate / dropped frame at any seam.
Overlaps are context-only (decoder warm-up), clamped at timeline edges, and
never contribute to the final timeline (``stitch.py`` trims them).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.services.s12_export.preflight import ESTIMATE_BPP

__all__ = [
    "TOOL_IDENTITY",
    "ChunkSpec",
    "ChunkPlanError",
    "DiskInsufficientError",
    "compute_content_hash",
    "plan_chunks",
    "render_window",
    "verify_seam_coverage",
    "estimate_chunk_bytes",
    "check_disk_for_run",
]

#: Tool identity pinned into every chunk content_hash so a chunk rendered by
#: a different tool/config can never be mistaken for ours (checkpoint binds
#: content + config + profile + tool identity).
TOOL_IDENTITY = "s12-t03b-chunks-v1"


class ChunkPlanError(ValueError):
    """Fail-closed chunk planning error."""


class DiskInsufficientError(ChunkPlanError):
    """Disk-aware gate: estimated bytes exceed usable space (fail-closed)."""


@dataclass(frozen=True)
class ChunkSpec:
    """One deterministic chunk boundary (pure value, no DB, no I/O)."""

    chunk_index: int
    order_index: int
    core_start_frame: int
    core_end_frame: int
    overlap_before: int
    overlap_after: int
    content_hash: str
    attempt: int = 1

    @property
    def core_frame_count(self) -> int:
        return self.core_end_frame - self.core_start_frame + 1


def _canonical(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_content_hash(
    *,
    plan_hash: str,
    checkpoint_hash: str,
    profile_id: str,
    chunk_index: int,
    core_start_frame: int,
    core_end_frame: int,
    attempt: int,
    tool_identity: str = TOOL_IDENTITY,
) -> str:
    """Bind plan + position + attempt + checkpoint + profile + tool identity."""
    raw = _canonical(
        {
            "plan": plan_hash,
            "checkpoint": checkpoint_hash,
            "profile": profile_id,
            "chunk": chunk_index,
            "core_start": core_start_frame,
            "core_end": core_end_frame,
            "attempt": attempt,
            "tool": tool_identity,
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan_chunks(
    *,
    frame_count: int,
    max_frames_per_chunk: int,
    overlap_frames: int,
    plan_hash: str,
    checkpoint_hash: str,
    profile_id: str,
    attempt: int = 1,
) -> list[ChunkSpec]:
    """Split ``[0, frame_count)`` into contiguous core ranges (fail-closed).

    Bounded-memory: every core is ``<= max_frames_per_chunk`` frames so the
    renderer only ever holds one bounded window in memory/disk.  Overlaps are
    context-only and clamped at both timeline edges.
    """
    if frame_count < 1:
        raise ChunkPlanError("frame_count must be >= 1")
    if max_frames_per_chunk < 1:
        raise ChunkPlanError("max_frames_per_chunk must be >= 1")
    if overlap_frames < 0:
        raise ChunkPlanError("overlap_frames must be >= 0")
    if overlap_frames >= max_frames_per_chunk:
        raise ChunkPlanError("overlap_frames must be < max_frames_per_chunk")
    if attempt < 1:
        raise ChunkPlanError("attempt must be >= 1")
    for name, value in (
        ("plan_hash", plan_hash),
        ("checkpoint_hash", checkpoint_hash),
    ):
        if not isinstance(value, str) or len(value) != 64:
            raise ChunkPlanError(f"{name} must be a 64-hex sha256")
    if not profile_id or len(profile_id) > 64:
        raise ChunkPlanError("profile_id must be 1..64 chars")

    specs: list[ChunkSpec] = []
    start = 0
    index = 0
    while start < frame_count:
        end = min(start + max_frames_per_chunk - 1, frame_count - 1)
        overlap_before = min(overlap_frames, start)
        overlap_after = min(overlap_frames, frame_count - 1 - end)
        specs.append(
            ChunkSpec(
                chunk_index=index,
                order_index=index,
                core_start_frame=start,
                core_end_frame=end,
                overlap_before=overlap_before,
                overlap_after=overlap_after,
                content_hash=compute_content_hash(
                    plan_hash=plan_hash,
                    checkpoint_hash=checkpoint_hash,
                    profile_id=profile_id,
                    chunk_index=index,
                    core_start_frame=start,
                    core_end_frame=end,
                    attempt=attempt,
                ),
                attempt=attempt,
            )
        )
        start = end + 1
        index += 1
    verify_seam_coverage(specs, frame_count)
    return specs


def render_window(spec: ChunkSpec, frame_count: int) -> tuple[int, int]:
    """Full render window (core + context overlaps), clamped to timeline."""
    start = max(0, spec.core_start_frame - spec.overlap_before)
    end = min(frame_count - 1, spec.core_end_frame + spec.overlap_after)
    if end < start:
        raise ChunkPlanError("render window is empty (stale spec?)")
    return start, end


def verify_seam_coverage(specs: list[ChunkSpec], frame_count: int) -> None:
    """Assert exact coverage: no gap, no overlap, no duplicate/drop at seams."""
    if not specs:
        raise ChunkPlanError("empty chunk plan")
    if specs[0].core_start_frame != 0:
        raise ChunkPlanError("first chunk must start at frame 0")
    if specs[-1].core_end_frame != frame_count - 1:
        raise ChunkPlanError("last chunk must end at frame_count - 1")
    for prev, cur in zip(specs, specs[1:]):
        if cur.core_start_frame != prev.core_end_frame + 1:
            raise ChunkPlanError(
                f"seam gap/overlap: chunk {prev.chunk_index} ends at "
                f"{prev.core_end_frame}, chunk {cur.chunk_index} starts at "
                f"{cur.core_start_frame}"
            )
    total = sum(s.core_frame_count for s in specs)
    if total != frame_count:
        raise ChunkPlanError(
            f"core coverage {total} != frame_count {frame_count} (drop/dup)"
        )


def estimate_chunk_bytes(width: int, height: int, frames: int) -> int:
    """Heuristic estimate (T01 ``ESTIMATE_BPP`` basis) for one chunk window."""
    if width < 1 or height < 1 or frames < 1:
        raise ChunkPlanError("estimate dims/frames must be >= 1")
    return int(width * height * frames * ESTIMATE_BPP)


def check_disk_for_run(
    root: str | Path,
    *,
    width: int,
    height: int,
    total_frames: int,
    margin_factor: float = 1.5,
) -> int:
    """Disk-aware gate: usable bytes must cover estimate x margin (fail-closed).

    Returns the estimate.  Raises :class:`DiskInsufficientError` when the
    managed root cannot hold the run (mirrors the T01 disk-gate semantics).
    """
    if total_frames < 1:
        raise ChunkPlanError("total_frames must be >= 1")
    estimate = int(width * height * total_frames * ESTIMATE_BPP * margin_factor)
    try:
        usable = shutil.disk_usage(str(root)).free
    except OSError as err:
        raise DiskInsufficientError(f"cannot stat disk for {root}: {err}") from err
    if usable < estimate:
        raise DiskInsufficientError(
            f"disk insufficient under {root}: usable={usable} < estimate={estimate} "
            f"({width}x{height}x{total_frames}f x{ESTIMATE_BPP}B/px x{margin_factor})"
        )
    return estimate
