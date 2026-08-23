"""S08-A02-T01-R1-C1 — Generation, Idempotency and Temporal Integrity tests.

Dedicated C1 semantic-safety suite.  Each C1 finding is closed by tests that
FAIL on the R1 (Codex CHANGES_REQUESTED) behavior and PASS on the corrected
repository:

- C1-F1 Generation semantics: two explicit workflows — (A) manual/user
  correction IN the current source generation (successor keeps the SAME
  generation, must carry user/manual confidence_source) and (B) re-analysis
  TRANSITION to the backend current generation (producing COMPLETED
  DISCOVER_OBJECTS job required, owner/generation/source-SHA validated).
  Arbitrary future/stale generations FAIL CLOSED.
- C1-F2 Logical identity + branch safety: the repository owns ``logical_id``
  (callers cannot attach one); an explicit ``lineage_version`` with
  UNIQUE(workspace_id, logical_id, lineage_version); no branching; concurrent
  supersede has exactly one winner; cycle/dangling/duplicate-predecessor fail
  closed; current version explicitly determinable.
- C1-F3 Complete idempotency: motion/occlusion/contact equivalence compares
  the FULL identity (segment/type/frame, endpoints, kind) AND payload; same
  key + ANY differing field = stable conflict, zero mutation; empty and
  over-length keys rejected pre-flush.
- C1-F4 Frame AND time containment: child ranges within the segment in BOTH
  dimensions; contact/occlusion within BOTH endpoints; updates rejected too.
- C1-F5 Ownership/artifact: mask = same workspace + kind=image + state=ready;
  model/detector evidence REQUIRES a matching COMPLETED DISCOVER_OBJECTS job;
  segment kind must match the ObjectRole taxonomy (create AND update).
- C1-F6 Domain validation before flush: algorithm lengths, idempotency key
  length, reasons list[str], provenance object, prompt points/boxes shape,
  non-empty labels, box w/h, NaN/Infinity, malformed JSON fail closed; only
  REAL idempotency conflicts are translated, never a blanket IntegrityError.
- C1-F7 Durable delete policy: object_role -> occurrence_segment and
  occurrence_segment -> segment_motion are RESTRICT — a referenced role or
  segment cannot be deleted; failed deletes leave rows byte-identical and
  PRAGMA foreign_key_check empty.

Runs on fresh isolated temp DBs only (never MAIN / user DBs), with real
SQLite FK / CHECK / partial-unique-index enforcement.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    ContactConflictError,
    MalformedJsonError,
    MotionConflictError,
    OcclusionConflictError,
    OwnershipMismatchError,
    SegmentConflictError,
    StructuralEvidenceRepository,
    canonical_json,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
WS = DEFAULT_WORKSPACE_ID
WS2 = "c1-ws2"
GEN = "3"


def _alembic_config(path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return cfg


def _sha(n: int) -> str:
    return f"{n:064x}"


class Seed:
    """Handles for the isolated C1 test graph."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.project = ""
        self.video = ""
        self.scene = ""
        self.roles: dict[str, str] = {}
        self.role_rows: dict[str, ObjectRole] = {}
        self.masks: list[str] = []
        self.job = ""
        self.other_artifact = ""
        self.video_mask = ""
        self.staging_mask = ""
        self.bad_sha_job = ""


def _seed(session: Session) -> Seed:
    """Backend-authoritative current generation \"3\" for the main video."""
    seed = Seed(session)
    workspace = Workspace(id=WS, name=WS)
    session.add(workspace)
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

    project = Project(workspace_id=WS, name="C1")
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

    # A COMPLETED DISCOVER_OBJECTS job of this video at the right generation
    # but with a manifest source SHA that does NOT match the video's current
    # source artifact (C1-F5 wrong-source-SHA rejection).
    bad_sha_job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video.id,
        state="completed",
        input_generation=GEN,
        input_manifest_json=canonical_json({"source_sha256": _sha(99)}),
    )
    session.add(bad_sha_job)
    session.flush()

    scene = Scene(
        video_item_id=video.id,
        position=0,
        start_frame=0,
        end_frame=180,
        start_time_ms=0,
        end_time_ms=6000,
        status="pending",
    )
    session.add(scene)
    session.flush()

    for name, kind in [
        ("Character", "character"),
        ("Phone", "prop"),
        ("Hand", "prop"),
        ("Face", "character"),
    ]:
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

    for i in range(6):
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

    # Non-image and non-ready artifacts for C1-F5 mask rejection.
    video_mask = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path="notamask.mp4",
        state="ready",
        sha256=_sha(50),
    )
    session.add(video_mask)
    session.flush()
    staging_mask = Artifact(
        workspace_id=WS,
        kind="image",
        relative_path="staging.png",
        state="staging",
        sha256=_sha(51),
    )
    session.add(staging_mask)
    session.flush()

    workspace2 = Workspace(id=WS2, name=WS2)
    session.add(workspace2)
    session.flush()
    other_artifact = Artifact(
        workspace_id=WS2,
        kind="image",
        relative_path="other.png",
        state="ready",
        sha256=_sha(60),
    )
    session.add(other_artifact)
    session.flush()

    seed.project = project.id
    seed.video = video.id
    seed.scene = scene.id
    seed.job = job.id
    seed.bad_sha_job = bad_sha_job.id
    seed.video_mask = video_mask.id
    seed.staging_mask = staging_mask.id
    seed.other_artifact = other_artifact.id
    session.commit()
    return seed


def _open_db(tmp_path: Path) -> tuple[Session, Seed, Path]:
    db = tmp_path / "c1.db"
    comm = _alembic_config(db)
    command.upgrade(comm, "head")
    factory = create_session_factory(create_engine_for_path(db))
    session = factory()
    seed = _seed(session)
    return session, seed, db


def _count(table: str, db: Path) -> int:
    with create_engine_for_path(db).connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar())


