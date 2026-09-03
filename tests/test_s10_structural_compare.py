"""Tests for S10-T04A structural comparison and review-entry gate.

Covers all five binary acceptance bullets:
 1) exact frame_count / timebase / shot order / cut frames
 2) trajectory median/P95, scale P95, rotation P95, contact P95 thresholds
 3) z-order / visibility / silhouette clipping guards
 4) missing/empty/NaN metric, missing annotation, wrong policy version
 5) REVIEW_REQUIRED vs BLOCKED with actionable role/layer/segment/route pointer
"""

from __future__ import annotations

from app.services.s10_structural_compare import (
    CONTACT_P95_MAX_PCT,
    ROTATION_P95_MAX_DEG,
    SCALE_P95_MAX_PCT,
    S10StructuralCompareService,
    TRAJECTORY_MEDIAN_MAX_PCT,
    TRAJECTORY_P95_MAX_PCT,
)


def _passing_kwargs(policy: str = "v1") -> dict:
    return {
        "source_frame_count": 100,
        "rendered_frame_count": 100,
        "source_fps_num": 30,
        "source_fps_den": 1,
        "rendered_fps_num": 30,
        "rendered_fps_den": 1,
        "source_shot_order": ["shot_a", "shot_b", "shot_c"],
        "rendered_shot_order": ["shot_a", "shot_b", "shot_c"],
        "source_cut_frames": [30, 60, 90],
        "rendered_cut_frames": [30, 60, 90],
        "trajectory_errors": [0.1, 0.2, 0.15, 0.3],
        "scale_errors": [0.5, 1.0, 0.8],
        "rotation_errors": [0.5, 1.0, 0.9],
        "contact_errors": [0.1, 0.2, 0.15],
        "z_order_inversions": 0,
        "visibility_events": 0,
        "clipping_via_silhouette_reuse": False,
        "policy_version": policy,
        "expected_policy_version": policy,
        "annotations": {
            "shot_order": ["shot_a", "shot_b"],
            "cut_frames": [30, 60],
            "z_order": [{"a": 1}],
            "visibility": [{"v": 1}],
        },
        "context": {
            "role": "char_hero",
            "layer": "character",
            "segment": "seg_001",
            "route": "sprite_affine",
        },
    }


# ── 1) REVIEW_REQUIRED only after all checks pass ──────────────────────────


def test_pass_enters_review_required() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    r = svc.compare(**kw)
    assert r.status == "REVIEW_REQUIRED"
    assert r.passed is True
    assert len(r.failures) == 0
    # every gate must be PASS
    for k in ("frame_count", "timebase", "shot_order", "cut_frames", "trajectory", "scale", "rotation", "contact", "z_order", "visibility", "clipping", "policy_version", "annotations"):
        assert r.checks[k] == "PASS", f"{k} should be PASS got {r.checks[k]}"


def test_review_required_deterministic_twice() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    r1 = svc.compare(**kw)
    r2 = svc.compare(**kw)
    assert r1.to_dict() == r2.to_dict()


# ── 2) exact frame count / timebase / shot order / cut frames ───────────────


def test_frame_count_mismatch_blocks_with_actionable_pointer() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["rendered_frame_count"] = 99
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "FRAME_COUNT_MISMATCH" for f in r.failures)
    # actionable pointer
    f = next(x for x in r.failures if x.code == "FRAME_COUNT_MISMATCH")
    assert f.role == "char_hero"
    assert f.layer == "character"
    assert f.segment == "seg_001"
    assert f.route == "sprite_affine"
    assert "frame_count" in f.reason.lower() or "mismatch" in f.reason.lower()


def test_timebase_mismatch_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["rendered_fps_num"] = 24
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "TIMEBASE_MISMATCH" for f in r.failures)
    assert any("timebase" in f.reason.lower() for f in r.failures)


def test_shot_order_wrong_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["rendered_shot_order"] = ["shot_a", "shot_c", "shot_b"]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "SHOT_ORDER_MISMATCH" for f in r.failures)


def test_cut_drift_blocks_with_segment_pointer() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    # drift 1 frame at index 1 (60 -> 61) exceeds tolerance 0
    kw["rendered_cut_frames"] = [30, 61, 90]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "CUT_DRIFT" for f in r.failures)
    f = next(x for x in r.failures if x.code == "CUT_DRIFT")
    assert "cut_1" in f.segment or "drift" in f.reason.lower()
    assert f.metric == "cut_frames"


# ── 3) trajectory / scale / rotation / contact thresholds ────────────────────


def test_trajectory_median_exceeded_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    # median 0.8 > 0.5 threshold
    kw["trajectory_errors"] = [0.8, 0.9, 0.7]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "TRAJECTORY_MEDIAN_EXCEEDED" for f in r.failures)
    f = next(x for x in r.failures if x.code == "TRAJECTORY_MEDIAN_EXCEEDED")
    assert f.threshold == TRAJECTORY_MEDIAN_MAX_PCT
    assert "trajectory" in f.reason.lower()


def test_trajectory_p95_exceeded_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    # median small but P95 large
    kw["trajectory_errors"] = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 5.0]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "TRAJECTORY_P95_EXCEEDED" for f in r.failures)
    f = next(x for x in r.failures if x.code == "TRAJECTORY_P95_EXCEEDED")
    assert f.threshold == TRAJECTORY_P95_MAX_PCT


def test_scale_p95_exceeded_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["scale_errors"] = [0.1, 0.1, 0.1, 10.0]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "SCALE_P95_EXCEEDED" for f in r.failures)
    f = next(x for x in r.failures if x.code == "SCALE_P95_EXCEEDED")
    assert f.threshold == SCALE_P95_MAX_PCT


def test_rotation_p95_exceeded_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["rotation_errors"] = [0.1, 0.1, 0.1, 10.0]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "ROTATION_P95_EXCEEDED" for f in r.failures)
    f = next(x for x in r.failures if x.code == "ROTATION_P95_EXCEEDED")
    assert f.threshold == ROTATION_P95_MAX_DEG


def test_contact_p95_exceeded_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["contact_errors"] = [0.1, 0.1, 0.1, 10.0]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "CONTACT_P95_EXCEEDED" for f in r.failures)
    f = next(x for x in r.failures if x.code == "CONTACT_P95_EXCEEDED")
    assert f.threshold == CONTACT_P95_MAX_PCT


# ── 4) z-order / visibility / clipping ──────────────────────────────────────


def test_z_order_inversion_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["z_order_inversions"] = 1
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "Z_ORDER_INVERSION" for f in r.failures)
    assert any("z-order" in f.reason.lower() for f in r.failures)


def test_unexplained_visibility_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["visibility_events"] = 2
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "VISIBILITY_UNEXPLAINED" for f in r.failures)


def test_clipping_via_silhouette_reuse_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["clipping_via_silhouette_reuse"] = True
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "CLIPPING_SILHOUETTE_REUSE" for f in r.failures)
    f = next(x for x in r.failures if x.code == "CLIPPING_SILHOUETTE_REUSE")
    assert "silhouette" in f.reason.lower()


# ── 5) missing / empty / NaN / annotation / policy guards ───────────────────


def test_missing_metric_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["trajectory_errors"] = None
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "TRAJECTORY_MISSING" for f in r.failures)


def test_empty_metric_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["scale_errors"] = []
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "SCALE_MISSING" for f in r.failures)


def test_nan_metric_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["trajectory_errors"] = [0.1, float("nan"), 0.2]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "TRAJECTORY_NAN" for f in r.failures)


