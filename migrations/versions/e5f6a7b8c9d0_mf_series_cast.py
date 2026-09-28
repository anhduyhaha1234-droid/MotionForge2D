"""MF-END-05 — series cast snapshot schema (series pin).

Revision ID: e5f6a7b8c9d0
Revises: f8b9c0d1e2f3 (MF-END-02 reference pack branch)

Two NEW tables (SQLite CREATE TABLE so every CHECK/FK/index is real
reflection-visible metadata):

- ``series_cast_snapshot`` — immutable, versioned freeze ("snapshot_index")
  of the cast bindings the videos of one series (the project that is the
  production container for the series) reuse.  ``entries_sha256`` covers the
  canonical JSON serialization of all entries; readers recompute and refuse
  on mismatch.

- ``series_cast_snapshot_entry`` — one frozen
  ``role_key -> character / pack_version / manifest sha256 / style`` entry.
  The reference-pack branch of ``character_pack_version`` (MF-END-02) is
  frozen into ``pack_contract_version`` + ``manifest_sha256`` (legacy => no
  manifest, reference_pack_v1 => manifest required), and
  ``references_json`` freezes the canonical per-key asset list
  (``pose_slot`` / ``artifact_id`` / ``sha256``).  No library row is copied:
  entries reference the immutable library rows by FK RESTRICT only.

Rows are INSERT-only in the application layer: changing a cast member creates
``snapshot_index + 1``; nothing rewrites an existing snapshot.  Parity with
``app.persistence.models`` (``SeriesCastSnapshot`` / ``SeriesCastSnapshotEntry``)
is asserted by migration tests.

Fail-closed downgrade: if ANY ``series_cast_snapshot`` row exists, ``downgrade``
REFUSES before any DDL mutation with a stable RuntimeError — the snapshot data
cannot be dropped silently.  PRAGMA integrity_check / foreign_key_check run on
every mutation decision path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "f8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SNAPSHOT_TABLE = "series_cast_snapshot"
_ENTRY_TABLE = "series_cast_snapshot_entry"


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


def _assert_no_snapshot_rows(conn: Connection) -> None:
    count = int(
        conn.execute(sa.text(f"SELECT COUNT(*) FROM {_SNAPSHOT_TABLE}")).scalar() or 0
    )
    if count > 0:
        raise RuntimeError(
            f"refusing to downgrade: {count} series cast snapshot row(s) exist in "
            f"{_SNAPSHOT_TABLE!r}; the series cast schema cannot be dropped without "
            "silently losing that data (MF-END-05 fail-closed downgrade)"
        )


def upgrade() -> None:
    conn = op.get_bind()
    op.create_table(
        _SNAPSHOT_TABLE,
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
        sa.Column("snapshot_index", sa.Integer(), nullable=False),
        sa.Column("entries_sha256", sa.String(64), nullable=False),
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
            "snapshot_index >= 1", name="ck_series_cast_snapshot_index_positive"
        ),
        sa.CheckConstraint(
            "length(entries_sha256) = 64",
            name="ck_series_cast_snapshot_entries_sha_len",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_series_cast_snapshot_revision_positive"
        ),
        sa.UniqueConstraint(
            "project_id",
            "snapshot_index",
            name="uq_series_cast_snapshot_project_index",
        ),
    )
    op.create_index(
        "ix_series_cast_snapshot_workspace", _SNAPSHOT_TABLE, ["workspace_id"]
    )
    op.create_index(
        "ix_series_cast_snapshot_project", _SNAPSHOT_TABLE, ["project_id"]
    )
    op.create_table(
        _ENTRY_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey(f"{_SNAPSHOT_TABLE}.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role_key", sa.String(64), nullable=False),
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
        sa.Column("pack_contract_version", sa.String(32), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("style_version", sa.String(64), nullable=True),
        sa.Column("references_json", sa.Text(), nullable=False),
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
            "length(role_key) BETWEEN 1 AND 64",
            name="ck_series_cast_entry_role_key_len",
        ),
        sa.CheckConstraint(
            "pack_contract_version IN ('legacy_six_slot_2d','reference_pack_v1')",
            name="ck_series_cast_entry_contract",
        ),
        sa.CheckConstraint(
            "(pack_contract_version = 'legacy_six_slot_2d' "
            "AND manifest_sha256 IS NULL) "
            "OR (pack_contract_version = 'reference_pack_v1' "
            "AND manifest_sha256 IS NOT NULL)",
            name="ck_series_cast_entry_manifest_branch",
        ),
        sa.CheckConstraint(
            "manifest_sha256 IS NULL OR length(manifest_sha256) = 64",
            name="ck_series_cast_entry_manifest_sha_len",
        ),
        sa.CheckConstraint(
            "style_version IS NULL OR length(style_version) BETWEEN 1 AND 64",
            name="ck_series_cast_entry_style_len",
        ),
        sa.CheckConstraint(
            "length(references_json) > 0",
            name="ck_series_cast_entry_refs_nonempty",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_series_cast_entry_revision_positive"
        ),
        sa.UniqueConstraint(
            "snapshot_id", "role_key", name="uq_series_cast_entry_snapshot_role"
        ),
    )
    op.create_index("ix_series_cast_entry_snapshot", _ENTRY_TABLE, ["snapshot_id"])
    op.create_index("ix_series_cast_entry_workspace", _ENTRY_TABLE, ["workspace_id"])
    op.create_index(
        "ix_series_cast_entry_pack_version", _ENTRY_TABLE, ["pack_version_id"]
    )
    op.create_index("ix_series_cast_entry_character", _ENTRY_TABLE, ["character_id"])
    _assert_db_integrity(conn, "upgrade series cast snapshot")


def downgrade() -> None:
    conn = op.get_bind()
    _assert_no_snapshot_rows(conn)
    op.drop_index("ix_series_cast_entry_character", table_name=_ENTRY_TABLE)
    op.drop_index("ix_series_cast_entry_pack_version", table_name=_ENTRY_TABLE)
    op.drop_index("ix_series_cast_entry_workspace", table_name=_ENTRY_TABLE)
    op.drop_index("ix_series_cast_entry_snapshot", table_name=_ENTRY_TABLE)
    op.drop_table(_ENTRY_TABLE)
    op.drop_index("ix_series_cast_snapshot_project", table_name=_SNAPSHOT_TABLE)
    op.drop_index("ix_series_cast_snapshot_workspace", table_name=_SNAPSHOT_TABLE)
    op.drop_table(_SNAPSHOT_TABLE)
    _assert_db_integrity(conn, "downgrade series cast snapshot")
