"""Shared helpers for API routes."""

from __future__ import annotations

from app.schemas import JobInfo


def job_response(info: JobInfo) -> dict:
    """Serialize JobInfo with 'status' key for frontend compatibility.

    Frontend expects 'status', backend model uses 'state'.
    """
    data = info.model_dump()
    data["status"] = data.pop("state")
    return data
