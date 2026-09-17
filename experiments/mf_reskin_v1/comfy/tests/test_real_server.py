"""REAL-SERVER integration tests (ComfyUI 0.28.2 on 127.0.0.1:8199).

These are the engine-level checks: real HTTP semantics, real inference, real
`/interrupt`. They are skipped (not faked) when the task-local server is down —
a skipped test must never read as a pass.

Pinned facts come from `EV/raw/probe_capabilities.json` and
`EV/raw/probe_rejections.json` produced by this same task.
"""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import pytest

from mf_comfy.adapter import ComfyStageAdapter, RunSpec
from mf_comfy.errors import (
    AmbiguousAfterSubmit,
    InvalidGraph,
    LeaseNotHeld,
    MissingModel,
    MissingNode,
)
from mf_comfy.gpugate import GpuStageGate
from mf_comfy.lease import InstanceEpoch, InstanceLease
from mf_comfy.paths import StagePaths
from mf_comfy.pinning import hash_workflow, sha256_file
from mf_comfy.resources import ResourceSampler
from mf_comfy.transport import HttpTransport

BASE_URL = "http://127.0.0.1:8199"
RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\comfy")
EV = Path(r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\mf-reskin-v1\20260917T110554Z\COMFY")
WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "mf_light_sdxl_v1.json"
CKPT = RT / "models" / "checkpoints" / "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"

PINNED_NODE_INVENTORY_SHA = "52674207e277a8ba881ac39f38df21511a22d2129cbab4c2ef636fc890eef745"
PINNED_COMFYUI_VERSION = "0.28.2"
PINNED_DEVICE_VRAM_MIB = 12227
OBSERVATIONS = EV / "runs" / "real_server_observations.json"


def _server_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8199), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _server_up(), reason="task-local ComfyUI server not running")


def _obs(key: str, value) -> None:
    OBSERVATIONS.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(OBSERVATIONS.read_text(encoding="utf-8")) if OBSERVATIONS.exists() else {}
    data[key] = value
    OBSERVATIONS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def light_graph(ckpt="Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors", **over):
    w = over.get("width", 512)
    h = over.get("height", 512)
    steps = over.get("steps", 8)
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a brass lantern", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 99, "steps": steps, "cfg": 5.0, "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": over.get("prefix", "mf_real"), "images": ["8", 0]}},
    }


@pytest.fixture()
def transport():
    t = HttpTransport(BASE_URL, http_timeout_s=120)
    yield t
    t.close()


# --------------------------------------------------------------- real capability
def test_real_server_identity_matches_pins(transport):
    caps = transport.probe_capabilities()
    assert caps["comfyui_version"] == PINNED_COMFYUI_VERSION
    assert caps["device_total_vram_mib"] == PINNED_DEVICE_VRAM_MIB
    assert "5070" in caps["device_name"]
    assert caps["loopback_only"] is True
    assert caps["node_class_count"] > 500
    oi = transport.object_info()
    from mf_comfy.pinning import hash_node_inventory

    assert hash_node_inventory(oi) == PINNED_NODE_INVENTORY_SHA, "node inventory drifted"
    _obs("server_identity", caps)


def test_real_int_e2e_light_workflow(tmp_path, transport):
    """Real inference end to end: submit -> history -> validate -> contract."""
    epoch = InstanceEpoch(RT / "instance_epoch.json")
    rec = epoch.read()
    assert rec, "instance epoch file missing"
    paths = StagePaths(tmp_path / "stage")
    lease = InstanceLease(RT / "leases", instance_id=rec["instance_id"], owner="pytest-real")
    gate = GpuStageGate(RT / "leases" / "gpu_stage.lock", timeout_s=5.0)
    adapter = ComfyStageAdapter(transport, paths, lease=lease, gate=gate, epoch=epoch,
                                sampler=ResourceSampler(interval_s=0.25))
    adapter.instance_epoch = rec
    graph = light_graph(width=512, height=512, steps=8, prefix="mf_pytest_real")
    spec = RunSpec(stage_id="pytest_real", workflow_id="mf_light_sdxl_v1", graph=graph,
                   workflow_sha256=hash_workflow(graph),
                   node_inventory_sha256=PINNED_NODE_INVENTORY_SHA,
                   model_pins={CKPT.name: sha256_file(CKPT)} if CKPT.exists() else {},
                   stage_timeout_s=300.0, poll_s=1.0)
    out = adapter.run(spec)
    assert out.status == "validated"
    assert adapter.submit_count == 1
    assert out.node_inventory_sha256 == PINNED_NODE_INVENTORY_SHA
    art = out.artifacts[0]
    assert art["decode_verified"] is True
    assert art["width"] == 512 and art["height"] == 512
    assert Path(art["staged_path"]).exists()
    assert str(art["staged_path"]).startswith(str(paths.root))
    assert out.resources["measured"] is True
    assert out.resources["peak_vram_used_mib"] is not None
    _obs("pytest_real_run", {"prompt_id": out.prompt_id, "timing": out.timing,
                             "resources": out.resources,
                             "artifact_sha256": art["sha256"],
                             "artifact_size": art["size_bytes"]})


