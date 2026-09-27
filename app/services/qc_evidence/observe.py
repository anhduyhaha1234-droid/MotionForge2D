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

Object GEOMETRY is NOT measured with the source-difference primitive (round D /
NR03): *"the output differs from the source inside the box the annotation
expects"* is not evidence that the actor is there — a render replaced by one
uniform unrelated level satisfies it and produced source-shaped boxes with a
0 clipping ratio.  Geometry comes from :func:`rendered_object_bbox`: the pixels
the output paints over ITS OWN dominant level (:func:`background_level`),
seeded by the annotation and grown over the contiguous object.  The
source-difference primitive (:func:`changed_mask` and friends) remains as the
change baseline for the temporal/stacking comparisons only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from app.services.qc_evidence.errors import dependency, malformed, missing

#: Revision of the observation definitions (bump when a definition changes).
#: 1.1.0 (round D / NR03): the rendered-object measurement (render-own
#: background) replaces "differs from the source" as the geometry authority,
#: and the rendered cut is searched over the annotation's whole span and is
#: reported only when it is a DOMINANT discontinuity.
#: 1.2.0 (correction round R27-04): a rendered object is attributed to a role
#: only through that role's OWN published support (its segmentation mask), and
#: a measured extent that reaches a frame side carries the AUTHORITY verdict
#: instead of being reported as a frame-bounded "clipped_ratio = 0" pass.
OBSERVATION_REVISION = "1.2.0"

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


#: A rendered shot change is reported only when its inter-frame discontinuity
#: dominates every other measured delta inside the searched span by this
#: factor.  A cut is a STEP in the output; camera/background motion is not —
#: without this test the largest motion delta would be reported as a cut the
#: render does not carry.  Below the factor the result is a typed
#: "not observable" state (see :func:`observed_boundary`), never a green.
CUT_DOMINANCE_FACTOR = 2.0

#: Minimum number of decodable consecutive frame pairs a cut search must
#: measure before any discontinuity may be reported.
CUT_SUPPORT_FRAMES = 2


def background_level(frame: Any, *, detector: str = _SCOPE) -> float:
    """The render frame's OWN dominant gray level (its measured background).

    Measured per frame from the decoded output bytes — never a constant, never
    a source-side value, never derived from the imported source.  Every
    rendered-object measurement below is defined against this level, which is
    what makes "the actor is there" an OUTPUT fact instead of "the output
    differs from the source here".
    """
    array = _gray(frame, detector=detector)
    values, counts = np.unique(array, return_counts=True)
    # np.unique is sorted, so argmax picks the LOWEST level on a tie
    # (deterministic tie-break).
    return float(values[int(np.argmax(counts))])


def rendered_object_mask(frame: Any, *, detector: str = _SCOPE) -> np.ndarray:
    """Boolean mask of the pixels the RENDER paints over its own background.

    ``|render(x) - background_level(render)| > 0``: the output's own content.
    A render whose whole frame is one uniform level carries no object pixels —
    it can be measured only as "nothing is painted there".
    """
    array = _gray(frame, detector=detector)
    return np.abs(array - background_level(frame, detector=detector)) > 0.0


def grown_region(mask: np.ndarray, region: Region) -> Region | None:
    """Grow ``region`` over the CONTIGUOUS True pixels of ``mask``.

    The annotated region only SEEDS the measurement; when the rendered object
    continues past the seed's edge the window follows it, so an object the
    output paints up to (or clipped at) the frame border carries its REAL
    measured geometry instead of the annotation's box.  Growth is bounded by
    the frame itself and stops as soon as the object stops, so no radius is
    invented.  ``None`` when the seed holds no object pixel.
    """
    height, width = int(mask.shape[0]), int(mask.shape[1])
    x0, y0, x1, y1 = clamp_region(region, mask.shape)
    if x1 <= x0 or y1 <= y0 or not mask[y0:y1, x0:x1].any():
        return None
    while True:
        if x0 > 0 and mask[y0:y1, x0].any():
            x0 -= 1
        elif x1 < width and mask[y0:y1, x1 - 1].any():
            x1 += 1
        elif y0 > 0 and mask[y0, x0:x1].any():
            y0 -= 1
        elif y1 < height and mask[y1 - 1, x0:x1].any():
            y1 += 1
        else:
            break
    return x0, y0, x1, y1


