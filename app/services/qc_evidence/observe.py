"""MF-P1-QC-EVIDENCE — the RENDERED (output) observation side of the band.

Authority separation (correction round C, findings R4/R5):

- SOURCE facts live in :mod:`.sources` (persisted rows/annotations: scene
  boundaries, segment z-order, scene-graph occlusion/contact edges, mask
  artifacts).  They are the INTENDED side.
- OBSERVED facts are measured HERE, on the decoded bytes of the resolved
  RENDER artifact — never on a source-side row and never on a re-conversion of
  one.  Every value returned carries the render artifact identity (id +
  re-verified sha256 + size) so a reviewer can trace it back to the exact
  output bytes.

Nothing in this module invents a threshold: a "changed" pixel is a pixel whose
decoded value is *not equal* to the source's pixel under the same geometry
(``|Δ| > 0``), and the stacking/boundary observers are argmax/mean comparisons
over that measured change set.  When the render carries no observable content
for the required region, the measurement refuses (``QcEvidenceError``) instead
of falling back to the source — a source annotation substituted for an
observation would read as green against a broken render.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from app.services.qc_evidence.errors import dependency, malformed

#: Revision of the observation definitions (bump when a definition changes).
OBSERVATION_REVISION = "1.0.0"

#: Refusal scope used by the pure measurement helpers.
_SCOPE = "qc_evidence_render_observation"

#: Half-open pixel region ``(x0, y0, x1, y1)``.
Region = tuple[int, int, int, int]


def _gray(value: Any, *, detector: str) -> np.ndarray:
    """Decode a persisted frame/mask payload to a float64 gray matrix."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.size == 0:
        raise malformed(
            detector,
            f"persisted pixel payload has shape {array.shape}; a 2-D gray "
            "matrix is required to measure the rendered output",
        )
    return array


def clamp_region(region: Region, shape: tuple[int, int]) -> Region:
    """Clamp a half-open region to a ``(height, width)`` matrix shape."""
    height, width = int(shape[0]), int(shape[1])
    x0, y0, x1, y1 = (int(v) for v in region)
    x0 = max(0, min(x0, width))
    x1 = max(x0, min(x1, width))
    y0 = max(0, min(y0, height))
    y1 = max(y0, min(y1, height))
    return x0, y0, x1, y1