def test_nan_in_scale_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["scale_errors"] = [0.1, float("inf")]
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any("SCALE_NAN" in f.code for f in r.failures)


def test_missing_annotation_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["annotations"] = None
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "ANNOTATIONS_MISSING" for f in r.failures)


def test_missing_required_annotation_key_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    # remove required key z_order
    kw["annotations"] = {
        "shot_order": ["shot_a"],
        "cut_frames": [30],
        "visibility": [{"v": 1}],
    }
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "ANNOTATION_MISSING" for f in r.failures)
    assert any("z_order" in f.reason for f in r.failures)


def test_wrong_policy_version_blocks() -> None:
    svc = S10StructuralCompareService(expected_policy_version="v1")
    kw = _passing_kwargs(policy="v1")
    kw["policy_version"] = "v2"
    kw["expected_policy_version"] = "v1"
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "POLICY_VERSION_MISMATCH" for f in r.failures)
    f = next(x for x in r.failures if x.code == "POLICY_VERSION_MISMATCH")
    assert "v2" in f.reason and "v1" in f.reason


def test_missing_policy_version_blocks_when_expected() -> None:
    svc = S10StructuralCompareService(expected_policy_version="v1")
    kw = _passing_kwargs(policy="v1")
    kw["policy_version"] = None
    kw["expected_policy_version"] = "v1"
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any(f.code == "POLICY_VERSION_MISSING" for f in r.failures)


def test_nan_policy_annotation_blocks() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["annotations"] = {
        "shot_order": ["shot_a"],
        "cut_frames": [30],
        "z_order": [{"a": 1}],
        "visibility": float("nan"),
    }
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any("ANNOTATION" in f.code for f in r.failures)


# ── 6) actionable pointer on every BLOCKED failure ──────────────────────────


def test_every_failure_has_actionable_pointer() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    # force many failures at once
    kw["rendered_frame_count"] = 1
    kw["trajectory_errors"] = [10.0]
    kw["z_order_inversions"] = 5
    kw["clipping_via_silhouette_reuse"] = True
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert len(r.failures) >= 4
    for f in r.failures:
        assert f.role and f.layer and f.segment and f.route, f"missing pointer in {f.code}"
        assert f.reason and "[" in f.reason and "role=" in f.reason


def test_blocked_never_enters_review_required() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["visibility_events"] = 1
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert r.passed is False
    # even one failure must keep it BLOCKED
    kw2 = _passing_kwargs()
    r2 = svc.compare(**kw2)
    assert r2.status == "REVIEW_REQUIRED"
    assert r2.passed is True


def test_frame_count_type_and_nan_guards() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    kw["rendered_frame_count"] = float("nan")
    r = svc.compare(**kw)
    assert r.status == "BLOCKED"
    assert any("FRAME_COUNT" in f.code for f in r.failures)


def test_api_compare_manifests_wrapper() -> None:
    svc = S10StructuralCompareService()
    kw = _passing_kwargs()
    src = {
        "frame_count": kw["source_frame_count"],
        "fps_num": kw["source_fps_num"],
        "fps_den": kw["source_fps_den"],
        "shot_order": kw["source_shot_order"],
        "cut_frames": kw["source_cut_frames"],
        "policy_version": kw["policy_version"],
    }
    rend = {
        "frame_count": kw["rendered_frame_count"],
        "fps_num": kw["rendered_fps_num"],
        "fps_den": kw["rendered_fps_den"],
        "shot_order": kw["rendered_shot_order"],
        "cut_frames": kw["rendered_cut_frames"],
    }
    metrics = {
        "trajectory_errors": kw["trajectory_errors"],
        "scale_errors": kw["scale_errors"],
        "rotation_errors": kw["rotation_errors"],
        "contact_errors": kw["contact_errors"],
        "z_order_inversions": kw["z_order_inversions"],
        "visibility_events": kw["visibility_events"],
        "clipping_via_silhouette_reuse": kw["clipping_via_silhouette_reuse"],
    }
    r = svc.compare_manifests(src, rend, metrics, annotations=kw["annotations"], expected_policy_version="v1", context=kw["context"])
    assert r.status == "REVIEW_REQUIRED"


# ── 7) Server-derived layer (C1) — hashes + new types ─────────────────────


def test_server_derived_hashes_present() -> None:
    from app.services.s10_structural_compare import (
        ServerDerivedCompareInput,
        build_server_derived_result,
        hash_canonical,
    )

    inp = ServerDerivedCompareInput(
        source_manifest={"frame_count": 100, "fps_num": 30, "fps_den": 1, "shot_order": ["a"], "cut_frames": [50], "policy_version": "v1"},
        source_manifest_hash=hash_canonical({"frame_count": 100}),
        policy_version="v1",
        rendered_frame_count=100,
        rendered_fps_num=30,
        rendered_fps_den=1,
        rendered_shot_order=["a"],
        rendered_cut_frames=[50],
        trajectory_errors=[0.1],
        scale_errors=[0.5],
        rotation_errors=[0.5],
        contact_errors=[0.1],
        z_order_inversions=0,
        visibility_events=0,
        clipping_via_silhouette_reuse=False,
        annotations={"shot_order": ["a"], "cut_frames": [50], "z_order": [{"a": 1}], "visibility": [{"v": 1}]},
        rendered_sha256="a" * 64,
        rendered_size_bytes=12345,
        decoded_frame_count=100,
        publication_id="pub-1",
        publication_content_hash="b" * 64,
        evidence_hashes={"routes": "c" * 64},
    )
    derived = build_server_derived_result(inp)
    d = derived.to_dict()
    assert d["status"] == "REVIEW_REQUIRED"
    assert d["source_manifest_hash"] == inp.source_manifest_hash
    assert d["rendered_sha256"] == "a" * 64
    assert d["publication_content_hash"] == "b" * 64
    assert "input_hashes" in d
    assert d["input_hashes"]["source_manifest"] == inp.source_manifest_hash


# ── 8) Negative API tests — server ignores forged good metrics ─────────────

import hashlib
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import deps
from app.api.app import app
from app.persistence import create_engine_for_path, create_session_factory


