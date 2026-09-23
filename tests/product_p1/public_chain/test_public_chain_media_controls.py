"""Retained R6/R7 media + output controls — RUNNABLE NOW.

LABELLING RULE (packet §2): everything this module generates is a **FIXTURE**
built by ffmpeg inside ``tmp_path``.  It is never presented as real product
media evidence, and no product/Comfy/provider/cloud endpoint is contacted —
the only I/O is the local ffmpeg/ffprobe binaries and the pure product
validator ``app.services.s12_export.validation.validate``.

Controls covered here: decoded PTS + exact frame count, audio presence/absence
and audio contract, partial output, corrupt output.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

LABEL = "FIXTURE"  # never "evidence": fixture media is not product evidence
FPS = 30
FRAMES = 60
WIDTH, HEIGHT = 320, 180


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


pytestmark = pytest.mark.skipif(
    not (_have("ffmpeg") and _have("ffprobe")),
    reason="ffmpeg/ffprobe unavailable on this host",
)


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


@pytest.fixture(scope="module")
def fixture_media(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("s12qa_fixture")
    path = root / "qa-fixture-2s.mp4"
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ]
    )
    assert result.returncode == 0, f"fixture generation failed: {result.stderr}"
    # pitfall: exit 0 with no file must be treated as failure
    assert path.is_file() and path.stat().st_size > 0, "fixture ffmpeg wrote no bytes"
    return path


def _probe_frames(path: Path) -> list[dict[str, Any]]:
    result = _run(
        [
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-select_streams", "v:0", "-show_entries", "frame=pts_time,pkt_pts_time,best_effort_timestamp_time",
            "-of", "json", str(path),
        ]
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout).get("frames", [])


def _probe_streams(path: Path) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-show_entries", "stream=codec_type,codec_name,channels,sample_rate,width,height,avg_frame_rate,nb_frames",
            "-show_entries", "format=duration,size",
            "-of", "json", str(path),
        ]
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_decoded_pts_monotonic_and_frame_count(fixture_media: Path) -> None:
    frames = _probe_frames(fixture_media)
    pts = [float(f["pts_time"]) for f in frames if f.get("pts_time") not in (None, "N/A")]
    assert len(pts) == FRAMES, f"{LABEL}: expected {FRAMES} decoded frames, measured {len(pts)}"
    assert pts == sorted(pts), f"{LABEL}: decoded PTS not monotonic: {pts[:8]}..."
    assert len(set(pts)) == len(pts), f"{LABEL}: duplicate decoded PTS (VFR/reorder signal)"
    assert pts[0] == pytest.approx(0.0, abs=1e-6), f"{LABEL}: first decoded PTS {pts[0]}"
    # CFR: every frame delta is one frame duration (ffprobe prints rounded
    # 1/30 as 0.033333/0.033334, so compare with a rational tolerance).
    expected_delta = 1.0 / FPS
    deltas = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
    worst = max(abs(delta - expected_delta) for delta in deltas)
    assert worst <= 1e-4, f"{LABEL}: CFR violated, worst delta error {worst:.6f}s"

    # Independent second method: real decode (not container metadata).
    import cv2

    capture = cv2.VideoCapture(str(fixture_media))
    decoded = 0
    while True:
        ok, _ = capture.read()
        if not ok:
            break
        decoded += 1
    capture.release()
    assert decoded == FRAMES, f"{LABEL}: cv2 decoded {decoded} frames, expected {FRAMES}"


def test_audio_contract_and_absence_detected(fixture_media: Path) -> None:
    from app.services.s12_export.validation import ValidationExpectation, validate

    inventory = _probe_streams(fixture_media)
    streams = inventory["streams"]
    video = [s for s in streams if s["codec_type"] == "video"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert video and video[0]["codec_name"] == "h264", f"{LABEL}: {video}"
    assert audio, f"{LABEL}: fixture must carry audio for this control"
    assert audio[0]["codec_name"] == "aac", f"{LABEL}: {audio[0]}"
    assert int(audio[0]["sample_rate"]) == 48000, f"{LABEL}: {audio[0]}"

    verdict = validate(
        fixture_media,
        ValidationExpectation(
            width=WIDTH,
            height=HEIGHT,
            codec="h264",
            audio_policy="required",
            expected_frame_count=FRAMES,
            expected_duration_sec=2.0,
            expected_fps=float(FPS),
        ),
    )
    # The aggregate can legitimately report NOT_MEASURED for probes the
    # expectation does not assert (e.g. provenance without expected_sha256).
    # What must NEVER happen is a PASS reported for a FAILing probe.
    failed_probes = [(p.name, p.verdict, p.detail) for p in verdict.probes if p.verdict == "FAIL"]
    assert failed_probes == [], f"{LABEL}: product validator failed a conforming fixture: {failed_probes}"
    assert verdict.verdict in ("PASS", "NOT_MEASURED"), verdict.verdict
    passed = {p.name for p in verdict.probes if p.verdict == "PASS"}
    assert {"completeness", "resolution", "timebase"} <= passed, sorted(passed)

    # Audio-absence control: the same media validated as if it must be silent
    # must FAIL — a validator that cannot see absence is worthless.
    silent_verdict = validate(
        fixture_media,
        ValidationExpectation(
            width=WIDTH,
            height=HEIGHT,
            codec="h264",
            audio_policy="absent",
            expected_frame_count=FRAMES,
            expected_duration_sec=2.0,
            expected_fps=float(FPS),
        ),
    )
    assert silent_verdict.verdict == "FAIL", (
        f"{LABEL}: audio_policy=absent must fail on media that carries audio, got "
        f"{silent_verdict.verdict}: {[(p.name, p.verdict) for p in silent_verdict.probes]}"
    )


def test_partial_output_rejected_by_product_validator(fixture_media: Path, tmp_path: Path) -> None:
    from app.services.s12_export.validation import PARTIAL_SUFFIX, validate

    partial = tmp_path / f"qa-export.mp4{PARTIAL_SUFFIX}"
    partial.write_bytes(fixture_media.read_bytes())
    verdict = validate(partial)
    assert verdict.verdict == "FAIL", (
        f"a {PARTIAL_SUFFIX} path must fail completeness, got {verdict.verdict}"
    )
    assert any(p.name == "completeness" and p.verdict == "FAIL" for p in verdict.probes), [
        (p.name, p.verdict, p.detail) for p in verdict.probes
    ]

    truncated = tmp_path / "qa-export-truncated.mp4"
    data = fixture_media.read_bytes()
    truncated.write_bytes(data[: max(1, len(data) // 2)])
    truncated_verdict = validate(truncated)
    assert truncated_verdict.verdict == "FAIL", (
        f"a truncated output must not PASS: {truncated_verdict.verdict} "
        f"{[(p.name, p.verdict, p.detail) for p in truncated_verdict.probes]}"
    )


def test_corrupt_output_fails_closed(tmp_path: Path) -> None:
    from app.services.s12_export.validation import validate

    corrupt = tmp_path / "qa-export-corrupt.mp4"
    corrupt.write_bytes(b"NOT-A-CONTAINER" * 512)
    verdict = validate(corrupt)
    assert verdict.verdict == "FAIL", f"corrupt bytes must fail closed, got {verdict.verdict}"
    assert verdict.verdict != "PASS"

    missing = tmp_path / "qa-export-missing.mp4"
    missing_verdict = validate(missing)
    assert missing_verdict.verdict == "FAIL", "a missing output must fail closed, never PASS"


def test_fixture_labeling_is_explicit(fixture_media: Path) -> None:
    """Fixtures and real media evidence must never be conflated."""
    assert LABEL == "FIXTURE"
    assert "fixture" in fixture_media.name, fixture_media.name
    text = Path(__file__).read_text(encoding="utf-8")
    assert "never presented as real product" in text
