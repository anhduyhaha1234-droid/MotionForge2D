"""Add durable object intelligence schema (S08-T01).

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_role",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("video_item_id", sa.String(36), nullable=False),
        sa.Column("source_generation", sa.String(64), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("kind", sa.String(16), server_default="character", nullable=False),
        sa.Column("status", sa.String(16), server_default="suggested", nullable=False),
        sa.Column("supersedes_role_id", sa.String(36), nullable=True),
        sa.Column("legacy_object_id", sa.String(255), nullable=True),
        sa.Column("legacy_scene_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('suggested','confirmed','superseded')", name="ck_object_role_status"
        ),
        sa.CheckConstraint("kind IN ('character','prop','other')", name="ck_object_role_kind"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 240", name="ck_object_role_name_len"),
        sa.CheckConstraint(
            "length(source_generation) > 0", name="ck_object_role_source_generation_nonempty"
        ),
        sa.CheckConstraint(
            "length(source_generation) <= 64", name="ck_object_role_source_generation_len"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_object_role_idempotency_key_len"
        ),
        sa.CheckConstraint("revision > 0", name="ck_object_role_revision_positive"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_item_id"], ["video_item.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_role_id"], ["object_role.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_object_role_workspace_idempotency",
        "object_role",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_object_role_video_status", "object_role", ["video_item_id", "status"])
    op.create_index("ix_object_role_legacy_object", "object_role", ["legacy_object_id"])
    op.create_index("ix_object_role_supersedes", "object_role", ["supersedes_role_id"])

    op.create_table(
        "object_occurrence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("video_item_id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.Column("scene_id", sa.String(36), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
        sa.Column("bbox_x", sa.Integer(), nullable=False),
        sa.Column("bbox_y", sa.Integer(), nullable=False),
        sa.Column("bbox_w", sa.Integer(), nullable=False),
        sa.Column("bbox_h", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_source", sa.String(32), server_default="model", nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=True),
        sa.Column("reasons_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("review_state", sa.String(16), server_default="unreviewed", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("frame_index >= 0", name="ck_object_occurrence_frame_index_nonneg"),
        sa.CheckConstraint("time_ms >= 0", name="ck_object_occurrence_time_ms_nonneg"),
        sa.CheckConstraint("bbox_x >= 0", name="ck_object_occurrence_bbox_x_nonneg"),
        sa.CheckConstraint("bbox_y >= 0", name="ck_object_occurrence_bbox_y_nonneg"),
        sa.CheckConstraint("bbox_w >= 0", name="ck_object_occurrence_bbox_w_nonneg"),
        sa.CheckConstraint("bbox_h >= 0", name="ck_object_occurrence_bbox_h_nonneg"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_object_occurrence_confidence_range"
        ),
        sa.CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_object_occurrence_confidence_source",
        ),
        sa.CheckConstraint(
            "review_state IN ('unreviewed','accepted','rejected','edited')",
            name="ck_object_occurrence_review_state",
        ),
        sa.CheckConstraint("length(algorithm) <= 64", name="ck_object_occurrence_algorithm_len"),
        sa.CheckConstraint(
            "length(algorithm_version) <= 64", name="ck_object_occurrence_algorithm_version_len"
        ),
        sa.CheckConstraint("revision > 0", name="ck_object_occurrence_revision_positive"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_item_id"], ["video_item.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["object_role.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_id"], ["scene.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "role_id", "scene_id", "frame_index", name="uq_object_occurrence_role_scene_frame"
        ),
    )
    op.create_index("ix_object_occurrence_role", "object_occurrence", ["role_id"])
    op.create_index("ix_object_occurrence_scene", "object_occurrence", ["scene_id"])
    op.create_index(
        "ix_object_occurrence_video_frame", "object_occurrence", ["video_item_id", "frame_index"]
    )


def downgrade() -> None:
    op.drop_table("object_occurrence")
    op.drop_table("object_role")
