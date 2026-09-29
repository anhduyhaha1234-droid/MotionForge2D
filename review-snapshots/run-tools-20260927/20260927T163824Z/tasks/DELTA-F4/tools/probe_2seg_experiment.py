"""Experiment: can the F1 fixture carry TWO occurrence segments (same role)?

If yes, the F4 world gets a multi-member chunk produced by the REAL planner.
Read-only wrt source; uses the F1 fixtures + structural evidence repos directly.
"""
from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F4")
sys.path.insert(0, str(WT / "tests" / "product_delivery"))
sys.path.insert(0, str(WT))

import test_delta_f1 as t  # noqa: E402


def _seed_checkpoint_two_segments(factory, artifacts, seed, scene_pk) -> dict:
    import hashlib

    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository

    ws = seed["workspace_id"]
    h64 = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    with factory() as s:
        mask_art = "art-mask-" + uuid.uuid4().hex[:6]
        mask_rel = "s10_full_apply/_f1/" + seed["video_item_id"] + "/mask.png"
        mask_abs = artifacts / mask_rel
        mask_abs.parent.mkdir(parents=True, exist_ok=True)
        import cv2
        import numpy as np

        mask_img = np.zeros((40, 40, 4), dtype=np.uint8)
        mask_img[:, :, 3] = 255
        cv2.imwrite(str(mask_abs), mask_img)
        t._insert_artifact(s, mask_art, "image", mask_rel, mask_abs)
        seg_repo = StructuralEvidenceRepository(s)
        seg1, _ = seg_repo.create_segment(
            ws, seed["project_id"], seed["video_item_id"], seed["role_id"], scene_pk,
            "Hero", 0, 99, 0, 3300, "1", kind="character", confidence_source="user",
            segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        seg2, _ = seg_repo.create_segment(
            ws, seed["project_id"], seed["video_item_id"], seed["role_id"], scene_pk,
            "Hero", 50, 99, 1650, 3300, "1", kind="character", confidence_source="user",
            segmentation={"boxes": [{"x": 0.50, "y": 0.50, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.55, "y": 0.55, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [str(seg1.id), str(seg2.id)],
            "fingerprints": {"z_order": h64("z"), "contacts": h64("c")},
            "segments": [
                {"occurrence_segment_id": str(seg1.id), "route": "sprite_affine",
                 "anchor": {"x": 0.5, "y": 0.5}, "start_frame": 0, "end_frame": 99,
                 "provenance": {"why": "delta-f4-experiment"}},
                {"occurrence_segment_id": str(seg2.id), "route": "sprite_affine",
                 "anchor": {"x": 0.5, "y": 0.5}, "start_frame": 0, "end_frame": 99,
                 "provenance": {"why": "delta-f4-experiment"}},
            ],
            "policy_version": "structural-thresholds-v1",
        }
        man, _mc = lock_repo.create_manifest(
            ws, seed["project_id"], seed["video_item_id"], "1", manifest_dict
        )
        for seg in (seg1, seg2):
            lock_repo.record_render_route(
                ws, seed["project_id"], seed["video_item_id"], str(seg.id),
                "sprite_affine", 0.5, 0.5, 0, 99,
                provenance={"why": "delta-f4-experiment"},
                reasons=["delta-f4-experiment"],
                structural_lock_manifest_id=man.id,
            )
        s.execute(
            t.text(
                "UPDATE reskin_config SET structural_lock_manifest_id=:m, "
                "lock_policy_version=:p WHERE id=:rc"
            ),
            {"m": man.id, "p": man.policy_version, "rc": seed["reskin_config_id"]},
        )
        s.flush()
        record, created = S09ApprovalRepository(s).submit_checkpoint_v2(
            ws,
            reskin_config_id=str(seed["reskin_config_id"]),
            expected_reskin_revision=1,
            pack_version_ids=[str(seed["pack_version_id"])],
            note="delta-f4 experiment",
        )
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = str(record.reskin_config_revision)
    return seed


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="f4-probe-2seg-"))
    db = tmp / "delta-f1.db"
    t._upgrade(db)
    from app.persistence import create_engine_for_path, create_session_factory

    factory = create_session_factory(create_engine_for_path(db))
    artifacts = tmp / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    seed, scene_pk = t._seed_graph_rows(factory, artifacts)
    seed = _seed_checkpoint_two_segments(factory, artifacts, seed, scene_pk)
    run_id, plan = t._submit(factory, seed, scene_pk)
    out = {
        "run_id": run_id,
        "members": {c["chunk_id"]: list(c.get("member_layer_ids") or []) for c in plan["chunks"]},
        "n_mappings": len((plan["render_authority"]["mapping"] or {}).get("mappings") or []),
        "roles": [
            m.get("role_id")
            for m in (plan["render_authority"]["mapping"] or {}).get("mappings") or []
        ],
    }
    print("EXPERIMENT_RESULT " + json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
