"""MF-END-21 — rendered-output observations: acceptance + negative controls.

Row map (binary; micro-job map in the task TARGET.md):

* micro repro: module surface, the typed-code prefix, digest determinism, the
  sealed round-trip and the CI-engine honesty gate;
* MF-END-21.1 (decode + real segmentation on the OUTPUT): the mask of every
  observation is re-derived INDEPENDENTLY from the decoded output frame bytes
  and must digest-match; the frame map / canvas / fps / render SHA bindings
  are asserted; a wrong geometry, a short frame map and a span the output
  does not carry each refuse with their own code;
* MF-END-21.2 (match instance -> cast/role): matched through the pinned cast
  reference pixels under the measured bbox window, with temporal continuity
  (occlusion run + out-of-frame span keep ONE instance id); an ambiguous or
  unsupported match is a TYPED UNKNOWN (no guess);
* MF-END-21.3 (publish): the sealed payload is written atomically, registered
  as a managed artifact and read back through the QC-evidence reader; tampered
  bytes refuse; the source-side track digest binds the two sides;
* MF-END-21.4 (honesty): foreign output, source-as-output (same bytes),
  no-render-at-all, all-canvas, hollow, empty mask, and "a source-shaped mask
  the output does not paint" each refuse with their EXACT typed code.

Disclosure: the CI fixture media is synthesized in-process (64x48 lossless
FFV1 clips) and every fixture row is a labelled CI row — the REAL SAM2.1 run
on a real rendered output lives in the task evidence harness
(raw/mf21_real_output_observe.py), which is where a production claim comes
from.  No GPU job runs inside this suite.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
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
    ObjectRole,
    Project,
    ProjectCastMapping,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.structural_evidence import StructuralEvidenceRepository
from app.services import rendered_observations as ro
from app.services import source_role_tracks as srt
from app.services.qc_evidence import sources as src
from app.services.qc_evidence.errors import QcEvidenceError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MANIFEST_PATH = PROJECT_ROOT / "app" / "media_workflows" / "role_segmentation_v1.json"

WS = "ws-mf21"
GEN = "1"
CANVAS_W, CANVAS_H = 64, 48
FPS_NUM, FPS_DEN = 30, 1
FRAMES = 12
SRC_BG = 3
SRC_LEVEL_A = 120
SRC_LEVEL_B = 200
BOX_A = (8, 8, 24, 24)  # (x0, y0, x1, y1)
BOX_B = (40, 8, 56, 24)
ROLE_A = "ROLE-A"
ROLE_B = "PROP-B"


# ── helpers ──────────────────────────────────────────────────────────────────


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _png_bytes(rect: tuple[int, int, int, int] | None) -> bytes:
    """A real canvas-sized grayscale PNG (optionally one white rectangle)."""
    from PIL import Image

    array = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    if rect is not None:
        x0, y0, x1, y1 = rect
        array[y0:y1, x0:x1] = 255
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _uniform_png(level: int) -> bytes:
    """A real canvas-sized uniform grayscale PNG (a role reference pattern)."""
    from PIL import Image

    array = np.full((CANVAS_H, CANVAS_W), int(level), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _paint(frame: np.ndarray, box: tuple[int, int, int, int], level: int) -> None:
    x0, y0, x1, y1 = box
    frame[y0:y1, x0:x1] = int(level)


def _clip(
    path: Path,
    *,
    bg: int,
    levels: dict[tuple[int, int, int, int], int] | None = None,
    frames: int = FRAMES,
) -> bytes:
    """Write a REAL lossless (FFV1) clip so frame measurements are exact."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"FFV1")
    writer = cv2.VideoWriter(str(path), fourcc, float(FPS_NUM), (CANVAS_W, CANVAS_H))
    assert writer.isOpened(), "FFV1 video writer unavailable on this host"
    for _index in range(frames):
        frame = np.full((CANVAS_H, CANVAS_W, 3), int(bg), dtype=np.uint8)
        for box, level in (levels or {}).items():
            _paint(frame, box, level)
        writer.write(frame)
    writer.release()
    data = path.read_bytes()
    assert len(data) > 0, "lossless clip came back empty (fail closed)"
    return data


def _decode_clip(path: Path, *, color: bool = False) -> dict[int, np.ndarray]:
    """Independent decode of the output artifact (test-side ground truth)."""
    import cv2

    capture = cv2.VideoCapture(str(path))
    assert capture.isOpened(), f"clip unreadable: {path}"
    out: dict[int, np.ndarray] = {}
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        out[index] = frame if color else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        index += 1
    capture.release()
    return out


