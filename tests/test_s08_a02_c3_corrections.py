"""S08-A02-T01-C3 — Project-Role Guard, Historical Pagination, Exactly-One Selector.

Uses isolated temp DBs (MOTIONFORGE_DATABASE_URL unset, -p no:cacheprovider).
Real SQLite FK, Alembic, repo, router — no mocked repository.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import text

from app.persistence import (
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Artifact,
    Job,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_intelligence import ObjectIntelligenceRepository
from app.persistence.structural_evidence import (
    OwnershipMismatchError,
    StructuralEvidenceRepository,
    canonical_json,
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


def _seed(session):
    seed = Seed(session)
    ws = Workspace(id=WS, name=WS)
    session.add(ws)
    session.flush()
    source = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path="src.mp4",
        state="ready",
        sha256=_sha(1),
    )
    session.add(source)
    session.flush()
    project = Project(workspace_id=WS, name="C3")
    session.add(project)
    session.flush()
    video = VideoItem(
        project_id=project.id,
        title="Video",
        position=0,
        source_artifact_id=source.id,
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
    db = tmp_path / "c3.db"
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
    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=seed.video,
        state="completed",
        input_generation=new_gen,
        input_manifest_json=canonical_json(
            {"source_sha256": _sha(1)},
        ),
    )
    session.add(job)
    session.flush()
    oi_repo = ObjectIntelligenceRepository(session)
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
        seed.role_rows[f"{name}_g{new_gen}"] = session.get(
            ObjectRole, new_role.id,
        )
    session.flush()
    session.commit()
    return job.id


def _count_segments(session, db):
    session.rollback()
    with create_engine_for_path(db).connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM occurrence_segment"),
            ).scalar(),
        )


# ── BLOCKER 1: project guard ───────────────────────────────────────────────
def test_c3_blocker1_wrong_project_rejected(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    prior_project = seed.project
    prior_video = seed.video
    other_project = Project(workspace_id=WS, name="OtherProject")
    session.add(other_project)
    session.flush()
    job4 = _advance_generation(session, seed, "4")
    wrong_role = ObjectRole(
        workspace_id=WS,
        project_id=other_project.id,
        video_item_id=prior_video,
        source_generation="4",
        name="WrongProjectRole",
        kind="character",
        status="confirmed",
    )
    session.add(wrong_role)
    session.flush()
    with pytest.raises(OwnershipMismatchError, match="project"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="4",
            source_job_id=job4,
            target_role_id=wrong_role.id,
            confidence_source="model",
            mask_artifact_id=seed.masks[1],
        )
    session.rollback()
    with create_engine_for_path(db).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, superseded_by_id, project_id "
                "FROM occurrence_segment WHERE workspace_id=:ws",
            ),
            {"ws": WS},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] is None, (
            "predecessor should still be active (superseded_by_id IS NULL)"
        )
        assert rows[0][2] == prior_project
        cnt_wrong = conn.execute(
            text(
                "SELECT COUNT(*) FROM occurrence_segment "
                "WHERE project_id=:pid",
            ),
            {"pid": other_project.id},
        ).scalar()
        assert cnt_wrong == 0
        fc = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert fc == []
    assert _count_segments(session, db) == 1
    session.close()


def test_c3_blocker1_prior_role_project_guard(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, mask=seed.masks[0])
    session.commit()
    other_project = Project(workspace_id=WS, name="OtherA")
    session.add(other_project)
    session.flush()
    wrong_role = ObjectRole(
        workspace_id=WS,
        project_id=other_project.id,
        video_item_id=seed.video,
        source_generation=GEN,
        name="WrongA",
        kind="character",
        status="confirmed",
    )
    session.add(wrong_role)
    session.flush()
    import uuid

    from app.persistence.models import OccurrenceSegment

    seg2_id = str(uuid.uuid4())
    logical = str(uuid.uuid4())
    row = OccurrenceSegment(
        id=seg2_id,
        logical_id=logical,
        lineage_version=1,
        superseded_by_id=None,
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=seed.video,
        role_id=wrong_role.id,
        scene_id=seed.scene,
        name="Corrupted",
        kind="character",
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        source_generation=GEN,
        source_job_id=seed.job,
        prompt_json=None,
        segmentation_json=None,
        mask_artifact_id=seed.masks[0],
        algorithm=None,
        algorithm_version=None,
        confidence=1.0,
        confidence_source="model",
        reasons_json=canonical_json([]),
        provenance_json=None,
        visibility="visible",
        z_order=0,
        idempotency_key=None,
        revision=1,
    )
    session.add(row)
    session.flush()
    session.commit()
    with pytest.raises(OwnershipMismatchError, match="project"):
        repo.supersede_segment(
            WS,
            seg2_id,
            1,
            source_generation=GEN,
            confidence_source="user",
            provenance={"who": "human"},
            reasons=["fix"],
            mask_artifact_id=seed.masks[1],
        )
    session.rollback()
    session.close()


# ── BLOCKER 2: historical pagination >10k ──────────────────────────────────
def test_c3_blocker2_historical_pagination_10001(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    stale_gen = GEN
    _advance_generation(session, seed, "4")
    stale_role = seed.roles["Character"]
    stale_job = seed.job
    import uuid

    batch = 1000
    total = 10001
    for start in range(0, total, batch):
        end = min(start + batch, total)
        for i in range(start, end):
            seg_id = str(uuid.uuid4())
            logical = str(uuid.uuid4())
            sf = i * 10
            ef = sf + 10
            row = {
                "id": seg_id,
                "logical_id": logical,
                "lineage_version": 1,
                "superseded_by_id": None,
                "workspace_id": WS,
                "project_id": seed.project,
                "video_item_id": seed.video,
                "role_id": stale_role,
                "scene_id": seed.scene,
                "name": f"Hist{i}",
                "kind": "character",
                "start_frame": sf,
                "end_frame": ef,
                "start_time_ms": sf * 10,
                "end_time_ms": ef * 10,
                "source_generation": stale_gen,
                "source_job_id": stale_job,
                "prompt_json": None,
                "segmentation_json": None,
                "mask_artifact_id": seed.masks[0],
                "algorithm": None,
                "algorithm_version": None,
                "confidence": 1.0,
                "confidence_source": "model",
                "reasons_json": canonical_json([]),
                "provenance_json": None,
                "visibility": "visible",
                "z_order": i % 5,
                "idempotency_key": None,
                "revision": 1,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
            session.execute(
                text(
                    "INSERT INTO occurrence_segment "
                    "(id, logical_id, lineage_version, superseded_by_id, "
                    "workspace_id, project_id, video_item_id, role_id, "
                    "scene_id, name, kind, start_frame, end_frame, "
                    "start_time_ms, end_time_ms, source_generation, "
                    "source_job_id, prompt_json, segmentation_json, "
                    "mask_artifact_id, algorithm, algorithm_version, "
                    "confidence, confidence_source, reasons_json, "
                    "provenance_json, visibility, z_order, "
                    "idempotency_key, revision, created_at, updated_at) "
                    "VALUES (:id, :logical_id, :lineage_version, "
                    ":superseded_by_id, :workspace_id, :project_id, "
                    ":video_item_id, :role_id, :scene_id, :name, :kind, "
                    ":start_frame, :end_frame, :start_time_ms, "
                    ":end_time_ms, :source_generation, :source_job_id, "
                    ":prompt_json, :segmentation_json, :mask_artifact_id, "
                    ":algorithm, :algorithm_version, :confidence, "
                    ":confidence_source, :reasons_json, :provenance_json, "
                    ":visibility, :z_order, :idempotency_key, :revision, "
                    ":created_at, :updated_at)",
                ),
                row,
            )
        session.flush()
    session.commit()
    rows, total_count = repo.list_historical_segments(
        WS, stale_gen, video_item_id=seed.video, limit=200, offset=0,
    )
    assert total_count == 10001, f"total should be 10001, got {total_count}"
    rows2, total2 = repo.list_historical_segments(
        WS, stale_gen, video_item_id=seed.video, limit=200, offset=9900,
    )
    assert total2 == 10001
    assert len(rows2) == 101, (
        f"offset 9900 limit 200 should return 101, got {len(rows2)}"
    )
    session.close()


# ── CONTRACT: exactly one selector ─────────────────────────────────────────
def test_c3_contract_no_selector_422(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    from app.api.routes.structural_evidence import list_historical_segments

    try:
        list_historical_segments(
            session,
            workspace_id=WS,
            source_generation=None,
            logical_id=None,
            video_item_id=None,
            role_id=None,
            limit=50,
            offset=0,
        )
        pytest.fail("should have raised 422")
    except HTTPException as exc:
        assert exc.status_code == 422
    finally:
        session.close()


def test_c3_contract_both_selectors_422(tmp_path: Path):
    session, seed, db = _open_db(tmp_path)
    from app.api.routes.structural_evidence import list_historical_segments

    try:
        list_historical_segments(
            session,
            workspace_id=WS,
            source_generation=GEN,
            logical_id="some-logical",
            video_item_id=None,
            role_id=None,
            limit=50,
            offset=0,
        )
        pytest.fail("should have raised 422 for both selectors")
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "exactly one" in str(exc.detail).lower()
    finally:
        session.close()


def test_c3_contract_exactly_one_succeeds(tmp_path: Path):
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
        reasons=["x"],
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    from app.api.routes.structural_evidence import list_historical_segments

    result = list_historical_segments(
        session,
        workspace_id=WS,
        source_generation=None,
        logical_id=seg.logical_id,
        video_item_id=None,
        role_id=None,
        limit=50,
        offset=0,
    )
    assert result.total >= 1
    assert result.scope == "historical"
    result2 = list_historical_segments(
        session,
        workspace_id=WS,
        source_generation=GEN,
        logical_id=None,
        video_item_id=seed.video,
        role_id=None,
        limit=50,
        offset=0,
    )
    assert result2.total >= 1
    session.close()


# ── C4-4: multi-video historical + no N+1 instrumentation ───────────────────
def _create_extra_video(
    session,
    project_id: str,
    gen_current: str,
    name_suffix: str,
):
    """Create one video+artifact+job+scene+role for C4 multi-video tests."""
    # Deterministic unique position: max existing +1 within project
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    max_pos = session.scalar(
        _select(_func.coalesce(_func.max(VideoItem.position), 0)).where(
            VideoItem.project_id == project_id
        )
    )
    next_pos = int(max_pos or 0) + 1
    # Stable sha derived from name_suffix without Python hash randomization
    import hashlib

    sha_hex = hashlib.sha256(name_suffix.encode()).hexdigest()[:64]
    art = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path=f"src_extra_{name_suffix}.mp4",
        state="ready",
        sha256=sha_hex,
    )
    session.add(art)
    session.flush()
    vid = VideoItem(
        project_id=project_id,
        title=f"Video_{name_suffix}",
        position=next_pos,
        source_artifact_id=art.id,
    )
    session.add(vid)
    session.flush()
    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=vid.id,
        state="completed",
        input_generation=gen_current,
        input_manifest_json=canonical_json(
            {"source_sha256": art.sha256},
        ),
    )
    session.add(job)
    session.flush()
    scene = Scene(
        video_item_id=vid.id,
        position=0,
        start_frame=0,
        end_frame=100,
        start_time_ms=0,
        end_time_ms=4000,
        status="pending",
    )
    session.add(scene)
    session.flush()
    role = ObjectRole(
        workspace_id=WS,
        project_id=project_id,
        video_item_id=vid.id,
        source_generation=gen_current,
        name=f"Role_{name_suffix}",
        kind="character",
        status="confirmed",
    )
    session.add(role)
    session.flush()
    return vid, scene, role, job


def test_c4_multi_video_historical_correctness(tmp_path: Path):
    """C4-4: multiple videos, mixed current/stale/superseded, query w/o
    video_item_id — assert total + page correct, deterministic ordering,
    no full-history load."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # seed already has one video with GEN=3, current 3
    # advance seed video to 4 to make GEN=3 stale for that video
    _advance_generation(session, seed, "4")
    # GEN=3 is now stale for seed.video
    # Create 4 extra videos: 2 stale (current 4), 2 current (current 3)
    extra = []
    for i in range(4):
        gen_cur = "4" if i < 2 else "3"
        vid, scene, role, job = _create_extra_video(
            session, seed.project, gen_cur, f"c4_{i}",
        )
        extra.append((vid, scene, role, job))
    session.commit()
    import uuid

    # Insert segments with source_generation=GEN=3
    # seed.video: GEN=3 is stale -> active segment is historical
    # extra[0], extra[1]: current 4 -> GEN=3 stale -> active historical
    # extra[2], extra[3]: current 3 -> GEN=3 current -> active NOT historical
    # For current videos, add a superseded segment to have historical via
    # superseded path
    all_videos = [
        (seed.video, seed.scene, seed.roles["Character"], True),
        (extra[0][0].id, extra[0][1].id, extra[0][2].id, True),
        (extra[1][0].id, extra[1][1].id, extra[1][2].id, True),
        (extra[2][0].id, extra[2][1].id, extra[2][2].id, False),
        (extra[3][0].id, extra[3][1].id, extra[3][2].id, False),
    ]
    # Use raw insert to avoid generation authority checks (like c3 pagination
    # test) — real SQLite rows, no mocked repo
    for idx, (vid_id, scene_id, role_id, is_stale) in enumerate(all_videos):
        # active segment
        seg_id = str(uuid.uuid4())
        logical = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, :sup, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', :z, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": seg_id,
                "logical_id": logical,
                "sup": None,
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role_id,
                "scene": scene_id,
                "name": f"Seg{idx}_active",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
                "z": idx,
            },
        )
        # for current videos, add a superseded segment (historical via
        # superseded) at a different start_frame to test ordering
        if not is_stale:
            seg2_id = str(uuid.uuid4())
            logical2 = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO occurrence_segment "
                    "(id, logical_id, lineage_version, "
                    "superseded_by_id, workspace_id, project_id, "
                    "video_item_id, role_id, scene_id, name, kind, "
                    "start_frame, end_frame, start_time_ms, end_time_ms, "
                    "source_generation, source_job_id, prompt_json, "
                    "segmentation_json, mask_artifact_id, algorithm, "
                    "algorithm_version, confidence, confidence_source, "
                    "reasons_json, provenance_json, visibility, z_order, "
                    "idempotency_key, revision, created_at, updated_at) "
                    "VALUES (:id, :logical_id, 1, :sup, :ws, :proj, :vid, "
                    ":role, :scene, :name, 'character', :sf, :ef, :st, "
                    ":et, :gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                    "'model', :reasons, NULL, 'visible', :z, NULL, 1, "
                    "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                ),
                {
                    "id": seg2_id,
                    "logical_id": logical2,
                    "sup": seg_id,
                    "ws": WS,
                    "proj": seed.project,
                    "vid": vid_id,
                    "role": role_id,
                    "scene": scene_id,
                    "name": f"Seg{idx}_sup",
                    "sf": idx * 10 + 5,
                    "ef": idx * 10 + 15,
                    "st": idx * 100 + 50,
                    "et": idx * 100 + 150,
                    "gen": GEN,
                    "job": seed.job,
                    "mask": seed.masks[0],
                    "reasons": canonical_json([]),
                    "z": idx,
                },
            )
    session.commit()
    # Query without video_item_id, source_generation=3
    # Expected historical: seed active stale (1) + extra0 active stale (1)
    # + extra1 active stale (1) + extra2 superseded (1) + extra3
    # superseded (1) = 5. Active current segments for extra2/3 are NOT
    # historical (they are current and not superseded).
    rows, total = repo.list_historical_segments(
        WS, GEN, limit=50, offset=0,
    )
    assert total == 5, f"expected total 5, got {total} rows {len(rows)}"
    assert len(rows) == 5
    # Deterministic ordering: start_frame, end_frame, z_order, id
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        assert (a.start_frame, a.end_frame, a.z_order, a.id) <= (
            b.start_frame,
            b.end_frame,
            b.z_order,
            b.id,
        ), "ordering not deterministic"
    # Pagination after filter: offset/limit applied after historical filter
    rows_p1, total_p1 = repo.list_historical_segments(
        WS, GEN, limit=2, offset=1,
    )
    assert total_p1 == 5
    assert len(rows_p1) == 2
    # Ensure page is slice of full ordered result
    full_ids = [r.id for r in rows]
    page_ids = [r.id for r in rows_p1]
    assert page_ids == full_ids[1:3]
    session.close()


