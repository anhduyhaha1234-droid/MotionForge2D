"""S08-T02 — Pristine production wiring for DISCOVER_OBJECTS (no DI/mocks).

Mirrors the S05-C04 pristine recipe: every application generation runs in a
FRESH Python subprocess that

- sets only ``MOTIONFORGE_ROOT`` / ``MOTIONFORGE_OUTPUT`` /
  ``MOTIONFORGE_MODELS`` to a temporary root and
  ``MOTIONFORGE_EXTRACTION_PROVIDER=deterministic`` (the EXPLICIT CI/QA
  provider selection — the production default ``model`` path fails closed
  and is covered by the focused suite);
- imports ``app.main:app`` (the real entrypoint) with NO patching of
  ``deps._job_service`` / ``deps._lifecycle_db`` and NO monkeypatching;
- enters the real FastAPI lifespan via ``TestClient``;
- creates a durable project + video item through the real v2 API, seeds a
  ready source artifact + scene rows (test fixture inputs), POSTs the
  extraction EXACTLY ONCE and proves the DEFAULT worker claims and
  completes the DISCOVER_OBJECTS job;
- generation 2 restarts the whole app lifecycle (fresh process) over the
  SAME temporary database and proves idempotent reuse (same job id, no
  duplicate rows/artifacts) and the read API exposing only committed
  outputs.

The parent process only creates fixtures, runs the subprocesses and READS
the temporary database afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from sqlalchemy import func, select

from app.persistence.models import Artifact, Job, ObjectOccurrence, ObjectRole

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_RUNNER = r"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ["MF_REPO"])
sys.path.insert(0, str(REPO))
os.environ.setdefault("MOTIONFORGE_OUTPUT", os.environ["MOTIONFORGE_ROOT"] + "/output")
os.environ.setdefault("MOTIONFORGE_MODELS", os.environ["MOTIONFORGE_ROOT"] + "/models")
# Explicit CI/QA provider selection (never a production fallback).
os.environ["MOTIONFORGE_EXTRACTION_PROVIDER"] = "deterministic"
# Genuine QA/test mode (isolated roots) authorizes the QA-only adapter
# (S08-T02-C2 acceptance 7-9).
os.environ["MOTIONFORGE_EXTRACTION_QA_MODE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402  (the REAL production entrypoint)
from app.persistence import (  # noqa: E402
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (  # noqa: E402
    Artifact,
    Job,
    ObjectOccurrence,
    ObjectRole,
    Scene,
    VideoItem,
)
from sqlalchemy import func, select  # noqa: E402

DB = Path(os.environ["MOTIONFORGE_ROOT"]) / "data" / "motionforge.db"
import hashlib as _h
SOURCE_MEDIA_BYTES = (bytes(range(1, 256)) * 48) + b"S08-T02-wiring-source"
SOURCE_SHA = _h.sha256(SOURCE_MEDIA_BYTES).hexdigest()


def _session():
    return create_session_factory(create_engine_for_path(DB))()


def _seed_inputs(project_id: str, video_item_id: str) -> None:
    # Fixture inputs: ready source artifact + canonical scene rows.
    with _session() as s:
        video = s.get(VideoItem, video_item_id)
        assert video is not None, "video item missing after API create"
        rel = f"artifacts/default/video/{video_item_id}/import/source.mp4"
        # Managed root = <project_root>/artifacts; artifact relative paths
        # already carry the "artifacts/" prefix (video_import convention).
        managed_target = (
            Path(os.environ["MOTIONFORGE_ROOT"]) / "artifacts" / rel
        )
        managed_target.parent.mkdir(parents=True, exist_ok=True)
        managed_target.write_bytes(SOURCE_MEDIA_BYTES)
        source = Artifact(
            workspace_id="default",
            kind="video",
            relative_path=rel,
            state="ready",
            sha256=SOURCE_SHA,
            size_bytes=len(SOURCE_MEDIA_BYTES),
            mime_type="video/mp4",
        )
        s.add(source)
        s.flush()
        video.source_artifact_id = source.id
        video.width = 320
        video.height = 240
        video.duration_ms = 6000
        video.fps_num = 30
        video.fps_den = 1
        for index in range(2):
            s.add(
                Scene(
                    video_item=video,
                    position=index,
                    start_frame=index * 90,
                    end_frame=index * 90 + 89,
                    start_time_ms=index * 3000,
                    end_time_ms=index * 3000 + 2999,
                    status="pending",
                )
            )
        s.commit()


def _wait_job(job_id: str, timeout: float = 120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _session() as s:
            state = s.execute(select(Job.state).where(Job.id == job_id)).scalar()
        if state in ("completed", "failed", "cancelled"):
            return state
        time.sleep(0.02)
    raise RuntimeError(f"job {job_id} did not reach terminal state")


def _submit():
    with TestClient(app) as client:
        resp = client.post("/api/v2/projects", json={"name": "T02 pristine"})
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["project_id"]
        resp = client.post(
            f"/api/v2/projects/{project_id}/videos",
            json={"title": "primary.mp4"},
        )
        assert resp.status_code == 201, resp.text
        video_item_id = resp.json()["video_item_id"]
        _seed_inputs(project_id, video_item_id)
        resp = client.post(
            "/api/v2/object-intelligence/extraction",
            json={
                "project_id": project_id,
                "video_item_id": video_item_id,
                "source_sha256": SOURCE_SHA,
                "generation": "1",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        job_id = body["job_id"]
        state = _wait_job(job_id)
        assert state == "completed", f"job {job_id} ended {state}"
        with _session() as s:
            roles = s.scalar(select(func.count()).select_from(ObjectRole))
            images = s.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.kind == "image")
            )
            occurrences = s.scalar(select(func.count()).select_from(ObjectOccurrence))
            from app.persistence.models import (  # noqa: E501
                OccurrenceSegment,
                SceneGraphContact,
                SceneGraphOcclusion,
                SegmentMotion,
            )
            segs = s.scalar(select(func.count()).select_from(OccurrenceSegment))
            motions = s.scalar(select(func.count()).select_from(SegmentMotion))
            occls = s.scalar(select(func.count()).select_from(SceneGraphOcclusion))
            contacts = s.scalar(select(func.count()).select_from(SceneGraphContact))
            from sqlalchemy import text as _text
            fk = s.execute(_text("PRAGMA foreign_key_check")).fetchall()
            assert fk == [], f"FK check failed: {fk}"
            integrity = s.execute(_text("PRAGMA integrity_check")).scalar()
            assert integrity == "ok"
        # The outputs endpoint serves ONLY the committed outputs + structural graph.
        resp = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
        assert resp.status_code == 200, resp.text
        outputs = resp.json()
        assert len(outputs["outputs"]) == 5, outputs
        # T02: structural graph exposed for completed jobs
        assert len(outputs.get("segments", [])) == 4, outputs
        assert len(outputs.get("motions", [])) >= 4, outputs
        assert len(outputs.get("occlusions", [])) >= 2, outputs
        assert len(outputs.get("contacts", [])) >= 2, outputs
        print(
            json.dumps(
                {
                    "phase": "submit",
                    "project_id": project_id,
                    "video_item_id": video_item_id,
                    "job_id": job_id,
                    "state": state,
                    "roles": int(roles or 0),
                    "occurrences": int(occurrences or 0),
                    "images": int(images or 0),
                    "segments": int(segs or 0),
                    "motions": int(motions or 0),
                    "occlusions": int(occls or 0),
                    "contacts": int(contacts or 0),
                }
            )
        )


def _resume():
    with TestClient(app) as client:
        with _session() as s:
            row = s.execute(
                select(Job.id, Job.input_manifest_json)
                .where(Job.job_type == "DISCOVER_OBJECTS")
                .order_by(Job.created_at.desc())
            ).first()
        assert row is not None
        job_id, manifest_json = row
        manifest = json.loads(manifest_json)
        resp = client.post(
            "/api/v2/object-intelligence/extraction",
            json={
                "project_id": manifest["project_id"],
                "video_item_id": manifest["video_item_id"],
                "source_sha256": manifest.get("source_sha256"),
                "generation": manifest["generation"],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["job_id"] == job_id, (body, job_id)
        assert body["reused"] is True, body
        resp = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
        assert resp.status_code == 200, resp.text
        outputs = resp.json()
        assert len(outputs["outputs"]) == 5, outputs
        with _session() as s:
            roles = s.scalar(select(func.count()).select_from(ObjectRole))
            images = s.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.kind == "image")
            )
            jobs = s.scalar(
                select(func.count()).select_from(Job).where(Job.job_type == "DISCOVER_OBJECTS")
            )
        print(
            json.dumps(
                {
                    "phase": "resume",
                    "job_id": job_id,
                    "reused": body["reused"],
                    "jobs": int(jobs or 0),
                    "roles": int(roles or 0),
                    "images": int(images or 0),
                }
            )
        )


def main():
    phase = os.environ["MF_PHASE"]
    if phase == "submit":
        _submit()
    else:
        _resume()


if __name__ == "__main__":
    main()
"""


