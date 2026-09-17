"""Unit tests: path scoping, lease/epoch, GPU gate, pinning, transport boundaries."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fake_transport import minimal_object_info

from mf_comfy.errors import (
    GpuStageBusy,
    LeaseConflict,
    LeaseNotHeld,
    ModelPinMismatch,
    NodeInventoryPinMismatch,
    NonLoopbackEndpoint,
    OomFailure,
    PathScopeViolation,
    WorkflowPinMismatch,
    WsDisconnected,
    classify_execution_message,
)
from mf_comfy.gpugate import GpuStageGate
from mf_comfy.lease import InstanceEpoch, InstanceLease, pid_alive
from mf_comfy.paths import StagePaths
from mf_comfy.pinning import (
    hash_node_inventory,
    hash_workflow,
    verify_model_pins,
    verify_node_inventory_pin,
    verify_workflow_pin,
)
from mf_comfy.transport import HttpTransport, parse_base_url


# ------------------------------------------------------------------- loopback
@pytest.mark.parametrize("url", ["http://192.168.1.5:8188", "http://comfy.example.com:8188",
                                 "https://10.0.0.9:8188"])
def test_non_loopback_endpoint_refused(url):
    with pytest.raises(NonLoopbackEndpoint) as exc:
        parse_base_url(url)
    assert exc.value.code == "MF_COMFY_NON_LOOPBACK"
    with pytest.raises(NonLoopbackEndpoint):
        HttpTransport(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8199", "http://localhost:8199"])
def test_loopback_endpoint_accepted(url):
    t = HttpTransport(url)
    assert t.base_url.startswith("http://")


def test_non_http_scheme_refused():
    with pytest.raises(NonLoopbackEndpoint):
        parse_base_url("file:///etc/passwd")


# ---------------------------------------------------------------- path scoping
def test_stage_paths_accepts_nested_relative(tmp_path):
    p = StagePaths(tmp_path / "stage")
    out = p.resolve("a.png", "sub/dir")
    assert str(out).startswith(str(p.root))
    assert out.parent.exists() is False  # resolution must not create anything


@pytest.mark.parametrize("filename,subfolder", [
    ("../../evil.png", ""),
    ("..\\..\\evil.png", ""),
    ("C:/evil.png", ""),
    ("//server/share/evil.png", ""),
    ("ok.png", "../../../etc"),
    ("ok.png", "C:/tmp"),
])
def test_stage_paths_rejects_escape(tmp_path, filename, subfolder):
    p = StagePaths(tmp_path / "stage")
    with pytest.raises(PathScopeViolation) as exc:
        p.resolve(filename, subfolder)
    assert exc.value.code == "MF_COMFY_PATH_SCOPE_VIOLATION"


def test_stage_paths_assert_inside(tmp_path):
    p = StagePaths(tmp_path / "stage")
    with pytest.raises(PathScopeViolation):
        p.assert_inside(tmp_path / "outside.png")


# ------------------------------------------------------------------ lease/epoch
def test_pid_alive_self_true_and_unknown_pid_false():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(999999) is False


def test_lease_conflict_for_live_holder(tmp_path):
    rec = InstanceEpoch(tmp_path / "epoch.json").write("http://127.0.0.1:8199", "t")
    a = InstanceLease(tmp_path / "leases", rec["instance_id"], "owner-a")
    b = InstanceLease(tmp_path / "leases", rec["instance_id"], "owner-b")
    a.acquire(attempt_id="a1", prompt_id="pid-a")
    try:
        with pytest.raises(LeaseConflict) as exc:
            b.acquire(attempt_id="b1")
        assert exc.value.code == "MF_COMFY_LEASE_CONFLICT"
    finally:
        a.release()


def test_stale_lease_from_dead_process_is_reclaimed(tmp_path):
    rec = InstanceEpoch(tmp_path / "epoch.json").write("http://127.0.0.1:8199", "t")
    holder = InstanceLease(tmp_path / "leases", rec["instance_id"], "owner-a")
    path = holder.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"instance_id": rec["instance_id"], "pid": 999999,
                                "owner": "dead", "token": "x", "acquired_at": time.time(),
                                "ttl_s": 3600}), encoding="utf-8")
    b = InstanceLease(tmp_path / "leases", rec["instance_id"], "owner-b")
    b.acquire(attempt_id="b1")
    assert json.loads(path.read_text(encoding="utf-8"))["owner"] == "owner-b"
    b.release()


def test_lease_assert_held_for_prompt_and_epoch(tmp_path):
    rec = InstanceEpoch(tmp_path / "epoch.json").write("http://127.0.0.1:8199", "t")
    lease = InstanceLease(tmp_path / "leases", rec["instance_id"], "owner-a")
    lease.acquire(attempt_id="a1", prompt_id="pid-a")
    try:
        lease.assert_held_for("pid-a", epoch=rec)
        with pytest.raises(LeaseNotHeld):
            lease.assert_held_for("pid-OTHER", epoch=rec)
        with pytest.raises(LeaseNotHeld):
            lease.assert_held_for("pid-a", epoch={"instance_id": "different"})
    finally:
        lease.release()
    with pytest.raises(LeaseNotHeld):
        lease.assert_held_for("pid-a", epoch=rec)


def test_instance_epoch_matches_detects_restart(tmp_path):
    ep = InstanceEpoch(tmp_path / "epoch.json")
    first = ep.write("http://127.0.0.1:8199", "t")
    assert ep.matches(first) is True
    second = ep.write("http://127.0.0.1:8199", "t")
    assert second["instance_id"] != first["instance_id"]
    assert ep.matches(first) is False


# -------------------------------------------------------------------- GPU gate
def test_gpu_gate_refuses_second_concurrent_stage(tmp_path):
    lock = tmp_path / "gpu.lock"
    first = GpuStageGate(lock, timeout_s=0.0)
    second = GpuStageGate(lock, timeout_s=0.0)
    first.acquire(stage_label="stage-1")
    try:
        with pytest.raises(GpuStageBusy) as exc:
            second.acquire(stage_label="stage-2")
        assert exc.value.code == "MF_COMFY_GPU_STAGE_BUSY"
        assert exc.value.details["holder"]["stage_label"] == "stage-1"
    finally:
        first.release()
    second.acquire(stage_label="stage-2")
    assert second.held is True
    second.release()


def test_gpu_gate_context_manager_releases(tmp_path):
    gate = GpuStageGate(tmp_path / "gpu.lock", timeout_s=0.0)
    with gate.heavy_stage("s"):
        assert gate.held is True
    assert gate.held is False
    other = GpuStageGate(tmp_path / "gpu.lock", timeout_s=0.0)
    other.acquire("s2")
    other.release()


# --------------------------------------------------------------------- pinning
def test_workflow_hash_is_stable_and_change_sensitive():
    g = {"1": {"class_type": "A", "inputs": {"x": 1}}}
    h = hash_workflow(g)
    assert h == hash_workflow(json.loads(json.dumps(g)))
    assert h != hash_workflow({"1": {"class_type": "A", "inputs": {"x": 2}}})
    verify_workflow_pin(g, h)
    with pytest.raises(WorkflowPinMismatch) as exc:
        verify_workflow_pin(g, "0" * 64)
    assert exc.value.code == "MF_COMFY_WORKFLOW_HASH_MISMATCH"


def test_node_inventory_hash_tracks_capability_not_docs():
    oi = minimal_object_info()
    h = hash_node_inventory(oi)
    verify_node_inventory_pin(oi, h)
    with pytest.raises(NodeInventoryPinMismatch):
        verify_node_inventory_pin(oi, "f" * 64)
    # cosmetic churn must NOT change the inventory hash
    oi2 = json.loads(json.dumps(oi))
    oi2["KSampler"]["description"] = "docs only"
    oi2["KSampler"]["category"] = "sampling"
    assert hash_node_inventory(oi2) == h
    # capability change MUST change it
    oi3 = json.loads(json.dumps(oi))
    oi3["KSampler"]["input"]["required"]["new_knob"] = ["INT", {}]
    assert hash_node_inventory(oi3) != h


def test_model_pin_verification(tmp_path):
    p = tmp_path / "m.bin"
    p.write_bytes(b"weights")
    import hashlib

    good = hashlib.sha256(b"weights").hexdigest()
    verify_model_pins({"m.bin": good}, {"m.bin": good})
    with pytest.raises(ModelPinMismatch) as exc:
        verify_model_pins({"m.bin": good}, {"m.bin": "0" * 64})
    assert exc.value.code == "MF_COMFY_MODEL_HASH_MISMATCH"


# ------------------------------------------------------------------- failure map
@pytest.mark.parametrize("text,expected", [
    ("CUDA out of memory. Tried to allocate", "MF_COMFY_OOM"),
    ("torch.cuda.OutOfMemoryError: ...", "MF_COMFY_OOM"),
    ("KeyError: 'model'", "MF_COMFY_EXECUTION_ERROR"),
    ('[["execution_interrupted", {"prompt_id": "x", "node_id": "3"}]]', "MF_COMFY_EXECUTION_INTERRUPTED"),
])
def test_execution_message_classification(text, expected):
    assert classify_execution_message(text).code == expected


def test_oom_class_is_typed_instance():
    assert isinstance(classify_execution_message("out of memory"), OomFailure)


# --------------------------------------------------------- websocket transport
class FakeWs:
    def __init__(self, script):
        self.script = list(script)

    def settimeout(self, _t):
        return None

    def recv(self):
        from websocket import WebSocketTimeoutException

        if not self.script:
            raise WebSocketTimeoutException("drained")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        return None


def _ws_connector_factory(scripts):
    state = {"i": 0}

    def connector(_url):
        i = min(state["i"], len(scripts) - 1)
        state["i"] += 1
        return FakeWs(scripts[i])

    return connector


def test_ws_drop_then_reconnect_recovers_events():
    from websocket import WebSocketConnectionClosedException

    scripts = [[WebSocketConnectionClosedException("dropped")], ['{"type":"status"}']]
    t = HttpTransport("http://127.0.0.1:8199", ws_reconnect_attempts=3,
                      ws_connector=_ws_connector_factory(scripts))
    events = t.drain_events("cid", 2.0)
    assert t.ws_disconnects == 1
    assert t.ws_reconnects == 1
    assert any(e.get("type") == "mf_ws_reconnect" for e in events)
    assert any(e.get("type") == "status" for e in events)


def test_ws_exhausted_reconnect_raises_typed_disconnect():
    from websocket import WebSocketConnectionClosedException

    scripts = [[WebSocketConnectionClosedException("drop1")],
               [WebSocketConnectionClosedException("drop2")]]
    t = HttpTransport("http://127.0.0.1:8199", ws_reconnect_attempts=0,
                      ws_connector=_ws_connector_factory(scripts))
    with pytest.raises(WsDisconnected) as exc:
        t.drain_events("cid", 0.2)
    assert exc.value.code == "MF_COMFY_WS_DISCONNECT"
