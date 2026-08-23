"""S05-C04-R2 — orchestrator lifecycle-binding regression tests (Codex finding 1).

Codex CHANGES_REQUESTED (finding 1, BLOCKER): ``get_analyze_orchestrator()``
used to create a COMPETING session factory whenever
``JobService.session_factory`` was ``None`` (a call before
``JobService.initialize()``), then cached the orchestrator keyed by
``JobService`` object identity — so the cached orchestrator permanently
kept the competing factory even after the real lifecycle initialization.

The correction (S05-C04-R2):

- the competing-factory fallback is GONE — the orchestrator receives its
  session factory and managed root ONLY through the initialized public
  ``JobService`` lifecycle binding (``JobService.session_factory`` /
  ``JobService.managed_root``);
- access before initialization FAILS CLOSED (``RuntimeError``) instead of
  silently creating a second engine/factory — no stale orchestrator can
  ever be cached before lifecycle init;
- the cache is still keyed by JobService object identity, but every cached
  orchestrator is now guaranteed to hold the EXACT authoritative factory.

These tests prove, on a REAL default ``JobService`` over a temporary
database:

1. ``get_analyze_orchestrator()`` before initialization raises
   (fail-closed) and caches nothing;
2. after ``JobService.initialize()`` the orchestrator binds the EXACT
   authoritative ``JobService.session_factory`` (object identity) and the
   service's ``managed_root`` (public properties — no private attribute is
   read anywhere);
3. no stale cached orchestrator survives lifecycle init: the orchestrator
   obtained after init runs (``ensure_started``/``stop``) and repeated
   access returns the same authoritative instance.

All storage is temporary: ``deps._config`` is pointed at ``tmp_path`` so
the default service's database is created under the temporary project
root only; the default managed root is explicitly bound under
``tmp_path`` in the explicit-service test, and the deps-default test
(S05-C04-R3, Codex finding 2) runs the whole default-service case with
``monkeypatch.chdir(tmp_path)`` — since S08-R01 AC5 the production
default resolves from the CONFIGURED absolute project root (never the
CWD), and the test additionally proves the CWD is irrelevant and the
worktree root is untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.workflow.analyze_orchestrator import (
    get_analyze_orchestrator,
    reset_analyze_orchestrator,
)


@pytest.fixture(autouse=True)
def _clean_orchestrator_state() -> None:
    """Start/end every test with a pristine process-wide orchestrator."""
    reset_analyze_orchestrator()
    yield
    reset_analyze_orchestrator()


@pytest.fixture()
def _tmp_app_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the app config at a temporary project root (isolation)."""
    from app.api import deps
    from app.config import AppConfig

    proj = tmp_path / "proj"
    cfg = AppConfig(
        project_root=proj,
        models_dir=proj / "models",
        output_dir=proj / "output",
    )
    monkeypatch.setattr(deps, "_config", cfg)
    return proj


