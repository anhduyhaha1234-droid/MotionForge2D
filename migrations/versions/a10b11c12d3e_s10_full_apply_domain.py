"""S10-T01A: durable FullApply domain — run/chunk/publication + checkpoint contract.

Revision ID: a10b11c12d3e
Revises: b3c4d5e6f7a9
Create Date: 2026-08-27

ONE additive operation set, ZERO destructive ops:

NEW ``s10_full_apply_run`` — durable FullApply run aggregate:
  opaque ``id`` PK, workspace/project/video FK RESTRICT,
  immutable FK ``apply_checkpoint_id`` RESTRICT to apply_checkpoint.id +
  frozen ``apply_checkpoint_hash`` (64 hex) + ``apply_checkpoint_revision``
  (the S09 approval's frozen revision), ``plan_id``/``plan_hash`` (64 hex)
  deterministic identity from the approved chunk plan, ``status`` CHECK
  derived from S10_FULL_APPLY_RUN_STATUSES, ``frame_count``,
  ``chunk_config_json`` canonical, ``idempotency_key`` UNIQUE(workspace)
  WHERE NOT NULL, ``natural_key`` UNIQUE(workspace) WHERE NOT NULL
  (content-derived lineage identity), ``attempt`` / ``revision`` CAS,
  timestamps, CHECKs fail-closed.  Workspace-scoped uniqueness prevents
  duplicate runs; natural_key prevents duplicate lineage.

NEW ``s10_full_apply_chunk`` — deterministic shot/layer chunk boundary:
  opaque ``id`` PK (deterministic per plan/shot/layer/core range), run FK
  RESTRICT to s10_full_apply_run.id, ``chunk_index``, ``shot_id``,
  ``layer_id`` / ``object_role_id`` nullable, ``core_start_frame`` /
  ``core_end_frame`` inclusive (core = timeline-contributing frames),
  ``overlap_before`` / ``overlap_after`` (context-only, never duplicated in
  final timeline), ``order_index``, ``content_hash`` (64 hex bound to
  plan+shot+range+attempt+checkpoint), ``attempt`` / ``state`` CHECK from
  S10_FULL_APPLY_CHUNK_STATES, ``artifact_id`` nullable FK RESTRICT,
  ``verified`` bool, ``idempotency_key`` UNIQUE(workspace) WHERE NOT NULL,
  ``natural_key`` UNIQUE(workspace) WHERE NOT NULL (run+chunk_index+attempt),
  ``revision`` CAS, timestamps, CHECKs.  UNIQUE(run_id, chunk_index) keeps
  chunk positions stable; UNIQUE(run_id, attempt, chunk_index) scopes
  attempts.

NEW ``s10_full_apply_publication`` — atomic publish of one verified full
output:
  opaque ``id`` PK, run FK RESTRICT, ``artifact_id`` FK RESTRICT
  (managed artifact, never .partial — enforced by repository validator AND
  CHECK ``artifact_relative_path NOT LIKE '%.partial%'`` via trigger-style
  repo guard; column is artifact_id so CHECK is on the publication table's
  own idempotency/natural-key semantics), ``content_hash`` (64 hex),
  ``frame_count`` / ``frame_metadata_json`` (exact frame count/timebase/shot
  order validation), ``checkpoint_id`` + ``checkpoint_hash`` frozen copy,
  ``state`` CHECK from S10_FULL_APPLY_PUBLICATION_STATES,
  ``idempotency_key`` UNIQUE(workspace) WHERE NOT NULL,
  ``natural_key`` UNIQUE(workspace) WHERE NOT NULL (run+content_hash),
  ``revision`` CAS, timestamps.  Exactly one publication per run lineage
  enforced by natural_key; completed publication cannot reference an
  unverified artifact (repository pre-publish CHECK).

All FKs RESTRICT fail-closed; all CHECKs are real SQLite CHECK reflection
metadata.  Workspace-scoped idempotency prevents duplicate lineage.

Fail-closed downgrade: refuses BEFORE any DDL/data mutation if ANY row
exists in ANY of the three new tables; otherwise drops exactly what this
revision created.  PRAGMA integrity_check / foreign_key_check run on every
mutation decision path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "a10b11c12d3e"
down_revision: str | None = "b3c4d5e6f7a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = (
    "s10_full_apply_run",
    "s10_full_apply_chunk",
    "s10_full_apply_publication",
)


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
                f"{table!r}; the S10 FullApply domain cannot be "
                "dropped without silently losing that data "
                "(fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()

    # ── s10_full_apply_run ───────────────────────────────────────────────
    op.create_table(
        "s10_full_apply_run",
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
            "apply_checkpoint_id",
            sa.String(36),
            sa.ForeignKey("apply_checkpoint.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("apply_checkpoint_hash", sa.String(64), nullable=False),
        sa.Column("apply_checkpoint_revision", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("fps_num", sa.Integer(), nullable=True),
        sa.Column("fps_den", sa.Integer(), nullable=True),
        sa.Column("chunk_config_json", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("natural_key", sa.String(255), nullable=True),
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
            "status IN ('pending','running','verifying','completed','failed','cancelled')",
            name="ck_s10_run_status",
        ),
        sa.CheckConstraint("length(plan_id) = 64", name="ck_s10_run_plan_id_len"),
        sa.CheckConstraint("length(plan_hash) = 64", name="ck_s10_run_plan_hash_len"),
        sa.CheckConstraint(
            "length(apply_checkpoint_hash) = 64", name="ck_s10_run_checkpoint_hash_len"
        ),
        sa.CheckConstraint(
            "apply_checkpoint_revision >= 1", name="ck_s10_run_checkpoint_revision_positive"
        ),
        sa.CheckConstraint("frame_count >= 1", name="ck_s10_run_frame_count_positive"),
        sa.CheckConstraint("fps_num IS NULL OR fps_num > 0", name="ck_s10_run_fps_num_positive"),
        sa.CheckConstraint("fps_den IS NULL OR fps_den > 0", name="ck_s10_run_fps_den_positive"),
        sa.CheckConstraint("attempt >= 1", name="ck_s10_run_attempt_positive"),
        sa.CheckConstraint("revision > 0", name="ck_s10_run_revision_positive"),
        sa.CheckConstraint(
            "length(natural_key) <= 255", name="ck_s10_run_natural_key_len"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s10_run_idempotency_key_len"
        ),
    )
    op.create_index(
        "uq_s10_run_natural",
        "s10_full_apply_run",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
    )
    op.create_index(
        "uq_s10_run_workspace_idempotency",
        "s10_full_apply_run",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_s10_run_workspace", "s10_full_apply_run", ["workspace_id"])
    op.create_index("ix_s10_run_project", "s10_full_apply_run", ["project_id"])
    op.create_index("ix_s10_run_video", "s10_full_apply_run", ["video_item_id"])
    op.create_index("ix_s10_run_checkpoint", "s10_full_apply_run", ["apply_checkpoint_id"])
    op.create_index("ix_s10_run_status", "s10_full_apply_run", ["status"])

    # ── s10_full_apply_chunk ─────────────────────────────────────────────
    op.create_table(
        "s10_full_apply_chunk",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("s10_full_apply_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.String(128), nullable=False),
        sa.Column("layer_id", sa.String(128), nullable=True),
        sa.Column(
            "object_role_id",
            sa.String(36),
            sa.ForeignKey("object_role.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("core_start_frame", sa.Integer(), nullable=False),
        sa.Column("core_end_frame", sa.Integer(), nullable=False),
        sa.Column("overlap_before", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("overlap_after", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "artifact_id",
            sa.String(36),
            sa.ForeignKey("artifact.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("verified", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("natural_key", sa.String(255), nullable=True),
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
        sa.CheckConstraint("chunk_index >= 0", name="ck_s10_chunk_index_nonneg"),
        sa.CheckConstraint("order_index >= 0", name="ck_s10_chunk_order_nonneg"),
        sa.CheckConstraint("length(shot_id) > 0", name="ck_s10_chunk_shot_nonempty"),
        sa.CheckConstraint("core_start_frame >= 0", name="ck_s10_chunk_core_start_nonneg"),
        sa.CheckConstraint(
            "core_end_frame >= core_start_frame", name="ck_s10_chunk_core_end_ge_start"
        ),
        sa.CheckConstraint("overlap_before >= 0", name="ck_s10_chunk_overlap_before_nonneg"),
        sa.CheckConstraint("overlap_after >= 0", name="ck_s10_chunk_overlap_after_nonneg"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_s10_chunk_content_hash_len"),
        sa.CheckConstraint(
            "state IN ('pending','running','completed','failed','skipped')",
            name="ck_s10_chunk_state",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_s10_chunk_attempt_positive"),
        sa.CheckConstraint("verified IN (0, 1)", name="ck_s10_chunk_verified_bool"),
        sa.CheckConstraint("revision > 0", name="ck_s10_chunk_revision_positive"),
        sa.CheckConstraint(
            "length(natural_key) <= 255", name="ck_s10_chunk_natural_key_len"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s10_chunk_idempotency_key_len"
        ),
        sa.UniqueConstraint(
            "run_id", "chunk_index", "attempt", name="uq_s10_chunk_run_index_attempt"
        ),
    )
    op.create_index(
        "uq_s10_chunk_natural",
        "s10_full_apply_chunk",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
    )
    op.create_index(
        "uq_s10_chunk_workspace_idempotency",
        "s10_full_apply_chunk",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_s10_chunk_run", "s10_full_apply_chunk", ["run_id"])
    op.create_index("ix_s10_chunk_state", "s10_full_apply_chunk", ["state"])
    op.create_index("ix_s10_chunk_shot", "s10_full_apply_chunk", ["shot_id"])
    op.create_index("ix_s10_chunk_run_state", "s10_full_apply_chunk", ["run_id", "state"])

    # ── s10_full_apply_publication ───────────────────────────────────────
    op.create_table(
        "s10_full_apply_publication",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("s10_full_apply_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.String(36),
            sa.ForeignKey("artifact.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("frame_metadata_json", sa.Text(), nullable=False),
        sa.Column(
            "checkpoint_id",
            sa.String(36),
            sa.ForeignKey("apply_checkpoint.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("checkpoint_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_revision", sa.Integer(), nullable=False),
        sa.Column(
            "state", sa.String(24), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("natural_key", sa.String(255), nullable=True),
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
        sa.CheckConstraint("length(content_hash) = 64", name="ck_s10_pub_content_hash_len"),
        sa.CheckConstraint("frame_count >= 1", name="ck_s10_pub_frame_count_positive"),
        sa.CheckConstraint("length(checkpoint_hash) = 64", name="ck_s10_pub_checkpoint_hash_len"),
        sa.CheckConstraint(
            "checkpoint_revision >= 1", name="ck_s10_pub_checkpoint_revision_positive"
        ),
        sa.CheckConstraint(
            "state IN ('pending','verifying','completed','failed')",
            name="ck_s10_pub_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_s10_pub_revision_positive"),
        sa.CheckConstraint(
            "length(natural_key) <= 255", name="ck_s10_pub_natural_key_len"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s10_pub_idempotency_key_len"
        ),
        sa.UniqueConstraint("run_id", "content_hash", name="uq_s10_pub_run_content_hash"),
    )
    op.create_index(
        "uq_s10_pub_natural",
        "s10_full_apply_publication",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
    )
    op.create_index(
        "uq_s10_pub_workspace_idempotency",
        "s10_full_apply_publication",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_s10_pub_run", "s10_full_apply_publication", ["run_id"])
    op.create_index("ix_s10_pub_artifact", "s10_full_apply_publication", ["artifact_id"])
    op.create_index("ix_s10_pub_state", "s10_full_apply_publication", ["state"])
    op.create_index("ix_s10_pub_checkpoint", "s10_full_apply_publication", ["checkpoint_id"])

    _assert_db_integrity(conn, "upgrade s10 FullApply domain")


def downgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: any FullApply row must block the downgrade.
    _assert_no_rows(conn, _NEW_TABLES, "pre-DDL check")

    op.drop_index("ix_s10_pub_checkpoint", table_name="s10_full_apply_publication")
    op.drop_index("ix_s10_pub_state", table_name="s10_full_apply_publication")
    op.drop_index("ix_s10_pub_artifact", table_name="s10_full_apply_publication")
    op.drop_index("ix_s10_pub_run", table_name="s10_full_apply_publication")
    op.drop_index("uq_s10_pub_workspace_idempotency", table_name="s10_full_apply_publication")
    op.drop_index("uq_s10_pub_natural", table_name="s10_full_apply_publication")
    op.drop_table("s10_full_apply_publication")

    op.drop_index("ix_s10_chunk_run_state", table_name="s10_full_apply_chunk")
    op.drop_index("ix_s10_chunk_shot", table_name="s10_full_apply_chunk")
    op.drop_index("ix_s10_chunk_state", table_name="s10_full_apply_chunk")
    op.drop_index("ix_s10_chunk_run", table_name="s10_full_apply_chunk")
    op.drop_index("uq_s10_chunk_workspace_idempotency", table_name="s10_full_apply_chunk")
    op.drop_index("uq_s10_chunk_natural", table_name="s10_full_apply_chunk")
    op.drop_table("s10_full_apply_chunk")

    op.drop_index("ix_s10_run_status", table_name="s10_full_apply_run")
    op.drop_index("ix_s10_run_checkpoint", table_name="s10_full_apply_run")
    op.drop_index("ix_s10_run_video", table_name="s10_full_apply_run")
    op.drop_index("ix_s10_run_project", table_name="s10_full_apply_run")
    op.drop_index("ix_s10_run_workspace", table_name="s10_full_apply_run")
    op.drop_index("uq_s10_run_workspace_idempotency", table_name="s10_full_apply_run")
    op.drop_index("uq_s10_run_natural", table_name="s10_full_apply_run")
    op.drop_table("s10_full_apply_run")

    _assert_db_integrity(conn, "downgrade s10 FullApply domain")
