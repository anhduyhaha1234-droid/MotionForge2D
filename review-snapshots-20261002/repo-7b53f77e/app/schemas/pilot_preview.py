"""Public request/response contracts for the bounded V3 pilot preview."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PilotPreviewContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=255)
    generation: str = Field(default="1", min_length=1, max_length=64)
    pack_id: str | None = Field(default=None, min_length=1, max_length=128)
    clean_plate_id: str | None = Field(default=None, min_length=1, max_length=128)


class PilotPreviewMaskCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox_xywh_norm: tuple[float, float, float, float]
    source_frame: int = Field(ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    note: str = Field(default="operator-corrected removal mask", max_length=500)

    @field_validator("bbox_xywh_norm")
    @classmethod
    def validate_bbox(cls, value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x, y, w, h = value
        if min(x, y, w, h) < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
            raise ValueError("bbox_xywh_norm must be a positive rectangle inside [0,1]^2")
        return value


class PilotPreviewAnchorKeyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame: int = Field(ge=0)
    anchor_xy_norm: tuple[float, float]
    scale: float = Field(default=1.0, gt=0.0, le=4.0)
    rotation_deg: float = Field(default=0.0, ge=-45.0, le=45.0)
    # Absolute anchor overrides are retained for wire compatibility but are
    # informational by default.  Only this explicit offset may move contact.
    operator_offset_xy_norm: tuple[float, float] = (0.0, 0.0)

    @field_validator("anchor_xy_norm")
    @classmethod
    def validate_anchor(cls, value: tuple[float, float]) -> tuple[float, float]:
        if not all(0.0 <= part <= 1.0 for part in value):
            raise ValueError("anchor_xy_norm must lie inside [0,1]^2")
        return value


class PilotPreviewOccluder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: str = Field(default="foreground_right", min_length=1, max_length=64)
    region_xywh_norm: tuple[float, float, float, float]
    z: int = Field(default=-1, ge=-10, le=-1)

    @field_validator("region_xywh_norm")
    @classmethod
    def validate_region(cls, value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x, y, w, h = value
        if min(x, y, w, h) < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
            raise ValueError("region_xywh_norm must be a positive rectangle inside [0,1]^2")
        return value


class PilotPreviewSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=255)
    generation: str = Field(default="1", min_length=1, max_length=64)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=1)
    role: str = Field(default="seated_character", min_length=1, max_length=80)
    source_prompt: str = Field(min_length=1, max_length=2000)
    # The id selects a server-owned versioned pack.  Its manifest, files,
    # hashes, poses, and anchors are resolved server-side; client capability
    # claims are never used as compatibility evidence.
    pack_id: str | None = Field(default=None, min_length=1, max_length=128)
    clean_plate_id: str | None = Field(default=None, min_length=1, max_length=128)
    anchor_mode: str = Field(default="source_derived", pattern="^(source_derived|explicit_offset)$")
    asset_sha256: str = Field(min_length=64, max_length=64)
    mask_correction: PilotPreviewMaskCorrection
    anchor_keyframes: list[PilotPreviewAnchorKeyframe] = Field(min_length=1, max_length=8)
    occluder: PilotPreviewOccluder
    # Declared pack capabilities (12 T01 keys).  Informational at submit;
    # the server owns the verdict (pinned V3 negative always fails).
    pack_capabilities: dict[str, bool | str] | None = None

    @field_validator("asset_sha256")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        value = value.lower()
        if any(char not in "0123456789abcdef" for char in value):
            raise ValueError("asset_sha256 must be lowercase hexadecimal")
        return value


class PilotPreviewContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    legacy_project_id: str
    durable_project_id: str | None
    durable_video_item_id: str | None
    generation: str
    chain_status: str
    source_name: str
    source_sha256: str
    width: int
    height: int
    fps_num: int
    fps_den: int
    frame_count: int
    duration_seconds: float
    allowed_frame_window: tuple[int, int]
    asset_sha256: str
    asset_url: str
    import_endpoint: str
    analyze_endpoint: str
    legacy_id_bridge: dict[str, str | None]
    # R2 pack gate: server-owned verdict inputs for this asset.
    composition_revision: str | None = None
    pack_required_capabilities: list[str] = Field(default_factory=list)
    pack_verdict_for_pinned_asset: dict[str, object] = Field(default_factory=dict)
    selected_pack_id: str | None = None
    clean_plate_required: bool = True
    clean_plate_verdict: dict[str, object] = Field(default_factory=dict)
    selected_clean_plate_id: str | None = None


class PilotPreviewSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    manifest: dict[str, object]


class PilotPreviewJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: dict[str, object]
    manifest: dict[str, object] | None = None
    media: dict[str, str] = Field(default_factory=dict)
