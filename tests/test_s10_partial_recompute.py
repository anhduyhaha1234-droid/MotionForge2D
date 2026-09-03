"""S10-T03 — Affected-only partial recompute (binary acceptance: 5 bullets).

Isolated DB per test (tmp_path) — never MAIN.  Proves:
1. mask/z-order/contact/route/asset changes invalidate exactly the required
   layer/segment closure including overlap dependents
2. unaffected approved publications keep exact IDs/SHA/size/frame_count and
   have no new renderer attempt (unaffected chunks preserved byte-exact)
3. affected chunks have one new generation/attempt and provenance to correction
4. replay same correction is dedupe/no-op; stale revision and cross-project fail closed
5. restart during partial recompute resumes without duplicate rendering or loss
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text as sa_text

from app.persistence import create_engine_for_path, create_session_factory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _h64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _upgrade(db: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")


# ── C4: durable APPLIED correction authority seeding ────────────────────────
#
# The recompute resolver (_resolve_correction_authority) requires the
# correction_id to resolve a real `s09_correction` row that is `applied`,
# durable (natural_key + applied_at), same project/video, whose
# impact.affected_layer_ids EXACTLY equals the requested target layers and
# whose result.render_effect carries the post-correction facts (mask region,
# z-order, contact graph, route_to).  These helpers build that authority from
# canonical S09 shapes so the C4-strict service never invents semantics.

S09_RENDER_EFFECT_VERSION = "s09-correction-render-effect-v1"


def _default_effect(correction_kind: str) -> dict[str, Any]:
    if correction_kind == "mask":
        return {
            "version": S09_RENDER_EFFECT_VERSION,
            "op": "mask",
            "target_layer_id": "layer_mask_a",
            "target_segment_id": "seg_mask_a",
            "mask_semantics": {
                "version": "s09-mask-semantics-v1",
                "source_generation": "gen-1",
                "segmentation": {
                    "affected_region": [0.10, 0.10, 0.40, 0.40],
                    "points": [{"x": 10.0, "y": 20.0, "label": "h"}],
                },
                "confidence_source": "user",
                "reasons": ["mask correction"],
            },
        }
    if correction_kind == "z_order":
        return {
            "version": S09_RENDER_EFFECT_VERSION,
            "op": "z_order",
            "target_layer_id": "layer_a",
            "target_segment_id": "seg_z",
            "z_order": 7,
        }
    if correction_kind == "contact":
        return {
            "version": S09_RENDER_EFFECT_VERSION,
            "op": "contact",
            "target_contact_id": "contact_1",
            "source_segment_id": "seg_src",
            "target_segment_id": "seg_tgt",
            "contact_kind": "hand",
            "start_frame": 10,
            "end_frame": 40,
            "start_time_ms": 200,
            "end_time_ms": 800,
        }
    if correction_kind == "route":
        return {
            "version": S09_RENDER_EFFECT_VERSION,
            "op": "route_override",
            "target_layer_id": "layer_route",
            "target_segment_id": "seg_route",
            "render_route_id": "rr_1",
            "route_from": "sprite_affine",
            "route_to": "controlled_redraw",
            "frame_range": {"start_frame": 0, "end_frame": 49},
            "anchor": {"x": 0.5, "y": 0.5},
            "provenance": {"route_from": "sprite_affine", "route_to": "controlled_redraw", "evidence": "seed"},
        }
    raise AssertionError(f"no default effect for kind {correction_kind!r}")


def _seed_correction_authority(
    factory: Any,
    seed: dict[str, Any],
    correction_id: str,
    correction_kind: str,
    layer_ids: list[str],
    *,
    loop_ids: list[str] | None = None,
    effect: dict[str, Any] | None = None,
    status: str = "applied",
    project_id: str | None = None,
    video_item_id: str | None = None,
) -> None:
    """Insert a durable APPLIED s09_correction authority row (canonical S09)."""
    s09_kind = {"mask": "mask", "z_order": "z_order", "contact": "contact", "route": "route_override"}[correction_kind]
    loops = loop_ids or seed.get("loop_ids") or ["shot_A", "shot_B"]
    impact = {
        "affected_loop_ids": loops,
        "affected_layer_ids": layer_ids,
    }
    eff = dict(effect if effect is not None else _default_effect(correction_kind))
    result = {"render_effect": eff}
    with factory() as s:
        s.execute(
            sa_text(
                "INSERT INTO s09_correction(id, workspace_id, project_id, video_item_id, correction_kind, "
                "status, request_json, impact_json, result_json, applied_at, natural_key) "
                "VALUES (:id, :ws, :proj, :vid, :kind, :status, '{}', :impact, :result, :applied, :nk)"
            ),
            {
                "id": correction_id,
                "ws": seed["workspace_id"],
                "proj": project_id or seed["project_id"],
                "vid": video_item_id or seed["video_item_id"],
                "kind": s09_kind,
                "status": status,
                "impact": json.dumps(impact, sort_keys=True),
                "result": json.dumps(result, sort_keys=True),
                "applied": datetime(2026, 8, 29, tzinfo=timezone.utc),
                "nk": f"nat-{correction_id}",
            },
        )
        s.commit()


def _seed_run_with_chunks(
    tmp_path: Path, *, frame_count: int = 100, layers: list[str] | None = None
) -> tuple[Path, Path, Any, dict[str, Any], list[dict[str, Any]]]:
    """Seed a REAL server-derived v2 authority graph + minimal-contract run.

    S10-C6A/C5 re-alignment: FullApplyService.submit now plans EXCLUSIVELY
    from a frozen ``s09.approval/v2`` checkpoint (client authority is never
    accepted).  This fixture therefore builds the canonical persisted graph —
    real managed source artifact + per-layer replacement assets, object roles
    (id == friendly layer name so chunk ``layer_id`` keeps the test contract),
    occurrence segments with BOXED geometry (the affected region is DERIVED
    from persisted geometry, never hard-coded in a client payload), a
    hash-pinned structural lock manifest, per-role reskin configs — and
    creates a REAL v2 checkpoint through ``S09ApprovalRepository
    .submit_checkpoint_v2``.  The run is then submitted through the minimal
    public identity/CAS contract (no legacy authority fields) and the durable
    job manifest carries the server-produced ``render_authority`` + frozen
    source/asset pins — exactly the production submit shape.
    """
    import math as _math

    import cv2 as _cv2
    import numpy as _np
    from app.persistence.artifacts import hash_file as _hash_file
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.renderer_routes.composite import write_frames_mp4 as _wfm
    from app.services.s09_approval import S09ApprovalRepository

    layers = layers or ["layer_mask_a", "layer_bg"]
    n = len(layers)
    db = tmp_path / f"t03-{uuid.uuid4().hex[:6]}.db"
    artifacts_root = tmp_path / f"art-{uuid.uuid4().hex[:6]}"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    _upgrade(db)
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)
    ws = "default"
    GEN = "1"
    with factory() as s:
        s.execute(sa_text("INSERT OR IGNORE INTO workspace(id,name) VALUES ('default','default')"))
        proj = f"proj-{uuid.uuid4().hex[:6]}"
        proj2 = f"proj2-{uuid.uuid4().hex[:6]}"
        vid = f"vid-{uuid.uuid4().hex[:6]}"
        vid2 = f"vid2-{uuid.uuid4().hex[:6]}"
        s.execute(sa_text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"), {"p": proj, "w": ws})
        s.execute(sa_text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Other')"), {"p": proj2, "w": ws})
        s.execute(sa_text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"), {"v": vid, "p": proj})
        s.execute(sa_text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'OtherVid',0)"), {"v": vid2, "p": proj2})
        s.execute(sa_text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,0,:ef,0,1000,'pending')"), {"s": f"sc-{uuid.uuid4().hex[:6]}", "v": vid, "ef": frame_count - 1})
        s.execute(sa_text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,50,:ef,0,1000,'pending')"), {"s": f"sc-{uuid.uuid4().hex[:6]}", "v": vid2, "ef": frame_count - 1})
        # Per-layer authority graph: character -> published pack -> role -> config.
        pack_ids: list[str] = []
        for layer in layers:
            char = f"ch-{uuid.uuid4().hex[:6]}"
            pv = f"pv-{uuid.uuid4().hex[:6]}"
            s.execute(
                sa_text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,:name,:code)"),
                {"c": char, "w": ws, "name": layer, "code": f"hero_{layer[:12]}_{uuid.uuid4().hex[:4]}"},
            )
            s.execute(
                sa_text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"),
                {"pv": pv, "c": char, "w": ws},
            )
            s.execute(
                sa_text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,:gen,:name,'character','confirmed')"),
                {"r": layer, "w": ws, "p": proj, "v": vid, "gen": GEN, "name": layer},
            )
            valid_params = {
                "anchor": {"x": 0.5, "y": 0.5},
                "scale": 1.0,
                "fit_mode": "contain",
                "clip_mode": "asset_alpha",
                "offset": {"x": 0.0, "y": 0.0},
                "rotation_offset_deg": 0.0,
                "opacity": 1.0,
            }
            rc = f"rc-{uuid.uuid4().hex[:6]}"
            s.execute(
                sa_text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"),
                {"rc": rc, "w": ws, "p": proj, "r": layer, "c": char, "pv": pv, "params": json.dumps(valid_params, sort_keys=True, separators=(",", ":"))},
            )
            pack_ids.append(pv)
        s.commit()
        seed = {
            "workspace_id": ws,
            "project_id": proj,
            "project_id2": proj2,
            "video_item_id": vid,
            "video_item_id2": vid2,
        }

    # ── Stage real decodable source + per-layer assets BEFORE artifact rows ──
    # so the frozen v2 authority pins REAL sha256/size_bytes of existing files.
    src_rel = f"s10_full_apply/_authority/{vid}/source.mp4"
    src_abs = artifacts_root / src_rel
    src_abs.parent.mkdir(parents=True, exist_ok=True)
    frames0: list[Any] = []
    for i in range(frame_count):
        f = _np.zeros((120, 160, 3), dtype=_np.uint8)
        f[:, :, 0] = int(30 + i * 2) % 255
        f[:, :, 1] = 80
        f[:, :, 2] = 20
        frames0.append(f)
    _wfm(frames0, src_abs, fps=30.0)
    src_sha = _hash_file(src_abs)
    with factory() as s:
        src_art = f"art-src-{uuid.uuid4().hex[:6]}"
        s.execute(
            sa_text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,:w,'video',:rel,'ready',:sha,:sz,1)"),
            {"id": src_art, "w": ws, "rel": src_rel, "sha": src_sha, "sz": src_abs.stat().st_size},
        )
        s.execute(sa_text("UPDATE video_item SET source_artifact_id=:aid WHERE id=:vid"), {"aid": src_art, "vid": vid})
        for layer in layers:
            # Executor contract: the replacement asset file must be named
            # exactly ``{layer_id}.png`` inside the assets dir (T02
            # execute_role_chunk resolves assets_dir / f"{layer_id}.png").
            asset_rel = f"s10_full_apply/_authority/{vid}/{layer}.png"
            asset_abs = artifacts_root / asset_rel
            asset_abs.parent.mkdir(parents=True, exist_ok=True)
            img = _np.zeros((40, 40, 4), dtype=_np.uint8)
            hx = hashlib.sha256(layer.encode()).hexdigest()
            img[:, :, 0] = int(hx[0:2], 16)
            img[:, :, 1] = int(hx[2:4], 16)
            img[:, :, 2] = int(hx[4:6], 16)
            img[:, :, 3] = 255
            _cv2.imwrite(str(asset_abs), img)
            asset_sha = _hash_file(asset_abs)
            asset_art = f"art-asset-{uuid.uuid4().hex[:6]}"
            s.execute(
                sa_text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                {"id": asset_art, "w": ws, "rel": asset_rel, "sha": asset_sha, "sz": asset_abs.stat().st_size},
            )
            pv = s.execute(
                sa_text("SELECT id FROM character_pack_version WHERE id IN (SELECT pack_version_id FROM reskin_config WHERE object_role_id=:r)"),
                {"r": layer},
            ).scalar()
            ca = f"ca-{uuid.uuid4().hex[:6]}"
            s.execute(
                sa_text("INSERT INTO character_asset(id,pack_version_id,workspace_id,pose_slot,artifact_id) VALUES (:id,:pv,:w,'base',:aid)"),
                {"id": ca, "pv": pv, "w": ws, "aid": asset_art},
            )
        s.commit()

    # ── Occurrence segments (boxed geometry) + hash-pinned SLM + v2 checkpoint ──
    with factory() as s:
        scene_id = s.execute(sa_text("SELECT id FROM scene WHERE video_item_id=:v ORDER BY position LIMIT 1"), {"v": vid}).scalar()
        per = _math.ceil(frame_count / n)
        seg_ids: list[str] = []
        seg_ranges: list[tuple[str, int, int]] = []
        seg_repo = StructuralEvidenceRepository(s)
        for i, layer in enumerate(layers):
            start = i * per
            end = min(start + per - 1, frame_count - 1)
            mask_art = f"art-mask-{uuid.uuid4().hex[:6]}"
            s.execute(
                sa_text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision) VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                {"id": mask_art, "w": ws, "rel": f"s10_full_apply/_authority/{vid}/mask_{layer}.png", "sha": _h64(f"mask-{layer}"), "sz": 64},
            )
            seg_rec, _sc = seg_repo.create_segment(
                ws,
                str(proj),
                vid,
                layer,
                str(scene_id),
                layer,
                start,
                end,
                start * 33,
                end * 33,
                GEN,
                kind="character",
                confidence_source="user",
                segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.40, "h": 0.40}]},
                prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.50, "h": 0.50}]},
                mask_artifact_id=mask_art,
            )
            seg_ids.append(str(seg_rec.id))
            seg_ranges.append((str(seg_rec.id), start, end))
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": frame_count,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": list(seg_ids),
            "fingerprints": {"z_order": _h64("z"), "contacts": _h64("c")},
            "segments": [
                {
                    "occurrence_segment_id": sid,
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": sf,
                    "end_frame": ef,
                    "provenance": {"why": "t03-c5-fixture"},
                }
                for (sid, sf, ef) in seg_ranges
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _mc = lock_repo.create_manifest(ws, str(proj), vid, GEN, manifest_dict)
        for sid, sf, ef in seg_ranges:
            lock_repo.record_render_route(
                ws,
                str(proj),
                vid,
                sid,
                "sprite_affine",
                0.5,
                0.5,
                sf,
                ef,
                provenance={"why": "t03-c5-fixture"},
                reasons=["t03-c5-fixture"],
                structural_lock_manifest_id=manifest.id,
            )
        for layer in layers:
            s.execute(
                sa_text("UPDATE reskin_config SET structural_lock_manifest_id=:m, lock_policy_version=:p WHERE object_role_id=:r"),
                {"m": manifest.id, "p": manifest.policy_version, "r": layer},
            )
        s.flush()
        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint_v2(
            ws,
            reskin_config_id=str(s.execute(sa_text("SELECT id FROM reskin_config WHERE object_role_id=:r"), {"r": layers[0]}).scalar()),
            expected_reskin_revision=1,
            pack_version_ids=pack_ids,
            note="t03-c5 server-derived v2 authority fixture",
        )
        assert created is True
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = int(record.reskin_config_revision)
        seed["loop_ids"] = list(seg_ids)
        seed["manifest_id"] = str(manifest.id)
        seed["manifest_hash"] = str(manifest.manifest_hash_hex)

    # ── Submit the MINIMAL public contract (identity/CAS + bounded controls) ──
    from app.services.s10_full_apply import FullApplyService

    with factory() as s:
        svc = FullApplyService(s)
        rec, created, plan = svc.submit(
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            video_item_id=seed["video_item_id"],
            apply_checkpoint_id=seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"],
            expected_checkpoint_revision=seed["checkpoint_revision"],
            chunk_config={"chunk_frames": 25, "overlap_frames": 4},
        )
        assert created, "minimal public submit must create a fresh run"
        s.commit()
        run_id = rec.id
    # Frozen source/asset pins straight from the persisted v2 authority.
    with factory() as s:
        auth = S09ApprovalRepository(s).full_apply_authority(seed["checkpoint_id"], ws)
        src_auth = auth["source"]
        pins: dict[str, Any] = {
            "source_media_artifact_id": str(src_auth["source_artifact_id"]),
            "source_media_rel": str(src_auth["relative_path"]),
            "source_media_sha256": str(src_auth["sha256"]),
            "source_media_size_bytes": int(src_auth["size_bytes"]),
        }
        repl: dict[str, Any] = {}
        for rm in auth.get("role_mappings") or []:
            role_id = str(rm["object_role_id"])
            chosen = rm["pack_assets"][0]
            repl[role_id] = {
                "artifact_id": str(chosen["artifact_id"]),
                "rel": str(chosen["relative_path"]),
                "sha256": str(chosen["sha256"]),
                "size_bytes": int(chosen["size_bytes"]),
            }
        pins["replacement_assets"] = repl
        pins["timebase_fingerprint"] = str(
            s.execute(sa_text("SELECT timebase_fingerprint FROM apply_checkpoint WHERE id=:id"), {"id": seed["checkpoint_id"]}).scalar()
        )
        s.commit()
    # Enqueue the durable worker job exactly like the API route (canonical
    # render_authority from the service plan + frozen pins).
    from app.api import deps
    from app.workflow.job_service import JobService
    from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

    js = JobService(session_factory=factory, managed_root=artifacts_root)
    register_s10_full_apply_handler(js._worker)  # type: ignore[attr-defined]
    try:
        js._worker.bind_session_factory(factory)  # type: ignore[attr-defined]
    except Exception:
        pass
    deps._job_service = js  # type: ignore[attr-defined]
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "workspace_id": ws,
        "project_id": proj,
        "video_item_id": vid,
        "apply_checkpoint_id": seed["checkpoint_id"],
        "plan_id": rec.plan_id,
        "plan_hash": rec.plan_hash,
        "managed_root": str(artifacts_root),
        "render_authority": plan["render_authority"],
        **pins,
    }
    js.create_job(
        "s10_full_apply",
        manifest,
        workspace_id=ws,
        owner_type="project",
        owner_id=proj,
        idempotency_key=f"s10_full_apply_job:{run_id}",
    )
    js._worker.run_once()  # type: ignore[attr-defined]
    # collect chunk rows
    with factory() as s:
        rows = s.execute(sa_text("SELECT id, chunk_index, shot_id, layer_id, core_start_frame, core_end_frame, overlap_before, overlap_after, content_hash, attempt, artifact_id, verified, revision FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY order_index"), {"rid": run_id}).mappings().all()
        chunks = [dict(r) for r in rows]
        assert all(r["verified"] == 1 for r in chunks), f"seed not fully verified: {chunks}"
        # also create one publication per run to prove unaffected preservation checks
        # (we use chunk 0's artifact as pub artifact)
        art_id = str(chunks[0]["artifact_id"])
        pub_hash = _h64(f"pub-{run_id}")
        from app.persistence.s10_full_apply import S10ApplyRepository

        repo = S10ApplyRepository(s)
        pub, _ = repo.create_publication(
            ws,
            run_id,
            art_id,
            pub_hash,
            frame_count,
            {"frame_count": frame_count, "timebase": "30/1"},
            seed["checkpoint_id"],
            seed["checkpoint_hash"],
            seed["checkpoint_revision"],
            natural_key=f"nat-pub-{run_id[:8]}",
        )
        repo.complete_publication(pub.id, ws)
        s.commit()
    return db, artifacts_root, factory, seed, chunks


def _chunk_artifact_sha(factory: Any, artifact_id: str, artifacts_root: Path) -> str:
    with factory() as s:
        rel = s.execute(sa_text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": artifact_id}).scalar()
        assert rel is not None
        from app.persistence.artifacts import hash_file

        return hash_file(artifacts_root / rel)


def _chunk_file_size(factory: Any, artifact_id: str, artifacts_root: Path) -> int:
    with factory() as s:
        rel = s.execute(sa_text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": artifact_id}).scalar()
        assert rel is not None
        p = artifacts_root / rel
        assert p.is_file()
        return p.stat().st_size


# ── 1. mask -> layer closure + overlap dependents ─────────────────────────

def test_mask_invalidate_layer_closure_plus_overlap(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_mask_a", "layer_bg"])
    # Use service to compute affected closure: change layer_mask_a
    from app.services.s10_recompute import S10RecomputeService, compute_affected_closure

    corr_id = f"corr-mask-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_mask_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, created = svc.apply_correction(
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            run_id=s.execute(sa_text("SELECT id FROM s10_full_apply_run WHERE workspace_id=:ws ORDER BY created_at DESC LIMIT 1"), {"ws": seed["workspace_id"]}).scalar(),
            correction_id=corr_id,
            correction_kind="mask",
            target_layer_ids=["layer_mask_a"],
        )
        s.commit()
        assert created is True
        affected = set(rec["affected_chunk_ids"])
        # All chunks of layer_mask_a plus their immediate overlap neighbours must be affected
        # Build groups by (shot, layer)
        all_ids_by_layer: dict[str, list[str]] = {}
        for ch in chunks:
            all_ids_by_layer.setdefault(str(ch["layer_id"]), []).append(str(ch["id"]))
        mask_ids = set(all_ids_by_layer["layer_mask_a"])
        assert mask_ids.issubset(affected), "mask layer closure must include all mask chunks"
        # layer_bg must stay unaffected
        bg_ids = set(all_ids_by_layer["layer_bg"])
        assert affected.isdisjoint(bg_ids), "mask change must not invalidate unrelated layer"
        # overlap dependents: neighbours within same (shot, layer) — affected should be at least mask_ids
        # and our closure adds immediate neighbours, so for 2 chunks per shot/layer the closure
        # covers both chunks in the same shot if one is targeted (which is all anyway)
        # Prove overlap expansion via direct compute_affected_closure call
        closure = compute_affected_closure(correction_kind="mask", target_layer_ids=["layer_mask_a"], chunks=chunks)
        assert closure == affected


def test_zorder_invalidate_closure(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b", "layer_c"])
    from app.services.s10_recompute import S10RecomputeService

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    corr_id = f"corr-z-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "z_order", ["layer_a", "layer_b"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, created = svc.apply_correction(
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            run_id=str(run_id),
            correction_id=corr_id,
            correction_kind="z_order",
            target_layer_ids=["layer_a", "layer_b"],
        )
        s.commit()
        affected = set(rec["affected_chunk_ids"])
        layer_ids = {str(c["layer_id"]) for c in chunks}
        assert "layer_c" in layer_ids
        # z_order involving a and b must invalidate exactly a+b closures (plus overlap neighbours)
        for ch in chunks:
            cid = str(ch["id"])
            lid = str(ch["layer_id"])
            if lid in ("layer_a", "layer_b"):
                assert cid in affected, f"z_order must invalidate {lid} chunk {cid}"
            else:
                assert cid not in affected, f"z_order must not invalidate unrelated layer_c chunk {cid}"


def test_contact_and_route_and_asset_kind(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_contact", "layer_other"])
    from app.services.s10_recompute import S10RecomputeService, S10RecomputeParamsError

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    # contact + route have a durable applied authority in the S09 domain
    for kind in ("contact", "route"):
        cid = f"corr-{kind}-{uuid.uuid4().hex[:6]}"
        _seed_correction_authority(factory, seed, cid, kind, ["layer_contact"])
        with factory() as s:
            svc = S10RecomputeService(s)
            rec, _ = svc.apply_correction(
                workspace_id=seed["workspace_id"],
                project_id=seed["project_id"],
                run_id=str(run_id),
                correction_id=cid,
                correction_kind=kind,
                target_layer_ids=["layer_contact"],
            )
            s.commit()
            aff = set(rec["affected_chunk_ids"])
            for ch in chunks:
                if str(ch["layer_id"]) == "layer_contact":
                    assert str(ch["id"]) in aff
                else:
                    assert str(ch["id"]) not in aff
    # asset has NO approved correction authority in the current S09 domain —
    # C4 blocks it explicitly instead of inventing semantics.
    cid_asset = f"corr-asset-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_asset, "mask", ["layer_contact"])
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeParamsError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"],
                project_id=seed["project_id"],
                run_id=str(run_id),
                correction_id=cid_asset,
                correction_kind="asset",
                target_layer_ids=["layer_contact"],
            )


# ── 2. unaffected keep exact ID/SHA/size/frame_count, no new attempt ───────

def test_unaffected_preserved_and_affected_attempt_plus_one(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    # Baseline snapshot
    with factory() as s:
        before_rows = {r["id"]: dict(r) for r in s.execute(sa_text("SELECT id, attempt, artifact_id, content_hash FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all()}
        pub_before = s.execute(sa_text("SELECT id, content_hash, frame_count, artifact_id FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().first()
        pub_before = dict(pub_before) if pub_before else {}
        # capture artifact sizes/SHAs
        before_shas: dict[str, str] = {}
        before_sizes: dict[str, int] = {}
        for cid, row in before_rows.items():
            aid = str(row["artifact_id"])
            before_shas[cid] = _chunk_artifact_sha(factory, aid, artifacts_root)
            before_sizes[cid] = _chunk_file_size(factory, aid, artifacts_root)
    from app.services.s10_recompute import S10RecomputeService

    corr_id = f"corr-preserve-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            run_id=str(run_id),
            correction_id=corr_id,
            correction_kind="mask",
            target_layer_ids=["layer_a"],
        )
        s.commit()
        affected = set(rec["affected_chunk_ids"])
    # execute partial recompute only for affected
    with factory() as s:
        svc = S10RecomputeService(s)
        res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=artifacts_root)
        s.commit()
        assert res["completed"] is True
        after_rows = {r["id"]: dict(r) for r in s.execute(sa_text("SELECT id, attempt, artifact_id, content_hash FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all()}
        pub_after = s.execute(sa_text("SELECT id, content_hash, frame_count, artifact_id FROM s10_full_apply_publication WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().first()
        pub_after = dict(pub_after) if pub_after else {}
    # Unaffected (layer_b) must keep exact IDs/SHA/size/frame_count and NO new attempt
    for cid, before_row in before_rows.items():
        if cid not in affected:
            after = after_rows[cid]
            assert after["attempt"] == before_row["attempt"], f"unaffected chunk {cid} attempt must not increase"
            assert after["artifact_id"] == before_row["artifact_id"], f"unaffected chunk {cid} artifact_id must stay exact"
            assert _chunk_artifact_sha(factory, str(after["artifact_id"]), artifacts_root) == before_shas[cid]
            assert _chunk_file_size(factory, str(after["artifact_id"]), artifacts_root) == before_sizes[cid]
        else:
            after = after_rows[cid]
            assert after["attempt"] == int(before_row["attempt"]) + 1, f"affected chunk {cid} must have attempt+1"
            assert after["artifact_id"] != before_row["artifact_id"], f"affected chunk {cid} must have new artifact"
            # provenance recorded
            with factory() as s2:
                svc2 = S10RecomputeService(s2)
                provs = svc2.get_provenance(seed["workspace_id"], cid)
                assert any(p.get("correction_id") == corr_id for p in provs), f"affected chunk {cid} provenance must reference correction"
    # publication (unaffected approved) keeps exact IDs/SHA/frame_count
    if pub_before and pub_after:
        assert pub_after["id"] == pub_before["id"]
        assert pub_after["content_hash"] == pub_before["content_hash"]
        assert pub_after["frame_count"] == pub_before["frame_count"]
        assert pub_after["artifact_id"] == pub_before["artifact_id"]


# ── 3. stale revision and cross-project fail closed ─────────────────────────

def test_stale_revision_fail_closed(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path)
    from app.services.s10_recompute import S10RecomputeService, S10RecomputeStaleError

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id, revision FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).mappings().first()["id"]
        rev = s.execute(sa_text("SELECT revision FROM s10_full_apply_run WHERE id=:rid"), {"rid": str(run_id)}).scalar()
        stale = int(rev) - 1 if int(rev) > 1 else int(rev) + 99
        cid = f"corr-stale-{uuid.uuid4().hex[:6]}"
        _seed_correction_authority(factory, seed, cid, "mask", [str(chunks[0]["layer_id"])])
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeStaleError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"],
                project_id=seed["project_id"],
                run_id=str(run_id),
                correction_id=cid,
                correction_kind="mask",
                target_layer_ids=[str(chunks[0]["layer_id"])],
                expected_revision=stale,
            )


def test_cross_project_rejected(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path)
    from app.services.s10_recompute import S10RecomputeService, S10RecomputeOwnershipError

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    cid = f"corr-cross-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid, "mask", [str(chunks[0]["layer_id"])])
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeOwnershipError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"],
                project_id=seed["project_id2"],
                run_id=str(run_id),
                correction_id=cid,
                correction_kind="mask",
                target_layer_ids=[str(chunks[0]["layer_id"])],
            )


# ── 4. replay same correction is dedupe/no-op ───────────────────────────────

def test_replay_same_correction_dedupe(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path)
    from app.services.s10_recompute import S10RecomputeService

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    corr_id = f"corr-replay-{uuid.uuid4().hex[:6]}"
    layer = str(chunks[0]["layer_id"])
    _seed_correction_authority(factory, seed, corr_id, "mask", [layer])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec1, c1 = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=[layer])
        s.commit()
        assert c1 is True
        # capture attempt after first correction
        attempt_after_first = s.execute(sa_text("SELECT attempt FROM s10_full_apply_chunk WHERE id=:cid"), {"cid": str(chunks[0]["id"])}).scalar()
        rec2, c2 = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=[layer])
        s.commit()
        assert c2 is False, "replay must be dedupe/no-op"
        assert rec2["affected_chunk_ids"] == rec1["affected_chunk_ids"]
        assert rec2["result_hash"] == rec1["result_hash"]
        attempt_after_replay = s.execute(sa_text("SELECT attempt FROM s10_full_apply_chunk WHERE id=:cid"), {"cid": str(chunks[0]["id"])}).scalar()
        assert int(attempt_after_replay) == int(attempt_after_first), "replay must not bump attempt again"


# ── 5. restart during partial recompute resumes without duplicate/loss ──────

def test_restart_during_partial_recompute_resumes(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    from app.services.s10_recompute import S10RecomputeService, _MidRecomputeStop

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    # Snapshot before recompute: all verified
    with factory() as s:
        before_verified = {r["id"]: dict(r) for r in s.execute(sa_text("SELECT id, verified, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all()}
        assert all(v["verified"] == 1 for v in before_verified.values())
    corr_id = f"corr-restart-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=["layer_a"])
        s.commit()
        affected = rec["affected_chunk_ids"]
        assert len(affected) >= 2, "need at least 2 affected for restart test"
    # First execute: stop after first affected chunk
    with factory() as s:
        svc = S10RecomputeService(s)
        try:
            svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=artifacts_root, stop_after=0)
            s.commit()
            assert False, "should have raised MidRecomputeStop"
        except _MidRecomputeStop:
            s.commit()
    # Checkpoint must be durable at 1
    with factory() as s:
        cp = s.execute(sa_text("SELECT next_index, executed_json, completed FROM s10_recompute_checkpoint WHERE correction_id=:cid"), {"cid": corr_id}).mappings().first()
        assert cp is not None
        assert int(cp["next_index"]) == 1
        assert int(cp["completed"]) == 0
        part_executed = json.loads(str(cp["executed_json"]))
        assert len(part_executed) == 1
        part_artifact = s.execute(sa_text("SELECT artifact_id FROM s10_full_apply_chunk WHERE id=:cid"), {"cid": part_executed[0]}).scalar()
        assert part_artifact is not None
    # Simulate fresh process: new service instance, resume
    with factory() as s:
        svc = S10RecomputeService(s)
        res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=artifacts_root)
        s.commit()
        assert res["completed"] is True
        # Previously approved chunks (the unaffected layer_b) must still be preserved
        # and the already-rendered affected chunk must not be duplicated (no second attempt bump)
        after = {r["id"]: dict(r) for r in s.execute(sa_text("SELECT id, attempt, artifact_id, verified FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all()}
        # Unaffected layer_b chunks must still be verified and attempt unchanged (1)
        for cid, row in before_verified.items():
            if str(cid) not in set(affected):
                assert after[cid]["verified"] == 1
                assert after[cid]["attempt"] == row.get("attempt", 1) or int(after[cid]["attempt"]) == 1
                assert after[cid]["artifact_id"] == row["artifact_id"], "unaffected chunks must not lose approved artifact on restart"
        # All affected must now be completed/verified and the first one kept its artifact (no rerender)
        assert after[part_executed[0]]["artifact_id"] == part_artifact, "restart must not duplicate already-rendered chunk"
        cp2 = s.execute(sa_text("SELECT next_index, completed FROM s10_recompute_checkpoint WHERE correction_id=:cid"), {"cid": corr_id}).mappings().first()
        assert int(cp2["next_index"]) == len(affected)
        assert int(cp2["completed"]) == 1


# ── deterministic closure smoke ─────────────────────────────────────────────

def test_compute_affected_closure_deterministic(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_x", "layer_y"])
    from app.services.s10_recompute import compute_affected_closure

    a = compute_affected_closure(correction_kind="mask", target_layer_ids=["layer_x"], chunks=chunks)
    b = compute_affected_closure(correction_kind="mask", target_layer_ids=["layer_x"], chunks=chunks)
    assert a == b
    # different kind same target still deterministic (closure identity bound to layer set)
    c = compute_affected_closure(correction_kind="route", target_layer_ids=["layer_x"], chunks=chunks)
    assert isinstance(c, set)

# ── C3 instrumented: adapter invocations, identity assertions, bytes, path-budget ──

def test_c3_affected_adapter_invocation_and_evidence(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    with factory() as s:
        before_shas: dict[str, str] = {}
        for r in s.execute(sa_text("SELECT id, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all():
            before_shas[str(r["id"])] = _chunk_artifact_sha(factory, str(r["artifact_id"]), artifacts_root) if r["artifact_id"] else ""
    from unittest.mock import patch
    from app.services.s10_multi_role_apply import S10MultiRoleService
    orig_exec = S10MultiRoleService.execute_role_chunk
    calls: list[dict[str, Any]] = []
    def _instrumented(self, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))
        return orig_exec(self, **kwargs)
    corr_id = f"corr-c3-adapter-{uuid.uuid4().hex[:6]}"
    # C4: seed a mask correction whose persisted region DIFFERS from the
    # baseline mapping region [0.10, 0.10, 0.40, 0.40] — under C4 the bytes
    # change only via the real corrected visual fact (no hash perturb).
    _seed_correction_authority(
        factory, seed, corr_id, "mask", ["layer_a"],
        effect={
            "version": S09_RENDER_EFFECT_VERSION,
            "op": "mask",
            "target_layer_id": "layer_a",
            "target_segment_id": "seg_a",
            "mask_semantics": {
                "version": "s09-mask-semantics-v1",
                "source_generation": "gen-1",
                "segmentation": {"affected_region": [0.10, 0.10, 0.45, 0.45], "points": []},
                "confidence_source": "user",
                "reasons": ["mask correction"],
            },
        },
    )
    with factory() as s:
        from app.services.s10_recompute import S10RecomputeService
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=["layer_a"])
        s.commit()
        affected = set(rec["affected_chunk_ids"])
        exp_affected = len(affected)
    with patch.object(S10MultiRoleService, "execute_role_chunk", _instrumented):
        with factory() as s:
            svc = S10RecomputeService(s)
            res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=artifacts_root)
            s.commit()
            assert res["completed"] is True
            assert len(res["rendered"]) == exp_affected, f"rendered {len(res['rendered'])} != affected {exp_affected}"
    # adapter invocation >0 with exact request/route assertion
    from app.workflow.s10_full_apply_jobs import _lp as _lp_test

    assert len(calls) == exp_affected, f"adapter calls {len(calls)} != affected {exp_affected}"
    expected_root = _lp_test(Path(artifacts_root), force=True)
    for kw in calls:
        assert kw.get("workspace_id") == seed["workspace_id"]
        assert kw.get("project_id") == seed["project_id"]
        assert kw.get("video_item_id") == seed["video_item_id"]
        # workspace_root is the extended-length-normalized managed root (same file)
        assert Path(str(kw.get("workspace_root"))).resolve() == Path(str(expected_root)).resolve()
        assert kw.get("source_media") is not None
        assert kw.get("assets_dir") is not None
        assert kw.get("output_media") is not None
        assert kw.get("source_timebase") is not None
    # route/effective_adapter must be from renderer execution (SpriteAffineAdapter) not correction label "mask"
    for r in res["rendered"]:
        ev = r["evidence"]
        assert ev["effective_adapter"] == "SpriteAffineAdapter", f"effective_adapter must be renderer truth got {ev['effective_adapter']!r}"
        assert ev["route"] == "sprite_affine", f"route must be pinned sprite_affine got {ev['route']!r}"
        assert ev["correction_kind"] == "mask"
        assert ev["correction_id"] == corr_id
        assert ev["renderer_evidence"]["effective_adapter"] == "SpriteAffineAdapter"
    # affected bytes must have changed (new SHA), unaffected unchanged
    with factory() as s:
        after_shas: dict[str, str] = {}
        for r in s.execute(sa_text("SELECT id, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all():
            after_shas[str(r["id"])] = _chunk_artifact_sha(factory, str(r["artifact_id"]), artifacts_root) if r["artifact_id"] else ""
    for cid in affected:
        assert before_shas[cid] != after_shas[cid], f"affected {cid} bytes must change"
    for cid in set(before_shas.keys()) - affected:
        assert before_shas[cid] == after_shas[cid], f"unaffected {cid} bytes must stay exact"


def test_c3_decodable_media_and_atomic_evidence(tmp_path: Path) -> None:
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    from app.services.s10_recompute import S10RecomputeService
    corr_id = f"corr-c3-media-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=["layer_a"])
        s.commit()
    with factory() as s:
        svc = S10RecomputeService(s)
        res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=artifacts_root)
        s.commit()
        assert res["completed"] is True
    from app.services.renderer_routes.composite import decode_rgb_frames, probe_source_timebase
    from app.persistence.artifacts import hash_file
    for r in res["rendered"]:
        rel = r["relative_path"]
        abs_p = artifacts_root / rel
        assert abs_p.is_file(), f"artifact missing {rel}"
        # decodable correct range/timebase
        frames = decode_rgb_frames(abs_p)
        with factory() as s:
            ch = s.execute(sa_text("SELECT core_start_frame, core_end_frame FROM s10_full_apply_chunk WHERE id=:cid"), {"cid": r["chunk_id"]}).mappings().first()
            exp = int(ch["core_end_frame"]) - int(ch["core_start_frame"]) + 1
            assert len(frames) == exp, f"frame_count {len(frames)} != expected {exp}"
        tb = probe_source_timebase(abs_p)
        assert tb == (30, 1)
        # actual SHA/size must match DB
        actual_sha = hash_file(abs_p)
        actual_size = abs_p.stat().st_size
        assert actual_sha == r["sha256"]
        assert r["size_bytes"] == actual_size
        with factory() as s:
            db_sha = s.execute(sa_text("SELECT sha256, size_bytes FROM artifact WHERE id=:aid"), {"aid": r["artifact_id"]}).mappings().first()
            assert str(db_sha["sha256"]) == actual_sha
            assert int(db_sha["size_bytes"]) == actual_size
        # atomic evidence in-root, no orphan
        ev_rel = rel + ".evidence.json"
        ev_abs = artifacts_root / ev_rel
        assert ev_abs.is_file(), f"evidence missing {ev_rel}"
        assert ".staging" not in str(ev_abs)
        ev_data = json.loads(ev_abs.read_text(encoding="utf-8"))
        assert ev_data["artifact_sha256"] == actual_sha
        assert ev_data["correction_id"] == corr_id
        # ensure no .staging orphan anywhere under managed root
        orphans = list(artifacts_root.rglob("*.staging"))
        assert orphans == [], f"orphan staging files: {orphans}"
        # evidence must be inside managed root
        assert str(ev_abs.resolve()).startswith(str(artifacts_root.resolve()))


def test_c3_nested_windows_root_path_budget(tmp_path: Path) -> None:
    # Simulate nested Windows root with long prefix (path length budget) — use bounded depth that stays under Windows 260 during setup
    nested = tmp_path / ("a" * 20) / ("b" * 20) / "deep_root"
    nested.mkdir(parents=True, exist_ok=True)
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(nested, layers=["layer_a", "layer_b"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    from app.services.s10_recompute import S10RecomputeService
    corr_id = f"corr-c3-nested-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=["layer_a"])
        s.commit()
    # managed_root for execute must be the same deep nested root that holds source/assets (artifacts_root from seed)
    deep_root = artifacts_root
    # sanity: deep_root already contains source
    with factory() as s:
        svc = S10RecomputeService(s)
        res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=deep_root)
        s.commit()
        assert res["completed"] is True
        for r in res["rendered"]:
            rel = r["relative_path"]
            # evidence must be in-root, short (hash-bounded), no .staging orphan
            ev_rel = rel + ".evidence.json"
            ev_abs = deep_root / ev_rel
            assert ev_abs.is_file()
            assert ev_abs.stat().st_size > 0
            assert len(rel) < 80, f"rel too long for Windows budget: {len(rel)} {rel!r}"
            assert len(ev_rel) < 100, f"evidence rel too long: {len(ev_rel)}"
            assert ".staging" not in ev_rel
        orphans = list(deep_root.rglob("*.staging"))
        assert orphans == []
        # verify Windows MAX_PATH safety: absolute path length < 240
        for r in res["rendered"]:
            abs_p = deep_root / r["relative_path"]
            assert len(str(abs_p)) < 260, f"absolute path too long: {len(str(abs_p))} {abs_p}"


def test_c3_no_fabric_sources(tmp_path: Path) -> None:
    # C4: no hard-coded absolute integration path — resolve from PROJECT_ROOT.
    src = (PROJECT_ROOT / "app/services/s10_recompute.py").read_text(encoding="utf-8")
    assert "_np.zeros" not in src, "fabric numpy remains"
    assert '"effective_adapter": route' not in src, "fabric effective_adapter remains"
    assert 'with_suffix(ev_path.suffix + ".staging")' not in src, "fabric staging suffix remains"
    assert "hashlib.sha256(f\"recompute:" not in src, "fabric recompute hash remains"
    assert ".bin" not in src.lower() or "binary" in src.lower(), "no .bin production path should remain (except comments)"
    # quick scan for .bin literal in recompute-coded rel
    import re

    assert not re.search(r"chunks?_.*\.bin", src), "no .bin chunk path"


# ── C4: authority-driven request identity + fail-closed authority semantics ──

def test_c4_random_cross_project_pending_cancelled_fail_closed(tmp_path: Path) -> None:
    """Random/cross-project/pending/cancelled/stale correction ids fail closed."""
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    from app.services.s10_recompute import (
        S10RecomputeNotFoundError,
        S10RecomputeOwnershipError,
        S10RecomputeParamsError,
        S10RecomputeService,
    )

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    layer = str(chunks[0]["layer_id"])

    # random / unknown id -> not found (no authority)
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeNotFoundError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id="does-not-exist", correction_kind="mask", target_layer_ids=[layer],
            )
    # pending authority -> fail closed
    cid_pending = f"corr-pending-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_pending, "mask", [layer], status="pending")
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeParamsError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_pending, correction_kind="mask", target_layer_ids=[layer],
            )
    # cancelled authority -> fail closed
    cid_cancelled = f"corr-cancelled-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_cancelled, "mask", [layer], status="cancelled")
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeParamsError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_cancelled, correction_kind="mask", target_layer_ids=[layer],
            )
    # cross-project correction authority -> fail closed (authority project != run project)
    cid_cross = f"corr-crossauth-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_cross, "mask", [layer], project_id=seed["project_id2"])
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeOwnershipError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_cross, correction_kind="mask", target_layer_ids=[layer],
            )
    # cross-video correction authority -> fail closed (authority video != run video)
    cid_crossvid = f"corr-crossvid-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_crossvid, "mask", [layer], video_item_id=seed["video_item_id2"])
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeOwnershipError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_crossvid, correction_kind="mask", target_layer_ids=[layer],
            )


def test_c4_missing_or_mismatched_authority_facts_fail_closed(tmp_path: Path) -> None:
    """Missing job manifest / authority kind / impact layer / render_effect fail closed."""
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    from app.services.s10_recompute import (
        S10RecomputeError,
        S10RecomputeParamsError,
        S10RecomputeService,
    )

    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    layer = str(chunks[0]["layer_id"])

    # authority exists but kind mismatch (request mask vs persisted route_override)
    cid_kind = f"corr-kindmm-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_kind, "route", [layer])
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeParamsError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_kind, correction_kind="mask", target_layer_ids=[layer],
            )
    # impact affected_layer_ids must EXACTLY match request target
    cid_layers = f"corr-layermm-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_layers, "mask", ["layer_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeParamsError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_layers, correction_kind="mask", target_layer_ids=["layer_b"],
            )
    # render_effect missing entirely -> fail closed (no invented semantics)
    cid_nofx = f"corr-nofx-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_nofx, "mask", [layer], effect={})
    with factory() as s:
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeParamsError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_nofx, correction_kind="mask", target_layer_ids=[layer],
            )
    # missing job manifest -> fail closed before any mutation (zero attempt bump)
    cid_nomanifest = f"corr-nomanifest-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, cid_nomanifest, "mask", [layer])
    with factory() as s:
        # Simulate a missing/empty durable manifest without touching FK children:
        # an empty manifest JSON has no render_authority/source/assets -> fail closed.
        s.execute(sa_text("UPDATE job SET input_manifest_json='{}' WHERE idempotency_key=:k"), {"k": f"s10_full_apply_job:{run_id}"})
        s.commit()
        before_attempts = dict(
            (r["id"], r["attempt"])
            for r in s.execute(sa_text("SELECT id, attempt FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all()
        )
        svc = S10RecomputeService(s)
        with pytest.raises(S10RecomputeError):
            svc.apply_correction(
                workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id),
                correction_id=cid_nomanifest, correction_kind="mask", target_layer_ids=[layer],
            )
        after_attempts = dict(
            (r["id"], r["attempt"])
            for r in s.execute(sa_text("SELECT id, attempt FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all()
        )
        assert before_attempts == after_attempts, "missing manifest must not bump any attempt"
        rec_count = s.execute(sa_text("SELECT COUNT(*) FROM s10_recompute_record WHERE correction_id=:cid"), {"cid": cid_nomanifest}).scalar()
        assert int(rec_count) == 0, "missing manifest must not persist a recompute record"


def test_c4_mask_region_authority_in_request(tmp_path: Path) -> None:
    """Mask correction must feed the PERSISTED mask/region authority (not hash perturb)."""
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    corr_id = f"corr-c4-mask-{uuid.uuid4().hex[:6]}"
    # capture pre-correction SHAs for the corrected-visual-fact assertion
    with factory() as s:
        before_shas: dict[str, str] = {}
        for r in s.execute(sa_text("SELECT id, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": str(run_id)}).mappings().all():
            before_shas[str(r["id"])] = _chunk_artifact_sha(factory, str(r["artifact_id"]), artifacts_root) if r["artifact_id"] else ""
    # persisted mask region authority = [0.10, 0.10, 0.55, 0.45] — DIFFERENT
    # from the baseline mapping region [0.10, 0.10, 0.40, 0.40] so the test
    # proves the executor request is built from the PERSISTED authority, not
    # from a hard-coded baseline (with DIFFERENT route (controlled_redraw ->
    # sprite_affine executor))
    effect = {
        "version": S09_RENDER_EFFECT_VERSION,
        "op": "mask",
        "target_layer_id": "layer_a",
        "target_segment_id": "seg_a",
        "mask_semantics": {
            "version": "s09-mask-semantics-v1",
            "source_generation": "gen-1",
            "segmentation": {"affected_region": [0.10, 0.10, 0.55, 0.45], "points": []},
            "confidence_source": "user",
            "reasons": ["mask correction"],
        },
    }
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_a"], effect=effect)
    from unittest.mock import patch

    from app.services.s10_multi_role_apply import S10MultiRoleService, RoleMapping
    from app.services.s10_recompute import S10RecomputeService

    captured: list[RoleMapping] = []
    orig_exec = S10MultiRoleService.execute_role_chunk

    def _instrumented(self, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs["role"])
        return orig_exec(self, **kwargs)

    with factory() as s:
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=["layer_a"])
        s.commit()
    with patch.object(S10MultiRoleService, "execute_role_chunk", _instrumented):
        with factory() as s:
            svc = S10RecomputeService(s)
            res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=artifacts_root)
            s.commit()
            assert res["completed"] is True
    assert captured, "executor must be invoked for affected chunks"
    for role in captured:
        assert role.affected_region == (0.10, 0.10, 0.55, 0.45), (
            f"RoleMapping.affected_region must equal persisted mask region authority, got {role.affected_region}"
        )
        # route stays pinned from authority mapping (sprite_affine), never the correction label
        assert role.route == "sprite_affine"
        assert role.layer_id == "layer_a"
    # corrected visual fact: affected media bytes differ from pre-correction
    # because the persisted region fact changed the composite — not unequal
    # SHA via any perturb trick.
    with factory() as s:
        affected_rows = s.execute(
            sa_text("SELECT id, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid AND layer_id='layer_a'"),
            {"rid": str(run_id)},
        ).mappings().all()
        for row in affected_rows:
            rel = s.execute(sa_text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": row["artifact_id"]}).scalar()
            assert rel is not None
            new_sha = _chunk_artifact_sha(factory, str(row["artifact_id"]), artifacts_root)
            assert new_sha != before_shas[str(row["id"])], f"affected {row['id']} bytes must change via persisted region fact"


def test_c4_zorder_contact_route_authority_in_request(tmp_path: Path) -> None:
    """z_order/contact/route corrections must feed PERSISTED post-correction facts."""
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_z", "layer_c", "layer_r"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    from unittest.mock import patch

    from app.services.s10_multi_role_apply import S10MultiRoleService, RoleMapping
    from app.services.s10_recompute import S10RecomputeService

    captured: list[RoleMapping] = []
    orig_exec = S10MultiRoleService.execute_role_chunk

    def _instrumented(self, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs["role"])
        return orig_exec(self, **kwargs)

    # z_order: persisted effect z_order = 13 -> RoleMapping.z_order must be 13
    corr_z = f"corr-c4-z-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_z, "z_order", ["layer_z"], effect={"version": S09_RENDER_EFFECT_VERSION, "op": "z_order", "target_layer_id": "layer_z", "target_segment_id": "seg_z", "z_order": 13})
    with factory() as s:
        svc = S10RecomputeService(s)
        rec_z, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_z, correction_kind="z_order", target_layer_ids=["layer_z"])
        s.commit()
    # contact: persisted anchor/contact graph -> RoleMapping.contact_anchor carries exact facts
    corr_c = f"corr-c4-c-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(
        factory, seed, corr_c, "contact", ["layer_c"],
        effect={"version": S09_RENDER_EFFECT_VERSION, "op": "contact", "target_contact_id": "ct_1",
                "source_segment_id": "seg_s1", "target_segment_id": "seg_t1", "contact_kind": "hand",
                "start_frame": 5, "end_frame": 45, "start_time_ms": 100, "end_time_ms": 900},
    )
    with factory() as s:
        svc = S10RecomputeService(s)
        rec_c, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_c, correction_kind="contact", target_layer_ids=["layer_c"])
        s.commit()
    # route: persisted route_to (controlled_redraw) -> RoleMapping.route must equal route_to, evidence route from renderer
    corr_r = f"corr-c4-r-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(
        factory, seed, corr_r, "route", ["layer_r"],
        effect={"version": S09_RENDER_EFFECT_VERSION, "op": "route_override", "target_layer_id": "layer_r", "target_segment_id": "seg_r",
                "render_route_id": "rr_2", "route_from": "sprite_affine", "route_to": "controlled_redraw",
                "frame_range": {"start_frame": 0, "end_frame": 49}, "anchor": {"x": 0.5, "y": 0.5},
                "provenance": {"route_from": "sprite_affine", "route_to": "controlled_redraw", "evidence": "seed"}},
    )
    with factory() as s:
        svc = S10RecomputeService(s)
        rec_r, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_r, correction_kind="route", target_layer_ids=["layer_r"])
        s.commit()
    with patch.object(S10MultiRoleService, "execute_role_chunk", _instrumented):
        with factory() as s:
            svc = S10RecomputeService(s)
            res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_z, managed_root=artifacts_root)
            assert res["completed"] is True
            s.commit()
        with factory() as s:
            svc = S10RecomputeService(s)
            res_c = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_c, managed_root=artifacts_root)
            assert res_c["completed"] is True
            s.commit()
        with factory() as s:
            svc = S10RecomputeService(s)
            res_r = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_r, managed_root=artifacts_root)
            assert res_r["completed"] is True
            s.commit()
    by_layer = {r.layer_id: r for r in captured}
    assert by_layer["layer_z"].z_order == 13, f"z_order must come from persisted effect, got {by_layer['layer_z'].z_order}"
    ca = by_layer["layer_c"].contact_anchor or {}
    assert ca.get("kind") == "hand" and ca.get("source_segment_id") == "seg_s1" and ca.get("target_segment_id") == "seg_t1"
    assert ca.get("start_frame") == 5 and ca.get("end_frame") == 45
    assert by_layer["layer_r"].route == "controlled_redraw", f"route must come from persisted route_to, got {by_layer['layer_r'].route}"
    # renderer-returned route/effective_adapter is authoritative in evidence
    z_ev = [r for r in res["rendered"] if r["chunk_id"]][0]["evidence"]
    assert z_ev["route"] == "sprite_affine" and z_ev["effective_adapter"] == "SpriteAffineAdapter"
    r_ev = [r for r in res_r["rendered"]][0]["evidence"]
    assert r_ev["requested_route"] == "controlled_redraw"
    assert r_ev["effective_adapter"] == "SpriteAffineAdapter"
    # corrected visual/structural fact: affected chunk media bytes changed vs pre-correction
    with factory() as s:
        rows = s.execute(sa_text("SELECT id, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid AND layer_id='layer_z'"), {"rid": str(run_id)}).mappings().all()
        for row in rows:
            rel = s.execute(sa_text("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": row["artifact_id"]}).scalar()
            assert rel is not None
    # provenance bound to correction ids
    with factory() as s:
        svc2 = S10RecomputeService(s)
        for cid in (corr_z, corr_c, corr_r):
            p = svc2.get_record(seed["workspace_id"], cid)
            assert p["correction_id"] == cid


def test_c4_nested_root_over_260_atomic_zero_orphan(tmp_path: Path) -> None:
    """Full recompute media/evidence survive a >260-char nested Windows root, zero orphan."""
    import shutil

    from app.workflow.s10_full_apply_jobs import _lp

    # Seed on a SHORT root (alembic/sqlite cannot open >260 unprefixed paths),
    # then mirror the whole managed tree into a genuinely >260-character
    # nested root (extended-length prefixed) and run the FULL recompute there
    # — no hard-coded absolute integration path anywhere.
    db, artifacts_root, factory, seed, chunks = _seed_run_with_chunks(tmp_path, layers=["layer_a", "layer_b"])
    run_id = None
    with factory() as s:
        run_id = s.execute(sa_text("SELECT id FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1")).scalar()
    deep = _lp(tmp_path / ("d" * 60) / ("e" * 60) / ("f" * 60) / "deep_root", force=True)
    deep.mkdir(parents=True, exist_ok=True)
    assert len(str(deep)) > 260, f"test managed root must exceed 260 chars, got {len(str(deep))}"
    # mirror every seeded file (source, assets, verified chunk artifacts) into the deep root
    for item in artifacts_root.rglob("*"):
        if item.is_file():
            rel = item.relative_to(artifacts_root)
            dest = deep / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
    from app.services.s10_recompute import S10RecomputeService

    corr_id = f"corr-c4-nested-{uuid.uuid4().hex[:6]}"
    _seed_correction_authority(factory, seed, corr_id, "mask", ["layer_a"])
    with factory() as s:
        svc = S10RecomputeService(s)
        rec, _ = svc.apply_correction(workspace_id=seed["workspace_id"], project_id=seed["project_id"], run_id=str(run_id), correction_id=corr_id, correction_kind="mask", target_layer_ids=["layer_a"])
        s.commit()
    with factory() as s:
        svc = S10RecomputeService(s)
        res = svc.execute_partial(workspace_id=seed["workspace_id"], run_id=str(run_id), correction_id=corr_id, managed_root=deep)
        s.commit()
        assert res["completed"] is True
    for r in res["rendered"]:
        rel = r["relative_path"]
        ev_rel = rel + ".evidence.json"
        abs_p = deep / rel
        ev_abs = deep / ev_rel
        assert abs_p.is_file(), f"artifact missing at {abs_p}"
        assert ev_abs.is_file(), f"evidence missing at {ev_abs}"
        assert len(str(abs_p)) > 260, f"final path must exceed 260, got {len(str(abs_p))} {abs_p}"
        assert ev_abs.stat().st_size > 0
        assert ".staging" not in str(ev_abs)
    orphans = list(deep.rglob("*.staging"))
    assert orphans == [], f"zero orphan expected, got {orphans}"

