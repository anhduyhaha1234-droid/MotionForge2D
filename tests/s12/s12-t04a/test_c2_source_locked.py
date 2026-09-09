"""S12-C2 T04A — source-locked validator tests (F07/C12/C19/C28 consumers).

Independent immutable reference evidence (frame digests, exact rational
fps, cuts, approved audio digest) is supplied from fixtures built BEFORE
the candidate; monotonic PTS/keyframes/audio presence/self-hash alone
must never PASS. Missing authority → FAIL/NOT_MEASURED.

Media is real ffmpeg output in isolated roots; every candidate is a
separate file from its reference so hashes/digests are never circular.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.s12_export.validation import (
    AudioReference,
    CutPoint,
    SourceReference,
    ValidationExpectation,
    probe_audio_digest,
    probe_frame_digests,
    sha256_file,
    validate,
)

from conftest import _DURATION as DURATION
from conftest import _FPS as FPS
from conftest import build_media

FRAMES = int(FPS * DURATION)
W, H = 320, 180


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    assert found is not None, "ffmpeg required for source-locked media"
    return found


def _media(dest: Path, pattern: str, *, audio_hz: int | None = None,
           duration: float = 1.0) -> Path:
    """Encode one 320x180 10fps segment (different content patterns)."""
    cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i",
           f"{pattern}=size={W}x{H}:rate={FPS}:duration={duration}"]
    if audio_hz is not None:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={audio_hz}:duration={duration}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio_hz is not None:
        cmd += ["-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(dest))
    rc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert rc.returncode == 0, rc.stderr[-400:]
    assert dest.is_file()
    return dest


def _concat(parts: list[Path], dest: Path) -> Path:
    lst = dest.with_suffix(".lst.txt")
    lst.write_text("".join(f"file '{part}'\n" for part in parts))
    rc = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         str(dest)],
        capture_output=True, text=True, timeout=300,
    )
    assert rc.returncode == 0, rc.stderr[-400:]
    return dest


def _expectation(**overrides) -> ValidationExpectation:
    base: dict = {
        "width": W,
        "height": H,
        "codec": "h264",
        "source_locked": True,
    }
    base.update(overrides)
    return ValidationExpectation(**base)


# ── fixtures: reference (approved) media + candidates ─────────────────


@pytest.fixture(scope="module")
def ref_segments(media_root: Path, tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("s12t04a_c2")
    seg_a = _media(root / "seg_a.mp4", "testsrc")
    seg_b = _media(root / "seg_b.mp4", "smptebars")
    seg_c = _media(root / "seg_c.mp4", "testsrc2", duration=0.5)
    seg_a_440 = _media(root / "seg_a_440.mp4", "testsrc", audio_hz=440)
    seg_b_880 = _media(root / "seg_b_880.mp4", "smptebars", audio_hz=880)
    seg_880_2s = _media(
        root / "seg_880_2s.mp4", "smptebars", audio_hz=880, duration=2.0
    )
    return {
        "root": root,
        "seg_a": seg_a,
        "seg_b": seg_b,
        "seg_c": seg_c,
        "seg_a_440": seg_a_440,
        "seg_b_880": seg_b_880,
        "seg_880_2s": seg_880_2s,
    }


@pytest.fixture(scope="module")
def approved_ab(ref_segments: dict) -> Path:
    """Approved silent output: A(1s)+B(1s), 20 frames, cut at frame 10."""
    return _concat([ref_segments["seg_a"], ref_segments["seg_b"]],
                   ref_segments["root"] / "approved_ab.mp4")


@pytest.fixture(scope="module")
def approved_audio_ab(ref_segments: dict) -> Path:
    """Approved audio output: A+B with 440Hz audio across both segments."""
    return _concat([ref_segments["seg_a_440"], ref_segments["seg_a_440"]],
                   ref_segments["root"] / "approved_audio_ab.mp4")


# ── reference evidence helpers ─────────────────────────────────────────


def _ref_silent(approved: Path) -> SourceReference:
    return SourceReference(
        artifact_sha256=sha256_file(approved),
        frame_count=FRAMES,
        fps_num=FPS,
        fps_den=1,
        frame_digests=probe_frame_digests(approved, W, H) or (),
        cuts=(CutPoint(0, 0, 1), CutPoint(FRAMES // 2, 1, 1)),
        audio=AudioReference(mode="absent"),
    )


def _ref_cuts_only(approved: Path) -> SourceReference:
    return SourceReference(
        artifact_sha256=sha256_file(approved),
        frame_count=FRAMES,
        fps_num=FPS,
        fps_den=1,
        cuts=(CutPoint(0, 0, 1), CutPoint(FRAMES // 2, 1, 1)),
        audio=AudioReference(mode="absent"),
    )


# ── C19: independent-reference negatives ───────────────────────────────


def test_c19_source_locked_full_pass(approved_ab: Path) -> None:
    candidate = approved_ab
    exp = _expectation(
        source_reference=_ref_silent(approved_ab),
        audio_policy="absent",
        expected_frame_count=FRAMES,
        expected_duration_sec=DURATION,
        expected_fps=float(FPS),
        expected_sha256=sha256_file(candidate),
    )
    verdict = validate(candidate, exp)
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c19_equal_length_reordered_content_fails(
    ref_segments: dict, tmp_path: Path
) -> None:
    """B+A decodes to the same frame count/length but content order wrong."""
    approved = _concat([ref_segments["seg_a"], ref_segments["seg_b"]],
                       tmp_path / "approved.mp4")
    candidate = _concat([ref_segments["seg_b"], ref_segments["seg_a"]],
                        tmp_path / "reordered.mp4")
    assert sha256_file(candidate) != sha256_file(approved)
    exp = _expectation(
        source_reference=_ref_silent(approved),
        audio_policy="absent",
        expected_frame_count=FRAMES,
        expected_duration_sec=DURATION,
        expected_fps=float(FPS),
        expected_sha256=sha256_file(candidate),
    )
    verdict = validate(candidate, exp)
    assert verdict.probe("frame_order") is not None
    assert verdict.probe("frame_order").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_changed_audio_fails(
    approved_audio_ab: Path, ref_segments: dict, tmp_path: Path
) -> None:
    """Same video, different (non-approved) audio content → FAIL remux."""
    video = approved_audio_ab
    digest = probe_audio_digest(video, 0)
    assert digest is not None
    replaced = tmp_path / "changed_audio.mp4"
    rc = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-i", str(ref_segments["seg_880_2s"]),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-shortest", str(replaced)],
        capture_output=True, text=True, timeout=300,
    )
    assert rc.returncode == 0, rc.stderr[-400:]
    assert probe_audio_digest(replaced, 0) != digest
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(video),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            frame_digests=probe_frame_digests(video, W, H) or (),
            audio=AudioReference(mode="remux", digest=digest, stream_index=0),
        ),
        expected_sha256=sha256_file(replaced),
    )
    verdict = validate(replaced, exp)
    assert verdict.probe("av_policy") is not None
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_timing_drift_fails(
    ref_segments: dict, approved_ab: Path, tmp_path: Path
) -> None:
    """Trailing 0.5s segment drifts duration beyond the 1-frame bound."""
    drifted = _concat([approved_ab, ref_segments["seg_c"]],
                      tmp_path / "drifted.mp4")
    exp = _expectation(
        source_reference=_ref_silent(approved_ab),
        audio_policy="absent",
        expected_frame_count=FRAMES,
        expected_duration_sec=DURATION,
        expected_fps=float(FPS),
        expected_sha256=sha256_file(drifted),
    )
    verdict = validate(drifted, exp)
    assert verdict.verdict == "FAIL", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c19_wrong_reference_fails(approved_ab: Path, tmp_path: Path) -> None:
    """Reference digests from unrelated media → content mismatch FAIL."""
    other = build_media(tmp_path / "other.mp4", width=W, height=H)
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(other),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            frame_digests=probe_frame_digests(other, W, H) or (),
            audio=AudioReference(mode="absent"),
        ),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("frame_order").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_missing_reference_fails(approved_ab: Path) -> None:
    verdict = validate(approved_ab, _expectation(source_reference=None))
    assert verdict.verdict == "FAIL"
    ref_probe = next((p for p in verdict.probes if p.name == "reference"), None)
    assert ref_probe is not None
    assert ref_probe.verdict == "FAIL"


def test_c19_combined_reorder_and_audio_fails(
    ref_segments: dict, tmp_path: Path
) -> None:
    approved = _concat([ref_segments["seg_a_440"], ref_segments["seg_a_440"]],
                       tmp_path / "approved.mp4")
    digest = probe_audio_digest(approved, 0)
    assert digest is not None
    candidate = _concat([ref_segments["seg_b_880"], ref_segments["seg_a_440"]],
                        tmp_path / "combined.mp4")
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(approved),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            frame_digests=probe_frame_digests(approved, W, H) or (),
            audio=AudioReference(mode="remux", digest=digest, stream_index=0),
        ),
        expected_sha256=sha256_file(candidate),
    )
    verdict = validate(candidate, exp)
    assert verdict.probe("frame_order").verdict == "FAIL"
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c19_self_hash_never_source_truth(approved_ab: Path) -> None:
    """Provenance matching (even self-hash) cannot carry a source-locked
    PASS: a reference with a misplaced cut still FAILs the whole verdict."""
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(approved_ab),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            cuts=(CutPoint(0, 0, 1), CutPoint(15, 1, 1)),  # frame 15 is 1.5s
            audio=AudioReference(mode="absent"),
        ),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),  # sha matches candidate
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("provenance").verdict == "PASS"  # hash alone passes
    assert verdict.probe("frame_order").verdict == "FAIL"  # ...but evidence not
    assert verdict.verdict == "FAIL"


# ── C12: exact cuts/rational timing, CFR controls, VFR rejection ───────


def test_c12_rational_cuts_placement_passes(approved_ab: Path) -> None:
    """Cuts-only reference (no digests) still locks exact rational cut pts."""
    exp = _expectation(
        source_reference=_ref_cuts_only(approved_ab),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("frame_order").verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c12_missing_order_authority_not_measured(approved_ab: Path) -> None:
    """No digests AND no cuts → no false confidence about frame order."""
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(approved_ab),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            audio=AudioReference(mode="absent"),
        ),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("frame_order").verdict == "NOT_MEASURED"
    assert verdict.verdict == "NOT_MEASURED"


def test_c12_wrong_cut_time_fails(approved_ab: Path) -> None:
    """Reference cut at 1.5s (mid-frame 15) is not on the timeline → FAIL."""
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(approved_ab),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            cuts=(CutPoint(0, 0, 1), CutPoint(15, 1, 1)),
            audio=AudioReference(mode="absent"),
        ),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("frame_order").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c12_vfr_rejected_no_false_confidence(
    approved_ab: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A/V frame rates disagree → FAIL, never an approximate PASS."""
    import app.services.s12_export.validation as _v

    real_json = _v._ffprobe_json

    def _vfr(path: Path) -> dict | None:
        payload = real_json(path)
        assert payload is not None
        for stream in payload.get("streams", []):
            if stream.get("codec_type") == "video":
                stream["r_frame_rate"] = "15/1"
        return payload

    monkeypatch.setattr(_v, "_ffprobe_json", _vfr)
    exp = _expectation(
        source_reference=_ref_silent(approved_ab),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("timebase").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


def test_c12_fps_mismatch_reference_fails(approved_ab: Path) -> None:
    """Candidate is 10fps but reference is rational 25/1 → FAIL."""
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(approved_ab),
            frame_count=FRAMES,
            fps_num=25,
            fps_den=1,
            frame_digests=probe_frame_digests(approved_ab, W, H) or (),
            audio=AudioReference(mode="absent"),
        ),
        audio_policy="absent",
        expected_sha256=sha256_file(approved_ab),
    )
    verdict = validate(approved_ab, exp)
    assert verdict.probe("timebase").verdict == "FAIL"
    assert verdict.verdict == "FAIL"


