"""MF-END-24 — UI xem trước, QC và retry shot lỗi: acceptance + negative controls.

Row map (binary; each row is either a REAL execution of the shipped frontend
logic under Node's type-stripping loader, a REAL HTTP call through the
``client`` fixture against the running FastAPI app, or a source-level contract
check that fails closed):

* micro repro (24.0): the NEW ``features/shot-review`` surface exists and the
  demo/apply integration markers are present; every backend path the feature
  consumes exists in the REAL FastAPI route table (no invented routes), and
  the checker itself is proven non-vacuous by a bogus-path control;
* 24.1 shots/time-map/view refs: chunks group into ONE unit per shot with the
  real frame range and state-derived progress; frame<->seconds uses the run's
  real fps and refuses to convert without it; publications bind to a shot only
  by artifact/content-hash identity; the HTTP status payload of a seeded run
  carries exactly the fields the UI reads, and the SHIPPED grouping function
  produces the same shots over that real payload;
* 24.2 QC markers + scoped retry: a marker's frame/role come from
  qc-navigation only (no location -> typed refusal, never a guessed frame);
  the scoped-retry payload targets exactly one shot and requires an applied
  correction authority; the recompute endpoint refuses a random correction id
  with ZERO mutation (fail-closed), and the qc-items/qc-navigation routes
  answer on the real app;
* 24.3 pause/cancel/retry/resume: the control matrix matches the real state
  machine (no dead buttons); cancel moves a running run to cancelled; retry
  creates a successor attempt with identical chunk boundaries while the
  predecessor's chunk hashes stay byte-identical; retry on a running run and
  resume on a cancelled run are refused (typed);
* 24.4 errors + refresh: every ``shot_cache_*`` code in the shipped taxonomy
  exists in the backend that raises it; OOM / network / 404 / 409 map to
  Vietnamese copy + an action; the URL/localStorage state round-trips and
  ignores unknown keys; a source scan proves no synthetic progress
  (no Math.random / setInterval / fake counters) and that every button in the
  new surfaces carries Vietnamese helper text with a readable colour.

Disclosure: everything here is CI fixture work — the run/chunk/publication
rows are seeded into the per-test isolated SQLite database from
``tests/conftest.py`` (deterministic bytes, no GPU, no ComfyUI, no real
product media).  No product-demo claim is made by this file.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

WT = Path(__file__).resolve().parents[2]
FRONTEND = WT / "frontend"
SR_DIR = FRONTEND / "src" / "features" / "shot-review"
LOGIC_TS = SR_DIR / "shotReviewLogic.ts"
API_TS = SR_DIR / "shotReviewApi.ts"

SR_FILES = [
    "shotReviewLogic.ts",
    "shotReviewApi.ts",
    "useShotReview.ts",
    "BeforeAfterSync.tsx",
    "QcMarkerList.tsx",
    "ShotList.tsx",
    "ShotReviewPanel.tsx",
    "index.ts",
]
APPLY_NEW = FRONTEND / "src" / "features" / "apply" / "ApplyShotReview.tsx"
DEMO_NEW = FRONTEND / "src" / "features" / "demo" / "DemoShotReview.tsx"

#: The shipped endpoint map is the ONLY backend surface this feature may use.
ENDPOINT_TEMPLATE = re.compile(r"\{[^}]+\}")


def _norm(path: str) -> str:
    return ENDPOINT_TEMPLATE.sub("{}", path.rstrip("/"))


# ── Node battery: run the SHIPPED logic (real execution, not a re-implementation) ──

_DRIVER_JS = r"""
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";

const mod = await import(pathToFileURL(process.argv[2]).href);
const payload = process.argv[3] ? JSON.parse(readFileSync(process.argv[3], "utf-8")) : null;

