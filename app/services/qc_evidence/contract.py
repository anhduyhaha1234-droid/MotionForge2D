"""MF-P1-QC-EVIDENCE — FROZEN detector → input → producer → provenance table.

This module is the single source of truth for *what* a QC detector consumes
and *which persisted producer* emits it.  It is frozen BEFORE the
implementation (gate order step 1) and is machine-checkable:

- :data:`CONTRACTS` enumerates one row per detector of the binding FULL band
  (8 visual/timecode + ``audio_missing`` + ``av_sync_drift``);
- :func:`table_digest` is a content digest over the canonical JSON of the
  whole table — any drift in a producer, persistence path, provenance proof
  or refusal code changes the digest, so a test can freeze it;
- :func:`render_markdown` renders the human table that is written verbatim
  to ``NEW/P1QC/QC_INPUT_PROVENANCE.md``.

Evidence families (the four the task freezes):

``source``      the video item's own source media artifact row + bytes.
``result``      producer RESULTS: extraction segments, scene rows,
                render routes, full-apply publications.
``annotation``  the structural graph the results are judged against:
                motion/occlusion/contact edges, scene boundaries, cast pins.
``artifact``    managed files on disk, re-hashed on read and compared with
                the ``sha256``/``size_bytes`` the database recorded.

Nothing here reaches the database or the detectors — it is the frozen map
the composer implements.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.services.qc_evidence.errors import (
    QC_EVIDENCE_DEPENDENCY,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_TAMPERED,
)

#: The binding FULL band, registration order (frozen — mirrors
#: ``app.workflow.qc_checks_handler.SCOPE_FULL``).
FULL_BAND: tuple[str, ...] = (
    "trajectory_drift",
    "cut_drift",
    "contact_break",
    "z_order_error",
    "silhouette_clipping",
    "identity_drift",
    "edge_halo",
    "temporal_flicker",
    "audio_missing",
    "av_sync_drift",
)

#: The four evidence families, closed set.
EVIDENCE_FAMILIES: tuple[str, ...] = ("source", "result", "annotation", "artifact")


@dataclass(frozen=True)
class DetectorInputContract:
    """One frozen row: detector → required input → producer → provenance."""

    detector: str
    required_input: str
    families: tuple[str, ...]
    producers: tuple[str, ...]
    persistence: tuple[str, ...]
    provenance: str
    derivations: str
    refusals: tuple[str, ...]

    def as_row(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "required_input": self.required_input,
            "families": list(self.families),
            "producers": list(self.producers),
            "persistence": list(self.persistence),
            "provenance": self.provenance,
            "derivations": self.derivations,
            "refusals": list(self.refusals),
        }


_ALL_REFUSALS = (
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_TAMPERED,
)

_CONTRACTS: tuple[DetectorInputContract, ...] = (
    DetectorInputContract(
        detector="trajectory_drift",
        required_input=(
            "reference_x[] (intended placement) + observed_x[] "
            "(rendered placement) + frame_start"
        ),
        families=("annotation", "artifact"),
        producers=(
            "S09 structural-lock render route (anchor_x anchor_y)",
            "S10 full-apply publication artifact (rendered pixels) "
            "with the imported source artifact as the disclosed fallback",
        ),
        persistence=(
            "segment_render_route.anchor_x / start_frame / end_frame",
            "artifact.sha256 + managed file bytes",
        ),
        provenance=(
            "route row id/revision + anchor_x, render artifact id + re-verified "
            "sha256/size, per-frame measured centroid column digest, feature revision"
        ),
        derivations=(
            "reference_x[f] = round(anchor_x * frame_width) over the bounded window; "
            "observed_x[f] = column centroid of the source↔render changed pixels in "
            "the segment region, measured on the decoded persisted artifacts"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="cut_drift",
        required_input="scene_boundaries[{position,start_frame}] + render_cuts_ms[] + timebase",
        families=("annotation", "result", "artifact"),
        producers=(
            "scene detector (scene rows — the INTENDED boundary ground truth)",
            "S10 full-apply publication / render-side artifact publication "
            "(the rendered output the cut is observed in)",
        ),
        persistence=(
            "scene.position / scene.start_frame",
            "artifact.sha256 + managed media bytes of the RENDER artifact",
            "occurrence_segment.start_time_ms (recorded as planned_cuts_ms only)",
            "video_item.fps_num / fps_den (canonical timebase)",
        ),
        provenance=(
            "scene row ids + positions, render artifact id + re-verified sha256, "
            "window + exact PTS (canonical timebase), producer identity, "
            "per-boundary measured deltas, planned_cuts_ms for comparison"
        ),
        derivations=(
            "render_cuts_ms[i] = exact millisecond of the frame whose "
            "|render(f) - render(f-1)| is maximal inside boundary i's neighbourhood "
            "(deterministic tie-break), measured on the decoded RENDER artifact; a "
            "boundary whose neighbourhood shows no measurable change refuses — the "
            "planned occurrence_segment.start_time_ms is never reported as observed"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="contact_break",
        required_input="analysis_window + contacts[] + segments[] with bbox_per_frame",
        families=("annotation", "result", "artifact"),
        producers=(
            "scene-graph contact edges (scene_graph_contact rows) + segment mask "
            "artifacts (the ANNOTATED region the observation is measured inside)",
            "S10 full-apply publication / render-side artifact publication "
            "(the rendered output the contact geometry is observed in)",
        ),
        persistence=(
            "scene_graph_contact.* / occurrence_segment.mask_artifact_id",
            "artifact.sha256 + managed media bytes of the RENDER artifact",
        ),
        provenance=(
            "contact ids + ranges, segment ids + revisions, annotated mask bbox per "
            "segment (expected_bbox_per_frame), render artifact id + re-verified "
            "sha256 + window/PTS, measured observed bbox per frame"
        ),
        derivations=(
            "bbox_per_frame = measured bbox of the source-to-render changed pixels "
            "INSIDE the segment's annotated mask region, per decoded RENDER frame "
            "(null where the output paints nothing there); the annotation is carried "
            "separately as expected_bbox_per_frame and is never reported as observed"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="z_order_error",
        required_input="analysis_window + segments[z_order] + occlusion_edges[] + render_order",
        families=("result", "annotation", "artifact"),
        producers=(
            "scene-graph occlusion edges + segment masks (the ANNOTATION the stacking "
            "is judged against)",
            "extraction segments (occurrence_segment.z_order — recorded for comparison "
            "only)",
            "S09 structural-lock manifest when a current active version exists "
            "(validated through the public S09 contract, recorded as "
            "lock_manifest_expected, never as the observed order)",
            "S10 full-apply publication / render-side artifact publication (the "
            "rendered output the stacking is observed in)",
        ),
        persistence=(
            "scene_graph_occlusion.* / occurrence_segment.mask_artifact_id",
            "structural_lock_manifest.manifest_json",
            "artifact.sha256 + managed media bytes of the RENDER artifact",
        ),
        provenance=(
            "segment ids + z_order + revisions, occlusion ids + ranges, manifest id + "
            "manifest_hash_hex + validated order when supplied, render artifact id + "
            "re-verified sha256 + window/PTS, per-pair measured stackings"
        ),
        derivations=(
            "render_order = bottom-to-top order implied by the MEASURED stacking of "
            "every occlusion pair: the region where the two annotated masks overlap is "
            "attributed to whichever segment's exclusive rendered appearance it "
            "matches, measured on the decoded RENDER artifact; a pair whose regions do "
            "not overlap, or whose appearance is indistinguishable, refuses — the "
            "persisted z_order and the planned manifest order are never reported as "
            "observed"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="silhouette_clipping",
        required_input="analysis_window + frame{width,height} + segments[bbox]",
        families=("result", "artifact", "source"),
        producers=(
            "video item canvas (video_item.width/height, probed at import)",
            "extraction segments + their mask artifacts (the ANNOTATED region)",
            "S10 full-apply publication / render-side artifact publication (the "
            "rendered output the silhouette is observed in)",
        ),
        persistence=(
            "video_item.width / height",
            "occurrence_segment.mask_artifact_id + artifact.sha256",
            "artifact.sha256 + managed media bytes of the RENDER artifact",
        ),
        provenance=(
            "canvas dims + their persisted source, segment ids, mask artifact ids + "
            "re-verified sha256, annotated bbox per segment (expected_bbox), render "
            "artifact id + re-verified sha256 + window/PTS, measured observed bbox"
        ),
        derivations=(
            "bbox = union of the per-frame measured bboxes of the source-to-render "
            "changed pixels INSIDE the segment's annotated mask region, measured on "
            "the decoded RENDER artifact frames of that segment's window; a segment "
            "whose rendered silhouette is not observable refuses — the annotation is "
            "carried separately as expected_bbox and is never reported as observed"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="identity_drift",
        required_input="pinned_reference{artifact_id,sha256,crop} + frames[] + cast_pin(coverage)",
        families=("artifact", "annotation"),
        producers=(
            "character library target identity: project cast mapping "
            "(project_cast_mapping.character_id + immutable pack_version_id) + the "
            "pinned REFERENCE asset of that PackVersion (character_asset pose_slot "
            "'reference')",
            "render result artifact (observed frame crops)",
        ),
        persistence=(
            "project_cast_mapping.* / character_asset.artifact_id / artifact.sha256 + "
            "managed bytes of the library reference",
            "artifact.sha256 + managed bytes of the RENDER",
        ),
        provenance=(
            "per-role coverage (role, mapping id/revision, character id/revision, pack "
            "version + revision + status, reference artifact id + re-verified sha256, "
            "workspace, generation), the compatibility verdict (a typed refusal, never "
            "coerced) and the render artifact id + re-verified sha256 + window/PTS"
        ),
        derivations=(
            "pinned_reference = crop of the pinned LIBRARY REFERENCE artifact of the "
            "selected CharacterID + PackVersion inside the measured segment window; "
            "frames = crops of the RENDER artifact inside the same window. The video's "
            "own source frames are the MOTION authority and are never the identity "
            "reference (finding R4). Coverage is enumerated per rendered role and the "
            "measurement scope is declared — a first-segment-only identity is never "
            "reported as the entire cast"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="edge_halo",
        required_input="rendered mask + expected mask + inner_radius_px",
        families=("artifact",),
        producers=(
            "extraction segment mask artifact (the pinned expected geometry)",
            "a DISTINCT rendered-side mask artifact for the same video "
            "(object-correction published mask)",
            "segment render route (radius reference geometry)",
        ),
        persistence=(
            "artifact.sha256 + managed PNG bytes (both masks)",
            "occurrence_segment.mask_artifact_id (expected side)",
        ),
        provenance=(
            "both artifact ids + re-verified sha256/size, mask dims, measured disc "
            "radius from the expected mask bytes"
        ),
        derivations=(
            "inner_radius_px = sqrt(expected_mask_area / pi) measured from the persisted "
            "expected mask bytes; the rendered mask MUST be a different artifact id + "
            "different sha256 than the expected mask (self-comparison is forbidden)"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="temporal_flicker",
        required_input="window{start_frame,end_frame} + luminance[]",
        families=("artifact",),
        producers=(
            "S10 full-apply publication / render-side artifact publication "
            "(rendered frames) — a video with no rendered output distinct from its "
            "imported source refuses instead of measuring the source",
        ),
        persistence="artifact.sha256 + managed media bytes of the RENDER artifact",
        provenance=(
            "artifact id + re-verified sha256/size, per-frame luminance digest, "
            "decode revision, bounded window"
        ),
        derivations=(
            "luminance[f] = mean grayscale of the decoded RENDER artifact frame f "
            "(bounded window, deterministic decode)"
        ),
        refusals=_ALL_REFUSALS + (QC_EVIDENCE_DEPENDENCY,),
    ),
    DetectorInputContract(
        detector="audio_missing",
        required_input="checkpoint (T03E attach envelope) + published",
        families=("result",),
        producers=("ATTACH_ORIGINAL_AUDIO completed attempt result (remux checkpoint)",),
        persistence="job / job_attempt.result_json (append-only attempt history)",
        provenance=(
            "job id + attempt id + the remux checkpoint's own content-derived identity "
            "(source sha256 / codecs / durations)"
        ),
        derivations="read verbatim from the persisted attempt result — never recomputed",
        refusals=_ALL_REFUSALS,
    ),
    DetectorInputContract(
        detector="av_sync_drift",
        required_input="checkpoint (T03E attach envelope) + scene_timeline",
        families=("result",),
        producers=(
            "ATTACH_ORIGINAL_AUDIO completed attempt result (remux checkpoint)",
            "video item duration (video_item.duration_ms)",
        ),
        persistence="job_attempt.result_json + video_item.duration_ms",
        provenance=(
            "job id + attempt id + checkpoint identity + video_item.duration_ms and its "
            "row identity (the only server-side timeline fact; never a client value)"
        ),
        derivations="scene_timeline.duration_seconds = duration_ms / 1000 (exact decimal)",
        refusals=_ALL_REFUSALS,
    ),
)

#: Frozen table (same order as :data:`FULL_BAND`).
CONTRACTS: tuple[DetectorInputContract, ...] = _CONTRACTS

_COLUMNS = (
    "#",
    "detector",
    "required input fact",
    "evidence families",
    "producer(s)",
    "persistence (table.column / artifact bytes)",
    "provenance proof",
    "derivation (bounded, disclosed)",
    "refusal codes",
)


def contract_for(detector: str) -> DetectorInputContract:
    for row in CONTRACTS:
        if row.detector == detector:
            return row
    raise KeyError(detector)


def table_payload() -> dict[str, Any]:
    """Canonical, machine-checkable payload of the whole frozen table."""
    return {
        "schema": "mf-p1-qc-evidence/input-provenance-table",
        "version": 1,
        "families": list(EVIDENCE_FAMILIES),
        "detectors": [row.as_row() for row in CONTRACTS],
    }


def table_digest() -> str:
    canonical = json.dumps(
        table_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown() -> str:
    """Render the frozen table as the human markdown sheet (no pipe hazards)."""
    lines: list[str] = []
    lines.append("| " + " | ".join(_COLUMNS) + " |")
    lines.append("|" + "|".join("---" for _ in _COLUMNS) + "|")
    for index, row in enumerate(CONTRACTS, start=1):
        cells = (
            str(index),
            row.detector,
            row.required_input,
            ", ".join(row.families),
            "; ".join(row.producers),
            "; ".join(row.persistence),
            row.provenance,
            row.derivations,
            ", ".join(row.refusals),
        )
        lines.append("| " + " | ".join(_md_cell(c) for c in cells) + " |")
    lines.append("")
    lines.append(f"table_digest = {table_digest()}")
    return "\n".join(lines) + "\n"
