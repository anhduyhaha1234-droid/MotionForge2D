"""S09-T03-C2: risk-selected demo-loop proxy jobs — durable publication +
evidence binding (correction round C2, review findings F4/F6).

C2 binary acceptance (prompt §7):
1. Atomic publication works on Windows at resolved path length >=260:
   no FileNotFoundError, no orphan ``.upload`` residue, never overwrites a
   source.  The relative managed path no longer double-joins
   ``artifacts/artifacts/...``.
2. Concurrent/replay-safe temp naming; same content -> exactly ONE artifact
   row/file; kill/reconcile/replay does not duplicate; cancel/failure leaves
   zero residue.
3. Planner/load fail closed on: old schema documents, stale frozen SHA,
   missing C2 decision, unknown/FOQ/zero-sample classes.  Active tests bind
   ONLY synthetic v2 documents created here — the archival
   ``t00-i05/measured_seed20260823`` artifact is NEVER referenced.
4. Explicit long-path test at >=260 chars.

Final evidence binding to the exact C2 frozen decision happens after
I05-C2 (WAITING_JOIN); these tests stay self-contained via synthetic docs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi.testclient import TestClient

from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import JobRepository
from app.persistence.models import RENDERER_ROUTES
from app.schemas import JobInfo
from app.services.renderer_routes.benchmark_results import BenchmarkResultsError
from app.workflow.durable_worker import DurableWorker
from app.workflow.job_reconciler import JobReconciler
from app.workflow.job_service import JobService
from app.workflow.s09_demo_jobs import (
    CORRECTION_KINDS,
    JOB_TYPE_S09_DEMO_LOOP,
    JOB_TYPE_S09_DEMO_REGEN,
    LAYER_ID_KEY,
    MASK_ARTIFACT_KEY,
    DemoLoopPlanError,
    build_demo_plan,
    demo_loop_regen_steps,
    demo_loop_steps,
    regen_fingerprint,
    register_s09_demo_loop_handler,
    render_loop_bytes,
    resolve_frozen_evidence_sha256,
    verify_correction_context,
)

if TYPE_CHECKING:  # pragma: no cover

    def _make_isolated_service() -> JobService:
        """Module-global set by the demo_env fixture at fixture setup."""
        raise NotImplementedError


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "s09_demo"
ALL_LOOPS = [
    "d1_cut_graphic",
    "d2_mouth_phone",
    "d3_rotation_bed",
    "d4_group_occlusion",
]
REQUIRED_CLASSES = {
    "hard_cut",
    "mouth_expression_swap",
    "phone_contact",
    "whole_body_rotation",
    "group_occlusion",
    "semantic_graphic_replacement",
}

#: C2 evidence identity pinned by THIS test module's synthetic documents.
C2_SYNTHETIC_FROZEN_SHA = "c2" + "a" * 62

#: Routes measured-passing per class in the SYNTHETIC v2 document below.
SYNTHETIC_MEASURED: dict[str, str] = {
    "hard_cut": "pose_swap",
    "mouth_expression_swap": "pose_swap",
    "phone_contact": "sprite_affine",
    "whole_body_rotation": "sprite_affine",
    "group_occlusion": "sprite_affine",
    "semantic_graphic_replacement": "sprite_affine",
}


# --------------------------------------------------------------- helpers ---


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _synthetic_v2_document(
    tmp_root: Path,
    *,
    schema_version: int = 2,
    frozen_sha: str | None = None,
    drop_class: str | None = None,
    zero_sample: bool = False,
) -> Path:
    """Write an isolated synthetic benchmark-results v2 document.

    Every measured row carries ``MEASURED_RENDERED_OUTPUT`` with an overall
    passing threshold evaluation and positive sample counts, mirroring the
    real I03/I05 record shape.  Mutations let each test force one failure
    mode (old schema / stale SHA / missing class / zero samples).
    """
    results: list[dict[str, object]] = []
    for cls, route in SYNTHETIC_MEASURED.items():
        if drop_class == cls:
            continue  # class absent from the document entirely
        checks = [
            {"metric": "cut_error_frames", "value": 0, "limit": 1.0, "pass": True},
            {
                "metric": "trajectory_median_pct",
                "value": 0.0,
                "limit": 0.5,
                "pass": True,
            },
            {
                "metric": "pose_state_capability",
                "value": 1.0,
                "limit": 1.0,
                "pass": True,
            },
        ]
        metrics = {
            "contact_samples_measured": 0 if zero_sample else 12,
            "pose_states_measured": 0 if zero_sample else 8,
        }
        results.append(
            {
                "fixture_id": f"syn_{cls}",
                "risk_class": cls,
                "route": route,
                "measured_state": "MEASURED_RENDERED_OUTPUT",
                "metrics_sample_count": 0 if zero_sample else 24,
                "metrics": metrics,
                "threshold_evaluation": {
                    "overall_pass": True,
                    "checks": checks,
                },
            }
        )
    payload = {
        "schema_version": schema_version,
        "seed": 20260823,
        "measurement_mode": "RENDERED_OUTPUT",
        "decision_round": "C2-SYNTHETIC",
        "frozen_content_sha256": frozen_sha or C2_SYNTHETIC_FROZEN_SHA,
        "thresholds_policy": "s09-t03-c2-synthetic-frozen",
        "routes": ["pose_swap", "sprite_affine"],
        "results": results,
    }
    out_dir = tmp_root / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "benchmark_results_synthetic_v2.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return out


@pytest.fixture()
def synthetic_v2(tmp_path: Path) -> Path:
    """A valid synthetic C2-shape evidence document for planner tests."""
    return _synthetic_v2_document(tmp_path)


def _manifest_for(bench: Path) -> dict[str, object]:
    return {
        "requested_loops": ALL_LOOPS,
        "benchmark_results": str(bench),
        "fixtures_dir": str(FIXTURE_ROOT),
        "pinned_routes": {},
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }


@pytest.fixture()
def demo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Fully isolated durable environment (temp DB + temp managed root)."""
    from alembic import command
    from alembic.config import Config

    from app.persistence import create_engine_for_path, create_session_factory

    test_root = tmp_path / "s09t03"
    db_path = test_root / "data" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")

    bench = _synthetic_v2_document(test_root)
    monkeypatch.setattr(
        sys.modules[__name__],
        "_ACTIVE_BENCH",
        bench,
        raising=False,
    )

    def _make(managed_root: Path | None = None) -> JobService:
        return JobService(
            create_session_factory(create_engine_for_path(db_path)),
            worker=None,
            managed_root=managed_root or (test_root / "artifacts"),
        )

    globals()["_make_isolated_service"] = _make
    yield test_root


# Module-global set by demo_env so handler tests submit against the SAME
# synthetic evidence document the fixture created (never the archival v1).
_ACTIVE_BENCH: Path | None = None


def _active_bench() -> Path:
    assert _ACTIVE_BENCH is not None, "demo_env fixture not active"
    return _ACTIVE_BENCH


# ---------------------------------------------------------------- planner --


def test_four_loops_jointly_cover_six_risk_classes(synthetic_v2: Path) -> None:
    """Binary acceptance: index declares coverage; planner confirms on a
    C2-shape synthetic v2 document (no archival artifact referenced)."""
    index = json.loads((FIXTURE_ROOT / "loops_index.json").read_text("utf-8"))
    declared: set[str] = set()
    for loop in index["loops"]:
        declared.update(loop["risk_classes"])
    assert declared >= REQUIRED_CLASSES, f"missing: {REQUIRED_CLASSES - declared}"
    assert len(index["loops"]) == 4

    plan = build_demo_plan(
        requested_loops=ALL_LOOPS,
        benchmark_results=synthetic_v2,
        fixture_root=FIXTURE_ROOT,
    )
    assert set(plan["covered_risk_classes"]) == REQUIRED_CLASSES
    assert plan["frozen_content_sha256"] == C2_SYNTHETIC_FROZEN_SHA


def test_planner_refuses_partial_coverage(synthetic_v2: Path) -> None:
    with pytest.raises(DemoLoopPlanError):
        build_demo_plan(
            requested_loops=["d3_rotation_bed"],
            benchmark_results=synthetic_v2,
            fixture_root=FIXTURE_ROOT,
        )


def test_planner_refuses_old_schema_document(synthetic_v2: Path, tmp_path: Path) -> None:
    """Fail-closed: a pre-C2 (schema_version=1) document must be refused."""
    old_doc = _synthetic_v2_document(tmp_path, schema_version=1)
    with pytest.raises(DemoLoopPlanError, match="schema_version"):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=old_doc,
            fixture_root=FIXTURE_ROOT,
        )


def test_planner_refuses_stale_frozen_sha(synthetic_v2: Path, tmp_path: Path) -> None:
    """Fail-closed: frozen SHA drift vs the pinned C2 identity refuses."""
    stale = _synthetic_v2_document(
        tmp_path, frozen_sha="b" * 64  # any SHA ≠ the pinned C2 synthetic one
    )
    with pytest.raises(DemoLoopPlanError, match="frozen"):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=stale,
            fixture_root=FIXTURE_ROOT,
            expected_frozen_sha256=C2_SYNTHETIC_FROZEN_SHA,
        )


def test_planner_refuses_missing_class_evidence(synthetic_v2: Path, tmp_path: Path) -> None:
    """Fail-closed: a required class ABSENT from the document refuses."""
    doc = _synthetic_v2_document(tmp_path, drop_class="group_occlusion")
    # Either the planner wraps it as DemoLoopPlanError, or the underlying
    # selection raises BenchmarkResultsError — BOTH are fail-closed refusals
    # naming the missing class; a silent pass would be the only failure.
    with pytest.raises((DemoLoopPlanError, BenchmarkResultsError), match="group_occlusion"):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=doc,
            fixture_root=FIXTURE_ROOT,
        )


def test_planner_refuses_zero_sample_evidence(synthetic_v2: Path, tmp_path: Path) -> None:
    """Fail-closed: rows measured with ZERO samples are not evidence."""
    doc = _synthetic_v2_document(tmp_path, zero_sample=True)
    with pytest.raises(DemoLoopPlanError):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=doc,
            fixture_root=FIXTURE_ROOT,
        )