def rendered_object_bbox(
    frame: Any,
    *,
    region: Region,
    detector: str = _SCOPE,
) -> Region | None:
    """Measured bbox of the object the RENDER itself paints inside ``region``.

    Returns ``None`` when the output paints NO object there (a uniform /
    unrelated frame, a missing actor) — the caller must refuse; the source's
    pixels are never substituted for the observation.
    """
    mask = rendered_object_mask(frame, detector=detector)
    grown = grown_region(mask, region)
    if grown is None:
        return None
    gx0, gy0, gx1, gy1 = grown
    inner = bbox_of_mask(mask[gy0:gy1, gx0:gx1])
    if inner is None:
        return None
    return (gx0 + inner[0], gy0 + inner[1], gx0 + inner[2], gy0 + inner[3])


#: Verdicts of the silhouette geometry AUTHORITY (correction round R27-04).
#:
#: The frozen detector's metric is bbox area OUTSIDE the frame, and a bbox
#: measured from decoded pixels is frame-bounded by construction, so that ratio
#: can never carry a cut the frame itself bounds.  A measurement therefore
#: states WHICH of these it is, and the composer refuses when the observation
#: has no authority to attribute the rendered object to the role at all:
#:
#: * ``in_frame_measured``            — the object lies fully inside the frame;
#: * ``source_intended_edge_contact`` — the object reaches frame side(s) the
#:   ROLE'S OWN published extent already reaches: the character is legitimately
#:   at/over that edge in the source, so this is NOT new truncation;
#: * ``newly_introduced_truncation``  — the object reaches frame side(s) the
#:   role's own extent does NOT reach while a rendered-side role mask attributes
#:   the cut content to this role: the OUTPUT cut the role;
#: * ``unattributable_edge_contact``  — the object reaches frame side(s) the
#:   role's extent does not reach and NO rendered-side role mask exists: nothing
#:   attributes the cut content to this role, so nothing may be reported from
#:   it (the caller refuses; it never reports a zero-risk PASS).
GEOMETRY_IN_FRAME = "in_frame_measured"
GEOMETRY_SOURCE_INTENDED_EDGE = "source_intended_edge_contact"
GEOMETRY_NEW_TRUNCATION = "newly_introduced_truncation"
GEOMETRY_UNATTRIBUTABLE = "unattributable_edge_contact"

#: Verdicts that may travel to the detector as a MEASURED role geometry.
GEOMETRY_ADMISSIBLE = (
    GEOMETRY_IN_FRAME,
    GEOMETRY_SOURCE_INTENDED_EDGE,
    GEOMETRY_NEW_TRUNCATION,
)

#: Verdicts that clear the clipping question for a role (no item is expected).
GEOMETRY_CLEARING = (GEOMETRY_IN_FRAME, GEOMETRY_SOURCE_INTENDED_EDGE)


def support_mask(value: Any, *, detector: str = _SCOPE) -> np.ndarray:
    """Boolean mask of a ROLE's own persisted support (its segmentation mask).

    The support is what makes "this rendered content is this role" an
    attributed fact: without it the rendered pixels are unrelated content and
    must never become a role's measured geometry.
    """
    array = _gray(value, detector=detector)
    mask = array > 0.0
    if not mask.any():
        raise missing(
            detector,
            "the role's published support mask bounds no pixels, so no rendered "
            "object can be attributed to this role",
        )
    return mask


def supported_object_bbox(
    frame: Any,
    *,
    support: Any,
    region: Region,
    detector: str = _SCOPE,
) -> Region | None:
    """Measured bbox of the rendered object ATTRIBUTED to one role.

    The object the render paints is measured only inside the role's OWN
    published support: ``region`` must BE that support's measured bbox, so a
    region that is not the role's geometry (an arbitrary box, an unrelated
    textured area, another segment's mask) is refused instead of becoming "the
    object".  ``None`` when the output paints nothing inside the support — the
    caller must refuse, the source's pixels are never substituted.
    """
    mask = support_mask(support, detector=detector)
    array = _gray(frame, detector=detector)
    if mask.shape != array.shape:
        raise malformed(
            detector,
            f"the role's support mask is {mask.shape} but the rendered frame is "
            f"{array.shape}; the rendered geometry cannot be attributed to this "
            "role (fail closed)",
        )
    bbox = bbox_of_mask(mask)
    if bbox is None:  # pragma: no cover - support_mask already refused empty
        raise missing(detector, "the role's support mask carries no geometry")
    if tuple(int(v) for v in region) != tuple(int(v) for v in bbox):
        raise malformed(
            detector,
            f"the measurement region {tuple(int(v) for v in region)} is not the "
            f"role's own published extent {bbox}; a region that is not this "
            "role's persisted geometry cannot be measured as its silhouette",
        )
    return rendered_object_bbox(array, region=bbox, detector=detector)


