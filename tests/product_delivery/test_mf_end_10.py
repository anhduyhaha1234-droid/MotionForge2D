"""MF-END-10 — UI kho nhân vật + chọn bộ series: acceptance + negative controls.

Mọi row là CI fixture: bytes deterministic sinh trong tiến trình, SQLite cô lập
từ ``tests/conftest.py`` và ``TestClient`` chạy CHUỖI ROUTE THẬT — bằng chứng
engineering, không phải product-demo. Không GPU, không mạng, không ffmpeg.

Row map (nhị phân):

* micro repro: 5 nhóm endpoint mà UI mới dùng đều nằm trên router cũ (không
  thêm router/route mới); module FE chỉ gọi đúng các path có thật (đối chiếu
  OpenAPI); quy ước helper text tiếng Việt dưới nút của UI được giữ
  (``text-gray-400``, ≥11px, không ``text-gray-500``, không hex lạ); wiring
  component được chèn vào đúng file trong write-set.
* acceptance (qua API thật, đúng trình tự UI gọi): gợi ý là READ-ONLY và mọi
  ứng viên có lý do; MỘT thao tác xác nhận ghim được bộ và lặp lại là replay
  (0 mutation); tải lại trang vẫn giữ pin (đọc lại từ server); cập nhật kho
  (pack mới hơn của cùng nhân vật) KHÔNG tự đổi bộ đã ghim — kể cả khi có
  series pin (series thắng xếp hạng); nhập ảnh tham chiếu qua route thật làm
  ``missing_slots`` giảm; tạo asset thiếu bằng job bền vững (202 + trạng thái +
  hủy + chạy lại); chuỗi đầu-cuối "kho thiếu view → bổ sung → ghim" chạy hoàn
  toàn qua API (không cần shell).
* negative controls: trace lệch pack; đổi pin thiếu/ stale ``expected_revision``;
  pack chưa xuất bản; mask không được nhập làm artwork; phiên bản đã xuất bản
  không nhận thêm asset; prompt job không nêu view; key đích đã có asset; view
  ngoài từ vựng; hủy job không tồn tại — mỗi lỗi trả mã typed và ZERO mutation.

Ghi chú phạm vi: các row "generate" dừng ở ranh giới job (đăng ký/duyệt trạng
thái/hủy/chạy lại) vì việc chạy engine thật cần GPU — đó là R1 của MF-END-09,
không phải điều kiện của task UI này.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import inspect, select, text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import CharacterRepository
from app.persistence.models import (
    CORE_POSE_SLOTS,
    Artifact,
    ObjectRole,
    Project,
    ProjectCastMapping,
    VideoItem,
    Workspace,
)
from app.persistence.project_cast import SeriesCastEntryInput, SeriesCastRepository
from app.schemas.cast_recommendation import (
    GENERATION_PLAN_NOTE_FULL,
    GENERATION_PLAN_NOTE_MISSING,
)
from app.workflow import reference_asset_jobs

SUGGEST = "/api/v2/project-cast/recommendations"
CONFIRM = "/api/v2/project-cast/recommendations/confirm"
MAPPINGS = "/api/v2/project-cast"
ARTWORK = "/api/v2/characters/versions/{version_id}/reference-artwork"
ASSET_JOBS = "/api/v2/characters/versions/{version_id}/reference-asset-jobs"
ASSET_JOB = "/api/v2/characters/reference-asset-jobs/{job_id}"
ROLE_PATH = "/api/v2/object-intelligence/roles/{role_id}"
HERO_KEY = "ROLE-HERO"

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend" / "src"
REFLIB = FRONTEND / "features" / "reference-library"


# ── helpers: DB + managed root ────────────────────────────────────────────────


def _session():
    service = deps._job_service
    assert service is not None
    return service.session_factory()


def _managed_root() -> Path:
    service = deps._job_service
    assert service is not None
    return Path(service.managed_root)


def _png_bytes(
    width: int = 256, height: int = 256, *, gray: int = 120, mode: str = "RGBA"
) -> bytes:
    if mode == "L":
        img = Image.new("L", (width, height), gray % 256)
    else:
        img = Image.new("RGBA", (width, height), (gray % 255, 60, 200, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_managed(rel: str, data: bytes) -> Path:
    target = _managed_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _ensure_workspace(session, workspace_id: str = DEFAULT_WORKSPACE_ID) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    session.execute(
        sqlite_insert(Workspace)
        .values(id=workspace_id, name=workspace_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


def _table_census() -> dict[str, int]:
    with _session() as session:
        names = inspect(session.get_bind()).get_table_names()
        return {
            name: int(session.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one())
            for name in names
        }


def _managed_files() -> list[str]:
    root = _managed_root()
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
    )


def _mapping_rows() -> list[ProjectCastMapping]:
    with _session() as session:
        return list(session.scalars(select(ProjectCastMapping)).all())


# ── helpers: seeding (đúng convention của MF-END-07) ─────────────────────────


def _seed_series(name: str | None = None) -> dict:
    """Một series = một project + hai video; tên role cũng là role key."""
    with _session() as session:
        _ensure_workspace(session)
        project = Project(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name=name or f"Series-{uuid.uuid4().hex[:6]}",
        )
        session.add(project)
        session.flush()
        video_a = VideoItem(project_id=project.id, title="Episode A", position=0)
        video_b = VideoItem(project_id=project.id, title="Episode B", position=1)
        session.add_all([video_a, video_b])
        session.flush()
        roles: dict[str, str] = {}
        for slot, kind, video in (
            (HERO_KEY, "character", video_a),
            ("ROLE-BOOK", "prop", video_a),
        ):
            role = ObjectRole(
                workspace_id=DEFAULT_WORKSPACE_ID,
                project_id=project.id,
                video_item_id=video.id,
                source_generation="1",
                name=slot,
                kind=kind,
                status="confirmed",
            )
            session.add(role)
            session.flush()
            roles[slot] = role.id
        session.commit()
        return {
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "project_id": project.id,
            "video_a": video_a.id,
            "video_b": video_b.id,
            "roles": roles,
        }


def _create_character(client: TestClient, code: str) -> dict:
    resp = client.post(
        "/api/v2/characters",
        json={"name": f"Cast {code}", "code": code, "character_type": "character"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _attach_artifact(client: TestClient, ver_id: str, slot: str, *, gray: int) -> dict:
    data = _png_bytes(gray=gray)
    rel = f"characters/mf_end_10/{ver_id}/{slot.replace('@', '_')}.png"
    _write_managed(rel, data)
    with _session() as session:
        art = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=rel,
            state="ready",
            size_bytes=len(data),
            mime_type="image/png",
            sha256=hashlib.sha256(data).hexdigest(),
        )
        session.add(art)
        session.commit()
        artifact_id = art.id
    resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/assets",
        json={"pose_slot": slot, "artifact_id": artifact_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish(client: TestClient, ver_id: str, revision: int) -> dict:
    resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish", json={"revision": revision}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_legacy_pack(
    client: TestClient, code: str, *, slots: tuple[str, ...] = CORE_POSE_SLOTS
) -> dict:
    char = _create_character(client, code)
    ver = _create_version(client, char["id"])
    for index, slot in enumerate(slots):
        _attach_artifact(client, ver["id"], slot, gray=90 + index * 7)
    _publish(client, ver["id"], ver["revision"])
    return {"character_id": char["id"], "version_id": ver["id"], "code": code}


def _add_pack_version(
    client: TestClient, char_id: str, *, slots: tuple[str, ...] = CORE_POSE_SLOTS
) -> dict:
    """Xuất bản thêm MỘT phiên bản mới cho nhân vật đã có (cập nhật kho)."""
    ver = _create_version(client, char_id)
    for index, slot in enumerate(slots):
        _attach_artifact(client, ver["id"], slot, gray=140 + index * 5)
    _publish(client, ver["id"], ver["revision"])
    char = client.get(f"/api/v2/characters/{char_id}").json()
    return {
        "character_id": char_id,
        "version_id": ver["id"],
        "revision": ver["revision"],
        "default_version_id": char["default_version_id"],
    }


def _declare_manifest(client: TestClient, version_id: str, keys: tuple[str, ...]) -> None:
    manifest = {
        "manifest_version": 1,
        "pack_contract": "reference_pack_v1",
        "requirements": list(keys),
        "capabilities": ["source_video_motion_transfer"],
    }
    with _session() as session:
        CharacterRepository(session).declare_reference_manifest(
            version_id, DEFAULT_WORKSPACE_ID, manifest
        )
        session.commit()


def _upload_reference(
    client: TestClient, version_id: str, key: str, *, gray: int, mode: str = "RGBA"
):
    data = _png_bytes(gray=gray, mode=mode)
    return client.post(
        ARTWORK.format(version_id=version_id),
        data={"reference_key": key},
        files={"file": (f"{key.replace('@', '_')}.png", data, "image/png")},
    )


def _make_reference_pack(
    client: TestClient,
    code: str,
    *,
    keys: tuple[str, ...],
    uploaded: tuple[str, ...] | None = None,
    publish: bool = True,
) -> dict:
    """Pack reference_pack_v1 qua CHUỖI ROUTE THẬT (declare manifest → upload → publish)."""
    char = _create_character(client, code)
    ver = _create_version(client, char["id"])
    _declare_manifest(client, ver["id"], keys)
    for index, key in enumerate(uploaded if uploaded is not None else keys):
        resp = _upload_reference(client, ver["id"], key, gray=30 + index * 11)
        assert resp.status_code == 201, resp.text
    if publish:
        resp = client.get(f"/api/v2/characters/versions/{ver['id']}/validation")
        assert resp.status_code == 200, resp.text
        assert resp.json()["complete"] is True, resp.text
        _publish(client, ver["id"], ver["revision"])
    return {"character_id": char["id"], "version_id": ver["id"], "code": code}


def _freeze(series: dict, entries: list[SeriesCastEntryInput]):
    with _session() as session:
        repo = SeriesCastRepository(session)
        record, created = repo.freeze_snapshot(
            series["workspace_id"], series["project_id"], entries
        )
        session.commit()
        return record, created


def _entry(pack: dict, role_key: str = HERO_KEY) -> SeriesCastEntryInput:
    return SeriesCastEntryInput(
        role_key=role_key,
        character_id=pack["character_id"],
        pack_version_id=pack["version_id"],
    )


# ── helpers: recommendation flow (đúng cách UI gọi) ──────────────────────────


def _suggest(client: TestClient, video_id: str, *, requirements=None) -> dict:
    body: dict = {"video_item_id": video_id, "advisory": "off"}
    if requirements is not None:
        body["requirements"] = requirements
    resp = client.post(SUGGEST, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _role(plan: dict, role_key: str) -> dict:
    return next(item for item in plan["roles"] if item["role_key"] == role_key)


def _requirement(
    series: dict,
    role_key: str,
    *,
    views: list[str],
    kind: str = "character",
) -> dict:
    return {
        "role_key": role_key,
        "kind": kind,
        "object_role_id": series["roles"][role_key],
        "required_views": views,
    }


def _trace_for(plan: dict, role_key: str, pack: dict, **overrides) -> dict:
    """Trace mà UI dựng lại từ kết quả gợi ý (echo của người dùng)."""
    role = _role(plan, role_key)
    trace: dict = {
        "role_key": role_key,
        "selection_mode": "manual",
        "selected_pack_version_id": pack["version_id"],
    }
    if role["series_pin"] is not None:
        trace.update(
            {
                "selection_mode": "series_pin",
                "series_snapshot_id": role["series_pin"]["snapshot_id"],
                "series_snapshot_index": role["series_pin"]["snapshot_index"],
                "series_entries_sha256": role["series_pin"]["entries_sha256"],
            }
        )
    trace.update(overrides)
    return trace


def _confirm_body(
    series: dict,
    role_key: str,
    pack: dict,
    trace: dict,
    *,
    key: str,
    expected_revision: int | None = None,
) -> dict:
    body = {
        "video_item_id": series["video_a"],
        "object_role_id": series["roles"][role_key],
        "character_id": pack["character_id"],
        "pack_version_id": pack["version_id"],
        "idempotency_key": key,
        "recommendation": trace,
    }
    if expected_revision is not None:
        body["expected_revision"] = expected_revision
    return body


def _confirm(client, series, role_key, pack, trace, *, key, expected_revision=None):
    return client.post(
        CONFIRM,
        json=_confirm_body(
            series, role_key, pack, trace, key=key, expected_revision=expected_revision
        ),
    )


# ── helpers: frontend source contract ────────────────────────────────────────


def _read_src(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


def _api_literals(source: str) -> set[str]:
    """Mọi literal path ``/api/...`` trong một module FE (đã chuẩn hoá template)."""
    found: set[str] = set()
    for raw in re.findall(r"[\`\"](/api/[^\`\"]*)[\`\"]", source):
        found.add(_normalise_path(raw))
    return found


def _normalise_path(path: str) -> str:
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    return re.sub(r"\{[^}]*\}", "{}", path)


def _openapi_paths(client: TestClient) -> set[str]:
    spec = client.get("/openapi.json").json()
    return {_normalise_path(p) for p in spec["paths"]}


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_01_endpoints_ride_existing_routers(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert SUGGEST in paths and SUGGEST + "/" in paths
    assert CONFIRM in paths and CONFIRM + "/" in paths
    assert paths[SUGGEST]["post"]["tags"] == ["project-cast"]
    assert paths[CONFIRM]["post"]["tags"] == ["project-cast"]
    assert ARTWORK in paths, sorted(p for p in paths if "reference-artwork" in p)
    assert paths[ARTWORK]["post"]["tags"] == ["durable-characters"]
    assert ASSET_JOBS in paths and paths[ASSET_JOBS]["post"]["tags"] == ["durable-characters"]
    assert ASSET_JOB in paths and paths[ASSET_JOB]["get"]["tags"] == ["durable-characters"]
    assert ASSET_JOB + "/cancel" in paths and ASSET_JOB + "/retry" in paths
    assert ROLE_PATH in paths
    # Không có route mới nào bị thêm cho task này.
    assert sorted(p for p in paths if "recommendations" in p) == sorted(
        [SUGGEST, SUGGEST + "/", CONFIRM, CONFIRM + "/"]
    )
    app_source = (REPO_ROOT / "app/api/app.py").read_text(encoding="utf-8")
    assert app_source.count("project_cast.router") == 1


def test_micro_02_frontend_module_calls_only_real_routes(client: TestClient) -> None:
    source = (REFLIB / "referenceLibraryApi.ts").read_text(encoding="utf-8")
    called = _api_literals(source)
    assert called, "module phải chứa literal path /api/..."
    assert called <= _openapi_paths(client), sorted(called - _openapi_paths(client))
    expected = {
        _normalise_path(SUGGEST),
        _normalise_path(CONFIRM),
        _normalise_path(ARTWORK),
        _normalise_path(ASSET_JOBS),
        _normalise_path(ASSET_JOB),
        _normalise_path(ASSET_JOB + "/cancel"),
        _normalise_path(ASSET_JOB + "/retry"),
        _normalise_path(ROLE_PATH),
    }
    assert expected <= called, sorted(expected - called)


def test_micro_03_ui_helper_text_conventions(client: TestClient) -> None:
    module_files = [
        REFLIB / "referenceLibraryApi.ts",
        REFLIB / "reasonText.ts",
        REFLIB / "ReferenceViewBoard.tsx",
        REFLIB / "CastRecommendationPanel.tsx",
        REFLIB / "index.ts",
    ]
    component_files = [
        REFLIB / "ReferenceViewBoard.tsx",
        REFLIB / "CastRecommendationPanel.tsx",
    ]
    for path in module_files:
        text_src = path.read_text(encoding="utf-8")
        assert "text-gray-500" not in text_src, path.name
        assert not re.search(r"#[0-9a-fA-F]{6}\b", text_src), path.name
    for path in component_files:
        text_src = path.read_text(encoding="utf-8")
        assert "var(--" in text_src, path.name
    board = (REFLIB / "ReferenceViewBoard.tsx").read_text(encoding="utf-8")
    panel = (REFLIB / "CastRecommendationPanel.tsx").read_text(encoding="utf-8")
    helpers = ("cast-confirm", "recommend-retry", "ref-views-retry", "ref-job-cancel",
               "ref-job-retry", "ref-job-dismiss")
    combined = board + panel
    for testid in helpers:
        idx = combined.find(f'data-testid="{testid}"')
        assert idx != -1, testid
        window = combined[idx : idx + 800]
        assert "text-[11px] text-gray-400" in window, testid
    for rel in (
        "app/(app)/characters/page.tsx",
        "features/project-cast/ProjectCastPicker.tsx",
        "features/project-cast/LibraryPicker.tsx",
        "features/project-cast/CompatibilityWarnings.tsx",
    ):
        src = _read_src(rel)
        assert "text-gray-500" not in src, rel
        # helper dưới nút phải là gray-400 (hoặc sáng hơn: --text-muted #94a3b8)
        assert "text-gray-400" in src or "text-[var(--text-muted)]" in src, rel


def test_micro_04_components_wired_into_write_set_files() -> None:
    page = _read_src("app/(app)/characters/page.tsx")
    assert 'from "@/features/reference-library"' in page
    assert "<ReferenceViewBoard" in page
    assert "versionId={selectedVersion.id}" in page
    picker = _read_src("features/project-cast/ProjectCastPicker.tsx")
    assert 'from "@/features/reference-library"' in picker
    assert "<CastRecommendationPanel" in picker
    assert "objectRoleId={objectRoleId}" in picker
    assert 'data-testid="project-cast-picker"' in picker  # hành vi cũ giữ nguyên
    assert 'data-testid="cast-submit"' in picker


# ── acceptance (E2E qua API thật, đúng trình tự UI) ───────────────────────────


def test_acceptance_01_suggestion_is_read_only_and_every_candidate_has_reasons(
    client: TestClient,
) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "heroA1")
    _make_reference_pack(client, "refA1", keys=("front@character", "side@character"))
    before_census = _table_census()
    before_files = _managed_files()

    plan = _suggest(client, series["video_a"])

    assert plan["read_only"] is True
    assert plan["mutations"] == 0
    assert plan["manual_choice_available"] is True
    role = _role(plan, HERO_KEY)
    assert role["object_role_id"] == series["roles"][HERO_KEY]
    assert role["candidates"], "kho phải có ứng viên đã xuất bản"
    for candidate in role["candidates"]:
        assert candidate["reasons"], candidate["pack_version_id"]
        assert candidate["pack_version_id"]
        assert isinstance(candidate["available_views"], list)
        assert isinstance(candidate["missing_views"], list)
    assert plan["advisory"]["status"] == "not_requested"
    assert plan["advisory"]["route"]["fallback_allowed"] is False
    assert _table_census() == before_census, "gợi ý không được ghi DB"
    assert _managed_files() == before_files, "gợi ý không được ghi file"


def test_acceptance_02_single_confirm_pins_and_identical_replay_is_free(
    client: TestClient,
) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroA2")
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, hero)

    first = _confirm(client, series, HERO_KEY, hero, trace, key="ui-A2")
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["created"] is True and data["replayed"] is False
    assert data["mutations"] == 1
    assert data["mapping"]["pack_version_id"] == hero["version_id"]
    assert data["trace"]["checked_against"] == "live_recommendation"

    again = _confirm(client, series, HERO_KEY, hero, trace, key="ui-A2")
    assert again.status_code == 200, again.text
    replay = again.json()
    assert replay["replayed"] is True and replay["created"] is False
    assert replay["mutations"] == 0
    assert replay["mapping"]["id"] == data["mapping"]["id"]
    rows = _mapping_rows()
    assert len(rows) == 1 and str(rows[0].pack_version_id) == hero["version_id"]


def test_acceptance_03_reload_keeps_pin(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroA3")
    plan = _suggest(client, series["video_a"])
    confirmed = _confirm(
        client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="ui-A3"
    )
    assert confirmed.status_code == 201, confirmed.text
    mapping_id = confirmed.json()["mapping"]["id"]

    # "Tải lại trang": đọc lại từ server bằng một request mới hoàn toàn.
    listed = client.get(
        MAPPINGS, params={"project_id": series["project_id"], "limit": 50, "offset": 0}
    )
    assert listed.status_code == 200, listed.text
    rows = [
        m for m in listed.json()["mappings"] if m["object_role_id"] == series["roles"][HERO_KEY]
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == mapping_id
    assert rows[0]["pack_version_id"] == hero["version_id"]

    plan2 = _suggest(client, series["video_a"])
    role2 = _role(plan2, HERO_KEY)
    assert role2["selected_pack_version_id"] == hero["version_id"]


def test_acceptance_04_library_update_never_switches_the_pin(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroA4")
    _freeze(series, [_entry(hero)])
    plan = _suggest(client, series["video_a"])
    role = _role(plan, HERO_KEY)
    assert role["selection_mode"] == "series_pin"
    confirmed = _confirm(
        client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="ui-A4"
    )
    assert confirmed.status_code == 201, confirmed.text
    pinned_before = confirmed.json()["mapping"]

    # Cập nhật kho: phiên bản mới hơn của CÙNG nhân vật (nhiều view hơn).
    updated = _add_pack_version(client, hero["character_id"])

    plan2 = _suggest(client, series["video_a"])
    role2 = _role(plan2, HERO_KEY)
    assert role2["series_pin"]["live_ok"] is True
    assert role2["selection_mode"] == "series_pin"
    assert role2["selected_pack_version_id"] == hero["version_id"], "pin không tự đổi"
    assert role2["selected_pack_version_id"] != updated["version_id"]

    rows = _mapping_rows()
    assert len(rows) == 1
    assert str(rows[0].pack_version_id) == hero["version_id"]
    assert rows[0].revision == pinned_before["revision"], "pin không bị rewrite"
    assert str(rows[0].id) == pinned_before["id"]


def test_acceptance_05_upload_reference_view_without_shell(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refA5",
        keys=("front@character", "side@character"),
        uploaded=("front@character",),
        publish=False,
    )
    version_id = pack["version_id"]

    before = client.get(f"/api/v2/characters/versions/{version_id}/validation").json()
    assert before["missing_slots"] == ["side@character"]
    assert before["complete"] is False

    resp = _upload_reference(client, version_id, "side@character", gray=210)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["reference_key"] == "side@character"
    assert data["view"] == "side" and data["role"] == "character"
    assert data["purpose"] == "artwork" and data["has_alpha"] is True
    assert len(data["sha256"]) == 64

    version = client.get(f"/api/v2/characters/{pack['character_id']}/versions").json()[0]
    slots = sorted(a["pose_slot"] for a in version["assets"])
    assert slots == ["front@character", "side@character"]

    after = client.get(f"/api/v2/characters/versions/{version_id}/validation").json()
    assert after["missing_slots"] == []
    assert after["complete"] is True

    # Nhập lại cùng key = thay ảnh, không sinh bản ghi thứ hai.
    resp2 = _upload_reference(client, version_id, "side@character", gray=230)
    assert resp2.status_code == 201, resp2.text
    assert resp2.json()["replaced_existing"] is True
    version2 = client.get(f"/api/v2/characters/{pack['character_id']}/versions").json()[0]
    assert len([a for a in version2["assets"] if a["pose_slot"] == "side@character"]) == 1


def test_acceptance_06_generate_missing_asset_is_a_durable_job(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refA6",
        keys=("front@character", "side@character"),
        uploaded=("front@character",),
        publish=False,
    )
    version_id = pack["version_id"]
    prompt = "Ảnh tham chiếu view 'side' cho nhân vật: giữ nhận dạng và trang phục."

    resp = client.post(
        ASSET_JOBS.format(version_id=version_id),
        json={"reference_key": "side@character", "view_prompt": prompt},
    )
    assert resp.status_code == 202, resp.text
    submit = resp.json()
    job_id = submit["job"]["job_id"]
    assert submit["reference_key"] == "side@character"
    assert submit["view"] == "side" and submit["role"] == "character"
    assert submit["duplicate"] is False
    assert submit["content_key"]

    status = client.get(ASSET_JOB.format(job_id=job_id))
    assert status.status_code == 200, status.text
    info = status.json()
    assert info["job_id"] == job_id
    assert info["job_type"] == reference_asset_jobs.JOB_TYPE_REFERENCE_ASSET
    assert info["state"] in {"queued", "running"}

    duplicate = client.post(
        ASSET_JOBS.format(version_id=version_id),
        json={"reference_key": "side@character", "view_prompt": prompt},
    )
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["job"]["job_id"] == job_id

    cancelled = client.post(ASSET_JOB.format(job_id=job_id) + "/cancel")
    assert cancelled.status_code == 200, cancelled.text
    after_cancel = client.get(ASSET_JOB.format(job_id=job_id)).json()
    # Route giữ nguyên attempt identity: trạng thái là "cancelling" cho tới khi
    # worker xác nhận hủy. Tiến trình test không có worker, nên trạng thái cuối
    # được ghi qua ORM fixture (tiền đề terminal hợp lệ) trước khi thử chạy lại.
    assert after_cancel["state"] == "cancelling"
    from app.persistence.models import Job

    with _session() as session:
        row = session.get(Job, job_id)
        assert row is not None
        row.state = "cancelled"
        session.commit()

    retried = client.post(
        ASSET_JOB.format(job_id=job_id) + "/retry",
        json={"input_generation": "ui-retry-1"},
    )
    assert retried.status_code == 202, retried.text
    fresh = retried.json()
    assert fresh["job"]["job_id"] != job_id
    assert fresh["reference_key"] == "side@character"
    assert client.get(ASSET_JOB.format(job_id=fresh["job"]["job_id"])).json()[
        "state"
    ] in {"queued", "running"}


def test_acceptance_07_end_to_end_pick_fill_reload_repin(client: TestClient) -> None:
    """Chuỗi UI thật: thiếu view → bổ sung qua API → lần gợi ý sau đã đủ → ghim."""
    series = _seed_series()
    pack = _make_reference_pack(
        client,
        "refA7",
        keys=("front@character", "side@character", "back@character"),
        uploaded=("front@character", "side@character", "back@character"),
    )
    requirement = _requirement(series, HERO_KEY, views=["front", "side", "back", "sitting"])

    plan = _suggest(client, series["video_a"], requirements=[requirement])
    role = _role(plan, HERO_KEY)
    assert role["candidates"], role
    candidate = next(
        c for c in role["candidates"] if c["pack_version_id"] == pack["version_id"]
    )
    assert candidate["missing_views"] == ["sitting"]
    assert candidate["covers_required_views"] is False
    assert role["generation"]["required"] is True
    assert role["generation"]["views"] == ["sitting"]
    assert role["generation"]["note"] == GENERATION_PLAN_NOTE_MISSING

    # UI: mở phiên bản DRAFT mới của cùng nhân vật để bổ sung view còn thiếu
    # (phiên bản đã xuất bản là bất biến), khai manifest đủ 4 view.
    follow = _create_version(client, pack["character_id"])
    follow_id = follow["id"]
    _declare_manifest(client, follow_id, ("front@character", "side@character",
                                          "back@character", "sitting@character"))
    _upload_reference(client, follow_id, "front@character", gray=41)

    # UI: đăng ký job tạo asset thiếu (bền vững, 202) — không cần shell.
    job = client.post(
        ASSET_JOBS.format(version_id=follow_id),
        json={
            "reference_key": "sitting@character",
            "view_prompt": "Ảnh tham chiếu view 'sitting' cho nhân vật, giữ nhận dạng.",
            "idempotency_key": "ui-A7-sitting",
        },
    )
    assert job.status_code == 202, job.text

    # UI: nhập ảnh có tác giả cho đúng view thiếu (đường không cần shell).
    uploaded = _upload_reference(client, follow_id, "sitting@character", gray=250)
    assert uploaded.status_code == 201, uploaded.text
    for key, gray in (("side@character", 61), ("back@character", 81)):
        assert _upload_reference(client, follow_id, key, gray=gray).status_code == 201
    complete = client.get(f"/api/v2/characters/versions/{follow_id}/validation").json()
    assert complete["complete"] is True, complete
    follow_publish = client.get(f"/api/v2/characters/{pack['character_id']}/versions").json()
    follow_row = next(v for v in follow_publish if v["id"] == follow_id)
    _publish(client, follow_id, follow_row["revision"])
    follow_pack = {"character_id": pack["character_id"], "version_id": follow_id}

    # Gợi ý lại: đòi hỏi đã đủ view → không còn kế hoạch tạo asset.
    plan2 = _suggest(client, series["video_a"], requirements=[requirement])
    role2 = _role(plan2, HERO_KEY)
    updated = next(
        c for c in role2["candidates"] if c["pack_version_id"] == follow_id
    )
    assert updated["covers_required_views"] is True
    assert role2["selected_pack_version_id"] == follow_id
    assert role2["generation"]["required"] is False
    assert role2["generation"]["note"] == GENERATION_PLAN_NOTE_FULL

    # Ghim bằng MỘT thao tác xác nhận, trace echo đúng như UI dựng.
    trace = _trace_for(
        plan2,
        HERO_KEY,
        follow_pack,
        required_views=["front", "side", "back", "sitting"],
    )
    confirmed = _confirm(client, series, HERO_KEY, follow_pack, trace, key="ui-A7")
    assert confirmed.status_code == 201, confirmed.text
    data = confirmed.json()
    assert data["missing_views"] == []
    assert data["mapping"]["pack_version_id"] == follow_id

    # "Tải lại trang" vẫn giữ đúng bộ vừa ghim.
    listed = client.get(
        MAPPINGS, params={"project_id": series["project_id"], "limit": 50, "offset": 0}
    ).json()
    rows = [m for m in listed["mappings"] if m["object_role_id"] == series["roles"][HERO_KEY]]
    assert len(rows) == 1 and rows[0]["pack_version_id"] == follow_id


# ── negative controls ─────────────────────────────────────────────────────────


def test_negative_01_trace_pack_mismatch_refused_with_zero_mutation(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroN1")
    other = _make_legacy_pack(client, "otherN1")
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, hero)
    body = _confirm_body(series, HERO_KEY, other, trace, key="ui-N1")
    resp = client.post(CONFIRM, json=body)
    assert resp.status_code == 409, resp.text
    assert _mapping_rows() == []


def test_negative_02_replace_without_revision_refused(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroN2")
    other = _make_legacy_pack(client, "otherN2")
    plan = _suggest(client, series["video_a"])
    first = _confirm(client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="ui-N2a")
    assert first.status_code == 201, first.text
    resp = _confirm(
        client, series, HERO_KEY, other, _trace_for(plan, HERO_KEY, other), key="ui-N2b"
    )
    assert resp.status_code == 422, resp.text
    rows = _mapping_rows()
    assert len(rows) == 1 and str(rows[0].pack_version_id) == hero["version_id"]


def test_negative_03_stale_expected_revision_refused(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroN3")
    other = _make_legacy_pack(client, "otherN3")
    plan = _suggest(client, series["video_a"])
    first = _confirm(client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="ui-N3a")
    assert first.status_code == 201, first.text
    resp = _confirm(
        client,
        series,
        HERO_KEY,
        other,
        _trace_for(plan, HERO_KEY, other),
        key="ui-N3b",
        expected_revision=999,
    )
    assert resp.status_code == 409, resp.text
    rows = _mapping_rows()
    assert len(rows) == 1 and str(rows[0].pack_version_id) == hero["version_id"]


def test_negative_04_unpublished_pack_is_not_a_live_candidate(client: TestClient) -> None:
    series = _seed_series()
    char = _create_character(client, "draftN4")
    ver = _create_version(client, char["id"])
    _attach_artifact(client, ver["id"], "front", gray=10)
    draft = {"character_id": char["id"], "version_id": ver["id"]}
    plan = _suggest(client, series["video_a"])
    assert plan["read_only"] is True
    trace = {
        "role_key": HERO_KEY,
        "selection_mode": "manual",
        "selected_pack_version_id": ver["id"],
    }
    resp = _confirm(client, series, HERO_KEY, draft, trace, key="ui-N4")
    assert resp.status_code == 409, resp.text
    assert "not a live candidate" in resp.text
    assert _mapping_rows() == []


def test_negative_05_mask_is_never_ingested_as_artwork(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refN5",
        keys=("front@character", "side@character"),
        uploaded=("front@character",),
        publish=False,
    )
    before_census = _table_census()
    resp = _upload_reference(client, pack["version_id"], "side@character", gray=77, mode="L")
    assert resp.status_code == 422, resp.text
    assert _table_census() == before_census


def test_negative_06_published_version_refuses_new_artwork(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refN6",
        keys=("front@character", "side@character"),
        uploaded=("front@character", "side@character"),
    )
    resp = _upload_reference(client, pack["version_id"], "front@character", gray=99)
    assert resp.status_code == 409, resp.text
    assert "PACK_VERSION_IMMUTABLE" in json.dumps(resp.json())


def test_negative_07_job_prompt_must_name_the_view(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refN7",
        keys=("front@character", "side@character"),
        uploaded=("front@character",),
        publish=False,
    )
    resp = client.post(
        ASSET_JOBS.format(version_id=pack["version_id"]),
        json={
            "reference_key": "side@character",
            "view_prompt": "Ảnh tham chiếu cho nhân vật, giữ nhận dạng và trang phục.",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "view prompt must name the target view" in json.dumps(detail)


def test_negative_08_job_target_key_already_present(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refN8",
        keys=("front@character", "side@character"),
        uploaded=("front@character", "side@character"),
        publish=False,
    )
    resp = client.post(
        ASSET_JOBS.format(version_id=pack["version_id"]),
        json={
            "reference_key": "side@character",
            "view_prompt": "Ảnh tham chiếu view 'side' cho nhân vật, giữ nhận dạng.",
        },
    )
    assert resp.status_code == 409, resp.text
    assert "mf_end09_target_key_present" in json.dumps(resp.json())


def test_negative_09_job_unknown_view_in_key_refused(client: TestClient) -> None:
    pack = _make_reference_pack(
        client,
        "refN9",
        keys=("front@character", "side@character"),
        uploaded=("front@character",),
        publish=False,
    )
    resp = client.post(
        ASSET_JOBS.format(version_id=pack["version_id"]),
        json={
            "reference_key": "profile@character",
            "view_prompt": "Ảnh tham chiếu view 'profile' cho nhân vật, giữ nhận dạng.",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "mf_end09" in json.dumps(resp.json())


def test_negative_10_cancel_unknown_job_is_404(client: TestClient) -> None:
    resp = client.post(ASSET_JOB.format(job_id=str(uuid.uuid4())) + "/cancel")
    assert resp.status_code == 404, resp.text
    assert "mf_end09_job_not_found" in json.dumps(resp.json())


def test_negative_11_confirm_for_foreign_role_is_404(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "heroN11")
    plan = _suggest(client, series["video_a"])
    body = _confirm_body(series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="ui-N11")
    body["object_role_id"] = str(uuid.uuid4())
    resp = client.post(CONFIRM, json=body)
    assert resp.status_code == 404, resp.text
    assert _mapping_rows() == []
