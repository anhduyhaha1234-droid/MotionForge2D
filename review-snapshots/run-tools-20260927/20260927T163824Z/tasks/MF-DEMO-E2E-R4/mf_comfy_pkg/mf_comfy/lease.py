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

import hashlib
import json
import os
import re
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import (
    AttemptAlreadyTerminal,
    CorruptReservation,
    LeaseConflict,
    LeaseNotHeld,
    ReservationConflict,
)

STILL_ACTIVE = 259

RESERVATION_SCHEMA = "mf.comfy.prompt_reservation/1"
RESERVATION_UNRESOLVED = "unresolved"
RESERVATION_RELEASED = "released"
RESERVATION_QUARANTINED = "quarantined"

# Durable submit lifecycle. `SUBMIT_INFLIGHT` is written *before* the transport
# POST is attempted, so "the server has no prompt for this client_id" is only
# ever proof that the POST never landed while the record still says
# `SUBMIT_OPENING` and its opener is provably gone. Anything else (inflight /
# acked / ambiguous / a pre-fix record with no state at all) means a POST may
# still be on the wire and the reservation must keep blocking.
SUBMIT_OPENING = "opening"
SUBMIT_INFLIGHT = "inflight"
SUBMIT_ACKED = "acked"
SUBMIT_AMBIGUOUS = "ambiguous"

# R28 (R27-6-F1): one receipt per (instance, attempt) slot is written once -- but
# a LEGAL never-submitted release may be SUPERSEDED, at most once, by the
# terminal outcome of the retry it authorised. Without that transition the
# release consumed the slot, the retry's validated result could not be recorded
# and every later replay was refused for an attempt that had in fact completed.
# The predecessor shape is deliberately narrow: a release whose own durable
# fields prove no POST ever started.
SUPERSEDABLE_OUTCOME = "not_accepted"
TRANSITION_LOCK_SUFFIX = ".transition.lock"


def receipt_is_legal_predecessor(prev: dict | None, incoming: dict | None) -> tuple[bool, str]:
    """May the terminal receipt `incoming` replace the recorded receipt `prev`?

    Legal ONLY for the never-submitted release of the SAME work item on the SAME
    server boot, whose recorded fields themselves prove that no POST started
    (`not_accepted`, no `prompt_id`, `submit_count == 0`), replaced by a receipt
    that carries the prompt of the retry that followed it. A release that was
    superseded once may never be superseded again, and a receipt that records a
    POST (any prompt id) is a finished attempt: it is never overwritten.
    """
    prev = prev if isinstance(prev, dict) else {}
    inc = incoming if isinstance(incoming, dict) else {}
    if prev.get("state") != RESERVATION_RELEASED:
        return False, f"the recorded state is {prev.get('state')!r}, not a release"
    if prev.get("outcome") != SUPERSEDABLE_OUTCOME:
        return False, (f"the receipt records the outcome {prev.get('outcome')!r}; only a "
                       f"never-submitted release ({SUPERSEDABLE_OUTCOME!r}) may be superseded")
    if prev.get("prompt_id"):
        return False, ("the receipt already carries a prompt "
                       f"({prev.get('prompt_id')!r}): a POST did start")
    if int(prev.get("submit_count") or 0) != 0:
        return False, f"the receipt records submit_count {prev.get('submit_count')!r}"
    if prev.get("superseded_by") or prev.get("transitions"):
        return False, "the receipt was already superseded once"
    if not str(inc.get("prompt_id") or ""):
        return False, "the incoming record carries no prompt: it cannot prove a POST"
    for field in ("instance_id", "host", *DURABLE_IDENTITY_FIELDS):
        if str(prev.get(field) or "") != str(inc.get(field) or ""):
            return False, (f"{field} differs: recorded {prev.get(field)!r} vs incoming "
                           f"{inc.get(field)!r}")
    return True, ""


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


