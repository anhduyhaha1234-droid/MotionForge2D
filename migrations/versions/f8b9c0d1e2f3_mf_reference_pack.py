"""MF-END-02 — reference pack persistence branch (legacy_six_slot_2d | reference_pack_v1).

Adds the reference-pack branch to ``character_pack_version``:

* ``pack_contract_version``       VARCHAR(32) NOT NULL
                                  DEFAULT 'legacy_six_slot_2d'
* ``requirement_manifest_json``   TEXT NULL
* ``requirement_manifest_sha256`` VARCHAR(64) NULL

plus four CHECK constraints:

* ``ck_pack_version_contract``            — branch vocabulary (exactly two values)
* ``ck_pack_version_manifest_pair``       — json/sha both NULL or both NOT NULL
* ``ck_pack_version_manifest_sha256_len`` — sha256 is 64 chars when present
* ``ck_pack_version_reference_manifest``  — legacy => NO manifest;
  reference_pack_v1 => manifest REQUIRED

Legacy rows keep the ORIGINAL six-slot 2D contract through the column
DEFAULT — no UPDATE ever runs, so user data is never rewritten; every
pre-existing row reads back as ``legacy_six_slot_2d``.

WHY NOT batch_alter_table (measured 2026-09-28, MF-END-02 recon):
SQLite cannot ``ALTER TABLE ADD CONSTRAINT``, so the usual alembic route is
a batch copy-and-move.  MEASURED in this repository: with child rows present
(``character_asset.pack_version_id`` and ``character.default_version_id``
both reference this table) the batch rebuild fails at ``DROP TABLE
character_pack_version`` with ``FOREIGN KEY constraint failed`` under the
domain contract's ``PRAGMA foreign_keys=ON`` connections.  Instead:

* the three columns are added with native ``ALTER TABLE ADD COLUMN``
  (SQLite >= 3.35; no table rebuild, no FK interaction); and
* the four CHECKs are appended by a SURGICAL ``PRAGMA writable_schema``
  edit of the stored DDL (same documented technique as f7a8b9c0d1e2),
  anchored on the single ``UNIQUE (character_id, version)`` tail so the
  edit is byte-scoped, single-occurrence and reversible.

Downgrade reverses exactly — the CHECK block is removed from the stored
DDL, then the three columns are dropped with native ``ALTER TABLE DROP
COLUMN``; the stored DDL returns to its pre-migration text and no row data
is touched.  A downgrade REFUSES (fail closed, zero bytes moved) while any
``reference_pack_v1`` row exists: dropping the manifest columns would
silently orphan its requirement manifest.

MANAGER PIN CONFLICT (disclosed in REPORT.md): the launch guard pinned
``down_revision = f7a8b9c0d1e2``; the MEASURED sole head in the task
worktree and in the PRODUCT integration tree is ``d4e5f6a7b8c9``.  Chaining
to the pinned (non-head) revision would fork a SECOND head and fail the
binary acceptance "một revision nối live head", so this revision revises
the measured live head.  Revision id and filename stay exactly as pinned.

Revision: f8b9c0d1e2f3 (revises d4e5f6a7b8c9).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "f8b9c0d1e2f3"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

_TABLE = "character_pack_version"

#: Byte format (no space after each comma) matches the frozen literal in
#: ``app/persistence/models.py`` (``PACK_CONTRACT_VERSION_CHECK_SQL``) so the
#: writable_schema edit keeps finding its needle EXACTLY ONCE.
_PACK_CONTRACT_CHECK = (
    "pack_contract_version IN ('legacy_six_slot_2d','reference_pack_v1')"
)
_MANIFEST_PAIR_CHECK = (
    "(requirement_manifest_json IS NULL) = (requirement_manifest_sha256 IS NULL)"
)
_MANIFEST_SHA256_LEN_CHECK = (
    "requirement_manifest_sha256 IS NULL OR length(requirement_manifest_sha256) = 64"
)
_REFERENCE_MANIFEST_CHECK = (
    "(pack_contract_version = 'legacy_six_slot_2d' "
    "AND requirement_manifest_json IS NULL) "
    "OR (pack_contract_version = 'reference_pack_v1' "
    "AND requirement_manifest_json IS NOT NULL)"
)

_NEW_CHECKS = (
    ("ck_pack_version_contract", _PACK_CONTRACT_CHECK),
    ("ck_pack_version_manifest_pair", _MANIFEST_PAIR_CHECK),
    ("ck_pack_version_manifest_sha256_len", _MANIFEST_SHA256_LEN_CHECK),
    ("ck_pack_version_reference_manifest", _REFERENCE_MANIFEST_CHECK),
)

_NEW_COLUMN_NAMES = (
    "pack_contract_version",
    "requirement_manifest_json",
    "requirement_manifest_sha256",
)

#: The stored DDL's single tail constraint; after the native ADD COLUMNs the
#: tail is still ``... UNIQUE (character_id, version)`` followed by ``)``.
_TAIL_ANCHOR = (
    "CONSTRAINT uq_pack_version_character_version UNIQUE (character_id, version)"
)


def _stored_ddl(conn: Connection) -> str:
    row = conn.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": _TABLE},
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"{_TABLE} table not found in sqlite_master")
    return str(row[0])


def _assert_db_integrity(conn: Connection, phase: str) -> None:
    """Fail closed if the DB is not internally consistent after a mutation.

    ``PRAGMA integrity_check`` returns a single first row ``"ok"`` when the
    file/schema is consistent; ``PRAGMA foreign_key_check`` returns zero rows
    when every FK reference resolves.  Any violation is a hard failure — a
    broken DB after a migration must never be silently committed.
    """
    integrity = conn.execute(sa.text("PRAGMA integrity_check")).fetchall()
    if not integrity or str(integrity[0][0]).strip().lower() != "ok":
        raise RuntimeError(
            f"PRAGMA integrity_check after {phase} did not report ok: {integrity!r}"
        )
    fk_violations = conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if fk_violations:
        raise RuntimeError(
            f"PRAGMA foreign_key_check after {phase} found "
            f"{len(fk_violations)} violation(s): {fk_violations[:5]!r}"
        )


def _write_stored_ddl(conn: Connection, new_sql: str, phase: str) -> None:
    conn.execute(sa.text("PRAGMA writable_schema = ON"))
    try:
        conn.execute(
            sa.text(
                "UPDATE sqlite_master SET sql=:sql WHERE type='table' AND name=:t"
            ),
            {"sql": new_sql, "t": _TABLE},
        )
    finally:
        conn.execute(sa.text("PRAGMA writable_schema = OFF"))
    # Force SQLite to re-parse the schema from the edited sqlite_master.
    schema_version = int(conn.execute(sa.text("PRAGMA schema_version")).scalar() or 0)
    conn.execute(sa.text(f"PRAGMA schema_version = {schema_version + 1}"))
    _assert_db_integrity(conn, phase)


def _checks_block(nl: str) -> str:
    return "".join(
        f",{nl}\tCONSTRAINT {name} CHECK ({sql})" for name, sql in _NEW_CHECKS
    )


def _append_checks(conn: Connection) -> None:
    ddl = _stored_ddl(conn)
    nl = "\r\n" if "\r\n" in ddl else "\n"
    if ddl.count(_TAIL_ANCHOR) != 1:
        raise RuntimeError(
            f"tail anchor appears {ddl.count(_TAIL_ANCHOR)} time(s) in stored "
            "DDL; refusing ambiguous writable_schema edit"
        )
    for name, _sql in _NEW_CHECKS:
        if f"CONSTRAINT {name} " in ddl:
            raise RuntimeError(f"CHECK {name!r} already present in stored DDL")
    tail = f"{_TAIL_ANCHOR}{nl})"
    if ddl.count(tail) != 1:
        raise RuntimeError(
            f"tail {tail!r} not found exactly once; unexpected stored DDL tail: "
            f"{ddl[-200:]!r}"
        )
    new_ddl = ddl.replace(tail, f"{_TAIL_ANCHOR}{_checks_block(nl)}{nl})")
    _write_stored_ddl(conn, new_ddl, "upgrade CHECK append")


def _remove_checks(conn: Connection) -> None:
    ddl = _stored_ddl(conn)
    nl = "\r\n" if "\r\n" in ddl else "\n"
    block = _checks_block(nl)
    if ddl.count(block) != 1:
        raise RuntimeError(
            f"appended CHECK block appears {ddl.count(block)} time(s) in stored "
            "DDL; refusing ambiguous reverse edit"
        )
    new_ddl = ddl.replace(block, "")
    _write_stored_ddl(conn, new_ddl, "downgrade CHECK removal")


def _assert_existing_rows_satisfy_new_checks(conn: Connection) -> None:
    """Refuse the upgrade if any pre-existing row would violate the new CHECKs."""
    where = " OR ".join(f"NOT ({sql})" for _name, sql in _NEW_CHECKS)
    bad = conn.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE {where}")).scalar()
    if int(bad or 0) != 0:
        raise RuntimeError(
            f"{int(bad)} existing {_TABLE} row(s) would violate the new "
            "reference-pack CHECK constraints; refusing the migration"
        )


def _assert_no_reference_rows(conn: Connection) -> None:
    """Fail-closed downgrade pre-check: refuse while reference_pack_v1 rows exist."""
    bad = conn.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {_TABLE} "
            "WHERE pack_contract_version = 'reference_pack_v1'"
        )
    ).scalar()
    if int(bad or 0) != 0:
        raise RuntimeError(
            f"refusing to downgrade: {int(bad)} {_TABLE} row(s) are "
            "reference_pack_v1; dropping the manifest columns would silently "
            "orphan their requirement manifest"
        )


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column(
        _TABLE,
        sa.Column(
            "pack_contract_version",
            sa.String(length=32),
            nullable=False,
            server_default="legacy_six_slot_2d",
        ),
    )
    op.add_column(
        _TABLE, sa.Column("requirement_manifest_json", sa.Text(), nullable=True)
    )
    op.add_column(
        _TABLE,
        sa.Column("requirement_manifest_sha256", sa.String(length=64), nullable=True),
    )
    _assert_existing_rows_satisfy_new_checks(conn)
    _append_checks(conn)
    _assert_db_integrity(conn, "upgrade complete")


def downgrade() -> None:
    conn = op.get_bind()
    # Fail closed BEFORE any mutation: a reference_pack_v1 row's requirement
    # manifest cannot survive the column drop, so the downgrade is refused
    # with ZERO bytes moved (revision/DDL/rows stay byte-identical).
    _assert_no_reference_rows(conn)
    _remove_checks(conn)
    for name in reversed(_NEW_COLUMN_NAMES):
        op.drop_column(_TABLE, name)
    _assert_db_integrity(conn, "downgrade complete")