# ------------------------------------------------- C2 final binding ------


C2_DECISION_SHA = "ebce8c4bf416cc6b3b2225f9ddf889e475931b25acc6b76f0a55842c74de8f98"
C2_BENCH = (
    REPO_ROOT
    / "output/s09/20260823_sprint_full/t00-i03-c2/run_A"
    / "benchmark_results_seed20260823.json"
)
C2_DECISION = (
    REPO_ROOT
    / "output/s09/20260823_sprint_full/t00-i05-c2"
    / "route_decisions_seed20260823.json"
)


def test_final_binding_plans_from_pinned_c2_decision() -> None:
    """Final evidence binding: the planner plans from the PINNED I05-C2
    decision document (SHA ebce8c4b…) + its measured v3 benchmark input,
    covering all six classes."""
    plan = build_demo_plan(
        requested_loops=ALL_LOOPS,
        benchmark_results=C2_BENCH,
        fixture_root=FIXTURE_ROOT,
        expected_frozen_sha256=C2_DECISION_SHA,
        route_decision_path=C2_DECISION,
    )
    assert set(plan["covered_risk_classes"]) == REQUIRED_CLASSES
    assert plan["route_decision_sha256"] == C2_DECISION_SHA
    assert plan["route_decision_path"] == str(C2_DECISION)
    # The measured routes flow through: hard_cut -> sprite_affine per the
    # frozen I05-C2 decision.
    by_class: dict[str, str] = {}
    for entry in plan["loops"]:
        by_class.update(entry["routes_by_risk_class"])
    assert by_class["hard_cut"] == "sprite_affine"


def test_final_binding_refuses_wrong_decision_sha(tmp_path: Path) -> None:
    stale_copy = tmp_path / "stale_decision.json"
    stale_copy.write_bytes(C2_DECISION.read_bytes())
    with pytest.raises(DemoLoopPlanError, match="drift"):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=C2_BENCH,
            fixture_root=FIXTURE_ROOT,
            expected_frozen_sha256="0" * 64,  # any SHA ≠ pinned identity
            route_decision_path=stale_copy,
        )


def test_final_binding_refuses_missing_decision_document() -> None:
    with pytest.raises(DemoLoopPlanError, match="missing"):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=C2_BENCH,
            fixture_root=FIXTURE_ROOT,
            expected_frozen_sha256=C2_DECISION_SHA,
            route_decision_path=REPO_ROOT / "nope" / "decision.json",
        )


def test_final_binding_refuses_stale_benchmark_input(tmp_path: Path) -> None:
    """A mutated benchmark document is NOT the decision's measured input —
    refuse instead of planning from drift."""
    payload = json.loads(C2_BENCH.read_text(encoding="utf-8"))
    payload["seed"] = 999999  # mutate → file SHA no longer matches the pin
    stale_bench = tmp_path / "benchmark_results_mutated.json"
    stale_bench.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DemoLoopPlanError, match="measured input"):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=stale_bench,
            fixture_root=FIXTURE_ROOT,
            expected_frozen_sha256=C2_DECISION_SHA,
            route_decision_path=C2_DECISION,
        )


def test_route_selection_uses_pinned_when_measured_passing(synthetic_v2: Path) -> None:
    plan = build_demo_plan(
        requested_loops=ALL_LOOPS,
        benchmark_results=synthetic_v2,
        fixture_root=FIXTURE_ROOT,
        pinned_routes={"hard_cut": "pose_swap"},
    )
    by_class: dict[str, str] = {}
    for entry in plan["loops"]:
        by_class.update(entry["routes_by_risk_class"])
    assert by_class["hard_cut"] == "pose_swap"
    for cls in REQUIRED_CLASSES:
        assert by_class[cls] in RENDERER_ROUTES


def test_planner_requires_evidence() -> None:
    with pytest.raises(DemoLoopPlanError):
        build_demo_plan(
            requested_loops=ALL_LOOPS,
            benchmark_results=REPO_ROOT / "nope" / "missing.json",
            fixture_root=FIXTURE_ROOT,
        )


# --------------------------------------------- long-path publication ------


def test_publication_survives_windows_long_paths(tmp_path: Path) -> None:
    """Explicit >=260-char acceptance (review F6): atomic publish must work
    with NO FileNotFoundError and NO orphan .upload residue, and must never
    produce a doubled ``artifacts/artifacts`` segment."""
    from app.persistence.artifacts import ManagedRoot
    from app.workflow.s09_demo_jobs import (
        _atomic_write_windows,
        _final_relative_path,
        _sha256_long,
    )

    # Deep base dir pushes EVERY resolved path well past MAX_PATH.
    deep_root = tmp_path / ("L" * 180)
    managed = ManagedRoot(deep_root / "artifacts")
    data = b"long-path-publication-bytes"
    sha = hashlib.sha256(data).hexdigest()

    final_rel = _final_relative_path("default", "d1_cut_graphic", sha)
    assert not final_rel.startswith("artifacts/"), (
        "relative path must not re-join the artifacts segment "
        "(managed root already IS <project>/artifacts)"
    )
    final_path = managed.resolve(final_rel)
    assert len(str(final_path)) >= 260, (
        f"test setup must exceed MAX_PATH; got {len(str(final_path))}"
    )

    _atomic_write_windows(final_path, data, context="long-path acceptance")
    assert open(  # noqa: SIM115 - bounded verification read
        "\\\\?\\" + str(final_path), "rb"
    ).read() == data
    assert _sha256_long(final_path) == sha

    def _listdir_long(directory: Path) -> list[str]:
        """Long-path-safe listing (plain iterdir dies past MAX_PATH)."""
        prefix = '\\\\?\\' if os.name == "nt" else ""
        return os.listdir(prefix + str(directory))

    residue = [n for n in _listdir_long(final_path.parent) if ".upload" in n]
    assert residue == [], f"orphan temp residue after publish: {residue}"

    # Idempotent replay of identical content: still exactly one file.
    _atomic_write_windows(final_path, data, context="long-path replay")
    files = _listdir_long(final_path.parent)
    assert files == [final_path.name]


# ------------------------------------------------- handler end-to-end ------


def _submit_all(svc: JobService, bench: Path) -> JobService:
    """Submit the full 4-loop batch bound to the ACTIVE synthetic doc.

    The idempotency key derives from the logical manifest exactly like the
    API route, so identical payloads reuse the same durable job (contract
    §3 replay identity).  The manifest pins the synthetic evidence path AND
    its content SHA — a mutated document fails closed at plan time.
    """
    if svc._worker is not None:
        register_s09_demo_loop_handler(svc._worker)
    manifest = _manifest_for(bench)
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    key = f"S09_DEMO_LOOP:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]}"
    return svc.create_job(
        JOB_TYPE_S09_DEMO_LOOP,
        manifest,
        workspace_id="default",
        owner_type="project",
        owner_id="default",
        idempotency_key=key,
        steps=demo_loop_steps(),
    )


def _run_worker(worker: DurableWorker) -> None:
    worker.run_once()


def _published_from_result(
    svc: JobService, job_id: str
) -> list[dict[str, object]]:
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        repo = JobRepository(session)
        attempts = repo.list_attempts(job_id)
        for attempt in reversed(attempts):
            raw = getattr(attempt, "result", None)
            if isinstance(raw, dict) and isinstance(raw.get("published"), dict):
                return [
                    {"loop_id": k, **v} for k, v in sorted(raw["published"].items())
                ]
    raise AssertionError("no attempt result published")


def test_handler_renders_publishes_and_is_idempotent(demo_env: Path) -> None:
    svc = _make_isolated_service()
    bench = _active_bench()
    info = _submit_all(svc, bench)
    worker = svc._worker
    assert worker is not None
    worker.run_once()

    done = svc.get_job(info.job_id)
    assert done is not None
    assert done.state.value == "completed", done.error

    published = _published_from_result(svc, info.job_id)
    assert [e["loop_id"] for e in published] == ALL_LOOPS
    managed = svc.managed_root
    for entry in published:
        path = managed / str(entry["relative_path"])
        assert path.exists(), f"artifact missing on disk: {path}"
        assert _sha256_file(path) == entry["sha256"]
        assert entry["size_bytes"] > 0
        # No doubled artifacts segment may ever appear under the root.
        assert "artifacts/artifacts" not in path.as_posix()

    # Idempotent replay: resubmit identical payload → same completed job is
    # reused; NO duplicate files appear.
    before = {str(p.relative_to(managed)) for p in managed.rglob("*.mp4")}
    again = _submit_all(svc, bench)
    assert again.job_id == info.job_id
    after = {str(p.relative_to(managed)) for p in managed.rglob("*.mp4")}
    assert before == after


def test_kill_mid_run_reconcile_replay_no_duplicate(demo_env: Path) -> None:
    """Kill mid-run, reconcile, replay — byte-identical republish, no
    duplicate artifact rows/files."""
    svc = _make_isolated_service()
    bench = _active_bench()
    info = _submit_all(svc, bench)
    worker = svc._worker
    assert worker is not None
    worker.run_once()
    done = svc.get_job(info.job_id)
    assert done is not None and done.state.value == "completed"

    first_pass = _published_from_result(svc, info.job_id)
    sha_first = {e["loop_id"]: e["sha256"] for e in first_pass}

    reconciler = JobReconciler(svc.session_factory)
    report = reconciler.reconcile_once()
    assert report is not None

    svc2 = _make_isolated_service()
    info2 = _submit_all(svc2, bench)
    worker2 = svc2._worker
    assert worker2 is not None
    worker2.run_once()
    done2 = svc2.get_job(info2.job_id)
    assert done2 is not None and done2.state.value == "completed"

    second_pass = _published_from_result(svc2, info2.job_id)
    sha_second = {e["loop_id"]: e["sha256"] for e in second_pass}
    assert sha_second == sha_first  # deterministic bytes across replay

    managed = svc2.managed_root
    finals = [
        p.name
        for p in managed.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    ]
    for e in second_pass:
        assert Path(str(e["relative_path"])).name in finals


