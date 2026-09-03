"""S10-T04B-C3 (C6A) — bounded executable authority seed (S10-C6A-EXEC).

Runs ONCE per isolated C6A runtime, immediately after the T04C canonical
setup (run-prod-seed.py + post_seed_real_authority.py) and the NOAUTH seed.
It creates a deterministic project whose v2 approval authority IS EXECUTABLE
under the server-derived minimal contract:

  * every manifest-selected segment uses route ``sprite_affine`` (member of
    FULL_APPLY_EXECUTABLE_ROUTES — never a downgrade from mesh_warp/part_rig);
  * every segment carries REAL boxed geometry (segmentation/prompt boxes) so
    the affected region is derivable server-side (never guessed);
  * role mapping + published CharacterPackVersion + CharacterAsset rows +
    image Artifacts (real PNG bytes) satisfy the frozen pack authority;
  * source media + mask artifacts are real decodable bytes pinned as managed
    Artifacts (the worker loads them like the main project's authority).

The T04C-seeded MAIN project (S10-PROD-E2E) is NOT executable under C6A —
its SLM pins shot_b route ``mesh_warp`` and both segments lack geometry, so
minimal submit fails closed (422) there.  This seed provides the executable
positive path the 20-case live UI suite needs.  NOAUTH remains the
incomplete-authority negative; scenario-8 BLOCKED uses genuine rendered-file
tamper on a completed EXEC run (T04A-proven RENDERED_TAMPERED path).

All mutable run/approval truth after this point flows through product
UI/public APIs only. Prints EXEC_SEEDED on success (fail-closed).
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
    wt = cli or os.environ.get("MOTIONFORGE_WORKTREE", "")
    if wt and Path(wt).is_dir():
        return Path(wt)
    return Path("C:/Users/Admin/MotionForge2D-worktrees/s08-integration")


def _resolve_run_root(cli: str | None) -> Path:
    rr = cli or os.environ.get("MOTIONFORGE_ROOT", "")
    if not rr or not Path(rr).is_dir():
        raise SystemExit("seed_exec_project: --runtime-root or MOTIONFORGE_ROOT required (fail-closed)")
    return Path(rr)


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _lp(path: Path, *, force: bool = False) -> Path:
    """Windows extended-length path — mirrors the producer helper byte-for-byte."""
    raw = str(path)
    if os.name == "nt" and not raw.startswith("\\\\?\\") and (force or len(raw) > 259):
        return Path("\\\\?\\" + os.path.abspath(raw))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S10-C6A executable authority seed")
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--worktree", default=None)
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    worktree = _resolve_worktree(args.worktree)
    run_root = _resolve_run_root(args.runtime_root)
    db_path = run_root / "data" / "motionforge.db"
    managed_root = run_root / "artifacts"
    fixture_dir = worktree / "tests" / "fixtures" / "s10_full_apply"

    if not db_path.is_file():
        raise SystemExit(f"seed_exec_project: DB missing at {db_path} (run T04C setup first)")
    manifest_path = fixture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"seed_exec_project: fixture manifest missing at {manifest_path}")

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.models import (
        Artifact,
        Character,
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
        VideoItem,
        Workspace,
    )
    from app.persistence.structural_lock import StructuralLockRepository

    WS = "default"
    NAME = "S10-C6A-EXEC"
    GEN = "1"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    media_src_rel = manifest["media"]["source"]
    media_assets = manifest["media"]["assets"]

    engine = create_engine_for_path(db_path)
    factory = create_session_factory(engine)

    with factory() as s:
        ws = s.get(Workspace, WS)
        if ws is None:
            raise SystemExit("seed_exec_project: workspace 'default' missing")
        existing = s.query(Project).filter_by(name=NAME).first()
        if existing is not None:
            print(f"EXEC_SEEDED project={existing.id} (already present)")
            engine.dispose()
            return 0

        # ── source media: real decodable bytes + artifact pin ──────────────
        managed_root.mkdir(parents=True, exist_ok=True)
        src_abs = managed_root / "s10-c6a-exec" / "src.mp4"
        src_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture_dir / media_src_rel, src_abs)
        src_sha = _sha256_file(src_abs)
        src_art = Artifact(
            workspace_id=WS,
            kind="video",
            relative_path="s10-c6a-exec/src.mp4",
            state="ready",
            sha256=src_sha,
            size_bytes=src_abs.stat().st_size,
        )
        s.add(src_art)
        s.flush()

        project = Project(workspace_id=WS, name=NAME)
        s.add(project)
        s.flush()
        video = VideoItem(
            project_id=project.id,
            title="S10 C6A Exec Demo Video",
            position=1,
            source_artifact_id=src_art.id,
        )
        s.add(video)
        s.flush()
        scene = Scene(
            video_item_id=video.id,
            position=0,
            start_frame=0,
            end_frame=99,
            start_time_ms=0,
            end_time_ms=3300,
            status="pending",
        )
        s.add(scene)
        s.flush()

        # ── character / published pack / per-layer assets ──────────────────
        char = Character(workspace_id=WS, name="CharS10Exec", code="cr_s10_exec")
        s.add(char)
        s.flush()
        pack = CharacterPackVersion(workspace_id=WS, character_id=char.id, version=1, status="published")
        s.add(pack)
        s.flush()
        role = ObjectRole(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            source_generation=GEN,
            name="HeroExec",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        role_b = ObjectRole(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            source_generation=GEN,
            name="HeroExecB",
            kind="character",
            status="confirmed",
        )
        s.add(role_b)
        s.flush()

        pose_slots = ["stand", "sit", "walk"]
        for idx, rel in enumerate(media_assets.values()):
            exec_rel = f"s10-c6a-exec/assets/{Path(rel).name}"
            asset_abs = managed_root / exec_rel
            asset_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture_dir / rel, asset_abs)
            sha = _sha256_file(asset_abs)
            art = Artifact(
                workspace_id=WS,
                kind="image",
                relative_path=exec_rel,
                state="ready",
                sha256=sha,
                size_bytes=asset_abs.stat().st_size,
            )
            s.add(art)
            s.flush()
            s.add(
                CharacterAsset(
                    pack_version_id=pack.id,
                    workspace_id=WS,
                    artifact_id=art.id,
                    pose_slot=pose_slots[idx % len(pose_slots)],
                )
            )
            s.flush()

        # ── real segment rows with BOXED geometry + masks + motion ──────────
        seg_rows: dict[str, OccurrenceSegment] = {}
        sprite_src = {
            "shot_a": fixture_dir / "sprites" / "bg.png",
            "shot_b": fixture_dir / "sprites" / "fg_table.png",
        }
        for sid, seg_range in (("shot_a", (0, 49)), ("shot_b", (50, 99))):
            start, end = seg_range
            seg_role = role if sid == "shot_a" else role_b
            mask_rel = f"s10-c6a-exec/masks/mask_{sid}.png"
            mask_abs = managed_root / mask_rel
            mask_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sprite_src[sid], mask_abs)
            mask_sha = _sha256_file(mask_abs)
            mask_art = Artifact(
                workspace_id=WS,
                kind="image",
                relative_path=mask_rel,
                state="ready",
                sha256=mask_sha,
                size_bytes=mask_abs.stat().st_size,
            )
            s.add(mask_art)
            s.flush()
            seg = OccurrenceSegment(
                workspace_id=WS,
                project_id=project.id,
                video_item_id=video.id,
                role_id=seg_role.id,
                scene_id=scene.id,
                logical_id=f"layer_{sid}",
                name=f"seg_{sid}",
                kind="character",
                start_frame=start,
                end_frame=end,
                start_time_ms=start * 1000 // 30,
                end_time_ms=end * 1000 // 30,
                source_generation=GEN,
                algorithm="fixture",
                algorithm_version="1",
                confidence=0.9,
                confidence_source="manual",
                reasons_json="[]",
                segmentation_json=json.dumps({"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]}),
                prompt_json=json.dumps({"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]}),
                mask_artifact_id=mask_art.id,
                z_order=0 if sid == "shot_a" else 20,
                lineage_version=1,
                idempotency_key=f"s10c6a-exec-seg-{sid}",
            )
            s.add(seg)
            s.flush()
            seg_rows[sid] = seg
            s.add(
                SegmentMotion(
                    workspace_id=WS,
                    occurrence_segment_id=seg.id,
                    transform_type="object_relative",
                    transform_json='{"dx":0,"dy":0}',
                    start_frame=start,
                    end_frame=end,
                    start_time_ms=start * 1000 // 30,
                    end_time_ms=end * 1000 // 30,
                    algorithm="fixture",
                    algorithm_version="1",
                    confidence=0.9,
                    confidence_source="manual",
                    reasons_json="[]",
                    revision=1,
                    idempotency_key=f"s10c6a-exec-mot-{seg.id}",
                )
            )
        s.flush()

        # ── structural lock manifest (EXECUTABLE: all sprite_affine) ───────
        # Manifest segments reference the REAL occurrence_segment row ids so
        # the v2 authority builder resolves persisted rows (never synthetic).
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [seg_rows["shot_a"].id, seg_rows["shot_b"].id],
            "fingerprints": {
                "z_order": hashlib.sha256(b"z-exec").hexdigest(),
                "contacts": hashlib.sha256(b"c-exec").hexdigest(),
            },
            "segments": [
                {
                    "occurrence_segment_id": seg_rows["shot_a"].id,
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 49,
                    "provenance": {"source": "fixture", "generation": GEN},
                },
                {
                    "occurrence_segment_id": seg_rows["shot_b"].id,
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 50,
                    "end_frame": 99,
                    "provenance": {"source": "fixture", "generation": GEN},
                },
            ],
            "policy_version": "structural-thresholds-v1",
        }
        slm, _mc = lock_repo.create_manifest(WS, project.id, video.id, GEN, manifest_dict)
        s.flush()

        # ── render route evidence (bound to the executable SLM) ─────────────
        for sid, seg in seg_rows.items():
            start = int(seg.start_frame)
            end = int(seg.end_frame)
            s.add(
                SegmentRenderRoute(
                    workspace_id=WS,
                    project_id=project.id,
                    video_item_id=video.id,
                    occurrence_segment_id=seg.id,
                    structural_lock_manifest_id=slm.id,
                    route="sprite_affine",
                    anchor_x=0.5,
                    anchor_y=0.5,
                    start_frame=start,
                    end_frame=end,
                    algorithm="fixture",
                    algorithm_version="1",
                    confidence=0.9,
                    confidence_source="manual",
                    reasons_json="[]",
                    idempotency_key=f"s10c6a-exec-route-{seg.id}",
                )
            )
        s.flush()

        # contact evidence (source/segment/contact authority parity)
        s.add(
            SceneGraphContact(
                workspace_id=WS,
                project_id=project.id,
                video_item_id=video.id,
                source_segment_id=seg_rows["shot_b"].id,
                target_segment_id=seg_rows["shot_a"].id,
                contact_kind="hand_phone",
                start_frame=50,
                end_frame=99,
                start_time_ms=50 * 1000 // 30,
                end_time_ms=99 * 1000 // 30,
                algorithm="fixture",
                algorithm_version="1",
                confidence=0.9,
                confidence_source="manual",
                reasons_json="[]",
                revision=1,
                idempotency_key=f"s10c6a-exec-contact-{video.id}",
            )
        )
        s.flush()

        # ── reskin pinned to the executable SLM (one per role mapping) ──────
        reskin = ReskinConfig(
            workspace_id=WS,
            project_id=project.id,
            object_role_id=role.id,
            character_id=char.id,
            pack_version_id=pack.id,
            params_json='{"anchor":{"x":0.5,"y":0.5},"scale":1.0,"fit_mode":"contain","clip_mode":"asset_alpha","offset":{"x":0,"y":0},"rotation_offset_deg":0,"opacity":1.0}',
            structural_lock_manifest_id=slm.id,
            lock_policy_version=slm.policy_version,
            revision=1,
        )
        s.add(reskin)
        s.flush()
        reskin_b = ReskinConfig(
            workspace_id=WS,
            project_id=project.id,
            object_role_id=role_b.id,
            character_id=char.id,
            pack_version_id=pack.id,
            params_json='{"anchor":{"x":0.5,"y":0.5},"scale":1.0,"fit_mode":"contain","clip_mode":"asset_alpha","offset":{"x":0,"y":0},"rotation_offset_deg":0,"opacity":1.0}',
            structural_lock_manifest_id=slm.id,
            lock_policy_version=slm.policy_version,
            revision=1,
        )
        s.add(reskin_b)
        s.flush()

        # ── replacement asset files named by ROLE (worker resolution) ───────
        # The worker resolves the sprite_affine replacement as
        # assets_dir/<layer_id>.png where layer_id == object_role_id
        # (authority mapping layer_id is the role id, not the artifact id).
        # The artifact rows above pin fixture-named rel paths (layer_fg.png);
        # those files exist, but build_render_request additionally requires
        # assets_dir/<role_id>.png to exist.  Materialize one copy per role
        # from the FIRST pose asset of the shared published pack.
        first_asset = (
            s.query(CharacterAsset)
            .filter_by(pack_version_id=pack.id)
            .order_by(CharacterAsset.pose_slot)
            .first()
        )
        if first_asset is not None:
            first_art = s.get(Artifact, first_asset.artifact_id)
            if first_art is not None:
                src_file = managed_root / first_art.relative_path
                for role_obj in (role, role_b):
                    role_file = managed_root / f"s10-c6a-exec/assets/{role_obj.id}.png"
                    shutil.copyfile(src_file, role_file)
        s.commit()

    print(
        f"EXEC_SEEDED project={project.id} video={video.id} reskin={reskin.id} "
        f"pack={pack.id} slm={slm.id} seg={len(seg_rows)}"
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
