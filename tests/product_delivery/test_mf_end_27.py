"""MF-END-27 — Batch hai video và tài sản tái dùng: acceptance + negatives.

Row map (nhị phân):

* 27.0 micro/surface: module batch tồn tại và KHÔNG có bảng mới (không
  ``__tablename__``); batch tựa vào bảng job + run hiện có (S12ExportRun,
  ProjectCastMapping); ``batch_key`` tất định; 4 route batch có mặt trong
  OpenAPI THẬT của app; frontend feature ``series-batch`` có đủ file + chuỗi
  route thật + helper text tiếng Việt dưới nút (≥11px, ``text-gray-400``,
  không ``gray-500``) và không có tiến trình giả (``Math.random``).
* 27.1 (HTTP thật qua TestClient): project + hai video cùng một pack cast →
  POST series-batches 202: prepare ĐỘC LẬP cho cả hai video, video thứ hai
  ``deferred_lease`` với ZERO run row (lease nặng = 1); GET đọc lại không
  submit; thiếu cast → 422 typed; lệch pack → 409 typed; mọi lần từ chối
  không ghi thêm run/job nào.
* 27.3 (ACCEPTANCE, thế giới S12-T03C thật dùng lại read-only): batch queue
  hai video của cùng series → cả hai export chạy qua authority thật →
  HAI MP4 khác nhau (sha khác nhau) cùng ``pack_hash`` đã pin; restart
  (service mới + re-entry idempotent) không mất queue, không đổi cast,
  không duplicate job.
* 27.4: lỗi video 1 (nguồn hỏng) KHÔNG xoá/không đụng video 2 — video 2 vẫn
  hoàn tất và file của nó còn nguyên bytes; huỷ đúng một video không đụng
  video kia; và ``metrics`` trả nguyên văn ``"unmeasured"`` khi CHƯA đo
  (U26 — không bịa số, không hứa 30 phút từ mẫu dễ).

Disclosure: đây là bằng chứng engineering/CI.  Không GPU, không ComfyUI
trong file này: tầng engine/render phía trên (MF-END-19/20) nằm ngoài batch;
batch chỉ xếp hàng authority export thật (ffmpeg thật trong harness MF-END-26,
dùng lại read-only).  Render GPU là hạng mục real-run R1, ghi NOT_RUN ở đây.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from app.services import series_batch as sb

WT = Path(__file__).resolve().parents[2]

FEATURE = WT / "frontend" / "src" / "features" / "series-batch"
API_FILE = FEATURE / "seriesBatchApi.ts"
LOGIC_FILE = FEATURE / "seriesBatchLogic.ts"
PANEL_FILE = FEATURE / "SeriesBatchPanel.tsx"

EXPECTED_ROUTE_STRINGS = (
    "/api/v2/projects/${projectId}/series-batches",
    "/api/v2/projects/${projectId}/series-batches/advance",
    "/api/v2/projects/${projectId}/series-batches/cancel",
)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: REAL MF-END-26 harness (read-only reuse, same delivery): exposes the
#: S12-T03C retry world, the real export route and the real handler.
_T26 = _load_module(
    "mf27_t26_harness", WT / "tests" / "product_delivery" / "test_mf_end_26.py"
)
_RETRY = _T26._RETRY

WS = _RETRY.WS
PROJECT = f"p-{WS}"
V1 = f"v-{WS}"
V2 = f"v2-{WS}"


# ── 27.0 — micro/surface ─────────────────────────────────────────────────────


def test_mf27_0_service_surface_no_new_table_and_deterministic_key() -> None:
    """Batch reuses the job/run tables and never adds a queue of its own."""
    source = (WT / "app" / "services" / "series_batch.py").read_text(encoding="utf-8")
    assert "__tablename__" not in source, "series_batch must not define a table"
    assert "from app.persistence.models import" in source
    for reused in ("Job", "S12ExportRun", "ProjectCastMapping", "ObjectRole", "VideoItem"):
        assert reused in source, f"batch must read the existing {reused} rows"
    # deterministic identity: same input -> same key, sorted input order
    k1 = sb.batch_key("p1", [V2, V1])
    k2 = sb.batch_key("p1", [V1, V2])
    assert k1 == k2 and k1.startswith("series-batch:")
    assert sb.batch_key("p1", [V1, V2], generation="2") != k1


def test_mf27_0_metrics_are_unmeasured_without_a_real_measurement() -> None:
    """U26: no fabricated throughput/30-minute numbers, ever."""
    metrics = sb.SeriesBatchService.metrics(SimpleNamespace(), measured=None)
    assert metrics["measured"] is False
    for field in (
        "window_seconds",
        "accepted_seconds",
        "throughput_accepted_per_second",
        "peak_ram_mb",
        "peak_vram_mb",
        "forecast_30min",
    ):
        assert metrics[field] == sb.UNMEASURED == "unmeasured", field
    numeric = [
        value
        for key, value in metrics.items()
        if key != "measured" and isinstance(value, (int, float))
    ]
    assert numeric == [], f"unmeasured metrics must not carry numbers: {numeric}"
    # control: a REAL measurement is passed through verbatim
    real = sb.SeriesBatchService.metrics(
        SimpleNamespace(),
        measured={
            "window_seconds": 12.5,
            "accepted_seconds": 4.0,
            "throughput_accepted_per_second": 0.32,
            "peak_ram_mb": 2048,
            "peak_vram_mb": 11000,
            "forecast_30min": 1800,
        },
    )
    assert real["measured"] is True
    assert real["peak_ram_mb"] == 2048
    assert real["forecast_30min"] == 1800


def test_mf27_0_routes_and_frontend_surface_are_real() -> None:
    """The 4 batch routes exist in the REAL OpenAPI; the UI calls only them."""
    from app.api.app import app

    paths = app.openapi()["paths"]
    base = "/api/v2/projects/{project_id}/series-batches"
    assert "post" in paths[base] and "get" in paths[base]
    assert "post" in paths[f"{base}/advance"]
    assert "post" in paths[f"{base}/cancel"]

    for path in (API_FILE, LOGIC_FILE, PANEL_FILE):
        assert path.is_file(), f"missing frontend feature file {path}"
    api_src = API_FILE.read_text(encoding="utf-8")
    for route in EXPECTED_ROUTE_STRINGS:
        assert route in api_src, f"route string missing from the UI client: {route}"
    panel_src = PANEL_FILE.read_text(encoding="utf-8")
    logic_src = LOGIC_FILE.read_text(encoding="utf-8")
    combined = api_src + panel_src + logic_src
    assert "Math.random" not in combined, "no synthetic progress in the batch UI"
    assert "unmeasured" in logic_src, "metrics honesty must reach the UI"
    # helper text under EVERY button (Vietnamese, >=11px, gray-400 or lighter):
    # 3 top buttons pass helper= into <Button>, the row button renders <Helper>
    assert panel_src.count("helper=") >= 3
    assert panel_src.count("<Helper>") >= 2
    for label in ("Xếp hàng batch", "Mở video kế tiếp", "Tải lại trạng thái", "Huỷ video này"):
        assert label in panel_src, f"missing button label: {label}"
    assert "text-[11px]" in panel_src
    assert "text-gray-400" in panel_src
    assert "text-gray-500" not in panel_src


# ── helpers: HTTP world and the REAL two-video retry world ───────────────────


def _counts(factory: Any) -> dict[str, int]:
    with factory() as session:
        runs = session.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar()
        jobs = session.execute(text("SELECT COUNT(*) FROM job")).scalar()
    return {"runs": int(runs or 0), "jobs": int(jobs or 0)}


def _seed_http_world(client: Any, deps: Any, *, pack_hash: str = "a" * 8) -> dict[str, str]:
    """Real HTTP project + two video items + one shared cast pack."""
    project_id = client.post("/api/v2/projects", json={"name": "Series Q"}).json()[
        "project_id"
    ]
    factory = deps._job_service.session_factory
    with factory() as session:
        session.execute(
            text(
                "INSERT INTO character(id,workspace_id,name,code) "
                "VALUES ('ch-x','default','Hero','hero-x')"
            )
        )
        session.execute(
            text(
                "INSERT INTO character_pack_version"
                "(id,character_id,workspace_id,version,status) "
                "VALUES (:pv,'ch-x','default',1,'published')"
            ),
            {"pv": f"pv-{pack_hash}"},
        )
        for index, vid in enumerate((f"vid-a-{project_id[:8]}", f"vid-b-{project_id[:8]}")):
            session.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position) "
                    "VALUES (:v,:p,:t,:pos)"
                ),
                {"v": vid, "p": project_id, "t": f"Tap {index}", "pos": index},
            )
            role_id = f"role-{index}"
            session.execute(
                text(
                    "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                    "source_generation,name,kind,status) "
                    "VALUES (:r,'default',:p,:v,'g','Hero','character','confirmed')"
                ),
                {"r": role_id, "p": project_id, "v": vid},
            )
            session.execute(
                text(
                    "INSERT INTO project_cast_mapping"
                    "(id,workspace_id,project_id,object_role_id,character_id,"
                    "pack_version_id,idempotency_key,revision) "
                    "VALUES (:m,'default',:p,:r,'ch-x',:pv,NULL,1)"
                ),
                {"m": f"map-{index}", "p": project_id, "r": role_id, "pv": f"pv-{pack_hash}"},
            )
        session.commit()
    return {
        "project_id": project_id,
        "v1": f"vid-a-{project_id[:8]}",
        "v2": f"vid-b-{project_id[:8]}",
        "roles": {"v1": "role-0", "v2": "role-1"},
    }


def _two_video_retry_world(tmp_path: Path) -> dict[str, Any]:
    """The REAL S12-T03C world, extended with a SECOND video of the series."""
    fixture = getattr(_RETRY.env, "__wrapped__", _RETRY.env)
    root = tmp_path / "retry"
    root.mkdir(parents=True, exist_ok=True)
    factory, svc, manifest1, auth1, dirs, managed = next(fixture(root))
    with factory() as session:
        session.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) "
                "VALUES (:v,:p,'Tap 2',1)"
            ),
            {"v": V2, "p": PROJECT},
        )
        session.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) "
                "VALUES ('rl-b',:w,:p,:v,'g','C','character','confirmed')"
            ),
            {"w": WS, "p": PROJECT, "v": V2},
        )
        session.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                "cast_mapping_id,character_id,pack_version_id,params_json,"
                "idempotency_key,revision) "
                "VALUES ('rc-b',:w,:p,'rl-b',NULL,'ch-a','pv-a','{}',NULL,1)"
            ),
            {"w": WS, "p": PROJECT},
        )
        session.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                "loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,"
                "note,idempotency_key,revision) "
                "VALUES ('ac-b',:w,:p,'rc-b',1,'[]','[]','tb','{}',:h,NULL,NULL,1)"
            ),
            {"w": WS, "p": PROJECT, "h": _RETRY.CHK_HASH},
        )
        session.commit()
        lock = _RETRY.StructuralLockRepository(session)
        manifest2, _ = lock.create_manifest(
            WS, PROJECT, V2, "gen1", _RETRY._manifest_doc()
        )
        session.commit()
        manifest2_id = manifest2.id
    with factory() as session:
        auth2 = _RETRY._seed_s10_authority(
            session,
            ws=WS,
            pid=PROJECT,
            vid=V2,
            ckpt={
                "checkpoint_id": "ac-b",
                "checkpoint_hash": _RETRY.CHK_HASH,
                "checkpoint_revision": 1,
            },
            frame_count=_RETRY.FRAMES,
            fps_num=_RETRY.FPS,
            fps_den=1,
        )
        session.commit()
    # the shared series cast: both videos pinned to ONE pack (U03)
    with factory() as session:
        session.execute(
            text(
                "INSERT INTO project_cast_mapping(id,workspace_id,project_id,"
                "object_role_id,character_id,pack_version_id,idempotency_key,revision) "
                "VALUES ('m1',:w,:p,'rl-a','ch-a','pv-a',NULL,1),"
                "('m2',:w,:p,'rl-b','ch-a','pv-a',NULL,1)"
            ),
            {"w": WS, "p": PROJECT},
        )
        session.commit()
    # real source media for BOTH videos (the export runner reads the source);
    # video 2 gets DIFFERENT pixels (hue shift, same duration/rate/audio) so
    # "hai MP4 khác nhau" is a real difference, not a fixture coincidence.
    sources = {
        V1: _T26._make_source(managed / "apply" / "mf27-v1.mp4", audio=True),
        V2: _T26._make_source(managed / "apply" / "mf27-v2.mp4", audio=True),
    }
    shifted = managed / "apply" / "mf27-v2-shift.mp4"
    subprocess.run(
        [
            _T26._ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(sources[V2]),
            "-vf",
            "hue=h=120",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(shifted),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    sources[V2] = shifted
    assert sources[V1].read_bytes() != sources[V2].read_bytes(), (
        "the two video sources must really differ before the acceptance run"
    )
    with factory() as session:
        for vid, artifact_id in ((V1, auth1["artifact_id"]), (V2, auth2["artifact_id"])):
            session.execute(
                text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"),
                {
                    "rel": str(sources[vid].relative_to(managed)).replace("\\", "/"),
                    "aid": artifact_id,
                },
            )
        session.commit()
    return {
        "factory": factory,
        "svc": svc,
        "managed": managed,
        "manifest1": manifest1,
        "manifest2": manifest2_id,
        "auth1": auth1,
        "auth2": auth2,
        "sources": sources,
    }


def _patch_world(mp: pytest.MonkeyPatch, svc: Any, managed: Path) -> None:
    mp.setattr(_RETRY.route, "get_job_service", lambda: svc)
    mp.setattr(_RETRY.route, "get_managed_root", lambda: managed)
    mp.setattr("app.api.deps.get_job_service", lambda: svc)
    mp.setattr("app.api.deps.get_managed_root", lambda: managed)
    mp.setattr(
        "app.persistence.readiness.compute_project_readiness",
        lambda session, **kw: SimpleNamespace(
            status="ready",
            videos=[
                SimpleNamespace(video_item_id=V1),
                SimpleNamespace(video_item_id=V2),
            ],
        ),
    )
    mp.setattr(
        "app.services.s12_export.publication._check_run_readiness",
        lambda session, **kw: "ready",
    )


def _export_payloads(world: dict[str, Any]) -> dict[str, dict[str, Any]]:
    factory = world["factory"]
    over2 = {
        "project_id": PROJECT,
        "video_item_id": V2,
        "checkpoint_id": "ac-b",
        "checkpoint_hash": _RETRY.CHK_HASH,
        "checkpoint_revision": 1,
    }
    return {
        V1: _RETRY._authority_body(factory, world["auth1"], world["manifest1"]),
        V2: _RETRY._authority_body(
            factory, world["auth2"], world["manifest2"], **over2
        ),
    }


def _run_export(factory: Any, out: dict[str, Any]) -> dict[str, Any]:
    """Execute the REAL export handler for one submitted run (worker-sim)."""
    from app.persistence.models import Job as JobRow

    with factory() as session:
        row = session.get(JobRow, out["job_id"])
        manifest = json.loads(row.input_manifest_json)
    ctx = SimpleNamespace(
        worker_id="worker-mf27",
        session_factory=factory,
        input_manifest=manifest,
    )
    return _RETRY._s12_export_handler(ctx)


def _batch_service(world: dict[str, Any]) -> Any:
    return sb.SeriesBatchService(
        world["factory"], job_service=world["svc"], max_heavy_in_flight=1
    )


def _create(service: Any, world: dict[str, Any], payloads: dict[str, Any]) -> dict[str, Any]:
    from app.api.routes import durable_projects as route

    return route.create_series_batch(
        project_id=PROJECT,
        body=route.SeriesBatchCreateRequest(
            video_item_ids=[V1, V2], exports=payloads
        ),
        workspace_id=WS,
    )


def _advance(service: Any, world: dict[str, Any], payloads: dict[str, Any]) -> dict[str, Any]:
    from app.api.routes import durable_projects as route

    return route.advance_series_batch(
        project_id=PROJECT,
        body=route.SeriesBatchCreateRequest(
            video_item_ids=[V1, V2], exports=payloads
        ),
        workspace_id=WS,
    )


# ── 27.1 — HTTP: prepare độc lập, lease=1, cast fail-closed ─────────────────


def test_mf27_1_http_queue_lease_and_cast_fail_closed(client: Any) -> None:
    from app.api import deps

    world = _seed_http_world(client, deps)
    video_ids = [world["v1"], world["v2"]]
    before = _counts(deps._job_service.session_factory)
    body = {"video_item_ids": video_ids, "exports": {}}
    created = client.post(
        f"/api/v2/projects/{world['project_id']}/series-batches", json=body
    )
    assert created.status_code == 202, created.text
    view = created.json()
    assert view["schema"] == sb.SCHEMA
    assert view["cast"]["ok"] is True and view["pack_hash"]
    assert view["prepare"]["prepared_count"] == 2
    assert [row["state"] for row in view["videos"]] == ["pending", "pending"]
    assert view["lease"] == {
        "max_heavy_in_flight": 1,
        "active_heavy": 0,
        "serialized": True,
    }
    assert view["metrics"]["measured"] is False
    assert view["metrics"]["forecast_30min"] == "unmeasured"
    after = _counts(deps._job_service.session_factory)
    assert after == before, "a batch with no export payload writes no run/job"
    # read-only GET: same identity, still zero writes
    got = client.get(
        f"/api/v2/projects/{world['project_id']}/series-batches",
        params={"video_item_ids": ",".join(video_ids)},
    )
    assert got.status_code == 200, got.text
    assert got.json()["batch_key"] == view["batch_key"]
    assert _counts(deps._job_service.session_factory) == before

    # NEGATIVE: one video loses its cast rows -> typed refusal, zero writes
    factory = deps._job_service.session_factory
    with factory() as session:
        session.execute(
            text("DELETE FROM project_cast_mapping WHERE object_role_id=:r"),
            {"r": world["roles"]["v2"]},
        )
        session.commit()
    missing = client.post(
        f"/api/v2/projects/{world['project_id']}/series-batches", json=body
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"]["code"] == "series_batch_cast_missing"
    assert _counts(factory) == before
    # NEGATIVE: the two videos pin DIFFERENT packs -> 409 typed, zero writes
    with factory() as session:
        session.execute(
            text(
                "INSERT INTO character_pack_version"
                "(id,character_id,workspace_id,version,status) "
                "VALUES ('pv-other','ch-x','default',2,'published')"
            )
        )
        session.execute(
            text(
                "INSERT INTO project_cast_mapping(id,workspace_id,project_id,"
                "object_role_id,character_id,pack_version_id,idempotency_key,revision) "
                "VALUES ('map-back',:w,:p,:r,'ch-x','pv-other',NULL,1)"
            ),
            {
                "w": "default",
                "p": world["project_id"],
                "r": world["roles"]["v2"],
            },
        )
        session.commit()
    mismatched = client.post(
        f"/api/v2/projects/{world['project_id']}/series-batches", json=body
    )
    assert mismatched.status_code == 409, mismatched.text
    assert mismatched.json()["detail"]["code"] == "series_batch_cast_mismatch"
    assert _counts(factory) == before


def test_mf27_1_http_cancel_without_job_is_honest(client: Any) -> None:
    from app.api import deps

    world = _seed_http_world(client, deps)
    out = client.post(
        f"/api/v2/projects/{world['project_id']}/series-batches/cancel",
        json={
            "video_item_ids": [world["v1"], world["v2"]],
            "video_item_id": world["v1"],
        },
    )
    assert out.status_code == 200, out.text
    assert out.json()["cancelled"] is False
    assert "no durable job" in out.json()["detail"]


# ── 27.3 — ACCEPTANCE: hai MP4 khác nhau cùng pack + restart an toàn ────────


def test_mf27_3_two_videos_two_different_mp4s_one_pack_restart_safe(
    tmp_path: Path,
) -> None:
    _T26._ffmpeg()
    world = _two_video_retry_world(tmp_path)
    mp = pytest.MonkeyPatch()
    _patch_world(mp, world["svc"], world["managed"])
    try:
        payloads = _export_payloads(world)
        service = _batch_service(world)
        counts0 = _counts(world["factory"])

        view = _create(service, world, payloads)
        states = {row["video_item_id"]: row["state"] for row in view["videos"]}
        assert states[V1] == "running", states  # video 1 admitted first
        assert states[V2] == "deferred_lease", states  # lease = 1, no run yet
        assert view["lease"]["serialized"] is True
        assert view["lease"]["active_heavy"] == 1
        assert view["metrics"]["measured"] is False
        assert view["metrics"]["forecast_30min"] == "unmeasured"
        counts1 = _counts(world["factory"])
        assert counts1 == {"runs": counts0["runs"] + 1, "jobs": counts0["jobs"] + 1}
        v2_rows_before = _runs_for(world["factory"], V2)
        assert v2_rows_before == [], "deferred video must have NO run row yet"

        # video 1: the REAL export path produces MP4 #1
        run1 = _runs_for(world["factory"], V1)[0]
        result1 = _run_export(world["factory"], {"job_id": run1.job_id})
        assert result1["status"] == "completed", result1

        view2 = _advance(service, world, payloads)
        states2 = {row["video_item_id"]: row["state"] for row in view2["videos"]}
        assert states2[V1] == "completed" and states2[V2] == "running", states2
        run2 = _runs_for(world["factory"], V2)[0]
        result2 = _run_export(world["factory"], {"job_id": run2.job_id})
        assert result2["status"] == "completed", result2

        # ACCEPTANCE: two DIFFERENT MP4s, one shared pack hash
        view3 = service.get_batch(
            workspace_id=WS, project_id=PROJECT, video_item_ids=[V1, V2]
        )
        rows = {row["video_item_id"]: row for row in view3["videos"]}
        assert rows[V1]["state"] == "completed" and rows[V2]["state"] == "completed"
        files = []
        for vid in (V1, V2):
            output = rows[vid]["output"]
            assert output and output["size_bytes"] > 0, (vid, output)
            files.append(output)
        assert files[0]["sha256"] != files[1]["sha256"], "hai video phải khác nhau"
        assert files[0]["path"] != files[1]["path"]
        assert view3["pack_hash"] == view["pack_hash"]
        assert view3["cast"]["ok"] is True

        # RESTART: a fresh service instance adopts the same rows, no new job
        counts2 = _counts(world["factory"])
        restarted = _batch_service(world)
        reentry = _create(restarted, world, payloads)
        assert reentry["batch_key"] == view["batch_key"]
        assert _counts(world["factory"]) == counts2, "restart must not duplicate jobs"
        restart_rows = {row["video_item_id"]: row for row in reentry["videos"]}
        assert restart_rows[V2]["output"]["sha256"] == files[1]["sha256"]
        assert reentry["pack_hash"] == view["pack_hash"], "cast must not change"

        # measurements stay honest: no fabricated throughput/30-minute numbers
        assert reentry["metrics"]["measured"] is False
        assert reentry["metrics"]["forecast_30min"] == "unmeasured"
    finally:
        mp.undo()


def _fail_job(factory: Any, job_id: str, err: Exception) -> None:
    """Apply the worker's terminal-failure path on the durable job."""
    from app.persistence.jobs import JobRepository

    with factory() as session:
        repo = JobRepository(session)
        rec = repo.get_job(job_id)
        if str(rec.state) == "queued":
            rec = repo.transition_job(
                job_id,
                "running",
                actor="reconciler",
                expected_revision=rec.revision,
            )
        repo.transition_job(
            job_id,
            "failed",
            actor="reconciler",
            expected_revision=rec.revision,
            error={"code": "series_batch_export_failed", "detail": str(err)},
        )
        session.commit()


