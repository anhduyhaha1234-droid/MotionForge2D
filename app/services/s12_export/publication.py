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
   public output is created by ONE exclusive ``os.link`` from the
   validated candidate, only after the source-locked validator scores
   ``PASS``.  Exclusive creation lets a stale participant lose without
   an overwrite-capable rename touching a winner.  The private candidate
   remains until the fenced DB commit and is then cleaned by its owner.
   A private staged copy of the candidate is created before the seam and
   its inode identity (volume + file index) is recorded in the intent;
   the public file is adopted later only when it is provably that exact
   inode -- a byte-equal foreign copy is a different inode and is denied.
5. **Validation** — the candidate scores ``PASS`` against server-owned
   source-locked expectations (T04A C2 contract; ``FAIL`` /
   ``NOT_MEASURED`` fails closed and lands the run ``failed``).
6. **Commit boundary** — the filesystem rename, sidecar, and publication
   receipt are durable file operations; the run transitions
   ``running -> verifying -> completed`` under fence + revision CAS in a
   separate SQLite transaction.  The receipt makes that file/DB boundary
   recoverable without unchecked overwrite.  A real cross-process
   publication lock (``_PublicationGuard``) serializes ownership
   re-validation, intent, exclusive creation and companion writes, so an
   expired participant performs no public publication at all.
7. **Completed replay by bytes** — a replayed publication re-verifies
   the existing public artifact (sha256 vs the server-owned expected
   hash when asserted; never a bare status shortcut) before returning
   ``reused``.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.services.s12_export.publication_lease_guard import (
    publication_lease_guard,
    sqlite_db_path_from_session,
)

__all__ = [
    "PublicationError",
    "PublicationPathError",
    "PublicationRaceLost",
    "publish_export_run",
]

_CHUNK_DIR = "chunk_dir"
_SCRATCH_DIR = "scratch_dir"
_OUTPUT_PATH = "output_path"
_CANDIDATE_PATH = "candidate_path"
_HASH_CHUNK = 1024 * 1024
_RECEIPT_SUFFIX = ".publication.json"


class PublicationError(ValueError):
    """Fail-closed publication gate error."""


class PublicationPathError(PublicationError):
    """The public artifact or its immutable companions cannot be addressed."""

    code = "S12_T03C_PUBLICATION_PATH_INVALID"


