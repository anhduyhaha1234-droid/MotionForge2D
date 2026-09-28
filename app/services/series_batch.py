"""MF-END-27 — series batch: queue >=2 videos of ONE series safely.

The series is the EXISTING production container (``project``).  A batch
queues its videos' S12 export stage (MF-END-26 authority, which consumes
the MF-END-23 export gate) against ONE pinned cast pack and drives them to
per-video results without ever creating a second business queue.

Design rules (all reused, nothing duplicated):

* **No second queue / no new table.**  Queue and state live in the EXISTING
  durable tables: the ``job`` table (rows created by the export authority
  through MF-END-15 idempotent submit) and the ``s12_export_run`` authority
  rows.  This service WRITES no row of its own — it derives the batch view
  from those rows and only ever asks the existing authorities to submit.
* **Shared cast is proven, not assumed (U03).**  Every batch video's cast
  set — ``project_cast_mapping`` joined through ``object_role.video_item_id``,
  the per-video cast authority from MF-END-05 — must be EQUAL across the
  batch and yields the batch ``pack_hash``.  Missing or divergent cast fails
  closed with a typed refusal and ZERO submissions: a batch never silently
  clones or swaps a character.
* **CPU prepares first, heavy work one at a time (U19).**  :meth:`prepare`
  resolves every video independently (no cross-video dependency, no writes,
  no submissions).  The scheduler then admits at most ONE non-terminal
  heavy export run per batch (``max_heavy_in_flight = 1``), so a later
  video is deferred until the previous video's run is terminal.  The heavy
  stage below this one (render/assembly) is already serialised by the
  worker's single claim loop; the batch never adds a second concurrent
  heavy submit.
* **Restart safety = replay, not repair.**  :meth:`create_batch` and
  :meth:`advance` are idempotent: for the same payload the export authority
  converges on the SAME run/job (MF-END-15/26), so re-entering after a
  restart re-adopts the existing rows and submits nothing new.  An adopted
  run whose durable identity no longer matches the current payload is a
  typed refusal (:class:`SeriesBatchStaleRun`) — never a silent resubmit.
* **Errors are per video.**  A failed or cancelled video's rows stay
  intact, its typed error is surfaced with the run/job state, and the batch
  continues with the next video on the next :meth:`advance`.  A failed
  video never deletes another video's run, job or output bytes.
* **Measurements are honest (U26).**  :meth:`metrics` returns the literal
  ``"unmeasured"`` for every field unless a real measurement was supplied.
  One easy sample is never extrapolated into a 30-minute promise.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.persistence.models import (
    Job,
    ObjectRole,
    Project,
    ProjectCastMapping,
    S12ExportRun,
    VideoItem,
)

log = logging.getLogger(__name__)

SCHEMA = "mf-end-27/series-batch@1"

#: A batch is "two videos" at minimum (U19) and bounded for memory sanity.
MIN_VIDEOS = 2
MAX_VIDEOS = 8

#: Export-run states that release the batch's heavy lease.
HEAVY_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

#: The ONLY honest value for an un-measured field (U26 wording).
UNMEASURED = "unmeasured"

#: Output-path keys the export manifests use, checked in order.
_OUTPUT_KEYS = ("output_path", "output", "final_output", "final_path")

_MEDIA_SUFFIXES = (".mp4", ".mov", ".m4v", ".mkv")

#: sha256 is computed for outputs up to this size; larger files report
#: ``sha256_skipped`` instead of blocking the read path.
_SHA_MAX_BYTES = 512 * 1024 * 1024


class SeriesBatchError(RuntimeError):
    """Base typed refusal for the series batch."""

    code = "series_batch_refused"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}


class SeriesBatchNotFound(SeriesBatchError):  # noqa: N818 - typed refusal naming
    """The project (series) does not exist in this workspace."""

    code = "series_batch_not_found"


class SeriesBatchInputError(SeriesBatchError):
    """Bad batch input: unknown/foreign video, duplicate, bad count."""

    code = "series_batch_input_invalid"


class SeriesBatchCastError(SeriesBatchError):
    """The shared cast pack is missing or not equal across the batch."""

    code = "series_batch_cast_invalid"


class SeriesBatchCastMissing(SeriesBatchCastError):  # noqa: N818 - typed refusal naming
    code = "series_batch_cast_missing"


class SeriesBatchCastMismatch(SeriesBatchCastError):  # noqa: N818 - typed refusal naming
    code = "series_batch_cast_mismatch"


class SeriesBatchStaleRun(SeriesBatchError):  # noqa: N818 - typed refusal naming
    """An adopted run does not match the current payload identity."""

    code = "series_batch_stale_run"


class SeriesBatchSubmitError(SeriesBatchError):
    """The export authority refused one video's submit (typed + status)."""

    code = "series_batch_submit_failed"

    def __init__(self, detail: str, *, status: int | None = None) -> None:
        super().__init__(detail)
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        payload = super().as_dict()
        payload["status"] = self.status
        return payload