const chunks = [
  { id: "c1", chunk_index: 0, order_index: 0, shot_id: "BOOK", layer_id: "l1", object_role_id: "r1", core_start_frame: 0, core_end_frame: 9, content_hash: "a".repeat(64), state: "completed", attempt: 1, artifact_id: "art-1", verified: true },
  { id: "c2", chunk_index: 1, order_index: 1, shot_id: "BOOK", layer_id: "l1", object_role_id: "r1", core_start_frame: 10, core_end_frame: 19, content_hash: "b".repeat(64), state: "pending", attempt: 2, artifact_id: null, verified: false },
  { id: "c3", chunk_index: 2, order_index: 2, shot_id: "TURN", layer_id: "l2", object_role_id: null, core_start_frame: 20, core_end_frame: 29, content_hash: "c".repeat(64), state: "completed", attempt: 1, artifact_id: "art-3", verified: true },
];
const pubs = [
  { id: "pub-1", artifact_id: "art-1", content_hash: "a".repeat(64), frame_count: 10, frame_metadata: {}, state: "completed" },
  { id: "pub-x", artifact_id: "art-OTHER", content_hash: "d".repeat(64), frame_count: 10, frame_metadata: {}, state: "completed" },
  { id: "pub-stale", artifact_id: "art-1", content_hash: "a".repeat(64), frame_count: 10, frame_metadata: {}, state: "failed" },
];

let singleFlightCalls = 0;
const latch = mod.createSingleFlight();
const slow = () => new Promise((resolve) => setTimeout(() => { singleFlightCalls += 1; resolve("ok"); }, 20));
const [r1, r2] = await Promise.all([latch.run(slow), latch.run(slow)]);
const afterSettle = await latch.run(async () => { singleFlightCalls += 1; return "again"; });

