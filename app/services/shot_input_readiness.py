"""Shot input-readiness gate — coverage / contact / pose / camera / reference hashes (MF-END-15.3).

The gate answers ONE binary question before an anchor job (or any GPU video
work) may start for a shot: *are the declared inputs provably complete?*  It
reads the FROZEN shot contract ``app.schemas.shot_reskin`` (the shot plan, its
elements/interactions/source evidence and the reference manifest) and produces
a report with FIVE hard rows:

``coverage``
    every declared person/prop role carries a visible span and a MEASURED
    presence fact on the locked source — a role nobody measured cannot be
    redrawn ("replaced because it was small" is the failure U06 names).
``contact``
    every interaction that carries an object (holds / gives / receives /
    touches / reads / occludes) is in state ``measured``/``confirmed`` and
    names a measured contact/holder/occlusion evidence fact.  A bounding-box
    touch is NOT "holding" until the image was inspected.
``pose``
    each view the SHOT declares as required per role resolves (through the
    caller's published-artifact resolver) to a PUBLISHED artwork artifact —
    never a mask, never an unpublished draft.
``camera``
    at least one camera fact, measured on the LOCKED source artifact, exists;
    an absent camera is UNKNOWN, not "static by default".
``reference_hashes``
    every reference item in the shot's reference manifest resolves to an
    artifact whose sha256 equals the digest the plan declares.

Laws (enforced here, not by convention):

1. A missing/unverifiable input is a FAIL, never a warning — warnings can
   never satisfy a row and can never turn a blocked report into an accepted
   one ("warning không biến thành autoaccept").  ``verdict`` is ``READY`` iff
   every hard row passes; warnings are advisory notes ON TOP of that and are
   never auto-promoted to a pass.
2. The report ACCEPTS nothing by itself: callers must call
   :func:`require_ready` (the anchor job does), so a stored report can never
   be silently read as an approval.
3. Mask-like artifacts are refused as artwork by NAME and by MODE: the
   ``mask`` kind and the single-channel modes (``1`` / ``L`` / ``I;16``)
   are masks, not character designs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.schemas.shot_reskin import (
    ReferenceItem,
    ShotPlan,
    SourceEvidenceFact,
    payload_sha256,
)

__all__ = [
    "CONTACT_RELATIONS",
    "HARD_ROWS",
    "MASK_MODES",
    "ROW_NAMES",
    "SCHEMA_VERSION",
    "ReadinessRefusalCode",
    "ReadinessRow",
    "ReferenceResolution",
    "ShotInputReadinessError",
    "evaluate_shot_input_readiness",
    "is_mask_like_mode",
    "probe_image_mode",
    "require_ready",
]

SCHEMA_VERSION = "mf.shot_input_readiness.report/1"

ROW_COVERAGE = "coverage"
ROW_CONTACT = "contact"
ROW_POSE = "pose"
ROW_CAMERA = "camera"
ROW_REFERENCE_HASHES = "reference_hashes"
#: The five hard rows, in report order.  A row is hard when the gate cannot be
#: READY while it fails; warnings never live here.
ROW_NAMES: tuple[str, ...] = (
    ROW_COVERAGE,
    ROW_CONTACT,
    ROW_POSE,
    ROW_CAMERA,
    ROW_REFERENCE_HASHES,
)
HARD_ROWS = ROW_NAMES

#: Interaction relations that name an object/other role the shot promises.
CONTACT_RELATIONS = frozenset({"holds", "gives", "receives", "touches", "reads", "occludes"})
#: Evidence kinds that PROVE a contact-bearing relation was inspected.
CONTACT_EVIDENCE_KINDS = frozenset({"contact", "holder", "occlusion"})
#: PIL image modes that are masks (single channel / bitmap), never artwork.
MASK_MODES = frozenset({"1", "L", "I;16", "I;16L", "I;16B"})

#: Advisory thresholds — they produce warnings, never passes.
LOW_CONFIDENCE = 0.5
MIN_VISIBLE_FRAMES = 1


class ReadinessRefusalCode(str, Enum):
    """Typed refusal codes — one per condition, never a generic error."""

    READINESS_INPUT_INVALID = "readiness_input_invalid"
    READINESS_BLOCKED = "readiness_blocked"
    REFERENCE_UNRESOLVED = "reference_unresolved"
    REFERENCE_MASK_AS_ARTWORK = "reference_mask_as_artwork"
    REFERENCE_HASH_MISMATCH = "reference_hash_mismatch"
    REFERENCE_NOT_PUBLISHED = "reference_not_published"


class ShotInputReadinessError(Exception):
    """Typed refusal raised by :func:`require_ready`."""

    def __init__(self, code: ReadinessRefusalCode, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.context = context

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail, "context": self.context}


def is_mask_like_mode(mode: str | None) -> bool:
    """True when an image mode is a single-channel mask (never artwork)."""
    return bool(mode) and str(mode) in MASK_MODES


def probe_image_mode(path: str | Path) -> str | None:
    """Read an image file's mode with Pillow; ``None`` when it cannot be read."""
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:  # pragma: no cover - Pillow is a project dependency
        return None
    try:
        with Image.open(path) as img:
            return str(img.mode)
    except Exception:  # noqa: BLE001 - unreadable file is "no mode"
        return None


