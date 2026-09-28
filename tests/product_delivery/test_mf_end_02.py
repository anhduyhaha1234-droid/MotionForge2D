"""MF-END-02 — reference pack persistence: acceptance + negative controls.

Row map (binary):

* micro repro: the single live Alembic head is the new revision; the previous
  head has EXACTLY ONE child (no fork); the ORM table carries the three
  branch columns + the four CHECK constraints;
* acceptance: fresh upgrade creates the branch schema; upgrade from the
  previous head with seeded legacy rows keeps every row readable as
  ``legacy_six_slot_2d`` (no data rewrite) and round-trips downgrade ->
  upgrade with the stored DDL restored byte-identically; reference_pack_v1
  fields persist after a restart (engine dispose + reopen); the legacy
  repository reader contract is unchanged;
* negative controls: unknown branch refused; reference_pack_v1 without
  manifest refused; legacy WITH manifest refused; half manifest pair
  refused; short sha256 refused; downgrade with a reference row refused
  with ZERO mutation (revision/DDL/rows byte-identical).

Every negative control asserts the FAILING CONSTRAINT NAME from the SQLite
error text and that the failure is NOT a foreign-key error, so a missing
parent row can never masquerade as a CHECK refusal.

All databases are fresh temp SQLite files under pytest's ``tmp_path`` — the
real application database is never opened.  No GPU, no network, no ffmpeg.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence import create_engine_for_path
from app.persistence.characters import CharacterRepository
from app.persistence.models import (
    PACK_CONTRACT_VERSION_LEGACY,
    PACK_CONTRACT_VERSION_REFERENCE,
    CharacterPackVersion,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATIONS = PROJECT_ROOT / "migrations"

#: Frozen identities of this round; the head is ALSO discovered live (see
#: :func:`_live_heads`) so a newer revision stacked on top cannot silently
#: re-point the chain assertions.  MF-END-05 (writer codex/mf-end-05-0928)
#: stacked e5f6a7b8c9d0 on this revision: rows asserting "upgrade head
#: lands on the migrated head" now follow :func:`_live_head()`, while
#: every revision-identity and chain assertion stays pinned.  Impact is
#: recorded in the MF-END-05 write-set guard disclosure before patching.
NEW_REVISION = "f8b9c0d1e2f3"
PREV_HEAD = "d4e5f6a7b8c9"
WS = "ws-mf-end-02"

ORIGINAL_COLUMNS = (
    "id",
    "character_id",
    "workspace_id",
    "version",
    "status",
    "validation_json",
    "published_at",
    "revision",
    "created_at",
    "updated_at",
    "archived_at",
)
BRANCH_COLUMNS = (
    "pack_contract_version",
    "requirement_manifest_json",
    "requirement_manifest_sha256",
)
CHECK_NAMES = (
    "ck_pack_version_contract",
    "ck_pack_version_manifest_pair",
    "ck_pack_version_manifest_sha256_len",
    "ck_pack_version_reference_manifest",
)

MANIFEST = {
    "pack_contract": "reference_pack_v1",
    "requirements": ["identity", "front", "side", "back"],
    "source": "MF-END-02 acceptance fixture",
}
MANIFEST_JSON = json.dumps(MANIFEST, sort_keys=True, separators=(",", ":"))
MANIFEST_SHA = hashlib.sha256(MANIFEST_JSON.encode("utf-8")).hexdigest()


# ── helpers ───────────────────────────────────────────────────────────────────


def _live_heads() -> list[str]:
    return list(ScriptDirectory(str(MIGRATIONS)).get_heads())


def _live_head() -> str:
    """The single live head.

    MF-END-05 (writer codex/mf-end-05-0928) stacked e5f6a7b8c9d0 on
    this suite's revision; rows asserting "upgrade head lands on the
    migrated head" follow the live head discovery instead of the
    frozen epoch id.
    """
    heads = _live_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads}"
    return heads[0]


def _alembic_config(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _upgrade(db: Path, revision: str = "head") -> None:
    command.upgrade(_alembic_config(db), revision)


def _downgrade(db: Path, revision: str) -> None:
    command.downgrade(_alembic_config(db), revision)


def _connect_query(db: Path, sql: str, params: dict | None = None):
    engine = create_engine_for_path(db)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params or {}).fetchall()
    finally:
        engine.dispose()


def _alembic_version(db: Path) -> str:
    return str(_connect_query(db, "SELECT version_num FROM alembic_version")[0][0])


def _table_ddl(db: Path) -> str:
    return str(
        _connect_query(
            db,
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='character_pack_version'",
        )[0][0]
    )


def _column_info(db: Path) -> dict[str, dict]:
    rows = _connect_query(db, "PRAGMA table_info(character_pack_version)")
    return {
        str(r[1]): {"type": str(r[2]), "notnull": int(r[3]), "default": r[4]}
        for r in rows
    }


def _integrity(db: Path) -> tuple[str, list]:
    integrity = _connect_query(db, "PRAGMA integrity_check")
    fk = _connect_query(db, "PRAGMA foreign_key_check")
    return str(integrity[0][0]), list(fk)


def _rows(db: Path, columns: tuple[str, ...] = ORIGINAL_COLUMNS) -> list[tuple]:
    sel = ", ".join(columns)
    return [
        tuple(r)
        for r in _connect_query(
            db, f"SELECT {sel} FROM character_pack_version ORDER BY id"
        )
    ]


def _ensure_parent_rows(db: Path) -> None:
    """Ensure the workspace + ``char-ref`` character exist for branch rows.

    A branch row must never fail on a missing parent: the negative controls
    assert the CHECK constraint name, and a foreign-key error would be a
    different (wrong) failure.
    """
    engine = create_engine_for_path(db)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)"),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO character(id,workspace_id,name,code) "
                    "VALUES ('char-ref',:w,'Reference Holder','char-ref')"
                ),
                {"w": WS},
            )
    finally:
        engine.dispose()


def _seed_legacy(db: Path, tag: str) -> dict[str, str]:
    """Seed a realistic legacy pack: parent + pose asset child + default pin.

    The child rows (``character_asset.pack_version_id`` and
    ``character.default_version_id``) are the exact configuration under which
    the batch-rebuild route was MEASURED to fail, so their survival is part
    of the acceptance.
    """
    ids = {
        "character": f"char-{tag}",
        "artifact": f"art-{tag}",
        "version": f"pack-{tag}",
        "asset": f"asset-{tag}",
    }
    engine = create_engine_for_path(db)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)"),
                {"w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO character(id,workspace_id,name,code) "
                    "VALUES (:c,:w,:n,:n)"
                ),
                {"c": ids["character"], "w": WS, "n": f"legacy-{tag}"},
            )
            conn.execute(
                text(
                    "INSERT INTO artifact(id,workspace_id,kind,relative_path) "
                    "VALUES (:a,:w,'image',:p)"
                ),
                {"a": ids["artifact"], "w": WS, "p": f"packs/{tag}/front.png"},
            )
            conn.execute(
                text(
                    "INSERT INTO character_pack_version"
                    "(id,character_id,workspace_id,version) VALUES (:v,:c,:w,1)"
                ),
                {"v": ids["version"], "c": ids["character"], "w": WS},
            )
            conn.execute(
                text(
                    "INSERT INTO character_asset"
                    "(id,pack_version_id,workspace_id,pose_slot,artifact_id) "
                    "VALUES (:s,:v,:w,'front',:a)"
                ),
                {"s": ids["asset"], "v": ids["version"], "w": WS, "a": ids["artifact"]},
            )
            conn.execute(
                text("UPDATE character SET default_version_id=:v WHERE id=:c"),
                {"v": ids["version"], "c": ids["character"]},
            )
    finally:
        engine.dispose()
    return ids


def _insert_pack_row(
    db: Path,
    row_id: str,
    *,
    contract: str,
    manifest_json: str | None,
    manifest_sha: str | None,
    version: int,
) -> None:
    """Raw insert of a branch row; raises IntegrityError on CHECK violations."""
    _ensure_parent_rows(db)
    engine = create_engine_for_path(db)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO character_pack_version"
                    "(id,character_id,workspace_id,version,pack_contract_version,"
                    "requirement_manifest_json,requirement_manifest_sha256) "
                    "VALUES (:id,:c,:w,:ver,:cv,:mj,:ms)"
                ),
                {
                    "id": row_id,
                    "c": "char-ref",
                    "w": WS,
                    "ver": version,
                    "cv": contract,
                    "mj": manifest_json,
                    "ms": manifest_sha,
                },
            )
    finally:
        engine.dispose()


def _insert_reference_row_orm(db: Path, row_id: str, version: int) -> None:
    """ORM insert of a reference_pack_v1 row (Python-side defaults path)."""
    _ensure_parent_rows(db)
    engine = create_engine_for_path(db)
    try:
        with Session(engine) as session:
            session.add(
                CharacterPackVersion(
                    id=row_id,
                    character_id="char-ref",
                    workspace_id=WS,
                    version=version,
                    status="draft",
                    pack_contract_version=PACK_CONTRACT_VERSION_REFERENCE,
                    requirement_manifest_json=MANIFEST_JSON,
                    requirement_manifest_sha256=MANIFEST_SHA,
                )
            )
            session.commit()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def head_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One REAL ``upgrade head`` run, reused by tests that only need head bytes."""
    db = tmp_path_factory.mktemp("mfe02-templates") / "head.db"
    _upgrade(db, "head")
    assert _alembic_version(db) == _live_head()
    return db


