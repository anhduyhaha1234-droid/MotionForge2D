"""S05-C04 — Production Job Service wiring (pristine integration test).

The confirmed defect (see ``output/s05t05_qa_backend.py``): a bare
``uvicorn app.main:app`` constructs a default ``JobService()`` whose
``DurableWorker`` is bound to a PLACEHOLDER session factory that raises
``RuntimeError("job service not initialized")``; ``JobService.initialize()``
created the REAL service factory but never rebound that worker, so
``start_worker()`` started the stale placeholder-bound worker and the
production entry point never executed Jobs.

This test proves the fix through the REAL production dependency path in a
PRISTINE process/module state — every application generation runs in a FRESH
Python subprocess that:

- sets only ``MOTIONFORGE_ROOT`` / ``MOTIONFORGE_OUTPUT`` /
  ``MOTIONFORGE_MODELS`` to a temporary root (never MAIN, never a worktree
  ``data/`` dir, never user data);
- imports ``app.main:app`` (the real entrypoint) with NO patching of
  ``deps._job_service`` and NO ``deps._lifecycle_db`` injection;
- enters the real FastAPI lifespan via ``TestClient``;
- creates/uploads a real synthetic video and POSTs ``/analyze`` EXACTLY ONCE;
- proves the DEFAULT worker claims and completes T02 -> T03 -> T04;
- enforces STAGE BOUNDARIES per fresh-process generation (S05-C04-R2
  finding 2): gen1 ends with proxy=0/scene=0, gen2 resumes+completes the
  proxy with scene still 0, only gen3 creates/completes the scene, gen4
  duplicates nothing — the test FAILS if a successor completes before
  its intended restart;
- restarts the real app lifecycle (fresh process) on the SAME temporary
  database and proves correct resume with no duplicate effects;
- proves the string ``job service not initialized`` never appears.

The parent test process only creates fixtures, runs the subprocesses and
READS the temporary database afterwards (read-only inspection via its own
session factory) — it never injects anything into ``deps``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.persistence.models import Job, Project, Scene, VideoItem

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The pristine generation probe executed as a fresh subprocess per app
#: generation.  It MUST NOT touch ``deps._job_service`` / ``deps._lifecycle_db``.
_RUNNER = r"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ["MF_REPO"])
sys.path.insert(0, str(REPO))
# The AppConfig singleton is created at import time from these env vars —
# the whole generation runs against the temporary root only.
os.environ.setdefault("MOTIONFORGE_OUTPUT", os.environ["MOTIONFORGE_ROOT"] + "/output")
os.environ.setdefault("MOTIONFORGE_MODELS", os.environ["MOTIONFORGE_ROOT"] + "/models")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402  (the REAL production entrypoint)
from app.workflow import analyze_orchestrator  # noqa: E402
from app.persistence import (  # noqa: E402
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import Job  # noqa: E402
from sqlalchemy import select  # noqa: E402

DB = Path(os.environ["MOTIONFORGE_ROOT"]) / "data" / "motionforge.db"


def _session():
    return create_session_factory(create_engine_for_path(DB))()


def _job_counts_and_states():
    with _session() as s:
        rows = s.execute(select(Job.id, Job.state, Job.idempotency_key)).all()
    counts = {"import": 0, "proxy": 0, "scene": 0}
    states = {"import": [], "proxy": [], "scene": []}
    for _job_id, state, key in rows:
        key = key or ""
        if "scene_detect" in key:
            counts["scene"] += 1
            states["scene"].append(state)
        elif key.startswith("GENERATE_PROXY:"):
            counts["proxy"] += 1
            states["proxy"].append(state)
        elif key.startswith("ANALYZE_MEDIA:video_item:"):
            counts["import"] += 1
            states["import"].append(state)
    return counts, states


def _wait_job(job_id, target, timeout=180.0):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        with _session() as s:
            row = s.execute(select(Job.state).where(Job.id == job_id)).first()
        state = row[0] if row else None
        if state is not None and state not in seen:
            seen.append(state)
        if state == target:
            return seen
        time.sleep(0.02)
    raise RuntimeError("job %s did not reach %r; seen=%s" % (job_id, target, seen))


def _wait_target(target, timeout=180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        counts, states = _job_counts_and_states()
        if target == "proxy" and counts["proxy"] == 1 and states["proxy"][0] == "completed":
            return
        if target == "scene" and counts["scene"] == 1 and states["scene"][0] == "completed":
            return
        time.sleep(0.02)
    counts, states = _job_counts_and_states()
    raise RuntimeError("target %r not completed: counts=%s states=%s" % (target, counts, states))


def _submit():
    with TestClient(app) as client:
        resp = client.post("/api/projects", json={"name": "C04 pristine"})
        assert resp.status_code == 201, resp.text
        pid = resp.json()["project_id"]
        source = Path(os.environ["MF_SOURCE"])
        with source.open("rb") as handle:
            up = client.post(
                "/api/projects/%s/video" % pid,
                files={"file": (source.name, handle, "video/mp4")},
            )
        assert up.status_code == 200, up.text
        resp = client.post(
            "/api/projects/%s/analyze" % pid,
            json={"generation": "1", "title": source.name},
        )
        assert resp.status_code == 200, resp.text
        state = resp.json()
        import_job_id = state["steps"]["import"]["job_id"]
        assert import_job_id is not None, state
        # STAGE BOUNDARY (S05-C04-R2 finding 2): the analyze POST happened
        # EXACTLY ONCE; freeze the app's OWN progression loop immediately
        # after it, so the proxy job CANNOT materialize in this generation.
        # This is a public stop() on the app's own orchestrator (the
        # lifespan started it) — never an advance_once call, never a deps
        # injection.  The import job completes under the independent
        # durable WORKER (started by the app lifecycle).
        analyze_orchestrator.get_analyze_orchestrator().stop(timeout=5.0)
        seen = _wait_job(import_job_id, "completed")
        counts, states = _job_counts_and_states()
        # gen1 boundary: import completed; proxy and scene still ABSENT.
        assert counts["proxy"] == 0 and counts["scene"] == 0, (counts, states)
        print(json.dumps({
            "phase": "submit",
            "project_id": pid,
            "import_job_id": import_job_id,
            "import_seen_states": seen,
            "counts": counts,
            "states": states,
        }))


def _resume(target):
    with TestClient(app) as client:
        # The lifespan startup scan (the app's OWN orchestrator.start())
        # materializes the next step's Job from durable rows.  Freeze the
        # loop immediately so the FOLLOWING step cannot materialize in this
        # generation (S05-C04-R2 finding 2 stage boundaries).  No manual
        # advance_once is ever called and no analyze POST is ever sent.
        analyze_orchestrator.get_analyze_orchestrator().stop(timeout=5.0)
        if target == "none":
            time.sleep(4.0)
        else:
            _wait_target(target)
        counts, states = _job_counts_and_states()
        # Stage boundaries asserted IN the fresh subprocess (a successor
        # completing before its intended restart FAILS the generation):
        if target == "proxy":
            # gen2: proxy completed, scene still ABSENT.
            assert counts["import"] == 1, (counts, states)
            assert counts["scene"] == 0, (counts, states)
        elif target == "scene":
            # gen3: scene completed; import/proxy still exactly one each.
            assert counts["import"] == 1 and counts["proxy"] == 1, (counts, states)
        elif target == "none":
            # gen4: no duplicate jobs/states anywhere.
            assert counts == {"import": 1, "proxy": 1, "scene": 1}, (counts, states)
            assert all(states[k] == ["completed"] for k in states), states
        print(json.dumps({"phase": "resume", "target": target, "counts": counts, "states": states}))


def main():
    phase = os.environ["MF_PHASE"]
    if phase == "submit":
        _submit()
    else:
        _resume(os.environ["MF_TARGET"])


if __name__ == "__main__":
    main()
"""


