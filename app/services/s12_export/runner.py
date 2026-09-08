"""S12-T03B export runner — chunk render, stitch, checkpoint resume.

Consumes read-only (frozen, never rewritten here):
- ``app/persistence/s12_export.py`` (T03A) — run/chunk/lease rows own ALL
  DB state (``upsert_chunk`` / ``transition_chunk`` / ``list_chunks`` /
  ``get_run`` / ``get_lease``).  This module never issues raw SQL and never
  mutates a row except through those fenced methods.
- ``app/services/s12_export/chunks.py`` — deterministic plan + content_hash
  (content + config + profile + tool identity).
- ``app/services/s12_export/stitch.py`` — seam-exact assembly, audio muxed
  exactly once, atomic ``.partial`` → completed finalize.
- ``app/services/ffmpeg_utils.py`` — real ffmpeg/ffprobe binaries.

Lifecycle per run (caller owns claim + commit boundaries; every method
takes the caller's session-bound repository):

1. :meth:`ExportRunner.ensure_plan` — upsert every planned chunk boundary
   (idempotent: same content_hash replays, different hash fails closed in
   T03A).  Verifies the run pins (checkpoint/plan/profile/frame_count)
   still match the caller pins — a stale caller fails closed.
2. :meth:`ExportRunner.render_pending` — render each non-completed chunk
   window from the validated source to ``<chunk>.mp4`` via ``.partial``
   scratch + atomic rename; verify decoded frames == window size.
   Crash-safe: a crash leaves ``pending``/``running`` rows + ``.partial``
   scratch only — resume re-renders them, never accepts them.
3. :meth:`ExportRunner.resume` — fresh-process safe: re-read rows + files
   from disk, reuse only completed+verified chunks whose file decodes to
   the exact window size (tampered/short file → re-render), then render
   the rest and assemble.  No DB repair, no in-memory ownership.
4. :meth:`ExportRunner.assemble` — all chunks completed+verified →
   :func:`stitch.assemble_run` → candidate path.  The runner NEVER marks
   the run ``completed`` and never publishes (T03C owns publication).

Fail-closed paths: stale lease (expired/released or foreign worker),
cancel request, disk-full (ENOSPC), tampered chunk, source/identity drift.
"""

from __future__ import annotations

import errno
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.persistence.s12_export import (
    FencedWorkerError,
    LeaseConflictError,
    S12ExportRepository,
    StaleIdentityError,
)
from app.services.ffmpeg_utils import find_ffmpeg
from app.services.s12_export.chunks import (
    TOOL_IDENTITY,
    ChunkSpec,
    DiskInsufficientError,
    check_disk_for_run,
    compute_content_hash,
    plan_chunks,
    render_window,
)
from app.services.s12_export.stitch import (
    ChunkMedia,
    StitchError,
    assemble_run,
    check_source_cfr,
    count_video_frames,
)

__all__ = [
    "TOOL_IDENTITY",
    "RunnerError",
    "StaleLeaseError",
    "CancelledError",
    "DiskFullError",
    "RunnerConfig",
    "ExportRunner",
]

#: Chunk artifact filename pattern inside the run chunk directory.
CHUNK_FILENAME = "chunk_{index:04d}.mp4"

#: Frozen profile→encoder mirror (T01 ``PROFILE_ENCODERS`` is authoritative;
#: this fallback keeps the runner working on trees that predate the C1
#: interface — the same pattern canonical ``capabilities.py`` uses).
_FROZEN_PROFILE_ENCODERS_FALLBACK: dict[str, str] = {
    "master-4k-h264": "libx264",
    "master-4k-hevc": "libx265",
    "preview-1080p-h264": "libx264",
}


