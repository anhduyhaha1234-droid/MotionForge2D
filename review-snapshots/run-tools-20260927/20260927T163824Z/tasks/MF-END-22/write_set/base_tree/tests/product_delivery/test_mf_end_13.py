"""MF-END-13 — producer contact/occlusion/camera của nguồn: acceptance + negatives.

Row map (binary; every row is CI-labelled and derived from REAL pixels):
* micro repro: module surface + typed codes + the thresholds the SEALED artifact
  echoes must equal the module constants (the numbers tests rely on cannot drift);
* contact rows: a HELD prop (contained in the person box) yields ONE measured
  grasp fact; a prop measured far away yields a measured NEGATIVE (no fact,
  no blocked row); a pair with no shared visible frame is MISSING DATA with a
  position (U21);
* occlusion rows: the visible-containment cue binds order prop->person from
  real pixels; an occlusion RUN with a real overlapping track binds the
  occluder; a run with NO real candidate is blocked (an occluder is never
  invented) — "không fake second segment" starts here;
* camera rows: static window reads static with the content change measured as
  an EVENT (never a cut); a hard change reads as a CUT and the measured
  segment order is asserted (declared order compared, config never creates a
  fact); a shifting window reads PAN with the measured direction, and the
  mirrored fixture proves the direction is directional; a uniform window reads
  UNSUPPORTED with a blocked position and is never publishable;
* publish rows (isolated DB): facts publish ONLY through the structural-evidence
  repository; both endpoints must be real segments (a missing one refuses with
  SOURCE_FACTS_SECOND_SEGMENT_MISSING and creates NOTHING); a replayed publish
  converges (created 0); a CI artifact can never publish (NOT_PRODUCTION); the
  camera motion is clipped to each bound segment's own range;
* lock rows: the StructuralLockProducer freezes the published facts and refuses
  when their sealed source identity disagrees with the manifest source
  (immutable source facts are never re-bound to another source);
* overwrite rows: an OUTPUT-side claim that contradicts a sealed source fact is
  refused; agreement is allowed; an unknown fact id is refused.

The CI fixture media is synthesized in-process (tiny 160x120 frames — NOT
product output; labelled CI in every artifact).  The REAL run over the
MF-END-12 tracks + the four real source windows lives in the task evidence
harness, which is where a production claim must come from.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient  # noqa: F401  (fixture dependency)

from app.api import deps
from app.persistence import (
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import Artifact, Job, ObjectRole, Project, Scene, VideoItem, Workspace
from app.persistence.structural_evidence import (
    StructuralEvidenceRepository,
    canonical_json,
)
from app.services import source_interaction_facts as sif
from app.services import source_role_tracks as srt
from app.services.structural_lock_producer import (
    CODE_SOURCE_FACTS_SOURCE_MISMATCH,
    ProducerValidationError,
    StructuralLockProducer,
)

W, H = 160, 120
BG = (30, 30, 30)
PERSON = (255, 64, 64)
PROP = (64, 64, 255)
BAR = (0, 0, 0)
FRAMES = 12
SPAN = (0, FRAMES)
WS = DEFAULT_WORKSPACE_ID
API = "/api/v2/structural-evidence"
GEN = "3"

PERSON_BOX = (20, 30, 30, 40)  # x, y, w, h — held prop sits inside this box
PROP_BOX = (30, 42, 10, 12)
FAR_BOX = (120, 20, 12, 12)
BAR_BOX = (16, 26, 24, 52)  # solid occluder; its box overlaps the person seed box
BARVIS = (70, 70, 70)
OCCLUDED = (4, 8)  # person is behind the bar on frames [4, 8)


# ── CI fixture media (real pixels, deterministic) ────────────────────────────


def _paint(frame: np.ndarray, box: tuple[int, int, int, int], colour) -> None:
    x, y, w, h = box
    frame[y : y + h, x : x + w] = colour


def _base_texture(seed: int = 7) -> np.ndarray:
    """Low-contrast deterministic texture (gives the camera path real signal)."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(-8, 9, size=(H // 4, W // 4), dtype=np.int16)
    up = np.kron(noise, np.ones((4, 4), dtype=np.int16))
    img = np.clip(np.int16(90) + up, 0, 255).astype(np.uint8)
    return np.stack([img, img, img], axis=-1)


def _frames_held() -> list[np.ndarray]:
    out = []
    for _ in range(FRAMES):
        frame = _base_texture()
        _paint(frame, PERSON_BOX, PERSON)
        _paint(frame, PROP_BOX, PROP)
        out.append(frame)
    return out


def _frames_far() -> list[np.ndarray]:
    out = []
    for _ in range(FRAMES):
        frame = _base_texture()
        _paint(frame, PERSON_BOX, PERSON)
        _paint(frame, FAR_BOX, PROP)
        out.append(frame)
    return out


def _frames_held_with_bar() -> list[np.ndarray]:
    out = []
    for index in range(FRAMES):
        frame = _base_texture()
        _paint(frame, PERSON_BOX, PERSON)
        if OCCLUDED[0] <= index < OCCLUDED[1]:
            _paint(frame, PERSON_BOX, BARVIS)  # the person is fully behind the bar
        _paint(frame, BAR_BOX, BARVIS)  # solid occluder over the person's left part
        _paint(frame, PROP_BOX, PROP)  # the held prop stays visible above the bar
        out.append(frame)
    return out


def _frames_conflict() -> list[np.ndarray]:
    """Person declared [0,4) and prop [6,12): no shared visible frame."""
    out = []
    for index in range(FRAMES):
        frame = _base_texture()
        if index < 4:
            _paint(frame, PERSON_BOX, PERSON)
        if index >= 6:
            _paint(frame, PROP_BOX, PROP)
        out.append(frame)
    return out


def _cam_static() -> list[np.ndarray]:
    frame = _base_texture()
    return [frame.copy() for _ in range(FRAMES)]


def _cam_event() -> list[np.ndarray]:
    """A moderate in-frame change: above the event floor, below the cut floor."""
    out = []
    for index in range(FRAMES):
        frame = _base_texture()
        if index >= 6:
            frame[40:70, 40:70] = (240, 240, 240)
        out.append(frame)
    return out


def _cam_cut() -> list[np.ndarray]:
    out = []
    for index in range(FRAMES):
        if index < 6:
            out.append(_base_texture())
        else:
            frame = _base_texture(seed=99)
            frame[:, :] = (250, 250, 250)
            out.append(frame)
    return out


def _cam_pan(step: int = 2) -> list[np.ndarray]:
    wide = _base_texture(seed=3)
    canvas = np.concatenate([wide, wide, wide], axis=1)
    out = []
    for index in range(FRAMES):
        left = (index * step) % W
        out.append(canvas[:, left : left + W].copy())
    return out


def _cam_uniform() -> list[np.ndarray]:
    frame = np.full((H, W, 3), 20, dtype=np.uint8)
    return [frame.copy() for _ in range(FRAMES)]


# ── track fixtures (real pixels through the MF-END-12 mask-source protocol)───


class CiBoxMaskSource:
    """CI mask source: masks come from the drawn pixels, never from the seed box."""

    provenance = srt.PROVENANCE_FIXTURE
    engine_id = "contour"
    probe = None
    candidates = {"sam3": srt.STATUS_NOT_RUN}
    inference_ran = False

    def __init__(self, colour: tuple[int, int, int], box: tuple[int, int, int, int]) -> None:
        self.colour = colour
        self.box = box

    def sample(self, frame_index: int, seed: srt.RoleSeed, frame: np.ndarray):
        target = np.array(self.colour, dtype=np.uint8)
        mask = np.all(np.abs(frame.astype(np.int16) - target) <= 2, axis=-1).astype(np.uint8) * 255
        if mask.any():
            return srt.MaskSample(mask=mask, method="cv2_colour_seed", score=None)
        x, y, w, h = self.box
        return srt.MaskSample(mask=None, method="cv2_absent_rule", out_of_frame=True)


class CiTwoTargetSource:
    """One mask source serving both the person and the prop seed."""

    provenance = srt.PROVENANCE_FIXTURE
    engine_id = "contour"
    probe = None
    candidates = {"sam3": srt.STATUS_NOT_RUN}
    inference_ran = False

    def sample(self, frame_index: int, seed: srt.RoleSeed, frame: np.ndarray):
        colour = PERSON if seed.kind == srt.ROLE_KIND_PERSON else PROP
        if seed.role_id == "OCC-BAR":
            colour = (70, 70, 70)
        target = np.array(colour, dtype=np.uint8)
        mask = np.all(np.abs(frame.astype(np.int16) - target) <= 2, axis=-1).astype(np.uint8) * 255
        if mask.any():
            return srt.MaskSample(mask=mask, method="cv2_colour_seed", score=None)
        return srt.MaskSample(mask=None, method="cv2_absent_rule", out_of_frame=True)


