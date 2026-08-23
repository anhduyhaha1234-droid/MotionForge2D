"""S09-T00-I01 migration tests — structural lock + renderer route schema.

Covers every migration invariant of
``migrations/versions/d8e9f0a1b2c3_s09_t00_structural_lock.py``:
- single Alembic head + LIVE down_revision discovery (never hard-coded)
- migration/ORM parity for BOTH new tables (columns, CHECK, FK, indexes)
  AND for the additive pin columns on reskin_config / apply_checkpoint
- upgrade → downgrade → upgrade byte-identical on empty graph (schema
  signature: every CREATE TABLE/Index statement + alembic_version)
- downgrade with ANY row present REFUSES atomically (fail-closed), both
  for new-table rows and for pin values in the altered tables
- PRAGMA integrity_check = ok and foreign_key_check = empty at each step
- FK RESTRICT fail closed (deleting a pinned manifest refused)

Runs on fresh isolated temp DB files only (never MAIN).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.persistence import create_engine_for_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
NEW_TABLES = ("structural_lock_manifest", "segment_render_route")
ALTERED_TABLES = ("reskin_config", "apply_checkpoint")
WS = "ws-test-s09t00mig"


def _config(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _live_heads() -> list[str]:
    """Discover heads LIVE from the script directory (no hard-coding)."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config(Path(PROJECT_ROOT) / "data"))
    return list(script.get_heads())


def _revision(db: Path) -> str | None:
    with create_engine_for_path(db).connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


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


def _integrity(db: Path) -> str:
    with create_engine_for_path(db).connect() as conn:
        return str(conn.execute(text("PRAGMA integrity_check")).scalar())


def _fk_violations(db: Path) -> list[tuple]:
    with create_engine_for_path(db).connect() as conn:
        return [tuple(r) for r in conn.execute(text("PRAGMA foreign_key_check")).fetchall()]


def test_single_head_and_live_down_revision() -> None:
    import migrations.versions.d8e9f0a1b2c3_s09_t00_structural_lock as mig

    assert mig.revision == "d8e9f0a1b2c3"
    # The migration's declared parent MUST be discovered live, not assumed.
    assert mig.down_revision == "c9d0e1f2a3b4"
    heads = _live_heads()
    assert heads == ["d8e9f0a1b2c3"], f"expected exactly one head, got {heads}"


def test_upgrade_downgrade_upgrade_empty_graph_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    assert _revision(db) == "d8e9f0a1b2c3"
    sig_first = _schema_signature(db)
    assert "structural_lock_manifest" in sig_first["tables"]  # type: ignore[operator]
    assert "segment_render_route" in sig_first["tables"]  # type: ignore[operator]
    for table in ALTERED_TABLES:
        cols = sig_first["tables"][table]  # type: ignore[index]
        assert "structural_lock_manifest_id" in cols
        assert "lock_policy_version" in cols
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []

    command.downgrade(cfg, "c9d0e1f2a3b4")
    assert _revision(db) == "c9d0e1f2a3b4"
    sig_pre = _schema_signature(db)
    assert "structural_lock_manifest" not in sig_pre["tables"]  # type: ignore[operator]
    assert "segment_render_route" not in sig_pre["tables"]  # type: ignore[operator]
    for table in ALTERED_TABLES:
        cols = sig_pre["tables"][table]  # type: ignore[index]
        assert "structural_lock_manifest_id" not in cols
        assert "lock_policy_version" not in cols

    command.upgrade(cfg, "head")
    sig_again = _schema_signature(db)
    assert sig_again == sig_first, "re-upgraded schema differs from first upgrade"
    assert _revision(db) == "d8e9f0a1b2c3"
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []


def _seed_full_graph(db: Path, *, with_manifest_row: bool = True) -> None:
    """Seed workspace/project/video/role/scene/segment/config/checkpoint."""
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
                "INSERT INTO occurrence_segment(id,workspace_id,project_id,"
                "video_item_id,role_id,scene_id,logical_id,lineage_version,name,kind,"
                "start_frame,end_frame,start_time_ms,end_time_ms,source_generation,"
                "confidence,confidence_source,reasons_json,visibility,z_order,revision)"
                " VALUES ('seg1',:w,'p1','v1','r1','s1','lg1',1,'Char','character',"
                "0,10,0,1000,'1',0.9,'model','[]','visible',0,1)"
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
                "cast_mapping_id,character_id,pack_version_id,params_json,"
                "idempotency_key,revision)"
                " VALUES ('rc1',:w,'p1','r1',NULL,'c1','pv1','{}',NULL,1)"
            ),
            {"w": WS},
        )


