"""S07-T01 migration tests — project_cast_mapping schema.

Covers every migration invariant of
``migrations/versions/b2c3d4e5f6a7b_s07_project_cast_mapping.py``
(revision ``b2c3d4e5f6a7b``, down_revision ``a0b1c2d3e4f5``):
- single Alembic head
- migration/ORM parity (tables, columns, nullability, CHECK, FK, indexes, defaults)
- upgrade -> downgrade -> upgrade byte-identical on empty graph
- downgrade with ANY row present REFUSES atomically (no partial mutation)
- PRAGMA integrity_check = ok and foreign_key_check = empty
- FK RESTRICT fail closed (deleting referenced project/role/character/pack refused)

Runs on fresh isolated temp DB files only (never MAIN).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.persistence import create_engine_for_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
PRE = "a0b1c2d3e4f5"
HEAD = "b2c3d4e5f6a7b"
NEW_TABLES = ("project_cast_mapping",)
WS = "ws-test-s07mig"


def _config(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _schema_signature(db: Path) -> dict[str, object]:
    with create_engine_for_path(db).connect() as conn:
        tables = {
            str(r[0]): str(r[1])
            for r in conn.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ).all()
        }
        indexes = sorted(
            (str(r[0]), str(r[1]), str(r[2]))
            for r in conn.execute(
                text(
                    "SELECT name, tbl_name, sql FROM sqlite_master "
                    "WHERE type='index'"
                )
            ).all()
        )
        return {"tables": tables, "indexes": indexes}


def _revision(db: Path) -> str | None:
    with create_engine_for_path(db).connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _integrity(db: Path) -> str:
    with create_engine_for_path(db).connect() as conn:
        return str(conn.execute(text("PRAGMA integrity_check")).scalar())


def _fk_violations(db: Path) -> list[tuple]:
    with create_engine_for_path(db).connect() as conn:
        return [tuple(r) for r in conn.execute(text("PRAGMA foreign_key_check")).fetchall()]


def _seed_parents(db: Path) -> None:
    with create_engine_for_path(db).begin() as conn:
        conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        conn.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"),
            {"w": WS},
        )
        conn.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) "
                "VALUES ('v1','p1','Vid',0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) "
                "VALUES ('s1','v1',0,0,10,0,1000,'pending')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) "
                "VALUES ('r1',:w,'p1','v1','1','Char','character','confirmed')"
            ),
            {"w": WS},
        )
        conn.execute(
            text("INSERT INTO character(id,workspace_id,name,code) VALUES ('c1',:w,'Hero','hero')"),
            {"w": WS},
        )
        conn.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) "
                "VALUES ('pv1','c1',:w,1,'published')"
            ),
            {"w": WS},
        )


def _insert_mapping(db: Path, mid: str, key: str | None = None) -> None:
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_cast_mapping("
                "id,workspace_id,project_id,object_role_id,character_id,"
                "pack_version_id,idempotency_key,revision) "
                "VALUES (:id,:w,'p1','r1','c1','pv1',:key,1)"
            ),
            {"id": mid, "w": WS, "key": key},
        )


def test_revision_chain_and_single_head() -> None:
    import migrations.versions.b2c3d4e5f6a7b_s07_project_cast_mapping as mig

    assert mig.revision == HEAD
    assert mig.down_revision == PRE
    assert mig.branch_labels is None
    assert mig.depends_on is None

    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(PROJECT_ROOT / "migrations"))
    heads = script.get_heads()
    assert heads == [HEAD], f"unexpected Alembic head(s): {heads}"


def test_upgrade_downgrade_upgrade_empty_graph_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _config(db)

    command.upgrade(cfg, "head")
    assert _revision(db) == HEAD
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []
    up_once = _schema_signature(db)

    command.downgrade(cfg, PRE)
    assert _revision(db) == PRE
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []
    with create_engine_for_path(db).connect() as conn:
        names = inspect(conn).get_table_names()
    for t in NEW_TABLES:
        assert t not in names, f"downgrade left {t!r} behind"
    downgraded = _schema_signature(db)

    command.upgrade(cfg, "head")
    assert _revision(db) == HEAD
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []
    assert _schema_signature(db) == up_once, "re-upgrade DDL differs"
    assert set(downgraded["tables"]) < set(up_once["tables"])


def test_downgrade_refused_atomically_with_any_row(tmp_path: Path) -> None:
    db = tmp_path / "refuse.db"
    cfg = _config(db)

    command.upgrade(cfg, "head")
    _seed_parents(db)
    _insert_mapping(db, "m1", key="k1")

    before = _schema_signature(db)
    with create_engine_for_path(db).connect() as conn:
        before_cnt = conn.execute(text("SELECT COUNT(*) FROM project_cast_mapping")).scalar()

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE)

    assert _revision(db) == HEAD
    assert _schema_signature(db) == before
    with create_engine_for_path(db).connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM project_cast_mapping")).scalar()
    assert cnt == before_cnt
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []

    command.upgrade(cfg, "head")
    assert _revision(db) == HEAD
    assert _schema_signature(db) == before


def test_migration_orm_parity(tmp_path: Path) -> None:
    from app.persistence.models import Base

    mig_db = tmp_path / "mig.db"
    cfg = _config(mig_db)
    command.upgrade(cfg, "head")

    orm_db = tmp_path / "orm.db"
    engine = create_engine_for_path(orm_db)
    Base.metadata.create_all(engine)

    def tables(engine_path: Path) -> dict[str, dict]:
        out: dict[str, dict] = {}
        with create_engine_for_path(engine_path).connect() as conn:
            inspector = inspect(conn)
            for t in NEW_TABLES:
                out[t] = {
                    "cols": {
                        c["name"]: (str(c["type"]), c["nullable"])
                        for c in inspector.get_columns(t)
                    },
                    "checks": sorted(
                        (c["name"], str(c["sqltext"]))
                        for c in inspector.get_check_constraints(t)
                    ),
                    "fks": sorted(
                        (
                            fk["referred_table"],
                            tuple(fk["referred_columns"]),
                            tuple(fk["constrained_columns"]),
                            fk.get("options", {}).get("ondelete"),
                        )
                        for fk in inspector.get_foreign_keys(t)
                    ),
                    "indexes": sorted(
                        (
                            i["name"],
                            tuple(i["column_names"] or []),
                            bool(i.get("unique")),
                            str(i.get("dialect_options", {}).get("sqlite_where")),
                        )
                        for i in inspector.get_indexes(t)
                    ),
                }
        return out

    mig = tables(mig_db)
    orm = tables(orm_db)
    assert mig == orm, "migration schema differs from ORM"


def test_fk_restrict_fail_closed(tmp_path: Path) -> None:
    """Deleting a referenced row while mapping exists must fail (RESTRICT)."""
    db = tmp_path / "fkrestrict.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_parents(db)
    _insert_mapping(db, "m1")

    # Try to delete project while mapping exists
    with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
        conn.execute(text("DELETE FROM project WHERE id='p1'"))

    # Try to delete object_role while mapping exists
    with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
        conn.execute(text("DELETE FROM object_role WHERE id='r1'"))

    # Try to delete character while mapping exists
    with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
        conn.execute(text("DELETE FROM character WHERE id='c1'"))

    # Try to delete pack_version while mapping exists
    with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
        conn.execute(text("DELETE FROM character_pack_version WHERE id='pv1'"))

    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []


def test_workspace_idempotency_partial_index_exists(tmp_path: Path) -> None:
    db = tmp_path / "idem.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(
            text(
                "SELECT \"unique\", \"partial\" FROM pragma_index_list('project_cast_mapping') "
                "WHERE name='uq_project_cast_mapping_workspace_idempotency'"
            )
        ).first()
        assert row, "workspace idempotency index missing"
        assert row[0] == 1 and row[1] == 1, "must be unique+partial"
        sql = conn.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='uq_project_cast_mapping_workspace_idempotency'"
            )
        ).scalar()
        assert sql is not None and "idempotency_key IS NOT NULL" in str(sql)


def test_foreign_key_check_clean_after_inserts(tmp_path: Path) -> None:
    db = tmp_path / "fkclean.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_parents(db)
    _insert_mapping(db, "m1", key="k1")
    # Create second parents for a different project/role to avoid unique violation
    with create_engine_for_path(db).begin() as conn:
        conn.execute(  # noqa: E501
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p2',:w,'Proj2')"), {"w": WS}  # noqa: E501
        )
        conn.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) VALUES ('v2','p2','Vid2',1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) VALUES ('s2','v2',0,0,10,0,1000,'pending')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) VALUES ('r2',:w,'p2','v2','1','Char2','character','confirmed')"  # noqa: E501
            ),
            {"w": WS},
        )
        conn.execute(
            text("INSERT INTO character(id,workspace_id,name,code) VALUES ('c2',:w,'Hero2','hero2')"),  # noqa: E501
            {"w": WS},
        )
        conn.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) "
                "VALUES ('pv2','c2',:w,1,'published')"
            ),
            {"w": WS},
        )
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_cast_mapping("
                "id,workspace_id,project_id,object_role_id,character_id,"
                "pack_version_id,idempotency_key,revision) "
                "VALUES ('m2',:w,'p2','r2','c2','pv2','k2',1)"
            ),
            {"w": WS},
        )
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []
