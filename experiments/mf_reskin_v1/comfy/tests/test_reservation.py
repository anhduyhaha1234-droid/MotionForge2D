"""F01 regression suite: a durable unresolved-prompt reservation.

F01 (P1) as reproduced by the reviewer on `9e57f3e`:

    prompt still in `/queue` -> `run()` returns `unresolved` -> the `finally`
    block released the lease AND the GPU gate -> a second stage acquired the
    gate while prompt #1 was still occupying the server.

The contract these tests enforce (packet §2C.1):

  a. a queued timeout blocks caller-2's gate acquisition, even after the byte
     lock itself is gone;
  b. a lost acknowledgement is adopted, never resubmitted;
  c. a client restart finds the same prompt (no duplicate output);
  d. a server reboot / epoch mismatch quarantines the record: foreign output is
     never adopted as ours and never reported as success;
  e. terminal success / terminal error / cancel / reconcile-to-completed each
     release the reservation exactly once;
  f. `/interrupt` is never sent for a foreign or unknown prompt.

NEGATIVE CONTROL. Every test here is written to be runnable against the pre-fix
preimage as well. On `9e57f3e` the typed refusal `UnresolvedReservation` does not
exist (the shim below stands in for it) and the ledger does not exist either, so
each test fails on an assertion. The pre/fix runs are kept as evidence in
`COMFY/raw/negative_control_open.txt` and
`COMFY/raw/negative_control_prefix.txt`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fake_transport import (history_error, history_success, make_rig, make_spec,
                            queue_item)
from mf_comfy.adapter import ComfyStageAdapter
from mf_comfy.errors import (
    AmbiguousAfterSubmit,
    LeaseNotHeld,
    MfComfyError,
    TransportError,
)
from mf_comfy.gpugate import GpuStageGate
from mf_comfy.lease import InstanceLease

try:  # present only on the fixed tree
    from mf_comfy.errors import UnresolvedReservation
except ImportError:  # pragma: no cover - pre-fix preimage only
    class UnresolvedReservation(MfComfyError):
        code = "MF_COMFY_UNRESOLVED_RESERVATION"


def _store(adapter):
    """The durable ledger. Missing attribute == pre-fix tree -> assertion failure."""
    store = getattr(adapter, "reservations", None)
    assert store is not None, "adapter exposes no durable reservation ledger"
    return store


def _simulate_process_exit(rig) -> None:
    """Model the death of the attempt's process.

    The OS drops the byte lock when the process dies and a restart reclaims the
    lease because `pid_alive()` is false; in-process we do both explicitly.
    """
    if rig.gate is not None and rig.gate.held:
        rig.gate.release()
    rig.lease.release()


def _receipts(rig, adapter=None):
    return _store(adapter or rig.adapter).receipts()


# --------------------------------------------------------------------- (a)
def test_f01_queued_timeout_blocks_second_stage_gate_acquisition(tmp_path):
    """The F01 core: unresolved prompt in /queue must keep the gate blocked."""
    rig = make_rig(tmp_path / "rig")
    # the reviewer's queue shape for this probe: [prompt_id, client, extra]
    rig.transport.queue_state["queue_running"] = [["pid-1", "client", {}]]

    res = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert res.status == "unresolved"
    assert rig.transport.submit_calls == 1

    store = _store(rig.adapter)
    pending = store.unresolved(rig.rec["instance_id"])
    assert len(pending) == 1, "an unprovable prompt must leave a durable reservation"
    assert pending[0]["prompt_id"] == "pid-1"
    assert Path(pending[0]["path"]).exists(), "reservation marker must exist on disk"

    # The byte lock is NOT the guarantee (it dies with the process). Drop it.
    rig.gate.release()
    second = GpuStageGate(tmp_path / "rig" / "gpu_stage.lock", timeout_s=0.0)
    try:
        with pytest.raises(UnresolvedReservation) as exc:
            second.acquire(stage_label="second-stage")
        assert exc.value.code == "MF_COMFY_UNRESOLVED_RESERVATION"
        assert exc.value.details["unresolved_count"] == 1
    finally:
        second.release()
    assert second.held is False, "caller-2 must not hold the gate"
    # still unresolved and still on disk after the refusal
    assert store.is_unresolved(rig.rec["instance_id"], pending[0]["attempt_id"]) is True


# --------------------------------------------------------------------- (b)
def test_f01_lost_acknowledgement_is_adopted_not_resubmitted(tmp_path):
    """A raced POST: the later attempt must adopt the landed prompt, POST once."""
    rig = make_rig(tmp_path / "rig")
    cid = rig.adapter.client_id
    rig.transport.submit_exception = TransportError("connection reset during POST")

    with pytest.raises(AmbiguousAfterSubmit):
        rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert rig.transport.submit_calls == 1

    store = _store(rig.adapter)
    pending = store.unresolved(rig.rec["instance_id"])
    assert len(pending) == 1
    assert pending[0]["prompt_id"] is None, "the acknowledgement was lost"

    # ...but the POST did land on the server, and later finished.
    rig.transport.submit_exception = None
    rig.transport.queue_state["queue_running"] = [queue_item("pid-9", cid)]
    rig.transport.history_map["pid-9"] = history_success("pid-9", "adopted_00001_.png")

    _simulate_process_exit(rig)
    rig2 = make_rig(rig.root, transport=rig.transport, write_epoch=False,
                    owner="restart-owner")
    out = rig2.adapter.run(make_spec(stage_timeout_s=2.0))

    assert rig.transport.submit_calls == 1, "a lost acknowledgement must never resubmit"
    assert out.prompt_id == "pid-9"
    assert out.adopted is True
    assert out.status == "validated"
    assert out.artifacts[0]["filename"] == "adopted_00001_.png"


# --------------------------------------------------------------------- (c)
def test_f01_client_restart_finds_the_same_prompt(tmp_path):
    """New process, same durable dir: same prompt_id, one output, one POST."""
    rig = make_rig(tmp_path / "rig")
    rig.transport.queue_state["queue_running"] = [
        queue_item("pid-1", rig.adapter.client_id)]
    res = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert res.status == "unresolved"
    assert rig.transport.submit_calls == 1

    _simulate_process_exit(rig)
    # while we were down, the prompt finished
    rig.transport.queue_state["queue_running"] = []
    rig.transport.history_map["pid-1"] = history_success("pid-1", "once_only_00001_.png")

    rig2 = make_rig(rig.root, transport=rig.transport, write_epoch=False,
                    owner="restart-owner")
    out = rig2.adapter.run(make_spec(stage_timeout_s=2.0))

    assert rig.transport.submit_calls == 1
    assert out.prompt_id == "pid-1"
    assert out.adopted is True
    assert out.status == "validated"
    staged = sorted(p.name for p in rig.paths.root.rglob("*.png"))
    assert staged == ["once_only_00001_.png"], f"duplicate/stray output: {staged}"


# --------------------------------------------------------------------- (d)
def test_f01_server_reboot_quarantines_and_never_adopts_foreign_output(tmp_path):
    """A new boot identity can never adopt the previous boot's output."""
    rig = make_rig(tmp_path / "rig")
    rig.transport.queue_state["queue_running"] = [["pid-1", "client", {}]]
    res = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert res.status == "unresolved"

    store = _store(rig.adapter)
    assert len(store.unresolved(rig.rec["instance_id"])) == 1
    _simulate_process_exit(rig)

    # server reboot: same host, same pid slot, NEW boot identity
    new_rec = rig.epoch.write("http://127.0.0.1:8199", "fake-0.0")
    assert new_rec["instance_id"] != rig.rec["instance_id"]

    # the old prompt did finish on the old boot: its artifact is foreign output
    rig.transport.queue_state["queue_running"] = []
    rig.transport.history_map["pid-1"] = history_success("pid-1", "foreign_00001_.png")
    rig.transport.history_map["pid-2"] = history_success("pid-2", "own_00001_.png")

    rig2 = make_rig(rig.root, transport=rig.transport, write_epoch=False,
                    owner="restart-owner")
    out = rig2.adapter.run(make_spec(stage_timeout_s=2.0))

    assert out.prompt_id == "pid-2", "the new boot must not report the old prompt"
    assert out.adopted is False
    assert out.status == "validated"
    assert out.artifacts[0]["filename"] == "own_00001_.png"
    assert not (rig.paths.root / "foreign_00001_.png").exists(), \
        "foreign output must never be staged as this attempt's result"
    # the old record is provably quarantined, not silently released as success
    quarantine = store.quarantined(rig.rec["instance_id"])
    assert len(quarantine) == 1
    assert quarantine[0]["quarantine_reason"] == "server_epoch_changed"
    assert store.unresolved(rig.rec["instance_id"]) == []
    assert all(r.get("prompt_id") != "pid-1" for r in store.receipts()), \
        "the quarantined record must never be released as our success"


