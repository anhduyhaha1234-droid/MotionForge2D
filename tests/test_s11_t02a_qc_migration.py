"""S11-T02A QCItem migration tests.

Covers ``migrations/versions/e11a02a2026f_s11_t02a_qc_item.py``
(revision ``e11a02a2026f``, down_revision = live single head measured at
creation — ``a10b11c12d3e``):

- single Alembic head + exact chain position
- upgrade -> downgrade -> upgrade byte-identical on an empty graph
- PRAGMA integrity_check = ok and foreign_key_check = empty at every step
- downgrade with ANY ``qc_item`` row present REFUSES atomically (fail-closed)
- migration CHECK literals are byte-identical to the ORM-derived CHECKs and
  are live (bogus enum + blocker/dismissed rejected on a migrated DB)
- FK ``segment_row_id`` -> ``occurrence_segment`` enforced on the migrated DB

Runs on fresh isolated temp DB files only (never MAIN).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.persistence import create_engine_for_path
from app.persistence.models import Base
from app.persistence.models import (
    QC_ITEM_CATEGORY_CHECK_SQL,
    QC_ITEM_SEVERITY_CHECK_SQL,
    QC_ITEM_STATUS_CHECK_SQL,
    QC_REASON_CODE_CHECK_SQL,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
PRE = "a10b11c12d3e"
REV = "e11a02a2026f"
NEW_TABLE = "qc_item"

_SEGMENT_PAIR_CHECK = (
    "(segment_row_id IS NULL AND segment_logical_id IS NULL) OR "
    "(segment_row_id IS NOT NULL AND segment_logical_id IS NOT NULL)"
)
_BLOCKER_DISMISSED_CHECK = "NOT (severity = 'blocker' AND status = 'dismissed')"


def _cfg(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _live_head() -> str:
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads}"
    return heads[0]


def _schema_sig(db: Path) -> dict[str, object]:
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


def _rev(db: Path) -> str | None:
    with create_engine_for_path(db).connect() as conn:
        return conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()  # type: ignore[no-any-return]


def _integrity(db: Path) -> str:
    with create_engine_for_path(db).connect() as conn:
        return str(conn.execute(text("PRAGMA integrity_check")).scalar())


def _fk_violations(db: Path) -> list[tuple]:
    with create_engine_for_path(db).connect() as conn:
        return [tuple(r) for r in conn.execute(text("PRAGMA foreign_key_check")).fetchall()]


def _qc_ddl(db: Path) -> str:
    with create_engine_for_path(db).connect() as conn:
        return str(
            conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='qc_item'"
                )
            ).scalar()
        )


def test_revision_chain_and_single_head() -> None:
    import migrations.versions.e11a02a2026f_s11_t02a_qc_item as mig

    assert mig.revision == REV
    assert mig.down_revision == PRE
    assert mig.branch_labels is None


def test_single_head_via_alembic() -> None:
    from alembic.script import ScriptDirectory

    cfg = _cfg(Path(PROJECT_ROOT) / "data" / "never-used-s11t02a.db")
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    assert heads == [_live_head()], f"expected exactly one live head, got {heads}"
    assert heads == [REV]


def test_upgrade_downgrade_upgrade_empty_graph_byte_identical(
    tmp_path: Path,
) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    assert _rev(db) == _live_head()
    assert NEW_TABLE in _schema_sig(db)["tables"]  # type: ignore[operator]
    before_sig = _schema_sig(db)
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []

    command.downgrade(cfg, PRE)
    assert _rev(db) == PRE
    after_pre = _schema_sig(db)
    assert NEW_TABLE not in after_pre["tables"]  # type: ignore[operator]

    command.upgrade(cfg, "head")
    after_sig = _schema_sig(db)
    assert after_sig == before_sig, "re-upgraded schema differs from first upgrade"
    assert _rev(db) == _live_head()
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []


def _seed_parents(db: Path) -> None:
    """Minimal parent rows so every qc_item FK target exists."""
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text("INSERT OR IGNORE INTO workspace(id,name) VALUES ('ws-mig','W')")
        )
        conn.execute(
            text(
                "INSERT INTO project(id,workspace_id,name) "
                "VALUES ('p-mig','ws-mig','P')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) "
                "VALUES ('v-mig','p-mig','V',0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,"
                "end_frame,start_time_ms,end_time_ms,status) "
                "VALUES ('sc-mig','v-mig',0,0,10,0,1000,'pending')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,"
                "video_item_id,source_generation,name,kind,status) "
                "VALUES ('ro-mig','ws-mig','p-mig','v-mig','1','Hero',"
                "'character','confirmed')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO occurrence_segment (id, workspace_id, project_id, "
                "video_item_id, role_id, scene_id, logical_id, lineage_version, "
                "name, kind, start_frame, end_frame, start_time_ms, end_time_ms, "
                "source_generation, confidence, confidence_source, reasons_json, "
                "visibility, z_order) "
                "VALUES ('seg-mig','ws-mig','p-mig','v-mig','ro-mig','sc-mig',"
                "'lin-mig',1,'Hero','character',0,10,0,1000,'1',0.9,'model',"
                "'[]','visible',0)"
            )
        )


def _seed_qc_row(db: Path, qid: str = "q-mig-row") -> None:
    with create_engine_for_path(db).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO qc_item (id, workspace_id, project_id, "
                "video_item_id, segment_row_id, segment_logical_id, "
                "layer_ref_type, layer_ref_id, reason_code, "
                "evidence_window_key, evidence_json, status, severity, "
                "category, detector, detector_revision, confidence, "
                "confidence_source, checkpoint_ref) "
                "VALUES (:qid, 'ws-mig', 'p-mig', 'v-mig', 'seg-mig', "
                "'lin-mig', 'video_item', 'v-mig', 'clipping', 'ewk-mig', "
                "'{\"schema_version\": 1}', 'open', 'warning', 'clipping', "
                "'qc-lane-a', '1.0.0', 0.8, 'model', 'ckpt-mig')"
            ),
            {"qid": qid},
        )


def test_downgrade_refused_atomically_with_any_row(tmp_path: Path) -> None:
    db = tmp_path / "withrow.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    _seed_parents(db)
    _seed_qc_row(db)

    with create_engine_for_path(db).connect() as conn:
        before = conn.execute(
            text("SELECT id FROM qc_item WHERE id='q-mig-row'")
        ).first()
    assert before is not None

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE)

    with create_engine_for_path(db).connect() as conn:
        after = conn.execute(
            text("SELECT id FROM qc_item WHERE id='q-mig-row'")
        ).first()
        assert after == before, "downgrade refusal mutated data"
        assert _rev(db) == _live_head()
        assert _integrity(db) == "ok"
        assert _fk_violations(db) == []


def test_migration_checks_byte_identical_to_orm_and_live(tmp_path: Path) -> None:
    db_mig = tmp_path / "migrated.db"
    cfg = _cfg(db_mig)
    command.upgrade(cfg, "head")
    _seed_parents(db_mig)

    db_orm = tmp_path / "orm.db"
    engine = create_engine_for_path(db_orm)
    Base.metadata.create_all(engine)

    mig_ddl = _qc_ddl(db_mig)
    orm_ddl = _qc_ddl(db_orm)

    for literal in (
        QC_ITEM_STATUS_CHECK_SQL,
        QC_ITEM_SEVERITY_CHECK_SQL,
        QC_ITEM_CATEGORY_CHECK_SQL,
        QC_REASON_CODE_CHECK_SQL,
        _SEGMENT_PAIR_CHECK,
        _BLOCKER_DISMISSED_CHECK,
    ):
        assert literal in mig_ddl, f"migration DDL missing CHECK {literal!r}"
        assert literal in orm_ddl, f"ORM DDL missing CHECK {literal!r}"

    # The live migrated DB enforces them (they are real reflected CHECKs).
    # Parents exist, so the failures below are genuinely the CHECKs, not FKs.
    with create_engine_for_path(db_mig).begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO qc_item (id, workspace_id, project_id, "
                "video_item_id, layer_ref_type, layer_ref_id, reason_code, "
                "evidence_window_key, evidence_json, status, severity, "
                "category, detector, detector_revision, confidence, "
                "confidence_source, checkpoint_ref) "
                "VALUES ('q-bad', 'ws-mig', 'p-mig', 'v-mig', 'video_item', "
                "'v-mig', 'clipping', 'ewk-bad', '{}', 'bogus', 'warning', "
                "'clipping', 'qc-lane-a', '1.0.0', 0.8, 'model', 'ckpt-mig')"
            )
        )
    with create_engine_for_path(db_mig).begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO qc_item (id, workspace_id, project_id, "
                "video_item_id, layer_ref_type, layer_ref_id, reason_code, "
                "evidence_window_key, evidence_json, status, severity, "
                "category, detector, detector_revision, confidence, "
                "confidence_source, checkpoint_ref) "
                "VALUES ('q-bd', 'ws-mig', 'p-mig', 'v-mig', 'video_item', "
                "'v-mig', 'clipping', 'ewk-bd', '{}', 'dismissed', 'blocker', "
                "'clipping', 'qc-lane-a', '1.0.0', 0.8, 'model', 'ckpt-mig')"
            )
        )
    assert _fk_violations(db_mig) == []


def test_segment_fk_enforced_on_migrated_db(tmp_path: Path) -> None:
    db = tmp_path / "fkmig.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    _seed_parents(db)
    with create_engine_for_path(db).begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO qc_item (id, workspace_id, project_id, "
                "video_item_id, segment_row_id, segment_logical_id, "
                "layer_ref_type, layer_ref_id, reason_code, "
                "evidence_window_key, evidence_json, status, severity, "
                "category, detector, detector_revision, confidence, "
                "confidence_source, checkpoint_ref) "
                "VALUES ('q-fk', 'ws-mig', 'p-mig', 'v-mig', 'no-such-seg', "
                "'lin-mig', 'video_item', 'v-mig', 'clipping', 'ewk-fk', "
                "'{}', 'open', 'warning', 'clipping', 'qc-lane-a', '1.0.0', "
                "0.8, 'model', 'ckpt-mig')"
            )
        )
    assert _fk_violations(db) == []