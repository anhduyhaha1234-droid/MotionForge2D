"""S10-T04C-C3 (C4A) post-seed — complete REAL canonical authority via product handlers.

Runs ONCE per isolated runtime, immediately after run-prod-seed.py (SEED phase,
before any run activity).  It completes the persisted authority that the C6
production submit path requires:

  * source media  — real decodable bytes at managed_root/s10-src.mp4 + artifact
                    row pin (sha256/size_bytes) matching the file;
  * per-layer replacement assets — real PNG bytes at
                    managed_root/s10_full_apply/_assets/{layer}.png + Artifact
                    row + CharacterAsset bound to the seeded pack version;
  * structural rows — occurrence_segment / segment_motion / scene_graph_contact
                    / segment_render_route rows proving source/segment/motion/
                    contact/route authority exists (no zero-row fallback).

All writes happen through the app persistence layer / product repositories
(identical style to run-prod-seed.py).  The Playwright run itself probes the
database READ-ONLY.  No stage_c4.py, no input_manifest_json patch, no lease
mutation, no direct reconciler invocation.

Usage: python post_seed_real_authority.py --runtime-root <root> --worktree <wt>
Env fallback: MOTIONFORGE_ROOT / MOTIONFORGE_WORKTREE.  Prints POST_SEEDED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


def _resolve_worktree(cli: str | None) -> Path:
    wt = cli or __import__("os").environ.get("MOTIONFORGE_WORKTREE", "")
    if wt and Path(wt).is_dir():
        return Path(wt)
    return Path("C:/Users/Admin/MotionForge2D-worktrees/s08-integration")


def _resolve_run_root(cli: str | None) -> Path:
    rr = cli or __import__("os").environ.get("MOTIONFORGE_ROOT", "")
    if not rr or not Path(rr).is_dir():
        raise SystemExit("post_seed_real_authority: --runtime-root or MOTIONFORGE_ROOT required (fail-closed)")
    return Path(rr)


def _lp(path: Path, *, force: bool = False) -> Path:
    """Windows extended-length path (>=260) so deep managed roots still work.

    Mirrors the producer helper in app/workflow/s10_full_apply_jobs.py::_lp
    byte-for-byte: deep fixture writes (silhouette masks under the C4A nested
    runtime root) must survive >260-char nesting exactly like producer
    media/evidence I/O.  On this Python/Windows the working extended-length
    form is the pathlib round-tripped ``\\\\?\\`` prefix (str() yields four
    leading backslashes); a hand-built two-backslash ``\\?\\`` string is
    rejected with EINVAL, so the fixture MUST go through this helper.
    """
    raw = str(path)
    if os.name == "nt" and not raw.startswith("\\\\?\\") and (force or len(raw) > 259):
        return Path("\\\\?\\" + os.path.abspath(raw))
    return path


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S10 C4A post-seed")
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--worktree", default=None)
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    worktree = _resolve_worktree(args.worktree)
    run_root = _resolve_run_root(args.runtime_root)
    db_path = run_root / "data" / "motionforge.db"
    managed_root = run_root / "artifacts"
    fixture_dir = worktree / "tests" / "fixtures" / "s10_full_apply"

    if not db_path.is_file():
        raise SystemExit(f"post_seed: DB missing at {db_path} (run seeder first)")
    manifest_path = fixture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"post_seed: fixture manifest missing at {manifest_path}")

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.models import (
        Artifact,
        CharacterAsset,
        CharacterPackVersion,
        ObjectRole,
        OccurrenceSegment,
        Project,
        ReskinConfig,
        Scene,
        SceneGraphContact,
        SegmentMotion,
        SegmentRenderRoute,
        StructuralLockManifest,
        VideoItem,
        Workspace,
    )
    from app.persistence.structural_lock import (
        canonical_manifest_json as _canonical_manifest_json,
        manifest_hash as _manifest_hash,
    )

    WS = "default"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layers = manifest["layers"]
    media_src_rel = manifest["media"]["source"]
    media_assets = manifest["media"]["assets"]

    engine = create_engine_for_path(db_path)
    factory = create_session_factory(engine)

    with factory() as s:
        ws = s.get(Workspace, WS)
        if ws is None:
            raise SystemExit("post_seed: workspace 'default' missing")
        project = s.query(Project).filter_by(name="S10-PROD-E2E").first()
        if project is None:
            raise SystemExit("post_seed: S10-PROD-E2E project missing (seeder must run first)")
        video = s.query(VideoItem).filter_by(project_id=project.id).order_by(VideoItem.position.asc()).first()
        if video is None:
            raise SystemExit("post_seed: video missing")
        reskin = s.query(ReskinConfig).filter_by(project_id=project.id).first()
        if reskin is None:
            raise SystemExit("post_seed: reskin_config missing")
        pack = s.query(CharacterPackVersion).filter_by(workspace_id=WS, character_id=reskin.character_id).order_by(CharacterPackVersion.version.desc()).first()
        if pack is None:
            raise SystemExit("post_seed: pack_version missing")
        # ── S10-T04C-C5: per-logical-layer role authority ────────────────────
        # The v2 full-apply planner emits mapping layer_id = str(role_id)
        # (s10_full_apply.py:265) while the S09 correction impact binds the
        # STABLE logical layer id.  For the correction closure to match chunks
        # one-to-one, EVERY corrected layer must own a DISTINCT role whose id
        # EQUALS the logical layer id ("layer_bg"/"layer_fg" — ObjectRole.id is
        # a free String(36) PK).  ReskinConfig is UNIQUE(project, role): each
        # role gets its own contract row reusing the SAME seeded pack so
        # _build_role_mapping freezes identical pack/asset authority per role
        # (no shared-role mapping dedupe, no duplicate chunk layer_id).
        layers_order = [l["layer_id"] for l in layers if l["layer_id"] in ("layer_bg", "layer_fg")]
        role_by_lid: dict[str, ObjectRole] = {}
        for lid in layers_order:
            role = s.get(ObjectRole, lid)
            if role is None or role.workspace_id != WS or role.project_id != project.id:
                role = ObjectRole(
                    id=lid,
                    workspace_id=WS,
                    project_id=project.id,
                    video_item_id=video.id,
                    source_generation="1",
                    name=f"role_{lid}",
                    kind="character",
                    status="confirmed",
                    revision=1,
                    idempotency_key=f"s10c4a-role-{video.id}-{lid}",
                )
                s.add(role)
            role_by_lid[lid] = role
        s.flush()
        for lid, role in role_by_lid.items():
            cfg = s.query(ReskinConfig).filter_by(project_id=project.id, object_role_id=role.id).first()
            if cfg is None:
                s.add(ReskinConfig(
                    workspace_id=WS,
                    project_id=project.id,
                    object_role_id=role.id,
                    character_id=reskin.character_id,
                    pack_version_id=pack.id,
                    params_json=reskin.params_json,
                    structural_lock_manifest_id=reskin.structural_lock_manifest_id,
                    lock_policy_version=reskin.lock_policy_version,
                    revision=1,
                    idempotency_key=f"s10c4a-reskin-{project.id}-{lid}",
                ))
        s.flush()
        scene = s.query(Scene).filter_by(video_item_id=video.id).order_by(Scene.position.asc()).first()

        managed_root.mkdir(parents=True, exist_ok=True)

        # ── 1. Source media: real decodable file + artifact pin ──────────────
        src_abs = managed_root / "s10-src.mp4"
        shutil.copyfile(fixture_dir / media_src_rel, src_abs)
        src_sha = sha256_file(src_abs)
        src_size = src_abs.stat().st_size
        src_art = s.query(Artifact).filter(Artifact.workspace_id == WS, Artifact.relative_path == "s10-src.mp4").first()
        if src_art is None:
            src_art = Artifact(workspace_id=WS, kind="video", relative_path="s10-src.mp4", state="ready", sha256=src_sha, size_bytes=src_size)
            s.add(src_art)
        else:
            src_art.sha256 = src_sha
            src_art.size_bytes = src_size
            src_art.state = "ready"
        s.flush()

        # ── 2. Per-layer replacement assets: real PNG + Artifact + CharacterAsset ──
        # NOTE: character_asset has UNIQUE(pack_version_id, pose_slot); use bulk
        # deletes (executed immediately) to avoid SQLAlchemy flush-order
        # INSERT-before-DELETE UNIQUE conflicts, and one asset per distinct pose.
        assets_pin: dict[str, dict[str, str]] = {}
        pose_slots = ["stand", "sit", "walk"]
        for idx, (lid, rel) in enumerate(media_assets.items()):
            asset_abs = managed_root / rel
            asset_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture_dir / rel, asset_abs)
            sha = sha256_file(asset_abs)
            size = asset_abs.stat().st_size
            # remove stale rows for this rel (bulk delete executes immediately)
            s.query(Artifact).filter(Artifact.workspace_id == WS, Artifact.relative_path == rel).delete(synchronize_session=False)
            art = Artifact(workspace_id=WS, kind="image", relative_path=rel, state="ready", sha256=sha, size_bytes=size)
            s.add(art)
            s.flush()
            assets_pin[lid] = {"rel": rel, "sha256": sha, "size_bytes": str(size)}
            pose = pose_slots[idx % len(pose_slots)]
            # repoint any existing asset row for this pack+pose (bulk delete then insert)
            s.query(CharacterAsset).filter(
                CharacterAsset.pack_version_id == pack.id, CharacterAsset.pose_slot == pose
            ).delete(synchronize_session=False)
            s.add(CharacterAsset(pack_version_id=pack.id, workspace_id=WS, artifact_id=art.id, pose_slot=pose))
            s.flush()
        s.flush()

        # ── 3. Structural rows: source/segment/motion/contact/route authority ──
        # delete-then-create (idempotent within a runtime re-seed)
        for model in (SegmentRenderRoute, SceneGraphContact, OccurrenceSegment):
            for row in s.query(model).filter(model.video_item_id == video.id).all():
                s.delete(row)
        seg_ids_old = [r[0] for r in s.query(OccurrenceSegment.id).filter(OccurrenceSegment.video_item_id == video.id).all()]
        if seg_ids_old:
            s.query(SegmentMotion).filter(SegmentMotion.occurrence_segment_id.in_(seg_ids_old)).delete(synchronize_session=False)
        s.flush()

        seg_rows: dict[str, OccurrenceSegment] = {}
        for shot in manifest["shots"]:
            sid = shot["shot_id"]
            # C4A: the S09 correction impact binds the STABLE layer key
            # (segment.logical_id) to chunks by layer_id.  For the real
            # route_override authority to drive the recompute closure, the
            # corrected segment's logical_id MUST equal a chunk layer_id
            # (layer_bg/layer_fg/layer_phone) — otherwise impact layer binding
            # matches zero chunks and closure is empty (fail-closed 422).
            layer_binding = "layer_bg" if sid == "shot_a" else "layer_fg"
            seg = OccurrenceSegment(
                # S10-T04C-C5: the segment PRIMARY KEY is pinned to the SLM
                # shot name ("shot_a"/"shot_b").  The full-apply planner emits
                # shot_id = occurrence_segment_id (s10_full_apply.py:262) and
                # the structural-compare gate compares chunk shot_ids against
                # the pinned SLM shot_order fail-closed, so the seeded rows
                # MUST carry the stable shot-name ids instead of random UUIDs.
                # Every other consumer treats occurrence_segment.id as an
                # opaque FK (segment_render_route / segment_motion / mask
                # artifacts / correction impact), so the pin is transparent.
                id=sid,
                workspace_id=WS,
                project_id=project.id,
                video_item_id=video.id,
                role_id=role_by_lid[layer_binding].id,
                scene_id=scene.id if scene else None,
                logical_id=layer_binding,
                name=f"seg_{sid}",
                kind="character",
                start_frame=shot["start_frame"],
                end_frame=shot["end_frame"],
                start_time_ms=shot["start_frame"] * 1000 // 30,
                end_time_ms=shot["end_frame"] * 1000 // 30,
                source_generation="1",
                algorithm="fixture",
                algorithm_version="1",
                confidence=0.9,
                confidence_source="manual",
                reasons_json="[]",
                z_order=0,
                lineage_version=1,
                segmentation_json=json.dumps({
                    "points": [],
                    "boxes": [{
                        "x": 0.08 if layer_binding == "layer_bg" else 0.42,
                        "y": 0.06 if layer_binding == "layer_bg" else 0.38,
                        "w": 0.84 if layer_binding == "layer_bg" else 0.31,
                        "h": 0.60 if layer_binding == "layer_bg" else 0.44,
                    }],
                }),
                idempotency_key=f"s10c4a-seg-{video.id}-{sid}",
            )
            s.add(seg)
            s.flush()
            seg_rows[sid] = seg
            s.add(SegmentMotion(
                workspace_id=WS,
                occurrence_segment_id=seg.id,
                transform_type="object_relative",
                transform_json='{"dx":0,"dy":0}',
                start_frame=shot["start_frame"],
                end_frame=shot["end_frame"],
                start_time_ms=shot["start_frame"] * 1000 // 30,
                end_time_ms=shot["end_frame"] * 1000 // 30,
                algorithm="fixture",
                algorithm_version="1",
                confidence=0.9,
                confidence_source="manual",
                reasons_json="[]",
                revision=1,
                idempotency_key=f"s10c4a-mot-{seg.id}",
            ))
            # S10-T04C-C5: ONE executable route decision per segment.
            # sprite_affine ∈ FULL_APPLY_EXECUTABLE_ROUTES — a non-executable
            # seeded route (e.g. mesh_warp) freezes the v2 authority as
            # non-executable (fail closed), while pre-seeding the correction's
            # route_to (pose_swap) would collide with the route_override INSERT
            # under UNIQUE(occurrence_segment_id, route, start_frame).
            s.add(SegmentRenderRoute(
                workspace_id=WS,
                project_id=project.id,
                video_item_id=video.id,
                occurrence_segment_id=seg.id,
                structural_lock_manifest_id=reskin.structural_lock_manifest_id,
                route="sprite_affine",
                anchor_x=0.5,
                anchor_y=0.5,
                start_frame=shot["start_frame"],
                end_frame=shot["end_frame"],
                algorithm="fixture",
                algorithm_version="1",
                confidence=0.9,
                confidence_source="manual",
                reasons_json="[]",
                idempotency_key=f"s10c4a-route-{seg.id}",
            ))
        s.flush()
        for edge in manifest["contact_edges"]:
            seg_b = seg_rows.get("shot_b")
            seg_a = seg_rows.get("shot_a")
            if seg_b is not None and seg_a is not None:
                s.add(SceneGraphContact(
                    workspace_id=WS,
                    project_id=project.id,
                    video_item_id=video.id,
                    source_segment_id=seg_b.id,
                    target_segment_id=seg_a.id,
                    contact_kind=edge["contact_kind"],
                    start_frame=edge["start_frame"],
                    end_frame=edge["end_frame"],
                    start_time_ms=edge["start_frame"] * 1000 // 30,
                    end_time_ms=edge["end_frame"] * 1000 // 30,
                    algorithm="fixture",
                    algorithm_version="1",
                    confidence=0.9,
                    confidence_source="manual",
                    reasons_json="[]",
                    revision=1,
                    idempotency_key=f"s10c4a-contact-{video.id}-{edge['edge_id']}",
                ))
        s.flush()

        # ── 4. Silhouette mask authority: real PNG bytes + Artifact rows + per-segment mask_artifact_id ──
        # C4A gate measures clipping via silhouette reuse (route 1290-1299):
        # every segment MUST carry mask_artifact_id and at least one
        # source-generation segment must pin a silhouette artifact, otherwise
        # clipping is None -> CLIPPING_MISSING BLOCKED (fail-closed).  These are
        # real decodable PNG bytes copied from the fixture bundle (sprites).
        mask_rows: dict[str, Artifact] = {}
        for sid, seg in seg_rows.items():
            sprite_src = {
                "shot_a": fixture_dir / "sprites" / "bg.png",
                "shot_b": fixture_dir / "sprites" / "fg_table.png",
            }.get(sid, fixture_dir / "sprites" / "bg.png")
            mask_rel = f"s10_full_apply/masks/mask_{sid}.png"
            mask_abs = managed_root / mask_rel
            mask_abs.parent.mkdir(parents=True, exist_ok=True)
            mask_lp = _lp(mask_abs)
            shutil.copyfile(sprite_src, mask_lp)
            mask_sha = sha256_file(mask_lp)
            mask_size = mask_lp.stat().st_size
            # remove stale mask rows for this rel (bulk delete executes immediately)
            s.query(Artifact).filter(
                Artifact.workspace_id == WS, Artifact.relative_path == mask_rel
            ).delete(synchronize_session=False)
            mask_art = Artifact(
                workspace_id=WS, kind="image", relative_path=mask_rel,
                state="ready", sha256=mask_sha, size_bytes=mask_size,
            )
            s.add(mask_art)
            s.flush()
            mask_rows[sid] = mask_art
            seg.mask_artifact_id = mask_art.id
        s.flush()

        # ── 5. Structural lock manifest: real segments (source cut authority) ──
        # C4A gate derives source_cut_frames from manifest segments interior
        # start_frame boundaries (route 1120-1132) and annotations from
        # shot_order + cut_frames + segment rows (route 1304-1314); an empty
        # segments list yields CUT_FRAMES_MISSING / ANNOTATIONS_MISSING.  We
        # update the pinned manifest with the REAL occurrence segment rows and
        # recompute its canonical manifest_hash so the route revalidation
        # (route 925-933) still passes.
        slm = None
        if reskin.structural_lock_manifest_id:
            slm = s.get(StructuralLockManifest, reskin.structural_lock_manifest_id)
        if slm is not None:
            md = json.loads(slm.manifest_json)
            md["segments"] = []
            for sid, seg in seg_rows.items():
                md["segments"].append({
                    "occurrence_segment_id": seg.id,
                    # executable at BOTH freeze sites: SLM manifest segments
                    # (RENDERER_ROUTES enum at approval) AND the planner
                    # executable set (FULL_APPLY_EXECUTABLE_ROUTES).
                    "route": "sprite_affine",
                    "anchor": {"x": 0.0, "y": 0.0},
                    "start_frame": int(seg.start_frame),
                    "end_frame": int(seg.end_frame),
                    "provenance": {"source": "fixture", "generation": "1"},
                })
            canonical = _canonical_manifest_json(md)
            slm.manifest_json = canonical
            slm.manifest_hash = _manifest_hash(canonical)
            s.flush()
        s.commit()

        n_seg = s.query(OccurrenceSegment).filter(OccurrenceSegment.video_item_id == video.id).count()
        n_mot = s.query(SegmentMotion).filter(SegmentMotion.workspace_id == WS).count()
        n_contact = s.query(SceneGraphContact).filter(SceneGraphContact.workspace_id == WS).count()
        n_route = s.query(SegmentRenderRoute).filter(SegmentRenderRoute.workspace_id == WS).count()
        n_art = s.query(Artifact).filter(Artifact.workspace_id == WS).count()
        n_mask = len(mask_rows)
        print(
            "POST_SEEDED "
            f"project={project.id} video={video.id} pack={pack.id} "
            f"source_rel=s10-src.mp4 source_sha={src_sha[:12]} source_size={src_size} "
            f"assets={len(assets_pin)} seg={n_seg} motion={n_mot} contact={n_contact} route={n_route} artifacts={n_art} masks={n_mask}"
        )
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
