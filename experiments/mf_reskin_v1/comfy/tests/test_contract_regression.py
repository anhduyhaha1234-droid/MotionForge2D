"""F01-F05 correction suite (adapter job-management contract).

Registered rows (packet MF-V1-COMFY correction round), one test per row:

    F01  test_inflight_submit_cannot_be_released_by_other_caller
    F02  test_adoption_requires_exact_attempt_stage_workflow_owner
    F03  test_epoch_change_with_success_history_is_rejected
    F04  test_corrupt_reservation_blocks_gate
    F05  test_output_contract_ignores_input_preview_and_requires_terminal_output

Round c2 rows (graph pin + durable output contract + identity-bound resubmit):

    F02-a  test_f02_graph_pin_is_compared_before_adoption_or_submit
    F02-b  test_f02_independent_new_request_after_valid_terminal
    F05    test_f05_output_contract_is_durable_across_restart

Each row's reviewer reproduction (READ/root-probes/comfy/reviewer_micro_results.json,
READ/root-probes/input-only-result.json) is encoded as the first phase of its test.
The c2 rows encode `REVIEW_ROOT/evidence/valid-pin-probes/` (f02a, f02b, f05).

NEGATIVE CONTROL. This file has to fail on the pre-fix preimage. Every access to a
new contract field is therefore wrapped in a helper that raises `AssertionError`
(never an import/collection error), so the pre-fix run is a clean RED with a
row-by-row reason. The pre-fix run is kept in
`COMFY/raw/negative_control_prefix.txt`, the fixed run in `COMFY/raw/micro_tests.txt`.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from fake_transport import (history_success, light_graph, make_rig, make_spec,
                            queue_item)
from mf_comfy.contract import StageInput
from mf_comfy.errors import ArtifactMissing, MfComfyError, UnresolvedReservation
from mf_comfy.gpugate import GpuStageGate
from mf_comfy.lease import PromptReservations

try:  # present only on the fixed tree
    from mf_comfy.errors import CorruptReservation
except ImportError:  # pragma: no cover - pre-fix preimage only

    class CorruptReservation(MfComfyError):  # type: ignore[no-redef]
        code = "MF_COMFY_CORRUPT_RESERVATION"


# --------------------------------------------------------------- thin shims
def _new_spec(**kw) -> object:
    """RunSpec carrying the declared-identity / terminal-output contract fields.

    On the pre-fix tree the constructor rejects the new keywords, so the row
    fails with an assertion naming the missing contract instead of erroring.
    """
    try:
        return make_spec(**kw)
    except TypeError as exc:  # pragma: no cover - pre-fix preimage only
        raise AssertionError(
            f"RunSpec does not declare the F01-F05 contract fields: {exc}") from exc


def _store(adapter) -> PromptReservations:
    store = getattr(adapter, "reservations", None)
    assert store is not None, "adapter exposes no durable reservation ledger"
    return store


def _markers(store) -> list:
    return sorted(store.root.glob(f"*{store.SUFFIX}"))


def _record(store, path) -> dict:
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(rec, dict) and rec.get("key"), f"not a reservation record: {path}"
    return rec


def _simulate_process_exit(rig) -> None:
    """Model the death of the attempt's process (lock + lease die with it)."""
    if rig.gate is not None and rig.gate.held:
        rig.gate.release()
    rig.lease.release()


def _assert_still_blocking(root: Path, stage_label: str) -> GpuStageGate:
    """A fresh caller (no lock, no reconcile callback) must be refused."""
    gate = GpuStageGate(root / "gpu_stage.lock", timeout_s=0.0)
    try:
        with pytest.raises(UnresolvedReservation) as exc:
            gate.acquire(stage_label=stage_label)
        assert exc.value.code == "MF_COMFY_UNRESOLVED_RESERVATION"
    finally:
        gate.release()
    assert gate.held is False, "caller-2 must not hold the gate"
    return gate


# =========================================================== F01 (P1)
def test_inflight_submit_cannot_be_released_by_other_caller(tmp_path):
    """A POST that is in flight is not "no prompt on the server".

    Reviewer reproduction (`false_release_during_live_submit`): caller-2 released
    caller-1's reservation while caller-1's POST was mid-flight, then took the
    gate (`third_gate_acquired_while_first_prompt_running: true`). The two live
    callers rendezvous at the real POST here, with a barrier, and caller-2 must
    not be able to delete the marker.
    """
    root = tmp_path / "rig"
    rig = make_rig(root, owner="owner-1")
    spec = _new_spec(attempt_id="att-f01", stage_id="stage-f01", workflow_id="wf-f01",
                     owner="owner-1", stage_timeout_s=2.0)

    entered, barrier = threading.Event(), threading.Event()

    def hook(client_id):  # at the top of the transport POST
        entered.set()
        barrier.wait(20)

    rig.transport.submit_hook = hook
    errors: list = []

    def caller1() -> None:
        try:
            rig.adapter.run(spec)
        except BaseException as exc:  # noqa: BLE001 - recorded, not swallowed
            errors.append(exc)

    thread = threading.Thread(target=caller1, daemon=True)
    thread.start()
    assert entered.wait(20), "caller-1 never reached its POST"

    # --- phase 1: the POST is in flight -> durable marker present, caller-2 refused
    store = _store(rig.adapter)
    markers = _markers(store)
    assert len(markers) == 1, f"the reservation must be durable before the POST: {markers}"
    marker = markers[0]
    rec = _record(store, marker)
    assert rec.get("submit_state") == "inflight", \
        "the durable record must prove a submit is on the wire"
    assert rec.get("prompt_id") is None

    caller2 = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-2")
    caller2_spec = _new_spec(attempt_id="att-f01-other", stage_id="stage-f01-other",
                             workflow_id="wf-f01-other", owner="owner-2",
                             graph=light_graph(), stage_timeout_s=2.0)
    with pytest.raises(UnresolvedReservation):
        caller2.adapter.run(caller2_spec)
    assert rig.transport.submit_calls == 1, "caller-2 must not POST while a submit is in flight"
    assert marker.exists(), "an in-flight reservation must never be deleted by another caller"
    assert _record(store, marker).get("state") == "unresolved"

    # --- phase 2: the POST is accepted; the prompt is now really on the server
    # caller-2 shares this transport and `make_rig` re-points its clock advancer,
    # so give caller-1's own clock back before letting its POST complete.
    rig.transport.time_advancer = rig.clock.advance
    rig.transport.queue_state["queue_running"] = [queue_item("pid-1", rig.adapter.client_id)]
    barrier.set()
    thread.join(20)
    assert not thread.is_alive()
    assert rig.transport.submit_calls == 1
    assert marker.exists(), "an accepted prompt keeps its reservation unresolved"
    assert _record(store, marker).get("prompt_id") == "pid-1"
    assert rig.adapter.reservation_released is False

    # --- phase 3: caller-1's process exits -> the outcome is still unprovable
    _simulate_process_exit(rig)
    assert marker.exists()
    _assert_still_blocking(root, "caller-3-after-accepted")

    # --- phase 4: same-identity resume continues the SAME prompt, never a new POST
    rig.transport.queue_state["queue_running"] = []
    rig.transport.history_map["pid-1"] = history_success("pid-1", "once_00001_.png")
    same = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-1")
    out = same.adapter.run(_new_spec(attempt_id="att-f01", stage_id="stage-f01",
                                     workflow_id="wf-f01", owner="owner-1",
                                     stage_timeout_s=2.0))
    assert rig.transport.submit_calls == 1, "a resume must never issue a second POST"
    assert out.prompt_id == "pid-1"
    assert out.adopted is True
    assert out.status == "validated"
    assert out.artifacts[0]["filename"] == "once_00001_.png"
    assert _markers(store) == [], "the adopted prompt released its reservation exactly once"
    assert len([r for r in store.receipts() if r.get("prompt_id") == "pid-1"]) == 1

    # caller-1 itself: nothing was silently swallowed
    assert all(not isinstance(e, AssertionError) for e in errors), errors


