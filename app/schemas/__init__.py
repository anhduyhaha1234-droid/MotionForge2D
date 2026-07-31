"""Pydantic schemas for MotionForge project data model.

Schema version 2.0.0 — adds tracking metadata, occlusion, confidence.
Backward compatible: can load v1.0.0 projects via migration.
"""

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


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


# ─── Replacement Config (from TRANSFORM_SPEC.md) ────────────────────────────

class FitMode(str, Enum):
    CONTAIN = "contain"
    COVER = "cover"
    STRETCH = "stretch"


class ClipMode(str, Enum):
    ASSET_ALPHA = "asset_alpha"
    ORIGINAL_MASK = "original_mask"
    INTERSECTION = "intersection"


class ReplacementMode(str, Enum):
    NONE = "none"
    STATIC_ASSET = "static_asset"
    FRAME_SEQUENCE = "frame_sequence"
    KEYFRAME_ASSETS = "keyframe_assets"


class Point2D(BaseModel):
    x: float = 0.0
    y: float = 0.0


class ReplacementConfig(BaseModel):
    """Replacement transform settings matching docs/TRANSFORM_SPEC.md."""
    mode: ReplacementMode = ReplacementMode.STATIC_ASSET
    asset_path: str = Field(default="", alias="assetPath")
    anchor: Point2D = Field(default_factory=Point2D)
    offset: Point2D = Field(default_factory=Point2D)
    scale: float = 1.0
    rotation_offset_deg: float = Field(default=0.0, alias="rotationOffsetDeg")
    opacity: float = 1.0
    fit_mode: FitMode = Field(default=FitMode.CONTAIN, alias="fitMode")
    clip_mode: ClipMode = Field(default=ClipMode.ASSET_ALPHA, alias="clipMode")

    model_config = {"populate_by_name": True}


# ─── Object Crop Manifest ────────────────────────────────────────────────────

class ObjectCrop(BaseModel):
    """A single crop image for a tracked object at a frame."""
    frame_index: int
    crop_path: str


class GalleryManifest(BaseModel):
    """Manifest listing all crop images for a tracked object."""
    object_id: str
    project_id: str
    thumbnail_path: str = ""
    crops: list[ObjectCrop] = Field(default_factory=list)


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
    """A detected scene within the video.

    Frame indexing: zero-based, start_frame and end_frame are INCLUSIVE.
    """
    scene_id: int
    start_frame: int        # inclusive, zero-based
    end_frame: int          # inclusive, zero-based
    start_time_sec: float
    end_time_sec: float
    duration_sec: float
    frame_count: int


class SceneStatus(str, Enum):
    PENDING = "pending"      # Chưa làm
    DRAFT = "draft"          # Đang sửa
    APPROVED = "approved"    # Đã duyệt


class SceneDetail(BaseModel):
    """Extended scene info with status and audio path."""
    scene_id: int
    start_frame: int
    end_frame: int
    start_time_sec: float
    end_time_sec: float
    duration_sec: float
    frame_count: int
    status: SceneStatus = SceneStatus.PENDING
    audio_path: str = ""         # relative path to scene audio file
    notes: str = ""


# ─── Selection ────────────────────────────────────────────────────────────────

class SelectionInput(BaseModel):
    """User selection on a frame — point or bounding box.

    Coordinates are in pixel units (origin = top-left of frame).
    frame_index is zero-based, absolute within the scene.
    """
    mode: SelectionMode
    frame_index: int            # Absolute frame index in the scene (zero-based)
    x: float                    # Point x or bbox top-left x (pixels)
    y: float                    # Point y or bbox top-left y (pixels)
    width: float | None = None  # Bbox width (only for bbox mode, pixels)
    height: float | None = None # Bbox height (only for bbox mode, pixels)


# ─── Motion Data ──────────────────────────────────────────────────────────────

class BoundingBox(BaseModel):
    """Axis-aligned bounding box in pixel coordinates."""
    x: float
    y: float
    width: float
    height: float


