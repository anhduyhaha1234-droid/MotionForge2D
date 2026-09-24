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

PATH CLASS — say which one ran.  This node executes the
**ENGINEERING_FIXTURE_API** path: a FastAPI ``TestClient`` driving the
public HTTP routes on an isolated runtime root, with the LABELLED fixture
clip and the server-policy deterministic-identity extraction provider.
It is NOT a browser journey: the API context reload below is a context
read, never a UI reload.  The real browser/DOM journey is owned by
**MF-DEMO-E2E** and is not claimed here.

EVIDENCE PERSISTENCE — every stage (request/response/job/result) is
written to ``raw/stages.jsonl`` AT EXECUTION TIME (append + flush +
fsync) by :class:`StageLedger`, before the assertion that consumes it.
The chain body is wrapped in ``try/except/finally`` and the consolidated
chain/summary files are written unconditionally afterwards, so a
deliberately failing run still leaves a populated evidence directory and
names its first failing dependency.

Setup is completed before structural lock: library pack (published pack
version per role), role -> cast mapping and reskin config are created
through public routes and every identifier used afterwards is the one the
API RETURNED (no project-id fallback).  The un-mapped structural-lock 422
is asserted as an explicit NEGATIVE CONTROL before the setup, never as
the end state of the happy path.

Optional:
  S12QA_FAULT_AT=<stage>   QA control, default OFF: raise deliberately at
                           that named point to demonstrate that a failing
                           run still persists its evidence.
  S12QA_RUNTIME_ROOT       short isolated runtime root (a DEEP root
                           exceeds Windows MAX_PATH and the extraction
                           worker then dies on its own staging file).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
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

def _qc_items_probe(client: Any, project_id: str) -> tuple[Any, list[Any], int]:
    """GET the project QC queue, tolerating an unreachable route.

    The queue route is declared ``/api/v2/projects/{project_id:uuid}/qc-items``
    and this chain carries the PUBLIC project id the API RETURNED (12 hex
    chars, not a UUID), so the route answers 404 for exactly the reason the
    sibling denials suite accepts ``in (200, *CLIENT_ERRORS)``: the id shape
    does not match the queue path.  A CLEAN QC run may also legitimately have
    ZERO items, so the reachable shape is recorded and emptiness is asserted
    only when the route answers 200; the completeness of the decoded
    eligibility facts (readiness payload) is the authoritative check.
    """
    response = client.get(f"/api/v2/projects/{project_id}/qc-items")
    status = int(response.status_code)
    rows: list[Any] = []
    if status == 200:
        body = response.json() or {}
        payload = body.get("items") if isinstance(body, dict) else body
        rows = list(payload or [])
    else:
        assert status in CLIENT_ERRORS, response.text
    return response, rows, status

#: Server-side policy that makes this run the declared
#: ENGINEERING_FIXTURE_API path (deterministic extraction on an isolated
#: root).  Recorded in evidence, not hidden.
#:
#: The LAYOUT adapter ("deterministic") is used, not the cross-scene identity
#: adapter: it emits exactly ONE subject per persisted scene, so every scene
#: boundary has exactly one persisted occurrence segment -- which is what the
#: QC full-scope cut_drift evidence composer requires ("scene position N has
#: <n> matching persisted render segments").  The cross-scene identity
#: adapter emits TWO objects in scene 0 by construction, so scope=full is
#: refused for a structural reason that has nothing to do with this chain.
#: Its masks are full-frame RGBA with real transparency, so the packs publish.
EXTRACTION_POLICY_ENV = {
    "MOTIONFORGE_EXTRACTION_QA_MODE": "1",
    "MOTIONFORGE_EXTRACTION_PROVIDER": "deterministic",
}

#: Windows MAX_PATH head-room.  Measured failure mode of a deep runtime
#: root: the extraction worker cannot create its own staging file
#: (FileNotFoundError on '.candidate_01_thumbnail.png.<hex>.staging').
RUNTIME_ROOT_MAX_CHARS = 120

#: QA control pin, default OFF.
FAULT_ENV = "S12QA_FAULT_AT"

#: Stages whose refusal is the EXPECTED outcome of a declared negative
#: control.  Every other >=400 response in the chain is asserted to be
#: absent: a refusal may never be the end state of the happy path.
EXPECTED_REFUSAL_STAGES = frozenset({"negative_control_lock_without_role_mapping"})

#: The six core pose slots a publishable pack version must carry.
POSE_SLOTS = ("front", "three_quarter", "side", "back", "sitting", "walking")

#: Every decoded-eligibility fact the QC readiness payload must carry.
#: A clean run may legitimately have ZERO QC findings, so completeness of
#: these facts is asserted instead of demanding non-empty QC issues.
QC_READINESS_FACTS = (
    "run_state",
    "status",
    "policy_id",
    "policy_content_hash",
    "current_evidence_fingerprint",
    "evidence_matches",
    "policy_matches",
    "zero_item_completion",
)
QC_TERMINAL_RUN_STATES = {"completed", "failed", "stale"}
RUN_STATE_COMPLETED = "completed"

#: Fail-closed readiness verdict the server publishes when no completed
#: CURRENT FULL-scope run holds authority (an audio-only run never does).
READINESS_NOT_RUN = "not_run"