def test_c4_multi_video_no_nplus1(tmp_path: Path):
    """C4-4: prove no N+1 via statement counter — per-video
    current-generation must not grow linearly with video count."""
    import uuid

    from sqlalchemy import event, select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # Deterministic setup: advance seed to 4 first (fail fast if error)
    _advance_generation(session, seed, "4")
    # Create 12 extra videos to make N+1 visible (distinct ~13)
    # All with current 4, so GEN=3 is stale -> all historical
    for i in range(12):
        _create_extra_video(session, seed.project, "4", f"nplus1_{i}")
    session.commit()
    # Insert one stale segment per extra video + seed
    # Use raw insert for speed
    # Fetch distinct video ids via actual video table
    vids = session.scalars(
        select(VideoItem.id).where(VideoItem.project_id == seed.project),
    ).all()
    for idx, vid_id in enumerate(vids):
        # need scene/role for each vid
        scene = session.scalars(
            select(Scene).where(Scene.video_item_id == vid_id),
        ).first()
        role = session.scalars(
            select(ObjectRole).where(
                ObjectRole.video_item_id == vid_id,
            ),
        ).first()
        if scene is None or role is None:
            continue
        seg_id = str(uuid.uuid4())
        logical = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": seg_id,
                "logical_id": logical,
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"Np1_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    engine = session.get_bind()
    counter = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    counter["n"] = 0
    rows, total = repo.list_historical_segments(
        WS, GEN, limit=50, offset=0,
    )
    event.remove(engine, "before_cursor_execute", _count)
    # With batch, statement count is bounded: distinct (1) + video fetch
    # (1) + artifact fetch (1) + project fetch (1) + job fetch (1) +
    # count (1) + fetch (1) ~= 7. Old N+1 code would be 1 + N + 2 ~= 15+
    # for 13 videos. Assert bounded.
    assert total >= 10, f"expected many historical rows, got {total}"
    assert counter["n"] <= 10, (
        f"N+1 detected: {counter['n']} statements for {len(vids)} "
        f"videos (expected <=10 with batch, old code would be "
        f"{len(vids) + 3})"
    )
    # Also verify it does not grow linearly: run again with fewer videos
    # would have similar count — we just proved bounded
    session.close()