const out = {
  shots: mod.groupChunksIntoShots(chunks),
  progress: mod.runProgress(chunks),
  progressEmpty: mod.runProgress([]),
  refs: mod.shotOutputRefs(mod.groupChunksIntoShots(chunks)[0], pubs),
  fps30: mod.frameToSeconds(30, 30, 1),
  back: mod.secondsToFrame(1.0, 30, 1),
  noFps: mod.frameToSeconds(30, null, null),
  backNoFps: mod.secondsToFrame(1.0, 0, 0),
  window: mod.shotWindowOnRun(mod.groupChunksIntoShots(chunks)[0], 30, 1),
  windowNoFps: mod.shotWindowOnRun(mod.groupChunksIntoShots(chunks)[0], null, null),
  controlsRunning: mod.reviewControls("running"),
  controlsFailed: mod.reviewControls("failed"),
  controlsCancelled: mod.reviewControls("cancelled"),
  controlsCompleted: mod.reviewControls("completed"),
  controlsUnknown: mod.reviewControls("weird_state"),
  marker: mod.placeQcMarker({ qc_item_id: "q1", severity: "blocker", reason_code: "identity_drift", location: { frame_index: 15, timecode_ms: 500, object_role_id: "role-a" } }, 30, 1),
  markerTimecode: mod.placeQcMarker({ qc_item_id: "q2", severity: "warning", reason_code: "x", location: { frame_index: null, timecode_ms: 1000, object_role_id: "role-b" } }, 30, 1),
  markerNoLoc: mod.placeQcMarker({ qc_item_id: "q3", severity: "warning", reason_code: "x", location: null }, 30, 1),
  markerEmptyLoc: mod.placeQcMarker({ qc_item_id: "q4", severity: "warning", reason_code: "x", location: { frame_index: null, timecode_ms: null, object_role_id: null } }, 30, 1),
  markerNoFps: mod.placeQcMarker({ qc_item_id: "q5", severity: "warning", reason_code: "x", location: { frame_index: 15, timecode_ms: null, object_role_id: null } }, null, null),
  retry: mod.scopedRetryPayload("BOOK", { correction_id: "corr-1", correction_kind: "route", target_layer_ids: ["l1"] }, 3),
  retryNoAuth: mod.scopedRetryPayload("BOOK", null, 3),
  retryEmptyLayers: mod.scopedRetryPayload("BOOK", { correction_id: "corr-1", correction_kind: "route", target_layer_ids: [] }, 3),
  authority: mod.correctionAuthorityFromCheckpoint({ correction: { correction_id: "corr-9", correction_kind: "mask", target_layer_ids: ["la", "lb"] } }),
  authorityMalformed: mod.correctionAuthorityFromCheckpoint({ correction: { correction_id: "", correction_kind: "mask", target_layer_ids: [] } }),
  authorityMissing: mod.correctionAuthorityFromCheckpoint(null),
  errCache: mod.classifyReviewError({ code: "shot_cache_receipt_conflict" }),
  errOom: mod.classifyReviewError({ message: "CUDA out of memory. Tried to allocate 512 MiB" }),
  err404: mod.classifyReviewError({ status: 404, message: "not found" }),
  err409: mod.classifyReviewError({ status: 409, message: "conflict" }),
  errNetwork: mod.classifyReviewError({ message: "TypeError: Failed to fetch" }),
  errUnknown: mod.classifyReviewError({}),
  url: mod.serializeReviewState({ runId: "run-24", shotId: "BOOK", frame: 15 }),
  urlSparse: mod.serializeReviewState({ runId: "run-24", shotId: null, frame: null }),
  urlSeconds: mod.serializeReviewState({ runId: "run-24", shotId: "BOOK", frame: 15, seconds: 0.5 }),
  parsed: mod.parseReviewState("run=run-24&shot=BOOK&frame=15&bogus=1"),
  parsedSeconds: mod.parseReviewState("run=run-24&sec=0.5"),
  parsedBadFrame: mod.parseReviewState("run=r&frame=abc"),
  singleFlight: { calls: singleFlightCalls, r1, r2, afterSettle, pending: latch.isPending() },
  http: payload
    ? {
        shots: mod.groupChunksIntoShots(payload.chunks),
        refs: mod.groupChunksIntoShots(payload.chunks).map((s) => mod.shotOutputRefs(s, payload.publications)),
        progress: mod.runProgress(payload.chunks),
        fps_typed_null: mod.frameToSeconds(payload.frame_count, payload.fps_num ?? null, payload.fps_den ?? null),
        window_typed_null: mod.shotWindowOnRun(mod.groupChunksIntoShots(payload.chunks)[0], payload.fps_num ?? null, payload.fps_den ?? null),
      }
    : null,
};
console.log(JSON.stringify(out));
"""


def _run_node(driver: Path, payload: dict[str, Any] | None = None, tmp_dir: Path | None = None) -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to execute the shipped shot-review logic"
    argv = [node, "--no-warnings", str(driver), str(LOGIC_TS)]
    if payload is not None:
        assert tmp_dir is not None
        payload_path = tmp_dir / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        argv.append(str(payload_path))
    proc = subprocess.run(
        argv,
        cwd=str(FRONTEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"node battery failed rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, f"node battery printed no JSON payload\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def node_driver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    driver_dir = tmp_path_factory.mktemp("mf24_driver")
    driver = driver_dir / "driver.mjs"
    driver.write_text(_DRIVER_JS, encoding="utf-8")
    return driver


@pytest.fixture(scope="module")
def battery(node_driver: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _run_node(node_driver, tmp_dir=tmp_path_factory.mktemp("mf24_battery"))


# ── 24.0 — micro repro: surface + real route binding ────────────────────────


def test_mf24_0_surface_exists_and_integration_markers_present() -> None:
    for name in SR_FILES:
        path = SR_DIR / name
        assert path.is_file(), f"missing shipped file: {path}"
        assert path.stat().st_size > 0, f"empty shipped file: {path}"
    assert APPLY_NEW.is_file() and APPLY_NEW.stat().st_size > 0
    assert DEMO_NEW.is_file() and DEMO_NEW.stat().st_size > 0
    progress = (FRONTEND / "src" / "features" / "apply" / "ApplyProgress.tsx").read_text(encoding="utf-8")
    assert "ApplyShotReview" in progress, "ApplyProgress must mount the shared shot-review panel"
    apply_index = (FRONTEND / "src" / "features" / "apply" / "index.ts").read_text(encoding="utf-8")
    assert "ApplyShotReview" in apply_index
    demo_panel = (FRONTEND / "src" / "features" / "demo" / "DemoComparePanel.tsx").read_text(encoding="utf-8")
    assert "DemoShotReview" in demo_panel, "DemoComparePanel must render the before/after sync card"
    # The panel itself must be composed of the shipped parts.
    panel = (SR_DIR / "ShotReviewPanel.tsx").read_text(encoding="utf-8")
    for part in ("BeforeAfterSync", "QcMarkerList", "ShotList", "useShotReview"):
        assert part in panel, f"ShotReviewPanel must compose {part}"


def _endpoint_entries() -> list[tuple[str, str]]:
    src = API_TS.read_text(encoding="utf-8")
    block = src.split("SHOT_REVIEW_ENDPOINTS", 1)[1].split("] as const", 1)[0]
    entries = re.findall(r'method:\s*"([A-Z]+)",\s*path:\s*"([^"]+)"', block)
    assert entries, "SHOT_REVIEW_ENDPOINTS must declare method+path pairs"
    return entries


def _unbound_endpoints(entries: list[tuple[str, str]]) -> list[str]:
    from app.api.app import app

    # This FastAPI build wraps included routers (`_IncludedRouter`, path=None),
    # so the authoritative flat surface is the generated OpenAPI document.
    spec = app.openapi()
    available: set[tuple[str, str]] = set()
    for path, ops in spec.get("paths", {}).items():
        for method in ops:
            available.add((method.upper(), _norm(path)))
    unbound: list[str] = []
    for method, path in entries:
        if (method.upper(), _norm(path)) not in available:
            unbound.append(f"{method} {path}")
    return unbound


def test_mf24_0_every_consumed_route_exists_on_the_real_app() -> None:
    unbound = _unbound_endpoints(_endpoint_entries())
    assert unbound == [], f"feature consumes routes the backend does not serve: {unbound}"
    # every /api/v2 literal in the feature sources must be one of the declared paths
    declared = {_norm(p) for _, p in _endpoint_entries()}
    for name in SR_FILES:
        src = (SR_DIR / name).read_text(encoding="utf-8")
        for literal in re.findall(r'"(/api/v2[^"]*)"', src):
            assert _norm(literal) in declared, f"{name} uses undeclared path {literal}"


def test_mf24_0_route_checker_is_not_vacuous() -> None:
    bogus = [("GET", "/api/v2/does-not-exist/{run_id}"), ("POST", "/api/v2/full-apply/{run_id}/explode")]
    unbound = _unbound_endpoints(bogus)
    assert len(unbound) == 2, f"route checker failed to flag bogus routes: {unbound}"
    # and the real GET status route must NOT be flagged (positive control)
    assert _unbound_endpoints([("GET", "/api/v2/full-apply/{run_id}")]) == []


# ── 24.1 — before/after sync, shot list, view refs ──────────────────────────


def test_mf24_1_shots_group_per_shot_with_real_ranges_and_progress(battery: dict[str, Any]) -> None:
    shots = battery["shots"]
    assert [s["shot_id"] for s in shots] == ["BOOK", "TURN"]
    book = shots[0]
    assert book["chunk_count"] == 2 and book["chunk_ids"] == ["c1", "c2"]
    assert (book["start_frame"], book["end_frame"]) == (0, 19)
    assert book["state"] == "pending" and book["completed"] == 1 and book["progress_pct"] == 50
    assert book["attempt"] == 2 and book["verified"] is False
    turn = shots[1]
    assert turn["state"] == "completed" and turn["verified"] is True and turn["progress_pct"] == 100
    assert battery["progress"] == 67
    assert battery["progressEmpty"] is None


def test_mf24_1_time_map_uses_real_fps_and_refuses_without_it(battery: dict[str, Any]) -> None:
    assert battery["fps30"] == 1.0
    assert battery["back"] == 30
    assert battery["noFps"] is None and battery["backNoFps"] is None
    window = battery["window"]
    assert window is not None and window["start_sec"] == 0.0
    assert abs(window["end_sec"] - (20 / 30)) < 1e-9
    assert battery["windowNoFps"] is None


def test_mf24_1_view_refs_bind_only_by_real_identity(battery: dict[str, Any]) -> None:
    refs = battery["refs"]
    assert [r["publication_id"] for r in refs] == ["pub-1"], (
        "a publication must bind by artifact/content-hash identity and a non-completed one is not an output"
    )
    assert refs[0]["artifact_id"] == "art-1" and refs[0]["content_hash"] == "a" * 64


def test_mf24_1_http_status_payload_feeds_the_shipped_grouping(
    client: Any, node_driver: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    from app.api import deps

    sf = deps._job_service.session_factory
    run_id = "run-24-status"
    _seed_run(sf, run_id=run_id, pending_chunks=1)
    res = client.get(f"/api/v2/full-apply/{run_id}", params={"workspace_id": "default", "project_id": "p1"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["run_id"] == run_id and body["status"] == "running"
    assert body["frame_count"] == 30
    assert {c["shot_id"] for c in body["chunks"]} == {"BOOK", "TURN"}
    for chunk in body["chunks"]:
        for key in ("id", "shot_id", "core_start_frame", "core_end_frame", "state", "artifact_id", "content_hash", "attempt", "verified"):
            assert key in chunk, f"status chunk lost the field the UI reads: {key}"
    assert len(body["publications"]) == 1 and body["publications"][0]["artifact_id"] == f"art-{run_id}-ck00"
    # The SHIPPED grouping runs over the REAL HTTP payload.
    out = _run_node(node_driver, payload={"chunks": body["chunks"], "publications": body["publications"]}, tmp_dir=tmp_path_factory.mktemp("mf24_http"))
    http_shots = out["http"]["shots"]
    assert [s["shot_id"] for s in http_shots] == ["BOOK", "TURN"]
    assert http_shots[0]["chunk_count"] == 2 and (http_shots[0]["start_frame"], http_shots[0]["end_frame"]) == (0, 19)
    assert out["http"]["refs"][0] and out["http"]["refs"][0][0]["artifact_id"] == f"art-{run_id}-ck00"
    assert out["http"]["progress"] == 67
    # This backend version's status payload carries no fps: the shipped logic
    # must answer with a TYPED null (never invent a frame rate) — the timeline
    # then shows its explicit "chưa có fps" state instead of fake seconds.
    assert "fps_num" not in body and "fps_den" not in body
    assert out["http"]["fps_typed_null"] is None and out["http"]["window_typed_null"] is None


# ── 24.2 — QC marker placement + scoped retry ───────────────────────────────


def test_mf24_2_marker_placement_is_canonical_or_typed_refusal(battery: dict[str, Any]) -> None:
    marker = battery["marker"]
    assert marker["status"] == "ok" and marker["frame"] == 15 and marker["seconds"] == 0.5
    assert marker["role_id"] == "role-a"
    tc = battery["markerTimecode"]
    assert tc["status"] == "ok" and tc["frame"] == 30 and tc["seconds"] == 1.0 and tc["role_id"] == "role-b"
    # a canonical frame without a timecode/fps keeps the FRAME (never guessed)
    # and honestly reports no seek target instead of inventing seconds
    no_fps = battery["markerNoFps"]
    assert no_fps["status"] == "ok" and no_fps["frame"] == 15 and no_fps["seconds"] is None
    for key in ("markerNoLoc", "markerEmptyLoc"):
        assert battery[key]["status"] == "no_location", f"{key} must refuse instead of guessing a frame"
        assert battery[key]["reason_vi"], f"{key} must carry the Vietnamese refusal reason"


def test_mf24_2_scoped_retry_payload_targets_one_shot_and_needs_authority(battery: dict[str, Any]) -> None:
    payload = battery["retry"]
    assert payload["target_shot_ids"] == ["BOOK"]
    assert payload["correction_id"] == "corr-1" and payload["target_layer_ids"] == ["l1"]
    assert payload["expected_revision"] == 3
    assert battery["retryNoAuth"] is None and battery["retryEmptyLayers"] is None
    authority = battery["authority"]
    assert authority["correction_id"] == "corr-9" and authority["target_layer_ids"] == ["la", "lb"]
    assert battery["authorityMalformed"] is None and battery["authorityMissing"] is None


def test_mf24_2_http_qc_routes_answer_on_the_real_app(client: Any) -> None:
    # qc-items is keyed by a real project UUID on the live surface
    project_uuid = "11111111-1111-1111-1111-111111111111"
    res = client.get(f"/api/v2/projects/{project_uuid}/qc-items")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["project_id"] == project_uuid and isinstance(body["items"], list) and "total" in body
    nav = client.get("/api/v2/qc-navigation/00000000-0000-0000-0000-000000000000")
    assert nav.status_code == 404, "unknown QC item must 404 (no fabricated location)"


def test_mf24_2_http_recompute_refuses_random_correction_with_zero_mutation(client: Any) -> None:
    from app.api import deps

    sf = deps._job_service.session_factory
    run_id = "run-24-recompute-neg"
    _seed_run(sf, run_id=run_id)
    before = _run_snapshot(sf, run_id)
    res = client.post(
        f"/api/v2/full-apply/{run_id}/recompute",
        params={"workspace_id": "default", "project_id": "p1"},
        json={
            "correction_id": "random-correction-not-applied",
            "correction_kind": "route",
            "target_layer_ids": ["layer_a"],
            "target_shot_ids": ["BOOK"],
        },
    )
    assert res.status_code in (404, 422), f"random correction id must fail closed, got {res.status_code}: {res.text}"
    after = _run_snapshot(sf, run_id)
    assert before == after, "a refused recompute must not mutate run revision or chunk attempts"


# ── 24.3 — pause/cancel/retry/resume through the real API ───────────────────


def test_mf24_3_control_matrix_matches_the_real_state_machine(battery: dict[str, Any]) -> None:
    running = battery["controlsRunning"]
    assert running["cancel"] and running["resume"] and not running["retry"]
    failed = battery["controlsFailed"]
    assert failed["retry"] and failed["resume"] and not failed["cancel"]
    cancelled = battery["controlsCancelled"]
    assert cancelled["retry"] and not cancelled["cancel"] and not cancelled["resume"]
    completed = battery["controlsCompleted"]
    assert not (completed["cancel"] or completed["retry"] or completed["resume"])
    unknown = battery["controlsUnknown"]
    assert not (unknown["cancel"] or unknown["retry"] or unknown["resume"])
    assert all(battery[k]["note_vi"] for k in ("controlsRunning", "controlsFailed", "controlsCancelled", "controlsCompleted"))


def test_mf24_3_http_cancel_then_retry_keeps_other_shots_bytes(client: Any) -> None:
    from app.api import deps

    sf = deps._job_service.session_factory
    run_id = "run-24-cancel"
    _seed_run(sf, run_id=run_id, status="running")
    before_chunks = _chunk_rows(sf, run_id)

    cancel = client.post(f"/api/v2/full-apply/{run_id}/cancel", params={"workspace_id": "default", "project_id": "p1"})
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"
    status = client.get(f"/api/v2/full-apply/{run_id}", params={"workspace_id": "default"}).json()
    assert status["status"] == "cancelled"

    # retry on a RUNNING run must be refused before any successor exists
    other = "run-24-running-retry"
    _seed_run(sf, run_id=other, status="running")
    refused = client.post(f"/api/v2/full-apply/{other}/retry", params={"workspace_id": "default", "project_id": "p1"})
    assert refused.status_code in (409, 422), f"retry of a running run must be refused: {refused.status_code}"

    retry = client.post(f"/api/v2/full-apply/{run_id}/retry", params={"workspace_id": "default", "project_id": "p1"})
    assert retry.status_code == 200, retry.text
    successor = retry.json()
    assert successor["attempt"] == 2 and successor["predecessor_run_id"] == run_id
    succ_status = client.get(f"/api/v2/full-apply/{successor['run_id']}", params={"workspace_id": "default"}).json()
    assert succ_status["status"] in ("pending", "running")
    assert succ_status["attempt"] == 2
    # successor carries the same shot/frame plan
    assert [(c["shot_id"], c["core_start_frame"], c["core_end_frame"]) for c in succ_status["chunks"]] == [
        (c["shot_id"], c["core_start_frame"], c["core_end_frame"]) for c in before_chunks
    ]
    # predecessor bytes are untouched by the retry (U17: retry keeps the kept shots)
    assert _chunk_rows(sf, run_id) == before_chunks

    # resume on a cancelled run is refused (typed) — no silent resurrection
    resume = client.post(f"/api/v2/full-apply/{run_id}/resume", params={"workspace_id": "default", "project_id": "p1"})
    assert resume.status_code == 422, f"resume on cancelled must be 422: {resume.status_code} {resume.text}"


# ── 24.4 — error taxonomy, refresh persistence, no-fake-progress ────────────


def test_mf24_4_taxonomy_codes_exist_in_the_backend_that_raises_them() -> None:
    logic = LOGIC_TS.read_text(encoding="utf-8")
    backend = (WT / "app" / "services" / "shot_reskin_cache.py").read_text(encoding="utf-8")
    codes = set(re.findall(r"shot_cache_[a-z_]+", logic))
    assert len(codes) >= 7, f"taxonomy lost codes: {sorted(codes)}"
    missing = sorted(c for c in codes if c not in backend)
    assert missing == [], f"taxonomy names codes the backend never raises: {missing}"
    for pattern in ("out of memory", "no durable job manifest", "affected closure is empty"):
        assert pattern in logic, f"taxonomy lost the runtime pattern: {pattern}"


def test_mf24_4_error_copy_is_vietnamese_with_an_action(battery: dict[str, Any]) -> None:
    for key in ("errCache", "errOom", "err404", "err409", "errNetwork", "errUnknown"):
        copy = battery[key]
        assert copy["title_vi"] and copy["action_vi"], f"{key} lacks VN copy"
        assert any(ord(ch) >= 0xC0 for ch in copy["title_vi"]), f"{key} title is not Vietnamese"
    assert battery["errOom"]["code"] == "engine_out_of_memory" and battery["errOom"]["retryable"] is True
    assert battery["errCache"]["code"] == "shot_cache_receipt_conflict" and battery["errCache"]["retryable"] is True
    assert battery["err404"]["code"] == "not_found" and battery["err404"]["retryable"] is False
    assert battery["errNetwork"]["code"] == "network_unreachable"


def test_mf24_4_refresh_state_roundtrip(battery: dict[str, Any]) -> None:
    assert battery["url"] == "run=run-24&shot=BOOK&frame=15"
    assert battery["urlSparse"] == "run=run-24"
    assert battery["urlSeconds"] == "run=run-24&shot=BOOK&frame=15&sec=0.5"
    parsed = battery["parsed"]
    assert parsed["runId"] == "run-24" and parsed["shotId"] == "BOOK" and parsed["frame"] == 15
    assert battery["parsedSeconds"]["seconds"] == 0.5
    assert battery["parsedBadFrame"]["frame"] is None and battery["parsedBadFrame"]["runId"] == "r"


def test_mf24_4_single_flight_latch_issues_one_request_per_intent(battery: dict[str, Any]) -> None:
    sf = battery["singleFlight"]
    assert sf["calls"] == 2, f"two rapid clicks must issue ONE request (plus the explicit retry): {sf}"
    assert sf["r1"] == sf["r2"] == "ok" and sf["afterSettle"] == "again" and sf["pending"] is False


def test_mf24_4_no_synthetic_progress_and_helper_text_convention() -> None:
    forbidden = ("Math.random", "setInterval", "fakeProgress", "simulateProgress")
    for name in SR_FILES:
        src = (SR_DIR / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in src, f"{name} contains synthetic progress token {token}"
    panel = (SR_DIR / "ShotReviewPanel.tsx").read_text(encoding="utf-8")
    assert "review.progress" in panel, "progress must come from the backend-derived hook value"
    # every button in the new surfaces must carry Vietnamese helper text below it
    helper_files = [SR_DIR / n for n in SR_FILES if n.endswith(".tsx")]
    helper_files += [APPLY_NEW, DEMO_NEW]
    for path in helper_files:
        src = path.read_text(encoding="utf-8")
        for match in re.finditer(r"</button>", src):
            tail = src[match.end() : match.end() + 400]
            assert "HELPER" in tail or "text-[11px]" in tail, f"{path.name}: button without helper text below"
        assert "text-gray-500" not in src.replace("disabled:text-gray-500", ""), (
            f"{path.name}: helper text must not use gray-500 (unreadable on gray-900)"
        )


# ── seeding helpers (raw SQL over the isolated test DB) ─────────────────────


def _seed_run(
    sf: Any,
    *,
    run_id: str,
    status: str = "running",
    shots: tuple[tuple[str, int], ...] = (("BOOK", 2), ("TURN", 1)),
    fps: tuple[int, int] = (30, 1),
    frame_count: int = 30,
    pending_chunks: int = 0,
) -> None:
    cp_hash = "a" * 64
    with sf() as s:
        # Parent chain required by the FK constraints (workspace -> project ->
        # video -> cast -> checkpoint -> run).  INSERT OR IGNORE keeps a second
        # seed call in the same test idempotent.
        s.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES ('default','default')"))
        s.execute(text("INSERT OR IGNORE INTO project(id,workspace_id,name) VALUES ('p1','default','Proj')"))
        s.execute(text("INSERT OR IGNORE INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)"))
        s.execute(text("INSERT OR IGNORE INTO character(id,workspace_id,name,code) VALUES ('ch1','default','hero','hero1')"))
        s.execute(
            text(
                "INSERT OR IGNORE INTO character_pack_version(id,character_id,workspace_id,version,status)"
                " VALUES ('pv1','ch1','default',1,'published')"
            )
        )
        s.execute(
            text(
                "INSERT OR IGNORE INTO object_role(id,workspace_id,project_id,video_item_id,"
                " source_generation,name,kind,status) VALUES ('r1','default','p1','v1','1','role','character','confirmed')"
            )
        )
        s.execute(
            text(
                "INSERT OR IGNORE INTO reskin_config(id, workspace_id, project_id, object_role_id,"
                " character_id, pack_version_id, params_json, revision) VALUES ('rc1','default','p1','r1','ch1','pv1','{}',1)"
            )
        )
        s.execute(
            text(
                "INSERT OR IGNORE INTO apply_checkpoint(id, workspace_id, project_id, reskin_config_id,"
                " reskin_config_revision, pack_version_ids_json, loop_hashes_json,"
                " timebase_fingerprint, snapshot_json, checkpoint_hash, revision, created_at,"
                " updated_at) VALUES ('cp1','default','p1','rc1',1,'[]','[]','30/1','{}',:h,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"h": cp_hash},
        )
        s.execute(
            text(
                "INSERT INTO s10_full_apply_run(id, workspace_id, project_id, video_item_id,"
                " apply_checkpoint_id, apply_checkpoint_hash, apply_checkpoint_revision, plan_id,"
                " plan_hash, status, frame_count, fps_num, fps_den, chunk_config_json, attempt,"
                " revision, created_at, updated_at) VALUES"
                " (:id,'default','p1','v1','cp1',:h,1,:pid,:ph,:status,:fc,:fn,:fd,'{}',1,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": run_id,
                "h": cp_hash,
                "pid": "c" * 64,
                "ph": "b" * 64,
                "status": status,
                "fc": frame_count,
                "fn": fps[0],
                "fd": fps[1],
            },
        )
        idx = 0
        for shot, count in shots:
            for k in range(count):
                chunk_id = f"{run_id}-ck{idx:02d}"
                chunk_hash = hashlib.sha256(f"{run_id}:{idx}".encode()).hexdigest()
                total_chunks = sum(count for _, count in shots)
                chunk_state = "pending" if idx >= total_chunks - pending_chunks else "completed"
                chunk_verified = 0 if chunk_state == "pending" else 1
                s.execute(
                    text(
                        "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256,"
                        " size_bytes, revision) VALUES (:id,'default','video',:rel,'ready',:sha,1024,1)"
                    ),
                    {"id": f"art-{chunk_id}", "rel": f"shots/{chunk_id}.mp4", "sha": "d" * 64},
                )
                s.execute(
                    text(
                        "INSERT INTO s10_full_apply_chunk(id, workspace_id, run_id, shot_id, layer_id,"
                        " order_index, chunk_index, core_start_frame, core_end_frame, state, verified,"
                        " attempt, artifact_id, content_hash, natural_key) VALUES (:id,'default',:rid,"
                        ":shot,'layer_a',:oi,:oi,:cs,:ce,:state,:ver,1,:aid,:ch,:nk)"
                    ),
                    {
                        "id": chunk_id,
                        "rid": run_id,
                        "shot": shot,
                        "oi": idx,
                        "cs": idx * 10,
                        "ce": idx * 10 + 9,
                        "state": chunk_state,
                        "ver": chunk_verified,
                        "aid": f"art-{chunk_id}",
                        "ch": chunk_hash,
                        "nk": f"s10_chunk:{run_id}:{idx}",
                    },
                )
                idx += 1
        # The publication pins the FIRST chunk's artifact identity so the UI's
        # view-ref binding can be exercised over real rows (CI fixture).
        first_artifact = f"art-{run_id}-ck00"
        pub_hash = hashlib.sha256(f"pub:{run_id}:{first_artifact}".encode()).hexdigest()
        s.commit()
        from app.persistence.s10_full_apply import S10ApplyRepository

        repo = S10ApplyRepository(s)
        repo.create_publication(
            "default",
            run_id,
            first_artifact,
            pub_hash,
            frame_count,
            {"frame_count": frame_count},
            "cp1",
            cp_hash,
            1,
            state="completed",
        )
        s.commit()


def _chunk_rows(sf: Any, run_id: str) -> list[dict[str, Any]]:
    with sf() as s:
        rows = (
            s.execute(
                text(
                    "SELECT id, shot_id, core_start_frame, core_end_frame, state, attempt,"
                    " content_hash, artifact_id FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY order_index"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchall()
        )
        return [dict(r) for r in rows]


def _run_snapshot(sf: Any, run_id: str) -> dict[str, Any]:
    with sf() as s:
        run = s.execute(
            text("SELECT status, revision, attempt FROM s10_full_apply_run WHERE id=:rid"),
            {"rid": run_id},
        ).mappings().first()
        chunks = (
            s.execute(
                text("SELECT id, attempt, state, verified, content_hash FROM s10_full_apply_chunk WHERE run_id=:rid ORDER BY id"),
                {"rid": run_id},
            )
            .fetchall()
        )
        return {"run": dict(run) if run else None, "chunks": [tuple(r) for r in chunks]}
