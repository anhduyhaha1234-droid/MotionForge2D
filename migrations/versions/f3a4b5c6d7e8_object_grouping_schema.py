"""Add cross-scene grouping and curation surfaces (S08-T03).

Revision ID: f3a4b5c6d7e8
Revises: f2a3b4c5d6e7

Two NEW durable tables (SQLite CREATE TABLE so every CHECK/FK/index is
real reflection-visible metadata):

- ``object_grouping_suggestion`` — a REVIEWABLE cross-scene grouping
  suggestion over a set of ObjectRoles (always created ``pending``; never
  auto-confirmed).  Carries confidence, reasons and provenance
  (algorithm/version).  ``natural_key`` (workspace + content fingerprint)
  and ``idempotency_key`` partial-unique indexes make generation idempotent
  and race-safe; status lifecycle ``pending -> dismissed|applied|superseded``
  keeps every superseded suggestion traceable.

- ``object_role_operation`` — the AUDIT history of explicit durable
  merge/split/confirm mutations.  One row per completed operation with the
  target role, source role ids, created role ids, the exact
  transferred-occurrence map (merge/split) and the revision the target
  reached.  ``natural_key`` partial-unique makes duplicate/concurrent
  requests replay the SAME operation (never a second mutation); two
  ``idempotency_key`` partial-unique indexes are per-workspace backstops.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "f2a3b4c5d6e7"
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
        "object_grouping_suggestion",
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
        sa.Column("source_generation", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("role_ids_json", sa.Text(), nullable=False),
        sa.Column(
            "target_role_id",
            sa.String(36),
            sa.ForeignKey("object_role.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'video'"),
        ),
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
            "status IN ('pending','dismissed','applied','superseded')",
            name="ck_object_grouping_suggestion_status",
        ),
        sa.CheckConstraint(
            "scope IN ('video','project')",
            name="ck_object_grouping_suggestion_scope",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_object_grouping_suggestion_confidence_range",
        ),
        sa.CheckConstraint(
            "length(source_generation) BETWEEN 1 AND 64",
            name="ck_object_grouping_suggestion_generation_len",
        ),
        sa.CheckConstraint(
            "length(algorithm) BETWEEN 1 AND 64",
            name="ck_object_grouping_suggestion_algorithm_len",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) BETWEEN 1 AND 64",
            name="ck_object_grouping_suggestion_algorithm_version_len",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_grouping_suggestion_idem_key_len",
        ),
        sa.CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_object_grouping_suggestion_natural_key_len",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_object_grouping_suggestion_revision_positive"
        ),
        sa.Index(
            "uq_object_grouping_suggestion_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa.text("natural_key IS NOT NULL"),
        ),
        sa.Index(
            "uq_object_grouping_suggestion_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        ),
        sa.Index(
            "ix_object_grouping_suggestion_video_status",
            "video_item_id",
            "status",
        ),
    )
    op.create_table(
        "object_role_operation",
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
        sa.Column("operation_type", sa.String(16), nullable=False),
        sa.Column(
            "target_role_id",
            sa.String(36),
            sa.ForeignKey("object_role.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_role_ids_json", sa.Text(), nullable=False),
        sa.Column("created_role_ids_json", sa.Text(), nullable=False),
        sa.Column("transferred_occurrence_ids_json", sa.Text(), nullable=False),
        sa.Column(
            "suggestion_id",
            sa.String(36),
            sa.ForeignKey("object_grouping_suggestion.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("natural_key", sa.String(255), nullable=True),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "operation_type IN ('merge','split','confirm')",
            name="ck_object_role_operation_type",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_role_operation_idem_key_len",
        ),
        sa.CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_object_role_operation_natural_key_len",
        ),
        sa.CheckConstraint(
            "revision_after > 0", name="ck_object_role_operation_revision_after_positive"
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_object_role_operation_revision_positive"
        ),
        sa.Index(
            "uq_object_role_operation_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa.text("natural_key IS NOT NULL"),
        ),
        sa.Index(
            "uq_object_role_operation_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        ),
        sa.Index(
            "ix_object_role_operation_video_type",
            "video_item_id",
            "operation_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("object_role_operation")
    op.drop_table("object_grouping_suggestion")