def _h64(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _upgrade(db: Path, project_root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")


def _make_server_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, str], Path]:
    project_root = Path(__file__).resolve().parent.parent
    db = tmp_path / f"s10-compare-{uuid.uuid4().hex[:6]}.db"
    artifacts_root = tmp_path / f"artifacts-{uuid.uuid4().hex[:6]}"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    _upgrade(db, project_root)
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)
    from app.workflow.job_service import JobService

    svc = JobService(session_factory=factory, managed_root=artifacts_root)
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, "default") is None:
            s.add(Workspace(id="default", name="default"))
            s.commit()
    from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

    register_s10_full_apply_handler(svc._worker)  # type: ignore[attr-defined]
    try:
        svc._worker.bind_session_factory(factory)  # type: ignore[attr-defined]
    except Exception:
        pass
    monkeypatch.setattr(deps, "_job_service", svc, raising=False)

    # Seed project/video/lock manifest/checkpoint/run with NO publication (blocked)
    import json as _json

    from app.persistence.structural_lock import StructuralLockRepository

    with factory() as s:
        ws = "default"
        proj = f"proj-{uuid.uuid4().hex[:6]}"
        vid = f"vid-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"), {"p": proj, "w": ws})
        s.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"), {"v": vid, "p": proj})
        s.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,0,99,0,1000,'pending')"), {"s": f"sc-{uuid.uuid4().hex[:6]}", "v": vid})
        char = f"ch-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,'Hero',:code)"), {"c": char, "w": ws, "code": f"hero_{uuid.uuid4().hex[:4]}"})
        pv = f"pv-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"), {"pv": pv, "c": char, "w": ws})
        role = f"role-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"), {"r": role, "w": ws, "p": proj, "v": vid})
        rc = f"rc-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,'{}',1)"), {"rc": rc, "w": ws, "p": proj, "r": role, "c": char, "pv": pv})
        # Structural lock manifest — server authority
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": ["shot_a", "shot_b"],
            "fingerprints": {"z_order": _h64("z"), "contacts": _h64("c")},
            "segments": [
                {"occurrence_segment_id": "seg-src-a", "route": "sprite_affine", "anchor": {"x": 0, "y": 0}, "start_frame": 0, "end_frame": 49, "provenance": {"det": "ok"}},
                {"occurrence_segment_id": "seg-src-b", "route": "sprite_affine", "anchor": {"x": 0, "y": 0}, "start_frame": 50, "end_frame": 99, "provenance": {"det": "ok"}},
            ],
            "policy_version": "structural-thresholds-v1",
        }
        manifest, _ = lock_repo.create_manifest(ws, proj, vid, "1", manifest_dict)
        # Apply checkpoint pinning the manifest
        ckpt = f"ckpt-{uuid.uuid4().hex[:6]}"
        chash = _h64(f"ckpt-{ckpt}")
        # snapshot must carry structural_lock_manifest pin
        snap = _json.dumps({"structural_lock_manifest_id": manifest.id, "frame_count": 100})
        s.execute(
            text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision,structural_lock_manifest_id,lock_policy_version) VALUES (:id,:w,:p,:rc,1,'[]','[]',:tbf,:snap,:ch,1,:slm,:pol)"),
            {"id": ckpt, "w": ws, "p": proj, "rc": rc, "tbf": _h64("tbf"), "snap": snap, "ch": chash, "slm": manifest.id, "pol": manifest.policy_version},
        )
        s.commit()
        # Create a run via repo (so checkpoint binding is valid)
        from app.persistence.s10_full_apply import S10ApplyRepository
        from app.services.s10_chunk_plan import plan_full_apply

        repo = S10ApplyRepository(s)
        plan = plan_full_apply(
            approved_checkpoint={"checkpoint_id": ckpt, "checkpoint_hash": chash, "revision": 1},
            structural_lock_manifest={"manifest_hash": _h64("manifest"), "policy_version": "structural-thresholds-v1", "source_generation": "1", "frame_count": 100},
            scene_manifest={"shots": [{"shot_id": "shot_a", "start_frame": 0, "end_frame": 49}, {"shot_id": "shot_b", "start_frame": 50, "end_frame": 99}]},
            mapping={"mappings": [{"layer_id": "bg", "route": "sprite_affine"}]},
            compatibility_policy={"policy_version": "structural-thresholds-v1"},
            chunk_frames=50,
            overlap_frames=4,
        )
        rec, _ = repo.create_run(
            ws, proj, vid, ckpt,
            expected_checkpoint_hash=chash,
            expected_checkpoint_revision=1,
            plan_id=plan["plan_id"],
            plan_hash=plan["plan_hash"],
            frame_count=100,
            chunk_config={"chunk_frames": 50, "overlap_frames": 4},
            fps_num=30,
            fps_den=1,
        )
        for idx, ch in enumerate(plan["chunks"]):
            repo.create_chunk(
                ws, rec.id,
                chunk_index=idx,
                order_index=idx,
                shot_id=str(ch["shot_id"]),
                core_start_frame=int(ch["core_start_frame"]),
                core_end_frame=int(ch["core_end_frame"]),
                content_hash=str(ch["content_hash_input"]),
                overlap_before=int(ch.get("overlap_before", 0)),
                overlap_after=int(ch.get("overlap_after", 0)),
                layer_id=str(ch.get("layer_id")) if ch.get("layer_id") else None,
            )
        s.commit()
        seed = {"workspace_id": ws, "project_id": proj, "video_item_id": vid, "checkpoint_id": ckpt, "checkpoint_hash": chash, "run_id": rec.id, "manifest_id": manifest.id, "policy": manifest.policy_version}
    client = TestClient(app)
    return client, seed, artifacts_root