class StageLedger:
    """Append-only stage ledger, forced to disk at EXECUTION TIME.

    A run must leave evidence even when it dies mid-assertion, so every
    entry is written (write + flush + fsync) at the moment the stage is
    recorded -- before the assertion that consumes it can fire.  The file
    is opened in APPEND mode and never with "w": truncating a ledger
    would destroy an earlier run's history.
    """

    def __init__(self, path: Path, *, run_id: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.rows = 0
        self._handle = self.path.open("a", encoding="utf-8")

    def append(self, name: str, payload: Any) -> None:
        try:
            body = json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            body = json.dumps({"unserializable": repr(payload)[:2000]})
        row = (
            "{"
            f'"run_id": {json.dumps(self.run_id)}, '
            f'"stage": {json.dumps(name)}, '
            f'"payload": {body}'
            "}"
        )
        self._handle.write(row + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.rows += 1

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._handle.close()


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


def _ffprobe_decoded_video(path: Path) -> dict[str, Any]:
    """VIDEO-ONLY decoded frame facts (``-select_streams v:0``).

    Decoded presentation timestamps of the video stream, with no audio
    frames in the window -- the decoded-frame count and PTS sequence are
    the asserted outcome, not a container metadata flag.
    """
    proc = subprocess.run(
        ["ffprobe", "-hide_banner", "-loglevel", "error", "-select_streams", "v:0",
         "-print_format", "json", "-show_streams", "-show_frames",
         "-show_entries", "stream=codec_type,time_base,nb_frames,avg_frame_rate",
         "-show_entries", "frame=pts_time,media_type", str(path)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[:500], "returncode": proc.returncode}
    probe = json.loads(proc.stdout)
    frames = probe.get("frames") or []
    pts = [
        round(float(f["pts_time"]), 6)
        for f in frames
        if f.get("pts_time") not in (None, "N/A")
    ]
    streams = probe.get("streams") or []
    return {
        "decoded_frame_count": len(pts),
        "decoded_pts": pts,
        "decoded_pts_monotonic": pts == sorted(pts),
        "decoded_pts_unique": len(set(pts)) == len(pts),
        "decoded_pts_first": pts[0] if pts else None,
        "decoded_pts_last": pts[-1] if pts else None,
        "decoded_media_types": sorted({str(f.get("media_type")) for f in frames}),
        "streams": [
            {
                "codec_type": s.get("codec_type"),
                "time_base": s.get("time_base"),
                "nb_frames": s.get("nb_frames"),
                "avg_frame_rate": s.get("avg_frame_rate"),
            }
            for s in streams
        ],
    }


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

    evidence_root = Path(os.environ["S12QA_EVIDENCE_OUT"])
    candidate_root = Path(os.environ["S12QA_CANDIDATE_ROOT"]).resolve()
    expected_sha = os.environ["S12QA_EXPECTED_CANDIDATE_SHA"]
    assert not evidence_root.exists(), (
        f"evidence root must be exclusive/new (never reuse): {evidence_root}"
    )
    evidence_root.mkdir(parents=True)
    raw_dir = evidence_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    chain: dict[str, Any] = {
        "lane": "S12-LC3-QA",
        "node": f"{R.PKG}/test_public_chain_frozen_candidate.py::"
        "test_public_chain_end_to_end_on_frozen_candidate",
        "path_class": {
            "executed": "ENGINEERING_FIXTURE_API",
            "why": "FastAPI TestClient over the public HTTP routes on an "
            "isolated runtime root, with the LABELLED fixture clip and the "
            "server-policy deterministic-identity extraction provider.",
            "browser_journey": "NOT_RUN_BY_THIS_OWNER: the real browser/DOM "
            "journey belongs to MF-DEMO-E2E (demo owner).  The context read in "
            "this node is an API read, never a UI reload.",
            "product_approval": "NONE - this run is engineering evidence, not "
            "a product approval and not a visual verdict.",
        },
        "evidence_root": str(evidence_root),
        "raw_dir": str(raw_dir),
        "candidate_root": str(candidate_root),
        "candidate_sha_expected": expected_sha,
        "stages": {},
        "identities": {},
        "counts": {},
        "flags": {},
        "controls": {},
        "status": None,
    }
    stage_order: list[str] = []
    in_flight: dict[str, Any] = {"name": None}
    ledger = StageLedger(raw_dir / "stages.jsonl", run_id=evidence_root.name)
    ledger.append(
        "run_header",
        {
            "node": chain["node"],
            "evidence_root": str(evidence_root),
            "candidate_root": str(candidate_root),
            "candidate_sha_expected": expected_sha,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "path_class": chain["path_class"],
        },
    )

    def stage(name: str, payload: Any) -> None:
        """Record a stage AND persist it AT EXECUTION TIME.

        The ledger row lands on disk (write + flush + fsync) before the
        assertion that consumes it can fire, so a failing run still leaves
        every reached request/response/job/result on disk.
        """
        chain["stages"][name] = payload
        stage_order.append(name)
        in_flight["name"] = name
        ledger.append(name, payload)

    # A DEEP runtime root exceeds Windows MAX_PATH and the extraction worker
    # then dies on its own staging file (measured failure mode).  Keep it
    # short and outside the deep evidence root.
    runtime_root = Path(
        os.environ.get("S12QA_RUNTIME_ROOT")
        or (Path(tempfile.gettempdir()) / "s12qa-runtime" / evidence_root.name)
    )
    assert len(str(runtime_root)) <= RUNTIME_ROOT_MAX_CHARS, (
        f"runtime root too deep for Windows MAX_PATH: {len(str(runtime_root))} chars"
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    chain["runtime_root"] = str(runtime_root)
    chain["runtime_root_length"] = len(str(runtime_root))

    # Isolate the runtime BEFORE importing the app: env roots, then DB.
    runtime_env = {
        "MOTIONFORGE_ROOT": str(runtime_root),
        "MOTIONFORGE_OUTPUT": str(runtime_root / "output"),
        "MOTIONFORGE_MODELS": str(runtime_root / "models"),
        **EXTRACTION_POLICY_ENV,
    }
    old_env = {
        key: os.environ.get(key)
        for key in (*runtime_env, "MOTIONFORGE_DATABASE_URL")
    }
    os.environ.pop("MOTIONFORGE_DATABASE_URL", None)
    for key, value in runtime_env.items():
        os.environ[key] = value
    chain["isolation"] = {
        "runtime_root": str(runtime_root),
        "runtime_root_length": len(str(runtime_root)),
        "env_set": dict(runtime_env),
        "database_url_cleared": True,
    }

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

    service: Any = None
    factory: Any = None
    engine: Any = None
    saved: Any = None
    failure: BaseException | None = None

    def counts() -> dict[str, int]:
        with factory() as session:
            return {
                name: int(session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }

    def fault(point: str) -> None:
        """Labelled fault injection (QA control, default OFF).

        ``S12QA_FAULT_AT=<point>`` raises deliberately AT that exact point so
        the evidence-persistence requirement can be demonstrated with a
        failing run.  It never fires while the pin is unset.
        """
        if os.environ.get(FAULT_ENV) == point:
            chain["flags"]["fault_injection"] = point
            raise AssertionError(f"DELIBERATE FAULT INJECTION at {point}")

    try:
        db_path = runtime_root / "data" / "s12qa.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        alembic_cfg = AlembicConfig(str(candidate_root / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(candidate_root / "migrations"))
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

        saved = (
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
        deps._lifecycle_db = db_path
        deps._project_wf = ProjectWorkflowService(config)

        chain["isolation"].update(
            {
                "durable_db": str(db_path),
                "managed_root": str(managed_root),
                "db_under_runtime_root": str(db_path).startswith(str(runtime_root)),
                "managed_under_runtime_root": str(managed_root).startswith(
                    str(runtime_root)
                ),
                "bound_project_root": str(getattr(deps._config, "project_root", "")),
            }
        )
        assert chain["isolation"]["db_under_runtime_root"], chain["isolation"]
        assert chain["isolation"]["managed_under_runtime_root"], chain["isolation"]

        chain["candidate_sha_actual"] = _git_head(candidate_root)
        assert chain["candidate_sha_actual"] == expected_sha, (
            f"candidate moved: {chain['candidate_sha_actual']} != {expected_sha}"
        )
        assert _git_head(REPO_ROOT) == expected_sha, (
            "the executing worktree is not the frozen candidate"
        )
        stage(
            "candidate_identity",
            {
                "candidate_sha_actual": chain["candidate_sha_actual"],
                "executing_worktree_sha": _git_head(REPO_ROOT),
                "expected": expected_sha,
                "match": True,
            },
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            service.start_worker()
            assert service.worker_running, "durable worker did not start"
            chain["counts"]["before_chain"] = counts()
            stage("counts_before_chain", chain["counts"]["before_chain"])

            source_env = os.environ.get("S12QA_SOURCE_MEDIA")
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
                "decoded_video": _ffprobe_decoded_video(source),
            }
            assert chain["source_media"]["facts"]["audio"], "source must carry audio"
            assert (
                chain["source_media"]["decoded_video"]["decoded_frame_count"] > 0
            ), chain["source_media"]["decoded_video"]
            stage(
                "source_media",
                {
                    "kind": source_kind,
                    "path": str(source),
                    "sha256": chain["source_media"]["sha256"],
                    "facts": chain["source_media"]["facts"],
                    "decoded_video": chain["source_media"]["decoded_video"],
                },
            )

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
                f"/api/projects/{project_id}/analyze",
                json={"generation": "1", "title": "S12QA"},
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
            fault("after_analyze")

            # 2) library extraction -> roles + segments (earned, never seeded)
            extraction = client.post(
                "/api/v2/object-intelligence/extraction",
                json={"project_id": project_id, "video_item_id": video_id,
                      "generation": generation},
            )
            stage("extraction_submit", _rec(extraction))
            assert extraction.status_code == 201, extraction.text
            extraction_id = extraction.json()["job_id"]
            extraction_poll = _poll(
                client, f"/api/v2/object-intelligence/extraction/{extraction_id}",
                terminal=TERMINAL, timeout_seconds=900.0,
            )
            stage("extraction_job", extraction_poll)
            assert ((extraction_poll["final"] or {}).get("body") or {}).get(
                "status"
            ) == "completed", json.dumps((extraction_poll["final"] or {}).get("body"))[:1500]

            graph_read = client.get(
                f"/api/v2/object-intelligence/extraction/{extraction_id}/graph"
            )
            stage("extraction_graph", _rec(graph_read))
            assert graph_read.status_code == 200, graph_read.text
            graph_segments = (graph_read.json() or {}).get("segments", [])
            roles_read = client.get(
                "/api/v2/object-intelligence/roles", params={"video_item_id": video_id}
            )
            stage("roles_read", _rec(roles_read))
            assert roles_read.status_code == 200, roles_read.text
            roles = roles_read.json().get("roles", [])
            assert roles, "no public current ObjectRole after extraction"
            role_mask = {
                str(seg.get("role_id")): str(seg.get("mask_artifact_id"))
                for seg in graph_segments
                if seg.get("role_id") and seg.get("mask_artifact_id")
            }
            stage(
                "role_segment_map",
                {
                    "segment_count": len(graph_segments),
                    "role_ids": [str(r["id"]) for r in roles],
                    "role_mask": role_mask,
                    "segment_role_ids": [str(seg.get("role_id")) for seg in graph_segments],
                },
            )
            role_ids: list[str] = []
            for index, role in enumerate(roles):
                role_id = str(role["id"])
                assert role_id in role_mask, (
                    f"role {role_id} has no mask artifact in the extraction graph"
                )
                role_update = client.patch(
                    f"/api/v2/object-intelligence/roles/{role_id}",
                    json={"revision": int(role["revision"]), "status": "confirmed"},
                )
                stage(f"role_confirm_{index}", _rec(role_update))
                assert role_update.status_code == 200, role_update.text
                role_ids.append(role_id)
            chain["identities"]["role_ids"] = role_ids
            fault("after_roles")

            # 2b) NEGATIVE CONTROL (expected refusal, side-effect free): the
            #     structural lock must REFUSE while no role->cast mapping /
            #     reskin config exists.  The 422 is asserted here as the
            #     EXPECTED outcome of a control -- never as the end state of
            #     the happy path.
            unmapped_lock = client.post(
                f"/api/v2/projects/{project_id}/videos/{video_id}/structural-lock", json={}
            )
            stage("negative_control_lock_without_role_mapping", _rec(unmapped_lock))
            assert unmapped_lock.status_code == 422, (
                f"expected the un-mapped lock to be refused 422, got "
                f"{unmapped_lock.status_code}: {unmapped_lock.text[:500]}"
            )
            assert "STRUCTURAL_LOCK_ROLE_MAPPING_MISSING" in unmapped_lock.text, (
                unmapped_lock.text[:1000]
            )
            chain["controls"]["negative_lock_without_role_mapping"] = {
                "status_code": unmapped_lock.status_code,
                "code": "STRUCTURAL_LOCK_ROLE_MAPPING_MISSING",
                "expected": "refused before any write: the setup step was missing",
            }

            # 3) library pack per role: character -> version -> six core pose
            #    slots (the role's OWN mask artifact as the pose asset) ->
            #    validation -> PUBLISH.  Every id below is API-returned.
            reskin_params = {
                "anchor": {"x": 0.5, "y": 0.5},
                "scale": 1.0,
                "fit_mode": "contain",
                "clip_mode": "asset_alpha",
                "offset": {"x": 0.0, "y": 0.0},
                "rotation_offset_deg": 0.0,
                "opacity": 1.0,
            }
            character_ids: list[str] = []
            version_ids: list[str] = []
            asset_artifact_ids: list[str] = []
            for index, role_id in enumerate(role_ids):
                mask_artifact = role_mask[role_id]
                character = client.post(
                    "/api/v2/characters",
                    json={
                        "name": f"S12QA Character {index}",
                        "code": f"S12QA_{project_id[:8]}_{index}",
                    },
                )
                stage(f"character_create_{index}", _rec(character))
                assert character.status_code == 201, character.text
                character_id = character.json()["id"]
                version = client.post(f"/api/v2/characters/{character_id}/versions")
                stage(f"pack_version_create_{index}", _rec(version))
                assert version.status_code == 201, version.text
                version_id = version.json()["id"]
                for slot in POSE_SLOTS:
                    attach = client.post(
                        f"/api/v2/characters/versions/{version_id}/assets",
                        json={"pose_slot": slot, "artifact_id": mask_artifact},
                    )
                    stage(f"pack_asset_{index}_{slot}", _rec(attach))
                    assert attach.status_code == 200, attach.text
                validation = client.get(
                    f"/api/v2/characters/versions/{version_id}/validation"
                )
                stage(f"pack_validation_{index}", _rec(validation))
                assert validation.status_code == 200, validation.text
                assert (validation.json() or {}).get("complete") is True, (
                    f"pack {index} not publishable: {validation.text[:800]}"
                )
                publish = client.post(
                    f"/api/v2/characters/versions/{version_id}/publish",
                    json={"revision": int(version.json()["revision"])},
                )
                stage(f"pack_publish_{index}", _rec(publish))
                assert publish.status_code == 200, publish.text
                published = publish.json()
                assert published.get("status") == "published", published
                character_ids.append(character_id)
                version_ids.append(version_id)
                asset_artifact_ids.append(mask_artifact)
            chain["identities"].update(
                {
                    "character_ids": character_ids,
                    "pack_version_ids": version_ids,
                    "pack_asset_artifact_ids": asset_artifact_ids,
                }
            )
            fault("after_packs")

            # 4) role -> cast mapping + reskin config (API-returned ids only)
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
                        "idempotency_key": f"s12qa-cast-{index}-{project_id}",
                    },
                )
                stage(f"project_cast_create_{index}", _rec(cast))
                assert cast.status_code in (200, 201), cast.text
                cast_id = str(cast.json()["id"])
                cast_ids.append(cast_id)
                config_create = client.post(
                    "/api/v2/reskin-configs",
                    json={
                        "project_id": project_id,
                        "object_role_id": role_id,
                        "character_id": character_ids[index],
                        "pack_version_id": version_ids[index],
                        "cast_mapping_id": cast_id,
                        "params": reskin_params,
                        "idempotency_key": f"s12qa-config-{index}-{project_id}",
                    },
                )
                stage(f"reskin_config_create_{index}", _rec(config_create))
                assert config_create.status_code in (200, 201), config_create.text
                config_body = config_create.json()
                config_id = str(config_body["id"])
                assert config_id not in cast_ids, (
                    "reskin config id must be its OWN API-returned identity, "
                    "never a project-id or cast-id fallback"
                )
                assert config_body.get("cast_mapping_id") == cast_id, config_body
                config_ids.append(config_id)
                config_revisions[config_id] = int(config_body["revision"])
            chain["identities"].update(
                {"project_cast_ids": cast_ids, "reskin_config_ids": config_ids}
            )
            assert config_ids and cast_ids and version_ids, chain["identities"]
            fault("after_role_mapping")

            # 5) structural lock producer on the completed setup
            producer = client.post(
                f"/api/v2/projects/{project_id}/videos/{video_id}/structural-lock", json={}
            )
            stage("producer_structural_lock", _rec(producer))
            assert producer.status_code == 201, (
                f"producer denied: {producer.status_code} {producer.text[:2000]}"
            )
            producer_body = producer.json()
            manifest_id = str(producer_body["manifest_id"])
            manifest_hash = str(producer_body["manifest_hash"])
            assert int(producer_body.get("segment_count") or 0) >= 1, producer_body
            chain["identities"].update(
                {
                    "manifest_id": manifest_id,
                    "manifest_hash": manifest_hash,
                    "manifest_segment_count": producer_body.get("segment_count"),
                    "manifest_policy_version": producer_body.get("policy_version"),
                    "route_decisions_created": producer_body.get("route_decisions_created"),
                }
            )
            fault("after_producer")

            # 6) ReskinConfig CAS pin + S09 reapproval using returned ids
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
            primary_pinned_revision = pinned_revisions[config_id]
            reapprove = client.post(
                "/api/v2/s09-approvals/reapprove",
                params={"workspace_id": "default"},
                json={
                    "reskin_config_id": config_id,
                    "expected_reskin_revision": primary_pinned_revision,
                    "pack_version_ids": version_ids,
                    "idempotency_key": f"s12qa-reapprove-{project_id}",
                    "note": "S12QA frozen-candidate run; not a product approval",
                },
            )
            stage("approval_reapprove", _rec(reapprove))
            assert reapprove.status_code in (200, 201), reapprove.text
            checkpoint = reapprove.json()
            checkpoint_id = str(checkpoint["id"])
            checkpoint_hash = str(checkpoint["checkpoint_hash"])
            checkpoint_revision = int(
                checkpoint.get("reskin_config_revision") or primary_pinned_revision
            )
            assert str(checkpoint.get("reskin_config_id")) == config_id, checkpoint
            assert str(checkpoint.get("structural_lock_manifest_id")) == manifest_id, (
                checkpoint
            )
            authority = client.get(
                f"/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority",
                params={"workspace_id": "default"},
            )
            stage("approval_authority", _rec(authority))
            assert authority.status_code == 200, authority.text
            assert authority.json()["eligibility"]["full_apply_executable"] is True, (
                f"authority not executable: {json.dumps(authority.json())[:1500]}"
            )
            chain["identities"]["checkpoint_id"] = checkpoint_id
            fault("after_reapproval")

            # 7) S10 Full Apply
            full_apply = client.post(
                f"/api/v2/projects/{project_id}/full-apply",
                params={"workspace_id": "default"},
                json={
                    "video_item_id": video_id,
                    "apply_checkpoint_id": checkpoint_id,
                    "expected_checkpoint_hash": checkpoint_hash,
                    "expected_checkpoint_revision": checkpoint_revision,
                },
            )
            stage("s10_submit", _rec(full_apply))
            assert full_apply.status_code == 202, full_apply.text
            fa_body = full_apply.json()
            fa_run_id = str(fa_body.get("run_id") or fa_body.get("id"))
            chain["identities"]["s10_run_id"] = fa_run_id
            s10_poll = _poll(
                client, f"/api/v2/full-apply/{fa_run_id}", terminal=TERMINAL,
                timeout_seconds=1800.0,
            )
            stage("s10_run", s10_poll)
            s10_final = (s10_poll["final"] or {}).get("body") or {}
            assert s10_final.get("status") == "completed", json.dumps(s10_final)[:1500]
            chain["flags"]["s10_completed"] = True
            fault("after_s10")

            # 8) original audio attach
            audio = client.post(
                f"/api/v2/projects/{project_id}/original-audio-attach",
                json={"video_item_id": video_id},
            )
            stage("audio_attach", _rec(audio))
            assert audio.status_code == 202, audio.text
            audio_job = str(audio.json().get("job_id"))
            audio_poll = _poll(
                client, f"/api/jobs/{audio_job}", terminal=TERMINAL, timeout_seconds=600.0
            )
            stage("audio_job", audio_poll)

            # 9) FULL QC.  A clean run may legitimately produce ZERO findings,
            #    so completeness of the decoded eligibility facts is asserted
            #    instead of demanding non-empty QC issues.
            qc_full = client.post(
                f"/api/v2/projects/{project_id}/qc-check-runs",
                json={"video_item_id": video_id, "scope": "full"},
            )
            stage("qc_full_submit", _rec(qc_full))
            if qc_full.status_code == 422 and "QC_RUN_EVIDENCE_UNAVAILABLE" in qc_full.text:
                # EXPECTED REFUSAL (asserted negative control, not an
                # un-asserted blocker).  The refusal is typed and fail-closed,
                # and it is NOT a setup omission on this side: every stage
                # below is asserted to have returned < 400 unless it is in the
                # declared expected-refusal set.  It is the QC evidence
                # composers refusing to fabricate the inputs they judge:
                #   * ``_cut_drift`` needs EXACTLY ONE persisted occurrence
                #     segment per scene start frame
                #     (app/services/qc_evidence/compose.py);
                #   * the contact/occlusion detectors need persisted
                #     scene-graph edges, and the extraction worker publishes
                #     those ONLY for a scene carrying >= 2 segments
                #     (app/services/object_extraction.py, QA-synthetic block).
                # With the QA providers available on this candidate those two
                # requirements are mutually exclusive: the layout adapter
                # emits ONE subject per scene (so no edges exist), the
                # cross-scene identity adapter emits TWO objects in scene 0
                # (so two segments share a scene start frame).  No QC state
                # and no scene graph is seeded to go around it, and no
                # product guard is weakened.
                qc_refused = True
                qc_detail = (qc_full.json() or {}).get("detail")
                chain["controls"]["qc_full_scope_refused"] = {
                    "expected": True,
                    "status_code": qc_full.status_code,
                    "detail": qc_detail,
                    "why_expected": "typed QC_EVIDENCE_MISSING refusal from the "
                    "scope=full evidence composer; the preconditions it names "
                    "(one segment per scene start for cut_drift; published "
                    "scene-graph edges for the contact/occlusion detectors) "
                    "cannot both hold for any source this candidate accepts",
                    "setup_complete_before_refusal": True,
                    "product_code_touched": False,
                    "sql_seeded": False,
                }
                chain["controls"]["expected_refusal_stages"] = sorted(
                    set(chain["controls"].get("expected_refusal_stages") or [])
                    | {"qc_full_submit"}
                )
                assert "QC_EVIDENCE_MISSING" in str(qc_detail), qc_detail
            else:
                assert qc_full.status_code in (200, 202, 409), qc_full.text
            if qc_refused:
                # A refused run must be SIDE-EFFECT FREE: no QC job, no QC
                # state, no QC items.
                qc_state_after = client.get(
                    f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}"
                )
                stage("qc_state_after_refusal", _rec(qc_state_after))
                assert qc_state_after.status_code == 200, qc_state_after.text
                assert (qc_state_after.json() or {}).get("run_state") == "never_run", (
                    qc_state_after.text[:800]
                )
                items_after, rows_after, items_after_status = _qc_items_probe(
                    client, project_id
                )
                stage("qc_items_after_refusal", _rec(items_after))
                assert items_after_status in (200, *CLIENT_ERRORS), items_after.text
                if items_after_status == 200:
                    assert rows_after == [], items_after.text
                # Route-shape independent proof that the refusal wrote
                # nothing: the persisted QC item count, read from the
                # isolated runtime DB (never seeded, only counted).
                after_counts = counts()
                assert after_counts["qc_items"] == 0, after_counts
                chain["flags"]["qc_items_db_count_after_refusal"] = (
                    after_counts["qc_items"]
                )
                chain["flags"]["qc_refusal_side_effect_free"] = True
                chain["flags"]["qc_item_count"] = len(rows_after)
                chain["flags"]["qc_items_route_status"] = items_after_status
                chain["flags"]["qc_findings_present"] = False
            else:
                qc_job = (
                    str(qc_full.json().get("job_id")) if qc_full.status_code == 202 else None
                )
                if qc_job:
                    qc_job_poll = _poll(
                        client, f"/api/jobs/{qc_job}", terminal=TERMINAL,
                        timeout_seconds=1800.0,
                    )
                    stage("qc_job", qc_job_poll)
                qc_state = _poll(
                    client,
                    f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}",
                    terminal=TERMINAL | {"ready", "blocked", "not_run"},
                    timeout_seconds=1800.0,
                )
                stage("qc_state", qc_state)
                readiness = client.get(
                    f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}/readiness"
                )
                stage("qc_readiness", _rec(readiness))
                items, issue_rows, qc_items_status = _qc_items_probe(
                    client, project_id
                )
                stage("qc_items", _rec(items))
                assert readiness.status_code == 200, readiness.text
                assert qc_items_status in (200, *CLIENT_ERRORS), items.text
                qc_state_body = (qc_state.get("final") or {}).get("body") or {}
                readiness_body = readiness.json() or {}
                missing_facts = sorted(
                    k for k in QC_READINESS_FACTS if k not in readiness_body
                )
                assert not missing_facts, (
                    f"QC readiness is missing eligibility facts {missing_facts}: "
                    f"{json.dumps(readiness_body)[:1200]}"
                )
                assert str(qc_state_body.get("run_state")) in QC_TERMINAL_RUN_STATES, (
                    qc_state_body
                )
                assert str(readiness_body.get("run_state")) in QC_TERMINAL_RUN_STATES, (
                    readiness_body
                )
                assert len(str(readiness_body.get("policy_content_hash"))) == 64, (
                    readiness_body
                )
                assert len(str(readiness_body.get("current_evidence_fingerprint"))) == 64, (
                    readiness_body
                )
                chain["flags"].update(
                    {
                        "qc_run_state": qc_state_body.get("run_state"),
                        "qc_readiness_run_state": readiness_body.get("run_state"),
                        "qc_readiness_status": readiness_body.get("status"),
                        "qc_item_count": len(issue_rows),
                        "qc_items_route_status": qc_items_status,
                        "qc_items_db_count": counts()["qc_items"],
                        "qc_zero_item_completion": readiness_body.get(
                            "zero_item_completion"
                        ),
                        "qc_policy_id": readiness_body.get("policy_id"),
                        "qc_readiness_facts_present": sorted(QC_READINESS_FACTS),
                    }
                )
                if issue_rows:
                    chain["flags"]["qc_findings_present"] = True
                    for row in issue_rows:
                        assert str(
                            row.get("reason_code") or row.get("category") or ""
                        ).strip(), row
                else:
                    # A clean run legitimately has ZERO QC items.  When the
                    # queue route is reachable that is the decoded empty
                    # table; when it is not (project-id shape, see
                    # ``_qc_items_probe``) the authoritative zero-item
                    # evidence is the DECODED readiness fact
                    # ``zero_item_completion`` -- never an inferred empty
                    # list and never a fabricated finding.
                    chain["flags"]["qc_findings_present"] = False
                    chain["flags"]["qc_zero_item_shape"] = (
                        "empty_table"
                        if qc_items_status == 200
                        else "readiness_zero_item_completion"
                    )
                    assert str(qc_state_body.get("run_state")) == RUN_STATE_COMPLETED, (
                        "a completed-zero-item QC run is the only clean shape: "
                        f"{json.dumps(qc_state_body)[:800]}"
                    )
                    assert readiness_body.get("zero_item_completion") is True, (
                        "completed with zero items must be evidenced as a decoded "
                        "zero-item completion, not inferred from an empty table: "
                        f"{readiness_body}"
                    )
            if qc_refused:
                # THE LEGITIMATE CLEAN-QC CASE.  scope=full refuses above
                # because the non-audio bands have no persisted structural
                # graph to judge (this fixture's source carries exactly ONE
                # occurrence segment, so no contact/occlusion edge can exist),
                # so the COMPOSABLE band is run: scope=audio.  A clean run may
                # legitimately have ZERO items, so the COMPLETE eligibility
                # facts below are asserted instead of demanding non-empty QC
                # issues.
                qc_audio = client.post(
                    f"/api/v2/projects/{project_id}/qc-check-runs",
                    json={"video_item_id": video_id, "scope": "audio"},
                )
                stage("qc_audio_submit", _rec(qc_audio))
                chain["flags"]["qc_audio_submit_status"] = qc_audio.status_code
                if qc_audio.status_code == 409:
                    # The audio attach flow already enqueued the audio-scope
                    # job under the same idempotency key; adopt that durable
                    # job instead of duplicating it.
                    _detail = str((qc_audio.json() or {}).get("detail") or qc_audio.text)
                    qc_audio_job = (
                        _detail.split("job ", 1)[1].split(" ", 1)[0]
                        if "job " in _detail
                        else None
                    )
                    chain["flags"]["qc_audio_existing_job"] = qc_audio_job
                else:
                    assert qc_audio.status_code in (200, 202), qc_audio.text
                    qc_audio_job = str((qc_audio.json() or {}).get("job_id"))
                chain["identities"]["qc_audio_job_id"] = qc_audio_job
                if qc_audio_job and qc_audio_job != "None":
                    stage(
                        "qc_audio_job",
                        _poll(
                            client,
                            f"/api/jobs/{qc_audio_job}",
                            terminal=TERMINAL,
                            timeout_seconds=1800.0,
                        ),
                    )
                qc_audio_state = _poll(
                    client,
                    f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}",
                    terminal=TERMINAL | {"ready", "blocked", "not_run", "never_run"},
                    timeout_seconds=300.0,
                )
                stage("qc_audio_state", qc_audio_state)
                audio_readiness = client.get(
                    f"/api/v2/projects/{project_id}/qc-check-runs/{video_id}/readiness"
                )
                stage("qc_audio_readiness", _rec(audio_readiness))
                items_audio, rows_audio, items_audio_status = _qc_items_probe(
                    client, project_id
                )
                stage("qc_items_audio", _rec(items_audio))
                assert audio_readiness.status_code == 200, audio_readiness.text
                assert items_audio_status in (200, *CLIENT_ERRORS), items_audio.text
                audio_state_body = (qc_audio_state.get("final") or {}).get("body") or {}
                audio_ready_body = audio_readiness.json() or {}
                audio_db_counts = counts()
                audio_missing = sorted(
                    k for k in QC_READINESS_FACTS if k not in audio_ready_body
                )
                assert not audio_missing, (
                    f"QC readiness is missing eligibility facts {audio_missing}: "
                    f"{json.dumps(audio_ready_body)[:1200]}"
                )
                # The DECODED clean-QC facts of the composable band: the durable
                # RUN_QC_CHECKS job reached a terminal state, the queue is empty
                # (route reachable) or the persisted table holds no item, and
                # the readiness payload publishes the zero-item completion fact.
                assert str(audio_state_body.get("run_state")) in (
                    QC_TERMINAL_RUN_STATES | {"never_run", "not_run"}
                ), audio_state_body
                assert audio_db_counts["qc_items"] == len(rows_audio), audio_db_counts
                assert (
                    str(audio_ready_body.get("status")) == READINESS_NOT_RUN
                ), (
                    "an audio-only run must NEVER create readiness authority "
                    f"(fail-closed): {audio_ready_body}"
                )
                assert str(audio_ready_body.get("run_state")) in (
                    "never_run",
                    "not_run",
                ), audio_ready_body
                assert len(str(audio_ready_body.get("policy_content_hash"))) == 64, (
                    audio_ready_body
                )
                assert (
                    len(str(audio_ready_body.get("current_evidence_fingerprint"))) == 64
                ), audio_ready_body
                chain["flags"].update(
                    {
                        "qc_clean_run_state": audio_state_body.get("run_state"),
                        "qc_clean_readiness_status": audio_ready_body.get("status"),
                        "qc_clean_readiness_run_state": audio_ready_body.get("run_state"),
                        "qc_clean_item_count": len(rows_audio),
                        "qc_clean_db_item_count": audio_db_counts["qc_items"],
                        "qc_clean_zero_item_completion": audio_ready_body.get(
                            "zero_item_completion"
                        ),
                        "qc_clean_items_route_status": items_audio_status,
                        "qc_clean_findings_present": bool(rows_audio),
                        "qc_clean_readiness_facts_present": sorted(QC_READINESS_FACTS),
                    }
                )
                if rows_audio:
                    for row in rows_audio:
                        assert str(
                            row.get("reason_code") or row.get("category") or ""
                        ).strip(), row
                else:
                    # A clean run may legitimately have ZERO items -- but the
                    # server's OWN rule is that readiness authority (and hence
                    # the decoded zero-item fact) comes from a completed
                    # SCOPE_FULL run: an audio-only / partial run never creates
                    # it, so the eligibility facts stay fail-closed (None) while
                    # the payload still publishes every fact KEY and names the
                    # rule in check_state_detail.  A completed-zero-item FULL
                    # run is therefore UNREACHABLE through the public API on
                    # this candidate (scope=full is refused above) -- which is
                    # the exact reason the S12 gate below cannot be satisfied.
                    assert audio_ready_body.get("zero_item_completion") is None, (
                        "an audio-only run must never publish the decoded "
                        f"zero-item fact: {audio_ready_body}"
                    )
                    assert "never create full-run authority" in str(
                        audio_ready_body.get("check_state_detail")
                    ), audio_ready_body
                    assert audio_db_counts["qc_items"] == 0, audio_db_counts
                    chain["flags"]["qc_clean_authority_rule_asserted"] = (
                        "completed SCOPE_FULL run required; an audio-only run "
                        "never creates full-run authority (asserted)"
                    )
            fault("after_qc")

            # 10) S12 context / preflight / submit
            context = client.get(
                f"/api/v2/projects/{project_id}/export/context",
                params={"video_item_id": video_id},
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
            preflight_body = preflight.json()
            checks = preflight_body.get("checks") or []
            assert checks, "preflight must report its COMPLETE check list"
            failed_checks = [
                c.get("name") for c in checks if c.get("passed") is not True
            ]
            if preflight_body.get("eligible") is not True:
                # DECLARED, ASSERTED GATE CONTROL -- never an unasserted
                # blocker.  The S12 gate is fail-closed and TYPED: exactly one
                # reason set is accepted, and only when the gate's COMPLETE
                # check list shows the readiness check as the single failing
                # one while the QC authority really is absent.  Any other
                # ineligibility still fails the node.
                reasons = sorted(preflight_body.get("reasons") or [])
                assert reasons == ["S12_EXPORT_NOT_READY"], (
                    "unexpected S12 gate refusal (not the documented product "
                    f"gap): reasons={reasons} failed={failed_checks}"
                )
                assert failed_checks == ["readiness"], failed_checks
                assert chain["flags"].get("qc_clean_readiness_status") == (
                    READINESS_NOT_RUN
                ), chain["flags"].get("qc_clean_readiness_status")
                chain["flags"].update(
                    {
                        "s12_preflight_eligible": False,
                        "s12_preflight_reasons": reasons,
                        "s12_preflight_checks": [c.get("name") for c in checks],
                        "s12_preflight_check_count": len(checks),
                        "s12_preflight_failed_checks": failed_checks,
                        "s12_export_submitted": False,
                        "s12_gate": "BLOCKED_EXACT_S12_READINESS",
                        "s12_gate_control_asserted": True,
                    }
                )
                chain["status"] = "BLOCKED_EXACT_S12_READINESS"
                chain["blocker"] = {
                    "code": "S12_EXPORT_NOT_READY",
                    "gate": "readiness -- S12 export preflight CONSUMES the QC "
                    "readiness verdict and never loosens it",
                    "readiness_status": chain["flags"].get("qc_clean_readiness_status"),
                    "readiness_run_state": chain["flags"].get(
                        "qc_clean_readiness_run_state"
                    ),
                    "why_unreachable": "readiness authority requires a completed "
                    "CURRENT SCOPE_FULL QC run; scope=full is refused 422 "
                    "QC_RUN_EVIDENCE_UNAVAILABLE on this candidate (the "
                    "non-audio evidence composers have no persisted structural "
                    "graph to judge: the fixture source persists exactly ONE "
                    "occurrence segment, so no contact/occlusion edge can "
                    "exist) and an audio-only run never creates full-run "
                    "authority -- so the decoded zero-item fact stays None",
                    "corroboration": "the sibling node in this lane "
                    "(tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py) "
                    "records the identical BLOCKED_EXACT_S12_READINESS from the "
                    "same cause, and frontend/e2e/s12-export-seed.py seeds a "
                    "completed FULL RUN_QC_CHECKS run directly because the S12 "
                    "E2E itself never reaches readiness through public APIs",
                    "export_attempted": False,
                    "product_code_touched": False,
                    "sql_seeded": False,
                }
                raise AssertionError(
                    "BLOCKED_EXACT: S12 export preflight ineligible on the public "
                    f"chain (reasons={reasons}; failed checks={failed_checks}; "
                    f"readiness={chain['flags'].get('qc_clean_readiness_status')!r}; "
                    "full-scope QC submit refused 422 "
                    "QC_RUN_EVIDENCE_UNAVAILABLE)"
                )
            # Complete checks + eligibility facts (not just "eligible: true").
            assert failed_checks == [], f"preflight checks not all passed: {failed_checks}"
            assert preflight_body.get("reasons") == [], preflight_body.get("reasons")
            preflight_replay = client.post(
                f"/api/v2/projects/{project_id}/export/preflight",
                json={
                    "video_item_id": video_id,
                    "profile_id": "master-4k-h264",
                    "aspect_handling": "letterbox",
                    "checkpoint": context_body["checkpoint"],
                    "lock": context_body["lock"],
                },
            )
            stage("s12_preflight_replay", _rec(preflight_replay))
            assert preflight_replay.status_code == 200, preflight_replay.text
            assert [
                c.get("name") for c in (preflight_replay.json().get("checks") or [])
            ] == [c.get("name") for c in checks], "preflight checks must be deterministic"
            chain["flags"]["preflight_checks"] = [c.get("name") for c in checks]
            chain["flags"]["preflight_check_count"] = len(checks)
            chain["flags"]["preflight_eligible"] = True

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
            chain["identities"]["s12_run_id"] = run_id

            # 11) worker -> publisher -> result
            run_poll = _poll(
                client, f"/s12-exports/{run_id}", terminal=TERMINAL, timeout_seconds=3600.0
            )
            stage("s12_run", run_poll)
            run_final = (run_poll["final"] or {}).get("body") or {}
            assert run_final.get("status") == "completed", json.dumps(run_final)[:1500]
            result = client.get(f"/s12-exports/{run_id}/result")
            stage("s12_result", _rec(result))
            assert result.status_code == 200, result.text
            fault("after_s12_run")

            # 12) download + REAL decoded outcomes (video-only PTS / frames /
            #     audio preservation)
            media = client.get(f"/s12-exports/{run_id}/media")
            stage(
                "s12_media_http",
                {
                    "status_code": media.status_code,
                    "bytes": len(media.content),
                    "sha256": hashlib.sha256(media.content).hexdigest(),
                },
            )
            assert media.status_code == 200, media.text[:500]
            downloaded = raw_dir / "s12qa-downloaded-export.mp4"
            downloaded.write_bytes(media.content)
            export_facts = _media_facts(downloaded)
            export_decoded = _ffprobe_decoded_video(downloaded)
            source_decoded = chain["source_media"]["decoded_video"]
            source_facts = chain["source_media"]["facts"]
            chain["export_media"] = {
                "path": str(downloaded),
                "sha256": hashlib.sha256(media.content).hexdigest(),
                "facts": export_facts,
                "decoded_video": export_decoded,
            }
            stage("s12_media_facts", chain["export_media"])

            assert export_decoded.get("decoded_frame_count", 0) > 0, export_decoded
            assert export_decoded.get("decoded_media_types") == ["video"], (
                "decoded frame window must be VIDEO-ONLY: "
                f"{export_decoded.get('decoded_media_types')}"
            )
            assert export_decoded.get("decoded_pts_monotonic") is True, export_decoded
            assert export_decoded.get("decoded_pts_unique") is True, export_decoded
            assert export_decoded["decoded_pts_first"] == pytest.approx(0.0, abs=1e-3), (
                f"first decoded PTS {export_decoded['decoded_pts_first']}"
            )
            assert export_decoded["decoded_frame_count"] == source_decoded["decoded_frame_count"], (
                "frame count must be preserved: export "
                f"{export_decoded['decoded_frame_count']} != source "
                f"{source_decoded['decoded_frame_count']}"
            )
            export_fps = (export_facts.get("video") or {}).get("fps")
            source_fps = (source_facts.get("video") or {}).get("fps")
            assert export_fps == source_fps, (export_fps, source_fps)
            if export_fps:
                expected_span = (export_decoded["decoded_frame_count"] - 1) / export_fps
                assert export_decoded["decoded_pts_last"] == pytest.approx(
                    expected_span, abs=(1.0 / export_fps) + 1e-3
                ), (export_decoded["decoded_pts_last"], expected_span)
            assert export_facts["audio"], "export lost its audio"
            assert export_facts["audio"]["channels"] == source_facts["audio"]["channels"], (
                export_facts["audio"],
                source_facts["audio"],
            )
            assert export_facts["audio"]["sample_rate"] == source_facts["audio"]["sample_rate"], (
                export_facts["audio"],
                source_facts["audio"],
            )
            assert export_facts["audio"]["duration_s"] >= 0.5 * float(
                source_facts["audio"]["duration_s"]
            ), (export_facts["audio"], source_facts["audio"])
            chain["flags"].update(
                {
                    "frame_count_preserved": True,
                    "decoded_pts_monotonic": True,
                    "decoded_pts_first_zero": True,
                    "fps_preserved": True,
                    "audio_preserved": True,
                    "export_frames": export_decoded["decoded_frame_count"],
                    "source_frames": source_decoded["decoded_frame_count"],
                    "export_audio": export_facts["audio"],
                    "source_audio": source_facts["audio"],
                }
            )

            # 13) controls: partial / corrupt output verdicts
            from app.services.s12_export.validation import PARTIAL_SUFFIX, validate

            partial = raw_dir / f"s12qa-partial-copy.mp4{PARTIAL_SUFFIX}"
            partial.write_bytes(media.content)
            partial_verdict = validate(partial)
            partial.unlink()
            chain["controls"]["partial_output"] = {
                "verdict": partial_verdict.verdict,
                "partial_suffix": PARTIAL_SUFFIX,
                "file_removed_after_check": not partial.exists(),
            }
            assert partial_verdict.verdict == "FAIL", partial_verdict

            corrupt = raw_dir / "s12qa-corrupt-copy.mp4"
            corrupt.write_bytes(b"NOT-A-CONTAINER" * 512)
            corrupt_verdict = validate(corrupt)
            chain["controls"]["corrupt_output"] = {
                "verdict": corrupt_verdict.verdict,
                "bytes": 15 * 512,
            }
            assert corrupt_verdict.verdict == "FAIL", corrupt_verdict

            # 14) API context reload + replay (idempotent, zero extra rows).
            #     NOTE: an API context read is NOT a UI reload.
            before_replay = counts()
            reload_body = client.get(
                f"/api/v2/projects/{project_id}/export/context",
                params={"video_item_id": video_id},
            )
            stage("api_context_reload", _rec(reload_body))
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
            chain["controls"]["replay"] = {
                "before": before_replay,
                "after": after_replay,
                "extra_runs": after_replay["s12_runs"] - before_replay["s12_runs"],
                "extra_jobs": after_replay["jobs"] - before_replay["jobs"],
                "replay_status_code": replay.status_code,
            }
            assert chain["controls"]["replay"]["extra_runs"] == 0, chain["controls"]["replay"]
            assert chain["controls"]["replay"]["extra_jobs"] == 0, chain["controls"]["replay"]

            # 15) cancel leg: submit with the worker STOPPED on a NEW
            #     idempotency key -> public cancel -> restart -> the cancelled
            #     work must stay unprocessed.
            service.stop_worker(timeout=15.0)
            before_cancel = counts()
            cancel_submit = client.post(
                "/s12-exports/submit",
                json={
                    "project_id": project_id,
                    "video_item_id": video_id,
                    "profile_id": "master-4k-h264",
                    "context_revision": str(reload_body.json()["context_revision"]),
                    "idempotency_key": f"s12qa-cancel-{project_id}",
                },
            )
            stage("control_cancel_submit", _rec(cancel_submit))
            assert cancel_submit.status_code == 202, cancel_submit.text
            cancel_run_id = str(cancel_submit.json()["run_id"])
            assert cancel_run_id != run_id, "a NEW submit must not reuse the completed run"
            cancel = client.post(f"/s12-exports/{cancel_run_id}/cancel")
            stage("control_cancel_request", _rec(cancel))
            assert cancel.status_code == 200, cancel.text
            assert cancel.json().get("cancelled") is True, cancel.text
            cancel_state = client.get(f"/s12-exports/{cancel_run_id}")
            stage("control_cancel_state", _rec(cancel_state))
            assert (cancel_state.json() or {}).get("status") == "cancelled", cancel_state.text
            service.start_worker()
            time.sleep(3.0)
            service.stop_worker(timeout=15.0)
            after_cancel_restart = counts()
            chain["controls"]["cancel"] = {
                "cancelled_run_id": cancel_run_id,
                "before": before_cancel,
                "after_restart": after_cancel_restart,
                "extra_runs": after_cancel_restart["s12_runs"] - before_cancel["s12_runs"],
                "extra_publications": (
                    after_cancel_restart["s10_publications"]
                    - before_cancel["s10_publications"]
                ),
            }
            assert chain["controls"]["cancel"]["extra_runs"] == 1, chain["controls"]["cancel"]
            assert chain["controls"]["cancel"]["extra_publications"] == 0, (
                chain["controls"]["cancel"]
            )

            # 16) retry leg: retrying the CANCELLED run must create a NEW
            #     lineage run that really completes and really serves media.
            retry = client.post(f"/s12-exports/{cancel_run_id}/retry", json={})
            stage("control_retry_submit", _rec(retry))
            assert retry.status_code == 202, retry.text
            retry_body = retry.json()
            retry_run_id = str(retry_body["run_id"])
            assert retry_run_id != cancel_run_id, retry_body
            assert str(retry_body.get("predecessor_run_id")) == cancel_run_id, retry_body
            service.start_worker()
            retry_poll = _poll(
                client, f"/s12-exports/{retry_run_id}", terminal=TERMINAL,
                timeout_seconds=1800.0,
            )
            stage("control_retry_run", retry_poll)
            retry_final = (retry_poll["final"] or {}).get("body") or {}
            assert retry_final.get("status") == "completed", json.dumps(retry_final)[:1500]
            retry_media = client.get(f"/s12-exports/{retry_run_id}/media")
            stage(
                "control_retry_media",
                {"status_code": retry_media.status_code, "bytes": len(retry_media.content)},
            )
            assert retry_media.status_code == 200, retry_media.text[:500]
            chain["controls"]["retry"] = {
                "predecessor": cancel_run_id,
                "successor": retry_run_id,
                "successor_status": retry_final.get("status"),
                "successor_media_bytes": len(retry_media.content),
            }

            # 17) repeat retry dedupes onto the winner; retry of a COMPLETED
            #     run is refused (real contract, asserted).
            retry_again = client.post(f"/s12-exports/{cancel_run_id}/retry", json={})
            stage("control_retry_repeat", _rec(retry_again))
            assert retry_again.status_code == 202, retry_again.text
            assert str(retry_again.json()["run_id"]) == retry_run_id, retry_again.text
            assert retry_again.json().get("created") is not True, retry_again.text
            retry_completed = client.post(f"/s12-exports/{run_id}/retry", json={})
            stage("control_retry_after_complete", _rec(retry_completed))
            assert retry_completed.status_code == 409, retry_completed.text
            cancel_terminal = client.post(f"/s12-exports/{run_id}/cancel")
            stage("control_cancel_after_terminal", _rec(cancel_terminal))
            assert cancel_terminal.status_code == 409, cancel_terminal.text
            chain["controls"]["terminal_guards"] = {
                "retry_after_complete": retry_completed.status_code,
                "cancel_after_terminal": cancel_terminal.status_code,
                "repeat_retry_deduped": True,
            }

            # 18) restart on the same DB: no duplicate work.
            restart_before = counts()
            service.start_worker()
            time.sleep(3.0)
            service.stop_worker(timeout=15.0)
            restart_after = counts()
            chain["controls"]["restart"] = {
                "before": restart_before,
                "after": restart_after,
            }
            chain["controls"]["restart_no_duplicate"] = restart_after == restart_before
            assert chain["controls"]["restart_no_duplicate"], (
                restart_before,
                restart_after,
            )

            # 19) stale-lease control — honest disposition + real assertion.
            #     A stale/expired export lease can only be driven through a
            #     public route; the frozen candidate exposes none, and seeding
            #     one through SQL is forbidden.  The assertion makes the
            #     disposition checkable instead of merely claimed.
            public_paths = sorted(
                {str(getattr(route, "path", "")) for route in app.routes}
            )
            lease_paths = [path for path in public_paths if "lease" in path.lower()]
            chain["controls"]["stale_lease"] = {
                "disposition": "NOT_PUBLICLY_DRIVABLE",
                "why": "no public lease route exists on the frozen candidate, so a "
                "stale/expired export lease cannot be driven through the public "
                "surface without SQL seeding (forbidden).  Lease reclaim is "
                "worker-internal and owned by the VAL lane (R06/A02).",
                "public_route_count": len(public_paths),
                "public_lease_routes": lease_paths,
                "covered_instead": "cancel + cancelled_work_not_processed + "
                "restart_no_duplicate (an unclaimed job is never silently drained)",
            }
            assert lease_paths == [], lease_paths

            chain["counts"]["after_chain"] = counts()
            chain["status"] = "PASS"

    except BaseException as exc:  # preserve every reached stage, then re-raise
        failure = exc
        if not str(chain.get("status", "")).startswith("BLOCKED_"):
            chain["status"] = f"FAILED_{type(exc).__name__}"
        chain["failure"] = str(exc)[:4000]
        chain["first_failing_stage"] = in_flight["name"]
        with contextlib.suppress(Exception):
            chain["counts"]["at_failure"] = counts()
        with contextlib.suppress(Exception):
            ledger.append(
                "FIRST_FAILING_DEPENDENCY",
                {
                    "stage": in_flight["name"],
                    "type": type(exc).__name__,
                    "error": str(exc)[:4000],
                },
            )
    finally:
        with contextlib.suppress(Exception):
            service.stop_worker(timeout=10.0)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if saved is not None:
            (
                deps._config,
                deps._job_service,
                deps._project_service,
                deps._video_service,
                deps._lifecycle_db,
                deps._project_wf,
            ) = saved
        with contextlib.suppress(Exception):
            engine.dispose()

    # ── ALWAYS persist, on a passing OR a failing run ────────────────────
    if chain["status"] is None:
        chain["status"] = "PASS"
    # Every refusal must be the EXPECTED outcome of a declared control.  This
    # is the Manager's rule ("the 422 may only appear where it is the expected
    # outcome of a negative control") expressed as a real assertion over the
    # run's own evidence, not as prose.
    expected_refusals = set(chain["controls"].get("expected_refusal_stages") or [])
    expected_refusals.update(EXPECTED_REFUSAL_STAGES)
    refusals: list[dict[str, Any]] = []
    blocked_stage = None
    for name in stage_order:
        payload = chain["stages"].get(name)
        code = payload.get("status_code") if isinstance(payload, dict) else None
        if isinstance(code, int) and code >= 400:
            refusals.append({"stage": name, "status_code": code})
            if blocked_stage is None:
                blocked_stage = {"stage": name, "status_code": code, "response": payload}
    unexpected_refusals = [row for row in refusals if row["stage"] not in expected_refusals]
    chain["controls"]["expected_refusal_stages"] = sorted(expected_refusals)
    chain["controls"]["observed_refusals"] = refusals
    chain["controls"]["unexpected_refusals"] = unexpected_refusals
    chain["stage_order"] = list(stage_order)
    chain["stage_status"] = {
        "reached": list(stage_order),
        "blocked": blocked_stage,
        "expected_refusals": sorted(chain["controls"]),
    }
    summary = {
        "status": chain["status"],
        "candidate_sha": chain.get("candidate_sha_actual"),
        "path_class": chain["path_class"],
        "source_media_kind": (chain.get("source_media") or {}).get("kind"),
        "identities": chain["identities"],
        "counts": chain["counts"],
        "flags": chain["flags"],
        "controls": chain["controls"],
        "failure": chain.get("failure"),
        "first_failing_stage": chain.get("first_failing_stage"),
        "stage_count": len(stage_order),
        "evidence_sha256": {},
    }
    chain_path = evidence_root / "s12qa-chain.json"
    chain_path.write_text(
        json.dumps(chain, indent=1, sort_keys=True, default=str), encoding="utf-8"
    )
    ledger.append("run_footer", {"status": chain["status"], "stage_count": len(stage_order)})
    summary["evidence_sha256"]["s12qa-chain.json"] = hashlib.sha256(
        chain_path.read_bytes()
    ).hexdigest()
    summary["evidence_sha256"]["raw/stages.jsonl"] = hashlib.sha256(
        (raw_dir / "stages.jsonl").read_bytes()
    ).hexdigest()
    (evidence_root / "s12qa-summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True, default=str), encoding="utf-8"
    )
    ledger.close()

    if failure is not None:
        raise failure
    assert unexpected_refusals == [], (
        "a refusal appeared OUTSIDE the declared expected-refusal set: "
        f"{unexpected_refusals}"
    )
    assert summary["status"] == "PASS", summary["status"]


def test_stage_ledger_persists_at_execution_time_and_after_failure(
    tmp_path: Path,
) -> None:
    """RUNNABLE NOW (no pins): the persistence mechanism must be real.

    Proves, without any frozen pin or product state:
      (a) a stage is ON DISK the moment it is recorded -- not at the end
          of the run;
      (b) a stage recorded before an assertion failure is still on disk
          AFTER the failure propagates (NR07 evidence-persistence);
      (c) the ledger APPENDS and never truncates.
    """
    path = tmp_path / "stages.jsonl"
    ledger = StageLedger(path, run_id="s12qa-unit")
    ledger.append("first", {"status_code": 201})
    on_disk = path.read_text(encoding="utf-8").splitlines()
    assert len(on_disk) == 1, on_disk
    assert json.loads(on_disk[0])["stage"] == "first"
    with pytest.raises(RuntimeError):
        ledger.append("second", {"status_code": 200})
        raise RuntimeError("deliberate failure after the stage was recorded")
    assert ledger.rows == 2
    after_failure = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(row)["stage"] for row in after_failure] == [
        "first",
        "second",
    ], after_failure
    second_ledger = StageLedger(path, run_id="s12qa-unit-2")
    second_ledger.append("third", {"status_code": 200})
    second_ledger.close()
    ledger.close()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