class CiOccludedPersonSource:
    """Person: real mask when drawn; during the bar window the source asserts
    PRESENT with no usable mask (the occlusion-run protocol)."""

    provenance = srt.PROVENANCE_FIXTURE
    engine_id = "contour"
    probe = None
    candidates = {"sam3": srt.STATUS_NOT_RUN}
    inference_ran = False

    def sample(self, frame_index: int, seed: srt.RoleSeed, frame: np.ndarray):
        if seed.role_id == "OCC-BAR":
            target = np.array(BARVIS, dtype=np.uint8)
        elif seed.role_id == "PROP-B":
            target = np.array(PROP, dtype=np.uint8)
        else:
            target = np.array(PERSON, dtype=np.uint8)
        mask = np.all(np.abs(frame.astype(np.int16) - target) <= 2, axis=-1).astype(np.uint8) * 255
        if mask.any():
            return srt.MaskSample(mask=mask, method="cv2_colour_seed", score=None)
        if seed.role_id != "OCC-BAR" and OCCLUDED[0] <= frame_index < OCCLUDED[1]:
            return srt.MaskSample(mask=None, method="cv2_present_rule", present=True)
        return srt.MaskSample(mask=None, method="cv2_absent_rule", out_of_frame=True)


def _seed(role_id: str, kind: str, box, *, declare=SPAN, partial=False) -> srt.RoleSeed:
    return srt.RoleSeed(
        role_id=role_id,
        kind=kind,
        box=tuple(box),  # type: ignore[arg-type]
        declare_frames=declare,
        partial_required=partial,
    )


def _tracks(frames, seeds, mask_source, *, source_sha="0" * 64):
    return srt.build_role_tracks(
        source_sha256=source_sha,
        span=srt.SourceSpan(start_frame=0, end_frame_exclusive=len(frames)),
        frames=frames,
        fps_rational="10/1",
        seeds=seeds,
        mask_source=mask_source,
        manifest_sha256=srt.payload_sha256({"manifest": "ci"}),
        manifest_version="1.0.0",
        production=False,
        strict=True,
    )


def _seal(payload: dict, *, production: bool) -> sif.FactSet:
    """Re-seal a CI payload (the publish machinery is what these rows test)."""
    body = {k: v for k, v in payload.items() if k != "digest"}
    body["production"] = production
    body["digest"] = sif.payload_sha256(body)
    return sif.FactSet(payload=body)


def _held_artifact(*, production=False, window=None):
    tracks = _tracks(
        _frames_held(),
        [
            _seed("ROLE-P", srt.ROLE_KIND_PERSON, PERSON_BOX),
            _seed("PROP-B", srt.ROLE_KIND_PROP, PROP_BOX),
        ],
        CiTwoTargetSource(),
    )
    windows = []
    if window is not None:
        windows.append(
            {
                "window_id": "W1",
                "frames": window,
                "span": {"start_frame": 0, "end_frame_exclusive": len(window)},
                "source_sha256": "0" * 64,
            }
        )
    artifact = sif.build_artifact(
        tracks=tracks, windows=windows, require_production=False
    )
    return _seal(artifact.to_payload(), production=production) if production else artifact


# ── rows: micro repro + artifact integrity ───────────────────────────────────


def test_micro_repro_module_surface_and_sealed_thresholds() -> None:
    assert sif.SCHEMA_VERSION == "mf.source_interaction_facts.v1"
    assert sif.POLICY_VERSION == "source-interaction-facts-v1"
    assert sif.ALGORITHM == "source-interaction-facts"
    for code in (
        sif.CODE_MISSING_DATA,
        sif.CODE_OCCLUDER_UNMEASURED,
        sif.CODE_SECOND_SEGMENT_MISSING,
        sif.CODE_NOT_PRODUCTION,
        sif.CODE_FACT_CONFLICT,
        sif.CODE_OUTPUT_OVERWRITE,
        sif.CODE_DIGEST_MISMATCH,
        sif.CODE_CROP_MISMATCH,
    ):
        assert code.startswith("SOURCE_FACTS_")
    payload = _held_artifact(window=_cam_static()).to_payload()
    assert payload["thresholds"] == {
        "contact_max_gap_px": sif.CONTACT_MAX_GAP_PX,
        "contact_min_containment": sif.CONTACT_MIN_CONTAINMENT,
        "contact_min_frames": sif.CONTACT_MIN_FRAMES,
        "occlusion_min_containment": sif.OCCLUSION_MIN_CONTAINMENT,
        "occlusion_min_visible_frames": sif.OCCLUSION_MIN_VISIBLE_FRAMES,
        "state_change_area_ratio": sif.STATE_CHANGE_AREA_RATIO,
        "state_change_shift_px": sif.STATE_CHANGE_SHIFT_PX,
        "camera_border_fraction": sif.CAMERA_BORDER_FRACTION,
        "camera_static_max_px_per_frame": sif.CAMERA_STATIC_MAX_PX_PER_FRAME,
        "camera_pan_min_px_per_frame": sif.CAMERA_PAN_MIN_PX_PER_FRAME,
        "camera_cut_min_mad": sif.CAMERA_CUT_MIN_MAD,
        "camera_event_min_mad": sif.CAMERA_EVENT_MIN_MAD,
        "camera_event_min_ratio": sif.CAMERA_EVENT_MIN_RATIO,
        "camera_min_response": sif.CAMERA_MIN_RESPONSE,
    }
    assert sif.check_artifact(_held_artifact()) == ()
    assert payload["source"]["sha256"] == "0" * 64
    assert payload["production"] is False


