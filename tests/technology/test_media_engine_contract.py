"""Contract tests for the MF-TOOL-CONTRACT media-engine schema (S13 P00).

Pure: no database, no GPU, no network, no filesystem.  Every test here is a
frozen contract fact from ``docs/technology/mf_engine_v1/MEDIA_ENGINE_CONTRACT.md``
and the four refusal cases the C-CONTRACT gate requires:

1. a source-locked capability may not silently fall back to T2V/I2V;
2. a client-supplied path or graph is refused with a typed code;
3. an unresolved replay re-attaches or refuses — it never duplicates the POST;
4. a reference change invalidates the affected shots (and only those).
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

from app.schemas.media_engine import (
    CAPABILITY_REFERENCE_REQUIREMENTS,
    E01_JOB_STORE,
    FORBIDDEN_DEGRADATION_TARGETS,
    IDENTITY_COMPONENT_FIELDS,
    IDENTITY_PROOF_FIELDS,
    MEDIA_ENGINE_CONTRACT_VERSION,
    NO_AUTO_DOWNLOAD_FROM_UI,
    PUBLISHABLE_SERVER_TYPES,
    RESERVATION_IDENTITY_FIELDS,
    SERVER_OUTPUT_TYPES,
    SERVER_PUBLISHABLE_TYPES,
    SOURCE_LOCKED_CAPABILITIES,
    STATE_ORDER,
    STATE_TRANSITION_TABLE,
    AudioHandoff,
    BackendIdentityProof,
    CacheEntry,
    CacheIdentity,
    CastBinding,
    CapabilityOffer,
    CapabilitySet,
    DecodedMap,
    GpuLeaseGrant,
    GpuLeaseRequest,
    GpuLeaseView,
    HardwareProfile,
    InflightReservation,
    ManagedArtifact,
    MediaCapability,
    MediaEngineCancel,
    MediaEngineFailure,
    MediaEngineRefusal,
    MediaEngineRefusalCode,
    MediaEngineRequest,
    MediaEngineResult,
    MediaEngineState,
    ModelPin,
    ModelRegistry,
    ModelRegistryEntry,
    NodePin,
    OutputContract,
    ReferenceArtifact,
    ReferenceChange,
    ReferenceRequirement,
    ReplayAction,
    ReplayDecision,
    ResourceBudget,
    ShotRange,
    SourceLock,
    StateTransition,
    WorkflowPins,
    assert_publishable_set,
    assert_shared_stack,
    cache_identity_for,
    identity_integrity,
    invalidate_for_reference_change,
    reservation_identity_for,
    resolve_replay,
    verify_identity_proof,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


# ── builders ──────────────────────────────────────────────────────────────────


def make_range(start: int = 100, end: int = 119) -> ShotRange:
    return ShotRange(start_frame=start, end_frame=end)


def make_artifact(artifact_id: str = "art-ref-1", sha: str = SHA_B) -> ReferenceArtifact:
    return ReferenceArtifact(artifact_id=artifact_id, sha256=sha)


def make_cast(
    role: str = "protagonist",
    character_id: str = "char-1",
    pack_version_id: str = "packver-1",
    references: tuple[ReferenceArtifact, ...] | None = None,
    style_version: str | None = "style-1",
) -> CastBinding:
    return CastBinding(
        role=role,
        character_id=character_id,
        pack_version_id=pack_version_id,
        references=references if references is not None else (make_artifact(),),
        style_version=style_version,
    )


def make_pins(
    workflow_id: str = "wf-transfer",
    model_id: str = "wan-animate-2",
    seed: int = 1234,
    node_id: str = "node-1",
    node_config_hash: str = "cfg" + "0" * 13,
) -> WorkflowPins:
    return WorkflowPins(
        workflow_id=workflow_id,
        workflow_version="3",
        workflow_hash="wf" + "1" * 14,
        model=ModelPin(
            model_id=model_id,
            revision="rev-1",
            file_sha256=SHA_C,
            precision="int8",
        ),
        nodes=(NodePin(node_id=node_id, node_class="KSampler", config_hash=node_config_hash),),
        config_hash="cf" + "2" * 14,
        seed=seed,
    )


def make_output(
    width: int = 640,
    height: int = 360,
    frame_count: int = 20,
    audio: AudioHandoff | None = None,
) -> OutputContract:
    return OutputContract(
        width=width,
        height=height,
        fps_num=30,
        fps_den=1,
        frame_count=frame_count,
        container="mp4",
        video_codec="h264",
        audio=audio if audio is not None else AudioHandoff(mode="silent"),
    )


def make_request(
    capability: MediaCapability = MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER,
    cast: tuple[CastBinding, ...] | None = None,
    pins: WorkflowPins | None = None,
    output: OutputContract | None = None,
    source: SourceLock | None = None,
    stage: str = "video_apply",
) -> MediaEngineRequest:
    return MediaEngineRequest(
        workspace_id="ws-1",
        project_id="proj-1",
        series_id="series-1",
        video_id="video-1",
        stage=stage,
        attempt_id="attempt-1",
        job_id="job-1",
        capability=capability,
        source=source
        if source is not None
        else SourceLock(
            source_artifact_id="art-source-1",
            source_sha256=SHA_A,
            shot_range=make_range(),
            pts_start_ticks=0,
            pts_end_ticks=60928,
            fps_num=30,
            fps_den=1,
            # The stream's rational time_base, measured by BENCH/VIDEO14B on the
            # very clip this fixture mirrors — NOT the 30/1 frame rate (R6).
            stream_timebase_num=1,
            stream_timebase_den=15360,
            decoded_frame_count=20,
        ),
        cast=cast if cast is not None else (make_cast(),),
        pins=pins if pins is not None else make_pins(),
        output=output if output is not None else make_output(),
        budget=ResourceBudget(
            resource_class="gpu",
            max_wall_seconds=900.0,
            max_vram_bytes=12 * 1024**3,
            max_output_bytes=64 * 1024**2,
        ),
    )


def make_offer(
    capability: MediaCapability,
    available: bool = True,
    reason: str | None = None,
) -> CapabilityOffer:
    return CapabilityOffer(
        capability=capability,
        available=available,
        unavailable_reason_code=reason if not available else None,
        evidence_source="probed_config",
    )


def make_reservation(
    submit_state: str = "acked",
    prompt_id: str | None = "prompt-1",
    owner_session: str = "session-owner",
    server_epoch: str | None = "epoch-7",
    workspace_id: str | None = "ws-1",
    output_contract_digest: str | None = "oc" + "3" * 14,
) -> InflightReservation:
    return InflightReservation(
        attempt_id="attempt-1",
        job_id="job-1",
        stage="video_apply",
        owner_session=owner_session,
        submit_state=submit_state,
        workflow_digest="wd" + "1" * 14,
        input_digest="id" + "2" * 14,
        prompt_id=prompt_id,
        workspace_id=workspace_id,
        server_epoch=server_epoch,
        output_contract_digest=output_contract_digest,
    )


def make_proof(
    requester_session: str = "session-owner",
    resolution: str = "resolved",
    server_epoch: str = "epoch-7",
    workspace_id: str = "ws-1",
    attempt_id: str = "attempt-1",
    job_id: str = "job-1",
    stage: str = "video_apply",
    workflow_digest: str = "wd" + "1" * 14,
    input_digest: str = "id" + "2" * 14,
    output_contract_digest: str = "oc" + "3" * 14,
    integrity: bool = True,
) -> BackendIdentityProof:
    """A backend-RESOLVED identity claim — never a caller-supplied boolean."""

    claim = {
        "requester_session": requester_session,
        "workspace_id": workspace_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "stage": stage,
        "server_epoch": server_epoch,
        "workflow_digest": workflow_digest,
        "input_digest": input_digest,
        "output_contract_digest": output_contract_digest,
        "resolution": resolution,
    }
    return BackendIdentityProof(
        integrity_sha256=identity_integrity(**claim) if integrity else SHA_D,
        resolved_by="e01_attempt_row",
        **claim,
    )


# ── 1. capabilities are distinct and never degrade silently ───────────────────


def test_capability_set_is_exactly_the_four_frozen_values() -> None:
    assert {c.value for c in MediaCapability} == {
        "image_edit_multi_reference",
        "source_video_motion_transfer",
        "video_edit_controlled",
        "text_to_video",
    }
    assert len({c.value for c in MediaCapability}) == 4


def test_source_locked_capabilities_are_the_two_clip_locked_routes() -> None:
    assert SOURCE_LOCKED_CAPABILITIES == frozenset(
        {
            MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER,
            MediaCapability.VIDEO_EDIT_CONTROLLED,
        }
    )
    assert MediaCapability.TEXT_TO_VIDEO not in SOURCE_LOCKED_CAPABILITIES
    assert MediaCapability.IMAGE_EDIT_MULTI_REFERENCE not in SOURCE_LOCKED_CAPABILITIES


@pytest.mark.parametrize("requested", sorted(SOURCE_LOCKED_CAPABILITIES, key=lambda c: c.value))
@pytest.mark.parametrize(
    "substitute",
    [
        MediaCapability.TEXT_TO_VIDEO,
        MediaCapability.IMAGE_EDIT_MULTI_REFERENCE,
    ],
)
def test_source_locked_route_refuses_t2v_i2v_substitution(
    requested: MediaCapability, substitute: MediaCapability
) -> None:
    """The core anti-degradation gate: T2V/I2V can never serve a locked source."""

    offers = CapabilitySet(
        offers=(
            make_offer(requested),
            make_offer(substitute),
        )
    )
    assert requested in FORBIDDEN_DEGRADATION_TARGETS
    assert substitute in FORBIDDEN_DEGRADATION_TARGETS[requested]

    with pytest.raises(MediaEngineRefusal) as exc:
        offers.assert_can_serve(requested, substitute=substitute)
    assert exc.value.code is MediaEngineRefusalCode.CAPABILITY_DEGRADATION_REFUSED


@pytest.mark.parametrize("requested", sorted(SOURCE_LOCKED_CAPABILITIES, key=lambda c: c.value))
def test_operator_approval_cannot_bless_a_t2v_degradation(
    requested: MediaCapability,
) -> None:
    """Approval is not a licence to relabel a T2V result as a motion transfer."""

    offers = CapabilitySet(
        offers=(make_offer(requested), make_offer(MediaCapability.TEXT_TO_VIDEO))
    )
    with pytest.raises(MediaEngineRefusal) as exc:
        offers.assert_can_serve(
            requested,
            substitute=MediaCapability.TEXT_TO_VIDEO,
            operator_approved_substitution=True,
        )
    assert exc.value.code is MediaEngineRefusalCode.CAPABILITY_DEGRADATION_REFUSED


def test_substitution_still_needs_explicit_approval_when_not_forbidden() -> None:
    """A permitted substitution is never silent — it still requires approval."""

    offers = CapabilitySet(
        offers=(
            make_offer(MediaCapability.TEXT_TO_VIDEO),
            make_offer(MediaCapability.IMAGE_EDIT_MULTI_REFERENCE),
        )
    )
    with pytest.raises(MediaEngineRefusal) as exc:
        offers.assert_can_serve(
            MediaCapability.TEXT_TO_VIDEO,
            substitute=MediaCapability.IMAGE_EDIT_MULTI_REFERENCE,
        )
    assert exc.value.code is MediaEngineRefusalCode.CAPABILITY_DEGRADATION_REFUSED

    approved = offers.assert_can_serve(
        MediaCapability.TEXT_TO_VIDEO,
        substitute=MediaCapability.IMAGE_EDIT_MULTI_REFERENCE,
        operator_approved_substitution=True,
    )
    assert approved.capability is MediaCapability.IMAGE_EDIT_MULTI_REFERENCE


def test_capability_absence_is_explicit_and_fail_closed() -> None:
    """An unavailable capability must state a reason; absence is never implied."""

    with pytest.raises(ValueError):
        CapabilityOffer(capability=MediaCapability.TEXT_TO_VIDEO, available=False)
    with pytest.raises(ValueError):
        CapabilityOffer(
            capability=MediaCapability.TEXT_TO_VIDEO,
            available=True,
            unavailable_reason_code="weird",
        )
    with pytest.raises(ValueError):
        CapabilityOffer(
            capability=MediaCapability.TEXT_TO_VIDEO,
            available=True,
            evidence_source="wishful_thinking",
        )

    offers = CapabilitySet(
        offers=(make_offer(MediaCapability.TEXT_TO_VIDEO, available=False, reason="no_model"),)
    )
    with pytest.raises(MediaEngineRefusal) as exc:
        offers.assert_can_serve(MediaCapability.TEXT_TO_VIDEO)
    assert exc.value.code is MediaEngineRefusalCode.CAPABILITY_UNAVAILABLE
    assert "no_model" in exc.value.detail

    with pytest.raises(MediaEngineRefusal) as exc2:
        offers.assert_can_serve(MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER)
    assert exc2.value.code is MediaEngineRefusalCode.CAPABILITY_UNAVAILABLE


# ── 2. backend-managed artifacts are the authority ────────────────────────────


def test_request_refuses_a_client_supplied_path() -> None:
    payload = make_request().model_dump()
    payload["client_path"] = "C:/Users/Admin/raw/clip.mp4"

    with pytest.raises(MediaEngineRefusal) as exc:
        MediaEngineRequest(**payload)
    assert exc.value.code is MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED
    assert exc.value.as_dict()["code"] == "client_artifact_path_refused"


def test_request_refuses_a_client_supplied_graph() -> None:
    payload = make_request().model_dump()
    payload["client_graph"] = {"nodes": [{"id": 1, "class": "KSampler"}]}

    with pytest.raises(MediaEngineRefusal) as exc:
        MediaEngineRequest(**payload)
    assert exc.value.code is MediaEngineRefusalCode.CLIENT_GRAPH_REFUSED


def test_reference_artifact_refuses_a_raw_path() -> None:
    with pytest.raises(MediaEngineRefusal) as exc:
        ReferenceArtifact(artifact_id="art-1", sha256=SHA_B, path="/tmp/pose.png")
    assert exc.value.code is MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED


@pytest.mark.parametrize(
    "bad_path",
    ["C:/abs/out.mp4", "/abs/out.mp4", "\\abs\\out.mp4", "../escape/out.mp4", "a/../../b.mp4"],
)
def test_managed_artifact_paths_must_stay_inside_the_store(bad_path: str) -> None:
    with pytest.raises(MediaEngineRefusal) as exc:
        ManagedArtifact(
            artifact_id="art-out-1",
            kind="video",
            media_type="video/mp4",
            sha256=SHA_D,
            store_relative_path=bad_path,
            size_bytes=1024,
            publishable=True,
        )
    assert exc.value.code is MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED


def test_intermediate_artifacts_are_managed_but_never_publishable() -> None:
    """A mask/graph/pose_sheet is a legitimate intermediate and stays managed."""

    mask = ManagedArtifact(
        artifact_id="art-mask-1",
        kind="mask",
        media_type="image/png",
        sha256=SHA_D,
        store_relative_path="masks/shot-0.png",
        size_bytes=2048,
        publishable=False,
    )
    assert mask.publishable is False and mask.kind == "mask"

    with pytest.raises(MediaEngineRefusal) as exc:
        ManagedArtifact(
            artifact_id="art-mask-1",
            kind="mask",
            media_type="image/png",
            sha256=SHA_D,
            store_relative_path="masks/shot-0.png",
            size_bytes=2048,
            publishable=True,
        )
    assert exc.value.code is MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED

    video = ManagedArtifact(
        artifact_id="art-out-1",
        kind="video",
        media_type="video/mp4",
        sha256=SHA_D,
        store_relative_path="video/out.mp4",
        size_bytes=1024,
        publishable=True,
    )
    assert assert_publishable_set([mask, video]) == (video,)


def test_publication_gate_is_fail_closed() -> None:
    mask = ManagedArtifact(
        artifact_id="art-mask-1",
        kind="mask",
        media_type="image/png",
        sha256=SHA_D,
        store_relative_path="masks/shot-0.png",
        size_bytes=2048,
        publishable=False,
    )
    with pytest.raises(MediaEngineRefusal) as exc:
        assert_publishable_set([mask])
    assert exc.value.code is MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED

    video = ManagedArtifact(
        artifact_id="art-out-1",
        kind="video",
        media_type="video/mp4",
        sha256=SHA_D,
        store_relative_path="video/out.mp4",
        size_bytes=1024,
        publishable=True,
    )
    assert assert_publishable_set([video], publishable_types=("output",)) == (video,)
    with pytest.raises(ValueError):
        assert_publishable_set([video], publishable_types=("output", "preview"))
    with pytest.raises(ValueError):
        OutputContract(
            width=640,
            height=360,
            fps_num=30,
            fps_den=1,
            frame_count=20,
            container="mp4",
            video_codec="h264",
            audio=AudioHandoff(mode="silent"),
            publishable_types=("output", "raw"),
        )


def make_output_artifact(
    artifact_id: str = "art-out-1",
    server_output_type: str = "output",
    publishable: bool = True,
    kind: str = "video",
) -> ManagedArtifact:
    return ManagedArtifact(
        artifact_id=artifact_id,
        kind=kind,
        media_type="video/mp4",
        sha256=SHA_D,
        store_relative_path="video/out.mp4",
        size_bytes=1024,
        publishable=publishable,
        server_output_type=server_output_type,
    )


def test_empty_publish_allowlist_refuses() -> None:
    """D03 — the exact R7 case: ``publishable_types=()`` used to return the artifact.

    An empty allow-list is not "no narrowing" — it is a refusal.  The valid output
    still passes through the default (server-owned) allow-list.
    """

    video = make_output_artifact()
    with pytest.raises(MediaEngineRefusal) as exc:
        assert_publishable_set([video], publishable_types=())
    assert exc.value.code is MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED
    assert "EMPTY" in exc.value.detail

    assert assert_publishable_set([video]) == (video,)
    assert assert_publishable_set([video], publishable_types=SERVER_PUBLISHABLE_TYPES) == (video,)
    assert assert_publishable_set([video], publishable_types=PUBLISHABLE_SERVER_TYPES) == (video,)


@pytest.mark.parametrize("server_output_type", ["temp", "input", "intermediate", "preview"])
def test_non_output_server_classifications_refuse_publication(server_output_type: str) -> None:
    """D03 — the SERVER's node-output classification is the publication authority."""

    artifact = make_output_artifact(server_output_type=server_output_type)
    # The producing node staged it as publishable; that flag is not authority.
    assert artifact.publishable is True and artifact.server_output_type == server_output_type
    with pytest.raises(MediaEngineRefusal) as exc:
        assert_publishable_set([artifact], publishable_types=SERVER_PUBLISHABLE_TYPES)
    assert exc.value.code is MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED
    assert server_output_type in exc.value.detail