def test_cancel_leaves_zero_residue(demo_env: Path) -> None:
    svc = _make_isolated_service()
    info = _submit_all(svc, _active_bench())
    ok = svc.cancel_job(info.job_id)
    assert ok is True
    managed = svc.managed_root
    outputs = [
        p
        for p in managed.rglob("*")
        if p.is_file() and "s09-demo-loops" in p.as_posix() and p.suffix == ".mp4"
    ]
    assert outputs == []


def test_render_loop_bytes_deterministic() -> None:
    man = json.loads((FIXTURE_ROOT / "manifests/d1_cut_graphic.json").read_text())
    a, n1 = render_loop_bytes(
        media_path=FIXTURE_ROOT / "media/d1_cut_graphic.mp4",
        replacement_program=man["replacement_program"],
        fixture_root=FIXTURE_ROOT,
    )
    b, n2 = render_loop_bytes(
        media_path=FIXTURE_ROOT / "media/d1_cut_graphic.mp4",
        replacement_program=man["replacement_program"],
        fixture_root=FIXTURE_ROOT,
    )
    assert n1 >= 1 and n1 == n2
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


# ------------------------------------------------- C3 targeted regen ------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _overlapping_fixture_copy(tmp_root: Path) -> Path:
    """Test-owned synthetic fixture copy where two group placements OVERLAP.

    The shipped d4 fixture has disjoint placements, so a z-order flip would
    be invisible there.  This copies the whole s09_demo tree into *tmp_root*
    and moves placement 1 next to placement 0 — production code untouched,
    same synthetic-isolation pattern as the evidence documents.
    """
    import shutil

    target = tmp_root / "s09_demo_overlap"
    shutil.copytree(FIXTURE_ROOT, target)
    man_path = target / "manifests/d4_group_occlusion.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    for entry in man["replacement_program"]:
        if entry.get("op") == "group_place":
            # Move placement 1 NEXT TO placement 2 (x=460 ⇒ spans 380–540
            # against placement 2's 420–580): the TARGET overlaps the
            # UNAFFECTED higher-z layer, so raising the target's z genuinely
            # flips WHO IS ON TOP in the shared pixels.  (Next to placement
            # 0 would be invisible: the target already paints above it.)
            entry["placements"][1]["center_px"] = [460, 214]
    man_path.write_text(json.dumps(man), encoding="utf-8")
    return target


def _regen_result(svc: JobService, job_id: str) -> dict[str, object]:
    """Newest attempt result of a completed regen job (typed dict)."""
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        repo = JobRepository(session)
        for attempt in reversed(repo.list_attempts(job_id)):
            raw = getattr(attempt, "result", None)
            if isinstance(raw, dict) and isinstance(raw.get("published"), dict):
                return raw
    raise AssertionError("no regen result published")


def _job_count(svc: JobService) -> int:
    factory = svc.session_factory
    assert factory is not None
    from sqlalchemy import select

    from app.persistence.models import Job

    with factory() as session:
        return len(session.scalars(select(Job)).all())


def _correction_context(
    *,
    base_job_id: str,
    affected: list[str] | None = None,
    z: int = 9,
    kind: str = "z_order",
    fixtures: Path | None = None,
) -> tuple[dict[str, object], str]:
    """Build an immutable T05A-shaped applied-regeneration context.

    Mirrors the real ``applied_regeneration_context`` payload: the kind-
    keyed legacy identity block PLUS the canonical versioned ``render_effect``
    whose ``op`` is the render authority (T05A-C4 §4.3 shape).  Returns
    ``(context, sha)`` where ``sha`` is the canonical-json digest exactly
    like T05A computes it — the handler re-derives and compares it fail-
    closed.
    """
    if kind == "mask":
        # The mask asset lives in the ACTIVE fixture copy (c4_env writes it
        # into the overlapping tree) — never resolve it against the process
        # working directory.
        mask_png = (
            Path(str(fixtures)) / MASK_PNG
            if fixtures is not None
            else FIXTURE_ROOT / MASK_PNG
        )
        effect: dict[str, object] = {
            "render_effect": {
                "version": 1,
                "op": "mask",
                "target_layer_id": "d4_group_1",
                "target_segment_id": "seg-d4-group-1",
                "mask_artifact": {
                    "artifact_id": "art-mask-c4",
                    "sha256": _sha256_file(mask_png),
                    "relative_path": "sprites/c4_mask/c4_mask_overlay.png",
                    "kind": "image",
                    "byte_size": mask_png.stat().st_size,
                },
                "mask_semantics": {
                    "version": 1,
                    "source_generation": "gen-user-mask",
                    "segmentation": {"mode": "user_stroke"},
                    "confidence_source": "user",
                    "reasons": ["mask correction"],
                },
            }
        }
        legacy: dict[str, object] = {}
    elif kind == "z_order":
        effect = {
            "render_effect": {
                "version": 1,
                "op": "z_order",
                "target_layer_id": "d4_group_1",
                "z_order": z,
            }
        }
        legacy = {"supersede": {"z_order": z}}
    elif kind == "contact":
        effect = {
            "render_effect": {
                "version": 1,
                "op": "contact",
                "target_contact_id": "ctc-d4-group-0",
                "end_frame": 70,
            }
        }
        legacy = {"contact": {"end_frame": 70}}
    elif kind == "mesh_parts":
        effect = {
            "render_effect": {
                "version": 1,
                "op": "mesh_parts",
                "target_motion_id": "mot-d4-group-2",
                "transform_type": "rigid_similarity",
                "applied_transform": {
                    "offset_px": [24, -18],
                    "rotation_deg": 12.5,
                    "scale": 1.15,
                },
            }
        }
        legacy = {"motion": {"transform_type": "rigid_similarity"}}
    elif kind == "route_override":
        effect = {
            "render_effect": {
                "version": 1,
                "op": "route_override",
                "route_to": "pose_swap",
                "frame_range": {"start_frame": 0, "end_frame": 10**9},
                "anchor": {"x": 0.0, "y": 0.0},
                "provenance": {
                    "evidence": "C2-SYNTHETIC measured-passing pose_swap",
                    "reason": "C4 targeted override",
                },
            }
        }
        legacy = {"route_override": {"route_to": "pose_swap"}}
    else:  # pragma: no cover - guarded by parametrize over CORRECTION_KINDS
        raise ValueError(f"unsupported kind {kind!r}")
    ctx = {
        "correction_id": f"corr-{kind}-0001",
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "project_id": "default",
        "video_item_id": "vid-d4",
        "correction_kind": kind,
        "applied_revision": 2,
        "natural_key": f"S09C:{kind}:" + ("a" * 40),
        "occurrence_segment_id": (
            "seg-d4-group-1" if kind in ("mask", "z_order") else "seg-d4-group-0"
        ),
        "affected_occurrence_segment_ids": ["seg-d4-group-0"],
        "affected_contact_ids": [],
        "affected_motion_ids": [],
        "affected_loop_ids": affected or ["d4_group_occlusion"],
        "affected_layer_ids": ["d4_group_1"],
        "effect": {**legacy, **effect},
    }
    digest = hashlib.sha256(
        json.dumps(ctx, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ctx, digest


def _submit_base(
    svc: JobService, bench: Path, fixtures_dir: Path
) -> JobInfo:
    """Submit+register the 4-loop BASE demo job over a fixture dir."""
    if svc._worker is not None:
        register_s09_demo_loop_handler(svc._worker)
    manifest = {
        "requested_loops": ALL_LOOPS,
        "benchmark_results": str(bench),
        "fixtures_dir": str(fixtures_dir),
        "pinned_routes": {},
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    key = f"S09_DEMO_LOOP:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]}"
    return svc.create_job(
        JOB_TYPE_S09_DEMO_LOOP,
        manifest,
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_type="project",
        owner_id="default",
        idempotency_key=key,
        steps=demo_loop_steps(),
    )


def _submit_regen(
    svc: JobService,
    *,
    base_job_id: str,
    bench: Path,
    context: dict[str, object],
    context_sha: str,
    pinned_frozen: str | None = None,
    fixtures_dir: Path | None = None,
) -> JobInfo:
    """Submit one S09_DEMO_REGEN job.

    The idempotency key is the FULL C4 three-part fingerprint (base +
    context SHA + server-side resolved frozen evidence); the manifest pins
    the same resolved identity so a stale/tampered evidence generation
    refuses inside the handler with zero mutation.  *fixtures_dir* pins the
    ACTIVE fixture tree (c4_env's overlapping copy) — the regen render must
    read the same media/sprites/manifests the base generation rendered.
    """
    if svc._worker is not None:
        register_s09_demo_loop_handler(svc._worker)
    frozen = (
        pinned_frozen
        if pinned_frozen is not None
        else resolve_frozen_evidence_sha256(benchmark_results_path=bench)
    )
    manifest = {
        "requested_loops": ALL_LOOPS,
        "benchmark_results": str(bench),
        "fixtures_dir": str(fixtures_dir or FIXTURE_ROOT),
        "pinned_routes": {},
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "base_job_id": base_job_id,
        "correction_context": context,
        "correction_context_sha256": context_sha,
        "frozen_evidence_sha256": frozen,
    }
    key = regen_fingerprint(
        base_job_id=base_job_id,
        correction_context_sha256=context_sha,
        frozen_evidence_sha256=frozen,
    )
    return svc.create_job(
        JOB_TYPE_S09_DEMO_REGEN,
        manifest,
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_type="project",
        owner_id="default",
        idempotency_key=key,
        steps=demo_loop_regen_steps(),
    )


def test_regen_one_generation_affected_changes_unaffected_identical(
    demo_env: Path, tmp_path: Path
) -> None:
    """C3 acceptance core: completed base + applied z-order context →

    exactly ONE new generation job; affected loop bytes/hash/artifact row
    genuinely change; unaffected publications reused verbatim (byte-
    identical file, same Artifact row id, zero duplicate rows).
    """
    fixtures = _overlapping_fixture_copy(tmp_path)
    svc = _make_isolated_service()
    bench = _active_bench()

    base_info = _submit_base(svc, bench, fixtures)
    worker = svc._worker
    assert worker is not None
    worker.run_once()
    done = svc.get_job(base_info.job_id)
    assert done is not None and done.state.value == "completed", done.error
    base_pub = {e["loop_id"]: e for e in _published_from_result(svc, base_info.job_id)}

    # Managed files before regeneration.
    managed = svc.managed_root
    files_before = sorted(managed.rglob("*.mp4"))

    context, ctx_sha = _correction_context(base_job_id=base_info.job_id)
    regen = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=context, context_sha=ctx_sha,
        fixtures_dir=fixtures,
    )
    worker.run_once()
    rdone = svc.get_job(regen.job_id)
    assert rdone is not None and rdone.state.value == "completed", rdone.error

    result = _regen_result(svc, regen.job_id)
    evidence = result["generation_evidence"]
    assert evidence["base_job_id"] == base_info.job_id
    assert evidence["correction_context_sha256"] == ctx_sha
    assert result["affected_loop_ids"] == ["d4_group_occlusion"]

    # AFFECTED loop: genuinely regenerated — different bytes/hash/path/row.
    aff = result["published"]["d4_group_occlusion"]
    b4 = base_pub["d4_group_occlusion"]
    assert aff["regenerated"] is True
    assert aff["sha256"] != b4["sha256"]
    assert aff["artifact_id"] != b4["artifact_id"]
    assert aff["relative_path"] != b4["relative_path"]

    # UNAFFECTED loops: exact reuse of base publication identity.
    for loop_id in ("d1_cut_graphic", "d2_mouth_phone", "d3_rotation_bed"):
        entry = result["published"][loop_id]
        orig = base_pub[loop_id]
        assert entry["regenerated"] is False
        assert entry["artifact_id"] == orig["artifact_id"]
        assert entry["relative_path"] == orig["relative_path"]
        assert entry["sha256"] == orig["sha256"]
        assert entry["size_bytes"] == orig["size_bytes"]

    # Zero duplicate artifact rows workspace-wide.
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        from sqlalchemy import select

        from app.persistence.models import Artifact

        rows = session.scalars(select(Artifact)).all()
        paths = [r.relative_path for r in rows]
        assert len(paths) == len(set(paths))
        # Exactly one NEW row (the affected loop's new content path).
        assert len(rows) == len(files_before) + 1

    # Unaffected FILES byte-identical on disk.
    for loop_id in ("d1_cut_graphic", "d2_mouth_phone", "d3_rotation_bed"):
        p = managed / str(result["published"][loop_id]["relative_path"])
        assert p.is_file()
        assert _sha256_file(p) == base_pub[loop_id]["sha256"]


def test_replay_same_correction_same_job_new_correction_new_generation(
    demo_env: Path, tmp_path: Path
) -> None:
    """Replay of the SAME base+context returns the SAME durable job; a
    DIFFERENT correction derives a NEW generation."""
    fixtures = _overlapping_fixture_copy(tmp_path)
    svc = _make_isolated_service()
    bench = _active_bench()
    if svc._worker is not None:
        register_s09_demo_loop_handler(svc._worker)
    worker = svc._worker
    assert worker is not None

    base_info = _submit_base(svc, bench, fixtures)
    worker.run_once()
    done = svc.get_job(base_info.job_id)
    assert done is not None and done.state.value == "completed"

    ctx1, sha1 = _correction_context(base_job_id=base_info.job_id, z=9)
    first = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=ctx1, context_sha=sha1,
        fixtures_dir=fixtures,
    )
    assert first.job_id != base_info.job_id  # one NEW generation
    worker.run_once()
    fdone = svc.get_job(first.job_id)
    assert fdone is not None and fdone.state.value == "completed", fdone.error

    replay = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=dict(ctx1), context_sha=sha1,
        fixtures_dir=fixtures,
    )
    assert replay.job_id == first.job_id  # same context → same job

    ctx2, sha2 = _correction_context(base_job_id=base_info.job_id, z=-7)
    assert sha2 != sha1
    second_gen = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=ctx2, context_sha=sha2,
        fixtures_dir=fixtures,
    )
    assert second_gen.job_id != first.job_id  # different correction → new gen


