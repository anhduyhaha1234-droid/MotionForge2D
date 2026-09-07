"""S12-T05 E2E seed — export UI dataset (T03C fixture shape).

Seeds the task backend DB: workspace/project/videos, ready source artifact
(3840x2160 native 4K), one BLOCKED video (no source), reskin_config + ready
apply_checkpoint, structural-lock manifest (gen1), completed FULL
RUN_QC_CHECKS run (readiness), plus one real export run via
submit_export_job (pending) and one completed run with verified chunks.

Prints ONE final JSON line consumed by the Playwright spec.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid as _uuid
from pathlib import Path as _Path

_BACKEND_ROOT = os.environ.get("MF_BACKEND_ROOT", "")
if _BACKEND_ROOT and _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text as _text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path  # noqa: E402
from app.persistence.jobs import JobRepository, StepInput  # noqa: E402
from app.persistence.models import VideoItem, Workspace  # noqa: E402
from app.workflow.qc_checks_handler import (  # noqa: E402
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_FULL,
    evidence_fingerprint,
    policy_bundle,
    scope_fingerprint,
)

DB = os.environ["MF_DB_PATH"]
WS = DEFAULT_WORKSPACE_ID
CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


def _manifest_doc() -> dict:
    return {
        "frame_count": 100,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


def _completion_block() -> dict:
    policy = policy_bundle()
    return {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "job_type": JOB_TYPE_RUN_QC_CHECKS,
        "completed": True,
        "run_id": "a" * 64,
        "policy_id": policy["policy_id"],
        "policy_content_hash": policy["policy_content_hash"],
        "source_generation": "1",
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
        "evidence_fingerprint": "computed-in-caller",
        "detectors": ["audio_missing", "av_sync_drift"],
        "detector_revisions": {"audio_missing": "1.0.0", "av_sync_drift": "1.0.0"},
        "summary": {
            "checks_requested": 2,
            "checks_run": 2,
            "errors": 0,
            "created": 0,
            "not_applicable": 2,
        },
        "zero_item_completion": {
            "evidence": True,
            "qc_items_created": 0,
            "issues_found": 0,
            "checks_run": 2,
            "not_applicable": 2,
        },
    }


def _seed_completed_check_run(session: Session, *, pid: str, vid: str) -> str:
    repo = JobRepository(session)
    session.get(Workspace, WS)
    session.get(VideoItem, vid)
    fp = evidence_fingerprint(session, workspace_id=WS, video_item_id=vid)
    manifest = {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "workspace_id": WS,
        "project_id": pid,
        "video_item_id": vid,
        "evidence_fingerprint": fp,
        "policy_content_hash": policy_bundle()["policy_content_hash"],
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
    }
    record = repo.create_job(
        workspace_id=WS,
        job_type=JOB_TYPE_RUN_QC_CHECKS,
        owner_type="video_item",
        owner_id=vid,
        input_manifest=manifest,
        idempotency_key=f"RUN_QC_CHECKS:video_item:{vid}:s12t05:1",
        input_generation="1",
        steps=[StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
        actor="api",
    )
    step = repo.list_steps(record.id)[0]
    repo.transition_step(step.id, "ready", actor="system",
                         expected_revision=step.revision, fence_token="seed-token")
    step2 = repo.list_steps(record.id)[0]
    repo.transition_step(step2.id, "running", actor="system",
                         expected_revision=step2.revision, fence_token="seed-token")
    step3 = repo.list_steps(record.id)[0]
    completion = _completion_block()
    completion["evidence_fingerprint"] = fp
    repo.record_attempt(
        job_id=record.id,
        step_id=step3.id,
        step_code="run_qc_checks",
        attempt=1,
        worker_id="seed-worker",
        fence_token="seed-token",
        result=completion,
    )
    repo.transition_step(step3.id, "completed", actor="system",
                         expected_revision=step3.revision, fence_token="seed-token")
    running = repo.transition_job(record.id, "running", actor="system",
                                  expected_revision=record.revision)
    repo.transition_job(record.id, "completed", actor="system",
                        expected_revision=running.revision)
    session.commit()
    return record.id


def cmd_export(session: Session) -> dict:
    pid = str(_uuid.uuid4())
    v_ready = str(_uuid.uuid4())
    v_blocked = str(_uuid.uuid4())

    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": WS},
    )
    session.execute(
        _text("INSERT INTO project(id,workspace_id,name,description,status) "
              "VALUES (:p,:w,'ProjT05','','active') ON CONFLICT(id) DO NOTHING"),
        {"p": pid, "w": WS},
    )
    session.execute(
        _text("INSERT INTO video_item(id,project_id,title,position,status,width,height,"
              "fps_num,fps_den,duration_ms) VALUES (:v,:p,'VidReady',0,'imported',"
              "3840,2160,30,1,10000)"),
        {"v": v_ready, "p": pid},
    )
    session.execute(
        _text("INSERT INTO video_item(id,project_id,title,position,status,width,height,"
              "fps_num,fps_den,duration_ms) VALUES (:v,:p,'VidBlocked',1,'imported',"
              "1920,1080,30,1,10000)"),
        {"v": v_blocked, "p": pid},
    )
    art_rel = "s12t05/source_ready.mp4"
    art_bytes = b"S12T05-READY-SOURCE" * 64
    art_path = _Path(os.environ["S12T05_QA_ROOT"]) / "artifacts" / art_rel
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_bytes(art_bytes)
    art_id = str(_uuid.uuid4())
    session.execute(
        _text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,"
              "size_bytes,mime_type,width,height) VALUES (:a,:w,'video',:rel,'ready',"
              ":sha,:sz,'video/mp4',3840,2160)"),
        {"a": art_id, "w": WS, "rel": art_rel,
         "sha": hashlib.sha256(art_bytes).hexdigest(), "sz": len(art_bytes)},
    )
    session.execute(
        _text("UPDATE video_item SET source_artifact_id=:a WHERE id=:v"),
        {"a": art_id, "v": v_ready},
    )
    session.execute(
        _text("INSERT INTO character(id,workspace_id,name,code) VALUES ('ch-t05',:w,'H','h-t05')"),
        {"w": WS},
    )
    session.execute(
        _text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,"
              "status) VALUES ('pv-t05','ch-t05',:w,1,'published')"),
        {"w": WS},
    )
    session.execute(
        _text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
              "source_generation,name,kind,status) VALUES ('rl-t05',:w,:p,:v,'g','C',"
              "'character','confirmed')"),
        {"w": WS, "p": pid, "v": v_ready},
    )
    session.execute(
        _text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
              "cast_mapping_id,character_id,pack_version_id,params_json,"
              "idempotency_key,revision) VALUES ('rc-t05',:w,:p,'rl-t05',NULL,"
              "'ch-t05','pv-t05','{}',NULL,1)"),
        {"w": WS, "p": pid},
    )
    session.execute(
        _text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
              "reskin_config_revision,pack_version_ids_json,loop_hashes_json,"
              "timebase_fingerprint,snapshot_json,checkpoint_hash,note,"
              "idempotency_key,revision) VALUES ('ac-t05',:w,:p,'rc-t05',1,'[]','[]',"
              "'tb','{}',:h,NULL,NULL,1)"),
        {"w": WS, "p": pid, "h": CHK_HASH},
    )
    session.commit()

    from app.persistence.structural_lock import StructuralLockRepository  # noqa: E402

    lock = StructuralLockRepository(session)
    m1, _ = lock.create_manifest(WS, pid, v_ready, "gen1", _manifest_doc())
    session.commit()
    manifest_id = m1.id
    manifest_hash = str(m1.manifest_hash_hex)

    _seed_completed_check_run(session, pid=pid, vid=v_ready)

    from app.persistence import create_session_factory  # noqa: E402
    from app.workflow.s12_export_jobs import submit_export_job  # noqa: E402
    from app.workflow.job_service import JobService  # noqa: E402

    factory = create_session_factory(session.bind)
    qa_root = _Path(os.environ["S12T05_QA_ROOT"])
    svc = JobService(factory, managed_root=str(qa_root / "artifacts"))
    dirs = {
        "chunk_dir": str(qa_root / "chunks"),
        "scratch_dir": str(qa_root / "scratch"),
        "output_path": str(qa_root / "out.mp4"),
    }
    kw = dict(
        workspace_id=WS,
        project_id=pid,
        video_item_id=v_ready,
        checkpoint_id="ac-t05",
        checkpoint_hash=CHK_HASH,
        checkpoint_revision=1,
        manifest_id=manifest_id,
        manifest_hash=manifest_hash,
        manifest_generation="gen1",
        profile_id="master-4k-h264",
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        frame_count=100,
        chunk_config={"overlap": 5, "max_frames": 50},
        source_path=str(art_path),
        fps=30.0,
        idempotency_key="s12t05-seed-run",
        **dirs,
    )
    run, _job, _created = submit_export_job(svc, **kw)

    from app.persistence.s12_export import S12ExportRepository  # noqa: E402

    with factory() as s2:
        repo = S12ExportRepository(s2)
        keep = ("workspace_id", "project_id", "video_item_id", "checkpoint_id",
                "checkpoint_hash", "checkpoint_revision", "manifest_id",
                "manifest_hash", "manifest_generation", "profile_id", "plan_id",
                "plan_hash", "frame_count", "chunk_config")
        kw2 = {k: v for k, v in kw.items() if k in keep}
        kw2["idempotency_key"] = "s12t05-seed-completed"
        kw2["plan_id"] = "f" * 64
        kw2["plan_hash"] = "a" * 63 + "0"
        rec2, _ = repo.create_run(**kw2)
        s2.commit()
        lease = repo.claim_run(rec2.id, "seed-worker")
        s2.commit()
        for idx in range(2):
            chunk, _ = repo.upsert_chunk(
                run_id=rec2.id,
                workspace_id=WS,
                chunk_index=idx,
                order_index=idx,
                core_start_frame=idx * 50,
                core_end_frame=idx * 50 + 49,
                content_hash="f" * 64 if idx == 0 else "a" * 64,
                actor="seed-worker",
                fence_token=lease.fence_token,
            )
            s2.commit()
            repo.transition_chunk(
                chunk.id, "running", actor="seed-worker",
                fence_token=lease.fence_token, expected_revision=chunk.revision,
            )
            s2.commit()
            progressed = repo.list_chunks(rec2.id)[idx]
            repo.transition_chunk(
                progressed.id, "completed", actor="seed-worker",
                fence_token=lease.fence_token, expected_revision=progressed.revision,
                verified=1,
            )
            s2.commit()
        s2.execute(
            _text("UPDATE s12_export_run SET status='completed', revision=revision+1 WHERE id=:r"),
            {"r": rec2.id},
        )
        s2.commit()
        completed_id = rec2.id

    return {
        "case": "export",
        "project_id": pid,
        "workspace_id": WS,
        "video_ready": v_ready,
        "video_blocked": v_blocked,
        "checkpoint_id": "ac-t05",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": manifest_hash,
        "manifest_generation": "gen1",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "pending_run_id": run.id,
        "completed_run_id": completed_id,
    }


def main() -> None:
    case = sys.argv[1]
    engine = create_engine_for_path(DB)
    with Session(engine) as session:
        assert case == "export", f"unknown case {case!r}"
        out = cmd_export(session)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