def test_artifact_tamper_is_caught_and_reseal_of_invalid_is_refused() -> None:
    payload = _held_artifact().to_payload()
    tampered = dict(payload)
    tampered["contacts"] = [dict(item) for item in payload["contacts"]]
    tampered["contacts"][0]["measured"] = {"frames": 1}
    assert sif.CODE_DIGEST_MISMATCH in sif.check_artifact(tampered)

    stolen = {k: v for k, v in tampered.items() if k != "digest"}
    stolen["digest"] = sif.payload_sha256(stolen)
    violations = sif.check_artifact(stolen)
    assert sif.CODE_MISSING_DATA in violations  # re-sealing cannot legalise it

    broken = {k: v for k, v in payload.items() if k != "digest"}
    broken["contacts"] = [{**payload["contacts"][0], "evidence": {}}]
    broken["digest"] = sif.payload_sha256(broken)
    assert sif.CODE_ARTIFACT_INVALID in sif.check_artifact(broken)


# ── rows: contacts ───────────────────────────────────────────────────────────


def test_held_prop_yields_one_measured_grasp_fact() -> None:
    payload = _held_artifact().to_payload()
    assert len(payload["contacts"]) == 1
    fact = payload["contacts"][0]
    assert fact["subject_role_id"] == "ROLE-P"
    assert fact["object_role_id"] == "PROP-B"
    assert fact["kind"] == sif.CONTACT_KIND_GRASP
    assert (fact["start_frame"], fact["end_frame"]) == (0, FRAMES)
    assert fact["measured"]["min_gap_px"] == 0.0
    assert fact["measured"]["mean_containment"] >= sif.CONTACT_MIN_CONTAINMENT
    assert fact["confidence"] == fact["measured"]["mean_containment"]
    assert fact["confidence_source"] == "derived"
    assert fact["evidence"]["mask_sha256_first"]
    assert payload["blocked"] == []


def test_far_prop_is_a_measured_negative_not_a_blocked_row() -> None:
    artifact = _held_artifact()  # placeholder to keep the fixture warm
    assert artifact is not None
    tracks = _tracks(
        _frames_far(),
        [
            _seed("ROLE-P", srt.ROLE_KIND_PERSON, PERSON_BOX),
            _seed("PROP-B", srt.ROLE_KIND_PROP, FAR_BOX),
        ],
        CiTwoTargetSource(),
    )
    payload = sif.build_artifact(tracks=tracks, require_production=False).to_payload()
    assert payload["contacts"] == []
    assert payload["blocked"] == []
    assert payload["occlusions"] == []


def test_pair_without_shared_frames_is_blocked_with_position() -> None:
    tracks = _tracks(
        _frames_conflict(),
        [
            _seed("ROLE-P", srt.ROLE_KIND_PERSON, PERSON_BOX, declare=(0, 4)),
            _seed("PROP-B", srt.ROLE_KIND_PROP, PROP_BOX, declare=(6, FRAMES)),
        ],
        CiTwoTargetSource(),
    )
    payload = sif.build_artifact(tracks=tracks, require_production=False).to_payload()
    assert payload["contacts"] == []
    blocked = [item for item in payload["blocked"] if item["kind"] == "contact"]
    assert len(blocked) == 1
    assert blocked[0]["code"] == sif.CODE_MISSING_DATA
    assert blocked[0]["position"]["subject_role_id"] == "ROLE-P"
    assert blocked[0]["position"]["object_role_id"] == "PROP-B"


# ── rows: occlusions ─────────────────────────────────────────────────────────


def test_visible_containment_binds_occlusion_order_from_pixels() -> None:
    payload = _held_artifact().to_payload()
    assert len(payload["occlusions"]) == 1
    fact = payload["occlusions"][0]
    assert fact["occluder_role_id"] == "PROP-B"
    assert fact["occludee_role_id"] == "ROLE-P"
    assert fact["order"] == "in_front_of"
    assert fact["measured"]["cue"] == "visible_containment"
    assert fact["measured"]["mean_containment"] >= sif.OCCLUSION_MIN_CONTAINMENT
    assert (fact["start_frame"], fact["end_frame"]) == (0, FRAMES)


