"""Exclusive instance lease and server instance epoch.

`/interrupt` affects whatever the instance is currently executing. The adapter
sends it only when it holds an exclusive lease that proves the running prompt is
this attempt's prompt, so cancelling a foreign workflow is impossible by
construction (`COMFYUI_HUNYUAN_CONTROL.md`, C-A9).

The instance epoch is owned by the launcher: every server start mints a new
`instance_id`. If the epoch we submitted against is gone, history/queue results
cannot be attributed to our attempt and the attempt is unresolved — never
silently attributed and never resubmitted (C-A8).
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import LeaseConflict, LeaseNotHeld

STILL_ACTIVE = 259


def pid_alive(pid: int) -> bool:
    """Liveness of a process id without shelling out."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


class InstanceEpoch:
    """Immutable identity of one server launch, written by the launcher."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def read(self) -> dict | None:
        return _read_json(self.path)

    def write(self, base_url: str, comfyui_version: str = "", extra: dict | None = None) -> dict:
        rec = {
            "instance_id": uuid.uuid4().hex,
            "launched_at": time.time(),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "base_url": base_url,
            "comfyui_version": comfyui_version,
        }
        if extra:
            rec.update(extra)
        _write_json_atomic(self.path, rec)
        return rec

    def matches(self, expected: dict | None) -> bool:
        cur = self.read() or {}
        if not expected:
            return False
        return (
            cur.get("instance_id") == expected.get("instance_id")
            and cur.get("pid") == expected.get("pid")
            and pid_alive(int(cur.get("pid") or 0))
        )


class InstanceLease:
    """Exclusive lease over one ComfyUI instance; authorises `/interrupt`."""

    def __init__(
        self,
        lease_dir: str | os.PathLike[str],
        instance_id: str,
        owner: str,
        ttl_s: float = 3600.0,
    ) -> None:
        self.dir = Path(lease_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.instance_id = instance_id
        self.owner = owner
        self.ttl_s = ttl_s
        self.token = uuid.uuid4().hex
        self.path = self.dir / f"instance-{instance_id}.lease"

    # -- internal ---------------------------------------------------------
    def _own_record(self) -> dict | None:
        rec = _read_json(self.path)
        if rec and rec.get("token") == self.token and rec.get("owner") == self.owner:
            return rec
        return None

    # -- public -----------------------------------------------------------
    def read(self) -> dict | None:
        return _read_json(self.path)

    def acquire(self, attempt_id: str = "", prompt_id: str | None = None) -> dict:
        """Take the exclusive lease. Refuses while a live foreign holder exists."""
        rec = {
            "instance_id": self.instance_id,
            "attempt_id": attempt_id,
            "prompt_id": prompt_id,
            "owner": self.owner,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "token": self.token,
            "acquired_at": time.time(),
            "ttl_s": self.ttl_s,
        }
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                held = _read_json(self.path) or {}
                holder_alive = pid_alive(int(held.get("pid") or 0))
                age = time.time() - float(held.get("acquired_at") or 0.0)
                expired = age > float(held.get("ttl_s") or self.ttl_s)
                if holder_alive and not expired:
                    raise LeaseConflict(
                        "instance lease is held by another live attempt",
                        instance_id=self.instance_id,
                        holder=held,
                        our_pid=os.getpid(),
                    )
                # stale/reclaimable holder: only reclaim a provably dead or expired one
                self.path.unlink(missing_ok=True)
                continue
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(rec, fh, indent=1, sort_keys=True)
            except BaseException:
                self.path.unlink(missing_ok=True)
                raise
            return rec
        raise LeaseConflict("could not acquire instance lease", instance_id=self.instance_id)

    def set_prompt(self, prompt_id: str) -> dict:
        own = self._own_record()
        if own is None:
            raise LeaseNotHeld("cannot bind a prompt: lease not held by this attempt",
                               instance_id=self.instance_id, owner=self.owner)
        own["prompt_id"] = prompt_id
        own["bound_at"] = time.time()
        _write_json_atomic(self.path, own)
        return own

    def assert_held_for(self, prompt_id: str | None = None, epoch: dict | None = None) -> dict:
        own = self._own_record()
        if own is None:
            raise LeaseNotHeld("exclusive instance lease is not held by this attempt",
                               instance_id=self.instance_id, owner=self.owner)
        if epoch is not None and own.get("instance_id") != epoch.get("instance_id"):
            raise LeaseNotHeld("lease belongs to a different instance epoch",
                               lease_instance=own.get("instance_id"),
                               epoch_instance=epoch.get("instance_id"))
        if prompt_id is not None and own.get("prompt_id") != prompt_id:
            raise LeaseNotHeld("lease does not cover the requested prompt",
                               requested=prompt_id, leased=own.get("prompt_id"))
        if not pid_alive(int(own.get("pid") or 0)):
            raise LeaseNotHeld("lease holder process is no longer alive", holder_pid=own.get("pid"))
        return own

    def release(self) -> None:
        if self._own_record() is not None:
            self.path.unlink(missing_ok=True)

    @contextmanager
    def hold(self, attempt_id: str = "", prompt_id: str | None = None):
        self.acquire(attempt_id=attempt_id, prompt_id=prompt_id)
        try:
            yield self
        finally:
            self.release()
