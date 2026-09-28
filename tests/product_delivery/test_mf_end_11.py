"""MF-END-11 — shot plan + precise timebase: acceptance + negative controls.

Row map (binary; micro-job map in the task TARGET.md):
* micro repro: module surface + capability budget;
* MF-END-11.1 probe: REAL ffmpeg-generated CFR/VFR/one-frame sources — full-file
  sha256, exact rational timebase, measured packet/PTS table (display order),
  deep-decode cross-check, audio metadata, typed probe refusals;
* MF-END-11.2 cuts: real detector split at the measured cut, adapter parity with
  the legacy SceneInfo contract, half-open partition coverage codes, dropped-cut
  accounting (zero/duplicate/out-of-range);
* MF-END-11.3 chunking: capability frame limit, even split, trim/context map
  without double-counted buffer frames, protected-interval boundary avoidance
  and the flagged straddle when unavoidable, property sweep over lengths;
* MF-END-11.4 artifact: versioned canonical JSON round-trip + digest, tamper /
  unknown-version refusals, source-changed invalidation and staleness refusal;
* negative controls each assert the EXACT typed code.

Real media is synthesized with ffmpeg at test time (tiny CI fixtures — NOT
product output); no GPU, no network, no render.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from app.services import shot_reskin_plan as plan
from app.services.ffmpeg_utils import find_ffmpeg
from app.services.scene_detection import detect_scene_intervals, detect_scenes
from app.services.source_locked_timeline import (
    CODE_COVERAGE_FRAME_COUNT,
    CODE_COVERAGE_GAP,
    CODE_COVERAGE_OVERLAP,
    pick_partition_code,
    validate_half_open_partition,
)

MF_TS_SIZE = "160x120"


# ── fixtures: tiny REAL media generated once per session ─────────────────────


def _ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        [find_ffmpeg(), "-y", *args], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"ffmpeg failed: {result.stderr[-400:]}"


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("mfend11")
    return root


@pytest.fixture(scope="session")
def cfr30(media_dir: Path) -> Path:
    path = media_dir / "cfr30.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=duration=1:size={MF_TS_SIZE}:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ]
    )
    assert path.stat().st_size > 0
    return path


@pytest.fixture(scope="session")
def cfr30_changed(media_dir: Path) -> Path:
    """Same generator, an extra frame -> different bytes AND frame count."""
    path = media_dir / "cfr31.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=duration=1.04:size={MF_TS_SIZE}:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )
    assert path.stat().st_size > 0
    return path


@pytest.fixture(scope="session")
def vfr_drop(media_dir: Path) -> Path:
    path = media_dir / "vfr_drop.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=duration=2:size={MF_TS_SIZE}:rate=30",
            "-vf", "select='gt(mod(n,7),1)'", "-fps_mode", "vfr",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )
    assert path.stat().st_size > 0
    return path


@pytest.fixture(scope="session")
def cut60(media_dir: Path) -> Path:
    """testsrc -> solid black hard cut measured at frame 30 (see lab evidence)."""
    path = media_dir / "cut60.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=duration=1:size={MF_TS_SIZE}:rate=30",
            "-f", "lavfi", "-i", f"color=black:duration=1:size={MF_TS_SIZE}:rate=30",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[out]", "-map", "[out]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )
    assert path.stat().st_size > 0
    return path


@pytest.fixture(scope="session")
def one_frame(media_dir: Path) -> Path:
    path = media_dir / "one_frame.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=duration=1:size={MF_TS_SIZE}:rate=30",
            "-frames:v", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )
    assert path.stat().st_size > 0
    return path


# ── helpers ──────────────────────────────────────────────────────────────────


def _refuses(code: str, fn, *args, **kwargs) -> Exception:
    with pytest.raises(plan.ShotPlanError) as excinfo:
        fn(*args, **kwargs)
    assert excinfo.value.code == code, excinfo.value
    return excinfo.value


def _assert_chunk_invariants(shot: plan.PlannedShot, capability: plan.CapabilityFrameLimit) -> None:
    cursor = shot.span.start_frame
    for chunk in shot.chunks:
        assert chunk.core.start_frame == cursor
        assert shot.span.contains(chunk.render)
        assert chunk.render.contains(chunk.core)
        assert chunk.render.frame_count <= capability.max_frames
        assert chunk.context_left_frames == chunk.core.start_frame - chunk.render.start_frame
        assert (
            chunk.context_right_frames
            == chunk.render.end_frame_exclusive - chunk.core.end_frame_exclusive
        )
        assert chunk.output_trim_start == chunk.context_left_frames
        assert chunk.output_trim_end - chunk.output_trim_start == chunk.core.frame_count
        cursor = chunk.core.end_frame_exclusive
    assert cursor == shot.span.end_frame_exclusive
    assert sum(chunk.core.frame_count for chunk in shot.chunks) == shot.span.frame_count


# ── micro repro ──────────────────────────────────────────────────────────────


def test_micro_repro_module_surface() -> None:
    assert plan.PLAN_SCHEMA_VERSION == "mf.shot_reskin.plan.v1"
    assert plan.DEFAULT_COMFY_CAPABILITY.budget() == 81
    for name in plan.__all__:
        assert hasattr(plan, name), f"__all__ names a missing symbol: {name}"


def test_micro_repro_capability_budget_shapes() -> None:
    assert plan.CapabilityFrameLimit(max_frames=81).budget() == 81
    assert plan.CapabilityFrameLimit(max_frames=100).budget() == 97
    assert plan.CapabilityFrameLimit(max_frames=5).budget() == 5
    assert plan.CapabilityFrameLimit(max_frames=3).budget() == 1
    assert plan.CapabilityFrameLimit(max_frames=1).budget() == 1


def test_micro_repro_capability_invalid_refusals() -> None:
    _refuses(plan.CODE_CAPABILITY_INVALID, plan.CapabilityFrameLimit, max_frames=0)
    _refuses(
        plan.CODE_CAPABILITY_INVALID,
        plan.CapabilityFrameLimit,
        max_frames=81,
        shape_modulus=0,
    )
    _refuses(
        plan.CODE_CAPABILITY_INVALID,
        plan.CapabilityFrameLimit,
        max_frames=81,
        shape_modulus=4,
        shape_offset=4,
    )
    _refuses(
        plan.CODE_CAPABILITY_INVALID,
        plan.CapabilityFrameLimit,
        max_frames=81,
        label="",
    )


# ── MF-END-11.1: probe real sources ─────────────────────────────────────────


def test_probe_cfr_source_measures_real_facts(cfr30: Path) -> None:
    facts = plan.probe_source_facts(cfr30, deep_count=True)
    assert facts.source_sha256 == hashlib.sha256(cfr30.read_bytes()).hexdigest()
    assert facts.file_size_bytes == cfr30.stat().st_size
    assert (facts.fps_num, facts.fps_den) == (30, 1)
    assert facts.fps_classification == "CFR"
    assert (facts.stream_timebase_num, facts.stream_timebase_den) == (1, 15360)
    assert facts.frame_count == len(facts.pts_ticks) == 30
    assert facts.pts_start_ticks == 0
    assert facts.pts_uniform is True
    assert facts.decoded_frame_count == 30  # deep decode agrees with packets
    assert facts.container_nb_frames == 30
    assert facts.audio is not None
    assert facts.audio.codec_name == "aac"
    assert facts.audio.sample_rate == 44100
    assert facts.audio.channels == 1
    assert facts.fps == Fraction(30, 1)


def test_probe_cfr_timebase_facts_match_frozen_contract(cfr30: Path) -> None:
    facts = plan.probe_source_facts(cfr30)
    timebase = facts.timebase_facts()  # the FROZEN MF-END-01 type
    assert timebase.fps == "30/1"
    assert timebase.timebase == "1/15360"
    assert timebase.timebase != timebase.fps  # rate != container time_base
    assert timebase.pts_span_ticks == 29 * 512
    required = timebase.required_pts_span(facts.frame_count)
    assert required is not None and facts.pts_end_ticks - facts.pts_start_ticks >= required
    assert timebase.decoded_frame_count is None  # no deep decode requested


def test_probe_vfr_source_measures_display_order_pts(vfr_drop: Path) -> None:
    facts = plan.probe_source_facts(vfr_drop)
    assert facts.fps_classification == "VFR"
    assert (facts.fps_num, facts.fps_den) == (45, 2)
    assert facts.frame_count == len(facts.pts_ticks) == 42
    assert facts.container_nb_frames == 42
    gaps = [b - a for a, b in zip(facts.pts_ticks, facts.pts_ticks[1:])]
    assert len(set(gaps)) >= 2, "VFR fixture must show a non-uniform grid"
    assert facts.pts_uniform is False


def test_probe_expected_sha_mismatch_refuses(cfr30: Path) -> None:
    _refuses(
        plan.CODE_SOURCE_CHANGED,
        plan.probe_source_facts,
        cfr30,
        expected_sha256="0" * 64,
    )


def test_probe_missing_source_refuses(media_dir: Path) -> None:
    _refuses(plan.CODE_SOURCE_MISSING, plan.probe_source_facts, media_dir / "nope.mp4")


def test_deep_count_cross_check_pure() -> None:
    plan.require_matching_frame_counts(30, 30)
    _refuses(plan.CODE_FRAME_COUNT_MISMATCH, plan.require_matching_frame_counts, 30, 29)


def test_normalize_pts_ticks_sorts_shifts_and_refuses_duplicates() -> None:
    ticks, origin = plan.normalize_pts_ticks([512, 0, 1024])
    assert ticks == (0, 512, 1024)
    assert origin == 0
    ticks, origin = plan.normalize_pts_ticks([-1024, 0, 512])
    assert ticks == (0, 1024, 1536)
    assert origin == -1024
    _refuses(plan.CODE_PTS_MEASUREMENT_FAILED, plan.normalize_pts_ticks, [7, 7])
    _refuses(plan.CODE_PTS_MEASUREMENT_FAILED, plan.normalize_pts_ticks, [])


def test_parse_rational_refusals() -> None:
    assert plan.parse_rational("30000/1001") == (30000, 1001)
    assert plan.parse_rational("30") == (30, 1)
    _refuses(plan.CODE_TIMEBASE_UNAVAILABLE, plan.parse_rational, "0/1")
    _refuses(plan.CODE_TIMEBASE_UNAVAILABLE, plan.parse_rational, "x/y")


# ── MF-END-11.2: cuts, coverage, dropped-cut accounting ─────────────────────


def test_scene_adapter_matches_legacy_contract(cut60: Path) -> None:
    legacy = detect_scenes(cut60)
    adapter = detect_scene_intervals(cut60)
    assert adapter == [(scene.start_frame, scene.end_frame + 1) for scene in legacy]
    assert adapter == [(0, 30), (30, 60)]  # measured hard cut at frame 30
    assert legacy[0].end_frame == 29 and legacy[1].start_frame == 30  # inclusive legacy


def test_detect_shot_intervals_real_file_cut_boundary(cut60: Path) -> None:
    partition = plan.detect_shot_intervals(cut60, 60)
    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [
        (0, 30),
        (30, 60),
    ]
    assert partition.dropped_cuts == ()
    assert partition.frame_count == 60


def test_plan_shot_intervals_full_coverage_and_drops() -> None:
    partition = plan.plan_shot_intervals([0, 5, 5, 120, -3, 10], 100)
    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [
        (0, 5),
        (5, 10),
        (10, 100),
    ]
    assert [(d.cut_frame, d.reason) for d in partition.dropped_cuts] == [
        (0, "at_zero"),
        (5, "duplicate"),
        (120, "out_of_range"),
        (-3, "out_of_range"),
    ]


def test_plan_shot_intervals_single_frame_source() -> None:
    partition = plan.plan_shot_intervals([], 1)
    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [(0, 1)]


def test_plan_shot_intervals_tail_reconciliation() -> None:
    # A detector boundary at/beyond the measured end is dropped, never kept.
    partition = plan.plan_shot_intervals([30, 60], 60)
    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [
        (0, 30),
        (30, 60),
    ]
    assert [(d.cut_frame, d.reason) for d in partition.dropped_cuts] == [(60, "out_of_range")]


def test_plan_shot_intervals_bad_frame_count_refuses() -> None:
    _refuses(plan.CODE_COVERAGE_INVALID, plan.plan_shot_intervals, [], 0)


@pytest.mark.parametrize(
    ("spans", "frame_count", "code"),
    [
        ([(0, 5), (6, 10)], 10, CODE_COVERAGE_GAP),
        ([(0, 7), (5, 10)], 10, CODE_COVERAGE_OVERLAP),
        ([(0, 5), (5, 9)], 10, CODE_COVERAGE_FRAME_COUNT),
        ([(2, 5), (5, 10)], 10, CODE_COVERAGE_GAP),
        ([(0, 5), (5, 10)], 10, None),
    ],
)
def test_half_open_partition_validator_codes(spans, frame_count, code) -> None:
    problems = validate_half_open_partition(spans, frame_count)
    if code is None:
        assert problems == []
    else:
        assert problems
        assert pick_partition_code(problems) == code


# ── MF-END-11.3: capability chunking + trim/context map ─────────────────────


def test_chunking_even_split_without_context() -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    shot = plan.plan_shot_chunks(
        plan.SourceSpan(start_frame=0, end_frame_exclusive=100),
        shot_id="shot-0000",
        capability=capability,
    )
    assert [(c.core.start_frame, c.core.end_frame_exclusive) for c in shot.chunks] == [
        (0, 50),
        (50, 100),
    ]
    assert all(c.context_left_frames == 0 and c.context_right_frames == 0 for c in shot.chunks)
    assert all(c.output_trim_start == 0 and c.output_trim_end == c.core.frame_count
               for c in shot.chunks)
    assert shot.boundary_shifts == ()
    _assert_chunk_invariants(shot, capability)


def test_chunking_context_map_not_double_counted() -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    shot = plan.plan_shot_chunks(
        plan.SourceSpan(start_frame=0, end_frame_exclusive=100),
        shot_id="shot-0000",
        capability=capability,
        context_frames_per_side=8,
    )
    first, second = shot.chunks
    assert (first.core.start_frame, first.core.end_frame_exclusive) == (0, 50)
    assert (first.render.start_frame, first.render.end_frame_exclusive) == (0, 58)
    assert first.context_right_frames == 8 and first.context_left_frames == 0
    assert (second.core.start_frame, second.core.end_frame_exclusive) == (50, 100)
    assert (second.render.start_frame, second.render.end_frame_exclusive) == (42, 100)
    assert second.context_left_frames == 8 and second.context_right_frames == 0
    assert first.output_trim_end - first.output_trim_start == 50  # exported once
    assert sum(c.core.frame_count for c in shot.chunks) == 100
    _assert_chunk_invariants(shot, capability)


def test_chunking_tail_case_uneven_sizes() -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    shot = plan.plan_shot_chunks(
        plan.SourceSpan(start_frame=0, end_frame_exclusive=163),
        shot_id="shot-0000",
        capability=capability,
    )
    assert [c.core.frame_count for c in shot.chunks] == [55, 54, 54]
    assert shot.chunks[-1].core.end_frame_exclusive == 163
    _assert_chunk_invariants(shot, capability)


@pytest.mark.parametrize("context", [0, 1, 7])
@pytest.mark.parametrize("length", [1, 2, 3, 4, 5, 79, 80, 81, 82, 100, 163, 200, 251])
def test_chunking_property_sweep(length: int, context: int) -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    shot = plan.plan_shot_chunks(
        plan.SourceSpan(start_frame=0, end_frame_exclusive=length),
        shot_id="shot-0000",
        capability=capability,
        context_frames_per_side=context,
    )
    assert sum(c.core.frame_count for c in shot.chunks) == length
    _assert_chunk_invariants(shot, capability)


def test_chunking_protected_boundary_shifts_away() -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    protected = (
        plan.ProtectedInterval(
            span_id="int-1", span=plan.SourceSpan(start_frame=45, end_frame_exclusive=55)
        ),
    )
    shot = plan.plan_shot_chunks(
        plan.SourceSpan(start_frame=0, end_frame_exclusive=100),
        shot_id="shot-0000",
        capability=capability,
        protected_intervals=protected,
    )
    assert [(c.core.start_frame, c.core.end_frame_exclusive) for c in shot.chunks] == [
        (0, 45),
        (45, 100),
    ]
    assert shot.boundary_shifts == ((50, 45),)
    assert all(c.protected_straddles == () for c in shot.chunks)
    _assert_chunk_invariants(shot, capability)


def test_chunking_protected_straddle_flagged_when_unavoidable() -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    protected = (
        plan.ProtectedInterval(
            span_id="int-wide", span=plan.SourceSpan(start_frame=40, end_frame_exclusive=60)
        ),
    )
    shot = plan.plan_shot_chunks(
        plan.SourceSpan(start_frame=0, end_frame_exclusive=100),
        shot_id="shot-0000",
        capability=capability,
        protected_intervals=protected,
    )
    assert [(c.core.start_frame, c.core.end_frame_exclusive) for c in shot.chunks] == [
        (0, 50),
        (50, 100),
    ]
    assert shot.boundary_shifts == ()
    assert shot.chunks[0].protected_straddles == ()
    assert shot.chunks[1].protected_straddles == ("int-wide",)
    _assert_chunk_invariants(shot, capability)


def test_chunking_context_invalid_refusals() -> None:
    capability = plan.CapabilityFrameLimit(max_frames=81)
    span = plan.SourceSpan(start_frame=0, end_frame_exclusive=10)
    _refuses(
        plan.CODE_CONTEXT_INVALID,
        plan.plan_shot_chunks,
        span,
        shot_id="s",
        capability=capability,
        context_frames_per_side=-1,
    )
    _refuses(
        plan.CODE_CONTEXT_INVALID,
        plan.plan_shot_chunks,
        span,
        shot_id="s",
        capability=capability,
        context_frames_per_side=41,
    )


def test_build_shot_plan_real_file_end_to_end(cut60: Path) -> None:
    artifact = plan.build_shot_plan(
        cut60,
        plan_artifact_id="plan-e2e",
        source_artifact_id="src-e2e",
        capability=plan.CapabilityFrameLimit(max_frames=17),
    )
    assert artifact.detector.mode == "scenedetect"
    assert artifact.facts.frame_count == 60
    assert [s.span.start_frame for s in artifact.shots] == [0, 30]
    assert [len(s.chunks) for s in artifact.shots] == [2, 2]  # 30 frames / budget 17
    for shot in artifact.shots:
        _assert_chunk_invariants(shot, artifact.capability)
    assert artifact.content_sha256 == artifact.computed_digest()


# ── MF-END-11.4: versioned artifact + invalidation ───────────────────────────


def test_artifact_round_trip_and_digest_stability(cfr30: Path) -> None:
    artifact = plan.build_shot_plan(cfr30, plan_artifact_id="plan-rt")
    payload = artifact.to_json()
    reloaded = plan.ShotPlanArtifact.from_json(payload)
    assert reloaded.to_json() == payload
    assert reloaded.content_sha256 == artifact.content_sha256
    assert artifact.computed_digest() == plan.ShotPlanArtifact.from_json(payload).computed_digest()
    assert json.loads(json.dumps(payload)) == payload  # plain JSON, no exotic types


def test_artifact_unknown_version_refuses(cfr30: Path) -> None:
    payload = plan.build_shot_plan(cfr30).to_json()
    payload["plan_version"] = "mf.shot_reskin.plan.v2"
    _refuses(plan.CODE_VERSION_UNSUPPORTED, plan.ShotPlanArtifact.from_json, payload)


def test_artifact_digest_tamper_refuses(cfr30: Path) -> None:
    payload = plan.build_shot_plan(cfr30).to_json()
    payload["shots"][0]["chunks"][0]["chunk_id"] = "shot-0000:chunk-999"
    _refuses(plan.CODE_DIGEST_MISMATCH, plan.ShotPlanArtifact.from_json, payload)


def test_artifact_span_tamper_refuses_coverage(cfr30: Path) -> None:
    payload = plan.build_shot_plan(cfr30).to_json()
    # Self-consistent tamper (span = core = render = trim) so ONLY the
    # coverage law is red, not the per-chunk consistency checks.
    payload["shots"][0]["span"] = [0, 29]
    payload["shots"][0]["chunks"][0]["core"] = [0, 29]
    payload["shots"][0]["chunks"][0]["render"] = [0, 29]
    payload["shots"][0]["chunks"][0]["output_trim_end"] = 29
    _refuses(plan.CODE_COVERAGE_INVALID, plan.ShotPlanArtifact.from_json, payload)


def test_invalidation_valid_for_unchanged_source(cfr30: Path) -> None:
    artifact = plan.build_shot_plan(cfr30)
    verdict = plan.check_plan_validity(artifact, current_facts=plan.probe_source_facts(cfr30))
    assert verdict.valid is True
    assert verdict.status == plan.INVALIDATION_VALID
    assert verdict.reasons == (plan.CODE_VALID,)


def test_invalidation_source_changed_after_edit(cfr30: Path, cfr30_changed: Path) -> None:
    artifact = plan.build_shot_plan(cfr30)
    verdict = plan.invalidate_if_source_changed(artifact, cfr30_changed)
    assert verdict.valid is False
    assert verdict.status == plan.INVALIDATION_SOURCE_CHANGED
    assert verdict.reasons == (plan.CODE_SOURCE_CHANGED,)
    _refuses(
        plan.CODE_SOURCE_CHANGED,
        plan.require_current_plan,
        artifact,
        source_path=cfr30_changed,
    )
    assert plan.require_current_plan(artifact, source_path=cfr30) is not None


def test_invalidation_timebase_changed_same_digest(cfr30: Path) -> None:
    artifact = plan.build_shot_plan(cfr30)
    facts = plan.probe_source_facts(cfr30)
    forged = replace(
        facts,
        frame_count=facts.frame_count + 1,
        pts_ticks=facts.pts_ticks + (facts.pts_end_ticks + 512,),
        pts_end_ticks=facts.pts_end_ticks + 512,
    )
    verdict = plan.check_plan_validity(artifact, current_facts=forged)
    assert verdict.valid is False
    assert verdict.status == plan.INVALIDATION_TIMEBASE_CHANGED
    assert verdict.reasons == (plan.CODE_TIMEBASE_CHANGED,)


def test_unsealed_plan_refuses(cfr30: Path) -> None:
    artifact = plan.build_shot_plan(cfr30)
    unsealed = replace(artifact, content_sha256="")
    _refuses(
        plan.CODE_DIGEST_MISMATCH,
        plan.check_plan_validity,
        unsealed,
        current_facts=plan.probe_source_facts(cfr30),
    )


# ── one-frame / tail acceptance on REAL sources ──────────────────────────────


def test_one_frame_source_plan(one_frame: Path) -> None:
    facts = plan.probe_source_facts(one_frame)
    assert facts.frame_count == 1
    assert facts.pts_ticks == (0,)
    assert facts.pts_uniform is True  # no gaps -> vacuously uniform
    artifact = plan.build_shot_plan(one_frame)
    shot = artifact.shots[0]
    assert (shot.span.start_frame, shot.span.end_frame_exclusive) == (0, 1)
    chunk = shot.chunks[0]
    assert (chunk.core.start_frame, chunk.core.end_frame_exclusive) == (0, 1)
    assert (chunk.render.start_frame, chunk.render.end_frame_exclusive) == (0, 1)
    assert (chunk.output_trim_start, chunk.output_trim_end) == (0, 1)
    assert artifact.facts.timebase_facts().pts_span_ticks == 0
    assert artifact.content_sha256 == artifact.computed_digest()


def test_vfr_source_plan_full_coverage(vfr_drop: Path) -> None:
    facts = plan.probe_source_facts(vfr_drop)
    artifact = plan.build_shot_plan(vfr_drop)
    problems = validate_half_open_partition(
        [(s.span.start_frame, s.span.end_frame_exclusive) for s in artifact.shots],
        facts.frame_count,
    )
    assert problems == []
    assert artifact.facts.fps_classification == "VFR"
    assert artifact.shots[0].span.end_frame_exclusive == facts.frame_count
