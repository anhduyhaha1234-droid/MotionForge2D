"""MF-P1-QC-EVIDENCE — server-side composition of the visual QC band.

This module supplies the eight non-audio detectors of the binding FULL band
with REAL persisted evidence, composed server-side from what the database and
the managed artifact root actually contain (see :mod:`.contract` for the
frozen detector → input → producer → provenance table).

Non-negotiables, all enforced here:

- nothing is fabricated: every value either comes from a persisted row column,
  from bytes re-hashed against the recorded digest, or from a bounded
  deterministic measurement over those bytes (the exact derivation is
  recorded in ``evidence_provenance`` and named in the frozen table);
- missing / stale / foreign / malformed / tampered evidence refuses with a
  typed :class:`~app.services.qc_evidence.errors.QcEvidenceError` — never a
  silent pass;
- a fact with no producer at all raises ``QC_EVIDENCE_DEPENDENCY`` carrying an
  exact dependency report (missing fact + missing producer + expected
  persistence), never an invention;
- pixel payloads are bounded to a small window so the detector args stay a
  sane size inside the durable job manifest.

The audio band is untouched: ``audio_missing`` / ``av_sync_drift`` keep the
existing T03E attach-envelope composition path in the workflow handler.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.services.qc_evidence import observe as obs
from app.services.qc_evidence import sources as src
from app.services.qc_evidence.contract import FULL_BAND
from app.services.qc_evidence.errors import (
    QcEvidenceError,
    dependency,
    malformed,
    missing,
    stale,
)
from app.services.qc_evidence.measure import (
    MAX_WINDOW_FRAMES,
    MEASURE_REVISION,
    changed_centroid_x,
    content_digest,
    crop_region,
    crop_revision,
    crop_sha256,
    decode_png_gray,
    decode_video_frames,
    disc_radius_px,
    frame_luminance,
    mask_area,
    mask_bbox,
    window_indices,
)

#: Provenance checkpoint identity this composer stamps into every argument set.
CHECKPOINT_REF = "s11-qc-evidence"

#: The eight detectors this module composes (the audio pair is composed by the
#: workflow handler from the persisted attach envelope).
VISUAL_DETECTORS: tuple[str, ...] = tuple(
    name for name in FULL_BAND if name not in ("audio_missing", "av_sync_drift")
)

#: Bound on the pixel window handed to the crop/mask detectors (the job
#: manifest carries the args, so payloads stay small and deterministic).
CROP_WINDOW_PX = 32

#: Halo band (px) added around the measured expected-mask bbox for
#: ``edge_halo``: the ring it measures lives OUTSIDE the expected region, so a
#: window cropped to the expected bbox can never contain it.
HALO_MARGIN_PX = 4

#: Hard bound on the halo window (px, per side) so the payload stays small.
HALO_WINDOW_LIMIT_PX = 48

#: Budget for the argv-transported argument set of ONE detector.
#: ``app/services/qc_checks/runner.py`` hands the composed set to the detector
#: child process as ``sys.argv[2]`` (``json.dumps(args, separators=(",", ":"))``),
#: so it must stay inside the Windows command line.  Measured on this host: a
#: 32,500-char argument spawns and a 32,700-char argument raises
#: ``FileNotFoundError: [WinError 206]`` — the failure round D hit at 66,664 B.
ARGV_DETECTOR_ARGS_BUDGET_BYTES = 30000

#: The measured ``CreateProcess`` ceiling of ONE argv item on this host.
ARGV_CEILING_SPAWN_OK_BYTES = 32500
ARGV_CEILING_WINERROR_206_BYTES = 32700


def _bounded_window(
    bbox: tuple[int, int, int, int], *, limit: int = CROP_WINDOW_PX
) -> tuple[int, int, int, int]:
    """Centre-crop a bbox to at most ``limit`` × ``limit`` pixels."""
    x0, y0, x1, y1 = bbox
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    if width > limit:
        pad = (width - limit) // 2
        x0, x1 = x0 + pad, x0 + pad + limit
    if height > limit:
        pad = (height - limit) // 2
        y0, y1 = y0 + pad, y0 + pad + limit
    return x0, y0, x1, y1


def _halo_window(
    expected_bbox: tuple[int, int, int, int],
    rendered_bbox: tuple[int, int, int, int],
    *,
    frame: tuple[int, int] | None = None,
) -> tuple[tuple[int, int, int, int], bool]:
    """Window covering the expected ∪ rendered regions plus a halo margin.

    Returns ``(window, bounded)``.  ``bounded`` is True when the window had to
    be shrunk to :data:`HALO_WINDOW_LIMIT_PX` (disclosed in the provenance), so
    a reviewer can see the measurement was made over a truncated band.
    """
    x0 = min(int(expected_bbox[0]), int(rendered_bbox[0])) - HALO_MARGIN_PX
    y0 = min(int(expected_bbox[1]), int(rendered_bbox[1])) - HALO_MARGIN_PX
    x1 = max(int(expected_bbox[2]), int(rendered_bbox[2])) + HALO_MARGIN_PX
    y1 = max(int(expected_bbox[3]), int(rendered_bbox[3])) + HALO_MARGIN_PX
    if frame is not None:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(int(frame[0]), x1), min(int(frame[1]), y1)
    bounded = False
    width, height = x1 - x0, y1 - y0
    if width > HALO_WINDOW_LIMIT_PX:
        centre = (x0 + x1) // 2
        x0 = centre - HALO_WINDOW_LIMIT_PX // 2
        x1 = x0 + HALO_WINDOW_LIMIT_PX
        bounded = True
    if height > HALO_WINDOW_LIMIT_PX:
        centre = (y0 + y1) // 2
        y0 = centre - HALO_WINDOW_LIMIT_PX // 2
        y1 = y0 + HALO_WINDOW_LIMIT_PX
        bounded = True
    return (x0, y0, x1, y1), bounded


def _bbox_overlaps(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> bool:
    """True when two half-open bboxes share at least one pixel."""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


@dataclass
class _Context:
    """Lazily-loaded, verified view of one video item's persisted evidence."""

    session: Session
    managed_root: Path
    scope: src.VideoScope
    max_frames: int = MAX_WINDOW_FRAMES
    _segments: list[Any] | None = None
    _routes: list[Any] | None = None
    _masks: dict[str, tuple[src.ArtifactEvidence, list[list[float]], int, int]] = field(
        default_factory=dict
    )

    # ── rows ────────────────────────────────────────────────────────────
    def segments(self, detector: str) -> list[Any]:
        if self._segments is None:
            self._segments = src.current_segments(self.session, self.scope)
        if not self._segments:
            raise missing(
                detector,
                "the video has no current-generation occurrence segments; the "
                "structural evidence producer (object extraction / segmentation) "
                "has not published evidence for this video",
                video_item_id=self.scope.video_item_id,
            )
        return self._segments

    def segment_by_id(self, segment_id: str, detector: str) -> Any:
        for row in self.segments(detector):
            if str(row.id) == segment_id:
                return row
        raise malformed(
            detector,
            f"annotation references segment {segment_id!r} which is not a "
            "current segment of this video (dangling evidence)",
            segment_id=segment_id,
        )

    def routes(self, detector: str) -> list[Any]:
        if self._routes is None:
            self._routes = src.render_routes(self.session, self.scope)
        if not self._routes:
            raise dependency(
                detector,
                "no persisted renderer-route evidence for this video",
                fact="per-segment rendered placement (anchor_x/anchor_y) and the "
                "rendered frame range",
                producer="S09 structural-lock render-route recorder "
                "(StructuralLockRepository.record_render_route)",
                persistence="segment_render_route.anchor_x / anchor_y / "
                "start_frame / end_frame",
            )
        return self._routes

    def scenes(self, detector: str) -> list[Any]:
        rows = src.scene_rows(self.session, self.scope)
        if not rows:
            raise missing(
                detector,
                "the video has no persisted scene rows; the scene-detector "
                "ground truth this check compares against does not exist",
                video_item_id=self.scope.video_item_id,
            )
        return rows

    def occlusions(self, detector: str) -> list[Any]:
        rows = src.occlusion_edges(self.session, self.scope)
        if not rows:
            raise missing(
                detector,
                "the video has no persisted scene-graph occlusion edges; the "
                "annotation producer has not published the graph this check "
                "judges against",
                video_item_id=self.scope.video_item_id,
            )
        return rows

    def contacts(self, detector: str) -> list[Any]:
        rows = src.contact_edges(self.session, self.scope)
        if not rows:
            raise missing(
                detector,
                "the video has no persisted scene-graph contact edges; the "
                "annotation producer has not published the graph this check "
                "judges against",
                video_item_id=self.scope.video_item_id,
            )
        return rows

    # ── artifacts ───────────────────────────────────────────────────────
    def mask(
        self, artifact_id: str | None, detector: str
    ) -> tuple[src.ArtifactEvidence, list[list[float]], int, int, tuple[int, int, int, int]]:
        if not artifact_id:
            raise missing(
                detector,
                "the segment records no mask artifact id; its geometry was "
                "never published as persisted bytes",
                video_item_id=self.scope.video_item_id,
            )
        key = str(artifact_id)
        if key not in self._masks:
            evidence = src.read_artifact(
                self.session, self.managed_root, self.scope, key, detector=detector
            )
            matrix, width, height = decode_png_gray(evidence.data, detector=detector)
            self._masks[key] = (evidence, matrix, width, height)
        evidence, matrix, width, height = self._masks[key]
        return evidence, matrix, width, height, mask_bbox(matrix)

    def source(self, detector: str) -> src.ArtifactEvidence:
        return src.source_artifact(
            self.session, self.managed_root, self.scope, detector=detector
        )

    def render(
        self, detector: str
    ) -> tuple[src.ArtifactEvidence, str, dict[str, Any]]:
        return src.render_result_artifact(
            self.session, self.managed_root, self.scope, detector=detector
        )

    def frames(
        self, evidence: src.ArtifactEvidence, indices: list[int], detector: str
    ) -> dict[int, list[list[float]]]:
        absolute = Path(self.managed_root) / evidence.relative_path
        return decode_video_frames(absolute, indices, detector=detector)


def _identity(scope: src.VideoScope, detector: str) -> dict[str, Any]:
    return {
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "video_item_id": scope.video_item_id,
        "layer_ref_type": "video_item",
        "layer_ref_id": scope.video_item_id,
        "checkpoint_ref": CHECKPOINT_REF,
    }