class CiLevelMaskSource:
    """CI fixture mask source: REAL cv2 segmentation of the fixture pixels.

    Documented deterministic rule (the same rule the shipped CI engine uses):
    inside the seed box the instance is the LARGEST connected component of the
    pixels that differ from the frame's own dominant level.  No pixels, no
    mask — ``present=False``.
    """

    engine_id = "contour"
    provenance = srt.PROVENANCE_FIXTURE
    probe = None
    candidates: dict[str, str] = {}
    inference_ran = False

    def sample(self, frame_index: int, seed: srt.RoleSeed, frame: np.ndarray):
        import cv2

        array = np.asarray(frame).astype(np.float64)
        if array.ndim == 3:
            array = array[:, :, 0]
        values, counts = np.unique(array, return_counts=True)
        level = float(values[int(np.argmax(counts))])
        painted = np.abs(array - level) > 0.0
        x, y, w, h = (int(v) for v in seed.box)
        bounded = np.zeros_like(painted)
        bounded[y : y + h, x : x + w] = painted[y : y + h, x : x + w]
        if not bounded.any():
            return srt.MaskSample(mask=None, method="contour:none", present=False)
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            bounded.astype(np.uint8), connectivity=8
        )
        best_label, best_area = 0, 0
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area > best_area:
                best_label, best_area = label, area
        return srt.MaskSample(
            mask=(labels == best_label), method="contour:largest_component"
        )


@dataclass
class ScriptedMaskEngine:
    """Labelled CI engine standing at the extractor boundary (like MF-END-19).

    ``answer`` maps ``frame_index -> np.ndarray | srt.MaskSample | None`` so a
    negative control can hand the REAL builder the exact degenerate claim it
    must refuse.
    """

    answer: dict[int, Any] = field(default_factory=dict)
    fallback: Any = None
    engine_id: str = "scripted_ci"
    provenance: str = ro.PROVENANCE_FIXTURE
    probe: dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=lambda: {"rule": "scripted_ci"})
    candidates: dict[str, str] = field(default_factory=dict)
    inference_ran: bool = False

    def sample(self, frame_index: int, segment: ro.RenderedSegment, frame: np.ndarray):
        answer = self.answer.get(int(frame_index), self.fallback)
        if isinstance(answer, srt.MaskSample) or answer is None:
            return answer
        return srt.MaskSample(mask=np.asarray(answer).astype(bool), method="scripted")


class _World:
    """Isolated production-schema DB + managed root with a seeded world."""

    def __init__(self, root: Path, name: str) -> None:
        self.managed = root / f"{name}-managed"
        self.managed.mkdir(parents=True, exist_ok=True)
        self.db = root / f"{name}.db"
        command.upgrade(_alembic_config(self.db), "head")
        self.factory = create_session_factory(create_engine_for_path(self.db))
        self.root = ManagedRoot(self.managed)
        self.ids: dict[str, Any] = {}


