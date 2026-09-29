"""DV3-R2-T04 acceptance: public pipeline wiring, fail-closed gates, H264 path.

Covers the T04 packet acceptance rows without a compatible render pack
(V3 pinned asset stays a fail-closed negative — no 120-frame render here):

- real API negatives/ownership via the public routes (404 project, 422
  pack gate before heavy work, 403 preview-only approval, 404 foreign job);
- deterministic revised identity/replay (identical replay converges,
  changed pack/geometry inputs yield a new identity);
- source/asset/mask tamper rejects (final-input + persisted-manifest paths);
- no accidental live-DB selection (QA root guard rejects MAIN/CWD roots);
- preview-only authority (policy binding + approve rejection);
- worker consumes the T01/T03 transform/layer contract per frame;
- H264/yuv420p encode path via the runnable FFmpeg on synthetic frames.

Isolated: every test uses ``tmp_path`` stores; no servers/ports, no MAIN
contact.  Endpoints that need a legacy project use a fixture project whose
``source_video`` points at a tiny generated MP4 under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.workflow.pilot_preview_jobs as jobs
from app.api import deps
from app.config import UnsafeRuntimeRootError, validate_runtime_roots
from app.services.pilot_preview.pose_composition import (
    COMPOSITION_REVISION,
    PoseCompositionError,
    book_state_at,
    check_layer_stack,
    layer_stack_for_frame,
    mouth_state_at,
    pose_state_at,
)
from app.services.pilot_preview.scene_contract import COMPAT_REQUIREMENTS, SOURCE_PINNED_SHA256
from app.workflow.pilot_preview_jobs import (
    PILOT_PIPELINE_REVISION,
    PILOT_RENDER_GEOMETRY,
    V3_NEGATIVE_ASSET_SHA256,
    PilotPreviewError,
    _assert_final_inputs,
    _probe_media,
    _remux,
    _validate_video,
    _write_video_only,
    build_output_relpaths,
    compute_input_identity_sha256,
    output_relpaths_for_manifest,
    pack_gate_verdict,
    require_pack_compatible,
)

V3_SHA = V3_NEGATIVE_ASSET_SHA256
OTHER_SHA = "f" * 64


def _submit_body(asset_sha: str = V3_SHA) -> dict[str, Any]:
    return {
        "project_id": "legacy-demo",
        "generation": "1",
        "start_frame": 450,
        "end_frame": 570,
        "role": "seated_character",
        "source_prompt": "Replace only the seated source character in the shot.",
        "asset_sha256": asset_sha,
        "mask_correction": {
            "bbox_xywh_norm": [0.32, 0.26, 0.16, 0.60],
            "source_frame": 450,
            "confidence": 0.94,
            "note": "operator-corrected removal region",
        },
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": [0.40, 0.55], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.42, 0.54], "scale": 1.0, "rotation_deg": 0.0},
        ],
        "occluder": {
            "layer_id": "foreground_right",
            "region_xywh_norm": [0.76, 0.34, 0.20, 0.66],
            "z": -1,
        },
    }


def _manifest(asset_sha: str = V3_SHA, capabilities: dict[str, bool] | None = None) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": "pilot-preview-v1",
        "pipeline_revision": PILOT_PIPELINE_REVISION,
        "render_geometry_contract": dict(PILOT_RENDER_GEOMETRY),
        "composition_revision": COMPOSITION_REVISION,
        "pack_capabilities": capabilities,
        "project_id": "demo",
        "durable_project_id": "durable-demo",
        "durable_video_item_id": "video-demo",
        "generation": "1",
        "source_sha256": "a" * 64,
        "asset_sha256": asset_sha,
        "sam2_checkpoint_sha256": "c" * 64,
        "sam2_model_cfg": "configs/sam2.1/sam2.1_hiera_l.yaml",
        "sam2_device": "cpu",
        "start_frame": 450,
        "end_frame": 570,
        "role": "seated_character",
        "source_prompt": "replace the seated source character",
        "mask_correction": {"bbox_xywh_norm": [0.32, 0.26, 0.16, 0.6], "source_frame": 450},
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": [0.4, 0.55], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.4, 0.55], "scale": 1.0, "rotation_deg": 0.0},
        ],
        "occluder": {"layer_id": "foreground_right", "region_xywh_norm": [0.76, 0.34, 0.2, 0.66], "z": -1},
        "policy": {"preview_only": True, "single_shot": True, "no_full_apply": True, "no_s12": True},
    }
    manifest["input_identity_sha256"] = compute_input_identity_sha256(manifest)
    manifest["output_relpaths"] = build_output_relpaths(str(manifest["input_identity_sha256"]))
    return manifest


def _full_capabilities() -> dict[str, bool]:
    return {key: True for key in COMPAT_REQUIREMENTS}


# ── pack gate: server-owned verdict before heavy work ────────────────────────


def test_r2_pack_gate_rejects_pinned_v3_negative() -> None:
    verdict = pack_gate_verdict({"asset_sha256": V3_SHA})
    assert verdict["compatible"] is False
    assert verdict["code"] == "PACK_COMPATIBILITY_FAILED"
    assert "grip_both_hands_chest" in verdict["missing"]
    assert "book_open_variant" in verdict["missing"]
    assert len(verdict["required"]) == 12


def test_r2_pack_gate_rejects_v3_despite_claimed_capabilities() -> None:
    """Submitter claims cannot override the server-owned V3 negative verdict."""
    verdict = pack_gate_verdict({"asset_sha256": V3_SHA, "pack_capabilities": _full_capabilities()})
    assert verdict["compatible"] is False
    with pytest.raises(PilotPreviewError, match="PACK_COMPATIBILITY_FAILED"):
        require_pack_compatible({"asset_sha256": V3_SHA, "pack_capabilities": _full_capabilities()})


def test_r2_pack_gate_rejects_missing_capabilities_map() -> None:
    verdict = pack_gate_verdict({"asset_sha256": OTHER_SHA})
    assert verdict["compatible"] is False
    assert "server-resolved versioned pack" in verdict["reason"]


def test_r2_pack_gate_requires_resolved_files_not_claimed_capabilities(tmp_path: Path) -> None:
    # A capability map alone is never a positive path.  The positive server
    # resolver/manifest fixture is covered by test_r2_pack_resolution.py.
    verdict = pack_gate_verdict({"asset_sha256": OTHER_SHA, "pack_capabilities": _full_capabilities()})
    assert verdict["compatible"] is False
    assert "server-resolved versioned pack" in verdict["reason"]


def test_r2_pack_gate_rejects_partial_capabilities() -> None:
    partial = _full_capabilities()
    partial["grip_both_hands_chest"] = False
    verdict = pack_gate_verdict({"asset_sha256": OTHER_SHA, "pack_capabilities": partial})
    assert verdict["compatible"] is False


# ── identity: deterministic replay, changed inputs → new identity ────────────


def test_r2_identity_replay_converges_and_changes_diverge() -> None:
    base = _manifest(asset_sha=OTHER_SHA, capabilities=_full_capabilities())
    replay = _manifest(asset_sha=OTHER_SHA, capabilities=_full_capabilities())
    assert replay["input_identity_sha256"] == base["input_identity_sha256"]
    assert replay["output_relpaths"] == base["output_relpaths"]

    changed_pack = _manifest(asset_sha=OTHER_SHA, capabilities=None)
    assert changed_pack["input_identity_sha256"] != base["input_identity_sha256"]

    changed_geo = dict(base)
    changed_geo["render_geometry_contract"] = {**PILOT_RENDER_GEOMETRY, "replacement_fit": "native_scale"}
    assert compute_input_identity_sha256(changed_geo) != base["input_identity_sha256"]

    changed_rev = dict(base)
    changed_rev["pipeline_revision"] = "other-revision"
    assert compute_input_identity_sha256(changed_rev) != base["input_identity_sha256"]

    changed_comp = dict(base)
    changed_comp["composition_revision"] = "other-composition"
    assert compute_input_identity_sha256(changed_comp) != base["input_identity_sha256"]


def test_r2_identity_binds_effective_scene_pack_plate_masks_and_algorithm() -> None:
    base = _manifest(asset_sha=OTHER_SHA, capabilities=_full_capabilities())
    for field, changed in (
        ("scene_contract_hash", "scene-tampered"),
        ("pack_content_sha256", "pack-tampered"),
        ("pack_state_identity", {"seated_book_open": {"sha256": "changed"}}),
        ("clean_plate_identity", {"algorithm": "different"}),
        ("protected_masks_identity", {"roles": ["room"]}),
        ("reconstruction_revision", "reconstruction-tampered"),
        ("effective_geometry", {"anchor": "wrong"}),
    ):
        altered = dict(base)
        altered[field] = changed
        assert compute_input_identity_sha256(altered) != base["input_identity_sha256"], field


def test_r2_output_path_tamper_fails_closed() -> None:
    manifest = _manifest(asset_sha=OTHER_SHA, capabilities=_full_capabilities())
    manifest["output_relpaths"] = {"before": "pilot-preview/before.mp4"}
    with pytest.raises(PilotPreviewError, match="OUTPUT_PATH_CONTRACT_FAILED"):
        output_relpaths_for_manifest(manifest)


def test_r2_final_inputs_reject_source_asset_mask_tamper(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"real-source-bytes")
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"real-asset-bytes")
    checkpoint = tmp_path / "sam2.pt"
    checkpoint.write_bytes(b"real-checkpoint-bytes")

    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = _manifest(asset_sha=OTHER_SHA, capabilities=_full_capabilities())
    manifest["source_sha256"] = _hash(source)
    manifest["asset_sha256"] = _hash(asset)
    manifest["sam2_checkpoint_sha256"] = _hash(checkpoint)
    manifest["pack_capabilities"] = _full_capabilities()
    manifest["input_identity_sha256"] = compute_input_identity_sha256(manifest)
    manifest["output_relpaths"] = build_output_relpaths(str(manifest["input_identity_sha256"]))

    tampered = dict(manifest)
    tampered["source_sha256"] = "0" * 64
    with pytest.raises(PilotPreviewError, match="SOURCE_HASH_MISMATCH_FINAL"):
        _assert_final_inputs(tampered, source, asset, checkpoint)

    tampered = dict(manifest)
    tampered["asset_sha256"] = "0" * 64
    with pytest.raises(PilotPreviewError, match="PACK_STATE_HASH_MISMATCH_FINAL"):
        _assert_final_inputs(tampered, source, asset, checkpoint)

    tampered = dict(manifest)
    tampered["sam2_checkpoint_sha256"] = "0" * 64
    with pytest.raises(PilotPreviewError, match="SAM2_CHECKPOINT_HASH_MISMATCH_FINAL"):
        _assert_final_inputs(tampered, source, asset, checkpoint)

    tampered = dict(manifest)
    tampered["input_identity_sha256"] = "0" * 64
    with pytest.raises(PilotPreviewError, match="INPUT_IDENTITY_MISMATCH"):
        _assert_final_inputs(tampered, source, asset, checkpoint)


def test_r2_final_inputs_reject_policy_and_composition_drift(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"s")
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"a")
    checkpoint = tmp_path / "sam2.pt"
    checkpoint.write_bytes(b"c")

    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = _manifest(asset_sha=OTHER_SHA, capabilities=_full_capabilities())
    manifest["source_sha256"] = _hash(source)
    manifest["asset_sha256"] = _hash(asset)
    manifest["sam2_checkpoint_sha256"] = _hash(checkpoint)
    manifest["pack_capabilities"] = _full_capabilities()
    manifest["input_identity_sha256"] = compute_input_identity_sha256(manifest)
    manifest["output_relpaths"] = build_output_relpaths(str(manifest["input_identity_sha256"]))

    no_preview = dict(manifest)
    no_preview["policy"] = {"preview_only": False, "single_shot": True, "no_full_apply": True, "no_s12": True}
    with pytest.raises(PilotPreviewError, match="INPUT_IDENTITY_MISMATCH"):
        _assert_final_inputs(no_preview, source, asset, checkpoint)

    bad_comp = dict(manifest)
    bad_comp["composition_revision"] = "stale-revision"
    with pytest.raises(PilotPreviewError, match="INPUT_IDENTITY_MISMATCH"):
        _assert_final_inputs(bad_comp, source, asset, checkpoint)

    v3_manifest = dict(manifest)
    v3_manifest["asset_sha256"] = V3_SHA
    with pytest.raises(PilotPreviewError, match="PACK_STATE_HASH_MISMATCH_FINAL"):
        _assert_final_inputs(v3_manifest, source, asset, checkpoint)


# ── isolation: no accidental live-DB / MAIN selection ────────────────────────


def test_r2_isolated_roots_reject_main_and_relative(tmp_path: Path) -> None:
    from app.config import PROTECTED_MAIN_ROOT

    main = str(PROTECTED_MAIN_ROOT)
    with pytest.raises(UnsafeRuntimeRootError):
        validate_runtime_roots(main, str(tmp_path / "managed"))
    with pytest.raises(UnsafeRuntimeRootError):
        validate_runtime_roots(str(tmp_path / "projects"), main)
    with pytest.raises(UnsafeRuntimeRootError):
        validate_runtime_roots("relative/root", str(tmp_path / "managed"))
    # Isolated absolute roots pass.
    validate_runtime_roots(str(tmp_path / "projects"), str(tmp_path / "managed"))


# ── worker consumes the transform/layer contract ─────────────────────────────


def test_r2_worker_schedule_and_layers_consumed_for_window() -> None:
    """Every frozen-window frame binds schedule state + a validated stack."""
    for source_frame in (450, 510, 521, 522, 545, 569):
        stack = layer_stack_for_frame(source_frame)
        check_layer_stack(stack)  # raises on inversion/dropped layers
        assert pose_state_at(source_frame) == "seated_holding_book_chest"
        assert mouth_state_at(source_frame, "character") == "closed"
        assert mouth_state_at(source_frame, "woman") == "closed"
    assert book_state_at(521) == "closed"
    assert book_state_at(522) == "open"
    with pytest.raises(PoseCompositionError):
        layer_stack_for_frame(0)
    with pytest.raises(PoseCompositionError):
        pose_state_at(0)


def test_r2_worker_calls_reconstruction_and_pixel_compositor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker path, not a helper-only test, consumes all three stages."""
    import cv2
    import json
    import shutil
    import numpy as np

    import app.workflow.pilot_preview_jobs as jobs
    from app.services.pilot_preview.asset_pack import resolve_versioned_pack

    pack_root, content_sha = _engineering_pack_for_api(
        tmp_path / "runtime" / "assets" / "pilot-packs",
        source_sha256=SOURCE_PINNED_SHA256,
    )
    pack = resolve_versioned_pack("engineering-pack-v1", pack_root)
    source_input = next(
        candidate for candidate in (Path.home() / "MotionForge2D-evidence").rglob("source_*.mp4")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() == SOURCE_PINNED_SHA256
    )
    source = tmp_path / "runtime" / "source.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_input, source)
    checkpoint = Path(__file__).resolve().parents[3] / "runtime" / "models" / "sam2.1_hiera_large.pt"
    assert checkpoint.is_file()
    closed = Path(pack["states"]["seated_book_closed"]["path"])
    plate_root = tmp_path / "runtime" / "assets" / "pilot-plates"
    plate_dir = plate_root / "reviewed-plate-v1"
    plate_dir.mkdir(parents=True)
    plate_path = plate_dir / "clean-plate.png"
    assert cv2.imwrite(str(plate_path), np.zeros((360, 640, 3), dtype=np.uint8))
    plate_manifest = {
        "plate_id": "reviewed-plate-v1", "version": "engineering-v1",
        "revision": "reviewed-clean-plate-v1", "camera_view": "three_quarter_front",
        "source_sha256": SOURCE_PINNED_SHA256, "source_window": [450, 570],
        "canvas_size": [640, 360], "image": "clean-plate.png",
        "image_sha256": hashlib.sha256(plate_path.read_bytes()).hexdigest(),
        "coverage": {"mode": "full_frame"},
        "approval": {"status": "APPROVED", "reviewer": "test", "reviewed_at": "2026-09-09T00:00:00Z"},
    }
    (plate_dir / "manifest.json").write_text(json.dumps(plate_manifest, sort_keys=True), encoding="utf-8")
    from app.services.pilot_preview.clean_plate_pack import resolve_reviewed_plate
    resolved_plate = resolve_reviewed_plate("reviewed-plate-v1", plate_root, source_sha256=plate_manifest["source_sha256"])
    manifest = {
        "schema_version": "pilot-preview-v1",
        "pipeline_revision": PILOT_PIPELINE_REVISION,
        "render_geometry_contract": dict(PILOT_RENDER_GEOMETRY),
        "composition_revision": COMPOSITION_REVISION,
        "project_id": "demo", "durable_project_id": None, "durable_video_item_id": None,
        "generation": "1", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "asset_sha256": content_sha, "asset_state_sha256": pack["states"]["seated_book_closed"]["sha256"],
        "sam2_checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "sam2_model_cfg": "configs/sam2.1/sam2.1_hiera_l.yaml", "sam2_device": "cpu",
        "start_frame": 450, "end_frame": 570, "role": "seated_character",
        "source_prompt": "replace seated character",
        "mask_correction": {"bbox_xywh_norm": [0.32, 0.26, 0.16, 0.6], "source_frame": 450, "confidence": 1.0},
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": [0.4, 0.55], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.4, 0.55], "scale": 1.0, "rotation_deg": 0.0},
        ],
        "occluder": {"layer_id": "foreground_right", "region_xywh_norm": [0.76, 0.34, 0.2, 0.66], "z": -1},
        "policy": {"preview_only": True, "single_shot": True, "max_frames": 150, "no_full_apply": True, "no_s12": True, "preserve_source_audio": True},
        "pack_id": "engineering-pack-v1", "pack_version": pack["version"],
        "pack_root": str(pack_root), "pack_manifest_path": pack["manifest_path"],
        "pack_manifest_sha256": pack["manifest_sha256"], "pack_content_sha256": content_sha,
        "pack_state_identity": {state_id: {"sha256": state["sha256"], "canvas_size": state["canvas_size"], "anchors": state["anchors"]} for state_id, state in pack["states"].items()},
            "pack_capabilities": pack["capabilities"],
            "clean_plate_id": resolved_plate["plate_id"], "clean_plate_root": str(plate_root),
            "clean_plate_manifest_sha256": resolved_plate["manifest_sha256"],
            "clean_plate_content_sha256": resolved_plate["content_sha256"],
            "clean_plate_image_sha256": resolved_plate["image_sha256"],
            "clean_plate_source_sha256": resolved_plate["source_sha256"],
            "clean_plate_source_window": resolved_plate["source_window"],
            "clean_plate_revision": resolved_plate["revision"], "anchor_mode": "source_derived",
        "project_root": str(tmp_path / "runtime"), "runtime_root": str(tmp_path / "runtime"),
        "managed_root": str(tmp_path / "managed"), "source_path": str(source), "asset_path": str(closed),
        "sam2_checkpoint_path": str(checkpoint),
        "scene_contract_hash": "scene-contract-test", "reconstruction_revision": "pilot-scene-reconstruction-r2",
        "clean_plate_identity": {"revision": "pilot-scene-reconstruction-r2", "algorithm": "test"},
        "protected_masks_identity": {"revision": "pilot-scene-reconstruction-r2", "roles": ["book", "woman"]},
        "effective_geometry": dict(PILOT_RENDER_GEOMETRY),
    }
    manifest["input_identity_sha256"] = compute_input_identity_sha256(manifest)
    manifest["output_relpaths"] = build_output_relpaths(manifest["input_identity_sha256"])

    events: list[str] = []
    original_schedule = jobs._build_composition_schedule
    original_compositor = jobs._composite_v3

    def tracked_schedule(current_manifest: dict[str, Any], current_pack: dict[str, Any]) -> list[dict[str, Any]]:
        events.append("schedule")
        return original_schedule(current_manifest, current_pack)

    def tracked_compositor(*args: Any, **kwargs: Any) -> Any:
        events.append("compositor")
        return original_compositor(*args, **kwargs)

    def fake_masks(frames: list[Any], _rect: tuple[float, float, float, float], _manifest: dict[str, Any]) -> list[Any]:
        events.append("sam2")
        return [np.zeros(frame.shape[:2], dtype=np.uint8) for frame in frames]

    monkeypatch.setattr(jobs, "_build_composition_schedule", tracked_schedule)
    monkeypatch.setattr(jobs, "_composite_v3", tracked_compositor)
    monkeypatch.setattr(jobs, "_sam2_masks", fake_masks)
    monkeypatch.setattr(jobs, "_write_video_only", lambda _frames, target, _ffmpeg: target.write_bytes(b"video"))
    monkeypatch.setattr(jobs, "_trim_before", lambda _source, target, _start, _count, _ffmpeg: target.write_bytes(b"before"))
    monkeypatch.setattr(jobs, "_remux", lambda _source, _video, target, _start, _count, _ffmpeg: target.write_bytes(b"after"))
    monkeypatch.setattr(jobs, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(jobs, "find_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(jobs, "_probe_media", lambda _path, _probe: {"width": 640, "height": 360, "video_codec": "h264", "pix_fmt": "yuv420p", "fps": (30, 1), "audio_present": False})
    monkeypatch.setattr(jobs, "_validate_video", lambda path, _count, _width, _height, _probe: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "frames": 120, "stream": {}})
    monkeypatch.setattr(jobs, "_has_audio", lambda _path, _probe: False)

    class Context:
        job_id = "worker-test"
        input_manifest = manifest

        def is_cancelled(self) -> bool: return False
        def progress(self, _value: float, _message: str) -> None: return None
        def staging_dir(self) -> Path:
            path = tmp_path / "runtime" / "staging"
            path.mkdir(exist_ok=True)
            return path
        def write_checkpoint(self, _payload: dict[str, Any]) -> None: return None

    result = jobs.pilot_preview_handler(Context())
    assert result["status"] == "completed"
    assert events == ["schedule", "sam2", "compositor"]


# ── H264/yuv420p encode path on synthetic frames ─────────────────────────────


def _synthetic_frames(count: int = 8, width: int = 64, height: int = 48) -> list[Any]:
    import numpy as np

    frames: list[Any] = []
    for index in range(count):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (40, 40, 40)
        frame[8:-8, 8 + index : 40 + index] = (0, 0, 200)
        frames.append(frame)
    return frames


def test_r2_encode_path_emits_h264_yuv420p(tmp_path: Path) -> None:
    from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe

    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    target = tmp_path / "synthetic.mp4"
    _write_video_only(_synthetic_frames(), target, ffmpeg)
    media = _probe_media(target, ffprobe)
    assert media["video_codec"] == "h264"
    assert media["pix_fmt"] == "yuv420p"
    qc = _validate_video(target, 8, 64, 48, ffprobe)
    assert qc["frames"] == 8


def test_r2_remux_preserves_audio_mapping_and_offsets(tmp_path: Path) -> None:
    from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe

    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    # Synthetic source with a real AAC track (sine tone) at 30fps.
    silent = tmp_path / "video-only.mp4"
    _write_video_only(_synthetic_frames(count=30), silent, ffmpeg)
    tone = tmp_path / "tone.wav"
    import subprocess

    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", "-y", str(tone)],
        check=True,
    )
    source = tmp_path / "source.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(silent),
         "-i", str(tone), "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", "-y", str(source)],
        check=True,
    )
    after = tmp_path / "after.mp4"
    _remux(source, silent, after, 0, 30, ffmpeg)
    media = _probe_media(after, ffprobe)
    assert media["video_codec"] == "h264"
    assert media["pix_fmt"] == "yuv420p"
    assert media["audio_present"] is True
    assert media["audio_codec"] == "aac"
    offset = media.get("audio_start_offset_seconds")
    assert offset is None or abs(float(offset)) <= (1 / 30)
    qc = _validate_video(after, 30, 64, 48, ffprobe)
    assert qc["frames"] == 30