def _count_segments(session: Session, db: Path) -> int:
    session.rollback()
    return _count("occurrence_segment", db)


def _segment_rows(db: Path, where: str = "1=1") -> list[tuple]:
    with create_engine_for_path(db).connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(f"SELECT * FROM occurrence_segment WHERE {where}")
            ).fetchall()
        ]


def _motion_rows(db: Path) -> list[tuple]:
    with create_engine_for_path(db).connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT * FROM segment_motion")).fetchall()]


def _prompt() -> dict:
    return {
        "points": [{"x": 10.0, "y": 20.0, "label": "center"}],
        "boxes": [{"x": 1.0, "y": 2.0, "w": 30.0, "h": 30.0}],
    }


_AUTO_JOB = object()  # sentinel: use the seed's producing job by default


def _seg(
    repo: StructuralEvidenceRepository,
    seed: Seed,
    name: str = "Character",
    *,
    role: str | None = None,
    gen: str = GEN,
    job: object = _AUTO_JOB,
    mask: str | None = None,
    prompt: dict | None = None,
    frame: tuple[int, int] = (0, 180),
    time: tuple[int, int] = (0, 6000),
    idem: str | None = None,
    **kw,
) -> tuple:
    # C1-F5: segment kind is inherited from the ObjectRole taxonomy.
    role_id = role or seed.roles["Character"]
    role_row = seed.session.get(ObjectRole, role_id)
    kind = kw.pop("kind", role_row.kind)
    source_job_id: str | None = seed.job if job is _AUTO_JOB else job  # type: ignore[assignment]
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
        prompt=prompt,
        idempotency_key=idem,
        **kw,
    )


def _advance_generation(session: Session, seed: Seed, new_gen: str) -> str:
    """Advance the backend current generation to ``new_gen`` via REAL
    ObjectIntelligenceRepository.create_role (C2-F1: never mutate
    ObjectRole.source_generation directly)."""
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
        # create new role for this generation
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


def _new_role_for_gen(seed: Seed, base_name: str, new_gen: str) -> str:
    key = f"{base_name}_g{new_gen}"
    if key not in seed.roles:
        raise KeyError(f"no role for {key!r}")
    return seed.roles[key]


# ══════════════════════════════════════════════════════════════════════════
# C1-F1 — Generation semantics
# ══════════════════════════════════════════════════════════════════════════


def test_c1f1_manual_correction_same_generation_succeeds_and_keeps_current(
    tmp_path: Path,
) -> None:
    """Workflow A: a manual/user correction creates a successor in the SAME
    current generation (R1 forced an arbitrary generation advance instead)."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", job=seed.job, gen=GEN, mask=seed.masks[0])
    session.commit()

    prior, successor = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        mask_artifact_id=seed.masks[1],
        reasons=["user correction"],
        provenance={"who": "human"},
    )
    session.commit()

    # Same generation, same lineage, new version/record id.
    assert successor.source_generation == seg.source_generation == GEN
    assert successor.logical_id == prior.logical_id
    assert successor.id != prior.id
    assert successor.lineage_version == prior.lineage_version + 1
    # Manual provenance: confidence_source MUST be user/manual, never model.
    assert successor.confidence_source == "user"
    assert successor.reasons == ["user correction"]
    assert successor.provenance == {"who": "human"}

    # Predecessor is historical/read-only.
    with pytest.raises(SegmentConflictError, match="superseded"):
        repo.update_segment(WS, prior.id, prior.revision, name="nope")
    session.rollback()

    # Successor is STILL current and updatable.
    updated = repo.update_segment(WS, successor.id, successor.revision, confidence=0.91)
    session.commit()
    assert updated.id == successor.id and updated.confidence == 0.91
    assert repo.current_segment_by_logical_id(WS, seg.logical_id).id == successor.id
    assert _count_segments(session, db) == 2
    session.close()


def test_c1f1_manual_correction_refuses_silent_machine_provenance(
    tmp_path: Path,
) -> None:
    """Workflow A MUST NOT silently inherit model/detector provenance."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    with pytest.raises(SegmentConflictError, match="user/manual"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation=GEN,
            mask_artifact_id=seed.masks[1],  # no confidence_source -> inherits model
        )
    session.rollback()
    assert _count_segments(session, db) == 1
    session.close()


def test_c1f1_arbitrary_future_generation_rejected(tmp_path: Path) -> None:
    """Public create MUST fail closed on a future generation (R1 accepted
    arbitrary generations)."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(SegmentConflictError, match="arbitrary future/stale"):
        _seg(repo, seed, "Character", gen="99", mask=seed.masks[0])
    assert _count_segments(session, db) == 0
    # A stale generation is rejected the same way.
    with pytest.raises(SegmentConflictError, match="arbitrary future/stale"):
        _seg(repo, seed, "Character", gen="2", mask=seed.masks[0])
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f1_reanalysis_transition_to_true_current_generation_succeeds(
    tmp_path: Path,
) -> None:
    """Workflow B: transition to the REAL backend current generation with a
    producing job succeeds; the successor becomes current/mutable."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()

    job4 = _advance_generation(session, seed, "4")
    authority = ObjectIntelligenceRepository(session)
    assert authority.current_generation(WS, seed.video) == "4"

    prior, successor = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation="4",
        source_job_id=job4,
        target_role_id=_new_role_for_gen(seed, "Character", "4"),
        mask_artifact_id=seed.masks[1],
        confidence_source="model",
    )
    session.commit()
    assert successor.source_generation == "4"
    assert successor.source_job_id == job4
    assert successor.logical_id == prior.logical_id
    assert prior.superseded_by_id == successor.id
    assert successor.lineage_version == 2
    # Successor is current and mutable.
    assert repo.current_segment_by_logical_id(WS, seg.logical_id).id == successor.id
    updated = repo.update_segment(WS, successor.id, successor.revision, confidence=0.8)
    session.commit()
    assert updated.confidence == 0.8
    session.close()


