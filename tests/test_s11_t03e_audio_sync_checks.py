"""S11-T03E (W6): audio_missing/output-audio + av_sync_drift check tests.

Decision D freeze C2-F2 binary acceptance:

- A REAL ``NO_AUDIO_PRESENT`` source fact is a valid terminal fact -> check
  result ``not_applicable``, ZERO QCItem, nothing fabricated, no readiness
  block (binary count of audio_missing items == 0).
- Source HAS audio but the expected output is missing / attach job failed /
  validated output lost audio -> ONE QCItem, severity=blocker, status=open,
  reason_code EXACTLY the binding code ``audio_missing``.
- Time conversion is ONE-WAY through ``CanonicalTimebase`` exact rationals
  (raw floats between frame/ms/s are forbidden); a unit mismatch must be
  CAUGHT (never silently pass), reason_code ``av_sync_drift``.
- av_sync_drift: drift below warning -> pass (zero items); drift in the
  warning band -> warning QCItem; at/over the blocker boundary -> blocker
  QCItem (frozen policy s11-qc-thresholds-v1, boundaries cited from T06A2
  av_sync.json raw values).

Isolation: no DB, no cache provider, short unique Windows-native basetemp
(supplied by the runner), ``MOTIONFORGE_DATABASE_URL`` stripped by the
runner command.  Media fixtures are REAL T06A1 outputs (no_audio_source via
``build_no_audio_source``, ``_make_multistream_aac`` canonical first-audio,
streams never mixed).  The binding QC enum (correction C1, c1a6777) names
the two audio codes ``audio_missing`` / ``av_sync_drift`` — every reason
code emitted by these checks is a binding code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from s11_qc_media_builders import (
    build_no_audio_source,
    ffmpeg_available,
    probe,
)
from test_s11_original_audio_integration import _make_multistream_aac

import pytest

from app.services.qc_checks import (
    audio_missing,
    av_sync_drift,
)
from app.services.qc_checks.registry import get_detector
from app.services.qc_checks.runner import run_detector

pytestmark = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)

_WORKSPACE_ID = "ws-s11-t03e"
_PROJECT_ID = "prj-s11-t03e"
_VIDEO_ITEM_ID = "vid-s11-t03e"
_CHECKPOINT_REF = "ckpt-s11-t03e-1"

#: Frozen T06A2 raw values (tests/fixtures/s11_qc/calibration/av_sync.json)
#: — warning boundary = level-2 raw (0.1 s), blocker boundary = level-4 raw
#: (0.5 s).  Reading them here keeps tests content-derived; the check itself
#: reads the frozen policy via thresholds.classify.
_AV_SYNC_RAW = {
    "level1_sec": 0.05,
    "warning_sec": 0.1,   # level 2 raw == warning boundary
    "level3_sec": 0.25,
    "blocker_sec": 0.5,   # level 4 raw == blocker boundary
}


def _identity() -> dict[str, str]:
    return {
        "workspace_id": _WORKSPACE_ID,
        "project_id": _PROJECT_ID,
        "video_item_id": _VIDEO_ITEM_ID,
        "layer_ref_type": "video_item",
        "layer_ref_id": _VIDEO_ITEM_ID,
        "checkpoint_ref": _CHECKPOINT_REF,
    }


def _sha256_hex(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _no_audio_checkpoint(tmp_path: Path) -> dict:
    """REAL T06A1 no-audio media -> checkpoint mirroring the remux
    ``NO_AUDIO_PRESENT`` terminal envelope (status, zero audio fields)."""
    source = build_no_audio_source(tmp_path / "no_audio_source.mp4", duration=2.0)
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


def _multistream_checkpoint(tmp_path: Path) -> dict:
    """REAL T06A1 ``_make_multistream_aac`` (canonical FIRST audio stream,
    streams never mixed) -> a plausible post-remux checkpoint envelope."""
    source = _make_multistream_aac(tmp_path / "multistream.mp4", duration=2.0)
    data = probe(source)
    streams = [
        s for s in data.get("streams", []) if s.get("codec_type") == "audio"
    ]
    assert len(streams) >= 1, "multistream fixture must carry audio"
    first_audio = streams[0]  # canonical first-audio, no mixing
    assert first_audio.get("index") == 1, (
        "canonical first audio stream must be index 1 (video at 0)"
    )
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
        "audio_stream_index": first_audio.get("index"),
    }
    published = {
        "no_audio_present": False,
        "final_rel": "final/original_audio.mp4",
        "artifact_id": "art-t03e-1",
        "sha256": _sha256_hex({"artifact": "output"}),
        "size_bytes": 12345,
        "status": "STREAM_COPY",
    }
    return {"checkpoint": checkpoint, "published": published}


# ── audio_missing: NO_AUDIO_PRESENT branch ──────────────────────────────────


def test_no_audio_present_real_source_not_applicable_zero_items(
    tmp_path: Path,
) -> None:
    """AC1 branch 1: real NO_AUDIO_PRESENT terminal fact -> ``not_applicable``,
    ZERO audio_missing QCItem (binary count), nothing fabricated, no block."""
    args = {**_identity(), **_no_audio_checkpoint(tmp_path)}
    result = audio_missing.detect(args)

    assert result["detector"] == "audio_missing"
    assert result["applicability"] == "not_applicable"
    assert result["qc_items"] == []
    assert len(result["qc_items"]) == 0  # binary count: zero items
    assert result["block_readiness"] is False
    # Decision D: nothing fabricated — the source fact stands as recorded.
    assert result["evidence"]["source_audio_present"] is False
    assert result["evidence"]["status"] == "NO_AUDIO_PRESENT"
    assert "fabricated" not in result["evidence"]


def test_no_audio_present_checkpoint_status_alone_is_terminal(tmp_path: Path) -> None:
    """NO_AUDIO_PRESENT decided by the checkpoint status even without a
    published envelope (terminal source fact, content-derived)."""
    envelope = _no_audio_checkpoint(tmp_path)
    args = {**_identity(), "checkpoint": envelope["checkpoint"], "published": None}
    result = audio_missing.detect(args)
    assert result["applicability"] == "not_applicable"
    assert result["qc_items"] == []


# ── audio_missing: source-has-audio loss branches (blocker/open) ────────────


def test_source_audio_attach_job_failed_blocker_open(tmp_path: Path) -> None:
    """AC1 branch 2a: source HAS audio + attach job FAILED (error envelope)
    -> ONE QCItem severity=blocker status=open, binding reason code."""
    envelope = _multistream_checkpoint(tmp_path)
    args = {
        **_identity(),
        **envelope,
        "error": {
            "error_type": "AttachAudioError",
            "code": "ATTACH_VALIDATION_FAILED",
            "message": "attach validation failed",
        },
    }
    result = audio_missing.detect(args)
    assert result["applicability"] == "applicable"
    assert result["status"] == "blocker"
    assert len(result["qc_items"]) == 1
    item = result["qc_items"][0]
    assert item["severity"] == "blocker"
    assert item["status"] == "open"
    assert item["reason_code"] == "audio_missing"
    assert item["category"] == "audio_missing"
    assert item["detector"] == "audio_missing"
    assert item["evidence"]["source_audio_present"] is True
    assert item["evidence"]["failure_kind"] == "attach_failed"


def test_source_audio_expected_output_missing_blocker_open(tmp_path: Path) -> None:
    """AC1 branch 2b: source HAS audio but expected output is missing (no
    published artifact, no output audio duration) -> blocker/open."""
    envelope = _multistream_checkpoint(tmp_path)
    checkpoint = dict(envelope["checkpoint"])
    checkpoint["output_audio_duration"] = None
    checkpoint["output_audio_codec"] = None
    args = {
        **_identity(),
        "checkpoint": checkpoint,
        "published": None,  # nothing ever published
        "error": None,
    }
    result = audio_missing.detect(args)
    assert result["status"] == "blocker"
    assert len(result["qc_items"]) == 1
    item = result["qc_items"][0]
    assert item["severity"] == "blocker"
    assert item["status"] == "open"
    assert item["reason_code"] == "audio_missing"
    assert item["evidence"]["failure_kind"] == "output_missing"


def test_source_audio_validated_output_lost_audio_blocker_open(
    tmp_path: Path,
) -> None:
    """AC1 branch 2c: source HAS audio, artifact published, but the validated
    output lost its audio (no output_audio_codec/duration) -> blocker/open."""
    envelope = _multistream_checkpoint(tmp_path)
    checkpoint = dict(envelope["checkpoint"])
    checkpoint["output_audio_codec"] = None
    checkpoint["output_audio_duration"] = None
    args = {
        **_identity(),
        "checkpoint": checkpoint,
        "published": envelope["published"],
    }
    result = audio_missing.detect(args)
    assert result["status"] == "blocker"
    assert len(result["qc_items"]) == 1
    item = result["qc_items"][0]
    assert item["severity"] == "blocker"
    assert item["status"] == "open"
    assert item["reason_code"] == "audio_missing"
    assert item["evidence"]["failure_kind"] == "output_lost_audio"


def test_source_audio_output_present_passes_zero_items(tmp_path: Path) -> None:
    """Healthy branch: source HAS audio and the validated output still has
    audio -> applicable pass, ZERO QCItem."""
    envelope = _multistream_checkpoint(tmp_path)
    args = {**_identity(), **envelope, "error": None}
    result = audio_missing.detect(args)
    assert result["applicability"] == "applicable"
    assert result["status"] == "pass"
    assert result["qc_items"] == []
    assert result["block_readiness"] is False


# ── av_sync_drift: one-way CanonicalTimebase + unit mismatch ────────────────


def test_av_sync_frames_timeline_exact_fraction_pass() -> None:
    """Scene timeline given as 60 frames @ 30fps == exactly 2 s (one-way via
    CanonicalTimebase exact rational); remux decimal6 duration 2.000000 ->
    drift 0 -> pass, zero QCItem."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": "2.000000",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["applicability"] == "applicable"
    assert result["status"] == "pass"
    assert result["qc_items"] == []
    # evidence carries the exact rational and the boundary read from policy
    assert result["evidence"]["drift_seconds"] == 0
    assert result["evidence"]["drift_seconds_exact"] == "0"
    assert result["evidence"]["unit"] == "s"


