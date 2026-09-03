"""QC navigation READ-ONLY API routes (S11-T04A / W9).

``GET /api/v2/qc-navigation/{item_id}`` — canonical location + 1-1
navigation target for one QCItem (lane-c REVIEW_QUEUE_CONTRACT §2 /
API_UI_GAP_MATRIX G2/G12/G13).  Decision A hold: the surface is GET-only by
construction — zero mutation methods exist in this router; QCItem creation
stays exclusively in the internal repository (T02B, imported only).

Ownership is fail-closed exactly like the qc-items detail route: an id that
exists in another workspace answers 404 (zero existence leak).  The
resolver answers 500 fail-closed (stable envelope ``{code, message}``) when
the canonical mapping is missing (unknown location kind) — the client never
receives a guessed target.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.qc_items import QCItemNotFoundError, QCItemRepository
from app.schemas.qc_items import QCItemData
from app.schemas.qc_navigation import QcNavigationData
from app.services.qc_navigation import NavigationResolutionError, resolve_navigation

router = APIRouter(prefix="/api/v2", tags=["qc-navigation"])

#: The local install owns exactly one workspace (contract §3) — server-owned.
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.get("/qc-navigation/{item_id:uuid}")
@router.get("/qc-navigation/{item_id:uuid}/")
def get_qc_navigation(item_id: uuid.UUID, session: SessionDep) -> QcNavigationData:
    """Resolve canonical location + navigation target for one QCItem."""
    repo = QCItemRepository(session)
    try:
        record = repo.get(str(item_id), WORKSPACE_ID)
    except QCItemNotFoundError as err:
        raise HTTPException(404, str(err)) from err

    item = QCItemData.from_record(record)
    try:
        return resolve_navigation(item)
    except NavigationResolutionError as err:
        # Fail-closed: canonical mapping missing → stable 500, never a guess.
        raise HTTPException(
            500, detail={"code": err.code, "message": err.message}
        ) from err