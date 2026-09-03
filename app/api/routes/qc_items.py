"""QCItem READ-ONLY API routes (S11-T02B, Decision A).

The HTTP surface is GET-only by construction — creation/upsert/lifecycle
live exclusively in the internal repository (app.persistence.qc_items),
called by check runners/services, NEVER by this router:

- ``GET /api/v2/projects/{project_id}/qc-items`` — queue list (lane-C G1
  shape): exact filters status/severity/category/video_item_id + bounded
  limit/offset paging, deterministic ordering, ``total``/``has_more``.
- ``GET /api/v2/qc-items/{item_id}`` — one item + evidence refs (lane-C G2
  shape, navigation-ready location/evidence fields).

Workspace is server-owned (DEFAULT_WORKSPACE_ID); an id that exists in
another workspace is answered 404 exactly like an unknown id (fail-closed
ownership, zero leak).  Invalid filter values are 422.  No ORM object ever
crosses this boundary: the repository hands frozen dataclasses and the
routes map them to frozen response DTOs (lane-A §2 #4).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.qc_items import (
    QCItemNotFoundError,
    QCItemParamsError,
    QCItemRepository,
)
from app.schemas.qc_items import QCItemData, QCItemListResponse

router = APIRouter(prefix="/api/v2", tags=["qc-items"])

#: The local install owns exactly one workspace (contract §3) — server-owned.
WORKSPACE_ID = DEFAULT_WORKSPACE_ID

#: Hard bound for one collection page (G1 shape; bounded query count).
QC_ITEM_PAGE_LIMIT_MAX = 200


@router.get("/projects/{project_id:uuid}/qc-items")
@router.get("/projects/{project_id:uuid}/qc-items/")
def list_qc_items(
    project_id: uuid.UUID,
    session: SessionDep,
    status: str | None = Query(default=None, max_length=16),
    severity: str | None = Query(default=None, max_length=16),
    category: str | None = Query(default=None, max_length=48),
    video_item_id: str | None = Query(default=None, max_length=36),
    limit: Annotated[int, Query(ge=1, le=QC_ITEM_PAGE_LIMIT_MAX)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QCItemListResponse:
    """List QC items of a project (workspace-scoped, filterable, paged)."""
    repo = QCItemRepository(session)
    try:
        records, total = repo.list(
            WORKSPACE_ID,
            project_id=str(project_id),
            status=status,
            severity=severity,
            category=category,
            video_item_id=video_item_id,
            limit=limit,
            offset=offset,
        )
    except QCItemParamsError as err:
        raise HTTPException(422, str(err)) from err
    has_more = offset + len(records) < total
    return QCItemListResponse(
        workspace_id=WORKSPACE_ID,
        project_id=str(project_id),
        limit=limit,
        offset=offset,
        total=total,
        has_more=has_more,
        items=[QCItemData.from_record(record) for record in records],
    )


@router.get("/qc-items/{item_id:uuid}")
@router.get("/qc-items/{item_id:uuid}/")
def get_qc_item(item_id: uuid.UUID, session: SessionDep) -> QCItemData:
    """Read one QCItem with its evidence refs (404 for foreign/unknown)."""
    repo = QCItemRepository(session)
    try:
        record = repo.get(str(item_id), WORKSPACE_ID)
    except QCItemNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return QCItemData.from_record(record)