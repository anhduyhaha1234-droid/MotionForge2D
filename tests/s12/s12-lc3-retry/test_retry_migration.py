"""Upgrade proof for retained S12 rows from the actual prior revision."""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from sqlalchemy import text
from test_export_jobs_api import CHK_HASH, _config, env  # noqa: F401

from app.persistence.models import Job, S12ExportRun


def test_upgrade_retains_terminal_rows_hashes_and_binds_existing_job(env):  # noqa: F811
    factory, svc, manifest_id, _dirs = env
    db = factory.kw["bind"].url.database
    cfg = _config(Path(db))
    command.downgrade(cfg, "c3d4e5f6a7b8")

    with factory() as session:
        manifest_hash = str(
            session.execute(
                text("SELECT manifest_hash FROM structural_lock_manifest WHERE id=:id"),
                {"id": manifest_id},
            ).scalar_one()
        )
        ids = [str(uuid.uuid4()) for _ in range(4)]
        statuses = ("pending", "completed", "failed", "cancelled")
        for index, (run_id, state) in enumerate(zip(ids, statuses, strict=True)):
            session.execute(
                text(
                    "INSERT INTO s12_export_run "
                    "(id,workspace_id,project_id,video_item_id,checkpoint_id,"
                    "checkpoint_hash,checkpoint_revision,manifest_id,manifest_hash,"
                    "manifest_generation,profile_id,profile_dims,profile_codec,plan_id,"
                    "plan_hash,status,frame_count,chunk_config_json,attempt,natural_key,"
                    "idempotency_key,revision) VALUES "
                    "(:id,'ws-s12t03c','p-ws-s12t03c','v-ws-s12t03c','ac-a',:ch,1,"
                    ":mid,:mh,'gen1','master-4k-h264','3840x2160','h264',:pi,:ph,:st,"
                    "100,:cfg,1,:nk,:ik,1)"
                ),
                {
                    "id": run_id,
                    "ch": CHK_HASH,
                    "mid": manifest_id,
                    "mh": manifest_hash,
                    "pi": f"{index + 1:064x}",
                    "ph": f"{index + 11:064x}",
                    "st": state,
                    "cfg": '{"max_frames":50,"overlap":5}',
                    "nk": f"legacy-lineage-{index}",
                    "ik": f"legacy-idem-{index}",
                },
            )
        session.execute(
            text(
                "INSERT INTO s12_export_chunk "
                "(id,workspace_id,run_id,chunk_index,order_index,core_start_frame,"
                "core_end_frame,overlap_before,overlap_after,content_hash,state,attempt,"
                "verified,natural_key,idempotency_key,revision) VALUES "
                "(:id,'ws-s12t03c',:run,0,0,0,49,0,0,:hash,'completed',1,1,:nk,:ik,1)"
            ),
            {
                "id": str(uuid.uuid4()),
                "run": ids[2],
                "hash": "a" * 64,
                "nk": "legacy-chunk-lineage",
                "ik": "legacy-chunk-idem",
            },
        )
        session.commit()

    job = svc.create_job(
        "s12_export",
        {
            "schema_version": 1,
            "run_id": ids[2],
            "workspace_id": "ws-s12t03c",
            "project_id": "p-ws-s12t03c",
            "video_item_id": "v-ws-s12t03c",
            "plan_hash": f"{13:064x}",
            "checkpoint_hash": CHK_HASH,
        },
        workspace_id="ws-s12t03c",
        owner_type="project",
        owner_id="p-ws-s12t03c",
        idempotency_key=f"s12_export_job:{ids[2]}",
        input_generation=f"{13:064x}",
    )

    command.upgrade(cfg, "head")
    with factory() as session:
        rows = session.query(S12ExportRun).filter_by(workspace_id="ws-s12t03c").all()
        assert {row.status for row in rows} == set(statuses)
        assert {row.attempt for row in rows} == {1}
        assert all(row.lineage_id for row in rows)
        retained = session.get(S12ExportRun, ids[2])
        assert retained is not None
        assert retained.checkpoint_hash == CHK_HASH
        assert retained.manifest_hash == manifest_hash
        assert retained.job_id == job.job_id
        assert session.query(Job).filter_by(id=job.job_id).count() == 1
        assert session.execute(
            text("SELECT content_hash FROM s12_export_chunk WHERE run_id=:id"),
            {"id": ids[2]},
        ).scalar_one() == "a" * 64