def test_c1f1_transition_to_wrong_future_or_stale_generation_rejected(
    tmp_path: Path,
) -> None:
    """Workflow B target generation MUST equal the backend current generation."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    _advance_generation(session, seed, "4")

    # Target generation "5" is a FUTURE generation vs current "4".
    with pytest.raises(SegmentConflictError, match="arbitrary future/stale"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="5",
            source_job_id=seed.job,
            confidence_source="model",
        )
    session.rollback()
    # Target generation "2" is STALE.
    with pytest.raises(SegmentConflictError, match="arbitrary future/stale"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="2",
            source_job_id=seed.job,
            confidence_source="model",
        )
    session.rollback()
    assert _count_segments(session, db) == 1
    session.close()


def test_c1f1_missing_job_rejected(tmp_path: Path) -> None:
    """Model/detector ROOT evidence without a producing job must be rejected."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="missing model job"):
        _seg(repo, seed, "Character", job=None, mask=seed.masks[0])
    assert _count_segments(session, db) == 0
    # Manual evidence is allowed without a job.
    rec, _ = _seg(
        repo,
        seed,
        "Character",
        job=None,
        mask=seed.masks[0],
        confidence_source="user",
    )
    session.commit()
    assert rec.confidence_source == "user" and rec.source_job_id is None
    session.close()


def test_c1f1_reanalysis_transition_requires_producing_job(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    _advance_generation(session, seed, "4")
    with pytest.raises(ValueError, match="source_job_id"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="4",
            target_role_id=_new_role_for_gen(seed, "Character", "4"),
            confidence_source="model",
        )
    session.rollback()
    assert _count_segments(session, db) == 1
    session.close()


def test_c1f1_role_generation_mismatch_rejected(tmp_path: Path) -> None:
    """A segment's root create must not bind a role of an incompatible
    generation."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    stale_role = ObjectRole(
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=seed.video,
        source_generation="2",
        name="StaleRole",
        kind="character",
        status="confirmed",
    )
    session.add(stale_role)
    session.commit()
    with pytest.raises(OwnershipMismatchError, match="role generation"):
        _seg(repo, seed, "Character", role=stale_role.id, gen=GEN)
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f1_failure_leaves_zero_mutation(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    before = _segment_rows(db)
    with pytest.raises(SegmentConflictError):
        _seg(repo, seed, "Character", gen="77")
    session.rollback()
    with pytest.raises(SegmentConflictError, match="user/manual"):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation=GEN,
            confidence_source="model",
        )
    session.rollback()
    assert _segment_rows(db) == before
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# C1-F2 — Logical identity and branch safety
# ══════════════════════════════════════════════════════════════════════════


def test_c1f2_caller_cannot_attach_arbitrary_logical_id(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="logical_id"):
        _seg(repo, seed, "Character", logical_id="id-from-caller")
    assert _count_segments(session, db) == 0
    # Repository-generated logical ids are valid opaque 36-char ids.
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    assert len(seg.logical_id) == 36 and seg.lineage_version == 1
    session.close()


def test_c1f2_logical_id_workspace_scoped_per_contract(tmp_path: Path) -> None:
    """The same logical_id in a DIFFERENT workspace coexists (workspace
    scope); reuse within the SAME workspace is rejected by the unique index."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()

    # Cross-video/role reuse within the SAME workspace + same lineage version
    # is rejected by UNIQUE(workspace_id, logical_id, lineage_version).
    other_video = VideoItem(project_id=seed.project, title="V2", position=9)
    session.add(other_video)
    session.flush()
    scene2 = Scene(
        video_item_id=other_video.id,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    role2 = ObjectRole(
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=other_video.id,
        source_generation="1",
        name="Other",
        kind="prop",
        status="confirmed",
    )
    session.add_all([scene2, role2])
    session.commit()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            OccurrenceSegment(
                logical_id=seg.logical_id,
                lineage_version=1,
                workspace_id=WS,
                project_id=seed.project,
                video_item_id=other_video.id,
                role_id=role2.id,
                scene_id=scene2.id,
                name="X",
                kind="prop",
                start_frame=0,
                end_frame=10,
                start_time_ms=0,
                end_time_ms=1000,
                source_generation="1",
                confidence=1.0,
                confidence_source="user",
            )
        )
        session.flush()
    session.rollback()

    # The same logical_id in ANOTHER workspace is an independent lineage
    # (workspace-scoped per contract).  ws2 already exists in the seed.
    p2 = Project(workspace_id=WS2, name="P2")
    session.add(p2)
    session.flush()
    v2 = VideoItem(project_id=p2.id, title="V", position=0)
    session.add(v2)
    session.flush()
    s2 = Scene(
        video_item_id=v2.id,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    r2 = ObjectRole(
        workspace_id=WS2,
        project_id=p2.id,
        video_item_id=v2.id,
        source_generation="1",
        name="Char2",
        kind="character",
        status="confirmed",
    )
    session.add_all([s2, r2])
    session.commit()
    with session.begin_nested():
        session.add(
            OccurrenceSegment(
                logical_id=seg.logical_id,
                lineage_version=1,
                workspace_id=WS2,
                project_id=p2.id,
                video_item_id=v2.id,
                role_id=r2.id,
                scene_id=s2.id,
                name="Char2",
                kind="character",
                start_frame=0,
                end_frame=10,
                start_time_ms=0,
                end_time_ms=1000,
                source_generation="1",
                confidence=1.0,
                confidence_source="user",
            )
        )
        session.flush()
    session.commit()
    assert repo.get_segment_by_logical_id(WS, seg.logical_id)
    assert repo.get_segment_by_logical_id(WS2, seg.logical_id)
    session.close()


def test_c1f2_concurrent_supersede_single_winner(tmp_path: Path) -> None:
    db = tmp_path / "concurrent-super.db"
    comm = _alembic_config(db)
    command.upgrade(comm, "head")
    master = create_session_factory(create_engine_for_path(db))()
    seed = _seed(master)
    repo = StructuralEvidenceRepository(master)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    master.commit()
    seg_id, rev = seg.id, seg.revision
    logical = seg.logical_id
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
                mask_artifact_id=seed.masks[1],
                provenance={"who": "human"},
                reasons=["concurrent"],
            )
            s.commit()
            outcomes.append("ok:" + succ.id)
        except Exception as exc:  # noqa: BLE001 — test harness
            s.rollback()
            outcomes.append(type(exc).__name__)
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)

    with create_engine_for_path(db).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, lineage_version, superseded_by_id "
                "FROM occurrence_segment WHERE logical_id = :lid ORDER BY lineage_version"
            ),
            {"lid": logical},
        ).all()
    assert len(rows) == 2, f"concurrent supersede created extra rows: {outcomes}"
    assert rows[0][1] == 1 and rows[0][2] == rows[1][0]  # prior -> sole successor
    assert rows[1][1] == 2 and rows[1][2] is None  # successor active
    assert sum(1 for o in outcomes if o.startswith("ok:")) == 1
    session = create_session_factory(create_engine_for_path(db))()
    assert _count_segments(session, db) == 2
    session.close()


