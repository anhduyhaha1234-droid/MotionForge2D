"""S08-A01-C1 (F2) focused tests — kind-safe manual merge.

The A01 merge guard excluded removal-only participants but still allowed
merging e.g. a ``graphic`` into a ``character``.  C1 closes that gap: every
merge source MUST share the target's kind — rejected with a stable 409
BEFORE any mutation, and the correction/merge PREVIEW reports it too.

Covers (in-scope repository + API parts):
- mixed-kind merge refused in BOTH directions (target character + prop
  source; target prop + character source) with ZERO mutation of roles,
  revisions, statuses, occurrences, operations and suggestions;
- same-kind merge still works (no regression);
- API surfaces the 409 with a stable message.

(The correction/merge PREVIEW conflict check lives in a packet-scope
decision — see BLOCKED note in REPORT; the repository/API execute guard here
is the same ``apply_merge`` path the correction confirm flow reuses.)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    ObjectGroupingSuggestion,
    ObjectOccurrence,
    ObjectRole,
    RoleOperation,
)
from app.persistence.object_grouping import (
    ObjectGroupingRepository,
    OperationConflictError,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
)

API = "/api/v2/object-intelligence/grouping"


def _session() -> Session:
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _seed_cluster(session: Session) -> dict[str, str]:
    """Minimal ownership chain (workspace -> project -> video -> scene)."""
    from app.persistence.models import Project, Scene, VideoItem, Workspace

    workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
    project = Project(workspace_id=workspace.id, name="F2")
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
    session.add_all([workspace, project, video, scene])
    session.commit()
    return {"project": project.id, "video": video.id, "scene": scene.id}


def _role(
    session: Session, cluster: dict[str, str], name: str, kind: str
) -> ObjectRole:
    repo = ObjectIntelligenceRepository(session)
    record, _ = repo.create_role(
        DEFAULT_WORKSPACE_ID,
        cluster["project"],
        cluster["video"],
        "1",
        name,
        kind=kind,
    )
    return record  # type: ignore[return-value]


def _occurrence(
    session: Session, cluster: dict[str, str], role_id: str, frame: int
) -> ObjectOccurrence:
    repo = ObjectIntelligenceRepository(session)
    record, _ = repo.create_occurrence(
        DEFAULT_WORKSPACE_ID,
        role_id,
        cluster["scene"],
        frame,
        frame * 100,
        bbox_x=10,
        bbox_y=10,
        bbox_w=40,
        bbox_h=40,
        confidence=0.8,
        confidence_source="detector",
        algorithm="deterministic-layout",
        algorithm_version="1",
        reasons=["test-evidence"],
        review_state="accepted",
    )
    return record  # type: ignore[return-value]


def _snapshot(session: Session) -> dict[str, object]:
    """Every durable surface that a merge could mutate — byte-level snapshot."""
    roles = [
        (r.id, r.revision, r.status, r.name, r.kind)
        for r in session.scalars(select(ObjectRole).order_by(ObjectRole.id)).all()
    ]
    occs = [
        (o.id, o.role_id, o.revision, o.scene_id, o.frame_index)
        for o in session.scalars(
            select(ObjectOccurrence).order_by(ObjectOccurrence.id)
        ).all()
    ]
    ops = [
        (o.id, o.operation_type, o.target_role_id)
        for o in session.scalars(select(RoleOperation).order_by(RoleOperation.id)).all()
    ]
    suggs = [
        (s.id, s.status)
        for s in session.scalars(
            select(ObjectGroupingSuggestion).order_by(ObjectGroupingSuggestion.id)
        ).all()
    ]
    return {"roles": roles, "occurrences": occs, "operations": ops, "suggestions": suggs}


# ── repository: kind guard, both directions, ZERO mutation ─────────────────


def test_repo_merge_mixed_kinds_refused_both_directions(client: TestClient) -> None:
    with _session() as session:
        cluster = _seed_cluster(session)
        char = _role(session, cluster, "Hero", "character")
        prop = _role(session, cluster, "Sword", "prop")
        session.commit()
        char_id, prop_id = char.id, prop.id
        # Pre-seed a suggestion so we can prove it is untouched on refusal.
        repo = ObjectGroupingRepository(session)
        suggestion, _ = repo.create_suggestion(
            DEFAULT_WORKSPACE_ID,
            cluster["project"],
            cluster["video"],
            "1",
            [char_id, prop_id],
            0.9,
            ["test"],
            "role-fingerprint",
            "1",
        )
        session.commit()
        suggestion_id = suggestion.id
        before = _snapshot(session)

        # direction 1: character target + prop source
        with pytest.raises(OperationConflictError, match="share the target role kind"):
            repo.apply_merge(
                DEFAULT_WORKSPACE_ID,
                cluster["project"],
                cluster["video"],
                char_id,
                [prop_id],
                1,
            )
        # direction 2: prop target + character source
        with pytest.raises(OperationConflictError, match="share the target role kind"):
            repo.apply_merge(
                DEFAULT_WORKSPACE_ID,
                cluster["project"],
                cluster["video"],
                prop_id,
                [char_id],
                1,
            )

    with _session() as session:
        after = _snapshot(session)
        # PROVE ZERO MUTATION: every surface byte-identical after both refusals.
        assert after == before
        assert len(after["roles"]) == 2
        assert len(after["occurrences"]) == 0
        assert len(after["operations"]) == 0
        assert len(after["suggestions"]) == 1
        # Suggestion still pending (not dismissed/superseded by the refusal).
        sug = session.get(ObjectGroupingSuggestion, suggestion_id)
        assert sug is not None and sug.status == "pending"


def test_repo_merge_same_kind_still_applies(client: TestClient) -> None:
    with _session() as session:
        cluster = _seed_cluster(session)
        role_a = _role(session, cluster, "Hero", "character")
        role_b = _role(session, cluster, "Hero", "character")
        _occurrence(session, cluster, role_a.id, 5)
        _occurrence(session, cluster, role_b.id, 105)
        session.commit()
        target_id, source_id = role_a.id, role_b.id

        repo = ObjectGroupingRepository(session)
        op, target, created = repo.apply_merge(
            DEFAULT_WORKSPACE_ID,
            cluster["project"],
            cluster["video"],
            target_id,
            [source_id],
            role_a.revision,
        )
        session.commit()
        assert created and op.operation_type == "merge"
        with _session() as session2:
            source = session2.get(ObjectRole, source_id)
            assert source is not None and source.status == "superseded"
            assert source.supersedes_role_id == target_id
            target = session2.get(ObjectRole, target_id)
            assert target is not None and target.kind == "character"


# ── API: stable 409 before mutation, both directions ───────────────────────


def test_api_merge_mixed_kinds_409_zero_mutation(client: TestClient) -> None:
    with _session() as session:
        cluster = _seed_cluster(session)
        char = _role(session, cluster, "Hero", "character")
        graphic = _role(session, cluster, "LogoGraphic", "graphic")
        session.commit()
        char_id, graphic_id = char.id, graphic.id
        before = _snapshot(session)

        # direction 1: target character + graphic source -> 409
        r1 = client.post(
            f"{API}/roles/{char_id}/merge",
            json={
                "video_item_id": cluster["video"],
                "revision": char.revision,
                "source_role_ids": [graphic_id],
            },
        )
        assert r1.status_code == 409, r1.text
        assert "share the target role kind" in r1.json()["detail"]

        # direction 2: target graphic + character source -> 409
        r2 = client.post(
            f"{API}/roles/{graphic_id}/merge",
            json={
                "video_item_id": cluster["video"],
                "revision": graphic.revision,
                "source_role_ids": [char_id],
            },
        )
        assert r2.status_code == 409, r2.text
        assert "share the target role kind" in r2.json()["detail"]

    with _session() as session:
        after = _snapshot(session)
        assert after == before
        assert len(after["roles"]) == 2
        assert len(after["operations"]) == 0


def test_api_merge_remove_only_kind_still_refused(client: TestClient) -> None:
    """F2 keeps A01's removal-only guarantee: source_overlay never merges."""
    with _session() as session:
        cluster = _seed_cluster(session)
        char = _role(session, cluster, "Hero", "character")
        overlay = _role(session, cluster, "Watermark", "source_overlay")
        session.commit()

        r = client.post(
            f"{API}/roles/{char.id}/merge",
            json={
                "video_item_id": cluster["video"],
                "revision": char.revision,
                "source_role_ids": [overlay.id],
            },
        )
        assert r.status_code == 409, r.text
        assert "removal-only" in r.json()["detail"]


