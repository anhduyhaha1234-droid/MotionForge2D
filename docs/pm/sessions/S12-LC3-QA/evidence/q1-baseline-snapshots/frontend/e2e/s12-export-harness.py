"""S12-T05 test-only FastAPI harness — production app AS-IS.

The T03C ``s12_export`` router (submit/status/cancel/retry) is ALREADY
mounted on the production app (app/api/app.py:207, canonical post W4),
so the harness adds NOTHING — no router injection, no middleware. It
only pins an isolated MOTIONFORGE_ROOT/DB via environment and serves
the production app on the task port.

Production code is untouched.
"""

from __future__ import annotations

import os

os.environ.setdefault("MOTIONFORGE_QA_MODE", "1")

from app.api.app import app  # noqa: E402

__all__ = ["app"]