def test_c1f2_branch_attempt_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    prior, _ = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        mask_artifact_id=seed.masks[1],
        provenance={"who": "human"},
        reasons=["human fix"],
    )
    session.commit()
    # A second supersede of the SAME (now superseded) predecessor fails closed.
    with pytest.raises(SegmentConflictError, match="superseded"):
        repo.supersede_segment(
            WS,
            prior.id,
            prior.revision,
            source_generation=GEN,
            confidence_source="user",
            mask_artifact_id=seed.masks[2],
            provenance={"who": "human"},
            reasons=["again"],
        )
    session.rollback()
    with create_engine_for_path(db).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT lineage_version, superseded_by_id "
                "FROM occurrence_segment WHERE logical_id = :lid"
            ),
            {"lid": seg.logical_id},
        ).all()
    assert len([r for r in rows if r[1] is None and r[0] == 2]) == 1
    session.close()


def test_c1f2_lineage_from_any_version_oldest_to_newest(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()

    job4 = _advance_generation(session, seed, "4")
    p1, v2 = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation="4",
        source_job_id=job4,
        target_role_id=_new_role_for_gen(seed, "Character", "4"),
        confidence_source="model",
        mask_artifact_id=seed.masks[1],
    )
    session.commit()
    job5 = _advance_generation(session, seed, "5")
    p2, v3 = repo.supersede_segment(
        WS,
        v2.id,
        v2.revision,
        source_generation="5",
        source_job_id=job5,
        target_role_id=_new_role_for_gen(seed, "Character", "5"),
        confidence_source="model",
        mask_artifact_id=seed.masks[2],
    )
    session.commit()

    expected = [p1.id, p2.id, v3.id]
    for probe in (p1.id, p2.id, v3.id):
        chain = repo.segment_lineage(WS, probe)
        assert [c.id for c in chain] == expected
        assert [c.lineage_version for c in chain] == [1, 2, 3]
    by_logical = repo.get_segment_by_logical_id(WS, seg.logical_id)
    assert [r.lineage_version for r in by_logical] == [1, 2, 3]
    assert repo.current_segment_by_logical_id(WS, seg.logical_id).id == v3.id
    session.close()


