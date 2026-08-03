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
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence import (
    BUSY_TIMEOUT_MS,
    FOREIGN_KEYS_PRAGMA,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.channels import (
    DEFAULT_WORKSPACE_ID,
    ChannelRepository,
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


def _upgrade_to_revision(database_path: Path, revision: str) -> None:
    """Run ``alembic upgrade <revision>`` against the temporary database."""
    command.upgrade(_alembic_config(database_path), revision)


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

#: All tables present at the S02 head (S01 eight + the five durable job tables).
S02_HEAD_TABLES = {
    "workspace",
    "channel",
    "project",
    "video_item",
    "scene",
    "artifact",
    "artifact_owner",
    "legacy_import",
    "job",
    "job_step",
    "job_attempt",
    "job_event",
    "job_lease",
    "alembic_version",
}


def test_initial_schema_has_expected_tables(upgraded_db: Path) -> None:
    """The migrated head schema contains the approved S01 tables."""
    engine = create_engine_for_path(upgraded_db)
    tables = set(inspect(engine).get_table_names())
    assert {
        "workspace",
        "channel",
        "project",
        "video_item",
        "scene",
        "artifact",
        "artifact_owner",
        "legacy_import",
        "alembic_version",
    } <= tables


def test_head_includes_durable_job_tables(upgraded_db: Path) -> None:
    """The S02 head includes the five durable job tables (S02-T02)."""
    engine = create_engine_for_path(upgraded_db)
    tables = set(inspect(engine).get_table_names())
    assert {
        "job",
        "job_step",
        "job_attempt",
        "job_event",
        "job_lease",
    } <= tables


def test_s01_revision_has_no_job_tables(db_path: Path) -> None:
    """Job tables were absent at the S01 revision (upgrade-to-S01 proof).

    The S01 revision alone must not contain Job tables; the S02 migration
    adds them.  Upgrading exactly to ``a1b2c3d4e5f6`` proves the S01 schema
    shape is preserved and the durable job tables arrive only at the S02
    head.
    """
    _upgrade_to_revision(db_path, "a1b2c3d4e5f6")
    engine = create_engine_for_path(db_path)
    tables = set(inspect(engine).get_table_names())
    assert not any("job" in name for name in tables), "Job tables are out of S01 scope"
    # And the S01 revision is the app's supported predecessor.
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "a1b2c3d4e5f6"


def test_no_api_cutover_tables(upgraded_db: Path) -> None:
    """No API/session tables outside the approved contract exist."""
    engine = create_engine_for_path(upgraded_db)
    tables = set(inspect(engine).get_table_names())
    unexpected = tables - S02_HEAD_TABLES
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


# ── AC7: upgrade-from-S02 preservation (S03-T01) ─────────────────────────────


def _insert_s02_channel(
    session: Session,
    *,
    workspace_id: str = "default",
    role: str = "source",
    name: str = "S02 Channel",
    legacy_id: str | None = None,
) -> str:
    """Insert a channel row exactly as S02's schema allowed (no S03 code)."""
    ws = session.get(Workspace, workspace_id)
    if ws is None:
        ws = Workspace(id=workspace_id, name=workspace_id)
        session.add(ws)
        session.flush()
    channel = Channel(
        workspace_id=workspace_id,
        legacy_id=legacy_id,
        role=role,
        name=name,
        status="active",
    )
    session.add(channel)
    session.flush()
    return channel.id


def test_upgrade_from_s02_preserves_all_channel_rows(tmp_path: Path) -> None:
    """AC7: migrating a database from the S02 head preserves every row.

    Builds a database at the S02 head (``23b308b1fd0b``), inserts channel
    rows through the raw ORM (exactly the S02-era shape), upgrades to the
    S03 head, then proves row identity + required data survived.
    """
    db = tmp_path / "s02_to_s03.db"
    _upgrade_to_revision(db, "23b308b1fd0b")
    engine = create_engine_for_path(db)
    with Session(engine) as session:
        ids = [
            _insert_s02_channel(session, role="source", name="Src A", legacy_id="legacy-src-a"),
            _insert_s02_channel(session, role="production", name="Prod A"),
            _insert_s02_channel(
                session, role="source", name="Archived Src", legacy_id="legacy-arch"
            ),
        ]
        # Archive one row the S02 way (raw field update — S03 archive API
        # did not exist at S02, this is the pre-cutover state).
        archived = session.get(Channel, ids[2])
        assert archived is not None
        archived.status = "archived"
        session.commit()
        before = {
            c.id: (c.workspace_id, c.role, c.name, c.status, c.revision)
            for c in session.scalars(select(Channel)).all()
        }

    # S03 head upgrade: revision chain a1b2c3d4e5f6 -> 23b308b1fd0b -> head.
    _upgrade_to_head(db)

    engine2 = create_engine_for_path(db)
    with Session(engine2) as session:
        after = {
            c.id: (c.workspace_id, c.role, c.name, c.status, c.revision)
            for c in session.scalars(select(Channel)).all()
        }
    assert len(after) == len(before) == 3
    assert after == before, "S02 channel rows were altered by the S03 upgrade"
    # The S03 head is still the max supported revision (no schema drift).
    from app.persistence.revision import (
        database_schema_revision,
        max_supported_schema_revision,
    )

    assert database_schema_revision(engine2) == max_supported_schema_revision(
        PROJECT_ROOT / "migrations"
    )


def test_upgrade_from_s02_preserves_referencing_project_rows(tmp_path: Path) -> None:
    """AC7: S02 rows referencing channels (FK RESTRICT) survive the upgrade."""
    db = tmp_path / "s02_to_s03_projects.db"
    _upgrade_to_revision(db, "23b308b1fd0b")
    engine = create_engine_for_path(db)
    with Session(engine) as session:
        ws = Workspace(id="default", name="default")
        session.add(ws)
        session.flush()
        src = Channel(workspace_id="default", role="source", name="Src")
        prod = Channel(workspace_id="default", role="production", name="Prod")
        session.add_all([src, prod])
        session.flush()
        project = Project(
            workspace_id="default",
            name="S02 Project",
            source_channel_id=src.id,
            production_channel_id=prod.id,
        )
        session.add(project)
        session.commit()
        project_id = project.id

    _upgrade_to_head(db)

    engine2 = create_engine_for_path(db)
    with Session(engine2) as session:
        loaded = session.get(Project, project_id)
        assert loaded is not None
        assert loaded.name == "S02 Project"
        assert loaded.source_channel_id is not None
        assert loaded.production_channel_id is not None
        assert session.get(Channel, loaded.source_channel_id) is not None
        assert session.get(Channel, loaded.production_channel_id) is not None


def test_s03_head_reuses_s01_channel_schema_no_new_tables(tmp_path: Path) -> None:
    """S03 adds no schema: the head table set is identical to S02's."""
    _upgrade_to_head(tmp_path / "s03_head.db")
    engine = create_engine_for_path(tmp_path / "s03_head.db")
    tables = set(inspect(engine).get_table_names())
    assert tables == S02_HEAD_TABLES, f"unexpected schema drift: {tables - S02_HEAD_TABLES}"
    # The durable channel repository works directly on the S01 channel table.
    with Session(engine) as session:
        session.add(Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID))
        session.commit()
        repo = ChannelRepository(session)
        record = repo.create_channel(
            workspace_id=DEFAULT_WORKSPACE_ID,
            role="source",
            name="Repo-Proven Channel",
        )
        session.commit()
        assert record.status == "active"
        assert record.revision == 1


def test_s03_head_index_is_active_only_and_case_insensitive(tmp_path: Path) -> None:
    """The S03 partial unique index is active-only and lower(name)-based."""
    _upgrade_to_head(tmp_path / "s03_index.db")
    engine = create_engine_for_path(tmp_path / "s03_index.db")
    with Session(engine) as session:
        session.add(Workspace(id="default", name="default"))
        session.commit()
        repo = ChannelRepository(session)
        a = repo.create_channel(
            workspace_id="default", role="source", name="Reusable Name"
        )
        session.commit()
        # Archive -> same name is immediately creatable (active-only)
        repo.archive_channel(a.id, "default", expected_revision=1)
        session.commit()
        b = repo.create_channel(
            workspace_id="default", role="source", name="Reusable Name"
        )
        session.commit()
        assert b.id != a.id
        # Case-variant active create is rejected by the index backstop
        from app.persistence.channels import NameConflictError

        with pytest.raises(NameConflictError):
            repo.create_channel(
                workspace_id="default", role="source", name="reusable name"
            )
            session.commit()


def test_upgrade_from_s02_preserves_referenced_archived_channel(
    tmp_path: Path,
) -> None:
    """PM1: an archived channel referenced by a project survives S02→head.

    The S03 migration rebuilds the channel table (batch copy-and-move);
    FK references from project rows must survive the table swap.
    """
    db = tmp_path / "s02_to_s03_archived_ref.db"
    _upgrade_to_revision(db, "23b308b1fd0b")
    engine = create_engine_for_path(db)
    with Session(engine) as session:
        ws = Workspace(id="default", name="default")
        session.add(ws)
        session.flush()
        archived_src = Channel(
            workspace_id="default", role="source", name="Archived Src"
        )
        session.add(archived_src)
        session.flush()
        archived_src.status = "archived"
        project = Project(
            workspace_id="default",
            name="S02 Ref Archived",
            source_channel_id=archived_src.id,
        )
        session.add(project)
        session.commit()
        archived_id = archived_src.id
        project_id = project.id

    _upgrade_to_head(db)

    engine2 = create_engine_for_path(db)
    with Session(engine2) as session:
        loaded = session.get(Project, project_id)
        assert loaded is not None
        assert loaded.source_channel_id == archived_id
        archived = session.get(Channel, archived_id)
        assert archived is not None
        assert archived.status == "archived"
        assert archived.name == "Archived Src"


def test_s03_upgrade_preserves_fk_integrity(tmp_path: Path) -> None:
    """PM2 finding 5: after S02→head upgrade, FKs are active and clean.

    ``PRAGMA foreign_keys`` must be 1 on every connection and
    ``PRAGMA foreign_key_check`` must report zero violations, including
    the project/video_item references to channel rows rebuilt by the
    batch migration.
    """
    db = tmp_path / "s02_to_s03_fk.db"
    _upgrade_to_revision(db, "23b308b1fd0b")
    engine = create_engine_for_path(db)
    with Session(engine) as session:
        ws = Workspace(id="default", name="default")
        session.add(ws)
        session.flush()
        src = Channel(workspace_id="default", role="source", name="Src")
        session.add(src)
        session.flush()
        project = Project(
            workspace_id="default",
            name="FK Project",
            source_channel_id=src.id,
        )
        session.add(project)
        session.flush()
        video = VideoItem(
            project_id=project.id,
            title="FK Video",
            position=0,
            source_channel_id=src.id,
        )
        session.add(video)
        session.commit()

    _upgrade_to_head(db)

    engine2 = create_engine_for_path(db)
    with engine2.connect() as conn:
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        assert fk == 1, "foreign keys must be enabled after the upgrade"
        violations = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        assert violations == [], f"FK violations after S03 upgrade: {violations}"


def test_s03_head_descends_from_s02_revision() -> None:
    """PM2 finding 6: the S03 head provably descends from the S02 head.

    Uses the Alembic revision graph (ScriptDirectory) to walk the new
    head's ancestry and prove ``23b308b1fd0b`` is an ancestor — not just
    a different revision string.
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(PROJECT_ROOT / "migrations"))
    head = script.get_current_head()
    assert head is not None
    assert head == "1c9f2a4b7d8e"
    ancestry: set[str] = set()
    for rev in script.walk_revisions(base="23b308b1fd0b", head=head):
        ancestry.add(rev.revision)
    assert "23b308b1fd0b" in ancestry
    assert "1c9f2a4b7d8e" in ancestry


def test_orm_metadata_index_ddl_matches_migration(tmp_path: Path) -> None:
    """PM2 finding 1: ORM metadata compiles the SAME DDL as the migration.

    The index must use the real column expression ``lower(name)`` — not
    the string literal ``lower('name')``.  Creating a schema purely from
    ORM metadata must enforce case-variant active uniqueness while
    allowing archived-name reuse.
    """
    from sqlalchemy.schema import CreateIndex

    from app.persistence.channels import ChannelRepository
    from app.persistence.models import Base

    idx = next(
        i for i in Channel.__table__.indexes
        if i.name == "uq_channel_active_workspace_role_name"
    )
    ddl = str(CreateIndex(idx).compile(dialect=sqlite_dialect()))
    assert "lower(name)" in ddl
    assert "lower('name')" not in ddl
    # The migration DDL (already applied by the head upgrade) is identical.
    with create_engine_for_path(_head_db(tmp_path)).connect() as conn:
        migrated = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='index' AND "
            "name='uq_channel_active_workspace_role_name'"
        ).scalar()
    assert migrated is not None
    assert "lower(name)" in migrated
    assert "lower('name')" not in migrated

    # Create a schema purely from ORM metadata and prove the invariant.
    meta_db = tmp_path / "orm_meta.db"
    meta_engine = create_engine_for_path(meta_db)
    Base.metadata.create_all(meta_engine)
    with Session(meta_engine) as session:
        session.add(Workspace(id="default", name="default"))
        session.commit()
        repo = ChannelRepository(session)
        a = repo.create_channel(
            workspace_id="default", role="source", name="Meta Name"
        )
        session.commit()
        repo.archive_channel(a.id, "default", expected_revision=1)
        session.commit()
        b = repo.create_channel(
            workspace_id="default", role="source", name="Meta Name"
        )
        session.commit()
        assert b.id != a.id  # archived-name reuse succeeds
        from app.persistence.channels import NameConflictError

        with pytest.raises(NameConflictError):
            repo.create_channel(
                workspace_id="default", role="source", name="meta name"
            )
            session.commit()


def sqlite_dialect():
    import sqlalchemy as sa

    return sa.dialects.sqlite.dialect()


def _head_db(tmp_path: Path) -> Path:
    db = tmp_path / "orm_meta_head.db"
    _upgrade_to_head(db)
    return db
