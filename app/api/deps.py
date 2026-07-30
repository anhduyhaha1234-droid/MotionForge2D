"""FastAPI dependency injection — singleton services."""

from __future__ import annotations

from app.config import AppConfig, config
from app.workflow.job_service import JobService
from app.workflow.object_extraction_service import ObjectExtractionService
from app.workflow.project_workflow import ProjectWorkflowService
from app.workflow.render_service import FinalRenderService, PreviewRenderService
from app.workflow.replacement_service import ReplacementService
from app.workflow.segmentation_service import SegmentationService

# Singletons shared across the application
_config: AppConfig = config
_job_service = JobService()
_project_wf = ProjectWorkflowService(_config)
_seg_service = SegmentationService(_config)
_obj_extraction = ObjectExtractionService()
_replacement_service = ReplacementService(_project_wf)
_preview_render = PreviewRenderService()
_final_render = FinalRenderService()


def get_config() -> AppConfig:
    return _config


def get_job_service() -> JobService:
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