def test_c1f2_cycle_dangling_duplicate_predecessor_fail_closed(
    tmp_path: Path,
) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    first, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()

    # Cycle: fabricate two rows pointing at each other.
    with session.begin_nested():
        a = session.get(OccurrenceSegment, first.id)
        b = OccurrenceSegment(
            logical_id="cycle-b",
            lineage_version=1,
            workspace_id=WS,
            project_id=seed.project,
            video_item_id=seed.video,
            role_id=seed.roles["Character"],
            scene_id=seed.scene,
            name="B",
            kind="character",
            start_frame=1,
            end_frame=2,
            start_time_ms=1,
            end_time_ms=2,
            source_generation=GEN,
            confidence=1.0,
            confidence_source="user",
        )
        session.add(b)
        session.flush()
        a.superseded_by_id = b.id
        b.superseded_by_id = a.id
    session.commit()
    with pytest.raises(SegmentConflictError, match="cycle"):
        repo.segment_lineage(WS, first.id)
    session.rollback()

    # Dangling forward link: point the root at a missing successor.
    with create_engine_for_path(db).begin() as conn:
        pass
    with create_engine_for_path(db).connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text("UPDATE occurrence_segment SET superseded_by_id='missing-x' WHERE id=:i"),
            {"i": first.id},
        )
        conn.commit()
    with pytest.raises(SegmentConflictError, match="dangling"):
        repo.segment_lineage(WS, first.id)
    session.rollback()
    # Clean dangling state before next phase (restore first.id to NULL so FK check passes at end)
    with create_engine_for_path(db).connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text("UPDATE occurrence_segment SET superseded_by_id=NULL WHERE id=:i"), {"i": first.id}
        )
        conn.commit()

    # Duplicate predecessor: two rows B1/B2 both claim the SAME successor — C2-F4 DB-enforced.
    # The DB must REFUSE the second predecessor at INSERT time (UNIQUE on superseded_by_id),
    # not silently store it for the walker to detect later.
    with create_engine_for_path(db).connect() as conn:
        conn.execute(
            text(
                "INSERT INTO occurrence_segment("
                "id,logical_id,lineage_version,workspace_id,project_id,"
                "video_item_id,role_id,scene_id,name,kind,start_frame,end_frame,"
                "start_time_ms,end_time_ms,source_generation,confidence,"
                "confidence_source,reasons_json,visibility,z_order,revision,"
                "superseded_by_id) VALUES ("
                "'c1-root','dup-root',1,'default',:p,:v,:r,:s,'Root',"
                "'character',1,2,1,2,'3',1.0,'user','[]','visible',0,1,NULL)"
            ),
            {"p": seed.project, "v": seed.video, "r": seed.roles["Character"], "s": seed.scene},
        )
        conn.execute(
            text(
                "INSERT INTO occurrence_segment("
                "id,logical_id,lineage_version,workspace_id,project_id,"
                "video_item_id,role_id,scene_id,name,kind,start_frame,end_frame,"
                "start_time_ms,end_time_ms,source_generation,confidence,"
                "confidence_source,reasons_json,visibility,z_order,revision,"
                "superseded_by_id) VALUES ("
                "'c1-b1','dup-b',1,'default',:p,:v,:r,:s,'B1','character',1,2,1,2,"
                "'3',1.0,'user','[]','visible',0,1,'c1-root')"
            ),
            {"p": seed.project, "v": seed.video, "r": seed.roles["Character"], "s": seed.scene},
        )
        conn.commit()
        # Second predecessor with same successor must be DB-rejected (C2-F4)
        with pytest.raises(
            Exception, match="UNIQUE constraint failed.*superseded_by_id|IntegrityError"
        ):
            conn.execute(
                text(
                    "INSERT INTO occurrence_segment("
                    "id,logical_id,lineage_version,workspace_id,project_id,"
                    "video_item_id,role_id,scene_id,name,kind,start_frame,end_frame,"
                    "start_time_ms,end_time_ms,source_generation,confidence,"
                    "confidence_source,reasons_json,visibility,z_order,revision,"
                    "superseded_by_id) VALUES ("
                    "'c1-b2','dup-b',2,'default',:p,:v,:r,:s,'B2','character',1,2,1,2,"
                    "'3',1.0,'user','[]','visible',0,1,'c1-root')"
                ),
                {"p": seed.project, "v": seed.video, "r": seed.roles["Character"], "s": seed.scene},
            )
            conn.commit()
    # Walker still detects the single predecessor correctly; no branch stored.
    chain = repo.segment_lineage(WS, "c1-root")
    assert len(chain) == 2
    assert chain[0].id == "c1-b1" and chain[1].id == "c1-root"
    # Also verify DB integrity still ok after refused insert
    with create_engine_for_path(db).connect() as conn2:
        assert conn2.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert list(conn2.execute(text("PRAGMA foreign_key_check"))) == []
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# C1-F3 — Complete idempotency (identity-aware equivalence)
# ══════════════════════════════════════════════════════════════════════════


def _two_segments(repo: StructuralEvidenceRepository, seed: Seed) -> tuple:
    a, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    b, _ = _seg(repo, seed, "Phone", role=seed.roles["Phone"], mask=seed.masks[1])
    return a.id, b.id


