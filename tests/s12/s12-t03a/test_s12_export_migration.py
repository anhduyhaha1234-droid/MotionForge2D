"""S12-T03A migration tests — export domain revision, corrected for current head.

Two distinct revisions are covered and never conflated:

- ``TARGET_REV`` = ``c3d4e5f6a7b8`` — the revision this suite was written for;
  it creates the three S12 export tables on top of ``PARENT_REV``.
- ``CURRENT_HEAD`` = ``d4e5f6a7b8c9`` — the current sole head at the
  S12-LC3 wave-base: an additive retry-lineage / durable Job binding
  revision on top of ``TARGET_REV``.

Coverage (unchanged semantics, plus the current-head obligations):

- exactly one head, equal to ``CURRENT_HEAD``, and a linear chain whose
  adjacent edges are asserted individually: ``PARENT_REV`` -> ``TARGET_REV``
  and ``TARGET_REV`` -> ``CURRENT_HEAD``;
- fresh DB upgrades to the current head with the three S12 tables, their
  PK/FK/CHECK/reflection metadata, the original index set, and the additive
  lineage columns/indexes/foreign keys;
- upgrade from the parent lands on the target revision (pre-lineage shape),
  seed rows there, then upgrade to the current head: retained data survives,
  the lineage block is backfilled (lineage_id from natural_key, unambiguous
  Job binding), FK integrity holds and the import-side target revision
  upgrade is data-preserving;
- fail-closed downgrade: with rows present the current head refuses BEFORE
  any DDL (exact guard message), the head and rows are unchanged; the
  export-domain guard text is retained; an empty downgrade removes exactly
  the lineage block at the target revision and then drops exactly the three
  tables, landing back on ``PARENT_REV``.

Runs against real migrated temp DBs (never MAIN, never production).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.persistence import create_engine_for_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Revision this suite was written for (creates the S12 export domain).
TARGET_REV = "c3d4e5f6a7b8"
# Current sole head at the S12-LC3 wave-base (additive retry lineage + Job binding).
CURRENT_HEAD = "d4e5f6a7b8c9"
PARENT_REV = "f9a0b1c2d3e4"
NEW_TABLES = ("s12_export_run", "s12_export_chunk", "s12_export_lease")
LINEAGE_COLUMNS = ("lineage_id", "predecessor_run_id", "job_id")


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

def test_single_head_is_current_head() -> None:
    cfg = _config(Path("unused.db"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert set(heads) == {CURRENT_HEAD}, f"expected sole head {CURRENT_HEAD}, got {heads}"


def test_history_links_both_linear_edges() -> None:
    cfg = _config(Path("unused.db"))
    script = ScriptDirectory.from_config(cfg)
    target = script.get_revision(TARGET_REV)
    assert target is not None
    assert target.down_revision == PARENT_REV or (
        isinstance(target.down_revision, tuple) and PARENT_REV in target.down_revision
    )
    head = script.get_revision(CURRENT_HEAD)
    assert head is not None
    assert head.down_revision == TARGET_REV or (
        isinstance(head.down_revision, tuple) and TARGET_REV in head.down_revision
    )


def test_history_walk_from_head_is_linear_to_parent() -> None:
    cfg = _config(Path("unused.db"))
    script = ScriptDirectory.from_config(cfg)
    walked: list[str] = []
    rev = script.get_revision(CURRENT_HEAD)
    while rev is not None:
        walked.append(rev.revision)
        down = rev.down_revision
        if down is None:
            break
        assert isinstance(down, str), f"branched history at {rev.revision}: {down!r}"
        rev = script.get_revision(down)
    assert walked[:3] == [CURRENT_HEAD, TARGET_REV, PARENT_REV], walked


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
            assert ver == CURRENT_HEAD
            fk_bad = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            assert fk_bad == []

        columns = {c["name"] for c in insp.get_columns("s12_export_run")}
        for column in LINEAGE_COLUMNS:
            assert column in columns, f"{column} missing after fresh upgrade to head"
        lineage_indexes = {i["name"] for i in insp.get_indexes("s12_export_run")}
        for index in ("uq_s12_run_lineage_attempt", "uq_s12_run_predecessor", "uq_s12_run_job"):
            assert index in lineage_indexes, index
        fk_names = {fk["name"] for fk in insp.get_foreign_keys("s12_export_run")}
        assert "fk_s12_export_run_job_id_job" in fk_names
        assert "fk_s12_export_run_predecessor_run_id_s12_export_run" in fk_names
    finally:
        eng.dispose()


# ── Upgrade from parent + retained data + lineage backfill ───────────────────

def test_upgrade_from_parent_retains_data_to_current_head(fresh_db_path: Path) -> None:
    # Step 1: the target revision this suite was written for is reachable from
    # the parent and still has the original (pre-lineage) shape.
    command.upgrade(_config(fresh_db_path), TARGET_REV)
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO workspace(id,name) VALUES ('w1','W1')"))
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == TARGET_REV
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(s12_export_run)"))}
            for column in LINEAGE_COLUMNS:
                assert column not in columns, f"{column} exists before {CURRENT_HEAD}"
    finally:
        eng.dispose()

    # Step 2: upgrade to the current sole head; retained rows survive.
    command.upgrade(_config(fresh_db_path), "head")
    eng2 = create_engine_for_path(fresh_db_path)
    try:
        with eng2.connect() as conn:
            kept = conn.execute(
                text("SELECT name FROM workspace WHERE id='w1'")
            ).scalar()
            assert kept == "W1"
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == CURRENT_HEAD
            names = {
                r[0]
                for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            for table in NEW_TABLES:
                assert table in names
            fk_bad = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            assert fk_bad == []
    finally:
        eng2.dispose()


def test_upgrade_to_head_backfills_lineage_from_seeded_run(fresh_db_path: Path) -> None:
    # A pre-lineage export row (seeded at the target revision, with
    # natural_key and a bound durable Job) is retained and backfilled at the
    # current head: lineage_id from natural_key, unambiguous Job binding.
    command.upgrade(_config(fresh_db_path), TARGET_REV)
    _seed_export_lineage(fresh_db_path)
    command.upgrade(_config(fresh_db_path), "head")
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == CURRENT_HEAD
            row = conn.execute(
                text(
                    "SELECT lineage_id, predecessor_run_id, job_id, attempt "
                    "FROM s12_export_run WHERE id='r1'"
                )
            ).one()
            assert row[0] == "f" * 64  # natural_key backfilled as lineage identity
            assert row[1] is None
            assert row[2] == "jb1"
            assert row[3] == 1
            assert conn.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar() == 1
            assert conn.execute(text("SELECT COUNT(*) FROM job")).scalar() == 1
            fk_bad = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            assert fk_bad == []
    finally:
        eng.dispose()


# ── Fail-closed downgrade ────────────────────────────────────────────────────

def _seed_export_lineage(db: Path) -> None:
    eng = create_engine_for_path(db)
    try:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO workspace(id,name) VALUES ('w1','W1')"))
            conn.execute(
                text(
                    "INSERT INTO job(id,workspace_id,job_type,owner_type,owner_id,"
                    "idempotency_key) VALUES ('jb1','w1','S12_EXPORT',"
                    "'video_item','v1','s12_export_job:r1')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO project(id,workspace_id,name) VALUES ('p1','w1','P')"
                )
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


def test_downgrade_with_rows_refuses_at_current_head(fresh_db_path: Path) -> None:
    command.upgrade(_config(fresh_db_path), "head")
    _seed_export_lineage(fresh_db_path)
    # The current head refuses BEFORE any DDL with its exact guard message.
    with pytest.raises(
        Exception,
        match=r"refusing downgrade \(pre-DDL\): 1 row\(s\) exist in 's12_export_run'",
    ):
        command.downgrade(_config(fresh_db_path), PARENT_REV)
    # head unchanged, data intact, lineage columns still present
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == CURRENT_HEAD
            kept = conn.execute(
                text("SELECT COUNT(*) FROM s12_export_run")
            ).scalar()
            assert kept == 1
            assert conn.execute(text("SELECT COUNT(*) FROM job")).scalar() == 1
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(s12_export_run)"))}
            for column in LINEAGE_COLUMNS:
                assert column in columns
    finally:
        eng.dispose()


def test_export_domain_guard_text_is_retained(fresh_db_path: Path) -> None:
    # The target-revision fail-closed guard (export data cannot be dropped)
    # is retained verbatim and still refuses nonempty data in isolation: the
    # current head guard short-circuits the public downgrade before it.
    module_path = (
        PROJECT_ROOT / "migrations" / "versions" / "c3d4e5f6a7b8_s12_export_domain.py"
    )
    spec = importlib.util.spec_from_file_location("s12_export_domain_c3d4e5f6a7b8", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    command.upgrade(_config(fresh_db_path), "head")
    _seed_export_lineage(fresh_db_path)
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.connect() as conn:
            with pytest.raises(Exception, match="refusing to downgrade"):
                module._assert_no_rows(conn, ("s12_export_run",), "pre-DDL check")
            assert conn.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar() == 1
    finally:
        eng.dispose()


def test_empty_downgrade_unwinds_lineage_then_tables(fresh_db_path: Path) -> None:
    command.upgrade(_config(fresh_db_path), "head")

    # One step down: the additive lineage block is removed (target-revision
    # shape), the three export tables stay, and the original six-field run
    # identity unique constraint is restored.
    command.downgrade(_config(fresh_db_path), TARGET_REV)
    eng = create_engine_for_path(fresh_db_path)
    try:
        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == TARGET_REV
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(s12_export_run)"))}
            for column in LINEAGE_COLUMNS:
                assert column not in columns, f"{column} survived the lineage downgrade"
            identity_columns = [
                "workspace_id",
                "project_id",
                "video_item_id",
                "profile_id",
                "plan_hash",
                "checkpoint_hash",
            ]
            restored = False
            for row in conn.execute(text("PRAGMA index_list(s12_export_run)")):
                if row[2] != 1:  # not unique
                    continue
                cols = [r[2] for r in conn.execute(text(f"PRAGMA index_info({row[1]})"))]
                if cols == identity_columns:
                    restored = True
            assert restored, "uq_s12_run_identity not restored at the target revision"
    finally:
        eng.dispose()

    # Final step: empty tables drop cleanly and the DB lands on the parent.
    command.downgrade(_config(fresh_db_path), PARENT_REV)
    names = _table_names(fresh_db_path)
    for table in NEW_TABLES:
        assert table not in names, f"{table} still present after downgrade"
    assert "workspace" in names  # older tables untouched
    eng2 = create_engine_for_path(fresh_db_path)
    try:
        with eng2.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == PARENT_REV
    finally:
        eng2.dispose()
