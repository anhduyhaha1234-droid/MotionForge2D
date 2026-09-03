"""SQLAlchemy ORM models for the approved S01 persistence contract.

These models mirror ``docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md``
exactly.  No Job/JobStep tables exist yet (deferred to S02-T01).  Models are
the storage layer only — they are never exported as API schemas.
"""

from __future__ import annotations

import re as _re
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_STATES",
    "ARCHIVED_VIDEO_STATUS",
    "CHARACTER_STATUSES",
    "CHARACTER_SYMMETRIES",
    "CHARACTER_TYPES",
    "CHANNEL_ROLES",
    "CHANNEL_STATUSES",
    "CONTACT_KINDS",
    "CONTACT_KIND_CHECK_SQL",
    "CONTACT_KIND_PATTERN",
    "CORE_POSE_SLOTS",
    "GROUPING_SCOPES",
    "GROUPING_SUGGESTION_STATUSES",
    "JOB_ACTORS",
    "JOB_STATES",
    "JOB_STEP_STATES",
    "LEGACY_IMPORT_STATUSES",
    "OBJECT_KINDS",
    "OBJECT_KIND_CHECK_SQL",
    "OBJECT_KIND_PATTERN",
    "RENDERER_ROUTES",
    "RENDERER_ROUTE_CHECK_SQL",
    "RENDERER_ROUTE_PATTERN",
    "S09_CORRECTION_KINDS",
    "S09_CORRECTION_STATUSES",
    "STRUCTURAL_LOCK_MANIFEST_STATUSES",
    "OBJECT_ROLE_STATUSES",
    "OCCURRENCE_CONFIDENCE_SOURCES",
    "OCCURRENCE_REVIEW_STATES",
    "OCCURRENCE_SEGMENT_VISIBILITY",
    "OCCURRENCE_SEGMENT_VISIBILITY_CHECK_SQL",
    "OCCURRENCE_SEGMENT_VISIBILITY_PATTERN",
    "OBJECT_CORRECTION_STATUSES",
    "OBJECT_CORRECTION_TYPES",
    "OWNER_TYPES",
    "PACK_STATUSES",
    "PROJECT_STATUSES",
    "QC_ITEM_BLOCKER_DISMISSED_CHECK_SQL",
    "QC_ITEM_CATEGORIES",
    "QC_ITEM_CATEGORY_CHECK_SQL",
    "QC_ITEM_SEGMENT_PAIR_NULL_CHECK_SQL",
    "QC_ITEM_SEVERITIES",
    "QC_ITEM_SEVERITY_CHECK_SQL",
    "QC_ITEM_STATUSES",
    "QC_ITEM_STATUS_CHECK_SQL",
    "QC_CONFIDENCE_SOURCE_CHECK_SQL",
    "QC_REASON_CODES",
    "QC_REASON_CODE_CHECK_SQL",
    "RESOURCE_CLASSES",
    "REMOVAL_ONLY_KINDS",
    "SCENE_STATUSES",
    "SOURCE_OVERLAY_KIND",
    "STEP_TYPES",
    "VIDEO_PIPELINE_STATES",
    "Artifact",
    "ArtifactOwner",
    "Character",
    "CharacterAsset",
    "CharacterPackVersion",
    "Channel",
    "ContactEdge",
    "Job",
    "JobAttempt",
    "JobEvent",
    "JobLease",
    "JobStep",
    "LegacyImport",
    "ObjectCorrection",
    "ObjectGroupingSuggestion",
    "ObjectOccurrence",
    "ObjectRole",
    "ObjectRoleArtifact",
    "OcclusionEdge",
    "Project",
    "QCItem",
    "RoleOperation",
    "Scene",
    "SceneGraphContact",
    "ProjectCastMapping",
    "ApplyCheckpoint",
    "ReskinConfig",
    "StructuralLockManifest",
    "SegmentRenderRoute",
    "S09Correction",
    "SceneGraphOcclusion",
    "SegmentMotion",
    "OccurrenceSegment",
    "S10FullApplyChunk",
    "S10FullApplyPublication",
    "S10FullApplyRun",
    "S10_FULL_APPLY_CHUNK_STATES",
    "S10_FULL_APPLY_PUBLICATION_STATES",
    "S10_FULL_APPLY_RUN_STATUSES",
    "VideoItem",
    "Workspace",
    "utc_now",
]

# ── Enum-like constants (stored as validated strings) ────────────────────────

CHANNEL_ROLES = ("source", "production")
CHANNEL_STATUSES = ("active", "archived")
PROJECT_STATUSES = (
    "draft",
    "active",
    "needs_review",
    "rendering",
    "completed",
    "archived",
)
VIDEO_PIPELINE_STATES = (
    "imported",
    "analyzing",
    "objects_ready",
    "mapping_required",
    "demo_required",
    "demo_approved",
    "applying_reskin",
    "needs_review",
    "ready_to_export",
    "rendering",
    "completed",
    "failed",
    "archived",
)
#: Convenience constant: the archive terminal state of a Video Item.
ARCHIVED_VIDEO_STATUS = "archived"
CHARACTER_STATUSES = ("draft", "generating", "needs_review", "ready", "archived")
CHARACTER_TYPES = ("character", "prop", "other")
CHARACTER_SYMMETRIES = ("symmetric", "asymmetric")
PACK_STATUSES = ("draft", "validating", "ready", "published", "archived")
CORE_POSE_SLOTS = ("front", "three_quarter", "side", "back", "sitting", "walking")
SCENE_STATUSES = ("pending", "draft", "approved")
ARTIFACT_KINDS = ("video", "image", "audio", "document", "other")
ARTIFACT_STATES = ("staging", "ready", "trash", "missing", "failed")
OWNER_TYPES = ("channel", "project", "video_item", "scene", "artifact")
LEGACY_IMPORT_STATUSES = ("previewed", "importing", "completed", "failed", "rolled_back")
OBJECT_ROLE_STATUSES = ("suggested", "confirmed", "superseded")
#: Canonical ObjectRole source-locked 2D role/layer taxonomy (S08-A01).
#: Exactly these seven kinds are authoritative across ORM, migration
#: constraint, Pydantic schemas, repository and API.  ``source_overlay`` is
#: the BACKEND-OWNED removal-only role (a source watermark/logo layer that
#: must be removed, never reproduced as a replacement asset).
OBJECT_KINDS = (
    "character",
    "prop",
    "background",
    "foreground",
    "graphic",
    "source_overlay",
    "other",
)
#: Convenience constant for the backend-owned removal-only role kind.
SOURCE_OVERLAY_KIND = "source_overlay"
#: Kinds that are backend-owned removal-only: never a Character Pack /
#: replacement candidate; grouping never pairs them; curation surfaces must
#: not present them as replaceable output.  (Currently exactly
#: ``source_overlay``.)
REMOVAL_ONLY_KINDS = frozenset({SOURCE_OVERLAY_KIND})

#: SQL literal for the ``object_role.kind`` CHECK, DERIVED from
#: ``OBJECT_KINDS`` — the runtime/persistence ORM constraint can never drift
#: from the canonical taxonomy (S08-A01-C1 F3 single authority).  The byte
#: format (no space after each comma) deliberately matches the FROZEN
#: migration snapshot in
#: ``migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py`` so the
#: ``writable_schema`` CHECK-literal edit keeps finding its needle EXACTLY ONCE.
OBJECT_KIND_CHECK_SQL = (
    "kind IN (" + ",".join("'" + k + "'" for k in OBJECT_KINDS) + ")"
)

#: Pydantic ``pattern`` for every role-kind validation, DERIVED from
#: ``OBJECT_KINDS`` (F3 single authority — no duplicated regex literals).
OBJECT_KIND_PATTERN = (
    "^(" + "|".join(_re.escape(k) for k in OBJECT_KINDS) + ")$"
)

OCCURRENCE_CONFIDENCE_SOURCES = ("model", "detector", "user", "manual", "derived")
OCCURRENCE_REVIEW_STATES = ("unreviewed", "accepted", "rejected", "edited")
#: Canonical visibility state of an occurrence/segment (S08-A02 scene graph).
#: Exactly these four states are authoritative across ORM, migration
#: constraint, Pydantic schemas and repository validation.
OCCURRENCE_SEGMENT_VISIBILITY = ("visible", "occluded", "out_of_frame", "hidden")
#: SQL literal for the ``occurrence_segment.visibility`` CHECK, DERIVED from
#: ``OCCURRENCE_SEGMENT_VISIBILITY`` (single authority — never a second copy).
OCCURRENCE_SEGMENT_VISIBILITY_CHECK_SQL = (
    "visibility IN ("
    + ",".join("'" + v + "'" for v in OCCURRENCE_SEGMENT_VISIBILITY)
    + ")"
)
#: Pydantic ``pattern`` for segment visibility, DERIVED from the same enum.
OCCURRENCE_SEGMENT_VISIBILITY_PATTERN = (
    "^(" + "|".join(_re.escape(v) for v in OCCURRENCE_SEGMENT_VISIBILITY) + ")$"
)
#: Canonical renderer routes for the adaptive 2D renderer router (S09-T00-I01,
#: TARGET_PROFILE §4 P0-7 + §8 priority).  EXACTLY these five values are
#: authoritative across ORM, migration CHECK, Pydantic schemas and the
#: repository — never a second copy of the taxonomy.  ``pose_swap`` covers the
#: versioned pose/expression swap route; ``controlled_redraw`` is reserved for
#: exceptional complex shots only.
RENDERER_ROUTES = (
    "pose_swap",
    "sprite_affine",
    "mesh_warp",
    "part_rig",
    "controlled_redraw",
)
#: SQL literal for the ``segment_render_route.route`` CHECK, DERIVED from
#: ``RENDERER_ROUTES`` (single authority).
RENDERER_ROUTE_CHECK_SQL = (
    "route IN (" + ",".join("'" + r + "'" for r in RENDERER_ROUTES) + ")"
)
#: Pydantic ``pattern`` for renderer-route validation, DERIVED likewise.
RENDERER_ROUTE_PATTERN = (
    "^(" + "|".join(_re.escape(r) for r in RENDERER_ROUTES) + ")$"
)
#: Lifecycle statuses of a StructuralLockManifest (S09-T00-I01): ``active``
#: is the manifest a reskin/apply pin resolves to; superseding a manifest
#: archives it as ``superseded`` (history is kept, never overwritten) and a
#: draft lock may be ``voided`` before any pin references it.
STRUCTURAL_LOCK_MANIFEST_STATUSES = ("draft", "active", "superseded", "voided")
#: Targeted S09 correction kinds (S09-T05A): the demo-review mutation the
#: correction applies.  Masks/z-order corrections supersede the locked
#: OccurrenceSegment lineage; contact corrections CAS the SceneGraphContact
#: edge; mesh/parts corrections CAS the SegmentMotion transform; route
#: override writes a NEW SegmentRenderRoute history row (never mutates the
#: old decision).
S09_CORRECTION_KINDS = (
    "mask",
    "z_order",
    "contact",
    "mesh_parts",
    "route_override",
)
#: Correction workflow states (mirrors OBJECT_CORRECTION_STATUSES): a
#: correction is created ``pending`` with its computed affected scope, then
#: atomically confirmed ``applied`` (CAS) or ``cancelled`` — never both.
S09_CORRECTION_STATUSES = ("pending", "applied", "cancelled")
#: Canonical contact kinds for scene-graph contact edges (S08-A02).
#: ``hand_phone`` / ``character_phone`` are the two acceptance-scenario
#: kinds; the remaining values keep the set closed for future events without
#: a schema change.
CONTACT_KINDS = (
    "hand_phone",
    "character_phone",
    "hand_face",
    "touch",
    "grasp",
    "other",
)
#: SQL literal for the ``scene_graph_contact.contact_kind`` CHECK, DERIVED
#: from ``CONTACT_KINDS``.
CONTACT_KIND_CHECK_SQL = (
    "contact_kind IN (" + ",".join("'" + k + "'" for k in CONTACT_KINDS) + ")"
)
#: Pydantic ``pattern`` for contact kinds, DERIVED from the same enum.
CONTACT_KIND_PATTERN = "^(" + "|".join(_re.escape(k) for k in CONTACT_KINDS) + ")$"
#: Reviewable cross-scene grouping suggestions are NEVER auto-confirmed:
#: they start ``pending`` and only explicit user actions move them to
#: ``dismissed`` (reject), ``applied`` (a merge referenced the suggestion) or
#: ``superseded`` (the underlying role set changed — traceable, not deleted).
GROUPING_SUGGESTION_STATUSES = ("pending", "dismissed", "applied", "superseded")
#: Suggestion scope: ``video`` (roles of one video item) — ``project`` is
#: reserved for future cross-video grouping; the API currently supports
#: ``video`` only.
GROUPING_SCOPES = ("video", "project")
#: Explicit durable curation mutations recorded in the operation audit.
ROLE_OPERATION_TYPES = ("merge", "split", "confirm")
#: Targeted correction kinds (S08-T05): the mutation the correction applies.
OBJECT_CORRECTION_TYPES = ("reassign", "candidate_edit", "merge", "split")
#: Correction workflow states: ``pending`` (impact computed, awaiting
#: confirmation) -> ``applied`` (mutation + recompute job committed) or
#: ``cancelled`` (never applied).  The recompute outcome is read from the
#: linked durable Job (successor chain) — the correction row never fabricates
#: a ``completed`` state.
OBJECT_CORRECTION_STATUSES = ("pending", "applied", "cancelled")
JOB_STATES = (
    "pending",
    "queued",
    "running",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
    "fenced",
)
JOB_STEP_STATES = (
    "pending",
    "ready",
    "running",
    "cancelling",
    "cancelled",
    "completed",
    "failed",
    "skipped",
)
RESOURCE_CLASSES = ("cpu_light", "cpu_heavy", "gpu", "io")
STEP_TYPES = ("sync", "async")
JOB_ACTORS = ("worker", "scheduler", "api", "reconciler", "system")