def test_c1f3_motion_different_segment_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    session.commit()
    key = "motion-key"
    repo.create_motion(
        WS,
        a_id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=2,
        start_time_ms=0,
        end_time_ms=100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(MotionConflictError):
        repo.create_motion(
            WS,
            b_id,
            "camera_relative",
            {"tx": 1.0},
            start_frame=0,
            end_frame=2,
            start_time_ms=0,
            end_time_ms=100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("segment_motion", db) == 1
    session.close()


def test_c1f3_motion_different_transform_type_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, _ = _two_segments(repo, seed)
    session.commit()
    key = "motion-key2"
    repo.create_motion(
        WS,
        a_id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=2,
        start_time_ms=0,
        end_time_ms=100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(MotionConflictError):
        repo.create_motion(
            WS,
            a_id,
            "object_relative",
            {"tx": 1.0},
            start_frame=0,
            end_frame=2,
            start_time_ms=0,
            end_time_ms=100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("segment_motion", db) == 1
    session.close()


def test_c1f3_motion_different_start_frame_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, _ = _two_segments(repo, seed)
    session.commit()
    key = "motion-key3"
    repo.create_motion(
        WS,
        a_id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=2,
        start_time_ms=0,
        end_time_ms=100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(MotionConflictError):
        repo.create_motion(
            WS,
            a_id,
            "camera_relative",
            {"tx": 1.0},
            start_frame=1,
            end_frame=2,
            start_time_ms=0,
            end_time_ms=100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("segment_motion", db) == 1
    session.close()


def test_c1f3_occlusion_reversed_endpoints_conflict(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    session.commit()
    key = "occ-key"
    repo.create_occlusion(
        WS,
        seed.project,
        seed.video,
        a_id,
        b_id,
        0,
        2,
        0,
        100,
        idempotency_key=key,
    )
    session.commit()
    # Reversed endpoints = a DIFFERENT identity -> conflict, not replay.
    with pytest.raises(OcclusionConflictError):
        repo.create_occlusion(
            WS,
            seed.project,
            seed.video,
            b_id,
            a_id,
            0,
            2,
            0,
            100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("scene_graph_occlusion", db) == 1
    session.close()


def test_c1f3_occlusion_different_start_frame_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    session.commit()
    key = "occ-key2"
    repo.create_occlusion(
        WS,
        seed.project,
        seed.video,
        a_id,
        b_id,
        0,
        2,
        0,
        100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(OcclusionConflictError):
        repo.create_occlusion(
            WS,
            seed.project,
            seed.video,
            a_id,
            b_id,
            1,
            2,
            0,
            100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("scene_graph_occlusion", db) == 1
    session.close()


def test_c1f3_contact_different_endpoint_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    hand, _ = _seg(repo, seed, "Hand", role=seed.roles["Hand"], mask=seed.masks[2])
    session.commit()
    key = "con-key"
    repo.create_contact(
        WS,
        seed.project,
        seed.video,
        a_id,
        b_id,
        "character_phone",
        0,
        2,
        0,
        100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(ContactConflictError):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            a_id,
            hand.id,
            "character_phone",
            0,
            2,
            0,
            100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("scene_graph_contact", db) == 1
    session.close()


def test_c1f3_contact_different_kind_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    session.commit()
    key = "con-key2"
    repo.create_contact(
        WS,
        seed.project,
        seed.video,
        a_id,
        b_id,
        "character_phone",
        0,
        2,
        0,
        100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(ContactConflictError):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            a_id,
            b_id,
            "touch",
            0,
            2,
            0,
            100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("scene_graph_contact", db) == 1
    session.close()


def test_c1f3_contact_different_start_frame_conflicts(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    session.commit()
    key = "con-key3"
    repo.create_contact(
        WS,
        seed.project,
        seed.video,
        a_id,
        b_id,
        "character_phone",
        0,
        2,
        0,
        100,
        idempotency_key=key,
    )
    session.commit()
    with pytest.raises(ContactConflictError):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            a_id,
            b_id,
            "character_phone",
            1,
            2,
            0,
            100,
            idempotency_key=key,
        )
    session.rollback()
    assert _count("scene_graph_contact", db) == 1
    session.close()


def test_c1f3_same_key_exact_replay_is_idempotent(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, _ = _two_segments(repo, seed)
    session.commit()
    key = "replay-key"
    m1, created1 = repo.create_motion(
        WS,
        a_id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=2,
        start_time_ms=0,
        end_time_ms=100,
        idempotency_key=key,
    )
    session.commit()
    m2, created2 = repo.create_motion(
        WS,
        a_id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=2,
        start_time_ms=0,
        end_time_ms=100,
        idempotency_key=key,
    )
    session.commit()
    assert created1 and not created2 and m1.id == m2.id
    assert _count("segment_motion", db) == 1
    session.close()


def test_c1f3_concurrent_exact_replay_creates_one_row(tmp_path: Path) -> None:
    db = tmp_path / "concurrent-replay.db"
    comm = _alembic_config(db)
    command.upgrade(comm, "head")
    master = create_session_factory(create_engine_for_path(db))()
    seed = _seed(master)
    repo = StructuralEvidenceRepository(master)
    a_id, _ = _two_segments(repo, seed)
    master.commit()
    master.close()

    key = "concurrent-replay-key"
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def worker() -> None:
        s = create_session_factory(create_engine_for_path(db))()
        try:
            r = StructuralEvidenceRepository(s)
            barrier.wait(timeout=30)
            _, created = r.create_motion(
                WS,
                a_id,
                "camera_relative",
                {"tx": 1.0},
                start_frame=0,
                end_frame=2,
                start_time_ms=0,
                end_time_ms=100,
                idempotency_key=key,
            )
            s.commit()
            outcomes.append("created" if created else "replayed")
        except Exception as exc:  # noqa: BLE001 — test harness
            s.rollback()
            outcomes.append(type(exc).__name__)
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert _count("segment_motion", db) == 1
    assert outcomes.count("created") == 1
    session = create_session_factory(create_engine_for_path(db))()
    session.close()


def test_c1f3_empty_idempotency_key_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="must not be empty"):
        _seg(repo, seed, "Character", idem="   ")
    with pytest.raises(ValueError, match="must not be empty"):
        _seg(repo, seed, "Character", idem="")
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f3_overlength_idempotency_key_rejected_before_flush(
    tmp_path: Path,
) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="at most 255 chars"):
        _seg(repo, seed, "Character", idem="k" * 256)
    assert _count_segments(session, db) == 0
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# C1-F4 — Frame AND time containment
# ══════════════════════════════════════════════════════════════════════════


def test_c1f4_valid_frame_but_time_outside_segment_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], frame=(0, 100), time=(0, 5000))
    session.commit()
    # frames inside (0..100) but time ms exceeds the segment's 5000 -> reject.
    with pytest.raises(ValueError, match="within the segment range"):
        repo.create_motion(
            WS,
            seg.id,
            "object_relative",
            {"tx": 1.0},
            start_frame=0,
            end_frame=10,
            start_time_ms=0,
            end_time_ms=6000,
        )
    session.rollback()
    assert _count("segment_motion", db) == 0
    session.close()


def test_c1f4_valid_time_but_frame_outside_segment_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], frame=(0, 100), time=(0, 5000))
    session.commit()
    with pytest.raises(ValueError, match="within the segment range"):
        repo.create_motion(
            WS,
            seg.id,
            "object_relative",
            {"tx": 1.0},
            start_frame=50,
            end_frame=200,
            start_time_ms=0,
            end_time_ms=5000,
        )
    session.rollback()
    assert _count("segment_motion", db) == 0
    session.close()


def test_c1f4_update_end_time_beyond_segment_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], frame=(0, 100), time=(0, 5000))
    session.commit()
    motion, _ = repo.create_motion(
        WS,
        seg.id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=100,
        start_time_ms=0,
        end_time_ms=5000,
    )
    session.commit()
    with pytest.raises(ValueError, match="within the segment range"):
        repo.update_motion(WS, motion.id, motion.revision, end_time_ms=5500)
    session.rollback()
    intact = repo.get_motion(WS, motion.id)
    assert intact.end_time_ms == 5000 and intact.revision == motion.revision
    session.close()


def test_c1f4_update_end_frame_beyond_segment_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, b_id = _two_segments(repo, seed)
    target, _ = _seg(
        repo,
        seed,
        "Hand",
        role=seed.roles["Hand"],
        mask=seed.masks[2],
        frame=(0, 50),
        time=(0, 2000),
    )
    session.commit()
    occ, _ = repo.create_occlusion(
        WS,
        seed.project,
        seed.video,
        a_id,
        target.id,
        0,
        50,
        0,
        2000,
        idempotency_key="occ-update-key",
    )
    session.commit()
    with pytest.raises(ValueError, match="within the segment range"):
        repo.update_occlusion(WS, occ.id, occ.revision, end_frame=120)
    session.rollback()
    intact = repo.get_occlusion(WS, occ.id)
    assert intact.end_frame == 50 and intact.revision == occ.revision
    session.close()


def test_c1f4_range_inside_source_but_outside_target_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    source, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    target, _ = _seg(
        repo,
        seed,
        "Phone",
        role=seed.roles["Phone"],
        mask=seed.masks[1],
        frame=(0, 50),
        time=(0, 2000),
    )
    session.commit()
    # (40,60) is inside source (0..180) but outside target (0..50).
    with pytest.raises(ValueError, match="within the segment range"):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            source.id,
            target.id,
            "character_phone",
            40,
            60,
            0,
            2000,
        )
    session.rollback()
    assert _count("scene_graph_contact", db) == 0
    session.close()


def test_c1f4_zero_mutation_after_each_reject(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], frame=(0, 100), time=(0, 5000))
    session.commit()
    seg_rows_before = _segment_rows(db)
    for kw in (
        dict(start_frame=0, end_frame=10, start_time_ms=0, end_time_ms=6000),
        dict(start_frame=50, end_frame=120, start_time_ms=0, end_time_ms=5000),
    ):
        with pytest.raises(ValueError):
            repo.create_motion(
                WS,
                seg.id,
                "object_relative",
                {"tx": 1.0},
                **kw,
            )
        session.rollback()
    assert _count("segment_motion", db) == 0
    assert _segment_rows(db) == seg_rows_before
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# C1-F5 — Ownership and artifact
# ══════════════════════════════════════════════════════════════════════════


def test_c1f5_non_image_mask_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="kind=image"):
        _seg(repo, seed, "Character", mask=seed.video_mask, prompt=_prompt())
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f5_non_ready_mask_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="state=ready"):
        _seg(repo, seed, "Character", mask=seed.staging_mask, prompt=_prompt())
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f5_wrong_workspace_mask_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="another workspace"):
        _seg(repo, seed, "Character", mask=seed.other_artifact, prompt=_prompt())
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f5_missing_model_job_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="missing model job"):
        _seg(repo, seed, "Character", job=None, mask=seed.masks[0])
    with pytest.raises(ValueError, match="missing model job"):
        repo.create_segment(
            WS,
            seed.project,
            seed.video,
            seed.roles["Character"],
            seed.scene,
            "Character",
            0,
            180,
            0,
            6000,
            GEN,
            mask_artifact_id=seed.masks[0],
            confidence_source="detector",
        )
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f5_wrong_source_sha_job_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # bad_sha_job is a COMPLETED DISCOVER_OBJECTS job of THIS video at the
    # RIGHT generation but its manifest source SHA does not match the video's
    # current source artifact.
    with pytest.raises(OwnershipMismatchError, match="source SHA"):
        _seg(repo, seed, "Character", job=seed.bad_sha_job, gen=GEN)
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f5_role_kind_mismatch_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # Character role kind == "character" but the caller forces "prop".
    with pytest.raises(OwnershipMismatchError, match="ObjectRole taxonomy"):
        _seg(repo, seed, "Character", kind="prop")
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f5_segment_kind_update_mismatch_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    # Role kind is "character" — updating the segment kind to "prop" diverges
    # from the role taxonomy.
    with pytest.raises(OwnershipMismatchError, match="ObjectRole kind"):
        repo.update_segment(WS, seg.id, seg.revision, kind="prop")
    session.rollback()
    intact = repo.get_segment(WS, seg.id)
    assert intact.kind == "character" and intact.revision == seg.revision
    assert _count_segments(session, db) == 1
    session.close()