def _run_generation(
    root: Path,
    runner: Path,
    *,
    phase: str,
    timeout: int = 240,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "MOTIONFORGE_ROOT": str(root),
            "MOTIONFORGE_OUTPUT": str(root / "output"),
            "MOTIONFORGE_MODELS": str(root / "models"),
            "MF_REPO": str(PROJECT_ROOT),
            "MF_PHASE": phase,
        }
    )
    return subprocess.run(
        [sys.executable, str(runner)],
        cwd=str(root),  # default managed root "artifacts" lands under the tmp root
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _db_counts(root: Path) -> dict[str, int]:
    from app.persistence import create_engine_for_path, create_session_factory

    factory = create_session_factory(
        create_engine_for_path(root / "data" / "motionforge.db")
    )
    with factory() as s:
        from app.persistence.models import (
            OccurrenceSegment,
            SceneGraphContact,
            SceneGraphOcclusion,
            SegmentMotion,
        )
        return {
            "jobs": int(
                s.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.job_type == "DISCOVER_OBJECTS")
                )
                or 0
            ),
            "roles": int(s.scalar(select(func.count()).select_from(ObjectRole)) or 0),
            "occurrences": int(
                s.scalar(select(func.count()).select_from(ObjectOccurrence)) or 0
            ),
            "images": int(
                s.scalar(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.kind == "image")
                )
                or 0
            ),
            "manifests": int(
                s.scalar(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.kind == "document")
                )
                or 0
            ),
            "segments": int(s.scalar(select(func.count()).select_from(OccurrenceSegment)) or 0),
            "motions": int(s.scalar(select(func.count()).select_from(SegmentMotion)) or 0),
            "occlusions": int(s.scalar(select(func.count()).select_from(SceneGraphOcclusion)) or 0),
            "contacts": int(s.scalar(select(func.count()).select_from(SceneGraphContact)) or 0),
        }


