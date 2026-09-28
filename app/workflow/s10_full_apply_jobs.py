"""Durable FullApply job execution — real renderer, checkpoint/resume/cancel + stitch + publication (S10-T01C-C4).

One durable job type: S10_FULL_APPLY.  The worker executes each shot/layer chunk
through the corrected T02 real executor (sprite_affine/pose_swap/controlled_redraw
via renderer_router/composite), checkpointing BEFORE each chunk so a fresh process
resumes the exact unfinished chunk and never re-renders verified completed chunks.

C4 (S10-C2 correction C1-F1/F5):
- The production path NEVER fabricates inputs.  It LOADs the immutable
  server-side `render_authority` (approved_checkpoint / structural_lock_manifest /
  scene_manifest / mapping / compatibility_policy + run chunk_config) from the job
  manifest, recomputes the deterministic plan, and verifies plan_id/plan_hash
  against the persisted run row before rendering ANY chunk.  Source media and
  replacement assets are loaded from manifest-pinned relative paths + sha256 under
  the managed root; missing/tampered inputs fail closed.
- Chunk identities (workspace/project/video, shot/layer/cores) come from the DB row
  and the verified plan — no `layer_N`/`pack_N_v1`/`mapping_N_v1` fabrication, no
  route downgrade: an unsupported route raises (fail closed).
- Crash/restart injection is possible ONLY through the module-level
  `_TEST_STOP_AFTER_CHUNK` test control.  A production manifest that carries
  `stop_after_chunk` is rejected (caller crash-hook injection -> fail closed).
- Zero chunks is fail-closed: the run is marked failed, never completed, and no
  publication is created (`:342-345` empty-run completion removed).
- Resume reuses a verified chunk only when artifact SHA/size, decoded frame count,
  probed timebase, stored evidence content-hash AND the pinned plan content_hash
  all match; otherwise it quarantines and recomputes, never advancing the
  checkpoint past an unverified chunk.
- Stitch COMPOSES (never dedups): every output frame is the source frame with
  ALL active visible/occluded layers applied in deterministic order; ranges
  with no active layer keep source frames verbatim.  Per-layer decoded-region
  evidence (frozen Q9 format) proves each layer contributed; missing evidence
  or a no_delta row fails the run closed (no publication).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text as sa_text

from app.persistence.artifacts import hash_file
from app.workflow.durable_worker import WorkerContext

try:
    from app.services.s10_chunk_plan import ChunkPlanError, plan_full_apply
except ImportError:  # pragma: no cover - defensive
    ChunkPlanError: Any = None  # type: ignore[no-redef]
    plan_full_apply: Any = None  # type: ignore[no-redef]

try:
    from app.services.s10_multi_role_apply import (
        S10MultiRoleService as _S10MultiRoleService,  # noqa: F401
    )
except ImportError:
    _S10MultiRoleService: Any = None  # type: ignore[no-redef]

try:
    from app.services.s10_recompute import (  # noqa: F401
        S10RecomputeService as _S10RecomputeService,
    )
    from app.services.s10_recompute import (
        compute_affected_closure as _compute_affected_closure,
    )
except ImportError:
    _S10RecomputeService: Any = None  # type: ignore[no-redef]
    _compute_affected_closure: Any = None  # type: ignore[no-redef]

try:
    from app.services.s10_structural_compare import (  # noqa: F401
        S10StructuralCompareService as _S10StructuralCompareService,
    )
except ImportError:
    _S10StructuralCompareService: Any = None  # type: ignore[no-redef]

try:
    from app.services.shot_reskin_executor import (
        ShotRenderRefusal as _ShotRenderRefusal,
    )
    from app.services.shot_reskin_executor import (
        run_shot_render as _run_shot_render,
    )
    from app.services.shot_reskin_executor import (
        select_profile as _select_shot_profile,
    )
except ImportError:  # pragma: no cover - defensive
    _ShotRenderRefusal: Any = None  # type: ignore[no-redef]
    _run_shot_render: Any = None  # type: ignore[no-redef]
    _select_shot_profile: Any = None  # type: ignore[no-redef]

try:
    from app.services.shot_reskin_cache import (  # noqa: F401
        ShotCacheRefusal as _ShotCacheRefusal,
    )
    from app.services.shot_reskin_cache import (
        ShotReskinCache as _ShotReskinCache,
    )
    from app.services.shot_reskin_cache import (
        run_cached_shot_render as _run_cached_shot_render,
    )
except ImportError:  # pragma: no cover - defensive
    _ShotCacheRefusal: Any = None  # type: ignore[no-redef]
    _ShotReskinCache: Any = None  # type: ignore[no-redef]
    _run_cached_shot_render: Any = None  # type: ignore[no-redef]

__all__ = [
    "JOB_TYPE_S10_FULL_APPLY",
    "S10_FULL_APPLY_STEP_CODE",
    "S10FullApplyJobError",
    "s10_full_apply_handler",
    "register_s10_full_apply_handler",
]

JOB_TYPE_S10_FULL_APPLY = "s10_full_apply"
S10_FULL_APPLY_STEP_CODE = "s10_full_apply"
S10_CP_VERSION = 1

# Routes the licensed T02 adapters can execute in production.  Anything else
# (e.g. mesh_warp) fails closed — the worker never downgrades a route.
_EXECUTABLE_ROUTES = frozenset({"sprite_affine", "pose_swap", "controlled_redraw"})

# Test-owned crash/restart control.  The production API manifest can NEVER set
# this: the handler reads ONLY this module global and REJECTS any manifest that
# contains `stop_after_chunk` (caller crash-hook injection -> fail closed).
_TEST_STOP_AFTER_CHUNK: int | None = None


class S10FullApplyJobError(RuntimeError):
    code = "S10_FULL_APPLY_FAILED"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_fingerprint(value: Any) -> str:
    """Deterministic sha256 over canonical JSON — matches service fingerprint."""
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _lp(path: Path, *, force: bool = False) -> Path:
    """Windows extended-length path (>=260) so deep managed roots still work.

    Returns a ``Path`` carrying the ``\\\\\\\\?\\\\`` prefix when the absolute path
    exceeds the classic MAX_PATH; other platforms pass through unchanged.
    With ``force=True`` (used once for the managed ROOT) the prefix is applied
    on Windows regardless of length, so the root and EVERY derived child
    (workspace_root, output_media, evidence, staging) share the SAME path
    form — otherwise a root just under MAX_PATH yields prefixed children but
    an unprefixed workspace_root, which breaks the renderer contract's
    containment check (mixed-form ``relative_to`` raises).
    All FullApply media/evidence I/O goes through this helper so final and
    staging paths under the managed root survive >260-char nesting.
    """
    raw = str(path)
    if os.name == "nt" and not raw.startswith("\\\\?\\") and (force or len(raw) > 259):
        return Path("\\\\?\\" + os.path.abspath(raw))
    return path


# ── server-side input loading (C4: never fabricate source/asset) ────────────


def _require_manifest_authority(
    manifest: dict[str, Any],
    run_row: dict[str, Any],
    *,
    session_factory: Any = None,
    workspace_id: str = "",
    checkpoint_id: str = "",
) -> dict[str, Any]:
    """Load and verify the canonical server-side render authority.

    C8: the authority is built by the service EXCLUSIVELY from the frozen
    ``s09.approval/v2`` checkpoint (never a client body echo) and stored in the
    job manifest; retry/resume inherit it from the predecessor job.  The worker
    (a) recomputes the deterministic plan from these canonical inputs and
    verifies plan_id/hash against the run row, and (b) re-derives the
    authority fingerprint from the PERSISTED v2 row and verifies it against
    the manifest pin — any mutation/tamper fails closed before render.
    Missing/empty authority fails closed — the worker never invents
    checkpoint/scene/mapping inputs.
    """
    if ChunkPlanError is None or plan_full_apply is None:
        raise S10FullApplyJobError("chunk planner not available")
    authority = manifest.get("render_authority")
    if not isinstance(authority, dict) or not authority:
        raise S10FullApplyJobError(
            "render_authority missing from job manifest — cannot render without canonical server-side authority"
        )
    required = (
        "authority_fingerprint",
        "approved_checkpoint",
        "structural_lock_manifest",
        "scene_manifest",
        "mapping",
        "compatibility_policy",
    )
    for key in required:
        if key not in authority or authority[key] in (None, "", [], {}):
            raise S10FullApplyJobError(f"render_authority.{key} is missing (fail closed)")
    chunk_config = run_row.get("chunk_config") or {}
    plan = plan_full_apply(
        authority["approved_checkpoint"],
        authority["structural_lock_manifest"],
        authority["scene_manifest"],
        authority["mapping"],
        authority.get("compatibility_policy"),
        chunk_frames=None,
        overlap_frames=None,
        chunk_config=dict(chunk_config),
    )
    if plan["plan_id"] != run_row.get("plan_id") or plan["plan_hash"] != run_row.get("plan_hash"):
        raise S10FullApplyJobError(
            "plan pin mismatch: recomputed plan_id/hash does not match run row (tampered authority)"
        )
    # Re-derive the authority fingerprint from the PERSISTED v2 row and verify
    # the manifest pin — fences mutation/tamper before any render/publication.
    if session_factory is not None and checkpoint_id:
        from app.services.s09_approval import S09ApprovalRepository as _S09Repo

        try:
            with session_factory() as _s:
                _db_authority = _S09Repo(_s).full_apply_authority(checkpoint_id, workspace_id)
        except Exception as exc:
            raise S10FullApplyJobError(
                f"cannot re-derive v2 authority from persisted row: {exc} (fail closed)"
            ) from exc
        _db_fp = _canonical_fingerprint(_db_authority)
        if _db_fp != authority.get("authority_fingerprint"):
            raise S10FullApplyJobError(
                "authority fingerprint mismatch vs persisted v2 row (tampered/mutated authority)"
            )
    return authority


def _load_source_media(managed_root: Path, manifest: dict[str, Any]) -> Path:
    """Load the pinned source artifact; missing/tampered source fails closed."""
    rel_raw = manifest.get("source_media_rel")
    if not isinstance(rel_raw, str) or not rel_raw:
        raise S10FullApplyJobError("source_media_rel missing from manifest (no source artifact pin)")
    pinned_sha = manifest.get("source_media_sha256")
    if not isinstance(pinned_sha, str) or len(pinned_sha) != 64:
        raise S10FullApplyJobError("source_media_sha256 missing from manifest (no source hash pin)")
    src = _lp(managed_root / rel_raw)
    if not src.is_file():
        raise S10FullApplyJobError(f"source media missing: {rel_raw}")
    actual = hash_file(src)
    if actual != pinned_sha.lower():
        raise S10FullApplyJobError(f"source media sha mismatch: expected {pinned_sha} got {actual}")
    pinned_size = manifest.get("source_media_size_bytes")
    if isinstance(pinned_size, int) and pinned_size > 0 and src.stat().st_size != pinned_size:
        raise S10FullApplyJobError(
            f"source media size mismatch: expected {pinned_size} got {src.stat().st_size}"
        )
    from app.services.renderer_routes.composite import decode_rgb_frames

    try:
        frames = decode_rgb_frames(src)
    except Exception as exc:
        raise S10FullApplyJobError(f"source not decodable: {exc}") from exc
    if not frames:
        raise S10FullApplyJobError("source media has zero decodable frames")
    return src


def _load_replacement_asset(managed_root: Path, manifest: dict[str, Any], layer_id: str) -> Path:
    """Load one manifest-pinned replacement/pose asset; missing asset fails closed."""
    assets = manifest.get("replacement_assets")
    if not isinstance(assets, dict) or layer_id not in assets:
        raise S10FullApplyJobError(f"replacement_assets missing entry for layer {layer_id!r}")
    entry = assets[layer_id]
    if not isinstance(entry, dict):
        raise S10FullApplyJobError(f"replacement_assets[{layer_id!r}] must be a dict")
    rel_raw = entry.get("rel")
    pinned_sha = entry.get("sha256")
    if not isinstance(rel_raw, str) or not rel_raw or not isinstance(pinned_sha, str) or len(pinned_sha) != 64:
        raise S10FullApplyJobError(f"replacement_assets[{layer_id!r}] missing rel/sha256 pin")
    abs_p = _lp(managed_root / rel_raw)
    if not abs_p.is_file():
        raise S10FullApplyJobError(f"replacement asset missing for {layer_id!r}: {rel_raw}")
    actual = hash_file(abs_p)
    if actual != pinned_sha.lower():
        raise S10FullApplyJobError(
            f"replacement asset sha mismatch for {layer_id!r}: expected {pinned_sha} got {actual}"
        )
    pinned_size = entry.get("size_bytes")
    if isinstance(pinned_size, int) and pinned_size > 0 and abs_p.stat().st_size != pinned_size:
        raise S10FullApplyJobError(
            f"replacement asset size mismatch for {layer_id!r}: expected {pinned_size} got {abs_p.stat().st_size}"
        )
    return abs_p


def _authoritative_mapping_by_layer(authority: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize the authority mapping into {layer_id: entry} — no fabrication.

    Each layer entry MUST pin affected_region (real-adapter execution requires
    pinned source geometry; a missing region is a fabricated mapping and fails
    closed).
    """
    raw = authority.get("mapping")
    entries: list[Any] = []
    if isinstance(raw, dict):
        if isinstance(raw.get("mappings"), list):
            entries = raw["mappings"]
        elif isinstance(raw.get("layers"), list):
            entries = raw["layers"]
    elif isinstance(raw, list):
        entries = raw
    if not entries:
        raise S10FullApplyJobError("authority mapping has no layers (fabricated/missing mapping)")
    out: dict[str, dict[str, Any]] = {}
    for i, m in enumerate(entries):
        if not isinstance(m, dict):
            raise S10FullApplyJobError(f"authority mapping[{i}] must be a dict")
        layer_id = m.get("layer_id") or m.get("role_id") or m.get("layer") or m.get("role") or m.get("id")
        if not isinstance(layer_id, str) or not layer_id:
            raise S10FullApplyJobError(f"authority mapping[{i}] missing layer_id")
        ar = m.get("affected_region")
        if not isinstance(ar, (list, tuple)) or len(ar) != 4:
            raise S10FullApplyJobError(
                f"authority mapping layer {layer_id!r} missing affected_region [x,y,w,h] (fabricated mapping)"
            )
        route = m.get("route")
        if not isinstance(route, str) or route not in _EXECUTABLE_ROUTES:
            raise S10FullApplyJobError(
                f"authority mapping layer {layer_id!r} route {route!r} not executable "
                f"(supported: {sorted(_EXECUTABLE_ROUTES)})"
            )
        out[layer_id] = {
            "layer_id": layer_id,
            "route": route,
            "affected_region": [float(v) for v in ar],
            "pack_version": m.get("pack_version") or m.get("pack_version_id") or "v1",
            "mapping_id": m.get("mapping_id") or m.get("id") or f"mapping_{layer_id}",
            "deps": sorted(str(d) for d in m.get("deps", []) or []),
            # BRIDGE timeline feed (CONTRACT §3/§8): occurrence-scoped identity
            # and deterministic order keys; defaults keep legacy mappings
            # (role-as-layer) working unchanged.
            "role_id": str(m.get("role_id") or ""),
            "visibility": str(m.get("visibility") or "visible"),
            "z_order": int(m.get("z_order") or 0),
            "logical_id": str(m.get("logical_id") or layer_id),
            "lineage_version": int(m.get("lineage_version") or 1),
            "start_frame": m.get("start_frame"),
            "end_frame": m.get("end_frame"),
        }
    return out


