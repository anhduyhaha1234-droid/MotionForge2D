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
    # F02: the resume must declare the SAME work-item identity (attempt + owner)
    # as the attempt whose acknowledgement was lost.
    ident = {"attempt_id": "attempt-lost-ack", "owner": "restart-owner"}
    rig.transport.submit_exception = TransportError("connection reset during POST")

    with pytest.raises(AmbiguousAfterSubmit):
        rig.adapter.run(make_spec(**ident, stage_timeout_s=2.0))
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
    out = rig2.adapter.run(make_spec(**ident, stage_timeout_s=2.0))

    assert rig.transport.submit_calls == 1, "a lost acknowledgement must never resubmit"
    assert out.prompt_id == "pid-9"
    assert out.adopted is True
    assert out.status == "validated"
    assert out.artifacts[0]["filename"] == "adopted_00001_.png"


# --------------------------------------------------------------------- (c)
def test_f01_client_restart_finds_the_same_prompt(tmp_path):
    """New process, same durable dir: same prompt_id, one output, one POST."""
    rig = make_rig(tmp_path / "rig")
    ident = {"attempt_id": "attempt-restart", "owner": "restart-owner"}
    rig.transport.queue_state["queue_running"] = [
        queue_item("pid-1", rig.adapter.client_id)]
    res = rig.adapter.run(make_spec(**ident, stage_timeout_s=2.0))
    assert res.status == "unresolved"
    assert rig.transport.submit_calls == 1

    _simulate_process_exit(rig)
    # while we were down, the prompt finished
    rig.transport.queue_state["queue_running"] = []
    rig.transport.history_map["pid-1"] = history_success("pid-1", "once_only_00001_.png")

    rig2 = make_rig(rig.root, transport=rig.transport, write_epoch=False,
                    owner="restart-owner")
    out = rig2.adapter.run(make_spec(**ident, stage_timeout_s=2.0))

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


# ================================ R28 receipt supersession (R27-6-F1, lease.py)
# The slot holds exactly ONE receipt. R28 makes exactly ONE replacement legal: the
# terminal receipt of the retry that a PROVABLY never-submitted release authorised.
# Every other second write is refused with an existing typed error and moves not a
# single byte of the recorded evidence.
def _r28_slot(tmp_path, attempt: str):
    """A real never-submitted release receipt for one (instance, attempt) slot."""
    from mf_comfy.lease import PromptReservations, canonical_digest

    store = PromptReservations(Path(tmp_path) / "res")
    epoch = {"instance_id": "inst-r28", "host": "h-r28", "base_url": "u"}
    identity = {"source_sha256": "a" * 64}
    contract = {"nodes": {"9": {"kind": "images", "media_type": "image"}}}
    fields = {"stage_id": "t", "owner": "o-r28", "client_id": "c-orphan",
              "workflow_id": "wf", "workflow_sha256": "b" * 64,
              "input_digest": canonical_digest(identity), "input_identity": identity,
              "output_contract": contract,
              "output_contract_digest": canonical_digest(contract)}
    rec = store.open(epoch, attempt, note="orphan fixture: opened, POST never attempted",
                     **fields)
    release = store.close(rec, "not_accepted", closer="orphan")
    assert release["released"] is True and release["release_count"] == 1
    return store, epoch, fields, release


def _r28_retry_marker(store, epoch, attempt, fields, prompt_id: str = "pid-9", **overrides):
    """The retry's own marker for the SAME attempt, bound to the prompt it POSTed."""
    options = dict(fields)
    options.pop("client_id", None)
    options.update(overrides)
    rec = store.open(epoch, attempt, client_id="c-retry",
                     note="retry after a legal never-submitted release", **options)
    assert rec.get("created") is not False
    return store.bind(epoch, attempt, prompt_id)


