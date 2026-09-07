"""S12-T05 test-only FastAPI harness — mounts the PRODUCTION app plus the
unmounted T03C ``s12_export`` router (submit/status/cancel/retry) alongside
the mounted preflight, on port 8415 with an isolated MOTIONFORGE_ROOT.

Production code is untouched: the harness only *adds* the missing router
registration in a test-only process.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MOTIONFORGE_QA_MODE", "1")

from app.api.app import app  # noqa: E402
from app.api.routes import s12_export  # noqa: E402

app.include_router(s12_export.router)
