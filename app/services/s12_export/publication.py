"""S12-T03C — validated publication gate (s12-export-v1 §6).

The run reaches ``completed`` ONLY through
:func:`publish_export_run`, and only when every gate holds:

1. **Fence** — the caller holds the live lease fence token
   (``FencedWorkerError`` otherwise; a stale worker cannot publish).
2. **Readiness** — current project readiness is ``ready``
   (``not_run``/``blocked`` fails closed: never publish from an
   unchecked or blocked project state).
3. **Ownership** — run workspace/project match the request scope.
4. **Validation** — the assembled candidate scores ``PASS`` against
   manifest-derived expectations (``FAIL``/``NOT_MEASURED`` fails
   closed; never SQL-seed readiness or trust caller claims).
5. **Atomicity** — assemble refuses to overwrite an existing completed
   output; the run transitions ``running -> verifying -> completed``
   under fence + revision CAS.  Any failure lands on ``failed``
   (coherent, retryable) — never a fake ``completed``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "PublicationError",
    "publish_export_run",
]

_CHUNK_DIR = "chunk_dir"
_SCRATCH_DIR = "scratch_dir"
_OUTPUT_PATH = "output_path"


class PublicationError(ValueError):
    """Fail-closed publication gate error."""


def publish_export_run(
    session: Any,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    worker_id: str,
    fence_token: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Assemble, validate and publish one export run (fail-closed gates).

    ``manifest`` carries the server-owned immutable render pins (source
    path, fps, chunk/scratch/output dirs) plus manifest-derived
    expectations (frame count, profile dims/codec, expected sha256 when
    asserted).  Returns publication evidence on success.
    """
    from app.persistence.s12_export import (  # noqa: PLC0415
        FencedWorkerError,
        RunNotFoundError,
        S12ExportRepository,
    )
    from app.services.s12_export.stitch import assemble_run  # noqa: PLC0415
    from app.services.s12_export.validation import validate  # noqa: PLC0415

    repo = S12ExportRepository(session)
    try:
        run = repo.get_run(run_id)
    except RunNotFoundError as err:
        raise PublicationError(str(err)) from err
    if run.workspace_id != workspace_id or run.project_id != project_id:
        raise PublicationError(
            f"export run {run_id!r} not owned by workspace/project scope"
        )
    if run.status == "completed":
        # Idempotent replay: already published, converge on the winner.
        return {"run_id": run_id, "status": "completed", "reused": True}
    if run.status not in ("running", "verifying", "pending"):
        raise PublicationError(
            f"run {run_id} in status {run.status!r}; cannot publish"
        )
    _require_ready(session, workspace_id=workspace_id, project_id=project_id)
    _require_fence(repo, run_id, worker_id, fence_token)

    chunks = _load_chunks(repo, run_id, manifest)
    candidate = assemble_run(
        chunks,
        frame_count=int(run.frame_count),
        fps=float(manifest["fps"]),
        output_path=str(manifest[_OUTPUT_PATH]),
        audio_source=manifest.get("audio_source"),
        scratch_dir=str(manifest[_SCRATCH_DIR]),
    )
    expectation = _expectation_for(run, manifest)
    verdict = validate(candidate, expectation)
    if verdict.verdict != "PASS":
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        failing = [p.name for p in verdict.probes if p.verdict != "PASS"]
        raise PublicationError(
            f"export validation {verdict.verdict} on {failing}; run failed (retryable)"
        )
    try:
        rec = repo.transition_run(
            run_id,
            "verifying",
            actor=worker_id,
            expected_revision=run.revision,
            fence_token=fence_token,
        )
        final = repo.transition_run(
            run_id,
            "completed",
            actor=worker_id,
            expected_revision=rec.revision,
            fence_token=fence_token,
        )
    except (FencedWorkerError, ValueError) as err:
        raise PublicationError(str(err)) from err
    session.commit()
    return {
        "run_id": run_id,
        "status": final.status,
        "revision": final.revision,
        "candidate_path": str(candidate),
        "verdict": verdict.verdict,
        "probes": [
            {"name": p.name, "verdict": p.verdict, "detail": p.detail}
            for p in verdict.probes
        ],
    }


