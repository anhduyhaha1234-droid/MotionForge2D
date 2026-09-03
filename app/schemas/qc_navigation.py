"""Read-only Pydantic DTOs for the QC navigation domain (S11-T04A).

FREEZE C2-F1: this is T04A's OWN navigation schema — ``app/schemas/qc_items.py``
(T02B-owned) is never touched; T04A only imports ``QCItemData`` from it.

Shape follows lane-c REVIEW_QUEUE_CONTRACT §2 / API_UI_GAP_MATRIX G2/G12/G13:
every QCItem resolves to a canonical location + a 1-1 navigation target per
location kind (frame/object/audio/scene/segment/render/route).  Decisions:

- Response DTOs are strict (``extra="forbid"``), frozen-free Pydantic models
  matching the project's durable-DTO convention — clients can never add
  fields and get silent passthrough.
- ``action.kind`` is binary: ``navigate`` (target/endpoint present) or
  ``explain`` (Decision E — issue ngoài phạm vi rerun V1: blocker still
  presented with a stable ``code`` + Vietnamese ``reason``, NO dead link).
- ``canonical_location`` is REQUIRED in every response (acceptance
  criterion 3): scene_id / frame_index / timecode_ms / object_role_id /
  segment ids come ONLY from structured data (typed evidence keys + frozen
  QCItem fields) — never inferred from free text (MASTER_PLAN §10).
- The 500 fail-closed envelope (``QcNavigationErrorData``) carries a stable
  ``code`` so a client can render the exact failure (unknown kind ⇒
  ``unknown_kind``) instead of guessing a target.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CanonicalLocationData",
    "NavigationActionData",
    "QcNavigationData",
    "QcNavigationErrorData",
]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanonicalLocationData(_StrictBase):
    """STRUCTURED-only canonical anchors for one QCItem.

    Every field is nullable because a location kind legitimately has no
    frame (audio) or no role (scene) — but the OBJECT itself is always
    present in the response.  Absent anchors mean ``None``, never a
    free-text guess.  ``segment_row_id``/``segment_logical_id`` mirror the
    frozen QCItem fields (durable join key — names are never joins).
    """

    scene_id: int | None = None
    frame_index: int | None = None
    timecode_ms: int | None = None
    object_role_id: str | None = None
    segment_row_id: str | None = None
    segment_logical_id: str | None = None


class NavigationActionData(_StrictBase):
    """1-1 navigation action for the QCItem's location kind.

    - ``navigate``: ``target`` is the concrete URL, ``endpoint`` is the
      registered path template (client-verifiable against OpenAPI).
    - ``explain``: ``target`` MUST be None (no dead link); ``code`` +
      ``reason`` explain why the item is out of rerun-V1 scope.
    """

    kind: Literal["navigate", "explain"]
    method: Literal["GET"]
    target: str | None = None
    endpoint: str | None = None
    code: str | None = None
    reason: str | None = None


class QcNavigationData(_StrictBase):
    """GET /api/v2/qc-navigation/{item_id} response body."""

    qc_item_id: str
    layer_ref_type: str
    canonical_location: CanonicalLocationData
    action: NavigationActionData
    #: Renderer route for kind render/route, carried ONLY when the value is
    #: inside the structural_lock contract (RENDERER_ROUTES) — fail-closed.
    renderer_route: str | None = None


class QcNavigationErrorData(_StrictBase):
    """Stable 500 envelope — canonical mapping missing, never a guess."""

    code: str
    message: str