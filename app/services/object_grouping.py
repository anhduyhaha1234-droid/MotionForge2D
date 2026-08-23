"""Deterministic cross-scene grouping algorithm (S08-T03, correction C1).

A REAL, rule-based algorithm (no mock) that turns the durable role +
occurrence evidence of ONE video item / source generation into reviewable
pairwise grouping suggestions.  Identical inputs ALWAYS produce identical
output (deterministic CI evidence).

**Current-generation policy (correction C1):**
- Group ONLY the roles of the explicit video/source generation the caller
  selects (the repository filters by generation; the natural key embeds it).
- The display name is NEVER identity authority: names are advisory hints at
  most.  A pair is suggested only when EVIDENCE (spatial footprint and
  temporal disjointness of occurrences) supports it, and a same-name pair
  that CO-OCCURS in time with a different footprint is NOT suggested
  (two identical-looking objects seen together are distinct).
- Stable role ids (``role_id``) are the only joins/keys of suggestions and
  operations; renames never change them.

Confidence bands (calibration v2):
- Same name + consistent footprint (IoU >= 0.4) → **0.9**
- Same name + partial overlap (IoU >= 0.15) → **0.65**
- Same name + disjoint footprint + temporally disjoint occurrences → **0.45**
  (advisory: one object moving, or two identical objects — reviewer decides)
- Same name + disjoint footprint + CO-OCCURRING → **no suggestion**
- Different names + matching footprint (IoU >= 0.7) + temporally disjoint →
  **0.6** (appearance evidence despite name difference — ambiguity)
- Different names + matching footprint + CO-OCCURRING → **no suggestion**
- Different names + weak footprint → no suggestion
- Missing occurrence evidence → no suggestion (name alone is never enough)

Every suggestion is ADVISORY: the module never confirms or merges anything.
Provenance: every suggestion carries ``algorithm`` + ``algorithm_version``;
the policy (semantics, review threshold, calibration version) is exposed by
:func:`grouping_policy`.  The service imports nothing from persistence —
the router/repository supply evidence and persist the pairs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "DEFAULT_CALIBRATION_VERSION",
    "DEFAULT_GROUPING_ALGORITHM",
    "DEFAULT_GROUPING_ALGORITHM_VERSION",
    "GroupingPolicy",
    "MIN_SUGGESTION_CONFIDENCE",
    "OccurrenceEvidence",
    "PairSuggestion",
    "RoleEvidence",
    "generate_pair_suggestions",
    "grouping_policy",
    "normalize_name",
]

#: Provenance of the deterministic grouping algorithm.
DEFAULT_GROUPING_ALGORITHM = "role-fingerprint"
DEFAULT_GROUPING_ALGORITHM_VERSION = "1"

#: Noise floor — pairs below this are never suggested.
MIN_SUGGESTION_CONFIDENCE = 0.35

#: Confidence bands (deterministic rules).
_CONF_SAME_NAME_CONSISTENT = 0.9
_CONF_SAME_NAME_PARTIAL = 0.65
_CONF_SAME_NAME_LOW_ADVISORY = 0.45
_CONF_DIFFERENT_NAME_SPATIAL = 0.6

_OVERLAP_CONSISTENT = 0.4
_OVERLAP_PARTIAL = 0.15
_OVERLAP_CROSS_NAME = 0.7

#: Calibration version of the confidence bands above.  BUMP whenever the
#: band semantics change (v1 = T03 bands; v2 = C1 evidence-first bands).
DEFAULT_CALIBRATION_VERSION = "2"

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class OccurrenceEvidence:
    """One scene/frame evidence record used by the algorithm."""

    scene_id: str
    frame_index: int
    time_ms: int
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int


@dataclass(frozen=True)
class RoleEvidence:
    """One active ObjectRole plus its occurrences (for one video/generation)."""

    role_id: str
    name: str
    kind: str
    source_generation: str
    occurrences: tuple[OccurrenceEvidence, ...]


@dataclass(frozen=True)
class PairSuggestion:
    """One deterministic pairwise grouping decision."""

    role_ids: tuple[str, str]
    confidence: float
    reasons: tuple[str, ...]
    algorithm: str
    algorithm_version: str


@dataclass(frozen=True)
class GroupingPolicy:
    """Exposed grouping policy metadata (backend-authoritative)."""

    algorithm: str
    algorithm_version: str
    calibration_version: str
    review_threshold: float
    advisory: bool
    confidence_semantics: tuple[str, ...]
    note: str


def grouping_policy(
    *,
    algorithm: str = DEFAULT_GROUPING_ALGORITHM,
    algorithm_version: str = DEFAULT_GROUPING_ALGORITHM_VERSION,
    calibration_version: str = DEFAULT_CALIBRATION_VERSION,
) -> GroupingPolicy:
    """Backend-authoritative grouping policy metadata.

    The calibration version changes whenever the confidence band semantics
    change, so consumers can detect that suggestion confidences were
    produced under a different calibration.
    """
    return GroupingPolicy(
        algorithm=algorithm,
        algorithm_version=algorithm_version,
        calibration_version=calibration_version,
        review_threshold=MIN_SUGGESTION_CONFIDENCE,
        advisory=True,
        confidence_semantics=(
            "0.90 same-name + consistent spatial footprint (IoU >= 0.4)",
            "0.65 same-name + partial spatial overlap (IoU >= 0.15)",
            "0.45 same-name + disjoint footprint + temporally disjoint evidence",
            "0.60 different-names + matching footprint (IoU >= 0.7) + "
            "temporally disjoint evidence (ambiguity)",
            "pairs that CO-OCCUR in time with a different footprint are NOT "
            "suggested (display name is never identity authority)",
        ),
        note="Grouping results are advisory; they are never auto-confirmed "
        "or auto-merged.  Suggestions and operations reference stable role "
        "ids only.",
    )


def normalize_name(name: str) -> str:
    """Deterministic name fingerprint: lower-case, trimmed, whitespace-folded."""
    return _WS_RE.sub(" ", name.strip().lower())


def _representative(occurrences: tuple[OccurrenceEvidence, ...]) -> OccurrenceEvidence | None:
    """Deterministic representative: the LATEST occurrence (max frame)."""
    if not occurrences:
        return None
    return max(
        occurrences,
        key=lambda o: (o.frame_index, o.scene_id, o.time_ms),
    )


def _bbox_overlap(
    a: OccurrenceEvidence, b: OccurrenceEvidence
) -> float:
    """Intersection-over-union of two bounding boxes (deterministic)."""
    a_x2 = a.bbox_x + a.bbox_w
    a_y2 = a.bbox_y + a.bbox_h
    b_x2 = b.bbox_x + b.bbox_w
    b_y2 = b.bbox_y + b.bbox_h
    inter_w = max(0, min(a_x2, b_x2) - max(a.bbox_x, b.bbox_x))
    inter_h = max(0, min(a_y2, b_y2) - max(a.bbox_y, b.bbox_y))
    inter = inter_w * inter_h
    union = a.bbox_w * a.bbox_h + b.bbox_w * b.bbox_h - inter
    if union <= 0:
        return 0.0
    return inter / union


def _temporal_disjoint(
    a: tuple[OccurrenceEvidence, ...], b: tuple[OccurrenceEvidence, ...]
) -> bool:
    """True when the occurrence time spans of two roles do not intersect."""
    if not a or not b:
        return False
    a_min = min(o.time_ms for o in a)
    a_max = max(o.time_ms for o in a)
    b_min = min(o.time_ms for o in b)
    b_max = max(o.time_ms for o in b)
    return a_max < b_min or b_max < a_min


def _same_name_pair(
    evidence_a: RoleEvidence, evidence_b: RoleEvidence
) -> tuple[float, tuple[str, ...]] | None:
    """Evidence-first decision for two roles sharing a normalized name.

    The name is only a hint.  A suggestion requires evidence: a consistent
    footprint (0.9), a partial overlap (0.65), or a disjoint footprint that
    is temporally DISJOINT (0.45, advisory — one object moving or two
    identical objects).  A disjoint footprint that CO-OCCURS in time means
    two identical objects were visible together: the pair is NOT suggested
    even though the names match.
    """
    rep_a = _representative(evidence_a.occurrences)
    rep_b = _representative(evidence_b.occurrences)
    if rep_a is None or rep_b is None:
        # No occurrence evidence -> the name alone is never authority.
        return None
    overlap = _bbox_overlap(rep_a, rep_b)
    if overlap >= _OVERLAP_CONSISTENT:
        return _CONF_SAME_NAME_CONSISTENT, (
            "same-normalized-name",
            "spatial-footprint-consistent-across-scenes",
        )
    if overlap >= _OVERLAP_PARTIAL:
        return _CONF_SAME_NAME_PARTIAL, (
            "same-normalized-name",
            "spatial-footprint-partial-overlap",
        )
    if _temporal_disjoint(evidence_a.occurrences, evidence_b.occurrences):
        return _CONF_SAME_NAME_LOW_ADVISORY, (
            "same-normalized-name",
            "spatial-footprint-differs-may-be-distinct-objects",
            "occurrences-temporally-disjoint",
        )
    return None


def _different_name_pair(
    evidence_a: RoleEvidence, evidence_b: RoleEvidence
) -> tuple[float, tuple[str, ...]] | None:
    """Ambiguity rule for different names (matching footprint, no co-timing).

    Appearance/track evidence MAY raise a suggestion even when the display
    names differ; co-occurring objects with different names are never
    suggested (they were seen together -> distinct).
    """
    rep_a = _representative(evidence_a.occurrences)
    rep_b = _representative(evidence_b.occurrences)
    if rep_a is None or rep_b is None:
        return None
    if _bbox_overlap(rep_a, rep_b) >= _OVERLAP_CROSS_NAME:
        if _temporal_disjoint(evidence_a.occurrences, evidence_b.occurrences):
            return _CONF_DIFFERENT_NAME_SPATIAL, (
                "spatial-footprint-matches-across-scenes",
                "different-names",
                "occurrences-temporally-disjoint-ambiguity",
            )
        return None
    return None


def _pair_decision(
    evidence_a: RoleEvidence,
    evidence_b: RoleEvidence,
    *,
    removal_only_kinds: frozenset[str],
) -> tuple[float, tuple[str, ...]] | None:
    # S08-A01 role taxonomy guards:
    # - Removal-only kinds (source_overlay) NEVER pair with anything.
    # - Different kinds are NEVER paired (a background never merges with a
    #   character, a graphic never with a prop, a foreground never with a
    #   source overlay, etc.).  Grouping is kind-homogeneous — the merged
    #   target keeps the shared kind.
    if evidence_a.kind in removal_only_kinds or evidence_b.kind in removal_only_kinds:
        return None
    if evidence_a.kind != evidence_b.kind:
        return None
    name_a = normalize_name(evidence_a.name)
    name_b = normalize_name(evidence_b.name)
    if name_a == name_b:
        return _same_name_pair(evidence_a, evidence_b)
    return _different_name_pair(evidence_a, evidence_b)


def generate_pair_suggestions(
    evidence: list[RoleEvidence],
    *,
    removal_only_kinds: frozenset[str],
    algorithm: str = DEFAULT_GROUPING_ALGORITHM,
    algorithm_version: str = DEFAULT_GROUPING_ALGORITHM_VERSION,
) -> list[PairSuggestion]:
    """Deterministic pairwise suggestions over one video's active roles.

    S08-A01: suggestions are KIND-HOMOGENEOUS — different-kind roles are
    never paired and removal-only roles (``source_overlay``) never pair with
    anything (the same backend-owned policy drives the merge guard).  Callers
    MUST pass the canonical ``removal_only_kinds`` (``REMOVAL_ONLY_KINDS``
    from ``app.persistence.models``) — F3 removed the mirrored default so
    there is exactly ONE production authority for the removal-only policy.

    Input order is irrelevant to correctness but the CALLER must pass a stable
    order (the repository orders by created_at/id); pairs are enumerated
    (i<j) on the sorted role id sequence, so output is canonical.
    """
    ordered = sorted(
        (item for item in evidence if item.role_id),
        key=lambda item: item.role_id,
    )
    suggestions: list[PairSuggestion] = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            decision = _pair_decision(
                ordered[i],
                ordered[j],
                removal_only_kinds=removal_only_kinds,
            )
            if decision is None:
                continue
            confidence, reasons = decision
            if confidence < MIN_SUGGESTION_CONFIDENCE:
                continue
            suggestions.append(
                PairSuggestion(
                    role_ids=(
                        ordered[i].role_id,
                        ordered[j].role_id,
                    ),
                    confidence=round(confidence, 3),
                    reasons=reasons,
                    algorithm=algorithm,
                    algorithm_version=algorithm_version,
                )
            )
    return suggestions
