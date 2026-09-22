"""F01-F05 correction suite (adapter job-management contract).

Registered rows (packet MF-V1-COMFY correction round), one test per row:

    F01  test_inflight_submit_cannot_be_released_by_other_caller
    F02  test_adoption_requires_exact_attempt_stage_workflow_owner
    F03  test_epoch_change_with_success_history_is_rejected
    F04  test_corrupt_reservation_blocks_gate
    F05  test_output_contract_ignores_input_preview_and_requires_terminal_output

Each row's reviewer reproduction (READ/root-probes/comfy/reviewer_micro_results.json,
READ/root-probes/input-only-result.json) is encoded as the first phase of its test.

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
    field is varied on its own here; every variant must be refused and must not
    resubmit, and two claimants for one identity must fail closed.
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
        with pytest.raises(UnresolvedReservation):
            stranger.adapter.run(_new_spec(**spec_kw), stage_input)
        assert stranger.adapter.adopted_prompt_id is None, \
            f"a foreign {label} must never adopt this prompt"
        assert rig.transport.submit_calls == 1, \
            f"a foreign {label} must not resubmit while the prompt runs"
        assert _markers(store) != [], \
            f"the refusal for a foreign {label} must keep the reservation"

        # (ii) the prompt finishes while the stranger is looking: it must never
        #      receive that output, and must never adopt it -- it may only run its
        #      own prompt (a different prompt_id), or fail unproven.
        rig.transport.queue_state["queue_running"] = []
        rig.transport.history_map["pid-1"] = history_success("pid-1", "first_image.png")
        other = make_rig(root, transport=rig.transport, write_epoch=False,
                         owner=override.get("owner", base["owner"]))
        try:
            out = other.adapter.run(_new_spec(**spec_kw), stage_input)
            own_prompt = out.prompt_id
            status = out.status
        except MfComfyError as exc:
            own_prompt = (exc.details or {}).get("prompt_id")
            status = getattr(exc, "code", type(exc).__name__)
        assert other.adapter.adopted_prompt_id is None, \
            f"a foreign {label} must never adopt the completed prompt"
        assert own_prompt != "pid-1", \
            f"a foreign {label} must never continue/report the other work item's prompt"
        assert not list(rig.paths.root.rglob("first_image.png")), \
            f"a foreign {label} must never receive the other work item's output"
        assert rig.transport.submit_calls == 2, "it may only POST its own work item"
        results[label] = {"refused_while_running": "MF_COMFY_UNRESOLVED_RESERVATION",
                          "own_prompt": own_prompt, "status": status,
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