def submit_provably_never_started(record: dict | None) -> bool:
    """True only when the durable record PROVES no POST was ever attempted.

    `mark_submit_inflight` writes `submit_state=inflight` before the transport
    POST, so:
      * `opening` + the opener is not a live process on this host -> the POST was
        never attempted: absent from `/queue` + `/history` really is proof;
      * anything else (`inflight`, `acked`, `ambiguous`, or a legacy record with
        no state) -> a POST may be on the wire; absence is NOT proof.
    """
    rec = record or {}
    if rec.get("submit_state") != SUBMIT_OPENING:
        return False
    host = rec.get("submit_owner_host") or rec.get("host")
    if not host or host != socket.gethostname():
        return True  # another host: we cannot prove its process is gone
    try:
        pid = int(rec.get("submit_owner_pid") or 0)
    except (TypeError, ValueError):
        return True
    if pid <= 0 or pid == os.getpid():
        return True  # unknown or ourselves: not provable
    return not pid_alive(pid)


# Required authority fields. A durable record that does not carry them cannot be
# attributed to an instance, an attempt or a work item at all: it is UNKNOWN
# state and every decision about it must fail closed (round C, Codex finding
# `lease.py:536`: a marker without `instance_id` used to be read as "another
# boot's record", get quarantined, and licence a fresh POST).
MARKER_AUTHORITY_FIELDS = ("schema", "state", "key", "instance_id", "host", "attempt_id")
RECEIPT_AUTHORITY_FIELDS = ("schema", "state", "key", "instance_id", "host", "attempt_id",
                            "outcome")

# The durable identity of one work item. `adapter._identity_matches` compares all
# of these on BOTH sides; no subset may ever be used to adopt or to refuse.
DURABLE_IDENTITY_FIELDS = ("attempt_id", "stage_id", "workflow_id", "workflow_sha256",
                           "owner", "input_digest", "output_contract_digest")


