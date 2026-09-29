"""MF-END-15 — shot anchor job + input readiness (acceptance + negative controls).

Row map (binary):
* micro repro: the two modules import; ``register_api_handlers`` registers the
  ``shot_anchor_run`` job type WITH its fail-closed output validator; the
  default engine factory constructs the REAL Comfy adapter door;
* 15.1 resolution: published pack/view artifacts resolve; masks (by kind AND by
  real single-channel image mode), unpublished drafts, missing digests and
  declared-digest mismatches are typed refusals;
* 15.2 durable run: a scripted engine at the ENGINE boundary produces real
  bytes; the accepted manifest binds source + cast + anchor + graph hashes and
  the engine receipt, written through the managed root; the worker's own
  completion gate re-validates the manifest on disk; the REAL adapter refuses
  fail-closed when its pinned engine is unavailable (engine code surfaced);
* 15.3 input gate: coverage / contact / pose / camera / reference_hashes rows
  pass and fail exactly as specified; warnings never satisfy a row and never
  auto-accept; blocked readiness STOPS the run before the engine is called;
* 15.4 invalidation + video gate: missing / rejected / STALE / tampered anchors
  each refuse the video submit with their typed code; an accepted + current
  anchor unblocks it;
* job identity: submitting the same request twice converges on ONE durable Job
  (active and completed), rows proof; the shared job API (``JobService.get_job``
  → ``job_response``) reads the anchor job's status.

No GPU, no network, no real ComfyUI server here: the engine boundary is
scripted (CI fixture, labelled) while the production door is asserted to be the
real adapter class.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import func, select

from app.api.helpers import job_response
from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import Job, Workspace
from app.schemas.shot_reskin import (
    EngineArtifactOutput,
    EngineDecodedFacts,
    EngineOutputBinding,
    ShotEngineError,
    ShotExecutionRecord,
)
from app.services import shot_input_readiness as sread
from app.workflow import job_handlers as jh
from app.workflow import shot_anchor_jobs as sa
from app.workflow.job_service import JobService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
GRAPH_PATH = PROJECT_ROOT / "app" / "media_workflows" / "shot_anchor_v1.json"
#: the delivered MF-END-14 graph — the SAME bytes the accepted run used.
GRAPH_SHA = "e02574f799cfac6477be455aa18ff68e02f5ba5ed34c2651dba55d8496f266c6"

#: REAL measured hashes from the accepted proof (MF-END-13/14 evidence).
SOURCE_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"
KEYFRAME_SHA = "3f0d090a9c022fe136542c9f017b1f7cde40b1f79e80b92541846ed0e0a9c8c0"
REF_P1_SHA = "a2ad4db98ac733c969260d052f35e737c37eef664b1b36d5a6fd9a7254006821"
REF_P3_SHA = "49e99094d802495dd92e1dbab87125806efcb077f0be37125738b7218a63096f"
EXTRA_P1_SHA = hashlib.sha256(b"mf15-second-view-p1").hexdigest()
EXTRA_P2_SHA = hashlib.sha256(b"mf15-second-view-p2").hexdigest()
MODEL_SHA = "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6"


def _hex64(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _write_png(path: Path, *, mode: str = "RGB", size: tuple[int, int] = (64, 64)) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    color: Any = (32, 64, 96) if mode == "RGB" else 128
    Image.new(mode, size, color).save(path)
    return sha_of(path)


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── CI engine double (the engine boundary; NOT the production door) ──────────


class ScriptedAnchorEngine:
    """CI fixture: writes real PNG bytes, returns a REAL ``ShotExecutionRecord``."""

    def __init__(
        self,
        managed_root: Path,
        *,
        outcome: str = "completed",
        prompt_id: str = "pid-anchor-0001",
        wall: float = 1.25,
        vram: int = 11000,
        raise_engine_error: Any | None = None,
    ) -> None:
        self.managed_root = Path(managed_root)
        self.outcome = outcome
        self.prompt_id = prompt_id
        self.wall = wall
        self.vram = vram
        self.raise_engine_error = raise_engine_error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def run_shot(self, binding: Any, *, graph: dict, terminal_outputs: Any = None,
                 expected_artifact_hashes: Any = None, shot_id: str = "",
                 params: Any = None, decoded_facts: Any = None) -> ShotExecutionRecord:
        self.calls.append({
            "binding": binding,
            "graph_nodes": len(graph),
            "terminal_outputs": terminal_outputs,
            "shot_id": shot_id,
        })
        if self.raise_engine_error is not None:
            raise self.raise_engine_error
        rel = (f"media_engine/comfy_shot_engine/stage/"
               f"{binding.identity.attempt_id}/{shot_id or 'shot'}.png")
        target = self.managed_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (10, 20, 30)).save(target)
        sha = sha_of(target)
        if self.outcome != "completed":
            return ShotExecutionRecord(
                execution_backend="comfy_shot_engine",
                capability=binding.capability,
                outcome="failed",
                input=binding,
                error=ShotEngineError(code="MF_COMFY_OOM", message="scripted failure",
                                      retryable=True),
            )
        output = EngineOutputBinding(
            prompt_id=self.prompt_id,
            owner_session="test-host",
            graph_sha256_server=binding.graph.workflow_hash,
            artifacts=(
                EngineArtifactOutput(
                    artifact_id=f"{binding.identity.attempt_id}:SAVE:{shot_id}.png",
                    kind="image",
                    media_type="image/png",
                    sha256=sha,
                    store_relative_path=rel,
                    size_bytes=target.stat().st_size,
                    publishable=True,
                    server_output_type="output",
                ),
            ),
            decoded=EngineDecodedFacts(decoded_frames=1, first_pts_ticks=0,
                                       timebase="1/1", mapping=None),
            audio=binding.output_contract.audio,
            server_side_wall_s=self.wall,
            vram_peak_mib=self.vram,
        )
        return ShotExecutionRecord(
            execution_backend="comfy_shot_engine",
            capability=binding.capability,
            outcome="completed",
            input=binding,
            output=output,
        )

    def close(self) -> None:
        self.closed = True


# ── request builder (real graph bytes + real measured hashes) ────────────────


def build_request(tmp_path: Path, *, contact_state: str = "measured",
                  camera: bool = True, second_views: bool = True,
                  staged_override: dict | None = None,
                  required_views: dict | None = None) -> dict[str, Any]:
    managed = tmp_path / "managed"
    staged: dict[str, dict[str, str]] = {}
    for name in ("keyframe", "ref_p1", "ref_p3"):
        rel = f"inputs/{name}.png"
        sha = _write_png(managed / rel)
        staged[name] = {"relative_path": rel, "sha256": sha}
    cast_entries = [
        {"role": "BOOK-P1", "character_id": "cast-boy-hacker",
         "pack_version_id": "demo-packversion-r28", "key": "front@BOOK-P1",
         "view": "front", "artifact_id": "artifact.ref.p1.front",
         "sha256": staged["ref_p1"]["sha256"], "published": True, "kind": "artwork",
         "mode": "RGB", "store_relative_path": "inputs/ref_p1.png"},
        {"role": "BOOK-P3", "character_id": "cast-gau-nau",
         "pack_version_id": "demo-packversion-r28", "key": "back@BOOK-P3",
         "view": "back", "artifact_id": "artifact.ref.p3.back",
         "sha256": staged["ref_p3"]["sha256"], "published": True, "kind": "artwork",
         "mode": "RGB", "store_relative_path": "inputs/ref_p3.png"},
    ]
    if second_views:
        cast_entries += [
            {"role": "BOOK-P1", "character_id": "cast-boy-hacker",
             "pack_version_id": "demo-packversion-r28", "key": "three_quarter@BOOK-P1",
             "view": "three_quarter", "artifact_id": "artifact.ref.p1.three_quarter",
             "sha256": EXTRA_P1_SHA, "published": True, "kind": "artwork", "mode": "RGB"},
            {"role": "BOOK-P3", "character_id": "cast-gau-nau",
             "pack_version_id": "demo-packversion-r28",
             "key": "three_quarter@BOOK-P3", "view": "three_quarter",
             "artifact_id": "artifact.ref.p3.three_quarter", "sha256": EXTRA_P2_SHA,
             "published": True, "kind": "artwork", "mode": "RGB"},
        ]
    manifest_items = {
        "BOOK-P1": [
            {"key": "front@BOOK-P1", "view": "front",
             "artifact": {"artifact_id": "artifact.ref.p1.front", "kind": "image",
                          "sha256": staged["ref_p1"]["sha256"],
                          "store_relative_path": "inputs/ref_p1.png"}},
        ] + ([{"key": "three_quarter@BOOK-P1", "view": "three_quarter",
               "artifact": {"artifact_id": "artifact.ref.p1.three_quarter", "kind": "image",
                            "sha256": EXTRA_P1_SHA,
                            "store_relative_path": "inputs/ref_p1_tq.png"}}]
             if second_views else []),
        "BOOK-P3": [
            {"key": "back@BOOK-P3", "view": "back",
             "artifact": {"artifact_id": "artifact.ref.p3.back", "kind": "image",
                          "sha256": staged["ref_p3"]["sha256"],
                          "store_relative_path": "inputs/ref_p3.png"}},
        ] + ([{"key": "three_quarter@BOOK-P3", "view": "three_quarter",
               "artifact": {"artifact_id": "artifact.ref.p3.three_quarter", "kind": "image",
                            "sha256": EXTRA_P2_SHA,
                            "store_relative_path": "inputs/ref_p3_tq.png"}}]
             if second_views else []),
    }
    facts = [
        {"evidence_id": "EV-P1-PRESENCE", "subject_role": "BOOK-P1", "kind": "presence",
         "span": {"start_frame": 0, "end_frame_exclusive": 120}, "state": "measured"},
        {"evidence_id": "EV-P3-PRESENCE", "subject_role": "BOOK-P3", "kind": "presence",
         "span": {"start_frame": 0, "end_frame_exclusive": 120}, "state": "measured"},
        {"evidence_id": "EV-P1-HOLDS", "subject_role": "BOOK-P1", "kind": "contact",
         "span": {"start_frame": 0, "end_frame_exclusive": 72}, "state": "measured"},
        {"evidence_id": "EV-P2-WARN", "subject_role": "BOOK-P3", "kind": "presence",
         "span": {"start_frame": 0, "end_frame_exclusive": 120}, "state": "measured",
         "confidence": 0.2},
    ]
    if camera:
        facts.append({"evidence_id": "EV-CAM", "subject_role": "BOOK-P1", "kind": "camera",
                      "span": {"start_frame": 0, "end_frame_exclusive": 120},
                      "state": "measured"})
    plan = {
        "project_id": "demo-project-mf15",
        "series_id": "demo-series-mf15",
        "video_id": "demo-video-book",
        "unit_id": "BOOK-UNIT-001",
        "shot_id": "BOOK",
        "source": {"artifact_id": "artifact.book.source_window", "kind": "video",
                   "sha256": SOURCE_SHA, "store_relative_path": "inputs/BOOK_src.mp4"},
        "span": {"start_frame": 0, "end_frame_exclusive": 120},
        "timebase": {"fps_num": 30, "fps_den": 1, "stream_timebase_num": 1,
                     "stream_timebase_den": 15360, "pts_start_ticks": 0,
                     "pts_end_ticks": 60928, "decoded_frame_count": 120},
        "elements": [
            {"role": "BOOK-P1", "kind": "person", "occlusion": "visible",
             "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}]},
            {"role": "BOOK-P3", "kind": "person", "occlusion": "visible",
             "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}]},
        ],
        "interactions": [
            {"subject_role": "BOOK-P1", "relation": "holds", "object_role": "BOOK-P3",
             "spans": [{"start_frame": 0, "end_frame_exclusive": 72}],
             "evidence_ids": ["EV-P1-HOLDS"], "state": contact_state},
        ],
        "reference_manifest": {
            "style_version": "roundD-style-1",
            "roles": [
                {"role": "BOOK-P1", "character_id": "cast-boy-hacker",
                 "pack_version_id": "demo-packversion-r28", "items": manifest_items["BOOK-P1"]},
                {"role": "BOOK-P3", "character_id": "cast-gau-nau",
                 "pack_version_id": "demo-packversion-r28", "items": manifest_items["BOOK-P3"]},
            ],
        },
        "source_evidence": [
            {**fact,
             "artifact": {"artifact_id": "artifact.book.source_window", "kind": "video",
                          "sha256": SOURCE_SHA,
                          "store_relative_path": "inputs/BOOK_src.mp4"}}
            for fact in facts
        ],
    }
    if staged_override:
        staged.update(staged_override)
    return {
        "workspace_id": "default",
        "project_id": "demo-project-mf15",
        "series_id": "demo-series-mf15",
        "video_id": "demo-video-book",
        "unit_id": "BOOK-UNIT-001",
        "shot_id": "BOOK",
        "seed": 2026092501,
        "capability": "image_edit_multi_reference",
        "plan": plan,
        "required_views": required_views if required_views is not None
        else {"BOOK-P1": ["front"], "BOOK-P3": ["back"]},
        "cast_entries": cast_entries,
        "staged_inputs": staged,
        "source": {"artifact_id": "artifact.book.source_window", "sha256": SOURCE_SHA,
                   "store_relative_path": "inputs/BOOK_src.mp4",
                   "span": {"start_frame": 0, "end_frame_exclusive": 120},
                   "timebase": {"fps_num": 30, "fps_den": 1, "stream_timebase_num": 1,
                                "stream_timebase_den": 15360, "pts_start_ticks": 0,
                                "pts_end_ticks": 60928, "decoded_frame_count": 120}},
        "graph": {"file": "app/media_workflows/shot_anchor_v1.json",
                  "source_root": str(PROJECT_ROOT), "sha256": GRAPH_SHA,
                  "workflow_id": "shot_anchor_v1", "workflow_version": "v1",
                  "config_hash": GRAPH_SHA,
                  "model": {"model_id": "flux-2-klein-4b-fp8", "revision": "mf-pin-flux2",
                            "file_sha256": MODEL_SHA, "precision": "fp8",
                            "size_bytes": 0}},
        "output_contract": {"width": 640, "height": 368, "frame_count": 1},
        "budget": {"resource_class": "gpu_12gb", "max_wall_seconds": 900.0},
        "engine": {"base_url": "http://127.0.0.1:9"},
    }


# ── scheduler/db helpers ─────────────────────────────────────────────────────


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _service(db_path: Path, managed_root: Path) -> JobService:
    command.upgrade(_alembic_config(db_path), "head")
    factory = create_session_factory(create_engine_for_path(db_path))
    svc = JobService(factory, managed_root=managed_root)
    with factory() as session:
        if session.get(Workspace, "default") is None:
            session.add(Workspace(id="default", name="default"))
            session.commit()
    return svc


def _count_anchor_jobs(svc: JobService) -> int:
    with svc.session_factory() as session:
        return int(session.scalar(
            select(func.count(Job.id)).where(Job.job_type == sa.JOB_TYPE_SHOT_ANCHOR_RUN)
        ) or 0)


# ── micro repro: wiring + the real door ──────────────────────────────────────


class RecordingWorker:
    def __init__(self) -> None:
        self.registrations: dict[str, tuple[Any, dict]] = {}

    def register_handler(self, job_type: str, handler: Any, **kwargs: Any) -> None:
        self.registrations[job_type] = (handler, kwargs)


def test_mf15_1_job_type_registered_through_api_handlers() -> None:
    worker = RecordingWorker()
    jh.register_api_handlers(worker)
    assert sa.JOB_TYPE_SHOT_ANCHOR_RUN == "shot_anchor_run"
    handler, kwargs = worker.registrations[sa.JOB_TYPE_SHOT_ANCHOR_RUN]
    assert handler is sa.shot_anchor_handler
    assert kwargs.get("output_validator") is sa.anchor_output_validator
    # the legacy registrations are untouched by the patch
    for legacy in (jh.JOB_TYPE_INGEST, jh.JOB_TYPE_PROPAGATE, jh.JOB_TYPE_PREVIEW,
                   jh.JOB_TYPE_RENDER):
        assert legacy in worker.registrations


def test_mf15_1_default_engine_factory_is_the_real_adapter(tmp_path: Path) -> None:
    from app.adapters.media_engine.comfy import ComfyShotEngine

    assert sa.ENGINE_FACTORY is sa._engine_factory
    engine = sa.ENGINE_FACTORY(managed_root=tmp_path / "managed",
                               base_url="http://127.0.0.1:9")
    assert isinstance(engine, ComfyShotEngine)
    assert engine.base_url == "http://127.0.0.1:9"


# ── 15.1 resolution ──────────────────────────────────────────────────────────


def test_mf15_1_resolution_accepts_published_artwork() -> None:
    entry = {"role": "BOOK-P1", "view": "front", "artifact_id": "artifact.ref.p1.front",
             "sha256": REF_P1_SHA, "published": True, "kind": "artwork", "mode": "RGB"}
    resolved = sa.resolve_anchor_references([entry])
    assert resolved[0].sha256 == REF_P1_SHA


@pytest.mark.parametrize(
    "mutate, code",
    [
        ({"kind": "mask"}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_MASK_AS_ARTWORK),
        ({"mode": "L"}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_MASK_AS_ARTWORK),
        ({"mode": "1"}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_MASK_AS_ARTWORK),
        ({"published": False}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_NOT_PUBLISHED),
        ({"sha256": None}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED),
        ({"artifact_id": ""}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED),
        ({"role": ""}, sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED),
    ],
)
def test_mf15_1_resolution_refuses(mutate: dict, code: sa.ShotAnchorRefusalCode) -> None:
    entry = {"role": "BOOK-P1", "view": "front", "artifact_id": "artifact.ref.p1.front",
             "sha256": REF_P1_SHA, "published": True, "kind": "artwork", "mode": "RGB"}
    entry.update(mutate)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.resolve_anchor_references([entry])
    assert exc.value.code is code


def test_mf15_1_resolution_refuses_declared_digest_mismatch() -> None:
    entry = {"role": "BOOK-P1", "view": "front", "artifact_id": "artifact.ref.p1.front",
             "sha256": REF_P1_SHA, "published": True, "kind": "artwork", "mode": "RGB"}
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.resolve_anchor_references([entry], expected_sha256={"front@BOOK-P1": EXTRA_P1_SHA})
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_HASH_MISMATCH


def test_mf15_1_real_mask_file_mode_is_detected(tmp_path: Path) -> None:
    mask_path = tmp_path / "mask.png"
    _write_png(mask_path, mode="L")
    art_path = tmp_path / "art.png"
    _write_png(art_path, mode="RGB")
    assert sread.probe_image_mode(mask_path) == "L"
    assert sread.is_mask_like_mode(sread.probe_image_mode(mask_path)) is True
    assert sread.is_mask_like_mode(sread.probe_image_mode(art_path)) is False


# ── 15.2 the durable run ─────────────────────────────────────────────────────


def test_mf15_2_accepted_run_binds_source_cast_anchor_hashes(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    result = sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)

    assert result["verdict"] == "accepted"
    assert len(engine.calls) == 1
    binding = engine.calls[0]["binding"]
    # the capability floor of the FROZEN schema is satisfied by the resolved cast
    assert binding.capability == "image_edit_multi_reference"
    assert {role.role for role in binding.cast} == {"BOOK-P1", "BOOK-P3"}
    assert all(len(role.references) >= 2 for role in binding.cast)

    manifest_path = managed / result["anchor_manifest"]["relative_path"]
    assert manifest_path.is_file()
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert doc["schema_version"] == sa.ANCHOR_MANIFEST_SCHEMA
    assert doc["verdict"] == "accepted"
    assert doc["source"]["sha256"] == SOURCE_SHA
    assert doc["graph"]["workflow_sha256"] == GRAPH_SHA
    assert doc["input_identity_digest"] == result["input_identity_digest"]
    assert doc["input_identity_digest"] == sa.anchor_input_identity_digest(
        sa.anchor_input_identity(request)
    )
    cast_roles = {entry["role"] for entry in doc["cast"]}
    assert cast_roles == {"BOOK-P1", "BOOK-P3"}
    assert all(len(entry["sha256"]) == 64 for entry in doc["cast"])
    anchor = doc["anchor"]
    anchor_file = managed / anchor["store_relative_path"]
    assert anchor_file.is_file()
    assert sha_of(anchor_file) == anchor["sha256"]
    assert anchor["size_bytes"] == anchor_file.stat().st_size
    assert anchor["engine_artifact_sha256"] == anchor["sha256"]
    assert doc["receipt"]["prompt_id"] == "pid-anchor-0001"
    assert doc["receipt"]["server_side_wall_s"] == 1.25
    assert doc["receipt"]["vram_peak_mib"] == 11000
    assert doc["readiness"]["verdict"] == "ready"
    assert result["anchor_manifest"]["sha256"] == sha_of(manifest_path)
    with Image.open(anchor_file) as img:
        assert img.mode == "RGB"


def test_mf15_2_engine_receives_the_real_graph_bytes(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert engine.calls[0]["graph_nodes"] > 0
    assert engine.calls[0]["terminal_outputs"] == {"SAVE": {"kind": "image",
                                                            "media_type": "image"}}
    assert GRAPH_PATH.is_file() and sha_of(GRAPH_PATH) == GRAPH_SHA


def test_mf15_2_readiness_blocked_stops_before_the_engine(tmp_path: Path) -> None:
    request = build_request(tmp_path, contact_state="unmeasured")
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_READINESS_BLOCKED
    assert engine.calls == []  # no engine work after a blocked gate
    manifest = managed / sa.anchor_manifest_rel_path("BOOK")
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert doc["verdict"] == "rejected"
    assert [reason["code"] for reason in doc["reasons"]] == ["readiness_blocked"]


def test_mf15_2_engine_failure_is_a_rejected_manifest(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed, outcome="failed")
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_ENGINE_FAILED
    doc = json.loads((managed / sa.anchor_manifest_rel_path("BOOK")).read_text("utf-8"))
    assert doc["verdict"] == "rejected"
    assert doc["reasons"][0]["engine_code"] == "MF_COMFY_OOM"


def test_mf15_2_engine_refusal_surfaces_typed(tmp_path: Path) -> None:
    class _Refusal(RuntimeError):  # noqa: N818 — mirrors the engine's typed refusal
        code = "mf_end18_engine_unavailable"

    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed, raise_engine_error=_Refusal("engine absent"))
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_ENGINE_REFUSED
    assert exc.value.context["engine_code"] == "mf_end18_engine_unavailable"
    doc = json.loads((managed / sa.anchor_manifest_rel_path("BOOK")).read_text("utf-8"))
    assert doc["verdict"] == "rejected"
    assert doc["reasons"][0]["code"] == "engine_refused"


def test_mf15_2_staged_input_digest_mismatch_refused(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    request["staged_inputs"]["keyframe"] = {
        "relative_path": "inputs/keyframe.png", "sha256": _hex64("wrong"),
    }
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID
    assert engine.calls == []


def test_mf15_2_graph_digest_mismatch_refused(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    request["graph"]["sha256"] = _hex64("not-the-graph")
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID


def test_mf15_2_single_reference_cast_refused_by_the_frozen_floor(tmp_path: Path) -> None:
    request = build_request(tmp_path, second_views=False)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_CAST_REFERENCE_REQUIRED
    assert engine.calls == []


def test_mf15_2_real_adapter_absent_engine_refuses_through_the_same_path(
    tmp_path: Path,
) -> None:
    """The production door IS the real adapter: with the pinned wheel absent (or
    the epoch missing) the SAME run path produces a typed engine refusal."""
    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = sa.ENGINE_FACTORY(managed_root=managed, base_url="http://127.0.0.1:9")
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_ENGINE_REFUSED
    assert exc.value.context["engine_code"] in {
        "mf_end18_engine_unavailable", "epoch_missing",
    }
    doc = json.loads((managed / sa.anchor_manifest_rel_path("BOOK")).read_text("utf-8"))
    assert doc["verdict"] == "rejected"


# ── 15.3 the input gate ──────────────────────────────────────────────────────


def _plan(request: dict) -> Any:
    from app.schemas.shot_reskin import ShotPlan

    return ShotPlan.model_validate(request["plan"])


def test_mf15_3_gate_ready_rows_and_warnings_are_advisory(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    resolved = sa.resolve_anchor_references(request["cast_entries"])
    report = sread.evaluate_shot_input_readiness(
        _plan(request),
        required_views=request["required_views"],
        resolve_reference=sa._resolver_for(resolved),
    )
    assert report["verdict"] == "ready"
    assert report["blocking_rows"] == []
    assert report["accepted"] is False  # the gate never accepts by itself
    assert report["warnings_are_advisory"] is True
    assert {row["status"] for row in report["rows"].values()} == {"pass"}
    # the low-confidence fact and the partial-person note are warnings ONLY
    codes = {warning["code"] for warning in report["warnings"]}
    assert "low_confidence_fact" in codes
    sread.require_ready(report)  # explicit acceptance step passes


@pytest.mark.parametrize(
    "mutate, expect_row",
    [
        ("no_presence", "coverage"),
        ("unmeasured_interaction", "contact"),
        ("camera_missing", "camera"),
        ("view_missing", "pose"),
        ("reference_sha_changed", "reference_hashes"),
    ],
)
def test_mf15_3_gate_rows_fail_and_warnings_never_accept(
    tmp_path: Path, mutate: str, expect_row: str
) -> None:
    request = build_request(
        tmp_path,
        contact_state="unmeasured" if mutate == "unmeasured_interaction" else "measured",
        camera=mutate != "camera_missing",
    )
    if mutate == "no_presence":
        request["plan"]["source_evidence"] = [
            fact for fact in request["plan"]["source_evidence"]
            if fact["evidence_id"] != "EV-P1-PRESENCE"
        ]
    if mutate == "view_missing":
        request["required_views"] = {"BOOK-P1": ["side"]}
    if mutate == "reference_sha_changed":
        request["plan"]["reference_manifest"]["roles"][0]["items"][0]["artifact"][
            "sha256"
        ] = _hex64("x")
    resolved = sa.resolve_anchor_references(request["cast_entries"])
    report = sread.evaluate_shot_input_readiness(
        _plan(request),
        required_views=request["required_views"],
        resolve_reference=sa._resolver_for(resolved),
    )
    assert report["verdict"] == "blocked"
    assert expect_row in report["blocking_rows"]
    assert report["rows"][expect_row]["status"] == "fail"
    with pytest.raises(sread.ShotInputReadinessError) as exc:
        sread.require_ready(report)
    assert exc.value.code is sread.ReadinessRefusalCode.READINESS_BLOCKED
    assert expect_row in exc.value.context["blocking_rows"]


def test_mf15_3_mask_view_refused_and_unpublished_view_refused(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    resolved = sa.resolve_anchor_references(
        [e for e in request["cast_entries"] if e["role"] != "BOOK-P1"]
    )

    def resolver(role: str, view: str | None) -> sread.ReferenceResolution | None:
        if role == "BOOK-P1":
            # the published authority returned a MASK for this role's front view
            return sread.ReferenceResolution(
                artifact_id="artifact.mask.p1", sha256=REF_P1_SHA, published=True,
                kind="mask", mode="L",
            )
        return sa._resolver_for(resolved)(role, view)

    report = sread.evaluate_shot_input_readiness(
        _plan(request),
        required_views={"BOOK-P1": ["front"]},
        resolve_reference=resolver,
    )
    assert report["verdict"] == "blocked"
    assert "pose" in report["blocking_rows"]
    assert "MASK" in report["rows"]["pose"]["detail"]

    request2 = build_request(tmp_path)
    request2["cast_entries"][2]["published"] = False  # second view unpublished
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.resolve_anchor_references(request2["cast_entries"])
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_NOT_PUBLISHED


def test_mf15_3_unknown_resolver_is_a_fail_not_a_warning(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    report = sread.evaluate_shot_input_readiness(
        _plan(request), required_views={"BOOK-P1": ["front"]}, resolve_reference=None
    )
    assert report["verdict"] == "blocked"
    assert report["rows"]["pose"]["status"] == "fail"
    assert report["rows"]["reference_hashes"]["status"] == "fail"


def test_mf15_3_validator_rehashes_the_manifest_on_disk(tmp_path: Path) -> None:
    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    result = sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    ctx = SimpleNamespace(input_manifest={"managed_root": str(managed)})
    evidence = sa.anchor_output_validator(ctx, result, managed)
    assert evidence["anchor_manifest"]["sha256"] == result["anchor_manifest"]["sha256"]
    manifest_file = managed / result["anchor_manifest"]["relative_path"]
    manifest_file.write_text("{}", encoding="utf-8")  # tamper
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.anchor_output_validator(ctx, result, managed)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_ARTIFACT_HASH_MISMATCH


# ── 15.4 invalidation + the video gate ───────────────────────────────────────


def _accepted_manifest(tmp_path: Path) -> tuple[Path, dict, str]:
    request = build_request(tmp_path)
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    result = sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    return managed, request, result["input_identity_digest"]


def test_mf15_4_gate_unblocks_on_a_current_accepted_anchor(tmp_path: Path) -> None:
    managed, _request, digest = _accepted_manifest(tmp_path)
    gate = sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK",
                                      expected_identity_digest=digest)
    assert gate["verdict"] == "accepted"
    assert gate["receipt"]["prompt_id"] == "pid-anchor-0001"
    assert gate["anchor"]["sha256"] == gate["anchor"]["sha256"]


def test_mf15_4_missing_manifest_blocks_video(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK")
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING


def test_mf15_4_rejected_anchor_blocks_video(tmp_path: Path) -> None:
    request = build_request(tmp_path, contact_state="unmeasured")
    managed = tmp_path / "managed"
    engine = ScriptedAnchorEngine(managed)
    with pytest.raises(sa.ShotAnchorRefusal):
        sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK")
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED
    assert exc.value.context["reasons"][0]["code"] == "readiness_blocked"


def test_mf15_4_changed_asset_or_input_makes_the_anchor_stale(tmp_path: Path) -> None:
    managed, request, digest = _accepted_manifest(tmp_path)
    # one reference artifact changed -> the input identity digest changes
    request2 = copy.deepcopy(request)
    request2["cast_entries"][0]["sha256"] = _hex64("replaced-ref")
    new_digest = sa.anchor_input_identity_digest(sa.anchor_input_identity(request2))
    assert new_digest != digest
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK",
                                   expected_identity_digest=new_digest)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_STALE_INPUT
    # the SAME manifest is still current for the identity it was produced under
    gate = sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK",
                                      expected_identity_digest=digest)
    assert gate["verdict"] == "accepted"


def test_mf15_4_tampered_anchor_bytes_block_video(tmp_path: Path) -> None:
    managed, _request, digest = _accepted_manifest(tmp_path)
    doc = json.loads((managed / sa.anchor_manifest_rel_path("BOOK")).read_text("utf-8"))
    (managed / doc["anchor"]["store_relative_path"]).write_bytes(b"tampered")
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK",
                                   expected_identity_digest=digest)
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_ARTIFACT_MISSING


# ── retry law + shared job API (durable integration) ─────────────────────────


def test_mf15_2_submit_is_idempotent_and_shared_api_reads_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service(tmp_path / "jobs.db", tmp_path / "managed")
    request = build_request(tmp_path)
    managed = tmp_path / "managed"

    def _factory(**kwargs: Any) -> ScriptedAnchorEngine:
        return ScriptedAnchorEngine(kwargs.get("managed_root", managed))

    monkeypatch.setattr(sa, "ENGINE_FACTORY", _factory)

    first = sa.submit_shot_anchor_job(svc, request=request)
    second = sa.submit_shot_anchor_job(svc, request=request)
    assert first.job_id == second.job_id  # same inputs converge on ONE Job
    assert _count_anchor_jobs(svc) == 1

    ran = svc.worker.run_once()
    assert ran == 1
    info = svc.get_job(first.job_id)
    assert info is not None
    assert info.state.value == "completed"
    body = job_response(info)
    assert body["status"] == "completed"

    # a completed job is REUSED, never duplicated
    third = sa.submit_shot_anchor_job(svc, request=request)
    assert third.job_id == first.job_id
    assert _count_anchor_jobs(svc) == 1

    # the UI reads the anchor evidence through the same shared job API
    manifest = managed / sa.anchor_manifest_rel_path("BOOK")
    assert manifest.is_file()
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert doc["verdict"] == "accepted"
    assert doc["receipt"]["prompt_id"] == "pid-anchor-0001"
    assert doc["input_identity_digest"] == sa.anchor_input_identity_digest(
        sa.anchor_input_identity(request)
    )


def test_mf15_2_stale_completed_job_does_not_block_a_new_input_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed input is a NEW job (new generation) — the old one is untouched."""
    svc = _service(tmp_path / "jobs.db", tmp_path / "managed")
    request = build_request(tmp_path)
    managed = tmp_path / "managed"

    def _factory(**kwargs: Any) -> ScriptedAnchorEngine:
        return ScriptedAnchorEngine(kwargs.get("managed_root", managed))

    monkeypatch.setattr(sa, "ENGINE_FACTORY", _factory)
    first = sa.submit_shot_anchor_job(svc, request=request)
    svc.worker.run_once()
    request2 = copy.deepcopy(request)
    request2["cast_entries"][0]["sha256"] = _hex64("new-generation-ref")
    second = sa.submit_shot_anchor_job(svc, request=request2)
    assert second.job_id != first.job_id
    assert _count_anchor_jobs(svc) == 2


