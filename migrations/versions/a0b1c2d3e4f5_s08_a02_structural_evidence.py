"""Add S08-A02 structural evidence bridge schema (occurrence segments,
segment motion, scene-graph occlusion/contact edges).

Revision ID: a0b1c2d3e4f5
Revises: f7a8b9c0d1e2

Four NEW tables (SQLite CREATE TABLE so every CHECK/FK/index is real
reflection-visible metadata):

- ``occurrence_segment`` — the durable occurrence/segment evidence record:
  stable opaque ``id`` (the per-version evidence-record id) plus the stable
  ``logical_id`` (the durable lineage key — names are never joins), explicit
  frame/time range, generation ownership (``source_generation`` +
  ``source_job_id``), prompt/segmentation JSON evidence, an optional mask
  artifact reference, scene-graph geometry (visibility + z-order), CAS
  revision and the self-FK ``superseded_by_id`` correction lineage.
- ``segment_motion`` — camera-relative / object-relative transform contract:
  deterministic JSON blob + provenance/confidence + temporal validity +
  durable point/track/flow evidence reference.  CONTRACT-ONLY: no dense
  optical-flow engine is implemented by this migration or this task.
- ``scene_graph_occlusion`` — occluder occurrence/segment -> occludee edge
  with temporal validity, provenance and confidence.
- ``scene_graph_contact`` — contact edge/event between two occurrence
  segments (hand<->phone, character<->phone, ...) with temporal validity,
  provenance, confidence and a stable contact kind.

R1 recovery design (S08-A02-T01-R1, Codex findings F1..F11 normative):

- F2/F3: the segment carries a STABLE ``logical_id`` across corrections
  (same lineage) while ``id`` is the immutable per-version evidence-record
  id.  Active/current rows are deduplicated by a PARTIAL UNIQUE INDEX
  ``uq_occurrence_segment_active_identity`` (``WHERE superseded_by_id
  IS NULL`` on ``(role_id, scene_id, start_frame, end_frame,
  source_generation)``) so multiple versions/generations coexist and a
  successor of the same occurrence never conflicts (SQLite 3.45 reflects
  and enforces partial unique indexes).
- F8: ``segment_motion`` / ``scene_graph_occlusion`` / ``scene_graph_contact``
  carry NO dead ``superseded_by_id`` column (real supersession lives on
  ``occurrence_segment`` only); their updates stay CAS-versioned.
- F9: every new table has a workspace-scoped idempotency UNIQUE INDEX
  ``WHERE idempotency_key IS NOT NULL`` — the key is used, not just stored;
  the natural key is never an idempotency key.
- F11: table/column/nullability/CHECK/FK-delete-policy/index/server-default
  parity with ``app.persistence.models`` A02 block is asserted by
  tests/test_s08_a02_structural_evidence_migration.py.

Fail-closed downgrade (same discipline as f7a8b9c0d1e2 F1): if ANY row
exists in any new table, ``downgrade`` REFUSES before any DDL/data mutation
with a stable ``RuntimeError``; the revision, DDL, rows, indexes and FKs stay
byte-identical.  PRAGMA integrity_check / foreign_key_check run on every
mutation decision path.

Frozen CHECK literals below are byte-identical to the ORM-derived literals
(``OBJECT_KIND_CHECK_SQL`` / ``OCCURRENCE_SEGMENT_VISIBILITY_CHECK_SQL`` /
``CONTACT_KIND_CHECK_SQL`` in ``app.persistence.models``) — asserted by the
parity test.  Migrations are immutable; they keep their own frozen snapshot.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = (
    "occurrence_segment",
    "segment_motion",
    "scene_graph_occlusion",
    "scene_graph_contact",
)

#: Frozen CHECK literals (byte-identical to the ORM-derived strings).
_KIND_CHECK = (
    "kind IN ('character','prop','background','foreground','graphic',"
    "'source_overlay','other')"
)
_VISIBILITY_CHECK = "visibility IN ('visible','occluded','out_of_frame','hidden')"
_CONTACT_KIND_CHECK = (
    "contact_kind IN ('hand_phone','character_phone','hand_face','touch',"
    "'grasp','other')"
)
_CONFIDENCE_SOURCE_CHECK = (
    "confidence_source IN ('model','detector','user','manual','derived')"
)


def _assert_db_integrity(conn: Connection, phase: str) -> None:
    """Fail closed if the DB is not internally consistent after a mutation."""
    integrity = conn.execute(sa.text("PRAGMA integrity_check")).fetchall()
    if not integrity or str(integrity[0][0]).strip().lower() != "ok":
        raise RuntimeError(
            f"PRAGMA integrity_check after {phase} did not report ok: {integrity!r}"
        )
    fk_violations = conn.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if fk_violations:
        raise RuntimeError(
            f"PRAGMA foreign_key_check after {phase} found {len(fk_violations)} "
            f"violation(s): {fk_violations[:5]!r}"
        )


def _assert_no_structural_evidence_rows(conn: Connection) -> None:
    """Fail-closed downgrade pre-check: refuse BEFORE any DDL/data mutation.

    If any row exists in any new table, dropping the tables would silently
    lose that evidence.  The downgrade is REFUSED ATOMICALLY — alembic exits
    non-zero and revision/DDL/rows/indexes/FKs stay byte-identical (S08-A02
    AC6, same discipline as f7a8b9c0d1e2 F1).
    """
    for table in _NEW_TABLES:
        count = int(
            conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()
            or 0
        )
        if count > 0:
            raise RuntimeError(
                f"refusing to downgrade: {count} structural evidence row(s) "
                f"exist in {table!r}; the structural evidence schema cannot be "
                "dropped without silently losing that evidence (S08-A02 AC6 "
                "fail-closed downgrade)"
            )


def _occurrence_segment_cols() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("logical_id", sa.String(36), nullable=False),
        # C1-F2: explicit lineage versioning (starts at 1; successor = prior + 1).
        sa.Column(
            "lineage_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
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
            "role_id",
            sa.String(36),
            # C1-F7: structural evidence is durable historical truth — deleting
            # a role must NOT cascade-erase its occurrence-segment history.
            sa.ForeignKey("object_role.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "scene_id",
            sa.String(36),
            sa.ForeignKey("scene.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(240), nullable=False),
        # kind/visibility/z_order/confidence_source/reasons_json carry CLIENT
        # defaults in the ORM only (parity — no server_default in the DDL).
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("start_time_ms", sa.Integer(), nullable=False),
        sa.Column("end_time_ms", sa.Integer(), nullable=False),
        sa.Column("source_generation", sa.String(64), nullable=False),
        sa.Column(
            "source_job_id",
            sa.String(36),
            sa.ForeignKey("job.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("prompt_json", sa.Text(), nullable=True),
        sa.Column("segmentation_json", sa.Text(), nullable=True),
        sa.Column(
            "mask_artifact_id",
            sa.String(36),
            sa.ForeignKey("artifact.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("algorithm", sa.String(64), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_source", sa.String(32), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("z_order", sa.Integer(), nullable=False),
        sa.Column(
            "superseded_by_id",
            sa.String(36),
            sa.ForeignKey(
                "occurrence_segment.id",
                ondelete="RESTRICT",
                deferrable=True,
                initially="DEFERRED",
            ),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
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
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    ]


def _segment_constr() -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(
            "start_frame >= 0", name="ck_occurrence_segment_start_frame_nonneg"
        ),
        sa.CheckConstraint(
            "end_frame >= start_frame", name="ck_occurrence_segment_end_frame_ge_start"
        ),
        sa.CheckConstraint(
            "start_time_ms >= 0", name="ck_occurrence_segment_start_time_ms_nonneg"
        ),
        sa.CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_occurrence_segment_end_time_ms_ge_start",
        ),
        sa.CheckConstraint(
            "length(source_generation) BETWEEN 1 AND 64",
            name="ck_occurrence_segment_source_generation_len",
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 240", name="ck_occurrence_segment_name_len"
        ),
        sa.CheckConstraint(_KIND_CHECK, name="ck_occurrence_segment_kind"),
        sa.CheckConstraint(_VISIBILITY_CHECK, name="ck_occurrence_segment_visibility"),
        sa.CheckConstraint(
            "z_order BETWEEN -1000000 AND 1000000",
            name="ck_occurrence_segment_z_order_range",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_occurrence_segment_confidence_range",
        ),
        sa.CheckConstraint(
            _CONFIDENCE_SOURCE_CHECK, name="ck_occurrence_segment_confidence_source"
        ),
        sa.CheckConstraint(
            "length(algorithm) <= 64", name="ck_occurrence_segment_algorithm_len"
        ),
        sa.CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_occurrence_segment_algorithm_version_len",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_occurrence_segment_idempotency_key_len",
        ),
        sa.CheckConstraint("revision > 0", name="ck_occurrence_segment_revision_positive"),
        sa.CheckConstraint(
            "lineage_version >= 1",
            name="ck_occurrence_segment_lineage_version_positive",
        ),
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id != id",
            name="ck_occurrence_segment_no_self_link",
        ),
    ]


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "occurrence_segment",
        *_occurrence_segment_cols(),
        *_segment_constr(),
    )
    op.create_index("ix_occurrence_segment_role", "occurrence_segment", ["role_id"])
    op.create_index("ix_occurrence_segment_scene", "occurrence_segment", ["scene_id"])
    op.create_index(
        "ix_occurrence_segment_video_generation",
        "occurrence_segment",
        ["video_item_id", "source_generation"],
    )
    op.create_index(
        "ix_occurrence_segment_mask_artifact",
        "occurrence_segment",
        ["mask_artifact_id"],
    )
    # C2-F4: DB-enforced lineage — no self-link CHECK, unique successor,
    # and unique active lineage (partial indexes). Branch safety is still CAS
    # but now also DB-refused.
    op.create_index(
        "uq_occurrence_segment_successor",
        "occurrence_segment",
        ["superseded_by_id"],
        unique=True,
        sqlite_where=sa.text("superseded_by_id IS NOT NULL"),
    )
    op.create_index(
        "uq_occurrence_segment_active_lineage",
        "occurrence_segment",
        ["workspace_id", "logical_id"],
        unique=True,
        sqlite_where=sa.text("superseded_by_id IS NULL"),
    )
    op.create_index(
        "ix_occurrence_segment_superseded_by",
        "occurrence_segment",
        ["superseded_by_id"],
    )
    # C1-F2: UNIQUE(workspace_id, logical_id, lineage_version) — current
    # version determinable, no duplicate/branching lineage version.
    op.create_index(
        "uq_occurrence_segment_lineage_version",
        "occurrence_segment",
        ["workspace_id", "logical_id", "lineage_version"],
        unique=True,
    )
    op.create_index(
        "ix_occurrence_segment_logical_id", "occurrence_segment", ["logical_id"]
    )
    op.create_index(
        "uq_occurrence_segment_active_identity",
        "occurrence_segment",
        ["role_id", "scene_id", "start_frame", "end_frame", "source_generation"],
        unique=True,
        sqlite_where=sa.text("superseded_by_id IS NULL"),
    )
    op.create_index(
        "uq_occurrence_segment_workspace_idempotency",
        "occurrence_segment",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "segment_motion",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "occurrence_segment_id",
            sa.String(36),
            # C1-F7: deleting a segment must NOT silently erase its motion
            # history — RESTRICT + fail-closed delete (was CASCADE in draft).
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("transform_type", sa.String(32), nullable=False),
        sa.Column("transform_json", sa.Text(), nullable=False),
        sa.Column("point_track_flow_ref_json", sa.Text(), nullable=True),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("start_time_ms", sa.Integer(), nullable=False),
        sa.Column("end_time_ms", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_source", sa.String(32), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
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
        sa.UniqueConstraint(
            "occurrence_segment_id",
            "transform_type",
            "start_frame",
            name="uq_segment_motion_segment_type_frame",
        ),
        sa.CheckConstraint(
            "transform_type IN ('camera_relative','object_relative')",
            name="ck_segment_motion_transform_type",
        ),
        sa.CheckConstraint(
            "start_frame >= 0", name="ck_segment_motion_start_frame_nonneg"
        ),
        sa.CheckConstraint(
            "end_frame >= start_frame", name="ck_segment_motion_end_frame_ge_start"
        ),
        sa.CheckConstraint(
            "start_time_ms >= 0", name="ck_segment_motion_start_time_ms_nonneg"
        ),
        sa.CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_segment_motion_end_time_ms_ge_start",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_segment_motion_confidence_range",
        ),
        sa.CheckConstraint(
            _CONFIDENCE_SOURCE_CHECK, name="ck_segment_motion_confidence_source"
        ),
        sa.CheckConstraint(
            "length(algorithm) <= 64", name="ck_segment_motion_algorithm_len"
        ),
        sa.CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_segment_motion_algorithm_version_len",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_segment_motion_idem_key_len"
        ),
        sa.CheckConstraint("revision > 0", name="ck_segment_motion_revision_positive"),
    )
    op.create_index(
        "ix_segment_motion_segment", "segment_motion", ["occurrence_segment_id"]
    )
    op.create_index(
        "uq_segment_motion_workspace_idempotency",
        "segment_motion",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "scene_graph_occlusion",
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
            "occluder_segment_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "occludee_segment_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("start_time_ms", sa.Integer(), nullable=False),
        sa.Column("end_time_ms", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_source", sa.String(32), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
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
        sa.UniqueConstraint(
            "occluder_segment_id",
            "occludee_segment_id",
            "start_frame",
            name="uq_scene_graph_occlusion_natural_key",
        ),
        sa.CheckConstraint(
            "occluder_segment_id != occludee_segment_id",
            name="ck_scene_graph_occlusion_not_self",
        ),
        sa.CheckConstraint(
            "start_frame >= 0", name="ck_scene_graph_occlusion_start_frame_nonneg"
        ),
        sa.CheckConstraint(
            "end_frame >= start_frame", name="ck_scene_graph_occlusion_end_frame_ge_start"
        ),
        sa.CheckConstraint(
            "start_time_ms >= 0", name="ck_scene_graph_occlusion_start_time_ms_nonneg"
        ),
        sa.CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_scene_graph_occlusion_end_time_ms_ge_start",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_scene_graph_occlusion_confidence_range",
        ),
        sa.CheckConstraint(
            _CONFIDENCE_SOURCE_CHECK, name="ck_scene_graph_occlusion_confidence_source"
        ),
        sa.CheckConstraint(
            "length(algorithm) <= 64", name="ck_scene_graph_occlusion_algorithm_len"
        ),
        sa.CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_scene_graph_occlusion_algorithm_version_len",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_scene_graph_occlusion_idem_key_len",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_scene_graph_occlusion_revision_positive"
        ),
    )
    op.create_index(
        "ix_scene_graph_occlusion_occluder",
        "scene_graph_occlusion",
        ["occluder_segment_id"],
    )
    op.create_index(
        "ix_scene_graph_occlusion_occludee",
        "scene_graph_occlusion",
        ["occludee_segment_id"],
    )
    op.create_index(
        "ix_scene_graph_occlusion_video", "scene_graph_occlusion", ["video_item_id"]
    )
    op.create_index(
        "uq_scene_graph_occlusion_workspace_idempotency",
        "scene_graph_occlusion",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "scene_graph_contact",
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
            "source_segment_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "target_segment_id",
            sa.String(36),
            sa.ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("contact_kind", sa.String(32), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("start_time_ms", sa.Integer(), nullable=False),
        sa.Column("end_time_ms", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=True),
        sa.Column("algorithm_version", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confidence_source", sa.String(32), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
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
        sa.UniqueConstraint(
            "source_segment_id",
            "target_segment_id",
            "contact_kind",
            "start_frame",
            name="uq_scene_graph_contact_natural_key",
        ),
        sa.CheckConstraint(
            "source_segment_id != target_segment_id",
            name="ck_scene_graph_contact_not_self",
        ),
        sa.CheckConstraint(_CONTACT_KIND_CHECK, name="ck_scene_graph_contact_kind"),
        sa.CheckConstraint(
            "start_frame >= 0", name="ck_scene_graph_contact_start_frame_nonneg"
        ),
        sa.CheckConstraint(
            "end_frame >= start_frame", name="ck_scene_graph_contact_end_frame_ge_start"
        ),
        sa.CheckConstraint(
            "start_time_ms >= 0", name="ck_scene_graph_contact_start_time_ms_nonneg"
        ),
        sa.CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_scene_graph_contact_end_time_ms_ge_start",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_scene_graph_contact_confidence_range",
        ),
        sa.CheckConstraint(
            _CONFIDENCE_SOURCE_CHECK, name="ck_scene_graph_contact_confidence_source"
        ),
        sa.CheckConstraint(
            "length(algorithm) <= 64", name="ck_scene_graph_contact_algorithm_len"
        ),
        sa.CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_scene_graph_contact_algorithm_version_len",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_scene_graph_contact_idem_key_len"
        ),
        sa.CheckConstraint("revision > 0", name="ck_scene_graph_contact_revision_positive"),
    )
    op.create_index(
        "ix_scene_graph_contact_source", "scene_graph_contact", ["source_segment_id"]
    )
    op.create_index(
        "ix_scene_graph_contact_target", "scene_graph_contact", ["target_segment_id"]
    )
    op.create_index("ix_scene_graph_contact_video", "scene_graph_contact", ["video_item_id"])
    op.create_index(
        "uq_scene_graph_contact_workspace_idempotency",
        "scene_graph_contact",
        ["workspace_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    _assert_db_integrity(conn, "upgrade")


def downgrade() -> None:
    conn = op.get_bind()
    # S08-A02 AC6: fail closed BEFORE any DDL/data mutation — if any row
    # exists in any new table the downgrade is REFUSED ATOMICALLY (revision,
    # DDL, rows, indexes, FKs stay byte-identical).  Must run before the
    # first DROP so a refused downgrade never touches sqlite_master or data.
    _assert_no_structural_evidence_rows(conn)
    op.drop_table("scene_graph_contact")
    op.drop_table("scene_graph_occlusion")
    op.drop_table("segment_motion")
    op.drop_table("occurrence_segment")
    _assert_db_integrity(conn, "downgrade")
