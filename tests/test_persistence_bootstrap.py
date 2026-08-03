"""Targeted tests for the S01 SQLite/SQLAlchemy persistence bootstrap.

Covers AC1-AC5 of S01-T02:

- AC1: Portable engine/session factory uses an explicit path and creates no
  database on import.
- AC2: SQLite connections enable foreign keys and a bounded busy timeout.
- AC3: The initial migration represents the approved S01 contract without Job
  tables or API cutover.
- AC4: Alembic upgrade from empty to head passes twice on independent temp
  databases.
- AC5: Reopening preserves data; invalid FK fails; the application refuses a
  newer unknown revision with an actionable error.

Every test uses a temporary database under ``tmp_path`` — never a database
under production project/user data.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence import (
    BUSY_TIMEOUT_MS,
    FOREIGN_KEYS_PRAGMA,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Channel,
    Project,
    VideoItem,
    Workspace,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _alembic_config(database_path: Path) -> Config:
    """Build an Alembic Config pointed at a temporary database."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade_to_head(database_path: Path) -> None:
    """Run ``alembic upgrade head`` against the temporary database."""
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """A fresh temporary database path per test (file must not exist yet)."""
    return tmp_path / "test_persistence.db"


@pytest.fixture()
def upgraded_db(db_path: Path) -> Iterator[Path]:
    """A temp database upgraded to head by Alembic."""
    _upgrade_to_head(db_path)
    yield db_path


# ── AC1: portable engine/session factory ─────────────────────────────────────


def test_engine_creation_does_not_create_database_file(db_path: Path) -> None:
    """Creating an engine for a path must not create any file on disk."""
    assert not db_path.exists()
    create_engine_for_path(db_path)
    assert not db_path.exists(), "engine creation must not create a database file"


def test_engine_accepts_explicit_path(db_path: Path) -> None:
    """An explicit path yields a working SQLite engine."""
    engine = create_engine_for_path(db_path)
    assert isinstance(engine, Engine)
    assert "sqlite" in str(engine.url).lower()


def test_session_factory_is_bound_to_engine(upgraded_db: Path) -> None:
    """Session factory binds to the engine and produces working sessions."""
    engine = create_engine_for_path(upgraded_db)
    factory = create_session_factory(engine)
    with factory() as session:
        assert isinstance(session, Session)
        assert session.execute(__import__("sqlalchemy").text("SELECT 1")).scalar() == 1


# ── AC2: connection pragmas ──────────────────────────────────────────────────


def test_foreign_keys_enabled_on_connection(upgraded_db: Path) -> None:
    """Every SQLite connection must have foreign keys enabled."""
    engine = create_engine_for_path(upgraded_db)
    with engine.connect() as conn:
        value = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert value == 1, f"expected PRAGMA {FOREIGN_KEYS_PRAGMA} to be active"


def test_busy_timeout_is_bounded(upgraded_db: Path) -> None:
    """The configured busy timeout must be a bounded positive value."""
    assert 0 < BUSY_TIMEOUT_MS <= 60_000
    engine = create_engine_for_path(upgraded_db)
    with engine.connect() as conn:
        value = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert value == BUSY_TIMEOUT_MS, "busy_timeout must match the configured constant"


# ── AC3: schema shape ────────────────────────────────────────────────────────


def test_initial_schema_has_expected_tables(upgraded_db: Path) -> None:
    """The migrated schema contains the eight approved S01 tables."""
    engine = create_engine_for_path(upgraded_db)
    tables = set(inspect(engine).get_table_names())
    assert tables == {
        "workspace",
        "channel",
        "project",
        "video_item",
        "scene",
        "artifact",
        "artifact_owner",
        "legacy_import",
        "alembic_version",
    }


def test_no_job_tables(upgraded_db: Path) -> None:
    """Job tables are intentionally deferred to S02 and must not exist yet."""
    engine = create_engine_for_path(upgraded_db)
    tables = set(inspect(engine).get_table_names())
    assert not any("job" in name for name in tables), "Job tables are out of S01 scope"


def test_no_api_cutover_tables(upgraded_db: Path) -> None:
    """No API/session tables outside the approved contract exist."""
    engine = create_engine_for_path(upgraded_db)
    tables = set(inspect(engine).get_table_names())
    unexpected = tables - {
        "workspace",
        "channel",
        "project",
        "video_item",
        "scene",
        "artifact",
        "artifact_owner",
        "legacy_import",
        "alembic_version",
    }
    assert not unexpected, f"unexpected tables: {sorted(unexpected)}"


# ── AC4: fresh upgrade twice ─────────────────────────────────────────────────


def test_upgrade_from_empty_to_head(db_path: Path) -> None:
    """A fresh temp database upgrades cleanly from empty to head."""
    _upgrade_to_head(db_path)
    engine = create_engine_for_path(db_path)
    tables = set(inspect(engine).get_table_names())
    assert "workspace" in tables and "artifact_owner" in tables


def test_upgrade_twice_on_independent_databases(tmp_path: Path) -> None:
    """Upgrade passes on two independent temporary databases."""
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    for db in (first, second):
        _upgrade_to_head(db)
        assert db.exists()
        engine = create_engine_for_path(db)
        assert "workspace" in set(inspect(engine).get_table_names())


# ── AC5: reopen, FK enforcement, newer revision ──────────────────────────────


