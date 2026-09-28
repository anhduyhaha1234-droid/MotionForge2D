"""DELTA-F1 — persist whole-shot/GROUP membership on ``s10_full_apply_chunk``.

Adds ONE additive nullable column:

* ``member_layer_ids_json`` TEXT NULL — the canonical (sorted, unique) JSON
  array of ``layer_id`` members the planner froze for a comfy_shot_engine
  whole-shot/GROUP chunk (``app/services/s10_chunk_plan.py``).  It is the
  chunk's membership identity: the worker re-reads it before rendering and
  keeps FAILING CLOSED (``carries no member_layer_ids``) whenever it is
  absent/empty — the guard is NOT widened by this migration.

NULL is meaningful and preserved: legacy per-layer chunks (the
``legacy_renderer`` route) carry no group membership, and every pre-existing
row reads back exactly as before (no UPDATE runs, no DEFAULT is applied).

WHY ADDITIVE + native ``ALTER TABLE ADD COLUMN`` (measured, SQLite 3.45):
the column is nullable, so no table rebuild, no FK interaction and no
stored-DDL surgery are required; the demo-schema table (22 columns,
``PRAGMA table_info`` measured before the fix) simply gains a 23rd column.

``down_revision`` is the MEASURED live head in this worktree
(``python -m alembic heads`` => ``e5f6a7b8c9d0``), never a remembered value.

Fail-closed downgrade: while ANY row carries a non-NULL
``member_layer_ids_json`` (i.e. a persisted group plan exists), ``downgrade``
REFUSES with a stable RuntimeError before any DDL mutation — dropping the
column would silently destroy the frozen membership of real runs.
``PRAGMA foreign_key_check`` / ``integrity_check`` run on every mutation
decision path.

Revision: b3c4d5e6f7a8 (revises e5f6a7b8c9d0).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "b3c4d5e6f7a8"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

_TABLE = "s10_full_apply_chunk"
_COLUMN = "member_layer_ids_json"


def _assert_db_integrity(conn: Connection, phase: str) -> None:
    fk_bad = conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if fk_bad:
        raise RuntimeError(f"foreign_key_check failed at {phase}: {fk_bad[:5]}")
    ok = conn.execute(sa.text("PRAGMA integrity_check")).scalar()
    if ok != "ok":
        raise RuntimeError(f"integrity_check failed at {phase}: {ok}")


def _assert_no_members(conn: Connection) -> None:
    """Fail-closed downgrade pre-check: refuse while persisted members exist."""
    n = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL")
    ).scalar()
    if int(n or 0) != 0:
        raise RuntimeError(
            f"refusing to downgrade: {int(n)} {_TABLE} row(s) carry persisted "
            "whole-shot/GROUP members; dropping the column would silently lose "
            "the frozen plan membership"
        )


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))
    _assert_db_integrity(conn, "upgrade complete")


def downgrade() -> None:
    conn = op.get_bind()
    # Fail closed BEFORE any mutation: a persisted group plan cannot survive
    # the column drop, so the downgrade is refused with ZERO bytes moved.
    _assert_no_members(conn)
    op.drop_column(_TABLE, _COLUMN)
    _assert_db_integrity(conn, "downgrade complete")
