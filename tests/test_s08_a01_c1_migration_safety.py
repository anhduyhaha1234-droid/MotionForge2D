"""S08-A01-C1 (F1) focused tests — safe fail-closed migration downgrade.

The A01 migration ``f7a8b9c0d1e2`` widens the ``object_role.kind`` CHECK
from 3 to 7 kinds.  C1 hardens the DOWNGRADE path so narrowing the CHECK
back to ``character|prop|other`` can never silently orphan (or implicitly
coerce) a row that uses a newer kind:

- (a) a legacy 3-kind DB still round-trips upgrade -> downgrade -> upgrade
  byte-identical (existing preserved behaviour);
- (b) a DB that HAS ``background``/``foreground``/``graphic``/``source_overlay``
  rows is REFUSED on downgrade ATOMICALLY — the downgrade exits non-zero,
  ``alembic_version`` stays ``f7a8b9c0d1e2`` (7-kind), and the table DDL and
  every row stay byte-identical (no partial mutation, no silent coercion);
- (c) ``PRAGMA integrity_check`` reports ``ok`` and revision/DDL/data are
  unchanged on BOTH paths (successful round-trip AND refused downgrade).

Run on fresh isolated roots only (custom sqlite file per test); the conftest
``client`` fixture is not needed here — this suite drives Alembic directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
PRE_A01 = "f6a7b8c9d0e1"
#: Revision identity of the migration under test — a frozen literal on
#: purpose; only the single head itself is discovered live via
#: :func:`_live_head` so newer revisions stacked on top never stale the
#: ``upgrade head -> alembic_version`` assertions.
A01 = "f7a8b9c0d1e2"
LEGACY = ("character", "prop", "other")
NEW = ("background", "foreground", "graphic", "source_overlay")


def _live_head() -> str:
    """Discover the CURRENT single Alembic head live from the script
    directory — never hard-coded, so new migrations on top of this one do
    not stale the assertion."""
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads}"
    return heads[0]


def _alembic_config(db: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _upgrade_pre_a01(db: Path) -> Config:
    cfg = _alembic_config(db)
    command.upgrade(cfg, PRE_A01)
    return cfg


def _seed_workspace(engine: object) -> None:
    from sqlalchemy.orm import Session

    from app.persistence import DEFAULT_WORKSPACE_ID as WS

    with Session(engine) as session:  # type: ignore[arg-type]
        session.execute(
            text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
            {"w": WS},
        )
        session.execute(
            text(
                "INSERT INTO project(id,workspace_id,name) "
                "VALUES ('p1',:w,'p') ON CONFLICT(id) DO NOTHING"
            ),
            {"w": WS},
        )
        session.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position) "
                "VALUES ('v1','p1','v',0) ON CONFLICT(id) DO NOTHING"
            )
        )
        session.commit()


def _seed_roles(
    engine: object, kinds: list[str], prefix: str = "Role"
) -> None:
    """Insert one object_role row per kind (unique name+id per call)."""
    import hashlib

    from sqlalchemy.orm import Session

    from app.persistence import DEFAULT_WORKSPACE_ID as WS

    with Session(engine) as session:  # type: ignore[arg-type]
        for idx, kind in enumerate(kinds):
            id_ = "r" + hashlib.sha1(f"{prefix}-{idx}-{kind}".encode()).hexdigest()[:30]
            session.execute(
                text(
                    "INSERT OR REPLACE INTO object_role("
                    "id,workspace_id,project_id,video_item_id,"
                    "source_generation,name,kind) VALUES "
                    "(:id,:w,'p1','v1','1',:n,:k)"
                ),
                {
                    "id": id_,
                    "w": WS,
                    "n": f"Legacy-{prefix}-{idx}-{kind}",
                    "k": kind,
                },
            )
        session.commit()


def _role_rows(engine: object) -> list[tuple[str, str, str]]:
    with engine.connect() as conn:  # type: ignore[attr-defined]
        return sorted(
            (str(a), str(b), str(c))
            for (a, b, c) in conn.execute(
                text("SELECT id, name, kind FROM object_role ORDER BY id")
            ).all()
        )


def _ddl(engine: object) -> str:
    with engine.connect() as conn:  # type: ignore[attr-defined]
        return str(
            conn.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='object_role'"
                )
            ).scalar()
        )


def _integrity(engine: object) -> list[tuple[str, ...]]:
    with engine.connect() as conn:  # type: ignore[attr-defined]
        return [tuple(r) for r in conn.execute(text("PRAGMA integrity_check")).fetchall()]


def _revision(engine: object) -> str | None:
    with engine.connect() as conn:  # type: ignore[attr-defined]
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _assert_7_kind(ddl: str) -> None:
    assert "'source_overlay'" in ddl
    assert "'background'" in ddl


def _assert_3_kind(ddl: str) -> None:
    assert "'source_overlay'" not in ddl
    assert "'background'" not in ddl
    assert "'character'" in ddl and "'prop'" in ddl and "'other'" in ddl


# ── (a) legacy 3-kind DB round-trips byte-identical ────────────────────────


def test_legacy_3_kind_roundtrip_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    cfg = _upgrade_pre_a01(db)
    engine = create_engine_for_path(db)
    _seed_workspace(engine)
    _seed_roles(engine, list(LEGACY))
    baseline = _role_rows(engine)
    assert len(baseline) == 3

    # upgrade A01 -> 7-kind
    command.upgrade(cfg, "head")
    assert _role_rows(engine) == baseline
    assert _revision(engine) == _live_head()
    _assert_7_kind(_ddl(engine))
    assert _integrity(engine)[0][0] == "ok"

    # downgrade -> 3-kind (legacy rows only: SAFE, no new kinds present)
    command.downgrade(cfg, PRE_A01)
    assert _role_rows(engine) == baseline
    assert _revision(engine) == PRE_A01
    _assert_3_kind(_ddl(engine))
    assert _integrity(engine)[0][0] == "ok"

    # re-upgrade -> 7-kind again, rows still byte-identical
    command.upgrade(cfg, "head")
    assert _role_rows(engine) == baseline
    assert _revision(engine) == _live_head()
    _assert_7_kind(_ddl(engine))
    assert _integrity(engine)[0][0] == "ok"


# ── (b) new-kind rows REFUSE downgrade atomically ──────────────────────────


def test_new_kind_rows_refuse_downgrade_atomic(tmp_path: Path) -> None:
    db = tmp_path / "newkinds.db"
    cfg = _upgrade_pre_a01(db)
    engine = create_engine_for_path(db)
    _seed_workspace(engine)
    _seed_roles(engine, list(LEGACY))
    command.upgrade(cfg, "head")  # 7-kind CHECK active
    _seed_roles(engine, list(NEW), prefix="New")  # rows using the NEW kinds
    before_rows = _role_rows(engine)
    before_ddl = _ddl(engine)
    assert len(before_rows) == 7  # 3 legacy + 4 new
    _assert_7_kind(before_ddl)
    assert _revision(engine) == _live_head()

    # downgrade MUST fail closed BEFORE any mutation: it raises, the exit is
    # non-zero (pytest.raises proves the failure surfaced), and the DB is
    # left byte-identical.
    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE_A01)

    # ATOMIC refusal: revision = f7a8b9c0d1e2 (7-kind), DDL unchanged,
    # every row unchanged (incl. all 4 new-kind rows), integrity ok.
    assert _revision(engine) == A01
    assert _ddl(engine) == before_ddl
    assert _role_rows(engine) == before_rows
    assert _integrity(engine)[0][0] == "ok"

    # And an explicit re-upgrade (legacy + new rows all still present) is a
    # byte-identical no-op — the DB was never partially mutated.
    command.upgrade(cfg, "head")
    assert _ddl(engine) == before_ddl
    assert _role_rows(engine) == before_rows
    assert _revision(engine) == _live_head()
    assert _integrity(engine)[0][0] == "ok"


# ── (c) integrity + DDL/data unchanged on both paths (also covered above) ──


def test_refused_downgrade_leaves_info_schema_and_foreign_keys_intact(
    tmp_path: Path,
) -> None:
    """Reject even a SINGLE new-kind row (edge: one row of each new kind)."""
    db = tmp_path / "one.db"
    cfg = _upgrade_pre_a01(db)
    engine = create_engine_for_path(db)
    _seed_workspace(engine)
    _seed_roles(engine, ["character"])
    command.upgrade(cfg, "head")
    _seed_roles(engine, [NEW[0]])  # one 'background' row
    before_ddl = _ddl(engine)
    before_rows = _role_rows(engine)

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg, PRE_A01)

    assert _revision(engine) == A01
    assert _ddl(engine) == before_ddl
    assert _role_rows(engine) == before_rows
    assert _integrity(engine)[0][0] == "ok"
    # No FK violations on the untouched DB.
    with engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    assert fk == []