def _runs_for(factory: Any, video_item_id: str) -> list[Any]:
    from sqlalchemy import select

    from app.persistence.models import S12ExportRun

    with factory() as session:
        return list(
            session.scalars(
                select(S12ExportRun)
                .where(
                    S12ExportRun.video_item_id == video_item_id,
                    S12ExportRun.project_id == PROJECT,
                )
                .order_by(S12ExportRun.created_at.asc())
            ).all()
        )


# ── 27.4 — error isolation + cancel per video ───────────────────────────────


def test_mf27_4_one_video_fails_the_other_keeps_its_bytes(tmp_path: Path) -> None:
    _T26._ffmpeg()
    world = _two_video_retry_world(tmp_path)
    mp = pytest.MonkeyPatch()
    _patch_world(mp, world["svc"], world["managed"])
    try:
        payloads = _export_payloads(world)
        # video 1's source is unreadable media: its export must FAIL typed
        world["sources"][V1].write_bytes(b"not-a-video")
        service = _batch_service(world)

        view = _create(service, world, payloads)
        assert view["videos"][0]["state"] == "running"
        run1 = _runs_for(world["factory"], V1)[0]
        # the REAL handler refuses broken media (RunnerError); the worker's
        # terminal-failure path is then applied on the durable job.
        try:
            failed = _run_export(world["factory"], {"job_id": run1.job_id})
            assert failed["status"] == "failed", failed
        except Exception as err:  # noqa: BLE001 - the worker records the failure
            _fail_job(world["factory"], run1.job_id, err)

        view2 = _advance(service, world, payloads)
        states = {row["video_item_id"]: row["state"] for row in view2["videos"]}
        assert states[V1] == "failed" and states[V2] == "running", states
        run2 = _runs_for(world["factory"], V2)[0]
        result2 = _run_export(world["factory"], {"job_id": run2.job_id})
        assert result2["status"] == "completed", result2

        view3 = service.get_batch(
            workspace_id=WS, project_id=PROJECT, video_item_ids=[V1, V2]
        )
        rows = {row["video_item_id"]: row for row in view3["videos"]}
        assert rows[V1]["state"] == "failed" and rows[V1]["error"] is not None
        assert rows[V2]["state"] == "completed"
        surviving = Path(rows[V2]["output"]["path"])
        assert surviving.is_file() and surviving.stat().st_size > 0
        # the failed video's row still exists (no cascade delete)
        assert [r.id for r in _runs_for(world["factory"], V1)] == [run1.id]
    finally:
        mp.undo()


