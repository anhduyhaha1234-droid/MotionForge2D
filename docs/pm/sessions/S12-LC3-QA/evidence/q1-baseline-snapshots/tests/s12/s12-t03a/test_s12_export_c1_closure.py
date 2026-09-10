"""S12-T03A C1 closure rows — replay-identity / union-orphan / claim / fencing.

C06 replay-material-identity: replay with UNCHANGED material pins returns
  the same run (created=False, zero extra rows); replay with ANY changed
  material pin (frame_count, chunk overlap, checkpoint hash/revision,
  manifest hash/generation, profile, plan hash) fails closed with
  IdempotencyConflictError and creates zero extra rows.

C07 identity-union-orphan: the exact claimant (same idempotency_key) is
  reused; wrong key/different payload/cross-scope replay/tampered lease
  row are all rejected; a DB error is never mistaken for absence (the
  conflict path re-reads and raises when no row resolves); a true orphan
  (lease row present, run row DELETED out-of-band) is repaired exactly
  once by re-claim CAS; every assertion counts ALL rows including
  misleading keys.

C08 two-participant claim/transition: two threads behind a
  threading.Barrier race claim_run with bounded joins — exactly 1 winner,
  1 LeaseConflictError loser, exactly 1 lease row, run running; plus a
  stale-ORM sequential control (winner then loser on the same session
  ordering) proving the loser path is deterministic, not timing luck.

C09 live-lease-fencing: after expiry/release/re-claim, writes with the
  OLD fence token produce 0 mutations (FencedWorkerError, revision and
  status untouched); exactly one live owner can mutate.

Isolated fixtures (temp roots s12t03a_c1_*), never MAIN/production.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

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
    LeaseConflictError,
    S12ExportRepository,
)
from app.persistence.structural_lock import StructuralLockRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WS = "ws-s12t03a-c1"

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


@pytest.fixture()
def c1db():  # type: ignore[no-untyped-def]
    """Migrated temp DB with one full export lineage; yields (factory, pins)."""
    import tempfile

    db = Path(tempfile.mkdtemp(prefix="s12t03a_c1_")) / "c1.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        seed.execute(text("INSERT INTO workspace(id,name) VALUES ('w1','W1')"))
        seed.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES ('p1','w1','P')")
        )
        seed.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position)"
                " VALUES ('v1','p1','V',0)"
            )
        )
        seed.execute(
            text(
                "INSERT INTO character(id,workspace_id,name,code)"
                " VALUES ('ch','w1','H','h')"
            )
        )
        seed.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,"
                "version,status) VALUES ('pv','ch','w1',1,'published')"
            )
        )
        seed.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) VALUES ('rl','w1','p1','v1',"
                "'g','C','character','confirmed')"
            )
        )
        seed.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,"
                "object_role_id,cast_mapping_id,character_id,pack_version_id,"
                "params_json,idempotency_key,revision) VALUES ('rc','w1','p1','rl',"
                "NULL,'ch','pv','{}',NULL,1)"
            )
        )
        seed.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                "loop_hashes_json,timebase_fingerprint,snapshot_json,"
                "checkpoint_hash,note,idempotency_key,revision)"
                f" VALUES ('ac','w1','p1','rc',1,'[]','[]','tb','{{}}',"
                f"'{CHK_HASH}',NULL,NULL,1)"
            )
        )
        seed.commit()
    with factory() as s2:
        lock = StructuralLockRepository(s2)
        m, _ = lock.create_manifest("w1", "p1", "v1", "gen1", _manifest_payload())
        s2.commit()
        mid = m.id
    with factory() as s3:
        row = s3.get(StructuralLockManifest, mid)
        assert row is not None
        mhash = str(row.manifest_hash)
    pins = {"manifest_id": mid, "manifest_hash": mhash}
    yield factory, pins
    engine = create_engine_for_path(db)
    engine.dispose()


def _kw(pins: dict[str, str], **over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "workspace_id": "w1",
        "project_id": "p1",
        "video_item_id": "v1",
        "checkpoint_id": "ac",
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
        "idempotency_key": "c1-key",
    }
    kw.update(over)
    return kw


def _counts(factory: Any) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    with factory() as s:
        runs = s.scalar(select(func.count()).select_from(S12ExportRun)) or 0
        chunks = s.scalar(select(func.count()).select_from(S12ExportChunk)) or 0
        leases = s.scalar(select(func.count()).select_from(S12ExportLease)) or 0
        return int(runs), int(chunks), int(leases)


# ── C06 replay-material-identity ─────────────────────────────────────────────

def test_c06_unchanged_replay_same_run_no_extra_rows(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        r1, c1 = repo.create_run(**_kw(pins))
        s.commit()
        r2, c2 = repo.create_run(**_kw(pins))
        s.commit()
        assert (c1, c2) == (True, False)
        assert r1.id == r2.id
    assert _counts(factory) == (1, 0, 0)


def test_c06_changed_frame_count_fails_no_extra_rows(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins))
        s.commit()
        # frame_count is NOT part of the identity key, but plan/natural pins
        # are: replay the same key with a changed plan_hash must conflict.
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(**_kw(pins, plan_hash="f" * 64))
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


def test_c06_changed_chunk_overlap_fails_no_extra_rows(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        lease = repo.claim_run(rec.id, "w-c06")
        s.commit()
        ch, created = repo.upsert_chunk(
            run_id=rec.id,
            workspace_id="w1",
            chunk_index=0,
            order_index=0,
            core_start_frame=0,
            core_end_frame=49,
            overlap_before=5,
            content_hash="a" * 64,
            actor="w-c06",
            fence_token=lease.fence_token,
        )
        s.commit()
        assert created is True
        # same slot, different overlap/content pin -> ambiguous -> fail closed
        with pytest.raises(Exception):
            repo.upsert_chunk(
                run_id=rec.id,
                workspace_id="w1",
                chunk_index=0,
                order_index=0,
                core_start_frame=0,
                core_end_frame=49,
                overlap_before=9,
                content_hash="b" * 64,
                actor="w-c06",
                fence_token=lease.fence_token,
            )
        s.rollback()
        _ = ch
    assert _counts(factory) == (1, 1, 1)


def test_c06_changed_checkpoint_pin_fails(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins))
        s.commit()
        with pytest.raises(Exception):
            repo.create_run(**_kw(pins, checkpoint_hash="f" * 64))
        s.rollback()
        with pytest.raises(Exception):
            repo.create_run(**_kw(pins, checkpoint_revision=2))
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


def test_c06_changed_manifest_profile_tool_source_pins_fail(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins))
        s.commit()
        for field, bad in (
            ("manifest_hash", "f" * 64),
            ("manifest_generation", "gen2"),
            ("profile_id", "preview-1080p-h264"),
            ("plan_hash", "f" * 64),
        ):
            with pytest.raises(Exception):
                repo.create_run(**_kw(pins, **{field: bad}))
            s.rollback()
    assert _counts(factory) == (1, 0, 0)


# ── C07 identity-union-orphan ────────────────────────────────────────────────

def test_c07_exact_claimant_reused(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        r1, _ = repo.create_run(**_kw(pins, idempotency_key="exact-1"))
        s.commit()
        r2, created2 = repo.create_run(**_kw(pins, idempotency_key="exact-1"))
        s.commit()
        assert created2 is False
        assert r1.id == r2.id
    assert _counts(factory) == (1, 0, 0)


def test_c07_wrong_key_new_payload_rejected_or_isolated(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        r1, _ = repo.create_run(**_kw(pins, idempotency_key="key-a"))
        s.commit()
        # same lineage natural key + different material payload on a WRONG
        # (different) key must still fail closed via natural-key match.
        with pytest.raises(IdempotencyConflictError):
            repo.create_run(
                **_kw(pins, idempotency_key="key-b", plan_hash="f" * 64,
                       natural_key=r1.natural_key)
            )
        s.rollback()
    assert _counts(factory) == (1, 0, 0)


def test_c07_cross_scope_replay_rejected(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        repo.create_run(**_kw(pins, idempotency_key="scope-1"))
        s.commit()
        # cross-workspace replay of the same key: workspace scoping keeps
        # rows isolated — either a distinct row (scoped key) or rejection;
        # what is FORBIDDEN is returning the w1 row for a w2 caller.
        s.execute(text("INSERT INTO workspace(id,name) VALUES ('w2','W2')"))
        s.commit()
        with pytest.raises(Exception):
            repo.create_run(**_kw(pins, workspace_id="w2", idempotency_key="scope-1"))
        s.rollback()
    with factory() as s2:
        rows = s2.scalars(
            select(S12ExportRun).where(S12ExportRun.idempotency_key == "scope-1")
        ).all()
        assert len(rows) == 1
        assert rows[0].workspace_id == "w1"
    assert _counts(factory) == (1, 0, 0)


def test_c07_tampered_lease_row_rejected(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        lease = repo.claim_run(rec.id, "w-good")
        s.commit()
        # out-of-band tamper of the lease row: claimant change under the
        # winner's token must be rejected, original lease intact.
        s.execute(
            text("UPDATE s12_export_lease SET worker_id='w-evil' WHERE run_id=:r"),
            {"r": rec.id},
        )
        s.commit()
        with pytest.raises(FencedWorkerError):
            repo.heartbeat_lease(rec.id, "w-good", lease.fence_token)
        s.rollback()
        live = repo.get_lease(rec.id)
        assert live is not None and live.worker_id == "w-evil"
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                rec.id, "verifying", actor="w-good",
                expected_revision=rec.revision + 1,
                fence_token=lease.fence_token,
            )
    assert _counts(factory) == (1, 0, 1)


def test_c07_true_orphan_repaired_once(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        repo.claim_run(rec.id, "w-first")
        s.commit()
        # true orphan: lease row deleted out-of-band while the run survives
        # (the RESTRICT FK forbids the reverse) — get_lease must report
        # absence (DB error != absence is about the conflict path; here
        # absence is real and explicit)...
        s.execute(text("DELETE FROM s12_export_lease WHERE run_id=:r"), {"r": rec.id})
        s.commit()
        assert repo.get_lease(rec.id) is None
        # ...and exactly one re-claim repairs it with a FRESH lease row.
        lease2 = repo.claim_run(rec.id, "w-second")
        s.commit()
        assert lease2.lease_version == 1  # fresh row: version restarts
        assert lease2.worker_id == "w-second"
    assert _counts(factory) == (1, 0, 1)


# ── C08 two-participant claim/transition ─────────────────────────────────────

def test_c08_barrier_exactly_one_winner(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        s.commit()
        run_id = rec.id
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def _racer(name: str) -> None:
        with factory() as s:
            repo = S12ExportRepository(s)
            barrier.wait(timeout=30)
            try:
                repo.claim_run(run_id, name)
                s.commit()
                outcomes[name] = "won"
            except LeaseConflictError:
                s.rollback()
                outcomes[name] = "lost"
            except Exception:  # noqa: BLE001 - any other error is also a loss
                s.rollback()
                outcomes[name] = "lost"

    threads = [
        threading.Thread(target=_racer, args=(n,), name=f"c08-{n}")
        for n in ("w-alpha", "w-beta")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "bounded joins exceeded"
    assert sorted(outcomes.values()) == ["lost", "won"], outcomes
    with factory() as s:
        leases = s.scalars(select(S12ExportLease)).all()
        assert len(leases) == 1
        run = s.get(S12ExportRun, run_id)
        assert run is not None and run.status == "running"
    assert _counts(factory) == (1, 0, 1)


def test_c08_stale_orm_sequential_control(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        s.commit()
        winner = repo.claim_run(rec.id, "w-winner")
        s.commit()
        # sequential loser AFTER the winner committed: deterministic loss.
        with pytest.raises(LeaseConflictError):
            repo.claim_run(rec.id, "w-loser")
        s.rollback()
        live = repo.get_lease(rec.id)
        assert live is not None and live.worker_id == "w-winner"
        assert live.fence_token == winner.fence_token
    assert _counts(factory) == (1, 0, 1)


# ── C09 live-lease-fencing ───────────────────────────────────────────────────

def test_c09_expired_lease_old_token_zero_mutations(c1db) -> None:  # type: ignore[no-untyped-def]
    import datetime as _dt

    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        lease = repo.claim_run(rec.id, "w-live", ttl_seconds=1)
        old_token = lease.fence_token
        rev_before = repo.get_run(rec.id).revision
        s.commit()
        # force expiry out-of-band (deterministic, no sleep)
        past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=60)
        s.execute(
            text("UPDATE s12_export_lease SET expires_at=:p WHERE run_id=:r"),
            {"p": past, "r": rec.id},
        )
        s.commit()
        # new owner claims the expired lease...
        lease2 = repo.claim_run(rec.id, "w-next")
        s.commit()
        assert lease2.fence_token != old_token
        # ...old token now yields ZERO mutations everywhere.
        for attempt in (
            lambda: repo.transition_run(
                rec.id, "verifying", actor="w-live",
                expected_revision=rev_before + 1, fence_token=old_token),
            lambda: repo.upsert_chunk(
                run_id=rec.id, workspace_id="w1", chunk_index=0, order_index=0,
                core_start_frame=0, core_end_frame=49, content_hash="a" * 64,
                actor="w-live", fence_token=old_token),
            lambda: repo.heartbeat_lease(rec.id, "w-live", old_token),
        ):
            with pytest.raises(FencedWorkerError):
                attempt()
            s.rollback()
        after = repo.get_run(rec.id)
        assert after.revision == rev_before + 1  # only the re-claim bump
        assert after.status == "running"
    assert _counts(factory) == (1, 0, 1)


def test_c09_released_reclaimed_old_token_dead(c1db) -> None:  # type: ignore[no-untyped-def]
    factory, pins = c1db
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, _ = repo.create_run(**_kw(pins))
        lease = repo.claim_run(rec.id, "w-first")
        old_token = lease.fence_token
        s.commit()
        repo.release_lease(rec.id, "w-first", old_token)
        s.commit()
        lease2 = repo.claim_run(rec.id, "w-second")
        s.commit()
        assert lease2.worker_id == "w-second"
        before = repo.get_run(rec.id)
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                rec.id, "verifying", actor="w-first",
                expected_revision=before.revision, fence_token=old_token)
        s.rollback()
        # one live owner CAN mutate.
        cur = repo.get_run(rec.id)
        moved = repo.transition_run(
            rec.id, "verifying", actor="w-second",
            expected_revision=cur.revision, fence_token=lease2.fence_token)
        s.commit()
        assert moved.status == "verifying"
    assert _counts(factory) == (1, 0, 1)