def _provenance_env(
    ctx: _Context,
    detector: str,
    *,
    families: Mapping[str, Any],
    derivations: Mapping[str, Any],
) -> dict[str, Any]:
    """The provenance envelope carried with every composed detector args set.

    It travels inside the RUN_QC_CHECKS input manifest (persisted with the
    job) and states exactly which persisted rows/bytes each input came from.
    """
    payload: dict[str, Any] = {
        "schema_version": 1,
        "composer": "mf-p1-qc-evidence",
        "measure_revision": MEASURE_REVISION,
        "detector": detector,
        "workspace_id": ctx.scope.workspace_id,
        "project_id": ctx.scope.project_id,
        "video_item_id": ctx.scope.video_item_id,
        "source_generation": ctx.scope.source_generation,
        "families": dict(families),
        "derivations": dict(derivations),
    }
    payload["input_digest"] = content_digest(payload)
    return payload


#: Exact producer identity of the RENDERED observation side, by the role the
#: render resolver reported (``source_fallback_no_render`` is NOT listed: a
#: source substituted for the rendered output is refused, never measured).
_OBSERVATION_PRODUCERS: dict[str, tuple[str, str]] = {
    "publication": (
        "S10 full-apply (stitch + publication) job",
        "s10_full_apply_publication.artifact_id",
    ),
    "owned_result_artifact": (
        "render-side artifact publication owned by the video item "
        "(artifact purpose 'result' / 'render' / 'publication')",
        "artifact(purpose in ('result','render','publication'), "
        "owner_type='video_item', owner_id=video_item_id)",
    ),
}


def _rendered_output(
    ctx: _Context, detector: str
) -> tuple[src.ArtifactEvidence, str, dict[str, Any]]:
    """Resolve the RENDER artifact the observation side must be measured on.

    The observed side of a QC check is what the OUTPUT contains.  When the
    video has no rendered output distinct from its imported source there is
    nothing to observe — measuring the source against itself would report the
    render as perfect by construction — so this refuses with an exact
    dependency report instead of falling back to the source.
    """
    evidence, role, facts = ctx.render(detector)
    if role not in _OBSERVATION_PRODUCERS:
        raise dependency(
            detector,
            "the video has no rendered output artifact distinct from its "
            "imported source, so the observation side of this check would be "
            "the source itself (a self-comparison against the input), not the "
            "output",
            fact="a rendered output artifact (a completed full-apply "
            "publication, or a published render-side artifact owned by the "
            "video item)",
            producer="S10 full-apply (stitch + publication) job / render-side "
            "artifact publication",
            persistence="s10_full_apply_publication.artifact_id or "
            "artifact(purpose in ('result','render','publication'))",
            video_item_id=ctx.scope.video_item_id,
            resolved_role=role,
        )
    return evidence, role, facts


def _round_half_up(value: Fraction) -> int:
    """Nearest integer of an exact ``Fraction`` (round half up)."""
    if value.numerator < 0:
        return -((2 * -value.numerator + value.denominator) // (2 * value.denominator))
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _frame_ms(ctx: _Context, detector: str) -> Callable[[int], int]:
    """Exact frame → integer-millisecond converter of the canonical timebase."""
    fps_num, fps_den = ctx.scope.fps_num, ctx.scope.fps_den
    if not fps_num or not fps_den:
        raise missing(
            detector,
            "the video item has no persisted canonical timebase "
            "(video_item.fps_num/fps_den are NULL), so a rendered frame "
            "cannot be given an exact presentation timestamp",
            video_item_id=ctx.scope.video_item_id,
        )
    from app.services.timebase import CanonicalTimebase

    timebase = CanonicalTimebase.from_rational(int(fps_num), int(fps_den), classification="CFR")

    def _to_ms(frame: int) -> int:
        return _round_half_up(timebase.frame_to_time(int(frame)) * 1000)

    return _to_ms


def _observation_envelope(
    ctx: _Context,
    detector: str,
    *,
    evidence: src.ArtifactEvidence,
    role: str,
    facts: Mapping[str, Any],
    window: tuple[int, int],
    measure: str,
) -> dict[str, Any]:
    """Provenance of the OBSERVED side: output artifact SHA + range/PTS + producer.

    Carried with every composed argument set whose "observed" values were
    measured on rendered bytes, so a reviewer can trace each observed value to
    the exact output artifact and its frame range / presentation timestamps —
    and cannot mistake a source-side row for an observation.
    """
    producer, persistence = _OBSERVATION_PRODUCERS[role]
    to_ms = _frame_ms(ctx, detector)
    return {
        "schema_version": 1,
        "detector": detector,
        "observation_revision": obs.OBSERVATION_REVISION,
        "artifact": evidence.provenance(),
        "render_role": role,
        "producer": producer,
        "producer_persistence": persistence,
        "producer_facts": dict(facts),
        "window": {"start_frame": int(window[0]), "end_frame": int(window[1])},
        "pts_ms": {
            "start_ms": to_ms(int(window[0])),
            "end_ms": to_ms(int(window[1])),
            "timebase": {"fps_num": int(ctx.scope.fps_num), "fps_den": int(ctx.scope.fps_den)},
        },
        "measure": measure,
    }


# ── per-detector composers ───────────────────────────────────────────────────


def _trajectory_drift(ctx: _Context) -> dict[str, Any]:
    detector = "trajectory_drift"
    # Order matters for the refusal code a caller sees first: when the video
    # has no persisted structural evidence at all, the truthful answer is
    # QC_EVIDENCE_MISSING (no segments were ever published), not a dependency
    # on a render route that the producer was never asked to record.
    ctx.segments(detector)
    routes = ctx.routes(detector)
    route = routes[0]
    segment = ctx.segment_by_id(str(route.occurrence_segment_id), detector)
    width, _height = ctx.scope.canvas(detector)
    indices = window_indices(
        int(route.start_frame), int(route.end_frame), limit=min(ctx.max_frames, 16)
    )
    source = ctx.source(detector)
    render, render_role, render_meta = _rendered_output(ctx, detector)
    source_frames = ctx.frames(source, indices, detector)
    render_frames = ctx.frames(render, indices, detector)
    observed: list[float] = []
    measured_frames: list[int] = []
    reference: list[float] = []
    for index in indices:
        source_frame = source_frames.get(index)
        render_frame = render_frames.get(index)
        if source_frame is None or render_frame is None:
            continue
        centroid = changed_centroid_x(source_frame, render_frame)
        if centroid is None:
            continue
        observed.append(round(centroid, 9))
        reference.append(float(round(float(route.anchor_x) * width, 9)))
        measured_frames.append(index)
    if len(observed) < 2:
        raise missing(
            detector,
            "no measurable rendered delta inside the route window: the render "
            "result carries no composited layer placement to compare against "
            "the persisted anchor",
            frames_examined=indices,
            render_role=render_role,
        )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "reference_x": reference,
        "observed_x": observed,
        "frame_start": measured_frames[0],
        "segment_row_id": str(segment.id),
        "segment_logical_id": str(segment.logical_id),
    }
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(measured_frames[0], measured_frames[-1]),
        measure="observed_x = column centroid of the source to render changed "
        "pixels (|delta| > 0), measured on the decoded RENDER artifact frames; "
        "the source frames are only the change baseline",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "annotation": {
                "route_id": str(route.id),
                "route_revision": int(route.revision),
                "anchor_x": float(route.anchor_x),
                "anchor_y": float(route.anchor_y),
                "source_generation": str(route.source_generation)
                if hasattr(route, "source_generation")
                else ctx.scope.source_generation,
                "frame_range": [int(route.start_frame), int(route.end_frame)],
            },
            "artifact": {
                "source": source.provenance(),
                "render": render.provenance(),
                "render_role": render_role,
                "render_role_facts": render_meta,
            },
            "result": {
                "segment_id": str(segment.id),
                "segment_revision": int(segment.revision),
                "segment_range": [int(segment.start_frame), int(segment.end_frame)],
            },
        },
        derivations={
            "reference_x": "round(route.anchor_x * frame_width) per measured frame",
            "observed_x": "column centroid of source to render changed pixels "
            "(|delta| >= 8 gray levels) per measured frame",
            "measured_frames": measured_frames,
            "reference_digest": content_digest(reference),
            "observed_digest": content_digest(observed),
            "render_observation": "traced to the resolved render artifact "
            "sha256 + frame range/PTS + producer (never to a source-side row)",
        },
    )
    return args