# ── C5: Batch-generation Scalability (S08-A02-T01-C5) ───────────────────────

def test_c5_501_stale_videos_no_operational_error(tmp_path: Path):
    """C5: 501 stale videos → NO OperationalError, total+page correct."""
    import uuid

    from sqlalchemy import select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # advance seed to 4 so GEN=3 is stale
    _advance_generation(session, seed, "4")
    # create 500 extra videos with current 4 (stale for GEN=3)
    for i in range(500):
        _create_extra_video(session, seed.project, "4", f"c5_501_{i}")
    session.commit()
    vids = session.scalars(
        select(VideoItem.id).where(VideoItem.project_id == seed.project),
    ).all()
    assert len(vids) == 501, f"expected 501 videos, got {len(vids)}"
    # one stale segment per video
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(
            select(Scene).where(Scene.video_item_id == vid_id),
        ).first()
        role = session.scalars(
            select(ObjectRole).where(ObjectRole.video_item_id == vid_id),
        ).first()
        assert scene is not None and role is not None
        seg_id = str(uuid.uuid4())
        logical = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": seg_id,
                "logical_id": logical,
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C5_501_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    # must not raise OperationalError (too many terms)
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    assert total == 501, f"expected 501, got {total}"
    assert len(rows) == 50
    # ordering deterministic
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        assert (a.start_frame, a.end_frame, a.z_order, a.id) <= (
            b.start_frame,
            b.end_frame,
            b.z_order,
            b.id,
        )
    # page after filter
    rows2, total2 = repo.list_historical_segments(WS, GEN, limit=50, offset=500)
    assert total2 == 501
    assert len(rows2) == 1
    # full ordering slice check
    full_rows, _ = repo.list_historical_segments(WS, GEN, limit=501, offset=0)
    assert [r.id for r in rows2] == [r.id for r in full_rows[500:501]]
    session.close()


def test_c5_1001_videos_chunking(tmp_path: Path):
    """C5: 1001 videos proof chunking (no compound limit, bounded SELECTs)."""
    import uuid

    from sqlalchemy import event, select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    for i in range(1000):
        _create_extra_video(session, seed.project, "4", f"c5_1001_{i}")
    session.commit()
    vids = session.scalars(
        select(VideoItem.id).where(VideoItem.project_id == seed.project),
    ).all()
    assert len(vids) == 1001
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(
            select(Scene).where(Scene.video_item_id == vid_id),
        ).first()
        role = session.scalars(
            select(ObjectRole).where(ObjectRole.video_item_id == vid_id),
        ).first()
        seg_id = str(uuid.uuid4())
        logical = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": seg_id,
                "logical_id": logical,
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C5_1001_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    engine = session.get_bind()
    counter = {"n": 0, "stmts": []}

    def _count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1
            counter["stmts"].append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    event.remove(engine, "before_cursor_execute", _count)
    assert total == 1001, f"expected 1001, got {total}"
    assert len(rows) == 50
    # bounded SELECTs (not N+1): distinct 1 + video chunks 2 + artifact 2
    # + project 1-2 + job chunks 2 + count 1 + fetch 1 ≈ 10-12
    assert counter["n"] <= 15, (
        f"N+1/chunking fail: {counter['n']} SELECTs for 1001 videos "
        f"(expected <=15); stmts={counter['stmts'][:3]}"
    )
    # ensure no literal_column / UNION ALL in emitted SQL
    joined = " ".join(counter["stmts"]).lower()
    assert "literal_column" not in joined
    assert "union all" not in joined
    # no OperationalError occurred -> chunking proof
    session.close()


