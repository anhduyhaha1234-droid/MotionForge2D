"""S09-T05A: targeted correction archive schema (additive).

Revision ID: b3c4d5e6f7a9
Revises: d8e9f0a1b2c3 (live-discovered at runtime — never hard-coded in
gates; the literal here is the parent link Alembic itself requires)
Create Date: 2026-08-24

Sole S09-T05A migration.  ONE additive operation, ZERO destructive ops:

NEW ``s09_correction`` — durable archive of one targeted demo-review
correction (S09-T05A): opaque ``id`` PK, workspace/project/video FK
RESTRICT + optional occurrence_segment FK RESTRICT, ``correction_kind``
CHECK derived from the canonical S09_CORRECTION_KINDS enum {mask,
z_order, contact, mesh_parts, route_override} (ORM single authority),
``status`` CHECK in ('pending','applied','cancelled'), request/impact/
result JSON evidence, workspace-scoped idempotency UNIQUE WHERE NOT NULL,
content-derived natural key UNIQUE WHERE NOT NULL, timestamps + revision
CAS.

Fail-closed downgrade: refuses BEFORE any DDL/data mutation if ANY row
exists in the new table; otherwise drops exactly what this revision
created.  PRAGMA integrity_check / foreign_key_check run on every
mutation decision path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "b3c4d5e6f7a9"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = ("s09_correction",)


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


def _assert_no_rows(conn: Connection, tables: tuple[str, ...], phase: str) -> None:
    for table in tables:
        count = int(
            conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        )
        if count > 0:
            raise RuntimeError(
                f"refusing to downgrade ({phase}): {count} row(s) exist in "
                f"{table!r}; the S09-T05A correction archive cannot be "
                "dropped without silently losing that data "
                "(fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()
    op.create_table(
        "s09_correction",
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
            "video_item_id",
            sa.String(36),
            sa.ForeignKey("video_item.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "occurrence_segment_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        # Kind literal DERIVED from app.persistence.models.S09_CORRECTION_KINDS
        # at authoring time (single authority); frozen here for migration
        # determinism.
        sa.Column("correction_kind", sa.String(24), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("impact_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column(
            "applied_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "cancelled_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("natural_key", sa.String(255), nullable=True),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
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
            "correction_kind IN ('mask','z_order','contact','mesh_parts',"
            "'route_override')",
            name="ck_s09_correction_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','applied','cancelled')",
            name="ck_s09_correction_status",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_s09_correction_idem_key_len",
        ),
        sa.CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_s09_correction_natural_key_len",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_s09_correction_revision_positive"
        ),
    )
    op.create_index(
        "uq_s09_correction_natural",
        "s09_correction",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
    )
    op.create_index(
        "uq_s09_correction_workspace_idempotency",
        "s09_correction",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_s09_correction_video_status", "s09_correction", ["video_item_id", "status"]
    )
    op.create_index(
        "ix_s09_correction_segment", "s09_correction", ["occurrence_segment_id"]
    )
    _assert_db_integrity(conn, "upgrade s09_correction")


def downgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: any archived correction must block the downgrade —
    # dropping the table would silently lose demo-review audit history.
    _assert_no_rows(conn, _NEW_TABLES, "pre-DDL check")

    op.drop_index("ix_s09_correction_segment", table_name="s09_correction")
    op.drop_index("ix_s09_correction_video_status", table_name="s09_correction")
    op.drop_index(
        "uq_s09_correction_workspace_idempotency", table_name="s09_correction"
    )
    op.drop_index("uq_s09_correction_natural", table_name="s09_correction")
    op.drop_table("s09_correction")
    _assert_db_integrity(conn, "downgrade s09_correction")
