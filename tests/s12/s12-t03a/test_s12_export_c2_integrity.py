"""S12-T03A C2 rows — durable integrity + real database serialization.

Closes F04 (material replay binding + identity union) and F05 (REAL
conditional DB CAS + live-lease fencing) at the persistence boundary:

- C06 unchanged replay returns the same run; independently AND jointly
  changed material inputs (frame_count, chunk_config, plan_hash,
  profile) are rejected with IdempotencyConflictError and ZERO extra
  rows.
- C07 identity union across durable keys with NO first-key-wins:
  misleading idempotency/natural keys that resolve to DIFFERENT runs
  raise; a DB-layer failure propagates (never absence); cross-scope
  claimants cannot see another workspace's row; a true lease orphan is
  repaired exactly once; every assertion counts ALL rows via SQL
  (including misleading-key rows), never ORM-trusting subsets.
- C08 REAL synchronized transition contention: two live participants at
  the contested transition op behind a barrier → exactly 1 accepted
  winner (rowcount CAS), bounded joins; plus a resident-stale ORM
  snapshot control where the loser fails on revision.
- C09 expired / released / reclaimed lease tokens cannot
  transition / write chunks / heartbeat / release — zero mutation on
  every path (revision/status/expiry untouched, no chunk rows).

Isolated fixtures (temp roots s12t03a_c2_*), never MAIN/production.
"""

from __future__ import annotations

import datetime as _dt
import threading
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, select, text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import (
    S12ExportChunk,
    S12ExportLease,
    S12ExportRun,
    StructuralLockManifest,
)
from app.persistence.s12_export import (
    FencedWorkerError,
    IdempotencyConflictError,
    S12ExportError,
    S12ExportRepository,
    StaleIdentityError,
)
from app.persistence.structural_lock import StructuralLockRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WS = "ws-s12t03a-c2"
WS2 = "ws-s12t03a-c2-other"

CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _manifest_payload() -> dict[str, Any]:
    return {
        "frame_count": 100,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


def _seed_lineage(s, ws: str, tag: str) -> None:  # type: ignore[no-untyped-def]
    s.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
    s.execute(
        text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'P')"),
        {"p": f"p-{ws}", "w": ws},
    )
    s.execute(
        text(
            "INSERT INTO video_item(id,project_id,title,position)"
            " VALUES (:v,:p,'V',0)"
        ),
        {"v": f"v-{ws}", "p": f"p-{ws}"},
    )
    s.execute(
        text(
            "INSERT INTO character(id,workspace_id,name,code)"
            " VALUES (:cid,:w,'H','h')"
        ).bindparams(cid=f"ch-{tag}"),
        {"w": ws},
    )
    s.execute(
        text(
            "INSERT INTO character_pack_version(id,character_id,workspace_id,"
            "version,status) VALUES (:pvid,:cid,:w,1,'published')"
        ).bindparams(pvid=f"pv-{tag}", cid=f"ch-{tag}"),
        {"w": ws},
    )
    s.execute(
        text(
            "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
            "source_generation,name,kind,status) VALUES (:rid,:w,:p,:v,"
            "'g','C','character','confirmed')"
        ).bindparams(rid=f"rl-{tag}"),
        {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
    )
    s.execute(
        text(
            "INSERT INTO reskin_config(id,workspace_id,project_id,"
            "object_role_id,cast_mapping_id,character_id,pack_version_id,"
            "params_json,idempotency_key,revision) VALUES (:rcid,:w,:p,"
            ":rid,NULL,:cid,:pvid,'{}',NULL,1)"
        ).bindparams(
            rcid=f"rc-{tag}", rid=f"rl-{tag}", cid=f"ch-{tag}", pvid=f"pv-{tag}"
        ),
        {"w": ws, "p": f"p-{ws}"},
    )
    s.execute(
        text(
            "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
            "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
            "loop_hashes_json,timebase_fingerprint,snapshot_json,"
            "checkpoint_hash,note,idempotency_key,revision) VALUES "
            "(:acid,:w,:p,:rcid,1,'[]','[]','tb','{}',:h,NULL,NULL,1)"
        ).bindparams(acid=f"ac-{tag}", rcid=f"rc-{tag}", h=CHK_HASH),
        {"w": ws, "p": f"p-{ws}"},
    )


@pytest.fixture()
def c2db():  # type: ignore[no-untyped-def]
    """Migrated temp DB; two workspaces each with a full export lineage."""
    import tempfile

    db = Path(tempfile.mkdtemp(prefix="s12t03a_c2_")) / "c2.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        _seed_lineage(seed, WS, "a")
        _seed_lineage(seed, WS2, "b")
        seed.commit()
    pins: dict[str, dict[str, str]] = {}
    with factory() as s:
        for ws, tag in ((WS, "a"), (WS2, "b")):
            lock = StructuralLockRepository(s)
            m, _ = lock.create_manifest(
                ws, f"p-{ws}", f"v-{ws}", "gen1", _manifest_payload()
            )
            s.flush()
            row = s.get(StructuralLockManifest, m.id)
            assert row is not None
            pins[ws] = {"manifest_id": m.id, "manifest_hash": str(row.manifest_hash)}
        s.commit()
    yield factory, pins
    engine = create_engine_for_path(db)
    engine.dispose()


def _kw(pins: dict[str, str], ws: str = WS, **over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "workspace_id": ws,
        "project_id": f"p-{ws}",
        "video_item_id": f"v-{ws}",
        "checkpoint_id": "ac-a" if ws == WS else "ac-b",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": pins["manifest_id"],
        "manifest_hash": pins["manifest_hash"],
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": 100,
        "chunk_config": {"overlap": 5, "max_frames": 50},
        "idempotency_key": "c2-key",
    }
    kw.update(over)
    return kw


def _counts(factory: Any) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    with factory() as s:
        runs = s.scalar(select(func.count()).select_from(S12ExportRun)) or 0
        chunks = s.scalar(select(func.count()).select_from(S12ExportChunk)) or 0
        leases = s.scalar(select(func.count()).select_from(S12ExportLease)) or 0
        return int(runs), int(chunks), int(leases)


def _run_id(factory: Any, idem: str) -> str:  # type: ignore[no-untyped-def]
    with factory() as s:
        row = s.scalar(
            select(S12ExportRun).where(S12ExportRun.idempotency_key == idem)
        )
        assert row is not None
        return str(row.id)


def _lease(factory: Any, run_id: str) -> S12ExportLease | None:  # type: ignore[no-untyped-def]
    with factory() as s:
        return s.get(S12ExportLease, run_id)


def _claim(factory: Any, run_id: str, worker: str, ttl: int = 300):  # type: ignore[no-untyped-def]
    with factory() as s:
        repo = S12ExportRepository(s)
        rec = repo.claim_run(run_id, worker, ttl_seconds=ttl)
        s.commit()
        return rec


# ── C06 replay-material-identity ─────────────────────────────────────────────

def test_c06_unchanged_replay_same_run_no_extra_rows(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        r1, c1 = repo.create_run(**_kw(pins[WS], idempotency_key="r-c06-1"))
        s.commit()
        r2, c2 = repo.create_run(**_kw(pins[WS], idempotency_key="r-c06-1"))
        s.commit()
        assert (c1, c2) == (True, False)
        assert r1.id == r2.id
        assert r2.frame_count == 100
    assert _counts(factory) == (1, 0, 0)


def test_c06_independent_frame_count_change_rejected(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins[WS], idempotency_key="r-c06-2"))
        s.commit()
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(
                **_kw(pins[WS], idempotency_key="r-c06-2", frame_count=3000)
            )
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


def test_c06_independent_chunk_config_change_rejected(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins[WS], idempotency_key="r-c06-3"))
        s.commit()
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(
                **_kw(
                    pins[WS],
                    idempotency_key="r-c06-3",
                    chunk_config={"overlap": 99, "max_frames": 7},
                )
            )
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


def test_c06_independent_plan_profile_change_rejected(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins[WS], idempotency_key="r-c06-4"))
        s.commit()
        for field, bad in (
            ("plan_hash", "f" * 64),
            ("profile_id", "preview-1080p-h264"),
        ):
            with pytest.raises(IdempotencyConflictError):
                repo.create_run(
                    **_kw(pins[WS], idempotency_key="r-c06-4", **{field: bad})
                )
            s.rollback()
        # checkpoint tamper is a pin validation failure BEFORE any insert —
        # fail-closed with StaleIdentityError, still zero extra rows.
        with pytest.raises(StaleIdentityError):
            repo.create_run(
                **_kw(pins[WS], idempotency_key="r-c06-4", checkpoint_hash="f" * 64)
            )
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


def test_c06_jointly_changed_material_rejected_no_extra_rows(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins[WS], idempotency_key="r-c06-5"))
        s.commit()
        # frame_count + chunk_config + plan_hash changed TOGETHER.
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(
                **_kw(
                    pins[WS],
                    idempotency_key="r-c06-5",
                    frame_count=3000,
                    chunk_config={"overlap": 99, "max_frames": 7},
                    plan_hash="f" * 64,
                )
            )
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


