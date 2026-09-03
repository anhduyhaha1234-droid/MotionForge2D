"""S10-T01A migration tests — FullApply domain schema.

Covers every invariant of
``migrations/versions/a10b11c12d3e_s10_full_apply_domain.py``
(revision ``a10b11c12d3e``, down_revision ``b3c4d5e6f7a9``):
- single Alembic head + exact chain position
- migration/ORM parity for all three new tables (columns, CHECK, FK, indexes)
- upgrade -> downgrade -> upgrade byte-identical on empty graph
- PRAGMA integrity_check = ok and foreign_key_check = empty at each step
- downgrade with ANY row present REFUSES atomically (fail-closed)
- FK RESTRICT fail closed
- existing S09 rows survive roundtrip (no S09 table lost)

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
PRE = "b3c4d5e6f7a9"
NEW_TABLES = ("s10_full_apply_run", "s10_full_apply_chunk", "s10_full_apply_publication")


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
                text("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            ).all()
        }
        indexes = sorted(
            (str(r[0]), str(r[1]), str(r[2]))
            for r in conn.execute(text("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'")).all()
        )
        return {"tables": tables, "indexes": indexes}


def _rev(db: Path) -> str | None:
    with create_engine_for_path(db).connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()  # type: ignore[no-any-return]


def _integrity(db: Path) -> str:
    with create_engine_for_path(db).connect() as conn:
        return str(conn.execute(text("PRAGMA integrity_check")).scalar())


def _fk_violations(db: Path) -> list[tuple]:
    with create_engine_for_path(db).connect() as conn:
        return [tuple(r) for r in conn.execute(text("PRAGMA foreign_key_check")).fetchall()]


def test_revision_chain_and_single_head() -> None:
    import migrations.versions.a10b11c12d3e_s10_full_apply_domain as mig

    assert mig.revision == "a10b11c12d3e"
    assert mig.down_revision == PRE
    assert mig.branch_labels is None


def test_single_head_via_alembic() -> None:
    from alembic.script import ScriptDirectory

    cfg = _cfg(Path(PROJECT_ROOT) / "data" / "never-used-s10t01a.db")
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    assert heads == [_live_head()], f"expected exactly one live head, got {heads}"


def test_upgrade_downgrade_upgrade_empty_graph_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    assert _rev(db) == _live_head()
    for t in NEW_TABLES:
        assert t in _schema_sig(db)["tables"]  # type: ignore[operator]
    before_sig = _schema_sig(db)
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []

    command.downgrade(cfg, PRE)
    assert _rev(db) == PRE
    after_pre = _schema_sig(db)
    for t in NEW_TABLES:
        assert t not in after_pre["tables"]  # type: ignore[operator]

    command.upgrade(cfg, "head")
    after_sig = _schema_sig(db)
    assert after_sig == before_sig, "re-upgraded schema differs from first upgrade"
    assert _rev(db) == _live_head()
    assert _integrity(db) == "ok"
    assert _fk_violations(db) == []


def test_downgrade_refused_atomically_with_any_row(tmp_path: Path) -> None:
    db = tmp_path / "withrow.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")

    def _seed_one_run() -> None:
        import hashlib

        ws = "ws-s10-mig-refuse"
        h = hashlib.sha256(b"x").hexdigest()
        with create_engine_for_path(db).begin() as conn:
            conn.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
            conn.execute(text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"), {"w": ws})
            conn.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)"))
            conn.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES ('c1',:w,'Hero','hero')"), {"w": ws})
            conn.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES ('pv1','c1',:w,1,'published')"), {"w": ws})
            conn.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES ('s1','v1',0,0,10,0,1000,'pending')"))
            conn.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES ('r1',:w,'p1','v1','1','Hero','character','confirmed')"), {"w": ws})
            conn.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES ('rc1',:w,'p1','r1','c1','pv1','{}',1)"), {"w": ws})
            conn.execute(text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES ('ckpt1',:w,'p1','rc1',1,'[]','[]',:tbf,'{}',:ch,1)"), {"w": ws, "tbf": h, "ch": h})
            conn.execute(text("INSERT INTO s10_full_apply_run(id,workspace_id,project_id,video_item_id,apply_checkpoint_id,apply_checkpoint_hash,apply_checkpoint_revision,plan_id,plan_hash,status,frame_count,chunk_config_json,attempt,revision) VALUES ('run1',:w,'p1','v1','ckpt1',:ch,1,:ch,:ch,'pending',100,'{}',1,1)"), {"w": ws, "ch": h})

    _seed_one_run()
    with create_engine_for_path(db).connect() as conn:
        before = conn.execute(text("SELECT id FROM s10_full_apply_run WHERE id='run1'")).first()
        assert before is not None

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE)

    with create_engine_for_path(db).connect() as conn:
        after = conn.execute(text("SELECT id FROM s10_full_apply_run WHERE id='run1'")).first()
        assert after == before, "downgrade refusal mutated data"
        assert _rev(db) == "a10b11c12d3e"
        assert _integrity(db) == "ok"
        assert _fk_violations(db) == []


def test_existing_s09_rows_survive_roundtrip(tmp_path: Path) -> None:
    """S09 checkpoint/correction rows must survive a10b11 downgrade/upgrade."""
    db = tmp_path / "s09survive.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    import hashlib

    ws = "ws-s09-survive"
    h = hashlib.sha256(b"s09").hexdigest()
    with create_engine_for_path(db).begin() as conn:
        conn.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
        conn.execute(text("INSERT INTO project(id,workspace_id,name) VALUES ('ps09',:w,'ProjS09')"), {"w": ws})
        conn.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES ('vs09','ps09','VidS09',0)"))
        conn.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES ('cs09',:w,'Hero','hero_s09')"), {"w": ws})
        conn.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES ('pvs09','cs09',:w,1,'published')"), {"w": ws})
        conn.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES ('ss09','vs09',0,0,10,0,1000,'pending')"))
        conn.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES ('rs09',:w,'ps09','vs09','1','Hero','character','confirmed')"), {"w": ws})
        conn.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES ('rcs09',:w,'ps09','rs09','cs09','pvs09','{}',1)"), {"w": ws})
        conn.execute(text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES ('ckpts09',:w,'ps09','rcs09',1,'[]','[]',:tbf,'{}',:ch,1)"), {"w": ws, "tbf": h, "ch": h})
        conn.execute(text("INSERT INTO s09_correction(id,workspace_id,project_id,video_item_id,correction_kind,status,request_json,impact_json,revision) VALUES ('corr1',:w,'ps09','vs09','mask','pending','{}','{}',1)"), {"w": ws})
    # downgrade to PRE removes only S10 tables; S09 rows stay
    command.downgrade(cfg, PRE)
    with create_engine_for_path(db).connect() as conn:
        ckpt = conn.execute(text("SELECT id FROM apply_checkpoint WHERE id='ckpts09'")).first()
        assert ckpt is not None, "S09 checkpoint lost after S10 downgrade"
        corr = conn.execute(text("SELECT id FROM s09_correction WHERE id='corr1'")).first()
        assert corr is not None, "S09 correction lost after S10 downgrade"
    command.upgrade(cfg, "head")
    with create_engine_for_path(db).connect() as conn:
        ckpt2 = conn.execute(text("SELECT id FROM apply_checkpoint WHERE id='ckpts09'")).first()
        assert ckpt2 is not None
        assert _rev(db) == _live_head()
        assert _integrity(db) == "ok"
        assert _fk_violations(db) == []


def test_fk_restrict_on_checkpoint_delete(tmp_path: Path) -> None:
    db = tmp_path / "fkrestrict.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    import hashlib
    ws = "ws-fk"
    h = hashlib.sha256(b"fk").hexdigest()
    with create_engine_for_path(db).begin() as conn:
        conn.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
        conn.execute(text("INSERT INTO project(id,workspace_id,name) VALUES ('pfk',:w,'ProjFk')"), {"w": ws})
        conn.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES ('vfk','pfk','Vid',0)"))
        conn.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES ('cfk',:w,'Hero','hero_fk')"), {"w": ws})
        conn.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES ('pvfk','cfk',:w,1,'published')"), {"w": ws})
        conn.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES ('sfk','vfk',0,0,10,0,1000,'pending')"))
        conn.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES ('rfk',:w,'pfk','vfk','1','Hero','character','confirmed')"), {"w": ws})
        conn.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES ('rcfk',:w,'pfk','rfk','cfk','pvfk','{}',1)"), {"w": ws})
        conn.execute(text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES ('ckptfk',:w,'pfk','rcfk',1,'[]','[]',:tbf,'{}',:ch,1)"), {"w": ws, "tbf": h, "ch": h})
        conn.execute(text("INSERT INTO s10_full_apply_run(id,workspace_id,project_id,video_item_id,apply_checkpoint_id,apply_checkpoint_hash,apply_checkpoint_revision,plan_id,plan_hash,status,frame_count,chunk_config_json,attempt,revision) VALUES ('runfk',:w,'pfk','vfk','ckptfk',:ch,1,:ch,:ch,'pending',10,'{}',1,1)"), {"w": ws, "ch": h})
    with create_engine_for_path(db).begin() as conn, pytest.raises(IntegrityError):
        conn.execute(text("DELETE FROM apply_checkpoint WHERE id='ckptfk'"))
