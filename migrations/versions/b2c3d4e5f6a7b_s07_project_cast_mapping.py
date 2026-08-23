"""Add S07-T01 Project Cast Mapping schema (project_cast_mapping).

Revision ID: b2c3d4e5f6a7b
Revises: a0b1c2d3e4f5

One NEW table (SQLite CREATE TABLE so every CHECK/FK/index is real
reflection-visible metadata):

- ``project_cast_mapping`` — pins a Project Object Role to an immutable
  Character Pack Version:
  stable opaque ``id`` PK, ``workspace_id`` FK RESTRICT, ``project_id`` FK
  RESTRICT, ``object_role_id`` FK RESTRICT, ``character_id`` FK RESTRICT
  (denormalized guard), ``pack_version_id`` FK RESTRICT (immutable row
  identity — new publish creates NEW pack_version row, old mapping FK still
  points old row), ``idempotency_key`` UNIQUE(workspace) WHERE IS NOT NULL,
  ``revision`` CAS, ``created_at``/``updated_at``. All FKs RESTRICT fail
  closed. Parity with app.persistence.models ProjectCastMapping is asserted
  by migration tests.

Fail-closed downgrade: if ANY row exists in project_cast_mapping,
``downgrade`` REFUSES before any DDL/data mutation with a stable
RuntimeError; revision, DDL, rows, indexes and FKs stay byte-identical.
PRAGMA integrity_check / foreign_key_check run on every mutation decision
path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "b2c3d4e5f6a7b"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = ("project_cast_mapping",)


def _assert_db_integrity(conn: Connection, phase: str) -> None:
    integrity = conn.execute(sa.text("PRAGMA integrity_check")).fetchall()
    if not integrity or str(integrity[0][0]).strip().lower() != "ok":
        raise RuntimeError(f"PRAGMA integrity_check after {phase} did not report ok: {integrity!r}")
    fk_violations = conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if fk_violations:
        raise RuntimeError(
            f"PRAGMA foreign_key_check after {phase} found {len(fk_violations)} violation(s): {fk_violations[:5]!r}"
        )


def _assert_no_project_cast_rows(conn: Connection) -> None:
    for table in _NEW_TABLES:
        count = int(conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
        if count > 0:
            raise RuntimeError(
                f"refusing to downgrade: {count} project cast mapping row(s) exist in {table!r}; "
                "the project_cast_mapping schema cannot be dropped without silently losing that data "
                "(S07-T01 fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()
    op.create_table(
        "project_cast_mapping",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("project.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "object_role_id",
            sa.String(36),
            sa.ForeignKey("object_role.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            sa.String(36),
            sa.ForeignKey("character.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pack_version_id",
            sa.String(36),
            sa.ForeignKey("character_pack_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.CheckConstraint("revision > 0", name="ck_project_cast_mapping_revision_positive"),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_project_cast_mapping_idempotency_key_len",
        ),
        sa.UniqueConstraint(
            "project_id", "object_role_id", name="uq_project_cast_project_role"
        ),
    )
    op.create_index(
        "ix_project_cast_mapping_workspace", "project_cast_mapping", ["workspace_id"]
    )
    op.create_index(
        "ix_project_cast_mapping_project", "project_cast_mapping", ["project_id"]
    )
    op.create_index(
        "ix_project_cast_mapping_role", "project_cast_mapping", ["object_role_id"]
    )
    op.create_index(
        "ix_project_cast_mapping_pack_version", "project_cast_mapping", ["pack_version_id"]
    )
    op.create_index(
        "ix_project_cast_mapping_character", "project_cast_mapping", ["character_id"]
    )
    op.create_index(
        "uq_project_cast_mapping_workspace_idempotency",
        "project_cast_mapping",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _assert_db_integrity(conn, "upgrade project_cast_mapping")


def downgrade() -> None:
    conn = op.get_bind()
    _assert_no_project_cast_rows(conn)
    op.drop_index(
        "uq_project_cast_mapping_workspace_idempotency", table_name="project_cast_mapping"
    )
    op.drop_index("ix_project_cast_mapping_character", table_name="project_cast_mapping")
    op.drop_index("ix_project_cast_mapping_pack_version", table_name="project_cast_mapping")
    op.drop_index("ix_project_cast_mapping_role", table_name="project_cast_mapping")
    op.drop_index("ix_project_cast_mapping_project", table_name="project_cast_mapping")
    op.drop_index("ix_project_cast_mapping_workspace", table_name="project_cast_mapping")
    op.drop_table("project_cast_mapping")
    _assert_db_integrity(conn, "downgrade project_cast_mapping")
