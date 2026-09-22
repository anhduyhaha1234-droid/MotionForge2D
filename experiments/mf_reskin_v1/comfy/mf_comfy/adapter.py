"""The ComfyUI stage adapter: submit -> queue/history -> websocket -> validate -> contract.

Design rules enforced here (from `COMFYUI_HUNYUAN_CONTROL.md` + task packet):
  * exactly one prompt submission per attempt; no blind retry anywhere;
  * timeout after submit is ambiguous -> reconcile via queue/history/epoch, and
    if it stays unproven the attempt ends `unresolved` (never a second submit);
  * websocket loss is not job failure and is not completion authority;
  * completion authority is `/history/{prompt_id}`;
  * artifacts are re-materialised inside the stage root and hashed there;
  * `/interrupt` requires the exclusive instance lease for *this* prompt;
  * one heavy GPU stage at a time via the machine-wide gate.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import pinning
from .contract import StageInput, StageOutput
from .errors import (
    AmbiguousAfterSubmit,
    ArtifactHashMismatch,
    ArtifactMissing,
    BlindResubmitRefused,
    CorruptReservation,
    InvalidGraph,
    LeaseNotHeld,
    MfComfyError,
    MissingModel,
    MissingNode,
    PartialOutput,
    ReservationConflict,
    ServerEpochChanged,
    TransportError,
    WsDisconnected,
    classify_execution_message,
)
from .lease import PromptReservations, same_boot_identity, submit_provably_never_started
from .paths import StagePaths

ARTIFACT_KEYS = ("images", "gifs", "videos", "audio")
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".gif"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
_MISSING = object()

# A product is a terminal output the server itself wrote, which ComfyUI marks
# `type == "output"`. An `input` item is a preview of what we SENT and `temp` is
# a scratch preview: neither is a result. `RunSpec.allowed_types` can only
# NARROW this set, never widen it (F05).
PUBLISHABLE_SERVER_TYPES = ("output",)


@dataclass
class RunSpec:
    stage_id: str
    workflow_id: str
    graph: dict
    workflow_sha256: str = ""
    node_inventory_sha256: str = ""
    model_pins: dict = field(default_factory=dict)
    stage_timeout_s: float = 600.0
    poll_s: float = 1.0
    expected_artifact_hashes: dict = field(default_factory=dict)
    allowed_types: tuple = ("output",)
    # --- F02: durable identity of the work item. A previous attempt's prompt may
    #     only be adopted by the SAME declared identity; `owner` defaults to the
    #     adapter's owner when empty.
    attempt_id: str = ""
    owner: str = ""
    # --- F05: the declared terminal output(s) of this workflow,
    #     `{node_id: {"kind": "images", "media_type": "image", "server_types": ("output",)}}`.
    #     Only these nodes can publish a product. When empty the graph's own
    #     terminal nodes (ComfyUI `output_node: true`) are used.
    terminal_outputs: dict = field(default_factory=dict)


class ComfyStageAdapter:
    def __init__(
        self,
        transport,
        paths: StagePaths,
        lease=None,
        gate=None,
        epoch=None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        sampler=None,
        client_id: str | None = None,
        owner: str = "mf-comfy-worker",
        reservations=None,
    ) -> None:
        self.transport = transport
        self.paths = paths
        self.lease = lease
        self.gate = gate
        self.epoch = epoch          # InstanceEpoch reader/writer
        self.clock = clock
        self.sleep = sleep
        self.sampler = sampler
        self.client_id = client_id or uuid.uuid4().hex
        self.owner = owner
        # Durable unresolved-prompt ledger (see mf_comfy.lease.PromptReservations).
        # It must be the *same* ledger the gate consults, otherwise the gate
        # guard would look at a different directory than the one we write to:
        # the gate resolves `<instance state dir>/reservations`, and the epoch
        # file lives in exactly that directory, so derive from it.
        if reservations is False:
            reservations = None
        elif reservations is None:
            reservations = getattr(gate, "reservations", None) if gate is not None else None
            if reservations is None and epoch is not None:
                reservations = PromptReservations(Path(epoch.path).parent / "reservations")
            if reservations is None:
                reservations = PromptReservations(paths.root / "reservations")
        self.reservations = reservations
        # attempt bookkeeping / counters used as evidence
        self.submit_count = 0
        self.reconcile_count = 0
        self.interrupt_count = 0
        self.interrupt_refusals = 0
        self.adopted_prompt_id: str | None = None
        self.reservation: dict | None = None
        self.reservation_released = False
        self.gate_acquired = False
        self.lease_acquired = False
        self.reservation_events: list[dict] = []
        self.ws_events: list[dict] = []
        self.notes: list[str] = []
        self.instance_epoch: dict | None = None
        self.capabilities: dict = {}
        self.node_inventory_sha256 = ""
        self.object_info: dict = {}

    # ---------------------------------------------------------------- preflight
    def preflight(self, graph: dict, node_inventory_sha256: str = "") -> dict:
        object_info = self.transport.object_info()
        # kept for the declared-terminal-output fallback (`output_node`)
        self.object_info = object_info
        inv_sha = pinning.verify_node_inventory_pin(object_info, node_inventory_sha256)
        self.node_inventory_sha256 = inv_sha
        self.capabilities = self.transport.probe_capabilities(object_info)
        self._validate_graph(object_info, graph)
        return {
            "node_inventory_sha256": inv_sha,
            "node_class_count": len(object_info or {}),
            "capabilities": self.capabilities,
            "workflow_sha256": pinning.hash_workflow(graph),
        }

    def _validate_graph(self, object_info: dict, graph: dict) -> None:
        if not isinstance(graph, dict) or not graph:
            raise InvalidGraph("workflow graph is empty or not an object")
        classes = []
        for node_id, node in graph.items():
            if not isinstance(node, dict) or "class_type" not in node:
                raise InvalidGraph("node is missing class_type", node_id=node_id)
            classes.append(node["class_type"])
        missing = pinning.inventory_missing_classes(object_info, classes)
        if missing:
            raise MissingNode(
                "workflow references node classes the server does not expose",
                missing_classes=missing,
            )
        for node_id, node in graph.items():
            spec = object_info.get(node["class_type"]) or {}
            required = ((spec.get("input") or {}).get("required") or {})
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise InvalidGraph("node has no inputs object", node_id=node_id,
                                   class_type=node["class_type"])
            for name, spec_def in required.items():
                value = inputs.get(name, _MISSING)
                if value is _MISSING:
                    raise InvalidGraph("node is missing a required input", node_id=node_id,
                                       class_type=node["class_type"], input=name)
                options = None
                if isinstance(spec_def, list) and spec_def and isinstance(spec_def[0], list):
                    options = spec_def[0]
                if options is not None and isinstance(value, str) and value not in options:
                    raise MissingModel(
                        "input value is not available on this server",
                        node_id=node_id, class_type=node["class_type"], input=name,
                        value=value, sample_available=options[:25],
                    )
            for name, value in inputs.items():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    if value[0] not in graph:
                        raise InvalidGraph("node references an unknown upstream node",
                                           node_id=node_id, input=name, link=value)

    # ------------------------------------------------------------------ submit
    def submit(self, graph: dict) -> str:
        if self.submit_count >= 1:
            raise BlindResubmitRefused(
                "refusing a second prompt submission for this attempt",
                submit_count=self.submit_count,
            )
        self.submit_count += 1
        # Durable "a POST is going on the wire" BEFORE the call itself: while this
        # is on disk, an empty `/queue` + `/history` is NOT proof that the prompt
        # never landed, so no later caller may release or adopt this reservation by
        # absence (F01).
        if self.reservations is not None and self.reservation is not None:
            self.reservation = self.reservations.mark_submit_inflight(self.reservation)
        try:
            res = self.transport.submit(graph, self.client_id)
        except (MissingNode, MissingModel, InvalidGraph):
            # the server refused the graph outright: provably no prompt exists
            raise
        except TransportError as exc:
            # The POST may or may not have been accepted: unprovable -> ambiguous.
            self._settle_submit()
            raise AmbiguousAfterSubmit(
                "prompt submission outcome is unprovable (transport failed during POST)",
                submit_attempted=True, prompt_id=None, transport_error=exc.to_dict(),
            ) from exc
        except BaseException:
            # Any other failure of the POST is equally unprovable: stamp it as
            # ambiguous so no caller can ever release it as "never landed".
            self._settle_submit()
            raise
        if self.lease is not None:
            try:
                self.lease.set_prompt(res.prompt_id)
            except MfComfyError as exc:
                self.notes.append(f"lease binding skipped: {exc.to_dict()}")
        return res.prompt_id

    # -------------------------------------------------------------------- wait
    def _settle_submit(self) -> None:
        """Stamp the reservation as "the POST ended, outcome unknown" (F01)."""
        if self.reservations is not None and self.reservation is not None:
            self.reservation = self.reservations.mark_submit_settled(self.reservation)

    def _history_entry(self, prompt_id: str) -> dict:
        """Completion authority.

        Verified against the pinned commit `306af3a8` (v0.28.2): `/history/{id}`
        answers directly with `{prompt_id: entry}`. The transport exposes
        `capabilities["history_direct_endpoint"]` so a build that only serves the
        full `/history` map can be handled without guessing here.
        """
        hist = self.transport.history(prompt_id) or {}
        entry = hist.get(prompt_id)
        if entry:
            return entry
        direct = (self.capabilities or {}).get("history_direct_endpoint", True)
        if not direct:
            full = self.transport.history("") or {}
            return full.get(prompt_id) or {}
        return {}

    def _track_event(self, event: dict) -> None:
        self.ws_events.append(
            {"t": round(self.clock(), 3), "type": event.get("type"),
             "data": event.get("data") if event.get("type") != "progress" else event.get("data")}
        )

    def wait_for_terminal(self, prompt_id: str, stage_timeout_s: float, poll_s: float,
                          exec_begin_ref: list) -> dict:
        deadline = self.clock() + stage_timeout_s
        while self.clock() < deadline:
            try:
                events = self.transport.drain_events(self.client_id, poll_s)
            except WsDisconnected as exc:
                self.notes.append(f"ws disconnect (not a failure): {exc.to_dict()}")
                events = []
            for ev in events:
                if ev.get("type") == "execution_start" and not exec_begin_ref:
                    exec_begin_ref.append(self.clock())
                self._track_event(ev)
            try:
                entry = self._history_entry(prompt_id)
            except TransportError as exc:
                self.notes.append(f"history poll failed (will retry/reconcile): {exc.to_dict()}")
                entry = {}
            if entry:
                # Identity FIRST: a success entry recorded by another launch of the
                # server is foreign output, never this attempt's result (F03).
                self._assert_epoch_unchanged(prompt_id, what="while waiting for the prompt")
                return entry
            self._assert_epoch_unchanged(prompt_id, what="while waiting for the prompt")
        return {}

    def _assert_epoch_unchanged(self, prompt_id: str, *, what: str) -> None:
        """Re-check the boot identity immediately before anything is accepted (F03)."""
        if self.instance_epoch is None or self.epoch is None:
            return
        if not self.epoch.matches(self.instance_epoch):
            raise ServerEpochChanged(
                f"server instance epoch changed {what}",
                instance_epoch=self.instance_epoch, observed_epoch=self.epoch.read(),
                prompt_id=prompt_id,
            )

    # -------------------------------------------------------------- reconcile
    @staticmethod
    def _queue_ids(item) -> list[str]:
        """String ids carried by one `/queue` item.

        The pinned server returns `[number, prompt_id, prompt, extra_data, outputs]`,
        so the prompt id is at index 1; simplest fakes put it at index 0. Both are
        accepted, and only string slots are considered so the integer queue number
        can never be mistaken for an id.
        """
        if not isinstance(item, (list, tuple)):
            return []
        return [x for x in list(item)[:2] if isinstance(x, str)]

    def reconcile(self, prompt_id: str) -> str:
        """Prove the outcome of an ambiguous wait. Never submits anything."""
        self.reconcile_count += 1
        try:
            q = self.transport.queue() or {}
        except TransportError as exc:
            self.notes.append(f"queue read failed during reconcile: {exc.to_dict()}")
            q = {}
        for bucket in ("queue_running", "queue_pending"):
            for item in q.get(bucket) or []:
                if prompt_id in self._queue_ids(item):
                    return "queued"
        # Boot identity BEFORE the history read: a success entry from another
        # launch of the server must land as `epoch_lost`, never as `completed` (F03).
        if self.instance_epoch is not None and self.epoch is not None:
            if not self.epoch.matches(self.instance_epoch):
                return "epoch_lost"
        try:
            if self._history_entry(prompt_id):
                return "completed"
        except TransportError as exc:
            self.notes.append(f"history read failed during reconcile: {exc.to_dict()}")
        return "unproven"

    # ------------------------------------------------- durable reservation
    @staticmethod
    def _input_identity(stage_input: StageInput | None) -> dict:
        """Source identity of a stage input: no paths, no volatile fields."""
        si = stage_input
        if si is None:
            return {}
        return {
            "project_id": getattr(si, "project_id", "") or "",
            "job_id": getattr(si, "job_id", "") or "",
            "shot_id": getattr(si, "shot_id", "") or "",
            "source_sha256": getattr(si, "source_sha256", "") or "",
            "source_frame_range": list(getattr(si, "source_frame_range", None) or []),
            "reference_assets": dict(getattr(si, "reference_assets", None) or {}),
        }

    @staticmethod
    def identity_digest(identity: dict) -> str:
        """Stable digest of an input identity (canonical JSON, sorted keys)."""
        blob = json.dumps(identity or {}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _claim(self, spec: RunSpec, stage_input: StageInput | None, attempt_id: str) -> dict:
        """The declared identity of the work item this attempt is claiming (F02)."""
        identity = self._input_identity(stage_input)
        return {
            "attempt_id": attempt_id or "",
            "stage_id": spec.stage_id or "",
            "workflow_id": spec.workflow_id or "",
            "workflow_sha256": spec.workflow_sha256 or pinning.hash_workflow(spec.graph),
            "owner": spec.owner or self.owner,
            "input_digest": self.identity_digest(identity),
            "input_identity": identity,
        }

    @staticmethod
    def _identity_matches(record: dict, claim: dict) -> bool:
        """Adoption is legal only for the exact declared work item (F02).

        Every field must be present on BOTH sides and equal: a record written by
        a build without identity, or by another attempt/stage/workflow/graph/
        input/owner, can never be adopted. It stays unresolved and blocking
        instead of being handed to a stranger.
        """
        for key in ("attempt_id", "stage_id", "workflow_id", "workflow_sha256",
                    "owner", "input_digest"):
            mine = str((claim or {}).get(key) or "")
            theirs = str((record or {}).get(key) or "")
            if not mine or not theirs or mine != theirs:
                return False
        return True

    def _scan_server_for_own_prompt(self, client_id: str) -> tuple[tuple[str, str] | None, bool]:
        """Find a prompt THIS client already submitted. Returns (found, reads_ok).

        `reads_ok` is False when a queue/history read failed, i.e. absence is not
        proven. Absence is only ever treated as proof when both reads worked.
        """
        if not client_id:
            return None, False
        reads_ok = True
        try:
            q = self.transport.queue() or {}
        except TransportError as exc:
            self.notes.append(f"queue read failed during adoption scan: {exc.to_dict()}")
            q, reads_ok = {}, False
        for bucket in ("queue_running", "queue_pending"):
            for item in q.get(bucket) or []:
                ids = self._queue_ids(item)
                if not ids:
                    continue
                extra = {}
                for idx in (3, 2):
                    if isinstance(item, (list, tuple)) and len(item) > idx and isinstance(item[idx], dict):
                        extra = item[idx]
                        break
                if extra.get("client_id") == client_id:
                    return ("queue", ids[0]), reads_ok
        try:
            full = self.transport.history("") or {}
        except TransportError as exc:
            self.notes.append(f"history read failed during adoption scan: {exc.to_dict()}")
            full, reads_ok = {}, False
        for prompt_id, entry in full.items():
            extra = {}
            if isinstance(entry, dict):
                info = entry.get("prompt")
                if isinstance(info, (list, tuple)) and len(info) > 3 and isinstance(info[3], dict):
                    extra = info[3]
                elif isinstance(entry.get("extra_data"), dict):
                    extra = entry["extra_data"]
            if extra.get("client_id") == client_id:
                return ("history", str(prompt_id)), reads_ok
        return None, reads_ok

    def _record_event(self, action: str, detail: dict) -> None:
        self.reservation_events.append({"action": action, "at": self.clock(), **detail})

    def adopt_pending(self, instance_epoch: dict | None = None,
                      claim: dict | None = None) -> dict | None:
        """Adopt a prompt this server boot already owns — never a second POST.

        Order:
          1. an unreadable marker is unknown state and fails the attempt closed
             before anything else (F04);
          2. a reservation of a *different* boot of this same server can never be
             adopted -> quarantined (its output is foreign output);
          3. a reservation of this boot is adopted only when its DURABLE IDENTITY
             (attempt / stage / workflow / graph / input / owner) equals the claim
             (F02); several claimants for one identity fail closed, never a coin
             flip;
          4. an unbound matching reservation is resolved by searching /queue +
             /history for the client_id that opened it. Only a record that PROVES
             the POST never started may be released as `not_accepted`; anything
             else stays unresolved and blocking (F01).
        """
        if self.reservations is None:
            return None
        corrupt = self.reservations.unreadable()
        if corrupt:
            raise CorruptReservation(
                "refusing to work on an instance whose reservation ledger holds "
                "unreadable markers",
                corrupt_count=len(corrupt), corrupt=corrupt)
        epoch = (instance_epoch or self.instance_epoch
                 or (self.epoch.read() if self.epoch else None) or {})
        inst = epoch.get("instance_id")
        # 1) foreign boot identity on the same server
        for rec in self.reservations.unresolved():
            if rec.get("instance_id") == inst:
                continue
            if rec.get("base_url") and epoch.get("base_url") and rec.get("base_url") != epoch.get("base_url"):
                continue
            if rec.get("host") != epoch.get("host"):
                continue
            res = self.reservations.quarantine(
                rec, "server_epoch_changed", closer=self.owner,
                evidence={"recorded_instance_id": rec.get("instance_id"),
                          "observed_instance_id": inst,
                          "recorded_host": rec.get("host"), "observed_host": epoch.get("host"),
                          "observed_pid": epoch.get("pid")})
            self._record_event("quarantine_foreign_epoch", {"prompt_id": rec.get("prompt_id"), "result": res})
        # 2) this boot's own unresolved reservations, bound by durable identity
        mine = [r for r in self.reservations.unresolved(inst)
                if self._identity_matches(r, claim or {})]
        if len(mine) > 1:
            raise ReservationConflict(
                "several reservations claim the same work item identity; refusing to choose",
                attempt_id=(claim or {}).get("attempt_id"),
                keys=[r.get("key") for r in mine],
                paths=[r.get("path") for r in mine],
            )
        if not mine:
            self._record_event("no_identity_match", {
                "claim": {k: (claim or {}).get(k) for k in
                          ("attempt_id", "stage_id", "workflow_id", "workflow_sha256", "owner")},
                "unresolved_for_this_boot": len(self.reservations.unresolved(inst)),
                "note": "a reservation of another work item stays unresolved and keeps "
                        "blocking the gate for this instance"})
            return None
        rec = mine[0]
        if rec.get("prompt_id"):
            self.reservation = rec
            self.adopted_prompt_id = rec["prompt_id"]
            self._record_event("adopted_bound_prompt", {"prompt_id": rec["prompt_id"]})
            return rec
        found, reads_ok = self._scan_server_for_own_prompt(rec.get("client_id", ""))
        if found:
            kind, prompt_id = found
            bound = self.reservations.bind(epoch, rec["attempt_id"], prompt_id, submit_count=0)
            self.reservation = bound
            self.adopted_prompt_id = prompt_id
            self._record_event("adopted_after_lost_ack",
                               {"prompt_id": prompt_id, "found_in": kind, "submit_count": 0})
            return bound
        if reads_ok and same_boot_identity(epoch, rec) and submit_provably_never_started(rec):
            res = self.reservations.close(
                rec, "not_accepted", closer=self.owner,
                evidence={"reason": "queue and history carry no prompt for this client_id AND the "
                                    "record proves the POST never started (submit_state=opening "
                                    "with a provably gone opener), so the POST never landed",
                          "client_id": rec.get("client_id"),
                          "submit_state": rec.get("submit_state"),
                          "submit_owner_pid": rec.get("submit_owner_pid")})
            self._record_event("released_not_accepted", {"result": res})
            return None
        # absence is NOT proof: keep it, and keep blocking
        self._record_event("kept_unproven", {
            "prompt_id": rec.get("prompt_id"), "reads_ok": reads_ok,
            "submit_state": rec.get("submit_state"),
            "reason": "a POST may have been on the wire; absence from /queue + /history "
                      "is not proof that it never landed"})
        return None

    def close_reservation(self, outcome: str, evidence: dict | None = None,
                          closer: str | None = None) -> dict:
        """Release this attempt's reservation exactly once (idempotent)."""
        if self.reservations is None or self.reservation is None:
            return {"released": False, "already_released": False, "reason": "no_reservation"}
        res = self.reservations.close(self.reservation, outcome,
                                      evidence=evidence or {}, closer=closer or self.owner)
        if res.get("released") or res.get("already_released"):
            self.reservation_released = True
        self._record_event("close", {"outcome": outcome, "result": res})
        return res

    def reservation_state(self) -> dict:
        if self.reservations is None or self.reservation is None:
            return {"exists": False, "released": self.reservation_released}
        key = self.reservation["key"]
        marker = Path(self.reservation["path"])
        cur = self.reservations.read(self.reservation["instance_id"], self.reservation["attempt_id"])
        return {
            "exists": marker.exists(),
            "released": self.reservation_released,
            "key": key,
            "marker_path": str(marker),
            "prompt_id": (cur or self.reservation).get("prompt_id"),
            "instance_id": (cur or self.reservation).get("instance_id"),
            "record": cur,
        }

    def gate_reconcile_hook(self, record: dict) -> str:
        """Prove (or fail to prove) a foreign reservation's outcome for the gate.

        This is the callback the gate guard uses: a later stage may take the GPU
        only once the earlier prompt reaches a provable terminal outcome.
        """
        pid = record.get("prompt_id")
        if not pid:
            found, reads_ok = self._scan_server_for_own_prompt(record.get("client_id", ""))
            if found:
                return "queued"
            # Absence only closes the record when it PROVES no POST ever started;
            # otherwise the gate keeps it blocking (F01).
            if reads_ok and submit_provably_never_started(record):
                return "not_accepted"
            return "unproven"
        return self.reconcile(pid)

    def _release_hold(self) -> None:
        if self.lease is not None:
            self.lease.release()
            self.lease_acquired = False
        if self.gate_acquired and self.gate is not None:
            self.gate.release()
            self.gate_acquired = False

    # --------------------------------------------------------------- validate
    def _decode_check(self, path: Path, raw: bytes) -> tuple[bool | None, int | None, int | None, str]:
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            try:
                from PIL import Image

                with Image.open(path) as img:
                    img.load()
                    return True, img.width, img.height, ""
            except Exception as exc:  # noqa: BLE001 - any decode problem means unvalidated
                return False, None, None, f"{type(exc).__name__}:{exc}"
        if suffix in VIDEO_SUFFIXES:
            try:
                import av

                with av.open(str(path)) as container:
                    frames = 0
                    for _ in container.decode(video=0):
                        frames += 1
                        break
                    if frames == 0:
                        return False, None, None, "no decodable video frame"
                    stream = container.streams.video[0] if container.streams.video else None
                    width = getattr(stream, "width", None)
                    height = getattr(stream, "height", None)
                    return True, width, height, ""
            except ImportError:
                return None, None, None, "av not installed: video decode not verified"
            except Exception as exc:  # noqa: BLE001
                return False, None, None, f"{type(exc).__name__}:{exc}"
        return None, None, None, "unknown artifact type: decode not verified"

    def _declared_terminal_outputs(self, spec: RunSpec) -> dict:
        """The terminal output node(s) of this workflow (F05).

        `RunSpec.terminal_outputs` is the declaration; when it is empty the
        graph's own terminal nodes are used (ComfyUI marks them
        `output_node: true`, e.g. SaveImage / SaveAnimatedWEBP).
        """
        declared: dict[str, dict] = {}
        for node_id, conf in (spec.terminal_outputs or {}).items():
            declared[str(node_id)] = dict(conf or {})
        if declared:
            return declared
        object_info = self.object_info or {}
        for node_id, node in (spec.graph or {}).items():
            cls = (node or {}).get("class_type")
            if (object_info.get(cls) or {}).get("output_node"):
                declared[str(node_id)] = {}
        return declared

    @staticmethod
    def _declared_server_types(conf: dict, spec: RunSpec) -> tuple:
        """Publishable server types for one declared node.

        A product is what the server WROTE (`type == "output"`). `allowed_types`
        may only narrow that set: it can never make an `input` preview or a
        `temp` scratch file into a result (F05).
        """
        want = tuple(conf.get("server_types") or spec.allowed_types or PUBLISHABLE_SERVER_TYPES)
        return tuple(t for t in want if t in PUBLISHABLE_SERVER_TYPES)

    def validate_artifacts(self, entry: dict, spec: RunSpec) -> list[dict]:
        outputs = entry.get("outputs") or {}
        declared = self._declared_terminal_outputs(spec)
        if not declared:
            raise ArtifactMissing(
                "workflow declares no terminal output node, so nothing can be published",
                prompt_id=entry.get("prompt_id"), outputs_keys=list(outputs),
                terminal_outputs=dict(spec.terminal_outputs or {}))
        candidates: list[tuple[str, str, dict, dict]] = []
        ignored: list[dict] = []
        for node_id, node_out in outputs.items():
            node_id = str(node_id)
            conf = declared.get(node_id)
            if conf is None:
                for key in ARTIFACT_KEYS:
                    for item in (node_out.get(key) or []):
                        ignored.append({"node_id": node_id, "kind": key,
                                        "type": item.get("type", "output"),
                                        "filename": item.get("filename", ""),
                                        "why": "node is not a declared terminal output"})
                continue
            for key in ARTIFACT_KEYS:
                for item in (node_out.get(key) or []):
                    if conf.get("kind") and key != conf["kind"]:
                        raise ArtifactMissing(
                            "declared terminal node published a different media kind",
                            node_id=node_id, expected_kind=conf.get("kind"),
                            actual_kind=key, item=item)
                    candidates.append((node_id, key, item, conf))
        if not candidates:
            raise ArtifactMissing(
                "history entry carries no artifact on a declared terminal output node",
                prompt_id=entry.get("prompt_id"), declared_nodes=sorted(declared),
                outputs_keys=list(outputs), ignored=ignored)
        artifacts: list[dict] = []
        for node_id, key, item, conf in candidates:
            filename = item.get("filename", "")
            subfolder = item.get("subfolder", "")
            atype = item.get("type", "output")
            allowed = self._declared_server_types(conf, spec)
            if atype not in allowed:
                # An input preview or temp preview is not a product: ignore it and
                # let the typed "nothing publishable" failure below decide.
                ignored.append({"node_id": node_id, "kind": key, "type": atype,
                                "filename": filename,
                                "why": "algorithm type is not publishable",
                                "allowed_types": list(allowed)})
                continue
            media = conf.get("media_type")
            suffix = Path(filename).suffix.lower()
            if media == "image" and suffix not in IMAGE_SUFFIXES:
                raise ArtifactMissing("declared terminal node published a non-image "
                                      "artifact", node_id=node_id, item=item,
                                      declared_media_type=media)
            if media == "video" and suffix not in VIDEO_SUFFIXES:
                raise ArtifactMissing("declared terminal node published a non-video "
                                      "artifact", node_id=node_id, item=item,
                                      declared_media_type=media)
            if filename.endswith(".partial"):
                raise PartialOutput("server produced a .partial artifact", item=item)
            target = self.paths.resolve(filename, subfolder)   # raises PathScopeViolation
            raw = self.transport.fetch_view(item)
            if not raw:
                raise PartialOutput("artifact fetch returned zero bytes", item=item)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(raw)
            sha = pinning.sha256_file(target)
            expected = (spec.expected_artifact_hashes or {}).get(filename)
            if expected and expected != sha:
                raise ArtifactHashMismatch("artifact hash differs from the recorded expectation",
                                           filename=filename, expected=expected, actual=sha)
            decode_ok, width, height, decode_note = self._decode_check(target, raw)
            if decode_ok is False:
                raise PartialOutput("artifact did not fully decode", item=item, note=decode_note)
            artifacts.append({
                "node_id": node_id, "kind": key, "filename": filename, "subfolder": subfolder,
                "server_type": atype, "staged_path": str(target), "sha256": sha,
                "size_bytes": len(raw), "width": width, "height": height,
                "decode_verified": decode_ok, "decode_note": decode_note,
            })
        if not artifacts:
            raise ArtifactMissing(
                "no publishable artifact on any declared terminal output node",
                prompt_id=entry.get("prompt_id"), declared_nodes=sorted(declared),
                ignored=ignored)
        return artifacts

    # -------------------------------------------------------------- interrupt
    def interrupt(self, prompt_id: str) -> dict:
        """`/interrupt` is only legal while holding the exclusive lease for this prompt."""
        if self.lease is None:
            self.interrupt_refusals += 1
            raise LeaseNotHeld("no lease manager configured; interrupt refused")
        try:
            self.lease.assert_held_for(prompt_id=prompt_id, epoch=self.instance_epoch)
        except MfComfyError:
            self.interrupt_refusals += 1
            raise
        self.interrupt_count += 1
        return self.transport.interrupt(prompt_id)

    def cancel(self, prompt_id: str, wait_terminal_s: float = 0.0,
               poll_s: float = 1.0) -> dict:
        """Cancel a prompt we provably own, then release the reservation once.

        The interrupt is still lease-gated (a foreign prompt is never touched).
        The reservation is only released when the server history proves the
        prompt reached a terminal state — otherwise it stays unresolved.
        `wait_terminal_s` waits (bounded) for the server to record the terminal
        entry after the real `/interrupt`; it never retries the interrupt.
        """
        self.interrupt(prompt_id)
        deadline = self.clock() + float(wait_terminal_s)
        entry: dict = {}
        while True:
            entry = self._history_entry(prompt_id)
            if entry or self.clock() >= deadline:
                break
            self.sleep(poll_s)
        outcome = self.reconcile(prompt_id)
        closed = None
        if entry:
            closed = self.close_reservation("cancelled",
                                            evidence={"interrupt": True, "reconcile_outcome": outcome,
                                                      "terminal_status": ((entry.get("status") or {})
                                                                          .get("status_str"))})
            self._release_hold()
        return {
            "prompt_id": prompt_id,
            "interrupt_count": self.interrupt_count,
            "reconcile_outcome": outcome,
            "terminal_proven": bool(entry),
            "waited_terminal_s": float(wait_terminal_s),
            "close": closed,
            "reservation_released": self.reservation_released,
            "reservation": self.reservation_state(),
        }

    # ------------------------------------------------------------------- run
    def run(self, spec: RunSpec, stage_input: StageInput | None = None) -> StageOutput:
        stage_input = stage_input or StageInput(stage_id=spec.stage_id, staging_root=str(self.paths.root))
        # Declared identity of this work item: adoption (and only adoption) is
        # bound to it, so a stranger can never receive this prompt's output (F02).
        attempt_id = (stage_input.attempt_id or spec.attempt_id or "").strip()
        if not attempt_id:
            attempt_id = f"attempt-{uuid.uuid4().hex[:12]}"
        claim = self._claim(spec, stage_input, attempt_id)
        t_start = self.clock()
        timing: dict[str, Any] = {}
        instance_epoch = self.instance_epoch or (self.epoch.read() if self.epoch else None)
        base = StageOutput(
            status="failed", stage_id=spec.stage_id, workflow_id=spec.workflow_id,
            instance_epoch=instance_epoch or {},
        )
        terminal_proven = False
        try:
            pre = self.preflight(spec.graph, spec.node_inventory_sha256)
            timing["preflight_s"] = round(self.clock() - t_start, 3)
            base.workflow_sha256 = pre["workflow_sha256"]
            base.node_inventory_sha256 = pre["node_inventory_sha256"]
            base.model_hashes = dict(spec.model_pins)

            # F01 fix, step 1: does THIS work item already own a prompt? Answer
            # BEFORE taking the gate, so the adopting attempt can take over its own
            # reservation instead of POSTing a second prompt. Adoption is bound to
            # the declared identity, and a reservation of another work item is left
            # unresolved (it keeps blocking the gate below).
            adopted = self.adopt_pending(instance_epoch, claim)
            adopt_key = self.reservation.get("key") if (adopted and self.reservation) else None

            if self.gate is not None:
                # epoch + reconcile callback: while any OTHER unresolved
                # reservation owns this server boot the gate refuses, and only a
                # provable terminal outcome clears one.
                self.gate.acquire(stage_label=spec.stage_id, epoch=instance_epoch,
                                  reconcile=self.gate_reconcile_hook, adopt_key=adopt_key)
                self.gate_acquired = True
            if self.lease is not None:
                self.lease.acquire(attempt_id=stage_input.attempt_id, prompt_id=None)
                self.lease_acquired = True

            if adopted is not None and adopted.get("prompt_id"):
                prompt_id = adopted["prompt_id"]
                base.adopted = True
                if self.lease is not None:
                    # the adopted prompt IS ours, so the lease must cover it —
                    # otherwise `/interrupt` would (correctly) refuse later.
                    try:
                        self.lease.set_prompt(prompt_id)
                    except MfComfyError as exc:
                        self.notes.append(f"lease binding after adoption skipped: {exc.to_dict()}")
                self.notes.append(
                    f"adopted existing prompt {prompt_id} from the durable reservation; "
                    "no second POST was sent")
            else:
                if self.reservations is not None:
                    self.reservation = self.reservations.open(
                        instance_epoch or {}, attempt_id, stage_id=spec.stage_id,
                        owner=claim["owner"], client_id=self.client_id,
                        workflow_id=claim["workflow_id"],
                        workflow_sha256=claim["workflow_sha256"],
                        input_digest=claim["input_digest"],
                        input_identity=claim["input_identity"],
                        note="opened before the POST: a lost acknowledgement must never resubmit")
                if self.sampler is not None:
                    self.sampler.start()
                t_submit = self.clock()
                prompt_id = self.submit(spec.graph)
                timing["submit_s"] = round(self.clock() - t_submit, 3)
                if self.reservations is not None and self.reservation is not None:
                    self.reservation = self.reservations.bind(
                        instance_epoch or {}, self.reservation["attempt_id"], prompt_id,
                        submit_count=self.submit_count)
            base.prompt_id = prompt_id
            base.reservation = self.reservation_state()

            exec_begin: list[float] = []
            t_wait = self.clock()
            entry = self.wait_for_terminal(prompt_id, spec.stage_timeout_s, spec.poll_s, exec_begin)
            timing["wait_s"] = round(self.clock() - t_wait, 3)
            if exec_begin:
                timing["queue_wait_s"] = round(exec_begin[0] - t_wait, 3)
                timing["exec_observed_s"] = round(self.clock() - exec_begin[0], 3)

            if not entry:
                outcome = self.reconcile(prompt_id)
                base.status = "unresolved"
                base.timing = timing
                base.notes = list(self.notes)
                if outcome == "queued":
                    base.notes.append(
                        "prompt still present in /queue: still running, not a failure; "
                        "durable reservation kept and the GPU gate is NOT released")
                    base.reservation = self.reservation_state()
                    return base
                if outcome == "completed":
                    entry = self._history_entry(prompt_id)
                elif outcome == "epoch_lost":
                    raise ServerEpochChanged(
                        "reconcile failed: instance epoch no longer matches the submitting epoch",
                        instance_epoch=instance_epoch, observed_epoch=self.epoch.read() if self.epoch else None,
                        prompt_id=prompt_id,
                    )
                else:
                    raise AmbiguousAfterSubmit(
                        "timeout after submit and no queue/history/epoch proof of the outcome",
                        prompt_id=prompt_id, submit_count=self.submit_count,
                        reconcile=self.reconcile_count, notes=list(self.notes),
                    )

            # Identity re-checked immediately before acceptance: the entry only
            # counts as ours while the server launch is still the one we used (F03).
            self._assert_epoch_unchanged(prompt_id, what="before accepting the result")
            terminal_proven = bool(entry)
            status = ((entry.get("status") or {}).get("status_str")) or "unknown"
            if status == "error":
                messages = (entry.get("status") or {}).get("messages") or []
                text = json.dumps(messages, ensure_ascii=False)
                raise classify_execution_message(text)
            if status not in ("success",):
                raise InvalidGraph("history entry reached a terminal state that is not success", status=status)

            base.status = "generated"
            t_val = self.clock()
            base.artifacts = self.validate_artifacts(entry, spec)
            timing["validate_s"] = round(self.clock() - t_val, 3)
            base.status = "validated"
            base.resources = self.sampler.stop() if self.sampler else {"measured": False}
            timing["total_s"] = round(self.clock() - t_start, 3)
            base.timing = timing
            base.source_map = {
                "exact_frame_mapping": None,
                "note": "adapter does not assert source-frame mapping; MotionForge owns source clock/PTS",
            }
            base.notes = list(self.notes)
            base.reservation = self.reservation_state()
            self.close_reservation("terminal_success",
                                   evidence={"prompt_id": prompt_id, "terminal_status": status,
                                             "artifact_count": len(base.artifacts)})
            base.reservation = self.reservation_state()
            return base
        except MfComfyError as exc:
            base.status = "unresolved" if isinstance(exc, AmbiguousAfterSubmit) else "failed"
            base.failure = exc.to_dict()
            base.timing = timing
            base.notes = list(self.notes)
            if self.sampler is not None:
                base.resources = self.sampler.stop()
            if isinstance(exc, ServerEpochChanged):
                # A different boot identity: quarantine. Its output can never be
                # adopted as this attempt's result and is never released as success.
                if self.reservations is not None and self.reservation is not None:
                    res = self.reservations.quarantine(self.reservation, "epoch_lost",
                                                       closer=self.owner,
                                                       evidence={"error": exc.to_dict()})
                    self.reservation_released = True
                    self._record_event("quarantine_epoch_lost", {"result": res})
            elif terminal_proven:
                self.close_reservation("terminal_error", evidence={"error": exc.to_dict()})
            elif isinstance(exc, (MissingModel, MissingNode, InvalidGraph)):
                # the server rejected the graph outright: the POST provably never landed
                self.close_reservation("rejected_no_submit", evidence={"error": exc.to_dict()})
            base.reservation = self.reservation_state()
            raise
        finally:
            if self.reservation is not None and not self.reservation_released:
                # The prompt's outcome is unprovable, so this attempt is NOT done:
                # the reservation stays on disk and the GPU gate stays held. A
                # second stage is refused by the gate guard until someone
                # reconciles this reservation to a provable terminal outcome.
                base.status = "unresolved"
                base.reservation = self.reservation_state()
                self.notes.append(
                    "durable reservation kept on disk (prompt outcome unprovable): "
                    "GPU gate and instance lease NOT released")
                base.notes = list(self.notes)
            else:
                self._release_hold()
