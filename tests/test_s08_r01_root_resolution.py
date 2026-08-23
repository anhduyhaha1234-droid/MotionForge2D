"""S08-R01 — managed-root resolution + QA/test fail-closed protection.

Codex sprint-exit finding (T06 incident 5): the durable JobService's
default managed root was the CWD-relative ``artifacts`` path — a QA
backend launched without ``cd`` wrote uploads/staging into the worktree
root.  Related incident class (T03/T04): a bare TestClient/default app
bootstrapped the protected MAIN database.

The fix (engine-level):

1. The default managed artifact root resolves from the CONFIGURED absolute
   project root (``<project root>/artifacts``) — never the process CWD.
   Worker, reconciler, chain orchestrator, APIs and manifests all resolve
   the SAME public ``JobService.managed_root`` / session factory.
2. QA/test fail-closed: in QA mode (``MOTIONFORGE_QA_MODE=1``) or under
   pytest (``PYTEST_CURRENT_TEST``), the effective project/managed roots
   must be explicit, absolute and isolated — the protected MAIN root
   (``~/MotionForge2D``) and CWD-relative roots are rejected with a
   stable error before any file/DB side effect.
3. QA launchers no longer rely on ``cd``: env-inline roots alone place
   the database and artifacts under the isolated run root regardless of
   CWD.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import PROTECTED_MAIN_ROOT
from app.persistence import create_engine_for_path, create_session_factory
from app.workflow.job_service import JobService


def _fresh_config_from_env() -> None:
    """Point ``deps._config`` at a NEW AppConfig built from the live env."""
    from app.api import deps
    from app.config import AppConfig

    deps._config = AppConfig()


def _patch_deps_config(cfg) -> None:  # type: ignore[no-untyped-def]
    from app.api import deps

    deps._config = cfg


# ── AC5: default root from the configured project root, never CWD ────────────


def test_default_managed_root_from_configured_project_root_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A default JobService resolves its managed root from the configured
    absolute project root — the process CWD is irrelevant."""
    from app.config import AppConfig

    proj = tmp_path / "proj-root"
    cfg = AppConfig(project_root=proj, models_dir=proj / "models", output_dir=proj / "out")
    _patch_deps_config(cfg)
    # Run from an unrelated CWD to prove it plays no role.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    svc = JobService()
    expected = proj / "artifacts"
    assert svc.managed_root == expected
    assert svc.managed_root.is_absolute()
    # The worker is bound to the SAME public root (S05-C04 binding).
    assert svc.worker is not None
    assert svc.worker._config.staging_root == expected  # noqa: SLF001


def test_deps_get_managed_root_fallback_uses_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """deps.get_managed_root() (character/API path) falls back to the
    configured absolute root when no JobService is bound yet."""
    from app.api import deps
    from app.config import AppConfig

    proj = tmp_path / "proj-root"
    cfg = AppConfig(project_root=proj, models_dir=proj / "models", output_dir=proj / "out")
    monkeypatch.setattr(deps, "_config", cfg)
    monkeypatch.setattr(deps, "_job_service", None)
    assert deps.get_managed_root() == proj / "artifacts"
    assert deps.get_managed_root().is_absolute()


def test_worker_orchestrator_manifest_share_public_service_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker staging root, orchestrator managed root, the API accessor
    and created job manifests all resolve the SAME public service root."""
    from app.api import deps
    from app.workflow.analyze_orchestrator import (
        get_analyze_orchestrator,
        reset_analyze_orchestrator,
    )

    reset_analyze_orchestrator()
    try:
        db = tmp_path / "share.db"
        from alembic import command
        from alembic.config import Config

        project_root_dir = Path(__file__).resolve().parent.parent
        cfg = Config(str(project_root_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(project_root_dir / "migrations"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
        command.upgrade(cfg, "head")
        factory = create_session_factory(create_engine_for_path(db))
        managed = tmp_path / "managed"
        svc = JobService(factory, managed_root=managed)
        monkeypatch.setattr(deps, "_job_service", svc)

        assert svc.worker._config.staging_root == managed  # noqa: SLF001
        assert deps.get_managed_root() == managed
        orchestrator = get_analyze_orchestrator()
        assert orchestrator.managed_root == svc.managed_root == managed
        assert orchestrator.session_factory is svc.session_factory

        info = svc.create_job(
            "ingest", input_manifest={"schema_version": 1, "probe": "root-check"}
        )
        with factory() as s:
            from app.persistence import JobRepository

            job = JobRepository(s).get_job(info.job_id)
            assert job.input_manifest["managed_root"] == str(managed)
            assert job.input_manifest["project_root"]  # absolute configured root
            assert Path(job.input_manifest["project_root"]).is_absolute()
    finally:
        reset_analyze_orchestrator()


# ── AC6: QA/test fail-closed protection ──────────────────────────────────────


def test_test_mode_rejects_default_main_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under pytest, a default-configured JobService (project root = the
    protected MAIN tree) is rejected at construction — the bare
    TestClient/default-app incident class can never bootstrap MAIN."""
    monkeypatch.delenv("MOTIONFORGE_ROOT", raising=False)
    from app.config import AppConfig

    main_cfg = AppConfig()  # env-free default = protected MAIN root
    assert Path(main_cfg.project_root).resolve() == PROTECTED_MAIN_ROOT.resolve()
    _patch_deps_config(main_cfg)

    with pytest.raises(RuntimeError, match="protected MAIN"):
        JobService()