def test_pristine_production_wiring_extraction_completes_and_resumes(
    tmp_path: Path,
) -> None:
    """AC: real app.main:app + default JobService/worker; deterministic CI
    provider selected EXPLICITLY via env; two fresh-process generations:
    gen1 completes the job, gen2 reuses it idempotently with no duplicates."""
    root = tmp_path / "pristine"
    root.mkdir()
    runner = root / "runner.py"
    runner.write_text(textwrap.dedent(_RUNNER), encoding="utf-8")

    g1 = _run_generation(root, runner, phase="submit")
    combined1 = g1.stdout + g1.stderr
    assert g1.returncode == 0, combined1
    assert "job service not initialized" not in combined1
    ev1 = json.loads(g1.stdout.strip().splitlines()[-1])
    assert ev1["phase"] == "submit"
    assert ev1["state"] == "completed"
    assert ev1["roles"] == 2
    assert ev1["occurrences"] == 2
    assert ev1["images"] == 4
    job_id = ev1["job_id"]
    db1 = _db_counts(root)
    assert db1 == {"jobs": 1, "roles": 2, "occurrences": 2, "images": 4, "manifests": 1, "segments": 4, "motions": 8, "occlusions": 2, "contacts": 2}, db1  # noqa: E501

    g2 = _run_generation(root, runner, phase="resume")
    combined2 = g2.stdout + g2.stderr
    assert g2.returncode == 0, combined2
    assert "job service not initialized" not in combined2
    ev2 = json.loads(g2.stdout.strip().splitlines()[-1])
    assert ev2["phase"] == "resume"
    assert ev2["reused"] is True
    assert ev2["job_id"] == job_id
    db2 = _db_counts(root)
    # Restart produced zero duplicates: exactly one job, one effect set.
    assert db2 == db1, (db2, db1)

    # Staging fully drained; published bytes match the artifact rows.
    managed = root / "artifacts"
    staging = managed / "staging"
    if staging.is_dir():
        assert not [p for p in staging.rglob("*") if p.is_file()]
    published = [p for p in managed.rglob("*") if p.is_file() and "staging" not in p.parts]
    assert len(published) == 6  # source media + 4 images + manifest
