"""DELTA-F1 tests — group-chunk `member_layer_ids` survive persist (P1 fix).

Defect (measured by MF-DEMO-E2E on the frozen candidate): the planner froze
``member_layer_ids`` for every whole-shot/GROUP chunk, the persist path
dropped the field (no column), and the worker failed closed at chunk 0 for
EVERY ``comfy_shot_engine`` run (job ``dd64f660-…``, run
``8cd0dbe3-3ae3-47ec-af5e-4fe40fce2628``, 0.05 s, 0 GPU work).

Rows (scripted engine stands at the ENGINE BOUNDARY, labeled fixture — no
GPU, no ComfyUI server; production code is never mocked):

* F1.1 migration: ONE live head; the new revision revises the measured
  pre-fix head and is reachable from the current head.
* F1.2 public persist round-trip: ``FullApplyService.submit`` (comfy
  backend) -> chunk row column -> repository read -> worker read; members are
  byte-equal to the planner's frozen list (RED on base: the field is lost).
* F1.3 worker render: the row read back by ``_list_chunks`` drives the
  engine's cast for EXACTLY the persisted members (RED on base: the
  fail-closed guard fires before any engine call).
* F1.4 fail-closed kept: a row whose members are NULL is still refused with
  the original message and ZERO engine calls.
* F1.5 corrupt members JSON never crashes the read and never fabricates
  membership -> still refused.
* F1.6 legacy per-layer plan: no members persisted (NULL), records read as
  empty — the additive column does not invent membership.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.services.renderer_routes.composite import (
    canonical_frame_sha256,
    decode_rgb_frames,
    write_frames_mp4,
)
from app.workflow import s10_full_apply_jobs as jobs

WT = Path(__file__).resolve().parents[2]
GRAPH_REL = "app/media_workflows/wan_shot_v1.json"
WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"
OLD_HEAD = "e5f6a7b8c9d0"  # measured live head BEFORE this fix
NEW_REV = "b3c4d5e6f7a8"

_INS_ARTIFACT = (
    "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,"
    "size_bytes,revision) VALUES (:id,'default',:kind,:rel,'ready',:sha,:sz,1)"
)
_SEL_RAW_MEMBERS = (
    "SELECT member_layer_ids_json FROM s10_full_apply_chunk "
    "WHERE run_id=? ORDER BY chunk_index"
)
_UPD_RAW_MEMBERS = (
    "UPDATE s10_full_apply_chunk SET member_layer_ids_json=? WHERE run_id=?"
)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_mp4(path: Path, frames: int, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = []
    for i in range(frames):
        f = np.zeros((48, 64, 3), dtype=np.uint8)
        f[:, :, 0] = (int(seed) + i * 3) % 255
        f[:, :, 1] = 60
        f[:, :, 2] = 200
        arr.append(f)
    write_frames_mp4(arr, path, fps=30.0)
    return path


def _upgrade(db: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///" + db.as_posix())
    command.upgrade(cfg, "head")


def _insert_artifact(s: Any, artifact_id: str, kind: str, rel: str, abs_p: Path) -> None:
    from app.persistence.artifacts import hash_file

    s.execute(
        text(_INS_ARTIFACT),
        {
            "id": artifact_id,
            "kind": kind,
            "rel": rel,
            "sha": hash_file(abs_p),
            "sz": abs_p.stat().st_size,
        },
    )


def _seed_graph_rows(factory: Any, artifacts: Path) -> tuple[dict[str, str], str]:
    """Identity/CAS graph + pinned source/asset artifacts (no plan yet)."""
    ws = "default"
    with factory() as s:
        from app.persistence.models import Workspace

        if s.get(Workspace, ws) is None:
            s.add(Workspace(id=ws, name=ws))
            s.commit()
    with factory() as s:
        proj = "proj-" + uuid.uuid4().hex[:6]
        vid = "vid-" + uuid.uuid4().hex[:6]
        scene_pk = "sc-" + uuid.uuid4().hex[:6]
        char = "ch-" + uuid.uuid4().hex[:6]
        pv = "pv-" + uuid.uuid4().hex[:6]
        role = "role-" + uuid.uuid4().hex[:6]
        rc = "rc-" + uuid.uuid4().hex[:6]
        s.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
            {"p": proj, "w": ws},
        )
        s.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) "
                "VALUES (:v,:p,'Vid',0)"
            ),
            {"v": vid, "p": proj},
        )
        s.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) "
                "VALUES (:s,:v,0,0,99,0,1000,'pending')"
            ),
            {"s": scene_pk, "v": vid},
        )
        s.execute(
            text(
                "INSERT INTO character(id,workspace_id,name,code) "
                "VALUES (:c,:w,'Hero',:code)"
            ),
            {"c": char, "w": ws, "code": "hero_" + uuid.uuid4().hex[:4]},
        )
        s.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,"
                "version,status) VALUES (:pv,:c,:w,1,'published')"
            ),
            {"pv": pv, "c": char, "w": ws},
        )
        s.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) "
                "VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"
            ),
            {"r": role, "w": ws, "p": proj, "v": vid},
        )
        params = {
            "anchor": {"x": 0.5, "y": 0.5},
            "scale": 1.0,
            "fit_mode": "contain",
            "clip_mode": "asset_alpha",
            "offset": {"x": 0.0, "y": 0.0},
            "rotation_offset_deg": 0.0,
            "opacity": 1.0,
        }
        s.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                "character_id,pack_version_id,params_json,revision) "
                "VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"
            ),
            {
                "rc": rc,
                "w": ws,
                "p": proj,
                "r": role,
                "c": char,
                "pv": pv,
                "params": json.dumps(params, sort_keys=True, separators=(",", ":")),
            },
        )
        src_rel = "s10_full_apply/_f1/" + vid + "/source.mp4"
        src_abs = artifacts / src_rel
        _write_mp4(src_abs, 100, seed=1)
        src_art = "art-src-" + uuid.uuid4().hex[:6]
        _insert_artifact(s, src_art, "video", src_rel, src_abs)
        s.execute(
            text("UPDATE video_item SET source_artifact_id=:aid WHERE id=:vid"),
            {"aid": src_art, "vid": vid},
        )
        asset_rel = "s10_full_apply/_f1/" + vid + "/asset.png"
        asset_abs = artifacts / asset_rel
        asset_abs.parent.mkdir(parents=True, exist_ok=True)
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        hx = hashlib.sha256(pv.encode()).hexdigest()
        img[:, :, 0] = int(hx[0:2], 16)
        img[:, :, 1] = int(hx[2:4], 16)
        img[:, :, 2] = int(hx[4:6], 16)
        img[:, :, 3] = 255
        cv2.imwrite(str(asset_abs), img)
        asset_art = "art-asset-" + uuid.uuid4().hex[:6]
        _insert_artifact(s, asset_art, "image", asset_rel, asset_abs)
        s.execute(
            text(
                "INSERT INTO character_asset(id,pack_version_id,workspace_id,"
                "pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"
            ),
            {"id": "ca-" + uuid.uuid4().hex[:6], "pv": pv, "aid": asset_art},
        )
        # DELTA-F4: a SECOND role (own pack version + asset + reskin config) so
        # the group chunk carries members with DISTINCT roles — the real
        # multi-role coverage for the layer->role replacement-asset adapter.
        role2 = "role-" + uuid.uuid4().hex[:6]
        pv2 = "pv-" + uuid.uuid4().hex[:6]
        rc2 = "rc-" + uuid.uuid4().hex[:6]
        s.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) "
                "VALUES (:r,:w,:p,:v,'1','Rival','character','confirmed')"
            ),
            {"r": role2, "w": ws, "p": proj, "v": vid},
        )
        s.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,"
                "version,status) VALUES (:pv,:c,:w,2,'published')"
            ),
            {"pv": pv2, "c": char, "w": ws},
        )
        asset2_rel = "s10_full_apply/_f1/" + vid + "/asset2.png"
        asset2_abs = artifacts / asset2_rel
        img2 = np.zeros((40, 40, 4), dtype=np.uint8)
        hx2 = hashlib.sha256(pv2.encode()).hexdigest()
        img2[:, :, 0] = int(hx2[0:2], 16)
        img2[:, :, 1] = int(hx2[2:4], 16)
        img2[:, :, 2] = int(hx2[4:6], 16)
        img2[:, :, 3] = 255
        cv2.imwrite(str(asset2_abs), img2)
        asset2_art = "art-asset2-" + uuid.uuid4().hex[:6]
        _insert_artifact(s, asset2_art, "image", asset2_rel, asset2_abs)
        s.execute(
            text(
                "INSERT INTO character_asset(id,pack_version_id,workspace_id,"
                "pose_slot,artifact_id) VALUES (:id,:pv,'default','base',:aid)"
            ),
            {"id": "ca2-" + uuid.uuid4().hex[:6], "pv": pv2, "aid": asset2_art},
        )
        s.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                "character_id,pack_version_id,params_json,revision) "
                "VALUES (:rc,:w,:p,:r,:c,:pv,:params,1)"
            ),
            {
                "rc": rc2,
                "w": ws,
                "p": proj,
                "r": role2,
                "c": char,
                "pv": pv2,
                "params": json.dumps(params, sort_keys=True, separators=(",", ":")),
            },
        )
        s.commit()
        seed = {
            "workspace_id": ws,
            "project_id": proj,
            "video_item_id": vid,
            "pack_version_id": pv,
            "reskin_config_id": rc,
            "role_id": role,
            "role2_id": role2,
            "pack2_id": pv2,
            "reskin_config2_id": rc2,
        }
    return seed, scene_pk


def _seed_checkpoint(factory: Any, artifacts: Path, seed: dict[str, str]) -> None:
    from app.persistence.structural_evidence import StructuralEvidenceRepository
    from app.persistence.structural_lock import StructuralLockRepository
    from app.services.s09_approval import S09ApprovalRepository

    ws = seed["workspace_id"]
    h64 = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    with factory() as s:
        scene_id = s.execute(
            text(
                "SELECT id FROM scene WHERE video_item_id=:v "
                "ORDER BY position LIMIT 1"
            ),
            {"v": seed["video_item_id"]},
        ).scalar()
        mask_art = "art-mask-" + uuid.uuid4().hex[:6]
        mask_rel = "s10_full_apply/_f1/" + seed["video_item_id"] + "/mask.png"
        mask_abs = artifacts / mask_rel
        mask_abs.parent.mkdir(parents=True, exist_ok=True)
        mask_img = np.zeros((40, 40, 4), dtype=np.uint8)
        mask_img[:, :, 3] = 255
        cv2.imwrite(str(mask_abs), mask_img)
        _insert_artifact(s, mask_art, "image", mask_rel, mask_abs)
        seg_repo = StructuralEvidenceRepository(s)
        seg_rec, _sc = seg_repo.create_segment(
            ws,
            seed["project_id"],
            seed["video_item_id"],
            seed["role_id"],
            str(scene_id),
            "Hero",
            0,
            99,
            0,
            3300,
            "1",
            kind="character",
            confidence_source="user",
            segmentation={"boxes": [{"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.05, "y": 0.05, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        # DELTA-F4: a SECOND occurrence segment (distinct role, distinct frame
        # range — the segment identity is UNIQUE per role/scene/range) so the
        # shot's group chunk carries TWO members with DIFFERENT roles; the
        # layer ids stay occurrence ids distinct from both role ids.
        seg_rec2, _sc2 = seg_repo.create_segment(
            ws,
            seed["project_id"],
            seed["video_item_id"],
            seed["role2_id"],
            str(scene_id),
            "Rival",
            50,
            99,
            1650,
            3300,
            "1",
            kind="character",
            confidence_source="user",
            segmentation={"boxes": [{"x": 0.50, "y": 0.50, "w": 0.30, "h": 0.30}]},
            prompt={"boxes": [{"x": 0.55, "y": 0.55, "w": 0.40, "h": 0.40}]},
            mask_artifact_id=mask_art,
        )
        # Manifest segments = EXACTLY the created occurrences (the real lock
        # contract); both are active inside the single 0..99 shot.
        lock_repo = StructuralLockRepository(s)
        manifest_dict = {
            "frame_count": 100,
            "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
            "shot_order": [str(seg_rec.id), str(seg_rec2.id)],
            "fingerprints": {"z_order": h64("z"), "contacts": h64("c")},
            "segments": [
                {
                    "occurrence_segment_id": str(seg_rec.id),
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 0,
                    "end_frame": 99,
                    "provenance": {"why": "delta-f1-fixture"},
                },
                {
                    "occurrence_segment_id": str(seg_rec2.id),
                    "route": "sprite_affine",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "start_frame": 50,
                    "end_frame": 99,
                    "provenance": {"why": "delta-f1-fixture"},
                },
            ],
            "policy_version": "structural-thresholds-v1",
        }
        man, _mc = lock_repo.create_manifest(
            ws, seed["project_id"], seed["video_item_id"], "1", manifest_dict
        )
        for seg in (seg_rec, seg_rec2):
            lock_repo.record_render_route(
                ws,
                seed["project_id"],
                seed["video_item_id"],
                str(seg.id),
                "sprite_affine",
                0.5,
                0.5,
                0,
                99,
                provenance={"why": "delta-f1-fixture"},
                reasons=["delta-f1-fixture"],
                structural_lock_manifest_id=man.id,
            )
        for rc in (seed["reskin_config_id"], seed["reskin_config2_id"]):
            s.execute(
                text(
                    "UPDATE reskin_config SET structural_lock_manifest_id=:m, "
                    "lock_policy_version=:p WHERE id=:rc"
                ),
                {"m": man.id, "p": man.policy_version, "rc": rc},
            )
        s.flush()
        record, created = S09ApprovalRepository(s).submit_checkpoint_v2(
            ws,
            reskin_config_id=str(seed["reskin_config_id"]),
            expected_reskin_revision=1,
            pack_version_ids=[str(seed["pack_version_id"]), str(seed["pack2_id"])],
            note="delta-f1 fixture",
        )
        assert created is True
        s.commit()
        seed["checkpoint_id"] = str(record.id)
        seed["checkpoint_hash"] = str(record.checkpoint_hash)
        seed["checkpoint_revision"] = str(record.reskin_config_revision)


def _seed_world(tmp_path: Path) -> tuple[Any, dict[str, str], Path, str]:
    """A REAL v2 authority world (identity/CAS only) + pinned assets."""
    db = tmp_path / "delta-f1.db"
    _upgrade(db)
    factory = create_session_factory(create_engine_for_path(db))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    seed, scene_pk = _seed_graph_rows(factory, artifacts)
    _seed_checkpoint(factory, artifacts, seed)
    return factory, seed, artifacts, scene_pk


def _submit(
    factory: Any,
    seed: dict[str, str],
    scene_pk: str,
    *,
    comfy: bool = True,
) -> tuple[str, dict[str, Any]]:
    """PUBLIC submit path (the only place members can enter the DB)."""
    from app.services.s10_full_apply import FullApplyService

    kwargs: dict[str, Any] = {}
    if comfy:
        kwargs["execution_backend"] = {
            "backend": "comfy_shot_engine",
            "profile_id": WAN_PROFILE,
            "graph_sha256": _sha_file(WT / GRAPH_REL),
            "shot_prompts": {scene_pk: "delta-f1 prompt"},
        }
    with factory() as s:
        svc = FullApplyService(s)
        rec, created, plan = svc.submit(
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            video_item_id=seed["video_item_id"],
            apply_checkpoint_id=seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"],
            expected_checkpoint_revision=int(seed["checkpoint_revision"]),
            chunk_config={"chunk_frames": 120, "overlap_frames": 4},
            **kwargs,
        )
        s.commit()
    assert created is True
    assert plan["chunks"], "fixture must produce at least one chunk"
    return rec.id, plan


def _raw_column(db: Path, run_id: str) -> list[Any]:
    con = sqlite3.connect(str(db))
    try:
        con.execute("SELECT member_layer_ids_json FROM s10_full_apply_chunk LIMIT 1")
    except sqlite3.OperationalError:
        con.close()
        return [None]  # pre-fix schema: the field cannot be persisted at all
    rows = con.execute(_SEL_RAW_MEMBERS, (run_id,)).fetchall()
    con.close()
    return [r[0] for r in rows]


def _set_raw_members(db: Path, run_id: str, value: str | None) -> None:
    con = sqlite3.connect(str(db))
    con.execute(_UPD_RAW_MEMBERS, (value, run_id))
    con.commit()
    con.close()


class _EngineWorld:
    """Render-time world built from the PERSISTED row (engine at the boundary).

    DELTA-F4: the manifest pins come from the REAL submit-route helper
    (``_resolve_canonical_render_pins`` over the persisted v2 authority) and the
    render authority is the REAL service output (``plan["render_authority"]``) —
    never a hand-made manifest, so the fixture can no longer invent a key space
    that the live route does not produce.
    """

    def __init__(
        self,
        tmp_path: Path,
        factory: Any,
        seed: dict[str, str],
        run_id: str,
        plan: dict[str, Any],
    ) -> None:
        self.factory = factory
        self.seed = seed
        self.run_id = run_id
        # The SAME managed root the persisted authority pins point into.
        self.managed = tmp_path / "artifacts"
        self.calls: list[dict[str, Any]] = []
        row = jobs._list_chunks(factory, seed["workspace_id"], run_id)[0]
        self.chunk = row
        self.shot_id = str(row["shot_id"])
        self.members = [str(m) for m in (row.get("member_layer_ids") or [])]
        # Render authority = the REAL service output (layer_id AND role_id pins).
        self.authority = plan["render_authority"]
        mappings = (self.authority.get("mapping") or {}).get("mappings") or []
        self.role_by_layer = {
            str(m["layer_id"]): str(m.get("role_id") or "") for m in mappings
        }
        # Route-parity manifest: the REAL submit-route pin helper over the
        # PERSISTED v2 authority — replacement_assets are role-keyed by
        # construction (DELTA-F4: never hand-key them to the layer id space).
        from app.api.routes import s10_full_apply as full_apply_routes
        from app.services.s09_approval import S09ApprovalRepository

        with factory() as s:
            v2_authority = S09ApprovalRepository(s).full_apply_authority(
                seed["checkpoint_id"], seed["workspace_id"]
            )
            pins = full_apply_routes._resolve_canonical_render_pins(
                s,
                workspace_id=seed["workspace_id"],
                project_id=seed["project_id"],
                video_item_id=seed["video_item_id"],
                apply_checkpoint_id=seed["checkpoint_id"],
                authority=v2_authority,
                managed_root=self.managed,
            )
        anchor = self.managed / "anchor" / "anchor_00001_.png"
        anchor.parent.mkdir(parents=True, exist_ok=True)
        anchor.write_bytes(b"\x89PNG" + b"anchor" * 4)
        self.manifest = {"managed_root": str(self.managed), **pins}
        anchor_pin = {
            "relative_path": "anchor/anchor_00001_.png",
            "sha256": _sha_file(anchor),
        }
        self.backend = {
            "backend": "comfy_shot_engine",
            "profile_id": WAN_PROFILE,
            "capability": "source_video_motion_transfer",
            "graph_file": GRAPH_REL,
            "graph_sha256": _sha_file(WT / GRAPH_REL),
            "output_node": "246",
            "seed": 582699151003550,
            "shot_prompts": {self.shot_id: "delta-f1 prompt"},
            "shot_anchors": {self.shot_id: anchor_pin},
        }

    def fake_engine(self, *, managed_root: Path, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(request)
        rel = "engine_out/" + str(request["chunk_id"]) + "_00001_.mp4"
        path = _write_mp4(managed_root / rel, 10, seed=3)
        frames = decode_rgb_frames(path)
        return {
            "output_relative_path": rel,
            "output_sha256": _sha_file(path),
            "output_size_bytes": path.stat().st_size,
            "decoded_sha256": canonical_frame_sha256(frames),
            "decoded_frame_count": len(frames),
            "fps_num": 30,
            "fps_den": 1,
            "prompt_id": "delta-f1-pid",
            "graph_object_sha256_submitted": "e" * 64,
        }

    def render(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, int, dict[str, Any]]:
        monkeypatch.setattr(jobs, "_run_shot_render", self.fake_engine)
        return jobs._render_shot_chunk_via_engine(
            managed_root=self.managed,
            run_id=self.run_id,
            chunk=dict(self.chunk),
            chunk_index=0,
            fps_num=30,
            fps_den=1,
            workspace_id=self.seed["workspace_id"],
            project_id=self.seed["project_id"],
            video_item_id=self.seed["video_item_id"],
            authority=self.authority,
            manifest=self.manifest,
            backend=self.backend,
            session_factory=self.factory,
        )


# ── F1.1 — migration wiring ──────────────────────────────────────────────────


def test_delta_f1_1_migration_revises_the_measured_head_and_is_reachable() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    sd = ScriptDirectory.from_config(cfg)
    heads = sd.get_heads()
    assert len(heads) == 1, f"expected exactly one live head, got {heads}"
    chain: list[str] = []
    cur: str | None = heads[0]
    while cur is not None:
        chain.append(cur)
        cur = sd.get_revision(cur).down_revision
    assert NEW_REV in chain, f"{NEW_REV} must be reachable from the live head"
    assert sd.get_revision(NEW_REV).down_revision == OLD_HEAD
    assert OLD_HEAD in chain


# ── F1.2 — public persist round-trip ─────────────────────────────────────────


def test_delta_f1_2_public_submit_persists_group_members_end_to_end(
    tmp_path: Path,
) -> None:
    factory, seed, _artifacts, scene_pk = _seed_world(tmp_path)
    run_id, plan = _submit(factory, seed, scene_pk)
    plan_members = {
        c["chunk_id"]: list(c.get("member_layer_ids") or []) for c in plan["chunks"]
    }
    assert all(plan_members.values()), f"fixture must freeze members: {plan_members}"

    # raw column
    raw = _raw_column(tmp_path / "delta-f1.db", run_id)
    assert len(raw) == len(plan_members)
    assert all(v for v in raw), f"members must be persisted on the row, got {raw}"
    first = json.loads(raw[0])
    assert isinstance(first, list) and first == sorted(first) and first

    # repository read
    from app.persistence.s10_full_apply import S10ApplyRepository

    with factory() as s:
        recs = S10ApplyRepository(s).list_chunks(seed["workspace_id"], run_id)
    got = {r.chunk_index: list(r.member_layer_ids) for r in recs}
    assert all(got.values()), f"repository read lost members: {got}"
    assert sorted(next(iter(plan_members.values()))) == sorted(got[0])

    # worker read (the exact helper the job handler uses)
    worker = jobs._list_chunks(factory, seed["workspace_id"], run_id)
    by_chunk = {
        jobs._shot_chunk_identity(r)[1]: list(r.get("member_layer_ids") or [])
        for r in worker
    }
    assert all(by_chunk.values()), f"worker read lost members: {by_chunk}"
    for cid, members in by_chunk.items():
        assert members == plan_members[cid], (cid, members, plan_members[cid])


# ── F1.3 — worker renders with the persisted members ────────────────────────


def test_delta_f1_3_worker_reads_members_and_reaches_the_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, seed, _artifacts, scene_pk = _seed_world(tmp_path)
    run_id, plan = _submit(factory, seed, scene_pk)
    plan_members = list(plan["chunks"][0]["member_layer_ids"])
    world = _EngineWorld(tmp_path, factory, seed, run_id, plan)
    assert world.members == plan_members, "row must carry the planner's members"

    rel, sha, size, evidence = world.render(monkeypatch)

    assert len(world.calls) == 1, "exactly ONE engine request"
    cast_roles = [str(c["role"]) for c in world.calls[0]["cast"]]
    assert cast_roles == world.members, "the cast must be EXACTLY the persisted members"
    assert evidence["route"] == "shot_group"
    out = world.managed / rel
    assert out.is_file() and _sha_file(out) == sha and size > 0


# ── F1.4/F1.5 — fail-closed kept ────────────────────────────────────────────


def test_delta_f1_4_missing_members_still_fail_closed_no_engine_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, seed, _artifacts, scene_pk = _seed_world(tmp_path)
    run_id, plan = _submit(factory, seed, scene_pk)
    _set_raw_members(tmp_path / "delta-f1.db", run_id, None)  # member-less row
    world = _EngineWorld(tmp_path, factory, seed, run_id, plan)
    assert world.members == []

    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        world.render(monkeypatch)

    assert "member_layer_ids" in str(exc.value)
    assert "fail closed" in str(exc.value)
    assert world.calls == [], "a member-less comfy chunk must never reach the engine"


def test_delta_f1_5_corrupt_members_json_fails_closed_never_fabricates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, seed, _artifacts, scene_pk = _seed_world(tmp_path)
    run_id, plan = _submit(factory, seed, scene_pk)
    db = tmp_path / "delta-f1.db"
    # (a) unparsable JSON
    _set_raw_members(db, run_id, "{not a json array")
    world = _EngineWorld(tmp_path, factory, seed, run_id, plan)
    assert world.members == []

    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        world.render(monkeypatch)

    assert "member_layer_ids" in str(exc.value)
    assert world.calls == []

    # (b) parseable array with a NON-string entry: all-or-nothing, never a
    # silently reduced cast
    _set_raw_members(db, run_id, '["a-layer", 5]')
    world2 = _EngineWorld(tmp_path, factory, seed, run_id, plan)
    assert world2.members == []

    with pytest.raises(jobs.S10FullApplyJobError) as exc2:
        world2.render(monkeypatch)

    assert "member_layer_ids" in str(exc2.value)
    assert world2.calls == []


# ── F1.6 — legacy plans stay member-less (the column invents nothing) ───────


def test_delta_f1_6_legacy_plan_persists_no_members(tmp_path: Path) -> None:
    factory, seed, _artifacts, scene_pk = _seed_world(tmp_path)
    run_id, plan = _submit(factory, seed, scene_pk, comfy=False)
    assert all("member_layer_ids" not in c for c in plan["chunks"]), (
        "legacy planner emits no members"
    )

    raw = _raw_column(tmp_path / "delta-f1.db", run_id)
    assert all(v is None for v in raw), f"legacy rows must stay NULL, got {raw}"

    from app.persistence.s10_full_apply import S10ApplyRepository

    with factory() as s:
        recs = S10ApplyRepository(s).list_chunks(seed["workspace_id"], run_id)
    assert all(list(r.member_layer_ids) == [] for r in recs)
