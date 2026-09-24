"""MF-P1-QC-EVIDENCE — the POSITIVE path through the real public chain.

public submit (``POST /api/v2/projects/{id}/qc-check-runs``) → server-side
composition from persisted evidence → durable RUN_QC_CHECKS job → worker →
persisted QC result.  No direct service call bypasses the handler, and no QC
row is ever seeded: every item asserted here was produced by a real detector
reading the persisted artifacts.

Also proved here: the audio-only path still works on its own, a video without
visual evidence refuses with the typed code (never a silent pass), and a run
whose evidence changed after submission refuses instead of going green.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest
from conftest import GEN, WS, _no_audio_attempt_result
from sqlalchemy import select, update

from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Job,
    JobAttempt,
    QCItem,
    VideoItem,
)
from app.workflow.durable_worker import WorkerConfig
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    policy_bundle,
)


def _bind_worker(service) -> None:  # noqa: ANN001
    worker = service.worker
    assert worker is not None
    worker._config = WorkerConfig(  # noqa: SLF001 - test seam on own instance
        worker_id="p1qc-worker",
        lease_ttl=60,
        heartbeat_interval=15,
        poll_interval=0.01,
        max_attempts=3,
        staging_root=Path(service.managed_root),
    )


def _run_to_terminal(service, *, rounds: int = 4) -> None:  # noqa: ANN001
    for _ in range(rounds):
        with contextlib.suppress(Exception):  # the job row is the authority
            service.worker.run_once()
        with service.session_factory() as session:
            states = session.scalars(select(Job.state)).all()
        if "running" not in states:
            return


def _submit(client, project_id: str, video_id: str, scope: str):  # noqa: ANN001
    return client.post(
        f"/api/v2/projects/{project_id}/qc-check-runs",
        json={"video_item_id": video_id, "scope": scope},
    )


def _add_video_with_audio_only(service) -> str:  # noqa: ANN001
    """A second video item whose ONLY persisted evidence is the audio attach."""
    from app.persistence.models import Project

    with service.session_factory() as session:
        project = session.scalars(select(Project)).first()
        video = VideoItem(
            project_id=project.id,
            title="audio only",
            position=5,
            status="imported",
            duration_ms=2000,
        )
        session.add(video)
        session.flush()
        job = Job(
            workspace_id=WS,
            job_type="ATTACH_ORIGINAL_AUDIO",
            owner_type="video_item",
            owner_id=video.id,
            state="completed",
            input_generation=GEN,
            input_manifest_json="{}",
        )
        session.add(job)
        session.flush()
        session.add(
            JobAttempt(
                job_id=job.id,
                step_code="attach_original_audio",
                attempt=1,
                worker_id="p1qc-fixture",
                fence_token=1,
                result_json=json.dumps(_no_audio_attempt_result()),
            )
        )
        session.commit()
        return str(video.id)


# ── the positive public path ────────────────────────────────────────────────


@pytest.fixture()
def completed_full_run(http_evidence):  # noqa: ANN001, ANN201
    client, service, ids = http_evidence
    _bind_worker(service)
    response = _submit(client, ids.project_id, ids.video_item_id, "full")
    assert response.status_code == 202, response.text
    job_id = str(response.json()["job_id"])
    _run_to_terminal(service)
    with service.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.state == "completed", job.error_json
        manifest = json.loads(job.input_manifest_json)
    return client, service, ids, job_id, manifest


def test_public_full_scope_submits_and_completes(completed_full_run) -> None:  # noqa: ANN001
    _client, service, ids, job_id, manifest = completed_full_run
    assert manifest["scope"] == "full"
    detector_args = manifest["detector_args"]
    assert len(detector_args) == 10
    # the composed provenance is PERSISTED with the durable run manifest
    for detector in (
        "trajectory_drift",
        "cut_drift",
        "contact_break",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "edge_halo",
        "temporal_flicker",
    ):
        provenance = detector_args[detector]["evidence_provenance"]
        assert provenance["detector"] == detector
        assert provenance["input_digest"]
    # the audio pair keeps the T03E envelope contract (no provenance envelope)
    assert "checkpoint" in detector_args["audio_missing"]
    assert "evidence_provenance" not in detector_args["audio_missing"]


def test_public_full_scope_persists_real_qc_items(completed_full_run) -> None:  # noqa: ANN001
    _client, service, ids, _job_id, manifest = completed_full_run
    with service.session_factory() as session:
        items = list(
            session.scalars(
                select(QCItem).where(QCItem.video_item_id == ids.video_item_id)
            ).all()
        )
    assert items, "the public run must persist the items its detectors found"
    detectors = {str(item.detector) for item in items}
    assert detectors <= {
        "trajectory_drift",
        "cut_drift",
        "contact_break",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "edge_halo",
        "temporal_flicker",
    }
    # the identity item's evidence carries the RENDER artifact id ⇒ the item was
    # produced from the persisted rendered bytes, not from a fabricated dict
    identity_items = [item for item in items if str(item.detector) == "identity_drift"]
    assert identity_items
    live_evidence = identity_items[0].evidence_json
    if isinstance(live_evidence, str):
        live_evidence = json.loads(live_evidence)
    frame_ids = {frame["artifact_id"] for frame in live_evidence["frames"]}
    assert frame_ids == {ids.render_artifact_id}
    # correction round C / R4: the persisted target identity is the pinned
    # LIBRARY reference of the selected CharacterID + PackVersion, not a crop
    # of the source video.
    assert (
        live_evidence["pinned_reference"]["artifact_id"]
        == ids.reference_artifact_ids["Character"]
    )
    assert live_evidence["pinned_reference"]["artifact_id"] != ids.source_artifact_id
    composed = manifest["detector_args"]["identity_drift"]
    assert composed["render_observation"]["artifact"]["artifact_id"] == (
        ids.render_artifact_id
    )
    assert composed["render_observation"]["pts_ms"]["timebase"] == {
        "fps_num": 30,
        "fps_den": 1,
    }
    assert composed["pinned_reference"]["artifact_id"] == (
        ids.reference_artifact_ids["Character"]
    )
    assert composed["cast_pin"]["roles_total"] == len(ids.role_ids)


def test_completion_block_records_all_ten_checks_and_frozen_policy(completed_full_run) -> None:  # noqa: ANN001, E501
    from app.persistence.models import JobStep

    _client, service, _ids, job_id, _manifest = completed_full_run
    with service.session_factory() as session:
        step = session.scalars(
            select(JobStep).where(JobStep.job_id == job_id)
        ).all()
    checkpoint = None
    for row in step:
        if row.checkpoint_json:
            block = json.loads(row.checkpoint_json)
            if block.get("completed") is True:
                checkpoint = block
    assert checkpoint is not None, "no durable completion evidence written"
    assert checkpoint["job_type"] == JOB_TYPE_RUN_QC_CHECKS
    assert checkpoint["summary"]["checks_run"] == 10
    assert checkpoint["summary"]["errors"] == 0
    assert sorted(checkpoint["detector_revisions"]) == sorted(
        [
            "trajectory_drift",
            "cut_drift",
            "contact_break",
            "z_order_error",
            "silhouette_clipping",
            "identity_drift",
            "edge_halo",
            "temporal_flicker",
            "audio_missing",
            "av_sync_drift",
        ]
    )
    # no threshold/registry change was needed for anything above
    assert checkpoint["policy_content_hash"] == policy_bundle()["policy_content_hash"]


# ── retained audio-only path + honest refusals on the public surface ────────


def test_audio_only_scope_still_works_without_visual_evidence(http_evidence) -> None:  # noqa: ANN001
    client, service, _ids = http_evidence
    _bind_worker(service)
    video_id = _add_video_with_audio_only(service)
    with service.session_factory() as session:
        project_id = session.get(VideoItem, video_id).project_id
    response = _submit(client, str(project_id), video_id, "audio")
    assert response.status_code == 202, response.text
    _run_to_terminal(service)
    with service.session_factory() as session:
        job = session.scalars(
            select(Job).where(
                Job.job_type == JOB_TYPE_RUN_QC_CHECKS,
                Job.owner_id == video_id,
            )
        ).first()
        assert job is not None and job.state == "completed", job.error_json


def test_full_scope_without_visual_evidence_refuses_with_typed_code(http_evidence) -> None:  # noqa: ANN001, E501
    client, service, _ids = http_evidence
    video_id = _add_video_with_audio_only(service)
    with service.session_factory() as session:
        project_id = session.get(VideoItem, video_id).project_id
    response = _submit(client, str(project_id), video_id, "full")
    assert response.status_code == 422, response.text
    detail = response.text
    assert "QC_RUN_EVIDENCE_UNAVAILABLE" in detail
    assert "QC_EVIDENCE_MISSING" in detail
    with service.session_factory() as session:
        assert (
            session.scalars(
                select(QCItem).where(QCItem.video_item_id == video_id)
            ).all()
            == []
        )


def test_evidence_changed_after_submit_refuses_instead_of_going_green(http_evidence) -> None:  # noqa: ANN001, E501
    client, service, ids = http_evidence
    _bind_worker(service)
    response = _submit(client, ids.project_id, ids.video_item_id, "full")
    assert response.status_code == 202, response.text
    job_id = str(response.json()["job_id"])
    with service.session_factory() as session:
        before = len(
            session.scalars(
                select(QCItem).where(QCItem.video_item_id == ids.video_item_id)
            ).all()
        )
        # a re-import/replacement changes the persisted source identity
        session.execute(
            update(Artifact)
            .where(Artifact.id == ids.source_artifact_id)
            .values(sha256="f" * 64)
        )
        session.commit()
    _run_to_terminal(service)
    with service.session_factory() as session:
        job = session.get(Job, job_id)
        after = len(
            session.scalars(
                select(QCItem).where(QCItem.video_item_id == ids.video_item_id)
            ).all()
        )
    assert job is not None
    assert job.state == "failed"
    assert "QC_RUN_EVIDENCE_CHANGED" in str(job.error_json)
    assert after == before, "a refused run must not persist partial QC results"


def test_public_manifest_pins_the_source_artifact_identity(completed_full_run) -> None:  # noqa: ANN001
    _client, service, ids, _job_id, manifest = completed_full_run
    with service.session_factory() as session:
        artifact = session.get(Artifact, ids.source_artifact_id)
    assert manifest["source_artifact_id"] == ids.source_artifact_id
    assert manifest["source_sha256"] == str(artifact.sha256)
    assert (
        session_count_owners(service, ids.render_artifact_id) >= 1
    ), "the render artifact must be genuinely persisted + owned"


def session_count_owners(service, artifact_id: str) -> int:  # noqa: ANN001
    with service.session_factory() as session:
        return len(
            session.scalars(
                select(ArtifactOwner).where(ArtifactOwner.artifact_id == artifact_id)
            ).all()
        )