# ── C15 correction (P1-04): public anchor API over the EXISTING durable job ──

#: Measured route-registration counts: before = `git show a52fca8:app/api/app.py
#: | grep -c "app.include_router("` = 28; after = 29 (the anchor router added).
APP_INCLUDE_ROUTER_BEFORE = 28
APP_INCLUDE_ROUTER_AFTER = 29

#: The PINNED HTTP contract of `app/api/routes/shot_anchors.py` (see its docstring).
ANCHOR_ROUTE_PATHS = (
    "/api/v2/projects/{project_id}/shot-anchors",
    "/api/v2/shot-anchors/{job_id}",
    "/api/v2/shot-anchors/{job_id}/retry",
    "/api/v2/projects/{project_id}/shot-anchors/{shot_id}/preview",
    "/api/v2/projects/{project_id}/shot-anchors/{shot_id}/accept",
    "/api/v2/projects/{project_id}/shot-anchors/{shot_id}/reject",
    "/api/v2/projects/{project_id}/shot-anchors/{shot_id}/video-gate",
)

#: Evidence root of the C15 correction round (raw HTTP receipts land here).
MF15_RUN_ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/"
    "cmc-correction-20260929T091814Z/tasks/MF-END-15"
)


def _receipt(name: str, payload: dict[str, Any]) -> None:
    """Persist one HTTP receipt into the round's raw/ evidence directory."""
    if not MF15_RUN_ROOT.is_dir():
        return
    target = MF15_RUN_ROOT / "raw" / "http_receipts"
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _client_with_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any]:
    """A TestClient bound to an ISOLATED JobService (tmp DB + tmp managed root)."""
    from fastapi.testclient import TestClient

    from app.api import deps as api_deps
    from app.api.app import app as api_app

    service = _service(tmp_path / "jobs.db", tmp_path / "managed")
    monkeypatch.setattr(api_deps, "_job_service", service)
    return TestClient(api_app), service


