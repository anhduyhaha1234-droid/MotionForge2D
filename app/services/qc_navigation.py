"""Canonical QC navigation resolver (S11-T04A / W9).

Maps EVERY QCItem location kind to a 1-1 navigation target whose endpoint
EXISTS in the real FastAPI app (lane-c REVIEW_QUEUE_CONTRACT §2 table +
API_UI_GAP_MATRIX G2/G12/G13; overlay §S11 \"jumps directly to the failing
layer and renderer route\"):

===================  ==========================================================
location kind        target endpoint (all registered GET routes)
===================  ==========================================================
``frame``            ``/api/projects/{project_id}/frames/{frame_index}``
                     (``app/api/routes/frames.py:26`` serve_frame, +``?scene_id=``)
``object``           ``/api/projects/{project_id}/objects/{object_id}/gallery``
                     (gallery route, ``app/api/routes/projects.py``) — fallback
                     ``/api/v2/object-intelligence/roles/{role_id}/occurrences``
                     when only the durable object_role_id is available
``audio``            ``/api/jobs/{job_id}`` (ATTACH_ORIGINAL_AUDIO job info,
                     ``app/api/routes/jobs.py`` — REVIEW_QUEUE_CONTRACT §2 audio)
``scene``            ``/api/projects/{project_id}/scenes/{scene_id}/objects``
                     (or the ``/scenes`` list when scene_id is absent)
``segment``          ``/api/v2/structural-evidence/segments/current/{segment_id}``
                     (structural-evidence read authority, S09 contract)
``render``           ``/api/projects/{project_id}`` (project page)
``route``            structural-evidence segment endpoint above + the renderer
                     route VALUE carried only when inside the structural_lock
                     contract ``RENDERER_ROUTES`` (fail-closed otherwise)
``video_item``       ``/api/projects/{project_id}`` (video-level issue; the
                     repository's default layer for video-scoped checks)
===================  ==========================================================

Hard rules (this module owns NO database access — pure resolver over the
frozen ``QCItemData`` DTO):

1. Canonical location is built ONLY from STRUCTURED data — typed evidence
   keys (``scene_id``/``frame_index``/``timecode_ms``/``object_role_id``)
   and the frozen QCItem fields (``segment_row_id``/``segment_logical_id``).
   No free text is ever parsed (MASTER_PLAN §10 constraint).  Wrong-typed
   values (str/float/bool where an int anchor is required) are treated as
   absent, never coerced.
2. Missing structured anchor ⇒ ``action.kind="explain"`` (Decision E:
   issue ngoài phạm vi rerun V1 — blocker + explanation, NO dead link).
3. Unknown location kind ⇒ ``NavigationResolutionError`` with stable code
   ``unknown_kind`` — the API layer answers 500 fail-closed (acceptance
   criterion 3: canonical mapping missing ⇒ stable error, never a guess).
4. Renderer-route values are validated against the structural_lock
   contract enum imported from ``app.persistence.models`` (read-only
   import — models.py is never modified).
"""

from __future__ import annotations

from typing import Any

from app.persistence.models import RENDERER_ROUTES
from app.schemas.qc_items import QCItemData
from app.schemas.qc_navigation import (
    CanonicalLocationData,
    NavigationActionData,
    QcNavigationData,
)

__all__ = [
    "LOCATION_KINDS",
    "KNOWN_KINDS",
    "NavigationResolutionError",
    "canonical_location",
    "resolve_navigation",
]

#: The canonical location-kind set (W9 outcome — every kind gets a target).
LOCATION_KINDS: tuple[str, ...] = (
    "frame",
    "object",
    "audio",
    "scene",
    "segment",
    "render",
    "route",
)

#: ``video_item`` is additionally mapped (the repository/default layer of
#: video-scoped checks like A/V sync — REVIEW_QUEUE_CONTRACT §2 "render /
#: project" family: project page).  Everything OUTSIDE this set is
#: fail-closed 500 — never guessed.
KNOWN_KINDS: tuple[str, ...] = LOCATION_KINDS + ("video_item",)

# ── registered endpoint templates (the ONLY authority for targets) ─────────