# ── correction/merge PREVIEW reports the same conflict (read-only) ─────────


def test_correction_merge_preview_reports_kind_conflict_both_directions(
    client: TestClient,
) -> None:
    """POST /corrections/preview with kind=merge and mixed kinds -> 409 with
    ZERO durable mutation (no correction row, roles/revisions unchanged)."""
    CORR = "/api/v2/object-intelligence/corrections"
    with _session() as session:
        cluster = _seed_cluster(session)
        char = _role(session, cluster, "Hero", "character")
        prop = _role(session, cluster, "Sword", "prop")
        session.commit()
        char_id, prop_id = char.id, prop.id
        before = _snapshot(session)

    payload_char_target = {
        "kind": "merge",
        "project_id": cluster["project"],
        "video_item_id": cluster["video"],
        "generation": "1",
        "target_role_id": char_id,
        "target_revision": 1,
        "source_role_ids": [prop_id],
    }
    # direction 1: character target + prop source
    r1 = client.post(f"{CORR}/preview", json=payload_char_target)
    assert r1.status_code == 409, r1.text
    assert "share the target role kind" in r1.json()["detail"]

    payload_prop_target = {
        "kind": "merge",
        "project_id": cluster["project"],
        "video_item_id": cluster["video"],
        "generation": "1",
        "target_role_id": prop_id,
        "target_revision": 1,
        "source_role_ids": [char_id],
    }
    # direction 2: prop target + character source
    r2 = client.post(f"{CORR}/preview", json=payload_prop_target)
    assert r2.status_code == 409, r2.text
    assert "share the target role kind" in r2.json()["detail"]

    with _session() as session:
        # ZERO durable mutation: no correction was created; every surface that
        # a merge/confirm could mutate is byte-identical to before.
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        from app.persistence.models import ObjectCorrection

        assert (
            session.scalar(sa_select(func.count()).select_from(ObjectCorrection))
            == 0
        )
        after = _snapshot(session)
        assert after == before
        assert len(after["roles"]) == 2
        assert len(after["occurrences"]) == 0
        assert len(after["operations"]) == 0


def test_correction_merge_preview_same_kind_succeeds(client: TestClient) -> None:
    """Same-kind merge preview returns a normal impact (200) — only mixed
    kinds are refused, so the correction flow still works for real merges."""
    CORR = "/api/v2/object-intelligence/corrections"
    with _session() as session:
        cluster = _seed_cluster(session)
        char_a = _role(session, cluster, "Hero", "character")
        char_b = _role(session, cluster, "Hero", "character")
        session.commit()

        r = client.post(
            f"{CORR}/preview",
            json={
                "kind": "merge",
                "project_id": cluster["project"],
                "video_item_id": cluster["video"],
                "generation": "1",
                "target_role_id": char_a.id,
                "target_revision": char_a.revision,
                "source_role_ids": [char_b.id],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["correction_type"] == "merge"
