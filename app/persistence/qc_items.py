"""QCItem repository + internal idempotent lifecycle service (S11-T02B).

EXCLUSIVE owner of the QCItem persistence layer for the whole S11 sprint —
every later task (T03* check runners, T04* review queue, T05* readiness)
IMPORTS this module and never writes to it.

Design (lane-A QC_DOMAIN_CONTRACT §1.3 rules 1/4/5 + §2 #4/#5, Decision A):

1. **Internal idempotent creation** — ``create`` is the ONLY way an item
   enters the system (no public POST anywhere; tests seed through this
   repository).  Idempotency is enforced by a DB-level atomic
   ``INSERT .. ON CONFLICT DO NOTHING`` over the 7-column natural key
   (workspace_id, project_id, video_item_id, layer_ref_type, layer_ref_id,
   reason_code, evidence_window_key) followed by a consistent read — NEVER
   a check-then-insert window, so a true concurrent uniqueness race
   converges deterministically on one row (C4-F1).  A duplicate create
   REUSES the existing row (no silent overwrite).

2. **Terminal-only resolution with fresh recheck evidence** — an item may
   only reach ``resolved``/``dismissed`` through ``recheck_resolved`` /
   ``recheck_dismissed``, which REQUIRE a fresh recheck evidence payload
   (rule 1 — no empty "trust me" transitions).  ``recheck_failed`` returns
   an acknowledged item to ``open`` when the recheck still detects the
   issue (also evidence-bearing).  ``acknowledge`` is the non-terminal
   review acknowledgement.  Terminal states are terminal: no reversal.

3. **Blocker honesty** — a ``blocker`` may never be dismissed (rule 2);
   the repository rejects it BEFORE the DB-level CHECK even runs, and the
   DB CHECK remains the backstop (T02A).

4. **Ownership fail-closed** — reads take an explicit ``workspace_id``;
   an id that does not exist in that workspace is indistinguishable from
   not-found (zero cross-workspace leakage).

5. **DTO boundary** — every method returns the frozen ``QCItemRecord``
   dataclass; ORM rows never leave this module (lane-A §2 #4).

Query surface is read-only: ``get`` / ``list`` with exact filters
(status/severity/category/video_item_id), deterministic ordering
(created_at DESC, id DESC) and bounded paging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.persistence.models import (
    OCCURRENCE_CONFIDENCE_SOURCES,
    QC_ITEM_CATEGORIES,
    QC_ITEM_SEVERITIES,
    QC_ITEM_STATUSES,
    QC_REASON_CODES,
    QCItem,
)

__all__ = [
    "QCItemBlockedDismissalError",
    "QCItemDataError",
    "QCItemEvidenceRequiredError",
    "QCItemInvalidTransitionError",
    "QCItemNotFoundError",
    "QCItemParamsError",
    "QCItemRecord",
    "QCItemRepository",
    "canonical_evidence_json",
]

#: The 7 natural-key columns (must match models.QCItem uq_qc_item_natural_key).
NATURAL_KEY_COLUMNS = (
    "workspace_id",
    "project_id",
    "video_item_id",
    "layer_ref_type",
    "layer_ref_id",
    "reason_code",
    "evidence_window_key",
)

#: Legal lifecycle transitions.  Terminal states (resolved/dismissed) have
#: no outgoing transitions; ``open``/``acknowledged`` may both reach
#: terminal states (each requires fresh recheck evidence).
_ALLOWED_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "open": frozenset({"acknowledged", "resolved", "dismissed"}),
    "acknowledged": frozenset({"open", "resolved", "dismissed"}),
    "resolved": frozenset(),
    "dismissed": frozenset(),
}

#: Transitions that demand fresh recheck evidence in the payload (terminal +
#: recheck-fail back to open).
_EVIDENCE_REQUIRED_TARGETS = frozenset({"resolved", "dismissed", "open"})


class QCItemNotFoundError(Exception):
    """Item does not exist in this workspace (404 semantics, zero leak)."""


class QCItemParamsError(ValueError):
    """Invalid create/filter/transition payload (422 semantics)."""


class QCItemEvidenceRequiredError(QCItemParamsError):
    """A terminal/recheck transition was attempted WITHOUT fresh evidence."""

    def __init__(self, item_id: str, new_status: str) -> None:
        super().__init__(
            f"transition of QCItem {item_id!r} to {new_status!r} requires "
            "fresh recheck evidence in the payload"
        )


class QCItemInvalidTransitionError(Exception):
    """The requested lifecycle transition is not allowed (fail-closed)."""


class QCItemBlockedDismissalError(QCItemParamsError):
    """A severity=blocker item can never be dismissed (lane-A §1.3 rule 2)."""

    def __init__(self, item_id: str) -> None:
        super().__init__(
            f"QCItem {item_id!r} has severity=blocker and cannot be dismissed"
        )


class QCItemDataError(Exception):
    """Stored evidence payload is corrupt and cannot be parsed (fail-closed)."""


@dataclass(frozen=True)
class QCItemRecord:
    """Frozen repository DTO for one QCItem row (never ORM)."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    segment_row_id: str | None
    segment_logical_id: str | None
    layer_ref_type: str
    layer_ref_id: str
    reason_code: str
    evidence_window_key: str
    evidence: dict[str, Any]
    status: str
    severity: str
    category: str
    detector: str
    detector_revision: str
    confidence: float
    confidence_source: str
    checkpoint_ref: str
    revision: int
    created_at: datetime
    updated_at: datetime


