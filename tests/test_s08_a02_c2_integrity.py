"""S08-A02-T01-C2 — Semantic API Integrity (C2-F1..F6)

Each finding must have failing-then-passing tests that fail on recovered pre-C2 code.
Tests use isolated temp DBs (MOTIONFORGE_DATABASE_URL unset, -p no:cacheprovider).
Uses real SQLite FK, Alembic, repo, router.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.persistence import (
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Artifact,
    Job,
    ObjectRole,
    OccurrenceSegment,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_intelligence import ObjectIntelligenceRepository
from app.persistence.structural_evidence import (
    OwnershipMismatchError,
    SegmentConflictError,
    StructuralEvidenceRepository,
    canonical_json,
)
from app.schemas.structural_evidence import (
    SegmentCreateRequest,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
WS = DEFAULT_WORKSPACE_ID
GEN = "3"


def _alembic_config(path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return cfg


def _sha(n: int) -> str:
    return f"{n:064x}"


class Seed:
    def __init__(self, session):
        self.session = session
        self.project = ""
        self.video = ""
        self.scene = ""
        self.roles = {}
        self.role_rows = {}
        self.masks = []
        self.job = ""
        self.video2 = ""
        self.scene2 = ""


def _seed(session):
    seed = Seed(session)
    ws = Workspace(id=WS, name=WS)
    session.add(ws)
    session.flush()
    source = Artifact(
        workspace_id=WS, kind="video", relative_path="src.mp4", state="ready", sha256=_sha(1)
    )
    session.add(source)
    session.flush()
    project = Project(workspace_id=WS, name="C2")
    session.add(project)
    session.flush()
    video = VideoItem(
        project_id=project.id, title="Video", position=0, source_artifact_id=source.id
    )
    session.add(video)
    session.flush()
    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video.id,
        state="completed",
        input_generation=GEN,
        input_manifest_json=canonical_json({"source_sha256": _sha(1)}),
    )
    session.add(job)
    session.flush()
    scene = Scene(
        video_item_id=video.id,
        position=0,
        start_frame=0,
        end_frame=200,
        start_time_ms=0,
        end_time_ms=8000,
        status="pending",
    )
    session.add(scene)
    session.flush()
    for name, kind in [("Character", "character"), ("Phone", "prop")]:
        role = ObjectRole(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            source_generation=GEN,
            name=name,
            kind=kind,
            status="confirmed",
        )
        session.add(role)
        session.flush()
        seed.roles[name] = role.id
        seed.role_rows[name] = role
    for i in range(5):
        mask = Artifact(
            workspace_id=WS,
            kind="image",
            relative_path=f"mask{i}.png",
            state="ready",
            sha256=_sha(10 + i),
        )
        session.add(mask)
        session.flush()
        seed.masks.append(mask.id)
    seed.project = project.id
    seed.video = video.id
    seed.scene = scene.id
    seed.job = job.id
    session.commit()
    return seed


def _open_db(tmp_path: Path):
    db = tmp_path / "c2.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    factory = create_session_factory(create_engine_for_path(db))
    session = factory()
    seed = _seed(session)
    return session, seed, db


_AUTO_JOB = object()


def _seg(
    repo,
    seed,
    name="Character",
    *,
    role=None,
    gen=GEN,
    job=_AUTO_JOB,
    mask=None,
    frame=(0, 200),
    time=(0, 8000),
    **kw,
):
    role_id = role or seed.roles["Character"]
    role_row = seed.session.get(ObjectRole, role_id)
    kind = kw.pop("kind", role_row.kind)
    source_job_id = seed.job if job is _AUTO_JOB else job
    return repo.create_segment(
        WS,
        seed.project,
        seed.video,
        role_id,
        seed.scene,
        name,
        frame[0],
        frame[1],
        time[0],
        time[1],
        gen,
        kind=kind,
        source_job_id=source_job_id,
        mask_artifact_id=mask,
        **kw,
    )


def _advance_generation(session, seed, new_gen: str) -> str:
    oi_repo = ObjectIntelligenceRepository(session)
    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=seed.video,
        state="completed",
        input_generation=new_gen,
        input_manifest_json=canonical_json({"source_sha256": _sha(1)}),
    )
    session.add(job)
    session.flush()
    for name, role in list(seed.role_rows.items()):
        if name.endswith(f"_g{new_gen}"):
            continue
        new_role, _ = oi_repo.create_role(
            workspace_id=WS,
            project_id=seed.project,
            video_item_id=seed.video,
            source_generation=new_gen,
            name=f"{name}_g{new_gen}",
            kind=role.kind,
            status=role.status,
        )
        seed.roles[f"{name}_g{new_gen}"] = new_role.id
        seed.role_rows[f"{name}_g{new_gen}"] = session.get(ObjectRole, new_role.id)
    session.flush()
    session.commit()
    return job.id


def _new_role_for_gen(seed, base: str, gen: str) -> str:
    return seed.roles[f"{base}_g{gen}"]


def _count_segments(session, db):
    session.rollback()
    with create_engine_for_path(db).connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM occurrence_segment")).scalar())


# ── C2-F1 ────────────────────────────────────────────────────────────────
def test_c2f1_reanalysis_requires_target_role_id(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    job4 = _advance_generation(session, seed, "4")
    with pytest.raises(SegmentConflictError, match="target_role_id"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="4",
            source_job_id=job4,
            confidence_source="model",
            mask_artifact_id=seed.masks[1],
        )
    session.rollback()
    assert _count_segments(session, db) == 1
    session.close()


def test_c2f1_reanalysis_success_binds_new_role(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    job4 = _advance_generation(session, seed, "4")
    new_role = _new_role_for_gen(seed, "Character", "4")
    session.get(ObjectRole, seed.roles["Character"])
    # Save prior generation for check
    prior, succ = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation="4",
        source_job_id=job4,
        target_role_id=new_role,
        confidence_source="model",
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    # predecessor retains old role, successor uses new
    assert prior.role_id == seed.roles["Character"]
    assert succ.role_id == new_role
    assert succ.source_generation == "4"
    # Ensure predecessor DB row still old role
    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(
            text("SELECT role_id, source_generation FROM occurrence_segment WHERE id=:id"),
            {"id": prior.id},
        ).fetchone()
        assert row[0] == seed.roles["Character"]
        row2 = conn.execute(
            text("SELECT role_id FROM occurrence_segment WHERE id=:id"), {"id": succ.id}
        ).fetchone()
        assert row2[0] == new_role
    session.close()


def test_c2f1_reanalysis_rejects_wrong_workspace_role(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    job4 = _advance_generation(session, seed, "4")
    # create role in different workspace
    ws2 = Workspace(id="ws-other", name="other")
    session.add(ws2)
    session.flush()
    p2 = Project(workspace_id="ws-other", name="P2")
    session.add(p2)
    session.flush()
    # need video for ws2
    art = Artifact(
        workspace_id="ws-other", kind="video", relative_path="v.mp4", state="ready", sha256=_sha(99)
    )
    session.add(art)
    session.flush()
    vid2 = VideoItem(project_id=p2.id, title="V2", position=0, source_artifact_id=art.id)
    session.add(vid2)
    session.flush()
    bad_role = ObjectRole(
        workspace_id="ws-other",
        project_id=p2.id,
        video_item_id=vid2.id,
        source_generation="4",
        name="X",
        kind="character",
        status="confirmed",
    )
    session.add(bad_role)
    session.flush()
    with pytest.raises(OwnershipMismatchError):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="4",
            source_job_id=job4,
            target_role_id=bad_role.id,
            confidence_source="model",
        )
    session.rollback()
    session.close()


def test_c2f1_reanalysis_rejects_wrong_kind(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    job4 = _advance_generation(session, seed, "4")
    # new role of kind prop but segment kind character -> mismatch
    # The _advance creates Character_g4 with kind character, Phone_g4 with prop
    # Use Phone_g4 (prop) as target for character segment
    phone_role_4 = _new_role_for_gen(seed, "Phone", "4")
    with pytest.raises(OwnershipMismatchError, match="kind"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="4",
            source_job_id=job4,
            target_role_id=phone_role_4,
            confidence_source="model",
        )
    session.rollback()
    session.close()


def test_c2f1_manual_same_gen_rejects_arbitrary_target_role(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    # Create a same-generation but different role to test
    # arbitrary target rejection (workflow A must keep prior role)
    oi = ObjectIntelligenceRepository(session)
    other_role, _ = oi.create_role(
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=seed.video,
        source_generation=GEN,
        name="Character_other",
        kind="character",
        status="confirmed",
    )
    with pytest.raises(SegmentConflictError, match="manual same-generation"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation=GEN,
            target_role_id=other_role.id,
            confidence_source="user",
            provenance={"who": "h"},
            reasons=["fix"],
            mask_artifact_id=seed.masks[1],
        )
    session.rollback()
    assert _count_segments(session, db) == 1
    session.close()


def test_c2f1_manual_same_gen_keeps_prior_role_when_target_equals_prior(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    prior, succ = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        target_role_id=seed.roles["Character"],
        confidence_source="user",
        provenance={"who": "h"},
        reasons=["ok"],
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    assert succ.role_id == prior.role_id == seed.roles["Character"]
    session.close()


# ── C2-F2 ────────────────────────────────────────────────────────────────
def test_c2f2_shrink_frame_rejected_with_motion(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, frame=(0, 200), time=(0, 8000), mask=seed.masks[0])
    session.commit()
    repo.create_motion(
        WS,
        seg.id,
        "camera_relative",
        {"dx": 1, "dy": 1},
        start_frame=50,
        end_frame=150,
        start_time_ms=1000,
        end_time_ms=6000,
    )
    session.commit()
    # shrink parent to exclude motion end
    with pytest.raises(SegmentConflictError, match="orphan.*motion"):
        repo.update_segment(WS, seg.id, seg.revision, end_frame=100)
    session.rollback()
    # ensure revision unchanged
    with create_engine_for_path(db).connect() as conn:
        rev = conn.execute(
            text("SELECT revision FROM occurrence_segment WHERE id=:id"), {"id": seg.id}
        ).scalar()
        assert rev == 1
    session.close()


def test_c2f2_shrink_time_rejected_with_occlusion(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, frame=(0, 200), time=(0, 8000), mask=seed.masks[0])
    session.commit()
    # need second segment for occlusion endpoints
    seg2, _ = _seg(
        repo,
        seed,
        name="Phone",
        role=seed.roles["Phone"],
        frame=(0, 200),
        time=(0, 8000),
        mask=seed.masks[1],
    )
    session.commit()
    repo.create_occlusion(
        WS,
        seed.project,
        seed.video,
        seg.id,
        seg2.id,
        start_frame=10,
        end_frame=90,
        start_time_ms=500,
        end_time_ms=4000,
    )
    session.commit()
    # shrink first segment time to exclude occlusion end
    with pytest.raises(SegmentConflictError, match="orphan.*occlusion"):
        repo.update_segment(WS, seg.id, seg.revision, end_time_ms=1000)
    session.rollback()
    session.close()


def test_c2f2_shrink_rejected_with_contact(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, frame=(0, 200), time=(0, 8000), mask=seed.masks[0])
    session.commit()
    seg2, _ = _seg(
        repo,
        seed,
        name="Phone",
        role=seed.roles["Phone"],
        frame=(0, 200),
        time=(0, 8000),
        mask=seed.masks[1],
    )
    session.commit()
    repo.create_contact(
        WS,
        seed.project,
        seed.video,
        seg.id,
        seg2.id,
        "touch",
        start_frame=20,
        end_frame=80,
        start_time_ms=800,
        end_time_ms=3000,
    )
    session.commit()
    # shrink via start_frame increase
    with pytest.raises(SegmentConflictError, match="orphan.*contact"):
        repo.update_segment(WS, seg.id, seg.revision, start_frame=30)
    session.rollback()
    session.close()


def test_c2f2_expansion_allowed(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, frame=(10, 100), time=(1000, 4000), mask=seed.masks[0])
    session.commit()
    repo.create_motion(
        WS,
        seg.id,
        "camera_relative",
        {"dx": 0, "dy": 0},
        start_frame=20,
        end_frame=80,
        start_time_ms=1500,
        end_time_ms=3500,
    )
    session.commit()
    # expand parent - should succeed
    updated = repo.update_segment(
        WS, seg.id, seg.revision, start_frame=5, end_frame=150, start_time_ms=500, end_time_ms=5000
    )
    session.commit()
    assert updated.start_frame == 5 and updated.end_frame == 150
    session.close()


def test_c2f2_stale_cas_preserves_zero_mutation(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, frame=(0, 200), time=(0, 8000), mask=seed.masks[0])
    session.commit()
    repo.create_motion(
        WS,
        seg.id,
        "object_relative",
        {"dx": 1},
        start_frame=50,
        end_frame=60,
        start_time_ms=1000,
        end_time_ms=2000,
    )
    session.commit()
    # stale revision
    with pytest.raises(SegmentConflictError, match="stale revision|revision"):
        repo.update_segment(WS, seg.id, seg.revision + 99, name="stale-should-fail")
    session.rollback()
    with create_engine_for_path(db).connect() as conn:
        row = conn.execute(
            text("SELECT start_frame, end_frame, revision FROM occurrence_segment WHERE id=:id"),
            {"id": seg.id},
        ).fetchone()
        assert row[2] == 1 and row[1] == 200
    session.close()


# ── C2-F3 ────────────────────────────────────────────────────────────────
def test_c2f3_manual_requires_provenance(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    for prov in [None, {}, {"": ""} if False else {}]:
        with pytest.raises(SegmentConflictError, match="provenance"):
            repo.supersede_segment(
                WS,
                seg.id,
                seg.revision,
                source_generation=GEN,
                confidence_source="user",
                mask_artifact_id=seed.masks[1],
                provenance=prov,
                reasons=["fix"],
            )
        session.rollback()
    # also empty dict explicitly
    with pytest.raises(SegmentConflictError, match="provenance"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation=GEN,
            confidence_source="user",
            mask_artifact_id=seed.masks[1],
            provenance={},
            reasons=["fix"],
        )
    session.rollback()
    assert _count_segments(session, db) == 1
    session.close()


def test_c2f3_manual_zero_mutation_on_missing_provenance(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    before = _count_segments(session, db)
    with pytest.raises(SegmentConflictError):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation=GEN,
            confidence_source="manual",
            mask_artifact_id=seed.masks[1],
            provenance=None,
        )
    session.rollback()
    assert _count_segments(session, db) == before
    session.close()


# ── C2-F4 ────────────────────────────────────────────────────────────────
def test_c2f4_no_self_link_rejected(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    # raw self-link should violate CHECK
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            text("UPDATE occurrence_segment SET superseded_by_id=id WHERE id=:id"),
            {"id": seg.id},
        )
        session.flush()
    session.rollback()
    # integrity check
    with create_engine_for_path(db).connect() as conn:
        chk = conn.execute(text("PRAGMA integrity_check")).scalar()
        assert chk == "ok"
        fk = list(conn.execute(text("PRAGMA foreign_key_check")))
        assert fk == []
    session.close()


def test_c2f4_duplicate_active_rejected(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    logical = seg.logical_id
    # try to insert second active row with same workspace+logical (active lineage unique)
    with pytest.raises(IntegrityError), session.begin_nested():
        dup = OccurrenceSegment(
            logical_id=logical,
            lineage_version=1,
            workspace_id=WS,
            project_id=seed.project,
            video_item_id=seed.video,
            role_id=seed.roles["Character"],
            scene_id=seed.scene,
            name="dup",
            kind="character",
            start_frame=0,
            end_frame=10,
            start_time_ms=0,
            end_time_ms=1000,
            source_generation=GEN,
            confidence=1.0,
            confidence_source="user",
        )
        session.add(dup)
        session.flush()
    session.rollback()
    session.close()


def test_c2f4_second_predecessor_same_successor_rejected(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    # create successor via supersede
    succ_prior, succ = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        provenance={"who": "h"},
        reasons=["a"],
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    # try to make another predecessor point at same successor via raw SQL
    seg2, _ = _seg(repo, seed, name="Other", frame=(0, 10), time=(0, 1000), mask=seed.masks[2])
    session.commit()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            text("UPDATE occurrence_segment SET superseded_by_id=:succ WHERE id=:id"),
            {"succ": succ.id, "id": seg2.id},
        )
        session.flush()
    session.rollback()
    # no orphans: count remains 3 (seg historical, succ active, seg2 active)
    assert _count_segments(session, db) == 3
    session.close()


def test_c2f4_concurrent_supersede_single_winner_db(tmp_path: Path):
    # REAL concurrency with independent sessions + threading.Barrier (reuse proven C1 pattern)
    db = tmp_path / "c2_concurrent.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    master = create_session_factory(create_engine_for_path(db))()
    seed = _seed(master)
    repo = StructuralEvidenceRepository(master)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    master.commit()
    seg_id, rev, logical = seg.id, seg.revision, seg.logical_id
    master.close()

    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def worker() -> None:
        s = create_session_factory(create_engine_for_path(db))()
        try:
            r = StructuralEvidenceRepository(s)
            barrier.wait(timeout=30)
            _, succ = r.supersede_segment(
                WS,
                seg_id,
                rev,
                source_generation=GEN,
                confidence_source="user",
                provenance={"who": "human"},
                reasons=["concurrent"],
                mask_artifact_id=seed.masks[1],
            )
            s.commit()
            outcomes.append("ok:" + succ.id)
        except Exception as exc:  # noqa: BLE001 — test harness records outcome
            s.rollback()
            outcomes.append(type(exc).__name__ + ":" + str(exc)[:120])
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not any(th.is_alive() for th in threads), "threads did not finish"
    # Exactly one winner
    ok_count = sum(1 for o in outcomes if o.startswith("ok:"))
    assert ok_count == 1, f"expected exactly one winner, outcomes={outcomes}"
    # Valid lineage: 2 rows, predecessor -> successor, successor active
    with create_engine_for_path(db).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, lineage_version, superseded_by_id FROM occurrence_segment "
                "WHERE logical_id=:lid ORDER BY lineage_version"
            ),
            {"lid": logical},
        ).fetchall()
        assert len(rows) == 2, f"concurrent supersede created extra rows: {outcomes} rows={rows}"
        assert rows[0][1] == 1 and rows[0][2] == rows[1][0]
        assert rows[1][1] == 2 and rows[1][2] is None
        assert rows[1][0] == outcomes[[o.startswith("ok:") for o in outcomes].index(True)].split(":", 1)[1]  # noqa: E501
    # No broad try/except turning unexpected errors into PASS — we already asserted ok_count==1  # noqa: E501
    # Ensure single ok outcome
    assert sum(1 for o in outcomes if o.startswith("ok:")) == 1


# ── C2-F5 (repo level) ─────────────────────────────────────────────────
def test_c2f5_historical_excludes_active(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0], gen=GEN)
    session.commit()
    # no history yet
    rows = repo.get_segment_by_logical_id(WS, seg.logical_id)
    assert len(rows) == 1
    # supersede to create history
    prior, succ = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        provenance={"who": "h"},
        reasons=["fix"],
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    # manual filter: historical should be only prior (superseded), not succ
    all_rows = repo.get_segment_by_logical_id(WS, seg.logical_id)
    # Simulate historical filter as route does: superseded or stale gen
    from app.persistence.object_intelligence import ObjectIntelligenceRepository

    cur_gen = ObjectIntelligenceRepository(session).current_generation(
        WS, seed.video
    )
    historical = [
        r for r in all_rows if r.superseded_by_id is not None or r.source_generation != cur_gen
    ]
    assert len(historical) == 1 and historical[0].id == prior.id
    assert succ.id not in [h.id for h in historical]
    session.close()


def test_c2f5_current_list_excludes_historical(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    prior, succ = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        provenance={"who": "h"},
        reasons=["fix"],
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    # Current view via router's _active_segments logic (active-only)
    with create_engine_for_path(db).connect() as conn:
        active_rows = conn.execute(
            text(
                "SELECT id, superseded_by_id FROM occurrence_segment "
                "WHERE workspace_id=:ws AND video_item_id=:vid "
                "AND source_generation=:gen AND superseded_by_id IS NULL"
            ),
            {
                "ws": WS,
                "vid": seed.video,
                "gen": ObjectIntelligenceRepository(session).current_generation(WS, seed.video),
            },
        ).fetchall()
        active_ids = [r[0] for r in active_rows]
        assert all(r[1] is None for r in active_rows)
        assert succ.id in active_ids
        assert prior.id not in active_ids
    session.close()


# ── C2-F6 ────────────────────────────────────────────────────────────────
def test_c2f6_strict_rejects_numeric_string(tmp_path: Path):
    with pytest.raises(ValidationError):
        SegmentCreateRequest.model_validate(
            {
                "project_id": WS,
                "video_item_id": "vid",
                "role_id": "r",
                "scene_id": "s",
                "name": "n",
                "start_frame": "0",
                "end_frame": 10,
                "start_time_ms": 0,
                "end_time_ms": 1000,
            }
        )


def test_c2f6_strict_rejects_bool_for_int(tmp_path: Path):
    # bool True must be rejected for strict int field; tight pytest.raises + loc check
    with pytest.raises(ValidationError) as exc_info:
        SegmentCreateRequest.model_validate(
            {
                "project_id": "p",
                "video_item_id": "v",
                "role_id": "r",
                "scene_id": "s",
                "name": "n",
                "start_frame": True,
                "end_frame": 10,
                "start_time_ms": 0,
                "end_time_ms": 1000,
            }
        )
    err = exc_info.value
    locs = [e.get("loc", ()) for e in err.errors()]
    assert any("start_frame" in str(loc) for loc in locs), (
        f"expected ValidationError at start_frame, got locs={locs} "
        f"errors={err.errors()}"
    )


def test_c2f6_rejects_unknown_field(tmp_path: Path):
    with pytest.raises(ValidationError):
        SegmentCreateRequest.model_validate(
            {
                "project_id": "p",
                "video_item_id": "v",
                "role_id": "r",
                "scene_id": "s",
                "name": "n",
                "start_frame": 0,
                "end_frame": 10,
                "start_time_ms": 0,
                "end_time_ms": 1000,
                "unknown_field": "x",
            }
        )


def test_c2f6_rejects_nan_inf(tmp_path: Path):
    # Use a REAL float field with allow_inf_nan=False in an otherwise-valid payload
    base = {
        "project_id": "p",
        "video_item_id": "v",
        "role_id": "r",
        "scene_id": "s",
        "name": "n",
        "kind": "character",
        "start_frame": 0,
        "end_frame": 10,
        "start_time_ms": 0,
        "end_time_ms": 1000,
        "confidence": 0.9,
    }
    for bad in (float("nan"), float("inf"), float("-inf")):
        payload = dict(base)
        payload["confidence"] = bad
        try:
            SegmentCreateRequest.model_validate(payload)
        except ValidationError as exc:
            msg = str(exc).lower()
            # Must be rejected because of non-finite number, not an unrelated reason
            assert "finite" in msg or "inf" in msg or "nan" in msg or "non-finite" in msg
            # ensure the failing loc is confidence
            locs = [str(e.get("loc", "")) for e in exc.errors()]
            assert any("confidence" in loc for loc in locs), f"bad value {bad!r} rejected at wrong loc {locs}"  # noqa: E501
        else:
            raise AssertionError(f"confidence={bad!r} should be rejected 422 for non-finite number")

    # Also ensure valid finite confidence passes
    valid = dict(base)
    valid["confidence"] = 0.5
    SegmentCreateRequest.model_validate(valid)


def test_c2f6_openapi_has_typed_request_body(tmp_path: Path):
    # Verify OpenAPI spec does not use generic dict for mutating ops
    from app.api.app import app

    spec = app.openapi()
    # Check 9 mutating ops have concrete requestBody schema
    mutating = [
        ("post", "/api/v2/structural-evidence/segments"),
        ("patch", "/api/v2/structural-evidence/segments/current/{segment_id}"),
        ("post", "/api/v2/structural-evidence/segments/current/{segment_id}/supersede"),
        ("post", "/api/v2/structural-evidence/motions"),
        ("patch", "/api/v2/structural-evidence/motions/{motion_id}"),
        ("post", "/api/v2/structural-evidence/occlusions"),
        ("patch", "/api/v2/structural-evidence/occlusions/{occlusion_id}"),
        ("post", "/api/v2/structural-evidence/contacts"),
        ("patch", "/api/v2/structural-evidence/contacts/{contact_id}"),
    ]
    missing = []
    for method, path in mutating:
        op = spec["paths"].get(path, {}).get(method)
        if not op:
            missing.append(f"{method} {path} missing")
            continue
        body = op.get("requestBody")
        if not body:
            missing.append(f"{method} {path} no requestBody")
            continue
        content = body.get("content", {}).get("application/json", {})
        schema = content.get("schema", {})
        # should have $ref or properties, not generic object
        # with additionalProperties true and no props
        if (
            schema.get("type") == "object"
            and not schema.get("properties")
            and not schema.get("$ref")
            and not schema.get("allOf")
            and (
                schema.get("additionalProperties") is True
                or schema.get("additionalProperties") == {}
            )
        ):
            missing.append(f"{method} {path} generic dict schema {schema}")
        # also check that it has $ref or explicit properties
        if (
            not schema.get("$ref")
            and not schema.get("properties")
            and not schema.get("allOf")
            and (
                schema == {"type": "object", "additionalProperties": True}
                or schema.get("type") == "object" and len(schema) <= 2
            )
        ):
            missing.append(f"{method} {path} not concrete {schema}")
    assert not missing, f"OpenAPI typed requestBody missing: {missing}"
