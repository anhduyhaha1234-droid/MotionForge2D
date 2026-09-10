"""S12-T04A — real-media negative controls (no fake PASS allowed).

Truncate/corrupt, wrong dimension, codec mismatch, timing mismatch,
missing/extra chunk (frame count), audio-policy breach, sha256 mismatch,
.partial suffix, missing path — every control must FAIL (or
NOT_MEASURED where evidence is insufficient) and never PASS.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.services.s12_export.validation import (
    ValidationExpectation,
    sha256_file,
    validate,
)

FRAMES = 20
DURATION = 2.0


def _copy(src: Path, tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copy(src, dest)
    return dest


def _pinned(src: Path, **overrides) -> ValidationExpectation:
    base = {
        "expected_frame_count": FRAMES,
        "expected_duration_sec": DURATION,
        "expected_sha256": sha256_file(src),
    }
    base.update(overrides)
    return ValidationExpectation(**base)


def test_missing_path_fails(tmp_path: Path) -> None:
    verdict = validate(tmp_path / "nope.mp4")
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness") is not None
    assert verdict.probe("completeness").verdict == "FAIL"


def test_truncated_media_fails(good_4k: Path, tmp_path: Path) -> None:
    target = _copy(good_4k, tmp_path, "truncated.mp4")
    size = target.stat().st_size
    with open(target, "r+b") as handle:
        handle.truncate(size // 2)
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict == "FAIL", [
        (item.name, item.verdict) for item in verdict.probes
    ]


def test_corrupt_bytes_fail(good_4k: Path, tmp_path: Path) -> None:
    target = _copy(good_4k, tmp_path, "corrupt.mp4")
    with open(target, "r+b") as handle:
        handle.seek(1024)
        handle.write(b"\x00" * 4096)
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict in ("FAIL", "NOT_MEASURED")
    assert verdict.verdict != "PASS"


def test_zero_byte_file_fails(tmp_path: Path) -> None:
    target = tmp_path / "empty.mp4"
    target.write_bytes(b"")
    verdict = validate(target)
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness").verdict == "FAIL"


def test_wrong_dimension_fails(small_1080: Path) -> None:
    verdict = validate(
        small_1080,
        ValidationExpectation(expected_sha256=sha256_file(small_1080)),
    )
    assert verdict.probe("resolution").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_codec_mismatch_fails(tiny_hevc: Path) -> None:
    verdict = validate(
        tiny_hevc, ValidationExpectation(codec="h264", width=320, height=180)
    )
    assert verdict.probe("codec").verdict == "FAIL"
    assert verdict.verdict != "PASS"


def test_codec_match_hevc_passes_shape(tiny_hevc: Path) -> None:
    verdict = validate(
        tiny_hevc,
        ValidationExpectation(
            codec="hevc",
            width=320,
            height=180,
            expected_sha256=sha256_file(tiny_hevc),
        ),
    )
    assert verdict.probe("codec").verdict == "PASS"
    assert verdict.probe("resolution").verdict == "PASS"


def test_timing_mismatch_fails(good_4k: Path) -> None:
    verdict = validate(
        good_4k, _pinned(good_4k, expected_duration_sec=DURATION + 30.0)
    )
    assert verdict.probe("duration").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_missing_chunk_fails_frame_count(good_4k: Path) -> None:
    """Fewer decoded frames than the manifest count → FAIL."""
    verdict = validate(good_4k, _pinned(good_4k, expected_frame_count=FRAMES + 10))
    assert verdict.probe("frame_count").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_extra_chunk_fails_frame_count(good_4k: Path) -> None:
    """Manifest count below decoded frames → FAIL (extra chunk)."""
    verdict = validate(good_4k, _pinned(good_4k, expected_frame_count=FRAMES - 5))
    assert verdict.probe("frame_count").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_audio_required_but_silent_fails(good_4k: Path) -> None:
    verdict = validate(
        good_4k, _pinned(good_4k, audio_policy="required")
    )
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_audio_present_but_policy_absent_fails(good_4k_audio: Path) -> None:
    verdict = validate(
        good_4k_audio,
        ValidationExpectation(
            audio_policy="absent",
            expected_frame_count=FRAMES,
            expected_duration_sec=DURATION,
            expected_sha256=sha256_file(good_4k_audio),
        ),
    )
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_sha256_mismatch_fails(good_4k: Path) -> None:
    verdict = validate(
        good_4k, _pinned(good_4k, expected_sha256="0" * 64)
    )
    assert verdict.probe("provenance").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_partial_suffix_never_completed(good_4k: Path, tmp_path: Path) -> None:
    target = _copy(good_4k, tmp_path, "final.mp4.partial")
    verdict = validate(target, _pinned(good_4k))
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness").verdict == "FAIL"