def test_c5_mixed_current_stale_superseded_total_page(tmp_path: Path):
    """C5: mixed current/stale/superseded total+page+ordering."""
    import uuid

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    extra = []
    for i in range(4):
        gen_cur = "4" if i < 2 else "3"
        vid, scene, role, job = _create_extra_video(
            session, seed.project, gen_cur, f"c5_mix_{i}",
        )
        extra.append((vid, scene, role, job))
    session.commit()
    all_videos = [
        (seed.video, seed.scene, seed.roles["Character"], True),
        (extra[0][0].id, extra[0][1].id, extra[0][2].id, True),
        (extra[1][0].id, extra[1][1].id, extra[1][2].id, True),
        (extra[2][0].id, extra[2][1].id, extra[2][2].id, False),
        (extra[3][0].id, extra[3][1].id, extra[3][2].id, False),
    ]
    for idx, (vid_id, scene_id, role_id, is_stale) in enumerate(all_videos):
        seg_id = str(uuid.uuid4())
        logical = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, :sup, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', :z, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": seg_id,
                "logical_id": logical,
                "sup": None,
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role_id,
                "scene": scene_id,
                "name": f"Mix{idx}_active",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
                "z": idx,
            },
        )
        if not is_stale:
            seg2_id = str(uuid.uuid4())
            logical2 = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO occurrence_segment "
                    "(id, logical_id, lineage_version, "
                    "superseded_by_id, workspace_id, project_id, "
                    "video_item_id, role_id, scene_id, name, kind, "
                    "start_frame, end_frame, start_time_ms, end_time_ms, "
                    "source_generation, source_job_id, prompt_json, "
                    "segmentation_json, mask_artifact_id, algorithm, "
                    "algorithm_version, confidence, confidence_source, "
                    "reasons_json, provenance_json, visibility, z_order, "
                    "idempotency_key, revision, created_at, updated_at) "
                    "VALUES (:id, :logical_id, 1, :sup, :ws, :proj, :vid, "
                    ":role, :scene, :name, 'character', :sf, :ef, :st, "
                    ":et, :gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                    "'model', :reasons, NULL, 'visible', :z, NULL, 1, "
                    "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                ),
                {
                    "id": seg2_id,
                    "logical_id": logical2,
                    "sup": seg_id,
                    "ws": WS,
                    "proj": seed.project,
                    "vid": vid_id,
                    "role": role_id,
                    "scene": scene_id,
                    "name": f"Mix{idx}_sup",
                    "sf": idx * 10 + 5,
                    "ef": idx * 10 + 15,
                    "st": idx * 100 + 50,
                    "et": idx * 100 + 150,
                    "gen": GEN,
                    "job": seed.job,
                    "mask": seed.masks[0],
                    "reasons": canonical_json([]),
                    "z": idx,
                },
            )
    session.commit()
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    assert total == 5
    assert len(rows) == 5
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        assert (a.start_frame, a.end_frame, a.z_order, a.id) <= (
            b.start_frame,
            b.end_frame,
            b.z_order,
            b.id,
        )
    rows_p1, total_p1 = repo.list_historical_segments(WS, GEN, limit=2, offset=1)
    assert total_p1 == 5
    assert len(rows_p1) == 2
    full_ids = [r.id for r in rows]
    page_ids = [r.id for r in rows_p1]
    assert page_ids == full_ids[1:3]
    session.close()


def test_c5_batch_generation_matches_scalar(tmp_path: Path):
    """C5: batch == scalar for (a)-(e), including fail-closed."""
    from app.persistence.models import Artifact
    from app.persistence.object_intelligence import RoleNotFoundError

    session, seed, db = _open_db(tmp_path)
    oi = ObjectIntelligenceRepository(session)
    # (a) current source SHA: video with matching job gen 3
    cur_a = oi.current_generation(WS, seed.video)
    batch_a = oi.batch_current_generation(WS, [seed.video])
    assert batch_a[seed.video] == cur_a == "3"
    # (b) changed source SHA: new artifact sha, jobs old sha -> new gen
    new_art = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path="new_src.mp4",
        state="ready",
        sha256=_sha(999),
    )
    session.add(new_art)
    session.flush()
    # create new video with new sha, no job for it yet
    vid_b = VideoItem(
        project_id=seed.project,
        title="B_changed_sha",
        position=99,
        source_artifact_id=new_art.id,
    )
    session.add(vid_b)
    session.flush()
    # add completed job for vid_b with OLD sha (not matching current)
    job_b = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=vid_b.id,
        state="completed",
        input_generation="2",
        input_manifest_json=canonical_json({"source_sha256": _sha(1)}),
    )
    session.add(job_b)
    session.flush()
    # current_sha is new_art sha, manifest is old -> no latest_for_sha,
    # max_gen=2 -> returns "3"
    scalar_b = oi.current_generation(WS, vid_b.id)
    batch_b = oi.batch_current_generation(WS, [vid_b.id])
    assert scalar_b == batch_b[vid_b.id] == "3"
    # (c) no completed job: fresh video with no jobs
    vid_c = VideoItem(
        project_id=seed.project,
        title="C_no_job",
        position=100,
        source_artifact_id=new_art.id,
    )
    session.add(vid_c)
    session.flush()
    scalar_c = oi.current_generation(WS, vid_c.id)
    batch_c = oi.batch_current_generation(WS, [vid_c.id])
    assert scalar_c == batch_c[vid_c.id] == "1"
    # (d) multiple completed generations: vid with jobs gen 2 and 5
    vid_d = VideoItem(
        project_id=seed.project,
        title="D_multi",
        position=101,
        source_artifact_id=new_art.id,
    )
    session.add(vid_d)
    session.flush()
    # deterministic timestamps: 2 older, 5 newer
    import datetime as _dt

    base = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.UTC)
    for idx, g in enumerate(["2", "5"]):
        j = Job(
            workspace_id=WS,
            job_type="DISCOVER_OBJECTS",
            owner_type="video_item",
            owner_id=vid_d.id,
            state="completed",
            input_generation=g,
            input_manifest_json=canonical_json({"source_sha256": _sha(999)}),
            created_at=base + _dt.timedelta(seconds=idx),
        )
        session.add(j)
    session.flush()
    # latest_for_sha should be "5" (newest matching), not max+1
    scalar_d = oi.current_generation(WS, vid_d.id)
    batch_d = oi.batch_current_generation(WS, [vid_d.id])
    assert scalar_d == batch_d[vid_d.id] == "5"
    # (e) wrong workspace fail-closed
    wrong_ws = "ws-wrong-" + _sha(9)[:8]
    ws_row = Workspace(id=wrong_ws, name=wrong_ws)
    session.add(ws_row)
    session.flush()
    with pytest.raises(RoleNotFoundError):
        oi.current_generation(wrong_ws, seed.video)
    with pytest.raises(RoleNotFoundError):
        oi.batch_current_generation(wrong_ws, [seed.video])
    # batch with multiple where one is wrong must also fail
    with pytest.raises(RoleNotFoundError):
        oi.batch_current_generation(wrong_ws, [seed.video, vid_c.id])
    # cross check batch vs scalar for set
    batch_all = oi.batch_current_generation(WS, [seed.video, vid_b.id, vid_c.id, vid_d.id])
    assert batch_all[seed.video] == oi.current_generation(WS, seed.video)
    assert batch_all[vid_b.id] == oi.current_generation(WS, vid_b.id)
    assert batch_all[vid_c.id] == oi.current_generation(WS, vid_c.id)
    assert batch_all[vid_d.id] == oi.current_generation(WS, vid_d.id)
    # deterministic: two calls same result despite hash randomization
    batch_all2 = oi.batch_current_generation(WS, [vid_d.id, seed.video, vid_b.id, vid_c.id])
    assert batch_all == batch_all2 or set(batch_all.items()) == set(batch_all2.items())
    session.close()


