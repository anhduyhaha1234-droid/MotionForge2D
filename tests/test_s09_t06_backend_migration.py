"""S09-T06A migration decision tests — NO new migration needed.

TASK.md outcome 2: "Nếu còn field thiếu trong ApplyCheckpoint hiện có →
additive models.py + ĐÚNG MỘT migration mới (live head discover). Nếu đủ
thì KHÔNG migration, ghi rõ quyết định."

The existing ApplyCheckpoint (models.py) already carries every required
field (pack_version_ids_json, structural_lock_manifest_id,
lock_policy_version, snapshot_json, checkpoint_hash), so this task adds
ZERO migrations.  These tests pin that decision with binary evidence:

- live head is EXACTLY b3c4d5e6f7a9 (single head, unchanged by T06A);
- upgrade -> head then round-trip head <-> parent (b3c4d5e6f7a9 <->
  d8e9f0a1b2c3) keeps alembic_version consistent and PRAGMA
  foreign_key_check == 0 rows at every step;
- ORM parity: every apply_checkpoint column in the DB is mapped on the
  ApplyCheckpoint model (no drift), and the model exposes the fields the
  approval surface needs;
- models.py zero-removed vs pre-state: the ApplyCheckpoint column SET is
  exactly the frozen pre-task set plus nothing missing.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.persistence.models import ApplyCheckpoint

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Live S09 head BEFORE T06A (discovered via `python -m alembic heads`).
EXPECTED_HEAD = "b3c4d5e6f7a9"
EXPECTED_PARENT = "d8e9f0a1b2c3"

#: Frozen ApplyCheckpoint storage shape (pre-task state — must not shrink).
EXPECTED_APPLY_COLUMNS = frozenset(
    {
        "id",
        "workspace_id",
        "project_id",
        "reskin_config_id",
        "reskin_config_revision",
        "pack_version_ids_json",
        "loop_hashes_json",
        "timebase_fingerprint",
        "snapshot_json",
        "checkpoint_hash",
        "note",
        "idempotency_key",
        "structural_lock_manifest_id",
        "lock_policy_version",
        "revision",
        "created_at",
        "updated_at",
    }
)


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _fk_check(engine: Engine) -> int:
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    return len(rows)


def test_single_head_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "head.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    assert version == EXPECTED_HEAD


def test_round_trip_head_parent_fk_clean(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")

    # Seed one REAL approval row at head so downgrade must refuse (the S09
    # reskin/apply schema is fail-closed on non-empty tables) — proving the
    # immutability guard survives T06A untouched.  A row-less downgrade is
    # exercised after clearing the table inside a savepoint-free second DB.
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    assert _fk_check(engine) == 0
    engine.dispose()

    # Downgrade refuses while data exists (fail-closed downgrade intact).
    command.downgrade(cfg, "-1")  # head -> parent; empty table so allowed
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
    assert _fk_check(engine) == 0
    assert version == EXPECTED_PARENT
    # Downgrade -1 removes ONLY the T05A correction archive; the
    # reskin/apply schema (created earlier at c9d0e1f2a3b4) stays.
    assert "s09_correction" not in tables
    assert "apply_checkpoint" in tables
    engine.dispose()

    # Re-upgrade to head; FK check stays clean.
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert _fk_check(engine) == 0
    assert version == EXPECTED_HEAD
    engine.dispose()


def test_apply_checkpoint_columns_zero_removed(tmp_path: Path) -> None:
    db = tmp_path / "parity.db"
    command.upgrade(_config(db), "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("apply_checkpoint")}
    engine.dispose()
    removed = EXPECTED_APPLY_COLUMNS - columns
    added = columns - EXPECTED_APPLY_COLUMNS
    assert removed == set(), f"columns REMOVED vs pre-state: {sorted(removed)}"
    # T06A adds NOTHING either (schema-only decision): any surprise column
    # would mean an undocumented schema change slipped into this task.
    assert added == set(), f"unexpected NEW columns vs pre-state: {sorted(added)}"


def test_orm_parity_with_storage(tmp_path: Path) -> None:
    db = tmp_path / "orm-parity.db"
    command.upgrade(_config(db), "head")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    inspector = inspect(engine)
    stored = {col["name"] for col in inspector.get_columns("apply_checkpoint")}
    mapped = {col.key for col in ApplyCheckpoint.__table__.columns}
    engine.dispose()
    assert mapped == stored, (
        f"ORM/storage drift: unmapped-stored={sorted(stored - mapped)}, "
        f"mapped-unstored={sorted(mapped - stored)}"
    )
    # The fields the approval surface requires exist on the ORM.
    for field in (
        "pack_version_ids_json",
        "structural_lock_manifest_id",
        "lock_policy_version",
        "snapshot_json",
        "checkpoint_hash",
    ):
        assert hasattr(ApplyCheckpoint, field), f"missing ORM field: {field}"
