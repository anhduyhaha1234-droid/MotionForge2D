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

from typing import TYPE_CHECKING

from app.config import AppConfig, config
from app.workflow.object_extraction_service import ObjectExtractionService
from app.workflow.project_workflow import ProjectWorkflowService
from app.workflow.render_service import FinalRenderService, PreviewRenderService
from app.workflow.replacement_service import ReplacementService
from app.workflow.segmentation_service import SegmentationService

if TYPE_CHECKING:
    from app.workflow.job_service import JobService

# Singletons shared across the application
_config: AppConfig = config
#: Durable job service (S02-T05 cutover).  Lazy: None until first access;
#: construction is side-effect free; initialization/worker start are
#: explicit application-lifecycle operations (app.lifecycle), never import
#: side effects (AC1).
_job_service: JobService | None = None
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
