"""S12-T03A migration tests — c3d4e5f6a7b8 export domain revision.

- fresh DB upgrades to the new sole head with the three S12 tables,
  their PK/FK/CHECK reflection metadata, and the expected index set;
- upgrade from the previous head (f9a0b1c2d3e4) works and retained rows
  in older tables survive the new revision (retained-data);
- the revision chain is linear: exactly one head, and walking history
  from head reaches f9a0b1c2d3e4 as the direct parent of c3d4e5f6a7b8;
- fail-closed downgrade: seed one row in s12_export_run (plus its FK
  lineage) at head, then downgrading c3d4e5f6a7b8 refuses BEFORE any
  DDL and the head is unchanged; an empty downgrade drops exactly the
  three tables and lands back on f9a0b1c2d3e4.

Runs against real migrated temp DBs (never MAIN, never production).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.persistence import create_engine_for_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

NEW_REV = "c3d4e5f6a7b8"
PARENT_REV = "f9a0b1c2d3e4"
NEW_TABLES = ("s12_export_run", "s12_export_chunk", "s12_export_lease")


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


@pytest.fixture()
def fresh_db_path(tmp_path: Path) -> Path:
    return tmp_path / "mig.db"


def _table_names(db: Path) -> set[str]:
    eng = create_engine_for_path(db)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


# ── Chain integrity ──────────────────────────────────────────────────────────

def test_single_head_is_new_revision() -> None:
    cfg = _config(Path("unused.db"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert set(heads) == {NEW_REV}, f"expected sole head {NEW_REV}, got {heads}"


def test_history_links_parent() -> None:
    cfg = _config(Path("unused.db"))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision(NEW_REV)
    assert rev is not None
    assert rev.down_revision == PARENT_REV or (
        isinstance(rev.down_revision, tuple) and PARENT_REV in rev.down_revision
    )


# ── Fresh upgrade ────────────────────────────────────────────────────────────

def test_fresh_upgrade_creates_tables(fresh_db_path: Path) -> None:
    command.upgrade(_config(fresh_db_path), "head")
    names = _table_names(fresh_db_path)
    for table in NEW_TABLES:
        assert table in names, f"{table} missing after fresh upgrade"

    eng = create_engine_for_path(fresh_db_path)
    try:
        insp = inspect(eng)
        run_pk = insp.get_pk_constraint("s12_export_run")
        assert run_pk["constrained_columns"] == ["id"]
        lease_pk = insp.get_pk_constraint("s12_export_lease")
        assert lease_pk["constrained_columns"] == ["run_id"]

        run_checks = {c["name"] for c in insp.get_check_constraints("s12_export_run")}
        assert "ck_s12_run_status" in run_checks
        chunk_checks = {c["name"] for c in insp.get_check_constraints("s12_export_chunk")}
        assert "ck_s12_chunk_state" in chunk_checks
        lease_checks = {c["name"] for c in insp.get_check_constraints("s12_export_lease")}
        assert "ck_s12_lease_token_nonempty" in lease_checks

        run_indexes = {i["name"] for i in insp.get_indexes("s12_export_run")}
        assert "uq_s12_run_natural" in run_indexes
        assert "uq_s12_run_workspace_idempotency" in run_indexes
        chunk_indexes = {i["name"] for i in insp.get_indexes("s12_export_chunk")}
        assert "uq_s12_chunk_run_index_attempt" in chunk_indexes or any(
            "uq_s12_chunk" in n for n in chunk_indexes
        )
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == NEW_REV
            fk_bad = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            assert fk_bad == []
    finally:
        eng.dispose()


# ── Upgrade from parent + retained data ──────────────────────────────────────

def test_upgrade_from_parent_retains_data(fresh_db_path: Path) -> None:
    command.upgrade(_config(fresh_db_path), PARENT_REV)
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO workspace(id,name) VALUES ('w1','W1')"))
    finally:
        eng.dispose()

    command.upgrade(_config(fresh_db_path), "head")
    eng2 = create_engine_for_path(fresh_db_path)
    try:
        with eng2.connect() as conn:
            kept = conn.execute(
                text("SELECT name FROM workspace WHERE id='w1'")
            ).scalar()
            assert kept == "W1"
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == NEW_REV
            names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            for table in NEW_TABLES:
                assert table in names
    finally:
        eng2.dispose()


# ── Fail-closed downgrade ────────────────────────────────────────────────────

def _seed_export_lineage(db: Path) -> None:
    eng = create_engine_for_path(db)
    try:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO workspace(id,name) VALUES ('w1','W1')"))
            conn.execute(
                text("INSERT INTO project(id,workspace_id,name) VALUES ('p1','w1','P')")
            )
            conn.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position)"
                    " VALUES ('v1','p1','V',0)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO character(id,workspace_id,name,code)"
                    " VALUES ('ch','w1','H','h')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO character_pack_version(id,character_id,workspace_id,"
                    "version,status) VALUES ('pv','ch','w1',1,'published')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                    "source_generation,name,kind,status) VALUES ('rl','w1','p1','v1',"
                    "'g','C','character','confirmed')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO reskin_config(id,workspace_id,project_id,"
                    "object_role_id,cast_mapping_id,character_id,pack_version_id,"
                    "params_json,idempotency_key,revision) VALUES ('rc','w1','p1','rl',"
                    "NULL,'ch','pv','{}',NULL,1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                    "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                    "loop_hashes_json,timebase_fingerprint,snapshot_json,"
                    "checkpoint_hash,note,idempotency_key,revision)"
                    " VALUES ('ac','w1','p1','rc',1,'[]','[]','tb','{}',"
                    f"'{'c' * 64}',NULL,NULL,1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO structural_lock_manifest(id,workspace_id,project_id,"
                    "video_item_id,source_generation,version,status,policy_version,"
                    "manifest_hash,manifest_json) VALUES ('m1','w1','p1','v1','gen1',"
                    f"1,'active','structural-thresholds-v1','{'a' * 64}','{{}}')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO s12_export_run(id,workspace_id,project_id,"
                    "video_item_id,checkpoint_id,checkpoint_hash,checkpoint_revision,"
                    "manifest_id,manifest_hash,manifest_generation,profile_id,"
                    "profile_dims,profile_codec,plan_id,plan_hash,status,frame_count,"
                    "chunk_config_json,attempt,natural_key) VALUES ('r1','w1','p1','v1',"
                    f"'ac','{'c' * 64}',1,'m1','{'a' * 64}','gen1',"
                    f"'master-4k-h264','3840x2160','h264','{'d' * 64}',"
                    f"'{'e' * 64}','pending',100,'{{}}',1,'{'f' * 64}')"
                )
            )
    finally:
        eng.dispose()


def test_downgrade_with_rows_refuses(fresh_db_path: Path) -> None:
    command.upgrade(_config(fresh_db_path), "head")
    _seed_export_lineage(fresh_db_path)
    with pytest.raises(Exception, match="refusing to downgrade"):
        command.downgrade(_config(fresh_db_path), PARENT_REV)
    # head unchanged, data intact
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == NEW_REV
            kept = conn.execute(
                text("SELECT COUNT(*) FROM s12_export_run")
            ).scalar()
            assert kept == 1
    finally:
        eng.dispose()


def test_empty_downgrade_drops_only_new_tables(fresh_db_path: Path) -> None:
    command.upgrade(_config(fresh_db_path), "head")
    command.downgrade(_config(fresh_db_path), PARENT_REV)
    names = _table_names(fresh_db_path)
    for table in NEW_TABLES:
        assert table not in names, f"{table} still present after downgrade"
    assert "workspace" in names  # older tables untouched
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == PARENT_REV
    finally:
        eng.dispose()