TEMPLATE_FRAME = "/api/projects/{project_id}/frames/{frame_index}"
TEMPLATE_GALLERY = "/api/projects/{project_id}/objects/{object_id}/gallery"
TEMPLATE_ROLE_OCCURRENCES = "/api/v2/object-intelligence/roles/{role_id}/occurrences"
TEMPLATE_JOB = "/api/jobs/{job_id}"
TEMPLATE_SCENES_LIST = "/api/projects/{project_id}/scenes"
TEMPLATE_SCENE_OBJECTS = "/api/projects/{project_id}/scenes/{scene_id}/objects"
TEMPLATE_SEGMENT = "/api/v2/structural-evidence/segments/current/{segment_id}"
TEMPLATE_PROJECT = "/api/projects/{project_id}"

#: Stable explain codes (Decision E) — rendered verbatim by the client.
EXPLAIN_REASONS: dict[str, str] = {
    "missing_frame_anchor": (
        "Thiếu frame_index có cấu trúc trong evidence — không thể neo vào "
        "frame cụ thể; issue ngoài phạm vi rerun V1, không tự đoán vị trí."
    ),
    "missing_object_anchor": (
        "Thiếu object_id/object_role_id có cấu trúc — không thể mở gallery "
        "đối tượng; issue ngoài phạm vi rerun V1, không tự đoán đối tượng."
    ),
    "missing_job_id": (
        "Thiếu job_id có cấu trúc trong evidence — không thể mở trạng thái "
        "job audio (ATTACH_ORIGINAL_AUDIO); không tự đoán job."
    ),
    "missing_segment_id": (
        "Thiếu segment_id có cấu trúc (layer ref/evidence/segment_row_id) — "
        "không thể mở segment; issue ngoài phạm vi rerun V1, không tự đoán."
    ),
    "renderer_route_outside_contract": (
        "Renderer route không nằm trong contract structural_lock "
        "(RENDERER_ROUTES) — fail-closed, không tự đoán route."
    ),
}