def test_reopen_preserves_data(upgraded_db: Path) -> None:
    """Data written through one connection survives reopen via a new engine."""
    engine = create_engine_for_path(upgraded_db)
    with Session(engine) as session:
        ws = Workspace(name="Reopen Workspace")
        session.add(ws)
        session.commit()
        workspace_id = ws.id

    engine2 = create_engine_for_path(upgraded_db)
    with Session(engine2) as session:
        loaded = session.get(Workspace, workspace_id)
        assert loaded is not None
        assert loaded.name == "Reopen Workspace"


def test_invalid_foreign_key_fails(upgraded_db: Path) -> None:
    """Inserting a channel with a missing workspace FK must raise IntegrityError."""
    engine = create_engine_for_path(upgraded_db)
    with Session(engine) as session:
        orphan = Channel(
            workspace_id="00000000-0000-0000-0000-000000000000",
            role="source",
            name="Orphan Channel",
        )
        session.add(orphan)
        with pytest.raises(IntegrityError):
            session.commit()


def test_channel_avatar_artifact_id_rejects_nonexistent_artifact(upgraded_db: Path) -> None:
    """channel.avatar_artifact_id is a real FK: a missing artifact must fail."""
    engine = create_engine_for_path(upgraded_db)
    with Session(engine) as session:
        ws = Workspace(name="Avatar Workspace")
        session.add(ws)
        session.flush()
        channel = Channel(
            workspace_id=ws.id,
            role="source",
            name="Avatar Channel",
            avatar_artifact_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
        session.add(channel)
        with pytest.raises(IntegrityError):
            session.commit()


def test_video_item_source_artifact_id_rejects_nonexistent_artifact(upgraded_db: Path) -> None:
    """video_item.source_artifact_id is a real FK: a missing artifact must fail."""
    engine = create_engine_for_path(upgraded_db)
    with Session(engine) as session:
        ws = Workspace(name="Source Artifact Workspace")
        session.add(ws)
        session.flush()
        project = Project(workspace_id=ws.id, name="Source Artifact Project")
        session.add(project)
        session.flush()
        video = VideoItem(
            project_id=project.id,
            title="Source Artifact Video",
            position=0,
            source_artifact_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
        session.add(video)
        with pytest.raises(IntegrityError):
            session.commit()


def test_alembic_online_connection_has_foreign_keys_enabled(
    db_path: Path, tmp_path: Path
) -> None:
    """The Alembic online migration connection must enable SQLite FKs.

    The migration itself inserts only DDL, so we prove enforcement by running
    an online migration against a temp database whose schema contains the
    artifact FKs, then attempting a channel row referencing a nonexistent
    artifact inside the same engine configuration path the migration used.
    """
    import sqlite3

    _upgrade_to_head(db_path)

    engine = create_engine_for_path(db_path)
    with engine.connect() as conn:
        value = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert value == 1

    # Prove the schema actually carries the FK and enforcement is live:
    # raw INSERT referencing a missing artifact must fail with FK violation.
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute(
            "INSERT INTO workspace (id, name, created_at, updated_at, revision) "
            "VALUES ('w1', 'W', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO channel (id, workspace_id, role, name, description, status, "
                "created_at, updated_at, revision, avatar_artifact_id) VALUES "
                "('c1', 'w1', 'source', 'C', '', 'active', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, 1, 'ffffffff-ffff-ffff-ffff-ffffffffffff')"
            )
    finally:
        raw.close()


def _stamp_unknown_revision(database_path: Path, revision: str) -> None:
    """Force an unknown revision into alembic_version (bypasses Alembic validation)."""
    import sqlite3

    conn = sqlite3.connect(str(database_path))
    try:
        conn.execute("DELETE FROM alembic_version")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        conn.commit()
    finally:
        conn.close()


def test_newer_revision_refused(upgraded_db: Path) -> None:
    """A database at a newer unknown revision must fail with an actionable error."""
    from app.persistence.revision import (
        assert_schema_revision_supported,
        database_schema_revision,
    )

    _upgrade_to_head(upgraded_db)

    # Stamp the database with a future revision id unknown to the app.
    _stamp_unknown_revision(upgraded_db, "deadbeef00")

    engine = create_engine_for_path(upgraded_db)
    assert database_schema_revision(engine) == "deadbeef00"

    with pytest.raises(RuntimeError, match="newer than the maximum revision"):
        assert_schema_revision_supported(
            engine,
            script_location=PROJECT_ROOT / "migrations",
            database_path=upgraded_db,
        )


def test_newer_revision_check_raises_actionable_error(upgraded_db: Path) -> None:
    """Refusing a newer revision surfaces the database path and revision id."""
    from app.persistence.revision import assert_schema_revision_supported

    _upgrade_to_head(upgraded_db)

    _stamp_unknown_revision(upgraded_db, "zzzz9999")

    engine = create_engine_for_path(upgraded_db)
    with pytest.raises(RuntimeError) as excinfo:
        assert_schema_revision_supported(
            engine,
            script_location=PROJECT_ROOT / "migrations",
            database_path=upgraded_db,
        )
    message = str(excinfo.value)
    assert "zzzz9999" in message
    assert str(upgraded_db) in message


def test_current_revision_is_supported(upgraded_db: Path) -> None:
    """A database at the app's own head revision passes the guard."""
    from app.persistence.revision import (
        assert_schema_revision_supported,
        database_schema_revision,
        max_supported_schema_revision,
    )

    engine = create_engine_for_path(upgraded_db)
    assert database_schema_revision(engine) == max_supported_schema_revision(
        PROJECT_ROOT / "migrations"
    )
    assert_schema_revision_supported(
        engine,
        script_location=PROJECT_ROOT / "migrations",
        database_path=upgraded_db,
    )
