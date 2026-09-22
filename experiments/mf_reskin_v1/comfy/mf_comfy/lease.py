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
import re
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import LeaseConflict, LeaseNotHeld

STILL_ACTIVE = 259

RESERVATION_SCHEMA = "mf.comfy.prompt_reservation/1"
RESERVATION_UNRESOLVED = "unresolved"
RESERVATION_RELEASED = "released"
RESERVATION_QUARANTINED = "quarantined"


def same_boot_identity(a: dict | None, b: dict | None) -> bool:
    """Boot identity of a server launch = `instance_id` + `host`.

    A bare pid is deliberately NOT identity: Windows reuses pids, so a pid that
    happens to be alive proves nothing about which launch it belongs to. `pid`
    stays a secondary liveness hint only (`pid_alive`), never the identity.
    """
    if not a or not b:
        return False
    return (a.get("instance_id") == b.get("instance_id")
            and a.get("host") == b.get("host"))


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


class PromptReservations:
    """Durable ledger of prompts whose outcome is not (yet) provable.

    Why this exists: a prompt that is still in `/queue` is occupying the server
    even after our wait timed out. Returning `unresolved` while dropping the
    lease + GPU gate lets a second stage start its own work on a GPU whose
    server is still executing prompt #1.

    The ledger is one file per reservation:

      * unresolved  -> `<root>/<key>.reservation.json`  (marker PRESENT)
      * quarantined -> `<root>/<key>.quarantined.json`  (marker ABSENT)
      * released    -> `<root>/closed/<key>.released.json` (marker ABSENT)

    "still unresolved" and "provably gone" are therefore filesystem facts, not
    process memory: they survive a crash and are readable by a later process.
    Release claims the receipt with `O_CREAT|O_EXCL`, so a reservation can be
    released exactly once even if two processes race — the loser gets
    `already_released` and never writes a second release.
    """

    SUFFIX = ".reservation.json"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.closed_dir = self.root / "closed"

    # -- keys -------------------------------------------------------------
    @staticmethod
    def key_for(instance_id: str, attempt_id: str) -> str:
        raw = f"{instance_id}__{attempt_id or 'noattempt'}"
        return re.sub(r"[^0-9A-Za-z._-]", "_", raw)

    def path_for(self, instance_id: str, attempt_id: str) -> Path:
        return self.root / (self.key_for(instance_id, attempt_id) + self.SUFFIX)

    # -- write ------------------------------------------------------------
    def open(
        self,
        instance_epoch: dict,
        attempt_id: str,
        *,
        stage_id: str = "",
        owner: str = "",
        client_id: str = "",
        prompt_id: str | None = None,
        note: str = "",
    ) -> dict:
        """Reserve this instance for one attempt BEFORE the POST is attempted.

        Opening before the POST is what makes a lost acknowledgement safe: the
        reservation is already durable when the transport raises, so a later
        attempt can find the prompt instead of submitting a second one.
        """
        instance_id = str((instance_epoch or {}).get("instance_id") or "")
        path = self.path_for(instance_id, attempt_id)
        existing = _read_json(path)
        if existing:
            return {**existing, "path": str(path), "created": False}
        rec = {
            "schema": RESERVATION_SCHEMA,
            "state": RESERVATION_UNRESOLVED,
            "key": self.key_for(instance_id, attempt_id),
            "instance_id": instance_id,
            "host": (instance_epoch or {}).get("host") or socket.gethostname(),
            "base_url": (instance_epoch or {}).get("base_url") or "",
            "server_pid": (instance_epoch or {}).get("pid"),
            "attempt_id": attempt_id,
            "stage_id": stage_id,
            "owner": owner,
            "client_id": client_id,
            "prompt_id": prompt_id,
            "submit_count": 0,
            "opened_at": time.time(),
            "note": note,
        }
        _write_json_atomic(path, rec)
        return {**rec, "path": str(path), "created": True}

    def bind(self, instance_epoch: dict, attempt_id: str, prompt_id: str,
             *, submit_count: int = 1) -> dict:
        """Record the prompt id the server acknowledged, still unresolved."""
        instance_id = str((instance_epoch or {}).get("instance_id") or "")
        path = self.path_for(instance_id, attempt_id)
        rec = _read_json(path)
        if rec is None:
            rec = {
                "schema": RESERVATION_SCHEMA,
                "key": self.key_for(instance_id, attempt_id),
                "instance_id": instance_id,
                "host": (instance_epoch or {}).get("host") or socket.gethostname(),
                "base_url": (instance_epoch or {}).get("base_url") or "",
                "server_pid": (instance_epoch or {}).get("pid"),
                "attempt_id": attempt_id,
                "stage_id": "", "owner": "", "client_id": "",
                "opened_at": time.time(),
            }
        rec.update({
            "state": RESERVATION_UNRESOLVED,
            "prompt_id": prompt_id,
            "submit_count": submit_count,
            "bound_at": time.time(),
        })
        _write_json_atomic(path, rec)
        return {**rec, "path": str(path)}

    def quarantine(self, record: dict, reason: str, evidence: dict | None = None,
                   *, closer: str = "") -> dict:
        """Move a reservation out of the blocking set because it can never be
        attributed to us (server restarted: different boot identity)."""
        src = Path(record["path"])
        if not src.exists():
            return {"quarantined": False, "already_closed": True, "reason": reason}
        payload = {k: v for k, v in record.items() if k != "path"}
        payload.update({
            "state": RESERVATION_QUARANTINED,
            "quarantine_reason": reason,
            "quarantined_at": time.time(),
            "quarantine_evidence": evidence or {},
            "closer": closer,
        })
        dst = self.root / f"{record['key']}.quarantined.json"
        _write_json_atomic(dst, payload)
        src.unlink(missing_ok=True)
        return {"quarantined": True, "already_closed": False, "reason": reason, "path": str(dst)}

    def close(self, record: dict, outcome: str, *, evidence: dict | None = None,
              closer: str = "") -> dict:
        """Release a reservation exactly once. Never releases an unproven one."""
        key = record["key"]
        self.closed_dir.mkdir(parents=True, exist_ok=True)
        receipt = self.closed_dir / f"{key}.released.json"
        payload = {
            "schema": RESERVATION_SCHEMA,
            "state": RESERVATION_RELEASED,
            "key": key,
            "instance_id": record.get("instance_id"),
            "host": record.get("host"),
            "attempt_id": record.get("attempt_id"),
            "prompt_id": record.get("prompt_id"),
            "outcome": outcome,
            "release_count": 1,
            "closed_at": time.time(),
            "closer": closer,
            "close_evidence": evidence or {},
        }
        try:
            fd = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            prev = _read_json(receipt) or {}
            # a crash may have left the marker behind after the claim: the marker
            # is not authority, the receipt is.
            Path(record["path"]).unlink(missing_ok=True)
            return {
                "released": False, "already_released": True,
                "release_count": int(prev.get("release_count") or 1),
                "outcome": prev.get("outcome"),
                "closed_path": str(receipt),
                "marker_removed": True,
            }
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(payload, fh, indent=1, sort_keys=True)
        finally:
            Path(record["path"]).unlink(missing_ok=True)
        return {
            "released": True, "already_released": False, "release_count": 1,
            "outcome": outcome, "closed_path": str(receipt),
        }

    # -- read -------------------------------------------------------------
    def read(self, instance_id: str, attempt_id: str) -> dict | None:
        rec = _read_json(self.path_for(instance_id, attempt_id))
        if rec is None:
            return None
        return {**rec, "path": str(self.path_for(instance_id, attempt_id))}

    def unresolved(self, instance_id: str | None = None) -> list[dict]:
        """Every reservation whose marker is still on disk (i.e. unresolved)."""
        out: list[dict] = []
        for p in sorted(self.root.glob(f"*{self.SUFFIX}")):
            rec = _read_json(p)
            if not rec:
                continue
            if instance_id is not None and rec.get("instance_id") != instance_id:
                continue
            out.append({**rec, "path": str(p)})
        return out

    def quarantined(self, instance_id: str | None = None) -> list[dict]:
        out: list[dict] = []
        for p in sorted(self.root.glob("*.quarantined.json")):
            rec = _read_json(p)
            if not rec:
                continue
            if instance_id is not None and rec.get("instance_id") != instance_id:
                continue
            out.append({**rec, "path": str(p)})
        return out

    def receipts(self) -> list[dict]:
        if not self.closed_dir.exists():
            return []
        out: list[dict] = []
        for p in sorted(self.closed_dir.glob("*.released.json")):
            rec = _read_json(p)
            if rec:
                out.append({**rec, "path": str(p)})
        return out

    def is_unresolved(self, instance_id: str, attempt_id: str) -> bool:
        return self.path_for(instance_id, attempt_id).exists()