def _seed_publication_directly(
    factory,
    seed: dict[str, str],
    artifacts_root,
    *,
    content_hash_override: str | None = None,
    natural_key_override: str | None = None,
    rel_override: str | None = None,
) -> str:
    """Create a decodable MP4 publication + artifact directly (no worker).

    Writes a minimal 100-frame MP4 via write_frames_mp4, inserts artifact
    (sha256/size) + s10_full_apply_publication (completed) rows. Returns
    the publication id. Uses the seeded chunks so the gate's shot/cut
    derivation matches.

    content_hash defaults to the REAL producer lineage contract
    (sha256("pub:{run_id}:{artifact_sha}"), natural_key NULL — FullApply
    producer formula).  Regression tests pass content_hash_override /
    natural_key_override to prove raw-sha, foreign-hash, recompute-lineage
    and unknown-provenance bindings are BLOCKED/ACCEPTED exactly as the
    route gate requires.  rel_override places the artifact at a deep nested
    path (>260 chars absolute) to exercise the gate's extended-length read
    (C4A finding-02) — the file is written/hashed through the same
    \\?\ extended form the producer ``_lp`` uses.
    """
    import uuid as _uu
    from pathlib import Path as _P
    import numpy as np
    from sqlalchemy import text as _t

    from app.persistence.artifacts import hash_file
    from app.services.renderer_routes.composite import write_frames_mp4

    # Create 100 frames of solid color (deterministic, decodable)
    frames = [np.zeros((32, 32, 3), dtype=np.uint8) for _ in range(100)]
    # Vary slightly so encode is not degenerate
    for i, f in enumerate(frames):
        f[:] = i % 256

    run_id = seed["run_id"]
    ws = seed["workspace_id"]
    if rel_override is not None:
        rel = rel_override
    else:
        rel = f"s10_full_apply/{run_id}/full_{_uu.uuid4().hex[:8]}.mp4"
    abs_p = _P(artifacts_root) / rel
    # Deep-root (>260-char) publications MUST be written through the same
    # extended-length form the producer uses (`_lp`); a plain Path on
    # Windows fails at MAX_PATH.  For shallow paths this is a no-op.
    fs_p = _lp_p(abs_p)
    fs_p.parent.mkdir(parents=True, exist_ok=True)
    write_frames_mp4(frames, fs_p, fps=30.0)
    sha = hash_file(fs_p)
    size = fs_p.stat().st_size
    art_id = f"art-{_uu.uuid4().hex[:6]}"
    pub_id = f"pub-{_uu.uuid4().hex[:6]}"
    # Need checkpoint id for FK
    with factory() as s:
        run_row = s.execute(_t("SELECT apply_checkpoint_id, apply_checkpoint_hash, apply_checkpoint_revision FROM s10_full_apply_run WHERE id=:rid"), {"rid": run_id}).mappings().first()
        ckpt_id = str(run_row["apply_checkpoint_id"]) if run_row else seed["checkpoint_id"]
        ckpt_hash = str(run_row["apply_checkpoint_hash"]) if run_row else seed["checkpoint_hash"]
        ckpt_rev = int(run_row["apply_checkpoint_revision"]) if run_row else 1
        # artifact
        s.execute(_t(
            "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256, size_bytes, revision) "
            "VALUES (:id,:ws,'video',:rel,'ready',:sha,:sz,1)"
        ), {"id": art_id, "ws": ws, "rel": rel, "sha": sha, "sz": size})
        # artifact_owner (optional but helps FK completeness)
        s.execute(_t(
            "INSERT INTO artifact_owner(artifact_id, owner_type, owner_id, purpose) VALUES (:aid,'video_item',:vid,'rendered')"
        ), {"aid": art_id, "vid": seed["video_item_id"]})
        # content_hash: REAL producer lineage contract (FullApply formula)
        # sha256("pub:{run_id}:{artifact_sha}"); natural_key NULL (producer does
        # not set one).  Overrides prove tampered/foreign/raw-sha bindings BLOCK.
        content_hash = (
            content_hash_override
            if content_hash_override is not None
            else hashlib.sha256(f"pub:{run_id}:{sha}".encode()).hexdigest()
        )
        natural_key = natural_key_override
        # publication
        s.execute(_t(
            "INSERT INTO s10_full_apply_publication(id, workspace_id, run_id, artifact_id, checkpoint_id, checkpoint_hash, checkpoint_revision, content_hash, frame_count, frame_metadata_json, state, natural_key, revision) "
            "VALUES (:id,:ws,:rid,:aid,:cid,:ch,:rev,:ch2,100,:fmj,'completed',:nk,1)"
        ), {"id": pub_id, "ws": ws, "rid": run_id, "aid": art_id, "cid": ckpt_id, "ch": ckpt_hash, "rev": ckpt_rev, "ch2": content_hash, "nk": natural_key, "fmj": "{\"fps\":30}"})
        # Seed required measurement evidence so the green path has authority:
        # mask artifacts (clipping), occurrence_segment rows with real
        # z_order/visibility/mask (z-order/visibility/clipping) and
        # segment_motion rows with measurable identity transforms
        # (trajectory/scale/rotation) + a scene_graph_contact row (contact).
        try:
            # Fetch FK ids created in _make_server_client
            _role_row = s.execute(_t("SELECT id FROM object_role WHERE workspace_id=:w AND video_item_id=:v LIMIT 1"), {"w": ws, "v": seed["video_item_id"]}).mappings().first()
            _scene_row = s.execute(_t("SELECT id FROM scene WHERE video_item_id=:v LIMIT 1"), {"v": seed["video_item_id"]}).mappings().first()
            if _role_row and _scene_row:
                _role_id = str(_role_row["id"])
                _scene_id = str(_scene_row["id"])
                # Replacement mask artifacts (NOT the source silhouettes).
                import uuid as _uu2
                _mask_ids = [f"mask-{_uu2.uuid4().hex[:8]}", f"mask-{_uu2.uuid4().hex[:8]}"]
                for _mid in _mask_ids:
                    s.execute(_t(
                        "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256, size_bytes, revision) "
                        "VALUES (:id,:ws,'image',:rel,'ready',:sha,64,1)"
                    ), {"id": _mid, "ws": ws, "rel": f"masks/{_mid}.png", "sha": _h64(_mid)})
                # Two segments with increasing z_order (no inversion) covering the 100 frames
                _seg_ids: list[str] = []
                for _idx, _z in enumerate([1, 2]):
                    _seg_id = f"seg-seed-{_uu2.uuid4().hex[:6]}"
                    _seg_ids.append(_seg_id)
                    _sf = _idx * 50
                    _ef = _sf + 49
                    s.execute(_t(
                        "INSERT INTO occurrence_segment(id, logical_id, workspace_id, project_id, video_item_id, role_id, scene_id, source_generation, name, kind, visibility, z_order, start_frame, end_frame, start_time_ms, end_time_ms, confidence, confidence_source, algorithm, algorithm_version, reasons_json, mask_artifact_id) "
                        "VALUES (:id,:lid,:ws,:p,:v,:rid,:sid,'1',:name,'character','visible',:z,:sf,:ef,:stm,:etm,0.9,'detector','test','1','[]',:mid)"
                    ), {"id": _seg_id, "lid": f"lid-{_seg_id}", "ws": ws, "p": seed["project_id"], "v": seed["video_item_id"], "rid": _role_id, "sid": _scene_id, "name": f"seed-seg-{_z}", "z": _z, "sf": _sf, "ef": _ef, "stm": _sf*10, "etm": _ef*10, "mid": _mask_ids[_idx]})
                    # segment_motion with a REAL measurable identity transform
                    # (translate (0,0), scale 1.0, rotation 0 deg, contact 0 px)
                    s.execute(_t(
                        "INSERT INTO segment_motion(id, workspace_id, occurrence_segment_id, transform_type, transform_json, point_track_flow_ref_json, start_frame, end_frame, start_time_ms, end_time_ms, confidence, confidence_source, algorithm, algorithm_version, revision, reasons_json, provenance_json) "
                        "VALUES (:mid,:ws,:oid,'object_relative',:tjson,'{}',:sf,:ef,:stm,:etm,0.9,'detector','test','1',1,'[]','{}')"
                    ), {"mid": f"mot-{_uu2.uuid4().hex[:6]}", "ws": ws, "oid": _seg_id, "tjson": '{"translate": {"x": 0.0, "y": 0.0}, "scale": 1.0, "rotation_deg": 0.0, "contact_offset": 0.0}', "sf": _sf, "ef": _ef, "stm": _sf*10, "etm": _ef*10})
                # Contact edge between the two segments (identity geometry -> 0 error)
                s.execute(_t(
                    "INSERT INTO scene_graph_contact(id, workspace_id, project_id, video_item_id, source_segment_id, target_segment_id, contact_kind, start_frame, end_frame, start_time_ms, end_time_ms, confidence, confidence_source, algorithm, algorithm_version, revision, reasons_json, provenance_json) "
                    "VALUES (:id,:ws,:p,:v,:src,:tgt,'touch',0,99,0,990,0.9,'detector','test','1',1,'[]','{}')"
                ), {"id": f"ct-{_uu2.uuid4().hex[:6]}", "ws": ws, "p": seed["project_id"], "v": seed["video_item_id"], "src": _seg_ids[0], "tgt": _seg_ids[1]})
        except Exception as _seed_e:
            raise
        s.commit()
    return pub_id


def _forged_good_body() -> dict:
    return {
        "source_frame_count": 100,
        "rendered_frame_count": 100,
        "source_fps_num": 30,
        "source_fps_den": 1,
        "rendered_fps_num": 30,
        "rendered_fps_den": 1,
        "source_shot_order": ["shot_a", "shot_b"],
        "rendered_shot_order": ["shot_a", "shot_b"],
        "source_cut_frames": [50],
        "rendered_cut_frames": [50],
        "trajectory_errors": [0.05, 0.08, 0.06],
        "scale_errors": [0.3, 0.5],
        "rotation_errors": [0.2, 0.3],
        "contact_errors": [0.05],
        "z_order_inversions": 0,
        "visibility_events": 0,
        "clipping_via_silhouette_reuse": False,
        "policy_version": "structural-thresholds-v1",
        "expected_policy_version": "structural-thresholds-v1",
        "annotations": {"shot_order": ["shot_a", "shot_b"], "cut_frames": [50], "z_order": [{"a": 1}], "visibility": [{"v": 1}]},
        "context": {"role": "hero", "layer": "character", "segment": "seg_001", "route": "sprite_affine"},
        "source_manifest": {"frame_count": 100, "fps_num": 30, "fps_den": 1, "shot_order": ["shot_a", "shot_b"], "cut_frames": [50], "policy_version": "structural-thresholds-v1"},
        "rendered_manifest": {"frame_count": 100, "fps_num": 30, "fps_den": 1, "shot_order": ["shot_a", "shot_b"], "cut_frames": [50]},
        "metrics": {"trajectory_errors": [0.05], "scale_errors": [0.3], "rotation_errors": [0.2], "contact_errors": [0.05], "z_order_inversions": 0, "visibility_events": 0, "clipping_via_silhouette_reuse": False},
    }


