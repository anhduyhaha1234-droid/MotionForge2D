"""S10-T01A domain tests — FullApply run/chunk/publication durable contract.

Covers the five binary bullets:
1. (migration) see test_s10_full_apply_migration.py — single head / roundtrip
2. immutable FK linkage to ApplyCheckpoint revision/hash; stale/cross-project rejected
3. durable states + uniqueness/idempotency prevent duplicate lineage
4. no completed publication can reference .partial / missing / unverified artifact
5. domain can represent deterministic shot/layer chunk boundaries, overlap,
   attempts, resume evidence

Isolated DB per test (tmp_path) — never MAIN.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _cfg(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _upgrade_head(db: Path) -> None:
    command.upgrade(_cfg(db), "head")


def _session_factory(db: Path):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    engine = create_engine_for_path(db)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _hex64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _seed_minimal_checkpoint(db: Path, ws: str = "ws-s10-dom") -> dict[str, str]:
    """Create workspace/project/video + minimal ApplyCheckpoint row.

    Returns dict with workspace_id, project_id, video_item_id, checkpoint_id, checkpoint_hash.
    """
    sf = _session_factory(db)
    with sf() as s:
        # Use raw SQL for speed and to avoid importing many models
        # Ensure workspace exists
        s.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
        proj = f"proj-{uuid.uuid4().hex[:8]}"
        vid = f"vid-{uuid.uuid4().hex[:8]}"
        s.execute(text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"), {"p": proj, "w": ws})
        s.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"), {"v": vid, "p": proj})
        s.execute(text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES (:s,:v,0,0,100,0,1000,'pending')"), {"s": f"sc-{uuid.uuid4().hex[:6]}", "v": vid})
        # Minimal character/pack/reskin for checkpoint FK
        char = f"ch-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,'Hero',:code)"), {"c": char, "w": ws, "code": f"hero_{uuid.uuid4().hex[:4]}"})
        pv = f"pv-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES (:pv,:c,:w,1,'published')"), {"pv": pv, "c": char, "w": ws})
        # need at least CORE_POSE_SLOTS artifacts? Not required for checkpoint FK — only reskin_config FK needs pack
        # Create a minimal artifact for pack completeness is NOT enforced at DB level, so we can skip.
        # Structural lock manifest optional
        # Create reskin_config
        rc = f"rc-{uuid.uuid4().hex[:6]}"
        # Need object_role for reskin_config
        role = f"role-{uuid.uuid4().hex[:6]}"
        s.execute(text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"), {"r": role, "w": ws, "p": proj, "v": vid})
        s.execute(text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,params_json,revision) VALUES (:rc,:w,:p,:r,:c,:pv,'{}',1)"), {"rc": rc, "w": ws, "p": proj, "r": role, "c": char, "pv": pv})
        # Create checkpoint
        ckpt = f"ckpt-{uuid.uuid4().hex[:6]}"
        chash = _hex64(f"ckpt-{ckpt}")
        s.execute(text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,revision) VALUES (:id,:w,:p,:rc,1,'[]','[]',:tbf,'{}',:ch,1)"), {"id": ckpt, "w": ws, "p": proj, "rc": rc, "tbf": _hex64("tbf"), "ch": chash})
        s.commit()
        return {"workspace_id": ws, "project_id": proj, "video_item_id": vid, "checkpoint_id": ckpt, "checkpoint_hash": chash, "reskin_revision": "1"}


def _seed_artifact(db: Path, ws: str, *, state: str = "ready", path: str | None = None) -> str:
    sf = _session_factory(db)
    aid = f"art-{uuid.uuid4().hex[:6]}"
    rel = path if path is not None else f"artifacts/{uuid.uuid4().hex}.mp4"
    with sf() as s:
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,revision) VALUES (:id,:w,'video',:rel,:st,1)"), {"id": aid, "w": ws, "rel": rel, "st": state})
        s.commit()
    return aid


# ── 1. Immutable checkpoint linkage ─────────────────────────────────

def test_create_run_requires_valid_checkpoint(tmp_path: Path) -> None:
    db = tmp_path / "t1.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        # valid
        rec, created = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"],
            expected_checkpoint_revision=1,
            plan_id=_hex64("plan1"), plan_hash=_hex64("ph1"),
            frame_count=100, chunk_config={"chunk_frames": 48, "overlap": 4},
        )
        s.commit()
        assert created is True
        assert rec.apply_checkpoint_hash == seed["checkpoint_hash"]
        # missing checkpoint -> NotFound
        with pytest.raises(Exception, match="not found"):
            repo.create_run(
                seed["workspace_id"], seed["project_id"], seed["video_item_id"], "no-such-ckpt",
                expected_checkpoint_hash=_hex64("x"), expected_checkpoint_revision=1,
                plan_id=_hex64("p2"), plan_hash=_hex64("ph2"), frame_count=10, chunk_config={},
            )


def test_stale_checkpoint_hash_rejected(tmp_path: Path) -> None:
    db = tmp_path / "t2.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyCheckpointStaleError, S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        wrong_hash = _hex64("wrong")
        with pytest.raises(S10ApplyCheckpointStaleError, match="hash mismatch"):
            repo.create_run(
                seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
                expected_checkpoint_hash=wrong_hash, expected_checkpoint_revision=1,
                plan_id=_hex64("plan"), plan_hash=_hex64("ph"), frame_count=10, chunk_config={},
            )


def test_stale_checkpoint_revision_rejected(tmp_path: Path) -> None:
    db = tmp_path / "t3.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyCheckpointStaleError, S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        with pytest.raises(S10ApplyCheckpointStaleError, match="revision mismatch"):
            repo.create_run(
                seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
                expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=99,
                plan_id=_hex64("plan"), plan_hash=_hex64("ph"), frame_count=10, chunk_config={},
            )


def test_cross_project_checkpoint_rejected(tmp_path: Path) -> None:
    db = tmp_path / "t4.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyOwnershipError, S10ApplyRepository

    # create a second project in same workspace
    Sf2 = _session_factory(db)
    with Sf2() as s2:
        other_proj = f"proj-other-{uuid.uuid4().hex[:4]}"
        other_vid = f"vid-other-{uuid.uuid4().hex[:4]}"
        s2.execute(text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'OtherProj')"), {"p": other_proj, "w": seed["workspace_id"]})
        s2.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'OtherVid',1)"), {"v": other_vid, "p": other_proj})
        s2.commit()
    with Sf2() as s:
        repo = S10ApplyRepository(s)
        with pytest.raises(S10ApplyOwnershipError, match="cross-project"):
            repo.create_run(
                seed["workspace_id"], other_proj, other_vid, seed["checkpoint_id"],
                expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
                plan_id=_hex64("plan-cross"), plan_hash=_hex64("ph-cross"), frame_count=10, chunk_config={},
            )


# ── 2. Durable states + uniqueness / idempotency ────────────────────

def test_run_idempotency_and_natural_key_dedupe(tmp_path: Path) -> None:
    db = tmp_path / "t5.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        plan = _hex64("plan-dedupe")
        ph = _hex64("ph-dedupe")
        rec1, c1 = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=plan, plan_hash=ph, frame_count=50, chunk_config={"cf": 10},
            idempotency_key="idem-run-1", natural_key="nat-run-1",
        )
        s.commit()
        assert c1 is True
        # replay same keys -> same row, not created
        rec2, c2 = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=plan, plan_hash=ph, frame_count=50, chunk_config={"cf": 10},
            idempotency_key="idem-run-1", natural_key="nat-run-1",
        )
        s.commit()
        assert c2 is False
        assert rec2.id == rec1.id
        # same natural_key without idempotency -> dedupe
        rec3, c3 = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=plan, plan_hash=ph, frame_count=50, chunk_config={"cf": 10},
            natural_key="nat-run-1",
        )
        s.commit()
        assert c3 is False
        assert rec3.id == rec1.id


def test_chunk_uniqueness_and_idempotency(tmp_path: Path) -> None:
    db = tmp_path / "t6.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-chunk"), plan_hash=_hex64("ph-chunk"), frame_count=100, chunk_config={},
        )
        s.commit()
        ch = _hex64("chunk-content-0")
        c1, created1 = repo.create_chunk(
            seed["workspace_id"], run.id, 0, 0, "shot-a", 0, 47, ch,
            overlap_before=0, overlap_after=4, layer_id="layer-0",
            natural_key="nat-chunk-0", idempotency_key="idem-chunk-0",
        )
        s.commit()
        assert created1 is True
        # replay
        c2, created2 = repo.create_chunk(
            seed["workspace_id"], run.id, 0, 0, "shot-a", 0, 47, ch,
            overlap_before=0, overlap_after=4, layer_id="layer-0",
            natural_key="nat-chunk-0", idempotency_key="idem-chunk-0",
        )
        s.commit()
        assert created2 is False
        assert c2.id == c1.id
        # duplicate (run, chunk_index) without keys -> DB unique violation -> conflict
        from app.persistence.s10_full_apply import S10ApplyConflictError

        with pytest.raises(S10ApplyConflictError):
            repo.create_chunk(
                seed["workspace_id"], run.id, 0, 1, "shot-a", 48, 95, _hex64("other"),
            )


def test_publication_lineage_dedupe(tmp_path: Path) -> None:
    db = tmp_path / "t7.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    art = _seed_artifact(db, seed["workspace_id"], state="ready")
    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-pub"), plan_hash=_hex64("ph-pub"), frame_count=100, chunk_config={},
        )
        s.commit()
        ch = _hex64("pub-content")
        p1, c1 = repo.create_publication(
            seed["workspace_id"], run.id, art, ch, 100, {"frame_count": 100, "timebase": "30fps"},
            seed["checkpoint_id"], seed["checkpoint_hash"], 1,
            natural_key="nat-pub-1", idempotency_key="idem-pub-1",
        )
        s.commit()
        assert c1 is True
        p2, c2 = repo.create_publication(
            seed["workspace_id"], run.id, art, ch, 100, {"frame_count": 100, "timebase": "30fps"},
            seed["checkpoint_id"], seed["checkpoint_hash"], 1,
            natural_key="nat-pub-1", idempotency_key="idem-pub-1",
        )
        s.commit()
        assert c2 is False
        assert p2.id == p1.id
        # lineage dedupe by (run, content_hash) even without keys
        p3, c3 = repo.create_publication(
            seed["workspace_id"], run.id, art, ch, 100, {"frame_count": 100, "timebase": "30fps"},
            seed["checkpoint_id"], seed["checkpoint_hash"], 1,
        )
        s.commit()
        assert c3 is False
        assert p3.id == p1.id


# ── 3. No completed publication can reference .partial / missing / unverified ─

def test_publication_rejects_partial_artifact(tmp_path: Path) -> None:
    db = tmp_path / "t8.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyParamsError, S10ApplyRepository

    art_partial = _seed_artifact(db, seed["workspace_id"], state="ready", path="artifacts/out.mp4.partial")
    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-partial"), plan_hash=_hex64("ph-partial"), frame_count=10, chunk_config={},
        )
        s.commit()
        with pytest.raises(S10ApplyParamsError, match=r"\.partial"):
            repo.create_publication(
                seed["workspace_id"], run.id, art_partial, _hex64("ch-partial"), 10, {"frame_count": 10},
                seed["checkpoint_id"], seed["checkpoint_hash"], 1,
            )


def test_publication_rejects_missing_artifact(tmp_path: Path) -> None:
    db = tmp_path / "t9.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyNotFoundError, S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-miss"), plan_hash=_hex64("ph-miss"), frame_count=10, chunk_config={},
        )
        s.commit()
        with pytest.raises(S10ApplyNotFoundError, match="Artifact"):
            repo.create_publication(
                seed["workspace_id"], run.id, "no-such-artifact", _hex64("ch-miss"), 10, {"frame_count": 10},
                seed["checkpoint_id"], seed["checkpoint_hash"], 1,
            )


def test_publication_rejects_unverified_artifact(tmp_path: Path) -> None:
    db = tmp_path / "t10.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyParamsError, S10ApplyRepository

    art_staging = _seed_artifact(db, seed["workspace_id"], state="staging")
    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-unverified"), plan_hash=_hex64("ph-unverified"), frame_count=10, chunk_config={},
        )
        s.commit()
        with pytest.raises(S10ApplyParamsError, match="not ready"):
            repo.create_publication(
                seed["workspace_id"], run.id, art_staging, _hex64("ch-unv"), 10, {"frame_count": 10},
                seed["checkpoint_id"], seed["checkpoint_hash"], 1,
            )


def test_complete_publication_revalidates_partial(tmp_path: Path) -> None:
    """Even if created as pending, complete() must re-check .partial."""
    db = tmp_path / "t11.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyParamsError, S10ApplyRepository

    art = _seed_artifact(db, seed["workspace_id"], state="ready")
    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-complete"), plan_hash=_hex64("ph-complete"), frame_count=10, chunk_config={},
        )
        s.commit()
        pub, _ = repo.create_publication(
            seed["workspace_id"], run.id, art, _hex64("ch-complete"), 10, {"frame_count": 10},
            seed["checkpoint_id"], seed["checkpoint_hash"], 1, state="pending",
        )
        s.commit()
        # mutate artifact to .partial behind the repo's back
        s.execute(text("UPDATE artifact SET relative_path='artifacts/out.mp4.partial' WHERE id=:a"), {"a": art})
        s.commit()
        with pytest.raises(S10ApplyParamsError, match=r"\.partial"):
            repo.complete_publication(pub.id, seed["workspace_id"])


# ── 4. Deterministic chunk boundaries / overlap / attempts / resume ───

def test_chunk_deterministic_boundaries_and_overlap(tmp_path: Path) -> None:
    db = tmp_path / "t12.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-bound"), plan_hash=_hex64("ph-bound"), frame_count=100, chunk_config={"chunk_frames": 48, "overlap": 4},
        )
        s.commit()
        # Two contiguous shots covering 0-99: shot-a 0-49, shot-b 50-99
        # Chunk 0: core 0-47 overlap_after 4, chunk 1: core 48-49 overlap_before 4 etc.
        c0, _ = repo.create_chunk(seed["workspace_id"], run.id, 0, 0, "shot-a", 0, 47, _hex64("ch0"), overlap_before=0, overlap_after=4, layer_id="bg")
        c1, _ = repo.create_chunk(seed["workspace_id"], run.id, 1, 1, "shot-a", 48, 49, _hex64("ch1"), overlap_before=4, overlap_after=0, layer_id="bg")
        c2, _ = repo.create_chunk(seed["workspace_id"], run.id, 2, 2, "shot-b", 50, 97, _hex64("ch2"), overlap_before=0, overlap_after=4, layer_id="bg")
        c3, _ = repo.create_chunk(seed["workspace_id"], run.id, 3, 3, "shot-b", 98, 99, _hex64("ch3"), overlap_before=4, overlap_after=0, layer_id="bg")
        s.commit()
        # core ranges are contiguous and non-overlapping; overlap is context-only
        chunks = repo.list_chunks(seed["workspace_id"], run.id)
        assert len(chunks) == 4
        # core coverage is exactly 0-99 once
        cores = sorted([(c.core_start_frame, c.core_end_frame) for c in chunks])
        assert cores == [(0, 47), (48, 49), (50, 97), (98, 99)]
        # overlap never extends core End beyond next core Start
        assert c0.overlap_after == 4 and c1.overlap_before == 4
        assert c2.overlap_after == 4 and c3.overlap_before == 4
        # 1-frame shot allowed: create a 1-frame chunk
        c4, _ = repo.create_chunk(seed["workspace_id"], run.id, 4, 4, "shot-c", 0, 0, _hex64("ch4-1frame"), layer_id="fg")
        s.commit()
        assert c4.core_start_frame == c4.core_end_frame == 0


def test_chunk_attempts_and_resume_evidence(tmp_path: Path) -> None:
    db = tmp_path / "t13.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-attempt"), plan_hash=_hex64("ph-attempt"), frame_count=100, chunk_config={},
        )
        s.commit()
        ch = _hex64("chunk-attempt-content")
        c1, _ = repo.create_chunk(seed["workspace_id"], run.id, 0, 0, "shot-a", 0, 47, ch, attempt=1)
        s.commit()
        assert c1.attempt == 1 and c1.verified is False
        # mark verified with correct hash and ready artifact -> resume eligible
        art = _seed_artifact(db, seed["workspace_id"], state="ready")
        verified = repo.mark_chunk_verified(c1.id, seed["workspace_id"], artifact_id=art, verified_content_hash=ch)
        s.commit()
        assert verified.verified is True and verified.state == "completed"
        # wrong hash -> fail-closed
        ch2 = _hex64("chunk-2")
        c2, _ = repo.create_chunk(seed["workspace_id"], run.id, 1, 1, "shot-a", 48, 99, ch2, attempt=1)
        s.commit()
        with pytest.raises(Exception, match="hash mismatch"):
            repo.mark_chunk_verified(c2.id, seed["workspace_id"], artifact_id=art, verified_content_hash=_hex64("wrong-hash"))
        # attempt 2 for same logical chunk_index (different row via Unique run+index+attempt)
        c1_retry, _ = repo.create_chunk(seed["workspace_id"], run.id, 0, 10, "shot-a", 0, 47, _hex64("ch-retry"), attempt=2, natural_key="nat-retry-0-2")
        s.commit()
        assert c1_retry.attempt == 2
        # verified chunks list is the resume evidence
        verified_list = repo.list_verified_chunks(seed["workspace_id"], run.id)
        assert len(verified_list) == 1 and verified_list[0].id == c1.id


def test_multi_layer_chunks_independent(tmp_path: Path) -> None:
    db = tmp_path / "t14.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-multilayer"), plan_hash=_hex64("ph-multilayer"), frame_count=60, chunk_config={},
        )
        s.commit()
        # same core range, different layer_id — independent lineage
        ch_bg = _hex64("bg-content")
        ch_fg = _hex64("fg-content")
        c_bg, _ = repo.create_chunk(seed["workspace_id"], run.id, 0, 0, "shot-a", 0, 29, ch_bg, layer_id="background")
        c_fg, _ = repo.create_chunk(seed["workspace_id"], run.id, 1, 1, "shot-a", 0, 29, ch_fg, layer_id="foreground")
        s.commit()
        assert c_bg.layer_id == "background" and c_fg.layer_id == "foreground"
        assert c_bg.content_hash != c_fg.content_hash


def test_run_status_values(tmp_path: Path) -> None:
    db = tmp_path / "t15.db"
    _upgrade_head(db)
    seed = _seed_minimal_checkpoint(db)
    from app.persistence.s10_full_apply import S10ApplyRepository

    sf = _session_factory(db)
    with sf() as s:
        repo = S10ApplyRepository(s)
        run, _ = repo.create_run(
            seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
            expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
            plan_id=_hex64("plan-status"), plan_hash=_hex64("ph-status"), frame_count=10, chunk_config={},
        )
        s.commit()
        assert run.status == "pending"
        # invalid frame_count rejected
        with pytest.raises(Exception):
            repo.create_run(
                seed["workspace_id"], seed["project_id"], seed["video_item_id"], seed["checkpoint_id"],
                expected_checkpoint_hash=seed["checkpoint_hash"], expected_checkpoint_revision=1,
                plan_id=_hex64("p2"), plan_hash=_hex64("ph2"), frame_count=0, chunk_config={},
            )
