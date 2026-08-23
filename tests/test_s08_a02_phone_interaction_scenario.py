"""S08-A02-T01-R1 acceptance scenario — a person using a phone.

A single focused write -> read-back integration test on ONE isolated temp DB
with REAL SQLite FK / CHECK / partial-unique-index enforcement:

- character occurrence, phone occurrence, hand anchor, face anchor
- character-phone and hand-phone contact edges/events
- a visibility assertion (both ``visible`` and ``occluded`` present)
- a z-order / occlusion assertion (phone over hand)
- camera-relative AND object-relative transforms (contract-only, no engine)
- temporal ranges on every durable row
- provenance + confidence on every evidence row
- deterministic (canonical) JSON round-trip
- read-back of BOTH the current graph and a CORRECTED historical lineage
  (same ``logical_id`` preserved; predecessor superseded -> successor; both
  queryable; ``PRAGMA foreign_key_check`` empty; ``integrity_check = ok``).

No API, no engine, no renderer — R1 has none.  Runs on a fresh isolated DB
only (never MAIN / user DBs).
"""

from __future__ import annotations

from pathlib import Path

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
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import (
    StructuralEvidenceRepository,
    canonical_json,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
WS = DEFAULT_WORKSPACE_ID
GEN = "3"


def _config(path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return cfg


def _sha(n: int) -> str:
    return f"{n:064x}"


def _seed(session: Session) -> dict[str, str]:
    workspace = Workspace(id=WS, name=WS)
    session.add(workspace)
    session.flush()
    source = Artifact(
        workspace_id=WS, kind="video", relative_path="src.mp4",
        state="ready", sha256=_sha(1),
    )
    session.add(source)
    session.flush()
    project = Project(workspace_id=WS, name="PhoneScene")
    session.add(project)
    session.flush()
    video = VideoItem(
        project_id=project.id, title="Phone", position=0,
        source_artifact_id=source.id,
    )
    session.add(video)
    session.flush()
    job = Job(
        workspace_id=WS, job_type="DISCOVER_OBJECTS", owner_type="video_item",
        owner_id=video.id, state="completed", input_generation=GEN,
        input_manifest_json=canonical_json({"source_sha256": _sha(1)}),
    )
    session.add(job)
    session.flush()
    scene = Scene(
        video_item_id=video.id, position=0, start_frame=0, end_frame=180,
        start_time_ms=0, end_time_ms=6000, status="pending",
    )
    session.add(scene)
    session.flush()

    roles: dict[str, str] = {}
    for name, kind in [
        ("Character", "character"),
        ("Phone", "prop"),
        ("Hand", "prop"),
        ("Face", "character"),
    ]:
        role = ObjectRole(
            workspace_id=WS, project_id=project.id, video_item_id=video.id,
            source_generation=GEN, name=name, kind=kind, status="confirmed",
        )
        session.add(role)
        session.flush()
        roles[name] = role.id

    masks: list[str] = []
    for i in range(6):
        mask = Artifact(
            workspace_id=WS, kind="image", relative_path=f"mask{i}.png",
            state="ready", sha256=_sha(10 + i),
        )
        session.add(mask)
        session.flush()
        masks.append(mask.id)

    session.commit()
    return {
        "project": project.id,
        "video": video.id,
        "scene": scene.id,
        "job": job.id,
        "roles": roles,
        "masks": masks,
    }


def test_phone_interaction_graph_write_and_readback(tmp_path: Path) -> None:
    db = tmp_path / "phone.db"
    command.upgrade(_config(db), "head")
    session = create_session_factory(create_engine_for_path(db))()
    seed = _seed(session)
    repo = StructuralEvidenceRepository(session)

    roles = seed["roles"]
    masks = seed["masks"]

    def seg(name: str, *, visibility: str, z: int, mask: str,
            prompt: dict | None = None) -> tuple[str, int]:
        # C1-F5: segment kind is inherited from the ObjectRole taxonomy.
        role_row = session.get(ObjectRole, roles[name])
        rec, created = repo.create_segment(
            WS, seed["project"], seed["video"], roles[name], seed["scene"],
            name, 0, 180, 0, 6000, GEN,
            kind=role_row.kind,
            source_job_id=seed["job"],
            mask_artifact_id=mask,
            prompt=prompt,
            segmentation={"points": [{"x": 10.0, "y": 10.0, "label": "c"}],
                          "boxes": [{"x": 2.0, "y": 2.0, "w": 50.0, "h": 80.0}]}
            if name == "Character" else None,
            algorithm="alpha-model", algorithm_version="1.4.0",
            confidence=0.97, confidence_source="model",
            reasons=["high_iou"], provenance={"run": "phone-scenario"},
            visibility=visibility, z_order=z,
            idempotency_key=f"seg-{name}",
        )
        assert created
        session.commit()
        return rec.id, rec.revision

    character_id, char_rev = seg("Character", visibility="visible", z=0, mask=masks[0],
                                 prompt={"points": [{"x": 5.0, "y": 5.0, "label": "torso"}]})
    phone_id, _ = seg("Phone", visibility="visible", z=2, mask=masks[1])
    hand_id, _ = seg("Hand", visibility="occluded", z=1, mask=masks[2],
                     prompt={"points": [{"x": 20.0, "y": 30.0, "label": "palm"}]})
    face_id, _ = seg("Face", visibility="visible", z=0, mask=masks[3],
                     prompt={"points": [{"x": 15.0, "y": 10.0, "label": "eye"}]})

    # Camera-relative transform (scene-level) on the Character segment.
    camera, _ = repo.create_motion(
        WS, character_id, "camera_relative",
        {"matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "proj": "affine2d"},
        point_track_flow_ref={"tracks": ["t-1", "t-2"], "kind": "sparse_flow"},
        start_frame=0, end_frame=180, start_time_ms=0, end_time_ms=6000,
        algorithm="flow-contract", algorithm_version="0.1",
        confidence=0.88, confidence_source="derived",
        provenance={"engine": "contract-only"}, idempotency_key="motion-camera",
    )
    # Object-relative transform on the Phone.
    obj_motion, _ = repo.create_motion(
        WS, phone_id, "object_relative",
        {"tx": 12.0, "ty": -3.0, "scale": 1.0, "rotation_deg": 0.0},
        start_frame=0, end_frame=180, start_time_ms=0, end_time_ms=6000,
        confidence=0.9, confidence_source="user", idempotency_key="motion-obj",
    )
    assert camera.transform_type == "camera_relative"
    assert obj_motion.transform_type == "object_relative"

    # Phone occludes Hand (z-order + occlusion assertion).
    occ, _ = repo.create_occlusion(
        WS, seed["project"], seed["video"], phone_id, hand_id,
        0, 180, 0, 6000, algorithm="alpha-model", algorithm_version="1.4.0",
        confidence=0.95, confidence_source="model",
        provenance={"kind": "phone_over_hand"}, idempotency_key="occ-phone-hand",
    )
    # Contacts: character<->phone and hand<->phone.
    contact_char, _ = repo.create_contact(
        WS, seed["project"], seed["video"], character_id, phone_id,
        "character_phone", 0, 180, 0, 6000,
        confidence=0.93, confidence_source="model",
        provenance={"kind": "character_phone"}, idempotency_key="con-char-phone",
    )
    contact_hand, _ = repo.create_contact(
        WS, seed["project"], seed["video"], hand_id, phone_id,
        "hand_phone", 20, 160, 1000, 5400,
        confidence=0.98, confidence_source="detector",
        provenance={"kind": "hand_phone"}, idempotency_key="con-hand-phone",
    )
    session.commit()

    # ── read back the full graph ────────────────────────────────────────────
    char = repo.get_segment(WS, character_id)
    phone = repo.get_segment(WS, phone_id)
    hand = repo.get_segment(WS, hand_id)
    face = repo.get_segment(WS, face_id)
    assert char.visibility == "visible" and char.z_order == 0
    assert phone.visibility == "visible" and phone.z_order == 2
    assert hand.visibility == "occluded" and hand.z_order == 1
    assert face.visibility == "visible"
    # Both visible and occluded states present.
    visibilities = {char.visibility, phone.visibility, hand.visibility, face.visibility}
    assert "visible" in visibilities and "occluded" in visibilities
    # Names are never identity.
    assert char.name == "Character" and phone.name == "Phone"

    # Deterministic JSON round-trip through the stored columns.
    assert canonical_json(
        {"points": [{"x": 10.0, "y": 10.0, "label": "c"}],
         "boxes": [{"x": 2.0, "y": 2.0, "w": 50.0, "h": 80.0}]}
    ) == char.segmentation_json

    _, total = repo.list_segments(WS, video_item_id=seed["video"])
    assert total == 4

    # Motion read-back.
    motions = repo.list_motions(WS, character_id)
    assert len(motions) == 1
    cam = motions[0]
    assert cam.transform == {
        "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "proj": "affine2d"
    }
    assert cam.point_track_flow_ref == {"tracks": ["t-1", "t-2"], "kind": "sparse_flow"}
    assert 0 <= cam.confidence <= 1 and cam.provenance == {"engine": "contract-only"}
    phone_motions = repo.list_motions(WS, phone_id)
    assert len(phone_motions) == 1 and phone_motions[0].transform["scale"] == 1.0

    # Occlusion + contact read-back.
    occs = repo.list_occlusions(WS, segment_id=phone_id)
    assert len(occs) == 1
    assert occs[0].occluder_segment_id == phone_id
    assert occs[0].occludee_segment_id == hand_id
    contacts = repo.list_contacts(WS)
    assert {c.contact_kind for c in contacts} == {"character_phone", "hand_phone"}
    by_hand = repo.list_contacts(WS, segment_id=hand_id)
    assert len(by_hand) == 1
    assert by_hand[0].contact_kind == "hand_phone"
    by_phone = repo.list_contacts(WS, segment_id=phone_id)
    assert len(by_phone) == 2

    # Real integrity at the end of the full graph.
    with create_engine_for_path(db).connect() as conn:
        integrity = conn.execute(text("PRAGMA integrity_check")).scalar()
        fk = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        seg_cnt = conn.execute(text("SELECT COUNT(*) FROM occurrence_segment")).scalar()
        con_cnt = conn.execute(text("SELECT COUNT(*) FROM scene_graph_contact")).scalar()
    assert integrity == "ok"
    assert fk == [], f"dangling FKs in phone graph: {fk}"
    assert int(seg_cnt) == 4
    assert int(con_cnt) == 2

    # ── corrected historical lineage read-back ──────────────────────────────
    # C1-F1 workflow A: MANUAL same-generation correction with user provenance.
    prior, successor = repo.supersede_segment(
        WS, character_id, char_rev, source_generation=GEN,
        confidence_source="user", mask_artifact_id=masks[4],
        visibility="visible", z_order=0, reasons=["user correction"], provenance={"who": "human"},
    )
    session.commit()
    assert successor.logical_id == prior.logical_id == char.logical_id
    assert successor.id != prior.id
    assert prior.superseded_by_id == successor.id
    assert successor.lineage_version == prior.lineage_version + 1 == 2

    # Both current and historical rows are queryable.
    hist = repo.get_segment(WS, prior.id)
    curr = repo.get_segment(WS, successor.id)
    assert hist.superseded_by_id == successor.id and hist.id == prior.id
    assert curr.id == successor.id and curr.superseded_by_id is None
    assert curr.logical_id == char.logical_id
    assert curr.source_generation == GEN
    assert curr.confidence_source == "user"

    # Lineage walker from either version returns oldest -> newest.
    chain = repo.segment_lineage(WS, prior.id)
    assert [c.id for c in chain] == [prior.id, successor.id]
    chain2 = repo.segment_lineage(WS, successor.id)
    assert [c.id for c in chain2] == [prior.id, successor.id]

    # Stable logical id lookup returns ALL versions.
    by_logical = repo.get_segment_by_logical_id(WS, char.logical_id)
    assert {r.id for r in by_logical} == {prior.id, successor.id}

    # The corrected successor carries the corrected evidence.
    assert curr.reasons == ["user correction"]
    with create_engine_for_path(db).connect() as conn:
        fk_after = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    assert fk_after == []
    session.close()
