"""S12-T04A — unit tests: aggregate rules, edge inputs, helper purity."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.s12_export import validation as module
from app.services.s12_export.validation import (
    REQUIRED_PROBES,
    ValidationExpectation,
    validate,
)


def test_probe_order_covers_all_required_probes() -> None:
    assert len(REQUIRED_PROBES) == 10
    assert set(REQUIRED_PROBES) == {
        "resolution",
        "codec",
        "streams",
        "frame_count",
        "frame_order",
        "timebase",
        "duration",
        "av_policy",
        "provenance",
        "completeness",
    }


def test_bad_audio_policy_is_fail_closed(good_4k: Path) -> None:
    verdict = validate(
        good_4k, ValidationExpectation(audio_policy="sometimes")  # type: ignore[arg-type]
    )
    assert verdict.probe("av_policy") is not None
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_non_media_file_fails_completeness(tmp_path: Path) -> None:
    target = tmp_path / "notes.mp4"
    target.write_bytes(b"this is not a media container" * 100)
    verdict = validate(target)
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness").verdict == "FAIL"


def test_directory_path_fails(tmp_path: Path) -> None:
    verdict = validate(tmp_path)
    assert verdict.verdict == "FAIL"
    assert verdict.probe("completeness").verdict == "FAIL"


def test_parse_rate_branches() -> None:
    assert module._parse_rate("10/1") == 10.0
    assert module._parse_rate("30000/1001") == pytest.approx(29.97, abs=0.01)
    assert module._parse_rate("0/1") is None
    assert module._parse_rate("10/0") is None
    assert module._parse_rate("nonsense") is None
    assert module._parse_rate(None) is None


def test_verdict_probe_lookup_miss(good_4k: Path) -> None:
    verdict = validate(good_4k)
    assert verdict.probe("no_such_probe") is None
