"""S11-T04B (W10) — QCItem → ObjectCorrection bridge.

SOLE OWNER of the mapping ``QCItem -> correction request`` (production plan
REV7/C6, W10 block, SHA 34247926...).  The correction flow for a QC item
anchored on an occurrence / segment / StructuralLock / renderer route
REUSES the existing S08-T05 pipeline (preview ImpactData -> confirm CAS ->
RECOMPUTE_OBJECTS) by CONSUMPTION only:

- schemas: ``app.schemas.object_correction`` (read-only import surface)
- repository/service: ``app.persistence.object_correction`` (same functions
  the registered HTTP routes call; nothing is re-implemented) and the
  registered routes are exercised by the test suite through a REAL
  TestClient on the temp app
- lifecycle: ``app.persistence.qc_items`` (import-only: acknowledge +
  recheck-gated transitions, never edited)
- stale reopen: ``app.services.qc_checks.orchestrator.reopen_stale_evidence``
  (the GAP-8 hook, shared with T03F)
- recheck trigger: ``app.workflow.qc_checks_handler.submit_run_qc_checks``
  (T03G submit authority) and ``run_full_check_set`` (T03F orchestrator)

V1 rerun scope (Decision E) is EXACTLY the four anchors below; everything
else is refused with an explain-action (never a guess, never a
whole-project rerun — AC1/AC2):
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    RENDERER_ROUTES,
    ProjectCastMapping,
    S10FullApplyChunk,
    S10FullApplyRun,
)
from app.persistence.object_correction import (
    CorrectionConflictError,
    CorrectionRecord,
    ObjectCorrectionRepository,
)
from app.persistence.object_intelligence import (
    OccurrenceConflictError,
    ObjectIntelligenceRepository,
    OccurrenceNotFoundError,
    OccurrenceRecord,
    OwnershipMismatchError,
    RoleConflictError,
)
from app.persistence.qc_items import (
    QCItemInvalidTransitionError,
    QCItemRecord,
    QCItemRepository,
)
from app.persistence.structural_evidence import (
    SegmentNotFoundError,
    SegmentRecord,
    StructuralEvidenceRepository,
)
from app.persistence.structural_lock import (
    LockManifestRecord,
    StructuralLockNotFoundError,
    StructuralLockRepository,
)
from app.schemas.object_correction import ImpactData
from app.services.qc_checks.orchestrator import reopen_stale_evidence
from app.workflow.qc_checks_handler import (
    QcCheckRunSubmitResult,
    submit_run_qc_checks,
)

__all__ = [
    "RERUN_ANCHORS",
    "QcCorrectionBridgeError",
    "QcRerunOutOfScopeError",
    "RerunScopeDecision",
    "StaleCheckResult",
    "CorrectionChainResult",
    "classify_rerun_scope",
    "role_changed_guard",
    "shot_correction_intent",
    "ShotCorrectionIntent",
    "build_correction_request",
    "preview_for_item",
    "run_correction_chain",
    "confirm_correction_for_item",
    "mark_item_recheck",
    "submit_recheck_run",
    "reopen_if_stale",
    "check_stale_evidence",
]

# ── V1 rerun anchors (Decision E — the ONLY in-scope set) ──────────────────

RERUN_ANCHOR_OCCURRENCE = "occurrence"
RERUN_ANCHOR_SEGMENT = "segment"
RERUN_ANCHOR_STRUCTURAL_LOCK = "structural_lock"
RERUN_ANCHOR_RENDERER_ROUTE = "renderer_route"

RERUN_ANCHORS: tuple[str, ...] = (
    RERUN_ANCHOR_OCCURRENCE,
    RERUN_ANCHOR_SEGMENT,
    RERUN_ANCHOR_STRUCTURAL_LOCK,
    RERUN_ANCHOR_RENDERER_ROUTE,
)

#: Stable Decision-E explain-action codes (rendered verbatim by the client).
EXPLAIN_REASONS: dict[str, str] = {
    "not_in_rerun_scope": (
        "Issue neo ở lớp không thuộc phạm vi rerun V1 (chỉ occurrence / "
        "segment / StructuralLock / renderer route) — không có correction "
        "targeted; không tự đoán anchor."
    ),
    "renderer_route_outside_contract": (
        "Renderer route không nằm trong contract structural_lock "
        "(RENDERER_ROUTES) — fail-closed, không tạo correction."
    ),
    "missing_occurrence_anchor": (
        "Thiếu occurrence anchor có cấu trúc (object_role_id / occurrence_id "
        "trong evidence) — không thể xác định occurrence; issue ngoài phạm vi "
        "rerun V1."
    ),
    "missing_segment_anchor": (
        "Thiếu segment anchor có cấu trúc (segment_row_id / segment_id trong "
        "evidence) — không thể xác định segment; issue ngoài phạm vi rerun V1."
    ),
    "missing_structural_lock_anchor": (
        "Thiếu lock_manifest_id có cấu trúc trong evidence — không thể neo "
        "StructuralLock; issue ngoài phạm vi rerun V1."
    ),
}

#: Structured evidence keys the bridge reads (typed anchors only — no free
#: text parsing, MASTER_PLAN §10).
_EV_OBJECT_ROLE_ID = "object_role_id"
_EV_OCCURRENCE_ID = "occurrence_id"
_EV_ROLE_REVISION = "role_revision"
_EV_OCCURRENCE_REVISION = "occurrence_revision"
_EV_SEGMENT_ID = "segment_id"
_EV_LINEAGE_VERSION = "lineage_version"
_EV_LOCK_MANIFEST_ID = "lock_manifest_id"
_EV_RENDERER_ROUTE = "renderer_route"
_EV_CAST_REVISION = "cast_revision"


class QcRerunOutOfScopeError(Exception):
    """Decision E explain-action: the item is NOT in V1 rerun scope.

    Carries a stable ``code`` + a human (Vietnamese) ``reason`` the client
    can render verbatim — there is never a fallback correction request.
    """

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


class QcCorrectionBridgeError(Exception):
    """Bridge-level failure with a stable machine code.

    ``ROLE_CHANGED`` is the stale-guard: the anchor role/occurrence revision
    recorded in the item's evidence no longer matches the persisted row (or
    the pipeline answered a CAS/ownership conflict at confirm time), so the
    correction is refused — the item must be rechecked on fresh evidence.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RerunScopeDecision:
    """Binary scope verdict for ONE QCItem (V1, Decision E)."""

    in_scope: bool
    anchor: str | None = None
    explain_code: str | None = None
    explain_reason: str | None = None


