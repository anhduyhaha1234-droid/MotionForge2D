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
from app.persistence.models import S12ExportRun as _RunExportRow  # noqa: E402
from app.persistence.models import VideoItem, Workspace  # noqa: E402
from app.workflow.qc_checks_handler import (  # noqa: E402
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_FULL,
    _ensure_full_band_registered_locked,
    detector_revisions,
    evidence_fingerprint,
    policy_bundle,
    scope_detectors,
    scope_fingerprint,
    source_artifact_fingerprint,
)

DB = os.environ["MF_DB_PATH"]
WS = DEFAULT_WORKSPACE_ID
CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


FRAME_COUNT = 60  # source real media: testsrc 384x216 @30fps duration=2s → 60 frames


def _manifest_doc() -> dict:
    return {
        "frame_count": FRAME_COUNT,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


def _completion_block(session: Session, *, pid: str, vid: str) -> dict:
    _ensure_full_band_registered_locked()
    policy = policy_bundle()
    band = scope_detectors(SCOPE_FULL)
    current_src = source_artifact_fingerprint(
        session, video_item_id=vid
    )
    fp = evidence_fingerprint(session, workspace_id=WS, video_item_id=vid)
    return {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "job_type": JOB_TYPE_RUN_QC_CHECKS,
        "completed": True,
        "run_id": "a" * 64,
        "policy_id": policy["policy_id"],
        "policy_content_hash": policy["policy_content_hash"],
        "source_generation": "1",
        "source_artifact_id": current_src["source_artifact_id"],
        "source_artifact_fingerprint": current_src["source_sha256"],
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
        "evidence_fingerprint": fp,
        "detectors": list(band),
        "detector_revisions": detector_revisions(list(band)),
        "summary": {
            "checks_requested": len(band),
            "checks_run": len(band),
            "checks_skipped": 0,
            "errors": 0,
            "cancelled": False,
            "deadline_exceeded": False,
            "created": 0,
            "not_applicable": len(band),
        },
        "zero_item_completion": {
            "evidence": True,
            "qc_items_created": 0,
            "issues_found": 0,
            "checks_run": len(band),
            "not_applicable": len(band),
        },
    }


def _seed_completed_check_run(session: Session, *, pid: str, vid: str) -> str:
    repo = JobRepository(session)
    session.get(Workspace, WS)
    session.get(VideoItem, vid)
    fp = evidence_fingerprint(session, workspace_id=WS, video_item_id=vid)
    src = source_artifact_fingerprint(session, video_item_id=vid)
    manifest = {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "workspace_id": WS,
        "project_id": pid,
        "video_item_id": vid,
        "evidence_fingerprint": fp,
        "policy_id": policy_bundle()["policy_id"],
        "policy_content_hash": policy_bundle()["policy_content_hash"],
        "source_generation": "1",
        "source_artifact_id": src["source_artifact_id"],
        "source_sha256": src["source_sha256"],
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
    completion = _completion_block(session, pid=pid, vid=vid)
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


def _seed_full_apply_authority(
    session: Session,
    *,
    ws: str,
    pid: str,
    vid: str,
    frame_count: int,
    source_file: str,
) -> dict[str, str]:
    """Seed the immutable CURRENT completed Full Apply authority (F02).

    Mirrors tests/s12/s12-t01/test_preflight_contract._seed_s10_authority:
    one completed S10FullApplyRun + one completed publication + its READY
    video artifact, all pinning the frozen checkpoint.  The publication
    artifact is a REAL file on disk under the managed root (the export
    worker renders from ``source_relative_path``), with a real sha256.
    """
    plan_id = _hex64(f"plan-seed-{_uuid.uuid4().hex}")
    run_id = f"run-{_uuid.uuid4().hex[:12]}"
    pub_id = f"pub-{_uuid.uuid4().hex[:12]}"
    art_id = f"art-{_uuid.uuid4().hex[:8]}"

    rel = f"s12t05/apply_out_{_uuid.uuid4().hex[:8]}.mp4"
    dest = _Path(os.environ["S12T05_QA_ROOT"]) / "artifacts" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    import shutil as _shutil  # noqa: PLC0415

    _shutil.copyfile(source_file, dest)
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()

    session.execute(
        _text(
            "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,"
            "size_bytes,mime_type,width,height,revision) "
            "VALUES (:a,:w,'video',:rel,'ready',:sha,:sz,'video/mp4',3840,2160,1)"
        ),
        {"a": art_id, "w": ws, "rel": rel, "sha": sha, "sz": dest.stat().st_size},
    )
    session.execute(
        _text(
            "INSERT INTO s10_full_apply_run(id,workspace_id,project_id,video_item_id,"
            "apply_checkpoint_id,apply_checkpoint_hash,apply_checkpoint_revision,"
            "plan_id,plan_hash,status,frame_count,fps_num,fps_den,chunk_config_json,"
            "attempt,revision) "
            "VALUES (:rid,:w,:p,:v,:cid,:ch,:crev,:plan,:plan,"
            "'completed',:fc,30,1,'{}',1,1)"
        ),
        {
            "rid": run_id,
            "w": ws,
            "p": pid,
            "v": vid,
            "cid": "ac-t05",
            "ch": CHK_HASH,
            "crev": 1,
            "plan": plan_id,
            "fc": frame_count,
        },
    )
    session.execute(
        _text(
            "INSERT INTO s10_full_apply_publication(id,workspace_id,run_id,artifact_id,"
            "content_hash,frame_count,frame_metadata_json,checkpoint_id,checkpoint_hash,"
            "checkpoint_revision,state,revision) "
            "VALUES (:pub,:w,:rid,:aid,:ch,:fc,:fm,:cid,:ckh,:ckr,'completed',1)"
        ),
        {
            "pub": pub_id,
            "w": ws,
            "rid": run_id,
            "aid": art_id,
            "ch": _hex64(f"pub-{pub_id}"),
            "fc": frame_count,
            "fm": '{"fps_num": 30, "fps_den": 1}',
            "cid": "ac-t05",
            "ckh": CHK_HASH,
            "ckr": 1,
        },
    )
    session.commit()
    return {"run_id": run_id, "publication_id": pub_id, "artifact_id": art_id}


def _hex64(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_completed_artifact(
    qa_root: _Path, pid: str, vid: str, source_media: str,
) -> _Path:
    """Write REAL export output + sha256 sidecar at the server-owned path.

    The C22 result/media endpoints derive the artifact path from managed
    root + project/video (app.api.routes.s12_export._server_paths) and
    serve ONLY completed runs whose artifact matches its sidecar.  This
    mirrors the T03C publication layout (export_master.mp4 + .sha256);
    the source bytes are the REAL ffmpeg media (playable video/mp4).
    """
    import shutil as _shutil  # noqa: PLC0415

    out_dir = qa_root / "artifacts" / "s12-exports" / pid / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / "export_master.mp4"
    _shutil.copyfile(source_media, artifact)
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    sidecar = out_dir / "export_master.mp4.sha256"
    sidecar.write_text(f"{sha}\n", encoding="ascii")
    return artifact


def _write_tampered_artifact(
    qa_root: _Path, pid: str, vid: str, source_media: str,
) -> _Path:
    """Write artifact with a WRONG sidecar (byte-identity mismatch)."""
    import shutil as _shutil  # noqa: PLC0415

    out_dir = qa_root / "artifacts" / "s12-exports" / pid / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / "export_master.mp4"
    _shutil.copyfile(source_media, artifact)
    sidecar = out_dir / "export_master.mp4.sha256"
    sidecar.write_text(f"{'0' * 64}\n", encoding="ascii")
    return artifact


def cmd_export(session: Session) -> dict:
    pid = str(_uuid.uuid4())
    pid_blocked = str(_uuid.uuid4())
    v_ready = str(_uuid.uuid4())
    v_blocked = str(_uuid.uuid4())

    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": WS},
    )
    session.execute(
        _text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'ExportProj')"),
        {"p": pid, "w": WS},
    )
    session.execute(
        _text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'BlockedProj')"),
        {"p": pid_blocked, "w": WS},
    )
    session.execute(
        _text("INSERT INTO video_item(id,project_id,title,position,status,width,height,"
              "fps_num,fps_den,duration_ms) VALUES (:v,:p,'VidReady',0,'imported',"
              "3840,2160,30,1,10000)"),
        {"v": v_ready, "p": pid},
    )
    # Video blocked -> PROJECT RIÊNG (C2 readiness aggregate: not_run WINS
    # khi ANY active video thiếu completed current run — gộp chung project
    # làm readiness cả project not_run, không phải lỗi backend).
    session.execute(
        _text("INSERT INTO video_item(id,project_id,title,position,status,width,height,"
              "fps_num,fps_den,duration_ms) VALUES (:v,:p,'VidBlocked',0,'imported',"
              "1920,1080,30,1,10000)"),
        {"v": v_blocked, "p": pid_blocked},
    )
    art_rel = "s12t05/source_ready.mp4"
    art_path = _Path(os.environ["S12T05_QA_ROOT"]) / "artifacts" / art_rel
    art_path.parent.mkdir(parents=True, exist_ok=True)
    # C2 F06/real-media: the source artifact MUST be real playable media —
    # a fake byte blob fails the runner CFR gate (moov atom missing).  Use
    # ffmpeg to synthesize a small CFR h264 source (testsrc pattern).
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("[seed] ffmpeg not on PATH (real-media source required)")
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=384x216:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(art_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    art_bytes = art_path.read_bytes()
    if len(art_bytes) < 1024:
        raise SystemExit(f"[seed] generated source too small ({len(art_bytes)}B)")
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
    from app.workflow.job_service import JobService  # noqa: E402

    factory = create_session_factory(session.bind)
    qa_root = _Path(os.environ["S12T05_QA_ROOT"])
    svc = JobService(factory, managed_root=str(qa_root / "artifacts"))
    dirs = {
        "chunk_dir": str(qa_root / "chunks"),
        "scratch_dir": str(qa_root / "scratch"),
        "output_path": str(qa_root / "out.mp4"),
    }

    # C2 F02 server-owned authority: seed the immutable CURRENT completed
    # Full Apply authority (one completed S10FullApplyRun + one completed
    # publication + its READY video artifact pinning the SAME checkpoint).
    # This mirrors the real fixture shape (tests/s12/s12-t01
    # test_preflight_contract._seed_s10_authority); without it the real
    # export gate fails closed with S12_EXPORT_FULL_APPLY_MISSING.
    _seed_full_apply_authority(
        session,
        ws=WS,
        pid=pid,
        vid=v_ready,
        frame_count=FRAME_COUNT,
        source_file=str(art_path),
    )

    # Pending run for UI progress/reopen tests — created DIRECTLY through
    # the repository (no claimable durable job), so the production worker
    # never claims it mid-test and the run stays pending for the whole E2E.
    from app.persistence.s12_export import S12ExportRepository  # noqa: E402

    with factory() as s1:
        repo = S12ExportRepository(s1)
        pending_kw = dict(
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
            frame_count=FRAME_COUNT,
            chunk_config={"overlap": 5, "max_frames": 30},
        )
        pend, _ = repo.create_run(
            idempotency_key="s12t05-ui-pending",
            **pending_kw,
        )
        s1.commit()
        pending_id = pend.id

        # Separate run for the CANCEL test (mobile project re-runs the same
        # spec against the same seeded DB; each state-changing API test owns
        # its own run so desktop/mobile never collide).
        cancel_run, _ = repo.create_run(
            idempotency_key="s12t05-ui-cancel",
            **pending_kw,
        )
        s1.commit()
        cancel_id = cancel_run.id

        # ── cancelled run WITH a real durable job for the RETRY test ──
        # retry inherits render pins from the predecessor job manifest, so
        # the cancelled run must carry a job row.  We enqueue via the real
        # submit path then cancel job+run through repository transitions
        # (same as the cancel route) BEFORE uvicorn starts — the worker
        # never sees a queued job because the job is already cancelling.
        from app.workflow.s12_export_jobs import submit_export_job  # noqa: E402

        retry_kw = dict(pending_kw)
        retry_kw["plan_id"] = "b" * 64
        retry_kw["plan_hash"] = "b" * 64
        retry_run, retry_job, _created = submit_export_job(
            svc,
            source_path=str(art_path),
            fps=30.0,
            chunk_dir=dirs["chunk_dir"],
            scratch_dir=dirs["scratch_dir"],
            output_path=dirs["output_path"],
            idempotency_key="s12t05-ui-retry-base",
            **retry_kw,
        )
        s1.commit()
        jrep = JobRepository(s1)
        cur = jrep.get_job(retry_job.job_id)
        jrep.transition_job(
            retry_job.job_id, "cancelling", actor="api",
            expected_revision=cur.revision, reason_code="CANCEL_REQUESTED",
        )
        rrow = s1.get(_RunExportRow, retry_run.id)
        if rrow is not None:
            rrow.status = "cancelled"
        s1.commit()
        retry_id = retry_run.id

    with factory() as s2:
        repo = S12ExportRepository(s2)
        keep = ("workspace_id", "project_id", "video_item_id", "checkpoint_id",
                "checkpoint_hash", "checkpoint_revision", "manifest_id",
                "manifest_hash", "manifest_generation", "profile_id", "plan_id",
                "plan_hash", "frame_count", "chunk_config")
        kw2 = {k: v for k, v in pending_kw.items() if k in keep}
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
                core_start_frame=idx * 30,
                core_end_frame=idx * 30 + 29,
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

    # C22-part positive: the completed run must expose a REAL playable
    # artifact at the server-derived output path (managed root
    # s12-exports/{project}/{video}/export_master.mp4) + immutable sha256
    # sidecar — the same layout the T03C publication writes.  We copy the
    # REAL ffmpeg source media as the export output (real video/mp4 bytes)
    # and write the byte-identity sidecar, so GET result/media serve it.
    _write_completed_artifact(
        qa_root, pid, v_ready, str(art_path),
    )

    # C22 denied: a TAMPERED artifact (sidecar mismatch) must NOT be
    # served — completed run + real file but WRONG sidecar => 403.
    # Server path is per project/video, so this uses the BLOCKED project's
    # video (its own server-derived path, never touching the good result),
    # with its OWN checkpoint/manifest/lock pins (create_run rejects
    # cross-project pins).
    with factory() as s3:
        session3 = s3  # same factory session shape
        session3.execute(
            _text("INSERT INTO character(id,workspace_id,name,code) VALUES ('ch-t05b',:w,'H','h-t05b')"),
            {"w": WS},
        )
        session3.execute(
            _text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) "
                  "VALUES ('pv-t05b','ch-t05b',:w,1,'published')"),
            {"w": WS},
        )
        session3.execute(
            _text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                  "source_generation,name,kind,status) VALUES ('rl-t05b',:w,:p,:v,'g','C',"
                  "'character','confirmed')"),
            {"w": WS, "p": pid_blocked, "v": v_blocked},
        )
        session3.execute(
            _text("INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
                  "cast_mapping_id,character_id,pack_version_id,params_json,"
                  "idempotency_key,revision) VALUES ('rc-t05b',:w,:p,'rl-t05b',NULL,"
                  "'ch-t05b','pv-t05b','{}',NULL,1)"),
            {"w": WS, "p": pid_blocked},
        )
        session3.execute(
            _text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                  "reskin_config_revision,pack_version_ids_json,loop_hashes_json,"
                  "timebase_fingerprint,snapshot_json,checkpoint_hash,note,"
                  "idempotency_key,revision) VALUES ('ac-t05b',:w,:p,'rc-t05b',1,'[]','[]',"
                  "'tb','{}',:h,NULL,NULL,1)"),
            {"w": WS, "p": pid_blocked, "h": CHK_HASH},
        )
        lock = StructuralLockRepository(session3)
        m_b, _ = lock.create_manifest(WS, pid_blocked, v_blocked, "gen1", _manifest_doc())
        session3.commit()
        manifest_b = m_b.id
        manifest_hash_b = str(m_b.manifest_hash_hex)

        repo3 = S12ExportRepository(session3)
        tamper_kw = dict(
            workspace_id=WS,
            project_id=pid_blocked,
            video_item_id=v_blocked,
            checkpoint_id="ac-t05b",
            checkpoint_hash=CHK_HASH,
            checkpoint_revision=1,
            manifest_id=manifest_b,
            manifest_hash=manifest_hash_b,
            manifest_generation="gen1",
            profile_id="master-4k-h264",
            plan_id="b" * 63 + "1",
            plan_hash="b" * 63 + "1",
            frame_count=FRAME_COUNT,
            chunk_config={"overlap": 5, "max_frames": 30},
        )
        tamper_run, _ = repo3.create_run(
            idempotency_key="s12t05-ui-tampered",
            **tamper_kw,
        )
        lease3 = repo3.claim_run(tamper_run.id, "seed-worker")
        session3.commit()
        ch3, _ = repo3.upsert_chunk(
            run_id=tamper_run.id,
            workspace_id=WS,
            chunk_index=0,
            order_index=0,
            core_start_frame=0,
            core_end_frame=29,
            content_hash="c" * 64,
            actor="seed-worker",
            fence_token=lease3.fence_token,
        )
        session3.commit()
        repo3.transition_chunk(
            ch3.id, "running", actor="seed-worker",
            fence_token=lease3.fence_token, expected_revision=ch3.revision,
        )
        session3.commit()
        progressed3 = repo3.list_chunks(tamper_run.id)[0]
        repo3.transition_chunk(
            progressed3.id, "completed", actor="seed-worker",
            fence_token=lease3.fence_token, expected_revision=progressed3.revision,
            verified=1,
        )
        session3.execute(
            _text("UPDATE s12_export_run SET status='completed', revision=revision+1 WHERE id=:r"),
            {"r": tamper_run.id},
        )
        session3.commit()
        tampered_id = tamper_run.id
    _write_tampered_artifact(
        qa_root, pid_blocked, v_blocked, str(art_path),
    )

    return {
        "case": "export",
        "project_id": pid,
        "project_blocked_id": pid_blocked,
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
        "pending_run_id": pending_id,
        "cancel_run_id": cancel_id,
        "retry_base_run_id": retry_id,
        "completed_run_id": completed_id,
        "tampered_run_id": tampered_id,
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
