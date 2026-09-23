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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from app.services.qc_evidence import sources as src
from app.services.qc_evidence.contract import FULL_BAND
from app.services.qc_evidence.errors import (
    QcEvidenceError,
    dependency,
    malformed,
    missing,
)
from app.services.qc_evidence.measure import (
    MAX_WINDOW_FRAMES,
    MEASURE_REVISION,
    changed_centroid_x,
    content_digest,
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
    render, render_role, render_meta = ctx.render(detector)
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
            "observed_x": "column centroid of source↔render changed pixels "
            "(|Δ| >= 8 gray levels) per measured frame",
            "measured_frames": measured_frames,
            "reference_digest": content_digest(reference),
            "observed_digest": content_digest(observed),
        },
    )
    return args


def _cut_drift(ctx: _Context) -> dict[str, Any]:
    detector = "cut_drift"
    scenes = ctx.scenes(detector)
    segments = ctx.segments(detector)
    fps_num, fps_den = ctx.scope.fps_num, ctx.scope.fps_den
    if not fps_num or not fps_den:
        raise missing(
            detector,
            "the video item has no persisted canonical timebase "
            "(video_item.fps_num/fps_den are NULL), so frame↔ms conversion "
            "cannot be exact",
            video_item_id=ctx.scope.video_item_id,
        )
    from app.services.timebase import CanonicalTimebase

    timebase = CanonicalTimebase.from_rational(int(fps_num), int(fps_den), classification="CFR")
    boundaries: list[dict[str, int]] = []
    render_cuts: list[int] = []
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
        render_cuts.append(int(start_time_ms))
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "scene_boundaries": boundaries,
        "render_cuts_ms": render_cuts,
        "timebase": timebase.to_json(),
    }
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
            },
            "result": {
                "render_cut_segments": [
                    {"segment_id": str(m.id), "start_frame": int(m.start_frame),
                     "start_time_ms": int(m.start_time_ms)}
                    for m in segments
                    if int(m.start_frame) in [b["start_frame"] for b in boundaries]
                ],
                "timebase": {"fps_num": int(fps_num), "fps_den": int(fps_den),
                             "source": "video_item.fps_num/fps_den"},
            },
        },
        derivations={
            "render_cuts_ms": "the persisted occurrence_segment.start_time_ms of the "
            "current segment that starts at each scene boundary frame — the "
            "renderer's own millisecond value, never a re-conversion of the "
            "scene frame",
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
    segments_payload: list[dict[str, Any]] = []
    mask_provenance: list[dict[str, Any]] = []
    for segment in (left, right):
        evidence, _matrix, _width, _height, bbox = ctx.mask(
            segment.mask_artifact_id, detector
        )
        mask_provenance.append(evidence.provenance())
        segments_payload.append(
            {
                "id": str(segment.id),
                "logical_id": str(segment.logical_id),
                "z_order": int(segment.z_order),
                "start_frame": int(segment.start_frame),
                "end_frame": int(segment.end_frame),
                "mask_artifact_id": evidence.artifact_id,
                "bbox_per_frame": [
                    [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
                    for _ in indices
                ],
            }
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
            },
            "result": {
                "segments": [
                    {"id": str(s.id), "revision": int(s.revision),
                     "range": [int(s.start_frame), int(s.end_frame)]}
                    for s in (left, right)
                ],
            },
            "artifact": {"masks": mask_provenance},
        },
        derivations={
            "analysis_window": f"contact ∩ both segment windows, bounded to "
            f"{len(indices)} frames",
            "bbox_per_frame": "measured bounding box of the persisted mask bytes, "
            "held constant per frame (the producer publishes one full-frame mask "
            "per segment and no per-frame bbox)",
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
    }
    if manifest is not None:
        args["lock_manifest"] = dict(manifest.manifest)
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
                "lock_manifest": (
                    {
                        "manifest_id": str(manifest.id),
                        "version": int(manifest.version),
                        "manifest_hash_hex": str(manifest.manifest_hash_hex),
                        "status": str(manifest.status),
                    }
                    if manifest is not None
                    else None
                ),
            },
        },
        derivations={
            "observed_order": "the validated S09 manifest order when supplied, "
            "otherwise the persisted scene-graph z_order ascending (detector "
            "precedence, unchanged)",
            "window": [window_start, window_end],
        },
    )
    return args


