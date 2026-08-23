"""Add extraction surfaces for durable object candidate discovery (S08-T02).

Revision ID: f2a3b4c5d6e7
Revises: e7f8a9b0c1d2
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Managed-artifact contract (S08-T02): published Image artifacts record
    # their pixel dimensions next to MIME/size/sha256. Nullable so existing
    # non-image artifacts keep working. SQLite does not support ALTER ADD
    # CONSTRAINT through Alembic (batch mode would recreate the table and
    # lose reflection-invisible partial indexes), so the column-level CHECKs
    # are part of the raw ADD COLUMN DDL — SQLite 3.25+ supports inline
    # column constraints in ALTER TABLE ADD COLUMN.
    op.execute(
        "ALTER TABLE artifact ADD COLUMN width INTEGER "
        "CHECK (width IS NULL OR width >= 0)"
    )
    op.execute(
        "ALTER TABLE artifact ADD COLUMN height INTEGER "
        "CHECK (height IS NULL OR height >= 0)"
    )
    # A worker-created ObjectRole records which durable DISCOVER_OBJECTS Job
    # produced it (audit + restart/retry lineage; S08-T02). Nullable so
    # T01-era/user-created roles are unaffected; the raw ADD COLUMN keeps a
    # real FK constraint (nullable REFERENCES clause, default NULL, is legal
    # in SQLite ADD COLUMN with foreign_keys enabled).
    op.execute(
        "ALTER TABLE object_role ADD COLUMN source_job_id VARCHAR(36) "
        "REFERENCES job(id) ON DELETE RESTRICT"
    )


def downgrade() -> None:
    op.drop_column("object_role", "source_job_id")
    op.drop_column("artifact", "height")
    op.drop_column("artifact", "width")