def changed_mask(
    source: Any,
    rendered: Any,
    *,
    region: Region | None = None,
    detector: str = _SCOPE,
) -> np.ndarray:
    """Boolean mask of the pixels the RENDER changed relative to the source.

    ``region`` restricts the measurement to an annotated area (half-open
    bbox) — the annotation says WHERE to look, the render bytes say WHAT is
    there.  Values outside the region are always False.
    """
    a = _gray(source, detector=detector)
    b = _gray(rendered, detector=detector)
    if a.shape != b.shape:
        raise malformed(
            detector,
            f"source frame {a.shape} and rendered frame {b.shape} have "
            "different geometry; the rendered output cannot be compared "
            "against this source geometry",
        )
    mask = np.abs(a - b) > 0.0
    if region is not None:
        x0, y0, x1, y1 = clamp_region(region, a.shape)
        bounded = np.zeros_like(mask)
        bounded[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
        mask = bounded
    return mask


def bbox_of_mask(mask: np.ndarray) -> Region | None:
    """Half-open bbox of the True pixels of ``mask`` (``None`` when empty)."""
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def changed_bbox(
    source: Any,
    rendered: Any,
    *,
    region: Region | None = None,
    detector: str = _SCOPE,
) -> Region | None:
    """Measured bbox of the rendered change inside ``region``."""
    return bbox_of_mask(changed_mask(source, rendered, region=region, detector=detector))


def changed_count(
    source: Any,
    rendered: Any,
    *,
    region: Region | None = None,
    detector: str = _SCOPE,
) -> int:
    """Measured number of changed pixels of the rendered change."""
    return int(changed_mask(source, rendered, region=region, detector=detector).sum())


def frame_delta(a: Any, b: Any, *, detector: str = _SCOPE) -> float:
    """Mean absolute decoded difference between two same-geometry frames."""
    left = _gray(a, detector=detector)
    right = _gray(b, detector=detector)
    if left.shape != right.shape:
        raise malformed(
            detector,
            f"frames {left.shape} and {right.shape} have different geometry",
        )
    return round(float(np.abs(left - right).mean()), 9)


def observed_boundary(
    render_frames: Mapping[int, Any],
    boundary: int,
    *,
    neighbourhood: int = 1,
    detector: str = _SCOPE,
) -> dict[str, Any] | None:
    """Observed cut frame nearest ``boundary``, measured on the RENDER bytes.

    A cut at frame ``f`` means a new shot starts at ``f``, so the observable
    is the inter-frame delta ``|frame(f) - frame(f-1)|``.  The observed cut is
    the argmax of that delta inside ``boundary ± neighbourhood`` (deterministic
    tie-break: closest to the intended boundary, then lowest frame).  Returns
    ``None`` when the decoded render carries no measurable pair at all.
    """
    deltas: dict[int, float] = {}
    for frame in range(int(boundary) - neighbourhood, int(boundary) + neighbourhood + 1):
        previous, current = frame - 1, frame
        if previous in render_frames and current in render_frames:
            deltas[current] = frame_delta(
                render_frames[previous], render_frames[current], detector=detector
            )
    if not deltas:
        return None
    observed = sorted(
        deltas.items(), key=lambda item: (-item[1], abs(item[0] - int(boundary)), item[0])
    )[0]
    return {
        "frame": int(observed[0]),
        "delta": float(observed[1]),
        "deltas": {str(frame): value for frame, value in sorted(deltas.items())},
        "neighbourhood": [int(boundary) - neighbourhood, int(boundary) + neighbourhood],
        "definition": "argmax over |render(f) - render(f-1)| inside the boundary "
        "neighbourhood of the decoded RENDER artifact",
    }


def measured_stacking(
    source_frames: Mapping[int, Any],
    render_frames: Mapping[int, Any],
    masks: Mapping[str, Any],
    pairs: Sequence[tuple[str, str]],
    *,
    detector: str,
) -> list[dict[str, Any]]:
    """Measure which segment of an occlusion pair the RENDER paints on top.

    For each ``(occluder, occludee)`` pair the annotated masks define three
    disjoint regions inside the frame: the occluder's exclusive area, the
    occludee's exclusive area and their overlap.  The rendered change
    (``|render - source|``) is averaged in each; the overlap region is painted
    by whichever segment's exclusive area its measured appearance matches.
    A pair whose regions do not all exist, or whose appearance is
    indistinguishable, has NO observable stacking in the output and refuses.
    """
    results: list[dict[str, Any]] = []
    for occluder, occludee in pairs:
        left = masks.get(str(occluder))
        right = masks.get(str(occludee))
        if left is None or right is None:
            raise dependency(
                detector,
                f"the occlusion pair {occluder!r}/{occludee!r} has no decoded "
                "mask artifact on both sides, so the rendered stacking of the "
                "pair cannot be measured from the output",
                fact="a decoded mask artifact for both segments of the pair",
                producer="object extraction / segmentation mask publication",
                persistence="occurrence_segment.mask_artifact_id + artifact bytes",
            )
        a = _gray(left, detector=detector) > 0.0
        b = _gray(right, detector=detector) > 0.0
        overlap = a & b
        exclusive_occluder = a & ~b
        exclusive_occludee = b & ~a
        if not overlap.any() or not exclusive_occluder.any() or not exclusive_occludee.any():
            raise dependency(
                detector,
                f"the two annotated mask regions of the occlusion pair "
                f"{occluder!r}/{occludee!r} do not overlap (or one of them has "
                "no exclusive area), so the rendered stacking is not "
                "observable in the output pixels",
                fact="an overlap region plus one exclusive region per segment",
                producer="object extraction / segmentation mask publication",
                persistence="artifact bytes of the pair's masks (measured regions)",
            )
        overlap_series: list[float] = []
        occluder_series: list[float] = []
        occludee_series: list[float] = []
        measured_frames: list[int] = []
        for index in sorted(render_frames):
            source_frame = source_frames.get(index)
            if source_frame is None:
                continue
            delta = np.abs(
                _gray(source_frame, detector=detector)
                - _gray(render_frames[index], detector=detector)
            )
            if delta.shape != a.shape:
                raise malformed(
                    detector,
                    f"rendered frame {index} is {delta.shape} but the segment "
                    f"masks are {a.shape}; the rendered stacking cannot be "
                    "measured (fail closed)",
                )
            overlap_series.append(float(delta[overlap].mean()))
            occluder_series.append(float(delta[exclusive_occluder].mean()))
            occludee_series.append(float(delta[exclusive_occludee].mean()))
            measured_frames.append(int(index))
        if not measured_frames:
            raise dependency(
                detector,
                "no decoded source/render frame pair inside the occlusion "
                "window, so the rendered stacking of this pair cannot be "
                "measured",
                fact="at least one decodable source+render frame pair",
                producer="full-apply render + imported source artifacts",
                persistence="artifact bytes of the render and the source",
            )
        mean_overlap = float(np.mean(overlap_series))
        mean_occluder = float(np.mean(occluder_series))
        mean_occludee = float(np.mean(occludee_series))
        distance_occluder = abs(mean_overlap - mean_occluder)
        distance_occludee = abs(mean_overlap - mean_occludee)
        if distance_occluder == distance_occludee:
            raise dependency(
                detector,
                f"the rendered appearance of the overlap region of "
                f"{occluder!r}/{occludee!r} is equidistant from both segments' "
                "exclusive areas, so the stacking is not observable in the "
                "output",
                fact="an overlap appearance that matches exactly one segment",
                producer="full-apply render artifact bytes",
                persistence="artifact bytes of the render (measured regions)",
            )
        on_top = str(occluder) if distance_occluder < distance_occludee else str(occludee)
        below = str(occludee) if on_top == str(occluder) else str(occluder)
        results.append(
            {
                "occluder_segment_id": str(occluder),
                "occludee_segment_id": str(occludee),
                "measured_on_top": on_top,
                "measured_below": below,
                "overlap_px": int(overlap.sum()),
                "measured_frames": measured_frames,
                "overlap_mean_delta": round(mean_overlap, 9),
                "occluder_exclusive_mean_delta": round(mean_occluder, 9),
                "occludee_exclusive_mean_delta": round(mean_occludee, 9),
                "distance_to_occluder": round(distance_occluder, 9),
                "distance_to_occludee": round(distance_occludee, 9),
                "agrees_with_annotation": on_top == str(occluder),
                "definition": "the overlap region is painted by whichever "
                "segment's EXCLUSIVE rendered appearance it matches, measured "
                "on the decoded RENDER artifact",
            }
        )
    return results


def stacking_order(
    measurements: Sequence[Mapping[str, Any]],
    *,
    others: Sequence[str] = (),
    detector: str,
) -> list[str]:
    """Bottom-to-top render order implied by the MEASURED stackings.

    Refuses when the measured relations contradict each other (a cycle), so a
    render whose pixels disagree with themselves is never reported as a
    consistent observed order.
    """
    rank: dict[str, int] = {}
    for row in measurements:
        above = str(row["measured_on_top"])
        below = str(row["measured_below"])
        rank.setdefault(above, 0)
        rank.setdefault(below, 0)
        rank[above] += 1
    for row in measurements:
        if rank[str(row["measured_on_top"])] <= rank[str(row["measured_below"])]:
            raise dependency(
                detector,
                "the rendered stackings measured on the output contradict each "
                "other (the top/bottom relation of "
                f"{row['measured_on_top']!r}/{row['measured_below']!r} is not "
                "satisfiable), so no consistent observed render order exists",
                fact="a consistent (acyclic) measured render order",
                producer="full-apply render artifact bytes",
                persistence="artifact bytes of the render (measured stackings)",
            )
    ordered = sorted(rank, key=lambda segment: (rank[segment], segment))
    bottom = sorted({str(segment) for segment in others} - set(ordered))
    return bottom + ordered


__all__ = [
    "OBSERVATION_REVISION",
    "Region",
    "bbox_of_mask",
    "changed_bbox",
    "changed_count",
    "changed_mask",
    "clamp_region",
    "frame_delta",
    "measured_stacking",
    "observed_boundary",
    "stacking_order",
]