# ── Synthetic media fixture (real ffmpeg → tmp_path; never mock data) ───────


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


def _make_cut_video(path: Path, *, fps: int = 30) -> Path | None:
    """A 2s/60-frame clip with ONE hard cut: blue (1s) -> red (1s)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:duration=1.0:size=320x240:rate={fps}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=red:duration=1.0:size=320x240:rate={fps}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return path


# ── Generation driver + read-only DB inspection (parent side) ───────────────


def _run_generation(
    root: Path,
    runner: Path,
    *,
    phase: str,
    target: str | None = None,
    source: Path | None = None,
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
            "MF_TARGET": target or "",
        }
    )
    if source is not None:
        env["MF_SOURCE"] = str(source)
    return subprocess.run(
        [sys.executable, str(runner)],
        cwd=str(root),  # default managed root "artifacts" lands under the tmp root
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _db_counts(root: Path) -> dict:
    """Read-only job/scene counts over the temporary database."""
    from app.persistence import create_engine_for_path, create_session_factory

    factory = create_session_factory(
        create_engine_for_path(root / "data" / "motionforge.db")
    )
    with factory() as s:
        rows = s.execute(select(Job.id, Job.state, Job.idempotency_key)).all()
        scene_count = s.scalar(select(func.count()).select_from(Scene))
        video_items = s.scalar(select(func.count()).select_from(VideoItem))
    counts = {"import": 0, "proxy": 0, "scene": 0}
    states = {"import": [], "proxy": [], "scene": []}
    for _job_id, state, key in rows:
        key = key or ""
        if "scene_detect" in key:
            counts["scene"] += 1
            states["scene"].append(state)
        elif key.startswith("GENERATE_PROXY:"):
            counts["proxy"] += 1
            states["proxy"].append(state)
        elif key.startswith("ANALYZE_MEDIA:video_item:"):
            counts["import"] += 1
            states["import"].append(state)
    return {
        "counts": counts,
        "states": states,
        "scene_rows": int(scene_count or 0),
        "video_items": int(video_items or 0),
    }


def _staging_files(managed_root: Path) -> list[Path]:
    staging = managed_root / "staging"
    if not staging.is_dir():
        return []
    return [p for p in staging.rglob("*") if p.is_file()]


def _managed_files(managed_root: Path) -> list[Path]:
    if not managed_root.is_dir():
        return []
    return [p for p in managed_root.rglob("*") if p.is_file()]


def test_default_production_wiring_chain_completes_and_resumes(
    tmp_path: Path,
) -> None:
    """AC4: pristine default-path wiring end-to-end through app.main:app.

    Four fresh-process generations over ONE temporary root/database:
      gen1 (submit): create + upload + POST /analyze exactly once; the
        app's OWN default worker claims and completes the import job;
        proxy=0 and scene=0 (stage boundary: the successor does NOT
        materialize in this generation); full lifespan shutdown on exit.
      gen2 (resume): fresh process, NO analyze API request, NO manual
        advance_once — the startup scan materializes the proxy job and
        the fresh default worker completes it; scene=0 (stage boundary);
        full shutdown.
      gen3 (resume): startup scan materializes the scene job and the
        fresh default worker completes it (only this generation creates
        the scene).
      gen4 (resume none): a further restart over the completed chain
        duplicates nothing (jobs, artifacts, Scene rows, durable
        effects).
    The stage boundaries are asserted BOTH inside each fresh subprocess
    (a successor completing before its intended restart fails the
    generation) and by the parent from the temporary database — the test
    FAILS if any successor completes before the intended restart.
    No generation ever emits ``job service not initialized``.
    """
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")

    root = tmp_path / "pristine"
    root.mkdir()
    video = _make_cut_video(root / "cfr_cut.mp4")
    assert video is not None, "ffmpeg failed to create the CFR cut fixture"
    runner = root / "runner.py"
    runner.write_text(textwrap.dedent(_RUNNER), encoding="utf-8")

    # ── Generation 1: pristine process — POST once; import completes;
    # proxy=0 and scene=0 (stage boundary). ────────────────────────────
    g1 = _run_generation(root, runner, phase="submit", source=video)
    combined1 = g1.stdout + g1.stderr
    assert g1.returncode == 0, combined1
    assert "job service not initialized" not in combined1
    ev1 = json.loads(g1.stdout.strip().splitlines()[-1])
    pid = ev1["project_id"]
    assert ev1["phase"] == "submit"
    assert ev1["counts"]["import"] == 1
    assert ev1["states"]["import"] == ["completed"]
    # The default worker CLAIMED the import job (queued→running→completed;
    # the claim is the only path to completion — the placeholder-bound
    # worker could never complete anything).
    assert ev1["import_seen_states"][-1] == "completed"
    # gen1 stage boundary: the proxy/scene jobs did NOT materialize.
    assert ev1["counts"]["proxy"] == 0, ev1
    assert ev1["counts"]["scene"] == 0, ev1
    db1 = _db_counts(root)
    assert db1["counts"]["import"] == 1
    assert db1["states"]["import"] == ["completed"]
    assert db1["counts"]["proxy"] == 0 and db1["counts"]["scene"] == 0, db1
    assert db1["video_items"] == 1

    # ── Generation 2: FRESH process over the same DB; NO analyze API
    # request, NO manual advance_once; the startup scan + the fresh
    # default worker complete T03; scene still ABSENT (stage boundary). ─
    g2 = _run_generation(root, runner, phase="resume", target="proxy")
    combined2 = g2.stdout + g2.stderr
    assert g2.returncode == 0, combined2
    assert "job service not initialized" not in combined2
    ev2 = json.loads(g2.stdout.strip().splitlines()[-1])
    assert ev2["counts"]["import"] == 1, ev2
    assert ev2["counts"]["proxy"] == 1
    assert ev2["states"]["proxy"] == ["completed"]
    # gen2 stage boundary: the scene job did NOT materialize.
    assert ev2["counts"]["scene"] == 0, ev2
    db2 = _db_counts(root)
    assert db2["counts"]["proxy"] == 1 and db2["states"]["proxy"] == ["completed"]
    assert db2["counts"]["scene"] == 0, db2

    # ── Generation 3: restart after proxy — ONLY this generation creates
    # and completes the scene job (T04) under the fresh default worker. ─
    g3 = _run_generation(root, runner, phase="resume", target="scene")
    combined3 = g3.stdout + g3.stderr
    assert g3.returncode == 0, combined3
    assert "job service not initialized" not in combined3
    ev3 = json.loads(g3.stdout.strip().splitlines()[-1])
    assert ev3["counts"] == {"import": 1, "proxy": 1, "scene": 1}, ev3
    assert ev3["states"]["scene"] == ["completed"]
    db3 = _db_counts(root)
    assert db3["counts"]["scene"] == 1 and db3["states"]["scene"] == ["completed"]

    # ── Generation 4: a further restart over the completed chain
    # duplicates nothing (correct resume, no duplicate effects). ────────
    g4 = _run_generation(root, runner, phase="resume", target="none")
    combined4 = g4.stdout + g4.stderr
    assert g4.returncode == 0, combined4
    assert "job service not initialized" not in combined4
    ev4 = json.loads(g4.stdout.strip().splitlines()[-1])
    assert ev4["counts"] == {"import": 1, "proxy": 1, "scene": 1}
    assert ev4["states"] == {
        "import": ["completed"],
        "proxy": ["completed"],
        "scene": ["completed"],
    }

    # ── Terminal proof on the temporary database (read-only). ───────────
    final = _db_counts(root)
    assert final["counts"] == {"import": 1, "proxy": 1, "scene": 1}
    assert final["states"] == {
        "import": ["completed"],
        "proxy": ["completed"],
        "scene": ["completed"],
    }
    assert final["scene_rows"] == 2  # the cut clip has one hard cut
    assert final["video_items"] == 1
    # The durable ownership shell row for the project exists (the chain
    # services created it through the default path).
    from app.persistence import create_engine_for_path, create_session_factory

    factory = create_session_factory(
        create_engine_for_path(root / "data" / "motionforge.db")
    )
    with factory() as s:
        assert s.get(Project, pid) is not None
    managed = root / "artifacts"
    assert len(_managed_files(managed)) >= 2  # source + proxy artifacts
    assert _staging_files(managed) == []  # staging fully drained