def clipping_authority(
    measured: Region,
    *,
    role_extent: Region | None,
    rendered_role_extent: Region | None,
    shape: tuple[int, int],
    detector: str = _SCOPE,
) -> dict[str, Any]:
    """Classify a MEASURED silhouette extent against the frame and the authority.

    Separates exactly the two sides the ratio cannot: a frame side the ROLE'S
    OWN published extent already reaches (source-intended partial visibility —
    the character is legitimately at/over the edge in the source) from a side
    only the RENDER reaches (newly introduced truncation), and reports the
    latter as ``unattributable`` when no rendered-side role mask exists to
    attribute the cut content to this role.  No appearance heuristic is used:
    the classification reads measured extents and persisted provenance only.
    """
    contact = border_contact(measured, shape)
    role_sides = list(border_contact(role_extent, shape)) if role_extent else []
    rendered_sides = (
        list(border_contact(rendered_role_extent, shape))
        if rendered_role_extent
        else []
    )
    intended = [side for side in contact if side in role_sides]
    uncovered = [side for side in contact if side not in role_sides]
    if not contact:
        verdict = GEOMETRY_IN_FRAME
    elif not uncovered:
        verdict = GEOMETRY_SOURCE_INTENDED_EDGE
    elif rendered_role_extent is not None:
        verdict = GEOMETRY_NEW_TRUNCATION
    else:
        verdict = GEOMETRY_UNATTRIBUTABLE
    return {
        "verdict": verdict,
        "contact_sides": contact,
        "role_extent_bbox": [int(v) for v in role_extent] if role_extent else None,
        "role_extent_reaches_sides": role_sides,
        "rendered_role_extent_bbox": (
            [int(v) for v in rendered_role_extent] if rendered_role_extent else None
        ),
        "rendered_role_extent_reaches_sides": rendered_sides,
        "sides_intended_by_source": intended,
        "sides_not_reached_by_role_extent": uncovered,
        "measure_authority": (
            "role_mask"
            if rendered_role_extent is None
            else "role_mask + rendered_side_role_mask"
        ),
        "detector_clearance": verdict in GEOMETRY_CLEARING,
        "newly_introduced_truncation": verdict == GEOMETRY_NEW_TRUNCATION,
        "attributed_to_role": verdict != GEOMETRY_UNATTRIBUTABLE,
        "metric_limit": "the frozen silhouette metric is bbox area OUTSIDE the "
        "frame and a pixel-measured bbox is frame-bounded by construction, so a "
        "cut the frame itself bounds is carried by THIS verdict, never by a "
        "clipped_ratio of 0",
        "measure_revision": OBSERVATION_REVISION,
    }


