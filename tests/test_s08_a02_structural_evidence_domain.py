"""S08-A02-T01-R1 domain tests — structural-evidence repository invariants.

Drives ``StructuralEvidenceRepository`` directly on fresh isolated DBs (no
API — R1 has no router) with REAL SQLite FK / CHECK / partial-unique-index
enforcement.  Each finding F2..F10 of the R1 recovery contract (normative in
TASK.md §4) is closed by a focused test that fails on the untrusted draft:

- F2: ``logical_id`` stable across supersession; per-version ``id`` distinct;
  predecessor.superseded_by_id -> successor; never delete predecessor; both
  current + historical queryable; display names never identity.
- F3: versions/generations coexist; no duplicate ACTIVE record; idempotent
  retry safe; natural key is NEVER an idempotency key.
- F4: generation authority EQUALS ``ObjectIntelligenceRepository`` (not a
  naive max+1 copy) and must consider source-SHA + completed DISCOVER job.
- F5: cross-workspace / cross-video / cross-generation ownership fails
  BEFORE commit creating ZERO rows (role-from-another-video, scene-from-
  another-video, artifact-from-another-workspace, job-owned-by-someone-else,
  job-of-a-different-generation).
- F6: mask REQUIRED with segmentation evidence + owned; strict prompt
  shape; NaN/Infinity rejected; malformed durable JSON fails CLOSED.
- F7: lineage on ANY version -> oldest->newest; cycle/dangling detected;
  atomic correction rollback on conflict.
- F8: historical/superseded mutation refused; stale revision -> stable
  conflict with ZERO mutation (segments + motion + occlusion + contact).
- F9: idempotency replay / payload-conflict / workspace-scoped / concurrent
  no-duplicate.
- F10: end>=start; edge/motion range within segment; same-video compatible
  generation endpoints; self-edge rejected; confidence/z-order/visibility/
  contact-kind enums.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
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
    parse_json,
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
    """Handles for the isolated test graph."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.project = ""
        self.video = ""
        self.other_video = ""
        self.scene = ""
        self.other_scene = ""
        self.roles: dict[str, str] = {}
        self.masks: list[str] = []
        self.other_artifact = ""
        self.job = ""
        self.other_job = ""
        self.job_wronggen = ""


def _seed(session: Session) -> Seed:
    """Seed a complete FK-resolvable graph with a backend-authoritative
    current generation "3" (completed DISCOVER_OBJECTS job whose manifest
    source SHA matches the video's source artifact)."""
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

    project = Project(workspace_id=WS, name="A02")
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

    # A completed job for ANOTHER video so the F5 "job owned by someone else"
    # case has a real foreign job.  other_video gets its own source artifact so
    # its backend current generation resolves to "7" (C1-F1 authority).
    other_source = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path="other-src.mp4",
        state="ready",
        sha256=_sha(2),
    )
    session.add(other_source)
    session.flush()
    other_video = VideoItem(
        project_id=project.id,
        title="Other",
        position=1,
        source_artifact_id=other_source.id,
    )
    session.add(other_video)
    session.flush()
    other_job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=other_video.id,
        state="completed",
        input_generation="7",
        input_manifest_json=canonical_json({"source_sha256": _sha(2)}),
    )
    session.add(other_job)
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
    other_scene = Scene(
        video_item_id=other_video.id,
        position=0,
        start_frame=0,
        end_frame=100,
        start_time_ms=0,
        end_time_ms=3000,
        status="pending",
    )
    session.add_all([scene, other_scene])
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

    # A role owned by the OTHER video (F5: role from another video rejected).
    other_role = ObjectRole(
        workspace_id=WS,
        project_id=project.id,
        video_item_id=other_video.id,
        source_generation="7",
        name="RoleOtherVideo",
        kind="character",
        status="confirmed",
    )
    session.add(other_role)
    session.flush()
    seed.other_role = other_role.id

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

    workspace2 = Workspace(id="ws2", name="ws2")
    session.add(workspace2)
    session.flush()
    other_artifact = Artifact(
        workspace_id=workspace2.id,
        kind="image",
        relative_path="other.png",
        state="ready",
        sha256=_sha(99),
    )
    session.add(other_artifact)
    session.flush()

    seed.project = project.id
    seed.video = video.id
    seed.other_video = other_video.id
    seed.scene = scene.id
    seed.other_scene = other_scene.id
    seed.job = job.id
    seed.other_job = other_job.id
    seed.other_artifact = other_artifact.id
    session.commit()
    return seed