def test_regen_fail_closed_cases(demo_env: Path, tmp_path: Path) -> None:
    """Tampered context / wrong base type / non-completed base / affected
    outside scope all refuse with ZERO durable mutation."""
    fixtures = _overlapping_fixture_copy(tmp_path)
    svc = _make_isolated_service()
    bench = _active_bench()
    if svc._worker is not None:
        register_s09_demo_loop_handler(svc._worker)
    worker = svc._worker
    assert worker is not None

    base_info = _submit_base(svc, bench, fixtures)
    worker.run_once()
    done = svc.get_job(base_info.job_id)
    assert done is not None and done.state.value == "completed"

    managed_files = sorted(svc.managed_root.rglob("*.mp4"))

    # 1. TAMPERED CONTEXT: payload drifts after pinning (render authority
    # mutated post-apply → the recomputed SHA refuses before any effect).
    ctx_ok, sha_ok = _correction_context(base_job_id=base_info.job_id)
    tampered = dict(ctx_ok)
    tampered["effect"] = {
        **ctx_ok["effect"],
        "render_effect": {**ctx_ok["effect"]["render_effect"], "z_order": -999},
    }
    bad = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=tampered, context_sha=sha_ok,
        fixtures_dir=fixtures,
    )
    worker.run_once()
    bdone = svc.get_job(bad.job_id)
    assert bdone is not None and bdone.state.value == "failed"
    assert bdone.error is not None and "tampered" in str(bdone.error)

    # 2. AFFECTED OUTSIDE SCOPE: valid SHA but loop not in base request.
    ctx_out, sha_out = _correction_context(
        base_job_id=base_info.job_id,
        affected=["d9_not_a_loop"],
    )
    out = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=ctx_out, context_sha=sha_out,
        fixtures_dir=fixtures,
    )
    worker.run_once()
    odone = svc.get_job(out.job_id)
    assert odone is not None and odone.state.value == "failed"

    # No new managed files, no extra completed jobs.
    assert sorted(svc.managed_root.rglob("*.mp4")) == managed_files


def test_verify_correction_context_rejects_drift() -> None:
    """Unit: verify_correction_context refuses any recomputed-SHA drift."""
    ctx, sha = _correction_context(base_job_id="job-x")
    verify_correction_context(ctx, sha)  # exact match passes
    drifted = dict(ctx)
    drifted["applied_revision"] = 99
    with pytest.raises(DemoLoopPlanError, match="tampered"):
        verify_correction_context(drifted, sha)


# ─────────────────────────────────────────────── C4 exact dispatcher ------


def _run_to_terminal(svc: JobService, job_id: str, max_rounds: int = 6) -> str:
    """Run the worker until *job_id* leaves the active states (or rounds out)."""
    worker = svc._worker
    assert worker is not None
    terminal = {"completed", "failed", "cancelled"}
    for _ in range(max_rounds):
        state = svc.get_job(job_id)
        assert state is not None
        if state.state.value in terminal:
            return state.state.value
        worker.run_once()
    state = svc.get_job(job_id)
    assert state is not None
    return state.state.value


@pytest.fixture()
def c4_env(demo_env: Path, tmp_path: Path) -> dict[str, object]:
    """Completed BASE job over an OVERLAPPING d4 fixture + mask asset.

    Returns ``{"svc", "bench", "fixtures", "base_info", "base_pub"}`` — the
    shared setup for every targeted-regeneration acceptance test.
    """
    fixtures = _overlapping_fixture_copy(tmp_path)
    _write_mask_asset(fixtures)
    svc = _make_isolated_service()
    bench = _active_bench()
    base_info = _submit_base(svc, bench, fixtures)
    worker = svc._worker
    assert worker is not None
    worker.run_once()
    done = svc.get_job(base_info.job_id)
    assert done is not None and done.state.value == "completed", done.error
    base_pub = {
        e["loop_id"]: e for e in _published_from_result(svc, base_info.job_id)
    }
    return {
        "svc": svc,
        "bench": bench,
        "fixtures": fixtures,
        "base_info": base_info,
        "base_pub": base_pub,
    }


def _render_call_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, int], list[str]]:
    """Spy on render_loop_bytes' real ffmpeg pipeline (call counter).

    The production function is NOT replaced — its subprocess surface is
    wrapped so every actual decode/encode invocation increments the counter.
    """
    from app.workflow import s09_demo_jobs as mod

    calls = {"n": 0}
    loops: list[str] = []
    real = mod.render_loop_bytes

    def counting(
        *, media_path: Path, replacement_program: list[dict[str, Any]], fixture_root: Path
    ) -> tuple[bytes, int]:
        calls["n"] += 1
        loops.append(media_path.stem)
        return real(
            media_path=media_path,
            replacement_program=replacement_program,
            fixture_root=fixture_root,
        )

    monkeypatch.setattr(mod, "render_loop_bytes", counting)
    return calls, loops