def _stage_layer_asset(
    managed_root: Path,
    run_id: str,
    layer_id: str,
    manifest: dict[str, Any],
    mapping_entry: dict[str, Any],
) -> Path:
    """Resolve + verify + stage ONE occurrence layer's replacement asset.

    The canonical job manifest keys ``replacement_assets`` by object role id
    (built by the submit route from ``role_mappings``) while occurrence-scoped
    plans key chunks by the occurrence ``layer_id``.  This adapter resolves
    through the frozen mapping entry, verifies the manifest pin (SHA/size)
    against the managed artifact, then stages a byte-identical copy as
    ``<layer_id>.png`` in a per-layer directory — the T02 executor resolves
    assets by exactly that name (``assets_dir / f"{layer_id}.png"``).
    Returns the staging directory to use as ``assets_dir``.
    """
    asset_key = str(mapping_entry.get("role_id") or layer_id)
    source_abs = _load_replacement_asset(managed_root, manifest, asset_key)
    src_hash = hash_file(source_abs)
    stage_dir = _lp(managed_root / f"s10_full_apply/{run_id}/_assets/{layer_id}")
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged = _lp(stage_dir / f"{layer_id}.png")
    if not staged.is_file() or hash_file(staged) != src_hash:
        import shutil as _shutil

        _shutil.copyfile(source_abs, staged)
        if hash_file(staged) != src_hash:
            raise S10FullApplyJobError(
                f"staged asset copy mismatch for layer {layer_id!r} (fail closed)"
            )
    return stage_dir