# ── C28 consumer: approved audio remux vs transcode explicit ───────────


def test_c28_remux_matching_audio_passes(approved_audio_ab: Path) -> None:
    digest = probe_audio_digest(approved_audio_ab, 0)
    assert digest is not None
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(approved_audio_ab),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            frame_digests=probe_frame_digests(approved_audio_ab, W, H) or (),
            audio=AudioReference(mode="remux", digest=digest, stream_index=0),
        ),
        expected_sha256=sha256_file(approved_audio_ab),
    )
    verdict = validate(approved_audio_ab, exp)
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c28_transcode_explicit_not_content_compared(
    approved_audio_ab: Path, ref_segments: dict, tmp_path: Path
) -> None:
    """Transcode mode asserts mapping/drift only — re-encode may differ."""
    video = approved_audio_ab
    transcoded = tmp_path / "transcoded.mp4"
    rc = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video),
         "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-b:a", "64k", str(transcoded)],
        capture_output=True, text=True, timeout=300,
    )
    assert rc.returncode == 0, rc.stderr[-400:]
    ref_digest = probe_audio_digest(video, 0)
    assert ref_digest is not None
    assert probe_audio_digest(transcoded, 0) != ref_digest  # content changed
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(video),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            cuts=(CutPoint(0, 0, 1), CutPoint(FRAMES // 2, 1, 1)),
            audio=AudioReference(
                mode="transcode", digest=ref_digest, stream_index=0
            ),
        ),
        expected_sha256=sha256_file(transcoded),
    )
    verdict = validate(transcoded, exp)
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]


def test_c28_audio_start_drift_fails(
    approved_audio_ab: Path, tmp_path: Path
) -> None:
    """Audio offset +0.5s (itsoffset) exceeds the 1-frame A/V bound → FAIL."""
    video = approved_audio_ab
    digest = probe_audio_digest(video, 0)
    assert digest is not None
    audio_src = _media(
        tmp_path / "audio_440_2s.mp4", "testsrc", audio_hz=440, duration=2.0
    )
    delayed = tmp_path / "delayed_audio.mp4"
    rc = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-itsoffset", "0.5", "-i", str(audio_src),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-shortest", str(delayed)],
        capture_output=True, text=True, timeout=300,
    )
    assert rc.returncode == 0, rc.stderr[-400:]
    exp = _expectation(
        source_reference=SourceReference(
            artifact_sha256=sha256_file(video),
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
            frame_digests=probe_frame_digests(video, W, H) or (),
            audio=AudioReference(
                mode="transcode", digest=digest, stream_index=0
            ),
        ),
        expected_sha256=sha256_file(delayed),
    )
    verdict = validate(delayed, exp)
    assert verdict.probe("av_policy").verdict == "FAIL"
    assert "drift" in verdict.probe("av_policy").detail
    assert verdict.verdict == "FAIL"