def test_forged_good_metrics_still_blocked_when_no_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, _art = _make_server_client(tmp_path, monkeypatch)
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert data["passed"] is False
    assert data.get("server_derived") is True
    # Must not trust client metrics — publication missing forces BLOCKED
    assert any(f["code"] in ("PUBLICATION_MISSING", "FRAME_COUNT_MISSING", "TRAJECTORY_MISSING") for f in data["failures"])


def test_forged_good_metrics_ignored_even_with_extra_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, _art = _make_server_client(tmp_path, monkeypatch)
    body = _forged_good_body()
    body["trajectory_errors"] = [0.0, 0.0]
    body["scale_errors"] = [0.0]
    body["extra_forged"] = {"perfect": True}
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED"
    # Server-derived hashes must be present regardless of client payload
    assert "source_manifest_hash" in data or "input_hashes" in data


def test_tampered_rendered_file_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    # First compare should be REVIEW_REQUIRED (happy path)
    body = _forged_good_body()
    r1 = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["status"] == "REVIEW_REQUIRED", d1
    # Tamper the publication artifact file on disk
    with factory() as s:  # type: ignore[operator]
        pub = s.execute(_t("SELECT artifact_id FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": seed["run_id"]}).mappings().first()
        assert pub is not None
        art = s.execute(_t("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": pub["artifact_id"]}).mappings().first()
        assert art is not None
        abs_p = artifacts_root / str(art["relative_path"])
        assert abs_p.is_file()
        abs_p.write_bytes(abs_p.read_bytes() + b"\x00\x01tamper")
    r2 = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["status"] == "BLOCKED", d2
    assert any(f["code"] in ("RENDERED_TAMPERED", "RENDERED_FILE_MISSING", "RENDERED_UNDECODABLE") for f in d2["failures"])


def test_missing_publication_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, _art = _make_server_client(tmp_path, monkeypatch)
    body: dict = {}
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED"
    assert any(f["code"] == "PUBLICATION_MISSING" for f in data["failures"])


def test_wrong_policy_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, _art = _make_server_client(tmp_path, monkeypatch)
    # Corrupt the checkpoint policy to be stale vs manifest
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE apply_checkpoint SET lock_policy_version='stale-policy-v9' WHERE id=:cid"), {"cid": seed["checkpoint_id"]})
        s.commit()
    body = _forged_good_body()
    # Client tries to claim correct policy, but server uses stale checkpoint pin -> BLOCKED
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED"
    assert any("POLICY" in f["code"] for f in data["failures"])


def test_only_server_green_can_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "REVIEW_REQUIRED", data
    assert data["passed"] is True
    assert data.get("server_derived") is True
    assert "source_manifest_hash" in data
    assert "rendered_sha256" in data


# ── C2 — measured gate: no placeholder, fail-closed, hashes + method/version ──


def test_measurement_method_version_present_in_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "REVIEW_REQUIRED", data
    assert data.get("measurement_method") == "s10-structural-v1"
    assert data.get("measurement_version") == "1"
    assert "evidence_hashes" in data
    assert "input_hashes" in data
    # input_hashes must contain source_manifest + evidence
    assert "source_manifest" in data["input_hashes"]
    assert "evidence" in data["input_hashes"]


def test_measurement_hashes_present_even_when_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No publication -> BLOCKED, but hashes linking to policy still present
    client, seed, _art = _make_server_client(tmp_path, monkeypatch)
    body: dict = {}
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED"
    assert "source_manifest_hash" in data
    assert data["source_manifest_hash"] is not None and len(data["source_manifest_hash"]) == 64


def test_cut_drift_via_chunk_boundary_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drift the chunk core_start so rendered_cut_frames mismatches source
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    # Drift second chunk by +3 frames (cut at 50 -> 53)
    with factory() as s:  # type: ignore[operator]
        chunks = s.execute(_t("SELECT id FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY core_start_frame"), {"rid": seed["run_id"]}).mappings().all()
        if len(chunks) >= 2:
            s.execute(_t("UPDATE s10_full_apply_chunk SET core_start_frame = core_start_frame + 3 WHERE id=:cid"), {"cid": chunks[1]["id"]})
            s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] in ("CUT_DRIFT", "CUT_FRAME_COUNT_MISMATCH", "CUT_FRAMES_MISSING") for f in data["failures"])


def test_z_order_inversion_blocks_via_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Insert occurrence_segment rows with z_order inversion and verify BLOCKED
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    import uuid as _uuid
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    # Create segments with intentional z inversion: z=5 then z=2 (decrease -> inversion)
    # Fetch seeded FKs so the INSERT satisfies NOT NULL + FK constraints.
    with factory() as _q:  # type: ignore[operator]
        _role_row = _q.execute(_t("SELECT id FROM object_role WHERE workspace_id=:w AND project_id=:p LIMIT 1"), {"w": seed["workspace_id"], "p": seed["project_id"]}).mappings().first()
        _scene_row = _q.execute(_t("SELECT id FROM scene WHERE video_item_id=:v LIMIT 1"), {"v": seed["video_item_id"]}).mappings().first()
        _role_id = str(_role_row["id"]) if _role_row else seed["video_item_id"]
        _scene_id = str(_scene_row["id"]) if _scene_row else seed["video_item_id"]
    with factory() as s:  # type: ignore[operator]
        for idx, z in enumerate([5, 2]):
            seg_id = f"seg-z-{_uuid.uuid4().hex[:6]}"
            # Distinct start_frame/end_frame to avoid uq_occurrence_segment_active_identity collision.
            sf = idx * 100
            ef = sf + 99
            s.execute(_t(
                "INSERT INTO occurrence_segment(id, logical_id, workspace_id, project_id, video_item_id, role_id, scene_id, source_generation, name, kind, visibility, z_order, start_frame, end_frame, start_time_ms, end_time_ms, confidence, confidence_source, algorithm, algorithm_version, reasons_json) "
                "VALUES (:id,:lid,:ws,:p,:v,:rid,:sid,'1',:name,'character','visible',:z,:sf,:ef,:stm,:etm,0.9,'detector','test','1','[]')"
            ), {"id": seg_id, "lid": f"lid-{seg_id}", "ws": seed["workspace_id"], "p": seed["project_id"], "v": seed["video_item_id"], "rid": _role_id, "sid": _scene_id, "name": f"seg-{z}", "z": z, "sf": sf, "ef": ef, "stm": sf*10, "etm": ef*10})
        s.commit()
    _seed_publication_directly(factory, seed, artifacts_root)
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Inversion should cause BLOCKED with Z_ORDER_INVERSION
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "Z_ORDER_INVERSION" for f in data["failures"])