def canonical_digest(payload) -> str:
    """Stable digest of a durable payload (canonical JSON, sorted keys).

    The single implementation used by the ledger AND by the adapter, so a body
    written by one side can always be re-hashed by the other.
    """
    blob = json.dumps(payload if payload is not None else {}, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def authority_problems(record: dict | None, fields) -> list[str]:
    """Authority fields that are absent, blank or not a string."""
    rec = record if isinstance(record, dict) else {}
    out: list[str] = []
    for name in fields:
        value = rec.get(name)
        if not isinstance(value, str) or not value.strip():
            out.append(name)
    return out


def body_digest_problems(record: dict | None, body_field: str, digest_field: str) -> list[str]:
    """Body <-> digest integrity of one durable field pair.

    Neither half may exist without the other, and a body must hash to the digest
    recorded next to it. This is what stops a mutated body (a contract re-pointed
    from output node 9 to 10, an input identity rewritten) from being validated
    against its own stale digest.
    """
    rec = record if isinstance(record, dict) else {}
    body = rec.get(body_field)
    digest = rec.get(digest_field)
    has_body = bool(body)
    has_digest = isinstance(digest, str) and bool(digest.strip())
    if has_body and not has_digest:
        return [f"{body_field} is recorded without {digest_field}"]
    if has_digest and not has_body:
        return [f"{digest_field} is recorded without {body_field}"]
    if not has_body and not has_digest:
        return []          # nothing recorded: consistent, just absent
    if canonical_digest(body) != digest.strip().lower():
        return [f"{body_field} does not hash to the recorded {digest_field}"]
    return []


def identity_integrity_problems(record: dict | None) -> list[str]:
    """Integrity of the durable identity carried by a marker or a receipt."""
    return (body_digest_problems(record, "input_identity", "input_digest")
            + body_digest_problems(record, "output_contract", "output_contract_digest"))


def name_body_problems(path, record: dict | None, suffix: str = "") -> list[str]:
    """The ledger file name encodes `<instance>__<attempt>`: the record may not
    disagree with the name it is stored under.

    A record whose file name claims one instance/attempt while its body claims
    another cannot be attributed at all — it is unknown state, not a foreign
    record that may be quarantined to unlock a new POST.
    """
    name = Path(path).name if path is not None else ""
    if not name:
        return []
    stem = name[: -len(suffix)] if suffix and name.endswith(suffix) else Path(name).stem
    if "__" not in stem:
        return []
    left, right = stem.split("__", 1)
    rec = record if isinstance(record, dict) else {}
    out: list[str] = []
    inst = rec.get("instance_id")
    if inst:
        sanitized = re.sub(r"[^0-9A-Za-z._-]", "_", str(inst))
        if left not in (str(inst), sanitized):
            out.append(f"instance_id {inst!r} disagrees with the file name {name!r}")
    attempt = rec.get("attempt_id")
    if attempt is not None:
        raw = str(attempt) if str(attempt) else "noattempt"
        sanitized = re.sub(r"[^0-9A-Za-z._-]", "_", raw)
        if right not in (raw, sanitized):
            out.append(f"attempt_id {attempt!r} disagrees with the file name {name!r}")
    return out


def receipt_problems(record: dict | None, path=None) -> list[str]:
    """Integrity of a completion receipt.

    A receipt is identity evidence for a finished attempt, so it is held to the
    same standard as a marker: authority fields, a positive `release_count`, a
    name that describes it, and a body that hashes to its own digest.
    """
    rec = record if isinstance(record, dict) else {}
    out = [f"missing authority field {f}" for f in authority_problems(rec, RECEIPT_AUTHORITY_FIELDS)]
    count = rec.get("release_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        out.append("release_count is not a positive integer")
    if path is not None:
        out += name_body_problems(path, rec, ".released.json")
    out += identity_integrity_problems(rec)
    return out


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

    R28 (R27-6-F1): the exclusive create also meant the ONE receipt of a slot
    was consumed by the release that authorised a retry, so the retry's own
    terminal outcome could never be recorded. `close(..., attempt_supersession=
    True)` therefore allows exactly ONE legal replacement: the terminal receipt
    of the retry supersedes the release that provably never submitted. Every
    other second write is still refused and the recorded bytes are kept.
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
        workflow_id: str = "",
        workflow_sha256: str = "",
        input_digest: str = "",
        input_identity: dict | None = None,
        output_contract: dict | None = None,
        output_contract_digest: str = "",
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
            # durable identity: adoption must match all of it (F02)
            "workflow_id": workflow_id,
            "workflow_sha256": workflow_sha256,
            "input_digest": input_digest,
            "input_identity": input_identity or {},
            # durable NORMALIZED output contract bound before the POST (F05):
            # the declaration used for the first submit governs every later read
            "output_contract": output_contract or {},
            "output_contract_digest": output_contract_digest,
            # durable submit lifecycle (F01)
            "submit_state": SUBMIT_OPENING,
            "submit_owner_pid": os.getpid(),
            "submit_owner_host": socket.gethostname(),
            "submit_started_at": None,
            "submit_settled_at": None,
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
            "submit_state": SUBMIT_ACKED,
            "submit_settled_at": time.time(),
            "bound_at": time.time(),
        })
        _write_json_atomic(path, rec)
        return {**rec, "path": str(path)}

    def _patch(self, record: dict, changes: dict) -> dict:
        """Bounded update of one existing marker.

        Never invents a record that is not on disk: if the marker vanished or is
        unreadable the update is skipped and reported, so a caller can never
        silently re-create or rewrite somebody else's evidence.
        """
        path = Path(record.get("path") or self.path_for(
            str(record.get("instance_id") or ""), str(record.get("attempt_id") or "")))
        cur = _read_json(path)
        if not isinstance(cur, dict):
            return {**record, "patch_skipped": "marker missing or unreadable"}
        cur.update(changes)
        _write_json_atomic(path, cur)
        return {**cur, "path": str(path)}

    def mark_submit_inflight(self, record: dict) -> dict:
        """Durable "a POST is going on the wire", written BEFORE the POST call.

        This is what makes an empty `/queue` + `/history` non-proof: a later
        caller that finds `inflight` knows a prompt may still land and must leave
        the reservation unresolved and blocking.
        """
        return self._patch(record, {
            "submit_state": SUBMIT_INFLIGHT,
            "submit_started_at": time.time(),
            "submit_owner_pid": os.getpid(),
            "submit_owner_host": socket.gethostname(),
        })

    def mark_submit_settled(self, record: dict, state: str = SUBMIT_AMBIGUOUS) -> dict:
        """The POST returned or raised: record how it ended."""
        return self._patch(record, {
            "submit_state": state,
            "submit_settled_at": time.time(),
        })

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
              closer: str = "", attempt_supersession: bool = False) -> dict:
        """Release a reservation exactly once. Never releases an unproven one.

        The receipt is not just a ledger note: it is the durable record that
        identity resolution reads on the next attempt, so it carries the whole
        durable identity of the work item (attempt / stage / workflow / graph /
        input / owner / normalized output contract) plus whatever validated
        evidence the caller supplies. `Round C (lease.py:555)`: without those
        fields a completed attempt could not be reconciled with a replay at all.
        """
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
            # -- durable work-item identity (so a replay can be reconciled) -----
            "base_url": record.get("base_url") or "",
            "server_pid": record.get("server_pid"),
            "client_id": record.get("client_id") or "",
            "stage_id": record.get("stage_id") or "",
            "owner": record.get("owner") or "",
            "workflow_id": record.get("workflow_id") or "",
            "workflow_sha256": record.get("workflow_sha256") or "",
            "input_digest": record.get("input_digest") or "",
            "input_identity": record.get("input_identity") or {},
            "output_contract": record.get("output_contract") or {},
            "output_contract_digest": record.get("output_contract_digest") or "",
            "submit_state": record.get("submit_state"),
            "submit_count": record.get("submit_count"),
        }
        if attempt_supersession:
            transition = self._supersede_receipt(receipt, payload, closer=closer)
            if transition is not None:
                Path(record["path"]).unlink(missing_ok=True)
                return transition

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

    def _take_transition_lock(self, lock: Path, wait_s: float = 5.0) -> bool:
        """Claim the single-slot transition lock, bounded.

        Exactly one closer may perform the release->terminal transition of one
        (instance, attempt) slot. The loser of that race does not guess: it waits
        (bounded) for the winner to publish, then re-reads the receipt and is
        refused by the ordinary legality check, which keeps the winner's bytes.
        """
        deadline = time.time() + max(0.0, float(wait_s))
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if time.time() >= deadline:
                    return False
                time.sleep(0.01)
                continue
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(f"{os.getpid()}\n")
            except BaseException:
                lock.unlink(missing_ok=True)
                raise
            return True

    def _supersede_receipt(self, receipt: Path, payload: dict, *,
                           closer: str = "") -> dict | None:
        """Replace a never-submitted release with the terminal receipt of its retry.

        Returns None when there is nothing to supersede yet (no receipt on disk),
        or when the incoming close cannot prove a POST -- those keep the original
        one-write-per-slot behaviour. Every unsafe replacement is refused with an
        EXISTING typed error (`AttemptAlreadyTerminal` / `ReservationConflict` /
        `CorruptReservation` / `LeaseConflict`) and moves not a single byte.
        """
        if not receipt.exists():
            return None
        if not str(payload.get("prompt_id") or ""):
            return None
        lock = receipt.with_name(receipt.name + TRANSITION_LOCK_SUFFIX)
        held = self._take_transition_lock(lock)
        try:
            if not held:
                raise LeaseConflict(
                    "refusing to replace this attempt's receipt: another closer is "
                    "performing the transition of this slot right now",
                    supersession=True, refusal="transition_in_progress",
                    receipt=str(receipt))
            prev = _read_json(receipt)
            if prev is None:
                raise CorruptReservation(
                    "refusing to replace a receipt that exists but cannot be read; "
                    "unknown state is never overwritten",
                    supersession=True, refusal="unreadable_receipt", receipt=str(receipt),
                    incoming_outcome=payload.get("outcome"),
                    incoming_prompt_id=payload.get("prompt_id"))
            # Idempotent re-close of the SAME terminal fact (same outcome, same
            # prompt, same durable identity): there is nothing to replace, and
            # `close()` must stay exactly-once. Only a DIFFERENT record for this
            # slot reaches the supersession rules below.
            same_identity = all(
                str(prev.get(field) or "") == str(payload.get(field) or "")
                for field in ("instance_id", "host", *DURABLE_IDENTITY_FIELDS))
            if (same_identity
                    and str(prev.get("outcome") or "") == str(payload.get("outcome") or "")
                    and str(prev.get("prompt_id") or "")
                    == str(payload.get("prompt_id") or "")):
                return {"released": False, "already_released": True,
                        "release_count": int(prev.get("release_count") or 1),
                        "outcome": prev.get("outcome"), "closed_path": str(receipt),
                        "transitioned": False, "already_recorded": True,
                        "marker_removed": True}
            ok, reason = receipt_is_legal_predecessor(prev, payload)
            if not ok:
                identity_mismatch = " differs:" in reason
                error = (ReservationConflict if identity_mismatch else AttemptAlreadyTerminal)
                raise error(
                    f"refusing to replace this attempt's receipt: {reason}",
                    supersession=True, refusal=reason, receipt=str(receipt),
                    recorded_outcome=prev.get("outcome"),
                    recorded_prompt_id=prev.get("prompt_id"),
                    recorded_submit_count=prev.get("submit_count"),
                    recorded_release_count=prev.get("release_count"),
                    incoming_outcome=payload.get("outcome"),
                    incoming_prompt_id=payload.get("prompt_id"))
            history = list(prev.get("transitions") or [])
            history.append({
                "from_outcome": prev.get("outcome"), "to_outcome": payload.get("outcome"),
                "at": time.time(), "by": closer or payload.get("closer"),
                "from_prompt_id": prev.get("prompt_id"),
                "to_prompt_id": payload.get("prompt_id"),
                "reason": "legal release->retry transition: the release proved no POST "
                          "started and the retry recorded the terminal outcome",
            })
            replaced = dict(payload)
            # The slot was released exactly once and stays released exactly once.
            replaced["release_count"] = 1
            replaced["supersedes"] = {
                "outcome": prev.get("outcome"), "closed_at": prev.get("closed_at"),
                "closer": prev.get("closer"), "submit_count": prev.get("submit_count"),
                "prompt_id": prev.get("prompt_id"),
                "close_evidence": prev.get("close_evidence") or {},
            }
            replaced["transitions"] = history
            replaced["superseded_by"] = payload.get("prompt_id")
            _write_json_atomic(receipt, replaced)
            return {"released": True, "already_released": False, "release_count": 1,
                    "transitioned": True, "previous_outcome": prev.get("outcome"),
                    "outcome": payload.get("outcome"), "closed_path": str(receipt),
                    "transitions": len(history), "marker_removed": True}
        finally:
            if held:
                lock.unlink(missing_ok=True)

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

    def unreadable(self) -> list[dict]:
        """Markers that exist but cannot be read as a reservation record.

        A malformed marker is neither "no reservation" nor evidence of anybody
        else's prompt: it is UNKNOWN state, and unknown state must fail closed.
        The file is never deleted or rewritten here -- it stays as evidence for
        whoever has to repair it.
        """
        out: list[dict] = []
        for p in sorted(self.root.glob(f"*{self.SUFFIX}")):
            try:
                raw = p.read_text(encoding="utf-8")
            except OSError as exc:
                out.append({"path": str(p), "reason": f"{type(exc).__name__}:{exc}",
                            "size": None})
                continue
            try:
                rec = json.loads(raw)
            except ValueError as exc:
                out.append({"path": str(p), "reason": f"unparsable JSON: {exc}",
                            "size": len(raw.encode("utf-8"))})
                continue
            if not isinstance(rec, dict) or not rec.get("key") or not rec.get("attempt_id"):
                out.append({"path": str(p), "reason": "not a reservation record",
                            "size": len(raw.encode("utf-8")),
                            "parsed_keys": sorted(rec)[:12] if isinstance(rec, dict) else None})
                continue
            # Round C: a record also has to describe ITSELF — authority fields and
            # a body that hashes to the digest recorded next to it. Without that it
            # cannot even be attributed to a boot, so "another boot's record ->
            # quarantine -> POST again" is off the table. (A record stored under a
            # NAME that describes another instance/attempt is handled separately by
            # the adapter: it is a competing claimant, refused as a conflict.)
            problems = [f"missing authority field {f}"
                        for f in authority_problems(rec, MARKER_AUTHORITY_FIELDS)]
            problems += identity_integrity_problems(rec)
            if problems:
                out.append({"path": str(p), "reason": "; ".join(problems),
                            "size": len(raw.encode("utf-8")),
                            "parsed_keys": sorted(rec)[:12],
                            "recorded_instance_id": rec.get("instance_id"),
                            "recorded_attempt_id": rec.get("attempt_id")})
        return out

    def unreadable_receipts(self) -> list[dict]:
        """Receipts that exist but cannot be read as a completion record.

        Same rule as an unreadable marker: unknown state fails closed. A receipt
        is the ONLY record that an attempt already finished, so silently skipping
        an unreadable one would licence exactly the second POST this round is
        about. Nothing is repaired or deleted here — the bytes stay as evidence.
        """
        out: list[dict] = []
        if not self.closed_dir.exists():
            return out
        for p in sorted(self.closed_dir.glob("*.released.json")):
            try:
                raw = p.read_text(encoding="utf-8")
            except OSError as exc:
                out.append({"path": str(p), "reason": f"{type(exc).__name__}:{exc}",
                            "size": None})
                continue
            try:
                rec = json.loads(raw)
            except ValueError as exc:
                out.append({"path": str(p), "reason": f"unparsable JSON: {exc}",
                            "size": len(raw.encode("utf-8"))})
                continue
            if not isinstance(rec, dict):
                out.append({"path": str(p), "reason": "not a receipt record",
                            "size": len(raw.encode("utf-8"))})
                continue
            problems = receipt_problems(rec, p)
            if problems:
                out.append({"path": str(p), "reason": "; ".join(problems),
                            "size": len(raw.encode("utf-8")),
                            "parsed_keys": sorted(rec)[:12],
                            "recorded_instance_id": rec.get("instance_id"),
                            "recorded_attempt_id": rec.get("attempt_id")})
        return out

    def unreadable_quarantines(self) -> list[dict]:
        """Quarantine records that exist but carry no usable authority.

        Round D (NR02): a quarantine record is durable state ABOUT an attempt that
        could not be reconciled, so it can never be read as "nothing was
        quarantined". Bytes that do not parse, or that do not say which
        instance/attempt they describe, are UNKNOWN state: they fail the attempt
        closed instead of silently disappearing from the candidate union and
        licensing a new POST. Nothing is repaired or deleted here -- the bytes stay
        as evidence for whoever has to repair them.
        """
        out: list[dict] = []
        for p in sorted(self.root.glob("*.quarantined.json")):
            try:
                raw = p.read_text(encoding="utf-8")
            except OSError as exc:
                out.append({"path": str(p), "reason": f"{type(exc).__name__}:{exc}",
                            "size": None})
                continue
            try:
                rec = json.loads(raw)
            except ValueError as exc:
                out.append({"path": str(p), "reason": f"unparsable JSON: {exc}",
                            "size": len(raw.encode("utf-8"))})
                continue
            if not isinstance(rec, dict) or not rec.get("key") or not rec.get("attempt_id"):
                out.append({"path": str(p), "reason": "not a quarantine record",
                            "size": len(raw.encode("utf-8")),
                            "parsed_keys": sorted(rec)[:12] if isinstance(rec, dict) else None})
                continue
            problems = [f"missing authority field {f}"
                        for f in authority_problems(rec, MARKER_AUTHORITY_FIELDS)]
            problems += identity_integrity_problems(rec)
            problems += name_body_problems(p, rec, ".quarantined.json")
            if problems:
                out.append({"path": str(p), "reason": "; ".join(problems),
                            "size": len(raw.encode("utf-8")),
                            "parsed_keys": sorted(rec)[:12],
                            "recorded_instance_id": rec.get("instance_id"),
                            "recorded_attempt_id": rec.get("attempt_id")})
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