def _cut_drift(ctx: _Context) -> dict[str, Any]:
    detector = "cut_drift"
    # Order matters for the refusal code a caller sees first: when the video
    # has no persisted structural evidence at all, the truthful answer is
    # QC_EVIDENCE_MISSING (no scene rows were ever published), not a
    # dependency on a render the producer was never asked to record.
    scenes = ctx.scenes(detector)
    segments = ctx.segments(detector)
    fps_num, fps_den = ctx.scope.fps_num, ctx.scope.fps_den
    if not fps_num or not fps_den:
        raise missing(
            detector,
            "the video item has no persisted canonical timebase "
            "(video_item.fps_num/fps_den are NULL), so frame to ms conversion "
            "cannot be exact",
            video_item_id=ctx.scope.video_item_id,
        )
    from app.services.timebase import CanonicalTimebase

    timebase = CanonicalTimebase.from_rational(int(fps_num), int(fps_den), classification="CFR")
    boundaries: list[dict[str, int]] = []
    planned_cuts: list[int] = []
    for scene in scenes:
        start_frame = int(scene.start_frame)
        matches = [s for s in segments if int(s.start_frame) == start_frame]
        if len(matches) != 1:
            raise missing(
                detector,
                f"scene position {int(scene.position)} (frame {start_frame}) has "
                f"{len(matches)} matching persisted render segments; the "
                "renderer's own cut time for that boundary cannot be resolved",
                scene_id=str(scene.id),
                scene_position=int(scene.position),
                start_frame=start_frame,
            )
        start_time_ms = matches[0].start_time_ms
        if start_time_ms is None:
            raise malformed(
                detector,
                f"segment {matches[0].id!r} records no start_time_ms",
                segment_id=str(matches[0].id),
            )
        boundaries.append({"position": int(scene.position), "start_frame": start_frame})
        planned_cuts.append(int(start_time_ms))
    # ── OBSERVED side: the cut points the RENDER itself carries ───────────
    # The renderer's planned segment start_time_ms is a PLAN (a source-side
    # row).  The observed cut is measured instead: inside each boundary's
    # neighbourhood the decoded RENDER frames expose the inter-frame delta
    # |render(f) - render(f-1)|, and the frame carrying the largest delta is
    # the cut the output actually shows.
    render, render_role, render_meta = _rendered_output(ctx, detector)
    boundary_frames = [int(row["start_frame"]) for row in boundaries]
    # ── the SEARCH SPAN each boundary supports (round D / NR03) ───────────
    # The annotation fixes the INTENT (scene i starts at frame f_i); the
    # OUTPUT says where the cut actually is.  A ±1-frame search could only
    # ever re-find the planned frame, so the cut the render really carries
    # (moved by N frames, or absent) was unfalsifiable.  Each boundary is
    # searched over the annotation's OWN scene span — from the first frame of
    # the previous scene to the last frame of the scene this boundary opens —
    # bounded to what one composition may decode, and always with
    # CONSECUTIVE frames (a sampled window cannot carry a cut delta).
    budget = max(4, int(ctx.max_frames))
    scene_spans: dict[int, tuple[int, int]] = {}
    for index, scene in enumerate(scenes):
        start = int(scene.start_frame)
        low = int(scenes[index - 1].start_frame) + 1 if index > 0 else start
        span = (max(0, low), int(scene.end_frame))
        if span[1] - span[0] + 1 > budget:
            begin = min(max(span[0], start - budget // 2), span[1] - budget + 1)
            span = (begin, begin + budget - 1)
        scene_spans[start] = span
    wanted: set[int] = set()
    for frame in boundary_frames:
        span = scene_spans.get(frame, (max(0, frame - 1), frame + 1))
        for index in range(span[0], span[1] + 1):
            wanted.add(index - 1)
            wanted.add(index)
    indices = sorted(wanted)[:MAX_WINDOW_FRAMES]
    render_frames = ctx.frames(render, indices, detector)
    to_ms = _frame_ms(ctx, detector)
    observed_cuts: list[int] = []
    cut_observations: list[dict[str, Any]] = []
    for frame in boundary_frames:
        if frame <= 0:
            detail: dict[str, Any] = {
                "frame": 0,
                "delta": None,
                "deltas": {},
                "observed": True,
                "search_span": [0, 0],
                "basis": "video start: the rendered output holds no earlier "
                "frame to measure a cut against",
            }
            observed_frame = 0
        else:
            span = scene_spans.get(frame, (max(0, frame - 1), frame + 1))
            measured = obs.observed_boundary(
                render_frames, frame, span=span, detector=detector
            )
            if not measured.get("observed"):
                raise missing(
                    detector,
                    "the decoded rendered output carries no OBSERVABLE shot "
                    f"change inside the search span {list(span)} around scene "
                    f"boundary frame {frame} ({measured.get('reason')}): the "
                    "planned timecode is never reported as the observed cut, "
                    "and an undominated motion delta is never reported as a "
                    "cut",
                    boundary_frame=frame,
                    search_span=[int(span[0]), int(span[1])],
                    reason=measured.get("reason"),
                    measured=measured,
                    render_artifact_id=render.artifact_id,
                    decoded_frames=indices,
                    render_role=render_role,
                )
            detail = dict(measured)
            observed_frame = int(measured["frame"])
        observed_cuts.append(to_ms(observed_frame))
        cut_observations.append(
            {
                "boundary_frame": frame,
                "observed_frame": observed_frame,
                "observed_cut_ms": to_ms(observed_frame),
                **detail,
            }
        )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "scene_boundaries": boundaries,
        "render_cuts_ms": observed_cuts,
        "timebase": timebase.to_json(),
        "planned_cuts_ms": planned_cuts,
        "cut_observations": cut_observations,
        "cut_search_spans": {
            str(frame): [int(scene_spans[frame][0]), int(scene_spans[frame][1])]
            for frame in boundary_frames
            if frame in scene_spans
        },
    }
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(min(boundary_frames[0], min(scene_spans.values(), key=lambda s: s[0])[0]),
                max(boundary_frames[-1], max(scene_spans.values(), key=lambda s: s[1])[1])),
        measure="render_cuts_ms = exact millisecond of the frame whose "
        "|render(f) - render(f-1)| is the DOMINANT maximum over the "
        "annotation-supported SEARCH SPAN of that boundary (consecutive decoded "
        "RENDER frames; a cut is a step, motion is not), measured on the "
        "decoded RENDER artifact",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "annotation": {
                "scenes": [
                    {
                        "scene_id": str(scene.id),
                        "position": int(scene.position),
                        "start_frame": int(scene.start_frame),
                        "start_time_ms": int(scene.start_time_ms),
                    }
                    for scene in scenes
                ],
                "scene_boundaries": "scene-detector ground truth (the INTENDED "
                "cut positions this check judges the output against)",
            },
            "result": {
                "planned_cut_segments": [
                    {"segment_id": str(m.id), "start_frame": int(m.start_frame),
                     "start_time_ms": int(m.start_time_ms)}
                    for m in segments
                    if int(m.start_frame) in boundary_frames
                ],
                "timebase": {"fps_num": int(fps_num), "fps_den": int(fps_den),
                             "source": "video_item.fps_num/fps_den"},
            },
        },
        derivations={
            "render_cuts_ms": "OBSERVED cut timecodes: the frame of the DOMINANT "
            "|render(f) - render(f-1)| inside each boundary's annotation-supported "
            "search span, on the decoded RENDER artifact; a boundary whose span "
            "carries no dominant discontinuity REFUSES (a motion delta is never "
            "reported as a cut)",
            "cut_search_spans": "the per-boundary search span (annotation scene "
            "span: previous scene start + 1 .. this scene end) the rendered cut "
            "was searched over — the intent comes from the annotation, the "
            "observed cut from the render bytes",
            "planned_cuts_ms": "the renderer's PLANNED occurrence_segment."
            "start_time_ms — recorded for comparison only; a planned value is "
            "never reported as an observed cut",
            "cut_observations": cut_observations,
        },
    )
    return args


def _contact_break(ctx: _Context) -> dict[str, Any]:
    detector = "contact_break"
    contacts = ctx.contacts(detector)
    contact = contacts[0]
    left = ctx.segment_by_id(str(contact.source_segment_id), detector)
    right = ctx.segment_by_id(str(contact.target_segment_id), detector)
    window_start = max(int(contact.start_frame), int(left.start_frame), int(right.start_frame))
    window_end = min(int(contact.end_frame), int(left.end_frame), int(right.end_frame))
    if window_end < window_start:
        raise malformed(
            detector,
            "contact range and its two segments do not overlap; the annotation "
            "cannot be judged against the persisted segment windows",
            contact_id=str(contact.id),
        )
    indices = window_indices(window_start, window_end, limit=min(ctx.max_frames, 16))
    # ── OBSERVED side: where the RENDER actually paints the two segments ──
    # The annotated mask region says WHERE to look; the geometry that is
    # judged is measured on the decoded rendered output inside that region.
    render, render_role, render_meta = _rendered_output(ctx, detector)
    # The imported source is still READ (its absence must refuse, never be
    # ignored) but it is only the change baseline: the contact geometry below
    # is measured on the object pixels the RENDER itself paints (round D /
    # NR03 — "differs from the source inside the expected box" is not evidence
    # that the actor is in the output).
    source = ctx.source(detector)
    render_frames = ctx.frames(render, indices, detector)
    if not render_frames:
        raise missing(
            detector,
            "no rendered frame decodes inside the contact analysis window, so "
            "the rendered contact geometry cannot be observed",
            frames_examined=indices,
            render_artifact_id=render.artifact_id,
            render_role=render_role,
        )
    segments_payload: list[dict[str, Any]] = []
    mask_provenance: list[dict[str, Any]] = []
    observed_total = 0
    for segment in (left, right):
        evidence, _matrix, _width, _height, bbox = ctx.mask(
            segment.mask_artifact_id, detector
        )
        mask_provenance.append(evidence.provenance())
        expected_bbox = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
        observed_frames: list[list[int] | None] = []
        background_levels: list[float | None] = []
        for index in indices:
            render_frame = render_frames.get(index)
            if render_frame is None:
                observed_frames.append(None)
                background_levels.append(None)
                continue
            measured = obs.rendered_object_bbox(
                render_frame, region=bbox, detector=detector
            )
            background_levels.append(
                round(obs.background_level(render_frame, detector=detector), 9)
            )
            observed_frames.append(
                [int(measured[0]), int(measured[1]), int(measured[2]), int(measured[3])]
                if measured is not None
                else None
            )
        observed_total += sum(1 for row in observed_frames if row is not None)
        segments_payload.append(
            {
                "id": str(segment.id),
                "logical_id": str(segment.logical_id),
                "z_order": int(segment.z_order),
                "start_frame": int(segment.start_frame),
                "end_frame": int(segment.end_frame),
                "mask_artifact_id": evidence.artifact_id,
                "bbox_per_frame": observed_frames,
                "expected_bbox_per_frame": [list(expected_bbox) for _ in indices],
                "render_background_level_per_frame": background_levels,
                "measured_on": "rendered_object_pixels: the bbox of the pixels "
                "the RENDER paints over its OWN dominant level, seeded by the "
                "annotated mask region and grown over the contiguous object "
                "(never the source-difference inside the expected box)",
            }
        )
    if observed_total == 0:
        raise dependency(
            detector,
            "the rendered output paints NO object inside the annotated contact "
            "regions over the analysis window, so the contact geometry of the "
            "output cannot be observed",
            fact="rendered object pixels (the composited output) inside the "
            "annotated contact regions of the two segments",
            producer="S10 full-apply (stitch + publication) job / render-side "
            "artifact publication",
            persistence="artifact bytes of the video's rendered result",
            window={"start_frame": indices[0], "end_frame": indices[-1]},
            render_role=render_role,
        )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "analysis_window": {"start_frame": indices[0], "end_frame": indices[-1]},
        "contacts": [
            {
                "id": str(contact.id),
                "source_segment_id": str(contact.source_segment_id),
                "target_segment_id": str(contact.target_segment_id),
                "contact_kind": str(contact.contact_kind),
                "start_frame": int(contact.start_frame),
                "end_frame": int(contact.end_frame),
                "confidence": float(contact.confidence),
                "confidence_source": str(contact.confidence_source),
            }
        ],
        "segments": segments_payload,
    }
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(indices[0], indices[-1]),
        measure="bbox_per_frame = measured bbox of the object the RENDER itself "
        "paints inside the segment's annotated mask region, per decoded RENDER "
        "frame (null where the output paints no object there); the object is "
        "defined against the render's OWN dominant level, never against the "
        "imported source",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "annotation": {
                "contact_id": str(contact.id),
                "contact_revision": int(contact.revision),
                "contact_kind": str(contact.contact_kind),
                "contact_range": [int(contact.start_frame), int(contact.end_frame)],
                "contacts_available": len(contacts),
                "expected_bbox_per_frame": "the persisted mask bbox of each "
                "segment (the ANNOTATED region the observation is measured "
                "inside — never reported as the observed geometry)",
            },
            "result": {
                "segments": [
                    {"id": str(s.id), "revision": int(s.revision),
                     "range": [int(s.start_frame), int(s.end_frame)]}
                    for s in (left, right)
                ],
            },
            "artifact": {"masks": mask_provenance},
            "change_baseline": {
                "source": source.provenance(),
                "note": "the imported source is read as the change BASELINE "
                "only; the contact geometry is measured on the render's own "
                "object pixels and a source-side box is never reported as the "
                "observation",
            },
        },
        derivations={
            "analysis_window": f"contact intersected with both segment windows, "
            f"bounded to {len(indices)} frames",
            "bbox_per_frame": "OBSERVED rendered geometry per frame: the bbox "
            "of the pixels the output paints over the render's OWN dominant "
            "level, seeded by the annotated mask region; the annotated mask "
            "bbox is recorded separately as expected_bbox_per_frame",
            "render_background_level_per_frame": "the render's own dominant "
            "level per measured frame (the object definition is measured on the "
            "output bytes)",
        },
    )
    return args