def test_server_output_type_vocabulary_is_closed_and_narrowing_only() -> None:
    assert SERVER_OUTPUT_TYPES[0] == "output"
    assert PUBLISHABLE_SERVER_TYPES == ("output",) == SERVER_PUBLISHABLE_TYPES
    with pytest.raises(ValueError):
        make_output_artifact(server_output_type="whatever")
    with pytest.raises(ValueError):
        assert_publishable_set([make_output_artifact()], publishable_types=("preview",))
    with pytest.raises(ValueError):
        assert_publishable_set([make_output_artifact()], publishable_types=("output", "preview"))
    # A non-publishable intermediate keeps refusing, whatever its server type.
    with pytest.raises(MediaEngineRefusal):
        assert_publishable_set([make_output_artifact(publishable=False)])
    with pytest.raises(MediaEngineRefusal):
        assert_publishable_set([make_output_artifact(kind="pose_sheet")])


def test_unknown_artifact_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        ManagedArtifact(
            artifact_id="art-out-1",
            kind="hologram",
            media_type="video/mp4",
            sha256=SHA_D,
            store_relative_path="video/out.mp4",
            size_bytes=1,
            publishable=True,
        )


def test_request_carries_every_frozen_fact() -> None:
    request = make_request()
    assert (request.workspace_id, request.project_id, request.series_id) == (
        "ws-1",
        "proj-1",
        "series-1",
    )
    assert (request.video_id, request.stage, request.attempt_id, request.job_id) == (
        "video-1",
        "video_apply",
        "attempt-1",
        "job-1",
    )
    assert request.capability is MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER
    assert request.source.shot_range.key() == "100-119"
    # fps and the stream's rational time_base are DIFFERENT facts (R6).  The
    # fixture mirrors the measured clip: 30/1 fps stored at a 1/15360 time_base.
    assert request.source.fps == "30/1"
    assert request.source.stream_timebase == "1/15360"
    assert request.source.timebase == "1/15360"
    assert request.source.timebase != request.source.fps
    assert request.source.ticks_per_frame == (512, 1)
    assert request.source.decoded_frame_count == 20
    assert (request.source.pts_start_ticks, request.source.pts_end_ticks) == (0, 60928)
    binding = request.cast[0]
    assert (binding.role, binding.character_id, binding.pack_version_id) == (
        "protagonist",
        "char-1",
        "packver-1",
    )
    assert binding.references[0].sha256 == SHA_B
    assert binding.style_version == "style-1"
    assert request.pins.seed == 1234
    assert request.pins.model.file_sha256 == SHA_C
    assert request.pins.nodes[0].node_id == "node-1"
    assert request.output.timebase == "30/1" and request.output.audio.mode == "silent"
    assert request.budget.resource_class == "gpu"


