"""MF-END-06 — library cast-set recommendation: acceptance + negative controls.

Every row below is a CI fixture: deterministic bytes generated in-process, the
per-test isolated SQLite database from ``tests/conftest.py``, and the FastAPI
``TestClient`` for preconditions — engineering evidence, never product-demo
evidence.  No GPU, no network, no ffmpeg, no real product media, and the
advisory route is ALWAYS injected (the pinned default client is never called
from here).

Row map (binary):

* micro repro: request strictness + frozen vocabularies (role-key grammar ==
  the series-pin grammar, view vocabulary == the reference ingest vocabulary);
  requirements are derived from the video's REAL roles (source_overlay is
  never a cast requirement).
* acceptance: the hard filter keeps only published + complete + kind
  compatible packs and lists refusals with real ids; metadata-first ranking
  records views/style; every id in the result exists in the database; the
  advisory is called ONLY on a genuine metadata tie (and the choice must be
  inside the tie set — anything else is recorded and ignored); advisory
  failures surface verbatim while the deterministic result stays usable;
  frames are bounded images and a video artifact is a typed refusal; the
  series pin has absolute priority (stale pin surfaced, never swapped); the
  generation plan exists only for missing views; recommendation is read-only
  (zero mutations, zero new files).
* negative controls: unknown/foreign targets, explicit-requirement
  contradictions, unpublished/archived/capability-missing packs are excluded
  with typed reasons; the pinned route metadata and the JSON extraction
  contract are asserted directly.
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
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence import project_cast as project_cast_module
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
    CAST_ROLE_KEY_PATTERN,
    GENERATION_PLAN_NOTE_FULL,
    GENERATION_PLAN_NOTE_MISSING,
    GENERATION_PLAN_NOTE_STALE_PIN,
    MAX_SOURCE_FRAMES,
    REQUIRED_VIEW_VOCABULARY,
    CastRecommendationRequest,
    CastRoleRequirement,
    SourceFrameInput,
)
from app.services import cast_recommendation as cr
from app.workflow.character_reference_ingest import REFERENCE_VIEWS

FRONT = "front"
SIDE = "side"
BACK = "back"
HERO_KEY = "ROLE-HERO"
BOOK_KEY = "ROLE-BOOK"


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
    if mode == "RGBA":
        img = Image.new("RGBA", (width, height), (gray, 60, 200, alpha))
    elif mode == "RGB":
        img = Image.new("RGB", (width, height), (gray, 60, 200))
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
    """One series = one project with two videos; roles named exactly as keys.

    Episode A carries ``ROLE-HERO`` (character), ``ROLE-BOOK`` (prop) and a
    backend-owned ``ROLE-LOGO`` (source_overlay) role.  Episode B carries
    ``ROLE-EXTRA`` for cross-video ownership negative controls.
    """
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
            ("ROLE-EXTRA", "character", video_b),
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


def _attach_artifact(
    client: TestClient, ver_id: str, slot: str, *, data: bytes | None = None
) -> dict:
    data = data if data is not None else _png_bytes(gray=170)
    rel = f"characters/mf_end_06/{ver_id}/{slot.replace('@', '_')}.png"
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


def _attach_six(client: TestClient, ver_id: str, *, gray: int = 200) -> None:
    for index, slot in enumerate(CORE_POSE_SLOTS):
        _attach_artifact(client, ver_id, slot, data=_png_bytes(gray=gray + index * 7))


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
    _attach_six(client, ver["id"])
    _publish(client, ver["id"], ver["revision"])
    return {
        "character_id": char["id"],
        "version_id": ver["id"],
        "code": code,
    }


def _make_reference_pack(
    client: TestClient, code: str, *, keys: tuple[str, ...]
) -> dict:
    """Publish a reference_pack_v1 pack through the REAL route chain."""
    char = _create_character(client, code)
    ver = _create_version(client, char["id"])
    manifest = {
        "manifest_version": 1,
        "pack_contract": PACK_CONTRACT_VERSION_REFERENCE,
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
    assert resp.json()["status"] == "valid", resp.text
    _publish(client, ver["id"], ver["revision"])
    return {"character_id": char["id"], "version_id": ver["id"], "code": code}


def _seed_orm_pack(
    *,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    character_type: str = "character",
    status: str = "published",
    contract: str = PACK_CONTRACT_VERSION_LEGACY,
    slots: tuple[str, ...] = (),
    manifest: dict | None = None,
    character_status: str = "ready",
) -> dict:
    """ORM-seeded precondition rows (negatives only; never a claim path)."""
    with _session() as session:
        _ensure_workspace(session, workspace_id)
        character = Character(
            workspace_id=workspace_id,
            name=f"Seeded {uuid.uuid4().hex[:6]}",
            code=f"seed_{uuid.uuid4().hex[:8]}",
            character_type=character_type,
            status=character_status,
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
            pack.requirement_manifest_sha256 = hashlib.sha256(text.encode()).hexdigest()
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


def _freeze(series: dict, entries: list[SeriesCastEntryInput]):
    with _session() as session:
        repo = SeriesCastRepository(session)
        record, created = repo.freeze_snapshot(
            series["workspace_id"], series["project_id"], entries
        )
        session.commit()
        return record, created


def _recommend(request: CastRecommendationRequest, *, client=None):
    with _session() as session:
        return cr.recommend_cast(
            session,
            DEFAULT_WORKSPACE_ID,
            request,
            advisory_client=client,
            managed_root=_managed_root(),
        )


class _StubAdvisory:
    """Deterministic advisory transport; records every call."""

    def __init__(self, *, payload=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._payload = payload
        self._error = error

    def complete(self, pin, messages, *, timeout_seconds):  # noqa: ANN001
        self.calls.append(
            {"pin": pin, "messages": messages, "timeout_seconds": timeout_seconds}
        )
        if self._error is not None:
            raise self._error
        return self._payload if self._payload is not None else {"choice": None}


def _hero_request(*, views: list[str] | None = None, **kwargs) -> CastRecommendationRequest:
    return CastRecommendationRequest(
        video_item_id=kwargs.pop("video_item_id"),
        requirements=[
            CastRoleRequirement(
                role_key=HERO_KEY, kind="character", required_views=views or []
            )
        ],
        **kwargs,
    )


def _count(model) -> int:  # noqa: ANN001
    with _session() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _managed_file_count() -> int:
    return sum(1 for path in _managed_root().rglob("*") if path.is_file())


def _candidate_ids(result) -> set[str]:  # noqa: ANN001
    ids: set[str] = set()
    for role in result.roles:
        for candidate in role.candidates:
            ids.add(candidate.pack_version_id)
        for entry in role.filtered:
            ids.add(entry.pack_version_id)
    return ids


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_schema_strictness_and_frozen_vocabularies(client: TestClient) -> None:
    # role_key grammar is the EXACT series-pin grammar (single source)
    assert CAST_ROLE_KEY_PATTERN.pattern == project_cast_module._ROLE_KEY_PATTERN.pattern
    # view vocabulary is the measured one (mirror of the ingest REFERENCE_VIEWS)
    assert set(REFERENCE_VIEWS) == REQUIRED_VIEW_VOCABULARY
    assert set(CORE_POSE_SLOTS) == REQUIRED_VIEW_VOCABULARY

    with pytest.raises(ValidationError):  # unknown field
        CastRecommendationRequest(video_item_id="x", bogus=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):  # strict: no int coercion
        CastRecommendationRequest(video_item_id=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):  # advisory mode literal
        CastRecommendationRequest(video_item_id="x", advisory="sometimes")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):  # empty explicit requirements
        CastRecommendationRequest(video_item_id="x", requirements=[])
    with pytest.raises(ValidationError):  # duplicate role keys
        CastRecommendationRequest(
            video_item_id="x",
            requirements=[
                CastRoleRequirement(role_key=HERO_KEY, kind="character"),
                CastRoleRequirement(role_key=HERO_KEY, kind="character"),
            ],
        )
    # unsupported role key grammar
    with pytest.raises(ValidationError):
        CastRoleRequirement(role_key="role hero!", kind="character")
    # invented view
    with pytest.raises(ValidationError):
        CastRoleRequirement(role_key=HERO_KEY, kind="character", required_views=["close_up"])
    # unknown capability
    with pytest.raises(ValidationError):
        CastRoleRequirement(
            role_key=HERO_KEY, kind="character", required_capabilities=["not_a_capability"]
        )
    # duplicate view
    with pytest.raises(ValidationError):
        CastRoleRequirement(
            role_key=HERO_KEY, kind="character", required_views=[FRONT, FRONT]
        )
    # frame budget: one over the cap is refused at the schema boundary
    frames = [
        SourceFrameInput(artifact_id=str(i))
        for i in range(MAX_SOURCE_FRAMES + 1)
    ]
    with pytest.raises(ValidationError):
        CastRecommendationRequest(video_item_id="x", source_frames=frames)
    with pytest.raises(ValidationError):  # duplicate frame artifact
        CastRecommendationRequest(
            video_item_id="x",
            source_frames=[
                SourceFrameInput(artifact_id="a"),
                SourceFrameInput(artifact_id="a"),
            ],
        )


def test_micro_derive_requirements_from_video_roles(client: TestClient) -> None:
    series = _seed_series()
    with _session() as session:
        derived = cr.derive_role_requirements(
            session, DEFAULT_WORKSPACE_ID, series["video_a"]
        )
    assert [requirement.role_key for requirement in derived] == [BOOK_KEY, HERO_KEY]
    by_key = {requirement.role_key: requirement for requirement in derived}
    assert by_key[HERO_KEY].kind == "character"
    assert by_key[HERO_KEY].object_role_id == series["roles"][HERO_KEY]
    assert by_key[BOOK_KEY].kind == "prop"
    assert all(requirement.required_views == [] for requirement in derived)
    # source_overlay is backend-owned removal-only: never a cast requirement
    assert "ROLE-LOGO" not in by_key


# ── acceptance: hard filter + ranking + real ids ─────────────────────────────


def test_acceptance_hard_filter_published_complete_kind(client: TestClient) -> None:
    series = _seed_series()
    good = _make_legacy_pack(client, "mf06-good")
    draft = _seed_orm_pack(slots=CORE_POSE_SLOTS, status="draft")
    incomplete = _seed_orm_pack(slots=(FRONT, SIDE))
    prop_pack = _make_legacy_pack(client, "mf06-prop", character_type="prop")
    ref_incomplete = _seed_orm_pack(
        contract=PACK_CONTRACT_VERSION_REFERENCE,
        manifest={
            "manifest_version": 1,
            "pack_contract": PACK_CONTRACT_VERSION_REFERENCE,
            "requirements": ["front@character", "side@character"],
        },
        slots=("front@character",),
    )
    foreign = _seed_orm_pack(workspace_id="ws-other", slots=CORE_POSE_SLOTS)

    result = _recommend(
        _hero_request(video_item_id=series["video_a"], advisory="off")
    )
    hero = result.roles[0]
    candidate_ids = {candidate.pack_version_id for candidate in hero.candidates}
    filtered_ids = {entry.pack_version_id for entry in hero.filtered}
    reasons = {entry.pack_version_id: [r.code for r in entry.reasons] for entry in hero.filtered}

    assert good["version_id"] in candidate_ids
    assert prop_pack["version_id"] not in candidate_ids  # kind mismatch
    assert incomplete["version_id"] not in candidate_ids
    assert ref_incomplete["version_id"] not in candidate_ids
    # unpublished pack is outside the pool entirely (pool = published packs)
    assert draft["version_id"] not in candidate_ids
    assert draft["version_id"] not in filtered_ids
    # foreign workspace packs never leak
    assert foreign["version_id"] not in candidate_ids
    assert foreign["version_id"] not in filtered_ids
    # refusals carry real ids + typed reasons
    assert "object_kind_mismatch" in reasons[prop_pack["version_id"]]
    assert "incomplete_pack" in reasons[incomplete["version_id"]]
    assert "missing_required_pose" in reasons[incomplete["version_id"]]
    assert "incomplete_pack" in reasons[ref_incomplete["version_id"]]
    assert result.advisory.status == "not_requested"
    assert result.mutations == 0 and result.read_only is True


def test_acceptance_rank_metadata_first_views_and_style_recorded(
    client: TestClient,
) -> None:
    series = _seed_series()
    covering = _make_legacy_pack(client, "mf06-cover")
    front_only = _make_reference_pack(client, "mf06-frontonly", keys=("front@character",))
    stub = _StubAdvisory(payload={"choice": None})
    result = _recommend(
        _hero_request(
            video_item_id=series["video_a"],
            views=[FRONT, SIDE, BACK],
            advisory="auto",
        ),
        client=stub,
    )
    hero = result.roles[0]
    by_id = {candidate.pack_version_id: candidate for candidate in hero.candidates}
    assert hero.candidates[0].pack_version_id == covering["version_id"]
    assert hero.candidates[0].rank == 0
    assert hero.candidates[1].pack_version_id == front_only["version_id"]
    assert hero.candidates[1].rank == 1
    assert by_id[covering["version_id"]].covers_required_views is True
    assert by_id[covering["version_id"]].missing_views == []
    assert by_id[front_only["version_id"]].covers_required_views is False
    assert by_id[front_only["version_id"]].missing_views == [SIDE, BACK]
    assert any(
        reason.code == "missing_required_views"
        for reason in by_id[front_only["version_id"]].reasons
    )
    # unique metadata top -> no advisory call at all
    assert stub.calls == []
    assert hero.advisory.status == "not_needed"

    styled = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            requirements=[
                CastRoleRequirement(
                    role_key=HERO_KEY,
                    kind="character",
                    required_views=[FRONT],
                    style_version="style-1",
                )
            ],
            advisory="off",
        ),
        client=stub,
    )
    hero_styled = styled.roles[0]
    assert hero_styled.style_version == "style-1"
    for candidate in hero_styled.candidates:
        assert candidate.style_match is None
        assert any(reason.code == "style_unverified" for reason in candidate.reasons)


def test_acceptance_no_invented_ids_all_result_ids_exist(client: TestClient) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "mf06-real-a")
    _make_legacy_pack(client, "mf06-real-b")
    result = _recommend(
        CastRecommendationRequest(video_item_id=series["video_a"], advisory="off")
    )
    all_pack_ids = _candidate_ids(result)
    assert all_pack_ids, "fixture must yield at least one real id"
    with _session() as session:
        real_packs = {
            row.id for row in session.scalars(select(CharacterPackVersion)).all()
        }
        real_characters = {row.id for row in session.scalars(select(Character)).all()}
        characters_by_pack = {
            row.id: row.character_id
            for row in session.scalars(select(CharacterPackVersion)).all()
        }
    assert all_pack_ids <= real_packs
    for role in result.roles:
        for candidate in role.candidates:
            assert candidate.character_id in real_characters
            assert characters_by_pack[candidate.pack_version_id] == candidate.character_id
            if candidate.snapshot_id is not None:
                with _session() as session:
                    assert session.get(SeriesCastSnapshot, candidate.snapshot_id) is not None
        if role.selected_pack_version_id is not None:
            assert role.selected_pack_version_id in real_packs
            assert role.selected_character_id in real_characters


# ── acceptance: advisory discipline ──────────────────────────────────────────


def test_acceptance_advisory_on_metadata_tie_only_and_choice_applied(
    client: TestClient,
) -> None:
    series = _seed_series()
    first = _make_legacy_pack(client, "mf06-tie-a")
    second = _make_legacy_pack(client, "mf06-tie-b")
    stub = _StubAdvisory(payload={"choice": second["version_id"], "reasons": ["style"]})
    result = _recommend(
        _hero_request(video_item_id=series["video_a"], advisory="auto"), client=stub
    )
    hero = result.roles[0]
    assert len(stub.calls) == 1
    tie_ids = {candidate.pack_version_id for candidate in hero.candidates}
    assert tie_ids == {first["version_id"], second["version_id"]}
    assert {candidate.rank for candidate in hero.candidates} == {0}
    assert hero.advisory.status == "ok"
    assert hero.advisory.choice_applied is True
    assert hero.advisory.choice_pack_version_id == second["version_id"]
    assert hero.selected_pack_version_id == second["version_id"]
    assert hero.selection_mode == "advisory"
    assert result.advisory.status == "ok" and result.advisory.calls == 1
    # the call carried the pinned route + scope with BOTH candidates only
    call = stub.calls[0]
    assert call["pin"] is cr.ADVISORY_ROUTE_PIN
    scope = json.loads(call["messages"][1]["content"][0]["text"])
    assert scope["role_key"] == HERO_KEY
    assert {item["pack_version_id"] for item in scope["candidates"]} == tie_ids
    assert scope["video_payload_attached"] is False


def test_acceptance_advisory_error_surfaced_manual_choice_kept(
    client: TestClient,
) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "mf06-down-a")
    _make_legacy_pack(client, "mf06-down-b")
    stub = _StubAdvisory(
        error=cr.AdvisoryUnavailableError("route down: connection refused (CI)")
    )
    result = _recommend(
        _hero_request(video_item_id=series["video_a"], advisory="auto"), client=stub
    )
    hero = result.roles[0]
    assert len(stub.calls) == 1
    assert hero.advisory.status == "unavailable"
    assert "connection refused" in (hero.advisory.error or "")
    assert any(
        note.code == "manual_choice_available" for note in hero.advisory.notes
    )
    # deterministic selection stays usable (manual choice from real candidates)
    assert hero.selection_mode == "metadata"
    assert hero.selected_pack_version_id in {
        candidate.pack_version_id for candidate in hero.candidates
    }
    assert result.advisory.status == "unavailable"
    assert "connection refused" in (result.advisory.error or "")
    assert result.advisory.route.model == "ocg/deepseek-v4.1-flash"
    assert result.advisory.route.fallback_allowed is False
    assert result.manual_choice_available is True


def test_acceptance_advisory_cannot_override_hard_filter(client: TestClient) -> None:
    series = _seed_series()
    good = _make_legacy_pack(client, "mf06-override-a")
    _make_legacy_pack(client, "mf06-override-b")
    excluded = _seed_orm_pack(slots=(FRONT,))
    invented = str(uuid.uuid4())
    for bad_choice in (excluded["version_id"], invented):
        stub = _StubAdvisory(payload={"choice": bad_choice})
        result = _recommend(
            _hero_request(video_item_id=series["video_a"], advisory="auto"), client=stub
        )
        hero = result.roles[0]
        assert len(stub.calls) == 1
        assert hero.advisory.status == "ok"
        assert hero.advisory.choice_applied is False
        assert any(
            note.code == "advisory_choice_outside_permitted_set"
            for note in hero.advisory.notes
        )
        assert hero.selection_mode == "metadata"
        # the eligible pack stays a candidate while the bad choice is ignored
        assert good["version_id"] in {
            candidate.pack_version_id for candidate in hero.candidates
        }
        # the excluded pack stays excluded; the chosen id is never selected
        assert excluded["version_id"] not in {
            candidate.pack_version_id for candidate in hero.candidates
        }
        assert hero.selected_pack_version_id != bad_choice
        assert hero.selected_pack_version_id in {
            candidate.pack_version_id for candidate in hero.candidates
        }
        assert result.mutations == 0


def test_acceptance_advisory_payload_never_contains_video(client: TestClient) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "mf06-vid-a")
    _make_legacy_pack(client, "mf06-vid-b")
    # a real video artifact (precondition) is a typed refusal, zero calls made
    with _session() as session:
        video_artifact = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="video",
            state="ready",
            relative_path=f"videos/{uuid.uuid4().hex}.mp4",
            mime_type="video/mp4",
            size_bytes=10,
            sha256="ab" * 32,
        )
        session.add(video_artifact)
        session.commit()
        video_id = video_artifact.id
    refusing = _StubAdvisory(payload={"choice": None})
    request = CastRecommendationRequest(
        video_item_id=series["video_a"],
        source_frames=[SourceFrameInput(artifact_id=video_id)],
    )
    with pytest.raises(cr.CastRecommendationInputError) as excinfo:
        _recommend(request, client=refusing)
    assert "video" in str(excinfo.value).lower()
    assert refusing.calls == []

    # happy path: payload carries bounded images only (candidates + 1 frame)
    frame_data = _png_bytes(gray=66)
    rel = f"frames/mf_end_06/{uuid.uuid4().hex}.png"
    _write_managed(rel, frame_data)
    with _session() as session:
        frame_artifact = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            state="ready",
            relative_path=rel,
            mime_type="image/png",
            size_bytes=len(frame_data),
            sha256=hashlib.sha256(frame_data).hexdigest(),
        )
        session.add(frame_artifact)
        session.commit()
        frame_id = frame_artifact.id
    stub = _StubAdvisory(payload={"choice": None})
    result = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            source_frames=[SourceFrameInput(artifact_id=frame_id, label="shot-head")],
        ),
        client=stub,
    )
    assert len(stub.calls) == 1
    messages = stub.calls[0]["messages"]
    serialized = json.dumps(messages)
    assert "video/" not in serialized
    assert ".mp4" not in serialized
    image_parts = [
        part
        for part in messages[1]["content"]
        if part["type"] == "image_url"
    ]
    assert len(image_parts) == 2 + 1  # two candidates + one frame
    assert all(
        part["image_url"]["url"].startswith("data:image/png;base64,")
        for part in image_parts
    )
    assert len(serialized.encode("utf-8")) <= cr.MAX_ADVISORY_PAYLOAD_BYTES
    hero_role = next(role for role in result.roles if role.role_key == HERO_KEY)
    assert hero_role.advisory.status == "ok"


def test_acceptance_source_frame_notes_digest_and_missing(client: TestClient) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "mf06-note-a")
    _make_legacy_pack(client, "mf06-note-b")
    missing_bytes = _png_bytes(gray=51)
    with _session() as session:
        missing = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            state="ready",
            relative_path=f"frames/absent/{uuid.uuid4().hex}.png",
            mime_type="image/png",
            size_bytes=len(missing_bytes),
            sha256=hashlib.sha256(missing_bytes).hexdigest(),
        )
        tampered_rel = f"frames/tampered/{uuid.uuid4().hex}.png"
        tampered = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            state="ready",
            relative_path=tampered_rel,
            mime_type="image/png",
            size_bytes=len(missing_bytes),
            sha256=hashlib.sha256(missing_bytes).hexdigest(),
        )
        session.add_all([missing, tampered])
        session.commit()
        missing_id, tampered_id = missing.id, tampered.id
    _write_managed(tampered_rel, _png_bytes(gray=222))  # bytes differ from the row
    stub = _StubAdvisory(payload={"choice": None})
    result = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            source_frames=[
                SourceFrameInput(artifact_id=missing_id),
                SourceFrameInput(artifact_id=tampered_id),
            ],
        ),
        client=stub,
    )
    assert len(stub.calls) == 1
    codes = [note.code for note in result.advisory.notes]
    assert "image_file_missing" in codes
    assert "image_digest_mismatch" in codes
    image_parts = [
        part
        for part in stub.calls[0]["messages"][1]["content"]
        if part["type"] == "image_url"
    ]
    assert len(image_parts) == 2  # both bad frames skipped; candidate art only


# ── acceptance: series pin priority + generation plan + read-only ────────────


def test_acceptance_series_pin_absolute_priority_no_advisory(client: TestClient) -> None:
    series = _seed_series()
    pinned = _make_legacy_pack(client, "mf06-pin")
    _make_legacy_pack(client, "mf06-pin-alt")
    record, created = _freeze(
        series,
        [
            SeriesCastEntryInput(
                role_key=HERO_KEY,
                character_id=pinned["character_id"],
                pack_version_id=pinned["version_id"],
            )
        ],
    )
    assert created is True
    stub = _StubAdvisory(payload={"choice": None})
    result = _recommend(
        _hero_request(
            video_item_id=series["video_a"], views=[FRONT], advisory="auto"
        ),
        client=stub,
    )
    hero = result.roles[0]
    assert stub.calls == []  # absolute priority: no advisory round-trip
    assert hero.advisory.status == "not_needed"
    assert hero.candidates[0].source == "series_snapshot"
    assert hero.candidates[0].pack_version_id == pinned["version_id"]
    assert hero.candidates[0].rank == 0
    assert hero.candidates[0].live_ok is True
    assert hero.selected_pack_version_id == pinned["version_id"]
    assert hero.selection_mode == "series_pin"
    assert hero.series_pin is not None
    assert hero.series_pin.snapshot_id == record.id
    assert result.series is not None and result.series.snapshot_index == record.snapshot_index
    # assets are sufficient -> the plan must explicitly refuse generation
    assert hero.generation.required is False
    assert hero.generation.note == GENERATION_PLAN_NOTE_FULL
    # the pinned pack appears exactly once (not duplicated as a library row)
    ids = [candidate.pack_version_id for candidate in hero.candidates]
    assert ids.count(pinned["version_id"]) == 1


def test_acceptance_series_pin_stale_surfaced_no_auto_change(client: TestClient) -> None:
    series = _seed_series()
    pinned = _make_legacy_pack(client, "mf06-stale")
    replacement = _make_legacy_pack(client, "mf06-stale-alt")
    _freeze(
        series,
        [
            SeriesCastEntryInput(
                role_key=HERO_KEY,
                character_id=pinned["character_id"],
                pack_version_id=pinned["version_id"],
            )
        ],
    )
    # the live library changes underneath the pin (precondition mutation)
    with _session() as session:
        row = session.get(CharacterPackVersion, pinned["version_id"])
        assert row is not None
        row.status = "draft"
        session.commit()
    result = _recommend(
        _hero_request(video_item_id=series["video_a"], advisory="off")
    )
    hero = result.roles[0]
    assert hero.candidates[0].pack_version_id == pinned["version_id"]
    assert hero.candidates[0].live_ok is False
    assert hero.candidates[0].live_problems
    assert any(
        reason.code == "series_pin_stale" for reason in hero.candidates[0].reasons
    )
    # absolute priority: the stale pin is surfaced, NOT silently swapped
    assert hero.selected_pack_version_id == pinned["version_id"]
    assert hero.selection_mode == "series_pin"
    assert hero.selected_pack_version_id != replacement["version_id"]
    assert hero.generation.required is False
    assert hero.generation.note == GENERATION_PLAN_NOTE_STALE_PIN


def test_acceptance_series_pin_style_match_recorded(client: TestClient) -> None:
    series = _seed_series()
    pinned = _make_legacy_pack(client, "mf06-style")
    _freeze(
        series,
        [
            SeriesCastEntryInput(
                role_key=HERO_KEY,
                character_id=pinned["character_id"],
                pack_version_id=pinned["version_id"],
                style_version="style-1",
            )
        ],
    )
    for style, expected in (("style-1", True), ("style-2", False)):
        result = _recommend(
            CastRecommendationRequest(
                video_item_id=series["video_a"],
                requirements=[
                    CastRoleRequirement(
                        role_key=HERO_KEY, kind="character", style_version=style
                    )
                ],
                advisory="off",
            )
        )
        hero = result.roles[0]
        assert hero.candidates[0].style_version == "style-1"
        assert hero.candidates[0].style_match is expected
        expected_code = "style_match" if expected else "style_mismatch"
        assert any(
            reason.code == expected_code for reason in hero.candidates[0].reasons
        )
        assert hero.selected_pack_version_id == pinned["version_id"]
        assert hero.selection_mode == "series_pin"


def test_acceptance_generation_plan_only_when_views_missing(client: TestClient) -> None:
    series = _seed_series()
    front_only = _make_reference_pack(client, "mf06-gen", keys=("front@character",))
    # selected candidate is short one view -> plan names exactly that view
    result = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            requirements=[
                CastRoleRequirement(
                    role_key=HERO_KEY, kind="character", required_views=[FRONT, SIDE]
                )
            ],
            advisory="off",
        )
    )
    hero = result.roles[0]
    assert hero.selected_pack_version_id == front_only["version_id"]
    assert hero.missing_views == [SIDE]
    assert hero.generation.required is True
    assert hero.generation.views == [SIDE]
    assert hero.generation.estimated_cost_units == 1
    assert hero.generation.note == GENERATION_PLAN_NOTE_MISSING
    # assets sufficient (view produced by the pack) -> NO generation proposed
    enough = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            requirements=[
                CastRoleRequirement(
                    role_key=HERO_KEY, kind="character", required_views=[FRONT]
                )
            ],
            advisory="off",
        )
    )
    hero_enough = enough.roles[0]
    assert hero_enough.generation.required is False
    assert hero_enough.generation.views == []
    assert hero_enough.generation.estimated_cost_units == 0
    assert hero_enough.generation.note == GENERATION_PLAN_NOTE_FULL


def test_acceptance_read_only_zero_mutation_and_no_artifacts(client: TestClient) -> None:
    series = _seed_series()
    _make_legacy_pack(client, "mf06-ro-a")
    _make_legacy_pack(client, "mf06-ro-b")
    seeded = _seed_orm_pack(slots=CORE_POSE_SLOTS)
    _freeze(
        series,
        [
            SeriesCastEntryInput(
                role_key=HERO_KEY,
                character_id=seeded["character_id"],
                pack_version_id=seeded["version_id"],
            )
        ],
    )
    stub = _StubAdvisory(payload={"choice": None})
    before = {
        "mappings": _count(ProjectCastMapping),
        "characters": _count(Character),
        "packs": _count(CharacterPackVersion),
        "artifacts": _count(Artifact),
        "snapshots": _count(SeriesCastSnapshot),
        "entries": _count(SeriesCastSnapshotEntry),
        "files": _managed_file_count(),
    }
    result = _recommend(
        CastRecommendationRequest(video_item_id=series["video_a"]), client=stub
    )
    after = {
        "mappings": _count(ProjectCastMapping),
        "characters": _count(Character),
        "packs": _count(CharacterPackVersion),
        "artifacts": _count(Artifact),
        "snapshots": _count(SeriesCastSnapshot),
        "entries": _count(SeriesCastSnapshotEntry),
        "files": _managed_file_count(),
    }
    assert before == after
    assert result.read_only is True
    assert result.mutations == 0


# ── negative controls ────────────────────────────────────────────────────────


def test_negative_unknown_and_foreign_targets(client: TestClient) -> None:
    series = _seed_series()
    unknown = str(uuid.uuid4())
    with pytest.raises(cr.CastRecommendationNotFoundError):
        _recommend(
            CastRecommendationRequest(video_item_id=unknown, advisory="off")
        )
    # video of a foreign workspace is "not found" for this workspace (no leak)
    with _session() as session:
        _ensure_workspace(session, "ws-other")
        project = Project(workspace_id="ws-other", name="Other")
        session.add(project)
        session.flush()
        foreign_video = VideoItem(project_id=project.id, title="Other", position=0)
        session.add(foreign_video)
        session.commit()
        foreign_video_id = foreign_video.id
    with pytest.raises(cr.CastRecommendationNotFoundError):
        _recommend(
            CastRecommendationRequest(video_item_id=foreign_video_id, advisory="off")
        )
    # role owned by ANOTHER video of the same series is not this video's role
    with pytest.raises(cr.CastRecommendationNotFoundError):
        _recommend(
            CastRecommendationRequest(
                video_item_id=series["video_a"],
                requirements=[
                    CastRoleRequirement(
                        role_key=HERO_KEY,
                        kind="character",
                        object_role_id=series["roles"]["ROLE-EXTRA"],
                    )
                ],
                advisory="off",
            )
        )
    # empty workspace id is refused up front
    with _session() as session, pytest.raises(cr.CastRecommendationInputError):
        cr.recommend_cast(
            session,
            "  ",
            CastRecommendationRequest(video_item_id=series["video_a"], advisory="off"),
            managed_root=_managed_root(),
        )


def test_negative_explicit_requirement_contradictions(client: TestClient) -> None:
    series = _seed_series()
    # declared kind contradicts the live role kind -> refuse, do not guess
    with pytest.raises(cr.CastRecommendationInputError):
        _recommend(
            CastRecommendationRequest(
                video_item_id=series["video_a"],
                requirements=[
                    CastRoleRequirement(
                        role_key=HERO_KEY,
                        kind="prop",
                        object_role_id=series["roles"][HERO_KEY],
                    )
                ],
                advisory="off",
            )
        )
    # frames require a managed root to resolve real bytes
    with _session() as session, pytest.raises(cr.CastRecommendationInputError):
        cr.recommend_cast(
            session,
            DEFAULT_WORKSPACE_ID,
            CastRecommendationRequest(
                video_item_id=series["video_a"],
                source_frames=[SourceFrameInput(artifact_id=str(uuid.uuid4()))],
                advisory="off",
            ),
            managed_root=None,
        )
    # unknown frame artifact -> not found (no fabrication, no silent skip)
    with pytest.raises(cr.CastRecommendationNotFoundError):
        _recommend(
            CastRecommendationRequest(
                video_item_id=series["video_a"],
                source_frames=[SourceFrameInput(artifact_id=str(uuid.uuid4()))],
                advisory="off",
            )
        )


def test_negative_unpublished_archived_and_capability_missing(
    client: TestClient,
) -> None:
    series = _seed_series()
    archived = _seed_orm_pack(slots=CORE_POSE_SLOTS, character_status="archived")
    # (published pool excludes drafts entirely; archived + capability are filtered)
    result = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            requirements=[
                CastRoleRequirement(
                    role_key=HERO_KEY,
                    kind="character",
                    required_capabilities=["image_edit_multi_reference"],
                )
            ],
            advisory="off",
        )
    )
    hero = result.roles[0]
    reasons = {entry.pack_version_id: [r.code for r in entry.reasons] for entry in hero.filtered}
    assert "archived_character" in reasons[archived["version_id"]]
    assert "missing_required_capability" in reasons[archived["version_id"]]
    assert hero.candidates == []
    assert hero.selected_pack_version_id is None
    assert hero.selection_mode == "none"
    assert hero.generation.required is False
    # a reference pack that DECLARES the capability passes that dimension
    declared = _seed_orm_pack(
        contract=PACK_CONTRACT_VERSION_REFERENCE,
        manifest={
            "manifest_version": 1,
            "pack_contract": PACK_CONTRACT_VERSION_REFERENCE,
            "requirements": ["front@character"],
            "capabilities": ["image_edit_multi_reference"],
        },
        slots=("front@character",),
    )
    result2 = _recommend(
        CastRecommendationRequest(
            video_item_id=series["video_a"],
            requirements=[
                CastRoleRequirement(
                    role_key=HERO_KEY,
                    kind="character",
                    required_capabilities=["image_edit_multi_reference"],
                )
            ],
            advisory="off",
        )
    )
    hero2 = result2.roles[0]
    assert declared["version_id"] in {
        candidate.pack_version_id for candidate in hero2.candidates
    }
    assert hero2.candidates[0].missing_capabilities == []


def test_pinned_route_metadata_and_json_extraction(client: TestClient) -> None:
    pin = cr.ADVISORY_ROUTE_PIN
    assert pin.provider == "custom"
    assert pin.base_url == "http://127.0.0.1:20128/v1"
    assert pin.api_mode == "chat_completions"
    assert pin.model == "ocg/deepseek-v4.1-flash"
    assert pin.fallback_allowed is False
    assert cr.MAX_ADVISORY_CANDIDATES >= 2
    assert cr.ESTIMATED_COST_UNITS_PER_VIEW == 1
    assert cr.GENERATION_COST_UNIT == "asset"
    parsed = cr._extract_json_object('prose {"choice": "pack-1"} tail')
    assert parsed == {"choice": "pack-1"}
    with pytest.raises(cr.AdvisoryUnavailableError):
        cr._extract_json_object("no json here")
    with pytest.raises(cr.AdvisoryUnavailableError):
        cr._extract_json_object("[1, 2, 3]")