def _z_order_error(ctx: _Context) -> dict[str, Any]:
    detector = "z_order_error"
    segments = ctx.segments(detector)
    edges = ctx.occlusions(detector)
    for edge in edges:
        ctx.segment_by_id(str(edge.occluder_segment_id), detector)
        ctx.segment_by_id(str(edge.occludee_segment_id), detector)
    window_start = min(int(edge.start_frame) for edge in edges)
    window_end = max(int(edge.end_frame) for edge in edges)
    manifest = src.current_lock_manifest(ctx.session, ctx.scope)
    manifest_expected: dict[str, Any] | None = None
    if manifest is not None:
        from app.persistence.structural_lock import validate_manifest

        try:
            validated = validate_manifest(dict(manifest.manifest))
        except Exception as exc:
            raise malformed(
                detector,
                f"the current S09 structural lock manifest {manifest.id!r} does "
                f"not validate through the public S09 contract: {exc}",
                manifest_id=str(manifest.id),
            ) from exc
        manifest_expected = {
            "manifest_id": str(manifest.id),
            "version": int(manifest.version),
            "manifest_hash_hex": str(manifest.manifest_hash_hex),
            "status": str(manifest.status),
            "validated_order": [
                str(seg["occurrence_segment_id"]) for seg in validated["segments"]
            ],
            "authority": "PLANNED lock manifest (annotation) — recorded for "
            "comparison; the observed render order is measured from the output "
            "bytes and is what the detector judges",
        }
    # ── OBSERVED side: the stacking the RENDER actually paints ────────────
    render, render_role, render_meta = _rendered_output(ctx, detector)
    source = ctx.source(detector)
    indices = window_indices(window_start, window_end, limit=min(ctx.max_frames, 16))
    source_frames = ctx.frames(source, indices, detector)
    render_frames = ctx.frames(render, indices, detector)
    by_id = {str(segment.id): segment for segment in segments}
    masks: dict[str, Any] = {}
    mask_provenance: list[dict[str, Any]] = []
    pairs: list[tuple[str, str]] = []
    for edge in edges:
        occluder = str(edge.occluder_segment_id)
        occludee = str(edge.occludee_segment_id)
        for segment_id in (occluder, occludee):
            if segment_id not in masks:
                evidence, matrix, _mw, _mh, _mbbox = ctx.mask(
                    by_id[segment_id].mask_artifact_id, detector
                )
                masks[segment_id] = matrix
                mask_provenance.append(
                    {**evidence.provenance(), "segment_id": segment_id}
                )
        if (occluder, occludee) not in pairs:
            pairs.append((occluder, occludee))
    measurements = obs.measured_stacking(
        source_frames, render_frames, masks, pairs, detector=detector
    )
    render_order = obs.stacking_order(
        measurements, others=[str(segment.id) for segment in segments], detector=detector
    )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "analysis_window": {"start_frame": window_start, "end_frame": window_end},
        "segments": [
            {
                "id": str(segment.id),
                "z_order": int(segment.z_order),
                "start_frame": int(segment.start_frame),
                "end_frame": int(segment.end_frame),
            }
            for segment in segments
        ],
        "occlusion_edges": [
            {
                "id": str(edge.id),
                "occluder_segment_id": str(edge.occluder_segment_id),
                "occludee_segment_id": str(edge.occludee_segment_id),
                "start_frame": int(edge.start_frame),
                "end_frame": int(edge.end_frame),
                "confidence": float(edge.confidence),
                "confidence_source": str(edge.confidence_source),
            }
            for edge in edges
        ],
        "render_order": render_order,
        "render_stacking": measurements,
    }
    if manifest_expected is not None:
        args["lock_manifest_expected"] = manifest_expected
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(window_start, window_end),
        measure="render_order = bottom-to-top order implied by the MEASURED "
        "stacking of every occlusion pair (the region where the two annotated "
        "masks overlap is attributed to whichever segment's exclusive rendered "
        "appearance it matches), measured on the decoded RENDER artifact",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "result": {
                "segments": [
                    {"id": str(s.id), "z_order": int(s.z_order),
                     "range": [int(s.start_frame), int(s.end_frame)]}
                    for s in segments
                ],
            },
            "annotation": {
                "occlusion_edges": [
                    {"id": str(e.id), "range": [int(e.start_frame), int(e.end_frame)],
                     "confidence_source": str(e.confidence_source)}
                    for e in edges
                ],
                "lock_manifest": manifest_expected,
            },
            "artifact": {
                "pair_masks": mask_provenance,
            },
        },
        derivations={
            "render_order": "OBSERVED bottom-to-top order measured from the "
            "rendered bytes (never the persisted scene-graph z_order and never "
            "the planned S09 manifest)",
            "render_stacking": measurements,
            "window": [window_start, window_end],
        },
    )
    return args


