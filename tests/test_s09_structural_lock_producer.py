"""S09-LOCK-PRODUCER-B01 — public StructuralLock producer acceptance tests.

E02 correction (R6): the previous 385-byte harness posted fake project/video
IDs with no source/evidence setup and expected HTTP 201 — an INVALID positive
criterion (a correct producer must DENY identities/evidence it cannot
derive).  This module is the corrected executable harness and separates:

(a) real route-registration coverage on the production app + typed denial
    for unknown identities (never a fake-201);
(b) the typed missing/stale/tampered/cross-workspace/foreign denial matrix
    with ZERO durable mutation on every rejected path;
(c) the valid public current-source/evidence SUCCESS path (isolated DB/env
    configured BEFORE the app import, REAL application lifespan, production
    ``get_db_session`` close-only semantics — routes commit explicitly).

The producer case matrix B01-A..H is frozen here on real migrated rows in a
temporary SQLite database.  Seeded fixtures are explicitly-labelled
ENGINEERING EVIDENCE built through ORM rows in the isolated temp DB; the
MAIN/real database is never targeted and no SQL seed is used against any
shared database.

R7 correction (F03): the producer must PROVE exact source timing from the
CURRENT source artifact BYTES (verified import probe + managed-root
checksum), never from defaults or a rounded duration.  The seeds therefore
build REAL deterministic media (ffmpeg testsrc2) at the managed root and
persist the SAME probe facts the verified import would (rational
r_frame_rate, duration, dimensions); the F03 block freezes the typed
zero-mutation denials (missing numerator/denominator, zero duration,
unproven/tampered bytes, VFR source, persisted-vs-probe mismatch) and the
exact-frame-count/CFR controls for 30/1 and 30000/1001.

Run: ``python -B -m pytest tests/test_s09_structural_lock_producer.py -q
-p no:cacheprovider``
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── ISOLATED RUNTIME ROOT, CONFIGURED BEFORE THE APP IMPORT (E02) ─────────
# The AppConfig singleton resolves MOTIONFORGE_ROOT at import time; set it to
# a fresh temp root FIRST so neither the imported app nor the lifespan can
# ever target the MAIN/real database.  MOTIONFORGE_DATABASE_URL is stripped.
# R7: when the runner provides an isolated runtime dir (S09B01_RUNTIME_DIR)
# the per-session root lives INSIDE it; otherwise a fresh temp root is used.
_RUNTIME_PARENT = os.environ.get("S09B01_RUNTIME_DIR")
if _RUNTIME_PARENT and Path(_RUNTIME_PARENT).is_dir():
    _RUNTIME_ROOT = Path(
        tempfile.mkdtemp(prefix="s09b01_", dir=_RUNTIME_PARENT)
    )
else:
    _RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="s09b01_"))
os.environ["MOTIONFORGE_ROOT"] = str(_RUNTIME_ROOT)
os.environ.setdefault("MOTIONFORGE_OUTPUT", str(_RUNTIME_ROOT / "output"))
os.environ.setdefault("MOTIONFORGE_MODELS", str(_RUNTIME_ROOT / "models"))
os.environ.pop("MOTIONFORGE_DATABASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.api import deps  # noqa: E402
from app.api.app import app as producer_app  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.artifacts import hash_file  # noqa: E402
from app.persistence.models import (  # noqa: E402
    ApplyCheckpoint,
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Job,
    ObjectRole,
    OccurrenceSegment,
    Project,
    ReskinConfig,
    Scene,
    SegmentRenderRoute,
    StructuralLockManifest,
    VideoItem,
    Workspace,
)
from app.services.ffmpeg_utils import find_ffmpeg  # noqa: E402
from app.services.video_import import probe_source  # noqa: E402
from app.workflow.analyze_orchestrator import (  # noqa: E402
    reset_analyze_orchestrator,
)
from app.workflow.job_service import JobService  # noqa: E402
from app.workflow.project_workflow import ProjectWorkflowService  # noqa: E402

WS = DEFAULT_WORKSPACE_ID
WS_B = "b01-other-workspace"
GEN = "1"
POLICY = "structural-thresholds-v1"
ROUTE_PATH = "/api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock"

VALID_PARAMS = {
    "anchor": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "fit_mode": "contain",
    "clip_mode": "asset_alpha",
    "offset": {"x": 0.0, "y": 0.0},
    "rotation_offset_deg": 0.0,
    "opacity": 1.0,
}


def _sha(n: int) -> str:
    return f"{n:064x}"


def _migrate(db: Path) -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")


class Graph:
    """Ids of one seeded engineering-evidence graph."""

    def __init__(self) -> None:
        self.project = ""
        self.video = ""
        self.video_b = ""
        self.source = ""
        self.source_sha = ""
        self.scene_ids: list[str] = []
        self.role = ""
        self.role_b = ""
        self.char = ""
        self.pack = ""
        self.config = ""
        self.segment = ""
        self.segment2 = ""
        self.mask = ""


def _encode_source_media(
    managed_root: Path,
    relative_path: str,
    *,
    rate: str,
    duration_s: float,
    width: int,
    height: int,
    vfr_select: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Generate REAL deterministic source media at the managed root and
    return ``(absolute path, verified probe payload)`` (R7 F03).

    Engineering evidence only: deterministic synthetic testsrc2 + ultrafast
    H.264 — but real bytes at the managed root, so the producer's exact
    timing proof runs against a genuine artifact.  ``rate`` is the ffmpeg
    rational text (``"30"``, ``"30000/1001"``); ``vfr_select`` produces a
    variable-frame-rate file for the VFR denial control.
    """
    target = Path(managed_root) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        find_ffmpeg(),
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate={rate}:duration={duration_s}",
    ]
    if vfr_select is not None:
        cmd += ["-vf", vfr_select, "-fps_mode", "vfr"]
    cmd += [
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        str(target),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    return target, probe_source(target)


def _seed_graph(
    session: Any,
    *,
    managed_root: Path | None = None,
    rate: str = "10",
    duration_s: float = 20.0,
    media_width: int = 256,
    media_height: int = 256,
    with_scenes: bool = True,
    with_segments: bool = True,
    with_configs: bool = True,
    scenes_count: int = 2,
) -> Graph:
    """Seed the isolated graph (engineering evidence; temp DB only).

    R7 F03: the source artifact is REAL media written at the managed root
    (ffmpeg testsrc2) and the persisted VideoItem timing facts are taken
    from the SAME verified import probe, exactly like a real import — so
    the producer's proof holds on the valid path and every timing denial is
    a genuine mutation of proven facts.
    """
    g = Graph()
    session.add(Workspace(id=WS, name=WS))
    session.add(Workspace(id=WS_B, name=WS_B))
    if managed_root is None:
        managed_root = Path(tempfile.mkdtemp(prefix="s09b01m_"))
    source_rel = "b01/src-b01.mp4"
    source_path, probe = _encode_source_media(
        managed_root,
        source_rel,
        rate=rate,
        duration_s=duration_s,
        width=media_width,
        height=media_height,
    )
    stream = probe["video_stream"]
    source_sha = hash_file(source_path)
    g.source_sha = source_sha
    source = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path=source_rel,
        state="ready",
        sha256=source_sha,
        size_bytes=source_path.stat().st_size,
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    g.source = str(source.id)

    project = Project(workspace_id=WS, name="B01")
    session.add(project)
    session.flush()
    g.project = str(project.id)
    video = VideoItem(
        project_id=project.id,
        title="V-B01",
        position=0,
        source_artifact_id=source.id,
        width=int(stream["width"]),
        height=int(stream["height"]),
        duration_ms=round(float(probe["container"]["duration_seconds"]) * 1000),
        fps_num=int(stream["r_frame_rate"]["num"]),
        fps_den=int(stream["r_frame_rate"]["den"]),
    )
    session.add(video)
    session.flush()
    g.video = str(video.id)

    # Backend generation authority: a completed DISCOVER_OBJECTS job whose
    # recorded source sha equals the video's current source artifact.
    session.add(
        Job(
            workspace_id=WS,
            job_type="DISCOVER_OBJECTS",
            owner_type="video_item",
            owner_id=video.id,
            state="completed",
            input_generation=GEN,
            input_manifest_json=json.dumps({"source_sha256": source_sha}),
        )
    )
    session.flush()

    if with_scenes:
        for position in range(scenes_count):
            scene = Scene(
                video_item_id=video.id,
                position=position,
                start_frame=position * 100,
                end_frame=position * 100 + 99,
                start_time_ms=position * 10000,
                end_time_ms=position * 10000 + 9900,
                status="pending",
            )
            session.add(scene)
            session.flush()
            g.scene_ids.append(str(scene.id))

    role = ObjectRole(
        workspace_id=WS,
        project_id=project.id,
        video_item_id=video.id,
        source_generation=GEN,
        name="Character",
        kind="character",
        status="confirmed",
    )
    session.add(role)
    session.flush()
    g.role = str(role.id)

    char = Character(workspace_id=WS, name="B01 Char", code="b01_char")
    session.add(char)
    session.flush()
    g.char = str(char.id)
    pack = CharacterPackVersion(
        workspace_id=WS, character_id=char.id, version=1, status="published"
    )
    session.add(pack)
    session.flush()
    g.pack = str(pack.id)
    # A publishable pack carries every CORE_POSE_SLOT (compatibility policy);
    # one ready image artifact serves all six slots (engineering evidence).
    pack_image = Artifact(
        workspace_id=WS,
        kind="image",
        relative_path="b01/pack-pose.png",
        state="ready",
        sha256=_sha(4),
        size_bytes=256,
    )
    session.add(pack_image)
    session.flush()
    for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
        session.add(
            CharacterAsset(
                workspace_id=WS,
                pack_version_id=pack.id,
                pose_slot=slot,
                artifact_id=pack_image.id,
            )
        )
    session.flush()
    if with_configs:
        config = ReskinConfig(
            workspace_id=WS,
            project_id=project.id,
            object_role_id=role.id,
            character_id=char.id,
            pack_version_id=pack.id,
            params_json=json.dumps(
                VALID_PARAMS, sort_keys=True, separators=(",", ":")
            ),
        )
        session.add(config)
        session.flush()
        g.config = str(config.id)

    if with_segments:
        mask = Artifact(
            workspace_id=WS,
            kind="image",
            relative_path="b01/seg1-mask.png",
            state="ready",
            sha256=_sha(3),
            size_bytes=128,
        )
        session.add(mask)
        session.flush()
        g.mask = str(mask.id)
        seg1 = OccurrenceSegment(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            logical_id="b01-logical-1",
            lineage_version=1,
            role_id=role.id,
            scene_id=g.scene_ids[0] if g.scene_ids else None,
            name="character-a",
            kind="character",
            start_frame=0,
            end_frame=99,
            start_time_ms=0,
            end_time_ms=9900,
            source_generation=GEN,
            prompt_json=json.dumps(
                {
                    "points": [],
                    "boxes": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}],
                }
            ),
            segmentation_json=json.dumps(
                {"points": [{"x": 0.2, "y": 0.2}], "boxes": []}
            ),
            mask_artifact_id=mask.id,
            confidence=0.9,
            confidence_source="model",
            z_order=0,
            visibility="visible",
        )
        session.add(seg1)
        session.flush()
        g.segment = str(seg1.id)
        seg2 = OccurrenceSegment(
            workspace_id=WS,
            project_id=project.id,
            video_item_id=video.id,
            logical_id="b01-logical-2",
            lineage_version=1,
            role_id=role.id,
            scene_id=g.scene_ids[1] if len(g.scene_ids) > 1 else None,
            name="character-b",
            kind="character",
            start_frame=100,
            end_frame=199,
            start_time_ms=10000,
            end_time_ms=19900,
            source_generation=GEN,
            prompt_json=json.dumps({"points": [{"x": 0.6, "y": 0.6}], "boxes": []}),
            confidence=0.9,
            confidence_source="model",
            z_order=1,
            visibility="visible",
        )
        session.add(seg2)
        session.flush()
        g.segment2 = str(seg2.id)
    session.commit()
    return g

