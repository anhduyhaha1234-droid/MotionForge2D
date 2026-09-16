"""B05 — immutable hashed authority (frozen D2 node IDs).

The approved, hashed authority pins global scene bounds, rational timing,
source generation, per-occurrence geometry/visibility/contact/occlusion and
mapping; live Scene/segment mutations after approval never silently change a
frozen execution; stale sources require reapproval; legacy checkpoint/hash
compatibility is explicit (v1 REAPPROVAL_REQUIRED; pre-timeline v2 → public
reapproval with bytes preserved).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from conftest import (
    GEN,
    WS,
    build_graph,
    h64,
    make_env,
    run_counts,
    submit_full_apply,
)

DBOX = {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}


def _row_bytes(env, checkpoint_id: str) -> str:
    with env.factory() as s:
        return str(
            s.execute(
                text(
                    "SELECT snapshot_json || '|' || checkpoint_hash || '|' || "
                    "CAST(revision AS TEXT) FROM apply_checkpoint WHERE id=:id"
                ),
                {"id": checkpoint_id},
            ).scalar()
        )


def _insert_v2_row(
    env, seed, *, snapshot: dict, checkpoint_hash: str, revision: int = 1, tbf: str | None = None
) -> str:
    ckpt = f"ckpt-{h64(str(snapshot)[:40])[:8]}"
    with env.factory() as s:
        rc_id = seed.get("reskin_config_id")
        if rc_id is None:
            cfg = s.execute(
                text("SELECT id FROM apply_checkpoint WHERE id=:id"),
                {"id": seed.get("checkpoint_id")},
            ).mappings().first()
            assert cfg is not None, "helper needs a known reskin config id"
            rc_id = str(cfg["id"])
        s.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                "reskin_config_revision,structural_lock_manifest_id,lock_policy_version,"
                "pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,"
                "checkpoint_hash,revision) VALUES (:id,:w,:p,:rc,:rev,:m,:lp,:packs,'[]',:tbf,:snap,:ch,:r)"
            ),
            {
                "id": ckpt,
                "w": WS,
                "p": seed["project_id"],
                "rc": rc_id,
                "rev": int(seed.get("checkpoint_revision") or 1),
                "m": seed["manifest_id"],
                "lp": "structural-thresholds-v1",
                "packs": json.dumps([seed["roles"]["r1"]["pack_id"]]),
                "tbf": tbf or h64("tbf-b05"),
                "snap": json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                "ch": checkpoint_hash,
                "r": revision,
            },
        )
        s.commit()
    return ckpt


def test_b05_timeline_block_inside_checkpoint_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.s09_approval import (
        S09ApprovalRepository,
        _checkpoint_content_hash,
    )

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env, monkeypatch, scenes=[(0, 119)], segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX}]
    )
    auth = seed["authority"]
    assert auth["timeline"]["timeline_version"] == "s09.full-apply-timeline/v1"
    with env.factory() as s:
        row = s.execute(
            text("SELECT * FROM apply_checkpoint WHERE id=:id"), {"id": seed["checkpoint_id"]}
        ).mappings().first()
        expected = _checkpoint_content_hash(
            reskin_config_id=row["reskin_config_id"],
            reskin_config_revision=int(row["reskin_config_revision"]),
            structural_lock_manifest_id=row["structural_lock_manifest_id"],
            lock_policy_version=row["lock_policy_version"],
            pack_version_ids=json.loads(row["pack_version_ids_json"]),
            loop_hashes=json.loads(row["loop_hashes_json"]),
            timebase_fingerprint=row["timebase_fingerprint"],
            snapshot=json.loads(row["snapshot_json"]),
        )
        assert expected == row["checkpoint_hash"]
        # the timeline sits INSIDE the hash: editing it changes the content hash
        tampered = json.loads(row["snapshot_json"])
        tampered["full_apply_authority"]["timeline"]["shots"][0]["end_frame"] -= 1
        tampered_hash = _checkpoint_content_hash(
            reskin_config_id=row["reskin_config_id"],
            reskin_config_revision=int(row["reskin_config_revision"]),
            structural_lock_manifest_id=row["structural_lock_manifest_id"],
            lock_policy_version=row["lock_policy_version"],
            pack_version_ids=json.loads(row["pack_version_ids_json"]),
            loop_hashes=json.loads(row["loop_hashes_json"]),
            timebase_fingerprint=row["timebase_fingerprint"],
            snapshot=tampered,
        )
        assert tampered_hash != row["checkpoint_hash"]
        # stored snapshot edited WITHOUT re-hashing → integrity fails closed
        s.execute(
            text("UPDATE apply_checkpoint SET snapshot_json=:s WHERE id=:id"),
            {
                "s": json.dumps(tampered, sort_keys=True, separators=(",", ":")),
                "id": seed["checkpoint_id"],
            },
        )
        s.commit()
        integrity = S09ApprovalRepository(s).verify_checkpoint(seed["checkpoint_id"], WS)
        assert integrity.verified is False
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert run_counts(env) == (0, 0)


def test_b05_live_scene_mutations_after_approval_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env, monkeypatch, scenes=[(0, 119)], segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX}]
    )
    before = _row_bytes(env, seed["checkpoint_id"])
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]

    # live Scene/segment mutations AFTER approval must not change the frozen run
    with env.factory() as s:
        s.execute(
            text("UPDATE scene SET end_frame=50 WHERE id=:id"), {"id": seed["scene_ids"][0]}
        )
        s.execute(
            text(
                "UPDATE occurrence_segment SET segmentation_json=:g, prompt_json=:g, "
                "end_frame=20 WHERE id=:id"
            ),
            {"g": json.dumps({"boxes": [{"x": 1.0, "y": 1.0, "w": 5.0, "h": 5.0}]}), "id": seed["segments"][list(seed["segments"])[0]]["seg_id"]},
        )
        s.commit()
    assert _row_bytes(env, seed["checkpoint_id"]) == before  # bytes untouched

    claimed = env.svc._worker.run_once()
    assert claimed == 1
    with env.factory() as s:
        run = s.execute(
            text("SELECT status, frame_count FROM s10_full_apply_run WHERE id=:r"),
            {"r": run_id},
        ).mappings().first()
    assert run["status"] == "completed"
    assert int(run["frame_count"]) == 120  # frozen partition, not the mutated one


def test_b05_stale_source_requires_reapproval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env, monkeypatch, scenes=[(0, 119)], segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX}]
    )
    old_bytes = _row_bytes(env, seed["checkpoint_id"])
    # a NEW approval state (fresh manifest version) creates a NEW checkpoint;
    # the old row keeps its exact bytes/hashes.
    from app.persistence.structural_lock import StructuralLockRepository

    with env.factory() as s:
        lock_repo = StructuralLockRepository(s)
        manifest2, _ = lock_repo.create_manifest(
            WS,
            seed["project_id"],
            seed["video_item_id"],
            GEN,
            {
                "frame_count": 120,
                "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
                "shot_order": list(seed["scene_ids"]),
                "fingerprints": {"z_order": h64("z2"), "contacts": h64("c2")},
                "segments": [
                    {
                        "occurrence_segment_id": sid,
                        "route": entry["route"],
                        "anchor": dict(entry["anchor"]),
                        "start_frame": entry["start"],
                        "end_frame": entry["end"],
                        "provenance": {"why": "b05-new-state"},
                    }
                    for sid, entry in seed["segments"].items()
                ],
                "policy_version": "structural-thresholds-v1",
            },
        )
        s.execute(
            text(
                "UPDATE reskin_config SET structural_lock_manifest_id=:m WHERE id=:rc"
            ),
            {"m": manifest2.id, "rc": seed["roles"]["r1"]["reskin_config_id"]},
        )
        s.flush()
        from app.services.s09_approval import S09ApprovalRepository

        rec2, created2 = S09ApprovalRepository(s).submit_checkpoint_v2(
            WS,
            reskin_config_id=seed["roles"]["r1"]["reskin_config_id"],
            expected_reskin_revision=1,
            pack_version_ids=[seed["roles"]["r1"]["pack_id"]],
            note="b05 new state",
        )
        assert created2 is True and str(rec2.id) != seed["checkpoint_id"]
        s.commit()
    assert _row_bytes(env, seed["checkpoint_id"]) == old_bytes  # old row frozen

    # stale client expectation (old checkpoint, new hash) fails closed
    resp = submit_full_apply(env, seed, expected_checkpoint_hash=h64("stale-hash"))
    assert resp.status_code == 422, resp.text
    assert run_counts(env) == (0, 0)
    # the frozen old checkpoint still executes under its own hash
    resp_ok = submit_full_apply(env, seed)
    assert resp_ok.status_code == 202, resp_ok.text
    assert run_counts(env)[0] == 1


def test_b05_legacy_v2_pre_timeline_public_reapproval_bytes_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.s09_approval import (
        S09ApprovalRepository,
        _checkpoint_content_hash,
    )

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX}],
        submit_approval=False,
    )
    # hand-build a PRE-TIMELINE v2 row (the pre-bridge representation)
    snapshot = {
        "schema": "s09.approval/v2",
        "note": "pre-timeline legacy",
        "full_apply_authority": {
            "authority_version": "s09.full-apply-authority/v1",
            "identity": {"workspace_id": WS, "project_id": seed["project_id"], "source_generation": GEN},
            "source": {"source_artifact_id": seed["source_artifact_id"], "frame_count": 120},
            "structural_lock": {
                "manifest_hash": seed["manifest_hash"],
                "policy_version": "structural-thresholds-v1",
            },
            "shot_order": list(seed["scene_ids"]),
            "segments": [],
            "role_mappings": [],
            "eligibility": {"full_apply_executable": True, "reasons": [], "unsupported_routes": []},
        },
    }
    with env.factory() as s:
        rc = s.execute(
            text("SELECT id FROM reskin_config WHERE object_role_id=:r"),
            {"r": seed["roles"]["r1"]["role_id"]},
        ).scalar()
        seed["reskin_config_id"] = str(rc)
        chash = _checkpoint_content_hash(
            reskin_config_id=str(rc),
            reskin_config_revision=1,
            structural_lock_manifest_id=seed["manifest_id"],
            lock_policy_version="structural-thresholds-v1",
            pack_version_ids=[seed["roles"]["r1"]["pack_id"]],
            loop_hashes=[],
            timebase_fingerprint=h64("tbf-b05"),
            snapshot=snapshot,
        )
    legacy_id = _insert_v2_row(
        env, seed, snapshot=snapshot, checkpoint_hash=chash, revision=1
    )
    legacy_bytes = _row_bytes(env, legacy_id)
    seed["checkpoint_id"] = legacy_id
    seed["checkpoint_hash"] = chash
    seed["checkpoint_revision"] = "1"
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert "LEGACY_AUTHORITY_REAPPROVAL_REQUIRED" in resp.json()["detail"]
    assert run_counts(env) == (0, 0)

    # public reapproval creates a NEW row carrying the timeline; the legacy
    # row keeps its exact bytes/hashes (never backfilled/reinterpreted).
    with env.factory() as s:
        rec, created = S09ApprovalRepository(s).submit_checkpoint_v2(
            WS,
            reskin_config_id=seed["reskin_config_id"],
            expected_reskin_revision=1,
            pack_version_ids=[seed["roles"]["r1"]["pack_id"]],
            note="public reapproval",
        )
        assert created is True
        new_authority = S09ApprovalRepository(s).full_apply_authority(str(rec.id), WS)
        s.commit()
    assert new_authority["timeline"]["timeline_version"] == "s09.full-apply-timeline/v1"
    assert _row_bytes(env, legacy_id) == legacy_bytes


def test_b05_legacy_v1_reapproval_required_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.s09_approval import _checkpoint_content_hash

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX}],
        submit_approval=False,
    )
    snapshot_v1 = {"schema": "s09.approval/v1", "note": "legacy v1"}
    with env.factory() as s:
        rc = s.execute(
            text("SELECT id FROM reskin_config WHERE object_role_id=:r"),
            {"r": seed["roles"]["r1"]["role_id"]},
        ).scalar()
    seed["reskin_config_id"] = str(rc)
    chash = _checkpoint_content_hash(
        reskin_config_id=str(rc),
        reskin_config_revision=1,
        structural_lock_manifest_id=seed["manifest_id"],
        lock_policy_version="structural-thresholds-v1",
        pack_version_ids=[seed["roles"]["r1"]["pack_id"]],
        loop_hashes=[],
        timebase_fingerprint=h64("tbf-b05v1"),
        snapshot=snapshot_v1,
    )
    v1_id = _insert_v2_row(
        env, seed, snapshot=snapshot_v1, checkpoint_hash=chash, revision=1, tbf=h64("tbf-b05v1")
    )
    before = _row_bytes(env, v1_id)
    seed["checkpoint_id"] = v1_id
    seed["checkpoint_hash"] = chash
    seed["checkpoint_revision"] = "1"
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert "REAPPROVAL_REQUIRED" in resp.json()["detail"]
    assert run_counts(env) == (0, 0)
    assert _row_bytes(env, v1_id) == before


def test_b05_corrupted_timeline_fails_closed_no_live_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.s09_approval import _checkpoint_content_hash

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env, monkeypatch, scenes=[(0, 119)], segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX}]
    )
    # corrupt the timeline with a RECOMPUTED hash (integrity passes, content invalid)
    with env.factory() as s:
        row = s.execute(
            text("SELECT * FROM apply_checkpoint WHERE id=:id"), {"id": seed["checkpoint_id"]}
        ).mappings().first()
        snap = json.loads(row["snapshot_json"])
        snap["full_apply_authority"]["timeline"]["shots"][0]["end_frame"] -= 1
        new_hash = _checkpoint_content_hash(
            reskin_config_id=row["reskin_config_id"],
            reskin_config_revision=int(row["reskin_config_revision"]),
            structural_lock_manifest_id=row["structural_lock_manifest_id"],
            lock_policy_version=row["lock_policy_version"],
            pack_version_ids=json.loads(row["pack_version_ids_json"]),
            loop_hashes=json.loads(row["loop_hashes_json"]),
            timebase_fingerprint=row["timebase_fingerprint"],
            snapshot=snap,
        )
        s.execute(
            text("UPDATE apply_checkpoint SET snapshot_json=:s, checkpoint_hash=:h WHERE id=:id"),
            {
                "s": json.dumps(snap, sort_keys=True, separators=(",", ":")),
                "h": new_hash,
                "id": seed["checkpoint_id"],
            },
        )
        s.commit()
    seed["checkpoint_hash"] = new_hash
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert "corrupted timeline authority" in resp.json()["detail"]
    assert "TIMELINE_COVERAGE" in resp.json()["detail"]
    assert run_counts(env) == (0, 0)

    # live fallback proof: even a FRESH valid scene partition on disk cannot
    # rescue the corrupted frozen block (no live re-read).
    with env.factory() as s:
        s.execute(
            text("UPDATE scene SET end_frame=118 WHERE id=:id"), {"id": seed["scene_ids"][0]}
        )
        s.commit()
    resp2 = submit_full_apply(env, seed)
    assert resp2.status_code == 422, resp2.text
    assert run_counts(env) == (0, 0)
