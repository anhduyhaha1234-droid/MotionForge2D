"""S12-T06B Scenario F — 1080p->2160p labeled upscale + Native 4K control.

Acceptance thật (không waive):
- F1 (MEASURED): real ffmpeg upscale 1920x1080 -> 3840x2160; output ffprobe
  dims 3840x2160; preflight verdict source_kind == "upscale_4k" với
  upscale_method CÓ NHÃN; aspect preserve (DAR in == DAR out, không
  stretch/crop im lặng); output decode đủ frames + audio decode thật
  (mở/nghe output thật).
- F2 (MEASURED): Native 4K control — real 3840x2160 encode + provenance
  native_4k=True -> source_kind == "native_4k", upscale_method None;
  output decode đủ frames + audio decode thật.
- F3: phân biệt Native vs Upscale theo provenance (không chỉ kích thước
  file cuối) + ghi nhận hành vi dims-only fallback (F-OBS-01 -> owner T01).
- F4: aspect fail-closed (drift + fail_closed -> S12_EXPORT_ASPECT_MISMATCH,
  eligible False) và letterbox pass.

READ-ONLY production: chỉ gọi production, không sửa file production nào.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.s12_export import ExportPreflightRequest
from app.services.s12_export.preflight import (
    PreflightContext,
    classify_source_kind,
    evaluate_preflight,
)
from app.services.s12_export.stitch import count_video_frames
from app.services.s12_export.validation import (
    ValidationExpectation,
    validate,
)

from conftest import (  # type: ignore[import-not-found]
    UPSCALE_METHOD_LABEL,
    WS,
    build_native_4k,
    build_source_1080p,
    decode_audio_to_wav,
    make_request,
    ok_ctx,
    probe_dims,
    probe_has_audio,
    upscale_to_4k,
)

SRC_FRAMES = 30
SRC_DURATION = 3.0
NATIVE_FRAMES = 20
NATIVE_DURATION = 2.0


@pytest.mark.measured
def test_f1_upscale_1080p_to_2160_labeled(tmp_path: Path) -> None:
    src = build_source_1080p(tmp_path / "src1080.mp4")
    assert probe_dims(src) == (1920, 1080)
    assert probe_has_audio(src) is True

    out = tmp_path / "upscaled4k.mp4"
    method = upscale_to_4k(src, out)
    assert method == UPSCALE_METHOD_LABEL

    # Output thật 3840x2160, aspect preserve (DAR 16:9 cả hai đầu).
    out_w, out_h = probe_dims(out)
    assert (out_w, out_h) == (3840, 2160)
    assert abs((1920 / 1080) - (out_w / out_h)) < 1e-9

    # Preflight verdict: upscale_4k + method CÓ NHÃN (không stretch im lặng).
    req: ExportPreflightRequest = make_request(f"v-{WS}")
    ctx: PreflightContext = ok_ctx(upscale_method=method)
    resp = evaluate_preflight(req, ctx)
    assert resp.source_kind == "upscale_4k"
    assert resp.profile.upscale_method == UPSCALE_METHOD_LABEL
    assert resp.source_width == 1920
    assert resp.source_height == 1080
    aspect = [c for c in resp.checks if c.name == "aspect"]
    assert aspect and all(c.passed for c in aspect)

    # Mở output thật: decode đủ frames + validator resolution PASS.
    assert count_video_frames(out) == SRC_FRAMES
    verdict = validate(
        out,
        ValidationExpectation(
            width=3840,
            height=2160,
            codec="h264",
            audio_policy="required",
            expected_frame_count=SRC_FRAMES,
            expected_duration_sec=SRC_DURATION,
        ),
    )
    by_name = {p.name: p for p in verdict.probes}
    assert by_name["resolution"].verdict == "PASS"
    assert by_name["frame_count"].verdict == "PASS"
    assert by_name["av_policy"].verdict == "PASS"

    # Nghe output thật: audio decode ra wav có bytes thật.
    wav_size = decode_audio_to_wav(out, tmp_path / "up.wav")
    assert wav_size > 44 + 1000


@pytest.mark.measured
def test_f2_native_4k_control(tmp_path: Path) -> None:
    out = build_native_4k(tmp_path / "native4k.mp4")
    assert probe_dims(out) == (3840, 2160)
    assert probe_has_audio(out) is True

    req: ExportPreflightRequest = make_request(f"v-{WS}")
    ctx: PreflightContext = ok_ctx(
        source_width=3840,
        source_height=2160,
        source_frame_count=NATIVE_FRAMES,
        source_native_4k=True,
        upscale_method=None,
    )
    resp = evaluate_preflight(req, ctx)
    assert resp.source_kind == "native_4k"
    assert resp.profile.upscale_method is None

    assert count_video_frames(out) == NATIVE_FRAMES
    verdict = validate(
        out,
        ValidationExpectation(
            width=3840,
            height=2160,
            codec="h264",
            audio_policy="required",
            expected_frame_count=NATIVE_FRAMES,
            expected_duration_sec=NATIVE_DURATION,
        ),
    )
    by_name = {p.name: p for p in verdict.probes}
    assert by_name["resolution"].verdict == "PASS"
    assert by_name["frame_count"].verdict == "PASS"

    wav_size = decode_audio_to_wav(out, tmp_path / "nat.wav")
    assert wav_size > 44 + 1000


def test_f3_provenance_decides_not_filesize() -> None:
    """Native vs Upscale theo provenance, không chỉ kích thước file cuối."""
    upscale_ctx: PreflightContext = ok_ctx(
        source_width=1920,
        source_height=1080,
        source_native_4k=False,
        upscale_method=UPSCALE_METHOD_LABEL,
    )
    native_ctx: PreflightContext = ok_ctx(
        source_width=3840,
        source_height=2160,
        source_native_4k=True,
        upscale_method=None,
    )
    assert classify_source_kind(upscale_ctx) == "upscale_4k"
    assert classify_source_kind(native_ctx) == "native_4k"

    # F-OBS-01 CLOSED by T01-C1 (commit 0d5bc77): bare 3840x2160 dims
    # WITHOUT proved provenance now classify "upscale_4k"
    # (already-upscaled-4K honesty), never "native_4k".  Dims alone never
    # imply native — "file size alone never decides".
    bare_ctx: PreflightContext = ok_ctx(
        source_width=3840,
        source_height=2160,
        source_native_4k=False,
        upscale_method=None,
    )
    assert classify_source_kind(bare_ctx) == "upscale_4k"  # F-OBS-01 closed


def test_f4_aspect_fail_closed_and_letterbox() -> None:
    """Drift DAR + fail_closed -> MISMATCH/eligible False; letterbox pass."""
    drifted = {"source_width": 1440, "source_height": 1080}  # 4:3 vs 16:9

    req_fail: ExportPreflightRequest = make_request(
        f"v-{WS}", aspect_handling="fail_closed"
    )
    resp_fail = evaluate_preflight(req_fail, ok_ctx(**drifted))
    assert resp_fail.eligible is False
    assert "S12_EXPORT_ASPECT_MISMATCH" in list(resp_fail.reasons)
    aspect_fail = [c for c in resp_fail.checks if c.name == "aspect"]
    assert aspect_fail and all(not c.passed for c in aspect_fail)

    req_lb: ExportPreflightRequest = make_request(
        f"v-{WS}", aspect_handling="letterbox"
    )
    resp_lb = evaluate_preflight(req_lb, ok_ctx(**drifted))
    aspect_lb = [c for c in resp_lb.checks if c.name == "aspect"]
    assert aspect_lb and all(c.passed for c in aspect_lb)
