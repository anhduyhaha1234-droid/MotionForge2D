"""Pydantic schemas for the durable object-candidate extraction API (S08-T02).

DTOs for submitting and reading ``DISCOVER_OBJECTS`` jobs.  The read models
expose ONLY published final outputs (purpose ``thumbnail``/``mask``/``result``)
of a terminal-``completed`` Job — partial or stale output is never exposed:
``outputs`` is empty for every non-completed state and the outputs endpoint
is 409 while the Job is active.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExtractionSubmitRequest(BaseModel):
    """Submit payload for one durable candidate extraction."""

    project_id: str = Field(..., min_length=1)
    video_item_id: str = Field(..., min_length=1)
    source_sha256: str | None = Field(
        None,
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "ASSERTION ONLY (C2): the server resolves the current source "
            "SHA-256 itself; a mismatched hint fails closed 409 with no Job."
        ),
    )
    generation: str | None = Field(
        None,
        min_length=1,
        max_length=64,
        description=(
            "ASSERTION ONLY (C2): the server resolves the current generation "
            "from durable state; a mismatched hint fails closed 409 with no "
            "Job.  Never defaulted to '1' when the backend differs."
        ),
    )
    extractor_version: str | None = Field(None, max_length=64)
    provider: str | None = Field(
        None,
        description=(
            "RESERVED — provider selection is server/runtime policy "
            "(MOTIONFORGE_EXTRACTION_PROVIDER).  Any client-supplied value "
            "is rejected (422); the QA provider can never be selected "
            "through request JSON."
        ),
    )


class ExtractionSubmitResponse(BaseModel):
    """Submit result: the durable Job id and whether it was reused."""

    job_id: str
    reused: bool
    job_type: str = "DISCOVER_OBJECTS"
    status: str = "queued"


class ExtractionOutputData(BaseModel):
    """One published artifact of a completed extraction Job."""

    artifact_id: str
    name: str
    purpose: str
    relative_path: str
    sha256: str
    size_bytes: int
    width: int | None
    height: int | None
    mime_type: str | None


class ExtractionCandidateData(BaseModel):
    """One candidate (role + occurrences + artifact references).

    ``role_id`` is the STABLE role identifier (deterministic per job +
    candidate index); display names are never joins/ids (correction B5).
    """

    index: int
    role_id: str
    name: str
    kind: str
    confidence: float
    reasons: list[str]
    occurrences: list[dict[str, Any]]
    artifacts: list[ExtractionOutputData]


class ExtractionSegmentData(BaseModel):
    """One occurrence segment produced by T02 wiring (per role×scene)."""

    id: str
    logical_id: str
    role_id: str
    scene_id: str
    name: str
    kind: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    source_generation: str
    source_job_id: str | None
    mask_artifact_id: str | None
    prompt: dict[str, Any] | None = None
    segmentation: dict[str, Any] | None = None
    algorithm: str | None = None
    algorithm_version: str | None = None
    confidence: float
    confidence_source: str
    visibility: str
    z_order: int
    revision: int


class ExtractionMotionData(BaseModel):
    """One segment motion (camera_relative / object_relative) — REFERENCE only."""

    id: str
    occurrence_segment_id: str
    transform_type: str
    transform: dict[str, Any]
    point_track_flow_ref: dict[str, Any] | list[Any] | None = None
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None = None
    algorithm_version: str | None = None
    confidence: float
    confidence_source: str
    revision: int


class ExtractionOcclusionData(BaseModel):
    """One occlusion edge (occluder → occludee)."""

    id: str
    occluder_segment_id: str
    occludee_segment_id: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    confidence: float
    confidence_source: str
    revision: int


class ExtractionContactData(BaseModel):
    """One contact edge (source → target)."""

    id: str
    source_segment_id: str
    target_segment_id: str
    contact_kind: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    confidence: float
    confidence_source: str
    revision: int


class ExtractionJobResponse(BaseModel):
    """Read model of a DISCOVER_OBJECTS Job.

    ``outputs``/``candidates`` are populated ONLY when the Job is
    terminal-``completed``; every other state exposes an empty output set —
    partial or stale output is never visible through this API.
    Structural graph (segments/motions/occlusions/contacts) is also exposed
    only for completed jobs (T02 wiring, read-only).
    """

    job_id: str
    job_type: str
    status: str
    progress: float
    message: str
    error: str | None = None
    provider: str | None = None
    extractor_version: str | None = None
    generation: str | None = None
    source_sha256: str | None = None
    video_item_id: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    outputs: list[ExtractionOutputData] = Field(default_factory=list)
    candidates: list[ExtractionCandidateData] = Field(default_factory=list)
    segments: list[ExtractionSegmentData] = Field(default_factory=list)
    motions: list[ExtractionMotionData] = Field(default_factory=list)
    occlusions: list[ExtractionOcclusionData] = Field(default_factory=list)
    contacts: list[ExtractionContactData] = Field(default_factory=list)