@pytest.fixture(scope="module")
def prev_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One REAL ``upgrade`` to the PREVIOUS head, reused for legacy-DB tests."""
    db = tmp_path_factory.mktemp("mfe02-templates") / "prev.db"
    _upgrade(db, PREV_HEAD)
    assert _alembic_version(db) == PREV_HEAD
    return db


def _copy_template(template: Path, tmp_path: Path, name: str) -> Path:
    db = tmp_path / name
    shutil.copyfile(template, db)
    return db


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_repro_sole_head_is_the_new_revision() -> None:
    heads = _live_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads}"
    script = ScriptDirectory(str(MIGRATIONS))
    revision = script.get_revision(NEW_REVISION)
    assert revision.down_revision == PREV_HEAD, (
        f"new revision must chain the live head {PREV_HEAD}, "
        f"got {revision.down_revision!r}"
    )
    # MF-END-05: the sole head is this revision or a LINEAR descendant of
    # it (e5f6a7b8c9d0 stacked on top); the chain itself must stay linear.
    cursor = script.get_revision(heads[0])
    visited: set[str] = set()
    while cursor is not None and cursor.revision != NEW_REVISION:
        assert cursor.revision not in visited, (
            f"migration graph cycles at {cursor.revision}"
        )
        visited.add(cursor.revision)
        cursor = (
            script.get_revision(cursor.down_revision)
            if cursor.down_revision
            else None
        )
    assert cursor is not None, f"{NEW_REVISION} must remain in the live head chain"


def test_micro_repro_previous_head_has_exactly_one_child() -> None:
    script = ScriptDirectory(str(MIGRATIONS))
    children = [
        rev.revision
        for rev in script.walk_revisions()
        if rev.down_revision == PREV_HEAD
    ]
    assert children == [NEW_REVISION], f"migration graph forked: {children}"


def test_micro_repro_orm_table_carries_branch_columns_and_checks() -> None:
    table = CharacterPackVersion.__table__
    assert set(BRANCH_COLUMNS) <= {c.name for c in table.columns}
    assert table.c.pack_contract_version.nullable is False
    assert table.c.pack_contract_version.default is not None
    assert table.c.requirement_manifest_json.nullable is True
    assert table.c.requirement_manifest_sha256.nullable is True
    constraint_names = {c.name for c in table.constraints}
    assert set(CHECK_NAMES) <= constraint_names


# ── acceptance ────────────────────────────────────────────────────────────────


def test_fresh_upgrade_adds_branch_columns_and_checks(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    _upgrade(db, "head")
    assert _alembic_version(db) == _live_head()

    info = _column_info(db)
    assert info["pack_contract_version"]["notnull"] == 1
    assert info["pack_contract_version"]["default"] == "'legacy_six_slot_2d'"
    assert info["requirement_manifest_json"]["notnull"] == 0
    assert info["requirement_manifest_sha256"]["notnull"] == 0

    ddl = _table_ddl(db)
    for name in CHECK_NAMES:
        assert f"CONSTRAINT {name} CHECK" in ddl, f"missing {name} in stored DDL"
    assert "ck_pack_version_positive" in ddl  # pre-existing checks survive

    integrity, fk = _integrity(db)
    assert integrity == "ok"
    assert fk == []


def test_upgrade_from_previous_head_preserves_legacy_rows_and_round_trips(
    tmp_path: Path, prev_template: Path
) -> None:
    db = _copy_template(prev_template, tmp_path, "legacy.db")
    ids = _seed_legacy(db, "roundtrip")
    rows_before = _rows(db)
    ddl_before = _table_ddl(db)
    assert len(rows_before) == 1

    _upgrade(db, "head")
    assert _alembic_version(db) == _live_head()

    rows_after = _rows(db)
    assert rows_after == rows_before, "original columns must be byte-identical"
    branch = _rows(db, ("id",) + BRANCH_COLUMNS)
    assert branch == [(ids["version"], PACK_CONTRACT_VERSION_LEGACY, None, None)]

    # child rows and the default-version pin survive the migration
    assert _connect_query(
        db, "SELECT pack_version_id FROM character_asset WHERE id=:s", {"s": ids["asset"]}
    )[0][0] == ids["version"]
    assert _connect_query(
        db, "SELECT default_version_id FROM character WHERE id=:c", {"c": ids["character"]}
    )[0][0] == ids["version"]
    integrity, fk = _integrity(db)
    assert integrity == "ok"
    assert fk == []

    # downgrade restores the stored DDL byte-identically and keeps every row
    _downgrade(db, PREV_HEAD)
    assert _alembic_version(db) == PREV_HEAD
    assert _table_ddl(db) == ddl_before, "downgrade must restore the pre-migration DDL"
    assert _rows(db) == rows_before
    assert set(BRANCH_COLUMNS).isdisjoint(_column_info(db))

    # round trip: upgrade again -> legacy row still reads legacy_six_slot_2d
    _upgrade(db, "head")
    assert _alembic_version(db) == _live_head()
    assert _rows(db) == rows_before
    assert _rows(db, ("id",) + BRANCH_COLUMNS) == [
        (ids["version"], PACK_CONTRACT_VERSION_LEGACY, None, None)
    ]


def test_reference_pack_fields_persist_after_restart(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "restart.db")
    ids = _seed_legacy(db, "restart")
    _insert_reference_row_orm(db, "pack-ref-1", version=2)

    # restart: dispose + brand-new engine, as the app does per process
    engine = create_engine_for_path(db)
    engine.dispose()
    engine2 = create_engine_for_path(db)
    try:
        with Session(engine2) as session:
            ref = session.get(CharacterPackVersion, "pack-ref-1")
            assert ref is not None
            assert ref.pack_contract_version == PACK_CONTRACT_VERSION_REFERENCE
            assert json.loads(ref.requirement_manifest_json) == MANIFEST
            assert ref.requirement_manifest_sha256 == MANIFEST_SHA
            assert (
                hashlib.sha256(ref.requirement_manifest_json.encode("utf-8")).hexdigest()
                == ref.requirement_manifest_sha256
            )
            legacy = session.get(CharacterPackVersion, ids["version"])
            assert legacy is not None
            assert legacy.pack_contract_version == PACK_CONTRACT_VERSION_LEGACY
            assert legacy.requirement_manifest_json is None
            assert legacy.requirement_manifest_sha256 is None
    finally:
        engine2.dispose()


def test_legacy_repository_reader_contract_unchanged(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "reader.db")
    engine = create_engine_for_path(db)
    try:
        with Session(engine) as session:
            repo = CharacterRepository(session)
            character = repo.create_character(WS, "Book Holder", "book-holder")
            created = repo.create_pack_version(character.id, WS)
            session.commit()
            listed = repo.list_pack_versions(character.id, WS)
            fetched = repo.get_pack_version(created.id, WS)
    finally:
        engine.dispose()

    assert [v.id for v in listed] == [created.id]
    assert fetched.version == 1
    assert fetched.status == "draft"
    assert fetched.validation_json is None
    assert fetched.assets == []
    # the legacy DTO stays exactly the six-slot contract record
    assert not hasattr(fetched, "pack_contract_version")


# ── negative controls ─────────────────────────────────────────────────────────


def test_negative_unknown_contract_version_refused(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "neg-version.db")
    with pytest.raises(IntegrityError) as excinfo:
        _insert_pack_row(
            db,
            "neg-1",
            contract="six_slot_3d",
            manifest_json=None,
            manifest_sha=None,
            version=2,
        )
    message = str(excinfo.value)
    assert "FOREIGN KEY" not in message, message
    assert any(
        name in message
        for name in ("ck_pack_version_contract", "ck_pack_version_reference_manifest")
    ), message


def test_negative_reference_pack_without_manifest_refused(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "neg-no-manifest.db")
    with pytest.raises(IntegrityError) as excinfo:
        _insert_pack_row(
            db,
            "neg-2",
            contract=PACK_CONTRACT_VERSION_REFERENCE,
            manifest_json=None,
            manifest_sha=None,
            version=2,
        )
    message = str(excinfo.value)
    assert "FOREIGN KEY" not in message, message
    assert "ck_pack_version_reference_manifest" in message, message


def test_negative_legacy_pack_with_manifest_refused(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "neg-legacy-manifest.db")
    with pytest.raises(IntegrityError) as excinfo:
        _insert_pack_row(
            db,
            "neg-3",
            contract=PACK_CONTRACT_VERSION_LEGACY,
            manifest_json=MANIFEST_JSON,
            manifest_sha=MANIFEST_SHA,
            version=2,
        )
    message = str(excinfo.value)
    assert "FOREIGN KEY" not in message, message
    assert "ck_pack_version_reference_manifest" in message, message


def test_negative_half_manifest_pair_refused(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "neg-half-pair.db")
    # reference_pack_v1 with json but no sha -> ONLY the pair CHECK fails
    with pytest.raises(IntegrityError) as excinfo:
        _insert_pack_row(
            db,
            "neg-4a",
            contract=PACK_CONTRACT_VERSION_REFERENCE,
            manifest_json=MANIFEST_JSON,
            manifest_sha=None,
            version=2,
        )
    message = str(excinfo.value)
    assert "FOREIGN KEY" not in message, message
    assert "ck_pack_version_manifest_pair" in message, message
    # legacy with sha but no json -> ONLY the pair CHECK fails
    with pytest.raises(IntegrityError) as excinfo:
        _insert_pack_row(
            db,
            "neg-4b",
            contract=PACK_CONTRACT_VERSION_LEGACY,
            manifest_json=None,
            manifest_sha=MANIFEST_SHA,
            version=3,
        )
    message = str(excinfo.value)
    assert "FOREIGN KEY" not in message, message
    assert "ck_pack_version_manifest_pair" in message, message


def test_negative_short_manifest_sha256_refused(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "neg-short-sha.db")
    with pytest.raises(IntegrityError) as excinfo:
        _insert_pack_row(
            db,
            "neg-5",
            contract=PACK_CONTRACT_VERSION_REFERENCE,
            manifest_json=MANIFEST_JSON,
            manifest_sha=MANIFEST_SHA[:63],
            version=2,
        )
    message = str(excinfo.value)
    assert "FOREIGN KEY" not in message, message
    assert "ck_pack_version_manifest_sha256_len" in message, message


def test_negative_downgrade_with_reference_row_refused_zero_mutation(
    tmp_path: Path, head_template: Path
) -> None:
    db = _copy_template(head_template, tmp_path, "neg-downgrade.db")
    # MF-END-05: head_template now carries the stacked successor revision;
    # this row tests the END-02 downgrade refusal, so pin the copy to THIS
    # suite's revision first (the stacked revision holds no rows to refuse).
    if _alembic_version(db) != NEW_REVISION:
        _downgrade(db, NEW_REVISION)
        assert _alembic_version(db) == NEW_REVISION
    _seed_legacy(db, "downgrade")
    _insert_reference_row_orm(db, "pack-ref-downgrade", version=2)

    ddl_before = _table_ddl(db)
    rows_before = _rows(db)
    version_before = _alembic_version(db)

    with pytest.raises(Exception) as excinfo:
        _downgrade(db, PREV_HEAD)
    assert "refusing to downgrade" in str(excinfo.value)

    assert _alembic_version(db) == version_before == NEW_REVISION
    assert _table_ddl(db) == ddl_before
    assert _rows(db) == rows_before
    integrity, fk = _integrity(db)
    assert integrity == "ok"
    assert fk == []