class NavigationResolutionError(Exception):
    """Canonical mapping missing — API layer answers 500 fail-closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _int_anchor(evidence: dict[str, Any], key: str) -> int | None:
    """Structured INT anchor only — str/float/bool are never coerced."""
    value = evidence.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _str_anchor(evidence: dict[str, Any], key: str) -> str | None:
    """Structured non-empty STR anchor only."""
    value = evidence.get(key)
    if not isinstance(value, str) or not value:
        return None
    return value


def canonical_location(item: QCItemData) -> CanonicalLocationData:
    """STRUCTURED-only canonical anchors — never parsed from free text."""
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    return CanonicalLocationData(
        scene_id=_int_anchor(evidence, "scene_id"),
        frame_index=_int_anchor(evidence, "frame_index"),
        timecode_ms=_int_anchor(evidence, "timecode_ms"),
        object_role_id=_str_anchor(evidence, "object_role_id"),
        segment_row_id=item.segment_row_id,
        segment_logical_id=item.segment_logical_id,
    )


def _explain(code: str) -> NavigationActionData:
    return NavigationActionData(
        kind="explain",
        method="GET",
        target=None,
        endpoint=None,
        code=code,
        reason=EXPLAIN_REASONS[code],
    )


def _navigate(target: str, endpoint: str) -> NavigationActionData:
    return NavigationActionData(
        kind="navigate",
        method="GET",
        target=target,
        endpoint=endpoint,
        code=None,
        reason=None,
    )


def _segment_id(item: QCItemData, loc: CanonicalLocationData) -> str | None:
    """Segment anchor priority: layer ref → evidence → durable item field."""
    if item.layer_ref_id and item.layer_ref_id != item.video_item_id:
        return item.layer_ref_id
    return None


def resolve_navigation(item: QCItemData) -> QcNavigationData:
    """Resolve the 1-1 navigation target for one QCItem (pure, no I/O)."""
    kind = item.layer_ref_type
    if kind not in KNOWN_KINDS:
        raise NavigationResolutionError(
            "unknown_kind",
            f"Không có mapping navigation cho location kind {kind!r} — "
            "canonical location không thể xác định, tự đoán bị cấm (fail-closed).",
        )

    loc = canonical_location(item)
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    project_id = item.project_id

    if kind == "frame":
        frame_index = loc.frame_index
        if frame_index is None:
            return QcNavigationData(
                qc_item_id=item.id,
                layer_ref_type=kind,
                canonical_location=loc,
                action=_explain("missing_frame_anchor"),
            )
        target = TEMPLATE_FRAME.format(project_id=project_id, frame_index=frame_index)
        if loc.scene_id is not None:
            target += f"?scene_id={loc.scene_id}"
        return QcNavigationData(
            qc_item_id=item.id,
            layer_ref_type=kind,
            canonical_location=loc,
            action=_navigate(target, TEMPLATE_FRAME),
        )

    if kind == "object":
        object_id = item.layer_ref_id if item.layer_ref_id != item.video_item_id else None
        role_id = loc.object_role_id
        if object_id is None:
            object_id = _str_anchor(evidence, "object_id")
        if object_id is not None:
            target = TEMPLATE_GALLERY.format(project_id=project_id, object_id=object_id)
            return QcNavigationData(
                qc_item_id=item.id,
                layer_ref_type=kind,
                canonical_location=loc,
                action=_navigate(target, TEMPLATE_GALLERY),
            )
        if role_id is not None:
            target = TEMPLATE_ROLE_OCCURRENCES.format(role_id=role_id)
            return QcNavigationData(
                qc_item_id=item.id,
                layer_ref_type=kind,
                canonical_location=loc,
                action=_navigate(target, TEMPLATE_ROLE_OCCURRENCES),
            )
        return QcNavigationData(
            qc_item_id=item.id,
            layer_ref_type=kind,
            canonical_location=loc,
            action=_explain("missing_object_anchor"),
        )

    if kind == "audio":
        job_id = _str_anchor(evidence, "job_id")
        if job_id is None or job_id == item.video_item_id:
            return QcNavigationData(
                qc_item_id=item.id,
                layer_ref_type=kind,
                canonical_location=loc,
                action=_explain("missing_job_id"),
            )
        target = TEMPLATE_JOB.format(job_id=job_id)
        return QcNavigationData(
            qc_item_id=item.id,
            layer_ref_type=kind,
            canonical_location=loc,
            action=_navigate(target, TEMPLATE_JOB),
        )

    if kind == "scene":
        if loc.scene_id is not None:
            target = TEMPLATE_SCENE_OBJECTS.format(project_id=project_id, scene_id=loc.scene_id)
            endpoint = TEMPLATE_SCENE_OBJECTS
        else:
            target = TEMPLATE_SCENES_LIST.format(project_id=project_id)
            endpoint = TEMPLATE_SCENES_LIST
        return QcNavigationData(
            qc_item_id=item.id,
            layer_ref_type=kind,
            canonical_location=loc,
            action=_navigate(target, endpoint),
        )

    if kind in ("segment", "route"):
        segment_id = _segment_id(item, loc)
        if segment_id is None:
            segment_id = _str_anchor(evidence, "segment_id")
        if segment_id is None:
            segment_id = loc.segment_row_id
        if segment_id is None:
            return QcNavigationData(
                qc_item_id=item.id,
                layer_ref_type=kind,
                canonical_location=loc,
                action=_explain("missing_segment_id"),
            )
        route_value = _str_anchor(evidence, "renderer_route")
        if kind == "route" and route_value is not None and route_value not in RENDERER_ROUTES:
            return QcNavigationData(
                qc_item_id=item.id,
                layer_ref_type=kind,
                canonical_location=loc,
                action=_explain("renderer_route_outside_contract"),
            )
        target = TEMPLATE_SEGMENT.format(segment_id=segment_id)
        return QcNavigationData(
            qc_item_id=item.id,
            layer_ref_type=kind,
            canonical_location=loc,
            action=_navigate(target, TEMPLATE_SEGMENT),
            renderer_route=route_value if route_value in RENDERER_ROUTES else None,
        )

    # render / video_item → project page (project_id always present).
    target = TEMPLATE_PROJECT.format(project_id=project_id)
    route_value = _str_anchor(evidence, "renderer_route")
    return QcNavigationData(
        qc_item_id=item.id,
        layer_ref_type=kind,
        canonical_location=loc,
        action=_navigate(target, TEMPLATE_PROJECT),
        renderer_route=route_value if route_value in RENDERER_ROUTES else None,
    )