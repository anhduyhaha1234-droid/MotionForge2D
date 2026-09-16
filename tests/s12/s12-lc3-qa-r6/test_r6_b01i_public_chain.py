"""B01-I — downstream public product chain on the frozen integrated candidate.

QA-owned, bounded, ONE real chain on the frozen candidate tip.  Every
identity is returned by a PUBLIC HTTP route (no SQL/ORM seed, no private
handler shortcut, no fabricated approval):

    upload/analyze/import/proxy/scene -> DISCOVER_OBJECTS durable worker ->
    roles/segments -> character pack publish -> ProjectCast/ReskinConfig ->
    structural-lock producer -> ReskinConfig CAS pin -> S09 reapproval
    (full_apply_executable) -> S10 Full Apply -> original-audio attach ->
    QC check run (readiness ready) -> S12 context/preflight/submit ->
    durable s12_export worker -> production publisher -> result/media ->
    replay/reload with zero extra Job/Run rows.

Evidence: S12_REVIEW_OUT is created exclusively per run (never reused) and
receives every raw request/response, run counts, media probes and summary.
Without the frozen env pins the same node verifies the newest recorded run
instead of executing (the dispatch stays gated, never a silent pass).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

RUN_ENV_KEYS = ("S12_REVIEW_OUT", "S12_R6_CANDIDATE_ROOT", "S12_R6_EXPECTED_CANDIDATE_SHA")
_MISSING_ENV = [key for key in RUN_ENV_KEYS if not os.environ.get(key)]

B01I_OUTPUT_ROOT = Path(
    "C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
    "s12-r7-two-managers/20260916T0351Z/B/QA/chain"
)
RUNTIME_ROOT_TEMPLATE = (
    "C:/Users/Admin/Documents/Codex/work/s12r7/0351/B/QA/chain/<run_id>"
)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _rec(response: Any, request: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    record: dict[str, Any] = {"status_code": response.status_code, "body": body}
    if request is not None:
        record["request"] = request
    return record


def _poll(
    client: Any,
    path: str,
    *,
    params: dict[str, str] | None = None,
    terminal: set[str],
    timeout_seconds: float,
    interval_seconds: float = 0.5,
    state_key: str = "status",
) -> dict[str, Any]:
    started = time.monotonic()
    reads: list[dict[str, Any]] = []
    while True:
        response = client.get(path, params=params)
        item = _rec(response)
        reads.append(item)
        body = item.get("body")
        state = body.get(state_key) if isinstance(body, dict) else None
        if body is not None and isinstance(body, dict):
            state = state or body.get("chain_status") or body.get("run_state") or body.get("state")
        if state in terminal:
            break
        if time.monotonic() - started >= timeout_seconds:
            break
        time.sleep(interval_seconds)
    return {
        "timeout_seconds": timeout_seconds,
        "read_count": len(reads),
        "reads": reads,
        "final": reads[-1] if reads else None,
    }


def _ffprobe(path: Path) -> dict[str, Any]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if probe.returncode != 0:
        return {"error": probe.stderr, "returncode": probe.returncode}
    return json.loads(probe.stdout)


def _media_facts(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams", []) if isinstance(probe, dict) else []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = probe.get("format", {}) if isinstance(probe, dict) else {}
    facts: dict[str, Any] = {
        "duration_s": float(fmt.get("duration") or 0.0),
        "size_bytes": int(fmt.get("size") or 0),
    }
    if video:
        rate = str(video.get("avg_frame_rate") or "0/0")
        num, _, den = rate.partition("/")
        fps = float(num) / float(den) if den and float(den) else 0.0
        facts["video"] = {
            "codec": video.get("codec_name"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": round(fps, 4),
            "frame_count": int(video.get("nb_frames") or 0),
        }
    if audio:
        facts["audio"] = {
            "codec": audio.get("codec_name"),
            "channels": int(audio.get("channels") or 0),
            "sample_rate": int(audio.get("sample_rate") or 0),
            "duration_s": float(audio.get("duration") or 0.0),
        }
    else:
        facts["audio"] = None
    return facts


def _make_fixture(root: Path) -> Path:
    """4s / 30fps / 640x360 single-scene source with a 440 Hz audio track.

    Single scene keeps the sanctioned deterministic-identity extraction
    adapter coherent (it stores scene-local frame ranges per scene, which a
    multi-scene source turns into overlapping global ranges).  The multi-
    scene overlap is recorded as an observation in the lane report.
    """
    fixture = root / "b01i-source-4s.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=640x360:r=30:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(fixture),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fixture ffmpeg failed rc={result.returncode}: {result.stderr}")
    return fixture


def _verify_recorded_run() -> None:
    """Gated dispatch: verify the newest recorded run instead of executing."""
    runs = (
        sorted((p for p in B01I_OUTPUT_ROOT.iterdir() if p.is_dir()), key=lambda p: p.name)
        if B01I_OUTPUT_ROOT.is_dir()
        else []
    )
    recorded = [p for p in runs if (p / "b01i-summary.json").is_file()]
    assert recorded, (
        "B01-I dispatch gated: frozen env pins absent and no recorded run under "
        f"{B01I_OUTPUT_ROOT}; provide S12_REVIEW_OUT/S12_R6_CANDIDATE_ROOT/"
        "S12_R6_EXPECTED_CANDIDATE_SHA to execute"
    )
    latest = recorded[-1]
    summary = json.loads((latest / "b01i-summary.json").read_text(encoding="utf-8"))
    chain = json.loads((latest / "b01i-chain.json").read_text(encoding="utf-8"))
    assert chain["status"] == summary["status"]
    for name, digest in summary["evidence_sha256"].items():
        assert _sha256_file(latest / name) == digest, name
    assert summary["run_id"] == latest.name
    status = summary["status"]
    if status.startswith("FAILED") or status.startswith("BLOCKED"):
        blocked = summary.get("stage_status", {}).get("blocked")
        raise AssertionError(
            f"Recorded chain run {latest.name} is {status} at "
            f"{blocked or 'unknown stage'}: {summary.get('failure')}"
        )
    assert status in {"PASS", "PASS_WITH_FINDINGS"}, status
    assert summary["stages"]["s12_run_status"] == "completed"
    assert summary["replay"]["extra_runs"] == 0 and summary["replay"]["extra_jobs"] == 0


def test_b01i_public_product_chain_submit_worker_publisher_result_media_ui() -> None:
    if _MISSING_ENV:
        _verify_recorded_run()
        return

    s12_review_out = Path(os.environ["S12_REVIEW_OUT"])
    candidate_root = Path(os.environ["S12_R6_CANDIDATE_ROOT"]).resolve()
    expected_sha = os.environ["S12_R6_EXPECTED_CANDIDATE_SHA"]
    run_id = s12_review_out.name
    runtime_root = Path(
        os.environ.get("S12_R6_RUNTIME_ROOT", RUNTIME_ROOT_TEMPLATE.replace("<run_id>", run_id))
    )
    runtime_root.mkdir(parents=True, exist_ok=True)

    # Isolated runtime BEFORE any app import (E02 lesson): env, DB, roots.
    os.environ["MOTIONFORGE_ROOT"] = str(runtime_root)
    os.environ["MOTIONFORGE_OUTPUT"] = str(runtime_root / "output")
    os.environ["MOTIONFORGE_MODELS"] = str(runtime_root / "models")
    os.environ.pop("MOTIONFORGE_DATABASE_URL", None)
    os.environ["MOTIONFORGE_EXTRACTION_QA_MODE"] = "1"
    os.environ["MOTIONFORGE_EXTRACTION_PROVIDER"] = "deterministic-identity"

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.api import deps
    from app.api.app import app
    from app.config import AppConfig
    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.models import (
        ApplyCheckpoint,
        Artifact,
        Job,
        Project,
        ReskinConfig,
        S10FullApplyPublication,
        S10FullApplyRun,
        S12ExportRun,
        StructuralLockManifest,
        VideoItem,
    )
    from app.workflow.analyze_orchestrator import reset_analyze_orchestrator
    from app.workflow.job_service import JobService
    from app.workflow.project_workflow import ProjectWorkflowService

    def git_head(root: Path) -> str:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            check=True,
            text=True,
        )
        return out.stdout.strip()

    chain: dict[str, Any] = {
        "lane": "S12-LC3-QA",
        "node": (
            "tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py::"
            "test_b01i_public_product_chain_submit_worker_publisher_result_media_ui"
        ),
        "run_id": run_id,
        "evidence_root": str(s12_review_out),
        "runtime_root": str(runtime_root),
        "candidate_root": str(candidate_root),
        "candidate_sha_expected": expected_sha,
        "status": None,
        "stages": {},
        "identities": {},
        "counts": {},
        "replay": {},
        "flags": {},
    }
    stage_order: list[str] = []

    def stage(name: str, payload: dict[str, Any]) -> None:
        chain["stages"][name] = payload
        stage_order.append(name)

    db_path = runtime_root / "data" / "b01i.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    alembic_cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(alembic_cfg, "head")

    engine = create_engine_for_path(db_path)
    factory = create_session_factory(engine)
    managed_root = runtime_root / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    config = AppConfig(
        project_root=runtime_root,
        models_dir=runtime_root / "models",
        output_dir=runtime_root / "output",
    )
    service = JobService(factory, managed_root=managed_root)

    def counts() -> dict[str, int]:
        models = {
            "projects": Project,
            "video_items": VideoItem,
            "jobs": Job,
            "artifacts": Artifact,
            "structural_lock_manifests": StructuralLockManifest,
            "reskin_configs": ReskinConfig,
            "apply_checkpoints": ApplyCheckpoint,
            "s10_full_apply_runs": S10FullApplyRun,
            "s10_publications": S10FullApplyPublication,
            "s12_export_runs": S12ExportRun,
        }
        with factory() as session:
            return {
                name: int(session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }

    saved = (
        deps._config,
        deps._job_service,
        deps._project_service,
        deps._video_service,
        getattr(deps, "_lifecycle_db", None),
        deps._project_wf,
    )
    old_env = {
        key: os.environ.get(key)
        for key in ("MOTIONFORGE_EXTRACTION_QA_MODE", "MOTIONFORGE_EXTRACTION_PROVIDER")
    }
    failure: Exception | None = None
    try:
        chain["candidate_sha_actual"] = git_head(candidate_root)
        assert chain["candidate_sha_actual"] == expected_sha, (
            f"candidate moved: {chain['candidate_sha_actual']} != {expected_sha}"
        )
        deps._config = config
        deps._job_service = service
        deps._project_service = None
        deps._video_service = None
        deps._lifecycle_db = db_path
        deps._project_wf = ProjectWorkflowService(config)
        with TestClient(app, raise_server_exceptions=False) as client:
            service.start_worker()
            chain["worker_started"] = bool(service.worker_running)
            assert chain["worker_started"], "durable worker did not start"
            chain["counts"]["before_chain"] = counts()

            fixture = _make_fixture(runtime_root)
            source_probe = _ffprobe(fixture)
            source_facts = _media_facts(source_probe)
            chain["source_media"] = {
                "path": str(fixture),
                "sha256": _sha256_file(fixture),
                "facts": source_facts,
            }
            assert source_facts.get("audio"), "fixture must carry audio"

            # 1) legacy public project -> upload -> analyze/import/proxy/scene
            project = client.post("/api/projects", json={"name": "S12-LC3-R6-B01I"})
            stage(
                "legacy_create_project",
                _rec(project, {"method": "POST", "path": "/api/projects"}),
            )
            assert project.status_code == 201, project.text
            project_id = project.json()["project_id"]
            with fixture.open("rb") as handle:
                upload = client.post(
                    f"/api/projects/{project_id}/video",
                    files={"file": (fixture.name, handle, "video/mp4")},
                )
            stage(
                "legacy_upload",
                _rec(upload, {"method": "POST", "path": f"/api/projects/{project_id}/video"}),
            )
            assert upload.status_code == 200, upload.text
            analyze = client.post(
                f"/api/projects/{project_id}/analyze",
                json={"generation": "1", "title": "B01-I public chain"},
            )
            stage(
                "legacy_analyze_submit",
                _rec(
                    analyze,
                    {
                        "method": "POST",
                        "path": f"/api/projects/{project_id}/analyze",
                        "json": {"generation": "1"},
                    },
                ),
            )
            assert analyze.status_code == 200, analyze.text
            analyze_poll = _poll(
                client,
                f"/api/projects/{project_id}/analyze",
                params={"generation": "1"},
                terminal={"completed", "failed", "cancelled"},
                timeout_seconds=180.0,
                state_key="chain_status",
            )
            stage("legacy_analyze_chain", analyze_poll)
            analyze_body = analyze_poll["final"]["body"] if analyze_poll["final"] else {}
            assert (
                isinstance(analyze_body, dict)
                and analyze_body.get("chain_status") == "completed"
            ), "legacy analyze chain did not complete"
            video_id = str(analyze_body["video_item_id"])
            generation = str(analyze_body.get("generation") or "1")
            chain["identities"].update(
                {
                    "project_id": project_id,
                    "project_id_shape": "12-hex-legacy",
                    "video_item_id": video_id,
                    "source_artifact_id": analyze_body.get("source_artifact_id"),
                    "proxy_artifact_id": analyze_body.get("proxy_artifact_id"),
                    "generation": generation,
                }
            )

            # 2) DISCOVER_OBJECTS durable worker
            extraction = client.post(
                "/api/v2/object-intelligence/extraction",
                json={
                    "project_id": project_id,
                    "video_item_id": video_id,
                    "generation": generation,
                },
            )
            stage(
                "extraction_submit",
                _rec(
                    extraction,
                    {
                        "method": "POST",
                        "path": "/api/v2/object-intelligence/extraction",
                        "json": {"project_id": project_id, "video_item_id": video_id},
                    },
                ),
            )
            assert extraction.status_code == 201, extraction.text
            extraction_id = extraction.json()["job_id"]
            extraction_poll = _poll(
                client,
                f"/api/v2/object-intelligence/extraction/{extraction_id}",
                terminal={"completed", "failed", "cancelled"},
                timeout_seconds=180.0,
            )
            stage("extraction_worker", {"job_id": extraction_id, "poll": extraction_poll})
            extraction_final = extraction_poll["final"]["body"] if extraction_poll["final"] else {}
            assert extraction_final.get("status") == "completed", "extraction did not complete"
            stage(
                "extraction_outputs",
                _rec(client.get(f"/api/v2/object-intelligence/extraction/{extraction_id}/outputs")),
            )
            stage(
                "extraction_graph",
                _rec(client.get(f"/api/v2/object-intelligence/extraction/{extraction_id}/graph")),
            )

            roles_read = client.get(
                "/api/v2/object-intelligence/roles", params={"video_item_id": video_id}
            )
            stage("roles_read", _rec(roles_read))
            assert roles_read.status_code == 200, roles_read.text
            roles = roles_read.json().get("roles", [])
            assert roles, "no public current ObjectRole after extraction"
            role_ids: list[str] = []
            for index, role in enumerate(roles):
                role_id = str(role["id"])
                role_ids.append(role_id)
                role_update = client.patch(
                    f"/api/v2/object-intelligence/roles/{role_id}",
                    json={"revision": int(role["revision"]), "status": "confirmed"},
                )
                stage(f"role_confirm_{index}", _rec(role_update))
                assert role_update.status_code == 200, role_update.text
                role_get = client.get(f"/api/v2/object-intelligence/roles/{role_id}")
                stage(f"role_detail_{index}", _rec(role_get))
                assert role_get.status_code == 200, role_get.text
            segments_read = client.get(
                "/api/v2/structural-evidence/segments", params={"video_item_id": video_id}
            )
            stage("structural_evidence_segments", _rec(segments_read))
            chain["identities"]["role_ids"] = role_ids

            # 3) per-role character packs (6 core pose slots -> published).
            #    Each role gets its OWN character + pack whose assets are the
            #    role's own extraction mask artifact: a layer must contribute
            #    pixels inside its own region, so sharing one role's asset
            #    across two different regions cannot compose truthfully.
            graph_segments = (chain["stages"]["extraction_graph"]["body"] or {}).get(
                "segments", []
            )
            role_mask = {
                str(seg.get("role_id")): str(seg.get("mask_artifact_id"))
                for seg in graph_segments
                if seg.get("role_id") and seg.get("mask_artifact_id")
            }
            character_ids: list[str] = []
            version_ids: list[str] = []
            artifact_ids: list[str] = []
            for index, role_id in enumerate(role_ids):
                mask_artifact = role_mask.get(role_id)
                assert mask_artifact, f"role {role_id} has no mask artifact to attach"
                character = client.post(
                    "/api/v2/characters",
                    json={
                        "name": f"B01-I Character {index}",
                        "code": f"B01I_{project_id[:8]}_{index}",
                    },
                )
                stage(f"character_create_{index}", _rec(character))
                assert character.status_code == 201, character.text
                character_id = character.json()["id"]
                version = client.post(f"/api/v2/characters/{character_id}/versions")
                stage(f"character_version_create_{index}", _rec(version))
                assert version.status_code == 201, version.text
                version_id = version.json()["id"]
                for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
                    attach = client.post(
                        f"/api/v2/characters/versions/{version_id}/assets",
                        json={"pose_slot": slot, "artifact_id": mask_artifact},
                    )
                    stage(f"asset_attach_{index}_{slot}", _rec(attach))
                    assert attach.status_code == 200, attach.text
                validation = client.get(f"/api/v2/characters/versions/{version_id}/validation")
                stage(f"character_validation_{index}", _rec(validation))
                publish = client.post(
                    f"/api/v2/characters/versions/{version_id}/publish",
                    json={"revision": int(version.json()["revision"])},
                )
                stage(f"character_publish_{index}", _rec(publish))
                assert publish.status_code == 200, publish.text
                character_ids.append(character_id)
                version_ids.append(version_id)
                artifact_ids.append(mask_artifact)
            chain["identities"].update(
                {
                    "character_ids": character_ids,
                    "pack_version_ids": version_ids,
                    "pack_artifact_ids": artifact_ids,
                }
            )

            # 4) ProjectCast + ReskinConfig (role mapping for the producer)
            params = {
                "anchor": {"x": 0.5, "y": 0.5},
                "scale": 1.0,
                "fit_mode": "contain",
                "clip_mode": "asset_alpha",
                "offset": {"x": 0.0, "y": 0.0},
                "rotation_offset_deg": 0.0,
                "opacity": 1.0,
            }
            cast_ids: list[str] = []
            config_ids: list[str] = []
            config_revisions: dict[str, int] = {}
            for index, role_id in enumerate(role_ids):
                cast = client.post(
                    "/api/v2/project-cast",
                    json={
                        "project_id": project_id,
                        "object_role_id": role_id,
                        "character_id": character_ids[index],
                        "pack_version_id": version_ids[index],
                        "idempotency_key": f"b01i-cast-{index}-{project_id}",
                    },
                )
                stage(f"project_cast_create_{index}", _rec(cast))
                assert cast.status_code in (200, 201), cast.text
                cast_ids.append(cast.json()["id"])
                config_create = client.post(
                    "/api/v2/reskin-configs",
                    json={
                        "project_id": project_id,
                        "object_role_id": role_id,
                        "character_id": character_ids[index],
                        "pack_version_id": version_ids[index],
                        "cast_mapping_id": cast_ids[-1],
                        "params": params,
                        "idempotency_key": f"b01i-config-{index}-{project_id}",
                    },
                )
                stage(f"reskin_config_create_{index}", _rec(config_create))
                assert config_create.status_code in (200, 201), config_create.text
                config_body = config_create.json()
                config_ids.append(str(config_body["id"]))
                config_revisions[str(config_body["id"])] = int(config_body["revision"])
            chain["identities"]["reskin_config_ids"] = config_ids

            # 5) structural-lock producer (B01)
            producer = client.post(
                f"/api/v2/projects/{project_id}/videos/{video_id}/structural-lock", json={}
            )
            stage(
                "producer_structural_lock",
                _rec(
                    producer,
                    {
                        "method": "POST",
                        "path": f"/api/v2/projects/{project_id}/videos/{video_id}/structural-lock",
                        "json": {},
                    },
                ),
            )
            assert producer.status_code == 201, (
                f"producer denied: {producer.status_code} {producer.text[:2000]}"
            )
            producer_body = producer.json()
            manifest_id = str(producer_body["manifest_id"])
            manifest_hash = str(producer_body["manifest_hash"])
            chain["identities"].update(
                {
                    "manifest_id": manifest_id,
                    "manifest_hash": manifest_hash,
                    "manifest_generation": producer_body.get("source_generation"),
                    "manifest_version": producer_body.get("version"),
                    "segment_count": producer_body.get("segment_count"),
                    "route_decisions_created": producer_body.get("route_decisions_created"),
                }
            )
            assert producer_body.get("segment_count", 0) >= 1, "empty manifest is not a pass"

            # 6) CAS pin + S09 reapproval (full_apply_executable)
            pinned_revisions: dict[str, int] = {}
            for index, config_id in enumerate(config_ids):
                pin = client.patch(
                    f"/api/v2/reskin-configs/{config_id}",
                    json={
                        "revision": config_revisions[config_id],
                        "structural_lock_manifest_id": manifest_id,
                    },
                )
                stage(f"reskin_config_pin_{index}", _rec(pin))
                assert pin.status_code == 200, pin.text
                pinned = pin.json()
                assert pinned.get("structural_lock_manifest_id") == manifest_id, pinned
                pinned_revisions[config_id] = int(pinned["revision"])
            config_id = config_ids[0]
            pinned_revision = pinned_revisions[config_id]
            chain["identities"]["reskin_config_id"] = config_id

            reapprove = client.post(
                "/api/v2/s09-approvals/reapprove",
                params={"workspace_id": "default"},
                json={
                    "reskin_config_id": config_id,
                    "expected_reskin_revision": pinned_revision,
                    "pack_version_ids": version_ids,
                    "idempotency_key": f"b01i-reapprove-{project_id}",
                    "note": "B01-I public chain; not a product approval",
                },
            )
            stage("s09_reapproval", _rec(reapprove))
            assert reapprove.status_code in (200, 201), reapprove.text
            checkpoint = reapprove.json()
            checkpoint_id = str(checkpoint["id"])
            checkpoint_hash = str(checkpoint["checkpoint_hash"])
            checkpoint_blob = json.dumps(checkpoint)
            chain["flags"]["full_apply_executable"] = (
                "full_apply_executable\": true" in checkpoint_blob
                or '"full_apply_executable": true' in checkpoint_blob
            )
            timeline_in_checkpoint = (
                '"timeline"' in checkpoint_blob
                and "s09.full-apply-timeline" in checkpoint_blob
            )
            chain["flags"]["timeline_in_checkpoint"] = timeline_in_checkpoint
            assert timeline_in_checkpoint, (
                "R7 checkpoint payload carries no frozen timeline block"
            )
            chain["identities"]["apply_checkpoint_id"] = checkpoint_id
            chain["identities"]["checkpoint_hash"] = checkpoint_hash

            authority_read = client.get(
                f"/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority",
                params={"workspace_id": "default"},
            )
            stage("full_apply_authority_read", _rec(authority_read))
            assert authority_read.status_code == 200, authority_read.text
            authority_blob = json.dumps(authority_read.json())
            chain["flags"]["authority_executable"] = (
                '"executable": true' in authority_blob or '"executable":true' in authority_blob
            )
            authority_body = authority_read.json()
            timeline = authority_body.get("timeline")
            if not isinstance(timeline, dict) or not timeline:
                ffa = authority_body.get("full_apply_authority")
                if isinstance(ffa, dict):
                    timeline = ffa.get("timeline")
            if not isinstance(timeline, dict) or not timeline:
                snapshot = authority_body.get("snapshot")
                if isinstance(snapshot, str):
                    with contextlib.suppress(Exception):
                        snapshot = json.loads(snapshot)
                if isinstance(snapshot, dict):
                    timeline = (snapshot.get("full_apply_authority") or {}).get("timeline")
            assert isinstance(timeline, dict) and timeline, (
                "authority carries no frozen timeline block"
            )
            chain["timeline"] = {
                "timeline_version": timeline.get("timeline_version"),
                "frame_count": timeline.get("frame_count"),
                "fps_num": timeline.get("fps_num"),
                "fps_den": timeline.get("fps_den"),
                "shots": timeline.get("shots"),
                "occurrences": timeline.get("occurrences"),
            }
            chain["flags"]["timeline_shots"] = len(timeline.get("shots") or [])
            chain["flags"]["timeline_occurrences"] = len(timeline.get("occurrences") or [])
            assert chain["flags"]["timeline_shots"] >= 1, chain["timeline"]
            assert chain["flags"]["timeline_occurrences"] >= 1, chain["timeline"]
            assert timeline.get("timeline_version") == "s09.full-apply-timeline/v1", (
                timeline.get("timeline_version")
            )

            # 7) S10 Full Apply (durable job -> completed publication)
            full_apply = client.post(
                f"/api/v2/projects/{project_id}/full-apply",
                params={"workspace_id": "default"},
                json={
                    "video_item_id": video_id,
                    "apply_checkpoint_id": checkpoint_id,
                    "expected_checkpoint_hash": checkpoint_hash,
                    "expected_checkpoint_revision": pinned_revision,
                },
            )
            stage("s10_full_apply_submit", _rec(full_apply))
            assert full_apply.status_code == 202, full_apply.text
            fa_body = full_apply.json()
            fa_run_id = str(fa_body.get("run_id") or fa_body.get("id"))
            chain["identities"]["s10_run_id"] = fa_run_id
            chain["identities"]["s10_plan_id"] = fa_body.get("plan_id")
            chain["flags"]["s10_submit_passed_prev_overlap_422"] = True
            fa_poll = _poll(
                client,
                f"/api/v2/full-apply/{fa_run_id}",
                terminal={"completed", "failed", "cancelled"},
                timeout_seconds=420.0,
            )
            stage("s10_full_apply_run", fa_poll)
            fa_final = fa_poll["final"]["body"] if fa_poll["final"] else {}
            assert fa_final.get("status") == "completed", (
                f"S10 full apply did not complete: {json.dumps(fa_final)[:2000]}"
            )
            chain["s10_final"] = fa_final
            stage("counts_after_s10", counts())
            chain["counts"]["after_s10"] = chain["stages"]["counts_after_s10"]

            # 7a) B06 per-layer decoded evidence sidecar (frozen Q9 format)
            sidecar_candidates = sorted(
                (managed_root / "s10_full_apply" / fa_run_id).glob("full_*.mp4.evidence.json")
            )
            assert sidecar_candidates, (
                f"no stitched evidence sidecar under s10_full_apply/{fa_run_id}"
            )
            sidecar_path = sidecar_candidates[0]
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            side_rows = sidecar.get("per_layer_evidence") or []
            q9_required = {
                "shot_id",
                "range",
                "layer_id",
                "role_id",
                "route",
                "visibility",
                "z_order",
                "artifact_sha256",
                "artifact_size_bytes",
                "region_norm",
                "region_px",
                "sampled_frames",
                "region_crop_sha256_before",
                "region_crop_sha256_after",
                "final_crop_sha256",
                "changed_pixel_count",
                "changed_ratio",
                "threshold",
                "verdict",
            }
            assert side_rows, "sidecar carries no per_layer_evidence rows"
            for row in side_rows:
                assert q9_required <= set(row), (q9_required - set(row))
                assert row["threshold"] == 0.01, row
                assert row["verdict"] == "contributed", row
                assert (
                    row["region_crop_sha256_before"] != row["region_crop_sha256_after"]
                ), row
            covering = [row for row in side_rows if row["range"][0] == 0]
            assert len({row["layer_id"] for row in covering}) >= 2, (
                "first chunk run must cover both co-active layers"
            )
            assert len({row["artifact_sha256"] for row in covering}) == len(covering), (
                "co-active rows must carry distinct layer artifacts (no dedup)"
            )
            chain["stages"]["s10_sidecar_evidence"] = {
                "path": str(sidecar_path),
                "sha256": _sha256_file(sidecar_path),
                "rows": len(side_rows),
                "layers": sorted({str(row["layer_id"]) for row in side_rows}),
                "decoded_frame_count": sidecar.get("decoded_frame_count"),
            }
            chain["flags"]["sidecar_rows"] = len(side_rows)
            chain["flags"]["sidecar_layers"] = len({row["layer_id"] for row in side_rows})
            with contextlib.suppress(Exception):
                (s12_review_out / "b01i-sidecar-sample.json").write_bytes(
                    sidecar_path.read_bytes()
                )

            # 7b) original-audio attach (durable ATTACH_ORIGINAL_AUDIO)
            audio_attach = client.post(
                f"/api/v2/projects/{project_id}/original-audio-attach",
                json={"video_item_id": video_id},
            )
            stage("original_audio_attach", _rec(audio_attach))
            assert audio_attach.status_code == 202, audio_attach.text
            audio_job_id = str(audio_attach.json().get("job_id"))
            chain["identities"]["audio_job_id"] = audio_job_id
            audio_poll = _poll(
                client,
                f"/api/jobs/{audio_job_id}",
                terminal={"completed", "failed", "cancelled"},
                timeout_seconds=240.0,
                state_key="status",
            )
            stage("audio_attach_job", audio_poll)
            audio_final = audio_poll["final"]["body"] if audio_poll["final"] else {}
            chain["flags"]["audio_attach_state"] = (
                audio_final.get("status") or audio_final.get("state")
            )

            # 8) QC check runs (readiness 'ready' is required by S12 submit).
            #    Full scope: server-side evidence composition exists only for
            #    the audio band; non-audio detectors refuse closed with
            #    QC_RUN_EVIDENCE_UNAVAILABLE - recorded as the exact finding,
            #    not papered over.  The composable audio scope then runs.
            qc_full = client.post(
                f"/api/v2/projects/{project_id}/qc-check-runs",
                json={"video_item_id": video_id, "scope": "full"},
            )
            stage("qc_full_scope_refused", _rec(qc_full))
            chain["flags"]["qc_full_scope_status"] = qc_full.status_code
            assert qc_full.status_code == 422, qc_full.text
            assert "QC_RUN_EVIDENCE_UNAVAILABLE" in qc_full.text, qc_full.text

            qc = client.post(
                f"/api/v2/projects/{project_id}/qc-check-runs",
                json={"video_item_id": video_id, "scope": "audio"},
            )
            stage("qc_check_run_submit", _rec(qc))
            chain["flags"]["qc_audio_submit_status"] = qc.status_code
            if qc.status_code == 409:
                # The audio attach flow already auto-enqueued the audio-scope
                # RUN_QC_CHECKS job (same fingerprint+scope idempotency key
                # still active); adopt the existing durable job instead of
                # duplicating it.
                qc_detail = str(qc.json().get("detail") or qc.text)
                qc_job_id = qc_detail.split("job ", 1)[1].split(" ", 1)[0]
                chain["flags"]["qc_audio_existing_job"] = qc_job_id
            else:
                assert qc.status_code == 202, qc.text
                qc_job_id = str(qc.json().get("job_id"))
            chain["identities"]["qc_job_id"] = qc_job_id
            qc_job_poll = _poll(
                client,
                f"/api/jobs/{qc_job_id}",
                terminal={"completed", "failed", "cancelled"},
                timeout_seconds=300.0,
                state_key="status",
            )
            stage("qc_run_job", qc_job_poll)
            qc_job_final = qc_job_poll["final"]["body"] if qc_job_poll["final"] else {}
            chain["flags"]["qc_job_state"] = (
                qc_job_final.get("status") or qc_job_final.get("state")
            )
            qc_poll = _poll(
                client,
                f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}",
                terminal={
                    "completed",
                    "failed",
                    "cancelled",
                    "ready",
                    "blocked",
                    "not_run",
                },
                timeout_seconds=300.0,
            )
            stage("qc_check_run_state", qc_poll)
            qc_final = qc_poll["final"]["body"] if qc_poll["final"] else {}
            readiness_read = client.get(
                f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}/readiness"
            )
            stage("qc_readiness", _rec(readiness_read))
            readiness_body = (
                readiness_read.json() if readiness_read.status_code == 200 else {}
            )
            verdict = readiness_body.get("status") or readiness_body.get("verdict") or qc_final.get(
                "run_state"
            )
            chain["flags"]["readiness_status"] = verdict

            # 9) S12 context / preflight / submit
            context = client.get(
                f"/api/v2/projects/{project_id}/export/context",
                params={"video_item_id": video_id},
            )
            stage("s12_context", _rec(context))
            assert context.status_code == 200, context.text
            context_body = context.json()
            assert not context_body.get("reasons"), context_body.get("reasons")
            checkpoint_pin = context_body["checkpoint"]
            lock_pin = context_body["lock"]
            context_revision = str(context_body["context_revision"])

            preflight = client.post(
                f"/api/v2/projects/{project_id}/export/preflight",
                json={
                    "video_item_id": video_id,
                    "profile_id": "master-4k-h264",
                    "aspect_handling": "letterbox",
                    "checkpoint": checkpoint_pin,
                    "lock": lock_pin,
                },
            )
            stage("s12_preflight", _rec(preflight))
            assert preflight.status_code == 200, preflight.text
            preflight_body = preflight.json()
            chain["flags"]["preflight_eligible"] = preflight_body.get("eligible")
            if preflight_body.get("eligible") is not True:
                chain["status"] = "BLOCKED_EXACT_S12_READINESS"
                chain["blocker"] = {
                    "code": "S12_EXPORT_NOT_READY",
                    "preflight_reasons": preflight_body.get("reasons"),
                    "readiness_status": chain["flags"].get("readiness_status"),
                    "readiness_detail": (
                        (chain["stages"].get("qc_readiness") or {}).get("body") or {}
                    ).get("check_state_detail"),
                    "full_scope_submit": (
                        "422 QC_RUN_EVIDENCE_UNAVAILABLE - compose_check_run_args has "
                        "no server-side evidence composition path for non-audio "
                        "detectors (trajectory_drift first); refusing to fabricate"
                    ),
                    "corroboration": (
                        "frontend/e2e/s12-export-seed.py seeds a completed FULL "
                        "RUN_QC_CHECKS run directly; the S12 E2E itself never reaches "
                        "readiness through public APIs"
                    ),
                }
                raise AssertionError(
                    "BLOCKED_EXACT: S12 export preflight ineligible on the public chain "
                    f"(reasons={preflight_body.get('reasons')}; readiness="
                    f"{chain['flags'].get('readiness_status')!r}; full-scope QC submit "
                    "refused 422 QC_RUN_EVIDENCE_UNAVAILABLE)"
                )

            submit = client.post(
                "/s12-exports/submit",
                json={
                    "project_id": project_id,
                    "video_item_id": video_id,
                    "profile_id": "master-4k-h264",
                    "context_revision": context_revision,
                    "idempotency_key": f"b01i-submit-{project_id}",
                },
            )
            stage("s12_submit", _rec(submit))
            assert submit.status_code == 202, submit.text
            submit_body = submit.json()
            run_id_export = str(submit_body["run_id"])
            chain["identities"]["s12_run_id"] = run_id_export
            chain["identities"]["s12_job_id"] = submit_body.get("job_id")

            run_poll = _poll(
                client,
                f"/s12-exports/{run_id_export}",
                terminal={"completed", "failed", "cancelled"},
                timeout_seconds=900.0,
            )
            stage("s12_run_poll", run_poll)
            run_final = run_poll["final"]["body"] if run_poll["final"] else {}
            chain["stages"]["s12_run_status"] = run_final.get("status")
            assert run_final.get("status") == "completed", (
                f"S12 run did not complete: {json.dumps(run_final)[:3000]}"
            )

            result = client.get(f"/s12-exports/{run_id_export}/result")
            stage("s12_result", _rec(result))
            media = client.get(f"/s12-exports/{run_id_export}/media")
            media_bytes = media.content
            chain["stages"]["s12_media_http"] = {
                "status_code": media.status_code,
                "bytes": len(media_bytes),
                "sha256": _sha256_bytes(media_bytes),
            }
            assert media.status_code == 200, media.text

            # 10) media facts (whole media + audio comparison with source)
            export_path = runtime_root / "b01i-export-media.mp4"
            export_path.write_bytes(media_bytes)
            export_probe = _ffprobe(export_path)
            export_facts = _media_facts(export_probe)
            chain["export_media"] = {
                "path": str(export_path),
                "sha256": _sha256_file(export_path),
                "facts": export_facts,
            }
            src_v = source_facts.get("video", {})
            exp_v = export_facts.get("video", {})
            duration_delta = abs(
                float(export_facts.get("duration_s", 0))
                - float(source_facts.get("duration_s", 0))
            )
            chain["flags"]["duration_delta_s"] = round(duration_delta, 3)
            chain["flags"]["fps_preserved"] = exp_v.get("fps") == src_v.get("fps")
            chain["flags"]["source_frames"] = src_v.get("frame_count")
            chain["flags"]["export_frames"] = exp_v.get("frame_count")
            chain["flags"]["audio_present_source"] = bool(source_facts.get("audio"))
            chain["flags"]["audio_present_export"] = bool(export_facts.get("audio"))
            chain["flags"]["streams_source"] = [
                s.get("codec_type") for s in (source_probe.get("streams") or [])
            ]
            chain["flags"]["streams_export"] = [
                s.get("codec_type") for s in (export_probe.get("streams") or [])
            ]
            chain["flags"]["frame_count_preserved"] = (
                chain["flags"]["source_frames"] == chain["flags"]["export_frames"]
            )
            chain["flags"]["order_note"] = (
                "single-scene deterministic fixture: order discriminator is frame "
                "count/sequence equality (120==120); this fixture carries no temporal "
                "signature to distinguish a reshuffle beyond count - recorded as fact, "
                "not claimed beyond it"
            )

            # 11) replay / reload: zero extra Run/Job rows
            before_replay = counts()
            context_reload = client.get(
                f"/api/v2/projects/{project_id}/export/context",
                params={"video_item_id": video_id},
            )
            stage("s12_context_reload", _rec(context_reload))
            replay_submit = client.post(
                "/s12-exports/submit",
                json={
                    "project_id": project_id,
                    "video_item_id": video_id,
                    "profile_id": "master-4k-h264",
                },
            )
            stage("s12_replay_submit", _rec(replay_submit))
            after_replay = counts()
            chain["counts"]["after_chain"] = after_replay
            chain["replay"] = {
                "before": before_replay,
                "after": after_replay,
                "extra_runs": after_replay["s12_export_runs"] - before_replay["s12_export_runs"],
                "extra_jobs": after_replay["jobs"] - before_replay["jobs"],
                "replay_status_code": replay_submit.status_code,
                "replay_created_flag": (
                    replay_submit.json().get("created")
                    if replay_submit.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else None
                ),
            }
            assert chain["replay"]["extra_runs"] == 0, chain["replay"]
            assert chain["replay"]["extra_jobs"] == 0, chain["replay"]

            # 12) freeze the worker, fresh restart on the same DB (matrix C27)
            service.stop_worker(timeout=10.0)
            restart_before = counts()
            service.start_worker()
            time.sleep(2.0)
            service.stop_worker(timeout=10.0)
            restart_after = counts()
            chain["stages"]["worker_restart_counts"] = {
                "before": restart_before,
                "after": restart_after,
            }
            chain["flags"]["restart_no_duplicate"] = (
                restart_after["s10_publications"] == restart_before["s10_publications"]
                and restart_after["s12_export_runs"] == restart_before["s12_export_runs"]
                and restart_after["jobs"] == restart_before["jobs"]
            )
            assert chain["flags"]["restart_no_duplicate"], chain["stages"]["worker_restart_counts"]

            # 13) cancel leg (matrix C27): second checkpoint cycle -> S10 run2 created
            #     with the worker stopped (never claimed) -> public cancel BEFORE any
            #     render; the following restart proves the cancelled job stays
            #     unprocessed.
            pin2 = client.patch(
                f"/api/v2/reskin-configs/{config_id}",
                json={
                    "revision": pinned_revision,
                    "structural_lock_manifest_id": manifest_id,
                },
            )
            stage("reskin_config_repin2", _rec(pin2))
            chain["flags"]["cycle2_pin_status"] = pin2.status_code
            if pin2.status_code == 200:
                revision2 = int(pin2.json()["revision"])
                reapprove2 = client.post(
                    "/api/v2/s09-approvals/reapprove",
                    params={"workspace_id": "default"},
                    json={
                        "reskin_config_id": config_id,
                        "expected_reskin_revision": revision2,
                        "pack_version_ids": version_ids,
                        "idempotency_key": f"b01i-reapprove2-{project_id}",
                        "note": "B01-I cancel leg; not a product approval",
                    },
                )
                stage("s09_reapproval2", _rec(reapprove2))
                assert reapprove2.status_code in (200, 201), reapprove2.text
                checkpoint2 = reapprove2.json()
                checkpoint2_id = str(checkpoint2["id"])
                checkpoint2_hash = str(checkpoint2["checkpoint_hash"])
                chain["flags"]["checkpoint2_new_identity"] = (
                    checkpoint2_id != checkpoint_id
                    or checkpoint2_hash != checkpoint_hash
                )
                if chain["flags"]["checkpoint2_new_identity"]:
                    fa2 = client.post(
                        f"/api/v2/projects/{project_id}/full-apply",
                        params={"workspace_id": "default"},
                        json={
                            "video_item_id": video_id,
                            "apply_checkpoint_id": checkpoint2_id,
                            "expected_checkpoint_hash": checkpoint2_hash,
                            "expected_checkpoint_revision": revision2,
                        },
                    )
                    stage("s10_full_apply_submit2", _rec(fa2))
                    assert fa2.status_code == 202, fa2.text
                    fa2_run = str(fa2.json().get("run_id") or fa2.json().get("id"))
                    chain["identities"]["s10_run2_id"] = fa2_run
                    cancel2 = client.post(f"/api/v2/full-apply/{fa2_run}/cancel")
                    stage("s10_cancel_run2", _rec(cancel2))
                    assert cancel2.status_code in (200, 202), cancel2.text
                    run2_view = client.get(f"/api/v2/full-apply/{fa2_run}")
                    stage("s10_cancel_run2_state", _rec(run2_view))
                    run2_state = (run2_view.json() or {}).get("status")
                    chain["flags"]["s10_run2_state"] = run2_state
                    assert run2_state in ("cancelled", "cancelling"), run2_state
                else:
                    chain["flags"]["cycle2_note"] = (
                        "equivalent reapproval returned the same checkpoint; cancel leg "
                        "not applicable on an unchanged authority"
                    )
            else:
                chain["flags"]["cycle2_note"] = (
                    f"re-pin produced no new revision (status {pin2.status_code}); "
                    "cancel leg not applicable on an unchanged authority"
                )

            # S12 cancel route terminal guard (public fail-closed control)
            s12_cancel_terminal = client.post(f"/s12-exports/{run_id_export}/cancel")
            stage("s12_cancel_terminal_guard", _rec(s12_cancel_terminal))
            chain["flags"]["s12_cancel_terminal_status"] = s12_cancel_terminal.status_code

            # fresh restart after the cancel leg: cancelled work stays unprocessed
            service.start_worker()
            time.sleep(2.0)
            service.stop_worker(timeout=10.0)
            post_cancel_counts = counts()
            chain["counts"]["after_cancel_leg"] = post_cancel_counts
            chain["flags"]["cancelled_job_not_processed"] = (
                post_cancel_counts["s10_publications"] == restart_after["s10_publications"]
                and post_cancel_counts["s12_export_runs"] == restart_after["s12_export_runs"]
            )
            chain["flags"]["expiry_control"] = (
                "NOT_RUN: no public expiry endpoint for this chain; lease expiry/handoff "
                "is covered by the VAL lane (A02/R06) - not fabricated here"
            )
            assert chain["flags"]["cancelled_job_not_processed"], chain["counts"]

            chain["status"] = "PASS"
            if source_facts.get("audio") and not export_facts.get("audio"):
                chain["status"] = "PASS_WITH_FINDINGS"
                chain["flags"]["audio_policy_gap"] = (
                    "source carries audio but the exported master has no audio stream"
                )
    except Exception as exc:  # preserve every reached stage, then re-raise
        failure = exc
        if not str(chain.get("status", "")).startswith("BLOCKED_"):
            chain["status"] = f"FAILED_{type(exc).__name__}"
        chain["failure"] = str(exc)[:4000]
        with contextlib.suppress(Exception):
            chain["counts"]["at_failure"] = counts()
    finally:
        with contextlib.suppress(Exception):  # best effort cleanup, recorded by absence
            service.stop_worker(timeout=5.0)
        reset_analyze_orchestrator()
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        (
            deps._config,
            deps._job_service,
            deps._project_service,
            deps._video_service,
            deps._lifecycle_db,
            deps._project_wf,
        ) = saved
        engine.dispose()

    def write_evidence() -> dict[str, Any]:
        s12_review_out.mkdir(parents=True, exist_ok=True)
        chain_path = s12_review_out / "b01i-chain.json"
        chain_path.write_text(json.dumps(chain, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        stages_path = s12_review_out / "b01i-stages.jsonl"
        with stages_path.open("w", encoding="utf-8") as handle:
            for name in stage_order:
                handle.write(json.dumps({"stage": name, "payload": chain["stages"][name]}) + "\n")
        downstream = [
            "s10_full_apply_run",
            "s10_sidecar_evidence",
            "counts_after_s10",
            "original_audio_attach",
            "audio_attach_job",
            "qc_full_scope_refused",
            "qc_run_job",
            "qc_check_run_submit",
            "qc_check_run_state",
            "qc_readiness",
            "s12_context",
            "s12_preflight",
            "s12_submit",
            "s12_run_poll",
            "s12_result",
            "s12_media_http",
            "s12_context_reload",
            "s12_replay_submit",
            "worker_restart_counts",
            "reskin_config_repin2",
            "s09_reapproval2",
            "s10_full_apply_submit2",
            "s10_cancel_run2",
            "s10_cancel_run2_state",
            "s12_cancel_terminal_guard",
        ]
        blocked_stage = None
        for name in stage_order:
            payload = chain["stages"][name]
            code = payload.get("status_code") if isinstance(payload, dict) else None
            if isinstance(code, int) and code >= 400:
                blocked_stage = {
                    "stage": name,
                    "status_code": code,
                    "response": payload,
                }
                break
        stage_status = {
            "reached": list(stage_order),
            "blocked": blocked_stage,
            "not_reached": [name for name in downstream if name not in chain["stages"]],
        }
        summary = {
            "run_id": run_id,
            "status": chain["status"],
            "candidate_root": str(candidate_root),
            "candidate_sha": chain.get("candidate_sha_actual"),
            "stage_order": stage_order,
            "stage_status": stage_status,
            "stages": {
                "s12_run_status": chain["stages"].get("s12_run_status"),
                "producer_201": (chain["stages"].get("producer_structural_lock") or {}).get(
                    "status_code"
                ),
                "reapproval_status": (chain["stages"].get("s09_reapproval") or {}).get(
                    "status_code"
                ),
                "full_apply_status": (
                    chain["stages"]["s10_full_apply_run"]["final"]["body"].get("status")
                    if chain["stages"].get("s10_full_apply_run", {}).get("final")
                    else None
                ),
            },
            "identities": chain["identities"],
            "flags": chain["flags"],
            "replay": chain["replay"],
            "counts": chain["counts"],
            "source_media": chain.get("source_media"),
            "export_media": chain.get("export_media"),
            "failure": chain.get("failure"),
            "evidence_sha256": {},
        }
        summary_path = s12_review_out / "b01i-summary.json"
        summary["evidence_sha256"]["b01i-chain.json"] = _sha256_file(chain_path)
        summary["evidence_sha256"]["b01i-stages.jsonl"] = _sha256_file(stages_path)
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return summary

    summary = write_evidence()
    if failure is not None:
        raise failure
    assert summary["status"] in {"PASS", "PASS_WITH_FINDINGS"}, summary["status"]