def test_request_rejects_unknown_fields_and_duplicate_roles() -> None:
    payload = make_request().model_dump()
    payload["surprise"] = 1
    with pytest.raises(ValueError):
        MediaEngineRequest(**payload)

    with pytest.raises(ValueError):
        make_request(cast=(make_cast("hero"), make_cast("hero", character_id="char-2")))


def test_shot_range_is_inclusive_and_checked() -> None:
    assert ShotRange(start_frame=5, end_frame=5).frame_count == 1
    assert ShotRange(start_frame=0, end_frame=119).frame_count == 120
    with pytest.raises(ValueError):
        ShotRange(start_frame=10, end_frame=9)
    assert ShotRange(start_frame=0, end_frame=9).overlaps(ShotRange(start_frame=9, end_frame=20))
    assert not ShotRange(start_frame=0, end_frame=8).overlaps(
        ShotRange(start_frame=9, end_frame=20)
    )


# ── 2b. the two rate facts, PTS invariants, capability-aware references ────────


def make_source(**kwargs: object) -> SourceLock:
    """A source lock mirroring the measured clip: 30/1 fps at a 1/15360 time_base."""

    base: dict[str, object] = {
        "source_artifact_id": "art-source-1",
        "source_sha256": SHA_A,
        "shot_range": make_range(),
        "pts_start_ticks": 0,
        "pts_end_ticks": 60928,
        "fps_num": 30,
        "fps_den": 1,
        "stream_timebase_num": 1,
        "stream_timebase_den": 15360,
        "decoded_frame_count": 20,
    }
    base.update(kwargs)
    return SourceLock(**base)


