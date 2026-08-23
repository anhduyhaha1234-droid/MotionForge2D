"""S09-T00-I01: structural lock + renderer route schema (additive).

Revision ID: d8e9f0a1b2c3
Revises: c9d0e1f2a3b4
Create Date: 2026-08-23

Sole S09-T00-I01 migration.  FOUR additive operations, ZERO destructive ops:

1. NEW ``structural_lock_manifest`` — versioned StructuralLockManifest per
   Video Item (TARGET_PROFILE §4 P0-1): opaque ``id`` PK,
   workspace/project/video FK RESTRICT, ``source_generation`` (canonical
   occurrence-segment values), ``version`` >= 1 with
   UNIQUE(workspace, project, video, generation, version), status CHECK in
   ('draft','active','superseded','voided'), frozen ``policy_version``,
   sha256 ``manifest_hash`` (exactly 64 chars), fail-closed-validated
   ``manifest_json``, workspace-scoped idempotency UNIQUE WHERE NOT NULL,
   self-link guard + partial unique active-slot index
   (WHERE status IN ('draft','active')), timestamps + revision CAS.

2. NEW ``segment_render_route`` — persisted renderer route + contact anchor
   per occurrence segment (§4 P0-4/P0-7): route CHECK derived from the
   canonical RENDERER_ROUTES enum {pose_swap,sprite_affine,mesh_warp,
   part_rig,controlled_redraw} (ORM single authority), contact anchors
   ``anchor_x``/``anchor_y`` CHECK-bound into [0,1] (normalized source-frame
   coordinates), frame-range/confidence/confidence-source/length CHECKs,
   provenance_json evidence, natural key
   UNIQUE(occurrence_segment_id, route, start_frame), all parent FKs RESTRICT,
   workspace-scoped idempotency.

3. ADDITIVE columns on ``reskin_config``: ``structural_lock_manifest_id``
   FK RESTRICT to structural_lock_manifest.id (optional pin) +
   ``lock_policy_version`` VARCHAR(64).  Implemented as NATIVE SQLite
   ``ALTER TABLE ADD COLUMN`` (spike-verified on this host's SQLite 3.45.1:
   the sqlite_master CREATE statement stays byte-stable through an
   upgrade→downgrade→upgrade cycle and the added FK is genuinely enforced
   under PRAGMA foreign_keys=ON).  ``batch_alter_table`` would recreate both
   tables and DESTROY byte identity, so it is deliberately NOT used.

4. ADDITIVE columns on ``apply_checkpoint``: same two-column pin pair so an
   approved checkpoint freezes the manifest version + policy it validated.

Fail-closed downgrade: refuses BEFORE any DDL/data mutation if ANY row exists
in either new table or in either altered table that actually USES a pin value;
otherwise drops only what this revision created (added columns are dropped
natively — spike-verified byte-restoring; new tables dropped last).  PRAGMA
integrity_check / foreign_key_check run on every mutation decision path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = ("structural_lock_manifest", "segment_render_route")
_ALTERED_TABLES = ("reskin_config", "apply_checkpoint")
_PIN_COLUMNS = ("structural_lock_manifest_id", "lock_policy_version")


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
                f"{table!r}; the S09-T00 structural-lock schema cannot be "
                "dropped without silently losing that data "
                "(fail-closed downgrade)"
            )


def upgrade() -> None:
    conn = op.get_bind()
    op.create_table(
        "structural_lock_manifest",
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
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column(
            "superseded_by_id",
            sa.String(36),
            sa.ForeignKey(
                "structural_lock_manifest.id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default=sa.text("1")
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
        sa.CheckConstraint(
            "version >= 1", name="ck_structural_lock_manifest_version_positive"
        ),
        sa.CheckConstraint(
            "length(source_generation) BETWEEN 1 AND 64",
            name="ck_structural_lock_manifest_source_generation_len",
        ),
        sa.CheckConstraint(
            "length(policy_version) BETWEEN 1 AND 64",
            name="ck_structural_lock_manifest_policy_version_len",
        ),
        sa.CheckConstraint(
            "length(manifest_hash) = 64",
            name="ck_structural_lock_manifest_hash_len",
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','superseded','voided')",
            name="ck_structural_lock_manifest_status",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_structural_lock_manifest_idem_key_len",
        ),
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id != id",
            name="ck_structural_lock_manifest_no_self_link",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_structural_lock_manifest_revision_positive"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "video_item_id",
            "source_generation",
            "version",
            name="uq_structural_lock_manifest_natural_key",
        ),
    )
    op.create_index(
        "ix_structural_lock_manifest_workspace",
        "structural_lock_manifest",
        ["workspace_id"],
    )
    op.create_index(
        "ix_structural_lock_manifest_project",
        "structural_lock_manifest",
        ["project_id"],
    )
    op.create_index(
        "ix_structural_lock_manifest_video",
        "structural_lock_manifest",
        ["video_item_id"],
    )
    op.create_index(
        "ix_structural_lock_manifest_superseded_by",
        "structural_lock_manifest",
        ["superseded_by_id"],
    )
    op.create_index(
        "uq_structural_lock_manifest_active",
        "structural_lock_manifest",
        ["workspace_id", "project_id", "video_item_id", "source_generation"],
        unique=True,
        sqlite_where=sa.text("status IN ('draft','active')"),
    )
    op.create_index(
        "uq_structural_lock_manifest_workspace_idempotency",
        "structural_lock_manifest",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _assert_db_integrity(conn, "upgrade structural_lock_manifest")

    op.create_table(
        "segment_render_route",
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
            "occurrence_segment_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "structural_lock_manifest_id",
            sa.String(36),
            sa.ForeignKey("structural_lock_manifest.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        # Route literal DERIVED from app.persistence.models.RENDERER_ROUTES at
        # authoring time (single authority); frozen here for migration
        # determinism.
        sa.Column("route", sa.String(24), nullable=False),
        sa.Column("anchor_x", sa.Float(), nullable=False),
        sa.Column("anchor_y", sa.Float(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_source", sa.String(32), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default=sa.text("1")
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
        sa.CheckConstraint(
            "route IN ('pose_swap','sprite_affine','mesh_warp','part_rig',"
            "'controlled_redraw')",
            name="ck_segment_render_route_route",
        ),
        sa.CheckConstraint(
            "anchor_x >= 0.0 AND anchor_x <= 1.0",
            name="ck_segment_render_route_anchor_x_range",
        ),
        sa.CheckConstraint(
            "anchor_y >= 0.0 AND anchor_y <= 1.0",
            name="ck_segment_render_route_anchor_y_range",
        ),
        sa.CheckConstraint(
            "start_frame >= 0", name="ck_segment_render_route_start_frame_nonneg"
        ),
        sa.CheckConstraint(
            "end_frame >= start_frame",
            name="ck_segment_render_route_end_frame_ge_start",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_segment_render_route_confidence_range",
        ),
        sa.CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_segment_render_route_confidence_source",
        ),
        sa.CheckConstraint(
            "length(algorithm) <= 64",
            name="ck_segment_render_route_algorithm_len",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_segment_render_route_algorithm_version_len",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_segment_render_route_idem_key_len",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_segment_render_route_revision_positive"
        ),
        sa.UniqueConstraint(
            "occurrence_segment_id",
            "route",
            "start_frame",
            name="uq_segment_render_route_natural_key",
        ),
    )
    op.create_index(
        "ix_segment_render_route_segment", "segment_render_route", ["occurrence_segment_id"]
    )
    op.create_index(
        "ix_segment_render_route_video", "segment_render_route", ["video_item_id"]
    )
    op.create_index(
        "ix_segment_render_route_route", "segment_render_route", ["route"]
    )
    op.create_index(
        "ix_segment_render_route_manifest",
        "segment_render_route",
        ["structural_lock_manifest_id"],
    )
    op.create_index(
        "uq_segment_render_route_workspace_idempotency",
        "segment_render_route",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _assert_db_integrity(conn, "upgrade segment_render_route")

    # ── Additive pins on EXISTING tables.  Native ``ALTER TABLE ADD COLUMN``
    # with an inline REFERENCES clause (spike-verified on this host's SQLite
    # 3.45.1: the FK is genuinely enforced — invalid refs refused and parent
    # deletes RESTRICTed under PRAGMA foreign_keys=ON — and
    # PRAGMA foreign_key_list reports ON DELETE RESTRICT, matching what
    # Base.metadata.create_all reflects for these columns).  Alembic's
    # create_foreign_key() raises NotImplementedError on SQLite and
    # batch_alter_table would recreate both tables destroying byte identity;
    # both are deliberately avoided.
    for table in _ALTERED_TABLES:
        op.get_bind().exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN structural_lock_manifest_id "
            "VARCHAR(36) REFERENCES structural_lock_manifest (id) "
            "ON DELETE RESTRICT"
        )
        op.get_bind().exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN lock_policy_version VARCHAR(64)"
        )
        _assert_db_integrity(conn, f"upgrade pin columns on {table}")


def downgrade() -> None:
    conn = op.get_bind()

    # Fail-closed FIRST: any data this schema holds must block the downgrade.
    # Rows in the ALTERED tables matter only when they carry pin values (the
    # columns were added nullable); rows in the NEW tables always matter.
    for table in _ALTERED_TABLES:
        used = int(
            conn.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {table} "
                    "WHERE structural_lock_manifest_id IS NOT NULL "
                    "OR lock_policy_version IS NOT NULL"
                )
            ).scalar()
            or 0
        )
        if used > 0:
            raise RuntimeError(
                f"refusing to downgrade: {used} row(s) in {table!r} still use "
                "structural-lock pin columns; dropping them would silently "
                "lose pinned provenance (S09-T00-I01 fail-closed downgrade)"
            )
    _assert_no_rows(conn, _NEW_TABLES, "pre-DDL check")

    # Drop exactly what this revision created, children before parents.
    for table in _ALTERED_TABLES:
        op.get_bind().exec_driver_sql(
            f"ALTER TABLE {table} DROP COLUMN lock_policy_version"
        )
        op.get_bind().exec_driver_sql(
            f"ALTER TABLE {table} DROP COLUMN structural_lock_manifest_id"
        )
        _assert_db_integrity(conn, f"downgrade pin removal on {table}")

    op.drop_index(
        "uq_segment_render_route_workspace_idempotency", table_name="segment_render_route"
    )
    op.drop_index("ix_segment_render_route_manifest", table_name="segment_render_route")
    op.drop_index("ix_segment_render_route_route", table_name="segment_render_route")
    op.drop_index("ix_segment_render_route_video", table_name="segment_render_route")
    op.drop_index(
        "ix_segment_render_route_segment", table_name="segment_render_route"
    )
    op.drop_table("segment_render_route")
    _assert_db_integrity(conn, "downgrade segment_render_route")

    op.drop_index(
        "uq_structural_lock_manifest_workspace_idempotency",
        table_name="structural_lock_manifest",
    )
    op.drop_index(
        "uq_structural_lock_manifest_active", table_name="structural_lock_manifest"
    )
    op.drop_index(
        "ix_structural_lock_manifest_superseded_by",
        table_name="structural_lock_manifest",
    )
    op.drop_index(
        "ix_structural_lock_manifest_video", table_name="structural_lock_manifest"
    )
    op.drop_index(
        "ix_structural_lock_manifest_project", table_name="structural_lock_manifest"
    )
    op.drop_index(
        "ix_structural_lock_manifest_workspace",
        table_name="structural_lock_manifest",
    )
    op.drop_table("structural_lock_manifest")
    _assert_db_integrity(conn, "downgrade structural_lock_manifest")
