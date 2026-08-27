"""S09 demo comparison API routes (S09-T04).

Isolated read/observe router under ``/api/v2/s09-demo-compare`` (disjoint
from every legacy route, from /api/v2/reskin-configs and from the T03
``/api/v2/s09-demo-loops`` namespace).  Thin API boundary ONLY — no business
logic, no fabricated fallback:

- GET /capabilities: measured route evidence from ONE frozen benchmark
  results document (validated by the T02 loader).  Every row/check is copied
  from the document; a class with no passing measurement reports
  ``smallest_passing_route: null`` — never an invented default.
- POST /jobs: submits the risk-selected demo-loop batch through the T03
  service contract (same manifest fingerprint → idempotent replay → same
  durable Job) and ensures the S09_DEMO_LOOP handler + worker are live so a
  UI-submitted job actually RUNS (T03 leaves registration to the caller).
- GET /loops: per-loop locked structure from fixture manifests with planned
  routes resolved through the SAME fail-closed planner used at submit time.
- GET /jobs/{job_id}: durable status + published artifacts (content served
  through the contained managed-root endpoint) + persisted SegmentRenderRoute
  evidence when the manifest references one.
- GET /content/{loop_id}/{sha256}: serves published loop bytes from the
  managed root via containment-checked resolution (ManagedRoot.resolve);
  unknown path → 404 without leaking filesystem detail.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from app.api.deps import get_job_service
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import IdempotencyKeyInUse, JobRepository
from app.schemas.s09_demo_compare import (
    BenchmarkClassSummary,
    BenchmarkRouteRow,
    CapabilitiesResponse,
    DemoCompareJobCreated,
    DemoCompareJobRequest,
    DemoCompareStatus,
    GenerationEvidence,
    LoopListResponse,
    LoopManifestResponse,
    LoopSegment,
    PublicationIdentity,
    PublicationStatus,
    PublishedArtifact,
    RegenerateJobCreated,
    RegenerateJobRequest,
    RouteEvidenceEntry,
)
from app.services.renderer_routes import (
    BenchmarkResultsDocument,
    BenchmarkResultsError,
    load_benchmark_results,
)
from app.services.s09_correction import (
    CorrectionConflictError,
    CorrectionNotFoundError,
    CorrectionValidationError,
    S09CorrectionRepository,
)
from app.workflow.s09_demo_jobs import (
    JOB_TYPE_S09_DEMO_LOOP,
    JOB_TYPE_S09_DEMO_REGEN,
    build_demo_plan,
    demo_loop_steps,
    regen_fingerprint,
)
from app.workflow.s09_demo_jobs import (
    register_s09_demo_loop_handler as _register_handler,
)

router = APIRouter(prefix="/api/v2/s09-demo-compare", tags=["s09-demo-compare"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID

# ── FINAL C2 evidence binding (Manager resume 2026-08-25, J2-C2 open) ────────
#
# The EXACT frozen S09-C3 evidence identity every T04 surface must pin.
# capabilities / loops / jobs ALL resolve evidence through _pinned_evidence,
# which verifies the on-disk decision document hashes to this SHA and that
# its embedded i03_run_A input is the SAME benchmark document being read —
# a missing/stale/mutated file fails closed instead of planning routes.
# C3 FINAL BINDING (Manager resume, I05-C3 exit): the C2/v1 chain is fully
# retired — nothing in this API references it any more.
C3_DECISION_SHA256 = "d289929d948ddfa7ae961810c47e43d4e1a37bda8aea21074c5a7df8c13063e9"
#: Repo-relative path of the frozen decision document (resolved against the
#: effective project root at request time).
C3_DECISION_RELPATH = (
    "output/s09/20260823_sprint_full/t00-i05-c3/route_decisions_c3_seed20260823.json"
)
#: Exact content SHA-256 of the frozen I03-C3 run_A benchmark document the
#: decision was measured from (the pin callers must supply and re-verify).
C3_BENCHMARK_CONTENT_SHA256 = "12de134527765da2b3a2e890dc7a8d693c43b8325c2f8e122eb8886783d038c3"


def _sha256_file(path: Path) -> str:
    """Content SHA-256 of one file (streamed; never materialised in RAM)."""
    digest = hashlib.sha256()
    with open(_win_long_path(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _c3_decision_path() -> Path:
    """Resolve the frozen C3 decision document (override wins over root).

    Resolution order mirrors _repo_root(): an explicit MOTIONFORGE_S09_DECISION_DIR
    (QA/e2e launcher + tests stage the frozen pair into their isolated root)
    wins; otherwise the decision resolves against the effective project root
    exactly like any other repo artifact.
    """
    override = os.environ.get("MOTIONFORGE_S09_DECISION_DIR")
    if override:
        return Path(override) / "route_decisions_c3_seed20260823.json"
    return _repo_root() / C3_DECISION_RELPATH


def _pinned_evidence(
    benchmark_results: str,
    expect_content_sha256: str | None = None,
) -> tuple[BenchmarkResultsDocument, list[dict[str, Any]], str]:
    """Bind the benchmark document to the EXACT frozen C3 decision (closed).

    S09-T04-C3 FINAL binding (Manager resume, I05-C3 exit): every T04
    surface pins the I05-C3 route-decision document by its frozen SHA
    (``C3_DECISION_SHA256``).  Before ANY route-relevant byte is used this
    helper verifies, in order:

    1. The explicitly configured benchmark path EXISTS (else 422 — no
       default/fallback evidence is allowed anywhere in this API);
    2. An optionally supplied ``expect_content_sha256`` still matches the
       on-disk bytes (else 409 STALE — TOCTOU guard for callers that took
       the pin earlier);
    3. The FROZEN C3 DECISION document exists on disk and hashes EXACTLY to
       ``C3_DECISION_SHA256`` (else 409/422 — a missing or mutated decision
       can never authorize planning);
    4. The decision's embedded ``i03_run_A.file_sha256`` names THIS exact
       benchmark document (else 409 — the document being read is not the
       measured input of the pinned decision).
    """
    path = Path(benchmark_results)
    if not path.is_file():
        raise HTTPException(
            422,
            "benchmark evidence missing: no document at the explicitly "
            f"configured path {benchmark_results!r} "
            "(S09-T04-C3: no default/fallback evidence is allowed)",
        )
    if expect_content_sha256 is not None:
        actual = _sha256_file(path)
        if actual != expect_content_sha256:
            raise HTTPException(
                409,
                "benchmark evidence stale: pinned content sha256 does not "
                f"match the document bytes now on disk (expected "
                f"{expect_content_sha256}, got {actual}). Re-pin from the "
                "current frozen decision before planning routes.",
            )
    # ── Exact C3 decision binding (fail closed) ──────────────────────
    decision_path = _c3_decision_path()
    if not decision_path.is_file():
        raise HTTPException(
            422,
            "frozen C3 route-decision document missing: "
            f"{decision_path} (pin {C3_DECISION_SHA256[:16]}…) — refusing "
            "to serve capabilities without the exact C3 identity",
        )
    decision_sha = _sha256_file(decision_path)
    if decision_sha != C3_DECISION_SHA256:
        raise HTTPException(
            409,
            "frozen C3 route-decision drifted: on-disk decision hashes "
            f"{decision_sha}, expected {C3_DECISION_SHA256} — refusing",
        )
    try:
        with open(_win_long_path(decision_path), "rb") as _df:
            decision = json.loads(_df.read().decode("utf-8"))
    except (OSError, ValueError) as err:
        raise HTTPException(422, f"frozen C3 route-decision unreadable: {err}") from err
    bench_input_sha = str(
        ((decision.get("independent_verification") or {}).get("i03_run_A") or {}).get(
            "content_sha256"
        )
        or ""
    )
    this_bench_sha = _sha256_file(path)
    if bench_input_sha and bench_input_sha != this_bench_sha:
        raise HTTPException(
            409,
            "benchmark document is NOT the measured input of the pinned C3 "
            f"decision (decision pins {bench_input_sha[:16]}…, this "
            f"document hashes {this_bench_sha[:16]}…) — refusing",
        )
    try:
        doc = load_benchmark_results(path)
    except BenchmarkResultsError as err:
        raise HTTPException(422, f"benchmark evidence unusable: {err}") from err
    raw = doc._payload.get("results")  # noqa: SLF001 - single-owner module view
    if not isinstance(raw, list):
        raise HTTPException(422, "benchmark document 'results' is not a list")
    return doc, [r for r in raw if isinstance(r, dict)], _sha256_file(path)


def _frozen_evidence_identity(
    benchmark_results: str,
) -> tuple[dict[str, Any], str]:
    """SERVER-side frozen-evidence identity for generation binding (§4.4).

    S09-T04-C4-PREP (review C3 F4): the regeneration identity must fold in
    ONE machine value covering the EXACT frozen evidence — never a
    caller-trusted SHA.  This helper re-verifies the evidence through
    :func:`_pinned_evidence` (which already fail-closes on missing/mutated/
    mismatched bytes) and then derives a canonical identity object:

    - ``decision_sha256``: the exact I05-C3 decision document SHA
      (d289929d…), re-hashed from on-disk bytes;
    - ``benchmark_content_sha256``: content SHA of the measured run-A
      document being read (12de1345…), cross-checked against the decision's
      embedded ``i03_run_A.content_sha256`` by ``_pinned_evidence``;
    - ``run_b_content_sha256``: the decision's embedded I03-C3 run-B
      content identity (dab37e41…) — part of the frozen chain.

    Returns ``(canonical_object, frozen_evidence_sha256)`` where the SHA is
    the canonical JSON hash of that object.  Callers pass ONLY this derived
    value into ``regen_fingerprint``; no client-supplied hash is ever an
    authority.
    """
    _doc, _rows, bench_sha = _pinned_evidence(benchmark_results)
    decision_path = _c3_decision_path()
    try:
        with open(_win_long_path(decision_path), "rb") as _df2:
            decision = json.loads(_df2.read().decode("utf-8"))
    except (OSError, ValueError) as err:
        raise HTTPException(422, f"frozen C3 route-decision unreadable: {err}") from err
    iv = decision.get("independent_verification") or {}
    run_a = iv.get("i03_run_A") or {}
    run_b = iv.get("i03_run_B") or {}
    bench_input_sha = str(run_a.get("content_sha256") or "")
    if not bench_input_sha or bench_input_sha != bench_sha:
        # Defensive double-check: _pinned_evidence already refuses this,
        # but this identity must NEVER be derived from unverified input.
        raise HTTPException(
            409,
            "frozen-evidence identity refused: benchmark document does not "
            "match the pinned C3 decision's measured input",
        )
    canonical_obj: dict[str, Any] = {
        "decision_sha256": C3_DECISION_SHA256,
        "benchmark_content_sha256": bench_input_sha,
        "run_b_content_sha256": str(run_b.get("content_sha256") or ""),
    }
    canonical_bytes = json.dumps(canonical_obj, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return canonical_obj, hashlib.sha256(canonical_bytes).hexdigest()


# ── GET /capabilities ────────────────────────────────────────────────────────


@router.get("/capabilities", status_code=200)
@router.get("/capabilities/", status_code=200)
def get_capabilities(
    benchmark_results: str,
    expect_content_sha256: str | None = Query(default=None),
) -> CapabilitiesResponse:
    doc, raw_rows, content_sha256 = _pinned_evidence(benchmark_results, expect_content_sha256)
    classes: list[BenchmarkClassSummary] = []
    seen_classes: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        cls = str(row.get("risk_class", ""))
        if not cls or cls in seen_classes:
            continue
        seen_classes.add(cls)
        rows = [
            BenchmarkRouteRow(
                fixture_id=str(r.get("fixture_id", "")),
                risk_class=cls,
                route=str(r.get("route", "")),
                overall_pass=(
                    isinstance(r.get("threshold_evaluation"), dict)
                    and r["threshold_evaluation"].get("overall_pass") is True
                ),
                checks=(
                    r["threshold_evaluation"].get("checks", [])
                    if isinstance(r.get("threshold_evaluation"), dict)
                    else []
                ),
            )
            for r in doc.rows_for_class(cls)
        ]
        classes.append(
            BenchmarkClassSummary(
                risk_class=cls,
                measured_routes=rows,
                smallest_passing_route=doc.smallest_passing_route(cls),
            )
        )
    return CapabilitiesResponse(
        benchmark_results=str(doc.path),
        content_sha256=content_sha256,
        frozen_content_sha256=doc.frozen_content_sha256,
        thresholds_policy=doc.thresholds_policy,
        routes_measured=doc.routes,
        classes=classes,
    )


# ── POST /jobs ───────────────────────────────────────────────────────────────


def _manifest_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ensure_demo_pipeline(svc: Any) -> None:
    """Make the submitted job RUN: handler registered + worker started.

    The T03 contract leaves ``register_s09_demo_loop_handler`` to the caller
    (tests do it explicitly); a UI submission has no test harness around it,
    so this read-only-ish wiring step guarantees the durable worker picks the
    job up.  Both operations are idempotent (registration is id()-keyed;
    ``start_worker`` guards re-entry).
    """
    _register_handler()
    worker = getattr(svc, "_worker", None)
    if worker is not None and not svc.worker_running:
        svc.start_worker()


@router.post("/jobs", status_code=201)
@router.post("/jobs/", status_code=201)
def submit_demo_compare_job(
    body: DemoCompareJobRequest, response: Response
) -> DemoCompareJobCreated:
    # Fail-closed evidence binding BEFORE anything durable happens: the pin
    # (when supplied) is verified against the on-disk bytes and the SAME
    # verification is embedded in the idempotency fingerprint, so a stale
    # pin can never silently reuse a job planned from different evidence.
    _pinned_evidence(body.benchmark_results, body.expect_content_sha256)
    svc = get_job_service()
    payload_manifest: dict[str, object] = {
        "requested_loops": list(body.requested_loops),
        "benchmark_results": body.benchmark_results,
        "expect_content_sha256": body.expect_content_sha256,
        # Exact C2 decision binding travels WITH the job so the worker-side
        # planner re-verifies the SAME frozen identity at execution time
        # (no plan may ever run on unverified or drifted evidence).
        "route_decision_path": str(_c3_decision_path()),
        "expected_frozen_sha256": C3_DECISION_SHA256,
        "fixtures_dir": body.fixtures_dir,
        "pinned_routes": dict(body.pinned_routes or {}),
        "workspace_id": WORKSPACE_ID,
    }
    fingerprint = _manifest_fingerprint(payload_manifest)
    # SAME derivation as the T03 route → equivalent submissions through
    # either surface reuse ONE durable Job (contract §3 identity).
    idempotency_key = f"S09_DEMO_LOOP:{fingerprint[:32]}"
    try:
        info = svc.create_job(
            JOB_TYPE_S09_DEMO_LOOP,
            {
                **payload_manifest,
                "benchmark_results": str(body.benchmark_results),
                "fixtures_dir": str(body.fixtures_dir),
            },
            workspace_id=WORKSPACE_ID,
            owner_type="project",
            owner_id=WORKSPACE_ID,
            idempotency_key=idempotency_key,
        )
        state_val = info.state.value if hasattr(info.state, "value") else str(info.state)
        reused = state_val == "completed"
    except Exception as err:  # IdempotencyKeyInUse surfaces as 409 below
        if type(err).__name__ == "IdempotencyKeyInUse":
            raise HTTPException(
                409,
                "an active demo-loop job with an equivalent payload already exists",
            ) from err
        raise HTTPException(422, f"submission refused: {err}") from err
    _ensure_demo_pipeline(svc)
    response.status_code = 200 if reused else 201
    return DemoCompareJobCreated(
        job_id=info.job_id,
        status=state_val,
        reused=reused,
        detail_url=f"/api/v2/s09-demo-compare/jobs/{info.job_id}",
    )


# ── POST /jobs/{base_job_id}/regenerate (S09-T04-C3, §3.2) ───────────────────


def _regeneration_session(svc: Any) -> Any:
    """A durable session from the JobService's own factory.

    The T05A repository is a pure-read surface on the SAME durable
    database the jobs live in — one session per request, closed by the
    caller via the ``with`` block.
    """
    factory = svc.session_factory
    if factory is None:
        raise HTTPException(500, "durable session factory unavailable")
    return factory()


@router.post(
    "/jobs/{base_job_id:uuid}/regenerate",
    status_code=201,
    response_model=RegenerateJobCreated,
)
@router.post(
    "/jobs/{base_job_id:uuid}/regenerate/",
    status_code=201,
    response_model=RegenerateJobCreated,
)
def regenerate_demo_compare_job(
    base_job_id: uuid.UUID,
    body: RegenerateJobRequest,
    response: Response,
) -> RegenerateJobCreated:
    """Submit ONE targeted regeneration Job for an applied correction.

    Real end-to-end wiring (J1-C3 open):

    1. Load the immutable applied-regeneration context through the REAL
       T05A service (``S09CorrectionRepository.
       applied_regeneration_context`` — caller NEVER supplies affected
       scope or context; unknown → 404, non-applied/stale → 409,
       malformed archive → 422);
    2. Verify the base job: exists in this workspace, type ==
       s09_demo_loop, and COMPLETED (the T03 regen handler refuses any
       other state — refuse identically here so the API contract matches
       the durable one exactly);
    3. Verify affected loop IDs are a SUBSET of the base requested loops;
    4. Re-verify the exact benchmark content pin against on-disk bytes;
    5. Submit an S09_DEMO_REGEN manifest for the T03 handler with the
       canonical context + pinned context SHA, idempotency derived from
       ``regen_fingerprint(base_job_id, context_sha,
       frozen_evidence_sha256)`` — the SAME three-field key the worker-side
       helper derives (contract C4 §4.4), so replay through ANY surface
       returns ONE durable generation identity bound to the EXACT frozen
       evidence.

    Zero durable mutation happens when any validation step fails — every
    refusal below raises BEFORE ``create_job`` is reached.
    """
    svc = get_job_service()

    # ── 1. Immutable correction context via the REAL T05A service ───────
    with _regeneration_session(svc) as session:
        repo = S09CorrectionRepository(session)
        try:
            ctx = repo.applied_regeneration_context(WORKSPACE_ID, body.correction_id)
        except CorrectionNotFoundError as err:
            raise HTTPException(404, f"correction {body.correction_id!r} not found") from err
        except CorrectionConflictError as err:
            raise HTTPException(409, str(err)) from err
        except CorrectionValidationError as err:
            raise HTTPException(422, str(err)) from err

    affected_loops: list[str] = [str(x) for x in ctx["affected_loop_ids"]]
    context_sha = str(ctx["context_sha256"])
    # Canonical context WITHOUT the embedded sha — exactly what the T03
    # handler re-hashes fail-closed at execution time.
    context_payload: dict[str, Any] = {k: v for k, v in ctx.items() if k != "context_sha256"}

    # ── 2. Base job: ours, demo-loop type, COMPLETED ────────────────────
    try:
        info = svc.get_job(str(base_job_id))
    except Exception:
        info = None
    if info is None:
        raise HTTPException(404, f"base job {base_job_id} not found")
    if info.job_type != JOB_TYPE_S09_DEMO_LOOP:
        raise HTTPException(400, f"not a {JOB_TYPE_S09_DEMO_LOOP} job")
    with _regeneration_session(svc) as read_session:
        record = JobRepository(read_session).get_job(str(base_job_id))
    if record.workspace_id != WORKSPACE_ID:
        raise HTTPException(404, f"base job {base_job_id} not found")
    if record.state != "completed":
        raise HTTPException(
            409,
            f"base job is {record.state!r}; targeted regeneration requires a COMPLETED base",
        )
    manifest = dict(record.input_manifest) if isinstance(record.input_manifest, dict) else {}
    base_benchmark = str(manifest.get("benchmark_results", ""))
    base_fixtures = str(manifest.get("fixtures_dir", ""))
    base_loops = [str(x) for x in manifest.get("requested_loops", [])]
    if not base_loops:
        raise HTTPException(409, "base job manifest lacks requested_loops")

    # ── 3. Affected scope ⊆ base requested loops (fail closed) ──────────
    outside = sorted(set(affected_loops) - set(base_loops))
    if outside:
        raise HTTPException(
            422,
            f"affected loop ids are NOT a subset of the base requested loops: {outside}",
        )

    # ── 4. Exact benchmark evidence pin re-verified NOW ─────────────────
    if not base_benchmark:
        raise HTTPException(409, "base job manifest lacks benchmark_results")
    _pinned_evidence(base_benchmark, body.expect_content_sha256)
    # C4 §4.4: derive the SERVER-side frozen-evidence identity (I05 decision
    # + measured run-A/run-B content) — the caller NEVER supplies it.
    frozen_obj, frozen_evidence_sha256 = _frozen_evidence_identity(base_benchmark)

    # ── 5. C3 manifest → T03 fingerprint → durable S09_DEMO_REGEN job ──
    payload_manifest: dict[str, object] = {
        # Targeted scope: ONLY the affected loops re-render; the handler
        # plans them under targeted=True (six-class gate waived because
        # the completed base already proved full coverage).
        "requested_loops": affected_loops,
        "benchmark_results": base_benchmark,
        "fixtures_dir": base_fixtures,
        "pinned_routes": {str(k): str(v) for k, v in (manifest.get("pinned_routes") or {}).items()},
        "workspace_id": WORKSPACE_ID,
        "managed_root": str(svc.managed_root),
        # Frozen-evidence binding carried verbatim from the base job so
        # the planner re-verifies the SAME decision identity at execute
        # time (anti-drift, same semantics as POST /jobs).
        "route_decision_path": (
            str(manifest.get("route_decision_path")) or str(_c3_decision_path())
        ),
        "expected_frozen_sha256": (
            str(manifest.get("expected_frozen_sha256") or C3_DECISION_SHA256)
        ),
        # ── T03 regen-handler contract fields ───────────────────────────
        "base_job_id": str(base_job_id),
        "correction_context": context_payload,
        "correction_context_sha256": context_sha,
        # C4 §4.4: the SERVER-derived frozen-evidence identity travels with
        # the job so any surface can re-derive/re-bind the SAME generation.
        "frozen_evidence_object": frozen_obj,
        "frozen_evidence_sha256": frozen_evidence_sha256,
    }
    idempotency_key = regen_fingerprint(
        base_job_id=str(base_job_id),
        correction_context_sha256=context_sha,
        frozen_evidence_sha256=frozen_evidence_sha256,
    )
    try:
        created_info = svc.create_job(
            JOB_TYPE_S09_DEMO_REGEN,
            payload_manifest,
            workspace_id=WORKSPACE_ID,
            owner_type="project",
            owner_id=WORKSPACE_ID,
            idempotency_key=idempotency_key,
        )
        # Replay semantics §3.2 (review C3 F2): the repository returns an
        # EXISTING COMPLETED job directly for a duplicate key (contract
        # §8.1) WITHOUT raising; only ACTIVE blockers raise InUse.  The
        # freshly-inserted branch can never be terminal at return time
        # (the worker runs async), so a completed state here IS the replay
        # signal — same identity, reused=true, 200.
        created_state = (
            created_info.state.value
            if hasattr(created_info.state, "value")
            else str(created_info.state)
        )
        reused = created_state == "completed"
        created_id = created_info.job_id
    except IdempotencyKeyInUse as err:
        # Replay semantics §3.2: same base + same applied correction →
        # SAME job identity.  A completed blocker is returned directly by
        # the repository; an ACTIVE one (queued/running/pending) raises
        # InUse carrying its id — resolve it read-only and return it.
        existing_id = getattr(err, "job_id", None)
        if not existing_id:
            raise HTTPException(409, str(err)) from err
        try:
            existing = svc.get_job(str(existing_id))
        except Exception:
            existing = None
        if existing is None or existing.job_type != JOB_TYPE_S09_DEMO_REGEN:
            raise HTTPException(409, str(err)) from err
        reused = True
        created_id = existing.job_id
    _ensure_demo_pipeline(svc)

    final = svc.get_job(created_id)
    if final is None:  # pragma: no cover - the job was just created/replayed
        raise HTTPException(500, f"regeneration job {created_id} vanished")
    state_val = final.state.value if hasattr(final.state, "value") else str(final.state)
    # Replay is signalled EITHER by the repository's completed-return path
    # (reused already true) OR by an InUse blocker resolution — never by
    # guessing from state after a fresh insert (review C3 F2).
    response.status_code = 200 if reused else 201
    return RegenerateJobCreated(
        job_id=created_id,
        state=state_val,
        reused=reused,
        base_job_id=str(base_job_id),
        correction_id=str(ctx["correction_id"]),
        correction_context_sha256=context_sha,
        frozen_evidence_sha256=frozen_evidence_sha256,
        affected_loop_ids=affected_loops,
        detail_url=f"/api/v2/s09-demo-compare/jobs/{created_id}",
    )


# ── GET /loops ───────────────────────────────────────────────────────────────


def _loop_response(
    fixture_root: Path,
    loop_id: str,
    index_entry: dict[str, Any],
    joint_plan: dict[str, Any] | None,
    plan_error: str | None,
) -> LoopManifestResponse:
    """Build one loop's read model from its REAL manifest + planner output."""
    manifest_path = fixture_root / "manifests" / f"{loop_id}.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, f"loop manifest unreadable for {loop_id!r}") from None
    media_rel = str(index_entry.get("media_path", f"media/{loop_id}.mp4"))
    media = fixture_root / media_rel
    if not media.is_file():
        raise HTTPException(404, f"loop media missing for {loop_id!r}")
    probe = _probe_dimensions(media)
    program = payload.get("replacement_program")
    ops = (
        [str(e.get("op")) for e in program if isinstance(e, dict) and e.get("op")]
        if isinstance(program, list)
        else []
    )
    classes = [str(c) for c in payload.get("risk_classes", []) if isinstance(c, str)]
    routes: dict[str, str] | None = None
    if joint_plan is not None:
        for e in joint_plan["loops"]:
            if str(e["loop_id"]) == loop_id:
                routes = {str(k): str(v) for k, v in e["routes_by_risk_class"].items()}
    return LoopManifestResponse(
        loop_id=loop_id,
        frame_count=int(index_entry.get("frame_count", payload.get("frame_count", 0))),
        fps=float(payload.get("fps", 30)),
        width=int(probe.get("width", 0)),
        height=int(probe.get("height", 0)),
        segments=[
            LoopSegment(
                shot_id=str(s.get("shot_id", "")),
                start_frame=int(s.get("start_frame", 0)),
                end_frame=int(s.get("end_frame", 0)),
            )
            for s in payload.get("segments", [])
            if isinstance(s, dict)
        ],
        risk_classes=classes,
        replacement_ops=ops,
        routes_by_risk_class=routes,
        plan_error=plan_error,
    )