def test_mf27_4_cancel_touches_exactly_one_video(tmp_path: Path) -> None:
    _T26._ffmpeg()
    world = _two_video_retry_world(tmp_path)
    mp = pytest.MonkeyPatch()
    _patch_world(mp, world["svc"], world["managed"])
    try:
        payloads = _export_payloads(world)
        service = _batch_service(world)
        view = _create(service, world, payloads)
        assert view["videos"][0]["state"] == "running"
        run1 = _runs_for(world["factory"], V1)[0]

        from app.api.routes import durable_projects as route

        cancelled = route.cancel_series_batch_video(
            project_id=PROJECT,
            body=route.SeriesBatchCancelRequest(
                video_item_ids=[V1, V2], video_item_id=V1
            ),
            workspace_id=WS,
        )
        assert cancelled["cancelled"] is True
        assert cancelled["job_id"] == run1.job_id
        assert _runs_for(world["factory"], V2) == [], "other video untouched"
        view2 = service.get_batch(
            workspace_id=WS, project_id=PROJECT, video_item_ids=[V1, V2]
        )
        rows = {row["video_item_id"]: row for row in view2["videos"]}
        assert rows[V1]["job_state"] in {"cancelling", "cancelled"}
        assert rows[V1]["run_id"] == run1.id
    finally:
        mp.undo()
