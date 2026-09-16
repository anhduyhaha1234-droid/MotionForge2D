"""Deterministic shot/layer chunk planner (S10-T01B).

Pure function: plan_full_apply(...) -> canonical plan dict with
plan_id=sha256(canonical_json), chunks with deterministic IDs.

No DB, no IO, no time/process/path leakage. Hash only from pinned inputs.
Fail-closed on malformed / non-monotonic / overlapping manifests.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "RENDERER_ROUTES",
    "ChunkPlanError",
    "plan_full_apply",
]

RENDERER_ROUTES = frozenset(
    {
        "pose_swap",
        "sprite_affine",
        "mesh_warp",
        "part_rig",
        "controlled_redraw",
    }
)


class ChunkPlanError(ValueError):
    """Fail-closed validation error for chunk planning."""


# ── canonical JSON helpers ───────────────────────────────────────────────────


def _canonical_json(obj: Any) -> str:
    """Deterministic JSON: sort_keys, compact separators, no whitespace variance."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ── pinned filtering helpers ─────────────────────────────────────────────────


def _filtered_checkpoint(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ChunkPlanError("approved_checkpoint must be a dict")
    # pinned keys only - ambient keys ignored
    allowed = ("checkpoint_id", "checkpoint_hash", "revision", "source_generation", "video_item_id", "project_id", "workspace_id")
    out: dict[str, Any] = {}
    for k in allowed:
        if k in raw:
            out[k] = raw[k]
    # required
    if "checkpoint_id" not in out or not isinstance(out["checkpoint_id"], str) or not out["checkpoint_id"]:
        raise ChunkPlanError("approved_checkpoint.checkpoint_id is required (non-empty str)")
    if "checkpoint_hash" not in out or not isinstance(out["checkpoint_hash"], str) or len(out["checkpoint_hash"]) != 64:
        raise ChunkPlanError("approved_checkpoint.checkpoint_hash must be 64 hex chars")
    # hex validation
    try:
        bytes.fromhex(out["checkpoint_hash"])
    except ValueError as exc:
        raise ChunkPlanError("approved_checkpoint.checkpoint_hash must be hex") from exc
    if "revision" in out:
        if not isinstance(out["revision"], int) or out["revision"] < 1:
            raise ChunkPlanError("approved_checkpoint.revision must be int >= 1")
    else:
        out["revision"] = 1
    # normalize optional to string if present
    for k in ("source_generation", "video_item_id", "project_id", "workspace_id"):
        if k in out and out[k] is not None and not isinstance(out[k], str):
            raise ChunkPlanError(f"approved_checkpoint.{k} must be str if provided")
    return out


def _filtered_manifest(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ChunkPlanError("structural_lock_manifest must be a dict")
    allowed = ("manifest_hash", "policy_version", "source_generation", "frame_count", "fps_num", "fps_den")
    out: dict[str, Any] = {}
    for k in allowed:
        if k in raw:
            out[k] = raw[k]
    if "manifest_hash" not in out or not isinstance(out["manifest_hash"], str) or len(out["manifest_hash"]) != 64:
        raise ChunkPlanError("structural_lock_manifest.manifest_hash must be 64 hex chars")
    try:
        bytes.fromhex(out["manifest_hash"])
    except ValueError as exc:
        raise ChunkPlanError("structural_lock_manifest.manifest_hash must be hex") from exc
    if "policy_version" not in out or not isinstance(out["policy_version"], str) or not out["policy_version"]:
        raise ChunkPlanError("structural_lock_manifest.policy_version is required (non-empty str)")
    if "source_generation" not in out or not isinstance(out["source_generation"], str) or not out["source_generation"]:
        raise ChunkPlanError("structural_lock_manifest.source_generation is required (non-empty str)")
    if "frame_count" not in out:
        raise ChunkPlanError("structural_lock_manifest.frame_count is required")
    if not isinstance(out["frame_count"], int) or out["frame_count"] < 1:
        raise ChunkPlanError("structural_lock_manifest.frame_count must be int >= 1")
    # fps optional but if present must be int >0
    for k in ("fps_num", "fps_den"):
        if k in out and out[k] is not None and (not isinstance(out[k], int) or out[k] < 1):
            raise ChunkPlanError(f"structural_lock_manifest.{k} must be int >= 1 if provided")
    return out


def _normalize_shots(raw: Any) -> list[dict[str, Any]]:
    # scene_manifest may be dict with shots/scenes or raw list
    shots_raw: Any
    if isinstance(raw, dict):
        if "shots" in raw:
            shots_raw = raw["shots"]
        elif "scenes" in raw:
            shots_raw = raw["scenes"]
        elif "scene_manifest" in raw:
            shots_raw = raw["scene_manifest"]
        else:
            # maybe the dict itself is a shot? but we expect list
            raise ChunkPlanError("scene_manifest must contain shots or scenes list")
    elif isinstance(raw, list):
        shots_raw = raw
    else:
        raise ChunkPlanError("scene_manifest must be dict with shots or list of shots")

    if not isinstance(shots_raw, list) or len(shots_raw) == 0:
        raise ChunkPlanError("scene_manifest shots must be non-empty list")

    normalized: list[dict[str, Any]] = []
    for idx, s in enumerate(shots_raw):
        if not isinstance(s, dict):
            raise ChunkPlanError(f"shot[{idx}] must be dict")
        if "shot_id" not in s or not isinstance(s["shot_id"], str) or not s["shot_id"]:
            raise ChunkPlanError(f"shot[{idx}].shot_id is required (non-empty str)")
        if "start_frame" not in s or "end_frame" not in s:
            raise ChunkPlanError(f"shot[{idx}] must have start_frame and end_frame")
        sf = s["start_frame"]
        ef = s["end_frame"]
        if not isinstance(sf, int) or not isinstance(ef, int):
            raise ChunkPlanError(f"shot[{idx}] start_frame/end_frame must be int")
        if sf < 0 or ef < 0:
            raise ChunkPlanError(f"shot[{idx}] frames must be >= 0")
        if ef < sf:
            raise ChunkPlanError(f"shot[{idx}] end_frame ({ef}) < start_frame ({sf})")
        # pinned shot shape only
        normalized.append({"shot_id": s["shot_id"], "start_frame": sf, "end_frame": ef})

    # sort by start_frame to detect monotonic/overlap/gap
    normalized.sort(key=lambda x: x["start_frame"])

    # validate monotonic, non-overlapping, no gaps, contiguous from 0
    if normalized[0]["start_frame"] != 0:
        raise ChunkPlanError(f"first shot must start at 0, got {normalized[0]['start_frame']}")

    for i in range(len(normalized)):
        cur = normalized[i]
        if i > 0:
            prev = normalized[i - 1]
            # overlapping or non-monotonic
            if cur["start_frame"] <= prev["end_frame"]:
                raise ChunkPlanError(
                    f"shots overlap or non-monotonic: shot {prev['shot_id']} [{prev['start_frame']},{prev['end_frame']}] "
                    f"and {cur['shot_id']} [{cur['start_frame']},{cur['end_frame']}]"
                )
            # gap detection: must be contiguous (prev end +1 == cur start)
            if cur["start_frame"] != prev["end_frame"] + 1:
                raise ChunkPlanError(
                    f"gap between shots: {prev['shot_id']} ends at {prev['end_frame']}, "
                    f"{cur['shot_id']} starts at {cur['start_frame']}"
                )
        # also check 1-frame shot is allowed (end == start is valid)
    return normalized


def _normalize_mappings(raw: Any) -> list[dict[str, Any]]:
    mappings_raw: Any
    if isinstance(raw, dict):
        if "mappings" in raw:
            mappings_raw = raw["mappings"]
        elif "layers" in raw:
            mappings_raw = raw["layers"]
        else:
            raise ChunkPlanError("mapping must contain mappings or layers list")
    elif isinstance(raw, list):
        mappings_raw = raw
    else:
        raise ChunkPlanError("mapping must be dict with mappings or list")

    if not isinstance(mappings_raw, list) or len(mappings_raw) == 0:
        raise ChunkPlanError("mapping mappings must be non-empty list")

    normalized: list[dict[str, Any]] = []
    seen_layer_ids: set[str] = set()
    for idx, m in enumerate(mappings_raw):
        if not isinstance(m, dict):
            raise ChunkPlanError(f"mapping[{idx}] must be dict")
        # layer_id or role_id or layer or role
        layer_id = m.get("layer_id") or m.get("role_id") or m.get("layer") or m.get("role") or m.get("object_role_id")
        if not isinstance(layer_id, str) or not layer_id:
            # fallback to explicit id field
            lid2 = m.get("id")
            if isinstance(lid2, str) and lid2:
                layer_id = lid2
            else:
                raise ChunkPlanError(f"mapping[{idx}] requires layer_id/role_id (non-empty str)")
        assert isinstance(layer_id, str)
        if layer_id in seen_layer_ids:
            raise ChunkPlanError(f"duplicate layer_id {layer_id!r} in mapping")
        seen_layer_ids.add(layer_id)

        route = m.get("route")
        if not isinstance(route, str) or route not in RENDERER_ROUTES:
            raise ChunkPlanError(f"mapping[{idx}] route must be one of {sorted(RENDERER_ROUTES)}, got {route!r}")

        deps = m.get("deps")
        if deps is None:
            deps = []
        if not isinstance(deps, list):
            raise ChunkPlanError(f"mapping[{idx}].deps must be list if provided")
        for d in deps:
            if not isinstance(d, str):
                raise ChunkPlanError(f"mapping[{idx}].deps entries must be str")

        # object_role_id optional but pinned if present
        entry: dict[str, Any] = {"layer_id": layer_id, "route": route, "deps": sorted(deps)}
        if "object_role_id" in m and isinstance(m["object_role_id"], str) and m["object_role_id"]:
            entry["object_role_id"] = m["object_role_id"]
        if "pack_version_id" in m and isinstance(m["pack_version_id"], str) and m["pack_version_id"]:
            entry["pack_version_id"] = m["pack_version_id"]
        # Occurrence-scoped active range + deterministic order keys (BRIDGE
        # timeline feed; CONTRACT §3 / ruling Q5/Q10).  Optional — legacy
        # mappings without them keep the historical whole-shot behavior.
        for key in ("start_frame", "end_frame"):
            if key in m and m[key] is not None:
                value = m[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ChunkPlanError(f"mapping[{idx}].{key} must be int >= 0")
                entry[key] = value
        if (
            "start_frame" in entry
            and "end_frame" in entry
            and entry["end_frame"] < entry["start_frame"]
        ):
            raise ChunkPlanError(f"mapping[{idx}] end_frame < start_frame")
        for key in ("visibility", "logical_id"):
            if key in m and isinstance(m[key], str) and m[key]:
                entry[key] = m[key]
        if "z_order" in m and m["z_order"] is not None:
            if not isinstance(m["z_order"], int) or isinstance(m["z_order"], bool):
                raise ChunkPlanError(f"mapping[{idx}].z_order must be int")
            entry["z_order"] = m["z_order"]
        if "lineage_version" in m and m["lineage_version"] is not None:
            if (
                not isinstance(m["lineage_version"], int)
                or isinstance(m["lineage_version"], bool)
                or m["lineage_version"] < 1
            ):
                raise ChunkPlanError(f"mapping[{idx}].lineage_version must be int >= 1")
            entry["lineage_version"] = m["lineage_version"]
        normalized.append(entry)

    # deterministic order by layer_id
    normalized.sort(key=lambda x: x["layer_id"])
    return normalized


def _filtered_policy(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"policy_version": "default"}
    if not isinstance(raw, dict):
        raise ChunkPlanError("compatibility_policy must be dict if provided")
    # pinned keys
    allowed = ("policy_version", "thresholds", "compatibility_policy_version")
    out: dict[str, Any] = {}
    for k in allowed:
        if k in raw:
            out[k] = raw[k]
    # normalize policy_version
    pv = out.get("policy_version") or out.get("compatibility_policy_version")
    if pv is None:
        # maybe raw has version key
        if "version" in raw and isinstance(raw["version"], str):
            pv = raw["version"]
        else:
            pv = "default"
    if not isinstance(pv, str) or not pv:
        raise ChunkPlanError("compatibility_policy policy_version must be non-empty str")
    out = {"policy_version": pv}
    if "thresholds" in raw and isinstance(raw["thresholds"], dict):
        # include thresholds deterministically (sorted keys already via canonical json)
        out["thresholds"] = raw["thresholds"]
    return out


def _normalize_chunk_config(raw: Any, chunk_frames: int | None, overlap_frames: int | None) -> dict[str, int]:
    # raw may be dict with chunk_frames/overlap_frames
    cfg: dict[str, int] = {}
    if isinstance(raw, dict):
        if "chunk_frames" in raw:
            cfg["chunk_frames"] = raw["chunk_frames"]
        if "overlap_frames" in raw:
            cfg["overlap_frames"] = raw["overlap_frames"]
        if "chunk_size" in raw and "chunk_frames" not in cfg:
            cfg["chunk_frames"] = raw["chunk_size"]
        if "overlap" in raw and "overlap_frames" not in cfg:
            cfg["overlap_frames"] = raw["overlap"]
    if chunk_frames is not None:
        cfg["chunk_frames"] = chunk_frames
    if overlap_frames is not None:
        cfg["overlap_frames"] = overlap_frames
    if "chunk_frames" not in cfg:
        cfg["chunk_frames"] = 48
    if "overlap_frames" not in cfg:
        cfg["overlap_frames"] = 4
    cf = cfg["chunk_frames"]
    ov = cfg["overlap_frames"]
    if not isinstance(cf, int) or cf < 1:
        raise ChunkPlanError("chunk_frames must be int >= 1")
    if not isinstance(ov, int) or ov < 0:
        raise ChunkPlanError("overlap_frames must be int >= 0")
    if ov >= cf:
        raise ChunkPlanError("overlap_frames must be < chunk_frames")
    return {"chunk_frames": cf, "overlap_frames": ov}


# ── main planner ─────────────────────────────────────────────────────────────


def plan_full_apply(
    approved_checkpoint: dict[str, Any],
    structural_lock_manifest: dict[str, Any],
    scene_manifest: dict[str, Any] | list[dict[str, Any]],
    mapping: dict[str, Any] | list[dict[str, Any]],
    compatibility_policy: dict[str, Any] | None = None,
    *,
    chunk_frames: int | None = None,
    overlap_frames: int | None = None,
    chunk_config: dict[str, Any] | None = None,
    **_ambient: Any,
) -> dict[str, Any]:
    """Generate a deterministic full-video chunk plan.

    All inputs are pinned; ambient ``**_ambient`` kwargs (path, time, pid, etc.)
    are explicitly ignored and never affect the hash.

    Returns:
        Canonical plan dict with ``plan_id`` (sha256 of canonical JSON),
        ``plan_hash`` (same), ``version``, ``inputs`` and ``chunks``.

    Each chunk contains:
        ``chunk_id``, ``shot_id``, ``layer_id``, ``core_start_frame``,
        ``core_end_frame``, ``overlap_before``, ``overlap_after``,
        ``route``, ``deps``, ``content_hash_input``.

    Raises:
        ChunkPlanError: on any malformed / overlapping / non-monotonic input.
    """
    # ambient is intentionally ignored - ensures path/time/process does not affect identity
    _ = _ambient

    ckpt = _filtered_checkpoint(approved_checkpoint)
    manifest = _filtered_manifest(structural_lock_manifest)
    shots = _normalize_shots(scene_manifest)
    mappings = _normalize_mappings(mapping)
    policy = _filtered_policy(compatibility_policy)
    cfg = _normalize_chunk_config(chunk_config, chunk_frames, overlap_frames)

    # frame_count from manifest must match shots coverage
    total_frames = shots[-1]["end_frame"] + 1  # since start 0 contiguous
    if manifest["frame_count"] != total_frames:
        raise ChunkPlanError(
            f"frame_count mismatch: manifest {manifest['frame_count']} vs shots cover {total_frames} "
            f"(shots [{shots[0]['start_frame']},{shots[-1]['end_frame']}])"
        )
    # also validate no shot exceeds manifest frame_count
    if shots[-1]["end_frame"] >= manifest["frame_count"]:
        raise ChunkPlanError("shot end_frame exceeds manifest frame_count")

    # Build pinned inputs for hashing (deterministic, sorted)
    pinned: dict[str, Any] = {
        "approved_checkpoint": ckpt,
        "chunk_config": cfg,
        "compatibility_policy": policy,
        "mapping": mappings,
        "scene_manifest": shots,
        "structural_lock_manifest": manifest,
        "version": 1,
    }
    pinned_hash = _sha256_hex(_canonical_json(pinned))

    # Generate chunks: per shot, per layer, split core frames into cfg chunk_frames
    chunks: list[dict[str, Any]] = []
    # track chunk_ids for deps resolution
    # For deps we need mapping from (shot_id, layer_id, index) -> chunk_id
    chunk_id_by_position: dict[tuple[str, str, int], str] = {}

    # First pass: generate chunk_ids deterministically
    # We need to know pinned_hash before chunk ids, already have it.
    for shot in shots:
        shot_id: str = shot["shot_id"]
        s_start: int = shot["start_frame"]
        s_end: int = shot["end_frame"]
        for layer in mappings:
            layer_id: str = layer["layer_id"]
            # Occurrence-scoped active range clipped to this shot (BRIDGE
            # CONTRACT §3): a pair with an empty intersection produces NO
            # chunks — inactive layers are never applied.  Legacy mappings
            # without a range keep the historical whole-shot behavior.
            p_start = max(s_start, int(layer.get("start_frame", s_start)))
            p_end = min(s_end, int(layer.get("end_frame", s_end)))
            if p_end < p_start:
                continue
            pair_frames = p_end - p_start + 1
            num_chunks = (pair_frames + cfg["chunk_frames"] - 1) // cfg["chunk_frames"]
            for ci in range(num_chunks):
                core_start = p_start + ci * cfg["chunk_frames"]
                core_end = min(core_start + cfg["chunk_frames"] - 1, p_end)
                # deterministic chunk_id from pinned_hash + position
                identity = {
                    "layer_id": layer_id,
                    "core_end_frame": core_end,
                    "core_start_frame": core_start,
                    "pinned_hash": pinned_hash,
                    "shot_id": shot_id,
                }
                cid = "ck_" + _sha256_hex(_canonical_json(identity))[:16]
                chunk_id_by_position[(shot_id, layer_id, ci)] = cid

    # Second pass: build full chunk records with overlap, route, deps, content hash
    for shot in shots:
        shot_id = shot["shot_id"]
        s_start = shot["start_frame"]
        s_end = shot["end_frame"]
        for layer_idx, layer in enumerate(mappings):
            layer_id = layer["layer_id"]
            route: str = layer["route"]
            p_start = max(s_start, int(layer.get("start_frame", s_start)))
            p_end = min(s_end, int(layer.get("end_frame", s_end)))
            if p_end < p_start:
                continue
            pair_frames = p_end - p_start + 1
            num_chunks = (pair_frames + cfg["chunk_frames"] - 1) // cfg["chunk_frames"]
            # structural deps from layer mapping (sorted)
            base_deps: list[str] = list(layer.get("deps", []))
            for ci in range(num_chunks):
                core_start = p_start + ci * cfg["chunk_frames"]
                core_end = min(core_start + cfg["chunk_frames"] - 1, p_end)
                # Q10: zero at the pair edges — no overlap bleed across a cut
                # or into an inactive interval.
                overlap_before = cfg["overlap_frames"] if ci > 0 else 0
                overlap_after = cfg["overlap_frames"] if core_end < p_end else 0
                # deps: previous chunk in same shot/layer + same-index chunk from previous layer
                deps: list[str] = list(base_deps)
                if ci > 0:
                    prev_id = chunk_id_by_position[(shot_id, layer_id, ci - 1)]
                    deps.append(prev_id)
                if layer_idx > 0:
                    prev_layer_id = mappings[layer_idx - 1]["layer_id"]
                    # same chunk index in previous layer, if that layer also has this index
                    prev_layer_cid = chunk_id_by_position.get((shot_id, prev_layer_id, ci))
                    if prev_layer_cid is not None:
                        deps.append(prev_layer_cid)
                deps = sorted(set(deps))
                chunk_id = chunk_id_by_position[(shot_id, layer_id, ci)]
                # content hash input: hash of pinned + chunk core identity + route + deps
                content_input = {
                    "checkpoint_hash": ckpt["checkpoint_hash"],
                    "core_end_frame": core_end,
                    "core_start_frame": core_start,
                    "layer_id": layer_id,
                    "manifest_hash": manifest["manifest_hash"],
                    "overlap_after": overlap_after,
                    "overlap_before": overlap_before,
                    "policy_version": policy["policy_version"],
                    "route": route,
                    "shot_id": shot_id,
                    "deps": deps,
                }
                content_hash_input = _sha256_hex(_canonical_json(content_input))
                record: dict[str, Any] = {
                    "chunk_id": chunk_id,
                    "shot_id": shot_id,
                    "layer_id": layer_id,
                    "core_start_frame": core_start,
                    "core_end_frame": core_end,
                    "overlap_before": overlap_before,
                    "overlap_after": overlap_after,
                    "route": route,
                    "deps": deps,
                    "content_hash_input": content_hash_input,
                }
                # Q5: the deterministic layer order keys are RECORDED in the
                # plan rows when the mapping carries them (timeline feed).
                for key in ("z_order", "logical_id", "lineage_version", "visibility"):
                    if key in layer:
                        record[key] = layer[key]
                chunks.append(record)

    # Deterministic order: sort by shot start_frame, then layer_id, then core_start
    # Build shot order map for stable sort
    shot_order = {s["shot_id"]: i for i, s in enumerate(shots)}
    layer_order = {m["layer_id"]: i for i, m in enumerate(mappings)}
    chunks.sort(key=lambda c: (shot_order[c["shot_id"]], layer_order[c["layer_id"]], c["core_start_frame"]))

    # Canonical plan without plan_id for hashing
    plan_body: dict[str, Any] = {
        "chunks": chunks,
        "inputs": pinned,
        "version": 1,
    }
    plan_id = _sha256_hex(_canonical_json(plan_body))

    plan: dict[str, Any] = {
        "plan_id": plan_id,
        "plan_hash": plan_id,
        "version": 1,
        "inputs": pinned,
        "chunks": chunks,
        "frame_count": total_frames,
        "chunk_config": cfg,
    }
    return plan
