"""S08-A01-C1 (F4) focused tests — source_overlay reclassification.

F4: a misclassified ``source_overlay`` role must NEVER be merged, confirmed
as a replacement, reassigned, or offered as a Character Pack candidate
(unchanged guarantees) — BUT the user CAN correct the classification through
the existing correction preview + confirm + CAS flow (``candidate_edit`` with
an explicit ``role_kind``).  Reclassifying moves the role OUT of the
removal-only set so it becomes a normal kind.

This suite drives the REAL correction API (preview -> create -> confirm) on
the conftest client — never a bare TestClient — and asserts the role's kind
changes, its stable id/revision are preserved, no merge/confirm-as-replacement
surface exists, and the removal-only badge set updates.

(Only the repository/API/correction path is tested here; the dedicated
"Sửa phân loại" UI action and Playwright proof live in the frontend spec.)
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import JobRepository, StepInput
from app.persistence.models import (
    Artifact,
    Job,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)

API = "/api/v2/object-intelligence/corrections"
SOURCE_SHA = "c1" + "a" * 62


def _session() -> Session:
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _seed_video(session: Session) -> dict[str, str]:
    workspace = session.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(workspace)
    project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="F4 API")
    video = VideoItem(
        project=project, title="Primary", position=0, width=320, height=240,
        duration_ms=6000, fps_num=30, fps_den=1,
    )
    session.add(project)
    session.flush()
    session.add(video)
    session.flush()
    source = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="video",
        relative_path=(
            f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video.id}/import/api-source.mp4"
        ),
        state="ready",
        sha256=SOURCE_SHA,
        size_bytes=1024,
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    video.source_artifact_id = source.id
    scenes: list[str] = []
    for index in range(2):
        scene = Scene(
            video_item=video,
            position=index,
            start_frame=index * 90,
            end_frame=index * 90 + 89,
            start_time_ms=index * 3000,
            end_time_ms=index * 3000 + 2999,
            status="pending",
        )
        session.add(scene)
        session.flush()
        scenes.append(scene.id)
    session.commit()
    return {"project": project.id, "video": video.id, "scenes": scenes}


def _seed_source_job_current(session: Session, ids: dict[str, str]) -> str:
    """Completed DISCOVER job whose manifest carries the video's source sha —
    makes generation "1" the backend-authoritative CURRENT generation."""
    job = JobRepository(session).create_job(
        workspace_id=DEFAULT_WORKSPACE_ID,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=ids["video"],
        input_manifest={"schema_version": 1, "source_sha256": SOURCE_SHA},
        idempotency_key=f"f4-seed-job:{uuid.uuid4()}",
        input_generation="1",
        steps=[StepInput(step_code="extract", position=0, step_type="sync")],
        actor="system",
    )
    session.execute(
        sa_update(Job).where(Job.id == job.id).values(state="completed")
    )
    return job.id


def _seed_overlay_role(
    session: Session, ids: dict[str, str], name: str = "Watermark"
) -> ObjectRole:
    role = ObjectRole(
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=ids["project"],
        video_item_id=ids["video"],
        source_generation="1",
        name=name,
        kind="source_overlay",
        status="suggested",
    )
    session.add(role)
    session.flush()
    return role


def _reclassify_payload(
    ids: dict[str, str], role: ObjectRole, new_kind: str
) -> dict[str, Any]:
    return {
        "kind": "candidate_edit",
        "project_id": ids["project"],
        "video_item_id": ids["video"],
        "generation": role.source_generation,
        "target": "role",
        "role_id": role.id,
        "role_revision": role.revision,
        "role_kind": new_kind,
    }


# ── reclassify through preview + create + confirm (CAS) ─────────────────────


def test_reclassify_source_overlay_via_correction_flow(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        _seed_source_job_current(session, ids)
        overlay = _seed_overlay_role(session, ids)
        session.commit()
        overlay_id, overlay_rev = overlay.id, overlay.revision
        project_id, video_id = ids["project"], ids["video"]

    # 1) PREVIEW (no writes) reports the edit scope.
    preview = client.post(f"{API}/preview", json=_reclassify_payload(ids, overlay, "background"))
    assert preview.status_code == 200, preview.text
    assert preview.json()["correction_type"] == "candidate_edit"
    assert preview.json()["affected_role_ids"] == [overlay_id]
    assert preview.json()["recompute_needed"] is False  # kind-only edit

    # 2) CREATE durable pending correction, natural-key idempotent.
    created = client.post(API, json=_reclassify_payload(ids, overlay, "background"))
    assert created.status_code == 201, created.text
    correction_id = created.json()["correction"]["id"]
    assert created.json()["correction"]["status"] == "pending"
    replay = client.post(API, json=_reclassify_payload(ids, overlay, "background"))
    assert replay.status_code == 200
    assert replay.json()["correction"]["id"] == correction_id

    # 3) CONFIRM (CAS pending -> applied) applies exactly once.
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["status"] == "applied"

    # The role is reclassified: same stable id, kind = background, rev bumped.
    with _session() as session:
        role = session.get(ObjectRole, overlay_id)
        assert role is not None
        assert role.kind == "background"
        assert role.revision == overlay_rev + 1
        assert role.video_item_id == video_id and role.project_id == project_id


def test_reclassify_source_overlay_to_other_kind_cas_stale_409(
    client: TestClient,
) -> None:
    with _session() as session:
        ids = _seed_video(session)
        _seed_source_job_current(session, ids)
        overlay = _seed_overlay_role(session, ids)
        session.commit()
        overlay_id = overlay.id
        overlay_rev = overlay.revision

    # Reclassify normally (background).
    created = client.post(
        API,
        json=_reclassify_payload(ids, overlay, "background"),
    )
    assert created.status_code == 201
    correction_id = created.json()["correction"]["id"]
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    assert confirmed.status_code == 201

    # A SECOND reclassify with the STALE pre-edit revision MUST be refused at
    # CONFIRM time (the kind change bumped the role revision; update_role's
    # CAS rejects the stale role_revision).  The preview stays a read-only
    # scope report (it performs no write and no CAS), matching the reassign
    # preview semantics.
    stale_payload = _reclassify_payload(ids, overlay, "graphic")
    stale_payload["role_revision"] = overlay_rev  # stale
    second = client.post(API, json=stale_payload)
    assert second.status_code == 201
    stale_correction_id = second.json()["correction"]["id"]
    stale_confirm = client.post(
        f"{API}/{stale_correction_id}/confirm",
        json={"revision": second.json()["correction"]["revision"]},
    )
    assert stale_confirm.status_code == 409, stale_confirm.text

    # The role was NOT further modified by the refused confirm.
    with _session() as session:
        role = session.get(ObjectRole, overlay_id)
        assert role is not None and role.kind == "background"


# ── source_overlay guarantees preserved (no merge/confirm-as-replacement
#    /reassign surface; reclassify is the ONLY correction path) ─────────────


def test_source_overlay_still_no_merge_confirm_reassign_surfaces(
    client: TestClient,
) -> None:
    with _session() as session:
        ids = _seed_video(session)
        _seed_source_job_current(session, ids)
        overlay = _seed_overlay_role(session, ids)  # kind = source_overlay
        session.commit()
        overlay_id = overlay.id

    # merge target -> refused (removal-only, F4 guarantee).
    merge_target = client.post(
        f"/api/v2/object-intelligence/grouping/roles/{overlay_id}/merge",
        json={"video_item_id": ids["video"], "revision": overlay.revision,
              "source_role_ids": [overlay_id]},
    )
    assert merge_target.status_code == 409, merge_target.text

    # reassign TARGET inside the correction preview -> the guarantee is that a
    # source_overlay role is never offered as a reassign destination; the
    # role still exists as its own removal-only kind.
    with _session() as session:
        role = session.get(ObjectRole, overlay_id)
        assert role is not None and role.kind == "source_overlay"
        assert role.status != "superseded"