def test_f01_lost_ack_and_dead_opener_stay_blocking(tmp_path):
    """Lost ACK: marker kept. Dead opener: kept while a POST may have been on the wire.

    Discharge criterion of F01: only a record that PROVES no submit ever started
    may be released; anything else stays unresolved and blocking.
    """
    root = tmp_path / "rig"
    rig = make_rig(root, owner="owner-la")
    rig.transport.submit_exception = MfComfyError("connection reset during POST")
    with pytest.raises(MfComfyError):
        rig.adapter.run(_new_spec(attempt_id="att-la", stage_id="stage-la",
                                  workflow_id="wf-la", owner="owner-la",
                                  stage_timeout_s=1.0))
    assert rig.transport.submit_calls == 1

    store = _store(rig.adapter)
    markers = _markers(store)
    assert len(markers) == 1
    rec = _record(store, markers[0])
    assert rec.get("submit_state") == "ambiguous", \
        "a POST whose acknowledgement was lost must be recorded as ambiguous"
    assert rec.get("prompt_id") is None

    _simulate_process_exit(rig)
    _assert_still_blocking(root, "caller-2-lost-ack")
    assert markers[0].exists(), "a lost ACK is never released by absence of evidence"

    # a provably-dead opener does NOT make an in-flight/ambiguous POST releasable
    dead = json.loads(markers[0].read_text(encoding="utf-8"))
    dead["submit_owner_pid"] = 4294967290
    markers[0].write_text(json.dumps(dead, indent=1, sort_keys=True), encoding="utf-8")
    _assert_still_blocking(root, "caller-3-dead-opener")

    # ...but "opening" + dead opener IS provable: the POST never started
    proves = json.loads(markers[0].read_text(encoding="utf-8"))
    proves["submit_state"] = "opening"
    proves["submit_started_at"] = None
    markers[0].write_text(json.dumps(proves, indent=1, sort_keys=True), encoding="utf-8")
    fresh = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-la")
    fresh.transport.submit_exception = None
    # the retried POST is accepted, so the attempt ends unresolved (not proven done)
    rig.transport.queue_state["queue_running"] = [queue_item("pid-2", fresh.adapter.client_id)]
    out = fresh.adapter.run(_new_spec(attempt_id="att-la", stage_id="stage-la",
                                      workflow_id="wf-la", owner="owner-la",
                                      stage_timeout_s=1.0))
    assert out.status == "unresolved", out.notes
    assert rig.transport.submit_calls == 2, \
        "a provably-never-started POST may be retried on the same attempt"
    released = [r for r in store.receipts() if r.get("outcome") == "not_accepted"]
    assert len(released) == 1, "the phantom reservation is released exactly once"


