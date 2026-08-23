"""S08-A01 focused tests — Source-Locked 2D Role Taxonomy Bridge.

Covers the canonical seven-kind ObjectRole taxonomy end-to-end on isolated
roots (the conftest ``client`` fixture only — never a bare TestClient):

- schema/repository/API: all seven kinds accepted on create/update, unknown
  kind -> stable 422 (never silently coerced to ``other``), kind filter on
  list (unknown filter -> 422), and the canonical kinds endpoint exposing
  the removal-only policy for ``source_overlay``;
- legacy provenance: historical unknown kinds still map to ``other`` but
  record the raw source value + normalization reason;
- extraction: the deterministic QA adapter can emit the new role/layer kinds
  (background, foreground, graphic, source_overlay);
- grouping: different-kind roles are never paired and removal-only
  (``source_overlay``) never pairs with anything; character/prop grouping
  must not regress;
- correction: merge refuses removal-only participants; the taxonomy anchor
  (models.REMOVAL_ONLY_KINDS == grouping default) holds.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    OBJECT_KINDS,
    REMOVAL_ONLY_KINDS,
    SOURCE_OVERLAY_KIND,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_grouping import (
    ObjectGroupingRepository,
    OperationConflictError,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
    RoleConflictError,
)
from app.services.object_grouping import (
    OccurrenceEvidence,
    RoleEvidence,
    generate_pair_suggestions,
)

API = "/api/v2/object-intelligence"
ALL_SEVEN = list(OBJECT_KINDS)


# ── local test helpers (isolated, no cross-test coupling) ────────────────


def _session() -> Session:
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _seed_ownership(session: Session) -> tuple[str, str, str, str]:
    workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
    project = Project(workspace_id=workspace.id, name="A01")
    video = VideoItem(project=project, title="V", position=0)
    scene = Scene(
        video_item=video,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    other_scene = Scene(
        video_item=video,
        position=1,
        start_frame=11,
        end_frame=20,
        start_time_ms=1001,
        end_time_ms=2000,
        status="pending",
    )
    session.add_all([workspace, project, video, scene, other_scene])
    session.commit()
    return project.id, video.id, scene.id, other_scene.id


def _api_role(client: TestClient, ids: tuple[str, str, str, str], kind: str, name: str):
    project_id, video_id, _, _ = ids
    return client.post(
        f"{API}/roles",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
            "source_generation": "1",
            "name": name,
            "kind": kind,
        },
    )


def _evidence(
    role_id: str,
    name: str,
    occurrences: list[tuple[int, int, int, int, int, int]],
    *,
    kind: str = "character",
) -> RoleEvidence:
    return RoleEvidence(
        role_id=role_id,
        name=name,
        kind=kind,
        source_generation="1",
        occurrences=tuple(
            OccurrenceEvidence(
                scene_id=f"scene-{frame}",
                frame_index=frame,
                time_ms=time_ms,
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
            )
            for frame, time_ms, x, y, w, h in occurrences
        ),
    )


# ── taxonomy anchors ──────────────────────────────────────────────────────


# ── AC2: backward-compatible migration round-trip ──────────────────────────


def test_migration_widens_kind_preserving_rows(tmp_path: Any) -> None:
    """Existing character/prop/other rows survive the new migration's
    upgrade -> downgrade -> upgrade exactly (AC2: byte-identical rows)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.persistence import create_engine_for_path

    project_root = Path(__file__).resolve().parent.parent
    db = tmp_path / "a01-mig.db"
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")

    # 1. Upgrade to the PRE-A01 head (f6a7b8c9d0e1), seed the legacy 3 kinds.
    command.upgrade(cfg, "f6a7b8c9d0e1")
    engine = create_engine_for_path(db)
    from sqlalchemy.orm import Session

    def seed() -> None:
        with Session(engine) as session:
            from app.persistence import DEFAULT_WORKSPACE_ID as WS

            session.execute(
                text(
                    "INSERT INTO workspace(id,name) VALUES (:w, :w) "
                    "ON CONFLICT(id) DO NOTHING"
                ),
                {"w": WS},
            )
            session.execute(
                text(
                    "INSERT INTO project(id,workspace_id,name) VALUES "
                    "('p1',:w,'p') ON CONFLICT(id) DO NOTHING"
                ),
                {"w": WS},
            )
            session.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position) "
                    "VALUES ('v1','p1','v',0) ON CONFLICT(id) DO NOTHING"
                )
            )
            for idx, kind in enumerate(("character", "prop", "other")):
                session.execute(
                    text(
                        "INSERT OR REPLACE INTO object_role("
                        "id,workspace_id,project_id,video_item_id,"
                        "source_generation,name,kind) VALUES "
                        "(:id,:w,'p1','v1','1',:n,:k)"
                    ),
                    {"id": f"r{idx}", "w": WS, "n": f"Legacy-{kind}", "k": kind},
                )
            session.commit()

    def snapshot() -> list[tuple[str, str, str]]:
        with engine.connect() as conn:
            return sorted(
                (str(a), str(b), str(c))
                for (a, b, c) in conn.execute(
                    text(
                        "SELECT id, name, kind FROM object_role ORDER BY id"
                    )
                ).all()
            )

    seed()
    baseline = snapshot()
    assert len(baseline) == 3

    # 2. Upgrade A01 -> head: rows byte-identical, constraint widened.
    command.upgrade(cfg, "head")
    assert snapshot() == baseline
    with engine.connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        assert version == "b2c3d4e5f6a7b"  # S08-A02 head (post-A01)
        ddl = "".join(
            conn.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE type='table' "
                    "AND name='object_role'"
                )
            ).scalars()
        )
        assert "'source_overlay'" in ddl

    # 3. Downgrade A01 -> f6: rows still present, constraint restored to 3.
    command.downgrade(cfg, "f6a7b8c9d0e1")
    assert snapshot() == baseline
    with engine.connect() as conn:
        ddl = "".join(
            conn.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE type='table' "
                    "AND name='object_role'"
                )
            ).scalars()
        )
        assert "'source_overlay'" not in ddl

    # 4. Re-upgrade: rows still byte-identical.
    command.upgrade(cfg, "head")
    assert snapshot() == baseline