def _require_ready(session: Any, *, workspace_id: str, project_id: str) -> None:
    """Current project readiness must be ``ready`` (computed, never seeded)."""
    from app.persistence.readiness import compute_project_readiness  # noqa: PLC0415
    from app.workflow.qc_checks_handler import (  # noqa: PLC0415
        evidence_fingerprint,
        policy_bundle,
    )

    record = compute_project_readiness(
        session, workspace_id=workspace_id, project_id=project_id
    )
    videos = list(getattr(record, "videos", []) or [])
    if not videos:
        raise PublicationError("no videos in project; readiness not_run — cannot publish")
    bundle = policy_bundle()
    for video in videos:
        video_id = getattr(video, "video_item_id", None) or getattr(video, "id", None)
        if video_id is None:
            raise PublicationError("unaddressable video in readiness record — cannot publish")
        readiness = _check_run_readiness(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=str(video_id),
            evidence_fingerprint=evidence_fingerprint(
                session, workspace_id=workspace_id, video_item_id=str(video_id)
            ),
            policy_content_hash=str(bundle["policy_content_hash"]),
        )
        if readiness != "ready":
            raise PublicationError(
                f"project readiness {readiness!r} for video {video_id}; "
                "publication requires ready"
            )


def _check_run_readiness(session: Any, **kwargs: Any) -> str:
    from app.persistence.qc_check_runs import check_run_readiness  # noqa: PLC0415

    return str(check_run_readiness(session, **kwargs).status)  # type: ignore[arg-type]


def _require_fence(repo: Any, run_id: str, worker_id: str, fence_token: str) -> None:
    from app.persistence.s12_export import FencedWorkerError  # noqa: PLC0415

    try:
        lease = repo.get_lease(run_id)
    except Exception as err:
        raise PublicationError(f"no live lease for run {run_id}: {err}") from err
    if lease is None:
        raise PublicationError(f"no live lease for run {run_id}")
    if lease.worker_id != worker_id or lease.fence_token != fence_token:
        raise FencedWorkerError(
            f"fence mismatch for run {run_id}", run_id=run_id
        )


def _load_chunks(repo: Any, run_id: str, manifest: dict[str, Any]) -> list[Any]:
    from app.services.s12_export.stitch import (  # noqa: PLC0415
        ChunkMedia,
        ChunkSpec,
    )

    try:
        chunk_dir = Path(str(manifest[_CHUNK_DIR]))
    except KeyError as err:
        raise PublicationError(f"manifest missing chunk_dir: {err}") from err
    rows = [c for c in repo.list_chunks(run_id) if c.verified]
    if not rows:
        raise PublicationError(f"run {run_id} has no verified chunks; cannot publish")
    media: list[Any] = []
    for row in sorted(rows, key=lambda c: c.order_index):
        path = chunk_dir / f"chunk_{row.chunk_index:04d}.mp4"
        if not path.is_file():
            raise PublicationError(f"verified chunk file missing: {path.name}")
        media.append(
            ChunkMedia(
                spec=ChunkSpec(
                    chunk_index=int(row.chunk_index),
                    order_index=int(row.order_index),
                    core_start_frame=int(row.core_start_frame),
                    core_end_frame=int(row.core_end_frame),
                    overlap_before=int(row.overlap_before),
                    overlap_after=int(row.overlap_after),
                    content_hash=str(row.content_hash),
                    attempt=int(row.attempt),
                ),
                path=path,
            )
        )
    return media


def _expectation_for(run: Any, manifest: dict[str, Any]) -> Any:
    from app.services.s12_export.validation import (  # noqa: PLC0415
        MASTER_HEIGHT,
        MASTER_WIDTH,
        ValidationExpectation,
    )

    dims = str(getattr(run, "profile_dims", "") or "")
    width, height = MASTER_WIDTH, MASTER_HEIGHT
    if "x" in dims:
        try:
            width, height = (int(part) for part in dims.split("x", 1))
        except ValueError:
            width, height = MASTER_WIDTH, MASTER_HEIGHT
    expected_sha = manifest.get("expected_sha256")
    return ValidationExpectation(
        width=width,
        height=height,
        codec=str(getattr(run, "profile_codec", "") or "h264"),
        audio_policy=str(manifest.get("audio_policy", "either")),
        expected_frame_count=int(run.frame_count),
        expected_duration_sec=manifest.get("expected_duration_sec"),
        expected_sha256=str(expected_sha) if expected_sha else None,
    )


def _fail_run(repo: Any, run_id: str, worker_id: str, fence_token: str, revision: int) -> None:
    from app.persistence.s12_export import (  # noqa: PLC0415
        FencedWorkerError,
        S12ExportError,
    )

    try:
        rec = repo.transition_run(
            run_id,
            "failed",
            actor=worker_id,
            expected_revision=revision,
            fence_token=fence_token,
        )
        _ = rec
    except (FencedWorkerError, S12ExportError):
        return
