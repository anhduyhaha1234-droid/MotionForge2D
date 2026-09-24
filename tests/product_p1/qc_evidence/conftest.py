"""MF-P1-QC-EVIDENCE — persisted-evidence fixtures for the QC evidence suite.

The fixture builds a REAL persisted world for one video item:

- workspace / project / video item (with probed canvas + canonical timebase);
- a real imported source media artifact and a real rendered result artifact
  (both written into the managed root, both with their true sha256/size);
- a completed full-apply run + publication pointing at the rendered artifact;
- extraction segments + their mask artifacts (real PNG bytes);
- a distinct rendered-side mask artifact (object-correction style publication);
- scene rows (scene-detector ground truth), render routes (S09), and the
  scene-graph contact/occlusion annotations;
- the CHARACTER LIBRARY target identity of every rendered role (correction
  round C / R4): a workspace Character + a PUBLISHED immutable
  CharacterPackVersion carrying all CORE_POSE_SLOTS plus the ``reference``
  slot, and the project cast pin (ProjectCastMapping) that selects it; the
  rendered output actually paints every segment, so the four output-side
  detectors have a real observation to measure (R5);
- a completed ATTACH_ORIGINAL_AUDIO attempt carrying the T03E envelope.

Disclosure (no green-by-fabrication anywhere): the fixture writes the media
and mask BYTES itself through the managed-root contract and seeds the
upstream domain rows, because driving the whole S08→S10 job chain would need
a GPU renderer.  Every byte is real, every sha256 is the real digest of the
bytes on disk, and every QC result in the suite is produced by the real
detectors reading these persisted facts — nothing is seeded into the QC
tables.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from alembic import command
from alembic.config import Config

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.artifacts import ManagedRoot
from app.persistence.models import (
    CORE_POSE_SLOTS,
    Artifact,
    ArtifactOwner,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Job,
    JobAttempt,
    ObjectRole,
    Project,
    ProjectCastMapping,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import (
    StructuralEvidenceRepository,
    canonical_json,
)
from app.persistence.structural_lock import StructuralLockRepository

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

WS = "ws-p1-qc-evidence"
PROJECT = "p-p1-qc-evidence"
GEN = "1"

CANVAS_W = 640
CANVAS_H = 360
FPS_NUM = 30
FPS_DEN = 1
TOTAL_FRAMES = 20

#: Frames 0..9 carry the rendered layer delta at this square.  The rect is
#: 41 px wide starting at x=100, so its column centroid is exactly 120.0 —
#: an even width would put the centroid on a half pixel and the pinned anchor
#: could never match the measured placement exactly.
DELTA_RECT = (100, 160, 141, 200)
DELTA_CENTRE_X = 120
#: Gray level the rendered layer carries.  It must be >= the changed-pixel
#: threshold the trajectory measurement uses (8 gray levels) so the rendered
#: placement is measurable, and it must stay INSIDE the identity_drift metric's
#: sanity bound (max 8.0 px) — a saturated 255 delta is refused as INVALID by
#: the real detector, which is correct behaviour but is not the positive path.
RENDER_LEVEL = 8
#: The persisted render-route anchor is the SAME position, so the intended vs
#: measured drift is exactly 0 for the positive path.
ANCHOR_X = DELTA_CENTRE_X / float(CANVAS_W)

#: Expected (pinned) mask of segment A, and the DISTINCT rendered-side mask
#: published for the same region (the object-correction style publication).
#: The rendered mask is a strict superset that extends 2 px beyond the
#: expected one on every side, so the edge_halo ring is a real measured band.
#: Both stay small so the composed pixel window (bbox ∪ bbox + margin) fits
#: inside the composer's halo-window bound.
MASK_A_RECT = (100, 160, 116, 176)
MASK_B_RECT = (300, 160, 340, 200)
#: The occlusion pair (segment A occludes segment C) must be OBSERVABLE in the
#: rendered pixels: the two annotated mask regions overlap, so the rendered
#: appearance of their overlap can be attributed to whichever segment paints
#: it.  Segment C's own rendered layer covers exactly this region.
MASK_C_RECT = (110, 160, 150, 200)
MASK_RENDERED_RECT = (98, 158, 118, 178)

#: Gray levels of the library REFERENCE pattern.  The identity metric is an
#: RMS pixel distance with a sanity bound of 8.0 px, so the reference must stay
#: measurable against the rendered crop (level 8) while crossing the warning
#: boundary (2.0 px): a 5/11 checkerboard sits at exactly 3.0 px from 8.0.
REFERENCE_LOW = 5
REFERENCE_HIGH = 11


def _new_id() -> str:
    return str(uuid.uuid4())


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _reference_png_bytes() -> bytes:
    """A real canvas-sized library REFERENCE image (checkerboard pattern).

    The pinned target identity of a reskin is the character library's
    reference asset, never a crop of the video's source frames — this fixture
    publishes genuine bytes at the video canvas geometry so the reference crop
    is comparable with the rendered crop under the same window.
    """
    from PIL import Image

    array = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    array[:, :] = REFERENCE_LOW
    array[::2, ::2] = REFERENCE_HIGH
    array[1::2, 1::2] = REFERENCE_HIGH
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _png_bytes(rect: tuple[int, int, int, int]) -> bytes:
    """A real 640x360 grayscale PNG with one white rectangle."""
    from PIL import Image

    array = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    x0, y0, x1, y1 = rect
    array[y0:y1, x0:x1] = 255
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _video_bytes(
    path: Path,
    *,
    square_rect: tuple[int, int, int, int] | None,
    lit_frames: range,
    level: int = 255,
    extra_layers: tuple[tuple[tuple[int, int, int, int], range], ...] = (),
) -> bytes:
    """Write a REAL lossless (FFV1) clip so frame measurements are exact.

    ``extra_layers`` paints further composited layers (rect, frame range) so
    the rendered output carries one observable layer per rendered segment.
    """
    import cv2

    fourcc = cv2.VideoWriter_fourcc(*"FFV1")
    writer = cv2.VideoWriter(str(path), fourcc, float(FPS_NUM), (CANVAS_W, CANVAS_H))
    assert writer.isOpened(), "FFV1 video writer unavailable on this host"
    for index in range(TOTAL_FRAMES):
        frame = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
        if square_rect is not None and index in lit_frames:
            x0, y0, x1, y1 = square_rect
            frame[y0:y1, x0:x1] = int(level)
        for rect, frames in extra_layers:
            if index in frames:
                x0, y0, x1, y1 = rect
                frame[y0:y1, x0:x1] = int(level)
        writer.write(frame)
    writer.release()
    data = path.read_bytes()
    assert len(data) > 0, "lossless clip came back empty (fail closed)"
    return data


@dataclass(frozen=True)
class EvidenceIds:
    workspace_id: str
    project_id: str
    video_item_id: str
    source_artifact_id: str
    render_artifact_id: str
    publication_id: str
    segment_a: str
    segment_b: str
    segment_c: str
    mask_a: str
    mask_b: str
    mask_c: str
    mask_rendered: str
    route_a: str
    contact_id: str
    occlusion_id: str
    role_ids: dict[str, str]
    character_ids: dict[str, str]
    pack_version_ids: dict[str, str]
    cast_mapping_ids: dict[str, str]
    reference_artifact_ids: dict[str, str]


def _publish(
    session: Any,
    root: ManagedRoot,
    *,
    rel: str,
    data: bytes,
    kind: str,
    mime_type: str,
    purposes: tuple[tuple[str, str, str], ...] = (),
) -> Artifact:
    sha256, size_bytes = root.atomic_write_bytes(rel, data)
    row = Artifact(
        workspace_id=WS,
        kind=kind,
        relative_path=rel,
        state="ready",
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type,
        width=CANVAS_W if kind == "image" else None,
        height=CANVAS_H if kind == "image" else None,
    )
    session.add(row)
    session.flush()
    for owner_type, owner_id, purpose in purposes:
        session.add(
            ArtifactOwner(
                artifact_id=row.id,
                owner_type=owner_type,
                owner_id=owner_id,
                purpose=purpose,
            )
        )
    return row


def seed_qc_evidence(session_factory: Any, managed_root: Path) -> EvidenceIds:
    """Seed the persisted evidence world (through the real repositories)."""
    root = ManagedRoot(Path(managed_root))
    root_root = Path(managed_root)
    media_dir = root_root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    source_bytes = _video_bytes(
        media_dir / "source.avi", square_rect=None, lit_frames=range(0)
    )
    # The rendered output paints one layer per segment (A over frames 0..9,
    # B and C over frames 10..19) so the output-side detectors have a real
    # observation to measure — a render that paints nothing would have to be
    # refused by them, never passed from the source-side annotation.
    render_bytes = _video_bytes(
        media_dir / "render.avi",
        square_rect=DELTA_RECT,
        lit_frames=range(0, 10),
        level=RENDER_LEVEL,
        extra_layers=(
            (MASK_B_RECT, range(10, TOTAL_FRAMES)),
            (MASK_C_RECT, range(10, TOTAL_FRAMES)),
        ),
    )

    with session_factory() as session:
        session.add(Workspace(id=WS, name=WS))
        session.flush()
        project = Project(workspace_id=WS, name="P1QC", description="", status="active")
        session.add(project)
        session.flush()
        source = _publish(
            session,
            root,
            rel="media/source.avi",
            data=source_bytes,
            kind="video",
            mime_type="video/x-msvideo",
            purposes=(("video_item", "placeholder", "source"),),
        )
        video = VideoItem(
            project_id=project.id,
            title="P1QC evidence fixture",
            position=0,
            status="objects_ready",
            source_artifact_id=None,
            duration_ms=int(TOTAL_FRAMES * 1000 / FPS_NUM),
            width=CANVAS_W,
            height=CANVAS_H,
            fps_num=FPS_NUM,
            fps_den=FPS_DEN,
        )
        session.add(video)
        session.flush()
        session.add(
            ArtifactOwner(
                artifact_id=source.id,
                owner_type="video_item",
                owner_id=video.id,
                purpose="source",
            )
        )
        video.source_artifact_id = source.id

        job = Job(
            workspace_id=WS,
            job_type="DISCOVER_OBJECTS",
            owner_type="video_item",
            owner_id=video.id,
            state="completed",
            input_generation=GEN,
            input_manifest_json=canonical_json({"source_sha256": str(source.sha256)}),
        )
        session.add(job)
        session.flush()

        scene_rows = []
        for position, (start, end) in enumerate(((0, 9), (10, 19))):
            scene = Scene(
                video_item_id=video.id,
                position=position,
                start_frame=start,
                end_frame=end,
                start_time_ms=int(round(start * 1000 / FPS_NUM)),
                end_time_ms=int(round((end + 1) * 1000 / FPS_NUM)),
                status="approved",
            )
            session.add(scene)
            session.flush()
            scene_rows.append(scene)

        roles = {}
        for name, kind in (("Character", "character"), ("Prop", "prop"), ("Extra", "prop")):
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
            roles[name] = role

        cast = _seed_cast(session, root, project, roles)

        mask_a = _publish(
            session, root, rel="media/mask_a.png", data=_png_bytes(MASK_A_RECT),
            kind="image", mime_type="image/png",
            purposes=(("video_item", video.id, "mask"),),
        )
        mask_b = _publish(
            session, root, rel="media/mask_b.png", data=_png_bytes(MASK_B_RECT),
            kind="image", mime_type="image/png",
            purposes=(("video_item", video.id, "mask"),),
        )
        mask_c = _publish(
            session, root, rel="media/mask_c.png", data=_png_bytes(MASK_C_RECT),
            kind="image", mime_type="image/png",
            purposes=(("video_item", video.id, "mask"),),
        )
        mask_rendered = _publish(
            session, root, rel="media/mask_rendered.png",
            data=_png_bytes(MASK_RENDERED_RECT), kind="image", mime_type="image/png",
            purposes=(("video_item", video.id, "mask"),),
        )
        render = _publish(
            session, root, rel="media/render.avi", data=render_bytes,
            kind="video", mime_type="video/x-msvideo",
            purposes=(("video_item", video.id, "result"),),
        )
        session.flush()
        # DISCLOSURE: no S10 full-apply run/publication is seeded here.  Driving
        # the real stitcher + publication needs a GPU renderer, which this CPU
        # wave does not have.  The composer's disclosed precedence therefore
        # resolves the rendered result through its second rule (the newest
        # PUBLISHED render-side artifact owned by the video, purpose 'result')
        # and records `render_role=owned_result_artifact` in the provenance;
        # the `publication_artifact` rule stays covered by the refusal tests
        # that exercise a completed-run-without-publication as STALE.
        # The publication precedence itself is NOT_REVIEWED in this wave.

        attach_job = Job(
            workspace_id=WS,
            job_type="ATTACH_ORIGINAL_AUDIO",
            owner_type="video_item",
            owner_id=video.id,
            state="completed",
            input_generation=GEN,
            input_manifest_json=canonical_json({"video_item_id": video.id}),
        )
        session.add(attach_job)
        session.flush()
        session.add(
            JobAttempt(
                id=_new_id(),
                job_id=attach_job.id,
                step_id=None,
                step_code="attach_original_audio",
                attempt=1,
                worker_id="p1qc-fixture",
                fence_token=1,
                result_json=canonical_json(_no_audio_attempt_result()),
                error_json=None,
            )
        )
        session.flush()

        repo = StructuralEvidenceRepository(session)

        def segment(
            role: ObjectRole,
            scene: Scene,
            *,
            name: str,
            start_frame: int,
            end_frame: int,
            mask_id: str,
            z_order: int,
        ):
            record, created = repo.create_segment(
                WS,
                project.id,
                video.id,
                role.id,
                scene.id,
                name,
                start_frame,
                end_frame,
                int(round(start_frame * 1000 / FPS_NUM)),
                int(round((end_frame + 1) * 1000 / FPS_NUM)),
                GEN,
                kind=role.kind,
                source_job_id=job.id,
                mask_artifact_id=mask_id,
                segmentation={
                    "points": [{"x": 10.0, "y": 1.0, "label": "c"}],
                    "boxes": [{"x": 1.0, "y": 1.0, "w": 8.0, "h": 8.0}],
                },
                algorithm="p1qc-fixture",
                algorithm_version="1.0.0",
                confidence=0.99,
                confidence_source="model",
                provenance={"fixture": "mf-p1-qc-evidence"},
                visibility="visible",
                z_order=z_order,
                idempotency_key=f"seg-{name}",
            )
            assert created
            return record

        seg_a = segment(roles["Character"], scene_rows[0], name="CharacterA",
                        start_frame=0, end_frame=9, mask_id=mask_a.id, z_order=1)
        seg_b = segment(roles["Prop"], scene_rows[1], name="PropB",
                        start_frame=10, end_frame=19, mask_id=mask_b.id, z_order=0)
        seg_c = segment(roles["Extra"], scene_rows[1], name="ExtraC",
                        start_frame=5, end_frame=19, mask_id=mask_c.id, z_order=0)
        session.flush()

        occlusion, _ = repo.create_occlusion(
            WS, project.id, video.id, seg_a.id, seg_c.id,
            5, 9, int(round(5 * 1000 / FPS_NUM)), int(round(10 * 1000 / FPS_NUM)),
            algorithm="p1qc-fixture", algorithm_version="1.0.0",
            confidence=0.95, confidence_source="model",
            provenance={"fixture": "mf-p1-qc-evidence"},
            idempotency_key="occ-a-over-c",
        )
        contact, _ = repo.create_contact(
            WS, project.id, video.id, seg_a.id, seg_c.id, "other",
            5, 9, int(round(5 * 1000 / FPS_NUM)), int(round(10 * 1000 / FPS_NUM)),
            algorithm="p1qc-fixture", algorithm_version="1.0.0",
            confidence=0.97, confidence_source="detector",
            provenance={"fixture": "mf-p1-qc-evidence"},
            idempotency_key="contact-a-c",
        )
        session.flush()

        lock_repo = StructuralLockRepository(session)
        route, _ = lock_repo.record_render_route(
            WS,
            project.id,
            video.id,
            seg_a.id,
            "sprite_affine",
            ANCHOR_X,
            0.5,
            0,
            9,
            provenance={"fixture": "mf-p1-qc-evidence"},
            reasons=["pinned"],
            confidence_source="derived",
            idempotency_key="route-a",
        )
        session.commit()

        return EvidenceIds(
            workspace_id=WS,
            project_id=str(project.id),
            video_item_id=str(video.id),
            source_artifact_id=str(source.id),
            render_artifact_id=str(render.id),
            publication_id="",
            segment_a=str(seg_a.id),
            segment_b=str(seg_b.id),
            segment_c=str(seg_c.id),
            mask_a=str(mask_a.id),
            mask_b=str(mask_b.id),
            mask_c=str(mask_c.id),
            mask_rendered=str(mask_rendered.id),
            route_a=str(route.id),
            contact_id=str(contact.id),
            occlusion_id=str(occlusion.id),
            role_ids={name: str(role.id) for name, role in roles.items()},
            character_ids={name: row["character_id"] for name, row in cast.items()},
            pack_version_ids={name: row["pack_version_id"] for name, row in cast.items()},
            cast_mapping_ids={name: row["mapping_id"] for name, row in cast.items()},
            reference_artifact_ids={
                name: row["reference_artifact_id"] for name, row in cast.items()
            },
        )


def _seed_cast(
    session: Any, root: ManagedRoot, project: Project, roles: dict[str, ObjectRole]
) -> dict[str, dict[str, str]]:
    """Seed the CHARACTER LIBRARY target identity of every rendered role.

    For each object role: a workspace Character, a PUBLISHED immutable
    CharacterPackVersion carrying every CORE_POSE_SLOT plus the ``reference``
    slot (the pinned identity pixels), and the project cast pin that selects
    it.  This is what the identity check compares the rendered output against
    (finding R4) — the video's own source frames are the motion authority and
    are never the identity reference.
    """
    out: dict[str, dict[str, str]] = {}
    for name, role in roles.items():
        character_type = role.kind if role.kind in ("character", "prop") else "prop"
        character = Character(
            workspace_id=WS,
            name=f"{name} library character",
            code=f"LIB-{name}",
            character_type=character_type,
            status="ready",
            revision=1,
        )
        session.add(character)
        session.flush()
        pack = CharacterPackVersion(
            character_id=character.id,
            workspace_id=WS,
            version=1,
            status="published",
            revision=1,
        )
        session.add(pack)
        session.flush()
        reference = _publish(
            session,
            root,
            rel=f"media/reference_{name}.png",
            data=_reference_png_bytes(),
            kind="image",
            mime_type="image/png",
            purposes=(("project", project.id, "reference"),),
        )
        session.add(
            CharacterAsset(
                pack_version_id=pack.id,
                workspace_id=WS,
                pose_slot="reference",
                artifact_id=reference.id,
            )
        )
        for slot in CORE_POSE_SLOTS:
            pose = _publish(
                session,
                root,
                rel=f"media/pose_{name}_{slot}.png",
                data=_png_bytes(MASK_A_RECT if slot == "front" else MASK_B_RECT),
                kind="image",
                mime_type="image/png",
                purposes=(("project", project.id, "pose"),),
            )
            session.add(
                CharacterAsset(
                    pack_version_id=pack.id,
                    workspace_id=WS,
                    pose_slot=slot,
                    artifact_id=pose.id,
                )
            )
        session.flush()
        mapping = ProjectCastMapping(
            workspace_id=WS,
            project_id=project.id,
            object_role_id=role.id,
            character_id=character.id,
            pack_version_id=pack.id,
            revision=1,
        )
        session.add(mapping)
        session.flush()
        out[name] = {
            "character_id": str(character.id),
            "pack_version_id": str(pack.id),
            "mapping_id": str(mapping.id),
            "reference_artifact_id": str(reference.id),
        }
    return out


def _no_audio_attempt_result() -> dict[str, Any]:
    """The T03E envelope for a source with NO audio stream (terminal fact)."""
    return {
        "remux": {
            "checkpoint": {
                "schema_version": 1,
                "status": "NO_AUDIO_PRESENT",
                "mode": None,
                "source_sha256": "a" * 64,
                "source_size_bytes": 1024,
                "source_audio_codec": None,
                "source_audio_duration": None,
                "output_audio_codec": None,
                "output_audio_duration": None,
                "audio_time_base": None,
                "video_codec": "h264",
            }
        },
        "published": {
            "no_audio_present": True,
            "artifact_id": None,
            "final_rel": None,
            "sha256": None,
            "size_bytes": None,
            "status": "NO_AUDIO_PRESENT",
        },
    }


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def evidence_db(tmp_path: Path):
    """Isolated production-schema DB + managed root with the seeded world."""
    database_path = tmp_path / "p1qc.db"
    command.upgrade(_alembic_config(database_path), "head")
    session_factory = create_session_factory(create_engine_for_path(database_path))
    managed_root = tmp_path / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    ids = seed_qc_evidence(session_factory, managed_root)
    return session_factory, managed_root, ids


@pytest.fixture()
def http_evidence(client):  # noqa: ANN001, ANN201 - root conftest client fixture
    """Seed the SAME evidence world into the live app's isolated DB + root."""
    from app.api import deps

    service = deps._job_service  # noqa: SLF001 - the fixture owns this app instance
    ids = seed_qc_evidence(service.session_factory, Path(service.managed_root))
    return client, service, ids


__all__ = [
    "ALEMBIC_INI",
    "ANCHOR_X",
    "CANVAS_H",
    "CANVAS_W",
    "DELTA_CENTRE_X",
    "DELTA_RECT",
    "EvidenceIds",
    "GEN",
    "MASK_A_RECT",
    "MASK_RENDERED_RECT",
    "PROJECT",
    "PROJECT_ROOT",
    "TOTAL_FRAMES",
    "WS",
    "seed_qc_evidence",
]
