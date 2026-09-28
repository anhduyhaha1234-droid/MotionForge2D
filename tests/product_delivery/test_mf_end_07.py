"""MF-END-07 — cast recommendation / confirm API: acceptance + negative controls.

Every row is a CI fixture: deterministic bytes generated in-process, the
per-test isolated SQLite database from ``tests/conftest.py``, and the FastAPI
``TestClient`` exercising the REAL route chain — engineering evidence, never
product-demo evidence.  No GPU, no network, no ffmpeg: the suggestion route is
always called with ``advisory="off"`` so the pinned advisory client is never
reached from a test process.

Row map (binary):

* micro repro: both endpoints ride the EXISTING ``/api/v2/project-cast`` router
  (the app still includes that router exactly once); role requirements AND the
  series pin are derived on the SERVER — the client never supplies them.
* acceptance: the suggestion mutates NOTHING (every table's row count and every
  managed file unchanged); the confirm writes through the existing cast
  authority and echoes the verified trace; an identical confirm replays without
  a second write; a series-pin trace confirms onto the frozen pack and freezes
  no new snapshot; missing required views surface as actionable warnings plus a
  generation plan (and disappear when the assets cover the requirement); the
  confirm introduces no new store — ``project_cast_mapping`` is the ONLY table
  that grows.
* negative controls: stale series snapshot, choice ≠ trace proposal, filtered
  (incomplete) pack, capability-missing pack, foreign project/video role,
  replacement without a version guard, stale version guard, idempotency key
  bound to another payload, unknown trace views, and a ``series_pin`` trace
  that pins no snapshot — each refused with ZERO mutation.
"""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, inspect, select, text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import CharacterRepository
from app.persistence.models import (
    CORE_POSE_SLOTS,
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    ObjectRole,
    Project,
    ProjectCastMapping,
    SeriesCastSnapshot,
    SeriesCastSnapshotEntry,
    VideoItem,
    Workspace,
)
from app.persistence.project_cast import (
    SeriesCastEntryInput,
    SeriesCastRepository,
)
from app.schemas.cast_recommendation import (
    GENERATION_PLAN_NOTE_FULL,
    REQUIRED_VIEW_VOCABULARY,
)
from app.schemas.shot_reskin import ENGINE_CAPABILITY_PINS

SUGGEST = "/api/v2/project-cast/recommendations"
CONFIRM = "/api/v2/project-cast/recommendations/confirm"
HERO_KEY = "ROLE-HERO"
BOOK_KEY = "ROLE-BOOK"
EXTRA_KEY = "ROLE-EXTRA"


# ── helpers ───────────────────────────────────────────────────────────────────


def _session():
    service = deps._job_service
    assert service is not None
    return service.session_factory()


def _managed_root() -> Path:
    service = deps._job_service
    assert service is not None
    return Path(service.managed_root)


def _png_bytes(
    width: int = 256,
    height: int = 256,
    *,
    gray: int = 120,
) -> bytes:
    img = Image.new("RGBA", (width, height), (gray, 60, 200, 200))
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


def _seed_series(
    workspace_id: str = DEFAULT_WORKSPACE_ID, name: str | None = None
) -> dict:
    """One series = one project with two videos; role names double as role keys."""
    with _session() as session:
        _ensure_workspace(session, workspace_id)
        project = Project(
            workspace_id=workspace_id,
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
            (BOOK_KEY, "prop", video_a),
            ("ROLE-LOGO", "source_overlay", video_a),
            (EXTRA_KEY, "character", video_b),
        ):
            role = ObjectRole(
                workspace_id=workspace_id,
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
            "workspace_id": workspace_id,
            "project_id": project.id,
            "video_a": video_a.id,
            "video_b": video_b.id,
            "roles": roles,
        }


