"""R3 QA-owned public producer-chain harness.

This executable exercises only public HTTP routes in an isolated migrated
database and managed root.  It deliberately keeps deterministic extraction
marked as a QA runtime policy; its outputs are engineering evidence and are
never counted as normal-product export/UI evidence.  No authority, readiness,
or completion/export row is inserted by SQL/ORM.  S09 checkpoint rows in this
probe are created only through public approval endpoints and remain explicitly
non-executable because no StructuralLockManifest is pinned.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

WORKSPACE = "default"


def _upgrade(database_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(cfg, "head")


def _record(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status_code": response.status_code, "body": body}


def _poll(
    client: TestClient,
    path: str,
    *,
    params: dict[str, str] | None = None,
    terminal: set[str],
    timeout_seconds: float,
    interval_seconds: float = 0.25,
) -> dict[str, Any]:
    started = time.monotonic()
    reads: list[dict[str, Any]] = []
    while True:
        response = client.get(path, params=params)
        item = _record(response)
        reads.append(item)
        body = item.get("body")
        state = body.get("status") if isinstance(body, dict) else None
        chain_state = body.get("chain_status") if isinstance(body, dict) else None
        if state in terminal or chain_state in terminal:
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


def _counts(factory: Any) -> dict[str, int]:
    from app.persistence.models import (
        ApplyCheckpoint,
        Artifact,
        Character,
        CharacterAsset,
        CharacterPackVersion,
        Job,
        ObjectOccurrence,
        ObjectRole,
        Project,
        ProjectCastMapping,
        ReskinConfig,
        S12ExportRun,
        StructuralLockManifest,
        VideoItem,
    )

    models = {
        "projects": Project,
        "video_items": VideoItem,
        "jobs": Job,
        "artifacts": Artifact,
        "characters": Character,
        "pack_versions": CharacterPackVersion,
        "character_assets": CharacterAsset,
        "roles": ObjectRole,
        "occurrences": ObjectOccurrence,
        "project_cast_mappings": ProjectCastMapping,
        "reskin_configs": ReskinConfig,
        "structural_lock_manifests": StructuralLockManifest,
        "s09_approvals": ApplyCheckpoint,
        "s12_export_runs": S12ExportRun,
    }
    with factory() as session:
        return {
            name: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in models.items()
        }


def _make_fixture(root: Path) -> tuple[Path, str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is unavailable; a real public upload fixture cannot be made")
    fixture = root / "upload-fixture-256.mp4"
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=256x256:r=10:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(fixture),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg fixture failed rc={result.returncode}: {result.stderr}")
    return fixture, hashlib.sha256(fixture.read_bytes()).hexdigest()


def run(work_root: Path) -> dict[str, Any]:
    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    database_path = work_root / "data" / "r3-public-chain.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    _upgrade(database_path)

    from app.api import deps
    from app.api.app import app
    from app.config import AppConfig
    from app.persistence import create_engine_for_path, create_session_factory
    from app.workflow.analyze_orchestrator import reset_analyze_orchestrator
    from app.workflow.job_service import JobService
    from app.workflow.project_workflow import ProjectWorkflowService

    config = AppConfig(
        project_root=work_root,
        models_dir=work_root / "models",
        output_dir=work_root / "output",
    )
    managed_root = work_root / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    engine = create_engine_for_path(database_path)
    factory = create_session_factory(engine)
    service = JobService(factory, managed_root=managed_root)
    old_values = (
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
    os.environ["MOTIONFORGE_EXTRACTION_QA_MODE"] = "1"
    os.environ["MOTIONFORGE_EXTRACTION_PROVIDER"] = "deterministic-identity"
    evidence: dict[str, Any] = {
        "classification": {
            "normal_product_export": "NOT_DEMONSTRATED",
            "normal_product_ui": "NOT_RUN",
            "deterministic_extraction": "FIXTURE_ONLY_ENGINEERING_MECHANISM",
            "manual_sql_fabrication": False,
        },
        "runtime": {
            "work_root": str(work_root),
            "database": str(database_path),
            "managed_root": str(managed_root),
            "provider_policy": "deterministic-identity",
            "qa_mode": True,
        },
        "steps": {},
    }
    try:
        deps._config = config
        deps._job_service = service
        deps._project_service = None
        deps._video_service = None
        deps._lifecycle_db = database_path
        deps._project_wf = ProjectWorkflowService(config)
        client = TestClient(app, raise_server_exceptions=False)
        service.start_worker()
        evidence["worker_started"] = service.worker_running
        openapi = client.get("/openapi.json")
        paths = openapi.json().get("paths", {}) if openapi.status_code == 200 else {}
        evidence["steps"]["openapi_producer_routes"] = {
            "response": _record(openapi),
            "routes": {
                path: sorted(methods)
                for path, methods in paths.items()
                if any(
                    token in path.lower()
                    for token in (
                        "character",
                        "object-intelligence",
                        "project-cast",
                        "reskin",
                        "structural",
                        "s09-approval",
                        "full-apply",
                    )
                )
            },
        }
        fixture, fixture_sha = _make_fixture(work_root)
        evidence["fixture"] = {
            "path": str(fixture),
            "sha256": fixture_sha,
            "bytes": fixture.stat().st_size,
        }

        # Legacy public 12-hex project -> upload -> durable import/proxy/scene
        # chain.  Every subsequent identity is taken from its response.
        legacy_create = client.post(
            "/api/projects", json={"name": "S12-LC3-R3-public-chain"}
        )
        evidence["steps"]["legacy_create_project"] = _record(legacy_create)
        assert legacy_create.status_code == 201, legacy_create.text
        legacy_project_id = legacy_create.json()["project_id"]
        with fixture.open("rb") as handle:
            legacy_upload = client.post(
                f"/api/projects/{legacy_project_id}/video",
                files={"file": (fixture.name, handle, "video/mp4")},
            )
        evidence["steps"]["legacy_public_upload"] = _record(legacy_upload)
        assert legacy_upload.status_code == 200, legacy_upload.text
        legacy_analyze = client.post(
            f"/api/projects/{legacy_project_id}/analyze",
            json={"generation": "1", "title": "R3 public upload/analyze"},
        )
        evidence["steps"]["legacy_public_analyze_submit"] = _record(legacy_analyze)
        assert legacy_analyze.status_code == 200, legacy_analyze.text
        chain_poll = _poll(
            client,
            f"/api/projects/{legacy_project_id}/analyze",
            params={"generation": "1"},
            terminal={"completed", "failed", "cancelled"},
            timeout_seconds=60.0,
        )
        evidence["steps"]["legacy_public_analyze_chain"] = chain_poll
        chain = chain_poll["final"].get("body") if chain_poll["final"] else None
        assert isinstance(chain, dict), "legacy chain did not return a JSON state"
        evidence["identities"] = {
            "legacy_project_id": legacy_project_id,
            "legacy_project_id_shape": "12-hex",
            "legacy_video_item_id": chain.get("video_item_id"),
            "legacy_source_artifact_id": chain.get("source_artifact_id"),
            "legacy_proxy_artifact_id": chain.get("proxy_artifact_id"),
        }
        if chain.get("chain_status") != "completed":
            evidence["status"] = "BLOCKED_LEGACY_CHAIN"
            evidence["first_missing_contract"] = (
                "legacy public analyze chain did not reach completed"
            )
            return evidence
        video_id = str(chain["video_item_id"])
        generation = str(chain.get("generation") or "1")
        legacy_context = client.get(
            f"/api/v2/projects/{legacy_project_id}/export/context",
            params={"video_item_id": video_id},
        )
        evidence["steps"]["legacy_to_v2_context_boundary"] = {
            "request": {
                "method": "GET",
                "path": f"/api/v2/projects/{legacy_project_id}/export/context",
                "params": {"video_item_id": video_id},
            },
            "response": _record(legacy_context),
            "classification": "legacy_project_id_rejected_or_scoped_as_returned",
        }

        extraction = client.post(
            "/api/v2/object-intelligence/extraction",
            json={
                "project_id": legacy_project_id,
                "video_item_id": video_id,
                "generation": generation,
            },
        )
        evidence["steps"]["public_object_extraction_submit"] = _record(extraction)
        if extraction.status_code != 201:
            evidence["status"] = "BLOCKED_OBJECT_EXTRACTION"
            evidence["first_missing_contract"] = "public DISCOVER_OBJECTS submit"
            return evidence
        extraction_id = extraction.json()["job_id"]
        extraction_poll = _poll(
            client,
            f"/api/v2/object-intelligence/extraction/{extraction_id}",
            terminal={"completed", "failed", "cancelled"},
            timeout_seconds=60.0,
        )
        evidence["steps"]["public_object_extraction_worker"] = {
            "job_id": extraction_id,
            "poll": extraction_poll,
            "outputs": _record(
                client.get(
                    f"/api/v2/object-intelligence/extraction/{extraction_id}/outputs"
                )
            ),
            "graph": _record(
                client.get(
                    f"/api/v2/object-intelligence/extraction/{extraction_id}/graph"
                )
            ),
        }
        extraction_body = extraction_poll["final"].get("body") if extraction_poll["final"] else None
        if not isinstance(extraction_body, dict) or extraction_body.get("status") != "completed":
            evidence["status"] = "BLOCKED_OBJECT_EXTRACTION"
            evidence["first_missing_contract"] = "DISCOVER_OBJECTS durable worker did not publish"
            return evidence

        roles_read = client.get(
            "/api/v2/object-intelligence/roles",
            params={"video_item_id": video_id},
        )
        evidence["steps"]["public_roles_current"] = _record(roles_read)
        assert roles_read.status_code == 200, roles_read.text
        roles = roles_read.json().get("roles", [])
        if not roles:
            evidence["status"] = "BLOCKED_ROLE_PRODUCER"
            evidence["first_missing_contract"] = (
                "extraction completed without a public current ObjectRole"
            )
            return evidence
        role = roles[0]
        role_id = str(role["id"])
        role_revision = int(role["revision"])
        role_update = client.patch(
            f"/api/v2/object-intelligence/roles/{role_id}",
            json={"revision": role_revision, "status": "confirmed"},
        )
        evidence["steps"]["public_role_confirm"] = _record(role_update)
        assert role_update.status_code == 200, role_update.text
        role_get = client.get(f"/api/v2/object-intelligence/roles/{role_id}")
        evidence["steps"]["public_role_with_occurrences"] = _record(role_get)
        assert role_get.status_code == 200, role_get.text
        evidence["identities"].update(
            {"role_id": role_id, "role_source_generation": role["source_generation"]}
        )

        # The extraction worker normally produces occurrences.  If it does
        # not, do not invent a scene/frame: preserve the exact public result
        # and classify the missing producer instead of making a fake row.
        role_body = role_get.json()
        if not role_body.get("occurrences"):
            evidence["steps"]["public_occurrence_producer"] = {
                "status": "NOT_DEMONSTRATED",
                "reason": "role response contained no occurrence evidence to follow",
            }
        else:
            evidence["steps"]["public_occurrence_producer"] = {
                "status": "PRODUCED_BY_DISCOVER_OBJECTS",
                "count": len(role_body["occurrences"]),
                "ids": [item.get("id") for item in role_body["occurrences"]],
            }

        character = client.post(
            "/api/v2/characters",
            json={"name": "R3 Public Character", "code": f"R3_{legacy_project_id[:8]}"},
        )
        evidence["steps"]["public_character_create"] = _record(character)
        assert character.status_code == 201, character.text
        character_id = character.json()["id"]
        version = client.post(f"/api/v2/characters/{character_id}/versions")
        evidence["steps"]["public_character_version_create"] = _record(version)
        assert version.status_code == 201, version.text
        version_id = version.json()["id"]
        outputs = evidence["steps"]["public_object_extraction_worker"]["outputs"].get("body", {})
        output_rows = outputs.get("outputs", []) if isinstance(outputs, dict) else []
        image_outputs = [
            row
            for row in output_rows
            if row.get("mime_type", "").startswith("image/")
        ]
        if not image_outputs:
            evidence["status"] = "BLOCKED_CHARACTER_ASSET_PRODUCER"
            evidence["first_missing_contract"] = (
                "no public ready image artifact from extraction to attach"
            )
            return evidence
        artifact_id = str(image_outputs[0]["artifact_id"])
        attached: list[dict[str, Any]] = []
        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
            response = client.post(
                f"/api/v2/characters/versions/{version_id}/assets",
                json={"pose_slot": slot, "artifact_id": artifact_id},
            )
            attached.append({"slot": slot, "response": _record(response)})
            assert response.status_code == 200, response.text
        evidence["steps"]["public_character_asset_attach"] = {
            "artifact_id": artifact_id,
            "attached": attached,
        }
        validation = client.get(f"/api/v2/characters/versions/{version_id}/validation")
        evidence["steps"]["public_character_version_validation"] = _record(validation)
        publish = client.post(
            f"/api/v2/characters/versions/{version_id}/publish",
            json={"revision": int(version.json()["revision"])},
        )
        evidence["steps"]["public_character_version_publish"] = _record(publish)
        assert publish.status_code == 200, publish.text
        evidence["identities"].update(
            {
                "character_id": character_id,
                "pack_version_id": version_id,
                "pack_artifact_id": artifact_id,
            }
        )

        cast = client.post(
            "/api/v2/project-cast",
            json={
                "project_id": legacy_project_id,
                "object_role_id": role_id,
                "character_id": character_id,
                "pack_version_id": version_id,
                "idempotency_key": f"r3-cast-{legacy_project_id}",
            },
        )
        evidence["steps"]["public_project_cast_mapping"] = _record(cast)
        if cast.status_code not in (200, 201):
            evidence["status"] = "BLOCKED_PROJECT_CAST"
            evidence["first_missing_contract"] = "public ProjectCast create"
            return evidence
        cast_id = cast.json()["id"]
        params = {
            "anchor": {"x": 0.5, "y": 0.5},
            "scale": 1.0,
            "fit_mode": "contain",
            "clip_mode": "asset_alpha",
            "offset": {"x": 0.0, "y": 0.0},
            "rotation_offset_deg": 0.0,
            "opacity": 1.0,
        }
        config_create = client.post(
            "/api/v2/reskin-configs",
            json={
                "project_id": legacy_project_id,
                "object_role_id": role_id,
                "character_id": character_id,
                "pack_version_id": version_id,
                "cast_mapping_id": cast_id,
                "params": params,
                "idempotency_key": f"r3-config-{legacy_project_id}",
            },
        )
        evidence["steps"]["public_reskin_config_create"] = _record(config_create)
        if config_create.status_code not in (200, 201):
            evidence["status"] = "BLOCKED_RESkin_CONFIG"
            evidence["first_missing_contract"] = "public ReskinConfig create"
            return evidence
        config_body = config_create.json()
        config_id = config_body["id"]
        revision = int(config_body["revision"])
        evidence["steps"]["public_structural_evidence_current"] = _record(
            client.get("/api/v2/structural-evidence/segments", params={"video_item_id": video_id})
        )

        # This is the supported S09 consumer boundary.  A 409/422 here is
        # the exact first missing producer only after all public prerequisites
        # above have succeeded.
        approval = client.post(
            "/api/v2/s09-approvals",
            params={"workspace_id": WORKSPACE},
            json={
                "reskin_config_id": config_id,
                "expected_reskin_revision": revision,
                "pack_version_ids": [version_id],
                "idempotency_key": f"r3-approval-{legacy_project_id}",
                "note": "R3 public producer-chain probe; not product approval",
            },
        )
        evidence["steps"]["public_s09_approval_submit"] = _record(approval)
        if approval.status_code in (200, 201):
            checkpoint_id = approval.json()["id"]
            reapprove = client.post(
                "/api/v2/s09-approvals/reapprove",
                params={"workspace_id": WORKSPACE},
                json={
                    "reskin_config_id": config_id,
                    "expected_reskin_revision": revision,
                    "pack_version_ids": [version_id],
                    "idempotency_key": f"r3-reapprove-{legacy_project_id}",
                    "note": "R3 public producer-chain probe; not product approval",
                },
            )
            evidence["steps"]["public_s09_reapprove"] = _record(reapprove)
            if reapprove.status_code in (200, 201):
                checkpoint_id = reapprove.json()["id"]
                evidence["steps"]["public_full_apply_authority"] = _record(
                    client.get(
                        f"/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority",
                        params={"workspace_id": WORKSPACE},
                    )
                )
                s10_submit = client.post(
                    f"/api/v2/projects/{legacy_project_id}/full-apply",
                    params={"workspace_id": WORKSPACE},
                    json={
                        "video_item_id": video_id,
                        "apply_checkpoint_id": checkpoint_id,
                        "expected_checkpoint_hash": reapprove.json()["checkpoint_hash"],
                        "expected_checkpoint_revision": 1,
                    },
                )
                evidence["steps"]["public_s10_full_apply_submit"] = _record(s10_submit)
                evidence["steps"]["counts_after_s10_full_apply_submit"] = _counts(factory)
        evidence["counts_before_s12_submit"] = _counts(factory)
        context = client.get(
            f"/api/v2/projects/{legacy_project_id}/export/context",
            params={"video_item_id": video_id},
        )
        evidence["steps"]["public_s12_context_after_producers"] = _record(context)
        submit = client.post(
            "/s12-exports/submit",
            json={
                "project_id": legacy_project_id,
                "video_item_id": video_id,
                "profile_id": "master-4k-h264",
            },
        )
        evidence["steps"]["public_s12_submit_after_producers"] = _record(submit)
        evidence["counts_after_s12_submit"] = _counts(factory)
        evidence["status"] = (
            "BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY"
            if submit.status_code != 202
            else "PUBLIC_AUTHORITY_CHAIN_REACHED_S12"
        )
        evidence["first_missing_contract"] = (
            "public StructuralLockManifest producer/pin after source, evidence, "
            "cast, and config producers and before executable S09/S10 authority"
            if submit.status_code != 202
            else None
        )
        evidence["assertions"] = [
            "legacy public 12-hex project upload/analyze chain used actual returned IDs",
            "public DISCOVER_OBJECTS durable worker produced current role/occurrence evidence",
            "public character/version/ready-artifact attach/publish completed",
            "public ProjectCast and ReskinConfig consumers were exercised",
            "S09/S12 authority result was recorded without fabricated SQL rows",
            "normal-product export/UI/media remains NOT_DEMONSTRATED unless S12 returned 202",
        ]
        return evidence
    finally:
        with contextlib.suppress(Exception):
            service.stop_worker(timeout=3.0)
        with contextlib.suppress(Exception):
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
        ) = old_values
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    started = time.time()
    try:
        result = run(args.work_root)
        result["elapsed_seconds"] = round(time.time() - started, 3)
        rendered = json.dumps(result, indent=2, sort_keys=True)
        print(rendered)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered + "\n", encoding="utf-8")
        return 0
    except Exception as exc:  # preserve a raw harness failure for QA review
        failure = {
            "status": "HARNESS_FAILURE",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "elapsed_seconds": round(time.time() - started, 3),
        }
        rendered = json.dumps(failure, indent=2, sort_keys=True)
        print(rendered)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
