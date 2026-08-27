"""S09-T00-I02 tests — RendererRouter/failure/license contract.

Binary acceptance per TASK.md:
- deterministic registry ordering;
- route selection / explicit override / provenance on escalation;
- failure taxonomy: EVERY code raises its own exception type (unknown backend,
  unknown capability, license_missing, capability_mismatch,
  benchmark_below_threshold, binary missing);
- escalation ONLY when measured error strictly exceeds the gate AND reduces
  with the next route; evidence artifact written either way;
- unknown backend FAILS CLOSED (no silent fallback, never a result from a
  different backend than requested);
- no NC/no-permission license can pass the product gate;
- route persisted per segment via StructuralLockRepository round-trip.

Fixture metrics are allowed in tests; production modules contain no stubs —
the adapters execute REAL FFmpeg/NVENC processes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter
from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import RENDERER_ROUTES
from app.persistence.structural_lock import (
    StructuralLockRepository,
)
from app.services.renderer_contract import (
    BACKEND_LICENSE_REGISTRY,
    PROVENANCE_REQUIRED_FIELDS,
    BenchmarkBelowThresholdError,
    CapabilityDescriptor,
    CapabilityMismatchError,
    LicenseMissingError,
    RenderRequest,
    RouteProvenance,
    UnknownBackendError,
    UnknownCapabilityError,
    validate_license_for_product_use,
)
from app.services.renderer_router import RendererRouter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS_A = "ws-router-a"


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


@pytest.fixture()
def migrated(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Yield (factory, ids) on a fully-migrated temp DB with one segment."""
    db = tmp_path / "router.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    ws = WS_A
    p, v = f"p-{ws}", f"v-{ws}"
    with factory() as seed:
        seed.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
        seed.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
            {"p": p, "w": ws},
        )
        seed.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position)"
                " VALUES (:v,:p,'Vid',0)"
            ),
            {"v": v, "p": p},
        )
        seed.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
                "start_time_ms,end_time_ms,status) VALUES ('sc',:v,0,0,100,0,3000,'pending')"
            ),
            {"v": v},
        )
        seed.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) VALUES ('rl',:w,:p,:v,'g','C',"
                "'character','confirmed')"
            ),
            {"w": ws, "p": p, "v": v},
        )
        seed.execute(
            text(
                "INSERT INTO occurrence_segment(id,workspace_id,project_id,"
                "video_item_id,role_id,scene_id,logical_id,lineage_version,name,kind,"
                "start_frame,end_frame,start_time_ms,end_time_ms,source_generation,"
                "confidence,confidence_source,reasons_json,visibility,z_order,revision)"
                " VALUES ('sg',:w,:p,:v,'rl','sc','lg',1,'C','character',0,100,0,3000,"
                "'g',0.9,'model','[]','visible',0,1)"
            ),
            {"w": ws, "p": p, "v": v},
        )
        seed.commit()
    yield factory, {"workspace_id": ws, "project_id": p, "video_item_id": v}
    engine = create_engine_for_path(db)
    engine.dispose()


# ── Fake adapter (test-only) ─────────────────────────────────────────────────


@dataclass
class FakeAdapter:
    backend_id_value: str
    route_value: str
    cap: CapabilityDescriptor

    @property
    def backend_id(self) -> str:
        return self.backend_id_value

    @property
    def route(self) -> str:
        return self.route_value

    def capability(self) -> CapabilityDescriptor:
        return self.cap

    def render(self, request: RenderRequest) -> Any:  # pragma: no cover - unused
        raise AssertionError("fake adapter must not render in these tests")


def _cap(
    backend: str,
    route: str,
    *,
    available: bool = True,
    license_id: str = "ffmpeg-gpl-build",
    runtime: float | None = None,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        backend_id=backend,
        route=route,
        available=available,
        license_id=license_id,
        runtime_ms_per_frame=runtime,
        evidence_source="measured_live",
    )


# ── Registry determinism ─────────────────────────────────────────────────────


