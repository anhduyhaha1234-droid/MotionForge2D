"""MotionForge 2D entry point.

Run with: uvicorn app.main:app --reload
"""

from __future__ import annotations

import cv2

cv2.setNumThreads(8)

from app.api.app import app  # noqa: E402, F401

__all__ = ["app"]
