"""S11-T02A-C1: QCItem category/reason-code enum correction (Decision B + D).

Revision ID: f9a0b1c2d3e4
Revises: e11a02a2026f
Create Date: 2026-09-03

Corrects the QCItem enum contract to the BINDING codes (Manager finding
T02A-C1 [P1]):

- 8 overlay codes (Decision B, overlay §S11 L370-371): trajectory_drift,
  cut_drift, contact_break, z_order_error, silhouette_clipping,
  identity_drift, edge_halo, temporal_flicker — renames from the W1 draft
  (z_order -> z_order_error, clipping -> silhouette_clipping, identity ->
  identity_drift, flicker -> temporal_flicker), adds edge_halo, and REMOVES
  audio_timecode from the overlay set.
- + 2 audio codes (Decision D, T03E audio checks): audio_missing,
  av_sync_drift.
Total enum = 10 codes, 1:1 for category and reason_code.

SQLite cannot ALTER a CHECK constraint, so this revision performs the
standard table rebuild: create ``qc_item_new`` with the NEW CHECK literals
(byte twins of the ORM CHECKs DERIVED from the updated Python tuples in
app/persistence/models.py), copy every row, drop the old table, rename.
The five explicit ``ix_qc_item_*`` indexes are recreated AFTER the rename
(SQLite index names are database-global so they cannot exist on both tables
at once); the table-level UNIQUE constraint lives inside the new table and
its auto-index is renamed by SQLite together with the table.

Fail-closed in BOTH directions:
- upgrade: refuses BEFORE any DDL/data mutation if ANY existing qc_item row
  carries a ``category``/``reason_code`` invalid under the NEW enum
  (renamed/removed values) — the migration never silently mutates or
  corrupts data;
- downgrade: refuses if ANY row carries a value invalid under the OLD enum
  (e.g. edge_halo / audio_missing / av_sync_drift).
PRAGMA integrity_check / foreign_key_check run on every mutation decision
path.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e11a02a2026f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "qc_item"
_TABLE_NEW = "qc_item_new"

# FROZEN literals — byte twins of the ORM CHECKs DERIVED from the updated
# single Python tuples (CONTACT_KIND_CHECK_SQL pattern) in
# app/persistence/models.py (QC_ITEM_CATEGORIES / QC_REASON_CODES).
_STATUS_CHECK = "status IN ('open','acknowledged','resolved','dismissed')"
_SEVERITY_CHECK = "severity IN ('blocker','warning','info')"
_CATEGORY_CHECK = (
    "category IN ('trajectory_drift','cut_drift','contact_break','z_order_error',"
    "'silhouette_clipping','identity_drift','edge_halo','temporal_flicker',"
    "'audio_missing','av_sync_drift')"
)
_REASON_CODE_CHECK = (
    "reason_code IN ('trajectory_drift','cut_drift','contact_break','z_order_error',"
    "'silhouette_clipping','identity_drift','edge_halo','temporal_flicker',"
    "'audio_missing','av_sync_drift')"
)
_CONFIDENCE_SOURCE_CHECK = (
    "confidence_source IN ('model','detector','user','manual','derived')"
)
_SEGMENT_PAIR_NULL_CHECK = (
    "(segment_row_id IS NULL AND segment_logical_id IS NULL) OR "
    "(segment_row_id IS NOT NULL AND segment_logical_id IS NOT NULL)"
)
_BLOCKER_DISMISSED_CHECK = "NOT (severity = 'blocker' AND status = 'dismissed')"

#: The 10 binding codes (NEW enum) and the 8 pre-correction codes (OLD enum).
_NEW_CODES: tuple[str, ...] = (
    "trajectory_drift",
    "cut_drift",
    "contact_break",
    "z_order_error",
    "silhouette_clipping",
    "identity_drift",
    "edge_halo",
    "temporal_flicker",
    "audio_missing",
    "av_sync_drift",
)
_OLD_CODES: tuple[str, ...] = (
    "trajectory_drift",
    "cut_drift",
    "contact_break",
    "z_order",
    "clipping",
    "identity",
    "flicker",
    "audio_timecode",
)

#: OLD (pre-correction) CHECK literals for downgrade — byte twins of the W1
#: ORM-derived literals frozen in ``e11a02a2026f``.
_OLD_CATEGORY_CHECK = (
    "category IN ('trajectory_drift','cut_drift','contact_break','z_order',"
    "'clipping','identity','flicker','audio_timecode')"
)
_OLD_REASON_CODE_CHECK = (
    "reason_code IN ('trajectory_drift','cut_drift','contact_break','z_order',"
    "'clipping','identity','flicker','audio_timecode')"
)

_COLUMNS = (
    "id, workspace_id, project_id, video_item_id, segment_row_id, "
    "segment_logical_id, layer_ref_type, layer_ref_id, reason_code, "
    "evidence_window_key, evidence_json, status, severity, category, detector, "
    "detector_revision, confidence, confidence_source, checkpoint_ref, "
    "created_at, updated_at, revision"
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


def _assert_rows_compatible(
    conn: Connection, allowed: tuple[str, ...], phase: str
) -> None:
    """Fail-closed: every existing row must satisfy the target enum."""
    args = list(enumerate(allowed))
    cat_placeholders = ", ".join(f":cat{i}" for i, _ in args)
    rc_placeholders = ", ".join(f":rc{i}" for i, _ in args)
    params: dict[str, str] = {}
    for i, code in args:
        params[f"cat{i}"] = code
        params[f"rc{i}"] = code
    rows = conn.execute(
        sa.text(
            f"SELECT id, category, reason_code FROM {_TABLE} "
            f"WHERE category NOT IN ({cat_placeholders}) "
            f"OR reason_code NOT IN ({rc_placeholders})"
        ),
        params,
    ).fetchall()
    bad = [
        (r[0], r[1], r[2])
        for r in rows
        if r[1] not in allowed or r[2] not in allowed
    ]
    if bad:
        raise RuntimeError(
            f"refusing to proceed ({phase}): {len(bad)} qc_item row(s) use "
            f"enum values outside the target set, e.g. {bad[:3]!r} — the "
            "migration never silently rewrites or drops data"
        )


def upgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: rows using renamed/removed codes would violate the
    # NEW CHECK after the copy — refuse before any DDL mutation.
    _assert_rows_compatible(conn, _NEW_CODES, "upgrade pre-DDL check")

    op.create_table(
        _TABLE_NEW,
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

    # Copy every existing row verbatim (column-for-column, no mutation).
    op.execute(
        f"INSERT INTO {_TABLE_NEW} ({_COLUMNS}) "
        f"SELECT {_COLUMNS} FROM {_TABLE}"
    )
    op.drop_table(_TABLE)
    op.rename_table(_TABLE_NEW, _TABLE)

    # Recreate the explicit indexes on the (renamed) live table.
    op.create_index("ix_qc_item_workspace", _TABLE, ["workspace_id"])
    op.create_index("ix_qc_item_project", _TABLE, ["project_id"])
    op.create_index("ix_qc_item_video", _TABLE, ["video_item_id"])
    op.create_index("ix_qc_item_segment", _TABLE, ["segment_row_id"])
    op.create_index("ix_qc_item_status", _TABLE, ["status"])

    _assert_db_integrity(conn, "upgrade qc_item enum correction")


def downgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: rows using NEW-only codes (edge_halo / audio_missing
    # / av_sync_drift / renamed codes) would violate the OLD CHECK.
    _assert_rows_compatible(conn, _OLD_CODES, "downgrade pre-DDL check")

    op.create_table(
        _TABLE_NEW,
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
        # OLD (pre-correction) CHECK literals — the frozen W1 enum.
        sa.CheckConstraint(
            "status IN ('open','acknowledged','resolved','dismissed')",
            name="ck_qc_item_status",
        ),
        sa.CheckConstraint(
            "severity IN ('blocker','warning','info')", name="ck_qc_item_severity"
        ),
        sa.CheckConstraint(
            _OLD_CATEGORY_CHECK,
            name="ck_qc_item_category",
        ),
        sa.CheckConstraint(
            _OLD_REASON_CODE_CHECK,
            name="ck_qc_item_reason_code",
        ),
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

    op.execute(
        f"INSERT INTO {_TABLE_NEW} ({_COLUMNS}) "
        f"SELECT {_COLUMNS} FROM {_TABLE}"
    )
    op.drop_table(_TABLE)
    op.rename_table(_TABLE_NEW, _TABLE)

    op.create_index("ix_qc_item_workspace", _TABLE, ["workspace_id"])
    op.create_index("ix_qc_item_project", _TABLE, ["project_id"])
    op.create_index("ix_qc_item_video", _TABLE, ["video_item_id"])
    op.create_index("ix_qc_item_segment", _TABLE, ["segment_row_id"])
    op.create_index("ix_qc_item_status", _TABLE, ["status"])

    _assert_db_integrity(conn, "downgrade qc_item enum correction")