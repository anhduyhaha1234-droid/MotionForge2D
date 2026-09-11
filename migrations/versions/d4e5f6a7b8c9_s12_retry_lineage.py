"""S12-LC3-RETRY: additive immutable run lineage and durable Job binding.

This revision changes only the S12 export run identity block.  The old
six-field UNIQUE constraint incorrectly made a retry collide with its
predecessor.  Initial-submit dedup remains the workspace natural/idempotency
key, while retries use a stable lineage/attempt identity and an exclusive
predecessor pointer.

The upgrade is data-preserving: it backfills lineage from ``natural_key`` (or
the immutable run id for legacy rows) and binds only an unambiguous existing
S12 Job.  Ambiguous job bindings fail before the new constraints are created.
Downgrade is fail-closed while S12 rows exist.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_db_integrity(conn: Connection, phase: str) -> None:
    integrity = conn.execute(sa.text("PRAGMA integrity_check")).fetchall()
    if not integrity or str(integrity[0][0]).strip().lower() != "ok":
        raise RuntimeError(f"integrity_check after {phase} failed: {integrity!r}")
    fk_violations = conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if fk_violations:
        raise RuntimeError(
            f"foreign_key_check after {phase} found {len(fk_violations)} violation(s): "
            f"{fk_violations[:5]!r}"
        )


def _assert_no_ambiguous_jobs(conn: Connection) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT r.id, COUNT(j.id) AS job_count "
            "FROM s12_export_run r "
            "JOIN job j ON j.workspace_id = r.workspace_id "
            "AND j.idempotency_key = 's12_export_job:' || r.id "
            "GROUP BY r.id HAVING COUNT(j.id) > 1"
        )
    ).fetchall()
    if rows:
        raise RuntimeError(
            "refusing S12 retry-lineage upgrade: ambiguous durable Job binding(s) "
            f"{rows[:10]!r}"
        )


def _assert_no_s12_rows(conn: Connection, phase: str) -> None:
    for table in ("s12_export_run", "s12_export_chunk", "s12_export_lease"):
        count = int(conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
        if count:
            raise RuntimeError(
                f"refusing downgrade ({phase}): {count} row(s) exist in {table!r}"
            )


def upgrade() -> None:
    conn = op.get_bind()
    _assert_db_integrity(conn, "preflight")
    _assert_no_ambiguous_jobs(conn)

    # SQLite cannot drop/recreate a referenced parent while foreign_keys is
    # enabled.  This is a narrowly scoped DDL rebuild; enforcement is restored
    # in the finally block and the postflight PRAGMAs prove the data remained
    # valid.  No application/runtime write occurs with FK checks disabled.
    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("s12_export_run", recreate="always") as batch:
            batch.drop_constraint("uq_s12_run_identity", type_="unique")
            batch.add_column(sa.Column("lineage_id", sa.String(255), nullable=True))
            batch.add_column(
                sa.Column(
                    "predecessor_run_id",
                    sa.String(36),
                    nullable=True,
                )
            )
            batch.add_column(
                sa.Column(
                    "job_id",
                    sa.String(36),
                    nullable=True,
                )
            )
            batch.create_foreign_key(
                "fk_s12_export_run_predecessor_run_id_s12_export_run",
                "s12_export_run",
                ["predecessor_run_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_s12_export_run_job_id_job",
                "job",
                ["job_id"],
                ["id"],
                ondelete="RESTRICT",
            )
    finally:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    # Existing runs remain attempt 1.  ``id`` is a deterministic, immutable
    # fallback for old rows that deliberately omitted natural_key.
    conn.execute(
        sa.text(
            "UPDATE s12_export_run SET lineage_id = COALESCE(natural_key, id) "
            "WHERE lineage_id IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE s12_export_run SET job_id = ("
            "SELECT j.id FROM job j WHERE j.workspace_id = s12_export_run.workspace_id "
            "AND j.idempotency_key = 's12_export_job:' || s12_export_run.id"
            ") WHERE job_id IS NULL AND EXISTS ("
            "SELECT 1 FROM job j WHERE j.workspace_id = s12_export_run.workspace_id "
            "AND j.idempotency_key = 's12_export_job:' || s12_export_run.id"
            ")"
        )
    )

    # The natural key remains an initial-submit dedup key only.  A retry has
    # natural_key NULL and is identified by lineage_id + attempt instead.
    op.drop_index("uq_s12_run_natural", table_name="s12_export_run")
    op.create_index(
        "uq_s12_run_natural",
        "s12_export_run",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL AND attempt = 1"),
        postgresql_where=sa.text("natural_key IS NOT NULL AND attempt = 1"),
    )
    op.create_index(
        "uq_s12_run_lineage_attempt",
        "s12_export_run",
        ["workspace_id", "lineage_id", "attempt"],
        unique=True,
        sqlite_where=sa.text("lineage_id IS NOT NULL"),
        postgresql_where=sa.text("lineage_id IS NOT NULL"),
    )
    op.create_index(
        "uq_s12_run_predecessor",
        "s12_export_run",
        ["predecessor_run_id"],
        unique=True,
        sqlite_where=sa.text("predecessor_run_id IS NOT NULL"),
        postgresql_where=sa.text("predecessor_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_s12_run_job",
        "s12_export_run",
        ["job_id"],
        unique=True,
        sqlite_where=sa.text("job_id IS NOT NULL"),
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )
    op.create_index("ix_s12_run_lineage", "s12_export_run", ["lineage_id"])
    op.create_index("ix_s12_run_predecessor", "s12_export_run", ["predecessor_run_id"])
    op.create_index("ix_s12_run_job", "s12_export_run", ["job_id"])
    _assert_db_integrity(conn, "upgrade")


def downgrade() -> None:
    conn = op.get_bind()
    _assert_no_s12_rows(conn, "pre-DDL")
    _assert_db_integrity(conn, "downgrade preflight")

    for name in (
        "ix_s12_run_job",
        "ix_s12_run_predecessor",
        "ix_s12_run_lineage",
        "uq_s12_run_job",
        "uq_s12_run_predecessor",
        "uq_s12_run_lineage_attempt",
        "uq_s12_run_natural",
    ):
        op.drop_index(name, table_name="s12_export_run")
    op.create_index(
        "uq_s12_run_natural",
        "s12_export_run",
        ["workspace_id", "natural_key"],
        unique=True,
        sqlite_where=sa.text("natural_key IS NOT NULL"),
        postgresql_where=sa.text("natural_key IS NOT NULL"),
    )
    with op.batch_alter_table("s12_export_run", recreate="always") as batch:
        batch.drop_constraint("fk_s12_export_run_job_id_job", type_="foreignkey")
        batch.drop_constraint(
            "fk_s12_export_run_predecessor_run_id_s12_export_run",
            type_="foreignkey",
        )
        batch.drop_column("job_id")
        batch.drop_column("predecessor_run_id")
        batch.drop_column("lineage_id")
        batch.create_unique_constraint(
            "uq_s12_run_identity",
            [
                "workspace_id",
                "project_id",
                "video_item_id",
                "profile_id",
                "plan_hash",
                "checkpoint_hash",
            ],
        )
    _assert_db_integrity(conn, "downgrade")