def _encoder_for_profile(profile_id: str) -> str:
    """Frozen encoder for *profile_id* (T01 ``PROFILE_ENCODERS``, read-only).

    Prefers the live T02-C1 table when the tree provides it; otherwise uses
    the frozen mirror above.  Unknown profile → fail-closed (no guessing).
    """
    table: dict[str, str] | None = None
    try:
        from app.services.s12_export.preflight import PROFILE_ENCODERS

        table = dict(PROFILE_ENCODERS)
    except Exception:
        table = None
    if table is None:
        table = _FROZEN_PROFILE_ENCODERS_FALLBACK
    encoder = table.get(profile_id)
    if not encoder:
        raise RunnerError(
            f"unknown profile {profile_id!r} — no frozen encoder (fail-closed)"
        )
    return str(encoder)


def _probe_encoder_usable(encoder: str) -> tuple[bool, str]:
    """Real encoder usability probe (binary + listed + 1-frame smoke).

    Prefers T01-C02 ``probe_encoder_support`` per-profile when importable;
    otherwise probes the encoder name directly with the same semantics:
    True ONLY on located binary + listed encoder + smoke rc 0.
    """
    try:
        from app.services.s12_export.preflight import _find_ffmpeg as _locate
    except Exception:
        _locate = None  # type: ignore[assignment]
    ffmpeg: str | None = None
    if _locate is not None:
        try:
            ffmpeg = _locate()
        except Exception:
            ffmpeg = None
    if ffmpeg is None:
        import shutil as _shutil

        ffmpeg = _shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg binary not found (capability unproven)"
    try:
        enc = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            timeout=30,
        )
    except Exception as exc:
        return False, f"ffmpeg -encoders probe failed: {exc}"
    if encoder.encode() not in (enc.stdout or b""):
        return False, f"encoder {encoder!r} absent from ffmpeg -encoders"
    import tempfile as _tempfile

    try:
        with _tempfile.TemporaryDirectory(prefix="s12t03b_enc_") as tmp:
            out = str(Path(tmp) / "smoke.mp4")
            smoke = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=64x64:rate=10:duration=0.2",
                    "-frames:v",
                    "1",
                    "-c:v",
                    encoder,
                    "-pix_fmt",
                    "yuv420p",
                    out,
                ],
                capture_output=True,
                timeout=60,
            )
    except Exception as exc:
        return False, f"encoder smoke probe failed: {exc}"
    if smoke.returncode != 0:
        tail = (smoke.stderr or b"")[-200:].decode("utf-8", "replace")
        return False, f"encoder {encoder!r} smoke rc={smoke.returncode}: {tail}"
    return True, f"encoder {encoder!r} listed + 1-frame smoke rc 0"


class RunnerError(ValueError):
    """Fail-closed runner error."""


class StaleLeaseError(RunnerError):
    """The lease is expired/released or held by another worker — stop."""


class CancelledError(RunnerError):
    """A cancel was requested — the run stops without a candidate."""


class DiskFullError(RunnerError):
    """Disk filled mid-render (ENOSPC) — chunk failed, resume later."""


@dataclass
class RunnerConfig:
    """All runner inputs (pure values; the caller owns sessions/commits)."""

    run_id: str
    workspace_id: str
    worker_id: str
    fence_token: str
    source_path: str | Path
    fps: float
    chunk_dir: str | Path
    scratch_dir: str | Path
    output_path: str | Path
    audio_source: str | Path | None = None
    max_frames_per_chunk: int = 120
    overlap_frames: int = 4
    cancel_flag: str | Path | None = None
    extra: dict[str, str] = field(default_factory=dict)