def _probe_dimensions(media: Path) -> dict[str, int]:
    """Real dimensions via ffprobe (never assumed from the manifest)."""
    import subprocess

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(media),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise HTTPException(500, f"ffprobe failed for {media.name}")
    payload = json.loads(proc.stdout.decode("utf-8", "replace"))
    streams = payload.get("streams") or [{}]
    s0 = streams[0] if streams else {}
    return {"width": int(s0.get("width", 0)), "height": int(s0.get("height", 0))}


@router.get("/loops", status_code=200)
@router.get("/loops/", status_code=200)
def list_loops(
    fixtures_dir: str,
    benchmark_results: str,
    expect_content_sha256: str | None = Query(default=None),
) -> LoopListResponse:
    # Anti-TOCTOU: the SAME pinned-bytes verification runs here BEFORE the
    # planner resolves routes, so capabilities/loops/submit can never mix
    # route decisions from two different evidence documents.
    _pinned_evidence(benchmark_results, expect_content_sha256)
    fixture_root = Path(fixtures_dir)
    index_path = fixture_root / "loops_index.json"
    if not index_path.is_file():
        raise HTTPException(404, f"loops index missing under {fixtures_dir}")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise HTTPException(422, f"unreadable loops index: {err}") from err
    loops_raw = index.get("loops")
    if not isinstance(loops_raw, list):
        raise HTTPException(422, "loops index has no 'loops' list")
    # Resolve planned routes ONCE through the fail-closed planner over ALL
    # indexed loops (joint coverage holds); a planner refusal is disclosed
    # per loop as plan_error — routes stay null, never invented.
    joint_plan: dict[str, Any] | None = None
    plan_error: str | None = None
    try:
        joint_plan = build_demo_plan(
            requested_loops=[
                str(e["loop_id"]) for e in loops_raw if isinstance(e, dict) and e.get("loop_id")
            ],
            benchmark_results=Path(benchmark_results),
            fixture_root=fixture_root,
        )
    except Exception as err:
        plan_error = str(err)
    out: list[LoopManifestResponse] = []
    for entry in loops_raw:
        if not isinstance(entry, dict) or not entry.get("loop_id"):
            continue
        out.append(
            _loop_response(
                fixture_root,
                str(entry["loop_id"]),
                entry,
                joint_plan,
                plan_error,
            )
        )
    return LoopListResponse(loops=out)


