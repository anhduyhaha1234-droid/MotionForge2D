"""Shared harness for S12-PUBLIC-AUTHORITY-BRIDGE (B03-B06) tests.

Isolated per-test DB (alembic head) + isolated managed root; every graph is
built through persisted repository/service paths with REAL media bytes.
Multi-scene fixtures seed GLOBAL frame ranges (ruling Q2 test-adapter note:
the sanctioned deterministic extraction provider persists scene-local ranges
for scenes after the first — out of R7 scope; fixtures here must not copy it).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
WS = "default"
GEN = "1"


def h64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _upgrade(db: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")


@dataclass
class Env:
    client: Any
    factory: Any
    svc: Any
    managed_root: Path
    tmp_path: Path


def make_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / f"bridge-{uuid.uuid4().hex[:6]}.db"
    artifacts_root = tmp_path / f"artifacts-{uuid.uuid4().hex[:6]}"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    _upgrade(db)

    from app.persistence import create_engine_for_path, create_session_factory

    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)

    from app.api import deps
    from app.api.app import app
    from app.workflow.job_service import JobService

    svc = JobService(session_factory=factory, managed_root=artifacts_root)
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, WS) is None:
            s.add(Workspace(id=WS, name=WS))
            s.commit()
    from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

    register_s10_full_apply_handler(svc._worker)
    try:
        svc._worker.bind_session_factory(factory)
    except Exception:
        pass
    monkeypatch.setattr(deps, "_job_service", svc, raising=False)

    from fastapi.testclient import TestClient

    client = TestClient(app)
    return Env(
        client=client,
        factory=factory,
        svc=svc,
        managed_root=artifacts_root,
        tmp_path=tmp_path,
    )


def write_source(
    managed_root: Path,
    video_id: str,
    frame_count: int = 120,
    *,
    width: int = 160,
    height: int = 120,
    fps: float = 30.0,
) -> tuple[str, str, int]:
    """Solid-colour per-frame source (distinct frames, deterministic bytes)."""
    from app.persistence.artifacts import hash_file
    from app.services.renderer_routes.composite import write_frames_mp4

    rel = f"bridge/{video_id}/source.mp4"
    abs_p = managed_root / rel
    abs_p.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(frame_count):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :, 0] = (i * 2) % 250
        frame[:, :, 1] = 90
        frame[:, :, 2] = 30
        frames.append(frame)
    write_frames_mp4(frames, abs_p, fps=fps)
    return rel, hash_file(abs_p), abs_p.stat().st_size


def write_asset(
    managed_root: Path,
    video_id: str,
    name: str,
    color_bgra: tuple[int, int, int, int],
    *,
    size: int = 40,
) -> tuple[str, str, int]:
    import cv2

    from app.persistence.artifacts import hash_file

    rel = f"bridge/{video_id}/assets/{name}.png"
    abs_p = managed_root / rel
    abs_p.parent.mkdir(parents=True, exist_ok=True)
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, 0] = color_bgra[0]
    img[:, :, 1] = color_bgra[1]
    img[:, :, 2] = color_bgra[2]
    img[:, :, 3] = color_bgra[3]
    cv2.imwrite(str(abs_p), img)
    return rel, hash_file(abs_p), abs_p.stat().st_size


def build_graph(
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenes: list[tuple[int, int]],
    segments: list[dict[str, Any]],
    frame_count: int = 120,
    dims: tuple[int, int] = (160, 120),
    fps: float = 30.0,
    shot_order_mode: str = "scene",
    with_timeline_probe: bool = False,
    submit_approval: bool = True,
) -> dict[str, Any]:
    """Build a full persisted authority graph and submit the v2 approval.

    ``segments`` entries: role key/name/kind, scene index, start/end (GLOBAL
    frames), route, geometry spec (``box`` / ``boxes`` / ``points_only`` /
    ``none``), visibility, z_order, asset color, optional ``role2`` style.
    ``shot_order_mode``: "scene" (producer shape) | "segment" (legacy
    fixture shape) — used to prove the r7 rulings.
    Returns a seed dict: ids for video/project/checkpoint/segments/roles/etc.
    """
    from sqlalchemy import text

    from app.persistence.models import (
        Character,
        CharacterAsset,
        CharacterPackVersion,
        ObjectRole,
        Project,
        VideoItem,
    )
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository
    from app.services.source_locked_timeline import (
        CODE_BOX_AMBIGUOUS,
        CODE_BOX_MISSING,
        CODE_ROUTE_NOT_EXECUTABLE,
    )

    factory = env.factory
    root = env.managed_root
    vid = f"vid-{uuid.uuid4().hex[:6]}"
    proj = f"proj-{uuid.uuid4().hex[:6]}"
    width, height = dims

    src_rel, src_sha, src_size = write_source(
        root, vid, frame_count, width=width, height=height, fps=fps
    )

    seed: dict[str, Any] = {
        "video_item_id": vid,
        "project_id": proj,
        "frame_count": frame_count,
        "dims": dims,
        "source_rel": src_rel,
        "source_sha": src_sha,
        "source_size": src_size,
        "segments": {},
        "roles": {},
        "assets": {},
        "geometry_codes": {
            "box_missing": CODE_BOX_MISSING,
            "box_ambiguous": CODE_BOX_AMBIGUOUS,
            "route_not_executable": CODE_ROUTE_NOT_EXECUTABLE,
        },
    }

    with factory() as s:
        s.add(Project(id=proj, workspace_id=WS, name="Bridge"))
        s.flush()
        video = VideoItem(
            id=vid,
            project_id=proj,
            title="BridgeVid",
            position=0,
            width=width,
            height=height,
            duration_ms=int(frame_count / fps * 1000),
            fps_num=int(round(fps)),
            fps_den=1,
        )
        s.add(video)
        s.flush()

        from app.persistence.models import Artifact, Job

        src_art = f"art-src-{uuid.uuid4().hex[:6]}"
        s.add(
            Artifact(
                id=src_art,
                workspace_id=WS,
                kind="video",
                relative_path=src_rel,
                state="ready",
                sha256=src_sha,
                size_bytes=src_size,
            )
        )
        s.flush()
        video.source_artifact_id = src_art
        seed["source_artifact_id"] = src_art
        # Backend current generation authority (same pattern as the C8 fixtures)
        s.add(
            Job(
                workspace_id=WS,
                job_type="DISCOVER_OBJECTS",
                owner_type="video_item",
                owner_id=vid,
                state="completed",
                input_generation=GEN,
                input_manifest_json=json.dumps({"source_sha256": src_sha}),
            )
        )
        s.flush()

        # Scenes (GLOBAL ranges, position-ordered)
        scenes_table = __import__(
            "app.persistence.models", fromlist=["Scene"]
        ).Scene
        scene_ids: list[str] = []
        for position, (start, end) in enumerate(scenes):
            scene_id = f"sc-{uuid.uuid4().hex[:6]}"
            s.add(
                scenes_table(
                    id=scene_id,
                    video_item_id=vid,
                    position=position,
                    start_frame=start,
                    end_frame=end,
                    start_time_ms=0,
                    end_time_ms=0,
                    status="pending",
                )
            )
            scene_ids.append(scene_id)
        s.flush()
        seed["scene_ids"] = scene_ids

        # Roles + packs + assets (one per spec role key)
        role_rows: dict[str, dict[str, Any]] = {}
        default_colors = {
            "r1": (0, 0, 255, 255),  # red BGRA
            "r2": (255, 0, 0, 255),  # blue
            "r3": (0, 255, 0, 255),  # green
        }
        for spec in segments:
            key = str(spec["role"])
            if key in role_rows:
                continue
            role_name = str(spec.get("role_name") or key)
            kind = str(spec.get("kind") or "character")
            color = spec.get("asset_color") or default_colors.get(
                key, (255, 255, 0, 255)
            )
            char = f"ch-{uuid.uuid4().hex[:6]}"
            s.add(Character(id=char, workspace_id=WS, name=role_name, code=char))
            s.flush()
            pack = f"pv-{uuid.uuid4().hex[:6]}"
            s.add(
                CharacterPackVersion(
                    id=pack, character_id=char, workspace_id=WS, version=1, status="published"
                )
            )
            s.flush()
            asset_rel, asset_sha, asset_size = write_asset(
                root, vid, f"{key}-{uuid.uuid4().hex[:4]}", color
            )
            asset_art = f"art-asset-{uuid.uuid4().hex[:6]}"
            s.add(
                Artifact(
                    id=asset_art,
                    workspace_id=WS,
                    kind="image",
                    relative_path=asset_rel,
                    state="ready",
                    sha256=asset_sha,
                    size_bytes=asset_size,
                )
            )
            s.flush()
            s.add(
                CharacterAsset(
                    id=f"ca-{uuid.uuid4().hex[:6]}",
                    pack_version_id=pack,
                    workspace_id=WS,
                    pose_slot="base",
                    artifact_id=asset_art,
                )
            )
            role = f"role-{uuid.uuid4().hex[:6]}"
            s.add(
                ObjectRole(
                    id=role,
                    workspace_id=WS,
                    project_id=proj,
                    video_item_id=vid,
                    source_generation=GEN,
                    name=role_name,
                    kind=kind,
                    status="confirmed",
                )
            )
            s.flush()
            params = {
                "anchor": {"x": 0.5, "y": 0.5},
                "scale": 1.0,
                "fit_mode": "contain",
                "clip_mode": "asset_alpha",
                "offset": {"x": 0.0, "y": 0.0},
                "rotation_offset_deg": 0.0,
                "opacity": 1.0,
            }
            rc = f"rc-{uuid.uuid4().hex[:6]}"
            s.add(
                __import__("app.persistence.models", fromlist=["ReskinConfig"]).ReskinConfig(
                    id=rc,
                    workspace_id=WS,
                    project_id=proj,
                    object_role_id=role,
                    character_id=char,
                    pack_version_id=pack,
                    params_json=json.dumps(params, sort_keys=True, separators=(",", ":")),
                    revision=1,
                )
            )
            s.flush()
            role_rows[key] = {
                "role_id": role,
                "pack_id": pack,
                "asset_rel": asset_rel,
                "asset_sha": asset_sha,
                "asset_size": asset_size,
                "asset_artifact_id": asset_art,
                "reskin_config_id": rc,
            }
        seed["roles"] = role_rows

        # Segments (persisted evidence rows)
        seg_repo = StructuralEvidenceRepository(s)
        seg_specs: list[dict[str, Any]] = []
        for spec in segments:
            key = str(spec["role"])
            role = role_rows[key]["role_id"]
            scene_idx = int(spec.get("scene", 0))
            start = int(spec["start"])
            end = int(spec["end"])
            geometry_mode = str(spec.get("geometry", "box"))
            seg_kwargs: dict[str, Any] = {
                "kind": str(spec.get("kind") or "character"),
                "confidence_source": "user",
                "visibility": str(spec.get("visibility") or "visible"),
                "z_order": int(spec.get("z_order") or 0),
            }
            if geometry_mode == "none":
                seg_kwargs["segmentation"] = None
                seg_kwargs["prompt"] = None
            elif geometry_mode == "points_only":
                seg_kwargs["segmentation"] = {"points": [{"x": 5.0, "y": 5.0, "label": "p"}]}
                seg_kwargs["prompt"] = {"points": [{"x": 6.0, "y": 6.0, "label": "p"}]}
            elif geometry_mode == "multi_box":
                seg_kwargs["segmentation"] = {
                    "boxes": [
                        {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0},
                        {"x": 40.0, "y": 20.0, "w": 60.0, "h": 40.0},
                    ]
                }
                seg_kwargs["prompt"] = {"boxes": [{"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}]}
            elif geometry_mode == "cross_key_conflict":
                seg_kwargs["segmentation"] = {
                    "boxes": [{"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}]
                }
                seg_kwargs["prompt"] = {
                    "boxes": [{"x": 30.0, "y": 20.0, "w": 50.0, "h": 50.0}]
                }
            else:  # "box": pixel-scale or normalized box passed explicitly
                box = spec.get("box")
                if box is None:
                    box = {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}
                seg_kwargs["segmentation"] = {"boxes": [dict(box)]}
                seg_kwargs["prompt"] = {"boxes": []}
            mask_art = f"art-mask-{uuid.uuid4().hex[:6]}"
            s.add(
                Artifact(
                    id=mask_art,
                    workspace_id=WS,
                    kind="image",
                    relative_path=f"bridge/{vid}/mask-{uuid.uuid4().hex[:4]}.png",
                    state="ready",
                    sha256=h64(mask_art),
                    size_bytes=64,
                )
            )
            s.flush()
            seg_kwargs["mask_artifact_id"] = mask_art
            seg_rec, _created = seg_repo.create_segment(
                WS,
                proj,
                vid,
                role,
                scene_ids[scene_idx],
                str(spec.get("seg_name") or f"seg-{key}-{len(seg_specs)}"),
                start,
                end,
                0,
                0,
                GEN,
                **seg_kwargs,
            )
            seg_specs.append(
                {
                    "seg_id": str(seg_rec.id),
                    "role_key": key,
                    "route": str(spec.get("route") or "sprite_affine"),
                    "start": start,
                    "end": end,
                    "anchor": spec.get("anchor") or {"x": 0.5, "y": 0.5},
                    "provenance": {"why": "bridge-fixture"},
                }
            )
        for entry in seg_specs:
            seed["segments"][entry["seg_id"]] = entry

        # Structural lock manifest
        lock_repo = StructuralLockRepository(s)
        if shot_order_mode == "segment":
            shot_order = [entry["seg_id"] for entry in seg_specs]
        else:
            shot_order = list(scene_ids)
        manifest_dict = {
            "frame_count": frame_count,
            "timebase": {"fps": float(fps), "time_base": f"1/{int(round(fps))}", "start_time_ms": 0},
            "shot_order": shot_order,
            "fingerprints": {"z_order": h64("z-bridge"), "contacts": h64("c-bridge")},
            "segments": [
                {
                    "occurrence_segment_id": entry["seg_id"],
                    "route": entry["route"],
                    "anchor": dict(entry["anchor"]),
                    "start_frame": entry["start"],
                    "end_frame": entry["end"],
                    "provenance": dict(entry["provenance"]),
                }
                for entry in seg_specs
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _mc = lock_repo.create_manifest(WS, proj, vid, GEN, manifest_dict)
        for entry in seg_specs:
            lock_repo.record_render_route(
                WS,
                proj,
                vid,
                entry["seg_id"],
                entry["route"],
                float(entry["anchor"]["x"]),
                float(entry["anchor"]["y"]),
                int(entry["start"]),
                int(entry["end"]),
                provenance={"why": "bridge-fixture"},
                reasons=["bridge-fixture"],
                structural_lock_manifest_id=manifest.id,
            )
        # Pin the manifest on every role's reskin config
        for row in role_rows.values():
            s.execute(
                text(
                    "UPDATE reskin_config SET structural_lock_manifest_id=:m, lock_policy_version=:p WHERE id=:rc"
                ),
                {"m": manifest.id, "p": manifest.policy_version, "rc": row["reskin_config_id"]},
            )
        s.flush()

        if not submit_approval:
            s.commit()
            seed["checkpoint_id"] = None
            seed["checkpoint_hash"] = None
            seed["checkpoint_revision"] = None
            seed["manifest_id"] = str(manifest.id)
            seed["manifest_hash"] = str(manifest.manifest_hash_hex)
            seed["approval_created"] = False
            seed["authority"] = None
            return seed

        repo = S09ApprovalRepository(s)
        record, created = repo.submit_checkpoint_v2(
            WS,
            reskin_config_id=str(next(iter(role_rows.values()))["reskin_config_id"]),
            expected_reskin_revision=1,
            pack_version_ids=[
                str(role_rows[str(segments[0]["role"])]["pack_id"])
            ],
            note="bridge fixture",
        )
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = str(record.reskin_config_revision)
        seed["manifest_id"] = str(manifest.id)
        seed["manifest_hash"] = str(manifest.manifest_hash_hex)
        seed["approval_created"] = bool(created)

        # Capture the frozen authority for direct consumption tests
        authority = repo.full_apply_authority(str(record.id), WS)
        seed["authority"] = authority
    return seed


def submit_full_apply(env: Env, seed: dict[str, Any], **kwargs: Any) -> Any:
    payload: dict[str, Any] = {
        "video_item_id": seed["video_item_id"],
        "apply_checkpoint_id": seed["checkpoint_id"],
        "expected_checkpoint_hash": seed["checkpoint_hash"],
        "expected_checkpoint_revision": int(seed["checkpoint_revision"]),
    }
    payload.update(kwargs)
    return env.client.post(
        f"/api/v2/projects/{seed['project_id']}/full-apply", json=payload
    )


def run_counts(env: Env) -> tuple[int, int]:
    """(full-apply runs, full-apply durable jobs) — fixture DISCOVER jobs
    (generation authority) are not S10 rows and never counted."""
    from sqlalchemy import text

    with env.factory() as s:
        runs = int(
            s.execute(
                text("SELECT COUNT(*) FROM s10_full_apply_run WHERE workspace_id=:w"),
                {"w": WS},
            ).scalar()
            or 0
        )
        jobs = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM job WHERE workspace_id=:w AND job_type='s10_full_apply'"
                ),
                {"w": WS},
            ).scalar()
            or 0
        )
    return runs, jobs


def cli_get(env: Env, run_id: str) -> dict[str, Any]:
    from sqlalchemy import text

    with env.factory() as s:
        row = s.execute(
            text(
                "SELECT status, frame_count, plan_id, plan_hash FROM s10_full_apply_run WHERE id=:r AND workspace_id=:w"
            ),
            {"r": run_id, "w": WS},
        ).mappings().first()
    return dict(row) if row else {}


def render_authority_for(seed: dict[str, Any]) -> dict[str, Any]:
    """Build the RENDER-AUTHORITY shape the job manifest carries (the worker's
    composition input): scene partition + manifest pins + canonical mapping
    (render-active occurrences) — derived from the frozen full authority."""
    auth = seed["authority"]
    timeline = auth["timeline"]
    shots = [
        {"shot_id": s["shot_id"], "start_frame": s["start_frame"], "end_frame": s["end_frame"]}
        for s in timeline["shots"]
    ]
    mappings = []
    for occ in timeline["occurrences"]:
        if occ["visibility"] not in ("visible", "occluded"):
            continue
        mappings.append(
            {
                "layer_id": occ["layer_id"],
                "role_id": occ["role_id"],
                "route": occ["route"],
                "affected_region": list(occ["affected_region"]),
                "pack_version_id": occ["pack_version_id"],
                "deps": [],
                "start_frame": occ["start_frame"],
                "end_frame": occ["end_frame"],
                "z_order": occ["z_order"],
                "logical_id": occ["logical_id"],
                "lineage_version": occ["lineage_version"],
                "visibility": occ["visibility"],
            }
        )
    mappings.sort(key=lambda m: m["layer_id"])
    return {
        "authority_version": "s09.full-apply-authority/v1",
        "authority_fingerprint": h64("fixture-fingerprint"),
        "approved_checkpoint": {
            "checkpoint_id": seed["checkpoint_id"],
            "checkpoint_hash": seed["checkpoint_hash"],
            "revision": int(seed["checkpoint_revision"]),
        },
        "structural_lock_manifest": {
            "manifest_hash": seed["manifest_hash"],
            "policy_version": "structural-thresholds-v1",
            "source_generation": GEN,
            "frame_count": timeline["frame_count"],
        },
        "scene_manifest": {"shots": shots},
        "mapping": {"mappings": mappings},
        "compatibility_policy": {"policy_version": "structural-thresholds-v1"},
    }


def authorized_manifest(seed: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the job-manifest pins the way the submit route does (role-keyed
    replacement assets + source pins) for direct workflow-layer tests."""
    assets = {}
    for key, row in seed["roles"].items():
        assets[row["role_id"]] = {
            "rel": row["asset_rel"],
            "sha256": row["asset_sha"],
            "size_bytes": row["asset_size"],
            "artifact_id": row["asset_artifact_id"],
        }
    return {
        "source_media_rel": seed["source_rel"],
        "source_media_sha256": seed["source_sha"],
        "source_media_size_bytes": seed["source_size"],
        "project_id": seed["project_id"],
        "video_item_id": seed["video_item_id"],
        "replacement_assets": assets,
    }
