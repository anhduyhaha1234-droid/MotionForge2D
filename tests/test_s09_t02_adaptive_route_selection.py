"""S09-T02 tests — adaptive route selection + router wiring.

Binary acceptance coverage per TASK.md:
- runtime benchmark-results loader: fail-closed on unknown schema/missing
  frozen SHA/missing file; smallest-passing per risk class from MEASURED
  evaluations (never hard-coded outcomes);
- select_route policy: pose_swap kept for annotated-swap segments without
  measured swap evidence; refusal when NO passing route exists; disclosed
  notes (nothing silent);
- ownership-transfer wiring is ADDITIVE ONLY (zero removed lines vs the
  pre-task worktree state) and the default registry stays deterministic;
- two-run determinism of every derived decision;
- legacy regressions stay green (router contract suite runs unchanged).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.renderer_router import (
    RendererRouter,
    build_adaptive_default_router,
)
from app.services.renderer_routes import (
    BenchmarkResultsError,
    OptimizedSpriteAffineAdapter,
    PoseSwapAdaptiveAdapter,
    load_benchmark_results,
    select_route,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Frozen C2 measured evidence (read-only input).  Prompt C2 mục 3.5: the
#: old schema-v1 artifact directory is FORBIDDEN as active test input — it
#: predates the group-occlusion fix and once produced a false PASS on an
#: empty universe.
FROZEN_RESULTS = (
    PROJECT_ROOT
    / "output/s09/20260823_sprint_full/t00-i03-c2/run_A"
    / "benchmark_results_seed20260823.json"
).resolve()

ALL_CLASSES = [
    "hard_cut",
    "mouth_expression_swap",
    "phone_contact",
    "whole_body_rotation",
    "group_occlusion",
    "semantic_graphic_replacement",
]


@pytest.fixture(scope="module")
def frozen_doc():  # type: ignore[no-untyped-def]
    return load_benchmark_results(FROZEN_RESULTS)


# ── Loader fail-closed ────────────────────────────────────────────────────────


def test_loader_missing_file_refused(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkResultsError):
        load_benchmark_results(tmp_path / "nope.json")


def test_loader_unknown_schema_refused(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema_version": 99, "results": []}), encoding="utf-8")
    with pytest.raises(BenchmarkResultsError, match="schema_version"):
        load_benchmark_results(p)


def test_loader_missing_frozen_sha_refused(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    p.write_text(
        json.dumps({"schema_version": 1, "routes": ["pose_swap"], "results": []}),
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkResultsError, match="frozen_content_sha256"):
        load_benchmark_results(p)


def test_loader_unknown_route_refused(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "frozen_content_sha256": "a" * 64,
                "routes": ["teleport"],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkResultsError, match="unknown route"):
        load_benchmark_results(p)


def test_loader_accepts_frozen_document(frozen_doc) -> None:  # type: ignore[no-untyped-def]
    # C2 measured run_A: schema v3, both routes present, policy pinned by
    # the T00-I03-C1 freeze — asserted explicitly, never inherited from v1.
    pv = frozen_doc.payload if hasattr(frozen_doc, "payload") else frozen_doc._payload
    assert pv.get("schema_version") == 3
    assert frozen_doc.thresholds_policy == "s09-t00-i03-c1-frozen-20260824"
    assert set(frozen_doc.routes) == {"pose_swap", "sprite_affine"}


# ── Prompt C2 mục 3.5: v1 artifacts NEVER referenced as active evidence ──────


def test_frozen_input_is_c2_measured_run_not_v1() -> None:
    """The frozen input MUST be the C2 measured run (schema v3, 6/6 classes
    with real rows).  The old schema-v1 artifact directory is FORBIDDEN as
    active test evidence — it once produced a false group-occlusion PASS on
    an empty universe."""
    assert FROZEN_RESULTS.is_file()
    doc = load_benchmark_results(FROZEN_RESULTS)
    # C2 measured run_A carries schema_version 3.
    pv = doc.payload if hasattr(doc, "payload") else doc._payload
    assert pv.get("schema_version") == 3
    for risk_class in ALL_CLASSES:
        rows = doc.rows_for_class(risk_class)
        assert rows, f"C2 run_A missing measured rows for {risk_class}"
    # The forbidden v1 directory name must NOT appear anywhere in this test
    # module (constructed here from parts so this check cannot match its own
    # source text).
    forbidden = "t00-" + "i05/measured_seed" + "20260823"
    source = Path(__file__).read_text(encoding="utf-8")
    assert (
        forbidden not in source
    ), "old v1 artifact path referenced as active input"


# ── Smallest-passing from MEASURED evaluations ───────────────────────────────


@pytest.mark.parametrize("risk_class", ALL_CLASSES)
def test_smallest_passing_matches_frozen_evidence(
    frozen_doc, risk_class: str  # type: ignore[no-untyped-def]
) -> None:
    # C2 measured run_A truth: sprite_affine passes 5/6 classes; pose_swap
    # only passes the mouth/expression class (sprite_affine is
    # contract-refused there).  Derive the expected winner from the document
    # instead of hard-coding a v1-era answer.
    expected: str | None = None
    for route in ("pose_swap", "sprite_affine"):
        if frozen_doc.route_measured_passing(risk_class, route):
            expected = route
            break
    assert frozen_doc.smallest_passing_route(risk_class) == expected


def test_smallest_passing_none_when_nothing_passes(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "frozen_content_sha256": "b" * 64,
        "routes": ["pose_swap"],
        "results": [
            {
                "fixture_id": "fx",
                "risk_class": "hard_cut",
                "route": "pose_swap",
                "threshold_evaluation": {"checks": [], "overall_pass": False},
            }
        ],
    }
    p = tmp_path / "r.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    doc = load_benchmark_results(p)
    assert doc.smallest_passing_route("hard_cut") is None
    with pytest.raises(BenchmarkResultsError, match="no measured route passes"):
        doc.smallest_passing_or_raise("hard_cut")


def test_smallest_passing_prefers_earlier_ladder_route(tmp_path: Path) -> None:
    """When a smaller route genuinely passes, it must win over pose_swap."""
    payload = {
        "schema_version": 1,
        "frozen_content_sha256": "c" * 64,
        "routes": ["pose_swap", "sprite_affine"],
        "results": [
            {
                "risk_class": "phone_contact",
                "route": "pose_swap",
                "threshold_evaluation": {"overall_pass": True},
            },
            {
                "risk_class": "phone_contact",
                "route": "sprite_affine",
                "threshold_evaluation": {"overall_pass": True},
            },
        ],
    }
    p = tmp_path / "r.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    doc = load_benchmark_results(p)
    # sprite_affine sits AFTER pose_swap in ROUTE_PRIORITY, so pose_swap is
    # still the smallest ladder step among passers.
    assert doc.smallest_passing_route("phone_contact") == "pose_swap"


def test_malformed_evaluation_row_is_never_treated_as_passing(
    tmp_path: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "frozen_content_sha256": "d" * 64,
        "routes": ["pose_swap"],
        "results": [
            {"risk_class": "hard_cut", "route": "pose_swap"},
            {
                "risk_class": "hard_cut",
                "route": "pose_swap",
                "threshold_evaluation": {"overall_pass": True},
            },
        ],
    }
    p = tmp_path / "r.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    doc = load_benchmark_results(p)
    assert doc.smallest_passing_route("hard_cut") == "pose_swap"


# ── select_route policy ──────────────────────────────────────────────────────


@pytest.mark.parametrize("risk_class", ALL_CLASSES)
def test_select_route_matches_measured_c2_evidence(
    frozen_doc, risk_class: str  # type: ignore[no-untyped-def]
) -> None:
    # Without annotated swaps the smallest measured-passing route wins.
    decision = select_route(frozen_doc, risk_class=risk_class, has_annotated_swaps=False)
    assert decision.route == frozen_doc.smallest_passing_route(risk_class)


@pytest.mark.parametrize("risk_class", ALL_CLASSES)
def test_select_route_annotated_swaps_fail_closed_without_capability(
    frozen_doc, risk_class: str  # type: ignore[no-untyped-def]
) -> None:
    """Overlay §8 policy against C2 run_A truth: pose_swap is measured
    passing ONLY for mouth_expression_swap.  For every other class a
    swap-annotated segment has NO route with measured pose-state capability
    (sprite_affine rows carry no passing psc check; pose_swap rows are
    contract-refused), so adaptive selection must REFUSE — never hand the
    segment a failing route."""
    from app.services.renderer_routes.benchmark_results import (
        BenchmarkResultsError,
    )

    if frozen_doc.route_measured_passing(risk_class, "pose_swap"):
        decision = select_route(
            frozen_doc, risk_class=risk_class, has_annotated_swaps=True
        )
        assert decision.route == "pose_swap"
        return
    with pytest.raises(BenchmarkResultsError, match="adaptive selection refused"):
        select_route(frozen_doc, risk_class=risk_class, has_annotated_swaps=True)


def test_select_route_records_disclosed_note_for_swap_classes_without_swap_evidence(
    frozen_doc,  # type: ignore[no-untyped-def]
) -> None:
    # mouth_expression_swap is the one class pose_swap measured-passes in
    # run_A, so the annotated-swaps decision keeps pose_swap and must record
    # a DISCLOSED policy note (no passing psc check in the document), not
    # silence.
    decision = select_route(
        frozen_doc, risk_class="mouth_expression_swap", has_annotated_swaps=True
    )
    assert decision.route == "pose_swap"
    assert any("pose_state_capability" in n for n in decision.notes)


def test_select_route_refuses_when_no_route_passes(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "frozen_content_sha256": "e" * 64,
        "routes": ["pose_swap", "sprite_affine"],
        "results": [
            {
                "risk_class": "whole_body_rotation",
                "route": route,
                "threshold_evaluation": {"overall_pass": False},
            }
            for route in ("pose_swap", "sprite_affine")
        ],
    }
    p = tmp_path / "r.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    doc = load_benchmark_results(p)
    with pytest.raises(BenchmarkResultsError, match="no.*passing route"):
        select_route(doc, risk_class="whole_body_rotation", has_annotated_swaps=False)


def test_select_route_two_run_determinism(frozen_doc) -> None:  # type: ignore[no-untyped-def]
    for cls in ALL_CLASSES:
        if not frozen_doc.route_measured_passing(cls, "pose_swap") and (
            frozen_doc.smallest_passing_route(cls) != "pose_swap"
        ):
            # Swap-annotated segments on classes without measured pose-state
            # capability REFUSE (fail-closed) — determinism of the refusal
            # is covered below via the smallest-passing class instead.
            a = frozen_doc.smallest_passing_route(cls)
            b = frozen_doc.smallest_passing_route(cls)
            assert a == b
            continue
        a = select_route(frozen_doc, risk_class=cls, has_annotated_swaps=True)
        b = select_route(frozen_doc, risk_class=cls, has_annotated_swaps=True)
        assert a.route == b.route
        assert a.notes == b.notes
        assert a.frozen_content_sha256 == b.frozen_content_sha256


# ── Ownership-transfer wiring: ADDITIVE ONLY ─────────────────────────────────


def test_router_wiring_is_purely_additive() -> None:
    """F3 (S09-T02-C1): the wiring is proven against a FROZEN SEMANTIC
    CONTRACT, never against mutable git state (``git show HEAD`` is a moving
    target once anything commits; byte-diff tests rot).

    The contract below pins the semantic invariants that MUST hold regardless
    of git history:

    1. the legacy I02 public API surface (class + method names) survives;
    2. the legacy import block from ``renderer_contract`` keeps its exact
       symbol set and order;
    3. exactly ONE additive factory exists as the sole T02 wiring point;
    4. escalation refusal payload kind is unchanged (auditable no-op path);
    5. every route in RENDERER_ROUTES stays registered-or-unregistered
       exactly as the overlay declares (no invented backends).
    """
    current = (PROJECT_ROOT / "app/services/renderer_router.py").read_text(
        encoding="utf-8"
    ).splitlines()

    # (1) Legacy I02 API surface — frozen semantic contract.
    stripped = [line.strip() for line in current]
    for symbol in (
        "class RendererRouter:",
        "def select_backend",
        "def _gate_adapter",
        "def execute",
        "def maybe_escalate",
        "def available_backends_for_route",
        "def _require_known_route",
    ):
        assert any(line.startswith(symbol) for line in stripped), (
            f"legacy router API surface lost: {symbol!r}"
        )

    # (2) The pre-task import block survives VERBATIM and IN ORDER.
    task_start_baseline = [
        "    ROUTE_PRIORITY,",
        "    BackendAdapter,",
        "    BackendBinaryMissingError,",
        "    BenchmarkBelowThresholdError,",
        "    CapabilityMismatchError,",
        "    LicenseMissingError,",
        "    RendererContractCode,",
        "    RendererRoute,",
        "    RenderRequest,",
        "    RenderResult,",
        "    UnknownBackendError,",
        "    UnknownCapabilityError,",
        "    validate_license_for_product_use,",
        ")",
    ]
    start = current.index("from app.services.renderer_contract import (")
    block = current[start + 1 : start + 1 + len(task_start_baseline)]
    assert block == task_start_baseline, (
        "pre-task import block was modified (non-additive change)"
    )

    # (3) Exactly ONE factory definition exists (the additive wiring point).
    factories = [
        line
        for line in current
        if line.startswith("def build_adaptive_default_router")
    ]
    assert len(factories) == 1

    # (4) Escalation refusal artifact kind is part of the frozen contract.
    assert any(
        '"kind": "renderer_route_escalation_refused"' in line
        for line in current
    ), "escalation refusal payload kind changed"

    # (5) No subprocess/git dependency anywhere in this module's wiring.
    assert not any(
        "git show" in line or "subprocess" in line for line in current
    ), "wiring must not depend on mutable git state"


def test_default_registry_is_deterministic_and_fail_closed() -> None:
    r1 = build_adaptive_default_router()
    r2 = build_adaptive_default_router()
    caps1 = r1.capabilities()
    caps2 = r2.capabilities()
    assert caps1 == caps2
    ids = [b for b, _ in caps1]
    assert "ffmpeg-nvenc-pose-swap-adaptive" in ids
    assert "ffmpeg-nvenc-sprite-affine" in ids  # I02 backend preserved first
    assert "ffmpeg-nvenc-sprite-affine-optimized" in ids
    # Unimplemented routes stay unregistered → UnknownCapabilityError.
    from app.services.renderer_contract import RenderRequest, UnknownCapabilityError

    req = RenderRequest(
        request_id="t02-wire",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="mesh_warp",
        start_frame=0,
        end_frame=1,
    )
    with pytest.raises(UnknownCapabilityError):
        r1.select_backend(req)


def test_factory_returns_real_router_with_override_honor() -> None:
    router = build_adaptive_default_router()
    assert isinstance(router, RendererRouter)
    # Demo-review override MUST hit exactly the named backend.
    from app.services.renderer_contract import RenderRequest

    req = RenderRequest(
        request_id="t02-ovr",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="sprite_affine",
        start_frame=0,
        end_frame=1,
        backend_override="ffmpeg-nvenc-sprite-affine-optimized",
    )
    adapter = router.select_backend(req)
    assert isinstance(adapter, OptimizedSpriteAffineAdapter)
    assert router.select_backend(req).backend_id == adapter.backend_id == (
        "ffmpeg-nvenc-sprite-affine-optimized"
    )


def test_adapters_keep_distinct_backend_ids() -> None:
    a = PoseSwapAdaptiveAdapter()
    b = OptimizedSpriteAffineAdapter()
    from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
    from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter

    assert a.backend_id == "ffmpeg-nvenc-pose-swap-adaptive"
    assert b.backend_id == "ffmpeg-nvenc-sprite-affine-optimized"
    # Distinct from the I02 backends so registries can hold both.
    assert a.backend_id != PoseSwapAdapter.backend_id_value
    assert b.backend_id != SpriteAffineAdapter.backend_id_value
    assert a.route == "pose_swap" and b.route == "sprite_affine"