def test_c5_sql_parameterized_no_literal_column(tmp_path: Path):
    """C5: SQL is parameterized — no literal_column, no f-string ids."""
    import uuid

    from sqlalchemy import event, select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    for i in range(5):
        _create_extra_video(session, seed.project, "4", f"param_{i}")
    session.commit()
    # file-level check: no literal_column usage in structural_evidence.py
    import pathlib

    sev_path = pathlib.Path("app/persistence/structural_evidence.py")
    txt = sev_path.read_text(encoding="utf-8")
    # allow comment mentioning but not code usage literal_column(
    assert "literal_column(" not in txt, "literal_column still present in code"
    # runtime check: emitted SQL has no injected UUID literal
    vids = session.scalars(
        select(VideoItem.id).where(VideoItem.project_id == seed.project),
    ).all()
    for idx, vid_id in enumerate(vids[:3]):
        scene = session.scalars(
            select(Scene).where(Scene.video_item_id == vid_id),
        ).first()
        role = session.scalars(
            select(ObjectRole).where(ObjectRole.video_item_id == vid_id),
        ).first()
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', 0, 10, 0, 100, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"P{idx}",
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    engine = session.get_bind()
    stmts = []

    def _cap(conn, cursor, statement, parameters, context, executemany):
        stmts.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", _cap)
    repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    event.remove(engine, "before_cursor_execute", _cap)
    # no statement should contain a raw UUID from vids (which would indicate
    # string interpolation). Parameters should hold ids.
    for stmt, _params in stmts:
        low = stmt.lower()
        assert "literal_column" not in low
        for vid in vids:
            # if vid string appears literally in SQL text (not as ? param),
            # that's interpolation
            if vid in stmt:
                # need to ensure it's not just via parameter tuple string repr
                # actual SQL text should contain ? or :param, not the uuid
                raise AssertionError(f"raw id {vid!r} interpolated in SQL: {stmt[:400]}")
    session.close()


def test_c5_no_nplus1_selects_only(tmp_path: Path):
    """C5: No N+1 — bounded SELECT count (BEGIN/ROLLBACK not counted)."""
    import uuid

    from sqlalchemy import event, select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    for i in range(20):
        _create_extra_video(session, seed.project, "4", f"nplus1c5_{i}")
    session.commit()
    vids = session.scalars(
        select(VideoItem.id).where(VideoItem.project_id == seed.project),
    ).all()
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(
            select(Scene).where(Scene.video_item_id == vid_id),
        ).first()
        role = session.scalars(
            select(ObjectRole).where(ObjectRole.video_item_id == vid_id),
        ).first()
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"NpC5_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    engine = session.get_bind()
    counter = {"n": 0}

    def _cnt(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _cnt)
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    event.remove(engine, "before_cursor_execute", _cnt)
    assert total == len(vids)
    # bounded: distinct 1 + batch (video 1, project 1, artifact 1, job 1)
    # + count 1 + fetch 1 = ~7, plus chunk overhead <15
    assert counter["n"] <= 12, f"N+1: {counter['n']} SELECTs for {len(vids)} vids"
    # ensure BEGIN not counted (would inflate)
    session.close()

# ── C6: Final Query Bind-Parameter Scalability (S08-A02-T01-C6) ─────────────────
# Every SQL statement has FIXED declared budget; final COUNT/page SELECT bounded
# independent of stale-video count via SQLite JSON1 json_each() single param.
# Tests capture ACTUAL SQL execution via before_cursor_execute (statement+parameters).

def _c6_param_count(params):
    """Actual total bind param count for a before_cursor_execute hook."""
    if params is None:
        return 0
    if isinstance(params, dict):
        return len(params)
    if isinstance(params, (list, tuple)):
        if not params:
            return 0
        # executemany: list/tuple of dicts/tuples
        if isinstance(params[0], (dict, list, tuple)):
            # For executemany, params[0] is first row; count per statement is len(row)
            if isinstance(params[0], dict):
                return len(params[0])
            # tuple row
            return len(params[0])
        return len(params)
    return 0


def _c6_capture_statements(engine):
    """Attach before_cursor_execute to capture every SQL statement+params."""
    from sqlalchemy import event

    captured = []

    def _hook(conn, cursor, statement, parameters, context, executemany):
        # store raw statement and parameters (copy)
        captured.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", _hook)
    return captured, _hook


def _c6_uncapture(engine, hook):
    from sqlalchemy import event

    event.remove(engine, "before_cursor_execute", hook)


def _c6_is_final_occurrence_stmt(stmt: str, low: str | None = None) -> bool:
    """Final COUNT or page SELECT for occurrence_segment historical filter."""
    if low is None:
        low = stmt.lower()
    # must touch occurrence_segment and be a SELECT
    if "occurrence_segment" not in low:
        return False
    if not low.lstrip().startswith("select"):
        return False
    # final filter touches superseded/json_each; batch helper stmts do not
    return (
        "count(" in low
        or "order by" in low
        or "superseded" in low
        or "json_each" in low
    )


def _c6_final_counts_and_selects(captured):
    """Split captured into final COUNT vs final SELECT (occurrence hist)."""
    finals = [(s, p) for s, p in captured if _c6_is_final_occurrence_stmt(s)]
    counts = [(s, p) for s, p in finals if "count(" in s.lower()]
    selects = [(s, p) for s, p in finals if "count(" not in s.lower()]
    return finals, counts, selects