def _open_db(tmp_path: Path) -> tuple[Session, Seed, Path]:
    db = tmp_path / "a02.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    factory = create_session_factory(create_engine_for_path(db))
    session = factory()
    seed = _seed(session)
    return session, seed, db


def _count_segments(session: Session, db: Path) -> int:
    session.rollback()
    with create_engine_for_path(db).connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM occurrence_segment")).scalar())


def _prompt() -> dict:
    return {
        "points": [{"x": 10.0, "y": 20.0, "label": "center"}],
        "boxes": [{"x": 1.0, "y": 2.0, "w": 30.0, "h": 30.0}],
    }


def _seg(
    repo: StructuralEvidenceRepository,
    seed: Seed,
    name: str = "Character",
    *,
    role: str | None = None,
    scene: str | None = None,
    gen: str = GEN,
    job: str | None = None,
    mask: str | None = None,
    prompt: dict | None = None,
    frame: tuple[int, int] = (0, 180),
    time: tuple[int, int] = (0, 6000),
    idem: str | None = None,
    **kw,
) -> tuple:
    # C1-F5: a segment kind is INHERITED from the ObjectRole taxonomy.
    role_id = role or seed.roles["Character"]
    role_row = repo._session.get(ObjectRole, role_id)
    kind = kw.pop("kind", role_row.kind)
    return repo.create_segment(
        WS,
        seed.project,
        seed.video,
        role_id,
        scene or seed.scene,
        name,
        frame[0],
        frame[1],
        time[0],
        time[1],
        gen,
        kind=kind,
        # C1-F5: model/detector evidence requires the producing job; the
        # default helper models a REAL model-produced segment.
        source_job_id=job if job is not None else seed.job,
        mask_artifact_id=mask,
        prompt=prompt,
        idempotency_key=idem,
        **kw,
    )


def _advance_generation(session: Session, seed: Seed, new_gen: str) -> str:
    """Advance backend current generation to new_gen via REAL
    ObjectIntelligenceRepository.create_role (C2-F1: never mutate
    ObjectRole.source_generation directly)."""
    from app.persistence.object_intelligence import ObjectIntelligenceRepository

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
    for name, role_id in list(seed.roles.items()):
        if name.endswith(f"_g{new_gen}"):
            continue
        r = session.get(ObjectRole, role_id)
        if r is None:
            continue
        new_role, _ = oi_repo.create_role(
            workspace_id=WS,
            project_id=seed.project,
            video_item_id=seed.video,
            source_generation=new_gen,
            name=f"{name}_g{new_gen}",
            kind=r.kind,
            status=r.status,
        )
        seed.roles[f"{name}_g{new_gen}"] = new_role.id
    session.flush()
    session.commit()
    return job.id


# ── F2 logical identity vs record-version identity ─────────────────────────