def test_no_mirroring_source_cuts_stay_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Verify source cuts are NOT mirrored from rendered: even if we drift
    # rendered cuts, source cuts remain manifest truth and comparison fails.
    # This is the C2 invariant: source_cut_frames derived from manifest, not rendered.
    from app.services.s10_structural_compare import S10StructuralCompareService

    svc = S10StructuralCompareService(expected_policy_version="structural-thresholds-v1")
    # Source has cuts [30, 60], rendered drifted to [30, 61] -> must BLOCK
    r = svc.compare(
        source_frame_count=100,
        rendered_frame_count=100,
        source_fps_num=30,
        source_fps_den=1,
        rendered_fps_num=30,
        rendered_fps_den=1,
        source_shot_order=["shot_a", "shot_b", "shot_c"],
        rendered_shot_order=["shot_a", "shot_b", "shot_c"],
        source_cut_frames=[30, 60],
        rendered_cut_frames=[30, 61],
        trajectory_errors=[0.1, 0.2],
        scale_errors=[0.5],
        rotation_errors=[0.5],
        contact_errors=[0.1],
        z_order_inversions=0,
        visibility_events=0,
        clipping_via_silhouette_reuse=False,
        policy_version="structural-thresholds-v1",
        expected_policy_version="structural-thresholds-v1",
        annotations={"shot_order": ["a"], "cut_frames": [30], "z_order": [{"a": 1}], "visibility": [{"v": 1}]},
    )
    assert r.status == "BLOCKED"
    assert any(f.code == "CUT_DRIFT" for f in r.failures)


def test_removed_evidence_blocks_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Create green run, then delete chunk rows -> next compare must BLOCKED
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    body = _forged_good_body()
    r1 = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert r1.status_code == 200, r1.json().get("status") == "REVIEW_REQUIRED" and r1.json() or r1.text
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("DELETE FROM s10_full_apply_chunk WHERE run_id=:rid"), {"rid": seed["run_id"]})
        s.commit()
    r2 = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["status"] == "BLOCKED"
    assert any(f["code"] == "EVIDENCE_MISSING" for f in data["failures"])


def test_no_fake_shot_a_in_blocked_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No fake shot_a: service-level check that shot_order is not synthesized
    # when source has explicit shot_order.  The API gate never injects fake
    # shot_a into blocked paths — verify via source_manifest truth.
    from app.services.s10_structural_compare import S10StructuralCompareService

    svc = S10StructuralCompareService(expected_policy_version="structural-thresholds-v1")
    r = svc.compare(
        source_frame_count=100,
        rendered_frame_count=100,
        source_fps_num=30,
        source_fps_den=1,
        rendered_fps_num=30,
        rendered_fps_den=1,
        source_shot_order=["shot_a", "shot_b"],
        rendered_shot_order=["shot_a", "shot_b"],
        source_cut_frames=[50],
        rendered_cut_frames=[50],
        trajectory_errors=[0.1],
        scale_errors=[0.5],
        rotation_errors=[0.5],
        contact_errors=[0.1],
        z_order_inversions=0,
        visibility_events=0,
        clipping_via_silhouette_reuse=False,
        policy_version="structural-thresholds-v1",
        expected_policy_version="structural-thresholds-v1",
        annotations={"shot_order": ["shot_a"], "cut_frames": [50], "z_order": [{"a": 1}], "visibility": [{"v": 1}]},
    )
    assert r.status == "REVIEW_REQUIRED"
    # Now with wrong shot order -> BLOCKED, and failure mentions real shot ids
    r2 = svc.compare(
        source_frame_count=100,
        rendered_frame_count=100,
        source_fps_num=30,
        source_fps_den=1,
        rendered_fps_num=30,
        rendered_fps_den=1,
        source_shot_order=["shot_a", "shot_b"],
        rendered_shot_order=["shot_x", "shot_b"],
        source_cut_frames=[50],
        rendered_cut_frames=[50],
        trajectory_errors=[0.1],
        scale_errors=[0.5],
        rotation_errors=[0.5],
        contact_errors=[0.1],
        z_order_inversions=0,
        visibility_events=0,
        clipping_via_silhouette_reuse=False,
        policy_version="structural-thresholds-v1",
        expected_policy_version="structural-thresholds-v1",
        annotations={"shot_order": ["shot_a"], "cut_frames": [50], "z_order": [{"a": 1}], "visibility": [{"v": 1}]},
    )
    assert r2.status == "BLOCKED"
    assert any("SHOT_ORDER_MISMATCH" == f.code for f in r2.failures)


# ── C4 — measured perturbations per metric family + authority deletion ─────
# Every required metric family gets its own perturbation (REVIEW_REQUIRED
# green -> BLOCKED after perturbation) and every required authority deletion
# blocks.  Caller-supplied forged metrics never influence the verdict.


def _rewrite_publication(factory, seed: dict[str, str], artifacts_root, *, frame_count: int = 100, fps: float = 30.0) -> None:
    """Re-encode the publication artifact (new frame count / fps) and update
    the artifact + publication identity rows so hash/size stay consistent —
    a STRUCTURAL perturbation, not tampering."""
    from pathlib import Path as _P

    import numpy as np
    from sqlalchemy import text as _t

    from app.persistence.artifacts import hash_file
    from app.services.renderer_routes.composite import write_frames_mp4

    with factory() as s:  # type: ignore[operator]
        pub = s.execute(_t("SELECT id, artifact_id FROM s10_full_apply_publication WHERE run_id=:rid AND state='completed'"), {"rid": seed["run_id"]}).mappings().first()
        art = s.execute(_t("SELECT relative_path FROM artifact WHERE id=:aid"), {"aid": pub["artifact_id"]}).mappings().first()
    abs_p = _P(artifacts_root) / str(art["relative_path"])
    frames = [np.zeros((32, 32, 3), dtype=np.uint8) for _ in range(frame_count)]
    for i, f in enumerate(frames):
        f[:] = i % 256
    write_frames_mp4(frames, abs_p, fps=fps)
    sha = hash_file(abs_p)
    size = abs_p.stat().st_size
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE artifact SET sha256=:sha, size_bytes=:sz WHERE id=:aid"), {"sha": sha, "sz": size, "aid": pub["artifact_id"]})
        # content_hash is a LINEAGE key: re-encoding changes the artifact sha,
        # so the FullApply lineage hash must be recomputed, not set to raw sha.
        lineage_hash = hashlib.sha256(f"pub:{seed['run_id']}:{sha}".encode()).hexdigest()
        s.execute(_t("UPDATE s10_full_apply_publication SET content_hash=:ch WHERE id=:pid"), {"ch": lineage_hash, "pid": pub["id"]})
        s.commit()


def _green_post(client, seed: dict[str, str]) -> dict:
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "REVIEW_REQUIRED", data
    return data


def _seed_seg_ids(factory, seed: dict[str, str]) -> list[str]:
    from sqlalchemy import text as _t

    with factory() as s:  # type: ignore[operator]
        rows = s.execute(_t("SELECT id FROM occurrence_segment WHERE workspace_id=:w AND video_item_id=:v ORDER BY start_frame, id"), {"w": seed["workspace_id"], "v": seed["video_item_id"]}).mappings().all()
        return [str(r["id"]) for r in rows]


def test_c4_frame_count_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    # Re-encode at 99 frames (identity rows updated -> structural mismatch)
    _rewrite_publication(factory, seed, artifacts_root, frame_count=99, fps=30.0)
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "FRAME_COUNT_MISMATCH" for f in data["failures"])


