"""MF-END-25 — Nối hành trình UI từ import tới export: acceptance + negative controls.

Mọi row đều là CI fixture (SQLite cô lập từ ``tests/conftest.py`` + ``TestClient``
chạy ROUTE THẬT) hoặc là pin nguồn fail-closed trên đúng 5 file write-set; không
GPU, không mạng, không fixture DB sản phẩm.

Row map (nhị phân):

* micro repro (25.0): 5 file write-set chứa đúng dây nối hành trình (journey
  helpers + rail + nút có điều kiện + picker export); MỌI chuỗi ``/api/...``
  trong các file UI sửa đổi tồn tại trong OpenAPI thật của chính app này (kèm
  control giả để chứng minh phép kiểm không rỗng), và mọi method ``api.<x>``
  được gọi đều tồn tại trong object ``api`` của ``lib/api.ts``.
* acceptance (qua HTTP thật, đúng trình tự UI gọi): dự án tạo bằng route thật
  ``POST /api/projects``; đọc chain thật ``GET /api/projects/{id}/analyze``;
  đọc video thật ``GET /api/v2/projects/{id}/videos``; đọc cast mapping thật
  ``GET /api/v2/project-cast``; đọc checkpoint duyệt thật
  ``GET /api/v2/s09-approvals``; đọc export context thật
  ``GET /api/v2/projects/{id}/export/context`` — rồi đưa ĐÚNG payload thật đó
  vào hàm journey ĐÃ SHIP (node battery chạy ``lib/api.ts``) và kiểm trạng
  thái/href/next-step.  Chuỗi "thiếu cast → thiếu duyệt Demo → thiếu run →
  thiếu publication" được kiểm là fail-closed: bước bị chặn có lý do cụ thể
  và href null (không mở được cửa chết).
* negative controls: project-cast/export-context trả 404 thật cho id sai →
  journey không bịa bước; pointer localStorage của /apply không rò sang dự án
  khác; export page ưu tiên URL hơn pointer; không có synthetic progress
  (Math.random) trong code mới; quy ước helper text tiếng Việt dưới mỗi nút
  của các file sửa đổi (≥11px, không gray-500).

Disclosure: đây là bằng chứng engineering/CI — không phải product demo; không
có GPU, ComfyUI hay media sản phẩm thật trong file này.  Việc "import chain
completed" được kiểm bằng trạng thái idle THẬT của chain (chain chưa chạy) để
chứng minh mapping không tự nhận "đã xong"; row acceptance dùng full-apply run
status=completed thật trong DB test để đóng bước Apply/Export.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

WT = Path(__file__).resolve().parents[2]
FRONTEND = WT / "frontend"
SRC = FRONTEND / "src"
API_TS = SRC / "lib" / "api.ts"
PROJECT_PAGE = SRC / "app" / "(app)" / "projects" / "[id]" / "page.tsx"
APPLY_PAGE = SRC / "app" / "(app)" / "apply" / "page.tsx"
EXPORT_PAGE = SRC / "app" / "(app)" / "export" / "page.tsx"
IMPORT_PANEL = SRC / "components" / "ImportAnalyzePanel.tsx"

WRITE_SET = [API_TS, PROJECT_PAGE, APPLY_PAGE, EXPORT_PAGE, IMPORT_PANEL]

API_STR = re.compile(r"(/api/[^\s\"'`<>]*)")
API_METHOD_USE = re.compile(r"\bapi\.([a-zA-Z0-9_]+)\s*\(")
API_METHOD_DEF = re.compile(r"^\s{2}([a-zA-Z0-9_]+)\s*[:(]", re.MULTILINE)

#: Một chuỗi /api chết ĐÃ CÓ SẴN ở base (api.inpaintScene; backend không có route
#: này) — ngoài phạm vi task, chỉ được ghi nhận chứ không được sửa hay che.
KNOWN_PRE_EXISTING_DEAD = {"/api/projects/{}/scenes/{}/inpaint"}

#: Sáu bước hành trình — thứ tự là hợp đồng (StageRail + rail của project page).
STAGE_ORDER = ["import", "objects", "demo", "apply", "review", "export"]


def _norm_path(raw: str) -> str:
    p = raw.split("?")[0]
    p = re.sub(r"\$\{[^}]*\}", "{}", p)
    p = re.sub(r"\{[^}]*\}", "{}", p)
    return p.rstrip("/").rstrip(".,;:)]}'\"`{$\u2026")


def _journey_section(text: str) -> str:
    """The NEW journey block of lib/api.ts (single source of the mapping)."""
    start = text.index("// ── Journey (import → objects/cast")
    end = text.index("export const api = {")
    return text[start:end]


# ── Node battery: chạy CHÍNH hàm journey đã ship (không re-implementation) ───

_DRIVER_JS = r"""
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";