def _create_character(
    client: TestClient, code: str, *, character_type: str = "character"
) -> dict:
    resp = client.post(
        "/api/v2/characters",
        json={"name": f"Cast {code}", "code": code, "character_type": character_type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _attach_artifact(client: TestClient, ver_id: str, slot: str, *, gray: int) -> dict:
    data = _png_bytes(gray=gray)
    rel = f"characters/mf_end_07/{ver_id}/{slot.replace('@', '_')}.png"
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
    client: TestClient, code: str, *, character_type: str = "character"
) -> dict:
    char = _create_character(client, code, character_type=character_type)
    ver = _create_version(client, char["id"])
    for index, slot in enumerate(CORE_POSE_SLOTS):
        _attach_artifact(client, ver["id"], slot, gray=90 + index * 7)
    _publish(client, ver["id"], ver["revision"])
    return {"character_id": char["id"], "version_id": ver["id"], "code": code}


def _make_reference_pack(client: TestClient, code: str, *, keys: tuple[str, ...]) -> dict:
    """Publish a reference_pack_v1 pack through the REAL route chain."""
    char = _create_character(client, code)
    ver = _create_version(client, char["id"])
    manifest = {
        "manifest_version": 1,
        "pack_contract": "reference_pack_v1",
        "requirements": list(keys),
        "capabilities": ["source_video_motion_transfer"],
    }
    with _session() as session:
        CharacterRepository(session).declare_reference_manifest(
            ver["id"], DEFAULT_WORKSPACE_ID, manifest
        )
        session.commit()
    for index, key in enumerate(keys):
        data = _png_bytes(gray=30 + index * 11)
        resp = client.post(
            f"/api/v2/characters/versions/{ver['id']}/reference-artwork",
            data={"reference_key": key},
            files={"file": (f"{key.replace('@', '_')}.png", data, "image/png")},
        )
        assert resp.status_code == 201, resp.text
    resp = client.get(f"/api/v2/characters/versions/{ver['id']}/validation")
    assert resp.status_code == 200, resp.text
    assert resp.json()["complete"] is True, resp.text
    _publish(client, ver["id"], ver["revision"])
    return {"character_id": char["id"], "version_id": ver["id"], "code": code}


def _seed_incomplete_pack(
    *, slots: tuple[str, ...] = ("front",), character_type: str = "character"
) -> dict:
    """Published but INCOMPLETE pack (ORM-seeded precondition, negatives only)."""
    with _session() as session:
        _ensure_workspace(session)
        character = Character(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name=f"Seeded {uuid.uuid4().hex[:6]}",
            code=f"seed_{uuid.uuid4().hex[:8]}",
            character_type=character_type,
            status="ready",
        )
        session.add(character)
        session.flush()
        pack = CharacterPackVersion(
            character_id=character.id,
            workspace_id=DEFAULT_WORKSPACE_ID,
            version=1,
            status="published",
        )
        session.add(pack)
        session.flush()
        for index, slot in enumerate(slots):
            art = Artifact(
                workspace_id=DEFAULT_WORKSPACE_ID,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256=f"{index:02x}" * 32,
            )
            session.add(art)
            session.flush()
            session.add(
                CharacterAsset(
                    pack_version_id=pack.id,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    pose_slot=slot,
                    artifact_id=art.id,
                )
            )
        session.commit()
        return {"character_id": character.id, "version_id": pack.id}


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


def _suggest(client: TestClient, video_id: str) -> dict:
    resp = client.post(SUGGEST, json={"video_item_id": video_id, "advisory": "off"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _role(plan: dict, role_key: str) -> dict:
    return next(item for item in plan["roles"] if item["role_key"] == role_key)


def _trace_for(plan: dict, role_key: str, pack: dict, **overrides) -> dict:
    """The trace the client would echo for *pack* (series fields when pinned)."""
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


def _confirm(
    client: TestClient,
    series: dict,
    role_key: str,
    pack: dict,
    trace: dict,
    *,
    key: str,
    expected_revision: int | None = None,
):
    return client.post(
        CONFIRM,
        json=_confirm_body(
            series, role_key, pack, trace, key=key, expected_revision=expected_revision
        ),
    )


def _mapping_rows() -> list[ProjectCastMapping]:
    with _session() as session:
        return list(session.scalars(select(ProjectCastMapping)).all())


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


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_01_endpoints_ride_the_existing_router(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in (SUGGEST, CONFIRM):
        assert path in spec["paths"], sorted(spec["paths"])
        assert spec["paths"][path]["post"]["tags"] == ["project-cast"]
    assert sorted(p for p in spec["paths"] if "recommendations" in p) == sorted(
        [SUGGEST, SUGGEST + "/", CONFIRM, CONFIRM + "/"]
    )
    from app.api.routes import project_cast as route_module

    assert route_module.router.prefix == "/api/v2/project-cast"
    app_source = (Path(__file__).resolve().parents[2] / "app/api/app.py").read_text(
        encoding="utf-8"
    )
    assert app_source.count("project_cast.router") == 1


def test_micro_02_server_derives_requirements_and_series_pin(
    client: TestClient,
) -> None:
    series = _seed_series()
    plan = _suggest(client, series["video_a"])
    assert sorted(item["role_key"] for item in plan["roles"]) == sorted(
        [HERO_KEY, BOOK_KEY]
    )
    for role in plan["roles"]:
        assert role["object_role_id"] == series["roles"][role["role_key"]]
    assert plan["series"] is None
    assert plan["read_only"] is True
    assert plan["mutations"] == 0
    hero = _make_legacy_pack(client, "hero02")
    record, created = _freeze(series, [_entry(hero)])
    assert created is True
    plan = _suggest(client, series["video_a"])
    hero_role = _role(plan, HERO_KEY)
    assert plan["series"]["snapshot_id"] == record.id
    assert plan["series"]["snapshot_index"] == record.snapshot_index
    assert hero_role["series_pin"]["live_ok"] is True
    assert hero_role["selection_mode"] == "series_pin"
    assert hero_role["selected_pack_version_id"] == hero["version_id"]


# ── acceptance ────────────────────────────────────────────────────────────────


def test_acceptance_03_suggestion_mutates_nothing(client: TestClient) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "hero03")
    files_before = _managed_files()
    census_before = _table_census()
    plan = _suggest(client, series["video_a"])
    assert plan["read_only"] is True
    assert plan["mutations"] == 0
    assert _table_census() == census_before
    assert _managed_files() == files_before
    assert _mapping_rows() == []


def test_acceptance_04_confirm_creates_pin_from_recommendation(
    client: TestClient,
) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero04")
    plan = _suggest(client, series["video_a"])
    resp = _confirm(
        client,
        series,
        HERO_KEY,
        hero,
        _trace_for(plan, HERO_KEY, hero),
        key="k04",
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["created"] is True
    assert data["replayed"] is False
    assert data["mutations"] == 1
    assert data["mapping"]["pack_version_id"] == hero["version_id"]
    assert data["mapping"]["object_role_id"] == series["roles"][HERO_KEY]
    assert data["trace"]["verified_source"] == "library_candidate"
    assert data["trace"]["checked_against"] == "live_recommendation"
    rows = _mapping_rows()
    assert len(rows) == 1
    assert rows[0].pack_version_id == hero["version_id"]


def test_acceptance_05_confirm_replay_writes_once(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero05")
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, hero)
    first = _confirm(client, series, HERO_KEY, hero, trace, key="k05")
    assert first.status_code == 201, first.text
    second = _confirm(client, series, HERO_KEY, hero, trace, key="k05")
    assert second.status_code == 200, second.text
    data = second.json()
    assert data["replayed"] is True
    assert data["created"] is False
    assert data["mutations"] == 0
    rows = _mapping_rows()
    assert len(rows) == 1
    assert rows[0].revision == first.json()["mapping"]["revision"]


def test_acceptance_06_series_pin_trace_confirms_frozen_pack(
    client: TestClient,
) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero06")
    _freeze(series, [_entry(hero)])
    plan = _suggest(client, series["video_a"])
    role = _role(plan, HERO_KEY)
    assert role["selection_mode"] == "series_pin"
    resp = _confirm(
        client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="k06"
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["trace"]["verified_source"] == "series_pin"
    assert data["trace"]["snapshot_id"] == role["series_pin"]["snapshot_id"]
    assert data["trace"]["snapshot_index"] == role["series_pin"]["snapshot_index"]
    assert data["trace"]["entries_sha256"] == role["series_pin"]["entries_sha256"]
    assert data["mapping"]["pack_version_id"] == hero["version_id"]
    with _session() as session:
        assert session.scalar(select(func.count()).select_from(SeriesCastSnapshot)) == 1
        assert (
            session.scalar(select(func.count()).select_from(SeriesCastSnapshotEntry)) == 1
        )


def test_acceptance_13_missing_views_warn_with_generation_plan(
    client: TestClient,
) -> None:
    series = _seed_series()
    ref = _make_reference_pack(client, "ref13", keys=("front@character", "side@character"))
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(
        plan, HERO_KEY, ref, required_views=["front", "side", "back"]
    )
    resp = _confirm(client, series, HERO_KEY, ref, trace, key="k13")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["missing_views"] == ["back"]
    assert data["generation"]["required"] is True
    assert data["generation"]["views"] == ["back"]
    codes = [warning["code"] for warning in data["warnings"]]
    assert "missing_required_views" in codes
    assert "generation_plan_required" in codes
    assert any("back" in warning["detail"] for warning in data["warnings"])
    assert all(warning["action"] for warning in data["warnings"])


def test_acceptance_14_covered_views_report_no_warning(client: TestClient) -> None:
    series = _seed_series()
    ref = _make_reference_pack(client, "ref14", keys=("front@character", "side@character"))
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, ref, required_views=["front", "side"])
    resp = _confirm(client, series, HERO_KEY, ref, trace, key="k14")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["missing_views"] == []
    assert data["generation"]["required"] is False
    assert data["generation"]["note"] == GENERATION_PLAN_NOTE_FULL
    assert data["warnings"] == []


def test_acceptance_18_confirm_introduces_no_new_store(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero18")
    plan = _suggest(client, series["video_a"])
    census_before = _table_census()
    files_before = _managed_files()
    resp = _confirm(
        client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="k18"
    )
    assert resp.status_code == 201, resp.text
    census_after = _table_census()
    assert sorted(census_after) == sorted(census_before)
    delta = {
        name: census_after[name] - census_before.get(name, 0) for name in census_after
    }
    assert {name: value for name, value in delta.items() if value} == {
        "project_cast_mapping": 1
    }
    assert _managed_files() == files_before


# ── negative controls ─────────────────────────────────────────────────────────


def test_negative_07_stale_series_snapshot_refused(client: TestClient) -> None:
    series = _seed_series()
    hero_a = _make_legacy_pack(client, "hero07a")
    hero_b = _make_legacy_pack(client, "hero07b")
    _freeze(series, [_entry(hero_a)])
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, hero_a)
    _freeze(series, [_entry(hero_b)])  # a NEW snapshot supersedes the trace's basis
    resp = _confirm(client, series, HERO_KEY, hero_a, trace, key="k07")
    assert resp.status_code == 409, resp.text
    assert "stale recommendation basis" in resp.json()["detail"]
    assert _mapping_rows() == []
    with _session() as session:
        assert session.scalar(select(func.count()).select_from(SeriesCastSnapshot)) == 2


def test_negative_08_choice_not_matching_proposal_refused(
    client: TestClient,
) -> None:
    series = _seed_series()
    hero_a = _make_legacy_pack(client, "hero08a")
    hero_b = _make_legacy_pack(client, "hero08b")
    plan = _suggest(client, series["video_a"])
    resp = _confirm(
        client,
        series,
        HERO_KEY,
        hero_b,
        _trace_for(plan, HERO_KEY, hero_a),
        key="k08",
    )
    assert resp.status_code == 409, resp.text
    assert "does not match the recommendation trace proposal" in resp.json()["detail"]
    assert _mapping_rows() == []


def test_negative_09_filtered_pack_not_confirmable(client: TestClient) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "hero09")
    incomplete = _seed_incomplete_pack()
    plan = _suggest(client, series["video_a"])
    hero_role = _role(plan, HERO_KEY)
    filtered_ids = [item["pack_version_id"] for item in hero_role["filtered"]]
    assert incomplete["version_id"] in filtered_ids
    assert incomplete["version_id"] not in [
        item["pack_version_id"] for item in hero_role["candidates"]
    ]
    resp = _confirm(
        client,
        series,
        HERO_KEY,
        incomplete,
        _trace_for(plan, HERO_KEY, incomplete),
        key="k09",
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "incomplete_pack" in detail
    assert _mapping_rows() == []


def test_negative_10_foreign_project_role_refused(client: TestClient) -> None:
    series = _seed_series()
    other = _seed_series(name="Other-series")
    hero = _make_legacy_pack(client, "hero10")
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, hero)
    # a role of ANOTHER video in the same project
    sibling = client.post(
        CONFIRM,
        json={
            **_confirm_body(series, HERO_KEY, hero, trace, key="k10a"),
            "object_role_id": series["roles"][EXTRA_KEY],
        },
    )
    assert sibling.status_code == 404, sibling.text
    # a role of ANOTHER project (foreign project entirely)
    foreign = client.post(
        CONFIRM,
        json={
            **_confirm_body(series, HERO_KEY, hero, trace, key="k10b"),
            "object_role_id": other["roles"][HERO_KEY],
        },
    )
    assert foreign.status_code == 404, foreign.text
    # an id that does not exist at all
    unknown = client.post(
        CONFIRM,
        json={
            **_confirm_body(series, HERO_KEY, hero, trace, key="k10c"),
            "object_role_id": str(uuid.uuid4()),
        },
    )
    assert unknown.status_code == 404, unknown.text
    assert _mapping_rows() == []


def test_negative_11_replacement_needs_version_guard(client: TestClient) -> None:
    series = _seed_series()
    hero_a = _make_legacy_pack(client, "hero11a")
    hero_b = _make_legacy_pack(client, "hero11b")
    plan = _suggest(client, series["video_a"])
    first = _confirm(
        client, series, HERO_KEY, hero_a, _trace_for(plan, HERO_KEY, hero_a), key="k11a"
    )
    assert first.status_code == 201, first.text
    revision = first.json()["mapping"]["revision"]
    assert revision == 1
    # replacement without a version guard -> 422, zero mutation
    unguarded = _confirm(
        client, series, HERO_KEY, hero_b, _trace_for(plan, HERO_KEY, hero_b), key="k11b"
    )
    assert unguarded.status_code == 422, unguarded.text
    assert "expected_revision" in unguarded.json()["detail"]
    # stale guard -> 409, zero mutation
    stale = _confirm(
        client,
        series,
        HERO_KEY,
        hero_b,
        _trace_for(plan, HERO_KEY, hero_b),
        key="k11c",
        expected_revision=999,
    )
    assert stale.status_code == 409, stale.text
    assert "stale revision" in stale.json()["detail"]
    rows = _mapping_rows()
    assert len(rows) == 1
    assert rows[0].pack_version_id == hero_a["version_id"]
    # correct guard -> 200 and the pin really moves
    guarded = _confirm(
        client,
        series,
        HERO_KEY,
        hero_b,
        _trace_for(plan, HERO_KEY, hero_b),
        key="k11d",
        expected_revision=revision,
    )
    assert guarded.status_code == 200, guarded.text
    data = guarded.json()
    assert data["mapping"]["pack_version_id"] == hero_b["version_id"]
    assert data["mapping"]["revision"] == revision + 1
    assert _mapping_rows()[0].pack_version_id == hero_b["version_id"]


def test_negative_12_idempotency_key_bound_to_another_payload(
    client: TestClient,
) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero12")
    book = _make_legacy_pack(client, "book12", character_type="prop")
    plan = _suggest(client, series["video_a"])
    first = _confirm(
        client, series, HERO_KEY, hero, _trace_for(plan, HERO_KEY, hero), key="k12"
    )
    assert first.status_code == 201, first.text
    clash = _confirm(
        client, series, BOOK_KEY, book, _trace_for(plan, BOOK_KEY, book), key="k12"
    )
    assert clash.status_code == 409, clash.text
    rows = _mapping_rows()
    assert len(rows) == 1
    assert rows[0].object_role_id == series["roles"][HERO_KEY]


def test_negative_15_capability_missing_pack_refused(client: TestClient) -> None:
    assert "source_video_motion_transfer" in ENGINE_CAPABILITY_PINS
    series = _seed_series()
    legacy = _make_legacy_pack(client, "hero15")
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(
        plan, HERO_KEY, legacy, required_capabilities=["source_video_motion_transfer"]
    )
    resp = _confirm(client, series, HERO_KEY, legacy, trace, key="k15")
    assert resp.status_code == 409, resp.text
    assert "missing_required_capability" in resp.json()["detail"]
    assert _mapping_rows() == []


def test_negative_16_unknown_trace_views_rejected(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero16")
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(
        plan, HERO_KEY, hero, required_views=["not_a_measured_view"]
    )
    resp = _confirm(client, series, HERO_KEY, hero, trace, key="k16")
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "required_views" in str(detail)
    assert _mapping_rows() == []


def test_negative_17_series_pin_trace_must_pin_its_snapshot(
    client: TestClient,
) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero17")
    trace = {
        "role_key": HERO_KEY,
        "selection_mode": "series_pin",
        "selected_pack_version_id": hero["version_id"],
    }
    resp = _confirm(client, series, HERO_KEY, hero, trace, key="k17")
    assert resp.status_code == 422, resp.text
    detail = str(resp.json()["detail"])
    assert "series_snapshot_id" in detail
    assert _mapping_rows() == []


def test_negative_19_stale_frozen_entry_refused(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "hero19")
    _freeze(series, [_entry(hero)])
    plan = _suggest(client, series["video_a"])
    trace = _trace_for(plan, HERO_KEY, hero)
    # the frozen pack stops being published AFTER the recommendation was shown
    with _session() as session:
        pack = session.get(CharacterPackVersion, hero["version_id"])
        pack.status = "draft"
        session.commit()
    plan = _suggest(client, series["video_a"])
    assert _role(plan, HERO_KEY)["series_pin"]["live_ok"] is False
    resp = _confirm(client, series, HERO_KEY, hero, trace, key="k19")
    assert resp.status_code == 409, resp.text
    assert "stale recommendation basis" in resp.json()["detail"]
    assert _mapping_rows() == []


def test_micro_20_view_vocabulary_is_the_frozen_ingest_set() -> None:
    """Guard: the trace view vocabulary is the measured ingest vocabulary."""
    assert sorted(REQUIRED_VIEW_VOCABULARY) == [
        "back",
        "front",
        "side",
        "sitting",
        "three_quarter",
        "walking",
    ]