@dataclass(frozen=True)
class StaleCheckResult:
    """GAP-8 service-level staleness verdict for ONE QCItem."""

    stale: bool
    anchor: str | None = None
    superseded_by_id: str | None = None
    manifest_revision: str | None = None
    cast_revision: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CorrectionChainResult:
    """Outcome of preview -> create -> confirm (one caller-owned tx)."""

    correction_id: str
    status: str
    created: bool
    impact: ImpactData
    recompute_job_id: str | None
    applied_revision: int


# ── structured-anchor helpers (typed; never coerced) ───────────────────────

def _str_anchor(evidence: Mapping[str, Any], key: str) -> str | None:
    value = evidence.get(key)
    if not isinstance(value, str) or not value:
        return None
    return value


def _int_anchor(evidence: Mapping[str, Any], key: str) -> int | None:
    value = evidence.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# ── scope classification (pure — no I/O) ───────────────────────────────────

def classify_rerun_scope(item: QCItemRecord) -> RerunScopeDecision:
    """Binary V1 scope check (Decision E) — occurrence/segment/StructuralLock/
    renderer route ONLY; everything else answers an explain-action.

    Pure and structured-only: the verdict is computed from the frozen
    QCItem fields + typed evidence keys, never from free text.
    """
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    kind = item.layer_ref_type

    if kind == "object":
        role_id = _str_anchor(evidence, _EV_OBJECT_ROLE_ID) or _str_anchor(
            evidence, "role_id"
        )
        occ_id = _str_anchor(evidence, _EV_OCCURRENCE_ID)
        if role_id is not None or occ_id is not None:
            return RerunScopeDecision(True, RERUN_ANCHOR_OCCURRENCE)
        return RerunScopeDecision(
            False,
            explain_code="missing_occurrence_anchor",
            explain_reason=EXPLAIN_REASONS["missing_occurrence_anchor"],
        )

    if kind == "segment":
        seg_id = _segment_id(item, evidence)
        if seg_id is not None:
            return RerunScopeDecision(True, RERUN_ANCHOR_SEGMENT)
        return RerunScopeDecision(
            False,
            explain_code="missing_segment_anchor",
            explain_reason=EXPLAIN_REASONS["missing_segment_anchor"],
        )

    if kind == "route":
        route = _str_anchor(evidence, _EV_RENDERER_ROUTE)
        if route is not None and route not in RENDERER_ROUTES:
            return RerunScopeDecision(
                False,
                explain_code="renderer_route_outside_contract",
                explain_reason=EXPLAIN_REASONS["renderer_route_outside_contract"],
            )
        if route in RENDERER_ROUTES:
            return RerunScopeDecision(True, RERUN_ANCHOR_RENDERER_ROUTE)
        if _segment_id(item, evidence) is not None:
            # A route-carried issue WITHOUT the contract value cannot be
            # mapped to a renderer route — refused (no guessing).
            return RerunScopeDecision(
                False,
                explain_code="renderer_route_outside_contract",
                explain_reason=EXPLAIN_REASONS["renderer_route_outside_contract"],
            )
        return RerunScopeDecision(
            False,
            explain_code="missing_segment_anchor",
            explain_reason=EXPLAIN_REASONS["missing_segment_anchor"],
        )

    if kind == "render":
        lock_id = _str_anchor(evidence, _EV_LOCK_MANIFEST_ID)
        if lock_id is not None:
            return RerunScopeDecision(True, RERUN_ANCHOR_STRUCTURAL_LOCK)
        return RerunScopeDecision(
            False,
            explain_code="missing_structural_lock_anchor",
            explain_reason=EXPLAIN_REASONS["missing_structural_lock_anchor"],
        )

    # frame / audio / scene / video_item (and any unknown kind) — no
    # targeted-correction anchor exists; whole-project rerun NEVER exists.
    return RerunScopeDecision(
        False,
        explain_code="not_in_rerun_scope",
        explain_reason=EXPLAIN_REASONS["not_in_rerun_scope"],
    )


