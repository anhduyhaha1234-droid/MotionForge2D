"""Cross-process serialization of S12 export run ownership transitions (R7 F01).

The publication critical section — fence re-validation, exclusive public
create, companion writes and the fenced DB transitions — and the lease
claim transaction share ONE per-run advisory file lock.  Consequences:

- A claimant that arrives while a publication section is active waits a
  bounded time and then fails with :class:`PublicationInProgressError` and
  **zero mutation** (no lease write, no run revision change).
- A publisher that enters its section re-validates ownership first, so a
  claim that committed *before* the section is observed there and the
  publisher performs no public mutation.

This is what makes the last fence read atomic with the filesystem
mutation: the read is the section entry and no claim can interleave with
the section it guards (a further non-atomic fence read would not help).

The lock file is an empty coordination artifact; it is never read as
data.  Locks release automatically when the owning process dies.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.persistence.s12_export import S12ExportError

__all__ = [
    "DEFAULT_WAIT_SECONDS",
    "LEASE_GUARD_DIR_ENV",
    "LEASE_GUARD_WAIT_ENV",
    "PublicationInProgressError",
    "lease_guard_dir_for_db",
    "publication_lease_guard",
    "sqlite_db_path_from_session",
]

LEASE_GUARD_DIR_ENV = "S12_EXPORT_LEASE_GUARD_DIR"
LEASE_GUARD_WAIT_ENV = "S12_EXPORT_LEASE_GUARD_WAIT"
DEFAULT_WAIT_SECONDS = 45.0
_POLL_SECONDS = 0.05
_LOCK_SUFFIX = ".publication-lease.lock"


class PublicationInProgressError(S12ExportError):
    """A run ownership transition raced an active publication section.

    Fail-closed typed error: the claim performed **no** mutation and the
    caller may retry once the current owner's publication section ends.
    """

    code = "S12_T03C_PUBLICATION_IN_PROGRESS"

    def __init__(self, message: str, *, run_id: str = "") -> None:
        super().__init__(message)
        self.run_id = run_id


def sqlite_db_path_from_session(session: Any) -> Path | None:
    """Best-effort SQLite database path for the session's bind."""
    try:
        bind = session.get_bind()
    except Exception:  # noqa: BLE001 - best effort only
        return None
    url = getattr(bind, "url", None)
    database = getattr(url, "database", None)
    if not database:
        return None
    return Path(str(database))


def lease_guard_dir_for_db(db_path: Path | None) -> Path:
    """Directory holding the per-run publication lease locks."""
    override = os.environ.get(LEASE_GUARD_DIR_ENV)
    if override:
        return Path(override)
    if db_path is not None:
        return db_path.parent / "s12_export_lease_locks"
    return Path(tempfile.gettempdir()) / "s12_export_lease_locks"


def _wait_seconds() -> float:
    raw = os.environ.get(LEASE_GUARD_WAIT_ENV)
    if raw is None:
        return DEFAULT_WAIT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_WAIT_SECONDS
    return max(0.0, value)


def _acquire_native(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_native(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def publication_lease_guard(
    run_id: str,
    *,
    db_path: Path | None = None,
    wait_seconds: float | None = None,
) -> Iterator[Path]:
    """Hold the per-run publication lease lock (cross-process, bounded wait).

    Raises :class:`PublicationInProgressError` (without any mutation) when
    another owner keeps the lock past the bounded wait.
    """
    directory = lease_guard_dir_for_db(db_path)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / f"run-{run_id}{_LOCK_SUFFIX}"
    bound = wait_seconds if wait_seconds is not None else _wait_seconds()
    deadline = time.monotonic() + bound
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as err:
            raise PublicationInProgressError(
                f"publication lease lock is unavailable for run {run_id!r}: "
                f"{lock_path}",
                run_id=run_id,
            ) from err
        try:
            _acquire_native(fd)
        except OSError:
            os.close(fd)
            fd = None
            if time.monotonic() >= deadline:
                raise PublicationInProgressError(
                    f"publication in progress for run {run_id!r}: another "
                    f"owner holds the publication lease section ({lock_path})",
                    run_id=run_id,
                ) from None
            time.sleep(_POLL_SECONDS)
            continue
        break
    try:
        yield lock_path
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                _release_native(fd)
            with contextlib.suppress(OSError):
                os.close(fd)
