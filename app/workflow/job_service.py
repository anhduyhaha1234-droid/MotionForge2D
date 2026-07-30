"""Job service — in-process background worker with progress and cancellation."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from app.schemas import JobInfo, JobState


class JobService:
    """Manages background jobs running in worker threads.

    Jobs are stored in memory. Each job runs a user-supplied callable
    that receives a progress callback and a cancel-check callback.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    def create_job(
        self,
        job_type: str,
        func: Callable[[Callable[[float, str], None], Callable[[], bool]], Any],
    ) -> JobInfo:
        """Create and start a background job.

        Args:
            job_type: Human-readable job type (e.g. "ingest", "propagate").
            func: Callable receiving (progress_cb, is_cancelled_cb).
                  progress_cb(progress: float, message: str) where progress is 0-100.
                  is_cancelled() returns True if cancellation was requested.

        Returns:
            JobInfo for the newly created job.
        """
        job_id = uuid.uuid4().hex[:12]
        cancel_event = threading.Event()

        info = JobInfo(
            job_id=job_id,
            state=JobState.QUEUED,
            job_type=job_type,
            progress=0.0,
            message="Queued",
        )
        self._jobs[job_id] = info
        self._cancel_flags[job_id] = cancel_event

        def progress_cb(pct: float, msg: str = "") -> None:
            info.progress = max(0.0, min(100.0, pct))
            if msg:
                info.message = msg

        def is_cancelled() -> bool:
            return cancel_event.is_set()

        def worker() -> None:
            info.state = JobState.RUNNING
            info.message = "Running"
            try:
                result = func(progress_cb, is_cancelled)
                if is_cancelled():
                    info.state = JobState.CANCELLED
                    info.message = "Cancelled"
                else:
                    info.state = JobState.COMPLETED
                    info.progress = 100.0
                    info.message = "Completed"
                    if isinstance(result, str):
                        info.result_path = result
            except Exception as exc:
                info.state = JobState.FAILED
                info.error = str(exc)
                info.message = f"Failed: {exc}"

        thread = threading.Thread(target=worker, name=f"job-{job_id}", daemon=True)
        self._threads[job_id] = thread
        thread.start()
        return info

    def get_job(self, job_id: str) -> JobInfo | None:
        """Get current job status."""
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a running job.

        Returns:
            True if the cancel flag was set, False if job not found or not running.
        """
        info = self._jobs.get(job_id)
        if info is None:
            return False
        if info.state not in (JobState.QUEUED, JobState.RUNNING):
            return False
        info.state = JobState.CANCELLING
        info.message = "Cancelling"
        event = self._cancel_flags.get(job_id)
        if event:
            event.set()
        return True
