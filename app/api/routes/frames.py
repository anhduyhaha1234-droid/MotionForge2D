"""Frame serving endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_project_workflow

router = APIRouter(prefix="/api/projects", tags=["frames"])


@router.get("/{project_id}/frames/{frame_index}")
def serve_frame(project_id: str, frame_index: int, scene_id: int = 0) -> FileResponse:
    """Serve a frame image file.

    Args:
        project_id: Project identifier.
        frame_index: Zero-based frame index.
        scene_id: Scene identifier (default 0).
    """
    pwf = get_project_workflow()
    proj_dir = pwf._project_dir(project_id)

    # Try exact frame number in the scene directory
    frame_path = proj_dir / "frames" / f"scene_{scene_id}" / f"frame_{frame_index:06d}.png"

    if not frame_path.exists():
        # Try to find by glob in any scene
        for scene_dir in sorted((proj_dir / "frames").glob("scene_*")):
            candidate = scene_dir / f"frame_{frame_index:06d}.png"
            if candidate.exists():
                frame_path = candidate
                break
        else:
            raise HTTPException(404, f"Frame {frame_index} not found")

    return FileResponse(str(frame_path), media_type="image/png")
