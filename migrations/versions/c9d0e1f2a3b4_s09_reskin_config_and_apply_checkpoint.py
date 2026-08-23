"""S09-T01: add reskin_config + apply_checkpoint schema (SOLE S09 migration).

Revision ID: c9d0e1f2a3b4
Revises: b2c3d4e5f6a7b
Create Date: 2026-08-23

TWO NEW tables (SQLite CREATE TABLE so every CHECK/FK/index is real
reflection-visible metadata) — this is the ONLY migration of Sprint S09
(MIGRATION DECISION A, frozen; T06 consumes ``apply_checkpoint`` as-is):

- ``reskin_config`` — durable reskin parameter contract pinned to a
  (project, object_role) pair and an immutable CharacterPackVersion:
  stable opaque ``id`` PK, ``workspace_id``/``project_id``/``object_role_id``
  FK RESTRICT, optional ``cast_mapping_id`` FK RESTRICT to
  project_cast_mapping.id, ``character_id`` FK RESTRICT (denormalized guard),
  ``pack_version_id`` FK RESTRICT (immutable pin identity — new publish
  creates a NEW pack_version row and never mutates this FK), ``params_json``
  (fail-closed validated contract), ``idempotency_key``
  UNIQUE(workspace) WHERE NOT NULL, ``revision`` CAS, timestamps.
  UNIQUE(project_id, object_role_id) — one contract per role.

- ``apply_checkpoint`` — IMMUTABLE append-only approval checkpoint
  (schema-only, written by S09-T06): ``reskin_config_id`` FK RESTRICT +
  frozen ``reskin_config_revision``, ``pack_version_ids_json``,
  ``loop_hashes_json``, ``timebase_fingerprint``, ``snapshot_json``,
  ``checkpoint_hash`` (sha256 hex, exactly 64 chars), optional ``note``,
  ``idempotency_key`` UNIQUE(workspace) WHERE NOT NULL, revision CHECK
  ``revision = 1`` (rows are never versioned — no UPDATE, no DELETE).

Fail-closed downgrade: if ANY row exists in either table, ``downgrade``
REFUSES before any DDL/data mutation with a stable RuntimeError; revision,
DDL, rows, indexes and FKs stay byte-identical. PRAGMA integrity_check /
foreign_key_check run on every mutation decision path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b2c3d4e5f6a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = ("reskin_config", "apply_checkpoint")


def _assert_db_integrity(conn: Connection, phase: str) -> None:
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


def _assert_no_reskin_rows(conn: Connection) -> None:
    for table in _NEW_TABLES:
        count = int(
            conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        )
        if count > 0:
            raise RuntimeError(
                f"refusing to downgrade: {count} row(s) exist in {table!r}; "
                "the S09 reskin schema cannot be dropped without silently "
                "losing that data (S09-T01 fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()
    op.create_table(
        "reskin_config",
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
            "cast_mapping_id",
            sa.String(36),
            sa.ForeignKey("project_cast_mapping.id", ondelete="RESTRICT"),
            nullable=True,
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
        sa.Column("params_json", sa.Text(), nullable=False),
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
        sa.CheckConstraint("revision > 0", name="ck_reskin_config_revision_positive"),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_reskin_config_idempotency_key_len",
        ),
        sa.UniqueConstraint(
            "project_id", "object_role_id", name="uq_reskin_config_project_role"
        ),
    )
    op.create_index("ix_reskin_config_workspace", "reskin_config", ["workspace_id"])
    op.create_index("ix_reskin_config_project", "reskin_config", ["project_id"])
    op.create_index("ix_reskin_config_role", "reskin_config", ["object_role_id"])
    op.create_index("ix_reskin_config_pack_version", "reskin_config", ["pack_version_id"])
    op.create_index("ix_reskin_config_mapping", "reskin_config", ["cast_mapping_id"])
    op.create_index(
        "uq_reskin_config_workspace_idempotency",
        "reskin_config",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _assert_db_integrity(conn, "upgrade reskin_config")

    op.create_table(
        "apply_checkpoint",
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
            "reskin_config_id",
            sa.String(36),
            sa.ForeignKey("reskin_config.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reskin_config_revision", sa.Integer(), nullable=False),
        sa.Column("pack_version_ids_json", sa.Text(), nullable=False),
        sa.Column("loop_hashes_json", sa.Text(), nullable=False),
        sa.Column("timebase_fingerprint", sa.String(128), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_hash", sa.String(64), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
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
        sa.CheckConstraint(
            "revision = 1", name="ck_apply_checkpoint_immutable_revision"
        ),
        sa.CheckConstraint(
            "length(checkpoint_hash) = 64",
            name="ck_apply_checkpoint_hash_len",
        ),
    )
    op.create_index("ix_apply_checkpoint_workspace", "apply_checkpoint", ["workspace_id"])
    op.create_index("ix_apply_checkpoint_project", "apply_checkpoint", ["project_id"])
    op.create_index("ix_apply_checkpoint_created", "apply_checkpoint", ["created_at"])
    op.create_index(
        "uq_apply_checkpoint_workspace_idempotency",
        "apply_checkpoint",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _assert_db_integrity(conn, "upgrade apply_checkpoint")


def downgrade() -> None:
    conn = op.get_bind()
    _assert_no_reskin_rows(conn)
    op.drop_index(
        "uq_apply_checkpoint_workspace_idempotency", table_name="apply_checkpoint"
    )
    op.drop_index("ix_apply_checkpoint_created", table_name="apply_checkpoint")
    op.drop_index("ix_apply_checkpoint_project", table_name="apply_checkpoint")
    op.drop_index("ix_apply_checkpoint_workspace", table_name="apply_checkpoint")
    op.drop_table("apply_checkpoint")
    _assert_db_integrity(conn, "downgrade apply_checkpoint")
    op.drop_index(
        "uq_reskin_config_workspace_idempotency", table_name="reskin_config"
    )
    op.drop_index("ix_reskin_config_mapping", table_name="reskin_config")
    op.drop_index("ix_reskin_config_pack_version", table_name="reskin_config")
    op.drop_index("ix_reskin_config_role", table_name="reskin_config")
    op.drop_index("ix_reskin_config_project", table_name="reskin_config")
    op.drop_index("ix_reskin_config_workspace", table_name="reskin_config")
    op.drop_table("reskin_config")
    _assert_db_integrity(conn, "downgrade reskin_config")
