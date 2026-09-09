"""S12-T03C C2 — C22-part backend: scoped result playback/download.

Artifact path DERIVED from the server-owned project/video export context
(same derivation as submit); metadata/media served ONLY for ``completed``
runs owned by the request scope. Missing/tampered/partial artifacts and
pending/failed runs fail closed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.routes import s12_export as route

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_c1_closure as t1c  # noqa: E402

WS = t1c.WS
FPS = t1c.FPS
FRAMES = t1c.FRAMES
CHK_HASH = t1c.CHK_HASH
PLAN_ID = t1c.PLAN_ID
PLAN_HASH = t1c.PLAN_HASH
_authority_body = t1c._authority_body
_ready = t1c._ready
_manifest_doc = t1c._manifest_doc


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Same isolated lineage as test_c1_closure (planned duplication)."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.structural_lock import StructuralLockRepository
    from app.workflow.job_service import JobService

    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
    db = tmp_path / "t03c-c22.db"
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")
    factory = create_session_factory(create_engine_for_path(db))
    managed = tmp_path / "managed"
    managed.mkdir()
    with factory() as seed:
        seed.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        seed.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
            {"p": f"p-{WS}", "w": WS},
        )
        seed.execute(
            text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"),
            {"v": f"v-{WS}", "p": f"p-{WS}"},
        )
        seed.execute(
            text("INSERT INTO character(id,workspace_id,name,code) VALUES ('ch-a',:w,'H','h-a')"),
            {"w": WS},
        )
        seed.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
                " VALUES ('pv-a','ch-a',:w,1,'published')"
            ),
            {"w": WS},
        )
        seed.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) VALUES ('rl-a',:w,:p,:v,'g','C','character','confirmed')"
            ),
            {"w": WS, "p": f"p-{WS}", "v": f"v-{WS}"},
        )
        seed.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,cast_mapping_id,"
                "character_id,pack_version_id,params_json,idempotency_key,revision) VALUES ('rc-a',:w,:p,"
                "'rl-a',NULL,'ch-a','pv-a','{}',NULL,1)"
            ),
            {"w": WS, "p": f"p-{WS}"},
        )
        seed.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                "reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,"
                "snapshot_json,checkpoint_hash,note,idempotency_key,revision)"
                " VALUES ('ac-a',:w,:p,'rc-a',1,'[]','[]','tb','{}',:h,NULL,NULL,1)"
            ),
            {"w": WS, "p": f"p-{WS}", "h": CHK_HASH},
        )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(
                WS, f"p-{WS}", f"v-{WS}", "gen1", t1c._manifest_doc()
            )
            s2.commit()
            manifest_id = m1.id
        svc = JobService(factory, managed_root=managed)
        auth = _seed_authority(s2, factory, managed)
    dirs = {
        "chunk": str(tmp_path / "chunks"),
        "scratch": str(tmp_path / "scratch"),
        "output": str(tmp_path / "out.mp4"),
    }
    yield factory, svc, manifest_id, auth, dirs, managed
    engine = create_engine_for_path(db)
    engine.dispose()


def _seed_authority(session: Any, factory: Any, managed: Path) -> dict[str, str]:
    from sqlalchemy import text  # noqa: PLC0415

    sys.path.insert(0, str(PROJECT_ROOT / "tests" / "s12" / "s12-t01"))
    from test_preflight_contract import _seed_s10_authority  # noqa: PLC0415

    auth = _seed_s10_authority(
        session,
        ws=WS,
        pid=f"p-{WS}",
        vid=f"v-{WS}",
        ckpt={
            "checkpoint_id": "ac-a",
            "checkpoint_hash": CHK_HASH,
            "checkpoint_revision": 1,
        },
        frame_count=FRAMES,
        fps_num=FPS,
        fps_den=1,
    )
    source = managed / "apply" / f"{auth['artifact_id']}.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"0" * 1024)
    with factory() as s:
        s.execute(
            text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"),
            {"rel": str(source.relative_to(managed)).replace("\\", "/"), "aid": auth["artifact_id"]},
        )
        s.commit()
    return auth


def _complete_export_at_server_path(factory, svc, managed, auth, manifest_id, mp, payload: bytes) -> str:
    """Route submit (ready patch) then a REAL fenced publication whose
    artifact lands at the server-derived output path (C22 context)."""
    from app.persistence.s12_export import S12ExportRepository as Repo
    from app.services.s12_export import publication as pubmod

    _ready(mp)
    mp.setattr(route, "get_job_service", lambda: svc)
    mp.setattr(route, "get_managed_root", lambda: managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as s:
        out = route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.commit()
    run_id = out["run_id"]
    paths = route._server_paths(str(managed), f"p-{WS}", f"v-{WS}")
    scratch = Path(paths["scratch_dir"])
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "candidate_final.mp4").write_bytes(payload)
    with factory() as s:
        lease = Repo(s).claim_run(run_id, "worker-res")
        s.commit()
        fence = lease.fence_token
    mp.setattr(pubmod, "_require_ready", lambda session, **kw: None)
    mp.setattr(
        "app.services.s12_export.validation.validate",
        lambda path, exp: SimpleNamespace(
            verdict="PASS",
            probes=(SimpleNamespace(name="p", verdict="PASS", detail=""),),
        ),
    )
    manifest = {
        "fps": float(FPS),
        "fps_num": FPS,
        "fps_den": 1,
        "frame_count": FRAMES,
        "chunk_dir": paths["chunk_dir"],
        "scratch_dir": paths["scratch_dir"],
        "output_path": paths["output_path"],
        "profile_codec": "h264",
        "expected_sha256": "",
    }
    with factory() as s:
        pubmod.publish_export_run(
            s,
            run_id=run_id,
            workspace_id=WS,
            project_id=f"p-{WS}",
            worker_id="worker-res",
            fence_token=fence,
            manifest=manifest,
        )
        s.commit()
    return run_id


def test_c22_result_metadata_served_when_completed(env) -> None:  # type: ignore[no-untyped-def]
    """Completed + owned run → metadata with server-owned media URL."""
    factory, svc, manifest_id, auth, dirs, managed = env
    mp = pytest.MonkeyPatch()
    run_id = _complete_export_at_server_path(
        factory, svc, managed, auth, manifest_id, mp, b"0" * 2048
    )
    with factory() as s:
        meta = route.export_result(run_id, s, workspace_id=WS, project_id=None)
    assert meta["run_id"] == run_id
    assert meta["status"] == "completed"
    assert meta["filename"] == "export_master.mp4"
    assert meta["mime"] == "video/mp4"
    assert meta["media_url"] == f"/s12-exports/{run_id}/media"
    assert meta["size_bytes"] == 2048
    with factory() as s:
        resp = route.export_media(run_id, s, workspace_id=WS, project_id=None)
    assert str(resp.path).endswith("export_master.mp4")
    mp.undo()


def test_c22_media_serves_playable_bytes(env) -> None:  # type: ignore[no-untyped-def]
    """media returns the exact public artifact bytes (playable download)."""
    factory, svc, manifest_id, auth, dirs, managed = env
    payload = bytes(range(256)) * 4
    mp = pytest.MonkeyPatch()
    run_id = _complete_export_at_server_path(factory, svc, managed, auth, manifest_id, mp, payload)
    with factory() as s:
        resp = route.export_media(run_id, s, workspace_id=WS, project_id=None)
    with open(resp.path, "rb") as handle:
        assert handle.read() == payload
    assert resp.media_type == "video/mp4"
    mp.undo()


def test_c22_result_denied_before_completion(env) -> None:  # type: ignore[no-untyped-def]
    """Pending/failed runs are never served (409, no media)."""
    from fastapi import HTTPException

    factory, svc, manifest_id, auth, dirs, managed = env
    mp = pytest.MonkeyPatch()
    _ready(mp)
    mp.setattr(route, "get_job_service", lambda: svc)
    mp.setattr(route, "get_managed_root", lambda: managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as s:
        out = route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.commit()
    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.export_result(out["run_id"], s, workspace_id=WS, project_id=None)
        s.rollback()
    assert exc.value.status_code == 409
    with factory() as s:
        with pytest.raises(HTTPException) as exc2:
            route.export_media(out["run_id"], s, workspace_id=WS, project_id=None)
        s.rollback()
    assert exc2.value.status_code == 409
    mp.undo()


def test_c22_cross_project_denied(env) -> None:  # type: ignore[no-untyped-def]
    """Wrong project scope → 404 even when the run is completed."""
    from fastapi import HTTPException

    factory, svc, manifest_id, auth, dirs, managed = env
    mp = pytest.MonkeyPatch()
    run_id = _complete_export_at_server_path(factory, svc, managed, auth, manifest_id, mp, b"x" * 512)
    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.export_result(run_id, s, workspace_id=WS, project_id="p-other")
        s.rollback()
    assert exc.value.status_code == 404
    mp.undo()


def test_c22_tampered_or_missing_never_served(env) -> None:  # type: ignore[no-untyped-def]
    """Tampered artifact (sidecar mismatch) and missing file fail closed."""
    from fastapi import HTTPException

    factory, svc, manifest_id, auth, dirs, managed = env
    mp = pytest.MonkeyPatch()
    run_id = _complete_export_at_server_path(factory, svc, managed, auth, manifest_id, mp, b"y" * 512)
    paths = route._server_paths(str(managed), f"p-{WS}", f"v-{WS}")
    artifact = Path(paths["output_path"])
    # Tamper: bytes change, sidecar unchanged → 403.
    artifact.write_bytes(b"tampered" * 64)
    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.export_media(run_id, s, workspace_id=WS, project_id=None)
        s.rollback()
    assert exc.value.status_code == 403
    # Missing artifact → 404.
    artifact.unlink()
    with factory() as s:
        with pytest.raises(HTTPException) as exc2:
            route.export_result(run_id, s, workspace_id=WS, project_id=None)
        s.rollback()
    assert exc2.value.status_code == 404
    mp.undo()
