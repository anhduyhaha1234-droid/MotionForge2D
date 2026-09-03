"""S11-T03F (W7): full per-video orchestrator + recheck resolution +
measured summary tests.

Binary acceptances (production plan REV7/C6 SHA 34247926 block W7):

1. ONE orchestrator command on ONE video_item runs the FULL registered
   check-set (8 visual/timecode reasons + audio_missing + av_sync_drift),
   persisting exactly the QCItem set each detector reports (dynamic
   per-detector expectation, never a hard-coded count).
2. Recheck flow: fix evidence -> recheck-run -> item auto-resolves; not
   fixed -> stays open; no code path may place terminal QC status outside
   the recheck-evidence lifecycle (C2-F2): binary source scan over app/.
3. Idempotency: running twice on identical input yields the same item set,
   zero duplicates (natural key), zero new rows on the second run.
4. Summary counts are MEASURED runtime values (created,
   resolved_after_recheck, not_applicable, errors, per-detector counts);
   assertions are dynamic against the fixture manifest, not hard-coded
   expected counts.
5. no_audio_source (T06A1 REAL media) -> ``not_applicable`` recorded for
   audio_missing (and av_sync_drift), ZERO QCItem created (C2-F2).
6. Cancel / deadline bounds the WHOLE run: pre-set cancel -> all checks
   skipped, zero writes, zero child spawns.
7. Stale-reopen hook (wiring GAP-8, service layer shared with T04B):
   evidence supersede (superseded_by_id + manifest/cast revision) reopens
   an acknowledged item to open with a stale flag in evidence; terminal
   items are refused (no reversal).

Isolation: per-test temp SQLite DB built from ORM metadata; short unique
Windows-native basetemp supplied by the runner; ``-p no:cacheprovider`` and
``MOTIONFORGE_DATABASE_URL`` stripped by the runner command.  Media fixtures
are REAL T06A1 outputs (build_two_scene_source, build_multistream_duration_
variant, build_no_audio_source — each asserted by ffprobe in the builder).
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import threading
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.persistence import create_engine_for_path
from app.persistence.models import Base, QC_REASON_CODES
from app.persistence.qc_items import (
    QCItemEvidenceRequiredError,
    QCItemInvalidTransitionError,
    QCItemRecord,
    QCItemRepository,
)
from app.services.qc_checks import (
    audio_missing,
    av_sync_drift,
    contact_break,
    cut_drift,
    edge_halo,
    identity_drift,
    silhouette_clipping,
    temporal_flicker,
    trajectory_drift,
    z_order_error,
)
from app.services.qc_checks.registry import registry
from app.services.qc_checks.runner import (
    QC_RUNNER_INVALID_ARGS,
    QcRunnerError,
)
# RED gate: the orchestrator module does NOT exist at WAVE_BASE — importing
# it here is the RED proof (ModuleNotFoundError before implementation).
from app.services.qc_checks.orchestrator import (
    OrchestratorSummary,
    reopen_stale_evidence,
    run_full_check_set,
)
from app.services.timebase import CanonicalTimebase
from s11_qc_calibration_builders import generate_trajectory_drift_input
from s11_qc_media_builders import (
    build_multistream_duration_variant,
    build_no_audio_source,
    build_two_scene_source,
    ffmpeg_available,
    probe,
)
from s11_qc_seed import seed_workspace_project_video

pytestmark = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)

WS = "ws-s11-t03f"
P1 = "p-s11-t03f"
V1 = "v-s11-t03f"

#: Frozen registration identities (T03B/C/D/E) — the orchestrator consumes
#: the registry read-only; this fixture only asserts the binding set.
_REGISTRATION = [
    ("trajectory_drift", "app.services.qc_checks.trajectory_drift:detect"),
    ("cut_drift", "app.services.qc_checks.cut_drift:detect"),
    ("contact_break", "app.services.qc_checks.contact_break:detect_contact_break"),
    ("z_order_error", "app.services.qc_checks.z_order_error:detect_z_order_error"),
    ("silhouette_clipping", "app.services.qc_checks.silhouette_clipping:detect_silhouette_clipping"),
    ("identity_drift", "app.services.qc_checks.identity_drift:detect"),
    ("edge_halo", "app.services.qc_checks.edge_halo:detect"),
    ("temporal_flicker", "app.services.qc_checks.temporal_flicker:detect"),
    ("audio_missing", "app.services.qc_checks.audio_missing:detect"),
    ("av_sync_drift", "app.services.qc_checks.av_sync_drift:detect"),
]

#: T06A2 raw boundary values referenced by the fixtures (frozen calibration,
#: tests/fixtures/s11_qc/calibration/av_sync.json; same convention as T03E).
AV_SYNC_WARNING_SEC = 0.1
AV_SYNC_BLOCKER_SEC = 0.5


@pytest.fixture(scope="module", autouse=True)
def _ensure_full_registered_set() -> None:
    """Idempotently refresh the binding 10-check registration set.

    Importing the detector modules self-registers; a previous suite may have
    unregistered members (T03C teardown), so re-registering the exact binding
    entry points makes the orchestrator's discovery deterministic for THIS
    module.  No unregistration on teardown (never harm a later suite).
    """
    for name, entry_point in _REGISTRATION:
        registry.register(name, entry_point)


# ── engine / session helpers (mirror T02B/T03B fresh-DB pattern) ───────────


def _fresh_engine(tmp_path: Path, name: str = "t03f.db") -> Any:
    engine = create_engine_for_path(tmp_path / name)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        seed_workspace_project_video(
            conn, workspace_id=WS, project_id=P1, video_item_id=V1
        )
    return engine


def _identity() -> dict[str, str]:
    return {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "checkpoint_ref": "ckpt-t03f",
    }


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ── REAL T06A1 media -> checkpoint envelopes (T03E replica) ─────────────────


def _healthy_audio_checkpoint(source: Path) -> dict[str, Any]:
    """Probe-derived post-remux checkpoint for a source that HAS audio and
    whose validated output kept it (STREAM_COPY, published artifact)."""
    data = probe(source)
    streams = [
        s for s in data.get("streams", []) if s.get("codec_type") == "audio"
    ]
    assert len(streams) >= 1, "fixture source must carry audio"
    first_audio = streams[0]
    duration = data.get("format", {}).get("duration")
    output_duration = f"{float(duration):.6f}" if duration else "2.000000"
    checkpoint = {
        "schema_version": 1,
        "status": "STREAM_COPY",
        "mode": "stream_copy",
        "source_sha256": _sha256_hex({"path": str(source)}),
        "source_size_bytes": source.stat().st_size,
        "source_audio_codec": first_audio.get("codec_name"),
        "source_audio_duration": output_duration,
        "output_audio_codec": "aac",
        "output_audio_duration": output_duration,
        "audio_time_base": first_audio.get("time_base") or "1/48000",
        "video_codec": "h264",
    }
    published = {
        "no_audio_present": False,
        "final_rel": "final/original_audio.mp4",
        "artifact_id": "art-t03f-1",
        "sha256": _sha256_hex({"artifact": "output"}),
        "size_bytes": 12345,
        "status": "STREAM_COPY",
    }
    return {"checkpoint": checkpoint, "published": published}


def _no_audio_checkpoint(source: Path) -> dict[str, Any]:
    """Real no-audio media -> the NO_AUDIO_PRESENT terminal envelope."""
    data = probe(source)
    streams = data.get("streams", [])
    assert all(s.get("codec_type") != "audio" for s in streams), (
        "no_audio_source fixture must carry zero audio streams"
    )
    checkpoint = {
        "schema_version": 1,
        "status": "NO_AUDIO_PRESENT",
        "mode": None,
        "source_sha256": _sha256_hex({"path": str(source)}),
        "source_size_bytes": source.stat().st_size,
        "source_audio_codec": None,
        "source_audio_duration": None,
        "output_audio_codec": None,
        "output_audio_duration": None,
        "audio_time_base": None,
        "video_codec": "h264",
    }
    published = {
        "no_audio_present": True,
        "artifact_id": None,
        "final_rel": None,
        "sha256": None,
        "size_bytes": None,
        "status": "NO_AUDIO_PRESENT",
    }
    return {"checkpoint": checkpoint, "published": published}


# ── per-detector args (T03B/C/D/E fixture families) ────────────────────────


def _traj_args(amp: float, frames: int = 64, seed: int = 11001) -> dict[str, Any]:
    inp = generate_trajectory_drift_input(seed=seed, drift_px_per_frame=amp, frames=frames)
    return {
        **_identity(),
        "reference_x": [float(v) for v in inp["reference_x"]],
        "observed_x": [float(v) for v in inp["drifted_x"]],
        "frame_start": 0,
        "checkpoint_ref": "ckpt-t03f-traj",
    }


def _cut_args(*, render_cuts_ms: list[int]) -> dict[str, Any]:
    tb = CanonicalTimebase.from_rational(30, 1, nb_frames=120)
    return {
        **_identity(),
        "timebase": tb.to_json(),
        "scene_boundaries": [{"position": 1, "start_frame": 60}],
        "render_cuts_ms": render_cuts_ms,
        "checkpoint_ref": "ckpt-t03f-cut",
    }


_WINDOW = {"start_frame": 0, "end_frame": 47}


def _segment(
    seg_id: str,
    *,
    z_order: int,
    start_frame: int = 0,
    end_frame: int = 47,
    bbox_per_frame: list[list[float]] | None = None,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "id": seg_id,
        "logical_id": f"L-{seg_id}",
        "z_order": z_order,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "bbox_per_frame": bbox_per_frame,
        "bbox": bbox,
    }


def _contact(
    source: str,
    target: str,
    *,
    start_frame: int,
    end_frame: int,
) -> dict[str, Any]:
    return {
        "id": f"contact-{source}-{target}",
        "source_segment_id": source,
        "target_segment_id": target,
        "contact_kind": "touch",
        "start_frame": start_frame,
        "end_frame": end_frame,
        "confidence": 0.98,
        "confidence_source": "derived",
    }


def _contact_pass_args() -> dict[str, Any]:
    """Contact still active at the end of the window -> not expired -> pass."""
    w = _WINDOW["end_frame"] - _WINDOW["start_frame"] + 1
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    b = _segment("seg-b", z_order=20, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    return {
        "contacts": [_contact("seg-a", "seg-b", start_frame=0, end_frame=47)],
        "segments": [a, b],
        "analysis_window": dict(_WINDOW),
        "checkpoint_ref": "ckpt-t03f-contact",
    }


def _chain_segments(count: int) -> list[dict[str, Any]]:
    segs = []
    for i in range(count):
        segs.append(_segment(f"s{i}", z_order=count - i))
    return segs


def _chain_edges(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"occ-s{i}-s{i + 1}",
            "occluder_segment_id": f"s{i}",
            "occludee_segment_id": f"s{i + 1}",
            "start_frame": 0,
            "end_frame": 47,
            "confidence": 0.99,
            "confidence_source": "derived",
        }
        for i in range(count - 1)
    ]


def _zorder_pass_args() -> dict[str, Any]:
    """Occlusion-consistent (no render_order -> z_order fallback) -> pass."""
    return {
        "segments": _chain_segments(3),
        "occlusion_edges": _chain_edges(3),
        "analysis_window": dict(_WINDOW),
        "render_order": None,
        "lock_manifest": None,
        "checkpoint_ref": "ckpt-t03f-zorder",
    }


def _clipping_pass_args() -> dict[str, Any]:
    """Bbox fully inside the 100x100 frame -> zero clip ratio -> pass."""
    seg = _segment("seg-a", z_order=10, bbox=[5.0, 5.0, 95.0, 95.0])
    return {
        "segments": [seg],
        "frame": {"width": 100.0, "height": 100.0},
        "analysis_window": dict(_WINDOW),
        "checkpoint_ref": "ckpt-t03f-clip",
    }


def _crop(base: float = 100.0, grid: int = 8) -> dict[str, Any]:
    pixels = [[int(base)] * grid for _ in range(grid)]
    raw = json.dumps(pixels, separators=(",", ":")).encode("utf-8")
    return {
        "width": grid,
        "height": grid,
        "pixels": pixels,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _sha256_of_pixels(pixels: list[list[int]]) -> str:
    raw = json.dumps(pixels, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identity_args(*, delta: float, meta_deltas: list[bool]) -> dict[str, Any]:
    ref = _crop(100.0)
    frames: list[dict[str, Any]] = []
    for i, flipped in enumerate(meta_deltas):
        pixels = [[int(100.0 + delta)] * 8 for _ in range(8)]
        frames.append(
            {
                "frame_index": i,
                "artifact_id": f"art-id-{i}",
                "sha256": _sha256_of_pixels(pixels),
                "crop": {"width": 8, "height": 8, "pixels": pixels},
                "metadata": {
                    "role_id": "role-flip" if flipped else "role-pinned",
                    "instance_id": "inst-pinned",
                    "cast_pin_ref": "cast-pin-1",
                },
            }
        )
    return {
        **_identity(),
        "checkpoint_ref": "ckpt-t03f-identity",
        "segment_row_id": None,
        "segment_logical_id": None,
        "pinned_reference": {
            "artifact_id": "art-ref",
            "sha256": ref["sha256"],
            "crop_revision": "1.0.0",
            "crop": {"width": 8, "height": 8, "pixels": ref["pixels"]},
        },
        "cast_pin": {
            "object_role_id": "role-pinned",
            "character_id": "char-1",
            "pack_version_id": "pack-1",
            "revision": 1,
            "expected_metadata": {
                "role_id": "role-pinned",
                "instance_id": "inst-pinned",
                "cast_pin_ref": "cast-pin-1",
            },
            "compatible": True,
            "compatibility_reasons": [],
        },
        "frames": frames,
    }


def _disc_mask(grid: int, inner_r: float, halo_r: float) -> list[list[int]]:
    center = grid / 2.0
    mask: list[list[int]] = []
    for y in range(grid):
        row: list[int] = []
        for x in range(grid):
            d = math.sqrt((x - center) ** 2 + (y - center) ** 2)
            row.append(1 if d < inner_r + halo_r else 0)
        mask.append(row)
    return mask


def _halo_args(*, halo_r: float, grid: int = 64, inner_r: float = 20.0) -> dict[str, Any]:
    """Small grid (64x64): the orchestrator serializes detector args onto the
    child command line (T03A runner) — a 200x200 pixel grid would exceed the
    Windows 32K CreateProcess limit (WinError 206).  Same T06A2 ring
    geometry, scaled; halo_r=0 -> identical masks -> pass."""
    expected_px = _disc_mask(grid, inner_r, 0.0)
    rendered_px = _disc_mask(grid, inner_r, halo_r)
    return {
        **_identity(),
        "checkpoint_ref": "ckpt-t03f-halo",
        "frame_index": 10,
        "mask_revision": "2.1.0",
        "inner_radius_px": inner_r,
        "rendered": {
            "artifact_id": "art-rendered-halo",
            "sha256": _sha256_of_pixels(rendered_px),
            "mask": {"width": grid, "height": grid, "pixels": rendered_px},
        },
        "expected": {
            "artifact_id": "art-expected-mask",
            "sha256": _sha256_of_pixels(expected_px),
            "mask": {"width": grid, "height": grid, "pixels": expected_px},
        },
    }


def _flicker_args(*, amp: float, frames: int = 128, seed: int = 11008) -> dict[str, Any]:
    phase = float(seed % 8)
    luminance = [
        100.0 + amp * math.sin(2.0 * math.pi * (ti + phase) / 16.0)
        for ti in range(frames)
    ]
    return {
        **_identity(),
        "checkpoint_ref": "ckpt-t03f-flicker",
        "window": {"start_frame": 0, "end_frame": frames - 1},
        "luminance": luminance,
    }


def _audio_issue_args(healthy: dict[str, Any]) -> dict[str, Any]:
    """Source HAS audio but the attach job FAILED -> one blocker item."""
    return {
        **_identity(),
        **healthy,
        "error": {
            "error_type": "AttachAudioError",
            "code": "ATTACH_VALIDATION_FAILED",
            "message": "attach validation failed",
        },
    }


def _av_sync_args(drift_total_sec: float) -> dict[str, Any]:
    """Scene timeline = 60 frames @ 30fps (exactly 2 s); output duration =
    2 s + drift -> the given drift in the frozen policy band."""
    return {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": f"{2.0 + drift_total_sec:.6f}",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {"fps_num": 30, "fps_den": 1, "nb_frames": 60},
    }


def _no_audio_args(no_audio: dict[str, Any]) -> dict[str, Any]:
    """Both audio detectors over the terminal NO_AUDIO_PRESENT fact."""
    return {
        **_identity(),
        **no_audio,
        "scene_timeline": None,
    }


# ── dynamic expectation: each detector's own in-process detect() ───────────


def _expected_created(name: str, args: dict[str, Any]) -> int:
    """Run the detector's OWN entry point in-process on the SAME args and
    count the issues it reports — the fixture manifest expectation, never a
    hard-coded count."""
    fn_map = {
        "trajectory_drift": trajectory_drift.detect,
        "cut_drift": cut_drift.detect,
        "contact_break": contact_break.detect_contact_break,
        "z_order_error": z_order_error.detect_z_order_error,
        "silhouette_clipping": silhouette_clipping.detect_silhouette_clipping,
        "identity_drift": identity_drift.detect,
        "edge_halo": edge_halo.detect,
        "temporal_flicker": temporal_flicker.detect,
        "audio_missing": audio_missing.detect,
        "av_sync_drift": av_sync_drift.detect,
    }
    output = fn_map[name](dict(args))
    if isinstance(output, list):
        return len(output)
    if isinstance(output.get("qc_items"), list):
        return len(output["qc_items"])
    if isinstance(output.get("items"), list):
        return len(output["items"])
    measurements = output.get("measurements")
    if isinstance(measurements, list):
        return len([m for m in measurements if m.get("severity") is not None])
    return 0


def _issue_args(tmp_path: Path) -> dict[str, Any]:
    """Full-set fixture: REAL 2-scene + multistream media for the audio
    checkpoints; 4 detectors reporting issues, 6 passing."""
    two_scene = build_two_scene_source(tmp_path / "two_scene.mp4")
    two_scene_streams = probe(two_scene).get("streams", [])
    assert any(s.get("codec_type") == "audio" for s in two_scene_streams), (
        "two_scene_source fixture must carry audio"
    )
    assert any(s.get("codec_type") == "video" for s in two_scene_streams), (
        "two_scene_source fixture must carry video"
    )
    multistream = build_multistream_duration_variant(tmp_path / "multistream.mp4")
    healthy = _healthy_audio_checkpoint(multistream)
    return {
        "trajectory_drift": _traj_args(amp=4.0),          # 126 px == blocker
        "cut_drift": _cut_args(render_cuts_ms=[2400]),     # drift 12 == blocker
        "contact_break": _contact_pass_args(),
        "z_order_error": _zorder_pass_args(),
        "silhouette_clipping": _clipping_pass_args(),
        "identity_drift": _identity_args(delta=0.0, meta_deltas=[False, False]),
        "edge_halo": _halo_args(halo_r=0.0),
        "temporal_flicker": _flicker_args(amp=0.0),
        "audio_missing": _audio_issue_args(healthy),
        "av_sync_drift": _av_sync_args(AV_SYNC_WARNING_SEC + 0.15),  # 0.25 s warning
    }


def _fixed_args(tmp_path: Path) -> dict[str, Any]:
    """The FIX of the issue args: every detector in its pass band."""
    two_scene = build_two_scene_source(tmp_path / "two_scene.mp4")
    assert any(s.get("codec_type") == "video" for s in probe(two_scene).get("streams", [])), (
        "two_scene_source fixture must carry video"
    )
    multistream = build_multistream_duration_variant(tmp_path / "multistream.mp4")
    healthy = _healthy_audio_checkpoint(multistream)
    return {
        "trajectory_drift": _traj_args(amp=0.2),              # 6.3 px -> pass
        "cut_drift": _cut_args(render_cuts_ms=[2000]),        # drift 0 -> pass
        "contact_break": _contact_pass_args(),
        "z_order_error": _zorder_pass_args(),
        "silhouette_clipping": _clipping_pass_args(),
        "identity_drift": _identity_args(delta=0.0, meta_deltas=[False, False]),
        "edge_halo": _halo_args(halo_r=0.0),
        "temporal_flicker": _flicker_args(amp=0.0),
        "audio_missing": {**_identity(), **healthy, "error": None},
        "av_sync_drift": _av_sync_args(0.0),                  # drift 0 -> pass
    }


def _no_audio_args_map(tmp_path: Path) -> dict[str, Any]:
    """Full-set args over the REAL no-audio source: audio detectors see the
    NO_AUDIO_PRESENT terminal fact; visuals use pass-band args."""
    no_audio = build_no_audio_source(tmp_path / "no_audio.mp4")
    env = _no_audio_checkpoint(no_audio)
    base = _fixed_args(tmp_path)
    base["audio_missing"] = {**_identity(), **env, "error": None}
    base["av_sync_drift"] = _no_audio_args(env)
    return base


def _natural_key(record: QCItemRecord) -> tuple[Any, ...]:
    return (
        record.workspace_id,
        record.project_id,
        record.video_item_id,
        record.layer_ref_type,
        record.layer_ref_id,
        record.reason_code,
        record.evidence_window_key,
    )


def _list_all(session: Session) -> list[QCItemRecord]:
    records, _total = QCItemRepository(session).list(workspace_id=WS, limit=10000)
    return records


def _run(
    session: Session,
    args_map: dict[str, Any],
    *,
    detectors: list[str] | None = None,
    deadline_sec: float = 60.0,
    cancel_event: threading.Event | None = None,
    lifecycle_signal: dict[str, Any] | None = None,
) -> OrchestratorSummary:
    return run_full_check_set(
        session,
        workspace_id=WS,
        project_id=P1,
        video_item_id=V1,
        detector_args=args_map,
        detectors=detectors,
        deadline_sec=deadline_sec,
        capture_cap_bytes=64 * 1024,
        cancel_event=cancel_event,
        lifecycle_signal=lifecycle_signal,
        commit=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# AC1: one command, full registered set, per-detector measured summary
# ═══════════════════════════════════════════════════════════════════════════


def test_registered_set_is_the_binding_10_reason_codes() -> None:
    names = registry.names()
    assert set(names) == set(QC_REASON_CODES)
    assert len(names) == len(QC_REASON_CODES) == 10


def test_full_set_one_command_measured_per_detector(tmp_path: Path) -> None:
    """AC1: ONE orchestrator command on ONE video_item runs the full
    registered set; the created set equals the fixture-manifest expectation
    computed dynamically from each detector's own in-process run."""
    engine = _fresh_engine(tmp_path)
    args_map = _issue_args(tmp_path)
    expected = {name: _expected_created(name, args_map[name]) for name in args_map}
    assert sum(expected.values()) >= 4, "fixture must exercise issue creation"

    with Session(engine) as session:
        summary = _run(session, args_map)
        items = _list_all(session)

    assert summary.checks_requested == len(_REGISTRATION) == len(QC_REASON_CODES)
    assert summary.checks_run == len(_REGISTRATION)
    assert summary.checks_skipped == 0
    assert summary.errors == 0
    assert summary.cancelled is False
    assert summary.deadline_exceeded is False
    # measured summary equals the fixture-manifest expectation (dynamic)
    assert summary.created == sum(expected.values())
    assert summary.resolved_after_recheck == 0
    assert summary.not_applicable == 0
    for name, expected_created in expected.items():
        assert summary.per_detector[name]["created"] == expected_created, (
            f"detector {name}: measured {summary.per_detector[name]['created']} "
            f"!= manifest expectation {expected_created}"
        )
        assert summary.per_detector[name]["ran"] is True
        assert summary.per_detector[name]["items_found"] == expected_created
    # every expected item exists in the DB with exactly the right reason code
    by_reason: dict[str, list[QCItemRecord]] = {}
    for item in items:
        by_reason.setdefault(item.reason_code, []).append(item)
    total_expected = sum(expected.values())
    assert len(items) == total_expected
    for name, expected_created in expected.items():
        if expected_created == 0:
            assert name not in by_reason
        else:
            assert len(by_reason[name]) == expected_created
            assert all(i.status == "open" for i in by_reason[name])
    # summary is fully JSON-serializable (measured report artifact)
    json.dumps(
        {
            "created": summary.created,
            "resolved_after_recheck": summary.resolved_after_recheck,
            "not_applicable": summary.not_applicable,
            "errors": summary.errors,
            "per_detector": summary.per_detector,
        },
        sort_keys=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# AC3: idempotency — identical input x2 -> same item set, zero duplicates
# ═══════════════════════════════════════════════════════════════════════════


def test_idempotency_x2_zero_duplicates(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    args_map = _issue_args(tmp_path)
    with Session(engine) as session:
        first = _run(session, args_map)
        items1 = _list_all(session)
        second = _run(session, args_map)
        items2 = _list_all(session)

    assert first.created >= 4
    # second run: zero new rows, zero duplicates (natural-key idempotent)
    assert second.created == 0
    assert second.reused >= first.created
    assert second.resolved_after_recheck == 0
    assert second.errors == 0
    assert len(items2) == len(items1)
    assert {_natural_key(i) for i in items2} == {_natural_key(i) for i in items1}
    assert len({_natural_key(i) for i in items2}) == len(items2)
    # determinism: same run fingerprint for identical input
    assert first.run_id == second.run_id


# ═══════════════════════════════════════════════════════════════════════════
# AC2: recheck flow — auto-resolve on pass evidence, stays open when unfixed
# ═══════════════════════════════════════════════════════════════════════════


def test_recheck_flow_fix_resolves_not_fixed_stays_open(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    issue = _issue_args(tmp_path)
    fixed = _fixed_args(tmp_path)

    with Session(engine) as session:
        # run 1: issues detected -> open items
        r1 = _run(session, issue)
        items1 = _list_all(session)
        open_keys = {_natural_key(i) for i in items1}
        assert r1.created == len(items1) >= 4

        # run 2: SAME input -> still open (chua fix -> van open), zero resolve
        r2 = _run(session, issue)
        items2 = _list_all(session)
        assert r2.created == 0
        assert r2.resolved_after_recheck == 0
        assert {i.status for i in items2} == {"open"}

        # run 3: fix evidence -> every previously open item auto-resolves
        r3 = _run(session, fixed)
        items3 = _list_all(session)
        assert r3.created == 0
        assert r3.resolved_after_recheck == len(open_keys)
        assert {i.status for i in items3} == {"resolved"}
        # every resolution carries fresh recheck evidence (measured fields)
        for item in items3:
            ev = item.evidence
            assert ev["recheck"] == "resolved"
            assert ev["recheck_source"] == "s11-qc-orchestrator"
            assert ev["recheck_result"] in ("pass", "not_applicable")
            assert ev["run_id"] == r3.run_id
            assert ev["supersedes_item_id"] == item.id
            assert ev["detector"] == item.detector
        # idempotent terminal: a 4th run cannot touch resolved items again
        r4 = _run(session, fixed)
        items4 = _list_all(session)
        assert r4.resolved_after_recheck == 0
        assert r4.created == 0
        assert {i.status for i in items4} == {"resolved"}
        assert len(items4) == len(items1)


def test_terminal_resolve_without_evidence_rejected(tmp_path: Path) -> None:
    """C2-F2: a terminal resolve attempt WITHOUT fresh evidence is refused by
    the lifecycle API — the orchestrator never bypasses it."""
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        item = repo.create(
            workspace_id=WS,
            project_id=P1,
            video_item_id=V1,
            layer_ref_type="video_item",
            layer_ref_id=V1,
            reason_code="trajectory_drift",
            evidence_window_key="ewk-t03f-no-evidence",
            evidence={"schema_version": 1, "seed": "t03f"},
            severity="blocker",
            category="trajectory_drift",
            detector="trajectory_drift",
            detector_revision="1.0.0",
            confidence=0.9,
            confidence_source="derived",
            checkpoint_ref="ckpt-t03f",
        )
        session.commit()
        with pytest.raises(QCItemEvidenceRequiredError):
            repo.recheck_resolved(item.id, WS, evidence=None)
        with pytest.raises(QCItemEvidenceRequiredError):
            repo.recheck_dismissed(item.id, WS, evidence=None)
        # the item is untouched: still open after the refused attempts
        assert repo.get(item.id, WS).status == "open"


def test_acknowledged_item_still_detected_returns_open(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    issue = _issue_args(tmp_path)
    with Session(engine) as session:
        _run(session, issue)
        items1 = _list_all(session)
        traj = next(i for i in items1 if i.detector == "trajectory_drift")
        repo = QCItemRepository(session)
        repo.acknowledge(traj.id, WS)
        session.commit()
        # recheck still detects the issue -> acknowledged returns to open
        r2 = _run(session, issue)
        after = repo.get(traj.id, WS)
        assert r2.resolved_after_recheck == 0
        assert after.status == "open"
        assert after.evidence["recheck"] == "failed"
        assert after.evidence["recheck_result"] == "still_detected"


# ═══════════════════════════════════════════════════════════════════════════
# C2-F2: no_audio_source terminal fact -> not_applicable + ZERO QCItem
# ═══════════════════════════════════════════════════════════════════════════


def test_no_audio_source_not_applicable_zero_items(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    args_map = _no_audio_args_map(tmp_path)
    with Session(engine) as session:
        summary = _run(session, args_map)
        items = _list_all(session)

    assert summary.not_applicable == 2  # audio_missing + av_sync_drift
    assert summary.per_detector["audio_missing"]["applicability"] == "not_applicable"
    assert summary.per_detector["av_sync_drift"]["applicability"] == "not_applicable"
    assert summary.per_detector["audio_missing"]["items_found"] == 0
    assert summary.created == 0  # ZERO QCItem created on the whole no-audio run
    assert items == []
    assert summary.errors == 0
    assert summary.checks_run == len(_REGISTRATION)


# ═══════════════════════════════════════════════════════════════════════════
# bounded run: cancel / deadline cover the WHOLE run, zero writes
# ═══════════════════════════════════════════════════════════════════════════


def test_cancel_event_bounds_whole_run_zero_writes(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    args_map = _issue_args(tmp_path)
    cancel = threading.Event()
    cancel.set()  # cancelled BEFORE any detector is scheduled
    with Session(engine) as session:
        summary = _run(session, args_map, cancel_event=cancel)
        items = _list_all(session)
    assert summary.cancelled is True
    assert summary.checks_run == 0
    assert summary.checks_skipped == len(_REGISTRATION)
    assert summary.created == 0
    assert summary.errors == 0  # skipped != errors
    assert items == []


def test_deadline_bounds_whole_run_invalid_bounds_rejected(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    args_map = _issue_args(tmp_path)
    with Session(engine) as session:
        with pytest.raises(QcRunnerError) as excinfo:
            _run(session, args_map, deadline_sec=0.0)
        assert excinfo.value.code == QC_RUNNER_INVALID_ARGS
        # A deadline that is already consumed before the first detector
        # bounds the WHOLE run: no detector produces a result, zero rows
        # written, the run reports deadline_exceeded.  (Whether a detector
        # lands on the scheduling-skip branch or the runner's own deadline
        # branch depends on OS timer granularity — the invariants below are
        # machine-independent: nothing ran, nothing was created, every
        # requested check is accounted for.)
        deadline_exhausted = _run(session, args_map, deadline_sec=1e-9)
        items = _list_all(session)
    assert deadline_exhausted.checks_run == 0
    assert deadline_exhausted.created == 0
    assert deadline_exhausted.deadline_exceeded is True
    assert (
        deadline_exhausted.checks_run
        + deadline_exhausted.checks_skipped
        + deadline_exhausted.errors
        == deadline_exhausted.checks_requested
        == len(_REGISTRATION)
    )
    assert items == []


def test_missing_detector_args_fail_closed(tmp_path: Path) -> None:
    """A registered detector without args can never run silently (fail-close:
    recorded as an orchestrator error, zero rows)."""
    engine = _fresh_engine(tmp_path)
    args_map = _issue_args(tmp_path)
    args_map.pop("trajectory_drift")
    with Session(engine) as session:
        summary = _run(session, args_map)
    entry = summary.per_detector["trajectory_drift"]
    assert entry["ran"] is False
    assert entry["error_code"] == "QC_ORCHESTRATOR_MISSING_ARGS"
    assert summary.errors == 1
    assert summary.checks_run == len(_REGISTRATION) - 1
    assert summary.created == sum(
        _expected_created(n, args_map[n]) for n in args_map
    )


# ═══════════════════════════════════════════════════════════════════════════
# GAP-8 stale-reopen hook (service layer, shared with T04B)
# ═══════════════════════════════════════════════════════════════════════════


def _seed_item(session: Session, *, reason_code: str = "trajectory_drift") -> QCItemRecord:
    repo = QCItemRepository(session)
    return repo.create(
        workspace_id=WS,
        project_id=P1,
        video_item_id=V1,
        layer_ref_type="video_item",
        layer_ref_id=V1,
        reason_code=reason_code,
        evidence_window_key="ewk-t03f-stale",
        evidence={"schema_version": 1, "seed": "t03f-stale"},
        severity="warning",
        category=reason_code,
        detector=reason_code,
        detector_revision="1.0.0",
        confidence=0.9,
        confidence_source="derived",
        checkpoint_ref="ckpt-t03f-stale",
    )


def test_stale_reopen_hook_acknowledged_to_open_stale_flag(tmp_path: Path) -> None:
    """GAP-8: superseding evidence (superseded_by_id + manifest lifecycle +
    cast revision) reopens an acknowledged item to open with the stale flag
    recorded in the fresh recheck evidence."""
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        item = _seed_item(session)
        session.commit()
        repo.acknowledge(item.id, WS)
        session.commit()
        reopened = reopen_stale_evidence(
            repo,
            repo.get(item.id, WS),
            workspace_id=WS,
            superseded_by_id="manifest-v2",
            supersession_reason="manifest lifecycle superseded",
            manifest_revision="2026-09-03-v2",
            cast_revision="cast-pack-4",
        )
        session.commit()
        ev = reopened.evidence
        assert reopened.status == "open"
        assert ev["stale"] is True
        assert ev["recheck"] == "stale_superseded"
        assert ev["superseded_by_id"] == "manifest-v2"
        assert ev["manifest_revision"] == "2026-09-03-v2"
        assert ev["cast_revision"] == "cast-pack-4"
        assert ev["recheck_source"] == "s11-qc-orchestrator"
        assert reopened.revision >= 2


def test_stale_reopen_terminal_item_refused(tmp_path: Path) -> None:
    """GAP-8 fail-closed: a terminally resolved/dismissed item can NEVER be
    reopened by the stale hook (terminal states are terminal, T02B)."""
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        item = _seed_item(session)
        session.commit()
        repo.recheck_resolved(
            item.id, WS, evidence={"schema_version": 1, "recheck": "resolved"}
        )
        session.commit()
        resolved = repo.get(item.id, WS)
        with pytest.raises(QCItemInvalidTransitionError):
            reopen_stale_evidence(
                repo,
                resolved,
                workspace_id=WS,
                superseded_by_id="manifest-v3",
                supersession_reason="superseded after terminal",
            )
        # untouched: still resolved with the original recheck evidence
        assert repo.get(item.id, WS).status == "resolved"


def test_run_level_stale_reopen_wiring(tmp_path: Path) -> None:
    """The orchestrator run wires the GAP-8 hook: a lifecycle signal naming
    an acknowledged item reopens it with the stale flag during the run."""
    engine = _fresh_engine(tmp_path)
    args_map = _issue_args(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        item = _seed_item(session, reason_code="trajectory_drift")
        session.commit()
        repo.acknowledge(item.id, WS)
        session.commit()
        summary = _run(
            session,
            args_map,
            lifecycle_signal={
                "superseded_by_id": item.id,
                "supersession_reason": "manifest lifecycle superseded",
                "manifest_revision": "2026-09-03-v2",
                "cast_revision": "cast-pack-4",
            },
        )
        after = repo.get(item.id, WS)
        session.commit()
    assert summary.reopened_stale == 1
    assert after.status == "open"
    assert after.evidence["stale"] is True
    assert after.evidence["superseded_by_id"] == item.id


# ═══════════════════════════════════════════════════════════════════════════
# C2-F2 zero-path: no terminal status outside the recheck lifecycle
# ═══════════════════════════════════════════════════════════════════════════


def test_zero_terminal_status_paths_outside_recheck_lifecycle() -> None:
    """AC2 binary source scan over app/: every caller that can place terminal
    QC status (resolved/dismissed) goes through the recheck-evidence path —
    zero exceptions.

    Scope is the QC lifecycle SURFACE: only modules that reference QCItem /
    qc_item are scanned (a ``status`` column on another domain — e.g.
    ObjectGroupingSuggestion dismissal — is not a QC terminal transition).
    Two probes:
    1. lifecycle-API callers (``recheck_resolved``/``recheck_dismissed``)
       exist ONLY in the lifecycle owner (definition) and the orchestrator
       (the single sanctioned consumer);
    2. REAL terminal-status WRITES (AST assignment / keyword writes with
       literal terminal values) exist NOWHERE outside the owner and the
       orchestrator — SQL CHECK literals (DDL strings) cannot appear as AST
       writes, so the T02A DB backstop is naturally excluded.
    """
    project_root = Path(__file__).resolve().parent.parent
    app_root = project_root / "app"
    lifecycle_owner = "app/persistence/qc_items.py"
    orchestrator = "app/services/qc_checks/orchestrator.py"

    terminal_calls = re.compile(r"\.recheck_(?:resolved|dismissed)\(")

    def is_terminal_constant(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in ("resolved", "dismissed")
        )

    caller_hits: list[tuple[str, int]] = []
    write_hits: list[tuple[str, int, str]] = []
    for py in sorted(app_root.rglob("*.py")):
        rel = py.relative_to(project_root).as_posix()
        text = py.read_text(encoding="utf-8", errors="replace")
        if "QCItem" not in text and "qc_item" not in text:
            continue  # no QC lifecycle surface in this module
        for lineno, line in enumerate(text.splitlines(), 1):
            if terminal_calls.search(line) and rel not in (
                lifecycle_owner,
                orchestrator,
            ):
                caller_hits.append((rel, lineno))
        if rel in (lifecycle_owner, orchestrator):
            continue  # sanctioned: owner defines, orchestrator consumes
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = (
                        target.id
                        if isinstance(target, ast.Name)
                        else target.attr
                        if isinstance(target, ast.Attribute)
                        else None
                    )
                    if name == "status" and is_terminal_constant(node.value):
                        write_hits.append(
                            (rel, node.lineno, ast.unparse(node)[:90])
                        )
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "status" and is_terminal_constant(kw.value):
                        write_hits.append(
                            (rel, node.lineno, ast.unparse(node)[:90])
                        )
    assert caller_hits == [], (
        f"terminal transition callers outside the orchestrator: {caller_hits}"
    )
    assert write_hits == [], (
        f"terminal status writes outside the QC lifecycle: {write_hits}"
    )

    # every orchestrator terminal/recheck call MUST pass fresh evidence
    orch_text = (project_root / orchestrator).read_text(encoding="utf-8")
    tree = ast.parse(orch_text)
    missing_evidence: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else None
        name = func.id if isinstance(func, ast.Name) else None
        if attr not in (
            "recheck_resolved",
            "recheck_dismissed",
            "recheck_failed",
        ) and name not in (
            "recheck_resolved",
            "recheck_dismissed",
            "recheck_failed",
        ):
            continue
        has_evidence_kw = any(kw.arg == "evidence" for kw in node.keywords)
        has_positional_evidence = len(node.args) >= 3
        if not (has_evidence_kw or has_positional_evidence):
            missing_evidence.append((node.lineno, attr or name or "?"))
    assert missing_evidence == [], (
        f"orchestrator terminal/recheck calls without evidence: {missing_evidence}"
    )