def test_c4_timebase_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    # Re-encode at 24 fps (container-measured timebase now 24/1 vs 30/1)
    _rewrite_publication(factory, seed, artifacts_root, frame_count=100, fps=24.0)
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "TIMEBASE_MISMATCH" for f in data["failures"])


def test_c4_shot_order_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    # Swap chunk shot ids so rendered order becomes [shot_b, shot_a]
    with factory() as s:  # type: ignore[operator]
        chunks = s.execute(_t("SELECT id, shot_id FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY core_start_frame"), {"rid": seed["run_id"]}).mappings().all()
        if len(chunks) >= 2:
            s.execute(_t("UPDATE s10_full_apply_chunk SET shot_id=:sh WHERE id=:cid"), {"sh": chunks[1]["shot_id"], "cid": chunks[0]["id"]})
            s.execute(_t("UPDATE s10_full_apply_chunk SET shot_id=:sh WHERE id=:cid"), {"sh": chunks[0]["shot_id"], "cid": chunks[1]["id"]})
            s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "SHOT_ORDER_MISMATCH" for f in data["failures"])


def test_c4_cut_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    # Drift second chunk core_start by +3 -> rendered cut 50 -> 53
    with factory() as s:  # type: ignore[operator]
        chunks = s.execute(_t("SELECT id FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY core_start_frame"), {"rid": seed["run_id"]}).mappings().all()
        if len(chunks) >= 2:
            s.execute(_t("UPDATE s10_full_apply_chunk SET core_start_frame = core_start_frame + 3 WHERE id=:cid"), {"cid": chunks[1]["id"]})
            s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] in ("CUT_DRIFT", "CUT_FRAME_COUNT_MISMATCH", "CUT_FRAMES_MISSING") for f in data["failures"])


def test_c4_trajectory_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    seg_ids = _seed_seg_ids(factory, seed)
    # Translate segment 0 by (10,10) px -> trajectory error ~31% of 32x32 diagonal
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE segment_motion SET transform_json=:tj WHERE occurrence_segment_id=:sid"), {"tj": '{"translate": {"x": 10.0, "y": 10.0}, "scale": 1.0, "rotation_deg": 0.0, "contact_offset": 0.0}', "sid": seg_ids[0]})
        s.commit()
    body = _forged_good_body()  # forged perfect metrics must NOT convert to green
    body["trajectory_errors"] = [0.0, 0.0]
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] in ("TRAJECTORY_MEDIAN_EXCEEDED", "TRAJECTORY_P95_EXCEEDED") for f in data["failures"])


def test_c4_scale_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    seg_ids = _seed_seg_ids(factory, seed)
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE segment_motion SET transform_json=:tj WHERE occurrence_segment_id=:sid"), {"tj": '{"translate": {"x": 0.0, "y": 0.0}, "scale": 2.0, "rotation_deg": 0.0, "contact_offset": 0.0}', "sid": seg_ids[0]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "SCALE_P95_EXCEEDED" for f in data["failures"])


def test_c4_rotation_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    seg_ids = _seed_seg_ids(factory, seed)
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE segment_motion SET transform_json=:tj WHERE occurrence_segment_id=:sid"), {"tj": '{"translate": {"x": 0.0, "y": 0.0}, "scale": 1.0, "rotation_deg": 45.0, "contact_offset": 0.0}', "sid": seg_ids[0]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "ROTATION_P95_EXCEEDED" for f in data["failures"])


def test_c4_contact_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    seg_ids = _seed_seg_ids(factory, seed)
    # Move target segment 20px away from source -> contact error ~44% of diagonal
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE segment_motion SET transform_json=:tj WHERE occurrence_segment_id=:sid"), {"tj": '{"translate": {"x": 20.0, "y": 0.0}, "scale": 1.0, "rotation_deg": 0.0, "contact_offset": 0.0}', "sid": seg_ids[1]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "CONTACT_P95_EXCEEDED" for f in data["failures"])


def test_c4_visibility_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    seg_ids = _seed_seg_ids(factory, seed)
    # Hide a segment with no occlusion row explaining it -> unexplained event
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("UPDATE occurrence_segment SET visibility='hidden' WHERE id=:sid"), {"sid": seg_ids[0]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "VISIBILITY_UNEXPLAINED" for f in data["failures"])


def test_c4_clipping_perturbation_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    seg_ids = _seed_seg_ids(factory, seed)
    # Reuse the source silhouette: mark segment 0 as a rendered (new
    # generation) segment whose mask equals segment 1's source silhouette
    with factory() as s:  # type: ignore[operator]
        masks = s.execute(_t("SELECT mask_artifact_id FROM occurrence_segment WHERE id IN (:a,:b) ORDER BY start_frame"), {"a": seg_ids[0], "b": seg_ids[1]}).mappings().all()
        _other_sil = str(masks[1]["mask_artifact_id"])
        s.execute(_t("UPDATE occurrence_segment SET source_generation='2', mask_artifact_id=:m WHERE id=:sid"), {"m": _other_sil, "sid": seg_ids[0]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "CLIPPING_SILHOUETTE_REUSE" for f in data["failures"])


def test_c4_delete_motion_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("DELETE FROM segment_motion WHERE workspace_id=:ws"), {"ws": seed["workspace_id"]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "TRAJECTORY_MISSING" for f in data["failures"])


def test_c4_delete_contact_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("DELETE FROM scene_graph_contact WHERE workspace_id=:ws"), {"ws": seed["workspace_id"]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "CONTACT_MISSING" for f in data["failures"])


# ── R2 (C4A) — publication content_hash LINEAGE contract binding ──────────
# The gate must accept the producer lineage hash (not the raw artifact
# sha256) and fail closed on raw-sha/foreign/tampered/unknown provenance.


def _pub_binding(factory, seed: dict[str, str]) -> tuple[str, str]:
    """Return (publication content_hash, artifact sha256) for the completed pub."""
    from sqlalchemy import text as _t

    with factory() as s:  # type: ignore[operator]
        row = s.execute(
            _t(
                "SELECT p.content_hash AS ch, a.sha256 AS sha "
                "FROM s10_full_apply_publication p JOIN artifact a ON a.id = p.artifact_id "
                "WHERE p.run_id=:rid AND p.state='completed'"
            ),
            {"rid": seed["run_id"]},
        ).mappings().first()
        assert row is not None
        return str(row["ch"]), str(row["sha"])


def _rewrite_pub_content_hash(factory, seed: dict[str, str], content_hash: str) -> None:
    from sqlalchemy import text as _t

    with factory() as s:  # type: ignore[operator]
        s.execute(
            _t("UPDATE s10_full_apply_publication SET content_hash=:ch WHERE run_id=:rid"),
            {"ch": content_hash, "rid": seed["run_id"]},
        )
        s.commit()


def test_c4_pub_fullapply_lineage_contract_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real producer path: FullApply pub content_hash = sha256('pub:{run}:{sha}')
    binds and reaches REVIEW_REQUIRED on sufficient measured evidence."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    # Prove the seeded binding IS the producer lineage formula
    ch, sha = _pub_binding(factory, seed)
    assert ch == hashlib.sha256(f"pub:{seed['run_id']}:{sha}".encode()).hexdigest(), ch
    assert ch != sha  # lineage key is NOT the raw file digest
    _green_post(client, seed)


def test_c4_pub_raw_sha_content_hash_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Raw-sha binding (old synthetic contract) must BLOCK — content_hash is a
    lineage key, never the artifact file digest."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _ch, _sha = _pub_binding(factory, seed)
    _rewrite_pub_content_hash(factory, seed, _sha)  # content_hash := file sha
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "PUBLICATION_CONTENT_HASH_MISMATCH" for f in data["failures"])
    assert data["failures"][0]["value"]["expected_lineage"] == hashlib.sha256(
        f"pub:{seed['run_id']}:{_sha}".encode()
    ).hexdigest()