def test_f2_logical_lineage_id_stable_and_versions_distinct(
    tmp_path: Path,
) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", job=seed.job, gen=GEN, mask=seed.masks[0])
    session.commit()

    # C1-F1 workflow A: MANUAL same-generation correction (new version, same
    # source generation, user provenance).
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

    # Same lineage id, distinct per-version record ids, name kept.
    assert successor.logical_id == prior.logical_id == seg.logical_id
    assert successor.id != prior.id
    assert successor.name == prior.name
    assert prior.superseded_by_id == successor.id
    # C1-F2: explicit lineage versioning — successor = prior + 1.
    assert successor.lineage_version == prior.lineage_version + 1 == 2
    # C1-F1: manual correction stays in the SAME current generation and must
    # carry user/manual provenance (never silently inherits machine).
    assert successor.source_generation == seg.source_generation == GEN
    assert successor.confidence_source == "user"
    assert successor.reasons == ["user correction"]
    assert successor.superseded_by_id is None

    # Both current and historical rows remain queryable (records never deleted).
    hist = repo.get_segment(WS, prior.id)
    curr = repo.get_segment(WS, successor.id)
    assert hist.id == prior.id and hist.superseded_by_id == successor.id
    assert curr.id == successor.id and curr.superseded_by_id is None

    # Lineage from ANY version returns oldest -> newest.
    for probe in (prior.id, successor.id):
        chain = repo.segment_lineage(WS, probe)
        assert [c.id for c in chain] == [prior.id, successor.id]

    # Stable logical id lookup returns all versions oldest->newest.
    by_logical = repo.get_segment_by_logical_id(WS, seg.logical_id)
    assert {r.id for r in by_logical} == {prior.id, successor.id}
    assert [r.lineage_version for r in by_logical] == [1, 2]
    # Current version explicitly determinable (not only via the partial index).
    current = repo.current_segment_by_logical_id(WS, seg.logical_id)
    assert current is not None and current.id == successor.id
    assert _count_segments(session, db) == 2
    # The successor is STILL current and updatable (C1-F1 requirement 2).
    updated = repo.update_segment(WS, successor.id, successor.revision, confidence=0.99)
    session.commit()
    assert updated.id == successor.id and updated.confidence == 0.99
    session.close()


# ── F3 versions coexist / no duplicate ACTIVE / natural key not idempotency ─


def test_f3_versions_coexist_but_single_active_and_no_natural_key_idempotency(
    tmp_path: Path,
) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg1, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()

    # Same identity + same generation -> duplicate ACTIVE refused (F3).
    with pytest.raises(SegmentConflictError):
        _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.rollback()
    assert _count_segments(session, db) == 1

    # C1-F1: versions/generations coexist via the backend current generation
    # (never an arbitrary caller-supplied future generation).  Advance the
    # backend generation to "4" with a role at "4", then create a second ROOT
    # segment in generation "4" with the same identity.
    job4 = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=seed.video,
        state="completed",
        input_generation="4",
        input_manifest_json=canonical_json({"source_sha256": _sha(1)}),
    )
    session.add(job4)
    session.flush()
    role4 = ObjectRole(
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=seed.video,
        source_generation="4",
        name="Character",
        kind="character",
        status="confirmed",
    )
    session.add(role4)
    session.commit()
    assert repo.current_generation(WS, seed.video) == "4"

    seg2, created = _seg(
        repo,
        seed,
        "Character",
        role=role4.id,
        gen="4",
        mask=seed.masks[1],
        job=job4.id,
    )
    session.commit()
    assert created and seg2.id != seg1.id
    # SAME identity, DIFFERENT (current) generation -> both active rows coexist.
    assert _count_segments(session, db) == 2
    session.close()


