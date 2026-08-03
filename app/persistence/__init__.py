"""Persistence bootstrap for MotionForge 2D (SQLAlchemy 2.x + SQLite)."""

from app.persistence.engine import (
    BUSY_TIMEOUT_MS,
    FOREIGN_KEYS_PRAGMA,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.revision import (
    SCHEMA_REVISION_REFUSED_MESSAGE,
    assert_schema_revision_supported,
    database_schema_revision,
    max_supported_schema_revision,
)

__all__ = [
    "BUSY_TIMEOUT_MS",
    "FOREIGN_KEYS_PRAGMA",
    "SCHEMA_REVISION_REFUSED_MESSAGE",
    "assert_schema_revision_supported",
    "create_engine_for_path",
    "create_session_factory",
    "database_schema_revision",
    "max_supported_schema_revision",
]