def test_registry_ordering_is_deterministic(tmp_path: Path) -> None:
    adapters = [
        FakeAdapter("b-sprite", "sprite_affine", _cap("b-sprite", "sprite_affine")),
        FakeAdapter("a-pose", "pose_swap", _cap("a-pose", "pose_swap")),
        FakeAdapter("z-mesh", "mesh_warp", _cap("z-mesh", "mesh_warp")),
    ]
    listing_1 = RendererRouter(adapters, evidence_dir=tmp_path).capabilities()
    # Rebuild in a different insertion order — same registry output.
    listing_2 = RendererRouter(
        list(reversed(adapters)), evidence_dir=tmp_path
    ).capabilities()
    assert listing_1 == listing_2 == [
        ("a-pose", "pose_swap"),
        ("b-sprite", "sprite_affine"),
        ("z-mesh", "mesh_warp"),
    ]


# ── Failure taxonomy: each code raises ITS exception ─────────────────────────


def test_unknown_backend_override_fails_closed(tmp_path: Path) -> None:
    router = RendererRouter(
        [PoseSwapAdapter(), SpriteAffineAdapter()], evidence_dir=tmp_path
    )
    request = RenderRequest(
        request_id="r1",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="pose_swap",
        start_frame=0,
        end_frame=10,
        backend_override="does-not-exist",
    )
    with pytest.raises(UnknownBackendError):
        router.select_backend(request)


def test_unknown_capability_route_without_backends_fails_closed(
    tmp_path: Path,
) -> None:
    router = RendererRouter([PoseSwapAdapter()], evidence_dir=tmp_path)
    request = RenderRequest(
        request_id="r2",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="controlled_redraw",  # registered route, NO backend wired
        start_frame=0,
        end_frame=10,
    )
    with pytest.raises(UnknownCapabilityError):
        router.select_backend(request)


def test_license_missing_refused_in_selection_and_gate(tmp_path: Path) -> None:
    unlicensed = FakeAdapter(
        "unlicensed-backend",
        "pose_swap",
        _cap("unlicensed-backend", "pose_swap", license_id="some-unknown-license"),
    )
    router = RendererRouter([unlicensed], evidence_dir=tmp_path)
    request = RenderRequest(
        request_id="r3",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="pose_swap",
        start_frame=0,
        end_frame=10,
    )
    # Selection with the ONLY candidate unlicensed raises the EXACT taxonomy
    # error (single-backend gate failures keep their code — TASK.md binary
    # acceptance: each failure kind raises its own exception type).
    from app.services.renderer_contract import RendererRouterError

    with pytest.raises(LicenseMissingError) as exc_info:
        router.select_backend(request)
    assert isinstance(exc_info.value, RendererRouterError)
    assert exc_info.value.code.value == "license_missing"
    # The raw gate raises the same specific taxonomy error.
    with pytest.raises(LicenseMissingError):
        validate_license_for_product_use("some-unknown-license")

    # With a LICENSED alternative present, selection deterministically serves
    # via the licensed backend — the unlicensed one is skipped, never used.
    licensed = FakeAdapter("licensed-backend", "pose_swap",
                           _cap("licensed-backend", "pose_swap"))
    router2 = RendererRouter([unlicensed, licensed], evidence_dir=tmp_path)
    chosen = router2.select_backend(request)
    assert chosen.backend_id == "licensed-backend"


@pytest.mark.parametrize(
    "forbidden",
    ["cc-by-nc-4.0", "CC-BY-NC-SA-4.0", "research-only", "non-commercial"],
)
def test_nc_no_permission_licenses_never_pass(forbidden: str) -> None:
    with pytest.raises(LicenseMissingError):
        validate_license_for_product_use(forbidden)


def test_benchmark_below_threshold_raises(tmp_path: Path) -> None:
    slow = FakeAdapter(
        "slow-backend",
        "sprite_affine",
        _cap("slow-backend", "sprite_affine", runtime=999.0),
    )
    router = RendererRouter([slow], evidence_dir=tmp_path)
    request = RenderRequest(
        request_id="r4",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="sprite_affine",
        start_frame=0,
        end_frame=10,
        max_runtime_ms_per_frame=50.0,
    )
    with pytest.raises(BenchmarkBelowThresholdError):
        router.select_backend(request)


def test_capability_mismatch_on_bad_route(tmp_path: Path) -> None:
    with pytest.raises(CapabilityMismatchError):
        RenderRequest(
            request_id="r5",
            workspace_id="ws",
            project_id="p",
            video_item_id="v",
            occurrence_segment_id="sg",
            route="not_a_route",
            start_frame=0,
            end_frame=10,
        )


