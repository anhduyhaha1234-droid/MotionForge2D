"""S12-T03C C2 — publication gate tests (candidate boundary contract).

The runner assembles a PRIVATE candidate under scratch; publication
validates it source-locked and, on PASS, atomically moves it to the public
output and completes the run.  Gates proven here: PASS publishes exactly
once (no double assembly), FAIL → failed (retryable), fence mismatch /
not-ready / cross-scope / missing candidate fail closed with zero public
output, completed replay re-verifies bytes, tampered completed artifact
fails replay, partials never become public.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import text

from app.api.routes import s12_export as _route  # noqa: F401  # route import sanity
from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.s12_export import S12ExportRepository
from app.persistence.structural_lock import StructuralLockRepository
from app.services.s12_export import publication as pub
from app.workflow.job_service import JobService
from app.workflow.s12_export_jobs import submit_export_job

import test_export_jobs_api as base

PROJECT_ROOT = base.PROJECT_ROOT
WS = base.WS
OTHER_WS = base.OTHER_WS
CHK_HASH = base.CHK_HASH
PLAN_ID = base.PLAN_ID
PLAN_HASH = base.PLAN_HASH


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t03c-pub.db"
    command.upgrade(base._config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        for ws in (WS, OTHER_WS):
            tag = "a" if ws == WS else "b"
            seed.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
            seed.execute(
                text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
                {"p": f"p-{ws}", "w": ws},
            )
            seed.execute(
                text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"),
                {"v": f"v-{ws}", "p": f"p-{ws}"},
            )
            seed.execute(
                text(f"INSERT INTO character(id,workspace_id,name,code) VALUES ('ch-{tag}',:w,'H','h-{tag}')"),
                {"w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
                    f" VALUES ('pv-{tag}','ch-{tag}',:w,1,'published')"
                ),
                {"w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                    f"source_generation,name,kind,status) VALUES ('rl-{tag}',:w,:p,:v,'g','C','character','confirmed')"
                ),
                {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,cast_mapping_id,"
                    f"character_id,pack_version_id,params_json,idempotency_key,revision) VALUES ('rc-{tag}',:w,:p,"
                    f"'rl-{tag}',NULL,'ch-{tag}','pv-{tag}','{{}}',NULL,1)"
                ),
                {"w": ws, "p": f"p-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                    "reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,"
                    "snapshot_json,checkpoint_hash,note,idempotency_key,revision)"
                    f" VALUES ('ac-{tag}',:w,:p,'rc-{tag}',1,'[]','[]','tb','{{}}',:h,NULL,NULL,1)"
                ),
                {"w": ws, "p": f"p-{ws}", "h": CHK_HASH},
            )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(WS, f"p-{WS}", f"v-{WS}", "gen1", base._manifest_doc())
            s2.commit()
            seed_manifest = m1.id
    svc = JobService(factory, managed_root=tmp_path / "artifacts")
    dirs = {
        "chunk": str(tmp_path / "chunks"),
        "scratch": str(tmp_path / "scratch"),
        "output": str(tmp_path / "out.mp4"),
    }
    yield factory, svc, seed_manifest, dirs
    engine = create_engine_for_path(db)
    engine.dispose()


class _Probe:
    def __init__(self, name: str, verdict: str, detail: str = "") -> None:
        self.name = name
        self.verdict = verdict
        self.detail = detail


class _Verdict:
    def __init__(self, verdict: str, names: list[str]) -> None:
        self.verdict = verdict
        self.probes = tuple(_Probe(n, verdict) for n in names)


def _patch(monkeypatch: pytest.MonkeyPatch, verdict: str) -> None:
    import app.services.s12_export.publication as pubmod

    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    monkeypatch.setattr(
        "app.services.s12_export.validation.validate",
        lambda path, exp: _Verdict(verdict, ["frame_count", "frame_order", "av_policy", "provenance"]),
    )


def _submit(env, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(svc, **base._submit_kwargs(factory, manifest_id, dirs))
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-1")
        s.commit()
    Path(dirs["scratch"]).mkdir(parents=True, exist_ok=True)
    candidate = Path(dirs["scratch"]) / "candidate_final.mp4"
    candidate.write_bytes(b"\x00" * 4096)
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 100,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "profile_codec": "h264",
        "expected_sha256": "",
    }
    kw = {
        "run_id": run.id,
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "worker_id": "worker-1",
        "fence_token": lease.fence_token,
        "manifest": manifest,
    }
    return factory, kw


def test_publish_pass_completes_once(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """PASS publishes exactly one immutable artifact and completes the run."""
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    with factory() as s:
        out = pub.publish_export_run(s, **kw)
        s.commit()
    assert out["status"] == "completed"
    assert out["verdict"] == "PASS"
    assert Path(kw["manifest"]["output_path"]).is_file()
    # The private candidate moved — no copy remains at the candidate path.
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    assert not candidate.exists()
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status == "completed"


def test_publish_validation_fail_lands_failed(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "FAIL")
    factory, kw = _submit(env, monkeypatch)
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(s, **kw)
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status == "failed"
    assert not Path(kw["manifest"]["output_path"]).exists()


def test_publish_fence_mismatch_fails_closed(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    kw = {**kw, "fence_token": "wrong-token"}
    with factory() as s:
        with pytest.raises(Exception):
            pub.publish_export_run(s, **kw)
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status != "completed"
    assert not Path(kw["manifest"]["output_path"]).exists()


def test_publish_fence_lost_before_rename_cleans_candidate(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """C17: a fence loss after validation cannot trigger the rename."""
    from app.persistence.s12_export import FencedWorkerError
    import app.services.s12_export.publication as pubmod

    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    original = pubmod._require_fence
    calls = 0

    def _fence(repo, run_id, worker_id, fence_token):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FencedWorkerError("fence lost", run_id=run_id)
        return original(repo, run_id, worker_id, fence_token)

    monkeypatch.setattr(pubmod, "_require_fence", _fence)
    with factory() as s:
        with pytest.raises(pub.PublicationError, match="fence lost"):
            pub.publish_export_run(s, **kw)
        s.rollback()
    assert calls == 2
    assert not Path(kw["manifest"]["output_path"]).exists()
    assert not list(Path(kw["manifest"]["scratch_dir"]).iterdir())


def test_publish_rename_fault_cleans_private_candidate(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """C18: exclusive final-create failure leaves no candidate or public artifact."""
    import app.services.s12_export.publication as pubmod

    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    monkeypatch.setattr(
        pubmod,
        "_publish_candidate_exclusive",
        lambda *args: (_ for _ in ()).throw(OSError("rename fault")),
    )
    with factory() as s:
        with pytest.raises(pub.PublicationError, match="rename failed"):
            pub.publish_export_run(s, **kw)
        s.rollback()
    assert not Path(kw["manifest"]["output_path"]).exists()
    assert not list(Path(kw["manifest"]["scratch_dir"]).iterdir())


def test_publish_sidecar_fault_removes_unpublished_output(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """C18: sidecar failure cannot strand an output that blocks retry."""
    import app.services.s12_export.publication as pubmod

    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    monkeypatch.setattr(pubmod, "_write_sidecar", lambda *args: (_ for _ in ()).throw(OSError("sidecar fault")))
    with factory() as s:
        with pytest.raises(pub.PublicationError, match="sidecar failed"):
            pub.publish_export_run(s, **kw)
        s.rollback()
    assert not Path(kw["manifest"]["output_path"]).exists()
    assert not Path(f"{kw['manifest']['output_path']}.sha256").exists()
    assert not list(Path(kw["manifest"]["scratch_dir"]).iterdir())


def test_publish_transition_fault_removes_unpublished_output(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """C18: a CAS transition fault removes the not-yet-completed artifact."""
    from app.persistence.s12_export import S12ExportRepository

    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    original = S12ExportRepository.transition_run

    def _transition(self, run_id, status, **kwargs):  # type: ignore[no-untyped-def]
        if status == "completed":
            raise ValueError("commit transition fault")
        return original(self, run_id, status, **kwargs)

    monkeypatch.setattr(S12ExportRepository, "transition_run", _transition)
    with factory() as s:
        with pytest.raises(pub.PublicationError, match="transition lost"):
            pub.publish_export_run(s, **kw)
        s.rollback()
    assert not Path(kw["manifest"]["output_path"]).exists()
    assert not Path(f"{kw['manifest']['output_path']}.sha256").exists()
    assert not list(Path(kw["manifest"]["scratch_dir"]).iterdir())


def test_publish_not_ready_fails_closed(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    import app.services.s12_export.publication as pubmod

    def _blocked(session: Any, **kwargs: Any) -> None:
        raise pub.PublicationError("project readiness 'blocked'; publication requires ready")

    monkeypatch.setattr(pubmod, "_require_ready", _blocked)
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(s, **kw)
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status != "completed"
    assert not Path(kw["manifest"]["output_path"]).exists()


def test_publish_cross_scope_fails_closed(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    kw = {**kw, "project_id": f"p-{OTHER_WS}"}
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(s, **kw)
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status != "completed"
    assert not Path(kw["manifest"]["output_path"]).exists()


def test_publish_missing_candidate_fails_closed(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    Path(kw["manifest"]["scratch_dir"], "candidate_final.mp4").unlink()
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(s, **kw)
        s.rollback()
    assert not Path(kw["manifest"]["output_path"]).exists()


def test_publish_replay_after_completed_rechecks_bytes(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    with factory() as s:
        first = pub.publish_export_run(s, **kw)
        s.commit()
    assert first["status"] == "completed"
    with factory() as s:
        second = pub.publish_export_run(s, **kw)
        s.commit()
    assert second == {"run_id": kw["run_id"], "status": "completed", "reused": True,
                      "output_path": kw["manifest"]["output_path"],
                      "artifact_sha256": first["artifact_sha256"]}
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status == "completed"


def test_publish_tampered_completed_replay_fails(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    with factory() as s:
        first = pub.publish_export_run(s, **kw)
        s.commit()
    assert first["status"] == "completed"
    # Tamper the public artifact: replay must fail closed (sidecar bytes
    # no longer match the public file).
    final = Path(kw["manifest"]["output_path"])
    final.write_bytes(b"\xff" * 4096)
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(s, **kw)
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(kw["run_id"]).status == "completed"


def test_publish_existing_output_never_overwritten(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _patch(monkeypatch, "PASS")
    factory, kw = _submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"pre-existing")
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(s, **kw)
        s.rollback()
    assert final.read_bytes() == b"pre-existing"


def _real_source(tmp_path: Path, *, audio: bool = False) -> Path:
    """Real ffmpeg source: 4K testsrc (native raster, master profile)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (real source-locked row needs real binary)")
    source = tmp_path / ("src_audio.mp4" if audio else "src.mp4")
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=3840x2160:rate=10:duration=0.8",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.8"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an"]
    cmd.append(str(source))
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    return source