class ExportRunner:
    """Chunk render + resume + assemble driver over a T03A repository."""

    def __init__(self, repo: S12ExportRepository, config: RunnerConfig) -> None:
        self._repo = repo
        self._cfg = config

    # ── guards ──────────────────────────────────────────────────────────

    def _require_live_lease(self) -> None:
        from datetime import UTC, datetime

        lease = self._repo.get_lease(self._cfg.run_id)
        if lease is None:
            raise StaleLeaseError("no lease row for run (stale lock?)")
        if lease.worker_id != self._cfg.worker_id:
            raise StaleLeaseError(
                f"lease held by worker {lease.worker_id!r} (stale lock?)"
            )
        if lease.fence_token != self._cfg.fence_token:
            raise FencedWorkerError(
                "fence token mismatch (worker was fenced)",
                run_id=self._cfg.run_id,
            )
        now = datetime.now(UTC)
        expires = lease.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= now:
            raise StaleLeaseError("lease expired (stale lock?)")

    def _require_not_cancelled(self) -> None:
        run = self._repo.get_run(self._cfg.run_id)
        if run.status == "cancelled":
            raise CancelledError(f"run {run.id} is cancelled")
        flag = self._cfg.cancel_flag
        if flag is not None and Path(flag).exists():
            raise CancelledError(f"cancel flag present: {flag}")

    def _run_pins(self):  # type: ignore[no-untyped-def]
        return self._repo.get_run(self._cfg.run_id)

    # ── plan ────────────────────────────────────────────────────────────

    def build_plan(self) -> list[ChunkSpec]:
        """Derive the deterministic chunk plan from the pinned run identity."""
        run = self._run_pins()
        return plan_chunks(
            frame_count=run.frame_count,
            max_frames_per_chunk=self._cfg.max_frames_per_chunk,
            overlap_frames=self._cfg.overlap_frames,
            plan_hash=run.plan_hash,
            checkpoint_hash=run.checkpoint_hash,
            profile_id=run.profile_id,
        )

    def ensure_plan(self) -> list[ChunkSpec]:
        """Pin every chunk boundary in the DB (idempotent resume-safe)."""
        self._require_live_lease()
        self._require_not_cancelled()
        specs = self.build_plan()
        run = self._run_pins()
        for spec in specs:
            # Bind the caller's live pins: a stale caller (rotated plan or
            # checkpoint) must fail closed instead of rendering stale media.
            expect = compute_content_hash(
                plan_hash=run.plan_hash,
                checkpoint_hash=run.checkpoint_hash,
                profile_id=run.profile_id,
                chunk_index=spec.chunk_index,
                core_start_frame=spec.core_start_frame,
                core_end_frame=spec.core_end_frame,
                attempt=spec.attempt,
            )
            if expect != spec.content_hash:  # pragma: no cover - defensive
                raise StaleIdentityError("chunk plan drifted from run pins")
            self._repo.upsert_chunk(
                run_id=run.id,
                workspace_id=self._cfg.workspace_id,
                chunk_index=spec.chunk_index,
                order_index=spec.order_index,
                core_start_frame=spec.core_start_frame,
                core_end_frame=spec.core_end_frame,
                overlap_before=spec.overlap_before,
                overlap_after=spec.overlap_after,
                content_hash=spec.content_hash,
                attempt=spec.attempt,
                actor=self._cfg.worker_id,
                fence_token=self._cfg.fence_token,
            )
        return specs

    # ── render ──────────────────────────────────────────────────────────

    def chunk_path(self, chunk_index: int) -> Path:
        return Path(self._cfg.chunk_dir) / CHUNK_FILENAME.format(index=chunk_index)

    def _render_window_file(self, spec: ChunkSpec, dest_final: Path) -> Path:
        src = Path(self._cfg.source_path)
        if not src.is_file():
            raise RunnerError(f"validated source missing: {src}")
        if self._cfg.fps <= 0:
            raise RunnerError("fps must be > 0")
        run = self._run_pins()
        # C10 — the chunk encoder is the run profile's frozen encoder (never
        # a silent substitution): it must probe usable (binary + listed +
        # smoke rc 0) or the render fails explicit.
        encoder = _encoder_for_profile(run.profile_id)
        usable, basis = _probe_encoder_usable(encoder)
        if not usable:
            raise RunnerError(
                f"profile {run.profile_id!r} encoder {encoder!r} unusable: "
                f"{basis}"
            )
        rs, re = render_window(spec, run.frame_count)
        window_frames = re - rs + 1
        dest_final.parent.mkdir(parents=True, exist_ok=True)
        # Scratch keeps a real .mp4 suffix (the muxer sniffs format from the
        # extension — ".partial" is not muxable); only the T03C-visible
        # candidate carries the frozen .partial name (see stitch.assemble_run).
        scratch = dest_final.parent / f"{dest_final.stem}.tmp-render.mp4"
        try:
            completed = subprocess.run(
                [
                    find_ffmpeg(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(src),
                    "-vf",
                    f"trim=start_frame={rs}:end_frame={re + 1},"
                    "setpts=PTS-STARTPTS",
                    "-an",
                    "-c:v",
                    encoder,
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(scratch),
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise DiskFullError(f"disk full rendering chunk {spec.chunk_index}") from err
            raise RunnerError(f"ffmpeg spawn failed: {err}") from err
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            if "No space left on device" in stderr:
                try:
                    if scratch.is_file():
                        os.remove(scratch)
                except OSError:
                    pass
                raise DiskFullError(
                    f"disk full rendering chunk {spec.chunk_index}"
                )
            raise RunnerError(
                f"chunk {spec.chunk_index} render failed "
                f"(encoder={encoder}): {stderr[-300:]}"
            )
        try:
            got = count_video_frames(scratch)
        except StitchError as err:
            raise RunnerError(
                f"chunk {spec.chunk_index} unreadable after render: {err}"
            ) from err
        if got != window_frames:
            try:
                os.remove(scratch)
            except OSError:
                pass
            raise RunnerError(
                f"chunk {spec.chunk_index} has {got} frames, window needs "
                f"{window_frames} (short/tampered render?)"
            )
        try:
            os.replace(scratch, dest_final)
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise DiskFullError(
                    f"disk full finalizing chunk {spec.chunk_index}"
                ) from err
            raise
        return dest_final

    def _chunk_usable(self, spec: ChunkSpec) -> bool:
        """A stored chunk file is reusable only when it decodes exact."""
        path = self.chunk_path(spec.chunk_index)
        if not path.is_file():
            return False
        run = self._run_pins()
        rs, re = render_window(spec, run.frame_count)
        try:
            return count_video_frames(path) == (re - rs + 1)
        except StitchError:
            return False

    def render_pending(self, specs: list[ChunkSpec]) -> list[ChunkMedia]:
        """Render every non-completed chunk; reuse verified + exact files."""
        self._require_live_lease()
        run = self._run_pins()
        # C12 — VFR rejected pre-work: frame-exact trim math needs CFR.
        try:
            _src_fps, _rfr, _afr = check_source_cfr(Path(self._cfg.source_path))
        except StitchError as err:
            raise RunnerError(f"source CFR gate failed: {err}") from err
        chunk_dir = Path(self._cfg.chunk_dir)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        Path(self._cfg.scratch_dir).mkdir(parents=True, exist_ok=True)
        try:
            dims_w, dims_h = _probe_dims(Path(self._cfg.source_path))
            check_disk_for_run(
                chunk_dir,
                width=dims_w,
                height=dims_h,
                total_frames=run.frame_count,
            )
        except DiskInsufficientError as err:
            raise DiskFullError(str(err)) from err
        rows = {c.chunk_index: c for c in self._repo.list_chunks(run.id)}
        media: list[ChunkMedia] = []
        for spec in specs:
            self._require_not_cancelled()
            row = rows.get(spec.chunk_index)
            if row is None:  # pragma: no cover - ensure_plan always pins first
                raise RunnerError(f"chunk {spec.chunk_index} not pinned (stale?)")
            if row.content_hash != spec.content_hash:
                raise StaleIdentityError(
                    f"chunk {spec.chunk_index} pinned hash drifted (stale caller?)"
                )
            if row.state == "completed" and row.verified == 1:
                if self._chunk_usable(spec):
                    media.append(ChunkMedia(spec=spec, path=self.chunk_path(spec.chunk_index)))
                    continue
                # Completed+verified in the DB but the file on disk is short/
                # unreadable → tampered chunk: fail closed, never silently
                # accept it and never rewrite a terminal row.
                raise RunnerError(
                    f"chunk {spec.chunk_index} is completed+verified but its "
                    "file decodes short/unreadable (tampered chunk?)"
                )
            # (Re)render: pending / failed / skipped / unverified / tampered.
            if row.state == "pending":
                row = self._repo.transition_chunk(
                    row.id,
                    "running",
                    actor=self._cfg.worker_id,
                    fence_token=self._cfg.fence_token,
                    expected_revision=row.revision,
                )
            elif row.state in ("failed", "skipped"):
                # failed/skipped are terminal in T03A — a re-attempt is a NEW
                # attempt row, never a rewrite.  Fail closed here.
                raise RunnerError(
                    f"chunk {spec.chunk_index} is terminal ({row.state}); "
                    "re-attempt requires a new attempt row (not implemented "
                    "in T03B runner scope)"
                )
            try:
                path = self._render_window_file(spec, self.chunk_path(spec.chunk_index))
            except (DiskFullError, CancelledError):
                raise
            except RunnerError:
                self._repo.transition_chunk(
                    row.id,
                    "failed",
                    actor=self._cfg.worker_id,
                    fence_token=self._cfg.fence_token,
                    expected_revision=row.revision,
                )
                raise
            if row.state != "running":
                row = self._repo.transition_chunk(
                    row.id,
                    "running",
                    actor=self._cfg.worker_id,
                    fence_token=self._cfg.fence_token,
                    expected_revision=row.revision,
                )
            row = self._repo.transition_chunk(
                row.id,
                "completed",
                actor=self._cfg.worker_id,
                fence_token=self._cfg.fence_token,
                expected_revision=row.revision,
                verified=1,
            )
            _ = row
            media.append(ChunkMedia(spec=spec, path=path))
        return media

    # ── resume + assemble ───────────────────────────────────────────────

    def resume(self) -> Path:
        """Fresh-process-safe resume: re-read rows + files, finish the run.

        Reuses only completed+verified chunks whose file decodes to the
        exact window size; re-renders everything else; assembles the
        candidate.  No DB repair, no in-memory ownership carried over.
        """
        self._require_live_lease()
        self._require_not_cancelled()
        specs = self.ensure_plan()
        media = self.render_pending(specs)
        return self.assemble(media)

    def assemble(self, media: list[ChunkMedia]) -> Path:
        """Stitch verified chunk media into the atomic candidate."""
        self._require_live_lease()
        self._require_not_cancelled()
        run = self._run_pins()
        if len(media) != len(self.build_plan()):
            raise RunnerError(
                f"cannot assemble: {len(media)} chunk files for "
                f"{run.frame_count}-frame plan (incomplete?)"
            )
        try:
            return assemble_run(
                media,
                frame_count=run.frame_count,
                fps=self._cfg.fps,
                output_path=Path(self._cfg.output_path),
                audio_source=self._cfg.audio_source,
                scratch_dir=Path(self._cfg.scratch_dir),
            )
        except StitchError as err:
            raise RunnerError(f"assemble failed: {err}") from err
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise DiskFullError("disk full during assemble") from err
            raise

    # ── error-code surface consumed by T03C/Manager ─────────────────────

    @staticmethod
    def code_for(err: BaseException) -> str:
        if isinstance(err, StaleLeaseError):
            return "S12_T03B_STALE_LEASE"
        if isinstance(err, CancelledError):
            return "S12_T03B_CANCELLED"
        if isinstance(err, DiskFullError):
            return "S12_T03B_DISK_FULL"
        if isinstance(err, StaleIdentityError):
            return "S12_T03B_STALE_IDENTITY"
        if isinstance(err, FencedWorkerError):
            return "FENCED_WORKER"
        if isinstance(err, LeaseConflictError):
            return "LEASE_CONFLICT"
        return "S12_T03B_RUNNER_ERROR"


def _probe_dims(path: Path) -> tuple[int, int]:
    """Measured source dims (real ffprobe); fallback keeps disk gate safe."""
    import json
    import subprocess

    from app.services.ffmpeg_utils import find_ffprobe

    try:
        completed = subprocess.run(
            [
                find_ffprobe(),
                "-hide_banner",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except Exception:
        return 3840, 2160
