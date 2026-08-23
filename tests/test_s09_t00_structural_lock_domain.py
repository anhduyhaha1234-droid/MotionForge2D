"""S09-T00-I01 domain tests — StructuralLockRepository behavior.

Binary acceptance coverage per TASK.md:
- manifest supersede/version chain (natural key, partial-unique active slot)
- idempotent replay returns the SAME row (created=False); materially
  different payload on the same key → conflict
- anchors normalized x/y ∈ [0,1], fail-closed at repository AND at DB CHECK
  (boundary values accepted, out-of-range refused)
- renderer route enum EXACT five values {pose_swap, sprite_affine,
  mesh_warp, part_rig, controlled_redraw} — anything else refused
- pins: ReskinConfig CAS (stale revision refused, revision bumps), pinned
  manifest must exist in the same workspace (cross-workspace refused);
  ApplyCheckpoint pins immutable once frozen
- workspace isolation BOTH directions (create + read)
- hash pinning: expected_hash mismatch refuses; canonical JSON is stable

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
from app.persistence.models import (
    ApplyCheckpoint,
    ReskinConfig,
)
from app.persistence.structural_lock import (
    StructuralLockConflictError,
    StructuralLockHashMismatchError,
    StructuralLockNotFoundError,
    StructuralLockOwnershipError,
    StructuralLockParamsError,
    StructuralLockRepository,
    canonical_manifest_json,
    manifest_hash,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS_A = "ws-domain-a"
WS_B = "ws-domain-b"


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "frame_count": 100,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def migrated(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Yield a session factory on a fully-migrated temp DB with two workspaces."""
    db = tmp_path / "domain.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        for ws in (WS_A, WS_B):
            seed.execute(
                text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws}
            )
            seed.execute(
                text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
                {"p": f"p-{ws}", "w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO video_item(id,project_id,title,position)"
                    " VALUES (:v,:p,'Vid',0)"
                ),
                {"v": f"v-{ws}", "p": f"p-{ws}"},
            )
        seed.commit()
    yield factory
    engine = create_engine_for_path(db)
    engine.dispose()


# ── Supersede / versioning ────────────────────────────────────────────────────


def test_manifest_supersede_and_version_chain(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        r1, created1 = repo.create_manifest(WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest())
        assert created1 and r1.version == 1 and r1.status == "active"

        r2, created2 = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest(frame_count=120)
        )
        assert created2 and r2.version == 2 and r2.status == "active"

        old = repo.get_manifest(r1.id, WS_A)
        assert old.status == "superseded"
        assert old.superseded_by_id == r2.id

        current = repo.get_current_manifest(WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1")
        assert current.id == r2.id and current.version == 2


def test_superseded_history_never_rewritten_by_third_version(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        r1, _ = repo.create_manifest(WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest())
        r2, _ = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest(frame_count=110)
        )
        r3, _ = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest(frame_count=130)
        )

        h1 = repo.get_manifest(r1.id, WS_A)
        h2 = repo.get_manifest(r2.id, WS_A)
        assert h1.status == "superseded" and h1.superseded_by_id == r2.id
        assert h2.status == "superseded" and h2.superseded_by_id == r3.id
        assert r3.version == 3


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_idempotent_replay_same_row_created_false(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        r1, c1 = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest(), idempotency_key="idem-x"
        )
        assert c1 is True
        r2, c2 = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest(), idempotency_key="idem-x"
        )
        assert c2 is False
        assert r2.id == r1.id
        # No phantom version bump.
        rows, total = repo.list_manifests(WS_A)
        assert total == 1


def test_idempotent_replay_different_payload_conflicts(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "gen1", _manifest(), idempotency_key="idem-y"
        )
        with pytest.raises(StructuralLockConflictError):
            repo.create_manifest(
                WS_A,
                f"p-{WS_A}",
                f"v-{WS_A}",
                "gen1",
                _manifest(frame_count=999),  # materially different
                idempotency_key="idem-y",
            )


# ── Anchors fail-closed ───────────────────────────────────────────────────────


