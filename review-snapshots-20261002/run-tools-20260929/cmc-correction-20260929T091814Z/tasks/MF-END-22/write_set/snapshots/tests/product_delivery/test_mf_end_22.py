"""MF-END-22 — source facts vs output observations: acceptance + negatives.

Row map (binary; every CI row is built from REAL deterministic pixels and both
sides come from their REAL producers):

* micro repro (22.0/22.4): the comparison surface (frozen policy identity,
  MEASURED calibration rows, typed codes), the verdict precedence
  (hard > blocked > unknown > soft > pass) and the rule that the OUTPUT's
  appearance can NEVER upgrade a verdict;
* 22.1: the comparator consumes the SEALED MF-END-13 facts + the SEALED
  MF-END-21 observations (+ the sealed MF-END-12 tracks as the source trace),
  preserves the source<->output frame mapping, and refuses a tampered side, a
  cross-source binding and an out-of-span mapping;
* 22.2: the calibration rows are MEASURED through the comparators' own
  functions (source control + deliberately wrong contact/role/camera/time) and
  frozen BEFORE the candidate; a failing candidate is never answered by
  widening a boundary;
* 22.3: BOOK changed owner / BOOK contact lost / OCC reversed / TURN identity
  lost / static output are all non-pass with their exact typed code, level and
  role/frame/evidence; a valid control passes;
* 22.4: an uncertain link is a TYPED UNKNOWN (never guessed into a pass/fail)
  and a pretty appearance never compensates a hard failure.

The fixture media is synthesized in-process (64x48 frames, labelled CI): the
REAL render/GPU path is not exercised here; the evidence harness
(raw/mf22_real_comparison.py) runs the same comparators over the same
deterministic bytes and dumps the raw frames + measurements.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import numpy as np

from app.services import rendered_observations as ro
from app.services import source_interaction_facts as sif
from app.services import source_role_tracks as srt
from app.services.qc_checks import contact_break as cb
from app.services.qc_checks import identity_drift as ident
from app.services.qc_checks import temporal_flicker as flick
from app.services.qc_checks import trajectory_drift as traj
from app.services.qc_checks import z_order_error as zerr
from app.services.qc_evidence import measure as qcm

W, H, FRAMES = 64, 48, 12
FPS = "10/1"
SRC_SHA = "a" * 64
OUT_SHA = "b" * 64
SPAN = (0, FRAMES)

#: Deterministic paint levels (far apart so a +-2 tolerance never collides).
LVL_BG_BASE = 90
LVL_PERSON = 200
LVL_PROP = 120
LVL_OTHER = 240
#: The held prop's SHADED appearance inside the pinned person reference
#: artwork: 40 levels away from the render's plain prop colour, which keeps
#: the person's reference distance over the prop area INSIDE the frozen match
#: tolerance while making the two roles' references distinguishable (an
#: identically painted bite made the prop's role link ambiguous).
LVL_BITE = 160
BG_TEXTURE_DELTA = 8
MOVE_PX = 2

PERSON_ROLE = "ROLE-BOOK-P1"
PROP_ROLE = "PROP-BOOK"
SECOND_ROLE = "ROLE-BOOK-P2"

FAR_PROP_BOX = (58, 12, 6, 6)  # 26 px away from the frozen person box
NEAR_PROP_BOX = (38, 12, 6, 6)  # 6 px away: inside the warning band
SECOND_BOX = (54, 8, 14, 14)  # covers FAR_PROP_BOX


# ── CI fixture media (real pixels, deterministic) ────────────────────────────


def _texture() -> np.ndarray:
    rng = np.random.default_rng(7)
    noise = rng.integers(-BG_TEXTURE_DELTA, BG_TEXTURE_DELTA + 1, size=(H, W))
    return np.clip(np.int16(LVL_BG_BASE) + noise, 0, 255).astype(np.uint8)


def _canvas() -> np.ndarray:
    img = _texture()
    return np.stack([img, img, img], axis=-1)


def _paint(frame: np.ndarray, box: tuple[int, int, int, int], level: int) -> None:
    x, y, w, h = (int(v) for v in box)
    frame[y : y + h, x : x + w] = level


def _person_box(index: int) -> tuple[int, int, int, int]:
    return (8 + MOVE_PX * index, 12, 24, 24)


def _prop_box(index: int) -> tuple[int, int, int, int]:
    x, y, _, _ = _person_box(index)
    return (x + 7, y + 7, 10, 10)


def _source_frame(index: int) -> np.ndarray:
    frame = _canvas()
    _paint(frame, _person_box(index), LVL_PERSON)
    _paint(frame, _prop_box(index), LVL_PROP)
    return frame


class _LevelSource:
    """CI engine: the instance is the pixels of its own painted level."""

    engine_id = "ci_level"
    provenance = srt.PROVENANCE_FIXTURE
    probe: dict[str, Any] | None = None
    candidates: dict[str, str] = {}
    inference_ran = False

    def __init__(
        self, levels: dict[str, int], hidden: dict[str, int] | None = None
    ) -> None:
        self.levels = dict(levels)
        self.hidden = dict(hidden or {})
        self.params = {"rule": "ci_level", "tolerance": 2}

    def sample(self, frame_index: int, seed: Any, frame: Any) -> Any:
        role_id = str(getattr(seed, "role_id", "") or seed.get("role_id"))
        hidden_from = self.hidden.get(role_id)
        if hidden_from is not None and int(frame_index) >= int(hidden_from):
            return srt.MaskSample(mask=None, method="ci:hidden", present=True)
        array = np.asarray(frame)
        if array.ndim == 3:
            array = array[:, :, 0]
        target = np.abs(array.astype(np.int64) - int(self.levels[role_id])) <= 2
        if not target.any():
            return srt.MaskSample(mask=None, method="ci:absent", present=False)
        return srt.MaskSample(mask=target.astype(np.uint8) * 255, method="ci:level")


def _source_tracks() -> srt.RoleTracksArtifact:
    seeds = [
        srt.RoleSeed(
            role_id=PERSON_ROLE,
            kind=srt.ROLE_KIND_PERSON,
            box=tuple(_person_box(0)),
            declare_frames=SPAN,
        ),
        srt.RoleSeed(
            role_id=PROP_ROLE,
            kind=srt.ROLE_KIND_PROP,
            box=tuple(_prop_box(0)),
            declare_frames=SPAN,
        ),
    ]
    return srt.build_role_tracks(
        source_sha256=SRC_SHA,
        span=srt.SourceSpan(start_frame=SPAN[0], end_frame_exclusive=SPAN[1]),
        frames=[_source_frame(index) for index in range(FRAMES)],
        fps_rational=FPS,
        seeds=seeds,
        mask_source=_LevelSource({PERSON_ROLE: LVL_PERSON, PROP_ROLE: LVL_PROP}),
        manifest_sha256=srt.payload_sha256({"manifest": "mf-end-22-ci"}),
        manifest_version="1.0.0",
        production=False,
        strict=True,
    )


def _source_facts() -> dict[str, Any]:
    facts = sif.build_artifact(
        tracks=_source_tracks(), windows=(), require_production=False
    )
    return facts.to_payload()


def _reference_frame(
    boxes: list[tuple[tuple[int, int, int, int], int]],
) -> np.ndarray:
    canvas = np.full((H, W), LVL_BG_BASE, dtype=np.uint8)
    for box, paint in boxes:
        x, y, w, h = (int(v) for v in box)
        canvas[y : y + h, x : x + w] = paint
    return canvas


def _references(person_level: int = LVL_PERSON) -> dict[str, ro.RenderedReference]:
    return {
        PERSON_ROLE: ro.RenderedReference(
            role_id=PERSON_ROLE,
            artifact_id="ref-person",
            sha256="ab" * 32,
            frame=_reference_frame(
                [(_person_box(0), person_level), (_prop_box(0), LVL_BITE)]
            ),
        ),
        PROP_ROLE: ro.RenderedReference(
            role_id=PROP_ROLE,
            artifact_id="ref-prop",
            sha256="cd" * 32,
            frame=_reference_frame([(_prop_box(0), LVL_PROP)]),
        ),
    }


def _build_world(
    *,
    person_level: int = LVL_PERSON,
    person_fixed_at: int | None = None,
    prop_fixed_box: tuple[int, int, int, int] | None = None,
    prop_hidden_from: int | None = None,
    second_box: tuple[int, int, int, int] | None = None,
    freeze_output: bool = False,
    references: bool = True,
    output_source_sha: str = SRC_SHA,
) -> dict[str, Any]:
    """One CI world: real source tracks/facts + a real output observation."""

    def _frame_at(index: int) -> np.ndarray:
        anchor = 0 if freeze_output else index
        person_anchor = 0 if person_fixed_at is not None else anchor
        # output frames are 2-D decoded grayscale (the builder's contract)
        frame = _texture()
        _paint(frame, _person_box(person_anchor), person_level)
        if second_box is not None:
            _paint(frame, second_box, LVL_OTHER)
        # the prop is painted LAST: it is the in-front object (the source
        # occlusion fact declares prop in_front_of person), so the second
        # person's box can overlap it without overwriting its own appearance.
        if prop_fixed_box is not None:
            if prop_hidden_from is None or index < prop_hidden_from:
                _paint(frame, prop_fixed_box, LVL_PROP)
        elif prop_hidden_from is None or index < prop_hidden_from:
            _paint(frame, _prop_box(anchor), LVL_PROP)
        return frame

    output_frames = {index: _frame_at(index) for index in range(FRAMES)}
    segments = [
        ro.RenderedSegment(
            segment_id="seg-person",
            role_id=PERSON_ROLE,
            kind=srt.ROLE_KIND_PERSON,
            start_frame=0,
            end_frame=FRAMES,
            window=(0, 0, W, H),
        ),
        ro.RenderedSegment(
            segment_id="seg-prop",
            role_id=PROP_ROLE,
            kind=srt.ROLE_KIND_PROP,
            start_frame=0,
            end_frame=FRAMES,
            window=(0, 0, W, H),
        ),
    ]
    levels = {PERSON_ROLE: person_level, PROP_ROLE: LVL_PROP}
    if second_box is not None:
        segments.append(
            ro.RenderedSegment(
                segment_id="seg-second",
                role_id=SECOND_ROLE,
                kind=srt.ROLE_KIND_PERSON,
                start_frame=0,
                end_frame=FRAMES,
                window=(0, 0, W, H),
            )
        )
        levels[SECOND_ROLE] = LVL_OTHER
    engine = _LevelSource(
        levels,
        hidden={PROP_ROLE: prop_hidden_from}
        if prop_hidden_from is not None
        else None,
    )
    output = ro.RenderedOutput(
        artifact_id="art-render",
        sha256=OUT_SHA,
        size_bytes=4096,
        relative_path="render/out.mp4",
        role="owned_result_artifact",
        width=W,
        height=H,
        frame_count=FRAMES,
        source_artifact_id="art-source",
        source_sha256=output_source_sha,
        producer="ci_render",
        facts={},
    )
    artifact = ro.build_rendered_observations(
        output=output,
        frames=output_frames,
        segments=segments,
        engine=engine,
        fps_rational=FPS,
        references=_references() if references else {},
        source_tracks_digest=_source_tracks().digest,
        production=False,
    )
    return {
        "facts": _source_facts(),
        "observations": artifact.to_payload(),
        "source_tracks": _source_tracks().to_payload(),
        "output_frames": output_frames,
    }


def _args(world: dict[str, Any], **extra: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "source_facts": world["facts"],
        "output_observations": world["observations"],
        "source_tracks": world["source_tracks"],
    }
    args.update(extra)
    return args


def _codes(result: dict[str, Any]) -> list[str]:
    return [item["code"] for item in result["items"]]


def _luminance(frames: dict[int, np.ndarray]) -> list[float]:
    return [
        round(float(np.asarray(frames[index]).astype(np.float64).mean()), 9)
        for index in sorted(frames)
    ]


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── micro repro (22.0) ───────────────────────────────────────────────────────


def test_mf22_0_surface_and_frozen_policy() -> None:
    assert qcm.COMPARISON_POLICY_ID == "mf-end-22-comparison-v1"
    assert qcm.COMPARISON_SCHEMA_VERSION == 1
    assert set(qcm.COMPARISON_METRICS) == {
        qcm.METRIC_CONTACT_GAP,
        qcm.METRIC_OCCLUSION_REVERSAL,
        qcm.METRIC_IDENTITY_UNLINKED,
        qcm.METRIC_MOTION_ATTENUATION,
        qcm.METRIC_FRAME_SHIFT,
    }
    for code in (
        qcm.CODE_CONTACT_LOST,
        qcm.CODE_CONTACT_OWNER_CHANGED,
        qcm.CODE_CONTACT_WEAKENED,
        qcm.CODE_OCCLUSION_REVERSED,
        qcm.CODE_IDENTITY_LOST,
        qcm.CODE_MOTION_STATIC,
        qcm.CODE_MOTION_LOST,
        qcm.CODE_FRAME_SHIFT,
        qcm.CODE_COMPARISON_UNKNOWN,
        qcm.CODE_COMPARISON_FRAME_MAP,
        qcm.CODE_COMPARISON_SOURCE_INVALID,
        qcm.CODE_COMPARISON_OUTPUT_INVALID,
    ):
        assert isinstance(code, str) and code.startswith("QC_COMPARISON")
    first = qcm.comparison_policy()
    second = qcm.comparison_policy()
    assert first == second
    assert first["content_hash"] == second["content_hash"]
    for metric in qcm.COMPARISON_METRICS:
        entry = first["thresholds"][metric]
        rows = qcm.COMPARISON_CALIBRATION[metric]
        assert entry["warning_boundary"] == rows[qcm.COMPARISON_WARNING_LEVEL]
        assert entry["blocker_boundary"] == rows[qcm.COMPARISON_BLOCKER_LEVEL]
        assert entry["sanity_bounds"] == {"min": 0.0, "max": None}
    assert qcm.frozen_comparison_policy()["content_hash"] == first["content_hash"]
    for entry in (
        cb.compare_contact_facts,
        zerr.compare_occlusion_facts,
        traj.compare_motion_facts,
        ident.compare_identity_facts,
        flick.compare_static_and_flicker,
    ):
        assert callable(entry)


def test_mf22_0_verdict_precedence_and_appearance_cannot_override() -> None:
    hard = qcm.comparison_item(
        metric=qcm.METRIC_CONTACT_GAP,
        code=qcm.CODE_CONTACT_LOST,
        level=qcm.LEVEL_HARD,
        severity="blocker",
        role_id="R",
        frames=[1, 2],
        detail="d",
        evidence={},
    )
    soft = qcm.comparison_item(
        metric=qcm.METRIC_CONTACT_GAP,
        code=qcm.CODE_CONTACT_WEAKENED,
        level=qcm.LEVEL_SOFT,
        severity="warning",
        role_id="R",
        frames=[1],
        detail="d",
        evidence={},
    )
    uncertain = [{"code": qcm.CODE_COMPARISON_UNKNOWN, "role_id": "R", "frames": []}]
    blocked = [
        {"code": qcm.CODE_COMPARISON_NOT_OBSERVED, "role_id": "R", "frames": []}
    ]
    pretty = {"style_score": 1.0, "support_separation": 255.0}
    assert qcm.compare_verdict([])["passed"] is True
    assert qcm.compare_verdict([soft])["verdict"] == qcm.VERDICT_WARN
    assert (
        qcm.compare_verdict([], uncertain=uncertain)["verdict"] == qcm.VERDICT_UNKNOWN
    )
    assert qcm.compare_verdict([], blocked=blocked)["verdict"] == qcm.VERDICT_BLOCKED
    verdict = qcm.compare_verdict(
        [hard, soft], uncertain=uncertain, blocked=blocked, appearance=pretty
    )
    assert verdict["verdict"] == qcm.VERDICT_FAIL
    assert verdict["passed"] is False
    assert verdict["appearance_cannot_override_hard_fail"] is True
    assert verdict["appearance"] == pretty
    assert verdict["hard_failures"] == [qcm.CODE_CONTACT_LOST]


def test_mf22_0_frame_map_bases_and_bounds() -> None:
    span = {"start_frame": 0, "end_frame_exclusive": 12}
    mapping, evidence = qcm.comparison_frame_map(
        source_span=span, output_span=dict(span), declared=None
    )
    assert evidence["basis"] == "identical_spans"
    assert mapping == {index: index for index in range(12)}
    mapping, evidence = qcm.comparison_frame_map(
        source_span={"start_frame": 2, "end_frame_exclusive": 8},
        output_span={"start_frame": 0, "end_frame_exclusive": 12},
        declared={2: 4, 3: 5},
    )
    assert evidence["basis"] == "declared" and mapping == {2: 4, 3: 5}
    mapping, evidence = qcm.comparison_frame_map(
        source_span=span, output_span=dict(span), declared={11: 99}
    )
    assert mapping is None
    assert evidence["code"] == qcm.CODE_COMPARISON_FRAME_MAP
    mapping, evidence = qcm.comparison_frame_map(
        source_span={"start_frame": 0, "end_frame_exclusive": 12},
        output_span={"start_frame": 0, "end_frame_exclusive": 8},
        declared=None,
    )
    assert mapping is None
    assert evidence["code"] == qcm.CODE_COMPARISON_FRAME_MAP


# ── 22.1 — the two sides, the binding and the frame mapping ──────────────────


def test_mf22_1_valid_control_passes_all_four() -> None:
    world = _build_world()
    contact = cb.compare_contact_facts(_args(world))
    occlusion = zerr.compare_occlusion_facts(_args(world))
    motion = traj.compare_motion_facts(_args(world))
    identity = ident.compare_identity_facts(_args(world))
    for result in (contact, occlusion, motion, identity):
        assert result["verdict"]["passed"] is True, (result["detector"], result)
        assert result["items"] == []
    assert [row["status"] for row in contact["checked"]] == ["pass"]
    assert contact["mapping"]["basis"] == "identical_spans"
    assert motion["mapping"]["basis"] == "identical_spans"
    assert identity["checked"][0]["status"] == "pass"
    assert motion["checked"], motion
    assert contact["provenance"]["source_sha256"] == SRC_SHA
    assert contact["provenance"]["output_sha256"] == OUT_SHA


def test_mf22_1_frame_mapping_declared_and_refused() -> None:
    world = _build_world()
    declared = {index: index for index in range(FRAMES)}
    result = cb.compare_contact_facts(
        _args(world, frame_map={"source_to_output": declared})
    )
    assert result["verdict"]["passed"] is True
    assert result["mapping"]["basis"] == "declared"
    assert result["mapping"]["declared"] == {str(k): v for k, v in declared.items()}
    bad = dict(declared)
    bad[FRAMES - 1] = FRAMES + 5
    refused = cb.compare_contact_facts(
        _args(world, frame_map={"source_to_output": bad})
    )
    assert refused["verdict"]["verdict"] == qcm.VERDICT_BLOCKED
    assert refused["blocked"][0]["code"] == qcm.CODE_COMPARISON_FRAME_MAP


def test_mf22_1_verification_refuses_tampered_and_foreign_sides() -> None:
    world = _build_world()
    tampered = copy.deepcopy(world["observations"])
    tampered["output"]["sha256"] = "0" * 64
    blocked = cb.compare_contact_facts(_args(world, output_observations=tampered))
    assert blocked["verdict"]["verdict"] == qcm.VERDICT_BLOCKED
    assert blocked["blocked"][0]["code"] == qcm.CODE_COMPARISON_OUTPUT_INVALID

    tampered_facts = copy.deepcopy(world["facts"])
    tampered_facts["policy_version"] = "other"
    blocked = cb.compare_contact_facts(_args(world, source_facts=tampered_facts))
    assert blocked["blocked"][0]["code"] == qcm.CODE_COMPARISON_SOURCE_INVALID

    foreign = _build_world(output_source_sha="c" * 64)
    blocked = cb.compare_contact_facts(
        _args(world, output_observations=foreign["observations"])
    )
    assert blocked["verdict"]["verdict"] == qcm.VERDICT_BLOCKED
    assert blocked["blocked"][0]["side"] == "binding"
    assert blocked["blocked"][0]["code"] == qcm.CODE_COMPARISON_SOURCE_INVALID

    bad_tracks = copy.deepcopy(world["source_tracks"])
    bad_tracks["digest"] = "f" * 64
    motion_blocked = traj.compare_motion_facts(_args(world, source_tracks=bad_tracks))
    assert motion_blocked["blocked"][0]["code"] == qcm.CODE_COMPARISON_SOURCE_INVALID
    assert motion_blocked["verdict"]["verdict"] == qcm.VERDICT_BLOCKED


# ── 22.2 — calibration and the frozen policy ─────────────────────────────────


def test_mf22_2_calibration_rows_are_measured_control_and_wrong_cases() -> None:
    rows = qcm.COMPARISON_CALIBRATION
    for metric in qcm.COMPARISON_METRICS:
        assert rows[metric][1] == 0.0, metric
    assert [rows[qcm.METRIC_CONTACT_GAP][level] for level in (1, 2, 3, 4)] == [
        0.0,
        2.0,
        8.0,
        24.0,
    ]
    assert rows[qcm.METRIC_OCCLUSION_REVERSAL][2] == 0.55
    assert abs(rows[qcm.METRIC_OCCLUSION_REVERSAL][3] - 0.72) < 1e-9
    assert abs(rows[qcm.METRIC_OCCLUSION_REVERSAL][4] - 0.9) < 1e-9
    assert rows[qcm.METRIC_IDENTITY_UNLINKED][4] == 0.5
    assert abs(rows[qcm.METRIC_MOTION_ATTENUATION][4] - 0.9) < 1e-9
    assert [rows[qcm.METRIC_FRAME_SHIFT][level] for level in (1, 2, 3, 4)] == [
        0.0,
        1.0,
        2.0,
        4.0,
    ]
    policy = qcm.comparison_policy()
    assert policy["thresholds"][qcm.METRIC_FRAME_SHIFT]["warning_boundary"] == 1.0
    assert policy["thresholds"][qcm.METRIC_FRAME_SHIFT]["blocker_boundary"] == 4.0
    # a defect WORSE than the level-4 row is still a blocker (the metrics are
    # unbounded above; only the physical floor invalidates a measurement)
    assert qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, 24.0)[0] == "blocker"
    assert qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, 999.0)[0] == "blocker"
    assert qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, 23.9)[0] == "warning"
    assert qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, 1.0)[0] == "pass"
    assert qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, -1.0)[0] == "invalid"


def test_mf22_2_thresholds_are_not_loosened_after_candidate_fail() -> None:
    world = _build_world(person_fixed_at=0, prop_fixed_box=FAR_PROP_BOX)
    before = qcm.comparison_policy_digest()
    result = cb.compare_contact_facts(_args(world))
    assert result["verdict"]["verdict"] == qcm.VERDICT_FAIL
    gap = result["items"][0]["evidence"]["measured_min_gap_px"]
    assert gap >= qcm.COMPARISON_CALIBRATION[qcm.METRIC_CONTACT_GAP][4]
    after = qcm.comparison_policy_digest()
    assert before == after  # the candidate did not move a boundary
    assert result["policy"]["digest"] == before
    loosened = copy.deepcopy(qcm.comparison_policy())
    loosened.pop("content_hash", None)
    loosened["thresholds"][qcm.METRIC_CONTACT_GAP]["blocker_boundary"] = 999.0
    loosened["thresholds"][qcm.METRIC_CONTACT_GAP]["sanity_bounds"]["max"] = 999.0
    loosened_digest = qcm.content_digest(loosened)
    assert loosened_digest != before
    assert gap < 999.0  # the loosened boundary would have hidden this defect
    status, _ = qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, gap)
    assert status == "blocker"
    assert result["items"][0]["level"] == qcm.LEVEL_HARD


# ── 22.3 — the relation/identity/motion defects are all non-pass ─────────────


def test_mf22_3_book_owner_changed_is_hard_fail() -> None:
    world = _build_world(
        person_fixed_at=0, prop_fixed_box=FAR_PROP_BOX, second_box=SECOND_BOX
    )
    result = cb.compare_contact_facts(_args(world, appearance={"style_score": 1.0}))
    assert result["verdict"]["verdict"] == qcm.VERDICT_FAIL
    assert qcm.CODE_CONTACT_OWNER_CHANGED in _codes(result)
    item = result["items"][0]
    assert item["level"] == qcm.LEVEL_HARD
    assert item["role_id"] == PERSON_ROLE
    assert item["evidence"]["owner_candidate"]["role_id"] == SECOND_ROLE
    assert result["verdict"]["appearance"] == {"style_score": 1.0}
    assert result["verdict"]["appearance_cannot_override_hard_fail"] is True


def test_mf22_3_book_contact_lost_is_hard_fail() -> None:
    world = _build_world(person_fixed_at=0, prop_fixed_box=FAR_PROP_BOX)
    result = cb.compare_contact_facts(_args(world))
    assert result["verdict"]["verdict"] == qcm.VERDICT_FAIL
    assert _codes(result) == [qcm.CODE_CONTACT_LOST]
    assert result["items"][0]["frames"], result["items"][0]
    assert result["items"][0]["evidence"]["measured_min_gap_px"] >= 24.0


def test_mf22_3_contact_weakened_is_soft_non_pass() -> None:
    world = _build_world(person_fixed_at=0, prop_fixed_box=NEAR_PROP_BOX)
    result = cb.compare_contact_facts(_args(world))
    assert result["verdict"]["verdict"] == qcm.VERDICT_WARN
    assert result["verdict"]["passed"] is False
    assert _codes(result) == [qcm.CODE_CONTACT_WEAKENED]
    assert result["items"][0]["level"] == qcm.LEVEL_SOFT


def test_mf22_3_occlusion_reversed_is_hard_fail() -> None:
    world = _build_world(freeze_output=True, prop_hidden_from=2)
    result = zerr.compare_occlusion_facts(_args(world))
    assert result["verdict"]["verdict"] == qcm.VERDICT_FAIL
    assert _codes(result) == [qcm.CODE_OCCLUSION_REVERSED]
    item = result["items"][0]
    assert item["level"] == qcm.LEVEL_HARD
    assert item["role_id"] == PERSON_ROLE  # the declared occludee
    assert item["frames"], item
    evidence = item["evidence"]["measured"]
    assert evidence["reversal_containment"] is not None
    assert evidence["reversal_containment"] >= 0.9
    assert evidence["hidden_occluder_share"] > 0.5


def test_mf22_3_occlusion_preserved_control_passes() -> None:
    world = _build_world()
    result = zerr.compare_occlusion_facts(_args(world))
    assert result["verdict"]["passed"] is True
    assert result["checked"], result
    assert result["checked"][0]["preserved_by"] in (
        "visible_occluder_inside_occludee",
        "hidden_occludee_covered_by_occluder",
    )


def test_mf22_3_turn_identity_lost_is_hard_fail() -> None:
    world = _build_world(person_level=LVL_OTHER)
    result = ident.compare_identity_facts(_args(world))
    assert result["verdict"]["verdict"] == qcm.VERDICT_FAIL
    assert qcm.CODE_IDENTITY_LOST in _codes(result)
    item = next(item for item in result["items"] if item["role_id"] == PERSON_ROLE)
    assert item["level"] == qcm.LEVEL_HARD
    assert item["evidence"]["measured"]["role_match_state"] == ro.MATCH_UNKNOWN
    assert (
        item["evidence"]["measured"]["role_match_reason"] == ro.UNKNOWN_REASON_UNMATCHED
    )


def test_mf22_3_static_output_is_hard_fail() -> None:
    world = _build_world(freeze_output=True)
    motion = traj.compare_motion_facts(_args(world))
    assert motion["verdict"]["verdict"] == qcm.VERDICT_FAIL
    assert _codes(motion) == [qcm.CODE_MOTION_STATIC]
    measured = motion["items"][0]["evidence"]["measured"]
    assert measured["source_px_per_frame"] > qcm.COMPARISON_STATIC_MAX_PX_PER_FRAME
    assert measured["output_px_per_frame"] == 0.0
    assert motion["items"][0]["level"] == qcm.LEVEL_HARD

    source = _build_world()
    flicker = flick.compare_static_and_flicker(
        {
            "luminance": _luminance(world["output_frames"]),
            "source_luminance": _luminance(source["output_frames"]),
            "window": {"start_frame": 0, "end_frame_exclusive": FRAMES},
        }
    )
    assert flicker["verdict"]["verdict"] == qcm.VERDICT_FAIL
    assert _codes(flicker) == [qcm.CODE_MOTION_STATIC]
    assert flicker["items"][0]["evidence"]["appearance"]["frozen_window"] is True


def test_mf22_3_items_carry_role_frame_evidence_and_level() -> None:
    for world, run in (
        (_build_world(freeze_output=True, prop_hidden_from=2), zerr.compare_occlusion_facts),
        (_build_world(person_level=LVL_OTHER), ident.compare_identity_facts),
        (_build_world(freeze_output=True), traj.compare_motion_facts),
    ):
        result = run(_args(world))
        assert result["items"], result["detector"]
        for item in result["items"]:
            assert item["level"] in (qcm.LEVEL_HARD, qcm.LEVEL_SOFT)
            assert item["role_id"]
            assert isinstance(item["frames"], list) and item["frames"]
            assert isinstance(item["evidence"], dict) and item["evidence"]
            assert len(item["evidence_window_key"]) == 64
            assert item["policy"]["warning_boundary"] is not None
            assert item["policy"]["blocker_boundary"] is not None


# ── 22.4 — uncertainty is typed; appearance never compensates ────────────────


def test_mf22_4_uncertain_link_is_typed_unknown_not_a_guess() -> None:
    world = _build_world(references=False)
    result = ident.compare_identity_facts(_args(world))
    assert result["verdict"]["verdict"] == qcm.VERDICT_UNKNOWN
    assert result["verdict"]["passed"] is False
    assert result["verdict"]["hard_failures"] == []
    assert result["unknown"], result
    assert result["unknown"][0]["code"] == qcm.CODE_COMPARISON_UNKNOWN
    assert result["unknown"][0]["evidence"]["measured"]["role_match_reason"] in (
        ro.UNKNOWN_REASON_NO_REFERENCE,
        ro.UNKNOWN_REASON_UNMATCHED,
    )


def test_mf22_4_measurements_are_reproducible() -> None:
    world = _build_world(
        person_fixed_at=0, prop_fixed_box=FAR_PROP_BOX, second_box=SECOND_BOX
    )
    first = cb.compare_contact_facts(_args(world))
    second = cb.compare_contact_facts(_args(world))
    assert _digest(first) == _digest(second)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    occlusion_first = zerr.compare_occlusion_facts(
        _args(_build_world(freeze_output=True, prop_hidden_from=2))
    )
    occlusion_second = zerr.compare_occlusion_facts(
        _args(_build_world(freeze_output=True, prop_hidden_from=2))
    )
    assert _digest(occlusion_first) == _digest(occlusion_second)
    frames = world["output_frames"]
    raw = b"".join(
        np.ascontiguousarray(frames[index]).tobytes() for index in sorted(frames)
    )
    assert len(raw) == FRAMES * H * W
    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(raw).hexdigest()
    assert (
        first["items"][0]["evidence"]["measured_min_gap_px"]
        == second["items"][0]["evidence"]["measured_min_gap_px"]
    )