def test_c1f5_failure_leaves_zero_mutation(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    before = _segment_rows(db)
    for bad in (
        dict(mask=seed.video_mask, prompt=_prompt()),
        dict(mask=seed.staging_mask, prompt=_prompt()),
        dict(job=seed.bad_sha_job),
    ):
        with pytest.raises(OwnershipMismatchError):
            _seg(repo, seed, "Character", **bad)
        session.rollback()
    assert _segment_rows(db) == before
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# C1-F6 — Domain validation before flush
# ══════════════════════════════════════════════════════════════════════════


def test_c1f6_algorithm_lengths_validated_before_flush(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="at most 64 chars"):
        _seg(repo, seed, "Character", mask=seed.masks[0], algorithm="a" * 65)
    with pytest.raises(ValueError, match="at most 64 chars"):
        _seg(repo, seed, "Character", mask=seed.masks[0], algorithm_version="9." + "x" * 63)
    assert _count_segments(session, db) == 0
    a_id, _ = _two_segments(repo, seed)
    session.commit()
    with pytest.raises(ValueError, match="at most 64 chars"):
        repo.create_motion(
            WS,
            a_id,
            "camera_relative",
            {"tx": 1.0},
            start_frame=0,
            end_frame=2,
            start_time_ms=0,
            end_time_ms=100,
            algorithm="y" * 65,
        )
    session.rollback()
    assert _count("segment_motion", db) == 0
    session.close()


def test_c1f6_reasons_provenance_types_validated(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="reasons must be a list"):
        _seg(repo, seed, "Character", mask=seed.masks[0], reasons="not-a-list")
    with pytest.raises(ValueError, match="reasons must be a list"):
        _seg(repo, seed, "Character", mask=seed.masks[0], reasons=[1, 2])
    with pytest.raises(ValueError, match="provenance must be a JSON object"):
        _seg(repo, seed, "Character", mask=seed.masks[0], provenance=["x"])
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f6_prompt_points_boxes_must_be_lists(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="points must be a JSON array"):
        _seg(repo, seed, "Character", mask=seed.masks[0], prompt={"points": 5, "boxes": []})
    with pytest.raises(ValueError, match="boxes must be a JSON array"):
        _seg(repo, seed, "Character", mask=seed.masks[0], prompt={"points": [], "boxes": {"x": 1}})
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f6_prompt_point_and_box_shapes_strict(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    bad = [
        {"points": [{"x": 1.0, "y": 2.0, "label": ""}], "boxes": []},  # empty label
        {"points": [{"x": 1.0, "y": 2.0, "label": "a", "extra": 1}], "boxes": []},  # extra key
        {"points": [], "boxes": [{"x": 1.0, "y": 2.0, "w": 3, "h": 4, "z": 5}]},  # extra key
        {"points": [], "boxes": [{"x": 1.0, "y": 2.0, "w": 3, "h": -1}]},  # bad h
        {"points": [{"x": 1.0, "y": 2.0, "label": "a", "extra": 1}], "boxes": []},
    ]
    for payload in bad:
        with pytest.raises(ValueError):
            _seg(repo, seed, "Character", mask=seed.masks[0], prompt=payload)
    assert _count_segments(session, db) == 0
    session.close()


def test_c1f6_nan_infinity_rejected_before_flush(tmp_path: Path) -> None:
    import math as _math

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="finite number"):
        _seg(
            repo,
            seed,
            "Character",
            mask=seed.masks[0],
            prompt={"points": [{"x": _math.nan, "y": 2.0, "label": "p"}], "boxes": []},
        )
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})
    a_id, _ = _two_segments(repo, seed)
    session.commit()
    with pytest.raises(ValueError):
        repo.create_motion(
            WS,
            a_id,
            "camera_relative",
            {"x": float("nan")},
            start_frame=0,
            end_frame=2,
            start_time_ms=0,
            end_time_ms=100,
        )
    session.rollback()
    assert _count_segments(session, db) == 2 and _count("segment_motion", db) == 0
    session.close()


