"""Pydantic schemas for the S09 demo comparison API (S09-T04).

Strict, additive DTOs for ``/api/v2/s09-demo-compare`` — the read/observe
surface the Demo comparison UI consumes.  Mirrors the S09-T03 contract
(``app/schemas/s09_demo_loops.py``):

- model_config = ConfigDict(extra="forbid", strict=True) on request models —
  unknown field → 422, no silent coercion.
- No client-fabricated authority: workspace/project ids are server-owned
  (DEFAULT_WORKSPACE_ID); requests never carry them.
- Every number the UI renders comes from a MEASURED source (frozen benchmark
  results document, published artifact metadata, persisted SegmentRenderRoute
  rows or the durable job record).  There is NO fabricated fallback: an
  absent value stays ``null`` / an absent list stays empty.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The single sync step of the S09-T03 demo-loop job this API submits.
_DEMO_STEP_CODE = "demo_loop"


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# ── POST /jobs ───────────────────────────────────────────────────────────────


class DemoCompareJobRequest(_StrictBase):
    """Submit ONE risk-selected demo-loop batch through the T03 contract.

    Shape-identical to ``DemoLoopSubmitRequest`` minus the client-supplied
    idempotency key (the route derives it from the canonical manifest
    fingerprint, exactly like T03, so equivalent replays reuse one Job).

    S09-T04-C2: ``benchmark_results`` is REQUIRED and has NO default —
    evidence must come from explicit validated configuration or the exact
    frozen C2 decision.  ``expect_content_sha256`` optionally PINS the file
    content identity; a mismatch fails closed (409) instead of planning
    routes from silently-changed bytes.
    """

    requested_loops: list[str] = Field(..., min_length=1, max_length=8)
    benchmark_results: str = Field(..., min_length=1)
    fixtures_dir: str = Field(..., min_length=1)
    #: Expected file-content SHA-256 of *benchmark_results*; when supplied,
    #: a document whose bytes hash differently is STALE → 409 fail-closed.
    expect_content_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    #: Optional per-risk-class pinned SegmentRenderRoute overrides; honored
    #: only when measured-passing (fail-closed at plan time by T03).
    pinned_routes: dict[str, str] | None = None


class DemoCompareJobCreated(_StrictBase):
    """201 create / 200 idempotent-replay response body."""

    job_id: str
    status: str
    reused: bool = False
    detail_url: str


# ── GET /capabilities ────────────────────────────────────────────────────────


class BenchmarkRouteRow(_StrictBase):
    """One measured route row from the frozen benchmark results document."""

    fixture_id: str
    risk_class: str
    route: str
    overall_pass: bool
    checks: list[dict[str, Any]] = []


class BenchmarkClassSummary(_StrictBase):
    """Measured evidence for one risk class: every row + smallest passing."""

    risk_class: str
    measured_routes: list[BenchmarkRouteRow]
    smallest_passing_route: str | None = None


class CapabilitiesResponse(_StrictBase):
    """What the frozen benchmark document actually measures.

    Every entry is derived from the document at *benchmark_results*; a class
    without passing measurements carries ``smallest_passing_route: null``
    instead of a fabricated default.

    S09-T04-C2: ``content_sha256`` is the FILE-content hash of the document
    bytes actually read — clients pin it via ``expect_content_sha256`` on
    every subsequent call so changed evidence fails closed (no TOCTOU).
    """

    benchmark_results: str
    content_sha256: str
    frozen_content_sha256: str
    thresholds_policy: str | None
    routes_measured: list[str]
    classes: list[BenchmarkClassSummary]


# ── GET /loops/{loop_id} ─────────────────────────────────────────────────────


class LoopSegment(_StrictBase):
    """One locked shot segment of a demo loop fixture manifest."""

    shot_id: str
    start_frame: int
    end_frame: int


class LoopManifestResponse(_StrictBase):
    """The loop's locked structure + per-class planned renderer routes.

    ``routes_by_risk_class`` resolves through the SAME fail-closed planner
    (measured evidence + optional pins) used at submission time.  When no
    plan can be built for the current evidence (e.g. nothing passes), the
    field is ``null`` and ``plan_error`` carries the planner refusal — never
    an invented route.
    """

    loop_id: str
    frame_count: int
    fps: float
    width: int
    height: int
    segments: list[LoopSegment]
    risk_classes: list[str]
    replacement_ops: list[str]
    routes_by_risk_class: dict[str, str] | None = None
    plan_error: str | None = None


class LoopListResponse(_StrictBase):
    """All loops declared by the fixture index with their planned routes."""

    loops: list[LoopManifestResponse]


# ── GET /jobs/{job_id} ───────────────────────────────────────────────────────


class PublishedArtifact(_StrictBase):
    loop_id: str
    relative_path: str
    content_url: str
    artifact_id: str
    sha256: str
    size_bytes: int
    frame_count: int | None = None
    reused_existing_file: bool | None = None


class RouteEvidenceEntry(_StrictBase):
    """One persisted SegmentRenderRoute decision relevant to the job.

    Emitted only when the job's input manifest references a reskin config;
    otherwise an empty list (no fabricated per-segment story).
    """

    occurrence_segment_id: str
    route: str
    anchor_x: float
    anchor_y: float
    start_frame: int
    end_frame: int
    confidence: float
    confidence_source: str
    reasons: list[str] = []
    provenance: dict[str, Any] | None = None


class GenerationEvidence(_StrictBase):
    """READ-ONLY immutable generation identity of ONE regeneration (§4.5).

    Emitted verbatim from the durable attempt ``result.
    generation_evidence`` written by the T03 regen handler — never derived,
    never caller-influenced.  ``frozen_evidence_sha256`` is the SERVER-side
    frozen-evidence identity (contract C4 §4.4) the job's generation
    fingerprint was bound to.
    """

    generation: str
    base_job_id: str
    correction_id: str
    correction_context_sha256: str
    frozen_evidence_sha256: str


class PublicationIdentity(_StrictBase):
    """The base publication identity an unaffected loop is bound from."""

    artifact_id: str
    relative_path: str
    sha256: str
    size_bytes: int


class PublicationStatus(_StrictBase):
    """Per-loop regeneration split of ONE regen job result (§4.5).

    ``regenerated`` is copied IMMUTABLY from the attempt result — the
    producer stamps it at render/bind time; this API NEVER infers it from
    hash equality.  ``None`` only when an older result carried no stamp
    (no fabricated story).  ``render_ms`` exists ONLY for affected renders;
    unaffected loops carry ``base_publication`` instead — their verbatim
    base identity (hash re-verified by the handler before binding).
    """

    loop_id: str
    regenerated: bool | None = None
    render_ms: int | None = None
    base_publication: PublicationIdentity | None = None


class DemoCompareStatus(_StrictBase):
    """Durable status of the demo-loop Job powering one comparison view."""

    job_id: str
    state: str
    progress: float
    error: dict[str, Any] | None = None
    requested_loops: list[str] = []
    covered_risk_classes: list[str] = []
    frozen_content_sha256: str | None = None
    thresholds_policy: str | None = None
    published: list[PublishedArtifact] = []
    route_evidence: list[RouteEvidenceEntry] = []
    #: Regen-only read model (§4.5): absent (``None``/empty) for plain
    #: demo-loop jobs — never fabricated.
    generation_evidence: GenerationEvidence | None = None
    affected_loop_ids: list[str] = []
    publications: list[PublicationStatus] = []


# ── POST /jobs/{base_job_id}/regenerate (S09-T04-C3, §3.2) ───────────────────


class RegenerateJobRequest(_StrictBase):
    """Body of the targeted-regeneration submit.

    §3.2 contract: the caller supplies ONLY the correction id.  The
    affected scope and correction context are NEVER caller-supplied — they
    are loaded server-side from the T05A applied-regeneration context so a
    hostile client cannot tamper with what regenerates.

    ``expect_content_sha256`` is OPTIONAL (review C3 F1): the endpoint is
    ALREADY bound to the exact frozen evidence server-side — the I05-C3
    decision SHA plus the decision-embedded measured-input SHA are verified
    against on-disk bytes on every request — so requiring clients to know
    the pin would block every caller without adding safety.  When a client
    DOES send a pin (e.g. taken from an earlier capabilities read), it is
    still verified against current bytes as a TOCTOU guard (409 on drift).
    """

    correction_id: str = Field(..., min_length=1, max_length=64)
    #: Optional client-side TOCTOU pin of the benchmark document the BASE
    #: job was planned from; verified against on-disk bytes WHEN SUPPLIED
    #: (409 stale).  Server-side frozen-evidence binding is unconditional.
    expect_content_sha256: str | None = Field(
        default=None, min_length=64, max_length=64
    )


class RegenerateJobCreated(_StrictBase):
    """Created (or replayed) durable regeneration Job reference (§3.2/§4.4)."""

    job_id: str
    state: str
    reused: bool
    base_job_id: str
    correction_id: str
    correction_context_sha256: str
    #: The SERVER-side frozen-evidence identity this generation is bound
    #: to — the exact value folded into the three-field fingerprint.
    frozen_evidence_sha256: str
    affected_loop_ids: list[str]
    detail_url: str
