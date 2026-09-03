"""S10-T04B-C3 (C6) — bounded noauth project seed (S10-C6-NOAUTH).

Runs ONCE per isolated C6 runtime, immediately after the T04C canonical
setup (run-prod-seed.py + post_seed_real_authority.py).  It creates a
deterministic SECOND project whose video/reskin checkpoint has NO pinned
StructuralLockManifest (missing-authority path).  The production
structural-compare gate then truthfully returns BLOCKED SOURCE_LOCK_MISSING
for a completed run of this project — a genuine missing-authority verdict
through the supported product contract, used by the scenario 8 Review-gate
negative branch.

Fixture shortcut enumeration (justified, no public creation API exists):
  - Project/VideoItem/Scene/ReskinConfig/CharacterPackVersion/CharacterAsset/
    ObjectRole rows via ORM — same canonical style as output/s10/run-prod-seed.py
    (there is no POST /api/v2/projects or equivalent public creator).
  - Source media + replacement asset BYTES are copied from the canonical S10
    fixture (real decodable MP4/PNG) and pinned as managed Artifacts — the
    worker loads them like the main project's authority (no media injection
    into a run; the run itself is created through the public submit API).

All mutable run/approval truth after this point flows through product
UI/public APIs only. Prints NOAUTH_SEEDED on success (fail-closed).
"""
from __future__ import annotations

import argparse
import hashlib
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
        raise SystemExit("seed_noauth_project: --runtime-root or MOTIONFORGE_ROOT required (fail-closed)")
    return Path(rr)


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S10-C6 noauth project seed")
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--worktree", default=None)
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    worktree = _resolve_worktree(args.worktree)
    run_root = _resolve_run_root(args.runtime_root)
    db_path = run_root / "data" / "motionforge.db"
    managed_root = run_root / "artifacts"
    fixture_dir = worktree / "tests" / "fixtures" / "s10_full_apply"

    if not db_path.is_file():
        raise SystemExit(f"seed_noauth_project: DB missing at {db_path} (run T04C setup first)")
    manifest_path = fixture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"seed_noauth_project: fixture manifest missing at {manifest_path}")

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.models import (
        Artifact,
        Character,
        CharacterAsset,
        CharacterPackVersion,
        ObjectRole,
        Project,
        ReskinConfig,
        Scene,
        VideoItem,
        Workspace,
    )

    WS = "default"
    NAME = "S10-C6-NOAUTH"
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    media_src_rel = manifest["media"]["source"]
    media_assets = manifest["media"]["assets"]

    engine = create_engine_for_path(db_path)
    factory = create_session_factory(engine)

    with factory() as s:
        ws = s.get(Workspace, WS)
        if ws is None:
            raise SystemExit("seed_noauth_project: workspace 'default' missing")
        existing = s.query(Project).filter_by(name=NAME).first()
        if existing is not None:
            print(f"NOAUTH_SEEDED project={existing.id} (already present)")
            engine.dispose()
            return 0

        # ── source media: real decodable bytes + artifact pin ──────────────
        # NOTE: distinct relative paths under s10-c6-noauth/ — the shared
        # fixture asset paths are already owned by the MAIN project's
        # post_seed artifacts (UNIQUE workspace_id+relative_path).
        managed_root.mkdir(parents=True, exist_ok=True)
        src_abs = managed_root / "s10-c6-noauth" / "src.mp4"
        src_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture_dir / media_src_rel, src_abs)
        src_sha = _sha256_file(src_abs)
        src_art = Artifact(
            workspace_id=WS,
            kind="video",
            relative_path="s10-c6-noauth/src.mp4",
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
            title="S10 C6 Noauth Demo Video",
            position=1,
            source_artifact_id=src_art.id,
        )
        s.add(video)
        s.flush()
        s.add(
            Scene(
                video_item_id=video.id,
                position=0,
                start_frame=0,
                end_frame=99,
                start_time_ms=0,
                end_time_ms=3300,
                status="pending",
            )
        )
        s.flush()

        # ── character / pack / per-layer assets (executable replacement) ───
        char = Character(workspace_id=WS, name="CharS10NoAuth", code="cr_s10_noauth")
        s.add(char)
        s.flush()
        pack = CharacterPackVersion(workspace_id=WS, character_id=char.id, version=1, status="published")
        s.add(pack)
        s.flush()
        role = ObjectRole(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            source_generation="1",
            name="HeroNoAuth",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()

        pose_slots = ["stand", "sit", "walk"]
        for idx, rel in enumerate(media_assets.values()):
            noauth_rel = f"s10-c6-noauth/assets/{Path(rel).name}"
            asset_abs = managed_root / noauth_rel
            asset_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture_dir / rel, asset_abs)
            sha = _sha256_file(asset_abs)
            art = Artifact(
                workspace_id=WS,
                kind="image",
                relative_path=noauth_rel,
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

        # ── reskin config WITHOUT structural lock manifest (missing authority) ──
        reskin = ReskinConfig(
            workspace_id=WS,
            project_id=project.id,
            object_role_id=role.id,
            character_id=char.id,
            pack_version_id=pack.id,
            params_json='{"anchor":{"x":0.5,"y":0.5},"scale":1.0,"fit_mode":"contain","clip_mode":"asset_alpha","offset":{"x":0,"y":0},"rotation_offset_deg":0,"opacity":1.0}',
            structural_lock_manifest_id=None,
            lock_policy_version=None,
            revision=1,
        )
        s.add(reskin)
        s.flush()
        s.commit()

    print(f"NOAUTH_SEEDED project={project.id} video={video.id} reskin={reskin.id} pack={pack.id}")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