def _counts(factory: Any) -> dict[str, int]:
    with factory() as session:
        return {
            "manifests": int(
                session.scalar(select(func.count()).select_from(StructuralLockManifest)) or 0
            ),
            "routes": int(
                session.scalar(select(func.count()).select_from(SegmentRenderRoute)) or 0
            ),
            "checkpoints": int(
                session.scalar(select(func.count()).select_from(ApplyCheckpoint)) or 0
            ),
            "configs": int(
                session.scalar(select(func.count()).select_from(ReskinConfig)) or 0
            ),
        }


def _post(
    client: TestClient,
    project: str,
    video: str,
    body: dict[str, Any] | None = None,
) -> Any:
    return client.post(
        f"/api/v2/projects/{project}/videos/{video}/structural-lock",
        json=body if body is not None else {},
    )


def _detail_code(response: Any) -> str:
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, dict), body
    return str(detail.get("code"))


@pytest.fixture()
def runtime(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Isolated runtime: fresh migrated temp DB + REAL application lifespan.

    The app runs with deps injected to the temp database/managed root and
    the production ``get_db_session`` (close-only) dependency, so route
    commits are genuinely explicit.
    """
    db = tmp_path / "b01-runtime.db"
    _migrate(db)
    engine = create_engine_for_path(db)
    factory = create_session_factory(engine)
    managed_root = tmp_path / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    service = JobService(factory, managed_root=managed_root)
    cfg = AppConfig(
        project_root=tmp_path,
        models_dir=tmp_path / "models",
        output_dir=tmp_path / "output",
    )
    saved = (
        deps._config,
        deps._job_service,
        deps._project_service,
        deps._video_service,
        getattr(deps, "_lifecycle_db", None),
        deps._project_wf,
    )
    deps._config = cfg
    deps._job_service = service
    deps._project_service = None
    deps._video_service = None
    deps._lifecycle_db = db
    deps._project_wf = ProjectWorkflowService(cfg)

    def seed(**kwargs: Any) -> Graph:
        with factory() as session:
            return _seed_graph(session, managed_root=managed_root, **kwargs)

    seed.managed_root = managed_root  # type: ignore[attr-defined]

    try:
        with TestClient(producer_app, raise_server_exceptions=False) as client:
            yield client, factory, seed
    finally:
        (
            deps._config,
            deps._job_service,
            deps._project_service,
            deps._video_service,
            deps._lifecycle_db,
            deps._project_wf,
        ) = saved
        reset_analyze_orchestrator()
        engine.dispose()


# ── (a) route registration + typed denial for unknown identities ──────────


def test_route_registration_and_unknown_identity_denied(runtime) -> None:  # type: ignore[no-untyped-def]
    """The production app registers ONE producer route; fake identities are
    DENIED typed (the removed fake-201 harness must never come back)."""
    client, factory, seed = runtime
    paths = producer_app.openapi().get("paths", {})
    producer_paths = {
        path: sorted(methods)
        for path, methods in paths.items()
        if "structural-lock" in path
    }
    assert producer_paths == {ROUTE_PATH: ["post"]}

    operation_ids = [
        str(op.get("operationId"))
        for ops in paths.values()
        for op in ops.values()
        if isinstance(op, dict) and op.get("operationId")
    ]
    assert len(operation_ids) == len(set(operation_ids))

    seed(with_scenes=False, with_segments=False)
    before = _counts(factory)
    response = _post(
        client, "project-micro", "video-micro", {"idempotency_key": "micro-red"}
    )
    assert response.status_code == 404, response.text
    assert _detail_code(response) == "STRUCTURAL_LOCK_UNKNOWN_PROJECT"
    assert response.status_code != 201
    assert _counts(factory) == before


# ── (b) typed missing/stale/tampered/cross-scope denials, zero mutation ───


def test_missing_evidence_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed(with_scenes=False, with_segments=False)
    before = _counts(factory)

    response = _post(client, graph.project, graph.video)
    assert response.status_code == 422
    assert _detail_code(response) == "STRUCTURAL_LOCK_EVIDENCE_MISSING"

    with factory() as session:
        session.add(
            Scene(
                video_item_id=graph.video,
                position=0,
                start_frame=0,
                end_frame=99,
                start_time_ms=0,
                end_time_ms=9900,
                status="pending",
            )
        )
        session.commit()
    second = _post(client, graph.project, graph.video)
    assert second.status_code == 422
    assert _detail_code(second) == "STRUCTURAL_LOCK_EVIDENCE_MISSING"
    assert _counts(factory) == before


def test_stale_expected_identity_conflicts_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed()
    before = _counts(factory)

    stale_gen = _post(
        client, graph.project, graph.video, {"expected_source_generation": "999"}
    )
    assert stale_gen.status_code == 409
    assert _detail_code(stale_gen) == "STRUCTURAL_LOCK_STALE_EXPECTED_GENERATION"

    stale_sha = _post(
        client, graph.project, graph.video, {"expected_source_sha256": _sha(9)}
    )
    assert stale_sha.status_code == 409
    assert _detail_code(stale_sha) == "STRUCTURAL_LOCK_STALE_EXPECTED_SOURCE_SHA256"
    assert _counts(factory) == before


def test_tampered_source_and_evidence_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed()
    before = _counts(factory)

    with factory() as session:
        source = session.get(Artifact, graph.source)
        source.sha256 = "A" * 64  # length-valid but not lowercase hex → tampered
        session.commit()
    tampered_source = _post(client, graph.project, graph.video)
    assert tampered_source.status_code == 422
    assert _detail_code(tampered_source) == "STRUCTURAL_LOCK_SOURCE_TAMPERED"

    with factory() as session:
        source = session.get(Artifact, graph.source)
        source.sha256 = graph.source_sha
        segment = session.get(OccurrenceSegment, graph.segment)
        segment.prompt_json = "{not-json"
        session.commit()
    corrupt_geometry = _post(client, graph.project, graph.video)
    assert corrupt_geometry.status_code == 422
    assert _detail_code(corrupt_geometry) == "STRUCTURAL_LOCK_EVIDENCE_TAMPERED"

    with factory() as session:
        segment = session.get(OccurrenceSegment, graph.segment)
        segment.prompt_json = '{"points": [], "boxes": [], "extra": NaN}'
        session.commit()
    non_finite = _post(client, graph.project, graph.video)
    assert non_finite.status_code == 422
    assert _detail_code(non_finite) == "STRUCTURAL_LOCK_EVIDENCE_TAMPERED"
    assert _counts(factory) == before


def test_cross_workspace_and_foreign_scope_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed()
    with factory() as session:
        foreign_project = Project(workspace_id=WS_B, name="Other")
        session.add(foreign_project)
        session.flush()
        foreign_video = VideoItem(
            project_id=foreign_project.id,
            title="V-other",
            position=0,
            width=64,
            height=64,
            duration_ms=1000,
            fps_num=10,
            fps_den=1,
        )
        session.add(foreign_video)
        session.flush()
        foreign_mask = Artifact(
            workspace_id=WS_B,
            kind="image",
            relative_path="b01/foreign-mask.png",
            state="ready",
            sha256=_sha(5),
            size_bytes=1,
        )
        session.add(foreign_mask)
        session.flush()
        segment = session.get(OccurrenceSegment, graph.segment)
        segment.mask_artifact_id = foreign_mask.id
        session.commit()
        foreign_project_id = str(foreign_project.id)
        foreign_video_id = str(foreign_video.id)
    before = _counts(factory)

    unknown_project = _post(client, foreign_project_id, foreign_video_id)
    assert unknown_project.status_code == 404
    assert _detail_code(unknown_project) == "STRUCTURAL_LOCK_UNKNOWN_PROJECT"

    unknown_video = _post(client, graph.project, foreign_video_id)
    assert unknown_video.status_code == 404
    assert _detail_code(unknown_video) == "STRUCTURAL_LOCK_UNKNOWN_VIDEO"

    cross_mask = _post(client, graph.project, graph.video)
    assert cross_mask.status_code == 422
    assert _detail_code(cross_mask) == "STRUCTURAL_LOCK_MASK_CROSS_SCOPE"
    assert _counts(factory) == before


def test_client_authority_and_filesystem_fields_rejected(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed()
    before = _counts(factory)
    for payload in (
        {"workspace_id": WS},
        {"relative_path": "C:/tmp/x.mp4"},
        {"route": "mesh_warp"},
        {"routes": {"segment": "mesh_warp"}},
        {"ready": True},
        {"manifest": {"frame_count": 1}},
        {"expected_source_generation": GEN, "workspace": WS},
    ):
        response = _post(client, graph.project, graph.video, payload)
        assert response.status_code == 422, payload
    assert _counts(factory) == before

    # The same endpoint still accepts the bounded request afterwards (the
    # rejected bodies left no partial state behind).
    accepted = _post(
        client, graph.project, graph.video, {"expected_source_generation": GEN}
    )
    assert accepted.status_code == 201, accepted.text
    assert _counts(factory)["manifests"] == before["manifests"] + 1

# ── (b cont.) route/policy/mapping denials + removal-only exclusion ──────


def test_unsupported_policy_route_and_ambiguity_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    import datetime as _dt

    client, factory, seed = runtime
    graph = seed()
    before = _counts(factory)

    bad_policy = _post(
        client, graph.project, graph.video, {"policy_version": "policy-x"}
    )
    assert bad_policy.status_code == 422
    assert _detail_code(bad_policy) == "STRUCTURAL_LOCK_UNSUPPORTED_POLICY"

    with factory() as session:
        session.add(
            SegmentRenderRoute(
                workspace_id=WS,
                project_id=graph.project,
                video_item_id=graph.video,
                occurrence_segment_id=graph.segment,
                route="mesh_warp",
                anchor_x=0.5,
                anchor_y=0.5,
                start_frame=0,
                end_frame=99,
                confidence=0.9,
                confidence_source="model",
                reasons_json="[]",
                created_at=_dt.datetime(2025, 1, 1),
            )
        )
        session.commit()
    before = _counts(factory)
    unsupported = _post(client, graph.project, graph.video)
    assert unsupported.status_code == 422
    assert _detail_code(unsupported) == "STRUCTURAL_LOCK_UNSUPPORTED_ROUTE"
    assert _counts(factory) == before

    # A NEWER executable decision becomes the current route again — the
    # unsupported history row alone never blocks the current graph.
    with factory() as session:
        session.add(
            SegmentRenderRoute(
                workspace_id=WS,
                project_id=graph.project,
                video_item_id=graph.video,
                occurrence_segment_id=graph.segment,
                route="sprite_affine",
                anchor_x=0.4,
                anchor_y=0.4,
                start_frame=0,
                end_frame=99,
                confidence=0.9,
                confidence_source="user",
                reasons_json="[]",
                created_at=_dt.datetime(2025, 1, 2),
            )
        )
        session.commit()
    previous = _counts(factory)
    accepted = _post(client, graph.project, graph.video)
    assert accepted.status_code == 201, accepted.text
    counts = _counts(factory)
    assert counts["manifests"] == previous["manifests"] + 1
    # only the missing segment decision is created; the persisted one is reused
    assert counts["routes"] == previous["routes"] + 1


def test_ambiguous_route_decisions_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    import datetime as _dt

    client, factory, seed = runtime
    graph = seed()
    instant = _dt.datetime(2025, 6, 1)
    with factory() as session:
        for route in ("sprite_affine", "pose_swap"):
            session.add(
                SegmentRenderRoute(
                    workspace_id=WS,
                    project_id=graph.project,
                    video_item_id=graph.video,
                    occurrence_segment_id=graph.segment,
                    route=route,
                    anchor_x=0.5,
                    anchor_y=0.5,
                    start_frame=0,
                    end_frame=99,
                    confidence=0.9,
                    confidence_source="model",
                    reasons_json="[]",
                    created_at=instant,
                )
            )
        session.commit()
    before = _counts(factory)
    response = _post(client, graph.project, graph.video)
    assert response.status_code == 422
    assert _detail_code(response) == "STRUCTURAL_LOCK_ROUTE_AMBIGUOUS"
    assert _counts(factory) == before


def test_role_mapping_prerequisite_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed(with_configs=False)
    before = _counts(factory)

    missing_mapping = _post(client, graph.project, graph.video)
    assert missing_mapping.status_code == 422
    assert _detail_code(missing_mapping) == "STRUCTURAL_LOCK_ROLE_MAPPING_MISSING"
    assert _counts(factory) == before

    # Config exists but the pack is not published/ready → still denied.
    with factory() as session:
        char = Character(workspace_id=WS, name="B01 Draft Char", code="b01_char_draft")
        session.add(char)
        session.flush()
        pack = CharacterPackVersion(
            workspace_id=WS, character_id=char.id, version=1, status="draft"
        )
        session.add(pack)
        session.flush()
        session.add(
            ReskinConfig(
                workspace_id=WS,
                project_id=graph.project,
                object_role_id=graph.role,
                character_id=char.id,
                pack_version_id=pack.id,
                params_json=json.dumps(
                    VALID_PARAMS, sort_keys=True, separators=(",", ":")
                ),
            )
        )
        session.commit()
    after_config = _counts(factory)
    unpublished = _post(client, graph.project, graph.video)
    assert unpublished.status_code == 422
    assert _detail_code(unpublished) == "STRUCTURAL_LOCK_ROLE_MAPPING_MISSING"
    assert _counts(factory) == after_config


def test_removal_only_only_graph_has_no_empty_success(runtime) -> None:  # type: ignore[no-untyped-def]
    """Removal-only roles are never replacement candidates: a graph whose
    only segment is a source_overlay cannot produce a lock (no empty
    manifest success)."""
    client, factory, seed = runtime
    graph = seed(with_segments=False, with_configs=False, scenes_count=1)
    with factory() as session:
        overlay_role = ObjectRole(
            workspace_id=WS,
            project_id=graph.project,
            video_item_id=graph.video,
            source_generation=GEN,
            name="Watermark",
            kind="source_overlay",
            status="confirmed",
        )
        session.add(overlay_role)
        session.flush()
        session.add(
            OccurrenceSegment(
                workspace_id=WS,
                project_id=graph.project,
                video_item_id=graph.video,
                logical_id="b01-logical-wm",
                lineage_version=1,
                role_id=overlay_role.id,
                scene_id=graph.scene_ids[0],
                name="watermark",
                kind="source_overlay",
                start_frame=0,
                end_frame=99,
                start_time_ms=0,
                end_time_ms=9900,
                source_generation=GEN,
                prompt_json=json.dumps(
                    {"points": [], "boxes": [{"x": 0.9, "y": 0.9, "w": 0.05, "h": 0.05}]}
                ),
                confidence=0.9,
                confidence_source="model",
                z_order=9,
                visibility="visible",
            )
        )
        session.commit()
    before = _counts(factory)
    response = _post(client, graph.project, graph.video)
    assert response.status_code == 422
    assert _detail_code(response) == "STRUCTURAL_LOCK_EVIDENCE_MISSING"
    assert _counts(factory) == before


# ── (c) valid current-source/evidence SUCCESS + B01-A..H matrix ───────────


def test_B01_A_success_current_source_evidence_graph(runtime) -> None:  # type: ignore[no-untyped-def]
    import hashlib

    from app.persistence.structural_evidence import canonical_json
    from app.persistence.structural_lock import StructuralLockRepository

    client, factory, seed = runtime
    graph = seed()
    # A removal-only role coexists in the current generation and must NOT
    # enter the manifest segments.
    with factory() as session:
        overlay_role = ObjectRole(
            workspace_id=WS,
            project_id=graph.project,
            video_item_id=graph.video,
            source_generation=GEN,
            name="Watermark",
            kind="source_overlay",
            status="confirmed",
        )
        session.add(overlay_role)
        session.flush()
        session.add(
            OccurrenceSegment(
                workspace_id=WS,
                project_id=graph.project,
                video_item_id=graph.video,
                logical_id="b01-logical-overlay",
                lineage_version=1,
                role_id=overlay_role.id,
                scene_id=graph.scene_ids[0],
                name="watermark",
                kind="source_overlay",
                start_frame=0,
                end_frame=99,
                start_time_ms=0,
                end_time_ms=9900,
                source_generation=GEN,
                prompt_json=json.dumps(
                    {"points": [], "boxes": [{"x": 0.9, "y": 0.9, "w": 0.05, "h": 0.05}]}
                ),
                confidence=0.9,
                confidence_source="model",
                z_order=9,
                visibility="visible",
            )
        )
        session.commit()

    response = _post(client, graph.project, graph.video, {"idempotency_key": "b01-a"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["status"] == "active"
    assert body["source_generation"] == GEN
    assert body["policy_version"] == POLICY
    assert body["version"] == 1
    assert body["segment_count"] == 2
    assert body["source_frame_count"] == 200
    assert (body["source_fps_num"], body["source_fps_den"]) == (10, 1)
    assert body["route_decisions_created"] == 2
    assert len(body["manifest_hash"]) == 64

    with factory() as session:
        row = session.get(StructuralLockManifest, body["manifest_id"])
        assert row is not None
        assert row.status == "active"
        assert row.source_generation == GEN
        assert row.manifest_hash == body["manifest_hash"]
        manifest = json.loads(row.manifest_json)
        # exact source/timebase derived from the video probe + source artifact
        assert manifest["frame_count"] == 200
        assert manifest["timebase"] == {
            "fps": 10.0,
            "time_base": "1/10",
            "start_time_ms": 0,
        }
        assert manifest["shot_order"] == graph.scene_ids
        seg_ids = [s["occurrence_segment_id"] for s in manifest["segments"]]
        assert seg_ids == [graph.segment, graph.segment2]
        for seg in manifest["segments"]:
            assert seg["route"] == "sprite_affine"
            assert seg["anchor"] == {"x": 0.5, "y": 0.5}

        # fingerprints recomputed INDEPENDENTLY from the persisted rows
        z_payload = {
            "segments": [
                {
                    "occurrence_segment_id": graph.segment,
                    "logical_id": "b01-logical-1",
                    "z_order": 0,
                    "visibility": "visible",
                    "start_frame": 0,
                    "end_frame": 99,
                },
                {
                    "occurrence_segment_id": graph.segment2,
                    "logical_id": "b01-logical-2",
                    "z_order": 1,
                    "visibility": "visible",
                    "start_frame": 100,
                    "end_frame": 199,
                },
            ],
            "occlusions": [],
        }
        assert manifest["fingerprints"]["z_order"] == hashlib.sha256(
            canonical_json(z_payload).encode("utf-8")
        ).hexdigest()
        assert manifest["fingerprints"]["contacts"] == hashlib.sha256(
            canonical_json({"contacts": []}).encode("utf-8")
        ).hexdigest()

        # exactly ONE active current lock for (video, generation)
        active = session.scalars(
            select(StructuralLockManifest).where(
                StructuralLockManifest.workspace_id == WS,
                StructuralLockManifest.video_item_id == graph.video,
                StructuralLockManifest.source_generation == GEN,
                StructuralLockManifest.status == "active",
            )
        ).all()
        assert len(active) == 1

        # route decisions persisted, bound to the manifest, deterministic keys
        decisions = session.scalars(
            select(SegmentRenderRoute).where(
                SegmentRenderRoute.video_item_id == graph.video
            )
        ).all()
        assert len(decisions) == 2
        for decision in decisions:
            assert decision.route == "sprite_affine"
            assert str(decision.structural_lock_manifest_id) == body["manifest_id"]
            assert decision.idempotency_key == (
                f"structural-lock-produce:{graph.video}:{GEN}:"
                f"{decision.occurrence_segment_id}"
            )

        # the current-manifest read agrees with the response
        current = StructuralLockRepository(session).get_current_manifest(
            WS, graph.project, graph.video, GEN
        )
        assert current.id == body["manifest_id"]
        assert current.manifest_hash_hex == body["manifest_hash"]


def test_B01_B_equivalent_replay_no_extra_rows(runtime) -> None:  # type: ignore[no-untyped-def]
    client, factory, seed = runtime
    graph = seed()
    first = _post(client, graph.project, graph.video, {"idempotency_key": "b01-b"})
    assert first.status_code == 201, first.text
    after_first = _counts(factory)

    second = _post(client, graph.project, graph.video, {"idempotency_key": "b01-b"})
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["created"] is False
    assert second_body["manifest_id"] == first.json()["manifest_id"]
    assert second_body["manifest_hash"] == first.json()["manifest_hash"]
    assert second_body["version"] == first.json()["version"]
    assert second_body["route_decisions_created"] == 0
    assert _counts(factory) == after_first

def test_B01_C_two_live_callers_exactly_one_creator(runtime) -> None:  # type: ignore[no-untyped-def]
    """Two live callers rendezvous at the actual creation point; exactly one
    creator and one coherent result (or a typed conflict, as the frozen
    contract dictates) — with an all-row proof afterwards."""
    from app.services.structural_lock_producer import (
        ProducerError,
        StructuralLockProducer,
    )

    _client, factory, seed = runtime
    graph = seed()
    barrier = threading.Barrier(2)
    results: dict[int, tuple[str, str, bool | None]] = {}

    def _caller(index: int) -> None:
        with factory() as session:
            producer = StructuralLockProducer(
                session, managed_root=seed.managed_root
            )
            barrier.wait(timeout=10)
            try:
                outcome = producer.produce(
                    WS,
                    graph.project,
                    graph.video,
                    idempotency_key="b01-c-race",
                )
                session.commit()
                results[index] = ("ok", outcome.record.id, outcome.created)
            except ProducerError as err:
                session.rollback()
                results[index] = ("err", err.code, None)

    threads = [
        threading.Thread(target=_caller, args=(index,)) for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2, results

    ok = [entry for entry in results.values() if entry[0] == "ok"]
    errors = [entry for entry in results.values() if entry[0] == "err"]
    assert len(ok) >= 1, results
    manifest_ids = {entry[1] for entry in ok}
    assert len(manifest_ids) == 1, results
    creators = [entry for entry in ok if entry[2] is True]
    assert len(creators) == 1, results
    for _kind, code, _created in errors:
        assert code == "STRUCTURAL_LOCK_CONFLICT"

    counts = _counts(factory)
    assert counts["manifests"] == 1
    assert counts["routes"] == 2
    with factory() as session:
        active = session.scalars(
            select(StructuralLockManifest).where(
                StructuralLockManifest.status == "active"
            )
        ).all()
        assert len(active) == 1
        decisions = session.scalars(select(SegmentRenderRoute)).all()
        assert {str(row.occurrence_segment_id) for row in decisions} == {
            graph.segment,
            graph.segment2,
        }


def test_B01_E_generation_change_and_supersession(runtime) -> None:  # type: ignore[no-untyped-def]
    """Current generation is explicitly validated; supersession archives the
    previous version (bytes unchanged); a stale key is a typed conflict; an
    OLD generation is never served as the current authority."""
    from app.persistence.structural_lock import StructuralLockRepository

    client, factory, seed = runtime
    graph = seed()
    first = _post(client, graph.project, graph.video, {"idempotency_key": "b01-e-v1"})
    assert first.status_code == 201, first.text
    first_body = first.json()
    with factory() as session:
        row = session.get(StructuralLockManifest, first_body["manifest_id"])
        hash_before = row.manifest_hash
        bytes_before = row.manifest_json
        assert hash_before == first_body["manifest_hash"]

    # Evidence changes: a third current-generation segment appears.
    with factory() as session:
        session.add(
            OccurrenceSegment(
                workspace_id=WS,
                project_id=graph.project,
                video_item_id=graph.video,
                logical_id="b01-logical-3",
                lineage_version=1,
                role_id=graph.role,
                scene_id=graph.scene_ids[1],
                name="character-c",
                kind="character",
                start_frame=200,
                end_frame=299,
                start_time_ms=20000,
                end_time_ms=29900,
                source_generation=GEN,
                prompt_json=json.dumps(
                    {"points": [{"x": 0.3, "y": 0.3}], "boxes": []}
                ),
                confidence=0.9,
                confidence_source="model",
                z_order=2,
                visibility="visible",
            )
        )
        session.commit()

    second = _post(client, graph.project, graph.video, {"idempotency_key": "b01-e-v2"})
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["version"] == 2
    assert second_body["segment_count"] == 3
    with factory() as session:
        old = session.get(StructuralLockManifest, first_body["manifest_id"])
        assert old.status == "superseded"
        assert str(old.superseded_by_id) == second_body["manifest_id"]
        assert old.manifest_hash == hash_before
        assert old.manifest_json == bytes_before
        current = StructuralLockRepository(session).get_current_manifest(
            WS, graph.project, graph.video, GEN
        )
        assert current.id == second_body["manifest_id"]

    # Stale-key replay after the evidence changed → typed conflict.
    stale = _post(client, graph.project, graph.video, {"idempotency_key": "b01-e-v1"})
    assert stale.status_code == 409
    assert _detail_code(stale) == "STRUCTURAL_LOCK_CONFLICT"

    # Source replaced + a NEW completed generation → the old lock is never
    # the current authority for the new generation (explicitly validated).
    # R7 F03: the replacement is a REAL second artifact at the managed root
    # whose persisted timing facts match the same verified probe profile.
    v2_path, _ = _encode_source_media(
        seed.managed_root,
        "b01/src-b01-v2.mp4",
        rate="10",
        duration_s=20.0,
        width=256,
        height=256,
    )
    v2_sha = hash_file(v2_path)
    with factory() as session:
        source_v2 = Artifact(
            workspace_id=WS,
            kind="video",
            relative_path="b01/src-b01-v2.mp4",
            state="ready",
            sha256=v2_sha,
            size_bytes=v2_path.stat().st_size,
            mime_type="video/mp4",
        )
        session.add(source_v2)
        session.flush()
        video = session.get(VideoItem, graph.video)
        video.source_artifact_id = source_v2.id
        session.add(
            Job(
                workspace_id=WS,
                job_type="DISCOVER_OBJECTS",
                owner_type="video_item",
                owner_id=graph.video,
                state="completed",
                input_generation="2",
                input_manifest_json=json.dumps({"source_sha256": v2_sha}),
            )
        )
        for index, (start, end) in enumerate(((0, 99), (100, 199))):
            session.add(
                OccurrenceSegment(
                    workspace_id=WS,
                    project_id=graph.project,
                    video_item_id=graph.video,
                    logical_id=f"b01-logical-g2-{index}",
                    lineage_version=1,
                    role_id=graph.role,
                    scene_id=graph.scene_ids[index],
                    name=f"character-g2-{index}",
                    kind="character",
                    start_frame=start,
                    end_frame=end,
                    start_time_ms=start * 100,
                    end_time_ms=end * 100 + 90,
                    source_generation="2",
                    prompt_json=json.dumps(
                        {"points": [{"x": 0.5, "y": 0.5}], "boxes": []}
                    ),
                    confidence=0.9,
                    confidence_source="model",
                    z_order=index,
                    visibility="visible",
                )
            )
        session.commit()

    stale_generation = _post(
        client, graph.project, graph.video, {"expected_source_generation": GEN}
    )
    assert stale_generation.status_code == 409
    assert _detail_code(stale_generation) == "STRUCTURAL_LOCK_STALE_EXPECTED_GENERATION"

    generation_two = _post(
        client, graph.project, graph.video, {"idempotency_key": "b01-e-gen2"}
    )
    assert generation_two.status_code == 201, generation_two.text
    assert generation_two.json()["source_generation"] == "2"
    assert generation_two.json()["version"] == 1
    with factory() as session:
        old = session.get(StructuralLockManifest, second_body["manifest_id"])
        assert old.status == "active"  # historical for ITS generation only
        current = StructuralLockRepository(session).get_current_manifest(
            WS, graph.project, graph.video, "2"
        )
        assert current.id == generation_two.json()["manifest_id"]
        assert current.id != second_body["manifest_id"]


def test_B01_F_pin_and_reapproval_full_apply_executable(runtime) -> None:  # type: ignore[no-untyped-def]
    """The existing ReskinConfig CAS pin accepts the produced lock (stale
    revision 409) and the real public S09 reapproval yields
    full_apply_executable=true with every prerequisite satisfied."""
    client, factory, seed = runtime
    graph = seed()
    produced = _post(client, graph.project, graph.video, {"idempotency_key": "b01-f"})
    assert produced.status_code == 201, produced.text
    manifest_id = produced.json()["manifest_id"]

    pin = client.patch(
        f"/api/v2/reskin-configs/{graph.config}",
        json={"revision": 1, "structural_lock_manifest_id": manifest_id},
    )
    assert pin.status_code == 200, pin.text
    pin_body = pin.json()
    assert pin_body["structural_lock_manifest_id"] == manifest_id
    assert pin_body["lock_policy_version"] == POLICY
    assert pin_body["revision"] == 2

    stale_pin = client.patch(
        f"/api/v2/reskin-configs/{graph.config}",
        json={"revision": 1, "structural_lock_manifest_id": manifest_id},
    )
    assert stale_pin.status_code == 409, stale_pin.text

    reapprove = client.post(
        "/api/v2/s09-approvals/reapprove",
        params={"workspace_id": WS},
        json={
            "reskin_config_id": graph.config,
            "expected_reskin_revision": 2,
            "pack_version_ids": [graph.pack],
            "idempotency_key": "b01-f-reapprove",
            "note": "B01 producer acceptance; engineering evidence",
        },
    )
    assert reapprove.status_code in (200, 201), reapprove.text
    checkpoint = reapprove.json()

    authority = client.get(
        f"/api/v2/s09-approvals/{checkpoint['id']}/full-apply-authority",
        params={"workspace_id": WS},
    )
    assert authority.status_code == 200, authority.text
    authority_body = authority.json()
    assert authority_body["verified"] is True
    eligibility = authority_body["eligibility"]
    assert eligibility["full_apply_executable"] is True, authority_body
    assert eligibility["reasons"] == []
    assert eligibility["unsupported_routes"] == []

    authority_block = authority_body["full_apply_authority"]
    assert authority_block["identity"]["source_generation"] == GEN
    assert authority_block["source"]["sha256"] == graph.source_sha
    assert authority_block["source"]["source_artifact_id"] == graph.source
    segments = authority_block["segments"]
    assert len(segments) == 2
    for segment in segments:
        assert segment["eligibility"]["executable"] is True, segment
    assert len(authority_block["role_mappings"]) == 1
    mapping = authority_block["role_mappings"][0]
    assert mapping["pack_status"] == "published"
    assert mapping["pack_version_id"] == graph.pack
    assert (
        authority_block["structural_lock"]["structural_lock_manifest_id"]
        == manifest_id
    )
    assert authority_block["structural_lock"]["policy_version"] == POLICY


def test_B01_H_transaction_failure_no_partial_state_then_retry(
    runtime, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A failure AFTER the manifest + route writes were staged rolls back the
    WHOLE transaction; the retry then succeeds deterministically."""
    from app.services.structural_lock_producer import StructuralLockProducer

    client, factory, seed = runtime
    graph = seed()

    def _boom(self: Any, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(StructuralLockProducer, "_ensure_default_decisions", _boom)
    before = _counts(factory)
    failed = _post(client, graph.project, graph.video, {"idempotency_key": "b01-h"})
    assert failed.status_code == 500, failed.text
    assert _counts(factory) == before
    monkeypatch.undo()

    retry = _post(client, graph.project, graph.video, {"idempotency_key": "b01-h"})
    assert retry.status_code == 201, retry.text
    assert retry.json()["created"] is True
    counts = _counts(factory)
    assert counts["manifests"] == before["manifests"] + 1
    assert counts["routes"] == before["routes"] + 2


def test_B01_H_read_failure_typed_denial(runtime, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A durable read failure is a typed denial with zero mutation."""
    import sqlalchemy.exc as sqlalchemy_exc

    from app.services.structural_lock_producer import StructuralLockProducer

    client, factory, seed = runtime
    graph = seed()
    before = _counts(factory)

    def _read_boom(self: Any, workspace_id: str, video_item_id: str) -> str:
        raise sqlalchemy_exc.OperationalError(
            "SELECT", {}, Exception("injected read failure")
        )

    monkeypatch.setattr(StructuralLockProducer, "_current_generation", _read_boom)
    failed = _post(client, graph.project, graph.video)
    assert failed.status_code == 422, failed.text
    assert _detail_code(failed) == "STRUCTURAL_LOCK_READ_ERROR"
    assert _counts(factory) == before


# ── R7 F03: exact source timing proof (denials + valid controls) ──────────


@pytest.mark.parametrize(
    "field,value",
    [("fps_num", None), ("fps_den", None), ("duration_ms", 0)],
)
def test_F03_missing_or_zero_source_timing_is_denied(runtime, field, value) -> None:  # type: ignore[no-untyped-def]
    """Reviewer-probe parity (adapted 1:1): fps_num=None / fps_den=None /
    duration_ms=0 → typed denial with zero durable mutation (no manifest,
    no route, no job).  The producer never defaults missing timing."""
    client, factory, seed = runtime
    graph = seed()
    with factory() as session:
        video = session.get(VideoItem, graph.video)
        setattr(video, field, value)
        session.commit()
    before = _counts(factory)
    response = _post(client, graph.project, graph.video)
    after = _counts(factory)
    assert response.status_code in (409, 422), response.text
    assert (
        _detail_code(response) == "STRUCTURAL_LOCK_SOURCE_TIMING_MISSING"
    ), response.text
    assert before == after
    assert after == {"manifests": 0, "routes": 0, "checkpoints": 0, "configs": 1}


def test_F03_unproven_or_tampered_source_bytes_denied(runtime) -> None:  # type: ignore[no-untyped-def]
    """Bytes missing or no longer matching the recorded checksum are a
    typed denial; restoring the EXACT bytes restores the valid path."""
    client, factory, seed = runtime
    graph = seed()
    path = seed.managed_root / "b01/src-b01.mp4"
    original = path.read_bytes()
    before = _counts(factory)

    path.unlink()
    missing = _post(client, graph.project, graph.video)
    assert missing.status_code == 422
    assert _detail_code(missing) == "STRUCTURAL_LOCK_SOURCE_TIMING_UNPROVEN"
    assert _counts(factory) == before

    path.write_bytes(original + b"tamper")
    tampered = _post(client, graph.project, graph.video)
    assert tampered.status_code == 422
    assert _detail_code(tampered) == "STRUCTURAL_LOCK_SOURCE_TIMING_UNPROVEN"
    assert _counts(factory) == before

    path.write_bytes(original)
    restored = _post(client, graph.project, graph.video)
    assert restored.status_code == 201, restored.text
    assert _counts(factory) == {**before, "manifests": 1, "routes": 2}


def test_F03_persisted_timing_mismatch_denied(runtime) -> None:  # type: ignore[no-untyped-def]
    """Persisted facts that disagree with the exact probe (rational FPS or
    frame-exact duration) are typed zero-mutation denials."""
    client, factory, seed = runtime
    graph = seed()
    before = _counts(factory)

    with factory() as session:
        video = session.get(VideoItem, graph.video)
        video.fps_num = 25  # the file is 10/1 → persisted disagrees
        session.commit()
    wrong_fps = _post(client, graph.project, graph.video)
    assert wrong_fps.status_code == 422
    assert _detail_code(wrong_fps) == "STRUCTURAL_LOCK_SOURCE_TIMING_MISMATCH"

    with factory() as session:
        video = session.get(VideoItem, graph.video)
        video.fps_num = 10
        video.duration_ms = 20001  # off-by-one ms is not the exact timing
        session.commit()
    wrong_duration = _post(client, graph.project, graph.video)
    assert wrong_duration.status_code == 422
    assert (
        _detail_code(wrong_duration) == "STRUCTURAL_LOCK_SOURCE_TIMING_MISMATCH"
    )
    assert _counts(factory) == before


def test_F03_vfr_source_denied_typed(runtime) -> None:  # type: ignore[no-untyped-def]
    """A VFR source (r_frame_rate != avg_frame_rate) is refused even when
    every persisted fact matches the probed rational — frame-exact locking
    needs CFR."""
    client, factory, seed = runtime
    graph = seed()
    vfr_path, vfr_probe = _encode_source_media(
        seed.managed_root,
        "b01/src-b01.mp4",
        rate="30",
        duration_s=1.0,
        width=256,
        height=256,
        vfr_select="select='not(mod(n,3))'",
    )
    stream = vfr_probe["video_stream"]
    assert stream["fps_classification"] == "VFR"
    vfr_sha = hash_file(vfr_path)
    with factory() as session:
        source = session.get(Artifact, graph.source)
        source.sha256 = vfr_sha
        source.size_bytes = vfr_path.stat().st_size
        video = session.get(VideoItem, graph.video)
        video.fps_num = int(stream["r_frame_rate"]["num"])
        video.fps_den = int(stream["r_frame_rate"]["den"])
        video.duration_ms = round(
            float(vfr_probe["container"]["duration_seconds"]) * 1000
        )
        job = session.scalars(
            select(Job).where(Job.owner_id == graph.video)
        ).first()
        assert job is not None
        job.input_manifest_json = json.dumps({"source_sha256": vfr_sha})
        session.commit()
    before = _counts(factory)
    response = _post(client, graph.project, graph.video)
    assert response.status_code == 422, response.text
    assert _detail_code(response) == "STRUCTURAL_LOCK_SOURCE_VFR"
    assert _counts(factory) == before


@pytest.mark.parametrize(
    "rate,duration_s,fps_pair,frame_count,time_base",
    [
        ("30", 1.0, (30, 1), 30, "1/30"),
        ("30000/1001", 1.001, (30000, 1001), 30, "1001/30000"),
    ],
)
def test_F03_valid_rational_control_exact_count_and_cfr(  # type: ignore[no-untyped-def]
    runtime, rate, duration_s, fps_pair, frame_count, time_base
) -> None:
    """Known valid 30/1 and 30000/1001 CFR sources produce the EXACT
    container frame count + exact rational timebase — never a default
    30fps/denominator-1 route or a rounded duration estimate."""
    client, factory, seed = runtime
    graph = seed(
        rate=rate, duration_s=duration_s, media_width=64, media_height=64
    )
    response = _post(
        client,
        graph.project,
        graph.video,
        {"idempotency_key": f"f03-{fps_pair[0]}-{fps_pair[1]}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Exactness: a FRESH independent probe of the very same bytes.
    fresh = probe_source(seed.managed_root / "b01/src-b01.mp4")
    exact_frames = int(fresh["video_stream"]["nb_frames"])
    assert body["source_frame_count"] == exact_frames == frame_count
    assert (body["source_fps_num"], body["source_fps_den"]) == fps_pair
    with factory() as session:
        row = session.get(StructuralLockManifest, body["manifest_id"])
        manifest = json.loads(row.manifest_json)
        assert manifest["frame_count"] == exact_frames
        assert manifest["timebase"]["time_base"] == time_base
        assert manifest["timebase"]["fps"] == fps_pair[0] / fps_pair[1]


@pytest.mark.parametrize("field", ["fps_num", "fps_den"])
def test_F03_database_rejects_zero_rational_components(runtime, field) -> None:  # type: ignore[no-untyped-def]
    """Positive control (reviewer parity): the DB already rejects zero
    rational components — retained as-is, nothing to fix there."""
    from sqlalchemy.exc import IntegrityError

    _client, factory, seed = runtime
    graph = seed()
    with factory() as session:
        video = session.get(VideoItem, graph.video)
        setattr(video, field, 0)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