def test_f3_idempotent_retry_safe_via_key_only(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    key = "seg-idem-1"
    rec, created = _seg(repo, seed, "Character", mask=seed.masks[0], idem=key)
    session.commit()
    assert created

    # Replay same key + identical payload -> existing record, not a new row.
    replay, created2 = _seg(repo, seed, "Character", mask=seed.masks[0], idem=key)
    session.commit()
    assert not created2 and replay.id == rec.id
    assert _count_segments(session, db) == 1

    # Same key + materially different payload -> stable conflict.
    with pytest.raises(SegmentConflictError):
        _seg(repo, seed, "Character", mask=seed.masks[1], idem=key)
    session.rollback()
    assert _count_segments(session, db) == 1

    # Workspace-scoped: the same key in another workspace is a fresh record.
    session.close()


def test_f9_idempotency_keys_are_workspace_scoped(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    key = "scoped"
    rec1, _ = _seg(repo, seed, "Character", mask=seed.masks[0], idem=key)
    session.commit()

    # Build a minimal graph in the SEPARATE workspace (seeded as ``ws2``) and
    # reuse the SAME key there: the unique index is workspace-scoped, so no
    # cross-workspace clash.
    project2 = Project(workspace_id="ws2", name="P2")
    session.add(project2)
    session.flush()
    video2 = VideoItem(project_id=project2.id, title="V2", position=0)
    session.add(video2)
    session.flush()
    scene2 = Scene(
        video_item_id=video2.id,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    role2 = ObjectRole(
        workspace_id="ws2",
        project_id=project2.id,
        video_item_id=video2.id,
        source_generation="1",
        name="Char2",
        kind="character",
        status="confirmed",
    )
    mask2 = Artifact(
        workspace_id="ws2",
        kind="image",
        relative_path="m2.png",
        state="ready",
        sha256=_sha(123),
    )
    session.add_all([scene2, role2, mask2])
    session.commit()

    rec2, created = repo.create_segment(
        "ws2",
        project2.id,
        video2.id,
        role2.id,
        scene2.id,
        "Char2",
        0,
        10,
        0,
        1000,
        "1",
        # user/manual evidence needs no producing job (C1-F5).
        mask_artifact_id=mask2.id,
        idempotency_key=key,
        confidence_source="user",
    )
    session.commit()
    assert created and rec2.id != rec1.id

    # Same key lives in BOTH workspaces with zero conflict.
    with create_engine_for_path(db).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT workspace_id, idempotency_key FROM occurrence_segment "
                "WHERE idempotency_key = :k ORDER BY id"
            ),
            {"k": key},
        ).all()
    assert len(rows) == 2
    assert {str(r[0]) for r in rows} == {WS, "ws2"}
    session.close()


# ── F4 generation authority equals ObjectIntelligenceRepository ────────────


def test_f4_generation_authority_matches_object_intelligence(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    authority = ObjectIntelligenceRepository(session)

    our_gen = repo.current_generation(WS, seed.video)
    auth_gen = authority.current_generation(WS, seed.video)
    assert our_gen == auth_gen == GEN, (
        "structural-evidence generation must equal the backend authority "
        f"(found {our_gen!r}, authority {auth_gen!r}; the naive max+1 draft "
        "returned a different value)"
    )

    # A segment produced by the CURRENT generation job is accepted...
    rec, _ = repo.create_segment(
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
        source_job_id=seed.job,
        mask_artifact_id=seed.masks[0],
    )
    session.commit()
    assert rec.source_generation == GEN
    session.close()


# ── F5 full ownership chain (fail pre-commit, zero rows) ───────────────────


def test_f5_cross_video_role_rejected_zero_rows(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="another video"):
        _seg(repo, seed, "Character", role=seed.other_role, scene=seed.scene)
    assert _count_segments(session, db) == 0
    session.close()


def test_f5_cross_video_scene_rejected_zero_rows(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="another video"):
        _seg(repo, seed, "Character", scene=seed.other_scene)
    assert _count_segments(session, db) == 0
    session.close()


def test_f5_cross_workspace_artifact_rejected_zero_rows(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="another workspace"):
        _seg(repo, seed, "Character", mask=seed.other_artifact, prompt=_prompt())
    assert _count_segments(session, db) == 0
    session.close()


def test_f5_job_owned_by_someone_else_rejected_zero_rows(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # Otherwise-valid request (current generation) with a job owned by ANOTHER
    # video -> rejected before commit with zero rows.
    with pytest.raises(OwnershipMismatchError, match="owned by someone else"):
        _seg(repo, seed, "Character", job=seed.other_job, gen=GEN)
    assert _count_segments(session, db) == 0
    session.close()


def test_f5_job_of_different_generation_rejected_zero_rows(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # A completed DISCOVER_OBJECTS job of THIS video but a DIFFERENT
    # generation than the segment being created -> reject before commit.
    wronggen = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=seed.video,
        state="completed",
        input_generation="2",
        # Non-matching manifest SHA so this job does NOT become the current
        # generation authority (C1-F1) — it stays a plain DIFFERENT-generation
        # job that the segment is wrongly bound to.
        input_manifest_json=canonical_json({"source_sha256": _sha(99)}),
    )
    session.add(wronggen)
    session.flush()
    with pytest.raises(OwnershipMismatchError, match="different generation"):
        _seg(repo, seed, "Character", job=wronggen.id, gen=GEN)
    assert _count_segments(session, db) == 0
    session.close()


def test_f5_video_chain_mismatch_rejected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError):
        repo.create_segment(
            WS,
            "bogus-project",
            seed.video,
            seed.roles["Character"],
            seed.scene,
            "Character",
            0,
            180,
            0,
            6000,
            GEN,
        )
    assert _count_segments(session, db) == 0
    session.close()


# ── F6 segmentation / mask / JSON contract ─────────────────────────────────


def test_f6_mask_required_with_segmentation_evidence(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="mask_artifact_id is missing"):
        _seg(repo, seed, "Character", prompt=_prompt(), mask=None)
    assert _count_segments(session, db) == 0
    # Not carrying evidence -> mask optional.
    rec, _ = _seg(repo, seed, "Character", mask=None)
    session.commit()
    assert rec.mask_artifact_id is None
    session.close()


def test_f6_mask_artifact_must_exist_and_belong(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(OwnershipMismatchError, match="does not exist"):
        _seg(repo, seed, "Character", mask="no-such-artifact", prompt=_prompt())
    assert _count_segments(session, db) == 0
    session.close()


def test_f6_strict_prompt_shape(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    bad = [
        {"points": [{"x": 1.0, "y": 2.0}], "boxes": []},  # missing point label
        {"points": [{"x": 1.0, "y": 2.0, "label": 5}]},  # label not a string
        {"points": [{"x": "a", "y": 2.0, "label": "p"}]},  # x not a number
        {"points": [], "boxes": [{"x": 1.0, "y": 2.0, "w": -1, "h": 3}]},  # neg w
        {"bogus": 1},  # unknown key
    ]
    for payload in bad:
        with pytest.raises(ValueError):
            _seg(repo, seed, "Character", mask=seed.masks[0], prompt=payload)
    assert _count_segments(session, db) == 0
    session.close()


def test_f6_nan_and_infinity_rejected(tmp_path: Path) -> None:
    import math as _math

    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    # NaN in canonical serialization is rejected (allow_nan=False).
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})
    # NaN as a prompt coordinate is rejected by the strict shape validator.
    with pytest.raises(ValueError, match="finite number"):
        _seg(
            repo,
            seed,
            "Character",
            mask=seed.masks[0],
            prompt={"points": [{"x": _math.nan, "y": 2.0, "label": "p"}]},
        )
    # NaN confidence rejected.
    with pytest.raises(ValueError, match="finite"):
        _seg(repo, seed, "Character", confidence=float("nan"))
    assert _count_segments(session, db) == 0
    session.close()


def test_f6_malformed_durable_json_fails_closed(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    rec, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    assert rec.reasons == []

    # Corrupt a durable JSON column behind the repository's back.
    with create_engine_for_path(db).connect() as conn:
        conn.execute(
            text("UPDATE occurrence_segment SET reasons_json = '{not-json' WHERE id=:i"),
            {"i": rec.id},
        )
        conn.commit()
    with pytest.raises(MalformedJsonError, match="malformed"):
        repo.get_segment(WS, rec.id)
    # parse_json itself fails closed too.
    with pytest.raises(MalformedJsonError, match="malformed"):
        parse_json("{not-json")
    session.close()


def test_f6_deterministic_serialization_round_trip(tmp_path: Path) -> None:
    payload = {
        "boxes": [{"x": 4.0, "y": 5.0, "w": 10.0, "h": 20.0}],
        "points": [{"x": 1.0, "y": 2.0, "label": "a"}],
    }
    enc1 = canonical_json(payload)
    enc2 = canonical_json(payload)
    assert enc1 == enc2
    assert canonical_json(parse_json(enc1)) == enc1  # byte-identical round-trip
    # Order-independent input serialises identically.
    shuffled = {
        "points": payload["points"],
        "boxes": payload["boxes"],
    }
    assert canonical_json(shuffled) == enc1


# ── F7 lineage walker + atomicity ──────────────────────────────────────────


def test_f7_lineage_from_any_version_oldest_to_newest(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)

    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()
    # C1-F1 workflow B: each transition = re-analysis to the NEW backend
    # current generation with a producing job (roles advance in lockstep).
    job4 = _advance_generation(session, seed, "4")
    prior1, v2 = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation="4",
        source_job_id=job4,
        target_role_id=seed.roles["Character_g4"],
        mask_artifact_id=seed.masks[1],
        confidence_source="model",
    )
    session.commit()
    job5 = _advance_generation(session, seed, "5")
    prior2, v3 = repo.supersede_segment(
        WS,
        v2.id,
        v2.revision,
        source_generation="5",
        source_job_id=job5,
        target_role_id=seed.roles["Character_g5"],
        mask_artifact_id=seed.masks[2],
        confidence_source="model",
    )
    session.commit()

    expected = [prior1.id, prior2.id, v3.id]
    # C1-F2: versions are 1 -> 2 -> 3.
    assert [v.lineage_version for v in repo.segment_lineage(WS, v3.id)] == [1, 2, 3]
    # Starting from the OLDEST.
    assert [c.id for c in repo.segment_lineage(WS, prior1.id)] == expected
    # Starting from the MIDDLE.
    assert [c.id for c in repo.segment_lineage(WS, prior2.id)] == expected
    # Starting from the NEWEST.
    assert [c.id for c in repo.segment_lineage(WS, v3.id)] == expected
    # Never reversed: oldest generation first.
    assert repo.segment_lineage(WS, v3.id)[0].source_generation == GEN
    session.close()


def test_f7_cycle_detected(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    # Build a two-node cycle by hand (behind the repository's back).
    with session.begin_nested():
        a = session.get(OccurrenceSegment, seg.id)
        b = OccurrenceSegment(
            logical_id="cycle",
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
            source_generation="4",
            confidence=1.0,
            confidence_source="user",
        )
        session.add(b)
        session.flush()
        a.superseded_by_id = b.id
        b.superseded_by_id = a.id
    session.commit()
    with pytest.raises(SegmentConflictError, match="cycle"):
        repo.segment_lineage(WS, seg.id)
    session.close()


def test_f7_dangling_link_detected(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    # SQLite enforces the FK on every app connection, so fabricate the
    # dangling link on a raw connection with FK enforcement OFF — the
    # repository walker must still detect it and refuse.
    with create_engine_for_path(db).connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text("UPDATE occurrence_segment SET superseded_by_id='missing-successor' WHERE id=:i"),
            {"i": seg.id},
        )
        conn.commit()
    with pytest.raises(SegmentConflictError, match="dangling"):
        repo.segment_lineage(WS, seg.id)
    session.close()


def test_f7_atomic_correction_rolls_back_on_conflict(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()

    # Force a failure INSIDE the correction savepoint: a used idempotency key
    # on the successor collides -> SegmentConflictError -> successor rolled back.
    _seg(repo, seed, "Phone", role=seed.roles["Phone"], mask=seed.masks[3], idem="taken")
    session.commit()
    before = _count_segments(session, db)  # Character + Phone
    assert before == 2

    with pytest.raises(SegmentConflictError):
        repo.supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation=GEN,
            confidence_source="user",
            provenance={"who": "human"},
            mask_artifact_id=seed.masks[1],
            idempotency_key="taken",
        )
    session.rollback()
    # The correction was fully rolled back: same row count, prior untouched.
    assert _count_segments(session, db) == before
    prior = repo.get_segment(WS, seg.id)
    assert prior.superseded_by_id is None and prior.revision == seg.revision
    session.close()


# ── F8 historical mutation safety / stale CAS ──────────────────────────────


def test_f8_superseded_segment_read_only_zero_mutation(tmp_path: Path) -> None:
    session, seed, db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()
    prior, successor = repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        provenance={"who": "human"},
        mask_artifact_id=seed.masks[1],
    )
    session.commit()

    with pytest.raises(SegmentConflictError, match="superseded"):
        repo.update_segment(WS, prior.id, prior.revision, name="nope")
    session.rollback()
    intact = repo.get_segment(WS, prior.id)
    assert intact.name == "Character" and intact.revision == 2
    with create_engine_for_path(db).connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM occurrence_segment")).scalar()
    assert int(cnt) == 2
    session.close()


def test_f8_stale_cas_conflict_segment_zero_mutation(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    with pytest.raises(SegmentConflictError, match="stale revision"):
        repo.update_segment(WS, seg.id, seg.revision + 5, name="x")
    session.rollback()
    after = repo.get_segment(WS, seg.id)
    assert after.name == "Character" and after.revision == seg.revision
    session.close()


def test_f8_motion_stale_and_superseded_segment_rejected(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], gen=GEN)
    session.commit()
    motion, _ = repo.create_motion(
        WS,
        seg.id,
        "camera_relative",
        {"a": [[1.0, 0.0], [0.0, 1.0]], "tx": 3.0},
        start_frame=0,
        end_frame=180,
        start_time_ms=0,
        end_time_ms=6000,
        confidence=0.9,
        idempotency_key="motion-1",
    )
    session.commit()

    # Stale revision on the motion -> stable conflict, zero mutation.
    with pytest.raises(MotionConflictError, match="stale revision"):
        repo.update_motion(WS, motion.id, motion.revision + 9, confidence=0.1)
    session.rollback()
    intact = repo.get_motion(WS, motion.id)
    assert intact.confidence == 0.9 and intact.revision == motion.revision

    # After the owning segment is superseded, the motion is historical too.
    repo.supersede_segment(
        WS,
        seg.id,
        seg.revision,
        source_generation=GEN,
        confidence_source="user",
        provenance={"who": "human"},
        mask_artifact_id=seed.masks[3],
    )
    session.commit()
    with pytest.raises(SegmentConflictError, match="superseded"):
        repo.update_motion(WS, motion.id, intact.revision, confidence=0.2)
    session.rollback()
    session.close()


def test_f8_occlusion_contact_stale_revision_conflict(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    char, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    phone, _ = _seg(repo, seed, "Phone", role=seed.roles["Phone"], mask=seed.masks[1])
    hand, _ = _seg(repo, seed, "Hand", role=seed.roles["Hand"], mask=seed.masks[2])
    session.commit()
    occ, _ = repo.create_occlusion(
        WS,
        seed.project,
        seed.video,
        phone.id,
        hand.id,
        0,
        180,
        0,
        6000,
        idempotency_key="occ-1",
    )
    con, _ = repo.create_contact(
        WS,
        seed.project,
        seed.video,
        char.id,
        phone.id,
        "character_phone",
        0,
        180,
        0,
        6000,
        idempotency_key="con-1",
    )
    session.commit()
    with pytest.raises(OcclusionConflictError, match="stale revision"):
        repo.update_occlusion(WS, occ.id, occ.revision + 4, confidence=0.5)
    with pytest.raises(ContactConflictError, match="stale revision"):
        repo.update_contact(WS, con.id, con.revision + 4, confidence=0.5)
    session.rollback()
    session.close()


# ── F10 temporal / endpoint invariants ─────────────────────────────────────


def test_f10_frame_time_range_invariants(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    with pytest.raises(ValueError, match="end_frame must be >= start_frame"):
        _seg(repo, seed, "Character", frame=(100, 50))
    with pytest.raises(ValueError, match="non-negative"):
        _seg(repo, seed, "Character", frame=(-1, 50))
    with pytest.raises(ValueError, match="end_time_ms must be >= start_time_ms"):
        _seg(repo, seed, "Character", time=(5000, 1000))
    with pytest.raises(ValueError, match="finite number between 0 and 1"):
        _seg(repo, seed, "Character", confidence=1.5)
    with pytest.raises(ValueError, match="z_order"):
        _seg(repo, seed, "Character", z_order=2_000_000)
    with pytest.raises(ValueError, match="visibility"):
        _seg(repo, seed, "Character", visibility="invisible")
    with pytest.raises(ValueError, match="source_generation"):
        _seg(repo, seed, "Character", gen="")
    session.rollback()
    session.close()


def test_f10_motion_range_must_fit_segment(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    seg, _ = _seg(repo, seed, "Character", mask=seed.masks[0], frame=(0, 100))
    session.commit()
    with pytest.raises(ValueError, match="within the segment range"):
        repo.create_motion(
            WS,
            seg.id,
            "object_relative",
            {"tx": 1.0},
            start_frame=50,
            end_frame=200,
            start_time_ms=50,
            end_time_ms=200,
        )
    session.rollback()
    session.close()


def test_f10_edges_same_video_compatible_generation_self_edge(
    tmp_path: Path,
) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    char, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    phone, _ = _seg(repo, seed, "Phone", role=seed.roles["Phone"], mask=seed.masks[1])
    session.commit()

    # Self-edge refused on both edge kinds.
    with pytest.raises(ValueError, match="different"):
        repo.create_occlusion(WS, seed.project, seed.video, char.id, char.id, 0, 180, 0, 6000)
    with pytest.raises(ValueError, match="different"):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            char.id,
            char.id,
            "hand_phone",
            0,
            180,
            0,
            6000,
        )
    # Invalid contact kind refused.
    with pytest.raises(ValueError, match="contact_kind"):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            char.id,
            phone.id,
            "nonsense",
            0,
            180,
            0,
            6000,
        )
    session.rollback()
    session.close()


def test_f10_endpoints_cross_video_rejected(tmp_path: Path) -> None:
    session, seed, _db = _open_db(tmp_path)
    repo = StructuralEvidenceRepository(session)
    char, _ = _seg(repo, seed, "Character", mask=seed.masks[0])
    session.commit()
    # A role owned by the OTHER video so the second segment is legitimately
    # created in another video, then a cross-video contact is rejected.
    orole = ObjectRole(
        workspace_id=WS,
        project_id=seed.project,
        video_item_id=seed.other_video,
        source_generation="7",
        name="OtherChar",
        kind="character",
        status="confirmed",
    )
    session.add(orole)
    session.flush()
    other, _ = repo.create_segment(
        WS,
        seed.project,
        seed.other_video,
        orole.id,
        seed.other_scene,
        "OtherChar",
        0,
        100,
        0,
        3000,
        "7",
        source_job_id=seed.other_job,
        mask_artifact_id=seed.masks[2],
    )
    session.commit()
    with pytest.raises(OwnershipMismatchError, match="same video"):
        repo.create_contact(
            WS,
            seed.project,
            seed.video,
            char.id,
            other.id,
            "hand_phone",
            0,
            100,
            0,
            3000,
        )
    session.rollback()
    session.close()


# ── F9 concurrent retry creates no duplicate ────────────────────────────────


def test_f9_concurrent_retry_no_duplicate(tmp_path: Path) -> None:
    db = tmp_path / "concurrent.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    session = create_session_factory(create_engine_for_path(db))()
    seed = _seed(session)
    session.close()

    key = "concurrent-key"
    barrier = threading.Barrier(4)
    outcomes: list[str] = []
    created_ids: list[str] = []

    def worker() -> None:
        s = create_session_factory(create_engine_for_path(db))()
        try:
            repo = StructuralEvidenceRepository(s)
            barrier.wait(timeout=30)
            rec, created = repo.create_segment(
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
                source_job_id=seed.job,
                mask_artifact_id=seed.masks[0],
                idempotency_key=key,
            )
            s.commit()
            if created:
                created_ids.append(rec.id)
            outcomes.append("ok")
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
            text("SELECT id FROM occurrence_segment WHERE idempotency_key = :k"),
            {"k": key},
        ).all()
    assert len(rows) == 1, f"concurrent retry created duplicates: {outcomes}"
    assert len(created_ids) <= 1
    if created_ids:
        assert str(rows[0][0]) == created_ids[0]