def _castless_plan(request: dict[str, Any]) -> dict[str, Any]:
    """The same shot plan WITHOUT reference roles.

    The anchor job then reaches the frozen engine cast floor and refuses typed,
    which lets the HTTP/durable protocol be proven end to end WITHOUT seeding a
    fake published pack into a test database.
    """
    plan = copy.deepcopy(request["plan"])
    plan["reference_manifest"]["roles"] = []
    return plan


def _http_payload(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_item_id": request["plan"]["video_id"],
        "unit_id": request["plan"]["unit_id"],
        "shot_id": request["plan"]["shot_id"],
        "series_id": request["plan"].get("series_id"),
        "seed": request["seed"],
        "capability": request["capability"],
        "cast": [],
        "plan": _castless_plan(request),
        "source": request["source"],
        "graph": request["graph"],
        "staged_inputs": request["staged_inputs"],
        "output_contract": request["output_contract"],
        "budget": request["budget"],
        "engine": request["engine"],
    }


def test_c15_1_public_anchor_api_is_registered() -> None:
    """The finding's core: the anchor job is reachable through the REAL app."""
    from app.api.app import app as api_app

    # `app.routes` does NOT flatten child routers (measured: 37 entries, 0
    # matching paths) — the included router is proven through the OpenAPI
    # document, which is the app's own published surface.
    paths = set(api_app.openapi()["paths"])
    missing = [path for path in ANCHOR_ROUTE_PATHS if path not in paths]
    assert missing == []
    # no pre-existing route was lost by the bounded app.py patch
    for legacy in ("/health", "/api/v1/health", "/api/jobs/{job_id}"):
        assert legacy in paths
    source = (PROJECT_ROOT / "app" / "api" / "app.py").read_text(encoding="utf-8")
    assert source.count("app.include_router(") == APP_INCLUDE_ROUTER_AFTER
    assert source.count("app.include_router(") == APP_INCLUDE_ROUTER_BEFORE + 1
    assert source.count("shot_anchors") == 2  # one import line + one include
    assert "app.include_router(shot_anchors.router)" in source
    # the new module is HTTP surface only: it reuses the durable job authority
    route_src = (
        PROJECT_ROOT / "app" / "api" / "routes" / "shot_anchors.py"
    ).read_text(encoding="utf-8")
    assert "__tablename__" not in route_src
    assert "JobRepository" in route_src
    assert "submit_shot_anchor_job" in route_src
    assert "require_accepted_anchor" in route_src