def test_fps_and_stream_timebase_are_different_quantities() -> None:
    """D02 — the R6 defect: ``timebase`` reported the fps instead of the stream's."""

    lock = make_source()
    assert lock.fps == "30/1"
    assert lock.stream_timebase == "1/15360"
    assert lock.timebase == lock.stream_timebase
    assert lock.timebase != lock.fps
    assert lock.ticks_per_frame == (512, 1)

    # A fractional frame rate is representable and never becomes the time_base.
    ntsc = make_source(fps_num=30000, fps_den=1001)
    assert ntsc.fps == "30000/1001"
    assert ntsc.stream_timebase == "1/15360"
    assert ntsc.ticks_per_frame == (64064, 125)  # (1001 * 15360) / 30000, reduced

    # An unprobed stream refuses to invent a time_base rather than answering "30/1".
    unprobed = make_source(stream_timebase_num=None, stream_timebase_den=None)
    assert unprobed.stream_timebase is None
    assert unprobed.timebase is None
    assert unprobed.fps == "30/1"
    with pytest.raises(ValueError):
        make_source(stream_timebase_den=None)


def test_pts_must_be_ordered_and_match_the_declared_count() -> None:
    """D02 — ordered PTS / range / count, with a nonzero start allowed."""

    with pytest.raises(ValueError):
        make_source(pts_start_ticks=10, pts_end_ticks=1)
    with pytest.raises(ValueError):
        make_source(shot_range=make_range(100, 119), decoded_frame_count=19)
    with pytest.raises(ValueError):
        make_source(pts_start_ticks=2048, pts_end_ticks=4096, decoded_frame_count=20)
    zero_span = make_source(pts_start_ticks=0, pts_end_ticks=0, decoded_frame_count=None)
    assert zero_span.pts_span_ticks == 0
    nonzero = make_source(pts_start_ticks=512, pts_end_ticks=60928)
    assert nonzero.pts_start_ticks == 512 and nonzero.pts_span_ticks == 60416


def test_decoded_map_carries_the_stream_timebase_not_the_fps() -> None:
    """D02 — decoded-map semantics preserved: rational time_base + source indices."""

    decoded = DecodedMap(
        decoded_frames=20,
        first_pts_ticks=0,
        timebase=make_source().stream_timebase,
        mapping=tuple(range(100, 120)),
    )
    assert decoded.timebase == "1/15360"
    assert decoded.timebase != make_source().fps
    assert len(decoded.mapping) == decoded.decoded_frames
    with pytest.raises(ValueError):
        DecodedMap(decoded_frames=20, first_pts_ticks=0, timebase="1/15360", mapping=(0, 1))


def test_source_motion_requires_reference_pixels() -> None:
    """D02 — zero-ref source-motion FAILS explicitly (it used to be accepted)."""

    with pytest.raises(MediaEngineRefusal) as exc:
        make_request(cast=())
    assert exc.value.code is MediaEngineRefusalCode.REFERENCE_REQUIREMENT_UNMET
    assert exc.value.as_dict()["code"] == "reference_requirement_unmet"
    assert "source_video_motion_transfer" in exc.value.detail

    with pytest.raises(MediaEngineRefusal) as exc2:
        make_request(cast=(make_cast(references=()),))
    assert exc2.value.code is MediaEngineRefusalCode.REFERENCE_REQUIREMENT_UNMET
    assert "protagonist" in exc2.value.detail

    # One reference pixel per bound role is enough, and the happy path still works.
    assert make_request().cast[0].references[0].sha256 == SHA_B


def test_controlled_edit_is_not_forced_to_carry_character_references() -> None:
    """D02 — a profile that requires no character refs is not forced to carry them."""

    controlled = CAPABILITY_REFERENCE_REQUIREMENTS[MediaCapability.VIDEO_EDIT_CONTROLLED]
    assert (controlled.min_roles, controlled.min_references_per_role) == (0, 0)
    request = make_request(capability=MediaCapability.VIDEO_EDIT_CONTROLLED, cast=())
    assert request.cast == ()
    assert CAPABILITY_REFERENCE_REQUIREMENTS[MediaCapability.TEXT_TO_VIDEO].min_roles == 0

    # The minima are code-owned and NORMATIVE.
    multi = CAPABILITY_REFERENCE_REQUIREMENTS[MediaCapability.IMAGE_EDIT_MULTI_REFERENCE]
    assert multi.min_references_per_role == 2
    with pytest.raises(MediaEngineRefusal) as exc:
        make_request(capability=MediaCapability.IMAGE_EDIT_MULTI_REFERENCE)
    assert exc.value.code is MediaEngineRefusalCode.REFERENCE_REQUIREMENT_UNMET