def test_binary_missing_adapter_reports_fail_closed(tmp_path: Path) -> None:
    broken = FakeAdapter(
        "broken-binary",
        "mesh_warp",
        _cap("broken-binary", "mesh_warp", available=False),
    )
    router = RendererRouter([broken], evidence_dir=tmp_path)
    request = RenderRequest(
        request_id="r6",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="mesh_warp",
        start_frame=0,
        end_frame=10,
    )
    with pytest.raises(UnknownCapabilityError):
        router.select_backend(request)


# ── No silent fallback ───────────────────────────────────────────────────────


def test_router_never_returns_result_from_a_different_route(tmp_path: Path) -> None:
    """The only wired backend is pose_swap; sprite_affine asks MUST raise,
    never silently come back served by the pose_swap backend."""
    router = RendererRouter([PoseSwapAdapter()], evidence_dir=tmp_path)
    request = RenderRequest(
        request_id="r7",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="sprite_affine",
        start_frame=0,
        end_frame=10,
    )
    with pytest.raises((UnknownCapabilityError, UnknownBackendError)):
        result = router.execute(request)
        # Belt-and-braces: even IF a result came back it must be from an
        # adapter bound to the exact requested route.
        if result is not None and getattr(result, "route", None):
            assert result.route == "sprite_affine"


def test_execute_routes_to_exact_requested_backend(tmp_path: Path) -> None:
    class RenderingFake(FakeAdapter):
        def render(self, request: RenderRequest) -> Any:  # noqa: ARG002
            from app.services.renderer_contract import RenderResult

            return RenderResult(
                request_id=request.request_id,
                route=self.route,
                backend_id=self.backend_id,
                ok=True,
                frames_rendered=request.end_frame - request.start_frame + 1,
                wall_time_ms=1.0,
            )

    pose = RenderingFake("only-pose", "pose_swap", _cap("only-pose", "pose_swap"))
    router = RendererRouter([pose], evidence_dir=tmp_path)
    request = RenderRequest(
        request_id="r8",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="pose_swap",
        start_frame=0,
        end_frame=4,
    )
    result = router.execute(request)
    assert result.ok and result.backend_id == "only-pose" and result.route == "pose_swap"


# ── Escalation provenance ────────────────────────────────────────────────────


def _prov_fields(artifact: Path) -> dict[str, Any]:
    return {
        "segment_id": "sg",
        "route_from": "pose_swap",
        "route_to": "sprite_affine",
        "metric_name": "residual_silhouette_error_pct",
        "metric_value": 1.5,
        "threshold": 1.0,
        "evidence_artifact_path": str(artifact),
    }


def test_escalation_requires_measured_reduction(tmp_path: Path) -> None:
    router = RendererRouter([PoseSwapAdapter(), SpriteAffineAdapter()],
                            evidence_dir=tmp_path)
    artifact = tmp_path / "escalation.json"

    # Case 1: metric below threshold → refused, refusal evidence written.
    escalated, info = router.maybe_escalate(
        segment_id="sg",
        route_from="pose_swap",
        metric_name="residual_silhouette_error_pct",
        metric_value=0.5,
        threshold=1.0,
        candidate_route="sprite_affine",
        artifact_path=str(artifact),
    )
    assert escalated is False
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["kind"] == "renderer_route_escalation_refused"

    # Case 2: above threshold but NO reduction evidence → refused (fail closed).
    escalated2, _ = router.maybe_escalate(
        segment_id="sg",
        route_from="pose_swap",
        metric_name="residual_silhouette_error_pct",
        metric_value=1.5,
        threshold=1.0,
        candidate_route="sprite_affine",
        artifact_path=str(artifact),
    )
    assert escalated2 is False

    # Case 2b: projection present but WORSE than measured → refused.
    escalated2b, _ = router.maybe_escalate(
        segment_id="sg",
        route_from="pose_swap",
        metric_name="residual_silhouette_error_pct",
        metric_value=1.5,
        threshold=1.0,
        candidate_route="sprite_affine",
        artifact_path=str(artifact),
        candidate_metric_projection=1.8,
    )
    assert escalated2b is False

    # Case 3: above threshold AND projected reduction → escalate + full
    # five-field provenance + artifact exists.
    escalated3, record = router.maybe_escalate(
        segment_id="sg",
        route_from="pose_swap",
        metric_name="residual_silhouette_error_pct",
        metric_value=1.5,
        threshold=1.0,
        candidate_route="sprite_affine",
        artifact_path=str(artifact),
        candidate_metric_projection=0.7,
    )
    assert escalated3 is True
    rec = dict(record)  # type: ignore[arg-type]
    for field_name in PROVENANCE_REQUIRED_FIELDS:
        assert field_name in rec, f"missing {field_name}"
    assert json.loads(artifact.read_text(encoding="utf-8"))["route_to"] == "sprite_affine"
    assert artifact.is_file()

    # Backward escalation (affine→pose) is always refused as non-forward.
    artifact2 = tmp_path / "backward.json"
    escalated4, _ = router.maybe_escalate(
        segment_id="sg",
        route_from="sprite_affine",
        metric_name="x",
        metric_value=9.9,
        threshold=1.0,
        candidate_route="pose_swap",
        artifact_path=str(artifact2),
    )
    assert escalated4 is False