# ── GET /jobs/{job_id} ───────────────────────────────────────────────────────


def _route_evidence_from_manifest(svc: Any, manifest: dict[str, Any]) -> list[RouteEvidenceEntry]:
    """Persisted SegmentRenderRoute rows referenced by the job manifest.

    Only real rows are returned: when the manifest carries no reskin config
    reference (the pure demo-loop case), the result is an EMPTY list — the
    UI renders its empty state instead of a fabricated per-segment story.
    """
    config_id = manifest.get("reskin_config_id")
    if not isinstance(config_id, str) or not config_id:
        return []
    factory = svc.session_factory
    if factory is None:
        return []
    from app.persistence.reskin_config import ReskinConfigRepository

    with factory() as session:
        repo = ReskinConfigRepository(session)
        try:
            rows = repo.list_renderer_route_evidence(WORKSPACE_ID, config_id)
        except Exception:
            return []
    return [
        RouteEvidenceEntry(
            occurrence_segment_id=str(r["occurrence_segment_id"]),
            route=str(r["route"]),
            anchor_x=float(r["anchor"]["x"]),
            anchor_y=float(r["anchor"]["y"]),
            start_frame=int(r["start_frame"]),
            end_frame=int(r["end_frame"]),
            confidence=float(r["confidence"]),
            confidence_source=str(r["confidence_source"]),
            reasons=[str(x) for x in r.get("reasons", [])],
            provenance=r.get("provenance"),
        )
        for r in rows
    ]


