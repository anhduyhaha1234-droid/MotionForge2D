"""Focused durable orchestration service for the approved T02→T03→T04 chain.

S05-C02 correction: chain progression is owned here — a durable workflow
service — NOT by the projects route and NOT by the read-only chain-state
endpoint.  One ``POST /analyze`` submits the ``ANALYZE_MEDIA`` import Job
(S05-T02); a background poll loop (``AnalyzeChainOrchestrator.start``) and
explicit ``advance_once`` passes materialize ``GENERATE_PROXY`` (S05-T03)
and the ``ANALYZE_MEDIA`` scene_detect Job (S05-T04) as each predecessor
durably completes — under backend ownership, with zero reliance on browser
polling.  ``GET`` (the route) calls :meth:`AnalyzeChainOrchestrator.chain_state`
which is strictly read-only: repeated/concurrent reads cause zero database
mutations.

Chain identity is bound to immutable input evidence: the **source file's
SHA-256** (computed streaming at submission — the preflight checksum policy,
VIDEO_PREFLIGHT_CONTRACT §5.4) plus the **generation/version**.  Every chain
query is scoped by that identity (the deterministic idempotency-key suffix),
so replacing the project source with a different video yields a new identity
→ a new chain; the previous chain's terminal rows and artifacts are never
silently reused.

This module uses ONLY the public submit surfaces of the approved services
(``video_import.submit_import``, ``video_proxy.submit_proxy``,
``scene_detector.submit_scene_detection``) and the public durable repository
(``JobRepository.create_successor``) — no JobService private members are
accessed from routes, and no job-state-machine semantics are changed.

S05-C03: the orchestrator's lifecycle is owned by the FastAPI application
lifespan (``app/api/app.py``) — startup calls ``ensure_started()`` whose
synchronous scan resumes every incomplete chain from durable rows, shutdown
calls ``stop()``.  Replacing the project source with a different SHA
supersedes the VideoItem (archive + new VideoItem) so the new chain reaches
completed with distinct identity/outputs while old jobs, artifacts and
scene rows stay immutable.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select

from app.persistence import IdempotencyKeyInUse, JobRepository, StepInput
from app.persistence.models import (
    Job,
    JobStep,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.services import scene_detector, video_import, video_proxy

log = logging.getLogger("motionforge.analyze_orchestrator")

#: UI-facing chain steps, in execution order.  The step codes are the
#: approved durable step codes themselves: ``import`` (S05-T02),
#: ``proxy`` (S05-T03), ``scene_detect`` (S05-T04).
CHAIN_STEP_ORDER = ("import", "proxy", "scene_detect")

#: The durable workspace the API chain runs in (legacy project workflow).
_CHAIN_WORKSPACE_ID = "default"

_IMPORT_KEY_PREFIX = f"{video_import.JOB_TYPE_ANALYZE_MEDIA}:video_item:"
_SCENE_KEY_PREFIX = f"{video_import.JOB_TYPE_ANALYZE_MEDIA}:scene_detect:video_item:"


def _sha256_file_streaming(path: Path) -> str:
    """Streaming SHA-256 of a source file (1 MiB chunks, preflight policy)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class AdvanceReport:
    """Result of one orchestration pass (never raises)."""

    scanned: int = 0
    advanced: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "advanced": self.advanced,
            "errors": list(self.errors),
        }


class AnalyzeChainOrchestrator:
    """Durable owner of the T02→T03→T04 chain progression for one database.

    Construction is side-effect free (no threads, no sessions, no files).
    The background poll loop is created only by :meth:`start` /
    :meth:`ensure_started`; :meth:`advance_once` never touches threading.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        managed_root: str | Path,
        *,
        poll_interval: float = 1.0,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._managed_root = Path(str(managed_root))
        self._poll_interval = float(poll_interval)
        self._sleeper = sleeper or time.sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public binding contract (S05-C04-R2) ────────────────────────────

    @property
    def session_factory(self) -> Callable[[], Any]:
        """The authoritative session factory this orchestrator is bound to.

        Public read-only accessor for the S05-C04 binding contract: the
        orchestrator receives its factory and managed root ONLY through
        the initialized public ``JobService`` lifecycle binding — never a
        competing/private factory (S05-C04-R2, Codex finding 1).  Callers
        use this to prove the orchestrator resolves the EXACT factory the
        job service initialized.
        """
        return self._session_factory

    @property
    def managed_root(self) -> Path:
        """The managed artifact root this orchestrator is bound to (public)."""
        return self._managed_root

    # ── Background loop (backend-owned progression) ─────────────────────

    @property
    def running(self) -> bool:
        """True while the background poll loop is alive."""
        return self._thread is not None and self._thread.is_alive()

    def ensure_started(self) -> None:
        """Idempotent lazy start of the background progression loop."""
        if not self.running:
            self.start()

    def start(self) -> None:
        """Start the daemon poll loop that advances every chain on schedule.

        Startup scan-and-resume (S05-C03): one synchronous idempotent
        advance pass runs BEFORE the loop thread starts, so process boot
        materializes the next Job of every incomplete chain immediately —
        without waiting for the first poll tick and without any POST, GET,
        browser polling or manual ``advance_once`` call by callers.  The
        pass is lease/fence-safe (the repository's owner-scoped idempotency
        keys make concurrent passes safe) and never raises.
        """
        if self.running:
            return
        self.advance_once()
        self._stop = threading.Event()
        thread = threading.Thread(
            target=self._run_loop,
            name="analyze-chain-orchestrator",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal and join the poll loop (shutdown, AC1 pattern)."""
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=timeout)
        self._thread = None

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                report = self.advance_once()
                if report.errors:
                    for error in report.errors:
                        log.warning("analyze orchestrator advance error: %s", error)
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                log.error("analyze orchestrator loop failure: %s", exc)
            self._sleeper(self._poll_interval)

    # ── Submission (one POST drives the whole chain) ────────────────────

    def submit_chain(
        self,
        project_id: str,
        source_path: str | Path,
        generation: str = "1",
        title: str | None = None,
    ) -> dict[str, object]:
        """Submit the chain for one project source and return chain state.

        The source file's SHA-256 is computed streaming at submission and
        becomes part of the import idempotency key
        (``ANALYZE_MEDIA:video_item:<id>:<sha>:<generation>``) — the chain
        identity is bound to immutable input evidence.  Re-submitting the
        SAME bytes reuses the existing chain (contract §8.1); submitting a
        DIFFERENT source yields a new identity → a new chain (never a
        silent reuse of the previous video's results).

        Submission-only: the request never runs the pipeline.  The
        background loop (started here) advances T02→T03→T04 under backend
        ownership.
        """
        source = Path(source_path)
        if not source.is_file():
            from app.services.video_import import CODE_INPUT_MISSING, VideoImportError

            raise VideoImportError(
                CODE_INPUT_MISSING,
                f"source file does not exist: {source}",
                location="source file path",
            )
        source_sha256 = _sha256_file_streaming(source)
        name = title or source.name
        item = self._resolve_chain_video_item(project_id)
        if item is not None:
            identity = self._current_identity(item.id)
            if identity is not None and identity[0] != source_sha256:
                # Source replacement (different SHA): an explicit
                # VideoItem/version supersession lifecycle.  The previous
                # VideoItem is ARCHIVED — its jobs, artifacts and scene
                # rows stay immutable and queryable (archive never
                # cascades, PERSISTENCE_DOMAIN_CONTRACT §5) — and a NEW
                # VideoItem becomes the pipeline unit for the new source,
                # owning fresh scene rows.  The new chain therefore
                # reaches completed without overwriting or silently
                # reusing old evidence (S05-C03).
                item = self._supersede_video_item(project_id, item, name)
        if item is None:
            item = self._ensure_durable_shell(project_id, name)
        with contextlib.suppress(IdempotencyKeyInUse):
            # An active chain already exists for this exact identity — the
            # repository returns/rejects per contract §8.1; reuse the chain.
            video_import.submit_import(
                self._session_factory,
                workspace_id=_CHAIN_WORKSPACE_ID,
                project_id=project_id,
                video_item_id=item.id,
                source_path=source,
                source_sha256=source_sha256,
                generation=generation,
                managed_root=self._managed_root,
                title=name,
            )
        self.ensure_started()
        self.advance_once(project_id=project_id)
        return self.chain_state(project_id, generation)

    # ── Read-only chain state (GET surface — zero mutations) ────────────

    def chain_state(self, project_id: str, generation: str = "1") -> dict[str, object]:
        """Backend-owned chain state — READ-ONLY.

        Every value is read from durable rows; this method performs no
        inserts, updates, deletes or commits.  Repeated/concurrent calls
        cause zero database mutations.
        """
        item = self._resolve_chain_video_item(project_id)
        if item is None:
            return self._idle_response(project_id, generation)
        identity = self._current_identity(item.id)
        if identity is None:
            return self._idle_response(project_id, generation)
        jobs = self._chain_jobs(item.id, identity)
        newest = {
            kind: (jobs[kind][0] if jobs[kind] else None) for kind in CHAIN_STEP_ORDER
        }
        steps = {
            kind: self._chain_step_payload(kind, newest[kind])
            for kind in CHAIN_STEP_ORDER
        }
        statuses: list[str | None] = []
        for kind in CHAIN_STEP_ORDER:
            job = newest[kind]
            statuses.append(job.state if job is not None else None)

        if all(s == "completed" for s in statuses):
            chain_status = "completed"
        elif any(s == "failed" for s in statuses):
            chain_status = "failed"
        elif any(s == "cancelled" for s in statuses):
            chain_status = "cancelled"
        elif any(
            s in ("pending", "queued", "running", "cancelling") for s in statuses
        ) or any(s is not None for s in statuses):
            chain_status = "running"
        else:
            chain_status = "idle"

        active_step: str | None = None
        for kind in CHAIN_STEP_ORDER:
            job = newest[kind]
            if job is not None and job.state in (
                "pending",
                "queued",
                "running",
                "cancelling",
            ):
                active_step = kind
                break
        if active_step is None and chain_status != "completed":
            for kind in CHAIN_STEP_ORDER:
                job = newest[kind]
                if job is None or job.state not in ("completed", "skipped"):
                    active_step = kind
                    break

        progress = 0.0
        for kind in CHAIN_STEP_ORDER:
            progress += self._chain_step_progress(newest[kind])
        progress = round(progress / len(CHAIN_STEP_ORDER), 2)

        # Artifact ids are the CURRENT chain's own published evidence
        # (checkpoint ``published.artifact_id``) — never a stale owner link
        # from a replaced source's chain.
        source_artifact_id = (
            self._published_artifact_id(newest["import"].id)
            if newest["import"] is not None
            else None
        )
        proxy_artifact_id = (
            self._published_artifact_id(newest["proxy"].id)
            if newest["proxy"] is not None
            else None
        )
        scenes_count = self._scenes_count(item.id)

        return {
            "project_id": project_id,
            "video_item_id": item.id,
            "generation": generation,
            "source_name": self._chain_source_name(newest["import"]),
            "source_sha256": identity[0],
            "chain_status": chain_status,
            "active_step": active_step,
            "progress": progress,
            "steps": steps,
            "source_artifact_id": source_artifact_id,
            "proxy_artifact_id": proxy_artifact_id,
            "scenes_count": scenes_count,
        }

    def _idle_response(self, project_id: str, generation: str) -> dict[str, object]:
        return {
            "project_id": project_id,
            "video_item_id": None,
            "generation": generation,
            "source_name": None,
            "source_sha256": None,
            "chain_status": "idle",
            "active_step": None,
            "progress": 0.0,
            "steps": {
                kind: self._chain_step_payload(kind, None)
                for kind in CHAIN_STEP_ORDER
            },
            "source_artifact_id": None,
            "proxy_artifact_id": None,
            "scenes_count": None,
        }

    # ── Retry (successor path, §8.5) ────────────────────────────────────

    def retry_chain(
        self, project_id: str, generation: str = "1"
    ) -> dict[str, object] | None:
        """Create the successor of the newest failed/cancelled chain Job.

        Owner validation: only Jobs belonging to this project's chain (the
        VideoItem's import/proxy/scene_detect Jobs for the CURRENT chain
        identity in workspace ``default``) are retryable.  Duplicate retries
        are idempotent: the already-created successor is reused (never a
        409/500 without a path).  The predecessor row stays immutable.
        Returns None when there is nothing to retry.
        """
        item = self._resolve_chain_video_item(project_id)
        if item is None:
            return None
        identity = self._current_identity(item.id)
        if identity is None:
            return None
        jobs = self._chain_jobs(item.id, identity)
        target: Any | None = None
        retry_in_flight = False
        for kind in CHAIN_STEP_ORDER:
            newest = jobs[kind][0] if jobs[kind] else None
            if newest is not None and newest.state in ("failed", "cancelled"):
                target = newest
                break
            if (
                newest is not None
                and newest.state in ("pending", "queued", "running", "cancelling")
                and newest.predecessor_job_id is not None
            ):
                # A successor for a terminal predecessor is already in
                # flight — a duplicate retry reuses it (contract §8.5).
                retry_in_flight = True
        if target is None and not retry_in_flight:
            return None
        if target is None:
            return self.chain_state(project_id, generation)
        with self._session_factory() as session:
            repo = JobRepository(session)
            successor_id = session.scalar(
                select(Job.id).where(Job.predecessor_job_id == target.id)
            )
            if successor_id is None:
                steps = [
                    StepInput(
                        step_code=step.step_code,
                        position=step.position,
                        step_type=step.step_type,
                    )
                    for step in repo.list_steps(target.id)
                ]
                try:
                    repo.create_successor(
                        predecessor_job_id=target.id,
                        input_manifest=json.loads(target.input_manifest_json or "{}"),
                        idempotency_key=target.idempotency_key,
                        input_generation=target.input_generation,
                        steps=steps,
                    )
                except IdempotencyKeyInUse:
                    # A concurrent retry won — the successor exists now.
                    session.rollback()
                else:
                    session.commit()
        return self.chain_state(project_id, generation)

    # ── Advancement (the durable owner of T02→T03→T04) ──────────────────

    def advance_once(self, project_id: str | None = None) -> AdvanceReport:
        """One idempotent pass materializing the next chain Job per chain.

        With *project_id* only that project's chain is considered; without
        it every chain in the database is scanned (the background loop).
        Each step's Job is created at most once — the repository's
        owner-scoped idempotency keys make concurrent passes safe (the
        loser receives ``IdempotencyKeyInUse`` and is ignored).  A
        failed/cancelled step is never auto-recreated; retry is explicit.
        Never raises: per-chain failures are collected on the report.
        """
        if project_id is not None:
            item = self._resolve_chain_video_item(project_id)
            candidates = [item] if item is not None else []
        else:
            candidates = self._chain_video_items()
        report = AdvanceReport(scanned=len(candidates))
        for item in candidates:
            try:
                if self._advance_item(item):
                    report.advanced += 1
            except Exception as exc:  # noqa: BLE001 - collected, never raised
                message = f"video_item {item.id}: {type(exc).__name__}: {exc}"
                log.warning("analyze chain advance failed: %s", message)
                report.errors.append(message)
        return report

    def _advance_item(self, item: Any) -> bool:
        """Create the next chain Job of one VideoItem when due.  Returns
        True when a Job was created by THIS pass."""
        if item.status == "archived":
            return False  # superseded source: frozen, never advanced
        identity = self._current_identity(item.id)
        if identity is None:
            return False
        jobs = self._chain_jobs(item.id, identity)
        import_job = jobs["import"][0] if jobs["import"] else None
        if import_job is None:
            return False  # nothing submitted yet
        created = False

        if import_job.state == "completed":
            proxy_job = jobs["proxy"][0] if jobs["proxy"] else None
            if proxy_job is None:
                source_artifact_id = self._published_artifact_id(import_job.id)
                if source_artifact_id is not None:
                    with contextlib.suppress(IdempotencyKeyInUse):
                        # A concurrent pass may have created it — reuse.
                        video_proxy.submit_proxy(
                            self._session_factory,
                            workspace_id=_CHAIN_WORKSPACE_ID,
                            project_id=item.project_id,
                            video_item_id=item.id,
                            source_artifact_id=source_artifact_id,
                            generation=identity[1],
                            managed_root=self._managed_root,
                            title="proxy",
                        )
                        created = True

        proxy_job = jobs["proxy"][0] if jobs["proxy"] else None
        if proxy_job is not None and proxy_job.state == "completed":
            scene_job = jobs["scene_detect"][0] if jobs["scene_detect"] else None
            if scene_job is None:
                source_artifact_id = self._published_artifact_id(import_job.id)
                proxy_artifact_id = self._published_artifact_id(proxy_job.id)
                if source_artifact_id is not None and proxy_artifact_id is not None:
                    with contextlib.suppress(IdempotencyKeyInUse):
                        # A concurrent pass may have created it — reuse.
                        scene_detector.submit_scene_detection(
                            self._session_factory,
                            workspace_id=_CHAIN_WORKSPACE_ID,
                            project_id=item.project_id,
                            video_item_id=item.id,
                            source_artifact_id=source_artifact_id,
                            proxy_artifact_id=proxy_artifact_id,
                            generation=identity[1],
                            managed_root=self._managed_root,
                            title="scene_detect",
                        )
                        created = True
        return created

    # ── Identity and durable-row helpers ────────────────────────────────

    def _current_identity(self, video_item_id: str) -> tuple[str, str] | None:
        """The (source_sha256, generation) of the newest import Job.

        The newest ``ANALYZE_MEDIA`` import Job of the VideoItem defines the
        CURRENT chain identity (submissions always bind the source SHA-256).
        For legacy Jobs created before the SHA binding, the checkpoint's
        published SHA-256 (the durable content evidence) is used.
        """
        with self._session_factory() as session:
            import_job = session.scalar(
                select(Job)
                .where(
                    Job.workspace_id == _CHAIN_WORKSPACE_ID,
                    Job.owner_type == "video_item",
                    Job.owner_id == video_item_id,
                    Job.idempotency_key.like(
                        f"{_IMPORT_KEY_PREFIX}{video_item_id}:%"
                    ),
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )
        if import_job is None:
            return None
        generation = import_job.input_generation or "1"
        sha: str | None = None
        try:
            manifest = json.loads(import_job.input_manifest_json or "{}")
        except (ValueError, TypeError):
            manifest = {}
        if isinstance(manifest, dict):
            candidate = manifest.get("source_sha256")
            if isinstance(candidate, str) and len(candidate) == 64:
                sha = candidate
        if sha is None:
            published = self._step_checkpoint(import_job.id).get("published") or {}
            candidate = published.get("sha256")
            if isinstance(candidate, str) and len(candidate) == 64:
                sha = candidate
        if sha is None:
            return None
        return (sha, generation)

    def _chain_jobs(
        self, video_item_id: str, identity: tuple[str, str]
    ) -> dict[str, list[Any]]:
        """All chain Jobs of one VideoItem for the CURRENT identity only.

        The identity is the deterministic idempotency-key suffix
        ``:<source_sha256>:<generation>`` — Jobs of a replaced source (a
        different SHA) are never part of the current chain, so stale results
        are never surfaced or advanced.
        """
        sha, generation = identity
        proxy_key = (
            f"{video_proxy.JOB_TYPE_GENERATE_PROXY}:video_item:"
            f"{video_item_id}:{sha}:{generation}"
        )
        scene_key = f"{_SCENE_KEY_PREFIX}{video_item_id}:{sha}:{generation}"
        grouped: dict[str, list[Any]] = {step: [] for step in CHAIN_STEP_ORDER}
        with self._session_factory() as session:
            rows = session.scalars(
                select(Job)
                .where(
                    Job.workspace_id == _CHAIN_WORKSPACE_ID,
                    Job.owner_type == "video_item",
                    Job.owner_id == video_item_id,
                    or_(
                        Job.idempotency_key == proxy_key,
                        Job.idempotency_key == scene_key,
                        Job.idempotency_key.like(
                            f"{_IMPORT_KEY_PREFIX}{video_item_id}:%"
                        ),
                    ),
                )
                .order_by(Job.created_at.desc())
            ).all()
        for job in rows:
            key = job.idempotency_key or ""
            if key.startswith(f"{video_proxy.JOB_TYPE_GENERATE_PROXY}:"):
                grouped["proxy"].append(job)
            elif key.startswith(_SCENE_KEY_PREFIX):
                grouped["scene_detect"].append(job)
            elif key.startswith(_IMPORT_KEY_PREFIX):
                grouped["import"].append(job)
        return grouped

    def _chain_video_items(self) -> list[Any]:
        """Every ACTIVE (non-archived) VideoItem that has at least one
        durable chain Job.

        Superseded VideoItems (source replaced — S05-C03) are archived and
        excluded: their chains are frozen at their terminal rows and the
        background scan never creates successor Jobs for a replaced
        source.
        """
        with self._session_factory() as session:
            ids = list(
                session.scalars(
                    select(Job.owner_id)
                    .where(
                        Job.workspace_id == _CHAIN_WORKSPACE_ID,
                        Job.owner_type == "video_item",
                        Job.idempotency_key.is_not(None),
                    )
                    .distinct()
                ).all()
            )
        items: list[Any] = []
        for item_id in ids:
            with self._session_factory() as session:
                item = session.get(VideoItem, str(item_id))
            if item is not None and item.status != "archived":
                items.append(item)
        return items

    def _step_checkpoint(self, job_id: str) -> dict[str, Any]:
        """The first step's checkpoint payload of a Job (or {})."""
        with self._session_factory() as session:
            step = session.scalars(
                select(JobStep)
                .where(JobStep.job_id == job_id)
                .order_by(JobStep.position)
            ).first()
            if step is None:
                return {}
            raw = step.checkpoint_json
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _published_artifact_id(self, job_id: str) -> str | None:
        """The artifact id this Job durably published (checkpoint evidence)."""
        published = self._step_checkpoint(job_id).get("published") or {}
        artifact_id = published.get("artifact_id")
        return str(artifact_id) if artifact_id else None

    def _scenes_count(self, video_item_id: str) -> int | None:
        with self._session_factory() as session:
            from sqlalchemy import func

            count = session.scalar(
                select(func.count())
                .select_from(Scene)
                .where(Scene.video_item_id == video_item_id)
            )
        return int(count) if count is not None else None

    def _resolve_chain_video_item(self, project_id: str) -> Any | None:
        """The chain's VideoItem for a legacy project (first non-archived)."""
        with self._session_factory() as session:
            return session.scalar(
                select(VideoItem)
                .where(
                    VideoItem.project_id == project_id,
                    VideoItem.status != "archived",
                )
                .order_by(VideoItem.position)
                .limit(1)
            )

    def _ensure_durable_shell(self, project_id: str, name: str) -> Any:
        """Materialize the durable Workspace → Project → VideoItem rows.

        The approved chain services validate a durable ownership chain at
        submit time; the legacy project API persists ``project.json`` on
        disk only, so the missing durable rows are created on demand
        (idempotent) so ONE UI-facing submission can drive the approved
        Jobs.
        """
        from app.services.video_import import CODE_PROJECT_NOT_FOUND, VideoImportError

        with self._session_factory() as session:
            if session.get(Workspace, _CHAIN_WORKSPACE_ID) is None:
                session.add(Workspace(id=_CHAIN_WORKSPACE_ID, name=_CHAIN_WORKSPACE_ID))
            project = session.get(Project, project_id)
            if project is None:
                project = Project(
                    id=project_id,
                    workspace_id=_CHAIN_WORKSPACE_ID,
                    name=(name or "Dự án")[:200],
                    status="active",
                )
                session.add(project)
            elif project.status == "archived":
                raise VideoImportError(
                    CODE_PROJECT_NOT_FOUND,
                    f"Project {project_id!r} is archived",
                    location="project",
                )
            item = session.scalar(
                select(VideoItem)
                .where(
                    VideoItem.project_id == project_id,
                    VideoItem.status != "archived",
                )
                .order_by(VideoItem.position)
                .limit(1)
            )
            if item is None:
                item = VideoItem(
                    project_id=project_id,
                    title=(name or "Video")[:240],
                    position=0,
                    status="imported",
                )
                session.add(item)
            session.commit()
            return item

    def _supersede_video_item(self, project_id: str, old_item: Any, name: str) -> Any:
        """Archive the current VideoItem and create a NEW one (supersession).

        One transaction: the previous VideoItem is marked ``archived``
        (with ``archived_at``; its jobs/artifacts/scene rows are NEVER
        touched — PERSISTENCE_DOMAIN_CONTRACT §4/§5 archive semantics) and
        a fresh VideoItem with the next free position becomes the pipeline
        unit for the new source.  ``chain_state``/``retry_chain`` and the
        background scan resolve the FIRST NON-ARCHIVED item, so after
        supersession every chain query exposes ONLY the current source.
        """
        with self._session_factory() as session:
            old = session.get(VideoItem, old_item.id)
            if old is None:
                old = old_item
            old.status = "archived"
            old.archived_at = datetime.now(UTC)
            max_position = session.scalar(
                select(func.max(VideoItem.position)).where(
                    VideoItem.project_id == project_id
                )
            )
            item = VideoItem(
                project_id=project_id,
                title=(name or "Video")[:240],
                position=int(max_position or 0) + 1,
                status="imported",
            )
            session.add(item)
            session.commit()
            return item

    def _chain_job_message(self, job: Any) -> str:
        state = job.state
        if state == "pending":
            return "Chờ bắt đầu"
        if state == "queued":
            return "Đang chờ xử lý"
        if state == "running":
            return "Đang chạy"
        if state == "cancelling":
            return "Đang hủy"
        if state == "cancelled":
            return "Đã hủy"
        if state == "completed":
            return "Hoàn tất"
        if state == "failed":
            message: str | None = None
            if job.error_json:
                try:
                    envelope = json.loads(job.error_json)
                    message = (
                        envelope.get("message") if isinstance(envelope, dict) else None
                    )
                except (ValueError, TypeError):
                    message = job.error_json
            return f"Thất bại: {message}" if message else "Thất bại"
        return "Bỏ qua"

    def _chain_step_progress(self, job: Any | None) -> float:
        if job is None:
            return 0.0
        if job.state == "completed":
            return 100.0
        return float(job.progress or 0.0)

    def _chain_step_payload(self, kind: str, job: Any | None) -> dict[str, object]:
        if job is None:
            return {
                "step": kind,
                "job_id": None,
                "status": "not_created",
                "progress": 0.0,
                "message": "Chưa tạo",
                "error": None,
                "error_code": None,
                "predecessor_job_id": None,
            }
        error: str | None = None
        error_code: str | None = None
        if job.error_json:
            try:
                envelope = json.loads(job.error_json)
                if isinstance(envelope, dict):
                    error = (
                        str(envelope.get("message"))
                        if envelope.get("message")
                        else None
                    )
                    error_code = (
                        str(envelope.get("error_code"))
                        if envelope.get("error_code")
                        else None
                    )
            except (ValueError, TypeError):
                error = job.error_json
        return {
            "step": kind,
            "job_id": job.id,
            "status": job.state,
            "progress": self._chain_step_progress(job),
            "message": self._chain_job_message(job),
            "error": error,
            "error_code": error_code,
            "predecessor_job_id": job.predecessor_job_id,
        }

    def _chain_source_name(self, import_job: Any | None) -> str | None:
        if import_job is None:
            return None
        try:
            manifest = json.loads(import_job.input_manifest_json or "{}")
            title = manifest.get("title")
            if not isinstance(title, str) or not title:
                return None
            return Path(title).name
        except (ValueError, TypeError):
            return None


# ── Process-wide accessor (binds to the same DB/managed root as the API) ─

_orchestrator: AnalyzeChainOrchestrator | None = None
_orchestrator_bound: Any = None


def get_analyze_orchestrator() -> AnalyzeChainOrchestrator:
    """Process-wide chain orchestrator bound to the API job service.

    Lazy and side-effect free until the first call; rebinds (stopping the
    previous instance) whenever the underlying ``JobService`` instance
    changes (tests inject a fresh service per test).  The session factory
    and managed root resolve through the JobService's PUBLIC binding
    contract (:attr:`JobService.session_factory` /
    :attr:`JobService.managed_root`) — no private service attribute is
    inspected from this module (S05-C04).

    **Fail-closed before initialization (S05-C04-R2, Codex finding 1).**
    The orchestrator must NEVER construct or bind a competing session
    factory: if :attr:`JobService.session_factory` is ``None`` the
    ``JobService`` has not been initialized yet, and this accessor raises
    instead of creating an engine/factory of its own.  Without this
    guard, a call before ``JobService.initialize()`` would cache an
    orchestrator bound to a competing factory for the lifetime of the
    process (the cache is keyed by JobService object identity, so the
    stale binding would survive the later lifecycle init).  With the
    guard, every orchestrator ever cached is bound to the EXACT
    authoritative factory the initialized job service exposes — the same
    factory that serves the ``DurableWorker`` and the ``JobReconciler``
    (one database, one managed root).
    """
    global _orchestrator, _orchestrator_bound

    from app.api import deps

    job_service = deps.get_job_service()
    if _orchestrator is not None and _orchestrator_bound is job_service:
        return _orchestrator
    if _orchestrator is not None:
        _orchestrator.stop(timeout=1.0)

    session_factory = job_service.session_factory
    if session_factory is None:
        raise RuntimeError(
            "analyze orchestrator requires an initialized JobService "
            "(session_factory is None); call JobService.initialize() first — "
            "the orchestrator never binds a competing session factory"
        )
    _orchestrator = AnalyzeChainOrchestrator(session_factory, job_service.managed_root)
    _orchestrator_bound = job_service
    return _orchestrator


def reset_analyze_orchestrator() -> None:
    """Stop and drop the process-wide orchestrator (test isolation)."""
    global _orchestrator, _orchestrator_bound
    if _orchestrator is not None:
        _orchestrator.stop(timeout=1.0)
    _orchestrator = None
    _orchestrator_bound = None
