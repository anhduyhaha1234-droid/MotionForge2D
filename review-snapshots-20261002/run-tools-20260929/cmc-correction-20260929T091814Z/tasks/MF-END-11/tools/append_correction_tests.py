#!/usr/bin/env python
"""MF-END-11 correction — append the CMC rows to test_mf_end_11.py (CRLF bounded).

Appends a new section at EOF (the existing bytes are preserved verbatim).
Asserts the current tail preimage, growth, and CRLF accounting.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/tests/product_delivery/test_mf_end_11.py"
)

PRE_TAIL = (
    b"    assert artifact.facts.fps_classification == \"VFR\"\r\n"
    b"    assert artifact.shots[0].span.end_frame_exclusive == facts.frame_count\r\n"
)

BLOCK_LF = '''

# ── CMC correction 29/09: source-authoritative map + audio timebase ─────────


def test_correction_real_fixture_authoritative_map(demo12s: Path) -> None:
    """The REAL demo fixture partitions at the MEASURED cuts (never 3x120)."""
    facts = plan.probe_source_facts(demo12s, deep_count=True)
    partition = plan.build_source_time_map(demo12s, facts=facts)
    assert facts.frame_count == 360
    assert facts.decoded_frame_count == 360  # decode agrees with the packet table
    assert (facts.fps_num, facts.fps_den) == (30, 1)
    assert facts.fps_classification == "CFR"
    assert (facts.stream_timebase_num, facts.stream_timebase_den) == (1, 15360)
    assert [s.start_frame for s in partition.shots] == [0, 121, 241, 343]
    assert [(s.start_frame, s.end_frame_exclusive) for s in partition.shots] == [
        (0, 121),
        (121, 241),
        (241, 343),
        (343, 360),
    ]
    assert partition.dropped_cuts == ()
    assert validate_half_open_partition(
        [(s.start_frame, s.end_frame_exclusive) for s in partition.shots], 360
    ) == []


def test_correction_detects_hardcoded_manifest_drift(demo12s: Path) -> None:
    """The demo's declared 3x120 map must NOT verify against the source."""
    verdict = plan.verify_shot_plan_correction(
        demo12s,
        [
            {"shot_id": "BOOK", "start_frame": 0, "end_frame": 119},
            {"shot_id": "TURN", "start_frame": 120, "end_frame": 239},
            {"shot_id": "OCC", "start_frame": 240, "end_frame": 359},
        ],
    )
    assert verdict.valid is False
    assert verdict.status == plan.CORRECTION_MANIFEST_MISMATCH
    assert verdict.measured_cuts == (121, 241, 343)
    assert verdict.declared_boundaries == (120, 240)
    assert verdict.missing_boundaries == (121, 241, 343)
    assert verdict.unexpected_boundaries == (120, 240)
    assert verdict.internal_cuts == (
        {"shot_id": "BOOK", "cut_frame": 121, "window_local_frame": 121,
         "must_be_represented_as": "boundary_or_declared_event"},
        {"shot_id": "TURN", "cut_frame": 241, "window_local_frame": 121,
         "must_be_represented_as": "boundary_or_declared_event"},
        {"shot_id": "OCC", "cut_frame": 343, "window_local_frame": 103,
         "must_be_represented_as": "boundary_or_declared_event"},
    )
    assert verdict.coverage_problems == ()
    assert verdict.measured_frame_count == 360


def test_correction_accepts_the_authoritative_map(demo12s: Path) -> None:
    """The measured map itself verifies valid (the check is not a rubber stamp)."""
    verdict = plan.verify_shot_plan_correction(
        demo12s,
        [
            {"shot_id": "S0", "start_frame": 0, "end_frame": 120},
            {"shot_id": "S1", "start_frame": 121, "end_frame": 240},
            {"shot_id": "S2", "start_frame": 241, "end_frame": 342},
            {"shot_id": "S3", "start_frame": 343, "end_frame": 359},
        ],
    )
    assert verdict.valid is True
    assert verdict.status == plan.CORRECTION_VALID
    assert verdict.missing_boundaries == ()
    assert verdict.unexpected_boundaries == ()
    assert verdict.internal_cuts == ()