@router.get("/jobs/{job_id:uuid}", status_code=200)
@router.get("/jobs/{job_id:uuid}/", status_code=200)
def get_demo_compare_status(job_id: uuid.UUID) -> DemoCompareStatus:
    svc = get_job_service()
    info = svc.get_job(str(job_id))
    if info is None:
        raise HTTPException(404, "Job not found")
    if info.job_type not in {JOB_TYPE_S09_DEMO_LOOP, JOB_TYPE_S09_DEMO_REGEN}:
        raise HTTPException(400, f"not a {JOB_TYPE_S09_DEMO_LOOP} job")
    requested: list[str] = []
    frozen: str | None = None
    policy: str | None = None
    covered: list[str] = []
    published: list[PublishedArtifact] = []
    evidence: list[RouteEvidenceEntry] = []
    gen_evidence: GenerationEvidence | None = None
    affected_loop_ids: list[str] = []
    publications: list[PublicationStatus] = []
    factory = svc.session_factory
    if factory is not None:
        with factory() as session:
            repo = JobRepository(session)
            record = repo.get_job(str(job_id))
            manifest = record.input_manifest if isinstance(record.input_manifest, dict) else {}
            requested = [str(x) for x in manifest.get("requested_loops", [])]
            attempts = repo.list_attempts(str(job_id))
            result_payload: dict[str, object] | None = None
            for attempt in reversed(attempts):
                raw = getattr(attempt, "result", None)
                if isinstance(raw, dict):
                    result_payload = raw
                    break
            if result_payload is not None:
                plan_raw = result_payload.get("plan")
                if isinstance(plan_raw, dict):
                    covered = [str(c) for c in plan_raw.get("covered_risk_classes", [])]
                    frozen = (
                        str(plan_raw["frozen_content_sha256"])
                        if plan_raw.get("frozen_content_sha256")
                        else None
                    )
                    policy = (
                        str(plan_raw["thresholds_policy"])
                        if plan_raw.get("thresholds_policy") is not None
                        else None
                    )
                pub_raw = result_payload.get("published")
                if isinstance(pub_raw, dict):
                    for lid, ev in sorted(pub_raw.items()):
                        if not isinstance(ev, dict):
                            continue
                        rel = str(ev.get("relative_path", ""))
                        sha = str(ev.get("sha256", ""))
                        published.append(
                            PublishedArtifact(
                                loop_id=str(lid),
                                relative_path=rel,
                                content_url=(f"/api/v2/s09-demo-compare/content/{lid}/{sha}"),
                                artifact_id=str(ev.get("artifact_id", "")),
                                sha256=sha,
                                size_bytes=int(ev.get("size_bytes", 0)),
                                frame_count=(
                                    int(ev["frame_count"])
                                    if ev.get("frame_count") is not None
                                    else None
                                ),
                                reused_existing_file=(
                                    bool(ev["reused_existing_file"])
                                    if ev.get("reused_existing_file") is not None
                                    else None
                                ),
                            )
                        )
                # C4 §4.5 (review C3 F6): regen-only READ model mapped from
                # the immutable attempt result — the producer's stamps are
                # the ONLY authority; this API never infers `regenerated`
                # from hash equality.
                gen_evidence, affected_loop_ids, publications = _regeneration_evidence_read_model(
                    result_payload
                )
            evidence = _route_evidence_from_manifest(svc, manifest)
    state_val = info.state.value if hasattr(info.state, "value") else str(info.state)
    return DemoCompareStatus(
        job_id=info.job_id,
        state=state_val,
        progress=float(info.progress),
        error={"message": info.error} if info.error else None,
        requested_loops=requested,
        covered_risk_classes=covered,
        frozen_content_sha256=frozen,
        thresholds_policy=policy,
        published=published,
        route_evidence=evidence,
        generation_evidence=gen_evidence,
        affected_loop_ids=affected_loop_ids,
        publications=publications,
    )