@dataclass(frozen=True)
class ReferenceResolution:
    """What the caller's resolver found for one reference item."""

    artifact_id: str
    sha256: str | None
    published: bool
    kind: str = "artwork"  #: artwork | mask | other
    mode: str | None = None
    store_relative_path: str | None = None


def resolution_is_mask(resolution: ReferenceResolution) -> bool:
    """A resolution is a mask when it says so or carries a mask image mode."""
    return resolution.kind == "mask" or is_mask_like_mode(resolution.mode)


@dataclass
class ReadinessRow:
    """One hard gate row."""

    row: str
    status: str  #: pass | fail
    detail: str
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "status": self.status,
            "detail": self.detail,
            "evidence": dict(self.evidence or {}),
        }


def _rows_by_name(rows: Sequence[ReadinessRow]) -> dict[str, dict[str, Any]]:
    return {row.row: row.to_dict() for row in rows}


def _facts_for(plan: ShotPlan, facts: Sequence[SourceEvidenceFact]) -> list[SourceEvidenceFact]:
    return [fact for fact in facts if fact.domain == "source"]


def _coverage_row(plan: ShotPlan, facts: Sequence[SourceEvidenceFact]) -> ReadinessRow:
    problems: list[str] = []
    evidence: dict[str, Any] = {}
    declared_roles = [
        element.role for element in plan.elements if element.kind in ("person", "prop")
    ]
    for element in plan.elements:
        if element.kind not in ("person", "prop"):
            continue
        if not element.visible_spans:
            problems.append(f"role {element.role!r} carries no visible span")
            continue
        covered = [
            fact for fact in facts
            if fact.subject_role == element.role and fact.kind == "presence"
            and fact.state in ("measured", "confirmed")
        ]
        evidence[element.role] = {
            "visible_spans": [span.key() for span in element.visible_spans],
            "presence_facts": [fact.evidence_id for fact in covered],
            "occlusion": element.occlusion,
        }
        if not covered:
            problems.append(
                f"role {element.role!r} has no MEASURED presence fact on the source"
            )
    if not declared_roles:
        problems.append("shot declares no person/prop elements to cover")
    detail = "every declared role carries a measured presence fact" if not problems else "; ".join(
        problems
    )
    return ReadinessRow(
        row=ROW_COVERAGE,
        status="fail" if problems else "pass",
        detail=detail,
        evidence=evidence,
    )


def _contact_row(plan: ShotPlan, facts: Sequence[SourceEvidenceFact]) -> ReadinessRow:
    problems: list[str] = []
    evidence: dict[str, Any] = {}
    by_id = {fact.evidence_id: fact for fact in facts}
    for interaction in plan.interactions:
        if interaction.relation not in CONTACT_RELATIONS:
            continue
        label = f"{interaction.subject_role}-{interaction.relation}-{interaction.object_role}"
        facts_named = [by_id[eid] for eid in interaction.evidence_ids if eid in by_id]
        proving = [
            fact for fact in facts_named
            if fact.kind in CONTACT_EVIDENCE_KINDS and fact.state in ("measured", "confirmed")
        ]
        evidence[label] = {
            "state": interaction.state,
            "evidence_ids": list(interaction.evidence_ids),
            "proving_facts": [fact.evidence_id for fact in proving],
        }
        if interaction.state not in ("measured", "confirmed"):
            problems.append(f"{label}: interaction state {interaction.state!r} is not measured")
        if not proving:
            problems.append(
                f"{label}: no measured contact/holder/occlusion fact proves the relation"
            )
    detail = "every contact-bearing interaction is measured with a proving fact" if not problems \
        else "; ".join(problems)
    return ReadinessRow(
        row=ROW_CONTACT,
        status="fail" if problems else "pass",
        detail=detail,
        evidence=evidence,
    )