def test_provenance_dataclass_round_trip(tmp_path: Path) -> None:
    artifact = tmp_path / "prov.json"
    prov = RouteProvenance(**_prov_fields(artifact))
    path = prov.write_evidence(extra={"note": "unit"})
    data = json.loads(path.read_text(encoding="utf-8"))
    for field_name in PROVENANCE_REQUIRED_FIELDS:
        assert field_name in data
    assert data["extra"] == {"note": "unit"}
    assert path == artifact


# ── Persistence round-trip via SegmentRenderRoute ────────────────────────────


def test_route_persisted_per_segment_round_trip(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, ids = migrated
    with factory() as session:
        repo = StructuralLockRepository(session)
        record, created = repo.record_render_route(
            ids["workspace_id"],
            ids["project_id"],
            ids["video_item_id"],
            "sg",
            "sprite_affine",
            0.25,
            0.75,
            0,
            100,
            provenance={
                "kind": "renderer_route_decision",
                "backend_id": "ffmpeg-nvenc-sprite-affine",
                "metric_name": "runtime_ms_per_frame",
                "metric_value": 6.854,
            },
            reasons=["benchmark-measured"],
            algorithm="ffmpeg-segment-reencode",
            algorithm_version="8.1.2",
            confidence_source="measured" if False else "derived",
            idempotency_key="s09t00i02-roundtrip-1",
        )
        assert created is True
        assert record.route == "sprite_affine"
        assert record.provenance is not None
        assert record.provenance["backend_id"] == "ffmpeg-nvenc-sprite-affine"

        routes = repo.list_routes_for_video(
            ids["workspace_id"], ids["project_id"], ids["video_item_id"]
        )
        assert len(routes) == 1
        assert routes[0].id == record.id
        assert routes[0].anchor_x == pytest.approx(0.25)
        # Commit so the durable partial-unique index sees the row from the
        # NEXT transaction (the idempotency authority is the DB index).
        session.commit()

    # Idempotent replay in a NEW transaction returns the SAME row
    # (created=False).
    with factory() as session:
        repo = StructuralLockRepository(session)
        replay, created_again = repo.record_render_route(
            ids["workspace_id"],
            ids["project_id"],
            ids["video_item_id"],
            "sg",
            "sprite_affine",
            0.25,
            0.75,
            0,
            100,
            idempotency_key="s09t00i02-roundtrip-1",
        )
        assert created_again is False
        assert replay.id == record.id


def test_invalid_route_enum_refused_by_persistence(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, ids = migrated
    with factory() as session:
        repo = StructuralLockRepository(session)
        from app.persistence.structural_lock import StructuralLockParamsError

        with pytest.raises(StructuralLockParamsError):
            repo.record_render_route(
                ids["workspace_id"],
                ids["project_id"],
                ids["video_item_id"],
                "sg",
                "magic_route",  # not in RENDERER_ROUTES
                0.5,
                0.5,
                0,
                10,
            )


# ── License registry integrity ───────────────────────────────────────────────


def test_registry_entries_all_approved_and_nonforbidden() -> None:
    for license_id, entry in BACKEND_LICENSE_REGISTRY.items():
        assert entry.get("product_use") in ("approved", "approved-local-use")
        spdx = entry.get("spdx", "").lower()
        assert "nc" not in spdx.split("-") or "commercial" not in spdx
        validate_license_for_product_use(license_id)  # must not raise


def test_renderer_routes_single_authority_unchanged() -> None:
    assert RENDERER_ROUTES == (
        "pose_swap",
        "sprite_affine",
        "mesh_warp",
        "part_rig",
        "controlled_redraw",
    )