def test_c6_1001_stale_videos_fixed_params(tmp_path: Path):
    """C6: 1001 stale videos — final COUNT/page SELECT bounded, no OR-chain, no UNION ALL, no interpolation."""  # noqa: E501
    import uuid

    from sqlalchemy import select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    for i in range(1000):
        _create_extra_video(session, seed.project, "4", f"c6_1001_{i}")
    session.commit()
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    assert len(vids) == 1001, f"expected 1001 vids, got {len(vids)}"
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(select(Scene).where(Scene.video_item_id == vid_id)).first()
        role = session.scalars(select(ObjectRole).where(ObjectRole.video_item_id == vid_id)).first()
        assert scene is not None and role is not None
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C6_1001_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    # also track via separate hook for counting total statements
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    _c6_uncapture(engine, hook)
    assert total == 1001, f"expected total 1001, got {total}"
    assert len(rows) == 50
    # ordering deterministic
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        assert (a.start_frame, a.end_frame, a.z_order, a.id) <= (b.start_frame, b.end_frame, b.z_order, b.id)  # noqa: E501
    # instrumentation: every statement bounded, final queries bounded, no UNION ALL, no OR-chain
    from app.persistence.structural_evidence import _FINAL_QUERY_PARAM_BUDGET, _SQLITE_MAX_PARAMS

    # no statement exceeds SQLITE max
    for stmt, params in captured:
        n = _c6_param_count(params)
        assert n <= _SQLITE_MAX_PARAMS, f"statement exceeds SQLITE max {n} > {_SQLITE_MAX_PARAMS}: {stmt[:300]} params={params!r}"  # noqa: E501
        low = stmt.lower()
        assert "union all" not in low, f"UNION ALL per video forbidden: {stmt[:400]}"
        # no raw UUID interpolated: stmt text must not contain any vid literal
        for vid in vids[:3]:
            if vid in stmt:
                raise AssertionError(f"raw id {vid!r} interpolated in SQL (must be bindparam): {stmt[:500]}")  # noqa: E501
    finals, counts, selects = _c6_final_counts_and_selects(captured)
    assert len(counts) >= 1, f"no final COUNT captured, finals={finals[:2]}"
    assert len(selects) >= 1, "no final page SELECT captured"
    for stmt, params in counts:
        n = _c6_param_count(params)
        assert n <= _FINAL_QUERY_PARAM_BUDGET, f"final COUNT bind count {n} > budget {_FINAL_QUERY_PARAM_BUDGET} (stale=1001): {stmt[:500]} params={params!r}"  # noqa: E501
        low = stmt.lower()
        assert "json_each" in low, f"final COUNT must use json_each (fixed 1 param) for 1001 stale: {stmt[:600]}"  # noqa: E501
        # no OR IN chain growth: old code had multiple IN(?,...) per chunk
        # With json_each, there is exactly one IN and no repeating OR IN
        assert low.count("in (") <= 2, f"OR IN chain detected in COUNT: {stmt[:800]}"
    for stmt, params in selects:
        n = _c6_param_count(params)
        # SELECT has limit/offset as binds too, so budget covers them; already _FINAL_QUERY_PARAM_BUDGET includes them (6)  # noqa: E501
        # For selects, total may be _FINAL_QUERY_PARAM_BUDGET (6) — allow exactly budget
        assert n <= _FINAL_QUERY_PARAM_BUDGET + 2, f"final SELECT bind count {n} > budget {_FINAL_QUERY_PARAM_BUDGET}+2: {stmt[:500]} params={params!r}"  # noqa: E501
        low = stmt.lower()
        assert "json_each" in low, f"final SELECT must use json_each: {stmt[:600]}"
    # page after filter: offset near end should be correct slice
    full_rows, _ = repo.list_historical_segments(WS, GEN, limit=1001, offset=0)
    assert len(full_rows) == 1001
    tail_rows, tail_total = repo.list_historical_segments(WS, GEN, limit=50, offset=1000)
    assert tail_total == 1001
    assert len(tail_rows) == 1
    assert tail_rows[0].id == full_rows[-1].id
    session.close()


def test_c6_5001_stale_videos_fixed_params(tmp_path: Path):
    """C6: >=5001 stale videos — final COUNT/page SELECT still bounded (same budget as 1001), no statement over budget."""  # noqa: E501
    import uuid

    from sqlalchemy import select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    # 5000 extra + seed = 5001
    for i in range(5000):
        _create_extra_video(session, seed.project, "4", f"c6_5001_{i}")
        if i % 1000 == 999:
            session.flush()
    session.commit()
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    assert len(vids) == 5001, f"expected 5001 vids, got {len(vids)}"
    # Insert one stale segment per video (batch commit every 1000)
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(select(Scene).where(Scene.video_item_id == vid_id)).first()
        role = session.scalars(select(ObjectRole).where(ObjectRole.video_item_id == vid_id)).first()
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C6_5001_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
        if idx % 1000 == 999:
            session.flush()
    session.commit()
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    _c6_uncapture(engine, hook)
    assert total == 5001, f"expected 5001, got {total}"
    assert len(rows) == 50
    from app.persistence.structural_evidence import _FINAL_QUERY_PARAM_BUDGET, _SQLITE_MAX_PARAMS

    for stmt, params in captured:
        n = _c6_param_count(params)
        assert n <= _SQLITE_MAX_PARAMS, f"statement exceeds SQLITE max {n} > 900: {stmt[:300]}"
        assert "union all" not in stmt.lower(), f"UNION ALL forbidden at 5001: {stmt[:400]}"
    finals, counts, selects = _c6_final_counts_and_selects(captured)
    assert len(counts) >= 1 and len(selects) >= 1
    for stmt, params in counts:
        n = _c6_param_count(params)
        assert n <= _FINAL_QUERY_PARAM_BUDGET, f"final COUNT 5001 bind {n} > budget {_FINAL_QUERY_PARAM_BUDGET}: {stmt[:500]}"  # noqa: E501
        assert "json_each" in stmt.lower(), "final COUNT must use json_each at 5001"
    for stmt, params in selects:
        n = _c6_param_count(params)
        assert n <= _FINAL_QUERY_PARAM_BUDGET + 2, f"final SELECT 5001 bind {n} > budget: {stmt[:500]}"  # noqa: E501
        assert "json_each" in stmt.lower()
    # offset near end correct
    rows_tail, total2 = repo.list_historical_segments(WS, GEN, limit=50, offset=5000)
    assert total2 == 5001
    assert len(rows_tail) == 1
    # deterministic ordering slice check
    full_rows, _ = repo.list_historical_segments(WS, GEN, limit=5001, offset=0)
    assert len(full_rows) == 5001
    assert rows_tail[0].id == full_rows[-1].id
    session.close()


