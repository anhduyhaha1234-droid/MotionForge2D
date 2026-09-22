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

from .errors import GpuStageBusy, UnresolvedReservation
from .lease import InstanceEpoch, PromptReservations


class GpuStageGate:
    """Cross-process exclusive heavy-stage lock + unresolved-reservation guard.

    The byte lock alone is not enough. A lock dies with the process that holds
    it, so a prompt that is still executing on the server after our wait timed
    out would look "free" to the next stage. `acquire` therefore also consults
    the durable `PromptReservations` ledger for the instance epoch: while an
    unresolved reservation exists, acquisition is refused with
    `UnresolvedReservation` unless the caller supplies a `reconcile` callback
    that proves a terminal outcome first.

    The ledger + epoch locations default to the conventional task-local layout
    (`<lock dir>/instance_epoch.json` + `<lock dir>/reservations`, or one level
    up), so a gate built from the same lock path — even by another process or
    another task — sees the same state without extra wiring.
    """

    def __init__(
        self,
        lock_path: str | os.PathLike[str],
        timeout_s: float = 0.0,
        poll_s: float = 0.5,
        *,
        epoch_path: str | os.PathLike[str] | None = None,
        reservations: object | None = None,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # The byte lock spans the whole lock file, so a contender cannot read a
        # record stored inside it. Holder info therefore lives in a sibling file
        # that is only ever read, never locked.
        self.holder_path = self.lock_path.with_name(self.lock_path.name + ".holder.json")
        state_dir = self._resolve_state_dir()
        self.epoch_path = (Path(epoch_path) if epoch_path is not None
                           else state_dir / "instance_epoch.json")
        if reservations is False:
            self.reservations = None
        elif reservations is None:
            self.reservations = PromptReservations(state_dir / "reservations")
        else:
            self.reservations = reservations
        self.timeout_s = float(timeout_s)
        self.poll_s = float(poll_s)
        self.token = uuid.uuid4().hex
        self._fh = None
        # guard evidence (raw numbers, never a summary)
        self.guard_refusals = 0
        self.guard_actions: list[dict] = []

    def _resolve_state_dir(self) -> Path:
        """Where the epoch + reservation ledger for this lock live."""
        base = self.lock_path.parent
        candidates = [base]
        if base.parent != base:
            candidates.append(base.parent)
        for candidate in candidates:
            if (candidate / "instance_epoch.json").exists() or (candidate / "reservations").exists():
                return candidate
        return base

    # -- unresolved-reservation guard --------------------------------------
    def _epoch_now(self, epoch: dict | None) -> dict | None:
        if epoch:
            return epoch
        try:
            return InstanceEpoch(self.epoch_path).read()
        except OSError:
            return None

    def blocking_reservations(self, epoch: dict | None = None, reconcile=None,
                              skip_key: str | None = None) -> list[dict]:
        """Reservations that still forbid taking the gate for this instance.

        `reconcile(record) -> str` may prove an outcome for a foreign
        reservation. Only a *provable* outcome closes it:
          completed / not_accepted -> released (exactly once)
          epoch_lost / epoch_mismatch -> quarantined (never adopted as ours)
          anything else / missing callback -> still blocking

        `skip_key` is the reservation this very attempt is taking over (the
        adopting attempt continues the same job, so its own reservation must not
        block it).
        """
        if self.reservations is None:
            return []
        inst = (self._epoch_now(epoch) or {}).get("instance_id")
        if not inst:
            return []
        records = [r for r in self.reservations.unresolved(inst) if r.get("key") != skip_key]
        if not records or reconcile is None:
            return records
        still: list[dict] = []
        for rec in records:
            try:
                outcome = reconcile(rec)
            except Exception as exc:  # noqa: BLE001 - an unprovable reconcile blocks
                outcome = f"unproven:{type(exc).__name__}"
            if outcome in ("completed", "reconcile_completed", "not_accepted"):
                res = self.reservations.close(rec, outcome=outcome, closer="gate-guard",
                                              evidence={"reconciled_by": "gate-guard"})
                self.guard_actions.append({"action": "release", "prompt_id": rec.get("prompt_id"),
                                           "outcome": outcome, "result": res})
            elif outcome in ("epoch_lost", "epoch_mismatch"):
                res = self.reservations.quarantine(rec, outcome, closer="gate-guard")
                self.guard_actions.append({"action": "quarantine", "prompt_id": rec.get("prompt_id"),
                                           "outcome": outcome, "result": res})
            else:
                still.append({**rec, "reconcile_outcome": outcome})
        return still

    def _refuse(self, blocking: list[dict], requested_by: dict, detail: str):
        self.guard_refusals += 1
        raise UnresolvedReservation(
            "refused: an unresolved prompt reservation still owns this instance",
            lock_path=str(self.lock_path),
            detail=detail,
            holder=blocking[0] if len(blocking) == 1 else None,
            unresolved=[{k: r.get(k) for k in
                         ("instance_id", "attempt_id", "prompt_id", "stage_id", "opened_at",
                          "state", "path", "reconcile_outcome")} for r in blocking],
            unresolved_count=len(blocking),
            requested_by=requested_by,
        )

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
    def acquire(self, stage_label: str = "", heavy: bool = True, *,
                epoch: dict | None = None, reconcile=None,
                adopt_key: str | None = None) -> dict:
        """Take the heavy-stage lock. Raises GpuStageBusy or UnresolvedReservation.

        Order of refusal: an unresolved reservation for this instance epoch is
        checked *before* the byte lock and again *after* it is taken, so a
        reservation opened while we waited still blocks us. `adopt_key` names the
        reservation this attempt is taking over (it is excluded).
        """
        record = {
            "token": self.token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "stage_label": stage_label,
            "heavy": bool(heavy),
            "acquired_at": time.time(),
        }
        blocking = self.blocking_reservations(epoch, reconcile, skip_key=adopt_key)
        if blocking:
            self._refuse(blocking, record, "before-lock")
        fh = open(self.lock_path, "a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout_s
        while True:
            if self._try_lock(fh):
                blocking = self.blocking_reservations(epoch, reconcile, skip_key=adopt_key)
                if blocking:
                    self._unlock(fh)
                    fh.close()
                    self._refuse(blocking, record, "after-lock")
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