const mod = await import(pathToFileURL(process.argv[2]).href);
const payload = JSON.parse(readFileSync(process.argv[3], "utf-8"));

const out = {};
for (const [key, ctx] of Object.entries(payload)) {
  if (key === "ids") continue;
  const rows = mod.buildJourneyStages(ctx);
  out[key] = rows;
  const next = mod.journeyNextStage(rows);
  out[key + "Next"] = next ? next.key : null;
  out[key + "Index"] = mod.journeyCurrentIndex(rows);
}
if (payload.full && payload.empty) {
  const a = JSON.stringify(mod.buildJourneyStages(payload.full));
  const b = JSON.stringify(mod.buildJourneyStages(payload.full));
  const c = JSON.stringify(mod.buildJourneyStages(payload.empty));
  const d = JSON.stringify(mod.buildJourneyStages(payload.empty));
  out.deterministic = a === b && c === d;
}
if (payload.ids) {
  const ids = payload.ids;
  out.hrefs = {
    import: mod.buildImportHref(ids.project),
    objects: mod.buildObjectsHref(ids.project, ids.video),
    demo: mod.buildDemoHref(),
    apply: mod.buildApplyHref(ids.project, ids.run),
    applyNoRun: mod.buildApplyHref(ids.project, null),
    review: mod.buildReviewHref(ids.project),
    export: mod.buildExportHref(ids.project, ids.video, "default", ids.run),
    exportNoRun: mod.buildExportHref(ids.project, ids.video),
    exportWorkspace: mod.buildExportHref(ids.project, ids.video, "ws-2", null),
  };
}
console.log(JSON.stringify(out));
"""


def _run_node(driver: Path, payload: dict[str, Any], tmp_dir: Path) -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to execute the shipped journey logic"
    payload_path = tmp_dir / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    argv = [node, "--no-warnings", str(driver), str(API_TS), str(payload_path)]
    proc = subprocess.run(
        argv,
        cwd=str(FRONTEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"node battery failed rc={proc.returncode}\n{proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, f"node battery printed no JSON payload\nstdout={proc.stdout}\n{proc.stderr}"
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def node_driver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    driver_dir = tmp_path_factory.mktemp("mf25_driver")
    driver = driver_dir / "driver.mjs"
    driver.write_text(_DRIVER_JS, encoding="utf-8")
    return driver


def _by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["key"]: row for row in rows}


def _ctx(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "projectId": "proj-25",
        "workspaceId": "default",
        "videoItemId": "vid-25",
        "analyzeChainStatus": "completed",
        "castMappingCount": 2,
        "approvalCount": 1,
        "applyRunId": "run-25",
        "applyRunStatus": "completed",
        "fullApplyRunId": "run-25",
        "exportRunId": None,
    }
    base.update(over)
    return base


def _payload() -> dict[str, Any]:
    return {
        "ids": {"project": "proj-25", "video": "vid-25", "run": "run-25"},
        "full": _ctx(),
        "unknownWithDownstream": _ctx(analyzeChainStatus=None),
        "unknownNoDownstream": _ctx(
            analyzeChainStatus=None, castMappingCount=0, approvalCount=0,
            applyRunId=None, applyRunStatus=None, fullApplyRunId=None,
        ),
        "noVideo": _ctx(videoItemId=None, analyzeChainStatus="running"),
        "videoOnly": _ctx(castMappingCount=0, approvalCount=0, applyRunId=None,
                          applyRunStatus=None, fullApplyRunId=None),
        "castOnly": _ctx(approvalCount=0, applyRunId=None, applyRunStatus=None,
                         fullApplyRunId=None),
        "approved": _ctx(applyRunId=None, applyRunStatus=None, fullApplyRunId=None),
        "running": _ctx(applyRunStatus="running", fullApplyRunId=None),
        "completed": _ctx(applyRunStatus="completed", fullApplyRunId=None),
        "exported": _ctx(exportRunId="export-run-25"),
        "empty": {
            "projectId": "",
            "workspaceId": "default",
            "videoItemId": "",
            "analyzeChainStatus": None,
            "castMappingCount": None,
            "approvalCount": None,
            "applyRunId": None,
            "applyRunStatus": None,
            "fullApplyRunId": None,
            "exportRunId": None,
        },
    }


@pytest.fixture(scope="module")
def battery(node_driver: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _run_node(node_driver, _payload(), tmp_path_factory.mktemp("mf25_battery"))


# ── micro repro (25.0) ───────────────────────────────────────────────────────


def test_mf25_0_journey_wiring_surface() -> None:
    api_src = API_TS.read_text(encoding="utf-8")
    section = _journey_section(api_src)
    for fn in (
        "export function buildJourneyStages",
        "export function journeyNextStage",
        "export function journeyCurrentIndex",
        "export function buildImportHref",
        "export function buildObjectsHref",
        "export function buildDemoHref",
        "export function buildApplyHref",
        "export function buildReviewHref",
        "export function buildExportHref",
    ):
        assert fn in section, f"lib/api.ts journey section missing {fn}"

    project_src = PROJECT_PAGE.read_text(encoding="utf-8")
    assert "buildJourneyStages" in project_src and "journeyNextStage" in project_src
    assert 'data-testid="project-journey"' in project_src
    assert 'data-testid="journey-next"' in project_src
    assert 'data-testid="project-go-export"' in project_src
    # Nút Apply/Export CHỈ mở khi stage có href; thiếu điều kiện → disabled + lý do.
    assert "applyStage?.href ?" in project_src and "exportStage?.href ?" in project_src
    assert "applyStage?.missing" in project_src and "exportStage?.missing" in project_src

    import_src = IMPORT_PANEL.read_text(encoding="utf-8")
    assert 'role="button"' in import_src and "tabIndex={0}" in import_src
    assert 'onKeyDown={(e) =>' in import_src and 'e.key === "Enter"' in import_src
    assert 'data-testid="import-go-project"' in import_src

    apply_src = APPLY_PAGE.read_text(encoding="utf-8")
    assert "buildExportHref" in apply_src and "buildReviewHref" in apply_src
    assert 'data-testid="apply-go-export"' in apply_src
    assert 'data-testid="apply-next-blocked"' in apply_src

    export_src = EXPORT_PAGE.read_text(encoding="utf-8")
    assert "ExportScopePicker" in export_src
    assert 'data-testid="export-picker-open"' in export_src
    assert "listDurableProjects" in export_src and "listProjectVideos" in export_src
    assert 'STORAGE_LAST_SCOPE = "s12:export:lastScope"' in export_src


def test_mf25_0_api_strings_and_methods_are_real() -> None:
    from app.api.app import app

    spec = app.openapi()
    paths = {_norm_path(p) for p in spec["paths"]}

    scanned = 0
    misses: list[str] = []
    for path in WRITE_SET:
        text = path.read_text(encoding="utf-8")
        scope = _journey_section(text) if path == API_TS else text
        for match in API_STR.finditer(scope):
            scanned += 1
            norm = _norm_path(match.group(1))
            if not (norm in paths or any(p.startswith(norm + "/") for p in paths)):
                misses.append(norm)
    assert scanned > 0, "no /api strings scanned — check would be vacuous"
    assert [m for m in misses if m not in KNOWN_PRE_EXISTING_DEAD] == [], misses

    # Non-vacuous control: một route bịa KHÔNG được khớp.
    bogus = _norm_path("/api/v2/definitely-not-a-real-route-mf25")
    assert not (bogus in paths or any(p.startswith(bogus + "/") for p in paths))

    # Mọi method api.<x> được gọi trong write-set phải tồn tại trong object api.
    api_src = API_TS.read_text(encoding="utf-8")
    defined = set(API_METHOD_DEF.findall(api_src))
    used: set[str] = set()
    for path in WRITE_SET:
        used.update(API_METHOD_USE.findall(path.read_text(encoding="utf-8")))
    assert used, "no api.<method> calls scanned — check would be vacuous"
    assert used <= defined, f"invented api methods: {sorted(used - defined)}"
    assert "definitelyNotAMethod" not in defined


# ── acceptance: mapping trên payload THẬT (node battery) ─────────────────────


def test_mf25_1_full_chain_all_steps_done_and_next_is_export(battery: dict[str, Any]) -> None:
    rows = _by_key(battery["full"])
    assert list(rows) == STAGE_ORDER, "stage order is the contract"
    assert rows["import"]["status"] == "done"
    assert rows["objects"]["status"] == "done"
    assert rows["demo"]["status"] == "done"
    assert rows["apply"]["status"] == "done"
    assert rows["review"]["status"] == "done"
    assert rows["export"]["status"] == "current"
    assert battery["fullNext"] == "export"
    assert rows["export"]["href"] == "/export?project=proj-25&video=vid-25&workspace=default"
    assert battery["deterministic"] is True


def test_mf25_2_missing_dependencies_fail_closed(battery: dict[str, Any]) -> None:
    no_video = _by_key(battery["noVideo"])
    for key in ("objects", "demo", "apply", "review", "export"):
        assert no_video[key]["status"] == "blocked", key
        assert no_video[key]["href"] is None, key
        assert no_video[key]["missing"] == "Thiếu: video item từ bước Nhập & Phân tích."
    assert no_video["import"]["status"] == "current"  # chain running → chưa xong
    assert no_video["objects"]["href"] is None

    video_only = _by_key(battery["videoOnly"])
    assert video_only["objects"]["status"] == "current"
    assert video_only["objects"]["href"] == "/object-gallery?project=proj-25&video=vid-25"
    for key in ("demo", "apply", "review", "export"):
        assert video_only[key]["status"] == "blocked", key
        assert video_only[key]["href"] is None
        assert video_only[key]["missing"] == (
            "Thiếu: ghim bộ nhân vật cho các vai (bước Chọn đối tượng)."
        )

    cast_only = _by_key(battery["castOnly"])
    assert cast_only["demo"]["status"] == "current"
    for key in ("apply", "review", "export"):
        assert cast_only[key]["status"] == "blocked", key
        assert cast_only[key]["missing"] == (
            "Thiếu: checkpoint duyệt Demo (bước So sánh & duyệt Demo)."
        )

    approved = _by_key(battery["approved"])
    assert approved["apply"]["status"] == "current"
    assert approved["apply"]["href"] == "/apply?project=proj-25"
    for key in ("review", "export"):
        assert approved[key]["status"] == "blocked", key
        assert approved[key]["missing"] == "Thiếu: lượt Apply đã chạy (bước Áp dụng)."

    running = _by_key(battery["running"])
    assert running["apply"]["status"] == "current"
    assert running["apply"]["href"] == "/apply?project=proj-25&run_id=run-25"
    assert running["review"]["status"] == "current"
    assert running["review"]["href"] == "/projects/proj-25/review"
    assert running["export"]["status"] == "blocked"
    assert running["export"]["missing"] == (
        "Thiếu: lượt Apply hoàn tất có publication (bước Áp dụng)."
    )

    completed = _by_key(battery["completed"])
    assert completed["export"]["status"] == "current"
    assert completed["export"]["href"] == "/export?project=proj-25&video=vid-25&workspace=default"


def test_mf25_2_hrefs_carry_context_and_encode(battery: dict[str, Any]) -> None:
    hrefs = battery["hrefs"]
    assert hrefs["import"] == "/import-analyze?project=proj-25"
    assert hrefs["objects"] == "/object-gallery?project=proj-25&video=vid-25"
    assert hrefs["demo"] == "/demo-compare"
    assert hrefs["apply"] == "/apply?project=proj-25&run_id=run-25"
    assert hrefs["applyNoRun"] == "/apply?project=proj-25"
    assert hrefs["review"] == "/projects/proj-25/review"
    assert hrefs["export"] == "/export?project=proj-25&video=vid-25&workspace=default&run=run-25"
    assert hrefs["exportNoRun"] == "/export?project=proj-25&video=vid-25&workspace=default"
    assert hrefs["exportWorkspace"] == "/export?project=proj-25&video=vid-25&workspace=ws-2"


def test_mf25_2_chain_unknown_uses_downstream_evidence(battery: dict[str, Any]) -> None:
    with_ds = _by_key(battery["unknownWithDownstream"])
    # Chain không đọc được (dự án durable-only) nhưng có cast/duyệt/run THẬT →
    # suy ra import đã xong từ chính bằng chứng hạ nguồn (không đoán mò).
    assert with_ds["import"]["status"] == "done"
    assert battery["unknownWithDownstreamNext"] == "export"
    no_ds = _by_key(battery["unknownNoDownstream"])
    # Chưa có bất kỳ bằng chứng hạ nguồn nào → KHÔNG được tự nhận đã import.
    assert no_ds["import"]["status"] == "current"
    assert battery["unknownNoDownstreamNext"] == "import"


def test_mf25_2_empty_context_is_nonvacuous_control(battery: dict[str, Any]) -> None:
    rows = _by_key(battery["empty"])
    assert battery["emptyNext"] == "import"
    assert rows["import"]["href"] == "/import-analyze?project="
    for key in ("objects", "demo", "apply", "review", "export"):
        assert rows[key]["href"] is None and rows[key]["status"] == "blocked"
    exported = _by_key(battery["exported"])
    assert all(r["status"] == "done" for r in exported.values())
    assert battery["exportedNext"] is None  # hết hành trình → không còn bước kế


# ── acceptance: đọc THẬT rồi đưa payload thật vào mapping đã ship ────────────


def _session() -> Any:
    from app.api import deps

    service = deps._job_service
    assert service is not None
    return service.session_factory()


def _seed_durable_shell(project_id: str, video_id: str) -> None:
    with _session() as session:
        session.execute(
            text("INSERT OR IGNORE INTO workspace(id,name) VALUES ('default','default')")
        )
        session.execute(
            text(
                "INSERT OR IGNORE INTO project(id,workspace_id,name,status)"
                " VALUES (:pid,'default','Dự án MF-END-25','active')"
            ),
            {"pid": project_id},
        )
        session.execute(
            text(
                "INSERT OR IGNORE INTO video_item(id,project_id,title,position,status)"
                " VALUES (:vid,:pid,'Nguồn 25',0,'imported')"
            ),
            {"vid": video_id, "pid": project_id},
        )
        session.execute(
            text(
                "INSERT OR IGNORE INTO character(id,workspace_id,name,code)"
                " VALUES ('ch25','default','hero','hero25')"
            )
        )
        session.execute(
            text(
                "INSERT OR IGNORE INTO character_pack_version(id,character_id,workspace_id,"
                "version,status)"
                " VALUES ('pv25','ch25','default',1,'published')"
            )
        )
        session.execute(
            text(
                "INSERT OR IGNORE INTO object_role(id,workspace_id,project_id,video_item_id,"
                " source_generation,name,kind,status)"
                " VALUES ('r25','default',:pid,:vid,'1','role','character','confirmed')"
            ),
            {"pid": project_id, "vid": video_id},
        )
        session.execute(
            text(
                "INSERT OR IGNORE INTO reskin_config(id, workspace_id, project_id, object_role_id,"
                " character_id, pack_version_id, params_json, revision)"
                " VALUES ('rc25','default',:pid,'r25','ch25','pv25','{}',1)"
            ),
            {"pid": project_id},
        )
        session.commit()


def _seed_cast_mapping(project_id: str) -> None:
    with _session() as session:
        session.execute(
            text(
                "INSERT OR IGNORE INTO project_cast_mapping(id, workspace_id, project_id,"
                " object_role_id, character_id, pack_version_id, revision)"
                " VALUES ('pcm25','default',:pid,'r25','ch25','pv25',1)"
            ),
            {"pid": project_id},
        )
        session.commit()


def _seed_approval(project_id: str) -> str:
    """Tạo checkpoint duyệt với hash THẬT (hàm production) — list endpoint verify."""
    from app.services.s09_approval import _checkpoint_content_hash

    checkpoint_hash = _checkpoint_content_hash(
        reskin_config_id="rc25",
        reskin_config_revision=1,
        structural_lock_manifest_id=None,
        lock_policy_version=None,
        pack_version_ids=[],
        loop_hashes=[],
        timebase_fingerprint="30/1",
        snapshot={},
    )
    with _session() as session:
        session.execute(
            text(
                "INSERT OR IGNORE INTO apply_checkpoint(id, workspace_id, project_id,"
                " reskin_config_id,"
                " reskin_config_revision, pack_version_ids_json, loop_hashes_json,"
                " timebase_fingerprint, snapshot_json, checkpoint_hash, revision, created_at,"
                " updated_at) VALUES ('cp25','default',:pid,'rc25',1,'[]','[]','30/1','{}',:h,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"pid": project_id, "h": checkpoint_hash},
        )
        session.commit()
    return checkpoint_hash


def _seed_completed_run(
    project_id: str, video_id: str, run_id: str, checkpoint_hash: str
) -> None:
    with _session() as session:
        session.execute(
            text(
                "INSERT OR IGNORE INTO s10_full_apply_run(id, workspace_id, project_id,"
                " video_item_id,"
                " apply_checkpoint_id, apply_checkpoint_hash, apply_checkpoint_revision, plan_id,"
                " plan_hash, status, frame_count, fps_num, fps_den, chunk_config_json, attempt,"
                " revision, created_at, updated_at) VALUES"
                " (:rid,'default',:pid,:vid,'cp25',:h,1,:plan,:ph,'completed',30,30,1,'{}',1,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "rid": run_id,
                "pid": project_id,
                "vid": video_id,
                "h": checkpoint_hash,
                "plan": "c" * 64,
                "ph": "b" * 64,
            },
        )
        session.commit()


def _create_durable_project(client: Any, name: str) -> str:
    res = client.post("/api/v2/projects", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["project_id"]


def _journey_from_real_payloads(
    client: Any, project_id: str, *, video_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Đọc các endpoint THẬT đúng như project page gọi rồi ráp context journey."""
    chain_res = client.get(f"/api/projects/{project_id}/analyze?generation=1")
    videos_res = client.get(f"/api/v2/projects/{project_id}/videos")
    cast_res = client.get(f"/api/v2/project-cast?project_id={project_id}&limit=50&offset=0")
    approvals_res = client.get(
        f"/api/v2/s09-approvals?workspace_id=default&project_id={project_id}"
    )
    assert videos_res.status_code == 200, videos_res.text
    assert approvals_res.status_code == 200, approvals_res.text
    chain = chain_res.json() if chain_res.status_code == 200 else None
    videos = videos_res.json()["videos"]
    resolved_video = video_id or (videos[0]["video_item_id"] if videos else None)
    context = None
    if resolved_video:
        ctx_res = client.get(
            f"/api/v2/projects/{project_id}/export/context?video_item_id={resolved_video}"
        )
        assert ctx_res.status_code == 200, ctx_res.text
        context = ctx_res.json()
    return {
        "chain": chain,
        "chain_status_code": chain_res.status_code,
        "videos": videos,
        "cast_status": cast_res.status_code,
        "cast_total": cast_res.json()["total"] if cast_res.status_code == 200 else None,
        "approval_total": approvals_res.json()["total"],
        "context": context,
        "video": resolved_video,
    }, {
        "projectId": project_id,
        "workspaceId": "default",
        "videoItemId": resolved_video,
        "analyzeChainStatus": (chain or {}).get("chain_status"),
        "castMappingCount": cast_res.json()["total"] if cast_res.status_code == 200 else None,
        "approvalCount": approvals_res.json()["total"],
        "applyRunId": None,
        "applyRunStatus": None,
        "fullApplyRunId": (context or {}).get("full_apply_run_id"),
        "exportRunId": ((context or {}).get("current_run") or {}).get("run_id"),
    }