def test_every_capability_declares_a_normative_reference_requirement() -> None:
    assert set(CAPABILITY_REFERENCE_REQUIREMENTS) == set(MediaCapability)
    for requirement in CAPABILITY_REFERENCE_REQUIREMENTS.values():
        assert requirement.rationale
        assert requirement.min_roles >= 0 and requirement.min_references_per_role >= 0
    with pytest.raises(ValueError):
        ReferenceRequirement(min_roles=0, min_references_per_role=0)  # rationale required
    with pytest.raises(ValueError):
        ReferenceRequirement(min_roles=-1, min_references_per_role=0, rationale="x")
    # An unmet reference requirement never silently passes.
    strict = ReferenceRequirement(min_roles=1, min_references_per_role=1, rationale="x")
    assert strict.unmet_reason((make_cast(),)) is None
    assert strict.unmet_reason(()) is not None
    assert strict.unmet_reason((make_cast(references=()),)) is not None


# ── 3. cache identity ─────────────────────────────────────────────────────────


def test_cache_identity_is_deterministic_and_self_verifying() -> None:
    first = cache_identity_for(make_request())
    second = cache_identity_for(make_request())
    assert first == second
    assert first.digest == second.digest
    assert first.identity_version == MEDIA_ENGINE_CONTRACT_VERSION
    with pytest.raises(ValueError):
        CacheIdentity.model_validate({**first.model_dump(), "digest": SHA_D})


def _mutators() -> dict[str, Callable[[], MediaEngineRequest]]:
    """One mutation per cache-identity component (9 components, frozen set)."""

    def source() -> MediaEngineRequest:
        return make_request(
            source=SourceLock(
                source_artifact_id="art-source-1",
                source_sha256=SHA_C,
                shot_range=make_range(),
                pts_start_ticks=0,
                pts_end_ticks=60928,
                fps_num=30,
                fps_den=1,
            )
        )

    def shot_range() -> MediaEngineRequest:
        return make_request(
            source=SourceLock(
                source_artifact_id="art-source-1",
                source_sha256=SHA_A,
                shot_range=make_range(100, 118),
                pts_start_ticks=0,
                pts_end_ticks=60928,
                fps_num=30,
                fps_den=1,
            )
        )

    def pts() -> MediaEngineRequest:
        return make_request(
            source=SourceLock(
                source_artifact_id="art-source-1",
                source_sha256=SHA_A,
                shot_range=make_range(),
                pts_start_ticks=512,
                pts_end_ticks=60928,
                fps_num=30,
                fps_den=1,
            )
        )

    def cast() -> MediaEngineRequest:
        return make_request(cast=(make_cast(character_id="char-2"),))

    def pack() -> MediaEngineRequest:
        return make_request(cast=(make_cast(pack_version_id="packver-2"),))

    def assets() -> MediaEngineRequest:
        return make_request(cast=(make_cast(references=(make_artifact(sha=SHA_D),)),))

    def style() -> MediaEngineRequest:
        return make_request(cast=(make_cast(style_version="style-9"),))

    def workflow() -> MediaEngineRequest:
        return make_request(pins=make_pins(workflow_id="wf-other"))

    def model() -> MediaEngineRequest:
        return make_request(pins=make_pins(model_id="wan-animate-2-distill"))

    def node() -> MediaEngineRequest:
        return make_request(pins=make_pins(node_config_hash="cfg" + "9" * 13))

    def seed() -> MediaEngineRequest:
        return make_request(pins=make_pins(seed=9999))

    def settings() -> MediaEngineRequest:
        return make_request(output=make_output(width=1280, height=720))

    return {
        "source_sha256": source,
        "shot_range": shot_range,
        "pts": pts,
        "cast": cast,
        "pack": pack,
        "assets": assets,
        "style": style,
        "workflow": workflow,
        "model": model,
        "node_config": node,
        "seed": seed,
        "settings": settings,
    }


@pytest.mark.parametrize("component", sorted(_mutators()))
def test_every_cache_identity_component_changes_the_digest(component: str) -> None:
    """source + range + cast + pack + assets + style + workflow + model + settings."""

    base = cache_identity_for(make_request())
    mutated = cache_identity_for(_mutators()[component]())
    assert mutated.digest != base.digest, f"{component} is not part of the cache identity"


def test_cache_distinguishes_capability_and_stream_timebase_but_not_the_epoch() -> None:
    """D04 — what the cache gained, and the fact that belongs to the reservation.

    The 12 mutation controls above are retained unchanged.  These rows are the
    distinctions this round added: the capability and the STREAM time_base are cache
    facts, while the server epoch is a RESERVATION fact — so re-interpreting the same
    ticks invalidates the cache, and a new server epoch does not.
    """

    assert len(IDENTITY_COMPONENT_FIELDS) == 12
    assert "server_epoch" not in IDENTITY_COMPONENT_FIELDS
    base = cache_identity_for(make_request())

    other_capability = cache_identity_for(
        make_request(capability=MediaCapability.TEXT_TO_VIDEO, cast=())
    )
    assert other_capability.digest != base.digest
    assert other_capability.settings_digest != base.settings_digest

    other_timebase = cache_identity_for(
        make_request(source=make_source(stream_timebase_num=1, stream_timebase_den=12800))
    )
    assert other_timebase.digest != base.digest
    assert other_timebase.settings_digest != base.settings_digest

    # The SAME request keeps the same cache identity (determinism, no epoch input).
    assert cache_identity_for(make_request()).digest == base.digest
    assert reservation_identity_for(make_reservation(server_epoch="epoch-9")) != (
        reservation_identity_for(make_reservation(server_epoch="epoch-7"))
    )


def test_reference_change_invalidates_only_the_affected_shots() -> None:
    shots = (
        CacheEntry(
            entry_id="entry-a",
            identity=cache_identity_for(make_request()),
            shot_range=make_range(0, 59),
            roles=("protagonist",),
            style_versions=(("protagonist", "style-1"),),
        ),
        CacheEntry(
            entry_id="entry-b",
            identity=cache_identity_for(make_request(cast=(make_cast("sidekick"),))),
            shot_range=make_range(60, 119),
            roles=("sidekick",),
            style_versions=(("sidekick", "style-1"),),
        ),
        CacheEntry(
            entry_id="entry-c",
            identity=cache_identity_for(make_request(cast=(make_cast("extra"),))),
            shot_range=make_range(120, 179),
            roles=("extra",),
            style_versions=(),
        ),
    )

    report = invalidate_for_reference_change(
        shots, ReferenceChange(role="protagonist", kind="pack_version", new_value="packver-2")
    )
    assert report.invalidated_entry_ids == ("entry-a",)
    assert report.invalidated_ranges == ("0-59",)
    assert report.invalidated_count == 1
    assert report.unaffected_entry_ids == ("entry-b", "entry-c")

    style_report = invalidate_for_reference_change(
        shots, ReferenceChange(role="protagonist", kind="style_version", new_value="style-2")
    )
    assert style_report.invalidated_entry_ids == ("entry-a",)

    none_report = invalidate_for_reference_change(
        shots, ReferenceChange(role="nobody", kind="reference_artifact", new_value=SHA_C)
    )
    assert none_report.invalidated_entry_ids == ()
    assert none_report.unaffected_entry_ids == ("entry-a", "entry-b", "entry-c")