def test_c15_2_http_submit_status_retry_real_durable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real HTTP: submit 202 → repeat 200 (no new job) → status 200 → worker runs
    the durable anchor job → retry 202 (exactly one successor) → active 409."""
    client, service = _client_with_service(tmp_path, monkeypatch)
    request = build_request(tmp_path)
    project_id = request["plan"]["project_id"]
    url = f"/api/v2/projects/{project_id}/shot-anchors"

    # The JOB is created at the SERVICE layer (the already-proven durable path);
    # the HTTP surface is then driven over it.  HTTP-driven submit is proven
    # separately as a typed refusal with ZERO job rows (test_c15_3), because a
    # test DB carries no published pack for the resolver to bind.
    info = sa.submit_shot_anchor_job(service, request=request)
    job_id = info.job_id
    same = sa.submit_shot_anchor_job(service, request=request)
    assert same.job_id == job_id  # identical inputs converge on ONE job
    assert _count_anchor_jobs(service) == 1
    _receipt("01_submit_idempotent_service.json", {
        "layer": "service", "call": "submit_shot_anchor_job", "job_id": job_id,
        "status": info.state.value, "reused_job_id": same.job_id,
        "anchor_jobs_in_db": 1,
    })

    status = client.get(f"/api/v2/shot-anchors/{job_id}")
    _receipt("03_status_queued.json", {
        "method": "GET", "path": f"/api/v2/shot-anchors/{job_id}",
        "status": status.status_code, "response": status.json(),
    })
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["shot_id"] == "BOOK"

    assert service.worker.run_once() == 1

    done = client.get(f"/api/v2/shot-anchors/{job_id}")
    _receipt("04_status_after_worker.json", {
        "method": "GET", "path": f"/api/v2/shot-anchors/{job_id}",
        "status": done.status_code, "response": done.json(),
    })
    assert done.status_code == 200
    done_body = done.json()
    assert done_body["status"] == "failed"
    # measured: with no Comfy adapter installed in the test env the durable job
    # fails fast at the engine boundary and the refusal is carried in `message`
    assert "engine refused" in json.dumps(done_body).lower()

    retried = client.post(f"/api/v2/shot-anchors/{job_id}/retry")
    _receipt("05_retry_terminal.json", {
        "method": "POST", "path": f"/api/v2/shot-anchors/{job_id}/retry",
        "status": retried.status_code, "response": retried.json(),
    })
    assert retried.status_code == 202
    retry_body = retried.json()
    assert retry_body["new_generation"] is True
    assert retry_body["job_id"] != job_id
    assert _count_anchor_jobs(service) == 2

    blocked = client.post(f"/api/v2/shot-anchors/{retry_body['job_id']}/retry")
    _receipt("06_retry_active.json", {
        "method": "POST", "path": f"/api/v2/shot-anchors/{retry_body['job_id']}/retry",
        "status": blocked.status_code, "response": blocked.json(),
    })
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "anchor_job_active"
    assert _count_anchor_jobs(service) == 2

    unknown = client.get("/api/v2/shot-anchors/does-not-exist")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "anchor_job_not_found"


def test_c15_3_submit_refuses_without_creating_a_half_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness / published-cast refusals are typed 422 with ZERO job rows."""
    client, service = _client_with_service(tmp_path, monkeypatch)
    request = build_request(tmp_path)
    payload = _http_payload(request)
    project_id = request["plan"]["project_id"]
    url = f"/api/v2/projects/{project_id}/shot-anchors"

    payload["cast"] = [{
        "role": "BOOK-P1",
        "character_id": "cast-absent",
        "pack_version_id": "pack-absent-v1",
        "views": ["front", "three_quarter"],
    }]
    unresolvable = client.post(url, json=payload)
    _receipt("07_submit_unresolvable_cast.json", {
        "method": "POST", "path": url, "request": payload,
        "status": unresolvable.status_code, "response": unresolvable.json(),
    })
    assert unresolvable.status_code == 422
    assert unresolvable.json()["detail"]["code"] == "anchor_reference_unresolved"
    assert _count_anchor_jobs(service) == 0

    # a warning-only input problem must NOT auto-accept: no camera measured on the
    # locked source blocks the shot even though every other row is satisfiable
    payload2 = _http_payload(request)
    payload2["plan"]["source_evidence"] = [
        fact for fact in payload2["plan"]["source_evidence"] if fact["kind"] != "camera"
    ]
    blocked = client.post(url, json=payload2)
    _receipt("08_submit_readiness_blocked.json", {
        "method": "POST", "path": url, "request": payload2,
        "status": blocked.status_code, "response": blocked.json(),
    })
    # A castless plan is refused at the INPUT layer (reference role removed, so
    # the frozen ShotPlan contract refuses it) BEFORE the readiness layer can
    # run — measured code: `anchor_input_invalid`, not `anchor_readiness_blocked`.
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "anchor_input_invalid"
    assert _count_anchor_jobs(service) == 0

    # a plan that is not the frozen ShotPlan contract is refused too
    payload3 = _http_payload(request)
    payload3["plan"]["span"] = {"start_frame": 5, "end_frame_exclusive": 5}
    malformed = client.post(url, json=payload3)
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "anchor_input_invalid"
    assert _count_anchor_jobs(service) == 0


