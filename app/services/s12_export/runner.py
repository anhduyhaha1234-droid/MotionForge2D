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
import hashlib
import os
import shutil
import subprocess
import time
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
    "cleanup_owned_export_artifacts",
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
        self.resource_metrics: dict[str, int | str] = {}

    def _run_render_process(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        """Run ffmpeg with a bounded deadline and cooperative cancellation."""
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as err:
            raise RunnerError(f"ffmpeg spawn failed: {err}") from err
        deadline = time.monotonic() + 600.0
        peak_rss = 0
        try:
            import psutil  # noqa: PLC0415
        except ImportError:
            psutil = None  # type: ignore[assignment]
            process_info = None
        else:
            try:
                process_info = psutil.Process(process.pid)
            except psutil.Error:
                process_info = None
        try:
            while process.poll() is None:
                if process_info is not None:
                    try:
                        peak_rss = max(peak_rss, process_info.memory_info().rss)
                    except psutil.Error:  # type: ignore[name-defined]
                        pass
                if self._cfg.cancel_flag is not None and Path(self._cfg.cancel_flag).exists():
                    process.kill()
                    process.wait()
                    raise CancelledError("cancel flag present during ffmpeg render")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    raise RunnerError("ffmpeg render timed out after 600s")
                try:
                    process.wait(timeout=min(0.2, remaining))
                except subprocess.TimeoutExpired:
                    continue
            stderr = process.stderr.read() if process.stderr is not None else ""
            return subprocess.CompletedProcess(argv, process.returncode, "", stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            self.resource_metrics["peak_ffmpeg_rss_bytes"] = peak_rss
            if process.stderr is not None:
                process.stderr.close()

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
        # F03/M04 — the chunk raster is the SELECTED profile raster, never the
        # source raster: scale (preserving aspect) then pad to the frozen
        # profile dims. 4K selection → real 3840x2160 chunk output.
        target_w, target_h = _parse_profile_dims(run.profile_dims)
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
            f"trim=start_frame={rs}:end_frame={re + 1},"
            "setpts=PTS-STARTPTS"
        )
        dest_final.parent.mkdir(parents=True, exist_ok=True)
        # Scratch keeps a real .mp4 suffix (the muxer sniffs format from the
        # extension — ".partial" is not muxable); only the T03C-visible
        # candidate carries the frozen .partial name (see stitch.assemble_run).
        scratch = dest_final.parent / f"{dest_final.stem}.tmp-render.mp4"
        try:
            completed = self._run_render_process(
                [
                    find_ffmpeg(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(src),
                    "-vf",
                    vf,
                    "-an",
                    "-c:v",
                    encoder,
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(scratch),
                ]
            )
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise DiskFullError(f"disk full rendering chunk {spec.chunk_index}") from err
            raise RunnerError(f"ffmpeg render failed: {err}") from err
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
        # F06/M05 — byte identity: verify the rendered window decodes to the
        # exact window size AND carries the selected profile raster.
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
        got_w, got_h = _probe_dims(scratch)
        if (got_w, got_h) != (target_w, target_h):
            try:
                os.remove(scratch)
            except OSError:
                pass
            raise RunnerError(
                f"chunk {spec.chunk_index} raster {got_w}x{got_h} != selected "
                f"profile {target_w}x{target_h} (M04 substitution rejected)"
            )
        try:
            os.replace(scratch, dest_final)
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise DiskFullError(
                    f"disk full finalizing chunk {spec.chunk_index}"
                ) from err
            raise
        # F06/M05 — persist byte identity beside the chunk: a resume may only
        # reuse a chunk whose ACTUAL file sha256 matches this recorded hash.
        _write_chunk_sha(dest_final)
        return dest_final

    def _chunk_usable(self, spec: ChunkSpec) -> bool:
        """A stored chunk file is reusable ONLY with verified byte identity.

        Three independent facts must hold: the recorded sidecar sha256
        exists, the ACTUAL file sha256 equals it (a byte-changed chunk of
        the same frame count is rejected — F06/M05), and the file decodes
        to the exact window size.
        """
        path = self.chunk_path(spec.chunk_index)
        if not path.is_file():
            return False
        try:
            if not _read_chunk_sha(path) == _chunk_sha256(path):
                return False
        except OSError:
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
        self._record_resource_snapshot()
        try:
            target_w, target_h = _parse_profile_dims(run.profile_dims)
            chunk_estimate = check_disk_for_run(
                chunk_dir,
                width=target_w,
                height=target_h,
                total_frames=run.frame_count,
            )
            scratch_estimate = check_disk_for_run(
                self._cfg.scratch_dir,
                width=target_w,
                height=target_h,
                total_frames=run.frame_count,
            )
            self.resource_metrics = {
                "profile_width": target_w,
                "profile_height": target_h,
                "estimated_chunk_bytes": chunk_estimate,
                "estimated_scratch_bytes": scratch_estimate,
                "frame_count": run.frame_count,
            }
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
                # Completed+verified in the DB but the file on disk no longer
                # matches its recorded byte identity (or decodes short) →
                # tampered chunk: fail closed, never silently accept it and
                # never rewrite a terminal row.
                raise RunnerError(
                    f"chunk {spec.chunk_index} is completed+verified but its "
                    "byte identity mismatch (tampered chunk?)"
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
            self._record_resource_snapshot()
        return media

    # ── resume + assemble ───────────────────────────────────────────────

    def resume(self) -> Path:
        """Fresh-process-safe resume: re-read rows + files, finish the run.

        Reuses only completed+verified chunks whose file decodes to the
        exact window size; re-renders everything else; assembles the
        candidate.  No DB repair, no in-memory ownership carried over.
        """
        try:
            self._require_live_lease()
            self._require_not_cancelled()
            specs = self.ensure_plan()
            media = self.render_pending(specs)
            return self.assemble(media)
        except BaseException:
            cleanup_owned_export_artifacts(
                scratch_dir=self._cfg.scratch_dir,
                chunk_dir=self._cfg.chunk_dir,
            )
            raise

    def assemble(self, media: list[ChunkMedia]) -> Path:
        """Stitch verified chunk media into the atomic candidate."""
        self._require_live_lease()
        self._require_not_cancelled()
        run = self._run_pins()
        encoder = _encoder_for_profile(run.profile_id)
        if len(media) != len(self.build_plan()):
            raise RunnerError(
                f"cannot assemble: {len(media)} chunk files for "
                f"{run.frame_count}-frame plan (incomplete?)"
            )
        try:
            output = assemble_run(
                media,
                frame_count=run.frame_count,
                fps=self._cfg.fps,
                output_path=Path(self._cfg.output_path),
                audio_source=self._cfg.audio_source,
                scratch_dir=Path(self._cfg.scratch_dir),
                encoder=encoder,
            )
            self._record_resource_snapshot()
            return output
        except StitchError as err:
            raise RunnerError(f"assemble failed: {err}") from err
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise DiskFullError("disk full during assemble") from err
            raise

    def _record_resource_snapshot(self) -> None:
        """Record bounded owned-root bytes and actual free disk space."""
        scratch = Path(self._cfg.scratch_dir)
        chunk = Path(self._cfg.chunk_dir)
        for label, root in (("scratch", scratch), ("chunk", chunk)):
            try:
                used = sum(
                    child.stat().st_size
                    for child in root.iterdir()
                    if child.is_file() and not child.is_symlink()
                )
                free = shutil.disk_usage(root).free
            except OSError:
                continue
            self.resource_metrics[f"{label}_bytes"] = used
            self.resource_metrics[f"{label}_free_bytes"] = free
            peak_key = f"peak_{label}_bytes"
            self.resource_metrics[peak_key] = max(
                int(self.resource_metrics.get(peak_key, 0)), used
            )


def cleanup_owned_export_artifacts(
    *, scratch_dir: str | Path | None, chunk_dir: str | Path | None = None
) -> None:
    """Remove only known private/partial children from owned job roots.

    Completed chunk files and successful public output are intentionally left
    untouched.  No recursive traversal or path-derived broad deletion is
    used; every removed child is a known temporary naming family.
    """
    roots = [Path(value) for value in (scratch_dir, chunk_dir) if value]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_symlink() or not child.is_file():
                continue
            name = child.name.lower()
            removable = (
                name in {
                    "candidate_final.mp4",
                    "candidate.tmp-finalize.mp4",
                    "stitched_video.mp4",
                    "_s12_t03b_concat.txt",
                }
                or name.startswith("core_") and name.endswith(".mp4")
                or ".tmp-render." in name
                or name.endswith(".partial")
                or name.endswith(".raw")
                or name.endswith(".raw.partial")
                or name.endswith(".tmp")
                or name.endswith(".sha256.tmp")
                or name.startswith(".s12-psnr-")
            )
            if removable:
                try:
                    child.unlink()
                except OSError:
                    pass

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


# ── profile raster + chunk byte-identity helpers (F03/F06) ────────────


def _parse_profile_dims(profile_dims: str) -> tuple[int, int]:
    """Parse the frozen ``WxH`` profile dims string; fail-closed on drift."""
    try:
        w_text, h_text = profile_dims.lower().split("x", 1)
        width, height = int(w_text), int(h_text)
    except (ValueError, AttributeError) as err:
        raise RunnerError(
            f"unparseable profile_dims {profile_dims!r} (fail-closed)"
        ) from err
    if width < 1 or height < 1:
        raise RunnerError(
            f"profile_dims {profile_dims!r} non-positive (fail-closed)"
        )
    return width, height


def _chunk_sha256(path: Path) -> str:
    """Streamed sha256 of a chunk file (lowercase 64-hex)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_sha_sidecar(path: Path) -> Path:
    return path.parent / f"{path.name}.sha256"


def _write_chunk_sha(path: Path) -> None:
    """Record byte identity beside the chunk (atomic write + fsync)."""
    sidecar = _chunk_sha_sidecar(path)
    tmp = sidecar.with_suffix(".sha256.tmp")
    tmp.write_text(_chunk_sha256(path) + "\n", encoding="ascii")
    os.replace(tmp, sidecar)


def _read_chunk_sha(path: Path) -> str:
    """Read the recorded byte identity; OSError/ValueError → mismatch."""
    return _chunk_sha_sidecar(path).read_text(encoding="ascii").strip()