def utc_now() -> datetime:
    """Timezone-aware UTC now used by every default timestamp."""
    return datetime.now(UTC)


def _new_id() -> str:
    """Opaque public identifier (UUIDv7-compatible string; UUID4 initial)."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Declarative base for all persistence models."""


# ── Mixins ────────────────────────────────────────────────────────────────────


class TimestampMixin:
    """Created/updated UTC timestamps plus optimistic-concurrency revision."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=sa_text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=sa_text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )


class ArchivableMixin(TimestampMixin):
    """Adds an optional archived_at timestamp."""

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Entities ──────────────────────────────────────────────────────────────────


class Workspace(TimestampMixin, Base):
    """Root ownership boundary for channels, projects and future libraries."""

    __tablename__ = "workspace"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="ck_workspace_name_len"),
        CheckConstraint("revision > 0", name="ck_workspace_revision_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    channels: Mapped[list[Channel]] = relationship(back_populates="workspace")
    projects: Mapped[list[Project]] = relationship(back_populates="workspace")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="workspace")
    jobs: Mapped[list[Job]] = relationship(back_populates="workspace")
    characters: Mapped[list[Character]] = relationship(back_populates="workspace")


class Channel(ArchivableMixin, Base):
    """Source or production channel owned by a workspace."""

    __tablename__ = "channel"
    __table_args__ = (
        # Uniqueness of ACTIVE channel names is enforced by the partial
        # unique index ``uq_channel_active_workspace_role_name`` (S03-T01
        # migration 1c9f2a4b7d8e): case-insensitive (lower(name)) and
        # active-only (status='active').  The legacy unconditional
        # constraint was dropped by that migration so archived names can
        # be reused by a new active channel.
        UniqueConstraint(
            "workspace_id", "legacy_id", name="uq_channel_workspace_legacy_id"
        ),
        CheckConstraint("length(name) > 0", name="ck_channel_name_nonempty"),
        CheckConstraint("length(name) <= 200", name="ck_channel_name_len"),
        CheckConstraint("role IN ('source', 'production')", name="ck_channel_role"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_channel_status"),
        CheckConstraint("revision > 0", name="ck_channel_revision_positive"),
        Index("ix_channel_workspace_role_name", "workspace_id", "role", "name"),
        Index(
            "uq_channel_active_workspace_role_name",
            "workspace_id",
            "role",
            sa_text("lower(name)"),
            unique=True,
            sqlite_where=sa_text("status = 'active'"),
            postgresql_where=sa_text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200, collation="NOCASE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    color: Mapped[str | None] = mapped_column(String(32))
    avatar_artifact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT")
    )
    target_language: Mapped[str | None] = mapped_column(String(32))
    default_output_profile: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    workspace: Mapped[Workspace] = relationship(back_populates="channels")


class Project(ArchivableMixin, Base):
    """Project aggregate root: owns VideoItem ordering and project defaults."""

    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("workspace_id", "legacy_id", name="uq_project_workspace_legacy_id"),
        CheckConstraint("length(name) BETWEEN 1 AND 200", name="ck_project_name_len"),
        CheckConstraint(
            "status IN ('draft','active','needs_review','rendering','completed','archived')",
            name="ck_project_status",
        ),
        CheckConstraint("revision > 0", name="ck_project_revision_positive"),
        Index("ix_project_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    source_channel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="RESTRICT")
    )
    production_channel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="RESTRICT")
    )
    default_output_profile: Mapped[str | None] = mapped_column(String(64))
    resume_step: Mapped[str | None] = mapped_column(String(64))

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    source_channel: Mapped[Channel | None] = relationship(foreign_keys=[source_channel_id])
    production_channel: Mapped[Channel | None] = relationship(
        foreign_keys=[production_channel_id]
    )
    video_items: Mapped[list[VideoItem]] = relationship(
        back_populates="project", order_by="VideoItem.position"
    )


class VideoItem(ArchivableMixin, Base):
    """Pipeline unit: owns its scene records and references its source media."""

    __tablename__ = "video_item"
    __table_args__ = (
        UniqueConstraint("project_id", "position", name="uq_video_item_project_position"),
        UniqueConstraint("project_id", "legacy_id", name="uq_video_item_project_legacy_id"),
        CheckConstraint("length(title) BETWEEN 1 AND 240", name="ck_video_item_title_len"),
        CheckConstraint("position >= 0", name="ck_video_item_position_nonneg"),
        CheckConstraint(
            "status IN ('imported','analyzing','objects_ready','mapping_required',"
            "'demo_required','demo_approved','applying_reskin','needs_review',"
            "'ready_to_export','rendering','completed','failed','archived')",
            name="ck_video_item_status",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_video_item_duration_ms"
        ),
        CheckConstraint("width IS NULL OR width >= 0", name="ck_video_item_width"),
        CheckConstraint("height IS NULL OR height >= 0", name="ck_video_item_height"),
        CheckConstraint("fps_num IS NULL OR fps_num > 0", name="ck_video_item_fps_num"),
        CheckConstraint("fps_den IS NULL OR fps_den > 0", name="ck_video_item_fps_den"),
        CheckConstraint("revision > 0", name="ck_video_item_revision_positive"),
        Index("ix_video_item_project_position", "project_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="imported")
    source_artifact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT")
    )
    source_channel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="RESTRICT")
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps_num: Mapped[int | None] = mapped_column(Integer)
    fps_den: Mapped[int | None] = mapped_column(Integer)
    resume_step: Mapped[str | None] = mapped_column(String(64))
    resume_payload_json: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="video_items")
    source_channel: Mapped[Channel | None] = relationship(foreign_keys=[source_channel_id])
    scenes: Mapped[list[Scene]] = relationship(
        back_populates="video_item", order_by="Scene.position"
    )


class Scene(TimestampMixin, Base):
    """Scene record owned by a VideoItem (cascade only inside authorized purge)."""

    __tablename__ = "scene"
    __table_args__ = (
        UniqueConstraint("video_item_id", "position", name="uq_scene_video_item_position"),
        UniqueConstraint(
            "video_item_id", "legacy_scene_id", name="uq_scene_video_item_legacy_id"
        ),
        CheckConstraint("position >= 0", name="ck_scene_position_nonneg"),
        CheckConstraint("start_frame >= 0", name="ck_scene_start_frame_nonneg"),
        CheckConstraint("end_frame >= 0", name="ck_scene_end_frame_nonneg"),
        CheckConstraint("start_time_ms >= 0", name="ck_scene_start_time_ms_nonneg"),
        CheckConstraint("end_time_ms >= 0", name="ck_scene_end_time_ms_nonneg"),
        CheckConstraint("end_frame >= start_frame", name="ck_scene_end_frame_ge_start"),
        CheckConstraint("end_time_ms >= start_time_ms", name="ck_scene_end_time_ms_ge_start"),
        CheckConstraint("status IN ('pending', 'draft', 'approved')", name="ck_scene_status"),
        CheckConstraint("revision > 0", name="ck_scene_revision_positive"),
        Index("ix_scene_video_item_position", "video_item_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="CASCADE"), nullable=False
    )
    legacy_scene_id: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    video_item: Mapped[VideoItem] = relationship(back_populates="scenes")


class Artifact(TimestampMixin, Base):
    """Managed file record; bytes live under the configured managed root."""

    __tablename__ = "artifact"
    __table_args__ = (
        UniqueConstraint("workspace_id", "relative_path", name="uq_artifact_workspace_path"),
        CheckConstraint("length(relative_path) > 0", name="ck_artifact_path_nonempty"),
        CheckConstraint(
            "kind IN ('video','image','audio','document','other')", name="ck_artifact_kind"
        ),
        CheckConstraint(
            "state IN ('staging','ready','trash','missing','failed')",
            name="ck_artifact_state",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_artifact_size_bytes"),
        CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64", name="ck_artifact_sha256_len"
        ),
        CheckConstraint("revision > 0", name="ck_artifact_revision_positive"),
        Index("ix_artifact_workspace_path", "workspace_id", "relative_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="staging")
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    # Pixel dimensions of the artifact (S08-T02; NULL for non-image kinds).
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="artifacts")
    owners: Mapped[list[ArtifactOwner]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class ArtifactOwner(Base):
    """Explicit polymorphic owner link between an artifact and a business entity."""

    __tablename__ = "artifact_owner"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('channel','project','video_item','scene','artifact')",
            name="ck_artifact_owner_type",
        ),
        CheckConstraint("length(purpose) > 0", name="ck_artifact_owner_purpose_nonempty"),
        Index("ix_artifact_owner_owner", "owner_type", "owner_id"),
    )

    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT"), primary_key=True
    )
    owner_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), primary_key=True)

    artifact: Mapped[Artifact] = relationship(back_populates="owners")


class LegacyImport(Base):
    """Idempotent record of a legacy JSON import attempt."""

    __tablename__ = "legacy_import"
    __table_args__ = (
        UniqueConstraint("source_kind", "source_sha256", name="uq_legacy_import_kind_sha256"),
        CheckConstraint("length(source_kind) > 0", name="ck_legacy_import_kind_nonempty"),
        CheckConstraint("length(source_locator) > 0", name="ck_legacy_import_locator_nonempty"),
        CheckConstraint("length(source_sha256) = 64", name="ck_legacy_import_sha256_len"),
        CheckConstraint(
            "status IN ('previewed','importing','completed','failed','rolled_back')",
            name="ck_legacy_import_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="previewed")
    summary_json: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Durable job entities (S02-T02, DURABLE_JOB_CONTRACT V1.1) ────────────────


class Job(TimestampMixin, Base):
    """Durable unit of user-visible work (approved DURABLE_JOB_CONTRACT V1.1).

    Terminal rows are immutable: no field changes, no re-run, no delete.
    Retry/restart of a terminal Job is a new successor Job linked through
    ``predecessor_job_id`` (contract §4.5-4, §6.4, §8.5).  Uniqueness: one
    active or completed Job per ``(workspace_id, idempotency_key)``.
    """

    __tablename__ = "job"
    __table_args__ = (
        Index(
            "uq_job_idempotency_key",
            "workspace_id",
            "idempotency_key",
            "input_generation",
            unique=True,
            sqlite_where=sa_text(
                "idempotency_key IS NOT NULL AND state NOT IN ('failed','cancelled')"
            ),
        ),
        UniqueConstraint("predecessor_job_id", name="uq_job_predecessor_job_id"),
        CheckConstraint(
            "state IN ('pending','queued','running','cancelling','cancelled',"
            "'completed','failed','fenced')",
            name="ck_job_state",
        ),
        CheckConstraint(
            "resource_class IN ('cpu_light','cpu_heavy','gpu','io')",
            name="ck_job_resource_class",
        ),
        CheckConstraint("priority BETWEEN 0 AND 100", name="ck_job_priority_range"),
        CheckConstraint("max_attempts >= 1", name="ck_job_max_attempts_positive"),
        CheckConstraint("attempt >= 0", name="ck_job_attempt_nonneg"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_job_progress_range"),
        CheckConstraint("length(job_type) > 0", name="ck_job_type_nonempty"),
        CheckConstraint("length(owner_type) > 0", name="ck_job_owner_type_nonempty"),
        CheckConstraint("length(owner_id) > 0", name="ck_job_owner_id_nonempty"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NOT NULL",
            name="ck_job_finished_requires_started",
        ),
        CheckConstraint("revision > 0", name="ck_job_revision_positive"),
        Index("ix_job_workspace_key", "workspace_id", "idempotency_key"),
        Index("ix_job_workspace_state", "workspace_id", "state"),
        Index("ix_job_queue", "state", "priority", "created_at"),
        Index("ix_job_owner", "owner_type", "owner_id"),
        Index("ix_job_parent", "parent_job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT")
    )
    predecessor_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resource_class: Mapped[str] = mapped_column(
        String(16), nullable=False, default="cpu_light"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    input_generation: Mapped[str | None] = mapped_column(String(64))
    input_manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="jobs")
    steps: Mapped[list[JobStep]] = relationship(
        back_populates="job", order_by="JobStep.position"
    )
    attempts: Mapped[list[JobAttempt]] = relationship(back_populates="job")
    events: Mapped[list[JobEvent]] = relationship(back_populates="job")
    lease: Mapped[JobLease | None] = relationship(back_populates="job")


class JobStep(TimestampMixin, Base):
    """Ordered, resumable unit inside a Job (checkpoint boundary)."""

    __tablename__ = "job_step"
    __table_args__ = (
        UniqueConstraint("job_id", "step_code", name="uq_job_step_job_code"),
        UniqueConstraint("job_id", "position", name="uq_job_step_job_position"),
        CheckConstraint(
            "state IN ('pending','ready','running','cancelling','cancelled',"
            "'completed','failed','skipped')",
            name="ck_job_step_state",
        ),
        CheckConstraint("step_type IN ('sync','async')", name="ck_job_step_type"),
        CheckConstraint(
            "resource_class IN ('cpu_light','cpu_heavy','gpu','io')",
            name="ck_job_step_resource_class",
        ),
        CheckConstraint("position >= 0", name="ck_job_step_position_nonneg"),
        CheckConstraint("priority BETWEEN 0 AND 100", name="ck_job_step_priority_range"),
        CheckConstraint("weight >= 0", name="ck_job_step_weight_nonneg"),
        CheckConstraint("attempt >= 0", name="ck_job_step_attempt_nonneg"),
        CheckConstraint("max_attempts >= 1", name="ck_job_step_max_attempts_positive"),
        CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_job_step_progress_range"
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NOT NULL",
            name="ck_job_step_finished_requires_started",
        ),
        CheckConstraint("revision > 0", name="ck_job_step_revision_positive"),
        Index("ix_job_step_job_position", "job_id", "position"),
        Index("ix_job_step_job_state", "job_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT"), nullable=False
    )
    step_code: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(16), nullable=False, default="sync")
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resource_class: Mapped[str] = mapped_column(
        String(16), nullable=False, default="cpu_light"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    checkpoint_json: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="steps")


class JobAttempt(Base):
    """Append-only record of one JobStep execution (contract §8.2)."""

    __tablename__ = "job_attempt"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "step_id", "attempt", name="uq_job_attempt_job_step_number"
        ),
        UniqueConstraint(
            "job_id", "step_code", "attempt", name="uq_job_attempt_job_code_number"
        ),
        CheckConstraint("attempt >= 1", name="ck_job_attempt_number_positive"),
        CheckConstraint("length(worker_id) > 0", name="ck_job_attempt_worker_nonempty"),
        CheckConstraint("length(fence_token) > 0", name="ck_job_attempt_token_nonempty"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NOT NULL",
            name="ck_job_attempt_finished_requires_started",
        ),
        Index("ix_job_attempt_job_step", "job_id", "step_id", "attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT"), nullable=False
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job_step.id", ondelete="RESTRICT")
    )
    step_code: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fence_token: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="attempts")


class JobEvent(Base):
    """Append-only state-transition log (contract §10.2)."""

    __tablename__ = "job_event"
    __table_args__ = (
        CheckConstraint("length(event_type) > 0", name="ck_job_event_type_nonempty"),
        CheckConstraint(
            "actor IN ('worker','scheduler','api','reconciler','system')",
            name="ck_job_event_actor",
        ),
        Index("ix_job_event_job_created", "job_id", "created_at"),
        Index("ix_job_event_job_step", "job_id", "step_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT"), nullable=False
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job_step.id", ondelete="RESTRICT")
    )
    step_code: Mapped[str | None] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(16))
    to_state: Mapped[str | None] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    fence_token: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int | None] = mapped_column(Integer)
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="events")


class JobLease(TimestampMixin, Base):
    """Exclusive claim by one worker over a Job for a bounded time window."""

    __tablename__ = "job_lease"
    __table_args__ = (
        CheckConstraint("lease_version >= 1", name="ck_job_lease_version_positive"),
        CheckConstraint("length(worker_id) > 0", name="ck_job_lease_worker_nonempty"),
        CheckConstraint("length(fence_token) > 0", name="ck_job_lease_token_nonempty"),
        CheckConstraint("ttl_seconds > 0", name="ck_job_lease_ttl_positive"),
        CheckConstraint(
            "expires_at >= acquired_at", name="ck_job_lease_expires_after_acquired"
        ),
        CheckConstraint(
            "heartbeat_at >= acquired_at", name="ck_job_lease_heartbeat_after_acquired"
        ),
    )

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT"), primary_key=True
    )
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fence_token: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    job: Mapped[Job] = relationship(back_populates="lease")


class Character(ArchivableMixin, Base):
    """Reusable workspace character asset definition."""

    __tablename__ = "character"
    __table_args__ = (
        CheckConstraint("length(name) > 0", name="ck_character_name_nonempty"),
        CheckConstraint("length(name) <= 200", name="ck_character_name_len"),
        CheckConstraint("length(code) > 0", name="ck_character_code_nonempty"),
        CheckConstraint("length(code) <= 64", name="ck_character_code_len"),
        CheckConstraint(
            "character_type IN ('character','prop','other')",
            name="ck_character_type",
        ),
        CheckConstraint(
            "symmetry IN ('symmetric','asymmetric')",
            name="ck_character_symmetry",
        ),
        CheckConstraint(
            "status IN ('draft','generating','needs_review','ready','archived')",
            name="ck_character_status",
        ),
        CheckConstraint("revision > 0", name="ck_character_revision_positive"),
        Index(
            "uq_character_active_workspace_code",
            "workspace_id",
            sa_text("lower(code)"),
            unique=True,
            postgresql_where=sa_text("status != 'archived'"),
            sqlite_where=sa_text("status != 'archived'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    character_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="character"
    )
    symmetry: Mapped[str] = mapped_column(
        String(32), nullable=False, default="symmetric"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
    )
    default_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "character_pack_version.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_character_default_version",
        ),
    )
    description: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    workspace: Mapped[Workspace] = relationship(back_populates="characters")
    versions: Mapped[list[CharacterPackVersion]] = relationship(
        back_populates="character",
        foreign_keys="[CharacterPackVersion.character_id]",
    )


class CharacterPackVersion(ArchivableMixin, Base):
    """Versioned pose pack for a Character."""

    __tablename__ = "character_pack_version"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "version", name="uq_pack_version_character_version"
        ),
        CheckConstraint("version > 0", name="ck_pack_version_positive"),
        CheckConstraint(
            "status IN ('draft','validating','ready','published','archived')",
            name="ck_pack_version_status",
        ),
        CheckConstraint("revision > 0", name="ck_pack_version_revision_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("character.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft"
    )
    validation_json: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    character: Mapped[Character] = relationship(
        back_populates="versions",
        foreign_keys=[character_id],
    )
    workspace: Mapped[Workspace] = relationship()
    assets: Mapped[list[CharacterAsset]] = relationship(back_populates="pack_version")


class CharacterAsset(TimestampMixin, Base):
    """Pose asset slot attachment referencing an Artifact."""

    __tablename__ = "character_asset"
    __table_args__ = (
        UniqueConstraint(
            "pack_version_id", "pose_slot", name="uq_character_asset_version_pose_slot"
        ),
        CheckConstraint("length(pose_slot) > 0", name="ck_character_asset_pose_slot_nonempty"),
        CheckConstraint("length(pose_slot) <= 64", name="ck_character_asset_pose_slot_len"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    pack_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("character_pack_version.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    pose_slot: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT"), nullable=False
    )

    pack_version: Mapped[CharacterPackVersion] = relationship(back_populates="assets")
    artifact: Mapped[Artifact] = relationship()
    workspace: Mapped[Workspace] = relationship()


class ObjectRole(TimestampMixin, Base):
    """Video-global object identity with explicit review status."""

    __tablename__ = "object_role"
    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested','confirmed','superseded')",
            name="ck_object_role_status",
        ),
        CheckConstraint(
            OBJECT_KIND_CHECK_SQL,  # derived from OBJECT_KINDS (F3 single authority)
            name="ck_object_role_kind",
        ),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 240", name="ck_object_role_name_len"
        ),
        CheckConstraint(
            "length(source_generation) > 0",
            name="ck_object_role_source_generation_nonempty",
        ),
        CheckConstraint(
            "length(source_generation) <= 64",
            name="ck_object_role_source_generation_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_role_idempotency_key_len",
        ),
        CheckConstraint("revision > 0", name="ck_object_role_revision_positive"),
        Index(
            "uq_object_role_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_object_role_video_status", "video_item_id", "status"),
        Index("ix_object_role_legacy_object", "legacy_object_id"),
        Index("ix_object_role_supersedes", "supersedes_role_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    source_generation: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="character")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="suggested")
    supersedes_role_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="RESTRICT")
    )
    legacy_object_id: Mapped[str | None] = mapped_column(String(255))
    legacy_scene_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    # The durable DISCOVER_OBJECTS Job that produced (and owns) this role
    # (S08-T02).  NULL for user-created / T01-era roles.
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    occurrences: Mapped[list[ObjectOccurrence]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        order_by="ObjectOccurrence.frame_index",
    )


class ObjectOccurrence(TimestampMixin, Base):
    """Canonical scene/frame evidence for an ObjectRole."""

    __tablename__ = "object_occurrence"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "scene_id", "frame_index", name="uq_object_occurrence_role_scene_frame"
        ),
        CheckConstraint("frame_index >= 0", name="ck_object_occurrence_frame_index_nonneg"),
        CheckConstraint("time_ms >= 0", name="ck_object_occurrence_time_ms_nonneg"),
        CheckConstraint("bbox_x >= 0", name="ck_object_occurrence_bbox_x_nonneg"),
        CheckConstraint("bbox_y >= 0", name="ck_object_occurrence_bbox_y_nonneg"),
        CheckConstraint("bbox_w >= 0", name="ck_object_occurrence_bbox_w_nonneg"),
        CheckConstraint("bbox_h >= 0", name="ck_object_occurrence_bbox_h_nonneg"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_object_occurrence_confidence_range",
        ),
        CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_object_occurrence_confidence_source",
        ),
        CheckConstraint(
            "review_state IN ('unreviewed','accepted','rejected','edited')",
            name="ck_object_occurrence_review_state",
        ),
        CheckConstraint(
            "length(algorithm) <= 64", name="ck_object_occurrence_algorithm_len"
        ),
        CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_object_occurrence_algorithm_version_len",
        ),
        CheckConstraint("revision > 0", name="ck_object_occurrence_revision_positive"),
        Index("ix_object_occurrence_role", "role_id"),
        Index("ix_object_occurrence_scene", "scene_id"),
        Index("ix_object_occurrence_video_frame", "video_item_id", "frame_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scene.id", ondelete="RESTRICT"), nullable=False
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_w: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_h: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_source: Mapped[str] = mapped_column(String(32), nullable=False, default="model")
    algorithm: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, default="unreviewed")
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    role: Mapped[ObjectRole] = relationship(back_populates="occurrences")
    scene: Mapped[Scene] = relationship()


class ObjectRoleArtifact(TimestampMixin, Base):
    """Durable id-based link between an ObjectRole and its published
    candidate artifact (S08-T02 correction B6).

    Keyed by stable ids + purpose + source generation + source job —
    display names are never joins, so renames and duplicate display names
    cannot re-map gallery/grouping references.  Written in the SAME
    publication transaction as the artifacts/roles/occurrences; replay is
    idempotent via the natural-key unique constraint.
    """

    __tablename__ = "object_role_artifact"
    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "artifact_id",
            "purpose",
            "source_generation",
            "source_job_id",
            name="uq_object_role_artifact_natural_key",
        ),
        CheckConstraint(
            "purpose IN ('thumbnail','mask')", name="ck_object_role_artifact_purpose"
        ),
        CheckConstraint(
            "length(source_generation) > 0",
            name="ck_object_role_artifact_generation_nonempty",
        ),
        CheckConstraint(
            "length(source_generation) <= 64",
            name="ck_object_role_artifact_generation_len",
        ),
        Index("ix_object_role_artifact_role", "role_id"),
        Index("ix_object_role_artifact_artifact", "artifact_id"),
        Index("ix_object_role_artifact_job", "source_job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    source_generation: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT"), nullable=False
    )
    # S08-T05-C1: when a correction recompute replaces this role's media the
    # OLD active association is pointed at the replacement via this self-FK —
    # the old row stays auditable, and "newest valid" resolution is simply
    # ``superseded_by_id IS NULL``.
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("object_role_artifact.id", ondelete="RESTRICT"),
        nullable=True,
    )


class ObjectGroupingSuggestion(TimestampMixin, Base):
    """Reviewable cross-scene grouping suggestion (S08-T03).

    A durable, NEVER-auto-confirmed suggestion that a set of ObjectRoles of
    one video item (same source generation) represent the same object.
    Statements carry confidence, review reasons and provenance
    (algorithm/version).  Status starts ``pending``; only explicit user
    actions move it to ``dismissed`` (reject), ``applied`` (a merge
    referenced it) or ``superseded`` (the role set changed — traceable).
    """

    __tablename__ = "object_grouping_suggestion"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','dismissed','applied','superseded')",
            name="ck_object_grouping_suggestion_status",
        ),
        CheckConstraint(
            "scope IN ('video','project')", name="ck_object_grouping_suggestion_scope"
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_object_grouping_suggestion_confidence_range",
        ),
        CheckConstraint(
            "length(source_generation) BETWEEN 1 AND 64",
            name="ck_object_grouping_suggestion_generation_len",
        ),
        CheckConstraint(
            "length(algorithm) BETWEEN 1 AND 64",
            name="ck_object_grouping_suggestion_algorithm_len",
        ),
        CheckConstraint(
            "length(algorithm_version) BETWEEN 1 AND 64",
            name="ck_object_grouping_suggestion_algorithm_version_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_grouping_suggestion_idem_key_len",
        ),
        CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_object_grouping_suggestion_natural_key_len",
        ),
        CheckConstraint(
            "revision > 0", name="ck_object_grouping_suggestion_revision_positive"
        ),
        Index(
            "uq_object_grouping_suggestion_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
            postgresql_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_object_grouping_suggestion_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_object_grouping_suggestion_video_status", "video_item_id", "status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    source_generation: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=sa_text("'pending'"),
    )
    role_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    target_role_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="RESTRICT")
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="video", server_default=sa_text("'video'")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    natural_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )


class RoleOperation(TimestampMixin, Base):
    """Audit history of an explicit durable merge/split/confirm mutation.

    One row per COMPLETED operation (S08-T03).  The row records the target
    role, source role ids, created role ids, the exact transferred-occurrence
    map (merge/split) and the target revision reached — so superseded roles
    and moved evidence stay traceable and approved evidence is never
    silently rewritten or deleted.  ``natural_key`` replay prevents
    duplicate/concurrent requests and restart from creating a second
    mutation.
    """

    __tablename__ = "object_role_operation"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('merge','split','confirm')",
            name="ck_object_role_operation_type",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_role_operation_idem_key_len",
        ),
        CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_object_role_operation_natural_key_len",
        ),
        CheckConstraint(
            "revision_after > 0", name="ck_object_role_operation_revision_after_positive"
        ),
        Index(
            "uq_object_role_operation_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
            postgresql_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_object_role_operation_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_object_role_operation_video_type", "video_item_id", "operation_type"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="RESTRICT"), nullable=False
    )
    source_role_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=sa_text("'[]'")
    )
    created_role_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=sa_text("'[]'")
    )
    transferred_occurrence_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=sa_text("'[]'")
    )
    suggestion_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("object_grouping_suggestion.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    natural_key: Mapped[str | None] = mapped_column(String(255))
    revision_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class ObjectCorrection(TimestampMixin, Base):
    """Durable archive of ONE targeted object correction (S08-T05).

    A correction is created ``pending`` with its computed impacted scope
    (``impact_json`` — the pre-confirmation report), then explicitly
    confirmed: the targeted mutation + supersession of the affected derived
    state + the ``RECOMPUTE_OBJECTS`` job (only where recompute is needed)
    are committed in ONE transaction, and the old affected mapping is
    archived in ``result_json``.  ``natural_key`` replay makes duplicate /
    concurrent requests return the SAME correction; ``recompute_job_id``
    links the durable recompute work (successor chain owns retry).
    """

    __tablename__ = "object_correction"
    __table_args__ = (
        CheckConstraint(
            "correction_type IN ('reassign','candidate_edit','merge','split')",
            name="ck_object_correction_type",
        ),
        CheckConstraint(
            "status IN ('pending','applied','cancelled')",
            name="ck_object_correction_status",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_object_correction_idem_key_len",
        ),
        CheckConstraint(
            "length(natural_key) <= 255",
            name="ck_object_correction_natural_key_len",
        ),
        CheckConstraint(
            "revision > 0", name="ck_object_correction_revision_positive"
        ),
        Index(
            "uq_object_correction_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_object_correction_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_object_correction_video_status",
            "video_item_id",
            "status",
        ),
        Index("ix_object_correction_recompute_job", "recompute_job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    correction_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=sa_text("'pending'"),
    )
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    impact_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    recompute_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT")
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    natural_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )


# ── Structural evidence bridge (S08-A02) ────────────────────────────────────


class OccurrenceSegment(TimestampMixin, Base):
    """Durable occurrence/segment evidence record (S08-A02).

    The structural-evidence bridge's canonical segment: a stable opaque id
    (the durable join key — names are never joins), an explicit frame/time
    range, generation ownership, prompt/segmentation JSON evidence, an
    optional mask artifact reference and scene-graph geometry (visibility +
    z-order).  The record is CAS-versioned and carries a self-FK
    ``superseded_by_id`` so a correction archives the prior row and points it
    at its successor instead of silently overwriting history.
    """

    __tablename__ = "occurrence_segment"
    __table_args__ = (
        CheckConstraint(
            "start_frame >= 0", name="ck_occurrence_segment_start_frame_nonneg"
        ),
        CheckConstraint(
            "end_frame >= start_frame", name="ck_occurrence_segment_end_frame_ge_start"
        ),
        CheckConstraint(
            "start_time_ms >= 0", name="ck_occurrence_segment_start_time_ms_nonneg"
        ),
        CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_occurrence_segment_end_time_ms_ge_start",
        ),
        CheckConstraint(
            "length(source_generation) BETWEEN 1 AND 64",
            name="ck_occurrence_segment_source_generation_len",
        ),
        CheckConstraint(
            "length(name) BETWEEN 1 AND 240", name="ck_occurrence_segment_name_len"
        ),
        CheckConstraint(
            OBJECT_KIND_CHECK_SQL,  # derived from OBJECT_KINDS (F3 single authority)
            name="ck_occurrence_segment_kind",
        ),
        CheckConstraint(
            OCCURRENCE_SEGMENT_VISIBILITY_CHECK_SQL,
            name="ck_occurrence_segment_visibility",
        ),
        CheckConstraint(
            "z_order BETWEEN -1000000 AND 1000000",
            name="ck_occurrence_segment_z_order_range",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_occurrence_segment_confidence_range",
        ),
        CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_occurrence_segment_confidence_source",
        ),
        CheckConstraint(
            "length(algorithm) <= 64", name="ck_occurrence_segment_algorithm_len"
        ),
        CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_occurrence_segment_algorithm_version_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_occurrence_segment_idempotency_key_len",
        ),
        CheckConstraint("revision > 0", name="ck_occurrence_segment_revision_positive"),
        CheckConstraint(
            "lineage_version >= 1",
            name="ck_occurrence_segment_lineage_version_positive",
        ),
        Index("ix_occurrence_segment_role", "role_id"),
        Index("ix_occurrence_segment_scene", "scene_id"),
        Index("ix_occurrence_segment_video_generation", "video_item_id", "source_generation"),
        Index("ix_occurrence_segment_mask_artifact", "mask_artifact_id"),
        # Branch safety (C1-F2) is enforced by the repository revision CAS (one
        # concurrent supersede wins, the loser CASes 0 rows and rolls back), by
        # the UNIQUE(workspace_id, logical_id, lineage_version) index below (no
        # duplicate lineage version) and by the ACTIVE partial unique identity
        # index (no duplicate active slot).  The plain superseded_by index here
        # supports the lineage walker; a branch/dangling state fabricated behind
        # the repository's back is detected by the walker fail-closed.
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id != id",
            name="ck_occurrence_segment_no_self_link",
        ),
        Index(
            "uq_occurrence_segment_successor",
            "superseded_by_id",
            unique=True,
            sqlite_where=sa_text("superseded_by_id IS NOT NULL"),
        ),
        Index(
            "uq_occurrence_segment_active_lineage",
            "workspace_id",
            "logical_id",
            unique=True,
            sqlite_where=sa_text("superseded_by_id IS NULL"),
        ),
        Index("ix_occurrence_segment_superseded_by", "superseded_by_id"),
        # C1-F2: explicit lineage versioning — UNIQUE(workspace_id, logical_id,
        # lineage_version) makes the current version determinable, rejects any
        # duplicate/branching lineage version and scopes each lineage to a
        # workspace (a logical_id is never reused across workspaces).
        Index(
            "uq_occurrence_segment_lineage_version",
            "workspace_id",
            "logical_id",
            "lineage_version",
            unique=True,
        ),
        Index("ix_occurrence_segment_logical_id", "logical_id"),
        # F3 (R1): NO full natural-key UniqueConstraint blocks versions — a
        # successor of the same occurrence or a newer generation must coexist.
        # Active/current rows are deduplicated by a PARTIAL unique index
        # (WHERE superseded_by_id IS NULL) so superseded history is excluded
        # and multiple versions/generations can live side by side.  SQLite
        # 3.45 reflects and enforces partial unique indexes (verified by
        # tests/test_s08_a02_structural_evidence_migration.py).
        Index(
            "uq_occurrence_segment_active_identity",
            "role_id",
            "scene_id",
            "start_frame",
            "end_frame",
            "source_generation",
            unique=True,
            sqlite_where=sa_text("superseded_by_id IS NULL"),
        ),
        # F9 (R1): workspace-scoped idempotency uniqueness — the idempotency
        # key is USED (not just stored); the natural key is never an
        # idempotency key.
        Index(
            "uq_occurrence_segment_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    #: Stable logical lineage id (F2): the segment's durable identity across
    #: corrections.  A correction creates a successor record that KEEPS the
    #: same ``logical_id`` (same lineage); the immutable ``id`` is the
    #: per-version evidence-record id.  Names are never the join key.
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: Lineage version (C1-F2): starts at 1 for the root row; a successor's
    #: version is ``predecessor.lineage_version + 1``.  UNIQUE(workspace_id,
    #: logical_id, lineage_version) makes the current version determinable and
    #: forbids duplicate/branching lineage versions.
    lineage_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sa_text("1"),
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(36),
        # C1-F7: structural evidence is durable historical truth — deleting a
        # role must NOT silently cascade-erase its occurrence-segment history.
        # RESTRICT + fail-closed delete (was CASCADE in the R1 draft).
        ForeignKey("object_role.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scene.id", ondelete="RESTRICT"), nullable=False
    )
    #: Stable display name of the segment (e.g. ``character``, ``phone``,
    #: ``hand``, ``face``).  Names are never the join key — the opaque ``id``
    #: is; ``name`` is a human label kept for deterministic ordering.
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    #: Canonical seven-kind ObjectRole taxonomy (derived from OBJECT_KINDS).
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="character")
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Generation ownership: the producing source generation; combined with
    #: ``source_job_id`` it is the durable production authority.  Only
    #: user/manual corrections may leave ``source_job_id`` NULL.
    source_generation: Mapped[str] = mapped_column(String(64), nullable=False)
    source_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job.id", ondelete="RESTRICT")
    )
    #: Structured prompt evidence — deterministic JSON with an array of
    #: points ``[{"x","y","label"}]`` and/or boxes ``[{"x","y","w","h"}]``
    #: (see ``app.schemas.structural_evidence`` canonical shape).  The
    #: historical flat ``bbox_*`` columns on ``object_occurrence`` remain;
    #: this field carries the prompt-evidence parallel.
    prompt_json: Mapped[str | None] = mapped_column(Text)
    #: Structured segmentation output JSON (deterministic shape; points/boxes
    #: or per-frame mask metadata).  Never a flattened single bounding box.
    segmentation_json: Mapped[str | None] = mapped_column(Text)
    #: Durable id-based link to the artifact row holding this segment's mask
    #: bytes (never path-guessed).  At least one mask reference per
    #: segmentation record is expected by the contract; indexed for lookup.
    mask_artifact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT")
    )
    algorithm: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="model"
    )
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provenance_json: Mapped[str | None] = mapped_column(Text)
    #: Scene-graph geometry persisted (never inferred at read time).
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="visible"
    )
    z_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Correction lineage: this row was superseded by ``superseded_by_id``
    #: (the successor segment).  NULL = the current/active row.  A historical
    #: row is never silently overwritten — a correction archives it and
    #: points it at its successor (auditable chain).
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "occurrence_segment.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"
        ),
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))

    role: Mapped[ObjectRole] = relationship(foreign_keys=[role_id])
    scene: Mapped[Scene] = relationship(foreign_keys=[scene_id])


class SegmentMotion(TimestampMixin, Base):
    """Durable per-segment motion/transform evidence record (S08-A02).

    Camera-relative or object-relative transform contract: a deterministic
    JSON blob (affine/homography parameters) with provenance + confidence, a
    temporal validity range and a durable reference to its point-correspondence
    / track / sparse-flow evidence (ids or deterministic JSON pointers).  For
    T01 this is CONTRACT-ONLY — no dense optical-flow engine runs here.
    """

    __tablename__ = "segment_motion"
    __table_args__ = (
        UniqueConstraint(
            "occurrence_segment_id",
            "transform_type",
            "start_frame",
            name="uq_segment_motion_segment_type_frame",
        ),
        CheckConstraint(
            "transform_type IN ('camera_relative','object_relative')",
            name="ck_segment_motion_transform_type",
        ),
        CheckConstraint(
            "start_frame >= 0", name="ck_segment_motion_start_frame_nonneg"
        ),
        CheckConstraint(
            "end_frame >= start_frame", name="ck_segment_motion_end_frame_ge_start"
        ),
        CheckConstraint(
            "start_time_ms >= 0", name="ck_segment_motion_start_time_ms_nonneg"
        ),
        CheckConstraint(
            "end_time_ms >= start_time_ms", name="ck_segment_motion_end_time_ms_ge_start"
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_segment_motion_confidence_range"
        ),
        CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_segment_motion_confidence_source",
        ),
        CheckConstraint(
            "length(algorithm) <= 64", name="ck_segment_motion_algorithm_len"
        ),
        CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_segment_motion_algorithm_version_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_segment_motion_idem_key_len"
        ),
        CheckConstraint("revision > 0", name="ck_segment_motion_revision_positive"),
        Index("ix_segment_motion_segment", "occurrence_segment_id"),
        # F9 (R1): workspace-scoped idempotency uniqueness; no dead
        # supersession column on motion (R1 F8 — real supersession lives on
        # occurrence_segment only).
        Index(
            "uq_segment_motion_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    occurrence_segment_id: Mapped[str] = mapped_column(
        String(36),
        # C1-F7: deleting a segment must NOT silently erase its motion evidence
        # history — RESTRICT + fail-closed delete (was CASCADE in R1 draft).
        ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: ``camera_relative`` = 2D affine/homography parameters of the camera for
    #: this segment; ``object_relative`` = object-relative motion
    #: (translation/rotation/scale or affine).  One row per (segment, type,
    #: start frame).
    transform_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Deterministic JSON blob of the transform parameters (canonical encoding).
    transform_json: Mapped[str] = mapped_column(Text, nullable=False)
    #: Durable reference (stable ids or deterministic JSON pointers) to the
    #: point-correspondence / track / sparse-flow evidence for this transform.
    point_track_flow_ref_json: Mapped[str | None] = mapped_column(Text)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="model"
    )
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provenance_json: Mapped[str | None] = mapped_column(Text)
    #: CAS/version token — bumped on every business mutation; stale => 409.
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))

    segment: Mapped[OccurrenceSegment] = relationship(foreign_keys=[occurrence_segment_id])


class SceneGraphOcclusion(TimestampMixin, Base):
    """Durable occlusion edge: occluder occurrence/segment -> occludee (S08-A02).

    FK-enforced source/target references to ``occurrence_segment``, temporal
    validity, provenance and confidence.  A correction archives the prior row
    via the self-FK (never a silent overwrite).
    """

    __tablename__ = "scene_graph_occlusion"
    __table_args__ = (
        UniqueConstraint(
            "occluder_segment_id",
            "occludee_segment_id",
            "start_frame",
            name="uq_scene_graph_occlusion_natural_key",
        ),
        CheckConstraint(
            "occluder_segment_id != occludee_segment_id",
            name="ck_scene_graph_occlusion_not_self",
        ),
        CheckConstraint(
            "start_frame >= 0", name="ck_scene_graph_occlusion_start_frame_nonneg"
        ),
        CheckConstraint(
            "end_frame >= start_frame", name="ck_scene_graph_occlusion_end_frame_ge_start"
        ),
        CheckConstraint(
            "start_time_ms >= 0", name="ck_scene_graph_occlusion_start_time_ms_nonneg"
        ),
        CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_scene_graph_occlusion_end_time_ms_ge_start",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_scene_graph_occlusion_confidence_range",
        ),
        CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_scene_graph_occlusion_confidence_source",
        ),
        CheckConstraint(
            "length(algorithm) <= 64", name="ck_scene_graph_occlusion_algorithm_len"
        ),
        CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_scene_graph_occlusion_algorithm_version_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_scene_graph_occlusion_idem_key_len",
        ),
        CheckConstraint("revision > 0", name="ck_scene_graph_occlusion_revision_positive"),
        Index("ix_scene_graph_occlusion_occluder", "occluder_segment_id"),
        Index("ix_scene_graph_occlusion_occludee", "occludee_segment_id"),
        Index("ix_scene_graph_occlusion_video", "video_item_id"),
        # F9 (R1): workspace-scoped idempotency uniqueness; no dead
        # supersession column on occlusion (R1 F8 — real supersession lives on
        # occurrence_segment only).
        Index(
            "uq_scene_graph_occlusion_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    occluder_segment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("occurrence_segment.id", ondelete="RESTRICT"), nullable=False
    )
    occludee_segment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("occurrence_segment.id", ondelete="RESTRICT"), nullable=False
    )
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="model"
    )
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provenance_json: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))

    occluder: Mapped[OccurrenceSegment] = relationship(
        foreign_keys=[occluder_segment_id]
    )
    occludee: Mapped[OccurrenceSegment] = relationship(
        foreign_keys=[occludee_segment_id]
    )


#: Backwards-friendly alias (structural-evidence nouns use ``OcclusionEdge``).
OcclusionEdge = SceneGraphOcclusion


class SceneGraphContact(TimestampMixin, Base):
    """Durable contact edge/event between two occurrence segments (S08-A02).

    E.g. hand<->phone or character<->phone: both endpoints are real FKs to
    ``occurrence_segment`` with RESTRICT delete, temporal validity,
    provenance/confidence and a stable contact kind.
    """

    __tablename__ = "scene_graph_contact"
    __table_args__ = (
        UniqueConstraint(
            "source_segment_id",
            "target_segment_id",
            "contact_kind",
            "start_frame",
            name="uq_scene_graph_contact_natural_key",
        ),
        CheckConstraint(
            "source_segment_id != target_segment_id",
            name="ck_scene_graph_contact_not_self",
        ),
        CheckConstraint(
            CONTACT_KIND_CHECK_SQL, name="ck_scene_graph_contact_kind"
        ),
        CheckConstraint(
            "start_frame >= 0", name="ck_scene_graph_contact_start_frame_nonneg"
        ),
        CheckConstraint(
            "end_frame >= start_frame", name="ck_scene_graph_contact_end_frame_ge_start"
        ),
        CheckConstraint(
            "start_time_ms >= 0", name="ck_scene_graph_contact_start_time_ms_nonneg"
        ),
        CheckConstraint(
            "end_time_ms >= start_time_ms",
            name="ck_scene_graph_contact_end_time_ms_ge_start",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_scene_graph_contact_confidence_range",
        ),
        CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_scene_graph_contact_confidence_source",
        ),
        CheckConstraint(
            "length(algorithm) <= 64", name="ck_scene_graph_contact_algorithm_len"
        ),
        CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_scene_graph_contact_algorithm_version_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_scene_graph_contact_idem_key_len"
        ),
        CheckConstraint("revision > 0", name="ck_scene_graph_contact_revision_positive"),
        Index("ix_scene_graph_contact_source", "source_segment_id"),
        Index("ix_scene_graph_contact_target", "target_segment_id"),
        Index("ix_scene_graph_contact_video", "video_item_id"),
        # F9 (R1): workspace-scoped idempotency uniqueness; no dead
        # supersession column on contact (R1 F8 — real supersession lives on
        # occurrence_segment only).
        Index(
            "uq_scene_graph_contact_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    source_segment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("occurrence_segment.id", ondelete="RESTRICT"), nullable=False
    )
    target_segment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("occurrence_segment.id", ondelete="RESTRICT"), nullable=False
    )
    contact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="model"
    )
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provenance_json: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))

    source: Mapped[OccurrenceSegment] = relationship(foreign_keys=[source_segment_id])
    target: Mapped[OccurrenceSegment] = relationship(foreign_keys=[target_segment_id])


#: Backwards-friendly alias (structural-evidence nouns use ``ContactEdge``).
ContactEdge = SceneGraphContact


class ProjectCastMapping(TimestampMixin, Base):
    """Project Cast Mapping pins an Object Role to an immutable Pack Version (S07-T01).

    - One mapping per (project, object_role) is expected; enforced via unique
      constraint on (project_id, object_role_id) fail-closed.
    - Immutable pin = pack_version_id FK to character_pack_version.id (immutable row identity);
      new publish creates NEW pack_version row, old mapping FK still points old row.
    - character_id is denormalized guard FK to character.id to enforce same-workspace
      consistency (pack_version.character_id must equal character_id).
    - Idempotency: UNIQUE(workspace_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
      equivalent replay returns existing, materially different payload -> conflict.
    - All FKs ondelete RESTRICT fail closed; revision >0 CAS.
    """

    __tablename__ = "project_cast_mapping"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_project_cast_mapping_revision_positive"),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_project_cast_mapping_idempotency_key_len",
        ),
        UniqueConstraint(
            "project_id", "object_role_id", name="uq_project_cast_project_role"
        ),
        Index("ix_project_cast_mapping_workspace", "workspace_id"),
        Index("ix_project_cast_mapping_project", "project_id"),
        Index("ix_project_cast_mapping_role", "object_role_id"),
        Index("ix_project_cast_mapping_pack_version", "pack_version_id"),
        Index("ix_project_cast_mapping_character", "character_id"),
        Index(
            "uq_project_cast_mapping_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    object_role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="RESTRICT"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("character.id", ondelete="RESTRICT"), nullable=False
    )
    pack_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("character_pack_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    workspace: Mapped[Workspace] = relationship()
    project: Mapped[Project] = relationship()
    object_role: Mapped[ObjectRole] = relationship()
    character: Mapped[Character] = relationship()
    pack_version: Mapped[CharacterPackVersion] = relationship()


class ReskinConfig(TimestampMixin, Base):
    """Durable Reskin parameter contract pinned to a Project Cast Mapping (S09-T01).

    - One config per (project, object_role): unique constraint fail-closed.
    - pack_version_id FK RESTRICT to character_pack_version.id — the immutable
      pin identity is inherited from the referenced ProjectCastMapping; new
      publishes create NEW pack_version rows and never mutate this FK (S07
      version isolation preserved).
    - params_json stores the transform contract validated fail-closed by
      app.persistence.reskin_config BEFORE any write (anchor {x,y} in [0,1],
      scale > 0, fit_mode in contain|cover|stretch, clip_mode in
      asset_alpha|original_mask|intersection, offset, rotation_offset_deg,
      opacity in [0,1]).
    - Idempotency: UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL —
      equivalent replay returns existing row, materially different payload → 409.
    - revision CAS > 0; all FKs ondelete RESTRICT fail closed.
    """

    __tablename__ = "reskin_config"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_reskin_config_revision_positive"),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_reskin_config_idempotency_key_len",
        ),
        UniqueConstraint(
            "project_id", "object_role_id", name="uq_reskin_config_project_role"
        ),
        Index("ix_reskin_config_workspace", "workspace_id"),
        Index("ix_reskin_config_project", "project_id"),
        Index("ix_reskin_config_role", "object_role_id"),
        Index("ix_reskin_config_pack_version", "pack_version_id"),
        Index("ix_reskin_config_mapping", "cast_mapping_id"),
        Index(
            "uq_reskin_config_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    object_role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="RESTRICT"), nullable=False
    )
    cast_mapping_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("project_cast_mapping.id", ondelete="RESTRICT"),
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("character.id", ondelete="RESTRICT"), nullable=False
    )
    pack_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("character_pack_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    #: S09-T00-I01 additive pins: this reskin contract is bound to exactly one
    #: versioned StructuralLockManifest (the structural authority it was
    #: derived from).  Optional until a lock manifest exists for the video;
    #: RESTRICT delete — a referenced lock can never be silently erased.
    structural_lock_manifest_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("structural_lock_manifest.id", ondelete="RESTRICT"),
    )
    #: Frozen CompatibilityPolicy / threshold-policy version string (bounded,
    #: backend-owned semantics; e.g. ``structural-thresholds-v1``).
    lock_policy_version: Mapped[str | None] = mapped_column(String(64))

    workspace: Mapped[Workspace] = relationship()
    project: Mapped[Project] = relationship()
    object_role: Mapped[ObjectRole] = relationship()
    cast_mapping: Mapped[ProjectCastMapping] = relationship()
    character: Mapped[Character] = relationship()
    pack_version: Mapped[CharacterPackVersion] = relationship()
    structural_lock_manifest: Mapped[StructuralLockManifest | None] = relationship()


class ApplyCheckpoint(TimestampMixin, Base):
    """Immutable append-only apply checkpoint (S09 schema-only for T06).

    T06 writes rows via app.persistence.apply_checkpoint; this class owns the
    storage shape ONLY. Rows are never UPDATEd or DELETEd: revision stays 1,
    snapshot_json + checkpoint_hash freeze the approved state for S10 full-apply.
    """

    __tablename__ = "apply_checkpoint"
    __table_args__ = (
        CheckConstraint("revision = 1", name="ck_apply_checkpoint_immutable_revision"),
        CheckConstraint(
            "length(checkpoint_hash) = 64",
            name="ck_apply_checkpoint_hash_len",
        ),
        Index("ix_apply_checkpoint_workspace", "workspace_id"),
        Index("ix_apply_checkpoint_project", "project_id"),
        Index("ix_apply_checkpoint_created", "created_at"),
        Index(
            "uq_apply_checkpoint_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    reskin_config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reskin_config.id", ondelete="RESTRICT"), nullable=False
    )
    reskin_config_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    pack_version_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    loop_hashes_json: Mapped[str] = mapped_column(Text, nullable=False)
    timebase_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    checkpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    #: S09-T00-I01 additive pins (immutable checkpoint): the approved apply
    #: snapshot freezes the StructuralLockManifest version it was validated
    #: against plus the policy/threshold version.  RESTRICT delete — an
    #: approved checkpoint never loses its structural authority silently.
    structural_lock_manifest_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("structural_lock_manifest.id", ondelete="RESTRICT"),
    )
    lock_policy_version: Mapped[str | None] = mapped_column(String(64))


class StructuralLockManifest(TimestampMixin, Base):
    """Versioned structural lock manifest per Video Item (S09-T00-I01).

    TARGET_PROFILE §4 P0-1: persist a StructuralLockManifest per Video Item.
    One manifest freezes the deterministic reconstruction contract for one
    source generation of a video item: exact frame count / timebase, shot
    order, z-order and contact topology fingerprints, the frozen threshold
    policy version (§8) and a full ``manifest_json`` payload validated
    fail-closed by ``app.persistence.structural_lock`` before any write.

    - Versioning: ``version`` starts at 1; creating a new manifest for the
      same (workspace, project, video_item, source_generation) supersedes the
      previous version — the old row is archived with status ``superseded``
      and ``superseded_by_id`` pointing at its successor. History is never
      overwritten or erased.
    - Natural key UNIQUE(workspace_id, project_id, video_item_id,
      source_generation, version) makes the current version determinable.
    - Idempotency: UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL;
      equivalent replay returns the existing row, materially different
      payload → conflict.
    - Status lifecycle: draft → active → superseded (or voided); CHECK-bound.
    - All FKs ondelete RESTRICT fail closed; revision CAS > 0.
    """

    __tablename__ = "structural_lock_manifest"
    __table_args__ = (
        CheckConstraint(
            "version >= 1", name="ck_structural_lock_manifest_version_positive"
        ),
        CheckConstraint(
            "length(source_generation) BETWEEN 1 AND 64",
            name="ck_structural_lock_manifest_source_generation_len",
        ),
        CheckConstraint(
            "length(policy_version) BETWEEN 1 AND 64",
            name="ck_structural_lock_manifest_policy_version_len",
        ),
        CheckConstraint(
            "length(manifest_hash) = 64",
            name="ck_structural_lock_manifest_hash_len",
        ),
        CheckConstraint(
            "status IN ('draft','active','superseded','voided')",
            name="ck_structural_lock_manifest_status",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_structural_lock_manifest_idem_key_len",
        ),
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id != id",
            name="ck_structural_lock_manifest_no_self_link",
        ),
        CheckConstraint("revision > 0", name="ck_structural_lock_manifest_revision_positive"),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "video_item_id",
            "source_generation",
            "version",
            name="uq_structural_lock_manifest_natural_key",
        ),
        Index("ix_structural_lock_manifest_workspace", "workspace_id"),
        Index("ix_structural_lock_manifest_project", "project_id"),
        Index("ix_structural_lock_manifest_video", "video_item_id"),
        Index("ix_structural_lock_manifest_superseded_by", "superseded_by_id"),
        Index(
            "uq_structural_lock_manifest_active",
            "workspace_id",
            "project_id",
            "video_item_id",
            "source_generation",
            unique=True,
            sqlite_where=sa_text("status IN ('draft','active')"),
        ),
        Index(
            "uq_structural_lock_manifest_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    #: The locked video item (P0-1: one manifest per Video Item).
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    #: Producing source generation this manifest locks (same canonical values
    #: as occurrence_segment.source_generation).
    source_generation: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    #: Frozen threshold/compatibility policy version (TARGET_PROFILE §8:
    #: thresholds calibrated from evidence, then frozen in a versioned policy).
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Deterministic sha256 hex over canonical manifest_json — integrity pin
    #: for the frozen contract.
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Full fail-closed-validated manifest payload (frame count/timebase,
    #: shot list, fingerprints, per-segment lock summary).
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    #: Correction lineage: the successor manifest that replaced this row.
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("structural_lock_manifest.id", ondelete="RESTRICT"),
    )

    workspace: Mapped[Workspace] = relationship()
    project: Mapped[Project] = relationship()
    video_item: Mapped[VideoItem] = relationship()
    superseded_by: Mapped[StructuralLockManifest | None] = relationship(remote_side=[id])
    render_routes: Mapped[list[SegmentRenderRoute]] = relationship(
        back_populates="manifest",
        cascade="save-update, merge, refresh-expire, expunge",
    )


class SegmentRenderRoute(TimestampMixin, Base):
    """Persisted renderer route + contact anchors per occurrence segment.

    TARGET_PROFILE §4 P0-7: renderer choice is PERSISTED PER OCCURRENCE
    SEGMENT (never inferred at read time) from the EXACT enum {pose_swap,
    sprite_affine, mesh_warp, part_rig, controlled_redraw} plus §4 P0-4
    contact anchors in NORMALIZED x/y ∈ [0,1] coordinates (per occurrence
    segment).  Each row carries its own provenance JSON evidence so Demo
    review can audit WHY a route was chosen and override it later by writing
    a NEW route row (history preserved via the natural key frame range).

    - Route CHECK derives from RENDERER_ROUTES (single authority, exact five).
    - Anchor coordinates are CHECK-bound into [0,1]; finiteness is enforced
      at the repository layer (SQLite binds NaN as NULL, so range CHECKs are
      authoritative only for real numbers — repository rejects non-finite).
    - Natural key UNIQUE(occurrence_segment_id, route, start_frame) keeps one
      decision per segment/frame-range/route triple.
    - Workspace-scoped idempotency uniqueness like every sibling table.
    """

    __tablename__ = "segment_render_route"
    __table_args__ = (
        CheckConstraint(RENDERER_ROUTE_CHECK_SQL, name="ck_segment_render_route_route"),
        CheckConstraint(
            "anchor_x >= 0.0 AND anchor_x <= 1.0",
            name="ck_segment_render_route_anchor_x_range",
        ),
        CheckConstraint(
            "anchor_y >= 0.0 AND anchor_y <= 1.0",
            name="ck_segment_render_route_anchor_y_range",
        ),
        CheckConstraint(
            "start_frame >= 0", name="ck_segment_render_route_start_frame_nonneg"
        ),
        CheckConstraint(
            "end_frame >= start_frame",
            name="ck_segment_render_route_end_frame_ge_start",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_segment_render_route_confidence_range",
        ),
        CheckConstraint(
            "confidence_source IN ('model','detector','user','manual','derived')",
            name="ck_segment_render_route_confidence_source",
        ),
        CheckConstraint(
            "length(algorithm) <= 64", name="ck_segment_render_route_algorithm_len"
        ),
        CheckConstraint(
            "length(algorithm_version) <= 64",
            name="ck_segment_render_route_algorithm_version_len",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255",
            name="ck_segment_render_route_idem_key_len",
        ),
        CheckConstraint("revision > 0", name="ck_segment_render_route_revision_positive"),
        UniqueConstraint(
            "occurrence_segment_id",
            "route",
            "start_frame",
            name="uq_segment_render_route_natural_key",
        ),
        Index("ix_segment_render_route_segment", "occurrence_segment_id"),
        Index("ix_segment_render_route_video", "video_item_id"),
        Index("ix_segment_render_route_route", "route"),
        Index("ix_segment_render_route_manifest", "structural_lock_manifest_id"),
        Index(
            "uq_segment_render_route_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    #: The locked occurrence segment (P0-4/P0-7: per occurrence segment).
    occurrence_segment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: Optional owning lock manifest (routes may exist pre-manifest; when a
    #: manifest pins them they become part of its frozen contract).
    structural_lock_manifest_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("structural_lock_manifest.id", ondelete="RESTRICT"),
    )
    #: Exact renderer-route enum value (CHECK-derived from RENDERER_ROUTES).
    route: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Contact anchor in normalized [0,1] source-frame coordinates.
    anchor_x: Mapped[float] = mapped_column(Float, nullable=False)
    anchor_y: Mapped[float] = mapped_column(Float, nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str | None] = mapped_column(String(64))
    algorithm_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="model"
    )
    #: Why this route was chosen (deterministic JSON: residual metrics,
    #: escalation trigger, benchmark refs).  Fail-closed finite-only JSON at
    #: the repository boundary.
    provenance_json: Mapped[str | None] = mapped_column(Text)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    idempotency_key: Mapped[str | None] = mapped_column(String(255))

    occurrence_segment: Mapped[OccurrenceSegment] = relationship()
    manifest: Mapped[StructuralLockManifest | None] = relationship(
        foreign_keys=[structural_lock_manifest_id],
        back_populates="render_routes",
    )


class S09Correction(TimestampMixin, Base):
    """Durable archive of ONE targeted demo-review correction (S09-T05A).

    A correction is created ``pending`` with its computed affected scope
    (``impact_json`` — the exact loop/layer/segment regeneration scope),
    then explicitly CONFIRMED: the targeted mutation through the verified
    durable core (mask/z_order → OccurrenceSegment supersede lineage,
    contact → SceneGraphContact CAS, mesh_parts → SegmentMotion CAS,
    route_override → a NEW SegmentRenderRoute history row) plus the result
    archive are committed in ONE transaction.  The natural key replays the
    SAME correction for duplicate/concurrent/restart submissions; the
    revision CAS makes confirm/cancel exactly-once and fail-closed.

    - ``correction_kind`` CHECK derives from S09_CORRECTION_KINDS (single
      authority); ``status`` CHECK from S09_CORRECTION_STATUSES.
    - ``request_json`` / ``impact_json`` / ``result_json`` are canonical
      finite-only JSON validated fail-closed by the repository BEFORE any
      write.
    - Idempotency: UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL —
      workspace-scoped like every sibling table; equivalent replay returns
      the existing row, materially different payload → conflict.
    - Natural key UNIQUE(workspace_id, natural_key) WHERE NOT NULL — the
      content-derived identity (kind + target ids + payload hash).
    - All FKs ondelete RESTRICT fail closed; revision CAS > 0.
    """

    __tablename__ = "s09_correction"
    __table_args__ = (
        CheckConstraint(
            "correction_kind IN ('mask','z_order','contact','mesh_parts',"
            "'route_override')",
            name="ck_s09_correction_kind",
        ),
        CheckConstraint(
            "status IN ('pending','applied','cancelled')",
            name="ck_s09_correction_status",
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s09_correction_idem_key_len"
        ),
        CheckConstraint(
            "length(natural_key) <= 255", name="ck_s09_correction_natural_key_len"
        ),
        CheckConstraint("revision > 0", name="ck_s09_correction_revision_positive"),
        Index(
            "uq_s09_correction_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_s09_correction_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_s09_correction_video_status", "video_item_id", "status"),
        Index("ix_s09_correction_segment", "occurrence_segment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    #: The locked occurrence segment this correction targets (NULL only for
    #: video-scope kinds that carry their own segment references inside
    #: request_json).
    occurrence_segment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
    )
    correction_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=sa_text("'pending'"),
    )
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    impact_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    natural_key: Mapped[str | None] = mapped_column(String(255))

    segment: Mapped[OccurrenceSegment | None] = relationship()

# ── S10 FullApply domain (S10-T01A) ─────────────────────────────────────────

S10_FULL_APPLY_RUN_STATUSES = (
    "pending",
    "running",
    "verifying",
    "completed",
    "failed",
    "cancelled",
)
S10_FULL_APPLY_CHUNK_STATES = (
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
)
S10_FULL_APPLY_PUBLICATION_STATES = (
    "pending",
    "verifying",
    "completed",
    "failed",
)


class S10FullApplyRun(TimestampMixin, Base):
    """Durable FullApply run aggregate (S10-T01A)."""

    __tablename__ = "s10_full_apply_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','verifying','completed','failed','cancelled')",
            name="ck_s10_run_status",
        ),
        CheckConstraint("length(plan_id) = 64", name="ck_s10_run_plan_id_len"),
        CheckConstraint("length(plan_hash) = 64", name="ck_s10_run_plan_hash_len"),
        CheckConstraint(
            "length(apply_checkpoint_hash) = 64", name="ck_s10_run_checkpoint_hash_len"
        ),
        CheckConstraint(
            "apply_checkpoint_revision >= 1", name="ck_s10_run_checkpoint_revision_positive"
        ),
        CheckConstraint("frame_count >= 1", name="ck_s10_run_frame_count_positive"),
        CheckConstraint("fps_num IS NULL OR fps_num > 0", name="ck_s10_run_fps_num_positive"),
        CheckConstraint("fps_den IS NULL OR fps_den > 0", name="ck_s10_run_fps_den_positive"),
        CheckConstraint("attempt >= 1", name="ck_s10_run_attempt_positive"),
        CheckConstraint("revision > 0", name="ck_s10_run_revision_positive"),
        CheckConstraint(
            "length(natural_key) <= 255", name="ck_s10_run_natural_key_len"
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s10_run_idempotency_key_len"
        ),
        Index(
            "uq_s10_run_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_s10_run_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_s10_run_workspace", "workspace_id"),
        Index("ix_s10_run_project", "project_id"),
        Index("ix_s10_run_video", "video_item_id"),
        Index("ix_s10_run_checkpoint", "apply_checkpoint_id"),
        Index("ix_s10_run_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    apply_checkpoint_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("apply_checkpoint.id", ondelete="RESTRICT"), nullable=False
    )
    apply_checkpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    apply_checkpoint_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fps_num: Mapped[int | None] = mapped_column(Integer)
    fps_den: Mapped[int | None] = mapped_column(Integer)
    chunk_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    natural_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    workspace: Mapped[Workspace] = relationship()
    project: Mapped[Project] = relationship()
    video_item: Mapped[VideoItem] = relationship()
    checkpoint: Mapped[ApplyCheckpoint] = relationship()


class S10FullApplyChunk(TimestampMixin, Base):
    """Deterministic shot/layer chunk (S10-T01A)."""

    __tablename__ = "s10_full_apply_chunk"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_s10_chunk_index_nonneg"),
        CheckConstraint("order_index >= 0", name="ck_s10_chunk_order_nonneg"),
        CheckConstraint("length(shot_id) > 0", name="ck_s10_chunk_shot_nonempty"),
        CheckConstraint("core_start_frame >= 0", name="ck_s10_chunk_core_start_nonneg"),
        CheckConstraint(
            "core_end_frame >= core_start_frame", name="ck_s10_chunk_core_end_ge_start"
        ),
        CheckConstraint("overlap_before >= 0", name="ck_s10_chunk_overlap_before_nonneg"),
        CheckConstraint("overlap_after >= 0", name="ck_s10_chunk_overlap_after_nonneg"),
        CheckConstraint("length(content_hash) = 64", name="ck_s10_chunk_content_hash_len"),
        CheckConstraint(
            "state IN ('pending','running','completed','failed','skipped')",
            name="ck_s10_chunk_state",
        ),
        CheckConstraint("attempt >= 1", name="ck_s10_chunk_attempt_positive"),
        CheckConstraint("verified IN (0, 1)", name="ck_s10_chunk_verified_bool"),
        CheckConstraint("revision > 0", name="ck_s10_chunk_revision_positive"),
        CheckConstraint(
            "length(natural_key) <= 255", name="ck_s10_chunk_natural_key_len"
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s10_chunk_idempotency_key_len"
        ),
        UniqueConstraint(
            "run_id", "chunk_index", "attempt", name="uq_s10_chunk_run_index_attempt"
        ),
        Index(
            "uq_s10_chunk_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_s10_chunk_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_s10_chunk_run", "run_id"),
        Index("ix_s10_chunk_state", "state"),
        Index("ix_s10_chunk_shot", "shot_id"),
        Index("ix_s10_chunk_run_state", "run_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("s10_full_apply_run.id", ondelete="RESTRICT"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    shot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    layer_id: Mapped[str | None] = mapped_column(String(128))
    object_role_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("object_role.id", ondelete="RESTRICT")
    )
    core_start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    core_end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap_before: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overlap_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    artifact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT")
    )
    verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    natural_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    run: Mapped[S10FullApplyRun] = relationship(back_populates="chunks")
    artifact: Mapped[Artifact | None] = relationship()
    object_role: Mapped[ObjectRole | None] = relationship()


S10FullApplyRun.chunks = relationship(
    "S10FullApplyChunk",
    back_populates="run",
    order_by="S10FullApplyChunk.order_index",
    cascade="save-update, merge, refresh-expire, expunge",
)


class S10FullApplyPublication(TimestampMixin, Base):
    """Atomic publish of one verified full output (S10-T01A)."""

    __tablename__ = "s10_full_apply_publication"
    __table_args__ = (
        CheckConstraint("length(content_hash) = 64", name="ck_s10_pub_content_hash_len"),
        CheckConstraint("frame_count >= 1", name="ck_s10_pub_frame_count_positive"),
        CheckConstraint("length(checkpoint_hash) = 64", name="ck_s10_pub_checkpoint_hash_len"),
        CheckConstraint(
            "checkpoint_revision >= 1", name="ck_s10_pub_checkpoint_revision_positive"
        ),
        CheckConstraint(
            "state IN ('pending','verifying','completed','failed')",
            name="ck_s10_pub_state",
        ),
        CheckConstraint("revision > 0", name="ck_s10_pub_revision_positive"),
        CheckConstraint(
            "length(natural_key) <= 255", name="ck_s10_pub_natural_key_len"
        ),
        CheckConstraint(
            "length(idempotency_key) <= 255", name="ck_s10_pub_idempotency_key_len"
        ),
        UniqueConstraint("run_id", "content_hash", name="uq_s10_pub_run_content_hash"),
        Index(
            "uq_s10_pub_natural",
            "workspace_id",
            "natural_key",
            unique=True,
            sqlite_where=sa_text("natural_key IS NOT NULL"),
        ),
        Index(
            "uq_s10_pub_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            sqlite_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_s10_pub_run", "run_id"),
        Index("ix_s10_pub_artifact", "artifact_id"),
        Index("ix_s10_pub_state", "state"),
        Index("ix_s10_pub_checkpoint", "checkpoint_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("s10_full_apply_run.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifact.id", ondelete="RESTRICT"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("apply_checkpoint.id", ondelete="RESTRICT"), nullable=False
    )
    checkpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    natural_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=sa_text("1"), nullable=False
    )

    run: Mapped[S10FullApplyRun] = relationship(back_populates="publications")
    artifact: Mapped[Artifact] = relationship()
    checkpoint: Mapped[ApplyCheckpoint] = relationship()


S10FullApplyRun.publications = relationship(
    "S10FullApplyPublication",
    back_populates="run",
    order_by="S10FullApplyPublication.created_at",
    cascade="save-update, merge, refresh-expire, expunge",
)


# ── QC domain (S11-T02A) ────────────────────────────────────────────────────

#: Canonical QCItem workflow states (lane-A QC_DOMAIN_CONTRACT §1.1): a QC
#: issue is created ``open``, may be ``acknowledged`` while being worked, and
#: ends ``resolved`` (fixed) or ``dismissed`` (rejected).  EXACTLY these four
#: values are authoritative across ORM CHECK, migration CHECK and Pydantic —
#: never a second copy of the taxonomy.
QC_ITEM_STATUSES = ("open", "acknowledged", "resolved", "dismissed")
#: SQL literal for the ``qc_item.status`` CHECK, DERIVED from
#: ``QC_ITEM_STATUSES`` (single authority — CONTACT_KIND_CHECK_SQL pattern).
QC_ITEM_STATUS_CHECK_SQL = (
    "status IN (" + ",".join("'" + s + "'" for s in QC_ITEM_STATUSES) + ")"
)
#: Canonical QCItem severities: ``blocker`` stops readiness (may only end
#: resolved/acknowledged/open — NEVER dismissed, lane-A §1.3 rule 2),
#: ``warning`` and ``info`` are non-blocking.
QC_ITEM_SEVERITIES = ("blocker", "warning", "info")
#: SQL literal for the ``qc_item.severity`` CHECK, DERIVED from
#: ``QC_ITEM_SEVERITIES``.
QC_ITEM_SEVERITY_CHECK_SQL = (
    "severity IN (" + ",".join("'" + s + "'" for s in QC_ITEM_SEVERITIES) + ")"
)
#: Canonical QCItem categories — EXACTLY the binding codes: the 8 overlay
#: codes (Decision B, overlay §S11 L370-371: trajectory_drift, cut_drift,
#: contact_break, z_order_error, silhouette_clipping, identity_drift,
#: edge_halo, temporal_flicker) plus the 2 audio codes (Decision D, T03E:
#: audio_missing, av_sync_drift) — the S09/S10 reviewable failure classes.
QC_ITEM_CATEGORIES = (
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
#: SQL literal for the ``qc_item.category`` CHECK, DERIVED from
#: ``QC_ITEM_CATEGORIES``.
QC_ITEM_CATEGORY_CHECK_SQL = (
    "category IN (" + ",".join("'" + c + "'" for c in QC_ITEM_CATEGORIES) + ")"
)
#: Canonical QCItem reason codes — EXACTLY the binding codes, kept as its
#: own tuple because ``reason_code`` is a NATURAL-KEY discriminator column:
#: 8 overlay codes (Decision B: trajectory_drift, cut_drift, contact_break,
#: z_order_error, silhouette_clipping, identity_drift, edge_halo,
#: temporal_flicker) + 2 audio codes (Decision D: audio_missing,
#: av_sync_drift).  1:1 with ``QC_ITEM_CATEGORIES``.
QC_REASON_CODES = (
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
#: SQL literal for the ``qc_item.reason_code`` CHECK, DERIVED from
#: ``QC_REASON_CODES``.
QC_REASON_CODE_CHECK_SQL = (
    "reason_code IN (" + ",".join("'" + r + "'" for r in QC_REASON_CODES) + ")"
)
#: SQL literal for the ``qc_item.confidence_source`` CHECK, DERIVED from the
#: existing ``OCCURRENCE_CONFIDENCE_SOURCES`` taxonomy (single authority —
#: a QC observation is a detection/observation and shares the source set).
QC_CONFIDENCE_SOURCE_CHECK_SQL = (
    "confidence_source IN ("
    + ",".join("'" + c + "'" for c in OCCURRENCE_CONFIDENCE_SOURCES)
    + ")"
)
#: SQL literal for the segment pair-null CHECK: ``segment_row_id`` and
#: ``segment_logical_id`` must be BOTH NULL (video-level issue) or BOTH set
#: (segment-anchored issue) — a partial pair is a domain error and is frozen
#: at DB level.
QC_ITEM_SEGMENT_PAIR_NULL_CHECK_SQL = (
    "(segment_row_id IS NULL AND segment_logical_id IS NULL) OR "
    "(segment_row_id IS NOT NULL AND segment_logical_id IS NOT NULL)"
)
#: SQL literal for the lane-A §1.3 rule 2 CHECK: a ``blocker`` may NEVER be
#: ``dismissed`` — fail-closed at DB level, not only in repository code.
QC_ITEM_BLOCKER_DISMISSED_CHECK_SQL = (
    "NOT (severity = 'blocker' AND status = 'dismissed')"
)


class QCItem(TimestampMixin, Base):
    """Durable QC issue record (S11-T02A, lane-A QC_DOMAIN_CONTRACT §1).

    The persistence tier of the QC domain, fail-closed and frozen at DB
    level:

    - natural-key UNIQUE over (workspace_id, project_id, video_item_id,
      layer_ref_type, layer_ref_id, reason_code, evidence_window_key) — every
      component is NOT NULL so SQLite NULL semantics can never bypass
      uniqueness;
    - ``segment_row_id`` is a REAL nullable FK to the immutable
      ``occurrence_segment.id`` (the durable join key, RESTRICT) while
      ``segment_logical_id`` is the scoped lineage VALUE and deliberately NOT
      an FK; the pair-null CHECK forces both-or-none;
    - layer references, ``evidence_window_key`` (canonical stable key/hash
      materialized as its own column — the uniqueness mechanism, never only
      inside evidence_json), ``evidence_json`` (schema-versioned +
      content-derived), detector identity, confidence/confidence_source and
      ``checkpoint_ref`` are all NOT NULL;
    - every enum CHECK is derived from its single Python tuple
      (CONTACT_KIND_CHECK_SQL pattern) and blocker+dismissed is rejected by a
      real DB CHECK (lane-A §1.3 rule 2).
    """

    __tablename__ = "qc_item"
    __table_args__ = (
        CheckConstraint(
            QC_ITEM_STATUS_CHECK_SQL, name="ck_qc_item_status"
        ),
        CheckConstraint(
            QC_ITEM_SEVERITY_CHECK_SQL, name="ck_qc_item_severity"
        ),
        CheckConstraint(
            QC_ITEM_CATEGORY_CHECK_SQL, name="ck_qc_item_category"
        ),
        CheckConstraint(
            QC_REASON_CODE_CHECK_SQL, name="ck_qc_item_reason_code"
        ),
        CheckConstraint(
            QC_CONFIDENCE_SOURCE_CHECK_SQL, name="ck_qc_item_confidence_source"
        ),
        CheckConstraint(
            QC_ITEM_SEGMENT_PAIR_NULL_CHECK_SQL,
            name="ck_qc_item_segment_pair_null",
        ),
        CheckConstraint(
            QC_ITEM_BLOCKER_DISMISSED_CHECK_SQL,
            name="ck_qc_item_blocker_not_dismissed",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_qc_item_confidence_range",
        ),
        CheckConstraint("revision > 0", name="ck_qc_item_revision_positive"),
        CheckConstraint(
            "length(layer_ref_type) BETWEEN 1 AND 32",
            name="ck_qc_item_layer_ref_type_len",
        ),
        CheckConstraint(
            "length(layer_ref_id) BETWEEN 1 AND 64",
            name="ck_qc_item_layer_ref_id_len",
        ),
        CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 48",
            name="ck_qc_item_reason_code_len",
        ),
        CheckConstraint(
            "length(evidence_window_key) BETWEEN 1 AND 64",
            name="ck_qc_item_evidence_window_key_len",
        ),
        CheckConstraint(
            "length(evidence_json) >= 1", name="ck_qc_item_evidence_json_nonempty"
        ),
        CheckConstraint(
            "length(detector) BETWEEN 1 AND 64", name="ck_qc_item_detector_len"
        ),
        CheckConstraint(
            "length(detector_revision) BETWEEN 1 AND 64",
            name="ck_qc_item_detector_revision_len",
        ),
        CheckConstraint(
            "length(checkpoint_ref) BETWEEN 1 AND 64",
            name="ck_qc_item_checkpoint_ref_len",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "video_item_id",
            "layer_ref_type",
            "layer_ref_id",
            "reason_code",
            "evidence_window_key",
            name="uq_qc_item_natural_key",
        ),
        Index("ix_qc_item_workspace", "workspace_id"),
        Index("ix_qc_item_project", "project_id"),
        Index("ix_qc_item_video", "video_item_id"),
        Index("ix_qc_item_segment", "segment_row_id"),
        Index("ix_qc_item_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="RESTRICT"), nullable=False
    )
    video_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_item.id", ondelete="RESTRICT"), nullable=False
    )
    #: The exact immutable occurrence row this QC issue is anchored to
    #: (S08-A02 ``occurrence_segment.id`` — the durable join key, never the
    #: lineage logical_id).  NULL for video-level issues; the pair-null CHECK
    #: keeps it consistent with ``segment_logical_id``.
    segment_row_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("occurrence_segment.id", ondelete="RESTRICT"),
    )
    #: Scoped lineage VALUE (the segment's ``logical_id``), denormalized for
    #: scoped lookup and deliberately NOT an FK — the logical_id is a lineage
    #: key, not a row id.
    segment_logical_id: Mapped[str | None] = mapped_column(String(64))
    #: Layer reference scope.  Video-level issues use ``video_item`` with
    #: ``layer_ref_id`` = video_item_id; part of the natural key so a
    #: layer-scoped issue can never collide with a video-scoped one.
    layer_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    layer_ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Canonical stable window key/hash materialized as its own column — the
    #: uniqueness mechanism; never ONLY inside ``evidence_json``.
    evidence_window_key: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Schema-versioned, content-derived evidence payload.  Deliberately NOT
    #: the uniqueness mechanism (``evidence_window_key`` is).
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    detector: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="model"
    )
    checkpoint_ref: Mapped[str] = mapped_column(String(64), nullable=False)
