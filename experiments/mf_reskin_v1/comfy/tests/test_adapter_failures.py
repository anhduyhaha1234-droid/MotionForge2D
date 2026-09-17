"""Adapter tests (fake transport) for every required typed failure case.

These prove the ADAPTER contract only — not an engine. See packet §5.5.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fake_transport import CKPT, history_error, history_success, light_graph, make_rig, make_spec, png_bytes

from mf_comfy.errors import (
    AmbiguousAfterSubmit,
    ArtifactHashMismatch,
    BlindResubmitRefused,
    ExecutionError,
    InvalidGraph,
    LeaseNotHeld,
    MissingModel,
    MissingNode,
    OomFailure,
    PartialOutput,
    PathScopeViolation,
    ServerEpochChanged,
    TransportError,
)


# ------------------------------------------------------------------ happy path
def test_happy_path_reaches_validated(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    out = rig.adapter.run(make_spec())
    assert out.status == "validated"
    assert out.prompt_id == "pid-1"
    assert rig.transport.submit_calls == 1
    assert len(out.artifacts) == 1
    art = out.artifacts[0]
    assert art["decode_verified"] is True
    assert art["sha256"] == hashlib.sha256(png_bytes()).hexdigest()
    assert art["size_bytes"] == len(png_bytes())
    staged = Path(art["staged_path"])
    assert staged.exists()
    assert str(staged).startswith(str(rig.paths.root))
    assert not rig.lease.path.exists(), "lease must be released after the run"
    assert rig.gate is not None and rig.gate.held is False
    assert out.timing and "total_s" in out.timing
    assert "accepted" not in out.status and "published" not in out.status


def test_graph_is_never_silently_mutated(tmp_path):
    """C-A14: FPS/duration/resolution are never changed behind the caller's back."""
    rig = make_rig(tmp_path)
    graph = light_graph()
    before = json.dumps(graph, sort_keys=True)
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    rig.adapter.run(make_spec(graph=graph))
    assert json.dumps(graph, sort_keys=True) == before, "caller graph was mutated"
    assert json.dumps(rig.transport.last_graph, sort_keys=True) == before, "submitted graph differs"


# ------------------------------------------------------- missing node / model
def test_missing_node_is_typed_and_never_submits(tmp_path):
    rig = make_rig(tmp_path)
    graph = light_graph()
    graph["99"] = {"class_type": "TotallyMissingNode", "inputs": {}}
    with pytest.raises(MissingNode) as exc:
        rig.adapter.run(make_spec(graph=graph))
    assert exc.value.code == "MF_COMFY_MISSING_NODE"
    assert "TotallyMissingNode" in json.dumps(exc.value.details)
    assert rig.transport.submit_calls == 0


def test_missing_model_is_typed_and_never_submits(tmp_path):
    rig = make_rig(tmp_path)
    with pytest.raises(MissingModel) as exc:
        rig.adapter.run(make_spec(graph=light_graph(ckpt="absent_model.safetensors")))
    assert exc.value.code == "MF_COMFY_MISSING_MODEL"
    assert exc.value.details["value"] == "absent_model.safetensors"
    assert rig.transport.submit_calls == 0


# ---------------------------------------------------------------- invalid graph
def test_invalid_graph_unknown_upstream_link(tmp_path):
    rig = make_rig(tmp_path)
    graph = light_graph()
    graph["8"]["inputs"]["samples"] = ["42", 0]
    with pytest.raises(InvalidGraph) as exc:
        rig.adapter.run(make_spec(graph=graph))
    assert exc.value.code == "MF_COMFY_INVALID_GRAPH"
    assert rig.transport.submit_calls == 0


def test_invalid_graph_missing_required_input(tmp_path):
    rig = make_rig(tmp_path)
    graph = light_graph()
    del graph["6"]["inputs"]["text"]
    with pytest.raises(InvalidGraph) as exc:
        rig.adapter.run(make_spec(graph=graph))
    assert exc.value.details.get("input") == "text"
    assert rig.transport.submit_calls == 0