def _segment_id(item: QCItemRecord, evidence: Mapping[str, Any]) -> str | None:
    if item.segment_row_id:
        return item.segment_row_id
    return _str_anchor(evidence, _EV_SEGMENT_ID)


def _require_in_scope(item: QCItemRecord) -> RerunScopeDecision:
    decision = classify_rerun_scope(item)
    if not decision.in_scope:
        raise QcRerunOutOfScopeError(
            decision.explain_code or "not_in_rerun_scope",
            decision.explain_reason or EXPLAIN_REASONS["not_in_rerun_scope"],
        )
    return decision


# ── resource resolution (read-only ORM/repository access) ──────────────────

def _role_row(session: Session, role_id: str) -> Any:
    from app.persistence.models import ObjectRole

    row = session.get(ObjectRole, role_id)
    if row is None:
        raise QcCorrectionBridgeError(
            "CORRECTION_UNRESOLVABLE",
            f"role {role_id!r} does not exist — không thể tạo correction.",
        )
    return row


def _occurrence_for_role(
    session: Session,
    workspace_id: str,
    role_id: str,
    *,
    video_item_id: str,
    scene_id: str | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
    preferred_id: str | None = None,
) -> OccurrenceRecord:
    """Deterministic occurrence resolution for a targeted correction."""
    repo = ObjectIntelligenceRepository(session)
    if preferred_id is not None:
        try:
            occ = repo.get_occurrence(workspace_id, role_id, preferred_id)
        except OccurrenceNotFoundError as err:
            raise QcCorrectionBridgeError(
                "CORRECTION_UNRESOLVABLE",
                f"occurrence {preferred_id!r} không tồn tại cho role "
                f"{role_id!r}: {err}",
            ) from err
        if occ.video_item_id != video_item_id:
            raise QcCorrectionBridgeError(
                "CORRECTION_UNRESOLVABLE",
                "occurrence thuộc video khác — không tạo correction chéo video.",
            )
        return occ
    occurrences = repo.list_occurrences(workspace_id, role_id)
    if scene_id is not None and start_frame is not None:
        for occ in occurrences:
            if occ.video_item_id != video_item_id:
                continue
            if occ.scene_id == scene_id and start_frame <= occ.frame_index <= (
                end_frame if end_frame is not None else start_frame
            ):
                return occ
    for occ in occurrences:
        if occ.video_item_id == video_item_id:
            return occ
    raise QcCorrectionBridgeError(
        "CORRECTION_UNRESOLVABLE",
        f"role {role_id!r} không có occurrence nào trong video "
        f"{video_item_id!r} — không thể neo occurrence cho correction.",
    )


def _segment_record(
    session: Session, workspace_id: str, segment_id: str
) -> SegmentRecord:
    try:
        return StructuralEvidenceRepository(session).get_segment(
            workspace_id, segment_id, only_current=False
        )
    except Exception as err:  # SegmentNotFoundError et al — wrap for the bridge
        raise QcCorrectionBridgeError(
            "CORRECTION_UNRESOLVABLE",
            f"segment {segment_id!r} không tồn tại/không đọc được: {err}",
        ) from err


def _occurrence_for_segment(
    session: Session,
    workspace_id: str,
    segment: SegmentRecord,
    item: QCItemRecord,
) -> OccurrenceRecord:
    return _occurrence_for_role(
        session,
        workspace_id,
        segment.role_id,
        video_item_id=item.video_item_id,
        scene_id=segment.scene_id,
        start_frame=segment.start_frame,
        end_frame=segment.end_frame,
        preferred_id=_str_anchor(
            item.evidence if isinstance(item.evidence, dict) else {}, _EV_OCCURRENCE_ID
        ),
    )


def _resolve_anchor_occurrence(
    session: Session,
    item: QCItemRecord,
    *,
    workspace_id: str,
) -> tuple[str, OccurrenceRecord]:
    """Map the V1 anchor to (role_id, occurrence) — the correction target.

    occurrence        -> evidence object_role_id + evidence occurrence_id
                         (fallback: first occurrence of the role in video)
    segment           -> segment row (segment_row_id / evidence.segment_id)
                         -> role -> occurrence within the segment's window
    structural_lock   -> lock manifest -> first manifest segment's
                         occurrence_segment_id -> segment -> role -> occurrence
    renderer_route    -> segment anchor -> role -> occurrence (same as segment)
    """
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    decision = _require_in_scope(item)
    anchor = decision.anchor

    if anchor == RERUN_ANCHOR_OCCURRENCE:
        role_id = _str_anchor(evidence, _EV_OBJECT_ROLE_ID) or _str_anchor(
            evidence, "role_id"
        )
        if role_id is None:
            raise QcCorrectionBridgeError(
                "CORRECTION_UNRESOLVABLE",
                "occurrence anchor thiếu object_role_id — không thể tạo "
                "correction.",
            )
        occ = _occurrence_for_role(
            session,
            workspace_id,
            role_id,
            video_item_id=item.video_item_id,
            preferred_id=_str_anchor(evidence, _EV_OCCURRENCE_ID),
        )
        return role_id, occ

    seg_id = _segment_id(item, evidence)
    if seg_id is None:
        raise QcCorrectionBridgeError(
            "CORRECTION_UNRESOLVABLE",
            "không có segment anchor để neo correction.",
        )

    if anchor == RERUN_ANCHOR_STRUCTURAL_LOCK:
        lock_id = _str_anchor(evidence, _EV_LOCK_MANIFEST_ID)
        manifest = _lock_manifest(session, workspace_id, lock_id)
        segment_refs = manifest.manifest.get("segments") or []
        first = segment_refs[0] if segment_refs else None
        if first is None:
            raise QcCorrectionBridgeError(
                "CORRECTION_UNRESOLVABLE",
                "lock manifest không chứa segment nào — không thể neo "
                "occurrence cho correction.",
            )
        seg_id = str(first.get("occurrence_segment_id") or "")

    segment = _segment_record(session, workspace_id, seg_id)
    occ = _occurrence_for_segment(session, workspace_id, segment, item)
    return segment.role_id, occ


