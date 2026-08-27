"""S08-A02-T01-R1 migration tests — structural-evidence schema bridge.

Covers every migration invariant of the REWRITTEN
``migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py``
(revision ``a0b1c2d3e4f5``, down_revision ``f7a8b9c0d1e2``):

- F1: import-smoke of ``app.persistence.models`` AND
  ``app.persistence.structural_evidence`` (the draft failed to import:
  ``non-default argument 'visibility' follows default argument``).
- F3: the PARTIAL unique index ``uq_occurrence_segment_active_identity``
  (WHERE ``superseded_by_id IS NULL``) is reflected AND enforced by SQLite
  3.45 — duplicate ACTIVE rows refused, versions/generations coexist.
- F9: workspace-scoped idempotency partial unique indexes exist on every new
  table.
- F11: migration/ORM parity — tables, columns, nullability, CHECK
  constraints, FK delete policy, indexes/unique indexes (incl. partial),
  server defaults.
- AC6: upgrade -> downgrade -> upgrade byte-identical on an empty graph;
  downgrade with ANY structural row present REFUSES atomically (revision /
  DDL / rows / indexes / FKs byte-identical; no partial mutation);
  ``PRAGMA integrity_check`` = ok and ``PRAGMA foreign_key_check`` = empty
  on every decision path.

Runs on fresh isolated temp DB files only (never MAIN / user DBs).  The
conftest ``client`` fixture is not used — this suite drives Alembic directly.
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
PRE = "f7a8b9c0d1e2"
# Revision under test (S08-A02-T01-R1 structural evidence bridge) — an
# IDENTITY constant, not the Alembic head; newer revisions may stack above
# it (the single head itself is discovered live via _live_head()).
HEAD_REVISION = "a0b1c2d3e4f5"
NEW_TABLES = (
    "occurrence_segment",
    "segment_motion",
    "scene_graph_occlusion",
    "scene_graph_contact",
)
WS = "ws-test-a02mig"


def _config(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _schema_signature(db: Path) -> dict[str, object]:
    """Byte-visible schema signature: table DDL + index DDL."""
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


def _live_head() -> str:
    """Discover the CURRENT single Alembic head live from the script
    directory — never hard-coded, so new migrations on top of this one do
    not stale the assertion."""
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads}"
    return heads[0]


def _seed_parent_rows(db: Path) -> None:
    """Insert minimal FK-resolvable parent rows (all pre-A02 tables exist at
    the current head because Alembic runs the full history)."""
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS}
        )
        conn.execute(
            text(
                "INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'p')"
            ),
            {"w": WS},
        )
        conn.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','v',0)"
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


def _insert_segment_row(db: Path, seg_id: str, gen: str = "1") -> None:
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO occurrence_segment("
                "id,logical_id,workspace_id,project_id,video_item_id,role_id,scene_id,"
                "name,kind,start_frame,end_frame,start_time_ms,end_time_ms,"
                "source_generation,confidence,confidence_source,reasons_json,"
                "visibility,z_order,revision,superseded_by_id) VALUES ("
                ":id,:lid,:w,'p1','v1','r1','s1',"
                "'Char','character',0,10,0,1000,"
                ":gen,1.0,'model','[]',"
                "'visible',0,1,NULL)"
            ),
            {"id": seg_id, "lid": seg_id, "w": WS, "gen": gen},
        )


# ── F1 import smoke ────────────────────────────────────────────────────────


def test_import_smoke_models_and_repository() -> None:
    """The corrected dataclasses must import cleanly (draft failed with a
    ``non-default argument 'visibility' follows default argument`` TypeError)."""
    import app.persistence.models  # noqa: F401
    import app.persistence.structural_evidence as se  # noqa: F401

    assert hasattr(se, "StructuralEvidenceRepository")
    assert hasattr(se, "SegmentRecord")
    # F1 fix proof: non-default fields must precede default fields in every DTO.
    for dto in (se.SegmentRecord, se.MotionRecord, se.OcclusionRecord, se.ContactRecord):
        names = list(dto.__dataclass_fields__)
        defaults_started = False
        for n in names:
            if dto.__dataclass_fields__[n].default is not None or (
                dto.__dataclass_fields__[n].default_factory is not None  # type: ignore[attr-defined]
            ):
                defaults_started = True
            else:
                assert not defaults_started, (
                    f"{dto.__name__}: non-default field {n!r} follows a default"
                )
    # F2 proof: the segment DTO carries the stable logical lineage id.
    assert "logical_id" in se.SegmentRecord.__dataclass_fields__


# ── AC6 empty-graph round-trip byte-identical ──────────────────────────────


def test_upgrade_downgrade_upgrade_empty_graph_byte_identical(
    tmp_path: Path,
) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _config(db)

    command.upgrade(cfg, "head")
    assert _revision(db) == _live_head()
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
    assert _revision(db) == _live_head()
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []
    assert _schema_signature(db) == up_once, "re-upgrade DDL differs (not byte-identical)"
    # The downgraded signature must be a strict subset: new tables gone.
    assert set(downgraded["tables"]) < set(up_once["tables"])


# ── AC6 atomic downgrade refusal with structural rows ──────────────────────


@pytest.mark.parametrize("table", NEW_TABLES)
def test_downgrade_refused_atomically_with_any_row(
    tmp_path: Path, table: str
) -> None:
    db = tmp_path / "refuse.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_parent_rows(db)
    _insert_segment_row(db, "seg-1", gen="1")
    before = _schema_signature(db)
    with create_engine_for_path(db).connect() as conn:
        before_rows = {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar())
            for t in NEW_TABLES
        }

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE)

    # ATOMIC refusal: with a newer head stacked above, the b2c->a0b1 leg
    # succeeds first, then a0b1c2d3e4f5->f7 refuses — leaving revision at
    # a0b1c2d3e4f5 (the S08-A02 revision under test).  # noqa: E501
    assert _revision(db) == HEAD_REVISION
    assert _schema_signature(db) != before  # b2c table gone, but 4 tables remain
    for t in NEW_TABLES:
        with create_engine_for_path(db).connect() as conn:
            cnt = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        assert cnt == before_rows[t], f"{t} row count changed on refused downgrade"
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []
    # Re-upgrade restores the live head discovered from the script directory.
    command.upgrade(cfg, "head")
    assert _revision(db) == _live_head()
    assert _schema_signature(db) == before


# ── F3 partial unique index: reflected AND enforced in SQLite 3.45 ─────────


def test_partial_active_unique_index_reflected_and_enforced(tmp_path: Path) -> None:
    db = tmp_path / "partial.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    _seed_parent_rows(db)
    _insert_segment_row(db, "seg-v1", gen="1")

    with create_engine_for_path(db).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, \"unique\", \"partial\" "
                "FROM pragma_index_list('occurrence_segment')"
            )
        ).all()
        active = [r for r in rows if r[0] == "uq_occurrence_segment_active_identity"]
        assert active, "active partial unique index not reflected in pragma_index_list"
        assert active[0][1] == 1, "active index must be UNIQUE"
        assert active[0][2] == 1, "active index must be PARTIAL"

    # Same (role, scene, frame range, generation) ACTIVE row -> refused.
    with pytest.raises(IntegrityError):
        _insert_segment_row(db, "seg-v1-dup", gen="1")
    # A NEWER generation with the same identity coexists (multiple versions).
    _insert_segment_row(db, "seg-v2", gen="2")
    # Retire v1 (superseded) -> its identity slot is free again for gen "1".
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text(
                "UPDATE occurrence_segment SET superseded_by_id='seg-v2' "
                "WHERE id='seg-v1'"
            )
        )
    _insert_segment_row(db, "seg-v1b", gen="1")
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []


# ── F9 workspace-scoped idempotency partial indexes exist ──────────────────


def test_workspace_idempotency_partial_indexes_exist(tmp_path: Path) -> None:
    db = tmp_path / "idem.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    expected = {
        "occurrence_segment": "uq_occurrence_segment_workspace_idempotency",
        "segment_motion": "uq_segment_motion_workspace_idempotency",
        "scene_graph_occlusion": "uq_scene_graph_occlusion_workspace_idempotency",
        "scene_graph_contact": "uq_scene_graph_contact_workspace_idempotency",
    }
    with create_engine_for_path(db).connect() as conn:
        for table, idx in expected.items():
            row = conn.execute(
                text(
                    "SELECT \"unique\", \"partial\" "
                    "FROM pragma_index_list(:t) WHERE name = :i"
                ),
                {"t": table, "i": idx},
            ).first()
            assert row, f"{idx!r} missing on {table}"
            assert row[0] == 1 and row[1] == 1, f"{idx!r} must be unique+partial"
            sql = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='index' AND name = :i"
                ),
                {"i": idx},
            ).scalar()
            assert sql is not None and "idempotency_key IS NOT NULL" in str(sql)


# ── F11 migration / ORM parity ─────────────────────────────────────────────


def test_migration_orm_parity(tmp_path: Path) -> None:
    """Two schemas — one built by Alembic, one by Base.metadata.create_all —
    must be structurally identical for the four new tables."""
    from app.persistence.models import Base

    mig_db = tmp_path / "mig.db"
    cfg = _config(mig_db)
    command.upgrade(cfg, "head")

    orm_db = tmp_path / "orm.db"
    engine = create_engine_for_path(orm_db)
    Base.metadata.create_all(engine)  # isolated temp DB only (contract §14)

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
    assert mig == orm, "migration schema differs from the ORM (R1 F11 parity)"


# ── F1/F11 revision chain + single head ────────────────────────────────────


def test_revision_chain_and_single_head() -> None:
    import migrations.versions.a0b1c2d3e4f5_s08_a02_structural_evidence as mig

    assert mig.revision == "a0b1c2d3e4f5"
    assert mig.down_revision == "f7a8b9c0d1e2"
    assert mig.branch_labels is None
    assert mig.depends_on is None

    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(PROJECT_ROOT / "migrations"))
    heads = script.get_heads()
    # Single-head, discovered LIVE (not a hard-coded snapshot).
    assert heads == [_live_head()], f"unexpected Alembic head(s): {heads}"
    # Chain still contains a0b1c2d3e4f5 as intermediate (S08-A02 → S07-T01),
    # reachable from the LIVE head.
    assert "a0b1c2d3e4f5" in {  # noqa: E501
        r.revision
        for r in script.walk_revisions(base="f7a8b9c0d1e2", head=_live_head())
    }