def border_contact(
    bbox: Region, shape: tuple[int, int]
) -> list[str]:
    """Frame sides a measured bbox touches (``left``/``right``/``top``/...).

    A rendered object whose measured extent reaches a frame edge is CUT OFF by
    the output: that is the observable signal a pixel measurement can carry
    for a clipped silhouette (a bbox measured from real pixels can never lie
    outside the frame).
    """
    height, width = int(shape[0]), int(shape[1])
    x0, y0, x1, y1 = (int(v) for v in bbox)
    sides: list[str] = []
    if x0 <= 0:
        sides.append("left")
    if y0 <= 0:
        sides.append("top")
    if x1 >= width:
        sides.append("right")
    if y1 >= height:
        sides.append("bottom")
    return sides


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
    span: tuple[int, int] | None = None,
    detector: str = _SCOPE,
) -> dict[str, Any]:
    """Observed cut near ``boundary``, measured on the RENDER bytes.

    A cut at frame ``f`` means a new shot starts at ``f``, so the observable is
    the inter-frame delta ``|frame(f) - frame(f-1)|``.  ``span`` is the SEARCH
    SPAN the annotation supports (the scene's own frame range); EVERY
    consecutive pair inside it is measured, so a cut the renderer moved away
    from the planned frame is still found — a ±1-frame search could only ever
    re-find the planned frame.  Defaults to ``boundary ± 1`` when no span is
    given.

    The reported cut is the argmax of the delta inside the span, and it is
    returned as OBSERVED only when the discontinuity is real:

    * at least :data:`CUT_SUPPORT_FRAMES` decodable consecutive pairs exist;
    * the peak delta is strictly positive;
    * the peak is an ISOLATED STEP: it dominates the deltas of the decoded
      frames immediately around it by :data:`CUT_DOMINANCE_FACTOR` — a shot
      change changes the frame once and then the new shot continues, while
      motion changes every frame by a comparable amount.

    Otherwise ``observed`` is False and ``reason`` names the typed
    not-observable state (``no_measurable_frame_pair`` / ``no_change_at_all``
    / ``insufficient_search_support`` / ``no_distinguishable_cut``): the
    largest motion delta is never reported as a cut.
    """
    boundary = int(boundary)
    if span is None:
        search = (boundary - 1, boundary + 1)
    else:
        low, high = int(span[0]), int(span[1])
        search = (min(low, high), max(low, high))
    deltas: dict[int, float] = {}
    for frame in range(search[0], search[1] + 1):
        previous, current = frame - 1, frame
        if previous in render_frames and current in render_frames:
            deltas[current] = frame_delta(
                render_frames[previous], render_frames[current], detector=detector
            )
    payload: dict[str, Any] = {
        "frame": None,
        "delta": None,
        "peak_frame": None,
        "runner_up_delta": None,
        "deltas": {str(frame): value for frame, value in sorted(deltas.items())},
        "measured_frames": sorted(deltas),
        "search_span": [search[0], search[1]],
        "neighbourhood": [search[0], search[1]],
        "dominance_factor": CUT_DOMINANCE_FACTOR,
        "support_frames_required": CUT_SUPPORT_FRAMES,
        "observed": False,
        "reason": "no_measurable_frame_pair",
        "definition": "argmax over |render(f) - render(f-1)| inside the "
        "annotation-supported SEARCH SPAN of the decoded RENDER artifact; "
        "reported only when the peak is a dominant discontinuity (a cut is a "
        "step, motion is not)",
    }
    if not deltas:
        return payload
    ordered = sorted(
        deltas.items(), key=lambda item: (-item[1], abs(item[0] - boundary), item[0])
    )
    peak_frame, peak_delta = ordered[0]
    runner_up = max(
        (value for frame, value in deltas.items() if frame != peak_frame), default=0.0
    )
    payload["delta"] = float(peak_delta)
    payload["peak_frame"] = int(peak_frame)
    payload["runner_up_delta"] = float(runner_up)
    if peak_delta <= 0.0:
        payload["reason"] = "no_change_at_all"
        return payload
    if len(deltas) < CUT_SUPPORT_FRAMES:
        payload["reason"] = "insufficient_search_support"
        return payload
    neighbour_max = max(
        (
            value
            for frame, value in deltas.items()
            if frame in (peak_frame - 1, peak_frame + 1)
        ),
        default=0.0,
    )
    payload["neighbour_max_delta"] = float(neighbour_max)
    if peak_delta < CUT_DOMINANCE_FACTOR * neighbour_max:
        # The peak is not an ISOLATED step: the frames around it change by a
        # comparable amount, which is what smooth motion looks like.  The
        # output carries no distinguishable cut here — report the typed
        # not-observable state instead of the largest motion delta.
        payload["reason"] = "no_distinguishable_cut"
        return payload
    payload["observed"] = True
    payload["reason"] = None
    payload["frame"] = int(peak_frame)
    return payload


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
    "CUT_DOMINANCE_FACTOR",
    "CUT_SUPPORT_FRAMES",
    "GEOMETRY_ADMISSIBLE",
    "GEOMETRY_CLEARING",
    "GEOMETRY_IN_FRAME",
    "GEOMETRY_NEW_TRUNCATION",
    "GEOMETRY_SOURCE_INTENDED_EDGE",
    "GEOMETRY_UNATTRIBUTABLE",
    "OBSERVATION_REVISION",
    "Region",
    "background_level",
    "bbox_of_mask",
    "border_contact",
    "changed_bbox",
    "changed_count",
    "changed_mask",
    "clamp_region",
    "clipping_authority",
    "frame_delta",
    "grown_region",
    "measured_stacking",
    "observed_boundary",
    "rendered_object_bbox",
    "rendered_object_mask",
    "stacking_order",
    "support_mask",
    "supported_object_bbox",
]