def _lock_manifest(
    session: Session, workspace_id: str, manifest_id: str | None
) -> LockManifestRecord:
    if not manifest_id:
        raise QcCorrectionBridgeError(
            "CORRECTION_UNRESOLVABLE",
            "structural_lock anchor thiếu lock_manifest_id.",
        )
    try:
        return StructuralLockRepository(session).get_manifest(manifest_id, workspace_id)
    except Exception as err:
        raise QcCorrectionBridgeError(
            "CORRECTION_UNRESOLVABLE",
            f"lock manifest {manifest_id!r} không đọc được: {err}",
        ) from err


# ── ROLE_CHANGED stale-guard ───────────────────────────────────────────────

def _current_role_revision(session: Session, role_id: str) -> int:
    return int(_role_row(session, role_id).revision)


def _current_occurrence_revision(
    session: Session, workspace_id: str, role_id: str, occurrence_id: str
) -> int:
    repo = ObjectIntelligenceRepository(session)
    try:
        return int(repo.get_occurrence(workspace_id, role_id, occurrence_id).revision)
    except OccurrenceNotFoundError as err:
        raise QcCorrectionBridgeError(
            "ROLE_CHANGED",
            f"occurrence {occurrence_id!r} không còn tồn tại — evidence của "
            "QC item đã stale, cần recheck trước khi correction.",
        ) from err


def role_changed_guard(
    session: Session, item: QCItemRecord, *, workspace_id: str
) -> None:
    """Stale-guard BEFORE any pipeline call: the anchor revisions recorded in
    the item's evidence must still match the persisted rows.

    ``role_revision`` / ``occurrence_revision`` are OPTIONAL structured
    evidence keys; when present and mismatch => the item's evidence is stale
    (ROLE_CHANGED, stable code + Vietnamese explain).  Wrong-typed values are
    treated as absent — never coerced.
    """
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    role_id = _str_anchor(evidence, _EV_OBJECT_ROLE_ID) or _str_anchor(
        evidence, "role_id"
    )
    expected_role = _int_anchor(evidence, _EV_ROLE_REVISION)
    if role_id is not None and expected_role is not None:
        current = _current_role_revision(session, role_id)
        if current != expected_role:
            raise QcCorrectionBridgeError(
                "ROLE_CHANGED",
                f"role {role_id!r} revision đã đổi {expected_role} -> {current} "
                "kể từ lúc QC item được tạo — evidence stale; recheck trước "
                "khi correction (GAP-8).",
            )
    occ_id = _str_anchor(evidence, _EV_OCCURRENCE_ID)
    expected_occ = _int_anchor(evidence, _EV_OCCURRENCE_REVISION)
    if role_id is not None and occ_id is not None and expected_occ is not None:
        current = _current_occurrence_revision(session, workspace_id, role_id, occ_id)
        if current != expected_occ:
            raise QcCorrectionBridgeError(
                "ROLE_CHANGED",
                f"occurrence {occ_id!r} revision đã đổi {expected_occ} -> "
                f"{current} kể từ lúc QC item được tạo — evidence stale; "
                "recheck trước khi correction (GAP-8).",
            )


# ── correction request mapping (SOLE OWNER) ────────────────────────────────