def _regeneration_evidence_read_model(
    result_payload: dict[str, object],
) -> tuple[GenerationEvidence | None, list[str], list[PublicationStatus]]:
    """Map ONE immutable regen attempt result into the §4.5 read model.

    Pure projection over the durable attempt ``result`` written by the T03
    regen handler — no recomputation, no hash-equality inference:

    - ``generation_evidence``: copied verbatim (missing fields → absent,
      never fabricated);
    - ``affected_loop_ids``: the exact producer-stamped list;
    - per-loop ``publications``: ``regenerated``/``render_ms`` only when
      the producer stamped them; unaffected loops carry their verbatim
      base publication identity instead.
    """
    gen_raw = result_payload.get("generation_evidence")
    if not isinstance(gen_raw, dict):
        return None, [], []
    required = (
        "generation",
        "base_job_id",
        "correction_id",
        "correction_context_sha256",
        "frozen_evidence_sha256",
    )
    if any(gen_raw.get(k) is None for k in required):
        return None, [], []
    gen_evidence = GenerationEvidence(
        generation=str(gen_raw["generation"]),
        base_job_id=str(gen_raw["base_job_id"]),
        correction_id=str(gen_raw["correction_id"]),
        correction_context_sha256=str(gen_raw["correction_context_sha256"]),
        frozen_evidence_sha256=str(gen_raw["frozen_evidence_sha256"]),
    )
    affected_raw = result_payload.get("affected_loop_ids")
    affected = [str(x) for x in affected_raw] if isinstance(affected_raw, list) else []
    publications: list[PublicationStatus] = []
    pub_raw = result_payload.get("published")
    if isinstance(pub_raw, dict):
        for lid, ev in sorted(pub_raw.items()):
            if not isinstance(ev, dict):
                continue
            regenerated = ev.get("regenerated")
            base_pub: PublicationIdentity | None = None
            if regenerated is False:
                # §4.5: unaffected loops carry their BASE publication
                # identity.  Two durable shapes are accepted, both copied
                # verbatim from the immutable attempt result: an explicit
                # nested ``base_publication`` object, or (the current T03
                # bind-phase shape) the reused BASE entry itself, whose own
                # identity fields ARE the base publication the handler
                # hash-verified before binding.
                base_src = ev.get("base_publication")
                if not isinstance(base_src, dict):
                    base_src = ev
                base_pub = PublicationIdentity(
                    artifact_id=str(base_src.get("artifact_id", "")),
                    relative_path=str(base_src.get("relative_path", "")),
                    sha256=str(base_src.get("sha256", "")),
                    size_bytes=int(base_src.get("size_bytes", 0)),
                )
            publications.append(
                PublicationStatus(
                    loop_id=str(lid),
                    regenerated=bool(regenerated) if regenerated is not None else None,
                    render_ms=(int(ev["render_ms"]) if ev.get("render_ms") is not None else None),
                    base_publication=base_pub,
                )
            )
    return gen_evidence, affected, publications