def test_r28_release_supersession_rejects_unsafe_receipt(tmp_path):
    """Wrong identity / unreadable / already-terminal receipts are never replaced."""
    from mf_comfy.errors import (AttemptAlreadyTerminal, CorruptReservation,
                                 ReservationConflict)

    artifacts = [{"filename": "x.png", "sha256": "d" * 64, "size_bytes": 4,
                  "staged_path": str(Path(tmp_path) / "x.png")}]
    checks: dict = {}

    # (a) WRONG IDENTITY: the incoming close is not the work item the release freed.
    store, epoch, fields, release = _r28_slot(tmp_path / "a", "attempt-wrong-identity")
    receipt = Path(release["closed_path"])
    before = receipt.read_bytes()
    marker = _r28_retry_marker(store, epoch, "attempt-wrong-identity", fields, owner="intruder")
    with pytest.raises(ReservationConflict) as bogus_identity:
        store.close(marker, "terminal_success", closer="intruder",
                    evidence={"artifacts": artifacts}, attempt_supersession=True)
    checks["wrong_identity.refusal_code"] = bogus_identity.value.code
    checks["wrong_identity.supersession_typed"] = (
        bogus_identity.value.to_dict()["details"]["supersession"])
    assert receipt.read_bytes() == before, "the recorded release must not move a byte"
    assert len(store.receipts()) == 1
    assert store.receipts()[0]["outcome"] == "not_accepted"
    assert store.receipts()[0]["prompt_id"] is None
    assert Path(marker["path"]).exists(), "the refused caller's marker stays as evidence"

    # (b) UNREADABLE RECEIPT: unknown state is never overwritten.
    store, epoch, fields, release = _r28_slot(tmp_path / "b", "attempt-unreadable")
    receipt = Path(release["closed_path"])
    receipt.write_bytes(b'{"schema": "mf.comfy.prompt_reservation/1", "key": "trunc')
    unreadable = receipt.read_bytes()
    marker = _r28_retry_marker(store, epoch, "attempt-unreadable", fields)
    with pytest.raises(CorruptReservation) as bogus_unreadable:
        store.close(marker, "terminal_success", closer="x",
                    evidence={"artifacts": artifacts}, attempt_supersession=True)
    checks["unreadable.refusal_code"] = bogus_unreadable.value.code
    checks["unreadable.refusal"] = bogus_unreadable.value.to_dict()["details"]["refusal"]
    assert receipt.read_bytes() == unreadable, "unreadable bytes are preserved verbatim"

    # (c) ALREADY TERMINAL, and the SAME terminal fact stays exactly-once.
    store, epoch, fields, release = _r28_slot(tmp_path / "c", "attempt-terminal")
    marker = _r28_retry_marker(store, epoch, "attempt-terminal", fields)
    first = store.close(marker, "terminal_success", closer="winner",
                        evidence={"artifacts": artifacts}, attempt_supersession=True)
    checks["terminal.first_close_transitioned"] = first["transitioned"]
    checks["terminal.first_close_release_count"] = first["release_count"]
    receipt = Path(first["closed_path"])
    terminal = receipt.read_bytes()
    checked = store.receipts()[0]
    checks["terminal.recorded_outcome"] = checked["outcome"]
    checks["terminal.recorded_prompt_id"] = checked["prompt_id"]
    checks["terminal.transition_count"] = len(checked["transitions"])
    checks["terminal.predecessor_outcome"] = checked["supersedes"]["outcome"]
    assert checked["outcome"] == "terminal_success" and checked["prompt_id"] == "pid-9"
    assert checked["release_count"] == 1 and len(checked["transitions"]) == 1
    with pytest.raises(AttemptAlreadyTerminal) as bogus_terminal:
        store.close(marker, "terminal_error", closer="x", attempt_supersession=True)
    checks["terminal.refusal_code"] = bogus_terminal.value.code
    assert receipt.read_bytes() == terminal, "a finished attempt is never rewritten"
    again = store.close(marker, "terminal_success", closer="y",
                        evidence={"artifacts": artifacts}, attempt_supersession=True)
    checks["terminal.same_outcome_is_idempotent"] = (
        again["released"] is False and again["already_released"] is True
        and again["transitioned"] is False)
    checks["terminal.same_outcome_release_count"] = again["release_count"]
    assert receipt.read_bytes() == terminal
    assert len(store.receipts()) == 1
    assert store.receipts()[0]["outcome"] == "terminal_success"
    assert store.receipts()[0]["release_count"] == 1

    # (d) THROUGH THE ADAPTER: an unsafe replacement posts nothing at all.
    rig = make_rig(tmp_path / "d")
    rig.transport.history_map["pid-1"] = history_success("pid-1")
    out = rig.adapter.run(make_spec(stage_timeout_s=2.0))
    assert out.status == "validated"
    store = _store(rig.adapter)
    receipt = Path(store.receipts()[0]["path"])
    adapter_before = receipt.read_bytes()
    submits_before = rig.transport.submit_calls
    rig.adapter.reservation["prompt_id"] = "pid-foreign"
    with pytest.raises(AttemptAlreadyTerminal) as adapter_refusal:
        rig.adapter.close_reservation("terminal_error")
    checks["adapter.refusal_code"] = adapter_refusal.value.code
    checks["adapter.no_new_post"] = rig.transport.submit_calls
    checks["adapter.refusal_surfaced"] = "receipt_supersession_refused" in [
        e.get("action") for e in rig.adapter.reservation_events]
    assert submits_before == 1 and rig.transport.submit_calls == 1
    assert receipt.read_bytes() == adapter_before
    checks["no_post_anywhere_in_this_row"] = 1
    print("R28-C4 observed:", checks)