# ── real API negatives/ownership/preview-only authority ──────────────────────


def _tiny_mp4(path: Path, frames: int = 900, width: int = 640, height: int = 360) -> None:
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (width, height))
    assert writer.isOpened()
    for index in range(frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (60, 60, 60)
        frame[10:-10, 10 + (index % 40) : 60 + (index % 40)] = (200, 0, 0)
        writer.write(frame)
    writer.release()


def _engineering_pack_for_api(
    root: Path,
    pack_id: str = "engineering-pack-v1",
    source_sha256: str = "a" * 64,
) -> tuple[Path, str]:
    """Create a non-artwork RGBA resolver fixture under the isolated root."""
    import cv2
    import json
    import numpy as np
    from app.services.pilot_preview.asset_pack import _content_sha256

    pack_dir = root / pack_id
    pack_dir.mkdir(parents=True)
    anchors = {
        "head": [40.0, 28.0], "seat_pelvis": [40.0, 166.0],
        # Inverse of the real 640x360 affine fit for the source contacts;
        # keep the worker fixture honest about the local transform inputs.
        # Inverse of the source-book-boundary fit for the engineering canvas;
        # these are real transform inputs, not declared zero residuals.
        "hand_grip_l": [27.36995537927615, 116.51978185423894],
        "hand_grip_r": [48.82597917699554, 117.14923153197816],
        "book_corners": [[24.0, 76.0], [56.0, 76.0], [56.0, 112.0], [24.0, 112.0]],
    }
    states = {}
    for state_id, colour, book in (("seated_book_closed", (190, 90, 40), "closed"), ("seated_book_open", (170, 110, 55), "open")):
        image = np.zeros((200, 80, 4), dtype=np.uint8)
        image[20:180, 15:65, :3] = colour
        image[20:180, 15:65, 3] = 255
        path = pack_dir / f"{state_id}.png"
        assert cv2.imwrite(str(path), image)
        state_anchors = {**anchors}
        if state_id == "seated_book_open":
            # Independent open-state fit for the source book's real
            # 522..569 hand contacts.
            state_anchors["hand_grip_l"] = [25.207932573128407, 118.21655924640552]
            state_anchors["hand_grip_r"] = [53.76579077838373, 116.76608824987602]
        states[state_id] = {
            "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size, "canvas_size": [80, 200],
            "anchors": state_anchors, "pose": "seated_holding_book_chest", "mouth": "closed", "book": book, "book_owner": "source",
            "contact_semantics": {"kind": "replacement_hand_to_source_book_boundary", "book_owner": "source", "source_role": "book"},
            "hand_contact_patches": {
                "left": {"contact_local": state_anchors["hand_grip_l"], "bbox_xywh": [12, 105, 18, 25]},
                "right": {"contact_local": state_anchors["hand_grip_r"], "bbox_xywh": [50, 105, 18, 25]},
            },
        }
    content_sha = _content_sha256(pack_id, "engineering-v1", "three_quarter_front_this_window", states)
    measurements = {}
    for frame in (450, 510, 521, 522, 523, 569):
        active = "seated_book_closed" if frame < 522 else "seated_book_open"
        inactive = "seated_book_open" if frame < 522 else "seated_book_closed"
        measurements[str(frame)] = {
            active: {
                contact: 0.0
                for contact in ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r", "book_corners")
            },
            inactive: {"not_applicable": True},
        }
    payload = {
        "pack_id": pack_id,
        "version": "engineering-v1",
        "camera_view": "three_quarter_front_this_window",
        "content_sha256": content_sha,
        "approval": {"status": "APPROVED", "approved_by": "engineering-test-fixture", "approved_at": "2026-09-09T00:00:00Z"},
        "compatibility_review": {
            "status": "APPROVED",
            "reviewer": "engineering-test-fixture",
            "reviewed_at": "2026-09-09T00:00:00Z",
            "camera_view": "three_quarter_front_this_window",
            "anchor_head_role": "replacement_character",
            "anchor_seat_pelvis_role": "replacement_character",
            "seat_reference": "occupied_chair_seat",
            "pose_compatible": True,
            "book_contact_compatible": True,
            "book_owner": "source",
            "semantic_contract_revision": "c6-source-prop-contact-v2",
            "measurement_policy_revision": "source-prop-boundary-contact-v2",
            "source_contact_annotation_digest": "a" * 64,
            "source_frame_samples": [450, 510, 521, 522, 523, 569],
            "source_sha256": source_sha256,
            "artwork_sha256": {state_id: state["sha256"] for state_id, state in states.items()},
            "contact_measurements": measurements,
        },
        "states": states,
    }
    (pack_dir / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return root, content_sha


def _c8_real_compositor_inputs(tmp_path: Path) -> tuple[Any, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], Any, Path]:
    """Use the consumed C8 body/hand pack through the real compositor boundary."""
    import copy
    import json
    import shutil
    import numpy as np

    import app.workflow.pilot_preview_jobs as jobs
    from app.services.pilot_preview import scene_reconstruction as sr
    from app.services.pilot_preview.asset_pack import resolve_versioned_pack
    from app.services.pilot_preview.clean_plate_pack import load_reviewed_plate, resolve_reviewed_plate

    fixture_root = os.environ.get("MOTIONFORGE_PILOT_FIXTURE_ROOT")
    if not fixture_root:
        pytest.skip("MOTIONFORGE_PILOT_FIXTURE_ROOT is required for the real-compositor fixture")
    c8_root = Path(fixture_root).resolve()
    assert c8_root.is_dir(), "C8 pack evidence root is required for the actual compositor fixture"
    source = tmp_path / "runtime" / "source.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(c8_root / "runtime" / "projects" / "8e660a635dfa" / "source.mp4", source)
    pack_root = tmp_path / "runtime" / "assets" / "pilot-packs"
    shutil.copytree(c8_root / "assets" / "pilot-packs" / "luna-reader-seated-c7-v1", pack_root / "luna-reader-seated-c7-v1")
    plate_root = tmp_path / "runtime" / "assets" / "pilot-plates"
    shutil.copytree(c8_root / "runtime" / "assets" / "pilot-plates" / "luna-clean-plate-preview-c7-v1", plate_root / "luna-clean-plate-preview-c7-v1")
    pack = resolve_versioned_pack("luna-reader-seated-c7-v1", pack_root, expected_source_sha256=SOURCE_PINNED_SHA256, allow_private_preview=True)
    plate = resolve_reviewed_plate("luna-clean-plate-preview-c7-v1", plate_root, source_sha256=SOURCE_PINNED_SHA256, allow_private_preview=True)
    plate_image = load_reviewed_plate(plate)
    frame = jobs._read_frames(source, 522, 523)[0]
    previous = jobs._read_frames(source, 521, 522)[0]
    recon = sr.reconstruct_frame(
        frame,
        source_frame=522,
        source_sha256=SOURCE_PINNED_SHA256,
        source_prompt_bbox_xywh_px=(203, 92, 129, 175),
        corrections=(sr.MaskCorrection((203, 92, 129, 175), "include", note="C8 actual compositor fixture"),),
        propagated_removal_mask=np.zeros(frame.shape[:2], dtype=np.uint8),
        neighbour_frames={521: previous, 522: frame},
        reviewed_plate=plate_image,
        reviewed_plate_identity=plate,
    )
    schedule = jobs._build_composition_schedule({"start_frame": 450, "end_frame": 570, "source_sha256": SOURCE_PINNED_SHA256}, pack)
    rows = copy.deepcopy(schedule[72:73])
    recons = [{
        "result": recon,
        "protected_masks": recon.protected_masks,
        "layer_order": list(recon.layer_order),
        "reconstructed_foreground_mask": recon.reconstructed_foreground_mask,
        "reconstructed_foreground_reference": recon.reconstructed_foreground_reference,
        "reconstructed_foreground_provenance": recon.reconstructed_foreground_provenance,
    }]
    return frame, pack, rows, recons, source, Path(pack["states"]["seated_book_open"]["path"])


def test_c8_final_rgb_rejects_missing_hand_blit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real body/hand compositor fault cannot pass the final pixel gate."""
    from app.services.renderer_routes import composite
    import app.workflow.pilot_preview_jobs as jobs

    frame, pack, rows, recons, source, asset = _c8_real_compositor_inputs(tmp_path)
    real = composite._alpha_composite_into

    def drop(*args: Any, **kwargs: Any) -> None:
        if inspect.currentframe().f_back.f_code.co_name == "_composite_v3":
            return
        real(*args, **kwargs)

    monkeypatch.setattr(composite, "_alpha_composite_into", drop)
    monkeypatch.setattr(jobs, "_write_video_only", lambda *args: None)
    with pytest.raises(PilotPreviewError, match="HAND_(FINAL_PIXEL|BOOK_NOT_VISIBLE)"):
        jobs._composite_v3(
            [frame.copy()], source=source, asset=asset, rect=(.32, .26, .16, .60),
            keyframes=[{"frame": 522, "anchor_xy_norm": [.4, .55], "scale": 1.0, "rotation_deg": 0.0}],
            occluder={"layer_id": "none"}, output=tmp_path / "fault.mp4", runtime_root=tmp_path,
            start_frame=522, ffmpeg="ffmpeg", ctx=type("C", (), {"progress": lambda *_: None})(),
            pack=pack, schedule_rows=rows, reconstructions=recons, anchor_mode="source_derived",
        )


def test_c8_final_rgb_rejects_hand_erased_after_occlusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Erasing a hand after its draw is also detected from final pixels."""
    from app.services.renderer_routes import composite
    import app.workflow.pilot_preview_jobs as jobs

    frame, pack, rows, recons, source, asset = _c8_real_compositor_inputs(tmp_path)
    real = composite._alpha_composite_into
    calls = 0

    def erase_after_draw(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        real(*args, **kwargs)
        if inspect.currentframe().f_back.f_code.co_name == "_composite_v3":
            calls += 1
            if calls == 2:
                base, layer = args[0], args[1]
                base[layer[:, :, 3] > 32] = 0

    monkeypatch.setattr(composite, "_alpha_composite_into", erase_after_draw)
    monkeypatch.setattr(jobs, "_write_video_only", lambda *args: None)
    with pytest.raises(PilotPreviewError, match="HAND_FINAL_PIXEL"):
        jobs._composite_v3(
            [frame.copy()], source=source, asset=asset, rect=(.32, .26, .16, .60),
            keyframes=[{"frame": 522, "anchor_xy_norm": [.4, .55], "scale": 1.0, "rotation_deg": 0.0}],
            occluder={"layer_id": "none"}, output=tmp_path / "erase.mp4", runtime_root=tmp_path,
            start_frame=522, ffmpeg="ffmpeg", ctx=type("C", (), {"progress": lambda *_: None})(),
            pack=pack, schedule_rows=rows, reconstructions=recons, anchor_mode="source_derived",
        )


C11CompositorInputs = tuple[
    Any,
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    Path,
    Path,
    Path,
]


def _c11_real_compositor_inputs(
    tmp_path: Path, *, source_frame: int = 522,
) -> C11CompositorInputs:
    """Copy C11's exact pack/plate/source into an isolated pytest runtime."""
    import copy
    import shutil

    import numpy as np

    from app.services.pilot_preview import scene_reconstruction as sr
    from app.services.pilot_preview.asset_pack import resolve_versioned_pack
    from app.services.pilot_preview.clean_plate_pack import (
        load_reviewed_plate,
        resolve_reviewed_plate,
    )

    fixture_root = os.environ.get("MOTIONFORGE_C11_FIXTURE_ROOT")
    if not fixture_root:
        pytest.skip("MOTIONFORGE_C11_FIXTURE_ROOT is required for the C11 real-compositor fixture")
    c11_root = Path(fixture_root).resolve()
    source_fixture = (
        c11_root
        / "projects"
        / "projects"
        / "4091af4c7374"
        / "source_42052c37861342d082d40404d3187698.mp4"
    )
    pack_fixture = c11_root / "assets" / "pilot-packs" / "luna-reader-seated-c7-v1"
    plate_fixture = c11_root / "assets" / "pilot-plates" / "luna-clean-plate-preview-c7-v1"
    assert source_fixture.is_file() and pack_fixture.is_dir() and plate_fixture.is_dir()

    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    source = runtime / "source.mp4"
    shutil.copyfile(source_fixture, source)
    pack_root = runtime / "assets" / "pilot-packs"
    pack_root.mkdir(parents=True)
    shutil.copytree(pack_fixture, pack_root / pack_fixture.name)
    plate_root = runtime / "assets" / "pilot-plates"
    plate_root.mkdir(parents=True)
    shutil.copytree(plate_fixture, plate_root / plate_fixture.name)

    pack = resolve_versioned_pack(
        "luna-reader-seated-c7-v1", pack_root,
        expected_source_sha256=SOURCE_PINNED_SHA256, allow_private_preview=True,
    )
    plate = resolve_reviewed_plate(
        "luna-clean-plate-preview-c7-v1", plate_root,
        source_sha256=SOURCE_PINNED_SHA256, allow_private_preview=True,
    )
    plate_image = load_reviewed_plate(plate)
    frame = jobs._read_frames(source, source_frame, source_frame + 1)[0]
    previous = jobs._read_frames(source, source_frame - 1, source_frame)[0]
    recon = sr.reconstruct_frame(
        frame,
        source_frame=source_frame,
        source_sha256=SOURCE_PINNED_SHA256,
        source_prompt_bbox_xywh_px=(203, 92, 129, 175),
        corrections=(
            sr.MaskCorrection(
                (203, 92, 129, 175),
                "include",
                note="C11 real-compositor correction test",
            ),
        ),
        propagated_removal_mask=np.zeros(frame.shape[:2], dtype=np.uint8),
        neighbour_frames={source_frame - 1: previous, source_frame: frame},
        reviewed_plate=plate_image,
        reviewed_plate_identity=plate,
    )
    schedule = jobs._build_composition_schedule(
        {"start_frame": 450, "end_frame": 570, "source_sha256": SOURCE_PINNED_SHA256}, pack,
    )
    rows = copy.deepcopy(schedule[source_frame - 450:source_frame - 449])
    recons = [{
        "result": recon,
        "protected_masks": recon.protected_masks,
        "layer_order": list(recon.layer_order),
        "reconstructed_foreground_mask": recon.reconstructed_foreground_mask,
        "reconstructed_foreground_reference": recon.reconstructed_foreground_reference,
        "reconstructed_foreground_provenance": recon.reconstructed_foreground_provenance,
    }]
    return (
        frame,
        pack,
        rows,
        recons,
        source,
        Path(pack["states"]["seated_book_open"]["path"]),
        runtime,
    )


def test_c11_real_compositor_rejects_source_book_corruption_before_encoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production compositor gate catches exact source-book mutations."""
    import numpy as np

    encoder_calls: list[str] = []

    def encoder_stub(_frames: Any, output: Path, _ffmpeg: str) -> None:
        encoder_calls.append(str(output))

    monkeypatch.setattr(jobs, "_write_video_only", encoder_stub)

    def render_case(
        values: C11CompositorInputs,
        output_name: str,
        *,
        source_frame: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        frame, pack, rows, recons, source, asset, runtime = values
        output = runtime / output_name
        _composed, _meta = jobs._composite_v3(
            [frame.copy()], source=source, asset=asset, rect=(.32, .26, .16, .60),
            keyframes=[{
                "frame": source_frame,
                "anchor_xy_norm": [.4, .55],
                "scale": 1.0,
                "rotation_deg": 0.0,
            }],
            occluder={"layer_id": "none"}, output=output, runtime_root=runtime,
            start_frame=source_frame,
            ffmpeg="ffmpeg",
            ctx=type("C", (), {"progress": lambda *_: None})(),
            pack=pack, schedule_rows=rows, reconstructions=recons, anchor_mode="source_derived",
        )
        return rows, recons

    control_frame = 546
    control = _c11_real_compositor_inputs(tmp_path / "control", source_frame=control_frame)
    control_rows, _ = render_case(control, "control.mp4", source_frame=control_frame)
    assert control_rows[0]["final_pixel_gate"]["status"] == "passed"
    assert len(encoder_calls) == 1, (
        "untouched real-compositor control must reach the encoder stub"
    )

    real_validator = jobs._validate_final_hand_pixels
    mutation_specs = (
        ("gray_exact_1629", 1629),
        ("green", 32),
        ("texture", 32),
        ("limited_erasure", 32),
    )
    corruption_records: list[dict[str, Any]] = []
    for mutation_kind, requested_count in mutation_specs:
        values = _c11_real_compositor_inputs(tmp_path / mutation_kind, source_frame=control_frame)
        frame, pack, rows, recons, source, asset, runtime = values
        record: dict[str, Any] = {"mutation": mutation_kind, "source_frame": control_frame}

        def corrupt_source_book_then_validate(
            *args: Any,
            _mutation_kind: str = mutation_kind,
            _requested_count: int = requested_count,
            _record: dict[str, Any] = record,
            **kwargs: Any,
        ) -> dict[str, Any]:
            mutation_kind = _mutation_kind
            requested_count = _requested_count
            record = _record
            final_frame = kwargs["final_frame"]
            original = final_frame.copy()
            book_mask = np.asarray(kwargs["book_mask"]) > 0
            book_reference = np.asarray(kwargs["book_reference"])
            expected = np.asarray(kwargs["before_hands"]).copy()
            expected_hand_union = np.zeros(book_mask.shape, dtype=bool)
            for side in ("left", "right"):
                next_expected = jobs._reference_alpha_composite(
                    expected, kwargs["hand_layers"][side]
                )
                expected_hand_union |= np.any(
                    next_expected != expected,
                    axis=2,
                )
                expected = next_expected
            eligible = book_mask & np.any(book_reference != 0, axis=2) & ~expected_hand_union
            record["available_unoccluded_book_pixels"] = int(np.count_nonzero(eligible))
            if mutation_kind == "gray_exact_1629":
                replacement = np.asarray((180, 180, 180), dtype=final_frame.dtype)
                candidates = eligible & np.any(final_frame != replacement, axis=2)
                ys, xs = np.where(candidates)
                assert len(xs) >= requested_count, (
                    "exact 1,629 source-owned pixels unavailable outside "
                    f"expected hand occlusion: {len(xs)}"
                )
                ys, xs = ys[:requested_count], xs[:requested_count]
                final_frame[ys, xs] = replacement
            else:
                ys, xs = np.where(eligible)
                assert len(xs) >= requested_count, (
                    "real source-owned book lacks pixels for corruption control"
                )
                ys, xs = ys[:requested_count], xs[:requested_count]
                if mutation_kind == "green":
                    replacement = np.asarray((20, 120, 30), dtype=final_frame.dtype)
                    keep = np.any(final_frame[ys, xs] != replacement, axis=1)
                    ys = ys[keep][:requested_count]
                    xs = xs[keep][:requested_count]
                    assert len(xs) == requested_count, (
                        "green corruption needs distinct source pixels"
                    )
                    final_frame[ys, xs] = replacement
                elif mutation_kind == "texture":
                    final_frame[ys, xs] = (
                        final_frame[ys, xs].astype(np.uint16)
                        + np.asarray((13, 29, 47), dtype=np.uint16)
                    ).astype(final_frame.dtype)
                else:
                    replacement = np.asarray((0, 0, 0), dtype=final_frame.dtype)
                    keep = np.any(final_frame[ys, xs] != replacement, axis=1)
                    ys = ys[keep][:requested_count]
                    xs = xs[keep][:requested_count]
                    assert len(xs) == requested_count, (
                        "limited-erasure corruption needs nonblack source pixels"
                    )
                    final_frame[ys, xs] = replacement
            actual_changed = eligible & np.any(final_frame != original, axis=2)
            record["mutated_source_owned_pixels"] = int(np.count_nonzero(actual_changed))
            record["outside_expected_hand_occlusion"] = True
            assert record["mutated_source_owned_pixels"] == requested_count
            try:
                return real_validator(*args, **kwargs)
            except PilotPreviewError as error:
                record["typed_gate_error"] = str(error)
                raise

        monkeypatch.setattr(jobs, "_validate_final_hand_pixels", corrupt_source_book_then_validate)
        if mutation_kind == "gray_exact_1629":
            expected_error = r"^HAND_BOOK_(?:CONTENT_MISMATCH(?::\d+)?|NOT_VISIBLE)$"
        else:
            expected_error = r"^HAND_BOOK_CONTENT_MISMATCH:\d+$"
        with pytest.raises(PilotPreviewError, match=expected_error):
            render_case(values, f"{mutation_kind}.mp4", source_frame=control_frame)
        assert len(encoder_calls) == 1, (
            f"{mutation_kind} corruption must fail before the encoder stub"
        )
        corruption_records.append(record)
        print(
            "C11_BOOK_CORRUPTION "
            + json.dumps(
                {**record, "encoder_stub_calls": len(encoder_calls)},
                sort_keys=True,
            )
        )
        monkeypatch.setattr(jobs, "_validate_final_hand_pixels", real_validator)

    assert [record["mutated_source_owned_pixels"] for record in corruption_records] == [
        1629,
        32,
        32,
        32,
    ]
    assert corruption_records[0]["outside_expected_hand_occlusion"] is True


@pytest.mark.parametrize(
    ("fault", "expected_error"),
    (
        ("drop_left", r"^HAND_FINAL_PIXEL_CONTRIBUTION_MISSING:left$"),
        ("drop_right", r"^HAND_FINAL_PIXEL_CONTRIBUTION_MISSING:right$"),
        ("late_erase", r"^HAND_FINAL_PIXEL_(?:CONTRIBUTION_MISSING|MISMATCH):left$"),
    ),
)
def test_c11_real_compositor_hand_faults_reject_before_encoder(
    fault: str, expected_error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C11's exact pack drives real dropped-hand and late-erasure negatives."""
    from app.services.renderer_routes import composite

    encoder_calls: list[str] = []
    monkeypatch.setattr(
        jobs,
        "_write_video_only",
        lambda _frames, output, _ffmpeg: encoder_calls.append(str(output)),
    )

    def render(values: C11CompositorInputs, name: str) -> tuple[list[Any], dict[str, Any]]:
        frame, pack, rows, recons, source, asset, runtime = values
        return jobs._composite_v3(
            [frame.copy()], source=source, asset=asset, rect=(.32, .26, .16, .60),
            keyframes=[{
                "frame": 522,
                "anchor_xy_norm": [.4, .55],
                "scale": 1.0,
                "rotation_deg": 0.0,
            }],
            occluder={"layer_id": "none"}, output=runtime / name, runtime_root=runtime,
            start_frame=522,
            ffmpeg="ffmpeg",
            ctx=type("C", (), {"progress": lambda *_: None})(),
            pack=pack, schedule_rows=rows, reconstructions=recons, anchor_mode="source_derived",
        )

    control = _c11_real_compositor_inputs(tmp_path / "control", source_frame=522)
    _control_frames, _control_meta = render(control, "control.mp4")
    assert control[2][0]["final_pixel_gate"]["status"] == "passed"
    assert len(encoder_calls) == 1, (
        "valid C11 real-compositor control must reach the encoder stub"
    )

    values = _c11_real_compositor_inputs(tmp_path / "fault", source_frame=522)
    real_composite = composite._alpha_composite_into
    hand_blits = 0
    saved_alpha: dict[str, Any] = {}

    def inject_real_compositor_fault(base: Any, layer: Any, x0: int, y0: int) -> None:
        nonlocal hand_blits
        caller = inspect.currentframe().f_back.f_code.co_name
        if caller != "_composite_v3":
            real_composite(base, layer, x0, y0)
            return
        hand_blits += 1
        if hand_blits == 1:
            saved_alpha["left"] = layer[:, :, 3].copy()
            if fault == "drop_left":
                return
        elif hand_blits == 2:
            saved_alpha["right"] = layer[:, :, 3].copy()
            if fault == "drop_right":
                return
        real_composite(base, layer, x0, y0)
        if fault == "late_erase" and hand_blits == 2:
            erase = (saved_alpha["left"] > 32) | (saved_alpha["right"] > 32)
            base[erase] = 0

    monkeypatch.setattr(composite, "_alpha_composite_into", inject_real_compositor_fault)
    with pytest.raises(PilotPreviewError, match=expected_error) as exc_info:
        render(values, f"{fault}.mp4")
    assert hand_blits == 2, "the injected fault must cover the two actual hand blits"
    assert len(encoder_calls) == 1, f"{fault} must fail before the encoder stub"
    print(
        "C11_COMPOSITOR_FAULT "
        + json.dumps(
            {
                "fault": fault,
                "typed_gate_error": str(exc_info.value),
                "real_hand_blits": hand_blits,
                "encoder_stub_calls": len(encoder_calls),
                "valid_control_reached_encoder": True,
            },
            sort_keys=True,
        )
    )


@pytest.mark.parametrize(
    ("fault", "expected_error"),
    (
        ("body_gap", r"^HAND_BODY_WRIST_DISCONNECTED:522:(?:left|right)$"),
        ("body_absent", r"^HAND_BODY_NOT_VISIBLE:522:(?:left|right)$"),
    ),
)
def test_c11_real_compositor_body_faults_reject_before_encoder(
    fault: str, expected_error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Body-specific faults use the current source/pack through _composite_v3."""
    import cv2
    import numpy as np

    from app.services.renderer_routes import composite

    encoder_calls: list[str] = []
    monkeypatch.setattr(
        jobs,
        "_write_video_only",
        lambda _frames, output, _ffmpeg: encoder_calls.append(str(output)),
    )

    def render(values: C11CompositorInputs, name: str) -> None:
        frame, pack, rows, recons, source, asset, runtime = values
        jobs._composite_v3(
            [frame.copy()], source=source, asset=asset, rect=(.32, .26, .16, .60),
            keyframes=[{
                "frame": 522,
                "anchor_xy_norm": [.4, .55],
                "scale": 1.0,
                "rotation_deg": 0.0,
            }],
            occluder={"layer_id": "none"}, output=runtime / name, runtime_root=runtime,
            start_frame=522, ffmpeg="ffmpeg",
            ctx=type("C", (), {"progress": lambda *_: None})(),
            pack=pack, schedule_rows=rows, reconstructions=recons,
            anchor_mode="source_derived",
        )

    control = _c11_real_compositor_inputs(tmp_path / "control", source_frame=522)
    render(control, "control.mp4")
    assert control[2][0]["final_pixel_gate"]["status"] == "passed"
    assert len(encoder_calls) == 1, "valid body control must reach the encoder stub"

    values = _c11_real_compositor_inputs(tmp_path / "fault", source_frame=522)
    real_warp = composite._warp_layer
    compositor_warp_calls = 0
    hand_layers: list[Any] = []
    body_injected = False

    def inject_body_fault(*args: Any, **kwargs: Any) -> Any:
        nonlocal body_injected, compositor_warp_calls
        result = real_warp(*args, **kwargs)
        caller = inspect.currentframe().f_back.f_code.co_name
        if caller == "_composite_v3":
            compositor_warp_calls += 1
            if compositor_warp_calls <= 2:
                hand_layers.append(result.copy())
            elif compositor_warp_calls == 3:
                body_injected = True
                body = result.copy()
                if fault == "body_absent":
                    body[:, :, 3] = 0
                else:
                    hand_union = np.logical_or(
                        hand_layers[0][:, :, 3] > 32,
                        hand_layers[1][:, :, 3] > 32,
                    ).astype(np.uint8)
                    hand_zone = cv2.dilate(
                        hand_union, np.ones((21, 21), dtype=np.uint8), iterations=1,
                    ).astype(bool)
                    body_visible = body[:, :, 3] > 32
                    retained = body_visible & ~hand_zone
                    if not np.any(retained):
                        candidates = body_visible & ~hand_union.astype(bool)
                        retained = np.zeros(body_visible.shape, dtype=bool)
                        if np.any(candidates):
                            distances = cv2.distanceTransform(
                                candidates.astype(np.uint8), cv2.DIST_L2, 3,
                            )
                            y, x = np.unravel_index(int(np.argmax(distances)), distances.shape)
                            retained[y, x] = True
                    body[:, :, 3] = np.where(retained, body[:, :, 3], 0).astype(np.uint8)
                return body
        return result

    monkeypatch.setattr(composite, "_warp_layer", inject_body_fault)
    with pytest.raises(PilotPreviewError, match=expected_error) as exc_info:
        render(values, f"{fault}.mp4")
    assert compositor_warp_calls == 3, "body fault must reach both hand warps and the body warp"
    assert body_injected is True
    assert len(encoder_calls) == 1, f"{fault} must fail before the encoder stub"
    print(
        "C11_BODY_COMPOSITOR_FAULT "
        + json.dumps(
            {
                "fault": fault,
                "typed_gate_error": str(exc_info.value),
                "real_compositor_warp_calls": compositor_warp_calls,
                "encoder_stub_calls": len(encoder_calls),
                "valid_control_reached_encoder": True,
            },
            sort_keys=True,
        )
    )


@pytest.mark.parametrize(
    ("fault", "expected_error"),
    (
        ("opaque_green", r"^HAND_GREEN_SUPPORT_VISIBLE:522:left$"),
        ("identity_swap", r"^HAND_BOOK_TARGET_MISMATCH:522:hand_grip_l$"),
    ),
)
def test_c11_real_compositor_semantic_faults_reject_before_encoder(
    fault: str, expected_error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic X06 faults are injected at the real compositor layer boundary."""
    import copy
    import numpy as np

    from app.services.renderer_routes import composite

    encoder_calls: list[str] = []
    monkeypatch.setattr(
        jobs,
        "_write_video_only",
        lambda _frames, output, _ffmpeg: encoder_calls.append(str(output)),
    )

    def render(values: C11CompositorInputs, name: str) -> None:
        frame, pack, rows, recons, source, asset, runtime = values
        jobs._composite_v3(
            [frame.copy()], source=source, asset=asset, rect=(.32, .26, .16, .60),
            keyframes=[{
                "frame": 522,
                "anchor_xy_norm": [.4, .55],
                "scale": 1.0,
                "rotation_deg": 0.0,
            }],
            occluder={"layer_id": "none"}, output=runtime / name, runtime_root=runtime,
            start_frame=522, ffmpeg="ffmpeg",
            ctx=type("C", (), {"progress": lambda *_: None})(),
            pack=pack, schedule_rows=rows, reconstructions=recons,
            anchor_mode="source_derived",
        )

    control = _c11_real_compositor_inputs(tmp_path / "control", source_frame=522)
    render(control, "control.mp4")
    assert control[2][0]["final_pixel_gate"]["status"] == "passed"
    assert len(encoder_calls) == 1, "valid semantic control must reach the encoder stub"

    values = _c11_real_compositor_inputs(tmp_path / "fault", source_frame=522)
    if fault == "identity_swap":
        frame, pack, rows, recons, source, asset, runtime = values
        pack = copy.deepcopy(pack)
        state_id = str(values[2][0]["pack_state"])
        patches = pack["states"][state_id]["hand_contact_patches"]
        patches["left"]["polygon"], patches["right"]["polygon"] = (
            patches["right"]["polygon"], patches["left"]["polygon"],
        )

        real_semantic = jobs._semantic_hand_alpha
        semantic_calls: list[str] = []

        def swap_hand_identity(layer: Any, *, side: str, state_id: str) -> Any:
            semantic_calls.append(side)
            opposite = "right" if side == "left" else "left"
            return real_semantic(layer, side=opposite, state_id=state_id)

        monkeypatch.setattr(jobs, "_semantic_hand_alpha", swap_hand_identity)
        values = (frame, pack, rows, recons, source, asset, runtime)
    else:
        real_alpha = composite._alpha_composite_into
        hand_blits = 0
        green_injected = False

        def inject_opaque_green(base: Any, layer: Any, x0: int, y0: int) -> None:
            nonlocal green_injected, hand_blits
            caller = inspect.currentframe().f_back.f_code.co_name
            if caller == "_composite_v3":
                hand_blits += 1
                if hand_blits == 1:
                    alpha_pixels = layer[:, :, 3] >= 240
                    if not np.any(alpha_pixels):
                        alpha_pixels = layer[:, :, 3] > 32
                    ys, xs = np.where(alpha_pixels)
                    assert len(xs), "real hand layer must have an opaque semantic pixel"
                    y, x = int(ys[0]), int(xs[0])
                    layer[y, x] = np.asarray((20, 120, 30, 255), dtype=layer.dtype)
                    green_injected = True
            real_alpha(base, layer, x0, y0)

        monkeypatch.setattr(composite, "_alpha_composite_into", inject_opaque_green)

    with pytest.raises(PilotPreviewError, match=expected_error) as exc_info:
        render(values, f"{fault}.mp4")
    if fault == "identity_swap":
        assert semantic_calls == ["left", "right"]
    else:
        assert hand_blits == 2, "opaque-green injection must cover both real hand blits"
        assert green_injected is True
    assert len(encoder_calls) == 1, f"{fault} must fail before the encoder stub"
    print(
        "C11_SEMANTIC_COMPOSITOR_FAULT "
        + json.dumps(
            {
                "fault": fault,
                "typed_gate_error": str(exc_info.value),
                "injection_boundary": "real_compositor_hand_layer",
                "encoder_stub_calls": len(encoder_calls),
                "valid_control_reached_encoder": True,
            },
            sort_keys=True,
        )
    )


def _c9_contact_fixture(*, body_dx: int = 1, book_dx: int = 1, body_visible: bool = True) -> tuple[Any, Any, Any, Any, Any, dict[str, Any]]:
    import numpy as np
    import app.workflow.pilot_preview_jobs as jobs

    before = np.zeros((40, 40, 3), dtype=np.uint8)
    left = np.zeros((40, 40, 4), dtype=np.uint8)
    right = np.zeros((40, 40, 4), dtype=np.uint8)
    left[10, 10] = (30, 80, 180, 255)
    right[30, 30] = (30, 80, 180, 255)
    book = np.zeros((40, 40), dtype=np.uint8); book[10, 10 + book_dx] = 255; book[30, 30 + book_dx] = 255
    before[10, 10 + book_dx] = (90, 70, 40)
    before[30, 30 + book_dx] = (90, 70, 40)
    body = np.zeros((40, 40, 4), dtype=np.uint8); body[10, 10 - body_dx] = (20, 120, 30, 255); body[30, 30 - body_dx] = (20, 120, 30, 255)
    if body_visible:
        before[10, 10 - body_dx] = (20, 120, 30)
        before[30, 30 - body_dx] = (20, 120, 30)
    final = jobs._reference_alpha_composite(before, left)
    final = jobs._reference_alpha_composite(final, right)
    row = {"source_frame": 522, "contact_measurements": {"hand_grip_l": {"transformed_output_px": [10, 10]}, "hand_grip_r": {"transformed_output_px": [30, 30]}}}
    return before, left, right, body, book, row


def test_c9_contact_rejects_body_gap_independently() -> None:
    before, left, right, body, book, row = _c9_contact_fixture(body_dx=3)
    with pytest.raises(PilotPreviewError, match="HAND_BODY_WRIST_DISCONNECTED"):
        jobs._validate_final_hand_pixels(before_hands=before, final_frame=jobs._reference_alpha_composite(jobs._reference_alpha_composite(before, left), right), hand_layers={"left": left, "right": right}, body_layer=body, book_mask=book, book_reference=before, row=row)


def test_c9_contact_rejects_book_gap_independently() -> None:
    before, left, right, body, book, row = _c9_contact_fixture(book_dx=6)
    with pytest.raises(PilotPreviewError, match="HAND_BOOK_BOUNDARY_DISCONNECTED"):
        jobs._validate_final_hand_pixels(before_hands=before, final_frame=jobs._reference_alpha_composite(jobs._reference_alpha_composite(before, left), right), hand_layers={"left": left, "right": right}, body_layer=body, book_mask=book, book_reference=before, row=row)


def test_c9_contact_rejects_body_absent_from_final_independently() -> None:
    before, left, right, body, book, row = _c9_contact_fixture(body_visible=False)
    with pytest.raises(PilotPreviewError, match="HAND_BODY_NOT_VISIBLE"):
        jobs._validate_final_hand_pixels(before_hands=before, final_frame=jobs._reference_alpha_composite(jobs._reference_alpha_composite(before, left), right), hand_layers={"left": left, "right": right}, body_layer=body, book_mask=book, book_reference=before, row=row)


def test_c9_contact_rejects_opaque_green_support() -> None:
    before, left, right, body, book, row = _c9_contact_fixture()
    left[9, 10] = (30, 150, 70, 255)
    with pytest.raises(PilotPreviewError, match="HAND_GREEN_SUPPORT_VISIBLE"):
        jobs._validate_final_hand_pixels(before_hands=before, final_frame=jobs._reference_alpha_composite(jobs._reference_alpha_composite(before, left), right), hand_layers={"left": left, "right": right}, body_layer=body, book_mask=book, book_reference=before, row=row)


def test_c9_contact_rejects_left_right_identity_swap() -> None:
    before, left, right, body, book, row = _c9_contact_fixture()
    with pytest.raises(PilotPreviewError, match="HAND_BOOK_TARGET_MISMATCH"):
        jobs._validate_final_hand_pixels(before_hands=before, final_frame=jobs._reference_alpha_composite(jobs._reference_alpha_composite(before, right), left), hand_layers={"left": right, "right": left}, body_layer=body, book_mask=book, book_reference=before, row=row)


def test_c9_semantic_hand_mask_excludes_opaque_shirt_support() -> None:
    import cv2
    import numpy as np

    fixture_root = os.environ.get("MOTIONFORGE_PILOT_FIXTURE_ROOT")
    if not fixture_root:
        pytest.skip("MOTIONFORGE_PILOT_FIXTURE_ROOT is required for the real hand-source fixture")
    asset = Path(fixture_root) / "assets" / "pilot-packs" / "luna-reader-seated-c7-v1" / "seated_book_open-c7-hand-source-rgba.png"
    rgba = cv2.imread(str(asset), cv2.IMREAD_UNCHANGED)
    masked = jobs._semantic_hand_alpha(rgba, side="left", state_id="seated_book_open")
    b, g, r = (masked[:, :, index].astype(np.int16) for index in range(3))
    opaque_green = (masked[:, :, 3] > 32) & (g >= r + 8) & (g >= b + 8)
    assert int(opaque_green.sum()) == 0
    assert int((masked[:, :, 3] > 32).sum()) > 0


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Isolated app client: disposable DB + managed root under tmp_path."""
    from alembic import command
    from alembic.config import Config

    from app.persistence import create_engine_for_path, create_session_factory
    from app.config import AppConfig
    from app.workflow.job_service import JobService
    from app.workflow.project_workflow import ProjectWorkflowService

    project_root = tmp_path / "projects"
    managed_root = tmp_path / "managed"
    project_root.mkdir(parents=True)
    managed_root.mkdir(parents=True)
    monkeypatch.setenv("MOTIONFORGE_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_ROOT", str(project_root))
    test_config = AppConfig(
        project_root=project_root,
        models_dir=tmp_path / "models",
        output_dir=tmp_path / "output",
    )
    monkeypatch.setattr(deps, "_config", test_config)
    monkeypatch.setattr(deps, "_project_wf", ProjectWorkflowService(test_config))
    db_path = project_root / "data" / "motionforge.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")
    factory = create_session_factory(create_engine_for_path(db_path))
    monkeypatch.setattr(deps, "_job_service", JobService(factory, managed_root=managed_root))
    from app.api.app import app

    return TestClient(app, raise_server_exceptions=False)


def _project_with_source(client: TestClient, tmp_path: Path, source_path: Path | None = None) -> str:
    resp = client.post("/api/projects", json={"name": "T04 pipeline probe"})
    assert resp.status_code == 201, resp.text
    legacy_id = resp.json()["project_id"]
    clip = source_path or (tmp_path / "clip.mp4")
    if source_path is None:
        _tiny_mp4(clip)
    with clip.open("rb") as handle:
        upload = client.post(
            f"/api/projects/{legacy_id}/video",
            files={"file": ("clip.mp4", handle, "video/mp4")},
        )
    assert upload.status_code in (200, 201), upload.text
    return legacy_id


def test_r2_api_rejects_unknown_project(api_client: TestClient) -> None:
    body = _submit_body()
    body["project_id"] = "no-such-project"
    resp = api_client.post("/api/v2/pilot-preview/jobs", json=body)
    assert resp.status_code == 404


def test_r2_api_pack_gate_before_heavy_work(api_client: TestClient, tmp_path: Path) -> None:
    """Real public submit with the V3 negative → 422 with reasons, no job row."""
    legacy_id = _project_with_source(api_client, tmp_path)
    body = _submit_body()
    body["project_id"] = legacy_id
    resp = api_client.post("/api/v2/pilot-preview/jobs", json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "PACK_COMPATIBILITY_FAILED" in detail
    assert "grip_both_hands_chest" in detail


def test_r2_public_api_positive_path_uses_server_pack(api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A positive submit crosses the public boundary only with a real pack.

    The engineering pack is a tiny RGBA fixture, not approved artwork.  This
    test stops at durable job creation; it does not claim a visual render.
    """
    pack_root = tmp_path / "assets" / "pilot-packs"
    clip = tmp_path / "clip.mp4"
    _tiny_mp4(clip)
    source_sha = hashlib.sha256(clip.read_bytes()).hexdigest()
    _root, content_sha = _engineering_pack_for_api(pack_root, source_sha256=source_sha)
    import shutil

    isolated_models = tmp_path / "models"
    isolated_models.mkdir()
    pinned_checkpoint = Path(__file__).resolve().parents[3] / "runtime" / "models" / "sam2.1_hiera_large.pt"
    assert pinned_checkpoint.is_file()
    shutil.copyfile(pinned_checkpoint, isolated_models / "sam2.1_hiera_large.pt")
    # The route reads the isolated project parent, which is tmp_path.
    legacy_id = _project_with_source(api_client, tmp_path, clip)
    import app.api.routes.pilot_preview as pilot_route

    monkeypatch.setattr(
        pilot_route,
        "_chain",
        lambda _legacy_id, _generation: {"chain_status": "completed", "video_item_id": "video-positive"},
    )
    body = _submit_body(asset_sha=content_sha)
    body["project_id"] = legacy_id
    body["pack_id"] = "engineering-pack-v1"
    body["pack_capabilities"] = {"seated_pose": False, "view_three_quarter_front": "side_profile"}
    response = api_client.post("/api/v2/pilot-preview/jobs", json=body)
    assert response.status_code == 202, response.text
    manifest = response.json()["manifest"]
    assert manifest["pack_id"] == "engineering-pack-v1"
    assert manifest["pack_content_sha256"] == content_sha
    assert manifest["pack_capabilities"]["view_three_quarter_front"] == "three_quarter_front_this_window"
    assert manifest["asset_sha256"] == content_sha


def test_r2_api_context_exposes_pack_verdict(api_client: TestClient, tmp_path: Path) -> None:
    legacy_id = _project_with_source(api_client, tmp_path)
    resp = api_client.post(
        "/api/v2/pilot-preview/context", json={"project_id": legacy_id, "generation": "1"}
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["composition_revision"] == COMPOSITION_REVISION
    assert payload["pack_required_capabilities"] == list(COMPAT_REQUIREMENTS)
    assert payload["pack_verdict_for_pinned_asset"]["compatible"] is False


def test_r2_api_foreign_job_and_approval_fail_closed(api_client: TestClient) -> None:
    resp = api_client.get("/api/v2/pilot-preview/jobs/does-not-exist")
    assert resp.status_code == 404
    resp = api_client.post("/api/v2/pilot-preview/jobs/does-not-exist/approve")
    assert resp.status_code in (403, 404)
    resp = api_client.get("/api/v2/pilot-preview/jobs/does-not-exist/media/after")
    assert resp.status_code == 404