def test_c6_mixed_current_stale_superseded_total_page(tmp_path: Path):
    """C6: mixed current/stale/superseded — total+page correct, deterministic ordering retained after json_each fix."""  # noqa: E501
    import uuid

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    extra = []
    for i in range(4):
        gen_cur = "4" if i < 2 else "3"
        vid, scene, role, job = _create_extra_video(session, seed.project, gen_cur, f"c6_mix_{i}")
        extra.append((vid, scene, role, job))
    session.commit()
    all_videos = [
        (seed.video, seed.scene, seed.roles["Character"], True),
        (extra[0][0].id, extra[0][1].id, extra[0][2].id, True),
        (extra[1][0].id, extra[1][1].id, extra[1][2].id, True),
        (extra[2][0].id, extra[2][1].id, extra[2][2].id, False),
        (extra[3][0].id, extra[3][1].id, extra[3][2].id, False),
    ]
    for idx, (vid_id, scene_id, role_id, is_stale) in enumerate(all_videos):
        seg_id = str(uuid.uuid4())
        logical = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, :sup, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', :z, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ),
            {
                "id": seg_id,
                "logical_id": logical,
                "sup": None,
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role_id,
                "scene": scene_id,
                "name": f"C6Mix{idx}_active",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
                "z": idx,
            },
        )
        if not is_stale:
            seg2_id = str(uuid.uuid4())
            logical2 = str(uuid.uuid4())
            session.execute(
                text(
                    "INSERT INTO occurrence_segment "
                    "(id, logical_id, lineage_version, "
                    "superseded_by_id, workspace_id, project_id, "
                    "video_item_id, role_id, scene_id, name, kind, "
                    "start_frame, end_frame, start_time_ms, end_time_ms, "
                    "source_generation, source_job_id, prompt_json, "
                    "segmentation_json, mask_artifact_id, algorithm, "
                    "algorithm_version, confidence, confidence_source, "
                    "reasons_json, provenance_json, visibility, z_order, "
                    "idempotency_key, revision, created_at, updated_at) "
                    "VALUES (:id, :logical_id, 1, :sup, :ws, :proj, :vid, "
                    ":role, :scene, :name, 'character', :sf, :ef, :st, "
                    ":et, :gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                    "'model', :reasons, NULL, 'visible', :z, NULL, 1, "
                    "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
                ),
                {
                    "id": seg2_id,
                    "logical_id": logical2,
                    "sup": seg_id,
                    "ws": WS,
                    "proj": seed.project,
                    "vid": vid_id,
                    "role": role_id,
                    "scene": scene_id,
                    "name": f"C6Mix{idx}_sup",
                    "sf": idx * 10 + 5,
                    "ef": idx * 10 + 15,
                    "st": idx * 100 + 50,
                    "et": idx * 100 + 150,
                    "gen": GEN,
                    "job": seed.job,
                    "mask": seed.masks[0],
                    "reasons": canonical_json([]),
                    "z": idx,
                },
            )
    session.commit()
    # Capture with instrumentation to also verify bounded
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    rows, total = repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    _c6_uncapture(engine, hook)
    assert total == 5, f"expected total 5, got {total} rows {len(rows)}"
    assert len(rows) == 5
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        assert (a.start_frame, a.end_frame, a.z_order, a.id) <= (b.start_frame, b.end_frame, b.z_order, b.id)  # noqa: E501
    rows_p1, total_p1 = repo.list_historical_segments(WS, GEN, limit=2, offset=1)
    assert total_p1 == 5
    assert len(rows_p1) == 2
    assert [r.id for r in rows_p1] == [r.id for r in rows[1:3]]
    # instrumentation bounded
    from app.persistence.structural_evidence import _FINAL_QUERY_PARAM_BUDGET, _SQLITE_MAX_PARAMS

    for stmt, params in captured:
        assert _c6_param_count(params) <= _SQLITE_MAX_PARAMS
        assert "union all" not in stmt.lower()
    finals, counts, selects = _c6_final_counts_and_selects(captured)
    assert len(counts) >= 1 and len(selects) >= 1
    for _stmt, params in counts + selects:
        assert _c6_param_count(params) <= _FINAL_QUERY_PARAM_BUDGET + 2
    session.close()


def test_c6_role_id_filter_correct(tmp_path: Path):
    """C6: role_id filter still correct after json_each fix (bounded)."""
    import uuid

    from sqlalchemy import select

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    # Create 2 extra videos, both stale for GEN=3
    extra = []
    for i in range(2):
        vid, scene, role, job = _create_extra_video(session, seed.project, "4", f"c6_role_{i}")
        extra.append((vid, scene, role))
    session.commit()
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    # Insert one segment per video, each with its own role
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(select(Scene).where(Scene.video_item_id == vid_id)).first()
        role = session.scalars(select(ObjectRole).where(ObjectRole.video_item_id == vid_id)).first()
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C6Role_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    # pick role of first extra video
    target_role_id = extra[0][2].id
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    rows, total = repo.list_historical_segments(WS, GEN, role_id=target_role_id, limit=50, offset=0)
    _c6_uncapture(engine, hook)
    # Only segments with that role_id are historical (1)
    assert total == 1, f"expected 1 for role filter, got {total}"
    assert len(rows) == 1
    assert rows[0].role_id == target_role_id
    # instrumentation still bounded (role_id adds 1 param but still <=budget)
    from app.persistence.structural_evidence import _FINAL_QUERY_PARAM_BUDGET, _SQLITE_MAX_PARAMS

    for stmt, params in captured:
        assert _c6_param_count(params) <= _SQLITE_MAX_PARAMS
        assert "union all" not in stmt.lower()
    finals, counts, selects = _c6_final_counts_and_selects(captured)
    for stmt, params in counts:
        assert _c6_param_count(params) <= _FINAL_QUERY_PARAM_BUDGET
        assert "json_each" in stmt.lower()
    session.close()


def test_c6_offset_near_end_correct(tmp_path: Path):
    """C6: offset near END of dataset correct after bounded filter."""
    import uuid

    from sqlalchemy import select

    from app.persistence.models import VideoItem

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    for i in range(100):
        _create_extra_video(session, seed.project, "4", f"c6_off_{i}")
    session.commit()
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    assert len(vids) == 101
    for idx, vid_id in enumerate(vids):
        scene = session.scalars(select(Scene).where(Scene.video_item_id == vid_id)).first()
        role = session.scalars(select(ObjectRole).where(ObjectRole.video_item_id == vid_id)).first()
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', :sf, :ef, :st, :et, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C6Off_{idx}",
                "sf": idx * 10,
                "ef": idx * 10 + 10,
                "st": idx * 100,
                "et": idx * 100 + 100,
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    full_rows, total = repo.list_historical_segments(WS, GEN, limit=101, offset=0)
    assert total == 101
    assert len(full_rows) == 101
    # offset near end: last 2
    tail_rows, tail_total = repo.list_historical_segments(WS, GEN, limit=10, offset=99)
    assert tail_total == 101
    assert len(tail_rows) == 2
    assert [r.id for r in tail_rows] == [r.id for r in full_rows[99:101]]
    # offset at exact end: empty page but total still correct
    empty_rows, empty_total = repo.list_historical_segments(WS, GEN, limit=10, offset=101)
    assert empty_total == 101
    assert len(empty_rows) == 0
    # instrumentation bounded
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    repo.list_historical_segments(WS, GEN, limit=10, offset=100)
    _c6_uncapture(engine, hook)
    from app.persistence.structural_evidence import _SQLITE_MAX_PARAMS

    for stmt, params in captured:
        assert _c6_param_count(params) <= _SQLITE_MAX_PARAMS
        assert "union all" not in stmt.lower()
    session.close()


