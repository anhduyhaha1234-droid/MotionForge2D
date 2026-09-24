"""Fixtures for the product-P1 public-chain suite.

The suite runs on the SHARED project conftest (``tests/conftest.py``:
loopback TestClient, per-test isolated project root + durable DB upgraded to
alembic head).  This conftest only adds read-only count helpers and makes the
registry importable regardless of pytest import mode.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


@pytest.fixture()
def state_counts() -> Any:
    """Read-only row counts from the isolated per-test durable DB."""
    from sqlalchemy import func, select

    from app.api import deps
    from app.persistence.models import (
        Job,
        Project,
        QCItem,
        S10FullApplyRun,
        S12ExportRun,
        VideoItem,
    )

    models = {
        "projects": Project,
        "video_items": VideoItem,
        "jobs": Job,
        "qc_items": QCItem,
        "s10_runs": S10FullApplyRun,
        "s12_runs": S12ExportRun,
    }

    def _counts() -> dict[str, int]:
        factory = deps._job_service.session_factory
        with factory() as session:
            return {
                name: int(session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }

    return _counts
