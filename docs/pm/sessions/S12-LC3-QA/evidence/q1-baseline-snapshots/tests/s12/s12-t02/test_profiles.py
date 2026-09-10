"""S12-T02 — render profile resolution tests (fail-closed, basis-stated).

Pure unit rows use hand-built :class:`CapabilityReport` doubles (injected
probes, short tmp roots only for spawn rows); nothing touches the T01
contract modules, DB, ports or network.
"""

from __future__ import annotations

from app.services.s12_export.capabilities import (
    CapabilityReport,
    EncoderProbe,
)
from app.services.s12_export.profiles import (
    RENDER_PROFILES,
    ResolvedProfile,
    estimate_for_profile,
    resolve_all_profiles,
    resolve_profile,
)


def _probe(encoder: str, codec: str, ok: bool, reason: str = "encoder_ok",
           detail: str = "probe detail", out: int = 4000) -> EncoderProbe:
    kind = "cpu" if encoder in ("libx264", "libx265") else "gpu"
    return EncoderProbe(encoder, codec, kind, ok, reason, detail, 10,
                        out if ok else 0)


def _report(probes: list[EncoderProbe], gpu_free: int | None = 4096) -> CapabilityReport:
    return CapabilityReport("ffmpeg", "ffmpeg version test", tuple(probes),
                            "Test GPU", 8192, gpu_free, ())


def _full_cpu() -> CapabilityReport:
    return _report([_probe("libx264", "h264", True),
                    _probe("libx265", "hevc", True)])


def test_frozen_dims_match_t01() -> None:
    assert RENDER_PROFILES["master-4k-h264"] == {"width": 3840, "height": 2160,
                                                "codec": "h264"}
    assert RENDER_PROFILES["master-4k-hevc"] == {"width": 3840, "height": 2160,
                                                "codec": "hevc"}
    assert RENDER_PROFILES["preview-1080p-h264"] == {"width": 1920, "height": 1080,
                                                    "codec": "h264"}


def test_cpu_baseline_always_resolves() -> None:
    resolved = resolve_profile("preview-1080p-h264", _full_cpu())
    assert resolved.supported is True
    assert resolved.path == "cpu" and resolved.encoder == "libx264"
    assert resolved.reason == "S12_EXPORT_OK"
    assert "spawn-probe" in resolved.support_basis


def test_hevc_needs_verified_probe() -> None:
    report = _report([_probe("libx264", "h264", True),
                      _probe("libx265", "hevc", False, "encoder_failed",
                             "exit 1: libx265 missing")])
    resolved = resolve_profile("master-4k-hevc", report)
    assert resolved.supported is False
    assert resolved.reason == "S12_EXPORT_UNSUPPORTED_PROFILE"
    assert "encoder_failed" in resolved.support_basis


def test_unknown_profile_fail_closed() -> None:
    resolved = resolve_profile("nope-8k-av1", _full_cpu())
    assert resolved.supported is False
    assert resolved.reason == "S12_EXPORT_UNSUPPORTED_PROFILE"


def test_aspect_mismatch_fail_closed_vs_letterbox() -> None:
    # Source 4:3 (640x480) vs 16:9 target → drift ~33%.
    closed = resolve_profile("preview-1080p-h264", _full_cpu(),
                             source_width=640, source_height=480,
                             aspect_handling="fail_closed")
    assert closed.supported is False
    assert closed.reason == "S12_EXPORT_ASPECT_MISMATCH"

    boxed = resolve_profile("preview-1080p-h264", _full_cpu(),
                            source_width=640, source_height=480,
                            aspect_handling="letterbox")
    assert boxed.supported is True
    assert "letterbox" in boxed.support_basis or "drift" in boxed.support_basis


def test_passthrough_aspect_match_ok() -> None:
    ok = resolve_profile("preview-1080p-h264", _full_cpu(),
                         source_width=1920, source_height=1080,
                         aspect_handling="passthrough")
    assert ok.supported is True