def _rendered_role_extent(
    ctx: _Context,
    detector: str,
    *,
    expected: src.ArtifactEvidence,
    role_bbox: tuple[int, int, int, int],
    canvas: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    """Measured extent of the role's RENDERED-side published mask, if any.

    Candidate discovery is the SAME authority rule ``edge_halo`` already
    consumes (``sources.rendered_minus_expected_masks``): a byte-DISTINCT
    published mask artifact that bounds the role's own region.  ``None`` when
    the video publishes no rendered-side mask for this role — the caller then
    refuses instead of attributing the cut rendered object to the role.
    """
    width, height = int(canvas[0]), int(canvas[1])
    for candidate in src.rendered_minus_expected_masks(
        ctx.session, ctx.scope, expected_id=expected.artifact_id
    ):
        evidence = src.read_artifact(
            ctx.session, ctx.managed_root, ctx.scope, candidate, detector=detector
        )
        if evidence.sha256 == expected.sha256:
            continue
        matrix, candidate_width, candidate_height = decode_png_gray(
            evidence.data, detector=detector
        )
        if (candidate_width, candidate_height) != (width, height):
            raise malformed(
                detector,
                f"rendered-side role mask {evidence.artifact_id!r} is "
                f"{candidate_width}x{candidate_height} but the video canvas is "
                f"{width}x{height}; geometry mismatch (fail closed)",
                artifact_id=evidence.artifact_id,
            )
        candidate_bbox = mask_bbox(matrix)
        if not _bbox_overlaps(candidate_bbox, role_bbox):
            continue
        return candidate_bbox
    return None


def _silhouette_clipping(ctx: _Context) -> dict[str, Any]:
    detector = "silhouette_clipping"
    segments = ctx.segments(detector)
    width, height = ctx.scope.canvas(detector)
    window_start = min(int(segment.start_frame) for segment in segments)
    window_end = max(int(segment.end_frame) for segment in segments)
    # ── OBSERVED side: the silhouette the RENDER actually paints ──────────
    render, render_role, render_meta = _rendered_output(ctx, detector)
    source = ctx.source(detector)
    payload: list[dict[str, Any]] = []
    masks: list[dict[str, Any]] = []
    for segment in segments:
        evidence, role_support, mask_w, mask_h, bbox = ctx.mask(
            segment.mask_artifact_id, detector
        )
        if (mask_w, mask_h) != (width, height):
            raise malformed(
                detector,
                f"segment {segment.id!r} mask is {mask_w}x{mask_h} but the video "
                f"canvas is {width}x{height}; geometry mismatch (fail closed)",
                segment_id=str(segment.id),
            )
        # Role/segment/frame binding: the geometry this role is measured with
        # must be THIS segment's own published mask.  A mask artifact that is
        # another current segment's published geometry binds the role to a
        # different role's region — the measurement would then report that
        # other role's silhouette as this one's (refuse, never measure).
        for other in segments:
            if str(other.id) == str(segment.id):
                continue
            if str(other.mask_artifact_id) == str(evidence.artifact_id):
                raise malformed(
                    detector,
                    f"segment {segment.id!r}'s mask artifact "
                    f"{evidence.artifact_id!r} is the published mask of segment "
                    f"{other.id!r}; the role/segment/frame binding is "
                    "inconsistent, so this region is not this role's geometry",
                    segment_id=str(segment.id),
                    conflicting_segment_id=str(other.id),
                    artifact_id=str(evidence.artifact_id),
                )
        masks.append(evidence.provenance())
        indices = window_indices(
            int(segment.start_frame),
            int(segment.end_frame),
            limit=min(ctx.max_frames, 8),
        )
        render_frames = ctx.frames(render, indices, detector)
        observed: tuple[int, int, int, int] | None = None
        observed_frames: list[int] = []
        background_levels: list[float | None] = []
        for index in indices:
            render_frame = render_frames.get(index)
            if render_frame is None:
                background_levels.append(None)
                continue
            background_levels.append(
                round(obs.background_level(render_frame, detector=detector), 9)
            )
            # The RENDER's own object pixels are the geometry authority: the
            # annotation seeds WHERE to look, and the window grows over the
            # contiguous object so a silhouette the output clips at the frame
            # border carries its REAL extent (round D / NR03).
            #
            # R27-04: the object is measured only inside the ROLE'S OWN
            # published support (segment mask), and `region` must BE that
            # support's own measured extent — a region that is not this role's
            # persisted geometry is refused instead of becoming "the object".
            measured = obs.supported_object_bbox(
                render_frame,
                support=role_support,
                region=bbox,
                detector=detector,
            )
            if measured is None:
                continue
            observed_frames.append(index)
            if observed is None:
                observed = measured
            else:
                observed = (
                    min(observed[0], measured[0]),
                    min(observed[1], measured[1]),
                    max(observed[2], measured[2]),
                    max(observed[3], measured[3]),
                )
        if observed is None:
            raise dependency(
                detector,
                f"the rendered output paints NO object inside segment "
                f"{segment.id!r}'s annotated region over the frames it is "
                "present in; judging its clipping from the source mask (or from "
                "'the output differs from the source here') would substitute the "
                "annotation for the observation",
                fact="rendered object pixels (the output's own content, "
                "measured against the render's dominant level) inside the "
                "segment's annotated silhouette region",
                producer="S10 full-apply (stitch + publication) job / render-side "
                "artifact publication",
                persistence="artifact bytes of the video's rendered result",
                segment_id=str(segment.id),
                frame_window=[
                    int(segment.start_frame),
                    int(segment.end_frame),
                ],
                background_levels=background_levels,
            )
        contact = obs.border_contact(observed, (int(height), int(width)))
        authority = obs.clipping_authority(
            observed,
            role_extent=bbox,
            rendered_role_extent=(
                None
                if not contact
                else _rendered_role_extent(
                    ctx,
                    detector,
                    expected=evidence,
                    role_bbox=bbox,
                    canvas=(int(width), int(height)),
                )
            ),
            shape=(int(height), int(width)),
            detector=detector,
        )
        if authority["verdict"] == obs.GEOMETRY_UNATTRIBUTABLE:
            raise dependency(
                detector,
                f"the rendered object inside segment {segment.id!r}'s region "
                "reaches the frame side(s) "
                f"{authority['sides_not_reached_by_role_extent']} that the role's "
                "own published extent does NOT reach, and no rendered-side role "
                "mask exists to attribute the cut content to this role: the "
                "observation has no authority, and the frozen metric (bbox area "
                "OUTSIDE the frame) would hand a frame-bounded bbox to the "
                "detector as a measured clipped_ratio of 0 — a cut object read "
                "as zero risk",
                fact="a rendered-side role mask (object-correction publication) "
                "attributing the cut rendered content to this role",
                producer="object-correction mask publication (publishes a NEW "
                "mask artifact per corrected role)",
                persistence="artifact(kind='image', purpose='mask', "
                "owner_type='video_item') + re-verified sha256/size",
                segment_id=str(segment.id),
                contact_sides=authority["contact_sides"],
                observed_bbox=[int(v) for v in observed],
                role_extent_bbox=[int(v) for v in bbox],
                clipping_authority=authority,
            )
        payload.append(
            {
                "id": str(segment.id),
                "logical_id": str(segment.logical_id),
                "start_frame": int(segment.start_frame),
                "end_frame": int(segment.end_frame),
                "mask_artifact_id": evidence.artifact_id,
                "bbox": [int(v) for v in observed],
                "expected_bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                "observed_frames": observed_frames,
                "render_background_level_per_frame": background_levels,
                "border_contact": contact,
                "clipping_authority": authority,
                "measured_on": "rendered_object_pixels: the bbox of the pixels "
                "the RENDER paints over its OWN dominant level, seeded by the "
                "annotated mask region and grown over the contiguous object "
                "(never the source-difference inside the expected box)",
            }
        )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "analysis_window": {"start_frame": window_start, "end_frame": window_end},
        "frame": {"width": int(width), "height": int(height)},
        "segments": payload,
    }
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(window_start, window_end),
        measure="bbox = union of the per-frame measured bboxes of the object the "
        "RENDER itself paints (pixels over the render's OWN dominant level) "
        "inside the segment's annotated mask region, measured on the decoded "
        "RENDER artifact frames of that segment window; border_contact records "
        "the frame sides the measured object reaches",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "source": {
                "canvas": {"width": int(width), "height": int(height),
                           "provenance": "video_item.width/height (probed at import)"},
            },
            "result": {
                "segments": [
                    {"id": str(s.id), "revision": int(s.revision),
                     "range": [int(s.start_frame), int(s.end_frame)]}
                    for s in segments
                ],
            },
            "artifact": {"masks": masks},
            "change_baseline": {
                "source": source.provenance(),
                "note": "read as the change BASELINE only; the silhouette "
                "geometry is measured on the render's own object pixels",
            },
        },
        derivations={
            "clipping_authority": "per-segment geometry AUTHORITY: a frame side "
            "the ROLE'S OWN published extent reaches is source-intended partial "
            "visibility (the character is legitimately at/over that edge in the "
            "source, so it is NOT new truncation); a side only the RENDER reaches "
            "is newly introduced truncation and is FLAGGED here (the frozen "
            "metric is bbox area OUTSIDE the frame and a pixel-measured bbox is "
            "frame-bounded, so the ratio can never carry it); when nothing "
            "attributes the cut content to the role the composer refuses with "
            "QC_EVIDENCE_DEPENDENCY instead of reporting a 0 PASS",
            "bbox": "OBSERVED silhouette geometry: the measured bbox of the "
            "object the RENDER paints over its own dominant level inside the "
            "annotated mask region (never the annotation itself and never the "
            "source-difference; expected_bbox records the annotation)",
            "border_contact": "the frame sides the measured object reaches — a "
            "pixel-measured bbox can never lie outside the frame, so border "
            "contact is the observable clipping signal of the output",
            "expected_bbox": "the persisted mask bbox (annotation of where the "
            "object is, recorded for comparison only)",
        },
    )
    args["clipping_authority"] = {
        "rule": "a frame side the ROLE'S OWN published extent reaches is "
        "source-intended partial visibility and is not new truncation; a side "
        "only the RENDER reaches is newly introduced truncation and is flagged "
        "(the frozen metric is bbox area OUTSIDE the frame, so a frame-bounded "
        "cut can never appear as a positive clipped_ratio); when nothing "
        "attributes the cut content to the role the composer refuses "
        "(QC_EVIDENCE_DEPENDENCY) instead of reporting 0",
        "per_segment": [
            {
                "segment_id": row["id"],
                "verdict": row["clipping_authority"]["verdict"],
                "contact_sides": row["clipping_authority"]["contact_sides"],
                "detector_clearance": row["clipping_authority"]["detector_clearance"],
                "newly_introduced_truncation": row["clipping_authority"][
                    "newly_introduced_truncation"
                ],
            }
            for row in payload
        ],
        "newly_introduced_truncation": sorted(
            row["id"]
            for row in payload
            if row["clipping_authority"]["newly_introduced_truncation"]
        ),
        "observation_revision": obs.OBSERVATION_REVISION,
    }
    return args


def _pixel_rms(left: Any, right: Any, *, detector: str) -> float:
    """RMS pixel distance (unit px) between two same-geometry gray crops.

    Reproduces the deterministic local-feature distance of the frozen
    ``app.services.qc_checks.identity_drift`` detector byte-for-byte
    (``sqrt(mean((a-b)^2))`` over the flattened crop), so the composer's
    per-role measurement is the SAME quantity the detector judges — a
    per-role verdict that could not be reproduced by the detector's own
    definition would be an invented metric.
    """
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        raise malformed(
            detector,
            f"crop geometries {a.shape} and {b.shape} differ (or are empty); "
            "the rendered identity distance cannot be measured (fail closed)",
        )
    return round(float(np.sqrt(np.square(a - b).mean())), 9)


def _classify_identity(value: float, *, detector: str) -> dict[str, Any]:
    """Per-role verdict from the FROZEN T03A policy (read-only consume).

    The composer invents no boundary: it asks the same frozen ``thresholds``
    module the detector asks.  A policy that cannot answer is a typed refusal
    (never a fabricated verdict, never a pass).  Imported lazily so the
    evidence package keeps no import-time dependency on the detector band.
    """
    from app.services.qc_checks.thresholds import classify, get_threshold

    try:
        entry = get_threshold("identity_drift")
        status, code = classify("identity_drift", float(value))
    except Exception as exc:
        raise dependency(
            detector,
            "the frozen T03A policy could not classify the measured identity "
            "distance, so no per-role identity verdict exists; reporting a "
            "verdict anyway would fabricate it",
            fact="the frozen identity_drift threshold entry "
            "(app.services.qc_checks.thresholds)",
            producer="S11-T03A policy registry (read-only)",
            persistence="app/services/qc_checks/thresholds.py (frozen policy)",
            policy_error_type=type(exc).__name__,
            policy_error=str(exc)[:300],
        ) from exc
    return {
        "status": status,
        "code": code,
        "metric": "identity_drift",
        "value": round(float(value), 9),
        "unit": entry["unit"],
        "warning_boundary": entry["warning_boundary"],
        "blocker_boundary": entry["blocker_boundary"],
        "source": "app.services.qc_checks.thresholds.classify (frozen T03A "
        "policy, read-only)",
    }


def _verdict_summary(verdict: Any) -> dict[str, Any]:
    """Status/code/value of a frozen-policy verdict, without a second copy.

    The FULL verdict object (boundaries, sanity bounds, policy source) is
    recorded ONCE per role in ``identity_measurements[].verdict``; the derived
    coverage reports and provenance families carry this summary so the
    argv-transported set does not ship the same block seven times.
    """
    if not isinstance(verdict, dict):
        return {"status": None, "code": None}
    return {
        "status": verdict.get("status"),
        "code": verdict.get("code"),
        "value": verdict.get("value"),
        "unit": verdict.get("unit"),
    }


def _pin_record(
    entry: dict[str, Any], *, include_contract: bool = False
) -> dict[str, Any]:
    """The FULL pinned cast target of one role (the cast-pin identity record).

    This is the one place the per-role pin travels with its declared
    pose/reference mapping and the public cast contract's compatibility
    verdict; the coverage reports carry the bounded per-role summary instead.
    """
    artifact = dict(entry.get("reference_artifact") or {})
    return {
        "object_role_id": str(entry["object_role_id"]),
        "mapping_id": str(entry.get("mapping_id")),
        "character_id": str(entry.get("character_id")),
        "pack_version_id": str(entry.get("pack_version_id")),
        "pack_version_status": entry.get("pack_version_status"),
        "pose_slot": str(entry.get("pose_slot")),
        "reference_asset_id": str(entry.get("reference_asset_id")),
        "reference_slot_source": str(entry.get("reference_slot_source")),
        "reference_slot_mapping": [
            str(v) for v in entry.get("reference_slot_mapping") or []
        ],
        "reference_artifact": {
            "artifact_id": artifact.get("artifact_id"),
            "sha256": artifact.get("sha256"),
            "size_bytes": artifact.get("size_bytes"),
            "bytes_reverified": artifact.get("bytes_reverified"),
        },
        "compatible": bool(entry.get("compatible")),
        "compatibility_reasons": [str(v) for v in entry.get("reasons") or []],
        "segment_row_ids": [str(v) for v in entry.get("segment_row_ids") or []],
        **(
            {"compatibility": dict(entry.get("compatibility") or {})}
            if include_contract
            else {}
        ),
    }