def test_real_invalid_node_inventory_pin_is_refused(transport, tmp_path):
    adapter = ComfyStageAdapter(transport, StagePaths(tmp_path / "s"))
    graph = light_graph()
    with pytest.raises(Exception) as exc:
        adapter.preflight(graph, node_inventory_sha256="0" * 64)
    assert getattr(exc.value, "code", "") == "MF_COMFY_NODE_INVENTORY_MISMATCH"


# ------------------------------------------------- real rejection classification
def test_real_unknown_node_class_is_missing_node(transport):
    g = light_graph()
    g["99"] = {"class_type": "MfDefinitelyMissingNode", "inputs": {"x": 1}}
    with pytest.raises(MissingNode) as exc:
        transport.submit(g, "pytest-missing-node")
    assert exc.value.code == "MF_COMFY_MISSING_NODE"
    assert "missing_node_type" in json.dumps(exc.value.details)


def test_real_absent_checkpoint_is_missing_model(transport):
    with pytest.raises(MissingModel) as exc:
        transport.submit(light_graph(ckpt="mf_absent_model.safetensors"), "pytest-missing-model")
    assert exc.value.code == "MF_COMFY_MISSING_MODEL"
    assert "value_not_in_list" in json.dumps(exc.value.details)


def test_real_missing_required_input_is_invalid_graph(transport):
    g = light_graph()
    del g["6"]["inputs"]["text"]
    with pytest.raises(InvalidGraph) as exc:
        transport.submit(g, "pytest-invalid")
    assert exc.value.code == "MF_COMFY_INVALID_GRAPH"


def test_real_empty_graph_is_invalid_graph(transport):
    with pytest.raises(InvalidGraph):
        transport.submit({}, "pytest-empty")


def test_real_unknown_history_is_empty_not_success(transport):
    """An unknown prompt must yield NO proof — never a fabricated success."""
    assert transport.history("00000000-0000-0000-0000-000000000000") == {}


# ---------------------------------------------------------- real interrupt lease
def test_real_interrupt_refused_without_lease_and_works_with_lease(transport):
    epoch = InstanceEpoch(RT / "instance_epoch.json")
    rec = epoch.read()
    lease = InstanceLease(RT / "leases", instance_id=rec["instance_id"], owner="pytest-interrupt")
    adapter = ComfyStageAdapter(transport, StagePaths(RT / "comfy-output" / "interrupt_probe"),
                               lease=lease, epoch=epoch)
    adapter.instance_epoch = rec

    long_graph = light_graph(width=1024, height=1024, steps=150, prefix="mf_pytest_interrupt")
    res = transport.submit(long_graph, "pytest-interrupt")
    pid = res.prompt_id
    try:
        # wait until the server is actually executing it
        running = False
        for _ in range(40):
            q = transport.queue() or {}
            blob = json.dumps(q)
            if pid in blob:
                running = True
                break
            time.sleep(0.5)
        assert running, "long prompt never appeared in /queue"

        # 1) foreign / unleased interrupt must be refused locally, with no HTTP call
        with pytest.raises(LeaseNotHeld):
            adapter.interrupt(pid)
        assert adapter.interrupt_refusals == 1
        assert transport.queue() and pid in json.dumps(transport.queue()), \
            "prompt must still be running after a refused interrupt"

        # 2) with the exclusive lease bound to THIS prompt, the real /interrupt works
        lease.acquire(attempt_id="pytest", prompt_id=pid)
        adapter.lease = lease
        adapter.interrupt(pid)
        assert adapter.interrupt_count == 1

        stopped = False
        for _ in range(40):
            if pid not in json.dumps(transport.queue() or {}):
                stopped = True
                break
            time.sleep(0.5)
        assert stopped, "prompt still queued after a real /interrupt"
        _obs("interrupt_probe", {"prompt_id": pid, "refused_without_lease": True,
                                 "interrupted_with_lease": True,
                                 "history_after_interrupt": transport.history(pid)})
    finally:
        # No blind cleanup interrupt: cancelling is only ever done for a prompt we
        # hold the lease for, and this test already proves the stop above.
        lease.release()