def test_pre_init_access_fails_closed_then_binds_authoritative_factory(
    tmp_path: Path,
    _tmp_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Access before init raises; after init the orchestrator holds the
    EXACT authoritative JobService factory + managed root."""
    from app.api import deps
    from app.workflow.job_service import JobService

    managed = tmp_path / "managed"
    service = JobService(managed_root=managed)  # default construction:
    # session_factory is None until initialize() — the placeholder worker
    # and the owned engine are the REAL production default path.
    monkeypatch.setattr(deps, "_job_service", service)

    # ── Access BEFORE initialization: fail-closed, nothing cached. ──────
    with pytest.raises(RuntimeError, match="initialize"):
        get_analyze_orchestrator()
    assert service.session_factory is None  # still uninitialized

    # ── Initialize the default JobService (real Alembic bootstrap). ─────
    service.initialize()
    assert service.session_factory is not None
    # Isolation: the owned database lives under pytest temporary storage.
    assert service.database_path is not None
    assert service.database_path.resolve().is_relative_to(tmp_path.resolve())

    # ── Obtain the orchestrator: EXACT authoritative binding. ───────────
    orchestrator = get_analyze_orchestrator()
    # Object identity: the very callable the JobService initialized.
    assert orchestrator.session_factory is service.session_factory
    assert orchestrator.managed_root == service.managed_root == managed

    # The bound orchestrator is fully usable (start/stop the poll loop).
    orchestrator.ensure_started()
    assert orchestrator.running
    orchestrator.stop(timeout=5.0)
    assert not orchestrator.running

    # ── No stale cached orchestrator survives lifecycle init: the cached
    # instance IS the authoritative one (same object, same factory). ─────
    assert get_analyze_orchestrator() is orchestrator
    assert get_analyze_orchestrator().session_factory is service.session_factory


def test_deps_default_service_binds_authoritative_factory_after_lifecycle_init(
    tmp_path: Path,
    _tmp_app_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The REAL production accessor path: deps constructs the default
    ``JobService()`` lazily; pre-init access raises; after
    ``JobService.initialize()`` the orchestrator binds that service's
    authoritative factory — never a competing one.

    S05-C04-R3 (Codex finding 2) — updated by S08-R01 AC5: the default
    service's managed root is ``<configured project root>/artifacts`` (an
    absolute path derived from ``deps._config.project_root``) — NEVER the
    process CWD.  The whole default-service case still runs with the CWD
    changed away from the worktree so it is additionally proven that the
    CWD is irrelevant and NO ``artifacts`` directory is created or
    modified in the original (worktree) CWD.
    """
    from app.api import deps

    original_cwd = Path.cwd()
    assert original_cwd != tmp_path.resolve()

    # Snapshot the pre-existing worktree artifacts dir (M1A openapi.json,
    # tracked baseline) so the test can prove it is NOT modified.
    def _artifacts_snapshot() -> list[tuple[str, int, float]]:
        root = original_cwd / "artifacts"
        if not root.is_dir():
            return []
        return sorted(
            (p.relative_to(original_cwd).as_posix(), p.stat().st_size, p.stat().st_mtime)
            for p in root.rglob("*")
            if p.is_file()
        )

    before_snapshot = _artifacts_snapshot()

    # S08-R01 AC5: the default managed root derives from the configured
    # absolute project root — the CWD is irrelevant.  Change it anyway to
    # PROVE no file can land in the worktree root regardless of CWD.
    monkeypatch.chdir(tmp_path)

    # Fresh process-wide default service (as ``uvicorn app.main:app``
    # would construct it on first access).
    monkeypatch.setattr(deps, "_job_service", None)

    with pytest.raises(RuntimeError, match="initialize"):
        get_analyze_orchestrator()

    job_service = deps.get_job_service()
    assert job_service.session_factory is None
    job_service.initialize()  # default service: owned engine under tmp
    assert job_service.session_factory is not None

    # S08-R01 AC5 assertion (updated from the old CWD-relative
    # ``Path("artifacts")`` default): the default managed root is the
    # ABSOLUTE ``<configured project root>/artifacts`` path.
    expected_root = _tmp_app_config / "artifacts"
    assert job_service.managed_root == expected_root
    assert job_service.managed_root.is_absolute()

    orchestrator = get_analyze_orchestrator()
    assert orchestrator.session_factory is job_service.session_factory
    assert orchestrator.managed_root == job_service.managed_root

    # Isolation (finding 2): the RESOLVED managed root and the database
    # live inside pytest temporary storage, and the worktree root's
    # artifacts directory is untouched (no file created or modified).
    resolved_root = orchestrator.managed_root.resolve()
    assert resolved_root == expected_root.resolve()
    assert resolved_root.is_relative_to(tmp_path.resolve())
    assert expected_root.is_dir()  # the default root was created
    assert _artifacts_snapshot() == before_snapshot  # worktree untouched
    assert job_service.database_path is not None
    assert job_service.database_path.resolve().is_relative_to(tmp_path.resolve())

    orchestrator.ensure_started()
    assert orchestrator.running
    orchestrator.stop(timeout=5.0)
    assert get_analyze_orchestrator() is orchestrator
