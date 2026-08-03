"""SQLAlchemy ORM models for the approved S01 persistence contract.

These models mirror ``docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md``
exactly.  No Job/JobStep tables exist yet (deferred to S02-T01).  Models are
the storage layer only — they are never exported as API schemas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
    "CHANNEL_ROLES",
    "CHANNEL_STATUSES",
    "OWNER_TYPES",
    "PROJECT_STATUSES",
    "SCENE_STATUSES",
    "VIDEO_PIPELINE_STATES",
    "Base",
    "Artifact",
    "ArtifactOwner",
    "Channel",
    "LegacyImport",
    "Project",
    "Scene",
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
SCENE_STATUSES = ("pending", "draft", "approved")
ARTIFACT_KINDS = ("video", "image", "audio", "document", "other")
ARTIFACT_STATES = ("staging", "ready", "trash", "missing", "failed")
OWNER_TYPES = ("channel", "project", "video_item", "scene", "artifact")
LEGACY_IMPORT_STATUSES = ("previewed", "importing", "completed", "failed", "rolled_back")


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


class Channel(ArchivableMixin, Base):
    """Source or production channel owned by a workspace."""

    __tablename__ = "channel"
    __table_args__ = (
        UniqueConstraint("workspace_id", "role", "name", name="uq_channel_workspace_role_name"),
        UniqueConstraint(
            "workspace_id", "legacy_id", name="uq_channel_workspace_legacy_id"
        ),
        CheckConstraint("length(name) > 0", name="ck_channel_name_nonempty"),
        CheckConstraint("length(name) <= 200", name="ck_channel_name_len"),
        CheckConstraint("role IN ('source', 'production')", name="ck_channel_role"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_channel_status"),
        CheckConstraint("revision > 0", name="ck_channel_revision_positive"),
        Index("ix_channel_workspace_role_name", "workspace_id", "role", "name"),
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