def _render_chunk_via_real_executor(
    *,
    managed_root: Path,
    run_id: str,
    chunk: dict[str, Any],
    chunk_index: int,
    fps_num: int,
    fps_den: int,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    authority: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[Path, str, int, dict[str, Any]]:
    """Render one chunk via corrected T02 executor with authoritative identities.

    Source media + replacement asset are LOADED (never created) from manifest
    pins; route/mapping come from the verified plan authority; ws/project/video
    identities are passed through to the T02-C2 typed executor (no hard-coded
    defaults, no hash-of-layer fabrication).
    """
    layer_id = str(chunk.get("layer_id") or "")
    if not layer_id:
        raise S10FullApplyJobError("chunk has no layer_id (authoritative identity missing)")
    shot_id = str(chunk.get("shot_id") or "")
    if not shot_id:
        raise S10FullApplyJobError("chunk has no shot_id (authoritative identity missing)")
    core_start = int(chunk.get("core_start_frame", 0))
    core_end = int(chunk.get("core_end_frame", core_start))
    if core_end < core_start:
        raise S10FullApplyJobError(f"bad core range {core_start}-{core_end}")

    mapping_by_layer = _authoritative_mapping_by_layer(authority)
    if layer_id not in mapping_by_layer:
        raise S10FullApplyJobError(f"layer {layer_id!r} not present in authority mapping")
    layer_route = mapping_by_layer[layer_id]["route"]

    source_media = _load_source_media(managed_root, manifest)
    assets_dir = _stage_layer_asset(
        managed_root, run_id, layer_id, manifest, mapping_by_layer[layer_id]
    )

    sha_marker = hashlib.sha256(f"{run_id}:{core_start}-{core_end}:{layer_route}".encode()).hexdigest()[:12]
    rel: Path = Path(f"s10_full_apply/{run_id}/chunk_{chunk_index:04d}_{layer_id}_{sha_marker}.mp4")
    abs_out = _lp(managed_root / rel)
    abs_out.parent.mkdir(parents=True, exist_ok=True)

    if _S10MultiRoleService is None:
        raise S10FullApplyJobError("S10MultiRoleService not available")
    svc = _S10MultiRoleService()
    from app.services.renderer_contract import SourceTimebase

    tb = SourceTimebase(fps_num=fps_num, fps_den=fps_den)
    role_raw = {
        "role_id": f"role_{layer_id}",
        "layer_id": layer_id,
        "route": layer_route,
        "pack_version": mapping_by_layer[layer_id]["pack_version"],
        "mapping_id": mapping_by_layer[layer_id]["mapping_id"],
        "deps": mapping_by_layer[layer_id]["deps"],
        "z_order": chunk_index,
        "affected_region": mapping_by_layer[layer_id]["affected_region"],
    }
    plan = svc.build_plan(
        roles=[role_raw],
        shots=[{"shot_id": shot_id, "start_frame": core_start, "end_frame": core_end}],
        chunk_config={"chunk_frames": core_end - core_start + 1, "overlap_frames": 0},
    )
    role_id = f"role_{layer_id}"
    ch_raw: Any = plan.per_role_chunks.get(role_id) or []
    ch_list: list[dict[str, Any]] = list(ch_raw)
    if not ch_list:
        raise S10FullApplyJobError("T02 plan produced no chunk for role")
    target = ch_list[0]
    out_media = abs_out
    ev = svc.execute_role_chunk(
        role=plan.roles[0],
        chunk=target,
        workspace_root=_lp(managed_root),
        source_media=source_media,
        assets_dir=assets_dir,
        output_media=out_media,
        source_timebase=tb,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
    )
    evidence = dict(ev.get("evidence", {}))
    from app.services.renderer_routes.composite import canonical_frame_sha256, decode_rgb_frames

    decoded = decode_rgb_frames(out_media)
    expected = core_end - core_start + 1
    if len(decoded) != expected:
        raise S10FullApplyJobError(f"chunk decode mismatch {len(decoded)} != {expected}")
    decoded_sha = canonical_frame_sha256(decoded)
    sha = hash_file(out_media)
    size = out_media.stat().st_size
    evidence["decoded_sha256"] = decoded_sha
    evidence["decoded_frame_count"] = len(decoded)
    evidence["fps_num"] = fps_num
    evidence["fps_den"] = fps_den
    evidence["layer_id"] = layer_id
    evidence["shot_id"] = shot_id
    evidence["workspace_id"] = workspace_id
    evidence["project_id"] = project_id
    evidence["video_item_id"] = video_item_id
    return rel, sha, size, evidence


def _png_crop_bytes(crop_bgr: Any) -> bytes:
    """Deterministic PNG-encoded RGB8 crop bytes (frozen Q9 hashing input)."""
    import cv2

    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    ok, buf = cv2.imencode(".png", rgb, [int(cv2.IMWRITE_PNG_COMPRESSION), 6])
    if not ok:
        raise S10FullApplyJobError(
            "STITCH_LAYER_EVIDENCE_MISSING: PNG crop encode failed (fail closed)"
        )
    return buf.tobytes()


def _crops_sha256(crops: list[Any]) -> str:
    """sha256 over the concatenated deterministic PNG bytes of the crops."""
    digest = hashlib.sha256()
    for crop in crops:
        digest.update(_png_crop_bytes(crop))
    return digest.hexdigest()


def _compose_layer_unit(
    *,
    svc: Any,
    unit: dict[str, Any],
    buffer_frames: list[Any],
    managed_root: Path,
    source_media: Path,
    output_dir: Path,
    fps_num: int,
    fps_den: int,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> None:
    """Apply ONE verified layer unit onto the running frame buffer IN PLACE.

    The unit (shot ∩ occurrence ∩ chunk run) is composited through the EXACT
    facilities the chunk render used: the T02 request builder consumes the
    same role payload + staged ``<layer_id>.png`` asset, and the deterministic
    composite functions run over the running buffer window (sequential
    composition — every layer contributes; range-dedup is never used).
    """
    from app.services.renderer_contract import SourceTimebase

    start = int(unit["core_start_frame"])
    end = int(unit["core_end_frame"])
    layer_id = str(unit["layer_id"])
    mapping_entry = unit["mapping"]
    role_raw = {
        "role_id": f"role_{layer_id}",
        "layer_id": layer_id,
        "route": unit["route"],
        "pack_version": mapping_entry.get("pack_version") or "v1",
        "mapping_id": mapping_entry.get("mapping_id") or f"mapping_{layer_id}",
        "deps": list(mapping_entry.get("deps") or []),
        "z_order": int(unit.get("z_order") or 0),
        "affected_region": list(mapping_entry["affected_region"]),
    }
    plan = svc.build_plan(
        roles=[role_raw],
        shots=[{"shot_id": unit["shot_id"], "start_frame": start, "end_frame": end}],
        chunk_config={"chunk_frames": end - start + 1, "overlap_frames": 0},
    )
    rm = plan.roles[0]
    ch_list = list(plan.per_role_chunks.get(role_raw["role_id"]) or [])
    if not ch_list:
        raise S10FullApplyJobError(
            "STITCH_LAYER_EVIDENCE_MISSING: composition produced no T02 chunk "
            f"for layer {layer_id!r}"
        )
    request = svc._build_render_request_for_chunk(
        rm=rm,
        chunk=ch_list[0],
        workspace_root=_lp(managed_root),
        source_media=source_media,
        output_media=_lp(output_dir / f"compose_{layer_id}_{start}_{end}.mp4"),
        assets_dir=unit["assets_dir"],
        source_timebase=SourceTimebase(fps_num=fps_num, fps_den=fps_den),
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
    )
    window = buffer_frames[start : end + 1]
    if str(unit["route"]) == "pose_swap":
        from app.services.renderer_routes.composite import composite_pose_swap_frames

        applied = composite_pose_swap_frames(window, request)
    else:
        from app.services.renderer_routes.composite import composite_sprite_affine_frames

        applied = composite_sprite_affine_frames(window, request)
    expected = end - start + 1
    if len(applied) != expected:
        raise S10FullApplyJobError(
            "STITCH_FRAME_COVERAGE_MISMATCH: composition produced "
            f"{len(applied)} frames for layer {layer_id!r} range [{start},{end}]"
        )
    for offset, frame in enumerate(applied):
        buffer_frames[start + offset] = frame


def _stitch_verified_chunks(
    *,
    managed_root: Path,
    run_id: str,
    chunks: list[dict[str, Any]],
    session_factory: Any,
    ws: str,
    fps_num: int,
    fps_den: int,
    authority: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    frame_count: int | None = None,
) -> tuple[Path, str, int, dict[str, Any]]:
    """Deterministically COMPOSE verified core chunks into one playable MP4.

    CONTRACT §8 / ruling Q9: every output frame is the source frame with ALL
    active visible/occluded layers composited in the deterministic order
    (z_order asc, tie → (logical_id, lineage_version)); ranges with no active
    layer keep the source frames verbatim (background-only coverage).
    Dedup-to-first-layer is FORBIDDEN — each active (shot ∩ occurrence ∩
    chunk run) unit is applied and proved by its own frozen-format per-layer
    decoded-region evidence row.  A missing artifact, missing/`no_delta`
    evidence, or a frame-coverage mismatch fails closed (run failed, zero
    publication).
    """
    import numpy as np

    from app.services.renderer_routes.composite import (
        _region_px,
        decode_rgb_frames,
        write_frames_mp4,
    )

    if not isinstance(authority, dict) or not isinstance(manifest, dict):
        raise S10FullApplyJobError(
            "STITCH_LAYER_EVIDENCE_MISSING: composition requires the frozen "
            "authority + manifest (fail closed)"
        )
    scene_manifest = authority.get("scene_manifest")
    sl_manifest = authority.get("structural_lock_manifest")
    if not isinstance(scene_manifest, dict) or not isinstance(sl_manifest, dict):
        raise S10FullApplyJobError(
            "STITCH_LAYER_EVIDENCE_MISSING: composition requires the frozen "
            "scene partition + manifest pins (fail closed)"
        )
    expected_frame_count = sl_manifest.get("frame_count")
    if not isinstance(expected_frame_count, int) or expected_frame_count < 1:
        raise S10FullApplyJobError(
            "STITCH_FRAME_COVERAGE_MISMATCH: timeline frame_count is invalid"
        )
    if frame_count is not None and int(frame_count) != expected_frame_count:
        raise S10FullApplyJobError(
            f"STITCH_FRAME_COVERAGE_MISMATCH: plan frame_count {frame_count} "
            f"!= timeline frame_count {expected_frame_count}"
        )

    mapping_by_layer = _authoritative_mapping_by_layer(authority)
    shots = [s for s in (scene_manifest.get("shots") or []) if isinstance(s, dict)]
    shot_by_id = {str(s.get("shot_id")): s for s in shots}
    shot_index = {str(s.get("shot_id")): idx for idx, s in enumerate(shots)}

    source_media = _load_source_media(managed_root, manifest)
    src_frames = decode_rgb_frames(source_media)
    if len(src_frames) != expected_frame_count:
        raise S10FullApplyJobError(
            f"STITCH_FRAME_COVERAGE_MISMATCH: source decodes to "
            f"{len(src_frames)} frames; timeline frame_count is "
            f"{expected_frame_count}"
        )
    buffer_frames: list[Any] = list(src_frames)
    frame_h, frame_w = buffer_frames[0].shape[:2]

    # ── expected units: (shot ∩ render-active occurrence) pairs ──────────
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for shot in shots:
        sid = str(shot.get("shot_id"))
        s0 = int(shot["start_frame"])
        s1 = int(shot["end_frame"])
        for lid, m in mapping_by_layer.items():
            if m["visibility"] not in ("visible", "occluded"):
                continue
            ms = m.get("start_frame")
            me = m.get("end_frame")
            p0 = max(s0, int(ms)) if isinstance(ms, int) else s0
            p1 = min(s1, int(me)) if isinstance(me, int) else s1
            if p1 < p0:
                continue
            expected[(sid, lid)] = {"shot_id": sid, "pair_start": p0, "pair_end": p1}

    # ── group DB chunk rows per pair; tile/validate ──────────────────────
    rows_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ch in chunks:
        sid = str(ch.get("shot_id") or "")
        lid = str(ch.get("layer_id") or "")
        rows_by_pair.setdefault((sid, lid), []).append(ch)

    for key, pair_rows in rows_by_pair.items():
        sid, lid = key
        if sid not in shot_by_id:
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: chunk references unknown "
                f"shot {sid!r} (fail closed)"
            )
        if lid not in mapping_by_layer:
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: chunk references layer "
                f"{lid!r} not in the frozen mapping (fail closed)"
            )
        m = mapping_by_layer[lid]
        if m["visibility"] not in ("visible", "occluded"):
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: chunk references non-render "
                f"layer {lid!r} (stale plan, fail closed)"
            )
        exp = expected.get(key)
        if exp is None:
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: chunk rows for {sid}/{lid} "
                "outside the active intersection (fail closed)"
            )
        cursor = exp["pair_start"]
        for row in sorted(pair_rows, key=lambda c: int(c["core_start_frame"])):
            a = int(row["core_start_frame"])
            b = int(row["core_end_frame"])
            if a != cursor or b < a:
                raise S10FullApplyJobError(
                    f"STITCH_LAYER_ARTIFACT_MISSING: {sid}/{lid} chunks do "
                    f"not tile [{exp['pair_start']},{exp['pair_end']}] "
                    "(gap/overlap, fail closed)"
                )
            cursor = b + 1
        if cursor != exp["pair_end"] + 1:
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: {sid}/{lid} chunks end at "
                f"{cursor - 1}; pair range ends at {exp['pair_end']} "
                "(fail closed)"
            )
    missing_pairs = [key for key in expected if key not in rows_by_pair]
    if missing_pairs:
        raise S10FullApplyJobError(
            "STITCH_LAYER_ARTIFACT_MISSING: no verified chunk artifacts for "
            "active pairs "
            + ", ".join(f"{sid}/{lid}" for sid, lid in sorted(missing_pairs))
        )

    # ── deterministic order: shot, z_order asc, (logical, lineage), layer ─
    staged_dirs: dict[str, Path] = {}
    units: list[dict[str, Any]] = []
    for ch in chunks:
        sid = str(ch.get("shot_id") or "")
        lid = str(ch.get("layer_id") or "")
        m = mapping_by_layer[lid]
        if lid not in staged_dirs:
            staged_dirs[lid] = _stage_layer_asset(managed_root, run_id, lid, manifest, m)
        units.append(
            {
                "shot_id": sid,
                "layer_id": lid,
                "chunk_id": str(ch.get("id")),
                "core_start_frame": int(ch["core_start_frame"]),
                "core_end_frame": int(ch["core_end_frame"]),
                "artifact_id": ch.get("artifact_id"),
                "route": m["route"],
                "mapping": m,
                "z_order": m["z_order"],
                "logical_id": m["logical_id"],
                "lineage_version": m["lineage_version"],
                "assets_dir": staged_dirs[lid],
            }
        )
    units.sort(
        key=lambda u: (
            shot_index.get(u["shot_id"], 0),
            int(u["z_order"]),
            str(u["logical_id"]),
            int(u["lineage_version"]),
            str(u["layer_id"]),
            int(u["core_start_frame"]),
        )
    )

    svc = _multi_role_service()
    composition_dir = _lp(managed_root / f"s10_full_apply/{run_id}/composition")
    composition_dir.mkdir(parents=True, exist_ok=True)

    per_layer_evidence: list[dict[str, Any]] = []
    final_crop_specs: list[tuple[dict[str, Any], tuple[int, int, int, int], list[int]]] = []
    for unit in units:
        aid = unit["artifact_id"]
        if not aid:
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: chunk {unit['chunk_id']} has "
                "no verified artifact (fail closed)"
            )
        start = int(unit["core_start_frame"])
        end = int(unit["core_end_frame"])
        layer_id = str(unit["layer_id"])
        m = unit["mapping"]
        with session_factory() as s:
            art = s.execute(
                sa_text(
                    "SELECT relative_path, workspace_id, state, sha256, size_bytes "
                    "FROM artifact WHERE id=:aid"
                ),
                {"aid": str(aid)},
            ).mappings().first()
            if (
                art is None
                or str(art["workspace_id"]) != ws
                or str(art["state"]) != "ready"
                or not art["sha256"]
                or not art["size_bytes"]
            ):
                raise S10FullApplyJobError(
                    f"STITCH_LAYER_ARTIFACT_MISSING: artifact {aid} not ready "
                    "for stitch (fail closed)"
                )
            rel = str(art["relative_path"])
            if ".partial" in rel:
                raise S10FullApplyJobError(
                    f"STITCH_LAYER_ARTIFACT_MISSING: artifact {aid} is "
                    ".partial (fail closed)"
                )
            abs_p = _lp(managed_root / rel)
            if not abs_p.is_file():
                raise S10FullApplyJobError(
                    f"STITCH_LAYER_ARTIFACT_MISSING: stitch missing file {rel} "
                    "(fail closed)"
                )
            artifact_sha = str(art["sha256"])
            artifact_size = int(art["size_bytes"])
            chunk_frames = decode_rgb_frames(abs_p)
        expected_len = end - start + 1
        if len(chunk_frames) != expected_len:
            raise S10FullApplyJobError(
                f"STITCH_LAYER_ARTIFACT_MISSING: layer {layer_id!r} artifact "
                f"decodes to {len(chunk_frames)} frames; expected "
                f"{expected_len} (fail closed)"
            )

        region = [float(v) for v in m["affected_region"]]
        rx0, ry0, rx1, ry1 = _region_px(
            (region[0], region[1], region[2], region[3]), frame_w, frame_h
        )
        sampled = [start] if start == end else [start, end]
        before_crops = [buffer_frames[f][ry0:ry1, rx0:rx1].copy() for f in sampled]
        before_hash = _crops_sha256(before_crops)

        _compose_layer_unit(
            svc=svc,
            unit=unit,
            buffer_frames=buffer_frames,
            managed_root=managed_root,
            source_media=source_media,
            output_dir=composition_dir,
            fps_num=fps_num,
            fps_den=fps_den,
            workspace_id=ws,
            project_id=str(manifest.get("project_id") or ""),
            video_item_id=str(manifest.get("video_item_id") or ""),
        )

        after_crops = [buffer_frames[f][ry0:ry1, rx0:rx1].copy() for f in sampled]
        after_hash = _crops_sha256(after_crops)
        changed = 0
        for before_crop, after_crop in zip(before_crops, after_crops):
            changed += int(np.any(before_crop != after_crop, axis=2).sum())
        area = max((rx1 - rx0) * (ry1 - ry0), 1)
        changed_ratio = changed / float(area * len(sampled))
        row = {
            "shot_id": unit["shot_id"],
            "range": [start, end],
            "layer_id": layer_id,
            "role_id": str(m.get("role_id") or layer_id),
            "route": str(unit["route"]),
            "visibility": str(m["visibility"]),
            "z_order": int(m["z_order"]),
            "artifact_sha256": artifact_sha,
            "artifact_size_bytes": artifact_size,
            "region_norm": region,
            "region_px": [int(rx0), int(ry0), int(rx1), int(ry1)],
            "sampled_frames": sampled,
            "region_crop_sha256_before": before_hash,
            "region_crop_sha256_after": after_hash,
            "final_crop_sha256": None,
            "changed_pixel_count": int(changed),
            "changed_ratio": float(changed_ratio),
            "threshold": 0.01,
            "verdict": "contributed" if changed_ratio >= 0.01 else "no_delta",
        }
        per_layer_evidence.append(row)
        final_crop_specs.append((row, (rx0, ry0, rx1, ry1), sampled))

    # ── Q9 acceptance: every unit proved; no_delta is a failure ──────────
    if len(per_layer_evidence) != len(chunks):
        raise S10FullApplyJobError(
            f"STITCH_LAYER_EVIDENCE_MISSING: {len(per_layer_evidence)} "
            f"evidence rows for {len(chunks)} active units (fail closed)"
        )
    no_delta = [r for r in per_layer_evidence if r["verdict"] != "contributed"]
    if no_delta:
        raise S10FullApplyJobError(
            "STITCH_LAYER_EVIDENCE_MISSING: layers without decoded-region "
            "contribution "
            + ", ".join(
                f"{r['layer_id']}@{r['range']} ratio={r['changed_ratio']:.6f}"
                for r in no_delta
            )
            + " (dropped/not composited — fail closed, no publication)"
        )

    for row, (rx0, ry0, rx1, ry1), sampled in final_crop_specs:
        row["final_crop_sha256"] = _crops_sha256(
            [buffer_frames[f][ry0:ry1, rx0:rx1] for f in sampled]
        )

    total = len(buffer_frames)
    if total != expected_frame_count:
        raise S10FullApplyJobError(
            f"STITCH_FRAME_COVERAGE_MISMATCH: composed {total} frames; "
            f"timeline frame_count is {expected_frame_count}"
        )
    fps = fps_num / fps_den if fps_den else 30.0
    stitch_hash = hashlib.sha256(
        f"stitch:{run_id}:{total}:{fps_num}/{fps_den}".encode()
    ).hexdigest()[:12]
    stitch_rel = Path(f"s10_full_apply/{run_id}/full_{stitch_hash}.mp4")
    abs_out = _lp(managed_root / stitch_rel)
    abs_out.parent.mkdir(parents=True, exist_ok=True)
    write_frames_mp4(buffer_frames, abs_out, fps=fps)
    sha = hash_file(abs_out)
    size = abs_out.stat().st_size
    metadata = {
        "frame_count": total,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "shot_order": [str(s.get("shot_id")) for s in shots],
        "cuts": [],
        "timebase": f"{fps_num}/{fps_den}",
        "per_layer_evidence": per_layer_evidence,
    }
    return stitch_rel, sha, size, metadata