def test_occlusion_run_binds_the_real_occluder_and_never_invents_one() -> None:
    seeds = [
        _seed("ROLE-P", srt.ROLE_KIND_PERSON, PERSON_BOX, partial=True),
        _seed("PROP-B", srt.ROLE_KIND_PROP, PROP_BOX),
    ]
    with_bar = _tracks(
        _frames_held_with_bar(),
        [*seeds, _seed("OCC-BAR", srt.ROLE_KIND_PROP, BAR_BOX)],
        CiOccludedPersonSource(),
    )
    fact = next(
        item for item in with_bar.tracks if item.role_id == "ROLE-P"
    )
    assert fact.occlusion_runs, "the fixture must produce a real occlusion run"
    payload = sif.build_artifact(tracks=with_bar, require_production=False).to_payload()
    runs = [
        item
        for item in payload["occlusions"]
        if item["measured"].get("cue") == "occlusion_run"
    ]
    assert len(runs) == 1
    assert runs[0]["occluder_role_id"] == "OCC-BAR"
    assert runs[0]["occludee_role_id"] == "ROLE-P"
    assert runs[0]["order"] == "in_front_of"
    assert runs[0]["evidence"]["reference"] == "seed_box"
    assert runs[0]["measured"]["overlap_ratio"] >= sif.OCCLUSION_MIN_CONTAINMENT
    assert (runs[0]["start_frame"], runs[0]["end_frame"]) == OCCLUDED

    # Same pixels WITHOUT the bar track: no real candidate -> blocked, no fact.
    without_bar = _tracks(
        _frames_held_with_bar(), seeds, CiOccludedPersonSource()
    )
    bare = sif.build_artifact(tracks=without_bar, require_production=False).to_payload()
    assert [
        item
        for item in bare["occlusions"]
        if item["measured"].get("cue") == "occlusion_run"
    ] == []
    blocked = [item for item in bare["blocked"] if item["code"] == sif.CODE_OCCLUDER_UNMEASURED]
    assert len(blocked) == 1
    assert blocked[0]["position"]["occludee_role_id"] == "ROLE-P"
    assert blocked[0]["position"]["start_frame"] == OCCLUDED[0]


# ── rows: camera / scene motion ──────────────────────────────────────────────


def _camera(window_id: str, frames: list[np.ndarray], **kwargs):
    return sif.estimate_camera(
        window_id,
        frames,
        span={"start_frame": 0, "end_frame_exclusive": len(frames)},
        **kwargs,
    )


def test_static_window_measures_content_change_as_event_not_cut() -> None:
    fact, blocked = _camera("S", _cam_event())
    assert fact.classification == sif.CLASS_STATIC
    assert fact.cut_frames == ()
    assert 6 in fact.content_events
    assert fact.content_motion["method"] == "phase_correlation_centre"
    assert all(seg["classification"] == "static" for seg in fact.content_motion["segments"])
    assert fact.segments_order == ((0, FRAMES),)
    assert fact.samples
    assert blocked == ()
    assert fact.publishable is True


def test_hard_change_reads_as_cut_with_measured_segment_order() -> None:
    fact, _ = _camera("C", _cam_cut())
    assert fact.cut_frames == (6,)
    assert fact.segments_order == ((0, 6), (6, FRAMES))
    assert fact.border_drift["skipped_cut_boundary_frames"] >= 1
    checks = sif.compare_declared(
        (),
        (),
        (fact,),
        {"cut_order": {"window_id": "C", "first_segment": 0}},
    )
    assert checks[0]["match"] is True
    inverted = sif.compare_declared(
        (),
        (),
        (fact,),
        {"cut_order": {"window_id": "C", "first_segment": 6}},
    )
    assert inverted[0]["match"] is False
    assert inverted[0]["measured"]["segments_order"][0] == [0, 6]


def test_shifting_window_reads_pan_with_directional_angle() -> None:
    # A camera panning right moves the CONTENT left in the frame and vice versa:
    # the measured direction must follow the content, and the mirrored fixture
    # proves the direction is directional (not a constant).
    content_left, _ = _camera("CL", _cam_pan(step=2))
    content_right, _ = _camera("CR", _cam_pan(step=-2))
    assert content_left.classification == sif.CLASS_PAN
    assert content_right.classification == sif.CLASS_PAN
    assert (
        content_left.border_drift["px_per_frame_median"]
        >= sif.CAMERA_PAN_MIN_PX_PER_FRAME
    )
    left_angle = content_left.border_drift["direction_deg"]
    right_angle = content_right.border_drift["direction_deg"]
    assert abs(abs(left_angle) - 180.0) <= 20.0, left_angle
    assert abs(right_angle) <= 20.0, right_angle
    delta = abs((left_angle - right_angle + 180.0) % 360.0 - 180.0)
    assert delta >= 120.0, (left_angle, right_angle)