# ── GET /content/{loop_id}/{sha256} ──────────────────────────────────────────


def _win_long_path(path: Path) -> str:
    """Extended-length (\\\\?\\) form of *path* for Windows filesystem calls.

    S09-T04-C3 (review C2 F4, P1): published artifacts legitimately exceed
    the 260-char MAX_PATH limit (deep managed roots × content-addressed
    names).  The T03 writer already uses this exact helper; the READER here
    must be long-path safe too — a plain ``Path.is_file()`` returns False
    and ``FileResponse`` raises past MAX_PATH even when the MP4 exists.
    Mirrors ``app.workflow.s09_demo_jobs._win_long_path`` (kept in sync by
    tests); on non-Windows it is a no-op passthrough.
    """
    raw = str(path)
    if os.name != "nt" or raw.startswith("\\\\?\\"):
        return raw
    # The \\?\ form rejects drive-relative paths — resolve to absolute first.
    if not Path(raw).is_absolute():
        raw = str(Path(raw).resolve())
    # UNC paths need \\?\UNC\<share> instead of \\?\<drive>.
    if raw.startswith("\\\\/"):
        return "\\\\?\\UNC\\" + raw[2:]
    return "\\\\?\\" + raw


def _longpath_is_file(path: Path) -> bool:
    """``is_file()`` that survives absolute paths beyond MAX_PATH."""
    try:
        return os.path.isfile(_win_long_path(path))
    except OSError:
        return False