def test_test_mode_rejects_relative_managed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under pytest, a CWD-relative managed root is rejected — the exact
    defect that wrote uploads/staging into the worktree root."""
    from app.config import AppConfig

    proj = tmp_path / "proj-root"
    cfg = AppConfig(project_root=proj, models_dir=proj / "models", output_dir=proj / "out")
    _patch_deps_config(cfg)
    factory = create_session_factory(create_engine_for_path(tmp_path / "rel.db"))
    with pytest.raises(RuntimeError, match="not absolute"):
        JobService(factory, managed_root="artifacts")


def test_test_mode_accepts_explicit_isolated_roots(tmp_path: Path) -> None:
    """An explicit absolute isolated managed root (the conftest pattern)
    constructs cleanly under pytest."""
    factory = create_session_factory(create_engine_for_path(tmp_path / "ok.db"))
    svc = JobService(factory, managed_root=tmp_path / "artifacts")
    assert svc.managed_root == tmp_path / "artifacts"


def test_qa_mode_rejects_protected_main_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA mode + MOTIONFORGE_ROOT=MAIN is rejected before any side effect."""
    monkeypatch.setenv("MOTIONFORGE_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_ROOT", str(PROTECTED_MAIN_ROOT))
    _fresh_config_from_env()
    with pytest.raises(RuntimeError, match="protected MAIN"):
        JobService()


def test_qa_mode_rejects_relative_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA mode + a relative MOTIONFORGE_ROOT is rejected."""
    monkeypatch.setenv("MOTIONFORGE_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_ROOT", "relative/run-root")
    _fresh_config_from_env()
    with pytest.raises(RuntimeError, match="relative"):
        JobService()


def test_qa_mode_requires_explicit_env_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA mode without an explicit MOTIONFORGE_ROOT env var is rejected
    (launchers may not rely on defaults)."""
    monkeypatch.setenv("MOTIONFORGE_QA_MODE", "1")
    monkeypatch.delenv("MOTIONFORGE_ROOT", raising=False)
    _fresh_config_from_env()
    with pytest.raises(RuntimeError, match="MOTIONFORGE_ROOT"):
        JobService()


def test_qa_launcher_without_cd_resolves_isolated_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC7: a QA launcher's env-inline roots alone place the database and
    the managed artifacts under the isolated run root — no ``cd`` is
    needed for storage correctness (the CWD is provably irrelevant)."""
    run_root = tmp_path / "qa-run-root"
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    monkeypatch.setenv("MOTIONFORGE_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_ROOT", str(run_root))
    monkeypatch.setenv("MOTIONFORGE_OUTPUT", str(run_root / "output"))
    monkeypatch.setenv("MOTIONFORGE_MODELS", str(run_root / "models"))
    _fresh_config_from_env()

    svc = JobService()  # the exact default path uvicorn app.main:app uses
    assert svc.managed_root == run_root / "artifacts"
    svc.initialize()  # explicit bootstrap under the env root only

    assert svc.database_path == run_root / "data" / "motionforge.db"
    assert (run_root / "data" / "motionforge.db").is_file()
    assert (run_root / "artifacts").is_dir()
    # Nothing landed under the process CWD.
    assert not (elsewhere / "artifacts").exists()
    assert not (elsewhere / "data").exists()


def test_production_mode_allows_default_main_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production processes (no QA flag, no pytest) keep the legitimate
    MAIN default — the guard never affects real production runs."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("MOTIONFORGE_QA_MODE", raising=False)
    monkeypatch.delenv("MOTIONFORGE_ROOT", raising=False)
    try:
        from app.config import AppConfig

        main_cfg = AppConfig()
        assert Path(main_cfg.project_root).resolve() == PROTECTED_MAIN_ROOT.resolve()
        _patch_deps_config(main_cfg)
        svc = JobService()  # no raise — production defaults are allowed
        assert svc.managed_root == PROTECTED_MAIN_ROOT / "artifacts"
    finally:
        # Restore the pytest marker for the rest of the session.
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_s08_r01_root_resolution.py")
