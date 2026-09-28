"""FullApply orchestration service — durable submit/plan/chunk/publish contract (S10-T01C).

Thin service over the S10-T01A repository + S10-T01B planner.  Every write
is fail-closed and every mutation is workspace/project-scoped.  The worker
layer (app/workflow/s10_full_apply_jobs.py) owns the durable execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from sqlalchemy.orm import Session

from app.persistence.s10_full_apply import (
    S10ApplyConflictError,
    S10ApplyNotFoundError,
    S10ApplyOwnershipError,
    S10ApplyParamsError,
    S10ApplyRepository,
    S10ChunkRecord,
    S10PublicationRecord,
    S10RunRecord,
)
from app.services.s10_chunk_plan import ChunkPlanError, plan_full_apply
from app.services.source_locked_timeline import (
    CODE_DUPLICATE_IDENTITY as _CODE_DUPLICATE_IDENTITY,
    CODE_LEGACY_AUTHORITY as _CODE_LEGACY_AUTHORITY,
    CODE_ROLE_UNMAPPED as _CODE_ROLE_UNMAPPED,
    CODE_ROUTE_NOT_EXECUTABLE as _CODE_ROUTE_NOT_EXECUTABLE,
    TimelineAuthorityError as _TimelineAuthorityError,
    derive_region as _derive_region,
    select_occurrence_box as _select_occurrence_box,
    validate_timeline_block as _validate_timeline_block,
)
from app.services.s09_approval import (
    FULL_APPLY_EXECUTABLE_ROUTES,
    ApprovalNotFoundError as _S09ApprovalNotFoundError,
    ApprovalValidationError as _S09ApprovalValidationError,
    S09ApprovalIntegrityError as _S09ApprovalIntegrityError,
    S09ApprovalRepository as _S09ApprovalRepository,
)

# Bounded S10-T02 integration: per-role dispatch (additive, no contract change)
try:
    from app.services.s10_multi_role_apply import (  # noqa: F401
        GROUP_FIXTURE_SPEC as _S10_T02_GROUP_FIXTURE_SPEC,
    )
    from app.services.s10_multi_role_apply import (
        S10MultiRoleService as _S10MultiRoleService,
    )
except ImportError:
    _S10MultiRoleService: Any = None  # type: ignore[no-redef]
    _S10_T02_GROUP_FIXTURE_SPEC: Any = None  # type: ignore[no-redef]

# Bounded S10-T03 integration: recompute closure (additive, no model change)
try:
    from app.services.s10_recompute import S10RecomputeService as _S10RecomputeService  # noqa: F401
    from app.services.s10_recompute import (
        compute_affected_closure as _compute_affected_closure,  # noqa: F401
    )
except ImportError:
    _S10RecomputeService: Any = None  # type: ignore[no-redef]
    _compute_affected_closure: Any = None  # type: ignore[no-redef]

# Bounded S10-T04A integration: structural compare gate (additive, no model change)
try:
    from app.services.s10_structural_compare import (  # noqa: F401
        S10StructuralCompareService as _S10StructuralCompareService,
    )
except ImportError:
    _S10StructuralCompareService: Any = None  # type: ignore[no-redef]

__all__ = [
    "FullApplyServiceError",
    "FullApplyService",
    "full_apply_natural_key",
    "full_apply_idempotency_key",
]


class FullApplyServiceError(ValueError):
    """Validation/service error (fail-closed, mapped to 4xx)."""


def _hex16(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_non_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise FullApplyServiceError(f"non-finite number at {path}")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_non_finite(v, f"{path}[{i}]")


def full_apply_natural_key(
    *,
    checkpoint_id: str,
    checkpoint_hash: str,
    checkpoint_revision: int,
    plan_hash: str,
    chunk_config: dict[str, Any],
) -> str:
    payload = {
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_id": checkpoint_id,
        "checkpoint_revision": checkpoint_revision,
        "chunk_config": chunk_config,
        "plan_hash": plan_hash,
    }
    return "s10_full_apply:" + hashlib.sha256(_canonical(payload).encode()).hexdigest()[:32]


def full_apply_idempotency_key(
    *,
    checkpoint_id: str,
    checkpoint_hash: str,
    checkpoint_revision: int,
    plan_id: str,
    plan_hash: str,
) -> str:
    payload = {
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_id": checkpoint_id,
        "checkpoint_revision": checkpoint_revision,
        "plan_hash": plan_hash,
        "plan_id": plan_id,
    }
    return "s10_full_apply_submit:" + hashlib.sha256(_canonical(payload).encode()).hexdigest()[:32]


def _authority_fingerprint(authority: dict[str, Any]) -> str:
    """Deterministic sha256 over the canonical v2 authority dict.

    The same v2 checkpoint row (same snapshot_json) always produces the same
    fingerprint; any live mutation/tamper changes it, so the job manifest can
    pin it and the worker can re-derive it from the persisted row.
    """
    return hashlib.sha256(_canonical(authority).encode()).hexdigest()


def _segment_region_from_geometry(
    geometry: dict[str, Any] | None,
    src_w: Any = None,
    src_h: Any = None,
) -> list[float] | None:
    """Derive the canonical NORMALIZED affected region ``[x, y, w, h]``.

    Frozen amendment v0.2 (dual-mode, deterministic): Mode A keeps boxes that
    are already normalized ``[0,1]``; Mode B divides pixel-scale boxes by the
    persisted source dims and clips to the physical frame.  Only boxed
    evidence (segmentation/prompt boxes, first entry) is authoritative — a
    missing/ambiguous/tampered box or an unresolvable scale is NEVER guessed;
    returns ``None`` (caller fails closed with a typed code).
    """
    box, _source, code = _select_occurrence_box(geometry)
    if code is not None or box is None:
        return None
    try:
        region, _mode = _derive_region(box, src_w, src_h)
    except _TimelineAuthorityError:
        return None
    return region


def _canonical_planner_inputs(
    authority: dict[str, Any],
    *,
    checkpoint_id: str,
    checkpoint_hash: str,
    checkpoint_revision: int,
) -> dict[str, Any]:
    """Build planner inputs EXCLUSIVELY from the canonical v2 authority.

    The client never supplies scene/shot/range/route/mapping/region/pack:
    everything the deterministic planner needs is derived here from the frozen
    ``full_apply_authority`` block.  Unsupported routes fail closed (never
    downgraded); missing boxed region fails closed (never guessed).
    """
    identity = authority.get("identity") or {}
    source = authority.get("source")
    sl = authority.get("structural_lock") or {}
    timeline = authority.get("timeline")
    role_mappings = authority.get("role_mappings") or []
    eligibility = authority.get("eligibility") or {}

    if not isinstance(source, dict) or not source.get("source_artifact_id"):
        raise FullApplyServiceError(
            "v2 authority has no frozen source artifact (incomplete authority)"
        )
    if not sl.get("manifest_hash") or not sl.get("policy_version"):
        raise FullApplyServiceError(
            "v2 authority has no frozen structural lock pins (incomplete authority)"
        )
    frame_count = source.get("frame_count")
    if not isinstance(frame_count, int) or frame_count < 1:
        raise FullApplyServiceError(
            "v2 authority has no frozen frame_count (incomplete authority)"
        )

    # Eligibility gate: authority must be executable for full apply.
    if not eligibility.get("full_apply_executable"):
        reasons = list(eligibility.get("reasons") or [])
        raise FullApplyServiceError(
            "v2 authority not executable for full apply: " + ("; ".join(reasons) if reasons else "no reason")
        )

    # Legacy classification (CONTRACT §5 / ruling Q7): a v2 authority without
    # the frozen timeline block predates the bridge representation and
    # requires a public reapproval.  Stored bytes/hashes are never touched,
    # backfilled or silently reinterpreted.
    if not isinstance(timeline, dict):
        raise FullApplyServiceError(
            f"{_CODE_LEGACY_AUTHORITY}: v2 authority predates the frozen "
            "timeline block; public reapproval is required (legacy rows are "
            "never backfilled or reinterpreted)"
        )
    try:
        _validate_timeline_block(timeline, frame_count=frame_count)
    except _TimelineAuthorityError as err:
        raise FullApplyServiceError(f"corrupted timeline authority: {err}") from err

    by_role: dict[str, dict[str, Any]] = {}
    for rm in role_mappings:
        if isinstance(rm, dict) and rm.get("object_role_id"):
            by_role[str(rm["object_role_id"])] = rm

    # Scene shots = the disjoint contiguous temporal partition (CONTRACT §2);
    # validated above by the shared timeline validator.
    shots: list[dict[str, Any]] = []
    for shot in timeline.get("shots") or []:
        shot_id = shot.get("shot_id")
        start = shot.get("start_frame")
        end = shot.get("end_frame")
        if (
            not isinstance(shot_id, str)
            or not shot_id
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            raise FullApplyServiceError(
                "timeline shot entry is malformed (corrupted authority)"
            )
        shots.append({"shot_id": shot_id, "start_frame": start, "end_frame": end})

    # Occurrence intervals = active layers inside the partition (§3).  Only
    # visible/occluded occurrences render (ruling Q3); each keeps its own
    # occurrence-scoped layer_id — repeated roles are never deduplicated.
    mappings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for occ in timeline.get("occurrences") or []:
        if not isinstance(occ, dict):
            raise FullApplyServiceError("timeline occurrence must be a dict (corrupted authority)")
        layer_id = occ.get("layer_id")
        if not isinstance(layer_id, str) or not layer_id:
            raise FullApplyServiceError(
                "timeline occurrence missing layer_id (corrupted authority)"
            )
        if layer_id in seen:
            raise FullApplyServiceError(
                f"{_CODE_DUPLICATE_IDENTITY}: occurrence {layer_id!r} appears twice (tampered)"
            )
        seen.add(layer_id)
        visibility = occ.get("visibility")
        if visibility not in ("visible", "occluded"):
            # represented in the authority, no chunks / no pixels (Q3)
            continue
        route = occ.get("route")
        if not isinstance(route, str) or route not in FULL_APPLY_EXECUTABLE_ROUTES:
            raise FullApplyServiceError(
                f"{_CODE_ROUTE_NOT_EXECUTABLE}: occurrence {layer_id!r} route "
                f"{route!r} not executable by full apply — no downgrade (fail closed)"
            )
        region = occ.get("affected_region")
        if not (isinstance(region, (list, tuple)) and len(region) == 4):
            raise FullApplyServiceError(
                f"PLAN_INPUT_GEOMETRY_MISSING: occurrence {layer_id!r} has no "
                "derived boxed region — region cannot be derived (fail closed)"
            )
        role_id = occ.get("role_id")
        rm = by_role.get(str(role_id)) if role_id is not None else None
        if rm is None:
            raise FullApplyServiceError(
                f"{_CODE_ROLE_UNMAPPED}: occurrence {layer_id!r} has no frozen "
                "role mapping (incomplete authority)"
            )
        pack_version_id = rm.get("pack_version_id")
        if not isinstance(pack_version_id, str) or not pack_version_id:
            raise FullApplyServiceError(
                f"occurrence {layer_id!r} role mapping has no frozen "
                "pack_version_id (incomplete authority)"
            )
        start = occ.get("start_frame")
        end = occ.get("end_frame")
        if not isinstance(start, int) or not isinstance(end, int):
            raise FullApplyServiceError(
                f"occurrence {layer_id!r} has invalid frame range (tampered)"
            )
        mappings.append(
            {
                "layer_id": layer_id,
                "role_id": str(role_id),
                "route": route,
                "affected_region": [float(v) for v in region],
                "pack_version_id": pack_version_id,
                "deps": [],
                "start_frame": start,
                "end_frame": end,
                "z_order": int(occ.get("z_order") or 0),
                "logical_id": str(occ.get("logical_id") or layer_id),
                "lineage_version": int(occ.get("lineage_version") or 1),
                "visibility": str(visibility),
            }
        )

    if not mappings:
        raise FullApplyServiceError(
            "v2 authority has zero render-active occurrences (incomplete authority)"
        )

    # Deterministic order: shots by start_frame, mappings by layer_id.
    shots.sort(key=lambda s: (s["start_frame"], s["shot_id"]))
    mappings.sort(key=lambda m: m["layer_id"])

    return {
        "approved_checkpoint": {
            "checkpoint_id": checkpoint_id,
            "checkpoint_hash": checkpoint_hash,
            "revision": checkpoint_revision,
        },
        "structural_lock_manifest": {
            "manifest_hash": sl["manifest_hash"],
            "policy_version": sl["policy_version"],
            "source_generation": identity.get("source_generation") or "",
            "frame_count": frame_count,
        },
        "scene_manifest": {"shots": shots},
        "mapping": {"mappings": mappings},
        "compatibility_policy": {"policy_version": sl["policy_version"]},
    }


def _legacy_aliases(
    authority: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Bounded legacy id-alias maps for the client-copy canonical-compare.

    The pre-bridge server canonical used segment-as-shot / role-as-layer ids.
    Clients that echo that legacy shape remain accepted ONLY through this
    deterministic, unambiguous alias mapping:

    - ``occurrence -> scene``: a legacy "shot id" that is really an occurrence
      id of the same video resolves to that occurrence's frozen scene;
    - ``role -> occurrence`` ONLY when the role owns exactly ONE occurrence
      (repeated roles are ambiguous → no alias → fail closed);
    - the set of frozen scene ids for direct new-shape copies.

    The alias NEVER alters the plan — the plan is always rebuilt from the
    canonical inputs; this only keeps legacy client validation available
    during the transition.
    """
    timeline = authority.get("timeline") or {}
    shots = timeline.get("shots") or []
    occurrences = timeline.get("occurrences") or []
    scene_ids = {
        str(s.get("shot_id"))
        for s in shots
        if isinstance(s, dict) and s.get("shot_id")
    }
    occ_to_scene: dict[str, str] = {}
    role_occ: dict[str, list[str]] = {}
    for occ in occurrences:
        if not isinstance(occ, dict):
            continue
        layer_id = occ.get("layer_id")
        scene_id = occ.get("scene_id")
        role_id = occ.get("role_id")
        if isinstance(layer_id, str) and isinstance(scene_id, str) and scene_id:
            occ_to_scene[layer_id] = scene_id
        if isinstance(layer_id, str) and isinstance(role_id, str) and role_id:
            role_occ.setdefault(role_id, []).append(layer_id)
    role_to_occ = {role: ids[0] for role, ids in role_occ.items() if len(ids) == 1}
    return occ_to_scene, role_to_occ, scene_ids