# ── C07 identity union / no first-key-wins / DB error != absence ────────────

def test_c07_misleading_keys_resolve_different_runs_ambiguous(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        # run A: idem key K1, lineage L1 (master-4k)
        a, _ = repo.create_run(**_kw(pins[WS], idempotency_key="K1"))
        s.commit()
        # run B: idem key K2, DIFFERENT lineage (preview-1080p -> different
        # natural key), same workspace.
        b, _ = repo.create_run(
            **_kw(pins[WS], idempotency_key="K2", profile_id="preview-1080p-h264")
        )
        s.commit()
        assert a.id != b.id
        # Misleading caller: idem K1 (run A) with the payload/natural of run B
        # -> the union resolves TWO different runs -> ambiguous, never A or B.
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(
                **_kw(
                    pins[WS],
                    idempotency_key="K1",
                    profile_id="preview-1080p-h264",
                )
            )
        s.rollback()
    assert _counts(factory) == (2, 0, 0)


def test_c07_cross_scope_claimant_rejected(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        # ws1 claimant with key X; ws2 claimant with the SAME key X is a
        # distinct scope — neither sees nor reuses the other's row.
        r1, _ = repo.create_run(**_kw(pins[WS], idempotency_key="scope-X"))
        s.commit()
        r2, created2 = repo.create_run(
            **_kw(pins[WS2], ws=WS2, idempotency_key="scope-X")
        )
        s.commit()
        assert created2 is True
        assert r1.id != r2.id
    assert _counts(factory) == (2, 0, 0)


def test_c07_db_error_is_not_absence(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    # A DB-layer failure during resolution must PROPAGATE, never be
    # converted into "not found / absent" by the repository.
    with factory() as s:
        engine = s.get_bind()

        @event.listens_for(engine, "before_cursor_execute")
        def _boom(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("simulated db failure")

        repo = S12ExportRepository(s)
        try:
            with pytest.raises(RuntimeError, match="simulated db failure"):
                repo.create_run(
                    **_kw(
                        pins[WS],
                        idempotency_key="absent-k",
                        natural_key="9" * 64,
                    )
                )
            s.rollback()
        finally:
            event.remove(engine, "before_cursor_execute", _boom)
    assert _counts(factory) == (0, 0, 0)


def test_c07_true_lease_orphan_repaired_once(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="orphan-1"))
        repo.claim_run(rec.id, "w-orphan-a")
        s.commit()
        # true orphan: the lease row disappears out-of-band while the run
        # survives (FK RESTRICT forbids the reverse deletion).
        s.execute(text("DELETE FROM s12_export_lease WHERE run_id=:r"), {"r": rec.id})
        s.commit()
        assert repo.get_lease(rec.id) is None
        # repair exactly once -> fresh lease, version restarts at 1
        lease2 = repo.claim_run(rec.id, "w-orphan-b")
        s.commit()
        assert lease2.worker_id == "w-orphan-b"
        assert lease2.lease_version == 1
        # a SECOND claimant cannot repair again while the lease is live
        with pytest.raises(Exception):
            repo.claim_run(rec.id, "w-orphan-c")
        s.rollback()
    assert _counts(factory) == (1, 0, 1)


def test_c07_all_rows_counted_including_misleading(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins[WS], idempotency_key="cnt-1"))
        repo.create_run(
            **_kw(pins[WS], idempotency_key="cnt-2", profile_id="preview-1080p-h264")
        )
        repo.create_run(**_kw(pins[WS2], ws=WS2, idempotency_key="cnt-3"))
        s.commit()
        # misleading-key attempts must NOT add rows
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(
                **_kw(pins[WS], idempotency_key="cnt-1", profile_id="preview-1080p-h264")
            )
        s.rollback()
    runs, chunks, leases = _counts(factory)
    assert (runs, chunks, leases) == (3, 0, 0)
    with factory() as s:
        all_runs = s.scalars(select(S12ExportRun)).all()
        by_key = {r.idempotency_key for r in all_runs}
        assert by_key == {"cnt-1", "cnt-2", "cnt-3"}


# ── C08 real synchronized transition contention ──────────────────────────────

def test_c08_transition_contention_one_winner(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="race-1"))
        s.commit()
        run_id = rec.id
    lease = _claim(factory, run_id, "w-race")
    with factory() as s:
        rev = s.get(S12ExportRun, run_id)
        assert rev is not None
        base_rev = rev.revision
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def _contender(name: str) -> None:
        with factory() as s:
            repo = S12ExportRepository(s)
            # each participant loads the same resident snapshot (base_rev)
            barrier.wait(timeout=30)
            try:
                repo.transition_run(
                    run_id,
                    "verifying",
                    actor="w-race",
                    expected_revision=base_rev,
                    fence_token=lease.fence_token,
                )
                s.commit()
                results[name] = "won"
            except Exception:  # noqa: BLE001 - loser may be fence/revision
                s.rollback()
                results[name] = "lost"

    threads = [threading.Thread(target=_contender, args=(n,)) for n in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "bounded joins exceeded"
    assert sorted(results.values()) == ["lost", "won"], results
    with factory() as s:
        final = s.get(S12ExportRun, run_id)
        assert final is not None
        assert final.status == "verifying"
        assert final.revision == base_rev + 1
    assert _counts(factory) == (1, 0, 1)


def test_c08_resident_stale_orm_snapshot_loses(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="stale-1"))
        s.commit()
        run_id = rec.id
    lease = _claim(factory, run_id, "w-stale")
    with factory() as s1:
        repo1 = S12ExportRepository(s1)
        rec1, _ = repo1.create_run(  # noqa: F841 - resident snapshot only
            **_kw(pins[WS], idempotency_key="stale-1")
        )
        _ = repo1.get_run(run_id)
    # two resident ORM snapshots of the SAME run at the same revision
    with factory() as s1:
        snap1 = s1.get(S12ExportRun, run_id)
        assert snap1 is not None
        rev1 = snap1.revision
    with factory() as s2:
        snap2 = s2.get(S12ExportRun, run_id)
        assert snap2 is not None
        rev2 = snap2.revision
    assert rev1 == rev2
    # snapshot 1 wins the transition
    with factory() as s1:
        repo1 = S12ExportRepository(s1)
        won = repo1.transition_run(
            run_id, "verifying", actor="w-stale",
            expected_revision=rev1, fence_token=lease.fence_token)
        s1.commit()
        assert won.status == "verifying"
        assert won.revision == rev1 + 1
    # snapshot 2 (stale) tries the SAME transition -> must lose
    with factory() as s2:
        repo2 = S12ExportRepository(s2)
        with pytest.raises(Exception):
            repo2.transition_run(
                run_id, "verifying", actor="w-stale",
                expected_revision=rev2, fence_token=lease.fence_token)
        s2.rollback()
        still = s2.get(S12ExportRun, run_id)
        assert still is not None
        assert still.status == "verifying"
        assert still.revision == rev1 + 1
    assert _counts(factory) == (1, 0, 1)


# ── C09 expired/released/reclaimed token zero mutation ───────────────────────

def _force_expired(factory: Any, run_id: str) -> None:  # type: ignore[no-untyped-def]
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=60)
    with factory() as s:
        s.execute(
            text("UPDATE s12_export_lease SET expires_at=:p WHERE run_id=:r"),
            {"p": past, "r": run_id},
        )
        s.commit()


