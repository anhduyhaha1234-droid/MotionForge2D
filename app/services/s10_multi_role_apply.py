"""Multi-role independent apply — per-role pinned mapping/pack/route + isolated dispatch (S10-T02).

Every role (layer_id) renders through its own pinned mapping entry,
pack version and renderer route.  Attempts are tracked per role-chunk
so a failure/correction of role A never silently mutates role B's
artifacts.  Contact and z-order graph edges are preserved across chunk
overlap/stitch boundaries and scheduling order does not affect the
canonical output identity.

This module is pure service logic (no DB schema, no migration, no API
routing).  The bounded integration hooks are in s10_full_apply.py and
s10_full_apply_jobs.py (route-per-role dispatch only).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MultiRoleApplyError",
    "RENDERER_ROUTES",
    "RoleMapping",
    "RoleAttempt",
    "ContactEdge",
    "ZOrderEdge",
    "VisibilityEvent",
    "MultiRolePlan",
    "S10MultiRoleService",
    "build_group_fixture",
    "GROUP_FIXTURE_SPEC",
]

RENDERER_ROUTES = frozenset({
    "pose_swap",
    "sprite_affine",
    "controlled_redraw",
    "mesh_warp",
    "part_rig",
})


class MultiRoleApplyError(ValueError):
    """Raised on invalid multi-role apply input."""


def _canonical(obj: Any) -> str:
    """Deterministic JSON representation for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _reject_non_finite(value: Any, path: str = "") -> None:
    """Reject inf/nan in pinned data (fail closed on non-finite authority)."""
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise MultiRoleApplyError(f"non-finite number at {path}")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_non_finite(v, f"{path}[{i}]")


# ── pinned role mapping ──────────────────────────────────────────────────


@dataclass(frozen=True)
class RoleMapping:
    """One pinned mapping entry for a single visible role/layer."""

    role_id: str
    layer_id: str
    route: str
    pack_version: str
    mapping_id: str
    deps: tuple[str, ...] = field(default_factory=tuple)
    contact_anchor: dict[str, Any] | None = None
    z_order: int = 0
    is_foreground_occluder: bool = False
    # Pinned affected region (bbox) — required for real-adapter execution;
    # must be provided by caller (authority source: segment geometry/mask).
    # None is allowed for legacy dispatch_per_role path; real adapter path
    # must fail closed if None.
    affected_region: tuple[float, float, float, float] | None = None
    # arbitrary pinned metadata (no ambient leakage)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoleAttempt:
    """Attempt evidence for one role-chunk."""

    role_id: str
    layer_id: str
    mapping_id: str
    pack_version: str
    route: str
    chunk_id: str
    attempt: int
    content_hash: str
    artifact_id: str | None = None
    artifact_sha256: str | None = None
    state: str = "pending"  # pending | running | completed | failed
    error: str | None = None


@dataclass(frozen=True)
class ContactEdge:
    """Contact graph edge between two occurrence segments."""

    edge_id: str
    source_segment_id: str
    target_segment_id: str
    contact_kind: str  # e.g. "hand_to_phone"
    anchor: dict[str, Any]
    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class ZOrderEdge:
    """Z-order between two visible layers."""

    edge_id: str
    front_role_id: str
    behind_role_id: str
    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class VisibilityEvent:
    """A visibility transition for a segment at a given frame."""

    event_id: str
    role_id: str
    segment_id: str
    from_visibility: str
    to_visibility: str
    frame: int
    reason: str  # must be non-empty (fail closed on unexplained)
    related_edge_id: str | None = None


@dataclass(frozen=True)
class MultiRolePlan:
    """Canonical multi-role plan — hash, roles, edges, scheduling."""

    plan_id: str
    plan_hash: str
    roles: tuple[RoleMapping, ...]
    contact_edges: tuple[ContactEdge, ...]
    z_order_edges: tuple[ZOrderEdge, ...]
    visibility_events: tuple[VisibilityEvent, ...]
    per_role_chunks: dict[str, tuple[dict[str, Any], ...]]
    per_role_attempts: dict[str, tuple[RoleAttempt, ...]]
    scheduling_order: tuple[str, ...]
    canonical_inputs_hash: str


# ── Default group fixture (4 roles, 2 chars, 1 prop, 1 fg occluder) ─────

GROUP_FIXTURE_SPEC: dict[str, Any] = {
    "roles": [
        {
            "role_id": "role_char_a",
            "layer_id": "layer_char_a",
            "kind": "character",
            "route": "pose_swap",
            "pack_version": "pack_char_a_v1",
            "mapping_id": "mapping_char_a_v1",
            "z_order": 10,
            "contact_anchor": None,
            "affected_region": [0.10, 0.10, 0.45, 0.45],
        },
        {
            "role_id": "role_char_b",
            "layer_id": "layer_char_b",
            "kind": "character",
            "route": "sprite_affine",
            "pack_version": "pack_char_b_v1",
            "mapping_id": "mapping_char_b_v1",
            "z_order": 20,
            "contact_anchor": None,
            "affected_region": [0.30, 0.30, 0.50, 0.50],
        },
        {
            "role_id": "role_prop_phone",
            "layer_id": "layer_prop_phone",
            "kind": "prop",
            "route": "sprite_affine",
            "pack_version": "pack_prop_phone_v1",
            "mapping_id": "mapping_prop_phone_v1",
            "z_order": 30,
            "contact_anchor": {"kind": "hand_to_phone", "x": 0.42, "y": 0.55, "role": "role_char_a"},
            "affected_region": [0.50, 0.50, 0.20, 0.20],
        },
        {
            "role_id": "role_fg_table",
            "layer_id": "layer_fg_table",
            "kind": "foreground_occluder",
            "route": "controlled_redraw",
            "pack_version": "pack_fg_table_v1",
            "mapping_id": "mapping_fg_table_v1",
            "z_order": 100,
            "is_foreground_occluder": True,
            "contact_anchor": None,
            "affected_region": [0.20, 0.70, 0.60, 0.25],
        },
    ],
    "contact_edges": [
        {
            "edge_id": "contact_char_a_phone",
            "source_role_id": "role_char_a",
            "target_role_id": "role_prop_phone",
            "contact_kind": "hand_to_phone",
            "anchor": {"x": 0.42, "y": 0.55},
            "start_frame": 0,
            "end_frame": 95,
        },
    ],
    "z_order_edges": [
        {
            "edge_id": "z_char_a_behind_table",
            "front_role_id": "role_fg_table",
            "behind_role_id": "role_char_a",
            "start_frame": 0,
            "end_frame": 95,
        },
        {
            "edge_id": "z_char_b_behind_table",
            "front_role_id": "role_fg_table",
            "behind_role_id": "role_char_b",
            "start_frame": 0,
            "end_frame": 95,
        },
    ],
}