def test_publish_real_source_locked_pass_identity_copy(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """REAL source-locked PASS: candidate is a byte-identical copy of the
    approved artifact — every T04A probe (dims/fps/frames/digests/audio/
    provenance) is measured and PASSes; publication completes once."""
    import app.services.s12_export.publication as pubmod
    import shutil

    from app.services.s12_export.validation import sha256_file  # noqa: PLC0415

    factory, svc, manifest_id, dirs = env
    source = _real_source(tmp_path)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    run, _job, _ = submit_export_job(
        svc,
        **base._submit_kwargs(
            factory, manifest_id, dirs,
            source_path=str(source),
            fps=10.0, fps_num=10, fps_den=1, frame_count=8,
            expected_sha256=sha256_file(source),
        ),
    )
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-real")
        s.commit()
    scratch = Path(dirs["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    candidate = scratch / "candidate_final.mp4"
    shutil.copyfile(source, candidate)
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 8,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "profile_codec": "h264",
        "source_path": str(source),
        "expected_sha256": sha256_file(source),
    }
    with factory() as s:
        out = pubmod.publish_export_run(
            s,
            run_id=run.id,
            workspace_id=WS,
            project_id=f"p-{WS}",
            worker_id="worker-real",
            fence_token=lease.fence_token,
            manifest=manifest,
        )
        s.commit()
    assert out["status"] == "completed"
    assert out["verdict"] == "PASS"
    checks = {p["name"]: p["verdict"] for p in out["probes"]}
    assert all(v == "PASS" for v in checks.values()), checks
    monkeypatch.undo()


def _reencode_for(src: Path, dst: Path, *, reverse: bool = False) -> Path:
    """Real lossy x264 re-encode of *src* (same raster) — the legit
    re-render path; ``reverse`` reverses frame order (tamper)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (PSNR row needs the real binary)")
    vf = "reverse" if reverse else "null"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-an",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    return dst


def test_publish_psnr_legit_reencode_passes(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """C26 lan cuoi: legit re-encoded export → frame_match_mode=psnr with the
    documented per-profile threshold → REAL validator PASSes."""
    import app.services.s12_export.publication as pubmod
    import shutil

    factory, svc, manifest_id, dirs = env
    source = _real_source(tmp_path)
    candidate_file = _reencode_for(source, tmp_path / "reec.mp4")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    run, _job, _ = submit_export_job(
        svc,
        **base._submit_kwargs(
            factory, manifest_id, dirs,
            source_path=str(source),
            fps=10.0, fps_num=10, fps_den=1, frame_count=8,
        ),
    )
    assert run.profile_id == "master-4k-h264"
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-psnr")
        s.commit()
    scratch = Path(dirs["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate_file, scratch / "candidate_final.mp4")
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 8,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "profile_codec": "h264",
        "source_path": str(source),
    }
    with factory() as s:
        out = pubmod.publish_export_run(
            s,
            run_id=run.id,
            workspace_id=WS,
            project_id=f"p-{WS}",
            worker_id="worker-psnr",
            fence_token=lease.fence_token,
            manifest=manifest,
        )
        s.commit()
    assert out["status"] == "completed"
    assert out["verdict"] == "PASS"
    checks = {p["name"]: p["verdict"] for p in out["probes"]}
    assert all(v == "PASS" for v in checks.values()), checks
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "completed"
    monkeypatch.undo()


def test_publish_real_wrong_audio_fails_and_cleans_private_candidate(
    env, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """A real equal-duration wrong-tone candidate cannot complete publication."""
    import shutil
    import subprocess

    import app.services.s12_export.publication as pubmod

    factory, svc, manifest_id, dirs = env
    source = _real_source(tmp_path, audio=True)
    wrong = tmp_path / "wrong_audio.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    completed = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100:duration=0.8",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-shortest", str(wrong),
        ],
        capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-400:]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    run, _job, _ = submit_export_job(
        svc,
        **base._submit_kwargs(
            factory, manifest_id, dirs,
            source_path=str(source), fps=10.0, fps_num=10, fps_den=1,
            frame_count=8,
        ),
    )
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-wrong-audio")
        s.commit()
    scratch = Path(dirs["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wrong, scratch / "candidate_final.mp4")
    manifest = {
        "fps": 10.0, "fps_num": 10, "fps_den": 1, "frame_count": 8,
        "chunk_dir": dirs["chunk"], "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"], "profile_codec": "h264",
        "source_path": str(source),
    }
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pubmod.publish_export_run(
                s, run_id=run.id, workspace_id=WS, project_id=f"p-{WS}",
                worker_id="worker-wrong-audio", fence_token=lease.fence_token,
                manifest=manifest,
            )
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "failed"
    assert not Path(dirs["output"]).exists()
    assert not list(scratch.iterdir())
    print(
        "S12_PUBLICATION_R01_ROOT",
        tmp_path,
        "source=",
        source,
        "wrong=",
        wrong,
        "scratch=",
        scratch,
        "output=",
        dirs["output"],
    )
    monkeypatch.undo()


def test_publish_psnr_reorder_tamper_fails(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Reordered content drops PSNR below any sane threshold → FAIL closed,
    run failed, no public artifact."""
    import app.services.s12_export.publication as pubmod
    import shutil

    factory, svc, manifest_id, dirs = env
    source = _real_source(tmp_path)
    tampered = _reencode_for(source, tmp_path / "tampered.mp4", reverse=True)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    run, _job, _ = submit_export_job(
        svc,
        **base._submit_kwargs(
            factory, manifest_id, dirs,
            source_path=str(source),
            fps=10.0, fps_num=10, fps_den=1, frame_count=8,
        ),
    )
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-psnr")
        s.commit()
    scratch = Path(dirs["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tampered, scratch / "candidate_final.mp4")
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 8,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "profile_codec": "h264",
        "source_path": str(source),
    }
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pubmod.publish_export_run(
                s,
                run_id=run.id,
                workspace_id=WS,
                project_id=f"p-{WS}",
                worker_id="worker-psnr",
                fence_token=lease.fence_token,
                manifest=manifest,
            )
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "failed"
    assert not Path(dirs["output"]).exists()
    monkeypatch.undo()


def test_frame_match_threshold_missing_fails_closed() -> None:  # type: ignore[no-untyped-def]
    """Re-encode profile WITHOUT a documented PSNR threshold → psnr mode with
    threshold None — the T04A validator fails closed (never a default)."""
    from types import SimpleNamespace

    run = SimpleNamespace(
        profile_id="ghost-profile",
        profile_dims="3840x2160",
        profile_codec="h264",
    )
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 8,
        "source_path": "/nonexistent/source.mp4",
        "chunk_dir": "/tmp/c",
        "scratch_dir": "/tmp/s",
        "output_path": "/tmp/o.mp4",
        "profile_codec": "h264",
    }
    mode, threshold = pub._frame_match(run, manifest, candidate_sha="a" * 64)
    assert mode == "psnr"
    assert threshold is None
    expectation = pub._expectation_for(run, manifest, candidate_sha="a" * 64)
    assert expectation.frame_match_mode == "psnr"
    assert expectation.frame_psnr_min_db is None


def _upscale_candidate(src: Path, dst: Path, *, reverse: bool = False) -> Path:
    """Real scale+pad letterbox re-encode to 4K (the product upscale path)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (upscale row needs the real binary)")
    vf = (
        "scale=3840:2160:force_original_aspect_ratio=decrease,"
        "pad=3840:2160:(ow-iw)/2:(oh-ih)/2,reverse"
        if reverse
        else "scale=3840:2160:force_original_aspect_ratio=decrease,"
        "pad=3840:2160:(ow-iw)/2:(oh-ih)/2"
    )
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    return dst


def _letterbox_source(tmp_path: Path) -> Path:
    """Real 4:3 320x240 source, 30 frames @ 10fps (non-16:9 letterbox case)."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (letterbox row needs the real binary)")
    source = tmp_path / "src_43.mp4"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=3.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
        str(source),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    return source


def test_publish_psnr_upscale_letterbox_30of30_passes(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """F11-T06B-02 final: cross-raster upscale + letterbox candidate PASSes
    30/30 frames — reference raster (server-probed) drives the product
    letterbox compare in the REAL validator."""
    import app.services.s12_export.publication as pubmod
    import shutil

    factory, svc, manifest_id, dirs = env
    source = _letterbox_source(tmp_path)  # 320x240 4:3, 30 frames
    candidate_file = _upscale_candidate(source, tmp_path / "cand_4k.mp4")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    run, _job, _ = submit_export_job(
        svc,
        **base._submit_kwargs(
            factory, manifest_id, dirs,
            source_path=str(source),
            fps=10.0, fps_num=10, fps_den=1, frame_count=30,
        ),
    )
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-upscale")
        s.commit()
    scratch = Path(dirs["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate_file, scratch / "candidate_final.mp4")
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 30,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "profile_codec": "h264",
        "source_path": str(source),
    }
    # Reference raster must be server-probed from the approved artifact.
    exp_ref = pub._build_source_reference(manifest, 10, 1)
    assert (exp_ref.reference_width, exp_ref.reference_height) == (320, 240)
    with factory() as s:
        out = pubmod.publish_export_run(
            s,
            run_id=run.id,
            workspace_id=WS,
            project_id=f"p-{WS}",
            worker_id="worker-upscale",
            fence_token=lease.fence_token,
            manifest=manifest,
        )
        s.commit()
    assert out["status"] == "completed"
    assert out["verdict"] == "PASS"
    order = next(p for p in out["probes"] if p["name"] == "frame_order")
    assert "30 frames" in order["detail"] or "PSNR" in order["detail"], order
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "completed"
    monkeypatch.undo()


def test_publish_psnr_upscale_reorder_fails(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Reordered upscale candidate FAILs under the same cross-raster PSNR
    path — content authority is real, tolerance never waives tamper."""
    import app.services.s12_export.publication as pubmod
    import shutil

    factory, svc, manifest_id, dirs = env
    source = _letterbox_source(tmp_path)
    tampered = _upscale_candidate(source, tmp_path / "tamper_4k.mp4", reverse=True)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    run, _job, _ = submit_export_job(
        svc,
        **base._submit_kwargs(
            factory, manifest_id, dirs,
            source_path=str(source),
            fps=10.0, fps_num=10, fps_den=1, frame_count=30,
        ),
    )
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-upscale")
        s.commit()
    scratch = Path(dirs["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tampered, scratch / "candidate_final.mp4")
    manifest = {
        "fps": 10.0,
        "fps_num": 10,
        "fps_den": 1,
        "frame_count": 30,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "profile_codec": "h264",
        "source_path": str(source),
    }
    with factory() as s:
        with pytest.raises(pub.PublicationError):
            pubmod.publish_export_run(
                s,
                run_id=run.id,
                workspace_id=WS,
                project_id=f"p-{WS}",
                worker_id="worker-upscale",
                fence_token=lease.fence_token,
                manifest=manifest,
            )
        s.rollback()
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "failed"
    assert not Path(dirs["output"]).exists()
    monkeypatch.undo()