def _publish(
    world: _World,
    session: Any,
    *,
    rel: str,
    data: bytes,
    kind: str,
    mime_type: str,
    purposes: tuple[tuple[str, str, str], ...] = (),
) -> Artifact:
    sha256, size_bytes = world.root.atomic_write_bytes(rel, data)
    row = Artifact(
        workspace_id=WS,
        kind=kind,
        relative_path=rel,
        state="ready",
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type,
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


def _seed_scenes_and_roles(session: Any, project: Project, video: VideoItem) -> dict[str, Any]:
    scenes = []
    for position, (start, end) in enumerate(((0, 5), (6, 11))):
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
        scenes.append(scene)
    roles: dict[str, ObjectRole] = {}
    for name, kind in ((ROLE_A, "character"), (ROLE_B, "prop")):
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
    return {"scenes": scenes, "roles": roles}


def _seed_cast(
    world: _World,
    session: Any,
    project: Project,
    roles: dict[str, ObjectRole],
    reference_levels: dict[str, int],
) -> dict[str, dict[str, str]]:
    """The pinned library reference of every role (canvas-geometry PNG bytes)."""
    out: dict[str, dict[str, str]] = {}
    for name, role in roles.items():
        character = Character(
            workspace_id=WS,
            name=f"{name} library character",
            code=f"LIB-{name}",
            character_type="character" if role.kind == "character" else "prop",
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
            world,
            session,
            rel=f"media/reference_{name}.png",
            data=_uniform_png(reference_levels[name]),
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
                world,
                session,
                rel=f"media/pose_{name}_{slot}.png",
                data=_png_bytes(None),
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


def _seed_segments(
    session: Any,
    project: Project,
    video: VideoItem,
    roles: dict[str, ObjectRole],
    scenes: list[Any],
    masks: dict[str, Artifact],
    *,
    source_sha: str,
) -> dict[str, str]:
    repo = StructuralEvidenceRepository(session)
    job = Job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video.id,
        state="completed",
        input_generation=GEN,
        input_manifest_json=json.dumps({"source_sha256": source_sha}, sort_keys=True),
    )
    session.add(job)
    session.flush()
    out: dict[str, str] = {}
    specs = (
        (ROLE_A, scenes[0], "SegA", 0, 5, BOX_A),
        (ROLE_B, scenes[1], "SegB", 6, 11, BOX_B),
    )
    for name, scene, label, start, end, box in specs:
        role = roles[name]
        record, created = repo.create_segment(
            WS,
            project.id,
            video.id,
            role.id,
            scene.id,
            label,
            start,
            end,
            int(round(start * 1000 / FPS_NUM)),
            int(round((end + 1) * 1000 / FPS_NUM)),
            GEN,
            kind=role.kind,
            source_job_id=str(job.id),
            mask_artifact_id=str(masks[name].id),
            segmentation={
                "points": [],
                "boxes": [{"x": box[0], "y": box[1], "w": box[2], "h": box[3]}],
            },
            algorithm="mf21-fixture",
            algorithm_version="1.0.0",
            confidence=0.99,
            confidence_source="model",
            provenance={"fixture": "mf-end-21"},
            visibility="visible",
            z_order=1,
            idempotency_key=f"seg-{label}",
        )
        assert created
        out[name] = str(record.id)
    session.flush()
    return out


def _seed_world(
    world: _World,
    *,
    render_level_a: int = 60,
    render_level_b: int = 200,
    reference_levels: dict[str, int] | None = None,
    render_paints: bool = True,
    create_render: bool = True,
    render_is_source: bool = False,
    seed_cast: bool = True,
) -> _World:
    reference_levels = reference_levels or {ROLE_A: 60, ROLE_B: 200}
    source_bytes = _clip(
        world.managed / "src" / "source.avi",
        bg=SRC_BG,
        levels={BOX_A: SRC_LEVEL_A, BOX_B: SRC_LEVEL_B},
    )
    if render_is_source:
        render_bytes = source_bytes
    else:
        render_bytes = _clip(
            world.managed / "render" / "render.avi",
            bg=0,
            levels=(
                {BOX_A: render_level_a, BOX_B: render_level_b} if render_paints else {}
            ),
        )
    with world.factory() as session:
        session.add(Workspace(id=WS, name=WS))
        session.flush()
        project = Project(workspace_id=WS, name="MF21", description="", status="active")
        session.add(project)
        session.flush()
        source = _publish(
            world, session, rel="src/source.avi", data=source_bytes,
            kind="video", mime_type="video/x-msvideo",
        )
        video = VideoItem(
            project_id=project.id,
            title="MF21 output-observation fixture",
            position=0,
            status="objects_ready",
            source_artifact_id=None,
            duration_ms=int(FRAMES * 1000 / FPS_NUM),
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
        world.ids.update(
            {
                "project_id": str(project.id),
                "video_id": str(video.id),
                "source_artifact_id": str(source.id),
                "source_sha": str(source.sha256),
                "source_rel": "src/source.avi",
            }
        )
        if create_render:
            render = _publish(
                world, session, rel="render/render.avi", data=render_bytes,
                kind="video", mime_type="video/x-msvideo",
                purposes=(("video_item", video.id, "result"),),
            )
            sidecar = world.managed / "render" / "render.avi.evidence.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "decoded_frame_count": FRAMES,
                        "fps_num": FPS_NUM,
                        "fps_den": FPS_DEN,
                        "decoded_sha256": _sha(render_bytes),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            world.ids.update(
                {
                    "render_artifact_id": str(render.id),
                    "render_sha": str(render.sha256),
                    "render_rel": "render/render.avi",
                }
            )
        seeded = _seed_scenes_and_roles(session, project, video)
        roles, scenes = seeded["roles"], seeded["scenes"]
        masks = {
            ROLE_A: _publish(
                world, session, rel="media/mask_a.png", data=_png_bytes(BOX_A),
                kind="image", mime_type="image/png",
                purposes=(("video_item", video.id, "mask"),),
            ),
            ROLE_B: _publish(
                world, session, rel="media/mask_b.png", data=_png_bytes(BOX_B),
                kind="image", mime_type="image/png",
                purposes=(("video_item", video.id, "mask"),),
            ),
        }
        world.ids["segment_ids"] = _seed_segments(
            session,
            project,
            video,
            roles,
            scenes,
            masks,
            source_sha=world.ids["source_sha"],
        )
        world.ids["role_ids"] = {name: str(role.id) for name, role in roles.items()}
        if seed_cast:
            world.ids["cast"] = _seed_cast(world, session, project, roles, reference_levels)
        # a SECOND video item in the same workspace owns a render-like artifact:
        # the foreign-output control points at it.
        other = VideoItem(
            project_id=project.id,
            title="other video",
            position=1,
            status="objects_ready",
            source_artifact_id=None,
            duration_ms=int(FRAMES * 1000 / FPS_NUM),
            width=CANVAS_W,
            height=CANVAS_H,
            fps_num=FPS_NUM,
            fps_den=FPS_DEN,
        )
        session.add(other)
        session.flush()
        foreign = _publish(
            world, session, rel="render/foreign.avi", data=render_bytes,
            kind="video", mime_type="video/x-msvideo",
            purposes=(("video_item", other.id, "result"),),
        )
        world.ids["foreign_video_id"] = str(other.id)
        world.ids["foreign_artifact_id"] = str(foreign.id)
        session.commit()
    return world


_WORLDS: dict[str, _World] = {}


@pytest.fixture(scope="session")
def worlds(tmp_path_factory: pytest.TempPathFactory) -> dict[str, _World]:
    root = tmp_path_factory.mktemp("mf21")

    def get(key: str, **kwargs: Any) -> _World:
        if key not in _WORLDS:
            _WORLDS[key] = _seed_world(_World(root, key), **kwargs)
        return _WORLDS[key]

    return {"root": root, "get": get}  # type: ignore[dict-item]


# ── shared builders ──────────────────────────────────────────────────────────


def _source_tracks_digest(world: _World) -> str:
    """The sealed MF-END-12 source-side artifact of this fixture's source."""
    source_frames = _decode_clip(world.managed / world.ids["source_rel"], color=True)
    seed = srt.RoleSeed(
        ROLE_A, srt.ROLE_KIND_PERSON, (BOX_A[0], BOX_A[1], 16, 16), (0, FRAMES)
    )
    manifest = srt.load_workflow_manifest(MANIFEST_PATH)
    artifact = srt.build_role_tracks(
        source_sha256=world.ids["source_sha"],
        span=srt.SourceSpan(start_frame=0, end_frame_exclusive=FRAMES),
        frames=[source_frames[index] for index in range(FRAMES)],
        fps_rational=f"{FPS_NUM}/{FPS_DEN}",
        seeds=[seed],
        mask_source=CiLevelMaskSource(),
        manifest_sha256=_sha(MANIFEST_PATH.read_bytes()),
        manifest_version=manifest.version,
        production=False,
        strict=True,
    )
    assert srt.check_artifact(artifact) == ()
    return artifact.digest


def _output(world: _World, **overrides: Any) -> ro.RenderedOutput:
    payload: dict[str, Any] = {
        "artifact_id": world.ids["render_artifact_id"],
        "sha256": world.ids["render_sha"],
        "size_bytes": (world.managed / world.ids["render_rel"]).stat().st_size,
        "relative_path": world.ids["render_rel"],
        "role": "owned_result_artifact",
        "width": CANVAS_W,
        "height": CANVAS_H,
        "frame_count": FRAMES,
        "source_artifact_id": world.ids["source_artifact_id"],
        "source_sha256": world.ids["source_sha"],
        "producer": "fixture",
        "facts": {},
    }
    payload.update(overrides)
    return ro.RenderedOutput(**payload)


def _segments(world: _World) -> tuple[ro.RenderedSegment, ...]:
    return (
        ro.RenderedSegment(
            segment_id="seg-a",
            role_id=world.ids["role_ids"][ROLE_A],
            kind=srt.ROLE_KIND_PERSON,
            start_frame=0,
            end_frame=FRAMES,
            window=BOX_A,
        ),
        ro.RenderedSegment(
            segment_id="seg-b",
            role_id=world.ids["role_ids"][ROLE_B],
            kind=srt.ROLE_KIND_PROP,
            start_frame=0,
            end_frame=FRAMES,
            window=BOX_B,
        ),
    )


def _references(world: _World, levels: dict[str, int]) -> dict[str, ro.RenderedReference]:
    out: dict[str, ro.RenderedReference] = {}
    for name, level in levels.items():
        role_id = world.ids["role_ids"][name]
        out[role_id] = ro.RenderedReference(
            role_id=role_id,
            artifact_id=f"ref-{name}",
            sha256=_sha(_uniform_png(level)),
            frame=np.full((CANVAS_H, CANVAS_W), level, dtype=np.float64),
            pose_slot="reference",
        )
    return out


def _frames(world: _World) -> dict[int, np.ndarray]:
    return _decode_clip(world.managed / world.ids["render_rel"])


def _build(world: _World, **kwargs: Any) -> ro.RenderedObservationsArtifact:
    kwargs.setdefault("output", _output(world))
    kwargs.setdefault("frames", _frames(world))
    kwargs.setdefault("segments", _segments(world))
    kwargs.setdefault("engine", ro.LevelComponentMaskSource())
    kwargs.setdefault("fps_rational", f"{FPS_NUM}/{FPS_DEN}")
    return ro.build_rendered_observations(**kwargs)


def _refuses(code: str, fn: Any, /, *args: Any, **kwargs: Any) -> ro.RenderedObservationsError:
    with pytest.raises(ro.RenderedObservationsError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, f"expected {code}, got {exc.value.code}: {exc.value.detail}"
    return exc.value


# ── micro repro (21.0) ───────────────────────────────────────────────────────


def test_mf21_0_surface_and_codes_are_stable() -> None:
    assert ro.OBSERVATIONS_SCHEMA_VERSION == "mf.rendered_observations.v1"
    codes = [
        value
        for name, value in vars(ro).items()
        if name.startswith("CODE_") and isinstance(value, str)
    ]
    assert codes, "no typed codes exposed"
    assert all(code.startswith("RENDERED_OBSERVATIONS_") for code in codes)
    assert len(set(codes)) == len(codes), "duplicate refusal code"
    assert ro.CODE_VALID == "RENDERED_OBSERVATIONS_VALID"
    assert ro.MATCH_MATCHED == "matched" and ro.MATCH_UNKNOWN == "unknown"
    assert src.RENDERED_OBSERVATIONS_PURPOSE == "rendered_observations"


def test_mf21_0_build_is_deterministic_and_seals(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    first = _build(world)
    second = _build(world)
    assert first.digest == second.digest, "same bytes must seal to the same digest"
    assert len(first.digest) == 64
    assert ro.check_artifact(first) == ()
    assert ro.assert_artifact(first) is None
    payload = first.to_payload()
    round_trip = ro.RenderedObservationsArtifact.from_payload(payload)
    assert round_trip.digest == first.digest
    assert round_trip.to_payload() == payload
    bad = dict(payload)
    bad["schema_version"] = "mf.rendered_observations.v99"
    with pytest.raises(ro.RenderedObservationsError) as exc:
        ro.RenderedObservationsArtifact.from_payload(bad)
    assert exc.value.code == ro.CODE_VERSION_UNSUPPORTED
    tampered = dict(payload)
    tampered["fps_rational"] = "31/1"
    with pytest.raises(ro.RenderedObservationsError) as exc:
        ro.RenderedObservationsArtifact.from_payload(tampered)
    assert exc.value.code == ro.CODE_DIGEST_MISMATCH


def test_mf21_0_ci_engine_can_never_claim_production(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    engine = ro.LevelComponentMaskSource()
    assert engine.provenance == ro.PROVENANCE_FIXTURE
    _refuses(
        ro.CODE_FIXTURE_NOT_PRODUCTION,
        _build,
        world,
        engine=engine,
        production=True,
    )


# ── 21.1 — decode the output + real segmentation on OUTPUT pixels ────────────


def test_mf21_1_masks_come_from_the_output_pixels(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    artifact = _build(world)
    decoded = _frames(world)
    assert len(artifact.tracks) == 2
    role_a = world.ids["role_ids"][ROLE_A]
    track_a = next(track for track in artifact.tracks if track.role_id == role_a)
    assert len(track_a.observations) == FRAMES
    for observation in track_a.observations:
        frame = decoded[int(observation["frame"])]
        window = observation["seed_window"]
        x0, y0, x1, y1 = (int(v) for v in window)
        # independent recomputation of the claimed mask from the OUTPUT bytes
        painted = np.abs(frame.astype(np.float64) - float(np.bincount(frame.ravel()).argmax())) > 0
        expected = np.zeros_like(painted)
        expected[y0:y1, x0:x1] = painted[y0:y1, x0:x1]
        assert srt.mask_digest(expected) == observation["mask_digest"], (
            "the observation mask must be re-derivable from the decoded OUTPUT "
            "frame alone"
        )
        # the measured appearance is the OUTPUT's painted level, not the source's
        inside = frame[expected]
        assert int(inside.mean()) == 60
        assert int(inside.mean()) != SRC_LEVEL_A
        assert observation["support"]["separation"] == 60
        assert observation["bbox"] == [BOX_A[0], BOX_A[1], 16, 16]


def test_mf21_1_frame_map_sha_fps_and_canvas_bind(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    artifact = _build(world)
    decoded = _frames(world)
    assert artifact.frame_map_digest == ro.frame_map_sha256(decoded)
    assert artifact.output["sha256"] == world.ids["render_sha"]
    assert artifact.output["artifact_id"] == world.ids["render_artifact_id"]
    assert artifact.fps_rational == f"{FPS_NUM}/{FPS_DEN}"
    assert artifact.frame_size == (CANVAS_W, CANVAS_H)
    assert artifact.span == {"start_frame": 0, "end_frame_exclusive": FRAMES}
    all_frames = [int(item["frame"]) for track in artifact.tracks for item in track.observations]
    assert set(all_frames) <= set(decoded)
    assert artifact.output["frame_count"] == len(decoded) == FRAMES


def test_mf21_1_geometry_mismatch_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    frames = {
        index: np.full((CANVAS_H + 1, CANVAS_W), 0, dtype=np.uint8)
        for index in range(FRAMES)
    }
    _refuses(ro.CODE_GEOMETRY_MISMATCH, _build, world, frames=frames)


def test_mf21_1_short_frame_map_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    frames = _frames(world)
    frames.pop(FRAMES - 1)
    _refuses(ro.CODE_FRAME_MAP_INVALID, _build, world, frames=frames)


def test_mf21_1_wrong_frame_span_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    segments = list(_segments(world))
    segments[0] = ro.RenderedSegment(
        segment_id="seg-a-plus",
        role_id=segments[0].role_id,
        kind=segments[0].kind,
        start_frame=0,
        end_frame=FRAMES + 1,
        window=BOX_A,
    )
    _refuses(ro.CODE_FRAME_NOT_OBSERVED, _build, world, segments=tuple(segments))


def test_mf21_1_decode_matches_independent_decode(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    path = world.managed / world.ids["render_rel"]
    decoded = ro.decode_output_frame_map(path, list(range(FRAMES)))
    independent = _decode_clip(path)
    assert sorted(decoded) == sorted(independent)
    for index, frame in decoded.items():
        assert np.array_equal(frame, independent[index])
    assert ro.decode_output_frame_map(path, []) == {}
    _refuses(
        ro.CODE_FRAME_MAP_INVALID,
        ro.decode_output_frame_map,
        path,
        list(range(FRAMES)),
        max_frames=4,
    )


# ── 21.2 — match instance → cast/role (refs + temporal continuity) ───────────


def test_mf21_2_matched_through_reference_pixels(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    references = _references(world, {ROLE_A: 60, ROLE_B: 200})
    artifact = _build(world, references=references)
    for track in artifact.tracks:
        match = track.role_match
        assert match["state"] == ro.MATCH_MATCHED
        assert match["reason"] is None
        assert match["role_id"] == track.role_id
        assert match["agrees_with_declared_role"] is True
        assert match["distances"][track.role_id] == 0.0
        others = {k: v for k, v in match["distances"].items() if k != track.role_id}
        assert others and all(value > 0.0 for value in others.values())
        assert match["frame"] == int(track.observations[0]["frame"])


def test_mf21_2_ambiguous_match_is_typed_unknown(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("ambiguous")
    references = _references(world, {ROLE_A: 60, ROLE_B: 60})
    artifact = _build(world, references=references)
    track = next(
        track for track in artifact.tracks if track.role_id == world.ids["role_ids"][ROLE_A]
    )
    match = track.role_match
    assert match["state"] == ro.MATCH_UNKNOWN
    assert match["role_id"] is None
    assert match["reason"] == ro.UNKNOWN_REASON_AMBIGUOUS
    assert len(match["tied_role_ids"]) >= 2
    assert match["declared_role_id"] == track.role_id
    assert ro.check_artifact(artifact) == ()


def test_mf21_2_unsupported_match_is_typed_unknown(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("unmatched")
    references = _references(world, {ROLE_A: 200, ROLE_B: 220})
    artifact = _build(world, references=references)
    track = next(
        track for track in artifact.tracks if track.role_id == world.ids["role_ids"][ROLE_A]
    )
    match = track.role_match
    assert match["state"] == ro.MATCH_UNKNOWN
    assert match["reason"] == ro.UNKNOWN_REASON_UNMATCHED
    assert match["role_id"] is None
    assert match["best_distance"] > match["match_max_distance"]
    assert match["nearest_role_id"] in references


def test_mf21_2_missing_reference_is_typed_unknown(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    artifact = _build(world, references={})
    assert artifact.tracks, "the output still carries measurable masks"
    for track in artifact.tracks:
        assert track.role_match["state"] == ro.MATCH_UNKNOWN
        assert track.role_match["reason"] == ro.UNKNOWN_REASON_NO_REFERENCE
        assert track.role_match["role_id"] is None


def test_mf21_2_temporal_continuity_keeps_one_instance(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    decoded = _frames(world)
    segment = _segments(world)[0]
    shipped = ro.LevelComponentMaskSource()
    base = {index: shipped.sample(index, segment, decoded[index]) for index in sorted(decoded)}
    occluded = {
        index: srt.MaskSample(mask=None, method="ci:occluded", present=True)
        for index in (4, 5)
    }
    out_of_frame = {
        index: srt.MaskSample(mask=None, method="ci:left", present=False, out_of_frame=True)
        for index in (10, 11)
    }
    engine = ScriptedMaskEngine(answer=dict(base))
    engine.answer.update(occluded)
    engine.answer.update(out_of_frame)
    artifact = _build(world, engine=engine, segments=(segment,))
    assert len(artifact.tracks) == 1
    track = artifact.tracks[0]
    assert {item["instance_id"] for item in track.observations} == {track.instance_id}
    assert track.occlusion_runs == ({"start_frame": 4, "end_frame": 6},)
    assert track.out_of_frame_frames == (10, 11)
    assert track.trace_complete is False
    assert [int(item["frame"]) for item in track.observations] == [0, 1, 2, 3, 6, 7, 8, 9]
    gaps = ScriptedMaskEngine(answer=dict(base))
    gaps.answer[3] = None
    artifact_gaps = _build(world, engine=gaps, segments=(segment,))
    assert artifact_gaps.tracks[0].gap_frames == (3,)
    assert artifact_gaps.tracks[0].trace_complete is False


def test_mf21_2_no_trace_refused_or_recorded(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    empty = ScriptedMaskEngine(fallback=None)
    _refuses(
        ro.CODE_NO_TRACE,
        _build,
        world,
        engine=empty,
        segments=(_segments(world)[0],),
        strict=True,
    )
    artifact = _build(
        world, engine=empty, segments=(_segments(world)[0],), strict=False
    )
    assert artifact.tracks == ()
    assert artifact.refused_tracks[0].code == ro.CODE_NO_TRACE


# ── 21.3 — publish + read back ───────────────────────────────────────────────


def test_mf21_3_publish_and_read_back(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    artifact = _build(world)
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        published = ro.publish_rendered_observations(
            session,
            world.managed,
            workspace_id=WS,
            video_item_id=world.ids["video_id"],
            relative_path="qc/rendered_observations.json",
            artifact=artifact,
        )
        session.commit()
        evidence, loaded = ro.load_rendered_observations(session, world.managed, scope)
    assert loaded.digest == artifact.digest
    assert published["sha256"] == evidence.sha256
    on_disk = (world.managed / "qc" / "rendered_observations.json").read_bytes()
    assert _sha(on_disk) == published["sha256"]
    assert json.loads(on_disk.decode("utf-8"))["digest"] == artifact.digest
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        path = world.managed / "qc" / "rendered_observations.json"
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(QcEvidenceError) as exc:
            ro.load_rendered_observations(session, world.managed, scope)
        assert exc.value.code in {"QC_EVIDENCE_TAMPERED", "QC_EVIDENCE_MALFORMED"}
        path.write_bytes(on_disk)  # restore the fixture for later rows


def test_mf21_3_source_side_digest_binds_both_sides(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    source_digest = _source_tracks_digest(world)
    assert len(source_digest) == 64
    artifact = _build(world, source_tracks_digest=source_digest)
    assert artifact.source_tracks_digest == source_digest
    assert artifact.source_sha256 == world.ids["source_sha"]
    assert artifact.extra == {}, "the pure builder adds no comparison envelope"
    plain = _build(world)
    assert plain.source_tracks_digest is None


# ── 21.4 — honesty / negative controls ──────────────────────────────────────


def test_mf21_4_foreign_output_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        refusal = _refuses(
            ro.CODE_OUTPUT_FOREIGN,
            ro.resolve_rendered_output,
            session,
            world.managed,
            scope,
            output_artifact_id=world.ids["foreign_artifact_id"],
        )
    assert world.ids["foreign_video_id"] in refusal.detail


def test_mf21_4_source_returned_as_output_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("source-as-render", render_is_source=True)
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        _refuses(
            ro.CODE_OUTPUT_IS_SOURCE,
            ro.resolve_rendered_output,
            session,
            world.managed,
            scope,
            output_artifact_id=world.ids["render_artifact_id"],
        )
    _refuses(
        ro.CODE_OUTPUT_IS_SOURCE,
        _build,
        world,
        output=_output(world, sha256=world.ids["source_sha"]),
    )


def test_mf21_4_no_render_at_all_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("no-render", create_render=False, seed_cast=False)
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        _refuses(
            ro.CODE_OUTPUT_NOT_RENDER,
            ro.resolve_rendered_output,
            session,
            world.managed,
            scope,
        )


def test_mf21_4_all_canvas_and_hollow_and_empty_refused(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    frames = _frames(world)
    segments = (_segments(world)[0],)
    full = np.ones((CANVAS_H, CANVAS_W), dtype=bool)
    engine = ScriptedMaskEngine(fallback=full)
    _refuses(ro.CODE_MASK_ALL_CANVAS, _build, world, engine=engine, segments=segments)
    hollow = np.zeros((CANVAS_H, CANVAS_W), dtype=bool)
    x0, y0, x1, y1 = 12, 8, 42, 38
    hollow[y0:y1, x0] = True
    hollow[y0:y1, x1 - 1] = True
    hollow[y0, x0:x1] = True
    hollow[y1 - 1, x0:x1] = True
    engine = ScriptedMaskEngine(fallback=hollow)
    _refuses(ro.CODE_MASK_HOLLOW, _build, world, engine=engine, segments=segments)
    engine = ScriptedMaskEngine(fallback=np.zeros((CANVAS_H, CANVAS_W), dtype=bool))
    _refuses(ro.CODE_MASK_EMPTY, _build, world, engine=engine, segments=segments)
    assert (int(frames[0][BOX_A[1]:BOX_A[3], BOX_A[0]:BOX_A[2]].mean()),) == (60,)


def test_mf21_4_source_shaped_mask_not_painted_by_output_refused(
    worlds: dict[str, Any],
) -> None:
    """The intended source crop must never pass as an output observation."""
    world = worlds["get"]("unpainted", render_paints=False, seed_cast=False)
    source_frames = _decode_clip(world.managed / world.ids["source_rel"])
    seed = srt.RoleSeed(ROLE_A, srt.ROLE_KIND_PERSON, (BOX_A[0], BOX_A[1], 16, 16), (0, FRAMES))
    source_mask = CiLevelMaskSource().sample(0, seed, source_frames[0]).mask
    assert source_mask is not None and int(source_mask.sum()) == 16 * 16
    output_frames = _frames(world)
    assert int(output_frames[0][BOX_A[1]:BOX_A[3], BOX_A[0]:BOX_A[2]].mean()) == 0
    engine = ScriptedMaskEngine(fallback=source_mask)
    refusal = _refuses(
        ro.CODE_SUPPORT_AMBIGUOUS,
        _build,
        world,
        engine=engine,
        segments=(_segments(world)[0],),
    )
    assert "no pixel support" in refusal.detail
    # the same source mask on the source frame IS supported — the refusal is
    # about the OUTPUT pixels, not about the mask shape
    support = ro.obs.mask_support_separation(source_frames[0], source_mask)
    assert support["separation"] == SRC_LEVEL_A - SRC_BG


# ── 21.5 — end-to-end through the persisted evidence ─────────────────────────


def test_mf21_5_end_to_end_from_persisted_evidence(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        engine = ro.LevelComponentMaskSource()
        artifact = ro.observe_rendered_output(session, world.managed, scope, engine=engine)
        segments = ro.segments_from_evidence(session, world.managed, scope)
        references = ro.references_for_roles(
            session, world.managed, scope, [segment.role_id for segment in segments]
        )
        _refuses(
            ro.CODE_FIXTURE_NOT_PRODUCTION,
            ro.observe_rendered_output,
            session,
            world.managed,
            scope,
            engine=engine,
            production=True,
        )
    assert len(segments) == 2
    assert {segment.segment_id for segment in segments} == set(world.ids["segment_ids"].values())
    assert all(segment.window is not None for segment in segments)
    assert len(references) == 2
    assert artifact.output["artifact_id"] == world.ids["render_artifact_id"]
    assert artifact.source_sha256 == world.ids["source_sha"]
    assert artifact.output["source_sha256"] == world.ids["source_sha"]
    assert artifact.output["source_artifact_id"] == world.ids["source_artifact_id"]
    for track in artifact.tracks:
        assert track.role_match["state"] == ro.MATCH_MATCHED
        assert track.role_match["agrees_with_declared_role"] is True
        assert track.role_match["distances"][track.role_id] == 0.0
    assert artifact.extra["source_comparison"]["output_sha256"] == world.ids["render_sha"]
    assert artifact.extra["source_comparison"]["shared_frame_size"] == [CANVAS_W, CANVAS_H]
    assert ro.check_artifact(artifact) == ()
    _refuses(
        ro.CODE_FIXTURE_NOT_PRODUCTION,
        ro.observe_rendered_output,
        session,
        world.managed,
        scope,
        engine=engine,
        production=True,
    )


def test_mf21_5_resolve_reads_the_sidecar_frame_count(worlds: dict[str, Any]) -> None:
    world = worlds["get"]("main")
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        output = ro.resolve_rendered_output(session, world.managed, scope)
    assert output.role == "owned_result_artifact"
    assert output.frame_count == FRAMES
    assert output.sha256 == world.ids["render_sha"]
    assert output.source_sha256 == world.ids["source_sha"]
    assert output.width == CANVAS_W and output.height == CANVAS_H
    sidecar = world.managed / "render" / "render.avi.evidence.json"
    sidecar.unlink()
    with world.factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=WS,
            project_id=world.ids["project_id"],
            video_item_id=world.ids["video_id"],
            generation=GEN,
        )
        _refuses(
            ro.CODE_FRAME_MAP_INVALID,
            ro.resolve_rendered_output,
            session,
            world.managed,
            scope,
        )
    sidecar.write_text(
        json.dumps(
            {"decoded_frame_count": FRAMES, "fps_num": FPS_NUM, "fps_den": FPS_DEN},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