def test_c09_expired_token_zero_mutation_all_paths(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="exp-1"))
        s.commit()
        run_id = rec.id
    lease = _claim(factory, run_id, "w-exp", ttl=1)
    _force_expired(factory, run_id)
    before = _lease(factory, run_id)
    assert before is not None
    with factory() as s:
        repo = S12ExportRepository(s)
        cur = repo.get_run(run_id)
        rev_before = cur.revision
        # transition with expired lease -> FencedWorkerError, zero mutation
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                run_id, "verifying", actor="w-exp",
                expected_revision=rev_before, fence_token=lease.fence_token)
        s.rollback()
        # chunk write -> FencedWorkerError, zero mutation
        with pytest.raises(FencedWorkerError):
            repo.upsert_chunk(
                run_id=run_id, workspace_id=WS, chunk_index=0, order_index=0,
                core_start_frame=0, core_end_frame=49, content_hash="a" * 64,
                actor="w-exp", fence_token=lease.fence_token)
        s.rollback()
        # heartbeat -> FencedWorkerError, zero mutation
        with pytest.raises(FencedWorkerError):
            repo.heartbeat_lease(run_id, "w-exp", lease.fence_token)
        s.rollback()
        # release -> FencedWorkerError, zero mutation
        with pytest.raises(FencedWorkerError):
            repo.release_lease(run_id, "w-exp", lease.fence_token)
        s.rollback()
        after = repo.get_run(run_id)
        assert after.revision == rev_before
        assert after.status == "running"
    assert _counts(factory) == (1, 0, 1)
    after_lease = _lease(factory, run_id)
    assert after_lease is not None
    assert after_lease.expires_at == before.expires_at  # untouched by old token


