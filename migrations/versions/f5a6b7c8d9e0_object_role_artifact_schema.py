"""Add durable ObjectRole->Artifact association (S08-T02 correction round).

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9

One NEW table ``object_role_artifact`` (SQLite CREATE TABLE so every
CHECK/FK/index is real reflection-visible metadata):

- durable link between a stable ``ObjectRole`` id and a published candidate
  artifact id, keyed by role id, artifact id, purpose, source generation and
  source job (correction finding B6).  Display names are never joins: the
  association is id-based, so renames and duplicate display names cannot
  re-map gallery/grouping references.
- ``source_job_id`` RESTRICT -> job.id keeps the producing extraction Job
  authoritative; ``role_id`` CASCADE keeps role deletion consistent with
  ``object_occurrence``; ``artifact_id`` RESTRICT keeps published artifact
  bytes authoritative (Trash eligibility stays owner-link based).
- the unique constraint ``(role_id, artifact_id, purpose,
  source_generation, source_job_id)`` makes publication replay idempotent
  (upsert semantics, no duplicate rows on restart/retry).

Existing tables/rows are untouched (pure additive migration).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_role_artifact",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.String(36),
            sa.ForeignKey("object_role.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(36),
            sa.ForeignKey("artifact.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("source_generation", sa.String(64), nullable=False),
        sa.Column(
            "source_job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="RESTRICT"),
            nullable=False,
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
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint(
            "purpose IN ('thumbnail','mask')", name="ck_object_role_artifact_purpose"
        ),
        sa.CheckConstraint(
            "length(source_generation) > 0",
            name="ck_object_role_artifact_generation_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_generation) <= 64",
            name="ck_object_role_artifact_generation_len",
        ),
        sa.CheckConstraint("revision > 0", name="ck_object_role_artifact_revision_positive"),
        sa.UniqueConstraint(
            "role_id",
            "artifact_id",
            "purpose",
            "source_generation",
            "source_job_id",
            name="uq_object_role_artifact_natural_key",
        ),
        sa.Index("ix_object_role_artifact_role", "role_id"),
        sa.Index("ix_object_role_artifact_artifact", "artifact_id"),
        sa.Index("ix_object_role_artifact_job", "source_job_id"),
    )


def downgrade() -> None:
    op.drop_table("object_role_artifact")
