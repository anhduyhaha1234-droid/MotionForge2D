"""S09-T02 tests — measured pose-state capability + backend anchor parity.

Binary acceptance coverage per TASK.md (outcomes 2 & 4):
- pose-state capability is MEASURED on a REAL NVENC re-encode: the adaptive
  adapter renders f2_mouth_swap through h264_nvenc and verifies every
  annotated swap on both input and output via the harness-recipe masked NCC
  classification; unmeasurable outcomes surface as evidence, never pass;
- backend anchor parity round-trip: the renderer's per-segment route +
  contact-anchor decision survives SegmentRenderRoute persistence byte-for-
  byte (route/anchors/provenance) against a real migrated temp DB;
- escalation evidence path: measured-error escalation goes through
  RendererRouter.maybe_escalate and lands a five-field RouteProvenance
  artifact; refusal writes an auditable refusal artifact instead.

Runs against real migrated temp DBs (never MAIN, never production).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from os.path import commonpath
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.structural_lock import StructuralLockRepository
from app.services.renderer_contract import (
    AffineKeyframe,
    PoseSwapEntry,
    RenderRequest,
    ReplacementAsset,
)
from app.services.renderer_router import build_adaptive_default_router
from app.services.renderer_routes import (
    OptimizedSpriteAffineAdapter,
    PoseSwapAdaptiveAdapter,
    load_pose_templates_rgba,
    measure_pose_state_capability,
)
from app.services.renderer_routes.composite import probe_source_timebase

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Runtime fixtures are REGENERATED deterministically into the task's own
#: output tree (byte-identical to the frozen fixture set on this machine's
#: pinned toolchain) so tests never depend on committed media.
RUNTIME_FIXTURES = (
    PROJECT_ROOT / "output/s09/20260823_sprint_full/t02/fixtures_runtime"
).resolve()


def _ensure_runtime_fixtures() -> Path:
    if not (RUNTIME_FIXTURES / "media" / "f2_mouth_swap.mp4").is_file():
        gen = (
            PROJECT_ROOT
            / "tests/fixtures/s09_renderer/generate_fixtures.py"
        ).resolve()
        completed = subprocess.run(  # noqa: S603 - fixed argv
            [sys.executable, str(gen), "--out", str(RUNTIME_FIXTURES)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            pytest.fail(
                "runtime fixture generation failed: "
                + (completed.stderr or completed.stdout)[-500:]
            )
    return RUNTIME_FIXTURES


@pytest.fixture(scope="module")
def fx_dir() -> Path:
    return _ensure_runtime_fixtures()


def _render_request(
    *,
    name: str,
    route: str,
    frames: int,
    media: Path,
    output_media: Path,
    fx: Path | None = None,
) -> RenderRequest:
    """Build a request satisfying the FULL S09-T02-C1 typed contract.

    pose_swap requests get the fixture's real head templates as pose-state
    assets plus the manifest swap schedule; sprite_affine requests get a
    head-sized replacement sprite anchored at the manifest pose region
    center with a real two-keyframe affine track.
    """
    kwargs: dict[str, object] = {}
    # Workspace root must contain BOTH input and output media (fail-closed
    # containment).  The fixtures live under output/.../t02/fixtures_runtime
    # while pytest tmp outputs sit elsewhere, so root at the common ancestor.
    if fx is not None:
        kwargs["workspace_root"] = str(
            Path(commonpath([media.resolve(), output_media.resolve()]))
        )
    else:
        kwargs["workspace_root"] = media.parent.parent
    if route == "pose_swap" and fx is not None:
        tpl = fx / "sprites" / "f2_mouth_swap"
        man = json.loads(
            (fx / "manifests" / "f2_mouth_swap.json").read_text(
                encoding="utf-8"
            )
        )
        open_asset = ReplacementAsset(
            path=tpl / "head_open_rep.png", kind="pose_state"
        )
        closed_asset = ReplacementAsset(
            path=tpl / "head_closed_rep.png", kind="pose_state"
        )
        schedule = tuple(
            PoseSwapEntry(
                frame=int(entry["swap_frame"]),
                state_id=str(entry["expected_state"]),
                asset=open_asset
                if entry["expected_state"] == "open"
                else closed_asset,
            )
            for entry in man["swaps"]
        )
        kwargs["pose_state_assets"] = {
            "open": open_asset,
            "closed": closed_asset,
        }
        kwargs["pose_schedule"] = schedule
    elif route == "sprite_affine" and fx is not None:
        tpl = fx / "sprites" / "f2_mouth_swap"
        man = json.loads(
            (fx / "manifests" / "f2_mouth_swap.json").read_text(
                encoding="utf-8"
            )
        )
        rx, ry, rw, rh = (
            float(v) for v in man["pose_region_bbox_xywh_norm"]
        )
        kwargs["replacement_asset"] = ReplacementAsset(
            path=tpl / "head_open_rep.png", kind="sprite"
        )
        kwargs["anchor_xy_norm"] = (rx + rw / 2.0, ry + rh / 2.0)
        kwargs["affine_keyframes"] = (
            AffineKeyframe(frame=0),
            AffineKeyframe(frame=max(0, frames - 1), scale=1.08),
        )
    return RenderRequest(
        request_id=name,
        workspace_id="ws-t02",
        project_id="p-t02",
        video_item_id="v-t02",
        occurrence_segment_id="seg-t02",
        route=route,
        start_frame=0,
        end_frame=frames - 1,
        input_media=media,
        output_media=output_media,
        source_timebase=probe_source_timebase(media),
        **kwargs,  # type: ignore[arg-type]
    )


# ── Measured pose-state capability over the REAL NVENC pipeline ──────────────


def _pose_inputs(fx: Path) -> dict[str, object]:
    man = json.loads(
        (fx / "manifests" / "f2_mouth_swap.json").read_text(encoding="utf-8")
    )
    tpl = fx / "sprites" / "f2_mouth_swap"
    return {
        "region": tuple(man["pose_region_bbox_xywh_norm"]),
        "templates": {
            "closed": tpl / "head_closed_rep.png",
            "open": tpl / "head_open_rep.png",
        },
        "plan": man["swaps"],
        "frames": int(man["frame_count"]),
    }


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="NVENC pipeline verified on this Windows host",
)
def test_adaptive_pose_swap_measures_swaps_on_real_nvenc_encode(
    fx_dir: Path, tmp_path: Path
) -> None:
    pose = _pose_inputs(fx_dir)
    adapter = PoseSwapAdaptiveAdapter()
    adapter.set_pose_measurement_inputs(
        region_xywh_norm=pose["region"],  # type: ignore[arg-type]
        templates=pose["templates"],  # type: ignore[arg-type]
        swap_plan=pose["plan"],  # type: ignore[assignment]
    )
    req = _render_request(
        name="t02-test-f2-nvenc",
        route="pose_swap",
        frames=int(pose["frames"]),  # type: ignore[arg-type]
        media=fx_dir / "media" / "f2_mouth_swap.mp4",
        output_media=tmp_path / "f2_out.mp4",
        fx=fx_dir,
    )
    result = adapter.render(req)
    assert result.ok, result.error_detail
    assert result.frames_rendered == int(pose["frames"])  # type: ignore[arg-type]

    evidence = adapter.last_pose_evidence
    assert evidence is not None
    assert evidence["measured"] is True
    assert evidence["capability"] is True, evidence["reasons"]
    assert evidence["value"] == "verified_all_swaps"
    # Every planned swap verified on BOTH input and rendered output.
    plan = pose["plan"]
    assert len(evidence["checks"]) == len(plan)  # type: ignore[arg-type]
    for check in evidence["checks"]:
        assert check["pass"] is True
        assert check["input_winner"] == check["expected_state"]
        assert check["output_winner"] == check["expected_state"]

    # The measured capability descriptor carries the verdict.
    cap = adapter.capability()
    assert cap.details.get("nvenc_available") is True
    assert cap.details.get("pose_state_capability") == "verified_all_swaps"
    assert cap.details.get("pose_state_capability_measured") is True


def test_pose_measurement_surfaces_verification_failure_not_silent_pass(
    fx_dir: Path, tmp_path: Path
) -> None:
    """A WRONG expected state must produce capability=False with evidence —
    never a silent pass (TASK.md: không silent/unmeasured escalation)."""
    pose = _pose_inputs(fx_dir)
    wrong_plan = [
        {**entry, "expected_state": "closed" if entry["expected_state"] == "open" else "open"}
        for entry in pose["plan"]  # type: ignore[union-attr]
    ]
    src = fx_dir / "media" / "f2_mouth_swap.mp4"
    verdict = measure_pose_state_capability(
        input_media=src,
        output_media=src,  # compare input against itself: swaps DO exist there
        region_xywh_norm=pose["region"],  # type: ignore[arg-type]
        templates_bgra=load_pose_templates_rgba(pose["templates"]),  # type: ignore[arg-type]
        swap_plan=wrong_plan,
    )
    assert verdict["measured"] is True
    assert verdict["capability"] is False
    assert verdict["value"] == "verification_failed"
    assert verdict["reasons"], "failure must carry reasons"


def test_pose_measurement_unreadable_media_is_reported_not_passed(
    tmp_path: Path, fx_dir: Path
) -> None:
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a video")
    pose = _pose_inputs(fx_dir)
    verdict = measure_pose_state_capability(
        input_media=fx_dir / "media" / "f2_mouth_swap.mp4",
        output_media=garbage,
        region_xywh_norm=pose["region"],  # type: ignore[arg-type]
        templates_bgra=load_pose_templates_rgba(pose["templates"]),  # type: ignore[arg-type]
        swap_plan=pose["plan"],  # type: ignore[arg-type]
    )
    assert verdict["measured"] is False
    assert verdict["capability"] is False
    assert "undecodable" in verdict["reasons"][0]


# ── Optimized sprite-affine identity skip ────────────────────────────────────


def test_optimized_affine_skips_filter_graph_only_for_identity(
    fx_dir: Path, tmp_path: Path
) -> None:
    media = fx_dir / "media" / "f1_hard_cut.mp4"
    opt = OptimizedSpriteAffineAdapter()
    req_identity = _render_request(
        name="t02-affine-identity",
        route="sprite_affine",
        frames=30,
        media=media,
        output_media=tmp_path / "affine_identity.mp4",
        fx=fx_dir,
    )
    # C2 (F5): identity is a TYPED declaration — the request_id carries no
    # business meaning.  The identity variant carries an EMPTY keyframe
    # track + identity_transform=True (contract-validated pairing).
    req_identity = replace(
        req_identity, affine_keyframes=(), identity_transform=True
    )
    res1 = opt.render(req_identity)
    assert res1.ok, res1.error_detail
    assert opt.last_identity_filter_skip is True

    req_full = _render_request(
        name="t02-affine-full",
        route="sprite_affine",
        frames=30,
        media=media,
        output_media=tmp_path / "affine_full.mp4",
        fx=fx_dir,
    )
    res2 = opt.render(req_full)
    assert res2.ok, res2.error_detail
    assert opt.last_identity_filter_skip is False
    cap = opt._last_capability
    assert cap is not None
    # F1 correction: "full" means the REQUEST's keyframe track is composited;
    # the descriptor must disclose a real composite (keyframes sampled), and
    # typed identity requests run with NO transform — both are real composites.
    assert cap.details.get("composite") == (
        "replacement_layer_anchor_keyframes_cpu_deterministic"
    )
    assert int(cap.details.get("keyframes_sampled", 0)) == 30


def test_optimized_affine_output_matches_i02_dimensions(tmp_path: Path) -> None:
    """Identity-skip must not change geometry: same resolution as source."""
    import cv2

    fx = _ensure_runtime_fixtures()
    src = fx / "media" / "f1_hard_cut.mp4"
    opt = OptimizedSpriteAffineAdapter()
    res = opt.render(
        _render_request(
            name="t02-dim",
            route="sprite_affine",
            frames=10,
            media=src,
            output_media=tmp_path / "dim.mp4",
            fx=_ensure_runtime_fixtures(),
        )
    )
    assert res.ok, res.error_detail
    src_cap = cv2.VideoCapture(str(src))
    out_cap = cv2.VideoCapture(str(tmp_path / "dim.mp4"))
    try:
        assert (
            int(src_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            == int(out_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        )
        assert (
            int(src_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            == int(out_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        )
    finally:
        src_cap.release()
        out_cap.release()


# ── Backend anchor parity round-trip (SegmentRenderRoute ↔ renderer) ─────────


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


WS = "ws-t02-parity"


def _seed_graph(db: Path):  # type: ignore[no-untyped-def]
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as s:
        s.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        s.execute(
            text(
                "INSERT INTO project(id,workspace_id,name)"
                " VALUES ('p-t02',:w,'Proj')"
            ),
            {"w": WS},
        )
        s.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position)"
                " VALUES ('v-t02','p-t02','Vid',0)"
            ),
        )
        s.execute(
            text(
                "INSERT INTO scene (id, video_item_id, legacy_scene_id, "
                "position, start_frame, end_frame, start_time_ms, "
                "end_time_ms, status) VALUES ('sc-t02','v-t02',NULL,0,"
                "0,59,0,2000,'draft')"
            ),
        )
        s.execute(
            text(
                "INSERT INTO object_role (id, workspace_id, project_id, "
                "video_item_id, source_generation, name, kind, status, "
                "revision) VALUES ('role-t02',:w,'p-t02','v-t02',"
                "'2','Head role','character','suggested',1)"
            ),
            {"w": WS},
        )
        s.execute(
            text(
                "INSERT INTO occurrence_segment "
                "(id, logical_id, lineage_version, superseded_by_id, "
                "workspace_id, project_id, video_item_id, role_id, scene_id, "
                "name, kind, start_frame, end_frame, start_time_ms, "
                "end_time_ms, source_generation, source_job_id, prompt_json, "
                "segmentation_json, mask_artifact_id, algorithm, "
                "algorithm_version, confidence, confidence_source, "
                "reasons_json, provenance_json, visibility, z_order, "
                "idempotency_key, revision, created_at, updated_at) "
                "VALUES ('seg-t02','lg1',1,NULL,:w,'p-t02','v-t02',"
                "'role-t02','sc-t02','Head swap segment',"
                "'character',0,59,0,2000,'gen-t02',NULL,NULL,NULL,"
                "NULL,'adaptive-pose-swap',"
                "'1.0.0',1.0,'derived','[]',NULL,'visible',1,NULL,1,"
                "'2026-08-24T00:00:00','2026-08-24T00:00:00')"
            ),
            {"w": WS},
        )
        s.commit()
    return factory


def test_backend_anchor_parity_roundtrip(tmp_path: Path) -> None:
    """The renderer decision (route/anchors/provenance) persists and reads
    back EXACTLY what the adaptive selection produced — no drift."""
    factory = _seed_graph(tmp_path / "parity.db")
    with factory() as s:
        repo = StructuralLockRepository(s)
        manifest, _created = repo.create_manifest(
            WS, "p-t02", "v-t02", "gen-t02", _minimal_manifest_payload()
        )

        # The RENDERER side of the contract: what the adaptive route decided.
        from app.services.renderer_routes import load_benchmark_results, select_route

        doc = load_benchmark_results(_frozen_results_path())
        decision = select_route(
            doc, risk_class="mouth_expression_swap", has_annotated_swaps=True
        )
        provenance = {
            "kind": "s09_t02_adaptive_selection",
            "route": decision.route,
            "risk_class": decision.risk_class,
            "evidence_artifact": decision.evidence_path,
            "frozen_content_sha256": decision.frozen_content_sha256,
            "thresholds_policy": decision.thresholds_policy,
            "notes": decision.notes,
        }
        anchor_x, anchor_y = 0.5, 0.25  # normalized contact anchor

        record, created = repo.record_render_route(
            WS,
            "p-t02",
            "v-t02",
            "seg-t02",
            decision.route,
            anchor_x,
            anchor_y,
            start_frame=0,
            end_frame=59,
            provenance=provenance,
            reasons=list(decision.notes),
            algorithm="adaptive-pose-swap",
            algorithm_version="1.0.0",
            confidence=1.0,
            confidence_source="derived",
            structural_lock_manifest_id=manifest.id,
        )
        assert created is True

        rows = repo.list_routes_for_video(WS, "p-t02", "v-t02")
        assert len(rows) == 1
        row = rows[0]
        # PARITY assertions: persisted row == renderer decision, exactly.
        assert row.route == decision.route
        assert row.anchor_x == anchor_x and row.anchor_y == anchor_y
        assert row.start_frame == 0 and row.end_frame == 59
        assert row.provenance == provenance
        assert row.reasons == list(decision.notes)
        assert row.structural_lock_manifest_id == manifest.id


def test_route_evidence_api_read_model_matches_persisted_row(
    tmp_path: Path,
) -> None:
    """The T01 read model (list_renderer_route_evidence) exposes the SAME
    route/anchor/provenance the renderer wrote — full parity at API shape.

    Seed uses the REPOSITORY write path (create_config) so compatibility
    policy (published pack + full CORE_POSE_SLOTS assets) is satisfied the
    same way production writes configs — not by hand-crafting rows.
    """
    from app.persistence.reskin_config import ReskinConfigRepository

    factory = _seed_graph(tmp_path / "api.db")
    with factory() as s:
        repo = StructuralLockRepository(s)
        manifest, _ = repo.create_manifest(
            WS, "p-t02", "v-t02", "gen-t02", _minimal_manifest_payload()
        )
        prov = {"kind": "t02", "route": "pose_swap", "risk_class": "hard_cut"}
        route_row, _ = repo.record_render_route(
            WS, "p-t02", "v-t02", "seg-t02", "pose_swap", 0.75, 0.5,
            start_frame=0, end_frame=29, provenance=prov, reasons=["r1"],
            structural_lock_manifest_id=manifest.id,
        )

        # FK chain for create_config: character → published pack version
        # (with ALL core pose slots) → config via the repository API.
        s.execute(
            text(
                "INSERT INTO character (id, workspace_id, name, code, "
                "character_type, status) VALUES ('char-x',:w,'Char X',"
                "'char-x','character','ready')"
            ),
            {"w": WS},
        )
        s.execute(
            text(
                "INSERT INTO character_pack_version (id, character_id, "
                "workspace_id, version, status) VALUES ('pv-x','char-x',:w,"
                "1,'published')"
            ),
            {"w": WS},
        )
        # One artifact row per CORE_POSE_SLOTS asset slot.
        slots = (
            "front",
            "three_quarter",
            "side",
            "back",
            "sitting",
            "walking",
        )
        for i, slot in enumerate(slots):
            s.execute(
                text(
                    "INSERT INTO artifact (id, workspace_id, kind, "
                    "relative_path, state) VALUES (:a,:w,'image',"
                    ":p,'ready')"
                ),
                {"a": f"art-{i}", "w": WS, "p": f"poses/{slot}.png"},
            )
            s.execute(
                text(
                    "INSERT INTO character_asset (id, pack_version_id, "
                    "workspace_id, pose_slot, artifact_id) VALUES "
                    "(:ca,'pv-x',:w,:slot,:a)"
                ),
                {"ca": f"cass-{i}", "w": WS, "slot": slot, "a": f"art-{i}"},
            )
        # A completed DISCOVER_OBJECTS job at generation '1' makes the
        # backend-authoritative current generation resolve to '2'
        # (_resolve_generation_from_jobs: no source artifact → max_gen+1).
        # Seed role.source_generation='2' so evaluate_compatibility matches.
        s.execute(
            text(
                "INSERT INTO job (id, workspace_id, job_type, owner_type, "
                "owner_id, state, input_generation) VALUES ('job-t02',:w,"
                "'DISCOVER_OBJECTS','video_item','v-t02','completed','1')"
            ),
            {"w": WS},
        )
        s.commit()

        api_repo = ReskinConfigRepository(s)
        cfg_repo_record, created = api_repo.create_config(
            WS,
            "p-t02",
            "role-t02",
            "char-x",
            "pv-x",
            params={
                "anchor": {"x": 0.5, "y": 0.25},
                "scale": 1.0,
                "fit_mode": "cover",
                "clip_mode": "asset_alpha",
                "offset": {"x": 0.0, "y": 0.0},
                "rotation_offset_deg": 0.0,
                "opacity": 1.0,
            },
            structural_lock_manifest_id=manifest.id,
        )
        assert created is True

        evidence = api_repo.list_renderer_route_evidence(WS, cfg_repo_record.id)
        assert len(evidence) == 1
        item = evidence[0]
        assert item["occurrence_segment_id"] == "seg-t02"
        assert item["route"] == "pose_swap"
        assert item["anchor"] == {"x": 0.75, "y": 0.5}
        assert item["provenance"] == prov
        assert item["structural_lock_manifest_id"] == manifest.id


# ── Escalation provenance (no silent escalation) ─────────────────────────────


def test_escalation_writes_five_field_provenance_artifact(
    tmp_path: Path,
) -> None:
    router = build_adaptive_default_router(evidence_dir=tmp_path)
    artifact = tmp_path / "escalation" / "seg-e1.json"
    escalated, record = router.maybe_escalate(
        "seg-e1",
        "pose_swap",
        "contact_p95_pct",
        1.5,
        1.0,
        "sprite_affine",  # FORWARD step; backend registered on this router
        artifact_path=str(artifact),
        candidate_metric_projection=0.4,
        extra={"benchmark_results_sha256": "f" * 64},
    )
    assert escalated is True
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    for field in (
        "route_from",
        "route_to",
        "metric_name",
        "metric_value",
        "threshold",
    ):
        assert field in payload, f"missing provenance field {field}"
    assert payload["segment_id"] == "seg-e1"
    assert record["evidence_bytes"] > 0


def test_escalation_without_projection_refused_and_auditable(
    tmp_path: Path,
) -> None:
    router = build_adaptive_default_router(evidence_dir=tmp_path)
    artifact = tmp_path / "refusal" / "seg-r1.json"
    escalated, reason = router.maybe_escalate(
        "seg-r1",
        "pose_swap",
        "contact_p95_pct",
        1.5,
        1.0,
        "mesh_warp",
        artifact_path=str(artifact),
        candidate_metric_projection=None,
    )
    assert escalated is False
    assert "candidate_metric_projection" in str(reason)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["kind"] == "renderer_route_escalation_refused"


def test_backward_escalation_never_allowed(tmp_path: Path) -> None:
    router = build_adaptive_default_router(evidence_dir=tmp_path)
    artifact = tmp_path / "back" / "seg-b1.json"
    escalated, _reason = router.maybe_escalate(
        "seg-b1",
        "sprite_affine",
        "contact_p95_pct",
        9.9,
        1.0,
        "pose_swap",  # BACKWARD step in ROUTE_PRIORITY
        artifact_path=str(artifact),
        candidate_metric_projection=0.1,
    )
    assert escalated is False
    assert json.loads(artifact.read_text(encoding="utf-8"))[
        "kind"
    ] == "renderer_route_escalation_refused"


# ── helpers ──────────────────────────────────────────────────────────────────


def _frozen_results_path() -> Path:
    # Prompt C2 mục 3.5: the old schema-v1 artifact directory is FORBIDDEN
    # as active test input — C2 measured run_A only.
    p = (
        PROJECT_ROOT
        / "output/s09/20260823_sprint_full/t00-i03-c2/run_A"
        / "benchmark_results_seed20260823.json"
    ).resolve()
    if not p.is_file():
        pytest.fail(f"frozen benchmark results missing: {p}")
    return p


def _minimal_manifest_payload() -> dict[str, object]:
    return {
        "frame_count": 60,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-t02"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }
