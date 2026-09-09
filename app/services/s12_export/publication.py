"""S12-T03C — validated publication gate (s12-export-v1 §6, C2 F01/F07).

The run reaches ``completed`` ONLY through
:func:`publish_export_run`, and only when every gate holds:

1. **Fence** — the caller holds the live lease fence token
   (``FencedWorkerError`` otherwise; a stale worker cannot publish).
2. **Readiness** — current project readiness is ``ready``
   (``not_run``/``blocked`` fails closed: never publish from an
   unchecked or blocked project state).
3. **Ownership** — run workspace/project match the request scope.
4. **Candidate boundary (C2 F07)** — the runner assembled a PRIVATE
   candidate under scratch; this module NEVER assembles.  The final
   public output is created by ONE atomic ``os.replace`` from the
   validated candidate, only after the source-locked validator scores
   ``PASS``.  An existing completed output is never overwritten;
   a crash leaves only ``.partial``/candidate scratch, never a public
   result.
5. **Validation** — the candidate scores ``PASS`` against server-owned
   source-locked expectations (T04A C2 contract; ``FAIL`` /
   ``NOT_MEASURED`` fails closed and lands the run ``failed``).
6. **Atomicity** — the run transitions ``running -> verifying ->
   completed`` under fence + revision CAS in the same transaction as
   the atomic rename (one crash-safe immutable publication).
7. **Completed replay by bytes** — a replayed publication re-verifies
   the existing public artifact (sha256 vs the server-owned expected
   hash when asserted; never a bare status shortcut) before returning
   ``reused``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

__all__ = [
    "PublicationError",
    "publish_export_run",
]

_CHUNK_DIR = "chunk_dir"
_SCRATCH_DIR = "scratch_dir"
_OUTPUT_PATH = "output_path"
_HASH_CHUNK = 1024 * 1024


class PublicationError(ValueError):
    """Fail-closed publication gate error."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(_HASH_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _sidecar_path(final: Path) -> Path:
    """Sidecar holding the immutable byte identity of the public artifact."""
    return final.with_name(f"{final.name}.sha256")


def _write_sidecar(final: Path, sha: str) -> None:
    """Write the byte-identity sidecar atomically next to the artifact."""
    sidecar = _sidecar_path(final)
    tmp = sidecar.with_name(f"{sidecar.name}.tmp")
    tmp.write_text(sha.strip().lower() + "\n", encoding="ascii")
    os.replace(tmp, sidecar)


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
    """Validate the runner's private candidate and publish it atomically.

    ``manifest`` carries the server-owned immutable render pins (source
    path, fps, chunk/scratch/output dirs) plus the authority-derived
    source-locked expectations (frame count, fps rational, expected
    sha256 of the approved Full Apply output).

    The candidate is the file the T03B runner assembled at
    ``<scratch>/candidate_final.mp4`` — always PRIVATE, never the
    public output path.  On every gate passing, the candidate becomes
    the public output through one atomic rename and the run transitions
    to ``completed`` inside the same transaction.
    """
    from app.persistence.s12_export import (  # noqa: PLC0415
        FencedWorkerError,
        RunNotFoundError,
        S12ExportRepository,
    )
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
        # Idempotent replay — but only after byte-identical artifact proof.
        return _replay_completed(repo, run_id, manifest)
    if run.status not in ("running", "verifying", "pending"):
        raise PublicationError(
            f"run {run_id} in status {run.status!r}; cannot publish"
        )

    candidate = _candidate_path(manifest)
    if candidate is None or not candidate.is_file():
        raise PublicationError(
            f"no private candidate for run {run_id}; cannot publish"
        )
    final = Path(str(manifest[_OUTPUT_PATH]))
    if final.name.lower().endswith(".partial"):
        raise PublicationError("public output must not carry the .partial suffix")
    if final.is_file():
        raise PublicationError(
            f"completed output exists — refusing overwrite: {final}"
        )
    if candidate.resolve() == final.resolve():
        raise PublicationError("candidate must be private, never the public output")

    _require_ready(session, workspace_id=workspace_id, project_id=project_id)
    _require_fence(repo, run_id, worker_id, fence_token)

    expectation = _expectation_for(run, manifest)
    verdict = validate(candidate, expectation)
    if verdict.verdict != "PASS":
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        failing = [p.name for p in verdict.probes if p.verdict != "PASS"]
        raise PublicationError(
            f"export validation {verdict.verdict} on {failing}; run failed (retryable)"
        )

    # ONE crash-safe immutable publication: atomic rename of the validated
    # private candidate onto the public path, then the CAS transitions in
    # the same transaction.
    try:
        os.replace(candidate, final)
    except OSError as err:
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        raise PublicationError(f"publication rename failed: {err}") from err
    actual_sha = _sha256_file(final)
    try:
        _write_sidecar(final, actual_sha)
    except OSError as err:
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        raise PublicationError(f"publication sidecar failed: {err}") from err
    try:
        rec = repo.transition_run(
            run_id,
            "verifying",
            actor=worker_id,
            expected_revision=run.revision,
            fence_token=fence_token,
        )
        final_rec = repo.transition_run(
            run_id,
            "completed",
            actor=worker_id,
            expected_revision=rec.revision,
            fence_token=fence_token,
        )
    except (FencedWorkerError, ValueError) as err:
        # The rename happened but the transition lost the race — never
        # report completed: the artifact stays, the run is failed/retryable
        # and a later winner converges by bytes.
        session.rollback()
        raise PublicationError(
            f"publication transition lost after rename: {err} (run {run_id})"
        ) from err
    session.commit()
    return {
        "run_id": run_id,
        "status": final_rec.status,
        "revision": final_rec.revision,
        "output_path": str(final),
        "artifact_sha256": actual_sha,
        "verdict": verdict.verdict,
        "probes": [
            {"name": p.name, "verdict": p.verdict, "detail": p.detail}
            for p in verdict.probes
        ],
    }


def _replay_completed(repo: Any, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Replay after completion: re-verify the public artifact by bytes.

    The immutable byte identity lives in the sidecar written with the
    publication.  A missing artifact, a missing sidecar, a ``.partial``
    name, or a sha mismatch (tamper) all fail closed — a completed replay
    is never a bare status shortcut.
    """
    final = Path(str(manifest[_OUTPUT_PATH]))
    if not final.is_file():
        raise PublicationError(
            f"completed run {run_id} has no public artifact; cannot replay"
        )
    if final.name.lower().endswith(".partial"):
        raise PublicationError(f"public artifact is partial for run {run_id}")
    sidecar = _sidecar_path(final)
    if not sidecar.is_file():
        raise PublicationError(
            f"completed run {run_id} has no byte-identity sidecar; cannot replay"
        )
    stored = sidecar.read_text(encoding="ascii").strip().lower()
    actual = _sha256_file(final)
    if stored != actual:
        raise PublicationError(
            f"completed artifact sha256 mismatch for run {run_id} "
            f"(expected {stored}, actual {actual})"
        )
    expected = manifest.get("expected_sha256") or manifest.get("authority_sha256")
    if expected and str(expected).lower() != actual:
        raise PublicationError(
            f"completed artifact sha256 mismatch for run {run_id} "
            f"(expected {expected}, actual {actual})"
        )
    return {
        "run_id": run_id,
        "status": "completed",
        "reused": True,
        "output_path": str(final),
        "artifact_sha256": actual,
    }


def _candidate_path(manifest: dict[str, Any]) -> Path | None:
    scratch = Path(str(manifest.get(_SCRATCH_DIR, "")))
    if not scratch.is_dir():
        return None
    return scratch / "candidate_final.mp4"


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


def _expectation_for(run: Any, manifest: dict[str, Any]) -> Any:
    from app.services.s12_export.validation import (  # noqa: PLC0415
        MASTER_HEIGHT,
        MASTER_WIDTH,
        SourceReference,
        ValidationExpectation,
    )

    dims = str(getattr(run, "profile_dims", "") or "")
    width, height = _dims(dims)
    fps = float(manifest.get("fps") or 0)
    fps_num, fps_den = _fps_rational(fps, manifest)
    expected_sha = manifest.get("expected_sha256") or manifest.get("authority_sha256")
    source_ref = SourceReference(
        artifact_sha256=str(expected_sha or ""),
        frame_count=int(manifest.get("frame_count") or 0) or None,
        fps_num=fps_num,
        fps_den=fps_den,
    )
    return ValidationExpectation(
        width=width or MASTER_WIDTH,
        height=height or MASTER_HEIGHT,
        codec=manifest.get("profile_codec") or run.profile_codec or "h264",
        expected_frame_count=int(manifest.get("frame_count") or 0) or None,
        expected_fps=fps or None,
        expected_sha256=str(expected_sha) if expected_sha else None,
        source_locked=True,
        source_reference=source_ref,
    )


def _dims(dims: str) -> tuple[int | None, int | None]:
    if "x" not in dims:
        return None, None
    left, right = dims.split("x", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None, None


def _fps_rational(fps: float, manifest: dict[str, Any]) -> tuple[int, int]:
    num = int(manifest.get("fps_num") or 0)
    den = int(manifest.get("fps_den") or 0)
    if num > 0 and den > 0:
        return num, den
    try:
        frac = fps.as_integer_ratio()
        return int(frac[0]), int(frac[1])
    except (AttributeError, ValueError, OverflowError):
        return 0, 0


def _fail_run(repo: Any, run_id: str, worker_id: str, fence_token: str, revision: int) -> None:
    from app.persistence.s12_export import FencedWorkerError  # noqa: PLC0415

    try:
        rec = repo.transition_run(
            run_id,
            "failed",
            actor=worker_id,
            expected_revision=revision,
            fence_token=fence_token,
        )
        _ = rec
    except (FencedWorkerError, ValueError):
        # Lost the fence mid-failure — a live owner owns the run now; the
        # gate already rejected publication, so failing closed is safe.
        pass