def test_canonical_taxonomy_constants() -> None:
    assert OBJECT_KINDS == (
        "character",
        "prop",
        "background",
        "foreground",
        "graphic",
        "source_overlay",
        "other",
    )
    assert SOURCE_OVERLAY_KIND == "source_overlay"
    assert frozenset({SOURCE_OVERLAY_KIND}) == REMOVAL_ONLY_KINDS
    # F3 single authority: the ORM CHECK literal and the validation regex are
    # DERIVED from OBJECT_KINDS (no duplicated hardcoded literal anywhere) and
    # must contain exactly the seven kinds in declaration order.
    from app.persistence.models import (
        OBJECT_KIND_CHECK_SQL,
        OBJECT_KIND_PATTERN,
    )

    assert OBJECT_KIND_CHECK_SQL == (
        "kind IN ('character','prop','background','foreground','graphic',"
        "'source_overlay','other')"
    )
    assert OBJECT_KIND_PATTERN == (
        "^(character|prop|background|foreground|graphic|source_overlay|other)$"
    )
    # The derived CHECK must match the migration's frozen literal exactly so
    # the writable_schema needle is found EXACTLY ONCE (F1).
    from migrations.versions.f7a8b9c0d1e2_object_role_7_kind_taxonomy import (
        _NEW_CHECK,
    )

    assert OBJECT_KIND_CHECK_SQL == _NEW_CHECK


# ── schema / repository / API: seven kinds + stable 422 ──────────────────