def test_r28_terminal_receipt_transition_race_is_idempotent(tmp_path):
    """Two LIVE closers on one slot: one transition wins, the loser keeps its bytes."""
    import threading

    from mf_comfy.errors import AttemptAlreadyTerminal
    from mf_comfy.lease import PromptReservations

    store, epoch, fields, release = _r28_slot(tmp_path / "race", "attempt-race")
    # a SECOND, unrelated attempt in the SAME ledger: its rights must survive untouched
    _, _, _, other_release = _r28_slot(tmp_path / "race", "attempt-other")
    other_receipt = Path(other_release["closed_path"])
    other_before = other_receipt.read_bytes()

    def _receipt_of(attempt: str) -> dict:
        return next(r for r in store.receipts() if r.get("attempt_id") == attempt)

    marker = _r28_retry_marker(store, epoch, "attempt-race", fields)
    staged = Path(tmp_path) / "race" / "raced.png"
    staged.write_bytes(b"PNG!")
    artifacts = [{"filename": "raced.png", "sha256": "e" * 64, "size_bytes": 4,
                  "staged_path": str(staged)}]
    barrier = threading.Barrier(2)
    results: list = []
    checks: dict = {}

    def closer(label, member):
        member.wait(30)
        try:
            res = store.close(marker, "terminal_success", closer=label,
                              evidence={"artifacts": [dict(a) for a in artifacts]},
                              attempt_supersession=True)
        except BaseException as exc:  # a refusal IS the measured outcome here
            res = {"refused": {"code": getattr(exc, "code", type(exc).__name__),
                               "message": str(exc)}}
        results.append({"closer": label, "result": res})

    threads = [threading.Thread(target=closer, args=(f"closer-{i}", barrier), name=f"r28-{i}")
               for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    joined = all(not t.is_alive() for t in threads)
    winners = [r for r in results if (r["result"].get("transitioned") is True)]
    losers = [r for r in results if not (r["result"].get("transitioned") is True)]
    record = _receipt_of("attempt-race")
    receipt = Path(record["path"])
    checks["race.both_closers_joined"] = len(results)
    checks["race.threads_finished"] = joined
    checks["race.transitions_won"] = len(winners)
    checks["race.loser_disposition"] = [r["result"].get("already_released", False)
                                        for r in losers]
    checks["race.loser_refusals"] = [r["result"].get("refused", {}).get("code")
                                     for r in losers]
    checks["race.receipt_outcome"] = record["outcome"]
    checks["race.receipt_prompt_id"] = record["prompt_id"]
    checks["race.release_count"] = record["release_count"]
    checks["race.transition_count"] = len(record.get("transitions") or [])
    checks["race.transition_closer"] = (record.get("transitions") or [{}])[0].get("by")
    checks["race.artifact_bytes_intact"] = staged.read_bytes()
    checks["race.receipt_count"] = len(store.receipts())
    checks["race.other_attempt_untouched"] = other_receipt.read_bytes() == other_before
    checks["race.other_attempt_outcome"] = _receipt_of("attempt-other")["outcome"]
    print("R28-C5 observed:", checks)
    assert joined and len(results) == 2, "both closers must be real, bounded threads"
    assert len(winners) == 1, "exactly ONE closer may perform the transition"
    assert record["outcome"] == "terminal_success" and record["prompt_id"] == "pid-9"
    assert record["release_count"] == 1 and len(record["transitions"]) == 1
    assert record["transitions"][0]["by"] == winners[0]["closer"]
    assert staged.read_bytes() == b"PNG!", "the winner's artifact bytes stay intact"
    assert len(store.receipts()) == 2, "one receipt per slot: the other attempt is separate"
    assert other_receipt.read_bytes() == other_before, "another attempt keeps its rights"
    assert _receipt_of("attempt-other")["outcome"] == "not_accepted"

    # a DIFFERENT outcome for an already-terminal slot is a typed refusal, not an edit
    terminal = receipt.read_bytes()
    with pytest.raises(AttemptAlreadyTerminal):
        store.close(marker, "terminal_error", closer="late", attempt_supersession=True)
    assert receipt.read_bytes() == terminal
    assert _receipt_of("attempt-race")["release_count"] == 1
    assert PromptReservations(Path(tmp_path) / "race" / "res").receipts()[0][
        "release_count"] == 1