def test_reference_change_kinds_are_closed() -> None:
    for kind in ("character_id", "pack_version", "reference_artifact", "style_version"):
        ReferenceChange(role="protagonist", kind=kind, new_value="x")
    with pytest.raises(ValueError):
        ReferenceChange(role="protagonist", kind="vibe", new_value="x")


# ── 4. unresolved replay: re-attach or refuse, never a second POST ────────────


def test_replay_actions_are_exactly_two() -> None:
    assert {a.value for a in ReplayAction} == {"re_attach", "refuse"}
    assert "post" not in {a.value for a in ReplayAction}


def test_replay_owner_is_proven_before_the_acked_reattach() -> None:
    """D01 — the exact C-CONTRACT R6 case, inverted.

    Before the fix, ``resolve_replay`` took the ACKed-prompt re-attach branch
    BEFORE the owner check, so a requester that was not the owner was accepted
    whenever the caller's own ``identity_matches`` boolean said so.  The owner is
    now proven from the backend-resolved identity proof, first.
    """

    decision = resolve_replay(
        make_reservation(owner_session="session-owner", submit_state="acked", prompt_id="prompt-1"),
        proof=make_proof(requester_session="session-intruder"),
    )
    assert decision.action is ReplayAction.REFUSE
    assert decision.reason_code == "reservation_owned_by_other_session"
    assert decision.issues_post is False
    # The caller's word is no longer part of the signature at all.
    assert "identity_matches" not in resolve_replay.__code__.co_varnames
    assert "requester_session" not in resolve_replay.__code__.co_varnames

    # ...and the legitimate owner still re-attaches: no over-locking.
    owner = resolve_replay(make_reservation(), proof=make_proof())
    assert owner.action is ReplayAction.RE_ATTACH
    assert owner.reason_code == "re_attach_acked_prompt"
    assert owner.issues_post is False


def test_identity_proof_carries_backend_resolved_identity_and_integrity() -> None:
    """D01 — owner/workspace/job/attempt/stage/epoch/workflow/input+output+integrity."""

    assert set(IDENTITY_PROOF_FIELDS) == {
        "requester_session",
        "workspace_id",
        "job_id",
        "attempt_id",
        "stage",
        "server_epoch",
        "workflow_digest",
        "input_digest",
        "output_contract_digest",
        "resolution",
    }
    proof = make_proof()
    assert verify_identity_proof(proof) is True
    # A mutated claim no longer verifies — the digest binds the resolved facts.
    tampered = proof.model_copy(update={"server_epoch": "epoch-8"})
    assert verify_identity_proof(tampered) is False
    assert tampered.server_epoch == "epoch-8" and proof.server_epoch == "epoch-7"
    with pytest.raises(ValueError):
        make_proof(resolution="probably_fine")


@pytest.mark.parametrize(
    ("reservation_kwargs", "proof_kwargs", "expected_action", "expected_reason"),
    [
        # D01 — the exact R6 case: another owner, ACKed prompt.
        (
            {"owner_session": "session-owner"},
            {"requester_session": "session-intruder"},
            ReplayAction.REFUSE,
            "reservation_owned_by_other_session",
        ),
        ({}, {}, ReplayAction.RE_ATTACH, "re_attach_acked_prompt"),
        # D01 — changed epoch refuses BEFORE the ACKed re-attach branch.
        (
            {"server_epoch": "epoch-7"},
            {"server_epoch": "epoch-8"},
            ReplayAction.REFUSE,
            "reservation_server_epoch_changed",
        ),
        ({"workspace_id": "ws-9"}, {}, ReplayAction.REFUSE, "reservation_workspace_mismatch"),
        (
            {"output_contract_digest": "oc" + "9" * 14},
            {},
            ReplayAction.REFUSE,
            "reservation_output_contract_mismatch",
        ),
        (
            {},
            {"attempt_id": "attempt-2"},
            ReplayAction.REFUSE,
            "reservation_identity_mismatch",
        ),
        ({}, {"job_id": "job-2"}, ReplayAction.REFUSE, "reservation_identity_mismatch"),
        ({}, {"stage": "image_apply"}, ReplayAction.REFUSE, "reservation_identity_mismatch"),
        (
            {},
            {"workflow_digest": "wd" + "9" * 14},
            ReplayAction.REFUSE,
            "reservation_identity_mismatch",
        ),
        (
            {},
            {"input_digest": "id" + "9" * 14},
            ReplayAction.REFUSE,
            "reservation_identity_mismatch",
        ),
        # D01 — unknown / ambiguous / multi-claim claims refuse with 0 POST.
        ({}, {"resolution": "unknown"}, ReplayAction.REFUSE, "identity_proof_unknown"),
        ({}, {"resolution": "ambiguous"}, ReplayAction.REFUSE, "identity_proof_ambiguous"),
        ({}, {"resolution": "multi_claim"}, ReplayAction.REFUSE, "identity_proof_multi_claim"),
        ({}, {"integrity": False}, ReplayAction.REFUSE, "identity_proof_integrity_failed"),
        (
            {"server_epoch": None, "workspace_id": None, "output_contract_digest": None},
            {},
            ReplayAction.REFUSE,
            "reservation_identity_incomplete",
        ),
        # submit-state ordering, retained from the previous round
        (
            {"submit_state": "ambiguous", "prompt_id": None},
            {},
            ReplayAction.REFUSE,
            "unresolved_ambiguous_reservation",
        ),
        (
            {"submit_state": "inflight", "prompt_id": None},
            {},
            ReplayAction.REFUSE,
            "reservation_not_acked_no_second_submit",
        ),
        (
            {"submit_state": "outstanding", "prompt_id": None},
            {},
            ReplayAction.REFUSE,
            "reservation_not_acked_no_second_submit",
        ),
    ],
)
def test_unresolved_replay_never_duplicates_the_post(
    reservation_kwargs: dict[str, object],
    proof_kwargs: dict[str, object],
    expected_action: ReplayAction,
    expected_reason: str,
) -> None:
    decision = resolve_replay(
        make_reservation(**reservation_kwargs), proof=make_proof(**proof_kwargs)
    )
    assert decision.action is expected_action
    assert decision.reason_code == expected_reason
    # The load-bearing assertion: no branch can ever issue a POST.
    assert decision.issues_post is False


def test_reservation_identity_is_epoch_bound_but_the_cache_is_not() -> None:
    """D04 — the reservation identity and the cache identity differ on the epoch."""

    assert set(RESERVATION_IDENTITY_FIELDS) == {
        "attempt_id",
        "job_id",
        "stage",
        "workspace_id",
        "owner_session",
        "server_epoch",
        "workflow_digest",
        "input_digest",
        "output_contract_digest",
    }
    assert "server_epoch" not in IDENTITY_COMPONENT_FIELDS
    assert reservation_identity_for(make_reservation(server_epoch="epoch-7")) != (
        reservation_identity_for(make_reservation(server_epoch="epoch-8"))
    )
    assert reservation_identity_for(make_reservation()) == reservation_identity_for(
        make_reservation()
    )
    assert reservation_identity_for(make_reservation(owner_session="someone-else")) != (
        reservation_identity_for(make_reservation())
    )