def build_correction_request(
    session: Session,
    item: QCItemRecord,
    *,
    workspace_id: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Map ONE in-scope QCItem to the existing pipeline's request payload.

    The V1 targeted correction is ``candidate_edit`` on the resolved
    occurrence (``review_state=rejected`` + reason) — deterministic,
    real-occurrence CAS, and it triggers RECOMPUTE_OBJECTS through the
    existing pipeline when the role is DISCOVER-produced.
    """
    _require_in_scope(item)
    role_id, occ = _resolve_anchor_occurrence(session, item, workspace_id=workspace_id)
    role = _role_row(session, role_id)
    request: dict[str, Any] = {
        "kind": "candidate_edit",
        "project_id": item.project_id,
        "video_item_id": item.video_item_id,
        "generation": role.source_generation,
        "target": "occurrence",
        "role_id": role_id,
        "occurrence_id": occ.id,
        "occurrence_revision": occ.revision,
        "review_state": "rejected",
        "reasons": [f"qc:{item.reason_code}"],
    }
    if idempotency_key is not None:
        request["idempotency_key"] = idempotency_key
    return request


# ── the S08-T05 chain (preview -> confirm -> RECOMPUTE_OBJECTS) ────────────

def preview_for_item(
    session: Session, item: QCItemRecord, *, workspace_id: str
) -> ImpactData:
    """Pre-confirmation impacted-scope report — ZERO durable writes.

    Consumes ``ObjectCorrectionRepository.compute_impact`` — the exact
    function the registered ``POST /corrections/preview`` route calls.
    """
    _require_in_scope(item)
    request = build_correction_request(session, item, workspace_id=workspace_id)
    impact = ObjectCorrectionRepository(session).compute_impact(
        workspace_id,
        item.project_id,
        item.video_item_id,
        str(request["kind"]),
        request,
    )
    return ImpactData(
        correction_type=impact.correction_type,
        affected_role_ids=list(impact.affected_role_ids),
        affected_occurrence_ids=list(impact.affected_occurrence_ids),
        invalidated_suggestion_ids=list(impact.invalidated_suggestion_ids),
        artifact_role_ids=list(impact.artifact_role_ids),
        regenerate_suggestions=impact.regenerate_suggestions,
        recompute_needed=impact.recompute_needed,
        counts=dict(impact.counts),
    )


def _raise_pipeline_conflict(err: Exception) -> NoReturn:
    """Translate a stale/CAS/ownership pipeline answer to the stable
    ``ROLE_CHANGED`` guard (never a raw 5xx; never a silent retry)."""
    raise QcCorrectionBridgeError(
        "ROLE_CHANGED",
        f"pipeline từ chối với conflict (anchor đã đổi giữa chừng) — {err}",
    ) from err


def confirm_correction_for_item(
    session: Session,
    item: QCItemRecord,
    *,
    workspace_id: str,
    correction_id: str,
    revision: int,
    managed_root: str,
) -> tuple[CorrectionRecord, bool]:
    """Confirm a pending correction with the pipeline's atomic CAS
    (targeted mutation + supersession + RECOMPUTE_OBJECTS in ONE
    transaction — S08-T05 contract).  A stale/ownership pipeline answer is
    translated to the bridge's stable ``ROLE_CHANGED`` guard."""
    role_changed_guard(session, item, workspace_id=workspace_id)
    try:
        return ObjectCorrectionRepository(session).confirm_correction(
            workspace_id,
            correction_id,
            revision,
            managed_root=managed_root,
        )
    except (
        CorrectionConflictError,
        RoleConflictError,
        OccurrenceConflictError,
        OwnershipMismatchError,
    ) as err:
        _raise_pipeline_conflict(err)


def run_correction_chain(
    session: Session,
    item: QCItemRecord,
    *,
    workspace_id: str,
    managed_root: str,
    idempotency_key: str | None = None,
) -> CorrectionChainResult:
    """preview -> create(pending) -> confirm(CAS -> RECOMPUTE_OBJECTS) in ONE
    caller-owned transaction (single commit at the caller).

    The pipeline functions are the same ones the registered routes call;
    preview itself performs ZERO writes and the confirm applies the targeted
    mutation + job creation atomically (S08-T05 contract).  Stale pipeline
    answers (CAS/ownership/role conflicts) surface as the stable
    ``ROLE_CHANGED`` guard.
    """
    role_changed_guard(session, item, workspace_id=workspace_id)
    request = build_correction_request(
        session,
        item,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key or f"qc-item:{item.id}",
    )
    repo = ObjectCorrectionRepository(session)
    try:
        impact = repo.compute_impact(
            workspace_id,
            item.project_id,
            item.video_item_id,
            str(request["kind"]),
            request,
        )
        record, created = repo.create_correction(
            workspace_id,
            item.project_id,
            item.video_item_id,
            str(request["kind"]),
            request,
            impact,
            idempotency_key=request.get("idempotency_key"),
        )
        applied, confirmed = repo.confirm_correction(
            workspace_id,
            record.id,
            record.revision,
            managed_root=managed_root,
        )
    except (
        CorrectionConflictError,
        RoleConflictError,
        OccurrenceConflictError,
        OwnershipMismatchError,
    ) as err:
        _raise_pipeline_conflict(err)
    return CorrectionChainResult(
        correction_id=record.id,
        status=applied.status,
        created=created and confirmed,
        impact=ImpactData(
            correction_type=impact.correction_type,
            affected_role_ids=list(impact.affected_role_ids),
            affected_occurrence_ids=list(impact.affected_occurrence_ids),
            invalidated_suggestion_ids=list(impact.invalidated_suggestion_ids),
            artifact_role_ids=list(impact.artifact_role_ids),
            regenerate_suggestions=impact.regenerate_suggestions,
            recompute_needed=impact.recompute_needed,
            counts=dict(impact.counts),
        ),
        recompute_job_id=applied.recompute_job_id,
        applied_revision=int(applied.revision),
    )


# ── post-publish lifecycle: item -> recheck + orchestrator auto-resolve ────

def mark_item_recheck(
    session: Session, item: QCItemRecord, *, workspace_id: str
) -> QCItemRecord:
    """Move the QC item to the recheck lane after a publish OK.

    ``open -> acknowledged`` via the T02B repository lifecycle (import-only
    consume); the orchestrator's fresh recheck then auto-resolves it
    (T03F owner).  A no-op/illegal transition is refused fail-closed by the
    repository's stable transition errors.
    """
    repo = QCItemRepository(session)
    if item.status == "open":
        return repo.acknowledge(item.id, workspace_id)
    if item.status == "acknowledged":
        return item
    raise QCItemInvalidTransitionError(
        f"QCItem {item.id!r} is in status {item.status!r} and cannot be "
        "moved to the recheck lane"
    )


def submit_recheck_run(
    session_factory: Callable[[], Session],
    item: QCItemRecord,
    *,
    workspace_id: str,
    scope: str,
    detector_args: Mapping[str, Mapping[str, Any]],
    generation: str = "1",
) -> QcCheckRunSubmitResult:
    """Queue the durable recheck run through the T03G submit authority
    (server-owned RUN_QC_CHECKS job) — never a new submit path."""
    return submit_run_qc_checks(
        session_factory,
        workspace_id=workspace_id,
        project_id=item.project_id,
        video_item_id=item.video_item_id,
        scope=scope,
        detector_args=detector_args,
        generation=generation,
    )


# ── MF-END-23: finding → SHOT correction intent ─────────────────────────────


@dataclass(frozen=True)
class ShotCorrectionIntent:
    """A finding resolved onto the SHOT(s) a targeted correction must re-render.

    ``shots`` carries every persisted chunk whose core span contains part of
    the finding's frame window — the correction intent names the exact
    ``shot_id`` set (and their frame spans + chunk ids) so the rerun touches
    ONLY the shot(s) that actually contain the finding.  A finding whose frame
    window cannot be resolved, or which lies outside every persisted shot, is
    REFUSED (``CORRECTION_SHOT_UNRESOLVED``) — a shot is never guessed.
    """

    workspace_id: str
    project_id: str
    video_item_id: str
    window: dict[str, int]
    shots: list[dict[str, Any]]
    render_artifact_id: str | None
    render_sha256: str | None
    anchor: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "shot_correction",
            "schema": "mf-end-23/shot-correction-intent@1",
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "video_item_id": self.video_item_id,
            "window": dict(self.window),
            "shots": [dict(shot) for shot in self.shots],
            "render_artifact_id": self.render_artifact_id,
            "render_sha256": self.render_sha256,
            "anchor": dict(self.anchor),
        }