class Anchor(BaseModel):
    """Anchor point for compositing (0.0–1.0 relative to bbox)."""
    x: float = 0.5  # 0.0 = left edge, 1.0 = right edge
    y: float = 0.5  # 0.0 = top edge, 1.0 = bottom edge


class FrameMotion(BaseModel):
    """Motion data for a single frame.

    Coordinate system: pixel coordinates, origin at top-left.
    Rotation unit: degrees (from cv2.minAreaRect, normalized to [-90, 90]).
    Scale: relative to reference_bbox (1.0 = same size as selection frame).
    Confidence: 0.0–1.0, tracking confidence (1.0 = certain).
    Visibility: True if object is considered present (mask area > threshold).
    Occluded: True if object is known to be behind another object.
    Needs_review: True if tracking quality is uncertain.
    Mask_path: relative path to the binary mask PNG for this frame.
    """
    frame_index: int                # zero-based
    centroid_x: float               # pixels
    centroid_y: float               # pixels
    bbox: BoundingBox               # pixels
    scale_x: float = 1.0            # relative to reference
    scale_y: float = 1.0            # relative to reference
    rotation_deg: float = 0.0       # degrees, [-90, 90]
    opacity: float = 1.0            # 0.0–1.0, fill ratio of bbox
    visibility: bool = True         # object present in frame
    area: float = 0.0               # mask area in pixels
    confidence: float = 1.0         # 0.0–1.0, tracking confidence
    occluded: bool = False          # behind another object
    needs_review: bool = False      # uncertain tracking quality
    mask_path: str | None = None    # relative path to mask PNG


class SceneMotion(BaseModel):
    """Aggregated motion data for an entire scene."""
    scene_id: int
    frames: list[FrameMotion] = Field(default_factory=list)
    reference_bbox: BoundingBox | None = None  # Bbox at selection frame
    tracking_backend: str = "unknown"  # "sam2", "contour", etc.
    model_version: str = ""            # e.g. "sam2.1_hiera_l"
    anchor: Anchor = Field(default_factory=Anchor)


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
    replacement_config: ReplacementConfig | None = None


# ─── Project ──────────────────────────────────────────────────────────────────

class ProjectData(BaseModel):
    """Top-level project state, serializable to JSON.

    Version history:
    - 1.0.0: Initial schema (Milestone 0)
    - 2.0.0: Added confidence, occluded, needs_review, mask_path,
              anchor, tracking_backend, model_version
    """
    version: str = "2.0.0"
    name: str
    source_video: str
    video_metadata: VideoMetadata | None = None
    scenes: list[SceneInfo] = Field(default_factory=list)
    scene_details: list[SceneDetail] = Field(default_factory=list)
    objects: list[TrackedObject] = Field(default_factory=list)


# ─── Job ──────────────────────────────────────────────────────────────────────

class JobInfo(BaseModel):
    """Status of a background processing job."""
    job_id: str
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    message: str = ""
    result_path: str | None = None
    error: str | None = None
    job_type: str = ""


# ─── Migration ────────────────────────────────────────────────────────────────

def migrate_v1_to_v2(data: dict) -> dict:
    """Migrate a v1.0.0 project dict to v2.0.0.

    Adds default values for new fields without breaking existing data.
    """
    if data.get("version", "1.0.0") >= "2.0.0":
        return data  # Already v2+

    data["version"] = "2.0.0"

    for obj in data.get("objects", []):
        motion = obj.get("motion")
        if motion:
            motion.setdefault("tracking_backend", "unknown")
            motion.setdefault("model_version", "")
            motion.setdefault("anchor", {"x": 0.5, "y": 0.5})
            for frame in motion.get("frames", []):
                frame.setdefault("confidence", 1.0)
                frame.setdefault("occluded", False)
                frame.setdefault("needs_review", False)
                frame.setdefault("mask_path", None)
        obj.setdefault("replacement_config", None)

    return data