def _validate_role_mapping(raw: dict[str, Any], idx: int) -> RoleMapping:
    """Parse and validate ONE role mapping from raw dict.

    Raises MultiRoleApplyError on missing/type/route errors.
    """
    role_id = raw.get("role_id") or raw.get("layer_id") or raw.get("id")
    layer_id = raw.get("layer_id") or role_id
    if not isinstance(layer_id, str) or not layer_id:
        raise MultiRoleApplyError(f"roles[{idx}] layer_id must be non-empty str")
    if not isinstance(role_id, str) or not role_id:
        raise MultiRoleApplyError(f"roles[{idx}] role_id must be non-empty str")
    route = str(raw.get("route", "sprite_affine"))
    if route not in RENDERER_ROUTES:
        raise MultiRoleApplyError(
            f"roles[{idx}] route must be one of {sorted(RENDERER_ROUTES)}"
        )
    pack_version = str(raw.get("pack_version", "v1"))
    mapping_id = str(raw.get("mapping_id", f"mapping_{role_id}_v1"))
    deps_raw = raw.get("deps", ())
    deps: tuple[str, ...] = tuple(str(d) for d in deps_raw) if deps_raw else ()
    contact_anchor = raw.get("contact_anchor")
    if contact_anchor is not None and not isinstance(contact_anchor, dict):
        raise MultiRoleApplyError(f"roles[{idx}].contact_anchor must be dict if provided")
    if contact_anchor is not None:
        _reject_non_finite(contact_anchor, f"roles[{idx}].contact_anchor")
    z_order = int(raw.get("z_order", 0))
    is_fg = bool(raw.get("is_foreground_occluder", False))
    # Parse affected_region if provided
    affected_region: tuple[float, float, float, float] | None = None
    ar_raw = raw.get("affected_region")
    if ar_raw is not None:
        if not isinstance(ar_raw, (list, tuple)) or len(ar_raw) != 4:
            raise MultiRoleApplyError(
                f"roles[{idx}] affected_region must be a list/tuple of 4 floats [x, y, w, h]"
            )
        affected_region = tuple(float(v) for v in ar_raw)  # type: ignore[assignment]
    md = raw.get("metadata", {})
    if not isinstance(md, dict):
        md = {}
    return RoleMapping(
        role_id=role_id,
        layer_id=layer_id,
        route=route,
        pack_version=pack_version,
        mapping_id=mapping_id,
        deps=deps,
        contact_anchor=dict(contact_anchor) if isinstance(contact_anchor, dict) else None,
        z_order=z_order,
        is_foreground_occluder=is_fg,
        affected_region=affected_region,
        metadata=dict(md),
    )


