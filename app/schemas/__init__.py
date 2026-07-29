"""Pydantic schemas for MotionForge project data model."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ─── Enums ────────────────────────────────────────────────────────────────────

class ObjectKind(str, Enum):
    CHARACTER = "character"
    PROP = "prop"
    EFFECT = "effect"
    BACKGROUND = "background"


class SelectionMode(str, Enum):
    POINT = "point"         # Single positive click
    BBOX = "bounding_box"   # Bounding box selection


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ─── Video Metadata ──────────────────────────────────────────────────────────

class VideoMetadata(BaseModel):
    """Metadata extracted from source video via ffprobe."""
    width: int
    height: int
    fps: float
    duration_seconds: float
    total_frames: int
    codec: str
    has_audio: bool
    audio_codec: str | None = None
    file_size_bytes: int = 0
    file_path: str = ""


# ─── Scene ───────────────────────────────────────────────────────────────────

class SceneInfo(BaseModel):
    """A detected scene within the video."""
    scene_id: int
    start_frame: int
    end_frame: int
    start_time_sec: float
    end_time_sec: float
    duration_sec: float
    frame_count: int


# ─── Selection ────────────────────────────────────────────────────────────────

class SelectionInput(BaseModel):
    """User selection on a frame — point or bounding box."""
    mode: SelectionMode
    frame_index: int            # Absolute frame index in the scene
    x: float                    # Point x or bbox top-left x
    y: float                    # Point y or bbox top-left y
    width: float | None = None   # Bbox width (only for bbox mode)
    height: float | None = None  # Bbox height (only for bbox mode)


# ─── Motion Data ──────────────────────────────────────────────────────────────

class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class FrameMotion(BaseModel):
    """Motion data for a single frame."""
    frame_index: int
    centroid_x: float
    centroid_y: float
    bbox: BoundingBox
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation_deg: float = 0.0
    opacity: float = 1.0
    visibility: bool = True
    area: float = 0.0  # Mask area in pixels


class SceneMotion(BaseModel):
    """Aggregated motion data for an entire scene."""
    scene_id: int
    frames: list[FrameMotion] = Field(default_factory=list)
    reference_bbox: BoundingBox | None = None  # Bbox at selection frame


# ─── Object Tracking ─────────────────────────────────────────────────────────

class TrackedObject(BaseModel):
    """An object being tracked across a scene."""
    object_id: str
    name: str
    kind: ObjectKind = ObjectKind.CHARACTER
    selection: SelectionInput
    scene_id: int
    replacement_image: str | None = None  # Path to replacement PNG
    motion: SceneMotion | None = None


# ─── Project ──────────────────────────────────────────────────────────────────

class ProjectData(BaseModel):
    """Top-level project state, serializable to JSON."""
    version: str = "1.0.0"
    name: str
    source_video: str
    video_metadata: VideoMetadata | None = None
    scenes: list[SceneInfo] = Field(default_factory=list)
    objects: list[TrackedObject] = Field(default_factory=list)


# ─── Job ──────────────────────────────────────────────────────────────────────

class JobInfo(BaseModel):
    """Status of a background processing job."""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = ""
    result_path: str | None = None
    error: str | None = None
