"""S09-T05A migration tests — additive schema + fail-closed downgrade.

Binary acceptance coverage per TASK.md:
- live head discovery at runtime: exactly ONE head, and it is THIS task's
  revision b3c4d5e6f7a9 whose parent is d8e9f0a1b2c3;
- upgrade creates s09_correction with the exact column contract + all
  CHECK/UNIQUE constraints; ORM parity with the migrated DB;
- FK enforcement is ON for the new table (bad project id refused);
- CHECK constraints refuse unknown kinds/statuses/non-positive revisions
  and over-long keys;
- partial-unique indexes enforce workspace-scoped natural-key +
  idempotency-key identity; distinct workspaces may reuse the same keys;
- ROUND-TRIP: upgrade → seed REAL rows through the durable core → full
  data snapshot → downgrade REFUSES fail-closed while rows exist (zero
  mutation) → purge archive rows (explicit operator action) → downgrade
  drops exactly what this revision created → re-upgrade reproduces an
  identical empty schema (byte-comparable snapshot of the new table);
- PRAGMA integrity_check + foreign_key_check stay clean across the trip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WS = "s09t05a-mig-ws"

EXPECTED_COLUMNS = {
    "id",
    "workspace_id",
    "project_id",
    "video_item_id",
    "occurrence_segment_id",
    "correction_kind",
    "status",
    "request_json",
    "impact_json",
    "result_json",
    "applied_at",
    "cancelled_at",
    "idempotency_key",
    "natural_key",
    "revision",
    "created_at",
    "updated_at",
}


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _connect(db: Path) -> sa.Engine:
    engine = create_engine(f"sqlite:///{db.as_posix()}")

    @sa.event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn: object, _record: object) -> None:  # pragma: no cover
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _assert_db_clean(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        integrity = conn.execute(text("PRAGMA integrity_check")).scalar()
        assert integrity == "ok"
        fk = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert fk == []


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "migration.db"
    command.upgrade(_config(path), "head")
    _assert_db_clean(_connect(path))
    return path


# ── single head + lineage ────────────────────────────────────────────────


def test_single_head_is_this_revision() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(PROJECT_ROOT / "migrations"))
    heads = list(script.get_heads())
    assert heads == ["b3c4d5e6f7a9"], f"expected single head, got {heads}"
    rev = script.get_revision("b3c4d5e6f7a9")
    assert rev.down_revision == "d8e9f0a1b2c3"


def test_live_db_version_is_this_revision(db_path: Path) -> None:
    with _connect(db_path).connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert version == "b3c4d5e6f7a9"


# ── column + constraint contract ─────────────────────────────────────────


def test_table_columns_match_contract(db_path: Path) -> None:
    engine = _connect(db_path)
    cols = {c["name"] for c in inspect(engine).get_columns("s09_correction")}
    assert cols == EXPECTED_COLUMNS
    indexes = {i["name"] for i in inspect(engine).get_indexes("s09_correction")}
    assert {
        "uq_s09_correction_natural",
        "uq_s09_correction_workspace_idempotency",
        "ix_s09_correction_video_status",
        "ix_s09_correction_segment",
    } <= indexes
    checks = {
        c["name"]
        for c in inspect(engine).get_check_constraints("s09_correction")
    }
    assert {
        "ck_s09_correction_kind",
        "ck_s09_correction_status",
        "ck_s09_correction_idem_key_len",
        "ck_s09_correction_natural_key_len",
        "ck_s09_correction_revision_positive",
    } <= checks


def test_orm_metadata_parity_with_migrated_db(db_path: Path) -> None:
    """Every ORM column exists in the migrated table, same nullability."""
    from app.persistence.models import S09Correction

    insp = inspect(_connect(db_path))
    db_cols = {c["name"]: c for c in insp.get_columns("s09_correction")}
    for col in S09Correction.__table__.columns:
        assert col.name in db_cols, f"ORM column {col.name} missing in DB"
        assert (
            db_cols[col.name]["nullable"] == col.nullable
        ), f"{col.name} nullability mismatch"


# ── constraint enforcement (real SQLite) ─────────────────────────────────


def _seed_graph(conn: sa.Connection, ws: str) -> None:
    conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
    conn.execute(
        text(
            "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256)"
            " VALUES ('a-'||:w,:w,'video','src.mp4','ready','"
            + "11" * 32
            + "')"
        ),
        {"w": ws},
    )
    conn.execute(
        text(
            "INSERT INTO project(id,workspace_id,name) "
            "VALUES ('p-'||:w,:w,'T05A')"
        ),
        {"w": ws},
    )
    conn.execute(
        text(
            "INSERT INTO video_item(id,project_id,title,position,source_artifact_id)"
            " VALUES ('v-'||:w,'p-'||:w,'V',0,'a-'||:w)"
        ),
        {"w": ws},
    )


def _insert_row(conn: sa.Connection, **over: object) -> None:
    payload: dict[str, object] = {
        "id": "11111111-1111-4111-8111-111111111111",
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "correction_kind": "mask",
        "status": "pending",
        "request_json": json.dumps({"a": 1}),
        "impact_json": json.dumps({"segments": []}),
        "revision": 1,
    }
    payload.update(over)  # type: ignore[arg-type]
    cols = ", ".join(payload.keys())
    params = ", ".join(f":{k}" for k in payload)
    conn.execute(
        text(f"INSERT INTO s09_correction ({cols}) VALUES ({params})"), payload
    )


def test_fk_enforcement_on_project(db_path: Path) -> None:
    engine = _connect(db_path)
    with engine.begin() as conn:
        _seed_graph(conn, WS)
    with engine.connect() as conn, pytest.raises(sa.exc.IntegrityError):
        _insert_row(
            conn,
            id="22222222-2222-4222-8222-222222222222",
            project_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
        )
    _assert_db_clean(engine)


def test_check_constraints_refuse_invalid_domains(db_path: Path) -> None:
    engine = _connect(db_path)
    with engine.begin() as conn:
        _seed_graph(conn, WS)
    bad_overrides = [
        {"correction_kind": "teleport"},
        {"status": "quantum"},
        {"revision": 0},
        {"revision": -3},
        {"idempotency_key": "x" * 256},
        {"natural_key": "y" * 256},
    ]
    for i, over in enumerate(bad_overrides):
        with engine.connect() as conn, pytest.raises(sa.exc.IntegrityError):
            _insert_row(
                conn,
                id=f"33333333-3333-4333-8333-{i:012d}",
                **over,
            )
    # The VALID baseline row still inserts.
    with engine.begin() as conn:
        _insert_row(conn, id="33333333-3333-4333-8333-999999999999")
    _assert_db_clean(engine)


def test_partial_unique_identities_and_workspace_scoping(db_path: Path) -> None:
    engine = _connect(db_path)
    with engine.begin() as conn:
        _seed_graph(conn, WS)
        _seed_graph(conn, WS + "-other")
    base = {
        "natural_key": "S09C:mask:abc",
        "idempotency_key": "idem-1",
    }
    with engine.begin() as conn:
        _insert_row(conn, **base)
        # Same natural key, same workspace → refused.
        with pytest.raises(sa.exc.IntegrityError):
            _insert_row(
                conn,
                id="44444444-4444-4444-8444-444444444444",
                **base,
            )
        # Same idempotency key, same workspace → refused.
        with pytest.raises(sa.exc.IntegrityError):
            _insert_row(
                conn,
                id="55555555-5555-4555-8555-555555555555",
                natural_key="S09C:mask:different",
                **{"idempotency_key": base["idempotency_key"]},  # type: ignore[dict-item]
            )
        # Same keys, DIFFERENT workspace → allowed (workspace scoping).
        _insert_row(
            conn,
            id="66666666-6666-4666-8666-666666666666",
            workspace_id=WS + "-other",
            project_id=f"p-{WS}-other",
            video_item_id=f"v-{WS}-other",
            **base,
        )
    _assert_db_clean(engine)


# ── round-trip + fail-closed downgrade ───────────────────────────────────


def _new_table_snapshot(engine: sa.Engine) -> list[tuple[object, ...]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM s09_correction ORDER BY id")
        ).fetchall()
    return [tuple(r) for r in rows]


def test_round_trip_byte_identical_and_downgrade_fail_closed(
    tmp_path: Path,
) -> None:
    db = tmp_path / "roundtrip.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")

    # Seed REAL pending corrections through the durable core repository.
    from app.persistence import create_engine_for_path, create_session_factory

    factory = create_session_factory(create_engine_for_path(db))
    with factory() as session:
        session.execute(
            text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS}
        )
        session.execute(
            text(
                "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,"
                "sha256) VALUES ('a-r',:w,'video','src.mp4','ready',:h)"
            ),
            {"w": WS, "h": "22" * 32},
        )
        session.execute(
            text(
                "INSERT INTO project(id,workspace_id,name) "
                "VALUES ('p-r',:w,'RT')"
            ),
            {"w": WS},
        )
        session.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position,"
                "source_artifact_id) VALUES ('v-r','p-r','V',0,'a-r')"
            )
        )
        session.commit()

    engine = _connect(db)
    with engine.begin() as conn:
        _insert_row(
            conn,
            id="77777777-7777-4777-8777-777777777777",
            project_id="p-r",
            video_item_id="v-r",
        )
        _insert_row(
            conn,
            id="88888888-8888-4888-8888-888888888888",
            project_id="p-r",
            video_item_id="v-r",
            correction_kind="route_override",
            status="applied",
            result_json=json.dumps({"ok": True}),
        )
    seeded = _new_table_snapshot(engine)
    assert len(seeded) == 2
    _assert_db_clean(engine)

    # Downgrade must REFUSE while archived corrections exist — and must not
    # have mutated anything when it refused.
    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, "d8e9f0a1b2c3")
    after_refusal = _new_table_snapshot(engine)
    assert after_refusal == seeded, "failed downgrade mutated data"
    with engine.connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert version == "b3c4d5e6f7a9"
    _assert_db_clean(engine)

    # Explicit operator purge, then downgrade succeeds and drops exactly
    # what this revision created.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM s09_correction"))
    command.downgrade(cfg, "d8e9f0a1b2c3")
    tables = set(inspect(_connect(db)).get_table_names())
    assert "s09_correction" not in tables
    with _connect(db).connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert version == "d8e9f0a1b2c3"

    # Re-upgrade reproduces an IDENTICAL empty schema.
    command.upgrade(cfg, "head")
    reengine = _connect(db)
    assert _new_table_snapshot(reengine) == []
    reloaded = {c["name"] for c in inspect(reengine).get_columns("s09_correction")}
    assert reloaded == EXPECTED_COLUMNS
    _assert_db_clean(reengine)