def _canonical_compare_legacy(
    canonical: dict[str, Any],
    *,
    authority: dict[str, Any],
    approved_checkpoint: Any,
    structural_lock_manifest: Any,
    scene_manifest: Any,
    mapping: Any,
    compatibility_policy: Any,
) -> None:
    """Fail-closed canonical-compare of optional legacy client authority.

    When a legacy client sends copies of the authority objects, every supplied
    field MUST equal the server-derived canonical value (after the bounded
    legacy id-alias of :func:`_legacy_aliases` for shot/layer identity only).
    Mismatch anywhere in manifest/scene/shot/range/route/mapping/region/pack/
    source/policy raises BEFORE any run/job/publication is created.  Client
    authority is never preferred or merged.
    """
    if approved_checkpoint is not None:
        if not isinstance(approved_checkpoint, dict):
            raise FullApplyServiceError("approved_checkpoint must be a dict when provided")
        c = canonical["approved_checkpoint"]
        for key in ("checkpoint_id", "checkpoint_hash", "revision"):
            if key in approved_checkpoint and approved_checkpoint[key] != c[key]:
                raise FullApplyServiceError(
                    f"approved_checkpoint.{key} mismatch vs server v2 authority "
                    f"(client {approved_checkpoint[key]!r} != server {c[key]!r})"
                )
    if structural_lock_manifest is not None:
        if not isinstance(structural_lock_manifest, dict):
            raise FullApplyServiceError("structural_lock_manifest must be a dict when provided")
        c = canonical["structural_lock_manifest"]
        for key in ("manifest_hash", "policy_version", "source_generation", "frame_count"):
            if key in structural_lock_manifest and structural_lock_manifest[key] != c[key]:
                raise FullApplyServiceError(
                    f"structural_lock_manifest.{key} mismatch vs server v2 authority "
                    f"(client {structural_lock_manifest[key]!r} != server {c[key]!r})"
                )
    occ_to_scene, role_to_occ, scene_ids = _legacy_aliases(authority)
    if scene_manifest is not None:
        client_shots = _normalize_client_shots(scene_manifest)
        aliased_shots: list[dict[str, Any]] = []
        for shot in client_shots:
            shot_id = str(shot["shot_id"])
            if shot_id not in scene_ids and shot_id in occ_to_scene:
                shot_id = occ_to_scene[shot_id]
            aliased_shots.append(
                {
                    "shot_id": shot_id,
                    "start_frame": shot["start_frame"],
                    "end_frame": shot["end_frame"],
                }
            )
        aliased_shots.sort(key=lambda s: (s["start_frame"], s["shot_id"]))
        if aliased_shots != canonical["scene_manifest"]["shots"]:
            raise FullApplyServiceError(
                "scene_manifest shots mismatch vs server v2 authority (client scene cannot alter plan)"
            )
    if mapping is not None:
        client_mappings = _normalize_client_mappings(mapping)
        occ_ids = set(occ_to_scene.keys())
        aliased_mappings: list[dict[str, Any]] = []
        for entry in client_mappings:
            layer_id = str(entry["layer_id"])
            if layer_id not in occ_ids and layer_id in role_to_occ:
                layer_id = role_to_occ[layer_id]
            aliased_mappings.append({**entry, "layer_id": layer_id})
        aliased_mappings.sort(key=lambda m: m["layer_id"])
        canonical_legacy = [
            {
                "layer_id": m["layer_id"],
                "role_id": m["role_id"],
                "route": m["route"],
                "affected_region": m["affected_region"],
                "pack_version_id": m["pack_version_id"],
                "deps": list(m.get("deps", [])),
            }
            for m in canonical["mapping"]["mappings"]
        ]
        if aliased_mappings != canonical_legacy:
            raise FullApplyServiceError(
                "mapping mismatch vs server v2 authority (client mapping cannot alter plan)"
            )
    if compatibility_policy is not None:
        if not isinstance(compatibility_policy, dict):
            raise FullApplyServiceError("compatibility_policy must be a dict when provided")
        cp = compatibility_policy.get("policy_version") or compatibility_policy.get("compatibility_policy_version")
        if cp is not None and cp != canonical["compatibility_policy"]["policy_version"]:
            raise FullApplyServiceError(
                f"compatibility_policy.policy_version mismatch vs server v2 authority "
                f"(client {cp!r} != server {canonical['compatibility_policy']['policy_version']!r})"
            )