def _pin_coverage_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Bounded per-role summary of the pinned coverage report.

    The full pin record travels once, in ``cast_pin.cast_coverage``; this row
    keeps the role / character / pack version / reference facts the coverage
    report is read for.
    """
    artifact = dict(entry.get("reference_artifact") or {})
    return {
        "object_role_id": str(entry["object_role_id"]),
        "character_id": str(entry.get("character_id")),
        "pack_version_id": str(entry.get("pack_version_id")),
        "pose_slot": str(entry.get("pose_slot")),
        "reference_artifact_id": artifact.get("artifact_id"),
        "reference_artifact_sha256": artifact.get("sha256"),
    }


def _coverage_provenance_digest(report: dict[str, Any]) -> dict[str, Any]:
    """Per-role digest of a coverage report, for the provenance family.

    ``pin_coverage`` and ``measured_coverage`` are recorded ONCE per detector
    set (top level); the provenance family carries the per-role summary so the
    argv-transported set never ships the same report twice.
    """
    rows: dict[str, Any] = {}
    per_role = report.get("per_role") or {}
    if per_role:
        for role, row in per_role.items():
            verdict = _verdict_summary(row.get("verdict"))
            rows[str(role)] = {
                "status": verdict["status"],
                "code": verdict["code"],
                "measured_distance_px": row.get("measured_distance_px"),
            }
    else:
        # the pinned report is already per-role and bounded at top level:
        # ``roles`` + ``full_report_at`` are the digest here.
        rows = {}
    return {
        "kind": report.get("kind"),
        "scope": report.get("scope"),
        "count": report.get("count"),
        "roles": [str(role) for role in report.get("roles") or []],
        "uncovered_role_ids": list(report.get("uncovered_role_ids") or []),
        "per_role": rows,
        "full_report_at": (
            "pin_coverage" if report.get("kind") == "pinned" else "measured_coverage"
        ),
    }


def _identity_drift(ctx: _Context) -> dict[str, Any]:
    detector = "identity_drift"
    segments = ctx.segments(detector)
    # ── TARGET IDENTITY (finding R4): the library pin, per role ───────────
    # The video's own source frames are the MOTION authority.  The identity
    # authority is the SELECTED library target of EVERY role the video renders:
    # the project cast pin (CharacterID + immutable PackVersion) and that pack
    # version's REFERENCE bytes, resolved through the declared pose/reference
    # mapping (round D / NR04).  Coverage is enumerated per role — a
    # first-segment-only identity is never reported as the entire cast, and a
    # role whose pin is missing / incompatible refuses the whole composition.
    identities: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    for row in segments:
        role_id = str(row.role_id)
        if role_id in identities:
            continue
        pin = src.cast_pin_for_role(
            ctx.session, ctx.managed_root, ctx.scope, role_id, detector=detector
        )
        if pin["compatible"] is not True:
            raise stale(
                detector,
                f"the pinned cast target for object role {role_id!r} is not "
                "compatible with this video's target "
                f"({', '.join(pin['reasons']) or 'no reason reported'}), so the "
                "rendered identity cannot be judged against it",
                role_id=role_id,
                mapping_id=str(pin["mapping_id"]),
                reasons=list(pin["reasons"]),
                compatibility=dict(pin["compatibility"]),
            )
        identities[role_id] = pin
        entry = src.pin_identity(pin)
        entry["segment_row_ids"] = [
            str(s.id) for s in segments if str(s.role_id) == role_id
        ]
        coverage.append(entry)
    render, render_role, render_meta = _rendered_output(ctx, detector)
    # ── MEASURED identity: ONE measurement per rendered role (NR04) ───────
    # Round C enumerated every role's PIN but measured only the role of the
    # first segment; the other roles carried whole-frame luma metadata the
    # detector never consumes, so corrupting a later role's pixels changed
    # nothing that was judged.  Each role is now measured against ITS OWN
    # pinned reference, over ITS OWN segment window, on the render bytes.
    measurements: list[dict[str, Any]] = []
    for entry in coverage:
        role_id = str(entry["object_role_id"])
        pin = identities[role_id]
        role_segment = next(s for s in segments if str(s.role_id) == role_id)
        role_reference = src.pin_reference(pin)
        reference_matrix, reference_w, reference_h = decode_png_gray(
            role_reference.data, detector=detector
        )
        _mask_evidence, _mask_matrix, _mask_w, _mask_h, role_bbox = ctx.mask(
            role_segment.mask_artifact_id, detector
        )
        role_window = _bounded_window(role_bbox)
        if obs.clamp_region(role_window, (reference_h, reference_w)) != role_window:
            raise malformed(
                detector,
                f"the pinned library reference artifact "
                f"{role_reference.artifact_id!r} of object role {role_id!r} "
                f"({reference_w}x{reference_h}) does not cover the measured "
                f"segment window {list(role_window)}; this role's identity "
                "cannot be compared against the rendered crop (fail closed)",
                role_id=role_id,
                artifact_id=role_reference.artifact_id,
                reference_geometry=[int(reference_w), int(reference_h)],
                window=[int(v) for v in role_window],
            )
        reference_crop = crop_region(reference_matrix, role_window)
        role_indices = window_indices(
            int(role_segment.start_frame),
            int(role_segment.end_frame),
            limit=min(ctx.max_frames, 4),
        )
        role_frames = ctx.frames(render, role_indices, detector)
        rendered_frames: list[dict[str, Any]] = []
        for index in sorted(role_frames):
            crop = _crop(role_frames[index], role_window)
            rendered_frames.append(
                {
                    "frame_index": int(index),
                    "sha256": crop_sha256(crop),
                    "distance_to_own_reference_px": _pixel_rms(
                        crop, reference_crop, detector=detector
                    ),
                    "crop": {
                        "pixels": crop,
                        "width": len(crop[0]),
                        "height": len(crop),
                    },
                    "metadata": {},
                }
            )
        if not rendered_frames:
            raise missing(
                detector,
                f"no decodable rendered frame inside object role {role_id!r}'s "
                "own segment window; that role's rendered identity evidence "
                "cannot be measured — an UNMEASURED role is never reported as "
                "measured coverage",
                role_id=role_id,
                frames_examined=role_indices,
                render_artifact_id=render.artifact_id,
            )
        own_reference = [row["distance_to_own_reference_px"] for row in rendered_frames]
        own_adjacent = [
            _pixel_rms(
                rendered_frames[i]["crop"]["pixels"],
                rendered_frames[i - 1]["crop"]["pixels"],
                detector=detector,
            )
            for i in range(1, len(rendered_frames))
        ]
        measured_distance = max([*own_reference, *own_adjacent])
        verdict = _classify_identity(measured_distance, detector=detector)
        measurements.append(
            {
                "object_role_id": role_id,
                "segment_row_id": str(role_segment.id),
                "render_artifact_id": str(render.artifact_id),
                "reference_artifact_id": str(role_reference.artifact_id),
                "reference_artifact_sha256": str(role_reference.sha256),
                "reference_pose_slot": str(pin["pose_slot"]),
                "reference_slot_source": str(pin["reference_slot_source"]),
                "reference_crop": {
                    "sha256": crop_sha256(reference_crop),
                    "width": len(reference_crop[0]),
                    "height": len(reference_crop),
                    "pixels": reference_crop,
                },
                "crop_geometry": {
                    "reference": [int(reference_w), int(reference_h)],
                    "window": [int(v) for v in role_window],
                },
                "rendered_frames": rendered_frames,
                "frames_measured": [row["frame_index"] for row in rendered_frames],
                "reference_distance_max_px": round(float(max(own_reference)), 9),
                "max_adjacent_distance_px": round(
                    float(max(own_adjacent)) if own_adjacent else 0.0, 9
                ),
                "measured_distance_px": measured_distance,
                "verdict": verdict,
                "measured_on": "the resolved RENDER artifact bytes, inside this "
                "role's own segment window (never the source, never another "
                "role's window)",
            }
        )
    # ── bound the argv-transported payload (round D size regression) ────────
    # The composed argument set travels to the detector as a CHILD-PROCESS
    # argument (``app/services/qc_checks/runner.py`` hands it over as
    # ``sys.argv[2]``), so it has to stay inside the Windows command-line
    # ceiling.  Measured on this host: a 32,500-char argument spawns, a
    # 32,700-char argument raises ``FileNotFoundError: [WinError 206]``.
    # Round D measured 66,664 B here and blew that ceiling.  The raw pixel
    # payload now travels ONCE, exactly where the frozen detector consumes
    # it: ``pinned_reference.crop`` (the primary role's reference crop) and
    # ``frames[].crop`` (the primary role's rendered crops).  NR04 is
    # unchanged — EVERY role still carries its own crop sha256, its own
    # measured distance, its own window and the frozen policy's own verdict;
    # the same bytes are simply never shipped twice.
    primary_reference_pixels = measurements[0]["reference_crop"]["pixels"]
    primary_frame_payloads = [
        dict(frame["crop"]) for frame in measurements[0]["rendered_frames"]
    ]
    for row in measurements:
        row["reference_crop"] = {
            "sha256": row["reference_crop"]["sha256"],
            "width": row["reference_crop"]["width"],
            "height": row["reference_crop"]["height"],
            "crop_payload": "digest_only",
            "pixels_in_manifest": (
                "pinned_reference.crop" if row is measurements[0] else "digest_only"
            ),
            "rendered_crop_payload": "digest_only",
        }
        for frame in row["rendered_frames"]:
            frame.pop("crop", None)
    # ── the PRIMARY block: the role of the FIRST current segment ──────────
    # The frozen detector consumes exactly one reference + one frame list (the
    # persisted ``segment_row_id`` contract of this check), so the primary
    # block keeps covering the role of the first current segment.  Coverage is
    # NOT claimed from it: every rendered role carries its OWN measurement in
    # ``identity_measurements``, and the fail-closed aggregate over all of them
    # is reported as ``measured_coverage.aggregate_distance_px`` (max).
    primary = measurements[0]
    worst = measurements[0]
    for row in measurements:
        if float(row["measured_distance_px"]) > float(worst["measured_distance_px"]):
            worst = row
    primary_role_id = str(primary["object_role_id"])
    identity = identities[primary_role_id]
    reference = src.pin_reference(identity)
    segment = next(s for s in segments if str(s.role_id) == primary_role_id)
    reference_crop = primary_reference_pixels
    window = (
        int(primary["crop_geometry"]["window"][0]),
        int(primary["crop_geometry"]["window"][1]),
        int(primary["crop_geometry"]["window"][2]),
        int(primary["crop_geometry"]["window"][3]),
    )
    # The frozen detector compares EVERY consumed frame's ``metadata`` with
    # ``cast_pin.expected_metadata`` (and copies both into the item evidence
    # when an identity flip fires), so this block is the metadata contract and
    # is deliberately small: it is repeated once per consumed frame.
    identity_metadata: dict[str, Any] = {
        "object_role_id": primary_role_id,
        "reference_artifact_id": str(reference.artifact_id),
        "reference_sha256": str(reference.sha256),
        "reference_pose_slot": str(identity["pose_slot"]),
        "reference_slot_source": str(identity["reference_slot_source"]),
        "pin_coverage_count": len(coverage),
        "measured_coverage_count": len(measurements),
    }
    frames = [
        {
            "frame_index": int(row["frame_index"]),
            "artifact_id": render.artifact_id,
            "sha256": row["sha256"],
            "crop": dict(primary_frame_payloads[index]),
            "metadata": dict(identity_metadata),
        }
        for index, row in enumerate(primary["rendered_frames"])
    ]
    # ── bounded per-role evidence: every fact exactly ONCE ────────────────
    # This set travels to the detector as a CHILD-PROCESS argument
    # (``runner.py`` -> ``sys.argv[2]``), so the raw payload and the per-role
    # reports are each recorded once and everything else carries ids + the
    # verdict summary:
    #   * raw pixels .................... pinned_reference.crop + frames[].crop
    #   * the full frozen-policy verdict  identity_measurements[].verdict
    #   * the full per-role pin record ... cast_pin.cast_coverage
    #   * the coverage reports ........... pin_coverage / measured_coverage
    # The public cast contract's compatibility verdict is identical for every
    # role of one mapping, so it is recorded ONCE (per-role identical blocks
    # were what made this set exceed the child-process argv ceiling).
    contracts = [dict(entry.get("compatibility") or {}) for entry in coverage]
    shared_contract = contracts[0] if contracts and all(
        entry == contracts[0] for entry in contracts
    ) else None
    pin_coverage: dict[str, Any] = {
        "kind": "pinned",
        "meaning": "the target SELECTED per role — a pin is not a measurement",
        "scope": "every object role this video renders",
        "roles": [str(entry["object_role_id"]) for entry in coverage],
        "count": len(coverage),
        "uncovered_role_ids": [],
        "cast_coverage": [_pin_coverage_row(entry) for entry in coverage],
        "full_record_at": "cast_pin.cast_coverage",
    }
    measured_coverage: dict[str, Any] = {
        "kind": "measured",
        "meaning": "the identity MEASURED on the resolved render, per role",
        "scope": "every role listed in pin_coverage",
        "roles": [str(row["object_role_id"]) for row in measurements],
        "count": len(measurements),
        "per_role": {
            str(row["object_role_id"]): {
                "measured_distance_px": row["measured_distance_px"],
                "verdict": _verdict_summary(row["verdict"]),
                "reference_artifact_id": row["reference_artifact_id"],
                "reference_pose_slot": row["reference_pose_slot"],
                "frames_measured": list(row["frames_measured"]),
            }
            for row in measurements
        },
        "worst_role_id": str(worst["object_role_id"]),
        "aggregate_distance_px": worst["measured_distance_px"],
        "aggregate_rule": "max over the measured roles (fail-closed), reported "
        "independently of the primary block the frozen detector consumes",
        "measured_on": "the resolved render artifact bytes",
        "full_verdicts_at": "identity_measurements[].verdict",
    }
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "segment_row_id": str(segment.id),
        "segment_logical_id": str(segment.logical_id),
        "pinned_reference": {
            "artifact_id": reference.artifact_id,
            "artifact_sha256": reference.sha256,
            "sha256": crop_sha256(reference_crop),
            "crop_revision": crop_revision(reference_crop),
            "crop": {
                "pixels": reference_crop,
                "width": len(reference_crop[0]),
                "height": len(reference_crop),
            },
            "identity": {
                "object_role_id": str(identity["object_role_id"]),
                "role_id": str(segment.role_id),
                "mapping_id": str(identity["mapping_id"]),
                "mapping_revision": int(identity["mapping_revision"]),
                "character_id": str(identity["character_id"]),
                "character_revision": int(identity["character_revision"]),
                "pack_version_id": str(identity["pack_version_id"]),
                "pack_version": int(identity["pack_version"]),
                "pack_version_revision": int(identity["pack_version_revision"]),
                "pack_version_status": str(identity["pack_version_status"]),
                "pose_slot": str(identity["pose_slot"]),
                "reference_asset_id": str(identity["reference_asset_id"]),
                "reference_slot_source": str(identity["reference_slot_source"]),
                "reference_slot_mapping": list(identity["reference_slot_mapping"]),
                "workspace_id": str(identity["workspace_id"]),
                "source_generation": str(identity["source_generation"]),
            },
            "compatibility_reasons": list(identity["reasons"]),
        },
        "frames": frames,
        "pin_coverage": pin_coverage,
        "measured_coverage": measured_coverage,
        "identity_measurements": measurements,
        "cast_pin": {
            "expected_metadata": dict(identity_metadata),
            "compatible": True,
            "compatibility_reasons": list(identity["reasons"]),
            "cast_contract": shared_contract,
            "cast_contract_scope": "identical for every role of this mapping"
            " when cast_contract is not null; otherwise it is per role in"
            " cast_coverage[].compatibility_reasons",
            "coverage_scope": "single_role",
            "coverage_scope_meaning": "'single_role' covers the PRIMARY block "
            "only; pin_coverage/measured_coverage cover every rendered role",
            "measured_role_id": primary_role_id,
            "primary_role_rule": "the role of the FIRST current segment (the "
            "persisted segment_row_id contract of this check)",
            "roles_total": len(coverage),
            "roles_covered": len(coverage),
            "uncovered_role_ids": [],
            "cast_coverage_kind": "pinned_only_not_measured",
            "measured_role_ids": [str(row["object_role_id"]) for row in measurements],
            "measurement_note": "pin coverage = what was selected per role; "
            "measured coverage = what was measured on the render, per role",
            "cast_coverage": [
                _pin_record(entry, include_contract=shared_contract is None)
                for entry in coverage
            ],
            "role_observations": [
                {
                    "object_role_id": row["object_role_id"],
                    "reference_artifact_id": row["reference_artifact_id"],
                    "reference_pose_slot": row["reference_pose_slot"],
                    "rendered_frames": [
                        {"frame_index": frame["frame_index"], "sha256": frame["sha256"]}
                        for frame in row["rendered_frames"]
                    ],
                    "measured_distance_px": row["measured_distance_px"],
                    "verdict": _verdict_summary(row["verdict"]),
                    "full_measurement_at": "identity_measurements",
                }
                for row in measurements
            ],
        },
    }
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(int(primary["frames_measured"][0]), int(primary["frames_measured"][-1])),
        measure="frames = crops of the decoded RENDER inside the measured "
        "segment window; pinned_reference = crop of the pinned LIBRARY reference "
        "of the target identity in the same window; identity_measurements "
        "carries the SAME measurement for every rendered role",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "artifact": {
                "reference": reference.provenance(),
                "render": render.provenance(),
                "render_role": render_role,
                "render_role_facts": render_meta,
                "segment_mask": ctx.mask(
                    segment.mask_artifact_id, detector
                )[0].provenance(),
                "mask_dims": [
                    int(ctx.scope.canvas(detector)[0]),
                    int(ctx.scope.canvas(detector)[1]),
                ],
                "crop_window_px": list(window),
                "reference_geometry": list(primary["crop_geometry"]["reference"]),
            },
            "annotation": {
                "pin_coverage": _coverage_provenance_digest(pin_coverage),
                "measured_coverage": _coverage_provenance_digest(measured_coverage),
                "coverage_scope": "single_role",
                "measured_role_id": primary_role_id,
                "identity_reference_slot_mapping": list(
                    src.IDENTITY_REFERENCE_POSE_SLOTS
                ),
                "reference_slot_sources": dict(src.REFERENCE_SLOT_SOURCES),
                "source_is_not_the_identity_authority": "the video's own source "
                "frames are the MOTION authority, never the identity reference",
            },
            "result": {
                "segment_id": str(segment.id),
                "segment_revision": int(segment.revision),
                "role_id": str(segment.role_id),
            },
        },
        derivations={
            "pinned_reference": "crop of the PINNED LIBRARY REFERENCE of the "
            "primary role, re-hashed on read",
            "frames": "crops of the RENDER artifact inside the same window",
            "identity_measurements": "per-role: the RENDER inside that role's "
            "own window against that role's OWN pinned reference + verdict",
            "crop_payload": "pixels once (pinned_reference.crop + frames[].crop);"
            " every other crop is pinned by sha256 + distance",
            "payload_budget": "bounded + measured (child-process argument)",
            "cast_pin": "the library target identity per role + the public cast "
            "contract's verdict; no verdict is a typed refusal",
        },
    )
    # ── the argv budget is a MEASURED, reported fact, not a promise ────────
    # ``runner.py`` serialises this set with ``separators=(",", ":")`` and hands
    # it over as ``sys.argv[2]``; the budget is checked against THAT form.
    transported_bytes = len(json.dumps(args, separators=(",", ":")))
    pretty_bytes = len(json.dumps(args))
    if transported_bytes > ARGV_CEILING_SPAWN_OK_BYTES:
        raise malformed(
            detector,
            f"the composed argument set is {transported_bytes} B, but the "
            f"detector child process can only receive ~"
            f"{ARGV_CEILING_SPAWN_OK_BYTES} B on the Windows command line "
            f"(measured: {ARGV_CEILING_WINERROR_206_BYTES} B raises WinError "
            "206, 'The filename or extension is too long'): refuse instead of "
            "handing the runner a payload it cannot spawn",
            measured_bytes=transported_bytes,
            budget_bytes=ARGV_DETECTOR_ARGS_BUDGET_BYTES,
            hard_cap_bytes=ARGV_CEILING_SPAWN_OK_BYTES,
        )
    args["payload_budget"] = {
        "transport": "sys.argv[2] of the detector child process (runner.py)",
        "limit_bytes": ARGV_DETECTOR_ARGS_BUDGET_BYTES,
        "measured_bytes": transported_bytes,
        "within_limit": transported_bytes <= ARGV_DETECTOR_ARGS_BUDGET_BYTES,
        "hard_cap_bytes": ARGV_CEILING_SPAWN_OK_BYTES,
        "pretty_bytes_excluding_this_block": pretty_bytes,
        "os_ceiling_measured_chars": [
            ARGV_CEILING_SPAWN_OK_BYTES,
            ARGV_CEILING_WINERROR_206_BYTES,
        ],
        "rule": "raw pixels once; coverage reports once; every other crop keeps "
        "its sha256 + distance",
    }
    return args

def _edge_halo(ctx: _Context) -> dict[str, Any]:
    detector = "edge_halo"
    segments = ctx.segments(detector)
    segment = segments[0]
    expected, expected_matrix, width, height, bbox = ctx.mask(
        segment.mask_artifact_id, detector
    )
    candidates = src.rendered_minus_expected_masks(
        ctx.session, ctx.scope, expected_id=expected.artifact_id
    )
    if not candidates:
        raise dependency(
            detector,
            "the video publishes exactly one mask artifact per segment (the "
            "pinned expected geometry); no rendered-side mask exists to compare "
            "it against, and comparing the mask with itself is forbidden",
            fact="a rendered-side mask artifact distinct from the expected mask",
            producer="object-correction mask publication (publishes a NEW mask "
            "artifact per corrected role)",
            persistence="artifact(kind='image', purpose='mask', owner=video_item)",
        )
    rendered_evidence: src.ArtifactEvidence | None = None
    rendered_matrix: list[list[float]] | None = None
    for candidate in candidates:
        evidence = src.read_artifact(
            ctx.session, ctx.managed_root, ctx.scope, candidate, detector=detector
        )
        if evidence.sha256 == expected.sha256:
            continue
        matrix, r_width, r_height = decode_png_gray(evidence.data, detector=detector)
        if (r_width, r_height) != (width, height):
            raise malformed(
                detector,
                f"rendered mask {evidence.artifact_id!r} is {r_width}x{r_height} "
                f"but the expected mask is {width}x{height}",
                artifact_id=evidence.artifact_id,
            )
        # A rendered-side mask must bound the SAME region as the expected
        # mask: a mask of a different region is a different object and
        # comparing the two would measure nothing about this edge.
        if not _bbox_overlaps(mask_bbox(matrix), bbox):
            continue
        rendered_evidence, rendered_matrix = evidence, matrix
        break
    if rendered_evidence is None or rendered_matrix is None:
        raise dependency(
            detector,
            "no rendered-side mask candidate is both byte-distinct from the "
            "expected mask and bound to the same region (a byte-identical "
            "candidate is a self-comparison and a non-overlapping candidate "
            "belongs to a different object); neither can be measured",
            fact="a rendered mask artifact, distinct from the expected mask, "
            "bounding the same region",
            producer="object-correction mask publication",
            persistence="artifact.sha256 + artifact bytes (measured bbox)",
        )
    rendered_bbox = mask_bbox(rendered_matrix)
    window, window_bounded = _halo_window(bbox, rendered_bbox, frame=(width, height))
    expected_pixels = _crop(expected_matrix, window)
    rendered_pixels = _crop(rendered_matrix, window)
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "segment_row_id": str(segment.id),
        "segment_logical_id": str(segment.logical_id),
        "frame_index": int(segment.start_frame),
        "mask_revision": str(crop_revision(expected_pixels)),
        "inner_radius_px": round(disc_radius_px(mask_area(expected_matrix)), 9),
        "expected": {
            "artifact_id": expected.artifact_id,
            "sha256": crop_sha256(expected_pixels),
            "width": len(expected_pixels[0]),
            "height": len(expected_pixels),
            "mask": {
                "width": len(expected_pixels[0]),
                "height": len(expected_pixels),
                "pixels": expected_pixels,
            },
        },
        "rendered": {
            "artifact_id": rendered_evidence.artifact_id,
            "sha256": crop_sha256(rendered_pixels),
            "width": len(rendered_pixels[0]),
            "height": len(rendered_pixels),
            "mask": {
                "width": len(rendered_pixels[0]),
                "height": len(rendered_pixels),
                "pixels": rendered_pixels,
            },
        },
    }
    to_ms = _frame_ms(ctx, detector)
    args["rendered_observation"] = {
        "schema_version": 1,
        "detector": detector,
        "observation_revision": obs.OBSERVATION_REVISION,
        "artifact": rendered_evidence.provenance(),
        "render_role": "rendered_side_mask_publication",
        "producer": "object-correction mask publication",
        "producer_persistence": "artifact(kind='image', purpose='mask', "
        "owner_type='video_item')",
        "window": {"start_frame": int(segment.start_frame),
                   "end_frame": int(segment.end_frame)},
        "pts_ms": {
            "start_ms": to_ms(int(segment.start_frame)),
            "end_ms": to_ms(int(segment.end_frame)),
            "timebase": {"fps_num": int(ctx.scope.fps_num),
                         "fps_den": int(ctx.scope.fps_den)},
        },
        "measure": "halo width measured between the RENDERED-side published "
        "mask artifact and the pinned expected geometry, over the shared "
        "window cropped from the persisted bytes; a byte-identical candidate is "
        "refused as a self-comparison",
    }
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "artifact": {
                "expected_mask": expected.provenance(),
                "rendered_mask": rendered_evidence.provenance(),
                "pixel_window_px": list(window),
                "full_mask_dims": [int(width), int(height)],
                "expected_mask_area_px": mask_area(expected_matrix),
                "rendered_mask_area_px": mask_area(rendered_matrix),
                "expected_bbox": [int(v) for v in bbox],
                "rendered_bbox": [int(v) for v in rendered_bbox],
                "window": [int(v) for v in window],
            },
            "result": {
                "segment_id": str(segment.id),
                "segment_revision": int(segment.revision),
                "mask_artifact_id": str(segment.mask_artifact_id),
            },
        },
        derivations={
            "inner_radius_px": "sqrt(expected_mask_area / pi) measured over the "
            "full persisted expected mask",
            "mask_payload": "expected bbox ∪ rendered bbox expanded by "
            f"{HALO_MARGIN_PX} px so the halo ring (which lies outside the "
            "expected region) is inside the window; both sides share it",
            "window_bounded": window_bounded,
            "halo_margin_px": HALO_MARGIN_PX,
            "window_px": [int(window[2] - window[0]), int(window[3] - window[1])],
        },
    )
    return args


def _temporal_flicker(ctx: _Context) -> dict[str, Any]:
    detector = "temporal_flicker"
    segments = ctx.segments(detector)
    segment = segments[0]
    render, render_role, render_meta = _rendered_output(ctx, detector)
    indices = window_indices(
        int(segment.start_frame), int(segment.end_frame), limit=min(ctx.max_frames, 16)
    )
    frames = ctx.frames(render, indices, detector)
    luminance = frame_luminance(frames)
    if len(luminance) < 2:
        raise missing(
            detector,
            "fewer than two decodable frames inside the segment window; a "
            "per-frame luminance series cannot be measured",
            frames_examined=indices,
            render_role=render_role,
        )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "segment_row_id": str(segment.id),
        "segment_logical_id": str(segment.logical_id),
        "window": {"start_frame": min(luminance), "end_frame": max(luminance)},
        "luminance": [luminance[index] for index in sorted(luminance)],
    }
    args["render_observation"] = _observation_envelope(
        ctx,
        detector,
        evidence=render,
        role=render_role,
        facts=render_meta,
        window=(min(luminance), max(luminance)),
        measure="luminance = mean grayscale of each decoded RENDER artifact "
        "frame (the source is never substituted for the output)",
    )
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "artifact": {
                "media": render.provenance(),
                "render_role": render_role,
                "render_role_facts": render_meta,
            },
            "result": {
                "segment_id": str(segment.id),
                "segment_revision": int(segment.revision),
                "range": [int(segment.start_frame), int(segment.end_frame)],
            },
        },
        derivations={
            "luminance": "mean grayscale of each decoded persisted frame "
            "(deterministic decode, rounded to 9 dp)",
            "measured_frames": sorted(luminance),
            "luminance_digest": content_digest([luminance[i] for i in sorted(luminance)]),
        },
    )
    return args


def _crop(
    matrix: list[list[float]], window: tuple[int, int, int, int]
) -> list[list[float]]:
    x0, y0, x1, y1 = window
    return [list(row[x0:x1]) for row in matrix[y0:y1]]


_BUILDERS: dict[str, Callable[[_Context], dict[str, Any]]] = {
    "trajectory_drift": _trajectory_drift,
    "cut_drift": _cut_drift,
    "contact_break": _contact_break,
    "z_order_error": _z_order_error,
    "silhouette_clipping": _silhouette_clipping,
    "identity_drift": _identity_drift,
    "edge_halo": _edge_halo,
    "temporal_flicker": _temporal_flicker,
}


def compose_visual_band(
    session: Session,
    *,
    managed_root: Path,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    generation: str = "1",
    max_frames: int = MAX_WINDOW_FRAMES,
) -> dict[str, dict[str, Any]]:
    """Compose real persisted detector args for the eight visual detectors.

    Raises :class:`QcEvidenceError` when ANY detector's evidence is missing,
    stale, foreign, malformed, tampered or has no producer — the aggregate
    error carries the per-detector refusal codes so a reviewer sees every gap
    at once rather than one per submission.
    """
    scope = src.load_scope(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        generation=generation,
    )
    ctx = _Context(session=session, managed_root=Path(managed_root), scope=scope,
                   max_frames=max_frames)
    composed: dict[str, dict[str, Any]] = {}
    failures: dict[str, QcEvidenceError] = {}
    for name in VISUAL_DETECTORS:
        try:
            composed[name] = _BUILDERS[name](ctx)
        except QcEvidenceError as exc:
            failures[name] = exc
    if failures:
        first_name = next(iter(failures))
        first = failures[first_name]
        raise QcEvidenceError(
            first.code,
            first.message,
            detector=first_name,
            dependency=first.dependency,
            failed_detectors={
                name: exc.as_dict() for name, exc in failures.items()
            },
            refusals={
                name: exc.code for name, exc in failures.items()
            },
        ) from first
    for _name, args in composed.items():
        args["evidence_provenance"]["composed_digest"] = hashlib.sha256(
            content_digest({k: v for k, v in args.items() if k != "evidence_provenance"})
            .encode("utf-8")
        ).hexdigest()
    return composed


__all__ = [
    "CHECKPOINT_REF",
    "CROP_WINDOW_PX",
    "HALO_MARGIN_PX",
    "VISUAL_DETECTORS",
    "compose_visual_band",
]
