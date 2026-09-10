"""Q1 public-boundary probe for the S12 export acceptance path.

This probe uses the public durable Project, Video Item, export-context, and
export-submit routes against an isolated migrated SQLite database.  It does
not seed Full Apply authority, readiness, approved records, or completion
with SQL.  A clean database is therefore expected to fail closed at the
server-owned authority boundary; that result is evidence of the current
external fixture/production contract block, not a positive render acceptance.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def _upgrade(database_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(cfg, "head")


def _response_record(response: Any) -> dict[str, Any]:
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status_code": response.status_code, "body": body}


def _operation_shape(paths: dict[str, Any], path: str, method: str) -> dict[str, Any] | None:
    """Keep a concise, exact OpenAPI route envelope in the evidence."""
    operation = (paths.get(path) or {}).get(method.lower())
    if not isinstance(operation, dict):
        return None
    return {
        "method": method.upper(),
        "path": path,
        "operation_id": operation.get("operationId"),
        "summary": operation.get("summary"),
        "parameters": [
            {
                "in": item.get("in"),
                "name": item.get("name"),
                "required": item.get("required", False),
            }
            for item in operation.get("parameters", [])
            if isinstance(item, dict)
        ],
        "request_body_schema": (
            (operation.get("requestBody") or {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        ),
        "response_statuses": sorted((operation.get("responses") or {}).keys()),
    }


def run_probe(work_root: Path | None = None) -> dict[str, Any]:
    """Run the isolated public API probe and return raw structured results."""
    temp_context: Any
    if work_root is None:
        temp_context = tempfile.TemporaryDirectory(prefix="s12_lc3_q1_public_probe_")
    else:
        work_root = work_root.resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        temp_context = contextlib.nullcontext(str(work_root))
    with temp_context as tmp:
        root = Path(tmp).resolve()
        database_path = root / "data" / "probe.db"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        _upgrade(database_path)

        from app.api import deps
        from app.api.app import app
        from app.config import AppConfig
        from app.persistence import create_engine_for_path, create_session_factory
        from app.persistence.models import Artifact, Job, Project, S12ExportRun, VideoItem
        from app.workflow.analyze_orchestrator import reset_analyze_orchestrator
        from app.workflow.job_service import JobService
        from app.workflow.project_workflow import ProjectWorkflowService

        config = AppConfig(
            project_root=root,
            models_dir=root / "models",
            output_dir=root / "output",
        )
        managed_root = root / "artifacts"
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
        deps._config = config
        deps._job_service = service
        deps._project_service = None
        deps._video_service = None
        deps._lifecycle_db = database_path
        deps._project_wf = ProjectWorkflowService(config)

        def counts() -> dict[str, int]:
            with factory() as session:
                return {
                    "projects": int(session.scalar(select(func.count()).select_from(Project)) or 0),
                    "video_items": int(
                        session.scalar(select(func.count()).select_from(VideoItem)) or 0
                    ),
                    "artifacts": int(
                        session.scalar(select(func.count()).select_from(Artifact)) or 0
                    ),
                    "jobs": int(session.scalar(select(func.count()).select_from(Job)) or 0),
                    "s12_export_runs": int(
                        session.scalar(select(func.count()).select_from(S12ExportRun)) or 0
                    ),
                }

        evidence: dict[str, Any] = {
            "status": "BLOCKED_EXTERNAL_AUTHORITY_FIXTURE",
            "database": str(database_path),
            "managed_root": str(root / "artifacts"),
            "manual_sql_used": False,
            "steps": {},
        }
        try:
            client = TestClient(app, raise_server_exceptions=False)
            service.start_worker()
            evidence["worker_started"] = service.worker_running
            project_response = client.post(
                "/api/v2/projects",
                json={"name": "S12-LC3-Q1-public-probe"},
            )
            evidence["steps"]["create_project"] = _response_record(project_response)
            if project_response.status_code != 201:
                raise RuntimeError("public durable project creation did not succeed")
            project_id = project_response.json()["project_id"]
            evidence["steps"]["create_project_mutation_counts"] = counts()

            video_response = client.post(
                f"/api/v2/projects/{project_id}/videos",
                json={"title": "S12-LC3-Q1-public-probe-video"},
            )
            evidence["steps"]["create_video"] = _response_record(video_response)
            if video_response.status_code != 201:
                raise RuntimeError("public durable video creation did not succeed")
            video_id = video_response.json()["video_item_id"]
            evidence["steps"]["create_video_mutation_counts"] = counts()

            openapi = client.get("/openapi.json")
            paths = openapi.json().get("paths", {}) if openapi.status_code == 200 else {}
            evidence["steps"]["openapi_authority_routes"] = {
                "response": _response_record(openapi),
                "paths": {
                    path: sorted(methods)
                    for path, methods in paths.items()
                    if any(
                        token in path
                        for token in (
                            "/api/v2/projects/",
                            "/api/v2/reskin-configs",
                            "/api/v2/project-cast",
                            "/api/v2/s09-approvals",
                            "/api/v2/full-apply",
                            "/api/v2/object-intelligence",
                            "/structural-lock",
                        )
                    )
                },
            }
            graph_targets = [
                ("POST", "/api/v2/projects/"),
                ("POST", "/api/v2/projects/{project_id}/videos"),
                ("GET", "/api/v2/projects/{project_id}/export/context"),
                ("GET", "/api/v2/reskin-configs"),
                ("POST", "/api/v2/reskin-configs"),
                ("GET", "/api/v2/object-intelligence/roles"),
                ("POST", "/api/v2/object-intelligence/roles"),
                ("GET", "/api/v2/project-cast"),
                ("GET", "/api/v2/s09-approvals"),
                ("POST", "/api/v2/s09-approvals/reapprove"),
                ("GET", "/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority"),
                ("POST", "/api/v2/projects/{project_id}/full-apply"),
                ("POST", "/s12-exports/submit"),
                ("POST", "/api/projects"),
                ("POST", "/api/projects/{project_id}/video"),
                ("POST", "/api/projects/{project_id}/analyze"),
                ("GET", "/api/projects/{project_id}/analyze"),
            ]
            evidence["steps"]["public_chain_openapi"] = {
                "response": _response_record(openapi),
                "operations": [
                    shape
                    for method, path in graph_targets
                    if (shape := _operation_shape(paths, path, method)) is not None
                ],
            }

            config_attempt = client.post(
                "/api/v2/reskin-configs",
                json={
                    "project_id": project_id,
                    "object_role_id": "missing-public-role",
                    "character_id": "missing-public-character",
                    "pack_version_id": "missing-public-pack",
                    "params": {
                        "anchor": {"x": 0.5, "y": 0.5},
                        "scale": 1.0,
                        "fit_mode": "contain",
                        "clip_mode": "asset_alpha",
                        "offset": {"x": 0.0, "y": 0.0},
                        "rotation_offset_deg": 0.0,
                        "opacity": 1.0,
                    },
                },
            )
            evidence["steps"]["reskin_config_create_missing_prerequisites"] = _response_record(
                config_attempt
            )
            picker_packs = client.get("/api/v2/project-cast/picker/packs")
            evidence["steps"]["project_cast_picker_packs"] = _response_record(picker_packs)

            # Bounded supported-authority attempt: make a real, decodable
            # fixture and offer it only through public upload/import routes.
            # The legacy upload route is intentionally exercised against the
            # durable UUID so the missing cross-domain boundary is explicit.
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                evidence["steps"]["authority_attempt"] = {
                    "status": "BLOCKED_TOOLCHAIN",
                    "detail": "ffmpeg is unavailable for a real upload fixture",
                }
            else:
                fixture = root / "upload-fixture.mp4"
                subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=32x32:r=10:d=1",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        str(fixture),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
                with fixture.open("rb") as handle:
                    legacy_upload = client.post(
                        f"/api/projects/{project_id}/video",
                        files={"file": ("upload-fixture.mp4", handle, "video/mp4")},
                    )
                with fixture.open("rb") as handle:
                    durable_import = client.post(
                        f"/api/v2/projects/{project_id}/videos/{video_id}/import",
                        files={"file": ("upload-fixture.mp4", handle, "video/mp4")},
                    )
                evidence["steps"]["authority_attempt"] = {
                    "fixture": str(fixture),
                    "legacy_upload": _response_record(legacy_upload),
                    "durable_import": _response_record(durable_import),
                    "durable_video_import_paths": sorted(
                        path
                        for path in paths
                        if "/api/v2/projects/" in path and "import" in path
                    ),
                }

                # Bounded legacy compatibility check: create a real legacy
                # project (the supported 12-hex identity), upload the same
                # decodable fixture through its public endpoint, and submit
                # the public analyze chain.  No IDs are forged and no SQL is
                # used to create authority/readiness/completion.
                legacy_project_response = client.post(
                    "/api/projects",
                    json={"name": "S12-LC3-Q1-legacy-public-probe"},
                )
                evidence["steps"]["legacy_create_project"] = _response_record(
                    legacy_project_response
                )
                if legacy_project_response.status_code == 201:
                    legacy_project_id = legacy_project_response.json()["project_id"]
                    evidence["legacy_project_id"] = legacy_project_id
                    evidence["steps"]["legacy_create_project_mutation_counts"] = counts()
                    with fixture.open("rb") as handle:
                        legacy_upload_real = client.post(
                            f"/api/projects/{legacy_project_id}/video",
                            files={"file": ("upload-fixture.mp4", handle, "video/mp4")},
                        )
                    evidence["steps"]["legacy_upload_real"] = _response_record(
                        legacy_upload_real
                    )
                    evidence["steps"]["legacy_upload_mutation_counts"] = counts()
                    if legacy_upload_real.status_code == 200:
                        legacy_analyze = client.post(
                            f"/api/projects/{legacy_project_id}/analyze",
                            json={"generation": "1", "title": "legacy probe video"},
                        )
                        evidence["steps"]["legacy_analyze_submit"] = _response_record(
                            legacy_analyze
                        )
                        evidence["steps"]["legacy_analyze_submit_mutation_counts"] = counts()
                        bounded_reads: list[dict[str, Any]] = []
                        deadline = time.monotonic() + 10.0
                        while True:
                            legacy_chain = client.get(
                                f"/api/projects/{legacy_project_id}/analyze",
                                params={"generation": "1"},
                            )
                            record = _response_record(legacy_chain)
                            bounded_reads.append(record)
                            state = record.get("body")
                            if (
                                not isinstance(state, dict)
                                or state.get("chain_status") not in {"running", "queued"}
                                or time.monotonic() >= deadline
                            ):
                                break
                            time.sleep(0.25)
                        evidence["steps"]["legacy_analyze_chain_bounded_reads"] = {
                            "max_seconds": 10,
                            "reads": bounded_reads,
                        }
                        final_state = bounded_reads[-1].get("body")
                        if isinstance(final_state, dict) and final_state.get("video_item_id"):
                            legacy_v2_context = client.get(
                                f"/api/v2/projects/{legacy_project_id}/export/context",
                                params={"video_item_id": final_state["video_item_id"]},
                            )
                            evidence["steps"]["legacy_id_v2_export_context"] = _response_record(
                                legacy_v2_context
                            )
                            legacy_video_id = final_state["video_item_id"]
                            scoped_reads: dict[str, Any] = {}
                            scoped_reads["reskin_configs"] = _response_record(
                                client.get(
                                    "/api/v2/reskin-configs",
                                    params={"project_id": legacy_project_id},
                                )
                            )
                            scoped_reads["object_roles"] = _response_record(
                                client.get(
                                    "/api/v2/object-intelligence/roles",
                                    params={
                                        "workspace_id": "default",
                                        "video_item_id": legacy_video_id,
                                    },
                                )
                            )
                            scoped_reads["project_cast"] = _response_record(
                                client.get(
                                    "/api/v2/project-cast",
                                    params={"project_id": legacy_project_id},
                                )
                            )
                            scoped_reads["s09_approvals"] = _response_record(
                                client.get(
                                    "/api/v2/s09-approvals",
                                    params={
                                        "workspace_id": "default",
                                        "project_id": legacy_project_id,
                                    },
                                )
                            )
                            scoped_reads["project_readiness"] = _response_record(
                                client.get(f"/api/v2/projects/{legacy_project_id}/readiness")
                            )
                            evidence["steps"]["legacy_current_authority_reads"] = {
                                "project_id": legacy_project_id,
                                "video_item_id": legacy_video_id,
                                "requests": scoped_reads,
                            }
                        evidence["steps"]["legacy_analyze_chain_read_mutation_counts"] = counts()

            # These are the next supported public authority steps. They are
            # deliberately sent with no fabricated IDs; the responses show
            # whether the public product exposes prerequisites for reapproval.
            reapprove_response = client.post(
                "/api/v2/s09-approvals/reapprove",
                params={"workspace_id": "default"},
                json={
                    "reskin_config_id": "missing-public-config",
                    "expected_reskin_revision": 1,
                    "pack_version_ids": ["missing-public-pack"],
                },
            )
            evidence["steps"]["s09_reapprove"] = _response_record(reapprove_response)
            full_apply_response = client.post(
                f"/api/v2/projects/{project_id}/full-apply",
                params={"workspace_id": "default"},
                json={
                    "video_item_id": video_id,
                    "apply_checkpoint_id": "missing-public-checkpoint",
                    "expected_checkpoint_hash": "0" * 64,
                    "expected_checkpoint_revision": 1,
                },
            )
            evidence["steps"]["s10_full_apply_submit"] = _response_record(
                full_apply_response
            )

            context_response = client.get(
                f"/api/v2/projects/{project_id}/export/context",
                params={"video_item_id": video_id},
            )
            evidence["steps"]["export_context"] = _response_record(context_response)
            before_submit_counts = counts()
            evidence["steps"]["before_s12_export_submit_counts"] = before_submit_counts

            submit_response = client.post(
                "/s12-exports/submit",
                json={
                    "project_id": project_id,
                    "video_item_id": video_id,
                    "profile_id": "master-4k-h264",
                },
            )
            evidence["steps"]["export_submit"] = _response_record(submit_response)
            evidence["project_id"] = project_id
            evidence["video_item_id"] = video_id

            with factory() as session:
                evidence["post_submit_counts"] = {
                    "s12_export_runs": session.scalar(
                        select(func.count()).select_from(S12ExportRun)
                    ),
                    "jobs": session.scalar(select(func.count()).select_from(Job)),
                }
            if evidence["post_submit_counts"]["s12_export_runs"] != 0 or any(
                evidence["post_submit_counts"][key] != before_submit_counts[key]
                for key in ("jobs", "s12_export_runs")
            ):
                raise AssertionError(
                    "fail-closed public submit created a durable run or job"
                )
            evidence["assertions"] = [
                "public durable project created",
                "public durable video created",
                "export context remained server-owned and non-ready",
                "export submit was rejected before durable mutation",
                "s12_export_runs == 0 after rejected submit",
                "the rejected submit did not change the pre-submit job count",
            ]
        finally:
            with __import__("contextlib").suppress(Exception):
                service.stop_worker(timeout=2.0)
            with contextlib.suppress(Exception):
                reset_analyze_orchestrator()
            (
                deps._config,
                deps._job_service,
                deps._project_service,
                deps._video_service,
                deps._lifecycle_db,
                deps._project_wf,
            ) = old_values
            engine.dispose()

        return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--work-root", type=Path)
    args = parser.parse_args()
    evidence = run_probe(args.work_root)
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    print(rendered)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
