"""S07-T03 REAL VERTICAL seed helper (correction C1).

Seeds an isolated MOTIONFORGE_ROOT temp tree through PRODUCTION schemas:

- Durable SQLite via alembic head (Workspace/Projects/VideoItems/Scenes/
  ObjectRoles/ObjectOccurrences/Characters/PackVersions/Assets/Jobs).
- Legacy ``projects/<id>/project.json`` files (the v1 analyze chain gate
  ``pwf.get_project`` reads them from disk — root cause of the previous
  "Không đọc được trạng thái phân tích" failure).
- Completed ANALYZE_MEDIA import + GENERATE_PROXY + scene_detect Jobs per
  video so ``chain_state`` reports ``chain_status="completed"`` (the Object
  Gallery hard gate).
- Published packs satisfy the C1 CORE_POSE_SLOTS policy (F-B parity).
- DRAFT packs ship REAL PNG files (alpha >= threshold, 160x160) + ready
  Artifact rows with true size/sha256 so publishing them through the
  production API exercises the full publish validation gate.

Prints ONE JSON line with every seeded id (captured into seed.json).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(os.environ["MOTIONFORGE_ROOT"])
DB_PATH = ROOT / "data" / "motionforge.db"
print(f"Seeding real-vertical temp root {ROOT}", file=sys.stderr)
(ROOT / "data").mkdir(parents=True, exist_ok=True)
(ROOT / "artifacts").mkdir(parents=True, exist_ok=True)
(ROOT / "projects").mkdir(parents=True, exist_ok=True)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH.as_posix()}")
command.upgrade(cfg, "head")

from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from app.persistence import create_engine_for_path, create_session_factory  # noqa: E402
from app.persistence.models import (  # noqa: E402
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Job,
    ObjectOccurrence,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)

engine = create_engine_for_path(DB_PATH)
factory = create_session_factory(engine)

WS = "default"
CORE_SLOTS = ("front", "three_quarter", "side", "back", "sitting", "walking")
MANAGED_ARTIFACTS = ROOT / "artifacts"


def write_pose_png(rel: str) -> tuple[int, str]:
    """Write a REAL RGBA pose PNG (alpha=200 -> real transparency) and
    return (size_bytes, sha256) exactly as the publish validator checks."""
    target = MANAGED_ARTIFACTS / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGBA", (160, 160), (110, 70, 190, 200)).save(buf, format="PNG")
    data = buf.getvalue()
    target.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()


def attach_real_assets(s, pack_version_id: str, count_seed: str) -> None:
    """Six CharacterAssets backed by ready Artifacts + REAL on-disk files."""
    for idx, slot in enumerate(CORE_SLOTS):
        rel = f"poses/{count_seed}_{idx}_{slot}.png"
        size, sha = write_pose_png(rel)
        art = Artifact(
            workspace_id=WS,
            kind="image",
            state="ready",
            relative_path=rel,
            mime_type="image/png",
            size_bytes=size,
            sha256=sha,
        )
        s.add(art)
        s.flush()
        s.add(
            CharacterAsset(
                pack_version_id=pack_version_id,
                workspace_id=WS,
                pose_slot=slot,
                artifact_id=art.id,
            )
        )


def attach_stub_assets(s, pack_version_id: str, sha_prefix: str) -> None:
    """Six asset rows for packs pinned/evaluated but never re-published.

    Mirrors the accepted S07 pytest fixture pattern: compatibility policy
    checks slot completeness + published status only; files are validated
    exclusively by the publish gate (which these packs never traverse).
    """
    for slot in CORE_SLOTS:
        art = Artifact(
            workspace_id=WS,
            kind="image",
            state="ready",
            relative_path=f"artifacts/{uuid.uuid4().hex}.png",
            mime_type="image/png",
            size_bytes=100,
            sha256=sha_prefix * 64,
        )
        s.add(art)
        s.flush()
        s.add(
            CharacterAsset(
                pack_version_id=pack_version_id,
                workspace_id=WS,
                pose_slot=slot,
                artifact_id=art.id,
            )
        )


def seed_chain_jobs(s, project: Project, video: VideoItem) -> None:
    """Completed import/proxy/scene Jobs => chain_status 'completed'."""
    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    sha = hashlib.sha256(video.id.encode()).hexdigest()
    manifest = json.dumps(
        {
            "source_sha256": sha,
            "title": "seed-source.mp4",
            "video_item_id": video.id,
            "project_id": project.id,
            "workspace_id": WS,
        }
    )

    def completed_job(job_type: str, key: str, offset_min: int) -> Job:
        return Job(
            workspace_id=WS,
            job_type=job_type,
            owner_type="video_item",
            owner_id=video.id,
            state="completed",
            idempotency_key=key,
            input_generation="1",
            input_manifest_json=manifest if job_type == "ANALYZE_MEDIA" else "{}",
            progress=100.0,
            resource_class="cpu_light",
            priority=50,
            max_attempts=3,
            attempt=1,
            started_at=base + timedelta(minutes=offset_min),
            finished_at=base + timedelta(minutes=offset_min + 1),
        )

    s.add(
        completed_job(
            "ANALYZE_MEDIA",
            f"ANALYZE_MEDIA:video_item:{video.id}:{sha}:1",
            0,
        )
    )
    s.add(
        completed_job(
            "GENERATE_PROXY",
            f"GENERATE_PROXY:video_item:{video.id}:{sha}:1",
            2,
        )
    )
    s.add(
        completed_job(
            "ANALYZE_MEDIA",
            f"ANALYZE_MEDIA:scene_detect:video_item:{video.id}:{sha}:1",
            4,
        )
    )


def write_project_json(project: Project) -> None:
    """Legacy v1 chain gate: pwf.get_project() reads this from disk."""
    pdir = ROOT / "projects" / project.id
    pdir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    payload = {
        "version": "2.0.0",
        "name": project.name,
        "source_video": f"projects/{project.id}/seed-source.mp4",
        "channel_id": "",
        "task_status": "completed",
        "created_at": now,
        "updated_at": now,
    }
    (pdir / "project.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


with factory() as s:
    s.execute(
        sqlite_insert(Workspace)
        .values(id=WS, name=WS)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )

    # ── Characters ────────────────────────────────────────────────────────
    char_a = Character(workspace_id=WS, name="RealVerticalChar", code=f"rva_{uuid.uuid4().hex[:6]}")
    char_b = Character(workspace_id=WS, name="RealVerticalCharB", code=f"rvb_{uuid.uuid4().hex[:6]}")
    char_prop = Character(
        workspace_id=WS,
        name="RealPropChar",
        code=f"rvp_{uuid.uuid4().hex[:6]}",
        character_type="prop",
    )
    s.add_all([char_a, char_b, char_prop])
    s.flush()

    # Published v1 packs (UI pin targets; stub assets suffice — never republished)
    pv_a1 = CharacterPackVersion(character_id=char_a.id, workspace_id=WS, version=1, status="published")
    pv_b1 = CharacterPackVersion(character_id=char_b.id, workspace_id=WS, version=1, status="published")
    pv_prop = CharacterPackVersion(character_id=char_prop.id, workspace_id=WS, version=1, status="published")
    s.add_all([pv_a1, pv_b1, pv_prop])
    s.flush()
    attach_stub_assets(s, pv_a1.id, "a")
    attach_stub_assets(s, pv_b1.id, "b")
    attach_stub_assets(s, pv_prop.id, "c")

    # DRAFT next versions WITH REAL files — published through the production
    # API during the spec run (full validation gate: files/sha/alpha/resolution)
    pv_a2 = CharacterPackVersion(character_id=char_a.id, workspace_id=WS, version=2, status="draft")
    pv_b2 = CharacterPackVersion(character_id=char_b.id, workspace_id=WS, version=2, status="draft")
    s.add_all([pv_a2, pv_b2])
    s.flush()
    attach_real_assets(s, pv_a2.id, f"deskdraft_{uuid.uuid4().hex[:6]}")
    attach_real_assets(s, pv_b2.id, f"mobdraft_{uuid.uuid4().hex[:6]}")

    # ── Projects A/B/C with video + scene + role (+1 occurrence each) ────
    seeds: list[dict] = []
    for letter in ("A", "B", "C"):
        proj = Project(workspace_id=WS, name=f"RealVerticalProj{letter}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title=f"SeedVid{letter}", position=0, status="objects_ready")
        s.add(vid)
        s.flush()
        scene = Scene(
            video_item_id=vid.id,
            position=0,
            start_frame=0,
            end_frame=99,
            start_time_ms=0,
            end_time_ms=4000,
            status="approved",
        )
        s.add(scene)
        s.flush()
        role = ObjectRole(
            workspace_id=WS,
            project_id=proj.id,
            video_item_id=vid.id,
            source_generation="1",
            name=f"RealHero{letter}",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        s.add(
            ObjectOccurrence(
                workspace_id=WS,
                project_id=proj.id,
                video_item_id=vid.id,
                role_id=role.id,
                scene_id=scene.id,
                frame_index=10,
                time_ms=400,
                bbox_x=10,
                bbox_y=10,
                bbox_w=64,
                bbox_h=64,
                confidence=0.92,
                confidence_source="model",
                review_state="accepted",
            )
        )
        s.flush()
        seed_chain_jobs(s, proj, vid)
        s.commit()
        write_project_json(proj)
        seeds.append({"proj": proj, "vid": vid, "role": role})

    out = {
        "projectId": seeds[0]["proj"].id,
        "projectId2": seeds[1]["proj"].id,
        "projectId3": seeds[2]["proj"].id,
        "videoId": seeds[0]["vid"].id,
        "videoId2": seeds[1]["vid"].id,
        "videoId3": seeds[2]["vid"].id,
        "roleId": seeds[0]["role"].id,
        "roleId2": seeds[1]["role"].id,
        "roleId3": seeds[2]["role"].id,
        "characterId": char_a.id,
        "characterId2": char_b.id,
        "propCharacterId": char_prop.id,
        "packVersionId": pv_a1.id,
        "draftPackVersionId": pv_a2.id,
        "packVersionId2": pv_b1.id,
        "draftPackVersionId2": pv_b2.id,
        "propPackVersionId": pv_prop.id,
    }
    s.commit()

print(json.dumps(out))