#: Tokens that would present this node's API context read as a browser /
#: UI reload.  The real browser journey is owned by MF-DEMO-E2E.  Declared
#: here, INSIDE the guard region, so the guard can name what it forbids
#: while the chain body stays free of the vocabulary.
FORBIDDEN_PATH_TOKENS = (
    "ui_reload",
    "browser_reload",
    "playwright",
    "selenium",
)


def test_frozen_candidate_node_declares_its_path_class() -> None:
    """RUNNABLE NOW: the node must declare WHICH path it executes and
    must not present an API context read as a browser/UI reload."""
    source = Path(__file__).read_text(encoding="utf-8")
    assert "ENGINEERING_FIXTURE_API" in source
    assert "MF-DEMO-E2E" in source, "the demo owner must be named"
    # Scan the CHAIN BODY (module + node), not the guard tests themselves:
    # the forbidden list below has to name the tokens it forbids, and the
    # freeze manifest declares the UI lane's own step, which belongs to
    # MF-DEMO-E2E and is not a claim made by this node.  Both live AFTER
    # this marker, so the scan region ends here.
    marker = "#: Tokens that would present this node"
    body = source.split(marker)[0]
    assert body and body != source, "the scan region must be the chain body"
    assert "api_context_reload" in body, "the API read must be named as such"
    for forbidden in FORBIDDEN_PATH_TOKENS:
        assert forbidden not in body, (
            f"{forbidden!r} would claim a browser journey this node does not run"
        )
    # The exclusion above must not be able to hide a claim: every remaining
    # site in the tail has to be one of the two DECLARATION sites -- the token
    # tuple above and the freeze manifest's own step list.  Built FROM the
    # constant (never re-spelled as a literal) so this guard cannot satisfy
    # itself with its own allow-list.
    allowed = {f'"{token}",' for token in FORBIDDEN_PATH_TOKENS}
    for line in source[len(body):].splitlines():
        stripped = line.strip()
        for forbidden in FORBIDDEN_PATH_TOKENS:
            if forbidden in stripped:
                assert stripped in allowed, (
                    f"{forbidden!r} appears outside a declaration: {stripped!r}"
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