# ── MF-END-19: shot-level (comfy) execution branch ───────────────────────────


def _execution_backend_of(run_row: dict[str, Any]) -> dict[str, Any]:
    """The run's validated execution-backend manifest ({} => legacy default)."""
    cfg = run_row.get("chunk_config") or {}
    if isinstance(cfg, dict):
        backend = cfg.get("execution_backend")
        if isinstance(backend, dict):
            return dict(backend)
    return {}


def _shot_anchor_pin(backend: dict[str, Any], shot_id: str) -> dict[str, Any]:
    """The shot's digest-pinned start anchor from the frozen backend manifest."""
    anchors = backend.get("shot_anchors")
    if not isinstance(anchors, dict) or shot_id not in anchors:
        raise S10FullApplyJobError(
            f"the run's execution backend pins no start anchor for shot {shot_id!r} "
            "(shot_anchors[shot_id] is a frozen plan input; fail closed)"
        )
    entry = anchors.get(shot_id)
    if not isinstance(entry, dict):
        raise S10FullApplyJobError(f"shot_anchors[{shot_id!r}] must be an object")
    return entry


def _shot_chunk_identity(chunk: dict[str, Any]) -> tuple[str, str]:
    """The canonical (shot_id, chunk_id) of one plan chunk row (fail closed).

    The DB row carries the planner's canonical ``ck_...`` id inside
    ``natural_key`` (``s10_chunk:<run>:<ck_...>``); a row with neither
    identity refuses — the comfy branch never invents an id.
    """
    shot_id = str(chunk.get("shot_id") or "")
    chunk_id = str(chunk.get("chunk_id") or "")
    if not chunk_id:
        natural = str(chunk.get("natural_key") or "")
        if natural.startswith("s10_chunk:"):
            chunk_id = natural.split(":", 2)[-1]
    if not shot_id or not chunk_id:
        raise S10FullApplyJobError("comfy chunk lacks shot_id/chunk_id identity")
    return shot_id, chunk_id


