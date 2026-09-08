"""S12-C1 C19 — validator negative matrix (T04A owner).

Every corruption family maps to FAIL (or NOT_MEASURED where the evidence
is genuinely insufficient), never a fake PASS — and never a self-hash
PASS (proving identity against a hash taken from the SAME bytes is
circular; provenance PASS requires the manifest's independent hash).

Isolated: session media built once with real ffmpeg; every mutation
copies into its own ``tmp_path`` first so shared media stays pristine.
Basetemp short/unique; no DB; validator is pure (no publish).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services.s12_export.validation import (
    ValidationExpectation,
    sha256_file,
    validate,
)

from conftest import _DURATION as DURATION
from conftest import _FPS as FPS
from conftest import build_media

FRAMES = int(FPS * DURATION)


def _copy(src: Path, tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copy(src, dest)
    return dest


def _pinned(src: Path, **overrides) -> ValidationExpectation:
    base: dict = {
        "audio_policy": "absent",
        "expected_frame_count": FRAMES,
        "expected_duration_sec": DURATION,
        "expected_fps": float(FPS),
        "expected_sha256": sha256_file(src),
    }
    base.update(overrides)
    return ValidationExpectation(**base)


# ── C19 control: full PASS reference ──────────────────────────────────


def test_c19_control_pass(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k))
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


# ── corrupt / truncate ────────────────────────────────────────────────


def test_c19_truncate_half_fails(good_4k: Path, tmp_path: Path) -> None:
    target = _copy(good_4k, tmp_path, "trunc.mp4")
    with open(target, "r+b") as handle:
        handle.truncate(target.stat().st_size // 2)
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict == "FAIL"


def test_c19_mid_bytes_corrupt_no_pass(good_4k: Path, tmp_path: Path) -> None:
    target = _copy(good_4k, tmp_path, "corrupt.mp4")
    with open(target, "r+b") as handle:
        handle.seek(4096)
        handle.write(b"\x00" * 8192)
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict in ("FAIL", "NOT_MEASURED")
    assert verdict.verdict != "PASS"


def test_c19_header_corrupt_fails(good_4k: Path, tmp_path: Path) -> None:
    target = _copy(good_4k, tmp_path, "hdr.mp4")
    with open(target, "r+b") as handle:
        handle.seek(0)
        handle.write(b"\x00" * 64)
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness") is not None
    assert verdict.probe("completeness").verdict == "FAIL"


# ── dims / codec / streams ────────────────────────────────────────────


def test_c19_wrong_dims_fails(small_1080: Path) -> None:
    verdict = validate(
        small_1080,
        ValidationExpectation(
            audio_policy="absent", expected_sha256=sha256_file(small_1080)
        ),
    )
    assert verdict.probe("resolution").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_codec_mismatch_fails(tiny_hevc: Path) -> None:
    verdict = validate(
        tiny_hevc, ValidationExpectation(codec="h264", width=320, height=180)
    )
    assert verdict.probe("codec").verdict == "FAIL"
    assert verdict.verdict != "PASS"


def test_c19_non_media_bytes_fail(tmp_path: Path) -> None:
    target = tmp_path / "junk.mp4"
    target.write_bytes(b"not a container" * 512)
    verdict = validate(target)
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness").verdict == "FAIL"


# ── count: missing chunk / extra chunk ────────────────────────────────


def test_c19_missing_chunk_fails(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k, expected_frame_count=FRAMES + 8))
    assert verdict.probe("frame_count").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_extra_chunk_fails(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k, expected_frame_count=FRAMES - 4))
    assert verdict.probe("frame_count").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


# ── cut / timing ──────────────────────────────────────────────────────


def test_c19_cut_without_keyframe_fails(good_4k: Path) -> None:
    """A manifest cut landing mid-GOP (no keyframe) must FAIL frame_order."""
    verdict = validate(good_4k, _pinned(good_4k, expected_cuts=(1.0,)))
    order = [item for item in verdict.probes if item.name == "frame_order"]
    assert any(item.verdict == "FAIL" for item in order), [
        (item.verdict, item.detail) for item in order
    ]
    assert verdict.verdict == "FAIL"


def test_c19_cut_on_keyframe_passes(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k, expected_cuts=(0.0,)))
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c19_duration_drift_fails(good_4k: Path) -> None:
    verdict = validate(
        good_4k, _pinned(good_4k, expected_duration_sec=DURATION + 30.0)
    )
    assert verdict.probe("duration").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_fps_mismatch_fails(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k, expected_fps=25.0))
    assert verdict.probe("timebase").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


# ── audio policy ──────────────────────────────────────────────────────


def test_c19_audio_required_on_silent_fails(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k, audio_policy="required"))
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_audio_present_policy_absent_fails(good_4k_audio: Path) -> None:
    exp = ValidationExpectation(
        audio_policy="absent",
        expected_frame_count=FRAMES,
        expected_duration_sec=DURATION,
        expected_fps=float(FPS),
        expected_sha256=sha256_file(good_4k_audio),
    )
    verdict = validate(good_4k_audio, exp)
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


# ── provenance: never self-hash PASS ──────────────────────────────────


def test_c19_wrong_hash_fails(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k, expected_sha256="0" * 64))
    assert verdict.probe("provenance").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_self_hash_is_circular_and_rejected(
    good_4k: Path, tmp_path: Path
) -> None:
    """Hashing the MUTATED bytes and pinning that hash must still FAIL.

    A 1s sub-clip (10 frames) hashed by itself: provenance PASS is
    circular and insufficient — the manifest's count/duration evidence
    (20 frames / 2s) mismatches, so the overall verdict can never be
    PASS from self-hash alone.
    """
    import subprocess

    import shutil as _shutil

    ffmpeg = _shutil.which("ffmpeg")
    assert ffmpeg is not None
    sub = tmp_path / "subclip.mp4"
    rc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(good_4k), "-t", "1.0", "-c", "copy", str(sub)],
        capture_output=True,
        timeout=300,
    )
    assert rc.returncode == 0
    self_hash = sha256_file(sub)
    verdict = validate(
        sub,
        ValidationExpectation(
            audio_policy="absent",
            expected_frame_count=FRAMES,
            expected_duration_sec=DURATION,
            expected_fps=float(FPS),
            expected_sha256=self_hash,
        ),
    )
    assert verdict.probe("provenance") is not None
    assert verdict.probe("provenance").verdict == "PASS"  # hash matches itself
    assert verdict.verdict == "FAIL"  # ...but evidence mismatch fails overall


# ── .partial ───────────────────────────────────────────────────────────


def test_c19_partial_suffix_never_completed(
    good_4k: Path, tmp_path: Path
) -> None:
    target = _copy(good_4k, tmp_path, "final.mp4.partial")
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness").verdict == "FAIL"


# ── C12 T04A-part: source-locked seams ────────────────────────────────


def test_c12_seam_stitch_correct_order_passes(
    media_root: Path, tmp_path: Path
) -> None:
    """A+B stitched in order validates: cuts keyframe-locked, CFR exact."""
    import shutil as _shutil
    import subprocess as _sp

    ffmpeg = _shutil.which("ffmpeg")
    assert ffmpeg is not None
    chunk_a = build_media(
        media_root / "seam_a.mp4", width=3840, height=2160, duration=1.0
    )
    chunk_b = build_media(
        media_root / "seam_b.mp4", width=3840, height=2160, duration=1.0
    )
    lst = tmp_path / "seam.txt"
    lst.write_text(f"file '{chunk_a}'\nfile '{chunk_b}'\n")
    stitched = tmp_path / "stitched.mp4"
    rc = _sp.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", str(lst), "-c", "copy", str(stitched)],
        capture_output=True,
        timeout=300,
    )
    assert rc.returncode == 0
    verdict = validate(
        stitched,
        ValidationExpectation(
            audio_policy="absent",
            expected_frame_count=FRAMES,
            expected_duration_sec=DURATION,
            expected_fps=float(FPS),
            expected_cuts=(0.0, 1.0),
            expected_sha256=sha256_file(stitched),
        ),
    )
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c12_vfr_rejected_pre_work(
    good_4k: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """r_frame_rate != avg_frame_rate → timebase FAIL (VFR rejected)."""
    import app.services.s12_export.validation as _v

    real_json = _v._ffprobe_json

    def _vfr(path: Path) -> dict | None:
        payload = real_json(path)
        assert payload is not None
        for stream in payload.get("streams", []):
            if stream.get("codec_type") == "video":
                stream["r_frame_rate"] = "15/1"
                stream["avg_frame_rate"] = "10/1"
        return payload

    monkeypatch.setattr(_v, "_ffprobe_json", _vfr)
    verdict = validate(good_4k, _pinned(good_4k))
    assert verdict.probe("timebase") is not None
    assert verdict.probe("timebase").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c12_cfr_control_matches_manifest(good_4k: Path) -> None:
    verdict = validate(good_4k, _pinned(good_4k))
    assert verdict.probe("timebase") is not None
    assert verdict.probe("timebase").verdict == "PASS"


# ── order: reordered timestamps ───────────────────────────────────────


def test_c19_reordered_container_fails(
    media_root: Path, tmp_path: Path
) -> None:
    """Two-chunk concat in swapped order decodes but violates the manifest.

    Chunk A (0-1s) + chunk B (1-2s) stitched B+A: same count, wrong order
    evidence — frame_count matches but duration/cuts pinned to A+B fail.
    """
    chunk_a = build_media(
        media_root / "ord_a.mp4", width=3840, height=2160, duration=1.0
    )
    chunk_b = build_media(
        media_root / "ord_b.mp4", width=3840, height=2160, duration=1.0
    )
    import subprocess

    ffmpeg = __import__("shutil").which("ffmpeg")
    lst = tmp_path / "lst.txt"
    lst.write_text(f"file '{chunk_b}'\nfile '{chunk_a}'\n")
    swapped = tmp_path / "swapped.mp4"
    rc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", str(lst), "-c", "copy", str(swapped)],
        capture_output=True,
        timeout=300,
    )
    assert rc.returncode == 0
    verdict = validate(
        swapped,
        ValidationExpectation(
            audio_policy="absent",
            expected_frame_count=FRAMES,
            expected_duration_sec=DURATION,
            expected_fps=float(FPS),
            expected_cuts=(0.0, 1.0),
            expected_sha256=sha256_file(chunk_a),
        ),
    )
    # provenance pinned to chunk A cannot match the B+A stitch → FAIL
    assert verdict.probe("provenance").verdict == "FAIL"
    assert verdict.verdict == "FAIL"