# --------------------------------------------------------------------- (e)
def test_f01_terminal_success_releases_reservation_exactly_once(tmp_path):
    rig = make_rig(tmp_path / "rig")
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    out = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert out.status == "validated"
    assert rig.adapter.reservation_released is True

    store = _store(rig.adapter)
    receipts = store.receipts()
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "terminal_success"
    assert receipts[0]["release_count"] == 1
    assert out.reservation["exists"] is False, "a released reservation is provably gone"

    again = rig.adapter.close_reservation("terminal_success")
    assert again["released"] is False
    assert again["already_released"] is True
    assert again["release_count"] == 1
    assert len(store.receipts()) == 1, "no second release receipt"


def test_f01_terminal_error_releases_reservation_exactly_once(tmp_path):
    rig = make_rig(tmp_path / "rig")
    rig.transport.history_map["pid-1"] = history_error("pid-1", "CUDA out of memory")
    with pytest.raises(MfComfyError):
        rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert rig.adapter.reservation_released is True
    store = _store(rig.adapter)
    receipts = store.receipts()
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "terminal_error"
    assert receipts[0]["release_count"] == 1
    assert rig.adapter.reservation_state()["exists"] is False


def test_f01_cancel_releases_reservation_exactly_once(tmp_path):
    rig = make_rig(tmp_path / "rig")
    rig.transport.queue_state["queue_running"] = [
        queue_item("pid-1", rig.adapter.client_id)]
    res = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert res.status == "unresolved"
    assert rig.adapter.reservation_released is False

    # the real /interrupt lands, and the server records the terminal interrupt
    rig.transport.history_map["pid-1"] = history_error("pid-1", "execution_interrupted")
    rig.transport.queue_state["queue_running"] = []
    report = rig.adapter.cancel("pid-1")

    assert report["interrupt_count"] == 1
    assert rig.transport.interrupt_calls == ["pid-1"]
    assert report["reservation_released"] is True
    receipts = _store(rig.adapter).receipts()
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "cancelled"
    assert receipts[0]["release_count"] == 1