def test_av_sync_unit_mismatch_ms_caught() -> None:
    """Unit mismatch is CAUGHT: a millisecond value recorded like a remux
    decimal6 duration (2000.000000) vs a 2 s scene -> ~1998 s drift is outside
    the calibrated envelope -> fail-closed blocker, NEVER a silent pass."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": "2000.000000",  # ms misread as seconds
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,  # == 2.000000 s exactly
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "blocker"
    assert len(result["qc_items"]) == 1
    item = result["qc_items"][0]
    assert item["severity"] == "blocker"
    assert item["status"] == "open"
    assert item["reason_code"] == "av_sync_drift"
    assert item["category"] == "av_sync_drift"
    assert item["evidence"]["unit_mismatch_caught"] is True


def test_av_sync_unit_mismatch_frames_caught() -> None:
    """Frame-unit confusion is caught: a frame count written into the
    duration field (60 frames as '60.000000') vs a 2 s scene -> 58 s drift ->
    fail-closed blocker (never silently pass)."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": "60.000000",  # frames misread as seconds
            "audio_time_base": "1/30",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "blocker"
    assert result["qc_items"][0]["severity"] == "blocker"
    assert result["qc_items"][0]["reason_code"] == "av_sync_drift"
    assert result["qc_items"][0]["evidence"]["unit_mismatch_caught"] is True