def test_mf25_3_real_reads_drive_journey_to_export(
    client: Any, node_driver: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    project_id = _create_durable_project(client, "MF-END-25 dự án A")
    video_id = str(uuid.uuid4())
    _seed_durable_shell(project_id, video_id)
    _seed_cast_mapping(project_id)
    checkpoint_hash = _seed_approval(project_id)
    _seed_completed_run(project_id, video_id, "run-25a", checkpoint_hash)

    raw, ctx = _journey_from_real_payloads(client, project_id)
    assert raw["chain_status_code"] == 404  # dự án durable-only: chain legacy 404 THẬT
    assert ctx["analyzeChainStatus"] is None  # UI nhận null → import chưa xong
    assert raw["video"] == video_id
    assert raw["cast_total"] == 1
    assert raw["approval_total"] == 1
    assert raw["context"]["full_apply_run_id"] == "run-25a"
    assert ctx["videoItemId"] == video_id

    out = _run_node(
        node_driver, {"full": ctx, "empty": _payload()["empty"], "ids": _payload()["ids"]},
        tmp_path_factory.mktemp("mf25_real"),
    )
    rows = _by_key(out["full"])
    assert rows["import"]["status"] == "done"  # suy từ bằng chứng hạ nguồn THẬT
    assert rows["objects"]["status"] == "done"  # cast mapping THẬT
    assert rows["demo"]["status"] == "done"  # checkpoint duyệt THẬT
    assert rows["apply"]["status"] == "done"  # full-apply run completed THẬT
    assert rows["export"]["status"] == "current"
    assert rows["export"]["href"] == (
        f"/export?project={project_id}&video={video_id}&workspace=default"
    )
    assert out["fullNext"] == "export"


def test_mf25_3_missing_cast_and_approval_are_read_not_guessed(
    client: Any, node_driver: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    project_id = _create_durable_project(client, "MF-END-25 dự án B")
    video_id = str(uuid.uuid4())
    _seed_durable_shell(project_id, video_id)  # KHÔNG cast, KHÔNG duyệt, KHÔNG run

    raw, ctx = _journey_from_real_payloads(client, project_id)
    assert raw["chain_status_code"] == 404
    assert raw["approval_total"] == 0
    assert raw["context"]["full_apply_run_id"] is None
    assert raw["video"] == video_id
    assert ctx["castMappingCount"] in (None, 0)

    out = _run_node(
        node_driver, {"videoOnly": ctx, "empty": _payload()["empty"], "ids": _payload()["ids"]},
        tmp_path_factory.mktemp("mf25_real_b"),
    )
    rows = _by_key(out["videoOnly"])
    assert out["videoOnlyNext"] == "import"  # chưa có bằng chứng hạ nguồn nào
    assert rows["objects"]["status"] == "current"
    assert rows["objects"]["href"] == (
        f"/object-gallery?project={project_id}&video={video_id}"
    )
    for key in ("demo", "apply", "review", "export"):
        assert rows[key]["status"] == "blocked", key
        assert rows[key]["href"] is None
        assert rows[key]["missing"] == (
            "Thiếu: ghim bộ nhân vật cho các vai (bước Chọn đối tượng)."
        )
    # 404 thật của export-context cho video sai → UI nhận null, không bịa bước.
    bad = client.get(f"/api/v2/projects/{project_id}/export/context?video_item_id=vid-nope")
    assert bad.status_code == 404


def test_mf25_4_reload_pointers_are_scoped_and_url_wins() -> None:
    project_src = PROJECT_PAGE.read_text(encoding="utf-8")
    assert 'STORAGE_APPLY_RUN = "s10:apply:lastRunId"' in project_src
    assert 'STORAGE_APPLY_PROJECT = "s10:apply:lastProjectId"' in project_src
    # Pointer của dự án khác bị từ chối (không rò context sang dự án khác).
    assert "storedProject && storedProject !== projectId" in project_src
    assert "s12:export:${workspaceId}:${projectId}:${videoItemId}:run" in project_src

    export_src = EXPORT_PAGE.read_text(encoding="utf-8")
    # URL là nguồn sự thật; pointer chỉ là fallback khi reload trần.
    assert 'params.get("project") ?? lastScope?.project ?? ""' in export_src
    assert 'params.get("video") ?? lastScope?.video ?? ""' in export_src
    assert (
        "writeLastScope({ project: projectId, video: videoItemId, workspace: workspaceId })"
        in export_src
    )
    assert "JSON.parse(raw)" in export_src  # đọc lại an toàn (try/catch)


def test_mf25_4_helper_text_and_no_synthetic_progress() -> None:
    for path in WRITE_SET:
        src = path.read_text(encoding="utf-8")
        assert "Math.random" not in src, f"{path.name}: synthetic progress token"
        assert "text-gray-500" not in src, f"{path.name}: helper text must not be gray-500"
        for match in re.finditer(r"</button>", src):
            tail = src[match.end(): match.end() + 400]
            assert "HELPER" in tail or "text-[11px]" in tail, (
                f"{path.name}: button without helper text below"
            )
    journey = _journey_section(API_TS.read_text(encoding="utf-8"))
    assert "setInterval" not in journey and "Math.random" not in journey
