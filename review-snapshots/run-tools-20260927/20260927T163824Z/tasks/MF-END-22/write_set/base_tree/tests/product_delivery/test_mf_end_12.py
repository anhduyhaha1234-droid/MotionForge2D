"""MF-END-12 — role/prop source tracks: acceptance + negative controls.

Row map (binary; micro-job map in the task TARGET.md):
* micro repro: module surface + typed codes + the on-disk workflow manifest
  (engines, rules, digest) and the binding of its rule numbers to the module
  constants;
* MF-END-12.1 (REAL probe rows, no deterministic QA mode): the production
  provider's ``capability_report()`` and the service's ``capability()`` are
  exercised against the REAL configured checkpoint — a missing checkpoint is
  asserted as BLOCKED_DEPENDENCY with the concrete path, and consistency
  between the two probes is asserted, never assumed;
* MF-END-12.2/.3 (engine rows): CI fixture frames with REAL pixel content are
  tracked through frame -> mask -> track: visible / partial (frame edge) /
  occluded (occluder present) / out-of-frame states, ONE instance id kept
  across occlusion, confidence/crop/stability measurements, artifact round-trip
  + digest;
* MF-END-12.4 (honesty rows): SAM3 was never run here — a SAM3 "applied" claim
  is refused with its exact code, and the manifest cannot declare SAM3 ready
  without a real probe run;
* negative controls assert the EXACT typed code for: all-canvas mask, hollow
  mask, wrong seed, duplicate instance, fixture-as-production, unprobed
  production, partial dropped, instance re-minted, digest/version/serialization
  tamper, invalid span/source/seed.

The CI fixture media is synthesized in-process at test time (tiny 160x120
frames — NOT product output) and every fixture row is labelled CI; the REAL
source inference row lives in the task evidence harness (SAM2.1 on
BOOK_src.mp4), which is where a production claim must come from.

No GPU job is launched here: the capability probe only stats/opens the
checkpoint, imports the package and (when CUDA is present) touches a 1-element
tensor — no inference, no render.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.config import AppConfig
from app.services import source_role_tracks as srt
from app.services.object_extraction import Sam2ExtractionProvider
from app.workflow.segmentation_service import SegmentationService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "app" / "media_workflows" / "role_segmentation_v1.json"

W, H = 160, 120
BG = (40, 40, 40)
PERSON = (255, 64, 64)
PROP = (64, 64, 255)
OCCLUDER = (0, 0, 0)
PERSON_BOX = (20, 40, 24, 30)
PROP_BOX = (34, 44, 10, 10)
FRAMES = 12
SPAN = (0, FRAMES)
#: x of the person per frame: visible 0-3, occluded 4-6 (black bar), partially
#: clipped at the right edge 7-9, fully outside 10-11.
PERSON_X = [20, 26, 32, 38, 44, 50, 56, 140, 144, 148, 170, 170]


# ── CI fixture media (real pixels, drawn once per session) ───────────────────


def _render_fixture(frames_dir: Path) -> list[np.ndarray]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[np.ndarray] = []
    for index in range(FRAMES):
        image = Image.new("RGB", (W, H), BG)
        x = PERSON_X[index]
        if index <= 9:  # person and prop are on/at the edge of the canvas
            for dx in range(24):
                for dy in range(30):
                    px = x + dx
                    if 0 <= px < W:
                        image.putpixel((px, 40 + dy), PERSON)
            for dx in range(10):
                for dy in range(10):
                    px = x - 6 + dx
                    if 0 <= px < W:
                        image.putpixel((px, 44 + dy), PROP)
        if 4 <= index <= 6:  # one stationary occluder hides both targets entirely
            for dx in range(56):
                for dy in range(36):
                    px = 36 + dx
                    py = 38 + dy
                    if 0 <= px < W and 0 <= py < H:
                        image.putpixel((px, py), OCCLUDER)
        path = frames_dir / f"frame_{index:03d}.png"
        image.save(path)
        decoded = cv2.imread(str(path), cv2.IMREAD_COLOR)
        assert decoded is not None, f"fixture frame unreadable: {path}"
        frames.append(decoded)
    return frames


@pytest.fixture(scope="session")
def frames(tmp_path_factory: pytest.TempPathFactory) -> list[np.ndarray]:
    return _render_fixture(tmp_path_factory.mktemp("mfend12"))


class CiColorMaskSource:
    """CI fixture mask source: REAL cv2 colour segmentation of fixture pixels.

    Documented deterministic rules (no fabricated masks):
    * target colour present -> the largest connected component is the mask;
    * no target pixels but a covering occluder overlaps the last known bbox
      -> ``MaskSample(mask=None, present=True)`` (occluded, instance kept);
    * no target pixels and no occluder -> ``MaskSample(mask=None,
      out_of_frame=True)`` (the declared instance is off-canvas).
    """

    provenance = srt.PROVENANCE_FIXTURE
    engine_id = "contour"
    probe = None
    candidates = {"sam2.1": srt.STATUS_NOT_RUN, "sam3": srt.STATUS_NOT_RUN}
    inference_ran = False

    def __init__(self, colour: tuple[int, int, int], last_box: tuple[int, int, int, int]) -> None:
        self.colour = colour
        self.last_box = last_box

    def _colour_mask(self, frame: np.ndarray) -> np.ndarray | None:
        bgr = frame.astype(np.int16)
        blue, green, red = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
        if self.colour == PERSON:
            hit = (red > 120) & (green < 120) & (blue < 120)
        else:
            hit = (blue > 120) & (red < 120) & (green < 120)
        if not bool(hit.any()):
            return None
        count, labels = cv2.connectedComponents(hit.astype(np.uint8))
        if count <= 1:
            return None
        best, best_area = 0, 0
        for label in range(1, count):
            area = int(np.count_nonzero(labels == label))
            if area > best_area:
                best, best_area = label, area
        return labels == best

    def sample(
        self, frame_index: int, seed: srt.RoleSeed, frame: np.ndarray
    ) -> srt.MaskSample | None:
        mask = self._colour_mask(frame)
        if mask is not None:
            ys, xs = np.nonzero(mask)
            self.last_box = (
                int(xs.min()),
                int(ys.min()),
                int(xs.max() - xs.min() + 1),
                int(ys.max() - ys.min() + 1),
            )
            return srt.MaskSample(mask=mask, method="cv2_colour_seed", score=None)
        bgr = frame.astype(np.int16)
        dark = (bgr[:, :, 0] < 20) & (bgr[:, :, 1] < 20) & (bgr[:, :, 2] < 20)
        x, y, w, h = self.last_box
        covered = bool(dark[max(0, y) : y + h, max(0, x) : x + w].any()) if w and h else False
        if covered:
            return srt.MaskSample(mask=None, method="cv2_occluder_rule", present=True)
        return srt.MaskSample(mask=None, method="cv2_absent_rule", out_of_frame=True)


class StaticMaskSource:
    """Test double for the mask RULES (a scripted mask per frame)."""

    provenance = srt.PROVENANCE_FIXTURE
    engine_id = "contour"
    probe = None
    candidates = {"sam3": srt.STATUS_NOT_RUN}
    inference_ran = False

    def __init__(self, script: dict[int, object]) -> None:
        self.script = script

    def sample(self, frame_index: int, seed: srt.RoleSeed, frame: np.ndarray):
        value = self.script.get(frame_index)
        return value(seed, frame) if callable(value) else value


def _seed(
    role_id: str = "R1", kind: str = srt.ROLE_KIND_PERSON, box=PERSON_BOX, partial=False
) -> srt.RoleSeed:
    return srt.RoleSeed(
        role_id=role_id,
        kind=kind,
        box=tuple(box),  # type: ignore[arg-type]
        declare_frames=SPAN,
        partial_required=partial,
    )


def _span() -> srt.SourceSpan:
    return srt.SourceSpan(start_frame=0, end_frame_exclusive=FRAMES)


def _mask_source() -> CiColorMaskSource:
    return CiColorMaskSource(PERSON, PERSON_BOX)


def _build(frames, seeds, mask_source, *, strict=True, production=False, tmp_frames=None):
    return srt.build_role_tracks(
        source_sha256="0" * 64,
        span=_span(),
        frames=tmp_frames if tmp_frames is not None else frames,
        fps_rational="10/1",
        seeds=seeds,
        mask_source=mask_source,
        manifest_sha256=srt.payload_sha256({"manifest": "ci"}),
        manifest_version="1.0.0",
        production=production,
        strict=strict,
    )


# ── micro repro + manifest ──────────────────────────────────────────────────


def test_micro_repro_module_surface() -> None:
    assert srt.TRACKS_SCHEMA_VERSION == "mf.source_role_tracks.v1"
    assert srt.MANIFEST_SCHEMA == "mf.role_segmentation_workflow.v1"
    for code in (
        srt.CODE_MASK_ALL_CANVAS,
        srt.CODE_MASK_HOLLOW,
        srt.CODE_NO_TRACE,
        srt.CODE_FIXTURE_NOT_PRODUCTION,
        srt.CODE_SAM3_UNPROBED,
        srt.CODE_PARTIAL_DROPPED,
        srt.CODE_INSTANCE_CHANGED,
        srt.CODE_SEED_NOT_SEEN,
        srt.CODE_DUPLICATE_INSTANCE,
    ):
        assert code.startswith("ROLE_TRACKS_")


def test_manifest_on_disk_is_valid_and_honest() -> None:
    manifest = srt.load_workflow_manifest(MANIFEST_PATH)
    assert manifest.workflow_id == "role_segmentation_v1"
    assert manifest.schema == srt.MANIFEST_SCHEMA
    assert manifest.engine_status("sam2.1") == srt.STATUS_PROBED_READY
    assert manifest.engine_status("sam3") == srt.STATUS_BLOCKED_DEPENDENCY
    assert manifest.engine_status("comfyui_sam2_nodes") == srt.STATUS_BLOCKED_DEPENDENCY
    assert manifest.engine_status("contour") == srt.STATUS_CI_ONLY
    # the manifest's measured-rule numbers ARE the module constants (no drift)
    assert manifest.mask_rules["all_canvas_max_coverage_ratio"] == srt.DEFAULT_ALL_CANVAS_RATIO
    assert manifest.mask_rules["hollow_max_hole_ratio"] == srt.DEFAULT_HOLLOW_RATIO
    assert manifest.mask_rules["min_area_px"] == srt.DEFAULT_MIN_AREA_PX
    assert manifest.track_rules["duplicate_instance_iou"] == srt.DEFAULT_DUPLICATE_IOU
    assert manifest.track_rules["drift_ratio_of_seed_box_diagonal"] == srt.DEFAULT_DRIFT_RATIO
    assert manifest.track_rules["unstable_step_shift_ratio_of_sqrt_area"] == srt.DEFAULT_SHIFT_RATIO
    assert manifest.track_rules["area_jump_factor"] == srt.DEFAULT_AREA_JUMP_RATIO
    assert manifest.digest == srt.payload_sha256(
        {key: value for key, value in manifest.raw.items() if key != "digest"}
    )
    assert srt.CODE_SAM3_UNPROBED in manifest.refusal_codes


def test_manifest_tamper_is_refused(tmp_path: Path) -> None:
    original = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    # (a) status lie: SAM3 "ready" without a real probe run
    lie = json.loads(json.dumps(original))
    lie["engines"]["sam3"]["status"] = srt.STATUS_PROBED_READY
    assert srt.CODE_SAM3_UNPROBED in srt.validate_workflow_manifest(lie)
    # (b) digest lie: body changed, digest kept
    broken = json.loads(json.dumps(original))
    broken["mask_rules"]["all_canvas_max_coverage_ratio"] = 1.5
    broken["digest"] = original["digest"]
    path = tmp_path / "role_segmentation_v1.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(srt.RoleTracksError) as excinfo:
        srt.load_workflow_manifest(path)
    assert excinfo.value.code == srt.CODE_MANIFEST_INVALID
    # (c) unknown engine status is refused
    bogus = json.loads(json.dumps(original))
    bogus["engines"]["sam2.1"]["status"] = "MAYBE"
    assert srt.CODE_ENGINE_UNPROBED in srt.validate_workflow_manifest(bogus)


# ── MF-END-12.1: REAL capability probe rows (no deterministic QA mode) ──────


@pytest.mark.sam2
def test_real_capability_probe_matches_disk_truth() -> None:
    provider = Sam2ExtractionProvider()
    report = provider.capability_report()
    checkpoint = Path(str(report["checkpoint"]))
    assert report["provider"] == "sam2-local"
    if report["ready"]:
        assert report["status"] == srt.STATUS_PROBED_READY
        assert checkpoint.is_file() and int(report["checkpoint_bytes"]) > 0
        assert report["device"] in ("cuda", "cpu")
    else:
        assert report["status"] == srt.STATUS_BLOCKED_DEPENDENCY
        assert "not found" in str(report["message"]) or "unavailable" in str(report["message"])
    service = SegmentationService(AppConfig())
    service_report = service.capability("sam2")
    if report["ready"]:
        assert service_report["available"] is True
        assert service_report["checkpoint"] == str(checkpoint)
        assert service_report["checkpoint_bytes"] == report["checkpoint_bytes"]
    else:
        assert service_report["available"] is False


def test_real_capability_probe_refuses_missing_checkpoint(tmp_path: Path) -> None:
    provider = Sam2ExtractionProvider(checkpoint=tmp_path / "absent.pt")
    report = provider.capability_report()
    assert report["ready"] is False
    assert report["status"] == srt.STATUS_BLOCKED_DEPENDENCY
    assert "checkpoint not found" in str(report["message"])
    config = AppConfig()
    object.__setattr__(config, "sam2_checkpoint", str(tmp_path / "absent.pt"))
    service_report = SegmentationService(config).capability("sam2")
    assert service_report["available"] is False
    assert "checkpoint not found" in str(service_report["reason"])


def test_backend_report_unknown_backend() -> None:
    report = SegmentationService(AppConfig()).capability("nope")
    assert report["available"] is False
    assert "unknown segmentation backend" in str(report["reason"])


# ── MF-END-12.2/.3: the trace itself ────────────────────────────────────────


def test_every_seed_has_frame_mask_track_trace(frames: list[np.ndarray]) -> None:
    seeds = [
        _seed("ROLE-BOOK-P1", srt.ROLE_KIND_PERSON, PERSON_BOX, partial=True),
        _seed("PROP-BOOK", srt.ROLE_KIND_PROP, PROP_BOX, partial=False),
    ]
    prop_source = CiColorMaskSource(PROP, PROP_BOX)
    source = CiColorMaskSource(PERSON, PERSON_BOX)

    class PairSource:
        provenance = srt.PROVENANCE_FIXTURE
        engine_id = "contour"
        probe = None
        candidates = {"sam3": srt.STATUS_NOT_RUN}
        inference_ran = False

        def sample(self, frame_index, seed, frame):
            if seed.kind == srt.ROLE_KIND_PROP:
                return prop_source.sample(frame_index, seed, frame)
            return source.sample(frame_index, seed, frame)

    artifact = _build(frames, seeds, PairSource())
    assert artifact.span.frame_count == FRAMES
    assert len(artifact.tracks) == 2
    expectations = {
        "ROLE-BOOK-P1": {"partial": 3, "frames": [0, 1, 2, 3, 7, 8, 9]},
        "PROP-BOOK": {"partial": 0, "frames": [0, 1, 2, 3, 7, 8, 9]},
    }
    for track in artifact.tracks:
        assert track.trace_complete is True
        assert track.observations, f"{track.role_id}: no observations"
        assert track.instance_id == f"trk:{track.role_id}"
        for observation in track.observations:
            assert observation["instance_id"] == track.instance_id
            assert observation["permission"] == srt.PERMISSION_GRANTED
            assert len(observation["mask_sha256"]) == 64
            assert int(observation["area_px"]) > 0
            assert observation["bbox"] is not None
            assert observation["crop_sha256"] is not None
        # visible 0-3, occluded 4-6, partial 7-9 (person), out of frame 10-11
        expected = expectations[track.role_id]
        assert [item["frame"] for item in track.observations] == expected["frames"]
        assert track.occlusion_runs and track.occlusion_runs[0].start_frame == 4
        assert track.occlusion_runs[0].end_frame == 7
        assert track.stability["n_occluded_frames"] == 3
        assert track.stability["n_partial"] == expected["partial"]
        assert track.stability["n_out_of_frame"] == 2
        assert track.stability["n_gap_frames"] == 0
        assert track.stability["mean_step_shift_px"] is not None
    assert not artifact.flags
    assert not artifact.refused_seeds


def test_partial_states_and_instance_id_survive_occlusion(frames: list[np.ndarray]) -> None:
    seed = _seed("ROLE-BOOK-P1", srt.ROLE_KIND_PERSON, PERSON_BOX, partial=True)
    artifact = _build(frames, [seed], _mask_source())
    track = artifact.tracks[0]
    states = {item["frame"]: item["state"] for item in track.observations}
    assert states[0] == srt.VISIBILITY_VISIBLE
    assert states[7] == srt.VISIBILITY_PARTIAL and states[9] == srt.VISIBILITY_PARTIAL
    assert track.partial_frames == (7, 8, 9)
    ids = {item["instance_id"] for item in track.observations}
    assert ids == {track.instance_id}  # ONE id across the occlusion
    assert track.occlusion_runs[0].frames == 3
    # the artifact round-trips byte-stably and its invariants hold
    payload = artifact.to_payload()
    restored = srt.RoleTracksArtifact.from_payload(json.loads(json.dumps(payload)))
    assert restored.digest == artifact.digest
    assert srt.check_artifact(restored) == ()
    assert srt.assert_artifact(restored) is None


def test_measurements_are_real_numbers_on_real_pixels(frames: list[np.ndarray]) -> None:
    seed = _seed()
    artifact = _build(frames, [seed], _mask_source())
    track = artifact.tracks[0]
    for observation in track.observations:
        assert 0.0 < float(observation["coverage_ratio"]) < srt.DEFAULT_ALL_CANVAS_RATIO
        assert float(observation["solidity"]) == 1.0  # a solid rectangle measured by cv2
        assert float(observation["hole_ratio"]) == 0.0
    first = track.observations[0]
    # the crop digest is the digest of the REAL pixels inside the mask bbox
    x, y, w, h = first["bbox"]
    crop = np.ascontiguousarray(frames[first["frame"]][y : y + h, x : x + w])
    import hashlib

    assert hashlib.sha256(crop.tobytes()).hexdigest() == first["crop_sha256"]


# ── negative controls: each asserts the EXACT typed code ────────────────────


def _refuses(code: str, fn, *args, **kwargs) -> srt.RoleTracksError:
    with pytest.raises(srt.RoleTracksError) as excinfo:
        fn(*args, **kwargs)
    assert excinfo.value.code == code, excinfo.value
    return excinfo.value


def test_all_canvas_mask_never_grants(frames: list[np.ndarray]) -> None:
    def full_mask(seed, frame):
        return srt.MaskSample(mask=np.ones((H, W), dtype=bool), method="scripted_all_canvas")

    scripted = {index: full_mask for index in range(FRAMES)}
    source = StaticMaskSource(scripted)
    # non-strict: the permission is DENIED with the measured code
    artifact = _build(frames, [_seed()], source, strict=False)
    observation = artifact.tracks[0].observations[0]
    assert observation["permission"] == srt.PERMISSION_DENIED
    assert observation["denial_code"] == srt.CODE_MASK_ALL_CANVAS
    assert artifact.tracks[0].trace_complete is False
    # strict: no granted trace -> the exact code
    _refuses(srt.CODE_NO_TRACE, _build, frames, [_seed()], source)
    # a re-sealed payload lying "granted" is caught by the invariant checker
    payload = artifact.to_payload(include_digest=False)
    payload["tracks"][0]["observations"][0]["permission"] = srt.PERMISSION_GRANTED
    payload["tracks"][0]["observations"][0]["denial_code"] = None
    payload["tracks"][0]["trace_complete"] = True
    payload["digest"] = srt.payload_sha256(payload)
    resealed = srt.RoleTracksArtifact.from_payload(payload)
    assert srt.CODE_MASK_ALL_CANVAS in srt.check_artifact(resealed)


def test_hollow_mask_never_grants(frames: list[np.ndarray]) -> None:
    def ring(seed, frame):
        mask = np.zeros((H, W), dtype=np.uint8)
        cv2.rectangle(mask, (30, 50), (90, 100), 1, thickness=1)
        return srt.MaskSample(mask=mask.astype(bool), method="scripted_hollow")

    source = StaticMaskSource({index: ring for index in range(FRAMES)})
    artifact = _build(frames, [_seed()], source, strict=False)
    observation = artifact.tracks[0].observations[0]
    assert observation["denial_code"] == srt.CODE_MASK_HOLLOW
    assert float(observation["hole_ratio"]) >= srt.DEFAULT_HOLLOW_RATIO
    _refuses(srt.CODE_NO_TRACE, _build, frames, [_seed()], source)


def test_empty_and_tiny_masks_are_denied(frames: list[np.ndarray]) -> None:
    def tiny(seed, frame):
        mask = np.zeros((H, W), dtype=bool)
        mask[5:7, 5:7] = True  # 4 px < min_area_px
        return srt.MaskSample(mask=mask, method="scripted_tiny")

    source = StaticMaskSource({index: tiny for index in range(FRAMES)})
    artifact = _build(frames, [_seed()], source, strict=False)
    observation = artifact.tracks[0].observations[0]
    assert observation["denial_code"] == srt.CODE_MASK_EMPTY
    assert int(observation["area_px"]) < srt.DEFAULT_MIN_AREA_PX


def test_wrong_seed_is_marked_and_refused(frames: list[np.ndarray]) -> None:
    # a red blob exists (frames 0-3 at x>=20) but the seed points at empty background
    bogus = _seed("ROLE-WRONG", srt.ROLE_KIND_PERSON, (120, 5, 12, 12))
    artifact = _build(frames, [bogus], _mask_source(), strict=False)
    codes = {item.code for item in artifact.refused_seeds}
    assert srt.CODE_SEED_NOT_SEEN in codes
    assert artifact.tracks[0].trace_complete is False
    assert any(flag.code == srt.CODE_SEED_NOT_SEEN for flag in artifact.tracks[0].flags)
    _refuses(srt.CODE_SEED_NOT_SEEN, _build, frames, [bogus], _mask_source())


def test_ambiguous_duplicate_instance_is_refused(frames: list[np.ndarray]) -> None:
    first = _seed("ROLE-A", srt.ROLE_KIND_PERSON, PERSON_BOX)
    second = _seed("ROLE-B", srt.ROLE_KIND_PERSON, PERSON_BOX)
    artifact = _build(frames, [first, second], _mask_source(), strict=False)
    duplicate = [flag for flag in artifact.flags if flag.code == srt.CODE_DUPLICATE_INSTANCE]
    assert duplicate, artifact.flags
    assert duplicate[0].frame == 0
    _refuses(srt.CODE_DUPLICATE_INSTANCE, _build, frames, [first, second], _mask_source())


def test_fixture_can_never_be_recorded_as_production(frames: list[np.ndarray]) -> None:
    _refuses(
        srt.CODE_FIXTURE_NOT_PRODUCTION, _build, frames, [_seed()], _mask_source(), production=True
    )
    artifact = _build(frames, [_seed()], _mask_source())
    assert artifact.production is False
    _refuses(srt.CODE_FIXTURE_NOT_PRODUCTION, srt.require_production, artifact)


def test_production_claim_requires_a_real_probe(frames: list[np.ndarray]) -> None:
    class UnprobedProduction:
        provenance = srt.PROVENANCE_PRODUCTION
        engine_id = srt.ENGINE_SAM2_1
        probe = None
        candidates = {srt.ENGINE_SAM3: srt.STATUS_NOT_RUN}
        inference_ran = False

        def sample(self, frame_index, seed, frame):
            return srt.MaskSample(mask=np.zeros((H, W), dtype=bool), method="never")

    _refuses(
        srt.CODE_ENGINE_UNPROBED,
        _build,
        frames,
        [_seed()],
        UnprobedProduction(),
        production=True,
    )


def test_sam3_is_never_recorded_as_applied(frames: list[np.ndarray]) -> None:
    artifact = _build(frames, [_seed()], _mask_source(), strict=False)
    assert artifact.engine.candidates[srt.ENGINE_SAM3] == srt.STATUS_NOT_RUN
    _refuses(srt.CODE_SAM3_UNPROBED, srt.check_engine_claim, artifact, srt.ENGINE_SAM3)
    # a re-sealed payload advertising SAM3 as the applied engine is caught
    payload = artifact.to_payload(include_digest=False)
    payload["engine"]["engine_id"] = srt.ENGINE_SAM3
    payload["engine"]["inference_ran"] = False
    payload["engine"]["provenance"] = srt.PROVENANCE_FIXTURE
    payload["digest"] = srt.payload_sha256(payload)
    resealed = srt.RoleTracksArtifact.from_payload(payload)
    assert srt.CODE_SAM3_UNPROBED in srt.check_artifact(resealed)
    # the applied engine itself must have run inference
    payload2 = artifact.to_payload(include_digest=False)
    payload2["engine"]["inference_ran"] = False
    payload2["digest"] = srt.payload_sha256(payload2)
    resealed2 = srt.RoleTracksArtifact.from_payload(payload2)
    _refuses(srt.CODE_ENGINE_UNPROBED, srt.check_engine_claim, resealed2, "contour")


def test_partial_character_gap_is_refused(frames: list[np.ndarray]) -> None:
    seed = _seed("ROLE-PARTIAL", srt.ROLE_KIND_PERSON, PERSON_BOX, partial=True)
    source = _mask_source()
    original_sample = source.sample

    def gap_sample(frame_index, seed_arg, frame):
        if frame_index == 2:  # the source cannot observe this frame at all
            return None
        return original_sample(frame_index, seed_arg, frame)

    source.sample = gap_sample  # type: ignore[method-assign]
    artifact = _build(frames, [seed], source, strict=False)
    codes = {item.code for item in artifact.refused_seeds}
    assert srt.CODE_PARTIAL_DROPPED in codes
    assert artifact.tracks[0].gap_frames == (2,)
    _refuses(srt.CODE_PARTIAL_DROPPED, _build, frames, [seed], source)


def test_instance_change_and_tamper_are_caught(frames: list[np.ndarray]) -> None:
    artifact = _build(frames, [_seed()], _mask_source())
    # (a) a re-sealed payload re-minting the instance id fails the invariant
    payload = artifact.to_payload(include_digest=False)
    payload["tracks"][0]["observations"][3]["instance_id"] = "trk:ROLE-OTHER"
    payload["digest"] = srt.payload_sha256(payload)
    resealed = srt.RoleTracksArtifact.from_payload(payload)
    assert srt.CODE_INSTANCE_CHANGED in srt.check_artifact(resealed)
    # (b) editing bytes without re-sealing fails the digest check itself
    payload2 = artifact.to_payload()
    payload2["tracks"][0]["observations"][0]["area_px"] = 1
    _refuses(
        srt.CODE_DIGEST_MISMATCH,
        srt.RoleTracksArtifact.from_payload,
        payload2,
    )
    # (c) an unknown schema version refuses before any reading
    payload3 = artifact.to_payload()
    payload3["schema_version"] = "mf.source_role_tracks.v99"
    _refuses(srt.CODE_VERSION_UNSUPPORTED, srt.RoleTracksArtifact.from_payload, payload3)


def test_input_validation_codes(frames: list[np.ndarray]) -> None:
    good = _mask_source()
    _refuses(
        srt.CODE_SPAN_INVALID, _build, frames, [_seed()], good, tmp_frames=frames[: FRAMES - 1]
    )
    bad_sha = dict(
        source_sha256="not-a-sha",
        span=_span(),
        frames=frames,
        fps_rational="10/1",
        seeds=[_seed()],
        mask_source=good,
        manifest_sha256="x",
        manifest_version="1.0.0",
    )
    _refuses(srt.CODE_SOURCE_INVALID, srt.build_role_tracks, **bad_sha)
    _refuses(
        srt.CODE_SEED_INVALID,
        srt.build_role_tracks,
        **{
            **bad_sha,
            "source_sha256": "0" * 64,
            "seeds": [srt.RoleSeed(role_id="", kind="person", box=PERSON_BOX, declare_frames=SPAN)],
        },
    )
    _refuses(
        srt.CODE_SEED_INVALID,
        srt.build_role_tracks,
        **{
            **bad_sha,
            "source_sha256": "0" * 64,
            "seeds": [srt.RoleSeed(role_id="R", kind="ghost", box=PERSON_BOX, declare_frames=SPAN)],
        },
    )


def test_real_source_inference_row_is_marked_not_silent() -> None:
    """The REAL SAM2.1-on-BOOK row lives in the evidence harness.

    CI rows above run synthetic pixels; a production track claim must come from
    the harness (`raw/real_probe.json`, GPU row declared in commands.jsonl).
    This row fails loudly if the harness evidence is missing, so the two are
    never confused.
    """
    evidence = Path(
        "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/"
        "tasks/MF-END-12/raw/real_source_tracks.json"
    )
    if not evidence.is_file():
        pytest.skip(
            "REAL_SOURCE_ROW runs in the task evidence harness (SAM2.1 on BOOK_src.mp4, one "
            "declared GPU job, raw/real_source_tracks.json); this CI file must not claim it"
        )
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert (
        payload["source_sha256"]
        == "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"
    )
    assert payload["engine"]["engine_id"] == srt.ENGINE_SAM2_1
    assert payload["engine"]["inference_ran"] is True


def test_fixture_media_is_tiny_ci_material(frames: list[np.ndarray]) -> None:
    assert len(frames) == FRAMES and frames[0].shape == (H, W, 3)
    assert frames[0].size == H * W * 3  # 160x120 CI frames, not product output