def test_api_create_all_seven_kinds(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    seen: dict[str, str] = {}
    for _idx, kind in enumerate(ALL_SEVEN):
        created = _api_role(client, ids, kind, f"Role-{kind}")
        assert created.status_code == 201, created.text
        assert created.json()["kind"] == kind
        seen[kind] = created.json()["id"]
    assert len(seen) == 7


def test_api_list_kind_filter(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    project_id, video_id, _, _ = ids
    for _idx, kind in enumerate(ALL_SEVEN):
        assert _api_role(client, ids, kind, f"F-{kind}").status_code == 201
    for kind in ALL_SEVEN:
        listed = client.get(
            f"{API}/roles?video_item_id={video_id}&kind={kind}"
        )
        assert listed.status_code == 200, listed.text
        payload = listed.json()
        assert payload["total"] == 1
        assert all(r["kind"] == kind for r in payload["roles"])
    # filtered + pagination combine harmlessly
    listed = client.get(
        f"{API}/roles?video_item_id={video_id}&kind=background&limit=1&offset=0"
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_api_unknown_kind_stable_422(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    created = _api_role(client, ids, "bogus", "X")
    assert created.status_code == 422, created.text
    role = _api_role(client, ids, "character", "Y")
    assert role.status_code == 201
    role_id = role.json()["id"]
    updated = client.patch(
        f"{API}/roles/{role_id}", json={"revision": 1, "kind": "bogus"}
    )
    assert updated.status_code == 422, updated.text
    # No silent coercion: the created role is still a character.
    assert client.get(f"{API}/roles/{role_id}").json()["kind"] == "character"


def test_api_list_unknown_kind_filter_422(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    project_id, video_id, _, _ = ids
    _api_role(client, ids, "character", "C")
    resp = client.get(f"{API}/roles?video_item_id={video_id}&kind=not-a-kind")
    assert resp.status_code == 422, resp.text


def test_kinds_endpoint_exposes_removal_only_policy(client: TestClient) -> None:
    resp = client.get(f"{API}/kinds")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["source_overlay"] == SOURCE_OVERLAY_KIND
    kinds = payload["kinds"]
    assert [k["name"] for k in kinds] == list(OBJECT_KINDS)
    overlay = next(k for k in kinds if k["name"] == SOURCE_OVERLAY_KIND)
    assert overlay["removal_only"] is True
    for k in kinds:
        if k["name"] != SOURCE_OVERLAY_KIND:
            assert k["removal_only"] is False, k


def test_repository_rejects_unknown_kind(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    repo = ObjectIntelligenceRepository(_session())
    with pytest.raises(ValueError):
        repo.create_role(
            DEFAULT_WORKSPACE_ID,
            ids[0],
            ids[1],
            "1",
            "Bad",
            kind="bogus",
        )
    role, _ = repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "Ok")
    with pytest.raises(ValueError):
        repo.update_role(DEFAULT_WORKSPACE_ID, role.id, role.revision, kind="bogus")
    with pytest.raises(ValueError):
        repo.list_roles(DEFAULT_WORKSPACE_ID, kind="bogus")


def test_repository_stores_all_seven_kinds(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    session = _session()
    repo = ObjectIntelligenceRepository(session)
    for _idx, kind in enumerate(ALL_SEVEN):
        record, created = repo.create_role(
            DEFAULT_WORKSPACE_ID,
            ids[0],
            ids[1],
            "1",
            f"Repo-{kind}",
            kind=kind,
        )
        assert created and record.kind == kind
    session.commit()
    kinds = sorted(
        {str(k) for (k,) in session.execute(select(ObjectRole.kind)).all()}
    )
    assert kinds == sorted(ALL_SEVEN)


# ── legacy mapping provenance ─────────────────────────────────────────────


def test_legacy_mapping_records_normalization_provenance(client: TestClient) -> None:
    session = _session()
    repo = ObjectIntelligenceRepository(session)
    data: dict[str, Any] = {
        "objects": [
            {
                "object_id": "o1",
                "name": "Unknown",
                "kind": "weird",
                "scene_id": 2,
                "selection": {
                    "frame_index": 3,
                    "x": 1,
                    "y": 2,
                    "width": 3,
                    "height": 4,
                },
            },
            {
                "object_id": "o2",
                "name": "Graphic",
                "kind": "graphic",
                "scene_id": 1,
                "selection": {
                    "frame_index": 1,
                    "x": 0,
                    "y": 0,
                    "width": 10,
                    "height": 10,
                },
            },
        ]
    }
    mapping = repo.map_legacy_objects("p", data)
    by_id = {item.legacy_object_id: item for item in mapping.mapped_objects}
    unknown = by_id["o1"]
    assert unknown.legacy_kind == "other"
    assert unknown.source_kind == "weird"
    assert unknown.kind_normalization_reason == "unknown-kind-normalized-to-other"
    graphic = by_id["o2"]
    assert graphic.legacy_kind == "graphic"
    assert graphic.source_kind == "graphic"
    assert graphic.kind_normalization_reason is None


def test_legacy_mapping_api_exposes_provenance(
    client: TestClient, sample_project_data: dict
) -> None:
    project_id = "a01-legacy-map"
    root = deps._config.project_root / "projects" / project_id
    root.mkdir(parents=True)
    # "effect" is a VALID legacy ProjectData kind but NOT one of the seven
    # canonical ObjectRole kinds — it must pass project validation and still
    # arrive at the mapping as a normalized "other" WITH provenance recorded.
    sample_project_data["objects"] = [
        {
            "object_id": "o1",
            "name": "LegacyEffect",
            "kind": "effect",
            "scene_id": 0,
            "selection": {
                "mode": "bounding_box",
                "frame_index": 0,
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
            },
        }
    ]
    (root / "project.json").write_text(json.dumps(sample_project_data), encoding="utf-8")
    resp = client.get(f"{API}/legacy-mapping/{project_id}")
    assert resp.status_code == 200, resp.text
    item = resp.json()["mapped_objects"][0]
    assert item["legacy_kind"] == "other"
    assert item["source_kind"] == "effect"
    assert item["kind_normalization_reason"] == "unknown-kind-normalized-to-other"


# ── extraction: deterministic adapter emits new role/layer kinds ──────────


def test_deterministic_provider_emits_source_locked_kinds() -> None:
    from app.services.object_extraction import (
        DeterministicExtractionProvider,
        extract_object_candidates,
    )

    provider = DeterministicExtractionProvider()
    evidence: dict[str, Any] = {
        "video_item_id": "00000000-0000-0000-0000-000000000002",
        "video_width": 320,
        "video_height": 240,
        "nb_frames": 300,
        "extractor_version": "1.0.0",
        "scenes": [
            {
                "id": f"s{i}",
                "start_frame": i * 30,
                "end_frame": i * 30 + 29,
                "start_time_ms": i * 1000,
                "end_time_ms": i * 1000 + 999,
            }
            for i in range(6)
        ],
    }
    candidates = extract_object_candidates(provider, **evidence)
    # Six layout proposals -> the first six canonical kinds (both providers
    # share the stable index -> kind mapping; source_overlay included).
    emitted = [c.kind for c in candidates]
    assert set(emitted) == {
        "character",
        "prop",
        "background",
        "foreground",
        "graphic",
        "source_overlay",
    }
    assert all(k in OBJECT_KINDS for k in emitted)


# ── grouping: kind-homogeneous, source_overlay excluded ───────────────────


def test_grouping_never_pairs_different_kinds() -> None:
    slow = [(5, 500, 10, 10, 40, 40)]
    evidence = [
        _evidence("r1", "Hero", slow, kind="character"),
        _evidence("r2", "Hero", slow, kind="prop"),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_grouping_source_overlay_never_pairs_with_anything() -> None:
    slow = [(5, 500, 10, 10, 40, 40)]
    evidence = [
        _evidence("r1", "Watermark", slow, kind="source_overlay"),
        _evidence("r2", "Watermark", slow, kind="graphic"),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []
    # Even two source_overlay roles sharing name + footprint never pair.
    both_overlay = [
        _evidence("r1", "Watermark", slow, kind="source_overlay"),
        _evidence("r2", "Watermark", slow, kind="source_overlay"),
    ]
    assert generate_pair_suggestions(both_overlay, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_grouping_character_metrics_do_not_regress() -> None:
    """Same-name character roles with a consistent footprint still pair 0.9."""
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r2", "Hero", [(105, 10500, 11, 10, 39, 41)]),
    ]
    suggestions = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)
    assert len(suggestions) == 1
    assert suggestions[0].confidence == 0.9


def test_grouping_prop_kind_homogeneous() -> None:
    """Two same-kind props still pair (kind guard is homogeneity, not a ban)."""
    evidence = [
        _evidence("r1", "Cup", [(5, 500, 10, 10, 40, 40)], kind="prop"),
        _evidence("r2", "Cup", [(105, 10500, 11, 10, 39, 41)], kind="prop"),
    ]
    suggestions = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)
    assert len(suggestions) == 1
    assert suggestions[0].confidence == 0.9


# ── correction: merge refuses removal-only participants ───────────────────


def test_merge_rejects_removal_only_participants(client: TestClient) -> None:
    session = _session()
    ids = _seed_ownership(session)
    project_id, video_id, scene_a, scene_b = ids
    repo = ObjectIntelligenceRepository(session)
    overlay, _ = repo.create_role(
        DEFAULT_WORKSPACE_ID,
        project_id,
        video_id,
        "1",
        "Watermark",
        kind="source_overlay",
    )
    graphic, _ = repo.create_role(
        DEFAULT_WORKSPACE_ID,
        project_id,
        video_id,
        "1",
        "PhoneGraphic",
        kind="graphic",
    )
    session.commit()

    group_repo = ObjectGroupingRepository(session)
    # source_overlay as merge TARGET -> conflict (never a merged replacement).
    with pytest.raises(RoleConflictError):
        group_repo.apply_merge(
            DEFAULT_WORKSPACE_ID,
            project_id,
            video_id,
            overlay.id,
            [graphic.id],
            overlay.revision,
        )
    # source_overlay as merge SOURCE -> conflict.
    with pytest.raises(OperationConflictError):
        group_repo.apply_merge(
            DEFAULT_WORKSPACE_ID,
            project_id,
            video_id,
            graphic.id,
            [overlay.id],
            graphic.revision,
        )


# ── correction schema: role_kind accepts all seven kinds, rejects unknown ─


def test_correction_role_kind_edit_schema_seven_kinds(client: TestClient) -> None:
    ids = _seed_ownership(_session())
    project_id, video_id, _, _ = ids
    created = _api_role(client, ids, "character", "Editable")
    role = created.json()
    base = {
        "kind": "candidate_edit",
        "project_id": project_id,
        "video_item_id": video_id,
        "generation": "1",
        "target": "role",
        "role_id": role["id"],
        "role_revision": role["revision"],
    }
    for kind in ALL_SEVEN:
        preview = client.post(f"{API}/corrections/preview", json={**base, "role_kind": kind})
        assert preview.status_code == 200, (kind, preview.text)
    unknown = client.post(f"{API}/corrections/preview", json={**base, "role_kind": "bogus"})
    assert unknown.status_code == 422, unknown.text
