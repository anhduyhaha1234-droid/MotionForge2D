#!/usr/bin/env python
"""MF-END-11 correction — bounded patch of app/services/shot_reskin_plan.py (CRLF).

Two byte-exact edits:
  1. three names added to __all__;
  2. source-authoritative verifier + audio time map appended at EOF.
Each preimage asserted count == 1; file must GROW; CRLF accounting checked.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

TARGET = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11/app/services/shot_reskin_plan.py"
)

PRE_ALL = b'    "probe_source_facts",\r\n'
NEW_ALL = (
    b'    "probe_source_facts",\r\n'
    b'    "build_source_time_map",\r\n'
    b'    "verify_shot_plan_correction",\r\n'
    b'    "audio_sample_span_for_frames",\r\n'
)

PRE_TAIL = (
    b'            "the plan must be rebuilt for the current source",\r\n'
    b'        )\r\n'
    b'    return artifact\r\n'
)

BLOCK_LF = '''

# ── source-authoritative correction: manifest vs MEASURED source ──────────────

#: Verdict statuses for a declared scene manifest checked against the source.
CORRECTION_VALID = "valid"
CORRECTION_MANIFEST_MISMATCH = "manifest_mismatch"
CORRECTION_UNMEASURABLE = "unmeasurable"


@dataclass(frozen=True)
class ShotPlanCorrectionVerdict:
    """Source-authoritative verdict for one declared scene manifest.

    The measured cuts come from the REAL detector over the locked source; the
    declared boundaries come from the manifest.  A measured cut strictly inside
    a declared shot is reported as an INTERNAL CUT (a real cut that the map
    must represent — as a boundary of the authoritative map, or as a declared
    event of that shot); it is surfaced for the caller to route, never silently
    dropped and never invented as a new cut for sub-threshold motion.
    """

    status: str
    measured_frame_count: int
    measured_cuts: tuple[int, ...]
    declared_boundaries: tuple[int, ...]
    missing_boundaries: tuple[int, ...]
    unexpected_boundaries: tuple[int, ...]
    internal_cuts: tuple[dict[str, Any], ...]
    coverage_problems: tuple[str, ...]
    tolerance_frames: int
    details: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status == CORRECTION_VALID

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "measured_frame_count": self.measured_frame_count,
            "measured_cuts": list(self.measured_cuts),
            "declared_boundaries": list(self.declared_boundaries),
            "missing_boundaries": list(self.missing_boundaries),
            "unexpected_boundaries": list(self.unexpected_boundaries),
            "internal_cuts": [dict(row) for row in self.internal_cuts],
            "coverage_problems": list(self.coverage_problems),
            "tolerance_frames": self.tolerance_frames,
            "details": list(self.details),
        }


def build_source_time_map(
    source_path: str | Path,
    *,
    threshold: float = DEFAULT_SCENE_THRESHOLD,
    min_scene_len_frames: int = DEFAULT_MIN_SCENE_LEN_FRAMES,
    facts: SourceFacts | None = None,
    cuts: Sequence[int] | None = None,
    deep_count: bool = False,
) -> SourcePartition:
    """The AUTHORITATIVE shot partition of a source (never a hardcoded split).

    Measures the source (or reuses injected ``facts``) and partitions it with
    the REAL detector through :func:`detect_shot_intervals`; a caller-supplied
    ``cuts`` list is accepted for unit rows only and must still cover the
    measured frame count exactly.
    """
    measured = facts if facts is not None else probe_source_facts(source_path, deep_count=deep_count)
    if cuts is not None:
        return plan_shot_intervals(cuts, measured.frame_count)
    return detect_shot_intervals(
        source_path,
        measured.frame_count,
        threshold=threshold,
        min_scene_len_frames=min_scene_len_frames,
    )


def _declared_shots(declared_shots: Any) -> list[dict[str, Any]]:
    if not isinstance(declared_shots, (list, tuple)) or not declared_shots:
        raise ShotPlanError(CODE_COVERAGE_INVALID, "declared shots must be a non-empty list")
    rows: list[dict[str, Any]] = []
    for index, shot in enumerate(declared_shots):
        if not isinstance(shot, dict):
            raise ShotPlanError(CODE_COVERAGE_INVALID, f"declared shot[{index}] must be an object")
        try:
            start = int(shot["start_frame"])
            end = int(shot["end_frame"])
        except (KeyError, TypeError, ValueError) as err:
            raise ShotPlanError(
                CODE_COVERAGE_INVALID, f"declared shot[{index}] needs int start_frame/end_frame"
            ) from err
        if start < 0 or end < start:
            raise ShotPlanError(
                CODE_COVERAGE_INVALID, f"declared shot[{index}] invalid range [{start},{end}]"
            )
        rows.append({"shot_id": str(shot.get("shot_id") or f"shot-{index:04d}"),
                     "start_frame": start, "end_frame": end})
    rows.sort(key=lambda row: (row["start_frame"], row["shot_id"]))
    return rows


def verify_shot_plan_correction(
    source_path: str | Path,
    declared_shots: Any,
    *,
    threshold: float = DEFAULT_SCENE_THRESHOLD,
    min_scene_len_frames: int = DEFAULT_MIN_SCENE_LEN_FRAMES,
    facts: SourceFacts | None = None,
    cuts: Sequence[int] | None = None,
    tolerance_frames: int = 0,
) -> ShotPlanCorrectionVerdict:
    """Compare a declared manifest against cuts MEASURED on the locked source.

    ``declared_shots`` uses the manifest's INCLUSIVE ``end_frame`` convention.
    ``manifest_mismatch`` is returned when a measured cut is absent from the
    declared boundaries, when a declared boundary matches no measured cut, or
    when the declared shots do not cover ``[0, measured_frame_count)`` exactly
    (frames lost or duplicated).  The declared values are NEVER adjusted to
    agree, and no cut is invented for sub-threshold motion.
    """
    if tolerance_frames < 0:
        raise ShotPlanError(CODE_COVERAGE_INVALID, f"tolerance_frames {tolerance_frames} < 0")
    measured = facts if facts is not None else probe_source_facts(source_path)
    partition = build_source_time_map(
        source_path,
        threshold=threshold,
        min_scene_len_frames=min_scene_len_frames,
        facts=measured,
        cuts=cuts,
    )
    declared = _declared_shots(declared_shots)
    measured_cuts = tuple(int(span.start_frame) for span in partition.shots[1:])
    declared_boundaries = tuple(row["start_frame"] for row in declared[1:])
    missing = tuple(
        cut for cut in measured_cuts
        if not any(abs(cut - boundary) <= tolerance_frames for boundary in declared_boundaries)
    )
    unexpected = tuple(
        boundary for boundary in declared_boundaries
        if not any(abs(boundary - cut) <= tolerance_frames for cut in measured_cuts)
    )
    internal: list[dict[str, Any]] = []
    for row in declared:
        for cut in measured_cuts:
            if row["start_frame"] < cut <= row["end_frame"]:
                internal.append({
                    "shot_id": row["shot_id"],
                    "cut_frame": cut,
                    "window_local_frame": cut - row["start_frame"],
                    "must_be_represented_as": "boundary_or_declared_event",
                })
    coverage = validate_half_open_partition(
        [(row["start_frame"], row["end_frame"] + 1) for row in declared], measured.frame_count
    )
    details: list[str] = []
    if missing:
        details.append(f"measured cuts absent from the manifest: {list(missing)}")
    if unexpected:
        details.append(f"declared boundaries with no measured cut: {list(unexpected)}")
    if coverage:
        details.append(f"{pick_partition_code(coverage)}: {'; '.join(coverage)}")
    for row in internal:
        details.append(
            f"internal cut {row['cut_frame']} (local {row['window_local_frame']}) inside declared "
            f"shot {row['shot_id']}"
        )
    status = (
        CORRECTION_MANIFEST_MISMATCH
        if (missing or unexpected or coverage)
        else CORRECTION_VALID
    )
    return ShotPlanCorrectionVerdict(
        status=status,
        measured_frame_count=measured.frame_count,
        measured_cuts=measured_cuts,
        declared_boundaries=declared_boundaries,
        missing_boundaries=missing,
        unexpected_boundaries=unexpected,
        internal_cuts=tuple(internal),
        coverage_problems=tuple(coverage),
        tolerance_frames=tolerance_frames,
        details=tuple(details),
    )


def audio_sample_span_for_frames(
    facts: SourceFacts, span: SourceSpan
) -> dict[str, Any]:
    """Exact audio boundary for a VIDEO frame span, on the AUDIO timebase.

    Sample boundaries are computed by exact rational arithmetic
    (``frame * sample_rate * fps_den / fps_num``, ceil for the exclusive end)
    — never by scaling the video frame count.  The video-derived estimate and
    the bound sample count are both reported so a caller trimming or padding
    audio can VERIFY the boundary bytes against the real stream instead of
    assuming the count.  Audio presence/sample rate come from the measured
    source facts; a source without an audio stream refuses.
    """
    if facts.audio is None:
        raise ShotPlanError(
            CODE_FACTS_INVALID, "source has no measured audio stream; audio map is undefined"
        )
    rate = facts.audio.sample_rate
    start_ratio = Fraction(span.start_frame * rate * facts.fps_den, facts.fps_num)
    end_ratio = Fraction(span.end_frame_exclusive * rate * facts.fps_den, facts.fps_num)
    start_sample = start_ratio.numerator // start_ratio.denominator
    end_sample = -((-end_ratio.numerator) // end_ratio.denominator)  # ceil
    nominal = max(0, end_sample - start_sample)
    return {
        "span": [span.start_frame, span.end_frame_exclusive],
        "frame_count": span.frame_count,
        "audio_sample_rate": rate,
        "audio_timebase": f"1/{rate}",
        "video_timebase_ticks_span": facts.pts_end_ticks - facts.pts_start_ticks,
        "start_sample": start_sample,
        "end_sample": end_sample,
        "sample_count": nominal,
        "exact_start_seconds": str(start_ratio / rate),
        "boundary_verified_by": "caller must hash the trimmed bytes and compare",
    }
'''

BLOCK = BLOCK_LF.replace("\n", "\r\n").encode("utf-8")


def main() -> int:
    data = TARGET.read_bytes()
    before_sha = hashlib.sha256(data).hexdigest()
    for label, pre in (("__all__", PRE_ALL), ("tail", PRE_TAIL)):
        count = data.count(pre)
        if count != 1:
            print(f"{label} PREIMAGE count {count} != 1; refusing")
            return 2
    if not data.endswith(PRE_TAIL):
        print("tail preimage is not at EOF; refusing")
        return 2
    post = data.replace(PRE_ALL, NEW_ALL, 1) + BLOCK
    if len(post) <= len(data):
        print("patch did not grow the file; refusing")
        return 2
    expected = len(data) + (len(NEW_ALL) - len(PRE_ALL)) + len(BLOCK)
    if len(post) != expected:
        print(f"size accounting {len(post)} != {expected}; refusing")
        return 2
    TARGET.write_bytes(post)
    after = TARGET.read_bytes()
    crlf = chr(13).encode() + chr(10).encode()
    print(f"shot_reskin_plan.py  bytes {len(data)} -> {len(after)} (+{len(after) - len(data)})")
    print(f"  lines {data.count(chr(10).encode())} -> {after.count(chr(10).encode())}")
    print(f"  crlf {data.count(crlf)} -> {after.count(crlf)}")
    print(f"  sha256 {before_sha[:16]} -> {hashlib.sha256(after).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
