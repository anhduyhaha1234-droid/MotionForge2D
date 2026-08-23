"""Add durable media supersession for corrected objects (S08-T05-C1, finding D).

RECOMPUTE_OBJECTS must REPLACE the published media links of affected stable
role ids.  Each correction recompute publishes NEW ObjectRoleArtifact rows
(new artifacts under the recompute job, same purpose, source_generation =
job generation, source_job_id = recompute job) and marks the role's previous
ACTIVE associations as superseded via ``superseded_by_id`` — a self-FK that
keeps the full lineage auditable while resolution ("the newest valid media"
per role + purpose) is simply ``superseded_by_id IS NULL``.

SQLite cannot add/alter constraints in place, so the table change goes
through Alembic's batch (copy-and-move) mode.

Revision: f6a7b8c9d0e1 (revises f5a6b7c8d9e0).
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("object_role_artifact") as batch_op:
        batch_op.add_column(sa.Column("superseded_by_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_object_role_artifact_superseded_by",
            "object_role_artifact",
            ["superseded_by_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_object_role_artifact_current",
            ["role_id", "purpose", "superseded_by_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("object_role_artifact") as batch_op:
        batch_op.drop_index("ix_object_role_artifact_current")
        batch_op.drop_constraint(
            "fk_object_role_artifact_superseded_by", type_="foreignkey"
        )
        batch_op.drop_column("superseded_by_id")