def _normalize_client_shots(scene_manifest: Any) -> list[dict[str, Any]]:
    """Deterministic client shots for canonical-compare (fail closed on junk)."""
    shots: list[dict[str, Any]] = []
    if isinstance(scene_manifest, dict):
        raw = scene_manifest.get("shots") or scene_manifest.get("scenes")
    elif isinstance(scene_manifest, list):
        raw = scene_manifest
    else:
        raise FullApplyServiceError("scene_manifest must be dict or list when provided")
    if not isinstance(raw, list) or not raw:
        raise FullApplyServiceError("scene_manifest shots must be a non-empty list when provided")
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise FullApplyServiceError(f"scene_manifest shot[{i}] must be a dict")
        sid = s.get("shot_id")
        start = s.get("start_frame")
        end = s.get("end_frame")
        if not isinstance(sid, str) or not sid or not isinstance(start, int) or not isinstance(end, int):
            raise FullApplyServiceError(f"scene_manifest shot[{i}] missing shot_id/start_frame/end_frame")
        shots.append({"shot_id": sid, "start_frame": start, "end_frame": end})
    shots.sort(key=lambda s: (s["start_frame"], s["shot_id"]))
    return shots


def _normalize_client_mappings(mapping: Any) -> list[dict[str, Any]]:
    """Deterministic client mappings for canonical-compare (fail closed on junk)."""
    raw: Any = []
    if isinstance(mapping, dict):
        raw = mapping.get("mappings") or mapping.get("layers")
    elif isinstance(mapping, list):
        raw = mapping
    else:
        raise FullApplyServiceError("mapping must be dict or list when provided")
    if not isinstance(raw, list) or not raw:
        raise FullApplyServiceError("mapping entries must be a non-empty list when provided")
    out: list[dict[str, Any]] = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise FullApplyServiceError(f"mapping[{i}] must be a dict")
        layer_id = m.get("layer_id") or m.get("role_id")
        route = m.get("route")
        region = m.get("affected_region")
        pack_version_id = m.get("pack_version_id")
        if not isinstance(layer_id, str) or not layer_id or not isinstance(route, str) or not route:
            raise FullApplyServiceError(f"mapping[{i}] missing layer_id/route")
        role_id_field = m.get("role_id")
        if not isinstance(role_id_field, str) or not role_id_field:
            role_id_field = layer_id
        region_norm: list[float] | None = None
        if isinstance(region, (list, tuple)) and len(region) >= 4:
            try:
                region_norm = [float(v) for v in region[:4]]
            except (TypeError, ValueError):
                raise FullApplyServiceError(f"mapping[{i}] affected_region must be numeric")
        out.append(
            {
                "layer_id": layer_id,
                "role_id": role_id_field,
                "route": route,
                "affected_region": region_norm,
                "pack_version_id": pack_version_id if isinstance(pack_version_id, str) else None,
                "deps": [],
            }
        )
    out.sort(key=lambda m: m["layer_id"])
    return out


