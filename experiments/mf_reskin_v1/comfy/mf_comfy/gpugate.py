"""Machine-wide gate: one heavy GPU stage at a time.

The RTX 5070 has 12,227 MiB. `COMFYUI_HUNYUAN_CONTROL.md` requires a single heavy
inference stage at a time on this card. The gate is a cross-process exclusive
byte lock so a second concurrent attempt is refused (typed `GpuStageBusy`)
instead of queueing a second model onto the same GPU.

Windows uses `msvcrt.locking(LK_NBLCK)`; other platforms fall back to `fcntl`.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import GpuStageBusy


class GpuStageGate:
    def __init__(
        self,
        lock_path: str | os.PathLike[str],
        timeout_s: float = 0.0,
        poll_s: float = 0.5,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # The byte lock spans the whole lock file, so a contender cannot read a
        # record stored inside it. Holder info therefore lives in a sibling file
        # that is only ever read, never locked.
        self.holder_path = self.lock_path.with_name(self.lock_path.name + ".holder.json")
        self.timeout_s = float(timeout_s)
        self.poll_s = float(poll_s)
        self.token = uuid.uuid4().hex
        self._fh = None

    # -- low level --------------------------------------------------------
    def _try_lock(self, fh) -> bool:
        if os.name == "nt":
            import msvcrt

            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl

        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(self, fh) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    # -- public -----------------------------------------------------------
    def acquire(self, stage_label: str = "", heavy: bool = True) -> dict:
        """Take the heavy-stage lock. Raises GpuStageBusy on timeout."""
        fh = open(self.lock_path, "a+", encoding="utf-8")
        record = {
            "token": self.token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "stage_label": stage_label,
            "heavy": bool(heavy),
            "acquired_at": time.time(),
        }
        deadline = time.monotonic() + self.timeout_s
        while True:
            if self._try_lock(fh):
                fh.seek(0)
                fh.truncate()
                fh.flush()
                os.fsync(fh.fileno())
                tmp = self.holder_path.with_name(self.holder_path.name + f".tmp{os.getpid()}")
                with open(tmp, "w", encoding="utf-8", newline="\n") as hf:
                    json.dump(record, hf, sort_keys=True)
                os.replace(tmp, self.holder_path)
                self._fh = fh
                return record
            holder = None
            try:
                holder = json.loads(self.holder_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                holder = None
            if time.monotonic() >= deadline:
                fh.close()
                raise GpuStageBusy(
                    "another heavy GPU stage holds the machine-wide gate",
                    lock_path=str(self.lock_path),
                    holder=holder,
                    waited_s=self.timeout_s,
                    requested_by=record,
                )
            time.sleep(self.poll_s)

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            self._unlock(self._fh)
            self._fh.close()
            try:
                held = json.loads(self.holder_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            if held.get("token") == self.token:
                self.holder_path.unlink(missing_ok=True)
        finally:
            self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    @contextmanager
    def heavy_stage(self, stage_label: str = ""):
        self.acquire(stage_label=stage_label, heavy=True)
        try:
            yield self
        finally:
            self.release()