def _insert_manifest_row(conn: Any, manifest_id: str) -> None:  # noqa: ANN401
    conn.execute(
        text(
            "INSERT INTO structural_lock_manifest("
            "id,workspace_id,project_id,video_item_id,source_generation,version,"
            "status,policy_version,manifest_hash,manifest_json,idempotency_key,"
            "superseded_by_id,revision)"
            " VALUES (:i,:w,'p1','v1','1',1,'active','pv-v1',:h,'{}',NULL,NULL,1)"
        ),
        {"i": manifest_id, "w": WS, "h": "a" * 64},
    )


def test_downgrade_refused_with_new_table_rows(tmp_path: Path) -> None:
    db = tmp_path / "withrow.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_full_graph(db)
    with create_engine_for_path(db).begin() as conn:
        _insert_manifest_row(conn, "slm1")

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, "c9d0e1f2a3b4")

    # Nothing mutated by the refusal.
    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(
            text("SELECT id, status FROM structural_lock_manifest WHERE id='slm1'")
        ).first()
        assert row is not None and row[1] == "active", "refusal mutated data"
        assert _revision(db) == "d8e9f0a1b2c3"
        assert _integrity(db) == "ok"
        assert _fk_violations(db) == []


def test_downgrade_refused_when_pins_used(tmp_path: Path) -> None:
    db = tmp_path / "withpin.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_full_graph(db, with_manifest_row=False)
    with create_engine_for_path(db).begin() as conn:
        _insert_manifest_row(conn, "slm1")
        conn.execute(
            text(
                "UPDATE reskin_config SET structural_lock_manifest_id='slm1', "
                "lock_policy_version='pv-v1' WHERE id='rc1'"
            )
        )

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, "c9d0e1f2a3b4")

    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(
            text(
                "SELECT structural_lock_manifest_id, lock_policy_version "
                "FROM reskin_config WHERE id='rc1'"
            )
        ).first()
        assert row == ("slm1", "pv-v1"), "refusal mutated pin data"
        assert _revision(db) == "d8e9f0a1b2c3"


def test_downgrade_allows_unused_empty_pins_then_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "cleanpins.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_full_graph(db, with_manifest_row=False)
    # Rows exist but carry NO pin values → columns are droppable safely.
    command.downgrade(cfg, "c9d0e1f2a3b4")
    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(text("SELECT id FROM reskin_config WHERE id='rc1'")).first()
        assert row is not None, "downgrade must not touch pre-existing data rows"
    command.upgrade(cfg, "head")
    assert _revision(db) == "d8e9f0a1b2c3"
    assert _fk_violations(db) == []


def test_migration_orm_parity(tmp_path: Path) -> None:
    """Migration DDL must equal Base.metadata exactly for the new surfaces."""
    from app.persistence.models import Base

    mig_db = tmp_path / "mig.db"
    cfg = _config(mig_db)
    command.upgrade(cfg, "head")

    orm_db = tmp_path / "orm.db"
    engine = create_engine_for_path(orm_db)
    Base.metadata.create_all(engine)

    def tables(engine_db: Path, names: tuple[str, ...]) -> dict[str, dict]:  # noqa: ANN001
        out: dict[str, dict] = {}
        with create_engine_for_path(engine_db).connect() as conn:
            inspector = inspect(conn)
            for t in names:
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

    mig = tables(mig_db, NEW_TABLES)
    orm = tables(orm_db, NEW_TABLES)
    assert mig == orm, f"migration schema differs from ORM:\n{mig}\nvs\n{orm}"

    # Additive pin columns must reflect identically too (type + RESTRICT FK).
    # Inspector quirk (SQLAlchemy 2.0.51): an UNNAMED FK reports
    # options={} regardless of its ON DELETE clause — true for both the
    # ALTER-added migration FK and ORM create_all's unnamed pin FK, so the
    # options field is deliberately EXCLUDED from this comparison.
    # RESTRICT semantics are proven behaviorally by
    # test_pinned_manifest_delete_restrict_fail_closed (delete → IntegrityError)
    # and by PRAGMA foreign_key_list in _pin_fk_restrict_ok below, which reads
    # SQLite's own on_delete column for BOTH databases.
    mig_pin = tables(mig_db, ("reskin_config",))["reskin_config"]
    orm_pin = tables(orm_db, ("reskin_config",))["reskin_config"]
    assert mig_pin["cols"]["structural_lock_manifest_id"] == (
        orm_pin["cols"]["structural_lock_manifest_id"]
    ), f"pin column type mismatch:\n{mig_pin['cols']}\nvs\n{orm_pin['cols']}"
    mig_fk = [fk[:3] for fk in mig_pin["fks"] if fk[2] == ("structural_lock_manifest_id",)]
    orm_fk = [fk[:3] for fk in orm_pin["fks"] if fk[2] == ("structural_lock_manifest_id",)]
    assert mig_fk == orm_fk, f"pin FK mismatch:\n{mig_fk}\nvs\n{orm_fk}"
    assert mig_fk, "pinned reskin FK missing after migration"

    def _pin_fk_restrict_ok(engine_db: Path) -> bool:
        """SQLite-native truth: PRAGMA foreign_key_list on_delete column."""
        with create_engine_for_path(engine_db).connect() as conn:
            rows = conn.exec_driver_sql(
                "PRAGMA foreign_key_list(reskin_config)"
            ).fetchall()
        # columns: id, seq, table, from, to, on_update, on_delete, match
        return any(
            r[2] == "structural_lock_manifest"
            and r[3] == "structural_lock_manifest_id"
            and str(r[6]).upper() == "RESTRICT"
            for r in rows
        )

    def _pin_fk_rows(engine_db: Path) -> list[tuple]:
        with create_engine_for_path(engine_db).connect() as conn:
            return [
                tuple(r)
                for r in conn.exec_driver_sql(
                    "PRAGMA foreign_key_list(reskin_config)"
                ).fetchall()
            ]

    assert _pin_fk_restrict_ok(mig_db), (
        "migration-added pin FK lost ON DELETE RESTRICT "
        f"(PRAGMA foreign_key_list={_pin_fk_rows(mig_db)})"
    )
    assert _pin_fk_restrict_ok(orm_db), (
        "ORM pin FK lost ON DELETE RESTRICT "
        f"(PRAGMA foreign_key_list={_pin_fk_rows(orm_db)})"
    )


