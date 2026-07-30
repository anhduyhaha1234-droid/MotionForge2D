"""FastAPI application — MotionForge 2D API server."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import frames, jobs, projects

app = FastAPI(
    title="MotionForge 2D API",
    version="0.2.0",
    description="Local-first 2D animation motion extraction and replacement",
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(frames.router)


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "service": "motionforge-2d"}
