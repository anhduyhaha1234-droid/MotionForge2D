"""Job status and cancel endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import get_job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job_status(job_id: str) -> dict:
    """Get job status."""
    job_svc = get_job_service()
    info = job_svc.get_job(job_id)
    if info is None:
        raise HTTPException(404, "Job not found")
    return info.model_dump()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Cancel a running job."""
    job_svc = get_job_service()
    success = job_svc.cancel_job(job_id)
    if not success:
        info = job_svc.get_job(job_id)
        if info is None:
            raise HTTPException(404, "Job not found")
        raise HTTPException(400, f"Cannot cancel job in state: {info.state.value}")
    return {"status": "cancel_requested", "job_id": job_id}
