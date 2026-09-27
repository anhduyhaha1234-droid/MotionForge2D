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

import json
import os
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
    AttemptAlreadyTerminal,
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
from .lease import (
    DURABLE_IDENTITY_FIELDS,
    PromptReservations,
    canonical_digest,
    identity_integrity_problems,
    name_body_problems,
    same_boot_identity,
    submit_provably_never_started,
)
from .paths import StagePaths

ARTIFACT_KEYS = ("images", "gifs", "videos", "audio")
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".gif"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
_MISSING = object()

# The media type each publishable artifact kind must declare (round C: a durable
# contract whose `kind` and `media_type` disagree is not a contract).
_MEDIA_OF_KIND = {"images": "image", "gifs": "image", "videos": "video", "audio": "audio"}

# The fields of `_input_identity`. A durable input identity may not carry anything
# else: an unknown field is a declaration no normalizer of ours ever produced.
_IDENTITY_FIELDS = ("project_id", "job_id", "shot_id", "source_sha256",
                    "source_frame_range", "reference_assets")

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
        # F05: the normalized output contract bound by the reservation this attempt
        # adopted/opened. When set it — never the caller's current spec — decides
        # which terminal node a result may be read from.
        self.bound_output_contract: dict | None = None
        self.object_info: dict = {}

    # ---------------------------------------------------------------- preflight
    def preflight(self, graph: dict, node_inventory_sha256: str = "",
                  workflow_sha256: str = "") -> dict:
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
            # A supplied pin is COMPARED with the hash of the graph actually being
            # submitted; it is never merely echoed (F02).
            "workflow_sha256": pinning.verify_workflow_pin(graph, workflow_sha256),
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
        return canonical_digest(identity)

    @staticmethod
    def output_contract_digest(contract: dict) -> str:
        """Stable digest of a normalized output contract (F05)."""
        return canonical_digest(contract)

    def _claim(self, spec: RunSpec, stage_input: StageInput | None, attempt_id: str) -> dict:
        """The declared identity of the work item this attempt is claiming (F02).

        `workflow_sha256` is never taken on trust: when the caller supplies a pin
        the graph is hashed and the pin must match, so the *correct* pin of an
        OLD graph can never be presented as the identity of a NEW graph. A bad
        pin fails typed (`MF_COMFY_WORKFLOW_HASH_MISMATCH`) right here, i.e.
        before any adoption, staging or POST.

        The normalized output contract is part of the identity (F05): it is bound
        durably at submit time, so a declaration changed across a restart is an
        identity mismatch instead of a licence to publish something else.
        """
        identity = self._input_identity(stage_input)
        return {
            "attempt_id": attempt_id or "",
            "stage_id": spec.stage_id or "",
            "workflow_id": spec.workflow_id or "",
            "workflow_sha256": pinning.verify_workflow_pin(spec.graph, spec.workflow_sha256),
            "owner": spec.owner or self.owner,
            "input_digest": self.identity_digest(identity),
            "input_identity": identity,
            "output_contract_digest": self.output_contract_digest(
                self._normalized_output_contract(spec)),
        }

    @staticmethod
    def _identity_matches(record: dict, claim: dict) -> bool:
        """Adoption is legal only for the exact declared work item (F02).

        Every field must be present on BOTH sides and equal: a record written by
        a build without identity, or by another attempt/stage/workflow/graph/
        input/owner, or under a different output contract, can never be adopted.
        It stays unresolved and blocking instead of being handed to a stranger.

        Round C: this comparison is only ever reached for a record that already
        passed `_record_integrity`, i.e. whose body provably hashes to the digest
        recorded next to it — otherwise a mutated body could compare "equal" on a
        stale digest.
        """
        for key in DURABLE_IDENTITY_FIELDS:
            mine = str((claim or {}).get(key) or "")
            theirs = str((record or {}).get(key) or "")
            if not mine or not theirs or mine != theirs:
                return False
        return True

    @staticmethod
    def _same_work_item(record: dict, claim: dict) -> bool:
        """Does this record describe the same work item the caller is claiming?

        Used on the gate -> new-reservation path: when a record of THIS boot is
        still unresolved and its durable identity does NOT match the caller, but
        it *is* the same work item (same attempt, or same stage+workflow), the
        caller must not be allowed to POST a second prompt for it. A caller
        declaring a genuinely different work item is an independent new request
        and is not blocked here (F02).
        """
        rec = record or {}
        clm = claim or {}
        rec_attempt = str(rec.get("attempt_id") or "")
        clm_attempt = str(clm.get("attempt_id") or "")
        if rec_attempt and clm_attempt and rec_attempt == clm_attempt:
            return True
        rec_stage = str(rec.get("stage_id") or "")
        clm_stage = str(clm.get("stage_id") or "")
        rec_wf = str(rec.get("workflow_id") or "")
        clm_wf = str(clm.get("workflow_id") or "")
        return bool(rec_stage and clm_stage and rec_stage == clm_stage
                    and rec_wf and clm_wf and rec_wf == clm_wf)

    # =============================================== durable resolve (round C)
    # The resolver used to look at UNRESOLVED MARKERS ONLY, so a completed
    # attempt's receipt and a quarantined record were invisible to it: an
    # identical replay looked like brand-new work and POSTed again, and a
    # tampered marker body was reconciled against its own stale digest. These
    # methods build the candidate UNION of all three sources, all of them
    # integrity-checked, and reconcile on independent identity before anything
    # may be released, staged or submitted.
    @staticmethod
    def _same_attempt(record: dict | None, claim: dict | None) -> bool:
        """Same `attempt_id` == the same work item for a TERMINAL record.

        Deliberately narrower than `_same_work_item`: a completion receipt is
        finished business, so a NEW attempt for the same stage/workflow (a
        re-render that declares its own `attempt_id`) is genuinely new work and
        must never be blocked by it (round C, C07: no over-locking).
        """
        mine = str((record or {}).get("attempt_id") or "")
        theirs = str((claim or {}).get("attempt_id") or "")
        return bool(mine and theirs and mine == theirs)

    @staticmethod
    def _contract_schema_problems(contract) -> list[dict]:
        """Semantic/schema consistency of a durable normalized output contract.

        The digest already proves the body is the one that was bound at submit
        time; this proves the body IS a contract — a normalized declaration can
        only ever name publishable kinds, a matching media type, server types
        that narrow (never widen) the publishable set, and sha256 pins.
        """
        if not contract:
            return []
        if not isinstance(contract, dict):
            return [{"problem": "normalized output contract is not an object"}]
        problems: list[dict] = []
        nodes = contract.get("nodes")
        if not isinstance(nodes, dict) or not nodes:
            return [{"problem": "normalized output contract declares no terminal node"}]
        for node_id in sorted(nodes, key=str):
            conf = nodes[node_id]
            if not isinstance(conf, dict):
                problems.append({"problem": "declared terminal node is not an object",
                                 "node_id": str(node_id)})
                continue
            kind, media = conf.get("kind"), conf.get("media_type")
            if kind and kind not in ARTIFACT_KEYS:
                # An EMPTY kind is normal: when the caller declares no terminal
                # output, the normalized contract names the graph's own terminal
                # nodes without a media kind and the server output decides.
                problems.append({"problem": "declared node kind is not publishable",
                                 "node_id": str(node_id), "kind": kind,
                                 "publishable_kinds": list(ARTIFACT_KEYS)})
            elif kind and media and _MEDIA_OF_KIND.get(kind) != media:
                problems.append({"problem": "declared node media type does not match its kind",
                                 "node_id": str(node_id), "kind": kind, "media_type": media,
                                 "expected_media_type": _MEDIA_OF_KIND.get(kind)})
            server_types = conf.get("server_types")
            if not isinstance(server_types, (list, tuple)):
                problems.append({"problem": "declared node server_types is not a sequence",
                                 "node_id": str(node_id), "server_types": server_types})
            elif [t for t in server_types if t not in PUBLISHABLE_SERVER_TYPES]:
                problems.append({"problem": "declared node server_types widen the publishable "
                                            "set",
                                 "node_id": str(node_id), "server_types": list(server_types),
                                 "publishable": list(PUBLISHABLE_SERVER_TYPES)})
        pins = contract.get("expected_artifact_pins", {})
        if not isinstance(pins, dict):
            problems.append({"problem": "expected_artifact_pins is not an object",
                             "expected_artifact_pins": pins})
        else:
            for filename, digest in sorted(pins.items()):
                if not isinstance(digest, str) or len(digest) != 64:
                    problems.append({"problem": "artifact pin is not a sha256 hex digest",
                                     "filename": filename, "pin": digest})
        return problems

    @staticmethod
    def _input_identity_schema_problems(identity) -> list[dict]:
        """Semantic/schema consistency of a durable input identity."""
        if not identity:
            return []
        if not isinstance(identity, dict):
            return [{"problem": "input identity is not an object"}]
        problems: list[dict] = []
        unknown = sorted(set(identity) - set(_IDENTITY_FIELDS))
        if unknown:
            problems.append({"problem": "input identity carries unknown fields",
                             "unknown_fields": unknown,
                             "known_fields": list(_IDENTITY_FIELDS)})
        source = identity.get("source_sha256")
        if source not in (None, "") and (not isinstance(source, str) or len(source) != 64):
            problems.append({"problem": "source_sha256 is not a 64-character digest",
                             "source_sha256": source})
        frames = identity.get("source_frame_range")
        if frames is not None and (not isinstance(frames, list)
                                   or any(not isinstance(v, int) or isinstance(v, bool)
                                          for v in frames)):
            problems.append({"problem": "source_frame_range is not a list of integers",
                             "source_frame_range": frames})
        if identity.get("reference_assets") is not None \
                and not isinstance(identity["reference_assets"], dict):
            problems.append({"problem": "reference_assets is not an object"})
        return problems

    def _record_integrity(self, record: dict, *, what: str, path=None,
                          suffix: str = "") -> list[dict]:
        """Integrity of ONE durable record, BEFORE it takes part in the resolve.

        Only an internally consistent record may be reconciled:

          * its identity bodies must hash to the digests recorded next to them
            (`input_identity`↔`input_digest`, `output_contract`↔
            `output_contract_digest`) — this is what stops a mutated body from
            being validated against a stale digest;
          * it may not be stored under a name that describes a different
            instance/attempt than the body it carries;
          * its normalized contract and input identity must actually BE a
            contract / an identity.

        Anything else is UNKNOWN state, and unknown state fails closed: never an
        adoption, never a release, never a licence for a second POST.
        """
        rec = record if isinstance(record, dict) else {}
        problems: list[dict] = []
        for detail in identity_integrity_problems(rec):
            problems.append({
                "problem": "durable identity body does not match its own digest",
                "what": what, "detail": detail,
                "recorded_input_digest": rec.get("input_digest") or "",
                "recomputed_input_digest":
                    canonical_digest(rec.get("input_identity") or {}),
                "recorded_output_contract_digest": rec.get("output_contract_digest") or "",
                "recomputed_output_contract_digest":
                    canonical_digest(rec.get("output_contract") or {}),
            })
        if path is not None:
            parts = self._file_name_parts(path, suffix)
            for detail in name_body_problems(path, rec, suffix):
                problem = {"problem": "record disagrees with the file it is stored in",
                           "class": "name", "what": what, "detail": detail,
                           "path": str(path)}
                if parts:
                    problem["name_instance"], problem["name_attempt"] = parts
                problems.append(problem)
        for problem in self._contract_schema_problems(rec.get("output_contract")):
            problems.append({**problem, "class": "contract"})
        for problem in self._input_identity_schema_problems(rec.get("input_identity")):
            problems.append({**problem, "class": "input"})
        return problems

    @staticmethod
    def _file_name_parts(path, suffix: str = "") -> tuple[str, str] | None:
        """`<instance>__<attempt>` as encoded by the ledger file name, or None."""
        if path is None:
            return None
        name = Path(path).name
        stem = name[: -len(suffix)] if suffix and name.endswith(suffix) else Path(name).stem
        if "__" not in stem:
            return None
        return tuple(stem.split("__", 1))  # type: ignore[return-value]

    def _assert_record_integrity(self, record: dict, *, what: str, path=None,
                                 suffix: str = "") -> None:
        problems = self._record_integrity(record, what=what, path=path, suffix=suffix)
        if not problems:
            return
        misnamed = [p for p in problems if p.get("class") == "name"]
        if misnamed and len(misnamed) == len(problems):
            raise ReservationConflict(
                f"refusing to reconcile a {what} that is stored under a name describing a "
                "different instance/attempt than the record it carries",
                attempt_id=(record or {}).get("attempt_id"),
                path=str(path) if path else (record or {}).get("path"),
                problems=misnamed[:8])
        raise CorruptReservation(
            f"refusing to reconcile a {what} that does not describe itself",
            attempt_id=(record or {}).get("attempt_id"),
            path=str(path) if path else (record or {}).get("path"),
            problem_count=len(problems), problems=problems[:12])

    def ledger_candidates(self, instance_epoch: dict | None = None) -> dict:
        """UNION of every durable record that can speak about this boot.

        unresolved markers ∪ completion receipts ∪ quarantine records, each one
        integrity-checked before it is allowed to take part in identity
        resolution. Round C: looking at unresolved markers only is exactly why a
        completed attempt could be POSTed a second time.
        """
        view = {"markers": [], "receipts": [], "quarantined": [], "corrupt": [],
                "misnamed": [], "instance_epoch": instance_epoch or {}}
        if self.reservations is None:
            return view
        store = self.reservations
        # Round D (NR02): quarantine bytes are authority too. An unreadable or
        # identity-incomplete quarantine record is UNKNOWN state, so it joins the
        # corrupt set instead of being silently skipped by `quarantined()`.
        view["corrupt"] = (list(store.unreadable())
                           + list(store.unreadable_receipts())
                           + list(store.unreadable_quarantines()))
        for bucket, records, what, suffix in (
                ("markers", store.unresolved(), "unresolved reservation", store.SUFFIX),
                ("receipts", store.receipts(), "completion receipt", ".released.json"),
                ("quarantined", store.quarantined(), "quarantine record",
                 ".quarantined.json")):
            for rec in records:
                problems = self._record_integrity(rec, what=what, path=rec.get("path"),
                                                  suffix=suffix)
                misnamed = [p for p in problems if p.get("class") == "name"]
                rest = [p for p in problems if p.get("class") != "name"]
                if rest:
                    view["corrupt"].append({"path": rec.get("path"), "what": what,
                                            "problems": rest[:8]})
                elif misnamed:
                    # A record whose own file name describes another instance/attempt
                    # cannot be attributed by name, so it is a competing claimant
                    # rather than a candidate: reconciled as a conflict, never
                    # silently chosen (round C, C04 alternate key/path).
                    view["misnamed"].append({"path": rec.get("path"), "what": what,
                                             "record": rec, "problems": misnamed[:4],
                                             "name_instance": misnamed[0].get("name_instance"),
                                             "name_attempt": misnamed[0].get("name_attempt")})
                else:
                    view[bucket].append(rec)
        return view

    def _replayed_evidence(self, receipt: dict) -> list[dict] | None:
        """Durable validated evidence of a completed attempt, if it is still intact.

        Never re-fetches and never re-POSTs: the recorded staged artifacts are
        re-hashed on disk, re-checked against their recorded size and confined to
        this stage root, and only then handed back. Missing or changed bytes mean
        the evidence is gone, which is a REFUSAL — not a new attempt.
        """
        if str(receipt.get("outcome") or "") != "terminal_success":
            return None
        records = (receipt.get("close_evidence") or {}).get("artifacts")
        if not isinstance(records, list) or not records:
            return None
        root = str(Path(self.paths.root).resolve()).lower().rstrip(os.sep)
        artifacts: list[dict] = []
        for item in records:
            if not isinstance(item, dict):
                return None
            raw_path = str(item.get("staged_path") or "")
            if not raw_path:
                return None
            real = Path(raw_path)
            try:
                real = real.resolve()
            except OSError:
                return None
            where = str(real).lower()
            if where != root and not where.startswith(root + os.sep):
                return None
            if not real.exists() or real.stat().st_size != item.get("size_bytes"):
                return None
            if pinning.sha256_file(real) != item.get("sha256"):
                return None
            artifacts.append({**item, "staged_path": str(real),
                              "reused_from": receipt.get("path")})
        return artifacts

    def _durable_union_fingerprint(self, instance_epoch: dict | None = None) -> frozenset:
        """What the durable ledger said when THIS caller took its decision.

        R27-03: the resolve/claim decision is taken before the gate and REPEATED
        inside the gate's critical section, because a caller holding the same
        attempt identity can durably commit while this caller waits for the lock.
        This fingerprint is the comparison the in-gate decision uses: the decision
        is re-taken exactly when another caller changed the durable state, and
        never re-triggered by the records THIS caller has already dispositioned
        itself (its own `not_accepted` release, its own adopted marker) -- reading
        those again would turn a legitimate requeue into a refusal of the very
        attempt the release was meant to free.
        """
        if self.reservations is None:
            return frozenset()
        view = self.ledger_candidates(instance_epoch)
        marks: set = set()
        for bucket in ("markers", "receipts", "quarantined"):
            for rec in view[bucket]:
                marks.add((bucket, str(rec.get("path") or ""), str(rec.get("state") or ""),
                           str(rec.get("outcome") or ""), str(rec.get("prompt_id") or "")))
        for item in view["misnamed"]:
            rec = item.get("record") or {}
            marks.add(("misnamed", str(rec.get("path") or ""), str(rec.get("state") or ""),
                       str(rec.get("outcome") or ""), str(rec.get("prompt_id") or "")))
        for item in view["corrupt"]:
            marks.add(("corrupt", str(item.get("path") or ""), "", "", ""))
        return frozenset(marks)

    def resolve_durable_prior(self, claim: dict, instance_epoch: dict | None = None) -> dict | None:
        """Reconcile the durable UNION against this caller's declared identity.

        Returns the receipt to REPLAY when a terminal completion of exactly this
        work item can hand its durable validated evidence back, raises the typed
        refusal when the durable state forbids a new attempt, and returns None
        when this caller is free to submit (an independent new work item, or
        nothing durable claims this attempt).

        Fixed order: integrity (`ledger_candidates`) -> enumerate the COMPLETE
        candidate union and resolve its conflicts (round D) -> reconcile on
        independent identity -> release/reuse -> and only THEN may a stage submit.
        """
        view = self.ledger_candidates(instance_epoch)
        if view["corrupt"]:
            raise CorruptReservation(
                "refusing to resolve this attempt: durable reservation state is unreadable",
                corrupt_count=len(view["corrupt"]), corrupt=view["corrupt"][:12])
        inst = str((instance_epoch or {}).get("instance_id") or "")
        # A claimant stored under a name that describes another instance/attempt is
        # not a candidate that may be chosen and not a foreign record that may be
        # quarantined to unlock a POST: it is a competing claim about OUR state.
        ours = [m for m in view["misnamed"]
                if inst and (m.get("name_instance") == inst
                             or str((m.get("record") or {}).get("instance_id") or "") == inst)]
        if ours:
            raise ReservationConflict(
                "a durable claimant is stored under a name that describes a different "
                "instance/attempt than the record it carries; refusing to choose which "
                "record is the real one",
                misnamed=[{k: m.get(k) for k in ("path", "what", "name_instance",
                                                 "name_attempt")} for m in ours[:8]],
                observed_instance_id=inst)
        # ---- Round D (NR01): resolve the COMPLETE candidate union first.
        # Round C handed back the first successful receipt as soon as it reached
        # it, so a second durable record that also claimed this attempt -- a
        # wrong-owner marker, a duplicate receipt, a quarantine record -- was never
        # read: the caller received "validated" evidence while the ledger disagreed
        # with itself. The union is now enumerated IN FULL (unresolved markers u
        # completion receipts u quarantine records, plus the records whose own file
        # name contradicts the body they carry) and every conflict is decided
        # BEFORE any reuse, staging or POST.
        claims: list[tuple[str, dict]] = []
        for bucket in ("markers", "receipts", "quarantined"):
            for rec in view[bucket]:
                if self._same_attempt(rec, claim):
                    claims.append((bucket, rec))
        for item in view["misnamed"]:
            rec = item.get("record") or {}
            if self._same_attempt(rec, claim):
                claims.append(("misnamed", rec))
        self._record_event("durable_union_enumerated", {
            "union": {"markers": len(view["markers"]), "receipts": len(view["receipts"]),
                      "quarantined": len(view["quarantined"]),
                      "misnamed": len(view["misnamed"]), "corrupt": len(view["corrupt"])},
            "claimants": [{"bucket": bucket, "path": rec.get("path"),
                           "recorded_instance_id": rec.get("instance_id"),
                           "recorded_owner": rec.get("owner"),
                           "recorded_attempt_id": rec.get("attempt_id"),
                           "state": rec.get("state"), "outcome": rec.get("outcome")}
                          for bucket, rec in claims],
            "note": "the whole union is enumerated and integrity-checked BEFORE any "
                    "reuse decision; a quarantine record or a second claimant of this "
                    "attempt refuses below"})
        for bucket, rec in claims:
            if bucket != "quarantined":
                continue
            # Durable evidence that an attempt's outcome was NOT proven can never be
            # turned into a licence for a new POST: under the same boot the ledger
            # contradicts itself, and under a different boot the epoch change is not
            # proof that the attempt never landed (NR02).
            raise ReservationConflict(
                "a quarantine record claims this attempt, so the ledger holds no proof "
                "of its outcome; neither an implicit release nor a new POST for this "
                "attempt is legal",
                recorded_instance_id=rec.get("instance_id"),
                observed_instance_id=inst,
                recorded_attempt_id=rec.get("attempt_id"),
                quarantine_reason=rec.get("quarantine_reason"),
                recorded_host=rec.get("host"), path=rec.get("path"))
        if len(claims) > 1:
            raise ReservationConflict(
                "more than one durable record claims this attempt; refusing to choose "
                "one of them and refusing a second POST for it",
                attempt_id=(claim or {}).get("attempt_id"),
                observed_instance_id=inst,
                claimants=[{"bucket": bucket, "path": rec.get("path"),
                            "recorded_instance_id": rec.get("instance_id"),
                            "recorded_owner": rec.get("owner"),
                            "recorded_attempt_id": rec.get("attempt_id"),
                            "state": rec.get("state"), "outcome": rec.get("outcome")}
                           for bucket, rec in claims])
        for rec in view["receipts"]:
            if not self._same_attempt(rec, claim):
                self._record_event("terminal_record_other_attempt", {
                    "receipt": rec.get("path"), "recorded_attempt_id": rec.get("attempt_id"),
                    "outcome": rec.get("outcome"),
                    "note": "a terminal record of another attempt is finished business; "
                            "this independently declared work item is free to run"})
                continue
            outcome = str(rec.get("outcome") or "")
            same_boot = same_boot_identity(rec, instance_epoch)
            if same_boot and self._identity_matches(rec, claim or {}):
                replayed = self._replayed_evidence(rec)
                if replayed is not None:
                    self._record_event("replayed_terminal_receipt", {
                        "receipt": rec.get("path"), "outcome": outcome,
                        "prompt_id": rec.get("prompt_id"),
                        "artifact_count": len(replayed),
                        "note": "completion is already proven for this exact work item; the "
                                "durable validated evidence is handed back instead of "
                                "submitting a second prompt"})
                    return {"receipt": rec, "artifacts": replayed}
            if not same_boot:
                raise AttemptAlreadyTerminal(
                    "a previous server boot already reached a terminal outcome for this exact "
                    "attempt; the durable receipt forbids an implicit second attempt (a new "
                    "piece of work must declare its own attempt_id)",
                    recorded_instance_id=rec.get("instance_id"),
                    observed_instance_id=inst, recorded_outcome=outcome,
                    receipt=rec.get("path"), release_count=rec.get("release_count"),
                    recorded_host=rec.get("host"))
            if not self._identity_matches(rec, claim or {}):
                raise ReservationConflict(
                    "a released reservation covers this attempt with a DIFFERENT durable "
                    "identity; refusing to choose between the recorded identity and the "
                    "declared one",
                    incoming={k: (claim or {}).get(k) for k in DURABLE_IDENTITY_FIELDS},
                    existing={k: rec.get(k) for k in DURABLE_IDENTITY_FIELDS},
                    receipt=rec.get("path"), outcome=outcome)
            raise AttemptAlreadyTerminal(
                f"this attempt already reached a terminal outcome "
                f"({outcome or 'unknown'}); refusing a second POST. The durable receipt is "
                f"kept as evidence",
                recorded_outcome=outcome, receipt=rec.get("path"),
                release_count=rec.get("release_count"),
                reopened_by=rec.get("closer"),
                reusable_artifacts=bool((rec.get("close_evidence") or {}).get("artifacts")))
        return None

    def _replayed_output(self, spec: RunSpec, prior: dict,
                         stage_input: StageInput | None, base: StageOutput) -> StageOutput:
        """Hand back the durable validated evidence of an already-terminal attempt.

        No gate, no lease, no POST and no re-fetch: completion is already proven
        by the receipt and the artifact bytes were re-hashed on disk. `adopted` is
        True because this attempt took over existing evidence instead of making
        new output.
        """
        receipt = prior["receipt"]
        base.status = "validated"
        base.adopted = True
        base.prompt_id = receipt.get("prompt_id")
        base.artifacts = prior["artifacts"]
        base.timing = {"replay_s": 0.0}
        base.source_map = {
            "exact_frame_mapping": None,
            "note": "replayed from a durable completion receipt; no new server interaction",
        }
        base.reservation = {
            "exists": False,
            "released": True,
            "source": "completion_receipt",
            "receipt_path": receipt.get("path"),
            "receipt_outcome": receipt.get("outcome"),
            "release_count": receipt.get("release_count"),
            "receipt_instance_id": receipt.get("instance_id"),
            "observed_instance_id": (self.instance_epoch or {}).get("instance_id"),
            "submit_calls": self.submit_count,
        }
        base.notes = list(self.notes)
        base.notes.append(
            "reused durable validated evidence from the completion receipt of this exact "
            "work item; no gate, no lease and no second POST were needed")
        return base

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
        # 2) this boot's own unresolved reservations, bound by durable identity.
        # Integrity FIRST (round C): a record may only be reconciled once it has
        # proven it describes itself, so a re-pointed output contract or a
        # rewritten input identity can never be validated against its own stale
        # digest.
        same_boot = self.reservations.unresolved(inst)
        for rec in same_boot:
            self._assert_record_integrity(rec, what="unresolved reservation of this boot",
                                          path=rec.get("path"),
                                          suffix=self.reservations.SUFFIX)
        mine = [r for r in same_boot if self._identity_matches(r, claim or {})]
        claimants = [r for r in same_boot if self._same_work_item(r, claim or {})]
        if len(mine) > 1:
            raise ReservationConflict(
                "several reservations claim the same work item identity; refusing to choose",
                attempt_id=(claim or {}).get("attempt_id"),
                keys=[r.get("key") for r in mine],
                paths=[r.get("path") for r in mine],
            )
        if mine and len(claimants) > 1:
            # Round C (Codex `one_exact_one_wrong_same_attempt`): one record that
            # matches this identity exactly PLUS another that also claims this work
            # item is not licence to adopt the exact subset — the wrong claimant
            # may be the one holding the prompt.
            raise ReservationConflict(
                "one reservation matches this identity exactly while another also claims "
                "this work item; refusing to pick the exact subset",
                attempt_id=(claim or {}).get("attempt_id"),
                incoming={k: (claim or {}).get(k) for k in DURABLE_IDENTITY_FIELDS},
                claimant_count=len(claimants),
                claimants=[{k: r.get(k) for k in
                            ("key", "attempt_id", "stage_id", "workflow_id", "owner",
                             "input_digest", "output_contract_digest", "prompt_id",
                             "submit_state", "state", "path")} for r in claimants],
                paths=[r.get("path") for r in claimants],
            )
        if not mine:
            # F02 (gate -> new-reservation branch): a reservation of THIS boot may
            # still describe the SAME work item while its durable identity does not
            # match this caller. That is not a licence to open a second reservation
            # and POST: reaching the gate would let the reconcile hook prove the
            # old prompt terminal, free its marker and silently submit a duplicate.
            # The only legal paths are (a) recovery of the exact same identity and
            # (b) a genuinely independent request for a DIFFERENT work item.
            conflicts = claimants
            if conflicts:
                raise ReservationConflict(
                    "an unresolved reservation already claims this work item, but its "
                    "durable identity does not match this caller; refusing to silently "
                    "submit a second prompt. Recover it with the exact identity "
                    "(attempt/stage/workflow/graph/output contract/input/owner) or "
                    "reconcile its outcome first.",
                    attempt_id=(claim or {}).get("attempt_id"),
                    incoming={k: (claim or {}).get(k) for k in
                              ("attempt_id", "stage_id", "workflow_id", "workflow_sha256",
                               "owner", "input_digest", "output_contract_digest")},
                    existing=[{k: r.get(k) for k in
                               ("key", "attempt_id", "stage_id", "workflow_id",
                                "workflow_sha256", "owner", "input_digest",
                                "output_contract_digest", "prompt_id", "submit_state",
                                "state")} for r in conflicts],
                    paths=[r.get("path") for r in conflicts],
                )
            self._record_event("no_identity_match", {
                "claim": {k: (claim or {}).get(k) for k in
                          ("attempt_id", "stage_id", "workflow_id", "workflow_sha256", "owner")},
                "unresolved_for_this_boot": len(self.reservations.unresolved(inst)),
                "note": "a reservation of another work item stays unresolved and keeps "
                        "blocking the gate for this instance"})
            return None
        rec = mine[0]
        # F05: the normalized output contract is durable. A record whose contract is
        # missing or corrupt cannot be validated against the caller's CURRENT
        # declaration, so it fails closed instead of publishing whatever the current
        # spec happens to name.
        contract = rec.get("output_contract")
        if not isinstance(contract, dict) or not contract.get("nodes"):
            raise CorruptReservation(
                "the reservation carries no durable normalized output contract; refusing "
                "to validate a result against the caller's current declaration",
                attempt_id=rec.get("attempt_id"), path=rec.get("path"),
                present=[k for k in ("output_contract", "output_contract_digest") if k in rec])
        self.bound_output_contract = contract
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
        self._report_unrecorded_outcome(outcome, res)
        return res

    def _report_unrecorded_outcome(self, outcome: str, result: dict) -> None:
        """A requested outcome the LEDGER did not record is never reported silently.

        `PromptReservations.close()` writes ONE receipt per (instance, attempt) and
        refuses a second write for that slot (exclusive create, first write wins).
        A same-attempt requeue therefore asks for the SECOND write of one slot: the
        orphan was already released as `not_accepted` before this caller re-POSTed
        (F01: a POST that provably never started may be retried on the same
        attempt), so the requeued run's own terminal outcome is dropped and the
        durable ledger keeps the release. The run is real -- the artifact exists on
        the wire and on disk -- but a later replay of this attempt reads a receipt
        that carries no artifacts, so the validated evidence is NOT reusable.

        The adapter cannot make that second write legal (the one-receipt slot is the
        store's invariant), so the contradiction must not pass silently: it is
        reported as a typed event plus a note carrying the requested outcome, the
        recorded outcome, the release count and the receipt path.
        """
        if not result.get("already_released"):
            return
        recorded = result.get("outcome")
        if recorded == outcome:
            return
        self._record_event("terminal_outcome_not_durably_recorded",
                           {"requested_outcome": outcome, "recorded_outcome": recorded,
                            "release_count": result.get("release_count"),
                            "receipt": result.get("closed_path")})
        self.notes.append(
            f"the durable ledger did NOT record this attempt\'s {outcome!r}: this "
            f"attempt\'s single receipt was already written by an earlier outcome "
            f"({recorded!r}) and the store refuses a second write for the same attempt "
            f"slot, so a later replay of this attempt cannot reuse the validated "
            f"evidence ({result.get('closed_path')})")

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

    def _declared_terminal_outputs(self, spec: RunSpec, contract: dict | None = None) -> dict:
        """The terminal output node(s) of this workflow (F05).

        With a durable `contract` (the one bound at submit time) THAT contract
        governs: the caller's current spec can never re-declare a different node
        for an attempt that was already submitted. Without one,
        `RunSpec.terminal_outputs` is the declaration; when it is empty the
        graph's own terminal nodes are used (ComfyUI marks them
        `output_node: true`, e.g. SaveImage / SaveAnimatedWEBP).
        """
        if isinstance(contract, dict) and isinstance(contract.get("nodes"), dict):
            return {str(k): dict(v or {}) for k, v in contract["nodes"].items()}
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

    def _normalized_output_contract(self, spec: RunSpec) -> dict:
        """The durable, normalized result contract of one submit (F05).

        Normalized = the resolved terminal node ids (explicit declaration, or the
        graph's own `output_node` nodes) with their kind / media type / publishable
        server types, plus the expected artifact pins. This exact structure is
        written into the reservation and is the only thing any later read of the
        same attempt may validate against.
        """
        declared = self._declared_terminal_outputs(spec)
        nodes: dict[str, dict] = {}
        for node_id in sorted(declared):
            conf = declared[node_id] or {}
            nodes[str(node_id)] = {
                "kind": conf.get("kind") or "",
                "media_type": conf.get("media_type") or "",
                "server_types": list(self._declared_server_types(conf, spec)),
            }
        pins = {str(k): str(v) for k, v in sorted((spec.expected_artifact_hashes or {}).items())}
        return {"nodes": nodes, "expected_artifact_pins": pins}

    @staticmethod
    def _declared_server_types(conf: dict, spec: RunSpec) -> tuple:
        """Publishable server types for one declared node.

        A product is what the server WROTE (`type == "output"`). `allowed_types`
        may only narrow that set: it can never make an `input` preview or a
        `temp` scratch file into a result (F05). An explicit `server_types` on
        the declaration is authoritative and is never widened.
        """
        want = conf.get("server_types")
        if want is None:
            want = spec.allowed_types or PUBLISHABLE_SERVER_TYPES
        return tuple(t for t in want if t in PUBLISHABLE_SERVER_TYPES)

    def _staging_report(self, records: list[dict]) -> dict:
        """Isolated staging vs publication, told apart explicitly (round C).

        An artifact is written into the stage root BEFORE it can be validated, so
        a failing validation can legitimately leave isolated staged bytes behind.
        That is not a published result, and a report may never claim "0 staged"
        while a file exists: this says how many files are isolated-staged, which
        ones, and that the published count is zero.
        """
        return {
            "stage_root": str(self.paths.root),
            "isolated_staged": len(records),
            "published": 0,
            "records": [{k: r.get(k) for k in ("node_id", "kind", "filename", "server_type",
                                               "staged_path", "sha256", "size_bytes")}
                        for r in records],
            "note": "isolated staging only: these bytes were never accepted or published, "
                    "and they are kept as failure evidence",
        }

    def validate_artifacts(self, entry: dict, spec: RunSpec,
                           contract: dict | None = None) -> list[dict]:
        outputs = entry.get("outputs") or {}
        bound = contract if contract is not None else getattr(self, "bound_output_contract", None)
        declared = self._declared_terminal_outputs(spec, bound)
        pins = (bound or {}).get("expected_artifact_pins") if isinstance(bound, dict) else None
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
        # Round C: an artifact written into the stage root is ISOLATED STAGING
        # until it passes every check. A validation failure may therefore leave a
        # real file behind, and the typed failure has to say so (never "0 staged").
        staged: list[dict] = []
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
            staged.append({"node_id": node_id, "kind": key, "filename": filename,
                           "subfolder": subfolder, "server_type": atype,
                           "staged_path": str(target), "sha256": sha,
                           "size_bytes": len(raw)})
            expected = (pins if pins is not None
                        else (spec.expected_artifact_hashes or {})).get(filename)
            if expected and expected != sha:
                raise ArtifactHashMismatch("artifact hash differs from the recorded expectation",
                                           filename=filename, expected=expected, actual=sha,
                                           staging=self._staging_report(staged))
            decode_ok, width, height, decode_note = self._decode_check(target, raw)
            if decode_ok is False:
                raise PartialOutput("artifact did not fully decode", item=item,
                                    note=decode_note, staging=self._staging_report(staged))
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
        # `claim` is built after preflight (below): the normalized output contract
        # resolves against the loaded node inventory, and the caller's workflow pin
        # is verified against the real graph hash before any adoption or POST.
        t_start = self.clock()
        timing: dict[str, Any] = {}
        instance_epoch = self.instance_epoch or (self.epoch.read() if self.epoch else None)
        base = StageOutput(
            status="failed", stage_id=spec.stage_id, workflow_id=spec.workflow_id,
            instance_epoch=instance_epoch or {},
        )
        terminal_proven = False
        try:
            pre = self.preflight(spec.graph, spec.node_inventory_sha256, spec.workflow_sha256)
            timing["preflight_s"] = round(self.clock() - t_start, 3)
            base.workflow_sha256 = pre["workflow_sha256"]
            base.node_inventory_sha256 = pre["node_inventory_sha256"]
            base.model_hashes = dict(spec.model_pins)

            # Declared identity of this work item (F02), including the normalized
            # output contract (F05). A pin that does not match the real graph hash
            # raises inside `_claim` here — before adoption, staging or POST.
            claim = self._claim(spec, stage_input, attempt_id)

            # Round C: the durable resolve now covers ALL THREE sources at once
            # (unresolved markers ∪ completion receipts ∪ quarantine records). A
            # terminal receipt of exactly this work item either hands its durable
            # validated evidence back or refuses HERE — before the gate, before the
            # lease and before any POST, so a replay can never become a second
            # submission even if it is a fresh process.
            prior = self.resolve_durable_prior(claim, instance_epoch)
            if prior is not None:
                return self._replayed_output(spec, prior, stage_input, base)

            # F01 fix, step 1: does THIS work item already own a prompt? Answer
            # BEFORE taking the gate, so the adopting attempt can take over its own
            # reservation instead of POSTing a second prompt. Adoption is bound to
            # the declared identity, and a reservation of another work item is left
            # unresolved (it keeps blocking the gate below).
            adopted = self.adopt_pending(instance_epoch, claim)
            adopt_key = self.reservation.get("key") if (adopted and self.reservation) else None
            # R27-03: the durable state THIS caller has already decided on, taken
            # after our own pre-gate commit (own marker adopted / own orphan
            # released) and compared again inside the gate below.
            durable_decided = self._durable_union_fingerprint(instance_epoch)

            if self.gate is not None:
                # epoch + reconcile callback: while any OTHER unresolved
                # reservation owns this server boot the gate refuses, and only a
                # provable terminal outcome clears one.
                self.gate.acquire(stage_label=spec.stage_id, epoch=instance_epoch,
                                  reconcile=self.gate_reconcile_hook, adopt_key=adopt_key)
                self.gate_acquired = True
                # R27-03 (class fix): the durable resolve/claim DECISION is re-taken
                # inside the gate's critical section. Two callers of ONE attempt
                # identity can both read an empty candidate union before the gate;
                # the first then completes, closes its reservation and releases the
                # lock while the second is still waiting, so the second would enter
                # the gate holding a stale decision and POST a second prompt for an
                # already-terminal attempt (reviewer probe: 2 POSTs for one attempt,
                # duplicate artifact published, receipt keeps the first prompt).
                # Re-resolving here means the caller entering the critical section
                # either reuses the exact committed receipt/artifact or refuses with
                # an existing typed error -- exactly one POST per attempt identity.
                if self._durable_union_fingerprint(instance_epoch) != durable_decided:
                    prior_in_gate = self.resolve_durable_prior(claim, instance_epoch)
                    if prior_in_gate is not None:
                        return self._replayed_output(spec, prior_in_gate, stage_input, base)
                    adopted = self.adopt_pending(instance_epoch, claim)
                    adopt_key = (self.reservation.get("key")
                                 if (adopted and self.reservation) else None)
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
                # F05: the normalized output contract is bound durably HERE, before
                # the POST, and it governs every later read of this attempt.
                contract = self._normalized_output_contract(spec)
                if self.reservations is not None:
                    self.reservation = self.reservations.open(
                        instance_epoch or {}, attempt_id, stage_id=spec.stage_id,
                        owner=claim["owner"], client_id=self.client_id,
                        workflow_id=claim["workflow_id"],
                        workflow_sha256=claim["workflow_sha256"],
                        input_digest=claim["input_digest"],
                        input_identity=claim["input_identity"],
                        output_contract=contract,
                        output_contract_digest=self.output_contract_digest(contract),
                        note="opened before the POST: a lost acknowledgement must never resubmit")
                self.bound_output_contract = contract
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
                                             "artifact_count": len(base.artifacts),
                                             # durable validated evidence: a later replay of
                                             # this exact work item reuses it instead of
                                             # POSTing a second prompt (round C)
                                             "artifacts": [dict(a) for a in base.artifacts]})
            base.reservation = self.reservation_state()
            return base
        except MfComfyError as exc:
            base.status = "unresolved" if isinstance(exc, AmbiguousAfterSubmit) else "failed"
            base.failure = exc.to_dict()
            base.timing = timing
            staging = (getattr(exc, "details", None) or {}).get("staging")
            if isinstance(staging, dict) and staging.get("isolated_staged"):
                self.notes.append(
                    f"isolated staging: {staging['isolated_staged']} file(s) were written into "
                    "the stage root and then failed validation; they were never accepted or "
                    "published and are kept as failure evidence")
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