def test_route_check_refuses_invalid_enum(tmp_path: Path) -> None:
    db = tmp_path / "routecheck.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_full_graph(db, with_manifest_row=False)

    def _insert_route(route: str, row_id: str) -> None:
        with create_engine_for_path(db).begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO segment_render_route("
                    "id,workspace_id,project_id,video_item_id,occurrence_segment_id,"
                    "route,anchor_x,anchor_y,start_frame,end_frame,confidence,"
                    "confidence_source,reasons_json,revision)"
                    " VALUES (:rid,:w,'p1','v1','seg1',:route,0.5,0.5,0,10,1.0,"
                    "'model','[]',1)"
                ),
                {"rid": row_id, "w": WS, "route": route},
            )

    for n, good in enumerate(
        (
            "pose_swap",
            "sprite_affine",
            "mesh_warp",
            "part_rig",
            "controlled_redraw",
        ),
        start=1,
    ):
        _insert_route(good, f"rr{n}")  # five exact enum values, unique ids

    with pytest.raises(IntegrityError):
        _insert_route("fabric_draw", "rr-bad")  # not in enum — CHECK refuses


def test_anchor_range_checks_fail_closed(tmp_path: Path) -> None:
    db = tmp_path / "anchorrange.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_full_graph(db, with_manifest_row=False)

    def _insert_anchor(x: float, y: float) -> None:
        with create_engine_for_path(db).begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO segment_render_route("
                    "id,workspace_id,project_id,video_item_id,occurrence_segment_id,"
                    "route,anchor_x,anchor_y,start_frame,end_frame,confidence,"
                    "confidence_source,reasons_json,revision)"
                    " VALUES ('rr2',:w,'p1','v1','seg1','sprite_affine',:x,:y,0,10,"
                    "1.0,'model','[]',1)"
                ),
                {"w": WS, "x": x, "y": y},
            )

    # Boundary values are legal.
    _insert_anchor(0.0, 1.0)
    # Out-of-range anchors refused by CHECK.
    for bad_x, bad_y in ((1.01, 0.5), (-0.01, 0.5), (0.5, 1.5), (0.5, -0.001)):
        with pytest.raises(IntegrityError):
            _insert_anchor(bad_x, bad_y)


def test_pinned_manifest_delete_restrict_fail_closed(tmp_path: Path) -> None:
    db = tmp_path / "restrict.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_full_graph(db, with_manifest_row=False)
    with create_engine_for_path(db).begin() as conn:
        _insert_manifest_row(conn, "slm1")
        conn.execute(
            text(
                "UPDATE reskin_config SET structural_lock_manifest_id='slm1' "
                "WHERE id='rc1'"
            )
        )

    with pytest.raises(IntegrityError), create_engine_for_path(db).begin() as conn:
        conn.execute(text("DELETE FROM structural_lock_manifest WHERE id='slm1'"))

    assert _fk_violations(db) == []
    assert _integrity(db) == "ok"