def _finding_window(item: QCItemRecord) -> tuple[int, int] | None:
    """The finding's frame window from STRUCTURED evidence (typed, no parsing).

    Accepted shapes, in order: ``frame_start``/``frame_end`` (inclusive),
    ``window.{start_frame,end_frame_exclusive}``, ``frames[]`` (min..max),
    and — when only a segment anchor exists — the segment's own frame span.
    Wrong-typed values are treated as absent, never coerced.
    """
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    start = _int_anchor(evidence, "frame_start")
    end = _int_anchor(evidence, "frame_end")
    if start is not None and end is not None and end >= start:
        return start, end
    window = evidence.get("window")
    if isinstance(window, dict):
        w_start = _int_anchor(window, "start_frame")
        w_end = _int_anchor(window, "end_frame_exclusive")
        if w_start is not None and w_end is not None and w_end > w_start:
            return w_start, w_end - 1
    frames = evidence.get("frames")
    if isinstance(frames, list) and frames:
        ints = [int(v) for v in frames if isinstance(v, (int, float))]
        if ints:
            return min(ints), max(ints)
    return None


def shot_correction_intent(
    session: Session, item: QCItemRecord, *, workspace_id: str
) -> ShotCorrectionIntent:
    """Map ONE QC finding onto the SHOT(s) a targeted correction must touch.

    Resolution rules (fail-closed, no guessing):

    * the finding's frame window comes from its STRUCTURED evidence
      (:func:`_finding_window`); a segment anchor may supply it through the
      segment's own frame span;
    * the shot inventory is the newest persisted S10 full-apply run of the
      video with chunk rows (core spans); the intent carries every chunk
      whose ``[core_start_frame, core_end_frame]`` INTERSECTS the window;
    * no window ⇒ ``CORRECTION_SHOT_UNRESOLVED``; no intersecting shot ⇒
      ``CORRECTION_SHOT_UNRESOLVED`` (the finding is not attributable to any
      rendered shot — it is NOT routed to a whole-video rerun).

    The intent also pins the CURRENT rendered-output identity so the caller
    can detect a stale finding before spending a render.
    """
    window = _finding_window(item)
    if window is None:
        evidence_map = item.evidence if isinstance(item.evidence, dict) else {}
        seg_id = _segment_id(item, evidence_map)
        if seg_id is not None:
            segment = _segment_record(session, workspace_id, seg_id)
            if segment is not None:
                window = (
                    int(segment.start_frame),
                    max(int(segment.start_frame), int(segment.end_frame) - 1),
                )
    if window is None:
        raise QcCorrectionBridgeError(
            "CORRECTION_SHOT_UNRESOLVED",
            "QC item không mang frame window có cấu trúc (frame_start/frame_end, "
            "window, frames[]) và không suy được từ segment anchor — không thể "
            "xác định shot cần correction (không đoán shot).",
        )
    w_start, w_end = window
    run = session.scalars(
        select(S10FullApplyRun)
        .where(
            S10FullApplyRun.workspace_id == workspace_id,
            S10FullApplyRun.video_item_id == item.video_item_id,
        )
        .order_by(S10FullApplyRun.created_at.desc(), S10FullApplyRun.id)
        .limit(1)
    ).first()
    if run is None:
        raise QcCorrectionBridgeError(
            "CORRECTION_SHOT_UNRESOLVED",
            f"video {item.video_item_id!r} chưa có S10 full-apply run nào để "
            "biết shot inventory — không thể neo correction vào shot.",
        )
    chunks = session.scalars(
        select(S10FullApplyChunk)
        .where(S10FullApplyChunk.run_id == run.id)
        .order_by(S10FullApplyChunk.shot_id, S10FullApplyChunk.chunk_index)
    ).all()
    by_shot: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        c_start = int(chunk.core_start_frame)
        c_end = int(chunk.core_end_frame)
        if c_end < w_start or c_start > w_end:
            continue
        shot_id = str(chunk.shot_id)
        entry = by_shot.setdefault(
            shot_id,
            {
                "shot_id": shot_id,
                "run_id": str(run.id),
                "core_start_frame": c_start,
                "core_end_frame": c_end,
                "chunk_ids": [],
                "layer_ids": [],
            },
        )
        entry["core_start_frame"] = min(entry["core_start_frame"], c_start)
        entry["core_end_frame"] = max(entry["core_end_frame"], c_end)
        entry["chunk_ids"].append(str(chunk.id))
        if chunk.layer_id:
            entry["layer_ids"].append(str(chunk.layer_id))
    if not by_shot:
        raise QcCorrectionBridgeError(
            "CORRECTION_SHOT_UNRESOLVED",
            f"finding window [{w_start},{w_end}] không giao với shot nào của run "
            f"{run.id!r} — không route correction vào shot không chứa finding.",
        )
    from app.services.qc_evidence.compose import render_row  # lazy: no cycle

    render: dict[str, Any] | None = None
    try:
        render = render_row(
            session,
            workspace_id=workspace_id,
            project_id=item.project_id,
            video_item_id=item.video_item_id,
        )
    except Exception:  # noqa: BLE001 - the intent stays usable without it
        render = None
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    anchor = {
        "role_id": _str_anchor(evidence, _EV_OBJECT_ROLE_ID)
        or _str_anchor(evidence, "role_id"),
        "occurrence_id": _str_anchor(evidence, _EV_OCCURRENCE_ID),
        "segment_id": _segment_id(item, evidence),
    }
    render_artifact = (render or {}).get("artifact") or {}
    return ShotCorrectionIntent(
        workspace_id=workspace_id,
        project_id=str(item.project_id),
        video_item_id=str(item.video_item_id),
        window={"start_frame": w_start, "end_frame": w_end},
        shots=[by_shot[key] for key in sorted(by_shot)],
        render_artifact_id=(
            str(render_artifact.get("artifact_id")) if render_artifact else None
        ),
        render_sha256=(str(render_artifact.get("sha256")) if render_artifact else None),
        anchor=anchor,
    )