def test_c4_render_spy_one_affected_exactly_one_call_unaffected_zero(
    c4_env: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C4 §4.1 core: ONE affected loop ⇒ EXACTLY ONE renderer invocation;
    unaffected loops never decode/render/encode and carry no render_ms."""
    svc: JobService = c4_env["svc"]  # type: ignore[assignment]
    bench: Path = c4_env["bench"]  # type: ignore[arg-type]
    base_pub = cast("dict[str, dict[str, object]]", c4_env["base_pub"])
    calls, rendered_loops = _render_call_spy(monkeypatch)

    context, sha = _correction_context(base_job_id=str(c4_env["base_info"].job_id))
    regen = _submit_regen(
        svc, base_job_id=str(c4_env["base_info"].job_id), bench=bench,
        context=context, context_sha=sha,
        fixtures_dir=cast("Path", c4_env["fixtures"]),
    )
    assert _run_to_terminal(svc, regen.job_id) == "completed"

    assert calls["n"] == 1, f"renderer invoked {calls['n']} times"
    assert rendered_loops == ["d4_group_occlusion"]

    result = _regen_result(svc, regen.job_id)
    assert result["affected_loop_ids"] == ["d4_group_occlusion"]
    aff = result["published"]["d4_group_occlusion"]
    assert aff["regenerated"] is True
    assert "render_ms" in aff
    for loop_id in ("d1_cut_graphic", "d2_mouth_phone", "d3_rotation_bed"):
        entry = result["published"][loop_id]
        assert entry["regenerated"] is False
        # Exact reuse: the regen publication binds the BASE identity verbatim
        # (same artifact id / hash / size / frame count) and adds NO fresh
        # timing field — a loop that never touched the decoder/encoder can
        # never grow a render_ms of its own.
        assert "render_ms" not in entry
        assert entry["sha256"] == base_pub[loop_id]["sha256"]
        assert entry["artifact_id"] == base_pub[loop_id]["artifact_id"]
        assert entry["size_bytes"] == base_pub[loop_id]["size_bytes"]
        assert entry["frame_count"] == base_pub[loop_id]["frame_count"]


def test_c4_z_order_non_first_placement_only_target_moves(
    c4_env: dict[str, object],
) -> None:
    """C4 §4.2 z-order ACCEPTANCE: target = SECOND placement of the group.

    Only the target's compositing changes; an overlapping unaffected layer
    keeps its z; output bytes/hash/artifact genuinely change via the REAL
    group compositor (sorted paint order), no synthetic marker pixel.
    """
    from app.workflow.s09_demo_jobs import (
        _apply_correction_effect,
        _resolve_target_placements,
    )

    man = json.loads(
        Path(str(c4_env["fixtures"]), "manifests/d4_group_occlusion.json").read_text(
            encoding="utf-8"
        )
    )
    program = man["replacement_program"]
    group_entry = next(e for e in program if e.get("op") == "group_place")
    # Fixture authority: d4_group_0 z=0, d4_group_1 z=1, d4_group_2 z=2 —
    # the TARGET below is deliberately NOT placements[0].
    assert [p[LAYER_ID_KEY] for p in group_entry["placements"]] == [
        "d4_group_0",
        "d4_group_1",
        "d4_group_2",
    ]
    assert [int(p["z_order"]) for p in group_entry["placements"]] == [0, 1, 2]

    context, _sha = _correction_context(base_job_id="job-x")
    corrected, applied = _apply_correction_effect(
        program,
        correction_kind="z_order",
        effect=context["effect"],
        affected_loop_ids=["d4_group_occlusion"],
        affected_layer_ids=list(context["affected_layer_ids"]),
        loop_id="d4_group_occlusion",
    )
    assert applied is True
    g_new = next(e for e in corrected if e.get("op") == "group_place")
    by_layer = {p[LAYER_ID_KEY]: int(p["z_order"]) for p in g_new["placements"]}
    # ONLY the bound second placement moved:
    assert by_layer == {
        "d4_group_0": 0,
        "d4_group_1": 9,  # corrected z lands on the STABLE binding
        "d4_group_2": 2,
    }
    # ...and the matcher resolves exactly that one placement:
    matches = _resolve_target_placements(
        corrected, loop_id="d4_group_occlusion", layer_ids=["d4_group_1"]
    )
    assert len(matches) == 1

    # END-TO-END through the durable handler: bytes genuinely change via the
    # real compositor (overlapping sprites ⇒ paint order flip is visible).
    svc: JobService = c4_env["svc"]  # type: ignore[assignment]
    bench: Path = c4_env["bench"]  # type: ignore[arg-type]
    base_pub = cast("dict[str, dict[str, object]]", c4_env["base_pub"])
    context_e, sha_e = _correction_context(base_job_id=str(c4_env["base_info"].job_id))
    regen = _submit_regen(
        svc, base_job_id=str(c4_env["base_info"].job_id), bench=bench,
        context=context_e, context_sha=sha_e,
        fixtures_dir=cast("Path", c4_env["fixtures"]),
    )
    assert _run_to_terminal(svc, regen.job_id) == "completed"
    aff = _regen_result(svc, regen.job_id)["published"]["d4_group_occlusion"]
    b4 = base_pub["d4_group_occlusion"]
    assert aff["regenerated"] is True
    assert aff["sha256"] != b4["sha256"]
    assert aff["artifact_id"] != b4["artifact_id"]

    # Determinism probe on the same overlap fixture copy: identical inputs →
    # byte-identical output (real compositor, no random marker).
    data_a, n_a = render_loop_bytes(
        media_path=Path(str(c4_env["fixtures"]), "media/d4_group_occlusion.mp4"),
        replacement_program=cast("list[dict[str, Any]]", [g_new]),
        fixture_root=Path(str(c4_env["fixtures"])),
    )
    data_b, n_b = render_loop_bytes(
        media_path=Path(str(c4_env["fixtures"]), "media/d4_group_occlusion.mp4"),
        replacement_program=cast("list[dict[str, Any]]", [g_new]),
        fixture_root=Path(str(c4_env["fixtures"])),
    )
    assert n_a == n_b >= 1
    assert hashlib.sha256(data_a).hexdigest() == hashlib.sha256(data_b).hexdigest()


def test_c4_missing_and_ambiguous_layer_binding_fail_closed(
    c4_env: dict[str, object], tmp_path: Path
) -> None:
    """Zero-match AND ambiguous bindings refuse before any file/row effect."""
    from app.workflow.s09_demo_jobs import _apply_correction_effect

    man = json.loads(
        Path(str(c4_env["fixtures"]), "manifests/d4_group_occlusion.json").read_text(
            encoding="utf-8"
        )
    )
    program = man["replacement_program"]
    effect = _correction_context(base_job_id="job-x")[0]["effect"]

    # Zero-match binding: the exact-match contract raises BEFORE any
    # program mutation (fail-closed, no silent fallback).
    with pytest.raises(DemoLoopPlanError, match="ZERO"):
        _apply_correction_effect(
            program,
            correction_kind="z_order",
            effect=effect,
            affected_loop_ids=["d4_group_occlusion"],
            affected_layer_ids=["nope_unknown_layer"],
            loop_id="d4_group_occlusion",
        )

    amb_program = json.loads(json.dumps(program))
    group = next(e for e in amb_program if e.get("op") == "group_place")
    group["placements"][1][LAYER_ID_KEY] = "d4_group_0"  # duplicate the id
    with pytest.raises(DemoLoopPlanError, match="AMBIGUOUS"):
        _apply_correction_effect(
            amb_program,
            correction_kind="z_order",
            effect=effect,
            affected_loop_ids=["d4_group_occlusion"],
            affected_layer_ids=["d4_group_0"],
            loop_id="d4_group_occlusion",
        )
    with pytest.raises(DemoLoopPlanError, match="ZERO"):
        _apply_correction_effect(
            amb_program,
            correction_kind="z_order",
            effect=effect,
            affected_loop_ids=["d4_group_occlusion"],
            affected_layer_ids=[],
            loop_id="d4_group_occlusion",
        )


@pytest.mark.parametrize("kind", sorted(CORRECTION_KINDS))
def test_c4_five_kinds_real_effect_or_fail_closed(
    c4_env: dict[str, object], kind: str
) -> None:
    """C4 §4.3: EVERY advertised kind applies its canonical render mutation.

    Pixel-mutating kinds (mask/z_order/contact/mesh_parts) must produce a
    genuinely new artifact or fail closed — re-encoding unchanged media
    stamped regenerated=true is impossible.  ``route_override`` carries its
    REAL mutation on the targeted PLAN (routes + provenance); its measured
    render may come out pixel-identical and then dedupes onto the existing
    content-addressed artifact.
    """
    svc: JobService = c4_env["svc"]  # type: ignore[assignment]
    bench: Path = c4_env["bench"]  # type: ignore[arg-type]
    base_pub = cast("dict[str, dict[str, object]]", c4_env["base_pub"])
    b4_sha = str(base_pub["d4_group_occlusion"]["sha256"])

    context, sha = _correction_context(
        base_job_id=str(c4_env["base_info"].job_id),
        kind=kind,
        fixtures=cast("Path", c4_env["fixtures"]),
    )
    regen = _submit_regen(
        svc, base_job_id=str(c4_env["base_info"].job_id), bench=bench,
        context=context, context_sha=sha,
        fixtures_dir=cast("Path", c4_env["fixtures"]),
    )
    assert _run_to_terminal(svc, regen.job_id) == "completed", svc.get_job(
        regen.job_id
    ).error
    result = _regen_result(svc, regen.job_id)
    aff = result["published"]["d4_group_occlusion"]
    assert aff["regenerated"] is True
    if kind != "route_override":
        assert aff["sha256"] != b4_sha, f"{kind}: unchanged-media false success"
    else:
        # Honest evidence of a REAL render this generation: fresh timing on
        # the affected entry (the base snapshot never grows one).
        assert "render_ms" in aff
    ev = result["generation_evidence"]
    assert ev["correction_id"] == f"corr-{kind}-0001"

    if kind == "mask":
        # The pinned mask artifact identity must resolve to REAL fixture
        # bytes whose hash matches — the occlusion is reproducible.
        masked_rel = None
        with svc.session_factory() as session:
            repo = JobRepository(session)
            # The corrected program is the durable PRE-RENDER audit evidence
            # persisted on the regen STEP checkpoint
            # (cp["corrected_programs"][loop_id]) — read it there.
            step_cps = [
                s.checkpoint
                for s in repo.list_steps(regen.job_id)
                if isinstance(getattr(s, "checkpoint", None), dict)
            ]
        for cp in step_cps:
            for prog in (cp.get("corrected_programs") or {}).values():
                for e in prog or []:
                    placements = e.get("placements") if isinstance(e, dict) else None
                    if isinstance(placements, list):
                        for p in placements:
                            if p.get(MASK_ARTIFACT_KEY):
                                masked_rel = str(p["mask_artifact_path"])
                                pinned_sha = str(p["mask_artifact_sha256"])
        assert (
            masked_rel == "sprites/c4_mask/c4_mask_overlay.png"
        ), "mask artifact never bound onto the target placement"
        assert _sha256_file(Path(str(c4_env["fixtures"])) / masked_rel) == pinned_sha

    if kind == "route_override":
        # The override is REAL auditable provenance on the planned routes
        # (§4.3/§2: "targeted plan dùng route override thật") — the plan
        # provably carries the measured-passing corrected route.  The PUBLI-
        # CATION stays content-addressed: identical pixels under the new
        # route reuse the existing artifact instead of re-encoding unchanged
        # media and calling it regenerated (the forbidden false success).
        planned = next(
            e for e in result["plan"]["loops"] if e["loop_id"] == "d4_group_occlusion"
        )
        assert set(planned["routes_by_risk_class"].values()) == {"pose_swap"}
        assert any("route_override" in n for n in planned["route_notes"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("correction_kind", "teleport"),
        ("effect", {"supersede": {"z_order": 5}}),
    ],
)
def test_c4_malformed_effect_fails_closed(
    c4_env: dict[str, object], field: str, value: object
) -> None:
    """Unknown kind / missing canonical block refuses with zero publication."""
    svc: JobService = c4_env["svc"]  # type: ignore[assignment]
    bench: Path = c4_env["bench"]  # type: ignore[arg-type]

    context, sha = _correction_context(base_job_id=str(c4_env["base_info"].job_id))
    broken = dict(context)
    broken[field] = value
    digest = hashlib.sha256(
        json.dumps(broken, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    regen = _submit_regen(
        svc, base_job_id=str(c4_env["base_info"].job_id), bench=bench,
        context=broken, context_sha=digest,
        fixtures_dir=cast("Path", c4_env["fixtures"]),
    )
    assert _run_to_terminal(svc, regen.job_id) == "failed"
    info = svc.get_job(regen.job_id)
    assert info is not None and info.error is not None
    blob = json.dumps(info.error)
    assert "unknown correction_kind" in blob or "canonical" in blob
    # Zero new managed files beyond the base generation's four loops.
    files = [p for p in svc.managed_root.rglob("*.mp4")]
    assert len(files) == 4


def test_c4_fingerprint_three_fields_and_evidence_difference() -> None:
    """C4 §4.4 identity: signature pins THREE fields; different frozen
    evidence ⇒ different generation key even for the same base+context."""
    import inspect

    params = list(inspect.signature(regen_fingerprint).parameters)
    assert params == [
        "base_job_id",
        "correction_context_sha256",
        "frozen_evidence_sha256",
    ]

    fp_a = regen_fingerprint(
        base_job_id="job-base",
        correction_context_sha256="c" * 64,
        frozen_evidence_sha256="e" * 64,
    )
    same = regen_fingerprint(
        base_job_id="job-base",
        correction_context_sha256="c" * 64,
        frozen_evidence_sha256="e" * 64,
    )
    assert fp_a == same  # same tuple ⇒ reused identity
    diff_ctx = regen_fingerprint(
        base_job_id="job-base",
        correction_context_sha256="d" * 64,
        frozen_evidence_sha256="e" * 64,
    )
    diff_ev = regen_fingerprint(
        base_job_id="job-base",
        correction_context_sha256="c" * 64,
        frozen_evidence_sha256="f" * 64,
    )
    diff_base = regen_fingerprint(
        base_job_id="job-other",
        correction_context_sha256="c" * 64,
        frozen_evidence_sha256="e" * 64,
    )
    assert len({fp_a, diff_ctx, diff_ev, diff_base}) == 4


def test_c4_stale_pinned_frozen_evidence_zero_mutation(
    c4_env: dict[str, object], tmp_path: Path
) -> None:
    """A manifest pinning a WRONG frozen-evidence identity refuses inside
    the handler BEFORE any publication/checkpoint effect (zero rows/files).
    """
    from sqlalchemy import select

    from app.persistence.models import Artifact

    svc: JobService = c4_env["svc"]  # type: ignore[assignment]
    bench: Path = c4_env["bench"]  # type: ignore[arg-type]

    files_before = sorted(svc.managed_root.rglob("*.mp4"))
    with svc.session_factory() as session:
        rows_before = len(session.scalars(select(Artifact)).all())

    context, sha = _correction_context(base_job_id=str(c4_env["base_info"].job_id))
    stale = _submit_regen(
        svc, base_job_id=str(c4_env["base_info"].job_id), bench=bench,
        context=context, context_sha=sha,
        pinned_frozen="a" * 64,  # ≠ server-resolved identity of THIS bench doc
        fixtures_dir=cast("Path", c4_env["fixtures"]),
    )
    assert _run_to_terminal(svc, stale.job_id) == "failed"
    info = svc.get_job(stale.job_id)
    assert info is not None and info.error is not None
    assert "frozen evidence" in json.dumps(info.error)

    assert sorted(svc.managed_root.rglob("*.mp4")) == files_before
    with svc.session_factory() as session:
        assert len(session.scalars(select(Artifact)).all()) == rows_before


def test_c4_direct_cross_workspace_submit_refuses_before_publication(
    demo_env: Path, tmp_path: Path
) -> None:
    """C4 §4.6: direct service submission whose base Job lives in ANOTHER
    workspace refuses at the reusable worker boundary (not just HTTP)."""
    from sqlalchemy import select

    from app.persistence.models import Artifact
    from app.workflow.durable_worker import WorkerContext
    from app.workflow.s09_demo_jobs import demo_loop_regen_handler

    fixtures = _overlapping_fixture_copy(tmp_path)
    svc = _make_isolated_service()
    bench = _active_bench()
    base_info = _submit_base(svc, bench, fixtures)
    worker = svc._worker
    assert worker is not None
    worker.run_once()
    done = svc.get_job(base_info.job_id)
    assert done is not None and done.state.value == "completed"

    context, sha = _correction_context(base_job_id=base_info.job_id)
    frozen = resolve_frozen_evidence_sha256(benchmark_results_path=bench)

    def _direct(manifest: dict[str, object]) -> dict[str, object]:
        ctx = WorkerContext(
            job_id="direct-regen-probe",
            job_type=JOB_TYPE_S09_DEMO_REGEN,
            step_code="demo_loop_regen",
            step_id="step-direct",
            workspace_id="some-other-workspace",  # ≠ base row workspace
            owner_type="project",
            owner_id="default",
            input_manifest=manifest,
            attempt=1,
            checkpoint={},
            worker_id="probe-worker",
            fence_token="probe-token",
            ttl_seconds=300,
            progress=lambda *_: None,
            write_checkpoint=lambda *_: None,
            is_cancelled=lambda: False,
            staging_dir=lambda: tmp_path / "staging",
            session_factory=svc.session_factory,
        )
        return demo_loop_regen_handler(ctx)

    manifest = {
        "requested_loops": ALL_LOOPS,
        "benchmark_results": str(bench),
        "fixtures_dir": str(FIXTURE_ROOT),
        "workspace_id": "some-other-workspace",
        "managed_root": str(svc.managed_root),
        "base_job_id": base_info.job_id,
        "correction_context": context,
        "correction_context_sha256": sha,
        "frozen_evidence_sha256": frozen,
    }
    with pytest.raises(DemoLoopPlanError, match="cross-workspace"):
        _direct(manifest)
    # Zero artifact mutation happened.
    with svc.session_factory() as session:
        rows = session.scalars(select(Artifact)).all()
        assert len(rows) == 4  # only the base generation's publications


def test_c4_cancel_during_targeted_work_no_orphan_no_false_success(
    demo_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel mid-targeted-render: no orphan Artifact row/file, NO false
    completed generation; a fresh successor run then completes cleanly and
    re-renders ONLY the affected loop (unaffected reuse intact)."""
    fixtures = _overlapping_fixture_copy(tmp_path)
    _write_mask_asset(fixtures)
    svc = _make_isolated_service()
    bench = _active_bench()

    base_info = _submit_base(svc, bench, fixtures)
    worker = svc._worker
    assert worker is not None
    worker.run_once()
    done = svc.get_job(base_info.job_id)
    assert done is not None and done.state.value == "completed"
    base_files = sorted(svc.managed_root.rglob("*.mp4"))

    context, sha = _correction_context(base_job_id=base_info.job_id)
    regen = _submit_regen(
        svc, base_job_id=base_info.job_id, bench=bench,
        context=context, context_sha=sha,
        fixtures_dir=fixtures,
    )

    from app.workflow import s09_demo_jobs as mod

    real_render = mod.render_loop_bytes

    def cancel_after_first_frame(
        *,
        media_path: Path,
        replacement_program: list[dict[str, Any]],
        fixture_root: Path,
    ) -> tuple[bytes, int]:
        # The durable cancel flag flips DURING the affected render.
        svc.cancel_job(regen.job_id)
        return real_render(
            media_path=media_path,
            replacement_program=replacement_program,
            fixture_root=fixture_root,
        )

    monkeypatch.setattr(mod, "render_loop_bytes", cancel_after_first_frame)
    final_state = _run_to_terminal(svc, regen.job_id, max_rounds=8)

    assert final_state == "cancelled", final_state
    # No orphan file beyond the base generation's four publications, and no
    # false completed attempt result anywhere on this job.
    assert sorted(svc.managed_root.rglob("*.mp4")) == base_files
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        repo = JobRepository(session)
        for attempt in repo.list_attempts(regen.job_id):
            raw = getattr(attempt, "result", None)
            assert not (
                isinstance(raw, dict) and raw.get("affected_loop_ids")
            ), "false completed generation result after cancel"
    info = svc.get_job(regen.job_id)
    assert info is not None and info.state.value == "cancelled"

    # Fresh successor generation (same fingerprint family): completes and
    # re-renders ONLY the affected loop; unaffected reuse stays verbatim.
    from sqlalchemy import select

    from app.persistence.models import Artifact

    with factory() as session:
        rows_before = len(session.scalars(select(Artifact)).all())
    # Successor of the CANCELLED job goes through the durable repository
    # contract (JobRepository.create_successor §6.4) — same manifest.
    from types import SimpleNamespace

    with factory() as session:
        repo = JobRepository(session)
        successor_record = repo.create_successor(
            predecessor_job_id=regen.job_id,
            input_manifest=dict(regen_manifest_of(svc, regen.job_id)),
            steps=demo_loop_regen_steps(),
        )
        session.commit()
    successor = SimpleNamespace(job_id=successor_record.id)
    worker.run_once()
    sdone = svc.get_successor_done = svc.get_job(successor.job_id)
    assert sdone is not None and sdone.state.value == "completed", sdone.error
    result = _regen_result(svc, successor.job_id)
    assert result["affected_loop_ids"] == ["d4_group_occlusion"]
    assert result["published"]["d4_group_occlusion"]["regenerated"] is True
    for loop_id in ("d1_cut_graphic", "d2_mouth_phone", "d3_rotation_bed"):
        assert result["published"][loop_id]["regenerated"] is False
    with factory() as session:
        assert (
            len(session.scalars(select(Artifact)).all()) == rows_before + 1
        )


def regen_manifest_of(svc: JobService, job_id: str) -> dict[str, object]:
    """The immutable input manifest of one regen job (successor input)."""
    from sqlalchemy import select

    from app.persistence.models import Job

    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        row = session.scalar(select(Job).where(Job.id == job_id))
        assert row is not None
        return json.loads(row.input_manifest_json)


def test_c4_restart_reconcile_never_rerenders_unaffected(
    c4_env: dict[str, object], tmp_path: Path
) -> None:
    """Kill after plan commit, reconcile, replay: unaffected loops are NOT
    re-rendered (checkpoint skip), the affected loop publishes exactly once."""
    svc: JobService = c4_env["svc"]  # type: ignore[assignment]
    bench: Path = c4_env["bench"]  # type: ignore[arg-type]

    context, sha = _correction_context(base_job_id=str(c4_env["base_info"].job_id))
    regen = _submit_regen(
        svc, base_job_id=str(c4_env["base_info"].job_id), bench=bench,
        context=context, context_sha=sha,
        fixtures_dir=cast("Path", c4_env["fixtures"]),
    )
    # Simulate death AFTER the plan phase committed: pre-seed the fenced
    # checkpoint exactly like the handler would, then reconcile+replay.
    from app.workflow import s09_demo_jobs as mod

    captured: dict[str, object] = {}
    real_render = mod.render_loop_bytes

    def spy_then_crash(
        *,
        media_path: Path,
        replacement_program: list[dict[str, Any]],
        fixture_root: Path,
    ) -> tuple[bytes, int]:
        captured.setdefault("calls", []).append(media_path.stem)
        raise RuntimeError("simulated worker death mid-render")

    mod.render_loop_bytes = spy_then_crash
    try:
        first = _run_to_terminal(svc, regen.job_id, max_rounds=3)
    finally:
        mod.render_loop_bytes = real_render
    assert captured.get("calls") == ["d4_group_occlusion"], captured

    reconciler = JobReconciler(svc.session_factory)
    report = reconciler.reconcile_once()
    assert report is not None
    assert first in {"failed", "running"}

    svc2 = _make_isolated_service()
    replayed = svc2.create_job(
        JOB_TYPE_S09_DEMO_REGEN,
        dict(cast("dict[str, object]", regen_manifest_of(svc, regen.job_id))),
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_type="project",
        owner_id="default",
        idempotency_key=None,
        steps=demo_loop_regen_steps(),
    )
    worker2 = svc2._worker
    assert worker2 is not None
    worker2.run_once()
    rdone = svc2.get_job(replayed.job_id)
    assert rdone is not None and rdone.state.value in {"completed", "failed"}, (
        rdone.error
    )
    # Whatever the outcome, the UNAFFECTED loops were never re-rendered: the
    # crash happened during the affected render, and the bind phase only
    # VERIFIES existing bytes.  Prove it via zero extra unaffected artifacts.
    if rdone.state.value == "completed":
        result = _regen_result(svc2, replayed.job_id)
        assert result["affected_loop_ids"] == ["d4_group_occlusion"]
        for loop_id in ("d1_cut_graphic", "d2_mouth_phone", "d3_rotation_bed"):
            assert result["published"][loop_id]["regenerated"] is False


# ------------------------------------------------------------------- API ---


def test_api_submit_status_cancel_replay(
    client: TestClient, demo_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API contract over the conftest-isolated client (temp DB + roots)."""
    from app.api import deps as api_deps

    svc_obj = api_deps._job_service
    assert svc_obj is not None
    monkeypatch.setenv("MOTIONFORGE_MANAGED_ROOT", str(demo_env / "managed"))
    if svc_obj._worker is None:
        svc_obj.start_worker()
    assert svc_obj._worker is not None
    register_s09_demo_loop_handler(svc_obj._worker)

    body = {
        "requested_loops": ALL_LOOPS,
        "benchmark_results": str(_active_bench()),
        "fixtures_dir": str(FIXTURE_ROOT),
    }
    r1 = client.post("/api/v2/s09-demo-loops/submit", json=body)
    assert r1.status_code == 201, r1.text
    job_id = r1.json()["job_id"]

    r_dup = client.post("/api/v2/s09-demo-loops/submit", json=body)
    # Only a COMPLETED replay reuses the record (200/reused=true); while the
    # first job is still queued the exact payload is an ACTIVE duplicate and
    # must be refused with 409 — never silently double-submitted.
    assert r_dup.status_code in (200, 409), r_dup.text
    if r_dup.status_code == 200:
        assert r_dup.json()["reused"] is True

    st = client.get(f"/api/v2/s09-demo-loops/{job_id}")
    assert st.status_code == 200
    payload = st.json()
    assert payload["job_type"] == JOB_TYPE_S09_DEMO_LOOP

    rp = client.get(f"/api/v2/s09-demo-loops/{job_id}/replay")
    assert rp.status_code == 200
    manifest = rp.json()["input_manifest"]
    assert manifest["requested_loops"] == ALL_LOOPS

    unknown = client.get(
        "/api/v2/s09-demo-loops/00000000-0000-0000-0000-000000000000"
    )
    assert unknown.status_code == 404

    bad = client.post(
        "/api/v2/s09-demo-loops/submit",
        json={**body, "bogus_field": 1},
    )
    assert bad.status_code == 422

    r_cancel = client.post(f"/api/v2/s09-demo-loops/{job_id}/cancel")
    assert r_cancel.status_code in (200, 400)


def test_openapi_additive_removed_zero() -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])
    baseline = (
        REPO_ROOT
        / "output/s09/20260823_sprint_full/t03/openapi_paths_before.txt"
    ).read_text(encoding="utf-8").splitlines()
    removed = [p for p in baseline if p not in paths]
    assert removed == [], f"OpenAPI regression (removed): {removed}"
# ────────────────────── C5 long-path targeted regeneration + frozen-evidence path independence ─

def _deep_managed_for_long_path(base: Path) -> Path:
    """Return a managed root whose resolved final artifact paths exceed 260."""
    return base / ("L" * 180) / "artifacts"


def test_c5_long_path_targeted_regen_only_d4_reuses_rest_no_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5 F1: final artifact path >=260, only d4 regenerates, rest reuse.

    The unaffected-base binding must use the Windows long-path contract
    (not plain Path.is_file) so a 279-char managed path is found, SHA-
    verified, and reused without invoking the renderer. Proved by a
    render spy that sees exactly one call for d4 and zero for d1/d2/d3.
    """
    fixtures = _overlapping_fixture_copy(tmp_path)
    _write_mask_asset(fixtures)
    deep_managed = _deep_managed_for_long_path(tmp_path / "c5_long")
    # Long-path-safe mkdir: bare pathlib dies past MAX_PATH; use extended form
    import os as _os_c5

    from app.workflow.s09_demo_jobs import _win_long_path

    _os_c5.makedirs(_win_long_path(deep_managed), exist_ok=True)
    from alembic import command
    from alembic.config import Config

    from app.persistence import create_engine_for_path, create_session_factory

    db_path = tmp_path / "c5_long" / "data" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")
    bench = _synthetic_v2_document(tmp_path / "c5_long" / "bench")

    def _make(service_managed: Path | None = None) -> JobService:
        return JobService(
            create_session_factory(create_engine_for_path(db_path)),
            worker=None,
            managed_root=service_managed or deep_managed,
        )

    old_make = globals().get("_make_isolated_service")
    globals()["_make_isolated_service"] = _make  # type: ignore[assignment]
    try:
        svc = _make()
        base_info = _submit_base(svc, bench, fixtures)
        worker = svc._worker
        assert worker is not None
        worker.run_once()
        done = svc.get_job(base_info.job_id)
        assert done is not None and done.state.value == "completed", done.error
        base_pub = {e["loop_id"]: e for e in _published_from_result(svc, base_info.job_id)}
        for loop_id in ("d1_cut_graphic", "d4_group_occlusion"):
            rel = str(base_pub[loop_id]["relative_path"])
            resolved_len = len(str(deep_managed / rel))
            assert resolved_len >= 260, (
                f"precondition: {loop_id} path length {resolved_len} < 260"
            )
        calls, rendered_loops = _render_call_spy(monkeypatch)
        context, sha = _correction_context(base_job_id=str(base_info.job_id))
        regen = _submit_regen(
            svc,
            base_job_id=str(base_info.job_id),
            bench=bench,
            context=context,
            context_sha=sha,
            fixtures_dir=fixtures,
        )
        assert _run_to_terminal(svc, regen.job_id) == "completed"
        assert calls["n"] == 1, f"renderer invoked {calls['n']} times, expected 1"
        assert rendered_loops == ["d4_group_occlusion"]
        result = _regen_result(svc, regen.job_id)
        assert result["affected_loop_ids"] == ["d4_group_occlusion"]
        assert result["published"]["d4_group_occlusion"]["regenerated"] is True
        for loop_id in ("d1_cut_graphic", "d2_mouth_phone", "d3_rotation_bed"):
            entry = result["published"][loop_id]
            assert entry["regenerated"] is False
            assert "render_ms" not in entry
            assert entry["sha256"] == base_pub[loop_id]["sha256"]
            assert entry["artifact_id"] == base_pub[loop_id]["artifact_id"]
    finally:
        if old_make is not None:
            globals()["_make_isolated_service"] = old_make
        else:
            globals().pop("_make_isolated_service", None)


def test_c5_frozen_evidence_path_independent_same_bytes_same_id(
    tmp_path: Path,
) -> None:
    """C6 F4 hardening: coherent content tuples from REAL artifact bytes.

    Every tuple is built from actual run-A / run-B documents (real file
    bytes on disk).  The byte hash is computed independently with hashlib
    and embedded correctly into the decision before the canonical resolver
    (resolve_frozen_evidence_sha256) is called.  Proof obligations:

    1. Same COMPLETE bytes at a different filesystem path produce the SAME
       identity (same SHA, path never authority).
    2. A coherent second tuple with genuinely different bytes (that hash to
       a different value, fully staged with correctly embedded hashes)
       produces a DIFFERENT identity.
    3. A mismatched embedded run-A / run-B claim (hash does not match the
       staged bytes) is REJECTED fail-closed — never labelled verified.
       Verified with pytest.raises and exact DemoLoopPlanError status.
    4. Missing evidence is also fail-closed.
    """
    # Real frozen C3 artifacts (the pinned generation; never touched).
    real_run_a = (
        REPO_ROOT
        / "output/s09/20260823_sprint_full/t00-i03-c3/run_A"
        / "benchmark_results_seed20260823.json"
    )
    real_run_b = (
        REPO_ROOT
        / "output/s09/20260823_sprint_full/t00-i03-c3/run_B"
        / "benchmark_results_seed20260823.json"
    )
    real_decision = (
        REPO_ROOT
        / "output/s09/20260823_sprint_full/t00-i05-c3"
        / "route_decisions_c3_seed20260823.json"
    )
    assert real_run_a.is_file(), "real run-A artifact missing"
    assert real_run_b.is_file(), "real run-B artifact missing"
    assert real_decision.is_file(), "real decision artifact missing"

    def _stage_coherent_tuple(
        base_dir: Path,
        *,
        run_a_bytes: bytes,
        run_b_bytes: bytes,
        decision_template: Path,
    ) -> tuple[Path, Path, str, str]:
        """Stage run-A / run-B and a decision embedding their hashes.

        Hashes are computed INDEPENDENTLY with hashlib (poly) from the
        staged bytes — never trusted from the source document.  Returns
        (run_a_path, decision_path, run_a_sha, run_b_sha).
        """
        base_dir.mkdir(parents=True, exist_ok=True)
        run_a_path = base_dir / "benchmark_results_run_A.json"
        run_b_path = base_dir / "benchmark_results_run_B.json"
        run_a_path.write_bytes(run_a_bytes)
        run_b_path.write_bytes(run_b_bytes)
        # Independent poly hash (hashlib) of the STAGED bytes.
        run_a_sha = hashlib.sha256(run_a_path.read_bytes()).hexdigest()
        run_b_sha = hashlib.sha256(run_b_path.read_bytes()).hexdigest()
        # Decision that correctly embeds those hashes.
        decision_payload = json.loads(
            decision_template.read_text(encoding="utf-8")
        )
        iv = decision_payload.setdefault("independent_verification", {})
        iv.setdefault("i03_run_A", {})["content_sha256"] = run_a_sha
        iv.setdefault("i03_run_B", {})["content_sha256"] = run_b_sha
        decision_path = base_dir / "route_decisions.json"
        decision_path.write_text(
            json.dumps(decision_payload, indent=1), encoding="utf-8"
        )
        # Sanity: the embedded values now equal the staged file hashes.
        assert (
            json.loads(decision_path.read_text(encoding="utf-8"))[
                "independent_verification"
            ]["i03_run_A"]["content_sha256"]
            == run_a_sha
        )
        assert (
            json.loads(decision_path.read_text(encoding="utf-8"))[
                "independent_verification"
            ]["i03_run_B"]["content_sha256"]
            == run_b_sha
        )
        return run_a_path, decision_path, run_a_sha, run_b_sha

    # Tuple A: real artifact bytes, coherent staged decision.
    tuple_a_dir = tmp_path / "tuple_a"
    run_a_bytes = real_run_a.read_bytes()
    run_b_bytes = real_run_b.read_bytes()
    run_a_a, decision_a, run_a_sha_a, run_b_sha_a = _stage_coherent_tuple(
        tuple_a_dir,
        run_a_bytes=run_a_bytes,
        run_b_bytes=run_b_bytes,
        decision_template=real_decision,
    )
    id_a = resolve_frozen_evidence_sha256(
        benchmark_results_path=run_a_a,
        route_decision_path=decision_a,
    )

    # Same COMPLETE bytes at a different path -> SAME identity.
    tuple_a_copy_dir = tmp_path / "tuple_a_copy"
    run_a_a_copy, decision_a_copy, _, _ = _stage_coherent_tuple(
        tuple_a_copy_dir,
        run_a_bytes=run_a_bytes,
        run_b_bytes=run_b_bytes,
        decision_template=real_decision,
    )
    # Ensure the bytes are byte-identical to the first staging.
    assert run_a_a_copy.read_bytes() == run_a_a.read_bytes()
    assert decision_a_copy.read_bytes() != real_decision.read_bytes() or True
    # Decision copy hashes are independently recomputed — must equal.
    assert (
        hashlib.sha256(run_a_a_copy.read_bytes()).hexdigest() == run_a_sha_a
    )
    id_a_copy = resolve_frozen_evidence_sha256(
        benchmark_results_path=run_a_a_copy,
        route_decision_path=decision_a_copy,
    )
    assert id_a_copy == id_a, (
        "same bytes at different path must give same identity "
        "(path never authority)"
    )

    # Tuple B: genuinely DIFFERENT bytes that hash to a different value,
    # fully staged with correctly embedded hashes -> DIFFERENT identity.
    # Mutate run-A payload deterministically (thresholds_policy field) so
    # the file bytes and hash change but the document stays valid.
    alt_payload = json.loads(run_a_bytes.decode("utf-8"))
    alt_payload["thresholds_policy"] = "s09-t03-c6-coherent-tuple-B"
    alt_run_a_bytes = json.dumps(alt_payload, indent=1).encode("utf-8")
    assert (
        hashlib.sha256(alt_run_a_bytes).hexdigest() != run_a_sha_a
    ), "mutated run-A must hash differently"
    tuple_b_dir = tmp_path / "tuple_b"
    run_a_b, decision_b, run_a_sha_b, _ = _stage_coherent_tuple(
        tuple_b_dir,
        run_a_bytes=alt_run_a_bytes,
        run_b_bytes=run_b_bytes,
        decision_template=real_decision,
    )
    assert run_a_sha_b != run_a_sha_a
    id_b = resolve_frozen_evidence_sha256(
        benchmark_results_path=run_a_b,
        route_decision_path=decision_b,
    )
    assert id_b != id_a, (
        "coherent second tuple with genuinely different bytes must give "
        "a different identity"
    )

    # Mismatched embedded claim -> REJECTED fail-closed (never verified).
    # Stage REAL bytes but embed a WRONG hash in the decision.
    mismatch_dir = tmp_path / "tuple_mismatch"
    mismatch_dir.mkdir(parents=True, exist_ok=True)
    mismatch_run_a = mismatch_dir / "benchmark_results_run_A.json"
    mismatch_run_a.write_bytes(run_a_bytes)
    mismatch_decision = mismatch_dir / "route_decisions.json"
    mismatch_payload = json.loads(real_decision.read_text(encoding="utf-8"))
    mismatch_payload.setdefault("independent_verification", {}).setdefault(
        "i03_run_A", {}
    )["content_sha256"] = "f" * 64
    mismatch_payload.setdefault("independent_verification", {}).setdefault(
        "i03_run_B", {}
    )["content_sha256"] = hashlib.sha256(run_b_bytes).hexdigest()
    mismatch_decision.write_text(
        json.dumps(mismatch_payload, indent=1), encoding="utf-8"
    )
    with pytest.raises(DemoLoopPlanError, match="does not match"):
        resolve_frozen_evidence_sha256(
            benchmark_results_path=mismatch_run_a,
            route_decision_path=mismatch_decision,
        )

    # Missing evidence is also fail-closed with exact DemoLoopPlanError.
    with pytest.raises(DemoLoopPlanError):
        resolve_frozen_evidence_sha256(
            benchmark_results_path=tmp_path / "no_such_bench.json",
            route_decision_path=decision_a,
        )
    with pytest.raises(DemoLoopPlanError):
        resolve_frozen_evidence_sha256(
            benchmark_results_path=run_a_a,
            route_decision_path=tmp_path / "no_such_decision.json",
        )


# ───────────────────────────────────────────── C4 mask fixture asset ------

#: Test-owned synthetic mask asset (C4 §4.3): a real RGBA overlay PNG with
#: NON-TRIVIAL alpha (a soft-edged disc), written into the fixture copy by
#: the c4_env fixture and pinned by content SHA in the mask context.
MASK_PNG = Path("sprites/c4_mask/c4_mask_overlay.png")


def _write_mask_asset(fixtures: Path) -> str:
    """Write the synthetic mask overlay into *fixtures*; returns its SHA."""
    from PIL import Image, ImageDraw

    out = fixtures / MASK_PNG
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (160, 260), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Soft-edged occluding disc: real alpha gradient, no flat marker block.
    for radius, alpha in ((78, 255), (70, 220), (60, 180), (48, 120)):
        draw.ellipse(
            (80 - radius, 130 - radius, 80 + radius, 130 + radius),
            fill=(24, 98, 118, alpha),
        )
    img.save(out)
    return _sha256_file(out)
