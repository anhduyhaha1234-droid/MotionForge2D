"""MF-END-05 — series cast snapshot ("series pin"): acceptance + negative controls.

Every row below is a CI fixture: deterministic bytes generated in-process, the
per-test isolated SQLite database from ``tests/conftest.py``, and the FastAPI
``TestClient`` — engineering evidence, never product-demo evidence.  No GPU,
no network, no ffmpeg, no real product media.

Row map (binary):

* micro repro: the new migration is the SOLE alembic head, revises the
  MF-END-02 revision ``f8b9c0d1e2f3`` and is its only child; the ORM tables
  and the migrated database carry the same CHECK/UNIQUE/index metadata, and
  the CHECKs are enforced by the database itself (raw invalid inserts fail).
* acceptance (through the REAL app call path — TestClient routes over the
  repository): two videos of one series (the project that is the production
  container for the series) share the same immutable pack versions after one
  freeze + two copies; a restart (brand-new engine on the same database file)
  reads byte-identical snapshots and pins; changing the library default
  version does not move old projects; a deliberate version change creates
  ``snapshot_index + 1`` while the old snapshot stays byte-identical; the
  reference-pack branch freezes its requirement-manifest sha256 + per-key
  asset references and is pinnable end-to-end; copy replay is idempotent
  through the EXISTING ``create_mapping`` idempotency key.
* negative controls: unpublished / incomplete packs refused at freeze (zero
  rows); foreign-workspace, foreign-series and foreign-video refusals;
  unknown role_key, missing (partial) resolution set and duplicate role_key
  refused with zero mutation; a tampered frozen manifest and tampered frozen
  asset references refused at apply with zero mappings written; a tampered
  snapshot entry (digest mismatch) refused on READ and on apply; downgrade
  with snapshot rows refused with zero mutation, while an empty database
  round-trips upgrade / downgrade cleanly; freeze/apply schema strictness.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path, create_session_factory
from app.persistence.characters import CharacterRepository
from app.persistence.models import (
    CORE_POSE_SLOTS,
    PACK_CONTRACT_VERSION_LEGACY,
    PACK_CONTRACT_VERSION_REFERENCE,
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    ObjectRole,
    Project,
    SeriesCastSnapshot,
    SeriesCastSnapshotEntry,
    VideoItem,
)
from app.persistence.project_cast import (
    ProjectCastRepository,
    SeriesCastRepository,
)

FRONT = "front@character"
SIDE = "side@character"
BACK = "back@character"


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
    mode: str = "RGBA",
    alpha: int = 200,
    gray: int = 120,
) -> bytes:
    """Deterministic PNG: RGBA with real transparency, RGB, or mode-L mask."""
    if mode == "RGBA":
        img = Image.new("RGBA", (width, height), (gray, 60, 200, alpha))
    elif mode == "RGB":
        img = Image.new("RGB", (width, height), (gray, 60, 200))
    elif mode == "L":
        img = Image.new("L", (width, height), gray)
    else:  # pragma: no cover - guard
        raise ValueError(mode)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_managed(rel: str, data: bytes) -> Path:
    target = _managed_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _ensure_workspace(session, workspace_id: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.persistence.models import Workspace

    session.execute(
        sqlite_insert(Workspace)
        .values(id=workspace_id, name=workspace_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


def _seed_series(
    *, workspace_id: str = DEFAULT_WORKSPACE_ID, name: str | None = None
) -> dict:
    """One series = one project with two videos; each video has HERO + BOOK."""
    with _session() as session:
        _ensure_workspace(session, workspace_id)
        project = Project(
            workspace_id=workspace_id,
            name=name or f"Series-{uuid.uuid4().hex[:6]}",
        )
        session.add(project)
        session.flush()
        videos: list[str] = []
        for index, title in enumerate(("Episode A", "Episode B")):
            video = VideoItem(project_id=project.id, title=title, position=index)
            session.add(video)
            session.flush()
            videos.append(video.id)
        roles: dict[str, str] = {}
        for suffix, video_id in zip(("A", "B"), videos):
            for slot, kind in (("HERO", "character"), ("BOOK", "prop")):
                role = ObjectRole(
                    workspace_id=workspace_id,
                    project_id=project.id,
                    video_item_id=video_id,
                    source_generation="1",
                    name=f"ROLE-{slot}-{suffix}",
                    kind=kind,
                    status="confirmed",
                )
                session.add(role)
                session.flush()
                roles[f"{slot}-{suffix}"] = role.id
        session.commit()
        return {
            "workspace_id": workspace_id,
            "project_id": project.id,
            "videos": videos,
            "roles": roles,
        }


def _seed_pack(
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    *,
    status: str = "published",
    slots: tuple[str, ...] = CORE_POSE_SLOTS,
    character_type: str = "character",
    contract: str = PACK_CONTRACT_VERSION_LEGACY,
    manifest: dict | None = None,
    style_code: str | None = None,
) -> dict:
    """ORM-seeded library rows for precondition-building (negatives)."""
    with _session() as session:
        _ensure_workspace(session, workspace_id)
        character = Character(
            workspace_id=workspace_id,
            name=f"Seeded {uuid.uuid4().hex[:6]}",
            code=f"seed_{uuid.uuid4().hex[:8]}",
            character_type=character_type,
        )
        session.add(character)
        session.flush()
        pack = CharacterPackVersion(
            character_id=character.id,
            workspace_id=workspace_id,
            version=1,
            status=status,
            pack_contract_version=contract,
        )
        if manifest is not None:
            text = json.dumps(manifest, sort_keys=True)
            pack.requirement_manifest_json = text
            pack.requirement_manifest_sha256 = hashlib.sha256(
                text.encode()
            ).hexdigest()
        session.add(pack)
        session.flush()
        for index, slot in enumerate(slots):
            art = Artifact(
                workspace_id=workspace_id,
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
                    workspace_id=workspace_id,
                    pose_slot=slot,
                    artifact_id=art.id,
                )
            )
        session.commit()
        return {"character_id": character.id, "version_id": pack.id}


def _create_character(
    client: TestClient, code: str, *, character_type: str = "character"
) -> dict:
    resp = client.post(
        "/api/v2/characters",
        json={"name": f"Series {code}", "code": code, "character_type": character_type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _attach_artifact(
    client: TestClient, ver_id: str, slot: str, *, data: bytes | None = None
) -> dict:
    from app.persistence.models import Artifact as _Artifact

    data = data if data is not None else _png_bytes(gray=170)
    rel = f"characters/mf_end_05/{ver_id}/{slot.replace('@', '_')}.png"
    _write_managed(rel, data)
    with _session() as session:
        art = _Artifact(
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


def _attach_six(client: TestClient, ver_id: str, *, alpha: int = 200, gray: int = 9) -> None:
    for index, slot in enumerate(CORE_POSE_SLOTS):
        _attach_artifact(client, ver_id, slot, data=_png_bytes(alpha=alpha, gray=gray + index))


def _publish(client: TestClient, ver_id: str, revision: int) -> dict:
    resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish", json={"revision": revision}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _upload(
    client: TestClient, version_id: str, data: bytes, *, key: str, filename: str = "artwork.png"
):
    return client.post(
        f"/api/v2/characters/versions/{version_id}/reference-artwork",
        data={"reference_key": key},
        files={"file": (filename, data, "image/png")},
    )


def _declare(ver_id: str, manifest: dict) -> str:
    with _session() as session:
        repo = CharacterRepository(session)
        repo.declare_reference_manifest(ver_id, DEFAULT_WORKSPACE_ID, manifest)
        session.commit()
    with _session() as session:
        row = session.get(CharacterPackVersion, ver_id)
        assert row is not None
        assert row.requirement_manifest_sha256 is not None
        return row.requirement_manifest_sha256


def _make_legacy_pack(client: TestClient, code: str, *, character_type: str = "character") -> dict:
    char = _create_character(client, code, character_type=character_type)
    ver = _create_version(client, char["id"])
    _attach_six(client, ver["id"])
    _publish(client, ver["id"], ver["revision"])
    return {
        "character_id": char["id"],
        "character_revision": char["revision"],
        "version_id": ver["id"],
    }


def _make_reference_pack(client: TestClient, code: str, keys: list[str]) -> dict:
    char = _create_character(client, code)
    ver = _create_version(client, char["id"])
    manifest = {
        "manifest_version": 1,
        "pack_contract": PACK_CONTRACT_VERSION_REFERENCE,
        "requirements": [{"key": key, "alpha": True} for key in keys],
    }
    declared = _declare(ver["id"], manifest)
    uploaded: dict[str, str] = {}
    for index, key in enumerate(keys):
        resp = _upload(client, ver["id"], _png_bytes(gray=20 + 60 * index), key=key)
        assert resp.status_code == 201, resp.text
        uploaded[key] = resp.json()["sha256"]
    _publish(client, ver["id"], ver["revision"])
    return {
        "character_id": char["id"],
        "character_revision": char["revision"],
        "version_id": ver["id"],
        "manifest_sha256": declared,
        "uploaded": uploaded,
    }


def _freeze_entries(hero: dict, book: dict, *, hero_style: str | None = None,
                    book_style: str | None = None) -> list[dict]:
    return [
        {
            "role_key": "ROLE-HERO",
            "character_id": hero["character_id"],
            "pack_version_id": hero["version_id"],
            "style_version": hero_style,
        },
        {
            "role_key": "ROLE-BOOK",
            "character_id": book["character_id"],
            "pack_version_id": book["version_id"],
            "style_version": book_style,
        },
    ]


def _freeze(client: TestClient, project_id: str, entries: list[dict]):
    return client.post(
        "/api/v2/project-cast/series-cast/snapshots",
        json={"project_id": project_id, "entries": entries},
    )


def _apply(client: TestClient, snapshot_id: str, video_item_id: str, resolutions: dict[str, str]):
    return client.post(
        f"/api/v2/project-cast/series-cast/snapshots/{snapshot_id}/apply",
        json={
            "video_item_id": video_item_id,
            "resolutions": [
                {"role_key": key, "object_role_id": value}
                for key, value in resolutions.items()
            ],
        },
    )


def _mappings(project_id: str) -> list[dict]:
    with _session() as session:
        rows, _total = ProjectCastRepository(session).list_mappings(
            DEFAULT_WORKSPACE_ID, project_id, limit=200
        )
    return [
        {
            "id": row.id,
            "object_role_id": row.object_role_id,
            "character_id": row.character_id,
            "pack_version_id": row.pack_version_id,
            "idempotency_key": row.idempotency_key,
        }
        for row in rows
    ]


def _snapshot_row_count(workspace_id: str = DEFAULT_WORKSPACE_ID) -> int:
    with _session() as session:
        return int(
            session.scalar(
                select(func.count(SeriesCastSnapshot.id)).where(
                    SeriesCastSnapshot.workspace_id == workspace_id
                )
            )
            or 0
        )


def _read_snapshot(snapshot_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    with _session() as session:
        return SeriesCastRepository(session).get_snapshot(snapshot_id, workspace_id)


def _freeze_two_videos(client: TestClient) -> tuple[dict, dict, dict]:
    """Common setup: series + 2 legacy packs + frozen snapshot applied to both."""
    series = _seed_series()
    hero = _make_legacy_pack(client, "sp-hero")
    book = _make_legacy_pack(client, "sp-book", character_type="prop")
    freeze = _freeze(client, series["project_id"], _freeze_entries(hero, book))
    assert freeze.status_code == 201, freeze.text
    snapshot = freeze.json()
    for suffix, video_id in zip(("A", "B"), series["videos"]):
        resp = _apply(
            client,
            snapshot["id"],
            video_id,
            {
                "ROLE-HERO": series["roles"][f"HERO-{suffix}"],
                "ROLE-BOOK": series["roles"][f"BOOK-{suffix}"],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created_count"] == 2
    return series, snapshot, {"hero": hero, "book": book}


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_repro_sole_head_and_single_child() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(cfg)

    assert script.get_heads() == ["e5f6a7b8c9d0"]
    revision = script.get_revision("e5f6a7b8c9d0")
    assert revision.down_revision == "f8b9c0d1e2f3"
    children = [
        rev.revision
        for rev in script.walk_revisions()
        if rev.down_revision == "f8b9c0d1e2f3"
    ]
    assert children == ["e5f6a7b8c9d0"]
    migration = root / "migrations" / "versions" / "e5f6a7b8c9d0_mf_series_cast.py"
    assert migration.is_file()


def test_micro_repro_tables_metadata_and_db_enforcement(client: TestClient) -> None:
    snap = SeriesCastSnapshot.__table__
    entry = SeriesCastSnapshotEntry.__table__
    assert {c.name for c in snap.constraints} >= {
        "uq_series_cast_snapshot_project_index",
        "ck_series_cast_snapshot_index_positive",
        "ck_series_cast_snapshot_entries_sha_len",
        "ck_series_cast_snapshot_revision_positive",
    }
    assert {i.name for i in snap.indexes} >= {
        "ix_series_cast_snapshot_workspace",
        "ix_series_cast_snapshot_project",
    }
    assert {c.name for c in entry.constraints} >= {
        "uq_series_cast_entry_snapshot_role",
        "ck_series_cast_entry_role_key_len",
        "ck_series_cast_entry_contract",
        "ck_series_cast_entry_manifest_branch",
        "ck_series_cast_entry_manifest_sha_len",
        "ck_series_cast_entry_style_len",
        "ck_series_cast_entry_refs_nonempty",
    }
    assert {i.name for i in entry.indexes} >= {
        "ix_series_cast_entry_snapshot",
        "ix_series_cast_entry_workspace",
        "ix_series_cast_entry_pack_version",
        "ix_series_cast_entry_character",
    }
    # foreign keys fail closed (RESTRICT) on both tables
    for table in (snap, entry):
        for column in table.columns:
            for fk in column.foreign_keys:
                assert fk.ondelete == "RESTRICT", (table.name, column.name)

    series = _seed_series()
    pack = _seed_pack()

    def probe(sql: str, params: dict) -> str:
        with _session() as session:
            try:
                session.connection().exec_driver_sql(sql, params)
                session.commit()
                return "ok"
            except IntegrityError:
                session.rollback()
                return "integrity_error"

    snap_insert = (
        "INSERT INTO series_cast_snapshot "
        "(id, workspace_id, project_id, snapshot_index, entries_sha256, revision, "
        " created_at, updated_at) "
        "VALUES (:id, :ws, :pj, :idx, :sha, 1, '2026-01-01', '2026-01-01')"
    )
    base = {"ws": series["workspace_id"], "pj": series["project_id"], "sha": "0" * 64}
    assert probe(snap_insert, {**base, "id": "bad-idx", "idx": 0}) == "integrity_error"
    assert probe(snap_insert, {**base, "id": "good-snap", "idx": 1}) == "ok"

    entry_insert = (
        "INSERT INTO series_cast_snapshot_entry "
        "(id, snapshot_id, workspace_id, role_key, character_id, pack_version_id, "
        " pack_contract_version, manifest_sha256, style_version, references_json, "
        " revision, created_at, updated_at) "
        "VALUES (:id, 'good-snap', :ws, :rk, :cid, :pid, :ctr, :man, NULL, '[]', 1, "
        "        '2026-01-01', '2026-01-01')"
    )
    entry_base = {
        "ws": series["workspace_id"],
        "cid": pack["character_id"],
        "pid": pack["version_id"],
    }
    # legacy branch must NOT carry a manifest; reference branch MUST carry one
    assert (
        probe(entry_insert, {**entry_base, "id": "e1", "rk": "R1",
                             "ctr": PACK_CONTRACT_VERSION_LEGACY, "man": "x" * 64})
        == "integrity_error"
    )
    assert (
        probe(entry_insert, {**entry_base, "id": "e2", "rk": "R2",
                             "ctr": PACK_CONTRACT_VERSION_REFERENCE, "man": None})
        == "integrity_error"
    )
    assert (
        probe(entry_insert, {**entry_base, "id": "e3", "rk": "", "ctr":
                             PACK_CONTRACT_VERSION_LEGACY, "man": None})
        == "integrity_error"
    )
    assert (
        probe(entry_insert, {**entry_base, "id": "e4", "rk": "R4",
                             "ctr": PACK_CONTRACT_VERSION_LEGACY, "man": None})
        == "ok"
    )
    # (snapshot_id, role_key) is unique
    assert (
        probe(entry_insert, {**entry_base, "id": "e5", "rk": "R4",
                             "ctr": PACK_CONTRACT_VERSION_LEGACY, "man": None})
        == "integrity_error"
    )


# ── acceptance: the real call path ────────────────────────────────────────────


def test_acceptance_two_videos_share_immutable_versions(client: TestClient) -> None:
    series, snapshot, packs = _freeze_two_videos(client)
    hero, book = packs["hero"], packs["book"]

    assert snapshot["snapshot_index"] == 1
    assert snapshot["project_id"] == series["project_id"]
    by_key = {entry["role_key"]: entry for entry in snapshot["entries"]}
    assert set(by_key) == {"ROLE-HERO", "ROLE-BOOK"}
    assert by_key["ROLE-HERO"]["character_id"] == hero["character_id"]
    assert by_key["ROLE-HERO"]["pack_version_id"] == hero["version_id"]
    assert by_key["ROLE-HERO"]["pack_contract_version"] == PACK_CONTRACT_VERSION_LEGACY
    assert by_key["ROLE-HERO"]["manifest_sha256"] is None
    assert by_key["ROLE-BOOK"]["pack_version_id"] == book["version_id"]
    for entry in snapshot["entries"]:
        assert len(entry["references"]) >= 1
        assert all(ref["sha256"] for ref in entry["references"])

    rows = _mappings(series["project_id"])
    assert len(rows) == 4
    pinned = {row["object_role_id"]: row for row in rows}
    for index, suffix in enumerate(("A", "B")):
        hero_row = pinned[series["roles"][f"HERO-{suffix}"]]
        book_row = pinned[series["roles"][f"BOOK-{suffix}"]]
        assert hero_row["pack_version_id"] == hero["version_id"]
        assert book_row["pack_version_id"] == book["version_id"]
        # the replay key is scoped to (snapshot, target video, role): copying
        # the same snapshot to the next video is NOT a replay of the first
        assert hero_row["idempotency_key"] == (
            f"series-snapshot:{snapshot['id']}:{series['videos'][index]}:ROLE-HERO"
        )
    # both videos point at the SAME immutable version rows
    assert {
        pinned[series["roles"][f"HERO-{suffix}"]]["pack_version_id"] for suffix in ("A", "B")
    } == {hero["version_id"]}
    # the appended digest verifies on read (repository recomputes it)
    assert _read_snapshot(snapshot["id"]).entries_sha256 == snapshot["entries_sha256"]


def test_acceptance_apply_replay_is_idempotent(client: TestClient) -> None:
    series, snapshot, _packs = _freeze_two_videos(client)
    before = _mappings(series["project_id"])
    replay = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-A"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
        },
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["created_count"] == 0
    assert body["replayed_count"] == 2
    assert {entry["mapping_id"] for entry in body["applied"]} <= {
        row["id"] for row in before
    }
    assert _mappings(series["project_id"]) == before


def test_acceptance_reference_pack_freezes_manifest_hash_and_applies(
    client: TestClient,
) -> None:
    series = _seed_series()
    ref = _make_reference_pack(client, "sp-ref", [FRONT, SIDE, BACK])
    freeze = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": ref["character_id"],
                "pack_version_id": ref["version_id"],
                "style_version": "style-ref-v1",
            }
        ],
    )
    assert freeze.status_code == 201, freeze.text
    snapshot = freeze.json()
    entry = snapshot["entries"][0]
    assert entry["pack_contract_version"] == PACK_CONTRACT_VERSION_REFERENCE
    assert entry["manifest_sha256"] == ref["manifest_sha256"]
    assert entry["style_version"] == "style-ref-v1"
    assert {ref_["pose_slot"] for ref_ in entry["references"]} == {FRONT, SIDE, BACK}
    for ref_ in entry["references"]:
        assert ref_["sha256"] == ref["uploaded"][ref_["pose_slot"]]

    applied = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {"ROLE-HERO": series["roles"]["HERO-A"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created_count"] == 1
    rows = _mappings(series["project_id"])
    assert len(rows) == 1
    assert rows[0]["pack_version_id"] == ref["version_id"]


def test_acceptance_restart_reads_identical_state(
    client: TestClient, _patch_project_root: Path
) -> None:
    series, snapshot, packs = _freeze_two_videos(client)
    before_rows = sorted(
        (row["object_role_id"], row["pack_version_id"]) for row in _mappings(series["project_id"])
    )
    before = _read_snapshot(snapshot["id"])

    # genuine restart: brand-new engine + factory on the SAME database file
    db_path = _patch_project_root / "data" / "test.db"
    engine = create_engine_for_path(db_path)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            after = SeriesCastRepository(session).get_snapshot(
                snapshot["id"], DEFAULT_WORKSPACE_ID
            )
            rows, total = ProjectCastRepository(session).list_mappings(
                DEFAULT_WORKSPACE_ID, series["project_id"], limit=200
            )
    finally:
        engine.dispose()

    assert total == 4
    assert after.id == before.id
    assert after.snapshot_index == before.snapshot_index == 1
    assert after.entries_sha256 == before.entries_sha256
    assert [entry.role_key for entry in after.entries] == ["ROLE-BOOK", "ROLE-HERO"]
    assert [
        (entry.role_key, entry.pack_version_id, entry.manifest_sha256)
        for entry in after.entries
    ] == [
        (entry.role_key, entry.pack_version_id, entry.manifest_sha256)
        for entry in before.entries
    ]
    assert sorted((row.object_role_id, row.pack_version_id) for row in rows) == before_rows


def test_acceptance_library_default_change_does_not_move_old_projects(
    client: TestClient,
) -> None:
    series, snapshot, packs = _freeze_two_videos(client)
    hero = packs["hero"]
    # publish a NEW version of the hero character and make it the library default
    v2 = _create_version(client, hero["character_id"])
    _attach_six(client, v2["id"], gray=100)
    _publish(client, v2["id"], v2["revision"])
    current = client.get(f"/api/v2/characters/{hero['character_id']}")
    assert current.status_code == 200, current.text
    resp = client.post(
        f"/api/v2/characters/{hero['character_id']}/default-version",
        json={"version_id": v2["id"], "revision": current.json()["revision"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_version_id"] == v2["id"]

    # every old pin still points at the frozen v1 row — nothing drifted
    rows = _mappings(series["project_id"])
    hero_rows = [
        row for row in rows
        if row["object_role_id"] in (series["roles"]["HERO-A"], series["roles"]["HERO-B"])
    ]
    assert {row["pack_version_id"] for row in hero_rows} == {hero["version_id"]}
    after = _read_snapshot(snapshot["id"])
    assert after.entries_sha256 == snapshot["entries_sha256"]
    assert {entry.pack_version_id for entry in after.entries} == {
        hero["version_id"],
        packs["book"]["version_id"],
    }
    # replay of the copy still resolves the FROZEN version (not the default)
    replay = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-A"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
        },
    )
    assert replay.status_code == 200, replay.text
    by_role = {entry["role_key"]: entry for entry in replay.json()["applied"]}
    assert by_role["ROLE-HERO"]["pack_version_id"] == hero["version_id"]


def test_acceptance_version_change_creates_new_snapshot(client: TestClient) -> None:
    series = _seed_series()
    hero_v1 = _make_legacy_pack(client, "sp-v1")
    book = _make_legacy_pack(client, "sp-v1b", character_type="prop")
    first = _freeze(client, series["project_id"], _freeze_entries(hero_v1, book))
    assert first.status_code == 201, first.text

    # identical freeze is an idempotent replay: same snapshot, no new index
    same = _freeze(client, series["project_id"], _freeze_entries(hero_v1, book))
    assert same.status_code == 200, same.text
    assert same.json()["id"] == first.json()["id"]
    assert same.json()["snapshot_index"] == 1
    assert _snapshot_row_count() == 1

    # deliberate version change -> snapshot_index + 1; the old row never moves
    v2 = _create_version(client, hero_v1["character_id"])
    _attach_six(client, v2["id"], gray=140)
    _publish(client, v2["id"], v2["revision"])
    hero_v2 = {"character_id": hero_v1["character_id"], "version_id": v2["id"]}
    second = _freeze(client, series["project_id"], _freeze_entries(hero_v2, book))
    assert second.status_code == 201, second.text
    assert second.json()["snapshot_index"] == 2
    assert second.json()["id"] != first.json()["id"]
    assert _snapshot_row_count() == 2

    old = _read_snapshot(first.json()["id"])
    assert old.snapshot_index == 1
    assert old.entries_sha256 == first.json()["entries_sha256"]
    old_hero = {entry.role_key: entry for entry in old.entries}["ROLE-HERO"]
    assert old_hero.pack_version_id == hero_v1["version_id"]

    # latest listing shows both, newest first
    resp = client.get(
        "/api/v2/project-cast/series-cast/snapshots",
        params={"project_id": series["project_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert [item["snapshot_index"] for item in body["snapshots"]] == [2, 1]

    # pins applied later follow whichever snapshot the caller asks for
    copy = _apply(
        client,
        second.json()["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-A"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
        },
    )
    assert copy.status_code == 200, copy.text
    rows = _mappings(series["project_id"])
    hero_row = next(
        row for row in rows if row["object_role_id"] == series["roles"]["HERO-A"]
    )
    assert hero_row["pack_version_id"] == v2["id"]


# ── negative controls ─────────────────────────────────────────────────────────


def test_negative_freeze_refuses_unpublished_and_incomplete_packs(
    client: TestClient,
) -> None:
    series = _seed_series()
    draft = _seed_pack(status="draft")  # not published
    incomplete = _seed_pack(status="published", slots=("front",))  # hand-edited
    for pack in (draft, incomplete):
        resp = _freeze(
            client,
            series["project_id"],
            [
                {
                    "role_key": "ROLE-HERO",
                    "character_id": pack["character_id"],
                    "pack_version_id": pack["version_id"],
                }
            ],
        )
        assert resp.status_code == 409, resp.text
    assert _snapshot_row_count() == 0

    unpublished_body = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": draft["character_id"],
                "pack_version_id": draft["version_id"],
            }
        ],
    ).json()["detail"]
    assert "unpublished_pack" in unpublished_body
    incomplete_body = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": incomplete["character_id"],
                "pack_version_id": incomplete["version_id"],
            }
        ],
    ).json()["detail"]
    assert "incomplete_pack" in incomplete_body
    assert "three_quarter" in incomplete_body and "front" not in incomplete_body


def test_negative_freeze_refuses_reference_pack_missing_required_key(
    client: TestClient,
) -> None:
    series = _seed_series()
    manifest = {
        "manifest_version": 1,
        "pack_contract": PACK_CONTRACT_VERSION_REFERENCE,
        "requirements": [
            {"key": FRONT, "alpha": True},
            {"key": SIDE, "alpha": True},
        ],
    }
    pack = _seed_pack(
        status="published",
        slots=(FRONT,),
        contract=PACK_CONTRACT_VERSION_REFERENCE,
        manifest=manifest,
    )
    resp = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": pack["character_id"],
                "pack_version_id": pack["version_id"],
            }
        ],
    )
    assert resp.status_code == 409, resp.text
    assert SIDE in resp.json()["detail"]
    assert _snapshot_row_count() == 0


def test_negative_foreign_workspace_ownership_refusals(client: TestClient) -> None:
    series = _seed_series()
    foreign_ws = f"ws-{uuid.uuid4().hex[:12]}"
    foreign_pack = _seed_pack(workspace_id=foreign_ws)
    foreign_series = _seed_series(workspace_id=foreign_ws)

    # project from another workspace
    resp = _freeze(
        client,
        foreign_series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": foreign_pack["character_id"],
                "pack_version_id": foreign_pack["version_id"],
            }
        ],
    )
    assert resp.status_code == 404, resp.text
    # character/pack from another workspace on a local project
    resp = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": foreign_pack["character_id"],
                "pack_version_id": foreign_pack["version_id"],
            }
        ],
    )
    assert resp.status_code == 404, resp.text
    assert _snapshot_row_count() == 0

    # snapshot ids never leak across workspaces (repository-level authority)
    hero = _make_legacy_pack(client, "sp-ws")
    book = _make_legacy_pack(client, "sp-ws-b", character_type="prop")
    frozen = _freeze(client, series["project_id"], _freeze_entries(hero, book))
    assert frozen.status_code == 201, frozen.text
    snapshot_id = frozen.json()["id"]
    with _session() as session:
        repo = SeriesCastRepository(session)
        with pytest.raises(Exception) as excinfo:
            repo.get_snapshot(snapshot_id, foreign_ws)
    assert "not found" in str(excinfo.value)
    resp = client.get(f"/api/v2/project-cast/series-cast/snapshots/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_negative_foreign_series_and_video_refusals(client: TestClient) -> None:
    series, snapshot, _packs = _freeze_two_videos(client)
    other = _seed_series(name="Other-Series")
    # apply a snapshot of series 1 onto a video of another series -> refused
    resp = _apply(
        client,
        snapshot["id"],
        other["videos"][0],
        {
            "ROLE-HERO": other["roles"]["HERO-A"],
            "ROLE-BOOK": other["roles"]["BOOK-A"],
        },
    )
    assert resp.status_code == 404, resp.text
    assert "same series" in resp.json()["detail"]
    # role of ANOTHER video in the SAME project is not the target video
    resp = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-B"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
        },
    )
    assert resp.status_code == 404, resp.text
    assert "target video" in resp.json()["detail"]
    assert len(_mappings(other["project_id"])) == 0


def test_negative_apply_requires_whole_set_and_known_keys(client: TestClient) -> None:
    series, snapshot, _packs = _freeze_two_videos(client)
    before = len(_mappings(series["project_id"]))

    unknown = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-A"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
            "ROLE-NOPE": series["roles"]["HERO-A"],
        },
    )
    assert unknown.status_code == 409, unknown.text
    assert "ROLE-NOPE" in unknown.json()["detail"]

    partial = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {"ROLE-HERO": series["roles"]["HERO-A"]},
    )
    assert partial.status_code == 409, partial.text
    assert "ROLE-BOOK" in partial.json()["detail"]

    duplicate = client.post(
        f"/api/v2/project-cast/series-cast/snapshots/{snapshot['id']}/apply",
        json={
            "video_item_id": series["videos"][0],
            "resolutions": [
                {"role_key": "ROLE-HERO", "object_role_id": series["roles"]["HERO-A"]},
                {"role_key": "ROLE-HERO", "object_role_id": series["roles"]["HERO-A"]},
            ],
        },
    )
    assert duplicate.status_code == 422, duplicate.text
    assert "duplicate role_key" in duplicate.json()["detail"]
    empty = client.post(
        f"/api/v2/project-cast/series-cast/snapshots/{snapshot['id']}/apply",
        json={"video_item_id": series["videos"][0], "resolutions": []},
    )
    assert empty.status_code == 422
    assert len(_mappings(series["project_id"])) == before


def test_negative_stale_frozen_manifest_refused_zero_mutation(
    client: TestClient,
) -> None:
    series = _seed_series()
    ref = _make_reference_pack(client, "sp-stale", [FRONT])
    frozen = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": ref["character_id"],
                "pack_version_id": ref["version_id"],
            }
        ],
    )
    assert frozen.status_code == 201, frozen.text
    snapshot_id = frozen.json()["id"]
    before = len(_mappings(series["project_id"]))

    # library hand-edit AFTER the freeze: the pack's manifest is rewritten
    tampered = json.dumps(
        {
            "manifest_version": 1,
            "pack_contract": PACK_CONTRACT_VERSION_REFERENCE,
            "requirements": [{"key": FRONT, "alpha": True}, {"key": SIDE, "alpha": True}],
        },
        sort_keys=True,
    )
    with _session() as session:
        row = session.get(CharacterPackVersion, ref["version_id"])
        assert row is not None
        row.requirement_manifest_json = tampered
        row.requirement_manifest_sha256 = hashlib.sha256(tampered.encode()).hexdigest()
        session.commit()

    resp = _apply(
        client,
        snapshot_id,
        series["videos"][0],
        {"ROLE-HERO": series["roles"]["HERO-A"]},
    )
    assert resp.status_code == 409, resp.text
    assert "frozen manifest sha256" in resp.json()["detail"]
    assert len(_mappings(series["project_id"])) == before
    # the snapshot itself is untouched and still readable
    assert _read_snapshot(snapshot_id).entries_sha256 == frozen.json()["entries_sha256"]


def test_negative_stale_frozen_asset_references_refused(client: TestClient) -> None:
    series, snapshot, packs = _freeze_two_videos(client)
    before = len(_mappings(series["project_id"]))
    # hand-edit the artifact behind one frozen reference (same row, new bytes)
    with _session() as session:
        entry = session.scalar(
            select(SeriesCastSnapshotEntry)
            .where(SeriesCastSnapshotEntry.snapshot_id == snapshot["id"])
            .order_by(SeriesCastSnapshotEntry.role_key)
        )
        assert entry is not None
        import json as _json

        first_ref = _json.loads(entry.references_json)[0]
        artifact = session.get(Artifact, first_ref["artifact_id"])
        assert artifact is not None
        artifact.sha256 = "f" * 64
        session.commit()

    resp = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-A"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
        },
    )
    assert resp.status_code == 409, resp.text
    assert "asset references" in resp.json()["detail"]
    assert len(_mappings(series["project_id"])) == before


def test_negative_tampered_snapshot_digest_fails_closed(client: TestClient) -> None:
    series, snapshot, _packs = _freeze_two_videos(client)
    before = len(_mappings(series["project_id"]))
    # raw row tamper: change an entry WITHOUT updating the header digest
    with _session() as session:
        entry = session.scalar(
            select(SeriesCastSnapshotEntry)
            .where(SeriesCastSnapshotEntry.snapshot_id == snapshot["id"])
            .order_by(SeriesCastSnapshotEntry.role_key)
        )
        assert entry is not None
        entry.style_version = "tampered"
        session.commit()

    resp = client.get(
        f"/api/v2/project-cast/series-cast/snapshots/{snapshot['id']}"
    )
    assert resp.status_code == 409, resp.text
    assert "corrupt" in resp.json()["detail"]
    resp = _apply(
        client,
        snapshot["id"],
        series["videos"][0],
        {
            "ROLE-HERO": series["roles"]["HERO-A"],
            "ROLE-BOOK": series["roles"]["BOOK-A"],
        },
    )
    assert resp.status_code == 409, resp.text
    assert len(_mappings(series["project_id"])) == before


def test_negative_schema_strictness(client: TestClient) -> None:
    series = _seed_series()
    hero = _make_legacy_pack(client, "sp-schema")
    # unknown field -> 422 (strict, extra=forbid)
    resp = client.post(
        "/api/v2/project-cast/series-cast/snapshots",
        json={
            "project_id": series["project_id"],
            "entries": [
                {
                    "role_key": "ROLE-HERO",
                    "character_id": hero["character_id"],
                    "pack_version_id": hero["version_id"],
                    "pose_slot": "front",
                }
            ],
        },
    )
    assert resp.status_code == 422
    # empty entries -> 422
    resp = _freeze(client, series["project_id"], [])
    assert resp.status_code == 422
    # invalid role_key grammar -> 422
    resp = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "role hero!",
                "character_id": hero["character_id"],
                "pack_version_id": hero["version_id"],
            }
        ],
    )
    assert resp.status_code == 422
    # duplicate role_key in one request -> 422 (repository ValueError)
    resp = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": hero["character_id"],
                "pack_version_id": hero["version_id"],
            },
            {
                "role_key": "ROLE-HERO",
                "character_id": hero["character_id"],
                "pack_version_id": hero["version_id"],
            },
        ],
    )
    assert resp.status_code == 422
    assert _snapshot_row_count() == 0


# ── migration downgrade / upgrade ─────────────────────────────────────────────


def _alembic_config(db_path: Path):
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _table_names(db_path: Path) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def test_negative_downgrade_with_snapshot_rows_refused_zero_mutation(
    tmp_path: Path,
) -> None:
    from alembic import command

    db_path = tmp_path / "mig" / "mf_end_05.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")
    assert {"series_cast_snapshot", "series_cast_snapshot_entry"} <= _table_names(db_path)

    # seed one snapshot row directly on the migrated database
    engine = create_engine_for_path(db_path)
    factory = create_session_factory(engine)
    with factory() as session:
        session.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO workspace (id, name, revision, created_at, updated_at) "
                "VALUES ('ws-mig', 'ws-mig', 1, '2026-01-01', '2026-01-01')"
            )
        )
        session.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO project (id, workspace_id, name, description, status, "
                "revision, created_at, updated_at) "
                "VALUES ('pj-mig', 'ws-mig', 'P', '', 'draft', 1, '2026-01-01', '2026-01-01')"
            )
        )
        session.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO series_cast_snapshot (id, workspace_id, project_id, "
                "snapshot_index, entries_sha256, revision, created_at, updated_at) "
                "VALUES ('snap-mig', 'ws-mig', 'pj-mig', 1, :sha, 1, '2026-01-01', '2026-01-01')"
            ),
            {"sha": "0" * 64},
        )
        session.commit()
    engine.dispose()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        ddl_before = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name IN "
            "('series_cast_snapshot','series_cast_snapshot_entry') ORDER BY name"
        ).fetchall()
        version_before = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    finally:
        conn.close()

    with pytest.raises(Exception) as excinfo:
        command.downgrade(cfg, "f8b9c0d1e2f3")
    assert "refusing to downgrade" in str(excinfo.value)
    # zero mutation: DDL, alembic version and the row are all untouched
    conn = sqlite3.connect(db_path)
    try:
        ddl_after = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name IN "
            "('series_cast_snapshot','series_cast_snapshot_entry') ORDER BY name"
        ).fetchall()
        version_after = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        count = conn.execute("SELECT COUNT(*) FROM series_cast_snapshot").fetchone()[0]
    finally:
        conn.close()
    assert ddl_after == ddl_before
    assert version_after == version_before == [("e5f6a7b8c9d0",)]
    assert count == 1


def test_micro_repro_empty_database_round_trips(tmp_path: Path) -> None:
    from alembic import command

    db_path = tmp_path / "mig2" / "mf_end_05_round.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")
    assert {"series_cast_snapshot", "series_cast_snapshot_entry"} <= _table_names(db_path)
    command.downgrade(cfg, "f8b9c0d1e2f3")
    names = _table_names(db_path)
    assert "series_cast_snapshot" not in names
    assert "series_cast_snapshot_entry" not in names
    command.upgrade(cfg, "head")
    assert {"series_cast_snapshot", "series_cast_snapshot_entry"} <= _table_names(db_path)


# ── protected legacy regression (cast authority stays branch-dispatched) ──────


def test_regression_legacy_pack_without_core_slots_still_refused(
    client: TestClient,
) -> None:
    """The legacy six-slot demand is byte-for-byte preserved for legacy rows."""
    series = _seed_series()
    legacy = _seed_pack(status="published", slots=("front",))
    hero = _make_legacy_pack(client, "sp-legacy-ok")
    book = _make_legacy_pack(client, "sp-legacy-b", character_type="prop")
    resp = _freeze(client, series["project_id"], _freeze_entries(hero, book))
    assert resp.status_code == 201
    resp = _freeze(
        client,
        series["project_id"],
        [
            {
                "role_key": "ROLE-HERO",
                "character_id": legacy["character_id"],
                "pack_version_id": legacy["version_id"],
            }
        ],
    )
    assert resp.status_code == 409
    assert "missing_required_pose" not in resp.json()["detail"]  # freeze wording
    assert "three_quarter" in resp.json()["detail"]