def canonical_evidence_json(evidence: Mapping[str, Any]) -> str:
    """Byte-stable serialization of the evidence payload (content-derived).

    Deterministic key order and compact separators so repeated writes of the
    same payload produce identical bytes.
    """
    return json.dumps(
        dict(evidence), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _map_row(row: QCItem) -> QCItemRecord:
    try:
        evidence = json.loads(row.evidence_json)
    except (json.JSONDecodeError, TypeError) as err:
        raise QCItemDataError(
            f"QCItem {row.id!r} has corrupt evidence_json: {err}"
        ) from err
    if not isinstance(evidence, dict):
        raise QCItemDataError(
            f"QCItem {row.id!r} evidence_json is not an object"
        )
    return QCItemRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        segment_row_id=row.segment_row_id,
        segment_logical_id=row.segment_logical_id,
        layer_ref_type=row.layer_ref_type,
        layer_ref_id=row.layer_ref_id,
        reason_code=row.reason_code,
        evidence_window_key=row.evidence_window_key,
        evidence=evidence,
        status=row.status,
        severity=row.severity,
        category=row.category,
        detector=row.detector,
        detector_revision=row.detector_revision,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        checkpoint_ref=row.checkpoint_ref,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class QCItemRepository:
    """Durable QCItem repository + internal lifecycle service.

    All writes go through this class; the HTTP layer (routes) is strictly
    READ-ONLY (Decision A).  A caller owns commit/rollback (route or test)
    — this repository never commits on its own, so partial failures leave
    zero partial rows.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── internal idempotent creation (the ONLY creation path) ──────────────

    def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        layer_ref_type: str,
        layer_ref_id: str,
        reason_code: str,
        evidence_window_key: str,
        evidence: Mapping[str, Any],
        severity: str,
        category: str,
        detector: str,
        detector_revision: str,
        confidence: float,
        confidence_source: str,
        checkpoint_ref: str,
        segment_row_id: str | None = None,
        segment_logical_id: str | None = None,
    ) -> QCItemRecord:
        """Create one QCItem in ``open`` state, idempotently (C4-F1).

        A duplicate 7-column natural key atomically reuses the existing
        row: the same id is returned (zero mutation, no duplicate row).
        """
        self._validate_create(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            layer_ref_type=layer_ref_type,
            layer_ref_id=layer_ref_id,
            reason_code=reason_code,
            evidence_window_key=evidence_window_key,
            evidence=evidence,
            severity=severity,
            category=category,
            detector=detector,
            detector_revision=detector_revision,
            confidence=confidence,
            confidence_source=confidence_source,
            checkpoint_ref=checkpoint_ref,
            segment_row_id=segment_row_id,
            segment_logical_id=segment_logical_id,
        )

        values: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "segment_row_id": segment_row_id,
            "segment_logical_id": segment_logical_id,
            "layer_ref_type": layer_ref_type,
            "layer_ref_id": layer_ref_id,
            "reason_code": reason_code,
            "evidence_window_key": evidence_window_key,
            "evidence_json": canonical_evidence_json(evidence),
            "status": "open",
            "severity": severity,
            "category": category,
            "detector": detector,
            "detector_revision": detector_revision,
            "confidence": confidence,
            "confidence_source": confidence_source,
            "checkpoint_ref": checkpoint_ref,
        }
        # Single atomic statement: unique index arbitrates the race — no
        # check-then-insert window exists in this code path.
        stmt = sqlite_insert(QCItem).values(**values).on_conflict_do_nothing(
            index_elements=list(NATURAL_KEY_COLUMNS)
        )
        self._session.execute(stmt)

        row = self._get_by_natural_key(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            layer_ref_type=layer_ref_type,
            layer_ref_id=layer_ref_id,
            reason_code=reason_code,
            evidence_window_key=evidence_window_key,
        )
        return _map_row(row)

    # ── read surface ────────────────────────────────────────────────────────

    def get(self, item_id: str, workspace_id: str) -> QCItemRecord:
        """Read one item; foreign/unknown ids are indistinguishable (404)."""
        row = self._session.scalar(
            select(QCItem).where(
                QCItem.id == item_id, QCItem.workspace_id == workspace_id
            )
        )
        if row is None:
            raise QCItemNotFoundError(
                f"QCItem {item_id!r} not found in workspace {workspace_id!r}"
            )
        return _map_row(row)

    def list(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        video_item_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QCItemRecord], int]:
        """List items in one workspace with exact filters + bounded paging.

        Deterministic ordering: ``created_at DESC`` then ``id DESC``.
        Returns ``(records, exact_filtered_total)``.
        """
        self._validate_filter("status", status, QC_ITEM_STATUSES)
        self._validate_filter("severity", severity, QC_ITEM_SEVERITIES)
        self._validate_filter("category", category, QC_ITEM_CATEGORIES)

        conditions = [QCItem.workspace_id == workspace_id]
        if project_id is not None:
            conditions.append(QCItem.project_id == project_id)
        if status is not None:
            conditions.append(QCItem.status == status)
        if severity is not None:
            conditions.append(QCItem.severity == severity)
        if category is not None:
            conditions.append(QCItem.category == category)
        if video_item_id is not None:
            conditions.append(QCItem.video_item_id == video_item_id)

        total = int(self._session.scalar(select(func.count()).select_from(QCItem).where(*conditions)) or 0)
        rows = self._session.scalars(
            select(QCItem)
            .where(*conditions)
            .order_by(QCItem.created_at.desc(), QCItem.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [_map_row(row) for row in rows], total

    # ── internal lifecycle transitions (recheck-evidence gated) ─────────────

    def acknowledge(self, item_id: str, workspace_id: str) -> QCItemRecord:
        """Non-terminal review acknowledgement (open -> acknowledged)."""
        return self._transition(item_id, workspace_id, new_status="acknowledged")

    def recheck_resolved(
        self,
        item_id: str,
        workspace_id: str,
        *,
        evidence: Mapping[str, Any] | None,
    ) -> QCItemRecord:
        """Terminal resolve — requires FRESH recheck evidence (rule 1)."""
        return self._transition(
            item_id,
            workspace_id,
            new_status="resolved",
            evidence=evidence,
        )

    def recheck_dismissed(
        self,
        item_id: str,
        workspace_id: str,
        *,
        evidence: Mapping[str, Any] | None,
    ) -> QCItemRecord:
        """Terminal dismiss — requires FRESH recheck evidence (rule 1)."""
        return self._transition(
            item_id,
            workspace_id,
            new_status="dismissed",
            evidence=evidence,
        )

    def recheck_failed(
        self,
        item_id: str,
        workspace_id: str,
        *,
        evidence: Mapping[str, Any] | None,
    ) -> QCItemRecord:
        """Recheck still detects the issue: acknowledged -> open (evidence)."""
        return self._transition(
            item_id,
            workspace_id,
            new_status="open",
            evidence=evidence,
        )

    # ── internals ───────────────────────────────────────────────────────────

    def _get_by_natural_key(self, **key: str) -> QCItem:
        row = self._session.scalar(
            select(QCItem).where(
                *[getattr(QCItem, col) == key[col] for col in NATURAL_KEY_COLUMNS]
            )
        )
        if row is None:  # pragma: no cover - invariant: insert or existing row
            raise QCItemDataError("idempotent insert produced no readable row")
        return row

    def _transition(
        self,
        item_id: str,
        workspace_id: str,
        *,
        new_status: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> QCItemRecord:
        if new_status not in QC_ITEM_STATUSES:
            raise QCItemParamsError(
                f"invalid target status {new_status!r} (allowed: {QC_ITEM_STATUSES})"
            )
        row = self._session.scalar(
            select(QCItem).where(
                QCItem.id == item_id, QCItem.workspace_id == workspace_id
            )
        )
        if row is None:
            raise QCItemNotFoundError(
                f"QCItem {item_id!r} not found in workspace {workspace_id!r}"
            )

        if new_status == row.status:
            raise QCItemInvalidTransitionError(
                f"QCItem {item_id!r} is already {new_status!r} (no-op refused)"
            )
        if new_status not in _ALLOWED_TRANSITIONS[row.status]:
            raise QCItemInvalidTransitionError(
                f"QCItem {item_id!r} cannot transition {row.status!r} -> "
                f"{new_status!r}"
            )

        if new_status in _EVIDENCE_REQUIRED_TARGETS:
            if evidence is None or not isinstance(evidence, Mapping) or len(evidence) == 0:
                raise QCItemEvidenceRequiredError(item_id, new_status)

        if new_status == "dismissed" and row.severity == "blocker":
            raise QCItemBlockedDismissalError(item_id)

        row.status = new_status
        if evidence is not None:
            row.evidence_json = canonical_evidence_json(evidence)
        row.revision += 1
        # Flush now so DB-level CHECKs (e.g. blocker+dismissed backstop,
        # T02A ck_qc_item_blocker_not_dismissed) fire before the caller
        # commits; the caller may rollback on error.
        self._session.flush()
        return _map_row(row)

    @staticmethod
    def _validate_filter(
        name: str, value: str | None, allowed: tuple[str, ...]
    ) -> None:
        if value is not None and value not in allowed:
            raise QCItemParamsError(
                f"invalid {name} filter {value!r} (allowed: {allowed})"
            )

    @staticmethod
    def _require_text(params: dict[str, Any], name: str) -> None:
        value = params.get(name)
        if not isinstance(value, str) or value == "":
            raise QCItemParamsError(f"{name} must be a non-empty string")

    @classmethod
    def _validate_create(cls, **params: Any) -> None:
        for name in (
            "workspace_id",
            "project_id",
            "video_item_id",
            "layer_ref_type",
            "layer_ref_id",
            "reason_code",
            "evidence_window_key",
            "detector",
            "detector_revision",
            "checkpoint_ref",
        ):
            cls._require_text(params, name)

        if params["severity"] not in QC_ITEM_SEVERITIES:
            raise QCItemParamsError(
                f"invalid severity {params['severity']!r} (allowed: {QC_ITEM_SEVERITIES})"
            )
        if params["category"] not in QC_ITEM_CATEGORIES:
            raise QCItemParamsError(
                f"invalid category {params['category']!r} (allowed: {QC_ITEM_CATEGORIES})"
            )
        if params["reason_code"] not in QC_REASON_CODES:
            raise QCItemParamsError(
                f"invalid reason_code {params['reason_code']!r} (allowed: {QC_REASON_CODES})"
            )
        confidence = params["confidence"]
        if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
            raise QCItemParamsError(
                f"invalid confidence {confidence!r} (must be within [0, 1])"
            )
        if params["confidence_source"] not in OCCURRENCE_CONFIDENCE_SOURCES:
            raise QCItemParamsError(
                f"invalid confidence_source {params['confidence_source']!r} "
                f"(allowed: {OCCURRENCE_CONFIDENCE_SOURCES})"
            )

        evidence = params["evidence"]
        if evidence is None or not isinstance(evidence, Mapping) or len(evidence) == 0:
            raise QCItemParamsError("evidence must be a non-empty object")

        seg_row = params.get("segment_row_id")
        seg_logical = params.get("segment_logical_id")
        if (seg_row is None) != (seg_logical is None):
            raise QCItemParamsError(
                "segment_row_id and segment_logical_id must be both set or both NULL"
            )