def test_c09_released_token_zero_mutation(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="rel-1"))
        s.commit()
        run_id = rec.id
    lease = _claim(factory, run_id, "w-rel")
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.release_lease(run_id, "w-rel", lease.fence_token)
        s.commit()
        cur = repo.get_run(run_id)
        rev_before = cur.revision
        # released token: transitions/chunks/heartbeat all fenced
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                run_id, "verifying", actor="w-rel",
                expected_revision=rev_before, fence_token=lease.fence_token)
        s.rollback()
        with pytest.raises(FencedWorkerError):
            repo.upsert_chunk(
                run_id=run_id, workspace_id=WS, chunk_index=0, order_index=0,
                core_start_frame=0, core_end_frame=49, content_hash="a" * 64,
                actor="w-rel", fence_token=lease.fence_token)
        s.rollback()
        with pytest.raises(FencedWorkerError):
            repo.heartbeat_lease(run_id, "w-rel", lease.fence_token)
        s.rollback()
        after = repo.get_run(run_id)
        assert after.revision == rev_before
        assert after.status == "running"
    assert _counts(factory) == (1, 0, 1)  # no chunk rows were written


def test_c09_reclaimed_old_token_dead_new_token_live(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="rec-1"))
        s.commit()
        run_id = rec.id
    old = _claim(factory, run_id, "w-old")
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.release_lease(run_id, "w-old", old.fence_token)
        s.commit()
    new = _claim(factory, run_id, "w-new")
    assert new.fence_token != old.fence_token
    with factory() as s:
        repo = S12ExportRepository(s)
        cur = repo.get_run(run_id)
        rev_before = cur.revision
        # OLD token after re-claim: dead on every path, zero mutation
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                run_id, "verifying", actor="w-old",
                expected_revision=rev_before, fence_token=old.fence_token)
        s.rollback()
        with pytest.raises(FencedWorkerError):
            repo.upsert_chunk(
                run_id=run_id, workspace_id=WS, chunk_index=0, order_index=0,
                core_start_frame=0, core_end_frame=49, content_hash="a" * 64,
                actor="w-old", fence_token=old.fence_token)
        s.rollback()
        with pytest.raises(FencedWorkerError):
            repo.heartbeat_lease(run_id, "w-old", old.fence_token)
        s.rollback()
        assert repo.get_run(run_id).revision == rev_before
        # NEW live token CAN transition
        moved = repo.transition_run(
            run_id, "verifying", actor="w-new",
            expected_revision=rev_before, fence_token=new.fence_token)
        s.commit()
        assert moved.status == "verifying"
        assert moved.revision == rev_before + 1
    assert _counts(factory) == (1, 0, 1)


# ── Same-field tamper (C08/C09 adversarial control) ──────────────────────────

def test_same_field_tamper_run_and_lease_detected(c2db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c2db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins[WS], idempotency_key="tamper-1"))
        s.commit()
        run_id = rec.id
    lease = _claim(factory, run_id, "w-tamper")
    with factory() as s:
        base_rev = s.get(S12ExportRun, run_id)
        assert base_rev is not None
        base_rev_value = base_rev.revision
        # out-of-band same-field tamper: run revision + lease worker changed
        s.execute(
            text("UPDATE s12_export_run SET revision=999 WHERE id=:r"), {"r": run_id}
        )
        s.execute(
            text("UPDATE s12_export_lease SET worker_id='w-evil' WHERE run_id=:r"),
            {"r": run_id},
        )
        s.commit()
        repo = S12ExportRepository(s)
        # tampered lease: old worker fenced
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                run_id, "verifying", actor="w-tamper",
                expected_revision=base_rev_value,
                fence_token=lease.fence_token)
        s.rollback()
        # tampered revision: the tampered lease owner still cannot move the
        # run with the STALE expected revision (rowcount CAS refuses).
        live = repo.get_lease(run_id)
        assert live is not None and live.worker_id == "w-evil"
        with pytest.raises(S12ExportError):
            repo.transition_run(
                run_id, "verifying", actor="w-evil",
                expected_revision=base_rev_value, fence_token=live.fence_token)
        s.rollback()
    assert _counts(factory) == (1, 0, 1)