def _silhouette_clipping(ctx: _Context) -> dict[str, Any]:
    detector = "silhouette_clipping"
    segments = ctx.segments(detector)
    width, height = ctx.scope.canvas(detector)
    window_start = min(int(segment.start_frame) for segment in segments)
    window_end = max(int(segment.end_frame) for segment in segments)
    payload: list[dict[str, Any]] = []
    masks: list[dict[str, Any]] = []
    for segment in segments:
        evidence, _matrix, mask_w, mask_h, bbox = ctx.mask(
            segment.mask_artifact_id, detector
        )
        if (mask_w, mask_h) != (width, height):
            raise malformed(
                detector,
                f"segment {segment.id!r} mask is {mask_w}x{mask_h} but the video "
                f"canvas is {width}x{height}; geometry mismatch (fail closed)",
                segment_id=str(segment.id),
            )
        masks.append(evidence.provenance())
        payload.append(
            {
                "id": str(segment.id),
                "logical_id": str(segment.logical_id),
                "start_frame": int(segment.start_frame),
                "end_frame": int(segment.end_frame),
                "mask_artifact_id": evidence.artifact_id,
                "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
            }
        )
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "analysis_window": {"start_frame": window_start, "end_frame": window_end},
        "frame": {"width": int(width), "height": int(height)},
        "segments": payload,
    }
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
        },
        derivations={
            "bbox": "bounding box of the non-zero pixels of the persisted mask "
            "artifact bytes (measured, never client-supplied)",
        },
    )
    return args


def _identity_drift(ctx: _Context) -> dict[str, Any]:
    detector = "identity_drift"
    segments = ctx.segments(detector)
    segment = segments[0]
    source = ctx.source(detector)
    render, render_role, render_meta = ctx.render(detector)
    if render.artifact_id == source.artifact_id:
        raise dependency(
            detector,
            "the rendered side of this video is its own source artifact (no "
            "full-apply publication exists); comparing it with itself would be "
            "a self-comparison baseline, which is forbidden",
            fact="a rendered result artifact distinct from the imported source",
            producer="S10 full-apply (stitch + publication) job",
            persistence="s10_full_apply_publication.artifact_id",
        )
    evidence, _matrix, width, height, bbox = ctx.mask(segment.mask_artifact_id, detector)
    window = _bounded_window(bbox)
    indices = window_indices(
        int(segment.start_frame), int(segment.end_frame), limit=min(ctx.max_frames, 8)
    )
    source_frames = ctx.frames(source, indices, detector)
    render_frames = ctx.frames(render, indices, detector)
    reference_crop: list[list[float]] | None = None
    frames: list[dict[str, Any]] = []
    for index in indices:
        source_frame = source_frames.get(index)
        render_frame = render_frames.get(index)
        if source_frame is None or render_frame is None:
            continue
        if reference_crop is None:
            reference_crop = _crop(source_frame, window)
        crop = _crop(render_frame, window)
        frames.append(
            {
                "frame_index": int(index),
                "artifact_id": render.artifact_id,
                "sha256": crop_sha256(crop),
                "crop": {"pixels": crop, "width": len(crop[0]), "height": len(crop)},
                "metadata": {},
            }
        )
    if reference_crop is None or not frames:
        raise missing(
            detector,
            "no decodable frame pair inside the segment window; there is no "
            "rendered identity evidence to measure",
            frames_examined=indices,
        )
    cast_pin: dict[str, Any] = {}
    pin = src.cast_pin_for_role(ctx.session, ctx.scope, str(segment.role_id))
    if pin is not None:
        cast_pin = {
            "mapping_id": pin["mapping_id"],
            "expected_metadata": {},
            "compatible": bool(pin.get("compatible", True)),
            "compatibility_reasons": list(pin.get("reasons") or []),
        }
    args: dict[str, Any] = {
        **_identity(ctx.scope, detector),
        "segment_row_id": str(segment.id),
        "segment_logical_id": str(segment.logical_id),
        "pinned_reference": {
            "artifact_id": source.artifact_id,
            "sha256": crop_sha256(reference_crop),
            "crop_revision": crop_revision(reference_crop),
            "crop": {
                "pixels": reference_crop,
                "width": len(reference_crop[0]),
                "height": len(reference_crop),
            },
        },
        "frames": frames,
        "cast_pin": cast_pin,
    }
    args["evidence_provenance"] = _provenance_env(
        ctx,
        detector,
        families={
            "artifact": {
                "source": source.provenance(),
                "render": render.provenance(),
                "render_role": render_role,
                "render_role_facts": render_meta,
                "segment_mask": evidence.provenance(),
                "crop_window_px": list(window),
                "mask_dims": [int(width), int(height)],
            },
            "annotation": {"cast_pin": pin},
            "result": {
                "segment_id": str(segment.id),
                "segment_revision": int(segment.revision),
                "role_id": str(segment.role_id),
            },
        },
        derivations={
            "pinned_reference": "crop of the SOURCE artifact inside the measured "
            "segment bbox (the reference side is never the observed side)",
            "frames": "crops of the RENDER artifact inside the same bbox window",
            "crop_payload": f"bounded to <= {CROP_WINDOW_PX}x{CROP_WINDOW_PX} px",
        },
    )
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
    render, render_role, render_meta = ctx.render(detector)
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
    for name, args in composed.items():
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