def test_a_decision_that_would_post_is_refused_by_construction() -> None:
    with pytest.raises(MediaEngineRefusal) as exc:
        ReplayDecision(
            action=ReplayAction.RE_ATTACH,
            reservation=make_reservation(),
            reason_code="re_attach_acked_prompt",
            issues_post=True,
        )
    assert exc.value.code is MediaEngineRefusalCode.REPLAY_REFUSED


def test_reservation_invariants_are_enforced() -> None:
    with pytest.raises(ValueError):
        make_reservation(submit_state="acked", prompt_id=None)
    with pytest.raises(ValueError):
        make_reservation(submit_state="inflight", prompt_id="prompt-1")
    with pytest.raises(ValueError):
        make_reservation(submit_state="pending", prompt_id=None)


# ── 5. result DTO + lifecycle states ──────────────────────────────────────────


def make_result(
    state: MediaEngineState = MediaEngineState.GENERATED,
    publishable: bool = True,
    failure: MediaEngineFailure | None = None,
    cancel: MediaEngineCancel | None = None,
) -> MediaEngineResult:
    request = make_request()
    return MediaEngineResult(
        prompt_id="prompt-1",
        server_epoch="epoch-7",
        owner_session="session-owner",
        lease_id="lease-1",
        capability=request.capability,
        identity=cache_identity_for(request),
        pins=request.pins,
        artifacts=(
            ManagedArtifact(
                artifact_id="art-out-1",
                kind="video",
                media_type="video/mp4",
                sha256=SHA_D,
                store_relative_path="renders/out.mp4",
                size_bytes=1_645_695,
                publishable=publishable,
            ),
        ),
        decoded=DecodedMap(
            decoded_frames=4,
            first_pts_ticks=0,
            timebase="1/15360",
            mapping=(0, 1, 2, 3),
        ),
        audio=AudioHandoff(mode="generated", sample_rate=44100, channels=2, codec="aac"),
        state=state,
        failure=failure,
        cancel=cancel,
    )


def test_result_carries_prompt_epoch_and_ownership() -> None:
    result = make_result()
    assert (result.prompt_id, result.server_epoch, result.owner_session) == (
        "prompt-1",
        "epoch-7",
        "session-owner",
    )
    assert result.lease_id == "lease-1"
    assert result.state is MediaEngineState.GENERATED
    assert result.pins.seed == 1234
    assert result.artifacts[0].sha256 == SHA_D
    assert result.decoded.timebase == "1/15360"
    assert result.audio.mode == "generated"


def test_result_states_are_distinct_and_ordered() -> None:
    assert [s.value for s in MediaEngineState] == [
        "generated",
        "validated",
        "reviewed",
        "accepted",
        "published",
    ]
    assert STATE_ORDER == tuple(MediaEngineState)
    assert len(set(STATE_ORDER)) == 5


def test_publication_requires_acceptance_and_a_publishable_artifact() -> None:
    with pytest.raises(MediaEngineRefusal) as exc:
        StateTransition(
            from_state=MediaEngineState.GENERATED, to_state=MediaEngineState.PUBLISHED
        )
    assert exc.value.code is MediaEngineRefusalCode.STATE_TRANSITION_REFUSED

    StateTransition(from_state=MediaEngineState.ACCEPTED, to_state=MediaEngineState.PUBLISHED)
    StateTransition(from_state=MediaEngineState.GENERATED, to_state=MediaEngineState.VALIDATED)

    with pytest.raises(MediaEngineRefusal):
        StateTransition(
            from_state=MediaEngineState.PUBLISHED, to_state=MediaEngineState.ACCEPTED
        )

    with pytest.raises(ValueError):
        make_result(state=MediaEngineState.PUBLISHED, publishable=False)

    published = make_result(state=MediaEngineState.PUBLISHED, publishable=True)
    assert published.state is MediaEngineState.PUBLISHED

    assert STATE_TRANSITION_TABLE[MediaEngineState.PUBLISHED] == ()


def test_terminal_results_are_typed_not_booleans() -> None:
    failed = make_result(
        failure=MediaEngineFailure(code="upstream_timeout", message="no response", retryable=True)
    )
    cancelled = make_result(
        cancel=MediaEngineCancel(requested_by="user-1", reason="wrong cast", at_utc="2026-09-23T09:00:00Z")
    )
    assert failed.failure is not None and failed.failure.retryable is True
    assert cancelled.cancel is not None and cancelled.failure is None
    assert failed.cancel is None

    with pytest.raises(ValueError):
        make_result(
            failure=MediaEngineFailure(code="x", message="y"),
            cancel=MediaEngineCancel(requested_by="u", reason="r", at_utc="2026-09-23T09:00:00Z"),
        )
    with pytest.raises(ValueError):
        make_result(state=MediaEngineState.PUBLISHED, failure=MediaEngineFailure(code="x", message="y"))


def test_decoded_map_must_be_consistent() -> None:
    DecodedMap(decoded_frames=2, first_pts_ticks=0, timebase="1/15360", mapping=(0, 1))
    with pytest.raises(ValueError):
        DecodedMap(decoded_frames=2, first_pts_ticks=0, timebase="1/15360", mapping=(0,))
    with pytest.raises(ValueError):
        DecodedMap(decoded_frames=1, first_pts_ticks=0, timebase="1/15360", mapping=(-1,))


def test_audio_handoff_is_typed_not_implicit() -> None:
    assert AudioHandoff(mode="source_remux", source_artifact_id="art-src").mode == "source_remux"
    with pytest.raises(ValueError):
        AudioHandoff(mode="source_remux")
    with pytest.raises(ValueError):
        AudioHandoff(mode="passthrough")


# ── 6. model registry ─────────────────────────────────────────────────────────


def make_entry(
    role: str = "video_transfer",
    available: bool = True,
    reason: str | None = None,
    release_date: str = "2025-06-01",
    repo_modified_date: str | None = "2026-09-10",
    capabilities: tuple[MediaCapability, ...] = (MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER,),
    operator_action: bool = True,
) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        role=role,
        model_id="wan-animate-2",
        revision="rev-1",
        file_sha256=SHA_C,
        precision="int8",
        capabilities=capabilities,
        hardware=(
            HardwareProfile(
                device="RTX 5070 12GB",
                vram_bytes=12 * 1024**3,
                measured_seconds_per_output_second=34.0,
                measured_at_utc="2026-09-22T10:00:00Z",
                evidence_source="measured_live",
            ),
        ),
        release_date=release_date,
        repo_modified_date=repo_modified_date,
        license_id="apache-2.0",
        available=available,
        unavailable_reason_code=reason if not available else None,
        download_requires_operator_action=operator_action,
    )


def test_release_date_and_repo_modification_date_are_different_facts() -> None:
    entry = make_entry()
    assert entry.release_date != entry.repo_modified_date
    assert str(entry.release_date) == "2025-06-01"
    assert str(entry.repo_modified_date) == "2026-09-10"
    assert entry.dates_are_distinct_facts is True
    assert make_entry(repo_modified_date=None).dates_are_distinct_facts is True