# ── av_sync_drift: warning / blocker bands (frozen policy boundaries) ───────


def test_av_sync_drift_warning_band_t06a2_level3() -> None:
    """Drift = level-3 T06A2 raw (0.25 s) is INSIDE the warning band
    [0.1, 0.5) -> QCItem severity=warning, status=open."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": f"{2.0 + _AV_SYNC_RAW['level3_sec']:.6f}",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "warning"
    assert len(result["qc_items"]) == 1
    item = result["qc_items"][0]
    assert item["severity"] == "warning"
    assert item["status"] == "open"
    assert item["reason_code"] == "av_sync_drift"
    assert item["detector"] == "av_sync_drift"


def test_av_sync_drift_warning_boundary_inclusive() -> None:
    """Drift == level-2 T06A2 raw (0.1 s) == warning boundary -> warning
    (>= warning boundary classifies warning, frozen policy)."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": f"{2.0 + _AV_SYNC_RAW['warning_sec']:.6f}",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "warning"
    assert result["qc_items"][0]["severity"] == "warning"


def test_av_sync_drift_blocker_boundary_inclusive() -> None:
    """Drift == level-4 T06A2 raw (0.5 s) == blocker boundary -> blocker
    (>= blocker boundary classifies blocker, frozen policy)."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": f"{2.0 + _AV_SYNC_RAW['blocker_sec']:.6f}",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "blocker"
    item = result["qc_items"][0]
    assert item["severity"] == "blocker"
    assert item["status"] == "open"


def test_av_sync_drift_beyond_blocker_is_blocker() -> None:
    """Drift beyond the blocker boundary (0.6 s, above level-4 raw) -> still
    a blocker (any sane value above the boundary is blocked)."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": "2.600000",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "blocker"
    assert result["qc_items"][0]["severity"] == "blocker"


