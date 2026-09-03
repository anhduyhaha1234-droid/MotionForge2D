"""S11-T02A: QCItem persistence — fail-closed QC freeze at DB level.

Revision ID: e11a02a2026f
Revises: a10b11c12d3e
Create Date: 2026-09-03

ONE additive operation set, ZERO destructive ops to existing tables:

NEW ``qc_item`` — durable QC issue record (lane-A QC_DOMAIN_CONTRACT §1):

- natural-key UNIQUE over (workspace_id, project_id, video_item_id,
  layer_ref_type, layer_ref_id, reason_code, evidence_window_key) — every
  component is NOT NULL so SQLite NULL semantics can never bypass
  uniqueness (C4-F1 test 6);
- ``segment_row_id`` nullable REAL FK RESTRICT to immutable
  ``occurrence_segment.id`` + ``segment_logical_id`` nullable scoped lineage
  VALUE (deliberately NOT an FK), with a pair-null CHECK (both NULL for a
  video-level issue, both set for a segment-anchored issue — partial pairs
  are rejected at DB level);
- ``layer_ref_type`` / ``layer_ref_id`` NOT NULL (video-level issues use
  layer_ref_type='video_item', layer_ref_id=video_item_id — no NULL in the
  natural key); ``evidence_window_key`` NOT NULL canonical stable key/hash
  materialized as its own column (the uniqueness mechanism, never only
  inside evidence_json); ``evidence_json`` NOT NULL schema-versioned +
  content-derived payload (deliberately NOT the uniqueness mechanism);
  detector / detector_revision / confidence / confidence_source /
  checkpoint_ref NOT NULL; TimestampMixin (created_at/updated_at/revision);
- every enum CHECK literal below is the FROZEN byte twin of the ORM CHECK
  DERIVED from the single Python tuple (QC_ITEM_STATUSES /
  QC_ITEM_SEVERITIES / QC_ITEM_CATEGORIES / QC_REASON_CODES /
  OCCURRENCE_CONFIDENCE_SOURCES in app/persistence/models.py) so
  migration/ORM parity can never drift;
- lane-A §1.3 rule 2: severity='blocker' AND status='dismissed' is rejected
  by a real SQLite CHECK (fail-closed at DB level, not only in repository).

Fail-closed downgrade: refuses BEFORE any DDL/data mutation if ANY row
exists in ``qc_item``; otherwise drops exactly what this revision created.
PRAGMA integrity_check / foreign_key_check run on every mutation decision
path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "e11a02a2026f"
down_revision: str | None = "a10b11c12d3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = ("qc_item",)

# FROZEN literals — byte twins of the ORM CHECKs derived from the single
# Python tuples (CONTACT_KIND_CHECK_SQL pattern) in app/persistence/models.py.
_STATUS_CHECK = "status IN ('open','acknowledged','resolved','dismissed')"
_SEVERITY_CHECK = "severity IN ('blocker','warning','info')"
_CATEGORY_CHECK = (
    "category IN ('trajectory_drift','cut_drift','contact_break','z_order',"
    "'clipping','identity','flicker','audio_timecode')"
)
_REASON_CODE_CHECK = (
    "reason_code IN ('trajectory_drift','cut_drift','contact_break','z_order',"
    "'clipping','identity','flicker','audio_timecode')"
)
_CONFIDENCE_SOURCE_CHECK = (
    "confidence_source IN ('model','detector','user','manual','derived')"
)
_SEGMENT_PAIR_NULL_CHECK = (
    "(segment_row_id IS NULL AND segment_logical_id IS NULL) OR "
    "(segment_row_id IS NOT NULL AND segment_logical_id IS NOT NULL)"
)
_BLOCKER_DISMISSED_CHECK = "NOT (severity = 'blocker' AND status = 'dismissed')"


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
                f"{table!r}; QCItem data cannot be dropped without silently "
                "losing it (fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()

    # ── qc_item ────────────────────────────────────────────────────────────
    op.create_table(
        "qc_item",
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
            "segment_row_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("segment_logical_id", sa.String(64), nullable=True),
        sa.Column("layer_ref_type", sa.String(32), nullable=False),
        sa.Column("layer_ref_id", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(48), nullable=False),
        sa.Column("evidence_window_key", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'open'")
        ),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("detector", sa.String(64), nullable=False),
        sa.Column("detector_revision", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "confidence_source",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'model'"),
        ),
        sa.Column("checkpoint_ref", sa.String(64), nullable=False),
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
            "revision", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_qc_item_status"),
        sa.CheckConstraint(_SEVERITY_CHECK, name="ck_qc_item_severity"),
        sa.CheckConstraint(_CATEGORY_CHECK, name="ck_qc_item_category"),
        sa.CheckConstraint(_REASON_CODE_CHECK, name="ck_qc_item_reason_code"),
        sa.CheckConstraint(
            _CONFIDENCE_SOURCE_CHECK, name="ck_qc_item_confidence_source"
        ),
        sa.CheckConstraint(_SEGMENT_PAIR_NULL_CHECK, name="ck_qc_item_segment_pair_null"),
        sa.CheckConstraint(
            _BLOCKER_DISMISSED_CHECK, name="ck_qc_item_blocker_not_dismissed"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_qc_item_confidence_range",
        ),
        sa.CheckConstraint("revision > 0", name="ck_qc_item_revision_positive"),
        sa.CheckConstraint(
            "length(layer_ref_type) BETWEEN 1 AND 32",
            name="ck_qc_item_layer_ref_type_len",
        ),
        sa.CheckConstraint(
            "length(layer_ref_id) BETWEEN 1 AND 64",
            name="ck_qc_item_layer_ref_id_len",
        ),
        sa.CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 48",
            name="ck_qc_item_reason_code_len",
        ),
        sa.CheckConstraint(
            "length(evidence_window_key) BETWEEN 1 AND 64",
            name="ck_qc_item_evidence_window_key_len",
        ),
        sa.CheckConstraint(
            "length(evidence_json) >= 1", name="ck_qc_item_evidence_json_nonempty"
        ),
        sa.CheckConstraint(
            "length(detector) BETWEEN 1 AND 64", name="ck_qc_item_detector_len"
        ),
        sa.CheckConstraint(
            "length(detector_revision) BETWEEN 1 AND 64",
            name="ck_qc_item_detector_revision_len",
        ),
        sa.CheckConstraint(
            "length(checkpoint_ref) BETWEEN 1 AND 64",
            name="ck_qc_item_checkpoint_ref_len",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "video_item_id",
            "layer_ref_type",
            "layer_ref_id",
            "reason_code",
            "evidence_window_key",
            name="uq_qc_item_natural_key",
        ),
    )
    op.create_index("ix_qc_item_workspace", "qc_item", ["workspace_id"])
    op.create_index("ix_qc_item_project", "qc_item", ["project_id"])
    op.create_index("ix_qc_item_video", "qc_item", ["video_item_id"])
    op.create_index("ix_qc_item_segment", "qc_item", ["segment_row_id"])
    op.create_index("ix_qc_item_status", "qc_item", ["status"])

    _assert_db_integrity(conn, "upgrade qc_item")


def downgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: any QCItem row must block the downgrade.
    _assert_no_rows(conn, _NEW_TABLES, "pre-DDL check")

    op.drop_index("ix_qc_item_status", table_name="qc_item")
    op.drop_index("ix_qc_item_segment", table_name="qc_item")
    op.drop_index("ix_qc_item_video", table_name="qc_item")
    op.drop_index("ix_qc_item_project", table_name="qc_item")
    op.drop_index("ix_qc_item_workspace", table_name="qc_item")
    op.drop_table("qc_item")

    _assert_db_integrity(conn, "downgrade qc_item")