def _seed_segment(s: Any, ws: str) -> str:  # type: ignore[no-untyped-def]
    s.execute(
        text(
            "INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,"
            "start_time_ms,end_time_ms,status) VALUES ('sc',:v,0,0,100,0,3000,'pending')"
        ),
        {"v": f"v-{ws}"},
    )
    s.execute(
        text(
            "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
            "source_generation,name,kind,status) VALUES ('rl',:w,:p,:v,'g','C',"
            "'character','confirmed')"
        ),
        {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
    )
    s.execute(
        text(
            "INSERT INTO occurrence_segment(id,workspace_id,project_id,video_item_id,"
            "role_id,scene_id,logical_id,lineage_version,name,kind,start_frame,end_frame,"
            "start_time_ms,end_time_ms,source_generation,confidence,confidence_source,"
            "reasons_json,visibility,z_order,revision) VALUES ('sg',:w,:p,:v,'rl','sc',"
            "'lg',1,'C','character',0,100,0,3000,'g',0.9,'model','[]','visible',0,1)"
        ),
        {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
    )


def test_anchor_boundaries_accepted_out_of_range_refused(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        _seed_segment(s, WS_A)

        rr, created = repo.record_render_route(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "sg", "sprite_affine", 0.0, 1.0, 0, 100
        )
        assert created and (rr.anchor_x, rr.anchor_y) == (0.0, 1.0)

        for bad_x, bad_y in ((1.0001, 0.5), (-0.0001, 0.5), (0.5, 1.5)):
            with pytest.raises(StructuralLockParamsError):
                repo.record_render_route(
                    WS_A, f"p-{WS_A}", f"v-{WS_A}", "sg", "mesh_warp", bad_x, bad_y, 0, 100
                )

    # And the DB itself refuses too (CHECK layer independent of Python).
    with (
        pytest.raises(Exception),  # noqa: B017 — sqlite3.IntegrityError via SA
        migrated() as s2,
    ):
        _seed_segment(s2, WS_B)
        s2.execute(
            text(
                "INSERT INTO segment_render_route(id,workspace_id,project_id,"
                "video_item_id,occurrence_segment_id,route,anchor_x,anchor_y,"
                "start_frame,end_frame,confidence,confidence_source,reasons_json,"
                "revision) VALUES ('bad','ws-domain-b','p-ws-domain-b','v-ws-domain-b',"
                "'sg','pose_swap',1.5,0.5,0,10,1.0,'model','[]',1)"
            )
        )
        s2.flush()


# ── Route enum exact five ─────────────────────────────────────────────────────


def test_route_enum_exact_five_values(migrated) -> None:  # type: ignore[no-untyped-def]
    from app.persistence.models import RENDERER_ROUTES

    assert RENDERER_ROUTES == (
        "pose_swap",
        "sprite_affine",
        "mesh_warp",
        "part_rig",
        "controlled_redraw",
    )
    with migrated() as s:
        repo = StructuralLockRepository(s)
        _seed_segment(s, WS_A)
        for route in RENDERER_ROUTES:
            rec, created = repo.record_render_route(
                WS_A, f"p-{WS_A}", f"v-{WS_A}", "sg", route, 0.25, 0.75, 0, 100,
                provenance={"residual": 0.4},
                reasons=[f"why-{route}"],
            )
            assert created and rec.route == route
        for bad in ("fabric_draw", "POSE_SWAP", "", "pose-swap", None):
            with pytest.raises((StructuralLockParamsError, TypeError)):
                if bad is None:
                    repo.record_render_route(
                        WS_A, f"p-{WS_A}", f"v-{WS_A}", "sg",
                        None,  # type: ignore[arg-type]
                        0.5, 0.5, 0, 100,
                    )
                else:
                    repo.record_render_route(
                        WS_A, f"p-{WS_A}", f"v-{WS_A}", "sg", str(bad), 0.5, 0.5, 0, 100
                    )


# ── Pins: CAS on ReskinConfig, immutable on ApplyCheckpoint ──────────────────


def _seed_reskin(s: Any, ws: str) -> None:  # type: ignore[no-untyped-def]
    s.execute(
        text(
            "INSERT INTO character(id,workspace_id,name,code) VALUES ('ch',:w,'H','h')"
        ),
        {"w": ws},
    )
    s.execute(
        text(
            "INSERT INTO character_pack_version(id,character_id,workspace_id,version,"
            "status) VALUES ('pv','ch',:w,1,'published')"
        ),
        {"w": ws},
    )
    s.execute(
        text(
            "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
            "source_generation,name,kind,status) VALUES ('rl',:w,:p,:v,'g','C',"
            "'character','confirmed')"
        ),
        {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
    )
    s.execute(
        text(
            "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
            "cast_mapping_id,character_id,pack_version_id,params_json,idempotency_key,"
            "revision) VALUES ('rc',:w,:p,'rl',NULL,'ch','pv','{}',NULL,1)"
        ),
        {"w": ws, "p": f"p-{ws}"},
    )


def test_reskin_pin_cas_bumps_and_refuses_stale(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        manifest, _ = repo.create_manifest(WS_A, f"p-{WS_A}", f"v-{WS_A}", "g", _manifest())
        _seed_reskin(s, WS_A)

        new_rev = repo.set_reskin_lock_pin(
            "rc", WS_A, 1, manifest.id, "structural-thresholds-v1"
        )
        assert new_rev == 2

        row = s.get(ReskinConfig, "rc")
        assert row.structural_lock_manifest_id == manifest.id
        assert row.lock_policy_version == "structural-thresholds-v1"
        assert row.revision == 2

        with pytest.raises(StructuralLockConflictError):
            repo.set_reskin_lock_pin("rc", WS_A, 1, manifest.id, "structural-thresholds-v1")

        # Correct CAS on the new revision works (unpin allowed too).
        newer_rev = repo.set_reskin_lock_pin("rc", WS_A, 2, None, None)
        assert newer_rev == 3


def test_reskin_pin_cross_workspace_manifest_refused(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        other, _ = repo.create_manifest(WS_B, f"p-{WS_B}", f"v-{WS_B}", "g", _manifest())
        _seed_reskin(s, WS_A)
        with pytest.raises(StructuralLockOwnershipError):
            repo.set_reskin_lock_pin(
                "rc", WS_A, 1, other.id, "structural-thresholds-v1"
            )


def test_checkpoint_pin_immutable_once_frozen(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        m1, _ = repo.create_manifest(WS_A, f"p-{WS_A}", f"v-{WS_A}", "g", _manifest())
        m2, _ = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "g", _manifest(frame_count=140)
        )
        _seed_reskin(s, WS_A)
        s.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                "loop_hashes_json,timebase_fingerprint,snapshot_json,checkpoint_hash,"
                "note,idempotency_key,revision) VALUES ('ac',:w,:p,'rc',1,'[]','[]',"
                "'tb','{}',:h,NULL,NULL,1)"
            ),
            {"w": WS_A, "p": f"p-{WS_A}", "h": "c" * 64},
        )

        repo.set_checkpoint_lock_pin("ac", WS_A, m2.id, "structural-thresholds-v1")
        s.flush()

        row = s.get(ApplyCheckpoint, "ac")
        assert row.structural_lock_manifest_id == m2.id
        assert row.revision == 1  # checkpoint stays immutable

        # Changing EITHER pin afterwards is refused with zero mutation.
        with pytest.raises(StructuralLockConflictError):
            repo.set_checkpoint_lock_pin("ac", WS_A, m1.id, "structural-thresholds-v1")
        with pytest.raises(StructuralLockConflictError):
            repo.set_checkpoint_lock_pin("ac", WS_A, m2.id, "other-policy-v9")
        s.flush()
        after = s.get(ApplyCheckpoint, "ac")
        assert after.structural_lock_manifest_id == m2.id
        assert after.lock_policy_version == "structural-thresholds-v1"

        # Equivalent re-freeze is a no-op (idempotent).
        repo.set_checkpoint_lock_pin("ac", WS_A, m2.id, "structural-thresholds-v1")


# ── Workspace isolation both directions ───────────────────────────────────────


def test_workspace_isolation_both_directions(migrated) -> None:  # type: ignore[no-untyped-def]
    with migrated() as s:
        repo = StructuralLockRepository(s)
        mine, _ = repo.create_manifest(WS_A, f"p-{WS_A}", f"v-{WS_A}", "g", _manifest())

        # Direction 1: reading A's manifest through B's scope → NotFound.
        with pytest.raises(StructuralLockNotFoundError):
            repo.get_manifest(mine.id, WS_B)

        # Direction 2: creating under B referencing A's project → Ownership.
        with pytest.raises(StructuralLockOwnershipError):
            repo.create_manifest(WS_B, f"p-{WS_A}", f"v-{WS_A}", "g", _manifest())

        # Direction 3: cross-workspace video under own project → Ownership.
        with pytest.raises(StructuralLockOwnershipError):
            repo.create_manifest(WS_B, f"p-{WS_B}", f"v-{WS_A}", "g", _manifest())


# ── Hash pinning + canonical stability ────────────────────────────────────────


def test_expected_hash_mismatch_refuses_and_canonical_stable(migrated) -> None:  # type: ignore[no-untyped-def]
    payload = _manifest()
    canonical = canonical_manifest_json(payload)
    digest = manifest_hash(canonical)
    assert len(digest) == 64

    with migrated() as s:
        repo = StructuralLockRepository(s)
        with pytest.raises(StructuralLockHashMismatchError):
            repo.create_manifest(
                WS_A, f"p-{WS_A}", f"v-{WS_A}", "g", payload, expected_hash="f" * 64
            )
        ok, created = repo.create_manifest(
            WS_A, f"p-{WS_A}", f"v-{WS_A}", "g", payload, expected_hash=digest
        )
        assert created and ok.manifest_hash_hex == digest