class PublicationRaceLost(PublicationError):
    """Another fenced participant exclusively published the final bytes."""

    code = "S12_T03C_PUBLICATION_RACE_LOST"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(_HASH_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _file_identity(path: Path) -> dict[str, int]:
    """Durable inode identity: volume + file index + size + mtime_ns."""
    stat = path.stat()
    return {
        "dev": int(stat.st_dev),
        "ino": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _identity_matches(path: Path, recorded: Any) -> bool:
    """True only when *path* is the exact inode one attempt recorded.

    Byte equality is never sufficient: an external copy with identical
    bytes is a different inode and must not be adopted.
    """
    if not isinstance(recorded, dict):
        return False
    try:
        dev = int(recorded["dev"])
        ino = int(recorded["ino"])
    except (KeyError, TypeError, ValueError):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return int(stat.st_dev) == dev and int(stat.st_ino) == ino


def _sidecar_path(final: Path) -> Path:
    """Sidecar holding the immutable byte identity of the public artifact."""
    return final.with_name(f"{final.name}.sha256")


def _publication_receipt_path(final: Path) -> Path:
    """Receipt binding an output's bytes to one export attempt."""
    return final.with_name(f"{final.name}{_RECEIPT_SUFFIX}")


_INTENT_SUFFIX = ".publication.intent"


def _publication_intent_path(final: Path) -> Path:
    """Intent proving which private attempt may complete a public write."""
    return final.with_name(f"{final.name}{_INTENT_SUFFIX}")


_PUBLICATION_LOCK_SUFFIX = ".publication.lock"
_PUBLICATION_LOCK_POLL_SECONDS = 0.05
_PUBLICATION_LOCK_WAIT_SECONDS = 30.0


def _publication_lock_path(final: Path) -> Path:
    """Cross-process lock file serializing the public mutation."""
    return final.with_name(f"{final.name}{_PUBLICATION_LOCK_SUFFIX}")


class _PublicationGuard:
    """Real exclusive lock over ownership, intent, creation and companions.

    The primitive is an OS-level advisory byte-range lock (``msvcrt`` on
    Windows, ``flock`` elsewhere) held for the entire public mutation
    span: ownership re-validation, intent, exclusive creation, sidecar
    and receipt.  An expired participant therefore performs NO public
    publication -- it is re-validated (and denied) inside one mutual
    exclusion shared with every other live participant.  The empty lock
    file is a coordination artifact and is never read as data.
    """

    def __init__(self, final: Path) -> None:
        self._path = _publication_lock_path(final)
        self._fd: int | None = None

    def __enter__(self) -> _PublicationGuard:
        native = _native_fs_path(self._path)
        deadline = time.monotonic() + _PUBLICATION_LOCK_WAIT_SECONDS
        while True:
            try:
                fd = os.open(native, os.O_CREAT | os.O_RDWR, 0o600)
            except OSError as err:
                raise PublicationError(
                    f"publication lock is unavailable: {self._path}"
                ) from err
            try:
                self._acquire_native(fd)
            except OSError:
                os.close(fd)
                if time.monotonic() >= deadline:
                    raise PublicationError(
                        f"publication lock wait timed out: {self._path}"
                    ) from None
                time.sleep(_PUBLICATION_LOCK_POLL_SECONDS)
                continue
            self._fd = fd
            return self

    @staticmethod
    def _acquire_native(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, *exc: object) -> None:
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415

                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)


def _exclusive_temp_path(
    path: Path, owner_token: str, *, nonce: str | None = None
) -> Path:
    safe_token = "".join(ch for ch in owner_token if ch.isalnum()) or "owner"
    suffix = nonce or uuid.uuid4().hex
    return path.with_name(f"{path.name}.{safe_token}.{suffix}.tmp")


def _native_fs_path(path: Path) -> str:
    """Use the Windows extended path form for long, valid Unicode paths."""
    value = os.fspath(path)
    if os.name != "nt" or value.startswith("\\\\?\\") or len(value) < 248:
        return value
    return "\\\\?\\" + os.path.abspath(value)


def _write_exclusive_file(path: Path, payload: bytes, *, owner_token: str) -> None:
    """Create *path* once, using an owner-unique temp and exclusive link."""
    tmp = _exclusive_temp_path(path, owner_token)
    fd: int | None = None
    try:
        fd = os.open(
            _native_fs_path(tmp),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link creation is the exclusive visibility primitive: it fails
        # when a participant already created the destination and never
        # replaces an existing sidecar or receipt.
        os.link(_native_fs_path(tmp), _native_fs_path(path))
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(_native_fs_path(tmp))
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _write_sidecar(final: Path, sha: str) -> None:
    """Create the byte-identity sidecar without replacing foreign bytes."""
    _write_exclusive_file(
        _sidecar_path(final),
        (sha.strip().lower() + "\n").encode("ascii"),
        owner_token=sha,
    )


def _write_publication_receipt(final: Path, payload: dict[str, Any]) -> None:
    """Persist ownership/content/validation identity before the DB commit."""
    _write_exclusive_file(
        _publication_receipt_path(final),
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
        owner_token=str(payload["fence_token"]),
    )


def _intent_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def _write_publication_intent(final: Path, payload: dict[str, Any]) -> None:
    """Durably bind the public path to one private attempt before linking."""
    _write_exclusive_file(
        _publication_intent_path(final),
        _intent_bytes(payload),
        owner_token=str(payload["fence_token"]),
    )


def _replace_publication_intent(final: Path, payload: dict[str, Any]) -> None:
    """Refresh the intent for the SAME attempt (caller holds the guard).

    A restaged copy of the same worker/fence attempt gets a new inode;
    the durable record must name the inode the next link will expose.
    """
    path = _publication_intent_path(final)
    temp = _exclusive_temp_path(path, str(payload["fence_token"]))
    fd: int | None = None
    try:
        fd = os.open(
            _native_fs_path(temp),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(_intent_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(_native_fs_path(temp), _native_fs_path(path))
    finally:
        if fd is not None:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(_native_fs_path(temp))


def _receipt_payload(
    run: Any,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    fence_token: str,
    artifact_sha: str,
    verdict: Any,
    artifact_identity: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build the durable identity record shared by fresh and recovered writes.

    ``artifact_identity`` names the exact published inode, so a receipt
    can never authorize adopting a foreign (even byte-equal) copy.
    """
    return {
        "version": 1,
        "run_id": run_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": run.video_item_id,
        "attempt": int(run.attempt),
        "fence_token": fence_token,
        "checkpoint_hash": run.checkpoint_hash,
        "manifest_hash": run.manifest_hash,
        "plan_hash": run.plan_hash,
        "profile_id": run.profile_id,
        "artifact_sha256": artifact_sha,
        "candidate_sha256": artifact_sha,
        "validation_verdict": verdict.verdict,
        "validation_probes": [
            p.name for p in verdict.probes if p.verdict == "PASS"
        ],
        **(
            {"artifact_identity": artifact_identity}
            if artifact_identity is not None
            else {}
        ),
    }


def _intent_payload(
    run: Any,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    worker_id: str,
    fence_token: str,
    final: Path,
    candidate: Path,
    artifact_sha: str,
    expected_sha: str,
    staged: Path | None = None,
) -> dict[str, Any]:
    """Build the durable pre-publication identity used after a crash.

    ``candidate_identity`` records the private attempt's own inode;
    ``staged_identity`` (when a staged copy exists) records the exact
    inode that the exclusive link will expose publicly.  Recovery adopts
    a public file only when it is provably ``staged_identity``.
    """
    return {
        "version": 1,
        "kind": "s12-publication-intent",
        "run_id": run_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": run.video_item_id,
        "attempt": int(run.attempt),
        "worker_id": worker_id,
        "fence_token": fence_token,
        "checkpoint_hash": run.checkpoint_hash,
        "manifest_hash": run.manifest_hash,
        "plan_hash": run.plan_hash,
        "profile_id": run.profile_id,
        "output_path": str(final),
        "candidate_path": str(candidate),
        "candidate_sha256": artifact_sha,
        "expected_sha256": str(expected_sha or ""),
        "candidate_identity": _file_identity(candidate),
        **(
            {"staged_identity": _file_identity(staged)}
            if staged is not None
            else {}
        ),
    }


def _before_publication_primitive(candidate: Path, final: Path) -> None:
    """Rendezvous seam immediately before exclusive final creation."""
    _ = candidate, final


def _after_publication_final(final: Path) -> None:
    """Fault seam immediately after final creation and before its sidecar."""
    _ = final


def _read_publication_intent(final: Path) -> dict[str, Any] | None:
    """Read an intent strictly; malformed or aliased proof fails closed."""
    path = _publication_intent_path(final)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise PublicationError(f"publication intent is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as err:
        raise PublicationError(f"publication intent is unreadable: {path}") from err
    if not isinstance(payload, dict):
        raise PublicationError(f"publication intent is not an object: {path}")
    return payload


def _intent_candidate_path(
    payload: dict[str, Any], manifest: dict[str, Any], run: Any
) -> Path | None:
    """Resolve only an attempt-owned candidate named by a valid intent."""
    try:
        candidate = Path(str(payload["candidate_path"]))
        attempt = int(payload["attempt"])
    except (KeyError, TypeError, ValueError):
        return None
    if candidate.name != "candidate_final.mp4" or candidate.is_symlink():
        return None
    scratch = Path(str(manifest.get(_SCRATCH_DIR, "")))
    try:
        scratch_root = scratch.resolve().parent
        resolved_parent = candidate.resolve().parent
        if candidate.parent.is_symlink() or scratch_root.is_symlink():
            return None
        same_current = resolved_parent == scratch.resolve()
        same_attempt_root = (
            resolved_parent.parent == scratch_root
            and resolved_parent != scratch_root
        )
    except OSError:
        return None
    if not (same_current or same_attempt_root):
        return None
    if attempt != int(getattr(run, "attempt", -1)):
        return None
    return candidate


def _intent_matches_run(
    payload: dict[str, Any],
    run: Any,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    final: Path,
    expected_sha: str,
    candidate_sha: str | None = None,
) -> bool:
    expected = {
        "version": 1,
        "kind": "s12-publication-intent",
        "run_id": run_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": run.video_item_id,
        "attempt": int(run.attempt),
        "checkpoint_hash": run.checkpoint_hash,
        "manifest_hash": run.manifest_hash,
        "plan_hash": run.plan_hash,
        "profile_id": run.profile_id,
        "output_path": str(final),
        "expected_sha256": str(expected_sha or ""),
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        return False
    if not isinstance(payload.get("worker_id"), str):
        return False
    if not isinstance(payload.get("fence_token"), str) or not payload["fence_token"]:
        return False
    if not isinstance(payload.get("candidate_path"), str):
        return False
    if candidate_sha is not None and payload.get("candidate_sha256") != candidate_sha:
        return False
    return True


def _ensure_publication_intent(
    final: Path,
    payload: dict[str, Any],
    *,
    repo: Any,
    run: Any,
    manifest: dict[str, Any],
) -> None:
    """Create one intent, or replace only a proven dead same-run intent."""
    path = _publication_intent_path(final)
    if not path.exists():
        _write_publication_intent(final, payload)
        return
    existing = _read_publication_intent(final)
    if existing is None:
        _write_publication_intent(final, payload)
        return
    if not _intent_matches_run(
        existing,
        run,
        run_id=str(payload["run_id"]),
        workspace_id=str(payload["workspace_id"]),
        project_id=str(payload["project_id"]),
        final=final,
        expected_sha=str(payload["expected_sha256"]),
    ):
        raise PublicationError(f"publication intent identity mismatch: {path}")
    try:
        if path.read_bytes() != _intent_bytes(existing):
            raise PublicationError(f"publication intent bytes were tampered: {path}")
    except OSError as err:
        raise PublicationError(f"publication intent is unreadable: {path}") from err
    old_candidate = _intent_candidate_path(existing, manifest, run)
    if old_candidate is None or not old_candidate.is_file():
        raise PublicationError(f"publication intent candidate is unavailable: {path}")
    try:
        if _sha256_file(old_candidate) != existing["candidate_sha256"]:
            raise PublicationError(f"publication intent candidate was tampered: {path}")
    except OSError as err:
        raise PublicationError(f"publication intent candidate is unreadable: {path}") from err
    same_owner = (
        existing.get("worker_id") == payload["worker_id"]
        and existing.get("fence_token") == payload["fence_token"]
        and existing.get("candidate_path") == payload["candidate_path"]
    )
    if same_owner:
        if existing.get("candidate_sha256") != payload["candidate_sha256"]:
            raise PublicationError(f"publication intent candidate changed: {path}")
        if _intent_bytes(existing) != _intent_bytes(payload):
            # The same attempt restaged its publishable copy: refresh the
            # recorded inode identity so recovery can still prove adoption.
            _replace_publication_intent(final, payload)
        return
    if _owner_is_live(
        repo,
        str(payload["run_id"]),
        str(existing["worker_id"]),
        str(existing["fence_token"]),
    ):
        # A second live participant may proceed to the same exclusive final
        # primitive.  It must not replace the first intent or any winner file.
        return
    try:
        path.unlink()
    except OSError as err:
        raise PublicationError(f"publication intent cleanup failed: {path}") from err
    _write_publication_intent(final, payload)


def _remove_owned_publication_intent(
    final: Path, payload: dict[str, Any] | None
) -> None:
    """Remove only the exact intent bytes this owner wrote."""
    if payload is None:
        return
    path = _publication_intent_path(final)
    try:
        if path.is_symlink() or not path.is_file():
            return
        if path.read_bytes() == _intent_bytes(payload):
            path.unlink()
    except OSError:
        pass


#: Staged publishable copy for the CURRENT attempt thread; the two-argument
#: exclusive primitive reads it so bounded harnesses keep their call shape.
_STAGED_COPY: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "s12_staged_publication_copy", default=None
)


def _stage_publication_copy(candidate: Path) -> Path:
    """Copy the validated candidate to an owner-unique staged inode.

    The staged inode (never the private candidate itself) becomes the
    public file through the exclusive link, so its durable identity can
    be recorded in the intent *before* the irreversible public mutation.
    """
    staged = candidate.with_name(f"{candidate.name}.{uuid.uuid4().hex}.tmp")
    fd: int | None = None
    try:
        fd = os.open(
            _native_fs_path(staged),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with open(_native_fs_path(candidate), "rb") as source, os.fdopen(
            fd, "wb"
        ) as target:
            fd = None
            while True:
                block = source.read(_HASH_CHUNK)
                if not block:
                    break
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        return staged
    except BaseException:
        if fd is not None:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(_native_fs_path(staged))
        raise


def _publish_candidate_exclusive(candidate: Path, final: Path) -> dict[str, int]:
    """Expose one owned inode at the public path exactly once.

    The staged inode to expose travels via ``_STAGED_COPY`` (set by the
    publish flow in this same thread); when it is absent -- e.g. a bounded
    reviewer/harness that calls this two-argument primitive directly -- a
    fresh owned copy of the candidate is staged here.  The staged inode's
    identity is verified on the published file before any companion may
    be written; the exclusive link never replaces a foreign inode.
    """
    staged = _STAGED_COPY.get(None)
    if staged is None:
        staged = _stage_publication_copy(candidate)
    staged_identity = _file_identity(staged)
    try:
        os.link(_native_fs_path(staged), _native_fs_path(final))
    except FileExistsError as err:
        raise PublicationRaceLost(
            f"publication race lost: final already exists and is immutable: {final}"
        ) from err
    finally:
        with contextlib.suppress(OSError):
            os.unlink(_native_fs_path(staged))
    if not _identity_matches(final, staged_identity):
        raise PublicationError(
            f"published final is not the staged inode: {final}"
        )
    return staged_identity


_MAX_PUBLICATION_COMPONENT_BYTES = 240
_MAX_PUBLICATION_PATH_CHARS = 32767


def _preflight_publication_paths(final: Path, *, owner_token: str = "") -> None:
    """Validate every public name and the actual exclusive temp companions."""
    if not final.is_absolute():
        raise PublicationPathError("public output path must be absolute")
    paths = (
        final,
        _sidecar_path(final),
        _publication_receipt_path(final),
        _publication_intent_path(final),
    )
    if not final.parent.is_dir() or final.parent.is_symlink():
        raise PublicationPathError(
            f"public output parent is not an owned directory: {final.parent}"
        )
    # The coordination lock is created directly (no exclusive temp), so
    # only its own name/path must be addressable -- never a temp bound.
    lock = _publication_lock_path(final)
    try:
        lock_component_bytes = len(lock.name.encode("utf-8"))
    except UnicodeError as err:
        raise PublicationPathError(
            f"public output lock name is not encodable: {lock.name!r}"
        ) from err
    if lock_component_bytes > _MAX_PUBLICATION_COMPONENT_BYTES:
        raise PublicationPathError(
            f"public output lock name is too long: {lock.name!r}"
        )
    if len(str(lock)) > _MAX_PUBLICATION_PATH_CHARS:
        raise PublicationPathError(f"public output lock path is too long: {lock}")
    if len(_native_fs_path(lock)) > _MAX_PUBLICATION_PATH_CHARS:
        raise PublicationPathError(f"public output lock path is too long: {lock}")
    for path in paths:
        try:
            component_bytes = len(path.name.encode("utf-8"))
        except UnicodeError as err:
            raise PublicationPathError(
                f"public output name is not encodable: {path.name!r}"
            ) from err
        if component_bytes > _MAX_PUBLICATION_COMPONENT_BYTES:
            raise PublicationPathError(
                f"public output companion name is too long: {path.name!r}"
            )
        if len(str(path)) > _MAX_PUBLICATION_PATH_CHARS:
            raise PublicationPathError(
                f"public output companion path is too long: {path}"
            )
        # The sidecar, receipt, and intent use the same helper as the write
        # path.  A digest is 64 characters; the lease token may be shorter or
        # longer, so validate both the actual token and the conservative
        # digest-shaped upper bound before any public mutation.
        owner_tokens = (owner_token, "f" * 64)
        for token in owner_tokens:
            temporary = _exclusive_temp_path(path, token, nonce="0" * 32)
            try:
                temporary_bytes = len(temporary.name.encode("utf-8"))
            except UnicodeError as err:
                raise PublicationPathError(
                    f"public output temporary name is not encodable: {temporary.name!r}"
                ) from err
            if temporary_bytes > _MAX_PUBLICATION_COMPONENT_BYTES:
                raise PublicationPathError(
                    f"public output temporary companion name is too long: {temporary.name!r}"
                )
            if len(str(temporary)) > _MAX_PUBLICATION_PATH_CHARS:
                raise PublicationPathError(
                    f"public output temporary companion path is too long: {temporary}"
                )
            if len(_native_fs_path(temporary)) > _MAX_PUBLICATION_PATH_CHARS:
                raise PublicationPathError(
                    f"public output native temporary path is too long: {temporary}"
                )


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
    the public output through one exclusive hard-link creation.  SQLite commit and
    filesystem publication are separate operations; a receipt binds the
    bytes and validation identity so a fresh owner can reconcile an
    uncertain acknowledgement.
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

    final = Path(str(manifest[_OUTPUT_PATH]))
    if final.name.lower().endswith(".partial"):
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError("public output must not carry the .partial suffix")
    try:
        _preflight_publication_paths(final, owner_token=fence_token)
    except PublicationPathError:
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise
    if final.exists() or final.is_symlink():
        with (
            publication_lease_guard(
                run_id, db_path=sqlite_db_path_from_session(session)
            ),
            _PublicationGuard(final),
        ):
            recovered = _recover_pending_publication(
                session,
                repo,
                run,
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                worker_id=worker_id,
                fence_token=fence_token,
                manifest=manifest,
                final=final,
            )
        if recovered is not None:
            _cleanup_publication_scratch(
                manifest,
                session=session,
                run_id=run_id,
                worker_id=worker_id,
                fence_token=fence_token,
            )
            return recovered
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError(
            f"completed output exists — refusing overwrite: {final}"
        )
    sidecar = _sidecar_path(final)
    receipt = _publication_receipt_path(final)
    if sidecar.exists() or sidecar.is_symlink() or receipt.exists() or receipt.is_symlink():
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError(
            f"publication companions exist without a final artifact; refusing overwrite: {final}"
        )
    candidate = _candidate_path(manifest)
    if candidate is None or not candidate.is_file():
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError(
            f"no private candidate for run {run_id}; cannot publish"
        )
    if candidate.resolve() == final.resolve():
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError("candidate must be private, never the public output")

    try:
        _require_ready(session, workspace_id=workspace_id, project_id=project_id)
        _require_fence(repo, run_id, worker_id, fence_token)
    except BaseException:
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise

    try:
        candidate_sha = _sha256_file(candidate)
        expectation = _expectation_for(run, manifest, candidate_sha=candidate_sha)
        verdict = validate(candidate, expectation)
    except BaseException:
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise
    if verdict.verdict != "PASS":
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        failing = [p.name for p in verdict.probes if p.verdict != "PASS"]
        raise PublicationError(
            f"export validation {verdict.verdict} on {failing}; run failed (retryable)"
        )

    # ONE immutable publication: stage the validated candidate, record the
    # attempt's durable inode identity, then exclusively create the public
    # path, write its sidecar and receipt and commit the fenced SQLite
    # state -- all inside one cross-process publication lock so a stale
    # participant can never win the public mutation.
    try:
        staged = _stage_publication_copy(candidate)
    except OSError as err:
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        raise PublicationError(f"publication rename failed: {err}") from err
    intent_payload = _intent_payload(
        run,
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        worker_id=worker_id,
        fence_token=fence_token,
        final=final,
        candidate=candidate,
        artifact_sha=candidate_sha,
        expected_sha=str(
            manifest.get("expected_sha256")
            or manifest.get("authority_sha256")
            or ""
        ),
        staged=staged,
    )
    try:
        # Publish the attempt identity before the seam: the recovery proof
        # must be durable before any public mutation can happen.
        _ensure_publication_intent(
            final,
            intent_payload,
            repo=repo,
            run=run,
            manifest=manifest,
        )
        _before_publication_primitive(candidate, final)
        with (
            publication_lease_guard(
                run_id, db_path=sqlite_db_path_from_session(session)
            ),
            _PublicationGuard(final),
        ):
            # The run ownership transition is serialized OUT of this entire
            # section: a claim cannot interleave with the verified owner's
            # public mutation and fenced transitions.  Inside ONE real
            # mutual exclusion: re-validated ownership, refreshed intent,
            # exclusive creation and every companion.
            _require_fence(repo, run_id, worker_id, fence_token)
            _ensure_publication_intent(
                final,
                intent_payload,
                repo=repo,
                run=run,
                manifest=manifest,
            )
            staged_token = _STAGED_COPY.set(staged)
            try:
                _publish_candidate_exclusive(candidate, final)
            finally:
                _STAGED_COPY.reset(staged_token)
            return _finalize_published_artifact(
                session,
                repo,
                run=run,
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                worker_id=worker_id,
                fence_token=fence_token,
                manifest=manifest,
                final=final,
                verdict=verdict,
                intent_payload=intent_payload,
            )
    except PublicationRaceLost:
        # The losing worker must not clean or mutate a winner's final,
        # sidecar, receipt, or a candidate belonging to a different fence.
        raise
    except OSError as err:
        _remove_owned_publication_intent(final, intent_payload)
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        raise PublicationError(f"publication rename failed: {err}") from err
    except FencedWorkerError as err:
        _remove_owned_publication_intent(final, intent_payload)
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError(f"publication fence lost before rename: {err}") from err
    except PublicationError:
        # Identity or hook failures before final creation preserve the
        # foreign proof bytes but release only this owner's private candidate.
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise


def _finalize_published_artifact(
    session: Any,
    repo: Any,
    *,
    run: Any,
    run_id: str,
    workspace_id: str,
    project_id: str,
    worker_id: str,
    fence_token: str,
    manifest: dict[str, Any],
    final: Path,
    verdict: Any,
    intent_payload: dict[str, Any],
) -> dict[str, Any]:
    """Serialized post-create finalization (caller holds the guard).

    Binds the sidecar and receipt to the published inode's durable
    identity, commits the fenced transitions and releases this attempt's
    private scratch.  Nothing here deletes or replaces an inode this
    attempt did not create.
    """
    from app.persistence.s12_export import FencedWorkerError  # noqa: PLC0415

    _after_publication_final(final)
    actual_sha = _sha256_file(final)
    published_identity = _file_identity(final)
    sidecar_owned = False
    receipt_owned = False
    try:
        _write_sidecar(final, actual_sha)
        sidecar_owned = True
    except OSError as err:
        if _owner_is_live(repo, run_id, worker_id, fence_token):
            _remove_unpublished_output(final, expected_sha=actual_sha)
            _remove_owned_publication_intent(final, intent_payload)
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        raise PublicationError(f"publication sidecar failed: {err}") from err
    try:
        _write_publication_receipt(
            final,
            _receipt_payload(
                run,
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                fence_token=fence_token,
                artifact_sha=actual_sha,
                verdict=verdict,
                artifact_identity=published_identity,
            ),
        )
        receipt_owned = True
    except OSError as err:
        if _owner_is_live(repo, run_id, worker_id, fence_token):
            _remove_unpublished_output(
                final,
                expected_sha=actual_sha,
                remove_sidecar=sidecar_owned,
            )
            _remove_owned_publication_intent(final, intent_payload)
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        _fail_run(repo, run_id, worker_id, fence_token, run.revision)
        session.commit()
        raise PublicationError(f"publication receipt failed: {err}") from err
    # Inside the held publication section, extend this owner's own lease so
    # the fenced transitions below remain authorized: ownership claims are
    # serialized out of the section, so a token-CAS extension without an
    # expiry predicate is safe and authoritative here.
    repo.extend_lease_for_publication(run_id, worker_id, fence_token)
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
        # The exclusive final creation happened but the transition lost the race — never
        # report completed: the artifact stays, the run is failed/retryable
        # and a later winner converges by bytes.
        session.rollback()
        if _owner_is_live(repo, run_id, worker_id, fence_token):
            _remove_unpublished_output(
                final,
                expected_sha=actual_sha,
                remove_sidecar=sidecar_owned,
                remove_receipt=receipt_owned,
            )
            _remove_owned_publication_intent(final, intent_payload)
        _cleanup_publication_scratch(
            manifest,
            session=session,
            run_id=run_id,
            worker_id=worker_id,
            fence_token=fence_token,
        )
        raise PublicationError(
            f"publication transition lost after final creation: {err} (run {run_id})"
        ) from err
    session.commit()
    _remove_owned_publication_intent(final, intent_payload)
    _cleanup_publication_scratch(
        manifest,
        session=session,
        run_id=run_id,
        worker_id=worker_id,
        fence_token=fence_token,
    )
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


def _recover_pending_publication(
    session: Any,
    repo: Any,
    run: Any,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    worker_id: str,
    fence_token: str,
    manifest: dict[str, Any],
    final: Path,
) -> dict[str, Any] | None:
    """Reconcile a file/DB boundary after an uncertain publication commit.

    The receipt is only a locator.  Adoption still requires the current live
    fence, matching run lineage, matching sidecar/file bytes, current
    readiness, and a fresh source-locked PASS.  A completed winner without
    this proof is preserved and never overwritten or deleted.
    """
    if final.is_symlink() or not final.is_file():
        return None
    receipt_path = _publication_receipt_path(final)
    if receipt_path.is_symlink():
        return None
    expected_sha = manifest.get("expected_sha256") or manifest.get("authority_sha256")
    try:
        intent = _read_publication_intent(final)
    except PublicationError:
        return None
    if not receipt_path.exists():
        if not _recover_pre_receipt_publication(
            session,
            repo,
            run,
            run_id=run_id,
            workspace_id=workspace_id,
            project_id=project_id,
            worker_id=worker_id,
            fence_token=fence_token,
            manifest=manifest,
            final=final,
        ):
            return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            return None
        actual_sha = _sha256_file(final)
        stored_sha = _sidecar_path(final).read_text(encoding="ascii").strip().lower()
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return None
    if stored_sha != actual_sha:
        return None
    if not _identity_matches(final, receipt.get("artifact_identity")):
        # The published file must be the exact inode this attempt created;
        # a byte-equal foreign copy is a different inode and is never
        # adopted (nor removed) here.
        return None
    if intent is not None and not _intent_matches_run(
        intent,
        run,
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        final=final,
        expected_sha=str(expected_sha or ""),
        candidate_sha=actual_sha,
    ):
        return None
    if intent is not None and not _identity_matches(
        final, intent.get("staged_identity")
    ):
        return None
    if any(
        receipt.get(key) != expected
        for key, expected in (
            ("version", 1),
            ("run_id", run_id),
            ("workspace_id", workspace_id),
            ("project_id", project_id),
            ("video_item_id", run.video_item_id),
            ("checkpoint_hash", run.checkpoint_hash),
            ("manifest_hash", run.manifest_hash),
            ("plan_hash", run.plan_hash),
            ("profile_id", run.profile_id),
            ("artifact_sha256", actual_sha),
            ("candidate_sha256", actual_sha),
            ("validation_verdict", "PASS"),
        )
    ):
        return None
    try:
        if int(receipt.get("attempt")) != int(run.attempt):
            return None
    except (TypeError, ValueError):
        return None
    if expected_sha and str(expected_sha).lower() != actual_sha:
        return None

    _require_ready(session, workspace_id=workspace_id, project_id=project_id)
    _require_fence(repo, run_id, worker_id, fence_token)
    from app.services.s12_export.validation import validate  # noqa: PLC0415

    expectation = _expectation_for(run, manifest, candidate_sha=actual_sha)
    verdict = validate(final, expectation)
    if verdict.verdict != "PASS":
        return None
    if run.status == "running":
        verifying = repo.transition_run(
            run_id,
            "verifying",
            actor=worker_id,
            expected_revision=run.revision,
            fence_token=fence_token,
        )
    elif run.status == "verifying":
        verifying = run
    else:
        return None
    completed = repo.transition_run(
        run_id,
        "completed",
        actor=worker_id,
        expected_revision=verifying.revision,
        fence_token=fence_token,
    )
    session.commit()
    _remove_owned_publication_intent(final, intent)
    return {
        "run_id": run_id,
        "status": completed.status,
        "revision": completed.revision,
        "output_path": str(final),
        "artifact_sha256": actual_sha,
        "verdict": verdict.verdict,
        "recovered": True,
        "probes": [
            {"name": p.name, "verdict": p.verdict, "detail": p.detail}
            for p in verdict.probes
        ],
    }


def _recover_pre_receipt_publication(
    session: Any,
    repo: Any,
    run: Any,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    worker_id: str,
    fence_token: str,
    manifest: dict[str, Any],
    final: Path,
) -> bool:
    """Rebuild missing companions only from a durable matching intent."""
    if run.status not in ("running", "verifying"):
        return False
    sidecar = _sidecar_path(final)
    try:
        intent = _read_publication_intent(final)
    except PublicationError:
        return False
    expected_sha = manifest.get("expected_sha256") or manifest.get("authority_sha256")
    if intent is None or not _intent_matches_run(
        intent,
        run,
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        final=final,
        expected_sha=str(expected_sha or ""),
    ):
        return False
    if not _identity_matches(final, intent.get("staged_identity")):
        # Adoption requires the published inode to be exactly the staged
        # inode this attempt created; a foreign (even byte-equal) copy is
        # preserved and never adopted, receipted or completed.
        return False
    candidate = _intent_candidate_path(intent, manifest, run)
    if sidecar.is_symlink() or candidate is None or not candidate.is_file():
        return False
    try:
        actual_sha = _sha256_file(final)
        candidate_sha = _sha256_file(candidate)
        same_inode = os.path.samefile(candidate, final)
    except (OSError, UnicodeError):
        return False
    if same_inode or candidate_sha != actual_sha:
        return False
    if intent.get("candidate_sha256") != candidate_sha:
        return False
    if sidecar.exists():
        if not sidecar.is_file():
            return False
        try:
            stored_sha = sidecar.read_text(encoding="ascii").strip().lower()
        except (OSError, UnicodeError):
            return False
        if stored_sha != actual_sha:
            return False
    if expected_sha and str(expected_sha).lower() != actual_sha:
        return False
    _require_ready(session, workspace_id=workspace_id, project_id=project_id)
    _require_fence(repo, run_id, worker_id, fence_token)
    from app.services.s12_export.validation import validate  # noqa: PLC0415

    expectation = _expectation_for(run, manifest, candidate_sha=actual_sha)
    verdict = validate(final, expectation)
    if verdict.verdict != "PASS":
        return False
    try:
        if not sidecar.exists():
            _write_sidecar(final, actual_sha)
        _write_publication_receipt(
            final,
            _receipt_payload(
                run,
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                fence_token=fence_token,
                artifact_sha=actual_sha,
                verdict=verdict,
                artifact_identity=_file_identity(final),
            ),
        )
    except OSError:
        return False
    return True


def _replay_completed(repo: Any, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Replay after completion: re-verify the public artifact by bytes.

    The immutable byte identity lives in the sidecar written with the
    publication.  A missing artifact, a missing sidecar, a ``.partial``
    name, or a sha mismatch (tamper) all fail closed — a completed replay
    is never a bare status shortcut.
    """
    final = Path(str(manifest[_OUTPUT_PATH]))
    if final.is_symlink() or not final.is_file():
        raise PublicationError(
            f"completed run {run_id} has no public artifact; cannot replay"
        )
    if final.name.lower().endswith(".partial"):
        raise PublicationError(f"public artifact is partial for run {run_id}")
    sidecar = _sidecar_path(final)
    if sidecar.is_symlink() or not sidecar.is_file():
        raise PublicationError(
            f"completed run {run_id} has no byte-identity sidecar; cannot replay"
        )
    receipt = _publication_receipt_path(final)
    if receipt.is_symlink() or not receipt.is_file():
        raise PublicationError(
            f"completed run {run_id} has no trustworthy publication receipt; cannot replay"
        )
    try:
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as err:
        raise PublicationError(
            f"completed run {run_id} has an unreadable publication receipt"
        ) from err
    if not isinstance(receipt_payload, dict) or receipt_payload.get("run_id") != run_id:
        raise PublicationError(
            f"completed run {run_id} has a mismatched publication receipt"
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
    explicit = manifest.get(_CANDIDATE_PATH)
    candidate = Path(str(explicit)) if explicit else scratch / "candidate_final.mp4"
    try:
        if candidate.is_symlink():
            return None
        if candidate.resolve().parent != scratch.resolve():
            return None
    except OSError:
        return None
    return candidate


def _cleanup_publication_scratch(
    manifest: dict[str, Any],
    *,
    session: Any | None = None,
    run_id: str | None = None,
    worker_id: str | None = None,
    fence_token: str | None = None,
) -> None:
    """Clean private VAL scratch without touching an existing public file."""
    from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415
    from app.services.s12_export.runner import cleanup_owned_export_artifacts

    cleanup_owned_export_artifacts(
        scratch_dir=manifest.get(_SCRATCH_DIR),
        chunk_dir=manifest.get(_CHUNK_DIR),
        candidate_path=manifest.get(_CANDIDATE_PATH),
        repository=(
            S12ExportRepository(session)
            if session is not None
            else None
        ),
        owner_run_id=run_id,
        owner_worker_id=worker_id,
        owner_fence_token=fence_token,
    )


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


def _owner_is_live(repo: Any, run_id: str, worker_id: str, fence_token: str) -> bool:
    """Check DB ownership at cleanup time, bypassing stale ORM snapshots."""
    from datetime import UTC, datetime

    try:
        return bool(
            repo._lease_live_sql(  # noqa: SLF001
                run_id,
                worker_id,
                fence_token,
                now=datetime.now(UTC),
            )
        )
    except Exception:
        return False


def _require_fence(repo: Any, run_id: str, worker_id: str, fence_token: str) -> None:
    from datetime import UTC, datetime

    from app.persistence.s12_export import FencedWorkerError  # noqa: PLC0415

    try:
        live = repo._lease_live_sql(  # noqa: SLF001
            run_id,
            worker_id,
            fence_token,
            now=datetime.now(UTC),
        )
    except Exception as err:
        raise PublicationError(f"no live lease for run {run_id}: {err}") from err
    if not live:
        raise FencedWorkerError(
            f"fence mismatch for run {run_id}", run_id=run_id
        )


#: Documented per-profile PSNR content-identity thresholds (T03C-owned,
#: C26/interface-delta). The validator fails closed when the profile's
#: threshold is missing — never a silent default. 30 dB is the standard
#: "visually lossless" benchmark for x264 master renders; preview lowers
#: to 28 dB because smaller rasters tolerate less bit budget.
_PSNR_MIN_DB_BY_PROFILE: dict[str, float] = {
    "master-4k-h264": 30.0,
    "master-4k-hevc": 30.0,
    "preview-1080p-h264": 28.0,
}


def _expectation_for(run: Any, manifest: dict[str, Any], candidate_sha: str | None = None) -> Any:
    from app.services.s12_export.validation import (  # noqa: PLC0415
        MASTER_HEIGHT,
        MASTER_WIDTH,
        ValidationExpectation,
    )

    dims = str(getattr(run, "profile_dims", "") or "")
    width, height = _dims(dims)
    fps = float(manifest.get("fps") or 0)
    fps_num, fps_den = _fps_rational(fps, manifest)
    expected_sha = manifest.get("expected_sha256") or manifest.get("authority_sha256")
    source = _build_source_reference(manifest, fps_num, fps_den)
    match_mode, psnr_min_db = _frame_match(run, manifest, candidate_sha)
    # Output identity: the manifest authority sha when supplied; otherwise
    # the server-measured candidate sha (recorded output identity).  In
    # psnr mode the CONTENT authority is the approved artifact reference —
    # the sha is identity bookkeeping, never the content proof.
    if expected_sha:
        output_sha = str(expected_sha)
    elif candidate_sha and match_mode == "psnr":
        output_sha = candidate_sha
    else:
        output_sha = str(expected_sha or "")
    return ValidationExpectation(
        width=width or MASTER_WIDTH,
        height=height or MASTER_HEIGHT,
        codec=manifest.get("profile_codec") or run.profile_codec or "h264",
        expected_frame_count=int(manifest.get("frame_count") or 0) or None,
        expected_fps=fps or None,
        expected_sha256=output_sha or None,
        frame_match_mode=match_mode,
        frame_psnr_min_db=psnr_min_db,
        source_locked=True,
        source_reference=source,
        scratch_dir=str(manifest.get(_SCRATCH_DIR) or "") or None,
        cancel_flag=manifest.get("cancel_flag"),
    )


def _frame_match(
    run: Any, manifest: dict[str, Any], candidate_sha: str | None
) -> tuple[str, float | None]:
    """Select the content-order match mode (exact vs measured PSNR).

    - Identity copy: the candidate is byte-identical to the approved
      artifact (no re-encode) → ``exact`` per-frame digests.
    - Re-encode / upscale / full render: decoded content MUST be compared
      against the approved artifact with the documented per-profile PSNR
      threshold (fail-closed when the profile has no documented
      threshold).
    """
    source = str(manifest.get("source_path") or "")
    if (
        candidate_sha
        and source
        and Path(source).is_file()
        and _sha256_file(Path(source)) == candidate_sha
    ):
        return "exact", None
    profile_id = str(getattr(run, "profile_id", "") or "")
    threshold = _PSNR_MIN_DB_BY_PROFILE.get(profile_id)
    return "psnr", threshold


def _build_source_reference(
    manifest: dict[str, Any], fps_num: int, fps_den: int
) -> Any:
    """Server-owned source-locked reference from the CURRENT approved artifact.

    Probes the approved Full Apply artifact (the job's server-derived
    ``source_path``) with the T04A helpers — never the candidate:
    - per-frame decoded content digests at the approved raster;
    - approved audio evidence (``transcode`` when the artifact carries
      audio — the S12 assembly re-encodes audio via AAC per C28-F01;
      ``absent`` when silent);
    - approved artifact sha256 + exact fps rational + frame count.

    When the artifact is unreadable/absent (legacy manifest), the
    reference degrades to fps/frame/sha only — the T04A source-locked
    validator then answers NOT_MEASURED/FAIL explicitly instead of a
    fabricated PASS.
    """
    from app.services.s12_export.validation import (  # noqa: PLC0415
        AudioReference,
        SourceReference,
        probe_audio_digest,
        probe_audio_shape,
        probe_frame_digests,
    )

    frame_count = int(manifest.get("frame_count") or 0) or None
    expected_sha = manifest.get("expected_sha256") or manifest.get("authority_sha256")
    source = str(manifest.get("source_path") or "")
    digests: tuple[str, ...] = ()
    audio: Any = None
    reference_width: int | None = None
    reference_height: int | None = None
    if source and Path(source).is_file():
        dims = _probe_source_dims(source)
        if dims is not None:
            width, height = dims
            # Raster of the immutable approved artifact (F11-T06B-02): the
            # validator scale+pad's the reference to the candidate raster
            # with the product letterbox policy — same geometry the runner
            # produces, never stretch.
            reference_width, reference_height = width, height
            probed = probe_frame_digests(source, width, height)
            if probed:
                digests = probed
        # else: fail-closed — reference raster unknown stays None; the
        # validator then measures same-raster (a real cross-raster case
        # scores low PSNR and FAILs). Never a fabricated raster.
        audio_digest = probe_audio_digest(source, 0)
        if audio_digest is not None:
            shape = probe_audio_shape(source, 0)
            channels, sample_rate = shape if shape is not None else (None, None)
            # The assembly layer re-encodes audio (AAC).  Content is compared
            # against this immutable source with bounded vectorized windows;
            # digest equality remains reserved for remux/copy.
            audio = AudioReference(
                mode="transcode",
                stream_index=0,
                reference_path=source,
                channels=channels,
                sample_rate=sample_rate,
            )
        else:
            audio = AudioReference(mode="absent", stream_index=0)
    return SourceReference(
        artifact_sha256=str(expected_sha or ""),
        frame_count=frame_count,
        fps_num=fps_num if fps_num > 0 else 0,
        fps_den=fps_den if fps_den > 0 else 0,
        frame_digests=digests,
        audio=audio,
        reference_width=reference_width,
        reference_height=reference_height,
        # Immutable approved-artifact media path for measured PSNR mode
        # (server-derived; never client-supplied). Absent → PSNR fails
        # closed; exact mode never opens it.
        reference_path=source if (source and Path(source).is_file()) else None,
    )


def _probe_source_dims(path: str) -> tuple[int, int] | None:
    """Probe the approved artifact's video raster (ffprobe, read-only)."""
    import json  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    from app.services.s12_export.stitch import find_ffprobe  # noqa: PLC0415

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
                path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            return None
        stream = json.loads(completed.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError):
        return None


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


def _remove_unpublished_output(
    final: Path,
    *,
    expected_sha: str | None = None,
    remove_sidecar: bool = False,
    remove_receipt: bool = False,
) -> None:
    """Remove only this attempt's identity-matched unpublished files."""
    if expected_sha is not None:
        try:
            if _sha256_file(final) != expected_sha:
                return
        except OSError:
            return
    paths = [final]
    if remove_sidecar:
        paths.append(_sidecar_path(final))
    if remove_receipt:
        paths.append(_publication_receipt_path(final))
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