def test_c1f6_malformed_durable_json_fails_closed(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    rec, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    with create_engine_for_path(db).connect() as conn:
        conn.execute(
            text("UPDATE occurrence_segment SET reasons_json='{oops' WHERE id=:i"),
            {"i": rec.id},
        )
        conn.commit()
    with pytest.raises(MalformedJsonError, match="malformed"):
        repo.get_segment(WS, rec.id)
    session.close()


def test_c1f6_non_idempotency_integrity_error_not_blanket_duplicate(
    tmp_path: Path,
) -> None:
    """A real duplicate (same segment+type+start frame) WITHOUT an idempotency
    key is reported as a REAL constraint conflict, never as an idempotency
    replay/duplicate."""
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    a_id, _ = _two_segments(repo, seed)
    session.commit()
    repo.create_motion(
        WS,
        a_id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=2,
        start_time_ms=0,
        end_time_ms=100,
    )
    session.commit()
    with pytest.raises(MotionConflictError) as excinfo:
        repo.create_motion(
            WS,
            a_id,
            "camera_relative",
            {"tx": 2.0},
            start_frame=0,
            end_frame=2,
            start_time_ms=0,
            end_time_ms=100,
        )
    msg = str(excinfo.value)
    assert "idempotency" not in msg and "duplicate" not in msg
    assert "persistence conflict" in msg
    session.rollback()
    assert _count("segment_motion", db) == 1
    session.close()


# ══════════════════════════════════════════════════════════════════════════
# C1-F7 — Durable delete policy (RESTRICT, history preserved)
# ══════════════════════════════════════════════════════════════════════════


def test_c1f7_delete_referenced_role_fails_closed_preserves_history(
    tmp_path: Path,
) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    before = _segment_rows(db)
    role_id = seed.roles["Character"]

    with pytest.raises(IntegrityError), create_engine_for_path(db).connect() as conn:
        conn.execute(text("DELETE FROM object_role WHERE id = :rid"), {"rid": role_id})
        conn.commit()
    # Rows are byte-identical after the failed delete; history preserved.
    assert _segment_rows(db) == before
    with create_engine_for_path(db).connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    session.close()


def test_c1f7_delete_referenced_segment_fails_closed_preserves_motion(
    tmp_path: Path,
) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    repo.create_motion(
        WS,
        seg.id,
        "camera_relative",
        {"tx": 1.0},
        start_frame=0,
        end_frame=180,
        start_time_ms=0,
        end_time_ms=6000,
    )
    session.commit()
    motion_before = _motion_rows(db)
    seg_before = _segment_rows(db)

    with pytest.raises(IntegrityError), create_engine_for_path(db).connect() as conn:
        conn.execute(
            text("DELETE FROM occurrence_segment WHERE id = :sid"),
            {"sid": seg.id},
        )
        conn.commit()
    assert _motion_rows(db) == motion_before
    assert _segment_rows(db) == seg_before
    with create_engine_for_path(db).connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    session.close()


def test_c1f7_delete_scope_reflected_in_sqlite_master(tmp_path: Path) -> None:
    """The migration's FK delete policies are RESTRICT (byte-identical to the
    ORM) — reflected from a fresh migrated DB."""
    db = tmp_path / "fk.db"
    comm = _alembic_config(db)
    command.upgrade(comm, "head")
    with create_engine_for_path(db).connect() as conn:
        sql = {
            str(r[0]): str(r[1])
            for r in conn.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='table' AND name IN "
                    "('occurrence_segment','segment_motion')"
                )
            ).fetchall()
        }
    assert "ON DELETE RESTRICT" in sql["occurrence_segment"]
    assert "ON DELETE RESTRICT" in sql["segment_motion"]
    assert "ON DELETE CASCADE" not in sql["occurrence_segment"]
    assert "ON DELETE CASCADE" not in sql["segment_motion"]
