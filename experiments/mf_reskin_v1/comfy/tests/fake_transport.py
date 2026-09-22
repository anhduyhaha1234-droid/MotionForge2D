"""In-memory fake transport + clock for adapter tests.

IMPORTANT (packet §5.5): these tests exercise the ADAPTER only. They are not
engine proof. Engine proof is the real-server run in `EV/runs/light_sdxl_v1.run.json`.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

from mf_comfy.adapter import ComfyStageAdapter, RunSpec
from mf_comfy.errors import WsDisconnected
from mf_comfy.gpugate import GpuStageGate
from mf_comfy.lease import InstanceEpoch, InstanceLease
from mf_comfy.paths import StagePaths
from mf_comfy.resources import NullSampler
from mf_comfy.transport import SubmitResult

CKPT = "model_a.safetensors"


def png_bytes(w: int = 8, h: int = 8, color=(120, 80, 40)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def minimal_object_info(ckpts=(CKPT,)) -> dict:
    return {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": [list(ckpts)]}},
            "output": ["MODEL", "CLIP", "VAE"],
            "output_node": False,
            "python_module": "nodes",
        },
        "EmptyLatentImage": {
            "input": {"required": {"width": ["INT", {}], "height": ["INT", {}],
                                   "batch_size": ["INT", {}]}},
            "output": ["LATENT"], "output_node": False, "python_module": "nodes",
        },
        "CLIPTextEncode": {
            "input": {"required": {"text": ["STRING", {}], "clip": ["CLIP", {}]}},
            "output": ["CONDITIONING"], "output_node": False, "python_module": "nodes",
        },
        "KSampler": {
            "input": {"required": {
                "seed": ["INT", {}], "steps": ["INT", {}], "cfg": ["FLOAT", {}],
                "sampler_name": [["euler", "dpmpp_2m"], {}], "scheduler": [["normal"], {}],
                "denoise": ["FLOAT", {}], "model": ["MODEL", {}],
                "positive": ["CONDITIONING", {}], "negative": ["CONDITIONING", {}],
                "latent_image": ["LATENT", {}]}},
            "output": ["LATENT"], "output_node": False, "python_module": "nodes",
        },
        "VAEDecode": {
            "input": {"required": {"samples": ["LATENT", {}], "vae": ["VAE", {}]}},
            "output": ["IMAGE"], "output_node": False, "python_module": "nodes",
        },
        "SaveImage": {
            "input": {"required": {"filename_prefix": ["STRING", {}], "images": ["IMAGE", {}]}},
            "output": ["IMAGE"], "output_node": True, "python_module": "nodes",
        },
    }


def light_graph(ckpt: str = CKPT, seed: int = 42, prefix: str = "fake_out") -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "b", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 1, "cfg": 1.0, "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }


def history_success(prompt_id: str, filename: str = "fake_out_00001_.png",
                    subfolder: str = "", server_type: str = "output",
                    client_id: str | None = None) -> dict:
    return {
        "prompt": [0, prompt_id, {},
                   ({"client_id": client_id} if client_id else {}), []],
        "outputs": {"9": {"images": [{"filename": filename, "subfolder": subfolder,
                                      "type": server_type}]}},
        "status": {"status_str": "success", "completed": True, "messages": []},
    }


def queue_item(prompt_id: str, client_id: str | None = None, number: int = 0) -> list:
    """`/queue` item shape of the pinned server: [number, prompt_id, prompt, extra_data, outputs]."""
    return [number, prompt_id, {}, ({"client_id": client_id} if client_id else {}), []]


def history_error(prompt_id: str, text: str) -> dict:
    return {
        "prompt": [0, prompt_id, {}, {}, []],
        "outputs": {},
        "status": {
            "status_str": "error",
            "completed": False,
            "messages": [["execution_error", {"node_id": "3", "node_type": "KSampler",
                                              "exception_message": text,
                                              "traceback": [text]}]],
        },
    }


class FakeClock:
    def __init__(self, step: float = 0.5) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float | None = None) -> None:
        self.t += self.step if dt is None else float(dt)


class FakeTransport:
    """Same surface as HttpTransport, driven by explicit scenario knobs."""

    def __init__(self, object_info: dict | None = None, time_advancer=None,
                 history_delay_drains: int = 0) -> None:
        self.oi = object_info if object_info is not None else minimal_object_info()
        self.time_advancer = time_advancer
        self.history_delay_drains = history_delay_drains
        self.history_map: dict = {}
        self.queue_state = {"queue_running": [], "queue_pending": []}
        self.submit_calls = 0
        self.interrupt_calls: list = []
        self.drain_calls = 0
        self.submit_exception: Exception | None = None
        self.submit_hook = None  # callable(client_id): rendezvous at the real POST
        self.drain_script: list = []
        self.drain_hooks: list = []
        self.view_payload: bytes = png_bytes()
        self.view_items: dict = {}
        self.last_graph: dict | None = None
        # number of upcoming history() calls that must fail (models a raced read)
        self.history_fail_calls = 0
        self.capabilities = {"comfyui_version": "fake-0.0", "history_direct_endpoint": True,
                            "device_total_vram_mib": 12227}

    # -- transport surface --
    def system_stats(self) -> dict:
        return {"system": {"comfyui_version": "fake-0.0", "python_version": "3.11",
                           "os": "test"},
                "devices": [{"name": "fake-gpu", "vram_total": 12227 * 1024 * 1024}]}

    def object_info(self) -> dict:
        return self.oi

    def probe_capabilities(self, object_info=None) -> dict:
        self.capabilities = dict(self.capabilities)
        self.capabilities["node_class_count"] = len(self.oi)
        return self.capabilities

    def submit(self, graph: dict, client_id: str) -> SubmitResult:
        self.submit_calls += 1
        self.last_graph = graph
        # A rendezvous point at the REAL POST: the F01 probe parks caller-1 inside
        # the POST so a second live caller can try to release its reservation.
        if self.submit_hook is not None:
            self.submit_hook(client_id)
        if self.submit_exception is not None:
            raise self.submit_exception
        return SubmitResult(prompt_id=f"pid-{self.submit_calls}", number=self.submit_calls)

    def history(self, prompt_id: str = "") -> dict:
        if self.history_fail_calls > 0:
            self.history_fail_calls -= 1
            from mf_comfy.errors import TransportError

            raise TransportError("simulated raced /history read", prompt_id=prompt_id)
        if not prompt_id:
            return dict(self.history_map)
        if self.drain_calls < self.history_delay_drains:
            return {}
        entry = self.history_map.get(prompt_id)
        return {prompt_id: entry} if entry else {}

    def queue(self) -> dict:
        return self.queue_state

    def interrupt(self, prompt_id: str) -> dict:
        self.interrupt_calls.append(prompt_id)
        return {"ok": True}

    def fetch_view(self, item: dict) -> bytes:
        key = (item.get("subfolder", ""), item.get("filename", ""))
        return self.view_items.get(key, self.view_payload)

    def drain_events(self, client_id: str, timeout_s: float) -> list:
        self.drain_calls += 1
        if self.time_advancer is not None:
            self.time_advancer(timeout_s)
        mode = self.drain_script[self.drain_calls - 1] if self.drain_calls - 1 < len(self.drain_script) else "ok"
        hook = self.drain_hooks[self.drain_calls - 1] if self.drain_calls - 1 < len(self.drain_hooks) else None
        if hook is not None:
            hook(self.drain_calls)
        if mode == "ws_disconnect":
            raise WsDisconnected("simulated websocket drop")
        return []

    def close(self) -> None:
        return None


@dataclass
class Rig:
    adapter: ComfyStageAdapter
    transport: FakeTransport
    epoch: InstanceEpoch
    rec: dict
    lease: InstanceLease
    gate: GpuStageGate | None
    paths: StagePaths
    clock: FakeClock
    root: Path


def make_rig(tmp_path: Path, *, graph: dict | None = None, oi: dict | None = None,
             stage_timeout_s: float = 5.0, poll_s: float = 1.0,
             gate_timeout_s: float = 0.0, with_gate: bool = True,
             history_delay_drains: int = 0, clock_step: float = 1.0,
             lock_path: Path | None = None, epoch_path: Path | None = None,
             lease_dir: Path | None = None, owner: str = "test-owner",
             client_id: str | None = None, transport: FakeTransport | None = None,
             write_epoch: bool = True) -> Rig:
    """Build one adapter against a task-local layout.

    `lock_path` / `epoch_path` / `lease_dir` / `transport` / `write_epoch` are
    overridable so a test can build a SECOND rig that shares the first rig's
    lock, epoch and server state — i.e. a simulated process restart over the same
    durable dirs, without minting a new boot identity.
    """
    clock = FakeClock(step=clock_step)
    if transport is None:
        transport = FakeTransport(object_info=oi, time_advancer=clock.advance,
                                  history_delay_drains=history_delay_drains)
    else:
        transport.time_advancer = clock.advance
    paths = StagePaths(tmp_path / "stage")
    epoch = InstanceEpoch(epoch_path or (tmp_path / "instance_epoch.json"))
    rec = epoch.write("http://127.0.0.1:8199", "fake-0.0") if write_epoch else epoch.read()
    lease = InstanceLease(lease_dir or (tmp_path / "leases"), rec["instance_id"], owner)
    gate = GpuStageGate(lock_path or (tmp_path / "gpu_stage.lock"),
                        timeout_s=gate_timeout_s) if with_gate else None
    adapter = ComfyStageAdapter(transport, paths, lease=lease, gate=gate, epoch=epoch,
                                clock=clock, sleep=clock.advance, sampler=NullSampler(),
                                owner=owner, client_id=client_id)
    adapter.instance_epoch = rec
    return Rig(adapter=adapter, transport=transport, epoch=epoch, rec=rec, lease=lease,
               gate=gate, paths=paths, clock=clock, root=tmp_path)


def make_spec(graph: dict | None = None, **kw) -> RunSpec:
    # `stage_id` / `workflow_id` / `graph` are overridable so a caller can model a
    # *different* stage/workflow/graph (the F02 identity variants).
    kw.setdefault("stage_timeout_s", 5.0)
    kw.setdefault("poll_s", 1.0)
    kw.setdefault("stage_id", "t")
    kw.setdefault("workflow_id", "wf_fake")
    kw.setdefault("graph", graph or light_graph())
    return RunSpec(**kw)


def write_epoch(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