def test_prefer_gpu_without_gpu_probe_falls_back_cpu() -> None:
    resolved = resolve_profile("master-4k-h264", _full_cpu(), prefer_gpu=True)
    assert resolved.supported is True
    assert resolved.path == "cpu" and resolved.encoder == "libx264"
    assert "CPU fallback" in resolved.support_basis


def test_prefer_gpu_with_verified_gpu_encoder() -> None:
    report = _report([_probe("libx264", "h264", True),
                      _probe("h264_nvenc", "h264", True, out=3000)])
    resolved = resolve_profile("master-4k-h264", report, prefer_gpu=True)
    assert resolved.supported is True
    assert resolved.path == "gpu" and resolved.encoder == "h264_nvenc"
    assert resolved.cpu_fallback_encoder == "libx264"


def test_prefer_gpu_vram_insufficient_falls_back() -> None:
    report = _report([_probe("libx264", "h264", True),
                      _probe("h264_nvenc", "h264", True, out=3000)], gpu_free=100)
    resolved = resolve_profile("master-4k-h264", report, prefer_gpu=True)
    assert resolved.path == "cpu" and resolved.encoder == "libx264"
    assert "vram_insufficient" in resolved.support_basis


def test_prefer_gpu_absent_gpu_falls_back() -> None:
    report = _report([_probe("libx264", "h264", True),
                      _probe("h264_nvenc", "h264", True, out=3000)], gpu_free=None)
    resolved = resolve_profile("master-4k-h264", report, prefer_gpu=True)
    assert resolved.path == "cpu"
    assert "gpu_absent" in resolved.support_basis


def test_prefer_gpu_no_cpu_encoder_unsupported() -> None:
    report = _report([_probe("libx264", "h264", False, "encoder_failed", "no x264"),
                      _probe("h264_nvenc", "h264", False, "encoder_not_in_build",
                             "absent")], gpu_free=None)
    resolved = resolve_profile("master-4k-h264", report, prefer_gpu=True)
    assert resolved.supported is False
    assert resolved.reason == "S12_EXPORT_UNSUPPORTED_PROFILE"


def test_resolve_all_covers_frozen_table() -> None:
    allp = resolve_all_profiles(_full_cpu())
    assert set(allp) == {"master-4k-h264", "master-4k-hevc", "preview-1080p-h264"}
    assert all(r.supported for r in allp.values())


def test_estimate_formula_measured_basis() -> None:
    report = _full_cpu()
    resolved = resolve_profile("preview-1080p-h264", report)
    total, basis = estimate_for_profile(resolved, 300, report)
    # measured libx264 probe: 4000B / (128*72*5f) = 0.0868 B/px
    expected = int(1920 * 1080 * 300 * (4000 / (128 * 72 * 5)))
    assert total == expected
    assert "measured libx264 probe" in basis
    assert basis.startswith("estimate 1920x1080x300f")


def test_estimate_unknown_frames_fail_closed() -> None:
    report = _full_cpu()
    resolved = resolve_profile("master-4k-h264", report)
    total, basis = estimate_for_profile(resolved, None, report)
    assert total is None
    assert "fail-closed" in basis


def test_estimate_heuristic_without_probe() -> None:
    resolved = ResolvedProfile("master-4k-h264", 3840, 2160, "h264", "cpu",
                               None, True, "manual", None, "S12_EXPORT_OK")
    total, basis = estimate_for_profile(resolved, 100, None)
    assert total == int(3840 * 2160 * 100 * 0.5)
    assert "T01 heuristic" in basis


def test_estimate_bpp_clamped() -> None:
    # Absurd 100MB probe on 128x72x5 must clamp to 2.0 B/px, not explode.
    report = _report([_probe("libx264", "h264", True, out=100_000_000)])
    resolved = resolve_profile("preview-1080p-h264", report)
    total, basis = estimate_for_profile(resolved, 10, report)
    assert total == int(1920 * 1080 * 10 * 2.0)
    assert "clamped" in basis


def test_export_fields_fit_t01_schema() -> None:
    fields = resolve_profile("master-4k-h264", _full_cpu()).as_export_fields()
    from app.schemas.s12_export import ExportProfile

    ExportProfile(**fields)  # must validate under frozen strict schema