# ── stale-evidence reopen (GAP-8 anchors + MF-END-23 render anchor) ─────────

def check_stale_evidence(
    session: Session, item: QCItemRecord, *, workspace_id: str
) -> StaleCheckResult:
    """Service-level staleness check performed AT RECHECK-RUN time (GAP-8).

    Exactly three anchors are consulted (lane-A GAP_RISKS R7/GAP-8):
      1. segment supersede  — the referenced OccurrenceSegment row carries
         a ``superseded_by_id`` (or a higher lineage version than the item's
         evidence recorded);
      2. manifest lifecycle  — the referenced StructuralLockManifest is no
         longer ``active`` (superseded/voided) / has a successor;
      3. cast revision       — the role's ProjectCastMapping revision no
         longer matches the item's structured ``cast_revision`` evidence.

    ReskinConfig is NEVER an anchor (lane-A phủ định): its revision (a
    params-CAS only, not a structural anchor) is never read here.
    """
    evidence = item.evidence if isinstance(item.evidence, dict) else {}

    seg_id = _segment_id(item, evidence)
    if seg_id is not None:
        try:
            segment = StructuralEvidenceRepository(session).get_segment(
                workspace_id, seg_id, only_current=False
            )
        except SegmentNotFoundError:
            # The referenced segment row no longer exists — the evidence's
            # segment anchor is gone (fail-closed: never silently fresh).
            return StaleCheckResult(
                stale=True,
                anchor="segment_superseded",
                superseded_by_id=None,
                reason="segment anchor không còn tồn tại — evidence stale",
            )
        recorded_lineage = _int_anchor(evidence, _EV_LINEAGE_VERSION)
        if segment.superseded_by_id is not None:
            return StaleCheckResult(
                stale=True,
                anchor="segment_superseded",
                superseded_by_id=segment.superseded_by_id,
                reason=(
                    "segment đã bị supersede — evidence của QC item chỉ "
                    "còn áp dụng cho segment cũ"
                ),
            )
        if (
            recorded_lineage is not None
            and segment.lineage_version > recorded_lineage
        ):
            return StaleCheckResult(
                stale=True,
                anchor="segment_superseded",
                superseded_by_id=segment.id,
                reason=(
                    "lineage_version của segment đã tăng so với evidence "
                    "(segment được supersede)"
                ),
            )

    lock_id = _str_anchor(evidence, _EV_LOCK_MANIFEST_ID)
    if lock_id is not None:
        try:
            manifest = StructuralLockRepository(session).get_manifest(
                lock_id, workspace_id
            )
        except StructuralLockNotFoundError:
            # The referenced lock manifest row no longer exists — the lock
            # anchor is gone (fail-closed: never silently fresh).
            return StaleCheckResult(
                stale=True,
                anchor="manifest_lifecycle",
                superseded_by_id=None,
                reason="lock manifest anchor không còn tồn tại — evidence stale",
            )
        if manifest.status != "active" or manifest.superseded_by_id is not None:
            return StaleCheckResult(
                stale=True,
                anchor="manifest_lifecycle",
                superseded_by_id=manifest.superseded_by_id,
                manifest_revision=str(manifest.revision),
                reason=(
                    f"lock manifest không còn active (status="
                    f"{manifest.status!r}) — evidence theo manifest cũ"
                ),
            )

    role_id = _str_anchor(evidence, _EV_OBJECT_ROLE_ID) or _str_anchor(
        evidence, "role_id"
    )
    cast_revision = _int_anchor(evidence, _EV_CAST_REVISION)
    if role_id is not None and cast_revision is not None:
        mapping = session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.workspace_id == workspace_id,
                ProjectCastMapping.project_id == item.project_id,
                ProjectCastMapping.object_role_id == role_id,
            )
        )
        if mapping is not None and int(mapping.revision) != cast_revision:
            return StaleCheckResult(
                stale=True,
                anchor="cast_revision",
                superseded_by_id=str(mapping.id),
                cast_revision=str(mapping.revision),
                reason=(
                    f"cast revision đã đổi {cast_revision} -> "
                    f"{int(mapping.revision)} — evidence cast của QC item stale"
                ),
            )

    # MF-END-23 4th anchor: the RENDERED OUTPUT the finding was observed on.
    # Typed keys only (``render_artifact_id`` / ``render_sha256``); absent keys
    # are NOT an anchor (never coerced, never invented).  When present, the
    # item's recorded render must still be the CURRENT rendered output —
    # otherwise the finding describes a superseded checkpoint and a rerun on
    # the new output must re-check it first (fail-closed when the current
    # output cannot be resolved).
    recorded_render = _str_anchor(evidence, "render_artifact_id")
    recorded_render_sha = _str_anchor(evidence, "render_sha256")
    if recorded_render is not None or recorded_render_sha is not None:
        from app.services.qc_evidence.compose import render_row  # lazy: no cycle

        try:
            current = render_row(
                session,
                workspace_id=workspace_id,
                project_id=item.project_id,
                video_item_id=item.video_item_id,
            )
        except Exception as err:  # noqa: BLE001 - fail closed, typed reason
            return StaleCheckResult(
                stale=True,
                anchor="render_changed",
                reason=(
                    f"không đọc được rendered output hiện tại ({err}) — evidence "
                    "render của QC item không xác minh được (fail closed)"
                ),
            )
        current_artifact = (current or {}).get("artifact") or {}
        current_id = str(current_artifact.get("artifact_id") or "")
        current_sha = str(current_artifact.get("sha256") or "")
        if (
            current is None
            or current.get("unusable") is not None
            or (recorded_render or "") != current_id
            or (recorded_render_sha or "") != current_sha
        ):
            return StaleCheckResult(
                stale=True,
                anchor="render_changed",
                superseded_by_id=current_id or None,
                reason=(
                    "rendered output đã đổi kể từ lúc QC item được tạo "
                    f"(recorded={recorded_render or '∅'}/{str(recorded_render_sha or '∅')[:12]} "
                    f"-> current={current_id or '∅'}/{current_sha[:12]} hoặc "
                    "render row không dùng được) — evidence stale; recheck trước "
                    "khi correction."
                ),
            )

    return StaleCheckResult(stale=False)


def reopen_if_stale(
    session: Session, item: QCItemRecord, *, workspace_id: str
) -> QCItemRecord | None:
    """Reopen an acknowledged item to ``open`` with the stale flag when a
    GAP-8 anchor fired; consume the T03F-provided hook (shared with the
    orchestrator's recheck path).  Terminal items stay terminal (the hook
    refuses them with the repository's stable transition error)."""
    result = check_stale_evidence(session, item, workspace_id=workspace_id)
    if not result.stale:
        return None
    return reopen_stale_evidence(
        QCItemRepository(session),
        item,
        workspace_id=workspace_id,
        superseded_by_id=result.superseded_by_id or item.id,
        supersession_reason=result.reason or "stale evidence superseded",
        manifest_revision=result.manifest_revision,
        cast_revision=result.cast_revision,
    )