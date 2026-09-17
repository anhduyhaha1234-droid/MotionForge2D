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
    InvalidGraph,
    MfComfyError,
    MissingModel,
    MissingNode,
    PartialOutput,
    ServerEpochChanged,
    TransportError,
    WsDisconnected,
    classify_execution_message,
)
from .paths import StagePaths

ARTIFACT_KEYS = ("images", "gifs", "videos", "audio")
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".gif"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
_MISSING = object()


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
        # attempt bookkeeping / counters used as evidence
        self.submit_count = 0
        self.reconcile_count = 0
        self.interrupt_count = 0
        self.interrupt_refusals = 0
        self.ws_events: list[dict] = []
        self.notes: list[str] = []
        self.instance_epoch: dict | None = None
        self.capabilities: dict = {}
        self.node_inventory_sha256 = ""

    # ---------------------------------------------------------------- preflight
    def preflight(self, graph: dict, node_inventory_sha256: str = "") -> dict:
        object_info = self.transport.object_info()
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
        try:
            res = self.transport.submit(graph, self.client_id)
        except (MissingNode, MissingModel, InvalidGraph):
            raise
        except TransportError as exc:
            # The POST may or may not have been accepted: unprovable -> ambiguous.
            raise AmbiguousAfterSubmit(
                "prompt submission outcome is unprovable (transport failed during POST)",
                submit_attempted=True, prompt_id=None, transport_error=exc.to_dict(),
            ) from exc
        if self.lease is not None:
            try:
                self.lease.set_prompt(res.prompt_id)
            except MfComfyError as exc:
                self.notes.append(f"lease binding skipped: {exc.to_dict()}")
        return res.prompt_id

    # -------------------------------------------------------------------- wait
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
                return entry
            if self.instance_epoch is not None and self.epoch is not None:
                if not self.epoch.matches(self.instance_epoch):
                    raise ServerEpochChanged(
                        "server instance epoch changed while waiting for the prompt",
                        instance_epoch=self.instance_epoch, observed_epoch=self.epoch.read(),
                        prompt_id=prompt_id,
                    )
        return {}

    # -------------------------------------------------------------- reconcile
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
                if isinstance(item, (list, tuple)) and item and item[0] == prompt_id:
                    return "queued"
        try:
            if self._history_entry(prompt_id):
                return "completed"
        except TransportError as exc:
            self.notes.append(f"history read failed during reconcile: {exc.to_dict()}")
        if self.instance_epoch is not None and self.epoch is not None:
            if not self.epoch.matches(self.instance_epoch):
                return "epoch_lost"
        return "unproven"

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

    def validate_artifacts(self, entry: dict, spec: RunSpec) -> list[dict]:
        outputs = entry.get("outputs") or {}
        candidates: list[tuple[str, str, dict]] = []
        for node_id, node_out in outputs.items():
            for key in ARTIFACT_KEYS:
                for item in (node_out.get(key) or []):
                    candidates.append((node_id, key, item))
        if not candidates:
            raise ArtifactMissing("history entry carries no artifact records",
                                  prompt_id=entry.get("prompt_id"), outputs_keys=list(outputs))
        artifacts: list[dict] = []
        for node_id, key, item in candidates:
            filename = item.get("filename", "")
            subfolder = item.get("subfolder", "")
            atype = item.get("type", "output")
            if atype not in spec.allowed_types:
                raise ArtifactMissing("artifact type is not publishable", node_id=node_id,
                                      item=item, allowed_types=list(spec.allowed_types))
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
        return artifacts

    # -------------------------------------------------------------- interrupt
    def interrupt(self, prompt_id: str) -> dict:
        """`/interrupt` is only legal while holding the exclusive lease for this prompt."""
        if self.lease is None:
            self.interrupt_refusals += 1
            from .errors import LeaseNotHeld

            raise LeaseNotHeld("no lease manager configured; interrupt refused")
        try:
            self.lease.assert_held_for(prompt_id=prompt_id, epoch=self.instance_epoch)
        except MfComfyError:
            self.interrupt_refusals += 1
            raise
        self.interrupt_count += 1
        return self.transport.interrupt(prompt_id)

    # ------------------------------------------------------------------- run
    def run(self, spec: RunSpec, stage_input: StageInput | None = None) -> StageOutput:
        stage_input = stage_input or StageInput(stage_id=spec.stage_id, staging_root=str(self.paths.root))
        t_start = self.clock()
        timing: dict[str, Any] = {}
        instance_epoch = self.instance_epoch or (self.epoch.read() if self.epoch else None)
        base = StageOutput(
            status="failed", stage_id=spec.stage_id, workflow_id=spec.workflow_id,
            instance_epoch=instance_epoch or {},
        )
        gate_acquired = False
        try:
            pre = self.preflight(spec.graph, spec.node_inventory_sha256)
            timing["preflight_s"] = round(self.clock() - t_start, 3)
            base.workflow_sha256 = pre["workflow_sha256"]
            base.node_inventory_sha256 = pre["node_inventory_sha256"]
            base.model_hashes = dict(spec.model_pins)

            if self.gate is not None:
                self.gate.acquire(stage_label=spec.stage_id)
                gate_acquired = True
            if self.lease is not None:
                self.lease.acquire(attempt_id=stage_input.attempt_id, prompt_id=None)

            if self.sampler is not None:
                self.sampler.start()
            t_submit = self.clock()
            prompt_id = self.submit(spec.graph)
            timing["submit_s"] = round(self.clock() - t_submit, 3)
            base.prompt_id = prompt_id

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
                    base.notes.append("prompt still present in /queue: still running, not a failure")
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
            return base
        except MfComfyError as exc:
            base.status = "unresolved" if isinstance(exc, AmbiguousAfterSubmit) else "failed"
            base.failure = exc.to_dict()
            base.timing = timing
            base.notes = list(self.notes)
            if self.sampler is not None:
                base.resources = self.sampler.stop()
            raise
        finally:
            if self.lease is not None:
                self.lease.release()
            if gate_acquired and self.gate is not None:
                self.gate.release()
