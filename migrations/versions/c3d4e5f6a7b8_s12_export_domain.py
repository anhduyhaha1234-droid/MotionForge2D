"""S12-T03A: durable export domain — run/chunk/lease + checkpoint contract.

Revision ID: c3d4e5f6a7b8
Revises: f9a0b1c2d3e4
Create Date: 2026-09-07

ONE additive operation set, ZERO destructive ops:

NEW ``s12_export_run`` — durable export run aggregate:
  opaque ``id`` PK, workspace/project/video FK RESTRICT, frozen
  ``checkpoint_id`` FK RESTRICT to apply_checkpoint.id + frozen
  ``checkpoint_hash`` (64 hex) + ``checkpoint_revision`` (>= 1),
  frozen ``manifest_id`` FK RESTRICT to structural_lock_manifest.id +
  frozen ``manifest_hash`` (64 hex) + ``manifest_generation``,
  frozen T01 profile snapshot (``profile_id``/``profile_dims``/
  ``profile_codec``), ``plan_id``/``plan_hash`` (64 hex) render-plan
  identity, ``status`` CHECK derived from S12_EXPORT_RUN_STATUSES,
  ``frame_count``, ``chunk_config_json`` canonical, ``attempt`` /
  ``revision`` CAS, ``natural_key`` UNIQUE(workspace) WHERE NOT NULL
  (content-derived lineage identity), ``idempotency_key``
  UNIQUE(workspace) WHERE NOT NULL, timestamps, CHECKs fail-closed.

NEW ``s12_export_chunk`` — deterministic export chunk boundary:
  opaque ``id`` PK, run FK RESTRICT to s12_export_run.id, ``chunk_index``
  / ``order_index``, ``core_start_frame`` / ``core_end_frame`` inclusive,
  ``overlap_before`` / ``overlap_after`` (context-only), ``content_hash``
  (64 hex bound to plan+position+attempt+checkpoint pin), ``attempt`` /
  ``state`` CHECK from S12_EXPORT_CHUNK_STATES, ``artifact_id`` nullable
  FK RESTRICT, ``verified`` bool, ``natural_key`` / ``idempotency_key``
  UNIQUE(workspace) WHERE NOT NULL, ``revision`` CAS, timestamps, CHECKs.
  UNIQUE(run_id, chunk_index, attempt) scopes attempts.

NEW ``s12_export_lease`` — single-winner claim lease per run:
  ``run_id`` PK (= one row per run) FK RESTRICT to s12_export_run.id,
  ``worker_id``, ``lease_version`` (>= 1, monotonic on re-claim),
  ``fence_token`` (nonempty — the enforcement point), ``acquired_at`` /
  ``expires_at`` / ``heartbeat_at``, ``ttl_seconds`` (>= 1), ``revision``
  CAS.  The first INSERT wins; re-claim is a guarded CAS on
  lease_version.  The row is retired, never deleted.

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

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = (
    "s12_export_run",
    "s12_export_chunk",
    "s12_export_lease",
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
                f"{table!r}; the S12 export domain cannot be "
                "dropped without silently losing that data "
                "(fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()

    # ── s12_export_run ───────────────────────────────────────────────────
    op.create_table(
        "s12_export_run",
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
            "checkpoint_id",
            sa.String(36),
            sa.ForeignKey("apply_checkpoint.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("checkpoint_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_revision", sa.Integer(), nullable=False),
        sa.Column(
            "manifest_id",
            sa.String(36),
            sa.ForeignKey("structural_lock_manifest.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("manifest_generation", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("profile_dims", sa.String(32), nullable=False),
        sa.Column("profile_codec", sa.String(16), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("frame_count", sa.Integer(), nullable=False),
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
            name="ck_s12_run_status",
        ),
        sa.CheckConstraint(
            "length(checkpoint_hash) = 64", name="ck_s12_run_checkpoint_hash_len"
        ),
        sa.CheckConstraint(
            "checkpoint_revision >= 1", name="ck_s12_run_checkpoint_revision_positive"
        ),
        sa.CheckConstraint(
            "length(manifest_hash) = 64", name="ck_s12_run_manifest_hash_len"
        ),
        sa.CheckConstraint(
            "length(manifest_generation) BETWEEN 1 AND 64",
            name="ck_s12_run_manifest_generation_len",
        ),
        sa.CheckConstraint(
            "length(profile_id) BETWEEN 1 AND 64", name="ck_s12_run_profile_id_len"
        ),
        sa.CheckConstraint("length(plan_id) = 64", name="ck_s12_run_plan_id_len"),
        sa.CheckConstraint("length(plan_hash) = 64", name="ck_s12_run_plan_hash_len"),
        sa.CheckConstraint("frame_count >= 1", name="ck_s12_run_frame_count_positive"),
        sa.CheckConstraint("attempt >= 1", name="ck_s12_run_attempt_positive"),
        sa.CheckConstraint("revision > 0", name="ck_s12_run_revision_positive"),
        sa.CheckConstraint(
            "length(natural_key) <= 255", name="ck_s12_run_natural_key_len"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s12_run_idem_key_len"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "video_item_id",
            "profile_id",
            "plan_hash",
            "checkpoint_hash",
            name="uq_s12_run_identity",
        ),
    )
    op.create_index(
        "uq_s12_run_natural",
        "s12_export_run",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
    )
    op.create_index(
        "uq_s12_run_workspace_idempotency",
        "s12_export_run",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_s12_run_workspace", "s12_export_run", ["workspace_id"])
    op.create_index("ix_s12_run_project", "s12_export_run", ["project_id"])
    op.create_index("ix_s12_run_video", "s12_export_run", ["video_item_id"])
    op.create_index("ix_s12_run_checkpoint", "s12_export_run", ["checkpoint_id"])
    op.create_index("ix_s12_run_manifest", "s12_export_run", ["manifest_id"])
    op.create_index("ix_s12_run_status", "s12_export_run", ["status"])

    # ── s12_export_chunk ─────────────────────────────────────────────────
    op.create_table(
        "s12_export_chunk",
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
            sa.ForeignKey("s12_export_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("chunk_index >= 0", name="ck_s12_chunk_index_nonneg"),
        sa.CheckConstraint("order_index >= 0", name="ck_s12_chunk_order_nonneg"),
        sa.CheckConstraint(
            "core_start_frame >= 0", name="ck_s12_chunk_core_start_nonneg"
        ),
        sa.CheckConstraint(
            "core_end_frame >= core_start_frame",
            name="ck_s12_chunk_core_end_ge_start",
        ),
        sa.CheckConstraint("overlap_before >= 0", name="ck_s12_chunk_overlap_before_nonneg"),
        sa.CheckConstraint("overlap_after >= 0", name="ck_s12_chunk_overlap_after_nonneg"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_s12_chunk_content_hash_len"),
        sa.CheckConstraint(
            "state IN ('pending','running','completed','failed','skipped')",
            name="ck_s12_chunk_state",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_s12_chunk_attempt_positive"),
        sa.CheckConstraint("verified IN (0, 1)", name="ck_s12_chunk_verified_bool"),
        sa.CheckConstraint("revision > 0", name="ck_s12_chunk_revision_positive"),
        sa.CheckConstraint(
            "length(natural_key) <= 255", name="ck_s12_chunk_natural_key_len"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s12_chunk_idem_key_len"
        ),
        sa.UniqueConstraint(
            "run_id", "chunk_index", "attempt", name="uq_s12_chunk_run_index_attempt"
        ),
    )
    op.create_index(
        "uq_s12_chunk_natural",
        "s12_export_chunk",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
    )
    op.create_index(
        "uq_s12_chunk_workspace_idempotency",
        "s12_export_chunk",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_s12_chunk_run", "s12_export_chunk", ["run_id"])
    op.create_index("ix_s12_chunk_state", "s12_export_chunk", ["state"])
    op.create_index("ix_s12_chunk_run_state", "s12_export_chunk", ["run_id", "state"])

    # ── s12_export_lease ─────────────────────────────────────────────────
    op.create_table(
        "s12_export_lease",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("s12_export_run.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("lease_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("fence_token", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("lease_version >= 1", name="ck_s12_lease_version_positive"),
        sa.CheckConstraint(
            "length(fence_token) > 0", name="ck_s12_lease_token_nonempty"
        ),
        sa.CheckConstraint("ttl_seconds >= 1", name="ck_s12_lease_ttl_positive"),
        sa.CheckConstraint("revision > 0", name="ck_s12_lease_revision_positive"),
    )
    op.create_index("ix_s12_lease_worker", "s12_export_lease", ["worker_id"])

    _assert_db_integrity(conn, "upgrade s12 export domain")


def downgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: any export row must block the downgrade.
    _assert_no_rows(conn, _NEW_TABLES, "pre-DDL check")

    op.drop_index("ix_s12_lease_worker", table_name="s12_export_lease")
    op.drop_table("s12_export_lease")

    op.drop_index("ix_s12_chunk_run_state", table_name="s12_export_chunk")
    op.drop_index("ix_s12_chunk_state", table_name="s12_export_chunk")
    op.drop_index("ix_s12_chunk_run", table_name="s12_export_chunk")
    op.drop_index("uq_s12_chunk_workspace_idempotency", table_name="s12_export_chunk")
    op.drop_index("uq_s12_chunk_natural", table_name="s12_export_chunk")
    op.drop_table("s12_export_chunk")

    op.drop_index("ix_s12_run_status", table_name="s12_export_run")
    op.drop_index("ix_s12_run_manifest", table_name="s12_export_run")
    op.drop_index("ix_s12_run_checkpoint", table_name="s12_export_run")
    op.drop_index("ix_s12_run_video", table_name="s12_export_run")
    op.drop_index("ix_s12_run_project", table_name="s12_export_run")
    op.drop_index("ix_s12_run_workspace", table_name="s12_export_run")
    op.drop_index("uq_s12_run_workspace_idempotency", table_name="s12_export_run")
    op.drop_index("uq_s12_run_natural", table_name="s12_export_run")
    op.drop_table("s12_export_run")

    _assert_db_integrity(conn, "downgrade s12 export domain")