def test_uniform_window_is_unsupported_with_position_and_never_published() -> None:
    fact, blocked = _camera("U", _cam_uniform())
    assert fact.classification == sif.CLASS_UNSUPPORTED
    assert fact.unsupported_reason == "no_measured_frames"
    assert fact.publishable is False
    assert len(blocked) == 1
    assert blocked[0].kind == "camera"
    assert blocked[0].code == sif.CODE_MISSING_DATA
    assert dict(blocked[0].position) == {"window_id": "U", "frame": 0}
    payload = sif.build_artifact(
        tracks=_tracks(
            _frames_held(),
            [
                _seed("ROLE-P", srt.ROLE_KIND_PERSON, PERSON_BOX),
                _seed("PROP-B", srt.ROLE_KIND_PROP, PROP_BOX),
            ],
            CiTwoTargetSource(),
        ),
        windows=[
            {
                "window_id": "U",
                "frames": _cam_uniform(),
                "span": {"start_frame": 0, "end_frame_exclusive": FRAMES},
                "source_sha256": "0" * 64,
            }
        ],
        require_production=False,
    ).to_payload()
    assert payload["camera"][0]["classification"] == sif.CLASS_UNSUPPORTED
    assert any(item["code"] == sif.CODE_MISSING_DATA for item in payload["blocked"])


def test_declared_holder_mismatch_is_flagged_never_a_fact() -> None:
    artifact = _held_artifact()
    payload = artifact.to_payload()
    contacts = sif.derive_contact_facts(
        _tracks(
            _frames_held(),
            [
                _seed("ROLE-P", srt.ROLE_KIND_PERSON, PERSON_BOX),
                _seed("PROP-B", srt.ROLE_KIND_PROP, PROP_BOX),
            ],
            CiTwoTargetSource(),
        )
    )[0]
    checks = sif.compare_declared(
        contacts,
        (),
        (),
        {"holder": {"subject_role_id": "ROLE-HACKER", "object_role_id": "PROP-B"}},
    )
    assert checks[0]["match"] is False
    assert checks[0]["measured"]["measured_holder_role_id"] == "ROLE-P"
    assert len(payload["contacts"]) == 1  # config produced no additional fact


# ── rows: output-side overwrite guard ────────────────────────────────────────


def test_output_claim_may_agree_but_never_rewrite_a_sealed_fact() -> None:
    artifact = _held_artifact()
    payload = artifact.to_payload()
    fact = payload["contacts"][0]
    fid = sif.fact_id(fact)
    sif.check_output_overwrite(
        artifact, {"origin": "output", "fact_id": fid, "value": {"kind": "grasp"}}
    )
    with pytest.raises(sif.SourceFactsError) as err:
        sif.check_output_overwrite(
            artifact, {"origin": "output", "fact_id": fid, "value": {"kind": "touch"}}
        )
    assert err.value.code == sif.CODE_OUTPUT_OVERWRITE
    with pytest.raises(sif.SourceFactsError) as missing:
        sif.check_output_overwrite(
            artifact, {"origin": "output", "fact_id": "contact:nobody", "value": {}}
        )
    assert missing.value.code == sif.CODE_UNKNOWN_FACT


# ── rows: publish through the existing authority (isolated DB) ───────────────


class _Seed:
    workspace = ""
    project = ""
    video = ""
    scene = ""
    segments: dict[str, str] = {}


def _seed_graph(session) -> _Seed:
    """Backend-authoritative generation "3" for one video (S08 conventions)."""
    seed = _Seed()
    for workspace_id in (WS,):
        if session.get(Workspace, workspace_id) is None:
            session.add(Workspace(id=workspace_id, name=workspace_id))
    session.flush()
    source = Artifact(
        workspace_id=WS, kind="video", relative_path="src.mp4", state="ready", sha256="1" * 64
    )
    session.add(source)
    session.flush()
    project = Project(workspace_id=WS, name="MF13")
    session.add(project)
    session.flush()
    video = VideoItem(
        project_id=project.id, title="MF13", position=0, source_artifact_id=source.id
    )
    session.add(video)
    session.flush()
    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video.id,
        state="completed",
        input_generation=GEN,
        input_manifest_json=canonical_json({"source_sha256": "1" * 64}),
    )
    session.add(job)
    session.flush()
    scene = Scene(
        video_item_id=video.id,
        position=0,
        start_frame=0,
        end_frame=FRAMES,
        start_time_ms=0,
        end_time_ms=1200,
        status="pending",
    )
    session.add(scene)
    session.flush()
    seed.workspace, seed.project, seed.video, seed.scene = (
        WS,
        project.id,
        video.id,
        scene.id,
    )
    repo = StructuralEvidenceRepository(session)
    for role_id, kind, (start, end) in (
        ("ROLE-P", "character", (0, FRAMES)),
        ("PROP-B", "prop", (0, FRAMES)),
        ("PROP-C2", "prop", (0, 6)),
    ):
        role = ObjectRole(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            source_generation=GEN,
            name=f"{role_id}-{kind}",
            kind=kind,
            status="confirmed",
        )
        session.add(role)
        session.flush()
        record, _ = repo.create_segment(
            WS,
            project.id,
            video.id,
            str(role.id),
            scene.id,
            f"segment-{role_id}",
            start,
            end,
            int(start * 100),
            int(end * 100),
            GEN,
            kind=kind,
            confidence_source="model",
            source_job_id=str(job.id),
        )
        seed.segments[role_id] = str(record.id)
    return seed


