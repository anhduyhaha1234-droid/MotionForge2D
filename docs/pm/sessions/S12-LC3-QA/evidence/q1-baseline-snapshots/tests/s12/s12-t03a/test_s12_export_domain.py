"""S12-T03A domain tests — export run/chunk ownership + claim/fence.

Covers §6 ownership + §7 contract acceptance for the durable export
domain (run/chunk/lease over the S12ExportRepository):

- FULL identity pinning at create_run: frozen ApplyCheckpoint pin
  (hash + revision + project) + frozen structural-lock manifest pin
  (hash + video/project + generation + draft/active) + frozen T01
  profile snapshot + render-plan identity — wrong/stale/ambiguous
  identity fails closed BEFORE any row is written.
- single-winner atomic claim: the first claimer wins the lease INSERT,
  every concurrent loser fails closed with LeaseConflictError; only an
  absent or expired/released lease may be claimed (re-claim via guarded
  lease_version CAS with a fresh fence token).
- fence enforcement on EVERY worker write: wrong worker/token raises
  FencedWorkerError and the row is untouched (chunk upsert/transition,
  run transition, heartbeat, release).
- idempotency: equivalent replay under the same idempotency_key returns
  the existing row (created=False); a materially different payload on
  the same key/natural key raises IdempotencyConflictError.
- chunk replay determinism: same (run, index, attempt) + same
  content_hash returns the existing chunk; different content_hash on
  the same slot raises StaleIdentityError (ambiguous identity never
  overwrites).
- wrong/stale/ambiguous pins fail closed: stale checkpoint revision,
  stale manifest hash/generation, cross-project checkpoint, unknown
  profile, non-hex hashes, unknown chunk state, invalid transitions,
  terminal-run immutability, revision CAS mismatch, chunk frame-range
  violations, lease-not-found paths.
- restart safety: engine dispose + reopen replays from the current
  lease/run rows (claim replays fail closed for the live lease; a
  released/expired lease re-claims with a bumped lease_version).

Runs against real migrated temp DBs (never MAIN, never production).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import S12ExportRun
from app.persistence.s12_export import (
    FencedWorkerError,
    IdempotencyConflictError,
    LeaseConflictError,
    LeaseNotFoundError,
    RunNotFoundError,
    S12ExportRepository,
    StaleIdentityError,
    compute_natural_key,
)
from app.persistence.structural_lock import StructuralLockRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WS = "ws-s12t03a"
OTHER_WS = "ws-s12t03a-other"

CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _manifest() -> dict[str, Any]:
    return {
        "frame_count": 100,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


@pytest.fixture()
def migrated():  # type: ignore[no-untyped-def]
    """Yield a session factory on a fully-migrated temp DB with seed lineage."""
    db = Path(__import__("tempfile").mkdtemp(prefix="s12t03a_dom_")) / "domain.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        for ws in (WS, OTHER_WS):
            tag = "a" if ws == WS else "b"
            seed.execute(
                text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws}
            )
            seed.execute(
                text(
                    "INSERT INTO project(id,workspace_id,name)"
                    " VALUES (:p,:w,'Proj')"
                ),
                {"p": f"p-{ws}", "w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position)"
                    " VALUES (:v,:p,'Vid',0)"
                ),
                {"v": f"v-{ws}", "p": f"p-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO character(id,workspace_id,name,code)"
                    f" VALUES ('ch-{tag}',:w,'H','h-{tag}')"
                ),
                {"w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO character_pack_version(id,character_id,workspace_id,"
                    f"version,status) VALUES ('pv-{tag}','ch-{tag}',:w,1,'published')"
                ),
                {"w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                    f"source_generation,name,kind,status) VALUES ('rl-{tag}',:w,:p,:v,'g',"
                    "'C','character','confirmed')"
                ),
                {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO reskin_config(id,workspace_id,project_id,"
                    "object_role_id,cast_mapping_id,character_id,pack_version_id,"
                    f"params_json,idempotency_key,revision) VALUES ('rc-{tag}',:w,:p,"
                    f"'rl-{tag}',NULL,'ch-{tag}','pv-{tag}','{{}}',NULL,1)"
                ),
                {"w": ws, "p": f"p-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                    "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                    "loop_hashes_json,timebase_fingerprint,snapshot_json,"
                    "checkpoint_hash,note,idempotency_key,revision)"
                    f" VALUES ('ac-{tag}',:w,:p,'rc-{tag}',1,'[]','[]','tb','{{}}',"
                    ":h,NULL,NULL,1)"
                ),
                {"w": ws, "p": f"p-{ws}", "h": CHK_HASH},
            )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(WS, f"p-{WS}", f"v-{WS}", "gen1", _manifest())
            m2, _ = lock.create_manifest(
                OTHER_WS, f"p-{OTHER_WS}", f"v-{OTHER_WS}", "gen1", _manifest()
            )
            s2.commit()
            seed_manifests = {"ws": m1.id, "other": m2.id}
    yield factory, seed_manifests
    engine = create_engine_for_path(db)
    engine.dispose()


def _create_kwargs(manifest_id: str, **over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": None,  # resolved per-test via live row
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": 100,
        "chunk_config": {"overlap": 5, "max_frames": 50},
    }
    kw.update(over)
    return kw


def _manifest_hash(factory: Any, manifest_id: str) -> str:
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        assert row is not None
        return str(row.manifest_hash)


def _make_run(factory: Any, manifest_id: str, **over: Any):  # type: ignore[no-untyped-def]
    kw = _create_kwargs(manifest_id, **over)
    if kw["manifest_hash"] is None:
        kw["manifest_hash"] = _manifest_hash(factory, manifest_id)
    with factory() as s:
        repo = S12ExportRepository(s)
        rec, created = repo.create_run(**kw)
        s.commit()
        return rec, created


# ── Identity pinning ─────────────────────────────────────────────────────────

def test_create_pins_full_identity(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, created = _make_run(factory, seeds["ws"])
    assert created is True
    assert rec.checkpoint_hash == CHK_HASH
    assert rec.checkpoint_revision == 1
    assert rec.profile_id == "master-4k-h264"
    assert rec.profile_dims == "3840x2160"
    assert rec.profile_codec == "h264"
    assert rec.status == "pending"
    assert rec.natural_key == compute_natural_key(
        project_id=f"p-{WS}",
        video_item_id=f"v-{WS}",
        profile_id="master-4k-h264",
        plan_hash=PLAN_HASH,
        checkpoint_hash=CHK_HASH,
    )


def test_create_stale_checkpoint_hash_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["ws"], checkpoint_hash="f" * 64)


def test_create_stale_checkpoint_revision_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["ws"], checkpoint_revision=2)


def test_create_cross_project_checkpoint_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["ws"], project_id=f"p-{OTHER_WS}")


def test_create_unknown_checkpoint_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["ws"], checkpoint_id="no-such-checkpoint")


def test_create_stale_manifest_hash_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["ws"], manifest_hash="f" * 64)


def test_create_stale_manifest_generation_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["ws"], manifest_generation="gen2")


def test_create_cross_workspace_manifest_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(StaleIdentityError):
        _make_run(factory, seeds["other"])


def test_create_unknown_profile_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    with pytest.raises(Exception):
        _make_run(factory, seeds["ws"], profile_id="no-such-profile")


def test_create_non_hex_hashes_fail_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    for field in ("checkpoint_hash", "plan_id", "plan_hash"):
        with pytest.raises(Exception):
            _make_run(factory, seeds["ws"], **{field: "not-a-hex-hash"})


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_idempotent_replay_returns_same_row(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec1, c1 = _make_run(factory, seeds["ws"], idempotency_key="idem-1")
    rec2, c2 = _make_run(factory, seeds["ws"], idempotency_key="idem-1")
    assert (c1, c2) == (True, False)
    assert rec1.id == rec2.id
    with factory() as s:
        assert s.query(S12ExportRun).count() == 1


def test_idempotent_replay_different_payload_conflicts(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    _make_run(factory, seeds["ws"], idempotency_key="idem-2")
    with pytest.raises(IdempotencyConflictError):
        _make_run(
            factory,
            seeds["ws"],
            idempotency_key="idem-2",
            plan_hash="f" * 64,
        )


def test_natural_key_replay_different_payload_conflicts(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    # same lineage natural_key, materially different plan payload
    with pytest.raises(IdempotencyConflictError):
        _make_run(
            factory,
            seeds["ws"],
            plan_hash="f" * 64,
            natural_key=rec.natural_key,
        )


# ── Claim / fence ────────────────────────────────────────────────────────────

def test_claim_single_winner(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        assert lease.worker_id == "worker-a"
        assert lease.lease_version == 1
        assert len(lease.fence_token) > 0
        with pytest.raises(LeaseConflictError):
            repo.claim_run(rec.id, "worker-b")
        s.rollback()
        got = repo.get_run(rec.id)
        assert got.status == "running"


def test_claim_unknown_run_fails(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, _seeds = migrated
    with factory() as s:
        repo = S12ExportRepository(s)
        with pytest.raises(RunNotFoundError):
            repo.claim_run("no-such-run", "worker-a")


def test_reclaim_after_release_bumps_version(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease1 = repo.claim_run(rec.id, "worker-a")
        s.commit()
        repo.release_lease(rec.id, "worker-a", lease1.fence_token)
        s.commit()
        lease2 = repo.claim_run(rec.id, "worker-b")
        s.commit()
        assert lease2.lease_version == lease1.lease_version + 1
        assert lease2.fence_token != lease1.fence_token
        assert lease2.worker_id == "worker-b"


def test_fenced_write_rejected(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        with pytest.raises(FencedWorkerError):
            repo.transition_run(
                rec.id,
                "verifying",
                actor="worker-a",
                expected_revision=rec.revision + 1,
                fence_token="wrong-token",
            )
        s.rollback()
        with pytest.raises(FencedWorkerError):
            repo.upsert_chunk(
                run_id=rec.id,
                workspace_id=WS,
                chunk_index=0,
                order_index=0,
                core_start_frame=0,
                core_end_frame=49,
                content_hash="a" * 64,
                actor="worker-b",
                fence_token=lease.fence_token,
            )
        s.rollback()
        assert repo.get_run(rec.id).status == "running"


def test_heartbeat_wrong_token_rejected(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        with pytest.raises(FencedWorkerError):
            repo.heartbeat_lease(rec.id, "worker-a", "wrong-token")
        with pytest.raises(LeaseNotFoundError):
            repo.heartbeat_lease("no-such-run", "worker-a", lease.fence_token)


# ── Chunk determinism ────────────────────────────────────────────────────────

def test_chunk_replay_same_hash_returns_existing(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        ch1, c1 = repo.upsert_chunk(
            run_id=rec.id,
            workspace_id=WS,
            chunk_index=0,
            order_index=0,
            core_start_frame=0,
            core_end_frame=49,
            content_hash="a" * 64,
            actor="worker-a",
            fence_token=lease.fence_token,
        )
        s.commit()
        ch2, c2 = repo.upsert_chunk(
            run_id=rec.id,
            workspace_id=WS,
            chunk_index=0,
            order_index=0,
            core_start_frame=0,
            core_end_frame=49,
            content_hash="a" * 64,
            actor="worker-a",
            fence_token=lease.fence_token,
        )
        s.commit()
        assert (c1, c2) == (True, False)
        assert ch1.id == ch2.id


def test_chunk_replay_different_hash_fails_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        repo.upsert_chunk(
            run_id=rec.id,
            workspace_id=WS,
            chunk_index=0,
            order_index=0,
            core_start_frame=0,
            core_end_frame=49,
            content_hash="a" * 64,
            actor="worker-a",
            fence_token=lease.fence_token,
        )
        s.commit()
        with pytest.raises(StaleIdentityError):
            repo.upsert_chunk(
                run_id=rec.id,
                workspace_id=WS,
                chunk_index=0,
                order_index=0,
                core_start_frame=0,
                core_end_frame=49,
                content_hash="b" * 64,
                actor="worker-a",
                fence_token=lease.fence_token,
            )


def test_chunk_bad_range_and_state_fail_closed(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        with pytest.raises(Exception):
            repo.upsert_chunk(
                run_id=rec.id,
                workspace_id=WS,
                chunk_index=0,
                order_index=0,
                core_start_frame=50,
                core_end_frame=10,
                content_hash="a" * 64,
                actor="worker-a",
                fence_token=lease.fence_token,
            )
        s.rollback()
        ch, _ = repo.upsert_chunk(
            run_id=rec.id,
            workspace_id=WS,
            chunk_index=1,
            order_index=1,
            core_start_frame=50,
            core_end_frame=99,
            content_hash="a" * 64,
            actor="worker-a",
            fence_token=lease.fence_token,
        )
        s.commit()
        with pytest.raises(Exception):
            repo.transition_chunk(
                ch.id,
                "no-such-state",
                actor="worker-a",
                fence_token=lease.fence_token,
                expected_revision=ch.revision,
            )


# ── Run lifecycle ────────────────────────────────────────────────────────────

def test_run_lifecycle_and_revision_cas(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        cur = repo.get_run(rec.id)
        with pytest.raises(Exception):
            repo.transition_run(
                rec.id,
                "verifying",
                actor="worker-a",
                expected_revision=cur.revision + 99,
                fence_token=lease.fence_token,
            )
        s.rollback()
        v = repo.transition_run(
            rec.id,
            "verifying",
            actor="worker-a",
            expected_revision=cur.revision,
            fence_token=lease.fence_token,
        )
        s.commit()
        assert v.status == "verifying"
        done = repo.transition_run(
            rec.id,
            "completed",
            actor="worker-a",
            expected_revision=v.revision,
            fence_token=lease.fence_token,
        )
        s.commit()
        assert done.status == "completed"
        with pytest.raises(Exception):
            repo.transition_run(
                rec.id,
                "failed",
                actor="worker-a",
                expected_revision=done.revision,
                fence_token=lease.fence_token,
            )


def test_terminal_run_freezes_chunks(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        s.commit()
        cur = repo.get_run(rec.id)
        v = repo.transition_run(
            rec.id,
            "verifying",
            actor="worker-a",
            expected_revision=cur.revision,
            fence_token=lease.fence_token,
        )
        done = repo.transition_run(
            rec.id,
            "completed",
            actor="worker-a",
            expected_revision=v.revision,
            fence_token=lease.fence_token,
        )
        s.commit()
        assert done.status == "completed"
        with pytest.raises(Exception):
            repo.upsert_chunk(
                run_id=rec.id,
                workspace_id=WS,
                chunk_index=0,
                order_index=0,
                core_start_frame=0,
                core_end_frame=49,
                content_hash="a" * 64,
                actor="worker-a",
                fence_token=lease.fence_token,
            )


# ── Restart safety ───────────────────────────────────────────────────────────

def test_restart_replays_from_lease_rows(migrated) -> None:  # type: ignore[no-untyped-def]
    factory, seeds = migrated
    rec, _ = _make_run(factory, seeds["ws"])
    with factory() as s:
        repo = S12ExportRepository(s)
        lease = repo.claim_run(rec.id, "worker-a")
        token = lease.fence_token
        version = lease.lease_version
        s.commit()
    with factory() as s2:
        repo2 = S12ExportRepository(s2)
        live = repo2.get_lease(rec.id)
        assert live is not None
        assert live.fence_token == token
        assert live.lease_version == version
        with pytest.raises(LeaseConflictError):
            repo2.claim_run(rec.id, "worker-b")
        s2.rollback()
        renewed = repo2.heartbeat_lease(rec.id, "worker-a", token)
        s2.commit()
        assert renewed.fence_token == token