@dataclass(frozen=True, slots=True)
class CastEntry:
    """One per-video cast row (the MF-END-05 per-video cast authority)."""

    role_id: str
    video_item_id: str
    character_id: str
    pack_version_id: str

    def pack_key(self) -> tuple[str, str]:
        """The shareable pack identity (role ids are video-specific)."""
        return (self.character_id, self.pack_version_id)


def batch_key(
    project_id: str,
    video_item_ids: Sequence[str],
    *,
    generation: str = "1",
) -> str:
    """Deterministic batch identity (restart-proof, input-derived).

    Two calls with the same inputs are the SAME batch — that is exactly what
    makes restart re-entry idempotent and duplicate-free.
    """
    canonical = json.dumps(
        {
            "schema": SCHEMA,
            "project_id": str(project_id),
            "videos": sorted({str(v) for v in video_item_ids}),
            "generation": str(generation),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"series-batch:{digest[:32]}"


def _cast_digest(pack_keys: Sequence[tuple[str, str]]) -> str:
    canonical = json.dumps(
        sorted(set(pack_keys)),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _default_export_submitter(
    payload: Mapping[str, Any],
    session: Any,
    workspace_id: str,
) -> Mapping[str, Any]:
    """Call the REAL export authority (the s12-export submit route).

    This is the single reused entry point: the batch adds no export logic of
    its own and inherits the gate consumption, the audio pinning and the
    idempotent run/job convergence from MF-END-26/MF-END-15.
    """
    from app.api.routes import s12_export as route  # noqa: PLC0415

    body = route.S12ExportSubmitRequest(**dict(payload))
    return dict(route.submit_export(body, session, workspace_id=workspace_id))


def _manifest_output_path(manifest: Mapping[str, Any]) -> str | None:
    """Find the output media path recorded in an export job manifest."""
    for key in _OUTPUT_KEYS:
        value = manifest.get(key)
        if isinstance(value, str) and value.lower().endswith(_MEDIA_SUFFIXES):
            return value
    paths = manifest.get("paths")
    if isinstance(paths, Mapping):
        for key in _OUTPUT_KEYS:
            value = paths.get(key)
            if isinstance(value, str) and value.lower().endswith(_MEDIA_SUFFIXES):
                return value
    for value in manifest.values():
        if isinstance(value, str) and value.lower().endswith(_MEDIA_SUFFIXES):
            return value
    return None


def _file_evidence(path_text: str | None) -> dict[str, Any] | None:
    """Size + sha256 of an output file, or None when it is not on disk."""
    if not path_text:
        return None
    path = Path(path_text)
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    evidence: dict[str, Any] = {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "sha256": None,
    }
    if stat.st_size <= _SHA_MAX_BYTES:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        evidence["sha256"] = digest.hexdigest()
    else:
        evidence["sha256_skipped"] = "large_file"
    return evidence


class SeriesBatchService:
    """Queue a series' videos against ONE pinned cast pack.

    The service is stateless across calls: every view is derived from the
    durable rows, so a process restart loses nothing (the queue lives in the
    ``job`` table created by the existing authorities).
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        job_service: Any,
        export_submitter: (
            Callable[[Mapping[str, Any], Any, str], Mapping[str, Any]] | None
        ) = None,
        max_heavy_in_flight: int = 1,
        min_videos: int = MIN_VIDEOS,
        max_videos: int = MAX_VIDEOS,
    ) -> None:
        if int(max_heavy_in_flight) < 1:
            raise ValueError("max_heavy_in_flight must be >= 1")
        if int(min_videos) < 2:
            raise ValueError("min_videos must be >= 2")
        if int(max_videos) < int(min_videos):
            raise ValueError("max_videos must be >= min_videos")
        self._session_factory = session_factory
        self._job_service = job_service
        self._export_submitter = export_submitter or _default_export_submitter
        self._max_heavy = int(max_heavy_in_flight)
        self._min_videos = int(min_videos)
        self._max_videos = int(max_videos)

    # ── input resolution (read-only) ────────────────────────────────────────

    def _require_project(
        self, session: Any, workspace_id: str, project_id: str
    ) -> Project:
        row = session.scalar(
            select(Project).where(
                Project.id == str(project_id),
                Project.workspace_id == str(workspace_id),
            )
        )
        if row is None:
            raise SeriesBatchNotFound(
                f"project {project_id!r} not found in workspace {workspace_id!r}"
            )
        return row

    def _require_videos(
        self,
        session: Any,
        project_id: str,
        video_item_ids: Sequence[str],
    ) -> list[str]:
        ordered: list[str] = []
        for raw in video_item_ids:
            candidate = str(raw)
            if candidate in ordered:
                raise SeriesBatchInputError(
                    f"duplicate video_item_id {candidate!r} in batch input"
                )
            ordered.append(candidate)
        if len(ordered) < self._min_videos:
            raise SeriesBatchInputError(
                f"a series batch needs at least {self._min_videos} videos, "
                f"got {len(ordered)}"
            )
        if len(ordered) > self._max_videos:
            raise SeriesBatchInputError(
                f"a series batch is bounded at {self._max_videos} videos "
                f"(memory guard), got {len(ordered)}"
            )
        rows = session.scalars(
            select(VideoItem).where(
                VideoItem.id.in_(ordered),
                VideoItem.project_id == str(project_id),
            )
        ).all()
        known = {row.id for row in rows}
        unknown = [vid for vid in ordered if vid not in known]
        if unknown:
            raise SeriesBatchInputError(
                f"video items not in project {project_id!r}: {sorted(unknown)}"
            )
        return ordered

    def _resolve_cast(
        self,
        session: Any,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Prove the SHARED cast pack across the batch (fail-closed)."""
        rows = session.execute(
            select(
                ProjectCastMapping.id,
                ProjectCastMapping.character_id,
                ProjectCastMapping.pack_version_id,
                ObjectRole.id,
                ObjectRole.video_item_id,
            )
            .join(ObjectRole, ObjectRole.id == ProjectCastMapping.object_role_id)
            .where(
                ProjectCastMapping.workspace_id == str(workspace_id),
                ProjectCastMapping.project_id == str(project_id),
                ObjectRole.video_item_id.in_(list(video_item_ids)),
            )
        ).all()
        per_video: dict[str, list[CastEntry]] = {v: [] for v in video_item_ids}
        for _mid, character_id, pack_version_id, role_id, video_item_id in rows:
            key = str(video_item_id)
            if key in per_video:
                per_video[key].append(
                    CastEntry(
                        role_id=str(role_id),
                        video_item_id=key,
                        character_id=str(character_id),
                        pack_version_id=str(pack_version_id),
                    )
                )
        missing = [v for v, entries in per_video.items() if not entries]
        if missing:
            raise SeriesBatchCastMissing(
                "these batch videos have no cast mapping rows yet: "
                f"{sorted(missing)} — pin the series cast first (U03)"
            )
        digests = {
            v: _cast_digest([e.pack_key() for e in entries])
            for v, entries in per_video.items()
        }
        if len(set(digests.values())) != 1:
            raise SeriesBatchCastMismatch(
                "batch videos do not share ONE cast pack: "
                + ", ".join(f"{v}={d[:12]}" for v, d in sorted(digests.items()))
            )
        shared_keys = {e.pack_key() for entries in per_video.values() for e in entries}
        return {
            "pack_hash": _cast_digest(list(shared_keys)),
            "cast_digest_by_video": digests,
            "shared_pack_keys": sorted(list(shared_keys)),
            "reused_entries": len(shared_keys),
            "per_video": per_video,
        }

    # ── CPU prepare (independent per video, zero writes) ────────────────────

    def prepare(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        generation: str = "1",
    ) -> dict[str, Any]:
        """Resolve every video INDEPENDENTLY: project, videos, shared cast.

        This is the CPU phase: read-only, no submissions, no mutations.  It
        is called for ALL videos before the scheduler admits any heavy work,
        and one video's failure cannot influence another video's prepare
        (they share no state).
        """
        key = batch_key(project_id, video_item_ids, generation=generation)
        with self._session_factory() as session:
            self._require_project(session, workspace_id, project_id)
            ordered = self._require_videos(session, project_id, video_item_ids)
            cast = self._resolve_cast(
                session, workspace_id, project_id, ordered
            )
            per_video = cast.pop("per_video")
            return {
                "schema": SCHEMA,
                "batch_key": key,
                "project_id": str(project_id),
                "generation": str(generation),
                "state": "prepared",
                "prepared_count": len(ordered),
                "videos": [
                    {
                        "video_item_id": vid,
                        "ordinal": index,
                        "cast_rows": len(per_video[vid]),
                        "prepared": True,
                    }
                    for index, vid in enumerate(ordered)
                ],
                **cast,
            }

    # ── durable reads (the batch's only "storage") ──────────────────────────

    def _latest_runs(
        self,
        session: Any,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
    ) -> dict[str, S12ExportRun | None]:
        rows = session.scalars(
            select(S12ExportRun)
            .where(
                S12ExportRun.workspace_id == str(workspace_id),
                S12ExportRun.project_id == str(project_id),
                S12ExportRun.video_item_id.in_(list(video_item_ids)),
            )
            .order_by(S12ExportRun.created_at.desc())
        ).all()
        latest: dict[str, S12ExportRun | None] = {v: None for v in video_item_ids}
        for row in rows:
            key = str(row.video_item_id)
            if key in latest and latest[key] is None:
                latest[key] = row
        return latest

    def _job_for_run(self, session: Any, run: S12ExportRun | None) -> Job | None:
        if run is None or not run.job_id:
            return None
        return session.get(Job, str(run.job_id))

    @staticmethod
    def _heavy_active(run: S12ExportRun | None, job: Job | None) -> bool:
        """A video holds the heavy lease while its run AND job are live.

        A terminally failed/cancelled JOB releases the lease even when the
        run row has not been re-attempted yet (the worker marks the job; the
        run follows on retry) — otherwise one broken video would starve the
        rest of the batch forever.
        """
        if run is None:
            return False
        if str(run.status) in HEAVY_TERMINAL_STATES:
            return False
        terminal_job = job is not None and str(job.state) in {
            "failed",
            "cancelled",
            "fenced",
        }
        return not terminal_job

    def _video_row(
        self,
        session: Any,
        index: int,
        video_item_id: str,
        run: S12ExportRun | None,
        submitted: Mapping[str, Any] | None,
        error: Mapping[str, Any] | None,
        deferred: bool,
    ) -> dict[str, Any]:
        job = self._job_for_run(session, run)
        row: dict[str, Any] = {
            "video_item_id": video_item_id,
            "ordinal": index,
            "run_id": str(run.id) if run is not None else None,
            "job_id": str(job.id) if job is not None else None,
            "run_state": str(run.status) if run is not None else None,
            "job_state": str(job.state) if job is not None else None,
            "output": None,
            "error": None,
        }
        if run is None:
            row["state"] = "deferred_lease" if deferred else "pending"
        else:
            run_status = str(run.status)
            job_state = str(job.state) if job is not None else None
            if run_status in HEAVY_TERMINAL_STATES:
                row["state"] = run_status
            elif job_state in {"failed", "cancelled"}:
                row["state"] = job_state
            else:
                row["state"] = "running"
        if job is not None and job.input_manifest_json:
            try:
                manifest = json.loads(job.input_manifest_json)
            except json.JSONDecodeError:  # pragma: no cover - defensive
                manifest = {}
            if isinstance(manifest, Mapping):
                output = _file_evidence(_manifest_output_path(manifest))
                if output is not None:
                    row["output"] = output
        if job is not None and job.error_json:
            try:
                row["error"] = json.loads(job.error_json)
            except json.JSONDecodeError:
                row["error"] = {"detail": str(job.error_json)}
        if error is not None:
            row["error"] = dict(error)
        if submitted is not None:
            row["submitted"] = dict(submitted)
        return row

    def _state(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        submitted: Mapping[str, Mapping[str, Any]],
        deferred: Sequence[str],
        submit_errors: Mapping[str, Mapping[str, Any]],
        measured: Mapping[str, Any] | None,
        generation: str = "1",
    ) -> dict[str, Any]:
        key = batch_key(project_id, video_item_ids, generation=generation)
        with self._session_factory() as session:
            self._require_project(session, workspace_id, project_id)
            ordered = self._require_videos(session, project_id, video_item_ids)
            cast_info: dict[str, Any]
            try:
                cast = self._resolve_cast(session, workspace_id, project_id, ordered)
                cast.pop("per_video")
                cast_info = {"ok": True, **cast}
            except SeriesBatchError as err:
                cast_info = {"ok": False, **err.as_dict()}
            runs = self._latest_runs(session, workspace_id, project_id, ordered)
            rows = [
                self._video_row(
                    session,
                    index,
                    vid,
                    runs.get(vid),
                    submitted.get(vid),
                    submit_errors.get(vid),
                    vid in set(deferred),
                )
                for index, vid in enumerate(ordered)
            ]
            active_heavy = sum(
                1
                for run in runs.values()
                if self._heavy_active(run, self._job_for_run(session, run))
            )
        states = [row["state"] for row in rows]
        if all(state == "completed" for state in states):
            batch_state = "completed"
        elif any(state in {"failed", "cancelled"} for state in states):
            batch_state = "partial_failure"
        elif any(state == "running" for state in states):
            batch_state = "running"
        else:
            batch_state = "queued"
        return {
            "schema": SCHEMA,
            "batch_key": key,
            "project_id": str(project_id),
            "state": batch_state,
            "cast": cast_info,
            "pack_hash": cast_info.get("pack_hash"),
            "videos": rows,
            "lease": {
                "max_heavy_in_flight": self._max_heavy,
                "active_heavy": active_heavy,
                "serialized": active_heavy <= self._max_heavy,
            },
            "metrics": self.metrics(measured=measured),
        }

    # ── scheduler: CPU first, then at most ONE heavy submit ────────────────

    def _schedule(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        exports: Mapping[str, Mapping[str, Any]],
        generation: str,
        measured: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        submitted: dict[str, dict[str, Any]] = {}
        deferred: list[str] = []
        submit_errors: dict[str, dict[str, Any]] = {}
        with self._session_factory() as session:
            self._require_project(session, workspace_id, project_id)
            ordered = self._require_videos(session, project_id, video_item_ids)
            runs = self._latest_runs(session, workspace_id, project_id, ordered)
            in_flight = sum(
                1
                for run in runs.values()
                if self._heavy_active(run, self._job_for_run(session, run))
            )
            for vid in ordered:
                run = runs.get(vid)
                payload = exports.get(vid)
                if run is not None:
                    self._assert_run_matches_payload(run, vid, payload)
                    continue
                if payload is None:
                    submit_errors[vid] = {
                        "code": "series_batch_export_payload_missing",
                        "detail": (
                            f"video {vid!r} has no export payload yet; "
                            "nothing submitted"
                        ),
                    }
                    continue
                if in_flight >= self._max_heavy:
                    deferred.append(vid)
                    continue
                try:
                    out = self._export_submitter(payload, session, workspace_id)
                except Exception as err:  # noqa: BLE001 - typed below
                    submit_errors[vid] = self._submit_error(err)
                    continue
                session.commit()
                submitted[vid] = {
                    "run_id": out.get("run_id"),
                    "job_id": out.get("job_id"),
                }
                in_flight += 1
        return self._state(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_ids=video_item_ids,
            submitted=submitted,
            deferred=deferred,
            submit_errors=submit_errors,
            measured=measured,
            generation=generation,
        )

    @staticmethod
    def _assert_run_matches_payload(
        run: S12ExportRun,
        video_item_id: str,
        payload: Mapping[str, Any] | None,
    ) -> None:
        """An adopted run must still be the run this payload would create."""
        if payload is None:
            return
        checks = (
            ("checkpoint_id", run.checkpoint_id),
            ("manifest_id", run.manifest_id),
            ("plan_id", run.plan_id),
            ("profile_id", run.profile_id),
        )
        for field, durable in checks:
            wanted = payload.get(field)
            if wanted is not None and str(wanted) != str(durable):
                raise SeriesBatchStaleRun(
                    f"video {video_item_id!r} already has run {run.id} pinned "
                    f"to {field}={durable!r}; the payload asks for {wanted!r} "
                    "— reload the batch instead of silently re-submitting"
                )

    @staticmethod
    def _submit_error(err: Exception) -> dict[str, Any]:
        status = getattr(err, "status_code", None)
        detail = getattr(err, "detail", None)
        if detail is None:
            detail = str(err)
        return {
            "code": "series_batch_submit_failed",
            "detail": str(detail),
            "status": status,
        }

    # ── public API ──────────────────────────────────────────────────────────

    def create_batch(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        exports: Mapping[str, Mapping[str, Any]],
        generation: str = "1",
        measured: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """CPU-prepare every video, then admit heavy submits one at a time."""
        prepared = self.prepare(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_ids=video_item_ids,
            generation=generation,
        )
        state = self._schedule(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_ids=video_item_ids,
            exports=exports,
            generation=generation,
            measured=measured,
        )
        state["prepare"] = prepared
        return state

    def advance(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        exports: Mapping[str, Mapping[str, Any]],
        generation: str = "1",
        measured: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Re-verify the cast pin, then admit the NEXT eligible submit.

        Called after a video's heavy run reaches a terminal state (or after
        a restart): idempotent by construction — existing runs are adopted,
        missing ones are submitted, and a cast drift refuses with zero
        submissions.
        """
        self.prepare(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_ids=video_item_ids,
            generation=generation,
        )
        return self._schedule(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_ids=video_item_ids,
            exports=exports,
            generation=generation,
            measured=measured,
        )

    def get_batch(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        generation: str = "1",
        measured: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read-only view over the durable rows (no submissions)."""
        return self._state(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_ids=video_item_ids,
            submitted={},
            deferred=(),
            submit_errors={},
            measured=measured,
            generation=generation,
        )

    def cancel_video(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_ids: Sequence[str],
        video_item_id: str,
        generation: str = "1",
    ) -> dict[str, Any]:
        """Cancel EXACTLY one video's durable job; the others are untouched."""
        target = str(video_item_id)
        with self._session_factory() as session:
            self._require_project(session, workspace_id, project_id)
            ordered = self._require_videos(session, project_id, video_item_ids)
            if target not in ordered:
                raise SeriesBatchInputError(
                    f"video {target!r} is not part of this batch"
                )
            runs = self._latest_runs(session, workspace_id, project_id, ordered)
            run = runs.get(target)
            job = self._job_for_run(session, run)
            if run is None or job is None:
                return {
                    "video_item_id": target,
                    "run_id": str(run.id) if run is not None else None,
                    "job_id": None,
                    "cancelled": False,
                    "job_state": None,
                    "detail": "no durable job for this video yet",
                }
            job_id = str(job.id)
            state_before = str(job.state)
        cancelled = bool(self._job_service.cancel_job(job_id))
        with self._session_factory() as session:
            row = session.get(Job, job_id)
            state_after = str(row.state) if row is not None else None
        return {
            "video_item_id": target,
            "run_id": str(run.id),
            "job_id": job_id,
            "cancelled": cancelled,
            "job_state": state_after or state_before,
            "detail": (
                "cancellation requested on the durable job (the run follows "
                "the worker's cancel drain)"
            ),
        }

    # ── measurements (U26: honest, never fabricated) ───────────────────────

    def metrics(
        self, *, measured: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Throughput / RAM figures — ``"unmeasured"`` unless really measured.

        A 30-minute promise needs a FULL-SOURCE measurement; nothing in this
        module may fabricate one, so the default is the literal string.
        """
        if measured is None:
            return {
                "measured": False,
                "window_seconds": UNMEASURED,
                "accepted_seconds": UNMEASURED,
                "throughput_accepted_per_second": UNMEASURED,
                "peak_ram_mb": UNMEASURED,
                "peak_vram_mb": UNMEASURED,
                "forecast_30min": UNMEASURED,
                "note": (
                    "no full-source measurement on this host yet — U26 says "
                    "measure before promising, so this batch reports "
                    "unmeasured instead of extrapolating"
                ),
            }
        payload = {"measured": True}
        for field in (
            "window_seconds",
            "accepted_seconds",
            "throughput_accepted_per_second",
            "peak_ram_mb",
            "peak_vram_mb",
            "forecast_30min",
        ):
            payload[field] = measured.get(field, UNMEASURED)
        return payload