def _session():
    factory = create_session_factory(create_engine_for_path(deps._lifecycle_db))
    return factory()


def _http_artifact(seed: _Seed):
    """A production-marked CI payload built from the held fixture + pan window."""
    artifact = _held_artifact(window=_cam_pan(step=2))
    payload = artifact.to_payload()
    payload["source"]["sha256"] = "1" * 64
    body = {k: v for k, v in payload.items() if k != "digest"}
    body["digest"] = sif.payload_sha256(body)
    return _seal(body, production=True)


def test_publish_writes_real_rows_and_replay_converges(client) -> None:
    with _session() as session:
        seed = _seed_graph(session)
        session.commit()
        session.info["mf13"] = True
    payload = _http_artifact(seed).to_payload()
    bindings = {
        "ROLE-P": seed.segments["ROLE-P"],
        "PROP-B": seed.segments["PROP-B"],
        "PROP-C2": seed.segments["PROP-C2"],
    }
    body = {
        "project_id": seed.project,
        "video_item_id": seed.video,
        "artifact": payload,
        "bindings": bindings,
    }
    first = client.post(f"{API}/source-interaction-facts", json=body)
    assert first.status_code in (200, 201), first.text
    data = first.json()
    assert data["artifact_digest"] == payload["digest"]
    assert data["contacts_created"] == 1
    assert data["occlusions_created"] == 1
    assert data["motions_created"] == 3  # one per bound segment, clipped
    listing = client.get(
        f"{API}/source-interaction-facts", params={"video_item_id": seed.video}
    )
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows["contacts"]) == 1 and len(rows["occlusions"]) == 1
    assert len(rows["motions"]) == 3
    clipped = [m for m in rows["motions"] if m["occurrence_segment_id"] == seed.segments["PROP-C2"]]
    assert len(clipped) == 1
    assert (clipped[0]["start_frame"], clipped[0]["end_frame"]) == (0, 6)
    assert clipped[0]["transform"]["classification"] == sif.CLASS_PAN

    replay = client.post(f"{API}/source-interaction-facts", json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["contacts_created"] == 0
    assert replay.json()["contacts_replayed"] == 1
    after = client.get(
        f"{API}/source-interaction-facts", params={"video_item_id": seed.video}
    ).json()
    assert len(after["contacts"]) == 1 and len(after["motions"]) == 3


def test_publish_refuses_missing_second_segment_and_creates_nothing(client) -> None:
    with _session() as session:
        seed = _seed_graph(session)
        session.commit()
    payload = _http_artifact(seed).to_payload()
    with _session() as session:
        repo = StructuralEvidenceRepository(session)
        records, total = repo.list_segments(WS, video_item_id=seed.video)
        segments_before = {row.id for row in records}
        assert len(records) == total
    body = {
        "project_id": seed.project,
        "video_item_id": seed.video,
        "artifact": payload,
        "bindings": {"ROLE-P": seed.segments["ROLE-P"]},  # PROP-B id is absent
    }
    response = client.post(f"{API}/source-interaction-facts", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == sif.CODE_SECOND_SEGMENT_MISSING
    with _session() as session:
        repo = StructuralEvidenceRepository(session)
        rows = repo.list_source_algorithm_facts(WS, seed.video, algorithm=sif.ALGORITHM)
        assert rows == {"contacts": [], "occlusions": [], "motions": []}
        after_records, _ = repo.list_segments(WS, video_item_id=seed.video)
        assert {row.id for row in after_records} == segments_before
    # The same refusal on the service path carries the same typed code.
    with _session() as session:
        with pytest.raises(sif.SourceFactsError) as err:
            sif.publish_facts(
                session,
                workspace_id=WS,
                project_id=seed.project,
                video_item_id=seed.video,
                artifact=sif.FactSet(payload=payload),
                bindings={"ROLE-P": seed.segments["ROLE-P"]},
                segment_ranges={seed.segments["ROLE-P"]: {"start_frame": 0, "end_frame": FRAMES}},
            )
        assert err.value.code == sif.CODE_SECOND_SEGMENT_MISSING


def test_ci_artifact_can_never_publish(client) -> None:
    with _session() as session:
        seed = _seed_graph(session)
        session.commit()
    ci = _held_artifact()  # production=False (CI provenance)
    with _session() as session:
        with pytest.raises(sif.SourceFactsError) as err:
            sif.publish_facts(
                session,
                workspace_id=WS,
                project_id=seed.project,
                video_item_id=seed.video,
                artifact=ci,
                bindings={
                    "ROLE-P": seed.segments["ROLE-P"],
                    "PROP-B": seed.segments["PROP-B"],
                },
                segment_ranges={
                    seed.segments["ROLE-P"]: {"start_frame": 0, "end_frame": FRAMES},
                    seed.segments["PROP-B"]: {"start_frame": 0, "end_frame": FRAMES},
                },
            )
        assert err.value.code == sif.CODE_NOT_PRODUCTION
    with _session() as session:
        rows = StructuralEvidenceRepository(session).list_source_algorithm_facts(
            WS, seed.video, algorithm=sif.ALGORITHM
        )
        assert rows == {"contacts": [], "occlusions": [], "motions": []}


def test_publish_body_rejects_unknown_authority_fields(client) -> None:
    response = client.post(
        f"{API}/source-interaction-facts",
        json={
            "project_id": "p",
            "video_item_id": "v",
            "track_artifact": {},
            "bindings": {},
            "workspace_id": WS,  # server-owned: never client-supplied
        },
    )
    assert response.status_code == 422


# ── rows: lock freeze + immutability of sealed source facts ──────────────────


def test_lock_producer_freezes_facts_and_refuses_foreign_source(client) -> None:
    with _session() as session:
        seed = _seed_graph(session)
        session.commit()
    payload = _http_artifact(seed).to_payload()
    with _session() as session:
        outcome = sif.publish_facts(
            session,
            workspace_id=WS,
            project_id=seed.project,
            video_item_id=seed.video,
            artifact=sif.FactSet(payload=payload),
            bindings={
                "ROLE-P": seed.segments["ROLE-P"],
                "PROP-B": seed.segments["PROP-B"],
                "PROP-C2": seed.segments["PROP-C2"],
            },
            segment_ranges={
                seed.segments["ROLE-P"]: {"start_frame": 0, "end_frame": FRAMES},
                seed.segments["PROP-B"]: {"start_frame": 0, "end_frame": FRAMES},
                seed.segments["PROP-C2"]: {"start_frame": 0, "end_frame": 6},
            },
        )
        session.commit()
        assert outcome.contacts_created == 1 and outcome.occlusions_created == 1

        producer = StructuralLockProducer(session)
        segment_ids = {seed.segments["ROLE-P"], seed.segments["PROP-B"]}
        frozen = producer._source_facts_payload(WS, seed.video, segment_ids)
        assert frozen is not None
        assert frozen["algorithm"] == sif.ALGORITHM
        assert frozen["source_sha256"] == ["1" * 64]
        assert len(frozen["contacts"]) == 1 and len(frozen["occlusions"]) == 1
        assert all(
            row["source_segment_id"] in segment_ids for row in frozen["contacts"]
        )
        producer._validate_source_facts(frozen, "1" * 64)  # agrees: no raise

        with pytest.raises(ProducerValidationError) as err:
            producer._validate_source_facts(frozen, "2" * 64)
        assert err.value.code == CODE_SOURCE_FACTS_SOURCE_MISMATCH
        assert err.value.reasons

        # rows whose endpoints are outside the manifest segment set are not
        # silently dropped into a manifest: they are simply not part of it.
        only_person = producer._source_facts_payload(
            WS, seed.video, {seed.segments["PROP-B"]}
        )
        assert only_person is None or only_person["contacts"] == []


def test_fact_identity_is_deterministic_and_no_update_path_is_exported() -> None:
    payload = _held_artifact().to_payload()
    first = sif.fact_id(payload["contacts"][0])
    second = sif.fact_id(dict(payload["contacts"][0]))
    assert first == second
    assert first.startswith("contact:ROLE-P:PROP-B:grasp:")
    public = {name for name in sif.__all__}
    assert not {name for name in public if name.startswith("update_")}
    assert not {name for name in public if "Segment" in name and name != "ContactFact"}
