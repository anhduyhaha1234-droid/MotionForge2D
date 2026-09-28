"""MF-END-19 tests — FullApply → shot-level render (whole-shot/group + comfy engine).

Rows (binary, no mocks inside production code; the CI scripted engine is
labeled and only stands at the engine boundary, like the MF-END-15 pattern):

* 19.1 execution-backend manifest: schema validation, planner normalization,
  legacy default unchanged (byte-identical behaviour for absent manifests).
* 19.2 whole-shot/GROUP dispatch: one generation unit per shot group carrying
  every member role; the legacy backend keeps per-layer chunks.
* 19.3 real Comfy adapter path: eligible-profile selection (INELIGIBLE VACE
  refused), graph pinning, declared-parameter patching, staged-input digests,
  output harvest (hashes + provenance), source-never-returned gate.
* 19.4 publication gates: every required chunk present + verified + usable,
  source frames never published as the output.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from app.schemas.s10_full_apply import ExecutionBackendManifest
from app.schemas.shot_reskin import (
    EngineArtifactOutput,
    EngineDecodedFacts,
    EngineOutputBinding,
    ShotExecutionRecord,
)
from app.services import s10_chunk_plan as cp
from app.services import shot_reskin_executor as sre
from app.services.renderer_routes.composite import write_frames_mp4
from app.workflow import s10_full_apply_jobs as jobs

WT = Path(__file__).resolve().parents[2]
GRAPH_REL = "app/media_workflows/wan_shot_v1.json"
WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"
VACE_PROFILE = "vace_14b_fp16_book"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_mp4(path: Path, frames: int, *, seed: int = 0, fps: float = 30.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = []
    for i in range(frames):
        f = np.zeros((48, 64, 3), dtype=np.uint8)
        f[:, :, 0] = (int(seed) + i * 3) % 255
        f[:, :, 1] = 60
        f[:, :, 2] = 200
        arr.append(f)
    write_frames_mp4(arr, path, fps=fps)
    return path


# ── 19.1 — execution backend manifest ────────────────────────────────────────


def test_mf19_1_manifest_schema_accepts_eligible_backend_forms() -> None:
    legacy = ExecutionBackendManifest.model_validate({"backend": "legacy_renderer"})
    assert legacy.backend == "legacy_renderer"
    comfy = ExecutionBackendManifest.model_validate(
        {
            "backend": "comfy_shot_engine",
            "profile_id": WAN_PROFILE,
            "graph_sha256": "a" * 64,
            "shot_prompts": {"BOOK": "prompt"},
        }
    )
    assert comfy.capability is None and comfy.shot_prompts == {"BOOK": "prompt"}


def test_mf19_1_manifest_pins_shot_anchors_and_normalizes_them() -> None:
    anchor_sha = "a1" * 32
    manifest = ExecutionBackendManifest.model_validate(
        {
            "backend": "comfy_shot_engine",
            "profile_id": WAN_PROFILE,
            "graph_sha256": "a" * 64,
            "shot_prompts": {"BOOK": "a book prompt"},
            "shot_anchors": {"BOOK": {"relative_path": "shots/BOOK/anchor.png", "sha256": anchor_sha}},
        }
    )
    assert manifest.shot_anchors["BOOK"].sha256 == anchor_sha
    ckpt, lock, scene, mapping, policy = _plan_inputs()
    plan = cp.plan_full_apply(
        ckpt,
        lock,
        scene,
        mapping,
        policy,
        chunk_config={
            "execution_backend": {
                "backend": "comfy_shot_engine",
                "profile_id": WAN_PROFILE,
                "graph_sha256": "a" * 64,
                "shot_prompts": {"BOOK": "a book prompt"},
                "shot_anchors": {"BOOK": {"relative_path": "shots/BOOK/anchor.png", "sha256": anchor_sha}},
            }
        },
    )
    backend = plan["chunk_config"]["execution_backend"]
    assert backend["shot_anchors"] == {
        "BOOK": {"relative_path": "shots/BOOK/anchor.png", "sha256": anchor_sha}
    }
    with pytest.raises(Exception):
        ExecutionBackendManifest.model_validate(
            {
                "backend": "legacy_renderer",
                "shot_anchors": {"BOOK": {"relative_path": "x", "sha256": anchor_sha}},
            }
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"backend": "legacy_routes"},
        {"backend": "comfy_shot_engine", "profile_id": WAN_PROFILE},
        {"backend": "comfy_shot_engine", "graph_sha256": "a" * 64},
        {"backend": "legacy_renderer", "profile_id": WAN_PROFILE},
        {"backend": "legacy_renderer", "shot_prompts": {"S": "p"}},
        {"backend": "comfy_shot_engine", "profile_id": "p", "graph_sha256": "zz", "output_node": "1"},
        {
            "backend": "comfy_shot_engine",
            "profile_id": "p",
            "graph_sha256": "a" * 64,
            "engine_base_url": "http://10.0.0.5:8188",
        },
    ],
)
def test_mf19_1_manifest_schema_refuses_invalid_forms(bad: dict[str, Any]) -> None:
    with pytest.raises(Exception):
        ExecutionBackendManifest.model_validate(bad)


def _plan_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    ckpt = {"checkpoint_hash": "b" * 64, "checkpoint_id": "ckpt-1", "revision": 1}
    lock = {
        "manifest_hash": "c" * 64,
        "frame_count": 120,
        "policy_version": "v1",
        "source_generation": "1",
    }
    scene = {
        "shots": [
            {"shot_id": "BOOK", "start_frame": 0, "end_frame": 119},
        ]
    }
    mapping = {
        "mappings": [
            {
                "layer_id": "BOOK-P1",
                "mapping_id": "m1",
                "route": "sprite_affine",
                "affected_region": [0, 0, 10, 10],
                "pack_version": "pv1",
                "start_frame": 0,
                "end_frame": 119,
            },
            {
                "layer_id": "BOOK-P2",
                "mapping_id": "m2",
                "route": "sprite_affine",
                "affected_region": [0, 0, 10, 10],
                "pack_version": "pv1",
                "start_frame": 0,
                "end_frame": 119,
            },
        ]
    }
    policy = {"policy_version": "v1"}
    return ckpt, lock, scene, mapping, policy


def test_mf19_1_planner_legacy_default_plan_unchanged() -> None:
    ckpt, lock, scene, mapping, policy = _plan_inputs()
    plan_absent = cp.plan_full_apply(ckpt, lock, scene, mapping, policy, chunk_config=None)
    plan_legacy = cp.plan_full_apply(
        ckpt, lock, scene, mapping, policy, chunk_config={"execution_backend": {"backend": "legacy_renderer"}}
    )
    # absent manifest -> cfg carries ONLY the historical keys; 2 roles at the
    # default 48-frame split over a 120-frame shot => 3 chunks x 2 layers = 6.
    assert plan_absent["chunk_config"] == {"chunk_frames": 48, "overlap_frames": 4}
    assert len(plan_absent["chunks"]) == 6
    assert plan_legacy["chunk_config"]["execution_backend"] == {"backend": "legacy_renderer"}
    # the explicit legacy manifest changes the plan hash (new frozen input), not the shape
    assert plan_legacy["plan_hash"] != plan_absent["plan_hash"]
    assert len(plan_legacy["chunks"]) == 6
    # determinism: same inputs, same plan id
    again = cp.plan_full_apply(ckpt, lock, scene, mapping, policy, chunk_config=None)
    assert again["plan_id"] == plan_absent["plan_id"]


def test_mf19_1_planner_refuses_invalid_manifest_and_persists_normal_form() -> None:
    ckpt, lock, scene, mapping, policy = _plan_inputs()
    with pytest.raises(cp.ChunkPlanError):
        cp.plan_full_apply(
            ckpt, lock, scene, mapping, policy, chunk_config={"execution_backend": "comfy_shot_engine"}
        )
    with pytest.raises(cp.ChunkPlanError):
        cp.plan_full_apply(
            ckpt, lock, scene, mapping, policy,
            chunk_config={"execution_backend": {"backend": "comfy_shot_engine", "profile_id": "x"}},
        )
    plan = cp.plan_full_apply(
        ckpt, lock, scene, mapping, policy,
        chunk_config={
            "execution_backend": {
                "backend": "comfy_shot_engine",
                "profile_id": WAN_PROFILE,
                "graph_sha256": "d" * 64,
                "shot_prompts": {"BOOK": "a book prompt"},
            }
        },
    )
    backend = plan["chunk_config"]["execution_backend"]
    assert backend["backend"] == "comfy_shot_engine"
    assert backend["capability"] == "source_video_motion_transfer"  # normalized default
    assert backend["require_accepted_anchor"] is False


# ── 19.2 — whole-shot/GROUP dispatch ─────────────────────────────────────────


def test_mf19_2_group_plan_is_one_unit_per_shot_with_all_members() -> None:
    ckpt, lock, scene, mapping, policy = _plan_inputs()
    plan = cp.plan_full_apply(
        ckpt, lock, scene, mapping, policy,
        chunk_config={
            "chunk_frames": 120,
            "overlap_frames": 4,
            "execution_backend": {
                "backend": "comfy_shot_engine",
                "profile_id": WAN_PROFILE,
                "graph_sha256": "d" * 64,
                "shot_prompts": {"BOOK": "a book prompt"},
            },
        },
    )
    assert len(plan["chunks"]) == 1, "one shot group => ONE generation, not one per person"
    chunk = plan["chunks"][0]
    assert chunk["shot_id"] == "BOOK"
    assert chunk["member_layer_ids"] == ["BOOK-P1", "BOOK-P2"]
    assert chunk["route"] == "shot_group"
    assert chunk["core_start_frame"] == 0 and chunk["core_end_frame"] == 119
    # legacy counterpart for the same inputs => 2 per-layer chunks
    legacy = cp.plan_full_apply(ckpt, lock, scene, mapping, policy, chunk_config={"chunk_frames": 120})
    assert len(legacy["chunks"]) == 2


def test_mf19_2_group_plan_refuses_a_shot_without_its_frozen_prompt() -> None:
    ckpt, lock, scene, mapping, policy = _plan_inputs()
    with pytest.raises(cp.ChunkPlanError):
        cp.plan_full_apply(
            ckpt, lock, scene, mapping, policy,
            chunk_config={
                "execution_backend": {
                    "backend": "comfy_shot_engine",
                    "profile_id": WAN_PROFILE,
                    "graph_sha256": "d" * 64,
                    "shot_prompts": {},
                }
            },
        )


def test_mf19_2_group_plan_splits_long_groups_but_keeps_all_members() -> None:
    ckpt, lock, scene, mapping, policy = _plan_inputs()
    plan = cp.plan_full_apply(
        ckpt, lock, scene, mapping, policy,
        chunk_config={
            "chunk_frames": 48,
            "overlap_frames": 4,
            "execution_backend": {
                "backend": "comfy_shot_engine",
                "profile_id": WAN_PROFILE,
                "graph_sha256": "d" * 64,
                "shot_prompts": {"BOOK": "a book prompt"},
            },
        },
    )
    assert [c["core_start_frame"] for c in plan["chunks"]] == [0, 48, 96]
    for chunk in plan["chunks"]:
        assert chunk["member_layer_ids"] == ["BOOK-P1", "BOOK-P2"]


# ── 19.3 — the shot executor + real Comfy door ───────────────────────────────


class ScriptedShotEngine:
    """CI fixture standing at the engine boundary; writes REAL mp4 bytes."""

    def __init__(
        self,
        managed_root: Path,
        *,
        frames: int,
        fps_num: int = 30,
        fps_den: int = 1,
        copy_source_as_output: Path | None = None,
        prompt_id: str = "pid-shot-0001",
        wall: float = 33.8,
        vram: int = 11224,
        extra_video_artifact: bool = False,
    ) -> None:
        self.managed_root = Path(managed_root)
        self.frames = frames
        self.fps_num = fps_num
        self.fps_den = fps_den
        self.copy_source_as_output = copy_source_as_output
        self.prompt_id = prompt_id
        self.wall = wall
        self.vram = vram
        self.extra_video_artifact = extra_video_artifact
        self.calls: list[dict[str, Any]] = []

    def run_shot(
        self,
        binding: Any,
        *,
        graph: dict,
        terminal_outputs: Any = None,
        expected_artifact_hashes: Any = None,
        shot_id: str = "",
        params: Any = None,
        decoded_facts: Any = None,
    ) -> ShotExecutionRecord:
        self.calls.append(
            {
                "binding": binding,
                "graph": graph,
                "terminal_outputs": terminal_outputs,
                "shot_id": shot_id,
            }
        )
        rel = f"media_engine/comfy_shot_engine/stage/out/{binding.identity.attempt_id}_00001_.mp4"
        target = self.managed_root / rel
        if self.copy_source_as_output is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.copy_source_as_output.read_bytes())
        else:
            _write_mp4(target, self.frames, seed=7, fps=float(self.fps_num) / float(self.fps_den))
        sha = _sha_file(target)
        size = target.stat().st_size
        artifacts = [
            EngineArtifactOutput(
                artifact_id="art-main",
                kind="video",
                media_type="video/mp4",
                sha256=sha,
                store_relative_path=rel,
                size_bytes=size,
                publishable=True,
                server_output_type="output",
            )
        ]
        if self.extra_video_artifact:
            aux_rel = rel.replace("_00001_", "_00003_")
            aux = self.managed_root / aux_rel
            aux.write_bytes(target.read_bytes())
            artifacts.append(
                EngineArtifactOutput(
                    artifact_id="art-aux",
                    kind="video",
                    media_type="video/mp4",
                    sha256=_sha_file(aux),
                    store_relative_path=aux_rel,
                    size_bytes=aux.stat().st_size,
                    publishable=True,
                    server_output_type="output",
                )
            )
        output = EngineOutputBinding(
            prompt_id=self.prompt_id,
            graph_sha256_server=binding.graph.workflow_hash,
            artifacts=tuple(artifacts),
            decoded=EngineDecodedFacts(
                decoded_frames=self.frames, first_pts_ticks=0, timebase="30/1", mapping=None
            ),
            audio={"mode": "source_remux", "source_artifact_id": "art-src"},
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
        pass


def _executor_request(
    tmp_path: Path,
    *,
    source_frames: int = 100,
    span: tuple[int, int] | None = None,
    profile_id: str = WAN_PROFILE,
    graph_sha256: str | None = None,
    parameters: dict[str, Any] | None = None,
    staged_anchor_sha: str | None = None,
    require_anchor: bool = False,
) -> tuple[dict[str, Any], Path, Path]:
    managed = tmp_path / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    source = _write_mp4(managed / "s10_full_apply" / "src" / "source.mp4", source_frames, seed=1)
    source_sha = _sha_file(source)
    anchor = managed / "anchor" / "anchor_book_p2_00001_.png"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_bytes(b"\x89PNG\r\n\x1a\n" + b"anchor-bytes" * 4)
    anchor_sha = _sha_file(anchor)
    span = span or (0, source_frames)
    graph_file = WT / GRAPH_REL
    graph_sha = graph_sha256 or _sha_file(graph_file)
    params = {"prompt": "a seated reader, opener book", "filename_prefix": "mf19/test"}
    if parameters is not None:
        params = parameters
    request: dict[str, Any] = {
        "workspace_id": "default",
        "project_id": "proj-1",
        "video_id": "vid-1",
        "shot_id": "BOOK",
        "chunk_id": "ck_mf19_0001",
        "attempt_id": "shot-attempt-0001",
        "backend": {
            "backend": "comfy_shot_engine",
            "profile_id": profile_id,
            "capability": "source_video_motion_transfer",
            "graph_file": GRAPH_REL,
            "graph_sha256": graph_sha,
            "output_node": "246",
            "seed": 582699151003550,
            "shot_prompts": {"BOOK": "a seated reader, opener book"},
            "require_accepted_anchor": require_anchor,
        },
        "graph": {"file": GRAPH_REL, "file_sha256": graph_sha},
        "parameters": params,
        "staged_inputs": {"anchor": {"relative_path": "anchor/anchor_book_p2_00001_.png", "sha256": anchor_sha}},
        "anchor": {"relative_path": "anchor/anchor_book_p2_00001_.png", "sha256": anchor_sha},
        "cast": [
            {
                "role": "BOOK-P1",
                "character_id": "ch-book",
                "pack_version_id": "pv1",
                "references": [
                    {
                        "key": "BOOK-P1@base",
                        "kind": "image",
                        "sha256": anchor_sha,
                        "store_relative_path": "anchor/anchor_book_p2_00001_.png",
                    }
                ],
            }
        ],
        "source": {
            "artifact_id": "art-src",
            "sha256": source_sha,
            "relative_path": "s10_full_apply/src/source.mp4",
            "size_bytes": source.stat().st_size,
            "fps": {"num": 30, "den": 1},
            "span": {"start_frame": span[0], "end_frame_exclusive": span[1]},
        },
        "output_contract": {
            "width": 640,
            "height": 368,
            "fps_num": 30,
            "fps_den": 1,
            "frame_count": span[1] - span[0],
            "container": "mp4",
            "video_codec": "h264",
            "audio": {"mode": "source_remux", "source_artifact_id": "art-src"},
        },
        "budget": {"resource_class": "gpu_12gb", "max_wall_seconds": 900.0},
    }
    if staged_anchor_sha is not None:
        request["staged_inputs"]["anchor"]["sha256"] = staged_anchor_sha
        request["anchor"]["sha256"] = staged_anchor_sha
    return request, managed, source


def test_mf19_3_ineligible_profile_refused_before_any_engine_call(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path, profile_id=VACE_PROFILE)
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_PROFILE_NOT_ELIGIBLE
    assert engine.calls == []  # no GPU work for an ineligible profile


def test_mf19_3_unknown_profile_refused(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path, profile_id="not-a-profile")
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN
    assert engine.calls == []


def test_mf19_3_backend_unsupported_is_typed(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path)
    request["backend"] = {"backend": "legacy_renderer"}
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_BACKEND_UNSUPPORTED


def test_mf19_3_graph_pin_mismatch_refused(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path, graph_sha256="e" * 64)
    request["graph"]["file_sha256"] = "e" * 64
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_GRAPH_PIN_MISMATCH


def test_mf19_3_undeclared_parameter_refused(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(
        tmp_path, parameters={"prompt": "p", "not_a_param": "x"}
    )
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_GRAPH_PARAMETER_MISSING


def test_mf19_3_staged_anchor_digest_mismatch_refused(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path, staged_anchor_sha="f" * 64)
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_INPUT_DIGEST_MISMATCH


def test_mf19_3_accepted_run_harvests_output_hashes_and_provenance(tmp_path: Path) -> None:
    request, managed, source = _executor_request(tmp_path)
    engine = ScriptedShotEngine(managed, frames=100)
    result = sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert result["verdict"] == "accepted"
    assert result["prompt_id"] == "pid-shot-0001"
    assert result["output_sha256"] != request["source"]["sha256"]
    # the engine received the PATCHED graph through its declared pointers
    sent = engine.calls[0]["graph"]
    assert sent["240"]["inputs"]["file"].startswith("shotwin_")
    assert sent["672:582"]["inputs"]["text"] == "a seated reader, opener book"
    assert sent["672:597"]["inputs"]["noise_seed"] == 582699151003550
    assert sent["246"]["inputs"]["filename_prefix"] == "mf19/test"
    # the durable record is on disk and pins the receipt + output hashes
    record_path = managed / result["record"]["relative_path"]
    assert record_path.is_file()
    doc = json.loads(record_path.read_text(encoding="utf-8"))
    assert doc["schema_version"] == sre.SHOT_RENDER_SCHEMA
    assert doc["verdict"] == "accepted"
    assert doc["receipt"]["prompt_id"] == "pid-shot-0001"
    assert doc["output"]["sha256"] == result["output_sha256"]
    assert doc["output"]["is_source_copy"] is False
    assert doc["graph"]["object_sha256_submitted"] == sre._graph_object_sha256(
        engine.calls[0]["graph"]
    )


def test_mf19_3_source_returned_as_output_is_refused(tmp_path: Path) -> None:
    request, managed, source = _executor_request(tmp_path)
    engine = ScriptedShotEngine(managed, frames=100, copy_source_as_output=source)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_SOURCE_RETURNED_AS_OUTPUT
    # the rejected record is durable so consumers can see WHY
    rejected = list((managed / "shot_render" / "BOOK").glob("*.json"))
    assert rejected and json.loads(rejected[0].read_text(encoding="utf-8"))["verdict"] == "rejected"


def test_mf19_3_main_artifact_selected_among_multiple_videos(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path)
    engine = ScriptedShotEngine(managed, frames=100, extra_video_artifact=True)
    result = sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert result["output_relative_path"].endswith("_00001_.mp4")


def test_mf19_3_require_accepted_anchor_without_manifest_is_typed(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path, require_anchor=True)
    engine = ScriptedShotEngine(managed, frames=100)
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_ANCHOR_GATE_REFUSED
    assert engine.calls == []


def test_mf19_3_frame_mismatch_is_refused(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path)
    engine = ScriptedShotEngine(managed, frames=90)  # contract says 100
    with pytest.raises(sre.ShotRenderRefusal) as exc:
        sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    assert exc.value.code is sre.ShotRenderRefusalCode.SHOT_OUTPUT_FRAME_MISMATCH


def test_mf19_3_partial_span_window_is_frame_accurate(tmp_path: Path) -> None:
    request, managed, _ = _executor_request(tmp_path, source_frames=100, span=(10, 40))
    request["output_contract"]["frame_count"] = 30
    engine = ScriptedShotEngine(managed, frames=30)
    result = sre.run_shot_render(managed_root=managed, request=request, engine=engine)
    window = result["window"]
    assert window["mode"] == "frame_slice_reencode"
    assert window["span"] == [10, 40]
    staged = managed / window["relative_path"]
    assert staged.is_file() and _sha_file(staged) == window["sha256"]


# ── 19.4 — publication gates (stitch) ────────────────────────────────────────


class _StitchFixture:
    def __init__(self, tmp_path: Path) -> None:
        self.managed = tmp_path / "managed"
        self.managed.mkdir(parents=True, exist_ok=True)
        self.db = tmp_path / "stitch.db"
        self.engine = create_engine(f"sqlite+pysqlite:///{self.db}")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE artifact(id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT,"
                    " relative_path TEXT, state TEXT, sha256 TEXT, size_bytes INTEGER, revision INTEGER)"
                )
            )

    def session_factory(self) -> Any:
        from sqlalchemy.orm import sessionmaker

        return sessionmaker(bind=self.engine)

    def add_chunk_artifact(
        self, *, chunk_id: str, rel: str, data_frames: int, seed: int = 5
    ) -> dict[str, Any]:
        path = _write_mp4(self.managed / rel, data_frames, seed=seed)
        sha = _sha_file(path)
        art_id = f"art-{chunk_id}"
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256,"
                    " size_bytes, revision) VALUES (:id,'default','video',:rel,'ready',:sha,:sz,1)"
                ),
                {"id": art_id, "rel": rel, "sha": sha, "sz": path.stat().st_size},
            )
        return {"artifact_id": art_id, "rel": rel, "sha": sha, "path": path, "frames": data_frames}


def _sidecar(fx: _StitchFixture, rel: str, frames: int) -> None:
    from app.services.renderer_routes.composite import canonical_frame_sha256, decode_rgb_frames

    decoded = decode_rgb_frames(fx.managed / rel)
    jobs._write_evidence_sidecar(
        fx.managed,
        Path(rel),
        {
            "decoded_sha256": canonical_frame_sha256(decoded),
            "decoded_frame_count": len(decoded),
            "fps_num": 30,
            "fps_den": 1,
            "layer_id": "grp_BOOK",
            "shot_id": "BOOK",
            "route": "shot_group",
            "effective_adapter": "comfy_shot_engine",
        },
    )


def test_mf19_4_stitch_requires_every_chunk_verified(tmp_path: Path) -> None:
    fx = _StitchFixture(tmp_path)
    source = _write_mp4(fx.managed / "src" / "source.mp4", 60, seed=1)
    manifest = {
        "source_media_rel": "src/source.mp4",
        "source_media_sha256": _sha_file(source),
        "source_media_size_bytes": source.stat().st_size,
    }
    chunks = [
        {"chunk_id": "ck1", "core_start_frame": 0, "core_end_frame": 29, "verified": False, "artifact_id": None},
        {"chunk_id": "ck2", "core_start_frame": 30, "core_end_frame": 59, "verified": True, "artifact_id": None},
    ]
    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        jobs._stitch_shot_chunks(
            managed_root=fx.managed, run_id="run-1", chunks=chunks,
            session_factory=fx.session_factory(), ws="default",
            fps_num=30, fps_den=1, authority={}, manifest=manifest, frame_count=60,
        )
    assert "STITCH_CHUNK_NOT_VERIFIED" in str(exc.value)


def test_mf19_4_stitch_tampered_artifact_fails_closed(tmp_path: Path) -> None:
    fx = _StitchFixture(tmp_path)
    source = _write_mp4(fx.managed / "src" / "source.mp4", 60, seed=1)
    a = fx.add_chunk_artifact(chunk_id="ck1", rel="chunks/ck1.mp4", data_frames=60)
    _sidecar(fx, a["rel"], 60)
    # tamper the published bytes AFTER the evidence sidecar was written
    (fx.managed / a["rel"]).write_bytes(b"tampered")
    chunks = [
        {
            "chunk_id": "ck1", "core_start_frame": 0, "core_end_frame": 59,
            "verified": True, "artifact_id": a["artifact_id"], "content_hash": "a" * 64,
        }
    ]
    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        jobs._stitch_shot_chunks(
            managed_root=fx.managed, run_id="run-1", chunks=chunks,
            session_factory=fx.session_factory(), ws="default",
            fps_num=30, fps_den=1,
            authority={}, manifest={
                "source_media_rel": "src/source.mp4",
                "source_media_sha256": _sha_file(source),
                "source_media_size_bytes": source.stat().st_size,
            },
            frame_count=60,
        )
    assert "STITCH_CHUNK_ARTIFACT_INVALID" in str(exc.value)


def test_mf19_4_stitch_source_returned_is_refused(tmp_path: Path) -> None:
    fx = _StitchFixture(tmp_path)
    source = _write_mp4(fx.managed / "src" / "source.mp4", 60, seed=1)
    rel = "chunks/source_copy.mp4"
    copy_path = fx.managed / rel
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    copy_path.write_bytes(source.read_bytes())
    art_id = "art-copy"
    with fx.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256,"
                " size_bytes, revision) VALUES (:id,'default','video',:rel,'ready',:sha,:sz,1)"
            ),
            {"id": art_id, "rel": rel, "sha": _sha_file(copy_path), "sz": copy_path.stat().st_size},
        )
    _sidecar(fx, rel, 60)
    chunks = [
        {
            "chunk_id": "ck1", "core_start_frame": 0, "core_end_frame": 59,
            "verified": True, "artifact_id": art_id, "content_hash": "a" * 64,
        }
    ]
    dev_null = fx.managed / "src" / "source_media.mp4"
    dev_null.write_bytes(source.read_bytes())  # manifest source == the chunk bytes
    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        jobs._stitch_shot_chunks(
            managed_root=fx.managed, run_id="run-1", chunks=chunks,
            session_factory=fx.session_factory(), ws="default",
            fps_num=30, fps_den=1,
            authority={}, manifest={
                "source_media_rel": "src/source_media.mp4",
                "source_media_sha256": _sha_file(dev_null),
                "source_media_size_bytes": dev_null.stat().st_size,
            },
            frame_count=60,
        )
    assert "STITCH_CHUNK_IS_SOURCE" in str(exc.value)


def test_mf19_4_stitch_success_keeps_source_frames_for_uncovered_ranges(tmp_path: Path) -> None:
    fx = _StitchFixture(tmp_path)
    source = _write_mp4(fx.managed / "src" / "source.mp4", 60, seed=1)
    a = fx.add_chunk_artifact(chunk_id="ck1", rel="chunks/ck1.mp4", data_frames=30)
    _sidecar(fx, a["rel"], 30)
    chunks = [
        {
            "chunk_id": "ck1", "core_start_frame": 0, "core_end_frame": 29,
            "verified": True, "artifact_id": a["artifact_id"], "content_hash": "a" * 64,
        }
    ]
    rel, sha, size, meta = jobs._stitch_shot_chunks(
        managed_root=fx.managed, run_id="run-1", chunks=chunks,
        session_factory=fx.session_factory(), ws="default",
        fps_num=30, fps_den=1,
        authority={}, manifest={
            "source_media_rel": "src/source.mp4",
            "source_media_sha256": _sha_file(source),
            "source_media_size_bytes": source.stat().st_size,
        },
        frame_count=60,
    )
    assert meta["generated_frames"] == 30
    assert meta["source_frames_verbatim"] == 30
    out = fx.managed / rel
    assert out.is_file() and sha == _sha_file(out)
    from app.services.renderer_routes.composite import decode_rgb_frames

    assert len(decode_rgb_frames(out)) == 60
    assert sha != _sha_file(source)


def test_mf19_4_backend_of_run_row_reads_frozen_manifest() -> None:
    assert jobs._execution_backend_of({"chunk_config": {"chunk_frames": 48}}) == {}
    backend = {"backend": "comfy_shot_engine", "profile_id": WAN_PROFILE}
    assert jobs._execution_backend_of({"chunk_config": {"execution_backend": backend}}) == backend


def test_mf19_3_chunk_identity_derives_the_planner_id_from_the_db_row() -> None:
    """The comfy branch must recover the planner's canonical ck_ id from the row.

    Regression for the first REAL RUN attempt: `_list_chunks` rows carry the
    canonical id inside `natural_key` ("s10_chunk:<run>:<ck_...>"), so the
    dispatch must derive it instead of failing on a missing `chunk_id` key.
    """
    shot_id, chunk_id = jobs._shot_chunk_identity(
        {"shot_id": "BOOK", "natural_key": "s10_chunk:run-1:ck_abcdef0123456789", "id": "row-1"}
    )
    assert (shot_id, chunk_id) == ("BOOK", "ck_abcdef0123456789")
    # an explicit chunk_id wins when present
    assert jobs._shot_chunk_identity(
        {"shot_id": "BOOK", "chunk_id": "ck_direct", "natural_key": "s10_chunk:r:ck_other"}
    ) == ("BOOK", "ck_direct")
    # neither identity -> fail closed, never an invented id
    with pytest.raises(jobs.S10FullApplyJobError):
        jobs._shot_chunk_identity({"shot_id": "BOOK", "id": "row-1"})
