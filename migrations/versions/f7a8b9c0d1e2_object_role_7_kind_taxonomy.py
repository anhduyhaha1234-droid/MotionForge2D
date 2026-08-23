"""Widen ObjectRole.kind to the canonical seven Source-Locked 2D kinds (S08-A01).

Approved target profile (`docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md`):
role/layer taxonomy = character, prop, background, foreground,
semantic graphic/text/screen and source-only overlay.  The canonical
backend taxonomy is exactly:

    character | prop | background | foreground | graphic |
    source_overlay | other

Backward compatibility:
- Historical migrations (e.g. e7f8a9b0c1d2) are never touched.
- Existing character/prop/other rows are left byte-identical by this
  migration (the CHECK is widened, not the data).
- ``source_overlay`` is the backend-owned removal-only role.
- Downgrade restores the original 3-kind CHECK; the round-trip loses
  nothing (constraint-only change).

WHY NOT batch_alter_table: an Alembic batch rebuild of ``object_role``
recovers the table through reflection, which converts the COLUMN-level
``source_job_id REFERENCES job(id)`` foreign key (added by the earlier
raw ``ALTER TABLE ADD COLUMN`` in f2a3b4c5d6e7) into a TABLE-level
``FOREIGN KEY(source_job_id) REFERENCES job (id)`` constraint.  SQLite
3.45 then refuses that table's historical ``DROP COLUMN source_job_id``
(f2 downgrade) with ``unknown column "source_job_id" in foreign key
definition`` — breaking the full downgrade chain.  Instead this migration
performs a SURGICAL ``PRAGMA writable_schema`` edit of the stored table
DDL, replacing ONLY the kind CHECK literal.  It is a documented SQLite
technique for constraint-only changes: no table copy, no FK conversion,
no index/column loss, no data rewrite.  The edit is byte-scoped so the
downgrade reverses it deterministically.

Revision: f7a8b9c0d1e2 (revises f6a7b8c9d0e1).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "f7a8b9c0d1e2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None

_OLD_CHECK = "kind IN ('character','prop','other')"
_NEW_CHECK = (
    "kind IN ('character','prop','background','foreground','graphic',"
    "'source_overlay','other')"
)


def _edit_kind_check(conn: Connection, new_check: bool) -> None:
    """Replace the object_role kind CHECK literal in sqlite_master.

    Surgical single-string edit (writable_schema).  ``new_check=True``
    widens to the seven kinds; ``False`` restores the original three.
    Bumps ``schema_version`` so SQLite re-reads the edited DDL immediately
    (no reconnect needed in-process); only the CHECK string is touched so
    the column-level ``source_job_id REFERENCES job(id)`` FK, indexes,
    columns and data are all preserved byte-for-byte.

    S08-A01-C1 (F1) hardening:
    - The target CHECK literal MUST appear EXACTLY ONCE in the stored table
      DDL.  ``str.replace`` silently replaces every occurrence, so an
      ambiguous multi-occurrence needle is a FAILURE (raise), never a guess.
    - ``PRAGMA integrity_check`` and ``PRAGMA foreign_key_check`` run after
      the edit on EVERY decision path — a ``writable_schema`` edit that left
      the DB inconsistent is a failure, not a silent state.
    """
    needle = _OLD_CHECK if new_check else _NEW_CHECK
    replacement = _NEW_CHECK if new_check else _OLD_CHECK
    row = conn.execute(
        sa.text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='object_role'"
        )
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError("object_role table not found in sqlite_master")
    current_sql = row[0]
    needle_count = current_sql.count(needle)
    if needle_count != 1:
        raise RuntimeError(
            f"kind CHECK {needle!r} appears {needle_count} time(s) in "
            f"object_role DDL; refusing ambiguous replacement "
            f"(unexpected current DDL: {current_sql[:200]!r})"
        )
    new_sql = current_sql.replace(needle, replacement)
    conn.execute(sa.text("PRAGMA writable_schema = ON"))
    try:
        conn.execute(
            sa.text(
                "UPDATE sqlite_master SET sql=:sql "
                "WHERE type='table' AND name='object_role'"
            ),
            {"sql": new_sql},
        )
    finally:
        conn.execute(sa.text("PRAGMA writable_schema = OFF"))
    # Force SQLite to re-parse the schema from the edited sqlite_master.
    # PRAGMA takes only a literal, so read the current version, then set the
    # bumped value from Python.
    schema_version = int(conn.execute(sa.text("PRAGMA schema_version")).scalar() or 0)
    conn.execute(sa.text(f"PRAGMA schema_version = {schema_version + 1}"))
    _assert_db_integrity(conn, f"{'upgrade' if new_check else 'downgrade'} CHECK edit")


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
            f"PRAGMA foreign_key_check after {phase} found {len(fk_violations)} "
            f"violation(s): {fk_violations[:5]!r}"
        )


def _assert_no_nonlegacy_kinds(conn: Connection) -> None:
    """F1 fail-closed downgrade pre-check: no new-kind rows may exist.

    Before the CHECK is narrowed 7-kind -> 3-kind, anywhere that stored a
    ``background``/``foreground``/``graphic``/``source_overlay`` row would be
    silently orphaned by the narrow CHECK.  If such rows exist the downgrade
    is REFUSED BEFORE ANY schema or data mutation — ``alembic downgrade``
    exits non-zero and the revision, DDL and rows stay byte-identical.  A new
    kind is NEVER silently converted to ``other``.
    """
    bad = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM object_role "
            "WHERE kind NOT IN ('character','prop','other')"
        )
    ).scalar()
    if int(bad or 0) > 0:
        raise RuntimeError(
            f"refusing to downgrade: {int(bad)} object_role row(s) use a "
            "source-locked 2D kind outside character|prop|other; the 3-kind "
            "CHECK cannot be restored without silently losing or coercing "
            "that classification (S08-A01-C1 F1 fail-closed downgrade)"
        )


def upgrade() -> None:
    _edit_kind_check(op.get_bind(), new_check=True)


def downgrade() -> None:
    # S08-A01-C1 (F1): fail closed BEFORE narrowing the CHECK — if any
    # object_role row uses a kind outside character|prop|other, refuse with
    # ZERO mutation (revision/DDL/rows/indexes/FKs stay byte-identical).
    # Must run before _edit_kind_check so a refused downgrade never touches
    # sqlite_master, the data or the schema_version.
    _assert_no_nonlegacy_kinds(op.get_bind())
    _edit_kind_check(op.get_bind(), new_check=False)