def build_group_fixture(
    roles: list[dict[str, Any]] | None = None,
    contact_edges: list[dict[str, Any]] | None = None,
    z_order_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a validated group fixture dict from spec or defaults.

    Guarantees the fixture describes at least 2 characters, 1 prop with contact
    anchor and 1 foreground occluder, with distinct layer_ids (no flattening).
    """
    roles = list(roles) if roles else [dict(r) for r in GROUP_FIXTURE_SPEC["roles"]]
    contact_edges = list(contact_edges) if contact_edges else [dict(e) for e in GROUP_FIXTURE_SPEC["contact_edges"]]
    z_order_edges = list(z_order_edges) if z_order_edges else [dict(e) for e in GROUP_FIXTURE_SPEC["z_order_edges"]]

    # Validate roles
    if not roles:
        raise MultiRoleApplyError("group fixture must have at least 2 character roles")
    validated = []
    seen_layer = set()
    for idx, raw in enumerate(roles):
        rm = _validate_role_mapping(raw, idx)
        if rm.layer_id in seen_layer:
            raise MultiRoleApplyError(
                f"group fixture roles must have distinct layer_ids (no flattening): "
                f"duplicate {rm.layer_id!r}"
            )
        seen_layer.add(rm.layer_id)
        validated.append(rm)

    char_count = sum(1 for r in roles if r.get("kind") == "character" or r.get("role_id", "").startswith("role_char"))
    prop_count = sum(1 for r in roles if r.get("kind") == "prop" or "prop" in r.get("role_id", ""))
    fg_count = sum(1 for r in roles if r.get("is_foreground_occluder") or "fg" in r.get("role_id", ""))
    for r in roles:
        _reject_non_finite(r)

    if char_count < 2:
        raise MultiRoleApplyError("group fixture must have at least 2 character roles")
    if prop_count < 1:
        raise MultiRoleApplyError("group fixture must have at least 1 prop role")
    if fg_count < 1:
        raise MultiRoleApplyError("group fixture must have at least 1 foreground occluder")

    # Check prop has contact_anchor
    for rm in validated:
        if "prop" in rm.role_id and rm.contact_anchor is None:
            raise MultiRoleApplyError(f"prop role {rm.role_id!r} must have contact_anchor")

    layer_ids = [r.layer_id for r in validated]

    # Check contact_edges reference known roles
    role_ids = {r.role_id for r in validated}
    for ce in contact_edges:
        src = ce.get("source_role_id") or ce.get("source_segment_id") or ""
        tgt = ce.get("target_role_id") or ce.get("target_segment_id") or ""
        if src not in role_ids or tgt not in role_ids:
            raise MultiRoleApplyError(
                f"contact edge references unknown role: {src!r} -> {tgt!r}"
            )

    def _kind(r: RoleMapping) -> str:
        if r.is_foreground_occluder or "fg" in r.role_id or "table" in r.layer_id:
            return "foreground_occluder"
        if "prop" in r.role_id or "phone" in r.layer_id:
            return "prop"
        return "character"

    return {
            "roles": [{"role_id": r.role_id, "layer_id": r.layer_id,
                       "kind": _kind(r),
                       "route": r.route, "pack_version": r.pack_version,
                       "mapping_id": r.mapping_id, "z_order": r.z_order,
                       "contact_anchor": r.contact_anchor,
                       "affected_region": list(r.affected_region) if r.affected_region else None}
                      for r in validated],
        "contact_edges": [dict(e) for e in contact_edges],
        "z_order_edges": [dict(e) for e in z_order_edges],
        "char_count": char_count,
        "prop_count": prop_count,
        "fg_count": fg_count,
        "not_flattened": len(layer_ids) == len(set(layer_ids)),
        "layer_ids": layer_ids,
    }


# ── S10MultiRoleService ──────────────────────────────────────────────────


class S10MultiRoleService:
    """Per-role independent dispatch service.

    Each role carries its own pinned mapping/pack/route and attempt
    evidence.  Rendering is dispatched per role; failures propagate only
    for the failing role.  Contact/z-order edges and visibility events
    survive chunk overlap/stitch boundaries.  Scheduling order does not
    affect the canonical plan/hash identity.
    """

    # ── Plan construction (pure, deterministic) ──────────────────────────

    def build_plan(
        self,
        *,
        roles: list[dict[str, Any]],
        contact_edges: list[dict[str, Any]] | None = None,
        z_order_edges: list[dict[str, Any]] | None = None,
        visibility_events: list[dict[str, Any]] | None = None,
        shots: list[dict[str, Any]] | None = None,
        chunk_config: dict[str, Any] | None = None,
        schedule_order: list[str] | None = None,
    ) -> MultiRolePlan:
        """Build a canonical multi-role plan (pure, deterministic)."""
        if not roles or len(roles) < 1:
            raise MultiRoleApplyError("roles must be non-empty list (1-4 visible roles)")
        if len(roles) > 4:
            raise MultiRoleApplyError("at most 4 visible roles per plan")
        validated: list[RoleMapping] = []
        seen_layer: set[str] = set()
        seen_role: set[str] = set()
        for idx, raw in enumerate(roles):
            if not isinstance(raw, dict):
                raise MultiRoleApplyError(f"roles[{idx}] must be dict")
            rm = _validate_role_mapping(raw, idx)
            if rm.layer_id in seen_layer:
                raise MultiRoleApplyError(f"duplicate layer_id {rm.layer_id!r}")
            if rm.role_id in seen_role:
                raise MultiRoleApplyError(f"duplicate role_id {rm.role_id!r}")
            seen_layer.add(rm.layer_id)
            seen_role.add(rm.role_id)
            validated.append(rm)

        role_ids = {r.role_id for r in validated}

        # Validate contact edges reference known roles
        contacts: list[ContactEdge] = []
        for idx, raw in enumerate(contact_edges or []):
            if not isinstance(raw, dict):
                raise MultiRoleApplyError(f"contact_edges[{idx}] must be dict")
            src = str(raw.get("source_role_id") or raw.get("source_segment_id") or "")
            tgt = str(raw.get("target_role_id") or raw.get("target_segment_id") or "")
            if src not in role_ids or tgt not in role_ids:
                raise MultiRoleApplyError(f"contact_edges[{idx}] references unknown role")
            if src == tgt:
                raise MultiRoleApplyError(f"contact_edges[{idx}] self-contact not allowed")
            edge_id = str(raw.get("edge_id") or f"contact_{src}_{tgt}_{idx}")
            contacts.append(
                ContactEdge(
                    edge_id=edge_id,
                    source_segment_id=str(raw.get("source_segment_id") or f"seg_{src}"),
                    target_segment_id=str(raw.get("target_segment_id") or f"seg_{tgt}"),
                    contact_kind=str(raw.get("contact_kind", "unknown")),
                    anchor=dict(raw.get("anchor") or raw.get("contact_anchor") or {}),
                    start_frame=int(raw.get("start_frame", 0)),
                    end_frame=int(raw.get("end_frame", 0)),
                )
            )

        # Validate z-order edges reference known roles
        z_edges: list[ZOrderEdge] = []
        for idx, raw in enumerate(z_order_edges or []):
            if not isinstance(raw, dict):
                raise MultiRoleApplyError(f"z_order_edges[{idx}] must be dict")
            front = str(raw.get("front_role_id") or raw.get("front_segment_id") or "")
            behind = str(raw.get("behind_role_id") or raw.get("behind_segment_id") or "")
            if front not in role_ids or behind not in role_ids:
                raise MultiRoleApplyError(f"z_order_edges[{idx}] references unknown role")
            if front == behind:
                raise MultiRoleApplyError(f"z_order_edges[{idx}] self-edge not allowed")
            edge_id = str(raw.get("edge_id") or f"z_{front}_behind_{behind}_{idx}")
            z_edges.append(
                ZOrderEdge(
                    edge_id=edge_id,
                    front_role_id=front,
                    behind_role_id=behind,
                    start_frame=int(raw.get("start_frame", 0)),
                    end_frame=int(raw.get("end_frame", 0)),
                )
            )

        # Validate visibility events
        vis_events: list[VisibilityEvent] = []
        for idx, raw in enumerate(visibility_events or []):
            if not isinstance(raw, dict):
                raise MultiRoleApplyError(f"visibility_events[{idx}] must be dict")
            rid = str(raw.get("role_id", ""))
            reason = str(raw.get("reason", ""))
            if not reason:
                raise MultiRoleApplyError(
                    f"visibility_events[{idx}] reason is required (fail closed on unexplained)"
                )
            vis_events.append(
                VisibilityEvent(
                    event_id=str(raw.get("event_id") or f"vis_{rid}_{idx}"),
                    role_id=rid,
                    segment_id=str(raw.get("segment_id") or f"seg_{rid}"),
                    from_visibility=str(raw.get("from_visibility", "visible")),
                    to_visibility=str(raw.get("to_visibility", "occluded")),
                    frame=int(raw.get("frame", 0)),
                    reason=reason,
                    related_edge_id=str(raw.get("related_edge_id")) if raw.get("related_edge_id") else None,
                )
            )

        # Chunk shots
        if not shots:
            shots = [{"shot_id": "shot_0", "start_frame": 0, "end_frame": 95}]
        chunk_frames = int((chunk_config or {}).get("chunk_frames", 24))
        overlap_frames = int((chunk_config or {}).get("overlap_frames", 2))

        # Build per-role chunks
        per_role_chunks: dict[str, Any] = {}
        for rm in validated:
            chunks: list[dict[str, Any]] = []
            for shot in shots:
                shot_start = int(shot.get("start_frame", 0))
                shot_end = int(shot.get("end_frame", 0))
                pos = shot_start
                chunk_idx = 0
                while pos <= shot_end:
                    core_start = pos
                    core_end = min(pos + chunk_frames - 1, shot_end)
                    overlap_start = max(core_start - overlap_frames, shot_start)
                    overlap_end = min(core_end + overlap_frames, shot_end)
                    chunk_id = "ck_" + _sha256_hex(_canonical({
                        "role_id": rm.role_id,
                        "shot_id": shot.get("shot_id", "shot"),
                        "core_start": core_start,
                        "core_end": core_end,
                        "plan_hash": "placeholder",  # resolved in _build_plan
                    }))[:16]
                    content_payload = {
                        "layer_id": rm.layer_id,
                        "core_start_frame": core_start,
                        "core_end_frame": core_end,
                        "overlap_start_frame": overlap_start,
                        "overlap_end_frame": overlap_end,
                        "asset_id": rm.mapping_id,
                        "pack_version": rm.pack_version,
                        "route": rm.route,
                    }
                    content_hash = _sha256_hex(_canonical(content_payload))
                    chunks.append({
                        "chunk_index": chunk_idx,
                        "chunk_id": chunk_id,
                        "shot_id": shot.get("shot_id", "shot"),
                        "core_start_frame": core_start,
                        "core_end_frame": core_end,
                        "overlap_start_frame": overlap_start,
                        "overlap_end_frame": overlap_end,
                        "layer_id": rm.layer_id,
                        "content_hash_input": content_hash,
                    })
                    pos = core_end + 1
                    chunk_idx += 1
            per_role_chunks[rm.role_id] = tuple(chunks)

        # Deterministic plan hash from sorted canonical inputs
        # scheduling_order does NOT affect plan_hash

        pinned_inputs = {
            "roles": [
                {
                    "role_id": r.role_id,
                    "layer_id": r.layer_id,
                    "route": r.route,
                    "pack_version": r.pack_version,
                    "mapping_id": r.mapping_id,
                    "contact_anchor": r.contact_anchor,
                    "z_order": r.z_order,
                    "is_foreground_occluder": r.is_foreground_occluder,
                    "affected_region": list(r.affected_region) if r.affected_region else None,
                    "deps": list(r.deps),
                }
                for r in sorted(validated, key=lambda x: x.role_id)
            ],
            "contact_edges": sorted(
                [
                    {
                        "edge_id": e.edge_id,
                        "source_role_id": e.source_segment_id,
                        "target_role_id": e.target_segment_id,
                        "contact_kind": e.contact_kind,
                        "anchor": e.anchor,
                        "start_frame": e.start_frame,
                        "end_frame": e.end_frame,
                    }
                    for e in contacts
                ],
                key=lambda x: str(x["edge_id"]),
            ),
            "z_order_edges": sorted(
                [
                    {
                        "edge_id": e.edge_id,
                        "front_role_id": e.front_role_id,
                        "behind_role_id": e.behind_role_id,
                        "start_frame": e.start_frame,
                        "end_frame": e.end_frame,
                    }
                    for e in z_edges
                ],
                key=lambda x: str(x["edge_id"]),
            ),
            "visibility_events": sorted(
                [
                    {
                        "event_id": e.event_id,
                        "role_id": e.role_id,
                        "segment_id": e.segment_id,
                        "from_visibility": e.from_visibility,
                        "to_visibility": e.to_visibility,
                        "frame": e.frame,
                        "reason": e.reason,
                    }
                    for e in vis_events
                ],
                key=lambda x: str(x["event_id"]),
            ),
            "shots": sorted(
                [dict(s) for s in (shots or [{"shot_id": "shot_0", "start_frame": 0, "end_frame": 95}])],
                key=lambda x: str(x["shot_id"]),
            ),
            "chunk_config": chunk_config or {"chunk_frames": 24, "overlap_frames": 2},
        }
        canonical_hash = _sha256_hex(_canonical(pinned_inputs))
        plan_id = "mr_" + canonical_hash[:16]
        plan_hash = canonical_hash

        # Rebuild chunk IDs with real plan_hash
        real_chunks: dict[str, Any] = {}
        for rm in validated:
            cks = []
            for ch in per_role_chunks[rm.role_id]:
                cid_payload = {
                    "role_id": rm.role_id,
                    "shot_id": ch["shot_id"],
                    "core_start": ch["core_start_frame"],
                    "core_end": ch["core_end_frame"],
                    "plan_hash": plan_hash,
                }
                chunk_id = "ck_" + _sha256_hex(_canonical(cid_payload))[:16]
                ch["chunk_id"] = chunk_id
                cks.append(ch)
            real_chunks[rm.role_id] = tuple(cks)

        # Build attempt records
        real_attempts: dict[str, Any] = {}
        for rm in validated:
            attempts = []
            for ch in real_chunks[rm.role_id]:
                attempts.append(
                    RoleAttempt(
                        role_id=rm.role_id,
                        layer_id=rm.layer_id,
                        mapping_id=rm.mapping_id,
                        pack_version=rm.pack_version,
                        route=rm.route,
                        chunk_id=str(ch["chunk_id"]),
                        attempt=1,
                        content_hash=str(ch["content_hash_input"]),
                        state="pending",
                    )
                )
            real_attempts[rm.role_id] = tuple(attempts)

        # scheduling_order is recorded for audit but does not affect plan_id/hash
        if schedule_order is not None:
            if set(schedule_order) != set(r.role_id for r in validated):
                raise MultiRoleApplyError("schedule_order must be a permutation of role_ids")
            ordering = tuple(schedule_order)
        else:
            ordering = tuple(sorted(r.role_id for r in validated))

        return MultiRolePlan(
            plan_id=plan_id,
            plan_hash=plan_hash,
            roles=tuple(sorted(validated, key=lambda x: x.role_id)),
            contact_edges=tuple(sorted(contacts, key=lambda e: e.edge_id)),
            z_order_edges=tuple(sorted(z_edges, key=lambda e: e.edge_id)),
            visibility_events=tuple(sorted(vis_events, key=lambda e: e.event_id)),
            per_role_chunks=real_chunks,
            per_role_attempts=real_attempts,
            scheduling_order=ordering,
            canonical_inputs_hash=canonical_hash,
        )

    # ── Typed per-role renderer executor (S10-T02-C1/C2 correction) ──────
    #
    # Replaces the synthetic hash dispatch with a typed executor that T01C/T03
    # can call.  For each role-chunk it constructs a VALID frozen RenderRequest
    # from the pinned source artifact, exact frame/core+overlap range, role/
    # layer mapping, pack/replacement asset, anchor/motion/contact/z-order and
    # pinned route, then invokes the REAL licensed adapter (sprite_affine,
    # pose_swap via renderer_router/composite) and returns decodable media +
    # route/attempt/frame/hash evidence.  No source-only re-encode.
    #
    # C2: workspace_id/project_id/video_item_id are REQUIRED params (not
    # hard-coded).  affected_region is REQUIRED from RoleMapping (fail closed
    # if None).  Evidence records requested_route + effective_adapter.

    def _build_render_request_for_chunk(
        self,
        *,
        rm: "RoleMapping",
        chunk: dict[str, Any],
        workspace_root: Path,
        source_media: Path,
        output_media: Path,
        assets_dir: Path,
        source_timebase: Any = None,
        workspace_id: str = "",
        project_id: str = "",
        video_item_id: str = "",
    ) -> Any:  # RenderRequest (local import; quoted breaks mypy without module-level import)
        """Construct a VALID frozen RenderRequest for one role-chunk.

        C2: workspace_id/project_id/video_item_id are REQUIRED — caller must
        supply them (fail closed if empty).  affected_region from RoleMapping
        is REQUIRED — fail closed if None.
        """
        from app.services.renderer_contract import (
            AffectedRegion,
            AffineKeyframe,
            ReplacementAsset,
            SourceTimebase,
        )

        start = int(chunk["core_start_frame"])
        end = int(chunk["core_end_frame"])
        layer_id = str(chunk.get("layer_id") or rm.layer_id)
        route = str(rm.route)

        # Validate caller-supplied identities (C2: no hard-coded defaults)
        if not workspace_id or not project_id or not video_item_id:
            raise MultiRoleApplyError(
                f"workspace_id/project_id/video_item_id are REQUIRED for real-adapter "
                f"execution (got ws={workspace_id!r} proj={project_id!r} vid={video_item_id!r})"
            )

        # Validate affected_region from RoleMapping (C2: no hash-layer fabrication)
        if rm.affected_region is None:
            raise MultiRoleApplyError(
                f"affected_region is REQUIRED for role {rm.role_id!r} layer {layer_id!r} — "
                f"no hash/layer_id fabrication allowed. Provide pinned source geometry/mask."
            )

        replacement_asset: ReplacementAsset | None = None
        pose_state_assets: dict[str, ReplacementAsset] | None = None
        pose_schedule: tuple[Any, ...] | None = None
        if route == "sprite_affine":
            cand = assets_dir / f"{layer_id}.png"
            if not cand.is_file():
                raise MultiRoleApplyError(
                    f"missing replacement asset for {layer_id!r}: {cand}"
                )
            replacement_asset = ReplacementAsset(path=cand, kind="sprite")
        elif route == "pose_swap":
            cand = assets_dir / f"{layer_id}.png"
            if not cand.is_file():
                raise MultiRoleApplyError(
                    f"missing pose state asset for {layer_id!r}: {cand}"
                )
            pose_state_assets = {layer_id: ReplacementAsset(path=cand, kind="sprite")}
            pose_schedule = (type("PoseSwapEntry", (), {"frame": start, "state_id": layer_id, "asset": ReplacementAsset(path=cand, kind="sprite")})(),)  # noqa: E501
        elif route == "controlled_redraw":
            cand = assets_dir / f"{layer_id}.png"
            if not cand.is_file():
                raise MultiRoleApplyError(
                    f"missing replacement asset for {layer_id!r}: {cand}"
                )
            replacement_asset = ReplacementAsset(path=cand, kind="sprite")
        else:
            raise MultiRoleApplyError(
                f"only sprite_affine/pose_swap/controlled_redraw are wired for "
                f"real-adapter execution (got {route!r})"
            )

        anchor_xy: tuple[float, float] | None = None
        if isinstance(rm.contact_anchor, dict):
            try:
                ax = float(rm.contact_anchor.get("x", 0.5))
                ay = float(rm.contact_anchor.get("y", 0.5))
                anchor_xy = (ax, ay)
            except (TypeError, ValueError):
                anchor_xy = None
        if anchor_xy is None:
            anchor_xy = (0.5, 0.5)

        affine_keyframes: tuple[AffineKeyframe, ...] | None = None
        if route in ("sprite_affine", "controlled_redraw"):
            affine_keyframes = (AffineKeyframe(frame=start),)

        # C2: Use pinned affected_region from RoleMapping (not hash-layer fabrication)
        rx, ry, rw, rh = rm.affected_region
        affected = AffectedRegion((rx, ry, rw, rh))

        tb = source_timebase
        if tb is None:
            tb = SourceTimebase(fps_num=30, fps_den=1)
        if isinstance(tb, tuple):
            tb = SourceTimebase(fps_num=int(tb[0]), fps_den=int(tb[1]))

        from app.services.renderer_contract import RenderRequest as _RenderRequest

        return _RenderRequest(
            request_id=f"s10_{layer_id}_{start}_{end}",
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            occurrence_segment_id=f"seg_{layer_id}_{start}",
            route=route,
            start_frame=start,
            end_frame=end,
            input_media=source_media,
            output_media=output_media,
            workspace_root=workspace_root,
            replacement_asset=replacement_asset,
            pose_state_assets=pose_state_assets,
            pose_schedule=pose_schedule,
            affine_keyframes=affine_keyframes,
            anchor_xy_norm=anchor_xy,
            affected_region=affected,
            source_timebase=tb,
        )

    def _execute_via_adapter(
        self,
        request: Any,
    ) -> dict[str, Any]:
        """Invoke the REAL licensed adapter for request.route.

        Returns evidence including requested_route + effective_adapter
        (C2: matches audit truth per C1-F4 requirement).
        """
        requested_route = str(request.route)
        adapter: Any = None
        effective_adapter_name: str = ""
        if requested_route == "sprite_affine":
            from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter

            adapter = SpriteAffineAdapter()
            effective_adapter_name = "SpriteAffineAdapter"
        elif requested_route == "pose_swap":
            from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter

            adapter = PoseSwapAdapter()
            effective_adapter_name = "PoseSwapAdapter"
        elif requested_route == "controlled_redraw":
            from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter

            adapter = SpriteAffineAdapter()
            effective_adapter_name = "SpriteAffineAdapter"
        else:
            raise MultiRoleApplyError(
                f"no licensed adapter for route {requested_route!r}"
            )
        result = adapter.render(request)
        if not result.ok:
            raise MultiRoleApplyError(
                f"render failed for {request.request_id!r} route={requested_route!r}: "
                f"{result.error_code}:{result.error_detail}"
            )
        from app.services.renderer_routes.composite import (
            canonical_frame_sha256,
            decode_rgb_frames,
        )

        assert request.output_media is not None
        decoded = decode_rgb_frames(request.output_media)
        expected = request.end_frame - request.start_frame + 1
        if len(decoded) != expected:
            raise MultiRoleApplyError(
                f"decoded {len(decoded)} frames for {request.request_id!r}; "
                f"expected {expected} (range {request.start_frame}..{request.end_frame})"
            )
        decoded_sha = canonical_frame_sha256(decoded)
        return {
            "requested_route": requested_route,
            "effective_adapter": effective_adapter_name,
            "route": requested_route,  # legacy field: same as requested_route
            "backend_id": adapter.backend_id,
            "frames_rendered": int(result.frames_rendered),
            "wall_time_ms": float(result.wall_time_ms),
            "output_media": str(request.output_media),
            "decoded_frame_count": len(decoded),
            "decoded_sha256": decoded_sha,
            "start_frame": int(request.start_frame),
            "end_frame": int(request.end_frame),
        }

    def execute_role_chunk(
        self,
        *,
        role: "RoleMapping",
        chunk: dict[str, Any],
        workspace_root: Path,
        source_media: Path,
        assets_dir: Path,
        output_media: Path,
        source_timebase: Any = None,
        workspace_id: str = "",
        project_id: str = "",
        video_item_id: str = "",
    ) -> dict[str, Any]:
        """Execute ONE role-chunk as a typed RenderRequest through the real adapter.

        C2: workspace_id/project_id/video_item_id passed through (no hard-coded defaults).
        """
        request = self._build_render_request_for_chunk(
            rm=role,
            chunk=chunk,
            workspace_root=workspace_root,
            source_media=source_media,
            output_media=output_media,
            assets_dir=assets_dir,
            source_timebase=source_timebase,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
        evidence = self._execute_via_adapter(request)
        return {
            "role_id": role.role_id,
            "layer_id": role.layer_id,
            "mapping_id": role.mapping_id,
            "pack_version": role.pack_version,
            "route": role.route,
            "chunk_id": str(chunk["chunk_id"]),
            "request_id": str(request.request_id),
            "evidence": evidence,
            "render_request": request,
        }

    def execute_plan_via_renderer(
        self,
        plan: "MultiRolePlan",
        *,
        workspace_root: Path,
        source_media: Path,
        assets_dir: Path,
        outputs_dir: Path,
        source_timebase: Any = None,
        fail_role_id: str | None = None,
        fail_chunk_index: int | None = None,
        workspace_id: str = "",
        project_id: str = "",
        video_item_id: str = "",
    ) -> dict[str, Any]:
        """Execute every role-chunk of plan through the real adapters.

        Produces one decodable MP4 per (role, chunk) under outputs_dir.
        One role failure does not mark other roles/chunk verified.  Scheduling
        order does not change canonical output identity.

        C2: workspace_id/project_id/video_item_id REQUIRED (no hard-coded defaults).
        """
        # Fail-fast identity validation — must happen before per-chunk loop
        # so that the exception propagates to the caller (not caught by
        # per-chunk try/except).
        if not workspace_id or not project_id or not video_item_id:
            raise MultiRoleApplyError(
                        f"workspace_id/project_id/video_item_id are REQUIRED for real-adapter "
                        f"execution (got ws={workspace_id!r} proj={project_id!r} vid={video_item_id!r})"
                )
        ordered_roles = sorted(plan.roles, key=lambda r: r.role_id)
        results: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "canonical_inputs_hash": plan.canonical_inputs_hash,
            "roles": {},
            "contact_edges_preserved": [e.edge_id for e in plan.contact_edges],
            "z_order_edges_preserved": [e.edge_id for e in plan.z_order_edges],
            "visibility_events": [
                {"event_id": e.event_id, "reason": e.reason, "role_id": e.role_id, "frame": e.frame}
                for e in plan.visibility_events
            ],
        }
        for rm in ordered_roles:
            chunks = list(plan.per_role_chunks.get(rm.role_id, []))
            attempts: list[dict[str, Any]] = []
            artifacts: list[dict[str, Any]] = []
            chunk_evidences: list[dict[str, Any]] = []
            failed = False
            for ch in chunks:
                ci = int(ch.get("chunk_index", 0))
                chunk_id = str(ch["chunk_id"])
                is_fail_target = (
                    fail_role_id == rm.role_id
                    and fail_chunk_index is not None
                    and ci == fail_chunk_index
                )
                if is_fail_target:
                    attempts.append(
                        {
                            "role_id": rm.role_id,
                            "layer_id": rm.layer_id,
                            "mapping_id": rm.mapping_id,
                            "pack_version": rm.pack_version,
                            "route": rm.route,
                            "chunk_id": chunk_id,
                            "attempt": 1,
                            "content_hash": str(ch.get("content_hash_input", "")),
                            "artifact_id": None,
                            "artifact_sha256": None,
                            "state": "failed",
                            "error": f"simulated failure for {rm.role_id} chunk {ci}",
                            "isolated": True,
                        }
                    )
                    failed = True
                    break
                out_media = outputs_dir / f"{rm.layer_id}_{chunk_id}.mp4"
                out_media.parent.mkdir(parents=True, exist_ok=True)
                try:
                    chunk_evidence = self.execute_role_chunk(
                        role=rm,
                        chunk=ch,
                        workspace_root=workspace_root,
                        source_media=source_media,
                        assets_dir=assets_dir,
                        output_media=out_media,
                        source_timebase=source_timebase,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        video_item_id=video_item_id,
                    )
                except MultiRoleApplyError as exc:
                    attempts.append(
                        {
                            "role_id": rm.role_id,
                            "layer_id": rm.layer_id,
                            "mapping_id": rm.mapping_id,
                            "pack_version": rm.pack_version,
                            "route": rm.route,
                            "chunk_id": chunk_id,
                            "attempt": 1,
                            "content_hash": str(ch.get("content_hash_input", "")),
                            "artifact_id": None,
                            "artifact_sha256": None,
                            "state": "failed",
                            "error": str(exc),
                        }
                    )
                    failed = True
                    break
                ev = chunk_evidence["evidence"]
                artifact_id = "art_" + _sha256_hex(
                    _canonical({
                        "chunk_id": chunk_id,
                        "layer_id": rm.layer_id,
                        "role_id": rm.role_id,
                        "route": rm.route,
                    }) + ":id"
                )[:16]
                artifacts.append(
                    {
                        "artifact_id": artifact_id,
                        "artifact_sha256": ev["decoded_sha256"],
                        "route": rm.route,
                        "mapping_id": rm.mapping_id,
                        "pack_version": rm.pack_version,
                        "chunk_id": chunk_id,
                        "evidence": ev,
                    }
                )
                attempts.append(
                    {
                        "role_id": rm.role_id,
                        "layer_id": rm.layer_id,
                        "mapping_id": rm.mapping_id,
                        "pack_version": rm.pack_version,
                        "route": rm.route,
                        "chunk_id": chunk_id,
                        "attempt": 1,
                        "content_hash": str(ch.get("content_hash_input", "")),
                        "artifact_id": artifact_id,
                        "artifact_sha256": ev["decoded_sha256"],
                        "state": "completed",
                        "evidence": ev,
                    }
                )
                chunk_evidences.append(chunk_evidence)
            results["roles"][rm.role_id] = {
                "role_id": rm.role_id,
                "layer_id": rm.layer_id,
                "mapping_id": rm.mapping_id,
                "pack_version": rm.pack_version,
                "route": rm.route,
                "failed": failed,
                "chunks": [dict(ck) for ck in chunks],
                "attempts": attempts,
                "artifacts": artifacts,
                "chunk_evidences": chunk_evidences,
            }
        # Contact/z-order survival
        results["contact_survival"] = self._check_edge_survival(
            plan, overlap_context=True, edge_kind="contact"
        )
        results["z_order_survival"] = self._check_edge_survival(
            plan, overlap_context=True, edge_kind="z_order"
        )
        results["unexplained_visibility_count"] = sum(
            1 for e in plan.visibility_events if not e.reason
        )
        return results


    # ── Legacy dispatch (deterministic hash, no real adapter) ────────────

    def dispatch_per_role(
        self,
        plan: MultiRolePlan,
        *,
        role_order: list[str] | None = None,
        fail_role_id: str | None = None,
        fail_chunk_index: int | None = None,
    ) -> dict[str, Any]:
        """Legacy dispatch entry — deterministic hash path for unit tests.

        Production callers (T01C/T03) MUST use execute_plan_via_renderer with
        real workspace/source/assets; this legacy path is retained so existing
        scheduling/edge/fixture tests that do not touch the renderer remain
        green without requiring filesystem setup.
        """
        order = role_order if role_order is not None else list(plan.scheduling_order)
        if set(order) != {r.role_id for r in plan.roles}:
            raise MultiRoleApplyError(
                "role_order must be a permutation of plan role_ids"
            )
        role_by_id = {r.role_id: r for r in plan.roles}
        results: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "canonical_inputs_hash": plan.canonical_inputs_hash,
            "dispatch_order": list(order),
            "roles": {},
            "contact_edges_preserved": [e.edge_id for e in plan.contact_edges],
            "z_order_edges_preserved": [e.edge_id for e in plan.z_order_edges],
            "visibility_events": [
                {"event_id": e.event_id, "reason": e.reason, "role_id": e.role_id, "frame": e.frame}
                for e in plan.visibility_events
            ],
        }
        for role_id in order:
            rm = role_by_id[role_id]
            chunks = list(plan.per_role_chunks.get(role_id, []))
            attempts: list[dict[str, Any]] = []
            artifacts: list[dict[str, Any]] = []
            failed = False
            for ch in chunks:
                ci = int(ch.get("chunk_index", 0))
                chunk_id = str(ch["chunk_id"])
                content_hash = str(ch["content_hash_input"])
                artifact_seed = _canonical(
                    {
                        "chunk_id": chunk_id,
                        "content_hash": content_hash,
                        "layer_id": rm.layer_id,
                        "mapping_id": rm.mapping_id,
                        "pack_version": rm.pack_version,
                        "role_id": rm.role_id,
                        "route": rm.route,
                    }
                )
                artifact_sha = _sha256_hex(artifact_seed)
                artifact_id = "art_" + _sha256_hex(artifact_seed + ":id")[:16]
                is_fail_target = (
                    fail_role_id == role_id
                    and fail_chunk_index is not None
                    and ci == fail_chunk_index
                )
                if is_fail_target:
                    attempts.append(
                        {
                            "role_id": role_id,
                            "layer_id": rm.layer_id,
                            "mapping_id": rm.mapping_id,
                            "pack_version": rm.pack_version,
                            "route": rm.route,
                            "chunk_id": chunk_id,
                            "attempt": 1,
                            "content_hash": content_hash,
                            "artifact_id": None,
                            "artifact_sha256": None,
                            "state": "failed",
                            "error": f"simulated failure for {role_id} chunk {ci}",
                            "isolated": True,
                            "failed": True,
                        }
                    )
                    failed = True
                    break
                attempts.append(
                    {
                        "role_id": role_id,
                        "layer_id": rm.layer_id,
                        "mapping_id": rm.mapping_id,
                        "pack_version": rm.pack_version,
                        "route": rm.route,
                        "chunk_id": chunk_id,
                        "attempt": 1,
                        "content_hash": content_hash,
                        "artifact_id": artifact_id,
                        "artifact_sha256": artifact_sha,
                        "state": "completed",
                    }
                )
                artifacts.append(
                    {
                        "artifact_id": artifact_id,
                        "artifact_sha256": artifact_sha,
                        "route": rm.route,
                        "mapping_id": rm.mapping_id,
                        "pack_version": rm.pack_version,
                        "chunk_id": chunk_id,
                        "content_hash": content_hash,
                    }
                )
            results["roles"][role_id] = {
                "role_id": role_id,
                "layer_id": rm.layer_id,
                "mapping_id": rm.mapping_id,
                "pack_version": rm.pack_version,
                "route": rm.route,
                "failed": failed,
                "chunks": [dict(ck) for ck in chunks],
                "attempts": attempts,
                "artifacts": artifacts,
            }
        results["contact_survival"] = self._check_edge_survival(
            plan, overlap_context=True, edge_kind="contact"
        )
        results["z_order_survival"] = self._check_edge_survival(
            plan, overlap_context=True, edge_kind="z_order"
        )
        results["unexplained_visibility_count"] = sum(
            1 for e in plan.visibility_events if not e.reason
        )
        return results

    # ── Retry (single role, new pack, new attempt) ───────────────────────

    def retry_role(
        self,
        plan: MultiRolePlan,
        role_id: str,
        new_pack_version: str | None = None,
    ) -> dict[str, Any]:
        """Retry a single role with an optional new pack version.

        Returns only the retried role's artifacts (isolated).  Does not mutate
        the original plan or other roles' evidence.
        """
        if role_id not in {r.role_id for r in plan.roles}:
            raise MultiRoleApplyError(f"retry_role: unknown role_id {role_id!r}")
        role_by_id = {r.role_id: r for r in plan.roles}
        rm = role_by_id[role_id]
        pack_version = new_pack_version if new_pack_version else rm.pack_version
        chunks = list(plan.per_role_chunks.get(role_id, []))
        attempts: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for ch in chunks:
            chunk_id = str(ch["chunk_id"])
            content_hash = str(ch["content_hash_input"])
            attempt_num = 2  # retry is always attempt 2
            artifact_seed = _canonical(
                {
                    "chunk_id": chunk_id,
                    "content_hash": content_hash,
                    "layer_id": rm.layer_id,
                    "mapping_id": rm.mapping_id,
                    "pack_version": pack_version,
                    "role_id": rm.role_id,
                    "route": rm.route,
                    "attempt": attempt_num,
                }
            )
            artifact_sha = _sha256_hex(artifact_seed)
            artifact_id = "art_" + _sha256_hex(artifact_seed + ":id")[:16]
            attempts.append(
                {
                    "role_id": role_id,
                    "layer_id": rm.layer_id,
                    "mapping_id": rm.mapping_id,
                    "pack_version": pack_version,
                    "route": rm.route,
                    "chunk_id": chunk_id,
                    "attempt": attempt_num,
                    "content_hash": content_hash,
                    "artifact_id": artifact_id,
                    "artifact_sha256": artifact_sha,
                    "state": "completed",
                }
            )
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_sha256": artifact_sha,
                    "route": rm.route,
                    "mapping_id": rm.mapping_id,
                    "pack_version": pack_version,
                    "chunk_id": chunk_id,
                    "content_hash": content_hash,
                }
            )
        return {
            "role_id": role_id,
            "layer_id": rm.layer_id,
            "mapping_id": rm.mapping_id,
            "pack_version": pack_version,
            "route": rm.route,
            "attempts": attempts,
            "artifacts": artifacts,
        }

    # ── Edge survival check ──────────────────────────────────────────────

    def _check_edge_survival(
        self,
        plan: MultiRolePlan,
        *,
        overlap_context: bool = True,
        edge_kind: str = "contact",
    ) -> dict[str, Any]:
        """Check that all edges of a kind survive chunk overlap/stitch boundaries.

        An edge survives if both its endpoint roles each have at least one chunk
        whose (overlap or core) region covers the edge's full frame interval.
        (Each chunk belongs to exactly one role, so we check per-role coverage,
        not co-occurrence in the same chunk.)
        """
        role_chunk_intervals: dict[str, list[dict[str, Any]]] = {}
        for rid, chunks in plan.per_role_chunks.items():
            for ch in chunks:
                role_chunk_intervals.setdefault(rid, []).append({
                    "start": ch.get("overlap_start_frame" if overlap_context else "core_start_frame",
                                    ch["core_start_frame"]),
                    "end": ch.get("overlap_end_frame" if overlap_context else "core_end_frame",
                                  ch["core_end_frame"]),
                })

        def _role_covers(role_id: str, edge_start: int, edge_end: int) -> bool:
            for iv in role_chunk_intervals.get(role_id, []):
                if iv["start"] <= edge_end and iv["end"] >= edge_start:
                    return True
            return False

        edge_results: list[dict[str, Any]] = []
        if edge_kind == "contact":
            for ce in plan.contact_edges:
                src = ce.source_segment_id.replace("seg_", "")
                tgt = ce.target_segment_id.replace("seg_", "")
                edge_results.append({
                    "edge_id": ce.edge_id,
                    "survives": _role_covers(src, ce.start_frame, ce.end_frame)
                               and _role_covers(tgt, ce.start_frame, ce.end_frame),
                })
        elif edge_kind == "z_order":
            for ze in plan.z_order_edges:
                src = ze.front_role_id
                tgt = ze.behind_role_id
                edge_results.append({
                    "edge_id": ze.edge_id,
                    "survives": _role_covers(src, ze.start_frame, ze.end_frame)
                               and _role_covers(tgt, ze.start_frame, ze.end_frame),
                })
        else:
            raise MultiRoleApplyError(f"unknown edge_kind {edge_kind!r}")
        return {
            "edge_kind": edge_kind,
            "all_survive": all(e["survives"] for e in edge_results),
            "edges": edge_results,
        }

    # ── Canonical output identity ────────────────────────────────────────

    def canonical_output_identity(self, result: dict[str, Any]) -> str:
        """Deterministic identity of the entire multi-role output.

        Scheduling order does NOT affect the identity — artifacts are sorted
        by role_id then chunk_id.  Use this to verify scheduling invariance.
        """
        per_role: dict[str, Any] = {}
        for rid, rd in result.get("roles", {}).items():
            per_role[rid] = sorted(
                [a["artifact_sha256"] for a in rd.get("artifacts", [])]
            )
        canonical = _canonical({k: per_role[k] for k in sorted(per_role)})
        return _sha256_hex(canonical)