def test_registry_entry_records_measured_hardware_profile() -> None:
    hardware = make_entry().hardware[0]
    assert hardware.device == "RTX 5070 12GB"
    assert hardware.measured_seconds_per_output_second == 34.0
    assert hardware.evidence_source == "measured_live"
    with pytest.raises(ValueError):
        HardwareProfile(device="d", vram_bytes=1, evidence_source="measured_live")


def test_registry_availability_is_explicit() -> None:
    with pytest.raises(ValueError):
        ModelRegistryEntry(
            role="r",
            model_id="m",
            revision="1",
            file_sha256=SHA_C,
            precision="fp16",
            capabilities=(MediaCapability.TEXT_TO_VIDEO,),
            hardware=(),
            release_date="2025-01-01",
            license_id="mit",
            available=False,
        )
    with pytest.raises(ValueError):
        ModelRegistryEntry(
            role="r",
            model_id="m",
            revision="1",
            file_sha256=SHA_C,
            precision="fp16",
            capabilities=(),
            hardware=(),
            release_date="2025-01-01",
            license_id="mit",
            available=True,
        )


def test_no_automatic_download_from_a_ui_click() -> None:
    assert NO_AUTO_DOWNLOAD_FROM_UI is True
    registry = ModelRegistry(entries=(make_entry(), make_entry(role="image_edit"),))
    for origin in ("ui_click", "api_call"):
        with pytest.raises(MediaEngineRefusal) as exc:
            registry.request_download(role="video_transfer", origin=origin)
        assert exc.value.code is MediaEngineRefusalCode.AUTO_DOWNLOAD_REFUSED

    with pytest.raises(MediaEngineRefusal) as exc:
        make_entry(operator_action=False)
    assert exc.value.code is MediaEngineRefusalCode.AUTO_DOWNLOAD_REFUSED


def test_registry_lookup_refuses_an_unavailable_role() -> None:
    registry = ModelRegistry(
        entries=(
            make_entry(role="video_transfer", available=False, reason="file_hash_mismatch"),
            make_entry(
                role="image_edit", capabilities=(MediaCapability.IMAGE_EDIT_MULTI_REFERENCE,)
            ),
        )
    )
    assert len(registry.for_capability(MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER)) == 1
    assert len(registry.for_capability(MediaCapability.TEXT_TO_VIDEO)) == 0

    with pytest.raises(MediaEngineRefusal) as exc:
        registry.require_available("video_transfer")
    assert exc.value.code is MediaEngineRefusalCode.MODEL_UNAVAILABLE
    assert "file_hash_mismatch" in exc.value.detail

    assert registry.require_available("image_edit").role == "image_edit"

    with pytest.raises(MediaEngineRefusal):
        registry.require_available("nobody")


# ── 7. one job store, one concurrency engine, one shared GPU lease ────────────


def test_second_job_store_and_competing_engine_are_refused() -> None:
    assert_shared_stack(job_store=E01_JOB_STORE, concurrency_engine=E01_JOB_STORE)

    with pytest.raises(MediaEngineRefusal) as exc:
        assert_shared_stack(job_store="media_engine_jobs", concurrency_engine=E01_JOB_STORE)
    assert exc.value.code is MediaEngineRefusalCode.SECOND_JOB_STORE_REFUSED

    with pytest.raises(MediaEngineRefusal) as exc2:
        assert_shared_stack(job_store=E01_JOB_STORE, concurrency_engine="engine_v2")
    assert exc2.value.code is MediaEngineRefusalCode.COMPETING_CONCURRENCY_ENGINE_REFUSED

    with pytest.raises(MediaEngineRefusal):
        GpuLeaseView(job_store="media_engine_jobs")


def test_one_shared_gpu_lease_serializes_image_and_video_jobs() -> None:
    view = GpuLeaseView()
    assert view.job_store == view.concurrency_engine == E01_JOB_STORE
    assert view.holder is None and view.queue == ()

    def request(job_id: str) -> GpuLeaseRequest:
        return GpuLeaseRequest(
            job_id=job_id,
            owner_session="session-owner",
            capability=MediaCapability.VIDEO_EDIT_CONTROLLED,
            budget=ResourceBudget(
                resource_class="gpu",
                max_wall_seconds=60.0,
                max_vram_bytes=1024,
                max_output_bytes=1024,
            ),
        )

    first = view.decide(request("job-image"), lease_id="lease-1", expires_at_utc="2030-01-01T00:00:00Z")
    assert first.granted is True and first.view.holder is not None
    assert first.view.holder.job_id == "job-image"
    assert first.view.holder.expired_at("2029-01-01T00:00:00Z") is False
    assert first.view.holder.expired_at("2030-01-01T00:00:01Z") is True

    second = first.view.decide(
        request("job-video"), lease_id="lease-2", expires_at_utc="2030-01-01T00:01:00Z"
    )
    assert second.granted is False
    assert second.queue == ("job-video",)
    assert second.view.holder is not None and second.view.holder.job_id == "job-image"

    with pytest.raises(ValueError):
        GpuLeaseView(holder=first.view.holder, queue=("job-image",))
    with pytest.raises(ValueError):
        GpuLeaseView(queue=("job-a", "job-a"))


def test_lease_grant_rejects_a_non_iso_expiry() -> None:
    # The lease request itself carries no expiry (E01 owns it) — an unknown
    # field is refused rather than ignored.
    with pytest.raises(ValueError):
        GpuLeaseRequest(
            job_id="j",
            owner_session="s",
            capability=MediaCapability.TEXT_TO_VIDEO,
            budget=ResourceBudget(
                resource_class="gpu", max_wall_seconds=1.0, max_vram_bytes=0, max_output_bytes=1
            ),
            expires_at_utc="2030-01-01T00:00:00Z",
        )

    for bad in ("tomorrow", "2030-01-01 00:00:00", "2030-01-01T00:00:00+07:00"):
        with pytest.raises(ValueError):
            GpuLeaseGrant(
                lease_id="l",
                job_id="j",
                owner_session="s",
                resource_class="gpu",
                expires_at_utc=bad,
            )
    assert (
        GpuLeaseGrant(
            lease_id="l",
            job_id="j",
            owner_session="s",
            resource_class="gpu",
            expires_at_utc="2030-01-01T00:00:00Z",
        ).expired_at("2029-12-31T23:59:59Z")
        is False
    )


# ── 8. the module stays pure (no DB, no queue, no second engine) ──────────────


def test_module_imports_no_persistence_or_network_libraries() -> None:
    """The contract module may not reach for a DB, a queue or the network."""

    source = Path("app/schemas/media_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"sqlalchemy", "requests", "httpx", "app", "subprocess", "socket", "asyncio"}
    assert imported & forbidden == set()
    assert imported <= {
        "__future__",
        "hashlib",
        "json",
        "datetime",
        "enum",
        "fractions",
        "typing",
        "pydantic",
    }

    body = source.lower()
    for needle in ("create_engine(", "sessionmaker(", "redis", "celery", "threading"):
        assert needle not in body, f"{needle} would create a second engine"
