"""S12-C1 W4 T03C — repro of the 2 real TypeErrors (unmocked path).

R1: ``ChunkSpec`` requires ``content_hash`` but
``publication._load_chunks`` never passes it → TypeError on the real path
(existing tests mock ``_load_chunks`` away, so they never see it).

R2: ``publication._require_ready`` + ``publish_export_run`` on the UNMOCKED
readiness path over a real migrated temp DB — captures the true traceback
(if any) instead of assuming one.
"""

from __future__ import annotations

import pytest

from app.services.s12_export import publication as pub


def test_R1_chunkspec_requires_content_hash() -> None:
    """Repro R1: ChunkSpec without content_hash must raise TypeError."""
    from app.services.s12_export.chunks import ChunkSpec

    with pytest.raises(TypeError) as exc:
        ChunkSpec(  # type: ignore[call-arg]
            chunk_index=0,
            order_index=0,
            core_start_frame=0,
            core_end_frame=49,
            overlap_before=0,
            overlap_after=5,
        )
    print(f"\nR1 TypeError message: {exc.value}")
    assert "content_hash" in str(exc.value)


def test_R1_load_chunks_fixed_no_typeerror(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Historical R1b: pre-fix _load_chunks raised TypeError.

    C2 removed the double-assembly path from publication entirely — the
    runner's private candidate is validated, never re-assembled.  The
    original pre-fix TypeError message is preserved in
    test_R1_chunkspec_requires_content_hash.
    """
    assert not hasattr(pub, "_load_chunks"), (
        "publication must not load chunks for assembly (C2 no double-assembly)"
    )


def test_R2_require_ready_unmocked_traceback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Repro R2: _require_ready unmocked over a real migrated temp DB.

    Not asserting a TypeError — capturing whatever the REAL path raises
    (TypeError, PublicationError, or success) with the true traceback.
    """
    import traceback

    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    from app.persistence import create_engine_for_path, create_session_factory

    root = Path(__file__).resolve().parent.parent.parent.parent
    db = tmp_path / "r2.db"
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as s:
        try:
            pub._require_ready(s, workspace_id="ws-x", project_id="p-x")
            outcome = "SUCCESS (no exception)"
        except Exception:
            outcome = "RAISED:\n" + traceback.format_exc()
    print(f"\nR2 outcome:\n{outcome}")
    assert isinstance(outcome, str)