def _render_shot_chunk_via_engine(
    *,
    managed_root: Path,
    run_id: str,
    chunk: dict[str, Any],
    chunk_index: int,
    fps_num: int,
    fps_den: int,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    authority: dict[str, Any],
    manifest: dict[str, Any],
    backend: dict[str, Any],
    session_factory: Any = None,
    retry: bool = False,
) -> tuple[Path, str, int, dict[str, Any]]:
    """Render one whole-shot/GROUP chunk through the shot-level engine (19.3).

    All identities come from the verified plan/authority; the request carries
    INPUTS ONLY (the outputs/prompt_id come from the engine call itself, never
    from the payload).  The executor writes the durable execution record
    (prompt_id + output hashes) and this function re-verifies the produced
    bytes before returning the frozen evidence shape.
    """
    if _run_shot_render is None or _select_shot_profile is None:
        raise S10FullApplyJobError("shot_reskin_executor not available")
    shot_id, chunk_id = _shot_chunk_identity(chunk)
    core_start = int(chunk.get("core_start_frame", 0))
    core_end = int(chunk.get("core_end_frame", core_start))
    if core_end < core_start:
        raise S10FullApplyJobError(f"bad core range {core_start}-{core_end}")
    member_layer_ids = [str(m) for m in (chunk.get("member_layer_ids") or [])]
    if not member_layer_ids:
        raise S10FullApplyJobError(
            f"comfy chunk {chunk_id!r} carries no member_layer_ids (the whole-shot/group "
            "plan is required; fail closed)"
        )
    mapping_by_layer = _authoritative_mapping_by_layer(authority)
    _ = chunk_index
    # Source media must exist + be digest-pinned (fail closed before staging).
    _load_source_media(managed_root, manifest)
    source_sha = str(manifest["source_media_sha256"]).lower()
    source_size = manifest.get("source_media_size_bytes")
    source_artifact_id = str(manifest.get("source_artifact_id") or source_sha[:32])
    cast: list[dict[str, Any]] = []
    for layer_id in member_layer_ids:
        if layer_id not in mapping_by_layer:
            raise S10FullApplyJobError(f"layer {layer_id!r} not present in authority mapping")
        _load_replacement_asset(managed_root, manifest, layer_id)
        entry = (manifest.get("replacement_assets") or {}).get(layer_id) or {}
        cast.append(
            {
                "role": layer_id,
                "character_id": str(mapping_by_layer[layer_id].get("role_id") or layer_id),
                "pack_version_id": str(mapping_by_layer[layer_id]["pack_version"]),
                "references": [
                    {
                        "key": f"{layer_id}@base",
                        "artifact_id": str(entry.get("artifact_id") or ""),
                        "kind": "image",
                        "sha256": str(entry.get("sha256") or "").lower(),
                        "store_relative_path": str(entry.get("rel") or ""),
                        "size_bytes": entry.get("size_bytes"),
                    }
                ],
            }
        )
    anchor_entry = _shot_anchor_pin(backend, shot_id)
    anchor_rel = str(anchor_entry.get("relative_path") or "")
    anchor_sha = str(anchor_entry.get("sha256") or "")
    if not anchor_rel or len(anchor_sha) != 64:
        raise S10FullApplyJobError(
            f"shot {shot_id!r} anchor pin is incomplete (relative_path+sha256 required)"
        )
    prompt = (backend.get("shot_prompts") or {}).get(shot_id)
    if not isinstance(prompt, str) or not prompt:
        raise S10FullApplyJobError(
            f"shot {shot_id!r} has no frozen prompt in the run's execution backend "
            "(fail closed)"
        )
    profile = _select_shot_profile(str(backend.get("profile_id") or ""))
    params = profile.get("params") or {}
    dims = list(params.get("native_output_dims") or [640, 368])
    request: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_id": video_item_id,
        "shot_id": shot_id,
        "chunk_id": chunk_id,
        "attempt_id": f"shot-{run_id[:8]}-{chunk_id[:12]}",
        "backend": backend,
        "graph": {
            "file": str(backend.get("graph_file") or profile.get("graph_file") or ""),
            "file_sha256": str(backend.get("graph_sha256") or ""),
        },
        "parameters": {
            "prompt": prompt,
            "filename_prefix": f"s10_full_apply/{run_id}/{shot_id}",
        },
        "staged_inputs": {"anchor": {"relative_path": anchor_rel, "sha256": anchor_sha}},
        "anchor": {"relative_path": anchor_rel, "sha256": anchor_sha},
        "cast": cast,
        "source": {
            "artifact_id": source_artifact_id,
            "sha256": source_sha,
            "relative_path": str(manifest.get("source_media_rel") or ""),
            "size_bytes": source_size if isinstance(source_size, int) else None,
            "fps": {"num": fps_num, "den": fps_den},
            "span": {"start_frame": core_start, "end_frame_exclusive": core_end + 1},
        },
        "output_contract": {
            "width": int(dims[0]),
            "height": int(dims[1]),
            "fps_num": fps_num,
            "fps_den": fps_den,
            "frame_count": core_end - core_start + 1,
            "container": "mp4",
            "video_codec": "h264",
            "audio": {"mode": "source_remux", "source_artifact_id": source_artifact_id},
        },
        "budget": {
            "resource_class": "gpu_12gb",
            "max_wall_seconds": float(manifest.get("shot_render_max_wall_s") or 900.0),
        },
        "require_accepted_anchor": bool(backend.get("require_accepted_anchor")),
        "anchor_identity_digest": None,
    }
    if backend.get("seed") is not None:
        request["parameters"]["seed"] = int(backend["seed"])
    # MF-END-20: the shot render goes through the content-keyed cache.  A
    # replay of an identical request NEVER issues a second engine POST; a
    # restart AFTER submit (in-doubt) refuses instead of re-POSTing the same
    # attempt, and a cancelled/superseded attempt never pins a late output.
    cache_hit = False
    cache_info: dict[str, Any] = {}
    if session_factory is not None and _run_cached_shot_render is not None:
        try:
            outcome = _run_cached_shot_render(
                session_factory=session_factory,
                managed_root=managed_root,
                workspace_id=workspace_id,
                run_id=run_id,
                request=request,
                retry=bool(retry),
                is_cancelled=None,
                render=lambda: _run_shot_render(managed_root=managed_root, request=request),
            )
        except _ShotCacheRefusal as exc:
            raise S10FullApplyJobError(
                f"shot render cache refused ({exc.code.value}): {exc.detail}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — executor refusals are terminal here
            code = getattr(exc, "code", None)
            code_value = getattr(code, "value", None) or code
            raise S10FullApplyJobError(
                f"shot render refused/failed ({code_value or type(exc).__name__}): {exc}"
            ) from exc
        cache_hit = bool(outcome.get("cache_hit"))
        cache_receipt = dict(outcome.get("receipt") or {})
        cache_info = {
            "hit": cache_hit,
            "content_key": str(outcome.get("content_key") or ""),
            "receipt_id": str(cache_receipt.get("receipt_id") or ""),
            "attempt_row_id": str(cache_receipt.get("attempt_row_id") or ""),
        }
        if cache_hit:
            rel = Path(str(cache_receipt.get("output_relative_path") or ""))
            sha = str(cache_receipt.get("output_sha256") or "")
            size = int(cache_receipt.get("output_size_bytes") or 0)
            abs_hit = _lp(managed_root / rel)
            if not rel.name or not abs_hit.is_file() or hash_file(abs_hit) != sha:
                raise S10FullApplyJobError(
                    f"cached shot render receipt is stale on disk: {rel} (fail closed)"
                )
            evidence = {
                "decoded_sha256": str(cache_receipt.get("decoded_sha256") or ""),
                "decoded_frame_count": int(cache_receipt.get("decoded_frame_count") or 0),
                "fps_num": int(cache_receipt.get("fps_num") or fps_num),
                "fps_den": int(cache_receipt.get("fps_den") or fps_den),
                "layer_id": str(chunk.get("layer_id") or ""),
                "shot_id": shot_id,
                "route": "shot_group",
                "effective_adapter": "comfy_shot_engine",
                "prompt_id": str(cache_receipt.get("prompt_id") or ""),
                "graph_object_sha256_submitted": str(
                    cache_receipt.get("graph_object_sha256_submitted") or ""
                ),
                "cache": cache_info,
            }
            return rel, sha, size, evidence
        result = dict(outcome.get("result") or {})
    else:
        try:
            result = _run_shot_render(managed_root=managed_root, request=request)
        except Exception as exc:  # noqa: BLE001 — executor refusals are terminal here
            code = getattr(exc, "code", None)
            code_value = getattr(code, "value", None) or code
            raise S10FullApplyJobError(
                f"shot render refused/failed ({code_value or type(exc).__name__}): {exc}"
            ) from exc
    rel = Path(str(result["output_relative_path"]))
    sha = str(result["output_sha256"])
    size = int(result["output_size_bytes"])
    abs_out = _lp(managed_root / rel)
    if not abs_out.is_file() or hash_file(abs_out) != sha:
        raise S10FullApplyJobError(f"shot render output vanished/drifted: {rel}")
    evidence = {
        "decoded_sha256": str(result["decoded_sha256"]),
        "decoded_frame_count": int(result["decoded_frame_count"]),
        "fps_num": int(result["fps_num"]),
        "fps_den": int(result["fps_den"]),
        "layer_id": str(chunk.get("layer_id") or ""),
        "shot_id": shot_id,
        "route": "shot_group",
        "effective_adapter": "comfy_shot_engine",
        "prompt_id": str(result.get("prompt_id") or ""),
        "graph_object_sha256_submitted": str(result.get("graph_object_sha256_submitted") or ""),
        "shot_render_record": dict(result.get("record") or {}),
        "window": dict(result.get("window") or {}),
        "cache": cache_info,
    }
    return rel, sha, size, evidence


def _stitch_shot_chunks(
    *,
    managed_root: Path,
    run_id: str,
    chunks: list[dict[str, Any]],
    session_factory: Any,
    ws: str,
    fps_num: int,
    fps_den: int,
    authority: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    frame_count: int | None = None,
) -> tuple[Path, str, int, dict[str, Any]]:
    """Stitch verified whole-shot chunks into one playable MP4 (19.4).

    Frame-accurate timeline assembly: every frame covered by a verified chunk
    comes from that chunk's generated bytes; ranges with no active chunk keep
    the SOURCE frames verbatim.  Publication-grade gates: EVERY chunk of the
    run must be present + verified + byte-usable (missing/stale/invalid =>
    fail closed, zero publication), at least one frame must be GENERATED, and
    the stitched file must NOT be the source bytes — the source is never
    returned as a successful output.
    """
    from app.services.renderer_routes.composite import (  # noqa: PLC0415
        canonical_frame_sha256,
        decode_rgb_frames,
        write_frames_mp4,
    )

    if not isinstance(authority, dict) or not isinstance(manifest, dict):
        raise S10FullApplyJobError(
            "STITCH_CHUNK_EVIDENCE_MISSING: stitching requires the frozen authority "
            "+ manifest pins (fail closed)"
        )
    ordered = sorted(
        chunks, key=lambda c: (int(c.get("core_start_frame", 0)), str(c.get("chunk_id")))
    )
    if not ordered:
        raise S10FullApplyJobError("STITCH_NO_CHUNKS: zero chunks cannot publish")
    source_media = _load_source_media(managed_root, manifest)
    src_frames = list(decode_rgb_frames(source_media))
    expected = int(frame_count or 0) or len(src_frames)
    if len(src_frames) != expected:
        raise S10FullApplyJobError(
            f"STITCH_FRAME_COVERAGE_MISMATCH: source decodes to {len(src_frames)} "
            f"frames; timeline frame_count is {expected}"
        )
    timeline: list[Any] = [None] * expected
    per_chunk: list[dict[str, Any]] = []
    for ch in ordered:
        chunk_id = str(ch.get("chunk_id"))
        if not bool(ch.get("verified")):
            raise S10FullApplyJobError(
                f"STITCH_CHUNK_NOT_VERIFIED: chunk {chunk_id} is not verified "
                "(missing required chunk; fail closed)"
            )
        if not _chunk_artifact_usable(
            session_factory, ws, ch, managed_root, fps_num, fps_den
        ):
            raise S10FullApplyJobError(
                f"STITCH_CHUNK_ARTIFACT_INVALID: chunk {chunk_id} artifact is "
                "missing/tampered/stale (fail closed)"
            )
        with session_factory() as s:
            row = s.execute(
                sa_text(
                    "SELECT relative_path, sha256, size_bytes FROM artifact WHERE id=:aid"
                ),
                {"aid": str(ch.get("artifact_id"))},
            ).mappings().first()
        if row is None:
            raise S10FullApplyJobError(
                f"STITCH_CHUNK_ARTIFACT_INVALID: no artifact row for chunk {chunk_id}"
            )
        if str(row["sha256"]) == hash_file(source_media):
            raise S10FullApplyJobError(
                f"STITCH_CHUNK_IS_SOURCE: chunk {chunk_id} bytes are the source media "
                "itself — the source is never returned as the output (fail closed)"
            )
        abs_chunk = _lp(managed_root / str(row["relative_path"]))
        frames = list(decode_rgb_frames(abs_chunk))
        c_start = int(ch.get("core_start_frame"))
        c_end = int(ch.get("core_end_frame"))
        want = c_end - c_start + 1
        if len(frames) != want:
            raise S10FullApplyJobError(
                f"STITCH_FRAME_COVERAGE_MISMATCH: chunk {chunk_id} decodes to "
                f"{len(frames)} frames; core range wants {want}"
            )
        for i, frame in enumerate(frames):
            idx = c_start + i
            if idx < 0 or idx >= expected:
                raise S10FullApplyJobError(
                    f"STITCH_FRAME_COVERAGE_MISMATCH: chunk {chunk_id} frame {idx} "
                    f"is outside the timeline ({expected} frames)"
                )
            if timeline[idx] is not None:
                raise S10FullApplyJobError(
                    f"STITCH_FRAME_OVERLAP: frame {idx} is covered by more than one "
                    "chunk (fail closed)"
                )
            timeline[idx] = frame
        per_chunk.append(
            {
                "chunk_id": chunk_id,
                "shot_id": ch.get("shot_id"),
                "core_start_frame": c_start,
                "core_end_frame": c_end,
                "artifact_sha256": str(row["sha256"]),
                "artifact_size_bytes": int(row["size_bytes"] or 0),
                "decoded_frame_count": len(frames),
                "decoded_sha256": canonical_frame_sha256(frames),
            }
        )
    generated = sum(1 for f in timeline if f is not None)
    if generated <= 0:
        raise S10FullApplyJobError(
            "STITCH_NO_GENERATED_FRAMES: every frame would be source — refusing to "
            "publish the source as the output"
        )
    for idx, frame in enumerate(timeline):
        if frame is None:
            timeline[idx] = src_frames[idx]
    rel = Path(f"s10_full_apply/{run_id}/stitch_shot_chunks.mp4")
    abs_out = _lp(managed_root / rel)
    abs_out.parent.mkdir(parents=True, exist_ok=True)
    write_frames_mp4(timeline, abs_out, fps=float(fps_num) / float(fps_den))
    if not abs_out.is_file() or abs_out.stat().st_size <= 0:
        raise S10FullApplyJobError("STITCH_OUTPUT_MISSING: stitched file was not written")
    stitch_sha = hash_file(abs_out)
    if stitch_sha == hash_file(source_media):
        raise S10FullApplyJobError(
            "STITCH_SOURCE_RETURNED_AS_OUTPUT: the stitched output is byte-identical "
            "to the source media (fail closed)"
        )
    meta = {
        "frame_count": expected,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "generated_frames": generated,
        "source_frames_verbatim": expected - generated,
        "per_chunk_evidence": per_chunk,
        "backend": "comfy_shot_engine",
    }
    return rel, stitch_sha, abs_out.stat().st_size, meta


def s10_full_apply_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Durable step handler — real chunk execution with checkpoint/resume + stitch + publication.

    Input manifest (server-built) must contain:
      run_id, workspace_id, project_id, managed_root, render_authority,
      source_media_rel, source_media_sha256, replacement_assets

    Checkpoint shape (fenced, versioned):
      {schema_version:1, run_id, next_chunk_index:int, executed:int[]}

    Each chunk is rendered via the corrected T02 executor with authoritative
    identities, written atomically, validated decodable with exact frame count +
    probed timebase + evidence content hash, and checkpointed BEFORE the next
    chunk.  Tampered/.partial/missing/stale/undecodable outputs are
    quarantined/recomputed and never advance the checkpoint.  After all verified
    core chunks, a deterministic stitched full-video + exactly ONE completed
    publication is produced.  Zero chunks, missing source/asset/mapping, and a
    caller-supplied `stop_after_chunk` manifest key all fail closed.
    """
    manifest = dict(ctx.input_manifest or {})
    run_id = str(manifest.get("run_id") or manifest.get("s10_run_id") or "")
    ws = str(manifest.get("workspace_id") or ctx.workspace_id or "")
    project_id = str(manifest.get("project_id") or "")
    video_item_id = str(manifest.get("video_item_id") or "")
    if not run_id or not ws:
        raise S10FullApplyJobError("input_manifest missing run_id/workspace_id")

    cp = dict(ctx.checkpoint or {})
    if "next_chunk_index" not in cp:
        cp = {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": 0, "executed": []}
    if cp.get("schema_version") != S10_CP_VERSION:
        cp["schema_version"] = S10_CP_VERSION
    next_idx: int = int(cp.get("next_chunk_index", 0))
    executed: list[int] = list(cp.get("executed") or [])

    session_factory = ctx.session_factory
    if session_factory is None:
        raise S10FullApplyJobError("worker context has no session_factory")

    managed_root: Path | None = None
    mr_raw = manifest.get("managed_root")
    if isinstance(mr_raw, str) and mr_raw:
        managed_root = Path(mr_raw)
    else:
        try:
            from app.api import deps as _deps  # noqa: PLC0415

            managed_root = _deps.get_managed_root()
        except Exception:
            managed_root = ctx.staging_dir().parent
    if managed_root is None:
        raise S10FullApplyJobError("managed_root unavailable")
    # C6 req 5: normalize the managed root ONCE to the Windows extended-length
    # form.  ``force=True`` applies the \\\\?\\ prefix on Windows regardless of
    # length so the root and EVERY derived child (workspace_root, output_media,
    # evidence, staging) share the SAME path form — otherwise a root just under
    # MAX_PATH yields prefixed children but an unprefixed workspace_root, which
    # breaks the renderer contract's containment check (mixed-form
    # relative_to raises).  cv2/evidence I/O then survive >260-char nesting.
    managed_root = _lp(managed_root, force=True)

    fps_num = 30
    fps_den = 1
    run_row: dict[str, Any] = {}
    try:
        with session_factory() as _s:
            row = _s.execute(
                sa_text(
                    "SELECT fps_num, fps_den, frame_count, plan_id, plan_hash, status, video_item_id, project_id, chunk_config_json "
                    "FROM s10_full_apply_run WHERE id=:rid AND workspace_id=:ws"
                ),
                {"rid": run_id, "ws": ws},
            ).mappings().first()
            if row is not None:
                run_row = dict(row)
                if row["fps_num"] is not None:
                    fps_num = int(row["fps_num"])
                if row["fps_den"] is not None:
                    fps_den = int(row["fps_den"])
    except Exception:
        pass
    if not run_row:
        raise S10FullApplyJobError(f"run {run_id!r} not found in workspace")
    if not project_id:
        project_id = str(run_row.get("project_id") or "")
    if not video_item_id:
        video_item_id = str(run_row.get("video_item_id") or "")
    if not project_id or not video_item_id:
        raise S10FullApplyJobError("workspace/project/video identities incomplete (fail closed)")
    run_chunk_config_raw = run_row.get("chunk_config_json")
    try:
        run_row["chunk_config"] = json.loads(run_chunk_config_raw) if run_chunk_config_raw else {}
    except Exception:
        run_row["chunk_config"] = {}

    # C1-F5: caller-controlled crash-hook injection is rejected, never honored.
    if "stop_after_chunk" in manifest:
        _mark_run_status(session_factory, ws, run_id, "failed")
        raise S10FullApplyJobError(
            "production manifest must not carry stop_after_chunk (caller crash-hook injection rejected)"
        )

    # MF-END-19.4: prompt ids / outputs / publications NEVER come from the
    # payload, the job manifest or a checkpoint — the engine call produces
    # them.  A manifest that tries to carry an output bypasses the public
    # render authority and is rejected before any work.
    for _forbidden in ("prompt_id", "render_outputs", "output_artifact", "publications"):
        if _forbidden in manifest:
            _mark_run_status(session_factory, ws, run_id, "failed")
            raise S10FullApplyJobError(
                f"manifest must not carry {_forbidden!r} — prompt ids/outputs/"
                "publications come from the engine call, never from the payload"
            )

    # C4: verify the canonical server-side render authority + plan pin BEFORE
    # work.  C8: the worker ALSO re-derives the authority fingerprint from the
    # persisted v2 row (fence mutation/tamper before render/publication).
    # Authority failure is fail-closed: the run is marked failed, zero render.
    try:
        authority = _require_manifest_authority(
            manifest,
            run_row,
            session_factory=session_factory,
            workspace_id=ws,
            checkpoint_id=str(manifest.get("apply_checkpoint_id") or ""),
        )
    except S10FullApplyJobError:
        _mark_run_status(session_factory, ws, run_id, "failed")
        raise

    _mark_run_status(session_factory, ws, run_id, "running")
    # MF-END-20: a durable RETRY (pipeline attempt > 1) is the only writer
    # allowed to supersede an in-doubt shot-cache submit; a bare restart of
    # attempt 1 never re-POSTs.
    pipeline_retry = int(getattr(ctx, "attempt", 1) or 1) > 1
    # MF-END-19: the run's frozen execution-backend manifest decides whether
    # each chunk renders through the shot-level engine (whole-shot/GROUP plan)
    # or keeps the legacy per-layer route executor.  Absent manifest => legacy.
    backend_manifest = _execution_backend_of(run_row)
    comfy_shot_mode = str(backend_manifest.get("backend") or "") == "comfy_shot_engine"
    chunks = _list_chunks(session_factory, ws, run_id)
    if not chunks:
        # C1-F5: empty run is fail-closed/non-completed — never mark completed.
        _mark_run_status(session_factory, ws, run_id, "failed")
        ctx.write_checkpoint({"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": 0, "executed": executed})
        raise S10FullApplyJobError("zero chunks — run cannot complete without exactly one verified publication")

    total = len(chunks)
    resumed = next_idx > 0
    rendered: list[dict[str, Any]] = []

    for idx in range(next_idx, total):
        if ctx.is_cancelled():
            ctx.write_checkpoint(
                {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": idx, "executed": executed}
            )
            _mark_run_status(session_factory, ws, run_id, "cancelled")
            raise _CancelledError(f"cancelled at chunk {idx}")

        ch = chunks[idx]
        chunk_id: str = str(ch["id"])
        verified = bool(ch.get("verified"))
        content_hash: str = str(ch.get("content_hash") or "")
        if verified:
            if _chunk_artifact_usable(session_factory, ws, ch, managed_root, fps_num, fps_den):
                executed.append(idx)
                ctx.write_checkpoint(
                    {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": idx + 1, "executed": executed}
                )
                rendered.append({"chunk_id": chunk_id, "skipped": True, "verified_reused": True})
                continue
            _quarantine_chunk(session_factory, ws, ch, managed_root)

        _mark_chunk_state(session_factory, ws, chunk_id, "running")

        try:
            if comfy_shot_mode:
                rel, sha, size, evidence = _render_shot_chunk_via_engine(
                    managed_root=managed_root,
                    run_id=run_id,
                    chunk=ch,
                    chunk_index=idx,
                    fps_num=fps_num,
                    fps_den=fps_den,
                    workspace_id=ws,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    authority=authority,
                    manifest=manifest,
                    backend=backend_manifest,
                    session_factory=session_factory,
                    retry=pipeline_retry,
                )
            else:
                rel, sha, size, evidence = _render_chunk_via_real_executor(
                    managed_root=managed_root,
                    run_id=run_id,
                    chunk=ch,
                    chunk_index=idx,
                    fps_num=fps_num,
                    fps_den=fps_den,
                    workspace_id=ws,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    authority=authority,
                    manifest=manifest,
                )
        except S10FullApplyJobError:
            _mark_chunk_state(session_factory, ws, chunk_id, "failed")
            _mark_run_status(session_factory, ws, run_id, "failed")
            raise
        artifact_id = _create_artifact_and_verify(
            session_factory, ws, managed_root, rel, sha, size, chunk_id, content_hash, evidence
        )

        executed.append(idx)
        ctx.write_checkpoint(
            {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": idx + 1, "executed": executed}
        )
        try:
            ctx.progress(float(idx + 1) / float(total), f"chunk {idx + 1}/{total}")
        except Exception:
            pass
        rendered.append(
            {"chunk_id": chunk_id, "artifact_id": artifact_id, "sha256": sha, "size_bytes": size, "relative_path": str(rel), "evidence": evidence}
        )

        # Test-owned crash/restart injection (module global, never from manifest).
        if _TEST_STOP_AFTER_CHUNK is not None and idx == _TEST_STOP_AFTER_CHUNK:
            _mark_run_status(session_factory, ws, run_id, "running")
            raise _MidRunStop(f"simulated stop after chunk {idx}")
        time.sleep(0.01)

    # S10-C6A F2 fence (pre-stitch/pre-publication): a durable cancel that
    # landed during the chunk loop must stop here — no stitch, no publication,
    # no completion (cancel wins, contract §6.2/§6.3).
    if ctx.is_cancelled():
        ctx.write_checkpoint(
            {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": total, "executed": executed}
        )
        _mark_run_status(session_factory, ws, run_id, "cancelled")
        raise _CancelledError(f"cancelled before stitch/publication ({total} chunks checkpointed)")

    try:
        with session_factory() as _s:
            pub_rows = _s.execute(
                sa_text("SELECT id, state FROM s10_full_apply_publication WHERE run_id=:rid AND workspace_id=:ws"),
                {"rid": run_id, "ws": ws},
            ).mappings().all()
            has_completed = any(r["state"] == "completed" for r in pub_rows)
    except Exception:
        has_completed = False
    if not has_completed:
        # MF-END-20: publication-time guard — the run's pinned shot receipts
        # must still be byte-live.  A tampered/missing receipt artifact refuses
        # the publication (replay never publishes drifted bytes).
        if comfy_shot_mode and _ShotReskinCache is not None:
            try:
                with session_factory() as _guard_sess:
                    _guard = _ShotReskinCache(_guard_sess, managed_root=managed_root)
                    _guard.assert_run_receipts_live(workspace_id=ws, run_id=run_id)
            except _ShotCacheRefusal as exc:
                _mark_run_status(session_factory, ws, run_id, "failed")
                raise S10FullApplyJobError(
                    f"publication refused by the shot cache guard ({exc.code.value}): {exc.detail}"
                ) from exc
        try:
            all_chunks = _list_chunks(session_factory, ws, run_id)
            # MF-END-19.4: the shot-level backend stitches frame-accurate whole-
            # shot chunks (every required chunk present + verified, never the
            # source as the output); the legacy backend keeps the per-layer
            # composition contract.
            _stitch_fn = _stitch_shot_chunks if comfy_shot_mode else _stitch_verified_chunks
            stitch_rel, stitch_sha, stitch_size, stitch_meta = _stitch_fn(
                managed_root=managed_root,
                run_id=run_id,
                chunks=all_chunks,
                session_factory=session_factory,
                ws=ws,
                fps_num=fps_num,
                fps_den=fps_den,
                authority=authority,
                manifest=manifest,
                frame_count=int(run_row.get("frame_count") or 0) or None,
            )
        except Exception as exc:
            _mark_run_status(session_factory, ws, run_id, "failed")
            raise S10FullApplyJobError(f"stitch failed: {exc}") from exc
        # S10-C6A F2 fence (pre-publication): a durable cancel that landed
        # during the stitch keeps the stitch file on disk but must NEVER
        # produce a publication row or a completed run (cancel wins).
        if ctx.is_cancelled():
            ctx.write_checkpoint(
                {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": total, "executed": executed}
            )
            _mark_run_status(session_factory, ws, run_id, "cancelled")
            raise _CancelledError("cancelled after stitch, before publication — publication withheld")

        # S10-C6A F2 / S10-C10 F2: publication + run completion commit as ONE
        # CAS-first transaction using the SHARED verified CAS contract — the
        # gated completion UPDATE + status re-read run in THIS transaction
        # (via the helper operating on the same session), so both branches
        # share one undrifted CAS-result contract.  On the cancel path the
        # UPDATE matches zero rows, NO publication row is inserted and the
        # transaction is never committed — a cancelled run cannot gain a
        # completed publication by construction.
        with session_factory() as pub_sess:
            pub_sess.execute(
                sa_text(
                    "UPDATE s10_full_apply_run SET status='completed', updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=:rid AND workspace_id=:ws AND status != 'cancelled'"
                ),
                {"rid": run_id, "ws": ws},
            )
            gated = pub_sess.execute(
                sa_text("SELECT status FROM s10_full_apply_run WHERE id=:rid AND workspace_id=:ws"),
                {"rid": run_id, "ws": ws},
            ).mappings().first()
            if gated is None or str(gated["status"]) != "completed":
                # CAS gate matched zero rows — the run was cancelled while the
                # stitch ran.  Roll the (uncommitted) publication back and
                # fail the attempt as cancelled; the cancelled run never
                # gains a publication.
                pub_sess.rollback()
                ctx.write_checkpoint(
                    {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": total, "executed": executed}
                )
                raise _CancelledError("cancelled before completion — publication withheld (CAS gate)")
            _create_full_publication(
                session_factory,
                ws,
                run_id,
                managed_root,
                stitch_rel,
                stitch_sha,
                stitch_size,
                stitch_meta,
                session=pub_sess,
            )
            pub_sess.commit()
    else:
        # Resume path: the completed publication is already durable (worker
        # crashed between publication commit and completion write).  Complete
        # the run through the SAME verified CAS helper — a run cancelled in
        # the meantime is never completed (cancel wins).  Only a VERIFIED CAS
        # (True) may fall through to the completed checkpoint below.
        if ctx.is_cancelled():
            ctx.write_checkpoint(
                {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": total, "executed": executed}
            )
            _mark_run_status(session_factory, ws, run_id, "cancelled")
            raise _CancelledError("cancelled before completion — resume path completion withheld")
        if not _complete_run_cas(session_factory, ws, run_id):
            # S10-C10 F2: cancel landed between the pre-check and the CAS —
            # it WINS.  No completed checkpoint, no completion claim; the
            # durable job drains cancelling/cancelled via _CancelledError.
            ctx.write_checkpoint(
                {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": total, "executed": executed}
            )
            raise _CancelledError("cancelled before completion — resume path completion withheld (CAS)")

    ctx.write_checkpoint(
        {"schema_version": S10_CP_VERSION, "run_id": run_id, "next_chunk_index": total, "executed": executed, "completed": True}
    )
    return {
        "run_id": run_id,
        "chunks_total": total,
        "chunks_executed": len([r for r in rendered if not r.get("skipped")]),
        "rendered": rendered,
        "resumed": resumed,
    }


class _CancelledError(RuntimeError):
    pass


class _MidRunStop(RuntimeError):
    pass


def _mark_run_status(session_factory, ws: str, run_id: str, status: str) -> None:  # type: ignore[no-untyped-def]
    # S10-C6A F2 CAS gate: a run that is already cancelled stays cancelled -
    # late worker status writes (running/failed/completed after the durable
    # cancel landed) are dropped, so a cancelled run is never resurrected.
    # Writing ``cancelled`` itself still passes (source state != cancelled).
    with session_factory() as s:
        s.execute(
            sa_text(
                "UPDATE s10_full_apply_run SET status=:st, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=:rid AND workspace_id=:ws AND status != 'cancelled'"
            ),
            {"st": status, "rid": run_id, "ws": ws},
        )
        s.commit()


def _complete_run_cas(session_factory: Any, ws: str, run_id: str) -> bool:
    """S10-C10 F2: shared verified completion CAS used by BOTH completion branches.

    Executes the conditional run completion UPDATE and the status re-read in
    the SAME transaction, then commits — a durable cancel that lands between
    the caller's pre-check and this CAS matches zero rows and the run stays
    ``cancelled``.  Returns True only when the re-read proves the run is now
    ``completed``; False means the cancel won (caller must NOT write a
    completed checkpoint and must fail the attempt as cancelled).
    """
    with session_factory() as comp_sess:
        comp_sess.execute(
            sa_text(
                "UPDATE s10_full_apply_run SET status='completed', updated_at=CURRENT_TIMESTAMP "
                "WHERE id=:rid AND workspace_id=:ws AND status != 'cancelled'"
            ),
            {"rid": run_id, "ws": ws},
        )
        gated = comp_sess.execute(
            sa_text("SELECT status FROM s10_full_apply_run WHERE id=:rid AND workspace_id=:ws"),
            {"rid": run_id, "ws": ws},
        ).mappings().first()
        if gated is None or str(gated["status"]) != "completed":
            comp_sess.rollback()
            return False
        comp_sess.commit()
        return True


def _mark_chunk_state(session_factory, ws: str, chunk_id: str, state: str) -> None:  # type: ignore[no-untyped-def]
    with session_factory() as s:
        s.execute(
            sa_text("UPDATE s10_full_apply_chunk SET state=:st, updated_at=CURRENT_TIMESTAMP WHERE id=:cid AND workspace_id=:ws"),
            {"st": state, "cid": chunk_id, "ws": ws},
        )
        s.commit()


def _list_chunks(session_factory, ws: str, run_id: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    with session_factory() as s:
        rows = s.execute(
            sa_text(
                "SELECT id, chunk_index, order_index, shot_id, layer_id, object_role_id, core_start_frame, core_end_frame, overlap_before, overlap_after, content_hash, state, attempt, artifact_id, verified, natural_key, member_layer_ids_json FROM s10_full_apply_chunk WHERE workspace_id=:ws AND run_id=:rid ORDER BY order_index, chunk_index"
            ),
            {"ws": ws, "rid": run_id},
        ).mappings().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("member_layer_ids_json", None)
            members: list[str] = []
            if raw:
                try:
                    parsed = json.loads(raw)
                except (TypeError, ValueError):
                    parsed = None
                # DELTA-F1: ALL-or-NOTHING — a persisted array is trusted only
                # when EVERY entry is a non-empty string; anything else stays
                # EMPTY so the comfy branch fails closed instead of silently
                # rendering a partial cast (the guard is never widened).
                if isinstance(parsed, list) and all(
                    isinstance(m, str) and m for m in parsed
                ):
                    members = [str(m) for m in parsed]
            item["member_layer_ids"] = members
            out.append(item)
        return out


def _quarantine_chunk(session_factory, ws: str, ch: dict[str, Any], managed_root: Path | None = None) -> None:  # type: ignore[no-untyped-def]
    cid = str(ch.get("id"))
    aid = ch.get("artifact_id")
    with session_factory() as s:
        s.execute(
            sa_text("UPDATE s10_full_apply_chunk SET artifact_id=NULL, verified=0, state='pending', updated_at=CURRENT_TIMESTAMP WHERE id=:cid AND workspace_id=:ws"),
            {"cid": cid, "ws": ws},
        )
        if aid:
            art = s.execute(
                sa_text("SELECT relative_path FROM artifact WHERE id=:aid AND workspace_id=:ws"),
                {"aid": str(aid), "ws": ws},
            ).mappings().first()
            rel = str(art["relative_path"]) if art and art["relative_path"] else None
            if rel:
                try:
                    mr = managed_root
                    if mr is None:
                        try:
                            from app.api import deps as _deps  # noqa: PLC0415

                            mr = _deps.get_managed_root()
                        except Exception:
                            mr = None
                    if mr is not None:
                        fp = _lp(mr / rel)
                        if fp.is_file():
                            try:
                                fp.unlink()
                            except Exception:
                                pass
                        ev = _lp(mr / (str(rel) + ".evidence.json"))
                        if ev.is_file():
                            try:
                                ev.unlink()
                            except Exception:
                                pass
                except Exception:
                    pass
            s.execute(
                sa_text("DELETE FROM artifact WHERE id=:aid AND workspace_id=:ws"),
                {"aid": str(aid), "ws": ws},
            )
        s.commit()


def _chunk_artifact_usable(session_factory, ws: str, ch: dict[str, Any], managed_root: Path | None, fps_num: int, fps_den: int) -> bool:  # type: ignore[no-untyped-def]
    """Strict resume reuse gate (C4 req 5): exact SHA/size + decoded frame count +
    probed timebase + stored evidence content identity all match, otherwise False.
    """
    aid = ch.get("artifact_id")
    if not aid:
        return False
    with session_factory() as s:
        art = s.execute(
            sa_text("SELECT relative_path, state, workspace_id, sha256, size_bytes FROM artifact WHERE id=:aid"),
            {"aid": str(aid)},
        ).mappings().first()
        if art is None or str(art["workspace_id"]) != ws or str(art["state"]) != "ready":
            return False
        rel = str(art["relative_path"] or "")
        if ".partial" in rel:
            return False
        if art["sha256"] is None or art["size_bytes"] is None or int(art["size_bytes"]) <= 0:
            return False
        if managed_root is None:
            try:
                from app.api import deps as _deps  # noqa: PLC0415

                managed_root = _deps.get_managed_root()
            except Exception:
                return False
        assert managed_root is not None
        abs_path = _lp(managed_root / rel)
        if not abs_path.is_file():
            return False
        if abs_path.stat().st_size != int(art["size_bytes"]):
            return False
        try:
            file_sha = hash_file(abs_path)
        except Exception:
            return False
        if file_sha != str(art["sha256"]):
            return False
        try:
            from app.services.renderer_routes.composite import canonical_frame_sha256, decode_rgb_frames, probe_source_timebase
        except Exception:
            return False
        try:
            frames = decode_rgb_frames(abs_path)
            expected = int(ch.get("core_end_frame", 0)) - int(ch.get("core_start_frame", 0)) + 1
            if len(frames) != expected:
                return False
            probed = probe_source_timebase(abs_path)
            if probed != (fps_num, fps_den):
                return False
            content_sha = canonical_frame_sha256(frames)
        except Exception:
            return False
        # Evidence file must exist and pin the same decoded content identity.
        ev_path = _lp(managed_root / (rel + ".evidence.json"))
        if not ev_path.is_file():
            return False
        try:
            evidence = json.loads(ev_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(evidence, dict):
            return False
        if evidence.get("decoded_sha256") != content_sha:
            return False
        if int(evidence.get("decoded_frame_count", -1)) != expected:
            return False
        if int(evidence.get("fps_num", -1)) != fps_num or int(evidence.get("fps_den", -1)) != fps_den:
            return False
        stored_hash = str(ch.get("content_hash") or "")
        if not stored_hash or len(stored_hash) != 64:
            return False
        return True


def _create_artifact_and_verify(session_factory, ws: str, managed_root: Path, rel: Path, sha: str, size: int, chunk_id: str, content_hash: str, evidence: dict[str, Any]) -> str:  # type: ignore[no-untyped-def]
    import uuid as _uuid  # noqa: PLC0415

    artifact_id = str(_uuid.uuid4())
    with session_factory() as s:
        s.execute(
            sa_text(
                "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256, size_bytes, revision) VALUES (:id, :ws, 'video', :rel, 'ready', :sha, :sz, 1)"
            ),
            {"id": artifact_id, "ws": ws, "rel": str(rel), "sha": sha, "sz": size},
        )
        s.execute(
            sa_text(
                "UPDATE s10_full_apply_chunk SET artifact_id=:aid, verified=1, state='completed', content_hash=:ch, updated_at=CURRENT_TIMESTAMP WHERE id=:cid AND workspace_id=:ws"
            ),
            {"aid": artifact_id, "ch": content_hash, "cid": chunk_id, "ws": ws},
        )
        s.commit()
    # Persist decoded content identity next to the artifact (atomic managed write).
    _write_evidence_sidecar(
        managed_root,
        rel,
        {
            "decoded_sha256": evidence.get("decoded_sha256"),
            "decoded_frame_count": evidence.get("decoded_frame_count"),
            "fps_num": evidence.get("fps_num"),
            "fps_den": evidence.get("fps_den"),
            "layer_id": evidence.get("layer_id"),
            "shot_id": evidence.get("shot_id"),
            "route": evidence.get("route") or evidence.get("requested_route"),
            "effective_adapter": evidence.get("effective_adapter"),
            "artifact_sha256": sha,
            "artifact_size_bytes": size,
        },
    )
    return artifact_id


def _create_full_publication(session_factory, ws: str, run_id: str, managed_root: Path, stitch_rel: Path, stitch_sha: str, stitch_size: int, stitch_meta: dict[str, Any], session: Any = None) -> str:  # type: ignore[no-untyped-def]
    import hashlib as _hl
    import uuid as _uuid2

    pub_artifact_id = str(_uuid2.uuid4())
    # S10-C6A F2: when the caller supplies a session (CAS-first completion
    # transaction), every insert joins THAT transaction and commit is left to
    # the caller — publication + run-completion become one atomic unit.  The
    # legacy no-session path keeps the old per-step commit behavior.
    if session is not None:
        session.execute(
            sa_text(
                "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256, size_bytes, revision) VALUES (:id, :ws, 'video', :rel, 'ready', :sha, :sz, 1)"
            ),
            {"id": pub_artifact_id, "ws": ws, "rel": str(stitch_rel), "sha": stitch_sha, "sz": stitch_size},
        )
        session.flush()
        run = session.execute(
            sa_text(
                "SELECT apply_checkpoint_id, apply_checkpoint_hash, apply_checkpoint_revision, frame_count, plan_hash FROM s10_full_apply_run WHERE id=:rid AND workspace_id=:ws"
            ),
            {"rid": run_id, "ws": ws},
        ).mappings().first()
        if run is None:
            raise S10FullApplyJobError("run not found for publication")
        checkpoint_id = str(run["apply_checkpoint_id"])
        checkpoint_hash = str(run["apply_checkpoint_hash"])
        checkpoint_revision = int(run["apply_checkpoint_revision"])
        frame_count = int(stitch_meta.get("frame_count") or int(run["frame_count"]))
        content_hash = _hl.sha256(f"pub:{run_id}:{stitch_sha}".encode()).hexdigest()
        frame_metadata = dict(stitch_meta)
        frame_metadata["content_hash"] = content_hash
        frame_metadata["stitch_sha256"] = stitch_sha
        frame_metadata["stitch_size_bytes"] = stitch_size
        _per_layer_evidence = list(stitch_meta.get("per_layer_evidence") or [])
        frame_metadata.pop("per_layer_evidence", None)
        from app.persistence.s10_full_apply import S10ApplyRepository

        repo = S10ApplyRepository(session)
        pub, _created = repo.create_publication(
            ws, run_id, pub_artifact_id, content_hash, frame_count, frame_metadata, checkpoint_id, checkpoint_hash, checkpoint_revision, state="completed"
        )
        if pub.state != "completed":
            repo.complete_publication(pub.id, ws)
        session.flush()
        _write_evidence_sidecar(
            managed_root,
            stitch_rel,
            {
                "decoded_sha256": stitch_sha,
                "decoded_frame_count": frame_count,
                "fps_num": int(stitch_meta.get("fps_num", 30)),
                "fps_den": int(stitch_meta.get("fps_den", 1)),
                "layer_id": None,
                "shot_id": None,
                "route": "stitch",
                "effective_adapter": "stitch",
                "artifact_sha256": stitch_sha,
                "artifact_size_bytes": stitch_size,
                "per_layer_evidence": _per_layer_evidence,
            },
        )
        return pub.id
    with session_factory() as s:
        s.execute(
            sa_text(
                "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256, size_bytes, revision) VALUES (:id, :ws, 'video', :rel, 'ready', :sha, :sz, 1)"
            ),
            {"id": pub_artifact_id, "ws": ws, "rel": str(stitch_rel), "sha": stitch_sha, "sz": stitch_size},
        )
        s.commit()
    with session_factory() as s:
        run = s.execute(
            sa_text(
                "SELECT apply_checkpoint_id, apply_checkpoint_hash, apply_checkpoint_revision, frame_count, plan_hash FROM s10_full_apply_run WHERE id=:rid AND workspace_id=:ws"
            ),
            {"rid": run_id, "ws": ws},
        ).mappings().first()
        if run is None:
            raise S10FullApplyJobError("run not found for publication")
        checkpoint_id = str(run["apply_checkpoint_id"])
        checkpoint_hash = str(run["apply_checkpoint_hash"])
        checkpoint_revision = int(run["apply_checkpoint_revision"])
        frame_count = int(stitch_meta.get("frame_count") or int(run["frame_count"]))
        content_hash = _hl.sha256(f"pub:{run_id}:{stitch_sha}".encode()).hexdigest()
        frame_metadata = dict(stitch_meta)
        frame_metadata["content_hash"] = content_hash
        frame_metadata["stitch_sha256"] = stitch_sha
        frame_metadata["stitch_size_bytes"] = stitch_size
        _per_layer_evidence = list(stitch_meta.get("per_layer_evidence") or [])
        frame_metadata.pop("per_layer_evidence", None)
        from app.persistence.s10_full_apply import S10ApplyRepository

        repo = S10ApplyRepository(s)
        pub, _ = repo.create_publication(
            ws, run_id, pub_artifact_id, content_hash, frame_count, frame_metadata, checkpoint_id, checkpoint_hash, checkpoint_revision, state="completed"
        )
        if pub.state != "completed":
            repo.complete_publication(pub.id, ws)
        s.commit()
    # C6 req 5: the full-stitch artifact also carries an evidence sidecar next
    # to the media (same managed-root relative path + ".evidence.json"), written
    # atomically with the SAME same-directory staging strategy as chunks so the
    # final path survives >260-char nesting and zero orphan .staging survive.
    _write_evidence_sidecar(
        managed_root,
        stitch_rel,
        {
            "decoded_sha256": stitch_sha,
            "decoded_frame_count": frame_count,
            "fps_num": int(stitch_meta.get("fps_num", 30)),
            "fps_den": int(stitch_meta.get("fps_den", 1)),
            "layer_id": None,
            "shot_id": None,
            "route": "stitch",
            "effective_adapter": "stitch",
            "artifact_sha256": stitch_sha,
            "artifact_size_bytes": stitch_size,
            "per_layer_evidence": _per_layer_evidence,
        },
    )
    return pub.id


def _write_evidence_sidecar(managed_root: Path, rel: Path, evidence: dict[str, Any]) -> None:
    """Atomically persist an evidence sidecar next to a managed artifact.

    Same-directory staging (``.name.<uuid>.staging`` -> ``os.replace``) with
    mandatory cleanup on failure so zero orphan ``.staging`` files survive and
    the final path works under Windows >260-char nesting via ``_lp``.
    """
    ev_path = _lp(managed_root / (str(rel) + ".evidence.json"))
    ev_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_ev = _lp(ev_path.with_name(f".{ev_path.name}.{uuid.uuid4().hex}.staging"))
    try:
        tmp_ev.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        tmp_ev.replace(ev_path)
    except BaseException:
        try:
            tmp_ev.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def register_s10_full_apply_handler(worker) -> None:  # type: ignore[no-untyped-def]
    worker.register_handler(JOB_TYPE_S10_FULL_APPLY, s10_full_apply_handler)


def _multi_role_service() -> Any:
    if _S10MultiRoleService is None:
        raise S10FullApplyJobError("S10MultiRoleService not available (T02 not installed)")
    return _S10MultiRoleService()


def dispatch_per_role_via_worker(
    *,
    roles: list[dict[str, Any]],
    contact_edges: list[dict[str, Any]] | None = None,
    z_order_edges: list[dict[str, Any]] | None = None,
    visibility_events: list[dict[str, Any]] | None = None,
    shots: list[dict[str, Any]] | None = None,
    chunk_config: dict[str, Any] | None = None,
    role_order: list[str] | None = None,
    fail_role_id: str | None = None,
    fail_chunk_index: int | None = None,
) -> dict[str, Any]:
    """Bounded S10-T02 route-per-role dispatch exposed on the workflow layer."""
    svc = _multi_role_service()
    plan = svc.build_plan(
        roles=roles,
        contact_edges=contact_edges,
        z_order_edges=z_order_edges,
        visibility_events=visibility_events,
        shots=shots,
        chunk_config=chunk_config,
        schedule_order=role_order,
    )
    return svc.dispatch_per_role(  # type: ignore[no-any-return]
        plan,
        role_order=role_order,
        fail_role_id=fail_role_id,
        fail_chunk_index=fail_chunk_index,
    )





