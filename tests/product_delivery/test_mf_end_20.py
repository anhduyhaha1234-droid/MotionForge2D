"""MF-END-20 tests — shot render cache / resume / cancel / retry safety.

Rows (binary; the scripted engine stands at the ENGINE BOUNDARY like the
MF-END-19 pattern — production code is not mocked):

* 20.1 content key: source/span/cast/input/graph/model/params — deterministic,
  refuses incomplete pins; receipts pin the managed artifact (DB row + sidecar).
* 20.2 restart BEFORE/AFTER submit + BEFORE/AFTER publication: a spent submit
  epoch never re-POSTs, an explicit retry supersedes it, the winner pins once,
  and the replay path never duplicates a POST or a publication.
* 20.3 cancel: rows are kept (all-row counts), the late output is never pinned
  and never published; retry follows the attempt lifecycle.
* 20.4 invalidation per shot / per dependent component seam (other shots keep
  their exact hashes); recompute reopen_state (all rows, bounded joins) and
  preservation_report (shot khác hash giữ); Windows long-path probe at the
  REAL managed root.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services import s10_recompute as rec
from app.services.renderer_routes.composite import (
    canonical_frame_sha256,
    decode_rgb_frames,
    write_frames_mp4,
)
from app.services.shot_reskin_cache import (
    ShotCacheRefusal,
    ShotCacheRefusalCode,
    ShotReskinCache,
    _long_path,
    run_cached_shot_render,
    shot_content_key,
    shot_key_texture,
)
from app.workflow import s10_full_apply_jobs as jobs

WT = Path(__file__).resolve().parents[2]
GRAPH_REL = "app/media_workflows/wan_shot_v1.json"
WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"
#: Real managed root of this task's run area (env-overridable) — the
#: long-path probe must run on a REAL absolute managed root, never a
#: synthetic short pytest tmp path.
_PROBE_MANAGED_ROOT_ENV = "MF_END20_PROBE_MANAGED_ROOT"
_DEFAULT_PROBE_MANAGED_ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-20/managed"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_mp4(path: Path, frames: int, *, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = []
    for i in range(frames):
        f = np.zeros((48, 64, 3), dtype=np.uint8)
        f[:, :, 0] = (int(seed) + i * 3) % 255
        f[:, :, 1] = 60
        f[:, :, 2] = 200
        arr.append(f)
    write_frames_mp4(arr, path, fps=30.0)
    return path


def _db(tmp_path: Path, name: str = "mf20.db") -> Any:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE artifact(id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT,"
                " relative_path TEXT, state TEXT, sha256 TEXT, size_bytes INTEGER,"
                " revision INTEGER)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE s10_full_apply_chunk(id TEXT PRIMARY KEY, workspace_id TEXT,"
                " run_id TEXT, shot_id TEXT, layer_id TEXT, order_index INTEGER,"
                " chunk_index INTEGER, core_start_frame INTEGER, core_end_frame INTEGER,"
                " state TEXT, verified INTEGER, attempt INTEGER, artifact_id TEXT,"
                " content_hash TEXT, overlap_before INTEGER, overlap_after INTEGER,"
                " natural_key TEXT, revision INTEGER)"
            )
        )
    return sessionmaker(bind=engine)


# ── 20.1 — content key + receipt pin ─────────────────────────────────────────


def _request(**over: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "workspace_id": "default",
        "project_id": "proj-1",
        "video_id": "vid-1",
        "shot_id": "BOOK",
        "chunk_id": "ck_0001",
        "attempt_id": "shot-mf20-0001",
        "backend": {
            "backend": "comfy_shot_engine",
            "profile_id": WAN_PROFILE,
            "capability": "source_video_motion_transfer",
            "graph_file": GRAPH_REL,
            "graph_sha256": "a" * 64,
            "output_node": "246",
            "seed": 582699151003550,
        },
        "graph": {"file": GRAPH_REL, "file_sha256": "a" * 64},
        "parameters": {"prompt": "a seated reader, opener book", "filename_prefix": "mf20/x"},
        "staged_inputs": {
            "anchor": {"relative_path": "anchor/a.png", "sha256": "b" * 64}
        },
        "anchor": {"relative_path": "anchor/a.png", "sha256": "b" * 64},
        "cast": [
            {
                "role": "BOOK-P1",
                "character_id": "ch-book",
                "pack_version_id": "pv1",
                "references": [{"key": "BOOK-P1@base", "sha256": "c" * 64}],
            }
        ],
        "source": {
            "artifact_id": "art-src",
            "sha256": "d" * 64,
            "relative_path": "src/source.mp4",
            "size_bytes": 1234,
            "fps": {"num": 30, "den": 1},
            "span": {"start_frame": 0, "end_frame_exclusive": 10},
        },
        "output_contract": {
            "width": 640,
            "height": 368,
            "fps_num": 30,
            "fps_den": 1,
            "frame_count": 10,
            "container": "mp4",
            "video_codec": "h264",
            "audio": {"mode": "source_remux", "source_artifact_id": "art-src"},
        },
    }
    request.update(over)
    return request


def _result(path: Path, rel: str | None = None, **over: Any) -> dict[str, Any]:
    frames = decode_rgb_frames(path)
    out: dict[str, Any] = {
        "output_relative_path": str(rel or path.name),
        "output_sha256": _sha_file(path),
        "output_size_bytes": path.stat().st_size,
        "decoded_sha256": canonical_frame_sha256(frames),
        "decoded_frame_count": len(frames),
        "fps_num": 30,
        "fps_den": 1,
        "prompt_id": "pid-mf20-1",
        "graph_object_sha256_submitted": "e" * 64,
    }
    out.update(over)
    return out


def test_mf20_1_content_key_covers_all_components() -> None:
    base = _request()
    key = shot_content_key(base)
    assert key == shot_content_key(_request())  # deterministic
    texture = shot_key_texture(base)
    assert sorted(texture) == ["cast", "graph", "input", "model", "params", "source", "span"]
    variants = {
        "source": {"source": {**base["source"], "sha256": "f" * 64}},
        "span": {
            "source": {**base["source"], "span": {"start_frame": 1, "end_frame_exclusive": 10}}
        },
        "cast": {"cast": [{"role": "BOOK-P1", "character_id": "ch-other", "pack_version_id": "pv1",
                           "references": [{"key": "k", "sha256": "c" * 64}]}]},
        "input": {"anchor": {"relative_path": "anchor/a.png", "sha256": "9" * 64}},
        "graph": {"graph": {"file": GRAPH_REL, "file_sha256": "1" * 64}},
        "model": {"backend": {**base["backend"], "profile_id": "other_profile"}},
        "params": {"parameters": {"prompt": "different", "filename_prefix": "mf20/x"}},
    }
    for name, over in variants.items():
        changed = _request(**over)
        assert shot_content_key(changed) != key, f"component {name} must affect the key"
        # exactly that component's texture digest moved
        moved = [c for c in texture if shot_key_texture(changed)[c] != texture[c]]
        assert moved == [name], (name, moved)


def test_mf20_1_key_refuses_incomplete_pins() -> None:
    bad = _request()
    bad["source"] = {**bad["source"], "sha256": ""}
    with pytest.raises(ShotCacheRefusal) as exc:
        shot_content_key(bad)
    assert exc.value.code is ShotCacheRefusalCode.SHOT_CACHE_KEY_INVALID
    bad2 = _request()
    bad2["graph"] = {"file": "", "file_sha256": ""}
    bad2["backend"] = {**bad2["backend"], "graph_file": "", "graph_sha256": ""}
    with pytest.raises(ShotCacheRefusal):
        shot_content_key(bad2)


def test_mf20_1_receipt_pins_managed_artifact_and_sidecar(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    outcome = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    assert outcome["cache_hit"] is False and calls == ["post"]
    receipt = outcome["receipt"]
    assert receipt["output_sha256"] == _sha_file(out)
    assert receipt["output_size_bytes"] == out.stat().st_size
    assert int(receipt["decoded_frame_count"]) == 10
    # the sidecar is a managed-root artifact whose sha is pinned in the row
    sidecar = managed / str(receipt["receipt_rel_path"])
    assert sidecar.is_file()
    assert _sha_file(sidecar) == str(receipt["receipt_file_sha256"])
    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_doc["output_sha256"] == receipt["output_sha256"]
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        live = cache.lookup(workspace_id="default", content_key=str(receipt["content_key"]))
        assert live is not None and live["state"] == "valid"


# ── 20.2 — restart before/after submit; winner/identity; no duplicate ────────


def test_mf20_2_restart_before_submit_reuses_the_prepared_attempt(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        first = cache.begin_attempt(workspace_id="default", request=_request(), run_id="run-1")
        second = cache.begin_attempt(workspace_id="default", request=_request(), run_id="run-1")
        assert first["action"] == second["action"] == "submit"
        assert second["resumed"] is True
        assert first["attempt"]["attempt_row_id"] == second["attempt"]["attempt_row_id"]
        s.commit()
    # the restart resumes the same prepared attempt: exactly ONE engine POST
    outcome = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    assert outcome["cache_hit"] is False and calls == ["post"]
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["total"] == 1
        assert state["attempts"]["by_state"] == {"completed": 1}


def test_mf20_2_restart_after_submit_is_in_doubt_and_does_not_repost(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        begin = cache.begin_attempt(workspace_id="default", request=_request(), run_id="run-1")
        assert cache.mark_submitted(
            workspace_id="default", attempt_row_id=begin["attempt"]["attempt_row_id"]
        )
        s.commit()
    with pytest.raises(ShotCacheRefusal) as exc:
        run_cached_shot_render(
            session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
            request=_request(), render=render,
        )
    assert exc.value.code is ShotCacheRefusalCode.SHOT_CACHE_SUBMIT_IN_DOUBT
    assert calls == []  # a bare restart NEVER re-POSTs the in-doubt attempt
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["in_doubt"] == 1
        assert state["receipts"]["total"] == 0


def test_mf20_2_explicit_retry_supersedes_in_doubt_and_pins_the_winner(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        begin = cache.begin_attempt(workspace_id="default", request=_request(), run_id="run-1")
        cache.mark_submitted(
            workspace_id="default", attempt_row_id=begin["attempt"]["attempt_row_id"]
        )
        s.commit()
    outcome = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render, retry=True,
    )
    assert outcome["cache_hit"] is False and calls == ["post"]
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["by_state"] == {"superseded": 1, "completed": 1}
        assert state["receipts"]["total"] == 1
        attempt_2 = "shot-mf20-0001#2"
        assert state["winner_by_key"][str(outcome["content_key"])] == attempt_2
        assert state["ambiguous_keys"] == []


def test_mf20_2_late_output_of_superseded_attempt_is_dropped(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        begin = cache.begin_attempt(workspace_id="default", request=_request(), run_id="run-1")
        old_id = str(begin["attempt"]["attempt_row_id"])
        cache.mark_submitted(workspace_id="default", attempt_row_id=old_id)
        retry = cache.begin_attempt(
            workspace_id="default", request=_request(), run_id="run-1", retry=True
        )
        assert retry["superseded"]["state"] == "superseded"
        payload = cache.receipt_payload(
            request=_request(),
            result=_result(out, "engine_out/ck_0001_00001_.mp4"),
            attempt_row_id=old_id,
        )
        dropped = cache.complete_attempt(
            workspace_id="default", attempt_row_id=old_id, receipt_payload=payload
        )
        assert dropped["pinned"] is False and dropped["late_dropped"] is True
        assert dropped["reason"] == "superseded"
        s.commit()
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["late_dropped"] == 1
        assert state["receipts"]["total"] == 0  # the late output was never pinned


def test_mf20_2_replay_does_not_duplicate_post_or_rows(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    first = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        verdict = cache.replay(workspace_id="default", request=_request())
        assert verdict["hit"] is True and verdict["engine_post_required"] is False
        before = cache.status(workspace_id="default")
    replay = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    assert replay["cache_hit"] is True
    assert replay["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert calls == ["post"]  # exactly one engine POST across the replay
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        after = cache.status(workspace_id="default")
        assert after["attempts"] == before["attempts"]
        assert after["receipts"] == before["receipts"]
        assert after["attempts"]["total"] == 1 and after["receipts"]["total"] == 1


def test_mf20_2_publication_guard_blocks_drifted_receipt_bytes(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=lambda: _result(out, "engine_out/ck_0001_00001_.mp4"),
    )
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        guard = cache.assert_run_receipts_live(workspace_id="default", run_id="run-1")
        assert guard["checked"] == 1 and guard["live"] == 1
        # tamper the pinned artifact AFTER the receipt was pinned
        original = out.read_bytes()
        out.write_bytes(b"drifted-bytes")
        with pytest.raises(ShotCacheRefusal) as exc:
            cache.assert_run_receipts_live(workspace_id="default", run_id="run-1")
        assert exc.value.code is ShotCacheRefusalCode.SHOT_CACHE_REPLAY_ARTIFACT_STALE
        # a lookup also refuses to serve drifted bytes and invalidates the receipt
        assert (
            cache.lookup(workspace_id="default", content_key=shot_content_key(_request()))
            is None
        )
        out.write_bytes(original)
        s.commit()
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        receipt = cache._load_receipt("default", shot_content_key(_request()))
        assert receipt is not None and receipt["state"] == "invalidated"


def test_mf20_2_publication_replay_does_not_duplicate(tmp_path: Path) -> None:
    """Replaying the same (run, stitch bytes) yields ONE completed publication."""
    from alembic import command
    from alembic.config import Config

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.s10_full_apply import S10ApplyRepository

    db = tmp_path / "pub.db"
    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")
    sf = create_session_factory(create_engine_for_path(db))
    managed = tmp_path / "managed"
    stitch = _write_mp4(managed / "stitch" / "full.mp4", 10, seed=5)
    stitch_sha = _sha_file(stitch)
    cp_hash = "a" * 64
    with sf() as s:
        s.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES ('default','default')"))
        s.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p1','default','Proj')")
        )
        s.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)"
            )
        )
        s.execute(
            text(
                "INSERT INTO character(id,workspace_id,name,code) VALUES"
                " ('ch1','default','hero','hero1')"
            )
        )
        s.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
                " VALUES ('pv1','ch1','default',1,'published')"
            )
        )
        s.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                " source_generation,name,kind,status) VALUES"
                " ('r1','default','p1','v1','1','role','character','confirmed')"
            )
        )
        s.execute(
            text(
                "INSERT INTO reskin_config(id, workspace_id, project_id, object_role_id,"
                " character_id, pack_version_id, params_json, revision) VALUES"
                " ('rc1','default','p1','r1','ch1','pv1','{}',1)"
            )
        )
        s.execute(
            text(
                "INSERT INTO apply_checkpoint(id, workspace_id, project_id, reskin_config_id,"
                " reskin_config_revision, pack_version_ids_json, loop_hashes_json,"
                " timebase_fingerprint, snapshot_json, checkpoint_hash, revision, created_at,"
                " updated_at) VALUES ('cp1','default','p1','rc1',1,'[]','[]','30/1','{}',:h,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"h": cp_hash},
        )
        s.execute(
            text(
                "INSERT INTO s10_full_apply_run(id, workspace_id, project_id, video_item_id,"
                " apply_checkpoint_id, apply_checkpoint_hash, apply_checkpoint_revision, plan_id,"
                " plan_hash, status, frame_count, fps_num, fps_den, chunk_config_json, attempt,"
                " revision, created_at, updated_at) VALUES"
                " ('run-1','default','p1','v1','cp1',:h,1,:pid,:ph,'completed',10,30,1,'{}',1,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"h": cp_hash, "pid": "c" * 64, "ph": "b" * 64},
        )
        s.execute(
            text(
                "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256,"
                " size_bytes, revision) VALUES"
                " ('art-stitch','default','video','stitch/full.mp4','ready',:sha,:sz,1)"
            ),
            {"sha": stitch_sha, "sz": stitch.stat().st_size},
        )
        s.commit()
        repo = S10ApplyRepository(s)
        content_hash = hashlib.sha256(f"pub:run-1:{stitch_sha}".encode()).hexdigest()
        pub1, created1 = repo.create_publication(
            "default", "run-1", "art-stitch", content_hash, 10, {"frame_count": 10},
            "cp1", cp_hash, 1, state="completed",
        )
        pub2, created2 = repo.create_publication(
            "default", "run-1", "art-stitch", content_hash, 10, {"frame_count": 10},
            "cp1", cp_hash, 1, state="completed",
        )
        s.commit()
        assert created1 is True and created2 is False
        assert pub1.id == pub2.id
        assert len(repo.list_publications("default", "run-1")) == 1


# ── 20.3 — cancel safety + retry lifecycle ───────────────────────────────────


def test_mf20_3_cancel_keeps_all_rows_and_withholds_late_output(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        begin = cache.begin_attempt(workspace_id="default", request=_request(), run_id="run-1")
        row_id = str(begin["attempt"]["attempt_row_id"])
        cache.mark_submitted(workspace_id="default", attempt_row_id=row_id)
        assert cache.cancel_attempt(
            workspace_id="default", attempt_row_id=row_id, detail="user cancel"
        )
        # cancel NEVER deletes bookkeeping (no slot/lease loss)
        assert cache.cancel_attempt(workspace_id="default", attempt_row_id=row_id) is False
        payload = cache.receipt_payload(
            request=_request(),
            result=_result(out, "engine_out/ck_0001_00001_.mp4"),
            attempt_row_id=row_id,
        )
        late = cache.complete_attempt(
            workspace_id="default", attempt_row_id=row_id, receipt_payload=payload
        )
        assert late["pinned"] is False and late["reason"] == "cancelled"
        s.commit()
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["total"] == 1
        assert state["attempts"]["by_state"] == {"cancelled": 1}
        assert state["attempts"]["late_dropped"] == 1
        assert state["receipts"]["total"] == 0
        status = cache.status(workspace_id="default")
        assert status["attempts"]["total"] == 1 and status["receipts"]["total"] == 0


def test_mf20_3_cancel_during_render_withholds_the_pin(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []
    cancelled = {"flag": False}

    def render() -> dict[str, Any]:
        calls.append("post")
        cancelled["flag"] = True
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    with pytest.raises(ShotCacheRefusal) as exc:
        run_cached_shot_render(
            session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
            request=_request(), render=render, is_cancelled=lambda: cancelled["flag"],
        )
    assert exc.value.code is ShotCacheRefusalCode.SHOT_CACHE_ATTEMPT_CANCELLED
    assert calls == ["post"]
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["by_state"] == {"cancelled": 1}
        assert state["receipts"]["total"] == 0


def test_mf20_3_retry_after_failed_attempt_follows_the_lifecycle(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    def boom() -> dict[str, Any]:
        raise RuntimeError("engine exploded")

    with pytest.raises(RuntimeError):
        run_cached_shot_render(
            session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
            request=_request(), render=boom,
        )
    outcome = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    assert outcome["cache_hit"] is False and calls == ["post"]
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["by_state"] == {"failed": 1, "completed": 1}
        assert state["receipts"]["total"] == 1


# ── 20.4 — invalidation seams ────────────────────────────────────────────────


def _two_shot_receipts(tmp_path: Path, sf: Any, managed: Path) -> dict[str, Any]:
    out_book = _write_mp4(managed / "engine_out" / "ck_book_00001_.mp4", 10, seed=3)
    out_turn = _write_mp4(managed / "engine_out" / "ck_turn_00001_.mp4", 10, seed=9)
    book_req = _request()
    turn_req = _request(
        shot_id="TURN",
        chunk_id="ck_turn",
        attempt_id="shot-mf20-turn",
        cast=[
            {
                "role": "TURN-P1",
                "character_id": "ch-turn",
                "pack_version_id": "pv2",
                "references": [{"key": "TURN-P1@base", "sha256": "8" * 64}],
            }
        ],
    )
    book = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=book_req, render=lambda: _result(out_book, "engine_out/ck_book_00001_.mp4"),
    )
    turn = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=turn_req, render=lambda: _result(out_turn, "engine_out/ck_turn_00001_.mp4"),
    )
    return {"book": book, "turn": turn, "book_req": book_req, "turn_req": turn_req}


def test_mf20_4_invalidate_shot_keeps_other_shots_receipts(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    fx = _two_shot_receipts(tmp_path, sf, managed)
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        count = cache.invalidate_shot(
            workspace_id="default", shot_id="BOOK", reason="qc retry BOOK"
        )
        assert count == 1
        s.commit()
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        assert cache.lookup(
            workspace_id="default", content_key=shot_content_key(fx["book_req"])
        ) is None
        turn = cache.lookup(workspace_id="default", content_key=shot_content_key(fx["turn_req"]))
        assert turn is not None and turn["state"] == "valid"
        assert turn["output_sha256"] == fx["turn"]["receipt"]["output_sha256"]
        status = cache.status(workspace_id="default")
        assert status["receipts"]["by_state"] == {"invalidated": 1, "valid": 1}


def test_mf20_4_invalidate_component_is_a_dependent_seam(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    fx = _two_shot_receipts(tmp_path, sf, managed)
    book_texture = shot_key_texture(fx["book_req"])
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        # invalidating the BOOK cast digest does NOT touch the TURN receipt
        count = cache.invalidate_component(
            workspace_id="default",
            component="cast",
            digest=book_texture["cast"],
            reason="cast repack",
        )
        assert count == 1
        s.commit()
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        assert cache.lookup(
            workspace_id="default", content_key=shot_content_key(fx["book_req"])
        ) is None
        assert cache.lookup(
            workspace_id="default", content_key=shot_content_key(fx["turn_req"])
        ) is not None
        with pytest.raises(ShotCacheRefusal):
            cache.invalidate_component(
                workspace_id="default", component="not-a-component", digest="a" * 64, reason="x"
            )
        with pytest.raises(ShotCacheRefusal):
            cache.invalidate_component(
                workspace_id="default", component="cast", digest="zz", reason="x"
            )


def test_mf20_4_invalidated_receipt_rerenders_and_repins(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    out = _write_mp4(managed / "engine_out" / "ck_0001_00001_.mp4", 10, seed=3)
    calls: list[str] = []

    def render() -> dict[str, Any]:
        calls.append("post")
        return _result(out, "engine_out/ck_0001_00001_.mp4")

    run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        count = cache.invalidate_shot(
            workspace_id="default", shot_id="BOOK", reason="user redraw"
        )
        assert count == 1
        s.commit()
    outcome = run_cached_shot_render(
        session_factory=sf, managed_root=managed, workspace_id="default", run_id="run-1",
        request=_request(), render=render,
    )
    assert calls == ["post", "post"]  # invalidated -> a fresh render, then re-pinned
    assert outcome["cache_hit"] is False
    with sf() as s:
        cache = ShotReskinCache(s, managed_root=managed)
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["receipts"] == {"total": 1, "valid": 1}


# ── 20.4 — recompute reopen/retry/cancel race: all rows, bounded joins ───────


def _seed_recompute_rows(sf: Any, *, run_id: str, chunks: int, shots: tuple[str, ...]) -> list[str]:
    ids: list[str] = []
    with sf() as s:
        for i in range(chunks):
            cid = f"{run_id}-ck{i:02d}"
            ids.append(cid)
            s.execute(
                text(
                    "INSERT INTO s10_full_apply_chunk(id, workspace_id, run_id, shot_id, layer_id,"
                    " order_index, chunk_index, core_start_frame, core_end_frame, state, verified,"
                    " attempt, artifact_id, content_hash, natural_key) VALUES (:id,'default',:rid,"
                    ":shot,'layer_a',:oi,:oi,:cs,:ce,'completed',1,1,:aid,:ch,:nk)"
                ),
                {
                    "id": cid,
                    "rid": run_id,
                    "shot": shots[i % len(shots)],
                    "oi": i,
                    "cs": i * 10,
                    "ce": i * 10 + 9,
                    "aid": f"art-{cid}",
                    "ch": "a" * 64,
                    "nk": f"s10_chunk:{run_id}:{cid}",
                },
            )
        s.commit()
    return ids


def test_mf20_4_recompute_reopen_state_all_rows_bounded(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    ids = _seed_recompute_rows(sf, run_id="run-a", chunks=3, shots=("BOOK", "TURN"))
    with sf() as s:
        svc = rec.S10RecomputeService(s)
        s.execute(
            text(
                "INSERT INTO s10_recompute_record(id, workspace_id, project_id, run_id,"
                " correction_id, correction_kind, target_layer_ids_json, affected_chunk_ids_json,"
                " result_hash, provenance_json, attempt_before, attempt_after, revision_before,"
                " revision_after) VALUES ('r1','default','p1','run-a','corr-1',"
                "'mask','[\"layer_a\"]',"
                ":aff,'" + "b" * 64 + "','{}',1,2,1,2)"
            ),
            {"aff": json.dumps(ids[:2])},
        )
        s.execute(
            text(
                "INSERT INTO s10_recompute_record(id, workspace_id, project_id, run_id,"
                " correction_id, correction_kind, target_layer_ids_json, affected_chunk_ids_json,"
                " result_hash, provenance_json, attempt_before, attempt_after, revision_before,"
                " revision_after) VALUES ('r2','default','p1','run-a','corr-2',"
                "'z_order','[\"layer_a\"]',"
                ":aff,'" + "c" * 64 + "','{}',2,3,2,3)"
            ),
            {"aff": json.dumps([ids[2]])},
        )
        for cid in ids[:2]:
            s.execute(
                text(
                    "INSERT INTO s10_recompute_provenance(chunk_id, correction_id, workspace_id,"
                    " run_id, provenance_json) VALUES (:cid,'corr-1','default','run-a','{}')"
                ),
                {"cid": cid},
            )
        s.execute(
            text(
                "INSERT INTO s10_recompute_checkpoint(correction_id, workspace_id, run_id,"
                " next_index, executed_json, completed) VALUES"
                " ('corr-1','default','run-a',0,'[]',0)"
            )
        )
        s.commit()
        state = svc.reopen_state(workspace_id="default", run_id="run-a")
        assert state["chunks"]["total"] == 3
        assert state["chunks"]["by_state"] == {"completed": 3}
        assert state["corrections"] == {
            "total": 2,
            "kinds": {"mask": 1, "z_order": 1},
            "affected_total": 3,
        }
        assert state["checkpoints"] == {"total": 1, "completed": 0}
        assert state["provenance_links"] == 2
        assert state["rows_total"] == 3 + 2 + 1
        assert state["statements_used"] == state["statements_max"] == 3
        assert state["per_shot"] == {
            "BOOK": {"chunks": 2, "verified": 2},
            "TURN": {"chunks": 1, "verified": 1},
        }
        # idempotent reopen: the same read twice returns the identical snapshot
        assert svc.reopen_state(workspace_id="default", run_id="run-a") == state
        # a retry/cancel race mutation (chunk failed, checkpoint reset) is
        # reflected while every row stays counted
        s.execute(
            text("UPDATE s10_full_apply_chunk SET state='failed', verified=0 WHERE id=:c"),
            {"c": ids[2]},
        )
        s.commit()
        raced = svc.reopen_state(workspace_id="default", run_id="run-a")
        assert raced["chunks"]["total"] == 3
        assert raced["chunks"]["by_state"]["failed"] == 1
        assert raced["rows_total"] == state["rows_total"]
        assert raced["statements_used"] == 3
    # bounded: 30 chunks in another run still needs the same 3 statements
    _seed_recompute_rows(sf, run_id="run-b", chunks=30, shots=("BOOK",))
    with sf() as s:
        svc = rec.S10RecomputeService(s)
        big = svc.reopen_state(workspace_id="default", run_id="run-b")
        assert big["chunks"]["total"] == 30
        assert big["statements_used"] == 3


def test_mf20_4_recompute_preservation_report_keeps_other_shot_hashes(tmp_path: Path) -> None:
    sf = _db(tmp_path)
    managed = tmp_path / "managed"
    shots = {"shot-a1": "BOOK", "shot-a2": "BOOK", "shot-b1": "TURN"}
    shas: dict[str, str] = {}
    with sf() as s:
        svc = rec.S10RecomputeService(s)
        for i, (cid, shot) in enumerate(shots.items()):
            path = _write_mp4(managed / "s10_full_apply" / f"{cid}.mp4", 5, seed=i + 1)
            shas[cid] = _sha_file(path)
            s.execute(
                text(
                    "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, sha256,"
                    " size_bytes, revision) VALUES (:aid,'default','video',:rel,'ready',:sha,:sz,1)"
                ),
                {"aid": f"art-{cid}", "rel": f"s10_full_apply/{cid}.mp4", "sha": shas[cid],
                 "sz": path.stat().st_size},
            )
            s.execute(
                text(
                    "INSERT INTO s10_full_apply_chunk(id, workspace_id, run_id, shot_id, layer_id,"
                    " order_index, chunk_index, core_start_frame, core_end_frame, state, verified,"
                    " attempt, artifact_id, content_hash, natural_key)"
                    " VALUES (:cid,'default','run-1',"
                    ":shot,'layer_a',:oi,:oi,:cs,:ce,'completed',1,1,:aid,:ch,:nk)"
                ),
                {"cid": cid, "shot": shot, "oi": i, "cs": i * 5, "ce": i * 5 + 4,
                 "aid": f"art-{cid}", "ch": "a" * 64, "nk": f"s10_chunk:run-1:{cid}"},
            )
        s.execute(
            text(
                "INSERT INTO s10_recompute_record(id, workspace_id, project_id, run_id,"
                " correction_id, correction_kind, target_layer_ids_json, affected_chunk_ids_json,"
                " result_hash, provenance_json, attempt_before, attempt_after, revision_before,"
                " revision_after) VALUES ('rx','default','p1','run-1','corr-x',"
                "'mask','[\"layer_a\"]',"
                ":aff,:rh,'{}',1,2,1,2)"
            ),
            {"aff": json.dumps(["shot-a1", "shot-a2"]), "rh": "d" * 64},
        )
        s.commit()
        before = svc.preservation_report(
            workspace_id="default", run_id="run-1", correction_id="corr-x"
        )
        assert before["affected"]["BOOK"] == sorted([shas["shot-a1"], shas["shot-a2"]])
        assert before["preserved"]["TURN"] == [shas["shot-b1"]]
        assert before["counts"] == {"chunks_total": 3, "affected_chunks": 2, "preserved_chunks": 1}
        assert before["statements_used"] == 2
        # simulate the affected-only recompute: shot A gets NEW artifact bytes,
        # shot B is untouched (byte-identical on disk)
        for cid in ("shot-a1", "shot-a2"):
            path = _write_mp4(managed / "s10_full_apply" / f"{cid}.mp4", 5, seed=99)
            s.execute(
                text("UPDATE artifact SET sha256=:sha, size_bytes=:sz WHERE id=:aid"),
                {"sha": _sha_file(path), "sz": path.stat().st_size, "aid": f"art-{cid}"},
            )
            s.execute(
                text("UPDATE s10_full_apply_chunk SET attempt=attempt+1 WHERE id=:cid"),
                {"cid": cid},
            )
        s.execute(
            text(
                "INSERT INTO s10_recompute_provenance(chunk_id, correction_id, workspace_id,"
                " run_id, provenance_json) VALUES ('shot-a1','corr-x','default','run-1','{}')"
            )
        )
        s.commit()
        after = svc.preservation_report(
            workspace_id="default", run_id="run-1", correction_id="corr-x"
        )
        assert after["preserved"]["TURN"] == before["preserved"]["TURN"]  # shot khác hash giữ
        assert after["affected"]["BOOK"] != before["affected"]["BOOK"]  # recomputed shot moved
        assert _sha_file(managed / "s10_full_apply" / "shot-b1.mp4") == shas["shot-b1"]
        with pytest.raises(rec.S10RecomputeNotFoundError):
            svc.preservation_report(workspace_id="default", run_id="run-1", correction_id="nope")
        with pytest.raises(rec.S10RecomputeOwnershipError):
            svc.preservation_report(
                workspace_id="default", run_id="run-OTHER", correction_id="corr-x"
            )


# ── 20.2 — jobs engine path: no duplicate POST; in-doubt typed ───────────────


def _jobs_fixture(tmp_path: Path) -> dict[str, Any]:
    sf = _db(tmp_path, name="jobs.db")
    managed = tmp_path / "managed"
    source = _write_mp4(managed / "src" / "source.mp4", 10, seed=1)
    asset = managed / "assets" / "BOOK-P1.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"asset-bytes" * 4)
    anchor = managed / "anchor" / "anchor_book_00001_.png"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_bytes(b"\x89PNG\r\n\x1a\n" + b"anchor-bytes" * 4)
    graph_sha = _sha_file(WT / GRAPH_REL)
    manifest = {
        "managed_root": str(managed),
        "source_media_rel": "src/source.mp4",
        "source_media_sha256": _sha_file(source),
        "source_media_size_bytes": source.stat().st_size,
        "replacement_assets": {
            "BOOK-P1": {
                "artifact_id": "art-asset",
                "rel": "assets/BOOK-P1.png",
                "sha256": _sha_file(asset),
                "size_bytes": asset.stat().st_size,
            }
        },
    }
    authority = {
        "mapping": [
            {
                "layer_id": "BOOK-P1",
                "route": "sprite_affine",
                "affected_region": [0.1, 0.1, 0.4, 0.4],
                "pack_version": "pv1",
            }
        ]
    }
    backend = {
        "backend": "comfy_shot_engine",
        "profile_id": WAN_PROFILE,
        "capability": "source_video_motion_transfer",
        "graph_file": GRAPH_REL,
        "graph_sha256": graph_sha,
        "output_node": "246",
        "seed": 582699151003550,
        "shot_prompts": {"BOOK": "a seated reader, opener book"},
        "shot_anchors": {
            "BOOK": {"relative_path": "anchor/anchor_book_00001_.png", "sha256": _sha_file(anchor)}
        },
    }
    chunk = {
        "id": "row-1",
        "chunk_id": "ck_grp_book",
        "shot_id": "BOOK",
        "core_start_frame": 0,
        "core_end_frame": 9,
        "member_layer_ids": ["BOOK-P1"],
        "layer_id": "grp_BOOK",
    }
    return {
        "sf": sf,
        "managed": managed,
        "manifest": manifest,
        "authority": authority,
        "backend": backend,
        "chunk": chunk,
    }


def _scripted_engine(fx: dict[str, Any], calls: list[str]) -> Any:
    def fake_render(*, managed_root: Path, request: dict[str, Any]) -> dict[str, Any]:
        calls.append(str(request["chunk_id"]))
        rel = f"engine_out/{request['chunk_id']}_00001_.mp4"
        path = _write_mp4(managed_root / rel, 10, seed=3)
        return _result(path, output_relative_path=rel)

    return fake_render


def test_mf20_2_jobs_engine_path_cache_hit_skips_the_second_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _jobs_fixture(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(jobs, "_run_shot_render", _scripted_engine(fx, calls))
    args = dict(
        managed_root=fx["managed"],
        run_id="run-1",
        chunk=fx["chunk"],
        chunk_index=0,
        fps_num=30,
        fps_den=1,
        workspace_id="default",
        project_id="proj-1",
        video_item_id="vid-1",
        authority=fx["authority"],
        manifest=fx["manifest"],
        backend=fx["backend"],
        session_factory=fx["sf"],
    )
    rel1, sha1, size1, ev1 = jobs._render_shot_chunk_via_engine(**args)
    assert ev1["cache"]["hit"] is False
    assert calls == ["ck_grp_book"]
    rel2, sha2, size2, ev2 = jobs._render_shot_chunk_via_engine(**args)
    assert ev2["cache"]["hit"] is True
    assert calls == ["ck_grp_book"]  # replay: NO second engine POST
    assert (str(rel2), sha2, size2) == (str(rel1), sha1, size1)
    assert ev2["prompt_id"] == ev1["prompt_id"]


def test_mf20_2_jobs_engine_path_in_doubt_is_typed_without_repost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _jobs_fixture(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(jobs, "_run_shot_render", _scripted_engine(fx, calls))
    args = dict(
        managed_root=fx["managed"],
        run_id="run-1",
        chunk=fx["chunk"],
        chunk_index=0,
        fps_num=30,
        fps_den=1,
        workspace_id="default",
        project_id="proj-1",
        video_item_id="vid-1",
        authority=fx["authority"],
        manifest=fx["manifest"],
        backend=fx["backend"],
        session_factory=fx["sf"],
    )
    jobs._render_shot_chunk_via_engine(**args)
    assert calls == ["ck_grp_book"]
    # simulate the previous process dying AFTER the submit epoch and BEFORE
    # the response for the SAME content: attempt stays durably SUBMITTED
    with fx["sf"]() as s:
        s.execute(text("DELETE FROM shot_reskin_cache_receipt"))
        s.execute(
            text(
                "UPDATE shot_reskin_cache_attempt SET state='submitted', prompt_id=NULL,"
                " late_output_json=NULL"
            )
        )
        s.commit()
    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        jobs._render_shot_chunk_via_engine(**args)
    assert "shot_cache_submit_in_doubt" in str(exc.value)
    assert calls == ["ck_grp_book"]  # the restart never re-POSTed
    # an explicit durable retry (pipeline attempt > 1) supersedes and renders
    rel, sha, size, ev = jobs._render_shot_chunk_via_engine(**args, retry=True)
    assert calls == ["ck_grp_book", "ck_grp_book"]
    assert ev["cache"]["hit"] is False
    with fx["sf"]() as s:
        cache = ShotReskinCache(s, managed_root=fx["managed"])
        state = cache.reopen_state(workspace_id="default", run_id="run-1")
        assert state["attempts"]["by_state"] == {"superseded": 1, "completed": 1}
        assert state["receipts"]["total"] == 1


# ── Windows long-path probe at the REAL managed root ────────────────────────


def test_mf20_windows_path_probe_at_real_managed_root(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("long-path probe is Windows-specific")

    real_roots: list[Path] = []
    env_root = os.environ.get(_PROBE_MANAGED_ROOT_ENV, "").strip()
    if env_root:
        real_roots.append(Path(env_root))
    else:
        real_roots.append(_DEFAULT_PROBE_MANAGED_ROOT)
    try:
        from app.api import deps

        real_roots.append(Path(deps.get_managed_root()))
    except Exception:
        pass  # QA/test mode fences the protected MAIN root — use the run area
    sf = _db(tmp_path, name="probe.db")
    long_shot = "shot_" + "S" * 120
    long_chunk = "ck_" + "C" * 130
    measurements: list[dict[str, Any]] = []
    for real_root in real_roots:
        assert real_root.is_absolute(), f"managed root must be absolute: {real_root}"
        real_root.mkdir(parents=True, exist_ok=True)
        protected = Path.home() / "MotionForge2D"
        assert real_root.resolve() != protected.resolve(), (
            "the probe refuses the protected MAIN root"
        )
        measurements.append(_probe_one_root(sf, real_root, long_shot, long_chunk))
    assert measurements and all(m["write"] == "OK" for m in measurements)
    assert all(m["path_chars"] > 260 for m in measurements), measurements


def _probe_one_root(
    sf: Any, real_root: Path, long_shot: str, long_chunk: str
) -> dict[str, Any]:
    shot_root = real_root / "shot_render_cache"
    my_dir = shot_root / long_shot
    measurement: dict[str, Any] = {}
    try:
        payload = {
            "shot_id": long_shot,
            "chunk_id": long_chunk,
            "output_relative_path": "engine_out/x_00001_.mp4",
            "output_sha256": "a" * 64,
            "state": "valid",
        }
        with sf() as s:
            cache = ShotReskinCache(s, managed_root=real_root)
            rel, sidecar_sha = cache._write_receipt_sidecar(payload)
            s.commit()
        target = real_root / rel
        measured = len(str(target))
        assert measured > 260, f"probe path {measured} chars did not exceed MAX_PATH"
        # the production path is long-path aware: read it back through the
        # SAME extended-length form the managed-root helpers use
        resolved = _long_path(target)
        assert resolved.is_file(), f"long path write failed at {measured} chars"
        assert _sha_file(resolved) == sidecar_sha
        roundtrip = json.loads(resolved.read_text(encoding="utf-8"))
        assert roundtrip["shot_id"] == long_shot and roundtrip["chunk_id"] == long_chunk
        assert not list(_long_path(my_dir).glob(".*.staging")), "orphan staging files"
        measurement = {
            "root": str(real_root),
            "path_chars": measured,
            "extended_length_form": len(str(resolved)),
            "write": "OK",
            "read": "OK",
            "plain_form_readable": bool(target.is_file()),
            "sha256": sidecar_sha,
        }
    finally:
        if my_dir.exists():
            shutil.rmtree(Path("\\\\?\\" + str(my_dir)), ignore_errors=True)
        assert not my_dir.exists(), f"probe dir survived: {my_dir}"
        if shot_root.exists() and not any(shot_root.iterdir()):
            with contextlib.suppress(OSError):
                shot_root.rmdir()
        assert real_root.is_dir()
    return measurement
