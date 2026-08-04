"""FastAPI dependency injection — singleton services.

**Laziness (PM CHANGES_REQUESTED #2):** importing this module constructs
nothing.  ``_job_service`` is ``None`` until :func:`get_job_service` is
first called, and even then constructing a ``JobService`` is side-effect
free (no mkdir, no engine, no DB file, no threads).  The owned engine and
database are created only by the explicit application lifecycle
(``app.lifecycle`` / FastAPI lifespan / fixture setup) via
``JobService.initialize()`` / ``start_worker()``.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import AppConfig, config
from app.workflow.object_extraction_service import ObjectExtractionService
from app.workflow.project_workflow import ProjectWorkflowService
from app.workflow.render_service import FinalRenderService, PreviewRenderService
from app.workflow.replacement_service import ReplacementService
from app.workflow.segmentation_service import SegmentationService

if TYPE_CHECKING:
    from app.persistence.channels import ChannelService
    from app.persistence.projects import ProjectService
    from app.persistence.videos import VideoItemService
    from app.workflow.job_service import JobService

# Singletons shared across the application
_config: AppConfig = config
#: Durable job service (S02-T05 cutover).  Lazy: None until first access;
#: construction is side-effect free; initialization/worker start are
#: explicit application-lifecycle operations (app.lifecycle), never import
#: side effects (AC1).
_job_service: JobService | None = None
_channel_service: ChannelService | None = None
_project_service: ProjectService | None = None
_video_service: VideoItemService | None = None
_project_wf = ProjectWorkflowService(_config)
_seg_service = SegmentationService(_config)
_obj_extraction = ObjectExtractionService()
_replacement_service = ReplacementService(_project_wf)
_preview_render = PreviewRenderService()
_final_render = FinalRenderService()


def get_config() -> AppConfig:
    return _config


def get_job_service() -> JobService:
    """Return the process-wide durable JobService (lazy, explicit init)."""
    global _job_service
    if _job_service is None:
        from app.workflow.job_service import JobService

        _job_service = JobService()
    return _job_service


def get_channel_service() -> ChannelService:
    """Return the process-wide durable ChannelService (lazy).

    The session factory resolves from the durable database the app
    lifecycle initializes (same path as :func:`get_job_service`); tests
    inject ``deps._lifecycle_db`` / a patched ``deps._job_service`` so the
    channel service always targets the same isolated database.  Laziness
    means importing this module constructs nothing (S02-T05 AC1 pattern).
    """
    global _channel_service
    if _channel_service is None:
        from app.persistence import create_engine_for_path, create_session_factory
        from app.persistence.channels import ChannelService

        job_service = get_job_service()
        session_factory = getattr(job_service, "_session_factory", None)
        if session_factory is not None:
            factory = session_factory
        else:
            injected = getattr(_config, "project_root", None)
            from app.lifecycle import default_database_path

            factory = create_session_factory(
                create_engine_for_path(default_database_path(injected))
            )
        _channel_service = ChannelService(factory)
    return _channel_service


def get_project_service() -> ProjectService:
    """Return the process-wide durable ProjectService (lazy).

    The session factory resolves from the durable database the app
    lifecycle initializes (same path as :func:`get_channel_service`);
    tests inject ``deps._lifecycle_db`` / a patched ``deps._job_service``
    so the project service always targets the same isolated database.
    Laziness means importing this module constructs nothing.
    """
    global _project_service
    if _project_service is None:
        from app.persistence import create_engine_for_path, create_session_factory
        from app.persistence.projects import ProjectService

        job_service = get_job_service()
        session_factory = getattr(job_service, "_session_factory", None)
        if session_factory is not None:
            factory = session_factory
        else:
            injected = getattr(_config, "project_root", None)
            from app.lifecycle import default_database_path

            factory = create_session_factory(
                create_engine_for_path(default_database_path(injected))
            )
        _project_service = ProjectService(factory)
    return _project_service


def get_video_service() -> VideoItemService:
    """Return the process-wide durable VideoItemService (lazy).

    The session factory resolves from the durable database the app
    lifecycle initializes (same path as :func:`get_channel_service`);
    tests inject ``deps._lifecycle_db`` / a patched ``deps._job_service``
    so the video service always targets the same isolated database.
    Laziness means importing this module constructs nothing.
    """
    global _video_service
    if _video_service is None:
        from app.persistence import create_engine_for_path, create_session_factory
        from app.persistence.videos import VideoItemService

        job_service = get_job_service()
        session_factory = getattr(job_service, "_session_factory", None)
        if session_factory is not None:
            factory = session_factory
        else:
            injected = getattr(_config, "project_root", None)
            from app.lifecycle import default_database_path

            factory = create_session_factory(
                create_engine_for_path(default_database_path(injected))
            )
        _video_service = VideoItemService(factory)
    return _video_service


def get_project_workflow() -> ProjectWorkflowService:
    return _project_wf


def get_segmentation_service() -> SegmentationService:
    return _seg_service


def get_object_extraction_service() -> ObjectExtractionService:
    return _obj_extraction


def get_replacement_service() -> ReplacementService:
    return _replacement_service


def get_preview_render_service() -> PreviewRenderService:
    return _preview_render


def get_final_render_service() -> FinalRenderService:
    return _final_render


def get_db_session() -> Generator[Session, None, None]:
    """Yield a database Session from the process-wide session factory."""
    job_service = get_job_service()
    session_factory = getattr(job_service, "_session_factory", None)
    if session_factory is None:
        from app.lifecycle import default_database_path
        from app.persistence import create_engine_for_path, create_session_factory

        session_factory = create_session_factory(
            create_engine_for_path(default_database_path())
        )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_db_session)]