# =========================================================== F02 (P1)
def test_adoption_requires_exact_attempt_stage_workflow_owner(tmp_path):
    """Adoption is bound to durable identity, not to "some prompt of this boot".

    Reviewer reproduction (`foreign_attempt_adoption`): a video-owner /
    video-stage / unrelated-workflow caller received the image-attempt /
    image-owner output with `status: validated, adopted: true`. Each identity
    field is varied on its own here; every variant must be refused, must not
    adopt, and — in BOTH the running state and after the old prompt has become a
    success (`valid-pin-probes/f02b`) — must never silently POST a second prompt
    for the same work item. Two claimants for one identity must fail closed.

    CORRECTED CONTRACT (c2). This test used to assert `submit_calls == 2` for the
    completed case ("it may only POST its own work item"). That encoded the wrong
    contract: an unresolved reservation that belongs to the same work item is not
    a licence to open a new reservation and POST once the gate's reconcile hook
    has proved the old prompt terminal. Total POST for the conflicting case is
    exactly 1; the independent-new-request positive control lives in
    `test_f02_independent_new_request_after_valid_terminal`.
    """
    base = dict(attempt_id="att-f02", stage_id="stage-image", workflow_id="wf-image",
                owner="image-owner")
    variants = {
        "attempt": {"attempt_id": "att-f02-other"},
        "owner": {"owner": "video-owner"},
        "stage": {"stage_id": "video-stage"},
        "workflow": {"workflow_id": "unrelated-workflow"},
        "graph": {"graph": light_graph(seed=7)},
        "input": {"source_sha256": "0" * 64},
    }

    results: dict = {}
    for label, override in variants.items():
        root = tmp_path / f"case-{label}"
        rig = make_rig(root, owner=base["owner"])
        rig.transport.queue_state["queue_running"] = [queue_item("pid-1", rig.adapter.client_id)]
        first = rig.adapter.run(_new_spec(**base, stage_timeout_s=1.0))
        assert first.status == "unresolved", first.notes
        assert first.prompt_id == "pid-1"
        _simulate_process_exit(rig)
        store = _store(rig.adapter)

        spec_kw = {k: v for k, v in {**base, **override}.items() if k != "source_sha256"}
        spec_kw.setdefault("graph", light_graph())
        spec_kw.setdefault("stage_timeout_s", 1.0)
        stage_input = None
        if override.get("source_sha256"):
            stage_input = StageInput(stage_id=spec_kw["stage_id"],
                                     source_sha256=override["source_sha256"])

        # (i) the prompt is STILL RUNNING: a foreign identity must be refused and
        #     must not POST anything at all.
        stranger = make_rig(root, transport=rig.transport, write_epoch=False,
                            owner=override.get("owner", base["owner"]))
        with pytest.raises(MfComfyError) as exc_running:
            stranger.adapter.run(_new_spec(**spec_kw), stage_input)
        assert getattr(exc_running.value, "code", "") in (
            "MF_COMFY_UNRESOLVED_RESERVATION", "MF_COMFY_RESERVATION_CONFLICT"), \
            f"a foreign {label} must be refused with a typed code, got {exc_running.value!r}"
        assert stranger.adapter.adopted_prompt_id is None, \
            f"a foreign {label} must never adopt this prompt"
        assert rig.transport.submit_calls == 1, \
            f"a foreign {label} must not resubmit while the prompt runs"
        assert _markers(store) != [], \
            f"the refusal for a foreign {label} must keep the reservation"

        # (ii) the prompt finishes while the stranger is looking (independent
        #      reviewer probe `valid-pin-probes/f02b`): the old marker may NOT be
        #      reconciled free and then re-submitted. Measured on the pre-fix bytes:
        #      the gate reconcile hook cleared the marker, POST pid-2 followed and
        #      the attempt ended `AmbiguousAfterSubmit` with total POST=2.
        #      Required: a typed refusal, no output of the other work item, and NO
        #      additional POST.
        rig.transport.queue_state["queue_running"] = []
        rig.transport.history_map["pid-1"] = history_success("pid-1", "first_image.png")
        other = make_rig(root, transport=rig.transport, write_epoch=False,
                         owner=override.get("owner", base["owner"]))
        with pytest.raises(MfComfyError) as exc_done:
            other.adapter.run(_new_spec(**spec_kw), stage_input)
        status = getattr(exc_done.value, "code", type(exc_done.value).__name__)
        assert status in ("MF_COMFY_UNRESOLVED_RESERVATION",
                          "MF_COMFY_RESERVATION_CONFLICT"), \
            f"a foreign {label} must be refused with a typed code, got {exc_done.value!r}"
        assert other.adapter.adopted_prompt_id is None, \
            f"a foreign {label} must never adopt the completed prompt"
        assert not list(rig.paths.root.rglob("first_image.png")), \
            f"a foreign {label} must never receive the other work item's output"
        assert rig.transport.submit_calls == 1, (
            f"a foreign {label} must never silently POST a second prompt for this work "
            "item: the old prompt reaching a terminal state is not a licence to resubmit "
            "(the pre-fix bytes measured total POST=2 here)")
        assert _markers(store) != [], \
            f"the conflicting {label} claim must leave the reservation blocking"
        results[label] = {"refused_while_running": "MF_COMFY_RESERVATION_CONFLICT",
                          "refused_when_completed": status,
                          "adopted": other.adapter.adopted_prompt_id,
                          "submit_calls": rig.transport.submit_calls}

    # --- same identity: adopt exactly one prompt, exactly one output file
    root = tmp_path / "case-exact"
    rig = make_rig(root, owner=base["owner"])
    rig.transport.queue_state["queue_running"] = [queue_item("pid-1", rig.adapter.client_id)]
    first = rig.adapter.run(_new_spec(**base, stage_timeout_s=1.0))
    assert first.status == "unresolved"
    _simulate_process_exit(rig)
    rig.transport.queue_state["queue_running"] = []
    rig.transport.history_map["pid-1"] = history_success("pid-1", "first_image.png")

    # two claimants for one identity: fail closed, never pick one
    store = _store(rig.adapter)
    marker = _markers(store)[0]
    dup = marker.with_name("duplicate-claimant__" + marker.name)
    dup.write_bytes(marker.read_bytes())
    same = make_rig(root, transport=rig.transport, write_epoch=False, owner=base["owner"])
    with pytest.raises(MfComfyError) as exc:
        same.adapter.run(_new_spec(**base, stage_timeout_s=1.0))
    assert getattr(exc.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", \
        f"ambiguous adoption must fail closed, got {exc.value!r}"
    assert not list(rig.paths.root.rglob("first_image.png"))
    dup.unlink()

    resumed = make_rig(root, transport=rig.transport, write_epoch=False, owner=base["owner"])
    out = resumed.adapter.run(_new_spec(**base, stage_timeout_s=1.0))
    assert out.adopted is True and out.prompt_id == "pid-1"
    assert out.status == "validated"
    assert [a["filename"] for a in out.artifacts] == ["first_image.png"]
    assert rig.transport.submit_calls == 1, "adoption must never POST again"
    assert results


# =========================================================== F03 (P1)
def test_epoch_change_with_success_history_is_rejected(tmp_path):
    """A success entry from another boot identity is never consumed.

    Reviewer reproduction (`epoch_changed_with_history`): the boot identity
    changed while `/history` held a success, and the adapter still validated
    `foreign_boot.png`. Both the wait path and the reconcile path are covered,
    and the identity is re-checked immediately before acceptance.
    """
    # --- wait path
    root = tmp_path / "wait"
    rig = make_rig(root, owner="owner-f03")
    rig.transport.history_map["pid-1"] = history_success("pid-1", "foreign_boot.png")
    rewritten: list = []

    def rewrite_epoch(_n: int) -> None:
        if not rewritten:  # the server boots again while we are waiting
            rewritten.append(rig.epoch.write("http://127.0.0.1:8199", "fake-0.0"))

    rig.transport.drain_hooks = [rewrite_epoch]
    with pytest.raises(MfComfyError) as exc:
        rig.adapter.run(_new_spec(attempt_id="att-f03", stage_id="stage-f03",
                                  workflow_id="wf-f03", owner="owner-f03",
                                  stage_timeout_s=3.0))
    assert exc.value.code == "MF_COMFY_SERVER_EPOCH_CHANGED", exc.value
    assert rewritten and rewritten[0]["instance_id"] != rig.rec["instance_id"]
    assert not list(rig.paths.root.rglob("*.png")), \
        "a foreign boot's output must never be staged"

    # --- reconcile path: the history read races during the wait, the boot changes,
    #     and the reconcile read finds the success. It must NOT become "completed".
    root2 = tmp_path / "reconcile"
    rig2 = make_rig(root2, owner="owner-f03")
    rig2.transport.history_map["pid-1"] = history_success("pid-1", "foreign_boot.png")
    rig2.transport.history_fail_calls = 6
    rewritten2: list = []

    def rewrite_epoch2(_n: int) -> None:
        if not rewritten2:
            rewritten2.append(rig2.epoch.write("http://127.0.0.1:8199", "fake-0.0"))

    rig2.transport.drain_hooks = [rewrite_epoch2]
    with pytest.raises(MfComfyError) as exc2:
        rig2.adapter.run(_new_spec(attempt_id="att-f03", stage_id="stage-f03",
                                   workflow_id="wf-f03", owner="owner-f03",
                                   stage_timeout_s=3.0))
    assert exc2.value.code in ("MF_COMFY_SERVER_EPOCH_CHANGED",
                               "MF_COMFY_AMBIGUOUS_AFTER_SUBMIT"), exc2.value
    assert not list(rig2.paths.root.rglob("*.png")), \
        "the reconcile path must not stage a foreign boot's output either"


# =========================================================== F04 (P1)
def test_corrupt_reservation_blocks_gate(tmp_path):
    """A malformed marker is unknown, not absent: the gate must fail closed.

    Reviewer reproduction (`unreadable_marker`): `unresolved: []` while the gate
    was acquired and the queue was running. The marker is evidence and must
    survive the refusal untouched.
    """
    root = tmp_path / "rig"
    rig = make_rig(root, owner="owner-f04")
    store = _store(rig.adapter)
    truncated = store.root / "truncated__attempt-f04.reservation.json"
    truncated.write_bytes(b'{"schema": "mf.comfy.prompt_reservation/1", "key": "trunc')
    malformed = store.root / "malformed__attempt-f04.reservation.json"
    malformed.write_text(json.dumps({"hello": "not a reservation"}), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in (truncated, malformed)}

    gate = GpuStageGate(root / "gpu_stage.lock", timeout_s=0.0)
    with pytest.raises(MfComfyError) as exc:
        gate.acquire(stage_label="caller-2")
    assert getattr(exc.value, "code", "") == "MF_COMFY_CORRUPT_RESERVATION", \
        f"a corrupt marker must be a typed refusal, got {exc.value!r}"
    assert gate.held is False, "the gate must not be acquired on corrupt state"
    gate.release()

    for path in (truncated, malformed):
        assert path.exists(), "a corrupt marker is evidence and must not be deleted"
        assert path.read_bytes() == before[path.name], "a corrupt marker must not be rewritten"

    # the adapter must not submit either, with or without a gate
    caller = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-f04")
    with pytest.raises(MfComfyError):
        caller.adapter.run(_new_spec(attempt_id="att-f04", stage_id="stage-f04",
                                     workflow_id="wf-f04", owner="owner-f04"))
    assert rig.transport.submit_calls == 0, "a corrupt ledger must never submit"
    assert caller.adapter.reservation is None
    assert truncated.exists() and malformed.exists()

    # a healthy ledger is still readable: corruption is not a blanket block
    truncated.unlink()
    malformed.unlink()
    ok = GpuStageGate(root / "gpu_stage.lock", timeout_s=0.0)
    try:
        ok.acquire(stage_label="caller-3")
        assert ok.held is True
    finally:
        ok.release()


# =========================================================== F05 (P1)
def test_output_contract_ignores_input_preview_and_requires_terminal_output(tmp_path):
    """Only a declared terminal output is a product.

    Reviewer reproduction (`root-probes/input-only-result.json`): a history entry
    whose only artifact is `type: input, source.png` returned `status: validated`
    under the runner that widened `allowed_types`. And a real VACE success was
    rejected because the adapter picked the input preview node.
    """
    declaring = {"terminal_outputs": {"9": {"kind": "images", "media_type": "image"}}}

    # (1) input preview beside a valid terminal output -> only the terminal is taken
    rig = make_rig(tmp_path / "both")
    entry = history_success("pid-1", "product.png")
    entry["outputs"]["5"] = {"images": [{"filename": "source.png", "subfolder": "",
                                         "type": "input"}]}
    rig.transport.history_map["pid-1"] = entry
    out = rig.adapter.run(_new_spec(**declaring))
    assert out.status == "validated"
    assert [a["filename"] for a in out.artifacts] == ["product.png"]
    assert [a["server_type"] for a in out.artifacts] == ["output"]
    assert not (rig.paths.root / "source.png").exists(), \
        "an input preview is not a product and must not be staged"

    # (2) input-ONLY -> fail, even for a caller that widened allowed_types
    rig2 = make_rig(tmp_path / "input_only")
    entry2 = history_success("pid-1", "source.png")
    entry2["outputs"] = {"9": {"images": [{"filename": "source.png", "subfolder": "",
                                           "type": "input"}]}}
    rig2.transport.history_map["pid-1"] = entry2
    with pytest.raises(ArtifactMissing):
        rig2.adapter.run(_new_spec(allowed_types=("output", "input"), **declaring))
    assert not list(rig2.paths.root.rglob("*.png")), "input-only must not produce a product"

    # (3) wrong node (nothing on the declared terminal node) -> fail
    rig3 = make_rig(tmp_path / "wrong_node")
    entry3 = history_success("pid-1", "elsewhere.png")
    entry3["outputs"] = {"8": {"images": [{"filename": "elsewhere.png", "subfolder": "",
                                           "type": "output"}]}}
    rig3.transport.history_map["pid-1"] = entry3
    with pytest.raises(ArtifactMissing):
        rig3.adapter.run(_new_spec(**declaring))
    assert not list(rig3.paths.root.rglob("*.png"))

    # (4) wrong media type for the declared node -> fail
    rig4 = make_rig(tmp_path / "wrong_media")
    entry4 = history_success("pid-1", "product.png")
    entry4["outputs"]["9"] = {"videos": [{"filename": "product.mp4", "subfolder": "",
                                          "type": "output"}]}
    rig4.transport.history_map["pid-1"] = entry4
    with pytest.raises(ArtifactMissing):
        rig4.adapter.run(_new_spec(**declaring))

    # (5) no explicit declaration: the graph's own terminal node is the declaration
    rig5 = make_rig(tmp_path / "graph_declared")
    rig5.transport.history_map["pid-1"] = history_success("pid-1", "from_graph.png")
    out5 = rig5.adapter.run(_new_spec())
    assert out5.status == "validated"
    assert [a["filename"] for a in out5.artifacts] == ["from_graph.png"]

    # (6) lost-ACK / restart keep the SAME contract: an adopted prompt is validated
    #     against the same declaration, and an input-only adopted entry still fails
    root6 = tmp_path / "adopted"
    rig6 = make_rig(root6, owner="owner-f05")
    rig6.transport.queue_state["queue_running"] = [queue_item("pid-1", rig6.adapter.client_id)]
    first = rig6.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                       workflow_id="wf-f05", owner="owner-f05",
                                       stage_timeout_s=1.0, **declaring))
    assert first.status == "unresolved"
    _simulate_process_exit(rig6)
    rig6.transport.queue_state["queue_running"] = []
    bad = history_success("pid-1", "source.png")
    bad["outputs"] = {"9": {"images": [{"filename": "source.png", "subfolder": "",
                                        "type": "input"}]}}
    rig6.transport.history_map["pid-1"] = bad
    resumed = make_rig(root6, transport=rig6.transport, write_epoch=False, owner="owner-f05")
    with pytest.raises(ArtifactMissing):
        resumed.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                      workflow_id="wf-f05", owner="owner-f05",
                                      stage_timeout_s=1.0, **declaring))
    assert not list(rig6.paths.root.rglob("*.png")), \
        "the adopted prompt must obey the same output contract"