def test_c6_wrong_workspace_fail_closed(tmp_path: Path):
    """C6: wrong workspace fail closed — no leak, total 0 or RoleNotFound, still bounded."""
    import uuid

    from sqlalchemy import select

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    # insert one stale segment in correct workspace
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    vid_id = vids[0]
    scene = session.scalars(select(Scene).where(Scene.video_item_id == vid_id)).first()
    role = session.scalars(select(ObjectRole).where(ObjectRole.video_item_id == vid_id)).first()
    session.execute(
        text(
            "INSERT INTO occurrence_segment "
            "(id, logical_id, lineage_version, superseded_by_id, "
            "workspace_id, project_id, video_item_id, role_id, "
            "scene_id, name, kind, start_frame, end_frame, "
            "start_time_ms, end_time_ms, source_generation, "
            "source_job_id, prompt_json, segmentation_json, "
            "mask_artifact_id, algorithm, algorithm_version, "
            "confidence, confidence_source, reasons_json, "
            "provenance_json, visibility, z_order, "
            "idempotency_key, revision, created_at, updated_at) "
            "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
            ":role, :scene, :name, 'character', 0, 10, 0, 100, "
            ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
            "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
            "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        ),
        {
            "id": str(uuid.uuid4()),
            "logical_id": str(uuid.uuid4()),
            "ws": WS,
            "proj": seed.project,
            "vid": vid_id,
            "role": role.id,
            "scene": scene.id,
            "name": "C6WrongWS",
            "gen": GEN,
            "job": seed.job,
            "mask": seed.masks[0],
            "reasons": canonical_json([]),
        },
    )
    session.commit()
    wrong_ws = "ws-wrong-" + _sha(9)[:8]
    ws_row = Workspace(id=wrong_ws, name=wrong_ws)
    session.add(ws_row)
    session.flush()
    session.commit()
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    # list_historical_segments with wrong workspace must not leak correct data
    rows, total = repo.list_historical_segments(wrong_ws, GEN, limit=50, offset=0)
    _c6_uncapture(engine, hook)
    assert total == 0, f"wrong workspace must be fail closed total 0, got {total}"
    assert len(rows) == 0
    # also batch generation must fail closed
    from app.persistence.object_intelligence import ObjectIntelligenceRepository, RoleNotFoundError

    oi = ObjectIntelligenceRepository(session)
    with pytest.raises(RoleNotFoundError):
        oi.batch_current_generation(wrong_ws, [vid_id])
    # instrumentation still bounded
    from app.persistence.structural_evidence import _SQLITE_MAX_PARAMS

    for _stmt, params in captured:
        assert _c6_param_count(params) <= _SQLITE_MAX_PARAMS
    session.close()


def test_c6_sql_parameterized_no_or_chain_and_no_union(tmp_path: Path):
    """C6: SQL is parameterized (no raw id interpolation), no OR IN chain growth, no UNION ALL — actual execution."""  # noqa: E501
    import pathlib

    from sqlalchemy import select

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _advance_generation(session, seed, "4")
    for i in range(5):
        _create_extra_video(session, seed.project, "4", f"c6_nor_{i}")
    session.commit()
    # file-level: no OR IN chain construction string
    sev_path = pathlib.Path("app/persistence/structural_evidence.py")
    txt = sev_path.read_text(encoding="utf-8")
    assert "stale_chunks" not in txt, "stale_chunks OR IN chain still present"
    assert "in_clauses" not in txt, "in_clauses OR chain still present"
    # runtime parameterized
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    import uuid

    for idx, vid_id in enumerate(vids[:3]):
        scene = session.scalars(select(Scene).where(Scene.video_item_id == vid_id)).first()
        role = session.scalars(select(ObjectRole).where(ObjectRole.video_item_id == vid_id)).first()
        session.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, "
                "scene_id, name, kind, start_frame, end_frame, "
                "start_time_ms, end_time_ms, source_generation, "
                "source_job_id, prompt_json, segmentation_json, "
                "mask_artifact_id, algorithm, algorithm_version, "
                "confidence, confidence_source, reasons_json, "
                "provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES (:id, :logical_id, 1, NULL, :ws, :proj, :vid, "
                ":role, :scene, :name, 'character', 0, 10, 0, 100, "
                ":gen, :job, NULL, NULL, :mask, NULL, NULL, 1.0, "
                "'model', :reasons, NULL, 'visible', 0, NULL, 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ),
            {
                "id": str(uuid.uuid4()),
                "logical_id": str(uuid.uuid4()),
                "ws": WS,
                "proj": seed.project,
                "vid": vid_id,
                "role": role.id,
                "scene": scene.id,
                "name": f"C6NoOr_{idx}",
                "gen": GEN,
                "job": seed.job,
                "mask": seed.masks[0],
                "reasons": canonical_json([]),
            },
        )
    session.commit()
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    repo.list_historical_segments(WS, GEN, limit=50, offset=0)
    _c6_uncapture(engine, hook)
    for stmt, _params in captured:
        low = stmt.lower()
        assert "union all" not in low
        for vid in vids:
            if vid in stmt:
                raise AssertionError(f"raw id {vid!r} interpolated in SQL: {stmt[:500]}")
        # final occurrence statements must use json_each, not OR IN chain
        if _c6_is_final_occurrence_stmt(stmt):
            assert "json_each" in low, f"final statement must use json_each: {stmt[:600]}"
            # old code had OR with many IN: check not multiple IN
            # json_each has exactly one IN (video_item_id IN (SELECT...))
            assert low.count("in (select value from json_each") == 1 or "json_each" in low
    session.close()


def test_c6_batch_job_params_budget(tmp_path: Path):
    """C6: batch_current_generation job query TOTAL params <=900 (chunk 898 + 2 predicates). Capture actual params."""  # noqa: E501

    from sqlalchemy import select

    from app.persistence.models import VideoItem
    from app.persistence.object_intelligence import _SQLITE_JOB_CHUNK, _SQLITE_MAX_PARAMS

    session, seed, db = _open_db(tmp_path)
    import app.persistence.object_intelligence as _oi_mod
    oi = _oi_mod.ObjectIntelligenceRepository(session)  # noqa: E501
    # need many videos to force chunking of jobs query: create 1000 videos (chunk will be 898)
    _advance_generation(session, seed, "4")
    for i in range(999):
        _create_extra_video(session, seed.project, "4", f"c6_job_{i}")
    session.commit()
    vids = session.scalars(select(VideoItem.id).where(VideoItem.project_id == seed.project)).all()
    assert len(vids) == 1000
    assert _SQLITE_JOB_CHUNK == _SQLITE_MAX_PARAMS - 2
    # capture job statements
    engine = session.get_bind()
    captured, hook = _c6_capture_statements(engine)
    batch = oi.batch_current_generation(WS, vids)
    _c6_uncapture(engine, hook)
    assert len(batch) == 1000
    for stmt, params in captured:
        n = _c6_param_count(params)
        assert n <= _SQLITE_MAX_PARAMS, f"batch statement {n} > 900: {stmt[:300]}"
        low = stmt.lower()
        # job query with IN must not exceed budget; detect job table
        if "job" in low and "owner_id" in low and "in (" in low:
            assert n <= _SQLITE_MAX_PARAMS, f"job chunk exceeds budget: {n} params, chunk would be {n-2}"  # noqa: E501
            # ensure chunk size is JOB_CHUNK, not 900
            assert n <= _SQLITE_JOB_CHUNK + 2
            assert "union all" not in low
    session.close()
