"""MotionForge 2D entry point.

Run with: uvicorn app.main:app --reload
"""

from __future__ import annotations

from app.api.app import app  # noqa: F401

__all__ = ["app"]