def test_f01_reconcile_to_completed_releases_reservation_exactly_once(tmp_path):
    """The timeout path reconciles to a terminal history entry, then releases once."""
    rig = make_rig(tmp_path / "rig")
    rig.transport.history_map["pid-1"] = history_success("pid-1", "late_00001_.png")
    # the /history reads raced during the wait (both drain iterations) and work
    # again by the time reconcile reads them.
    rig.transport.history_fail_calls = 2
    out = rig.adapter.run(make_spec(stage_timeout_s=2.0))

    assert rig.adapter.reconcile_count == 1, "the wait must time out first"
    assert out.status == "validated"
    assert out.artifacts[0]["filename"] == "late_00001_.png"
    assert rig.adapter.reservation_released is True
    receipts = _store(rig.adapter).receipts()
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "terminal_success"
    assert receipts[0]["release_count"] == 1


# --------------------------------------------------------------------- (f)
def test_f01_never_interrupts_a_foreign_prompt(tmp_path):
    """/interrupt stays lease-gated: a foreign prompt is never touched."""
    rig = make_rig(tmp_path / "rig")
    rig.transport.queue_state["queue_running"] = [["pid-1", "client", {}]]
    res = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert res.status == "unresolved"

    # 1) a lease that does not cover the running prompt cannot interrupt it
    rig.lease.release()
    intruder_lease = InstanceLease(rig.lease.dir, rig.rec["instance_id"], "intruder")
    intruder_lease.acquire(attempt_id="intruder", prompt_id="pid-someone-else")
    intruder = ComfyStageAdapter(rig.transport, rig.paths, lease=intruder_lease,
                                 epoch=rig.epoch)
    intruder.instance_epoch = rig.rec
    try:
        with pytest.raises(LeaseNotHeld):
            intruder.interrupt("pid-1")
        assert rig.transport.interrupt_calls == []
        assert intruder.interrupt_count == 0
        assert intruder.interrupt_refusals == 1
    finally:
        intruder_lease.release()

    # 2) a second stage refused by the reservation guard never interrupts either
    if rig.gate is not None and rig.gate.held:
        rig.gate.release()
    second = GpuStageGate(tmp_path / "rig" / "gpu_stage.lock", timeout_s=0.0)
    try:
        with pytest.raises(UnresolvedReservation):
            second.acquire(stage_label="second-stage")
    finally:
        second.release()
    assert rig.transport.interrupt_calls == []
    assert second.held is False


# ------------------------------------------------------- ledger unit behaviour
def test_reservation_release_is_exactly_once_even_when_racing(tmp_path):
    """Two releases of the same record: one receipt, release_count stays 1."""
    try:
        from mf_comfy.lease import PromptReservations
    except ImportError:  # pre-fix preimage: no durable ledger exists
        pytest.fail("mf_comfy.lease.PromptReservations missing (pre-fix tree)")

    store = PromptReservations(tmp_path / "res")
    rec = store.open({"instance_id": "inst-1", "host": "h", "base_url": "u"},
                     "attempt-1", stage_id="s", owner="o", client_id="c")
    rec = store.bind({"instance_id": "inst-1", "host": "h"}, "attempt-1", "pid-1")
    first = store.close(rec, "terminal_success", closer="a")
    second = store.close(rec, "terminal_success", closer="b")
    assert first["released"] is True and first["release_count"] == 1
    assert second["released"] is False and second["already_released"] is True
    assert second["release_count"] == 1
    assert len(store.receipts()) == 1
    assert store.unresolved("inst-1") == []