def test_c4_pub_foreign_content_hash_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A random/foreign hash must BLOCK (fail-closed on tamper)."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _rewrite_pub_content_hash(factory, seed, hashlib.sha256(b"foreign-bytes").hexdigest())
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "PUBLICATION_CONTENT_HASH_MISMATCH" for f in data["failures"])


def test_c4_pub_recompute_lineage_contract_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recompute producer path: natural_key 'recompute-pub:{run}:{cid}' with
    content_hash = sha256('pub-recompute:{run}:{cid}:{sha}') binds GREEN."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    cid = f"cid-{uuid.uuid4().hex[:8]}"
    _seed_publication_directly(
        factory, seed, artifacts_root, natural_key_override=f"recompute-pub:{seed['run_id']}:{cid}"
    )
    _ch, sha = _pub_binding(factory, seed)
    expected = hashlib.sha256(f"pub-recompute:{seed['run_id']}:{cid}:{sha}".encode()).hexdigest()
    _rewrite_pub_content_hash(factory, seed, expected)
    _green_post(client, seed)


def test_c4_pub_recompute_wrong_lineage_hash_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recompute natural_key with the FullApply (wrong) formula must BLOCK."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    cid = f"cid-{uuid.uuid4().hex[:8]}"
    _seed_publication_directly(
        factory, seed, artifacts_root, natural_key_override=f"recompute-pub:{seed['run_id']}:{cid}"
    )
    # content_hash stays the FullApply formula -> wrong for recompute provenance
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "PUBLICATION_CONTENT_HASH_MISMATCH" for f in data["failures"])


def test_c4_pub_unknown_provenance_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown natural_key provenance fails closed even with a plausible hash."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root, natural_key_override="foreign-nk-xyz")
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "PUBLICATION_CONTENT_HASH_MISMATCH" for f in data["failures"])


def test_c4_delete_segments_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps
    from sqlalchemy import text as _t

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    _seed_publication_directly(factory, seed, artifacts_root)
    _green_post(client, seed)
    # Deleting occurrence_segment requires clearing referencing rows first
    with factory() as s:  # type: ignore[operator]
        s.execute(_t("DELETE FROM segment_motion WHERE workspace_id=:ws"), {"ws": seed["workspace_id"]})
        s.execute(_t("DELETE FROM scene_graph_contact WHERE workspace_id=:ws"), {"ws": seed["workspace_id"]})
        s.execute(_t("DELETE FROM occurrence_segment WHERE workspace_id=:ws"), {"ws": seed["workspace_id"]})
        s.commit()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "Z_ORDER_MISSING" for f in data["failures"])
    assert any(f["code"] == "VISIBILITY_MISSING" for f in data["failures"])
    assert any(f["code"] == "CLIPPING_MISSING" for f in data["failures"])


# ── R3 — deep-root (>260-char) publication read path (C4A finding-02) ─────
# The producer writes every media/evidence file through the extended-length
# (\\?\) form so deep managed roots survive Windows MAX_PATH.  The gate
# previously rebuilt the artifact path WITHOUT the prefix, so a >260-char
# artifact read RENDERED_FILE_MISSING even though the file existed (binary
# rule 4/6 unreachable).  These tests seed a publication whose ABSOLUTE
# path exceeds 259 chars and drive the real route gate: green reaches
# REVIEW_REQUIRED, missing file / tamper stay BLOCKED (fail-closed kept).


def _lp_p(path: Path) -> Path:
    """Windows extended-length form when the absolute path exceeds MAX_PATH
    (mirrors the producer ``_lp`` helper — media/evidence I/O goes through
    the same form).  No-op for shallow paths and non-Windows platforms."""
    raw = str(path)
    if os.name == "nt" and len(raw) > 259 and not raw.startswith("\\\\?\\"):
        return Path("\\\\?\\" + os.path.abspath(raw))
    return path


def _deep_pub_rel(artifacts_root: Path, run_id: str) -> str:
    """A publication relative path whose ABSOLUTE form exceeds 259 chars no
    matter how shallow the pytest tmp root is (never hard-codes an absolute
    integration path).  Each iteration APPENDS one deeper level so the
    absolute length strictly grows until it crosses MAX_PATH."""
    file_name = f"full_{uuid.uuid4().hex[:8]}.mp4"
    prefix = f"s10_full_apply/{run_id}"
    rel = f"{prefix}/{file_name}"
    pad = 0
    while len(str(Path(artifacts_root) / rel)) <= 259:
        prefix = f"{prefix}/level_{pad:03d}"
        rel = f"{prefix}/{file_name}"
        pad += 1
    return rel


def test_c4_deep_root_publication_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """>260-char artifact path: gate reads through the extended-length form and
    reaches REVIEW_REQUIRED on sufficient measured evidence."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    rel = _deep_pub_rel(artifacts_root, seed["run_id"])
    _seed_publication_directly(factory, seed, artifacts_root, rel_override=rel)
    abs_p = Path(artifacts_root) / rel
    assert len(str(abs_p)) > 259, f"expected >260-char path, got {len(str(abs_p))}: {abs_p}"
    _green_post(client, seed)


def test_c4_deep_root_missing_file_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """>260-char artifact path with the backing file deleted: RENDERED_FILE_MISSING
    stays BLOCKED (fail-closed preserved on the extended-length read)."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    rel = _deep_pub_rel(artifacts_root, seed["run_id"])
    _seed_publication_directly(factory, seed, artifacts_root, rel_override=rel)
    abs_p = Path(artifacts_root) / rel
    assert len(str(abs_p)) > 259, f"expected >260-char path, got {len(str(abs_p))}: {abs_p}"
    _lp_p(abs_p).unlink()
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "RENDERED_FILE_MISSING" for f in data["failures"]), data


def test_c4_deep_root_tampered_file_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """>260-char artifact path with the backing file tampered: RENDERED_TAMPERED
    stays BLOCKED (content hash read through the extended-length form)."""
    client, seed, artifacts_root = _make_server_client(tmp_path, monkeypatch)
    from app.api import deps as _deps

    factory = _deps._job_service.session_factory  # type: ignore[attr-defined]
    rel = _deep_pub_rel(artifacts_root, seed["run_id"])
    _seed_publication_directly(factory, seed, artifacts_root, rel_override=rel)
    abs_p = Path(artifacts_root) / rel
    assert len(str(abs_p)) > 259, f"expected >260-char path, got {len(str(abs_p))}: {abs_p}"
    # Overwrite the backing file with different bytes WITHOUT updating the
    # artifact row -> content hash mismatch -> RENDERED_TAMPERED BLOCKED.
    _lp_p(abs_p).write_bytes(b"tampered-bytes-not-the-rendered-mp4")
    body = _forged_good_body()
    resp = client.post(f"/api/v2/full-apply/{seed['run_id']}/structural-compare", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "BLOCKED", data
    assert any(f["code"] == "RENDERED_TAMPERED" for f in data["failures"]), data