# =========================================================== F02-a (P1, c2)
def test_f02_graph_pin_is_compared_before_adoption_or_submit(tmp_path):
    """F02-a. A supplied workflow pin is COMPARED with the real graph hash.

    Independent reviewer probe `valid-pin-probes/f02a`: the caller pinned the
    ORIGINAL graph, the job stayed unresolved, the process exited, and only then
    was the graph seed changed to 7 while the OLD pin was kept. On the pre-fix
    bytes `_claim` echoed `spec.workflow_sha256`, so the restart came back
    `validated / adopted=true` and staged `stage/original.png` — the output of the
    OLD graph handed over as the result of the NEW one.

    Required: a typed mismatch (MF_COMFY_WORKFLOW_HASH_MISMATCH) BEFORE adoption,
    staging and POST, and no artifact. Graph changed with NO pin is refused too,
    in both the running and the completed state.
    """
    from mf_comfy.errors import WorkflowPinMismatch
    from mf_comfy.pinning import hash_workflow

    pinned = {"terminal_outputs": {"9": {"kind": "images", "media_type": "image"}}}

    def two_terminal(seed=42):
        g = light_graph(seed=seed)
        g["10"] = dict(g["9"])
        return g

    original, changed = two_terminal(), two_terminal(seed=7)
    base = dict(attempt_id="att-a", stage_id="stage-a", workflow_id="wf-a")

    # (1) a bad pin on the very first attempt never reaches the wire
    rig = make_rig(tmp_path / "bad-pin-first", owner="owner-f02a")
    with pytest.raises(WorkflowPinMismatch):
        rig.adapter.run(_new_spec(**base, owner="owner-f02a", graph=original,
                                  workflow_sha256="0" * 64, **pinned))
    assert rig.transport.submit_calls == 0, "a bad pin must not reach the POST"
    assert _markers(_store(rig.adapter)) == [], "a bad pin must not open a reservation"
    assert not list(rig.paths.root.rglob("*.png"))

    # (2) reviewer probe f02a: correct pin of the ORIGINAL graph, then graph changed
    root2 = tmp_path / "pin-then-change"
    rig2 = make_rig(root2, owner="owner-f02a")
    rig2.transport.queue_state["queue_running"] = [queue_item("pid-1", rig2.adapter.client_id)]
    first = rig2.adapter.run(_new_spec(**base, owner="owner-f02a", graph=original,
                                       workflow_sha256=hash_workflow(original),
                                       stage_timeout_s=1.0, **pinned))
    assert first.status == "unresolved" and first.prompt_id == "pid-1"
    _simulate_process_exit(rig2)
    rig2.transport.queue_state["queue_running"] = []
    rig2.transport.history_map["pid-1"] = history_success("pid-1", "original.png")
    restart = make_rig(root2, transport=rig2.transport, write_epoch=False, owner="owner-f02a")
    with pytest.raises(WorkflowPinMismatch):
        restart.adapter.run(_new_spec(**base, owner="owner-f02a", graph=changed,
                                      workflow_sha256=hash_workflow(original),
                                      stage_timeout_s=1.0, **pinned))
    assert restart.adapter.adopted_prompt_id is None, \
        "the old graph's prompt must never be adopted for the new graph"
    assert rig2.transport.submit_calls == 1, "a mismatching pin must not POST"
    assert not list(rig2.paths.root.rglob("*.png")), "no artifact may be staged"
    assert _markers(_store(rig2.adapter)) != [], "the old reservation stays blocking"

    # (3) positive control: the SAME graph + the SAME pin still adopts exactly once
    rig3 = make_rig(root2, transport=rig2.transport, write_epoch=False, owner="owner-f02a")
    out3 = rig3.adapter.run(_new_spec(**base, owner="owner-f02a", graph=original,
                                      workflow_sha256=hash_workflow(original),
                                      stage_timeout_s=1.0, **pinned))
    assert out3.status == "validated" and out3.adopted is True
    assert [a["filename"] for a in out3.artifacts] == ["original.png"]
    assert rig2.transport.submit_calls == 1, "an honest resume never POSTs again"

    # (4) graph changed with NO pin: running state -> typed refusal, no artifact
    root4 = tmp_path / "changed-no-pin"
    rig4 = make_rig(root4, owner="owner-f02a")
    rig4.transport.queue_state["queue_running"] = [queue_item("pid-1", rig4.adapter.client_id)]
    b = dict(attempt_id="att-b", stage_id="stage-b", workflow_id="wf-b")
    r4 = rig4.adapter.run(_new_spec(**b, owner="owner-f02a", graph=original,
                                    stage_timeout_s=1.0, **pinned))
    assert r4.status == "unresolved" and r4.prompt_id == "pid-1"
    _simulate_process_exit(rig4)
    nopin = make_rig(root4, transport=rig4.transport, write_epoch=False, owner="owner-f02a")
    with pytest.raises(MfComfyError) as exc_nopin:
        nopin.adapter.run(_new_spec(**b, owner="owner-f02a", graph=changed,
                                    stage_timeout_s=1.0, **pinned))
    assert getattr(exc_nopin.value, "code", "") in (
        "MF_COMFY_UNRESOLVED_RESERVATION", "MF_COMFY_RESERVATION_CONFLICT"), exc_nopin.value
    assert rig4.transport.submit_calls == 1 and not list(rig4.paths.root.rglob("*.png"))
    assert nopin.adapter.adopted_prompt_id is None

    # (5) ... and in the COMPLETED state: the old graph's result is never handed over
    rig4.transport.queue_state["queue_running"] = []
    rig4.transport.history_map["pid-1"] = history_success("pid-1", "original.png")
    nopin2 = make_rig(root4, transport=rig4.transport, write_epoch=False, owner="owner-f02a")
    with pytest.raises(MfComfyError) as exc_nopin2:
        nopin2.adapter.run(_new_spec(**b, owner="owner-f02a", graph=changed,
                                     stage_timeout_s=1.0, **pinned))
    assert getattr(exc_nopin2.value, "code", "") in (
        "MF_COMFY_UNRESOLVED_RESERVATION", "MF_COMFY_RESERVATION_CONFLICT"), exc_nopin2.value
    assert rig4.transport.submit_calls == 1, \
        "a changed graph whose prompt completed is not a licence to resubmit"
    assert nopin2.adapter.adopted_prompt_id is None
    assert not list(rig4.paths.root.rglob("*.png"))

    # (6) combined tamper (graph + owner) is refused by the same rule
    combo = make_rig(root4, transport=rig4.transport, write_epoch=False, owner="owner-f02a-x")
    with pytest.raises(MfComfyError) as exc_combo:
        combo.adapter.run(_new_spec(**b, owner="owner-f02a-x", graph=changed,
                                    stage_timeout_s=1.0, **pinned))
    assert getattr(exc_combo.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc_combo.value
    assert combo.adapter.adopted_prompt_id is None
    assert rig4.transport.submit_calls == 1 and not list(rig4.paths.root.rglob("*.png"))

    # (7) read-error case: an unreadable server is not an excuse to resubmit
    rig4.transport.history_fail_calls = 8
    err = make_rig(root4, transport=rig4.transport, write_epoch=False, owner="owner-f02a")
    with pytest.raises(MfComfyError) as exc_err:
        err.adapter.run(_new_spec(**b, owner="owner-f02a", graph=changed,
                                  stage_timeout_s=1.0, **pinned))
    assert getattr(exc_err.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc_err.value
    assert rig4.transport.submit_calls == 1
    assert _store(rig4.adapter).receipts() == [], \
        "a failed server read must never release (or claim) the reservation"
    assert _markers(_store(rig4.adapter)) != []


# =========================================================== F02-b (P1, c2)
def test_f02_independent_new_request_after_valid_terminal(tmp_path):
    """F02-b positive control: the conflict rule does NOT ban subsequent jobs.

    The refusal above applies to a caller that collides with an unresolved
    reservation of the SAME work item. Two other paths must keep working:

      * recovery of the exact same identity -> adopt once, total POST stays 1;
      * a genuinely independent new request -> valid, and it may POST its own
        prompt once the previous work item reached a VALID TERMINAL.
    """
    root = tmp_path / "rig"
    rig = make_rig(root, owner="owner-a")
    rig.transport.queue_state["queue_running"] = [queue_item("pid-1", rig.adapter.client_id)]
    first = rig.adapter.run(_new_spec(attempt_id="att-a", stage_id="stage-a",
                                      workflow_id="wf-a", owner="owner-a",
                                      stage_timeout_s=1.0))
    assert first.status == "unresolved" and first.prompt_id == "pid-1"
    _simulate_process_exit(rig)
    store = _store(rig.adapter)

    # (1) a DIFFERENT work item is a fresh claim: the identity layer does not refuse
    #     it (no conflict), and the F01 gate still blocks because A is unresolved.
    fresh = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-a")
    with pytest.raises(MfComfyError) as exc_fresh:
        fresh.adapter.run(_new_spec(attempt_id="att-b", stage_id="stage-b",
                                    workflow_id="wf-b", owner="owner-a",
                                    stage_timeout_s=1.0))
    assert getattr(exc_fresh.value, "code", "") == "MF_COMFY_UNRESOLVED_RESERVATION", \
        f"a new work item must be blocked by the F01 gate, not by the identity rule: {exc_fresh.value!r}"
    assert rig.transport.submit_calls == 1

    # (2) A reaches a VALID TERMINAL: the same identity adopts its own prompt once.
    rig.transport.queue_state["queue_running"] = []
    rig.transport.history_map["pid-1"] = history_success("pid-1", "a_result.png")
    same = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-a")
    done = same.adapter.run(_new_spec(attempt_id="att-a", stage_id="stage-a",
                                      workflow_id="wf-a", owner="owner-a",
                                      stage_timeout_s=1.0))
    assert done.status == "validated" and done.adopted is True
    assert [a["filename"] for a in done.artifacts] == ["a_result.png"]
    assert rig.transport.submit_calls == 1, "recovery of the same identity never POSTs again"
    assert _markers(store) == [], "a valid terminal released the reservation exactly once"

    # (3) ... and now an independent new request runs and validates its OWN output.
    staged_before = {p.name for p in rig.paths.root.rglob("*.png")}
    rig.transport.history_map["pid-2"] = history_success("pid-2", "b_result.png")
    nxt = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-b")
    out = nxt.adapter.run(_new_spec(attempt_id="att-b", stage_id="stage-b",
                                    workflow_id="wf-b", owner="owner-b",
                                    stage_timeout_s=1.0))
    assert out.status == "validated", out.notes
    assert out.adopted is False and out.prompt_id == "pid-2"
    assert [a["filename"] for a in out.artifacts] == ["b_result.png"]
    assert rig.transport.submit_calls == 2
    assert {p.name for p in rig.paths.root.rglob("*.png")} - staged_before == {"b_result.png"}, \
        "the new request must stage its OWN output and nothing of the previous work item"

    # (4) re-running the SAME stage under a NEW attempt is allowed after the valid
    #     terminal too: the rule bans conflicting concurrent claims, not all
    #     subsequent jobs.
    rig.transport.history_map["pid-3"] = history_success("pid-3", "a_result2.png")
    again = make_rig(root, transport=rig.transport, write_epoch=False, owner="owner-a")
    out2 = again.adapter.run(_new_spec(attempt_id="att-a2", stage_id="stage-a",
                                       workflow_id="wf-a", owner="owner-a",
                                       stage_timeout_s=1.0))
    assert out2.status == "validated", out2.notes
    assert out2.adopted is False and out2.prompt_id == "pid-3"
    assert [a["filename"] for a in out2.artifacts] == ["a_result2.png"]
    assert rig.transport.submit_calls == 3


# =========================================================== F05 (P1, c2)
def test_f05_output_contract_is_durable_across_restart(tmp_path):
    """F05. The FIRST submit's normalized result contract governs every later read.

    Independent reviewer probe `valid-pin-probes/f05`: the graph has two terminal
    nodes (9, 10). The first submit declares node 9 and stays unresolved; the
    restart re-declares node 10 for the same graph/attempt/owner. On the pre-fix
    bytes the adapter adopted pid-1 and staged `different.png` (node 10) — a result
    the first submit never asked for. Required: fail closed, no staging, no POST.
    """
    def two_terminal(seed=42):
        g = light_graph(seed=seed)
        g["10"] = dict(g["9"])
        return g

    def decl(node="9", kind="images", media_type="image"):
        return {"terminal_outputs": {node: {"kind": kind, "media_type": media_type}}}

    def unresolved_run(root, *, attempt, stage, wf, owner, **extra):
        rig = make_rig(root, owner=owner)
        rig.transport.queue_state["queue_running"] = [queue_item("pid-1", rig.adapter.client_id)]
        out = rig.adapter.run(_new_spec(attempt_id=attempt, stage_id=stage, workflow_id=wf,
                                        owner=owner, graph=two_terminal(),
                                        stage_timeout_s=1.0, **extra))
        assert out.status == "unresolved" and out.prompt_id == "pid-1", out.notes
        _simulate_process_exit(rig)
        rig.transport.queue_state["queue_running"] = []
        entry = history_success("pid-1", "original.png")
        entry["outputs"]["10"] = {"images": [{"filename": "different.png",
                                             "subfolder": "", "type": "output"}]}
        rig.transport.history_map["pid-1"] = entry
        return rig

    # (0) unchanged normalized contract: the completed output is adopted exactly once,
    #     read from the node the FIRST submit declared (never from node 10).
    rig0 = unresolved_run(tmp_path / "unchanged", attempt="att-f05", stage="stage-f05",
                          wf="wf-f05", owner="owner-f05", **decl())
    same0 = make_rig(tmp_path / "unchanged", transport=rig0.transport, write_epoch=False,
                     owner="owner-f05")
    out0 = same0.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                       workflow_id="wf-f05", owner="owner-f05",
                                       graph=two_terminal(), stage_timeout_s=1.0, **decl()))
    assert out0.status == "validated" and out0.adopted is True
    assert [a["filename"] for a in out0.artifacts] == ["original.png"], \
        "the first submit's declaration (node 9) must still govern the read"
    assert not (rig0.paths.root / "different.png").exists(), \
        "the re-declared node's artifact must never be staged"
    assert rig0.transport.submit_calls == 1

    # (1) reviewer probe f05: declaration changed across the restart -> fail closed
    rig1 = unresolved_run(tmp_path / "changed-node", attempt="att-f05", stage="stage-f05",
                          wf="wf-f05", owner="owner-f05", **decl("9"))
    other = make_rig(tmp_path / "changed-node", transport=rig1.transport, write_epoch=False,
                     owner="owner-f05")
    with pytest.raises(MfComfyError) as exc1:
        other.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                    workflow_id="wf-f05", owner="owner-f05",
                                    graph=two_terminal(), stage_timeout_s=1.0, **decl("10")))
    assert getattr(exc1.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc1.value
    assert other.adapter.adopted_prompt_id is None, "the re-declared contract must not adopt"
    assert rig1.transport.submit_calls == 1, "a re-declared terminal node must not POST"
    assert not list(rig1.paths.root.rglob("*.png")), \
        "no artifact may be staged for a changed output contract"
    assert _markers(_store(rig1.adapter)) != [], "the changed contract keeps it blocking"

    # (2) single-field tamper: same node, different declared kind -> refused
    kt = make_rig(tmp_path / "changed-node", transport=rig1.transport, write_epoch=False,
                  owner="owner-f05")
    with pytest.raises(MfComfyError) as exc_kt:
        kt.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                 workflow_id="wf-f05", owner="owner-f05",
                                 graph=two_terminal(), stage_timeout_s=1.0,
                                 **decl("9", kind="videos", media_type="video")))
    assert getattr(exc_kt.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc_kt.value
    assert rig1.transport.submit_calls == 1

    # (3) combined tamper (extra node + media type + a different artifact pin) -> refused
    ct = make_rig(tmp_path / "changed-node", transport=rig1.transport, write_epoch=False,
                  owner="owner-f05")
    with pytest.raises(MfComfyError) as exc_ct:
        ct.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                 workflow_id="wf-f05", owner="owner-f05",
                                 graph=two_terminal(), stage_timeout_s=1.0,
                                 terminal_outputs={"9": {"kind": "images", "media_type": "image"},
                                                   "10": {"kind": "videos", "media_type": "video"}},
                                 expected_artifact_hashes={"original.png": "0" * 64}))
    assert getattr(exc_ct.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc_ct.value
    assert rig1.transport.submit_calls == 1 and not list(rig1.paths.root.rglob("*.png"))

    # (4) expected-artifact pins are part of the durable contract too
    pt = make_rig(tmp_path / "changed-node", transport=rig1.transport, write_epoch=False,
                  owner="owner-f05")
    with pytest.raises(MfComfyError) as exc_pt:
        pt.adapter.run(_new_spec(attempt_id="att-f05", stage_id="stage-f05",
                                 workflow_id="wf-f05", owner="owner-f05",
                                 graph=two_terminal(), stage_timeout_s=1.0,
                                 expected_artifact_hashes={"original.png": "1" * 64}, **decl("9")))
    assert getattr(exc_pt.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc_pt.value
    assert rig1.transport.submit_calls == 1

    # (5) fallback declaration (graph terminal nodes) is durable as well: it
    #     resolves to EVERY terminal node of the graph, and the same fallback on a
    #     restart adopts the completed output exactly once.
    rig5 = unresolved_run(tmp_path / "fallback", attempt="att-fb", stage="stage-fb",
                          wf="wf-fb", owner="owner-f05")
    fb = make_rig(tmp_path / "fallback", transport=rig5.transport, write_epoch=False,
                  owner="owner-f05")
    out5 = fb.adapter.run(_new_spec(attempt_id="att-fb", stage_id="stage-fb",
                                    workflow_id="wf-fb", owner="owner-f05",
                                    graph=two_terminal(), stage_timeout_s=1.0))
    assert out5.status == "validated" and out5.adopted is True
    assert sorted(a["filename"] for a in out5.artifacts) == ["different.png", "original.png"], \
        "the fallback declaration covers both graph terminal nodes (9 and 10)"
    assert rig5.transport.submit_calls == 1

    # (6) fallback -> explicit declaration is a CONTRACT CHANGE -> refused
    rig6 = unresolved_run(tmp_path / "fb-then-explicit", attempt="att-fb2", stage="stage-fb2",
                          wf="wf-fb2", owner="owner-f05")
    ex = make_rig(tmp_path / "fb-then-explicit", transport=rig6.transport, write_epoch=False,
                  owner="owner-f05")
    with pytest.raises(MfComfyError) as exc_ex:
        ex.adapter.run(_new_spec(attempt_id="att-fb2", stage_id="stage-fb2",
                                 workflow_id="wf-fb2", owner="owner-f05",
                                 graph=two_terminal(), stage_timeout_s=1.0, **decl("9")))
    assert getattr(exc_ex.value, "code", "") == "MF_COMFY_RESERVATION_CONFLICT", exc_ex.value
    assert rig6.transport.submit_calls == 1 and not list(rig6.paths.root.rglob("*.png"))

    # (7) lost ACK + restart: the recovered prompt is still read under the BOUND
    #     contract, and a changed declaration is still refused afterwards.
    root7 = tmp_path / "lost-ack"
    rig7 = make_rig(root7, owner="owner-f05c", client_id="cid-f05c")
    rig7.transport.submit_exception = MfComfyError("connection reset during POST")
    with pytest.raises(MfComfyError):
        rig7.adapter.run(_new_spec(attempt_id="att-la", stage_id="stage-la",
                                   workflow_id="wf-la", owner="owner-f05c",
                                   graph=two_terminal(), stage_timeout_s=1.0, **decl("9")))
    assert rig7.transport.submit_calls == 1
    store7 = _store(rig7.adapter)
    marker7 = _markers(store7)[0]
    assert _record(store7, marker7).get("submit_state") == "ambiguous"
    assert _record(store7, marker7).get("output_contract", {}).get("nodes"), \
        "the normalized contract must be durable even for a POST whose ACK was lost"
    _simulate_process_exit(rig7)
    rig7.transport.submit_exception = None
    # the server DID accept the prompt: history carries it for this client_id
    rig7.transport.history_map["pid-1"] = history_success("pid-1", "lost_ack.png",
                                                          client_id="cid-f05c")
    found = make_rig(root7, transport=rig7.transport, write_epoch=False,
                     owner="owner-f05c", client_id="cid-f05c")
    out7 = found.adapter.run(_new_spec(attempt_id="att-la", stage_id="stage-la",
                                       workflow_id="wf-la", owner="owner-f05c",
                                       graph=two_terminal(), stage_timeout_s=1.0, **decl("9")))
    assert out7.status == "validated" and out7.adopted is True
    assert [a["filename"] for a in out7.artifacts] == ["lost_ack.png"]
    assert rig7.transport.submit_calls == 1, "the recovered prompt must never be re-POSTed"

    # (8a) a LEGACY record without the durable contract field fails closed
    root8 = tmp_path / "legacy"
    rig8 = unresolved_run(root8, attempt="att-lg", stage="stage-lg", wf="wf-lg",
                          owner="owner-f05d", **decl("9"))
    store8 = _store(rig8.adapter)
    marker8 = _markers(store8)[0]
    legacy = _record(store8, marker8)
    legacy.pop("output_contract", None)
    legacy.pop("output_contract_digest", None)
    marker8.write_text(json.dumps(legacy, indent=1, sort_keys=True), encoding="utf-8")
    lg = make_rig(root8, transport=rig8.transport, write_epoch=False, owner="owner-f05d")
    with pytest.raises(MfComfyError) as exc_lg:
        lg.adapter.run(_new_spec(attempt_id="att-lg", stage_id="stage-lg", workflow_id="wf-lg",
                                 owner="owner-f05d", graph=two_terminal(),
                                 stage_timeout_s=1.0, **decl("9")))
    assert getattr(exc_lg.value, "code", "") in (
        "MF_COMFY_RESERVATION_CONFLICT", "MF_COMFY_CORRUPT_RESERVATION"), exc_lg.value
    assert rig8.transport.submit_calls == 1 and not list(rig8.paths.root.rglob("*.png"))

    # (8b) a matching digest with a CORRUPT contract body fails closed as corrupt
    root9 = tmp_path / "corrupt-contract"
    rig9 = unresolved_run(root9, attempt="att-cc", stage="stage-cc", wf="wf-cc",
                          owner="owner-f05e", **decl("9"))
    store9 = _store(rig9.adapter)
    marker9 = _markers(store9)[0]
    broken = _record(store9, marker9)
    broken["output_contract"] = {"nodes": None}
    marker9.write_text(json.dumps(broken, indent=1, sort_keys=True), encoding="utf-8")
    cc = make_rig(root9, transport=rig9.transport, write_epoch=False, owner="owner-f05e")
    with pytest.raises(MfComfyError) as exc_cc:
        cc.adapter.run(_new_spec(attempt_id="att-cc", stage_id="stage-cc", workflow_id="wf-cc",
                                 owner="owner-f05e", graph=two_terminal(),
                                 stage_timeout_s=1.0, **decl("9")))
    assert getattr(exc_cc.value, "code", "") == "MF_COMFY_CORRUPT_RESERVATION", exc_cc.value
    assert rig9.transport.submit_calls == 1 and not list(rig9.paths.root.rglob("*.png"))

    # (9) direct proof that the BOUND contract governs the read: validate an entry
    #     whose history also carries node 10, while the caller's CURRENT spec
    #     declares node 10. The bound contract (node 9) decides.
    probe = make_rig(tmp_path / "bound-governs", owner="owner-f05x")
    probe.adapter.bound_output_contract = {
        "nodes": {"9": {"kind": "images", "media_type": "image", "server_types": ["output"]}},
        "expected_artifact_pins": {}}
    entry_probe = history_success("pid-x", "original.png")
    entry_probe["outputs"]["10"] = {"images": [{"filename": "different.png",
                                                "subfolder": "", "type": "output"}]}
    arts = probe.adapter.validate_artifacts(entry_probe, _new_spec(**decl("10")))
    assert [a["filename"] for a in arts] == ["original.png"], \
        "the durable contract, not the current spec, decides which node is a product"
    assert not (probe.paths.root / "different.png").exists()