class FullApplyService:
    """Thin orchestration over S10ApplyRepository + deterministic planner."""


    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = S10ApplyRepository(session)

    # ── Submit (HTTP entry — fast, synchronous DB only) ───────────────────

    def submit(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        apply_checkpoint_id: str,
        expected_checkpoint_hash: str,
        expected_checkpoint_revision: int,
        approved_checkpoint: dict[str, Any] | None = None,
        structural_lock_manifest: dict[str, Any] | None = None,
        scene_manifest: dict[str, Any] | list[dict[str, Any]] | None = None,
        mapping: dict[str, Any] | list[dict[str, Any]] | None = None,
        compatibility_policy: dict[str, Any] | None = None,
        chunk_config: dict[str, Any] | None = None,
        execution_backend: dict[str, Any] | None = None,
        chunk_frames: int | None = None,
        overlap_frames: int | None = None,
        fps_num: int | None = None,
        fps_den: int | None = None,
        idempotency_key: str | None = None,
        natural_key: str | None = None,
    ) -> tuple[S10RunRecord, bool, dict[str, Any]]:
        # Client legacy copies (if any) are validated for non-finite numbers,
        # then canonical-compared below — never used as plan authority.
        if approved_checkpoint is not None:
            _reject_non_finite(approved_checkpoint)
        if structural_lock_manifest is not None:
            _reject_non_finite(structural_lock_manifest)
        if scene_manifest is not None:
            _reject_non_finite(dict(scene_manifest) if isinstance(scene_manifest, dict) else list(scene_manifest))
        if mapping is not None:
            _reject_non_finite(dict(mapping) if isinstance(mapping, dict) else list(mapping))
        if compatibility_policy is not None:
            _reject_non_finite(compatibility_policy)
        if chunk_config is not None:
            _reject_non_finite(chunk_config)

        # MF-END-19.1: the execution-backend manifest is a first-class argument.
        # It rides INSIDE chunk_config so the deterministic planner (the existing
        # S10 authority) validates it, the plan hash binds it and the run row
        # persists it — the worker re-derives it before any render.  A duplicate
        # that disagrees with chunk_config, or a non-object, fails closed here;
        # every other validation happens in the frozen schema via the planner.
        if execution_backend is not None:
            if not isinstance(execution_backend, dict):
                raise FullApplyServiceError("execution_backend must be an object")
            merged = dict(chunk_config or {})
            if "execution_backend" in merged and merged["execution_backend"] != execution_backend:
                raise FullApplyServiceError(
                    "chunk_config.execution_backend conflicts with the execution_backend argument"
                )
            merged["execution_backend"] = execution_backend
            _reject_non_finite(merged)
            chunk_config = merged

        # ── Server-side canonical v2 authority (C8) — fail-closed BEFORE planner/enqueue ──
        # Load checkpoint row server-side and verify hash/revision/cross-project.
        ckpt_row_for_binding = self._repo._require_checkpoint(
            apply_checkpoint_id, workspace_id, expected_hash=expected_checkpoint_hash, expected_revision=expected_checkpoint_revision
        )
        if ckpt_row_for_binding.project_id != project_id:
            raise S10ApplyOwnershipError(f"checkpoint project {ckpt_row_for_binding.project_id!r} != run project {project_id!r}")
        # Require s09.approval/v2 — v1 fails closed with REAPPROVAL_REQUIRED
        # (zero mutation); tampered v2 fails closed; missing authority fails closed.
        try:
            authority = _S09ApprovalRepository(self._session).full_apply_authority(
                apply_checkpoint_id, workspace_id
            )
        except _S09ApprovalValidationError as exc:
            raise FullApplyServiceError(str(exc)) from exc
        except (_S09ApprovalIntegrityError, _S09ApprovalNotFoundError) as exc:
            raise FullApplyServiceError(str(exc)) from exc

        # Build planner inputs EXCLUSIVELY from the canonical v2 authority.
        canonical = _canonical_planner_inputs(
            authority,
            checkpoint_id=apply_checkpoint_id,
            checkpoint_hash=expected_checkpoint_hash,
            checkpoint_revision=expected_checkpoint_revision,
        )
        # Optional legacy client copies: canonical-compare every supplied field;
        # mismatch fails closed BEFORE any run/job/publication.
        _canonical_compare_legacy(
            canonical,
            authority=authority,
            approved_checkpoint=approved_checkpoint,
            structural_lock_manifest=structural_lock_manifest,
            scene_manifest=scene_manifest,
            mapping=mapping,
            compatibility_policy=compatibility_policy,
        )

        # Deterministic plan from CANONICAL server inputs only.
        try:
            plan = plan_full_apply(
                canonical["approved_checkpoint"],
                canonical["structural_lock_manifest"],
                canonical["scene_manifest"],
                canonical["mapping"],
                canonical["compatibility_policy"],
                chunk_frames=chunk_frames,
                overlap_frames=overlap_frames,
                chunk_config=chunk_config,
            )
        except ChunkPlanError as exc:
            raise FullApplyServiceError(str(exc)) from exc

        plan_id: str = plan["plan_id"]
        plan_hash: str = plan["plan_hash"]
        frame_count: int = int(plan["frame_count"])
        cfg: dict[str, Any] = dict(plan["chunk_config"])
        # Canonical render authority fingerprint — server-derived, pinned in the
        # job manifest; the worker re-derives it from the persisted v2 row.
        render_authority: dict[str, Any] = {
            "authority_version": str(authority.get("authority_version") or "s09.full-apply-authority/v1"),
            "authority_fingerprint": _authority_fingerprint(authority),
            "approved_checkpoint": canonical["approved_checkpoint"],
            "structural_lock_manifest": canonical["structural_lock_manifest"],
            "scene_manifest": canonical["scene_manifest"],
            "mapping": canonical["mapping"],
            "compatibility_policy": canonical["compatibility_policy"],
            "chunk_config": cfg,
        }

        # Natural lineage key (content-derived) and idempotency key
        computed_natural = full_apply_natural_key(
            checkpoint_id=apply_checkpoint_id,
            checkpoint_hash=expected_checkpoint_hash,
            checkpoint_revision=expected_checkpoint_revision,
            plan_hash=plan_hash,
            chunk_config=cfg,
        )
        computed_idem = full_apply_idempotency_key(
            checkpoint_id=apply_checkpoint_id,
            checkpoint_hash=expected_checkpoint_hash,
            checkpoint_revision=expected_checkpoint_revision,
            plan_id=plan_id,
            plan_hash=plan_hash,
        )
        # Caller-supplied keys must match computed when both present
        if natural_key is not None and natural_key != computed_natural:
            # Natural key mismatch → fail-closed (stale/ambient leakage)
            raise S10ApplyConflictError(
                f"natural_key does not match computed lineage {computed_natural!r}"
            )
        if idempotency_key is not None and idempotency_key != computed_idem:
            # Idempotency key is bound to the SAME tuple; a different tuple
            # under the same client key is a conflict (409).
            # We still validate — the repository does the final dedup.
            pass
        # Use computed lineage as natural_key when caller did not supply one
        use_natural = natural_key if natural_key is not None else computed_natural
        use_idem = idempotency_key if idempotency_key is not None else computed_idem

        rec, created = self._repo.create_run(
            workspace_id,
            project_id,
            video_item_id,
            apply_checkpoint_id,
            expected_checkpoint_hash=expected_checkpoint_hash,
            expected_checkpoint_revision=expected_checkpoint_revision,
            plan_id=plan_id,
            plan_hash=plan_hash,
            frame_count=frame_count,
            chunk_config=cfg,
            fps_num=fps_num,
            fps_den=fps_den,
            idempotency_key=use_idem,
            natural_key=use_natural,
        )
        # Materialize chunks on first creation (deterministic, inside same tx)
        if created:
            self._materialize_chunks(workspace_id, rec.id, plan)
            # Note: commit is the caller's responsibility (API route commits
            # explicitly; tests may use the same transaction).
        plan["render_authority"] = render_authority
        return rec, created, plan

    def _materialize_chunks(
        self, workspace_id: str, run_id: str, plan: dict[str, Any]
    ) -> list[S10ChunkRecord]:
        chunks: list[dict[str, Any]] = list(plan["chunks"])
        out: list[S10ChunkRecord] = []
        # Determine shot order for order_index (stable by plan order)
        for idx, ch in enumerate(chunks):
            layer_id = ch.get("layer_id")
            object_role_id = ch.get("object_role_id")
            content_hash = ch["content_hash_input"]
            natural = f"s10_chunk:{run_id}:{ch['chunk_id']}"
            idem = f"s10_chunk_idem:{run_id}:{ch['chunk_id']}"
            rec, _ = self._repo.create_chunk(
                workspace_id,
                run_id,
                chunk_index=idx,
                order_index=idx,
                shot_id=str(ch["shot_id"]),
                core_start_frame=int(ch["core_start_frame"]),
                core_end_frame=int(ch["core_end_frame"]),
                content_hash=str(content_hash),
                overlap_before=int(ch.get("overlap_before", 0)),
                overlap_after=int(ch.get("overlap_after", 0)),
                layer_id=str(layer_id) if layer_id else None,
                object_role_id=str(object_role_id) if object_role_id else None,
                # DELTA-F1: persist the planner's whole-shot/GROUP membership
                # with the chunk row (absent key => legacy per-layer chunk).
                member_layer_ids=list(ch.get("member_layer_ids") or []) or None,
                attempt=1,
                natural_key=natural,
                idempotency_key=idem,
            )
            out.append(rec)
        return out

    # ── Read/status ────────────────────────────────────────────────────────

    def get_run(self, run_id: str, workspace_id: str) -> S10RunRecord:
        return self._repo.get_run(run_id, workspace_id)

    def list_runs(
        self, workspace_id: str, project_id: str | None = None, limit: int = 100
    ) -> list[S10RunRecord]:
        return self._repo.list_runs(workspace_id, project_id, limit=limit)

    def list_chunks(self, workspace_id: str, run_id: str) -> list[S10ChunkRecord]:
        # Ownership is via run, but we still validate run exists
        self._repo.get_run(run_id, workspace_id)
        return self._repo.list_chunks(workspace_id, run_id)

    def get_chunk(self, chunk_id: str, workspace_id: str) -> S10ChunkRecord:
        return self._repo.get_chunk(chunk_id, workspace_id)

    def get_publication(self, pub_id: str, workspace_id: str) -> S10PublicationRecord:
        return self._repo.get_publication(pub_id, workspace_id)

    def list_publications(self, workspace_id: str, run_id: str) -> list[S10PublicationRecord]:
        self._repo.get_run(run_id, workspace_id)
        return self._repo.list_publications(workspace_id, run_id)

    # ── Lifecycle transitions (project-scoped, exact-process) ──────────────

    def cancel_run(self, run_id: str, workspace_id: str, *, project_id: str | None = None) -> S10RunRecord:
        """Request cancel: pending/running -> cancelled. Terminal stays terminal."""
        from sqlalchemy import select as _select  # noqa: PLC0415

        from app.persistence.models import S10FullApplyRun as _Run  # noqa: PLC0415

        row = self._session.scalar(
            _select(_Run).where(_Run.id == run_id, _Run.workspace_id == workspace_id)
        )
        if row is None:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found")
        if project_id is not None and row.project_id != project_id:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found in project")
        if row.status in ("completed", "failed", "cancelled"):
            return self._repo.get_run(run_id, workspace_id)
        if row.status not in ("pending", "running", "verifying"):
            raise S10ApplyParamsError(f"cannot cancel run in status {row.status!r}")
        row.status = "cancelled"
        self._session.flush()
        return self._repo.get_run(run_id, workspace_id)

    def retry_run(self, run_id: str, workspace_id: str, *, project_id: str | None = None) -> S10RunRecord:
        """Create successor attempt lineage for a terminal run (new row, new attempt)."""
        from sqlalchemy import select as _select  # noqa: PLC0415

        from app.persistence.models import S10FullApplyRun as _Run  # noqa: PLC0415

        src = self._session.scalar(
            _select(_Run).where(_Run.id == run_id, _Run.workspace_id == workspace_id)
        )
        if src is None:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found")
        if project_id is not None and src.project_id != project_id:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found in project")
        if src.status not in ("failed", "cancelled"):
            raise S10ApplyParamsError(f"can only retry a failed/cancelled run, got {src.status!r}")

        # Distinct lineage: new id, incremented attempt, new plan-derived
        # publication must use a new content lineage.  For this T01C slice,
        # retry inherits the same plan/checkpoint tuple but bumps attempt.
        import uuid as _uuid  # noqa: PLC0415

        new_id = str(_uuid.uuid4())
        new_attempt = int(src.attempt) + 1
        # New natural/idempotency derived from (predecessor, attempt)
        retry_natural = f"s10_retry:{src.id}:{new_attempt}"
        retry_idem = f"s10_retry_idem:{src.id}:{new_attempt}"
        row = _Run(
            id=new_id,
            workspace_id=src.workspace_id,
            project_id=src.project_id,
            video_item_id=src.video_item_id,
            apply_checkpoint_id=src.apply_checkpoint_id,
            apply_checkpoint_hash=src.apply_checkpoint_hash,
            apply_checkpoint_revision=src.apply_checkpoint_revision,
            plan_id=src.plan_id,
            plan_hash=src.plan_hash,
            status="pending",
            frame_count=src.frame_count,
            fps_num=src.fps_num,
            fps_den=src.fps_den,
            chunk_config_json=src.chunk_config_json,
            attempt=new_attempt,
            natural_key=retry_natural,
            idempotency_key=retry_idem,
        )
        self._session.add(row)
        self._session.flush()
        # Materialize chunks for the retry lineage as well
        # Reconstruct plan from the stored chunk_config + run identity
        # We need the original plan chunks — re-derive from stored chunks.
        # For T01C the chunk set is deterministic from plan; copying the
        # predecessor's chunk boundaries is sufficient for resume/retry.
        existing_chunks = self._repo.list_chunks(workspace_id, src.id)
        for ch in existing_chunks:
            self._repo.create_chunk(
                workspace_id,
                new_id,
                chunk_index=int(ch.chunk_index),
                order_index=int(ch.order_index),
                shot_id=str(ch.shot_id),
                core_start_frame=int(ch.core_start_frame),
                core_end_frame=int(ch.core_end_frame),
                content_hash=str(ch.content_hash),
                overlap_before=int(ch.overlap_before),
                overlap_after=int(ch.overlap_after),
                layer_id=ch.layer_id,
                object_role_id=ch.object_role_id,
                # DELTA-F1: a retry lineage must carry the same frozen group
                # membership as its predecessor (or the comfy branch fails
                # closed on a member-less successor).
                member_layer_ids=list(ch.member_layer_ids) or None,
                attempt=new_attempt,
                natural_key=f"s10_chunk:{new_id}:{ch.chunk_index}:{new_attempt}",
                idempotency_key=f"s10_chunk_idem:{new_id}:{ch.chunk_index}:{new_attempt}",
            )
        return self._repo.get_run(new_id, workspace_id)

    def resume_run(self, run_id: str, workspace_id: str, *, project_id: str | None = None) -> S10RunRecord:
        """Resume: re-open a running/pending run and ensure next chunk is runnable.

        Resume only reuses verified completed chunks (content-hash match);
        unverified/partial or stale chunks stay pending and will be
        recomputed by the worker outside the request.
        """
        from sqlalchemy import select as _select  # noqa: PLC0415

        from app.persistence.models import S10FullApplyRun as _Run  # noqa: PLC0415

        row = self._session.scalar(
            _select(_Run).where(_Run.id == run_id, _Run.workspace_id == workspace_id)
        )
        if row is None:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found")
        if project_id is not None and row.project_id != project_id:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found in project")
        if row.status == "completed":
            # Completed is terminal — no resume needed, return as-is
            return self._repo.get_run(run_id, workspace_id)
        if row.status == "cancelled":
            raise S10ApplyParamsError("cannot resume a cancelled run; use retry")
        if row.status not in ("pending", "running", "verifying", "failed"):
            raise S10ApplyParamsError(f"cannot resume run in status {row.status!r}")
        # Durable checkpoint is already persisted (chunks table).  A fresh
        # worker will resume from exact unfinished chunks; we just ensure the
        # run is not terminal and stays running/pending.
        if row.status == "failed":
            row.status = "pending"
            self._session.flush()
        return self._repo.get_run(run_id, workspace_id)

    # ── Publications (atomic managed path + sha256) ────────────────────────

    def publish_completed(
        self,
        *,
        workspace_id: str,
        run_id: str,
        content_hash: str,
        frame_count: int,
        frame_metadata: dict[str, Any],
        checkpoint_id: str,
        checkpoint_hash: str,
        checkpoint_revision: int,
        artifact_relative_path: str,
        artifact_sha256: str,
    ) -> S10PublicationRecord:
        """Atomically publish a completed output artifact.

        Writes bytes via ManagedRoot atomic path, creates a ready Artifact
        row, then creates the completed publication.  All inside the caller's
        transaction; commit is explicit at the API boundary.
        """
        _reject_non_finite(frame_metadata)
        if len(artifact_relative_path) == 0:
            raise FullApplyServiceError("artifact_relative_path must be non-empty")
        # Resolve managed root through deps (isolated in tests via patched job_service)

        from app.api import deps as _deps  # noqa: PLC0415

        managed_root = _deps.get_managed_root()
        from app.persistence.artifacts import ManagedRoot as _ManagedRoot  # noqa: F401,PLC0415
        from app.persistence.models import Artifact as _Artifact  # noqa: PLC0415

        # The file at artifact_relative_path is expected to have been written
        # by the worker already (worker owns the bytes).  Here we just verify
        # the published file exists and matches the claimed sha, then record
        # the durable Artifact + Publication.
        abs_path = managed_root / artifact_relative_path
        if not abs_path.is_file():
            raise FullApplyServiceError(f"published file not found: {artifact_relative_path!r}")
        from app.persistence.artifacts import hash_file as _hash_file  # noqa: PLC0415

        actual_sha = _hash_file(abs_path)
        if actual_sha != artifact_sha256.lower():
            raise FullApplyServiceError(
                f"artifact sha mismatch: claimed {artifact_sha256!r} vs file {actual_sha!r}"
            )
        # Artifact row (workspace-scoped, kind video, state ready)
        import uuid as _uuid  # noqa: PLC0415

        artifact_id = str(_uuid.uuid4())
        art_row = _Artifact(
            id=artifact_id,
            workspace_id=workspace_id,
            kind="video",
            relative_path=artifact_relative_path,
            state="ready",
        )
        self._session.add(art_row)
        self._session.flush()
        pub, _ = self._repo.create_publication(
            workspace_id,
            run_id,
            artifact_id,
            content_hash,
            frame_count,
            frame_metadata,
            checkpoint_id,
            checkpoint_hash,
            checkpoint_revision,
            state="completed",
        )
        # Complete it (re-validates .partial/ready)
        pub = self._repo.complete_publication(pub.id, workspace_id)
        return pub