def _pose_row(
    plan: ShotPlan,
    required_views: Mapping[str, Sequence[str]] | None,
    resolve_reference: Callable[[str, str | None], ReferenceResolution | None] | None,
) -> ReadinessRow:
    problems: list[str] = []
    evidence: dict[str, Any] = {}
    required = dict(required_views or {})
    declared_roles = {element.role for element in plan.elements}
    for role, views in sorted(required.items()):
        if role not in declared_roles:
            problems.append(f"required view declared for undeclared role {role!r}")
            continue
        for view in views:
            if resolve_reference is None:
                problems.append(
                    f"role {role!r} view {view!r}: no resolver was supplied — "
                    "the view cannot be proven and is refused, not assumed"
                )
                continue
            resolution = resolve_reference(role, view)
            if resolution is None:
                problems.append(f"role {role!r} view {view!r}: no published artifact resolved")
                continue
            evidence[f"{role}@{view}"] = {
                "artifact_id": resolution.artifact_id,
                "sha256": resolution.sha256,
                "published": resolution.published,
                "kind": resolution.kind,
                "mode": resolution.mode,
            }
            if resolution_is_mask(resolution):
                problems.append(
                    f"role {role!r} view {view!r}: artifact {resolution.artifact_id!r} is a "
                    "MASK (kind/mode) and can never be a character pose/design"
                )
                continue
            if not resolution.published:
                problems.append(
                    f"role {role!r} view {view!r}: artifact {resolution.artifact_id!r} is not "
                    "published"
                )
    detail = "every required view resolves to a published artwork artifact" if not problems \
        else "; ".join(problems)
    return ReadinessRow(
        row=ROW_POSE,
        status="fail" if problems else "pass",
        detail=detail,
        evidence=evidence,
    )


def _camera_row(plan: ShotPlan, facts: Sequence[SourceEvidenceFact]) -> ReadinessRow:
    measured = [
        fact for fact in facts
        if fact.kind == "camera" and fact.state in ("measured", "confirmed")
    ]
    on_source = [fact for fact in measured if fact.artifact.sha256 == plan.source.sha256]
    domain_errors = [
        fact for fact in measured if fact.artifact.sha256 != plan.source.sha256
    ]
    problems: list[str] = []
    if not on_source and not domain_errors:
        problems.append(
            "no measured camera fact exists on the locked source: the camera is UNKNOWN "
            "(a shot never defaults to a static camera by assumption)"
        )
    if not on_source and domain_errors:
        problems.append(
            "camera facts exist but none is measured on the locked source artifact "
            f"{plan.source.sha256[:16]}… (foreign-domain evidence)"
        )
    detail = "camera measured on the locked source" if not problems else "; ".join(problems)
    return ReadinessRow(
        row=ROW_CAMERA,
        status="fail" if problems else "pass",
        detail=detail,
        evidence={
            "measured_on_source": [fact.evidence_id for fact in on_source],
            "foreign_domain": [fact.evidence_id for fact in domain_errors],
        },
    )


def _reference_items(plan: ShotPlan) -> list[tuple[str, ReferenceItem]]:
    items: list[tuple[str, ReferenceItem]] = []
    for role_set in plan.reference_manifest.roles:
        for item in role_set.items:
            items.append((role_set.role, item))
    for item in plan.reference_manifest.props:
        items.append(("prop", item))
    if plan.reference_manifest.background is not None:
        items.append(("background", plan.reference_manifest.background))
    return items


def _reference_hashes_row(
    plan: ShotPlan,
    resolve_reference: Callable[[str, str | None], ReferenceResolution | None] | None,
) -> ReadinessRow:
    problems: list[str] = []
    evidence: dict[str, Any] = {}
    for role, item in _reference_items(plan):
        label = f"{role}@{item.key}"
        if item.artifact.kind == "mask":
            problems.append(
                f"{label}: the manifest itself declares a MASK artifact "
                f"({item.artifact.artifact_id!r}); a mask is not artwork"
            )
            continue
        if resolve_reference is None:
            problems.append(
                f"{label}: no resolver was supplied — the reference hash cannot be "
                "verified and is refused, not assumed"
            )
            continue
        resolution = resolve_reference(role, item.view)
        if resolution is None:
            problems.append(f"{label}: no published artifact resolved for this reference")
            continue
        evidence[label] = {
            "declared_sha256": item.artifact.sha256,
            "resolved_artifact_id": resolution.artifact_id,
            "resolved_sha256": resolution.sha256,
            "published": resolution.published,
            "kind": resolution.kind,
            "mode": resolution.mode,
        }
        if resolution_is_mask(resolution):
            problems.append(
                f"{label}: artifact {resolution.artifact_id!r} is a MASK (kind/mode) — "
                "refusing source-mask-as-artwork"
            )
            continue
        if not resolution.published:
            problems.append(f"{label}: artifact {resolution.artifact_id!r} is not published")
            continue
        if resolution.sha256 != item.artifact.sha256:
            problems.append(
                f"{label}: resolved artifact digest "
                f"{(resolution.sha256 or 'none')[:16]}… != the digest the plan declares "
                f"{item.artifact.sha256[:16]}…"
            )
    detail = "every reference resolves to a published artifact with a matching digest" \
        if not problems else "; ".join(problems)
    return ReadinessRow(
        row=ROW_REFERENCE_HASHES,
        status="fail" if problems else "pass",
        detail=detail,
        evidence=evidence,
    )


