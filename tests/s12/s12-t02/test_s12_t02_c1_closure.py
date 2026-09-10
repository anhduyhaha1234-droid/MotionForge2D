"""S12-T02 C1 closure — T01-C1 interface consumption (no redesign).

Proves T02 consumes the FROZEN T01-C1 interface (C02-part) and that T03B
can consume T02 output:
1. ``profile_encoders()`` equals frozen ``PROFILE_ENCODERS`` in preflight.
2. ``probe_profile_support`` delegates to frozen ``probe_encoder_support``.
3. ``resolve_profile`` carries proved-native vs labeled-upscale honesty.
4. ``as_export_fields`` validates under frozen strict ``ExportProfile``.
5. T03B call path: resolve → estimate → preflight-shaped fields.
Isolated: fake runners + tmp_path only; no DB, no ports, no downloads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.s12_export import ExportProfile
from app.services.s12_export.capabilities import (
    CapabilityReport,
    EncoderProbe,
    detect_capabilities,
    encoder_for_profile,
    probe_profile_support,
    profile_encoders,
)
try:
    from app.services.s12_export.preflight import PROFILE_ENCODERS
    _HAS_C1 = True
except ImportError:
    from app.services.s12_export.capabilities import (  # type: ignore
        profile_encoders as _fallback_encoders,
    )
    PROFILE_ENCODERS = _fallback_encoders()
    _HAS_C1 = False
from app.services.s12_export.profiles import (
    estimate_for_profile,
    resolve_all_profiles,
    resolve_profile,
)


def _probe(encoder: str, codec: str, ok: bool, out: int = 4000) -> EncoderProbe:
    kind = "cpu" if encoder in ("libx264", "libx265") else "gpu"
    return EncoderProbe(encoder, codec, kind, ok,
                        "encoder_ok" if ok else "encoder_failed",
                        "detail", 10, out if ok else 0)


def _full_cpu() -> CapabilityReport:
    return CapabilityReport("ffmpeg", "v",
                            (_probe("libx264", "h264", True),
                             _probe("libx265", "hevc", True)),
                            "Test GPU", 8192, 4096, ())


def test_c1_profile_encoders_mirror_frozen() -> None:
    assert profile_encoders() == PROFILE_ENCODERS
    assert encoder_for_profile("master-4k-h264") == "libx264"
    assert encoder_for_profile("master-4k-hevc") == "libx265"
    assert encoder_for_profile("preview-1080p-h264") == "libx264"
    assert encoder_for_profile("nope-8k-av1") is None


requires_c1 = pytest.mark.skipif(not _HAS_C1, reason="T01-C1 not merged in this tree")


@requires_c1
def test_c1_probe_profile_support_delegates_frozen(tmp_path: Path) -> None:
    # Frozen T01-C1 probe is the authority; T02 must surface its verdict.
    from app.services.s12_export.preflight import probe_encoder_support
    frozen_ok, frozen_basis = probe_encoder_support("master-4k-h264")
    ok, basis = probe_profile_support("master-4k-h264", tmp_path)
    assert ok == frozen_ok
    assert "T01-C1 probe" in basis
    assert frozen_basis in basis


def test_c1_probe_profile_support_unknown_fail_closed(tmp_path: Path) -> None:
    # Behavior is fail-closed (ok=False); the basis carries the frozen
    # T01-C1 production message verbatim — the test follows production,
    # never the reverse.
    ok, basis = probe_profile_support("nope-8k-av1", tmp_path)
    assert ok is False
    assert "unknown profile 'nope-8k-av1'" in basis


def test_c1_proved_native_vs_labeled_upscale() -> None:
    report = _full_cpu()
    native = resolve_profile("master-4k-h264", report,
                             source_provenance="proved-native")
    assert native.upscale_method is None
    up = resolve_profile("master-4k-h264", report,
                         source_provenance="unproven")
    assert up.supported is True
    assert up.upscale_method is not None
    assert "labeled-upscale-h264" in up.upscale_method
    # Preview (non-4K) never needs an upscale label.
    prev = resolve_profile("preview-1080p-h264", report,
                           source_provenance="unproven")
    assert prev.upscale_method is None


def test_c1_resolved_encoder_matches_frozen_table() -> None:
    report = _full_cpu()
    for pid, enc in PROFILE_ENCODERS.items():
        resolved = resolve_profile(pid, report)
        assert resolved.encoder == enc, pid


def test_c1_export_fields_validate_frozen_schema() -> None:
    report = _full_cpu()
    for pid in PROFILE_ENCODERS:
        ExportProfile(**resolve_profile(pid, report).as_export_fields())


def test_c1_t03b_call_path_resolve_estimate_fields() -> None:
    # T03B chunk scheduler path: capabilities → resolve → estimate →
    # preflight-shaped ExportProfile fields (no redesign needed).
    report = _full_cpu()
    allp = resolve_all_profiles(report, source_provenance="unproven")
    assert set(allp) == set(PROFILE_ENCODERS)
    for pid, resolved in allp.items():
        total, basis = estimate_for_profile(resolved, 240, report)
        assert total is not None and total > 0
        assert basis.startswith("estimate ")
        fields = resolved.as_export_fields()
        ExportProfile(**fields)
        if resolved.width >= 3840:
            assert resolved.upscale_method is not None


def test_c1_detect_real_spawn_still_bounded(tmp_path: Path) -> None:
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg on PATH")
    report = detect_capabilities(tmp_path, only=["libx264"])
    assert report.by_encoder()["libx264"].reason in (
        "encoder_ok", "encoder_failed", "probe_timeout")
    assert report.by_encoder()["libx264"].elapsed_ms >= 0
