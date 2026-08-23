"""S08-T02 correction — REAL SAM2.1 production-provider pipeline test.

Runs the actual local SAM2.1 inference path (correction finding B1):

- reads the production checkpoint READ-ONLY (never modified/copied;
  locator supplied via ``MOTIONFORGE_SAM2_CHECKPOINT``),
- decodes real frames from a managed synthetic video (fresh temp root),
- runs the FULL durable pipeline (submit -> worker -> publish) with the
  production provider as SERVER policy,
- asserts real pixel-derived output: mask PNGs with non-zero pixels,
  thumbnails that are real crops, occurrence bboxes from masks, SAM2.1
  provenance, association rows and the content endpoint.

GPU/inference capability is genuinely required: when the capability probe
fails (no CUDA / checkpoint absent), the test SKIPS with the honest reason
— the fail-closed paths are covered by the focused suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import cv2
import pytest

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import Artifact, ObjectOccurrence, ObjectRole, VideoItem
from app.services.object_extraction import (
    PROVIDER_PRODUCTION,
    SAM2_MODEL_VERSION,
    Sam2ExtractionProvider,
)

#: The production checkpoint, read-only.  Tests never write/copy it.
MAIN_CHECKPOINT = Path("C:/Users/Admin/MotionForge2D/models_checkpoints/sam2.1_hiera_large.pt")

pytestmark = pytest.mark.gpu


def _capability_ok() -> tuple[bool, str]:
    if not MAIN_CHECKPOINT.is_file():
        return False, f"checkpoint missing: {MAIN_CHECKPOINT}"
    provider = Sam2ExtractionProvider(checkpoint=MAIN_CHECKPOINT, env={})
    return provider.available(), "sam2.1 local backend ready"


def _make_cut_video(path: Path) -> Path:
    """A 2s/60-frame clip with ONE hard cut: blue (1s) -> red (1s)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "color=c=blue:duration=1.0:size=320x240:rate=30",
        "-f", "lavfi", "-i", "color=c=red:duration=1.0:size=320x240:rate=30",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return path


def _seed_video_with_media(svc, tmp_path: Path) -> tuple[str, str]:
    """Seed workspace/project/video + REAL managed source video + scenes."""

    from app.persistence.models import Project, Scene, Workspace

    video_path = _make_cut_video(tmp_path / "media" / "source.mp4")
    with svc.session_factory() as session:
        workspace = session.get(Workspace, DEFAULT_WORKSPACE_ID)
        if workspace is None:
            workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
            session.add(workspace)
        project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="SAM2 Project")
        video = VideoItem(
            project=project, title="source.mp4", position=0,
            width=320, height=240, duration_ms=2000, fps_num=30, fps_den=1,
        )
        session.add(project)
        session.flush()
        session.add(video)
        session.flush()
        rel = f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video.id}/import/source.mp4"
        managed_path = svc.managed_root / rel
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        managed_path.write_bytes(video_path.read_bytes())
        import hashlib

        sha = hashlib.sha256(managed_path.read_bytes()).hexdigest()
        source = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="video",
            relative_path=rel,
            state="ready",
            sha256=sha,
            size_bytes=managed_path.stat().st_size,
            mime_type="video/mp4",
        )
        session.add(source)
        session.flush()
        video.source_artifact_id = source.id
        session.add(Scene(
            video_item=video, position=0, start_frame=0, end_frame=29,
            start_time_ms=0, end_time_ms=999, status="pending",
        ))
        session.add(Scene(
            video_item=video, position=1, start_frame=30, end_frame=59,
            start_time_ms=1000, end_time_ms=1999, status="pending",
        ))
        session.commit()
        return project.id, video.id


def test_real_sam2_pipeline_through_durable_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client
) -> None:
    ok, reason = _capability_ok()
    if not ok:
        pytest.skip(f"SAM2.1 inference capability genuinely absent: {reason}")

    from sqlalchemy import select

    from app.persistence.models import ObjectRoleArtifact

    svc = deps._job_service
    assert svc is not None and svc.session_factory is not None
    # Server policy = production SAM2.1 provider (read-only MAIN checkpoint).
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_PROVIDER", PROVIDER_PRODUCTION)
    monkeypatch.setenv("MOTIONFORGE_SAM2_CHECKPOINT", str(MAIN_CHECKPOINT))
    project_id, video_id = _seed_video_with_media(svc, tmp_path)

    from app.persistence.jobs import JobRepository
    from app.services.object_extraction import submit_discover_objects

    def job_state(job_id: str) -> str:
        with svc.session_factory() as session:
            return JobRepository(session).get_job(job_id).state

    def run_worker(max_claims: int = 8) -> None:
        for _ in range(max_claims):
            if svc.worker.run_once() == 0:
                break

    result = submit_discover_objects(
        svc.session_factory,
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=project_id,
        video_item_id=video_id,
        source_sha256=None,
        generation="1",
        extractor_version="1.0.0",
        provider=PROVIDER_PRODUCTION,
        managed_root=svc.managed_root,
    )
    run_worker()
    assert job_state(result.job_id) == "completed"

    with svc.session_factory() as session:
        roles = session.scalars(select(ObjectRole)).all()
        assert len(roles) >= 1, "SAM2.1 must produce at least one candidate"
        occurrences = session.scalars(select(ObjectOccurrence)).all()
        assert len(occurrences) >= 1
        for occurrence in occurrences:
            assert occurrence.algorithm == "sam2.1-local"
            assert occurrence.algorithm_version == SAM2_MODEL_VERSION
            assert occurrence.confidence_source == "detector"
            assert 0.0 <= occurrence.confidence <= 1.0
            assert occurrence.bbox_w > 0 and occurrence.bbox_h > 0
        image_rows = session.scalars(
            select(Artifact).where(Artifact.kind == "image")
        ).all()
        assert len(image_rows) == 2 * len(roles)
        associations = session.scalars(select(ObjectRoleArtifact)).all()
        assert len(associations) == 2 * len(roles)
        for artifact in image_rows:
            assert artifact.mime_type == "image/png"
            assert artifact.sha256 and artifact.size_bytes

    # REAL bytes: decode the mask PNGs — non-zero pixels (real SAM mask).
    managed = svc.managed_root
    mask_count = 0
    for artifact in image_rows:
        target = managed / artifact.relative_path
        if artifact.relative_path.endswith("_mask.png"):
            img = cv2.imread(str(target), cv2.IMREAD_GRAYSCALE)
            assert img is not None
            assert img.shape == (240, 320)
            assert img.max() > 0, "SAM2 mask must contain non-zero pixels"
            mask_count += 1
        else:
            img = cv2.imread(str(target))
            assert img is not None and img.size > 0
    assert mask_count == len(roles)

    # The content endpoint serves the REAL bytes with ETag/nosniff.
    # (Uses the conftest client fixture — never a bare TestClient.)
    job_id = result.job_id
    with svc.session_factory() as session:
        first = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert first is not None
        artifact_id = first.id
    resp = client.get(
        f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/"
        f"{artifact_id}/content"
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["etag"] == f'"{first.sha256}"'
    assert resp.content.startswith(b"\x89PNG")