def _warnings_for(plan: ShotPlan, facts: Sequence[SourceEvidenceFact]) -> list[dict[str, Any]]:
    """Advisory notes.  They document risk; they never satisfy a row."""
    warnings: list[dict[str, Any]] = []
    for fact in facts:
        if fact.confidence is not None and fact.confidence < LOW_CONFIDENCE:
            warnings.append({
                "code": "low_confidence_fact",
                "detail": f"evidence {fact.evidence_id} confidence {fact.confidence} "
                          f"< {LOW_CONFIDENCE}",
            })
    for element in plan.elements:
        if element.occlusion in ("occluded", "out_of_frame"):
            warnings.append({
                "code": "partial_element",
                "detail": f"role {element.role!r} occlusion is {element.occlusion!r}: "
                          "the partial policy must be kept (never silently dropped)",
            })
    return warnings


def evaluate_shot_input_readiness(
    plan: ShotPlan,
    *,
    required_views: Mapping[str, Sequence[str]] | None = None,
    resolve_reference: Callable[[str, str | None], ReferenceResolution | None] | None = None,
    source_facts: Sequence[SourceEvidenceFact] | None = None,
) -> dict[str, Any]:
    """Evaluate the five hard rows for one shot plan and return the report dict.

    ``resolve_reference(role, view)`` must return a :class:`ReferenceResolution`
    for the role/view pair (the caller wires it to the published cast
    authority), or ``None`` when nothing resolves.  ``source_facts`` defaults
    to the plan's own ``source_evidence``.
    """
    facts = list(source_facts if source_facts is not None else plan.source_evidence)
    rows = [
        _coverage_row(plan, facts),
        _contact_row(plan, facts),
        _pose_row(plan, required_views, resolve_reference),
        _camera_row(plan, facts),
        _reference_hashes_row(plan, resolve_reference),
    ]
    by_name = _rows_by_name(rows)
    blocking = [row.row for row in rows if row.status != "pass"]
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": plan.project_id,
        "video_id": plan.video_id,
        "unit_id": plan.unit_id,
        "shot_id": plan.shot_id,
        "rows": by_name,
        "row_order": list(ROW_NAMES),
        "verdict": "blocked" if blocking else "ready",
        "blocking_rows": blocking,
        "warnings": _warnings_for(plan, facts),
        "warnings_are_advisory": True,
        "accepted": False,  #: the gate never accepts; the caller's verdict does (law 2)
    }
    report = dict(body)
    report["report_sha256"] = payload_sha256(body)
    return report


def require_ready(report: Mapping[str, Any]) -> None:
    """Fail closed unless the report is a READY report of this schema.

    Raises :class:`ShotInputReadinessError` with ``READINESS_BLOCKED`` naming
    every blocking row — the anchor job calls this before any engine work.
    """
    if not isinstance(report, Mapping) or report.get("schema_version") != SCHEMA_VERSION:
        raise ShotInputReadinessError(
            ReadinessRefusalCode.READINESS_INPUT_INVALID,
            f"not a {SCHEMA_VERSION!r} readiness report",
            got=None if not isinstance(report, Mapping) else report.get("schema_version"),
        )
    if report.get("verdict") != "ready":
        raise ShotInputReadinessError(
            ReadinessRefusalCode.READINESS_BLOCKED,
            "shot input readiness is BLOCKED: " + ", ".join(report.get("blocking_rows") or []),
            blocking_rows=list(report.get("blocking_rows") or []),
            details={
                row: (report.get("rows", {}).get(row) or {}).get("detail")
                for row in (report.get("blocking_rows") or [])
            },
        )
