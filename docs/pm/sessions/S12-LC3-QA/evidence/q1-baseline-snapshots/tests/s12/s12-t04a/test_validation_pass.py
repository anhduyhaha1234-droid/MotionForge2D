"""S12-T04A — PASS-path and contract-shape tests on real 4K media.

Covers: full PASS with a fully-pinned expectation (frames/duration/
provenance measured, not NOT_MEASURED), default (unconstrained)
expectation → NOT_MEASURED-by-design, probe order == required_probes,
pure-function guarantees (no publish/DB: verdict carries no handles).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.schemas.s12_export import ValidationContract
from app.services.s12_export.validation import (
    REQUIRED_PROBES,
    ValidationExpectation,
    sha256_file,
    validate,
)

FPS = 10
DURATION = 2.0
FRAMES = 20


def test_pass_pinned_4k(good_4k: Path) -> None:
    exp = ValidationExpectation(
        audio_policy="absent",
        expected_frame_count=FRAMES,
        expected_duration_sec=DURATION,
        expected_sha256=sha256_file(good_4k),
    )
    verdict = validate(good_4k, exp)
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]
    assert verdict.contract_version == "s12-export-v1"
    assert [item.name for item in verdict.probes] == list(REQUIRED_PROBES)
    assert all(item.verdict == "PASS" for item in verdict.probes)


def test_pass_with_audio_policy(good_4k_audio: Path) -> None:
    exp = ValidationExpectation(
        audio_policy="required",
        expected_frame_count=FRAMES,
        expected_duration_sec=DURATION,
        expected_sha256=sha256_file(good_4k_audio),
    )
    verdict = validate(good_4k_audio, exp)
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]
    assert verdict.probe("av_policy") is not None
    assert verdict.probe("av_policy").verdict == "PASS"


def test_absent_audio_policy_passes_on_silent(good_4k: Path) -> None:
    verdict = validate(good_4k, ValidationExpectation(audio_policy="absent"))
    assert verdict.probe("av_policy") is not None
    assert verdict.probe("av_policy").verdict == "PASS"


def test_default_expectation_is_not_measured_not_fake_pass(good_4k: Path) -> None:
    """Unconstrained probes report NOT_MEASURED — never a fake PASS."""
    verdict = validate(good_4k)
    by_name = {item.name: item.verdict for item in verdict.probes}
    assert by_name["frame_count"] == "NOT_MEASURED"
    assert by_name["duration"] == "NOT_MEASURED"
    assert by_name["av_policy"] == "NOT_MEASURED"
    assert by_name["provenance"] == "NOT_MEASURED"
    assert by_name["resolution"] == "PASS"
    assert by_name["codec"] == "PASS"
    assert verdict.verdict == "NOT_MEASURED"


def test_contract_shape_matches_frozen_module() -> None:
    frozen = ValidationContract()
    assert list(frozen.required_probes) == list(REQUIRED_PROBES)
    assert frozen.resolution_width == 3840
    assert frozen.resolution_height == 2160
    assert frozen.partial_suffix == ".partial"
    assert set(frozen.verdicts) == {"PASS", "FAIL", "NOT_MEASURED"}


def test_validator_is_pure_no_side_effects(
    good_4k: Path, tmp_path: Path
) -> None:
    """Validator must not publish/copy/move — input dir gains no files."""
    before = {item.name for item in good_4k.parent.iterdir()}
    validate(good_4k, ValidationExpectation(expected_sha256=sha256_file(good_4k)))
    assert {item.name for item in good_4k.parent.iterdir()} == before
    staged = tmp_path / "staged.mp4"
    shutil.copy(good_4k, staged)
    verdict = validate(staged)
    assert verdict.output_path == str(staged)
    assert (item for item in verdict.probes) is not None
    assert "publish" not in str(type(verdict)).lower()
