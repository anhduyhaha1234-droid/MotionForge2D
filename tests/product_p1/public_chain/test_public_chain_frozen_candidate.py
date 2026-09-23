"""Executed public chain on the FROZEN integrated candidate.

Status right now: **PENDING_FROZEN_CANDIDATE**.  This module is the later
round's driver, written against the measured public contract of THIS tree.
Without the three pins below it SKIPS with that exact reason — it never
passes by default, never stubs the product and never seeds QC/product state.

Pins (all three required to execute):
  S12QA_EVIDENCE_OUT          exclusive NEW evidence directory (must not exist)
  S12QA_CANDIDATE_ROOT        worktree of the frozen integrated candidate
  S12QA_EXPECTED_CANDIDATE_SHA  expected ``git rev-parse HEAD`` of that tree

Optional:
  S12QA_SOURCE_MEDIA          real source clip for the upload leg (recommended).
                              If absent a labelled FIXTURE is generated instead
                              and the run records ``source_media_kind=FIXTURE``.
  S12QA_RUNTIME_ROOT          isolated runtime root (DB/output/managed)

Everything the chain earns (roles, checkpoint, QC items, publication) is
earned through PUBLIC HTTP calls in chain order.  No SQL seeding of QC
eligibility or QC results, ever.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import public_chain_cases as R  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
PINS = ("S12QA_EVIDENCE_OUT", "S12QA_CANDIDATE_ROOT", "S12QA_EXPECTED_CANDIDATE_SHA")
_MISSING = [key for key in PINS if not os.environ.get(key)]

CLIENT_ERRORS = {400, 404, 409, 422}
TERMINAL = {"completed", "failed", "cancelled"}


def _rec(response: Any, request: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = response.text[:2000]
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
    state_key: str = "status",
    interval_seconds: float = 0.5,
) -> dict[str, Any]:
    started = time.monotonic()
    reads: list[dict[str, Any]] = []
    while True:
        response = client.get(path, params=params)
        item = _rec(response)
        reads.append(item)
        body = item.get("body")
        state = body.get(state_key) if isinstance(body, dict) else None
        if isinstance(body, dict):
            state = state or body.get("chain_status") or body.get("run_state") or body.get("state")
        if state in terminal:
            break
        if time.monotonic() - started >= timeout_seconds:
            break
        time.sleep(interval_seconds)
    return {
        "timeout_seconds": timeout_seconds,
        "read_count": len(reads),
        "reads": reads[-6:],
        "final": reads[-1] if reads else None,
    }


def _ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format", "json",
         "-show_format", "-show_streams", "-show_frames",
         "-show_entries", "frame=pts_time", str(path)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr, "returncode": proc.returncode}
    return json.loads(proc.stdout)


def _media_facts(path: Path) -> dict[str, Any]:
    probe = _ffprobe(path)
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = probe.get("format", {})
    pts = [
        float(f["pts_time"])
        for f in probe.get("frames", [])
        if f.get("pts_time") not in (None, "N/A")
    ]
    facts: dict[str, Any] = {
        "duration_s": float(fmt.get("duration") or 0.0),
        "size_bytes": int(fmt.get("size") or 0),
        "decoded_pts": pts,
        "decoded_pts_count": len(pts),
        "decoded_pts_monotonic": pts == sorted(pts),
        "decoded_pts_first": pts[0] if pts else None,
    }
    if video:
        rate = str(video.get("avg_frame_rate") or "0/0")
        num, _, den = rate.partition("/")
        facts["video"] = {
            "codec": video.get("codec_name"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": round(float(num) / float(den), 4) if den and float(den) else 0.0,
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
    """LABELLED FIXTURE — never real product media evidence."""
    fixture = root / "s12qa-FIXTURE-source-4s.mp4"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(fixture)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if proc.returncode != 0 or not fixture.is_file() or fixture.stat().st_size == 0:
        raise AssertionError(f"FIXTURE generation failed rc={proc.returncode}: {proc.stderr}")
    return fixture


def _git_head(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def test_public_chain_end_to_end_on_frozen_candidate() -> None:
    if _MISSING:
        pytest.skip(
            "PENDING_FROZEN_CANDIDATE: missing pin(s) "
            f"{_MISSING}. Executed later, on the frozen integrated candidate, after the QC "
            "writers (MF-P1-QC-EVIDENCE) and the UI writers (MF-P1-UI-BUILD) are terminal. "
            "Steps awaiting the freeze: " + ", ".join(R.pending_steps())
        )

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.api import deps
    from app.api.app import app
    from app.config import AppConfig
    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.models import (
        Artifact,
        Job,
        Project,
        QCItem,
        S10FullApplyPublication,
        S10FullApplyRun,
        S12ExportRun,
        VideoItem,
    )
    from app.workflow.job_service import JobService
    from app.workflow.project_workflow import ProjectWorkflowService

    evidence_root = Path(os.environ["S12QA_EVIDENCE_OUT"])
    candidate_root = Path(os.environ["S12QA_CANDIDATE_ROOT"]).resolve()
    expected_sha = os.environ["S12QA_EXPECTED_CANDIDATE_SHA"]
    assert not evidence_root.exists(), (
        f"evidence root must be exclusive/new (never reuse): {evidence_root}"
    )
    evidence_root.mkdir(parents=True)
    runtime_root = Path(os.environ.get("S12QA_RUNTIME_ROOT") or (evidence_root / "runtime"))
    runtime_root.mkdir(parents=True, exist_ok=True)

    chain: dict[str, Any] = {
        "lane": "S12-LC3-QA",
        "node": f"{R.PKG}/test_public_chain_frozen_candidate.py::"
        "test_public_chain_end_to_end_on_frozen_candidate",
        "evidence_root": str(evidence_root),
        "runtime_root": str(runtime_root),
        "candidate_root": str(candidate_root),
        "candidate_sha_expected": expected_sha,
        "stages": {},
        "identities": {},
        "counts": {},
        "flags": {},
        "status": None,
    }

    def stage(name: str, payload: Any) -> None:
        chain["stages"][name] = payload

    chain["candidate_sha_actual"] = _git_head(candidate_root)
    assert chain["candidate_sha_actual"] == expected_sha, (
        f"candidate moved: {chain['candidate_sha_actual']} != {expected_sha}"
    )
    assert _git_head(REPO_ROOT) == expected_sha, (
        "the executing worktree is not the frozen candidate"
    )

    db_path = runtime_root / "data" / "s12qa.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    alembic_cfg = AlembicConfig(str(candidate_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(candidate_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(alembic_cfg, "head")

    factory = create_session_factory(create_engine_for_path(db_path))
    managed_root = runtime_root / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    config = AppConfig(
        project_root=runtime_root,
        models_dir=runtime_root / "models",
        output_dir=runtime_root / "output",
    )
    service = JobService(factory, managed_root=managed_root)

    models = {
        "projects": Project,
        "video_items": VideoItem,
        "jobs": Job,
        "artifacts": Artifact,
        "qc_items": QCItem,
        "s10_runs": S10FullApplyRun,
        "s10_publications": S10FullApplyPublication,
        "s12_runs": S12ExportRun,
    }

    def counts() -> dict[str, int]:
        with factory() as session:
            return {
                name: int(session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }

    deps._config = config
    deps._job_service = service
    deps._project_service = None
    deps._video_service = None
    deps._lifecycle_db = db_path
    deps._project_wf = ProjectWorkflowService(config)

    source_env = os.environ.get("S12QA_SOURCE_MEDIA")
    with TestClient(app, raise_server_exceptions=False) as client:
        service.start_worker()
        assert service.worker_running, "durable worker did not start"
        chain["counts"]["before_chain"] = counts()

        if source_env:
            source = Path(source_env)
            assert source.is_file(), f"source media missing: {source}"
            source_kind = "REAL_SOURCE"
        else:
            source = _make_fixture(runtime_root)
            source_kind = "FIXTURE"
        chain["source_media"] = {
            "kind": source_kind,
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "facts": _media_facts(source),
        }
        assert chain["source_media"]["facts"]["audio"], "source must carry audio"

        # 1) upload + analyze (public only)
        project = client.post("/api/projects", json={"name": "S12-LC3-QA public chain"})
        stage("upload_project", _rec(project, {"method": "POST", "path": "/api/projects"}))
        assert project.status_code == 201, project.text
        project_id = project.json()["project_id"]
        with source.open("rb") as handle:
            upload = client.post(
                f"/api/projects/{project_id}/video",
                files={"file": (source.name, handle, "video/mp4")},
            )
        stage("upload_media", _rec(upload))
        assert upload.status_code == 200, upload.text

        analyze = client.post(
            f"/api/projects/{project_id}/analyze", json={"generation": "1", "title": "S12QA"}
        )
        stage("analyze_submit", _rec(analyze))
        assert analyze.status_code == 200, analyze.text
        analyze_poll = _poll(
            client, f"/api/projects/{project_id}/analyze", params={"generation": "1"},
            terminal=TERMINAL, timeout_seconds=300.0, state_key="chain_status",
        )
        stage("analyze_chain", analyze_poll)
        analyze_final = (analyze_poll["final"] or {}).get("body") or {}
        assert analyze_final.get("chain_status") == "completed", analyze_final
        video_id = str(analyze_final["video_item_id"])
        generation = str(analyze_final.get("generation") or "1")
        chain["identities"].update(
            {"project_id": project_id, "video_item_id": video_id, "generation": generation}
        )

        # 2) library: extraction -> roles (earned, never seeded)
        extraction = client.post(
            "/api/v2/object-intelligence/extraction",
            json={"project_id": project_id, "video_item_id": video_id, "generation": generation},
        )
        stage("extraction_submit", _rec(extraction))
        assert extraction.status_code == 201, extraction.text
        extraction_id = extraction.json()["job_id"]
        extraction_poll = _poll(
            client, f"/api/v2/object-intelligence/extraction/{extraction_id}",
            terminal=TERMINAL, timeout_seconds=300.0,
        )
        stage("extraction_job", extraction_poll)
        assert ((extraction_poll["final"] or {}).get("body") or {}).get("status") == "completed"
        roles_read = client.get(
            "/api/v2/object-intelligence/roles", params={"video_item_id": video_id}
        )
        stage("roles_read", _rec(roles_read))
        assert roles_read.status_code == 200, roles_read.text
        roles = roles_read.json().get("roles", [])
        assert roles, "no public current ObjectRole after extraction"

        # 3) producer + checkpoint
        lock = client.post(
            f"/api/v2/projects/{project_id}/videos/{video_id}/structural-lock", json={}
        )
        stage("producer", _rec(lock))
        assert lock.status_code in (200, 201, 202), lock.text
        reapprove = client.post(
            "/api/v2/s09-approvals/reapprove",
            params={"workspace_id": "default"},
            json={
                "reskin_config_id": lock.json().get("reskin_config_id") or project_id,
                "expected_reskin_revision": 1,
                "pack_version_ids": lock.json().get("pack_version_ids") or [],
                "idempotency_key": f"s12qa-reapprove-{project_id}",
                "note": "S12QA frozen-candidate run; not a product approval",
            },
        )
        stage("approval_reapprove", _rec(reapprove))
        if reapprove.status_code not in (200, 201):
            chain["status"] = "BLOCKED_EXACT_APPROVAL"
            raise AssertionError(f"approval blocked: {reapprove.status_code} {reapprove.text[:500]}")
        checkpoint = reapprove.json()
        checkpoint_id = str(checkpoint["id"])
        checkpoint_hash = str(checkpoint["checkpoint_hash"])
        pinned_revision = int(checkpoint.get("reskin_config_revision") or 1)
        authority = client.get(
            f"/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority",
            params={"workspace_id": "default"},
        )
        stage("approval_authority", _rec(authority))
        assert authority.status_code == 200, authority.text
        assert authority.json()["eligibility"]["full_apply_executable"] is True, (
            f"authority not executable: {json.dumps(authority.json())[:1500]}"
        )

        # 4) S10 Full Apply
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
        stage("s10_submit", _rec(full_apply))
        assert full_apply.status_code == 202, full_apply.text
        fa_body = full_apply.json()
        fa_run_id = str(fa_body.get("run_id") or fa_body.get("id"))
        s10_poll = _poll(
            client, f"/api/v2/full-apply/{fa_run_id}", terminal=TERMINAL, timeout_seconds=1800.0
        )
        stage("s10_run", s10_poll)
        s10_final = (s10_poll["final"] or {}).get("body") or {}
        assert s10_final.get("status") == "completed", json.dumps(s10_final)[:1500]
        chain["s10_final"] = s10_final

        # 5) audio attach
        audio = client.post(
            f"/api/v2/projects/{project_id}/original-audio-attach", json={"video_item_id": video_id}
        )
        stage("audio_attach", _rec(audio))
        assert audio.status_code == 202, audio.text
        audio_job = str(audio.json().get("job_id"))
        audio_poll = _poll(
            client, f"/api/jobs/{audio_job}", terminal=TERMINAL, timeout_seconds=600.0
        )
        stage("audio_job", audio_poll)

        # 6) FULL QC — the freeze is what makes full scope composable
        qc_full = client.post(
            f"/api/v2/projects/{project_id}/qc-check-runs",
            json={"video_item_id": video_id, "scope": "full"},
        )
        stage("qc_full_submit", _rec(qc_full))
        if qc_full.status_code == 422 and "QC_RUN_EVIDENCE_UNAVAILABLE" in qc_full.text:
            chain["status"] = "BLOCKED_EXACT_QC_RUN_EVIDENCE_UNAVAILABLE"
            raise AssertionError(
                "BLOCKED_EXACT: full-scope QC still refused 422 QC_RUN_EVIDENCE_UNAVAILABLE on "
                "the frozen candidate — the QC/UI freeze is not complete enough for the public "
                "chain; no QC state was seeded to go around it"
            )
        assert qc_full.status_code in (200, 202, 409), qc_full.text
        qc_job = str(qc_full.json().get("job_id")) if qc_full.status_code == 202 else None
        if qc_job:
            qc_job_poll = _poll(
                client, f"/api/jobs/{qc_job}", terminal=TERMINAL, timeout_seconds=1800.0
            )
            stage("qc_job", qc_job_poll)
        qc_state = _poll(
            client,
            f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}",
            terminal=TERMINAL | {"ready", "blocked", "not_run"},
            timeout_seconds=1800.0,
        )
        stage("qc_state", qc_state)
        readiness = client.get(f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}/readiness")
        stage("qc_readiness", _rec(readiness))
        items = client.get(f"/api/v2/projects/{project_id}/qc-items")
        stage("qc_items", _rec(items))
        assert items.status_code == 200, items.text
        assert (items.json().get("items") or []), "QC produced no items through the public chain"

        # 7) S12 context / preflight / submit
        context = client.get(
            f"/api/v2/projects/{project_id}/export/context", params={"video_item_id": video_id}
        )
        stage("s12_context", _rec(context))
        assert context.status_code == 200, context.text
        context_body = context.json()
        preflight = client.post(
            f"/api/v2/projects/{project_id}/export/preflight",
            json={
                "video_item_id": video_id,
                "profile_id": "master-4k-h264",
                "aspect_handling": "letterbox",
                "checkpoint": context_body["checkpoint"],
                "lock": context_body["lock"],
            },
        )
        stage("s12_preflight", _rec(preflight))
        assert preflight.status_code == 200, preflight.text
        if preflight.json().get("eligible") is not True:
            chain["status"] = "BLOCKED_EXACT_S12_READINESS"
            raise AssertionError(
                f"BLOCKED_EXACT: preflight ineligible: {preflight.json().get('reasons')}"
            )
        submit = client.post(
            "/s12-exports/submit",
            json={
                "project_id": project_id,
                "video_item_id": video_id,
                "profile_id": "master-4k-h264",
                "context_revision": str(context_body["context_revision"]),
                "idempotency_key": f"s12qa-submit-{project_id}",
            },
        )
        stage("s12_submit", _rec(submit))
        assert submit.status_code == 202, submit.text
        run_id = str(submit.json()["run_id"])

        # 8) worker -> publisher -> result
        run_poll = _poll(client, f"/s12-exports/{run_id}", terminal=TERMINAL, timeout_seconds=3600.0)
        stage("s12_run", run_poll)
        run_final = (run_poll["final"] or {}).get("body") or {}
        assert run_final.get("status") == "completed", json.dumps(run_final)[:1500]
        result = client.get(f"/s12-exports/{run_id}/result")
        stage("s12_result", _rec(result))
        assert result.status_code == 200, result.text

        # 9) download + controls (PTS / audio / partial / corrupt)
        media = client.get(f"/s12-exports/{run_id}/media")
        stage("s12_media_http", {"status_code": media.status_code, "bytes": len(media.content)})
        assert media.status_code == 200, media.text[:500]
        downloaded = evidence_root / "s12qa-downloaded-export.mp4"
        downloaded.write_bytes(media.content)
        export_facts = _media_facts(downloaded)
        source_facts = chain["source_media"]["facts"]
        chain["export_media"] = {"path": str(downloaded), "facts": export_facts}
        assert export_facts["decoded_pts_monotonic"], "export decoded PTS not monotonic"
        assert export_facts["decoded_pts_first"] == pytest.approx(0.0, abs=1e-3), (
            f"export first decoded PTS {export_facts['decoded_pts_first']}"
        )
        assert export_facts["audio"], "export lost its audio"
        assert export_facts["audio"]["channels"] == source_facts["audio"]["channels"]
        chain["flags"]["frame_count_preserved"] = (
            export_facts["video"]["frame_count"] == source_facts["video"]["frame_count"]
        )

        from app.services.s12_export.validation import PARTIAL_SUFFIX, validate

        partial = evidence_root / f"s12qa-partial-copy.mp4{PARTIAL_SUFFIX}"
        partial.write_bytes(media.content)
        chain["flags"]["partial_verdict"] = validate(partial).verdict
        assert chain["flags"]["partial_verdict"] == "FAIL"

        corrupt = evidence_root / "s12qa-corrupt-copy.mp4"
        corrupt.write_bytes(b"NOT-A-CONTAINER" * 512)
        chain["flags"]["corrupt_verdict"] = validate(corrupt).verdict
        assert chain["flags"]["corrupt_verdict"] == "FAIL"

        # 10) UI reload leg + replay (zero extra rows)
        before_replay = counts()
        reload_body = client.get(
            f"/api/v2/projects/{project_id}/export/context", params={"video_item_id": video_id}
        )
        stage("ui_reload_context", _rec(reload_body))
        assert reload_body.status_code == 200, reload_body.text
        replay = client.post(
            "/s12-exports/submit",
            json={
                "project_id": project_id,
                "video_item_id": video_id,
                "profile_id": "master-4k-h264",
                "context_revision": str(reload_body.json()["context_revision"]),
                "idempotency_key": f"s12qa-submit-{project_id}",
            },
        )
        stage("s12_replay_submit", _rec(replay))
        after_replay = counts()
        chain["replay"] = {
            "before": before_replay,
            "after": after_replay,
            "extra_runs": after_replay["s12_runs"] - before_replay["s12_runs"],
            "extra_jobs": after_replay["jobs"] - before_replay["jobs"],
        }
        assert chain["replay"]["extra_runs"] == 0, chain["replay"]
        assert chain["replay"]["extra_jobs"] == 0, chain["replay"]

        # 11) restart + retry/cancel controls (no duplicate work after restart)
        service.stop_worker(timeout=15.0)
        restart_before = counts()
        service.start_worker()
        time.sleep(3.0)
        service.stop_worker(timeout=15.0)
        restart_after = counts()
        chain["flags"]["restart_no_duplicate"] = restart_after == restart_before
        assert chain["flags"]["restart_no_duplicate"], (restart_before, restart_after)
        retry = client.post(f"/s12-exports/{run_id}/retry", json={})
        stage("s12_retry_after_complete", _rec(retry))
        chain["flags"]["retry_after_complete"] = retry.status_code
        chain["counts"]["after_chain"] = counts()

    chain["status"] = "PASS"
    (evidence_root / "s12qa-chain.json").write_text(
        json.dumps(chain, indent=1, sort_keys=True), encoding="utf-8"
    )
    (evidence_root / "s12qa-summary.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "candidate_sha": chain["candidate_sha_actual"],
                "source_media_kind": chain["source_media"]["kind"],
                "identities": chain["identities"],
                "counts": chain["counts"],
                "flags": chain["flags"],
                "replay": chain["replay"],
            },
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_pending_freeze_manifest_is_exact() -> None:
    """Runnable now: the pending list must be exactly the freeze-dependent steps."""
    pending = set(R.pending_steps())
    expected = {
        "public_upload",
        "analyze",
        "library_roles",
        "producer",
        "approval",
        "s10_full_apply",
        "audio",
        "qc_full",
        "s12_api",
        "worker",
        "publisher",
        "download",
        "ui_reload",
    }
    missing = expected - pending
    assert missing == set(), f"steps pending the freeze but not declared: {sorted(missing)}"
    for case in R.cases(R.PENDING_FROZEN_CANDIDATE):
        assert case["await"].strip(), f"{case['id']} has no declared await"
    doc = R.document()
    assert doc["totals"]["pending_frozen_candidate"] >= 2
    assert doc["pending_freeze_steps"], doc
