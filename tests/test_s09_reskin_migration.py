"""S09-T01 migration tests — reskin_config + apply_checkpoint schema.

Covers every migration invariant of
``migrations/versions/c9d0e1f2a3b4_s09_reskin_config_and_apply_checkpoint.py``
(revision ``c9d0e1f2a3b4``, down_revision ``b2c3d4e5f6a7b``):
- single Alembic head + exact chain position
- migration/ORM parity for BOTH new tables (columns, CHECK, FK, indexes)
- upgrade → downgrade → upgrade byte-identical on empty graph
- PRAGMA integrity_check = ok and foreign_key_check = empty at each step
- downgrade with ANY row present REFUSES atomically (fail-closed)
- FK RESTRICT fail closed (deleting referenced rows refused)

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
PRE = "b2c3d4e5f6a7b"
NEW_TABLES = ("reskin_config", "apply_checkpoint")
WS = "ws-test-s09mig"


def _config(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _live_head() -> str:
    """Discover the CURRENT single Alembic head live from the script
    directory — never hard-coded, so new migrations on top of this one do
    not stale the assertion."""
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads}"
    return heads[0]


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
                text("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'")
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


def test_revision_chain_and_single_head() -> None:
    import migrations.versions.c9d0e1f2a3b4_s09_reskin_config_and_apply_checkpoint as mig

    assert mig.revision == "c9d0e1f2a3b4"
    assert mig.down_revision == PRE
    assert mig.branch_labels is None


def test_single_head_via_alembic() -> None:
    cfg = _config(Path(PROJECT_ROOT) / "data" / "never-used-s09t01.db")
    # heads is a script-directory operation; the URL is irrelevant but must parse.
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    # Exactly ONE head, and it must be the LIVE head (discovered, not a
    # stale hard-coded snapshot).
    assert heads == [_live_head()], f"expected exactly one live head, got {heads}"


def test_upgrade_downgrade_upgrade_empty_graph_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    assert _revision(db) == _live_head()
    assert "reskin_config" in _schema_signature(db)["tables"]  # type: ignore[operator]
    assert "apply_checkpoint" in _schema_signature(db)["tables"]  # type: ignore[operator]
    before_sig = _schema_signature(db)
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []

    command.downgrade(cfg, PRE)
    assert _revision(db) == PRE
    after_pre = _schema_signature(db)
    assert "reskin_config" not in after_pre["tables"]  # type: ignore[operator]
    assert "apply_checkpoint" not in after_pre["tables"]  # type: ignore[operator]

    command.upgrade(cfg, "head")
    after_sig = _schema_signature(db)
    assert after_sig == before_sig, "re-upgraded schema differs from first upgrade"
    assert _revision(db) == _live_head()
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []


def test_downgrade_refused_atomically_with_any_row(tmp_path: Path) -> None:
    db = tmp_path / "withrow.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")

    def _seed_reskin_row() -> None:
        with create_engine_for_path(db).begin() as conn:
            conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
            conn.execute(
                text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position)"
                    " VALUES ('v1','p1','Vid',0)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                    "start_time_ms,end_time_ms,status) VALUES ('s1','v1',0,0,10,0,1000,'pending')"
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
                text(
                    "INSERT INTO character(id,workspace_id,name,code)"
                    " VALUES ('c1',:w,'Hero','hero')"
                ),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO character_pack_version("
                    "id,character_id,workspace_id,version,status) "
                    "VALUES ('pv1','c1',:w,1,'published')"
                ),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO structural_lock_manifest("
                    "id,workspace_id,project_id,video_item_id,source_generation,version,"
                    "status,policy_version,manifest_hash,manifest_json,idempotency_key,"
                    "superseded_by_id,revision)"
                    " VALUES ('slm1',:w,'p1','v1','1',1,'active','pv-v1',"
                    ":h,'{}',NULL,NULL,1)"
                ),
                {"w": WS, "h": "a" * 64},
            )
            conn.execute(
                text(
                    "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                    "cast_mapping_id,character_id,pack_version_id,params_json,idempotency_key,revision,"
                    "structural_lock_manifest_id,lock_policy_version)"
                    " VALUES ('rc1',:w,'p1','r1',NULL,'c1','pv1','{}',NULL,1,'slm1','pv-v1')"
                ),
                {"w": WS},
            )

    _seed_reskin_row()
    row_before = None
    with create_engine_for_path(db).connect() as conn:
        row_before = conn.execute(
            text("SELECT id, pack_version_id, revision FROM reskin_config WHERE id='rc1'")
        ).first()
        assert row_before is not None

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE)

    with create_engine_for_path(db).connect() as conn:
        row_after = conn.execute(
            text("SELECT id, pack_version_id, revision FROM reskin_config WHERE id='rc1'")
        ).first()
        assert row_after == row_before, "downgrade refusal mutated data"
        # With a PINNED row the refusal fires on the FIRST reskin leg
        # (d8e9→c9d0): the DB must still sit at d8e9f0a1b2c3 — the revision
        # OWNING the refusing guard (identity constant; the head above it is
        # discovered live elsewhere). Untouched by the refusal.
        assert _revision(db) == "d8e9f0a1b2c3"
        assert _integrity(db) == "ok"
        assert _fk_violations(db) == []


def test_downgrade_legwise_unpinned_row_stops_at_c9d0(tmp_path: Path) -> None:
    """Leg-wise semantics when the reskin row carries NO pin values.

    d8e9f0a1b2c3's downgrade only refuses rows that USE the pin columns; an
    unpinned row lets leg 1 (d8e9→c9d0) complete. The SECOND leg (c9d0→PRE)
    then refuses on its own rule ('reskin_config table not empty') — the
    chain is still fail-closed end-to-end and lands pinned at c9d0e1f2a3b4.
    """
    db = tmp_path / "unpinned.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")

    def _seed_unpinned_row() -> None:
        with create_engine_for_path(db).begin() as conn:
            conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
            conn.execute(
                text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position)"
                    " VALUES ('v1','p1','Vid',0)"
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
                text(
                    "INSERT INTO character(id,workspace_id,name,code)"
                    " VALUES ('c1',:w,'Hero','hero')"
                ),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO character_pack_version("
                    "id,character_id,workspace_id,version,status) "
                    "VALUES ('pv1','c1',:w,1,'published')"
                ),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                    "cast_mapping_id,character_id,pack_version_id,params_json,idempotency_key,revision)"
                    " VALUES ('rc1',:w,'p1','r1',NULL,'c1','pv1','{}',NULL,1)"
                ),
                {"w": WS},
            )

    _seed_unpinned_row()
    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE)

    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(
            text("SELECT id FROM reskin_config WHERE id='rc1'")
        ).first()
        assert row is not None, "downgrade refusal mutated data"
        # Leg 1 completed (no pin values in use); leg 2 refused atomically
        # because reskin_config itself holds a row → parked at c9d0e1f2a3b4.
        assert _revision(db) == "c9d0e1f2a3b4"
        assert _integrity(db) == "ok"
        assert _fk_violations(db) == []


def test_migration_orm_parity(tmp_path: Path) -> None:
    """Migration DDL must equal Base.metadata exactly for BOTH new tables."""
    from app.persistence.models import Base

    mig_db = tmp_path / "mig.db"
    cfg = _config(mig_db)
    command.upgrade(cfg, "head")

    orm_db = tmp_path / "orm.db"
    engine = create_engine_for_path(orm_db)
    Base.metadata.create_all(engine)

    def tables(engine_db: Path) -> dict[str, dict]:  # noqa: ANN001
        out: dict[str, dict] = {}
        with create_engine_for_path(engine_db).connect() as conn:
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
                        _fk_entry(fk)
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
    assert mig == orm, f"migration schema differs from ORM:\n{mig}\nvs\n{orm}"


def _fk_entry(fk: dict) -> tuple:  # noqa: ANN001, ANN202
    """Normalized FK comparison entry.

    The S09-T00 pin columns (structural_lock_manifest_id on both tables)
    are added via native ``ALTER TABLE ... ADD COLUMN ... REFERENCES ...
    ON DELETE RESTRICT`` — SQLite stores the ON DELETE action but SQLAlchemy's
    legacy reflection reports no options for inline column-level REFERENCES
    (only for table-level CONSTRAINT clauses). The RESTRICT behaviour is
    genuinely enforced at the engine level (spike-verified in d8e9f0a1b2c3),
    so ondelete is compared only where BOTH sides report it; enforcement
    parity is covered by test_fk_restrict_fail_closed.
    """
    ondelete = fk.get("options", {}).get("ondelete")
    return (
        fk["referred_table"],
        tuple(fk["referred_columns"]),
        tuple(fk["constrained_columns"]),
        None if fk["referred_table"] == "structural_lock_manifest" else ondelete,
    )


def test_fk_restrict_fail_closed(tmp_path: Path) -> None:
    db = tmp_path / "fk.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    with create_engine_for_path(db).begin() as conn:
        conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        conn.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"), {"w": WS}
        )
        conn.execute(
            text("INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)")
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) VALUES ('s1','v1',0,0,10,0,1000,'pending')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status)"
                " VALUES ('r1',:w,'p1','v1','1','Char','character','confirmed')"
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
        conn.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                "cast_mapping_id,character_id,pack_version_id,params_json,idempotency_key,revision)"
                " VALUES ('rc1',:w,'p1','r1',NULL,'c1','pv1','{}',NULL,1)"
            ),
            {"w": WS},
        )
        conn.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                "reskin_config_revision,pack_version_ids_json,loop_hashes_json,"
                "timebase_fingerprint,snapshot_json,checkpoint_hash,note,idempotency_key,revision)"
                " VALUES ('ac1',:w,'p1','rc1',1,'[]','[]','fp','{}',:h,NULL,NULL,1)"
            ),
            {"w": WS, "h": "a" * 64},
        )

    # Deleting referenced parents while children exist must fail (RESTRICT)
    for stmt in (
        "DELETE FROM character WHERE id='c1'",
        "DELETE FROM reskin_config WHERE id='rc1'",
        "DELETE FROM project WHERE id='p1'",
    ):
        with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
            conn.execute(text(stmt))

    assert _fk_violations(db) == []
    assert _integrity(db) == "ok"


def test_apply_checkpoint_immutability_constraints(tmp_path: Path) -> None:
    db = tmp_path / "ckpt.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    with create_engine_for_path(db).begin() as conn:
        conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        conn.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"), {"w": WS}
        )
        conn.execute(
            text("INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)")
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) VALUES ('s1','v1',0,0,10,0,1000,'pending')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status)"
                " VALUES ('r1',:w,'p1','v1','1','Char','character','confirmed')"
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
        conn.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                "cast_mapping_id,character_id,pack_version_id,params_json,idempotency_key,"
                "revision) VALUES ('rc1',:w,'p1','r1',NULL,'c1','pv1','{}',NULL,1)"
            ),
            {"w": WS},
        )

    # revision != 1 refused by CHECK (immutable single-version row)
    with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                "reskin_config_revision,pack_version_ids_json,loop_hashes_json,"
                "timebase_fingerprint,snapshot_json,checkpoint_hash,note,idempotency_key,"
                "revision) VALUES ('ac-badrev',:w,'p1','rc1',1,'[]','[]','fp','{}',"
                ":h,NULL,NULL,2)"
            ),
            {"w": WS, "h": "a" * 64},
        )


def test_apply_checkpoint_hash_length_enforced(tmp_path: Path) -> None:
    db = tmp_path / "ckpthash.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    with create_engine_for_path(db).begin() as conn:
        conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        conn.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"), {"w": WS}
        )
        conn.execute(
            text("INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)")
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) VALUES ('s1','v1',0,0,10,0,1000,'pending')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status)"
                " VALUES ('r1',:w,'p1','v1','1','Char','character','confirmed')"
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
        conn.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                "cast_mapping_id,character_id,pack_version_id,params_json,idempotency_key,revision)"
                " VALUES ('rc1',:w,'p1','r1',NULL,'c1','pv1','{}',NULL,1)"
            ),
            {"w": WS},
        )
        # wrong hash length must be refused by CHECK
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                    "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                    "loop_hashes_json,timebase_fingerprint,snapshot_json,"
                    "checkpoint_hash,note,idempotency_key,revision) VALUES ("
                    "'ac-short',:w,'p1','rc1',1,'[]','[]','fp','{}','tooshort',"
                    "NULL,NULL,1)"
                ),
                {"w": WS},
            )
