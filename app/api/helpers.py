"""Shared helpers for API routes."""

from __future__ import annotations

from pathlib import Path

from app.schemas import JobInfo


def find_frame_path(scene_dir: Path, frame_index: int) -> Path | None:
    """Find a frame file trying jpg/jpeg/png in order.

    Args:
        scene_dir: Directory containing frame files.
        frame_index: Zero-based frame index.

    Returns:
        Path to frame file, or None if not found.
    """
    for ext in ("jpg", "jpeg", "png"):
        p = scene_dir / f"frame_{frame_index:06d}.{ext}"
        if p.exists():
            return p
    return None


def job_response(info: JobInfo) -> dict:
    """Serialize JobInfo with 'status' key for frontend compatibility.

    Frontend expects 'status', backend model uses 'state'.
    """
    data = info.model_dump()
    data["status"] = data.pop("state")
    return data
