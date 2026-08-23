"""Add the durable targeted-correction surface (S08-T05).

Revision ID: f4a5b6c7d8e9
Revises: f3a4b5c6d7e8

One NEW durable table (SQLite CREATE TABLE so every CHECK/FK/index is real
reflection-visible metadata):

- ``object_correction`` — the durable archive of ONE targeted object
  correction (reassign / candidate_edit / merge / split).  A correction is
  created ``pending`` with its computed impacted scope (impact_json), then
  explicitly confirmed (CAS) — the targeted mutation + supersession of the
  affected derived state + the RECOMPUTE_OBJECTS job are committed in ONE
  transaction, and the old affected mapping is archived in ``result_json``.
  ``natural_key`` (workspace + content fingerprint) makes duplicate/
  concurrent requests replay the SAME correction; the ``recompute_job_id``
  link gives the durable recompute work its retry/cancel/restart contract.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "object_correction",
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
        sa.Column("correction_type", sa.String(24), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("impact_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column(
            "recompute_job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("natural_key", sa.String(255), nullable=True),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "correction_type IN ('reassign','candidate_edit','merge','split')",
            name="ck_object_correction_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','applied','cancelled')",
            name="ck_object_correction_status",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_correction_idem_key_len",
        ),
        sa.CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_object_correction_natural_key_len",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_object_correction_revision_positive"
        ),
        sa.Index(
            "uq_object_correction_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa.text("natural_key IS NOT NULL"),
        ),
        sa.Index(
            "uq_object_correction_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        ),
        sa.Index(
            "ix_object_correction_video_status",
            "video_item_id",
            "status",
        ),
        sa.Index("ix_object_correction_recompute_job", "recompute_job_id"),
    )


def downgrade() -> None:
    op.drop_table("object_correction")