def test_correction_internal_cut_is_reported_not_invented(cut60: Path) -> None:
    """A real cut inside one declared shot is REPORTED as internal, not added."""
    verdict = plan.verify_shot_plan_correction(
        cut60, [{"shot_id": "WHOLE", "start_frame": 0, "end_frame": 59}]
    )
    assert verdict.valid is False
    assert verdict.missing_boundaries == ()
    assert verdict.unexpected_boundaries == ()
    assert verdict.coverage_problems == ()
    assert [(row["cut_frame"], row["window_local_frame"]) for row in verdict.internal_cuts] == [
        (30, 30)
    ]


def test_correction_tolerance_and_bad_shots(cut60: Path) -> None:
    tolerant = plan.verify_shot_plan_correction(
        cut60,
        [
            {"shot_id": "A", "start_frame": 0, "end_frame": 29},
            {"shot_id": "B", "start_frame": 31, "end_frame": 59},
        ],
        tolerance_frames=1,
    )
    assert tolerant.status == plan.CORRECTION_MANIFEST_MISMATCH  # still a coverage mismatch
    assert tolerant.missing_boundaries == ()
    assert tolerant.unexpected_boundaries == ()
    assert tolerant.coverage_problems  # frame 30 is lost by the declared map
    _refuses(
        plan.CODE_COVERAGE_INVALID,
        plan.verify_shot_plan_correction,
        cut60,
        [],
    )
    _refuses(
        plan.CODE_COVERAGE_INVALID,
        plan.verify_shot_plan_correction,
        cut60,
        [{"shot_id": "A", "start_frame": 0, "end_frame": 59}],
        tolerance_frames=-1,
    )


def test_audio_sample_span_uses_audio_timebase(demo12s: Path) -> None:
    """Audio boundaries come from the AUDIO stream, not the video frame count."""
    facts = plan.probe_source_facts(demo12s)
    assert facts.audio is not None
    assert facts.audio.sample_rate == 48000
    assert facts.audio.channels == 2
    span = plan.SourceSpan(start_frame=0, end_frame_exclusive=360)
    mapped = plan.audio_sample_span_for_frames(facts, span)
    assert mapped["span"] == [0, 360]
    assert mapped["start_sample"] == 0
    assert mapped["end_sample"] == 576000  # 12 s x 48000 Hz, exact
    assert mapped["sample_count"] == 576000
    assert mapped["audio_timebase"] == "1/48000"


def test_audio_sample_span_one_frame_grid(demo12s: Path) -> None:
    facts = plan.probe_source_facts(demo12s)
    first = plan.audio_sample_span_for_frames(facts, plan.SourceSpan(0, 1))
    assert first["start_sample"] == 0
    assert first["end_sample"] == 1600
    second = plan.audio_sample_span_for_frames(facts, plan.SourceSpan(1, 2))
    assert second["start_sample"] == 1600
    assert second["end_sample"] == 3200


def test_audio_sample_span_refuses_without_audio(cfr30_noaudio: Path) -> None:
    facts = plan.probe_source_facts(cfr30_noaudio)
    assert facts.audio is None
    _refuses(
        plan.CODE_FACTS_INVALID,
        plan.audio_sample_span_for_frames,
        facts,
        plan.SourceSpan(0, 1),
    )
'''

BLOCK = BLOCK_LF.replace("\n", "\r\n").encode("utf-8")


def main() -> int:
    data = TARGET.read_bytes()
    before_sha = hashlib.sha256(data).hexdigest()
    count = data.count(PRE_TAIL)
    if count != 1:
        print(f"tail preimage count {count} != 1; refusing")
        return 2
    if not data.endswith(PRE_TAIL):
        print("tail preimage is not at EOF; refusing")
        return 2
    post = data + BLOCK
    if len(post) <= len(data):
        print("append did not grow the file; refusing")
        return 2
    crlf = chr(13).encode() + chr(10).encode()
    expected = data.count(crlf) + BLOCK.count(crlf)
    if post.count(crlf) != expected:
        print(f"CRLF accounting {post.count(crlf)} != {expected}; refusing")
        return 2
    TARGET.write_bytes(post)
    after = TARGET.read_bytes()
    print(f"test_mf_end_11.py  bytes {len(data)} -> {len(after)} (+{len(after) - len(data)})")
    print(f"  lines {data.count(chr(10).encode())} -> {after.count(chr(10).encode())}")
    print(f"  sha256 {before_sha[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