def test_invalid_graph_rejected_by_server(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.submit_exception = InvalidGraph("prompt rejected by server (prompt_outputs_failed_validation)",
                                                  node_errors={"3": {"errors": []}})
    with pytest.raises(InvalidGraph) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.code == "MF_COMFY_INVALID_GRAPH"
    assert rig.transport.submit_calls == 1


# --------------------------------------------------------- websocket behaviour
def test_ws_disconnect_then_reconnect_is_not_failure(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.drain_script = ["ws_disconnect", "ok", "ok"]
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    out = rig.adapter.run(make_spec())
    assert out.status == "validated"
    assert rig.transport.submit_calls == 1, "ws loss must not trigger a resubmit"
    assert any("ws disconnect" in n for n in rig.adapter.notes)


# ------------------------------------------------------------ restart / epoch
def test_server_restart_epoch_change_is_typed(tmp_path):
    rig = make_rig(tmp_path, stage_timeout_s=10.0)
    rig.transport.drain_hooks = [None, lambda i: rig.epoch.write("http://127.0.0.1:8199", "fake-0.0")]
    with pytest.raises(ServerEpochChanged) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.code == "MF_COMFY_SERVER_EPOCH_CHANGED"
    assert rig.transport.submit_calls == 1


def test_history_reset_without_epoch_proof_is_ambiguous(tmp_path):
    rig = make_rig(tmp_path, stage_timeout_s=2.0)
    with pytest.raises(AmbiguousAfterSubmit) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.code == "MF_COMFY_AMBIGUOUS_AFTER_SUBMIT"
    assert rig.transport.submit_calls == 1


# ------------------------------------------------------------- ambiguity rules
def test_ambiguous_after_submit_never_resubmits(tmp_path):
    rig = make_rig(tmp_path, stage_timeout_s=3.0, poll_s=1.0)
    with pytest.raises(AmbiguousAfterSubmit):
        rig.adapter.run(make_spec())
    assert rig.transport.submit_calls == 1, "blind resubmit detected"
    assert rig.adapter.reconcile_count >= 1, "ambiguity must be reconciled, not assumed"


def test_prompt_still_in_queue_is_unresolved_not_failure(tmp_path):
    rig = make_rig(tmp_path, stage_timeout_s=2.0)
    rig.transport.queue_state["queue_running"] = [["pid-1", "client", {}]]
    out = rig.adapter.run(make_spec())
    assert out.status == "unresolved"
    assert rig.transport.submit_calls == 1


def test_blind_resubmit_is_refused(tmp_path):
    rig = make_rig(tmp_path)
    rig.adapter.submit(light_graph())
    with pytest.raises(BlindResubmitRefused) as exc:
        rig.adapter.submit(light_graph())
    assert exc.value.code == "MF_COMFY_BLIND_RESUBMIT_REFUSED"
    assert rig.transport.submit_calls == 1


def test_submit_transport_error_is_ambiguous(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.submit_exception = TransportError("POST /prompt timed out")
    with pytest.raises(AmbiguousAfterSubmit) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.details.get("submit_attempted") is True
    assert rig.transport.submit_calls == 1


# ------------------------------------------------------------ artifact failure
def test_partial_suffix_rejected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1", filename="fake_out_00001_.png.partial")
    with pytest.raises(PartialOutput) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.code == "MF_COMFY_PARTIAL_OUTPUT"


def test_zero_byte_artifact_rejected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    rig.transport.view_payload = b""
    with pytest.raises(PartialOutput):
        rig.adapter.run(make_spec())


def test_undecodable_artifact_rejected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    rig.transport.view_payload = b"this is not a png"
    with pytest.raises(PartialOutput):
        rig.adapter.run(make_spec())


def test_history_without_artifacts_rejected(tmp_path):
    rig = make_rig(tmp_path)
    entry = history_success("pid-1")
    entry["outputs"] = {"9": {}}
    rig.transport.history_map["pid-1"] = entry
    from mf_comfy.errors import ArtifactMissing

    with pytest.raises(ArtifactMissing):
        rig.adapter.run(make_spec())


def test_artifact_hash_mismatch_detected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    spec = make_spec(expected_artifact_hashes={"fake_out_00001_.png": "0" * 64})
    with pytest.raises(ArtifactHashMismatch) as exc:
        rig.adapter.run(spec)
    assert exc.value.details["expected"] == "0" * 64
    assert exc.value.details["actual"] == hashlib.sha256(png_bytes()).hexdigest()


def test_temp_preview_artifact_is_not_publishable(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1", server_type="temp")
    from mf_comfy.errors import ArtifactMissing

    with pytest.raises(ArtifactMissing):
        rig.adapter.run(make_spec())


def test_path_escape_in_filename_rejected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1", filename="../../evil.png")
    with pytest.raises(PathScopeViolation):
        rig.adapter.run(make_spec())


def test_path_escape_in_subfolder_rejected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1", subfolder="../../../etc")
    with pytest.raises(PathScopeViolation):
        rig.adapter.run(make_spec())


def test_absolute_path_rejected(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_success("pid-1", filename="C:/windows/evil.png")
    with pytest.raises(PathScopeViolation):
        rig.adapter.run(make_spec())


# ------------------------------------------------------------- engine failures
def test_oom_is_typed(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_error(
        "pid-1", "torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB")
    with pytest.raises(OomFailure) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.code == "MF_COMFY_OOM"
    assert rig.transport.submit_calls == 1, "an OOM must not be retried silently"


def test_non_oom_execution_error_is_typed(tmp_path):
    rig = make_rig(tmp_path)
    rig.transport.history_map["pid-1"] = history_error("pid-1", "KeyError: 'vae'")
    with pytest.raises(ExecutionError) as exc:
        rig.adapter.run(make_spec())
    assert exc.value.code == "MF_COMFY_EXECUTION_ERROR"
    assert rig.transport.submit_calls == 1


# --------------------------------------------------------------- interrupt ACL
def test_interrupt_without_lease_is_refused(tmp_path):
    rig = make_rig(tmp_path)
    with pytest.raises(LeaseNotHeld) as exc:
        rig.adapter.interrupt("pid-1")
    assert exc.value.code == "MF_COMFY_LEASE_NOT_HELD"
    assert rig.transport.interrupt_calls == [], "no /interrupt HTTP call may be made"


def test_interrupt_for_foreign_prompt_is_refused(tmp_path):
    rig = make_rig(tmp_path)
    rig.lease.acquire(attempt_id="mine", prompt_id="pid-1")
    try:
        with pytest.raises(LeaseNotHeld):
            rig.adapter.interrupt("pid-FOREIGN")
        assert rig.transport.interrupt_calls == []
    finally:
        rig.lease.release()


def test_interrupt_allowed_for_own_prompt_under_lease(tmp_path):
    rig = make_rig(tmp_path)
    rig.lease.acquire(attempt_id="mine", prompt_id="pid-1")
    try:
        rig.adapter.interrupt("pid-1")
        assert rig.transport.interrupt_calls == ["pid-1"]
    finally:
        rig.lease.release()