def test_c15_4_published_cast_resolution_laws(tmp_path: Path) -> None:
    """Against the REAL (empty) workspace authority: nothing resolves."""
    service = _service(tmp_path / "jobs.db", tmp_path / "managed")
    requirement = {
        "role": "BOOK-P1", "character_id": "c-absent",
        "pack_version_id": "v-absent", "views": ["front"],
    }
    with service.session_factory() as session:
        with pytest.raises(sa.ShotAnchorRefusal) as exc:
            sa.resolve_published_cast_references(
                session, workspace_id="default", requirements=[requirement]
            )
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED
    with service.session_factory() as session:
        with pytest.raises(sa.ShotAnchorRefusal) as exc2:
            sa.resolve_published_cast_references(
                session, workspace_id="default",
                requirements=[{**requirement, "role": ""}],
            )
    assert exc2.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED


def test_c15_4_duplicate_pose_placeholder_mask_and_draft_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI fixture repository (labelled) for the laws that need a PUBLISHED pack:
    one artifact for two poses, a declared placeholder, a mask-shaped artifact
    and an unpublished version are each refused with their own code."""

    class _Asset:
        def __init__(self, slot: str, artifact_id: str, digest: str | None,
                     rel: str | None = None) -> None:
            self.pose_slot = slot
            self.artifact_id = artifact_id
            self.artifact_state = "ready"
            self.artifact_sha256 = digest
            self.artifact_relative_path = rel

    class _Version:
        def __init__(self, assets: tuple, status: str = "published") -> None:
            self.assets = assets
            self.status = status

    class _Repo:
        def __init__(self, session: Any, storage_root: Any = None) -> None:  # noqa: ARG002
            pass

        def get_pack_version_for_character(
            self, character_id: str, version_id: str, workspace_id: str
        ) -> Any:  # noqa: ARG002
            return _Version(())

    requirement = {
        "role": "BOOK-P1", "character_id": "c1",
        "pack_version_id": "v1", "views": ["front", "three_quarter"],
    }
    monkeypatch.setattr("app.persistence.characters.CharacterRepository", _Repo)

    same = _hex64("one-artifact-for-two-poses")

    class _DupRepo(_Repo):
        def get_pack_version_for_character(self, *args: Any) -> Any:
            return _Version((_Asset("front", "art-1", same),
                             _Asset("three_quarter", "art-2", same)))

    monkeypatch.setattr("app.persistence.characters.CharacterRepository", _DupRepo)
    with pytest.raises(sa.ShotAnchorRefusal) as exc:
        sa.resolve_published_cast_references(
            None, workspace_id="default", requirements=[requirement]
        )
    assert exc.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_VIEW_DUPLICATED

    class _PlaceholderRepo(_Repo):
        def get_pack_version_for_character(self, *args: Any) -> Any:
            return _Version((_Asset("front", "art-ph", _hex64("ph")),
                             _Asset("three_quarter", "art-2", _hex64("other"))))

    monkeypatch.setattr("app.persistence.characters.CharacterRepository", _PlaceholderRepo)
    with pytest.raises(sa.ShotAnchorRefusal) as exc2:
        sa.resolve_published_cast_references(
            None, workspace_id="default",
            requirements=[{**requirement, "placeholder_artifact_ids": ["art-ph"]}],
        )
    assert exc2.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_PLACEHOLDER

    class _DraftRepo(_Repo):
        def get_pack_version_for_character(self, *args: Any) -> Any:
            return _Version((_Asset("front", "art-1", _hex64("a")),
                             _Asset("three_quarter", "art-2", _hex64("b"))),
                            status="draft")

    monkeypatch.setattr("app.persistence.characters.CharacterRepository", _DraftRepo)
    with pytest.raises(sa.ShotAnchorRefusal) as exc3:
        sa.resolve_published_cast_references(
            None, workspace_id="default", requirements=[requirement]
        )
    assert exc3.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_NOT_PUBLISHED

    managed = tmp_path / "managed"
    _write_png(managed / "inputs" / "mask.png", mode="L")
    _write_png(managed / "inputs" / "art.png", mode="RGB")

    class _MaskRepo(_Repo):
        def get_pack_version_for_character(self, *args: Any) -> Any:
            return _Version((_Asset("front", "art-m", _hex64("m"), "inputs/mask.png"),
                             _Asset("three_quarter", "art-2", _hex64("o"),
                                    "inputs/art.png")))

    monkeypatch.setattr("app.persistence.characters.CharacterRepository", _MaskRepo)
    with pytest.raises(sa.ShotAnchorRefusal) as exc4:
        sa.resolve_published_cast_references(
            None, workspace_id="default", requirements=[requirement],
            managed_root=managed,
        )
    assert exc4.value.code is sa.ShotAnchorRefusalCode.ANCHOR_REFERENCE_MASK_AS_ARTWORK


def test_c15_5_decision_binding_and_video_gate_blocks(tmp_path: Path) -> None:
    """preview / accept / reject are bound to the CURRENT manifest hash, and a
    rejected or no-longer-covering decision BLOCKS the video gate."""
    managed, request, digest = _accepted_manifest(tmp_path)

    preview = sa.anchor_status(managed, "BOOK", expected_identity_digest=digest)
    assert preview["manifest_present"] is True
    assert preview["verdict"] == "accepted"
    assert preview["stale"] is False
    assert preview["video_allowed"] is True
    assert preview["anchor_artifact_intact"] is True
    assert preview["decision"] is None
    manifest_sha = preview["manifest_sha256"]

    with pytest.raises(sa.ShotAnchorRefusal) as stale_accept:
        sa.record_anchor_decision(
            managed, "BOOK", "accepted",
            expected_manifest_sha256=_hex64("not-the-current-manifest"),
        )
    assert stale_accept.value.code is sa.ShotAnchorRefusalCode.ANCHOR_DECISION_STALE

    with pytest.raises(sa.ShotAnchorRefusal) as no_reason:
        sa.record_anchor_decision(
            managed, "BOOK", "rejected",
            expected_manifest_sha256=manifest_sha, reason="   ",
        )
    assert no_reason.value.code is sa.ShotAnchorRefusalCode.ANCHOR_DECISION_INVALID

    accepted = sa.record_anchor_decision(
        managed, "BOOK", "accepted",
        expected_manifest_sha256=manifest_sha, note="reviewed by owner",
    )
    assert accepted["decision"] == "accepted"
    assert accepted["manifest_sha256"] == manifest_sha
    assert accepted["anchor_sha256"] == preview["anchor"]["sha256"]
    assert accepted["input_identity_digest"] == digest
    assert accepted["decision_path"] == sa.anchor_decision_rel_path("BOOK")
    assert sa.anchor_status(managed, "BOOK")["video_allowed"] is True
    assert sa.require_accepted_anchor(
        managed_root=managed, shot_id="BOOK", expected_identity_digest=digest
    )["verdict"] == "accepted"

    rejected = sa.record_anchor_decision(
        managed, "BOOK", "rejected", expected_manifest_sha256=manifest_sha,
        reason="source mask leaked into the anchor",
    )
    assert rejected["decision"] == "rejected"
    with pytest.raises(sa.ShotAnchorRefusal) as blocked:
        sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK")
    assert blocked.value.code is sa.ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED
    assert "REJECTED" in blocked.value.detail
    with pytest.raises(sa.ShotAnchorRefusal) as blocked2:
        sa.require_accepted_anchor(
            managed_root=managed, shot_id="BOOK", expected_identity_digest=digest
        )
    assert blocked2.value.code is sa.ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED
    assert sa.anchor_status(managed, "BOOK")["video_allowed"] is False

    # a NEW anchor (new manifest bytes) is not covered by the earlier decision:
    # video stays blocked until the new anchor is previewed and accepted
    engine = ScriptedAnchorEngine(managed)
    sa.run_anchor_attempt(managed_root=managed, request=request, engine=engine)
    with pytest.raises(sa.ShotAnchorRefusal) as not_covered:
        sa.require_accepted_anchor(managed_root=managed, shot_id="BOOK")
    assert not_covered.value.code is sa.ShotAnchorRefusalCode.ANCHOR_DECISION_STALE
    fresh = sa.anchor_status(managed, "BOOK")
    assert fresh["video_allowed"] is False
    assert fresh["decision"]["manifest_sha256"] != fresh["manifest_sha256"]
    fresh_accept = sa.record_anchor_decision(
        managed, "BOOK", "accepted",
        expected_manifest_sha256=fresh["manifest_sha256"], note="new anchor reviewed",
    )
    assert fresh_accept["manifest_sha256"] == fresh["manifest_sha256"]
    assert sa.anchor_status(managed, "BOOK")["video_allowed"] is True