def _resolve_published_path(svc: Any, loop_id: str, sha256: str) -> Path:
    """Containment-checked managed path for a published loop artifact.

    The path is recomputed from the workspace/loop/sha triple exactly like
    the T03 publisher — the client never supplies a raw filesystem path and
    ManagedRoot containment still guards the final open.

    C2: the T03 publisher's managed-relative layout dropped its redundant
    leading ``artifacts/`` segment (review F6 — the managed root already IS
    the artifacts directory); this reader mirrors ``_final_relative_path``
    so served URLs resolve to the real published file.

    C3 (review C2 F4): BOTH the existence probe and the FileResponse open
    run through Win32 extended-length paths so serving works at >=260.
    """
    final_rel = f"s09-demo-loops/{WORKSPACE_ID}/{loop_id}/{sha256}.mp4"
    managed = ManagedRoot(Path(str(svc.managed_root)))
    try:
        candidate = managed.resolve(final_rel)
    except Exception as err:
        raise HTTPException(404, "no such managed artifact") from err
    if not _longpath_is_file(candidate):
        raise HTTPException(404, f"artifact not published for loop {loop_id!r}")
    return candidate


@router.get("/content/{loop_id}/{sha256}", status_code=200)
@router.get("/content/{loop_id}/{sha256}/", status_code=200)
def get_demo_content(loop_id: str, sha256: str) -> FileResponse:
    if not loop_id or "/" in loop_id or "\\" in loop_id:
        raise HTTPException(422, "invalid loop id")
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256.lower()):
        raise HTTPException(422, "invalid content sha256")
    svc = get_job_service()
    path = _resolve_published_path(svc, loop_id.lower(), sha256.lower())
    return FileResponse(_win_long_path(path), media_type="video/mp4")