def test_av_sync_drift_below_warning_is_pass() -> None:
    """Drift below the warning boundary (level-1 raw 0.05 s) -> pass, zero
    QCItem."""
    args = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": f"{2.0 + _AV_SYNC_RAW['level1_sec']:.6f}",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {
            "fps_num": 30,
            "fps_den": 1,
            "nb_frames": 60,
        },
    }
    result = av_sync_drift.detect(args)
    assert result["status"] == "pass"
    assert result["qc_items"] == []


def test_av_sync_no_audio_not_applicable(tmp_path: Path) -> None:
    """av_sync_drift over a real NO_AUDIO_PRESENT source -> not_applicable,
    zero QCItem (nothing to synchronize)."""
    envelope = _no_audio_checkpoint(tmp_path)
    args = {
        **_identity(),
        "checkpoint": envelope["checkpoint"],
        "published": envelope["published"],
        "scene_timeline": None,
    }
    result = av_sync_drift.detect(args)
    assert result["applicability"] == "not_applicable"
    assert result["qc_items"] == []


# ── idempotency + registry/runner contract ──────────────────────────────────


def test_both_checks_idempotent_x2(tmp_path: Path) -> None:
    """Evidence is content-derived: running each check twice on identical
    args produces byte-identical results (no timestamps/randomness)."""
    multistream = _multistream_checkpoint(tmp_path)
    args_audio = {
        **_identity(),
        **multistream,
        "error": {
            "error_type": "AttachAudioError",
            "code": "ATTACH_VALIDATION_FAILED",
        },
    }
    r1 = audio_missing.detect(args_audio)
    r2 = audio_missing.detect(args_audio)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)

    args_sync = {
        **_identity(),
        "checkpoint": {
            "status": "STREAM_COPY",
            "source_audio_present": True,
            "output_audio_duration": "2.250000",
            "audio_time_base": "1/48000",
        },
        "scene_timeline": {"fps_num": 30, "fps_den": 1, "nb_frames": 60},
    }
    s1 = av_sync_drift.detect(args_sync)
    s2 = av_sync_drift.detect(args_sync)
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)


def test_detectors_registered_and_runnable_via_runner(tmp_path: Path) -> None:
    """Both W6 detectors are registered under the exact expected names and
    runnable end-to-end through the T03A common bounded runner (child
    protocol, JSON round-trip)."""
    spec_a = get_detector("audio_missing")
    assert spec_a.entry_point == "app.services.qc_checks.audio_missing:detect"
    spec_s = get_detector("av_sync_drift")
    assert spec_s.entry_point == "app.services.qc_checks.av_sync_drift:detect"

    envelope = _no_audio_checkpoint(tmp_path)
    run = run_detector(
        "audio_missing",
        args={**_identity(), **envelope, "error": None},
        deadline_sec=30.0,
        capture_cap_bytes=8192,
    )
    assert run.status == "ok"
    assert run.output["applicability"] == "not_applicable"
    assert run.output["qc_items"] == []