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
        "fps": 30.0,
        "fps_num": 30,
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