# ── GET /source-content/{loop_id} ────────────────────────────────────────────


def _repo_root() -> Path:
    """The effective project root (deps-injected config wins over default).

    Mirrors ``app.workflow.job_service._project_root``: tests patch
    ``deps._config.project_root`` to a temp tree, so reading the module
    default directly would ignore the injection and resolve containment
    against the wrong tree.
    """
    try:
        from app.api import deps  # noqa: PLC0415

        return Path(deps._config.project_root)
    except Exception:  # pragma: no cover - config always importable
        from app.config import config as _cfg

        return Path(str(_cfg.project_root))


@router.get("/source-content/{loop_id}", status_code=200)
@router.get("/source-content/{loop_id}/", status_code=200)
def get_demo_source_content(loop_id: str, fixtures_dir: str) -> FileResponse:
    """Serve the ORIGINAL fixture media for one loop (comparison left pane).

    Containment contract: *fixtures_dir* must resolve to a directory inside
    the configured project root AND the loop id must be a bare filename —
    the joined path is re-validated with ``resolve()`` before any open, so a
    hostile query string can never escape the repo tree.
    """
    if not loop_id or "/" in loop_id or "\\" in loop_id or ".." in loop_id:
        raise HTTPException(422, "invalid loop id")
    root = _repo_root().resolve()
    fixture_root = (root / fixtures_dir).resolve()
    if fixture_root != root and root not in fixture_root.parents:
        raise HTTPException(422, "fixtures_dir escapes the project root")
    media = (fixture_root / "media" / f"{loop_id}.mp4").resolve()
    if media != root and root not in media.parents:
        raise HTTPException(422, "media path escapes the project root")
    # C3 (review C2 F4): long-path safe existence + serve, same as /content.
    if not _longpath_is_file(media):
        raise HTTPException(404, f"source media not found for loop {loop_id!r}")
    return FileResponse(_win_long_path(media), media_type="video/mp4")


# Re-exported for tests asserting the step plan parity with T03.
DEMO_STEP_CODES = [s.step_code for s in demo_loop_steps()]
